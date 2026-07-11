#!/usr/bin/env python3
"""
S4 read-only what-if simulation: anchor embeddings vs topic embeddings.

Compares cross-channel link counts and same-channel merge losers under
different thresholds and embedding sources. No DB writes.

Usage (prod):
  docker compose exec -T tg_parser python scripts/s4_linking_simulation.py
  docker compose exec -T tg_parser python scripts/s4_linking_simulation.py --fine-sweep
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import text

from tg_parser.services.analytics_service import _extract_keywords
from tg_parser.services.topic_linking_service import (
    COSINE_WEIGHT,
    JACCARD_WEIGHT,
    _cosine_similarity,
    _jaccard_similarity,
)
from tg_parser.storage.sqlalchemy.database import Database
from tg_parser.storage.sqlalchemy.embedding_repo import _parse_pgvector_text
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

EmbeddingSource = Literal["anchor", "topic_with_fallback"]

CROSS_THRESHOLDS = [0.25, 0.30, 0.35, 0.40]
FINE_CROSS_THRESHOLDS = [0.30, 0.31, 0.32, 0.33, 0.34, 0.35]
MERGE_THRESHOLDS = [0.55, 0.60, 0.65, 0.70]

# WORKFLOW watch band: ±20% of prod baseline (2452 links, 2026-07-11)
WATCH_BAND_LOW = 1962
WATCH_BAND_HIGH = 2942


@dataclass
class ResolveStats:
    topic: int = 0
    anchor_fallback: int = 0
    missing: int = 0


def _get_channel(card) -> str | None:
    return card.sources[0] if card.sources else None


def _combined_score(
    kw_a: set[str],
    kw_b: set[str],
    emb_a: list[float] | None,
    emb_b: list[float] | None,
) -> tuple[float, list[str]]:
    jaccard, shared = _jaccard_similarity(kw_a, kw_b)
    if emb_a and emb_b:
        cosine = _cosine_similarity(emb_a, emb_b)
        return JACCARD_WEIGHT * jaccard + COSINE_WEIGHT * cosine, shared
    return jaccard, shared


def _resolve_embedding(
    card,
    topic_embs: dict[str, list[float]],
    anchor_embs: dict[str, list[float]],
    source: EmbeddingSource,
    stats: ResolveStats,
) -> list[float] | None:
    if source == "anchor":
        if not card.anchors:
            stats.missing += 1
            return None
        vec = anchor_embs.get(card.anchors[0].anchor_ref)
        if vec is None:
            stats.missing += 1
        return vec

    vec = topic_embs.get(card.id)
    if vec is not None:
        stats.topic += 1
        return vec
    if card.anchors:
        fallback = anchor_embs.get(card.anchors[0].anchor_ref)
        if fallback is not None:
            stats.anchor_fallback += 1
            return fallback
    stats.missing += 1
    return None


async def _load_embeddings(session) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    query = text("""
        SELECT source_ref, embedding::text, entry_type
        FROM document_embeddings
        WHERE entry_type IN ('topic', 'message')
    """)
    result = await session.execute(query)
    topic_embs: dict[str, list[float]] = {}
    anchor_embs: dict[str, list[float]] = {}
    for row in result.fetchall():
        vec = _parse_pgvector_text(row.embedding)
        if row.entry_type == "topic":
            topic_embs[row.source_ref] = vec
        else:
            anchor_embs[row.source_ref] = vec
    return topic_embs, anchor_embs


async def _load_embeddings_for_cards(
    session,
    cards,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Load topic embs + only anchor refs referenced by cards (faster than full scan)."""
    topic_query = text("""
        SELECT source_ref, embedding::text
        FROM document_embeddings
        WHERE entry_type = 'topic'
    """)
    topic_result = await session.execute(topic_query)
    topic_embs = {
        row.source_ref: _parse_pgvector_text(row.embedding) for row in topic_result.fetchall()
    }

    anchor_refs = list(dict.fromkeys(c.anchors[0].anchor_ref for c in cards if c.anchors))

    anchor_embs: dict[str, list[float]] = {}
    if anchor_refs:
        anchor_query = text("""
            SELECT source_ref, embedding::text
            FROM document_embeddings
            WHERE entry_type = 'message' AND source_ref = ANY(:refs)
        """)
        anchor_result = await session.execute(anchor_query, {"refs": anchor_refs})
        anchor_embs = {
            row.source_ref: _parse_pgvector_text(row.embedding) for row in anchor_result.fetchall()
        }

    return topic_embs, anchor_embs


