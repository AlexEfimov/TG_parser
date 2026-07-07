"""BUG-077: token-leak hardening of the BUG-076 resumable full topicization.

The committed BUG-076 feature (dark behind ``topicization_full_resume_enabled``)
left six residual unproductive-spend surfaces:

* **F1 (MUST-before-enable)** — the resume driver retries a live checkpoint
  EVERY tick with the BUG-071 cooldown deliberately disarmed, so a chunk that
  keeps failing WITHOUT advancing ``chunks_done`` was an unbounded token drip.
  Now a ``consecutive_noprogress_resumes`` counter (failure-path checkpoint
  write) + a shared :func:`noprogress_circuit_open` predicate gate BOTH entry
  points (driver AND pipeline — the latter covers the 0-card
  ``should_reescalate`` escalation path). Lock-skips are neutral; any durable
  advance resets the counter; after the cooldown TTL one probe is allowed.
* **F2 (folded into F1)** — a MALFORMED merge reply (e.g. string group ids)
  crashed out of ``run_topicization`` and was re-driven bare every tick; now a
  clean resumable halt that feeds the F1 counter.
* **F4 (MUST-before-enable)** — the BUG-075 reconcile hook fed docs still
  pinned by a live full run into Phase-2 discover (guaranteed double-spend);
  now DEFERRED (not abandoned) while a live checkpoint exists, dark when the
  flag is off.
* **F9** — non-advancing halts were invisible: a ``full_run_chunk_failed_total``
  counter (labelled by reason) + PRE-commit token emission make the drip
  alertable; an in-process atomic-commit failure is a clean counted halt.
* **F3** — a checkpoint READ error was indistinguishable from "no checkpoint"
  and started a FRESH pinned run (re-burn + duplicate cards); now
  :class:`FullCheckpointReadError` → benign 0-cost abort. A resume whose
  checkpoint vanished under the lock is a no-op, not a fresh run.
* **F5** — the stale-restart wipe was ``delete_by_channel`` (nuked
  incremental/discover cards too); chunked cards are now stamped with the
  checkpoint's ``run_id`` and the wipe is scoped to them, with a broad-wipe
  fallback for pre-fix checkpoints (``cards_stamped=False``).
* **F7** — a successful legacy monolithic run clears a leftover checkpoint so
  a future flag re-enable cannot resume a stale plan on top of its result.

All mock-driven (no Postgres) — the BUG-076 PG atomicity test still covers the
shared commit path.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.domain.models import (
    Anchor,
    MessageType,
    ProcessedDocument,
    TopicCard,
    TopicType,
)
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.processing.topicization_checkpoint import (
    FULL_CHECKPOINT_ERROR_CLASS,
    FullRunCheckpoint,
    full_checkpoint_marker_ref,
    noprogress_circuit_open,
    parse_checkpoint,
    planned_ref_hash,
)

CH = "labdiagnostica"
_BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _ref(n: int) -> str:
    return f"tg:{CH}:post:{n}"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_doc(n: int) -> ProcessedDocument:
    ref = _ref(n)
    return ProcessedDocument(
        id=f"doc:{ref}",
        source_ref=ref,
        source_message_id=str(n),
        channel_id=CH,
        processed_at=_BASE_TS,
        text_clean=f"clean text body number {n}",
        summary=f"summary {n}",
        topics=[],
    )


def _mk_card(ref: str) -> TopicCard:
    return TopicCard(
        id=f"topic:{ref}",
        title=f"topic for {ref}",
        summary="a short topic summary",
        scope_in=["in"],
        scope_out=["out"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=CH,
                message_id=ref.split(":")[-1],
                message_type=MessageType.POST,
                anchor_ref=ref,
                score=1.0,
            )
        ],
        sources=[CH],
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        tags=["tag"],
    )


def _mk_checkpoint(refs: list[str], **overrides) -> FullRunCheckpoint:
    base = {
        "run_id": "r",
        "planned_refs": list(refs),
        "planned_ref_hash": planned_ref_hash(refs),
        "planned_doc_count": len(refs),
        "chunk_batches": 1,
        "chunks_total": 3,
        "chunks_done": 1,
        "batches_done": 1,
        "tokens_spent_cumulative": 1,
        "final_merge_done": False,
    }
    base.update(overrides)
    return FullRunCheckpoint(**base)


class FakeFailureRepo:
    """In-memory ProcessingFailureRepo (same shape as the BUG-076 suite's)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.session = None

    async def record_failure(
        self,
        source_ref,
        channel_id,
        attempts,
        error_class,
        error_message,
        error_details=None,
        *,
        commit: bool = True,
    ) -> None:
        self.rows[source_ref] = {
            "source_ref": source_ref,
            "channel_id": channel_id,
            "attempts": attempts,
            "error_class": error_class,
            "error_message": error_message,
            "error_details": error_details,
        }

    async def list_failures(self, channel_id=None, limit=None) -> list[dict]:
        return [
            dict(v)
            for v in self.rows.values()
            if channel_id is None or v["channel_id"] == channel_id
        ]

    async def delete_failure(self, source_ref, *, commit: bool = True) -> None:
        self.rows.pop(source_ref, None)


class FlakyReadRepo(FakeFailureRepo):
    """Raises on selected ``list_failures`` calls (1-based call index)."""

    def __init__(self, fail_on_calls: set[int]) -> None:
        super().__init__()
        self.fail_on_calls = fail_on_calls
        self.read_calls = 0

    async def list_failures(self, channel_id=None, limit=None) -> list[dict]:
        self.read_calls += 1
        if self.read_calls in self.fail_on_calls:
            raise RuntimeError("simulated transient DB read failure")
        return await super().list_failures(channel_id=channel_id, limit=limit)


class FakeCardRepo:
    def __init__(self) -> None:
        self.cards: dict[str, TopicCard] = {}
        self.session = None

    async def upsert(self, card: TopicCard, *, commit: bool = True) -> None:
        self.cards[card.id] = card

    async def list_by_channel(self, channel_id) -> list[TopicCard]:
        return list(self.cards.values())

    async def get_by_id(self, topic_id):
        return self.cards.get(topic_id)

    async def delete_by_id(self, topic_id, *, commit: bool = True) -> int:
        return 1 if self.cards.pop(topic_id, None) else 0

    async def delete_by_channel(self, channel_id) -> int:
        n = len(self.cards)
        self.cards.clear()
        return n


class FakeBundleRepo:
    def __init__(self) -> None:
        self.bundles: dict[str, object] = {}
        self.session = None

    async def upsert(self, bundle, *, commit: bool = True) -> None:
        self.bundles[bundle.topic_id] = bundle

    async def list_by_channel(self, channel_id) -> list:
        return list(self.bundles.values())

    async def delete_by_topic_id(self, topic_id, *, commit: bool = True) -> int:
        return 1 if self.bundles.pop(topic_id, None) else 0

    async def delete_by_channel(self, channel_id) -> int:
        n = len(self.bundles)
        self.bundles.clear()
        return n


def _make_pipeline(
    *,
    card_repo: FakeCardRepo,
    bundle_repo: FakeBundleRepo,
    failure_repo,
    docs: list[ProcessedDocument],
    merge_side_effect=None,
    tokens_per_batch: int = 0,
) -> TopicizationPipelineImpl:
    """Real pipeline + fake repos + stubbed LLM-touching methods (BUG-076 style)."""
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=docs)

    pipe = TopicizationPipelineImpl(
        llm_client=AsyncMock(),
        processed_doc_repo=processed_repo,
        topic_card_repo=card_repo,
        topic_bundle_repo=bundle_repo,
        processing_failure_repo=failure_repo,
        model_id="test-model",
    )

    async def _fake_generate(batch, *args, **kwargs):
        if tokens_per_batch:
            pipe.total_input_tokens += tokens_per_batch
        return [{"anchor_ref": batch[0]["source_ref"]}]

    async def _fake_merge(all_batch_topics, candidates):
        if merge_side_effect is not None:
            raise merge_side_effect
        return all_batch_topics

    def _fake_build(raw_topic, channel_id, documents):
        return _mk_card(raw_topic["anchor_ref"])

    pipe._generate_topics_batch = _fake_generate  # type: ignore[method-assign]
    pipe._merge_topics = _fake_merge  # type: ignore[method-assign]
    pipe._build_topic_card = _fake_build  # type: ignore[method-assign]
    return pipe


