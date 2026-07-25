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
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from tg_parser.auth.models import CurrentUser
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
