"""BUG-072: concurrent full-topicization de-duplication regression tests.

Covers Option (a): a non-blocking per-channel Postgres advisory lock
(:func:`channel_topicization_lock`) wrapping the single full-topicization funnel
:func:`run_topicization`. Two FULL runs of the SAME channel must never execute
concurrently across ALL entry paths/processes (scheduler re-escalation, MCP/API
``full_pipeline`` + ``topicization`` jobs, CLI ``tg-parser run``).

Test layers:

* **Non-PG (always run)** — the guard degrades to "acquired" without a DB; the
  benign skip sentinel shape; the BUG-071 Fix-2 interplay (a lock-skip is NOT a
  failed 0-card attempt → it must NOT arm/clear the cooldown marker).
* **PG-gated (``TEST_POSTGRES=1``)** — the real ``pg_try_advisory_lock``
  behaviour: a second concurrent acquire on the same channel is refused, a
  different channel is not blocked, the lock releases on context exit, and the
  scheduler/dispatch/pipeline paths all contend on the SAME normalized key.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.domain.models import ProcessedDocument
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.services.topicization_service import (
    TOPICIZATION_LOCK_NS,
    _locked_skip_result,
    _reescalation_marker_ref,
    channel_topicization_lock,
    run_incremental_topicization,
    run_topicization,
)

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ---------------------------------------------------------------------------
# Helpers (mirror tests/test_bug071_topicization_truncation.py style)
# ---------------------------------------------------------------------------


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


class _FakeFailureRepo:
    """In-memory ProcessingFailureRepo stand-in (no Postgres needed)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def list_failures(self, channel_id=None, limit=None):
        return [
            dict(r)
            for r in self.rows.values()
            if channel_id is None or r["channel_id"] == channel_id
        ]

    async def record_failure(
        self,
        source_ref,
        channel_id,
        attempts,
        error_class,
        error_message,
        error_details=None,
    ):
        self.rows[source_ref] = {
            "source_ref": source_ref,
            "channel_id": channel_id,
            "attempts": attempts,
            "error_class": error_class,
            "error_message": error_message,
            "last_attempt_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    async def delete_failure(self, source_ref):
        self.rows.pop(source_ref, None)


def _zero_card_repos():
    """Repos for a 0-card channel with one new doc → re-escalation candidate."""
    doc = _make_doc("tg:labdiagnostica:post:900")
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.return_value = doc
    processed_repo.list_by_channel.return_value = [doc]
    # No real .session → forces the Fix-2 gate to use the injected fake repo.
    del processed_repo.session

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    return doc, processed_repo, topic_card_repo, topic_bundle_repo


@contextlib.asynccontextmanager
async def _yield_lock(acquired: bool):
    """Stand-in for ``channel_topicization_lock`` in unit tests (no DB)."""
    yield acquired


@contextlib.contextmanager
def _patch_incremental_phase(*, assign_return, discover_return):
    """Stub the cheap incremental Phase 1/2 path so it makes NO real LLM call.

    Mirrors ``tests/test_bug071_topicization_truncation.py::_patch_incremental_phase``.
    BUG-072: a lock-skipped re-escalation FALLS THROUGH to the incremental path
    (it must not abandon the tick's new docs), so the lock-skip tests must
    neutralise ``resolve_llm_config`` / ``create_llm_client`` and the two
    pipeline methods (``assign_documents_to_topics`` Phase 1,
    ``_discover_single_batch`` Phase 2) to stay offline and deterministic.
    """
    with (
        patch(
            "tg_parser.services.topicization_service.resolve_llm_config",
            return_value=("anthropic", "key", "model"),
        ),
        patch("tg_parser.services.topicization_service.create_llm_client") as mk_client,
        patch.object(
            TopicizationPipelineImpl,
            "assign_documents_to_topics",
            new_callable=AsyncMock,
            return_value=assign_return,
        ) as assign_mock,
        patch.object(
            TopicizationPipelineImpl,
            "_discover_single_batch",
            new_callable=AsyncMock,
            return_value=discover_return,
        ) as discover_mock,
    ):
        client = AsyncMock()
        client.close = AsyncMock()
        client.model = "model"
        client.compute_prompt_id = MagicMock(return_value="prompt-id")
        mk_client.return_value = client
        yield assign_mock, discover_mock


# ===========================================================================
# Non-PG: degradation + sentinel + Fix-2 interplay
# ===========================================================================


@pytest.mark.asyncio
async def test_lock_degrades_to_acquired_when_no_engine():
    """The advisory lock degrades to 'acquired' when the DB engine is
    unavailable (e.g. unit tests with no initialized DB) so lock-infra problems
    never block topicization."""
    fake_db = MagicMock()
    fake_db.processing_storage_engine = None

    with patch(
        "tg_parser.storage.sqlalchemy.database.Database.get_instance",
        return_value=fake_db,
    ):
        async with channel_topicization_lock("ch1") as acquired:
            assert acquired is True


@pytest.mark.asyncio
async def test_lock_degrades_to_acquired_when_no_db_context():
    """If ``Database.get_instance`` raises (no DB context at all) the guard still
    degrades to 'acquired' rather than crashing the run."""
    with patch(
        "tg_parser.storage.sqlalchemy.database.Database.get_instance",
        side_effect=RuntimeError("no DB"),
    ):
        async with channel_topicization_lock("ch1") as acquired:
            assert acquired is True


def test_locked_skip_result_shape_is_caller_compatible():
    """The benign skip sentinel is shaped exactly like a real run_topicization
    return so every caller (pipeline/dispatch/scheduler) handles it without a
    KeyError."""
    res = _locked_skip_result()
    # Keys consumed by run_full_pipeline / _retopicize_source / re-escalation.
    for key in ("topics_count", "bundles_count", "total_tokens"):
        assert res[key] == 0
    assert res["skipped_locked"] is True
    assert res["last_batch_error"] is None
    assert res["rejection_breakdown"] == {}


@pytest.mark.asyncio
async def test_run_topicization_returns_sentinel_when_lock_held():
    """When the channel lock is already held, run_topicization is a benign no-op:
    it returns the skip sentinel WITHOUT running the expensive inner body (no LLM
    client, no batch run) and WITHOUT raising."""
    with (
        patch(
            "tg_parser.services.topicization_service.channel_topicization_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        patch(
            "tg_parser.services.topicization_service._topicize_channel_locked",
            new_callable=AsyncMock,
        ) as inner,
    ):
        res = await run_topicization("labdiagnostica")

    assert res["skipped_locked"] is True
    assert res["topics_count"] == 0
    inner.assert_not_awaited()  # the expensive funnel body did NOT run


@pytest.mark.asyncio
async def test_run_topicization_runs_inner_when_lock_acquired():
    """When the lock IS acquired the wrapper delegates to the real inner funnel."""
    sentinel = {"topics_count": 3, "bundles_count": 1, "total_tokens": 42}
    with (
        patch(
            "tg_parser.services.topicization_service.channel_topicization_lock",
            lambda *_a, **_k: _yield_lock(True),
        ),
        patch(
            "tg_parser.services.topicization_service._topicize_channel_locked",
            new_callable=AsyncMock,
            return_value=sentinel,
        ) as inner,
    ):
        res = await run_topicization("labdiagnostica", force=True)

    assert res == sentinel
    inner.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_skip_does_not_arm_fix2_marker():
    """BUG-072 × BUG-071 Fix-2 interplay: a re-escalation that is skipped because
    another full run holds the channel lock is NOT a failed 0-card attempt — it
    must NOT arm the cooldown marker (skip ≠ failure)."""
    doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
    failure_repo = _FakeFailureRepo()
    marker_ref = _reescalation_marker_ref("labdiagnostica")

    # The real run_topicization is invoked by the re-escalation branch; force its
    # advisory lock to report "already held" so it returns the skip sentinel. The
    # branch then FALLS THROUGH to the cheap incremental path (stubbed offline).
    with (
        patch(
            "tg_parser.services.topicization_service.channel_topicization_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        _patch_incremental_phase(
            assign_return=([], [doc.source_ref]),
            discover_return=([], [], [doc.source_ref], 0),
        ),
    ):
        result = await run_incremental_topicization(
            "labdiagnostica",
            [doc.source_ref],
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    # No exception, benign result, and the cooldown marker was left untouched
    # (a lock-skip is a benign no-op, not a failed 0-card attempt).
    assert marker_ref not in failure_repo.rows
    assert result.coverage_after == 0.0


@pytest.mark.asyncio
async def test_lock_skip_falls_through_to_incremental_not_abandoned():
    """BUG-072 (Bugbot follow-up): a lock-skipped re-escalation must NOT abandon
    the tick's new docs. It suppresses ONLY the expensive full re-escalation and
    falls through to the cheap incremental Phase 1/2 path (mirroring the BUG-071
    cooldown fall-through), so the new docs are still processed this tick — while
    the cooldown marker stays untouched (skip ≠ failure)."""
    doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
    failure_repo = _FakeFailureRepo()
    marker_ref = _reescalation_marker_ref("labdiagnostica")

    with (
        patch(
            "tg_parser.services.topicization_service.channel_topicization_lock",
            lambda *_a, **_k: _yield_lock(False),
        ),
        # The expensive full re-escalation funnel must NOT run a full corpus pass.
        patch(
            "tg_parser.services.topicization_service._topicize_channel_locked",
            new_callable=AsyncMock,
        ) as inner_full,
        _patch_incremental_phase(
            assign_return=([], [doc.source_ref]),
            discover_return=([], [], [doc.source_ref], 0),
        ) as (assign_mock, discover_mock),
    ):
        await run_incremental_topicization(
            "labdiagnostica",
            [doc.source_ref],
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    # The expensive full re-escalation body did NOT run (lock held by a peer).
    inner_full.assert_not_awaited()
    # ...but the cheap incremental Phase 1 + Phase 2 DID run on the new docs
    # (docs not abandoned).
    assert assign_mock.await_count == 1
    assert discover_mock.await_count == 1
    # Cooldown marker untouched (benign skip, not a failed attempt).
    assert marker_ref not in failure_repo.rows


@pytest.mark.asyncio
async def test_acquired_zero_card_run_still_arms_fix2_marker():
    """Contrast guard: when the lock IS acquired and the full run persists 0
    cards, the existing Fix-2 arming behaviour is unchanged (the acquiring run
    owns the marker bookkeeping)."""
    doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
    failure_repo = _FakeFailureRepo()
    marker_ref = _reescalation_marker_ref("labdiagnostica")

    with (
        patch(
            "tg_parser.services.topicization_service.channel_topicization_lock",
            lambda *_a, **_k: _yield_lock(True),
        ),
        # Inner funnel runs but persists 0 cards (the BUG-071 truncation class).
        patch(
            "tg_parser.services.topicization_service._topicize_channel_locked",
            new_callable=AsyncMock,
            return_value={"topics_count": 0, "total_tokens": 0},
        ),
    ):
        await run_incremental_topicization(
            "labdiagnostica",
            [doc.source_ref],
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    # 0 persisted cards on an acquired run → marker ARMED (cooldown engages).
    assert marker_ref in failure_repo.rows
    assert failure_repo.rows[marker_ref]["attempts"] == 1


# ===========================================================================
# PG-gated: real advisory-lock behaviour
# ===========================================================================


@pg_only
@pytest.mark.asyncio
async def test_second_concurrent_acquire_same_channel_is_refused(test_db):
    """Two concurrent acquires for the SAME channel: the first wins, the second
    is refused (no double full run); a DIFFERENT channel is NOT blocked; and the
    lock releases on context exit so a later acquire succeeds again."""
    async with channel_topicization_lock("chan_a") as first:
        assert first is True

        # Same channel, second concurrent acquire → refused.
        async with channel_topicization_lock("chan_a") as second:
            assert second is False

        # Different channel → not blocked.
        async with channel_topicization_lock("chan_b") as other:
            assert other is True

    # First lock released on exit → a fresh acquire for chan_a succeeds again.
    async with channel_topicization_lock("chan_a") as reacquired:
        assert reacquired is True


@pg_only
@pytest.mark.asyncio
async def test_run_topicization_skips_when_channel_lock_held(test_db):
    """End-to-end through the real funnel: while another run holds the channel
    lock, run_topicization for that channel returns the skip sentinel and does
    NOT run the inner body; a different channel runs normally."""
    sentinel = {"topics_count": 2, "bundles_count": 0, "total_tokens": 7}
    with patch(
        "tg_parser.services.topicization_service._topicize_channel_locked",
        new_callable=AsyncMock,
        return_value=sentinel,
    ) as inner:
        async with channel_topicization_lock("chan_held") as held:
            assert held is True

            # Same channel → skipped, inner funnel not run.
            skipped = await run_topicization("chan_held")
            assert skipped["skipped_locked"] is True
            inner.assert_not_awaited()

            # Different channel → runs the inner funnel.
            ran = await run_topicization("chan_free")
            assert ran == sentinel
            inner.assert_awaited_once()


@pg_only
@pytest.mark.asyncio
async def test_cross_path_contends_on_same_normalized_key(test_db):
    """The scheduler re-escalation path, the dispatch/pipeline path and the CLI
    all identify the channel by its NORMALIZED id, so they contend on the SAME
    advisory lock. Holding the lock for ``chx`` blocks both ``chx`` and ``@chx``
    (which normalizes to ``chx``)."""
    with patch(
        "tg_parser.services.topicization_service._topicize_channel_locked",
        new_callable=AsyncMock,
        return_value={"topics_count": 1},
    ) as inner:
        async with channel_topicization_lock("chx") as held:
            assert held is True

            # Dispatch/pipeline path passes the bare normalized id.
            r1 = await run_topicization("chx")
            # A caller that passes the @-prefixed form normalizes to the same key.
            r2 = await run_topicization("@chx")

        assert r1["skipped_locked"] is True
        assert r2["skipped_locked"] is True
        inner.assert_not_awaited()


def test_topicization_lock_namespace_is_distinct_from_scheduler():
    """The topicization lock namespace must differ from the scheduler source-lock
    namespace so the two guards never collide in the shared advisory keyspace."""
    from tg_parser.services.scheduler_service import SCHEDULER_SOURCE_LOCK_NS

    assert TOPICIZATION_LOCK_NS != SCHEDULER_SOURCE_LOCK_NS
