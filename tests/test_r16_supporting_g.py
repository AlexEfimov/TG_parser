"""R16 / BUG-105 decision G: supporting = topk_denom with its own K (30) and cut ``le``.

Phase 1 is unchanged (decision 2a); keyword assignments carry ``bundle_score``
on the supporting K (owner decision on §2 p. 6.1, 2026-11-20).
"""

from __future__ import annotations

import itertools
import random
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.domain.models import (
    Anchor,
    BundleItemRole,
    MessageType,
    ProcessedDocument,
    TopicAssignment,
    TopicCard,
    TopicType,
)
from tg_parser.processing import topicization as topi
from tg_parser.processing.topicization import TopicizationPipelineImpl as Impl

CH = "labdiagnostica"
ANCHOR = f"tg:{CH}:post:1"


def _doc(n: int, *, strong=(), weak=(), summary: str | None = None) -> ProcessedDocument:
    ref = f"tg:{CH}:post:{n}"
    return ProcessedDocument(
        id=f"doc:{ref}",
        source_ref=ref,
        source_message_id=str(n),
        channel_id=CH,
        processed_at=datetime.now(UTC),
        text_clean=" ".join(weak) or "zz",
        summary=summary,
        topics=list(strong),
    )


def _card(scope_in: list[str], *, title: str | None = None, cid: str | None = None) -> TopicCard:
    return TopicCard(
        id=cid or f"topic:{ANCHOR}",
        title=title if title is not None else scope_in[0],
        summary="s",
        scope_in=scope_in,
        scope_out=["нерелевантное"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=CH,
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref=ANCHOR,
                score=0.9,
            )
        ],
        sources=[CH],
        updated_at=datetime.now(UTC),
    )


def _kws(n: int) -> list[str]:
    """``n`` distinct 4-letter tokens: no substring fallback (needs 5+ chars)."""
    letters = "бвгдклмнпрст"
    return ["".join(p) for p in itertools.islice(itertools.product(letters, repeat=4), n)]


def _pipeline() -> Impl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="pid")
    return Impl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=AsyncMock(),
        topic_bundle_repo=AsyncMock(),
    )


def _support(card, docs, **kw) -> list[tuple[str, float]]:
    items = _pipeline()._find_supporting_items_programmatic(
        topic_card=card, anchor_refs={ANCHOR}, documents=docs, **kw
    )
    return [(i.source_ref, i.score) for i in items]


def _hit_doc(kws: list[str], strong: int, weak: int, n: int = 2) -> ProcessedDocument:
    return _doc(n, strong=kws[:strong], weak=kws[strong : strong + weak])


# ---------------------------------------------------------------------------
# Defaults and boundaries
# ---------------------------------------------------------------------------


def test_defaults_are_decision_g():
    assert topi.SUPPORTING_KEYWORD_TOPK == 30
    assert topi.SUPPORTING_SCORE_CUT == "le"
    assert topi.ASSIGN_KEYWORD_TOPK == 3  # Phase 1 untouched (decision 2a)
    assert topi.MIN_SUPPORTING_SCORE == pytest.approx(0.10)


def test_n40_one_strong_hit_dropped():
    kws = _kws(40)
    assert _support(_card(kws), [_hit_doc(kws, 1, 0)]) == []  # 1/30


def test_n10_one_strong_exactly_threshold_dropped_two_kept():
    kws = _kws(10)
    card = _card(kws)
    assert _support(card, [_hit_doc(kws, 1, 0)]) == []  # 1/10 = 0.10, `le` drops it
    assert _support(card, [_hit_doc(kws, 2, 0)]) == [(f"tg:{CH}:post:2", 0.2)]


def test_one_weak_hit_at_threshold_dropped():
    kws = _kws(3)
    assert _support(_card(kws), [_hit_doc(kws, 0, 1)]) == []  # 0.3 / 3 = 0.10


def test_n_over_30_weight_3_dropped_3_1_kept():
    kws = _kws(45)
    card = _card(kws)
    assert _support(card, [_hit_doc(kws, 3, 0)]) == []  # W = 3.0 → 3/30 = 0.10
    assert _support(card, [_hit_doc(kws, 0, 10)]) == []  # W = 10 × 0.3 = 3.0
    assert _support(card, [_hit_doc(kws, 1, 7)]) == [(f"tg:{CH}:post:2", 0.103)]  # W = 3.1


