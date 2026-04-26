"""F5-C MCP tools — pure-mock tests (no Postgres required).

Locks in:

- ``get_topic_versions`` ownership: admin / owner-of-one-source /
  non-owner. The "access to at least one source" rule mirrors
  ``TopicCardRepo.list_by_channels`` so cross-channel topics stay
  reachable from a single-channel user (gotcha #9 in the sprint prompt).
- ``force_resummarize`` admin-only and pass-through of the service
  outcome dict.

Wider DB plumbing (real ``commit_resummary``, advisory lock, etc.) is
covered separately by ``test_f5c_topic_card_repo.py`` and
``test_f5c_resummarization_service.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.domain.models import (
    Anchor,
    MessageType,
    TopicCard,
    TopicCardVersion,
    TopicType,
)


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
    topic_id: str = "topic:tg:c1:post:1",
    sources: list[str] | None = None,
    summary_version: int = 3,
    last_summarized_at: datetime | None = None,
    new_items: int = 0,
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
        last_summarized_at=last_summarized_at,
        new_items_since_last_summary=new_items,
    )


def _make_version(version_no: int = 1) -> TopicCardVersion:
    return TopicCardVersion(
        id=version_no,
        topic_id="topic:tg:c1:post:1",
        version_no=version_no,
        summary=f"Snapshot v{version_no}",
        scope_in=["alpha"],
        scope_out=["beta"],
        supporting_items_count_at_time=10 + version_no,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        prompt_version="1.0.0",
        created_at=datetime(2026, 4, 26, 10, version_no, 0, tzinfo=UTC),
    )


class _FakeCardRepo:
    def __init__(self, card: TopicCard | None) -> None:
        self._card = card

    async def get_by_id(self, _topic_id: str) -> TopicCard | None:
        return self._card


class _FakeVersionRepo:
    def __init__(self, versions: list[TopicCardVersion]) -> None:
        self._versions = versions
        self.calls: list[dict] = []

    async def list_by_topic(self, topic_id: str, limit: int = 50):
        self.calls.append({"topic_id": topic_id, "limit": limit})
        return list(self._versions[:limit])


@asynccontextmanager
async def _fake_resummarization_repos(card_repo, version_repo):
    yield (card_repo, "_bundle_repo", version_repo, "_db")


# ---------------------------------------------------------------------------
# get_topic_versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetTopicVersions:
    async def test_admin_sees_history(self):
        from tg_parser.mcp_server import get_topic_versions

        card = _make_card(summary_version=3, new_items=2)
        versions = [_make_version(3), _make_version(2), _make_version(1)]
        cr = _FakeCardRepo(card)
        vr = _FakeVersionRepo(versions)

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_resummarization_repos(cr, vr),
            ),
        ):
            result = await get_topic_versions(topic_id="topic:tg:c1:post:1", limit=10)

        assert result["topic_id"] == "topic:tg:c1:post:1"
        assert result["current_version"] == 3
        assert result["new_items_since_last_summary"] == 2
        assert len(result["versions"]) == 3
        assert result["versions"][0]["version_no"] == 3
        assert vr.calls == [{"topic_id": "topic:tg:c1:post:1", "limit": 10}]

    async def test_topic_not_found_returns_error(self):
        from tg_parser.mcp_server import get_topic_versions

        cr = _FakeCardRepo(None)
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_resummarization_repos(cr, vr),
            ),
        ):
            result = await get_topic_versions(topic_id="topic:tg:cX:post:1")

        assert "not found" in result["error"].lower()
        assert vr.calls == []

    async def test_owner_of_one_source_sees_cross_channel_topic(self):
        """Visibility rule: access to AT LEAST ONE source is enough.

        Mirrors ``TopicCardRepo.list_by_channels`` so a cross-channel
        topic stays reachable from a user that owns just one of its
        sources (gotcha #9). Without this, a non-admin owner of c1 would
        be locked out of any topic that also spans c2.
        """
        from tg_parser.mcp_server import get_topic_versions

        card = _make_card(sources=["c1", "c2"])
        cr = _FakeCardRepo(card)
        vr = _FakeVersionRepo([_make_version(1)])

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_scoped(["c1"])),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_resummarization_repos(cr, vr),
            ),
        ):
            result = await get_topic_versions(topic_id="topic:tg:c1:post:1")

        assert "error" not in result
        assert len(result["versions"]) == 1

    async def test_non_owner_without_access_is_denied(self):
        from tg_parser.mcp_server import get_topic_versions

        card = _make_card(sources=["c1", "c2"])
        cr = _FakeCardRepo(card)
        vr = _FakeVersionRepo([_make_version(1)])

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_scoped(["c-other"])),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_resummarization_repos(cr, vr),
            ),
        ):
            result = await get_topic_versions(topic_id="topic:tg:c1:post:1")

        assert "no access" in result["error"].lower()
        assert vr.calls == [], "must short-circuit before listing versions"

    async def test_invalid_limit_returns_error_without_db(self):
        from tg_parser.mcp_server import get_topic_versions

        cr = _FakeCardRepo(_make_card())
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_resummarization_repos(cr, vr),
            ),
        ):
            result_low = await get_topic_versions(topic_id="topic:tg:c1:post:1", limit=0)
            result_high = await get_topic_versions(topic_id="topic:tg:c1:post:1", limit=99999)

        assert "limit" in result_low["error"].lower()
        assert "limit" in result_high["error"].lower()


# ---------------------------------------------------------------------------
# force_resummarize
# ---------------------------------------------------------------------------


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


@asynccontextmanager
async def _fake_full_repos():
    yield ("card_repo", "bundle_repo", "version_repo", "db")


@pytest.mark.asyncio
class TestForceResummarize:
    async def test_admin_invokes_service_and_returns_outcome(self):
        """The MCP tool spreads ``outcome`` into the result, so the field
        name must match the real ``ResummarizationService`` contract.
        That contract is ``version_no`` (not ``summary_version``) — the
        previous version of this test mocked ``summary_version`` and
        masked a real shape mismatch in production code paths."""
        from tg_parser.mcp_server import force_resummarize

        svc = _FakeService(
            outcome={
                "status": "ok",
                "version_no": 4,
                "tokens": 1234,
                "duration_s": 0.42,
            }
        )

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_full_repos,
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await force_resummarize(topic_id="topic:tg:c1:post:1")

        assert result["topic_id"] == "topic:tg:c1:post:1"
        assert result["status"] == "ok"
        assert result["version_no"] == 4
        assert result["tokens"] == 1234
        assert svc.calls == ["topic:tg:c1:post:1"]
        assert svc.closed is True, "aclose must run regardless"

    async def test_locked_status_passes_through(self):
        """Concurrency contract: when another worker holds the advisory
        lock, ``status='locked'`` must reach the operator unchanged so
        they know to retry rather than treat it as a hard failure."""
        from tg_parser.mcp_server import force_resummarize

        svc = _FakeService(outcome={"status": "locked"})

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_full_repos,
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await force_resummarize(topic_id="topic:tg:c1:post:1")

        assert result["status"] == "locked"
        assert "error" not in result
        assert svc.closed is True

    async def test_billing_error_propagates_through_force_resummarize(self):
        """Gotcha #16 in the MCP layer: ``AnthropicBillingError`` must NOT
        be swallowed by the tool, even though it's an admin-only manual
        trigger.  Otherwise an admin running the tool to "test" things
        would burn through retries against a paused account."""
        from tg_parser.mcp_server import force_resummarize
        from tg_parser.processing.llm.errors import AnthropicBillingError

        class _Billing(_FakeService):
            async def resummarize_topic(self, topic_id: str):
                raise AnthropicBillingError("credit balance is too low")

        svc = _Billing(outcome={})

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_full_repos,
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            with pytest.raises(AnthropicBillingError):
                await force_resummarize(topic_id="topic:tg:c1:post:1")

        assert svc.closed is True, "aclose must run even on billing error"

    async def test_non_admin_is_denied(self):
        from tg_parser.mcp_server import force_resummarize

        svc = _FakeService(outcome={"status": "ok"})

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_scoped(["c1"])),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_full_repos,
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            result = await force_resummarize(topic_id="topic:tg:c1:post:1")

        assert "admin" in result["error"].lower()
        assert svc.calls == [], "service must NOT be invoked for non-admin"
        assert svc.closed is False, "service must NOT be created for non-admin"

    async def test_aclose_called_even_when_service_raises(self):
        from tg_parser.mcp_server import force_resummarize

        class _Boom(_FakeService):
            async def resummarize_topic(self, topic_id: str):
                raise RuntimeError("boom")

        svc = _Boom(outcome={})

        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=_admin()),
            ),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _fake_full_repos,
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await force_resummarize(topic_id="topic:tg:c1:post:1")

        assert svc.closed is True
