"""BUG-076: resumable full-topicization checkpoint (synthetic ``processing_failures`` ref).

Standalone, dependency-light module so BOTH the pipeline
(``tg_parser.processing.topicization``) and the service
(``tg_parser.services.topicization_service``) can import the checkpoint
constants + (de)serialization helpers WITHOUT creating an import cycle (the
service already imports the pipeline). No migration: the checkpoint lives in the
existing ``processing_failures`` table under a synthetic, clearly-namespaced
``source_ref`` — the SAME collision-safe pattern as the BUG-071
``topicization:reescalation:<channel>`` and BUG-075
``topicization:discover_attempted:<ref>`` markers.

Collision-safety (identical argument to the two existing markers): a real
document ref is ``tg:<channel>:<type>:<id>`` and the per-tick processing skip
matches the REAL ref, so a ``topicization:full_checkpoint:<channel>`` row is
loaded into ``failure_map`` but can NEVER be matched against a real message →
it can never skip a doc from processing.

Append-tolerant plan pinning (BUG-076 round-2 F1 → round-3 F1)
--------------------------------------------------------------
A resumable run pins its PLANNED corpus at run start by **capturing the exact,
ordered set of planned document refs** (``planned_refs`` — the ``source_ref``
primary key used for batching) plus a stable ``planned_ref_hash``. On every
resume the plan is reconstructed by **membership-by-ref**: select exactly the
docs whose ``source_ref`` is in ``planned_refs`` and replay them in the pinned
order, so:

* pure APPENDS (new refs) are excluded by ref-membership and can NEVER shift
  chunk boundaries or inflate the set — REGARDLESS of ``processed_at`` ties /
  coarse timestamps (the round-2 ``max(processed_at)`` watermark heuristic had a
  tie flaw: a new doc ingested in the same second as the run-start max was
  ``<= watermark`` → wrongly counted → false stale wipe → the round-1 wipe-loop
  regression on active channels; round-3 removes the timestamp boundary as a
  guard entirely);
* a genuine material change = one or more PINNED refs no longer exist in the
  live corpus (deleted / replaced) → clean restart with the card/bundle cleanup;
* the ordered partition is reproduced IDENTICALLY every resume: ``planned_refs``
  is stored already sorted by ``source_ref`` (unique, so no ties), and the
  resume replays docs strictly in that pinned order.

The run therefore accumulates multi-chunk progress across ticks even while the
source is actively ingesting; newly-arrived docs are covered by the normal
incremental / BUG-075 reconcile path (or a subsequent full run), never by
nuking the checkpoint.

Chunk-plan pinning (BUG-076 round-2 Finding 3)
----------------------------------------------
The chunk partition span (``chunk_batches``) is pinned in the checkpoint at run
start. A resume rebuilds the partition with the PINNED span, not the live
``topicization_full_chunk_batches`` setting, so changing that setting mid-run
(deploy / env / A-B) can never re-interpret ``chunks_done`` against a different
partition (which would skip or drop batches). The setting change takes effect
only for the NEXT fresh run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

# Synthetic ``processing_failures`` namespace for the per-channel full-run
# checkpoint. Distinct from ``topicization:reescalation:`` (BUG-071) and
# ``topicization:discover_attempted:`` (BUG-075) and never a ``tg:`` doc ref.
FULL_CHECKPOINT_ERROR_CLASS = "TopicizationFullCheckpoint"
FULL_CHECKPOINT_PREFIX = "topicization:full_checkpoint:"


class FullCheckpointReadError(Exception):
    """BUG-077 (F3): a checkpoint READ failed (transport/DB error) — NOT "absent".

    Raised so callers can distinguish "the row could not be read right now"
    (abort the invocation at 0 token cost and retry next tick) from "no
    checkpoint exists" (start a fresh pinned run). Falling through to a fresh
    run on a transient read error would re-burn chunk 0+, overwrite the real
    checkpoint and mint duplicate LLM-derived-id cards.
    """


def full_checkpoint_marker_ref(channel_id: str) -> str:
    """Synthetic ``processing_failures.source_ref`` for the per-channel checkpoint."""
    return f"{FULL_CHECKPOINT_PREFIX}{channel_id}"


def planned_refs_from_documents(documents: list) -> list[str]:
    """Deterministic ordered planned ref list = sorted unique ``source_ref``s.

    Sorting by ``source_ref`` (a unique primary key) gives a total order with NO
    ties, so the partition is reproduced identically on every resume without
    depending on ``processed_at`` (which is coarse / non-unique — the round-3
    flaw). De-duplicates defensively in case the corpus query ever returns a ref
    twice.
    """
    return sorted({getattr(d, "source_ref", None) for d in documents} - {None})


def planned_ref_hash(refs: list[str]) -> str:
    """Stable content hash of the ordered planned ref set (integrity / logging)."""
    h = hashlib.sha256()
    for r in refs:
        h.update(r.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


@dataclass
class FullRunCheckpoint:
    """Deserialized full-run checkpoint state (BUG-076 §5.2 + round-2 pins).

    ``chunks_done`` doubles as the ``processing_failures.attempts`` column (the
    caller controls ``attempts`` — see ``SAProcessingFailureRepo.record_failure``).

    Pins:

    * ``planned_refs`` / ``planned_ref_hash`` — the EXACT ordered planned ref set
      (round-3 F1). Resume rebuilds the plan by ref-membership, so pure appends
      never invalidate it (tie-proof) and a missing pinned ref is the
      material-change signal that triggers a clean stale restart.
      ``planned_doc_count`` is retained (== ``len(planned_refs)``) for gauges /
      quick logging.
    * ``chunk_batches`` — pin the partition span so a changed
      ``topicization_full_chunk_batches`` setting cannot re-interpret
      ``chunks_done`` against a different partition (round-2 F3).

    BUG-077 additions (legacy-safe defaults — rows written before BUG-077
    parse to the defaults below):

    * ``consecutive_noprogress_resumes`` / ``last_noprogress_at`` — the F1
      circuit-breaker state. The counter is incremented by the resume driver's
      failure-path write whenever an invocation ends with NO durable progress
      (``chunks_done`` unchanged, ``final_merge_done`` not flipped, row not
      cleared); it resets to 0 implicitly on every atomic chunk commit (a fresh
      ``FullRunCheckpoint`` is written with the default 0) — i.e. any advance
      closes the breaker.
    * ``cards_stamped`` — True iff the run STARTED under the BUG-077 F5 code
      that stamps ``metadata.topicization_run_id = run_id`` into every
      persisted card. The stale-restart wipe is scoped to the run's stamped
      cards only when this is True; pre-fix checkpoints (False) fall back to
      the broad ``delete_by_channel`` (their cards carry unmatchable
      per-card ``run_<now>`` stamps).
    """

    run_id: str
    planned_refs: list[str]
    planned_ref_hash: str
    planned_doc_count: int
    chunk_batches: int
    chunks_total: int
    chunks_done: int
    batches_done: int
    tokens_spent_cumulative: int
    final_merge_done: bool
    last_chunk_at: str | None = None
    consecutive_noprogress_resumes: int = 0
    last_noprogress_at: str | None = None
    cards_stamped: bool = False

    def to_details(self) -> dict:
        """Serialize to the ``error_details`` dict persisted in ``error_details_json``."""
        return {
            "run_id": self.run_id,
            "planned_refs": list(self.planned_refs),
            "planned_ref_hash": self.planned_ref_hash,
            "planned_doc_count": self.planned_doc_count,
            "chunk_batches": self.chunk_batches,
            "chunks_total": self.chunks_total,
            "chunks_done": self.chunks_done,
            "batches_done": self.batches_done,
            "tokens_spent_cumulative": self.tokens_spent_cumulative,
            "final_merge_done": self.final_merge_done,
            "last_chunk_at": self.last_chunk_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "consecutive_noprogress_resumes": self.consecutive_noprogress_resumes,
            "last_noprogress_at": self.last_noprogress_at,
            "cards_stamped": self.cards_stamped,
        }

    @property
    def is_complete(self) -> bool:
        """True when every chunk is done AND the cross-chunk merge has committed."""
        return (
            self.chunks_total > 0
            and self.chunks_done >= self.chunks_total
            and self.final_merge_done
        )


def parse_checkpoint(failure_row: dict | None) -> FullRunCheckpoint | None:
    """Parse a ``processing_failures`` row (as returned by ``list_failures``) into state.

    Returns ``None`` when the row is absent or malformed (a missing / corrupt
    checkpoint degrades to "no checkpoint → start fresh", never a crash).
    """
    if not failure_row:
        return None
    details = failure_row.get("error_details") or {}
    if not isinstance(details, dict):
        return None
    try:
        raw_refs = details.get("planned_refs") or []
        planned_refs = [str(r) for r in raw_refs] if isinstance(raw_refs, list) else []
        return FullRunCheckpoint(
            run_id=str(details.get("run_id") or ""),
            planned_refs=planned_refs,
            planned_ref_hash=str(details.get("planned_ref_hash") or ""),
            planned_doc_count=int(details.get("planned_doc_count") or len(planned_refs) or 0),
            chunk_batches=int(details.get("chunk_batches") or 0),
            chunks_total=int(details.get("chunks_total") or 0),
            chunks_done=int(details.get("chunks_done", failure_row.get("attempts") or 0) or 0),
            batches_done=int(details.get("batches_done") or 0),
            tokens_spent_cumulative=int(details.get("tokens_spent_cumulative") or 0),
            final_merge_done=bool(details.get("final_merge_done") or False),
            last_chunk_at=details.get("last_chunk_at"),
            consecutive_noprogress_resumes=int(details.get("consecutive_noprogress_resumes") or 0),
            last_noprogress_at=details.get("last_noprogress_at"),
            cards_stamped=bool(details.get("cards_stamped") or False),
        )
    except (TypeError, ValueError):
        return None


def noprogress_circuit_open(
    checkpoint: FullRunCheckpoint,
    *,
    now: datetime | None = None,
) -> bool:
    """BUG-077 (F1): True while the no-progress circuit-breaker holds resumes off.

    Shared by BOTH gates so they can never disagree: the resume driver
    (``run_full_topicization_resume_for_channel`` — cheap pre-lock skip) and the
    chunked pipeline's resuming branch (which ALSO covers the 0-card
    ``should_reescalate`` escalation path — with a live checkpoint the BUG-071
    cooldown is deliberately not armed, so escalation would otherwise bypass a
    driver-only breaker and keep re-burning the failing chunk).

    Semantics:

    * counter < limit (or limit=0 → disabled) → closed (run normally);
    * counter >= limit AND cooldown_s == 0 → HARD-open (manual intervention);
    * counter >= limit AND within ``cooldown_s`` of ``last_noprogress_at`` →
      open (skip at 0 token cost);
    * counter >= limit AND the TTL elapsed (or the timestamp is
      missing/unparseable/future — never strand a run on bad metadata) →
      closed for ONE probe attempt; a failing probe re-arms the TTL via the
      driver's counter write.
    """
    from tg_parser.config import settings

    limit = int(getattr(settings, "topicization_full_resume_noprogress_limit", 0) or 0)
    if limit <= 0 or checkpoint.consecutive_noprogress_resumes < limit:
        return False
    cooldown_s = int(getattr(settings, "topicization_full_resume_noprogress_cooldown_s", 0) or 0)
    if cooldown_s <= 0:
        return True
    ts = checkpoint.last_noprogress_at
    if not ts:
        return False
    try:
        last = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return False
    age_s = ((now or datetime.now(UTC)) - last).total_seconds()
    if age_s < 0:
        return False
    return age_s < cooldown_s
