"""
Processing service.

Extracted from cli/process_cmd.py — owns the business logic for
processing raw messages through the LLM pipeline.
"""

import contextlib
import os
from typing import TYPE_CHECKING

import structlog

from tg_parser.config import settings

if TYPE_CHECKING:
    from tg_parser.processing.pipeline import ProcessingPipelineImpl
from tg_parser.processing import create_processing_pipeline
from tg_parser.services.advisory_lock import channel_advisory_lock
from tg_parser.services.db_context import raw_and_processed_repos
from tg_parser.storage.ports import (
    DedupDropRepo,
    ProcessedDocumentRepo,
    ProcessingFailureRepo,
    RawMessageRepo,
)

logger = structlog.get_logger(__name__)

# BUG-073 (F1): cross-process advisory-lock namespace guarding the PROCESSING
# stage of a channel. ALL trigger paths funnel into ``run_processing``:
# scheduler tick (``run_incremental_for_all_sources`` → ``run_full_pipeline`` →
# ``run_processing``), MCP/API ``full_pipeline`` dispatch job (→
# ``run_full_pipeline`` → ``run_processing``), CLI ``tg-parser run`` (→
# ``run_full_pipeline``) and CLI ``tg-parser process`` (→ ``run_processing``).
# Before this guard, a scheduled tick + a manual ``trigger_pipeline`` for the
# SAME channel could run ``run_processing`` concurrently and both pass the
# load-time ``exists()`` dedup before either persisted (TOCTOU), sending the
# same up-to-``processing_tick_batch_size`` raw messages to the LLM TWICE.
#
# DISTINCT int4 namespace from ``SCHEDULER_SOURCE_LOCK_NS`` (0x5C40, keyed by
# source_id) and ``TOPICIZATION_LOCK_NS`` (0x70C1) so the guards never collide
# in the shared ``pg_advisory_lock`` keyspace. 0x9C40 ≈ "proCessing". Keyed by
# ``hashtext(normalize_channel_id(channel_id))`` so scheduler + dispatch + CLI
# all contend on the SAME per-channel key (the scheduler's 0x5C40 source lock is
# keyed by source_id and is NOT enough on its own — a dispatch/CLI job takes
# neither it nor the in-process ``_running_channel_jobs`` set).
PIPELINE_LOCK_NS = 0x9C40


def channel_pipeline_lock(channel_id: str):
    """Per-channel cross-process advisory lock around the processing stage (F1).

    Thin wrapper over :func:`channel_advisory_lock` pinning the
    BUG-073 namespace + the ``advisory_lock_engine`` (BUG-082: a tiny
    dedicated pool so lock checkout cannot starve the processing data pool).
    All contenders share one Postgres database → the advisory lock is
    mutually visible. Non-blocking: yields ``True`` to run or ``False`` to
    benign-skip; degrades to ``True`` with no DB engine.
    """
    return channel_advisory_lock(
        channel_id,
        namespace=PIPELINE_LOCK_NS,
        engine_attr="advisory_lock_engine",
        label="pipeline_lock",
    )


def _locked_skip_processing_result() -> dict[str, int]:
    """Benign no-op sentinel for a lock-contended processing run (F1 / BUG-073).

    Returned when :func:`channel_pipeline_lock` is already held by another
    in-flight run for the channel. Shaped like a real :func:`run_processing`
    "no work" return (all counts zeroed) so every caller handles it without a
    ``KeyError``: ``run_full_pipeline`` reads ``processed_count`` /
    ``failed_count`` / ``total_tokens`` directly; the scheduler reads
    ``process`` stats via ``.get(...)`` (``total_count`` / ``skipped_count`` /
    ``processed_count`` / ``deduplicated_count`` / ``attempted_count`` /
    ``raw_total_count`` / ``billing_blocked_count``); the dispatch background job
    ignores the return.

    A benign skip is SAFE in processing: the lock-holding run processes the same
    bounded unprocessed backlog, and anything it does not reach stays
    unprocessed for the next tick (no permanent abandonment — unlike the
    tick-local topicization ``new_doc_refs``). The ``skipped_locked`` flag lets
    callers/tests recognise the no-op.
    """
    return {
        "processed_count": 0,
        "skipped_count": 0,
        "cooldown_skipped_count": 0,
        "deduplicated_count": 0,
        "failed_count": 0,
        "total_count": 0,
        "raw_total_count": 0,
        "attempted_count": 0,
        "billing_blocked_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "skipped_locked": True,
    }


