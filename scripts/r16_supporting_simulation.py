#!/usr/bin/env python3
"""
R16 / BUG-105 read-only what-if: supporting-item selection under candidate configs.

HISTORICAL (stage A, 2026-11-16..19). The product now selects supporting by
decision G (supporting K = 30, cut ``le``); this script's ``base`` stays the
PRE-R16 formula (Phase-1 K, cut ``lt``) so the §10 numbers remain reproducible:
the baseline guard calls the product with that formula explicitly
(``_find_supporting_items_programmatic(..., topk=<Phase-1 K>, cut="lt")``), and
config ``k30:k=30,cut=le`` equals the new product default (oracle test).

Counterfactual for ``_find_supporting_items_programmatic`` (bundle supporting) and
``assign_documents_to_topics`` (Phase 1) on the CURRENT topic cards of each live
channel. Base = the pre-R16 formula recomputed on current cards — candidates are
compared against that, not against stored bundles (stored bundles are a mix of
``mean`` and ``topk_denom`` builds; START_PROMPT R16 §1 / §3).

Scoring is the PRODUCT code, called — not copied:
  - ``TopicizationPipelineImpl._tokenize_topic_card`` / ``_tokenize_document``;
  - ``TopicizationPipelineImpl._compute_match_score(..., aggregation=, topk=)``.
A stoplist / DF filter is modelled as a set filter on the product tokenizer
output. That is algebraically identical to a stoplist inside ``_tokenize``:
``(T(text) - S) - (strong - S) == (T(text) - strong) - S``, and the substring
fallback then sees the filtered sets exactly as the product would. Only the
threshold comparison, sort and cap (≈10 lines) are re-implemented. A baseline
guard checks the published base outputs themselves (supporting per topic and
the Phase-1 argmax table) against ``_find_supporting_items_programmatic`` and
``assign_documents_to_topics`` on real data and withholds the channel result on
any mismatch.

Pairs that the product provably scores 0 (no exact and no substring-fallback
overlap, decided by a channel-level substring index built on the base token
sets — a superset of every filtered variant) are skipped; every non-zero pair
goes through the product call.

K axis (``k=`` in a config: supporting ``topk_denom`` with denominator
``min(n, K)``; Phase 1 and both discover doors stay on the product K). The
product rounds the aggregated score, so a K=5 score cannot be rescaled from the
K=3 one, and a direct product call per K per pair would cost ~+1 700 s per
filter variant on mediamedics. Deliberate, documented deviation from "call,
don't copy" (START_PROMPT R16 §2 p. 1): the weighted hit count ``W`` is
re-stated in ONE line (``_weighted_hits``) from the hits the product call
returned, and every score is the product ``_aggregate_assign_score`` +
``round(·, 3)`` of it. Guards: on EVERY non-zero pair the W path at the product
K must equal the product score; per K, a stratified sample of pairs with
n > product K — 6 strata, (n >= K or not) × (strong / weak / substring-fallback
hits), up to 50 pairs each per filter variant (the stage plan said 3 × 100; the
6 × 50 split keeps n < K pairs, whose denominator is n, in the sample too) — is
compared with a direct ``_compute_match_score(..., topk=K)``. Any mismatch, or a K with eligible pairs
but no product check, fails the baseline guard and withholds the channel.

Read-only: own engine with ``default_transaction_read_only=on`` in
``server_settings`` (asyncpg ignores PGOPTIONS); the value is checked on start.
No LLM, embeddings or Telegram calls. All output is JSONL on stdout (CLAUDE.md
«Прод»: вывод — только в stdout): results, ``{"type": "log"}`` progress lines
and product WARNING+ log records as JSON; ``--help`` is a ``{"type": "help"}``
line; CLI errors and any exception inside ``main()`` (argument parsing, memory
guard, logging setup, the run itself) become a ``{"type": "fatal"}`` line
(exit 3), and ``sys.stderr`` itself is replaced by a JSONL wrapper
(``{"type": "stderr"}``) for the whole of ``main()`` so stray Python-level
writes — the ``warnings`` module, third-party StreamHandlers — also land on
stdout. Out of reach by construction: C-level writes straight to fd 2 and
interpreter messages after ``main()`` returns (finalization).

Usage (prod — scripts/ is not in the image; see CLAUDE.md «Прод»):
  git archive <SHA>:scripts r16_supporting_simulation.py | ssh prod 'docker cp - tg_parser:/tmp/'
  ssh prod 'docker exec tg_parser timeout 1500 nice python -B /tmp/r16_supporting_simulation.py \\
      --channel Lab4health --configs base'
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import math
import random
import resource
import statistics
import sys
import time
import traceback
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

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
    cut: str = "lt"  # lt = pre-R16 product (`score < thr` rejected) | le (`score <= thr` rejected)
    agg: str = "topk_denom"  # supporting aggregation: topk_denom | mean
    thr: float = 0.10
    df: float | None = None  # drop topic keywords with in-channel df > df
    k: int | None = None  # topk_denom K for supporting; None = Phase-1 K (pre-R16 product)

    @property
    def variant(self) -> tuple[str, float | None]:
        """Token-filter variant: everything that changes the token sets."""
        return (self.stop, self.df)

    def score_key(self, product_k: int) -> tuple[str, int | None]:
        """Row key: ("topk_denom", K) or ("mean", None); k=None ≡ k=product K."""
        if self.agg == "mean":
            return ("mean", None)
        return ("topk_denom", self.k if self.k is not None else product_k)


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
    """``base`` / built-in name, or ``name:stop=r6a,cut=le,agg=mean,thr=0.15,df=0.25`` (or ``k=5`` with topk_denom)."""
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
        elif key == "k":
            k = int(value)
            if k < 1:
                raise ValueError("k must be an integer >= 1")
            kwargs["k"] = k
        else:
            raise ValueError(f"unknown config key {key!r}")
    if kwargs.get("agg") == "mean" and kwargs.get("k") is not None:
        raise ValueError("k applies to agg=topk_denom only (mean divides by n)")
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


def _weighted_hits(hits: set[str], strong: set[str]) -> float:
    """Weighted hit count, written exactly as the product computes it
    (``topicization.py`` ``_compute_match_score``: strong 1.0, the rest —
    including substring-fallback hits — 0.3). The ONLY scoring line this script
    re-states; every pair checks it against the product score (K = 3) and a
    stratified sample against a direct product call per K (see ``simulate_channel``)."""
    strong_hits = hits & strong
    weak_hits = hits - strong
    return len(strong_hits) + len(weak_hits) * 0.3


def k_score(weighted: float, n: int, k: int) -> float:
    """Product ``_aggregate_assign_score(topk_denom, topk=k)`` + the product's ``round(·, 3)``."""
    from tg_parser.processing.topicization import _aggregate_assign_score

    return round(_aggregate_assign_score(weighted, n, aggregation="topk_denom", topk=k), 3)


