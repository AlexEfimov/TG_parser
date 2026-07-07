"""BUG-076: crash-safe / resumable / budget-aware FULL topicization.

The legacy full path (``TopicizationPipelineImpl.topicize_channel``) was a
monolithic all-or-nothing run: it generated EVERY batch, did ONE global merge,
built ALL cards, and persisted them in ONE final loop. A crash / billing halt /
timeout anywhere before that final persist threw away the whole run's LLM spend
AND advanced nothing, so a large cold-start channel could burn tokens forever
without ever persisting a card (and ``TopicizationBurnNoProgress`` could not see
progress because ``record_topic_created`` only fired in the service wrapper).

BUG-076 makes the full path (behind ``topicization_full_resume_enabled``):

* **chunked** — corpus partitioned into ``topicization_full_chunk_batches``
  50-doc batches per chunk;
* **atomic per chunk** — (card upserts + bundle upserts + checkpoint advance) in
  ONE transaction, so a partial chunk becomes "chunk not started" (no duplicate
  LLM-derived-id cards on resume);
* **resumable** — a synthetic ``processing_failures`` checkpoint row + a standing
  scheduler resume driver (``_process_source``) drive the run to completion over
  ticks;
* **budget-aware** — a per-invocation token budget halts cleanly at a chunk
  boundary (benign partial/resumable result, NOT a failed-batch storm);
* **consolidated** — an idempotent cross-chunk merge dedups near-duplicate cards
  after all chunks land, recorded via ``final_merge_done``;
* **observable** — ``record_topic_created`` fires per chunk (wrapper emit
  removed so no double-count) + four new full-run metrics.

These tests are mostly mock-driven (no Postgres) plus one PG-gated atomicity /
no-duplicate-cards integration test (the HIGHEST-risk pillar).
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
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
    FULL_CHECKPOINT_PREFIX,
    FullRunCheckpoint,
    full_checkpoint_marker_ref,
    parse_checkpoint,
    planned_ref_hash,
    planned_refs_from_documents,
)

# Base timestamp for planned docs. Round-3 pins the plan by REF-membership (not a
# processed_at watermark), so "appended" docs sharing the EXACT run-start
# timestamp (_SAME_TS) must still be excluded by ref — the tie flaw round-3 fixes.
_BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)
_SAME_TS = _BASE_TS  # equal-timestamp (same-second) append
_LATER_TS = datetime(2026, 1, 2, tzinfo=UTC)


def _mk_checkpoint(refs: list[str], **overrides) -> FullRunCheckpoint:
    """Build a FullRunCheckpoint pinned to ``refs`` with sensible test defaults."""
    base = {
        "run_id": "r",
        "planned_refs": list(refs),
        "planned_ref_hash": planned_ref_hash(refs),
        "planned_doc_count": len(refs),
        "chunk_batches": 1,
        "chunks_total": 1,
        "chunks_done": 0,
        "batches_done": 0,
        "tokens_spent_cumulative": 1,
        "final_merge_done": False,
    }
    base.update(overrides)
    return FullRunCheckpoint(**base)


pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

CH = "labdiagnostica"


def _ref(n: int) -> str:
    return f"tg:{CH}:post:{n}"


def _make_doc(n: int, processed_at: datetime | None = None) -> ProcessedDocument:
    ref = _ref(n)
    return ProcessedDocument(
        id=f"doc:{ref}",
        source_ref=ref,
        source_message_id=str(n),
        channel_id=CH,
        processed_at=processed_at or _BASE_TS,
        text_clean=f"clean text body number {n}",
        summary=f"summary {n}",
        topics=[],
    )


def _mk_card(ref: str) -> TopicCard:
    """A minimal valid TopicCard anchored at ``ref`` (id = topic:<ref>)."""
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


class FakeFailureRepo:
    """In-memory ProcessingFailureRepo (survives across pipeline invocations)."""

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
    failure_repo: FakeFailureRepo,
    docs: list[ProcessedDocument],
    merge_side_effect=None,
    tokens_per_batch: int = 0,
) -> TopicizationPipelineImpl:
    """Build a real pipeline with fake repos and stubbed LLM-touching methods.

    ``_generate_topics_batch`` returns exactly ONE raw topic per batch anchored
    at the batch's first doc (so N batches -> N deterministic cards), optionally
    adding ``tokens_per_batch`` input tokens. ``_merge_topics`` is identity
    (unless ``merge_side_effect`` raises). ``_build_topic_card`` maps a raw topic
    to a minimal valid card.
    """
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=docs)

    pipe = TopicizationPipelineImpl(
        llm_client=AsyncMock(),
        processed_doc_repo=processed_repo,
        topic_card_repo=card_repo,
        topic_bundle_repo=bundle_repo,
        processing_failure_repo=failure_repo,
        # BUG-076 round-2 Finding 4: a real Postgres bundle repo does
        # ``stable_json_dumps(bundle.metadata)`` including ``model_id``; leaving
        # it an AsyncMock raises "AsyncMock is not JSON serializable" at chunk-0's
        # bundle upsert (before the PG atomicity test can even fire its crash).
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


# ===========================================================================
# Checkpoint module: collision-safety, (de)serialization, fingerprint
# ===========================================================================


def test_checkpoint_marker_ref_namespaced_and_collision_safe():
    ref = full_checkpoint_marker_ref(CH)
    assert ref == f"topicization:full_checkpoint:{CH}"
    # Never a real doc ref, nor the BUG-071 / BUG-075 markers.
    assert not ref.startswith("tg:")
    assert not ref.startswith("topicization:reescalation:")
    assert not ref.startswith("topicization:discover_attempted:")
    assert ref.startswith(FULL_CHECKPOINT_PREFIX)


def test_checkpoint_roundtrip_and_is_complete():
    refs = [_ref(i) for i in range(1, 121)]
    cp = FullRunCheckpoint(
        run_id="fullrun_x",
        planned_refs=refs,
        planned_ref_hash=planned_ref_hash(refs),
        planned_doc_count=120,
        chunk_batches=2,
        chunks_total=3,
        chunks_done=2,
        batches_done=40,
        tokens_spent_cumulative=1234,
        final_merge_done=False,
    )
    assert cp.is_complete is False
    row = {
        "source_ref": full_checkpoint_marker_ref(CH),
        "channel_id": CH,
        "attempts": 2,
        "error_class": FULL_CHECKPOINT_ERROR_CLASS,
        "error_message": "x",
        "error_details": cp.to_details(),
    }
    parsed = parse_checkpoint(row)
    assert parsed is not None
    assert parsed.run_id == "fullrun_x"
    assert parsed.planned_refs == refs
    assert parsed.planned_ref_hash == planned_ref_hash(refs)
    assert parsed.planned_doc_count == 120
    assert parsed.chunk_batches == 2
    assert parsed.chunks_total == 3
    assert parsed.chunks_done == 2
    assert parsed.batches_done == 40
    assert parsed.tokens_spent_cumulative == 1234
    assert parsed.final_merge_done is False

    cp.chunks_done = 3
    cp.final_merge_done = True
    assert cp.is_complete is True


def test_parse_checkpoint_degrades_gracefully():
    assert parse_checkpoint(None) is None
    assert parse_checkpoint({}) is None
    # Malformed details -> None, not a crash.
    assert parse_checkpoint({"source_ref": "x", "error_details": "not a dict"}) is None
    # attempts fallback when chunks_done absent from details.
    parsed = parse_checkpoint({"attempts": 5, "error_details": {"run_id": "r"}})
    assert parsed is not None
    assert parsed.chunks_done == 5


def test_planned_refs_deterministic_and_tie_proof():
    """Round-3 F1: the planned ref list is a deterministic, order-independent,
    tie-proof sort by source_ref (unique PK) — NOT dependent on processed_at."""
    docs = [_make_doc(i) for i in range(1, 4)]
    refs1 = planned_refs_from_documents(docs)
    refs2 = planned_refs_from_documents(list(reversed(docs)))
    assert refs1 == refs2 == sorted(_ref(i) for i in range(1, 4))
    assert planned_refs_from_documents([]) == []
    # Same-second (tied) processed_at does NOT change the plan/order.
    tied = [_make_doc(i, processed_at=_SAME_TS) for i in range(1, 4)]
    assert planned_refs_from_documents(tied) == refs1
    # Hash is stable + order-sensitive.
    assert planned_ref_hash(refs1) == planned_ref_hash(refs2)
    assert planned_ref_hash(refs1) != planned_ref_hash(list(reversed(refs1)))


# ===========================================================================
# Chunked full run: per-chunk atomic commit, resume, budget, merge-halt
# ===========================================================================


@contextlib.contextmanager
def _enable_full(chunk_batches=1, max_chunks=1, budget=0, merge_threshold=0.6):
    """Enable the resumable full path with the given tunables for the block."""
    from tg_parser.config import settings

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(settings, "topicization_full_resume_enabled", True))
        stack.enter_context(
            patch.object(settings, "topicization_full_chunk_batches", chunk_batches)
        )
        stack.enter_context(
            patch.object(settings, "topicization_full_max_chunks_per_invocation", max_chunks)
        )
        stack.enter_context(patch.object(settings, "topicization_full_run_token_budget", budget))
        stack.enter_context(
            patch.object(settings, "topicization_full_merge_threshold", merge_threshold)
        )
        yield


@pytest.mark.asyncio
async def test_chunked_run_bounded_by_max_chunks_per_invocation():
    """One invocation with max_chunks=1 advances exactly ONE chunk and persists
    a durable checkpoint (chunks_done=1) — the run is partial+resumable."""
    docs = [_make_doc(i) for i in range(1, 121)]  # 120 docs -> 3 batches
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _enable_full(chunk_batches=1, max_chunks=1):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    assert pipe.full_run_active is True
    assert pipe.full_run_chunks_total == 3
    assert pipe.full_run_chunks_done == 1
    assert pipe.full_run_all_chunks_done is False
    assert len(cards) == 1
    assert len(cr.cards) == 1
    marker = full_checkpoint_marker_ref(CH)
    cp = parse_checkpoint(fr.rows[marker])
    assert cp.chunks_done == 1
    assert cp.chunks_total == 3
    assert cp.final_merge_done is False


@pytest.mark.asyncio
async def test_crash_mid_run_resume_persists_no_duplicate_cards():
    """Resume across invocations drives all 3 chunks to completion with
    DETERMINISTIC, non-duplicated card ids (the LLM-derived-id risk)."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    all_ids: set[str] = set()
    # 3 invocations: first fresh (force), then 2 resumes.
    for inv in range(3):
        pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
        with _enable_full(chunk_batches=1, max_chunks=1):
            cards = await pipe.topicize_channel(channel_id=CH, force=(inv == 0), resume=(inv > 0))
        all_ids.update(c.id for c in cards)

    # 3 chunks -> 3 unique cards, no duplicates, checkpoint cleared or complete.
    assert len(cr.cards) == 3
    assert len(all_ids) == 3
    assert pipe.full_run_chunks_done == 3
    assert pipe.full_run_all_chunks_done is True


