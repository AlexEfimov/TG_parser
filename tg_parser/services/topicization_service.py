"""
Topicization service.

Extracted from cli/topicize_cmd.py — owns the business logic for
topic formation and bundle building.

Session 35: added run_incremental_topicization for Phase 1 (keyword assign).
Session 36: Phase 2 — LLM discover for unassigned documents.
Session 48: Phase 2 Enhancement + Phase 3 — cross-channel topicization.
"""

import contextlib
import random
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.domain.models import (
    BundleItem,
    BundleItemRole,
    IncrementalTopicizeResult,
    MessageType,
    TopicCard,
    TopicLink,
)
from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.services.advisory_lock import channel_advisory_lock
from tg_parser.services.analytics_service import _extract_keywords
from tg_parser.services.db_context import processing_repos, topic_linking_repos
from tg_parser.services.topic_linking_service import _cosine_similarity, _jaccard_similarity
from tg_parser.storage.ports import (
    ProcessedDocumentRepo,
    ProcessingFailureRepo,
    TopicBundleRepo,
    TopicCardRepo,
)
from tg_parser.storage.sqlalchemy.processing_failure_repo import SAProcessingFailureRepo
from tg_parser.utils.channel_id import normalize_channel_id

logger = structlog.get_logger(__name__)

# BUG-075 (Bugbot medium — anti-starvation): module-level RNG used to randomise
# the capped per-tick reconciliation slice so a perpetually-uncovered-but-
# unmarkable doc cannot permanently monopolise the head of a stable-sorted
# ``candidates[:max_docs]`` and starve the tail of the backlog. Module-level (not
# per-call) so it can be patched with a seeded ``random.Random`` in tests.
_RECONCILE_RNG = random.Random()

# BUG-071 (Fix 2): channel-level re-escalation cooldown marker. Reuses the
# existing ``processing_failures`` table (no migration) keyed by a synthetic,
# clearly-namespaced ``source_ref`` that can never collide with a real document
# ref (those are ``tg:<channel>:<type>:<id>``). The marker is written only when
# a full re-escalation produced 0 topic cards, and cleared when one succeeds.
_REESCALATION_ERROR_CLASS = "TopicizationReEscalation"


def _reescalation_marker_ref(channel_id: str) -> str:
    """Synthetic ``processing_failures.source_ref`` for the channel-level marker."""
    return f"topicization:reescalation:{channel_id}"


