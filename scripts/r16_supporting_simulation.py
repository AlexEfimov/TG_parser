#!/usr/bin/env python3
"""
R16 / BUG-105 read-only what-if: supporting-item selection under candidate configs.

Counterfactual for ``_find_supporting_items_programmatic`` (bundle supporting) and
``assign_documents_to_topics`` (Phase 1) on the CURRENT topic cards of each live
channel. Base = current product code recomputed on current cards — candidates are
compared against that, not against stored bundles (stored bundles are a mix of
``mean`` and ``topk_denom`` builds; START_PROMPT R16 §1 / §3).

Scoring is the PRODUCT code, called — not copied:
  - ``TopicizationPipelineImpl._tokenize_topic_card`` / ``_tokenize_document``;
  - ``TopicizationPipelineImpl._compute_match_score(..., aggregation=, topk=)``.
A stoplist / DF filter is modelled as a set filter on the product tokenizer
output. That is algebraically identical to a stoplist inside ``_tokenize``:
``(T(text) - S) - (strong - S) == (T(text) - strong) - S``, and the substring
fallback then sees the filtered sets exactly as the product would. Only the
threshold comparison, sort and cap (≈10 lines) are re-implemented, and a
baseline guard checks them against the product functions on real data.

Pairs that the product provably scores 0 (no exact and no substring-fallback
overlap, decided by a channel-level substring index built on the base token
sets — a superset of every filtered variant) are skipped; every non-zero score
comes from the product call.

Read-only: own engine with ``default_transaction_read_only=on`` in
``server_settings`` (asyncpg ignores PGOPTIONS); the value is checked on start.
No LLM, embeddings or Telegram calls. Output: JSONL on stdout, progress on stderr.

Usage (prod — scripts/ is not in the image; see CLAUDE.md «Прод»):
  git archive <SHA>:scripts r16_supporting_simulation.py | ssh prod 'docker cp - tg_parser:/tmp/'
  ssh prod 'docker exec tg_parser timeout 1500 nice python -B /tmp/r16_supporting_simulation.py \\
      --channel Lab4health --configs base'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import resource
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Word lists (data, not product code)
# ---------------------------------------------------------------------------

# R6 seed — identical to KEYWORD_STOPLIST in analytics_service (BUG-104).
R6_STOPLIST = frozenset(
    """
    для при как его её их это этой этот или чем что чтобы также
    the and for with from that this are was were
    """.split()
)

# Additions from the 2026-08-31 audit (§1 p. 1) and START_PROMPT R16 §1.
AUDIT_ADDITIONS = frozenset("между через после более если когда только свои весь".split())

STOPLIST_LEVELS = ("none", "r6", "r6a", "r6ax")

SAMPLE_CHANNELS_DEFAULT = (
    "andre_dataist",
    "aiinsideteam",
    "Lab4health",
    "profendocrinologist",
    "mediamedics",
)

DISCOVER_COST_USD = 0.85  # BUG-108: ~290k Sonnet input tokens per Phase 2 call
MIN_FALLBACK_LEN = 5  # product substring fallback: len(kw) >= 5 and len(dt) >= 5


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimConfig:
    """One candidate supporting configuration."""

    name: str
    stop: str = "none"  # none | r6 | r6a | r6ax
    cut: str = "lt"  # lt = product (`score < thr` rejected) | le (`score <= thr` rejected)
    agg: str = "topk_denom"  # supporting aggregation: topk_denom | mean
    thr: float = 0.10
    df: float | None = None  # drop topic keywords with in-channel df > df

    @property
    def variant(self) -> tuple[str, float | None]:
        """Token-filter variant: everything that changes the token sets."""
        return (self.stop, self.df)


STAGE1: tuple[SimConfig, ...] = (
    SimConfig("base"),
    SimConfig("stop_r6", stop="r6"),
    SimConfig("stop_r6a", stop="r6a"),
    SimConfig("stop_r6ax", stop="r6ax"),
    SimConfig("cut_le", cut="le"),
    SimConfig("agg_mean", agg="mean"),
    SimConfig("thr_015", thr=0.15),
    SimConfig("thr_020", thr=0.20),
    SimConfig("df_15", df=0.15),
    SimConfig("df_25", df=0.25),
    SimConfig("df_40", df=0.40),
)
_BUILTIN = {c.name: c for c in STAGE1}


def parse_config(spec: str) -> SimConfig:
    """``base`` / built-in name, or ``name:stop=r6a,cut=le,agg=mean,thr=0.15,df=0.25``."""
    spec = spec.strip()
    if spec in _BUILTIN:
        return _BUILTIN[spec]
    if ":" not in spec:
        raise ValueError(f"unknown config {spec!r}; built-ins: {sorted(_BUILTIN)}")
    name, _, body = spec.partition(":")
    kwargs: dict[str, Any] = {}
    for part in filter(None, body.split(",")):
        key, _, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if key == "stop":
            if value not in STOPLIST_LEVELS:
                raise ValueError(f"stop must be one of {STOPLIST_LEVELS}")
            kwargs["stop"] = value
        elif key == "cut":
            if value not in ("lt", "le"):
                raise ValueError("cut must be lt or le")
            kwargs["cut"] = value
        elif key == "agg":
            if value not in ("topk_denom", "mean"):
                raise ValueError("agg must be topk_denom or mean")
            kwargs["agg"] = value
        elif key == "thr":
            kwargs["thr"] = float(value)
        elif key == "df":
            kwargs["df"] = None if value in ("", "none") else float(value)
        else:
            raise ValueError(f"unknown config key {key!r}")
    return SimConfig(name=name.strip(), **kwargs)


def parse_configs(arg: str) -> list[SimConfig]:
    out: list[SimConfig] = []
    for spec in arg.split(";"):
        spec = spec.strip()
        if not spec:
            continue
        if spec == "stage1":
            out.extend(STAGE1)
        else:
            out.append(parse_config(spec))
    names = [c.name for c in out]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate config names: {names}")
    if "base" not in names:
        out.insert(0, _BUILTIN["base"])
    return out


def stopset(level: str, extra: frozenset[str]) -> frozenset[str]:
    if level == "none":
        return frozenset()
    if level == "r6":
        return R6_STOPLIST
    if level == "r6a":
        return R6_STOPLIST | AUDIT_ADDITIONS
    if level == "r6ax":
        return R6_STOPLIST | AUDIT_ADDITIONS | extra
    raise ValueError(level)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB)
# ---------------------------------------------------------------------------


def filter_doc_tokens(
    strong: set[str], weak: set[str], stop: frozenset[str]
) -> tuple[set[str], set[str]]:
    """Apply a stoplist to the product tokenizer output (== stoplist inside _tokenize)."""
    if not stop:
        return strong, weak
    return strong - stop, weak - stop


def passes(score: float, thr: float, cut: str) -> bool:
    """Product keeps ``not (score < thr)``; ``le`` keeps ``not (score <= thr)``."""
    if cut == "lt":
        return not (score < thr)
    if cut == "le":
        return not (score <= thr)
    raise ValueError(cut)


def select_supporting(
    scored: Sequence[tuple[str, float]], thr: float, cut: str, cap: int
) -> list[tuple[str, float]]:
    """Mirror ``_find_supporting_items_programmatic`` selection.

    ``scored`` is ``(source_ref, score)`` in document iteration order (anchors
    already excluded). Stable sort by ``-score`` then slice — exactly the product.
    """
    kept = [(ref, s) for ref, s in scored if passes(s, thr, cut)]
    kept.sort(key=lambda x: -(x[1] or 0))
    return kept[:cap]


def discover_calls_for_backlog(n_docs: int, feed_cap: int, batch_size: int) -> dict[str, int]:
    """BUG-075 reconcile drain: ``feed_cap`` docs per channel per tick, one call per batch."""
    if n_docs <= 0:
        return {"ticks": 0, "calls": 0, "max_calls_per_tick": 0}
    feed_cap = max(1, feed_cap)
    ticks = math.ceil(n_docs / feed_cap)
    calls = 0
    max_per_tick = 0
    remaining = n_docs
    for _ in range(ticks):
        fed = min(remaining, feed_cap)
        c = math.ceil(fed / batch_size)
        calls += c
        max_per_tick = max(max_per_tick, c)
        remaining -= fed
    return {"ticks": ticks, "calls": calls, "max_calls_per_tick": max_per_tick}


def df_drop_set(doc_token_sets: Iterable[set[str]], n_docs: int, frac: float) -> frozenset[str]:
    """Tokens present in more than ``frac`` of the channel's documents."""
    if n_docs <= 0:
        return frozenset()
    counts: Counter[str] = Counter()
    for toks in doc_token_sets:
        counts.update(toks)
    return frozenset(t for t, c in counts.items() if c / n_docs > frac)


