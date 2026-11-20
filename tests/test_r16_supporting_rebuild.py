"""R16 / BUG-105 stage B: ``tg-parser topic rebuild-supporting`` (no LLM).

Pure core (no DB) + PostgreSQL modes (``TEST_POSTGRES=1``) + the CLI surface.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    ProcessedDocument,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing import topicization as topi
from tg_parser.processing.topicization import TopicizationPipelineImpl as Impl
from tg_parser.services import supporting_rebuild_service as svc

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

CH = "ch"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _ref(n: int, ch: str = CH) -> str:
    return f"tg:{ch}:post:{n}"


def _doc(n: int, *, strong=(), weak="", summary="") -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{_ref(n)}",
        source_ref=_ref(n),
        source_message_id=str(n),
        channel_id=CH,
        processed_at=NOW,
        text_clean=weak or "zz",
        summary=summary or None,
        topics=list(strong),
    )


def _card(n: int, title: str, scope_in: list[str]) -> TopicCard:
    return TopicCard(
        id=f"topic:{_ref(n)}",
        title=title,
        summary="s",
        scope_in=scope_in,
        scope_out=["нерелевантное"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=CH,
                message_id=str(n),
                message_type=MessageType.POST,
                anchor_ref=_ref(n),
                score=0.9,
            )
        ],
        sources=[CH],
        updated_at=NOW,
    )


def _item(ref: str, *, role=BundleItemRole.SUPPORTING, score=0.5, why="keyword overlap: x"):
    parts = ref.split(":")
    return BundleItem(
        channel_id=parts[1],
        message_id=parts[3],
        message_type=MessageType(parts[2]),
        source_ref=ref,
        role=role,
        score=score,
        justification=None if role == BundleItemRole.ANCHOR else why,
    )


def _anchor(ref: str) -> BundleItem:
    return _item(ref, role=BundleItemRole.ANCHOR, score=0.9)


def _bundle(topic_id: str, items, *, channels=(CH,), metadata=None) -> TopicBundle:
    return TopicBundle(
        topic_id=topic_id,
        items=list(items),
        updated_at=NOW,
        channels=list(channels),
        metadata=metadata if metadata is not None else {"model_id": "claude-old"},
    )


LLM = "incremental llm assign (score=0.8)"
T1, T2, T3, T4 = (f"topic:{_ref(n)}" for n in (1, 2, 20, 21))


def _fixture() -> svc.ChannelSnapshot:
    """A channel exercising every branch of the core (see the comments per doc)."""
    docs = [
        _doc(1),  # anchor T1
        _doc(2),  # anchor T2
        _doc(3, strong=["анализ", "крови"]),  # T1 formula 2/3
        _doc(4, strong=["гормоны"]),  # T2 formula 1/3
        _doc(5, weak="крови"),  # T1 0.3/3 = 0.10 → out under `le`; Phase 1 keeps → 4a
        _doc(6, summary="погода"),  # LLM item in old T2 → kept
        _doc(7, strong=["анализ", "гемоглобин"]),  # formula T1 AND old LLM in T1 → LLM wins
        _doc(9, summary="погода"),  # old T2 keyword assign, no hit now → fallback T2
        _doc(10, summary="погода"),  # old T1 and T2, same old score → fallback min topic_id
        _doc(11, summary="погода"),  # old T1 0.2 / T2 0.4 → fallback T2 (old score)
        _doc(12, summary="погода"),  # only in a bundle without a card → stays covered
        _doc(13, strong=["витамин"]),  # Phase 1 best = T3 (skipped card) → fallback T1
        _doc(20),  # anchor T3
        _doc(21),  # anchor T4
    ]
    cards = [
        _card(1, "анализ крови", ["гемоглобин"]),
        _card(2, "щитовидная железа", ["гормоны"]),
        _card(20, "витамин", ["витамин"]),  # stored bundle is foreign → card skipped
        _card(21, "диета", ["диета"]),  # no stored bundle → built
    ]
    bundles = [
        _bundle(
            T1,
            [
                _anchor(_ref(1)),
                _item(_ref(3)),
                _item(_ref(5), score=0.333),
                _item(_ref(7), score=0.8, why=LLM),
                _item(_ref(99), score=0.8, why=LLM),  # orphan: no such document
                _item(_ref(10), score=0.5),
                _item(_ref(11), score=0.2),
                _item(_ref(13), score=0.3),
            ],
        ),
        _bundle(
            T2,
            [
                _anchor(_ref(2)),
                _item(_ref(6), score=0.8, why=LLM),
                _item(_ref(2), score=0.8, why=LLM),  # LLM duplicate of the anchor
                _item(_ref(9), score=0.4, why="incremental keyword assign (score=0.4)"),
                _item(_ref(10), score=0.5),
                _item(_ref(11), score=0.4),
            ],
        ),
        _bundle("topic:no-card", [_item(_ref(12))]),
        _bundle(T3, [_anchor(_ref(20))], channels=("other", CH)),
    ]
    return svc.ChannelSnapshot(CH, docs, cards, bundles)


def _pipeline() -> Impl:
    return svc._make_pipeline(AsyncMock(), AsyncMock(), AsyncMock())


def _items(result, topic_id):
    b = next(b for b in result.bundles if b.topic_id == topic_id)
    return [(i.source_ref, i.role.value, i.score, i.justification) for i in b.items]


def test_core_rebuilds_each_card_by_g_with_llm_and_4a():
    res = svc.rebuild_channel_bundles(_fixture(), _pipeline(), now=NOW)
    assert {b.topic_id for b in res.bundles} == {T1, T2, T4}  # T3 skipped, no-card untouched

    assert _items(res, T1) == [
        (_ref(1), "anchor", 0.9, None),
        (_ref(7), "supporting", 0.8, LLM),  # LLM wins over the formula item
        (_ref(3), "supporting", 0.667, "keyword overlap: анализ, крови"),
        (_ref(5), "supporting", 0.1, "rebuild coverage keep: крови"),  # 4a, K=30 score
        (_ref(10), "supporting", 0.0, "rebuild coverage keep (fallback)"),  # min topic_id
        (_ref(13), "supporting", 0.0, "rebuild coverage keep (fallback)"),  # best = skipped T3
    ]
    assert _items(res, T2) == [
        (_ref(2), "anchor", 0.9, None),  # anchor wins over the LLM duplicate
        (_ref(6), "supporting", 0.8, LLM),
        (_ref(4), "supporting", 0.333, "keyword overlap: гормоны"),
        (_ref(11), "supporting", 0.0, "rebuild coverage keep (fallback)"),  # old 0.4 > 0.2
        (_ref(9), "supporting", 0.0, "rebuild coverage keep (fallback)"),
    ]
    assert [i[0] for i in _items(res, T4)] == [_ref(21)]

    final = res.report["final"]
    assert final["previously_covered_now_uncovered"] == 0
    assert final["coverage_lost"] == 0
    assert final["coverage_kept"] == 1
    assert final["coverage_fallback"] == 4
    assert final["llm_kept"] == 2
    assert final["llm_orphans_dropped"] == 1
    assert final["llm_replaced_formula_item"] == 1
    assert final["cards_without_bundle"] == 1
    assert final["bundles_without_card"] == 1
    assert final["foreign_bundles_skipped"] == 1
    assert final["cards_skipped_foreign_bundle"] == 1


def test_core_skips_multichannel_bundle_even_with_this_channel_first():
    snap = _fixture()
    bundles = [
        _bundle(T3, [_anchor(_ref(20))], channels=(CH, "other")) if b.topic_id == T3 else b
        for b in snap.bundles
    ]
    res = svc.rebuild_channel_bundles(
        svc.ChannelSnapshot(CH, snap.docs, snap.cards, bundles), _pipeline(), now=NOW
    )
    assert {b.topic_id for b in res.bundles} == {T1, T2, T4}
    assert res.report["final"]["foreign_bundles_skipped"] == 1
    assert res.report["final"]["cards_skipped_foreign_bundle"] == 1
    assert T3 not in res.fingerprint["bundles"]


def test_core_left_alone_bundle_keeps_coverage_without_4a():
    # doc 13 sits in old T1 and in the multi-channel T3, which is not rebuilt:
    # it stays covered by T3, so 4a must not add it to T1.
    snap = _fixture()
    t3 = _bundle(T3, [_anchor(_ref(20)), _item(_ref(13), score=0.3)], channels=(CH, "other"))
    bundles = [t3 if b.topic_id == T3 else b for b in snap.bundles]
    res = svc.rebuild_channel_bundles(
        svc.ChannelSnapshot(CH, snap.docs, snap.cards, bundles), _pipeline(), now=NOW
    )
    assert _ref(13) not in [i[0] for i in _items(res, T1)]
    final = res.report["final"]
    assert final["coverage_fallback"] == 3
    assert final["previously_covered_now_uncovered"] == 0


def test_fingerprint_sees_a_change_of_a_foreign_bundle_content():
    snap = _fixture()
    fp = svc.channel_fingerprint(CH, snap.cards, snap.bundles)
    changed = [
        _bundle(T3, [_anchor(_ref(20)), _item(_ref(13))], channels=("other", CH))
        if b.topic_id == T3
        else b
        for b in snap.bundles
    ]
    assert svc.channel_fingerprint(CH, snap.cards, changed) != fp


def test_core_metadata_carries_model_and_rebuild_block():
    res = svc.rebuild_channel_bundles(_fixture(), _pipeline(), now=NOW)
    by_id = {b.topic_id: b for b in res.bundles}
    assert by_id[T1].metadata["model_id"] == "claude-old"
    assert by_id[T4].metadata["model_id"] == svc.NO_MODEL_ID
    assert by_id[T1].metadata["rebuild"] == {
        "tool": "rebuild-supporting",
        "at": NOW.isoformat(),
        "llm_kept": 1,
        "coverage_kept": 1,
        "coverage_fallback": 2,
    }
    params = by_id[T1].metadata["parameters"]
    assert (params["supporting_keyword_topk"], params["supporting_score_cut"]) == (30, "le")
    assert by_id[T1].channels == [CH]


def test_core_is_idempotent():
    snap = _fixture()
    first = svc.rebuild_channel_bundles(snap, _pipeline(), now=NOW)
    left = [b for b in snap.bundles if b.topic_id not in {x.topic_id for x in first.bundles}]
    again = svc.rebuild_channel_bundles(
        svc.ChannelSnapshot(CH, snap.docs, snap.cards, first.bundles + left),
        _pipeline(),
        now=NOW,
    )
    for b in first.bundles:
        assert _items(again, b.topic_id) == _items(first, b.topic_id)
    # 4a items are not formula items, so they are candidates again — and land
    # in the same topics with the same labels (asserted above)
    assert (
        again.report["final"]["coverage_candidates"] == first.report["final"]["coverage_candidates"]
    )
    assert again.report["final"]["previously_covered_now_uncovered"] == 0


def test_core_4a_may_exceed_the_cap(monkeypatch):
    monkeypatch.setattr(topi, "MAX_SUPPORTING_ITEMS", 1)
    res = svc.rebuild_channel_bundles(_fixture(), _pipeline(), now=NOW)
    sup = [i for i in _items(res, T1) if i[1] == "supporting"]
    formula = [i for i in sup if i[3].startswith("keyword overlap")]
    assert len(formula) == 1  # the cap still limits the formula
    assert len(sup) > 1  # LLM + 4a go past it (as add_items does)
    assert res.report["final"]["topics_over_cap"] >= 1


def _fixture_with_foreign_coverage() -> svc.ChannelSnapshot:
    # doc 30: only in the foreign T3 (other first) — not "previously covered" for
    # the script; doc 31: an LLM item of a multi-channel bundle with CH first —
    # the script counts it (first channel = CH).
    snap = _fixture()
    docs = [*snap.docs, _doc(30, summary="погода"), _doc(31, summary="погода")]
    bundles = [
        _bundle(T3, [_anchor(_ref(20)), _item(_ref(30))], channels=("other", CH))
        if b.topic_id == T3
        else b
        for b in snap.bundles
    ]
    bundles.append(
        _bundle("topic:multi", [_item(_ref(31), score=0.8, why=LLM)], channels=(CH, "other"))
    )
    return svc.ChannelSnapshot(CH, docs, snap.cards, bundles)


@pytest.mark.parametrize("make", [_fixture, _fixture_with_foreign_coverage])
def test_core_report_matches_simulation_definitions(make):
    """The comparable block uses the R16 simulation's definitions (§10.7)."""
    from scripts import r16_supporting_simulation as sim

    snap = make()
    own = [b for b in snap.bundles if (b.channels or [CH])[0] == CH]
    res = svc.rebuild_channel_bundles(snap, _pipeline(), now=NOW)
    out = sim.simulate_channel(
        sim.ChannelData(CH, snap.docs, snap.cards, own, set()),
        sim.parse_configs("base;k30:k=30,cut=le"),
        extra_stop=frozenset(),
        cap=topi.MAX_SUPPORTING_ITEMS,
        topk=topi.ASSIGN_KEYWORD_TOPK,
        phase1_thr=0.10,
        batch_size=25,
        feed_cap=200,
        resummarize_trigger=5,
        phase1_days=30,
        now=NOW,
        sample_topics=0,
        sample_configs=set(),
    )
    k30 = out["configs"]["k30"]
    g = res.report["simulation_g"]
    for key in ("topics", "items_sum", "sat_cap", "topics_per_doc", "topics_without_supporting"):
        assert g[key] == k30["all"][key], key
    assert g["uncovered_previously_covered"] == k30["door2"]["uncovered_previously_covered"]
    assert g["uncovered_kw_only"] == k30["door2"]["uncovered_kw_only"]


