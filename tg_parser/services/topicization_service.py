"""
Topicization service.

Extracted from cli/topicize_cmd.py — owns the business logic for
topic formation and bundle building.

Session 35: added run_incremental_topicization for Phase 1 (keyword assign).
Session 36: Phase 2 — LLM discover for unassigned documents.
Session 48: Phase 2 Enhancement + Phase 3 — cross-channel topicization.
"""

import contextlib
import math
import structlog
from sqlalchemy.exc import SQLAlchemyError
from collections import defaultdict
from datetime import UTC, datetime

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
from tg_parser.services.db_context import processing_repos, topic_linking_repos
from tg_parser.services.topic_linking_service import _cosine_similarity, _jaccard_similarity
from tg_parser.services.analytics_service import _extract_keywords
from tg_parser.storage.ports import ProcessedDocumentRepo, TopicBundleRepo, TopicCardRepo

logger = structlog.get_logger(__name__)


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
                processed_repo, topic_card_repo, topic_bundle_repo, _db = (
                    await stack.enter_async_context(processing_repos())
                )

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
                "input_tokens": pipeline.total_input_tokens,
                "output_tokens": pipeline.total_output_tokens,
                "total_tokens": pipeline.total_input_tokens + pipeline.total_output_tokens,
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
                assignments, docs_by_ref, topic_bundle_repo, method="keyword",
            )

            llm_assignments: list = []
            new_topic_cards: list = []
            truly_unassignable: list[str] = []
            tokens_used = 0

            # Phase 2 Enhancement: load cross-channel topics as context
            cross_channel_topics: list[dict] | None = None
            if cross_channel and unassigned_refs:
                cross_channel_topics = await _load_cross_channel_topics(
                    channel_id, topic_card_repo,
                )

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

                llm_assignments, new_topic_cards, truly_unassignable, tokens_used = \
                    await pipeline_with_llm.discover_new_topics(
                        channel_id, unassigned_docs,
                        batch_size=settings.topicization_batch_size,
                        cross_channel_topics=cross_channel_topics,
                    )

                await _update_bundles_for_assignments(
                    llm_assignments, docs_by_ref, topic_bundle_repo, method="llm",
                )

                from tg_parser.api.metrics import record_topic_created

                for card in new_topic_cards:
                    try:
                        await topic_card_repo.upsert(card)
                        await pipeline_with_llm.build_topic_bundle(
                            topic_card=card,
                            channel_id=channel_id,
                            documents=new_docs,
                        )
                        record_topic_created(channel_id=channel_id)
                        logger.info(
                            "Created discovered topic %s: %s", card.id, card.title[:60],
                        )
                    except (SQLAlchemyError, RuntimeError, ValueError) as e:
                        logger.error(
                            "Failed to save discovered topic %s: %s",
                            card.id, e, exc_info=True,
                        )

            # Phase 3: auto-create cross-channel TopicLinks
            cross_channel_links_created = 0
            if cross_channel:
                touched_topic_ids = _collect_touched_topic_ids(
                    assignments, llm_assignments, new_topic_cards,
                )
                if touched_topic_ids:
                    cross_channel_links_created = await _run_cross_channel_linking(
                        channel_id=channel_id,
                        touched_topic_ids=touched_topic_ids,
                        threshold=settings.cross_channel_link_threshold,
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
                cross_channel_links_created=cross_channel_links_created,
            )

            logger.info(
                "Incremental topicization for %s: "
                "phase1=%d, phase2_assign=%d, new_topics=%d, unassignable=%d, "
                "cross_links=%d, coverage %.1f%% -> %.1f%%",
                channel_id,
                len(assignments), len(llm_assignments),
                len(new_topic_cards), len(truly_unassignable),
                cross_channel_links_created,
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
        result = await run_incremental_topicization(
            channel_id, uncovered_refs, cross_channel=cross_channel,
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
            cross_topics.append({
                "id": card.id,
                "title": card.title,
                "scope_in": card.scope_in,
                "channel_id": card_channel,
            })
    logger.info(
        "Loaded %d cross-channel topics as context (excluding channel=%s)",
        len(cross_topics), channel_id,
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
    from tg_parser.services.topic_linking_service import JACCARD_WEIGHT, COSINE_WEIGHT

    async with topic_linking_repos() as (
        topic_card_repo, _bundle_repo, topic_link_repo, embedding_repo, _db,
    ):
        touched_cards: list[TopicCard] = []
        for tid in touched_topic_ids:
            card = await topic_card_repo.get_by_id(tid)
            if card:
                touched_cards.append(card)

        if not touched_cards:
            return 0

        all_cards = await topic_card_repo.list_all()
        other_cards = [
            c for c in all_cards
            if c.sources and c.sources[0] != channel_id
        ]

        if not other_cards:
            logger.info("No topics from other channels for cross-linking")
            return 0

        other_keywords: dict[str, set[str]] = {
            c.id: _extract_keywords(c) for c in other_cards
        }

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
                    new_links.append(TopicLink(
                        topic_id_a=touched_card.id,
                        topic_id_b=other_card.id,
                        similarity_score=round(combined, 4),
                        shared_keywords=shared,
                        created_at=datetime.now(UTC),
                    ))

        if not new_links:
            logger.info("Phase 3: no cross-channel links above threshold %.2f", threshold)
            return 0

        saved = await topic_link_repo.upsert_batch(new_links)
        logger.info(
            "Phase 3: created %d cross-channel TopicLinks for %d touched topics",
            saved, len(touched_cards),
        )
        return saved
