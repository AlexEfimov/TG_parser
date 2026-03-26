"""
Channel service: aggregate channel statistics from multiple repos.

Used by Channels API (P6a) and future MCP tools.
"""

import structlog

from tg_parser.services.db_context import (
    embedding_repos,
    ingestion_repos,
    processing_repos,
)

logger = structlog.get_logger(__name__)


async def get_channel_stats(channel_id: str) -> dict:
    """
    Aggregate channel statistics across ingestion, processing, and embedding domains.

    Returns a dict matching ChannelStatsResponse fields.

    Raises ValueError if channel_id is not found in ingestion sources.
    """
    async with ingestion_repos() as (state_repo, raw_repo, _db1):
        source = await state_repo.get_source(channel_id)
        if source is None:
            raise ValueError(f"Channel not found: {channel_id}")

        channel_username = source.channel_username
        raw_messages = await raw_repo.list_by_channel(channel_id)
        raw_count = len(raw_messages)

    async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db2):
        processed_docs = await proc_repo.list_by_channel(channel_id)
        processed_count = len(processed_docs)

        topic_cards = await topic_card_repo.list_by_channel(channel_id)
        topics_count = len(topic_cards)

        processed_refs = {d.source_ref for d in processed_docs}

        covered_refs: set[str] = set()
        for card in topic_cards:
            bundle = await topic_bundle_repo.get_by_topic_id(card.id)
            if bundle:
                for item in bundle.items:
                    covered_refs.add(item.source_ref)

        covered_documents = len(covered_refs & processed_refs)
        coverage_percent = (covered_documents / processed_count * 100) if processed_count else 0.0

    async with embedding_repos() as (emb_repo, _proc_repo2, _db3):
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