def test_core_with_base_reports_pre_r16_block():
    res = svc.rebuild_channel_bundles(_fixture(), _pipeline(), now=NOW, with_base=True)
    base = res.report["simulation_base_pre_r16"]
    # doc 5 (one weak hit, 0.10) is supporting only under the pre-R16 formula
    assert base["items_sum"] == res.report["simulation_g"]["items_sum"] + 1
    assert set(res.report["simulation_g"]["vs_base"]) == {"topics_emptied", "topics_halved"}


def test_effective_settings_line():
    eff = svc.effective_settings()
    assert eff["supporting_keyword_topk"] == 30
    assert eff["supporting_score_cut"] == "le"
    assert eff["assign_keyword_topk"] == 3


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_requires_channel():
    from typer.testing import CliRunner

    from tg_parser.cli.app import app

    r = CliRunner().invoke(app, ["topic", "rebuild-supporting"])
    assert r.exit_code == 2
    assert "--channel" in r.output


def test_cli_dry_run_emits_jsonl_and_restores_logging(monkeypatch):
    import logging

    import structlog
    from typer.testing import CliRunner

    from tg_parser.cli.app import app

    seen = {}

    async def fake_dry(channels, *, emit, with_base):
        seen.update(channels=channels, with_base=with_base)
        structlog.get_logger("tg_parser.test").warning("product_warning", x=1)
        structlog.get_logger("tg_parser.test").info("product_info_dropped")
        emit({"type": "channel", "channel_id": channels[0], "mode": "dry-run"})
        return 0

    monkeypatch.setattr(svc, "run_dry", fake_dry)
    before = (structlog.get_config(), logging.getLogger().handlers[:])
    r = CliRunner().invoke(
        app, ["topic", "rebuild-supporting", "--channel", "https://t.me/Some_Channel"]
    )
    assert r.exit_code == 0, r.output
    lines = [json.loads(line) for line in r.output.splitlines()]
    assert [o["type"] for o in lines] == ["meta", "lib_log", "channel", "summary"]
    assert lines[0]["mode"] == "dry-run" and lines[0]["effective"]["supporting_keyword_topk"] == 30
    assert lines[1]["event"] == "product_warning" and lines[1]["level"] == "warning"
    assert seen == {"channels": ["Some_Channel"], "with_base": False}
    assert (structlog.get_config(), logging.getLogger().handlers[:]) == before