@pytest.mark.asyncio
async def test_budget_kill_switch_clean_halt_at_chunk_boundary():
    """A per-invocation token budget halts cleanly at a chunk boundary: durable
    checkpoint, benign partial result, NO failed-batch inflation, halt metric."""
    from tg_parser.api.metrics import TOPICIZATION_FULL_RUN_BUDGET_HALT_TOTAL

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(
        card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs, tokens_per_batch=10
    )
    before = TOPICIZATION_FULL_RUN_BUDGET_HALT_TOTAL.labels(channel_id=CH)._value.get()

    with _enable_full(chunk_batches=1, max_chunks=10, budget=5):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    after = TOPICIZATION_FULL_RUN_BUDGET_HALT_TOTAL.labels(channel_id=CH)._value.get()
    assert pipe.full_run_halted is True
    assert pipe.full_run_all_chunks_done is False
    assert pipe.failed_batches == 0  # budget halt is NOT a failed batch
    assert len(cards) == 1  # one durable chunk before the budget tripped
    assert after - before == 1
    cp = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp.chunks_done == 1


@pytest.mark.asyncio
async def test_merge_billing_error_is_clean_resumable_halt():
    """A billing/timeout error at the merge site halts cleanly: the chunk is NOT
    committed (no checkpoint advance, no cards), a merge failed-batch is
    recorded, and NO exception propagates."""
    from tg_parser.processing.llm.errors import AnthropicBillingError

    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(
        card_repo=cr,
        bundle_repo=br,
        failure_repo=fr,
        docs=docs,
        merge_side_effect=AnthropicBillingError("credit balance too low"),
    )

    with _enable_full(chunk_batches=1, max_chunks=1):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    assert cards == []
    assert pipe.full_run_halted is True
    assert pipe.failed_batches >= 1  # merge-stage failed batch recorded
    assert len(cr.cards) == 0
    # chunk 0 NOT committed -> no checkpoint advance row written.
    assert full_checkpoint_marker_ref(CH) not in fr.rows