def _reescalation_in_cooldown(
    last_attempt_at: str | None,
    now: datetime,
    cooldown_s: int,
) -> bool:
    """Return True while a prior 0-card re-escalation is still within its TTL.

    BUG-071 (Fix 2): parses the persisted ``last_attempt_at`` (written by
    ``SAProcessingFailureRepo.record_failure`` as ``%Y-%m-%dT%H:%M:%SZ`` UTC).
    A missing / unparseable / future-dated timestamp returns False (never block
    escalation on bad metadata — mirrors ``pipeline._should_skip_failed``).
    """
    if not last_attempt_at:
        return False
    try:
        last = datetime.strptime(last_attempt_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return False
    age_s = (now - last).total_seconds()
    if age_s < 0:
        return False
    return age_s < cooldown_s


async def _arm_reescalation_marker(
    failure_repo: ProcessingFailureRepo | None,
    channel_id: str,
    marker: dict | None,
    *,
    error_message: str,
) -> None:
    """Best-effort: (re)arm the channel re-escalation cooldown marker, bumping ``attempts``.

    BUG-071 (Fix 2): records a synthetic ``processing_failures`` row keyed by
    :func:`_reescalation_marker_ref` so the next tick's pre-run gate skips the
    full re-escalation while within the TTL. ``marker`` is the row read BEFORE
    the run (``None`` on first failure → ``attempts=1``). All errors are
    swallowed: arming the cooldown must NEVER mask the caller's outcome (least
    of all the original re-escalation exception on the failure path).
    """
    if failure_repo is None:
        return
    attempts = int(marker.get("attempts") or 0) + 1 if marker else 1
    try:
        await failure_repo.record_failure(
            source_ref=_reescalation_marker_ref(channel_id),
            channel_id=channel_id,
            attempts=attempts,
            error_class=_REESCALATION_ERROR_CLASS,
            error_message=error_message,
        )
    except Exception as e:  # noqa: BLE001 — best-effort cooldown write
        logger.debug("reescalation_marker_write_failed channel=%s: %s", channel_id, e)


async def _clear_reescalation_marker(
    failure_repo: ProcessingFailureRepo | None,
    channel_id: str,
) -> None:
    """Best-effort: clear the cooldown marker after a recovered (>0 persisted cards) run."""
    if failure_repo is None:
        return
    try:
        await failure_repo.delete_failure(_reescalation_marker_ref(channel_id))
    except Exception as e:  # noqa: BLE001 — best-effort cooldown write
        logger.debug("reescalation_marker_clear_failed channel=%s: %s", channel_id, e)


# BUG-075: per-doc "discover attempted" idempotency marker. Reuses the
# ``processing_failures`` table (no migration) under a synthetic, clearly
# namespaced ``source_ref`` ``topicization:discover_attempted:<real_ref>`` —
# the SAME pattern as :func:`_reescalation_marker_ref` (which uses
# ``topicization:reescalation:<channel>``). The marker is written for every doc
# that CONSUMED a Phase-2 LLM discover call yet stayed UNCOVERED, so the
# standing coverage-reconciliation hook feeds each such doc to discover
# AT MOST ONCE (learning 2/3 — the off-topic / unassignable docs never enter a
# bundle, so an unconditional "uncovered" sweep would re-burn Sonnet forever).
#
# Why the synthetic ref is collision-safe (same argument as the re-escalation
# marker): a real document ref is ``tg:<channel>:<type>:<id>`` and the per-tick
# processing skip (``pipeline._should_skip_failed`` / ``raw_message_repo``)
# matches the REAL ref, so a ``topicization:discover_attempted:…`` row is loaded
# into ``failure_map`` but NEVER matched against a real message → it can NEVER
# cause a doc to be skipped from PROCESSING.
_DISCOVER_ATTEMPTED_ERROR_CLASS = "TopicizationDiscoverAttempted"
_DISCOVER_ATTEMPTED_PREFIX = "topicization:discover_attempted:"


def _discover_attempted_marker_ref(source_ref: str) -> str:
    """Synthetic ``processing_failures.source_ref`` for the per-doc discover marker."""
    return f"{_DISCOVER_ATTEMPTED_PREFIX}{source_ref}"


async def _list_discover_attempted_refs(
    failure_repo: ProcessingFailureRepo | None,
    channel_id: str,
) -> set[str]:
    """Return the set of REAL source_refs already marked ``discover_attempted``.

    BUG-075: reads the synthetic marker rows for ``channel_id`` and strips the
    :data:`_DISCOVER_ATTEMPTED_PREFIX` so callers get back the real doc refs.
    Best-effort: a missing repo or any read error degrades to an empty set
    (the candidate selection then simply re-considers those docs — bounded,
    never a crash).
    """
    if failure_repo is None:
        return set()
    out: set[str] = set()
    try:
        for f in await failure_repo.list_failures(channel_id=channel_id):
            ref = f.get("source_ref") or ""
            if ref.startswith(_DISCOVER_ATTEMPTED_PREFIX):
                out.add(ref[len(_DISCOVER_ATTEMPTED_PREFIX) :])
    except Exception as e:  # noqa: BLE001 — best-effort marker read
        logger.debug("discover_attempted_read_failed channel=%s: %s", channel_id, e)
        return set()
    return out


async def _mark_discover_attempted(
    failure_repo: ProcessingFailureRepo | None,
    channel_id: str,
    refs: list[str],
) -> None:
    """Best-effort: persist a ``discover_attempted`` marker for each ref in ``refs``.

    BUG-075 (learning 3): called ONLY after a COMPLETED Phase 2 with the set
    ``unassigned_refs − covered_after`` (docs that were sent to discover and did
    not end up covered). Each write is independently swallowed so a marker
    hiccup can never mask the caller's outcome.
    """
    if failure_repo is None or not refs:
        return
    for ref in refs:
        try:
            await failure_repo.record_failure(
                source_ref=_discover_attempted_marker_ref(ref),
                channel_id=channel_id,
                attempts=1,
                error_class=_DISCOVER_ATTEMPTED_ERROR_CLASS,
                error_message="topicization Phase-2 discover attempted; doc stayed uncovered",
            )
        except Exception as e:  # noqa: BLE001 — best-effort marker write
            # BUG-075 (R1 hardening): a persistent marker-write failure while the
            # discover LLM call succeeded leaves the doc unmarked → it is re-fed
            # to Phase-2 next tick (bounded re-burn, capped + sampled — NOT a
            # storm, NOT abandonment). This is the only quiet path to that
            # degradation, so it is genuinely actionable: warn + emit a metric.
            # Still strictly best-effort — the metric emit is itself swallowed so
            # the marker loop / reconcile hook can never crash or pollute
            # stage_errors.
            logger.warning("discover_attempted_mark_failed ref=%s: %s", ref, e)
            with contextlib.suppress(Exception):
                from tg_parser.api.metrics import record_discover_attempted_mark_failed

                record_discover_attempted_mark_failed(channel_id=channel_id)


# BUG-072: cross-process advisory-lock namespace guarding FULL topicization of
# a channel. A DISTINCT int4 namespace from ``SCHEDULER_SOURCE_LOCK_NS``
# (0x5C40) so the two guards never collide in the shared ``pg_advisory_lock``
# keyspace. 0x70C1 ≈ "T0C1" (TOPICization). ``run_topicization`` is the single
# expensive funnel reached by the scheduler re-escalation path, the MCP/API
# ``full_pipeline`` + ``topicization`` jobs, and the separate CLI
# ``tg-parser run`` process — keying the lock here makes all of them mutually
# exclusive per channel.
TOPICIZATION_LOCK_NS = 0x70C1

# BUG-073 (F3): SEPARATE namespace guarding the INCREMENTAL topicization path
# (Phase 1 keyword-assign + Phase 2 LLM-discover). DISTINCT from the FULL
# topicization namespace (0x70C1) ON PURPOSE — see the design note on
# :func:`channel_incremental_topicization_lock`. 0x70C2 ≈ "T0C2".
INCREMENTAL_TOPICIZATION_LOCK_NS = 0x70C2


def channel_incremental_topicization_lock(channel_id: str):
    """Per-channel advisory lock around the INCREMENTAL topicization path (F3).

    Why a SEPARATE namespace (0x70C2) from the FULL-topicization lock (0x70C1)
    rather than reusing 0x70C1 — this is the crux of the F3 design:

    * It must contend INCREMENTAL-vs-INCREMENTAL so a CLI
      ``run_incremental_topicization_for_uncovered`` (which feeds the ENTIRE
      uncovered backlog, NOT tick-local) cannot run its expensive Phase-2 LLM
      discover concurrently with another incremental run for the same channel
      and double-bill the same docs.
    * It must NOT contend INCREMENTAL-vs-FULL, because the BUG-072 re-escalation
      fall-through deliberately runs the cheap incremental Phase 1/2 WHILE a
      full run holds 0x70C1 (so the tick's ``new_doc_refs`` are not abandoned).
      If incremental took 0x70C1 too, that fall-through would self-contend and
      re-introduce the very abandonment BUG-072's follow-up fixed. The nested
      re-escalation ``run_topicization`` call still takes 0x70C1 independently —
      a different namespace means no self-deadlock.

    Trade-off (accepted, per the F3 design): incremental-vs-full Phase-2 overlap
    is NOT excluded; that overlap is bounded (one cheap incremental batch, and
    in the dominant long-full-run case the full run's start-of-run corpus
    snapshot EXCLUDES the late docs so the work is disjoint) and is the price of
    guaranteeing no doc abandonment.
    """
    return channel_advisory_lock(
        channel_id,
        namespace=INCREMENTAL_TOPICIZATION_LOCK_NS,
        engine_attr="processing_storage_engine",
        label="incremental_topicization_lock",
    )


@contextlib.asynccontextmanager
async def channel_topicization_lock(channel_id: str):
    """Per-channel cross-process advisory lock around full topicization (BUG-072).

    Generalises the proven scheduler ``_source_processing_lock`` pattern to the
    topicization funnel. Holds a SESSION-scoped ``pg_try_advisory_lock`` on a
    DEDICATED connection for the whole run (a full run spans many
    transactions/batches, so a transaction-scoped lock cannot cover it), then
    ``pg_advisory_unlock`` + close the connection in ``finally``. The dedicated
    connection is never returned to the pool while the lock is held — avoiding
    the classic footgun of a session lock leaking onto a pooled connection.

    The key is ``hashtext(normalize_channel_id(channel_id))`` so every caller
    that identifies the channel by its normalized id contends on the same lock,
    regardless of which entry path triggered the run.

    Yields ``True`` if the lock was acquired (caller should run) or ``False`` if
    another in-flight run owns the channel (caller should benign-skip).
    Degrades to ``True`` if the DB/engine is unavailable (e.g. unit tests with
    no initialized DB) so lock-infra problems never block topicization.
    """
    from sqlalchemy import text as _sa_text

    from tg_parser.storage.sqlalchemy.database import Database

    key = normalize_channel_id(channel_id) or channel_id

    try:
        db = Database.get_instance()
        engine = getattr(db, "processing_storage_engine", None)
    except Exception:  # noqa: BLE001 — no DB context → no cross-process guard
        engine = None

    if engine is None:
        yield True
        return

    conn = await engine.connect()
    acquired = False
    try:
        row = await conn.execute(
            _sa_text("SELECT pg_try_advisory_lock(:ns, hashtext(:cid))"),
            {"ns": TOPICIZATION_LOCK_NS, "cid": key},
        )
        acquired = bool(row.scalar())
        yield acquired
    finally:
        if acquired:
            try:
                await conn.execute(
                    _sa_text("SELECT pg_advisory_unlock(:ns, hashtext(:cid))"),
                    {"ns": TOPICIZATION_LOCK_NS, "cid": key},
                )
            except Exception as unlock_exc:  # noqa: BLE001
                logger.warning(
                    "topicization_lock_unlock_failed channel=%s: %s",
                    channel_id,
                    unlock_exc,
                )
        await conn.close()


def _locked_skip_result() -> dict[str, int]:
    """Benign no-op sentinel for a lock-contended full topicization (BUG-072).

    Returned when :func:`channel_topicization_lock` is already held by another
    in-flight run. Shaped EXACTLY like a real :func:`run_topicization` return
    (all counts zeroed) so every caller — ``run_full_pipeline``
    (``topics_count`` / ``bundles_count`` / ``total_tokens``), the scheduler
    ``_retopicize_source``, and the re-escalation branch in
    :func:`run_incremental_topicization` — handles it without a ``KeyError``.
    The extra ``skipped_locked`` flag lets the re-escalation branch recognise
    the skip and leave the BUG-071 Fix-2 cooldown marker untouched (a lock-skip
    is NOT a failed 0-card attempt, so it must neither arm nor clear it).
    """
    return {
        "topics_count": 0,
        "bundles_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_batches": 0,
        "failed_batches": 0,
        "last_batch_error": None,
        "rejection_breakdown": {},
        "total_documents": 0,
        "covered_documents": 0,
        "coverage_pct": 0.0,
        "uncovered_documents": 0,
        "skipped_locked": True,
    }


async def run_topicization(
    channel_id: str,
    force: bool = False,
    build_bundles: bool = True,
    *,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
) -> dict[str, int]:
    """BUG-072: serialise FULL topicization of a channel across processes.

    Thin wrapper around :func:`_topicize_channel_locked` that takes a
    NON-BLOCKING per-channel Postgres advisory lock
    (:func:`channel_topicization_lock`). If another full run already owns the
    channel the call is a BENIGN no-op: it logs and returns
    :func:`_locked_skip_result` (a zeroed result shaped like the real return)
    rather than raising — so the BUG-071 Fix-2 crash-path cooldown arming in
    :func:`run_incremental_topicization` is NOT tripped (a lock-skip is not a
    failed 0-card attempt) and no caller breaks. The acquiring run keeps the
    existing Fix-2 arm/clear-on-persisted-cards behaviour unchanged.
    """
    async with channel_topicization_lock(channel_id) as lock_acquired:
        if not lock_acquired:
            logger.warning(
                "topicization_run_skipped_already_in_flight channel=%s "
                "(another full run owns the channel lock)",
                channel_id,
            )
            return _locked_skip_result()
        return await _topicize_channel_locked(
            channel_id,
            force=force,
            build_bundles=build_bundles,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
        )


async def _topicize_channel_locked(
    channel_id: str,
    force: bool = False,
    build_bundles: bool = True,
    *,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
) -> dict[str, int]:
    """
    Run topicization for a channel.

    Args:
        channel_id: Channel identifier
        force: Regenerate topics even if they exist
        build_bundles: Create topic bundles (default True)
        processed_repo: Optional DI for ProcessedDocumentRepo
        topic_card_repo: Optional DI for TopicCardRepo
        topic_bundle_repo: Optional DI for TopicBundleRepo

    Returns:
        Statistics (topics_count, bundles_count)
    """
    provider, api_key, model = resolve_llm_config("topicization")
    logger.info("Topicization with %s/%s", provider, model or "default")
    llm_client = create_llm_client(
        provider=provider,
        api_key=api_key,
        model=model,
    )

    try:
        async with contextlib.AsyncExitStack() as stack:
            if processed_repo is None or topic_card_repo is None or topic_bundle_repo is None:
                (
                    processed_repo,
                    topic_card_repo,
                    topic_bundle_repo,
                    _db,
                ) = await stack.enter_async_context(processing_repos())

            pipeline = TopicizationPipelineImpl(
                llm_client=llm_client,
                processed_doc_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

            logger.info("Starting topicization for channel: %s", channel_id)
            topic_cards = await pipeline.topicize_channel(
                channel_id=channel_id,
                force=force,
            )

            topics_count = len(topic_cards)
            logger.info("Created %s topic cards", topics_count)

            from tg_parser.api.metrics import record_topic_created

            for _ in topic_cards:
                record_topic_created(channel_id=channel_id)

            bundles_count = 0
            if build_bundles:
                logger.info("Building topic bundles for %d topics", topics_count)

                channel_docs = await processed_repo.list_by_channel(channel_id)

                for card in topic_cards:
                    try:
                        await pipeline.build_topic_bundle(
                            topic_card=card,
                            channel_id=channel_id,
                            documents=channel_docs,
                        )
                        bundles_count += 1
                    except (RuntimeError, ValueError) as e:
                        logger.error(
                            "Failed to build bundle for topic %s: %s",
                            card.id,
                            e,
                            exc_info=True,
                        )

                logger.info("Created %d topic bundles", bundles_count)

            coverage = await _compute_coverage(
                processed_repo,
                topic_bundle_repo,
                channel_id,
            )
            coverage_pct = coverage["coverage_pct"]
            logger.info(
                "Coverage: %.1f%% (%d/%d documents)",
                coverage_pct,
                coverage["covered_documents"],
                coverage["total_documents"],
            )

            return {
                "topics_count": topics_count,
                "bundles_count": bundles_count,
                "input_tokens": pipeline.total_input_tokens,
                "output_tokens": pipeline.total_output_tokens,
                "total_tokens": pipeline.total_input_tokens + pipeline.total_output_tokens,
                # BUG-018: surface batch-failure ratio so the CLI can exit
                # non-zero on systemic failures (e.g. all 17 batches errored
                # with the same billing/quota class error).
                "total_batches": pipeline.total_batches,
                "failed_batches": pipeline.failed_batches,
                "last_batch_error": pipeline.last_batch_error,
                # BUG-023: surface aggregate quality-filter rejection
                # breakdown so the CLI can emit a per-reason summary.
                "rejection_breakdown": dict(pipeline.rejection_breakdown),
                **coverage,
            }
    finally:
        await llm_client.close()


async def run_incremental_topicization(
    channel_id: str,
    new_doc_refs: list[str],
    *,
    cross_channel: bool | None = None,
    defer_if_locked: bool = False,
    reconcile_only: bool = False,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> IncrementalTopicizeResult:
    """BUG-073 (F3): serialise INCREMENTAL topicization of a channel per-channel.

    Thin wrapper around :func:`_run_incremental_topicization_locked` that takes a
    NON-BLOCKING per-channel advisory lock in a SEPARATE namespace
    (:func:`channel_incremental_topicization_lock`, 0x70C2) — see that function
    for why it is distinct from the full-topicization lock (0x70C1).

    Skip / defer semantics (the F3 no-abandonment design):

    * ``defer_if_locked=True`` (the CLI backlog-fill path
      :func:`run_incremental_topicization_for_uncovered`): on contention this is
      a BENIGN skip — it returns an empty result and does NO work. SAFE because
      the uncovered backlog is recomputed from scratch on every invocation, so
      nothing is abandoned (a later backlog-fill — or the lock holder itself —
      covers those docs).
    * ``defer_if_locked=False`` (the scheduler tick path, default): the docs are
      TICK-LOCAL (``new_doc_refs`` = docs_after − docs_before for THIS tick;
      later ticks never re-feed them and there is no scheduler-side
      uncovered-doc recovery). Dropping them would PERMANENTLY abandon them, so
      this path NEVER skips: it acquires the lock when free (excluding a
      concurrent backlog-fill from duplicating Phase-2 spend), but on contention
      it PROCEEDS anyway. The duplicate work is bounded to one cheap tick-local
      batch — strictly cheaper than the abandonment it prevents, mirroring the
      BUG-072 re-escalation fall-through philosophy.

    Net effect: incremental-vs-incremental Phase-2 duplication is prevented for
    the expensive cases (backlog-vs-backlog, and tick-holds-vs-backlog), while
    no doc is ever permanently abandoned. The BUG-071 Fix-2 cooldown marker is
    left UNTOUCHED on a benign skip (a skip is not a failed 0-card attempt).

    BUG-075 (``reconcile_only``): the standing coverage-reconciliation hook
    passes ``reconcile_only=True`` (with ``defer_if_locked=True``). This forces
    the cheap Phase 1/2 path and HARD-DISABLES the BUG-071 zero-card full
    re-escalation (learning 5 — a standing hook that re-escalated would storm a
    full re-topicization on stuck 0-card channels). It also enables the per-doc
    ``discover_attempted`` marker write after a completed Phase 2 (learning 3),
    so each uncovered doc is sent to discover AT MOST ONCE. The flag is plumbed
    THROUGH to :func:`_run_incremental_topicization_locked` (do not skip a
    layer): ``should_reescalate`` lives there, so the inner body is the only
    place that can force it false.
    """
    async def _run() -> IncrementalTopicizeResult:
        return await _run_incremental_topicization_locked(
            channel_id,
            new_doc_refs,
            cross_channel=cross_channel,
            reconcile_only=reconcile_only,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            failure_repo=failure_repo,
        )

    async with channel_incremental_topicization_lock(channel_id) as lock_acquired:
        if lock_acquired:
            # Acquired (or degraded-to-acquired with no DB): HOLD the dedicated
            # lock connection for the whole run so a concurrent backlog-fill
            # cannot duplicate Phase-2 spend.
            return await _run()
        if defer_if_locked:
            logger.info(
                "incremental_topicization_skipped_already_in_flight channel=%s "
                "(another incremental run owns the channel lock; backlog deferred)",
                channel_id,
            )
            # BUG-073 (Bugbot follow-up): surface the defer as an OBSERVABLE
            # outcome (``deferred_locked=True``) so the CLI cannot mistake a
            # no-work skip for a "backlog processed, 0 assigned / 0% coverage"
            # success. The BUG-071 Fix-2 cooldown marker stays untouched (a defer
            # is benign, not a failed 0-card attempt — and we never reach the
            # re-escalation/marker code on this branch).
            return IncrementalTopicizeResult(deferred_locked=True)
        logger.warning(
            "incremental_topicization_lock_contended_proceeding channel=%s "
            "(tick-local run proceeds to avoid abandoning new docs)",
            channel_id,
        )
        # BUG-073 (Bugbot MEDIUM follow-up): proceed-WITHOUT-lock. Fall OUT of
        # the lock context here so the dedicated advisory-lock connection is
        # RELEASED *before* the long Phase 1/2 LLM run below — otherwise an idle
        # connection would stay checked out of the pool for the run's entire
        # duration even though no lock is held. The acquired + defer branches
        # above already returned inside the context, so the only path that
        # reaches past this `async with` is exactly this proceed-without-lock case.

    return await _run()


async def _run_incremental_topicization_locked(
    channel_id: str,
    new_doc_refs: list[str],
    *,
    cross_channel: bool | None = None,
    reconcile_only: bool = False,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> IncrementalTopicizeResult:
    """
    Incremental topicization: Phase 1 (keyword assign) + Phase 2 (LLM discover).

    1. Load new ProcessedDocuments by source_refs
    2. Compute coverage_before
    3. Phase 1: assign_documents_to_topics (keyword matching, 0 LLM tokens)
    4. Update bundles for assigned docs
    5. Phase 2: LLM discover for unassigned docs (assign/create/unassignable)
       - Phase 2 Enhancement: if cross_channel, load topics from ALL channels as context
    6. Update bundles for LLM-assigned docs, create bundles for new topics
    7. Phase 3: if cross_channel, auto-create TopicLinks for touched topics
    8. Compute coverage_after and return result

    Args:
        cross_channel: Enable cross-channel context + auto-linking.
            None = use settings.cross_channel_topicization.
    """
    from tg_parser.config import settings

    if cross_channel is None:
        cross_channel = settings.cross_channel_topicization

    llm_client = None
    try:
        async with contextlib.AsyncExitStack() as stack:
            if processed_repo is None or topic_card_repo is None or topic_bundle_repo is None:
                (
                    processed_repo,
                    topic_card_repo,
                    topic_bundle_repo,
                    _db,
                ) = await stack.enter_async_context(processing_repos())
                # BUG-071 (Fix 2): bind the cooldown-marker repo on the same
                # processing session when we own the repos (production path).
                # When the caller injects repos (tests), they inject failure_repo
                # explicitly — we never fabricate one from a mock session.
                if failure_repo is None:
                    failure_repo = SAProcessingFailureRepo(processed_repo.session)

            new_docs = []
            for ref in new_doc_refs:
                doc = await processed_repo.get_by_source_ref(ref)
                if doc:
                    new_docs.append(doc)
                else:
                    logger.warning("Document not found for source_ref=%s, skipping", ref)

            if not new_docs:
                logger.info("No new documents to assign for channel %s", channel_id)
                coverage = await _compute_coverage(processed_repo, topic_bundle_repo, channel_id)
                return IncrementalTopicizeResult(
                    coverage_before=coverage["coverage_pct"],
                    coverage_after=coverage["coverage_pct"],
                )

            existing_cards = await topic_card_repo.list_by_channel(channel_id)
            # BUG-071 (Fix 2): a zero-card channel with new docs is the trigger
            # for a full re-escalation. Decide whether to actually do the
            # EXPENSIVE full run, or fall through to the cheap incremental
            # Phase 1/2 path below.
            should_reescalate = len(existing_cards) == 0 and len(new_docs) > 0
            # BUG-075 (learning 5 — THE KILLER): the standing reconciliation
            # path must NEVER trigger a FULL re-topicization. A reconciliation
            # that keeps feeding new "uncovered" refs to a 0-card channel would
            # otherwise re-arm the BUG-071 zero-card escalation trigger on every
            # tick (the cooldown only SPACES it; it does not stop it) — exactly
            # the catastrophic token-burn BUG-071 fixed. Forcing the flag false
            # HERE (the only layer that owns ``should_reescalate``) keeps
            # reconciliation cheap-Phase-1/2-ONLY and leaves the re-escalation
            # cooldown marker untouched (the ``if should_reescalate`` blocks
            # below — incl. the marker read/arm/clear — are skipped entirely).
            if reconcile_only:
                should_reescalate = False
            marker = None
            if should_reescalate:
                # BUG-071 (Fix 2): gate the full re-escalation behind a cooldown.
                # A channel stuck at 0 cards (e.g. every full run truncates) would
                # otherwise be re-escalated to a full ~hundreds-of-batch Sonnet run
                # on EVERY tick that produces new docs, re-burning tokens unbounded.
                now = datetime.now(UTC)
                # ``failure_repo`` is bound above on the production path and
                # injected by tests; when it is None the gate degrades to "no
                # cooldown" (best-effort — never block escalation on a missing
                # store). Any repo error is likewise swallowed so the gate can
                # never crash the tick.
                if failure_repo is not None:
                    try:
                        marker_ref = _reescalation_marker_ref(channel_id)
                        for f in await failure_repo.list_failures(channel_id=channel_id):
                            if f.get("source_ref") == marker_ref:
                                marker = f
                                break
                    except Exception as e:  # noqa: BLE001 — best-effort cooldown read
                        logger.debug("reescalation_marker_read_failed channel=%s: %s", channel_id, e)
                        marker = None

                if marker is not None and _reescalation_in_cooldown(
                    marker.get("last_attempt_at"),
                    now,
                    settings.topicization_reescalation_cooldown_s,
                ):
                    # BUG-071 (Bugbot Finding 1): suppress ONLY the expensive full
                    # re-escalation while in cooldown — do NOT abandon the new docs.
                    # Fall through to the normal incremental Phase 1/2 path so the
                    # cheap keyword-assign + (Fix-1 batch-split) LLM-discover path
                    # can still assign/create topics for them this tick.
                    logger.info(
                        "topicization re-escalation skipped (cooldown) channel=%s attempts=%s "
                        "cooldown_s=%d — running cheap incremental Phase 1/2 instead",
                        channel_id,
                        marker.get("attempts"),
                        settings.topicization_reescalation_cooldown_s,
                    )
                    should_reescalate = False

            if should_reescalate:
                logger.info(
                    "channel=%s has 0 topic cards but %d new docs — escalating to full topicization",
                    channel_id,
                    len(new_docs),
                )
                try:
                    full = await run_topicization(
                        channel_id=channel_id,
                        force=False,
                        build_bundles=True,
                        processed_repo=processed_repo,
                        topic_card_repo=topic_card_repo,
                        topic_bundle_repo=topic_bundle_repo,
                    )
                except Exception as e:
                    # BUG-071 (Fix-2 failure-path gap — prod 2026-06-28):
                    # ``run_topicization`` RE-RAISES on failure (its only
                    # protection is ``finally: llm_client.close()``). A 0-card
                    # re-escalation that dies by exception (mass 300s
                    # ``LLMCallTimeoutError`` / ``AnthropicBillingError``) used to
                    # skip ALL the marker-arming below, so the next scheduler tick
                    # re-escalated the SAME 0-card channel to another full
                    # hundreds-of-batch Sonnet run — the exact re-burn loop Fix 2
                    # exists to break (two such crashes burned ~12.1M tokens in one
                    # session). A crashed re-escalation IS a failed 0-card attempt:
                    # ARM the marker BEFORE the exception propagates so the cooldown
                    # gate engages next tick. Arming is best-effort (the helper
                    # swallows its own errors) so it can NEVER mask ``e``; we then
                    # re-raise to preserve the scheduler's existing
                    # ``stages_failed=['incremental_topicization'] outcome=degraded``
                    # handling rather than silently swallowing the failure.
                    logger.warning(
                        "topicization re-escalation crashed channel=%s (%s: %s) — "
                        "arming cooldown marker before propagating",
                        channel_id,
                        type(e).__name__,
                        e,
                    )
                    await _arm_reescalation_marker(
                        failure_repo,
                        channel_id,
                        marker,
                        error_message=(
                            f"full topicization re-escalation raised {type(e).__name__}: {e}"
                        ),
                    )
                    raise

                # BUG-072: a lock-skip means another full run already owns the
                # channel advisory lock and is ACTIVELY topicizing it. This is a
                # BENIGN no-op for the expensive full re-escalation, NOT a failed
                # 0-card attempt — so we leave the Fix-2 cooldown marker UNTOUCHED
                # (neither arm nor clear; the run that holds the lock owns that
                # bookkeeping). But we must NOT abandon this tick's ``new_docs``:
                # mirroring the BUG-071 cooldown fall-through (above), we suppress
                # only the expensive full re-escalation and FALL THROUGH to the
                # cheap incremental Phase 1/2 path so the new docs are still
                # assigned/covered this tick.
                #
                # Why fall-through (vs. abandoning the docs) and why it does NOT
                # re-introduce BUG-072: the new docs are tick-local
                # (scheduler_service.py computes ``new_doc_refs`` as
                # docs_after − docs_before for THIS tick only; later ticks never
                # re-feed them and there is no scheduler-side uncovered-doc
                # recovery — ``_retopicize_source`` is dormant and
                # ``run_incremental_topicization_for_uncovered`` is CLI-only). If
                # we returned here, a 0-card channel whose concurrent full run
                # already loaded its corpus snapshot BEFORE these docs were
                # persisted (the dominant case — a long hundreds-of-batch run
                # holds the lock for a long time AFTER its snapshot) would leave
                # these docs permanently uncovered once that run succeeds and the
                # channel transitions to >0 cards (no future re-escalation fires).
                # The incremental fall-through is CHEAP and tick-local (a single
                # small batch over ``new_docs``), NOT a second full corpus run, so
                # it does not reintroduce the dual-full-run spend BUG-072 targets;
                # and in that dominant case the in-flight run's snapshot EXCLUDES
                # these docs, so the incremental Phase 2 covers a DISJOINT set with
                # distinct LLM-generated topic ids — no duplicate topics, no DB
                # conflict. (Only a short in-flight run whose snapshot already
                # includes these docs can produce minor duplicate work, bounded to
                # one incremental batch — strictly cheaper than the abandonment it
                # prevents.)
                if full.get("skipped_locked"):
                    logger.info(
                        "topicization re-escalation skipped channel=%s — another "
                        "full run holds the channel lock; running cheap incremental "
                        "Phase 1/2 instead (cooldown marker untouched)",
                        channel_id,
                    )
                    should_reescalate = False
                else:
                    coverage_after = await _compute_coverage(
                        processed_repo, topic_bundle_repo, channel_id
                    )

                    # BUG-071 (Bugbot Finding 2): gate marker-clearing on ACTUALLY
                    # PERSISTED cards, not the in-memory ``full["topics_count"]``.
                    # ``topicize_channel`` swallows ``SQLAlchemyError`` on each
                    # ``topic_card_repo.upsert`` and still returns the in-memory
                    # list, so ``topics_count`` can be > 0 while ZERO cards
                    # persisted. If we cleared the marker on that, the channel
                    # would stay at 0 persisted cards and re-escalate a full run
                    # EVERY tick. Re-query the repo for the authoritative persisted
                    # count; treat an unknown (errored) recount as failure so we
                    # ARM the cooldown (safe side).
                    persisted_cards = 0
                    try:
                        persisted_cards = len(await topic_card_repo.list_by_channel(channel_id))
                    except Exception as e:  # noqa: BLE001 — unknown persisted state ⇒ arm cooldown
                        logger.debug(
                            "reescalation_persisted_recount_failed channel=%s: %s", channel_id, e
                        )
                        persisted_cards = 0

                    # BUG-071 (Fix 2): record / clear the cooldown marker based on
                    # the PERSISTED escalation outcome. >0 persisted cards =
                    # recovered → clear so future ticks proceed normally. 0
                    # persisted = still failing → (re)arm the marker (bumping
                    # attempts) so the next tick is skipped until the TTL.
                    if persisted_cards > 0:
                        await _clear_reescalation_marker(failure_repo, channel_id)
                    else:
                        await _arm_reescalation_marker(
                            failure_repo,
                            channel_id,
                            marker,
                            error_message=(
                                "full topicization re-escalation persisted 0 topic cards"
                            ),
                        )

                    return IncrementalTopicizeResult(
                        coverage_before=0.0,
                        coverage_after=coverage_after["coverage_pct"],
                        tokens_used=int(full.get("total_tokens", 0)),
                    )

            coverage_before = await _compute_coverage(processed_repo, topic_bundle_repo, channel_id)

            pipeline = TopicizationPipelineImpl(
                llm_client=None,
                processed_doc_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

            assignments, unassigned_refs = await pipeline.assign_documents_to_topics(
                new_docs=new_docs,
                channel_id=channel_id,
            )

            docs_by_ref = {doc.source_ref: doc for doc in new_docs}
            await _update_bundles_for_assignments(
                assignments,
                docs_by_ref,
                topic_bundle_repo,
                method="keyword",
                topic_card_repo=topic_card_repo,
            )

            llm_assignments: list = []
            new_topic_cards: list = []
            truly_unassignable: list[str] = []
            tokens_used = 0

            # Phase 2 Enhancement: load cross-channel topics as context
            cross_channel_topics: list[dict] | None = None
            if cross_channel and unassigned_refs:
                cross_channel_topics = await _load_cross_channel_topics(
                    channel_id,
                    topic_card_repo,
                )

            if unassigned_refs:
                provider, api_key, model = resolve_llm_config("topicization")
                llm_client = create_llm_client(
                    provider=provider,
                    api_key=api_key,
                    model=model,
                )
                pipeline_with_llm = TopicizationPipelineImpl(
                    llm_client=llm_client,
                    processed_doc_repo=processed_repo,
                    topic_card_repo=topic_card_repo,
                    topic_bundle_repo=topic_bundle_repo,
                )

                unassigned_docs = [
                    docs_by_ref[ref] for ref in unassigned_refs if ref in docs_by_ref
                ]

                # BUG-075 (post-refill watch): count the docs that actually enter
                # Phase-2 discover on the RECONCILE path specifically
                # (reconcile_only=True). The normal tick-local new-docs incremental
                # path (reconcile_only=False) is deliberately NOT counted — this
                # series isolates reconcile-driven discover spend so a sustained
                # non-zero rate (non-convergence / re-burn) is alertable. Best-effort
                # + swallowed (mirrors the R1 marker-fail emit) so a metrics hiccup
                # can never crash the hook or pollute stage_errors.
                if reconcile_only and unassigned_docs:
                    with contextlib.suppress(Exception):
                        from tg_parser.api.metrics import record_reconcile_discover_docs

                        record_reconcile_discover_docs(
                            channel_id=channel_id, count=len(unassigned_docs)
                        )

                existing_topics = [
                    {"id": card.id, "title": card.title, "scope_in": card.scope_in}
                    for card in existing_cards
                ]
                existing_topic_ids = {card.id for card in existing_cards}

                from tg_parser.api.metrics import record_topic_created

                batch_size = settings.topicization_batch_size
                total_batches = (len(unassigned_docs) + batch_size - 1) // batch_size
                for batch_idx in range(0, len(unassigned_docs), batch_size):
                    batch_docs = unassigned_docs[batch_idx : batch_idx + batch_size]
                    batch_num = batch_idx // batch_size + 1

                    logger.info(
                        "incremental_llm_batch_start channel=%s batch=%d/%d docs=%d",
                        channel_id,
                        batch_num,
                        total_batches,
                        len(batch_docs),
                    )

                    (
                        batch_assignments,
                        batch_new_cards,
                        batch_unassignable,
                        batch_tokens,
                    ) = await pipeline_with_llm._discover_single_batch(
                        channel_id=channel_id,
                        batch_docs=batch_docs,
                        existing_topics=existing_topics,
                        existing_topic_ids=existing_topic_ids,
                        cross_channel_topics=cross_channel_topics,
                    )

                    # Batch checkpoint: persist each successful batch immediately,
                    # so later-batch failures do not erase already discovered progress.
                    await _update_bundles_for_assignments(
                        batch_assignments,
                        docs_by_ref,
                        topic_bundle_repo,
                        method="llm",
                        topic_card_repo=topic_card_repo,
                    )
                    llm_assignments.extend(batch_assignments)
                    truly_unassignable.extend(batch_unassignable)
                    tokens_used += batch_tokens

                    for card in batch_new_cards:
                        try:
                            await topic_card_repo.upsert(card)
                            await pipeline_with_llm.build_topic_bundle(
                                topic_card=card,
                                channel_id=channel_id,
                                documents=new_docs,
                            )
                            record_topic_created(channel_id=channel_id)
                            logger.info(
                                "Created discovered topic %s: %s",
                                card.id,
                                card.title[:60],
                            )
                            new_topic_cards.append(card)
                            existing_topics.append(
                                {"id": card.id, "title": card.title, "scope_in": card.scope_in}
                            )
                            existing_topic_ids.add(card.id)
                        except (SQLAlchemyError, RuntimeError, ValueError) as e:
                            logger.error(
                                "Failed to save discovered topic %s: %s",
                                card.id,
                                e,
                                exc_info=True,
                            )

            # Phase 3: auto-create cross-channel TopicLinks
            cross_channel_links_created = 0
            if cross_channel:
                touched_topic_ids = _collect_touched_topic_ids(
                    assignments,
                    llm_assignments,
                    new_topic_cards,
                )
                if touched_topic_ids:
                    cross_channel_links_created = await _run_cross_channel_linking(
                        channel_id=channel_id,
                        touched_topic_ids=touched_topic_ids,
                        threshold=settings.cross_channel_link_threshold,
                    )

            coverage_after = await _compute_coverage(processed_repo, topic_bundle_repo, channel_id)

            # BUG-075 (learning 3): mark every doc that CONSUMED a Phase-2
            # discover call and did NOT become covered, so the standing
            # reconciliation feeds it AT MOST ONCE. The marker set is
            # ``unassigned_refs − covered_after`` — i.e. the docs sent to Phase-2
            # discover (``unassigned_refs``) that did not end up in a bundle.
            # This DELIBERATELY EXCLUDES Phase-1 keyword-assigned docs (they
            # never reached discover, so a future cheap retry must stay open for
            # them). We only reach this point on a COMPLETED Phase 2: a discover
            # batch that RAISES (hard LLM/parse error) propagates out of the
            # batch loop BEFORE here, so its docs stay UNMARKED and are retried
            # next pass. Best-effort + gated on ``failure_repo`` (None on injected
            # test paths) so it never perturbs callers that do not opt in.
            if unassigned_refs and failure_repo is not None:
                covered_after_refs: set[str] = set()
                marker_scan_ok = True
                try:
                    for _b in await topic_bundle_repo.list_by_channel(channel_id):
                        for _item in _b.items:
                            covered_after_refs.add(_item.source_ref)
                except Exception as e:  # noqa: BLE001 — best-effort covered scan
                    logger.debug(
                        "discover_attempted_covered_scan_failed channel=%s: %s", channel_id, e
                    )
                    marker_scan_ok = False
                if marker_scan_ok:
                    # Only mark refs we are CONFIDENT did not get covered; on a
                    # scan error we mark nothing (retry next pass) rather than
                    # risk barring a genuinely-covered doc from a future retry.
                    to_mark = [
                        ref for ref in unassigned_refs if ref not in covered_after_refs
                    ]
                    await _mark_discover_attempted(failure_repo, channel_id, to_mark)

            # BUG-023: Phase 2 LLM discover may reject candidate topics via
            # ``_build_topic_card`` → ``_validate_quality``; surface the
            # per-reason aggregate breakdown so the CLI can show it.
            rejection_breakdown: dict[str, int] = {}
            if unassigned_refs:
                rejection_breakdown = dict(pipeline_with_llm.rejection_breakdown)

            result = IncrementalTopicizeResult(
                assigned_keyword=assignments,
                assigned_llm=llm_assignments,
                new_topics=new_topic_cards,
                unassignable=truly_unassignable,
                tokens_used=tokens_used,
                coverage_before=coverage_before["coverage_pct"],
                coverage_after=coverage_after["coverage_pct"],
                cross_channel_links_created=cross_channel_links_created,
                rejection_breakdown=rejection_breakdown,
            )

            logger.info(
                "Incremental topicization for %s: "
                "phase1=%d, phase2_assign=%d, new_topics=%d, unassignable=%d, "
                "cross_links=%d, coverage %.1f%% -> %.1f%%",
                channel_id,
                len(assignments),
                len(llm_assignments),
                len(new_topic_cards),
                len(truly_unassignable),
                cross_channel_links_created,
                result.coverage_before,
                result.coverage_after,
            )

            return result
    finally:
        if llm_client is not None:
            await llm_client.close()


async def run_incremental_topicization_for_uncovered(
    channel_id: str,
    assign_only: bool = False,
    *,
    cross_channel: bool | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
) -> IncrementalTopicizeResult:
    """
    CLI-mode incremental topicization: find uncovered docs, run Phase 1 (+ Phase 2).

    Unlike run_incremental_topicization which takes explicit new_doc_refs
    (used by the scheduler), this function discovers uncovered docs itself
    by comparing all channel documents against current bundle coverage.

    Args:
        channel_id: Channel identifier
        assign_only: If True, run Phase 1 only (0 LLM tokens, no Phase 2)
        cross_channel: Enable cross-channel context + auto-linking.
            None = use settings.cross_channel_topicization.
        processed_repo: Optional DI for ProcessedDocumentRepo
        topic_card_repo: Optional DI for TopicCardRepo
        topic_bundle_repo: Optional DI for TopicBundleRepo
    """
    async with contextlib.AsyncExitStack() as stack:
        if processed_repo is None or topic_card_repo is None or topic_bundle_repo is None:
            (
                processed_repo,
                topic_card_repo,
                topic_bundle_repo,
                _db,
            ) = await stack.enter_async_context(processing_repos())

        all_docs = await processed_repo.list_by_channel(channel_id)
        if not all_docs:
            logger.info("No documents found for channel %s", channel_id)
            return IncrementalTopicizeResult()

        covered_refs: set[str] = set()
        bundles = await topic_bundle_repo.list_by_channel(channel_id)
        for bundle in bundles:
            for item in bundle.items:
                covered_refs.add(item.source_ref)

        uncovered_refs = [d.source_ref for d in all_docs if d.source_ref not in covered_refs]

        logger.info(
            "CLI incremental for %s: %d total docs, %d covered, %d uncovered",
            channel_id,
            len(all_docs),
            len(covered_refs),
            len(uncovered_refs),
        )

        if not uncovered_refs:
            coverage = await _compute_coverage(
                processed_repo,
                topic_bundle_repo,
                channel_id,
            )
            return IncrementalTopicizeResult(
                coverage_before=coverage["coverage_pct"],
                coverage_after=coverage["coverage_pct"],
            )

    if assign_only:
        result = await _run_assign_only(channel_id, uncovered_refs)
    else:
        # BUG-073 (F3): the backlog-fill path feeds the ENTIRE uncovered backlog
        # (not tick-local), so its Phase-2 spend is the expensive
        # incremental-vs-incremental case. On lock contention it is a BENIGN skip
        # (defer): the uncovered set is recomputed on the next invocation, so no
        # doc is abandoned — only the (cheap, tick-local) scheduler path proceeds
        # unconditionally to avoid abandoning its new docs.
        result = await run_incremental_topicization(
            channel_id,
            uncovered_refs,
            cross_channel=cross_channel,
            defer_if_locked=True,
        )

    return result


async def run_reconciliation_for_channel(
    *,
    channel_id: str,
    max_docs: int | None = None,
    cross_channel: bool | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> dict[str, Any]:
    """BUG-075: standing per-tick coverage reconciliation (cheap-only, convergent).

    Satisfies all five hard-won learnings of the descoped prototype:

    * **Learning 1 (standing/convergent):** the scheduler calls this on EVERY
      tick. A deferral or a partial drain is naturally retried next tick because
      candidates are recomputed from scratch each call.
    * **Learning 2/3 (no re-burn / marker):** candidates are
      ``uncovered − attempted`` — uncovered docs MINUS those already carrying a
      ``discover_attempted`` marker. The marker is written by
      :func:`_run_incremental_topicization_locked` after a completed Phase 2, so
      each uncovered doc is sent to discover AT MOST ONCE → steady-state cost ~0.
    * **Learning 4 (connection lifecycle):** the candidate-selection repo session
      is opened and CLOSED (``async with`` exits) BEFORE the cheap incremental
      run, so no idle dedicated DB connection is held across the LLM run — and
      the incremental run itself inherits the correct release-before-run /
      defer structure of :func:`run_incremental_topicization`.
    * **Learning 5 (NEVER re-escalate):** the feed goes to
      :func:`run_incremental_topicization` with ``reconcile_only=True`` (forces
      ``should_reescalate=False``) and ``defer_if_locked=True`` (reuses the
      ``0x70C2`` incremental lock; a defer is retried next tick). It NEVER takes
      ``0x70C1`` / NEVER calls :func:`run_topicization`.

    Bounded by ``max_docs`` (default ``settings.topicization_reconcile_max_docs``)
    so one tick cannot trip the per-source watchdog; a large backlog drains over
    multiple standing ticks.

    Returns a small status dict suitable for structured logging::

        {"candidates": int, "fed": int, "deferred": bool, "tokens": int,
         "coverage_before": float, "coverage_after": float,
         "skipped_reason": str | None}
    """
    from tg_parser.config import settings

    if max_docs is None:
        max_docs = settings.topicization_reconcile_max_docs

    injected = (
        processed_repo is not None
        and topic_card_repo is not None
        and topic_bundle_repo is not None
    )

    # Phase A — candidate selection in a SHORT-LIVED repo session that is CLOSED
    # before the cheap incremental run below (learning 4: no idle connection
    # held across the LLM run). Mirrors run_incremental_topicization_for_uncovered.
    async with contextlib.AsyncExitStack() as stack:
        if not injected:
            (
                processed_repo,
                topic_card_repo,
                topic_bundle_repo,
                _db,
            ) = await stack.enter_async_context(processing_repos())
            if failure_repo is None:
                failure_repo = SAProcessingFailureRepo(processed_repo.session)

        all_docs = await processed_repo.list_by_channel(channel_id)
        if not all_docs:
            return {
                "candidates": 0,
                "fed": 0,
                "deferred": False,
                "tokens": 0,
                "coverage_before": 0.0,
                "coverage_after": 0.0,
                "skipped_reason": "no_docs",
            }

        covered_refs: set[str] = set()
        for bundle in await topic_bundle_repo.list_by_channel(channel_id):
            for item in bundle.items:
                covered_refs.add(item.source_ref)

        uncovered = [d.source_ref for d in all_docs if d.source_ref not in covered_refs]
        if not uncovered:
            return {
                "candidates": 0,
                "fed": 0,
                "deferred": False,
                "tokens": 0,
                "coverage_before": 100.0,
                "coverage_after": 100.0,
                "skipped_reason": "all_covered",
            }

        attempted = await _list_discover_attempted_refs(failure_repo, channel_id)
        candidates = [ref for ref in uncovered if ref not in attempted]
        if not candidates:
            # Steady state: every uncovered doc already consumed its single
            # discover attempt — issue ZERO LLM calls (learning 2 no-re-burn).
            return {
                "candidates": 0,
                "fed": 0,
                "deferred": False,
                "tokens": 0,
                "coverage_before": 0.0,
                "coverage_after": 0.0,
                "skipped_reason": "all_attempted",
            }

        # BUG-075 (Bugbot medium — anti-starvation): when the backlog exceeds the
        # cap, feed a UNIFORM RANDOM sample of the candidates rather than always
        # the stable-sorted head. A doc can stay in ``candidates`` indefinitely
        # WITHOUT earning a ``discover_attempted`` marker — e.g. a keyword-assigned
        # doc whose bundle write failed (never enters Phase-2 ``unassigned_refs``,
        # so never marked) or a doc whose discover batch RAISED (a non-completed
        # attempt deliberately retried per learning 3). Under the old
        # ``candidates[:max_docs]`` such a doc would permanently occupy the head
        # and the tail of the backlog would NEVER be reconciled (a convergence gap,
        # contra the Definition of Done). Random sampling gives every candidate a
        # fair chance each tick → the tail converges. This NEVER causes >1
        # COMPLETED discover per doc: a doc that completes a discover is marked and
        # leaves ``candidates`` permanently, so the only docs ever re-fed are the
        # ones that did NOT complete a discover (keyword-only docs cost 0 LLM;
        # raised-batch docs are the intended retry — learnings 2/3 intact).
        if max_docs and max_docs > 0 and len(candidates) > max_docs:
            feed = _RECONCILE_RNG.sample(candidates, max_docs)
        else:
            feed = list(candidates)
        forward = (
            {
                "processed_repo": processed_repo,
                "topic_card_repo": topic_card_repo,
                "topic_bundle_repo": topic_bundle_repo,
                "failure_repo": failure_repo,
            }
            if injected
            else {}
        )
    # repo session CLOSED here (production path) — no idle connection held below.

    result = await run_incremental_topicization(
        channel_id,
        feed,
        cross_channel=cross_channel,
        defer_if_locked=True,
        reconcile_only=True,
        **forward,
    )

    logger.info(
        "bug075_reconcile channel=%s uncovered=%d candidates=%d fed=%d "
        "deferred=%s tokens=%d coverage %.1f%% -> %.1f%%",
        channel_id,
        len(uncovered),
        len(candidates),
        len(feed),
        result.deferred_locked,
        result.tokens_used,
        result.coverage_before,
        result.coverage_after,
    )

    return {
        "candidates": len(candidates),
        "fed": len(feed),
        "deferred": result.deferred_locked,
        "tokens": result.tokens_used,
        "coverage_before": result.coverage_before,
        "coverage_after": result.coverage_after,
        "skipped_reason": None,
    }


async def _run_assign_only(
    channel_id: str,
    doc_refs: list[str],
) -> IncrementalTopicizeResult:
    """Phase 1 only: keyword assignment without LLM discover."""
    async with processing_repos() as (processed_repo, topic_card_repo, topic_bundle_repo, _db):
        new_docs = []
        for ref in doc_refs:
            doc = await processed_repo.get_by_source_ref(ref)
            if doc:
                new_docs.append(doc)

        if not new_docs:
            coverage = await _compute_coverage(
                processed_repo,
                topic_bundle_repo,
                channel_id,
            )
            return IncrementalTopicizeResult(
                coverage_before=coverage["coverage_pct"],
                coverage_after=coverage["coverage_pct"],
            )

        coverage_before = await _compute_coverage(
            processed_repo,
            topic_bundle_repo,
            channel_id,
        )

        pipeline = TopicizationPipelineImpl(
            llm_client=None,
            processed_doc_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
        )

        assignments, unassigned_refs = await pipeline.assign_documents_to_topics(
            new_docs=new_docs,
            channel_id=channel_id,
        )

        docs_by_ref = {doc.source_ref: doc for doc in new_docs}
        await _update_bundles_for_assignments(
            assignments,
            docs_by_ref,
            topic_bundle_repo,
            method="keyword",
            topic_card_repo=topic_card_repo,
        )

        coverage_after = await _compute_coverage(
            processed_repo,
            topic_bundle_repo,
            channel_id,
        )

        result = IncrementalTopicizeResult(
            assigned_keyword=assignments,
            unassignable=unassigned_refs,
            tokens_used=0,
            coverage_before=coverage_before["coverage_pct"],
            coverage_after=coverage_after["coverage_pct"],
        )

        logger.info(
            "Assign-only for %s: assigned=%d, unassigned=%d, coverage %.1f%% -> %.1f%%",
            channel_id,
            len(assignments),
            len(unassigned_refs),
            result.coverage_before,
            result.coverage_after,
        )

        return result


async def _update_bundles_for_assignments(
    assignments: list,
    docs_by_ref: dict,
    topic_bundle_repo: TopicBundleRepo,
    method: str,
    *,
    topic_card_repo: TopicCardRepo | None = None,
) -> None:
    """Group assignments by topic and add items to bundles.

    F5-C Evolving Topic Summaries (a4b5c6d7e8f9):
    after a successful ``add_items`` we bump
    ``topic_cards.new_items_since_last_summary`` by the number of items
    actually added — this is the trigger watched by
    ``ResummarizationService``.  ``topic_card_repo`` is keyword-only and
    defaults to None so older callers (e.g. legacy tests) keep working;
    production call sites in this module always pass it.
    """
    assignments_by_topic: dict[str, list] = defaultdict(list)
    for assignment in assignments:
        assignments_by_topic[assignment.topic_id].append(assignment)

    for topic_id, topic_assignments in assignments_by_topic.items():
        bundle_items = []
        for a in topic_assignments:
            doc = docs_by_ref.get(a.source_ref)
            if doc is None:
                continue
            parts = doc.source_ref.split(":")
            if len(parts) != 4:
                continue
            _, ch_id, msg_type, msg_id = parts
            bundle_items.append(
                BundleItem(
                    channel_id=ch_id,
                    message_id=msg_id,
                    message_type=MessageType(msg_type),
                    source_ref=doc.source_ref,
                    role=BundleItemRole.SUPPORTING,
                    score=a.score,
                    justification=f"incremental {method} assign (score={a.score})",
                )
            )

        if bundle_items:
            try:
                await topic_bundle_repo.add_items(topic_id, bundle_items)
                if topic_card_repo is not None:
                    # F5-C trigger: bump the resummarize counter atomically with the bundle add.
                    await topic_card_repo.increment_resummary_counter(
                        topic_id, by=len(bundle_items)
                    )
                logger.info(
                    "Added %d items to bundle %s (%s); resummary counter +%d",
                    len(bundle_items),
                    topic_id,
                    method,
                    len(bundle_items) if topic_card_repo is not None else 0,
                )
            except ValueError:
                logger.warning("Bundle not found for topic %s, skipping", topic_id)


async def _compute_coverage(
    processed_repo: ProcessedDocumentRepo,
    bundle_repo: TopicBundleRepo,
    channel_id: str,
) -> dict:
    """Compute topic coverage metrics for a channel."""
    all_docs = await processed_repo.list_by_channel(channel_id)
    total = len(all_docs)
    if total == 0:
        return {
            "total_documents": 0,
            "covered_documents": 0,
            "coverage_pct": 0.0,
            "uncovered_documents": 0,
        }

    all_refs = {d.source_ref for d in all_docs}

    covered_refs: set[str] = set()
    bundles = await bundle_repo.list_by_channel(channel_id)
    for bundle in bundles:
        for item in bundle.items:
            covered_refs.add(item.source_ref)

    covered = len(all_refs & covered_refs)
    return {
        "total_documents": total,
        "covered_documents": covered,
        "coverage_pct": round(covered / total * 100, 1),
        "uncovered_documents": total - covered,
    }


# ============================================================================
# Cross-channel helpers (Session 48)
# ============================================================================


async def _load_cross_channel_topics(
    channel_id: str,
    topic_card_repo: TopicCardRepo,
) -> list[dict]:
    """Load compact topic descriptors from ALL other channels for LLM context."""
    all_cards = await topic_card_repo.list_all()
    cross_topics = []
    for card in all_cards:
        card_channel = card.sources[0] if card.sources else None
        if card_channel and card_channel != channel_id:
            cross_topics.append(
                {
                    "id": card.id,
                    "title": card.title,
                    "scope_in": card.scope_in,
                    "channel_id": card_channel,
                }
            )
    logger.info(
        "Loaded %d cross-channel topics as context (excluding channel=%s)",
        len(cross_topics),
        channel_id,
    )
    return cross_topics if cross_topics else None


def _collect_touched_topic_ids(
    keyword_assignments: list,
    llm_assignments: list,
    new_topic_cards: list[TopicCard],
) -> set[str]:
    """Collect topic IDs that were touched during this incremental run."""
    touched: set[str] = set()
    for a in keyword_assignments:
        touched.add(a.topic_id)
    for a in llm_assignments:
        touched.add(a.topic_id)
    for card in new_topic_cards:
        touched.add(card.id)
    return touched


async def _run_cross_channel_linking(
    channel_id: str,
    touched_topic_ids: set[str],
    threshold: float = 0.3,
) -> int:
    """Phase 3: auto-create TopicLinks for touched topics against other channels.

    For each touched topic, computes Jaccard (keyword) + cosine (embedding)
    similarity against topics from other channels. Pairs above threshold
    are saved as TopicLinks.

    Reuses _jaccard_similarity / _cosine_similarity from topic_linking_service.

    Returns:
        Number of new TopicLinks created.
    """
    from tg_parser.services.topic_linking_service import COSINE_WEIGHT, JACCARD_WEIGHT

    async with topic_linking_repos() as (
        topic_card_repo,
        _bundle_repo,
        topic_link_repo,
        embedding_repo,
        _db,
    ):
        touched_cards: list[TopicCard] = []
        for tid in touched_topic_ids:
            card = await topic_card_repo.get_by_id(tid)
            if card:
                touched_cards.append(card)

        if not touched_cards:
            return 0

        all_cards = await topic_card_repo.list_all()
        other_cards = [c for c in all_cards if c.sources and c.sources[0] != channel_id]

        if not other_cards:
            logger.info("No topics from other channels for cross-linking")
            return 0

        other_keywords: dict[str, set[str]] = {c.id: _extract_keywords(c) for c in other_cards}

        other_embeddings: dict[str, list[float]] = {}
        for c in other_cards:
            if c.anchors:
                emb = await embedding_repo.get_by_source_ref(c.anchors[0].anchor_ref)
                if emb:
                    other_embeddings[c.id] = emb.embedding

        new_links: list[TopicLink] = []
        for touched_card in touched_cards:
            t_kw = _extract_keywords(touched_card)
            t_emb: list[float] | None = None
            if touched_card.anchors:
                emb = await embedding_repo.get_by_source_ref(
                    touched_card.anchors[0].anchor_ref,
                )
                if emb:
                    t_emb = emb.embedding

            for other_card in other_cards:
                o_kw = other_keywords.get(other_card.id, set())
                jaccard, shared = _jaccard_similarity(t_kw, o_kw)

                o_emb = other_embeddings.get(other_card.id)
                if t_emb and o_emb:
                    cosine = _cosine_similarity(t_emb, o_emb)
                    combined = JACCARD_WEIGHT * jaccard + COSINE_WEIGHT * cosine
                else:
                    combined = jaccard

                if combined >= threshold:
                    new_links.append(
                        TopicLink(
                            topic_id_a=touched_card.id,
                            topic_id_b=other_card.id,
                            similarity_score=round(combined, 4),
                            shared_keywords=shared,
                            created_at=datetime.now(UTC),
                        )
                    )

        if not new_links:
            logger.info("Phase 3: no cross-channel links above threshold %.2f", threshold)
            return 0

        saved = await topic_link_repo.upsert_batch(new_links)
        logger.info(
            "Phase 3: created %d cross-channel TopicLinks for %d touched topics",
            saved,
            len(touched_cards),
        )
        return saved
