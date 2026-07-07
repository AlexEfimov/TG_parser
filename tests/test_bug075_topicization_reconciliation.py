"""BUG-075: convergent topicization coverage reconciliation.

A processed-but-uncovered doc (persisted by a path that never topicizes it —
CLI ``process``, a ``skip_topicize`` run, a crash between processing and
topicization, or the F1 lock-skip widening) used to stay PERMANENTLY
untopicized: it was never in any tick's ``new_doc_refs`` and there was no
standing recovery. BUG-075 adds a STANDING per-tick reconciliation hook that
feeds only NOT-YET-ATTEMPTED uncovered docs to a CHEAP-ONLY incremental run
that can NEVER re-escalate to a full re-topicization.

The five hard-won learnings (each was a separate HIGH finding against the
descoped prototype) are pinned here — learning 5 first:

* **L5 (THE KILLER) — never re-escalate:** ``reconcile_only=True`` forces
  ``should_reescalate=False`` so a 0-card channel fed through reconciliation
  does NOT storm a full ``run_topicization`` and leaves the BUG-071 cooldown
  marker untouched.
* **L1 — standing/convergent:** the hook runs every tick; a deferred run does
  no work and writes no marker, so it is retried (and converges) next tick.
* **L2 — no re-burn:** a second reconciliation pass over the SAME
  perpetually-unassignable docs issues ZERO LLM calls (they carry the
  ``discover_attempted`` marker).
* **L3 — marker invariant:** after a completed Phase 2 only
  ``unassigned_refs − covered_after`` are marked (EXCLUDES Phase-1
  keyword-assigned docs); a discover batch that RAISES marks nothing.
* **L4 — connection lifecycle:** the candidate-selection repo session is
  closed before the incremental run, so no idle dedicated DB connection is
  held across the LLM run.

Plus the hook contract (errors never crash the tick / never pollute
``stage_errors``) and the per-tick ``topicization_reconcile_max_docs`` cap.

Test layers mirror ``tests/test_bug073_pipeline_concurrency.py``:
* **Non-PG (always run)** — flag threading, candidate selection, marker
  invariant, no-storm, no-re-burn, defer-retry, connection lifecycle, hook
  contract (all driven with mocked repos / pipeline / LLM).
* **PG-gated (``TEST_POSTGRES=1``)** — the real ``0x70C2`` advisory-lock
  behaviour for the reconciliation path.
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.api.metrics import (
    TOPICIZATION_DISCOVER_ATTEMPTED_MARK_FAILED_TOTAL,
    TOPICIZATION_RECONCILE_DISCOVER_DOCS_TOTAL,
)
from tg_parser.domain.models import IncrementalTopicizeResult, ProcessedDocument
from tg_parser.services.topicization_service import (
    _DISCOVER_ATTEMPTED_ERROR_CLASS,
    _REESCALATION_ERROR_CLASS,
    _discover_attempted_marker_ref,
    _list_discover_attempted_refs,
    _mark_discover_attempted,
    _run_incremental_topicization_locked,
    run_reconciliation_for_channel,
)

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

CH = "labdiagnostica"


def _ref(n: int) -> str:
    return f"tg:{CH}:post:{n}"


def _make_doc(source_ref: str) -> ProcessedDocument:
    parts = source_ref.split(":")
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=parts[-1],
        channel_id=CH,
        processed_at=datetime.now(UTC),
        text_clean="some text content",
        summary="summary",
        topics=[],
    )


class _Item:
    def __init__(self, source_ref: str) -> None:
        self.source_ref = source_ref


class _Bundle:
    def __init__(self, refs: list[str]) -> None:
        self.items = [_Item(r) for r in refs]


def _card(cid: str = "topic:existing"):
    """A minimal stand-in for a TopicCard — only ``id`` is read by the path."""
    c = MagicMock()
    c.id = cid
    c.title = "existing topic"
    c.scope_in = ["x"]
    return c


def _fake_pipeline(*, assign_result, discover_result):
    """Patch factory: both ``TopicizationPipelineImpl(...)`` calls return this."""
    inst = MagicMock()
    inst.assign_documents_to_topics = AsyncMock(return_value=assign_result)
    inst._discover_single_batch = AsyncMock(return_value=discover_result)
    inst.build_topic_bundle = AsyncMock()
    inst.rejection_breakdown = {}
    return MagicMock(return_value=inst), inst


def _llm_patches():
    """Context managers that neutralise the real LLM factory in the locked body."""
    llm = AsyncMock()
    llm.close = AsyncMock()
    return (
        patch(
            "tg_parser.services.topicization_service.resolve_llm_config",
            return_value=("openai", "key", "model"),
        ),
        patch(
            "tg_parser.services.topicization_service.create_llm_client",
            return_value=llm,
        ),
    )


# ===========================================================================
# Setting
# ===========================================================================


def test_reconcile_max_docs_setting_default():
    from tg_parser.config import settings

    assert settings.topicization_reconcile_max_docs == 200


# ===========================================================================
# Marker helpers (synthetic processing_failures ref — no migration)
# ===========================================================================


def test_marker_ref_namespaced_and_collision_safe():
    ref = _discover_attempted_marker_ref(_ref(7))
    assert ref == f"topicization:discover_attempted:tg:{CH}:post:7"
    # Never collides with a real doc ref (``tg:...``) nor the per-channel
    # re-escalation marker (``topicization:reescalation:...``).
    assert not ref.startswith("tg:")
    assert not ref.startswith("topicization:reescalation:")


@pytest.mark.asyncio
async def test_list_discover_attempted_strips_prefix_and_ignores_others():
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        {"source_ref": _discover_attempted_marker_ref(_ref(1))},
        {"source_ref": _discover_attempted_marker_ref(_ref(2))},
        {"source_ref": "topicization:reescalation:" + CH},  # not a discover marker
        {"source_ref": _ref(3)},  # a real failure row — ignored
    ]
    attempted = await _list_discover_attempted_refs(failure_repo, CH)
    assert attempted == {_ref(1), _ref(2)}


@pytest.mark.asyncio
async def test_list_discover_attempted_degrades_on_error():
    failure_repo = AsyncMock()
    failure_repo.list_failures.side_effect = RuntimeError("db down")
    assert await _list_discover_attempted_refs(failure_repo, CH) == set()
    assert await _list_discover_attempted_refs(None, CH) == set()


@pytest.mark.asyncio
async def test_mark_discover_attempted_noop_on_empty():
    failure_repo = AsyncMock()
    await _mark_discover_attempted(failure_repo, CH, [])
    await _mark_discover_attempted(None, CH, [_ref(1)])
    failure_repo.record_failure.assert_not_awaited()


def _mark_failed_metric_value(channel_id: str) -> float:
    # .labels(...) creates the series at 0 if it does not exist yet, so a
    # before-read is always safe and returns 0.0 for a fresh channel_id.
    return TOPICIZATION_DISCOVER_ATTEMPTED_MARK_FAILED_TOTAL.labels(
        channel_id=channel_id
    )._value.get()


@pytest.mark.asyncio
async def test_mark_discover_attempted_failure_emits_metric_warns_and_does_not_crash(caplog):
    """BUG-075 (R1 hardening): a persistent marker-write failure must (a) increment
    the new counter once per failed ref, (b) log at WARNING (the only quiet path to
    bounded re-burn), and (c) NEVER crash the best-effort marker loop."""
    channel = "kdl_r1_mark_failed"  # unique → isolates this test's counter series
    failure_repo = AsyncMock()
    failure_repo.record_failure.side_effect = RuntimeError("processing_failures down")
    refs = [f"tg:{channel}:post:{i}" for i in (1, 2)]

    before = _mark_failed_metric_value(channel)
    with caplog.at_level(logging.WARNING):
        # (c) must NOT raise despite every write failing.
        await _mark_discover_attempted(failure_repo, channel, refs)
    after = _mark_failed_metric_value(channel)

    # (a) one increment per failed ref.
    assert after - before == len(refs)
    # (b) logged at WARNING (not debug) and actionable.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("discover_attempted_mark_failed" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_mark_discover_attempted_success_does_not_emit_failure_metric():
    """Control: a SUCCESSFUL marker write writes the row and does NOT touch the
    R1 failure counter."""
    channel = "kdl_r1_mark_ok"
    failure_repo = AsyncMock()
    refs = [f"tg:{channel}:post:{i}" for i in (1, 2)]

    before = _mark_failed_metric_value(channel)
    await _mark_discover_attempted(failure_repo, channel, refs)
    after = _mark_failed_metric_value(channel)

    assert failure_repo.record_failure.await_count == len(refs)
    assert after - before == 0


# ===========================================================================
# L5 (THE KILLER) — reconciliation NEVER re-escalates to a full run
# ===========================================================================


@pytest.mark.asyncio
async def test_reconcile_only_zero_card_channel_does_not_storm_full_run():
    """A 0-card channel with new docs fed through the reconciliation path
    (``reconcile_only=True``) must NOT trigger ``run_topicization`` and must
    leave the BUG-071 re-escalation cooldown marker UNTOUCHED."""
    docs = [_make_doc(_ref(i)) for i in (1, 2)]
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: next(
        (d for d in docs if d.source_ref == r), None
    )
    processed_repo.list_by_channel.return_value = docs
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []  # 0 cards → escalation trigger
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []  # nothing covered
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    pipeline_cls, _ = _fake_pipeline(
        assign_result=([], [_ref(1), _ref(2)]),
        discover_result=([], [], [_ref(1), _ref(2)], 3),  # both unassignable
    )
    cfg, factory = _llm_patches()
    with (
        patch("tg_parser.services.topicization_service.TopicizationPipelineImpl", pipeline_cls),
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
        ) as full_run,
        cfg,
        factory,
    ):
        await _run_incremental_topicization_locked(
            CH,
            [_ref(1), _ref(2)],
            cross_channel=False,
            reconcile_only=True,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    # L5: the expensive full re-topicization funnel is NEVER reached.
    full_run.assert_not_awaited()
    # The re-escalation cooldown marker is untouched (no arm/clear with the
    # re-escalation error class).
    for call in failure_repo.record_failure.await_args_list:
        assert call.kwargs.get("error_class") != _REESCALATION_ERROR_CLASS


@pytest.mark.asyncio
async def test_without_reconcile_flag_zero_card_channel_still_escalates():
    """Control: the SAME 0-card channel WITHOUT ``reconcile_only`` DOES escalate
    to ``run_topicization`` — proving the flag is exactly what disables it."""
    docs = [_make_doc(_ref(1))]
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: next(
        (d for d in docs if d.source_ref == r), None
    )
    processed_repo.list_by_channel.return_value = docs
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []  # 0 cards
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    with patch(
        "tg_parser.services.topicization_service.run_topicization",
        new_callable=AsyncMock,
        return_value={"total_tokens": 0, "topics_count": 0},
    ) as full_run:
        await _run_incremental_topicization_locked(
            CH,
            [_ref(1)],
            cross_channel=False,
            reconcile_only=False,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    full_run.assert_awaited_once()


# ===========================================================================
# L3 — marker invariant: unassigned_refs − covered_after, not on a raised batch
# ===========================================================================


@pytest.mark.asyncio
async def test_marker_written_for_unassigned_minus_covered_only():
    """After a completed Phase 2, mark exactly ``unassigned_refs − covered_after``.

    d1..d4 all reach Phase-2 discover. d1 ends up covered (in a bundle); d2/d3/d4
    stay uncovered (quality-rejected / unassignable / dropped). Only d2/d3/d4 are
    marked — NOT d1 (covered), and NOT any Phase-1 keyword-assigned doc (there
    are none here by construction)."""
    refs = [_ref(i) for i in (1, 2, 3, 4)]
    docs = [_make_doc(r) for r in refs]
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: next(
        (d for d in docs if d.source_ref == r), None
    )
    processed_repo.list_by_channel.return_value = docs
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [_card()]  # non-zero → no escalation
    topic_bundle_repo = AsyncMock()
    # After Phase 2, only d1 is covered.
    topic_bundle_repo.list_by_channel.return_value = [_Bundle([_ref(1)])]
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    pipeline_cls, _ = _fake_pipeline(
        assign_result=([], refs),  # Phase 1 assigns nothing → all to discover
        discover_result=([], [], [_ref(3)], 5),
    )
    cfg, factory = _llm_patches()
    with (
        patch("tg_parser.services.topicization_service.TopicizationPipelineImpl", pipeline_cls),
        cfg,
        factory,
    ):
        await _run_incremental_topicization_locked(
            CH,
            refs,
            cross_channel=False,
            reconcile_only=True,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    marked = {
        c.kwargs["source_ref"]
        for c in failure_repo.record_failure.await_args_list
        if c.kwargs.get("error_class") == _DISCOVER_ATTEMPTED_ERROR_CLASS
    }
    assert marked == {
        _discover_attempted_marker_ref(_ref(2)),
        _discover_attempted_marker_ref(_ref(3)),
        _discover_attempted_marker_ref(_ref(4)),
    }
    assert _discover_attempted_marker_ref(_ref(1)) not in marked  # covered → not marked


@pytest.mark.asyncio
async def test_no_marker_when_discover_batch_raises():
    """A discover batch that RAISES (hard LLM/parse error) is NOT a completed
    attempt: the exception propagates BEFORE the marker write, so NO doc is
    marked and they are all retried next pass (L3)."""
    refs = [_ref(1), _ref(2)]
    docs = [_make_doc(r) for r in refs]
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: next(
        (d for d in docs if d.source_ref == r), None
    )
    processed_repo.list_by_channel.return_value = docs
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [_card()]
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    pipeline_cls, inst = _fake_pipeline(
        assign_result=([], refs),
        discover_result=([], [], [], 0),
    )
    inst._discover_single_batch.side_effect = RuntimeError("LLM hard error")
    cfg, factory = _llm_patches()
    with (
        patch("tg_parser.services.topicization_service.TopicizationPipelineImpl", pipeline_cls),
        cfg,
        factory,
    ):
        with pytest.raises(RuntimeError, match="LLM hard error"):
            await _run_incremental_topicization_locked(
                CH,
                refs,
                cross_channel=False,
                reconcile_only=True,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )

    # No discover_attempted marker written on the raised path.
    for c in failure_repo.record_failure.await_args_list:
        assert c.kwargs.get("error_class") != _DISCOVER_ATTEMPTED_ERROR_CLASS


# ===========================================================================
# reconcile-discover-docs counter (post-refill watch) — docs fed to Phase-2
# discover ON THE RECONCILE PATH specifically, NOT the normal incremental path.
# ===========================================================================


def _reconcile_discover_metric_value(channel_id: str) -> float:
    # .labels(...) materialises the series at 0 if absent, so a before-read is
    # always safe and returns 0.0 for a fresh channel_id.
    return TOPICIZATION_RECONCILE_DISCOVER_DOCS_TOTAL.labels(channel_id=channel_id)._value.get()


@pytest.mark.asyncio
async def test_reconcile_discover_counter_increments_with_docs_fed_to_discover():
    """On the reconcile path (``reconcile_only=True``), the counter increments by
    the number of docs that actually ENTER Phase-2 discover (``unassigned_docs``)."""
    channel = "kdl_reconcile_discover_inc"  # unique → isolates this series
    refs = [_ref(i) for i in (1, 2, 3, 4)]
    docs = [_make_doc(r) for r in refs]
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: next(
        (d for d in docs if d.source_ref == r), None
    )
    processed_repo.list_by_channel.return_value = docs
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [_card()]  # non-zero → no escalation
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    # Phase 1 keyword-assigns nothing → all 4 docs go to Phase-2 discover → count == 4.
    pipeline_cls, _ = _fake_pipeline(
        assign_result=([], refs),
        discover_result=([], [], list(refs), 7),
    )
    cfg, factory = _llm_patches()
    before = _reconcile_discover_metric_value(channel)
    with (
        patch("tg_parser.services.topicization_service.TopicizationPipelineImpl", pipeline_cls),
        cfg,
        factory,
    ):
        await _run_incremental_topicization_locked(
            channel,
            refs,
            cross_channel=False,
            reconcile_only=True,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )
    after = _reconcile_discover_metric_value(channel)

    assert after - before == 4  # exactly the docs fed to Phase-2 discover


@pytest.mark.asyncio
async def test_reconcile_discover_counter_not_incremented_on_normal_incremental_path():
    """Control: the SAME feed on the NORMAL incremental path (reconcile_only=False)
    must NOT touch the reconcile-discover counter — it isolates the reconcile path."""
    channel = "kdl_reconcile_discover_normal"
    refs = [_ref(1), _ref(2)]
    docs = [_make_doc(r) for r in refs]
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.side_effect = lambda r: next(
        (d for d in docs if d.source_ref == r), None
    )
    processed_repo.list_by_channel.return_value = docs
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [_card()]  # non-zero → no escalation
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = []

    pipeline_cls, _ = _fake_pipeline(
        assign_result=([], refs),  # all to discover
        discover_result=([], [], refs, 4),
    )
    cfg, factory = _llm_patches()
    before = _reconcile_discover_metric_value(channel)
    with (
        patch("tg_parser.services.topicization_service.TopicizationPipelineImpl", pipeline_cls),
        cfg,
        factory,
    ):
        await _run_incremental_topicization_locked(
            channel,
            refs,
            cross_channel=False,
            reconcile_only=False,  # NORMAL path
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )
    after = _reconcile_discover_metric_value(channel)

    assert after - before == 0


@pytest.mark.asyncio
async def test_reconcile_discover_counter_silent_on_all_attempted_shortcircuit():
    """L2 steady state (zero re-burn): when every uncovered doc already carries a
    ``discover_attempted`` marker, the hook short-circuits (``all_attempted``) and
    issues ZERO discover calls — the reconcile-discover counter must NOT move."""
    channel = "kdl_reconcile_discover_allattempted"
    pr, tcr, tbr, fr = _hook_repos(
        docs=[_ref(1), _ref(2)],
        covered=[],
        markers=[_ref(1), _ref(2)],  # both already attempted
    )
    before = _reconcile_discover_metric_value(channel)
    with patch(
        "tg_parser.services.topicization_service.run_incremental_topicization",
        new_callable=AsyncMock,
    ) as incr:
        summary = await run_reconciliation_for_channel(
            channel_id=channel,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )
    after = _reconcile_discover_metric_value(channel)

    incr.assert_not_awaited()  # no discover at all
    assert summary["skipped_reason"] == "all_attempted"
    assert after - before == 0  # zero re-burn → counter flat


# ===========================================================================
# Reconciliation hook — candidate selection / cap / flag threading
# ===========================================================================


def _hook_repos(*, docs, covered, markers):
    processed_repo = AsyncMock()
    processed_repo.list_by_channel.return_value = [_make_doc(r) for r in docs]
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = [_Bundle(covered)] if covered else []
    failure_repo = AsyncMock()
    failure_repo.list_failures.return_value = [
        {"source_ref": _discover_attempted_marker_ref(r)} for r in markers
    ]
    return processed_repo, topic_card_repo, topic_bundle_repo, failure_repo


@pytest.mark.asyncio
async def test_hook_feeds_uncovered_minus_attempted_capped_with_reconcile_flag():
    """Candidate = uncovered − attempted, capped at ``max_docs``, fed via
    ``run_incremental_topicization(reconcile_only=True, defer_if_locked=True)``."""
    pr, tcr, tbr, fr = _hook_repos(
        docs=[_ref(i) for i in range(1, 6)],
        covered=[_ref(1)],  # d1 covered
        markers=[_ref(2)],  # d2 already attempted
    )
    sentinel = IncrementalTopicizeResult(tokens_used=11, coverage_after=42.0)
    with (
        patch(
            "tg_parser.services.topicization_service._RECONCILE_RNG",
            __import__("random").Random(0),
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=sentinel,
        ) as incr,
    ):
        summary = await run_reconciliation_for_channel(
            channel_id=CH,
            max_docs=2,
            cross_channel=False,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )

    incr.assert_awaited_once()
    args, kwargs = incr.await_args
    assert args[0] == CH
    # uncovered {3,4,5} − none → 3 candidates; capped to a RANDOM 2-subset
    # (BUG-075 anti-starvation: not the stable head [_ref(3), _ref(4)]).
    fed = args[1]
    assert len(fed) == 2
    assert set(fed).issubset({_ref(3), _ref(4), _ref(5)})
    assert kwargs["reconcile_only"] is True
    assert kwargs["defer_if_locked"] is True
    assert summary["candidates"] == 3
    assert summary["fed"] == 2
    assert summary["tokens"] == 11
    assert summary["skipped_reason"] is None


@pytest.mark.asyncio
async def test_hook_no_reburn_when_all_uncovered_already_attempted():
    """L2 steady state: every uncovered doc already carries a marker → ZERO LLM
    calls (the incremental run is not even invoked)."""
    pr, tcr, tbr, fr = _hook_repos(
        docs=[_ref(1), _ref(2)],
        covered=[],
        markers=[_ref(1), _ref(2)],  # both already attempted
    )
    with patch(
        "tg_parser.services.topicization_service.run_incremental_topicization",
        new_callable=AsyncMock,
    ) as incr:
        summary = await run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )

    incr.assert_not_awaited()
    assert summary["candidates"] == 0
    assert summary["fed"] == 0
    assert summary["tokens"] == 0
    assert summary["skipped_reason"] == "all_attempted"


@pytest.mark.asyncio
async def test_hook_all_covered_short_circuits():
    pr, tcr, tbr, fr = _hook_repos(docs=[_ref(1)], covered=[_ref(1)], markers=[])
    with patch(
        "tg_parser.services.topicization_service.run_incremental_topicization",
        new_callable=AsyncMock,
    ) as incr:
        summary = await run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )
    incr.assert_not_awaited()
    assert summary["skipped_reason"] == "all_covered"


@pytest.mark.asyncio
async def test_hook_defer_is_retried_next_tick():
    """L1: a deferred reconciliation does no work and writes no marker, so the
    SAME candidate is re-fed on the next standing tick → convergence survives a
    single defer."""
    pr, tcr, tbr, fr = _hook_repos(docs=[_ref(3)], covered=[], markers=[])
    deferred = IncrementalTopicizeResult(deferred_locked=True)
    with patch(
        "tg_parser.services.topicization_service.run_incremental_topicization",
        new_callable=AsyncMock,
        return_value=deferred,
    ) as incr:
        s1 = await run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )
        # Next tick: markers unchanged (defer wrote none) → same candidate.
        s2 = await run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )

    assert s1["deferred"] is True
    assert s2["deferred"] is True
    assert incr.await_count == 2
    for call in incr.await_args_list:
        assert call.args[1] == [_ref(3)]  # retried, not abandoned


@pytest.mark.asyncio
async def test_hook_max_docs_zero_disables_cap():
    pr, tcr, tbr, fr = _hook_repos(docs=[_ref(i) for i in range(1, 6)], covered=[], markers=[])
    with patch(
        "tg_parser.services.topicization_service.run_incremental_topicization",
        new_callable=AsyncMock,
        return_value=IncrementalTopicizeResult(),
    ) as incr:
        await run_reconciliation_for_channel(
            channel_id=CH,
            max_docs=0,
            processed_repo=pr,
            topic_card_repo=tcr,
            topic_bundle_repo=tbr,
            failure_repo=fr,
        )
    assert incr.await_args.args[1] == [_ref(i) for i in range(1, 6)]


@pytest.mark.asyncio
async def test_capped_backlog_does_not_starve_tail_under_unmarkable_head():
    """BUG-075 (Bugbot medium): a backlog LARGER than ``max_docs`` whose HEAD docs
    are perpetually uncovered-but-UNMARKABLE (e.g. keyword-assigned-but-not-covered
    — never enter Phase-2 ``unassigned_refs`` so never earn a ``discover_attempted``
    marker) must NOT starve the tail. With the old stable ``candidates[:max_docs]``
    the head would occupy every slot forever and the tail would NEVER be fed; with
    the randomised slice every candidate gets a fair chance and the tail converges.

    Setup: 2 unmarkable head docs + 3 markable tail docs, cap=2. Tail docs complete
    a discover (become covered + marked → leave the candidate set); head docs stay
    uncovered + unmarked forever. Asserts every tail doc is eventually fed."""
    import random as _random

    head = [_ref(1), _ref(2)]
    tail = [_ref(3), _ref(4), _ref(5)]
    all_refs = head + tail
    marked: set[str] = set()
    covered: set[str] = set()

    pr = AsyncMock()
    pr.list_by_channel.return_value = [_make_doc(r) for r in all_refs]
    tcr = AsyncMock()
    tbr = AsyncMock()
    tbr.list_by_channel.side_effect = lambda *_a, **_k: (
        [_Bundle(sorted(covered))] if covered else []
    )
    fr = AsyncMock()
    fr.list_failures.side_effect = lambda *_a, **_k: [
        {"source_ref": _discover_attempted_marker_ref(r)} for r in sorted(marked)
    ]

    fed_union: set[str] = set()

    async def _incr(_channel_id, refs, **_kwargs):
        fed_union.update(refs)
        for r in refs:
            if r in tail:
                # Tail docs complete a discover → covered + marked (leave the set).
                covered.add(r)
                marked.add(r)
            # Head docs: keyword-assigned-but-not-covered → neither covered nor
            # marked → remain candidates forever (the starvation pressure).
        return IncrementalTopicizeResult()

    with (
        patch(
            "tg_parser.services.topicization_service._RECONCILE_RNG",
            _random.Random(12345),
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            side_effect=_incr,
        ),
    ):
        for _ in range(200):
            await run_reconciliation_for_channel(
                channel_id=CH,
                max_docs=2,
                processed_repo=pr,
                topic_card_repo=tcr,
                topic_bundle_repo=tbr,
                failure_repo=fr,
            )
            if set(tail).issubset(fed_union):
                break

    # The tail was reconciled despite the unmarkable head monopolising candidates.
    assert set(tail).issubset(fed_union)
    assert marked == set(tail)  # every tail doc consumed exactly one discover


@pytest.mark.asyncio
async def test_hook_no_docs_short_circuits():
    pr = AsyncMock()
    pr.list_by_channel.return_value = []
    summary = await run_reconciliation_for_channel(
        channel_id=CH,
        processed_repo=pr,
        topic_card_repo=AsyncMock(),
        topic_bundle_repo=AsyncMock(),
        failure_repo=AsyncMock(),
    )
    assert summary["skipped_reason"] == "no_docs"


# ===========================================================================
# L4 — connection lifecycle: candidate session closed BEFORE the LLM run
# ===========================================================================


@pytest.mark.asyncio
async def test_hook_closes_candidate_session_before_incremental_run():
    """L4 (production path, no injected repos): the candidate-selection
    ``processing_repos`` session is CLOSED before ``run_incremental_topicization``
    is invoked, so no idle dedicated DB connection is held across the LLM run."""
    state = {"session_open": False, "open_during_incremental": None}

    processed_repo = AsyncMock()
    processed_repo.list_by_channel.return_value = [_make_doc(_ref(1))]
    processed_repo.session = MagicMock()
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []  # d1 uncovered

    @contextlib.asynccontextmanager
    async def _spy_processing_repos():
        state["session_open"] = True
        try:
            yield (processed_repo, AsyncMock(), topic_bundle_repo, MagicMock())
        finally:
            state["session_open"] = False

    fr = AsyncMock()
    fr.list_failures.return_value = []  # no markers → d1 is a candidate

    async def _spy_incremental(*_a, **_k):
        state["open_during_incremental"] = state["session_open"]
        return IncrementalTopicizeResult()

    with (
        patch(
            "tg_parser.services.topicization_service.processing_repos",
            _spy_processing_repos,
        ),
        patch(
            "tg_parser.services.topicization_service.SAProcessingFailureRepo",
            return_value=fr,
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            side_effect=_spy_incremental,
        ) as incr,
    ):
        await run_reconciliation_for_channel(channel_id=CH)

    incr.assert_called_once()
    assert state["open_during_incremental"] is False  # session released first


# ===========================================================================
# Hook contract — source-level invariants (mirror tests/test_f5c_scheduler_hook)
# ===========================================================================


def _scheduler_src() -> str:
    import inspect

    from tg_parser.services import scheduler_service

    return inspect.getsource(scheduler_service)


def test_reconcile_hook_runs_every_tick_decoupled_from_new_doc_refs():
    """The BUG-075 hook sits at the outer (16-space) indentation of
    ``_process_source`` — it runs on EVERY tick, NOT nested inside
    ``if new_doc_refs:`` (a doc the scheduler never saw as "new" is exactly the
    abandonment case it must converge)."""
    src = _scheduler_src()
    decoupled = (
        "\n                try:\n"
        "                    from tg_parser.services.topicization_service import (\n"
        "                        run_reconciliation_for_channel,\n"
    )
    assert decoupled in src, (
        "BUG-075 reconcile hook must run on every tick at the outer (16-space) "
        "indentation of _process_source, decoupled from `if new_doc_refs:`."
    )


def test_reconcile_hook_runs_after_watchlist():
    src = _scheduler_src()
    wl = src.find("wl_summary = await run_watchlist_check_for_channel(")
    rec = src.find("rec_summary = await run_reconciliation_for_channel(")
    assert wl > 0 and rec > 0
    assert wl < rec, "BUG-075 reconcile hook must run after the F11 watchlist check"


def test_reconcile_hook_never_pollutes_stage_errors():
    """Hook contract: a reconciliation failure — INCLUDING a billing error — is
    a silent ``logger.exception`` and must NEVER add to ``stage_errors`` (which
    would make ``success = not stage_errors`` lie about upstream stages) and
    must NEVER crash the tick."""
    src = _scheduler_src()
    rec = src.find("rec_summary = await run_reconciliation_for_channel(")
    assert rec > 0, "reconcile hook anchor missing"
    completed = src.find('"Source %s completed', rec)
    block = src[rec:completed]

    assert "except Exception as rec_exc" in block, "generic Exception clause missing"
    assert "stage_errors.append" not in block, (
        "BUG-075 reconcile hook must NOT add to stage_errors (post-processing "
        "must not lie about upstream stages)."
    )
    assert "logger.exception" in block, "reconcile failure must be a silent log"


# ===========================================================================
# PG-gated — real 0x70C2 advisory-lock behaviour for the reconcile path
# ===========================================================================


@pg_only
@pytest.mark.asyncio
async def test_reconcile_defers_under_incremental_lock_contention(test_db):
    """The reconciliation path uses ``defer_if_locked=True`` over the real
    ``0x70C2`` incremental lock: while another incremental run holds the lock,
    a reconcile run benignly DEFERS (inner body not run → no double Phase-2
    spend) and is retried next tick."""
    from tg_parser.services.topicization_service import (
        channel_incremental_topicization_lock,
    )

    pr, tcr, tbr, fr = _hook_repos(docs=[_ref(1)], covered=[], markers=[])
    with patch(
        "tg_parser.services.topicization_service._run_incremental_topicization_locked",
        new_callable=AsyncMock,
    ) as inner:
        async with channel_incremental_topicization_lock(CH) as held:
            assert held is True
            summary = await run_reconciliation_for_channel(
                channel_id=CH,
                processed_repo=pr,
                topic_card_repo=tcr,
                topic_bundle_repo=tbr,
                failure_repo=fr,
            )

    assert summary["deferred"] is True
    inner.assert_not_awaited()  # deferred → no expensive Phase-2 work
