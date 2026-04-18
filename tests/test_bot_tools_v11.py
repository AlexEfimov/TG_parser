"""
Tests for Telegram bot V1.1 tools: trigger_pipeline, get_pipeline_status,
pause_channel, resume_channel (two-phase confirm + execute_tool dispatch).
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.bot.tools import (
    TOOL_DECLARATIONS,
    _background_tasks,
    _run_pipeline_background,
    _running_pipelines,
    execute_tool,
)
from tg_parser.storage.ports import Source

NOW = datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC)

INGEST_STATE_PATCH = "tg_parser.services.db_context.ingestion_state_repo"
SCHEDULER_STATUS_PATCH = "tg_parser.services.scheduler_service.get_scheduler_status"
CHANNEL_STATS_PATCH = "tg_parser.services.channel_service.get_channel_stats"


def _make_source(
    channel_id: str = "ch",
    status: str = "active",
    fail_count: int = 0,
    last_error: str | None = None,
) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status=status,
        include_comments=True,
        channel_username="test",
        fail_count=fail_count,
        last_error=last_error,
        created_at=NOW,
    )


def _mock_ingestion_state_repo(get_source_result=None):
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.get_source.return_value = get_source_result
    state_repo.upsert_source.return_value = None

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo


def _scheduler_sources_row(
    channel_id: str = "ch",
    *,
    last_attempt_at: str | None = "2026-01-01T00:00:00+00:00",
    last_success_at: str | None = "2026-01-02T00:00:00+00:00",
    fail_count: int = 0,
    last_error: str | None = None,
    status: str = "active",
) -> dict:
    return {
        "source_id": channel_id,
        "channel_id": channel_id,
        "status": status,
        "poll_interval_seconds": 600,
        "last_attempt_at": last_attempt_at,
        "last_success_at": last_success_at,
        "fail_count": fail_count,
        "last_error": last_error,
    }


def _full_scheduler_status(sources: list[dict] | None = None):
    return {
        "scheduler_enabled": True,
        "default_interval_seconds": 600,
        "retopicize_threshold": 5,
        "sources": sources or [],
    }


def _tool_names() -> set[str]:
    return {d["name"] for d in TOOL_DECLARATIONS}


class TestBotToolDeclarations:
    def test_v11_tools_registered(self):
        names = _tool_names()
        assert "trigger_pipeline" in names
        assert "get_pipeline_status" in names
        assert "pause_channel" in names
        assert "resume_channel" in names
        assert len(TOOL_DECLARATIONS) == 25


class TestExecuteToolTriggerPipeline:
    def setup_method(self):
        _running_pipelines.clear()
        _background_tasks.clear()

    async def test_preview_without_confirm(self):
        source = _make_source(channel_id="genotek", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        sched = _full_scheduler_status([_scheduler_sources_row("genotek")])
        mock_sched = AsyncMock(return_value=sched)
        mock_stats = AsyncMock(return_value={"processed_documents": 5400})

        with (
            patch(INGEST_STATE_PATCH, ctx),
            patch(SCHEDULER_STATUS_PATCH, mock_sched),
            patch(
                CHANNEL_STATS_PATCH,
                mock_stats,
            ),
        ):
            result = await execute_tool(
                "trigger_pipeline",
                {"channel_id": "@genotek", "force": True},
            )

        assert result["preview"] is True
        assert result["channel_id"] == "genotek"
        assert result["source_exists"] is True
        assert result["source_status"] == "active"
        assert result["processed_documents"] == 5400
        assert result["last_attempt_at"] is not None
        assert result["force"] is True
        assert result["pipeline_running_in_bot"] is False
        assert "confirm=true" in result["message"]

    async def test_preview_unknown_channel_stats_still_ok(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        mock_stats = AsyncMock(side_effect=ValueError("not in stats"))

        with (
            patch(INGEST_STATE_PATCH, ctx),
            patch(
                SCHEDULER_STATUS_PATCH,
                AsyncMock(return_value=_full_scheduler_status([])),
            ),
            patch(CHANNEL_STATS_PATCH, mock_stats),
        ):
            result = await execute_tool("trigger_pipeline", {"channel_id": "ch"})

        assert result["preview"] is True
        assert result["processed_documents"] is None

    async def test_confirm_triggers_background_task(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        mock_task = MagicMock()

        def _stub_create_task(coro, *, name=None):
            coro.close()
            return mock_task

        with (
            patch(INGEST_STATE_PATCH, ctx),
            patch(
                SCHEDULER_STATUS_PATCH,
                AsyncMock(return_value=_full_scheduler_status()),
            ),
            patch(CHANNEL_STATS_PATCH, AsyncMock(return_value={"processed_documents": 1})),
            patch(
                "tg_parser.bot.tools.asyncio.create_task",
                side_effect=_stub_create_task,
            ) as mock_create_task,
        ):
            result = await execute_tool(
                "trigger_pipeline",
                {"channel_id": "ch", "confirm": True, "force": False},
            )

        assert result["triggered"] is True
        assert result["channel_id"] == "ch"
        assert result["force"] is False
        mock_create_task.assert_called_once()
        mock_task.add_done_callback.assert_called_once()
        assert "ch" in _running_pipelines

    async def test_confirm_not_found(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None)
        with (
            patch(INGEST_STATE_PATCH, ctx),
            patch(
                SCHEDULER_STATUS_PATCH,
                AsyncMock(return_value=_full_scheduler_status()),
            ),
        ):
            result = await execute_tool(
                "trigger_pipeline",
                {"channel_id": "missing", "confirm": True},
            )

        assert result["triggered"] is False
        assert "not found" in result["message"].lower()

    async def test_confirm_non_active_source(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        with (
            patch(INGEST_STATE_PATCH, ctx),
            patch(
                SCHEDULER_STATUS_PATCH,
                AsyncMock(return_value=_full_scheduler_status()),
            ),
            patch(CHANNEL_STATS_PATCH, AsyncMock(return_value={"processed_documents": 0})),
        ):
            result = await execute_tool(
                "trigger_pipeline",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["triggered"] is False
        assert "paused" in result["message"]

    async def test_confirm_pipeline_already_running_in_bot(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        _running_pipelines.add("ch")
        with (
            patch(INGEST_STATE_PATCH, ctx),
            patch(
                SCHEDULER_STATUS_PATCH,
                AsyncMock(return_value=_full_scheduler_status()),
            ),
            patch(CHANNEL_STATS_PATCH, AsyncMock(return_value={"processed_documents": 1})),
        ):
            result = await execute_tool(
                "trigger_pipeline",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["triggered"] is False
        assert "already running" in result["message"].lower()


class TestExecuteToolGetPipelineStatus:
    async def test_all_sources(self):
        rows = [
            _scheduler_sources_row("a"),
            _scheduler_sources_row("b", status="paused"),
        ]
        mock_fn = AsyncMock(return_value=_full_scheduler_status(rows))
        with patch(SCHEDULER_STATUS_PATCH, mock_fn):
            result = await execute_tool("get_pipeline_status", {})

        assert result["scheduler_enabled"] is True
        assert result["default_interval_seconds"] == 600
        assert result["retopicize_threshold"] == 5
        assert len(result["sources"]) == 2
        assert {s["channel_id"] for s in result["sources"]} == {"a", "b"}

    async def test_filter_by_channel_normalizes_at(self):
        rows = [
            _scheduler_sources_row("genotek"),
            _scheduler_sources_row("other"),
        ]
        mock_fn = AsyncMock(return_value=_full_scheduler_status(rows))
        with patch(SCHEDULER_STATUS_PATCH, mock_fn):
            result = await execute_tool(
                "get_pipeline_status",
                {"channel_id": "@genotek"},
            )

        assert len(result["sources"]) == 1
        assert result["sources"][0]["channel_id"] == "genotek"


class TestExecuteToolPauseChannel:
    async def test_preview_active(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("pause_channel", {"channel_id": "ch"})

        assert result["preview"] is True
        assert result["current_status"] == "active"
        assert result["already_effectively_done"] is False
        assert "confirm=true" in result["message"]

    async def test_preview_already_paused(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("pause_channel", {"channel_id": "ch"})

        assert result["preview"] is True
        assert result["already_effectively_done"] is True

    async def test_confirm_pauses_active(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "pause_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["changed"] is True
        assert result["status"] == "paused"
        state_repo.upsert_source.assert_awaited_once()
        upserted: Source = state_repo.upsert_source.call_args[0][0]
        assert upserted.status == "paused"

    async def test_confirm_idempotent_paused(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "pause_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["changed"] is False
        state_repo.upsert_source.assert_not_awaited()

    async def test_not_found_preview(self):
        ctx, _ = _mock_ingestion_state_repo(get_source_result=None)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("pause_channel", {"channel_id": "nope"})

        assert result["preview"] is True
        assert result.get("error") == "not_found"

    async def test_not_found_confirm(self):
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=None)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "pause_channel",
                {"channel_id": "nope", "confirm": True},
            )

        assert result["changed"] is False
        assert "not found" in result["message"].lower()
        state_repo.upsert_source.assert_not_awaited()


class TestExecuteToolResumeChannel:
    async def test_preview_error_shows_counters_flag(self):
        source = _make_source(
            channel_id="ch",
            status="error",
            fail_count=3,
            last_error="boom",
        )
        ctx, _ = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool("resume_channel", {"channel_id": "ch"})

        assert result["preview"] is True
        assert result["clears_error_counters"] is True
        assert result["fail_count"] == 3
        assert result["last_error"] == "boom"
        assert "fail_count" in result["message"]

    async def test_confirm_from_error_clears_and_activates(self):
        source = _make_source(
            channel_id="ch",
            status="error",
            fail_count=5,
            last_error="err",
        )
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "resume_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["changed"] is True
        assert result["status"] == "active"
        upserted: Source = state_repo.upsert_source.call_args[0][0]
        assert upserted.status == "active"
        assert upserted.fail_count == 0
        assert upserted.last_error is None

    async def test_confirm_from_paused(self):
        source = _make_source(channel_id="ch", status="paused")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "resume_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["changed"] is True
        upserted: Source = state_repo.upsert_source.call_args[0][0]
        assert upserted.status == "active"

    async def test_confirm_idempotent_active(self):
        source = _make_source(channel_id="ch", status="active")
        ctx, state_repo = _mock_ingestion_state_repo(get_source_result=source)
        with patch(INGEST_STATE_PATCH, ctx):
            result = await execute_tool(
                "resume_channel",
                {"channel_id": "ch", "confirm": True},
            )

        assert result["changed"] is False
        state_repo.upsert_source.assert_not_awaited()


class TestBotRunPipelineBackground:
    def setup_method(self):
        _running_pipelines.clear()

    async def test_removes_from_running_even_on_pipeline_runtime_error(self):
        _running_pipelines.add("ch")
        mock_pipeline = AsyncMock(side_effect=RuntimeError("export failed"))
        mock_embedding = AsyncMock(return_value={"embedded": 1})

        with (
            patch(
                "tg_parser.services.pipeline_service.run_full_pipeline",
                mock_pipeline,
            ),
            patch(
                "tg_parser.services.embedding_service.run_embedding",
                mock_embedding,
            ),
        ):
            await _run_pipeline_background("ch", force=False)

        mock_pipeline.assert_awaited_once()
        mock_embedding.assert_awaited_once_with(channel_id="ch", force=False)
        assert "ch" not in _running_pipelines


class TestExecuteToolUnknown:
    async def test_unknown_tool_name(self):
        result = await execute_tool("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]
