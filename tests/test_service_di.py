"""
Unit tests demonstrating Dependency Injection in service layer.

These tests inject mock repos directly into service functions,
proving that the DI parameters work without any real database.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.domain.models import (
    ProcessedDocument,
    RawTelegramMessage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_raw_message(channel_id: str = "test_channel", msg_id: str = "1") -> RawTelegramMessage:
    return RawTelegramMessage(
        id=msg_id,
        message_type="post",
        source_ref=f"tg:{channel_id}:post:{msg_id}",
        channel_id=channel_id,
        date=datetime(2025, 1, 1, tzinfo=UTC),
        text=f"Test message {msg_id}",
    )


def _make_processed_doc(channel_id: str = "test_channel", msg_id: str = "1") -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:tg:{channel_id}:post:{msg_id}",
        source_ref=f"tg:{channel_id}:post:{msg_id}",
        source_message_id=msg_id,
        channel_id=channel_id,
        processed_at=datetime(2025, 1, 2, tzinfo=UTC),
        text_clean=f"Clean text {msg_id}",
        summary=f"Summary {msg_id}",
        topics=["test_topic"],
        entities=[],
        language="ru",
        metadata={"pipeline_version": "test"},
    )


# ---------------------------------------------------------------------------
# D5-1: run_processing with DI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_processing_di_no_messages():
    """run_processing with injected repos — empty channel returns zeros.

    BUG-069 / B2: the normal path now loads via the bounded
    list_unprocessed_by_channel (NOT list_by_channel)."""
    raw_repo = AsyncMock()
    raw_repo.list_unprocessed_by_channel = AsyncMock(return_value=[])
    raw_repo.count_by_channel = AsyncMock(return_value=0)

    processed_repo = AsyncMock()
    failure_repo = AsyncMock()

    with patch(
        "tg_parser.services.processing_service.create_processing_pipeline"
    ) as mock_pipeline_factory:
        mock_pipeline = AsyncMock()
        mock_pipeline_factory.return_value = mock_pipeline
        mock_pipeline.llm_client = AsyncMock()

        from tg_parser.services.processing_service import run_processing

        result = await run_processing(
            channel_id="empty_channel",
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
        )

    assert result["total_count"] == 0
    assert result["processed_count"] == 0
    assert result["raw_total_count"] == 0
    raw_repo.list_unprocessed_by_channel.assert_awaited_once()
    # The legacy full-backlog load must NOT be used on the normal path.
    raw_repo.list_by_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_processing_di_with_messages():
    """run_processing with injected repos — processes messages via the bounded
    (BUG-069) load and reports the true raw_total_count."""
    msg = _make_raw_message()
    doc = _make_processed_doc()

    raw_repo = AsyncMock()
    raw_repo.list_unprocessed_by_channel = AsyncMock(return_value=[msg])
    raw_repo.count_by_channel = AsyncMock(return_value=42)

    processed_repo = AsyncMock()
    processed_repo.exists = AsyncMock(return_value=False)

    failure_repo = AsyncMock()
    failure_repo.list_failures = AsyncMock(return_value=[])

    with patch(
        "tg_parser.services.processing_service.create_processing_pipeline"
    ) as mock_pipeline_factory:
        mock_pipeline = AsyncMock()
        mock_pipeline.process_batch = AsyncMock(return_value=[doc])
        mock_pipeline.llm_client = AsyncMock()
        mock_pipeline._batch_cooldown_skipped = 0
        mock_pipeline_factory.return_value = mock_pipeline

        from tg_parser.config import settings
        from tg_parser.services.processing_service import run_processing

        result = await run_processing(
            channel_id="test_channel",
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
        )

    assert result["total_count"] == 1
    assert result["processed_count"] == 1
    # Coverage denominator is the true backlog, not the bounded window.
    assert result["raw_total_count"] == 42
    mock_pipeline.process_batch.assert_awaited_once()
    # Bounded load is capped at the per-tick batch size and (BUG-069 Option A)
    # carries the failure_cooldown_enabled gate so the repo can anti-join
    # in-cooldown failures and avoid the poison-pill starvation regression.
    raw_repo.list_unprocessed_by_channel.assert_awaited_once_with(
        "test_channel",
        limit=settings.processing_tick_batch_size,
        failure_cooldown_enabled=settings.failure_cooldown_enabled,
    )


@pytest.mark.asyncio
async def test_run_processing_force_uses_full_backlog_load():
    """BUG-069: force=True must keep the legacy full list_by_channel load so it
    can reprocess already-processed docs (the bounded NOT EXISTS load would
    wrongly exclude them)."""
    msg = _make_raw_message()
    doc = _make_processed_doc()

    raw_repo = AsyncMock()
    raw_repo.list_by_channel = AsyncMock(return_value=[msg])
    raw_repo.count_by_channel = AsyncMock(return_value=1)

    processed_repo = AsyncMock()
    failure_repo = AsyncMock()

    with patch(
        "tg_parser.services.processing_service.create_processing_pipeline"
    ) as mock_pipeline_factory:
        mock_pipeline = AsyncMock()
        mock_pipeline.process_batch = AsyncMock(return_value=[doc])
        mock_pipeline.llm_client = AsyncMock()
        mock_pipeline_factory.return_value = mock_pipeline

        from tg_parser.services.processing_service import run_processing

        result = await run_processing(
            channel_id="test_channel",
            force=True,
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
        )

    assert result["processed_count"] == 1
    raw_repo.list_by_channel.assert_awaited_once_with("test_channel")
    raw_repo.list_unprocessed_by_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_processing_retry_failed_unchanged_load():
    """BUG-069: retry_failed keeps its own (failed source_ref) load path — it
    must NOT switch to the bounded NOT EXISTS load."""
    msg = _make_raw_message()
    doc = _make_processed_doc()

    raw_repo = AsyncMock()
    raw_repo.get_by_source_ref = AsyncMock(return_value=msg)
    raw_repo.count_by_channel = AsyncMock(return_value=1)

    processed_repo = AsyncMock()
    processed_repo.exists = AsyncMock(return_value=False)

    failure_repo = AsyncMock()
    failure_repo.list_failures = AsyncMock(
        return_value=[{"source_ref": msg.source_ref}]
    )

    with patch(
        "tg_parser.services.processing_service.create_processing_pipeline"
    ) as mock_pipeline_factory:
        mock_pipeline = AsyncMock()
        mock_pipeline.process_batch = AsyncMock(return_value=[doc])
        mock_pipeline.llm_client = AsyncMock()
        mock_pipeline._batch_cooldown_skipped = 0
        mock_pipeline_factory.return_value = mock_pipeline

        from tg_parser.services.processing_service import run_processing

        result = await run_processing(
            channel_id="test_channel",
            retry_failed=True,
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
        )

    assert result["processed_count"] == 1
    raw_repo.get_by_source_ref.assert_awaited_once_with(msg.source_ref)
    raw_repo.list_unprocessed_by_channel.assert_not_awaited()
    raw_repo.list_by_channel.assert_not_awaited()


# ---------------------------------------------------------------------------
# D5-2: run_export with DI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_export_di_empty(tmp_path):
    """run_export with injected repos — no docs yields zero counts."""
    processed_repo = AsyncMock()
    processed_repo.list_all = AsyncMock(return_value=[])
    processed_repo.list_by_channel = AsyncMock(return_value=[])

    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()

    ingestion_repo = AsyncMock()
    ingestion_repo.get_channel_usernames = AsyncMock(return_value={})

    from tg_parser.services.export_service import run_export

    result = await run_export(
        output_dir=str(tmp_path),
        processed_repo=processed_repo,
        topic_card_repo=topic_card_repo,
        topic_bundle_repo=topic_bundle_repo,
        ingestion_repo=ingestion_repo,
    )

    assert result["kb_entries_count"] == 0
    assert result["topics_count"] == 0
    assert result["channels_count"] == 0


# ---------------------------------------------------------------------------
# D5-3: run_topicization with DI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_topicization_di_no_docs():
    """run_topicization with injected repos — empty channel returns zero topics."""
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=[])

    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel = AsyncMock(return_value=[])

    with (
        patch(
            "tg_parser.services.topicization_service.resolve_llm_config",
            return_value=("openai", "fake-key", "gpt-4o-mini"),
        ),
        patch(
            "tg_parser.services.topicization_service.create_llm_client",
        ) as mock_llm_factory,
    ):
        mock_llm = AsyncMock()
        mock_llm.close = AsyncMock()
        mock_llm_factory.return_value = mock_llm

        with patch(
            "tg_parser.services.topicization_service.TopicizationPipelineImpl",
        ) as MockPipeline:
            pipeline_instance = AsyncMock()
            pipeline_instance.topicize_channel = AsyncMock(return_value=[])
            # BUG-018 / BUG-023: ``run_topicization`` reads these as real
            # values (failed-batch ratio + quality-rejection breakdown),
            # so an AsyncMock placeholder for ``rejection_breakdown``
            # would explode in ``dict(pipeline.rejection_breakdown)``.
            pipeline_instance.total_batches = 0
            pipeline_instance.failed_batches = 0
            pipeline_instance.last_batch_error = None
            pipeline_instance.rejection_breakdown = {}
            MockPipeline.return_value = pipeline_instance

            from tg_parser.services.topicization_service import run_topicization

            result = await run_topicization(
                channel_id="test_channel",
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

    assert result["topics_count"] == 0
    assert result["bundles_count"] == 0
    assert result["total_documents"] == 0
