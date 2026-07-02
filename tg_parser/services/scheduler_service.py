"""
Scheduler service for incremental pipeline runs.

Session 30: Automatic incremental processing — iterates over active sources
and runs the full pipeline (ingest → process → topicize → export) for each.
"""

import asyncio
import contextlib
import signal
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from tg_parser.config import settings
from tg_parser.domain.json_utils import coerce_aware_utc
from tg_parser.ingestion.telegram.telethon_client import SessionLockContentionError
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.services.db_context import ingestion_and_processing_repos, ingestion_state_repo
from tg_parser.storage.ports import IngestionStateRepo, ProcessedDocumentRepo
from tg_parser.utils.channel_id import normalize_channel_id

logger = structlog.get_logger(__name__)


def _setting_number(value: Any, default: float | None) -> float | None:
    """Return ``value`` if it is a real (non-bool) number, else ``default``.

    Defensive resolution for the BUG-067/068 scheduler config reads (watchdog
    timeout, degraded/coverage ratios). Pydantic guarantees real floats in
    production, so this is a no-op there; it only guards against a synthetic
    settings double (e.g. a unit-test ``MagicMock``) so the new threshold /
    ``asyncio.wait_for`` arithmetic never raises on a non-numeric attribute.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    return default


class DegradedProcessingTick(RuntimeError):
    """BUG-067 (B1): a source tick that processed too few of its attempted docs.

    Raised/recorded (not actually thrown to abort work) when a processing tick
    attempts >0 documents but the failed/attempted ratio meets
    ``settings.scheduler_degraded_failure_ratio`` — e.g. a fully billing-blocked
    tick that processed 0-of-N. Used as the recorded ``error_class`` /
    ``error_message`` so the tick is surfaced as a non-success outcome in
    ``get_pipeline_status`` instead of looking healthy.
    """


# Fix 4: namespace for the per-source advisory lock (two-key form, mirrors the
# F5-C resummarize pattern). 0x5C40 ≈ "SC4"(heduler fix 4) — an arbitrary but
# stable int4 namespace that reduces collisions against other hashtext() locks.
SCHEDULER_SOURCE_LOCK_NS = 0x5C40


@contextlib.asynccontextmanager
async def _source_processing_lock(source_id: str):
    """Per-source cross-tick advisory lock (Fix 4 — BUG-068 A3 follow-up).

    A3 raised ``scheduler_max_instances`` 1→2, so a coalesced/misfired second
    ``incremental_pipeline`` instance (or a tick that overruns the poll
    interval) could start a SECOND ``run_full_pipeline`` for the same channel.
    Both could pass ``exists()`` for the same new docs before either persists →
    duplicate Telegram/LLM work (re-burn). This guard holds a Postgres
    advisory lock per ``source_id`` for the whole tick so a given source is
    processed by at most one in-flight tick; a second concurrent tick is
    skipped (logged), not double-processed.

    Design vs. the resummarize hook (which uses ``pg_try_advisory_xact_lock``):
    a scheduler tick spans MANY transactions, so a transaction-scoped lock
    cannot cover it. We instead take a SESSION-scoped ``pg_try_advisory_lock``
    on a DEDICATED connection held open for the tick's lifetime, then
    ``pg_advisory_unlock`` + close. The dedicated connection is the key to
    avoiding the classic pooling footgun (a session lock leaking onto a pooled
    connection across commits) — this connection is never returned to the pool
    while the lock is held.

    Yields ``True`` if the lock was acquired (caller should process) or
    ``False`` if another in-flight tick holds it (caller should skip).
    Degrades to ``True`` if the DB/engine is unavailable (e.g. unit tests with
    no initialized DB) so lock-infra problems never block processing.
    """
    from sqlalchemy import text as _sa_text

    from tg_parser.storage.sqlalchemy.database import Database

    try:
        db = Database.get_instance()
        engine = getattr(db, "ingestion_state_engine", None)
    except Exception:  # noqa: BLE001 — no DB context → no cross-process guard
        engine = None

    if engine is None:
        yield True
        return

    conn = await engine.connect()
    acquired = False
    try:
        row = await conn.execute(
            _sa_text("SELECT pg_try_advisory_lock(:ns, hashtext(:sid))"),
            {"ns": SCHEDULER_SOURCE_LOCK_NS, "sid": source_id},
        )
        acquired = bool(row.scalar())
        yield acquired
    finally:
        if acquired:
            try:
                await conn.execute(
                    _sa_text("SELECT pg_advisory_unlock(:ns, hashtext(:sid))"),
                    {"ns": SCHEDULER_SOURCE_LOCK_NS, "sid": source_id},
                )
            except Exception as unlock_exc:  # noqa: BLE001
                logger.warning(
                    "source_lock_unlock_failed", source_id=source_id, error=str(unlock_exc)
                )
        await conn.close()


async def run_incremental_for_all_sources(
    output_dir: str = "./output",
    *,
    state_repo: IngestionStateRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
) -> dict[str, Any]:
    """
    Run incremental pipeline for every active source.

    For each source with status='active':
      1. Run full pipeline in incremental mode
      2. Record attempt with details in source_attempts
      3. Decide whether retopicization is needed (threshold strategy)

    Errors in one source do not block others.

    Concurrency model (post BUG-013 fix):

    The outer scope opens ONE short-lived ``ingestion_state_repo``
    session purely for the initial ``list_sources(status="active")``
    read; that session is closed BEFORE per-source tasks are spawned.
    Each ``_process_source`` task then opens its own
    ``ingestion_and_processing_repos`` session triple at the start of
    its body — no ``AsyncSession`` is shared across ``asyncio.gather``
    tasks (SQLAlchemy 2.x concurrency invariant).

    Optional ``state_repo`` / ``processed_repo`` kwargs are a
    test-injection legacy path. Zero production callers exercise it;
    when provided, both the outer list_sources read AND every per-task
    body operate on those injected repos and the caller is responsible
    for concurrency-safety (typical test fixtures use ``AsyncMock``
    which is concurrency-safe).

    Returns:
        Aggregate statistics across all sources.
    """
    from tg_parser.services.pipeline_service import run_full_pipeline

    aggregate: dict[str, Any] = {
        "sources_total": 0,
        "sources_succeeded": 0,
        "sources_failed": 0,
        "sources_degraded": 0,
        "sources_skipped": 0,
        "sources_lock_contended": 0,
        "total_new_messages": 0,
        "total_processed": 0,
        "retopicized_sources": [],
        "errors": {},
        "started_at": datetime.now(UTC).isoformat(),
        "duration_seconds": 0,
    }
    start_time = time.time()

    injected_repos = state_repo is not None and processed_repo is not None

    # BUG-013: open the OUTER state session purely for the initial
    # list_sources read, then close it before fanning out per-task work.
    # If repos are injected (test legacy path), reuse them for the
    # read instead of opening a fresh session.
    if injected_repos:
        sources = await state_repo.list_sources(status="active")
    else:
        async with ingestion_state_repo() as (outer_state_repo, _outer_db):
            sources = await outer_state_repo.list_sources(status="active")
        # outer session closed here; per-task code below opens its own.

    aggregate["sources_total"] = len(sources)

    if not sources:
        logger.info("No active sources found — nothing to do")
        return aggregate

    max_concurrent = settings.scheduler_max_concurrent_sources
    logger.info(
        "Incremental pipeline: found %d active source(s), max_concurrent=%d",
        len(sources),
        max_concurrent,
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process_source(source):
        source_start = time.time()
        source_id = source.source_id
        channel_id = normalize_channel_id(source.channel_id) or source.channel_id
        stage_errors: list[tuple[str, Exception]] = []
        stages_ok: list[str] = []
        degraded_reason: str | None = None

        # BUG-014 / BUG-014B defense-in-depth. Post-PR-#79 + Option B
        # (BUG-014B), ``SAIngestionStateRepo._row_to_source`` returns
        # ``rate_limit_until`` as tz-aware UTC, so this call is normally
        # an identity. Kept as belt-and-suspenders coerce that protects
        # any future refactor accidentally bypassing the storage layer
        # (e.g. raw SQL → direct ``Source`` construction in a test
        # fixture; also guarantees the PR #79 closure test
        # ``test_bug014_naive_rate_limit_until_does_not_crash`` stays
        # GREEN — it feeds a naive ``rate_limit_until`` directly).
        rate_limit_until = coerce_aware_utc(source.rate_limit_until)
        rate_limited = rate_limit_until is not None and rate_limit_until > datetime.now(UTC)
        if rate_limited:
            # AGGREGATE-MUTATION CONTRACT (BUG-013 fix, applies throughout
            # this closure):
            #
            # ``aggregate`` is mutated within per-task scope. asyncio
            # cooperative scheduling guarantees no preemption between
            # ``await`` points, so every single-statement mutation below
            # (``counter += 1``, ``list.append(...)``, ``dict[key] = ...``)
            # is atomic from the perspective of sibling tasks. Each task
            # also mutates ``aggregate["errors"]`` only under its own
            # ``source_id`` key, so even an interleaving across ``await``
            # would not produce a semantic race.
            #
            # Do NOT re-introduce ``repo_lock``. The session-isolation
            # contract (per-task ``ingestion_and_processing_repos``) is
            # the source of truth; aggregate mutations remain lock-free
            # by design.
            aggregate["sources_skipped"] += 1
            logger.info(
                "Skipping source %s until %s (rate-limited)",
                source_id,
                source.rate_limit_until.isoformat(),
            )
            return

        logger.info("Processing source %s (channel=%s)", source_id, channel_id)

        # BUG-013: per-task session triple. Each ``_process_source``
        # invocation owns its own ``(state_repo, processed_repo, db)``
        # — SQLAlchemy 2.x AsyncSession is not safe to share across
        # asyncio tasks (prior shared-session pattern produced
        # IllegalStateChangeError + cascading InterfaceError on every
        # tick). AsyncExitStack reads the test-injection branch as a
        # no-op stack, keeping a single structural shape.
        async with contextlib.AsyncExitStack() as task_stack:
            if injected_repos:
                task_state_repo: IngestionStateRepo = state_repo  # type: ignore[assignment]
                task_processed_repo: ProcessedDocumentRepo = processed_repo  # type: ignore[assignment]
            else:
                task_state_repo, task_processed_repo, _db = await task_stack.enter_async_context(
                    ingestion_and_processing_repos()
                )

            # Fix 4: per-source advisory lock held for the whole tick. If another
            # in-flight tick already owns this source (max_instances=2 overlap /
            # coalesced misfire / overrun), skip it rather than double-process and
            # duplicate Telegram/LLM work. The lock auto-releases when task_stack
            # unwinds (connection unlock + close).
            source_lock_acquired = await task_stack.enter_async_context(
                _source_processing_lock(source_id)
            )
            if not source_lock_acquired:
                aggregate["sources_skipped"] += 1
                logger.info(
                    "source_already_in_flight_skipped",
                    source_id=source_id,
                    channel_id=channel_id,
                )
                return

            # BUG-024: synchronous commit of ``last_attempt_at`` BEFORE
            # the first pipeline ``await``. After the BUG-013 per-task
            # session fix this is naturally safe — each task owns its
            # session, so the commit cannot race siblings. The later
            # ``record_attempt`` write in ``finally`` will refresh this
            # value (monotonically advancing); the redundant write is
            # harmless.
            await task_state_repo.mark_attempt_started(source_id)

            docs_before = await task_processed_repo.list_by_channel(channel_id)

            try:
                async with semaphore:
                    try:
                        # BUG-068 (A2): per-source watchdog. Bound the whole
                        # pipeline run with a wall-clock budget so a stuck/slow
                        # source times out, releases the scheduler slot, and is
                        # recorded as a failed tick instead of wedging every
                        # other source indefinitely. asyncio.wait_for cancels
                        # the in-flight coroutine on timeout (clean cancellation
                        # of in-flight LLM/DB work).
                        stats = await asyncio.wait_for(
                            run_full_pipeline(
                                source_id=source_id,
                                output_dir=output_dir,
                                mode="incremental",
                                skip_topicize=True,
                                concurrency=settings.processing_concurrency,
                            ),
                            timeout=_setting_number(
                                settings.scheduler_source_timeout_s, None
                            ),
                        )
                        # BUG-073 (F1): the full pipeline short-circuits with a
                        # benign ``skipped_locked`` result when another run holds
                        # the per-channel processing lock. Treat it as a benign
                        # skip — ingestion still ran, but processing/export did
                        # NOT — so it is NOT recorded as a successful process/
                        # export tick (and NOT as a failure). The downstream
                        # new_doc_refs incremental naturally no-ops (0 new docs).
                        if stats.get("skipped_locked"):
                            stages_ok.append("ingest")
                            logger.info(
                                "source_processing_skipped_lock_held",
                                source_id=source_id,
                                channel_id=channel_id,
                            )
                        else:
                            stages_ok.extend(["ingest", "process", "export"])
                    except SessionLockContentionError as exc:
                        # BUG-070 (H1): a sibling source held the Telethon
                        # session lock past the wait budget. This is BENIGN —
                        # the source merely waited, nothing is stuck — so it is
                        # recorded as the DISTINCT session_lock_contention
                        # outcome (retry next tick), NOT pipeline_timeout and
                        # NOT a hard failure. The finally block treats a
                        # contention-only tick as a no-penalty skip.
                        stage_errors.append(("session_lock_contention", exc))
                        logger.warning(
                            "source_session_lock_contention",
                            source_id=source_id,
                            channel_id=channel_id,
                            wait_timeout_s=settings.scheduler_session_lock_wait_timeout_s,
                        )
                        raise
                    except TimeoutError as exc:
                        stage_errors.append(("pipeline_timeout", exc))
                        logger.error(
                            "source_processing_timeout",
                            source_id=source_id,
                            channel_id=channel_id,
                            timeout_s=settings.scheduler_source_timeout_s,
                        )
                        raise
                    except Exception as exc:
                        stage_errors.append(("pipeline", exc))
                        raise

                new_messages = 0
                if stats.get("ingest"):
                    new_messages = stats["ingest"].get("posts_collected", 0) + stats["ingest"].get(
                        "comments_collected", 0
                    )

                new_processed = 0
                if stats.get("process"):
                    new_processed = stats["process"].get("processed_count", 0)

                aggregate["total_new_messages"] += new_messages
                aggregate["total_processed"] += new_processed

                docs_after = await task_processed_repo.list_by_channel(channel_id)

                # BUG-067 (B1): detect a degraded processing tick. The per-doc
                # billing/parse failures are swallowed inside
                # _process_batch_parallel (return None), so run_full_pipeline
                # raises no exception and the tick would otherwise record as a
                # healthy success even when it processed 0-of-N. Reconstruct the
                # outcome from the processing stats: if it attempted >0 docs and
                # the failed/attempted ratio meets the configured threshold,
                # mark the tick degraded so it is surfaced as a non-success.
                process_stats = stats.get("process") or {}
                p_total = process_stats.get("total_count", 0) or 0
                p_skipped = process_stats.get("skipped_count", 0) or 0
                p_failed = process_stats.get("failed_count", 0) or 0
                p_processed = process_stats.get("processed_count", 0) or 0
                # Fix 2 (HIGH): the degraded denominator must be docs ATTEMPTED
                # this tick, not the whole channel. run_processing loads the
                # entire channel and re-appends already-processed docs into
                # processed_count without counting them as skipped, so
                # (total - skipped) ≈ total_raw and fail_ratio is diluted to ~0
                # on any channel with a backlog — B1 would never fire. Prefer the
                # pipeline's attempted_count (len(to_process): post-exists,
                # post-cooldown); fall back to the legacy formula only if absent.
                attempted_count = process_stats.get("attempted_count")
                if attempted_count is None:
                    attempted = p_total - p_skipped
                else:
                    attempted = attempted_count
                degraded_ratio = _setting_number(
                    settings.scheduler_degraded_failure_ratio, 0.5
                )
                if attempted > 0:
                    fail_ratio = p_failed / attempted
                    if fail_ratio >= degraded_ratio:
                        degraded_reason = (
                            f"degraded processing tick: processed {p_processed} of "
                            f"{attempted} attempted (failed={p_failed}, "
                            f"fail_ratio={fail_ratio:.0%}, threshold="
                            f"{degraded_ratio:.0%})"
                        )
                        logger.warning(
                            "source_tick_degraded",
                            source_id=source_id,
                            channel_id=channel_id,
                            attempted=attempted,
                            processed=p_processed,
                            failed=p_failed,
                            fail_ratio=round(fail_ratio, 3),
                        )

                # BUG-067 (billing-pause): the parallel processing path no longer
                # raises AnthropicBillingError (it would lose completed/paid work);
                # it surfaces a billing-block count in the process stats instead.
                # Promote that into stage_errors[0] so the existing
                # _record_and_pause_on_billing fires (source paused per
                # billing_block_backoff_s) and the tick is labelled "degraded"
                # (not silently successful) without crashing sibling sources.
                billing_blocked_count = int(process_stats.get("billing_blocked_count", 0) or 0)
                if billing_blocked_count > 0 and not any(
                    isinstance(e, AnthropicBillingError) for _, e in stage_errors
                ):
                    stage_errors.insert(
                        0,
                        (
                            "process_billing_blocked",
                            AnthropicBillingError(
                                f"processing billing-blocked on {billing_blocked_count} doc(s)"
                            ),
                        ),
                    )
                    logger.error(
                        "source_tick_billing_blocked",
                        source_id=source_id,
                        channel_id=channel_id,
                        billing_blocked=billing_blocked_count,
                    )

                # BUG-067/B3 + BUG-069: per-channel processed/raw coverage gauge.
                # The denominator MUST be the TRUE raw backlog size, not the
                # process stage's total_count. After BUG-069 the process stage
                # loads only a BOUNDED unprocessed window
                # (processing_tick_batch_size), so total_count is the window size
                # — using it would yield coverage ratios >1 and false
                # channel_coverage_low alerts. run_processing now surfaces the
                # real COUNT(*) via raw_total_count; fall back to p_total only for
                # legacy stat shapes that predate that key.
                raw_total = process_stats.get("raw_total_count")
                if raw_total is None:
                    raw_total = p_total
                processed_total = len(docs_after)
                if raw_total and raw_total > 0:
                    # BUG-069 MEDIUM: clamp to 1.0. raw_total is a point-in-time
                    # COUNT(*) of the raw backlog while processed_total counts the
                    # processed_documents that survive; if raw rows were pruned /
                    # deleted (retention, channel cleanup) after their docs were
                    # produced, processed_total can exceed the stale denominator
                    # and emit a ratio >1 (and a spurious channel_coverage_low /
                    # gauge value). The min guards that; divide-by-zero is guarded
                    # by the `raw_total > 0` check above.
                    coverage_ratio = min(1.0, processed_total / raw_total)
                    coverage_alert = _setting_number(
                        settings.scheduler_coverage_alert_ratio, 0.8
                    )
                    from tg_parser.api.metrics import set_channel_coverage

                    set_channel_coverage(channel_id=channel_id, ratio=coverage_ratio)
                    is_low = coverage_ratio < coverage_alert
                    (logger.warning if is_low else logger.info)(
                        "channel_coverage_low" if is_low else "channel_coverage",
                        source_id=source_id,
                        channel_id=channel_id,
                        raw_messages=raw_total,
                        processed_documents=processed_total,
                        coverage_ratio=round(coverage_ratio, 4),
                        coverage_percent=round(coverage_ratio * 100, 2),
                        alert_threshold=coverage_alert,
                    )

                new_doc_refs = [
                    d.source_ref
                    for d in docs_after
                    if d.source_ref not in {dd.source_ref for dd in docs_before}
                ]
                if new_doc_refs:
                    logger.info(
                        "Running incremental topicization for %s (%d new docs)",
                        source_id,
                        len(new_doc_refs),
                    )
                    try:
                        from tg_parser.services.topicization_service import (
                            run_incremental_topicization,
                        )

                        incr_result = await run_incremental_topicization(
                            channel_id,
                            new_doc_refs,
                        )
                        stages_ok.append("incremental_topicization")
                        aggregate["retopicized_sources"].append(source_id)
                        logger.info(
                            "Incremental topicization for %s: "
                            "assigned=%d, unassigned=%d, "
                            "coverage %.1f%% -> %.1f%%",
                            source_id,
                            len(incr_result.assigned_keyword),
                            len(incr_result.unassignable),
                            incr_result.coverage_before,
                            incr_result.coverage_after,
                        )

                        try:
                            from tg_parser.services.embedding_service import run_topic_embedding

                            await run_topic_embedding(channel_id=channel_id, force=False)
                        except Exception as te:
                            logger.warning(
                                "Topic embedding failed for %s: %s",
                                source_id,
                                te,
                            )
                    except Exception as e:
                        stage_errors.append(("incremental_topicization", e))
                        logger.error(
                            "Incremental topicization failed for %s: %s",
                            source_id,
                            e,
                            exc_info=True,
                        )

                    # BUG-064: message-embedding write path. The near-duplicate
                    # observer below loads per-doc MESSAGE embeddings; without
                    # this step they are absent and every new doc is skipped
                    # (skipped_no_embedding++ → tg_dedup_near_duplicates_detected_total
                    # never moves, the symptom reported since the 2026-06-19
                    # deploy). Runs AFTER the topic-card embedding step and
                    # BEFORE the near-dup hook so the observer has embeddings to
                    # read. Mirror the near-dup hook's silent-log contract: this
                    # is post-processing, so a non-billing failure must NOT
                    # pollute stage_errors (otherwise success = not stage_errors
                    # would lie about upstream stages).
                    try:
                        from tg_parser.services.embedding_service import (
                            run_incremental_embedding,
                        )

                        emb_summary = await run_incremental_embedding(new_doc_refs)
                        logger.info(
                            "incremental_embedding source=%s embedded=%d total=%d",
                            source_id,
                            emb_summary["embedded_count"],
                            emb_summary["total_count"],
                        )
                    except Exception as emb_exc:
                        logger.exception(
                            "incremental_embedding_failed source=%s error=%s",
                            source_id,
                            emb_exc,
                        )

                    # F5-B Phase 0: near-duplicate observation-only counter
                    # (ADR-0016). Runs in the living loop after the embedding
                    # write path; OBSERVATION-ONLY (never hides/mutates docs)
                    # and graceful — like the F5-C/F11 hooks, a non-billing
                    # failure must NOT pollute stage_errors (post-processing
                    # must not lie about upstream stages via
                    # success = not stage_errors).
                    try:
                        from tg_parser.services.near_duplicate_service import (
                            run_near_duplicate_check_for_channel,
                        )

                        nd_summary = await run_near_duplicate_check_for_channel(
                            channel_id=channel_id,
                            new_doc_refs=new_doc_refs,
                        )
                        logger.info(
                            "near_duplicate_check source=%s checked=%d intra=%d "
                            "cross=%d skipped_no_embedding=%d",
                            source_id,
                            nd_summary["checked"],
                            nd_summary["intra"],
                            nd_summary["cross"],
                            nd_summary["skipped_no_embedding"],
                        )
                    except Exception as nd_exc:
                        logger.exception(
                            "near_duplicate_check_failed source=%s error=%s",
                            source_id,
                            nd_exc,
                        )

                # F5-C: Evolving Topic Summaries hook. Decoupled from the
                # ``if new_doc_refs:`` block (mirrors ENH-001 for the F11
                # watchlist below) so the age/freshness trigger
                # (RESUMMARIZE_MAX_AGE_DAYS) can fire on quiet channels that
                # never cross the counter threshold. Runs on EVERY tick, still
                # BEFORE the watchlist check so the matcher scores against the
                # freshest summary when there ARE new docs. Mirror F11's
                # silent-log contract: F5-C is post-processing, so non-billing
                # failures MUST NOT pollute stage_errors — otherwise
                # success=False (line `success = not stage_errors` below) would
                # lie about upstream stages. Only AnthropicBillingError
                # escalates so the existing _pause_source_for_billing fires
                # (Decision #13 + gotcha #16).
                try:
                    rs_summary = await run_resummarize_for_channel(channel_id=channel_id)
                    if rs_summary["resummarized"] > 0:
                        stages_ok.append("resummarize")
                    logger.info(
                        "f5c_resummarize source=%s candidates=%d "
                        "resummarized=%d skipped=%d tokens=%d",
                        source_id,
                        rs_summary["candidates"],
                        rs_summary["resummarized"],
                        rs_summary["skipped"],
                        rs_summary["tokens"],
                    )
                except AnthropicBillingError as billing_exc:
                    stage_errors.append(("resummarize", billing_exc))
                    logger.warning(
                        "f5c_resummarize_billing_error source=%s — pausing source",
                        source_id,
                    )
                except Exception as rs_exc:
                    logger.exception(
                        "f5c_resummarize_failed source=%s error=%s",
                        source_id,
                        rs_exc,
                    )

                # ENH-001: the watchlist check runs OUTSIDE the
                # ``if new_doc_refs:`` block above — on EVERY tick, including
                # quiet ones — so ``last_checked_at`` reflects evaluation
                # cadence (matcher liveness), not "last tick with new docs".
                # Ordering is preserved: topicization/embedding (gated on new
                # docs) and resummarize still run first, so when there ARE new
                # docs the matcher still scores against the freshest summary.
                try:
                    wl_summary = await run_watchlist_check_for_channel(
                        channel_id=channel_id,
                        new_doc_refs=new_doc_refs,
                    )
                    if wl_summary["inserted"]:
                        stages_ok.append("watchlist_check")
                    logger.info(
                        "watchlist_check source=%s inserted=%d skipped=%s",
                        source_id,
                        wl_summary["inserted"],
                        wl_summary["skipped_reason"],
                    )
                except AnthropicBillingError as wl_billing_exc:
                    # TD-05 / merged-plan C-006: F11 watchlist embeds and
                    # may invoke an Anthropic-backed embedding pipeline.
                    # Pre-TD-05 a generic ``except Exception`` swallowed
                    # the billing error → metric not recorded, source not
                    # paused, every subsequent tick re-incurred the
                    # billing call. Mirror the F5-C resummarize hook
                    # contract above (Decision #13 + Gotcha #16).
                    stage_errors.append(("watchlist_check", wl_billing_exc))
                    logger.warning(
                        "watchlist_check_billing_error source=%s — pausing source",
                        source_id,
                    )
                except Exception as wl_exc:
                    logger.exception(
                        "watchlist_check_failed source=%s error=%s",
                        source_id,
                        wl_exc,
                    )

                # BUG-076 §5.0: standing full-topicization RESUME driver. Runs on
                # EVERY tick and BEFORE the BUG-075 reconcile hook so a live
                # ``topicization:full_checkpoint:`` marker (a resumable full run
                # that halted at a chunk/budget boundary or crashed mid-run) is
                # driven forward one bounded invocation. MANDATORY: the only other
                # full-path driver, ``should_reescalate``, fires ONLY at 0 cards,
                # so once chunk 1 lands (cards > 0) a partial run would otherwise
                # stall forever. Best-effort like the F5-C / F11 / reconcile hooks:
                # a failure here (including billing) must NEVER pollute
                # ``stage_errors`` (``success = not stage_errors`` must reflect
                # only the upstream ingest/process/export stages) and must NEVER
                # crash the tick. No-op (dark) unless
                # ``topicization_full_resume_enabled`` is set.
                try:
                    from tg_parser.services.topicization_service import (
                        run_full_topicization_resume_for_channel,
                    )

                    resume_summary = await run_full_topicization_resume_for_channel(
                        channel_id=channel_id,
                    )
                    if resume_summary.get("resumed"):
                        stages_ok.append("full_topicization_resume")
                        logger.info(
                            "bug076_full_resume source=%s resumed=%s chunks=%s/%s "
                            "topics=%s reason=%s",
                            source_id,
                            resume_summary.get("resumed"),
                            resume_summary.get("chunks_done"),
                            resume_summary.get("chunks_total"),
                            resume_summary.get("topics_count"),
                            resume_summary.get("skipped_reason"),
                        )
                except Exception as resume_exc:
                    logger.exception(
                        "bug076_full_resume_failed source=%s error=%s",
                        source_id,
                        resume_exc,
                    )

                # BUG-075: standing per-tick coverage reconciliation. Runs on
                # EVERY tick (learning 1 — convergent/standing, NOT gated on
                # ``if new_doc_refs:``) so processed-but-never-topicized docs
                # (CLI ``process``, ``skip_topicize`` runs, crash-between-stages,
                # or the F1 lock-skip widening) eventually become covered. It
                # feeds only NOT-YET-ATTEMPTED uncovered docs to a CHEAP-ONLY
                # incremental run that CANNOT re-escalate to a full
                # re-topicization (learning 5) and marks each fed doc so the
                # steady-state cost is ~0 (learning 2/3). Mirrors the F5-C / F11
                # hook contract: post-processing, so a failure here — INCLUDING
                # a billing error — must NEVER pollute ``stage_errors`` (which
                # would make ``success = not stage_errors`` lie about the
                # upstream ingest/process/export stages) and must NEVER crash the
                # tick. The main processing path owns billing pausing; a bounded
                # (``topicization_reconcile_max_docs``) reconcile slice cannot
                # storm even on a freshly-refilled balance.
                try:
                    from tg_parser.services.topicization_service import (
                        run_reconciliation_for_channel,
                    )

                    rec_summary = await run_reconciliation_for_channel(
                        channel_id=channel_id,
                    )
                    logger.info(
                        "bug075_reconcile source=%s candidates=%d fed=%d "
                        "deferred=%s tokens=%d reason=%s",
                        source_id,
                        rec_summary["candidates"],
                        rec_summary["fed"],
                        rec_summary["deferred"],
                        rec_summary["tokens"],
                        rec_summary["skipped_reason"],
                    )
                except Exception as rec_exc:
                    logger.exception(
                        "bug075_reconcile_failed source=%s error=%s",
                        source_id,
                        rec_exc,
                    )

                logger.info(
                    "Source %s completed: new_messages=%d, processed=%d",
                    source_id,
                    new_messages,
                    new_processed,
                )

            except SessionLockContentionError:
                # BUG-070 (H1): benign contention re-raised from the inner
                # handler — already recorded in stage_errors; do NOT log it as a
                # source failure. The finally block resolves it to the
                # session_lock_contention outcome.
                pass
            except Exception as exc:
                if not stage_errors:
                    stage_errors.append(("unknown", exc))
                logger.error("Source %s failed: %s", source_id, exc, exc_info=True)
            finally:
                # BUG-070 (H1): a tick whose ONLY error is session-lock
                # contention is benign — the source simply waited on a busy
                # Telethon session and made no progress this tick. Surface it as
                # a DISTINCT session_lock_contention outcome and retry next tick
                # WITHOUT recording a failed attempt (no fail_count bump, no
                # last_error pollution, no last_success_at advance), mirroring
                # the rate-limited / already-in-flight benign-skip precedent.
                contention_only = bool(stage_errors) and all(
                    isinstance(e, SessionLockContentionError) for _, e in stage_errors
                )
                if contention_only:
                    aggregate["sources_lock_contended"] += 1
                    logger.info(
                        "source=%s: outcome=session_lock_contention "
                        "(benign — sibling held the Telethon session past the "
                        "wait budget; retry next tick)",
                        source_id,
                    )
                else:
                    # Per-task state_repo: BUG-013 isolation makes the
                    # billing-pause upsert + the record_attempt write commit
                    # cleanly on this task's own session.
                    await _record_and_pause_on_billing(stage_errors, source, task_state_repo)

                    # BUG-067 outcome resolution. Precedence:
                    #   1. a real (non-billing) stage error  -> failure
                    #   2. a billing block (temporary)        -> degraded (+ paused)
                    #   3. a degraded-ratio tick (B1)         -> degraded
                    #   4. otherwise                          -> success
                    # Billing is treated as degraded (not a hard failure) because it
                    # is temporary and the source is already paused/backed-off; this
                    # also avoids double-counting a billing tick that ALSO tripped the
                    # B1 degraded ratio.
                    hard_errors = [
                        (s, e)
                        for s, e in stage_errors
                        if not isinstance(e, AnthropicBillingError)
                    ]
                    billing_exc = next(
                        (e for _, e in stage_errors if isinstance(e, AnthropicBillingError)),
                        None,
                    )
                    billing_stage = next(
                        (s for s, e in stage_errors if isinstance(e, AnthropicBillingError)),
                        None,
                    )
                    is_degraded_only = not stage_errors and degraded_reason is not None
                    success = not stage_errors and degraded_reason is None

                    record_exc: Exception | None
                    if hard_errors:
                        record_stage = hard_errors[0][0]
                        record_exc = hard_errors[0][1]
                    elif billing_exc is not None:
                        record_stage = billing_stage or "process_billing_blocked"
                        record_exc = billing_exc
                    elif is_degraded_only:
                        record_stage = "process_degraded"
                        record_exc = DegradedProcessingTick(degraded_reason)
                    else:
                        record_stage = None
                        record_exc = None

                    if success:
                        outcome = "success"
                        aggregate["sources_succeeded"] += 1
                    elif hard_errors:
                        outcome = "failure"
                        aggregate["sources_failed"] += 1
                        aggregate["errors"][source_id] = str(record_exc)
                    else:
                        # billing block or B1 degraded ratio — both surface as degraded
                        outcome = "degraded"
                        aggregate["sources_failed"] += 1
                        aggregate["sources_degraded"] += 1
                        aggregate["errors"][source_id] = str(record_exc)

                    await _safe_record_attempt(
                        state_repo=task_state_repo,
                        source_id=source_id,
                        success=success,
                        failed_stage=record_stage,
                        exc=record_exc,
                        duration=time.time() - source_start,
                        details={
                            "trigger": "scheduled",
                            "outcome": outcome,
                            "degraded_reason": degraded_reason,
                            "new_messages": locals().get("new_messages", 0),
                            "new_processed": locals().get("new_processed", 0),
                            "duration_seconds": round(time.time() - source_start, 2),
                            "pipeline_stats": _safe_stats(locals().get("stats", {})),
                        },
                    )
                    logger.info(
                        "source=%s: stages_ok=%s, stages_failed=%s, outcome=%s",
                        source_id,
                        stages_ok,
                        [s for s, _ in stage_errors],
                        outcome,
                    )

    # BUG-013: gather with ``return_exceptions=True`` so that an unhandled
    # escape from one task's body (e.g. a future bug class we haven't
    # foreseen) does NOT cancel siblings. Each ``_process_source`` body
    # already wraps its work in ``try/except/finally`` — the cases we
    # catch here are escapes from that wrapper. We log one structured
    # ``logger.error`` line per escape; no Prometheus counter yet (defer
    # to a follow-up housekeeping sprint per planning § 7).
    results = await asyncio.gather(*[_process_source(s) for s in sources], return_exceptions=True)
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            logger.error(
                "scheduler_unhandled_escape source_id=%s error=%s",
                source.source_id,
                result,
                exc_info=(type(result), result, result.__traceback__),
            )

    aggregate["duration_seconds"] = round(time.time() - start_time, 2)
    aggregate["finished_at"] = datetime.now(UTC).isoformat()

    logger.info(
        "Incremental pipeline completed: succeeded=%d, failed=%d, degraded=%d, "
        "lock_contended=%d, duration=%.2fs",
        aggregate["sources_succeeded"],
        aggregate["sources_failed"],
        aggregate["sources_degraded"],
        aggregate["sources_lock_contended"],
        aggregate["duration_seconds"],
    )

    return aggregate


async def run_incremental_for_source(
    source_id: str,
    output_dir: str = "./output",
) -> dict[str, Any]:
    """
    Run incremental pipeline for a single source.

    Convenience wrapper for manual/CLI invocations targeting one source.
    """
    from tg_parser.services.pipeline_service import run_full_pipeline

    logger.info("Running incremental pipeline for source: %s", source_id)
    stats = await run_full_pipeline(
        source_id=source_id,
        output_dir=output_dir,
        mode="incremental",
        concurrency=settings.processing_concurrency,
    )
    return stats


async def get_scheduler_status(
    *,
    repo: IngestionStateRepo | None = None,
) -> dict[str, Any]:
    """
    Return status information about active sources and last attempts.
    """
    async with contextlib.AsyncExitStack() as stack:
        if repo is None:
            repo, _db = await stack.enter_async_context(ingestion_state_repo())
        state_repo = repo
        sources = await state_repo.list_sources()

        source_list = []
        for s in sources:
            source_list.append(
                {
                    "source_id": s.source_id,
                    "channel_id": s.channel_id,
                    "status": s.status,
                    "poll_interval_seconds": s.poll_interval_seconds
                    or settings.scheduler_default_interval,
                    "last_attempt_at": s.last_attempt_at.isoformat() if s.last_attempt_at else None,
                    "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
                    "fail_count": s.fail_count,
                    "last_error": s.last_error,
                }
            )

        return {
            "scheduler_enabled": settings.scheduler_enabled,
            "default_interval_seconds": settings.scheduler_default_interval,
            "retopicize_threshold": settings.scheduler_retopicize_threshold,
            "sources": source_list,
        }


def run_scheduler_blocking(
    interval_seconds: int | None = None,
) -> None:
    """
    Run the scheduler in daemon/blocking mode with graceful shutdown.

    This is meant for the CLI ``tg-parser scheduler start`` command.
    It sets up an APScheduler, registers the incremental pipeline job,
    and blocks until SIGTERM/SIGINT.
    """
    asyncio.run(_run_scheduler_async(interval_seconds))


async def _run_scheduler_async(
    interval_seconds: int | None = None,
) -> None:
    """Async entry point for the scheduler daemon."""
    from tg_parser.services.background_scheduler import (
        BackgroundScheduler,
        setup_default_tasks,
    )

    interval = interval_seconds or settings.scheduler_default_interval

    scheduler = BackgroundScheduler()

    setup_default_tasks(
        scheduler,
        incremental_pipeline_interval=interval,
    )

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal — stopping scheduler")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Trigger the first run immediately
    scheduler.start()
    logger.info("Scheduler daemon started (interval=%ds). Press Ctrl+C to stop.", interval)

    # Run the pipeline once right away before the first scheduled tick
    try:
        await run_incremental_for_all_sources()
    except Exception as exc:
        logger.error("Initial incremental run failed: %s", exc, exc_info=True)

    await shutdown_event.wait()

    scheduler.shutdown(wait=True)
    logger.info("Scheduler daemon stopped")


# ---------------------------------------------------------------------------
# APScheduler task entry points
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# F6 — Scheduled Digests: scheduler entry point + reconciliation
# ---------------------------------------------------------------------------


async def run_scheduled_digests_task(subscription_id: str) -> dict[str, Any]:
    """APScheduler entry point — generate and deliver one digest tick.

    Looks up the subscription, builds a ``DigestService`` against the live
    repos / prompt loader / LLM factory, and dispatches to
    ``DigestService.run_for_subscription``. The cursor is advanced inside the
    service (only on successful delivery / successful empty-skip).

    Returns a small status dict for logging / metrics. Never raises — failures
    are logged and surfaced via the return value so the scheduler wrapper does
    not retry storms.
    """
    from tg_parser.bot.runtime import get_bot
    from tg_parser.processing.llm.factory import (
        create_llm_client,
        resolve_llm_config,
    )
    from tg_parser.processing.prompt_loader import PromptLoader
    from tg_parser.services.db_context import (
        digest_subscription_repo,
        ingestion_and_processing_repos,
    )
    from tg_parser.services.digest_service import DigestService

    logger.info("digest_task_triggered", subscription_id=subscription_id)

    prompt_loader = PromptLoader(
        prompts_dir=str(settings.prompts_dir) if settings.prompts_dir is not None else None,
    )

    def _llm_factory():
        provider, api_key, model = resolve_llm_config("digest")
        return create_llm_client(provider=provider, api_key=api_key, model=model)

    # Resolve the subscription inside the same DB context that the service
    # will use, so an MCP-side delete/pause that lands between fetch and run
    # surfaces as "not_found" / "inactive" instead of a stale delivery.
    async with (
        ingestion_and_processing_repos() as (_state_repo, processed_repo, _db2),
        digest_subscription_repo() as (sub_repo, _db3),
    ):
        sub = await sub_repo.get(subscription_id)

        if sub is None:
            logger.warning("digest_subscription_not_found", subscription_id=subscription_id)
            return {"subscription_id": subscription_id, "status": "not_found"}

        if not sub.is_active:
            logger.info("digest_subscription_inactive", subscription_id=subscription_id)
            return {"subscription_id": subscription_id, "status": "inactive"}

        service = DigestService(
            processed_repo=processed_repo,
            subscription_repo=sub_repo,
            prompt_loader=prompt_loader,
            llm_client_factory=_llm_factory,
            max_docs_per_run=settings.digest_max_docs_per_run,
            first_run_lookback_hours=settings.digest_first_run_lookback_hours,
            message_max_chars=settings.digest_message_max_chars,
            max_message_parts=settings.digest_max_message_parts,
        )
        result = await service.run_for_subscription(sub, get_bot())

    return {
        "subscription_id": subscription_id,
        "status": (
            "delivery_failed"
            if result.delivery_failed
            else ("skipped" if result.skipped else "delivered")
        ),
        "docs_count": result.docs_count,
        "delivery_error": result.delivery_error,
    }


# ---------------------------------------------------------------------------
# F5-C — Evolving Topic Summaries: scheduler hook entry point
# ---------------------------------------------------------------------------


async def run_resummarize_for_channel(*, channel_id: str) -> dict[str, int]:
    """F5-C scheduler hook entry point. Mirrors the F11 hook contract.

    Builds a fresh :class:`ResummarizationService` against per-tick repos,
    dispatches candidates with all three caps (max topics / duration /
    tokens), then tears the service and the ``resummarization_repos``
    context down via ``try/finally`` so a partial failure does not leak a
    DB session or an LLM connection.

    Returns a small status dict suitable for structured logging::

        {"candidates": int, "resummarized": int, "skipped": int,
         "tokens": int, "duration_s": float}

    Failure semantics (Decision #13 + gotcha #16):

    - Non-billing exception **propagates** — caller wraps in
      ``except Exception`` + ``logger.exception`` (silent log; *NOT*
      added to ``stage_errors`` so source-attempt success is unaffected).
      F5-C is post-processing and one LLM hiccup must not lie about
      upstream stages via ``success = not stage_errors``.
    - :class:`AnthropicBillingError` propagates — caller catches it
      separately and pushes it into ``stage_errors`` so the existing
      :func:`_pause_source_for_billing` fires (the Anthropic budget is
      shared across stages, so a billing pause IS the right
      operational response).
    """
    from tg_parser.services.db_context import resummarization_repos
    from tg_parser.services.resummarization_service import ResummarizationService

    async with resummarization_repos() as (
        topic_card_repo,
        topic_bundle_repo,
        topic_card_version_repo,
        _db,
    ):
        service = ResummarizationService(
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            topic_card_version_repo=topic_card_version_repo,
        )
        try:
            return await service.run_for_channel(channel_id=channel_id)
        finally:
            await service.aclose()


# ---------------------------------------------------------------------------
# F11 — Topic Watchlist: scheduler hook entry point
# ---------------------------------------------------------------------------


async def run_watchlist_check_for_channel(
    *,
    channel_id: str,
    new_doc_refs: list[str],
) -> dict[str, Any]:
    """Run :meth:`WatchlistService.check_interests` for one channel/tick.

    Built as a standalone coroutine (not a method on ``WatchlistService``) so
    the scheduler can keep its repo lifetime contained: it opens a fresh
    ``watchlist_repos`` context, builds the service with a live OpenAI
    embedding client, dispatches notifications via ``get_bot()``, and tears
    everything down before returning.

    Returns a small status dict suitable for structured logging:
    ``{"inserted": int, "skipped_reason": str | None}``. The hook itself
    propagates exceptions (so ``service.aclose()`` and the
    ``watchlist_repos`` async-context can release resources via ``finally``);
    the surrounding scheduler call site in :func:`_process_source` wraps the
    invocation in ``try/except`` and logs the failure. Net effect: a
    watchlist outage never blocks ingestion (gotcha #10: graceful
    degradation, watchlist must never block the pipeline).

    ENH-001: there is intentionally NO ``if not new_doc_refs`` fast-path.
    The hook runs on EVERY tick — even quiet ones — so that
    :meth:`WatchlistService.check_interests` can stamp ``last_checked_at``
    on every active interest (matcher-liveness telemetry). When
    ``new_doc_refs`` is empty no scoring/notification work happens; only the
    freshness stamp fires. ``skipped_reason`` is ``"no_new_docs"`` for that
    quiet path so logs stay legible.
    """
    from tg_parser.bot.runtime import get_bot
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    async with watchlist_repos() as (
        interest_repo,
        match_repo,
        processed_doc_repo,
        embedding_repo,
        _db,
    ):
        service = make_watchlist_service(
            interest_repo=interest_repo,
            match_repo=match_repo,
            processed_doc_repo=processed_doc_repo,
            embedding_repo=embedding_repo,
        )
        try:
            inserted = await service.check_interests(
                channel_id=channel_id,
                new_doc_refs=new_doc_refs,
                bot=get_bot(),
            )
        finally:
            await service.aclose()

    return {
        "inserted": len(inserted),
        "skipped_reason": None if new_doc_refs else "no_new_docs",
    }


async def run_watchlist_batch_flush() -> dict[str, Any]:
    """Run :meth:`WatchlistService.flush_batch` once (F11 P2 / ADR-0014).

    Global cron flush task (registered by ``setup_default_tasks`` when
    ``settings.watchlist_batch_enabled`` is True). Mirrors
    :func:`run_watchlist_check_for_channel`: opens a fresh ``watchlist_repos``
    context, builds the service via :func:`make_watchlist_service`, dispatches
    pending batch-mode matches through the live ``get_bot()``, and tears
    everything down via ``finally`` so no OpenAI / DB resource leaks.

    Guards on bot availability — without a live ``Bot`` (e.g. the flush fires
    in a process where the bot has not started) there is no delivery channel,
    so the tick is a no-op (``skipped_reason="no_bot"``) and no matches are
    consumed (their ``notified=False`` watermark is preserved for the next
    flush). Returns a small status dict suitable for structured logging.
    """
    from tg_parser.bot.runtime import get_bot
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    bot = get_bot()
    if bot is None:
        logger.info("watchlist_batch_flush_skipped", reason="no_bot")
        return {"flushed": 0, "skipped_reason": "no_bot"}

    async with watchlist_repos() as (
        interest_repo,
        match_repo,
        processed_doc_repo,
        embedding_repo,
        _db,
    ):
        service = make_watchlist_service(
            interest_repo=interest_repo,
            match_repo=match_repo,
            processed_doc_repo=processed_doc_repo,
            embedding_repo=embedding_repo,
        )
        try:
            outcomes = await service.flush_batch(bot)
        finally:
            await service.aclose()

    sent = sum(1 for v in outcomes.values() if v == "sent")
    return {
        "flushed": sent,
        "interests": len(outcomes),
        "skipped_reason": None,
    }


async def reconcile_digest_subscriptions() -> dict[str, Any]:
    """Diff active subscriptions in the DB against scheduler jobs.

    Adds jobs for newly-created/activated subscriptions, removes jobs for
    deleted/paused ones. Designed to be invoked periodically inside the bot
    process so MCP-side mutations propagate without a restart.
    """
    from tg_parser.services.background_scheduler import (
        get_registered_digest_subscription_ids,
        register_digest_subscription,
        unregister_digest_subscription,
    )
    from tg_parser.services.db_context import digest_subscription_repo

    async with digest_subscription_repo() as (sub_repo, _db):
        active = await sub_repo.list_active()

    desired_ids = {sub.id for sub in active}
    registered_ids = get_registered_digest_subscription_ids()

    added: list[str] = []
    removed: list[str] = []
    failed: list[str] = []

    for sub in active:
        if sub.id in registered_ids:
            continue
        try:
            register_digest_subscription(sub)
            added.append(sub.id)
        except ValueError as exc:
            logger.warning(
                "digest_reconcile_register_failed",
                subscription_id=sub.id,
                error=str(exc),
            )
            failed.append(sub.id)

    for sub_id in registered_ids - desired_ids:
        if unregister_digest_subscription(sub_id, reason="reconcile"):
            removed.append(sub_id)

    if added or removed or failed:
        logger.info(
            "digest_reconcile",
            added=len(added),
            removed=len(removed),
            failed=len(failed),
        )

    return {
        "active_count": len(desired_ids),
        "added": added,
        "removed": removed,
        "failed": failed,
    }


async def cleanup_stale_idempotency_keys(*, ttl_hours: int = 24) -> dict[str, int]:
    """Hourly cleanup tick for the ``idempotency_keys`` table (ADR 0009, Q-OPEN-2).

    Deletes rows older than ``ttl_hours`` (default 24h; not env-configurable per
    sprint lock — KISS) and updates the ``tg_idempotency_keys_table_size``
    gauge with the post-cleanup row count so operators can alert on
    runaway cache growth.

    Returns a small status dict suitable for structured logging:
    ``{"deleted": int, "table_size": int}``. The cleanup is best-effort —
    a transient DB hiccup raises and the next tick will retry; we do
    not back-off ourselves because the cron trigger handles cadence.
    """
    from datetime import UTC, datetime, timedelta

    from tg_parser.api.metrics import set_idempotency_keys_table_size
    from tg_parser.services.db_context import idempotency_key_repo

    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    async with idempotency_key_repo() as (repo, _db):
        deleted = await repo.delete_older_than(cutoff)
        table_size = await repo.count()

    set_idempotency_keys_table_size(table_size)
    logger.info(
        "idempotency_keys_cleanup",
        deleted=deleted,
        table_size=table_size,
        ttl_hours=ttl_hours,
        cutoff=cutoff.isoformat(),
    )
    return {"deleted": deleted, "table_size": table_size}


async def incremental_pipeline_task() -> dict:
    """
    Periodic task: run incremental pipeline for all active sources.

    Registered in APScheduler via ``setup_default_tasks``.
    Metric recording is handled by ``BackgroundScheduler.add_task`` wrapper —
    do NOT call ``record_scheduler_task`` here to avoid double-counting.
    """
    logger.info("Incremental pipeline task triggered")
    result = await run_incremental_for_all_sources()

    logger.info(
        "Incremental pipeline task finished: succeeded=%d, failed=%d",
        result.get("sources_succeeded", 0),
        result.get("sources_failed", 0),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _retopicize_source(channel_id: str) -> None:
    """Run topicization + export for a single channel."""
    from tg_parser.services.topicization_service import run_topicization

    logger.info("Auto-retopicizing channel %s", channel_id)
    stats = await run_topicization(
        channel_id=channel_id,
        force=True,
        build_bundles=True,
    )
    logger.info(
        "Retopicization done for %s: topics=%d, bundles=%d",
        channel_id,
        stats["topics_count"],
        stats["bundles_count"],
    )


async def _safe_record_attempt(
    state_repo: IngestionStateRepo,
    source_id: str,
    success: bool,
    failed_stage: str | None,
    exc: Exception | None,
    duration: float,
    details: dict | None = None,
) -> None:
    """Record a source attempt, swallowing any secondary exceptions."""
    try:
        await state_repo.record_attempt(
            source_id=source_id,
            success=success,
            failed_stage=failed_stage,
            error_class=type(exc).__name__ if exc else None,
            error_message=_truncate_error_message(str(exc)) if exc else None,
            details=details or {"trigger": "scheduled", "duration_seconds": round(duration, 2)},
        )
    except Exception as inner:
        logger.error("Failed to record attempt for %s: %s", source_id, inner)


def _truncate_error_message(message: str, max_len: int = 4096) -> str:
    """Truncate ``error_message`` to the documented Sprint D.1 contract (4096 chars).

    The 4096-character cap is documented in CHANGELOG.md and
    ``docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`` (Sprint D.1 § 1).
    Earlier this helper silently dropped at 500, which was causing RCA evidence
    (Anthropic billing payloads, full Telegram exception strings, stack-trace
    fragments) to be lost in ``source_attempts.error_message``. See
    REVIEW_2026-04-26_MERGED_PLAN.md S-001 for context.
    """
    return message[:max_len]


async def _pause_source_for_billing(source, state_repo: IngestionStateRepo) -> None:
    source.rate_limit_until = datetime.now(UTC) + timedelta(
        seconds=settings.billing_block_backoff_s
    )
    await state_repo.upsert_source(source)
    logger.error(
        "anthropic_billing_source_paused",
        source_id=source.source_id,
        until=source.rate_limit_until.isoformat(),
        backoff_seconds=settings.billing_block_backoff_s,
    )


async def _record_and_pause_on_billing(
    stage_errors: list[tuple[str, Exception]],
    source: Any,
    state_repo: IngestionStateRepo,
) -> None:
    """If ``stage_errors[0]`` is an :class:`AnthropicBillingError`, record + pause.

    TD-05 / merged-plan C-006 + S-007: prior to this helper the
    ``finally`` block of ``_process_source`` had two consecutive ``if``
    guards with the same predicate (one for the metric increment, one
    for the source-pause), and the F11 watchlist hook had a generic
    ``except Exception`` that silently swallowed billing errors so this
    pair never fired for watchlist failures. Centralising both
    side-effects (metric + pause) here gives every scheduler hook a
    single, idempotent escalation point and removes the asymmetry
    between F5-C resummarize and F11 watchlist failure handling.

    Idempotent on empty/non-billing ``stage_errors`` — safe to call
    unconditionally from a ``finally`` block.

    Emits a structured ``anthropic_billing_pause_fired`` log line keyed
    by ``stage`` and ``source_id`` so log aggregators (Loki/ELK) can
    alert on the helper firing rather than on the underlying counter.
    """
    if not stage_errors:
        return
    first_stage, first_exc = stage_errors[0]
    if not isinstance(first_exc, AnthropicBillingError):
        return

    from tg_parser.api.metrics import record_anthropic_billing_block

    record_anthropic_billing_block(stage=first_stage)
    await _pause_source_for_billing(source, state_repo)
    logger.warning(
        "anthropic_billing_pause_fired",
        source_id=source.source_id,
        stage=first_stage,
        until=source.rate_limit_until.isoformat() if source.rate_limit_until else None,
    )


def _safe_stats(stats: dict) -> dict:
    """Extract serialisable subset of pipeline stats for storage."""
    safe: dict[str, Any] = {}
    for stage in ("ingest", "process", "topicize", "export"):
        if stats.get(stage):
            safe[stage] = {
                k: v
                for k, v in stats[stage].items()
                if isinstance(v, (int, float, str, bool, type(None)))
            }
    return safe
