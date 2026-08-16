"""
FSM regression suite for the Telegram bot — BUG-002 / BUG-004 closure.

Five areas under test:

* ``CONFIRM_PATTERN`` / ``REJECT_PATTERN`` / ``NEXT_PAGE_PATTERN`` —
  anchored regexes that decide whether a user reply is a yes/no/next or
  "something else" that should clear the FSM and re-route through the
  agent (D-4 default).
* ``GeminiAgent.process_message`` — must now return :class:`AgentResult`
  and surface ``preview_pending`` / ``pagination_pending`` from tool
  payloads. The dataclass is the contract handlers consume to arm
  :class:`ConfirmFlow` / :class:`PaginationFlow`.
* ``_handle_confirmation_response`` — deterministic execute path. The
  decisive regression is
  ``TestConfirmationResponseHandler.test_yes_after_remove_preview_does_not_call_add_channel``,
  guarding the exact 28.04 00:04 trace.
* ``_exec_list_topics`` — global ``n`` numbering across pages and
  ``pagination_pending`` payload that carries the channel filter
  unchanged into the next page (BUG-004 root cause).
* ``_handle_pagination_response`` — replays the stashed query on
  "ещё / next" without consulting the LLM, clears state on "стоп" and
  on terminal pages, and emits a soft-cap warning past 10 items.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import AgentResult, GeminiAgent
from tg_parser.bot.handlers import (
    CONFIRM_PATTERN,
    NEXT_PAGE_PATTERN,
    PAGINATION_SOFT_CAP,
    PENDING_TTL_SECONDS,
    REJECT_PATTERN,
    _format_paginated_list,
    _handle_confirmation_response,
    _handle_pagination_response,
    handle_text,
)
from tg_parser.bot.states import ConfirmFlow, PaginationFlow
from tg_parser.bot.tools import _exec_list_topics

_ADMIN = CurrentUser(
    id="admin-1",
    name="admin",
    role="admin",
    allowed_channel_ids=None,
    max_channels=100,
)

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
                "content": {"parts": [{"functionCall": {"name": name, "args": args}}]},
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
            _gemini_function_call("remove_channel", {"channel_id": "X", "confirm": True}),
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
            _gemini_function_call("add_channel", {"channel_id": "new_ch", "confirm": False}),
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
            created_at=datetime.now(UTC).isoformat(),
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
            created_at=datetime.now(UTC).isoformat(),
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

    async def test_handler_passes_confirm_flow_state_matching_preview(self) -> None:
        """BUG-009 (Session G) wiring contract — the handler MUST pass
        ``confirm_flow_state`` whose ``tool_name`` and original ``args``
        match the previewed action so the guard in ``execute_tool`` lets
        the call through. A miss here would mean the legitimate confirm
        path itself trips the guard (Stop-the-world condition).
        """
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "add_channel",
                "args": {"channel_id": "channel_a"},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        captured_kwargs: list[dict[str, Any]] = []

        async def mock_execute(name: str, args: dict, **kwargs):
            captured_kwargs.append({"name": name, "args": dict(args), "kwargs": dict(kwargs)})
            return {"ok": True, "message": "done"}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert len(captured_kwargs) == 1
        invocation = captured_kwargs[0]
        assert invocation["name"] == "add_channel"
        assert invocation["args"] == {"channel_id": "channel_a", "confirm": True}
        assert invocation["kwargs"]["confirm_flow_state"] == {
            "tool_name": "add_channel",
            "args": {"channel_id": "channel_a"},
        }

    async def test_no_clears_state_and_does_not_execute(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(UTC).isoformat(),
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

    async def test_unrelated_text_keeps_fsm_and_prompts_for_known_tokens(self) -> None:
        """BUG-032 closure: a genuine unknown NON-command token (not a known
        affirmative / negative per :func:`classify_confirmation_token`, and not
        an explicit new command / question per BUG-048's
        :func:`_looks_like_new_intent`) MUST keep the FSM armed and prompt the
        user for one of the accepted tokens, instead of clearing state and
        silently routing the reply to the LLM (which historically produced the
        opaque «Я не совсем понимаю ваш ответ» response — BUG_LOG § BUG-032).

        Note (BUG-048): an explicit new COMMAND / QUESTION reply (e.g. «покажи
        каналы») now intentionally BREAKS OUT of the ConfirmFlow and reroutes —
        that path is covered by ``test_bot_intent_break_bug048.py``. This test
        pins the residual BUG-032 contract for a genuine non-command token.
        """
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("синий слон")
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
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        agent.process_message.assert_not_called()
        # User-facing reply must list both an affirmative and a negative
        # token so the user can recover without re-issuing the intent.
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "да" in sent.lower() and "нет" in sent.lower()
        # The pre-fix opaque «не совсем понимаю» phrase MUST NOT appear.
        assert "не совсем понимаю" not in sent.lower()

    async def test_ttl_expiry_clears_state_and_does_not_execute(self) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        old = datetime.now(UTC) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
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
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="Привет!"))

        await handle_text(msg, agent=agent, state=state, current_user=None)

        assert await state.get_state() is None


# ---------------------------------------------------------------------------
# BUG-009 (Session G) — server-side guard in ``execute_tool`` blocks
# LLM-hallucinated ``add_channel(confirm=True)`` on suggestion-confirm replies
# ---------------------------------------------------------------------------


class TestBug009SuggestionConfirmGuard:
    """Direct integration test for the 2026-04-30 15:15:44 UTC production
    trace: read-tool returns ``suggestion=...`` → user replies "да X" →
    if Gemini hallucinates ``add_channel(confirm=True)`` instead of
    re-running ``list_topics``, the server-side guard MUST reject the
    call (``error_class="ConfirmFlowMismatch"``) and the executor MUST
    NOT run.

    This complements the unit tests in
    ``tests/test_bot_execute_tool_guard.py`` by exercising the full
    ``GeminiAgent.process_message`` path with a real (non-mocked)
    ``execute_tool`` so the guard's wiring through ``agent.py`` is
    proven end-to-end.
    """

    async def test_yes_after_suggestion_does_not_call_add_channel(self) -> None:
        """LLM forced to call ``add_channel(confirm=True)`` after a
        suggestion-context reply — guard blocks the executor and the
        agent receives a ``ConfirmFlowMismatch`` payload it can recover
        from. No DB row is ever attempted (executor sentinel never fires).
        """
        agent = GeminiAgent(api_key="test-key")
        gemini_responses = [
            # Turn 1: LLM hallucinates the BUG-009 failure mode — calling
            # the write-tool with confirm=True directly, bypassing FSM.
            _gemini_function_call(
                "add_channel",
                {"channel_id": "AgeManagment", "confirm": True},
            ),
            # Turn 2: after receiving ConfirmFlowMismatch, LLM produces
            # a graceful user-facing message (per prompt v1.4.0 recovery hint).
            _gemini_text_only("Произошла ошибка подтверждения — повторите запрос."),
        ]

        executor_invoked: list[dict[str, Any]] = []

        async def sentinel_add_channel(args, **_kw):
            executor_invoked.append(dict(args))
            return {"ok": True, "channel_id": args.get("channel_id")}

        captured_function_responses: list[dict[str, Any]] = []
        responses_iter = iter(gemini_responses)

        async def stubbed_call_gemini(contents, *, read_context=None):
            # Capture every functionResponse the agent feeds back so the
            # test can assert the guard's rejection reached the LLM turn.
            for item in contents:
                if item.get("role") == "function":
                    for part in item.get("parts", []):
                        fr = part.get("functionResponse")
                        if fr is not None:
                            captured_function_responses.append(fr)
            return next(responses_iter)

        with (
            patch.object(
                agent,
                "_call_gemini",
                side_effect=stubbed_call_gemini,
            ),
            patch.dict(
                "tg_parser.bot.tools._TOOL_EXECUTORS",
                {"add_channel": sentinel_add_channel},
                clear=False,
            ),
        ):
            result = await agent.process_message("да AgeManagment")

        # Guard must have prevented the executor from running.
        assert executor_invoked == [], (
            "BUG-009 regression: ``add_channel`` executor ran despite the "
            f"guard. Got: {executor_invoked}"
        )

        # The agent loop must have surfaced the structured error back to
        # the LLM via a functionResponse payload.
        assert any(
            isinstance(fr.get("response"), dict)
            and fr["response"].get("error_class") == "ConfirmFlowMismatch"
            for fr in captured_function_responses
        ), (
            "Expected at least one functionResponse with "
            "error_class='ConfirmFlowMismatch' to be sent back to the LLM "
            f"after the guard rejected the call. Got: {captured_function_responses}"
        )

        # And the agent loop must have terminated with a user-facing text
        # response (not crashed / not stuck in a tool-call loop).
        assert isinstance(result, AgentResult)
        assert result.response_text


# ---------------------------------------------------------------------------
# Pagination — regex / tool-payload / handler / numbering
# ---------------------------------------------------------------------------


class TestNextPagePattern:
    @pytest.mark.parametrize(
        "text",
        [
            "ещё",
            "еще",
            "Дальше",
            "далее",
            "next",
            "more",
            "продолжай",
            "продолжить",
            "следующую страницу",
        ],
    )
    def test_next_matches(self, text: str) -> None:
        assert NEXT_PAGE_PATTERN.match(text)

    @pytest.mark.parametrize(
        "text",
        [
            "покажи каналы",
            "дайте каналы",
            "привет",
            "удали канал",
        ],
    )
    def test_next_does_not_match_unrelated(self, text: str) -> None:
        assert not NEXT_PAGE_PATTERN.match(text)


class _FakeTopicType:
    """Stand-in for :class:`tg_parser.domain.models.TopicType`."""

    def __init__(self, value: str = "singleton") -> None:
        self.value = value


class _FakeCard:
    """Minimal duck-typed TopicCard for ``_exec_list_topics``."""

    def __init__(self, idx: int, channel_id: str = "channel_a") -> None:
        self.id = f"topic:{channel_id}:{idx}"
        self.title = f"Topic #{idx}"
        self.summary = f"Summary for topic {idx}"
        self.type = _FakeTopicType("singleton")
        self.sources = [channel_id]


def _patch_processing_repos(cards: list[_FakeCard], bundles: list | None = None):
    """Patch ``processing_repos`` ctx-manager used inside ``_exec_list_topics``."""
    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    db = MagicMock()
    topic_card_repo.list_by_channel.return_value = cards
    topic_card_repo.list_by_channels.return_value = cards
    topic_card_repo.list_all.return_value = cards
    topic_bundle_repo.list_by_channel.return_value = bundles or []
    topic_bundle_repo.list_all.return_value = bundles or []

    @asynccontextmanager
    async def mock_ctx():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

    # ``_exec_list_topics`` does ``from tg_parser.services.db_context import
    # processing_repos`` lazily, so we patch the source module.
    return patch("tg_parser.services.db_context.processing_repos", new=mock_ctx)


class TestListTopicsPagination:
    """``_exec_list_topics`` payload contract (BUG-004 fix surface)."""

    async def test_first_page_emits_pagination_pending(self) -> None:
        cards = [_FakeCard(i) for i in range(25)]
        with _patch_processing_repos(cards):
            result = await _exec_list_topics(
                {"channel_id": "channel_a", "offset": 0, "limit": 10},
                current_user=_ADMIN,
            )

        assert result["total"] == 25
        assert result["offset"] == 0
        assert result["limit"] == 10
        assert result["has_more"] is True
        # Critical: pagination hint carries the channel filter UNCHANGED
        assert "pagination_pending" in result
        pp = result["pagination_pending"]
        assert pp["tool_name"] == "list_topics"
        assert pp["args"]["channel_id"] == "channel_a"
        assert pp["args"]["offset"] == 10
        assert pp["args"]["limit"] == 10
        assert pp["total"] == 25
        # Items have a 1-based global ``n``
        assert [item["n"] for item in result["items"]] == list(range(1, 11))

    async def test_second_page_continues_global_numbering(self) -> None:
        """The numbering half of BUG-004: page 2 must start at n=11, not n=1."""
        cards = [_FakeCard(i) for i in range(25)]
        with _patch_processing_repos(cards):
            result = await _exec_list_topics(
                {"channel_id": "channel_a", "offset": 10, "limit": 10},
                current_user=_ADMIN,
            )

        assert [item["n"] for item in result["items"]] == list(range(11, 21))
        assert result["pagination_pending"]["args"]["offset"] == 20

    async def test_terminal_page_omits_pagination_pending(self) -> None:
        cards = [_FakeCard(i) for i in range(25)]
        with _patch_processing_repos(cards):
            result = await _exec_list_topics(
                {"channel_id": "channel_a", "offset": 20, "limit": 10},
                current_user=_ADMIN,
            )

        assert result["has_more"] is False
        assert "pagination_pending" not in result
        # Last 5 items numbered 21..25
        assert [item["n"] for item in result["items"]] == list(range(21, 26))

    async def test_pagination_args_strip_offset_then_advance(self) -> None:
        """Original ``offset`` must be replaced, not duplicated, in next args."""
        cards = [_FakeCard(i) for i in range(25)]
        with _patch_processing_repos(cards):
            result = await _exec_list_topics(
                {
                    "channel_id": "channel_a",
                    "topic_type": "singleton",
                    "offset": 5,
                    "limit": 10,
                },
                current_user=_ADMIN,
            )
        next_args = result["pagination_pending"]["args"]
        assert next_args["offset"] == 15
        assert next_args["limit"] == 10
        assert next_args["channel_id"] == "channel_a"
        # topic_type filter is preserved across pages
        assert next_args["topic_type"] == "singleton"


class TestFormatPaginatedList:
    def test_renders_global_numbering_and_footer(self) -> None:
        result = {
            "total": 25,
            "offset": 10,
            "limit": 10,
            "has_more": True,
            "items": [
                {"n": 11, "title": "T11", "summary": "S11"},
                {"n": 12, "title": "T12", "summary": "S12"},
            ],
        }
        text = _format_paginated_list("list_topics", result)
        assert "<b>11.</b>" in text
        assert "<b>12.</b>" in text
        assert "Показано 11–12 из 25" in text
        assert "ещё" in text.lower()

    def test_terminal_page_drops_more_hint(self) -> None:
        result = {
            "total": 25,
            "offset": 20,
            "limit": 10,
            "has_more": False,
            "items": [{"n": 21, "title": "T21"}],
        }
        text = _format_paginated_list("list_topics", result)
        assert "ещё" not in text.lower()

    def test_soft_cap_appends_warning(self) -> None:
        result = {
            "total": 30,
            "offset": 10,
            "limit": 5,
            "has_more": True,
            "items": [{"n": 11, "title": f"T{11 + i}"} for i in range(5)],
        }
        text = _format_paginated_list("list_topics", result, soft_cap_hit=True)
        assert "Уже показано" in text
        assert "15" in text


class TestPaginationFlowHandler:
    @staticmethod
    async def _arm_pagination(state: FSMContext, *, items_shown: int = 5) -> None:
        await state.set_state(PaginationFlow.has_active_list)
        await state.update_data(
            pagination={
                "tool_name": "list_topics",
                "args": {
                    "channel_id": "channel_a",
                    "offset": items_shown,
                    "limit": 5,
                },
                "total": 25,
                "offset": items_shown,
                "limit": 5,
            },
            items_shown=items_shown,
            created_at=datetime.now(UTC).isoformat(),
        )

    async def test_next_replays_query_with_stashed_args(self) -> None:
        state = _make_state()
        await self._arm_pagination(state, items_shown=5)
        msg = _make_message("ещё")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[tuple[str, dict[str, Any]]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            invoked.append((name, dict(args)))
            return {
                "total": 25,
                "offset": 5,
                "limit": 5,
                "has_more": True,
                "items": [{"n": 6, "title": f"T{i}"} for i in range(6, 11)],
                "pagination_pending": {
                    "tool_name": "list_topics",
                    "args": {
                        "channel_id": "channel_a",
                        "offset": 10,
                        "limit": 5,
                    },
                    "total": 25,
                    "offset": 10,
                    "limit": 5,
                },
            }

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_pagination_response(msg, agent, state, current_user=None)

        # Critical: replays the stashed query — channel_id intact, no LLM
        assert len(invoked) == 1
        assert invoked[0][0] == "list_topics"
        assert invoked[0][1]["channel_id"] == "channel_a"
        assert invoked[0][1]["offset"] == 5
        agent.process_message.assert_not_called()

        # State updates with new pagination
        new_state = await state.get_state()
        assert new_state == PaginationFlow.has_active_list.state
        data = await state.get_data()
        assert data["pagination"]["args"]["offset"] == 10
        assert data["items_shown"] == 10

    async def test_next_on_terminal_page_clears_state(self) -> None:
        state = _make_state()
        await self._arm_pagination(state, items_shown=20)
        msg = _make_message("дальше")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(_name: str, _args: dict, **_kw):
            return {
                "total": 25,
                "offset": 20,
                "limit": 5,
                "has_more": False,
                "items": [{"n": 21 + i, "title": f"T{21 + i}"} for i in range(5)],
            }

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_pagination_response(msg, agent, state, current_user=None)

        assert await state.get_state() is None

    async def test_stop_clears_state_without_execute(self) -> None:
        state = _make_state()
        await self._arm_pagination(state, items_shown=5)
        msg = _make_message("стоп")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_pagination_response(msg, agent, state, current_user=None)

        assert invoked == []
        assert await state.get_state() is None

    async def test_unrelated_text_clears_state_and_routes_to_agent(self) -> None:
        state = _make_state()
        await self._arm_pagination(state, items_shown=5)
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
        assert agent.process_message.call_args[0][0] == "покажи каналы"

    async def test_ttl_expiry_clears_state(self) -> None:
        state = _make_state()
        await state.set_state(PaginationFlow.has_active_list)
        old = datetime.now(UTC) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
        await state.update_data(
            pagination={
                "tool_name": "list_topics",
                "args": {"channel_id": "channel_a", "offset": 5, "limit": 5},
                "total": 25,
                "offset": 5,
                "limit": 5,
            },
            items_shown=5,
            created_at=old.isoformat(),
        )
        msg = _make_message("ещё")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_pagination_response(msg, agent, state, current_user=None)

        assert invoked == []
        assert await state.get_state() is None

    async def test_soft_cap_warning_appended_when_threshold_crossed(self) -> None:
        # Start at 8 items shown; the next page brings the total to 13,
        # crossing the soft-cap threshold of 10.
        state = _make_state()
        await self._arm_pagination(state, items_shown=8)
        # Re-arm with limit=5, args.offset=8
        await state.update_data(
            pagination={
                "tool_name": "list_topics",
                "args": {"channel_id": "channel_a", "offset": 8, "limit": 5},
                "total": 25,
                "offset": 8,
                "limit": 5,
            },
            items_shown=8,
        )
        msg = _make_message("ещё")
        agent = MagicMock()

        async def mock_execute(_name: str, _args: dict, **_kw):
            return {
                "total": 25,
                "offset": 8,
                "limit": 5,
                "has_more": True,
                "items": [{"n": 9 + i, "title": f"T{9 + i}"} for i in range(5)],
                "pagination_pending": {
                    "tool_name": "list_topics",
                    "args": {"channel_id": "channel_a", "offset": 13, "limit": 5},
                    "total": 25,
                    "offset": 13,
                    "limit": 5,
                },
            }

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_pagination_response(msg, agent, state, current_user=None)

        sent_text = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "Уже показано" in sent_text
        # State preserved — user can keep paging
        assert await state.get_state() == PaginationFlow.has_active_list.state


class TestHandleTextSetsPaginationFlow:
    async def test_pagination_pending_arms_pagination_flow(self) -> None:
        state = _make_state()
        msg = _make_message("покажи темы по genotek")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="Topic 1, Topic 2, ...",
                pagination_pending={
                    "tool_name": "list_topics",
                    "args": {
                        "channel_id": "genotek",
                        "offset": 10,
                        "limit": 10,
                    },
                    "total": 50,
                    "offset": 10,
                    "limit": 10,
                },
            )
        )
        await handle_text(msg, agent=agent, state=state, current_user=None)

        assert await state.get_state() == PaginationFlow.has_active_list.state
        data = await state.get_data()
        assert data["pagination"]["args"]["channel_id"] == "genotek"
        assert data["items_shown"] == 10

    async def test_preview_takes_precedence_over_pagination(self) -> None:
        """When both hints fire, ConfirmFlow wins (write-op safety > UX)."""
        state = _make_state()
        msg = _make_message("удали канал genotek")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="Подтвердите удаление?",
                preview_pending={
                    "tool_name": "remove_channel",
                    "args": {"channel_id": "genotek"},
                },
                pagination_pending={
                    "tool_name": "list_topics",
                    "args": {"channel_id": "genotek", "offset": 10, "limit": 10},
                    "total": 50,
                    "offset": 10,
                    "limit": 10,
                },
            )
        )
        await handle_text(msg, agent=agent, state=state, current_user=None)

        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state


class TestSoftCapConstant:
    def test_default_soft_cap_is_ten(self) -> None:
        assert PAGINATION_SOFT_CAP == 10