def test_denominator_is_min_n_30():
    doc_kws = 3  # W = 3 strong hits
    k29, k31 = _kws(29), _kws(31)
    assert _support(_card(k29), [_hit_doc(k29, doc_kws, 0)]) == [
        (f"tg:{CH}:post:2", round(3 / 29, 3))
    ]
    assert _support(_card(k31), [_hit_doc(k31, doc_kws, 0)]) == []  # 3/30 = 0.10


def test_meaningful_hits_and_abbreviations_kept():
    card = _card(["СОЭ", "IgE", "анализ крови"], title="СОЭ и IgE")
    # 3-letter abbreviations are tokens (MIN_TOKEN_LENGTH = 3); "и" is not
    assert Impl._tokenize_topic_card(card) == {"соэ", "ige", "анализ", "крови"}
    docs = [
        _doc(2, strong=["СОЭ"]),  # 1/4
        _doc(3, strong=["IgE", "анализ"]),  # 2/4
        _doc(4, strong=["погода"]),  # no hit
    ]
    assert _support(card, docs) == [(f"tg:{CH}:post:3", 0.5), (f"tg:{CH}:post:2", 0.25)]


def test_substring_fallback_hit():
    card = _card(["гемоглобин", "ферритин"], title="гемоглобин")
    # doc token "гемоглобина" ⊃ "гемоглобин": fallback hit, weighted as weak (0.3/2)
    docs = [_doc(2, strong=["гемоглобина"])]
    assert _support(card, docs) == [(f"tg:{CH}:post:2", 0.15)]


def test_substring_fallback_rewrite_same_hits_as_pair_loop():
    """R16 perf rewrite of the fallback: same hit set as the original pair loop."""

    def original(topic_keywords, doc_tokens):
        hits = set()
        for kw in topic_keywords:
            for dt in doc_tokens:
                if len(kw) >= 5 and len(dt) >= 5 and (kw in dt or dt in kw):
                    hits.add(kw)
                    break
        return hits

    rng = random.Random(3)
    alphabet = "абвгд"
    for _ in range(300):
        kws = {"".join(rng.choice(alphabet) for _ in range(rng.randint(3, 8))) for _ in range(8)}
        toks = {"".join(rng.choice(alphabet) for _ in range(rng.randint(3, 9))) for _ in range(10)}
        toks -= kws  # force the fallback branch (no exact hit)
        _score, hits = Impl._compute_match_score(kws, toks, set())
        assert hits == original(kws, toks)


# ---------------------------------------------------------------------------
# Rollback knob, tie-break, metadata
# ---------------------------------------------------------------------------


def _pre_r16_reference(card, docs) -> list[tuple[str, float]]:
    """The pre-R16 product body: Phase-1 K, ``score < thr`` rejected, stable sort."""
    kws = Impl._tokenize_topic_card(card)
    out = []
    for d in docs:
        if d.source_ref == ANCHOR:
            continue
        s, w = Impl._tokenize_document(d)
        score, _ = Impl._compute_match_score(kws, s, w, topk=3)
        if score < topi.MIN_SUPPORTING_SCORE:
            continue
        out.append((d.source_ref, score))
    out.sort(key=lambda x: -x[1])
    return out[: topi.MAX_SUPPORTING_ITEMS]


def _random_corpus(seed: int, n_docs: int = 150):
    rng = random.Random(seed)
    vocab = _kws(60)
    cards = [
        _card(rng.sample(vocab, rng.choice([2, 5, 12, 40])), cid=f"topic:{i}") for i in range(6)
    ]
    docs = [
        _doc(
            n,
            strong=rng.sample(vocab, rng.randint(0, 4)),
            weak=rng.sample(vocab, rng.randint(0, 6)),
        )
        for n in range(2, 2 + n_docs)
    ]
    docs.sort(key=lambda d: d.source_ref)  # DB order (list_by_channel: source_ref ASC)
    return cards, docs


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_explicit_pre_r16_args_reproduce_old_selection(seed):
    cards, docs = _random_corpus(seed)
    for card in cards:
        assert _support(card, docs, topk=3, cut="lt") == _pre_r16_reference(card, docs)


def test_env_rollback_constants_reproduce_old_selection(monkeypatch):
    """K=3 + cut=lt via the module constants (what the env knobs set)."""
    monkeypatch.setattr(topi, "SUPPORTING_KEYWORD_TOPK", 3)
    monkeypatch.setattr(topi, "SUPPORTING_SCORE_CUT", "lt")
    cards, docs = _random_corpus(4)
    for card in cards:
        assert _support(card, docs) == _pre_r16_reference(card, docs)


