"""BUG-073: cross-entrypoint per-channel concurrency guards (F1 + F3).

F1 — the PROCESSING stage gains a cross-process per-channel advisory lock
(:func:`channel_pipeline_lock`, namespace ``PIPELINE_LOCK_NS`` 0x9C40) wrapping
the single funnel :func:`run_processing`. ALL trigger paths funnel through it
(scheduler tick → ``run_full_pipeline`` → ``run_processing``; MCP/API
``full_pipeline`` dispatch → ``run_full_pipeline`` → ``run_processing``; CLI
``tg-parser run`` → ``run_full_pipeline``; CLI ``tg-parser process`` →
``run_processing``), keyed by ``hashtext(normalize_channel_id(channel_id))`` so
they all contend on the SAME per-channel key. A benign skip is SAFE in
processing: the lock-holder works the same bounded backlog and anything it does
not reach stays unprocessed for the next run (no permanent abandonment).

F3 — the INCREMENTAL topicization path gains a SEPARATE-namespace advisory lock
(:func:`channel_incremental_topicization_lock`, ``INCREMENTAL_TOPICIZATION_LOCK_NS``
0x70C2). It contends incremental-vs-incremental (preventing the expensive CLI
uncovered-backlog-fill from double-billing Phase-2) but NOT incremental-vs-full
(so the BUG-072 re-escalation fall-through keeps working and the scheduler tick's
tick-local ``new_doc_refs`` are never abandoned).

Test layers mirror ``tests/test_bug072_topicization_concurrency.py``:
* **Non-PG (always run)** — degradation, sentinel shape, wrapper skip/run logic.
* **PG-gated (``TEST_POSTGRES=1``)** — real ``pg_try_advisory_lock`` behaviour.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.domain.models import (
    IncrementalTopicizeResult,
    ProcessedDocument,
)
from tg_parser.services.processing_service import (
    PIPELINE_LOCK_NS,
    _locked_skip_processing_result,
    channel_pipeline_lock,
    run_multi_agent_processing,
    run_processing,
)
from tg_parser.services.topicization_service import (
    INCREMENTAL_TOPICIZATION_LOCK_NS,
    TOPICIZATION_LOCK_NS,
    channel_incremental_topicization_lock,
    channel_topicization_lock,
    run_incremental_topicization,
)

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _make_doc(source_ref: str, channel_id: str = "labdiagnostica") -> ProcessedDocument:
    parts = source_ref.split(":")
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=parts[-1],
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean="some text content",
        summary="summary",
        topics=[],
    )


@contextlib.asynccontextmanager
async def _yield_lock(acquired: bool):
    """Stand-in for a channel advisory lock in unit tests (no DB)."""
    yield acquired


# ===========================================================================
# F1 — processing lock: non-PG
# ===========================================================================


def test_pipeline_lock_namespaces_are_distinct():
    """The three per-channel guards must use DISTINCT namespaces so they never
    collide in the shared ``pg_advisory_lock`` keyspace."""
    from tg_parser.services.scheduler_service import SCHEDULER_SOURCE_LOCK_NS

    assert (
        len(
            {
                PIPELINE_LOCK_NS,
                TOPICIZATION_LOCK_NS,
                INCREMENTAL_TOPICIZATION_LOCK_NS,
                SCHEDULER_SOURCE_LOCK_NS,
            }
        )
        == 4
    )


def test_locked_skip_processing_result_is_caller_compatible():
    """The benign skip sentinel is shaped like a real ``run_processing`` 'no
    work' return so every caller handles it without a KeyError."""
    res = _locked_skip_processing_result()
    # run_full_pipeline reads these DIRECTLY (KeyError if missing).
    assert res["processed_count"] == 0
    assert res["failed_count"] == 0
    assert res["total_tokens"] == 0
    # scheduler reads these via .get(...).
    for key in ("total_count", "skipped_count", "raw_total_count", "attempted_count"):
        assert res[key] == 0
    assert res["skipped_locked"] is True


