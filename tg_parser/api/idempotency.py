"""Stripe-style Idempotency-Key HTTP middleware (Wave 1 step 3 commit 4/4).

Implements the HTTP arm of ADR 0009 Option C (hybrid): the service-layer
natural-key upsert (commits 1/4 + 2/4 + 3/4) closes BUG-022 cross-surface;
this dependency layers transient-retry safety on top for HTTP clients
that follow Stripe / Square / Plaid conventions and send a client-
generated ``Idempotency-Key`` header.

Opt-in per endpoint (Q-OPEN-7) — wired only on
``POST /api/v1/watchlists`` + ``POST /api/v1/digests`` in this commit;
broadening to other POST endpoints is intentionally deferred to a
future PR.

Semantics (per ADR 0009 + sprint prompt locks):

* Header absent → dependency returns ``None``; endpoint runs the normal
  flow without any cache I/O.
* Header present + record absent → ``IdempotencyContext(status='miss')``
  with the canonical body-hash pre-computed; endpoint runs the normal
  flow, then calls :meth:`IdempotencyContext.store` with its 2xx payload.
* Header present + record exists + ``request_hash`` matches → 200/201/2xx
  replay from cache; the endpoint short-circuits via
  ``ctx.cached_status`` / ``ctx.cached_body`` and skips its own work.
* Header present + record exists + ``request_hash`` differs → 422
  ``IdempotencyKeyMismatch`` raised here, before the endpoint runs
  (Q-OPEN-1 lean).

Risk mitigations explicitly encoded:

* **R-2 — only 2xx cached.** :meth:`IdempotencyContext.store` is a no-op
  for any status outside ``[200, 300)``. 4xx / 5xx responses pass through
  without polluting the cache so a transient validation failure can be
  retried with a corrected body under the same key.
* **R-4 — canonical body hashing.** :func:`canonicalize_body` sorts JSON
  keys and strips whitespace before hashing so a client that re-serializes
  the same logical body with different key order or formatting still
  hits the cache.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.metrics import record_idempotency_key_result
from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import IdempotencyKeyRepo

logger = structlog.get_logger(__name__)


# ── Constants ───────────────────────────────────────────────────────────────


IDEMPOTENCY_HEADER = "Idempotency-Key"
MISMATCH_ERROR_CLASS = "IdempotencyKeyMismatch"


# ── Exceptions ──────────────────────────────────────────────────────────────


class IdempotencyKeyMismatchError(Exception):
    """Raised by :func:`idempotency_key_check` when same key + different body.

    Caught by the FastAPI exception handler registered in
    :mod:`tg_parser.api.main` which translates the exception into a
    Q7-shaped ``{"detail": ..., "error_class": "IdempotencyKeyMismatch"}``
    422 response — same envelope used by every other validation error on
    the watchlist / digest surfaces.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


# ── Helpers ─────────────────────────────────────────────────────────────────


def canonicalize_body(body: bytes) -> bytes:
    """Return a deterministic canonical JSON encoding of ``body``.

    Sorts keys + uses compact separators so the SHA-256 hash is stable
    across client-side serialization variance (R-4 mitigation per
    sprint prompt). Empty / non-JSON bodies pass through verbatim so
    endpoints whose body is e.g. an empty POST still hash to a stable
    value (the canonical form of "no body" is "no body").
    """
    if not body:
        return b""
    try:
        parsed: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_body(body: bytes) -> str:
    """SHA-256 hex digest of the canonical body — the request_hash stored in DB."""
    return hashlib.sha256(canonicalize_body(body)).hexdigest()


# ── Context object passed to endpoints ──────────────────────────────────────


