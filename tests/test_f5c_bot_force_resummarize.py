"""F5-C #15 item #5 (write-part, #356 item A) — bot ``force_resummarize``.

Pure-mock tests (no Postgres). Mirror the MCP contract in
``tests/test_f5c_mcp_tools.py`` ``TestForceResummarize`` plus the bot
specifics:

* admin-only (non-admin → typed error, ResummarizationService NOT created);
* ``dry_run=true`` — CLI ``--dry-run`` parity report (no service, no mutation);
* rich preview (``confirm=false`` → ``{"preview": True, ...}`` with live-card
  fields; missing card → early typed "Topic not found");
* real run (``confirm=true``) — outcome dict passed through; ``aclose`` runs;
* ``status='locked'`` passthrough (success-ish, not an error);
* ``AnthropicBillingError`` propagates (executor does NOT swallow it) while
  ``aclose`` still runs; ``execute_tool`` surfaces the typed ``error_class``;
* BUG-009: LLM-issued ``confirm=true`` without an FSM snapshot is rejected;
* classifier-set membership (in the confirm set, not in the read / paginated
  / bot-context sets).

BUG-086 (post-deploy prod defect, 2026-07-25) adds the confirm-contract
regression block at the bottom of this module:

* the ``dry_run`` report is TERMINAL — it carries no ``preview`` key, does NOT
  arm ``ConfirmFlow``, and advertises its terminality via the machine-readable
  ``terminal`` / ``mutation_requires_confirm_preview_turn`` markers;
* ``dry_run`` + ``confirm`` is rejected (pre-fix ``dry_run`` silently won, so a
  *confirmed* run became a no-op);
* the agent-level structural guard: when the LLM hand-authors a «Подтвердите …
  [да/нет]» sentence after a preview-LESS write call, the framework
  deterministically re-issues the tool in its preview shape (``confirm`` and
  ``dry_run`` stripped) and arms ``ConfirmFlow`` itself;
* the ``prompts/bot.yaml`` v1.9.3 hard rule that separates the two call shapes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import (
    _PREVIEW_SUPPRESSING_ARGS,
    GeminiAgent,
    _looks_like_llm_authored_confirm,
)
from tg_parser.bot.tools import (
    _PAGINATED_READ_TOOLS,
    _READ_TOOLS_TRACKED_FOR_CONTEXT,
    _TOOLS_NEEDING_BOT_CONTEXT,
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    TOOL_DECLARATIONS,
    _exec_force_resummarize,
    execute_tool,
)
from tg_parser.domain.models import (
    Anchor,
    MessageType,
    TopicCard,
    TopicType,
)

TOPIC_ID = "topic:tg:c1:post:1"


def _admin() -> CurrentUser:
    return CurrentUser(
        id="user-admin",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _scoped(allowed: list[str]) -> CurrentUser:
    return CurrentUser(
        id="user-scoped",
        name="user",
        role="user",
        allowed_channel_ids=list(allowed),
        max_channels=10,
    )


def _make_card(
    *,
    topic_id: str = TOPIC_ID,
    sources: list[str] | None = None,
    summary_version: int = 3,
    new_items: int = 2,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title="Test topic",
        summary="Original summary",
        scope_in=["alpha"],
        scope_out=["beta"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="c1",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:c1:post:1",
                score=0.9,
            )
        ],
        sources=sources if sources is not None else ["c1"],
        updated_at=datetime(2026, 4, 26, tzinfo=UTC),
        summary_version=summary_version,
        last_summarized_at=None,
        new_items_since_last_summary=new_items,
    )


class _FakeCardRepo:
    def __init__(self, card: TopicCard | None) -> None:
        self._card = card
        self.calls: list[str] = []

    async def get_by_id(self, topic_id: str) -> TopicCard | None:
        self.calls.append(topic_id)
        return self._card


class _FakeBundle:
    def __init__(self, items: list) -> None:
        self.items = items


class _FakeBundleRepo:
    def __init__(self, bundle: _FakeBundle | None) -> None:
        self._bundle = bundle
        self.calls: list[str] = []

    async def get_by_topic_id(self, topic_id: str) -> _FakeBundle | None:
        self.calls.append(topic_id)
        return self._bundle


def _fake_repos(card_repo, bundle_repo=None):
    @asynccontextmanager
    async def _cm():
        yield (card_repo, bundle_repo, "_version_repo", "_proc_repo", "_db")

    return _cm


class _FakeService:
    def __init__(self, outcome: dict) -> None:
        self.outcome = outcome
        self.calls: list[str] = []
        self.closed = False

    async def resummarize_topic(self, topic_id: str) -> dict:
        self.calls.append(topic_id)
        return self.outcome

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Declaration / classifier-set membership
# ---------------------------------------------------------------------------


class TestDeclarationAndClassifiers:
    def test_declaration_present_and_count(self):
        names = {d["name"] for d in TOOL_DECLARATIONS}
        assert "force_resummarize" in names
        assert len(TOOL_DECLARATIONS) == 35

    def test_declaration_params(self):
        decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "force_resummarize")
        props = decl["parameters"]["properties"]
        assert decl["parameters"]["required"] == ["topic_id"]
        assert props["topic_id"]["type"] == "STRING"
        assert props["dry_run"]["type"] == "BOOLEAN"
        assert props["confirm"]["type"] == "BOOLEAN"

    def test_in_confirm_set_only(self):
        assert "force_resummarize" in _WRITE_TOOLS_REQUIRING_CONFIRM
        assert "force_resummarize" not in _READ_TOOLS_TRACKED_FOR_CONTEXT
        assert "force_resummarize" not in _PAGINATED_READ_TOOLS
        assert "force_resummarize" not in _TOOLS_NEEDING_BOT_CONTEXT


# ---------------------------------------------------------------------------
# Admin gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminGate:
    async def test_non_admin_denied_no_side_effect(self):
        svc = _FakeService(outcome={"status": "ok"})
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card())),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "confirm": True},
                current_user=_scoped(["c1"]),
            )

        assert "admin" in result["error"].lower()
        assert result["topic_id"] == TOPIC_ID
        assert svc.calls == []
        assert svc.closed is False


# ---------------------------------------------------------------------------
# Branch A — dry_run (CLI --dry-run parity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDryRun:
    async def test_dry_run_reports_without_service(self):
        card = _make_card(summary_version=3, new_items=2)
        card_repo = _FakeCardRepo(card)
        bundle_repo = _FakeBundleRepo(_FakeBundle([{"i": 1}, {"i": 2}, {"i": 3}]))
        svc = _FakeService(outcome={"status": "ok"})
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(card_repo, bundle_repo),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "dry_run": True},
                current_user=_admin(),
            )

        assert result["dry_run"] is True
        assert result["topic_id"] == TOPIC_ID
        assert result["current_version"] == 3
        assert result["new_items_since_last_summary"] == 2
        assert result["bundle_items_count"] == 3
        assert result["sources"] == ["c1"]
        # No mutation: service never created / invoked.
        assert svc.calls == []
        assert svc.closed is False

    async def test_dry_run_topic_not_found(self):
        card_repo = _FakeCardRepo(None)
        bundle_repo = _FakeBundleRepo(None)
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _fake_repos(card_repo, bundle_repo),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": "topic:tg:cX:post:9", "dry_run": True},
                current_user=_admin(),
            )

        assert "not found" in result["error"].lower()
        assert result["topic_id"] == "topic:tg:cX:post:9"


# ---------------------------------------------------------------------------
# Branch B — rich preview (confirm=false)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRichPreview:
    async def test_preview_shows_live_card_no_side_effect(self):
        card = _make_card(summary_version=5, new_items=7, sources=["c1", "c2"])
        card_repo = _FakeCardRepo(card)
        svc = _FakeService(outcome={"status": "ok"})
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(card_repo),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID},
                current_user=_admin(),
            )

        assert result["preview"] is True
        assert result["tool"] == "force_resummarize"
        assert result["current_version"] == 5
        assert result["new_items_since_last_summary"] == 7
        assert result["sources"] == ["c1", "c2"]
        assert result["user_facing_message"] is True
        assert svc.calls == []
        assert svc.closed is False

    async def test_preview_topic_not_found_early(self):
        card_repo = _FakeCardRepo(None)
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _fake_repos(card_repo),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID},
                current_user=_admin(),
            )

        assert "not found" in result["error"].lower()
        assert result["topic_id"] == TOPIC_ID


# ---------------------------------------------------------------------------
# Branch C — real run (confirm=true)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRealRun:
    async def test_confirm_invokes_service_and_passes_outcome(self):
        svc = _FakeService(
            outcome={"status": "ok", "version_no": 4, "tokens": 1234, "duration_s": 0.42}
        )
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "confirm": True},
                current_user=_admin(),
            )

        assert result["topic_id"] == TOPIC_ID
        assert result["status"] == "ok"
        assert result["version_no"] == 4
        assert result["tokens"] == 1234
        assert svc.calls == [TOPIC_ID]
        assert svc.closed is True

    async def test_locked_status_passes_through(self):
        svc = _FakeService(outcome={"status": "locked"})
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "confirm": True},
                current_user=_admin(),
            )

        assert result["status"] == "locked"
        assert "error" not in result
        assert svc.closed is True

    async def test_billing_error_propagates_and_closes(self):
        from tg_parser.processing.llm.errors import AnthropicBillingError

        class _Billing(_FakeService):
            async def resummarize_topic(self, topic_id: str):
                raise AnthropicBillingError("credit balance is too low")

        svc = _Billing(outcome={})
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            with pytest.raises(AnthropicBillingError):
                await _exec_force_resummarize(
                    {"topic_id": TOPIC_ID, "confirm": True},
                    current_user=_admin(),
                )

        assert svc.closed is True, "aclose must run even on billing error"


# ---------------------------------------------------------------------------
# execute_tool integration — BUG-009 guard + typed error surfacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteToolIntegration:
    async def test_llm_issued_confirm_true_without_state_rejected(self):
        result = await execute_tool(
            "force_resummarize",
            {"topic_id": TOPIC_ID, "confirm": True},
            current_user=_admin(),
        )
        assert result["error_class"] == "ConfirmFlowMismatch"
        assert "BUG-009" in result["error"]

    async def test_billing_error_surfaces_typed_error_class(self):
        from tg_parser.processing.llm.errors import AnthropicBillingError

        class _Billing(_FakeService):
            async def resummarize_topic(self, topic_id: str):
                raise AnthropicBillingError("credit balance is too low")

        svc = _Billing(outcome={})
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await execute_tool(
                "force_resummarize",
                {"topic_id": TOPIC_ID, "confirm": True},
                current_user=_admin(),
                confirm_flow_state={
                    "tool_name": "force_resummarize",
                    "args": {"topic_id": TOPIC_ID},
                },
            )

        assert result["error_class"] == "AnthropicBillingError"
        assert svc.closed is True


# ---------------------------------------------------------------------------
# BUG-086 — the two-phase confirm contract must be unambiguous
# ---------------------------------------------------------------------------


def _gemini_function_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {"parts": [{"functionCall": {"name": name, "args": args}}]},
                "finishReason": "STOP",
            }
        ]
    }


def _gemini_text(text: str) -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"},
        ]
    }


# The exact sentence the LLM hand-authored in the prod trace (2026-07-25).
_PROD_SELF_AUTHORED_CONFIRM = (
    "🔍 Dry-run для «topic:tg:Docma_ru:post:252»: текущая версия 8, новых "
    "элементов 0, элементов в бандле 197. LLM не вызывался, версия не "
    'записывалась.\nПодтвердите, пожалуйста, пере-суммаризацию темы "Сервис '
    'DocMa" [да/нет]'
)


@pytest.mark.asyncio
class TestDryRunIsTerminal:
    """BUG-086 defect #2 — the ``dry_run`` report must never look like a preview."""

    async def test_dry_run_payload_is_not_a_preview(self):
        card_repo = _FakeCardRepo(_make_card())
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _fake_repos(card_repo, _FakeBundleRepo(_FakeBundle([]))),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "dry_run": True},
                current_user=_admin(),
            )

        # The FSM arms ConfirmFlow on ``preview is True`` and NOTHING else —
        # the dry-run report must not carry it (accidentally adding it would
        # make a stray «да» burn LLM tokens).
        assert "preview" not in result
        # …and it must SAY it is terminal, machine-readably, so neither the LLM
        # nor a future framework path has to infer it.
        assert result["terminal"] is True
        assert result["mutation_requires_confirm_preview_turn"] is True
        assert "confirm=false" in result["next_step"]

    async def test_dry_run_with_confirm_rejected_no_silent_no_op(self):
        """Pre-fix ``dry_run`` won over ``confirm`` → a confirmed run silently
        reported instead of re-summarizing. Now it is a typed rejection."""
        svc = _FakeService(outcome={"status": "ok"})
        card_repo = _FakeCardRepo(_make_card())
        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(card_repo, _FakeBundleRepo(_FakeBundle([]))),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "dry_run": True, "confirm": True},
                current_user=_admin(),
            )

        assert result["error_class"] == "InvalidArguments"
        assert "mutually exclusive" in result["error"]
        assert result["topic_id"] == TOPIC_ID
        # Neither branch ran: no report was built, no service was invoked.
        assert card_repo.calls == []
        assert svc.calls == []

    async def test_declaration_dry_run_description_states_the_contract(self):
        decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "force_resummarize")
        dry_run_desc = decl["parameters"]["properties"]["dry_run"]["description"]
        assert "TERMINAL" in dry_run_desc
        assert "confirm=false" in dry_run_desc
        assert "BUG-086" in dry_run_desc