@pytest.mark.asyncio
async def test_pipeline_lock_degrades_to_acquired_when_no_engine():
    """The lock degrades to 'acquired' when the DB engine is unavailable so
    lock-infra problems never block processing."""
    fake_db = MagicMock()
    fake_db.processing_storage_engine = None
    with patch(
        "tg_parser.storage.sqlalchemy.database.Database.get_instance",
        return_value=fake_db,
    ):
        async with channel_pipeline_lock("ch1") as acquired:
            assert acquired is True


@pytest.mark.asyncio
async def test_pipeline_lock_degrades_to_acquired_when_no_db_context():
    """If ``Database.get_instance`` raises (no DB context) the guard degrades to
    'acquired' rather than crashing."""
    with patch(
        "tg_parser.storage.sqlalchemy.database.Database.get_instance",
        side_effect=RuntimeError("no DB"),
    ):
        async with channel_pipeline_lock("ch1") as acquired:
            assert acquired is True


@pytest.mark.asyncio
async def test_run_processing_returns_sentinel_when_lock_held():
    """When the channel lock is held, run_processing is a benign no-op: it
    returns the skip sentinel WITHOUT running the inner body (no backlog load,
    no LLM pass) and WITHOUT raising — the backlog is left for the next run."""
    with (
        patch(
            "tg_parser.services.processing_service.channel_pipeline_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        patch(
            "tg_parser.services.processing_service._run_processing_locked",
            new_callable=AsyncMock,
        ) as inner,
    ):
        res = await run_processing("labdiagnostica")

    assert res["skipped_locked"] is True
    assert res["processed_count"] == 0
    inner.assert_not_awaited()  # backlog untouched → not abandoned


@pytest.mark.asyncio
async def test_run_processing_runs_inner_when_lock_acquired():
    """When the lock IS acquired the wrapper delegates to the real inner body."""
    sentinel = {"processed_count": 5, "failed_count": 0, "total_tokens": 99}
    with (
        patch(
            "tg_parser.services.processing_service.channel_pipeline_lock",
            lambda *_a, **_k: _yield_lock(True),
        ),
        patch(
            "tg_parser.services.processing_service._run_processing_locked",
            new_callable=AsyncMock,
            return_value=sentinel,
        ) as inner,
    ):
        res = await run_processing("labdiagnostica", force=True)

    assert res == sentinel
    inner.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_multi_agent_processing_returns_sentinel_when_lock_held():
    """BUG-073 (F1) multi-agent funnel: when the SAME per-channel pipeline lock
    is held, ``run_multi_agent_processing`` is a benign no-op — it returns the
    skip sentinel WITHOUT running the inner body (no backlog load, no agent/LLM
    pass) and WITHOUT raising."""
    with (
        patch(
            "tg_parser.services.processing_service.channel_pipeline_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        patch(
            "tg_parser.services.processing_service._run_multi_agent_processing_locked",
            new_callable=AsyncMock,
        ) as inner,
    ):
        res = await run_multi_agent_processing("labdiagnostica")

    assert res["skipped_locked"] is True
    assert res["processed_count"] == 0
    inner.assert_not_awaited()  # backlog untouched → not abandoned


@pytest.mark.asyncio
async def test_run_multi_agent_processing_runs_inner_when_lock_acquired():
    """When the lock IS acquired the multi-agent wrapper delegates to the real
    inner body (same structure as the ``run_processing`` wrapper)."""
    sentinel = {"processed_count": 4, "failed_count": 0, "total_count": 4, "multi_agent": True}
    with (
        patch(
            "tg_parser.services.processing_service.channel_pipeline_lock",
            lambda *_a, **_k: _yield_lock(True),
        ),
        patch(
            "tg_parser.services.processing_service._run_multi_agent_processing_locked",
            new_callable=AsyncMock,
            return_value=sentinel,
        ) as inner,
    ):
        res = await run_multi_agent_processing("labdiagnostica", force=True)

    assert res == sentinel
    inner.assert_awaited_once()


# ===========================================================================
# F1 — processing lock: PG-gated
# ===========================================================================