def test_cli_failure_is_a_fatal_jsonl_line(monkeypatch):
    from typer.testing import CliRunner

    from tg_parser.cli.app import app

    async def boom(channels, *, emit, with_base):
        raise svc.RebuildRefused("default_transaction_read_only='off', expected 'on'")

    monkeypatch.setattr(svc, "run_dry", boom)
    r = CliRunner().invoke(app, ["topic", "rebuild-supporting", "--channel", "x"])
    assert r.exit_code == 3
    lines = [json.loads(line) for line in r.output.splitlines()]
    assert lines[-2]["type"] == "fatal" and "expected 'on'" in lines[-2]["msg"]
    assert lines[-1] == {"type": "summary", "exit_code": 3, "maxrss_mb": lines[-1]["maxrss_mb"]}


# ---------------------------------------------------------------------------
# PostgreSQL: dry-run read-only, write, guards
# ---------------------------------------------------------------------------


async def _seed(db, snap: svc.ChannelSnapshot) -> None:
    from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
    from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

    async with db.processing_storage_session() as session:
        for d in snap.docs:
            await SAProcessedDocumentRepo(session).upsert(d)
        for c in snap.cards:
            await SATopicCardRepo(session).upsert(c)
        for b in snap.bundles:
            await SATopicBundleRepo(session).upsert(b)
        await session.execute(
            text("UPDATE topic_cards SET new_items_since_last_summary = 7 WHERE id = :id"),
            {"id": T1},
        )
        await session.commit()


