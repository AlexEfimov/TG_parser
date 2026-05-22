"""
Digest HTTP API routes (P-2 Surface Parity MVP — Wave 1 step 3 commit 3/4).

Four endpoints under ``/api/v1/digests`` per sprint prompt §2:

* ``POST   /api/v1/digests``               — subscribe (idempotent upsert
  per BUG-022 on the ``(owner_id, name)`` natural key; returns
  ``{digest_id, created, changed_fields}`` per Q-OPEN-1).
* ``GET    /api/v1/digests``               — list current user's
  subscriptions with offset/limit pagination (default ``limit=50``, max 200).
* ``GET    /api/v1/digests/{digest_id}``   — single detail, emits
  ``workspace_id`` + ``workspace_name`` via a single workspaces JOIN
  (Q-OPEN-3). Foreign id returns 404-like, NEVER 403 (mirror F4-B).
* ``DELETE /api/v1/digests/{digest_id}``   — HARD DELETE (Q8 digest
  variant). Row is physically removed; the **second** DELETE on the
  same id returns 404 (REST-strict per parent Q-OPEN-8 lock —
  **ASYMMETRIC** vs the watchlist soft-delete 204+204 pattern).

Authentication piggybacks on the existing ``X-API-Key`` dependency
(``resolve_current_user``) — no new auth surface (Q1).

Idempotency-Key HTTP middleware is **not** wired in this commit (lands
in commit 4/4). Service-layer natural-key upsert (commit 1/4) already
guarantees that same-args POST replays collapse to a single row, so
this surface is safe for clients today.

Asymmetries vs the P-1 watchlist surface (sprint prompt §3):

* **Label field**: digests use ``name``, not ``title`` (Q6).
* **DELETE semantics**: hard delete, second→404 (Q8 + parent Q-OPEN-8).
* **No /matches sub-resource**: a digest's "matches" are scheduled
  Telegram sends, not online matches — out of scope per sprint §2.

The cron/timezone pair is **pre-validated at the router layer** (same
pattern as ``mcp_server.subscribe_digest``) so an invalid spec returns
422 *before* the upsert runs and never leaves a half-written row behind.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.idempotency import IdempotencyContext, idempotency_key_check
from tg_parser.api.schemas import (
    DigestCreateRequest,
    DigestListResponse,
    DigestResponse,
    DigestSubscribeResponse,
)
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import WorkspaceNotFound
from tg_parser.domain.models import DigestFormat, DigestSubscription

router = APIRouter(prefix="/api/v1/digests", tags=["Digests"])
logger = structlog.get_logger(__name__)


# ── Internal helpers ────────────────────────────────────────────────────────


def _error(status_code: int, detail: str, error_class: str) -> JSONResponse:
    """Build a Q7-shaped error response.

    ``{"detail": ..., "error_class": ...}`` is the locked HTTP error
    shape for this surface (sprint prompt §3 Q7). Centralised here so
    every endpoint emits an identical body — clients can branch on
    ``error_class`` to distinguish ``WorkspaceNotFound`` (caller
    referenced an unknown / foreign workspace) from ``NotFound``
    (caller referenced an unknown / foreign digest) and
    ``InvalidCron`` (cron/timezone pre-validation rejected the spec)
    without parsing free-form text.
    """
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_class": error_class},
    )


def _digest_to_response(
    sub: DigestSubscription,
    workspace_name: str | None,
) -> DigestResponse:
    """Project a domain ``DigestSubscription`` onto :class:`DigestResponse`.

    Centralises the field mapping (``format`` Enum → string,
    ``workspace_name`` JOIN-injected) so both GET endpoints stay in
    sync.
    """
    return DigestResponse(
        id=sub.id,
        owner_id=sub.owner_id,
        chat_id=sub.chat_id,
        name=sub.name,
        workspace_id=sub.workspace_id,
        workspace_name=workspace_name,
        channel_ids=list(sub.channel_ids),
        cron_expression=sub.cron_expression,
        timezone=sub.timezone,
        format=sub.format.value,
        language=sub.language,
        is_active=sub.is_active,
        last_sent_at=sub.last_sent_at,
        last_digest_cursor=sub.last_digest_cursor,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


async def _resolve_workspace_names(
    subscriptions: list[DigestSubscription],
) -> dict[str, str]:
    """Fetch ``workspaces.name`` for every distinct non-NULL ``workspace_id``.

    Performs at most ``N`` ``WorkspaceRepo.get(...)`` calls where ``N``
    is the count of unique workspace ids on the page — typically 0–5
    for a paginated list (Q-OPEN-3 ``workspace_name`` JOIN). Returns
    a dict keyed by ``workspace_id``. Workspaces that were deleted
    out-of-band (race against ON DELETE SET NULL) silently drop out —
    the row still renders with ``workspace_name=None``.
    """
    distinct_ids: set[str] = {s.workspace_id for s in subscriptions if s.workspace_id is not None}
    if not distinct_ids:
        return {}

    from tg_parser.services.db_context import workspace_repo

    names: dict[str, str] = {}
    async with workspace_repo() as (ws_repo, _db):
        for wid in distinct_ids:
            ws = await ws_repo.get(wid)
            if ws is not None:
                names[wid] = ws.name
    return names


def _validate_cron_timezone(cron_expression: str, timezone: str) -> str | None:
    """Pre-validate the cron expression + timezone pair.

    Mirrors :func:`tg_parser.mcp_server.subscribe_digest` so the HTTP
    surface and the MCP surface reject the same invalid specs with
    parity error messages — invalid cron should never sneak past the
    HTTP boundary and explode later inside
    ``register_digest_subscription``. Returns ``None`` on success or
    a human-readable error string on failure (so the router can wrap
    it into the Q7 JSON shape with ``error_class="InvalidCron"``).

    APScheduler / zoneinfo are import-guarded so test environments that
    strip APScheduler still pass — same fallback shape as the MCP path.
    """
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.debug("digest.cron_prevalidate_skipped", exc_info=True)
        return None

    try:
        CronTrigger.from_crontab(cron_expression, timezone=ZoneInfo(timezone))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        return (
            f"cron/timezone validation failed: invalid cron task spec "
            f"({cron_expression!r} / tz={timezone!r}): {exc}"
        )
    return None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=DigestSubscribeResponse,
    status_code=201,
    summary="Subscribe to a scheduled digest (idempotent upsert)",
)
async def create_digest(
    request: DigestCreateRequest,
    user: CurrentUser = Depends(resolve_current_user),
    idempotency: IdempotencyContext | None = Depends(idempotency_key_check),
):
    """Create (or idempotently upsert) a digest subscription.

    Idempotency contract (BUG-022 + Q-OPEN-1):

    * Same ``(owner_id, name)`` + identical payload → no-op replay;
      response carries ``created=False`` and ``changed_fields=[]``.
    * Same ``(owner_id, name)`` + different mutable args → UPDATE
      the changed columns; response is ``created=False`` with
      ``changed_fields=[<field names>]``.
    * New ``(owner_id, name)`` → INSERT; ``created=True`` and
      ``changed_fields=[]``.

    ENH-9: ``workspace_id`` may reference any workspace the caller
    owns (admin: any workspace). Unknown / foreign UUIDs raise a
    404-like ``WorkspaceNotFound`` to avoid leaking existence
    (mirror F4-B Q2 EC2).

    Cron / timezone are pre-validated at the router (same as the MCP
    path) so an invalid spec returns 422 with
    ``error_class="InvalidCron"`` before the upsert runs.

    Idempotency-Key middleware (ADR 0009 Option C): when the client
    sends an ``Idempotency-Key`` header, a same-key + same-body retry
    returns the cached 2xx response verbatim (no second DB write);
    same-key + different body raises 422 ``IdempotencyKeyMismatch``.

    Note: scheduler registration (``register_digest_subscription``)
    is intentionally NOT performed here. The HTTP surface persists
    the row; the next scheduler reconciliation tick picks it up.
    This keeps the API process decoupled from the bot's APScheduler
    state and matches the MCP architecture (sprint prompt §2 P-2).
    """
    from tg_parser.services.db_context import digest_subscription_repo, workspace_repo
    from tg_parser.services.digest_service import DigestService

    if (
        idempotency is not None
        and idempotency.status == "hit"
        and idempotency.cached_body is not None
    ):
        return idempotency.build_cached_response(normalize_created=True)

    logger.info(
        "digests_create",
        user_id=user.id,
        name_len=len(request.name),
        channel_count=len(request.channel_ids),
        has_workspace_id=request.workspace_id is not None,
    )

    cron_error = _validate_cron_timezone(request.cron_expression, request.timezone)
    if cron_error is not None:
        return _error(422, cron_error, "InvalidCron")

    format_enum = DigestFormat(request.format)
    language = request.language if request.language is not None else "ru"

    try:
        async with digest_subscription_repo() as (sub_repo, _db):
            if request.workspace_id is not None:
                async with workspace_repo() as (ws_repo_inst, _db2):
                    service = DigestService(
                        processed_repo=None,
                        subscription_repo=sub_repo,
                        prompt_loader=None,
                        llm_client_factory=None,
                        workspace_repo=ws_repo_inst,
                    )
                    result = await service.subscribe(
                        owner_id=user.id,
                        chat_id=request.chat_id,
                        name=request.name,
                        channel_ids=list(request.channel_ids),
                        cron_expression=request.cron_expression,
                        timezone=request.timezone,
                        format=format_enum,
                        language=language,
                        workspace_id=request.workspace_id,
                        is_admin=user.is_admin,
                    )
            else:
                service = DigestService(
                    processed_repo=None,
                    subscription_repo=sub_repo,
                    prompt_loader=None,
                    llm_client_factory=None,
                    workspace_repo=None,
                )
                result = await service.subscribe(
                    owner_id=user.id,
                    chat_id=request.chat_id,
                    name=request.name,
                    channel_ids=list(request.channel_ids),
                    cron_expression=request.cron_expression,
                    timezone=request.timezone,
                    format=format_enum,
                    language=language,
                    workspace_id=None,
                    is_admin=user.is_admin,
                )
    except WorkspaceNotFound as exc:
        return _error(404, exc.message, "WorkspaceNotFound")

    response_body = {
        "digest_id": str(result.subscription.id),
        "created": result.created,
        "changed_fields": list(result.changed_fields),
    }

    if idempotency is not None:
        await idempotency.store(body=response_body, status_code=201)

    return DigestSubscribeResponse(**response_body)


@router.get(
    "",
    response_model=DigestListResponse,
    summary="List the caller's digest subscriptions",
)
async def list_digests(
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=50, ge=1, le=200, description="Pagination limit"),
    user: CurrentUser = Depends(resolve_current_user),
):
    """List digest subscriptions owned by the caller.

    Pagination is offset/limit at the application layer — the repo
    returns the full list and the router slices, which keeps memory
    bounded by ``CurrentUser`` subscription count (operator-scale, not
    user-scale). Inactive subscriptions are included so the caller
    can re-subscribe them via the idempotent POST without a separate
    "deleted" endpoint.

    ``workspace_name`` is JOIN-fetched per Q-OPEN-3: one
    :class:`WorkspaceRepo.get` per distinct ``workspace_id`` on the
    page (typically ≤ 5 calls).
    """
    from tg_parser.services.db_context import digest_subscription_repo

    logger.info("digests_list", user_id=user.id, offset=offset, limit=limit)

    async with digest_subscription_repo() as (sub_repo, _db):
        subs = await sub_repo.list_by_owner(user.id)

    total = len(subs)
    page = subs[offset : offset + limit]
    workspace_names = await _resolve_workspace_names(page)
    items = [_digest_to_response(s, workspace_names.get(s.workspace_id or "")) for s in page]
    return DigestListResponse(items=items, total=total)


@router.get(
    "/{digest_id}",
    response_model=DigestResponse,
    summary="Get a single digest subscription",
)
async def get_digest(
    digest_id: str,
    user: CurrentUser = Depends(resolve_current_user),
):
    """Fetch a single digest subscription by id.

    Ownership rules (mirror F4-B Q2 EC2):

    * Caller owns the row → 200 with the full payload (including
      ``workspace_id`` + ``workspace_name``).
    * Admin → 200 for ANY row (parity with F4-A admin scope).
    * Non-admin caller asks for someone else's id → 404, NEVER 403
      (existence is never leaked).
    * Unknown id → 404.
    """
    from tg_parser.services.db_context import digest_subscription_repo

    logger.info("digests_get", user_id=user.id, digest_id=digest_id)

    async with digest_subscription_repo() as (sub_repo, _db):
        sub = await sub_repo.get(digest_id)

    if sub is None or (not user.is_admin and sub.owner_id != user.id):
        return _error(404, f"Digest {digest_id!r} not found", "NotFound")

    workspace_names = await _resolve_workspace_names([sub])
    return _digest_to_response(sub, workspace_names.get(sub.workspace_id or ""))


@router.delete(
    "/{digest_id}",
    status_code=204,
    summary="Delete a digest subscription (HARD delete)",
)
async def delete_digest(
    digest_id: str,
    user: CurrentUser = Depends(resolve_current_user),
):
    """HARD delete a digest subscription (Q8 digest variant).

    REST-strict per parent Q-OPEN-8 lock — **ASYMMETRIC** vs the
    P-1 watchlist soft-delete pattern:

    * First DELETE on an own row → ``DigestSubscriptionRepo.delete``
      physically removes the row, returns 204 with no body.
    * Second DELETE on the same id → 404 (row no longer exists; we
      cannot distinguish "deleted by you a moment ago" from "never
      existed", and per REST-strict that's the correct shape).
    * Foreign / unknown id → 404, never 403 (existence not leaked).

    Note: scheduler unregistration (``unregister_digest_subscription``)
    is NOT performed here — same rationale as create: the HTTP
    process is decoupled from the bot's APScheduler state and the
    reconciliation tick removes the orphan job within the next cycle.
    """
    from tg_parser.services.db_context import digest_subscription_repo

    logger.info("digests_delete", user_id=user.id, digest_id=digest_id)

    async with digest_subscription_repo() as (sub_repo, _db):
        existing = await sub_repo.get(digest_id)
        if existing is None or (not user.is_admin and existing.owner_id != user.id):
            return _error(404, f"Digest {digest_id!r} not found", "NotFound")
        await sub_repo.delete(digest_id)

    return Response(status_code=204)