@contextlib.contextmanager
def _hardened(
    *,
    enabled=True,
    chunk_batches=1,
    max_chunks=1,
    budget=0,
    limit=3,
    cooldown=3600,
):
    """Enable the full path + the BUG-077 F1 breaker tunables for the block."""
    from tg_parser.config import settings

    with contextlib.ExitStack() as stack:
        for name, val in (
            ("topicization_full_resume_enabled", enabled),
            ("topicization_full_chunk_batches", chunk_batches),
            ("topicization_full_max_chunks_per_invocation", max_chunks),
            ("topicization_full_run_token_budget", budget),
            ("topicization_full_resume_noprogress_limit", limit),
            ("topicization_full_resume_noprogress_cooldown_s", cooldown),
        ):
            stack.enter_context(patch.object(settings, name, val))
        yield


def _seed_checkpoint(fr: FakeFailureRepo, cp: FullRunCheckpoint) -> None:
    fr.rows[full_checkpoint_marker_ref(CH)] = {
        "source_ref": full_checkpoint_marker_ref(CH),
        "channel_id": CH,
        "attempts": cp.chunks_done,
        "error_class": FULL_CHECKPOINT_ERROR_CLASS,
        "error_message": "x",
        "error_details": cp.to_details(),
    }


def _parsed(fr: FakeFailureRepo) -> FullRunCheckpoint | None:
    return parse_checkpoint(fr.rows.get(full_checkpoint_marker_ref(CH)))


def _counter_value(metric, **labels) -> float:
    return metric.labels(**labels)._value.get()


# ===========================================================================
# F1 — noprogress_circuit_open predicate (shared by driver + pipeline gates)
# ===========================================================================


def test_circuit_closed_below_limit_and_when_disabled():
    cp = _mk_checkpoint([_ref(1)], consecutive_noprogress_resumes=2)
    with _hardened(limit=3):
        assert noprogress_circuit_open(cp) is False
    # limit=0 disables the breaker entirely — even a huge counter stays closed.
    cp.consecutive_noprogress_resumes = 99
    with _hardened(limit=0):
        assert noprogress_circuit_open(cp) is False


def test_circuit_hard_open_when_cooldown_zero():
    """cooldown_s=0 = hard-open: at/over the limit the breaker NEVER lets a
    probe through (manual intervention required)."""
    cp = _mk_checkpoint(
        [_ref(1)],
        consecutive_noprogress_resumes=3,
        last_noprogress_at=_ts(datetime.now(UTC) - timedelta(days=30)),
    )
    with _hardened(limit=3, cooldown=0):
        assert noprogress_circuit_open(cp) is True


def test_circuit_open_within_cooldown_then_one_probe_after_ttl():
    now = datetime.now(UTC)
    cp = _mk_checkpoint(
        [_ref(1)],
        consecutive_noprogress_resumes=3,
        last_noprogress_at=_ts(now - timedelta(seconds=10)),
    )
    with _hardened(limit=3, cooldown=3600):
        assert noprogress_circuit_open(cp, now=now) is True  # within TTL
        assert (
            noprogress_circuit_open(cp, now=now + timedelta(seconds=3601)) is False
        )  # TTL elapsed -> one probe allowed


def test_circuit_missing_or_bad_timestamp_never_strands_a_run():
    """A tripped counter with a missing / unparseable / future timestamp must
    NOT permanently strand the run — the probe is allowed."""
    now = datetime.now(UTC)
    with _hardened(limit=3, cooldown=3600):
        for bad_ts in (None, "", "not-a-timestamp", _ts(now + timedelta(hours=2))):
            cp = _mk_checkpoint(
                [_ref(1)],
                consecutive_noprogress_resumes=5,
                last_noprogress_at=bad_ts,
            )
            assert noprogress_circuit_open(cp, now=now) is False


# ===========================================================================
# F1 — resume driver: counter increment / reset / lock-skip-neutral / gate
# ===========================================================================


async def _drive(fr, *, rt_return=None, rt_side_effect=None):
    """Invoke the resume driver with injected fakes and a patched run_topicization."""
    from tg_parser.services.topicization_service import (
        run_full_topicization_resume_for_channel,
    )

    kwargs = {}
    if rt_side_effect is not None:
        kwargs["side_effect"] = rt_side_effect
    else:
        kwargs["return_value"] = rt_return or {
            "topics_count": 0,
            "skipped_locked": False,
        }
    with patch(
        "tg_parser.services.topicization_service.run_topicization",
        new_callable=AsyncMock,
        **kwargs,
    ) as rt:
        out = await run_full_topicization_resume_for_channel(
            channel_id=CH,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
            failure_repo=fr,
        )
    return out, rt


