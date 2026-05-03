"""FSM state groups for the Telegram bot's two-turn conversation flows.

Two flows live here:

* :class:`ConfirmFlow` — pending write-tool preview awaiting a yes/no reply.
  Closes BUG-002: handler executes the previewed tool deterministically with
  ``confirm=True``; the LLM is **not** consulted again, so it cannot
  hallucinate a different ``tool_name`` / ``args`` / ``channel_id`` on a
  bare "да".

* :class:`PaginationFlow` — list-tool result has more pages; user can ask
  "ещё / next" or "стоп / cancel". Closes BUG-004: ``offset`` is bumped by
  the handler from FSM-stored ``args`` (in particular ``channel_id``), so
  the second page can never collapse into "all topics across the KB".

:class:`ReadContextData` — NOT a state group; a plain TypedDict stored as
an FSM data field (BUG-011, Session H). Tracks the most-recent channel the
user was reading from across turns. Coexists with active ConfirmFlow /
PaginationFlow states; TTL-governed (15 min default).

Storage backend is configured in :func:`tg_parser.bot.main.run_bot`
(MemoryStorage by default per BUG_LOG § Session planning D-4 — single
replica deployment; switch to RedisStorage when scaling out).
"""

from __future__ import annotations

from typing import TypedDict

from aiogram.fsm.state import State, StatesGroup


class ConfirmFlow(StatesGroup):
    """User just received a write-tool preview, expects yes/no on next turn."""

    awaiting_confirmation = State()


class PaginationFlow(StatesGroup):
    """Last list-tool returned ``has_more=True``; user may say ``ещё`` / ``next``."""

    has_active_list = State()


class ReadContextData(TypedDict):
    """Shadow read-context preserved across read-tool turns (BUG-011, Session H).

    Stored as ``FSMContext.update_data(read_context=...)`` — NOT a state.
    Coexists with active ``ConfirmFlow.awaiting_confirmation`` /
    ``PaginationFlow.has_active_list`` states; persists across ``state.clear()``
    via explicit re-write in the handler.

    See ``handlers._refresh_read_context`` for update sites and
    ``handlers._read_context_for_agent`` for the resolution path.
    """

    last_channel_id: str
    last_tool: str
    created_at: str  # ISO UTC timestamp, used for TTL check