@pytest.mark.asyncio
class TestLlmAuthoredConfirmRecovery:
    """BUG-086 structural guard — an LLM-authored confirmation is repaired
    deterministically instead of dead-ending the user's «да»."""

    @staticmethod
    def _agent() -> GeminiAgent:
        return GeminiAgent(api_key="test-key", model="gemini-2.5-flash")

    async def test_prod_trace_arms_confirm_flow_with_framework_preview(self):
        """The exact prod trace: the LLM calls ``dry_run=true`` on a MUTATION
        request, then invents its own «Подтвердите … [да/нет]».

        Pre-fix: ``preview_pending`` stayed ``None`` → ConfirmFlow never armed →
        «да» hit the opaque «Я не совсем понимаю ваш ответ» fallback.
        """
        agent = self._agent()
        card_repo = _FakeCardRepo(_make_card(summary_version=8, new_items=0))
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                _gemini_text(_PROD_SELF_AUTHORED_CONFIRM),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(card_repo, _FakeBundleRepo(_FakeBundle([{"i": 1}]))),
            ),
        ):
            result = await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.preview_pending == {
            "tool_name": "force_resummarize",
            # ``dry_run`` stripped (it is what suppressed the preview) and no
            # ``confirm`` — the FSM adds ``confirm=True`` on the user's «да».
            "args": {"topic_id": TOPIC_ID},
        }
        # The framework's OWN preview text is rendered verbatim, so the user
        # sees a real confirmation ask instead of the LLM's invented one.
        assert result.preview_message is not None
        assert "Подтвердите [да/нет]" in result.preview_message
        assert "пересуммаризирована" in result.preview_message

    async def test_confirm_true_rejection_also_recovers(self):
        """A BUG-009-rejected ``confirm=true`` followed by a self-authored
        confirmation recovers through the same path (``confirm`` stripped)."""
        agent = self._agent()
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "confirm": True}),
                _gemini_text("Подтвердите, пожалуйста [да/нет]"),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
        ):
            result = await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.preview_pending == {
            "tool_name": "force_resummarize",
            "args": {"topic_id": TOPIC_ID},
        }

    async def test_dry_run_without_confirm_ask_stays_terminal(self):
        """A genuine «что будет, если …» dry-run must NOT arm anything — the
        guard fires only on a self-authored confirmation."""
        agent = self._agent()
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                _gemini_text(
                    "Текущая версия 8, новых элементов 0, элементов в бандле 197. LLM не вызывался."
                ),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
        ):
            result = await agent.process_message(
                "покажи, что будет, если пере-суммаризировать " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.preview_pending is None
        assert result.preview_message is None
        assert "Текущая версия 8" in result.response_text

    async def test_recovery_gives_up_when_no_preview_obtainable(self):
        """Topic vanished / permission denied → no invented FSM state, the
        LLM's text is preserved (no behavioural change vs pre-fix)."""
        agent = self._agent()
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                _gemini_text("Подтвердите пере-суммаризацию [да/нет]"),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(None), _FakeBundleRepo(None)),
            ),
        ):
            result = await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.preview_pending is None
        assert result.preview_message is None

    async def test_dry_run_paraphrasing_the_next_step_hint_stays_terminal(self):
        """BUG-086 follow-up: the dry-run payload's own ``next_step`` hint says
        «call again with confirm=false», and the LLM routinely paraphrases it.

        With the original bare-``confirm`` detector that echo looked like a
        self-authored confirmation: the guard replaced the REQUESTED read-only
        report with a mutation preview and armed ConfirmFlow, so a stray «да»
        would have burned LLM tokens on a re-summarize nobody asked for.
        """
        agent = self._agent()
        card_repo = _FakeCardRepo(_make_card(summary_version=8, new_items=0))
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                _gemini_text(
                    "🔍 Dry-run: текущая версия 8, новых элементов 0. LLM не вызывался. "
                    "Чтобы действительно пере-суммаризировать, нужно вызвать "
                    "force_resummarize с confirm=false и без dry_run — подтверждения "
                    "этого отчёта не требуется."
                ),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(card_repo, _FakeBundleRepo(_FakeBundle([{"i": 1}]))),
            ),
        ):
            result = await agent.process_message(
                "покажи, что будет, если пере-суммаризировать " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.preview_pending is None
        assert result.preview_message is None
        # The user keeps the report they asked for, verbatim.
        assert "Dry-run" in result.response_text
        # And the recovery never re-issued the tool (one dry-run round-trip only).
        assert card_repo.calls == [TOPIC_ID], card_repo.calls

    async def test_read_only_turn_never_triggers_the_guard(self):
        """No confirm-gated write tool ran → the detector is never consulted,
        even when the answer text happens to contain «подтвердите»."""
        agent = self._agent()
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("list_channels", {}),
                _gemini_text("Подтвердите, пожалуйста, что это нужный канал [да/нет]"),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.bot.tools._exec_list_channels",
                AsyncMock(return_value={"channels": []}),
            ),
        ):
            result = await agent.process_message("покажи каналы", current_user=_admin())

        assert result.preview_pending is None

    async def test_real_preview_turn_is_untouched(self):
        """The correct flow (``confirm=false``) still arms ConfirmFlow through
        the ORIGINAL path — the guard must not double-issue the tool."""
        agent = self._agent()
        card_repo = _FakeCardRepo(_make_card(summary_version=8, new_items=0))
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call(
                    "force_resummarize", {"topic_id": TOPIC_ID, "confirm": False}
                ),
                _gemini_text("Тема будет пересуммаризирована. Подтвердите [да/нет]"),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(card_repo, _FakeBundleRepo(_FakeBundle([]))),
            ),
        ):
            result = await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

        assert result.preview_pending == {
            "tool_name": "force_resummarize",
            "args": {"topic_id": TOPIC_ID},
        }
        # Exactly ONE executor round-trip: the preview came from the normal
        # path, so the recovery re-run never fired.
        assert card_repo.calls == [TOPIC_ID]