@pytest.mark.asyncio
async def test_driver_increments_counter_on_noprogress_resume():
    """A resume that ends with chunks_done UNCHANGED writes the F1 counter via
    the standalone failure-path checkpoint write, preserving chunks_done /
    attempts / the pinned plan (the atomic commit never ran by definition)."""
    fr = FakeFailureRepo()
    refs = [_ref(i) for i in range(1, 121)]
    _seed_checkpoint(fr, _mk_checkpoint(refs, chunks_done=1))

    with _hardened():
        out, rt = await _drive(fr)  # run_topicization mutates nothing -> stalled

    rt.assert_awaited_once()
    cp = _parsed(fr)
    assert cp.consecutive_noprogress_resumes == 1
    assert cp.last_noprogress_at is not None
    # Failure-path write preserved everything else.
    assert cp.chunks_done == 1
    assert cp.planned_refs == refs
    assert fr.rows[full_checkpoint_marker_ref(CH)]["attempts"] == 1
    # Driver summary exposes POST-invocation state (not the stale pre-read).
    assert out["resumed"] is True
    assert out["chunks_done"] == 1
    assert out["noprogress_count"] == 1

    # Second stalled tick -> 2 (monotone while stalled).
    with _hardened():
        out2, _ = await _drive(fr)
    assert _parsed(fr).consecutive_noprogress_resumes == 2
    assert out2["noprogress_count"] == 2


@pytest.mark.asyncio
async def test_driver_resets_stale_counter_when_resume_advances():
    """Progress (chunks_done advanced) closes the breaker: a stale non-zero
    counter surviving in the row is zeroed by the driver's repair write."""
    fr = FakeFailureRepo()
    refs = [_ref(i) for i in range(1, 121)]
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            refs,
            chunks_done=1,
            consecutive_noprogress_resumes=2,
            last_noprogress_at=_ts(datetime.now(UTC)),
        ),
    )

    async def _advancing(**kwargs):
        # Simulate a durable chunk commit that (unusually) carried the old
        # counter forward — the driver must repair it to 0.
        row = fr.rows[full_checkpoint_marker_ref(CH)]
        row["error_details"]["chunks_done"] = 2
        row["attempts"] = 2
        return {"topics_count": 1, "skipped_locked": False}

    with _hardened():
        out, _ = await _drive(fr, rt_side_effect=_advancing)

    cp = _parsed(fr)
    assert cp.chunks_done == 2
    assert cp.consecutive_noprogress_resumes == 0  # reset on advance
    assert cp.last_noprogress_at is None
    assert out["chunks_done"] == 2
    assert out["noprogress_count"] == 0


@pytest.mark.asyncio
async def test_driver_lock_skip_is_neutral_no_increment_no_reset():
    """A 0x70C1 lock-skip is benign contention: the counter neither increments
    (no false trip from a concurrent trigger) nor resets (no masking a stall)."""
    fr = FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            [_ref(1)],
            chunks_done=1,
            consecutive_noprogress_resumes=2,
            last_noprogress_at=_ts(datetime.now(UTC)),
        ),
    )

    with _hardened():
        out, _ = await _drive(fr, rt_return={"topics_count": 0, "skipped_locked": True})

    assert out["resumed"] is False
    assert out["skipped_reason"] == "locked"
    assert _parsed(fr).consecutive_noprogress_resumes == 2  # untouched


@pytest.mark.asyncio
async def test_driver_skips_at_zero_cost_while_circuit_open():
    """Breaker open -> the driver does NOT invoke run_topicization at all
    (0 token cost), emits the F1 skip metric, and reports the state."""
    from tg_parser.api.metrics import TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL

    fr = FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            [_ref(1)],
            chunks_done=1,
            consecutive_noprogress_resumes=3,
            last_noprogress_at=_ts(datetime.now(UTC)),
        ),
    )
    before = _counter_value(TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL, channel_id=CH)

    with _hardened(limit=3, cooldown=3600):
        out, rt = await _drive(fr)

    rt.assert_not_awaited()  # zero spend
    assert out["resumed"] is False
    assert out["skipped_reason"] == "noprogress_circuit_open"
    assert out["noprogress_count"] == 3
    after = _counter_value(TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL, channel_id=CH)
    assert after - before == 1
    # State untouched — the probe re-arm is the DRIVER's counter write, which
    # must not happen on a skipped tick.
    assert _parsed(fr).consecutive_noprogress_resumes == 3


@pytest.mark.asyncio
async def test_driver_allows_probe_after_cooldown_elapsed():
    """Once the cooldown TTL elapses, ONE probe resume runs; if it stalls again
    the counter increments (4) and the fresh timestamp re-arms the TTL."""
    fr = FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            [_ref(1)],
            chunks_done=1,
            consecutive_noprogress_resumes=3,
            last_noprogress_at=_ts(datetime.now(UTC) - timedelta(seconds=7200)),
        ),
    )

    with _hardened(limit=3, cooldown=3600):
        out, rt = await _drive(fr)

    rt.assert_awaited_once()  # probe ran
    cp = _parsed(fr)
    assert cp.consecutive_noprogress_resumes == 4  # failing probe re-arms
    # Fresh timestamp -> breaker open again for the next hour.
    with _hardened(limit=3, cooldown=3600):
        assert noprogress_circuit_open(cp) is True


@pytest.mark.asyncio
async def test_driver_exception_bookkeeps_counter_then_reraises():
    """An invocation that RAISES with no durable progress still increments the
    counter (the drip signature is 'spend then crash') and re-raises so the
    scheduler's existing logging is preserved."""
    fr = FakeFailureRepo()
    _seed_checkpoint(fr, _mk_checkpoint([_ref(1)], chunks_done=1))

    class _Boom(RuntimeError):
        pass

    with _hardened():
        with pytest.raises(_Boom):
            await _drive(fr, rt_side_effect=_Boom("mid-run crash"))

    assert _parsed(fr).consecutive_noprogress_resumes == 1


# ---------------------------------------------------------------------------
# Bugbot HIGH follow-up — F1 probe doubled via the escalation path
# ---------------------------------------------------------------------------
#
# The counter increment on a no-progress attempt used to live ONLY in the
# driver's post-invocation bookkeeping. The ``should_reescalate`` escalation
# branch (topicization_service.py, 0-card + new docs) ALSO drives a chunked
# attempt directly via its own ``run_topicization`` call, gated by the SAME
# ``noprogress_circuit_open`` predicate — but that call site never wrote the
# counter. Since the scheduler runs incremental topicization (containing the
# escalation branch) BEFORE the resume driver every tick, once the cooldown
# window opened for a probe, BOTH could independently fire a full chunked
# attempt in the SAME tick: the escalation branch's failed attempt left the
# checkpoint untouched, so the driver's own pre-invocation check still saw a
# closed breaker and fired a SECOND attempt — up to 2x generate+merge spend
# per probe window. Fixed by moving the counter write into the chunked
# pipeline itself (``TopicizationPipelineImpl._record_noprogress_resume``),
# the single choke point both callers funnel through, with the driver's own
# increment demoted to a fallback for the narrow "pipeline never even ran"
# case (idempotent — it no-ops when the pipeline already bumped the counter).


