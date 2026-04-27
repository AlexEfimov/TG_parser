"""
BUG-002 mitigation M2 — placeholder channel-name reject-list.

Single source of truth for "channel ids that must never be added as
real channels". This lives behind both `_exec_add_channel` (Telegram
bot) and `mcp_server.add_channel` (MCP) so neither LLM-driven flow can
materialise a hallucinated placeholder into the `sources` table.

Background: per `docs/notes/BUG_LOG.md` § BUG-002 the bot's lack of
multi-turn memory makes Gemini fall back to training-data placeholders
(`test_channel`, `example_channel`, …) on the second message of any
preview/confirm flow. M2 is the cheap pre-flight that turns the worst
case ("silently created bogus channel") into a deterministic refusal,
**before** any FSM-storage fix lands.

The reject-list is hardcoded for predictability and extensible at
runtime via the `BLOCKED_CHANNEL_IDS` env-var (comma-separated).
"""

from __future__ import annotations

import os
from typing import Final


# 8 commonly-hallucinated placeholders observed in BUG-002 traces and
# the immediate set of "obviously not a real channel" names we want to
# reject without touching the LLM. Add to this set conservatively —
# every entry is a hard "cannot be added" door.
DEFAULT_BLOCKED_PLACEHOLDER_NAMES: Final[frozenset[str]] = frozenset(
    {
        "test_channel",
        "example_channel",
        "my_channel",
        "default",
        "channel_a",
        "channel_b",
        "test",
        "example",
    }
)


def _env_blocked_names() -> frozenset[str]:
    """Parse `BLOCKED_CHANNEL_IDS` env-var (comma-separated) at call time.

    Read on every call so set_llm_config-style runtime overrides and
    test fixtures can mutate `os.environ` without re-importing this
    module.
    """
    raw = os.getenv("BLOCKED_CHANNEL_IDS", "")
    if not raw:
        return frozenset()
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def get_blocked_placeholder_names() -> frozenset[str]:
    """Return the full reject-set (defaults ∪ env-override)."""
    return DEFAULT_BLOCKED_PLACEHOLDER_NAMES | _env_blocked_names()


def is_blocked_placeholder(channel_id: str) -> bool:
    """True iff `channel_id` (already normalised, no leading `@`) is reserved."""
    return channel_id in get_blocked_placeholder_names()


def blocked_message(channel_id: str) -> str:
    """Stable user-facing rationale for an M2 reject."""
    return (
        f"Channel ID '{channel_id}' is reserved as a placeholder and cannot be "
        "added. Use a real Telegram channel username. "
        "Extend the reject-list via BLOCKED_CHANNEL_IDS=foo,bar (comma-separated)."
    )