@pg_only
@pytest.mark.asyncio
async def test_pipeline_lock_second_acquire_same_channel_refused(test_db):
    """Two concurrent acquires for the SAME channel: first wins, second refused;
    a DIFFERENT channel is not blocked; the lock releases on context exit."""
    async with channel_pipeline_lock("chan_a") as first:
        assert first is True
        async with channel_pipeline_lock("chan_a") as second:
            assert second is False
        async with channel_pipeline_lock("chan_b") as other:
            assert other is True
    async with channel_pipeline_lock("chan_a") as reacquired:
        assert reacquired is True


@pg_only
@pytest.mark.asyncio
async def test_run_processing_skips_when_lock_held(test_db):
    """End-to-end through the real funnel: while another run holds the channel
    lock, run_processing for that channel returns the skip sentinel and does NOT
    run the inner body; a different channel runs normally."""
    sentinel = {"processed_count": 3, "failed_count": 0, "total_tokens": 7}
    with patch(
        "tg_parser.services.processing_service._run_processing_locked",
        new_callable=AsyncMock,
        return_value=sentinel,
    ) as inner:
        async with channel_pipeline_lock("chan_held") as held:
            assert held is True

            skipped = await run_processing("chan_held")
            assert skipped["skipped_locked"] is True
            inner.assert_not_awaited()

            ran = await run_processing("chan_free")
            assert ran == sentinel
            inner.assert_awaited_once()


@pg_only
@pytest.mark.asyncio
async def test_processing_cross_path_contends_on_same_normalized_key(test_db):
    """The scheduler path, the dispatch ``full_pipeline`` path and the CLI all
    funnel through run_processing keyed by the NORMALIZED channel id, so they
    contend on the SAME advisory lock. Holding ``chx`` blocks both ``chx`` and
    ``@chx`` (which normalizes to ``chx``)."""
    with patch(
        "tg_parser.services.processing_service._run_processing_locked",
        new_callable=AsyncMock,
        return_value={"processed_count": 1, "failed_count": 0, "total_tokens": 0},
    ) as inner:
        async with channel_pipeline_lock("chx") as held:
            assert held is True
            r1 = await run_processing("chx")
            r2 = await run_processing("@chx")

        assert r1["skipped_locked"] is True
        assert r2["skipped_locked"] is True
        inner.assert_not_awaited()


@pg_only
@pytest.mark.asyncio
async def test_multi_agent_contends_with_run_processing_on_same_key(test_db):
    """BUG-073 (F1): ``run_processing`` and ``run_multi_agent_processing`` share
    the SAME per-channel key (``PIPELINE_LOCK_NS`` 0x9C40 over the normalized
    channel id), so they MUTUALLY EXCLUDE. A held pipeline lock for a channel
    benignly skips a multi-agent run for the SAME channel (inner body NOT run)
    while a DIFFERENT channel runs normally."""
    sentinel = {"processed_count": 2, "failed_count": 0, "total_count": 2, "multi_agent": True}
    with patch(
        "tg_parser.services.processing_service._run_multi_agent_processing_locked",
        new_callable=AsyncMock,
        return_value=sentinel,
    ) as inner:
        async with channel_pipeline_lock("ma_held") as held:
            assert held is True

            # Same channel → benign skip, inner not run.
            skipped = await run_multi_agent_processing("ma_held")
            assert skipped["skipped_locked"] is True
            inner.assert_not_awaited()

            # Same channel via a NON-normalized alias (``@ma_held`` → ``ma_held``)
            # also contends on the same key.
            skipped_alias = await run_multi_agent_processing("@ma_held")
            assert skipped_alias["skipped_locked"] is True
            inner.assert_not_awaited()

            # Different channel → runs normally.
            ran = await run_multi_agent_processing("ma_free")
            assert ran == sentinel
            inner.assert_awaited_once()


# ===========================================================================
# F3 — incremental topicization lock: non-PG
# ===========================================================================