def substring_related(
    kw_vocab: Iterable[str], doc_vocab: Iterable[str], min_len: int = MIN_FALLBACK_LEN
) -> dict[str, set[str]]:
    """``doc_token -> {kw}`` for every (kw, dt) pair the product fallback can hit.

    Fallback condition: ``len(kw) >= 5 and len(dt) >= 5 and (kw in dt or dt in kw)``.
    Built via substring enumeration (O(V·L²)), not pairwise.
    """
    kws = {k for k in kw_vocab if len(k) >= min_len}
    dts = {d for d in doc_vocab if len(d) >= min_len}
    related: dict[str, set[str]] = defaultdict(set)

    def _subs(word: str) -> set[str]:
        n = len(word)
        return {word[i:j] for i in range(n) for j in range(i + min_len, n + 1)}

    for dt in dts:
        for sub in _subs(dt):  # kw in dt
            if sub in kws:
                related[dt].add(sub)
    for kw in kws:
        for sub in _subs(kw):  # dt in kw
            if sub in dts:
                related[sub].add(kw)
    return related


def median(values: Sequence[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def check_read_only(value: str | None) -> None:
    if (value or "").strip().lower() != "on":
        raise SystemExit(
            f"r16: default_transaction_read_only={value!r}, expected 'on' — refusing to run"
        )


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _log(msg: str) -> None:
    print(f"r16 {datetime.now(UTC).strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Channel simulation
# ---------------------------------------------------------------------------


@dataclass
class ChannelData:
    channel_id: str
    docs: list  # ProcessedDocument, DB order (ORDER BY source_ref)
    cards: list  # TopicCard, DB order (ORDER BY updated_at DESC)
    bundles: list  # stored TopicBundle
    attempted: set[str]


def _stored_stats(data: ChannelData, cap: int) -> dict[str, Any]:
    doc_refs = {d.source_ref for d in data.docs}
    items = [len(b.items) for b in data.bundles]
    sat = sum(
        1 for b in data.bundles if sum(1 for it in b.items if it.role.value == "supporting") >= cap
    )
    covered = {it.source_ref for b in data.bundles for it in b.items} & doc_refs
    return {
        "topics": len(data.bundles),
        "items_sum": sum(items),
        "median_items": median(items),
        "sat_cap": sat,
        "topics_per_doc": round(sum(items) / len(data.docs), 2) if data.docs else 0.0,
        "coverage_pct": round(100.0 * len(covered) / len(data.docs), 2) if data.docs else 0.0,
    }


def simulate_channel(
    data: ChannelData,
    configs: list[SimConfig],
    *,
    extra_stop: frozenset[str],
    cap: int,
    topk: int,
    phase1_thr: float,
    batch_size: int,
    feed_cap: int,
    resummarize_trigger: int,
    phase1_days: int,
    now: datetime,
    sample_topics: int,
    sample_configs: set[str],
) -> dict[str, Any]:
    from tg_parser.processing.topicization import TopicizationPipelineImpl as Impl

    t0 = time.monotonic()
    docs = data.docs
    n_docs = len(docs)
    refs = [d.source_ref for d in docs]
    ref_idx = {r: i for i, r in enumerate(refs)}
    ref_set = set(refs)
    # product skips supporting candidates whose source_ref is not 4-part
    valid = [len(r.split(":")) == 4 for r in refs]

    # Product tokenization, once.
    base_doc = [Impl._tokenize_document(d) for d in docs]  # (strong, weak)
    base_kw = [Impl._tokenize_topic_card(c) for c in data.cards]
    anchors = [{a.anchor_ref for a in c.anchors} for c in data.cards]
    base_n = [len(k) for k in base_kw]

    # Substring index on BASE sets (superset of every filtered variant).
    doc_vocab: set[str] = set()
    for s, w in base_doc:
        doc_vocab |= s
        doc_vocab |= w
    kw_vocab: set[str] = set().union(*base_kw) if base_kw else set()
    related = substring_related(kw_vocab, doc_vocab)
    reach = []  # tokens a doc can hit: own tokens ∪ fallback-related kws
    for s, w in base_doc:
        r = set(s) | set(w)
        for dt in s | w:
            if dt in related:
                r |= related[dt]
        reach.append(r)

    base_union = [s | w for s, w in base_doc]
    df_cache: dict[float, frozenset[str]] = {}

    def _df(frac: float) -> frozenset[str]:
        if frac not in df_cache:
            df_cache[frac] = df_drop_set(base_union, n_docs, frac)
        return df_cache[frac]

    # Stored bundle facts.
    stored_cov = {it.source_ref for b in data.bundles for it in b.items}
    llm_refs = {
        it.source_ref
        for b in data.bundles
        for it in b.items
        if (it.justification or "").startswith("incremental llm assign")
        and it.source_ref in ref_idx
    }
    counter_now = {
        c.id: int(getattr(c, "new_items_since_last_summary", 0) or 0) for c in data.cards
    }

    # Phase-1 window (door 1): processed_at within the window, grouped by hour.
    since = now - timedelta(days=phase1_days)
    window_idx = [
        i for i, d in enumerate(docs) if d.processed_at and d.processed_at.astimezone(UTC) >= since
    ]
    tick_of = {i: docs[i].processed_at.astimezone(UTC).strftime("%Y-%m-%dT%H") for i in window_idx}

    # Composition / frequency stats (base variant only).
    comp: Counter[str] = Counter(
        dict.fromkeys(
            (
                "items",
                "score_eq_010",
                "only_service_words",
                "fallback_only",
                "single_hit",
                "single_weak_hit",
            ),
            0,
        )
    )
    single_hit_tokens: Counter[str] = Counter()
    service_words = R6_STOPLIST | AUDIT_ADDITIONS

    variants: dict[tuple[str, float | None], list[SimConfig]] = defaultdict(list)
    for cfg in configs:
        variants[cfg.variant].append(cfg)

    results: dict[str, Any] = {}
    phase1_best: dict[tuple[str, float | None], list[tuple[float, int | None]]] = {}
    pair_calls = 0
    pair_skipped = 0
    samples_out: dict[str, Any] = {}

    for variant, vcfgs in variants.items():
        stop_level, df_frac = variant
        stop = stopset(stop_level, extra_stop)
        drop = _df(df_frac) if df_frac is not None else frozenset()
        v_doc = [filter_doc_tokens(s, w, stop) for s, w in base_doc]
        v_kw = [(k - stop) - drop for k in base_kw]
        need_mean = any(c.agg == "mean" for c in vcfgs)

        # scores[agg][topic] = list[(doc_idx, score)] with score > 0, doc order
        scores: dict[str, list[list[tuple[int, float]]]] = {"topk_denom": [], "mean": []}
        # Phase 1 argmax (topk_denom), strict '>' in card order — as the product.
        best_list: list[tuple[float, int | None]] = [(0.0, None)] * n_docs

        for ti, kws in enumerate(v_kw):
            row_topk: list[tuple[int, float]] = []
            row_mean: list[tuple[int, float]] = []
            if kws:
                for di in range(n_docs):
                    if kws.isdisjoint(reach[di]):
                        pair_skipped += 1
                        continue
                    strong, weak = v_doc[di]
                    pair_calls += 1
                    score, _hits = Impl._compute_match_score(
                        kws, strong, weak, aggregation="topk_denom", topk=topk
                    )
                    if score > 0:
                        row_topk.append((di, score))
                        if score > best_list[di][0]:
                            best_list[di] = (score, ti)
                    if need_mean and score > 0:
                        if len(kws) > topk:
                            ms, _ = Impl._compute_match_score(
                                kws, strong, weak, aggregation="mean", topk=topk
                            )
                            pair_calls += 1
                        else:
                            ms = score  # byte-identical for n <= K
                        if ms > 0:
                            row_mean.append((di, ms))
            scores["topk_denom"].append(row_topk)
            scores["mean"].append(row_mean)
        phase1_best[variant] = best_list

        n_shift = sum(1 for ti, k in enumerate(v_kw) if base_n[ti] > topk and len(k) <= topk)
        n_empty = sum(1 for ti, k in enumerate(v_kw) if base_kw[ti] and not k)

        for cfg in vcfgs:
            rows = scores[cfg.agg]
            bundles: list[list[tuple[str, float]]] = []
            groups = {"le3": defaultdict(list), "gt3": defaultdict(list)}
            covered_a: set[str] = set()
            membership = Counter()
            for ti in range(len(data.cards)):
                anc = anchors[ti]
                scored = [(refs[di], s) for di, s in rows[ti] if refs[di] not in anc and valid[di]]
                sup = select_supporting(scored, cfg.thr, cfg.cut, cap) if v_kw[ti] else []
                # product: supporting only when len(documents) > len(anchor_refs)
                if not (n_docs > len(anc)):
                    sup = []
                bundles.append(sup)
                items = len(anc) + len(sup)
                g = "le3" if base_n[ti] <= topk else "gt3"
                groups[g]["items"].append(items)
                groups[g]["sat"].append(1 if len(sup) >= cap else 0)
                members = (anc & ref_set) | {r for r, _ in sup}
                covered_a |= members
                for r in members:
                    membership[r] += 1

            covered_b = covered_a | llm_refs
            uncovered_b = [r for r in refs if r not in covered_b]
            was_covered = [r for r in uncovered_b if r in stored_cov]
            p1 = phase1_best[variant]
            p1_thr = cfg.thr  # product shares MIN_SUPPORTING_SCORE between both paths

            def _assigned(r: str, thr: float, _p1=p1) -> bool:
                s, t = _p1[ref_idx[r]]
                return t is not None and s >= thr

            assignable_shared = [r for r in uncovered_b if _assigned(r, p1_thr)]
            assignable_010 = [r for r in uncovered_b if _assigned(r, phase1_thr)]
            to_discover = [
                r for r in uncovered_b if not _assigned(r, p1_thr) and r not in data.attempted
            ]
            f5c_add = Counter(data.cards[p1[ref_idx[r]][1]].id for r in assignable_shared)
            f5c_cross = sum(
                1
                for tid, add in f5c_add.items()
                if counter_now.get(tid, 0) < resummarize_trigger <= counter_now.get(tid, 0) + add
            )

            # Door 1 — Phase 1 on the recent window, at shared threshold and at 0.10.
            def _door1(thr: float, _p1=p1) -> dict[str, int]:
                miss_by_tick: Counter[str] = Counter()
                unassigned = 0
                for i in window_idx:
                    s, t = _p1[i]
                    if not (t is not None and s >= thr):
                        unassigned += 1
                        miss_by_tick[tick_of[i]] += 1
                calls = sum(math.ceil(n / batch_size) for n in miss_by_tick.values())
                return {
                    "docs": len(window_idx),
                    "unassigned": unassigned,
                    "ticks_with_miss": len(miss_by_tick),
                    "discover_calls": calls,
                }

            def _grp(g: dict) -> dict[str, Any]:
                return {
                    "topics": len(g["items"]),
                    "items_sum": sum(g["items"]),
                    "median_items": median(g["items"]),
                    "sat_cap": sum(g["sat"]),
                }

            all_items = groups["le3"]["items"] + groups["gt3"]["items"]
            results[cfg.name] = {
                "config": asdict(cfg),
                "all": {
                    "topics": len(all_items),
                    "items_sum": sum(all_items),
                    "median_items": median(all_items),
                    "sat_cap": sum(groups["le3"]["sat"]) + sum(groups["gt3"]["sat"]),
                    "topics_per_doc": round(sum(all_items) / n_docs, 2) if n_docs else 0.0,
                    "mean_topics_per_covered_doc": round(
                        sum(membership.values()) / len(membership), 2
                    )
                    if membership
                    else 0.0,
                },
                "n_le3": _grp(groups["le3"]),
                "n_gt3": _grp(groups["gt3"]),
                "topics_moved_gt3_to_le3": n_shift,
                "topics_lost_all_keywords": n_empty,
                "door2": {
                    "uncovered_kw_only": n_docs - len(covered_a),
                    "uncovered_with_llm_kept": len(uncovered_b),
                    "uncovered_previously_covered": len(was_covered),
                    "phase1_assignable_shared_thr": len(assignable_shared),
                    "phase1_assignable_thr_010": len(assignable_010),
                    "to_discover_minus_attempted": len(to_discover),
                    "discover_backlog": discover_calls_for_backlog(
                        len(to_discover), feed_cap, batch_size
                    ),
                    "f5c_topics_touched": len(f5c_add),
                    "f5c_topics_crossing_trigger": f5c_cross,
                },
                "door1_shared_thr": _door1(p1_thr),
                "door1_thr_010": _door1(phase1_thr),
            }

            # Bundles kept for base (composition) and sample configs; stripped before emit.
            if cfg.name == "base" or (sample_topics and cfg.name in sample_configs):
                results[cfg.name]["_bundles"] = bundles

        del scores

    # Composition of base supporting: hits re-derived by the product call, only
    # for selected items (≤ cap per topic) — no per-pair hit storage.
    base_b_all = results["base"]["_bundles"]
    for ti, sup in enumerate(base_b_all):
        for ref, s in sup:
            di = ref_idx[ref]
            strong, weak = base_doc[di]
            _, hits = Impl._compute_match_score(
                base_kw[ti], strong, weak, aggregation="topk_denom", topk=topk
            )
            comp["items"] += 1
            if s == 0.1:
                comp["score_eq_010"] += 1
            if hits and hits <= service_words:
                comp["only_service_words"] += 1
            if not (hits & (strong | weak)):
                comp["fallback_only"] += 1
            if len(hits) == 1:
                comp["single_hit"] += 1
                (h,) = tuple(hits)
                single_hit_tokens[h] += 1
                if h not in strong:
                    comp["single_weak_hit"] += 1

    # Samples (largest base bundle, median, smallest non-empty; n<=3 preferred for the 3rd).
    if sample_topics:
        base_b = results["base"].get("_bundles") or []
        order = sorted(range(len(base_b)), key=lambda t: -len(base_b[t]))
        picks: list[int] = []
        if order:
            picks.append(order[0])
            picks.append(order[len(order) // 2])
            le3 = [t for t in order if base_n[t] <= topk and t not in picks]
            picks.append(le3[0] if le3 else order[-1])
        picks = list(dict.fromkeys(picks))[:sample_topics]

        def _doc_brief(ref: str, s: float, ti: int, cfg: SimConfig) -> dict[str, Any]:
            di = ref_idx[ref]
            stop = stopset(cfg.stop, extra_stop)
            drop = _df(cfg.df) if cfg.df is not None else frozenset()
            strong, weak = filter_doc_tokens(*base_doc[di], stop)
            kws = (base_kw[ti] - stop) - drop
            _, hits = Impl._compute_match_score(kws, strong, weak, aggregation=cfg.agg, topk=topk)
            return {
                "ref": ref,
                "score": s,
                "hits": sorted(hits)[:8],
                "summary": (docs[di].summary or "")[:120],
            }

        base_cfg = _BUILTIN["base"]
        for cname in sorted(sample_configs):
            if cname == "base" or cname not in results or "_bundles" not in results[cname]:
                continue
            cfg = next(c for c in configs if c.name == cname)
            cb = results[cname]["_bundles"]
            topics_out = []
            for ti in picks:
                b_refs = dict(base_b[ti])
                c_refs = dict(cb[ti])
                left = [r for r in b_refs if r not in c_refs]
                stayed = [r for r in c_refs if r in b_refs]
                topics_out.append(
                    {
                        "topic_id": data.cards[ti].id,
                        "title": data.cards[ti].title[:80],
                        "n_keywords": base_n[ti],
                        "base_supporting": len(b_refs),
                        "cfg_supporting": len(c_refs),
                        "left_examples": [_doc_brief(r, b_refs[r], ti, base_cfg) for r in left[:5]],
                        "stayed_examples": [_doc_brief(r, c_refs[r], ti, cfg) for r in stayed[-5:]],
                    }
                )
            samples_out[cname] = topics_out

    for r in results.values():
        r.pop("_bundles", None)

    return {
        "type": "channel",
        "channel_id": data.channel_id,
        "docs": n_docs,
        "cards": len(data.cards),
        "cards_n_le3": sum(1 for n in base_n if n <= topk),
        "cards_without_keywords": sum(1 for n in base_n if n == 0),
        "phase1_window_docs": len(window_idx),
        "discover_attempted_markers": len(data.attempted),
        "llm_assign_refs_kept": len(llm_refs),
        "stored": _stored_stats(data, cap),
        "base_composition": dict(comp),
        "single_hit_tokens_top": single_hit_tokens.most_common(40),
        "df_top_keywords": _df_top(base_kw, base_union, n_docs),
        "configs": results,
        "samples": samples_out,
        "pair_calls": pair_calls,
        "pair_skipped_provable_zero": pair_skipped,
        "runtime_s": round(time.monotonic() - t0, 1),
    }


def _df_top(base_kw: list[set[str]], base_union: list[set[str]], n_docs: int) -> list:
    """Top topic keywords by in-channel document frequency (candidates for review)."""
    if not n_docs:
        return []
    kw_vocab: set[str] = set().union(*base_kw) if base_kw else set()
    counts: Counter[str] = Counter()
    for toks in base_union:
        counts.update(toks & kw_vocab)
    return [(t, round(c / n_docs, 3)) for t, c in counts.most_common(30)]


# ---------------------------------------------------------------------------
# Baseline guard: the re-implemented selection must equal the product.
# ---------------------------------------------------------------------------


async def baseline_guard(
    pipeline,
    data: ChannelData,
    *,
    guard_topics: int,
    guard_docs: int,
    cap: int,
    topk: int,
    min_score: float,
) -> dict[str, Any]:
    from tg_parser.processing.topicization import TopicizationPipelineImpl as Impl

    docs = data.docs
    cards = data.cards
    if guard_topics <= 0 or guard_topics >= len(cards):
        picked = list(range(len(cards)))
    else:
        step = len(cards) / guard_topics
        picked = sorted({int(i * step) for i in range(guard_topics)})

    sup_mismatch = []
    for ti in picked:
        card = cards[ti]
        anc = {a.anchor_ref for a in card.anchors}
        product = pipeline._find_supporting_items_programmatic(
            topic_card=card, anchor_refs=anc, documents=docs
        )
        prod = [(it.source_ref, it.score) for it in product]
        kws = Impl._tokenize_topic_card(card)
        scored = []
        if kws:
            for d in docs:
                if d.source_ref in anc:
                    continue
                parts = d.source_ref.split(":")
                if len(parts) != 4:
                    continue
                s, w = Impl._tokenize_document(d)
                score, _ = Impl._compute_match_score(kws, s, w, aggregation="topk_denom", topk=topk)
                scored.append((d.source_ref, score))
        mine = select_supporting(scored, min_score, "lt", cap) if kws else []
        if prod != mine:
            sup_mismatch.append(card.id)

    sample = docs[-guard_docs:] if guard_docs > 0 else docs
    assignments, unassigned = await pipeline.assign_documents_to_topics(
        new_docs=sample, channel_id=data.channel_id
    )
    prod_assign = {a.source_ref: (a.topic_id, a.score) for a in assignments}
    kw_sets = [(c, Impl._tokenize_topic_card(c)) for c in cards]
    kw_sets = [(c, k) for c, k in kw_sets if k]
    p1_mismatch = []
    for d in sample:
        s, w = Impl._tokenize_document(d)
        best, bid = 0.0, None
        for c, k in kw_sets:
            sc, _ = Impl._compute_match_score(k, s, w, aggregation="topk_denom", topk=topk)
            if sc > best:
                best, bid = sc, c.id
        mine = (bid, best) if (bid is not None and best >= min_score) else None
        if prod_assign.get(d.source_ref) != mine:
            p1_mismatch.append(d.source_ref)

    refs = [d.source_ref for d in docs]
    return {
        "type": "guard",
        "channel_id": data.channel_id,
        "supporting_topics_checked": len(picked),
        "supporting_mismatch": sup_mismatch[:20],
        "phase1_docs_checked": len(sample),
        "phase1_mismatch": p1_mismatch[:20],
        "db_order_equals_python_sort": refs == sorted(refs),
        "ok": not sup_mismatch and not p1_mismatch,
    }


# ---------------------------------------------------------------------------
# DB (read-only)
# ---------------------------------------------------------------------------


def _make_engine(settings):
    from sqlalchemy.ext.asyncio import create_async_engine

    from tg_parser.storage.engine_factory import create_postgres_engine_config

    cfg = create_postgres_engine_config(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    return create_async_engine(
        cfg.url,
        pool_size=1,
        max_overflow=0,
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )


async def _load_channel(session, channel_id: str) -> ChannelData:
    from sqlalchemy import text

    from tg_parser.services.topicization_service import _DISCOVER_ATTEMPTED_PREFIX
    from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
    from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

    docs = await SAProcessedDocumentRepo(session).list_by_channel(channel_id)
    cards = await SATopicCardRepo(session).list_by_channel(channel_id)
    bundles = await SATopicBundleRepo(session).list_by_channel(channel_id)
    rows = await session.execute(
        text(
            "SELECT source_ref FROM processing_failures "
            "WHERE channel_id = :ch AND source_ref LIKE :prefix"
        ),
        {"ch": channel_id, "prefix": _DISCOVER_ATTEMPTED_PREFIX + "%"},
    )
    attempted = {r[0][len(_DISCOVER_ATTEMPTED_PREFIX) :] for r in rows.fetchall()}
    # keep only bundles whose first channel is this one (LIKE pattern is loose)
    bundles = [b for b in bundles if (b.channels or [channel_id])[0] == channel_id]
    return ChannelData(channel_id, docs, cards, bundles, attempted)


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from tg_parser.config import settings
    from tg_parser.processing import topicization as topi
    from tg_parser.processing.topicization import TopicizationPipelineImpl
    from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
    from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

    configs = parse_configs(args.configs)
    extra = frozenset(
        w.strip().lower() for w in (args.extra_stopwords or "").split(",") if w.strip()
    )
    if any(c.stop == "r6ax" for c in configs) and not extra:
        _log("r6ax configs requested without --extra-stopwords — dropping them")
        configs = [c for c in configs if c.stop != "r6ax"]
    sample_configs = {s.strip() for s in (args.sample_configs or "").split(",") if s.strip()}

    engine = _make_engine(settings)
    started = time.monotonic()
    now = datetime.now(UTC)
    try:
        async with AsyncSession(engine) as session:
            ro = (await session.execute(text("SHOW default_transaction_read_only"))).scalar()
            _log(f"SHOW default_transaction_read_only = {ro}")
            check_read_only(ro)

            live = [
                r[0]
                for r in (
                    await session.execute(
                        text(
                            "SELECT DISTINCT channel_id FROM sources "
                            "WHERE deleted_at IS NULL ORDER BY channel_id"
                        )
                    )
                ).fetchall()
            ]
            channels = args.channel or live
            channels = [c for c in channels if c not in set(args.exclude_channel or [])]
            unknown = [c for c in channels if c not in live]

            meta = {
                "type": "meta",
                "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "default_transaction_read_only": ro,
                "channels": channels,
                "unknown_channels": unknown,
                "configs": [asdict(c) for c in configs],
                "extra_stopwords": sorted(extra),
                "stoplists": {
                    "r6": sorted(R6_STOPLIST),
                    "audit_additions": sorted(AUDIT_ADDITIONS),
                },
                "effective": {
                    "MIN_SUPPORTING_SCORE": topi.MIN_SUPPORTING_SCORE,
                    "MAX_SUPPORTING_ITEMS": topi.MAX_SUPPORTING_ITEMS,
                    "ASSIGN_KEYWORD_AGGREGATION": topi.ASSIGN_KEYWORD_AGGREGATION,
                    "ASSIGN_KEYWORD_TOPK": topi.ASSIGN_KEYWORD_TOPK,
                    "MIN_TOKEN_LENGTH": topi.MIN_TOKEN_LENGTH,
                    "TEXT_CLEAN_MATCH_CHARS": topi.TEXT_CLEAN_MATCH_CHARS,
                    "topicization_batch_size": settings.topicization_batch_size,
                    "topicization_reconcile_max_docs": settings.topicization_reconcile_max_docs,
                    "resummarize_trigger_n": settings.resummarize_trigger_n,
                },
                "phase1_days": args.phase1_days,
                "mem_guard_mb": getattr(args, "mem_guard_mb", None),
            }
            _emit(meta)
            if topi.ASSIGN_KEYWORD_AGGREGATION != "topk_denom":
                _log("WARNING: product aggregation is not topk_denom — base differs from prompt")

            pipeline = TopicizationPipelineImpl(
                llm_client=None,
                processed_doc_repo=SAProcessedDocumentRepo(session),
                topic_card_repo=SATopicCardRepo(session),
                topic_bundle_repo=SATopicBundleRepo(session),
            )
            all_ok = True
            for ch in channels:
                if ch in unknown:
                    continue
                _log(f"{ch}: loading")
                data = await _load_channel(session, ch)
                _log(f"{ch}: {len(data.docs)} docs, {len(data.cards)} cards")
                if not data.docs or not data.cards:
                    _emit({"type": "channel", "channel_id": ch, "skipped": "no_docs_or_cards"})
                    continue
                guard = await baseline_guard(
                    pipeline,
                    data,
                    guard_topics=args.guard_topics,
                    guard_docs=args.guard_docs,
                    cap=topi.MAX_SUPPORTING_ITEMS,
                    topk=topi.ASSIGN_KEYWORD_TOPK,
                    min_score=topi.MIN_SUPPORTING_SCORE,
                )
                _emit(guard)
                if not guard["ok"]:
                    all_ok = False
                    _log(f"{ch}: BASELINE GUARD FAILED — stopping")
                    break
                _log(f"{ch}: guard ok; simulating {len(configs)} configs")
                res = simulate_channel(
                    data,
                    configs,
                    extra_stop=extra,
                    cap=topi.MAX_SUPPORTING_ITEMS,
                    topk=topi.ASSIGN_KEYWORD_TOPK,
                    phase1_thr=topi.MIN_SUPPORTING_SCORE,
                    batch_size=settings.topicization_batch_size,
                    feed_cap=settings.topicization_reconcile_max_docs,
                    resummarize_trigger=settings.resummarize_trigger_n,
                    phase1_days=args.phase1_days,
                    now=now,
                    sample_topics=args.samples if ch in args.sample_channels else 0,
                    sample_configs=sample_configs,
                )
                _emit(res)
                _log(
                    f"{ch}: done in {res['runtime_s']}s, product calls {res['pair_calls']}, "
                    f"skipped {res['pair_skipped_provable_zero']}, "
                    f"maxrss {_maxrss_mb()} MB"
                )
                del data
    finally:
        await engine.dispose()

    _emit(
        {
            "type": "summary",
            "runtime_s": round(time.monotonic() - started, 1),
            "baseline_guard_ok": all_ok,
            "maxrss_mb": _maxrss_mb(),
        }
    )
    return 0 if all_ok else 2


def _maxrss_mb() -> int:
    """Peak RSS in MB (ru_maxrss is KB on Linux, bytes on macOS)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss // (1024 * 1024) if sys.platform == "darwin" else rss // 1024


def set_memory_guard(max_mem_mb: int) -> int | None:
    """Cap the address space (soft RLIMIT_AS): the prod container has no memory
    limit, and an OOM would hit the whole host. Fail closed — a requested guard
    that cannot be set aborts the run; ``0`` explicitly disables it."""
    if max_mem_mb <= 0:
        return None
    limit = max_mem_mb * 1024 * 1024
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY and hard < limit:
        limit = hard
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    except (ValueError, OSError) as e:
        raise SystemExit(
            f"r16: cannot set RLIMIT_AS={max_mem_mb} MB ({e}); pass --max-mem-mb 0 to run unguarded"
        ) from e
    return limit // (1024 * 1024)


def _quiet_logging() -> None:
    """Keep stdout pure JSONL: product loggers are structlog, whose unconfigured
    default prints to stdout. Route everything to stderr at WARNING."""
    import structlog

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    for name in ("tg_parser", "sqlalchemy", "asyncpg"):
        logging.getLogger(name).setLevel(logging.WARNING)
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        cache_logger_on_first_use=False,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--channel", action="append", help="channel_id (repeatable); default: all live")
    p.add_argument("--exclude-channel", action="append")
    p.add_argument(
        "--configs",
        default="base",
        help="';'-separated: 'stage1', built-in names, or 'name:stop=..,cut=..,agg=..,thr=..,df=..'",
    )
    p.add_argument("--extra-stopwords", default="", help="comma-separated, for stop=r6ax")
    p.add_argument("--phase1-days", type=int, default=30)
    p.add_argument("--samples", type=int, default=3, help="topics per sample channel")
    p.add_argument(
        "--sample-channels",
        default=",".join(SAMPLE_CHANNELS_DEFAULT),
        type=lambda s: {x.strip() for x in s.split(",") if x.strip()},
    )
    p.add_argument("--sample-configs", default="", help="comma-separated config names")
    p.add_argument("--guard-topics", type=int, default=20, help="0 = all topics")
    p.add_argument("--guard-docs", type=int, default=200, help="0 = all docs")
    p.add_argument("--max-mem-mb", type=int, default=4096, help="RLIMIT_AS guard; 0 = off")
    args = p.parse_args(argv)

    args.mem_guard_mb = set_memory_guard(args.max_mem_mb)

    _quiet_logging()

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