async def _state(db) -> tuple:
    async with db.processing_storage_session() as session:
        bundles = (
            await session.execute(
                text(
                    "SELECT topic_id, items_json, metadata_json FROM topic_bundles ORDER BY topic_id"
                )
            )
        ).fetchall()
        counters = (
            await session.execute(
                text("SELECT id, new_items_since_last_summary FROM topic_cards ORDER BY id")
            )
        ).fetchall()
    return [tuple(r) for r in bundles], [tuple(r) for r in counters]


def _collector():
    lines: list[dict] = []
    return lines, lines.append


@pg_only
@pytest.mark.asyncio
async def test_pg_dry_run_is_read_only_and_reports(test_db):
    await _seed(test_db, _fixture())
    before = await _state(test_db)
    lines, emit = _collector()
    engine = svc.make_read_only_engine(test_db.settings)
    try:
        rc = await svc.run_dry([CH, "nope"], emit=emit, engine=engine)
    finally:
        await engine.dispose()
    assert lines[0] == {"type": "read_only_check", "default_transaction_read_only": "on"}
    report = next(o for o in lines if o.get("channel_id") == CH)
    assert report["mode"] == "dry-run" and report["final"]["bundles_rebuilt"] == 3
    assert {"type": "channel", "channel_id": "nope", "error": "unknown_channel"} in lines
    assert rc == 2
    assert await _state(test_db) == before


