#!/usr/bin/env python3
"""
S5 read-only what-if simulation: top-k keyword aggregation for Phase 1 assign.

Counterfactual replay of assign_documents_to_topics under mean vs topk schemes.
No DB writes.

Usage (prod):
  docker compose exec -T tg_parser python scripts/s5_assign_simulation.py
  docker compose exec -T tg_parser python scripts/s5_assign_simulation.py --json-out /tmp/s5_sim.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from tg_parser.config import settings
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.services.topicization_service import _DISCOVER_ATTEMPTED_PREFIX
from tg_parser.storage.sqlalchemy.database import Database
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
from tg_parser.storage.sqlalchemy.processing_failure_repo import SAProcessingFailureRepo
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

# Schemes to sweep (read-only what-if)
SCHEMES = ("mean", "topk_denom", "topk_num", "max", "sqrt", "phrase_topk")
DEFAULT_THRESHOLDS = (0.08, 0.10, 0.12, 0.15)
DEFAULT_TOPK = 3
REF_SCHEME = "mean"
REF_THRESHOLD = 0.10


@dataclass
class HitStructure:
    weighted_hits: float
    n_keywords: int
    n_phrases: int
    hits: set[str]
    phrase_hits: int


@dataclass
class AssignOutcome:
    topic_id: str | None
    score: float


@dataclass
class SimulationStats:
    total_docs: int = 0
    assigned: int = 0
    unassigned: int = 0
    winner_changes_vs_ref: int = 0
    newly_assigned_vs_ref: int = 0
    newly_unassigned_vs_ref: int = 0
    per_channel: dict[str, dict[str, int]] = field(default_factory=dict)


def _compute_hit_structure(
    topic_keywords: set[str],
    scope_in: list[str],
    title: str,
    strong_tokens: set[str],
    weak_tokens: set[str],
) -> HitStructure:
    """Mirror _compute_match_score hit detection; return raw counts for aggregation."""
    doc_tokens = strong_tokens | weak_tokens
    if not doc_tokens or not topic_keywords:
        return HitStructure(0.0, len(topic_keywords), 0, set(), 0)

    hits = topic_keywords & doc_tokens
    if not hits:
        for kw in topic_keywords:
            for dt in doc_tokens:
                if len(kw) >= 5 and len(dt) >= 5 and (kw in dt or dt in kw):
                    hits.add(kw)
                    break

    if not hits:
        return HitStructure(0.0, len(topic_keywords), 0, set(), 0)

    strong_hits = hits & strong_tokens
    weak_hits = hits - strong_tokens
    weighted_hits = len(strong_hits) + len(weak_hits) * 0.3

    phrases: list[set[str]] = []
    for kw in scope_in:
        tokens = TopicizationPipelineImpl._tokenize(kw)
        if tokens:
            phrases.append(tokens)
    title_tokens = TopicizationPipelineImpl._tokenize(title)
    if title_tokens:
        phrases.append(title_tokens)
    phrase_hits = sum(1 for phrase in phrases if phrase <= doc_tokens)

    return HitStructure(
        weighted_hits=weighted_hits,
        n_keywords=len(topic_keywords),
        n_phrases=len(phrases),
        hits=hits,
        phrase_hits=phrase_hits,
    )


def _aggregate_score(
    hs: HitStructure,
    scheme: str,
    *,
    topk: int = DEFAULT_TOPK,
) -> float:
    """Apply aggregation scheme to precomputed hit structure."""
    if hs.weighted_hits <= 0 and scheme != "phrase_topk":
        return 0.0
    n = hs.n_keywords
    h = hs.weighted_hits

    if scheme == "mean":
        return round(h / max(n, 1), 3)
    if scheme == "topk_denom":
        return round(h / max(min(n, topk), 1), 3)
    if scheme == "topk_num":
        kk = topk
        return round(min(h, kk) / kk, 3)
    if scheme == "max":
        return 1.0 if h > 0 else 0.0
    if scheme == "sqrt":
        return round(math.sqrt(h / max(n, 1)), 3)
    if scheme == "phrase_topk":
        if hs.n_phrases <= 0 or hs.phrase_hits <= 0:
            return 0.0
        kp = min(topk, hs.n_phrases)
        return round(min(hs.phrase_hits, kp) / kp, 3)
    raise ValueError(f"unknown scheme: {scheme}")


def _assign_argmax(
    topic_order: list[tuple[str, float]],
    threshold: float,
) -> AssignOutcome:
    """Replicate assign loop: strict > tie-break, first topic wins."""
    best_score = 0.0
    best_topic_id: str | None = None
    for topic_id, score in topic_order:
        if score > best_score:
            best_score = score
            best_topic_id = topic_id
    if best_topic_id is not None and best_score >= threshold:
        return AssignOutcome(best_topic_id, best_score)
    return AssignOutcome(None, best_score)


async def _list_active_channel_ids(session) -> list[str]:
    """Only active, non-deleted ingestion sources — matches scheduler hot path."""
    ingestion_session = Database.get_instance().ingestion_state_session()
    async with ingestion_session as ing:
        repo = SAIngestionStateRepo(ing)
        sources = await repo.list_sources(status="active")
        return sorted({s.source_id for s in sources})


async def _list_channel_ids(session) -> list[str]:
    """Fallback: distinct channels from processed_documents (legacy / all corpus)."""
    result = await session.execute(
        text("SELECT DISTINCT channel_id FROM processed_documents ORDER BY channel_id")
    )
    return [row.channel_id for row in result.fetchall()]


async def _load_discover_attempted(session, channel_id: str) -> set[str]:
    failure_repo = SAProcessingFailureRepo(session)
    out: set[str] = set()
    for f in await failure_repo.list_failures(channel_id=channel_id):
        ref = f.get("source_ref") or ""
        if ref.startswith(_DISCOVER_ATTEMPTED_PREFIX):
            out.add(ref[len(_DISCOVER_ATTEMPTED_PREFIX) :])
    return out


async def _load_covered_refs(session, channel_id: str) -> set[str]:
    bundle_repo = SATopicBundleRepo(session)
    covered: set[str] = set()
    for bundle in await bundle_repo.list_by_channel(channel_id):
        for item in bundle.items:
            covered.add(item.source_ref)
    return covered


def _simulate_channel(
    channel_id: str,
    docs: list,
    topic_cards: list,
    *,
    schemes: tuple[str, ...],
    thresholds: tuple[float, ...],
    topk: int,
    ref_scheme: str = REF_SCHEME,
    ref_threshold: float = REF_THRESHOLD,
) -> dict[str, Any]:
    """Run counterfactual assign for one channel."""
    topic_keyword_sets: list[tuple[str, str, list[str], set[str]]] = []
    for card in topic_cards:
        kws = TopicizationPipelineImpl._tokenize_topic_card(card)
        if kws:
            topic_keyword_sets.append((card.id, card.title, list(card.scope_in or []), kws))

    if not topic_keyword_sets:
        return {
            "channel_id": channel_id,
            "docs": len(docs),
            "topics": 0,
            "skipped": "no_topic_keywords",
        }

    # Precompute hit structures: doc_ref -> topic_id -> HitStructure
    hit_cache: dict[str, dict[str, HitStructure]] = {}
    doc_tokens_cache: dict[str, tuple[set[str], set[str]]] = {}
    rich_topics: list[dict[str, Any]] = []

    for _tid, title, scope_in, kws in topic_keyword_sets:
        rich_topics.append(
            {
                "topic_id": _tid,
                "title": title[:80],
                "n_keywords": len(kws),
                "n_scope_in": len(scope_in),
            }
        )
    rich_topics.sort(key=lambda x: -x["n_keywords"])

    for doc in docs:
        strong, weak = TopicizationPipelineImpl._tokenize_document(doc)
        doc_tokens_cache[doc.source_ref] = (strong, weak)
        per_topic: dict[str, HitStructure] = {}
        for tid, card_title, scope_in, kws in topic_keyword_sets:
            per_topic[tid] = _compute_hit_structure(kws, scope_in, card_title, strong, weak)
        hit_cache[doc.source_ref] = per_topic

    # Score cache: scheme -> doc_ref -> topic_id -> score
    score_cache: dict[str, dict[str, dict[str, float]]] = {}
    for scheme in schemes:
        score_cache[scheme] = {}
        for doc in docs:
            per_topic_scores: dict[str, float] = {}
            for tid, _title, _scope_in, _kws in topic_keyword_sets:
                hs = hit_cache[doc.source_ref][tid]
                per_topic_scores[tid] = _aggregate_score(hs, scheme, topk=topk)
            score_cache[scheme][doc.source_ref] = per_topic_scores

    topic_order_ids = [tid for tid, _, _, _ in topic_keyword_sets]

    def run_assign(scheme: str, threshold: float) -> dict[str, AssignOutcome]:
        outcomes: dict[str, AssignOutcome] = {}
        for doc in docs:
            topic_order = [
                (tid, score_cache[scheme][doc.source_ref][tid]) for tid in topic_order_ids
            ]
            outcomes[doc.source_ref] = _assign_argmax(topic_order, threshold)
        return outcomes

    # Primary stats at ref_threshold
    ref_outcomes = run_assign(ref_scheme, ref_threshold)
    results_by_scheme: dict[str, dict[str, Any]] = {}

    for scheme in schemes:
        outcomes = run_assign(scheme, ref_threshold)
        assigned = sum(1 for o in outcomes.values() if o.topic_id is not None)
        unassigned = len(docs) - assigned
        winner_changed = 0
        newly_assigned = 0
        newly_unassigned = 0
        delta_pairs: list[dict[str, Any]] = []

        for doc in docs:
            ref_o = ref_outcomes[doc.source_ref]
            o = outcomes[doc.source_ref]
            if ref_o.topic_id != o.topic_id:
                if ref_o.topic_id is None and o.topic_id is not None:
                    newly_assigned += 1
                elif ref_o.topic_id is not None and o.topic_id is None:
                    newly_unassigned += 1
                elif ref_o.topic_id is not None and o.topic_id is not None:
                    winner_changed += 1
                if scheme != ref_scheme and len(delta_pairs) < 30:
                    strong, weak = doc_tokens_cache[doc.source_ref]
                    delta_pairs.append(
                        {
                            "source_ref": doc.source_ref,
                            "summary": (doc.summary or "")[:120],
                            "ref_topic": ref_o.topic_id,
                            "ref_score": ref_o.score,
                            "new_topic": o.topic_id,
                            "new_score": o.score,
                            "doc_topics": (doc.topics or [])[:5],
                        }
                    )

        results_by_scheme[scheme] = {
            "assigned": assigned,
            "unassigned": unassigned,
            "assign_rate_pct": round(100 * assigned / max(len(docs), 1), 2),
            "discover_proxy_pct": round(100 * unassigned / max(len(docs), 1), 2),
            "delta_vs_mean": {
                "newly_assigned": newly_assigned,
                "newly_unassigned": newly_unassigned,
                "winner_changed": winner_changed,
            },
            "sample_deltas": delta_pairs[:15] if scheme != ref_scheme else [],
        }

    # Threshold sensitivity for key schemes
    threshold_sweep: dict[str, dict[str, dict[str, Any]]] = {}
    for scheme in ("mean", "topk_denom", "topk_num"):
        threshold_sweep[scheme] = {}
        for thr in thresholds:
            outcomes = run_assign(scheme, thr)
            assigned = sum(1 for o in outcomes.values() if o.topic_id is not None)
            threshold_sweep[scheme][str(thr)] = {
                "assigned": assigned,
                "assign_rate_pct": round(100 * assigned / max(len(docs), 1), 2),
            }

    # Stratify topics by vocabulary size
    n_le3 = sum(1 for t in rich_topics if t["n_keywords"] <= 3)
    n_ge4 = sum(1 for t in rich_topics if t["n_keywords"] >= 4)
    scope_ge4 = sum(1 for t in rich_topics if t["n_scope_in"] >= 4)

    # Rich-topic assign lift (topk_denom vs mean) — precompute once
    topk_outcomes = run_assign("topk_denom", ref_threshold)
    rich_lift: list[dict[str, Any]] = []
    for t in rich_topics[:20]:
        tid = t["topic_id"]
        mean_wins = 0
        topk_wins = 0
        topk_only = 0
        for doc in docs:
            ref_o = ref_outcomes[doc.source_ref]
            topk_o = topk_outcomes[doc.source_ref]
            if ref_o.topic_id == tid:
                mean_wins += 1
            if topk_o.topic_id == tid:
                topk_wins += 1
            if ref_o.topic_id != tid and topk_o.topic_id == tid:
                topk_only += 1
        rich_lift.append({**t, "mean_wins": mean_wins, "topk_wins": topk_wins, "topk_only": topk_only})

    return {
        "channel_id": channel_id,
        "docs": len(docs),
        "topics": len(topic_keyword_sets),
        "topics_n_le3": n_le3,
        "topics_n_ge4": n_ge4,
        "topics_scope_in_ge4": scope_ge4,
        "schemes": results_by_scheme,
        "threshold_sweep": threshold_sweep,
        "rich_topics_top20": rich_lift,
    }


async def run_simulation(
    *,
    schemes: tuple[str, ...] = SCHEMES,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    topk: int = DEFAULT_TOPK,
    all_processed_channels: bool = False,
    exclude_channels: list[str] | None = None,
) -> dict[str, Any]:
    db = Database.get_instance()
    await db.init()
    session = db.processing_storage_session()

    async with session:
        if all_processed_channels:
            channel_ids = await _list_channel_ids(session)
            channel_filter = "all_processed_documents"
        else:
            channel_ids = await _list_active_channel_ids(session)
            channel_filter = "active_sources_only"

        exclude = set(exclude_channels or [])
        if exclude:
            channel_ids = [c for c in channel_ids if c not in exclude]

        print(
            f"[s5] channels={len(channel_ids)} filter={channel_filter} exclude={sorted(exclude)}",
            file=sys.stderr,
            flush=True,
        )
        card_repo = SATopicCardRepo(session)
        doc_repo = SAProcessedDocumentRepo(session)

        t1_channels: list[dict[str, Any]] = []
        t2_channels: list[dict[str, Any]] = []

        global_t1: dict[str, dict[str, int]] = defaultdict(
            lambda: {"assigned": 0, "unassigned": 0, "docs": 0}
        )
        global_t2: dict[str, dict[str, int]] = defaultdict(
            lambda: {"assigned": 0, "unassigned": 0, "docs": 0}
        )
        global_delta: dict[str, dict[str, int]] = defaultdict(
            lambda: {"newly_assigned": 0, "newly_unassigned": 0, "winner_changed": 0}
        )

        fp_candidates: list[dict[str, Any]] = []

        for idx, channel_id in enumerate(channel_ids, start=1):
            print(f"[s5] channel {idx}/{len(channel_ids)}: {channel_id}", file=sys.stderr, flush=True)
            docs = await doc_repo.list_by_channel(channel_id)
            if not docs:
                continue
            topic_cards = await card_repo.list_by_channel(channel_id)
            if not topic_cards:
                continue

            ch_result = _simulate_channel(
                channel_id,
                docs,
                topic_cards,
                schemes=schemes,
                thresholds=thresholds,
                topk=topk,
            )
            t1_channels.append(ch_result)

            for scheme, stats in ch_result.get("schemes", {}).items():
                global_t1[scheme]["assigned"] += stats["assigned"]
                global_t1[scheme]["unassigned"] += stats["unassigned"]
                global_t1[scheme]["docs"] += ch_result["docs"]
                if scheme != REF_SCHEME:
                    d = stats["delta_vs_mean"]
                    global_delta[scheme]["newly_assigned"] += d["newly_assigned"]
                    global_delta[scheme]["newly_unassigned"] += d["newly_unassigned"]
                    global_delta[scheme]["winner_changed"] += d["winner_changed"]
                    for sample in stats.get("sample_deltas", []):
                        if len(fp_candidates) < 50:
                            fp_candidates.append({"channel_id": channel_id, **sample})

            # T2: reconcile candidates = uncovered - discover_attempted
            covered = await _load_covered_refs(session, channel_id)
            attempted = await _load_discover_attempted(session, channel_id)
            candidate_refs = [
                d.source_ref
                for d in docs
                if d.source_ref not in covered and d.source_ref not in attempted
            ]
            if candidate_refs:
                candidate_docs = [d for d in docs if d.source_ref in candidate_refs]
                t2_result = _simulate_channel(
                    channel_id,
                    candidate_docs,
                    topic_cards,
                    schemes=("mean", "topk_denom", "topk_num"),
                    thresholds=thresholds,
                    topk=topk,
                )
                t2_channels.append(t2_result)
                for scheme, stats in t2_result.get("schemes", {}).items():
                    global_t2[scheme]["assigned"] += stats["assigned"]
                    global_t2[scheme]["unassigned"] += stats["unassigned"]
                    global_t2[scheme]["docs"] += t2_result["docs"]

        def _global_summary(bucket: dict[str, dict[str, int]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for scheme, counts in bucket.items():
                docs = counts["docs"]
                out[scheme] = {
                    "docs": docs,
                    "assigned": counts["assigned"],
                    "unassigned": counts["unassigned"],
                    "assign_rate_pct": round(100 * counts["assigned"] / max(docs, 1), 2),
                    "discover_proxy_pct": round(100 * counts["unassigned"] / max(docs, 1), 2),
                }
                if scheme == "topk_denom" and REF_SCHEME in bucket:
                    mean_unassigned = bucket[REF_SCHEME]["unassigned"]
                    topk_unassigned = counts["unassigned"]
                    reduction = mean_unassigned - topk_unassigned
                    out[scheme]["discover_reduction_vs_mean"] = reduction
                    out[scheme]["discover_reduction_pct"] = round(
                        100 * reduction / max(mean_unassigned, 1), 2
                    )
            return out


        return {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "settings": {
                "topicization_supporting_min_score": settings.topicization_supporting_min_score,
                "topicization_min_token_length": settings.topicization_min_token_length,
                "topicization_text_clean_match_chars": settings.topicization_text_clean_match_chars,
                "topk": topk,
                "ref_scheme": REF_SCHEME,
                "ref_threshold": REF_THRESHOLD,
            },
            "channels": len(channel_ids),
            "channel_filter": channel_filter,
            "excluded_channels": sorted(exclude),
            "t1_global": _global_summary(global_t1),
            "t1_delta_vs_mean": dict(global_delta),
            "t2_global": _global_summary(global_t2),
            "t1_per_channel": t1_channels,
            "t2_per_channel": t2_channels,
            "fp_spot_check_candidates": fp_candidates[:25],
            "watch_band_proposal": {
                "assign_rate_lift_pct": "5-25",
                "discover_reduction_pct": "10-30",
                "winner_change_pct_cap": None,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="S5 Phase 1 assign top-k simulation")
    parser.add_argument("--json-out", help="Write JSON results to file")
    parser.add_argument("--topk", type=int, default=DEFAULT_TOPK)
    parser.add_argument(
        "--all-processed-channels",
        action="store_true",
        help="Include paused/deleted channels that still have processed_documents (legacy T1)",
    )
    parser.add_argument(
        "--exclude-channel",
        action="append",
        default=[],
        help="Skip channel(s) e.g. murashko_med",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    for name in ("structlog", "tg_parser"):
        logging.getLogger(name).setLevel(logging.WARNING)

    result = asyncio.run(
        run_simulation(
            topk=args.topk,
            all_processed_channels=args.all_processed_channels,
            exclude_channels=args.exclude_channel,
        )
    )

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