def test_supporting_k_read_at_call_time_not_phase1_k(monkeypatch):
    """The 'two K' trap: supporting must not silently use ASSIGN_KEYWORD_TOPK."""
    kws = _kws(40)
    card = _card(kws)
    doc = _hit_doc(kws, 4, 0)  # W = 4
    assert _support(card, [doc]) == [(f"tg:{CH}:post:2", round(4 / 30, 3))]
    monkeypatch.setattr(topi, "ASSIGN_KEYWORD_TOPK", 7)
    assert _support(card, [doc]) == [(f"tg:{CH}:post:2", round(4 / 30, 3))]
    monkeypatch.setattr(topi, "SUPPORTING_KEYWORD_TOPK", 20)
    assert _support(card, [doc]) == [(f"tg:{CH}:post:2", 0.2)]


def test_unknown_cut_rejected():
    kws = _kws(3)
    with pytest.raises(ValueError):
        _support(_card(kws), [_hit_doc(kws, 2, 0)], cut="ge")


def test_cap_ties_break_by_source_ref_not_input_order(monkeypatch):
    monkeypatch.setattr(topi, "MAX_SUPPORTING_ITEMS", 5)
    kws = _kws(4)
    card = _card(kws)
    docs = [_doc(n, strong=kws[:2]) for n in range(2, 14)]  # all 2/4 = 0.5
    expected = sorted(d.source_ref for d in docs)[:5]
    for seed in range(5):
        shuffled = docs[:]
        random.Random(seed).shuffle(shuffled)
        assert [r for r, _ in _support(card, shuffled)] == expected


def test_token_cache_gives_identical_result():
    cards, docs = _random_corpus(5)
    cache = {d.source_ref: Impl._tokenize_document(d) for d in docs}
    for card in cards:
        assert _support(card, docs, doc_tokens=cache) == _support(card, docs)


def test_bundle_metadata_carries_scoring_parameters():
    kws = _kws(5)
    bundle = _pipeline()._compute_topic_bundle(_card(kws), CH, [_doc(1), _hit_doc(kws, 2, 0)])
    params = bundle.metadata["parameters"]
    assert params["supporting_keyword_topk"] == 30
    assert params["supporting_score_cut"] == "le"
    assert params["keyword_aggregation"] == "topk_denom"
    assert params["min_supporting_score"] == pytest.approx(0.10)


def test_stoplist_is_untouched_and_not_applied_to_supporting():
    """Decision 3: KEYWORD_STOPLIST stays bit for bit; supporting has no stoplist."""
    from tg_parser.services.analytics_service import KEYWORD_STOPLIST, _extract_keywords

    assert KEYWORD_STOPLIST == frozenset(
        "для при как его её их это этой этот или чем что чтобы также "
        "the and for with from that this are was were".split()
    )
    card = _card(["для анализа крови"], title="для")
    assert _extract_keywords(card) == {"анализа", "крови"}
    assert "для" in Impl._tokenize_topic_card(card)


# ---------------------------------------------------------------------------
# Phase 1 (decision 2a) + bundle_score (§2 p. 6.1 = A)
# ---------------------------------------------------------------------------


def _pre_r16_phase1(cards, docs):
    kw_sets = [(c, Impl._tokenize_topic_card(c)) for c in cards]
    kw_sets = [(c, k) for c, k in kw_sets if k]
    out, unassigned = [], []
    for d in docs:
        s, w = Impl._tokenize_document(d)
        best, best_id = 0.0, None
        for c, k in kw_sets:
            score, _ = Impl._compute_match_score(k, s, w)
            if score > best:
                best, best_id = score, c.id
        if best_id is not None and best >= topi.MIN_SUPPORTING_SCORE:
            out.append((d.source_ref, best_id, best))
        else:
            unassigned.append(d.source_ref)
    return out, unassigned


@pytest.mark.parametrize("seed", [6, 7])
def test_phase1_selection_unchanged_and_bundle_score_on_supporting_k(seed):
    cards, docs = _random_corpus(seed)
    got, unassigned = _pipeline().assign_documents_with_cards(docs, cards)
    ref, ref_unassigned = _pre_r16_phase1(cards, docs)
    assert [(a.source_ref, a.topic_id, a.score) for a in got] == ref
    assert unassigned == ref_unassigned
    by_id = {c.id: c for c in cards}
    docs_by_ref = {d.source_ref: d for d in docs}
    assert got, "fixture must assign something"
    for a in got:
        s, w = Impl._tokenize_document(docs_by_ref[a.source_ref])
        expected, _ = Impl._compute_match_score(
            Impl._tokenize_topic_card(by_id[a.topic_id]), s, w, topk=30
        )
        assert a.bundle_score == expected
        assert a.method == "keyword"


