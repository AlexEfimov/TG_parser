"""BUG-008 — batched channel-stats aggregation (H1) + read-scoped timeout (H2).

These Postgres-backed tests guard the BUG-008 root-cause fix in
``tg_parser/services/channel_service.py::get_all_channel_stats``:

* **H1 behavior-parity** — the new set-based batched aggregation returns
  byte-for-byte the same per-channel counts/coverage as the legacy
  per-channel fan-out (which still exists in the repos and is used here to
  build an independent reference).
* **H1 bounded query count** — the batched path issues a fixed, small number
  of SQL statements regardless of the number of channels (NOT O(channels)).
* **H2 read-scoped statement_timeout** — the timeout is applied (via
  ``SET LOCAL``) on the stats sessions but NOT on the pipeline/write sessions.

Gated by the standard ``TEST_POSTGRES=1`` mechanism (reuses the alembic-managed
``test_db`` fixture from ``conftest.py``).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text

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
from tg_parser.services.channel_service import _compute_coverage, get_all_channel_stats
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy import (
    SAIngestionStateRepo,
    SAProcessedDocumentRepo,
    SARawMessageRepo,
    SATopicBundleRepo,
    SATopicCardRepo,
)

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _add_source(db, channel_id: str, *, username: str | None = None, status: str = "active"):
    async with db.ingestion_state_session() as session:
        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=channel_id,
                channel_id=channel_id,
                channel_username=username,
                status=status,
                include_comments=False,
            )
        )


async def _add_processed(db, channel_id: str, ref_n: int):
    source_ref = f"tg:{channel_id}:post:{ref_n}"
    async with db.processing_storage_session() as session:
        repo = SAProcessedDocumentRepo(session)
        await repo.upsert(
            ProcessedDocument(
                id=f"doc:{source_ref}",
                source_ref=source_ref,
                source_message_id=str(ref_n),
                channel_id=channel_id,
                processed_at=_NOW,
                text_clean=f"clean text {source_ref}",
            )
        )
    return source_ref


async def _add_raw(db, channel_id: str, ref_n: int):
    from tg_parser.domain.models import RawTelegramMessage

    source_ref = f"tg:{channel_id}:post:{ref_n}"
    async with db.raw_storage_session() as session:
        repo = SARawMessageRepo(session)
        await repo.upsert(
            RawTelegramMessage(
                id=str(ref_n),
                message_type=MessageType.POST,
                source_ref=source_ref,
                channel_id=channel_id,
                date=_NOW,
                text=f"raw {source_ref}",
            )
        )


async def _add_topic_card(db, topic_n: str, sources: list[str]):
    anchor_ref = f"tg:{sources[0]}:post:{topic_n}"
    async with db.processing_storage_session() as session:
        repo = SATopicCardRepo(session)
        await repo.upsert(
            TopicCard(
                id=f"topic:{anchor_ref}",
                title=f"Topic {topic_n}",
                summary="summary",
                scope_in=["in"],
                scope_out=["out"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id=sources[0],
                        message_id=str(topic_n),
                        message_type=MessageType.POST,
                        anchor_ref=anchor_ref,
                    )
                ],
                sources=sources,
                updated_at=_NOW,
            )
        )
    return f"topic:{anchor_ref}"


async def _add_bundle(db, topic_id: str, item_refs: list[str], channels: list[str] | None):
    items = [
        BundleItem(
            channel_id=ref.split(":")[1],
            message_id=ref.split(":")[3],
            message_type=MessageType.POST,
            source_ref=ref,
            role=BundleItemRole.SUPPORTING,
        )
        for ref in item_refs
    ]
    async with db.processing_storage_session() as session:
        repo = SATopicBundleRepo(session)
        await repo.upsert(
            TopicBundle(
                topic_id=topic_id,
                items=items,
                updated_at=_NOW,
                channels=channels,
            )
        )


async def _seed_dataset(db) -> None:
    """A deliberately discriminating multi-channel dataset.

    * chA: 4 processed docs, partial bundle coverage (incl. a null-channel
      bundle and a bundle item NOT in processed docs → must NOT count).
    * chB: 3 processed docs, coverage via a chB bundle + the null bundle.
    * chC: 0 processed docs but owns a topic card (topics_count=1, coverage 0).
    """
    await _add_source(db, "chA", username="@cha")
    await _add_source(db, "chB", status="paused")
    await _add_source(db, "chC")

    for n in (1, 2, 3):  # chA raw
        await _add_raw(db, "chA", n)
    await _add_raw(db, "chB", 1)

    for n in (1, 2, 3, 4):
        await _add_processed(db, "chA", n)
    for n in (1, 2, 3):
        await _add_processed(db, "chB", n)

    t1 = await _add_topic_card(db, "1", ["chA"])
    t2 = await _add_topic_card(db, "2", ["chA", "chB"])
    t3 = await _add_topic_card(db, "3", ["chC"])

    # chA bundle: covers chA:1, chA:2 (+ chA:99 which is NOT processed → ignored)
    await _add_bundle(db, t1, ["tg:chA:post:1", "tg:chA:post:2", "tg:chA:post:99"], ["chA"])
    # null-channel bundle: covers chA:3 and chB:1 for EVERY channel (intersected)
    await _add_bundle(db, t2, ["tg:chA:post:3", "tg:chB:post:1"], None)
    # chB bundle: covers chB:2
    await _add_bundle(db, t3, ["tg:chB:post:2"], ["chB"])


# ---------------------------------------------------------------------------
# Legacy reference (independent re-implementation of the old per-channel path)
# ---------------------------------------------------------------------------


async def _legacy_reference(db, channel_ids: list[str]) -> dict[str, dict]:
    """Compute stats the OLD per-channel way, using the still-present repo methods.

    This is an independent algorithm from the new batched SQL, so equality
    proves behavior preservation rather than two copies of the same logic.
    """
    ref: dict[str, dict] = {}
    async with (
        db.raw_storage_session() as raw_s,
        db.processing_storage_session() as proc_s,
    ):
        raw_repo = SARawMessageRepo(raw_s)
        proc_repo = SAProcessedDocumentRepo(proc_s)
        tc_repo = SATopicCardRepo(proc_s)
        tb_repo = SATopicBundleRepo(proc_s)
        for cid in channel_ids:
            raw_count = await raw_repo.count_by_channel(cid)
            processed_count = await proc_repo.count_by_channel(cid)
            topics_count = len(await tc_repo.list_by_channel(cid))
            processed_refs = set(await proc_repo.list_source_refs_by_channel(cid))
            bundles = await tb_repo.list_by_channel(cid)
            _covered, coverage_percent = _compute_coverage(bundles, processed_refs, processed_count)
            ref[cid] = {
                "raw_messages": raw_count,
                "processed_documents": processed_count,
                "topics_count": topics_count,
                "coverage_percent": round(coverage_percent, 2),
            }
    return ref


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pg_only
class TestBatchedStatsParity:
    async def test_matches_legacy_per_channel_output(self, test_db):
        await _seed_dataset(test_db)

        result = await get_all_channel_stats()
        by_id = {r["channel_id"]: r for r in result}
        ref = await _legacy_reference(test_db, ["chA", "chB", "chC"])

        assert set(by_id) == {"chA", "chB", "chC"}
        for cid in ("chA", "chB", "chC"):
            for key in ("raw_messages", "processed_documents", "topics_count", "coverage_percent"):
                assert by_id[cid][key] == ref[cid][key], f"mismatch {cid}.{key}"

        # Hardcoded expectations guard against both implementations being
        # wrong in the same way.
        assert by_id["chA"]["raw_messages"] == 3
        assert by_id["chA"]["processed_documents"] == 4
        assert by_id["chA"]["topics_count"] == 2
        assert by_id["chA"]["coverage_percent"] == 75.0  # {1,2,3} covered of 4
        assert by_id["chB"]["processed_documents"] == 3
        assert by_id["chB"]["topics_count"] == 1
        assert by_id["chB"]["coverage_percent"] == 66.67  # {1,2} covered of 3
        assert by_id["chC"]["processed_documents"] == 0
        assert by_id["chC"]["topics_count"] == 1
        assert by_id["chC"]["coverage_percent"] == 0.0
        # status/username passthrough preserved
        assert by_id["chA"]["channel_username"] == "@cha"
        assert by_id["chB"]["status"] == "paused"

    async def test_scoping_filters_channels(self, test_db):
        await _seed_dataset(test_db)
        result = await get_all_channel_stats(allowed_channel_ids=["chB"])
        assert [r["channel_id"] for r in result] == ["chB"]


@pg_only
class TestBatchedStatsQueryCount:
    async def test_query_count_is_bounded_not_per_channel(self, test_db):
        engines = [
            test_db.ingestion_state_engine,
            test_db.raw_storage_engine,
            test_db.processing_storage_engine,
        ]
        counter = {"n": 0}

        def _count(conn, cursor, statement, parameters, context, executemany):
            counter["n"] += 1

        for eng in engines:
            event.listen(eng.sync_engine, "before_cursor_execute", _count)
        try:
            # One channel + warm-up call (establishes pooled connections so the
            # measured calls don't include one-off connection setup noise).
            await _add_source(test_db, "c0")
            await _add_processed(test_db, "c0", 1)
            await get_all_channel_stats()

            counter["n"] = 0
            await get_all_channel_stats()
            count_few = counter["n"]

            # Grow to several channels; the per-call statement count must NOT
            # scale with channel count (set-based aggregation, BUG-008 H1).
            for ch in ("c1", "c2", "c3", "c4"):
                await _add_source(test_db, ch)
                await _add_processed(test_db, ch, 1)

            counter["n"] = 0
            await get_all_channel_stats()
            count_many = counter["n"]
        finally:
            for eng in engines:
                event.remove(eng.sync_engine, "before_cursor_execute", _count)

        assert count_few == count_many, (
            f"query count scales with channels: {count_few} (1ch) vs {count_many} (5ch)"
        )
        # Generous absolute bound: 3 set_config + list_sources + 3 grouped
        # aggregates (+ possible pool pings). Decisively NOT O(channels).
        assert count_many <= 14, f"unexpectedly many statements: {count_many}"


@pg_only
class TestReadScopedStatementTimeout:
    async def test_timeout_applied_on_stats_session(self, test_db):
        from tg_parser.services.db_context import stats_repos

        async with stats_repos() as (state_repo, raw_repo, proc_repo, *_rest):
            for repo in (state_repo, raw_repo, proc_repo):
                res = await repo.session.execute(
                    text("SELECT current_setting('statement_timeout')")
                )
                value = res.scalar()
                assert value != "0", "read-scoped statement_timeout NOT applied on stats session"

    async def test_timeout_not_applied_on_pipeline_session(self, test_db):
        from tg_parser.services.db_context import processing_repos

        async with processing_repos() as (proc_repo, _tc, _tb, _db):
            res = await proc_repo.session.execute(
                text("SELECT current_setting('statement_timeout')")
            )
            assert res.scalar() == "0", (
                "statement_timeout leaked onto the pipeline/write session — "
                "must be read-scoped only (BUG-008 H2)"
            )
