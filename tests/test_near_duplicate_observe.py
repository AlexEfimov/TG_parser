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
