"""
Tests for the incremental-pipeline scheduler service (Session 30).

Tests cover:
- run_incremental_for_all_sources: iterate sources, run pipeline, record attempts
- Retopicization threshold logic
- Error isolation between sources
- get_scheduler_status
- BackgroundScheduler integration with incremental_pipeline_task
"""

import asyncio
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tg_parser.storage.ports import Source

# ============================================================================
# Helpers
# ============================================================================


def _mock_ingestion_and_processing_repos(state_repo, processed_repo):
    """Create a mock async context manager for ingestion_and_processing_repos."""

    @asynccontextmanager
    async def _cm():
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        yield state_repo, processed_repo, mock_db

    return _cm


def _mock_ingestion_and_processing_repos_queue(triples):
    """BUG-013 helper: yield a *distinct* mock triple per entry call.

    Used by T-1 to assert that ``_process_source`` opens its OWN session
    (i.e., each concurrent task receives a different ``state_repo`` /
    ``processed_repo`` instance). ``triples`` is an iterable of
    ``(state_repo, processed_repo, db)`` tuples. ``StopIteration`` is
    raised loudly if more entries are requested than provided — that
    signals a test/scheduler contract mismatch.
    """
    iterator = iter(triples)

    @asynccontextmanager
    async def _cm():
        triple = next(iterator)
        yield triple

    return _cm


def _mock_ingestion_state_repo(state_repo):
    """Create a mock async context manager for ingestion_state_repo."""

    @asynccontextmanager
    async def _cm():
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        yield state_repo, mock_db

    return _cm


def _ok_incr_result():
    """Build an :class:`IncrementalTopicizeResult` representing a successful tick.

    Lazy-import inside the helper so that test files that don't need the
    domain model (e.g., the helper-only unit tests) don't pay the import
    cost. Used by TD-05 watchlist-billing tests.
    """
    from tg_parser.domain.models import IncrementalTopicizeResult

    return IncrementalTopicizeResult(
        assigned_keyword=[],
        unassignable=[],
        coverage_before=0.0,
        coverage_after=0.0,
    )


# ============================================================================
# Tests: run_incremental_for_all_sources
# ============================================================================


def _incremental_outcome(outcome: str) -> float:
    """Read the B1 per-tick outcome counter (module-level; use before/after deltas)."""
    from tg_parser.api.metrics import INCREMENTAL_PIPELINE_SOURCES_TOTAL

    return INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome=outcome)._value.get()  # noqa: SLF001