async def run_processing(
    channel_id: str,
    force: bool = False,
    retry_failed: bool = False,
    provider: str | None = None,
    model: str | None = None,
    concurrency: int | None = None,
    limit: int | None = None,
    use_agent: bool = False,
    use_llm_tools: bool = False,
    use_pipeline_tool: bool = False,
    *,
    raw_repo: RawMessageRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
    dedup_drop_repo: DedupDropRepo | None = None,
) -> dict[str, int]:
    """BUG-073 (F1): serialise the PROCESSING stage of a channel across processes.

    Thin wrapper around :func:`_run_processing_locked` that takes a NON-BLOCKING
    per-channel Postgres advisory lock (:func:`channel_pipeline_lock`). If
    another processing run already owns the channel the call is a BENIGN no-op:
    it logs ``processing_run_skipped_already_in_flight`` and returns
    :func:`_locked_skip_processing_result` (a zeroed stats dict shaped like a
    real "no work" return) rather than raising — so no caller breaks and the
    skipped backlog simply stays unprocessed for the next run.
    """
    async with channel_pipeline_lock(channel_id) as lock_acquired:
        if not lock_acquired:
            logger.warning(
                "processing_run_skipped_already_in_flight channel=%s "
                "(another processing run owns the channel lock)",
                channel_id,
            )
            # BUG-075 (deferred): this benign skip slightly WIDENS the
            # pre-existing tick-local-abandonment window — docs the lock-holder
            # persists AFTER a skipped scheduler tick's docs_after snapshot are
            # not fed into that tick's incremental ``new_doc_refs`` and, if the
            # holder is a processing-only path, may stay processed-but-untopicized
            # until the channel is otherwise re-topicized. This is acceptable for
            # the F1+F3+F2 ship: it is essentially the pre-existing scheduler
            # property and the common holders (dispatch ``full_pipeline`` /
            # scheduler tick) topicize their own docs. A convergent coverage
            # reconciliation that closes this gap WITHOUT re-burning tokens is
            # deferred to BUG-075 (see
            # docs/notes/START_PROMPT_SESSION_BUG075_TOPICIZATION_COVERAGE_RECONCILIATION_2026-06-28.md).
            return _locked_skip_processing_result()
        return await _run_processing_locked(
            channel_id,
            force=force,
            retry_failed=retry_failed,
            provider=provider,
            model=model,
            concurrency=concurrency,
            limit=limit,
            use_agent=use_agent,
            use_llm_tools=use_llm_tools,
            use_pipeline_tool=use_pipeline_tool,
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
            dedup_drop_repo=dedup_drop_repo,
        )