def k_checks_ok(kc: dict[str, Any]) -> bool:
    """K-axis self-checks: no derivation/product mismatch, and every K that had
    eligible pairs (n > product K, score > 0) got at least one product check."""
    if kc.get("derivation_mismatch", 0):
        return False
    for k, eligible in kc.get("eligible_pairs", {}).items():
        if kc.get("product_mismatch", {}).get(k, 0):
            return False
        if eligible and not kc.get("product_checked", {}).get(k, 0):
            return False
    return True


def select_supporting(
    scored: Sequence[tuple[str, float]], thr: float, cut: str, cap: int
) -> list[tuple[str, float]]:
    """Mirror ``_find_supporting_items_programmatic`` selection.

    ``scored`` is ``(source_ref, score)`` in document iteration order (anchors
    already excluded). Sort by ``(-score, source_ref)`` then slice — exactly the
    product since R16 (before it, a stable ``-score`` sort over documents in
    ``source_ref`` order — the DB order the prod runs used — which is the same).
    """
    kept = [(ref, s) for ref, s in scored if passes(s, thr, cut)]
    kept.sort(key=lambda x: (-(x[1] or 0), x[0]))
    return kept[:cap]


def reconcile_drain(
    miss_flags: Sequence[bool], feed_cap: int, batch_size: int, *, seed: int = 0
) -> dict[str, int]:
    """BUG-075 reconcile drain forecast for one channel.

    Product (``topicization_service`` reconcile): candidates = uncovered −
    discover_attempted; each tick feeds a uniform random sample of up to
    ``feed_cap`` candidates (``0`` = no cap, everything at once) to Phase 1; the
    Phase-1 misses inside that feed go to discover in batches of ``batch_size``
    (one LLM call per batch). Every fed doc leaves the candidate set (assigned →
    covered, missed → marked), so ticks consume disjoint feeds.

    ``miss_flags[i]`` — candidate ``i`` would be missed by Phase 1. Returns the
    expected-ish drain (seeded shuffle, mirrors the random sample) and an upper
    bound over every possible split of the misses between feeds
    (:func:`max_calls_over_feeds`).
    """
    n = len(miss_flags)
    misses = sum(1 for m in miss_flags if m)
    if n == 0:
        return {
            "candidates": 0,
            "misses": 0,
            "ticks": 0,
            "calls": 0,
            "max_calls_per_tick": 0,
            "calls_worst_case": 0,
        }
    cap = n if feed_cap <= 0 else feed_cap
    order = list(miss_flags)
    random.Random(seed).shuffle(order)
    calls = 0
    max_per_tick = 0
    for start in range(0, n, cap):
        m = sum(1 for f in order[start : start + cap] if f)
        c = math.ceil(m / batch_size)
        calls += c
        max_per_tick = max(max_per_tick, c)
    feeds = [min(cap, n - start) for start in range(0, n, cap)]
    worst = max_calls_over_feeds(feeds, misses, batch_size)
    return {
        "candidates": n,
        "misses": misses,
        "ticks": math.ceil(n / cap),
        "calls": calls,
        "max_calls_per_tick": max_per_tick,
        "calls_worst_case": worst,
    }


