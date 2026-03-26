"""
Topicization service.

Extracted from cli/topicize_cmd.py — owns the business logic for
topic formation and bundle building.

Session 35: added run_incremental_topicization for Phase 1 (keyword assign).
Session 36: Phase 2 — LLM discover for unassigned documents.
"""

import contextlib
import logging
from collections import defaultdict

from tg_parser.domain.models import (
    BundleItem,
    BundleItemRole,
    IncrementalTopicizeResult,
    MessageType,
)
from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.services.db_context import processing_repos
from tg_parser.storage.ports import ProcessedDocumentRepo, TopicBundleRepo, TopicCardRepo

logger = logging.getLogger(__name__)


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
    logger.info(f"Topicization with {provider}/{model or 'default'}")
    llm_client = create_llm_client(
        provider=provider,
        api_key=api_key,
        model=model,
    )

    try:
        async with contextlib.AsyncExitStack() as stack:
            if processed_repo is None or topic_card_repo is None or topic_bundle_repo is None:
                processed_repo, topic_card_repo, topic_bundle_repo, _db = (
                    await stack.enter_async_context(processing_repos())
                )

            pipeline = TopicizationPipelineImpl(
                llm_client=llm_client,
                processed_doc_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

            logger.info(f"Starting topicization for channel: {channel_id}")
            topic_cards = await pipeline.topicize_channel(
                channel_id=channel_id,
                force=force,
            )

            topics_count = len(topic_cards)
            logger.info(f"Created {topics_count} topic cards")

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
                    except Exception as e:
                        logger.error(
                            "Failed to build bundle for topic %s: %s",
                            card.id, e, exc_info=True,
                        )

                logger.info("Created %d topic bundles", bundles_count)

            coverage = await _compute_coverage(
                processed_repo, topic_bundle_repo, channel_id,
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
                **coverage,
            }
    finally:
        await llm_client.close()


async def run_incremental_topicization(
    channel_id: str,
    new_doc_refs: list[str],
    *,
    processed_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
    topic_bundle_repo: TopicBundleRepo | None = None,
) -> IncrementalTopicizeResult:
    """
    Incremental topicization: Phase 1 (keyword assign) + Phase 2 (LLM discover).

    1. Load new ProcessedDocuments by source_refs
    2. Compute coverage_before
    3. Phase 1: assign_documents_to_topics (keyword matching, 0 LLM tokens)
    4. Update bundles for assigned docs
    5. Phase 2: LLM discover for unassigned docs (assign/create/unassignable)
    6. Update bundles for LLM-assigned docs, create bundles for new topics
    7. Compute coverage_after and return result
    """
    llm_client = None
    try:
        async with contextlib.AsyncExitStack() as stack:
            if processed_repo is None or topic_card_repo is None or topic_bundle_repo is None:
                processed_repo, topic_card_repo, topic_bundle_repo, _db = (
                    await stack.enter_async_context(processing_repos())
                )

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

            coverage_before = await _compute_coverage(processed_repo, topic_bundle_repo, channel_id)

            pipeline = TopicizationPipelineImpl(
                llm_client=None,  # type: ignore[arg-type]
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
                assignments, docs_by_ref, topic_bundle_repo, method="keyword",
            )

            llm_assignments: list = []
            new_topic_cards: list = []
            truly_unassignable: list[str] = []
            tokens_used = 0

            if unassigned_refs:
                provider, api_key, model = resolve_llm_config("topicization")
                llm_client = create_llm_client(
                    provider=provider, api_key=api_key, model=model,
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

                from tg_parser.config import settings
                llm_assignments, new_topic_cards, truly_unassignable, tokens_used = \
                    await pipeline_with_llm.discover_new_topics(
                        channel_id, unassigned_docs,
                        batch_size=settings.topicization_batch_size,
                    )

                await _update_bundles_for_assignments(
                    llm_assignments, docs_by_ref, topic_bundle_repo, method="llm",
                )

                for card in new_topic_cards:
                    try:
                        await topic_card_repo.upsert(card)
                        await pipeline_with_llm.build_topic_bundle(
                            topic_card=card,
                            channel_id=channel_id,
                            documents=new_docs,
                        )
                        logger.info(
                            "Created discovered topic %s: %s", card.id, card.title[:60],
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to save discovered topic %s: %s",
                            card.id, e, exc_info=True,
                        )

            coverage_after = await _compute_coverage(processed_repo, topic_bundle_repo, channel_id)

            result = IncrementalTopicizeResult(
                assigned_keyword=assignments,
                assigned_llm=llm_assignments,
                new_topics=new_topic_cards,
                unassignable=truly_unassignable,
                tokens_used=tokens_used,
                coverage_before=coverage_before["coverage_pct"],
                coverage_after=coverage_after["coverage_pct"],
            )

            logger.info(
                "Incremental topicization for %s: "
                "phase1=%d, phase2_assign=%d, new_topics=%d, unassignable=%d, "
                "coverage %.1f%% -> %.1f%%",
                channel_id,
                len(assignments), len(llm_assignments),
                len(new_topic_cards), len(truly_unassignable),
                result.coverage_before, result.coverage_after,
            )

            return result
    finally:
        if llm_client is not None:
            await llm_client.close()


async def run_incremental_topicization_for_uncovered(
    channel_id: str,
    assign_only: bool = False,
    *,
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
        processed_repo: Optional DI for ProcessedDocumentRepo
        topic_card_repo: Optional DI for TopicCardRepo
        topic_bundle_repo: Optional DI for TopicBundleRepo
    """
    async with contextlib.AsyncExitStack() as stack:
        if processed_repo is None or topic_card_repo is None or topic_bundle_repo is None:
            processed_repo, topic_card_repo, topic_bundle_repo, _db = (
                await stack.enter_async_context(processing_repos())
            )

        all_docs = await processed_repo.list_by_channel(channel_id)
        if not all_docs:
            logger.info("No documents found for channel %s", channel_id)
            return IncrementalTopicizeResult()

        covered_refs: set[str] = set()
        bundles = await topic_bundle_repo.list_by_channel(channel_id)
        for bundle in bundles:
            for item in bundle.items:
                covered_refs.add(item.source_ref)

        uncovered_refs = [
            d.source_ref for d in all_docs if d.source_ref not in covered_refs
        ]

        logger.info(
            "CLI incremental for %s: %d total docs, %d covered, %d uncovered",
            channel_id, len(all_docs), len(covered_refs), len(uncovered_refs),
        )

        if not uncovered_refs:
            coverage = await _compute_coverage(
                processed_repo, topic_bundle_repo, channel_id,
            )
            return IncrementalTopicizeResult(
                coverage_before=coverage["coverage_pct"],
                coverage_after=coverage["coverage_pct"],
            )

    if assign_only:
        result = await _run_assign_only(channel_id, uncovered_refs)
    else:
        result = await run_incremental_topicization(channel_id, uncovered_refs)

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
                processed_repo, topic_bundle_repo, channel_id,
            )
            return IncrementalTopicizeResult(
                coverage_before=coverage["coverage_pct"],
                coverage_after=coverage["coverage_pct"],
            )

        coverage_before = await _compute_coverage(
            processed_repo, topic_bundle_repo, channel_id,
        )

        pipeline = TopicizationPipelineImpl(
            llm_client=None,  # type: ignore[arg-type]
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
            assignments, docs_by_ref, topic_bundle_repo, method="keyword",
        )

        coverage_after = await _compute_coverage(
            processed_repo, topic_bundle_repo, channel_id,
        )

        result = IncrementalTopicizeResult(
            assigned_keyword=assignments,
            unassignable=unassigned_refs,
            tokens_used=0,
            coverage_before=coverage_before["coverage_pct"],
            coverage_after=coverage_after["coverage_pct"],
        )

        logger.info(
            "Assign-only for %s: assigned=%d, unassigned=%d, "
            "coverage %.1f%% -> %.1f%%",
            channel_id, len(assignments), len(unassigned_refs),
            result.coverage_before, result.coverage_after,
        )

        return result


async def _update_bundles_for_assignments(
    assignments: list,
    docs_by_ref: dict,
    topic_bundle_repo: TopicBundleRepo,
    method: str,
) -> None:
    """Group assignments by topic and add items to bundles."""
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
            bundle_items.append(BundleItem(
                channel_id=ch_id,
                message_id=msg_id,
                message_type=MessageType(msg_type),
                source_ref=doc.source_ref,
                role=BundleItemRole.SUPPORTING,
                score=a.score,
                justification=f"incremental {method} assign (score={a.score})",
            ))

        if bundle_items:
            try:
                await topic_bundle_repo.add_items(topic_id, bundle_items)
                logger.info(
                    "Added %d items to bundle %s (%s)", len(bundle_items), topic_id, method,
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