@pytest.mark.asyncio
async def test_incremental_lock_degrades_to_acquired_when_no_engine():
    fake_db = MagicMock()
    fake_db.processing_storage_engine = None
    with patch(
        "tg_parser.storage.sqlalchemy.database.Database.get_instance",
        return_value=fake_db,
    ):
        async with channel_incremental_topicization_lock("ch1") as acquired:
            assert acquired is True


@pytest.mark.asyncio
async def test_incremental_defer_skips_inner_when_lock_held():
    """The CLI backlog-fill path (defer_if_locked=True) is a BENIGN skip on
    contention — it returns an OBSERVABLE deferred result (``deferred_locked``)
    and does NOT run the inner body (the uncovered backlog is recomputed next
    invocation → not abandoned)."""
    with (
        patch(
            "tg_parser.services.topicization_service.channel_incremental_topicization_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        patch(
            "tg_parser.services.topicization_service._run_incremental_topicization_locked",
            new_callable=AsyncMock,
        ) as inner,
    ):
        res = await run_incremental_topicization(
            "labdiagnostica", ["tg:labdiagnostica:post:1"], defer_if_locked=True
        )

    assert isinstance(res, IncrementalTopicizeResult)
    # The defer is OBSERVABLE — not mistakable for a 0-coverage success.
    assert res.deferred_locked is True
    inner.assert_not_awaited()


@pytest.mark.asyncio
async def test_incremental_tick_proceeds_despite_contention():
    """The scheduler tick path (defer_if_locked=False, default) NEVER skips: on
    contention it PROCEEDS anyway so the tick-local new docs are not abandoned —
    the bounded duplicate work is strictly cheaper than abandonment."""
    sentinel = IncrementalTopicizeResult(tokens_used=42)
    with (
        patch(
            "tg_parser.services.topicization_service.channel_incremental_topicization_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        patch(
            "tg_parser.services.topicization_service._run_incremental_topicization_locked",
            new_callable=AsyncMock,
            return_value=sentinel,
        ) as inner,
    ):
        res = await run_incremental_topicization("labdiagnostica", ["tg:labdiagnostica:post:1"])

    assert res is sentinel
    # A normal (proceeding) run is NOT flagged deferred.
    assert res.deferred_locked is False
    inner.assert_awaited_once()


@pytest.mark.asyncio
async def test_incremental_runs_inner_when_lock_acquired():
    sentinel = IncrementalTopicizeResult(tokens_used=7)
    with (
        patch(
            "tg_parser.services.topicization_service.channel_incremental_topicization_lock",
            lambda *_a, **_k: _yield_lock(True),
        ),
        patch(
            "tg_parser.services.topicization_service._run_incremental_topicization_locked",
            new_callable=AsyncMock,
            return_value=sentinel,
        ) as inner,
    ):
        res = await run_incremental_topicization(
            "labdiagnostica", ["tg:labdiagnostica:post:1"], defer_if_locked=True
        )

    assert res is sentinel
    inner.assert_awaited_once()


@pytest.mark.asyncio
async def test_incremental_proceed_without_lock_releases_connection_before_run():
    """BUG-073 (Bugbot MEDIUM follow-up): on the proceed-WITHOUT-lock path
    (defer_if_locked=False + contention) the dedicated advisory-lock connection
    must be RELEASED *before* the long Phase 1/2 LLM run — no idle dedicated
    connection held for the run's whole duration. Proven by a spy lock CM: the
    inner body observes the lock context as already CLOSED when it runs."""
    state = {"lock_open": False, "inner_saw_lock_open": None}

    @contextlib.asynccontextmanager
    async def _spy_lock(*_a, **_k):
        state["lock_open"] = True
        try:
            yield False  # NOT acquired → contended (proceed-without-lock path)
        finally:
            state["lock_open"] = False

    def _inner(*_a, **_k):
        state["inner_saw_lock_open"] = state["lock_open"]
        return IncrementalTopicizeResult()

    with (
        patch(
            "tg_parser.services.topicization_service.channel_incremental_topicization_lock",
            _spy_lock,
        ),
        patch(
            "tg_parser.services.topicization_service._run_incremental_topicization_locked",
            new_callable=AsyncMock,
            side_effect=_inner,
        ),
    ):
        res = await run_incremental_topicization("chx", ["tg:chx:post:1"])

    # The lock context EXITED (dedicated connection released) BEFORE the Phase
    # 1/2 work ran — the whole point of the MEDIUM fix.
    assert state["inner_saw_lock_open"] is False
    assert res.deferred_locked is False