def max_calls_over_feeds(feeds: Sequence[int], misses: int, batch_size: int) -> int:
    """Max of ``sum(ceil(m_t / batch_size))`` over splits ``sum(m_t) = misses``, ``m_t <= feeds[t]``.

    Spreading maximises calls: the first miss in a feed costs one call, every
    further call in that feed costs ``batch_size`` more misses. Greedy by cost
    (1 first, then ``batch_size``) is optimal because the per-call costs are
    uniform within each step.
    """
    if misses <= 0 or not feeds:
        return 0
    m = [0] * len(feeds)
    remaining = misses
    calls = 0
    for t, cap in enumerate(feeds):  # one miss per feed first
        if remaining == 0:
            break
        if cap > 0:
            m[t] = 1
            remaining -= 1
            calls += 1
    progressed = True
    while remaining >= batch_size and progressed:  # then +batch_size per extra call
        progressed = False
        for t, cap in enumerate(feeds):
            if remaining < batch_size:
                break
            if m[t] and m[t] + batch_size <= cap:
                m[t] += batch_size
                remaining -= batch_size
                calls += 1
                progressed = True
    return calls


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


def _fatal(msg: str) -> NoReturn:
    """Report on stdout (JSONL) and exit non-zero — nothing goes to stderr."""
    _emit({"type": "fatal", "msg": msg})
    raise SystemExit(3)