@pytest.mark.asyncio
async def test_escalation_and_driver_share_bookkeeping_only_one_probe_per_tick():
    """At the no-progress limit with the cooldown TTL elapsed (one probe
    allowed), BOTH the escalation branch (a direct ``pipeline.topicize_channel``
    call, mirroring ``should_reescalate``) and the resume driver are invocable
    in the SAME tick, against a chunk that will fail-without-advancing. Only
    ONE actual chunked attempt (one generate+merge spend) may occur: the
    escalation-triggered attempt's OWN failure-path write (inside the chunked
    pipeline) must close the breaker BEFORE the driver's pre-invocation check
    runs, so the driver's ``run_topicization`` is never even called."""
    from tg_parser.processing.llm.errors import AnthropicBillingError

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            sorted(_ref(i) for i in range(1, 121)),
            chunks_done=1,
            consecutive_noprogress_resumes=3,  # AT the limit
            last_noprogress_at=_ts(datetime.now(UTC) - timedelta(seconds=7200)),
        ),  # TTL elapsed -> exactly one probe allowed
    )

    escalation_pipe = _make_pipeline(
        card_repo=cr,
        bundle_repo=br,
        failure_repo=fr,
        docs=docs,
        merge_side_effect=AnthropicBillingError("credit balance too low"),
    )
    gen_calls = {"n": 0}
    orig_gen = escalation_pipe._generate_topics_batch

    async def _counting_gen(batch, *a, **kw):
        gen_calls["n"] += 1
        return await orig_gen(batch, *a, **kw)

    escalation_pipe._generate_topics_batch = _counting_gen  # type: ignore[method-assign]

    with _hardened(limit=3, cooldown=3600, max_chunks=1):
        # 1) Escalation branch fires FIRST (mirrors scheduler ordering:
        # incremental/escalation runs BEFORE the resume driver each tick).
        # force=False, resume=False -> the escalation-style entry.
        cards = await escalation_pipe.topicize_channel(channel_id=CH)

    assert cards == []
    assert gen_calls["n"] == 1  # exactly ONE probe attempt (one batch generated)
    cp_after_escalation = _parsed(fr)
    assert cp_after_escalation.consecutive_noprogress_resumes == 4  # bumped by the pipeline itself
    assert cp_after_escalation.last_noprogress_at is not None

    # 2) SAME tick: the resume driver ALSO fires. It must see the ALREADY
    # incremented + freshly-timestamped counter and skip WITHOUT invoking
    # run_topicization a second time (0 additional spend).
    with _hardened(limit=3, cooldown=3600):
        out, rt = await _drive(fr)

    rt.assert_not_awaited()  # NO second chunked attempt this tick
    assert out["resumed"] is False
    assert out["skipped_reason"] == "noprogress_circuit_open"
    # Counter untouched by the driver's skip -- still 4 (only ONE probe fired).
    assert _parsed(fr).consecutive_noprogress_resumes == 4


@pytest.mark.asyncio
async def test_driver_invoked_real_pipeline_failure_counted_once_not_twice():
    """When the DRIVER itself invokes a real failing pipeline (no separate
    escalation call this tick), the pipeline's own bookkeeping write is the
    ONLY increment — the driver's post-invocation logic must detect it
    already happened (post-read counter differs from its pre-read snapshot)
    and must NOT write its own increment on top (which would double-count a
    single failed attempt)."""
    from tg_parser.processing.llm.errors import AnthropicBillingError

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    _seed_checkpoint(fr, _mk_checkpoint(sorted(_ref(i) for i in range(1, 121)), chunks_done=1))

    async def _real_failing_run(**kwargs):
        pipe = _make_pipeline(
            card_repo=cr,
            bundle_repo=br,
            failure_repo=fr,
            docs=docs,
            merge_side_effect=AnthropicBillingError("credit balance too low"),
        )
        cards = await pipe.topicize_channel(channel_id=CH, resume=True)
        return {"topics_count": len(cards), "skipped_locked": False}

    with _hardened(max_chunks=1):
        out, rt = await _drive(fr, rt_side_effect=_real_failing_run)

    rt.assert_awaited_once()
    assert _parsed(fr).consecutive_noprogress_resumes == 1  # incremented exactly ONCE
    assert out["noprogress_count"] == 1


@pytest.mark.asyncio
async def test_finalize_only_failure_does_not_trip_chunk_generation_breaker():
    """Bugbot round-2 HIGH: ``chunks_done == chunks_total`` BOTH pre- AND
    post-invocation means NO chunk-generation was even attempted this call —
    ``_topicize_channel_chunked``'s per-chunk loop range
    (``range(chunks_done, chunks_total)``) is empty, so ``halted`` stays
    False and ``TopicizationPipelineImpl._record_noprogress_resume`` never
    runs. The only thing that can fail here is the token-FREE
    ``_finalize_full_run`` tail (pure Jaccard/cosine over persisted cards, NO
    LLM calls) — a completely different cost profile than a stalled
    chunk-generation resume. That must NOT trip the SAME F1
    chunk-generation breaker, or repeated free finalize failures would
    eventually stall an otherwise fully-chunked run for a whole cooldown
    window with zero token spend to justify it."""
    docs = [_make_doc(1)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    refs = sorted(d.source_ref for d in docs)
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            refs,
            chunk_batches=1,
            chunks_total=1,
            chunks_done=1,  # ALL chunks ALREADY durable pre-invocation
            batches_done=1,
            final_merge_done=False,  # finalize not yet committed
        ),
    )

    class _FinalizeBoom(RuntimeError):
        pass

    async def _real_run_then_finalize_boom(**kwargs):
        pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
        cards = await pipe.topicize_channel(channel_id=CH, resume=True)
        # Confirm the premise: the chunk loop was a genuine no-op (nothing
        # LEFT to generate), NOT a halt — the pipeline's own no-progress
        # bookkeeping must not have fired either.
        assert cards == []
        assert pipe.full_run_halted is False
        assert pipe.full_run_all_chunks_done is True
        # Simulates _finalize_full_run raising in the service-layer tail.
        raise _FinalizeBoom("finalize crashed")

    with _hardened():
        with pytest.raises(_FinalizeBoom):
            await _drive(fr, rt_side_effect=_real_run_then_finalize_boom)

    cp = _parsed(fr)
    assert cp is not None
    assert cp.consecutive_noprogress_resumes == 0  # NOT bumped by a finalize failure
    assert cp.last_noprogress_at is None
    assert cp.chunks_done == 1
    assert cp.chunks_total == 1
    assert cp.final_merge_done is False  # finalize never committed