@pytest.mark.asyncio
async def test_no_active_sources_returns_zero():
    """With no active sources the function returns immediately."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = []

    before = {o: _incremental_outcome(o) for o in ("succeeded", "failed", "degraded")}

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, AsyncMock()),
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_total"] == 0
    assert result["sources_succeeded"] == 0
    assert result["sources_failed"] == 0
    # Idle tick must NOT emit B1 outcomes (idle ≠ outage).
    for outcome, value in before.items():
        assert _incremental_outcome(outcome) == value, f"idle tick must not emit {outcome}"


@pytest.mark.asyncio
async def test_single_source_success():
    """One active source processes successfully."""
    source = Source(
        source_id="s1",
        channel_id="ch1",
        status="active",
        include_comments=False,
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion", new_callable=AsyncMock
        ) as mock_ingest,
        patch(
            "tg_parser.services.pipeline_service.run_processing", new_callable=AsyncMock
        ) as mock_process,
        patch(
            "tg_parser.services.pipeline_service.run_export", new_callable=AsyncMock
        ) as mock_export,
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
    ):
        mock_ingest.return_value = {
            "posts_collected": 3,
            "comments_collected": 0,
            "errors": 0,
            "duration_seconds": 0.5,
        }
        mock_process.return_value = {
            "processed_count": 3,
            "skipped_count": 0,
            "failed_count": 0,
            "total_count": 3,
        }
        mock_export.return_value = {"kb_entries_count": 3, "topics_count": 0, "channels_count": 1}

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_total"] == 1
    assert result["sources_succeeded"] == 1
    assert result["sources_failed"] == 0
    assert result["total_new_messages"] == 3

    mock_state_repo.record_attempt.assert_awaited_once()
    attempt_kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert attempt_kwargs["success"] is True
    assert attempt_kwargs["details"]["trigger"] == "scheduled"


@pytest.mark.asyncio
async def test_source_failure_does_not_block_others():
    """If one source fails, the other still runs."""
    source_ok = Source(source_id="ok", channel_id="ch_ok", status="active", include_comments=False)
    source_fail = Source(
        source_id="fail", channel_id="ch_fail", status="active", include_comments=False
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source_fail, source_ok]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    ok_ingest = {
        "posts_collected": 1,
        "comments_collected": 0,
        "errors": 0,
        "duration_seconds": 0.1,
    }
    ok_process = {"processed_count": 1, "skipped_count": 0, "failed_count": 0, "total_count": 1}
    ok_export = {"kb_entries_count": 1, "topics_count": 0, "channels_count": 1}

    async def mock_ingest_side_effect(**kwargs):
        source_id = kwargs.get("source_id", "")
        if source_id == "fail":
            raise RuntimeError("Telegram FloodWait")
        return ok_ingest

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            side_effect=mock_ingest_side_effect,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value=ok_process,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value=ok_export,
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_ok",
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 1
    assert result["sources_failed"] == 1
    assert "fail" in result["errors"]
    assert "FloodWait" in result["errors"]["fail"]


@pytest.mark.asyncio
async def test_incremental_topicize_triggers_on_new_docs():
    """Session 35: When new docs appear, incremental topicization is triggered."""
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()

    doc_before: list = []
    doc_after = [f"tg:ch1:post:{i}" for i in range(5)]

    call_count = 0

    async def list_refs_side_effect(channel_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return doc_before
        return doc_after

    mock_processed_repo.list_source_refs_by_channel.side_effect = list_refs_side_effect

    from tg_parser.domain.models import IncrementalTopicizeResult

    mock_incr_result = IncrementalTopicizeResult(
        assigned_keyword=[],
        unassignable=[],
        coverage_before=77.0,
        coverage_after=78.0,
    )

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={
                "posts_collected": 5,
                "comments_collected": 0,
                "errors": 0,
                "duration_seconds": 0.5,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 5,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 5,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 5, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=mock_incr_result,
        ) as mock_incr_topicize,
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 3
        mock_settings.scheduler_max_concurrent_sources = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    mock_incr_topicize.assert_awaited_once()
    call_args = mock_incr_topicize.call_args
    assert call_args[0][0] == "ch1"
    assert len(call_args[0][1]) == 5
    assert "s1" in result["retopicized_sources"]


@pytest.mark.asyncio
async def test_s4_phase3_runs_after_topic_embedding_with_defer():
    """S4 AC-A: scheduler defers Phase 3 from incremental and runs it after embed."""
    from tg_parser.domain.models import IncrementalTopicizeResult, TopicAssignment

    source = Source(
        source_id="s_s4",
        channel_id="ch_s4",
        status="active",
        include_comments=False,
    )
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.side_effect = [
        [],
        ["tg:ch_s4:post:1"],
    ]

    incr_result = IncrementalTopicizeResult(
        assigned_keyword=[
            TopicAssignment(
                source_ref="tg:ch_s4:post:1", topic_id="t:1", score=1.0, method="keyword"
            )
        ],
        coverage_before=90.0,
        coverage_after=95.0,
    )

    call_order: list[str] = []

    async def _incr(*args, **kwargs):
        call_order.append("incremental")
        assert kwargs.get("defer_cross_channel_linking") is True
        return incr_result

    async def _embed(*args, **kwargs):
        if kwargs.get("force") is True:
            call_order.append("embed_touched_force")
        else:
            call_order.append("embed_channel")
        return {"embedded_count": 1, "skipped_count": 0, "total_count": 1}

    async def _link(**kwargs):
        call_order.append("phase3_link")
        assert kwargs["touched_topic_ids"] == {"t:1"}
        return 2

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_s4",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            side_effect=_incr,
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            side_effect=_embed,
        ),
        patch(
            "tg_parser.services.topicization_service._run_cross_channel_linking",
            side_effect=_link,
        ),
        patch(
            "tg_parser.services.scheduler_service.run_resummarize_for_channel",
            new_callable=AsyncMock,
            return_value={"candidates": 0, "resummarized": 0, "skipped": 0, "tokens": 0},
        ),
        patch(
            "tg_parser.services.scheduler_service.run_watchlist_check_for_channel",
            new_callable=AsyncMock,
            return_value={"matches": 0},
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.cross_channel_topicization = True
        mock_settings.cross_channel_link_threshold = 0.3

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        await run_incremental_for_all_sources()

    assert call_order == [
        "incremental",
        "embed_channel",
        "embed_touched_force",
        "phase3_link",
    ]


@pytest.mark.asyncio
async def test_new_doc_refs_composition_and_order_characterization():
    """O-3 (F-03) characterization: new_doc_refs is the set difference
    ``refs_after - refs_before`` in ``source_ref ASC`` order — byte-for-byte the
    same as the old full-row ``list_by_channel(... ORDER BY source_ref ASC)``
    followed by an in-order comprehension.

    The refs repo (``list_source_refs_by_channel``) returns rows WITHOUT an
    ORDER BY, so the service sorts explicitly. This test feeds an intentionally
    UNSORTED ``refs_after`` with a partial overlap against ``refs_before`` and
    asserts the diff handed to ``run_incremental_topicization`` is exactly the
    new refs, sorted lexicographically (== Postgres text ``ORDER BY ASC``).
    """
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()
    # Existing refs (unsorted); new refs appear after the pipeline run.
    refs_before = ["tg:ch1:post:5", "tg:ch1:post:2"]
    # Unsorted after-set: overlaps {2,5}, adds {1,3,10}. Note the "1 < 10 < 3"
    # lexicographic ordering is the exact contract the old ORDER BY guaranteed.
    refs_after = [
        "tg:ch1:post:5",
        "tg:ch1:post:10",
        "tg:ch1:post:1",
        "tg:ch1:post:2",
        "tg:ch1:post:3",
    ]
    expected_new = ["tg:ch1:post:1", "tg:ch1:post:10", "tg:ch1:post:3"]

    call_count = 0

    async def _refs_side_effect(channel_id):
        nonlocal call_count
        call_count += 1
        return list(refs_before) if call_count == 1 else list(refs_after)

    mock_processed_repo.list_source_refs_by_channel.side_effect = _refs_side_effect

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 3, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 3,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 5,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 5, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=_ok_incr_result(),
        ) as mock_incr_topicize,
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        await run_incremental_for_all_sources()

    mock_incr_topicize.assert_awaited_once()
    passed_refs = mock_incr_topicize.call_args[0][1]
    # Composition: only the genuinely-new refs (overlap excluded).
    assert set(passed_refs) == set(expected_new)
    # Order: byte-for-byte the ORDER BY source_ref ASC sequence.
    assert passed_refs == expected_new


@pytest.mark.asyncio
async def test_incremental_topicize_skipped_when_no_new_docs():
    """Session 35: When no new docs appear, incremental topicization is not triggered."""
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()
    existing_ref = "tg:ch1:post:1"
    mock_processed_repo.list_source_refs_by_channel.return_value = [existing_ref]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={
                "posts_collected": 0,
                "comments_collected": 0,
                "errors": 0,
                "duration_seconds": 0.1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 0,
                "skipped_count": 1,
                "failed_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
        ) as mock_incr_topicize,
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 10
        mock_settings.scheduler_max_concurrent_sources = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    mock_incr_topicize.assert_not_awaited()
    assert result["retopicized_sources"] == []


@pytest.mark.asyncio
async def test_resummarize_hook_fires_on_quiet_tick_no_new_docs():
    """F5-C decoupling: the resummarize hook runs on EVERY tick, including
    quiet ones with no new docs, so the age/freshness trigger can fire on
    low-volume channels that never cross the counter threshold.

    Contract pin (mirrors ENH-001 for F11): incremental topicization stays
    gated on ``new_doc_refs`` and must NOT run here, but
    ``run_resummarize_for_channel`` MUST be awaited regardless.
    """
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()
    existing_ref = "tg:ch1:post:1"
    # Same docs before and after the pipeline → new_doc_refs == [] (quiet tick).
    mock_processed_repo.list_source_refs_by_channel.return_value = [existing_ref]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={
                "posts_collected": 0,
                "comments_collected": 0,
                "errors": 0,
                "duration_seconds": 0.1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 0,
                "skipped_count": 1,
                "failed_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
        ) as mock_incr_topicize,
        patch(
            "tg_parser.services.scheduler_service.run_resummarize_for_channel",
            new_callable=AsyncMock,
            return_value={
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "tokens": 0,
                "duration_s": 0.0,
            },
        ) as mock_resummarize,
        patch(
            "tg_parser.services.scheduler_service.run_watchlist_check_for_channel",
            new_callable=AsyncMock,
            return_value={"inserted": 0, "skipped_reason": "no_new_docs"},
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 10
        mock_settings.scheduler_max_concurrent_sources = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        await run_incremental_for_all_sources()

    # Gated stage stays gated: no new docs → no incremental topicization.
    mock_incr_topicize.assert_not_awaited()
    # Decoupled stage fires anyway: the age trigger gets a chance every tick.
    mock_resummarize.assert_awaited_once_with(channel_id="ch1")


# ============================================================================
# Tests: get_scheduler_status
# ============================================================================


@pytest.mark.asyncio
async def test_get_scheduler_status():
    """Status returns source list with expected fields."""
    source = Source(
        source_id="s1",
        channel_id="ch1",
        status="active",
        include_comments=True,
        poll_interval_seconds=1800,
        last_success_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
        fail_count=0,
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_enabled = True
        mock_settings.scheduler_default_interval = 3600
        mock_settings.scheduler_retopicize_threshold = 10

        from tg_parser.services.scheduler_service import get_scheduler_status

        status = await get_scheduler_status()

    assert status["scheduler_enabled"] is True
    assert status["default_interval_seconds"] == 3600
    assert len(status["sources"]) == 1

    src = status["sources"][0]
    assert src["source_id"] == "s1"
    assert src["status"] == "active"
    assert src["poll_interval_seconds"] == 1800
    assert src["fail_count"] == 0


# ============================================================================
# Tests: BackgroundScheduler incremental_pipeline_task
# ============================================================================


@pytest.mark.asyncio
async def test_incremental_pipeline_task_calls_service():
    """The APScheduler wrapper invokes run_incremental_for_all_sources."""
    with patch(
        "tg_parser.services.scheduler_service.run_incremental_for_all_sources",
        new_callable=AsyncMock,
        return_value={"sources_succeeded": 1, "sources_failed": 0},
    ) as mock_run:
        from tg_parser.services.scheduler_service import incremental_pipeline_task

        result = await incremental_pipeline_task()

    mock_run.assert_awaited_once()
    assert result["sources_succeeded"] == 1


# ============================================================================
# Tests: setup_default_tasks registers incremental job
# ============================================================================


def test_setup_default_tasks_registers_incremental_pipeline():
    """setup_default_tasks adds the incremental_pipeline job to the scheduler."""
    from tg_parser.services.background_scheduler import BackgroundScheduler, setup_default_tasks

    scheduler = BackgroundScheduler()
    setup_default_tasks(scheduler, incremental_pipeline_interval=300)

    task_ids = {t["id"] for t in scheduler.get_tasks()}
    assert "incremental_pipeline" in task_ids
    assert "cleanup_expired_records" in task_ids
    assert "health_check" in task_ids


# ============================================================================
# Tests: record_attempt helpers
# ============================================================================


@pytest.mark.asyncio
async def test_record_attempt_details_stored():
    """Verify that _safe_record_attempt stores details correctly."""
    mock_state_repo = AsyncMock()
    from tg_parser.services.scheduler_service import _safe_record_attempt

    exc = RuntimeError("test error")
    await _safe_record_attempt(
        mock_state_repo,
        "src1",
        success=False,
        failed_stage="pipeline",
        exc=exc,
        duration=1.5,
    )

    mock_state_repo.record_attempt.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["source_id"] == "src1"
    assert kwargs["success"] is False
    assert kwargs["failed_stage"] == "pipeline"
    assert kwargs["error_class"] == "RuntimeError"
    assert kwargs["error_message"] == "test error"
    assert kwargs["details"]["trigger"] == "scheduled"
    assert kwargs["details"]["duration_seconds"] == 1.5


@pytest.mark.asyncio
async def test_record_attempt_truncates_at_documented_limit():
    """Regression — Sprint D.1 documented a 4096-char ``error_message`` cap;
    the helper previously dropped at 500 silently. See REVIEW_2026-04-26
    MERGED_PLAN S-001 for context."""
    mock_state_repo = AsyncMock()
    from tg_parser.services.scheduler_service import _safe_record_attempt

    long_message = "a" * 5000
    exc = RuntimeError(long_message)
    await _safe_record_attempt(
        mock_state_repo,
        "src-long",
        success=False,
        failed_stage="pipeline",
        exc=exc,
        duration=2.0,
    )

    mock_state_repo.record_attempt.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    persisted = kwargs["error_message"]
    assert len(persisted) == 4096
    assert persisted == long_message[:4096]


def test_truncate_error_message_default_matches_documented_contract():
    """Direct unit-level guard: helper signature ships with 4096 default
    so any future regression to 500 fails fast."""
    import inspect

    from tg_parser.services.scheduler_service import _truncate_error_message

    sig = inspect.signature(_truncate_error_message)
    assert sig.parameters["max_len"].default == 4096
    assert _truncate_error_message("x" * 10_000) == "x" * 4096


@pytest.mark.asyncio
async def test_failed_incremental_topicization_marks_attempt_failed():
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    doc_after = ["tg:ch1:post:1"]
    mock_processed_repo.list_source_refs_by_channel.side_effect = [[], doc_after]

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(429, request=req, text="rate limited")

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError("HTTP error", request=req, response=resp),
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_class"] == "HTTPStatusError"
    assert kwargs["failed_stage"] == "incremental_topicization"
    assert kwargs["error_message"]


@pytest.mark.asyncio
async def test_billing_error_pauses_source_and_marks_failure():
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.processing.llm.errors import AnthropicBillingError

    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.side_effect = [[], ["tg:ch1:post:1"]]

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="incremental_topicization")
    metric_before = metric._value.get()
    t_before = datetime.now(UTC)

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            side_effect=AnthropicBillingError("credit balance exhausted"),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1
    mock_state_repo.upsert_source.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["error_class"] == "AnthropicBillingError"
    assert kwargs["failed_stage"] == "incremental_topicization"

    # Pause must point to the FUTURE by ~billing_block_backoff_s.  A naive
    # `is not None` check would not catch a regression that pauses to past time
    # (i.e. effectively no pause at all).
    assert source.rate_limit_until is not None
    delta = (source.rate_limit_until - t_before).total_seconds()
    assert 3500 <= delta <= 3700, (
        f"rate_limit_until should be ~3600s in the future, got delta={delta:.0f}s"
    )

    # Observability must move in lock-step with mitigation.
    assert metric._value.get() == metric_before + 1, (
        "ANTHROPIC_BILLING_BLOCK_TOTAL{stage=incremental_topicization} not incremented"
    )


# ============================================================================
# Tests: _record_and_pause_on_billing helper (TD-05)
# ============================================================================


@pytest.mark.asyncio
async def test_record_and_pause_on_billing_noop_when_stage_errors_empty():
    """TD-05: helper is a no-op on empty stage_errors list.

    Required so callers can invoke unconditionally from a ``finally``
    block without an explicit empty-list guard.
    """
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.services.scheduler_service import _record_and_pause_on_billing

    source = Source(
        source_id="s_noop", channel_id="ch_noop", status="active", include_comments=False
    )
    state_repo = AsyncMock()

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="watchlist_check")
    metric_before = metric._value.get()

    await _record_and_pause_on_billing([], source, state_repo)

    assert source.rate_limit_until is None, "empty stage_errors must not pause"
    state_repo.upsert_source.assert_not_called()
    assert metric._value.get() == metric_before, "empty stage_errors must not record"


@pytest.mark.asyncio
async def test_record_and_pause_on_billing_noop_when_first_error_is_not_billing():
    """TD-05: helper ignores non-billing first error (no metric/pause)."""
    from tg_parser.services.scheduler_service import _record_and_pause_on_billing

    source = Source(
        source_id="s_other", channel_id="ch_other", status="active", include_comments=False
    )
    state_repo = AsyncMock()

    await _record_and_pause_on_billing(
        [("ingest", RuntimeError("boom"))],
        source,
        state_repo,
    )

    assert source.rate_limit_until is None
    state_repo.upsert_source.assert_not_called()


@pytest.mark.asyncio
async def test_record_and_pause_on_billing_records_metric_and_pauses_source():
    """TD-05: happy-path — billing as first error → metric +1 and source paused."""
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.processing.llm.errors import AnthropicBillingError
    from tg_parser.services.scheduler_service import _record_and_pause_on_billing

    source = Source(
        source_id="s_bill", channel_id="ch_bill", status="active", include_comments=False
    )
    state_repo = AsyncMock()

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="resummarize")
    metric_before = metric._value.get()
    t_before = datetime.now(UTC)

    with patch("tg_parser.services.scheduler_service.settings") as mock_settings:
        mock_settings.billing_block_backoff_s = 1800
        await _record_and_pause_on_billing(
            [("resummarize", AnthropicBillingError("credit balance is too low"))],
            source,
            state_repo,
        )

    assert source.rate_limit_until is not None
    delta = (source.rate_limit_until - t_before).total_seconds()
    assert 1700 <= delta <= 1900, f"rate_limit_until ≈ +1800s, got delta={delta:.0f}s"
    state_repo.upsert_source.assert_awaited_once_with(source)
    assert metric._value.get() == metric_before + 1


@pytest.mark.asyncio
async def test_watchlist_billing_error_propagates_and_pauses_source():
    """TD-05 / merged-plan S-007: F11 hook must escalate AnthropicBillingError.

    Pre-fix the watchlist hook had a generic ``except Exception`` that
    swallowed billing errors → ``stage_errors`` stayed empty → the
    ``_record_and_pause_on_billing`` finally block found nothing to do →
    source was not paused → next tick re-incurred the billing call.
    Mirrors :func:`test_billing_error_pauses_source_and_marks_failure`
    but exercises the **watchlist** entry point instead of
    incremental_topicization.
    """
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.processing.llm.errors import AnthropicBillingError

    source = Source(
        source_id="s_wl",
        channel_id="ch_wl",
        status="active",
        include_comments=False,
    )
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.side_effect = [
        [],
        ["tg:ch_wl:post:1"],
    ]

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="watchlist_check")
    metric_before = metric._value.get()
    t_before = datetime.now(UTC)

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_wl",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=_ok_incr_result(),
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new_callable=AsyncMock,
            return_value={"updated": 0, "skipped": 0},
        ),
        patch(
            "tg_parser.services.scheduler_service.run_resummarize_for_channel",
            new_callable=AsyncMock,
            return_value={
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "tokens": 0,
                "duration_s": 0.0,
            },
        ),
        patch(
            "tg_parser.services.scheduler_service.run_watchlist_check_for_channel",
            new_callable=AsyncMock,
            side_effect=AnthropicBillingError("credit balance is too low"),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1, (
        "billing error in F11 hook must mark the source as failed (not silently logged)"
    )
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["error_class"] == "AnthropicBillingError"
    assert kwargs["failed_stage"] == "watchlist_check"

    assert source.rate_limit_until is not None, (
        "F11 billing error must trigger _pause_source_for_billing via stage_errors"
    )
    delta = (source.rate_limit_until - t_before).total_seconds()
    assert 3500 <= delta <= 3700

    assert metric._value.get() == metric_before + 1, (
        "ANTHROPIC_BILLING_BLOCK_TOTAL{stage=watchlist_check} must increment "
        "in lock-step with the source pause"
    )


@pytest.mark.asyncio
async def test_watchlist_generic_exception_does_not_pause_source():
    """TD-05 regression: F11 silent-log contract preserved for non-billing failures.

    Decision #13 says F11 watchlist failures (other than billing) must
    silent-log without polluting ``stage_errors`` so ``success`` is not
    falsified for upstream stages. The TD-05 fix adds a billing-specific
    ``except`` arm — this test guards that the existing generic-exception
    path is untouched.
    """
    source = Source(
        source_id="s_wl_other",
        channel_id="ch_wl_other",
        status="active",
        include_comments=False,
    )
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.side_effect = [
        [],
        ["tg:ch_wl_other:post:1"],
    ]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_wl_other",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=_ok_incr_result(),
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new_callable=AsyncMock,
            return_value={"updated": 0, "skipped": 0},
        ),
        patch(
            "tg_parser.services.scheduler_service.run_resummarize_for_channel",
            new_callable=AsyncMock,
            return_value={
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "tokens": 0,
                "duration_s": 0.0,
            },
        ),
        patch(
            "tg_parser.services.scheduler_service.run_watchlist_check_for_channel",
            new_callable=AsyncMock,
            side_effect=RuntimeError("F11 transient failure"),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert source.rate_limit_until is None, (
        "non-billing F11 failure must NOT trigger source pause (silent-log contract)"
    )
    assert result["sources_succeeded"] == 1, (
        "non-billing F11 failure must NOT mark source as failed — "
        "F11 is post-processing, upstream stages succeeded"
    )


# ============================================================================
# Tests: _safe_stats helper
# ============================================================================


def test_safe_stats_filters_non_serializable():
    """_safe_stats only keeps scalar values."""
    from tg_parser.services.scheduler_service import _safe_stats

    stats = {
        "ingest": {
            "posts_collected": 5,
            "comments_collected": 0,
            "errors": 0,
            "duration_seconds": 1.23,
            "_internal": [1, 2, 3],
        },
        "process": {"processed_count": 5, "failed_count": 0},
        "topicize": None,
        "export": None,
    }

    result = _safe_stats(stats)
    assert "_internal" not in result["ingest"]
    assert result["ingest"]["posts_collected"] == 5
    assert "process" in result
    assert "topicize" not in result
    assert "export" not in result


# ============================================================================
# Tests: BUG-013 / BUG-014 / BUG-024 joint fix-sprint (T-1 .. T-6)
# ============================================================================
#
# Pure-mock unit tests. T-1 uses the queue-based fixture to assert that
# each concurrent task receives a DISTINCT (state_repo, processed_repo, db)
# triple — i.e. per-task SQLAlchemy AsyncSession isolation. T-2 verifies
# ``asyncio.gather(return_exceptions=True)`` isolation. T-3 / T-4 / T-5
# exercise the BUG-014 / BUG-024 invariants. T-6 verifies the
# unhandled-escape log line.


@pytest.mark.asyncio
async def test_bug013_per_task_session_isolation_across_concurrent_sources():
    """T-1 (BUG-013): each ``_process_source`` task opens its OWN repo triple.

    Two active sources → ``ingestion_and_processing_repos`` is entered
    TWICE, each time yielding a distinct ``(state_repo, processed_repo,
    db)``. The queue-based fixture loudly fails (``StopIteration``) if
    the scheduler regresses to opening a single shared triple.
    """
    source_a = Source(source_id="s_a", channel_id="ch_a", status="active", include_comments=False)
    source_b = Source(source_id="s_b", channel_id="ch_b", status="active", include_comments=False)

    outer_state_repo = AsyncMock()
    outer_state_repo.list_sources.return_value = [source_a, source_b]

    task_a_state = AsyncMock()
    task_a_processed = AsyncMock()
    task_a_processed.list_source_refs_by_channel.return_value = []
    task_b_state = AsyncMock()
    task_b_processed = AsyncMock()
    task_b_processed.list_source_refs_by_channel.return_value = []

    db_a = MagicMock()
    db_a.close = AsyncMock()
    db_b = MagicMock()
    db_b.close = AsyncMock()

    triples = [
        (task_a_state, task_a_processed, db_a),
        (task_b_state, task_b_processed, db_b),
    ]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(outer_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos_queue(triples),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={
                "posts_collected": 0,
                "comments_collected": 0,
                "errors": 0,
                "duration_seconds": 0.0,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 0,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            side_effect=lambda *a, **kw: a[0] if a else "ch_a",
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_max_concurrent_sources = 2
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.processing_concurrency = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        await run_incremental_for_all_sources()

    task_a_state.mark_attempt_started.assert_awaited_once_with("s_a")
    task_b_state.mark_attempt_started.assert_awaited_once_with("s_b")
    task_a_state.record_attempt.assert_awaited_once()
    task_b_state.record_attempt.assert_awaited_once()
    assert outer_state_repo is not task_a_state
    assert outer_state_repo is not task_b_state
    assert task_a_state is not task_b_state, (
        "BUG-013 regression: both tasks received the SAME state_repo — "
        "AsyncSession is being shared across asyncio.gather tasks"
    )
    # § 4.2 spec asserts: outer state_repo is used ONLY for list_sources;
    # per-task state writes (record_attempt, mark_attempt_started) MUST hit
    # the per-task triples, never the outer one. Catches a regression where
    # someone routes per-task writes back through the outer session.
    outer_state_repo.list_sources.assert_awaited_once_with(status="active")
    outer_state_repo.record_attempt.assert_not_called()
    outer_state_repo.mark_attempt_started.assert_not_called()


@pytest.mark.asyncio
async def test_bug013_return_exceptions_isolates_unhandled_escape(caplog):
    """T-2 (BUG-013): an unhandled escape from one task must NOT cancel siblings.

    ``record_attempt`` is wrapped in an outer try/except inside
    ``_process_source``, so we induce the escape one level higher: make
    ``mark_attempt_started`` raise for the faulty source. This bypasses
    the per-task try/except/finally and propagates to ``asyncio.gather``.
    With ``return_exceptions=True`` the sibling task still records its
    attempt; without it, ``gather`` would cancel siblings.
    """
    import logging

    source_ok = Source(
        source_id="ok_src", channel_id="ch_ok", status="active", include_comments=False
    )
    source_bad = Source(
        source_id="bad_src", channel_id="ch_bad", status="active", include_comments=False
    )

    outer_state_repo = AsyncMock()
    outer_state_repo.list_sources.return_value = [source_bad, source_ok]

    ok_state = AsyncMock()
    ok_processed = AsyncMock()
    ok_processed.list_source_refs_by_channel.return_value = []
    bad_state = AsyncMock()
    bad_state.mark_attempt_started.side_effect = RuntimeError("unhandled escape")
    bad_processed = AsyncMock()
    bad_processed.list_source_refs_by_channel.return_value = []

    triples_by_source = {
        "bad_src": (bad_state, bad_processed, MagicMock(close=AsyncMock())),
        "ok_src": (ok_state, ok_processed, MagicMock(close=AsyncMock())),
    }
    consumed: list[tuple] = []

    @asynccontextmanager
    async def _selecting_cm():
        # Order-independent: pop next; the first task to enter gets the
        # head triple. We don't care which is which — both source-id
        # arms exist in the dict and the assertion below targets ``ok_state``
        # regardless of dispatch order.
        if not consumed:
            triple = triples_by_source["bad_src"]
        else:
            triple = triples_by_source["ok_src"]
        consumed.append(triple)
        yield triple

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(outer_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _selecting_cm,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 0, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 0,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch",
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
        caplog.at_level(logging.ERROR, logger="tg_parser.services.scheduler_service"),
    ):
        mock_settings.scheduler_max_concurrent_sources = 2
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.processing_concurrency = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    ok_state.record_attempt.assert_awaited_once()
    assert result["sources_total"] == 2
    # § 4.2 spec also requires: the bad source's exception is logged via
    # caplog and does NOT cascade. Mirrors T-6 specifically for this test
    # so the contract holds independently of T-6's existence.
    assert any(
        "scheduler_unhandled_escape" in record.getMessage() and "bad_src" in record.getMessage()
        for record in caplog.records
    ), (
        "T-2 regression: per-task unhandled escape from gather must be "
        "surfaced via scheduler_unhandled_escape structured log line"
    )


@pytest.mark.asyncio
async def test_bug014_naive_rate_limit_until_does_not_crash():
    """T-3 (BUG-014): a tz-naive ``rate_limit_until`` must compare cleanly.

    Pre-fix this raised ``TypeError: can't compare offset-naive and
    offset-aware datetimes`` and aborted the task. With
    ``coerce_aware_utc`` (scheduler belt-and-suspenders) the comparison
    is aware-vs-aware and the source is correctly skipped (rate-limited
    until well into the future).
    """
    future_naive = datetime.now().replace(tzinfo=None) + timedelta(hours=1)
    assert future_naive.tzinfo is None

    source = Source(
        source_id="s_rl",
        channel_id="ch_rl",
        status="active",
        include_comments=False,
        rate_limit_until=future_naive,
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, AsyncMock()),
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_skipped"] == 1, (
        "BUG-014 regression: naive rate_limit_until should be coerced and "
        "the source should be cleanly skipped"
    )
    mock_state_repo.mark_attempt_started.assert_not_called()


@pytest.mark.asyncio
async def test_bug024_mark_attempt_started_called_before_pipeline_await():
    """T-4 (BUG-024): synchronous attempt-at write precedes the first pipeline await.

    Uses ``mock_calls`` ordering across the per-task state_repo and the
    pipeline functions to assert ``mark_attempt_started`` is awaited
    BEFORE ``run_ingestion`` is awaited. Guards against any future
    re-ordering that would re-introduce the invariant gap.
    """
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    call_order: list[str] = []

    async def _mark_started(_source_id):
        call_order.append("mark_attempt_started")

    async def _record_attempt(**_kwargs):
        call_order.append("record_attempt")

    async def _run_ingestion(**_kwargs):
        call_order.append("run_ingestion")
        return {"posts_collected": 0, "comments_collected": 0}

    mock_state_repo.mark_attempt_started.side_effect = _mark_started
    mock_state_repo.record_attempt.side_effect = _record_attempt

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            side_effect=_run_ingestion,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 0,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        await run_incremental_for_all_sources()

    mock_state_repo.mark_attempt_started.assert_awaited_once_with("s1")
    assert "mark_attempt_started" in call_order
    assert "run_ingestion" in call_order
    assert call_order.index("mark_attempt_started") < call_order.index("run_ingestion"), (
        "BUG-024 regression: mark_attempt_started must be awaited BEFORE the "
        "first pipeline await (run_ingestion)"
    )
    assert call_order.index("mark_attempt_started") < call_order.index("record_attempt")


@pytest.mark.asyncio
async def test_bug024_mark_attempt_started_skipped_for_rate_limited_source():
    """T-5b (BUG-024): rate-limited sources do NOT get the synchronous attempt-at write.

    **Forward-looking guardrail, not a fail-on-main regression test.** Both
    ``main`` (pre-fix) and the fix branch satisfy this invariant; the test
    exists to catch a FUTURE regression where someone moves
    ``mark_attempt_started`` to BEFORE the rate-limit check, accidentally
    over-marking skipped sources and violating BUG-024's narrower contract:
    «if the scheduler ACTUALLY ATTEMPTED a source (advanced past the
    rate-limit gate), `last_attempt_at` is non-null». A skipped source
    is by definition not attempted, so ``mark_attempt_started`` must NOT
    be called.

    The companion ``test_bug024_mark_attempt_started_survives_pipeline_failure``
    is the true fail-on-main regression test for BUG-024's positive case
    (attempt-at survives mid-pipeline crash).
    """
    future = datetime.now(UTC) + timedelta(hours=1)
    source = Source(
        source_id="s_rl",
        channel_id="ch_rl",
        status="active",
        include_comments=False,
        rate_limit_until=future,
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, AsyncMock()),
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_skipped"] == 1
    mock_state_repo.mark_attempt_started.assert_not_called()
    mock_state_repo.record_attempt.assert_not_called()


@pytest.mark.asyncio
async def test_bug013_unhandled_escape_emits_structured_log(caplog):
    """T-6 (BUG-013): an unhandled escape from gather is logged structurally.

    Mirrors T-2 but focuses specifically on the
    ``scheduler_unhandled_escape source_id=...`` log line emitted by the
    post-gather loop. Without this line, an escape would be lost in
    ``return_exceptions=True``'s silent-swallow behaviour.
    """
    import logging

    source = Source(
        source_id="escape_src",
        channel_id="ch_escape",
        status="active",
        include_comments=False,
    )

    outer_state_repo = AsyncMock()
    outer_state_repo.list_sources.return_value = [source]

    bad_state = AsyncMock()
    bad_state.mark_attempt_started.side_effect = RuntimeError("simulated escape")
    bad_processed = AsyncMock()
    bad_processed.list_source_refs_by_channel.return_value = []

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(outer_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(bad_state, bad_processed),
        ),
        caplog.at_level(logging.ERROR),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_total"] == 1
    assert any(
        "scheduler_unhandled_escape" in record.getMessage() and "escape_src" in record.getMessage()
        for record in caplog.records
    ), "T-6 regression: unhandled escape from a per-task body must be logged"


@pytest.mark.asyncio
async def test_bug024_mark_attempt_started_survives_pipeline_failure():
    """T-5a (BUG-024 § 4.2 spec): the attempt-at write survives mid-pipeline crash.

    Real fail-on-main regression test for BUG-024's positive case. Rigs
    ``run_ingestion`` to raise mid-execution; asserts:

    1. ``mark_attempt_started`` was awaited pre-failure (the synchronous
       commit happened BEFORE the first pipeline ``await``).
    2. ``record_attempt`` was still called in the per-task ``finally`` with
       ``success=False`` (the two writes are INDEPENDENT — the invariant
       survives even when the pipeline crashes).

    On ``main`` (pre-fix): ``mark_attempt_started`` doesn't exist as a port
    method, so the first assertion fails (awaited 0 times). On the fix
    branch: both writes occur in the documented order.
    """
    source = Source(
        source_id="s_crash", channel_id="ch_crash", status="active", include_comments=False
    )
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    call_order: list[str] = []

    async def _mark_started(_source_id):
        call_order.append("mark_attempt_started")

    async def _record_attempt(**_kwargs):
        call_order.append("record_attempt")

    async def _run_ingestion_raises(**_kwargs):
        call_order.append("run_ingestion")
        raise RuntimeError("simulated mid-pipeline crash")

    mock_state_repo.mark_attempt_started.side_effect = _mark_started
    mock_state_repo.record_attempt.side_effect = _record_attempt

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            side_effect=_run_ingestion_raises,
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_crash",
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    mock_state_repo.mark_attempt_started.assert_awaited_once_with("s_crash")
    mock_state_repo.record_attempt.assert_awaited_once()
    record_kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert record_kwargs["success"] is False, (
        "BUG-024 regression: pipeline failure must record_attempt with success=False"
    )
    assert record_kwargs["source_id"] == "s_crash"
    assert call_order.index("mark_attempt_started") < call_order.index("run_ingestion"), (
        "BUG-024 regression: mark_attempt_started must occur BEFORE the first "
        "pipeline await even when the pipeline subsequently raises"
    )
    assert "record_attempt" in call_order, (
        "BUG-024 regression: record_attempt must still be called in finally on pipeline failure"
    )
    assert result["sources_failed"] == 1


# ============================================================================
# Tests: coerce_aware_utc helper (T-6b — § 4.2 optional contract pin)
# ============================================================================


def test_coerce_aware_utc_returns_none_for_none():
    """T-6b case 1: ``None`` input passes through unchanged."""
    from tg_parser.domain.json_utils import coerce_aware_utc

    assert coerce_aware_utc(None) is None


def test_coerce_aware_utc_attaches_utc_to_naive():
    """T-6b case 2: tz-naive ``datetime`` gets ``UTC`` attached (value preserved)."""
    from tg_parser.domain.json_utils import coerce_aware_utc

    naive = datetime(2026, 5, 15, 12, 0, 0)
    assert naive.tzinfo is None

    coerced = coerce_aware_utc(naive)
    assert coerced is not None
    assert coerced.tzinfo is UTC
    # value preserved (only tzinfo attached, no shift)
    assert coerced.replace(tzinfo=None) == naive


def test_coerce_aware_utc_identity_on_already_aware():
    """T-6b case 3: already-aware ``datetime`` is returned unchanged.

    Important: this is not just ``tzinfo`` preservation — the IDENTITY
    contract means a non-UTC aware ``datetime`` is NOT silently shifted
    to UTC. The helper must be a strict «attach if missing» operation.
    """
    from tg_parser.domain.json_utils import coerce_aware_utc

    aware_utc = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
    assert coerce_aware_utc(aware_utc) is aware_utc, (
        "coerce_aware_utc must be identity on already-aware input — "
        "any non-trivial transformation risks a tz-shift bug"
    )

    # Stronger guard: non-UTC aware input must NOT be re-tagged to UTC.
    from datetime import timezone

    tz_plus4 = timezone(timedelta(hours=4))
    aware_other = datetime(2026, 5, 15, 12, 0, 0, tzinfo=tz_plus4)
    coerced = coerce_aware_utc(aware_other)
    assert coerced is aware_other
    assert coerced.tzinfo is tz_plus4, (
        "coerce_aware_utc must NOT silently shift non-UTC aware inputs"
    )


# ============================================================================
# BUG-068 (A2) — per-source watchdog
# BUG-067 (B1) — degraded-tick status
# BUG-067/B3 — per-channel coverage gauge
# ============================================================================


@asynccontextmanager
async def _yield_lock(acquired: bool):
    """Stand-in for ``_source_processing_lock`` in unit tests (no DB)."""
    yield acquired


def _bug067_source():
    return Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)


def _bug067_stack(stack, mock_state_repo, mock_processed_repo, run_full_pipeline):
    """Enter the common patch bundle for the A2/B1/B3 scheduler tests.

    ``run_full_pipeline`` is patched at the pipeline_service source module
    (the scheduler imports it locally inside run_incremental_for_all_sources).
    Returns the entered ``mock_settings`` MagicMock for further configuration.
    """
    stack.enter_context(
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        )
    )
    stack.enter_context(
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        )
    )
    stack.enter_context(
        patch(
            "tg_parser.services.pipeline_service.run_full_pipeline",
            run_full_pipeline,
        )
    )
    # Fix 4: stub the per-source advisory lock to always acquire, so these unit
    # tests are independent of any (possibly DB-initialized) global singleton.
    stack.enter_context(
        patch(
            "tg_parser.services.scheduler_service._source_processing_lock",
            lambda *_a, **_k: _yield_lock(True),
        )
    )
    mock_settings = stack.enter_context(patch("tg_parser.services.scheduler_service.settings"))
    mock_settings.scheduler_max_concurrent_sources = 1
    mock_settings.scheduler_retopicize_threshold = 100
    mock_settings.processing_concurrency = 1
    mock_settings.scheduler_source_timeout_s = 60
    mock_settings.scheduler_degraded_failure_ratio = 0.5
    mock_settings.scheduler_coverage_alert_ratio = 0.8
    return mock_settings


@pytest.mark.asyncio
async def test_a2_source_watchdog_times_out_releases_slot_and_records_failure():
    """BUG-068 (A2): a stuck source run is bounded by the per-source watchdog,
    cancelled, the scheduler slot released, and the tick recorded as a
    ``pipeline_timeout`` failure instead of wedging the whole scheduler."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    hang_cancelled = {"value": False}

    async def _hang(**_kwargs):
        try:
            await asyncio.sleep(30)  # far longer than the watchdog budget
        except asyncio.CancelledError:
            hang_cancelled["value"] = True
            raise
        return {}

    with ExitStack() as stack:
        mock_settings = _bug067_stack(stack, mock_state_repo, mock_processed_repo, _hang)
        mock_settings.scheduler_source_timeout_s = 0.1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        result = await run_incremental_for_all_sources()
        elapsed = loop.time() - t0

    assert elapsed < 10.0, "watchdog must fire fast, not wait for the full hang"
    assert hang_cancelled["value"] is True, "in-flight work must be cancelled on timeout"
    assert result["sources_failed"] == 1
    assert result["sources_succeeded"] == 0

    mock_state_repo.record_attempt.assert_awaited()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["failed_stage"] == "pipeline_timeout"


