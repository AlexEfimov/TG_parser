"""Regression suite for BUG-053 — short channel prefix read-clarify.

Real-fire trace: «покажи темы gen» → ``list_topics(gen)`` → ``total=0`` →
``_channel_suggestion_lookup`` at cutoff 0.7 finds no ``gen``→``genotek`` match
→ no ``clarify_pending`` → 2nd LLM paraphrase; ``read_context`` sticks on
``gen`` so a follow-up «genotek»/«да» re-routes through implicit context.

Fix A: ``_channel_suggestion_lookup`` falls back to ``_SUGGEST_FUZZY_CUTOFF``
(0.5) when the 0.7 tier is empty (single match only).
Fix B: ``agent.py`` skips ``read_tools_called`` when ``list_topics`` returns
``total=0``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import GeminiAgent
from tg_parser.bot.handlers import _handle_clarification_response
from tg_parser.bot.states import ClarifyFlow
from tg_parser.bot.tools import (
    _build_no_results_suggestion,
    _channel_suggestion_lookup,
)

SHORT_PREFIX = "gen"
FULL_CHANNEL = "genotek"
OTHER_CHANNEL = "AgeManagment"
DM_CHAT_ID = 100_500_053


def _admin(user_id: str = "user-bug053") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="bug053",
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


class _FakeSource:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id


def _fake_state_repo_ctx(channel_ids: list[str]):
    @asynccontextmanager
    async def _ctx():
        repo = MagicMock()
        repo.list_sources = AsyncMock(return_value=[_FakeSource(c) for c in channel_ids])
        yield (repo, MagicMock())

    return _ctx


def _read_clarify_action(**overrides: Any) -> dict[str, Any]:
    base = {
        "kind": "read",
        "tool_name": "list_topics",
        "args": {"channel_id": SHORT_PREFIX, "limit": 20},
        "channel_arg": "channel_id",
        "suggestion": FULL_CHANNEL,
        "message": (
            f"Канал «{SHORT_PREFIX}» не найден. Возможно, вы имели в виду "
            f"«{FULL_CHANNEL}»? Ответьте «да», чтобы продолжить."
        ),
    }
    base.update(overrides)
    return base


def _gemini_function_call(name: str, args: dict) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"functionCall": {"name": name, "args": args}}]}}]
    }


def _sent_text(msg: MagicMock) -> str:
    return " ".join(str(c.args) for c in msg.answer.call_args_list)


@pytest.mark.asyncio
class TestBug053ChannelSuggestionLookupTiers:
    async def test_short_prefix_resolves_via_suggest_tier(self):
        """«gen» must fuzzy-match «genotek» at the 0.5 fallback tier."""
        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            _fake_state_repo_ctx([FULL_CHANNEL, OTHER_CHANNEL]),
        ):
            matched, available = await _channel_suggestion_lookup(SHORT_PREFIX, _admin())
        assert matched == FULL_CHANNEL
        assert FULL_CHANNEL in available

    async def test_suggest_tier_skipped_when_multiple_matches(self):
        """Two channels at 0.5 → no single suggestion (parity with subscription resolver)."""
        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            _fake_state_repo_ctx(["genotek", "genetics", OTHER_CHANNEL]),
        ):
            matched, _available = await _channel_suggestion_lookup(SHORT_PREFIX, _admin())
        assert matched is None

    async def test_build_no_results_attaches_read_clarify_for_short_prefix(self):
        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            _fake_state_repo_ctx([FULL_CHANNEL, OTHER_CHANNEL]),
        ):
            payload = await _build_no_results_suggestion(
                SHORT_PREFIX,
                _admin(),
                tool_name="list_topics",
                args={"channel_id": SHORT_PREFIX, "limit": 20},
            )
        clarify = payload["clarify_pending"]
        assert clarify["kind"] == "read"
        assert clarify["suggestion"] == FULL_CHANNEL
        assert FULL_CHANNEL in clarify["message"]
        assert "да" in clarify["message"].lower()


@pytest.mark.asyncio
class TestBug053ReadClarifyFollowUp:
    async def test_affirmative_reruns_list_topics_with_suggested_channel(self):
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        calls: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            calls.append((name, dict(args)))
            return {
                "total": 1,
                "offset": 0,
                "limit": 20,
                "has_more": False,
                "items": [
                    {
                        "n": 1,
                        "id": "topic-gen-1",
                        "title": "Genomics overview",
                        "type": "thematic",
                        "summary": "Summary.",
                        "items_count": 1,
                        "sources": [FULL_CHANNEL],
                    }
                ],
            }

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert len(calls) == 1
        name, args = calls[0]
        assert name == "list_topics"
        assert args["channel_id"] == FULL_CHANNEL
        agent.process_message.assert_not_called()
        assert "не совсем понимаю" not in _sent_text(msg).lower()

    async def test_bare_genotek_token_reruns_list_topics(self):
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(FULL_CHANNEL)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            invoked.append((name, dict(args)))
            return {"total": 1, "offset": 0, "limit": 20, "has_more": False, "items": []}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert invoked[0][0] == "list_topics"
        assert invoked[0][1]["channel_id"] == FULL_CHANNEL
        agent.process_message.assert_not_called()


@pytest.mark.asyncio
class TestBug053AgentReadContextGuard:
    async def test_agent_short_circuits_with_read_clarify_for_gen(self):
        agent = GeminiAgent(api_key="test-key")
        read_clarify = _read_clarify_action()
        tool_result = {
            "total": 0,
            "offset": 0,
            "limit": 20,
            "has_more": False,
            "items": [],
            "clarify_pending": read_clarify,
        }
        with (
            patch.object(
                agent,
                "_call_gemini",
                new=AsyncMock(
                    side_effect=[_gemini_function_call("list_topics", {"channel_id": SHORT_PREFIX})]
                ),
            ),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("покажи темы gen")

        assert result.clarify_pending is not None
        assert result.clarify_pending["suggestion"] == FULL_CHANNEL
        assert result.read_tools_called == []

    async def test_successful_list_topics_still_updates_read_context(self):
        agent = GeminiAgent(api_key="test-key")
        call_count = 0

        async def _fake_post(url, *, json, params):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count == 1:
                resp.json.return_value = _gemini_function_call(
                    "list_topics", {"channel_id": FULL_CHANNEL, "limit": 20}
                )
            else:
                resp.json.return_value = {
                    "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]
                }
            return resp

        agent._client.post = _fake_post

        with patch(
            "tg_parser.bot.agent.execute_tool",
            new_callable=AsyncMock,
            return_value={
                "total": 3,
                "items": [],
                "offset": 0,
                "limit": 20,
                "has_more": False,
            },
        ):
            result = await agent.process_message("покажи темы genotek")

        assert len(result.read_tools_called) == 1
        assert result.read_tools_called[0][1]["channel_id"] == FULL_CHANNEL
