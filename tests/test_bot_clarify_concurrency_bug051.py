"""BUG-051 — per-chat serialization prevents concurrent ClarifyFlow races.

When two inbound text updates for the same chat overlap while
``ClarifyFlow.awaiting_channel_clarification`` is armed (read clarify:
«enotek» → suggest «genotek»), pre-fix both turns could enter
``_handle_clarification_response`` interleaved, double-call ``list_topics``,
and emit duplicate list replies.

The production fix is ``ChatSerializationMiddleware``: a per-(bot_id, chat_id)
``asyncio.Lock`` on the top-level dispatcher entry for non-empty text messages.
Recursive ``handle_text`` reroutes do not re-enter the middleware, so no
reentrant lock is required.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message as AiogramMessage

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import AgentResult, GeminiAgent
from tg_parser.bot.handlers import handle_text
from tg_parser.bot.middleware import ChatSerializationMiddleware
from tg_parser.bot.states import ClarifyFlow

TYPO_INPUT = "enotek"
CORRECT_SUGGESTION = "genotek"
TOPIC_MARKER = "BUG051-concurrency-topic"
DM_CHAT_ID = 100_500_051
BOT_ID = 42


def _admin() -> CurrentUser:
    return CurrentUser(
        id="user-bug051",
        name="bug051",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _make_state(
    bot_id: int = BOT_ID,
    chat_id: int = DM_CHAT_ID,
    user_id: int = 67890,
) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = DM_CHAT_ID) -> MagicMock:
    msg = MagicMock(spec=AiogramMessage)
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.bot.id = BOT_ID
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


def _read_clarify_action(**overrides: Any) -> dict[str, Any]:
    base = {
        "kind": "read",
        "tool_name": "list_topics",
        "args": {"channel_id": TYPO_INPUT, "limit": 20},
        "channel_arg": "channel_id",
        "suggestion": CORRECT_SUGGESTION,
        "message": (
            f"Канал «{TYPO_INPUT}» не найден. Возможно, вы имели в виду "
            f"«{CORRECT_SUGGESTION}»? Ответьте «да», чтобы продолжить."
        ),
    }
    base.update(overrides)
    return base


def _sent_text(msg: MagicMock) -> str:
    return " ".join(str(c.args) for c in msg.answer.call_args_list)


async def _dispatch_through_middleware(
    middleware: ChatSerializationMiddleware,
    msg: MagicMock,
    *,
    agent: GeminiAgent,
    state: FSMContext,
    current_user: CurrentUser,
) -> None:
    async def _inner(event: AiogramMessage, _data: dict[str, Any]) -> None:
        await handle_text(event, agent=agent, state=state, current_user=current_user)

    await middleware(_inner, msg, {})


@pytest.mark.asyncio
class TestBug051ClarifyConcurrency:
    async def test_overlapping_clarify_responses_execute_once(self) -> None:
        """Two concurrent «genotek» replies while read-clarify is armed must not
        double-invoke ``list_topics`` or duplicate the rendered list."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )

        msg1 = _make_message(CORRECT_SUGGESTION)
        msg2 = _make_message(CORRECT_SUGGESTION)

        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(response_text="ignored follow-up")
        )

        execute_calls: list[tuple[str, dict[str, Any]]] = []
        release_first = asyncio.Event()

        async def slow_execute(name: str, args: dict, **_kw: Any) -> dict[str, Any]:
            execute_calls.append((name, dict(args)))
            await release_first.wait()
            return {
                "total": 1,
                "offset": 0,
                "limit": 20,
                "has_more": False,
                "items": [
                    {
                        "n": 1,
                        "id": "topic-bug051",
                        "title": TOPIC_MARKER,
                        "type": "thematic",
                        "summary": "Concurrency regression marker.",
                        "items_count": 1,
                        "sources": [CORRECT_SUGGESTION],
                    }
                ],
            }

        middleware = ChatSerializationMiddleware()

        async def run_turn(msg: MagicMock) -> None:
            with (
                patch("tg_parser.bot.handlers.execute_tool", new=slow_execute),
                patch(
                    "tg_parser.bot.handlers.verify_channel_exists",
                    new=AsyncMock(return_value=True),
                ),
            ):
                await _dispatch_through_middleware(
                    middleware,
                    msg,
                    agent=agent,
                    state=state,
                    current_user=_admin(),
                )

        task1 = asyncio.create_task(run_turn(msg1))
        for _ in range(100):
            if execute_calls:
                break
            await asyncio.sleep(0)

        assert len(execute_calls) == 1, "first turn must enter list_topics before second starts"
        task2 = asyncio.create_task(run_turn(msg2))
        await asyncio.sleep(0.01)
        assert len(execute_calls) == 1, "second turn must wait on the chat lock"

        release_first.set()
        await asyncio.gather(task1, task2)

        assert [name for name, _ in execute_calls] == ["list_topics"]
        assert execute_calls[0][1]["channel_id"] == CORRECT_SUGGESTION

        combined = _sent_text(msg1) + _sent_text(msg2)
        assert combined.count(TOPIC_MARKER) == 1
        # After the first turn clears ClarifyFlow, the second turn is a fresh
        # agent path — acceptable. The race fix is: no duplicate list_topics
        # / duplicate clarify list render while both turns overlap.
        agent.process_message.assert_called_once()