@pytest.mark.asyncio
async def test_h1_session_lock_contention_recorded_as_benign_not_failure():
    """BUG-070 (H1): a tick aborted by SessionLockContentionError (a sibling
    held the Telethon session past the wait budget) is recorded as the DISTINCT
    benign session_lock_contention outcome — counted in sources_lock_contended,
    NOT sources_failed/sources_degraded, and WITHOUT a failed record_attempt
    (no fail_count bump / no pipeline_timeout mislabel)."""
    from tg_parser.ingestion.telegram.telethon_client import SessionLockContentionError

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    async def _contend(**_kwargs):
        raise SessionLockContentionError("a sibling held the Telethon session")

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(side_effect=_contend),
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_lock_contended"] == 1
    assert result["sources_failed"] == 0
    assert result["sources_degraded"] == 0
    assert result["sources_succeeded"] == 0
    # Benign: no failed attempt recorded (mark_attempt_started may run, but
    # record_attempt — which bumps fail_count — must NOT).
    mock_state_repo.record_attempt.assert_not_awaited()


@pytest.mark.asyncio
async def test_b1_zero_of_n_tick_recorded_as_degraded_not_success():
    """BUG-067 (B1): a tick that attempted N docs but processed 0 (e.g. fully
    billing-blocked) is recorded as a degraded FAILURE — not a healthy
    success — with a meaningful last_error."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    degraded_stats = {
        "ingest": {"posts_collected": 0, "comments_collected": 0},
        "process": {
            "processed_count": 0,
            "skipped_count": 0,
            "failed_count": 5,
            "total_count": 5,
        },
        "export": {"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
    }

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=degraded_stats),
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 0
    assert result["sources_failed"] == 1
    assert result["sources_degraded"] == 1

    mock_state_repo.record_attempt.assert_awaited()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["failed_stage"] == "process_degraded"
    assert kwargs["error_class"] == "DegradedProcessingTick"
    assert "degraded processing tick" in kwargs["error_message"]
    assert kwargs["details"]["outcome"] == "degraded"


@pytest.mark.asyncio
async def test_b1_observability_hard_fail_increments_failed_not_degraded():
    """B1 / BUG-085: a hard-failing source increments outcome=failed by 1 and
    does NOT bump outcome=degraded (before/after delta — module Counter)."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    before_failed = _incremental_outcome("failed")
    before_degraded = _incremental_outcome("degraded")
    before_succeeded = _incremental_outcome("succeeded")

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(side_effect=RuntimeError("SessionCryptoError: key unset")),
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1
    assert result["sources_degraded"] == 0
    assert _incremental_outcome("failed") == before_failed + 1
    assert _incremental_outcome("degraded") == before_degraded
    assert _incremental_outcome("succeeded") == before_succeeded