@pytest.mark.asyncio
async def test_repeated_finalize_failures_never_open_chunk_breaker():
    """Repeated finalize-only failures across many ticks must never open the
    F1 chunk-generation circuit — there is no chunk-generation spend here to
    bound, so the counter must stay at 0 no matter how many times finalize
    fails."""
    docs = [_make_doc(1)]

    class _FinalizeBoom(RuntimeError):
        pass

    for _tick in range(5):
        cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
        refs = sorted(d.source_ref for d in docs)
        _seed_checkpoint(
            fr,
            _mk_checkpoint(
                refs,
                chunk_batches=1,
                chunks_total=1,
                chunks_done=1,
                batches_done=1,
                final_merge_done=False,
            ),
        )

        async def _real_run_then_finalize_boom(*, _cr=cr, _br=br, _fr=fr, **kwargs):
            pipe = _make_pipeline(card_repo=_cr, bundle_repo=_br, failure_repo=_fr, docs=docs)
            await pipe.topicize_channel(channel_id=CH, resume=True)
            raise _FinalizeBoom("finalize crashed again")

        with _hardened(limit=3):
            assert noprogress_circuit_open(_parsed(fr)) is False  # never trips
            with pytest.raises(_FinalizeBoom):
                await _drive(fr, rt_side_effect=_real_run_then_finalize_boom)

        assert _parsed(fr).consecutive_noprogress_resumes == 0


@pytest.mark.asyncio
async def test_pipeline_checkpoint_read_abort_does_not_trip_chunk_breaker():
    """Bugbot round-3 MEDIUM: the CHUNKED PIPELINE's own internal F3
    checkpoint-read-error abort (a transient read blip DURING the invocation
    — distinct from the driver's own Phase-A pre-read, which succeeds here)
    is a ZERO-cost, ZERO-chunks-attempted no-op: ``run_topicization``
    completes NORMALLY (no exception, ``topics_count=0``) with the
    checkpoint UNCHANGED. Without the ``checkpoint_read_aborted`` signal the
    driver cannot tell this apart from a genuine (costly) chunk-generation
    no-progress stall — it must NOT increment the F1 breaker for a read
    hiccup that spent zero tokens and touched zero chunks."""
    docs = [_make_doc(i) for i in range(1, 121)]
    refs = sorted(d.source_ref for d in docs)
    # Call 1 = the driver's OWN Phase-A pre-read (succeeds). Call 2 = the
    # PIPELINE's internal ``_read_full_checkpoint`` during the invocation
    # (fails — the F3 abort this test targets). Call 3 = the driver's
    # Phase-C post-invocation re-read (succeeds again — transient, not
    # persistent).
    flaky = FlakyReadRepo(fail_on_calls={2})
    _seed_checkpoint(flaky, _mk_checkpoint(refs, chunks_done=1))

    async def _real_run_hits_pipeline_f3_abort(**kwargs):
        pipe = _make_pipeline(
            card_repo=FakeCardRepo(),
            bundle_repo=FakeBundleRepo(),
            failure_repo=flaky,
            docs=docs,
        )
        cards = await pipe.topicize_channel(channel_id=CH, resume=True)
        # Confirm the premise: this really is the F3 internal abort (0 LLM
        # calls, 0 chunks touched), NOT a chunk-generation halt.
        assert cards == []
        assert pipe.full_run_halted is True
        assert pipe.full_run_checkpoint_read_aborted is True
        return {
            "topics_count": 0,
            "skipped_locked": False,
            "checkpoint_read_aborted": pipe.full_run_checkpoint_read_aborted,
        }

    with _hardened():
        out, rt = await _drive(flaky, rt_side_effect=_real_run_hits_pipeline_f3_abort)

    rt.assert_awaited_once()
    cp = _parsed(flaky)
    assert cp.consecutive_noprogress_resumes == 0  # NOT bumped by a read hiccup
    assert cp.last_noprogress_at is None
    assert cp.chunks_done == 1  # untouched
    assert out["noprogress_count"] == 0


# ===========================================================================
# F3 — driver: read error is a benign abort; unreadable post-state is neutral
# ===========================================================================


@pytest.mark.asyncio
async def test_driver_pre_read_error_is_benign_skip():
    """A transient marker READ error must NOT fall through to 'no checkpoint'
    (which would skip a live run) nor to a resume — benign 0-cost skip."""
    fr = FlakyReadRepo(fail_on_calls={1})

    with _hardened():
        out, rt = await _drive(fr)

    rt.assert_not_awaited()
    assert out == {"resumed": False, "skipped_reason": "checkpoint_read_error"}


@pytest.mark.asyncio
async def test_driver_post_read_error_does_not_increment_counter():
    """UNKNOWN post-state (post-invocation re-read failed) must not falsely
    trip the breaker — no counter write this tick."""
    fr = FlakyReadRepo(fail_on_calls={2})  # pre-read OK, post-read raises
    _seed_checkpoint(fr, _mk_checkpoint([_ref(1)], chunks_done=1))

    with _hardened():
        out, rt = await _drive(fr)

    rt.assert_awaited_once()
    assert out["resumed"] is True
    assert _parsed(fr).consecutive_noprogress_resumes == 0  # no write