@pg_only
@pytest.mark.asyncio
async def test_pg_dry_run_refuses_a_writable_connection(test_db):
    from sqlalchemy.ext.asyncio import create_async_engine

    from tg_parser.storage.engine_factory import create_postgres_engine_config

    s = test_db.settings
    cfg = create_postgres_engine_config(
        host=s.db_host, port=s.db_port, database=s.db_name, user=s.db_user, password=s.db_password
    )
    engine = create_async_engine(cfg.url, pool_size=1, max_overflow=0)
    lines, emit = _collector()
    try:
        with pytest.raises(svc.RebuildRefused):
            await svc.run_dry([CH], emit=emit, engine=engine)
    finally:
        await engine.dispose()
    assert lines == [{"type": "read_only_check", "default_transaction_read_only": "off"}]


@pg_only
@pytest.mark.asyncio
async def test_pg_write_rebuilds_without_counter_and_is_idempotent(test_db):
    snap = _fixture()
    await _seed(test_db, snap)
    (_bundles0, counters0) = await _state(test_db)
    lines, emit = _collector()
    assert await svc.run_write([CH], emit=emit) == 0
    report = lines[-1]
    assert report["written"] == 3 and report["reverted_topics_count"] == 0
    bundles1, counters1 = await _state(test_db)
    assert counters1 == counters0  # F5-C counter untouched (upsert, not add_items)

    expected = svc.rebuild_channel_bundles(snap, _pipeline(), now=NOW)
    by_id = {row[0]: json.loads(row[1]) for row in bundles1}
    for b in expected.bundles:
        assert [i["source_ref"] for i in by_id[b.topic_id]] == [i.source_ref for i in b.items]
    assert [i["source_ref"] for i in by_id["topic:no-card"]] == [_ref(12)]  # untouched
    covered = {i["source_ref"] for items in by_id.values() for i in items}
    assert {_ref(n) for n in (3, 4, 5, 6, 7, 9, 10, 11, 12, 13)} <= covered

    lines2, emit2 = _collector()
    assert await svc.run_write([CH], emit=emit2) == 0
    bundles2, _ = await _state(test_db)
    items1 = {row[0]: row[1] for row in bundles1}
    items2 = {row[0]: row[1] for row in bundles2}
    assert items2 == items1  # same items on a second run