@pytest.mark.asyncio
async def test_b1_observability_degraded_increments_degraded_not_failed_label():
    """B1 / BUG-085: a degraded tick bumps outcome=degraded but NOT the hard
    ``failed`` label — proves emit-site subtraction sources_failed - sources_degraded."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    degraded_stats = {
        "ingest": {"posts_collected": 0, "comments_collected": 0},
        "process": {
            "processed_count": 0,
            "skipped_count": 0,
            "failed_count": 5,
            "total_count": 5,
        },
        "export": {"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
    }

    before_failed = _incremental_outcome("failed")
    before_degraded = _incremental_outcome("degraded")
    before_succeeded = _incremental_outcome("succeeded")

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=degraded_stats),
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    # Aggregate still double-counts (sources_failed includes degraded)...
    assert result["sources_failed"] == 1
    assert result["sources_degraded"] == 1
    # ...but the Prometheus ``failed`` label is HARD-only (net of degraded).
    assert _incremental_outcome("degraded") == before_degraded + 1
    assert _incremental_outcome("failed") == before_failed
    assert _incremental_outcome("succeeded") == before_succeeded


@pytest.mark.asyncio
async def test_b1_partial_failure_below_threshold_stays_success():
    """BUG-067 (B1): a tick whose failure ratio is BELOW the degraded threshold
    is still recorded as a success (no false-positive degraded flag)."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = [
        f"tg:ch1:post:{i}" for i in range(8)
    ]

    ok_stats = {
        "ingest": {"posts_collected": 10, "comments_collected": 0},
        "process": {
            "processed_count": 8,
            "skipped_count": 0,
            "failed_count": 2,
            "total_count": 10,
        },
        "export": {"kb_entries_count": 8, "topics_count": 0, "channels_count": 1},
    }

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=ok_stats),
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 1
    assert result["sources_degraded"] == 0
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is True


