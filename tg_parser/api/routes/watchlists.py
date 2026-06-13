"""
Watchlist HTTP API routes (P-1 Surface Parity MVP — Wave 1 step 3 commit 2/4).

Five endpoints under ``/api/v1/watchlists`` per sprint prompt §2:

* ``POST   /api/v1/watchlists``                       — subscribe (idempotent
  upsert per BUG-022 on the ``(user_id, title)`` natural key; returns
  ``{watchlist_id, created, changed_fields}`` per Q-OPEN-1).
* ``GET    /api/v1/watchlists``                       — list current user's
  interests with offset/limit pagination (default ``limit=50``, max 200).
* ``GET    /api/v1/watchlists/{watchlist_id}``        — single detail, emits
  ``workspace_id`` + ``workspace_name`` via a single workspaces JOIN
  (Q-OPEN-3). Foreign id returns 404-like, NEVER 403 (mirror F4-B).
* ``DELETE /api/v1/watchlists/{watchlist_id}``        — soft-delete (Q8
  watchlist variant). 204 No Content; preserves ``watch_matches``.
  Idempotent: a second DELETE on an already-inactive own row also
  returns 204 (REST-strict per parent Q-OPEN-8 lock).
* ``GET    /api/v1/watchlists/{watchlist_id}/matches`` — match history with
  optional ``?since=ISO8601`` + offset/limit pagination (Q-OPEN-4).
  Owner-only; soft-deleted interest still serves history.

Authentication piggybacks on the existing ``X-API-Key`` dependency
(``resolve_current_user``) — no new auth surface (Q1).

Idempotency-Key HTTP middleware is **not** wired in this commit (lands
in commit 4/4). Service-layer natural-key upsert (commit 1/4) already
guarantees that same-args POST replays collapse to a single row, so
this surface is safe for clients today.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.idempotency import IdempotencyContext, idempotency_key_check
from tg_parser.api.schemas import (
    WatchlistCreateRequest,
    WatchlistListResponse,
    WatchlistMatchesResponse,
    WatchlistMatchItem,
    WatchlistResponse,
    WatchlistSubscribeResponse,
)
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import WorkspaceNotFound
from tg_parser.domain.models import (
    WatchInterest,
    subscription_target_from_watch,
    target_to_api_dict,
)

router = APIRouter(prefix="/api/v1/watchlists", tags=["Watchlists"])
logger = structlog.get_logger(__name__)


# ── Internal helpers ────────────────────────────────────────────────────────


def _error(status_code: int, detail: str, error_class: str) -> JSONResponse:
    """Build a Q7-shaped error response.

    ``{"detail": ..., "error_class": ...}`` is the locked HTTP error
    shape for this surface (sprint prompt §3 Q7). Centralised here so
    every endpoint emits an identical body — clients can branch on
    ``error_class`` to distinguish ``WorkspaceNotFound`` (caller
    referenced an unknown / foreign workspace) from a plain ``NotFound``
    (caller referenced an unknown / foreign watchlist) without parsing
    free-form text.
    """
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_class": error_class},
    )


def _interest_to_response(
    interest: WatchInterest,
    workspace_name: str | None,
) -> WatchlistResponse:
    """Project a domain ``WatchInterest`` onto :class:`WatchlistResponse`.

    Centralises the field mapping (``notify_mode`` Enum → string,
    ``embedding`` elided, ``workspace_name`` JOIN-injected) so all
    three GET endpoints (single + list + matches' owner shape) stay
    in sync.
    """
    target = target_to_api_dict(subscription_target_from_watch(interest))
    return WatchlistResponse(
        id=interest.id,
        user_id=interest.user_id,
        target=target,
        chat_id=interest.chat_id,
        channel_id=interest.channel_id,
        title=interest.title,
        workspace_id=interest.workspace_id,
        workspace_name=workspace_name,
        description=interest.description,
        keywords=list(interest.keywords),
        exclude_keywords=list(interest.exclude_keywords),
        channel_ids=list(interest.channel_ids),
        threshold=interest.threshold,
        notify_mode=interest.notify_mode.value,
        is_active=interest.is_active,
        last_checked_at=interest.last_checked_at,
        last_match_at=interest.last_match_at,
        created_at=interest.created_at,
        updated_at=interest.updated_at,
    )


async def _resolve_workspace_names(
    interests: list[WatchInterest],
) -> dict[str, str]:
    """Fetch ``workspaces.name`` for every distinct non-NULL ``workspace_id``.

    Performs at most ``N`` ``WorkspaceRepo.get(...)`` calls where ``N``
    is the count of unique workspace ids on the page — typically 0–5
    for a paginated list (Q-OPEN-3 ``workspace_name`` JOIN). Returns
    a dict keyed by ``workspace_id`` so callers can build response
    objects without juggling per-row queries. Workspaces that were
    deleted out-of-band (race against ON DELETE SET NULL) silently
    drop out — the row still renders with ``workspace_name=None``.
    """
    distinct_ids: set[str] = {i.workspace_id for i in interests if i.workspace_id is not None}
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


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=WatchlistSubscribeResponse,
    status_code=201,
    summary="Subscribe to a watchlist (idempotent upsert)",
)
async def create_watchlist(
    request: WatchlistCreateRequest,
    user: CurrentUser = Depends(resolve_current_user),
    idempotency: IdempotencyContext | None = Depends(idempotency_key_check),
):
    """Create (or idempotently upsert) a watchlist interest.

    Idempotency contract (BUG-022 + Q-OPEN-1):

    * Same ``(user_id, title)`` + identical payload → no-op replay;
      response carries ``created=False`` and ``changed_fields=[]``.
    * Same ``(user_id, title)`` + different mutable args → UPDATE
      the changed columns; response is ``created=False`` with
      ``changed_fields=[<field names>]``.
    * New ``(user_id, title)`` → INSERT; ``created=True`` and
      ``changed_fields=[]``.

    ENH-9: ``workspace_id`` may reference any workspace the caller
    owns (admin: any workspace). Unknown / foreign UUIDs raise a
    404-like ``WorkspaceNotFound`` to avoid leaking existence
    (mirror F4-B Q2 EC2).

    Idempotency-Key middleware (ADR 0009 Option C): when the client
    sends an ``Idempotency-Key`` header, a same-key + same-body retry
    returns the cached 2xx response verbatim (no second DB write);
    same-key + different body raises 422 ``IdempotencyKeyMismatch``.
    Absence of the header is fully supported (service-layer natural-key
    upsert already collapses replays).
    """
    from tg_parser.services.db_context import watchlist_repos, workspace_repo
    from tg_parser.services.watchlist_service import make_watchlist_service

    if (
        idempotency is not None
        and idempotency.status == "hit"
        and idempotency.cached_body is not None
    ):
        return idempotency.build_cached_response(normalize_created=True)

    logger.info(
        "watchlists_create",
        user_id=user.id,
        title_len=len(request.title),
        channel_count=len(request.channel_ids),
        has_workspace_id=request.workspace_id is not None,
    )

    try:
        async with watchlist_repos() as (
            interest_repo,
            match_repo,
            processed_doc_repo,
            embedding_repo,
            _db,
        ):
            if request.workspace_id is not None:
                async with workspace_repo() as (ws_repo_inst, _db2):
                    service = make_watchlist_service(
                        interest_repo=interest_repo,
                        match_repo=match_repo,
                        processed_doc_repo=processed_doc_repo,
                        embedding_repo=embedding_repo,
                        workspace_repo=ws_repo_inst,
                    )
                    try:
                        result = await service.subscribe(
                            user_id=user.id,
                            chat_id=request.chat_id,
                            target=request.target,
                            title=request.title,
                            channel_ids=request.channel_ids,
                            keywords=request.keywords,
                            description=request.description,
                            exclude_keywords=request.exclude_keywords,
                            threshold=request.threshold,
                            workspace_id=request.workspace_id,
                            is_admin=user.is_admin,
                        )
                    finally:
                        await service.aclose()
            else:
                service = make_watchlist_service(
                    interest_repo=interest_repo,
                    match_repo=match_repo,
                    processed_doc_repo=processed_doc_repo,
                    embedding_repo=embedding_repo,
                )
                try:
                    result = await service.subscribe(
                        user_id=user.id,
                        chat_id=request.chat_id,
                        target=request.target,
                        title=request.title,
                        channel_ids=request.channel_ids,
                        keywords=request.keywords,
                        description=request.description,
                        exclude_keywords=request.exclude_keywords,
                        threshold=request.threshold,
                        workspace_id=None,
                        is_admin=user.is_admin,
                    )
                finally:
                    await service.aclose()
    except WorkspaceNotFound as exc:
        return _error(404, exc.message, "WorkspaceNotFound")

    response_body = {
        "watchlist_id": str(result.interest.id),
        "created": result.created,
        "changed_fields": list(result.changed_fields),
        "target": target_to_api_dict(subscription_target_from_watch(result.interest)),
        "threshold_calibration": (
            asdict(result.threshold_calibration)
            if result.threshold_calibration is not None
            else None
        ),
    }

    if idempotency is not None:
        await idempotency.store(body=response_body, status_code=201)

    return WatchlistSubscribeResponse(**response_body)


@router.get(
    "",
    response_model=WatchlistListResponse,
    summary="List the caller's watchlists",
)
async def list_watchlists(
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=50, ge=1, le=200, description="Pagination limit"),
    user: CurrentUser = Depends(resolve_current_user),
):
    """List active + paused watchlists owned by the caller.

    Pagination is offset/limit at the application layer — the repo
    returns the full list and the router slices, which keeps memory
    bounded by ``CurrentUser`` interest count (operator-scale, not
    user-scale). Soft-deleted interests are included so the caller
    can re-subscribe them via the idempotent POST without first
    listing inactive rows from a separate endpoint.

    ``workspace_name`` is JOIN-fetched per Q-OPEN-3: one
    :class:`WorkspaceRepo.get` per distinct ``workspace_id`` on the
    page (typically ≤ 5 calls).
    """
    from tg_parser.services.db_context import watchlist_repos

    logger.info("watchlists_list", user_id=user.id, offset=offset, limit=limit)

    async with watchlist_repos() as (
        interest_repo,
        _match_repo,
        _proc_repo,
        _emb_repo,
        _db,
    ):
        interests = await interest_repo.list_for_user(user.id)

    total = len(interests)
    page = interests[offset : offset + limit]
    workspace_names = await _resolve_workspace_names(page)
    items = [_interest_to_response(i, workspace_names.get(i.workspace_id or "")) for i in page]
    return WatchlistListResponse(items=items, total=total)


@router.get(
    "/{watchlist_id}",
    response_model=WatchlistResponse,
    summary="Get a single watchlist",
)
async def get_watchlist(
    watchlist_id: str,
    user: CurrentUser = Depends(resolve_current_user),
):
    """Fetch a single watchlist by id.

    Ownership rules (mirror F4-B Q2 EC2):

    * Caller owns the row → 200 with the full payload (including
      ``workspace_id`` + ``workspace_name``).
    * Admin → 200 for ANY row (parity with F4-A admin scope).
    * Non-admin caller asks for someone else's id → 404, NEVER 403
      (existence is never leaked).
    * Unknown id → 404.
    """
    from tg_parser.services.db_context import watchlist_repos

    logger.info("watchlists_get", user_id=user.id, watchlist_id=watchlist_id)

    async with watchlist_repos() as (
        interest_repo,
        _match_repo,
        _proc_repo,
        _emb_repo,
        _db,
    ):
        interest = await interest_repo.get(watchlist_id)

    if interest is None or (not user.is_admin and interest.user_id != user.id):
        return _error(404, f"Watchlist {watchlist_id!r} not found", "NotFound")

    workspace_names = await _resolve_workspace_names([interest])
    return _interest_to_response(interest, workspace_names.get(interest.workspace_id or ""))


@router.delete(
    "/{watchlist_id}",
    status_code=204,
    summary="Soft-delete a watchlist (idempotent)",
)
async def delete_watchlist(
    watchlist_id: str,
    user: CurrentUser = Depends(resolve_current_user),
):
    """Soft-delete a watchlist (Q8 watchlist variant).

    REST-strict idempotency per parent Q-OPEN-8 lock:

    * First DELETE on an active own row → flips ``is_active=False``,
      returns 204 with no body. ``watch_matches`` rows are preserved
      (the matches endpoint continues to serve history).
    * Second DELETE on the same already-inactive row → 204 (no-op).
    * Foreign / unknown id → 404, never 403 (existence not leaked).
    """
    from tg_parser.services.db_context import watchlist_repos

    logger.info("watchlists_delete", user_id=user.id, watchlist_id=watchlist_id)

    async with watchlist_repos() as (
        interest_repo,
        _match_repo,
        _proc_repo,
        _emb_repo,
        _db,
    ):
        existing = await interest_repo.get(watchlist_id)
        if existing is None or (not user.is_admin and existing.user_id != user.id):
            return _error(404, f"Watchlist {watchlist_id!r} not found", "NotFound")
        if existing.is_active:
            await interest_repo.soft_delete(watchlist_id)

    return Response(status_code=204)


@router.get(
    "/{watchlist_id}/matches",
    response_model=WatchlistMatchesResponse,
    summary="Get match history for a watchlist",
)
async def get_watchlist_matches(
    watchlist_id: str,
    since: datetime | None = Query(
        default=None,
        description="ISO-8601 cutoff; only matches with created_at > since are returned",
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=50, ge=1, le=200, description="Pagination limit"),
    user: CurrentUser = Depends(resolve_current_user),
):
    """Return ``WatchMatch`` rows for a watchlist (owner-only).

    Visibility mirrors :func:`get_watchlist`: caller must own the
    interest (admin bypasses). Soft-deleted interests still serve
    history — by design (Q8 watchlist variant), so historical
    analytics keep working after an unsubscribe.

    ``?since=ISO8601`` is a strict ``>`` filter on ``created_at``
    (parsed by FastAPI / Pydantic from the query string). Q-OPEN-4
    locks ``since`` + offset/limit as the *only* filters for v1; any
    richer filtering (score range, channel filter, …) is intentionally
    deferred so the surface stays minimal.
    """
    from tg_parser.services.db_context import watchlist_repos

    logger.info(
        "watchlists_matches",
        user_id=user.id,
        watchlist_id=watchlist_id,
        since=since.isoformat() if since else None,
        offset=offset,
        limit=limit,
    )

    async with watchlist_repos() as (
        interest_repo,
        match_repo,
        _proc_repo,
        _emb_repo,
        _db,
    ):
        existing = await interest_repo.get(watchlist_id)
        if existing is None or (not user.is_admin and existing.user_id != user.id):
            return _error(404, f"Watchlist {watchlist_id!r} not found", "NotFound")
        matches = await match_repo.list_for_interest(watchlist_id, since=since)

    total = len(matches)
    page = matches[offset : offset + limit]
    items = [
        WatchlistMatchItem(
            match_id=m.id,
            interest_id=m.interest_id,
            source_ref=m.source_ref,
            channel_id=m.channel_id,
            keyword_score=m.keyword_score,
            semantic_score=m.semantic_score,
            combined_score=m.combined_score,
            notified=m.notified,
            created_at=m.created_at,
        )
        for m in page
    ]
    return WatchlistMatchesResponse(items=items, total=total)
