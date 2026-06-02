"""BUG-052 — PaginationFlow bare channel token must not D-4 fall through to agent."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.bot.handlers import _handle_pagination_response
from tg_parser.bot.states import PaginationFlow


def _make_state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=42, chat_id=12345, user_id=67890)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = 12345
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    return msg


async def _arm_genotek_pagination(state: FSMContext) -> None:
    await state.set_state(PaginationFlow.has_active_list)
    await state.update_data(
        pagination={
            "tool_name": "list_topics",
            "args": {
                "channel_id": "genotek",
                "offset": 5,
                "limit": 5,
            },
            "total": 25,
            "offset": 5,
            "limit": 5,
        },
        items_shown=5,
        created_at=datetime.now(UTC).isoformat(),
        read_context={
            "last_channel_id": "genotek",
            "last_tool": "list_topics",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


@pytest.mark.asyncio
async def test_bare_matching_channel_is_noop_keeps_pagination() -> None:
    state = _make_state()
    await _arm_genotek_pagination(state)
    msg = _make_message("genotek")
    agent = MagicMock()
    agent.process_message = AsyncMock()

    with patch("tg_parser.bot.handlers.execute_tool", new=AsyncMock()) as mock_execute:
        await _handle_pagination_response(msg, agent, state, current_user=None)

    mock_execute.assert_not_called()
    agent.process_message.assert_not_called()
    assert await state.get_state() == PaginationFlow.has_active_list.state
    msg.answer.assert_called_once()
    assert "ещё" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_bare_different_channel_still_falls_through() -> None:
    state = _make_state()
    await _arm_genotek_pagination(state)
    msg = _make_message("other_channel")
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value=MagicMock(response_text="ok"))

    with patch("tg_parser.bot.handlers.execute_tool", new=AsyncMock()):
        with patch("tg_parser.bot.handlers.handle_text", new=AsyncMock()) as mock_handle:
            await _handle_pagination_response(msg, agent, state, current_user=None)

    mock_handle.assert_called_once()
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_next_page_and_stop_unchanged() -> None:
    state = _make_state()
    await _arm_genotek_pagination(state)
    stop_msg = _make_message("стоп")
    agent = MagicMock()
    agent.process_message = AsyncMock()

    with patch("tg_parser.bot.handlers.execute_tool", new=AsyncMock()) as mock_execute:
        await _handle_pagination_response(stop_msg, agent, state, current_user=None)

    mock_execute.assert_not_called()
    assert await state.get_state() is None
    assert "Остановлено" in stop_msg.answer.call_args[0][0]