@pytest.mark.asyncio
async def test_b3_channel_coverage_gauge_set_per_tick():
    """BUG-067/B3: each source tick exports a per-channel processed/raw coverage
    ratio so an under-covered channel is observable."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    # docs_before == docs_after (4 docs) so no new-doc topicization path runs;
    # processed_total = 4, raw_total = 10 -> coverage 0.4 (low).
    four_docs = [f"tg:ch1:post:{i}" for i in range(4)]
    mock_processed_repo.list_source_refs_by_channel.return_value = four_docs

    cov_stats = {
        "ingest": {"posts_collected": 0, "comments_collected": 0},
        "process": {
            "processed_count": 4,
            "skipped_count": 6,
            "failed_count": 0,
            "total_count": 10,
            # BUG-069: run_processing now surfaces the true raw backlog size
            # here; the coverage gauge uses it as the denominator.
            "raw_total_count": 10,
        },
        "export": {"kb_entries_count": 4, "topics_count": 0, "channels_count": 1},
    }

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=cov_stats),
        )
        mock_cov = stack.enter_context(patch("tg_parser.api.metrics.set_channel_coverage"))

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 1
    mock_cov.assert_called_once()
    cov_kwargs = mock_cov.call_args.kwargs
    assert cov_kwargs["channel_id"] == "ch1"
    assert cov_kwargs["ratio"] == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_bug069_coverage_uses_raw_total_not_bounded_window():
    """BUG-069: after the bounded process load, process_stats['total_count'] is
    the bounded WINDOW size (<= processing_tick_batch_size), not the channel's
    raw backlog. The coverage denominator must use raw_total_count, otherwise an
    established channel reports coverage >1 and a false channel_coverage_low is
    never (or wrongly) emitted."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    # 800 processed docs already exist for the channel (numerator).
    eight_hundred = [f"tg:ch1:post:{i}" for i in range(800)]
    mock_processed_repo.list_source_refs_by_channel.return_value = eight_hundred

    cov_stats = {
        "ingest": {"posts_collected": 5, "comments_collected": 0},
        "process": {
            "processed_count": 5,
            "skipped_count": 0,
            "failed_count": 0,
            # Bounded window this tick (NOT the backlog): only 5 new docs.
            "total_count": 5,
            "attempted_count": 5,
            # True raw backlog = 1000 -> coverage 800/1000 = 0.8.
            "raw_total_count": 1000,
        },
        "export": {"kb_entries_count": 800, "topics_count": 0, "channels_count": 1},
    }

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=cov_stats),
        )
        mock_cov = stack.enter_context(patch("tg_parser.api.metrics.set_channel_coverage"))

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 1
    cov_kwargs = mock_cov.call_args.kwargs
    # Old (buggy) behaviour: 800 / 5 = 160.0 (ratio >> 1). Fixed: 800 / 1000.
    assert cov_kwargs["ratio"] == pytest.approx(0.8)
    assert cov_kwargs["ratio"] <= 1.0


