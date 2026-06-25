"""F5-B Phase 0 — near-duplicate observation-only counter tests (ADR-0016).

Pure-mock unit tests for
:func:`tg_parser.services.near_duplicate_service.run_near_duplicate_check_for_channel`
and the :func:`tg_parser.api.metrics.record_near_duplicate_observed` helper.

Covers the two axes (intra / cross), threshold boundary, first-document and
no-sibling edges, graceful skip when an embedding is missing, the disabled
fast-path, and that the Prometheus counter/histogram series move. No Postgres
required — the embedding repo and source repo are in-memory fakes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from tg_parser.api.metrics import (
    NEAR_DUPLICATE_SIMILARITY,
    NEAR_DUPLICATES_DETECTED,
    record_near_duplicate_observed,
)
from tg_parser.config import settings
from tg_parser.services import near_duplicate_service
from tg_parser.services.near_duplicate_service import run_near_duplicate_check_for_channel
from tg_parser.storage.ports import DocumentEmbedding, SimilarityResult


def _counter_value(counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()


def _histogram_sum(histogram, **labels: str) -> float:
    return histogram.labels(**labels)._sum.get()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass
class _Source:
    channel_id: str
    status: str = "active"


class _FakeSourceRepo:
    def __init__(self, sources: list[_Source]) -> None:
        self._sources = sources

    async def list_sources(self, status: str | None = None, **_kw) -> list[_Source]:
        if status is None:
            return list(self._sources)
        return [s for s in self._sources if s.status == status]


class _FakeEmbeddingRepo:
    """In-memory embedding store keyed by source_ref → (embedding, channel_id)."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[list[float], str]] = {}

    def add(self, ref: str, embedding: list[float], channel_id: str) -> None:
        self.store[ref] = (embedding, channel_id)

    async def get_many_by_source_refs(self, refs: list[str]) -> dict[str, DocumentEmbedding]:
        out: dict[str, DocumentEmbedding] = {}
        for ref in refs:
            if ref in self.store:
                emb, cid = self.store[ref]
                out[ref] = DocumentEmbedding(
                    source_ref=ref,
                    embedding=list(emb),
                    model="fake",
                    created_at=datetime.now(UTC),
                    channel_ids=[cid],
                )
        return out

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        threshold: float = 0.0,
        entry_types: list[str] | None = None,
        channel_ids: list[str] | None = None,
    ) -> list[SimilarityResult]:
        rows: list[SimilarityResult] = []
        for ref, (emb, cid) in self.store.items():
            if channel_ids is not None and cid not in channel_ids:
                continue
            score = _cosine(query_embedding, emb)
            if score >= threshold:
                rows.append(SimilarityResult(source_ref=ref, score=score, entry_type="message"))
        rows.sort(key=lambda r: r.score, reverse=True)
        return rows[:limit]


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = (
        settings.near_dup_observe_enabled,
        settings.near_dup_similarity_threshold,
        settings.near_dup_window_n,
    )
    yield
    (
        settings.near_dup_observe_enabled,
        settings.near_dup_similarity_threshold,
        settings.near_dup_window_n,
    ) = saved


# ----------------------------------------------------------------------------
# metrics helper
# ----------------------------------------------------------------------------


def test_record_near_duplicate_observed_increments_counter_and_histogram() -> None:
    before = _counter_value(
        NEAR_DUPLICATES_DETECTED, channel_id="ch1", method="embedding_cosine", dimension="intra"
    )
    sum_before = _histogram_sum(NEAR_DUPLICATE_SIMILARITY, dimension="intra")
    record_near_duplicate_observed(channel_id="ch1", dimension="intra", similarity=0.95)
    after = _counter_value(
        NEAR_DUPLICATES_DETECTED, channel_id="ch1", method="embedding_cosine", dimension="intra"
    )
    sum_after = _histogram_sum(NEAR_DUPLICATE_SIMILARITY, dimension="intra")
    assert after == pytest.approx(before + 1.0)
    assert math.isclose(sum_after - sum_before, 0.95, abs_tol=1e-6)


def test_record_near_duplicate_observed_clamps_similarity() -> None:
    sum_before = _histogram_sum(NEAR_DUPLICATE_SIMILARITY, dimension="cross")
    record_near_duplicate_observed(channel_id="ch1", dimension="cross", similarity=1.7)
    record_near_duplicate_observed(channel_id="ch1", dimension="cross", similarity=-0.4)
    sum_after = _histogram_sum(NEAR_DUPLICATE_SIMILARITY, dimension="cross")
    # 1.7 -> 1.0, -0.4 -> 0.0 => total observed = 1.0
    assert math.isclose(sum_after - sum_before, 1.0, abs_tol=1e-6)


