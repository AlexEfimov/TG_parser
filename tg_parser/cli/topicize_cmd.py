"""
CLI команда для topicization pipeline.

Реализует формирование тем и тематических подборок для канала.
"""

import logging

from tg_parser.config import settings
from tg_parser.processing.llm.openai_client import OpenAIClient
from tg_parser.processing.topicization import TopicizationPipelineImpl
from tg_parser.storage.sqlite import Database
from tg_parser.storage.sqlite.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)
from tg_parser.storage.sqlite.topic_bundle_repo import SQLiteTopicBundleRepo
from tg_parser.storage.sqlite.topic_card_repo import SQLiteTopicCardRepo

logger = logging.getLogger(__name__)


async def run_topicization(
    channel_id: str,
    force: bool = False,
    build_bundles: bool = True,
) -> dict[str, int]:
    """
    Запустить topicization для канала.

    Args:
        channel_id: Идентификатор канала
        force: Переформировать темы даже если уже есть
        build_bundles: Создать topic bundles (по умолчанию True)

    Returns:
        Статистика тематизации (topics_count, bundles_count)
    """
    # Инициализируем database (Session 24: поддержка SQLite и PostgreSQL)
    db = Database.from_settings(settings)
    await db.init()

    # Создаём OpenAI client
    llm_client = OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.llm_model or "gpt-4o-mini",
    )

    try:
        # Создаём session
        processing_session = db.processing_storage_session()

        try:
            # Создаём репозитории
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)
            topic_card_repo = SQLiteTopicCardRepo(processing_session)
            topic_bundle_repo = SQLiteTopicBundleRepo(processing_session)

            # Создаём topicization pipeline
            pipeline = TopicizationPipelineImpl(
                llm_client=llm_client,
                processed_doc_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
            )

            # Формируем темы
            logger.info(f"Starting topicization for channel: {channel_id}")
            topic_cards = await pipeline.topicize_channel(
                channel_id=channel_id,
                force=force,
            )

            topics_count = len(topic_cards)
            logger.info(f"Created {topics_count} topic cards")

            # Формируем bundles
            bundles_count = 0
            if build_bundles:
                logger.info(f"Building topic bundles for {topics_count} topics")

                for topic_card in topic_cards:
                    try:
                        await pipeline.build_topic_bundle(
                            topic_card=topic_card,
                            channel_id=channel_id,
                        )
                        bundles_count += 1
                    except Exception as e:
                        logger.error(
                            f"Failed to build bundle for topic {topic_card.id}: {e}",
                            exc_info=True,
                        )

                logger.info(f"Created {bundles_count} topic bundles")

            return {
                "topics_count": topics_count,
                "bundles_count": bundles_count,
            }

        finally:
            await processing_session.close()

    finally:
        await llm_client.close()
        await db.close()