@pytest.mark.asyncio
async def test_fix2_degraded_uses_attempted_this_tick_not_total_backlog():
    """Fix 2 (HIGH): on a channel with a large already-processed backlog, the
    degraded ratio must use docs ATTEMPTED this tick (attempted_count), not the
    whole-channel total — otherwise fail_ratio dilutes to ~0 and B1 never fires."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = [
        f"tg:ch1:post:{i}" for i in range(992)
    ]

    backlog_stats = {
        "ingest": {"posts_collected": 10, "comments_collected": 0},
        "process": {
            "processed_count": 992,  # mostly re-appended backlog
            "skipped_count": 0,
            "failed_count": 8,
            "total_count": 1000,  # whole channel
            "attempted_count": 10,  # only 10 NEW docs attempted this tick
        },
        "export": {"kb_entries_count": 992, "topics_count": 0, "channels_count": 1},
    }

    with ExitStack() as stack:
        _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=backlog_stats),
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    # 8/10 = 0.8 >= 0.5 -> degraded (old code: 8/1000 = 0.008 -> would be success).
    assert result["sources_degraded"] == 1
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["failed_stage"] == "process_degraded"


@pytest.mark.asyncio
async def test_fix4_second_concurrent_run_for_same_source_is_skipped():
    """Fix 4: when the per-source advisory lock is already held by another
    in-flight tick, the source is skipped — run_full_pipeline is NOT invoked and
    no attempt is recorded (no duplicate Telegram/LLM work)."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    run_pipeline = AsyncMock(return_value={})

    with ExitStack() as stack:
        _bug067_stack(stack, mock_state_repo, mock_processed_repo, run_pipeline)
        # Override the stubbed lock to NOT acquire (simulates a concurrent tick).
        stack.enter_context(
            patch(
                "tg_parser.services.scheduler_service._source_processing_lock",
                lambda *_a, **_k: _yield_lock(False),
            )
        )

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_skipped"] == 1
    assert result["sources_succeeded"] == 0
    assert result["sources_failed"] == 0
    run_pipeline.assert_not_awaited()
    mock_state_repo.mark_attempt_started.assert_not_awaited()
    mock_state_repo.record_attempt.assert_not_awaited()