async def _run_processing_locked(
    channel_id: str,
    force: bool = False,
    retry_failed: bool = False,
    provider: str | None = None,
    model: str | None = None,
    concurrency: int | None = None,
    limit: int | None = None,
    use_agent: bool = False,
    use_llm_tools: bool = False,
    use_pipeline_tool: bool = False,
    *,
    raw_repo: RawMessageRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
    dedup_drop_repo: DedupDropRepo | None = None,
) -> dict[str, int]:
    """
    Run processing for a channel.

    Args:
        channel_id: Channel identifier
        force: Reprocess existing documents
        retry_failed: Retry only previously failed messages
        provider: LLM provider override
        model: Model override
        concurrency: Parallel requests (default: settings.processing_concurrency)
        use_agent: Use agent-based processing
        use_llm_tools: Use LLM-enhanced tools in agent
        use_pipeline_tool: Enable v1.2 pipeline as agent tool
        raw_repo: Optional DI for RawMessageRepo
        processed_repo: Optional DI for ProcessedDocumentRepo
        failure_repo: Optional DI for ProcessingFailureRepo
        dedup_drop_repo: Optional DI for DedupDropRepo (BUG-097 b)

    Returns:
        Processing statistics (processed_count, skipped_count, deduplicated_count,
        failed_count, total_count)
    """
    if concurrency is None:
        concurrency = settings.processing_concurrency

    logger.info(
        "Processing concurrency: %d (from %s)",
        concurrency,
        "settings" if concurrency == settings.processing_concurrency else "override",
    )

    pipeline = None
    async with contextlib.AsyncExitStack() as stack:
        if raw_repo is None or processed_repo is None or failure_repo is None:
            (
                raw_repo,
                processed_repo,
                failure_repo,
                resolved_drop_repo,
                _db,
            ) = await stack.enter_async_context(raw_and_processed_repos())
            # BUG-097 (b): only adopt the context's journal when the caller did
            # not inject one, so an explicitly injected repo (or an explicit None
            # in tests) is never silently replaced.
            if dedup_drop_repo is None:
                dedup_drop_repo = resolved_drop_repo

        try:
            pipeline = create_processing_pipeline(
                provider=provider,
                model=model,
                processed_doc_repo=processed_repo,
                failure_repo=failure_repo,
                raw_repo=raw_repo,
                dedup_drop_repo=dedup_drop_repo,
            )

            if retry_failed:
                logger.info("Loading failed messages for channel: %s", channel_id)
                failures = await failure_repo.list_failures(channel_id=channel_id)

                if not failures:
                    logger.info("No failed messages to retry for channel: %s", channel_id)
                    return {
                        "processed_count": 0,
                        "skipped_count": 0,
                        "failed_count": 0,
                        "total_count": 0,
                        "retry_mode": True,
                    }

                failed_source_refs = {f["source_ref"] for f in failures}
                raw_messages = []
                for source_ref in failed_source_refs:
                    msg = await raw_repo.get_by_source_ref(source_ref)
                    if msg:
                        raw_messages.append(msg)

                logger.info("Found %s failed messages to retry", len(raw_messages))
            elif force:
                # force=True reprocesses EVERYTHING, so it must still see the
                # already-processed docs — the BUG-069 bounded NOT EXISTS load
                # would (correctly) exclude them. Preserve the legacy full load so
                # `force` behaviour is byte-for-byte unchanged.
                logger.info("Loading raw messages for channel (force): %s", channel_id)
                raw_messages = await raw_repo.list_by_channel(channel_id)
            else:
                # BUG-069 / B2 (normal scheduler/process path): bounded backlog
                # load. Only unprocessed docs are returned, with the ORDER BY +
                # LIMIT pushed into SQL so Postgres never sorts the full backlog
                # (no pgsql_tmp DiskFull) and already-processed docs are never
                # re-sent to the LLM (no token re-burn). An explicit CLI `limit`
                # overrides the per-tick batch bound (benchmarking); otherwise the
                # bound is settings.processing_tick_batch_size.
                effective_limit = limit if limit else settings.processing_tick_batch_size
                logger.info(
                    "Loading up to %s unprocessed raw messages for channel: %s",
                    effective_limit,
                    channel_id,
                )
                # BUG-069 (Option A): exclude refs whose failure is still in its
                # cooldown so a poison-pill prefix of oldest failing messages can
                # not consume the whole bounded window and starve newer docs. The
                # repo SQL mirrors pipeline._should_skip_failed. Gated on the same
                # failure_cooldown_enabled flag as the Python filter so disabling
                # the feature restores the pre-Option-A behaviour exactly. force /
                # retry_failed never reach this branch (they keep their own load).
                raw_messages = await raw_repo.list_unprocessed_by_channel(
                    channel_id,
                    limit=effective_limit,
                    failure_cooldown_enabled=settings.failure_cooldown_enabled,
                )

            # BUG-067/B3 coverage denominator: the TRUE raw backlog size for the
            # channel (not the bounded window). Cheap indexed COUNT; surfaced in
            # the stats so the scheduler's coverage gauge uses raw totals rather
            # than the post-BUG-069 bounded window (which would yield ratios >1).
            raw_total_count = await raw_repo.count_by_channel(channel_id)

            if not raw_messages:
                logger.warning("No raw messages found for channel: %s", channel_id)
                return {
                    "processed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "total_count": 0,
                    "raw_total_count": raw_total_count,
                }

            # The bounded NOT EXISTS load already applied `limit` in SQL for the
            # normal path; the legacy CLI slice now only applies to the
            # non-bounded load paths (force / retry_failed).
            if (force or retry_failed) and limit and limit < len(raw_messages):
                raw_messages = raw_messages[:limit]
                logger.info("Limited to %s raw messages (of total available)", limit)

            logger.info("Found %s raw messages", len(raw_messages))

            if use_agent:
                processed_docs = await _process_with_agent(
                    raw_messages=raw_messages,
                    processed_repo=processed_repo,
                    force=force,
                    concurrency=concurrency,
                    provider=provider,
                    model=model,
                    use_llm_tools=use_llm_tools,
                    use_pipeline_tool=use_pipeline_tool,
                    pipeline=pipeline if use_pipeline_tool else None,
                )
                if not use_pipeline_tool:
                    pipeline = None
            else:
                processed_docs = await pipeline.process_batch(
                    raw_messages,
                    force=force,
                    concurrency=concurrency,
                    # BUG-067 B2b: an explicit retry_failed run must bypass the
                    # failure cooldown — the operator is deliberately retrying.
                    bypass_failure_cooldown=retry_failed,
                )

            total_count = len(raw_messages)
            processed_count = len(processed_docs)

            # BUG-067 B2b: docs deferred by the failure cooldown were NOT sent to
            # the LLM and are NOT new failures — count them as skipped so the
            # tick's failed_count reflects only docs actually attempted this tick
            # (keeps B1 degraded-status from mislabelling a cooldown-only tick).
            cooldown_skipped = getattr(pipeline, "_batch_cooldown_skipped", 0) or 0

            # S3 (O-2): within-tick reposts whose leader failed got no mirror this
            # tick. They were never sent to the LLM (excluded from to_process), so
            # they are DEFERRED (retried next tick), not failures — count them as
            # skipped so failed_count = total − processed − skipped stays honest
            # and the scheduler's B1 fail_ratio can't exceed 100% on repost bursts.
            pre_llm_deferred = getattr(pipeline, "_batch_pre_llm_deferred", 0) or 0

            # BUG-097 (a): docs discarded by the POST-LLM dedup. Unlike the two
            # buckets above they went through processing and it SUCCEEDED, so they
            # are neither a failure nor a skip — they get their own outcome and are
            # excluded from failed_count below. Without this they land in remainder
            # (total − processed − skipped) and a tick of nothing but duplicates
            # reports 100% failures, which is what kept nine working sources in a
            # permanent false `degraded` with a four-digit fail_count.
            deduplicated = getattr(pipeline, "_batch_post_llm_dedup", 0) or 0

            if force:
                skipped_count = 0
            elif retry_failed:
                # retry_failed keeps its legacy full-rescan skip accounting
                # UNCHANGED — its load path (failed source_refs) is not the
                # BUG-069 bounded load, so the per-message exists() re-scan still
                # carries semantic weight (a failed ref already processed by a
                # concurrent run must count as skipped, not failed).
                skipped_count = 0
                for msg in raw_messages:
                    if await processed_repo.exists(msg.source_ref):
                        if not any(doc.source_ref == msg.source_ref for doc in processed_docs):
                            skipped_count += 1
                skipped_count += cooldown_skipped + pre_llm_deferred
            else:
                # BUG-069 / B2: the normal-path load (list_unprocessed_by_channel)
                # already excludes already-processed docs in SQL, so the previous
                # per-message processed_repo.exists() re-scan over the whole window
                # is redundant (it would count ~0) and only added DB round-trips.
                # The only remaining "skipped" buckets on this path are the
                # failure-cooldown deferral and the S3 pre-LLM deferral, both
                # surfaced by the pipeline.
                skipped_count = cooldown_skipped + pre_llm_deferred

            failed_count = total_count - processed_count - skipped_count - deduplicated

            stats = {
                "processed_count": processed_count,
                "skipped_count": skipped_count,
                "cooldown_skipped_count": cooldown_skipped,
                # BUG-097 (a): processed, then dropped as a duplicate. A fourth
                # outcome next to processed / skipped / failed — kept OUT of
                # skipped_count so «skipped» keeps meaning «never processed».
                "deduplicated_count": deduplicated,
                "failed_count": failed_count,
                "total_count": total_count,
                # BUG-067/B3: true raw backlog size (coverage denominator).
                "raw_total_count": raw_total_count,
            }

            if pipeline is not None:
                stats["input_tokens"] = pipeline._batch_input_tokens
                stats["output_tokens"] = pipeline._batch_output_tokens
                stats["total_tokens"] = pipeline._batch_input_tokens + pipeline._batch_output_tokens
                # BUG-067: surface the billing-block signal so the scheduler can
                # pause the source AND mark the tick degraded (see B1 + pause).
                stats["billing_blocked_count"] = getattr(pipeline, "_batch_billing_blocked", 0) or 0
                # Fix 2: docs actually attempted (sent to the LLM) THIS tick, so
                # the scheduler's B1 degraded ratio is computed over real attempts
                # rather than the diluted whole-channel total.
                stats["attempted_count"] = getattr(pipeline, "_batch_attempted", 0) or 0
                # S3 (O-2): exact reposts deduplicated before the LLM. These
                # produce a persisted mirror row (counted in processed_count) but
                # are NOT attempts (excluded from attempted_count), so the B1
                # degraded fail_ratio is unaffected.
                stats["pre_llm_dedup_count"] = getattr(pipeline, "_batch_pre_llm_dedup", 0) or 0
                # S3: within-tick reposts deferred because their leader failed
                # (no mirror this tick) — folded into skipped_count above.
                stats["pre_llm_deferred_count"] = pre_llm_deferred

            return stats
        finally:
            if (
                pipeline is not None
                and hasattr(pipeline, "llm_client")
                and hasattr(pipeline.llm_client, "close")
            ):
                await pipeline.llm_client.close()


