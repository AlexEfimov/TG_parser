"""Regression suite for the bot conversational-layer cluster BUG-039..042.

These four defects surfaced in the 2026-05-31 production real-fire smoke of
the (closed) BUG-031..034 ``subscribe_digest`` cluster, against prod SHA
``39b6ba2``. They are genuine residual gaps in the conversational /
clarification layer — see ``docs/notes/BUG_LOG.md`` § BUG-039 / 040 / 041 /
042 and ``docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md`` § Results
2026-05-31 for the source-of-truth traces.

Each test reproduces a specific trace and is written to FAIL on the pre-fix
HEAD (``6ae610f``) — the fix introduces:

* ``ClarifyFlow`` + ``AgentResult.clarify_pending`` so a space-typo
  clarification «да» is actionable (BUG-039) and a bare channel-name reply
  mid-flow is interpreted in-flow rather than re-routed to ``update_channel``
  / ``list_topics`` (BUG-040);
* ``AgentResult.preview_message`` + deterministic preview rendering so the
  cron «0 * * * *» is no longer truncated by the LLM paraphrase (BUG-042);
* a ``prompts/bot.yaml`` hard rule forbidding the LLM from pre-normalizing
  channel names + a ``verify_channel_exists`` defense-in-depth helper
  (BUG-041).

Synthetic-only fixtures: no real prod channel / chat-id fixtures appear here
(mirrors the guard in ``tests/test_bot_channel_name_parser.py``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import AgentResult, GeminiAgent
from tg_parser.bot.handlers import PENDING_TTL_SECONDS, handle_text
from tg_parser.bot.states import ConfirmFlow, PaginationFlow
from tg_parser.bot.tools import (
    _NO_RESULTS_AVAILABLE_CAP,
    _build_no_results_suggestion,
    _exec_subscribe_digest,
    _exec_subscribe_watchlist,
)

# New symbols introduced by the BUG-039..042 fix. Imported defensively so the
# module still COLLECTS against the pre-fix HEAD — each test then fails on its
# own behavioural assertion (proving the trace reproduces) rather than the
# whole module erroring at import time.
try:  # pragma: no cover — branch exists for pre-fix self-review only
    from tg_parser.bot.handlers import _format_read_result, _handle_clarification_response
except ImportError:  # pragma: no cover
    _handle_clarification_response = None  # type: ignore[assignment]
    _format_read_result = None  # type: ignore[assignment]

try:  # pragma: no cover
    from tg_parser.bot.states import ClarifyFlow
except ImportError:  # pragma: no cover
    ClarifyFlow = None  # type: ignore[assignment]

try:  # pragma: no cover
    from tg_parser.bot.tools import verify_channel_exists
except ImportError:  # pragma: no cover
    verify_channel_exists = None  # type: ignore[assignment]

# Empirical BUG-034/041 trigger (carried verbatim from the smoke transcript).
TYPO_INPUT = "pro fendocrinologist"
CORRECT_SUGGESTION = "profendocrinologist"
FULL_CRON = "0 * * * *"
DM_CHAT_ID = 100_500_077


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-bug039") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="bug039",
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


def _gemini_text_only(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


def _gemini_function_call(name: str, args: dict) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"functionCall": {"name": name, "args": args}}]}}]
    }


def _clarify_action(**overrides: Any) -> dict[str, Any]:
    base = {
        "tool_name": "subscribe_digest",
        "args": {
            "name": "Ежечасный дайджест",
            "channel_ids": [TYPO_INPUT],
            "cron_expression": FULL_CRON,
            "timezone": "Europe/Moscow",
        },
        "channel_index": 0,
        "suggestion": CORRECT_SUGGESTION,
    }
    base.update(overrides)
    return base


def _read_clarify_action(**overrides: Any) -> dict[str, Any]:
    """BUG-043: a ``clarify_pending`` for the channel-not-found READ surface."""
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


class _FakeSource:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id


def _fake_state_repo_ctx(channel_ids: list[str]):
    """Patch target for ``ingestion_state_repo`` returning fixed sources."""

    @asynccontextmanager
    async def _ctx():
        repo = MagicMock()
        repo.list_sources = AsyncMock(return_value=[_FakeSource(c) for c in channel_ids])
        yield (repo, MagicMock())

    return _ctx


def _sent_text(msg: MagicMock) -> str:
    return " ".join(str(c.args) for c in msg.answer.call_args_list)


# ===========================================================================
# BUG-039 — channel-name clarification suggestion is actionable (not a dead-end)
# ===========================================================================


@pytest.mark.asyncio
class TestBug039ClarificationIsActionable:
    async def test_executor_space_typo_emits_clarify_pending(self):
        """The subscribe executor must attach a ``clarify_pending`` hint to the
        space-typo rejection so the framework can arm a recoverable FSM.

        Pre-fix: the rejection is a bare error with no ``clarify_pending`` —
        ``result["clarify_pending"]`` raises ``KeyError``.
        """
        result = await _exec_subscribe_digest(
            {
                "name": "morning",
                "channel_ids": [TYPO_INPUT],
                "cron_expression": "0 9 * * *",
            },
            current_user=_admin(),
            bot=None,
            chat_id=DM_CHAT_ID,
        )
        assert result["error_class"] == "InvalidChannelUsername"
        assert result["suggestion"] == CORRECT_SUGGESTION
        clarify = result["clarify_pending"]
        assert clarify["tool_name"] == "subscribe_digest"
        assert clarify["channel_index"] == 0
        assert clarify["suggestion"] == CORRECT_SUGGESTION
        assert clarify["args"]["channel_ids"] == [TYPO_INPUT]
        assert "confirm" not in clarify["args"]

    async def test_agent_short_circuits_with_deterministic_clarification(self):
        """The agent must return the clarification VERBATIM + a clarify hint,
        WITHOUT a second LLM turn re-authoring it.

        Pre-fix: ``AgentResult`` has no ``clarify_pending`` attribute and the
        loop feeds the error back to the LLM (a 2nd ``_call_gemini`` →
        ``StopAsyncIteration`` here).
        """
        agent = GeminiAgent(api_key="test-key")
        clarification = (
            f"Канал «{TYPO_INPUT}» содержит пробелы — Telegram usernames не "
            f"могут содержать пробелы. Возможно, вы имели в виду "
            f"«{CORRECT_SUGGESTION}»?"
        )
        tool_error = {
            "error": clarification,
            "error_class": "InvalidChannelUsername",
            "suggestion": CORRECT_SUGGESTION,
            "clarify_pending": _clarify_action(),
        }
        # Exactly ONE gemini response — a second call (LLM re-author) would
        # raise StopAsyncIteration, proving the loop short-circuited.
        with (
            patch.object(
                agent,
                "_call_gemini",
                new=AsyncMock(
                    side_effect=[
                        _gemini_function_call(
                            "subscribe_digest",
                            {"name": "morning", "channel_ids": [TYPO_INPUT]},
                        )
                    ]
                ),
            ),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_error),
            ),
        ):
            result = await agent.process_message("подпиши на дайджест pro fendocrinologist")

        assert result.clarify_pending is not None
        assert result.clarify_pending["suggestion"] == CORRECT_SUGGESTION
        assert CORRECT_SUGGESTION in result.response_text
        assert "не совсем понимаю" not in result.response_text.lower()

    async def test_handle_text_arms_clarify_flow(self):
        """``handle_text`` must arm ``ClarifyFlow`` from ``clarify_pending``."""
        state = _make_state()
        msg = _make_message("подпиши на дайджест pro fendocrinologist")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="… Возможно, вы имели в виду «profendocrinologist»?",
                clarify_pending=_clarify_action(),
            )
        )
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        data = await state.get_data()
        assert data["clarify_action"]["suggestion"] == CORRECT_SUGGESTION

    async def test_affirmative_reruns_subscribe_with_suggestion(self):
        """«да» on the clarification re-runs subscribe with the suggested
        channel and transitions to ConfirmFlow — NOT the opaque catch-all.

        This is the exact BUG-039 trace: clarification → «да» → actionable.
        """
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        calls: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            calls.append((name, dict(args)))
            return {
                "preview": True,
                "tool": "subscribe_digest",
                "message": (
                    "Preview: создать подписку «Ежечасный дайджест» на 1 канал(ов) "
                    f"по расписанию <code>{FULL_CRON}</code> (Europe/Moscow). "
                    "Подтвердите [да/нет]."
                ),
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
        assert name == "subscribe_digest"
        assert args["channel_ids"] == [CORRECT_SUGGESTION]
        assert "confirm" not in args
        # Re-run produced a preview → chat moves to ConfirmFlow.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        # The LLM is NEVER consulted on a clarification turn.
        agent.process_message.assert_not_called()
        # The opaque catch-all must NOT appear.
        assert "не совсем понимаю" not in _sent_text(msg).lower()


# ===========================================================================
# BUG-040 — bare channel-name reply mid-flow stays in the subscribe flow
# ===========================================================================


@pytest.mark.asyncio
class TestBug040BareTokenStaysInFlow:
    async def test_bare_token_reruns_subscribe_not_other_intent(self):
        """A bare «profendocrinologist» mid-clarify re-runs subscribe_digest —
        it must NOT be re-classified to update_channel / list_topics.

        Pre-fix: there is no ClarifyFlow, so a bare token routes through the
        stateless LLM (``agent.process_message``) and is mis-routed.
        """
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(CORRECT_SUGGESTION)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            invoked.append((name, dict(args)))
            return {
                "preview": True,
                "tool": "subscribe_digest",
                "message": "Preview: создать подписку … Подтвердите [да/нет].",
            }

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert [n for n, _ in invoked] == ["subscribe_digest"]
        assert "update_channel" not in [n for n, _ in invoked]
        assert "list_topics" not in [n for n, _ in invoked]
        assert invoked[0][1]["channel_ids"] == [CORRECT_SUGGESTION]
        agent.process_message.assert_not_called()

    async def test_handle_text_routes_clarify_state_without_llm(self):
        """When the chat is in ClarifyFlow, ``handle_text`` must NOT consult
        the LLM for a bare channel-name reply (BUG-040 root)."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(CORRECT_SUGGESTION)
        agent = MagicMock()
        agent.process_message = AsyncMock(return_value=AgentResult(response_text="x"))

        async def mock_execute(name: str, args: dict, **_kw):
            return {"preview": True, "tool": name, "message": "Подтвердите [да/нет]."}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await handle_text(msg, agent=agent, state=state, current_user=_admin())

        agent.process_message.assert_not_called()

    async def test_negative_cancels_clarify_flow(self):
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_clarify_action(),
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
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert invoked == []
        assert await state.get_state() is None
        assert "отменено" in _sent_text(msg).lower()

    async def test_clarify_ttl_expiry_clears_state(self):
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        old = datetime.now(UTC) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
        await state.update_data(clarify_action=_clarify_action(), created_at=old.isoformat())
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(name: str, _args: dict, **_kw):
            raise AssertionError("must not execute on expired clarify state")

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert await state.get_state() is None