@pytest.mark.asyncio
async def test_per_chunk_record_topic_created_once_per_card():
    """record_topic_created fires exactly once per persisted card across the
    whole chunked run (feeds TopicizationBurnNoProgress; no double-count)."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    with patch("tg_parser.api.metrics.record_topic_created") as rec:
        for inv in range(3):
            pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
            with _enable_full(chunk_batches=1, max_chunks=1):
                await pipe.topicize_channel(channel_id=CH, force=(inv == 0), resume=(inv > 0))

    assert rec.call_count == 3  # one per persisted card, once each


@pytest.mark.asyncio
async def test_stale_checkpoint_restarts_fresh_when_pinned_ref_missing():
    """A checkpoint pinning a ref that no longer exists in the live corpus
    (deleted/replaced) is discarded and the run restarts from chunk 0 (never
    resumes a stale plan)."""
    docs = [_make_doc(i) for i in range(1, 121)]  # 120 planned docs now
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    # Pinned plan references a ref (post:88888) that is NOT in the live corpus
    # -> a pinned ref is missing -> material change -> stale restart.
    stale = _mk_checkpoint(
        [_ref(88888), *(_ref(i) for i in range(1, 120))],
        run_id="old",
        chunk_batches=1,
        chunks_total=3,
        chunks_done=2,
        batches_done=40,
    )
    await fr.record_failure(
        source_ref=full_checkpoint_marker_ref(CH),
        channel_id=CH,
        attempts=2,
        error_class=FULL_CHECKPOINT_ERROR_CLASS,
        error_message="x",
        error_details=stale.to_details(),
    )
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, resume=True)

    # Restarted from 0 -> after one bounded invocation chunks_done == 1 (not 3).
    cp = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp.chunks_done == 1
    assert cp.planned_doc_count == 120  # re-pinned to the current corpus
    assert cp.planned_refs == sorted(_ref(i) for i in range(1, 121))


# ---------------------------------------------------------------------------
# Bugbot Finding 1 — empty-chunk checkpoint-advance semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_genuinely_empty_chunk_advances_and_converges():
    """A chunk that generates + merges cleanly but yields NO card (all docs
    genuinely uncoverable, ZERO batch failures) MUST advance so a cold-start
    run converges and terminates instead of halt-looping forever."""
    docs = [_make_doc(i) for i in range(1, 121)]  # 3 batches -> 3 chunks
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    async def _empty_gen(batch, *args, **kwargs):
        return []  # clean generation, zero topics -> zero cards, no failure

    pipe._generate_topics_batch = _empty_gen  # type: ignore[method-assign]

    with _enable_full(chunk_batches=1, max_chunks=10):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    assert cards == []
    assert pipe.failed_batches == 0
    assert pipe.full_run_halted is False
    # All 3 genuinely-empty chunks advanced -> run converged/terminated.
    assert pipe.full_run_chunks_done == 3
    assert pipe.full_run_all_chunks_done is True
    cp = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp.chunks_done == 3


@pytest.mark.asyncio
async def test_empty_chunk_after_batch_failure_does_not_advance():
    """A chunk that yields NO card because a batch RAISED (transient) must NOT
    advance the checkpoint — it halts cleanly so a resume regenerates it (else
    the docs are permanently stranded and a 0-card channel never converges)."""
    docs = [_make_doc(i) for i in range(1, 121)]  # 3 batches -> 3 chunks
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    async def _raising_gen(batch, *args, **kwargs):
        raise RuntimeError("transient generate failure")

    pipe._generate_topics_batch = _raising_gen  # type: ignore[method-assign]

    with _enable_full(chunk_batches=1, max_chunks=10):
        cards = await pipe.topicize_channel(channel_id=CH, force=True)

    assert cards == []
    assert pipe.full_run_halted is True
    assert pipe.failed_batches >= 1
    # Chunk 0 did NOT advance (no commit, no checkpoint row written).
    assert pipe.full_run_chunks_done == 0
    assert pipe.full_run_all_chunks_done is False
    assert full_checkpoint_marker_ref(CH) not in fr.rows
    assert len(cr.cards) == 0


# ---------------------------------------------------------------------------
# Bugbot Finding 2 — stale-fingerprint restart clears prior cards/bundles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_fingerprint_restart_clears_prior_run_cards():
    """A changed-corpus resume must delete the prior partial run's persisted
    cards/bundles before restarting (else stale rows from the old chunk plan
    survive as orphans/duplicates against the new corpus)."""
    docs = [_make_doc(i) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    # Prior partial run left a stale card+bundle NOT anchored in the new corpus.
    stale = _mk_card(_ref(9999))
    cr.cards[stale.id] = stale
    br.bundles[stale.id] = MagicMock(topic_id=stale.id, items=[])
    # Pinned plan references post:88888 which no longer exists -> material change.
    stale_cp = _mk_checkpoint(
        [_ref(88888), *(_ref(i) for i in range(1, 120))],
        run_id="old",
        chunk_batches=1,
        chunks_total=3,
        chunks_done=2,
        batches_done=40,
    )
    await fr.record_failure(
        source_ref=full_checkpoint_marker_ref(CH),
        channel_id=CH,
        attempts=2,
        error_class=FULL_CHECKPOINT_ERROR_CLASS,
        error_message="x",
        error_details=stale_cp.to_details(),
    )

    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, resume=True)

    # Stale card/bundle from the prior plan are gone (no orphans/duplicates).
    assert stale.id not in cr.cards
    assert stale.id not in br.bundles
    # Fresh chunk-0 pass ran against the new corpus, re-pinned to 120 docs.
    cp = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp.chunks_done == 1
    assert cp.planned_doc_count == 120
    # Only the fresh chunk-0 card survives (stale one deleted).
    assert len(cr.cards) == 1
    assert _mk_card(_ref(1)).id in cr.cards


# ---------------------------------------------------------------------------
# Round-2 Finding 1 — resume is append-tolerant (mid-run ingestion preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_continues_after_docs_appended_mid_run():
    """Finding 1 (HIGH): docs INGESTED AFTER the run started (routine per-tick
    processing) must NOT invalidate the in-flight plan. A resume with a grown
    corpus CONTINUES from the checkpoint (progress preserved) instead of
    wiping and restarting at chunk 0."""
    docs = [_make_doc(i) for i in range(1, 121)]  # 120 planned docs, 3 chunks
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    # Invocation 0: fresh run, one bounded chunk.
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, force=True)
    cp = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp.chunks_done == 1
    assert cp.planned_doc_count == 120
    cards_after_first = len(cr.cards)
    assert cards_after_first == 1

    # Mid-run ingestion: 30 NEW docs appended with a LATER processed_at.
    appended = docs + [_make_doc(i, processed_at=_LATER_TS) for i in range(200, 230)]

    # Invocation 1: resume with the GROWN corpus — must CONTINUE, not wipe.
    pipe2 = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=appended)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe2.topicize_channel(channel_id=CH, resume=True)

    cp2 = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    # Progress ADVANCED (1 -> 2), NOT reset to 1; plan still pinned to 120 refs.
    assert cp2.chunks_done == 2
    assert cp2.planned_doc_count == 120
    assert cp2.planned_refs == sorted(_ref(i) for i in range(1, 121))
    # The chunk-0 card from invocation 0 was NOT vaporized; a second accrued.
    assert len(cr.cards) == 2
    assert _mk_card(_ref(1)).id in cr.cards  # durable chunk-0 card preserved


@pytest.mark.asyncio
async def test_resume_continues_after_same_second_appends():
    """Round-3 F1 (the tie flaw): docs appended with the EXACT run-start max
    processed_at (same-second, so the round-2 `processed_at <= watermark` guard
    would have WRONGLY counted them → false stale wipe) must STILL be excluded by
    ref-membership → resume CONTINUES, progress preserved, no wipe."""
    docs = [_make_doc(i, processed_at=_SAME_TS) for i in range(1, 121)]  # all tied
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, force=True)
    assert parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)]).chunks_done == 1
    assert len(cr.cards) == 1

    # Appends sharing the EXACT same processed_at as the run-start max.
    appended = docs + [_make_doc(i, processed_at=_SAME_TS) for i in range(200, 230)]
    pipe2 = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=appended)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe2.topicize_channel(channel_id=CH, resume=True)

    cp2 = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp2.chunks_done == 2  # CONTINUED, not wiped back to 1
    assert cp2.planned_doc_count == 120  # same-second appends excluded by ref
    assert len(cr.cards) == 2
    assert _mk_card(_ref(1)).id in cr.cards


@pytest.mark.asyncio
async def test_resume_partition_identical_across_resumes_with_tied_timestamps():
    """Round-3 F1: with tied processed_at, the ordered partition is reproduced
    identically on every resume (pinned refs replayed in the pinned order), so no
    batch is dropped or reordered across a 3-chunk run driven over 3 ticks."""
    docs = [_make_doc(i, processed_at=_SAME_TS) for i in range(1, 121)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    for inv in range(3):
        pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
        with _enable_full(chunk_batches=1, max_chunks=1):
            await pipe.topicize_channel(channel_id=CH, force=(inv == 0), resume=(inv > 0))
    # 3 chunks over 3 ticks -> exactly 3 distinct cards, none dropped/duplicated.
    assert len(cr.cards) == 3
    assert len(set(cr.cards)) == 3
    assert pipe.full_run_all_chunks_done is True


# ---------------------------------------------------------------------------
# Round-2 Finding 3 — chunk partition plan is checkpoint-pinned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_changing_chunk_batches_between_invocations_does_not_drop_batches():
    """Finding 3 (MEDIUM): if topicization_full_chunk_batches changes between
    invocations, the resume must use the PINNED span from the checkpoint, not the
    live setting — so chunks_done is interpreted against the SAME partition and
    no batch is skipped or dropped (and no early false 'complete')."""
    docs = [_make_doc(i) for i in range(1, 121)]  # 3 batches of 50/50/20
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()

    # Invocation 0: run PINS chunk_batches=1 -> 3 chunks, does chunk 0.
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    with _enable_full(chunk_batches=1, max_chunks=1):
        await pipe.topicize_channel(channel_id=CH, force=True)
    cp = parse_checkpoint(fr.rows[full_checkpoint_marker_ref(CH)])
    assert cp.chunk_batches == 1
    assert cp.chunks_total == 3
    assert cp.chunks_done == 1

    # Setting CHANGES to 3 (would be a single chunk if applied naively -> a
    # chunks_done=1 would look "complete" and DROP batches 1..2). The pinned
    # span (1) must win on resume.
    pipe2 = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)
    with _enable_full(chunk_batches=3, max_chunks=10):
        await pipe2.topicize_channel(channel_id=CH, resume=True)

    # Pinned span honored: still a 3-chunk plan; the run finished all 3 chunks
    # (no dropped batches) -> 3 distinct cards persisted.
    assert pipe2.full_run_chunks_total == 3
    assert pipe2.full_run_all_chunks_done is True
    assert len(cr.cards) == 3
    cp2 = parse_checkpoint(fr.rows.get(full_checkpoint_marker_ref(CH)))
    assert cp2.chunk_batches == 1  # span still pinned to the original run
    assert cp2.chunks_done == 3  # all chunks completed, none dropped


# ---------------------------------------------------------------------------
# Round-2 Finding 2 — a resumable (partial-progress) run must NOT arm the
# BUG-071 re-escalation cooldown on a 0-card tick
# ---------------------------------------------------------------------------


def _zero_card_reescalation_repos():
    """Repos for the re-escalation arm path: a candidate channel with 0 persisted
    cards and no real ``.session`` (so the injected failure_repo is used)."""
    doc = _make_doc(900)
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.return_value = doc
    processed_repo.list_by_channel.return_value = [doc]
    del processed_repo.session  # force the injected fake failure_repo

    card_repo = FakeCardRepo()  # empty -> 0 persisted cards
    bundle_repo = FakeBundleRepo()
    return doc, processed_repo, card_repo, bundle_repo


def _seed_live_checkpoint(fr: FakeFailureRepo, *, chunks_total=3, chunks_done=1) -> None:
    cp = _mk_checkpoint(
        [_ref(i) for i in range(1, 121)],
        run_id="live",
        chunk_batches=1,
        chunks_total=chunks_total,
        chunks_done=chunks_done,  # < chunks_total AND final_merge_done False -> LIVE
        batches_done=chunks_done,
    )
    fr.rows[full_checkpoint_marker_ref(CH)] = {
        "source_ref": full_checkpoint_marker_ref(CH),
        "channel_id": CH,
        "attempts": chunks_done,
        "error_class": FULL_CHECKPOINT_ERROR_CLASS,
        "error_message": "x",
        "error_details": cp.to_details(),
    }


@pytest.mark.asyncio
async def test_live_checkpoint_suppresses_reescalation_cooldown_on_zero_cards():
    """Finding 2 (MEDIUM): when the flag is ENABLED and a LIVE full-run checkpoint
    exists, a 0-card re-escalation tick is PARTIAL PROGRESS (chunks_done advanced)
    — the BUG-071 cooldown must NOT be armed (else the resume driver is suppressed
    for the TTL)."""
    from tg_parser.services.topicization_service import (
        _reescalation_marker_ref,
        run_incremental_topicization,
    )

    doc, processed_repo, card_repo, bundle_repo = _zero_card_reescalation_repos()
    fr = FakeFailureRepo()
    _seed_live_checkpoint(fr)  # in-progress resumable run
    marker_ref = _reescalation_marker_ref(CH)

    with (
        _enable_full(),
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            return_value={"topics_count": 0, "total_tokens": 0},
        ) as mock_full,
    ):
        await run_incremental_topicization(
            CH,
            [doc.source_ref],
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=card_repo,
            topic_bundle_repo=bundle_repo,
            failure_repo=fr,
        )

    mock_full.assert_awaited_once()
    # Cooldown NOT armed (partial progress), and the checkpoint is untouched.
    assert marker_ref not in fr.rows
    assert full_checkpoint_marker_ref(CH) in fr.rows


@pytest.mark.asyncio
async def test_flag_disabled_leftover_checkpoint_still_arms_cooldown_success_path():
    """Round-4 (HIGH, rollback safety): with the master flag DISABLED, a leftover
    incomplete checkpoint row (from a prior enabled run, or after rollback to a
    build without the resume code) must NOT be treated as "live" — the legacy
    monolithic 0-card escalation STILL arms the BUG-071 cooldown (re-burn loop
    stays broken)."""
    from tg_parser.services.topicization_service import (
        _reescalation_marker_ref,
        run_incremental_topicization,
    )

    doc, processed_repo, card_repo, bundle_repo = _zero_card_reescalation_repos()
    fr = FakeFailureRepo()
    _seed_live_checkpoint(fr)  # leftover row, but flag is OFF
    marker_ref = _reescalation_marker_ref(CH)

    # NOTE: no _enable_full() -> topicization_full_resume_enabled stays False.
    with patch(
        "tg_parser.services.topicization_service.run_topicization",
        new_callable=AsyncMock,
        return_value={"topics_count": 0, "total_tokens": 0},
    ) as mock_full:
        await run_incremental_topicization(
            CH,
            [doc.source_ref],
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=card_repo,
            topic_bundle_repo=bundle_repo,
            failure_repo=fr,
        )

    mock_full.assert_awaited_once()
    # Flag OFF -> leftover checkpoint is inert -> cooldown ARMED (BUG-071 preserved).
    assert marker_ref in fr.rows
    assert fr.rows[marker_ref]["attempts"] == 1


@pytest.mark.asyncio
async def test_no_checkpoint_still_arms_reescalation_cooldown_on_zero_cards():
    """Finding 2 regression guard: with NO live checkpoint, a genuine 0-card
    escalation STILL arms the BUG-071 cooldown (original behavior preserved)."""
    from tg_parser.services.topicization_service import (
        _reescalation_marker_ref,
        run_incremental_topicization,
    )

    doc, processed_repo, card_repo, bundle_repo = _zero_card_reescalation_repos()
    fr = FakeFailureRepo()  # NO full-run checkpoint seeded
    marker_ref = _reescalation_marker_ref(CH)

    with patch(
        "tg_parser.services.topicization_service.run_topicization",
        new_callable=AsyncMock,
        return_value={"topics_count": 0, "total_tokens": 0},
    ) as mock_full:
        await run_incremental_topicization(
            CH,
            [doc.source_ref],
            cross_channel=False,
            processed_repo=processed_repo,
            topic_card_repo=card_repo,
            topic_bundle_repo=bundle_repo,
            failure_repo=fr,
        )

    mock_full.assert_awaited_once()
    # Genuine failed escalation -> cooldown ARMED.
    assert marker_ref in fr.rows
    assert fr.rows[marker_ref]["attempts"] == 1


@pytest.mark.asyncio
async def test_exception_with_live_checkpoint_does_not_arm_cooldown():
    """Round-3 Finding 2: when the flag is ENABLED and run_topicization RAISES but
    a LIVE full-run checkpoint exists (one or more chunks already committed), that
    is partial progress — the exception path must NOT arm the BUG-071 cooldown
    (else the resume driver is suppressed and the half-finished run is stranded).
    The exception still propagates."""
    from tg_parser.services.topicization_service import (
        _reescalation_marker_ref,
        run_incremental_topicization,
    )

    doc, processed_repo, card_repo, bundle_repo = _zero_card_reescalation_repos()
    fr = FakeFailureRepo()
    _seed_live_checkpoint(fr)  # chunks already committed -> resumable
    marker_ref = _reescalation_marker_ref(CH)

    class _TransientError(RuntimeError):
        pass

    with (
        _enable_full(),
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            side_effect=_TransientError("mass timeout mid-run"),
        ) as mock_full,
    ):
        with pytest.raises(_TransientError):
            await run_incremental_topicization(
                CH,
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                failure_repo=fr,
            )

    mock_full.assert_awaited_once()
    # NOT armed (partial progress); the live checkpoint is untouched.
    assert marker_ref not in fr.rows
    assert full_checkpoint_marker_ref(CH) in fr.rows


@pytest.mark.asyncio
async def test_flag_disabled_leftover_checkpoint_still_arms_cooldown_exception_path():
    """Round-4 (HIGH, rollback safety): with the master flag DISABLED, a leftover
    incomplete checkpoint row must NOT suppress arming on the EXCEPTION path
    either — a crashed legacy monolithic escalation STILL arms the BUG-071
    cooldown before propagating."""
    from tg_parser.services.topicization_service import (
        _reescalation_marker_ref,
        run_incremental_topicization,
    )

    doc, processed_repo, card_repo, bundle_repo = _zero_card_reescalation_repos()
    fr = FakeFailureRepo()
    _seed_live_checkpoint(fr)  # leftover row, but flag is OFF
    marker_ref = _reescalation_marker_ref(CH)

    class _TransientError(RuntimeError):
        pass

    # NOTE: no _enable_full() -> topicization_full_resume_enabled stays False.
    with patch(
        "tg_parser.services.topicization_service.run_topicization",
        new_callable=AsyncMock,
        side_effect=_TransientError("mass timeout monolithic"),
    ) as mock_full:
        with pytest.raises(_TransientError):
            await run_incremental_topicization(
                CH,
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                failure_repo=fr,
            )

    mock_full.assert_awaited_once()
    # Flag OFF -> leftover checkpoint inert -> cooldown ARMED (BUG-071 preserved).
    assert marker_ref in fr.rows
    assert fr.rows[marker_ref]["attempts"] == 1


@pytest.mark.asyncio
async def test_exception_without_checkpoint_still_arms_cooldown():
    """Round-3 Finding 2 regression guard: with NO live checkpoint, a crashed
    re-escalation STILL arms the BUG-071 cooldown before propagating (original
    Fix-2 failure-path behavior preserved)."""
    from tg_parser.services.topicization_service import (
        _reescalation_marker_ref,
        run_incremental_topicization,
    )

    doc, processed_repo, card_repo, bundle_repo = _zero_card_reescalation_repos()
    fr = FakeFailureRepo()  # NO full-run checkpoint
    marker_ref = _reescalation_marker_ref(CH)

    class _TransientError(RuntimeError):
        pass

    with patch(
        "tg_parser.services.topicization_service.run_topicization",
        new_callable=AsyncMock,
        side_effect=_TransientError("mass timeout monolithic"),
    ) as mock_full:
        with pytest.raises(_TransientError):
            await run_incremental_topicization(
                CH,
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                failure_repo=fr,
            )

    mock_full.assert_awaited_once()
    # Genuine crashed escalation -> cooldown ARMED before propagating.
    assert marker_ref in fr.rows
    assert fr.rows[marker_ref]["attempts"] == 1


# ===========================================================================
# Cross-chunk merge: destructive dedup + idempotency (design §5.4)
# ===========================================================================


def _kw_card(ref: str, tags: list[str], scope_in: list[str]) -> TopicCard:
    c = _mk_card(ref)
    c.tags = tags
    c.scope_in = scope_in
    return c


def _seed_complete_checkpoint(fr: FakeFailureRepo, *, chunks: int) -> None:
    cp = _mk_checkpoint(
        [_ref(i) for i in range(1, chunks + 1)],
        run_id="r",
        chunk_batches=1,
        chunks_total=chunks,
        chunks_done=chunks,
        batches_done=chunks,
    )
    fr.rows[full_checkpoint_marker_ref(CH)] = {
        "source_ref": full_checkpoint_marker_ref(CH),
        "channel_id": CH,
        "attempts": chunks,
        "error_class": FULL_CHECKPOINT_ERROR_CLASS,
        "error_message": "x",
        "error_details": cp.to_details(),
    }


@pytest.mark.asyncio
async def test_cross_chunk_merge_dedups_and_is_idempotent():
    from tg_parser.services.topicization_service import _finalize_full_run

    docs = [_make_doc(i) for i in range(1, 4)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    # Two near-duplicate cards (identical keywords -> Jaccard 1.0) + one distinct.
    dup_a = _kw_card(_ref(1), tags=["oncology"], scope_in=["oncology screening"])
    dup_b = _kw_card(_ref(2), tags=["oncology"], scope_in=["oncology screening"])
    distinct = _kw_card(_ref(3), tags=["cardiology"], scope_in=["heart rhythm"])
    for c in (dup_a, dup_b, distinct):
        cr.cards[c.id] = c
        br.bundles[c.id] = MagicMock(topic_id=c.id, items=[])
    _seed_complete_checkpoint(fr, chunks=1)

    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=docs)
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=docs)

    with _enable_full(merge_threshold=0.6):
        merged = await _finalize_full_run(
            pipeline=pipe,
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=cr,
            topic_bundle_repo=br,
            failure_repo=fr,
        )

    assert merged == 1  # one loser folded into the survivor
    assert len(cr.cards) == 2  # dup collapsed, distinct kept
    # Deterministic survivor = lexicographically-lowest id (topic:tg:...:1).
    assert dup_a.id in cr.cards
    assert dup_b.id not in cr.cards
    assert distinct.id in cr.cards
    # Checkpoint cleared on full completion.
    assert full_checkpoint_marker_ref(CH) not in fr.rows

    # Idempotent re-run: no checkpoint / no duplicate pairs -> no-op, no crash.
    with _enable_full(merge_threshold=0.6):
        merged2 = await _finalize_full_run(
            pipeline=pipe,
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=cr,
            topic_bundle_repo=br,
            failure_repo=fr,
        )
    assert merged2 == 0
    assert len(cr.cards) == 2


@pytest.mark.asyncio
async def test_finalize_noop_when_final_merge_already_done():
    from tg_parser.services.topicization_service import _finalize_full_run

    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    cp = _mk_checkpoint(
        [_ref(1), _ref(2)],
        run_id="r",
        chunk_batches=1,
        chunks_total=2,
        chunks_done=2,
        batches_done=2,
        final_merge_done=True,  # already merged on a prior invocation
    )
    fr.rows[full_checkpoint_marker_ref(CH)] = {
        "source_ref": full_checkpoint_marker_ref(CH),
        "channel_id": CH,
        "attempts": 2,
        "error_class": FULL_CHECKPOINT_ERROR_CLASS,
        "error_message": "x",
        "error_details": cp.to_details(),
    }
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=[])
    pipe = _make_pipeline(card_repo=cr, bundle_repo=br, failure_repo=fr, docs=[])

    with _enable_full():
        merged = await _finalize_full_run(
            pipeline=pipe,
            channel_id=CH,
            processed_repo=processed_repo,
            topic_card_repo=cr,
            topic_bundle_repo=br,
            failure_repo=fr,
        )
    assert merged == 0
    # A completed-but-uncleared checkpoint is simply cleared (crash-safety path).
    assert full_checkpoint_marker_ref(CH) not in fr.rows


# ===========================================================================
# Resume driver (§5.0): gated, no double-drive, force-independent
# ===========================================================================


@pytest.mark.asyncio
async def test_resume_driver_noop_when_disabled():
    from tg_parser.config import settings
    from tg_parser.services.topicization_service import (
        run_full_topicization_resume_for_channel,
    )

    with patch.object(settings, "topicization_full_resume_enabled", False):
        out = await run_full_topicization_resume_for_channel(channel_id=CH)
    assert out == {"resumed": False, "skipped_reason": "disabled"}


@pytest.mark.asyncio
async def test_resume_driver_noop_when_no_checkpoint():
    from tg_parser.services.topicization_service import (
        run_full_topicization_resume_for_channel,
    )

    fr = FakeFailureRepo()
    with (
        _enable_full(),
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
        ) as rt,
    ):
        out = await run_full_topicization_resume_for_channel(
            channel_id=CH,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
            failure_repo=fr,
        )
    assert out["resumed"] is False
    assert out["skipped_reason"] == "no_checkpoint"
    rt.assert_not_awaited()  # no double-drive: cold channel is escalation's job


@pytest.mark.asyncio
async def test_resume_driver_drives_run_when_live_checkpoint():
    from tg_parser.services.topicization_service import (
        run_full_topicization_resume_for_channel,
    )

    fr = FakeFailureRepo()
    _seed_complete_checkpoint(fr, chunks=3)
    # Make it INCOMPLETE (final_merge_done False already; also mid-run).
    row = fr.rows[full_checkpoint_marker_ref(CH)]
    details = row["error_details"]
    details["chunks_done"] = 1  # 1/3 -> live, incomplete

    with (
        _enable_full(),
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            return_value={"topics_count": 2, "skipped_locked": False},
        ) as rt,
    ):
        out = await run_full_topicization_resume_for_channel(
            channel_id=CH,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
            failure_repo=fr,
        )

    assert out["resumed"] is True
    rt.assert_awaited_once()
    assert rt.await_args.kwargs["resume"] is True
    assert rt.await_args.kwargs["channel_id"] == CH


@pytest.mark.asyncio
async def test_resume_driver_reports_locked_skip():
    from tg_parser.services.topicization_service import (
        run_full_topicization_resume_for_channel,
    )

    fr = FakeFailureRepo()
    _seed_complete_checkpoint(fr, chunks=3)
    fr.rows[full_checkpoint_marker_ref(CH)]["error_details"]["chunks_done"] = 1

    with (
        _enable_full(),
        patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            return_value={"topics_count": 0, "skipped_locked": True},
        ),
    ):
        out = await run_full_topicization_resume_for_channel(
            channel_id=CH,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
            failure_repo=fr,
        )
    assert out["resumed"] is False
    assert out["skipped_reason"] == "locked"


# ===========================================================================
# Wrapper double-count guard + finalize wiring (service layer)
# ===========================================================================


@pytest.mark.asyncio
async def test_wrapper_skips_record_topic_created_on_full_path():
    """When the chunked pipeline ran (full_run_active), the service wrapper must
    NOT emit record_topic_created (the pipeline already emitted per chunk) and
    must invoke the cross-chunk finalize when all chunks are done."""
    import tg_parser.services.topicization_service as svc

    docs = [_make_doc(i) for i in range(1, 4)]
    cr, br, fr = FakeCardRepo(), FakeBundleRepo(), FakeFailureRepo()
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=docs)

    fake_pipe = MagicMock()
    fake_pipe.full_run_active = True
    fake_pipe.full_run_all_chunks_done = True
    fake_pipe.total_input_tokens = 0
    fake_pipe.total_output_tokens = 0
    fake_pipe.total_batches = 1
    fake_pipe.failed_batches = 0
    fake_pipe.last_batch_error = None
    fake_pipe.rejection_breakdown = {}
    fake_pipe.topicize_channel = AsyncMock(return_value=[_mk_card(_ref(1)), _mk_card(_ref(2))])

    llm = AsyncMock()
    llm.close = AsyncMock()

    with (
        patch.object(svc, "TopicizationPipelineImpl", return_value=fake_pipe),
        patch.object(svc, "resolve_llm_config", return_value=("openai", "k", "m")),
        patch.object(svc, "create_llm_client", return_value=llm),
        patch.object(svc, "_finalize_full_run", new_callable=AsyncMock) as finalize,
        patch.object(
            svc,
            "_compute_coverage",
            new_callable=AsyncMock,
            return_value={
                "coverage_pct": 0.0,
                "covered_documents": 0,
                "total_documents": 3,
                "uncovered_documents": 3,
            },
        ),
        patch("tg_parser.api.metrics.record_topic_created") as rec,
        _enable_full(),
    ):
        result = await svc._topicize_channel_locked(
            CH,
            resume=True,
            processed_repo=processed_repo,
            topic_card_repo=cr,
            topic_bundle_repo=br,
            failure_repo=fr,
        )

    rec.assert_not_called()  # no wrapper double-count on the full path
    finalize.assert_awaited_once()  # cross-chunk merge driven when all chunks done
    assert result["topics_count"] == 2


# ===========================================================================
# PG-gated: atomic per-chunk commit / no-duplicate cards on resume (HIGHEST RISK)
# ===========================================================================


@pg_only
@pytest.mark.asyncio
async def test_atomic_chunk_no_duplicate_cards_on_resume_pg(test_db):
    """HIGHEST-RISK pillar on a REAL DB: a chunk's (cards + bundles + checkpoint)
    commit is atomic, so a crash between chunks leaves NO partial-chunk state and
    a resume re-topicizes only the missing chunks WITHOUT minting duplicate
    LLM-derived-id cards. Simulated crash = the atomic commit of chunk 1 is made
    to fail AFTER chunk 0 committed; the resume then completes all chunks."""
    from tg_parser.services.db_context import processing_repos
    from tg_parser.storage.sqlalchemy.processing_failure_repo import (
        SAProcessingFailureRepo,
    )

    docs = [_make_doc(i) for i in range(1, 121)]  # 3 batches

    async def _run(force: bool, resume: bool, *, crash_on_chunk: int | None = None):
        async with processing_repos() as (pr, tcr, tbr, _db):
            fr = SAProcessingFailureRepo(tcr.session)
            # Seed the corpus on the real processing DB.
            for d in docs:
                await pr.upsert(d) if hasattr(pr, "upsert") else None
            pipe = _make_pipeline(card_repo=tcr, bundle_repo=tbr, failure_repo=fr, docs=docs)
            # tcr/tbr/fr share the real session -> real atomic commit.
            if crash_on_chunk is not None:
                orig = pipe._commit_chunk_atomically
                calls = {"n": 0}

                async def _crashing(**kwargs):
                    if calls["n"] == crash_on_chunk:
                        calls["n"] += 1
                        raise RuntimeError("simulated crash mid-chunk-commit")
                    calls["n"] += 1
                    return await orig(**kwargs)

                pipe._commit_chunk_atomically = _crashing  # type: ignore[method-assign]
            with _enable_full(chunk_batches=1, max_chunks=10):
                try:
                    return await pipe.topicize_channel(channel_id=CH, force=force, resume=resume)
                except RuntimeError:
                    return None

    # First run crashes while committing chunk index 1 (chunk 0 already durable).
    await _run(force=True, resume=False, crash_on_chunk=1)
    async with processing_repos() as (pr, tcr, tbr, _db):
        after_crash = await tcr.list_by_channel(CH)
    # Only the atomically-committed chunk 0 persisted (no partial chunk 1).
    assert len(after_crash) == 1

    # Resume to completion.
    await _run(force=False, resume=True)
    await _run(force=False, resume=True)
    async with processing_repos() as (pr, tcr, tbr, _db):
        final_cards = await tcr.list_by_channel(CH)
    ids = [c.id for c in final_cards]
    assert len(ids) == len(set(ids))  # NO duplicate cards
    assert len(final_cards) == 3
