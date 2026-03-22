"""
Export service.

Extracted from cli/export_cmd.py — owns the business logic for
exporting topics and KB entries to JSON/NDJSON files.
"""

import logging
from datetime import datetime
from pathlib import Path

from tg_parser.config import settings
from tg_parser.export.kb_export import export_kb_entries_ndjson, filter_kb_entries
from tg_parser.export.kb_mapping import map_message_to_kb_entry
from tg_parser.export.telegram_url import resolve_telegram_url
from tg_parser.export.topics_export import export_topic_detail_json, export_topics_json
from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SQLiteIngestionStateRepo
from tg_parser.storage.sqlalchemy.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SQLiteTopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SQLiteTopicCardRepo

logger = logging.getLogger(__name__)


async def run_export(
    output_dir: str,
    channel_id: str | None = None,
    topic_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    pretty: bool = False,
) -> dict[str, int]:
    """
    Run artifact export.

    Args:
        output_dir: Output directory for files
        channel_id: Channel filter (optional)
        topic_id: Topic filter (optional)
        from_date: Date filter "from" (optional)
        to_date: Date filter "to" (optional)
        pretty: Pretty-print JSON

    Returns:
        Statistics (kb_entries_count, topics_count, channels_count)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    db = Database.from_settings(settings)
    await db.init()

    try:
        processing_session = db.processing_storage_session()

        try:
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)
            topic_card_repo = SQLiteTopicCardRepo(processing_session)
            topic_bundle_repo = SQLiteTopicBundleRepo(processing_session)

            if channel_id:
                logger.info(f"Loading processed documents for channel: {channel_id}")
                processed_docs = await processed_repo.list_by_channel(
                    channel_id=channel_id,
                    from_date=from_date,
                    to_date=to_date,
                )
            else:
                logger.info("Loading all processed documents (no channel filter)")
                processed_docs = await processed_repo.list_all(
                    from_date=from_date,
                    to_date=to_date,
                )

            if not processed_docs:
                logger.warning("No processed documents found for export")
                return {
                    "kb_entries_count": 0,
                    "topics_count": 0,
                    "channels_count": 0,
                }

            logger.info(f"Found {len(processed_docs)} processed documents")

            ingestion_session = db.ingestion_state_session()
            try:
                ingestion_repo = SQLiteIngestionStateRepo(ingestion_session)
                channel_username_map = await ingestion_repo.get_channel_usernames()
                logger.info(f"Loaded {len(channel_username_map)} channel usernames")
            finally:
                await ingestion_session.close()

            kb_entries = []
            for doc in processed_docs:
                channel_username = channel_username_map.get(doc.channel_id)
                telegram_url = resolve_telegram_url(
                    doc.channel_id,
                    doc.source_message_id,
                    channel_username,
                )
                kb_entry = map_message_to_kb_entry(doc, telegram_url=telegram_url)
                kb_entries.append(kb_entry)

            kb_entries = filter_kb_entries(
                kb_entries,
                channel_id=channel_id,
                topic_id=topic_id,
                from_date=from_date,
                to_date=to_date,
            )

            if not kb_entries:
                logger.warning("No KB entries after filtering")

            if kb_entries:
                kb_output_path = output_path / "kb_entries.ndjson"
                export_kb_entries_ndjson(kb_entries, kb_output_path)
                logger.info(f"Exported {len(kb_entries)} KB entries to {kb_output_path}")

            unique_channels = (
                len({entry.source.channel_id for entry in kb_entries if entry.source.channel_id})
                if kb_entries
                else 0
            )

            topics_count = 0

            if channel_id:
                logger.info(f"Loading topic cards for channel: {channel_id}")
                topic_cards = await topic_card_repo.list_by_channel(channel_id)

                if topic_id:
                    topic_cards = [card for card in topic_cards if card.id == topic_id]

                if topic_cards:
                    topics_json_path = output_path / "topics.json"
                    export_topics_json(topic_cards, topics_json_path, pretty=pretty)
                    logger.info(f"Exported {len(topic_cards)} topics to {topics_json_path}")

                    for card in topic_cards:
                        try:
                            bundle = await topic_bundle_repo.get_by_topic_id(card.id)

                            if bundle:
                                topic_filename = f"topic_{card.id.replace(':', '_')}.json"
                                topic_detail_path = output_path / topic_filename

                                export_topic_detail_json(
                                    card=card,
                                    bundle=bundle,
                                    channel_username_map=channel_username_map,
                                    output_path=topic_detail_path,
                                    pretty=pretty,
                                )

                                logger.info(f"Exported topic detail to {topic_detail_path}")
                            else:
                                logger.warning(f"No bundle found for topic: {card.id}")

                        except Exception as e:
                            logger.error(
                                f"Failed to export topic detail for {card.id}: {e}",
                                exc_info=True,
                            )

                    topics_count = len(topic_cards)
                else:
                    logger.info("No topic cards found for export")
            else:
                logger.info("Topics export requires channel_id filter")

            return {
                "kb_entries_count": len(kb_entries),
                "topics_count": topics_count,
                "channels_count": unique_channels,
            }

        finally:
            await processing_session.close()

    finally:
        await db.close()