async def _process_with_agent(
    raw_messages: list,
    processed_repo: ProcessedDocumentRepo,
    force: bool = False,
    concurrency: int = 3,
    provider: str | None = None,
    model: str | None = None,
    use_llm_tools: bool = False,
    use_pipeline_tool: bool = False,
    pipeline: "ProcessingPipelineImpl | None" = None,
) -> list:
    """Process messages using TGProcessingAgent."""
    from tg_parser.agents import TGProcessingAgent
    from tg_parser.processing.llm.factory import create_llm_client

    mode_str = "agent"
    if use_llm_tools:
        mode_str += "+llm"
    if use_pipeline_tool:
        mode_str += "+hybrid"

    logger.info("Starting %s processing for %s messages", mode_str, len(raw_messages))

    llm_client = None
    if use_llm_tools:
        provider_name = provider or "openai"
        api_key = _get_api_key_for_provider(provider_name)
        if api_key:
            llm_client = create_llm_client(
                provider=provider_name,
                api_key=api_key,
                model=model,
            )
            logger.info("Created LLM client for enhanced tools: %s", provider_name)
        else:
            logger.warning("No API key for %s, LLM tools will use fallback", provider_name)

    agent = TGProcessingAgent(
        model=model or "gpt-4o-mini",
        provider=provider or "openai",
        use_llm_tools=use_llm_tools,
        use_pipeline_tool=use_pipeline_tool,
        llm_client=llm_client,
        pipeline=pipeline,
    )

    messages_to_process = []
    for msg in raw_messages:
        if force or not await processed_repo.exists(msg.source_ref):
            messages_to_process.append(msg)

    if not messages_to_process:
        logger.info("No new messages to process")
        return []

    logger.info("Processing %s messages with agent", len(messages_to_process))

    processed_docs = await agent.process_batch(
        messages_to_process,
        concurrency=concurrency,
    )

    for doc in processed_docs:
        if force:
            await processed_repo.upsert(doc)
        else:
            await processed_repo.save(doc)

    logger.info("Agent processing complete: %s documents saved", len(processed_docs))

    return processed_docs