class TestLlmAuthoredConfirmDetector:
    """The guard's module-level knobs (narrow detector + flag registry)."""

    # The PRODUCTION decision function — never a re-implementation of it, so a
    # detector regression cannot hide behind test-local scrubbing.
    _detects = staticmethod(_looks_like_llm_authored_confirm)

    def test_detector_is_narrow(self):
        for text in (
            "Подтвердите, пожалуйста, пере-суммаризацию темы [да/нет]",
            "Подтверждаете запуск?",
            "Please confirm the re-summarize",
            "Proceed? [yes/no]",
        ):
            assert self._detects(text), text
        for text in (
            "Текущая версия 8, новых элементов 0.",
            "Тема не найдена.",
            "Вот список каналов: durov, genotek.",
        ):
            assert not self._detects(text), text

    def test_argument_literals_are_not_a_confirmation_ask(self):
        """BUG-086 follow-up — plumbing quoted back at the user is not an ask.

        Each of these fired the ORIGINAL bare-``confirm`` detector, which turned
        a legitimate read-only dry-run turn into an armed mutation preview.
        """
        for text in (
            "Вызовите force_resummarize с confirm=false и без dry_run.",
            "Call force_resummarize again with confirm=false, WITHOUT dry_run.",
            "Аргумент confirm=true передавать нельзя.",
            "Read-only report — no confirmation is pending.",
            "Отчёт сформирован без подтверждения; ничего не изменилось.",
        ):
            assert not self._detects(text), text

    @pytest.mark.asyncio
    async def test_detector_ignores_the_dry_run_payloads_own_next_step(self):
        """Self-maintaining pin on the interaction that produced the defect: the
        hint the LLM is most likely to paraphrase must never read as an ask, so
        rewording ``next_step`` can never silently re-arm the recovery path."""
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
        ):
            report = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "dry_run": True},
                current_user=_admin(),
            )

        assert report["terminal"] is True
        assert not self._detects(report["next_step"]), report["next_step"]

    def test_dry_run_is_registered_as_preview_suppressing(self):
        assert "dry_run" in _PREVIEW_SUPPRESSING_ARGS
        assert "confirm" not in _PREVIEW_SUPPRESSING_ARGS