# ===========================================================================
# F1 — pipeline-side gate (covers the 0-card should_reescalate escalation path)
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_breaker_gates_escalation_entry_at_zero_cost():
    """The escalation path enters run_topicization WITHOUT the driver gate (the
    BUG-071 cooldown is deliberately not armed while a checkpoint is live), so
    the pipeline re-checks the SAME predicate: open breaker -> 0 LLM calls,
    checkpoint untouched, skip metric emitted, benign halt."""
    from tg_parser.api.metrics import TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            sorted(_ref(i) for i in range(1, 121)),
            chunks_done=1,
            consecutive_noprogress_resumes=3,
            last_noprogress_at=_ts(datetime.now(UTC)),
        ),
    )
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    gen_calls = {"n": 0}
    orig_gen = pipe._generate_topics_batch

    async def _counting_gen(batch, *a, **kw):
        gen_calls["n"] += 1
        return await orig_gen(batch, *a, **kw)

    pipe._generate_topics_batch = _counting_gen  # type: ignore[method-assign]
    before = _counter_value(TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL, channel_id=CH)

    with _hardened(limit=3, cooldown=3600, max_chunks=10):
        # Escalation-style entry: force=False, resume=False.
        cards = await pipe.topicize_channel(channel_id=CH)

    assert cards == []
    assert gen_calls["n"] == 0  # ZERO LLM spend
    assert pipe.full_run_halted is True
    after = _counter_value(TOPICIZATION_FULL_RUN_NOPROGRESS_SKIP_TOTAL, channel_id=CH)
    assert after - before == 1
    # Checkpoint untouched (still 1/3, counter still 3).
    cp = _parsed(fr)
    assert cp.chunks_done == 1
    assert cp.consecutive_noprogress_resumes == 3


@pytest.mark.asyncio
async def test_pipeline_breaker_closed_lets_escalation_advance():
    """Counter below the limit -> the same entry advances a chunk normally
    (no false trip)."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            sorted(_ref(i) for i in range(1, 121)),
            chunks_done=1,
            consecutive_noprogress_resumes=2,
            last_noprogress_at=_ts(datetime.now(UTC)),
        ),
    )
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(limit=3, cooldown=3600):
        cards = await pipe.topicize_channel(channel_id=CH)

    assert len(cards) == 1  # chunk 1 committed
    cp = _parsed(fr)
    assert cp.chunks_done == 2
    # The atomic commit wrote a FRESH checkpoint -> counter implicitly reset.
    assert cp.consecutive_noprogress_resumes == 0


# ===========================================================================
# F2 — malformed merge reply is a clean resumable halt (real _merge_topics)
# ===========================================================================


@pytest.mark.asyncio
async def test_malformed_merge_reply_is_clean_resumable_halt():
    """A merge reply with STRING group ids crashes the ``0 <= mid`` comparison
    with TypeError. E2E through the REAL _merge_topics: the chunk is NOT
    committed, a merge failed-batch + the malformed_merge chunk-failure metric
    are recorded, and NO exception propagates (the resume driver would have
    re-driven the bare crash every tick)."""
    from tg_parser.api.metrics import TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    # Restore the REAL merge; feed it a malformed LLM reply.
    pipe._merge_topics = TopicizationPipelineImpl._merge_topics.__get__(pipe)  # type: ignore[method-assign]
    reply = MagicMock()
    reply.text = '{"groups": [["a", "b"]]}'  # string ids -> TypeError in id loop
    reply.input_tokens = 5
    reply.output_tokens = 5
    reply.stop_reason = "stop"
    pipe.llm_client.generate_with_usage = AsyncMock(return_value=reply)
    before = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL, channel_id=CH, reason="malformed_merge"
    )

    with _hardened(max_chunks=1):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    assert cards == []
    assert pipe.full_run_halted is True
    assert pipe.failed_batches >= 1
    assert len(cr.cards) == 0
    assert full_checkpoint_marker_ref(CH) not in fr.rows  # chunk NOT committed
    after = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL, channel_id=CH, reason="malformed_merge"
    )
    assert after - before == 1


# ===========================================================================
# F3 — pipeline: read error aborts (never a fresh run); vanished resume = no-op
# ===========================================================================


@pytest.mark.asyncio
async def test_checkpoint_read_error_aborts_invocation_not_fresh_start():
    """A transient checkpoint read failure must abort at 0 token cost — NOT
    fall through to a fresh pinned chunk-0 run (re-burn + the real checkpoint
    overwritten + duplicate LLM-derived-id cards)."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br = FakeCardRepo(), FakeBundleRepo()
    fr = FlakyReadRepo(fail_on_calls={1})
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(max_chunks=10):
        cards = await pipe.topicize_channel(channel_id=CH)  # escalation entry

    assert cards == []
    assert pipe.full_run_halted is True
    assert len(cr.cards) == 0  # NO fresh run
    assert full_checkpoint_marker_ref(CH) not in fr.rows  # nothing overwritten


@pytest.mark.asyncio
async def test_resume_with_vanished_checkpoint_is_noop_not_fresh_run():
    """Read/clear race: the driver saw a live checkpoint, but it was cleared
    before this invocation acquired 0x70C1. resume=True + no checkpoint must
    be a NO-OP — starting a fresh pinned run would re-burn the whole corpus."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()  # no row
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(max_chunks=10):
        cards = await pipe.topicize_channel(channel_id=CH, resume=True)

    assert cards == []
    assert len(cr.cards) == 0
    assert full_checkpoint_marker_ref(CH) not in fr.rows  # no fresh pin


@pytest.mark.asyncio
async def test_force_run_still_starts_fresh_despite_vanished_guard():
    """Regression guard: force=True legitimately starts fresh even when no
    checkpoint exists (the vanished-resume no-op must not block forced runs)."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(max_chunks=1):
        cards = await pipe.topicize_channel(channel_id=CH, force=True, resume=True)

    assert len(cards) == 1
    assert _parsed(fr).chunks_done == 1


# ===========================================================================
# F9 — chunk-failure metric + pre-commit token visibility + commit-failed halt
# ===========================================================================


@pytest.mark.asyncio
async def test_merge_halt_emits_chunk_failed_metric_and_precommit_tokens():
    """A billing merge halt (already clean in BUG-076) now ALSO emits the
    chunk_failed counter (reason=merge_halt) and the chunk's PRE-commit token
    spend — the F1 drip signature made alertable."""
    from tg_parser.api.metrics import (
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL,
        TOPICIZATION_FULL_RUN_TOKENS_TOTAL,
    )
    from tg_parser.processing.llm.errors import AnthropicBillingError

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(
        card_repo=cr,
        bundle_repo=br,
        failure_repo=fr,
        docs=docs,
        merge_side_effect=AnthropicBillingError("credit balance too low"),
        tokens_per_batch=10,
    )
    failed_before = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL, channel_id=CH, reason="merge_halt"
    )
    tokens_before = _counter_value(TOPICIZATION_FULL_RUN_TOKENS_TOTAL, channel_id=CH)

    with _hardened(max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, force=True)

    failed_after = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL, channel_id=CH, reason="merge_halt"
    )
    tokens_after = _counter_value(TOPICIZATION_FULL_RUN_TOKENS_TOTAL, channel_id=CH)
    assert failed_after - failed_before == 1
    # The failed chunk's 10 generate tokens are now visible pre-commit.
    assert tokens_after - tokens_before == 10


