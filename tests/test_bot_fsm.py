"""
FSM regression suite for the Telegram bot — BUG-002 / BUG-004 closure.

Three areas under test:

* ``CONFIRM_PATTERN`` / ``REJECT_PATTERN`` — anchored regexes that decide
  whether a user reply to a preview is a yes, a no, or "something else"
  that should clear the FSM and re-route through the agent (D-4 default).

* ``GeminiAgent.process_message`` — must now return :class:`AgentResult`
  and surface ``preview_pending`` whenever a tool replies with
  ``preview=True``. ``AgentResult`` is the contract the FSM handler
  consumes to arm :class:`ConfirmFlow`.

* ``_handle_confirmation_response`` — deterministic execute path. The
  decisive regression test is
  :meth:`TestConfirmationResponseHandler.test_yes_after_remove_preview_does_not_call_add_channel`,
  which guards against the exact 28.04 00:04 trace where a bare "да"
  caused the bot to invent ``add_channel(test_channel_123)``. Post-fix,
  the LLM is never reached on confirmation, so this class of
  hallucination is structurally impossible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.bot.agent import AgentResult, GeminiAgent
from tg_parser.bot.handlers import (
    CONFIRM_PATTERN,
    PENDING_TTL_SECONDS,
    REJECT_PATTERN,
    _handle_confirmation_response,
    handle_text,
)
from tg_parser.bot.states import ConfirmFlow


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_state(bot_id: int = 42, chat_id: int = 12345, user_id: int = 67890) -> FSMContext:
    """Real FSMContext backed by an in-memory storage — no aiogram bot required."""
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = 12345) -> MagicMock:
    """Minimal ``Message`` mock — only the surface our handlers touch."""
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


def _gemini_text_only(text: str) -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ]
    }


def _gemini_function_call(name: str, args: dict) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"functionCall": {"name": name, "args": args}}]
                },
            }
        ]
    }


# ---------------------------------------------------------------------------
# Regex sanity — the gate between LLM and deterministic execute
# ---------------------------------------------------------------------------


class TestConfirmRejectPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "да",
            "Да",
            "yes",
            "YES",
            "ok",
            "ОК",
            "Подтверждаю",
            "подтверди",
            "ага",
            "Уверен",
            "уверена",
            "конечно",
            "давай",
        ],
    )
    def test_confirm_matches(self, text: str) -> None:
        assert CONFIRM_PATTERN.match(text)

    @pytest.mark.parametrize(
        "text",
        [
            "нет",
            "НЕТ",
            "no",
            "отмена",
            "cancel",
            "стоп",
            "stop",
            "не надо",
            "передумал",
        ],
    )
    def test_reject_matches(self, text: str) -> None:
        assert REJECT_PATTERN.match(text)

    @pytest.mark.parametrize(
        "text",
        [
            "покажи каналы",
            "добавь канал genotek",
            "привет",
            "дайте каналы",
            "yesno",
        ],
    )
    def test_neither_matches_normal_requests(self, text: str) -> None:
        """Free-form requests must NOT be misclassified as yes/no."""
        assert not CONFIRM_PATTERN.match(text)
        assert not REJECT_PATTERN.match(text)


# ---------------------------------------------------------------------------
# AgentResult contract — process_message returns structured result
# ---------------------------------------------------------------------------


class TestProcessMessageReturnsAgentResult:
    async def test_returns_agent_result_for_plain_text_response(self) -> None:
        agent = GeminiAgent(api_key="test-key")
        with patch.object(
            agent,
            "_call_gemini",
            new=AsyncMock(return_value=_gemini_text_only("Hello")),
        ):
            result = await agent.process_message("hi")
        assert isinstance(result, AgentResult)
        assert result.response_text == "Hello"
        assert result.preview_pending is None
        assert result.pagination_pending is None

    async def test_captures_preview_pending_from_tool_payload(self) -> None:
        """Tool payload with ``preview=True`` must populate AgentResult.preview_pending."""
        agent = GeminiAgent(api_key="test-key")
        gemini_responses = [
            _gemini_function_call("remove_channel", {"channel_id": "channel_a"}),
            _gemini_text_only("Подтвердите удаление channel_a?"),
        ]
        tool_result = {
            "preview": True,
            "tool": "remove_channel",
            "args": {"channel_id": "channel_a"},
            "message": "Подтвердите удаление channel_a?",
        }
        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("удали channel_a")
        assert result.preview_pending == {
            "tool_name": "remove_channel",
            "args": {"channel_id": "channel_a"},
        }

    async def test_drops_preview_when_llm_self_confirms_in_same_loop(self) -> None:
        """If the LLM passes ``confirm=True`` itself, the FSM hint must drop."""
        agent = GeminiAgent(api_key="test-key")
        gemini_responses = [
            _gemini_function_call(
                "remove_channel", {"channel_id": "X", "confirm": True}
            ),
            _gemini_text_only("Канал X помечен как удалённый"),
        ]
        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value={"ok": True, "message": "Done"}),
            ),
        ):
            result = await agent.process_message("удали X")
        assert result.preview_pending is None

    async def test_preview_args_strip_confirm_field(self) -> None:
        """Original args stashed for FSM must not carry ``confirm`` from the LLM."""
        agent = GeminiAgent(api_key="test-key")
        gemini_responses = [
            # LLM erroneously includes ``confirm=False`` — handler must drop it.
            _gemini_function_call(
                "add_channel", {"channel_id": "new_ch", "confirm": False}
            ),
            _gemini_text_only("Добавить new_ch?"),
        ]
        tool_result = {
            "preview": True,
            "tool": "add_channel",
            "args": {"channel_id": "new_ch"},
            "message": "Добавить new_ch?",
        }
        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("добавь new_ch")
        assert result.preview_pending is not None
        assert "confirm" not in result.preview_pending["args"]
        assert result.preview_pending["args"] == {"channel_id": "new_ch"}


# ---------------------------------------------------------------------------
# ConfirmFlow handler — deterministic execute path
# ---------------------------------------------------------------------------


class TestConfirmationResponseHandler:
    async def test_yes_executes_original_tool_with_confirm_true(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "channel_a"},
            },
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        calls: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            calls.append((name, dict(args)))
            return {"ok": True, "message": "Канал помечен как удалённый"}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert calls == [
            ("remove_channel", {"channel_id": "channel_a", "confirm": True}),
        ]
        assert await state.get_state() is None
        # Critical: the LLM is NEVER consulted on a confirmation
        agent.process_message.assert_not_called()
        # And the tool's own ``message`` is rendered to the user
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "помечен как удалённый" in sent

    async def test_yes_after_remove_preview_does_not_call_add_channel(self) -> None:
        """Trace 28.04 00:04 regression — 'да' must invoke ONLY remove_channel.

        Pre-fix history: ``handle_text`` routed the user's "да" through
        Gemini, which had no memory of the just-issued
        ``remove_channel(test_channel_123)`` preview and hallucinated
        ``add_channel(test_channel_123)`` instead, creating a placeholder
        row in the production DB. The FSM handler now bypasses the LLM
        entirely on a confirmation, so the only tool that can run is the
        one stashed in ``ConfirmFlow.awaiting_confirmation`` data.
        """
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "old_channel"},
            },
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, args: dict, **_kw):
            invoked.append(name)
            return {"ok": True, "message": f"{name} done"}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert invoked == ["remove_channel"], (
            "FSM must invoke ONLY the previewed tool; "
            f"any constructive op like add_channel is a regression. Got: {invoked}"
        )
        assert "add_channel" not in invoked
        agent.process_message.assert_not_called()

    async def test_no_clears_state_and_does_not_execute(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        msg = _make_message("нет")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert invoked == []
        assert await state.get_state() is None

    async def test_unrelated_text_clears_state_and_routes_to_agent(self) -> None:
        """D-4 default: anything that isn't yes/no falls through to a fresh agent call."""
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        msg = _make_message("покажи каналы")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(response_text="Список каналов...")
        )

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await handle_text(msg, agent=agent, state=state, current_user=None)

        assert invoked == []
        assert await state.get_state() is None
        agent.process_message.assert_called_once()
        # The original user text is what the agent receives, not "покажи каналы"+something
        assert agent.process_message.call_args[0][0] == "покажи каналы"

    async def test_ttl_expiry_clears_state_and_does_not_execute(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        old = datetime.now(timezone.utc) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=old.isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert invoked == []
        assert await state.get_state() is None
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "истекл" in sent.lower()


# ---------------------------------------------------------------------------
# handle_text → ConfirmFlow transition
# ---------------------------------------------------------------------------


class TestHandleTextSetsConfirmFlow:
    async def test_preview_pending_arms_confirm_flow(self) -> None:
        """When the agent reports preview_pending, handle_text MUST set FSM."""
        state = _make_state()
        msg = _make_message("удали channel_x")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="Подтвердите удаление?",
                preview_pending={
                    "tool_name": "remove_channel",
                    "args": {"channel_id": "channel_x"},
                },
            )
        )

        await handle_text(msg, agent=agent, state=state, current_user=None)

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        data = await state.get_data()
        assert data["pending_action"] == {
            "tool_name": "remove_channel",
            "args": {"channel_id": "channel_x"},
        }
        assert "created_at" in data

    async def test_no_preview_pending_leaves_state_clear(self) -> None:
        state = _make_state()
        msg = _make_message("привет")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(response_text="Привет!")
        )

        await handle_text(msg, agent=agent, state=state, current_user=None)

        assert await state.get_state() is None