# ===========================================================================
# BUG-041 — deterministic space rejection + prompt rule + existence check
# ===========================================================================


@pytest.mark.asyncio
class TestBug041GuardHardening:
    async def test_prompt_forbids_llm_normalization(self):
        """The bot prompt must forbid the LLM from pre-normalizing / guessing a
        channel name with internal whitespace (the BUG-041 root cause).

        Pre-fix the prompt explicitly PERMITS stripping whitespace into a
        single token; post-fix it mandates passing the token verbatim.
        """
        import yaml

        bot_yaml = Path(__file__).resolve().parent.parent / "prompts" / "bot.yaml"
        spec = yaml.safe_load(bot_yaml.read_text(encoding="utf-8"))
        system_prompt = spec["system"]["prompt"]
        assert "BUG-041" in system_prompt
        lowered = system_prompt.lower()
        assert "verbatim" in lowered
        # The defect-permitting phrase must be gone: the prompt must no longer
        # instruct the LLM that it MAY strip whitespace into a single token.
        assert "stripped of all whitespace into a single token" not in lowered

    async def test_space_typo_rejected_regardless(self):
        """The deterministic guard rejects the space-bearing input (and now
        yields a clarify hint) — this is the LLM-independent backstop."""
        result = await _exec_subscribe_digest(
            {"name": "m", "channel_ids": [TYPO_INPUT], "cron_expression": "0 9 * * *"},
            current_user=_admin(),
            bot=None,
            chat_id=DM_CHAT_ID,
        )
        assert result["error_class"] == "InvalidChannelUsername"
        assert "clarify_pending" in result

    async def test_verify_channel_exists_true_false_none(self):
        """``verify_channel_exists`` resolves existence via the source repo
        (BUG-010 pattern) and fail-opens to ``None`` on lookup error."""

        class _FakeStateRepo:
            def __init__(self, known: set[str]) -> None:
                self._known = known

            async def get_source(self, cid: str):
                return None

            async def get_source_by_username(self, cid: str):
                return object() if cid in self._known else None

        @asynccontextmanager
        async def _ctx(known: set[str]):
            yield (_FakeStateRepo(known), MagicMock())

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _ctx({CORRECT_SUGGESTION}),
        ):
            assert await verify_channel_exists(CORRECT_SUGGESTION) is True
            assert await verify_channel_exists("ghost_channel") is False
        # Numeric ids skip the lookup (fail-open None).
        assert await verify_channel_exists("-1001234567890") is None

        # Repo raising → fail-open None (offline DB must not wedge the flow).
        @asynccontextmanager
        async def _raising_ctx():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _raising_ctx(),
        ):
            assert await verify_channel_exists("some_channel") is None

    async def test_nonexistent_corrected_channel_rejected_in_clarify(self):
        """Defense-in-depth: a corrected channel that does not exist must NOT
        produce a subscribe preview — the clarify FSM stays armed."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("ghostchannel")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {"preview": True, "tool": name, "message": "x"}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=False),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert invoked == []  # subscribe never re-run for a ghost channel
        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        assert "не найден" in _sent_text(msg).lower()


# ===========================================================================
# BUG-042 — deterministic preview cron (not LLM-truncated)
# ===========================================================================


@pytest.mark.asyncio
class TestBug042DeterministicPreviewCron:
    async def test_tool_preview_message_schedule_is_deterministic(self):
        """The subscribe preview ``message`` must represent the schedule
        deterministically (BUG-042 guarantee, reframed 2026-05-31):

        * a RECOGNIZED cron (`0 * * * *`) → the friendly label «ежечасно в :00
          (Europe/Moscow)» and NO raw cron / `<code>` (items 1+2);
        * an UNRECOGNIZED cron (`*/13 * * * *`) → the verbatim `<code>cron</code>`
          (never dropped / truncated).

        ``verify_channel_exists`` is failed open here (this test targets schedule
        rendering, not the B2 existence check; «durov» isn't seeded in test DB).
        """
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ):
            recognized = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["durov"],
                    "cron_expression": FULL_CRON,  # "0 * * * *" → hourly
                    "timezone": "Europe/Moscow",
                },
                current_user=_admin(),
                bot=None,
                chat_id=DM_CHAT_ID,
            )
            unrecognized = await _exec_subscribe_digest(
                {
                    "name": "odd",
                    "channel_ids": ["durov"],
                    "cron_expression": "*/13 * * * *",
                    "timezone": "Europe/Moscow",
                },
                current_user=_admin(),
                bot=None,
                chat_id=DM_CHAT_ID,
            )
        assert recognized.get("preview") is True
        assert "ежечасно в :00 (Europe/Moscow)" in recognized["message"]
        assert "<code>" not in recognized["message"]
        assert FULL_CRON not in recognized["message"]
        # Unrecognized cron is shown verbatim — the field is never silently lost.
        assert "<code>*/13 * * * *</code>" in unrecognized["message"]

    async def test_agent_captures_preview_message_verbatim(self):
        """The agent must surface the tool's preview ``message`` verbatim in
        ``preview_message`` (not rely on the LLM-paraphrased text).

        Pre-fix: ``AgentResult`` has no ``preview_message`` field.
        """
        agent = GeminiAgent(api_key="test-key")
        full_msg = (
            "Preview: создать подписку «morning» на 1 канал(ов) по расписанию "
            f"<code>{FULL_CRON}</code> (Europe/Moscow), формат summary. "
            "Подтвердите [да/нет]."
        )
        tool_result = {
            "preview": True,
            "tool": "subscribe_digest",
            # The real subscribe executors flag their preview text as
            # user-facing (review item B1) — the agent only captures the
            # verbatim message when this flag is present.
            "user_facing_message": True,
            "message": full_msg,
        }
        gemini_responses = [
            _gemini_function_call(
                "subscribe_digest",
                {"name": "morning", "channel_ids": ["durov"], "cron_expression": FULL_CRON},
            ),
            # LLM paraphrase TRUNCATES the cron to "0" (the BUG-042 symptom).
            _gemini_text_only("по расписанию 0 (Europe/Moscow)"),
        ]
        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("подпиши на ежечасный дайджест durov")

        assert result.preview_message == full_msg
        assert FULL_CRON in result.preview_message

    async def test_handle_text_sends_preview_verbatim_not_truncated(self):
        """``handle_text`` must send the deterministic preview message (full
        cron), NOT the LLM-truncated ``response_text`` («…0…»).

        This directly inverts the BUG-042 trace.
        """
        state = _make_state()
        msg = _make_message("подпиши на ежечасный дайджест durov")
        full_msg = (
            "Preview: создать подписку «morning» по расписанию "
            f"<code>{FULL_CRON}</code> (Europe/Moscow). Подтвердите [да/нет]."
        )
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="по расписанию 0 (Europe/Moscow)",  # LLM truncation
                preview_pending={"tool_name": "subscribe_digest", "args": {"name": "morning"}},
                preview_message=full_msg,
            )
        )
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        sent = _sent_text(msg)
        assert FULL_CRON in sent
        # The truncated standalone "0 (Europe/Moscow)" paraphrase must NOT be
        # what the user sees.
        assert "по расписанию 0 (europe/moscow)" not in sent.lower()
        # Preview still arms ConfirmFlow.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state


# ===========================================================================
# Review item B1 — verbatim preview path is scoped to the subscribe tools ONLY
# ===========================================================================
#
# Pre-B1-fix the agent captured ``message`` verbatim for ANY tool returning
# ``{"preview": True}`` and the handler rendered it whenever a preview was
# pending. For non-subscribe preview tools (pause_channel, remove_channel,
# set_llm_config, …) the ``message`` field is LLM-directed scaffolding
# («Preview only. Ask the user to confirm, then call again with confirm=true.»)
# — NOT user copy. Surfacing it verbatim leaks raw English scaffolding instead
# of the Russian LLM paraphrase. The fix scopes the verbatim path to the
# subscribe executors via the ``user_facing_message`` flag.
NON_SUBSCRIBE_SCAFFOLD = "Preview only. Ask the user to confirm, then call again with confirm=true."


@pytest.mark.asyncio
class TestB1VerbatimPreviewScopedToSubscribe:
    async def test_non_subscribe_preview_message_not_captured_verbatim(self):
        """A non-subscribe preview tool's LLM-scaffolding ``message`` must NOT
        be captured as ``preview_message`` (the verbatim-render channel).

        Pre-fix: ``preview_message`` held the English scaffolding; post-fix it
        is ``None`` because the tool result carries no ``user_facing_message``
        flag, so the handler falls back to the LLM paraphrase.
        """
        agent = GeminiAgent(api_key="test-key")
        # A non-subscribe write tool returning a preview with scaffolding text
        # and NO ``user_facing_message`` flag (mirrors _exec_pause_channel et al).
        tool_result = {
            "preview": True,
            "tool": "pause_channel",
            "message": NON_SUBSCRIBE_SCAFFOLD,
        }
        gemini_responses = [
            _gemini_function_call("pause_channel", {"channel_id": "durov"}),
            _gemini_text_only("Приостановить канал durov? Подтвердите [да/нет]."),
        ]
        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("поставь на паузу durov")

        # The preview FSM hint is still armed …
        assert result.preview_pending is not None
        assert result.preview_pending["tool_name"] == "pause_channel"
        # … but the scaffolding must NOT be on the verbatim channel.
        assert result.preview_message is None

    async def test_subscribe_preview_message_is_captured_verbatim(self):
        """Conversely, a subscribe_* preview IS user-facing and captured
        verbatim (the ``user_facing_message`` flag opts it in)."""
        agent = GeminiAgent(api_key="test-key")
        full_msg = (
            "Preview: создать подписку «morning» по расписанию "
            f"<code>{FULL_CRON}</code> (Europe/Moscow). Подтвердите [да/нет]."
        )
        tool_result = {
            "preview": True,
            "tool": "subscribe_digest",
            "user_facing_message": True,
            "message": full_msg,
        }
        gemini_responses = [
            _gemini_function_call(
                "subscribe_digest", {"name": "morning", "channel_ids": ["durov"]}
            ),
            _gemini_text_only("по расписанию 0"),  # would-be LLM truncation
        ]
        with (
            patch.object(agent, "_call_gemini", new=AsyncMock(side_effect=gemini_responses)),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("подпиши на дайджест durov")

        assert result.preview_message == full_msg

    async def test_handle_text_non_subscribe_preview_uses_llm_paraphrase(self):
        """End-to-end: when a preview is pending but ``preview_message`` is
        ``None`` (non-subscribe tool), ``handle_text`` must render the LLM
        paraphrase (``response_text``), NEVER the raw English scaffolding."""
        state = _make_state()
        msg = _make_message("поставь на паузу durov")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text="Приостановить канал durov? Подтвердите [да/нет].",
                preview_pending={
                    "tool_name": "pause_channel",
                    "args": {"channel_id": "durov"},
                },
                preview_message=None,
            )
        )
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        sent = _sent_text(msg)
        assert "Приостановить канал durov" in sent
        # The raw scaffolding must NOT reach the user.
        assert NON_SUBSCRIBE_SCAFFOLD not in sent
        assert "confirm=true" not in sent.lower()
        # The preview still arms ConfirmFlow.
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state


# ===========================================================================
# Review item B2 — executor verifies channel existence on the PRIMARY path
# ===========================================================================
#
# The clarify FSM only arms for embedded-space typos (validate_channel_username
# returns a ``suggestion``). The primary BUG-041 trace is the LLM emitting a
# wrong-but-VALID username DIRECTLY: it passes format validation, never arms
# clarify, and pre-B2-fix went straight to a preview. The executor now runs a
# fail-open existence check before previewing.


@pytest.mark.asyncio
class TestB2ExecutorExistenceCheckPrimaryPath:
    async def test_direct_nonexistent_username_rejected_digest(self):
        """A valid-format but non-existent username passed DIRECTLY to
        ``_exec_subscribe_digest`` is rejected (not previewed) when
        ``verify_channel_exists`` returns ``False``."""
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=False),
        ):
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["wrongbutvalidname"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=None,
                chat_id=DM_CHAT_ID,
            )
        assert result.get("preview") is not True
        assert result.get("error_class") == "ChannelNotFound"
        assert "не найден" in result["error"].lower()

    async def test_direct_nonexistent_username_rejected_watchlist(self):
        """Symmetric on the watchlist executor."""
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=False),
        ):
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["wrongbutvalidname"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
                current_user=_admin(),
                bot=None,
                chat_id=DM_CHAT_ID,
            )
        assert result.get("preview") is not True
        assert result.get("error_class") == "ChannelNotFound"
        assert "не найден" in result["error"].lower()

    async def test_fail_open_allows_preview_when_existence_unknown(self):
        """Fail-open: when ``verify_channel_exists`` returns ``None`` (numeric
        id / unreachable DB) the preview proceeds — the existing happy path is
        preserved (this is what keeps the absent-DB unit tests green)."""
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ):
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["durov"],
                    "cron_expression": FULL_CRON,
                    "timezone": "Europe/Moscow",
                },
                current_user=_admin(),
                bot=None,
                chat_id=DM_CHAT_ID,
            )
        assert result.get("preview") is True
        # Reframed schedule contract (items 1+2): `0 * * * *` is recognized →
        # friendly label only (no raw cron).
        assert "ежечасно в :00 (Europe/Moscow)" in result["message"]


# ===========================================================================
# BUG-043 — channel-not-found suggestion on the READ surface is actionable
# (BUG-039/040 residual; real-fire 2026-05-31 12:41 prod @ c0ff6d3)
# ===========================================================================
#
# Transcript:
#   12:41:22 user: «pro fendocrinologist»   (bare channel name, NO subscribe flow)
#   12:41:24 bot:  «Канал pro fendocrinologist не найден. Возможно, вы имели в
#                   виду profendocrinologist? Доступные каналы: …»
#   12:41:43 user: «да»
#   12:41:43 bot:  «Я не совсем понимаю ваш ответ.»   ← BUG-039 opaque fallback RESURFACES
#
# Root cause: the not-found+suggestion message is emitted by
# ``_build_no_results_suggestion`` (list_topics / search / get_cross_channel_stats),
# NOT the subscribe space-guard. Pre-fix that path attached no ``clarify_pending``,
# so the follow-up «да» reached ``handle_text`` with no FSM armed → stateless LLM →
# opaque fallback. The fix reuses the SAME ClarifyFlow plumbing.


@pytest.mark.asyncio
class TestBug043ReadSuggestionIsActionable:
    async def test_resolver_attaches_read_clarify_pending(self):
        """``_build_no_results_suggestion`` must attach a ``kind='read'``
        ``clarify_pending`` carrying the original tool + args + the BARE
        suggested channel id.

        Pre-fix: the resolver had no ``tool_name`` kwarg (TypeError) and never
        produced a ``clarify_pending`` — the read suggestion was inert.
        """
        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            _fake_state_repo_ctx([CORRECT_SUGGESTION, "AgeManagment", "Lab4health"]),
        ):
            payload = await _build_no_results_suggestion(
                TYPO_INPUT,
                _admin(),
                tool_name="list_topics",
                args={"channel_id": TYPO_INPUT, "limit": 20},
            )
        clarify = payload["clarify_pending"]
        assert clarify["kind"] == "read"
        assert clarify["tool_name"] == "list_topics"
        assert clarify["channel_arg"] == "channel_id"
        # The BARE channel id (directly usable as a channel arg), not a sentence.
        assert clarify["suggestion"] == CORRECT_SUGGESTION
        assert clarify["args"]["channel_id"] == TYPO_INPUT
        assert "confirm" not in clarify["args"]
        assert CORRECT_SUGGESTION in clarify["message"]
        assert "не найден" in clarify["message"].lower()

    async def test_resolver_no_clarify_without_tool_name(self):
        """Back-compat: when no ``tool_name`` is supplied the resolver keeps
        its legacy shape (suggestion sentence only, NO clarify hint)."""
        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            _fake_state_repo_ctx([CORRECT_SUGGESTION]),
        ):
            payload = await _build_no_results_suggestion(TYPO_INPUT, _admin())
        assert "clarify_pending" not in payload
        assert payload["suggestion"]  # the legacy Russian sentence is still set

    async def test_agent_short_circuits_with_read_clarification(self):
        """The agent must surface the read clarify ``message`` verbatim + the
        clarify hint, WITHOUT a second LLM turn (the dead-end pre-fix re-fed the
        result to the LLM, which paraphrased the suggestion and armed nothing).
        """
        agent = GeminiAgent(api_key="test-key")
        read_clarify = _read_clarify_action()
        tool_result = {
            "total": 0,
            "offset": 0,
            "limit": 20,
            "has_more": False,
            "items": [],
            "available_channel_ids": [CORRECT_SUGGESTION, "AgeManagment"],
            "suggestion": f"Возможно, имелся в виду '{CORRECT_SUGGESTION}'?",
            "clarify_pending": read_clarify,
        }
        # Exactly ONE gemini response — a second call would raise
        # StopAsyncIteration, proving the loop short-circuited.
        with (
            patch.object(
                agent,
                "_call_gemini",
                new=AsyncMock(
                    side_effect=[_gemini_function_call("list_topics", {"channel_id": TYPO_INPUT})]
                ),
            ),
            patch(
                "tg_parser.bot.agent.execute_tool",
                new=AsyncMock(return_value=tool_result),
            ),
        ):
            result = await agent.process_message("pro fendocrinologist")

        assert result.clarify_pending is not None
        assert result.clarify_pending["kind"] == "read"
        assert result.clarify_pending["suggestion"] == CORRECT_SUGGESTION
        assert CORRECT_SUGGESTION in result.response_text
        assert "не совсем понимаю" not in result.response_text.lower()

    async def test_handle_text_arms_clarify_flow_for_read_kind(self):
        """``handle_text`` arms ``ClarifyFlow`` from a read ``clarify_pending``."""
        state = _make_state()
        msg = _make_message("pro fendocrinologist")
        agent = MagicMock()
        agent.process_message = AsyncMock(
            return_value=AgentResult(
                response_text=(
                    f"Канал «{TYPO_INPUT}» не найден. Возможно, вы имели в виду "
                    f"«{CORRECT_SUGGESTION}»?"
                ),
                clarify_pending=_read_clarify_action(),
            )
        )
        await handle_text(msg, agent=agent, state=state, current_user=_admin())

        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        data = await state.get_data()
        assert data["clarify_action"]["kind"] == "read"
        assert data["clarify_action"]["suggestion"] == CORRECT_SUGGESTION

    async def test_affirmative_reruns_read_intent_no_opaque_fallback(self):
        """THE transcript: «да» on a read clarification re-runs the ORIGINAL
        read intent (list_topics) with the suggested channel — NOT the opaque
        «Я не совсем понимаю ваш ответ» catch-all, and WITHOUT consulting the LLM.
        """
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
                        "id": "topic-1",
                        "title": "Эндокринология: обзор",
                        "type": "thematic",
                        "summary": "Краткое описание темы.",
                        "items_count": 3,
                        "sources": [CORRECT_SUGGESTION],
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
        assert args["channel_id"] == CORRECT_SUGGESTION
        assert "confirm" not in args
        # Single-page result → state cleared (no pagination).
        assert await state.get_state() is None
        agent.process_message.assert_not_called()
        sent = _sent_text(msg)
        assert "не совсем понимаю" not in sent.lower()
        assert "Эндокринология" in sent

    async def test_bare_token_reruns_read_intent_not_reclassified(self):
        """A bare «profendocrinologist» mid-clarify re-runs list_topics with
        that channel — it must NOT be re-routed through the stateless LLM."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(CORRECT_SUGGESTION)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            invoked.append((name, dict(args)))
            return {"total": 0, "offset": 0, "limit": 20, "has_more": False, "items": []}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert [n for n, _ in invoked] == ["list_topics"]
        assert invoked[0][1]["channel_id"] == CORRECT_SUGGESTION
        agent.process_message.assert_not_called()

    async def test_read_clarify_arms_pagination_when_more_pages(self):
        """When the re-run read intent has more pages, the chat transitions to
        ``PaginationFlow`` (so a follow-up «ещё» works) instead of clearing."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(name: str, _args: dict, **_kw):
            return {
                "total": 40,
                "offset": 0,
                "limit": 20,
                "has_more": True,
                "items": [{"n": 1, "id": "t1", "title": "T1"}],
                "pagination_pending": {
                    "tool_name": "list_topics",
                    "args": {"channel_id": CORRECT_SUGGESTION, "offset": 20, "limit": 20},
                    "total": 40,
                    "offset": 20,
                    "limit": 20,
                },
            }

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert await state.get_state() == PaginationFlow.has_active_list.state
        data = await state.get_data()
        assert data["pagination"]["args"]["channel_id"] == CORRECT_SUGGESTION

    async def test_retyped_typo_reclarifies_not_deadends(self):
        """A re-typed «pro fendocrinologist» (still not found) keeps the clarify
        FSM armed (re-clarify) rather than dead-ending or previewing."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(TYPO_INPUT)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {"total": 0, "items": []}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=False),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        # The non-existent re-typed channel is rejected BEFORE re-running, and
        # the clarify FSM stays armed so the user can correct again.
        assert invoked == []
        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        assert "не найден" in _sent_text(msg).lower()

    async def test_negative_cancels_read_clarify(self):
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
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
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert invoked == []
        assert await state.get_state() is None
        assert "отменено" in _sent_text(msg).lower()

    async def test_read_clarify_ttl_expiry_clears_state(self):
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        old = datetime.now(UTC) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
        await state.update_data(clarify_action=_read_clarify_action(), created_at=old.isoformat())
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(name: str, _args: dict, **_kw):
            raise AssertionError("must not execute on expired clarify state")

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        assert await state.get_state() is None


# ===========================================================================
# BUG-044 — auto-derived subscription name keeps the pre-correction channel
# token after a clarify re-run (cosmetic naming consistency)
# ===========================================================================
#
# Real-fire 2026-05-31: «pro fendocrinologist» → suggestion → «да» created a
# subscription whose NAME still embedded the typo:
#   «📰 Подписка «Ежечасный дайджест pro fendocrinologist» создана.»
# even though the channel was correctly bound to `profendocrinologist`. The
# LLM auto-derives the digest ``name`` / watchlist ``title`` from the user's
# original text; the clarify re-run substituted only the channel id, leaving
# the typo in the display name. The fix rewrites the token in the name ONLY
# when the name literally contains the original (corrected) channel token.


@pytest.mark.asyncio
class TestBug044AutoDerivedNameConsistency:
    async def _run_affirmative(self, clarify_action: dict[str, Any]) -> dict[str, Any]:
        """Drive «да» through the clarify handler; return the re-run args."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=clarify_action,
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        captured: dict[str, Any] = {}

        async def mock_execute(name: str, args: dict, **_kw):
            captured["name"] = name
            captured["args"] = dict(args)
            return {"preview": True, "tool": name, "message": "Подтвердите [да/нет]."}

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())

        return captured

    async def test_autoderived_digest_name_corrected(self):
        """The auto-derived digest name «Ежечасный дайджест pro fendocrinologist»
        must be rewritten to embed the CORRECTED channel id on the re-run.

        Pre-fix: only ``channel_ids`` is substituted, so the name keeps the
        typo and the creation message reads «… pro fendocrinologist создана».
        """
        captured = await self._run_affirmative(
            _clarify_action(
                args={
                    "name": f"Ежечасный дайджест {TYPO_INPUT}",
                    "channel_ids": [TYPO_INPUT],
                    "cron_expression": FULL_CRON,
                    "timezone": "Europe/Moscow",
                },
            )
        )
        args = captured["args"]
        assert args["channel_ids"] == [CORRECT_SUGGESTION]
        assert args["name"] == f"Ежечасный дайджест {CORRECT_SUGGESTION}"
        assert TYPO_INPUT not in args["name"]
        assert CORRECT_SUGGESTION in args["name"]

    async def test_autoderived_watchlist_title_corrected(self):
        """Symmetric for the watchlist ``title`` arg."""
        captured = await self._run_affirmative(
            _clarify_action(
                tool_name="subscribe_watchlist",
                args={
                    "title": f"Слежу за {TYPO_INPUT}",
                    "channel_ids": [TYPO_INPUT],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
            )
        )
        args = captured["args"]
        assert args["channel_ids"] == [CORRECT_SUGGESTION]
        assert args["title"] == f"Слежу за {CORRECT_SUGGESTION}"
        assert TYPO_INPUT not in args["title"]

    async def test_user_chosen_name_preserved(self):
        """A name that does NOT embed the original channel token is an explicit
        user choice and must be left UNCHANGED (no clobber, no guessing)."""
        explicit = "Моя любимая подписка"
        captured = await self._run_affirmative(
            _clarify_action(
                args={
                    "name": explicit,
                    "channel_ids": [TYPO_INPUT],
                    "cron_expression": FULL_CRON,
                    "timezone": "Europe/Moscow",
                },
            )
        )
        args = captured["args"]
        assert args["channel_ids"] == [CORRECT_SUGGESTION]
        assert args["name"] == explicit

    async def test_multi_channel_corrects_only_target_token(self):
        """With multiple channels, only the corrected-index token is rewritten
        in the name — unrelated channel tokens in the name are untouched."""
        captured = await self._run_affirmative(
            _clarify_action(
                args={
                    "name": f"Дайджест durov + {TYPO_INPUT}",
                    "channel_ids": ["durov", TYPO_INPUT],
                    "cron_expression": FULL_CRON,
                    "timezone": "Europe/Moscow",
                },
                channel_index=1,
            )
        )
        args = captured["args"]
        assert args["channel_ids"] == ["durov", CORRECT_SUGGESTION]
        assert args["name"] == f"Дайджест durov + {CORRECT_SUGGESTION}"
        assert "durov" in args["name"]  # unrelated token preserved


# ===========================================================================
# BUG-043 residual (final-smoke 2026-05-31) — read re-run rendering fidelity
# Defect-1: per-intent header naming the resolved channel.
# Defect-2: «Доступные каналы» list cap parity (named constant, not magic 5).
# ===========================================================================


@pytest.mark.asyncio
class TestBug043FinalSmokeFidelity:
    async def _rerun_list_topics_affirmative(self, *, total: int, items: list[dict]) -> str:
        """Drive «да» on a read clarify → return the concatenated bot text."""
        state = _make_state()
        await state.set_state(ClarifyFlow.awaiting_channel_clarification)
        await state.update_data(
            clarify_action=_read_clarify_action(),
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(name: str, _args: dict, **_kw):
            payload: dict[str, Any] = {
                "total": total,
                "offset": 0,
                "limit": 20,
                "has_more": total > len(items),
                "items": items,
            }
            if total > len(items):
                payload["pagination_pending"] = {
                    "tool_name": "list_topics",
                    "args": {"channel_id": CORRECT_SUGGESTION, "offset": 20, "limit": 20},
                    "total": total,
                    "offset": 20,
                    "limit": 20,
                }
            return payload

        with (
            patch("tg_parser.bot.handlers.execute_tool", new=mock_execute),
            patch(
                "tg_parser.bot.handlers.verify_channel_exists",
                new=AsyncMock(return_value=True),
            ),
        ):
            await _handle_clarification_response(msg, agent, state, current_user=_admin())
        return _sent_text(msg)

    async def test_read_rerun_prepends_resolved_channel_header(self):
        """Defect-1: the deterministic list_topics re-run must prepend the
        «Показываю топ-N тем канала {resolved}:» header — the user's confirmation
        of WHICH channel was finally resolved.

        Pre-fix HEAD ``195589b``: the re-run jumped straight to «1. …» with no
        header → this assertion fails.
        """
        sent = await self._rerun_list_topics_affirmative(
            total=1,
            items=[{"n": 1, "id": "t1", "title": "Гормоны и старение", "summary": "S"}],
        )
        assert f"Показываю топ-1 тем канала {CORRECT_SUGGESTION}:" in sent
        # The resolved channel is named in the header (not the typo).
        assert TYPO_INPUT not in sent
        assert "Гормоны и старение" in sent

    async def test_read_rerun_header_reports_page_size_not_total(self):
        """The «топ-N» count reflects the items SHOWN on the page (mirrors the
        normal path «топ-20 … Показано 1–20 из 178»), and pagination is intact."""
        items = [{"n": i, "id": f"t{i}", "title": f"T{i}"} for i in range(1, 21)]
        sent = await self._rerun_list_topics_affirmative(total=178, items=items)
        assert f"Показываю топ-20 тем канала {CORRECT_SUGGESTION}:" in sent
        # Pagination footer preserved (no regression to BUG-043 paging).
        assert "Показано 1–20 из 178" in sent
        assert "«ещё»" in sent or "ещё" in sent

    @staticmethod
    async def _available_bullets(all_sources: list[str]) -> tuple[str, list[str]]:
        """Build the read clarify message for ``all_sources`` and return
        (full message, vertically-listed channel ids)."""
        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            _fake_state_repo_ctx(all_sources),
        ):
            payload = await _build_no_results_suggestion(
                TYPO_INPUT,
                _admin(),
                tool_name="list_topics",
                args={"channel_id": TYPO_INPUT, "limit": 20},
            )
        message = payload["clarify_pending"]["message"]
        bullets = [
            ln.removeprefix("• ").strip() for ln in message.splitlines() if ln.startswith("• ")
        ]
        return message, bullets

    async def test_available_channels_cap_is_the_named_constant_not_five(self):
        """Defect-2 (anti-regression core): the «Доступные каналы» list is
        capped at ``_NO_RESULTS_AVAILABLE_CAP`` (10), NOT the regressed magic 5.

        The suggested channel is placed LAST so it falls OUTSIDE the upstream
        ``available_channel_ids[:cap]`` slice — the list then fills to the full
        cap, pinning the constant exactly (==10). With more candidates than the
        cap, a hard-coded 5 (pre-fix HEAD ``195589b``) would yield 5 → fail.

        Exact equality is justified (not brittle): the source list is fully
        controlled here, so the count is deterministic.
        """
        # 14 non-matching sources + the suggestion LAST (rank 15, outside [:10]).
        all_sources = [f"chan{i}" for i in range(14)] + [CORRECT_SUGGESTION]
        message, listed = await self._available_bullets(all_sources)
        assert "Доступные каналы:" in message
        assert len(listed) == _NO_RESULTS_AVAILABLE_CAP  # exactly 10, definitively not 5
        # The suggestion isn't in the top-cap slice, so it isn't listed.
        assert CORRECT_SUGGESTION not in listed

    async def test_available_channels_excludes_suggested_and_renders_vertically(self):
        """Defect-2 + Item-4: when the suggested channel falls INSIDE the
        top-cap slice it is dropped from «Доступные каналы» (it's already named
        verbatim in the suggestion line), and the list is rendered VERTICALLY
        (one «• {channel}» per line), not comma-joined.

        With the suggestion first (inside [:cap]) the post-exclusion count is
        ``cap - 1`` (9) — deterministic given the controlled source order.
        Pre-fix HEAD ``195589b``: comma-joined inline (no «• » lines) → 0
        bullets → fail.
        """
        others = [f"chan{i}" for i in range(11)]
        all_sources = [CORRECT_SUGGESTION, *others]
        message, listed = await self._available_bullets(all_sources)
        assert "Доступные каналы:" in message
        # Vertical render produced real bullet lines (not an inline comma list).
        assert len(listed) > 5
        assert len(listed) == _NO_RESULTS_AVAILABLE_CAP - 1
        # Suggested excluded from the list, but still named once in the prompt.
        assert CORRECT_SUGGESTION not in listed
        assert f"«{CORRECT_SUGGESTION}»" in message
        # The legacy inline comma-joined form must be gone.
        assert "Доступные каналы: " not in message


class TestFormatReadResultHeaderUnit:
    """Direct unit coverage of ``_format_read_result`` — exercises the REAL
    header builder for every read intent (the handler harness only drives
    ``list_topics``), plus the no-channel / empty-list edges. No mocking: the
    function under test is called directly with structured results.

    Pre-fix HEAD ``195589b``: ``_format_read_result`` had no ``channel`` param,
    so the ``channel=`` keyword raises ``TypeError`` → every case fails.
    """

    CH = "profendocrinologist"

    def test_list_topics_header_and_body(self):
        out = _format_read_result(
            "list_topics",
            {"items": [{"n": 1, "title": "T1"}], "offset": 0, "total": 1, "has_more": False},
            channel=self.CH,
        )
        assert out.startswith(f"Показываю топ-1 тем канала {self.CH}:")
        assert "T1" in out  # the body is still rendered after the header

    def test_search_header_and_body(self):
        out = _format_read_result(
            "search",
            {"results": [{"summary": "найденный фрагмент"}]},
            channel="durov",
        )
        assert out.startswith("Результаты поиска в канале «durov»:")
        assert "найденный фрагмент" in out

    def test_cross_stats_header_and_body(self):
        out = _format_read_result(
            "get_cross_channel_stats",
            {"message": "Сводная статистика."},
            channel="durov",
        )
        assert out.startswith("Статистика по каналу «durov»:")
        assert "Сводная статистика." in out

    def test_no_channel_means_no_header(self):
        """Without a resolved channel (e.g. a non-clarify caller) the header is
        suppressed — the body renders exactly as before (back-compat guard)."""
        out = _format_read_result(
            "list_topics",
            {"items": [{"n": 1, "title": "T1"}], "offset": 0, "total": 1, "has_more": False},
            channel=None,
        )
        assert not out.startswith("Показываю")
        assert "T1" in out

    def test_empty_list_suppresses_header(self):
        """An empty page yields no «топ-N» header (N would be 0) — we never
        emit «Показываю топ-0 …»."""
        out = _format_read_result(
            "list_topics",
            {"items": [], "offset": 0, "total": 0, "has_more": False},
            channel="durov",
        )
        assert "топ-" not in out
        assert "Показываю" not in out