def _get_api_key_for_provider(provider: str) -> str | None:
    """Get API key for the specified provider from environment."""
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
    }
    env_var = key_map.get(provider.lower())
    if env_var:
        return os.getenv(env_var)
    return None


async def run_multi_agent_processing(
    channel_id: str,
    force: bool = False,
    provider: str | None = None,
    model: str | None = None,
    *,
    raw_repo: RawMessageRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> dict[str, int]:
    """BUG-073 (F1): serialise the MULTI-AGENT processing stage per-channel.

    Thin wrapper around :func:`_run_multi_agent_processing_locked` that takes the
    SAME NON-BLOCKING per-channel advisory lock as :func:`run_processing`
    (:func:`channel_pipeline_lock`, ``PIPELINE_LOCK_NS = 0x9C40``, keyed by
    ``hashtext(normalize_channel_id(channel_id))``). The multi-agent path
    (CLI ``tg-parser process --multi-agent``) is ALSO a live per-channel
    processing funnel that loads + LLM-processes the same bounded backlog, so it
    must mutually exclude with a concurrent scheduler tick / dispatch job /
    normal ``run_processing`` for the same channel — otherwise the TOCTOU
    double-billing F1 prevents would reopen on this path. On contention it is a
    BENIGN no-op: it logs ``multi_agent_processing_run_skipped_already_in_flight``
    and returns :func:`_locked_skip_processing_result` (the SAME caller-compatible
    zeroed sentinel ``run_processing`` uses).
    """
    async with channel_pipeline_lock(channel_id) as lock_acquired:
        if not lock_acquired:
            logger.warning(
                "multi_agent_processing_run_skipped_already_in_flight channel=%s "
                "(another processing run owns the channel lock)",
                channel_id,
            )
            # BUG-075 (deferred): same benign-skip abandonment caveat as the
            # ``run_processing`` skip site above — a skip can leave the bounded
            # backlog for the next run; if a processing-only holder persists docs
            # the skipped scheduler tick never sees, they may stay
            # processed-but-untopicized until the channel is otherwise
            # re-topicized. Acceptable for the F1+F3+F2 ship; the convergent
            # coverage reconciliation is deferred to BUG-075 (see
            # docs/notes/START_PROMPT_SESSION_BUG075_TOPICIZATION_COVERAGE_RECONCILIATION_2026-06-28.md).
            return _locked_skip_processing_result()
        return await _run_multi_agent_processing_locked(
            channel_id,
            force=force,
            provider=provider,
            model=model,
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
        )


async def _run_multi_agent_processing_locked(
    channel_id: str,
    force: bool = False,
    provider: str | None = None,
    model: str | None = None,
    *,
    raw_repo: RawMessageRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> dict[str, int]:
    """
    Run multi-agent orchestrated processing for a channel (Phase 3A).

    Uses OrchestratorAgent to coordinate specialized agents:
    - ProcessingAgent: Process raw messages
    - TopicizationAgent: Cluster into topics

    Args:
        channel_id: Channel identifier
        force: Reprocess existing documents
        provider: LLM provider override
        model: Model override
        raw_repo: Optional DI for RawMessageRepo
        processed_repo: Optional DI for ProcessedDocumentRepo
        failure_repo: Optional DI for ProcessingFailureRepo
    """
    from tg_parser.agents import (
        AgentRegistry,
        OrchestratorAgent,
        ProcessingAgent,
        TopicizationAgent,
    )

    logger.info("Starting multi-agent processing for channel: %s", channel_id)

    async with contextlib.AsyncExitStack() as stack:
        if raw_repo is None or processed_repo is None or failure_repo is None:
            (
                raw_repo,
                processed_repo,
                _failure_repo,
                _dedup_drop_repo,
                _db,
            ) = await stack.enter_async_context(raw_and_processed_repos())

        # BUG-069 / B2: apply the same bounded backlog load as run_processing so
        # the multi-agent path does not re-trigger the full-sort DiskFull / token
        # re-burn. force=True still needs the full backlog (reprocess everything),
        # so it keeps the legacy load; the normal path uses the bounded NOT EXISTS
        # query capped at settings.processing_tick_batch_size.
        if force:
            logger.info("Loading raw messages for channel (force): %s", channel_id)
            raw_messages = await raw_repo.list_by_channel(channel_id)
        else:
            logger.info("Loading unprocessed raw messages for channel: %s", channel_id)
            # BUG-069 (Option A): same bounded NOT EXISTS + cooldown anti-join as
            # run_processing (force-exempt) so the agent path also avoids the
            # poison-pill starvation / DiskFull / token re-burn.
            raw_messages = await raw_repo.list_unprocessed_by_channel(
                channel_id,
                limit=settings.processing_tick_batch_size,
                failure_cooldown_enabled=settings.failure_cooldown_enabled,
            )

        # BUG-067/B3 + MEDIUM fix: surface the TRUE raw backlog size as the
        # coverage denominator from the agent path too (run_processing already
        # does). Without this the scheduler coverage gauge would fall back to the
        # bounded window's total_count and report ratios >1 on this path.
        raw_total_count = await raw_repo.count_by_channel(channel_id)

        if not raw_messages:
            logger.warning("No raw messages found for channel: %s", channel_id)
            return {
                "processed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 0,
                "raw_total_count": raw_total_count,
                "multi_agent": True,
            }

        logger.info("Found %s raw messages", len(raw_messages))

        messages_to_process = []
        for msg in raw_messages:
            if force or not await processed_repo.exists(msg.source_ref):
                messages_to_process.append(msg)

        if not messages_to_process:
            logger.info("No new messages to process")
            return {
                "processed_count": 0,
                "skipped_count": len(raw_messages),
                "failed_count": 0,
                "total_count": len(raw_messages),
                "raw_total_count": raw_total_count,
                "multi_agent": True,
            }

        registry = AgentRegistry()

        processing_agent = ProcessingAgent(
            model=model or "gpt-4o-mini",
            provider=provider or "openai",
        )
        topicization_agent = TopicizationAgent(
            model=model or "gpt-4o-mini",
            provider=provider or "openai",
        )

        registry.register(processing_agent)
        registry.register(topicization_agent)

        orchestrator = OrchestratorAgent(registry=registry)

        await processing_agent.initialize()
        await topicization_agent.initialize()
        await orchestrator.initialize()

        logger.info("Multi-agent system initialized")

        processed_count = 0
        failed_count = 0
        processed_docs = []

        for msg in messages_to_process:
            try:
                result = await orchestrator.send_to(
                    "ProcessingAgent",
                    {"text": msg.text},
                )

                if result:
                    from datetime import UTC, datetime

                    from tg_parser.domain.ids import make_processed_document_id
                    from tg_parser.domain.models import Entity, ProcessedDocument

                    entities = [
                        Entity(
                            type=e.get("type", "unknown"),
                            value=e.get("value", ""),
                            confidence=e.get("confidence"),
                        )
                        for e in result.get("entities", [])
                        if e.get("value")
                    ]

                    doc = ProcessedDocument(
                        id=make_processed_document_id(msg.source_ref),
                        source_ref=msg.source_ref,
                        source_message_id=msg.id,
                        channel_id=msg.channel_id,
                        processed_at=datetime.now(UTC),
                        text_clean=result.get("text_clean", msg.text),
                        summary=result.get("summary"),
                        topics=result.get("topics", []),
                        entities=entities,
                        language=result.get("language", "unknown"),
                        metadata={
                            "pipeline_version": "multi-agent-v3.0",
                            "orchestrator": "OrchestratorAgent",
                            "agent": "ProcessingAgent",
                        },
                    )

                    if force:
                        await processed_repo.upsert(doc)
                    else:
                        await processed_repo.save(doc)

                    processed_docs.append(doc)
                    processed_count += 1

            except (RuntimeError, ValueError) as e:
                logger.error("Failed to process %s: %s", msg.source_ref, e)
                failed_count += 1

        await orchestrator.shutdown()
        await topicization_agent.shutdown()
        await processing_agent.shutdown()

        logger.info(
            "Multi-agent processing complete: %s processed, %s failed",
            processed_count,
            failed_count,
        )

        return {
            "processed_count": processed_count,
            "skipped_count": len(raw_messages) - len(messages_to_process),
            "failed_count": failed_count,
            "total_count": len(raw_messages),
            "raw_total_count": raw_total_count,
            "multi_agent": True,
        }
