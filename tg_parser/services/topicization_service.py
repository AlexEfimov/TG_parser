"""
Topicization service.

Extracted from cli/topicize_cmd.py — owns the business logic for
topic formation and bundle building.

Session 35: added run_incremental_topicization for Phase 1 (keyword assign).
Session 36: Phase 2 — LLM discover for unassigned documents.
Session 48: Phase 2 Enhancement + Phase 3 — cross-channel topicization.
"""

import contextlib
from collections import defaultdict
from datetime import UTC, datetime

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

logger = structlog.get_logger(__name__)

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


async def run_topicization(
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

                coverage_after = await _compute_coverage(
                    processed_repo, topic_bundle_repo, channel_id
                )

                # BUG-071 (Bugbot Finding 2): gate marker-clearing on ACTUALLY
                # PERSISTED cards, not the in-memory ``full["topics_count"]``.
                # ``topicize_channel`` swallows ``SQLAlchemyError`` on each
                # ``topic_card_repo.upsert`` and still returns the in-memory list,
                # so ``topics_count`` can be > 0 while ZERO cards persisted. If we
                # cleared the marker on that, the channel would stay at 0 persisted
                # cards and re-escalate a full run EVERY tick. Re-query the repo
                # for the authoritative persisted count; treat an unknown
                # (errored) recount as failure so we ARM the cooldown (safe side).
                persisted_cards = 0
                try:
                    persisted_cards = len(await topic_card_repo.list_by_channel(channel_id))
                except Exception as e:  # noqa: BLE001 — unknown persisted state ⇒ arm cooldown
                    logger.debug(
                        "reescalation_persisted_recount_failed channel=%s: %s", channel_id, e
                    )
                    persisted_cards = 0

                # BUG-071 (Fix 2): record / clear the cooldown marker based on the
                # PERSISTED escalation outcome. >0 persisted cards = recovered →
                # clear so future ticks proceed normally. 0 persisted = still
                # failing → (re)arm the marker (bumping attempts) so the next tick
                # is skipped until the TTL.
                if persisted_cards > 0:
                    await _clear_reescalation_marker(failure_repo, channel_id)
                else:
                    await _arm_reescalation_marker(
                        failure_repo,
                        channel_id,
                        marker,
                        error_message="full topicization re-escalation persisted 0 topic cards",
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
        result = await run_incremental_topicization(
            channel_id,
            uncovered_refs,
            cross_channel=cross_channel,
        )

    return result


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
