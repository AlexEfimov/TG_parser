"""BUG-050 watchlist parity — subscribe_intent router covers subscribe_watchlist."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import AgentResult
from tg_parser.bot.handlers import READ_CONTEXT_TTL_SECONDS, handle_text
from tg_parser.bot.states import ConfirmFlow

DM_CHAT_ID: int = 700_500_051
GOOD_CHANNEL = "genotek"
TYPO_CHANNEL = "enotek"


def _admin(user_id: str = "user-051") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="051",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _make_state(bot_id: int = 42, chat_id: int = DM_CHAT_ID, user_id: int = 67890) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = DM_CHAT_ID) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


def _watchlist_intent(*, created_at: str | None = None) -> dict:
    return {
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "tool_name": "subscribe_watchlist",
        "requested_channel": TYPO_CHANNEL,
        "partial_args": {},
    }


@pytest.mark.asyncio
async def test_watchlist_text_only_subscribe_create_sets_intent_with_tool() -> None:
    state = _make_state()
    agent = MagicMock()
    agent.process_message = AsyncMock(
        return_value=AgentResult(
            response_text='Канал "enotek" не найден. Возможно, вы имели в виду "genotek"?'
        )
    )
    msg = _make_message("Создай watchlist на канал enotek")
    await handle_text(msg, agent=agent, state=state, current_user=_admin())

    si = (await state.get_data()).get("subscribe_intent")
    assert si is not None
    assert si["tool_name"] == "subscribe_watchlist"
    age = (datetime.now(UTC) - datetime.fromisoformat(si["created_at"])).total_seconds()
    assert 0 <= age < READ_CONTEXT_TTL_SECONDS


@pytest.mark.asyncio
async def test_bare_channel_resumes_watchlist_not_list_topics() -> None:
    state = _make_state()
    await state.update_data(subscribe_intent=_watchlist_intent())
    msg = _make_message(GOOD_CHANNEL)
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

    invoked: list[tuple[str, dict]] = []

    async def mock_execute(name: str, args: dict, **_kw):
        invoked.append((name, dict(args)))
        return {
            "preview": True,
            "tool": name,
            "message": "Preview: создать watchlist… Подтвердите [да/нет].",
        }

    with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

    assert [n for n, _ in invoked] == ["subscribe_watchlist"]
    assert "list_topics" not in [n for n, _ in invoked]
    assert invoked[0][1]["channel_ids"] == [GOOD_CHANNEL]
    assert invoked[0][1]["title"] == f"Watchlist {GOOD_CHANNEL}"
    assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
    agent.process_message.assert_not_called()


@pytest.mark.asyncio
async def test_digest_intent_without_tool_name_still_defaults_to_digest() -> None:
    """Legacy subscribe_intent snapshots without tool_name remain digest-compatible."""
    state = _make_state()
    await state.update_data(
        subscribe_intent={
            "created_at": datetime.now(UTC).isoformat(),
            "requested_channel": TYPO_CHANNEL,
            "partial_args": {"cron_expression": "0 * * * *"},
        }
    )
    msg = _make_message(GOOD_CHANNEL)
    agent = MagicMock()
    agent.process_message = AsyncMock(return_value=AgentResult(response_text="ok"))

    invoked: list[str] = []

    async def mock_execute(name: str, _args: dict, **_kw):
        invoked.append(name)
        return {"preview": True, "tool": name, "message": "Preview."}

    with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

    assert invoked == ["subscribe_digest"]