def check_read_only(value: str | None) -> None:
    if (value or "").strip().lower() != "on":
        _fatal(f"default_transaction_read_only={value!r}, expected 'on' — refusing to run")


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _log(msg: str) -> None:
    _emit({"type": "log", "ts": datetime.now(UTC).strftime("%H:%M:%S"), "msg": msg})


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
    memberships = sum(len({it.source_ref for it in b.items} & doc_refs) for b in data.bundles)
    return {
        "topics": len(data.bundles),
        "items_sum": sum(items),
        "median_items": median(items),
        "sat_cap": sat,
        "topics_per_doc": round(memberships / len(data.docs), 2) if data.docs else 0.0,
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
    sample_topic_ids: frozenset[str] = frozenset(),
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
    # K axis: per-config supporting sizes (for "topics emptied", computed after
    # all variants — independent of --configs order) and self-check counters.
    sup_sizes: dict[str, list[int]] = {}
    v_n_of: dict[str, list[int]] = {}
    extra_ks = sorted(
        {c.score_key(topk)[1] for c in configs if c.agg == "topk_denom"} - {topk}  # type: ignore[arg-type]
    )
    k_checks: dict[str, Any] = {
        "derivation_mismatch": 0,
        "eligible_pairs": dict.fromkeys(extra_ks, 0),
        "product_checked": dict.fromkeys(extra_ks, 0),
        "product_mismatch": dict.fromkeys(extra_ks, 0),
    }
    K_STRATUM_CAP = 50  # per (n >= K, hit kind) stratum, per variant and K
    req_idx = [ti for ti, c in enumerate(data.cards) if c.id in sample_topic_ids]

    for variant, vcfgs in variants.items():
        stop_level, df_frac = variant
        stop = stopset(stop_level, extra_stop)
        drop = _df(df_frac) if df_frac is not None else frozenset()
        v_doc = [filter_doc_tokens(s, w, stop) for s, w in base_doc]
        v_kw = [(k - stop) - drop for k in base_kw]
        need_mean = any(c.agg == "mean" for c in vcfgs)
        v_ks = sorted(
            {c.score_key(topk)[1] for c in vcfgs if c.agg == "topk_denom"} - {topk}  # type: ignore[arg-type]
        )
        strata_seen: Counter[tuple[int, bool, str]] = Counter()

        # scores["topk_denom"][topic] = list[(doc_idx, W)] — weighted hits, from which
        # any K (product K included) is derived at selection time;
        # scores["mean"][topic] = list[(doc_idx, score)] from the product call.
        scores: dict[str, list[list[tuple[int, float]]]] = {"topk_denom": [], "mean": []}
        # Phase 1 argmax (topk_denom), strict '>' in card order — as the product.
        best_list: list[tuple[float, int | None]] = [(0.0, None)] * n_docs

        for ti, kws in enumerate(v_kw):
            row_topk: list[tuple[int, float]] = []
            row_mean: list[tuple[int, float]] = []
            n_kw = len(kws)
            if kws:
                for di in range(n_docs):
                    if kws.isdisjoint(reach[di]):
                        pair_skipped += 1
                        continue
                    strong, weak = v_doc[di]
                    pair_calls += 1
                    score, hits = Impl._compute_match_score(
                        kws, strong, weak, aggregation="topk_denom", topk=topk
                    )
                    if score > 0:
                        w = _weighted_hits(hits, strong)
                        # self-check on EVERY pair: the W path at product K == product
                        if k_score(w, n_kw, topk) != score:
                            k_checks["derivation_mismatch"] += 1
                        row_topk.append((di, w))
                        if score > best_list[di][0]:
                            best_list[di] = (score, ti)
                        if v_ks and n_kw > topk:
                            kind = (
                                "fallback"
                                if not (hits & (strong | weak))
                                else ("weak" if hits - strong else "strong")
                            )
                            for kk in v_ks:
                                k_checks["eligible_pairs"][kk] += 1
                                key = (kk, n_kw >= kk, kind)
                                if strata_seen[key] >= K_STRATUM_CAP:
                                    continue
                                strata_seen[key] += 1
                                direct, _ = Impl._compute_match_score(
                                    kws, strong, weak, aggregation="topk_denom", topk=kk
                                )
                                pair_calls += 1
                                k_checks["product_checked"][kk] += 1
                                if direct != k_score(w, n_kw, kk):
                                    k_checks["product_mismatch"][kk] += 1
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
            agg_key, cfg_k = cfg.score_key(topk)
            rows = scores[agg_key]
            bundles: list[list[tuple[str, float]]] = []
            groups = {"le3": defaultdict(list), "gt3": defaultdict(list)}
            covered_a: set[str] = set()
            membership = Counter()
            member_groups: dict[str, set[str]] = defaultdict(set)
            for ti in range(len(data.cards)):
                anc = anchors[ti]
                if agg_key == "mean":
                    scored = [
                        (refs[di], s) for di, s in rows[ti] if refs[di] not in anc and valid[di]
                    ]
                else:
                    # derived per topic on the fly: no second full row set in memory
                    n_t = len(v_kw[ti])
                    scored = [
                        (refs[di], k_score(w, n_t, cfg_k))  # type: ignore[arg-type]
                        for di, w in rows[ti]
                        if refs[di] not in anc and valid[di]
                    ]
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
                # topics_per_doc counts memberships of EXISTING docs only (orphan
                # anchor refs — e.g. medportal_rfed — would inflate the numerator)
                groups[g]["members"].append(len(members))
                covered_a |= members
                for r in members:
                    membership[r] += 1
                    member_groups[r].add(g)

            covered_b = covered_a | llm_refs
            uncovered_b = [r for r in refs if r not in covered_b]
            was_covered = [r for r in uncovered_b if r in stored_cov]
            # Reconcile only ever feeds uncovered docs WITHOUT a discover_attempted marker.
            candidates = [r for r in uncovered_b if r not in data.attempted]
            p1 = phase1_best[variant]
            # Primary forecast: Phase 1 threshold unchanged (0.10, START_PROMPT §2 p. 2 —
            # not touched without a separate decision). Secondary: if the threshold
            # stays shared with supporting (one MIN_SUPPORTING_SCORE for both paths).
            p1_thr = cfg.thr

            def _assigned(r: str, thr: float, _p1=p1) -> bool:
                s, t = _p1[ref_idx[r]]
                return t is not None and s >= thr

            def _door2(thr: float, _p1=p1, _cands=candidates, _unc=uncovered_b) -> dict[str, Any]:
                assigned = [r for r in _cands if _assigned(r, thr)]
                drain = reconcile_drain(
                    [not _assigned(r, thr) for r in _cands], feed_cap, batch_size
                )
                f5c_add = Counter(data.cards[_p1[ref_idx[r]][1]].id for r in assigned)
                f5c_cross = sum(
                    1
                    for tid, add in f5c_add.items()
                    if counter_now.get(tid, 0)
                    < resummarize_trigger
                    <= counter_now.get(tid, 0) + add
                )
                return {
                    "phase1_threshold": thr,
                    "uncovered_phase1_assignable": sum(1 for r in _unc if _assigned(r, thr)),
                    "candidates_phase1_assigned": len(assigned),
                    "drain": drain,
                    "discover_usd": round(drain["calls"] * DISCOVER_COST_USD, 2),
                    "f5c_topics_touched": len(f5c_add),
                    "f5c_topics_crossing_trigger": f5c_cross,
                }

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

            def _grp(g: dict, key: str, _mg=member_groups) -> dict[str, Any]:
                return {
                    "topics": len(g["items"]),
                    "items_sum": sum(g["items"]),
                    "median_items": median(g["items"]),
                    "sat_cap": sum(g["sat"]),
                    "topics_per_doc": round(sum(g["members"]) / n_docs, 2) if n_docs else 0.0,
                    # "out of all bundles" is global by definition; per group: docs
                    # whose only bundles are this group's (would fall out without it)
                    "docs_only_in_group": sum(1 for gs in _mg.values() if gs == {key}),
                }

            all_items = groups["le3"]["items"] + groups["gt3"]["items"]
            results[cfg.name] = {
                "config": asdict(cfg),
                "all": {
                    "topics": len(all_items),
                    "items_sum": sum(all_items),
                    "median_items": median(all_items),
                    "sat_cap": sum(groups["le3"]["sat"]) + sum(groups["gt3"]["sat"]),
                    "topics_per_doc": round(sum(membership.values()) / n_docs, 2)
                    if n_docs
                    else 0.0,
                    "mean_topics_per_covered_doc": round(
                        sum(membership.values()) / len(membership), 2
                    )
                    if membership
                    else 0.0,
                },
                "n_le3": _grp(groups["le3"], "le3"),
                "n_gt3": _grp(groups["gt3"], "gt3"),
                "topics_moved_gt3_to_le3": n_shift,
                "topics_lost_all_keywords": n_empty,
                "door2": {
                    "uncovered_kw_only": n_docs - len(covered_a),
                    "uncovered_with_llm_kept": len(uncovered_b),
                    "uncovered_previously_covered": len(was_covered),
                    "candidates_minus_attempted": len(candidates),
                    "phase1_thr_010": _door2(phase1_thr),
                    "phase1_thr_shared": _door2(p1_thr),
                },
                "door1_thr_010": _door1(phase1_thr),
                "door1_thr_shared": _door1(p1_thr),
            }
            sup_sizes[cfg.name] = [len(b) for b in bundles]
            v_n_of[cfg.name] = [len(k) for k in v_kw]

            # Bundles kept for base (composition) and sample configs; stripped before emit.
            sampling = sample_topics or req_idx
            if cfg.name == "base" or (sampling and cfg.name in sample_configs):
                results[cfg.name]["_bundles"] = bundles

        del scores

    # "Topics emptied" — after all variants, against base (order-independent).
    eligible_t = [bool(base_kw[ti]) and n_docs > len(anchors[ti]) for ti in range(len(data.cards))]
    base_sz = sup_sizes["base"]

    def _bucket(n: int) -> str:
        return "le3" if n <= 3 else "4_10" if n <= 10 else "11_30" if n <= 30 else "gt30"

    for cname, sz in sup_sizes.items():
        emptied = [
            ti for ti in range(len(sz)) if eligible_t[ti] and base_sz[ti] > 0 and sz[ti] == 0
        ]
        halved = [ti for ti in range(len(sz)) if eligible_t[ti] and 0 < sz[ti] < base_sz[ti] / 2]
        vn = v_n_of[cname]
        results[cname]["all"].update(
            {
                # absolute: every topic with empty supporting (gpt-review a0f51a2)
                "topics_without_supporting": sum(1 for s in sz if s == 0),
                # of which supporting is impossible: no keywords, or the product's
                # len(documents) > len(anchor_refs) condition fails
                "topics_supporting_impossible": sum(1 for e in eligible_t if not e),
                "topics_emptied": len(emptied),
                "topics_halved": len(halved),
                "emptied_n_median_base": median([base_n[t] for t in emptied]),
                "emptied_n_max_base": max((base_n[t] for t in emptied), default=0),
                "emptied_n_median_filtered": median([vn[t] for t in emptied]),
                "emptied_n_max_filtered": max((vn[t] for t in emptied), default=0),
                "emptied_by_n": dict(Counter(_bucket(base_n[t]) for t in emptied)),
                "halved_by_n": dict(Counter(_bucket(base_n[t]) for t in halved)),
            }
        )

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

    # Samples: largest base bundle, median, smallest non-empty (n<=3 preferred),
    # the widest topic (max n), plus every --sample-topic present in the channel.
    if sample_topics or req_idx:
        base_b = results["base"].get("_bundles") or []
        order = sorted(range(len(base_b)), key=lambda t: -len(base_b[t]))
        picks: list[int] = []
        if order and sample_topics:
            picks.append(order[0])
            picks.append(order[len(order) // 2])
            le3 = [t for t in order if base_n[t] <= topk and t not in picks]
            picks.append(le3[0] if le3 else order[-1])
            picks = list(dict.fromkeys(picks))[:sample_topics]
            picks.append(max(range(len(base_n)), key=lambda t: base_n[t]))
        picks = list(dict.fromkeys(picks + req_idx))

        def _doc_brief(
            ref: str, s: float, ti: int, cfg: SimConfig, *, also: SimConfig | None = None
        ) -> dict[str, Any]:
            """Hits under ``cfg``; with ``also`` — that config's own score too
            (why a document left: its score under the candidate config)."""
            di = ref_idx[ref]

            def _call(c: SimConfig) -> tuple[float, set[str]]:
                stop = stopset(c.stop, extra_stop)
                drop = _df(c.df) if c.df is not None else frozenset()
                strong, weak = filter_doc_tokens(*base_doc[di], stop)
                kws = (base_kw[ti] - stop) - drop
                agg, k = c.score_key(topk)
                return Impl._compute_match_score(
                    kws, strong, weak, aggregation=agg, topk=k if k is not None else topk
                )

            _, hits = _call(cfg)
            out = {
                "ref": ref,
                "score": s,
                "hits": sorted(hits)[:8],
                "summary": (docs[di].summary or "")[:120],
            }
            if also is not None:
                out["cfg_score"] = _call(also)[0]
            return out

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
                        "left_examples": [
                            _doc_brief(r, b_refs[r], ti, base_cfg, also=cfg) for r in left[:5]
                        ],
                        "stayed_examples": [_doc_brief(r, c_refs[r], ti, cfg) for r in stayed[-5:]],
                    }
                )
            samples_out[cname] = topics_out

    internal = {
        "base_bundles": results["base"]["_bundles"],
        "phase1_base": phase1_best[("none", None)],
        "k_checks": k_checks,
    }
    for r in results.values():
        r.pop("_bundles", None)

    return {
        "_internal": internal,  # for baseline_guard; popped before emit
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
        "k_checks": k_checks,
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
    internal: dict[str, Any],
    *,
    guard_topics: int,
    guard_docs: int,
    min_score: float,
    topk: int,
) -> dict[str, Any]:
    """Check simulate_channel's own base outputs against the product functions.

    ``internal`` is ``simulate_channel(...)["_internal"]``: base supporting per
    topic and the base Phase-1 argmax table — the exact data the published
    tables are computed from. ``base`` is the pre-R16 supporting formula, so the
    product is called with it explicitly: ``topk`` (the Phase-1 K that supporting
    shared before R16) and ``cut="lt"``.
    """
    docs = data.docs
    cards = data.cards
    if guard_topics <= 0 or guard_topics >= len(cards):
        picked = list(range(len(cards)))
    else:
        step = len(cards) / guard_topics
        picked = sorted({int(i * step) for i in range(guard_topics)})

    # Supporting: the SAME base bundles simulate_channel published (pair skipping,
    # anchor exclusion, cap and the n_docs > anchors condition included).
    sup_mismatch = []
    for ti in picked:
        card = cards[ti]
        anc = {a.anchor_ref for a in card.anchors}
        product = pipeline._find_supporting_items_programmatic(
            topic_card=card, anchor_refs=anc, documents=docs, topk=topk, cut="lt"
        )
        if not (len(docs) > len(anc)):  # _compute_topic_bundle skips supporting
            product = []
        prod = [(it.source_ref, it.score) for it in product]
        if prod != list(internal["base_bundles"][ti]):
            sup_mismatch.append(card.id)

    # Phase 1: the SAME argmax table (base variant) the door forecasts use.
    sample_idx = list(range(len(docs)))
    if 0 < guard_docs < len(docs):
        step = len(docs) / guard_docs
        sample_idx = sorted({int(i * step) for i in range(guard_docs)})
    sample = [docs[i] for i in sample_idx]
    assignments, _unassigned = await pipeline.assign_documents_to_topics(
        new_docs=sample, channel_id=data.channel_id
    )
    prod_assign = {a.source_ref: (a.topic_id, a.score) for a in assignments}
    best = internal["phase1_base"]
    p1_mismatch = []
    for i in sample_idx:
        s, t = best[i]
        mine = (cards[t].id, s) if (t is not None and s >= min_score) else None
        if prod_assign.get(docs[i].source_ref) != mine:
            p1_mismatch.append(docs[i].source_ref)

    refs = [d.source_ref for d in docs]
    kc = internal.get("k_checks") or {}
    return {
        "type": "guard",
        "channel_id": data.channel_id,
        "supporting_topics_checked": len(picked),
        "supporting_mismatch": sup_mismatch[:20],
        "phase1_docs_checked": len(sample),
        "phase1_mismatch": p1_mismatch[:20],
        "db_order_equals_python_sort": refs == sorted(refs),
        "k_checks": kc,
        "ok": not sup_mismatch and not p1_mismatch and k_checks_ok(kc),
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
    # keep only bundles whose first channel is this one (LIKE pattern is loose).
    # The product's coverage check uses every bundle list_by_channel returns, so
    # say so loudly whenever this filter drops anything (prod 2026-11-12: 0 of 1461).
    own = [b for b in bundles if (b.channels or [channel_id])[0] == channel_id]
    if len(own) != len(bundles):
        _log(f"{channel_id}: {len(bundles) - len(own)} foreign/multi-channel bundles dropped")
    bundles = own
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
    if "base" in sample_configs:
        # parse_configs always adds base, so the name check below would pass, but the
        # sample loop compares configs AGAINST base and skips it → samples={} at rc 0.
        _fatal("--sample-configs: 'base' is the reference, not a sample config")
    sample_topic_ids = frozenset(args.sample_topic or ())
    if sample_topic_ids and not sample_configs:
        _fatal("--sample-topic needs --sample-configs (nothing to compare against base)")
    unknown_samples = sorted(sample_configs - {c.name for c in configs})
    if unknown_samples:
        # Otherwise simulate_channel skips them and the run ends with samples={} and rc 0.
        _fatal(f"--sample-configs not among the simulated --configs: {unknown_samples}")
    sample_topics_found: set[str] = set()

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
            channels = resolve_channels(args.channel, args.exclude_channel, live)

            meta = {
                "type": "meta",
                "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "default_transaction_read_only": ro,
                "channels": channels,
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
            checked: list[str] = []
            for ch in channels:
                _log(f"{ch}: loading")
                data = await _load_channel(session, ch)
                _log(f"{ch}: {len(data.docs)} docs, {len(data.cards)} cards")
                if not data.docs or not data.cards:
                    _emit({"type": "channel", "channel_id": ch, "skipped": "no_docs_or_cards"})
                    continue
                # Found = its channel is simulated; a skipped channel yields no samples.
                sample_topics_found |= {c.id for c in data.cards} & sample_topic_ids
                _log(f"{ch}: simulating {len(configs)} configs")
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
                    sample_topic_ids=sample_topic_ids,
                )
                internal = res.pop("_internal")
                guard = await baseline_guard(
                    pipeline,
                    data,
                    internal,
                    guard_topics=args.guard_topics,
                    guard_docs=args.guard_docs,
                    min_score=topi.MIN_SUPPORTING_SCORE,
                    topk=topi.ASSIGN_KEYWORD_TOPK,
                )
                _emit(guard)
                if not guard["ok"]:
                    all_ok = False
                    _log(f"{ch}: BASELINE GUARD FAILED — channel result withheld, stopping")
                    break
                checked.append(ch)
                _emit(res)
                _log(
                    f"{ch}: done in {res['runtime_s']}s, product calls {res['pair_calls']}, "
                    f"skipped {res['pair_skipped_provable_zero']}, "
                    f"maxrss {_maxrss_mb()} MB"
                )
                del data
    finally:
        await engine.dispose()

    ok, rc = run_outcome(all_ok, len(checked))
    missing_topics = sorted(sample_topic_ids - sample_topics_found)
    if missing_topics:
        _log(f"WARNING: --sample-topic not found in the simulated channels: {missing_topics}")
    _emit(
        {
            "type": "summary",
            "runtime_s": round(time.monotonic() - started, 1),
            "channels_checked": len(checked),
            "sample_topics_missing": missing_topics,
            "baseline_guard_ok": ok,
            "maxrss_mb": _maxrss_mb(),
        }
    )
    return rc


def resolve_channels(
    requested: Sequence[str] | None, excluded: Sequence[str] | None, live: Sequence[str]
) -> list[str]:
    """Channels to simulate. A requested channel that is not live, or an empty
    selection, is a fatal error — never a silently empty "successful" run."""
    live_set = set(live)
    unknown = [c for c in (requested or []) if c not in live_set]
    if unknown:
        _fatal(f"unknown or deleted channels: {unknown}")
    unknown_ex = [c for c in (excluded or []) if c not in live_set]
    if unknown_ex:
        _fatal(f"unknown or deleted channels in --exclude-channel: {unknown_ex}")
    drop = set(excluded or [])
    channels = [c for c in (requested or live) if c not in drop]
    if not channels:
        _fatal("no channels selected (after --exclude-channel)")
    return channels


def run_outcome(all_ok: bool, n_checked: int) -> tuple[bool, int]:
    """``baseline_guard_ok`` holds only if at least one channel passed the guard."""
    ok = all_ok and n_checked > 0
    return ok, 0 if ok else 2


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
    except (ValueError, OSError, OverflowError) as e:
        _fatal(f"cannot set RLIMIT_AS={max_mem_mb} MB ({e}); pass --max-mem-mb 0 to run unguarded")
    return limit // (1024 * 1024)


def _quiet_logging() -> None:
    """Everything on stdout as JSONL: product loggers are structlog (whose
    unconfigured default prints plain text to stdout) plus stdlib logging.
    Both are rendered as one JSON object per line, WARNING and above only."""
    import structlog

    class _JsonLineFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return json.dumps(
                {
                    "type": "lib_log",
                    "logger": record.name,
                    "level": record.levelname,
                    "msg": record.getMessage(),
                },
                ensure_ascii=False,
            )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonLineFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING)
    for name in ("tg_parser", "sqlalchemy", "asyncpg"):
        logging.getLogger(name).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            lambda _l, _m, ev: {"type": "lib_log", **ev},
            structlog.processors.JSONRenderer(ensure_ascii=False, default=str),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        cache_logger_on_first_use=False,
    )