@dataclass
class IdempotencyContext:
    """Per-request state shared between the dependency and the endpoint.

    The dependency builds this object (status = ``hit`` or ``miss``) and
    returns it to the endpoint. The endpoint:

    1. If ``status == "hit"`` and ``cached_body is not None`` — return
       a :class:`~fastapi.responses.JSONResponse` from
       :meth:`build_cached_response` and skip its own work.
    2. Otherwise run normal flow, then call :meth:`store` with the final
       status code + JSON-serializable body.

    The ``status_to_log`` field is captured at dependency-resolution
    time so the structlog ``idempotency_key`` bind survives even if the
    endpoint forgets to call :meth:`store` (Karpathy principle 6 —
    instrumentation is independent of endpoint discipline).
    """

    key: str
    user_id: str
    body_hash: str
    repo: IdempotencyKeyRepo
    status: Literal["hit", "miss"]
    cached_status: int | None = None
    cached_body: dict[str, Any] | None = None
    _stored: bool = field(default=False, repr=False)

    def build_cached_response(self) -> JSONResponse:
        """Return a ``JSONResponse`` reproducing the cached 2xx outcome verbatim."""
        assert self.cached_body is not None, "build_cached_response called on miss context"
        return JSONResponse(
            status_code=self.cached_status or 200,
            content=self.cached_body,
        )

    async def store(self, *, body: dict[str, Any], status_code: int) -> None:
        """Persist ``body`` as the cached response for ``(user_id, key)``.

        No-op when:

        * ``status_code`` is outside ``[200, 300)`` (R-2 — only 2xx
          outcomes are cached so a transient validation failure can be
          retried with a corrected body under the same key).
        * Already stored once in this request lifecycle (defensive idempotency).
        * Current status is ``"hit"`` (the row already exists; skipping
          the INSERT avoids a redundant write).
        """
        if self._stored:
            return
        if not (200 <= status_code < 300):
            logger.debug(
                "idempotency_skip_non_2xx",
                idempotency_key=self.key,
                status_code=status_code,
            )
            return
        if self.status == "hit":
            self._stored = True
            return
        envelope: dict[str, Any] = {"status": int(status_code), "body": body}
        await self.repo.insert(
            key=self.key,
            user_id=self.user_id,
            request_hash=self.body_hash,
            response_body=envelope,
        )
        record_idempotency_key_result(result="miss")
        self._stored = True


# ── DI factory for the repo ─────────────────────────────────────────────────


async def get_idempotency_key_repo() -> IdempotencyKeyRepo:
    """FastAPI dependency providing a short-lived ``IdempotencyKeyRepo`` session.

    Each call opens a fresh ingestion-DB session and closes it when the
    yielded generator is finalised — mirrors the per-request lifetime
    of every other repo dependency in this surface.
    """
    from tg_parser.services.db_context import idempotency_key_repo

    async with idempotency_key_repo() as (repo, _db):
        yield repo


# ── Main dependency ─────────────────────────────────────────────────────────


async def idempotency_key_check(
    request: Request,
    user: CurrentUser = Depends(resolve_current_user),
    repo: IdempotencyKeyRepo = Depends(get_idempotency_key_repo),
) -> IdempotencyContext | None:
    """FastAPI dependency that implements the Stripe-style replay check.

    See the module docstring for the full state machine. Header absent
    → ``None`` (endpoint runs normal flow); same key + matching body
    → ``IdempotencyContext(status='hit')`` with cached payload pre-loaded;
    same key + different body → :class:`HTTPException(422)`.

    The body is read once via :meth:`fastapi.Request.body` and stored
    on ``request._body`` by FastAPI internals, so the downstream
    endpoint's Pydantic request-model deserialisation re-uses the cached
    bytes (no double-read penalty).
    """
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if not key:
        return None

    structlog.contextvars.bind_contextvars(idempotency_key=key)

    body_bytes = await request.body()
    body_hash = _hash_body(body_bytes)

    existing = await repo.find_by_key(key=key, user_id=user.id)

    if existing is None:
        logger.debug("idempotency_miss", idempotency_key=key, user_id=user.id)
        return IdempotencyContext(
            key=key,
            user_id=user.id,
            body_hash=body_hash,
            repo=repo,
            status="miss",
        )

    if existing.request_hash != body_hash:
        record_idempotency_key_result(result="mismatch")
        logger.info(
            "idempotency_mismatch",
            idempotency_key=key,
            user_id=user.id,
            stored_hash_prefix=existing.request_hash[:8],
            incoming_hash_prefix=body_hash[:8],
        )
        raise IdempotencyKeyMismatchError(
            "Idempotency-Key reused with a different request body. "
            "Generate a new key or replay the original body."
        )

    record_idempotency_key_result(result="hit")
    envelope = existing.response_body or {}
    cached_status = int(envelope.get("status", 200)) if isinstance(envelope, dict) else 200
    cached_body = envelope.get("body") if isinstance(envelope, dict) else None
    logger.info(
        "idempotency_hit",
        idempotency_key=key,
        user_id=user.id,
        cached_status=cached_status,
    )
    return IdempotencyContext(
        key=key,
        user_id=user.id,
        body_hash=body_hash,
        repo=repo,
        status="hit",
        cached_status=cached_status,
        cached_body=cached_body if isinstance(cached_body, dict) else None,
    )