async def _load_current_links(session) -> dict[frozenset[str], float]:
    result = await session.execute(
        text("SELECT topic_id_a, topic_id_b, similarity_score FROM topic_links")
    )
    out: dict[frozenset[str], float] = {}
    for row in result.fetchall():
        key = frozenset({row.topic_id_a, row.topic_id_b})
        out[key] = float(row.similarity_score)
    return out


def _simulate_cross_channel(
    cards,
    card_keywords: dict[str, set[str]],
    card_embeddings: dict[str, list[float]],
    thresholds: list[float],
) -> dict[str, dict[str, int | float]]:
    channel_cards: dict[str, list] = defaultdict(list)
    for card in cards:
        ch = _get_channel(card)
        if ch:
            channel_cards[ch].append(card)

    channels = sorted(channel_cards.keys())
    pair_scores: list[float] = []
    threshold_counts: dict[float, int] = dict.fromkeys(thresholds, 0)

    for i, ch_a in enumerate(channels):
        for ch_b in channels[i + 1 :]:
            for card_a in channel_cards[ch_a]:
                for card_b in channel_cards[ch_b]:
                    combined, _ = _combined_score(
                        card_keywords.get(card_a.id, set()),
                        card_keywords.get(card_b.id, set()),
                        card_embeddings.get(card_a.id),
                        card_embeddings.get(card_b.id),
                    )
                    pair_scores.append(combined)
                    for t in thresholds:
                        if combined >= t:
                            threshold_counts[t] += 1

    total_pairs = len(pair_scores)
    return {
        "channels": len(channels),
        "cards": len(cards),
        "total_pairs": total_pairs,
        "avg_score_all_pairs": round(sum(pair_scores) / total_pairs, 4) if total_pairs else 0.0,
        "links_at_threshold": {str(t): threshold_counts[t] for t in thresholds},
    }


def _simulate_same_channel_merge(
    cards,
    card_keywords: dict[str, set[str]],
    card_embeddings: dict[str, list[float]],
    thresholds: list[float],
) -> dict[str, dict[str, int]]:
    by_channel: dict[str, list] = defaultdict(list)
    for card in cards:
        ch = _get_channel(card)
        if ch:
            by_channel[ch].append(card)

    result: dict[str, dict[str, int]] = {}
    for threshold in thresholds:
        total_losers = 0
        per_channel: dict[str, int] = {}
        for ch, channel_cards in by_channel.items():
            if len(channel_cards) < 2:
                per_channel[ch] = 0
                continue
            cards_sorted = sorted(channel_cards, key=lambda c: c.id)
            alive = {c.id: True for c in cards_sorted}
            losers = 0
            for i, survivor in enumerate(cards_sorted):
                if not alive[survivor.id]:
                    continue
                for loser in cards_sorted[i + 1 :]:
                    if not alive[loser.id]:
                        continue
                    combined, _ = _combined_score(
                        card_keywords.get(survivor.id, set()),
                        card_keywords.get(loser.id, set()),
                        card_embeddings.get(survivor.id),
                        card_embeddings.get(loser.id),
                    )
                    if combined >= threshold:
                        alive[loser.id] = False
                        losers += 1
            per_channel[ch] = losers
            total_losers += losers
        result[str(threshold)] = {
            "total_merge_losers": total_losers,
            "per_channel": per_channel,
        }
    return result


