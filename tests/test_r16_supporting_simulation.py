"""R16 / BUG-105 — the supporting simulation script measures the product, not a copy.

The script re-implements only the threshold / sort / cap of
``_find_supporting_items_programmatic`` and models a stoplist as a set filter on
the product tokenizer output. These tests pin both claims against the product
code, plus the pure arithmetic the forecast tables rely on. No DB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import r16_supporting_simulation as sim  # noqa: E402
from tg_parser.processing.topicization import TopicizationPipelineImpl as Impl  # noqa: E402

NOW = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)


def _doc(n: int, *, topics=(), summary="", text="", hours_ago: int = 1):
    return SimpleNamespace(
        source_ref=f"tg:chan:post:{n}",
        topics=list(topics),
        summary=summary,
        text_clean=text,
        processed_at=NOW - timedelta(hours=hours_ago),
    )


def _card(cid: str, title: str, scope_in, anchors=()):
    return SimpleNamespace(
        id=cid,
        title=title,
        scope_in=list(scope_in),
        anchors=[SimpleNamespace(anchor_ref=a) for a in anchors],
        new_items_since_last_summary=0,
    )


def _corpus():
    docs = [
        _doc(1, topics=["диагностика щитовидной железы"], summary="ТТГ и гормоны"),
        _doc(2, summary="статья для пациентов", text="между делом про диабет"),
        _doc(3, topics=["питание"], summary="белки жиры углеводы", text="для здоровья"),
        _doc(4, summary="анализ крови СОЭ", text="диагностика воспаления"),
        _doc(5, summary="философия канала", text="между нами"),
        _doc(6, summary="диагностический поиск", text="через неделю после"),
        _doc(7, summary="щитовидная железа и йод", text="для взрослых"),
        _doc(8, summary="ничего общего", text="совсем другое"),
    ]
    cards = [
        _card(
            "topic:tg:chan:post:1",
            "Щитовидная железа",
            ["диагностика щитовидной железы", "ТТГ для взрослых"],
            anchors=["tg:chan:post:1"],
        ),
        _card(
            "topic:tg:chan:post:4", "Анализы", ["анализ крови", "СОЭ"], anchors=["tg:chan:post:4"]
        ),
        _card(
            "topic:tg:chan:post:3",
            "Питание и здоровье",
            ["питание для здоровья", "белки жиры углеводы между приёмами пищи"],
            anchors=["tg:chan:post:3"],
        ),
    ]
    return docs, cards


# ---------------------------------------------------------------------------
# Stoplist as a set filter == stoplist inside _tokenize
# ---------------------------------------------------------------------------


def test_set_filter_equals_stoplist_inside_tokenize(monkeypatch):
    docs, cards = _corpus()
    stop = sim.R6_STOPLIST | sim.AUDIT_ADDITIONS
    before_doc = [Impl._tokenize_document(d) for d in docs]
    before_kw = [Impl._tokenize_topic_card(c) for c in cards]

    original = Impl._tokenize
    monkeypatch.setattr(Impl, "_tokenize", staticmethod(lambda text: original(text) - stop))
    inside_doc = [Impl._tokenize_document(d) for d in docs]
    inside_kw = [Impl._tokenize_topic_card(c) for c in cards]
    monkeypatch.setattr(Impl, "_tokenize", staticmethod(original))

    for (s, w), (si, wi) in zip(before_doc, inside_doc, strict=True):
        assert sim.filter_doc_tokens(s, w, stop) == (si, wi)
    for k, ki in zip(before_kw, inside_kw, strict=True):
        assert k - stop == ki
    # and the product score on filtered sets is the same either way
    for k, ki in zip(before_kw, inside_kw, strict=True):
        for (s, w), (si, wi) in zip(before_doc, inside_doc, strict=True):
            fs, fw = sim.filter_doc_tokens(s, w, stop)
            assert Impl._compute_match_score(k - stop, fs, fw) == Impl._compute_match_score(
                ki, si, wi
            )


# ---------------------------------------------------------------------------
# Selection arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "cut", "kept"),
    [(0.1, "lt", True), (0.1, "le", False), (0.101, "le", True), (0.099, "lt", False)],
)
def test_cutoff_at_threshold(score, cut, kept):
    assert sim.passes(score, 0.10, cut) is kept


def test_select_supporting_is_stable_and_capped():
    scored = [("c", 0.1), ("a", 0.5), ("b", 0.1), ("d", 0.05), ("e", 0.1)]
    assert sim.select_supporting(scored, 0.10, "lt", 3) == [("a", 0.5), ("c", 0.1), ("b", 0.1)]
    assert sim.select_supporting(scored, 0.10, "le", 10) == [("a", 0.5)]


def test_reconcile_drain_all_misses():
    assert sim.reconcile_drain([], 200, 25)["calls"] == 0
    r = sim.reconcile_drain([True] * 450, 200, 25)
    assert (r["ticks"], r["calls"], r["max_calls_per_tick"], r["calls_worst_case"]) == (
        3,
        18,
        8,
        18,
    )


def test_reconcile_drain_feed_counts_phase1_assignable_candidates():
    # product feeds candidates BEFORE Phase 1: 100 misses among 2000 candidates
    # spread over 10 feeds of 200 → ~1 call per tick, not 4 calls in one tick
    flags = [True] * 100 + [False] * 1900
    r = sim.reconcile_drain(flags, 200, 25)
    assert r["ticks"] == 10
    assert r["misses"] == 100
    assert 10 >= r["calls"] >= 4  # each feed holds ≤ 25 misses w.h.p.; ≥ ceil(100/25)
    # upper bound: one miss per feed (10 calls), +3 calls from 3 more batches of 25
    assert r["calls_worst_case"] == 13
    assert r["calls_worst_case"] >= r["calls"]
    # deterministic for a fixed seed
    assert sim.reconcile_drain(flags, 200, 25) == r


def test_worst_case_is_an_upper_bound():
    # Codex round 2: 400 candidates, 2 misses, feeds of 200, batch 50 → 2 calls possible
    r = sim.reconcile_drain([True, True] + [False] * 398, 200, 50)
    assert r["calls_worst_case"] == 2 >= r["calls"]


@pytest.mark.parametrize("seed", range(40))
def test_max_calls_over_feeds_matches_exhaustive(seed):
    rng = random.Random(seed)
    feeds = [rng.randint(1, 7) for _ in range(rng.randint(1, 4))]
    batch = rng.randint(1, 4)
    misses = rng.randint(0, sum(feeds))

    def best(i: int, left: int) -> int:
        if i == len(feeds):
            return 0 if left == 0 else -(10**9)
        return max(
            math.ceil(m / batch) + best(i + 1, left - m) for m in range(0, min(feeds[i], left) + 1)
        )

    assert sim.max_calls_over_feeds(feeds, misses, batch) == best(0, misses)


def test_reconcile_drain_zero_cap_means_unbounded():
    r = sim.reconcile_drain([True] * 450, 0, 25)
    assert (r["ticks"], r["calls"]) == (1, 18)


def test_df_drop_set():
    sets = [{"a", "b"}, {"a"}, {"a", "c"}, {"d"}]
    assert sim.df_drop_set(sets, 4, 0.5) == frozenset({"a"})
    assert sim.df_drop_set(sets, 4, 0.2) == frozenset({"a", "b", "c", "d"})


def test_substring_index_matches_bruteforce():
    rng = random.Random(7)
    alphabet = "абвгде"
    words = {"".join(rng.choice(alphabet) for _ in range(rng.randint(3, 9))) for _ in range(300)}
    kws, dts = set(list(words)[:120]), set(list(words)[100:])
    related = sim.substring_related(kws, dts)
    for dt in dts:
        expected = {kw for kw in kws if len(kw) >= 5 and len(dt) >= 5 and (kw in dt or dt in kw)}
        assert related.get(dt, set()) == expected


def test_read_only_guard(capsys):
    sim.check_read_only("on")
    with pytest.raises(SystemExit):
        sim.check_read_only("off")
    with pytest.raises(SystemExit):
        sim.check_read_only(None)
    out, err = capsys.readouterr()
    assert err == ""
    assert [json.loads(line)["type"] for line in out.splitlines()] == ["fatal", "fatal"]


def test_all_output_is_jsonl_on_stdout(capsys):
    """CLAUDE.md «Прод»: вывод — только в stdout. Progress and library logs too."""
    import structlog

    # _quiet_logging reconfigures process-global logging; restore all of it so
    # later tests (caplog / structlog capture) see the state they expect.
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    names = ("tg_parser", "sqlalchemy", "asyncpg")
    saved_levels = {n: logging.getLogger(n).level for n in names}
    saved_structlog = structlog.get_config()
    sim._quiet_logging()
    try:
        sim._log("progress line")
        structlog.get_logger("tg_parser.x").warning("lib warning", k=1)
        structlog.get_logger("tg_parser.x").info("dropped below WARNING")
        logging.getLogger("tg_parser.y").warning("stdlib warning")
    finally:
        structlog.configure(**saved_structlog)
        root.handlers[:], _ = saved_root
        root.setLevel(saved_root[1])
        for n, lvl in saved_levels.items():
            logging.getLogger(n).setLevel(lvl)
    out, err = capsys.readouterr()
    assert err == ""
    types = [json.loads(line)["type"] for line in out.splitlines()]
    assert types == ["log", "lib_log", "lib_log"]


def test_config_parsing():
    cfgs = sim.parse_configs("stage1")
    assert cfgs[0].name == "base" and len(cfgs) == len(sim.STAGE1)
    c = sim.parse_configs("combo:stop=r6a,cut=le,thr=0.15,df=0.25")
    assert [x.name for x in c] == ["base", "combo"]
    assert c[1].variant == ("r6a", 0.25) and c[1].cut == "le" and c[1].thr == 0.15
    with pytest.raises(ValueError):
        sim.parse_config("bad:stop=xx")


# ---------------------------------------------------------------------------
# Baseline guard and the full channel run agree with the product
# ---------------------------------------------------------------------------


class _CardRepo:
    def __init__(self, cards):
        self._cards = cards

    async def list_by_channel(self, channel_id):
        return list(self._cards)


def _pipeline(cards):
    return Impl(
        llm_client=None,
        processed_doc_repo=None,
        topic_card_repo=_CardRepo(cards),
        topic_bundle_repo=None,
    )


def _data(docs, cards):
    return sim.ChannelData("chan", docs, cards, bundles=[], attempted=set())


def _simulate(docs, cards, configs="base;stop_r6a;cut_le", cap=100):
    return sim.simulate_channel(
        _data(docs, cards),
        sim.parse_configs(configs),
        extra_stop=frozenset(),
        cap=cap,
        topk=3,
        phase1_thr=0.10,
        batch_size=25,
        feed_cap=200,
        resummarize_trigger=5,
        phase1_days=30,
        now=NOW,
        sample_topics=0,
        sample_configs=set(),
    )


def _guard(docs, cards, internal):
    return asyncio.run(
        sim.baseline_guard(
            _pipeline(cards),
            _data(docs, cards),
            internal,
            guard_topics=0,
            guard_docs=0,
            min_score=0.10,
        )
    )


def test_baseline_guard_checks_simulate_outputs_and_detects_divergence():
    docs, cards = _corpus()
    res = _simulate(docs, cards)
    internal = res["_internal"]
    assert any(internal["base_bundles"]), "corpus must produce some supporting"
    ok = _guard(docs, cards, internal)
    assert ok["ok"], ok

    # a simulate path with a different cap than the product publishes other bundles
    capped = _simulate(docs, cards, cap=1)["_internal"]
    assert not _guard(docs, cards, capped)["ok"]

    # a corrupted Phase-1 table is caught too
    broken_p1 = dict(internal, phase1_base=[(0.0, None)] * len(docs))
    bad = _guard(docs, cards, broken_p1)
    assert not bad["ok"] and bad["phase1_mismatch"]


def test_simulate_base_equals_product_bundles():
    docs, cards = _corpus()
    res = _simulate(docs, cards)
    expected_items = 0
    for card in cards:
        anc = {a.anchor_ref for a in card.anchors}
        sup = Impl._find_supporting_items_programmatic(
            Impl, topic_card=card, anchor_refs=anc, documents=docs
        )
        expected_items += len(anc) + len(sup)
    assert res["configs"]["base"]["all"]["items_sum"] == expected_items
    # filters can only remove supporting
    assert (
        res["configs"]["stop_r6a"]["all"]["items_sum"] <= res["configs"]["base"]["all"]["items_sum"]
    )
    assert res["configs"]["cut_le"]["all"]["items_sum"] <= expected_items
    # door 1 window sees every doc (all processed 1 h ago)
    assert res["configs"]["base"]["door1_thr_010"]["docs"] == len(docs)
    assert "_bundles" not in res["configs"]["base"]
    base = res["configs"]["base"]
    # per-group metrics are present and add up
    assert base["n_le3"]["items_sum"] + base["n_gt3"]["items_sum"] == base["all"]["items_sum"]
    assert {"topics_per_doc", "docs_only_in_group"} <= set(base["n_gt3"])


def test_topics_per_doc_ignores_orphan_anchor_refs():
    """Codex round 2: an anchor ref without a document row must not inflate topics/doc."""
    docs = [_doc(1, summary="щитовидная железа йод"), _doc(2, summary="щитовидная железа йод")]
    cards = [
        _card(
            "topic:tg:chan:post:9",
            "Щитовидная железа",
            ["щитовидная железа йод"],
            ["tg:chan:post:9"],
        )
    ]
    base = _simulate(docs, cards, configs="base")["configs"]["base"]
    assert base["all"]["items_sum"] == 3  # product bundle: orphan anchor + 2 supporting
    assert base["all"]["topics_per_doc"] == 1.0
    assert base["n_le3"]["topics_per_doc"] + base["n_gt3"]["topics_per_doc"] == 1.0


def test_door2_primary_forecast_keeps_phase1_threshold():
    """thr_015 drops a 0.10 doc from supporting; Phase 1 (>= 0.10) still assigns it,
    so the primary door-2 forecast must not send it to discover."""
    docs = [
        _doc(1, summary="щитовидная железа"),  # anchor
        _doc(2, summary="ничего", text="щитовидная"),  # one weak hit → 0.3/3 = 0.1
    ]
    cards = [
        _card(
            "topic:tg:chan:post:1",
            "Щитовидная железа",
            ["щитовидная железа йод"],
            ["tg:chan:post:1"],
        )
    ]
    res = _simulate(docs, cards, configs="thr_015")
    d2 = res["configs"]["thr_015"]["door2"]
    assert d2["uncovered_with_llm_kept"] == 1
    assert d2["phase1_thr_010"]["candidates_phase1_assigned"] == 1
    assert d2["phase1_thr_010"]["drain"]["calls"] == 0
    assert d2["phase1_thr_shared"]["drain"]["calls"] == 1


def test_f5c_forecast_skips_discover_attempted():
    docs = [_doc(1, summary="щитовидная железа"), _doc(2, summary="ничего", text="щитовидная")]
    cards = [
        _card(
            "topic:tg:chan:post:1",
            "Щитовидная железа",
            ["щитовидная железа йод"],
            ["tg:chan:post:1"],
        )
    ]
    cards[0].new_items_since_last_summary = 4
    data = sim.ChannelData("chan", docs, cards, bundles=[], attempted={"tg:chan:post:2"})
    res = sim.simulate_channel(
        data,
        sim.parse_configs("thr_015"),
        extra_stop=frozenset(),
        cap=100,
        topk=3,
        phase1_thr=0.10,
        batch_size=25,
        feed_cap=200,
        resummarize_trigger=5,
        phase1_days=30,
        now=NOW,
        sample_topics=0,
        sample_configs=set(),
    )
    d2 = res["configs"]["thr_015"]["door2"]["phase1_thr_010"]
    assert d2["uncovered_phase1_assignable"] == 1
    assert d2["candidates_phase1_assigned"] == 0
    assert d2["f5c_topics_crossing_trigger"] == 0


# ---------------------------------------------------------------------------
# main(): every failure path reports on stdout as JSONL (CLAUDE.md «Прод»)
# ---------------------------------------------------------------------------


_REAL_SET_MEMORY_GUARD = sim.set_memory_guard


@pytest.fixture
def _no_global_side_effects(monkeypatch):
    """main() sets RLIMIT_AS (skipped here) and reconfigures process-global
    logging for real; restore every piece of it afterwards."""
    import structlog

    monkeypatch.setattr(sim, "set_memory_guard", lambda mb: None)
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    names = ("tg_parser", "sqlalchemy", "asyncpg")
    saved_levels = {n: logging.getLogger(n).level for n in names}
    saved_structlog = structlog.get_config()
    yield
    structlog.configure(**saved_structlog)
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for n, lvl in saved_levels.items():
        logging.getLogger(n).setLevel(lvl)


def _lines(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines()]


def test_main_argument_error_is_fatal_on_stdout(capsys, _no_global_side_effects):
    with pytest.raises(SystemExit) as exc:
        sim.main(["--phase1-days", "bad"])
    assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert err == ""
    assert [x["type"] for x in _lines(out)] == ["fatal"]


def test_main_runtime_exception_is_fatal_on_stdout(capsys, monkeypatch, _no_global_side_effects):
    async def boom(args):
        raise ConnectionError("db connection lost")

    monkeypatch.setattr(sim, "run", boom)
    with pytest.raises(SystemExit) as exc:
        sim.main([])
    assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert err == ""
    (fatal,) = _lines(out)
    assert fatal["type"] == "fatal" and "ConnectionError" in fatal["msg"]
    assert "Traceback" in fatal["traceback"]


def test_main_stray_stderr_and_warnings_land_on_stdout(
    capsys, monkeypatch, _no_global_side_effects
):
    import warnings

    async def noisy(args):
        print("stray line", file=sys.stderr)
        warnings.warn("library warning", RuntimeWarning, stacklevel=1)
        return 0

    monkeypatch.setattr(sim, "run", noisy)
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        assert sim.main([]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    text = "\n".join(json.dumps(x, ensure_ascii=False) for x in _lines(out))
    assert "stray line" in text and "library warning" in text
    assert sys.stderr is not None and not isinstance(sys.stderr, sim._StderrToJsonl)


def test_main_memory_guard_overflow_is_fatal_on_stdout(
    capsys, monkeypatch, _no_global_side_effects
):
    """gpt-review round 4 (Medium): setup before run() must be covered too."""

    def overflow(*_a):
        raise OverflowError("Python int too large to convert to C long")

    monkeypatch.setattr(sim.resource, "setrlimit", overflow)
    monkeypatch.setattr(sim, "set_memory_guard", _REAL_SET_MEMORY_GUARD)
    with pytest.raises(SystemExit) as exc:
        sim.main(["--max-mem-mb", "999999999999999999999999999999"])
    assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert err == ""
    (fatal,) = _lines(out)
    assert fatal["type"] == "fatal" and "RLIMIT_AS" in fatal["msg"]


def test_main_logging_setup_failure_is_fatal_on_stdout(
    capsys, monkeypatch, _no_global_side_effects
):
    def broken():
        raise MemoryError("logging setup")

    monkeypatch.setattr(sim, "_quiet_logging", broken)
    with pytest.raises(SystemExit) as exc:
        sim.main([])
    assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert err == ""
    (fatal,) = _lines(out)
    assert fatal["type"] == "fatal" and "MemoryError" in fatal["msg"]
    assert not isinstance(sys.stderr, sim._StderrToJsonl)


def test_main_help_is_jsonl_on_stdout(capsys, _no_global_side_effects):
    with pytest.raises(SystemExit) as exc:
        sim.main(["--help"])
    assert exc.value.code == 0
    out, err = capsys.readouterr()
    assert err == ""
    (helpline,) = _lines(out)
    assert helpline["type"] == "help" and "--max-mem-mb" in helpline["text"]


def test_resolve_channels_unknown_or_empty_is_fatal(capsys):
    """code-reviewer round 5 (Low): a typo must not yield an empty "ok" run."""
    live = ["Lab4health", "kdl_ru"]
    assert sim.resolve_channels(None, None, live) == live
    assert sim.resolve_channels(None, ["kdl_ru"], live) == ["Lab4health"]
    assert sim.resolve_channels(["kdl_ru"], None, live) == ["kdl_ru"]
    for requested, excluded in ((["lab4health"], None), (["kdl_ru"], ["kdl_ru"])):
        with pytest.raises(SystemExit) as exc:
            sim.resolve_channels(requested, excluded, live)
        assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert err == ""
    assert [x["type"] for x in _lines(out)] == ["fatal", "fatal"]


def test_run_outcome_needs_a_checked_channel():
    assert sim.run_outcome(True, 1) == (True, 0)
    assert sim.run_outcome(True, 0) == (False, 2)
    assert sim.run_outcome(False, 3) == (False, 2)


def test_stored_stats_topics_per_doc_over_existing_docs():
    """code-reviewer round 3 (Low): the stored snapshot ignores orphan refs too."""
    sup = SimpleNamespace(value="supporting")
    anc = SimpleNamespace(value="anchor")

    def item(ref, role):
        return SimpleNamespace(source_ref=ref, role=role, justification="")

    docs = [_doc(1), _doc(2)]
    bundles = [
        SimpleNamespace(
            items=[
                item("tg:chan:post:9", anc),  # orphan anchor, no document row
                item("tg:chan:post:1", sup),
                item("tg:chan:post:2", sup),
            ]
        )
    ]
    data = sim.ChannelData("chan", docs, [], bundles=bundles, attempted=set())
    stored = sim._stored_stats(data, cap=100)
    assert stored["items_sum"] == 3
    assert stored["topics_per_doc"] == 1.0
    assert stored["coverage_pct"] == 100.0


# ---------------------------------------------------------------------------
# K axis (stage A′): supporting topk_denom with denominator min(n, K)
# ---------------------------------------------------------------------------

_WIDE_ID = "topic:tg:chan:post:1"


def _corpus_k():
    """A wide topic (n = 8) where K changes supporting, and a narrow one (n = 3)."""
    docs = [
        _doc(1, summary="щитовидная железа"),
        _doc(2, summary="гормоны"),  # one strong hit
        _doc(3, text="гормоны"),  # one weak hit
        _doc(4, summary="йод узлы"),  # two strong hits
        _doc(5, text="железы"),  # one weak hit
        _doc(6, summary="ничего общего"),
        _doc(7, text="железыстый"),  # substring-fallback only (weak)
        _doc(8, summary="анализ крови СОЭ"),
        _doc(9, summary="гормоны йод узлы железы"),  # four strong hits
    ]
    cards = [
        _card(
            _WIDE_ID,
            "Щитовидная железа",
            ["диагностика щитовидной железы гормоны йод узлы"],
            anchors=["tg:chan:post:1"],
        ),
        _card("topic:tg:chan:post:8", "Анализ крови", ["СОЭ"], anchors=["tg:chan:post:8"]),
    ]
    return docs, cards


def _direct_items_sum(docs, cards, k, thr=0.10, cut="lt"):
    total = 0
    for card in cards:
        anc = {a.anchor_ref for a in card.anchors}
        kws = Impl._tokenize_topic_card(card)
        scored = []
        for d in docs:
            if d.source_ref in anc:
                continue
            strong, weak = Impl._tokenize_document(d)
            s, _ = Impl._compute_match_score(kws, strong, weak, aggregation="topk_denom", topk=k)
            if s > 0:
                scored.append((d.source_ref, s))
        total += len(anc) + len(sim.select_supporting(scored, thr, cut, 100))
    return total


def test_config_k_parsing():
    (_, k5) = sim.parse_configs("k5:k=5,cut=le")
    assert k5.k == 5 and k5.cut == "le" and k5.score_key(3) == ("topk_denom", 5)
    assert sim.parse_config("x:k=3").score_key(3) == sim.SimConfig("y").score_key(3)
    assert sim.parse_config("m:agg=mean").score_key(3) == ("mean", None)
    for bad in ("x:k=0", "x:k=x", "x:agg=mean,k=5"):
        with pytest.raises(ValueError):
            sim.parse_config(bad)


def test_k3_equals_base():
    docs, cards = _corpus_k()
    res = _simulate(docs, cards, configs="base;k3:k=3")
    b, k3 = res["configs"]["base"], res["configs"]["k3"]
    assert b["all"] == k3["all"] and b["door2"] == k3["door2"]


def test_k_axis_matches_direct_product_call_and_checks_pass():
    docs, cards = _corpus_k()
    assert len(Impl._tokenize_topic_card(cards[0])) == 8
    res = _simulate(docs, cards, configs="base;k5:k=5;k8:k=8;k10:k=10")
    sums = {
        k: res["configs"][n]["all"]["items_sum"] for k, n in ((5, "k5"), (8, "k8"), (10, "k10"))
    }
    for k, got in sums.items():
        assert got == _direct_items_sum(docs, cards, k), k
    base_sum = res["configs"]["base"]["all"]["items_sum"]
    assert sums[5] < base_sum, "fixture must make K matter"
    # count never grows with K (composition need not nest: equal rounded scores)
    assert base_sum >= sums[5] >= sums[8] >= sums[10]
    kc = res["k_checks"]
    assert kc["derivation_mismatch"] == 0
    assert all(kc["product_checked"][k] > 0 for k in (5, 8, 10))
    assert not any(kc["product_mismatch"].values())
    assert sim.k_checks_ok(kc)
    assert _guard(docs, cards, res["_internal"])["ok"]


def test_k_self_check_catches_a_wrong_weight(monkeypatch):
    """Codex-proof: patching the script's W line (not the product) must fail the guard."""
    docs, cards = _corpus_k()

    def wrong(hits, strong):
        return len(hits & strong) + len(hits - strong) * 0.31

    monkeypatch.setattr(sim, "_weighted_hits", wrong)
    res = _simulate(docs, cards, configs="base;k5:k=5")
    assert res["_internal"]["k_checks"]["derivation_mismatch"] > 0
    guard = _guard(docs, cards, res["_internal"])
    assert not guard["ok"] and guard["k_checks"]["derivation_mismatch"] > 0


