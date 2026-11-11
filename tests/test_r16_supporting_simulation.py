"""R16 / BUG-105 — the supporting simulation script measures the product, not a copy.

The script re-implements only the threshold / sort / cap of
``_find_supporting_items_programmatic`` and models a stoplist as a set filter on
the product tokenizer output. These tests pin both claims against the product
code, plus the pure arithmetic the forecast tables rely on. No DB.
"""

from __future__ import annotations

import asyncio
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
    assert r["calls_worst_case"] == 4  # misses packed into the first feed
    # deterministic for a fixed seed
    assert sim.reconcile_drain(flags, 200, 25) == r


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


def test_read_only_guard():
    sim.check_read_only("on")
    with pytest.raises(SystemExit):
        sim.check_read_only("off")
    with pytest.raises(SystemExit):
        sim.check_read_only(None)


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
