"""BUG-074 (F2): topicization JSON-parse retries must apply ``repair_json``.

Before this fix, the three large-prompt topicization stages
(``_generate_topics_batch``, ``_merge_topics``, ``_discover_single_batch``)
looped up to ``max_json_retries = 3`` RE-ISSUING the entire oversized prompt on
an HTTP-200 invalid-JSON reply (the BUG-065 class: unescaped inner quotes /
trailing commas) and never called the cheap deterministic ``repair_json`` the
per-message path already uses. F2 applies ``repair_json`` at all three parse
sites BEFORE the attempt is counted failed (recovering on the FIRST attempt) and
lowers the retry cap to ``_TOPICIZATION_MAX_JSON_RETRIES = 2``.

Crucially: the truncation path (``stop_reason == "max_tokens"``, BUG-071) is
UNAFFECTED — F2 is strictly the non-truncated invalid-JSON path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.domain.models import ProcessedDocument
from tg_parser.processing.ports import LLMResponse
from tg_parser.processing.topicization import (
    _TOPICIZATION_MAX_JSON_RETRIES,
    TopicizationBatchTruncatedError,
    TopicizationPipelineImpl,
)


def _resp(text: str, stop_reason: str | None = None) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=10, output_tokens=10, stop_reason=stop_reason)


def _make_doc(source_ref: str, channel_id: str = "labdiagnostica") -> ProcessedDocument:
    parts = source_ref.split(":")
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=parts[-1],
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean="some text content",
        summary="summary",
        topics=[],
    )


def _make_pipeline(generate_side_effect) -> TopicizationPipelineImpl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    llm.generate_with_usage = AsyncMock(side_effect=generate_side_effect)
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []
    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=topic_card_repo,
        topic_bundle_repo=AsyncMock(),
    )


# A reply that ``json.loads`` rejects (trailing comma) but ``repair_json`` fixes
# deterministically via ``_strip_trailing_commas``.
def _repairable_topics_json() -> str:
    return (
        '{"topics": [{"type": "cluster", "title": "T", "summary": "s", '
        '"scope_in": ["a"], "scope_out": ["b"], '
        '"anchors": [{"source_ref": "tg:labdiagnostica:post:1", "score": 0.9},]},]}'
    )


# A genuinely unrepairable reply (structurally broken; repair passes leave it
# still invalid).
_UNREPAIRABLE = '{"topics": [ {"title": '


# ===========================================================================
# _generate_topics_batch
# ===========================================================================


@pytest.mark.asyncio
async def test_generate_batch_repairs_on_first_attempt():
    """A trailing-comma reply is repaired + parsed on the FIRST attempt — the
    oversized prompt is NOT re-issued."""
    calls = 0

    async def side_effect(**_kwargs):
        nonlocal calls
        calls += 1
        return _resp(_repairable_topics_json())

    pipeline = _make_pipeline(side_effect)
    candidates = [
        {"source_ref": "tg:labdiagnostica:post:1", "text_clean": "x", "summary": "", "topics": []}
    ]
    topics = await pipeline._generate_topics_batch(candidates)

    assert calls == 1  # repaired in place, no re-issue
    assert len(topics) == 1
    assert topics[0]["title"] == "T"


@pytest.mark.asyncio
async def test_generate_batch_unrepairable_fails_after_reduced_cap():
    """A genuinely unrepairable reply still fails gracefully after the REDUCED
    retry cap (2), not the old 3."""
    calls = 0

    async def side_effect(**_kwargs):
        nonlocal calls
        calls += 1
        return _resp(_UNREPAIRABLE)

    pipeline = _make_pipeline(side_effect)
    candidates = [
        {"source_ref": "tg:labdiagnostica:post:1", "text_clean": "x", "summary": "", "topics": []}
    ]
    with pytest.raises(RuntimeError, match="JSON parse failed"):
        await pipeline._generate_topics_batch(candidates)

    assert calls == _TOPICIZATION_MAX_JSON_RETRIES == 2


@pytest.mark.asyncio
async def test_generate_batch_truncation_path_unaffected_by_repair():
    """A ``max_tokens`` truncation still routes to the BUG-071 shrink/scale path
    (NOT the repair path): a single un-splittable candidate scales to the cap
    then drops as a failed batch — proving F2 did not change truncation."""
    async def side_effect(**_kwargs):
        # Always truncate, regardless of (growing) max_tokens.
        return _resp("{partial truncated", stop_reason="max_tokens")

    pipeline = _make_pipeline(side_effect)
    candidates = [
        {"source_ref": "tg:labdiagnostica:post:1", "text_clean": "x", "summary": "", "topics": []}
    ]
    with pytest.raises(TopicizationBatchTruncatedError):
        await pipeline._generate_topics_batch(candidates)


# ===========================================================================
# _merge_topics
# ===========================================================================


@pytest.mark.asyncio
async def test_merge_repairs_on_first_attempt():
    """The merge stage repairs a trailing-comma ``groups`` reply on the first
    attempt instead of re-issuing the merge prompt."""
    calls = 0

    async def side_effect(**_kwargs):
        nonlocal calls
        calls += 1
        return _resp('{"groups": [[0], [1],]}')

    pipeline = _make_pipeline(side_effect)
    all_batch_topics = [
        {"title": "A", "summary": "a", "scope_in": [], "scope_out": [], "anchors": []},
        {"title": "B", "summary": "b", "scope_in": [], "scope_out": [], "anchors": []},
    ]
    merged = await pipeline._merge_topics(all_batch_topics, candidates=[])

    assert calls == 1
    # Two singleton groups → two merged topics.
    assert len(merged) == 2


# ===========================================================================
# _discover_single_batch
# ===========================================================================


@pytest.mark.asyncio
async def test_discover_repairs_on_first_attempt():
    """Phase-2 discover repairs a trailing-comma reply on the first attempt."""
    calls = 0

    async def side_effect(**_kwargs):
        nonlocal calls
        calls += 1
        return _resp('{"assignments": [], "new_topics": [], "unassignable": [],}')

    pipeline = _make_pipeline(side_effect)
    batch_docs = [_make_doc("tg:labdiagnostica:post:1")]
    assignments, new_cards, unassignable, tokens = await pipeline._discover_single_batch(
        "labdiagnostica",
        batch_docs,
        existing_topics=[],
        existing_topic_ids=set(),
    )

    assert calls == 1
    assert assignments == []
    assert new_cards == []
    assert tokens > 0


@pytest.mark.asyncio
async def test_discover_unrepairable_marks_unassignable_after_reduced_cap():
    """A genuinely unrepairable discover reply marks the batch docs unassignable
    after the reduced retry cap (2), without re-issuing 3x."""
    calls = 0

    async def side_effect(**_kwargs):
        nonlocal calls
        calls += 1
        return _resp(_UNREPAIRABLE)

    pipeline = _make_pipeline(side_effect)
    batch_docs = [_make_doc("tg:labdiagnostica:post:1")]
    assignments, new_cards, unassignable, _tokens = await pipeline._discover_single_batch(
        "labdiagnostica",
        batch_docs,
        existing_topics=[],
        existing_topic_ids=set(),
    )

    assert calls == _TOPICIZATION_MAX_JSON_RETRIES == 2
    assert assignments == []
    assert new_cards == []
    assert unassignable == ["tg:labdiagnostica:post:1"]


def test_repairable_fixture_is_actually_invalid_then_valid():
    """Guard: the 'repairable' fixture really is invalid JSON until repaired (so
    the tests above exercise the repair path, not a happy-path parse)."""
    from tg_parser.processing.pipeline import repair_json

    raw = _repairable_topics_json()
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    json.loads(repair_json(raw))  # repaired parses cleanly
