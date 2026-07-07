"""
Tests for MCP Management Tools (S2).

Covers: add_channel, pause_channel, resume_channel,
        get_pipeline_status, trigger_pipeline.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.auth.models import CurrentUser
from tg_parser.mcp_server import (
    AddChannelResult,
    ChannelStatusResult,
    PipelineStatusResult,
    RemoveChannelResult,
    TriggerPipelineResult,
    add_channel,
    get_pipeline_status,
    pause_channel,
    remove_channel,
    resume_channel,
    trigger_pipeline,
)
from tg_parser.storage.ports import Source

_TEST_USER = CurrentUser(
    id="test-user",
    name="tester",
    role="user",
    allowed_channel_ids=None,
    max_channels=20,
)


NOW = datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC)

INGEST_STATE_PATCH = "tg_parser.services.db_context.ingestion_state_repo"
SCHEDULER_STATUS_PATCH = "tg_parser.services.scheduler_service.get_scheduler_status"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(
    channel_id: str = "ch",
    status: str = "active",
    channel_username: str | None = "test_channel",
    fail_count: int = 0,
    last_error: str | None = None,
) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status=status,
        include_comments=True,
        channel_username=channel_username,
        fail_count=fail_count,
        last_error=last_error,
        created_at=NOW,
    )


def _mock_ingestion_state_repo(sources=None, get_source_result=None):
    sources = sources or []
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.list_sources.return_value = sources
    state_repo.get_source.return_value = get_source_result
    # BUG-010 (Session I): mirror get_source_result so "not found" tests still hold
    state_repo.get_source_by_username.return_value = get_source_result
    state_repo.upsert_source.return_value = None

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo


def _scheduler_status(sources_raw=None):
    return {
        "scheduler_enabled": True,
        "default_interval_seconds": 600,
        "retopicize_threshold": 5,
        "sources": sources_raw or [],
    }


# ===========================================================================
# add_channel
# ===========================================================================


class TestAddChannel:
    async def test_add_channel_new(self):
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=[],
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            # NB: BUG-002 M2 — `my_channel` is a blocked placeholder; use
            # a non-reserved name for the happy-path test.
            result = await add_channel("my_blog")

        assert isinstance(result, AddChannelResult)
        assert result.channel_id == "my_blog"
        assert result.source_id == "my_blog"
        assert result.status == "active"
        assert result.created is True
        state_repo.upsert_source.assert_awaited_once()

    async def test_add_channel_update(self):
        existing = _make_source(channel_id="ch")
        ctx, state_repo = _mock_ingestion_state_repo(
            get_source_result=existing,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("ch", include_comments=True)

        assert result.created is False
        assert result.status == "active"
        state_repo.upsert_source.assert_awaited_once()
        upserted: Source = state_repo.upsert_source.call_args[0][0]
        assert upserted.created_at == NOW

    async def test_add_channel_normalizes_at(self):
        ctx, _ = _mock_ingestion_state_repo(
            sources=[],
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("@my_blog")

        assert result.channel_id == "my_blog"
        assert result.created is True

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_channel_limit_reached(self, mock_resolve):
        mock_resolve.return_value = _TEST_USER
        active_sources = [_make_source(channel_id=f"ch{i}") for i in range(20)]
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=active_sources,
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("new_blog", ctx=None)

        assert result.status == "rejected"
        assert result.created is False
        assert "limit" in result.message.lower()
        state_repo.upsert_source.assert_not_awaited()


class TestAddChannelBlockedPlaceholder:
    """BUG-002 mitigation M2 — placeholder reject-list at MCP surface."""

    async def test_rejects_test_channel(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=[],
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("test_channel")

        assert result.status == "rejected"
        assert result.created is False
        assert "placeholder" in result.message.lower()
        state_repo.upsert_source.assert_not_awaited()

    async def test_rejects_normalized_at_prefix(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=[],
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("@example_channel")

        assert result.channel_id == "example_channel"
        assert result.status == "rejected"
        state_repo.upsert_source.assert_not_awaited()

    async def test_env_extension_rejects_runtime_added_name(self, monkeypatch):
        monkeypatch.setenv("BLOCKED_CHANNEL_IDS", "foo,bar,baz")
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=[],
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("foo")

        assert result.status == "rejected"
        assert result.created is False
        state_repo.upsert_source.assert_not_awaited()

    async def test_real_channel_proceeds_normally(self, monkeypatch):
        monkeypatch.delenv("BLOCKED_CHANNEL_IDS", raising=False)
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=[],
            get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("real_channel_xyz")

        assert result.status == "active"
        assert result.created is True
        state_repo.upsert_source.assert_awaited_once()


# ===========================================================================
# pause_channel
# ===========================================================================


class TestPauseChannel:
    async def test_pause_channel_active(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await pause_channel("ch")

        assert isinstance(result, ChannelStatusResult)
        assert result.status == "paused"
        assert result.previous_status == "active"
        assert result.changed is True
        state_repo.upsert_source.assert_awaited_once()

    async def test_pause_channel_already_paused(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await pause_channel("ch")

        assert result.changed is False
        assert result.status == "paused"
        state_repo.upsert_source.assert_not_awaited()

    async def test_pause_channel_not_found(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await pause_channel("nonexistent")

        assert result.changed is False
        assert "not found" in result.message.lower()


# ===========================================================================
# resume_channel
# ===========================================================================


class TestResumeChannel:
    async def test_resume_channel_paused(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await resume_channel("ch")

        assert isinstance(result, ChannelStatusResult)
        assert result.status == "active"
        assert result.previous_status == "paused"
        assert result.changed is True
        state_repo.upsert_source.assert_awaited_once()

    async def test_resume_channel_error_resets(self):
        source = _make_source(
            channel_id="ch",
            status="error",
            fail_count=5,
            last_error="timeout",
        )
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await resume_channel("ch")

        assert result.status == "active"
        assert result.previous_status == "error"
        assert result.changed is True
        upserted: Source = state_repo.upsert_source.call_args[0][0]
        assert upserted.fail_count == 0
        assert upserted.last_error is None

    async def test_resume_channel_not_found(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await resume_channel("nonexistent")

        assert result.changed is False
        assert "not found" in result.message.lower()


# ===========================================================================
# get_pipeline_status
# ===========================================================================


class TestGetPipelineStatus:
    async def test_get_pipeline_status_all(self):
        mock_status = _scheduler_status(
            sources_raw=[
                {
                    "source_id": "ch1",
                    "channel_id": "ch1",
                    "status": "active",
                    "poll_interval_seconds": 600,
                    "last_attempt_at": "2026-03-30T10:00:00",
                    "last_success_at": "2026-03-30T10:00:00",
                    "fail_count": 0,
                    "last_error": None,
                },
                {
                    "source_id": "ch2",
                    "channel_id": "ch2",
                    "status": "paused",
                    "poll_interval_seconds": 600,
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "fail_count": 0,
                    "last_error": None,
                },
            ]
        )
        mock_fn = AsyncMock(return_value=mock_status)
        with patch(SCHEDULER_STATUS_PATCH, mock_fn):
            result = await get_pipeline_status()

        assert isinstance(result, PipelineStatusResult)
        assert result.scheduler_enabled is True
        assert result.default_interval_seconds == 600
        assert len(result.sources) == 2
        assert result.sources[0].source_id == "ch1"
        assert result.sources[1].status == "paused"

    async def test_get_pipeline_status_filter(self):
        mock_status = _scheduler_status(
            sources_raw=[
                {
                    "source_id": "ch1",
                    "channel_id": "ch1",
                    "status": "active",
                    "poll_interval_seconds": 600,
                    "last_attempt_at": "2026-03-30T10:00:00",
                    "last_success_at": "2026-03-30T10:00:00",
                    "fail_count": 0,
                    "last_error": None,
                },
                {
                    "source_id": "ch2",
                    "channel_id": "ch2",
                    "status": "paused",
                    "poll_interval_seconds": 600,
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "fail_count": 0,
                    "last_error": None,
                },
            ]
        )
        mock_fn = AsyncMock(return_value=mock_status)
        with patch(SCHEDULER_STATUS_PATCH, mock_fn):
            result = await get_pipeline_status(channel_id="ch1")

        assert len(result.sources) == 1
        assert result.sources[0].channel_id == "ch1"


# ===========================================================================
# trigger_pipeline
# ===========================================================================


class TestTriggerPipeline:
    async def test_trigger_pipeline_success_via_dispatch(self):
        from tg_parser.services.pipeline_dispatch_client import PipelineDispatchClientResult

        dispatch = PipelineDispatchClientResult(
            channel_id="ch",
            triggered=True,
            message="queued",
            job_id="j1",
            job="full_pipeline",
        )
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", new_callable=AsyncMock),
            patch("tg_parser.mcp_server._extract_authenticated_user_id", return_value=None),
            patch("tg_parser.auth.ownership.assert_channel_access", new_callable=AsyncMock),
            patch(
                "tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger",
                new_callable=AsyncMock,
                return_value=dispatch,
            ),
        ):
            result = await trigger_pipeline("ch")

        assert isinstance(result, TriggerPipelineResult)
        assert result.triggered is True
        assert result.channel_id == "ch"
        assert result.job_id == "j1"

    async def test_trigger_pipeline_permission_denied(self):
        from tg_parser.auth.ownership import PermissionDenied

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", new_callable=AsyncMock),
            patch("tg_parser.mcp_server._extract_authenticated_user_id", return_value="u1"),
            patch(
                "tg_parser.auth.ownership.assert_channel_access",
                new_callable=AsyncMock,
                side_effect=PermissionDenied("denied"),
            ),
        ):
            result = await trigger_pipeline("ch")

        assert result.triggered is False
        assert result.error_class == "PermissionDenied"


# ===========================================================================
# remove_channel
# ===========================================================================

REMOVAL_REPOS_PATCH = "tg_parser.services.db_context.removal_repos"


def _mock_removal_repos(get_source_result=None):
    """Mock all repos returned by removal_repos()."""
    state_repo = AsyncMock()
    raw_repo = AsyncMock()
    proc_repo = AsyncMock()
    failure_repo = AsyncMock()
    embedding_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    job_repo = AsyncMock()
    task_history_repo = AsyncMock()
    db = MagicMock()

    state_repo.get_source.return_value = get_source_result
    # BUG-010 (Session I): mirror get_source_result so "not found" tests still hold
    state_repo.get_source_by_username.return_value = get_source_result
    state_repo.delete_source.return_value = get_source_result is not None

    for repo in [
        raw_repo,
        proc_repo,
        failure_repo,
        embedding_repo,
        topic_card_repo,
        topic_bundle_repo,
        job_repo,
        task_history_repo,
    ]:
        repo.delete_by_channel.return_value = 0

    @asynccontextmanager
    async def mock_ctx():
        yield (
            state_repo,
            raw_repo,
            proc_repo,
            failure_repo,
            embedding_repo,
            topic_card_repo,
            topic_bundle_repo,
            job_repo,
            task_history_repo,
            db,
        )

    repos = {
        "state": state_repo,
        "raw": raw_repo,
        "proc": proc_repo,
        "failure": failure_repo,
        "embedding": embedding_repo,
        "topic_card": topic_card_repo,
        "topic_bundle": topic_bundle_repo,
        "job": job_repo,
        "task_history": task_history_repo,
    }

    return mock_ctx, repos


class TestRemoveChannel:
    async def test_remove_no_confirm(self):
        result = await remove_channel("ch", confirm=False)

        assert isinstance(result, RemoveChannelResult)
        assert result.removed is False
        assert "confirm=true" in result.message
        assert result.details == {}

    async def test_remove_not_found(self):
        mock_ctx, repos = _mock_removal_repos(get_source_result=None)
        with patch(REMOVAL_REPOS_PATCH, mock_ctx):
            result = await remove_channel("ch", confirm=True)

        assert result.removed is False
        assert "not found" in result.message.lower()
        repos["state"].delete_source.assert_not_awaited()

    async def test_remove_pipeline_running(self):
        with patch(
            "tg_parser.services.pipeline_dispatch_service.is_channel_pipeline_busy",
            return_value=True,
        ):
            result = await remove_channel("ch", confirm=True)

        assert result.removed is False
        assert "running" in result.message.lower()

    async def test_remove_success_soft_delete(self):
        """BUG-002 M3: remove_channel must soft-delete only — no cascade.

        The tool now marks `sources.deleted_at = now()` and leaves
        raw_messages, processed_documents, topic_cards, embeddings,
        api_jobs, task_history untouched. This bounds the blast-radius
        of an LLM-hallucinated remove_channel call (BUG-002).
        """
        source = _make_source(channel_id="ch")
        mock_ctx, repos = _mock_removal_repos(get_source_result=source)
        repos["state"].delete_source.return_value = True

        with patch(REMOVAL_REPOS_PATCH, mock_ctx):
            result = await remove_channel("ch", confirm=True)

        assert isinstance(result, RemoveChannelResult)
        assert result.removed is True
        assert result.channel_id == "ch"

        assert result.details == {"source": 1, "soft_delete": True}
        assert "soft-delete" in result.message.lower()

        repos["state"].delete_source.assert_awaited_once_with("ch")

        repos["embedding"].delete_by_channel.assert_not_awaited()
        repos["proc"].delete_by_channel.assert_not_awaited()
        repos["failure"].delete_by_channel.assert_not_awaited()
        repos["topic_card"].delete_by_channel.assert_not_awaited()
        repos["topic_bundle"].delete_by_channel.assert_not_awaited()
        repos["job"].delete_by_channel.assert_not_awaited()
        repos["task_history"].delete_by_channel.assert_not_awaited()
        repos["raw"].delete_by_channel.assert_not_awaited()


# ===========================================================================
# S3: get_all_channel_stats (batch optimization)
# ===========================================================================

STATS_REPOS_PATCH = "tg_parser.services.channel_service.stats_repos"


def _mock_stats_repos(
    sources=None,
    raw_counts=None,
    proc_counts=None,
    topic_counts=None,
    coverage_counts=None,
):
    """Mock all repos returned by stats_repos() for the batched stats path.

    BUG-008 H1: ``get_all_channel_stats`` now issues batched aggregate queries
    (``count_all_grouped_by_channel`` / ``count_by_channel_grouped`` /
    ``coverage_counts_by_channel``) instead of a per-channel fan-out, so the mocks
    return ``{channel_id: value}`` dicts rather than per-call side effects.
    """
    sources = sources or []
    raw_counts = raw_counts or {}
    proc_counts = proc_counts or {}
    topic_counts = topic_counts or {}
    coverage_counts = coverage_counts or {}

    state_repo = AsyncMock()
    raw_repo = AsyncMock()
    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    emb_repo = AsyncMock()
    topic_link_repo = AsyncMock()
    db = MagicMock()

    state_repo.list_sources.return_value = sources
    raw_repo.count_all_grouped_by_channel.return_value = raw_counts
    proc_repo.count_all_grouped_by_channel.return_value = proc_counts
    topic_card_repo.count_by_channel_grouped.return_value = topic_counts
    proc_repo.coverage_counts_by_channel.return_value = coverage_counts
    topic_link_repo.list_all.return_value = []

    @asynccontextmanager
    async def mock_ctx():
        yield (
            state_repo,
            raw_repo,
            proc_repo,
            topic_card_repo,
            topic_bundle_repo,
            emb_repo,
            topic_link_repo,
            db,
        )

    return mock_ctx


class TestGetAllChannelStats:
    async def test_batch_stats_returns_all_channels(self):
        from tg_parser.services.channel_service import get_all_channel_stats

        sources = [
            _make_source(channel_id="ch1"),
            _make_source(channel_id="ch2", status="paused"),
        ]
        mock_ctx = _mock_stats_repos(
            sources=sources,
            raw_counts={"ch1": 100, "ch2": 50},
            proc_counts={"ch1": 95, "ch2": 48},
        )
        with patch(STATS_REPOS_PATCH, mock_ctx):
            result = await get_all_channel_stats()

        assert len(result) == 2
        assert result[0]["channel_id"] == "ch1"
        assert result[0]["raw_messages"] == 100
        assert result[0]["processed_documents"] == 95
        assert result[0]["status"] == "active"
        assert result[1]["channel_id"] == "ch2"
        assert result[1]["raw_messages"] == 50
        assert result[1]["status"] == "paused"

    async def test_batch_stats_empty(self):
        from tg_parser.services.channel_service import get_all_channel_stats

        mock_ctx = _mock_stats_repos(sources=[])
        with patch(STATS_REPOS_PATCH, mock_ctx):
            result = await get_all_channel_stats()

        assert result == []

    async def test_batch_stats_degrades_to_zeros_on_aggregation_error(self):
        """A failure in the batched aggregation degrades to zero-filled rows.

        BUG-008 H1: preserves the old "endpoint always returns one row per
        channel" contract — a DB error must not blow up ``list_channels``.
        """
        from tg_parser.services.channel_service import get_all_channel_stats

        sources = [_make_source(channel_id="ch")]

        state_repo = AsyncMock()
        raw_repo = AsyncMock()
        raw_repo.count_all_grouped_by_channel.side_effect = RuntimeError("DB down")
        state_repo.list_sources.return_value = sources

        # The non-raising aggregates must return real (empty) dicts, exactly like
        # a healthy repo with no rows — otherwise a bare AsyncMock returns a mock
        # whose ``.get()`` yields a coroutine and the per-channel coverage math
        # (covered / processed_count) raises TypeError instead of degrading.
        proc_repo = AsyncMock()
        proc_repo.count_all_grouped_by_channel.return_value = {}
        proc_repo.coverage_counts_by_channel.return_value = {}
        topic_card_repo = AsyncMock()
        topic_card_repo.count_by_channel_grouped.return_value = {}

        @asynccontextmanager
        async def error_ctx():
            yield (
                state_repo,
                raw_repo,
                proc_repo,
                topic_card_repo,
                AsyncMock(),
                AsyncMock(),
                AsyncMock(),
                MagicMock(),
            )

        with patch(STATS_REPOS_PATCH, error_ctx):
            result = await get_all_channel_stats()

        assert len(result) == 1
        assert result[0]["channel_id"] == "ch"
        assert result[0]["raw_messages"] == 0
        assert result[0]["coverage_percent"] == 0.0

    async def test_batch_stats_uses_grouped_aggregates_not_per_channel(self):
        """Verify the batched grouped aggregates are used, NOT the per-channel fan-out.

        BUG-008 H1 regression guard: the old code called ``count_by_channel`` /
        ``list_by_channel`` once per channel (O(channels)); the rewrite must call
        the grouped aggregates exactly once regardless of channel count and must
        NOT touch the per-channel methods.
        """
        from tg_parser.services.channel_service import get_all_channel_stats

        sources = [_make_source(channel_id="ch1"), _make_source(channel_id="ch2")]

        state_repo = AsyncMock()
        raw_repo = AsyncMock()
        proc_repo = AsyncMock()
        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        emb_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        db = MagicMock()

        state_repo.list_sources.return_value = sources
        raw_repo.count_all_grouped_by_channel.return_value = {"ch1": 200, "ch2": 10}
        proc_repo.count_all_grouped_by_channel.return_value = {"ch1": 190, "ch2": 8}
        topic_card_repo.count_by_channel_grouped.return_value = {"ch1": 3}
        proc_repo.coverage_counts_by_channel.return_value = {"ch1": 95}
        topic_link_repo.list_all.return_value = []

        @asynccontextmanager
        async def mock_ctx():
            yield (
                state_repo,
                raw_repo,
                proc_repo,
                topic_card_repo,
                topic_bundle_repo,
                emb_repo,
                topic_link_repo,
                db,
            )

        with patch(STATS_REPOS_PATCH, mock_ctx):
            result = await get_all_channel_stats()

        # Grouped aggregates called exactly once, regardless of channel count.
        raw_repo.count_all_grouped_by_channel.assert_awaited_once_with()
        proc_repo.count_all_grouped_by_channel.assert_awaited_once_with()
        topic_card_repo.count_by_channel_grouped.assert_awaited_once_with()
        proc_repo.coverage_counts_by_channel.assert_awaited_once_with()
        # Per-channel fan-out methods must NOT be used anymore.
        raw_repo.count_by_channel.assert_not_awaited()
        proc_repo.count_by_channel.assert_not_awaited()
        topic_card_repo.list_by_channel.assert_not_awaited()
        topic_bundle_repo.list_by_channel.assert_not_awaited()
        proc_repo.list_source_refs_by_channel.assert_not_awaited()

        assert result[0]["raw_messages"] == 200
        assert result[0]["processed_documents"] == 190
        assert result[0]["topics_count"] == 3
        # coverage = 95 / 190 * 100 = 50.0
        assert result[0]["coverage_percent"] == 50.0
        # ch2 has no topics/coverage rows → defaults to 0
        assert result[1]["topics_count"] == 0
        assert result[1]["coverage_percent"] == 0.0
        assert result[0]["processed_documents"] == 190
