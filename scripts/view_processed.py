#!/usr/bin/env python3
"""
Скрипт для просмотра обработанных документов.

Использование:
    python scripts/view_processed.py [--channel channel_id] [--limit N]
"""

import argparse
import asyncio

from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)


async def view_processed(channel_id: str | None = None, limit: int = 10):
    """Просмотреть обработанные документы."""
    config = DatabaseConfig()
    db = Database(config)
    await db.init()

    try:
        session = db.processing_storage_session()
        repo = SQLiteProcessedDocumentRepo(session)

        if channel_id:
            documents = await repo.list_by_channel(channel_id)
            print(f"\n📊 Обработанные документы канала: {channel_id}\n")
        else:
            # Для просмотра всех документов (упрощенный запрос)
            documents = []
            print("\n📊 Все обработанные документы\n")

        if not documents:
            print("❌ Документы не найдены")
            return

        for i, doc in enumerate(documents[:limit], 1):
            print(f"{'=' * 80}")
            print(f"Документ #{i}")
            print(f"{'=' * 80}")
            print(f"ID:          {doc.id}")
            print(f"Source Ref:  {doc.source_ref}")
            print(f"Channel:     {doc.channel_id}")
            print(f"Processed:   {doc.processed_at}")
            print("\n--- Text Clean ---")
            print(doc.text_clean[:200] + "..." if len(doc.text_clean) > 200 else doc.text_clean)

            if doc.summary:
                print("\n--- Summary ---")
                print(doc.summary)

            if doc.topics:
                print("\n--- Topics ---")
                print(", ".join(doc.topics))

            if doc.entities:
                print("\n--- Entities ---")
                for ent in doc.entities:
                    conf_str = f" ({ent.confidence:.2f})" if ent.confidence else ""
                    print(f"  • {ent.type}: {ent.value}{conf_str}")

            if doc.language:
                print("\n--- Language ---")
                print(doc.language)

            if doc.metadata:
                print("\n--- Metadata ---")
                print(f"  Pipeline: {doc.metadata.get('pipeline_version', 'N/A')}")
                print(f"  Model:    {doc.metadata.get('model_id', 'N/A')}")
                print(
                    f"  Prompt:   {doc.metadata.get('prompt_name', 'N/A')} ({doc.metadata.get('prompt_id', 'N/A')})"
                )

            print()

        await session.close()

        print(f"\n✅ Показано: {min(len(documents), limit)} из {len(documents)} документов")

    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser(description="Просмотр обработанных документов")
    parser.add_argument("--channel", help="Фильтр по каналу")
    parser.add_argument("--limit", type=int, default=10, help="Лимит документов")

    args = parser.parse_args()

    asyncio.run(view_processed(args.channel, args.limit))


if __name__ == "__main__":
    main()