class TestPromptHardRule:
    """BUG-086 prompt hardening — mirrors the existing prompt-defense asserts."""

    @staticmethod
    def _bot_yaml() -> dict:
        import yaml

        path = Path(__file__).resolve().parent.parent / "prompts" / "bot.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_version_bumped_within_the_1_9_pin(self):
        version = self._bot_yaml()["metadata"]["version"]
        # ``tests/test_f9_phase2_prompt_defense.py`` pins the 1.9 series.
        assert version.startswith("1.9")
        assert tuple(int(p) for p in version.split(".")) >= (1, 9, 3)

    def test_version_consistent_in_system_prompt(self):
        data = self._bot_yaml()
        version = data["metadata"]["version"]
        assert f"- Version: {version}" in data["system"]["prompt"]

    def test_hard_rule_separates_the_two_call_shapes(self):
        prompt = self._bot_yaml()["system"]["prompt"]
        assert "BUG-086" in prompt, "bot.yaml lost the BUG-086 force_resummarize hard rule"
        rule = next(line for line in prompt.splitlines() if "BUG-086" in line)
        assert "dry_run=true" in rule
        assert "confirm=false" in rule
        # The rule must forbid a self-authored confirmation and re-state BUG-009.
        assert "Подтвердите" in rule
        assert "BUG-009" in rule
