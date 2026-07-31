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
* the agent-level snapshot: when a preview-LESS write call ends a turn, the
  agent hands the handler a ``write_intent_pending`` record of that CALL
  (``confirm`` and ``dry_run`` stripped) so the user's next bare «да» can obtain
  the real preview — #359 / ADR-0020 replaced the original prose detector, which
  predicted the confirmation ask from the LLM's own text;
* the ``prompts/bot.yaml`` hard rule that separates the two call shapes.

The deterministic trigger itself (the two-message protocol, adjacency, tier-1
tokens, authorization re-checks) lives in
``tests/test_bot_write_intent_trigger_359.py``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.agent import (
    _PREVIEW_SUPPRESSING_ARGS,
    MAX_AGENT_TURNS,
    GeminiAgent,
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

_SNAPSHOT = {"tool_name": "force_resummarize", "args": {"topic_id": TOPIC_ID}}


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
class TestPreviewLessWriteCallIsSnapshotted:
    """#359 / ADR-0020 — the AGENT half of the deterministic trigger.

    The agent reports the preview-less write CALL and nothing else: no preview is
    invented and no prose is read. The snapshot is sanitized at creation, so the
    mutating shape cannot be reconstructed from it. What the handler then does
    with it — and the fact that only a bare «да» consumes it — is pinned in
    ``tests/test_bot_write_intent_trigger_359.py``.
    """

    @staticmethod
    def _agent() -> GeminiAgent:
        return GeminiAgent(api_key="test-key", model="gemini-2.5-flash")

    async def test_prod_trace_hands_over_a_snapshot_and_arms_nothing(self):
        """The exact prod trace: the LLM calls ``dry_run=true`` on a MUTATION
        request, then invents its own «Подтвердите … [да/нет]».

        Pre-BUG-086 the «да» that followed dead-ended on «Я не совсем понимаю ваш
        ответ»; the first repair armed ``ConfirmFlow`` off that invented
        sentence. Now the sentence is irrelevant — the CALL is what is
        remembered, and nothing is armed until the user speaks.
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

        assert result.preview_pending is None
        assert result.preview_message is None
        # ``dry_run`` stripped (it is what suppressed the preview) and no
        # ``confirm`` — the FSM alone adds ``confirm=True``, on the second «да».
        assert result.write_intent_pending == _SNAPSHOT
        # The LLM's own text is relayed untouched and the tool was NOT re-issued.
        assert result.response_text == _PROD_SELF_AUTHORED_CONFIRM
        assert card_repo.calls == [TOPIC_ID], card_repo.calls

    async def test_confirm_true_rejection_is_snapshotted_too(self):
        """The OTHER way a confirm-gated write tool ends a turn with nothing
        armed: a BUG-009-rejected ``confirm=true`` (``confirm`` stripped)."""
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

        assert result.preview_pending is None
        assert result.write_intent_pending == _SNAPSHOT

    async def test_dry_run_arms_nothing_but_is_snapshotted(self):
        """A genuine «что будет, если …» dry-run arms nothing, exactly as before.

        What CHANGED is that the turn now also carries a snapshot: the report is
        honest, so nothing may be pre-empted — yet a user who reads it and
        answers a bare «да» means «go ahead» and must be served. Both halves are
        asserted so the new semantics of this turn are explicit.
        """
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
        assert result.write_intent_pending == _SNAPSHOT

    async def test_turn_limit_exhaustion_still_hands_over_the_snapshot(self):
        """Every terminal exit that carries ``preview_pending`` must carry the
        snapshot too (round-3 review).

        Running out of turns is not a reason to forget the write: the user was
        left with «переформулируйте» after a preview-less write call, which is
        the same dead-end the mechanism exists to close. The exhaustion exit
        already propagates ``preview_pending``, so dropping only the snapshot was
        an inconsistency between two returns of the same function.
        """
        agent = self._agent()
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("force_resummarize", {"topic_id": TOPIC_ID, "dry_run": True}),
                # Never a text-only part, so the loop runs out of turns instead
                # of leaving through the ``not function_calls`` branch.
                *[_gemini_function_call("list_channels", {}) for _ in range(MAX_AGENT_TURNS - 1)],
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
            ),
            patch(
                "tg_parser.bot.tools._exec_list_channels",
                AsyncMock(return_value={"channels": []}),
            ),
        ):
            result = await agent.process_message(
                "пере-суммаризируй тему " + TOPIC_ID,
                current_user=_admin(),
            )

        assert gemini.await_count == MAX_AGENT_TURNS
        assert "Не удалось получить окончательный ответ" in result.response_text
        assert result.preview_pending is None
        assert result.write_intent_pending == _SNAPSHOT

    async def test_read_only_turn_produces_no_snapshot(self):
        """No confirm-gated write tool ran, so there is nothing to resume — even
        when the answer text happens to carry every ask marker there is."""
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
        assert result.write_intent_pending is None

    async def test_real_preview_turn_is_untouched(self):
        """The happy path (``confirm=false``) still arms ConfirmFlow directly, in
        ONE executor round-trip and with NO snapshot — one confirmation, not
        two."""
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

        assert result.preview_pending == _SNAPSHOT
        assert result.write_intent_pending is None
        assert card_repo.calls == [TOPIC_ID]

    async def test_the_agent_logs_no_verdict_and_no_message_text(self):
        """The privacy norm outlives the deleted shadow layer: the agent emits no
        guard record at all now (the snapshot is logged by its single handler
        set-site, keys only), and the user's message never reaches the log."""
        user_message = "пере-суммаризируй тему " + TOPIC_ID
        agent = self._agent()
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
                _fake_repos(
                    _FakeCardRepo(_make_card(summary_version=8, new_items=0)),
                    _FakeBundleRepo(_FakeBundle([{"i": 1}])),
                ),
            ),
            capture_logs() as captured,
        ):
            result = await agent.process_message(user_message, current_user=_admin())

        assert result.write_intent_pending == _SNAPSHOT
        assert not [r for r in captured if str(r.get("event", "")).startswith("llm_authored")]
        blob = json.dumps(captured, ensure_ascii=False, default=str)
        assert user_message not in blob


class TestPreviewSuppressingRegistry:
    """The one module-level knob that outlives the detector: a report-only flag
    must be registered, or the deterministic re-issue would return the same
    preview-less payload and could never obtain a preview."""

    def test_dry_run_is_registered_as_preview_suppressing(self):
        assert "dry_run" in _PREVIEW_SUPPRESSING_ARGS
        assert "confirm" not in _PREVIEW_SUPPRESSING_ARGS

    @pytest.mark.asyncio
    async def test_the_dry_run_payload_is_still_terminal_and_says_so(self):
        """Self-maintaining pin on the interaction that produced BUG-086: the
        report advertises its own terminality machine-readably, so neither the
        LLM nor a future framework path has to infer it from prose."""
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _fake_repos(_FakeCardRepo(_make_card()), _FakeBundleRepo(_FakeBundle([]))),
        ):
            report = await _exec_force_resummarize(
                {"topic_id": TOPIC_ID, "dry_run": True},
                current_user=_admin(),
            )

        assert report["terminal"] is True
        assert "confirm=false" in report["next_step"]
        assert "preview" not in report


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
