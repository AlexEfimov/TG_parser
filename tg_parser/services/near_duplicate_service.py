"""F5-B Phase 0 — near-duplicate observation-only counter (ADR-0016).

Post-processing hook that runs in the incremental scheduler tick after the
embedding-write path, alongside the F5-C re-summarize and F11 watchlist hooks.
For each newly-processed ``ProcessedDocument`` that already has an embedding it
measures the maximum cosine similarity (pgvector ``<=>``) against a sliding
window of recent embeddings on **two axes**:

* ``intra`` — other documents of the *same* channel.
* ``cross`` — documents of *sibling* channels. Phase 0 window composition is
  "all other active sources in this deployment" (the snapshot is a cluster of
  mono-thematic channels, so this captures cross-channel re-posts). The exact
  axis / window is refined in Phase 1 from the observed distribution.

When the max similarity on an axis is >= the observe threshold it increments
``tg_dedup_near_duplicates_detected_total{channel_id, method, dimension}`` plus
a similarity histogram and emits a ``near_duplicate_observed`` structlog event
carrying *both* ``source_ref`` values, the similarity and the ``dimension``.

OBSERVATION-ONLY (ADR-0016 Phase 0): nothing is hidden, mutated or deleted on
either axis. Graceful (ADR-0006 #7): a document without an embedding is skipped
silently; an embedding/repo failure is logged and never blocks ingestion.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import structlog

from tg_parser.api.metrics import record_near_duplicate_observed
from tg_parser.config import settings
from tg_parser.services.db_context import near_duplicate_repos

if TYPE_CHECKING:
    from tg_parser.storage.ports import EmbeddingRepo, IngestionStateRepo

logger = structlog.get_logger(__name__)

#: Hard cap on documents observed per tick — protects the scheduler from a
#: back-filled channel producing thousands of ``new_doc_refs`` at once. Mirrors
#: the watchlist ``MAX_DOCS_PER_TICK`` contract.
MAX_DOCS_PER_TICK: int = 100


async def _max_neighbor(
    emb_repo: EmbeddingRepo,
    query_embedding: list[float],
    *,
    exclude_ref: str,
    threshold: float,
    limit: int,
    channel_ids: list[str],
) -> tuple[str, float] | None:
    """Return the highest-similarity neighbour (ref, score) at/above ``threshold``.

    ``similarity_search`` already filters by ``threshold`` and returns rows
    ordered by descending similarity, so the first non-self result is the max.
    The document's own embedding (``exclude_ref``) is skipped so a document is
    never reported as a duplicate of itself.
    """
    if not channel_ids:
        return None
    results = await emb_repo.similarity_search(
        query_embedding=query_embedding,
        limit=limit,
        threshold=threshold,
        entry_types=["message"],
        channel_ids=channel_ids,
    )
    for r in results:
        if r.source_ref == exclude_ref:
            continue
        return (r.source_ref, float(r.score))
    return None


async def run_near_duplicate_check_for_channel(
    *,
    channel_id: str,
    new_doc_refs: list[str],
    emb_repo: EmbeddingRepo | None = None,
    source_repo: IngestionStateRepo | None = None,
) -> dict[str, int]:
    """Observe near-duplicates for ``new_doc_refs`` on the intra + cross axes.

    Returns a small status dict for structured logging::

        {"checked": int, "intra": int, "cross": int, "skipped_no_embedding": int}

    Disabled (``near_dup_observe_enabled=False``) or an empty ``new_doc_refs``
    is a fast no-op. Repos are opened lazily via :func:`near_duplicate_repos`
    when not injected (test seam).
    """
    if not settings.near_dup_observe_enabled or not new_doc_refs:
        return {"checked": 0, "intra": 0, "cross": 0, "skipped_no_embedding": 0}

    threshold = settings.near_dup_similarity_threshold
    window_n = settings.near_dup_window_n
    refs = new_doc_refs[:MAX_DOCS_PER_TICK]

    async with contextlib.AsyncExitStack() as stack:
        if emb_repo is None or source_repo is None:
            emb_repo, source_repo, _db = await stack.enter_async_context(near_duplicate_repos())

        # Cross-axis window composition: all other active sources (Phase 0).
        sources = await source_repo.list_sources(status="active")
        sibling_channels = sorted(
            {s.channel_id for s in sources if s.channel_id and s.channel_id != channel_id}
        )

        embeddings = await emb_repo.get_many_by_source_refs(refs)

        checked = 0
        intra_hits = 0
        cross_hits = 0
        skipped = 0

        for ref in refs:
            doc_emb = embeddings.get(ref)
            if doc_emb is None or not doc_emb.embedding:
                skipped += 1
                continue
            checked += 1

            # intra axis — window_n + 1 so the self-row never crowds out a
            # genuine neighbour before it is excluded.
            intra = await _max_neighbor(
                emb_repo,
                doc_emb.embedding,
                exclude_ref=ref,
                threshold=threshold,
                limit=window_n + 1,
                channel_ids=[channel_id],
            )
            if intra is not None:
                intra_hits += 1
                record_near_duplicate_observed(
                    channel_id=channel_id, dimension="intra", similarity=intra[1]
                )
                logger.info(
                    "near_duplicate_observed",
                    channel_id=channel_id,
                    dimension="intra",
                    method="embedding_cosine",
                    source_ref=ref,
                    neighbor_ref=intra[0],
                    similarity=round(intra[1], 4),
                )

            # cross axis — siblings only; self is in a different channel so it
            # never appears, but exclude_ref keeps the guard symmetric.
            cross = await _max_neighbor(
                emb_repo,
                doc_emb.embedding,
                exclude_ref=ref,
                threshold=threshold,
                limit=window_n,
                channel_ids=sibling_channels,
            )
            if cross is not None:
                cross_hits += 1
                record_near_duplicate_observed(
                    channel_id=channel_id, dimension="cross", similarity=cross[1]
                )
                logger.info(
                    "near_duplicate_observed",
                    channel_id=channel_id,
                    dimension="cross",
                    method="embedding_cosine",
                    source_ref=ref,
                    neighbor_ref=cross[0],
                    similarity=round(cross[1], 4),
                )

        return {
            "checked": checked,
            "intra": intra_hits,
            "cross": cross_hits,
            "skipped_no_embedding": skipped,
        }