@pytest.mark.asyncio
async def test_incremental_acquired_holds_connection_during_run():
    """Contrast with the proceed-without-lock case: when the lock IS acquired the
    dedicated connection is HELD for the run's duration (so a concurrent
    backlog-fill cannot duplicate Phase-2 spend). The inner body observes the
    lock context still OPEN — the MEDIUM refactor must not change this."""
    state = {"lock_open": False, "inner_saw_lock_open": None}

    @contextlib.asynccontextmanager
    async def _spy_lock(*_a, **_k):
        state["lock_open"] = True
        try:
            yield True  # acquired → hold for the run
        finally:
            state["lock_open"] = False

    def _inner(*_a, **_k):
        state["inner_saw_lock_open"] = state["lock_open"]
        return IncrementalTopicizeResult()

    with (
        patch(
            "tg_parser.services.topicization_service.channel_incremental_topicization_lock",
            _spy_lock,
        ),
        patch(
            "tg_parser.services.topicization_service._run_incremental_topicization_locked",
            new_callable=AsyncMock,
            side_effect=_inner,
        ),
    ):
        await run_incremental_topicization("chx", ["tg:chx:post:1"])

    assert state["inner_saw_lock_open"] is True


@pytest.mark.asyncio
async def test_uncovered_backlog_fill_propagates_deferred_locked():
    """The CLI uncovered backlog-fill (``run_incremental_topicization_for_uncovered``)
    confirms uncovered refs EXIST, then on lock contention propagates the
    deferred indicator instead of a silent zero-coverage result — so the CLI can
    distinguish "deferred, NOT processed" from "processed, nothing matched"."""
    from tg_parser.services.topicization_service import (
        run_incremental_topicization_for_uncovered,
    )

    doc = _make_doc("tg:labdiagnostica:post:1")
    processed_repo = AsyncMock()
    processed_repo.list_by_channel.return_value = [doc]
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []  # → doc is uncovered

    with patch(
        "tg_parser.services.topicization_service.channel_incremental_topicization_lock",
        lambda *_a, **_k: _yield_lock(False),
    ):
        res = await run_incremental_topicization_for_uncovered(
            "labdiagnostica",
            assign_only=False,
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
        )

    assert res.deferred_locked is True
    assert res.assigned_keyword == []
    assert res.coverage_after == 0.0


def test_cli_reports_deferred_outcome_distinctly(capsys):
    """The CLI stats printer surfaces a deferred backlog-fill as a DISTINCT
    outcome (not a green '✅ завершён' success with 0 coverage)."""
    from tg_parser.cli.app import _print_incremental_stats

    _print_incremental_stats(IncrementalTopicizeResult(deferred_locked=True))
    deferred_out = capsys.readouterr().out
    assert "deferred" in deferred_out.lower()
    assert "NOT processed" in deferred_out
    assert "завершён" not in deferred_out  # NOT the success banner

    _print_incremental_stats(IncrementalTopicizeResult())
    normal_out = capsys.readouterr().out
    assert "завершён" in normal_out  # normal run still prints the success banner
    assert "deferred" not in normal_out.lower()


# ===========================================================================
# F3 — incremental topicization lock: PG-gated
# ===========================================================================


@pg_only
@pytest.mark.asyncio
async def test_incremental_lock_distinct_from_full_lock(test_db):
    """The incremental lock namespace (0x70C2) is DISTINCT from the full
    topicization lock (0x70C1): holding the full lock for a channel does NOT
    block the incremental lock for the SAME channel — this is what keeps the
    BUG-072 re-escalation fall-through (and the scheduler tick) from being
    abandoned while a full run is in flight."""
    async with channel_topicization_lock("chx") as full_held:
        assert full_held is True
        # Different namespace → incremental still acquires for the same channel.
        async with channel_incremental_topicization_lock("chx") as incr:
            assert incr is True


