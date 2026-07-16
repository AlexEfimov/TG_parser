"""Best-effort audit event writer (F9 Phase 3).

Public write API for immutable ``audit_log`` inserts. Failures are logged and
swallowed so callers (esp. auth-reject) keep their primary response path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

# Action names locked in F9 Phase 3 D3
ACTION_CHANNEL_ADD = "channel.add"
ACTION_CHANNEL_REMOVE = "channel.remove"
ACTION_CHANNEL_PAUSE = "channel.pause"
ACTION_CHANNEL_RESUME = "channel.resume"
ACTION_LLM_CONFIG_SET = "llm_config.set"
ACTION_LLM_CONFIG_RESET = "llm_config.reset"
ACTION_AUTH_API_KEY_REJECTED = "auth.api_key_rejected"
ACTION_USER_REGISTER = "user.register"
ACTION_USER_UPDATE = "user.update"
ACTION_USER_AUTH_ADD = "user.auth_add"
ACTION_USER_AUTH_REMOVE = "user.auth_remove"

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_DENIED = "denied"


async def record_audit_event(
    *,
    action: str,
    outcome: str,
    actor_user_id: UUID | str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Insert one audit row. Never raises; never stores raw secrets.

    Callers must pass only non-secret ``meta`` (ids, scopes, key_prefix, etc.).
    """
    try:
        from tg_parser.services.db_context import audit_log_repo

        async with audit_log_repo() as (repo, _db):
            await repo.insert(
                action=action,
                outcome=outcome,
                actor_user_id=actor_user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                meta=meta,
            )
    except Exception:
        logger.warning(
            "audit_log_write_failed",
            action=action,
            outcome=outcome,
            exc_info=True,
        )


async def audit_channel_event(
    *,
    action: str,
    actor_user_id: UUID | str | None,
    channel_id: str,
    meta: dict[str, Any] | None = None,
) -> None:
    """Thin wrapper for channel lifecycle success events (bot + MCP)."""
    await record_audit_event(
        action=action,
        outcome=OUTCOME_SUCCESS,
        actor_user_id=actor_user_id,
        resource_type="channel",
        resource_id=channel_id,
        meta={"channel_id": channel_id, **(meta or {})},
    )