def test_k_checks_ok_requires_a_product_check_per_eligible_k():
    ok = {"derivation_mismatch": 0, "eligible_pairs": {5: 3}, "product_checked": {5: 3}}
    assert sim.k_checks_ok(ok)
    assert not sim.k_checks_ok(dict(ok, product_checked={5: 0}))
    assert not sim.k_checks_ok(dict(ok, product_mismatch={5: 1}))
    assert not sim.k_checks_ok(dict(ok, derivation_mismatch=1))
    assert sim.k_checks_ok({"derivation_mismatch": 0, "eligible_pairs": {8: 0}})


def test_topics_emptied_metrics_and_order_independence():
    docs, cards = _corpus_k()
    a = _simulate(docs, cards, configs="kbig:k=10,thr=0.6;k5:k=5")["configs"]
    b = _simulate(docs, cards, configs="k5:k=5;kbig:k=10,thr=0.6;base")["configs"]
    for name in ("kbig", "k5"):
        assert a[name]["all"] == b[name]["all"], name
    big = a["kbig"]["all"]
    # the wide topic (n = 8) is emptied (best doc: 4 strong hits / 8 = 0.5 < 0.6)
    assert big["topics_emptied"] == 1 and big["emptied_by_n"] == {"4_10": 1}
    assert big["emptied_n_max_base"] == 8 and big["topics_without_supporting"] >= 1
    assert a["base"]["all"]["topics_emptied"] == 0 and a["base"]["all"]["topics_halved"] == 0


def test_sample_topic_is_added_and_left_examples_show_cfg_score():
    docs, cards = _corpus_k()
    res = sim.simulate_channel(
        _data(docs, cards),
        sim.parse_configs("k10:k=10,thr=0.2"),
        extra_stop=frozenset(),
        cap=100,
        topk=3,
        phase1_thr=0.10,
        batch_size=25,
        feed_cap=200,
        resummarize_trigger=5,
        phase1_days=30,
        now=NOW,
        sample_topics=0,
        sample_configs={"k10"},
        sample_topic_ids=frozenset({_WIDE_ID}),
    )
    (topic,) = res["samples"]["k10"]
    assert topic["topic_id"] == _WIDE_ID and topic["n_keywords"] == 8
    assert topic["left_examples"], "k10 at 0.2 must drop something from the wide topic"
    assert all("cfg_score" in e for e in topic["left_examples"])


def test_resolve_channels_unknown_excluded_is_fatal(capsys):
    with pytest.raises(SystemExit) as exc:
        sim.resolve_channels(None, ["mediamedic"], ["Lab4health", "mediamedics"])
    assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert err == "" and "--exclude-channel" in _lines(out)[0]["msg"]