@pg_only
@pytest.mark.asyncio
async def test_pg_write_skips_live_full_checkpoint(test_db, monkeypatch):
    from tg_parser.config import settings
    from tg_parser.processing.topicization_checkpoint import (
        FULL_CHECKPOINT_ERROR_CLASS,
        FullRunCheckpoint,
        full_checkpoint_marker_ref,
    )
    from tg_parser.storage.sqlalchemy.processing_failure_repo import SAProcessingFailureRepo

    await _seed(test_db, _fixture())
    cp = FullRunCheckpoint(
        run_id="fullrun_x",
        planned_refs=[_ref(1)],
        planned_ref_hash="h",
        planned_doc_count=1,
        chunk_batches=1,
        chunks_total=2,
        chunks_done=1,
        batches_done=1,
        tokens_spent_cumulative=10,
        final_merge_done=False,
    )
    async with test_db.processing_storage_session() as session:
        await SAProcessingFailureRepo(session).record_failure(
            full_checkpoint_marker_ref(CH),
            CH,
            1,
            FULL_CHECKPOINT_ERROR_CLASS,
            "checkpoint",
            cp.to_details(),
        )
    monkeypatch.setattr(settings, "topicization_full_resume_enabled", True)
    before = await _state(test_db)
    lines, emit = _collector()
    assert await svc.run_write([CH], emit=emit) == 4
    assert lines[-1]["skipped"] == "live_full_checkpoint"
    assert await _state(test_db) == before


@pg_only
@pytest.mark.asyncio
async def test_pg_write_skips_when_incremental_lock_held(test_db):
    from tg_parser.services.topicization_service import channel_incremental_topicization_lock

    await _seed(test_db, _fixture())
    before = await _state(test_db)
    lines, emit = _collector()
    async with channel_incremental_topicization_lock(CH) as held:
        assert held
        assert await svc.run_write([CH], emit=emit) == 4
    assert lines[-1]["skipped"] == "incremental_topicization_lock_held"
    assert await _state(test_db) == before


@pg_only
@pytest.mark.asyncio
async def test_pg_write_rolls_back_when_bundles_change_during_compute(test_db, monkeypatch):
    """A tick writes between the snapshot and the write → fingerprint mismatch, rollback."""
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

    await _seed(test_db, _fixture())
    tick_item = _item(_ref(4), score=0.9, why="incremental keyword assign (score=0.9)")
    orig_list = SATopicBundleRepo.list_by_channel
    calls = {"n": 0}

    async def list_by_channel(self, channel_id):
        calls["n"] += 1
        if calls["n"] == 2:  # the fingerprint re-read: a tick landed during compute
            async with test_db.processing_storage_session() as s:
                await SATopicBundleRepo(s).add_items(T1, [tick_item])
        return await orig_list(self, channel_id)

    monkeypatch.setattr(SATopicBundleRepo, "list_by_channel", list_by_channel)
    lines, emit = _collector()
    assert await svc.run_write([CH], emit=emit) == 4
    assert lines[-1]["skipped"] == "bundles_changed"
    bundles, _ = await _state(test_db)
    t1 = next(r for r in bundles if r[0] == T1)
    assert _ref(4) in [i["source_ref"] for i in json.loads(t1[1])]  # the tick's write survived
    assert "rebuild" not in json.loads(t1[2])  # nothing of the rebuild was written


def _foreign_t4() -> TopicBundle:
    # The card T4 belongs to CH, but its stored bundle lists only another channel:
    # list_by_channel(CH) does not return it, upsert(T4) would replace it.
    return _bundle(T4, [_item(_ref(5, "other"), score=0.7)], channels=("other",))