@pg_only
@pytest.mark.asyncio
async def test_full_run_in_flight_does_not_abandon_incremental_tick(test_db):
    """REGRESSION (BUG-072 scenario): a full run in flight + a scheduler tick
    with new docs must still process the tick's new docs (NOT abandon them).
    With the full lock held, the tick-local incremental run delegates to its
    inner body (docs covered), proving no abandonment under the separate-
    namespace design."""
    sentinel = IncrementalTopicizeResult(tokens_used=1)
    with patch(
        "tg_parser.services.topicization_service._run_incremental_topicization_locked",
        new_callable=AsyncMock,
        return_value=sentinel,
    ) as inner:
        async with channel_topicization_lock("chx") as full_held:
            assert full_held is True
            res = await run_incremental_topicization("chx", ["tg:chx:post:1"])

    assert res is sentinel
    inner.assert_awaited_once()  # tick processed — docs NOT abandoned


@pg_only
@pytest.mark.asyncio
async def test_incremental_vs_incremental_mutually_exclude(test_db):
    """Two incremental runs for the SAME channel mutually exclude: while one
    holds the incremental lock, a backlog-fill (defer) benignly skips (inner not
    run → no double Phase-2 spend), while a tick (no defer) still proceeds (no
    abandonment). A different channel is not blocked."""
    with patch(
        "tg_parser.services.topicization_service._run_incremental_topicization_locked",
        new_callable=AsyncMock,
        return_value=IncrementalTopicizeResult(),
    ) as inner:
        async with channel_incremental_topicization_lock("chx") as held:
            assert held is True

            # A second raw acquire for the same channel is refused.
            async with channel_incremental_topicization_lock("chx") as second:
                assert second is False
            # Different channel is not blocked.
            async with channel_incremental_topicization_lock("chy") as other:
                assert other is True

            # Backlog-fill (defer) skips the expensive inner body.
            deferred = await run_incremental_topicization(
                "chx", ["tg:chx:post:1"], defer_if_locked=True
            )
            assert deferred.deferred_locked is True
            inner.assert_not_awaited()

            # Tick (no defer) proceeds anyway to avoid abandoning new docs.
            await run_incremental_topicization("chx", ["tg:chx:post:2"])
            inner.assert_awaited_once()


# ===========================================================================
# F1 — processing-skip propagation across ALL consumers. The skip sentinel
# (``skipped_locked``) must be a DISTINCT benign outcome everywhere — never
# mis-reported as a successful run (Bugbot round: "skip mis-reported as success").
# ===========================================================================


@pytest.mark.asyncio
async def test_run_full_pipeline_short_circuits_on_processing_skip():
    """When the processing stage returns the F1 skip sentinel, run_full_pipeline
    SHORT-CIRCUITS: it does NOT run topicization/export (no useless work on
    stale state) and returns a benign ``skipped_locked`` result instead of a
    successful full run."""
    from tg_parser.services import pipeline_service as ps

    with (
        patch.object(ps, "_get_channel_id_from_source", new_callable=AsyncMock, return_value="ch1"),
        patch.object(
            ps,
            "run_processing",
            new_callable=AsyncMock,
            return_value=_locked_skip_processing_result(),
        ),
        patch.object(ps, "run_topicization", new_callable=AsyncMock) as topicize,
        patch.object(ps, "run_export", new_callable=AsyncMock) as export,
    ):
        stats = await ps.run_full_pipeline(source_id="s1", skip_ingest=True)

    assert stats.get("skipped_locked") is True
    topicize.assert_not_awaited()  # downstream stages NOT run on a lock-skip
    export.assert_not_awaited()


