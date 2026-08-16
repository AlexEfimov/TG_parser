#!/usr/bin/env python3
"""
R6 read-only what-if: keyword stoplist / df vs current cross-channel linking.

Does not write to the DB. Does not modify product ``_extract_keywords``.
Keyword filters are wrappers over a copy of the baseline set.

Usage (prod, already-running tg_parser — scripts/ is not in the image):
  docker cp scripts/r6_stoplist_simulation.py tg_parser:/tmp/r6_stoplist_simulation.py
  docker compose exec -T tg_parser python /tmp/r6_stoplist_simulation.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from tg_parser.config import settings
from tg_parser.services.analytics_service import _extract_keywords
from tg_parser.services.db_context import topic_linking_repos
from tg_parser.services.topic_linking_service import (
    COSINE_WEIGHT,
    JACCARD_WEIGHT,
    _cosine_similarity,
    _jaccard_similarity,
    load_card_embeddings,
)

# Seed from START_PROMPT R6 §3.1 — not the final product list.
STOPLIST = frozenset(
    """
    для при как его её их это этой этот или чем что чтобы также
    the and for with from that this are was were
    """.split()
)

DF_FRACTIONS = (0.15, 0.25, 0.40)
THRESHOLDS = (0.30, 0.32, 0.33)
PRIMARY_THRESHOLD = 0.32
CONTENT_TOKENS_TO_WATCH = ("здоровье", "диагностика", "профилактика", "медицинских")
EVIDENCE_TOKENS = ("для", "при", "как", "его")
DLA_ALONE = ("для",)


def _pair_key(id_a: str, id_b: str) -> tuple[str, str]:
    """Canonical pair key — same as topic_link_repo ``sorted((id_a, id_b))``."""
    return tuple(sorted((id_a, id_b)))


def _get_channel(card) -> str | None:
    return card.sources[0] if card.sources else None


def _combined(
    kw_a: set[str],
    kw_b: set[str],
    cosine: float | None,
) -> tuple[float, list[str]]:
    jaccard, shared = _jaccard_similarity(kw_a, kw_b)
    if cosine is not None:
        return JACCARD_WEIGHT * jaccard + COSINE_WEIGHT * cosine, shared
    return jaccard, shared


def _apply_stoplist(kws: set[str]) -> set[str]:
    return {t for t in kws if t not in STOPLIST}


def _apply_df(kws: set[str], drop: frozenset[str]) -> set[str]:
    return {t for t in kws if t not in drop}


def _df_by_token(card_keywords: dict[str, set[str]], n_cards: int) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for kws in card_keywords.values():
        counts.update(kws)
    return {token: count / n_cards for token, count in counts.items()} if n_cards else {}


def _diff(
    current: dict[tuple[str, str], float],
    simulated: dict[tuple[str, str], float],
) -> dict[str, int]:
    current_keys = set(current)
    sim_keys = set(simulated)
    changed = 0
    for key in current_keys & sim_keys:
        if abs(current[key] - simulated[key]) > 0.0001:
            changed += 1
    return {
        "current_links": len(current_keys),
        "simulated_links": len(sim_keys),
        "added": len(sim_keys - current_keys),
        "removed": len(current_keys - sim_keys),
        "score_changed": changed,
        "unchanged": len(current_keys & sim_keys) - changed,
    }


def _avg(scores: Iterable[float]) -> float:
    values = list(scores)
    return round(sum(values) / len(values), 4) if values else 0.0


def _classify_current_link_fate(
    stored_shared: list[str],
    new_shared: list[str],
    new_score: float,
    threshold: float,
    filter_tokens: frozenset[str],
) -> str:
    """Fate of one existing table row under a keyword filter."""
    if new_score < threshold:
        return "dropped_below_threshold"
    stored_set = set(stored_shared)
    dropped = stored_set & filter_tokens
    if dropped and not new_shared:
        return "stayed_label_cleaned"
    if dropped:
        return "stayed_label_partially_cleaned"
    return "stayed_unchanged_label"


async def run_simulation() -> dict:
    started = time.monotonic()
    print("r6: loading cards / embeddings / current links", file=sys.stderr, flush=True)

    async with topic_linking_repos() as (
        topic_card_repo,
        _bundle_repo,
        topic_link_repo,
        embedding_repo,
        _db,
    ):
        cards = await topic_card_repo.list_all()
        current_rows = await topic_link_repo.list_all()
        card_embeddings, emb_stats = await load_card_embeddings(cards, embedding_repo)

    load_s = round(time.monotonic() - started, 1)
    print(
        f"r6: loaded {len(cards)} cards, {len(current_rows)} links in {load_s}s",
        file=sys.stderr,
        flush=True,
    )

    baseline_kw = {c.id: _extract_keywords(c) for c in cards}
    n_cards = len(cards)
    df = _df_by_token(baseline_kw, n_cards)
    df_drop = {
        frac: frozenset(token for token, freq in df.items() if freq > frac) for frac in DF_FRACTIONS
    }

    schemes: dict[str, dict[str, set[str]]] = {
        "baseline": baseline_kw,
        "stoplist": {cid: _apply_stoplist(kws) for cid, kws in baseline_kw.items()},
    }
    for frac in DF_FRACTIONS:
        schemes[f"df_{frac:.2f}"] = {
            cid: _apply_df(kws, df_drop[frac]) for cid, kws in baseline_kw.items()
        }

    filter_tokens = {
        "baseline": frozenset(),
        "stoplist": STOPLIST,
        **{f"df_{frac:.2f}": df_drop[frac] for frac in DF_FRACTIONS},
    }

    current_scores: dict[tuple[str, str], float] = {}
    current_shared: dict[tuple[str, str], list[str]] = {}
    for link in current_rows:
        key = _pair_key(link.topic_id_a, link.topic_id_b)
        current_scores[key] = float(link.similarity_score)
        current_shared[key] = list(link.shared_keywords or [])

    channel_cards: dict[str, list] = defaultdict(list)
    for card in cards:
        ch = _get_channel(card)
        if ch:
            channel_cards[ch].append(card)
    channels = sorted(channel_cards)
    total_pairs_est = 0
    for i, ch_a in enumerate(channels):
        for ch_b in channels[i + 1 :]:
            total_pairs_est += len(channel_cards[ch_a]) * len(channel_cards[ch_b])

    print(
        f"r6: {len(channels)} channels, ~{total_pairs_est} cross-channel pairs, "
        f"threshold default={settings.cross_channel_link_threshold}",
        file=sys.stderr,
        flush=True,
    )

    # scheme -> threshold -> {pair: (score, shared)}
    sim_links: dict[str, dict[float, dict[tuple[str, str], tuple[float, list[str]]]]] = {
        name: {t: {} for t in THRESHOLDS} for name in schemes
    }
    all_pair_scores: dict[str, list[float]] = {name: [] for name in schemes}
    pair_count = 0
    pairs_with_cosine = 0
    loop_started = time.monotonic()

    for i, ch_a in enumerate(channels):
        for ch_b in channels[i + 1 :]:
            for card_a in channel_cards[ch_a]:
                emb_a = card_embeddings.get(card_a.id)
                for card_b in channel_cards[ch_b]:
                    pair_count += 1
                    emb_b = card_embeddings.get(card_b.id)
                    if emb_a and emb_b:
                        cosine: float | None = _cosine_similarity(emb_a, emb_b)
                        pairs_with_cosine += 1
                    else:
                        cosine = None

                    key = _pair_key(card_a.id, card_b.id)
                    for name, kw_map in schemes.items():
                        combined, shared = _combined(
                            kw_map.get(card_a.id, set()),
                            kw_map.get(card_b.id, set()),
                            cosine,
                        )
                        all_pair_scores[name].append(combined)
                        rounded = round(combined, 4)
                        for threshold in THRESHOLDS:
                            if combined >= threshold:
                                sim_links[name][threshold][key] = (rounded, shared)

                    if pair_count % 200_000 == 0:
                        elapsed = time.monotonic() - loop_started
                        rate = pair_count / elapsed if elapsed else 0
                        eta = (total_pairs_est - pair_count) / rate if rate else 0
                        print(
                            f"r6: pairs {pair_count}/{total_pairs_est} "
                            f"({elapsed:.0f}s, eta {eta:.0f}s)",
                            file=sys.stderr,
                            flush=True,
                        )

    loop_s = round(time.monotonic() - loop_started, 1)
    print(f"r6: scored {pair_count} pairs in {loop_s}s", file=sys.stderr, flush=True)

    # Tokens the filter would drop from *current table* shared_keywords.
    current_token_counts: Counter[str] = Counter()
    for shared in current_shared.values():
        current_token_counts.update(shared)

    def _dropped_from_table(tokens: frozenset[str]) -> list[dict]:
        dropped = [
            {"token": token, "links": current_token_counts[token]}
            for token in tokens
            if current_token_counts[token]
        ]
        dropped.sort(key=lambda row: (-row["links"], row["token"]))
        return dropped

    # Current-table evidence: links whose stored shared set is only service tokens.
    stoplist_only_keys = [
        key for key, shared in current_shared.items() if shared and set(shared) <= STOPLIST
    ]
    dla_alone_keys = [key for key, shared in current_shared.items() if shared == list(DLA_ALONE)]

    def _fate_block(
        name: str,
        threshold: float,
        keys: list[tuple[str, str]],
    ) -> dict:
        counts: Counter[str] = Counter()
        empty_shared_stayed = 0
        for key in keys:
            sim = sim_links[name][threshold].get(key)
            if sim is None:
                counts["dropped_below_threshold"] += 1
                continue
            score, shared = sim
            fate = _classify_current_link_fate(
                current_shared[key],
                shared,
                score,
                threshold,
                filter_tokens[name],
            )
            counts[fate] += 1
            if not shared:
                empty_shared_stayed += 1
        return {
            "n": len(keys),
            "dropped_below_threshold": counts["dropped_below_threshold"],
            "stayed_label_cleaned": counts["stayed_label_cleaned"],
            "stayed_label_partially_cleaned": counts["stayed_label_partially_cleaned"],
            "stayed_unchanged_label": counts["stayed_unchanged_label"],
            "stayed_empty_shared_keywords": empty_shared_stayed,
        }

    scheme_reports: dict[str, dict] = {}
    for name in schemes:
        by_threshold: dict[str, dict] = {}
        for threshold in THRESHOLDS:
            simulated_scores = {
                key: score for key, (score, _shared) in sim_links[name][threshold].items()
            }
            by_threshold[str(threshold)] = {
                "links": len(simulated_scores),
                "avg_sim": _avg(simulated_scores.values()),
                "snapshot_diff": _diff(current_scores, simulated_scores),
                "stoplist_only_current_links": _fate_block(name, threshold, stoplist_only_keys),
                "dla_alone_current_links": _fate_block(name, threshold, dla_alone_keys),
            }
        tokens_removed_from_cards = Counter()
        for cid, kws in baseline_kw.items():
            tokens_removed_from_cards.update(kws - schemes[name][cid])
        scheme_reports[name] = {
            "avg_score_all_pairs": _avg(all_pair_scores[name]),
            "by_threshold": by_threshold,
            "tokens_removed_from_cards_top": [
                {"token": token, "cards": count}
                for token, count in tokens_removed_from_cards.most_common(20)
            ],
            "tokens_dropped_from_current_shared_keywords": _dropped_from_table(filter_tokens[name]),
        }

    content_token_df = {
        token: {
            "df": round(df.get(token, 0.0), 4),
            "cards": int(round(df.get(token, 0.0) * n_cards)),
            "dropped_by": [f"df_{frac:.2f}" for frac in DF_FRACTIONS if token in df_drop[frac]],
        }
        for token in CONTENT_TOKENS_TO_WATCH
    }

    evidence_in_table = {token: current_token_counts.get(token, 0) for token in EVIDENCE_TOKENS}

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime_s": round(time.monotonic() - started, 1),
        "settings": {
            "cross_channel_link_threshold": settings.cross_channel_link_threshold,
            "jaccard_weight": JACCARD_WEIGHT,
            "cosine_weight": COSINE_WEIGHT,
            "primary_threshold": PRIMARY_THRESHOLD,
            "sensitivity_thresholds": list(THRESHOLDS),
        },
        "corpus": {
            "cards": n_cards,
            "channels": len(channels),
            "channel_ids": channels,
            "cross_channel_pairs": pair_count,
            "pairs_with_cosine": pairs_with_cosine,
            "pairs_jaccard_only": pair_count - pairs_with_cosine,
        },
        "resolve_stats": {
            "topic": emb_stats.topic,
            "anchor_fallback": emb_stats.anchor_fallback,
            "missing": emb_stats.missing,
        },
        "current_prod_links": {
            "count": len(current_scores),
            "avg_score": _avg(current_scores.values()),
            "min_score": round(min(current_scores.values()), 4) if current_scores else 0.0,
            "evidence_tokens_in_shared_keywords": evidence_in_table,
            "dla_alone": len(dla_alone_keys),
            "stoplist_only_shared": len(stoplist_only_keys),
            "top_shared_keywords": [
                {"token": token, "links": count}
                for token, count in current_token_counts.most_common(25)
            ],
        },
        "stoplist": sorted(STOPLIST),
        "df": {
            "n_cards": n_cards,
            "tokens_above": {f"{frac:.2f}": len(df_drop[frac]) for frac in DF_FRACTIONS},
            "content_tokens": content_token_df,
            "top_df": [
                {"token": token, "df": round(freq, 4), "cards": int(round(freq * n_cards))}
                for token, freq in sorted(df.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
            ],
        },
        "schemes": scheme_reports,
    }


def main() -> None:
    import asyncio

    result = asyncio.run(run_simulation())
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
