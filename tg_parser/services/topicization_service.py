"""
Topicization service.

Extracted from cli/topicize_cmd.py — owns the business logic for
topic formation and bundle building.
"""

import logging

from tg_parser.config import settings
from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SQLiteTopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SQLiteTopicCardRepo

logger = logging.getLogger(__name__)


async def run_topicization(
    channel_id: str,
    force: bool = False,
    build_bundles: bool = True,
) -> dict[str, int]:
    """
    Run topicization for a channel.

    Args:
        channel_id: Channel identifier
        force: Regenerate topics even if they exist
        build_bundles: Create topic bundles (default True)

    Returns:
        Statistics (topics_count, bundles_count)
    """
    db = Database.from_settings(settings)
    await db.init()

    provider, api_key, model = resolve_llm_config("topicization")
    logger.info(f"Topicization with {provider}/{model or 'default'}")
    llm_client = create_llm_client(
        provider=provider,
        api_key=api_key,
        model=model,
    )

    try:
        processing_session = db.processing_storage_session()

        try:
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)
            topic_card_repo = SQLiteTopicCardRepo(processing_session)
            topic_bundle_repo = SQLiteTopicBundleRepo(processing_session)

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

            return {
                "topics_count": topics_count,
                "bundles_count": bundles_count,
            }

        finally:
            await processing_session.close()

    finally:
        await llm_client.close()
        await db.close()
