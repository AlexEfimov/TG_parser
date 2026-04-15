"""
Cross-channel analytics service (Cross-dev 2).

Provides aggregated analytics across channels: topic counts, coverage,
keyword overlaps, and per-channel detail.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

from tg_parser.domain.models import TopicCard, TopicType
from tg_parser.services.db_context import stats_repos

logger = structlog.get_logger(__name__)


@dataclass
class ChannelStats:
    channel_id: str
    processed_documents: int = 0
    singleton_count: int = 0
    cluster_count: int = 0
    coverage_percent: float = 0.0
    keywords: set[str] = field(default_factory=set)


@dataclass
class KeywordOverlap:
    keyword: str
    channels: list[str]


@dataclass
class CrossChannelAnalytics:
    """Aggregated result for get_cross_channel_stats."""
    channels: list[dict[str, Any]]
    keyword_overlaps: list[dict[str, Any]]
    total_documents: int = 0
    total_topics: int = 0


def _extract_keywords(card: TopicCard) -> set[str]:
    """Extract keyword tokens from a TopicCard (tags + scope_in words)."""
    kws: set[str] = set()
    if card.tags:
        for tag in card.tags:
            kws.add(tag.lower().strip())
    for scope_item in card.scope_in:
        for word in scope_item.lower().split():
            cleaned = word.strip(".,;:!?()[]\"'")
            if len(cleaned) >= 3:
                kws.add(cleaned)
    return kws


def _get_channel_for_card(card: TopicCard) -> str | None:
    """Derive channel_id from TopicCard.sources."""
    if card.sources:
        return card.sources[0]
    return None


async def get_cross_channel_analytics(
    channel_id: str | None = None,
    allowed_channel_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Compute cross-channel analytics.

    Args:
        channel_id: If set, return detailed stats for a single channel
                    plus related channels by keyword overlap.
                    If None, return aggregated stats for all channels.
        allowed_channel_ids: Tenant scoping — None=admin (all)

    Returns:
        Dict with channel stats, keyword overlaps, and totals.
    """
    async with stats_repos() as (
        state_repo, raw_repo, proc_repo,
        topic_card_repo, topic_bundle_repo, emb_repo, _db,
    ):
        all_cards = await topic_card_repo.list_all()
        all_bundles = await topic_bundle_repo.list_all()
        sources = await state_repo.list_sources()

        if allowed_channel_ids is not None:
            sources = [s for s in sources if s.channel_id in allowed_channel_ids]
            allowed_set = set(allowed_channel_ids)
            all_cards = [c for c in all_cards if any(s in allowed_set for s in c.sources)]

        source_map = {s.channel_id: s for s in sources}

        channel_stats: dict[str, ChannelStats] = {}

        for src in sources:
            cid = src.channel_id
            proc_count = await proc_repo.count_by_channel(cid)
            proc_refs = set(await proc_repo.list_source_refs_by_channel(cid))
            bundles_for_channel = [
                b for b in all_bundles
                if any(item.source_ref.startswith(f"tg:{cid}:") for item in b.items[:1])
                or (b.channels and cid in b.channels)
            ]
            # More reliable: filter bundles by checking card sources
            ch_bundle_topic_ids = {
                c.id for c in all_cards if cid in c.sources
            }
            bundles_for_channel = [
                b for b in all_bundles if b.topic_id in ch_bundle_topic_ids
            ]

            covered_refs: set[str] = set()
            for bundle in bundles_for_channel:
                for item in bundle.items:
                    covered_refs.add(item.source_ref)
            covered_count = len(covered_refs & proc_refs)
            coverage = (covered_count / proc_count * 100) if proc_count else 0.0

            channel_stats[cid] = ChannelStats(
                channel_id=cid,
                processed_documents=proc_count,
                coverage_percent=round(coverage, 1),
            )

        for card in all_cards:
            ch = _get_channel_for_card(card)
            if not ch or ch not in channel_stats:
                continue
            cs = channel_stats[ch]
            if card.type == TopicType.SINGLETON:
                cs.singleton_count += 1
            else:
                cs.cluster_count += 1
            cs.keywords |= _extract_keywords(card)

        # Build keyword → channels mapping
        keyword_channels: dict[str, set[str]] = defaultdict(set)
        for cid, cs in channel_stats.items():
            for kw in cs.keywords:
                keyword_channels[kw].add(cid)

        # Find overlapping keywords (present in 2+ channels)
        overlaps = [
            KeywordOverlap(keyword=kw, channels=sorted(chs))
            for kw, chs in sorted(keyword_channels.items())
            if len(chs) >= 2
        ]

        total_docs = sum(cs.processed_documents for cs in channel_stats.values())
        total_topics = sum(
            cs.singleton_count + cs.cluster_count for cs in channel_stats.values()
        )

    if channel_id:
        return _build_single_channel_response(
            channel_id, channel_stats, overlaps, total_docs, total_topics,
        )

    return _build_global_response(channel_stats, overlaps, total_docs, total_topics)


def _build_global_response(
    channel_stats: dict[str, ChannelStats],
    overlaps: list[KeywordOverlap],
    total_docs: int,
    total_topics: int,
) -> dict[str, Any]:
    """Build response for cross-channel (no channel_id) mode."""
    channels_out = []
    for cid, cs in sorted(channel_stats.items()):
        top_keywords = sorted(cs.keywords)[:10]
        channels_out.append({
            "channel_id": cid,
            "processed_documents": cs.processed_documents,
            "singleton_count": cs.singleton_count,
            "cluster_count": cs.cluster_count,
            "topics_count": cs.singleton_count + cs.cluster_count,
            "coverage_percent": cs.coverage_percent,
            "top_keywords": top_keywords,
        })

    overlap_out = [
        {"keyword": o.keyword, "channels": o.channels}
        for o in overlaps[:50]
    ]

    return {
        "total_documents": total_docs,
        "total_topics": total_topics,
        "channels": channels_out,
        "keyword_overlaps": overlap_out,
        "overlap_count": len(overlaps),
    }


def _build_single_channel_response(
    channel_id: str,
    channel_stats: dict[str, ChannelStats],
    overlaps: list[KeywordOverlap],
    total_docs: int,
    total_topics: int,
) -> dict[str, Any]:
    """Build response for single-channel (with channel_id) mode."""
    cs = channel_stats.get(channel_id)
    if cs is None:
        return {"error": f"Channel not found: {channel_id}"}

    all_keywords = sorted(cs.keywords)

    related_channels: dict[str, int] = defaultdict(int)
    channel_overlaps = []
    for o in overlaps:
        if channel_id in o.channels:
            channel_overlaps.append({"keyword": o.keyword, "channels": o.channels})
            for ch in o.channels:
                if ch != channel_id:
                    related_channels[ch] += 1

    related_sorted = sorted(
        related_channels.items(), key=lambda x: x[1], reverse=True,
    )

    return {
        "channel_id": channel_id,
        "processed_documents": cs.processed_documents,
        "singleton_count": cs.singleton_count,
        "cluster_count": cs.cluster_count,
        "topics_count": cs.singleton_count + cs.cluster_count,
        "coverage_percent": cs.coverage_percent,
        "all_keywords": all_keywords,
        "keyword_overlaps": channel_overlaps[:50],
        "related_channels": [
            {"channel_id": ch, "shared_keywords": count}
            for ch, count in related_sorted
        ],
    }