def test_phase1_async_wrapper_uses_repo_cards():
    kws = _kws(40)
    card = _card(kws)
    pipe = _pipeline()
    pipe.topic_card_repo.list_by_channel = AsyncMock(return_value=[card])
    doc = _hit_doc(kws, 1, 0)
    import asyncio

    assigned, unassigned = asyncio.run(pipe.assign_documents_to_topics([doc], CH))
    # Phase 1: 1/min(40, 3) = 0.333 ≥ 0.10 → assigned; bundle on K=30: 1/30
    assert [(a.score, a.bundle_score) for a in assigned] == [(0.333, 0.033)]
    assert unassigned == []


@pytest.mark.asyncio
async def test_update_bundles_writes_bundle_score_and_keeps_phase1_in_justification():
    from tg_parser.services.topicization_service import _update_bundles_for_assignments

    repo = AsyncMock()
    a_kw = TopicAssignment(
        source_ref=f"tg:{CH}:post:2",
        topic_id="topic:x",
        score=0.333,
        method="keyword",
        bundle_score=0.033,
    )
    a_zero = TopicAssignment(
        source_ref=f"tg:{CH}:post:3",
        topic_id="topic:x",
        score=0.5,
        method="keyword",
        bundle_score=0.0,
    )
    a_plain = SimpleNamespace(source_ref=f"tg:{CH}:post:4", topic_id="topic:x", score=0.7)
    docs = {
        r: _doc(int(r.rsplit(":", 1)[1]))
        for r in (a_kw.source_ref, a_zero.source_ref, a_plain.source_ref)
    }
    await _update_bundles_for_assignments([a_kw, a_zero, a_plain], docs, repo, method="keyword")
    (topic_id, items), _ = repo.add_items.await_args
    assert topic_id == "topic:x"
    got = {i.source_ref: (i.score, i.justification) for i in items}
    assert got == {
        a_kw.source_ref: (0.033, "incremental keyword assign (score=0.333)"),
        a_zero.source_ref: (0.0, "incremental keyword assign (score=0.5)"),  # 0.0 is a score
        a_plain.source_ref: (0.7, "incremental keyword assign (score=0.7)"),  # no field
    }
    assert all(i.role == BundleItemRole.SUPPORTING for i in items)


@pytest.mark.asyncio
async def test_reconcile_path_writes_bundle_score():
    """BUG-075 reconcile goes through the same incremental body → bundle_score lands."""
    from tg_parser.services.topicization_service import _run_incremental_topicization_locked

    ref = f"tg:{CH}:post:9"
    doc = _doc(9)
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: doc if r == ref else None
    processed_repo.list_by_channel.return_value = [doc]
    card = MagicMock()
    card.id = "topic:x"
    card_repo = AsyncMock()
    card_repo.list_by_channel.return_value = [card]
    bundle_repo = AsyncMock()
    bundle_repo.list_by_channel.return_value = []
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    inst = MagicMock()
    inst.assign_documents_to_topics = AsyncMock(
        return_value=(
            [
                TopicAssignment(
                    source_ref=ref,
                    topic_id="topic:x",
                    score=0.333,
                    method="keyword",
                    bundle_score=0.042,
                )
            ],
            [],
        )
    )
    inst._discover_single_batch = AsyncMock(return_value=([], [], [], 0))
    inst.rejection_breakdown = {}
    llm = AsyncMock()
    with (
        patch(
            "tg_parser.services.topicization_service.TopicizationPipelineImpl",
            MagicMock(return_value=inst),
        ),
        patch(
            "tg_parser.services.topicization_service.resolve_llm_config",
            return_value=("openai", "key", "model"),
        ),
        patch("tg_parser.services.topicization_service.create_llm_client", return_value=llm),
    ):
        await _run_incremental_topicization_locked(
            CH,
            [ref],
            cross_channel=False,
            reconcile_only=True,
            processed_repo=processed_repo,
            topic_card_repo=card_repo,
            topic_bundle_repo=bundle_repo,
            failure_repo=failure_repo,
        )
    (topic_id, items), _ = bundle_repo.add_items.await_args
    assert topic_id == "topic:x"
    assert [(i.source_ref, i.score) for i in items] == [(ref, 0.042)]
