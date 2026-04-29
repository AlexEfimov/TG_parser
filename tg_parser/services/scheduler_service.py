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
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.services.db_context import ingestion_and_processing_repos, ingestion_state_repo
from tg_parser.storage.ports import IngestionStateRepo, ProcessedDocumentRepo
from tg_parser.utils.channel_id import normalize_channel_id

logger = structlog.get_logger(__name__)


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

    Returns:
        Aggregate statistics across all sources.
    """
    from tg_parser.services.pipeline_service import run_full_pipeline

    aggregate: dict[str, Any] = {
        "sources_total": 0,
        "sources_succeeded": 0,
        "sources_failed": 0,
        "sources_skipped": 0,
        "total_new_messages": 0,
        "total_processed": 0,
        "retopicized_sources": [],
        "errors": {},
        "started_at": datetime.now(UTC).isoformat(),
        "duration_seconds": 0,
    }
    start_time = time.time()

    async with contextlib.AsyncExitStack() as stack:
        if state_repo is None or processed_repo is None:
            state_repo, processed_repo, _db = await stack.enter_async_context(
                ingestion_and_processing_repos()
            )
        sources = await state_repo.list_sources(status="active")
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
        repo_lock = asyncio.Lock()

        async def _process_source(source):
            source_start = time.time()
            source_id = source.source_id
            channel_id = normalize_channel_id(source.channel_id) or source.channel_id
            stage_errors: list[tuple[str, Exception]] = []
            stages_ok: list[str] = []
            rate_limited = source.rate_limit_until and source.rate_limit_until > datetime.now(UTC)
            if rate_limited:
                async with repo_lock:
                    aggregate["sources_skipped"] += 1
                logger.info(
                    "Skipping source %s until %s (rate-limited)",
                    source_id,
                    source.rate_limit_until.isoformat(),
                )
                return

            logger.info("Processing source %s (channel=%s)", source_id, channel_id)

            async with repo_lock:
                docs_before = await processed_repo.list_by_channel(channel_id)

            try:
                async with semaphore:
                    try:
                        stats = await run_full_pipeline(
                            source_id=source_id,
                            output_dir=output_dir,
                            mode="incremental",
                            skip_topicize=True,
                            concurrency=settings.processing_concurrency,
                        )
                        stages_ok.extend(["ingest", "process", "export"])
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

                async with repo_lock:
                    aggregate["total_new_messages"] += new_messages
                    aggregate["total_processed"] += new_processed

                    docs_after = await processed_repo.list_by_channel(channel_id)

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
                        async with repo_lock:
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

                    # F5-C: Evolving Topic Summaries hook (between F11-prep
                    # topic embedding and F11 watchlist check). Mirror F11's
                    # silent-log contract: F5-C is post-processing, so
                    # non-billing failures MUST NOT pollute stage_errors —
                    # otherwise success=False (line `success = not
                    # stage_errors` below) would lie about upstream stages.
                    # Only AnthropicBillingError escalates so the existing
                    # _pause_source_for_billing fires (Decision #13 +
                    # gotcha #16). F11 watchlist below scores against the
                    # freshest summary because of this ordering.
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

                logger.info(
                    "Source %s completed: new_messages=%d, processed=%d",
                    source_id,
                    new_messages,
                    new_processed,
                )

            except Exception as exc:
                if not stage_errors:
                    stage_errors.append(("unknown", exc))
                logger.error("Source %s failed: %s", source_id, exc, exc_info=True)
            finally:
                await _record_and_pause_on_billing(stage_errors, source, state_repo)

                first_stage = stage_errors[0][0] if stage_errors else None
                first_exc = stage_errors[0][1] if stage_errors else None
                success = not stage_errors
                if success:
                    async with repo_lock:
                        aggregate["sources_succeeded"] += 1
                else:
                    async with repo_lock:
                        aggregate["sources_failed"] += 1
                        aggregate["errors"][source_id] = str(first_exc)

                await _safe_record_attempt(
                    state_repo=state_repo,
                    source_id=source_id,
                    success=success,
                    failed_stage=first_stage,
                    exc=first_exc,
                    duration=time.time() - source_start,
                    details={
                        "trigger": "scheduled",
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
                    "success" if success else "failure",
                )

        await asyncio.gather(*[_process_source(s) for s in sources])

    aggregate["duration_seconds"] = round(time.time() - start_time, 2)
    aggregate["finished_at"] = datetime.now(UTC).isoformat()

    logger.info(
        "Incremental pipeline completed: succeeded=%d, failed=%d, duration=%.2fs",
        aggregate["sources_succeeded"],
        aggregate["sources_failed"],
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

    prompt_loader = PromptLoader(prompts_dir=str(settings.prompts_dir))

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
    """
    if not new_doc_refs:
        return {"inserted": 0, "skipped_reason": "no_new_docs"}

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

    return {"inserted": len(inserted), "skipped_reason": None}


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
        if unregister_digest_subscription(sub_id):
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
