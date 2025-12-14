"""
CLI команда для экспорта артефактов.

Реализует TR-56..TR-64: экспорт topics.json, topic_<id>.json, kb_entries.ndjson.
"""

import logging
from datetime import datetime
from pathlib import Path

from tg_parser.config import settings
from tg_parser.export.kb_export import export_kb_entries_ndjson, filter_kb_entries
from tg_parser.export.kb_mapping import map_message_to_kb_entry
from tg_parser.export.telegram_url import resolve_telegram_url
from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)

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
    Запустить экспорт артефактов.

    Args:
        output_dir: Директория для выходных файлов
        channel_id: Фильтр по каналу (опционально)
        topic_id: Фильтр по теме (опционально)
        from_date: Фильтр по дате "от" (опционально)
        to_date: Фильтр по дате "до" (опционально)
        pretty: Pretty-print JSON

    Returns:
        Статистика экспорта (kb_entries_count, channels_count)
    """
    # Создаём output директорию
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Создаём database config
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )

    # Инициализируем database
    db = Database(config)
    await db.init()

    try:
        # Создаём session
        processing_session = db.processing_storage_session()

        try:
            # Создаём репозитории
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)

            # Получаем processed documents с учётом фильтров
            if channel_id:
                logger.info(f"Loading processed documents for channel: {channel_id}")
                processed_docs = await processed_repo.list_by_channel(
                    channel_id=channel_id,
                    from_date=from_date,
                    to_date=to_date,
                )
            else:
                # TODO: добавить метод list_all() в ProcessedDocumentRepo для экспорта всех каналов
                logger.warning(
                    "Export without channel filter not fully implemented - using empty list"
                )
                processed_docs = []

            if not processed_docs:
                logger.warning("No processed documents found for export")
                return {
                    "kb_entries_count": 0,
                    "channels_count": 0,
                }

            logger.info(f"Found {len(processed_docs)} processed documents")

            # Собираем channel_username map (пока используем None для всех)
            # TODO: добавить получение usernames из IngestionStateRepo
            channel_username_map = {}

            # Формируем KB entries из processed documents
            kb_entries = []
            for doc in processed_docs:
                # Резолюция telegram URL (best-effort)
                channel_username = channel_username_map.get(doc.channel_id)
                telegram_url = resolve_telegram_url(
                    doc.channel_id,
                    doc.source_message_id,
                    channel_username,
                )

                # Маппинг в KB entry
                kb_entry = map_message_to_kb_entry(doc, telegram_url=telegram_url)
                kb_entries.append(kb_entry)

            # Применяем фильтры
            kb_entries = filter_kb_entries(
                kb_entries,
                channel_id=channel_id,
                topic_id=topic_id,
                from_date=from_date,
                to_date=to_date,
            )

            if not kb_entries:
                logger.warning("No KB entries after filtering")
                return {
                    "kb_entries_count": 0,
                    "channels_count": 0,
                }

            # Экспортируем KB entries в NDJSON
            kb_output_path = output_path / "kb_entries.ndjson"
            export_kb_entries_ndjson(kb_entries, kb_output_path)
            logger.info(f"Exported {len(kb_entries)} KB entries to {kb_output_path}")

            # Подсчитываем уникальные каналы
            unique_channels = len(
                {entry.source.channel_id for entry in kb_entries if entry.source.channel_id}
            )

            # TODO: экспорт topics.json и topic_<id>.json (требует TopicCardRepo/TopicBundleRepo)
            logger.info("Topic export not yet implemented (requires TopicCardRepo)")

            return {
                "kb_entries_count": len(kb_entries),
                "channels_count": unique_channels,
            }

        finally:
            await processing_session.close()

    finally:
        await db.close()
