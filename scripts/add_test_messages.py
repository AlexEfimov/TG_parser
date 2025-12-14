#!/usr/bin/env python3
"""
Скрипт для добавления тестовых raw сообщений в базу данных.

Использование:
    python scripts/add_test_messages.py
"""

import asyncio
from datetime import UTC, datetime

from tg_parser.domain.ids import make_source_ref
from tg_parser.domain.models import MessageType, RawTelegramMessage
from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.raw_message_repo import SQLiteRawMessageRepo


async def add_test_messages():
    """Добавить тестовые сообщения в raw_storage.sqlite."""
    # Тестовые сообщения
    test_messages = [
        {
            "id": "1001",
            "channel_id": "test_channel",
            "text": """Привет! Сегодня хочу рассказать о новой функции нашего приложения.

Мы добавили возможность автоматической обработки документов с помощью искусственного интеллекта.
Теперь вы можете загрузить PDF-файл, и система автоматически извлечет ключевую информацию:
- Заголовки и подзаголовки
- Основные темы документа
- Упоминания людей и организаций

Попробуйте и поделитесь впечатлениями!""",
        },
        {
            "id": "1002",
            "channel_id": "test_channel",
            "text": """Важное обновление по безопасности!

Вчера мы обнаружили и исправили уязвимость в модуле аутентификации.
Все пользователи должны обновить приложение до версии 2.3.1.

Спасибо команде безопасности за быстрое реагирование.""",
        },
        {
            "id": "1003",
            "channel_id": "test_channel",
            "text": """Расписание вебинаров на следующую неделю:

📅 Понедельник, 10:00 - "Введение в машинное обучение" (спикер: Иван Петров)
📅 Среда, 14:00 - "Архитектура микросервисов" (спикер: Мария Сидорова)
📅 Пятница, 16:00 - "Тестирование Python приложений" (спикер: Алексей Козлов)

Регистрация по ссылке в био.""",
        },
        {
            "id": "1004",
            "channel_id": "test_channel",
            "text": """Короткое сообщение для тестирования.""",
        },
        {
            "id": "1005",
            "channel_id": "test_channel",
            "text": """Python 3.13 released! 🎉

Major changes:
- Improved performance (15% faster on average)
- Better error messages
- New pattern matching features
- Enhanced type hints

Read more: https://python.org/downloads/release/python-3130/""",
        },
    ]

    # Инициализация database
    config = DatabaseConfig()
    db = Database(config)
    await db.init()

    try:
        # Создаём session и repo
        session = db.raw_storage_session()
        repo = SQLiteRawMessageRepo(session)

        added_count = 0

        # Добавляем сообщения
        for msg_data in test_messages:
            # Создаём source_ref (передаём строковое значение enum)
            source_ref = make_source_ref(
                msg_data["channel_id"], MessageType.POST.value, msg_data["id"]
            )

            # Создаём RawTelegramMessage
            message = RawTelegramMessage(
                id=msg_data["id"],
                message_type=MessageType.POST,
                source_ref=source_ref,
                channel_id=msg_data["channel_id"],
                date=datetime.now(UTC),
                text=msg_data["text"],
            )

            # Сохраняем (upsert, не перезапишет если уже есть)
            created = await repo.upsert(message)

            if created:
                print(f"✓ Добавлено: {source_ref}")
                added_count += 1
            else:
                print(f"⊘ Уже существует: {source_ref}")

        await session.close()

        print(f"\n✅ Готово! Добавлено {added_count} новых сообщений")
        print(f"Всего в базе: {len(test_messages)} тестовых сообщений")
        print("\nТеперь можно запустить:\n  python -m tg_parser.cli process --channel test_channel")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(add_test_messages())
