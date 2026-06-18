"""
Channel service: aggregate channel statistics from multiple repos.

Used by Channels API (P6a) and MCP tools.
"""

import structlog
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.services.db_context import stats_repos

logger = structlog.get_logger(__name__)


def _compute_coverage(
    bundles: list,
    processed_refs: set[str],
    processed_count: int,
) -> tuple[int, float]:
    """Compute coverage metrics: (covered_documents, coverage_percent).

    Intersects bundle source_refs with processed_refs to avoid counting
    refs from other channels.
    """
    covered_refs: set[str] = set()
    for bundle in bundles:
        for item in bundle.items:
            covered_refs.add(item.source_ref)

    covered_documents = len(covered_refs & processed_refs)
    coverage_percent = (covered_documents / processed_count * 100) if processed_count else 0.0
    return covered_documents, coverage_percent


async def get_channel_stats(channel_id: str) -> dict:
    """
    Aggregate channel statistics across ingestion, processing, and embedding domains.

    Returns a dict matching ChannelStatsResponse fields.

    Raises ValueError if channel_id is not found in ingestion sources.
    """
    async with stats_repos() as (
        state_repo,
        raw_repo,
        proc_repo,
        topic_card_repo,
        topic_bundle_repo,
        emb_repo,
        _topic_link_repo,
        _db,
    ):
        source = await state_repo.get_source(channel_id)
        if source is None:
            raise ValueError(f"Channel not found: {channel_id}")

        channel_username = source.channel_username
        raw_count = await raw_repo.count_by_channel(channel_id)
        processed_count = await proc_repo.count_by_channel(channel_id)

        topic_cards = await topic_card_repo.list_by_channel(channel_id)
        topics_count = len(topic_cards)

        processed_refs = set(await proc_repo.list_source_refs_by_channel(channel_id))
        all_bundles = await topic_bundle_repo.list_by_channel(channel_id)
        covered_documents, coverage_percent = _compute_coverage(
            all_bundles,
            processed_refs,
            processed_count,
        )

        missing_refs = await emb_repo.list_missing(channel_id)
        missing_embeddings = len(missing_refs)
        embeddings_count = max(0, processed_count - missing_embeddings)

    return {
        "channel_id": channel_id,
        "channel_username": channel_username,
        "raw_messages": raw_count,
        "processed_documents": processed_count,
        "topics_count": topics_count,
        "covered_documents": covered_documents,
        "coverage_percent": round(coverage_percent, 2),
        "embeddings_count": embeddings_count,
        "missing_embeddings": missing_embeddings,
    }


def _zero_stats(src) -> dict:
    """Zero-filled stats row for a source (degraded fallback)."""
    return {
        "channel_id": src.channel_id,
        "channel_username": src.channel_username,
        "status": src.status,
        "raw_messages": 0,
        "processed_documents": 0,
        "topics_count": 0,
        "coverage_percent": 0.0,
    }


async def get_all_channel_stats(
    allowed_channel_ids: list[str] | None = None,
) -> list[dict]:
    """Collect stats for all channels with a bounded number of batched queries.

    BUG-008 H1: this used to be a serial per-channel fan-out — for every channel
    it ran ~6 awaited queries, two of which (``topic_card_repo.list_by_channel`` /
    ``topic_bundle_repo.list_by_channel``) did a leading-wildcard ``LIKE`` on an
    un-indexed ``Text`` JSON column (full sequential scan **per channel**), plus a
    ``list_source_refs_by_channel`` that loaded every source-ref onto the event loop
    for a CPU-bound set-intersection. Cost grew as O(channels × table sizes) and
    degraded silently as data grew.

    It is now a fixed handful of set-based aggregate queries computed once for ALL
    channels: grouped COUNTs for raw/processed/topics and a single set-based
    coverage aggregate (see the repo methods). The output is byte-for-byte identical
    to the old per-channel result for the same data (same counts and coverage
    semantics). The read sessions are additionally bounded server-side by a
    read-scoped ``statement_timeout`` (BUG-008 H2, see :func:`stats_repos`).

    Args:
        allowed_channel_ids: Tenant scoping — None=admin (all)
    """
    async with stats_repos() as (
        state_repo,
        raw_repo,
        proc_repo,
        topic_card_repo,
        _topic_bundle_repo,
        _emb_repo,
        _topic_link_repo,
        _db,
    ):
        sources = await state_repo.list_sources()
        if allowed_channel_ids is not None:
            allowed = set(allowed_channel_ids)
            sources = [s for s in sources if s.channel_id in allowed]
        if not sources:
            return []

        try:
            raw_counts = await raw_repo.count_all_grouped_by_channel()
            processed_counts = await proc_repo.count_all_grouped_by_channel()
            topics_counts = await topic_card_repo.count_by_channel_grouped()
            coverage_counts = await proc_repo.coverage_counts_by_channel()
        except (SQLAlchemyError, RuntimeError):
            # Preserve the old "endpoint always returns one row per channel"
            # contract: degrade to zero-filled stats instead of failing the
            # whole list_channels call.
            logger.exception("Batched channel stats aggregation failed")
            return [_zero_stats(src) for src in sources]

        results: list[dict] = []
        for src in sources:
            cid = src.channel_id
            processed_count = processed_counts.get(cid, 0)
            covered = coverage_counts.get(cid, 0)
            coverage_percent = (covered / processed_count * 100) if processed_count else 0.0
            results.append(
                {
                    "channel_id": cid,
                    "channel_username": src.channel_username,
                    "status": src.status,
                    "raw_messages": raw_counts.get(cid, 0),
                    "processed_documents": processed_count,
                    "topics_count": topics_counts.get(cid, 0),
                    "coverage_percent": round(coverage_percent, 2),
                }
            )

        return results
