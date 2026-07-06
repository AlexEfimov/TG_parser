"""BUG-079: the topicization batch-fanout knobs must reach the pipeline.

The network-stall hardening tuned ``TOPICIZATION_BATCH_CONCURRENCY`` (5→2) and
``TOPICIZATION_BATCH_SIZE`` (50→25) to reduce simultaneous / oversized Anthropic
LLM batches on the FULL topicization path. These tests guard the wiring so the
tuned settings actually reach ``TopicizationPipelineImpl`` instead of silently
falling back to the constructor defaults (the class ran ``self.batch_concurrency``
= 5 and a hard-coded ``BATCH_SIZE = 50`` before this fix).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import tg_parser.services.topicization_service as topic_service
from tg_parser.config import settings as app_settings
from tg_parser.processing.topicization import TopicizationPipelineImpl


def test_pipeline_stores_batch_concurrency_and_size():
    """Constructor threads both knobs onto the instance used by the full path."""
    pipe = TopicizationPipelineImpl(
        llm_client=MagicMock(),
        processed_doc_repo=MagicMock(),
        topic_card_repo=MagicMock(),
        topic_bundle_repo=MagicMock(),
        batch_concurrency=2,
        batch_size=25,
    )
    assert pipe.batch_concurrency == 2
    assert pipe.batch_size == 25


def test_pipeline_defaults_unchanged():
    """BUG-079 must NOT change the historical constructor defaults (5 / 50)."""
    pipe = TopicizationPipelineImpl(
        llm_client=MagicMock(),
        processed_doc_repo=MagicMock(),
        topic_card_repo=MagicMock(),
        topic_bundle_repo=MagicMock(),
    )
    assert pipe.batch_concurrency == 5
    assert pipe.batch_size == 50


@pytest.mark.asyncio
async def test_full_topicization_path_threads_settings(monkeypatch):
    """``run_topicization`` (full path) builds the pipeline from settings.

    Proves ``settings.topicization_batch_concurrency`` /
    ``topicization_batch_size`` reach the constructor on the production
    construction path implicated by BUG-079 — not the constructor defaults.
    """

    class _StopAfterConstruction(Exception):
        pass

    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        raise _StopAfterConstruction()

    monkeypatch.setattr(topic_service, "TopicizationPipelineImpl", _capture)
    monkeypatch.setattr(
        topic_service, "resolve_llm_config", lambda stage: ("anthropic", "key", "model")
    )
    monkeypatch.setattr(topic_service, "create_llm_client", lambda **kw: AsyncMock())

    # Tuned prod values (differ from the 5 / 50 constructor defaults).
    monkeypatch.setattr(app_settings, "topicization_batch_concurrency", 2)
    monkeypatch.setattr(app_settings, "topicization_batch_size", 25)

    with pytest.raises(_StopAfterConstruction):
        await topic_service._topicize_channel_locked(
            channel_id="chan",
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
            failure_repo=AsyncMock(),
        )

    assert captured["batch_concurrency"] == 2
    assert captured["batch_size"] == 25