def test_cli_run_reports_processing_skip_distinctly():
    """CLI ``run``: a short-circuited (``skipped_locked``) pipeline prints a
    DISTINCT skipped line and NOT the green success banner."""
    from typer.testing import CliRunner

    from tg_parser.cli.app import app

    runner = CliRunner()
    with patch(
        "tg_parser.cli.run_cmd.run_full_pipeline",
        new_callable=AsyncMock,
        return_value={
            "ingest": None,
            "process": _locked_skip_processing_result(),
            "topicize": None,
            "export": None,
            "total_duration_seconds": 0.01,
            "skipped_locked": True,
        },
    ):
        result = runner.invoke(app, ["run", "--source", "ch1", "--skip-ingest"])

    assert result.exit_code == 0
    assert "пропущен" in result.stdout
    assert "завершён успешно" not in result.stdout


@pytest.mark.asyncio
async def test_api_processing_job_represents_lock_skip_distinctly():
    """API background job: a lock-skipped ``run_processing`` is represented as a
    DISTINCT benign outcome — terminal ``COMPLETED`` (NOT ``FAILED``) but the
    result + progress carry ``skipped_locked`` (+ a message) and the webhook
    status is ``skipped`` (NOT ``completed``), so it never reads as a successful
    processing run."""
    from tg_parser.api.routes import process as process_route
    from tg_parser.api.schemas import ProcessRequest
    from tg_parser.storage.ports import Job, JobStatus, JobType

    job = Job(
        job_id="j1",
        job_type=JobType.PROCESSING,
        status=JobStatus.PENDING,
        created_at=datetime.now(UTC),
        channel_id="ch1",
        webhook_url="https://example.test/hook",
    )

    fake_store = AsyncMock()
    fake_store.get_job.return_value = job

    sent: dict = {}

    async def _capture_webhook(*, url, payload, secret):
        sent["url"] = url
        sent["payload"] = payload
        return True

    req = ProcessRequest(channel_id="ch1", webhook_url="https://example.test/hook")

    with (
        patch.object(
            process_route,
            "ensure_job_store_initialized",
            new_callable=AsyncMock,
            return_value=fake_store,
        ),
        patch.object(
            process_route,
            "run_processing",
            new_callable=AsyncMock,
            return_value=_locked_skip_processing_result(),
        ),
        patch.object(process_route, "send_webhook", _capture_webhook),
    ):
        await process_route._run_processing_job("j1", req)

    # Terminal benign COMPLETED — NOT failed.
    assert job.status is JobStatus.COMPLETED
    # Result + progress carry the skip flag distinctly.
    assert job.result["skipped_locked"] is True
    assert "message" in job.result
    assert job.progress["skipped_locked"] is True
    assert job.progress["processed"] == 0
    # Webhook reads as a skip, not a normal completion.
    assert sent["payload"]["job"]["status"] == "skipped"
    assert sent["payload"]["job"]["result"]["skipped_locked"] is True


@pytest.mark.asyncio
async def test_dispatch_full_pipeline_records_skip_distinctly():
    """Dispatch ``full_pipeline`` job (a common F1 contender): a benign
    short-circuited pipeline is recorded as result=``skipped`` (NOT ``success``
    / ``failed``) and SKIPS the embedding step (another run owns the channel
    end-to-end)."""
    from tg_parser.services import pipeline_dispatch_service as pds
    from tg_parser.services.pipeline_dispatch_service import PipelineJobKind

    labels: list[str] = []

    def _record(*, job, result, surface):
        labels.append(result)

    with (
        patch(
            "tg_parser.services.pipeline_service.run_full_pipeline",
            new_callable=AsyncMock,
            return_value={"skipped_locked": True},
        ),
        patch(
            "tg_parser.services.embedding_service.run_embedding",
            new_callable=AsyncMock,
        ) as embedding,
        patch("tg_parser.api.metrics.record_pipeline_trigger", _record),
    ):
        await pds._run_pipeline_job_background(
            job_id="d1",
            channel_id="ch_disp",
            job=PipelineJobKind.FULL_PIPELINE,
            force=False,
            lock_key="ch_disp",
            surface="test",
        )

    assert "skipped" in labels
    assert "success" not in labels
    embedding.assert_not_awaited()  # no useless embedding on a lock-skip
