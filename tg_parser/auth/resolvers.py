"""
Shared user resolution with TTL cache (F4 Multi-Tenancy).

Used by API, Bot, and MCP layers to convert auth credentials into CurrentUser.

BUG-107: a resolved user's ``allowed_channel_ids`` is always an explicit list
of channels that are not soft-deleted — the admin's too. ``None`` ("every
channel") survives only on the synthetic dev-mode admin, so every check that
filters by ``allowed_channel_ids`` also hides removed channels from admin.
"""

import hashlib
import time
from typing import TYPE_CHECKING

import structlog

from tg_parser.auth.models import CurrentUser
from tg_parser.config import settings

if TYPE_CHECKING:
    from tg_parser.storage.ports import User, UserRepo

logger = structlog.get_logger(__name__)

_CACHE_TTL = 60  # seconds
_cache: dict[str, tuple[CurrentUser, float]] = {}

_DEFAULT_ADMIN_ID = "00000000-0000-0000-0000-000000000000"


async def load_channel_scope(repo: "UserRepo", db_user: "User") -> list[str]:
    """Channel scope for a DB user: every live channel for admin, owned live ones otherwise."""
    if db_user.role == "admin":
        return await repo.get_live_channel_ids()
    return await repo.get_owned_channel_ids(db_user.id)


async def resolve_user_by_auth(auth_type: str, auth_identifier: str) -> CurrentUser | None:
    """Resolve a user from auth credentials.

    For api_key and mcp_token auth_types, auth_identifier should already be
    the SHA-256 hash of the raw key. For telegram, it's the plain user ID string.
    """
    cache_key = f"{auth_type}:{auth_identifier}"

    cached = _cache.get(cache_key)
    if cached:
        user, ts = cached
        if time.monotonic() - ts < _CACHE_TTL:
            return user

    from tg_parser.services.db_context import user_repo

    async with user_repo() as (repo, _db):
        db_user = await repo.resolve_auth(auth_type, auth_identifier)
        if db_user is None:
            _cache.pop(cache_key, None)
            return None

        allowed = await load_channel_scope(repo, db_user)

    max_ch = (
        db_user.max_channels if db_user.max_channels is not None else settings.default_max_channels
    )

    current_user = CurrentUser(
        id=db_user.id,
        name=db_user.name,
        role=db_user.role,
        allowed_channel_ids=allowed,
        max_channels=max_ch,
    )
    _cache[cache_key] = (current_user, time.monotonic())
    return current_user


async def get_default_admin(*, live_scope: bool = False) -> CurrentUser:
    """Return a synthetic admin for access without a DB-mapped identity.

    ``live_scope=True`` is for identities that reach production — legacy
    static MCP tokens, API keys with no DB mapping, the operator CLI: the
    scope is loaded as every live channel, like a DB admin (BUG-107).
    The default ``allowed_channel_ids=None`` ("every channel") is left for
    unauthenticated dev mode, which production disables
    (``MCP_AUTH_ENABLED`` / ``API_KEY_REQUIRED`` / ``BOT_ALLOWED_USERS``).
    """
    allowed: list[str] | None = None
    if live_scope:
        from tg_parser.services.db_context import user_repo

        async with user_repo() as (repo, _db):
            allowed = await repo.get_live_channel_ids()
    return CurrentUser(
        id=_DEFAULT_ADMIN_ID,
        name="admin",
        role="admin",
        allowed_channel_ids=allowed,
        max_channels=settings.default_max_channels,
    )


def invalidate_user_cache(auth_type: str, auth_identifier: str) -> None:
    """Remove a specific entry from the resolver cache."""
    _cache.pop(f"{auth_type}:{auth_identifier}", None)


def invalidate_channel_scopes() -> None:
    """Drop every cached user after a channel is added, restored or removed.

    A channel change moves the scope of its owner and of every admin, so a
    per-user invalidation would miss someone. The cache is per process:
    another process (bot / API / MCP) still serves its entry for up to
    ``_CACHE_TTL`` seconds.
    """
    _cache.clear()


def hash_credential(raw: str) -> str:
    """SHA-256 hash a raw API key or MCP token for DB lookup."""
    return hashlib.sha256(raw.encode()).hexdigest()


def clear_cache() -> None:
    """Clear the entire resolver cache (for tests)."""
    _cache.clear()
