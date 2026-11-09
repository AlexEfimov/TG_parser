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


def test_discover_backlog_arithmetic():
    assert sim.discover_calls_for_backlog(0, 200, 25) == {
        "ticks": 0,
        "calls": 0,
        "max_calls_per_tick": 0,
    }
    assert sim.discover_calls_for_backlog(450, 200, 25) == {
        "ticks": 3,
        "calls": 18,
        "max_calls_per_tick": 8,
    }
    assert sim.discover_calls_for_backlog(1, 200, 50)["calls"] == 1


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


def test_baseline_guard_passes_on_product_and_detects_divergence():
    docs, cards = _corpus()
    data = _data(docs, cards)
    ok = asyncio.run(
        sim.baseline_guard(
            _pipeline(cards), data, guard_topics=0, guard_docs=0, cap=100, topk=3, min_score=0.10
        )
    )
    assert ok["ok"], ok
    # a different cap than the product's makes the re-implementation diverge
    bad = asyncio.run(
        sim.baseline_guard(
            _pipeline(cards), data, guard_topics=0, guard_docs=0, cap=1, topk=3, min_score=0.10
        )
    )
    assert not bad["ok"]


def test_simulate_base_equals_product_bundles():
    docs, cards = _corpus()
    data = _data(docs, cards)
    res = sim.simulate_channel(
        data,
        sim.parse_configs("base;stop_r6a;cut_le"),
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