@pg_only
@pytest.mark.asyncio
async def test_pg_write_never_overwrites_a_foreign_bundle_of_a_card(test_db):
    snap = _fixture()
    await _seed(
        test_db, svc.ChannelSnapshot(CH, snap.docs, snap.cards, [*snap.bundles, _foreign_t4()])
    )
    lines, emit = _collector()
    assert await svc.run_write([CH], emit=emit) == 0
    report = lines[-1]
    assert report["written"] == 2  # T1, T2; T3 and T4 are foreign → skipped
    assert report["final"]["foreign_bundles_skipped"] == 2
    assert report["final"]["cards_skipped_foreign_bundle"] == 2
    bundles, _ = await _state(test_db)
    t4 = next(r for r in bundles if r[0] == T4)
    assert [i["source_ref"] for i in json.loads(t4[1])] == [_ref(5, "other")]
    assert "rebuild" not in json.loads(t4[2])


@pg_only
@pytest.mark.asyncio
async def test_pg_write_upsert_guard_refuses_a_foreign_bundle(test_db, monkeypatch):
    """Last line of defence: a foreign bundle of a rebuilt card appears after the
    fingerprint check (fingerprint disabled here) → rollback, nothing written."""
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

    await _seed(test_db, _fixture())
    monkeypatch.setattr(svc, "channel_fingerprint", lambda *a, **k: {})
    orig_list = SATopicBundleRepo.list_by_channel
    calls = {"n": 0}

    async def list_by_channel(self, channel_id):
        calls["n"] += 1
        if calls["n"] == 2:  # the fingerprint re-read
            async with test_db.processing_storage_session() as s:
                await SATopicBundleRepo(s).upsert(_foreign_t4())
        return await orig_list(self, channel_id)

    monkeypatch.setattr(SATopicBundleRepo, "list_by_channel", list_by_channel)
    lines, emit = _collector()
    assert await svc.run_write([CH], emit=emit) == 4
    assert lines[-1]["skipped"] == "foreign_bundle"
    assert lines[-1]["foreign_topic_id"] == T4
    bundles, _ = await _state(test_db)
    by_id = {r[0]: r for r in bundles}
    assert [i["source_ref"] for i in json.loads(by_id[T4][1])] == [_ref(5, "other")]
    assert all("rebuild" not in json.loads(r[2]) for r in bundles)  # rolled back


def test_load_bundles_fetches_the_stored_bundle_of_a_card_list_by_channel_misses():
    snap = _fixture()

    class Repo:
        async def list_by_channel(self, channel_id):
            return list(snap.bundles)

        async def get_by_topic_id(self, topic_id):
            return _foreign_t4() if topic_id == T4 else None

    bundles = asyncio.run(svc._load_bundles(Repo(), CH, snap.cards))
    assert [b.topic_id for b in bundles][-1] == T4
    res = svc.rebuild_channel_bundles(
        svc.ChannelSnapshot(CH, snap.docs, snap.cards, bundles), _pipeline(), now=NOW
    )
    assert {b.topic_id for b in res.bundles} == {T1, T2}
    assert T4 in res.fingerprint["foreign"]


@pg_only
@pytest.mark.asyncio
async def test_pg_write_reports_a_topic_reverted_after_commit(test_db, monkeypatch):
    """A tick that read before the commit and wrote after it restores old metadata."""
    from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

    snap = _fixture()
    await _seed(test_db, snap)
    stale_t2 = next(b for b in snap.bundles if b.topic_id == T2)
    orig_list = SATopicBundleRepo.list_by_channel
    calls = {"n": 0}

    async def list_by_channel(self, channel_id):
        calls["n"] += 1
        if calls["n"] == 3:  # post-commit re-read: the stale tick write lands first
            async with test_db.processing_storage_session() as s:
                await SATopicBundleRepo(s).upsert(stale_t2)
        return await orig_list(self, channel_id)

    monkeypatch.setattr(SATopicBundleRepo, "list_by_channel", list_by_channel)
    lines, emit = _collector()
    assert await svc.run_write([CH], emit=emit) == 4
    assert lines[-1]["written"] == 3
    assert lines[-1]["reverted_topics"] == [T2]


@pg_only
@pytest.mark.asyncio
async def test_pg_write_refuses_without_lock_engine(test_db, monkeypatch):
    monkeypatch.setattr(test_db, "advisory_lock_engine", None)
    with pytest.raises(svc.RebuildRefused):
        await svc.run_write([CH], emit=MagicMock())
