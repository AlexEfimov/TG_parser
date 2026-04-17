"""
Cross-channel topic linking service (Cross-dev 3).

Links topics from different channels by semantic similarity using:
1. Jaccard similarity on keywords (tags + scope_in tokens)
2. Cosine similarity on topic summary embeddings

Topics with combined score > threshold are linked in the topic_links table.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from tg_parser.domain.models import TopicCard, TopicLink
from tg_parser.services.analytics_service import _extract_keywords
from tg_parser.services.db_context import topic_linking_repos

logger = structlog.get_logger(__name__)

SIMILARITY_THRESHOLD = 0.3
JACCARD_WEIGHT = 0.4
COSINE_WEIGHT = 0.6


@dataclass
class LinkingResult:
    total_pairs_evaluated: int = 0
    links_created: int = 0
    links_above_threshold: int = 0
    avg_similarity: float = 0.0


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> tuple[float, list[str]]:
    """Compute Jaccard similarity and return shared items."""
    if not set_a or not set_b:
        return 0.0, []
    intersection = set_a & set_b
    union = set_a | set_b
    score = len(intersection) / len(union)
    return score, sorted(intersection)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_channel(card: TopicCard) -> str | None:
    return card.sources[0] if card.sources else None


async def link_topics(
    threshold: float = SIMILARITY_THRESHOLD,
) -> LinkingResult:
    """Build cross-channel topic links.

    For each pair of topics from different channels, compute combined
    Jaccard (keywords) + cosine (embedding) similarity. Links with
    score > threshold are saved to the topic_links table.

    Returns:
        LinkingResult with stats about the linking process.
    """
    async with topic_linking_repos() as (
        topic_card_repo, _bundle_repo, topic_link_repo, embedding_repo, _db,
    ):
        all_cards = await topic_card_repo.list_all()

        # Group by channel
        channel_cards: dict[str, list[TopicCard]] = defaultdict(list)
        for card in all_cards:
            ch = _get_channel(card)
            if ch:
                channel_cards[ch].append(card)

        channels = sorted(channel_cards.keys())
        if len(channels) < 2:
            logger.info("Less than 2 channels, nothing to link")
            return LinkingResult()

        # Pre-compute keywords for all cards
        card_keywords: dict[str, set[str]] = {}
        for card in all_cards:
            card_keywords[card.id] = _extract_keywords(card)

        # Load embeddings for topic summaries (use first anchor's source_ref)
        card_embeddings: dict[str, list[float]] = {}
        for card in all_cards:
            if card.anchors:
                emb = await embedding_repo.get_by_source_ref(card.anchors[0].anchor_ref)
                if emb:
                    card_embeddings[card.id] = emb.embedding

        # Compare topics across channel pairs
        links: list[TopicLink] = []
        total_pairs = 0
        total_score = 0.0

        for i, ch_a in enumerate(channels):
            for ch_b in channels[i + 1:]:
                for card_a in channel_cards[ch_a]:
                    for card_b in channel_cards[ch_b]:
                        total_pairs += 1

                        kw_a = card_keywords.get(card_a.id, set())
                        kw_b = card_keywords.get(card_b.id, set())
                        jaccard, shared = _jaccard_similarity(kw_a, kw_b)

                        emb_a = card_embeddings.get(card_a.id)
                        emb_b = card_embeddings.get(card_b.id)
                        cosine = _cosine_similarity(emb_a, emb_b) if emb_a and emb_b else 0.0

                        if emb_a and emb_b:
                            combined = JACCARD_WEIGHT * jaccard + COSINE_WEIGHT * cosine
                        else:
                            combined = jaccard

                        if combined >= threshold:
                            links.append(TopicLink(
                                topic_id_a=card_a.id,
                                topic_id_b=card_b.id,
                                similarity_score=round(combined, 4),
                                shared_keywords=shared,
                                created_at=datetime.now(UTC),
                            ))
                            total_score += combined

        # Clear old links and save new ones
        deleted = await topic_link_repo.delete_all()
        if deleted:
            logger.info("Cleared %d old topic links", deleted)

        saved = 0
        if links:
            saved = await topic_link_repo.upsert_batch(links)
            logger.info(
                "Created %d topic links from %d pairs (threshold=%.2f)",
                saved, total_pairs, threshold,
            )

    return LinkingResult(
        total_pairs_evaluated=total_pairs,
        links_created=saved,
        links_above_threshold=len(links),
        avg_similarity=round(total_score / len(links), 4) if links else 0.0,
    )


async def get_related_topics_for(
    topic_id: str,
    allowed_channel_ids: list[str] | None = None,
) -> list[dict]:
    """Get topics related to a given topic via topic_links.

    Args:
        topic_id: The topic to find related topics for.
        allowed_channel_ids: Tenant scoping — None=admin (all)

    Returns list of dicts with topic details and similarity info.
    """
    async with topic_linking_repos() as (
        topic_card_repo, _bundle_repo, topic_link_repo, _emb_repo, _db,
    ):
        links = await topic_link_repo.get_by_topic_id(topic_id)
        if not links:
            return []

        related = []
        for link in links:
            other_id = link.topic_id_b if link.topic_id_a == topic_id else link.topic_id_a
            card = await topic_card_repo.get_by_id(other_id)
            if card is None:
                continue

            channel = _get_channel(card) or "unknown"

            if allowed_channel_ids is not None:
                if not any(s in allowed_channel_ids for s in card.sources):
                    continue

            related.append({
                "topic_id": other_id,
                "title": card.title,
                "channel_id": channel,
                "similarity_score": link.similarity_score,
                "shared_keywords": link.shared_keywords,
            })

        return related
