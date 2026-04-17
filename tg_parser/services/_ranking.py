"""
Ranking fusion utilities for hybrid retrieval (F5-A Phase 1).

Reciprocal Rank Fusion (RRF) combines multiple ranked result lists
(e.g. semantic pgvector + keyword FTS) into a single ranked list
without requiring score normalization across heterogeneous metrics.

Reference:
    Cormack, G.V., Clarke, C.L.A., Buettcher, S.
    "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"
    SIGIR 2009.
"""

from collections.abc import Sequence

from tg_parser.storage.ports import SimilarityResult


def rrf_fuse(
    *lists: Sequence[SimilarityResult],
    k: int = 60,
) -> list[SimilarityResult]:
    """Fuse several ranked result lists via Reciprocal Rank Fusion.

    For each list the rank is 1-indexed in the order received (lists are
    assumed to be pre-sorted by their native relevance metric). Each
    document contributes ``1 / (k + rank)`` to its RRF score; duplicates
    across lists sum their contributions.

    Args:
        *lists: Variadic sequences of ``SimilarityResult``. Each list must
            already be sorted (most relevant first). Empty lists are
            tolerated and contribute nothing.
        k: RRF constant. Larger k compresses the influence of high-rank
            items; the canonical default is 60.

    Returns:
        Fused ``list[SimilarityResult]`` sorted by RRF score descending.
        The ``score`` field is replaced with the RRF score (not the
        original cosine / ts_rank). ``entry_type`` and ``topic_id`` come
        from the first occurrence of each ``source_ref`` across input
        lists (earlier lists win).
    """
    if k < 1:
        raise ValueError("k must be >= 1")

    accumulated: dict[str, float] = {}
    first_seen: dict[str, SimilarityResult] = {}
    insertion_order: dict[str, int] = {}

    for result_list in lists:
        for rank, item in enumerate(result_list, start=1):
            contribution = 1.0 / (k + rank)
            if item.source_ref in accumulated:
                accumulated[item.source_ref] += contribution
            else:
                accumulated[item.source_ref] = contribution
                first_seen[item.source_ref] = item
                insertion_order[item.source_ref] = len(insertion_order)

    fused = [
        SimilarityResult(
            source_ref=ref,
            score=accumulated[ref],
            entry_type=first_seen[ref].entry_type,
            topic_id=first_seen[ref].topic_id,
        )
        for ref in insertion_order
    ]

    fused.sort(key=lambda r: (-r.score, insertion_order[r.source_ref]))
    return fused
