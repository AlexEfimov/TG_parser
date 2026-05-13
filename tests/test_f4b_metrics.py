"""F4-B Core — Phase 5 Prometheus metrics tests.

Verifies that ``WorkspaceService`` emits the documented
``tg_workspace_*`` series on create / delete / resolver paths. We use
``REGISTRY.get_sample_value`` on a freshly-bumped counter / histogram so
the test is robust to ordering (other tests in the same suite may have
already incremented the counters).
"""

from __future__ import annotations

import os

import pytest
from prometheus_client import REGISTRY

from tg_parser.api.metrics import (
    WORKSPACE_QUERY_TOTAL,
    WORKSPACE_TOOL_TOTAL,
    record_workspace_query,
    record_workspace_tool,
)
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import WorkspaceNotFound
from tg_parser.services.workspace_service import WorkspaceService
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _user(user_id: str, *, role: str = "user", allowed: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="metric_user",
        role=role,
        allowed_channel_ids=None if role == "admin" else (allowed or []),
        max_channels=10,
    )


@pytest.fixture
async def metric_ws_service(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield WorkspaceService(SAWorkspaceRepo(session)), SAUserRepo(session)
    finally:
        await session.close()


def _query_total(result: str) -> float:
    return REGISTRY.get_sample_value("tg_workspace_query_total", {"result": result}) or 0.0


def _tool_total(tool: str, result: str) -> float:
    return (
        REGISTRY.get_sample_value("tg_workspace_tool_total", {"tool": tool, "result": result})
        or 0.0
    )


def _histogram_count(name: str) -> float:
    sample = REGISTRY.get_sample_value(name + "_count")
    return sample or 0.0


class TestMetricsRegistration:
    def test_workspace_query_counter_is_registered(self):
        names = {m.name for m in REGISTRY.collect() if m.name.startswith("tg_workspace_")}
        assert "tg_workspace_query" in names
        assert "tg_workspace_size" in names
        assert "tg_workspace_effective_size" in names
        assert "tg_workspace_resolver_seconds" in names
        assert "tg_workspace_tool" in names
        assert "tg_workspace_total" in names

    def test_workspace_tool_counter_is_registered(self):
        assert WORKSPACE_TOOL_TOTAL._name.startswith("tg_workspace_tool")

    def test_record_workspace_query_known_results(self):
        before = {r: _query_total(r) for r in ("scoped", "null_fallback", "not_found")}
        record_workspace_query(
            result="scoped", effective_size=2, workspace_size=3, duration_s=0.001
        )
        record_workspace_query(result="null_fallback")
        record_workspace_query(result="not_found")
        for r in ("scoped", "null_fallback", "not_found"):
            assert _query_total(r) == before[r] + 1.0

    def test_record_workspace_tool_outcome(self):
        WORKSPACE_QUERY_TOTAL  # noqa: B018 — sentinel ensure import side-effect
        before = _tool_total("create_workspace", "ok")
        record_workspace_tool(tool="create_workspace", result="ok")
        assert _tool_total("create_workspace", "ok") == before + 1.0


@pg_only
class TestResolverEmitsMetrics:
    async def test_null_fallback_increments_null_fallback_counter(self, metric_ws_service):
        svc, user_repo = metric_ws_service
        user_db = await user_repo.create_user("alice_metric_null")
        user = _user(user_db.id, allowed=["ch_a"])
        before = _query_total("null_fallback")
        result = await svc.effective_channel_ids(user, workspace_id=None)
        assert result == ["ch_a"]
        assert _query_total("null_fallback") == before + 1.0

    async def test_scoped_resolver_emits_size_histograms(self, metric_ws_service):
        svc, user_repo = metric_ws_service
        user_db = await user_repo.create_user("alice_metric_scoped")
        user = _user(user_db.id, allowed=[])
        ws = await svc.create_workspace(user, name="metric_scoped_ws", description=None)
        before_scoped = _query_total("scoped")
        before_size_n = _histogram_count("tg_workspace_size")
        before_eff_n = _histogram_count("tg_workspace_effective_size")
        before_dur_n = _histogram_count("tg_workspace_resolver_seconds")

        result = await svc.effective_channel_ids(user, workspace_id=ws.id)
        assert result == []
        assert _query_total("scoped") == before_scoped + 1.0
        assert _histogram_count("tg_workspace_size") == before_size_n + 1.0
        assert _histogram_count("tg_workspace_effective_size") == before_eff_n + 1.0
        assert _histogram_count("tg_workspace_resolver_seconds") == before_dur_n + 1.0

    async def test_unknown_workspace_id_increments_not_found(self, metric_ws_service):
        svc, user_repo = metric_ws_service
        user_db = await user_repo.create_user("alice_metric_404")
        user = _user(user_db.id)
        before = _query_total("not_found")
        with pytest.raises(WorkspaceNotFound):
            await svc.effective_channel_ids(
                user,
                workspace_id="00000000-0000-0000-0000-000000000999",
            )
        assert _query_total("not_found") == before + 1.0


@pg_only
class TestCreateDeleteEmitGauge:
    async def test_create_workspace_emits_gauge_bump(self, metric_ws_service):
        svc, user_repo = metric_ws_service
        user_db = await user_repo.create_user("alice_metric_gauge")
        user = _user(user_db.id)
        before = REGISTRY.get_sample_value("tg_workspace_total") or 0.0
        ws = await svc.create_workspace(user, name="metric_gauge_ws", description=None)
        assert REGISTRY.get_sample_value("tg_workspace_total") == before + 1.0
        deleted = await svc.delete_workspace(user, ws.id)
        assert deleted is True
        assert REGISTRY.get_sample_value("tg_workspace_total") == before