class _StderrToJsonl(io.TextIOBase):
    """Replacement for ``sys.stderr``: every line becomes ``{"type": "stderr"}`` on stdout."""

    def __init__(self) -> None:
        self._buf = ""

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            _emit({"type": "stderr", "line": line})
        return len(s)

    def flush(self) -> None:
        if self._buf:
            _emit({"type": "stderr", "line": self._buf})
            self._buf = ""


class _JsonlArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _fatal(f"argument error: {message}")

    def print_help(self, file=None) -> None:  # noqa: ARG002 — always stdout JSONL
        _emit({"type": "help", "text": self.format_help()})

    def print_usage(self, file=None) -> None:  # noqa: ARG002 — always stdout JSONL
        _emit({"type": "help", "text": self.format_usage()})


def _build_parser() -> argparse.ArgumentParser:
    p = _JsonlArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--channel", action="append", help="channel_id (repeatable); default: all live")
    p.add_argument("--exclude-channel", action="append")
    p.add_argument(
        "--configs",
        default="base",
        help="';'-separated: 'stage1', built-in names, or 'name:stop=..,cut=..,agg=..,thr=..,df=..,k=..'",
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
    p.add_argument(
        "--sample-topic",
        action="append",
        help="topic_id to add to the eyeball samples (repeatable; any channel)",
    )
    p.add_argument("--guard-topics", type=int, default=20, help="0 = all topics")
    p.add_argument("--guard-docs", type=int, default=200, help="0 = all docs")
    p.add_argument("--max-mem-mb", type=int, default=2048, help="RLIMIT_AS guard; 0 = off")
    return p


def main(argv: list[str] | None = None) -> int:
    saved_stderr = sys.stderr
    sys.stderr = _StderrToJsonl()
    logging.captureWarnings(True)  # warnings → logging → JSON handler on stdout
    try:
        try:
            args = _build_parser().parse_args(argv)
            args.mem_guard_mb = set_memory_guard(args.max_mem_mb)
            _quiet_logging()
            return asyncio.run(run(args))
        except SystemExit:
            raise
        except BaseException as e:  # noqa: BLE001 — every failure must reach stdout as JSONL
            _emit(
                {
                    "type": "fatal",
                    "msg": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                }
            )
            raise SystemExit(3) from None
    finally:
        sys.stderr.flush()
        sys.stderr = saved_stderr
        logging.captureWarnings(False)


if __name__ == "__main__":
    sys.exit(main())