# ----------------------------------------------------------------------------
# happy paths
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intra_near_duplicate_detected() -> None:
    emb_repo = _FakeEmbeddingRepo()
    emb_repo.add("tg:ch1:post:1", [1.0, 0.0], "ch1")
    emb_repo.add("tg:ch1:post:2", [1.0, 0.0], "ch1")  # identical neighbour, same channel
    source_repo = _FakeSourceRepo([_Source("ch1")])

    before = _counter_value(
        NEAR_DUPLICATES_DETECTED, channel_id="ch1", method="embedding_cosine", dimension="intra"
    )
    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    after = _counter_value(
        NEAR_DUPLICATES_DETECTED, channel_id="ch1", method="embedding_cosine", dimension="intra"
    )

    assert result["checked"] == 1
    assert result["intra"] == 1
    assert result["cross"] == 0
    assert after == pytest.approx(before + 1.0)


@pytest.mark.asyncio
async def test_cross_near_duplicate_detected() -> None:
    emb_repo = _FakeEmbeddingRepo()
    emb_repo.add("tg:ch1:post:1", [1.0, 0.0], "ch1")
    emb_repo.add("tg:ch2:post:9", [1.0, 0.0], "ch2")  # identical neighbour, sibling channel
    source_repo = _FakeSourceRepo([_Source("ch1"), _Source("ch2")])

    before = _counter_value(
        NEAR_DUPLICATES_DETECTED, channel_id="ch1", method="embedding_cosine", dimension="cross"
    )
    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    after = _counter_value(
        NEAR_DUPLICATES_DETECTED, channel_id="ch1", method="embedding_cosine", dimension="cross"
    )

    assert result["checked"] == 1
    assert result["intra"] == 0  # no same-channel neighbour besides self
    assert result["cross"] == 1
    assert after == pytest.approx(before + 1.0)


# ----------------------------------------------------------------------------
# edges / negatives
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_is_excluded_first_document_no_neighbours() -> None:
    emb_repo = _FakeEmbeddingRepo()
    emb_repo.add("tg:ch1:post:1", [1.0, 0.0], "ch1")  # only itself in its channel
    source_repo = _FakeSourceRepo([_Source("ch1")])

    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    assert result == {"checked": 1, "intra": 0, "cross": 0, "skipped_no_embedding": 0}


@pytest.mark.asyncio
async def test_below_threshold_not_counted() -> None:
    emb_repo = _FakeEmbeddingRepo()
    emb_repo.add("tg:ch1:post:1", [1.0, 0.0], "ch1")
    emb_repo.add("tg:ch1:post:2", [0.0, 1.0], "ch1")  # orthogonal => cosine 0
    source_repo = _FakeSourceRepo([_Source("ch1")])

    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    assert result["intra"] == 0
    assert result["cross"] == 0


@pytest.mark.asyncio
async def test_no_sibling_channels_cross_is_noop() -> None:
    emb_repo = _FakeEmbeddingRepo()
    emb_repo.add("tg:ch1:post:1", [1.0, 0.0], "ch1")
    emb_repo.add("tg:ch1:post:2", [1.0, 0.0], "ch1")
    source_repo = _FakeSourceRepo([_Source("ch1")])  # only this channel, no siblings

    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    assert result["intra"] == 1
    assert result["cross"] == 0


@pytest.mark.asyncio
async def test_missing_embedding_is_skipped_gracefully() -> None:
    emb_repo = _FakeEmbeddingRepo()  # empty store — no embedding for the new doc
    source_repo = _FakeSourceRepo([_Source("ch1"), _Source("ch2")])

    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    assert result == {"checked": 0, "intra": 0, "cross": 0, "skipped_no_embedding": 1}


@pytest.mark.asyncio
async def test_disabled_flag_is_fast_noop() -> None:
    settings.near_dup_observe_enabled = False
    emb_repo = _FakeEmbeddingRepo()
    emb_repo.add("tg:ch1:post:1", [1.0, 0.0], "ch1")
    emb_repo.add("tg:ch1:post:2", [1.0, 0.0], "ch1")
    source_repo = _FakeSourceRepo([_Source("ch1")])

    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=["tg:ch1:post:1"],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    assert result == {"checked": 0, "intra": 0, "cross": 0, "skipped_no_embedding": 0}