@pytest.mark.asyncio
async def test_fix4_source_lock_degrades_to_acquired_when_no_engine():
    """Fix 4: the advisory lock degrades to 'acquired' (process) when the DB
    engine is unavailable, so lock-infra problems never block processing."""
    from tg_parser.services import scheduler_service as ss

    fake_db = MagicMock()
    fake_db.ingestion_state_engine = None

    with patch(
        "tg_parser.storage.sqlalchemy.database.Database.get_instance",
        return_value=fake_db,
    ):
        async with ss._source_processing_lock("s1") as acquired:
            assert acquired is True


@pytest.mark.asyncio
async def test_billing_block_pauses_source_and_marks_tick_degraded():
    """BUG-067 (billing-pause): a processing billing block is surfaced via the
    process stats (not swallowed). The scheduler pauses the source for the
    billing backoff AND records the tick as degraded — not a silent success,
    and without crashing sibling sources."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [_bug067_source()]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_source_refs_by_channel.return_value = []

    billing_stats = {
        "ingest": {"posts_collected": 0, "comments_collected": 0},
        "process": {
            "processed_count": 0,
            "skipped_count": 0,
            "failed_count": 5,
            "total_count": 5,
            "billing_blocked_count": 5,
        },
        "export": {"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
    }

    with ExitStack() as stack:
        mock_settings = _bug067_stack(
            stack,
            mock_state_repo,
            mock_processed_repo,
            AsyncMock(return_value=billing_stats),
        )
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 0
    assert result["sources_failed"] == 1
    assert result["sources_degraded"] == 1

    # Source paused for the billing backoff (rate_limit_until upserted).
    mock_state_repo.upsert_source.assert_awaited()

    mock_state_repo.record_attempt.assert_awaited()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["failed_stage"] == "process_billing_blocked"
    assert kwargs["error_class"] == "AnthropicBillingError"
    assert kwargs["details"]["outcome"] == "degraded"