def _diff_links(
    current: dict[frozenset[str], float],
    simulated_pairs: list[tuple[str, str, float]],
    ref_threshold: float = 0.30,
) -> dict[str, int | float]:
    sim: dict[frozenset[str], float] = {}
    for a, b, score in simulated_pairs:
        if score >= ref_threshold:
            sim[frozenset({a, b})] = score

    current_keys = set(current.keys())
    sim_keys = set(sim.keys())
    added = sim_keys - current_keys
    removed = current_keys - sim_keys
    changed = 0
    for key in current_keys & sim_keys:
        if abs(current[key] - sim[key]) > 0.0001:
            changed += 1

    return {
        "current_links": len(current_keys),
        "simulated_links": len(sim_keys),
        "added": len(added),
        "removed": len(removed),
        "score_changed": changed,
        "unchanged": len(current_keys & sim_keys) - changed,
    }


def _pick_threshold_in_band(
    links_at_threshold: dict[str, int],
    thresholds: list[float],
    low: int,
    high: int,
) -> dict:
    in_band = [
        (t, links_at_threshold[str(t)])
        for t in thresholds
        if low <= links_at_threshold[str(t)] <= high
    ]
    closest = min(
        ((t, links_at_threshold[str(t)]) for t in thresholds),
        key=lambda x: abs(x[1] - (low + high) // 2),
    )
    return {
        "watch_band": [low, high],
        "in_band": {str(t): n for t, n in in_band},
        "closest_to_midband": {"threshold": closest[0], "links": closest[1]},
    }


async def run_fine_sweep() -> dict:
    """Topic-emb cross-channel sweep @ 0.30–0.35 (0.01 steps). Skips merge/anchor reruns."""
    db = Database.get_instance()
    await db.init()
    session = db.processing_storage_session()

    async with session:
        card_repo = SATopicCardRepo(session)
        cards = await card_repo.list_all()
        topic_embs, anchor_embs = await _load_embeddings_for_cards(session, cards)
        current_links = await _load_current_links(session)

        card_keywords = {c.id: _extract_keywords(c) for c in cards}

        topic_resolve = ResolveStats()
        topic_card_embeddings: dict[str, list[float]] = {}
        for card in cards:
            vec = _resolve_embedding(
                card, topic_embs, anchor_embs, "topic_with_fallback", topic_resolve
            )
            if vec is not None:
                topic_card_embeddings[card.id] = vec

        cross_topic = _simulate_cross_channel(
            cards, card_keywords, topic_card_embeddings, FINE_CROSS_THRESHOLDS
        )

        links_map = {k: int(v) for k, v in cross_topic["links_at_threshold"].items()}
        recommendation = _pick_threshold_in_band(
            links_map, FINE_CROSS_THRESHOLDS, WATCH_BAND_LOW, WATCH_BAND_HIGH
        )

        return {
            "mode": "fine_sweep",
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "thresholds": FINE_CROSS_THRESHOLDS,
            "current_prod_links": {
                "count": len(current_links),
                "avg_score": round(sum(current_links.values()) / len(current_links), 4)
                if current_links
                else 0.0,
            },
            "resolve_stats": {
                "topic_with_fallback": {
                    "topic": topic_resolve.topic,
                    "anchor_fallback": topic_resolve.anchor_fallback,
                    "missing": topic_resolve.missing,
                },
            },
            "cross_channel_topic_emb": cross_topic,
            "recommendation": recommendation,
        }


async def run_simulation() -> dict:
    db = Database.get_instance()
    await db.init()
    session = db.processing_storage_session()

    async with session:
        card_repo = SATopicCardRepo(session)
        cards = await card_repo.list_all()
        topic_embs, anchor_embs = await _load_embeddings(session)
        current_links = await _load_current_links(session)

        card_keywords = {c.id: _extract_keywords(c) for c in cards}

        # Resolve stats for topic-with-fallback (proposed production path)
        topic_resolve = ResolveStats()
        topic_card_embeddings: dict[str, list[float]] = {}
        for card in cards:
            vec = _resolve_embedding(
                card, topic_embs, anchor_embs, "topic_with_fallback", topic_resolve
            )
            if vec is not None:
                topic_card_embeddings[card.id] = vec

        anchor_resolve = ResolveStats()
        anchor_card_embeddings: dict[str, list[float]] = {}
        for card in cards:
            vec = _resolve_embedding(card, topic_embs, anchor_embs, "anchor", anchor_resolve)
            if vec is not None:
                anchor_card_embeddings[card.id] = vec

        cross_anchor = _simulate_cross_channel(
            cards, card_keywords, anchor_card_embeddings, CROSS_THRESHOLDS
        )
        cross_topic = _simulate_cross_channel(
            cards, card_keywords, topic_card_embeddings, CROSS_THRESHOLDS
        )

        merge_anchor = _simulate_same_channel_merge(
            cards, card_keywords, anchor_card_embeddings, MERGE_THRESHOLDS
        )
        merge_topic = _simulate_same_channel_merge(
            cards, card_keywords, topic_card_embeddings, MERGE_THRESHOLDS
        )

        # Build simulated link pairs at 0.30 for snapshot diff
        def collect_pairs(card_embeddings: dict[str, list[float]]) -> list[tuple[str, str, float]]:
            channel_cards: dict[str, list] = defaultdict(list)
            for card in cards:
                ch = _get_channel(card)
                if ch:
                    channel_cards[ch].append(card)
            channels = sorted(channel_cards.keys())
            pairs: list[tuple[str, str, float]] = []
            for i, ch_a in enumerate(channels):
                for ch_b in channels[i + 1 :]:
                    for card_a in channel_cards[ch_a]:
                        for card_b in channel_cards[ch_b]:
                            combined, _ = _combined_score(
                                card_keywords.get(card_a.id, set()),
                                card_keywords.get(card_b.id, set()),
                                card_embeddings.get(card_a.id),
                                card_embeddings.get(card_b.id),
                            )
                            pairs.append((card_a.id, card_b.id, combined))
            return pairs

        diff_anchor = _diff_links(current_links, collect_pairs(anchor_card_embeddings), 0.30)
        diff_topic = _diff_links(current_links, collect_pairs(topic_card_embeddings), 0.30)

        coverage = {
            "total_cards": len(cards),
            "topic_embeddings": len(topic_embs),
            "topic_emb_coverage_pct": round(100 * len(topic_embs) / max(len(cards), 1), 2),
        }

        return {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coverage": coverage,
            "resolve_stats": {
                "anchor_source": {
                    "topic": anchor_resolve.topic,
                    "anchor_fallback": anchor_resolve.anchor_fallback,
                    "missing": anchor_resolve.missing,
                },
                "topic_with_fallback": {
                    "topic": topic_resolve.topic,
                    "anchor_fallback": topic_resolve.anchor_fallback,
                    "missing": topic_resolve.missing,
                },
            },
            "cross_channel": {
                "anchor_emb": cross_anchor,
                "topic_emb": cross_topic,
            },
            "same_channel_merge": {
                "anchor_emb": merge_anchor,
                "topic_emb": merge_topic,
            },
            "snapshot_diff_at_0_30": {
                "anchor_emb": diff_anchor,
                "topic_emb": diff_topic,
            },
            "current_prod_links": {
                "count": len(current_links),
                "avg_score": round(sum(current_links.values()) / len(current_links), 4)
                if current_links
                else 0.0,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="S4 topic linking threshold simulation")
    parser.add_argument(
        "--fine-sweep",
        action="store_true",
        help="Topic-emb only: sweep 0.30–0.35 (skips merge/anchor reruns)",
    )
    args = parser.parse_args()

    result = asyncio.run(run_fine_sweep() if args.fine_sweep else run_simulation())
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