@pytest.mark.asyncio
async def test_empty_after_failure_emits_chunk_failed_metric():
    from tg_parser.api.metrics import TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    async def _raising_gen(batch, *args, **kwargs):
        raise RuntimeError("transient generate failure")

    pipe._generate_topics_batch = _raising_gen  # type: ignore[method-assign]
    before = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL,
        channel_id=CH,
        reason="empty_after_failure",
    )

    with _hardened(max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, force=True)

    after = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL,
        channel_id=CH,
        reason="empty_after_failure",
    )
    assert after - before == 1


@pytest.mark.asyncio
async def test_commit_failure_is_clean_counted_halt_not_a_crash():
    """An in-process atomic-commit failure (e.g. a card violating a DB
    constraint) must be a CLEAN resumable halt — counted (reason=commit_failed,
    failed-batch) with NO checkpoint advance, NO record_topic_created for the
    rolled-back cards, and NO exception propagating (else the resume driver
    re-drives the bare crash every tick)."""
    from tg_parser.api.metrics import TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    async def _failing_commit(**kwargs):
        raise RuntimeError("simulated constraint violation at commit")

    pipe._commit_chunk_atomically = _failing_commit  # type: ignore[method-assign]
    before = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL, channel_id=CH, reason="commit_failed"
    )

    with patch("tg_parser.api.metrics.record_topic_created") as rec, _hardened(max_chunks=10):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    assert cards == []  # nothing durable this invocation
    assert pipe.full_run_halted is True
    assert pipe.failed_batches >= 1
    assert full_checkpoint_marker_ref(CH) not in fr.rows  # NOT advanced
    rec.assert_not_called()  # rolled-back cards never counted as created
    after = _counter_value(
        TOPICIZATION_FULL_RUN_CHUNK_FAILED_TOTAL, channel_id=CH, reason="commit_failed"
    )
    assert after - before == 1


# ===========================================================================
# F5 — run_id card stamping + scoped stale wipe (with pre-fix broad fallback)
# ===========================================================================


@pytest.mark.asyncio
async def test_chunked_cards_are_stamped_with_checkpoint_run_id():
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, force=True)

    cp = _parsed(fr)
    assert cp.cards_stamped is True  # fresh runs start under the F5 code
    assert cp.run_id.startswith("fullrun_")
    assert len(cr.cards) == 1
    for card in cr.cards.values():
        assert (card.metadata or {}).get("topicization_run_id") == cp.run_id


@pytest.mark.asyncio
async def test_stale_wipe_scoped_to_prior_runs_stamped_cards():
    """A stale restart of a POST-fix run (cards_stamped=True) deletes ONLY the
    cards stamped with the prior run_id — incremental/discover cards created by
    the BUG-075 reconcile path on the same channel SURVIVE."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    prior_full = _mk_card(_ref(9999))
    prior_full.metadata = {"topicization_run_id": "fullrun_old"}
    incremental = _mk_card(_ref(8888))
    incremental.metadata = {"topicization_run_id": "run_20260101_000000"}
    for c in (prior_full, incremental):
        cr.cards[c.id] = c
        br.bundles[c.id] = MagicMock(topic_id=c.id, items=[])

    # Pinned plan references a ref missing from the live corpus -> stale restart.
    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            [_ref(88888), *(_ref(i) for i in range(1, 120))],
            run_id="fullrun_old",
            chunks_done=2,
            cards_stamped=True,
        ),
    )
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, resume=True)

    # Prior full-run card wiped; foreign (incremental) card + bundle survive.
    assert prior_full.id not in cr.cards
    assert prior_full.id not in br.bundles
    assert incremental.id in cr.cards
    assert incremental.id in br.bundles
    # Fresh chunk-0 pass re-pinned and committed one card.
    cp = _parsed(fr)
    assert cp.chunks_done == 1
    assert cp.planned_doc_count == 120
    assert _mk_card(_ref(1)).id in cr.cards


@pytest.mark.asyncio
async def test_prefix_checkpoint_falls_back_to_broad_wipe():
    """A checkpoint written BEFORE the F5 stamp (cards_stamped=False — its
    cards carry unmatchable per-card run_<now> ids) must fall back to the broad
    delete_by_channel so the duplicate-card problem the wipe prevents cannot
    return."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    unstamped = _mk_card(_ref(9999))  # pre-fix card: no matching stamp
    other = _mk_card(_ref(8888))
    other.metadata = {"topicization_run_id": "run_20260101_000000"}
    for c in (unstamped, other):
        cr.cards[c.id] = c
        br.bundles[c.id] = MagicMock(topic_id=c.id, items=[])

    _seed_checkpoint(
        fr,
        _mk_checkpoint(
            [_ref(88888), *(_ref(i) for i in range(1, 120))],
            run_id="fullrun_old",
            chunks_done=2,
            cards_stamped=False,  # pre-fix run
        ),
    )
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _hardened(max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, resume=True)

    # Broad wipe: BOTH prior cards gone; only the fresh chunk-0 card remains.
    assert unstamped.id not in cr.cards
    assert other.id not in cr.cards
    assert len(cr.cards) == 1
    assert _mk_card(_ref(1)).id in cr.cards