@pytest.mark.asyncio
async def test_empty_new_doc_refs_is_noop() -> None:
    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=[],
        emb_repo=_FakeEmbeddingRepo(),
        source_repo=_FakeSourceRepo([]),
    )
    assert result == {"checked": 0, "intra": 0, "cross": 0, "skipped_no_embedding": 0}


@pytest.mark.asyncio
async def test_max_docs_per_tick_cap_applies(monkeypatch) -> None:
    monkeypatch.setattr(near_duplicate_service, "MAX_DOCS_PER_TICK", 2)
    emb_repo = _FakeEmbeddingRepo()
    for i in range(5):
        emb_repo.add(f"tg:ch1:post:{i}", [1.0, 0.0], "ch1")
    source_repo = _FakeSourceRepo([_Source("ch1")])

    result = await run_near_duplicate_check_for_channel(
        channel_id="ch1",
        new_doc_refs=[f"tg:ch1:post:{i}" for i in range(5)],
        emb_repo=emb_repo,
        source_repo=source_repo,
    )
    # only the first 2 refs are observed this tick
    assert result["checked"] == 2


# ----------------------------------------------------------------------------
# BUG-064 — scheduler wiring: message embeddings exist BEFORE the near-dup hook
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_embeds_messages_before_near_dup_check(monkeypatch) -> None:
    """BUG-064 regression: the scheduler must write per-doc MESSAGE embeddings
    BEFORE invoking the near-duplicate observer, otherwise every new doc is
    skipped (``skipped_no_embedding++``) and
    ``tg_dedup_near_duplicates_detected_total`` never moves (the 0-samples
    symptom seen since the 2026-06-19 deploy).

    Drives ``run_incremental_for_all_sources`` end-to-end with the heavy
    stages mocked. The embedding step (``run_incremental_embedding``) is
    replaced with a spy that mirrors its only observable side effect —
    message embeddings land in a shared in-memory store for the new doc refs.
    The near-dup hook runs FOR REAL against that same store via the
    ``emb_repo`` / ``source_repo`` injection seam, so the assertion
    (``checked == 2``, ``skipped_no_embedding == 0``) genuinely proves the
    embeddings were present at hook-call time. The recorded ``call_order``
    pins the ordering: embedding must precede the near-dup observation.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from tg_parser.domain.models import IncrementalTopicizeResult
    from tg_parser.services import scheduler_service
    from tg_parser.storage.ports import Source

    # Real near-dup observer must be enabled with a threshold the identical
    # vectors clear; restored by the autouse ``_restore_settings`` fixture.
    settings.near_dup_observe_enabled = True
    settings.near_dup_similarity_threshold = 0.8
    settings.near_dup_window_n = 5

    new_refs = ["tg:ch1:post:1", "tg:ch1:post:2"]

    # Shared MESSAGE-embedding store starts EMPTY — the pre-fix near-dup hook
    # would skip both docs. The real source repo gives the observer its
    # cross-axis window composition.
    emb_repo = _FakeEmbeddingRepo()
    source_repo = _FakeSourceRepo([_Source("ch1")])

    call_order: list[str] = []
    captured: dict[str, int] = {}

    async def _spy_run_incremental_embedding(doc_refs, **_kw):
        call_order.append("embedding")
        for ref in doc_refs:
            emb_repo.add(ref, [1.0, 0.0], "ch1")
        return {"embedded_count": len(doc_refs), "total_count": len(doc_refs)}

    real_near_dup = near_duplicate_service.run_near_duplicate_check_for_channel

    async def _wrapped_near_dup(*, channel_id, new_doc_refs, **_kw):
        call_order.append("near_dup")
        # Inject the shared store so the REAL observer reads exactly what the
        # embedding step just wrote (proves presence + ordering).
        summary = await real_near_dup(
            channel_id=channel_id,
            new_doc_refs=new_doc_refs,
            emb_repo=emb_repo,
            source_repo=source_repo,
        )
        captured.update(summary)
        return summary

    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    docs_after = [MagicMock(source_ref=ref) for ref in new_refs]
    mock_processed_repo.list_by_channel.side_effect = [[], docs_after]

    @asynccontextmanager
    async def _state_cm():
        yield mock_state_repo, MagicMock(close=AsyncMock())

    @asynccontextmanager
    async def _repos_cm():
        yield mock_state_repo, mock_processed_repo, MagicMock(close=AsyncMock())

    with (
        patch("tg_parser.services.scheduler_service.ingestion_state_repo", _state_cm),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _repos_cm,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 2, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 2,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 2,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 2, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=IncrementalTopicizeResult(
                assigned_keyword=[],
                unassignable=[],
                coverage_before=0.0,
                coverage_after=0.0,
            ),
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new_callable=AsyncMock,
            return_value={"embedded_count": 0, "skipped_count": 0, "total_count": 0},
        ),
        patch(
            "tg_parser.services.embedding_service.run_incremental_embedding",
            side_effect=_spy_run_incremental_embedding,
        ),
        patch.object(
            near_duplicate_service,
            "run_near_duplicate_check_for_channel",
            side_effect=_wrapped_near_dup,
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
            return_value={"inserted": 0, "skipped_reason": None},
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.processing_concurrency = 1

        result = await scheduler_service.run_incremental_for_all_sources()

    # Wiring: the embedding step ran before the near-dup observer.
    assert call_order == ["embedding", "near_dup"], (
        "BUG-064: run_incremental_embedding must be wired BEFORE the near-dup "
        f"hook in _process_source; got call_order={call_order}"
    )
    # And the observer saw real message embeddings — it checked both docs and
    # skipped NONE for a missing embedding (the pre-fix failure mode).
    assert captured["checked"] == 2
    assert captured["skipped_no_embedding"] == 0
    # The hook is post-processing and graceful, so the source still succeeds.
    assert result["sources_succeeded"] == 1


@pytest.mark.asyncio
async def test_scheduler_embedding_failure_is_isolated_from_stage_errors(monkeypatch) -> None:
    """post-processing-must-not-lie: a failure inside the wired incremental
    embedding step must be logged and swallowed — NOT appended to
    ``stage_errors`` — so the source attempt still reports success (mirrors the
    near-dup / F5-C / F11 graceful-degradation contract). A non-billing embed
    outage must never falsify ``success = not stage_errors`` for the upstream
    ingest/process/export stages.

    Also pins graceful degradation: the embed failure must NOT abort the rest
    of the ``if new_doc_refs:`` block — the near-dup observer is still invoked
    on the same tick.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from tg_parser.domain.models import IncrementalTopicizeResult
    from tg_parser.services import scheduler_service
    from tg_parser.storage.ports import Source

    new_refs = ["tg:ch1:post:1", "tg:ch1:post:2"]
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    docs_after = [MagicMock(source_ref=ref) for ref in new_refs]
    mock_processed_repo.list_by_channel.side_effect = [[], docs_after]

    async def _boom_embedding(doc_refs, **_kw):
        raise RuntimeError("embedding backend unavailable")

    @asynccontextmanager
    async def _state_cm():
        yield mock_state_repo, MagicMock(close=AsyncMock())

    @asynccontextmanager
    async def _repos_cm():
        yield mock_state_repo, mock_processed_repo, MagicMock(close=AsyncMock())

    with (
        patch("tg_parser.services.scheduler_service.ingestion_state_repo", _state_cm),
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _repos_cm,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 2, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 2,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 2,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 2, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=IncrementalTopicizeResult(
                assigned_keyword=[],
                unassignable=[],
                coverage_before=0.0,
                coverage_after=0.0,
            ),
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new_callable=AsyncMock,
            return_value={"embedded_count": 0, "skipped_count": 0, "total_count": 0},
        ),
        patch(
            "tg_parser.services.embedding_service.run_incremental_embedding",
            side_effect=_boom_embedding,
        ),
        patch.object(
            near_duplicate_service,
            "run_near_duplicate_check_for_channel",
            new_callable=AsyncMock,
            return_value={"checked": 0, "intra": 0, "cross": 0, "skipped_no_embedding": 2},
        ) as mock_near_dup,
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
            return_value={"inserted": 0, "skipped_reason": None},
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.processing_concurrency = 1

        result = await scheduler_service.run_incremental_for_all_sources()

    # The embed failure was swallowed: the source attempt is a SUCCESS and the
    # error is not surfaced as a stage failure.
    assert result["sources_succeeded"] == 1
    assert result["sources_failed"] == 0
    assert "s1" not in result["errors"]
    # Graceful degradation: the near-dup observer still ran this tick despite
    # the embed failure (the two hooks are independent try/except blocks).
    mock_near_dup.assert_awaited_once()
