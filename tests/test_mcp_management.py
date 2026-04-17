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
    _background_tasks,
    _run_pipeline_background,
    _running_pipelines,
    add_channel,
    get_pipeline_status,
    pause_channel,
    remove_channel,
    resume_channel,
    trigger_pipeline,
)
from tg_parser.storage.ports import Source

_TEST_USER = CurrentUser(
    id="test-user", name="tester", role="user",
    allowed_channel_ids=None, max_channels=20,
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
            sources=[], get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("my_channel")

        assert isinstance(result, AddChannelResult)
        assert result.channel_id == "my_channel"
        assert result.source_id == "my_channel"
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
            sources=[], get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("@my_channel")

        assert result.channel_id == "my_channel"
        assert result.created is True

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_channel_limit_reached(self, mock_resolve):
        mock_resolve.return_value = _TEST_USER
        active_sources = [_make_source(channel_id=f"ch{i}") for i in range(20)]
        ctx, state_repo = _mock_ingestion_state_repo(
            sources=active_sources, get_source_result=None,
        )
        with patch(INGEST_STATE_PATCH, ctx):
            result = await add_channel("new_channel", ctx=None)

        assert result.status == "rejected"
        assert result.created is False
        assert "limit" in result.message.lower()
        state_repo.upsert_source.assert_not_awaited()


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
            channel_id="ch", status="error",
            fail_count=5, last_error="timeout",
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
        mock_status = _scheduler_status(sources_raw=[
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
        ])
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
        mock_status = _scheduler_status(sources_raw=[
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
        ])
        mock_fn = AsyncMock(return_value=mock_status)
        with patch(SCHEDULER_STATUS_PATCH, mock_fn):
            result = await get_pipeline_status(channel_id="ch1")

        assert len(result.sources) == 1
        assert result.sources[0].channel_id == "ch1"


# ===========================================================================
# trigger_pipeline
# ===========================================================================


class TestTriggerPipeline:

    def setup_method(self):
        _running_pipelines.clear()
        _background_tasks.clear()

    async def test_trigger_pipeline_success(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        mock_task = MagicMock()

        def _stub_create_task(coro, *, name=None):
            coro.close()
            return mock_task

        with patch(INGEST_STATE_PATCH, ctx), \
             patch("tg_parser.mcp_server.asyncio") as mock_asyncio:
            mock_asyncio.create_task.side_effect = _stub_create_task
            result = await trigger_pipeline("ch")

        assert isinstance(result, TriggerPipelineResult)
        assert result.triggered is True
        assert result.channel_id == "ch"
        mock_asyncio.create_task.assert_called_once()
        mock_task.add_done_callback.assert_called_once()

    async def test_trigger_pipeline_not_found(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await trigger_pipeline("nonexistent")

        assert result.triggered is False
        assert "not found" in result.message.lower()

    async def test_trigger_pipeline_paused(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await trigger_pipeline("ch")

        assert result.triggered is False
        assert "paused" in result.message.lower()

    async def test_trigger_pipeline_duplicate(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        _running_pipelines.add("ch")
        with patch(INGEST_STATE_PATCH, ctx):
            result = await trigger_pipeline("ch")

        assert result.triggered is False
        assert "already running" in result.message.lower()


class TestRunPipelineBackground:

    def setup_method(self):
        _running_pipelines.clear()

    async def test_embedding_runs_when_pipeline_fails(self):
        _running_pipelines.add("ch")
        mock_pipeline = AsyncMock(side_effect=RuntimeError("export failed"))
        mock_embedding = AsyncMock(return_value={"embedded": 10})

        with patch("tg_parser.mcp_server.run_full_pipeline", mock_pipeline, create=True), \
             patch("tg_parser.mcp_server.run_embedding", mock_embedding, create=True), \
             patch("tg_parser.services.pipeline_service.run_full_pipeline", mock_pipeline), \
             patch("tg_parser.services.embedding_service.run_embedding", mock_embedding):
            await _run_pipeline_background("ch", force=False)

        mock_pipeline.assert_awaited_once()
        mock_embedding.assert_awaited_once_with(channel_id="ch", force=False)
        assert "ch" not in _running_pipelines


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
    state_repo.delete_source.return_value = get_source_result is not None

    for repo in [raw_repo, proc_repo, failure_repo, embedding_repo,
                 topic_card_repo, topic_bundle_repo, job_repo, task_history_repo]:
        repo.delete_by_channel.return_value = 0

    @asynccontextmanager
    async def mock_ctx():
        yield (
            state_repo, raw_repo, proc_repo, failure_repo,
            embedding_repo, topic_card_repo, topic_bundle_repo,
            job_repo, task_history_repo, db,
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

    def setup_method(self):
        _running_pipelines.clear()

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
        _running_pipelines.add("ch")
        result = await remove_channel("ch", confirm=True)

        assert result.removed is False
        assert "running" in result.message.lower()

    async def test_remove_success(self):
        source = _make_source(channel_id="ch")
        mock_ctx, repos = _mock_removal_repos(get_source_result=source)

        repos["embedding"].delete_by_channel.return_value = 50
        repos["proc"].delete_by_channel.return_value = 100
        repos["failure"].delete_by_channel.return_value = 3
        repos["topic_card"].delete_by_channel.return_value = 10
        repos["topic_bundle"].delete_by_channel.return_value = 10
        repos["job"].delete_by_channel.return_value = 5
        repos["task_history"].delete_by_channel.return_value = 8
        repos["raw"].delete_by_channel.return_value = 120
        repos["state"].delete_source.return_value = True

        with patch(REMOVAL_REPOS_PATCH, mock_ctx):
            result = await remove_channel("ch", confirm=True)

        assert isinstance(result, RemoveChannelResult)
        assert result.removed is True
        assert result.channel_id == "ch"

        assert result.details["embeddings"] == 50
        assert result.details["processed_documents"] == 100
        assert result.details["processing_failures"] == 3
        assert result.details["topic_cards"] == 10
        assert result.details["topic_bundles"] == 10
        assert result.details["api_jobs"] == 5
        assert result.details["task_history"] == 8
        assert result.details["raw_messages"] == 120
        assert result.details["source"] == 1

        total = sum(result.details.values())
        assert total == 307
        assert "307" in result.message

        repos["embedding"].delete_by_channel.assert_awaited_once_with("ch")
        repos["proc"].delete_by_channel.assert_awaited_once_with("ch")
        repos["failure"].delete_by_channel.assert_awaited_once_with("ch")
        repos["topic_card"].delete_by_channel.assert_awaited_once_with("ch")
        repos["topic_bundle"].delete_by_channel.assert_awaited_once_with("ch")
        repos["job"].delete_by_channel.assert_awaited_once_with("ch")
        repos["task_history"].delete_by_channel.assert_awaited_once_with("ch")
        repos["raw"].delete_by_channel.assert_awaited_once_with("ch")
        repos["state"].delete_source.assert_awaited_once_with("ch")


# ===========================================================================
# S3: get_all_channel_stats (batch optimization)
# ===========================================================================

STATS_REPOS_PATCH = "tg_parser.services.channel_service.stats_repos"


def _mock_stats_repos(sources=None, raw_counts=None, proc_counts=None,
                      topic_cards_by_channel=None, bundles_by_channel=None,
                      missing_by_channel=None, source_refs_by_channel=None):
    """Mock all repos returned by stats_repos()."""
    sources = sources or []
    raw_counts = raw_counts or {}
    proc_counts = proc_counts or {}
    topic_cards_by_channel = topic_cards_by_channel or {}
    bundles_by_channel = bundles_by_channel or {}
    missing_by_channel = missing_by_channel or {}
    source_refs_by_channel = source_refs_by_channel or {}

    state_repo = AsyncMock()
    raw_repo = AsyncMock()
    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    emb_repo = AsyncMock()
    db = MagicMock()

    state_repo.list_sources.return_value = sources
    raw_repo.count_by_channel.side_effect = lambda cid: raw_counts.get(cid, 0)
    proc_repo.count_by_channel.side_effect = lambda cid: proc_counts.get(cid, 0)
    proc_repo.list_source_refs_by_channel.side_effect = lambda cid: source_refs_by_channel.get(cid, [])
    topic_card_repo.list_by_channel.side_effect = lambda cid: topic_cards_by_channel.get(cid, [])
    topic_bundle_repo.list_by_channel.side_effect = lambda cid: bundles_by_channel.get(cid, [])
    emb_repo.list_missing.side_effect = lambda cid: missing_by_channel.get(cid, [])

    @asynccontextmanager
    async def mock_ctx():
        yield (
            state_repo, raw_repo, proc_repo,
            topic_card_repo, topic_bundle_repo, emb_repo, db,
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

    async def test_batch_stats_handles_per_channel_error(self):
        from tg_parser.services.channel_service import get_all_channel_stats

        sources = [_make_source(channel_id="ch")]
        mock_ctx = _mock_stats_repos(sources=sources)

        state_repo = AsyncMock()
        raw_repo = AsyncMock()
        raw_repo.count_by_channel.side_effect = RuntimeError("DB down")
        state_repo.list_sources.return_value = sources

        @asynccontextmanager
        async def error_ctx():
            yield (
                state_repo, raw_repo, AsyncMock(), AsyncMock(),
                AsyncMock(), AsyncMock(), MagicMock(),
            )

        with patch(STATS_REPOS_PATCH, error_ctx):
            result = await get_all_channel_stats()

        assert len(result) == 1
        assert result[0]["channel_id"] == "ch"
        assert result[0]["raw_messages"] == 0
        assert result[0]["coverage_percent"] == 0.0

    async def test_batch_stats_uses_count_not_list(self):
        """Verify count_by_channel is called instead of list_by_channel."""
        from tg_parser.services.channel_service import get_all_channel_stats

        sources = [_make_source(channel_id="ch")]

        state_repo = AsyncMock()
        raw_repo = AsyncMock()
        proc_repo = AsyncMock()
        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        emb_repo = AsyncMock()
        db = MagicMock()

        state_repo.list_sources.return_value = sources
        raw_repo.count_by_channel.return_value = 200
        proc_repo.count_by_channel.return_value = 190
        proc_repo.list_source_refs_by_channel.return_value = []
        topic_card_repo.list_by_channel.return_value = []
        topic_bundle_repo.list_by_channel.return_value = []
        emb_repo.list_missing.return_value = []

        @asynccontextmanager
        async def mock_ctx():
            yield (
                state_repo, raw_repo, proc_repo,
                topic_card_repo, topic_bundle_repo, emb_repo, db,
            )

        with patch(STATS_REPOS_PATCH, mock_ctx):
            result = await get_all_channel_stats()

        raw_repo.count_by_channel.assert_awaited_once_with("ch")
        proc_repo.count_by_channel.assert_awaited_once_with("ch")
        assert not hasattr(raw_repo.list_by_channel, 'await_count') or \
               raw_repo.list_by_channel.await_count == 0
        assert result[0]["raw_messages"] == 200
        assert result[0]["processed_documents"] == 190