# ===========================================================================
# F7 — successful legacy monolithic run clears a leftover checkpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_legacy_success_clears_leftover_full_checkpoint():
    """Flag OFF (legacy path): a completed monolithic run (>=1 card) clears a
    leftover checkpoint row so a future flag re-enable cannot resume a stale
    plan on top of the fresh legacy result."""
    docs = [_make_doc(1)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    _seed_checkpoint(fr, _mk_checkpoint([_ref(77777)], run_id="leftover"))
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    # No _hardened(): topicization_full_resume_enabled stays False (dark).
    cards = await pipe.topicize_channel(channel_id=CH)

    assert len(cards) == 1  # legacy run succeeded
    assert full_checkpoint_marker_ref(CH) not in fr.rows  # marker cleared


@pytest.mark.asyncio
async def test_legacy_zero_card_run_leaves_checkpoint_for_future_resume():
    """A 0-card legacy run did NOT supersede the prior partial progress — the
    leftover checkpoint stays for a future enabled resume."""
    docs = [_make_doc(1)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    _seed_checkpoint(fr, _mk_checkpoint([_ref(77777)], run_id="leftover"))
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    async def _empty_gen(batch, *args, **kwargs):
        return []

    pipe._generate_topics_batch = _empty_gen  # type: ignore[method-assign]

    cards = await pipe.topicize_channel(channel_id=CH)

    assert cards == []
    assert full_checkpoint_marker_ref(CH) in fr.rows  # preserved


# ===========================================================================
# F4 — reconcile hook defers (never abandons) while a full run is live
# ===========================================================================


@pytest.mark.asyncio
async def test_reconcile_deferred_while_full_run_live():
    """Flag ON + live checkpoint: reconcile hard-skips BEFORE any candidate
    selection or LLM feed (0 spend), reporting a retryable deferral."""
    import tg_parser.services.topicization_service as svc

    fr = FakeFailureRepo()
    _seed_checkpoint(fr, _mk_checkpoint([_ref(1)], chunks_done=1))
    processed_repo = AsyncMock()

    with (
        _hardened(),
        patch.object(svc, "run_incremental_topicization", new_callable=AsyncMock) as ri,
    ):
        out = await svc.run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=FakeCardRepo(),
            topic_bundle_repo=FakeBundleRepo(),
            failure_repo=fr,
        )

    assert out["skipped_reason"] == "full_run_in_progress"
    assert out["deferred"] is True  # DEFER semantics — retried next tick
    assert out["fed"] == 0
    ri.assert_not_awaited()  # zero LLM spend
    processed_repo.list_by_channel.assert_not_awaited()  # gate fires first


@pytest.mark.asyncio
async def test_reconcile_gate_releases_after_checkpoint_clears():
    """No live checkpoint -> the gate releases and the normal reconcile path
    proceeds (no permanent abandonment — the deferral is not sticky)."""
    import tg_parser.services.topicization_service as svc

    fr = FakeFailureRepo()  # checkpoint cleared (run completed)
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=[])

    with _hardened(), patch.object(svc, "run_incremental_topicization", new_callable=AsyncMock):
        out = await svc.run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=FakeCardRepo(),
            topic_bundle_repo=FakeBundleRepo(),
            failure_repo=fr,
        )

    # Past the gate: the corpus was consulted (empty here -> benign no_docs).
    assert out["skipped_reason"] == "no_docs"
    processed_repo.list_by_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_completed_checkpoint_not_live_no_defer():
    """A present-but-COMPLETE checkpoint (awaiting clear) is NOT live — the
    reconcile gate must not defer on it."""
    import tg_parser.services.topicization_service as svc

    fr = FakeFailureRepo()
    _seed_checkpoint(
        fr,
        _mk_checkpoint([_ref(1)], chunks_total=3, chunks_done=3, final_merge_done=True),
    )
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=[])

    with _hardened(), patch.object(svc, "run_incremental_topicization", new_callable=AsyncMock):
        out = await svc.run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=FakeCardRepo(),
            topic_bundle_repo=FakeBundleRepo(),
            failure_repo=fr,
        )

    assert out["skipped_reason"] == "no_docs"  # gate released


@pytest.mark.asyncio
async def test_reconcile_gate_dark_when_flag_disabled():
    """Flag OFF + leftover live-looking checkpoint: the F4 gate is inert
    (dark-by-default) — legacy reconcile behavior is bit-for-bit preserved."""
    import tg_parser.services.topicization_service as svc

    fr = FakeFailureRepo()
    _seed_checkpoint(fr, _mk_checkpoint([_ref(1)], chunks_done=1))  # leftover
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=[])

    # No _hardened(): topicization_full_resume_enabled stays False.
    with patch.object(svc, "run_incremental_topicization", new_callable=AsyncMock):
        out = await svc.run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=FakeCardRepo(),
            topic_bundle_repo=FakeBundleRepo(),
            failure_repo=fr,
        )

    assert out["skipped_reason"] == "no_docs"  # proceeded past the (dark) gate
    processed_repo.list_by_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_defers_closed_on_checkpoint_read_error():
    """Bugbot round-3 HIGH: a checkpoint-READ error during the F4 gate must
    fail CLOSED (defer this tick) — NOT open. Proceeding with Phase-2
    discover on a tick where liveness genuinely could not be determined is
    the EXACT double-spend F4 exists to prevent, just triggered by a
    transient read failure instead of the normal live-checkpoint case."""
    import tg_parser.services.topicization_service as svc

    flaky = FlakyReadRepo(fail_on_calls={1})  # the gate's OWN liveness read
    processed_repo = AsyncMock()

    with (
        _hardened(),
        patch.object(svc, "run_incremental_topicization", new_callable=AsyncMock) as ri,
    ):
        out = await svc.run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=FakeCardRepo(),
            topic_bundle_repo=FakeBundleRepo(),
            failure_repo=flaky,
        )

    assert out["skipped_reason"] == "full_run_in_progress"
    assert out["deferred"] is True
    ri.assert_not_awaited()  # zero LLM spend — the fail-closed defer
    processed_repo.list_by_channel.assert_not_awaited()  # gate fires first

    # NOT sticky / not abandonment: a SUBSEQUENT tick with a working read (no
    # live checkpoint — the transient blip already passed) proceeds normally.
    processed_repo.list_by_channel = AsyncMock(return_value=[])
    with _hardened(), patch.object(svc, "run_incremental_topicization", new_callable=AsyncMock):
        out2 = await svc.run_reconciliation_for_channel(
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=FakeCardRepo(),
            topic_bundle_repo=FakeBundleRepo(),
            failure_repo=flaky,
        )
    assert out2["skipped_reason"] == "no_docs"  # gate released — not abandoned
    processed_repo.list_by_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_has_live_full_checkpoint_still_fails_open_on_read_error():
    """The BUG-071 cooldown-arming wrapper's fail-OPEN policy is UNCHANGED by
    the F4 fail-closed refactor: a read error still resolves to ``False``
    ("not live") for the cooldown-arming call sites, exactly as before —
    only the NEW reconcile-gate call site gets the opposite (fail-closed)
    policy."""
    import tg_parser.services.topicization_service as svc

    flaky = FlakyReadRepo(fail_on_calls={1})
    with _hardened():
        assert await svc._has_live_full_checkpoint(flaky, CH) is False


@pytest.mark.asyncio
async def test_read_full_checkpoint_liveness_raises_on_read_error():
    """The raising core used by the fail-CLOSED reconcile-gate caller
    propagates a checkpoint-read failure as ``FullCheckpointReadError``
    rather than swallowing it — callers choose their own fail-open vs
    fail-closed policy on top of this."""
    import tg_parser.services.topicization_service as svc
    from tg_parser.processing.topicization_checkpoint import FullCheckpointReadError

    flaky = FlakyReadRepo(fail_on_calls={1})
    with _hardened(), pytest.raises(FullCheckpointReadError):
        await svc._read_full_checkpoint_liveness(flaky, CH)
