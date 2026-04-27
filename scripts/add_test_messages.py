#!/usr/bin/env python3
"""
Скрипт для добавления тестовых raw сообщений в базу данных.

Использование:
    python scripts/add_test_messages.py --channel-id <your_channel_id>

`--channel-id` обязателен. До M1 (BUG-002 mitigation) скрипт по умолчанию
писал в канал `test_channel`, что превращало этот плейсхолдер в реальный
источник в БД и усиливало hallucination-attractor для bot-LLM на пустом
контексте подтверждения. Теперь имя канала всегда задаёт пользователь.
"""

import argparse
import asyncio
from datetime import UTC, datetime

from tg_parser.domain.ids import make_source_ref
from tg_parser.domain.models import MessageType, RawTelegramMessage
from tg_parser.storage.sqlalchemy import Database, DatabaseConfig
from tg_parser.storage.sqlalchemy.raw_message_repo import SARawMessageRepo

# Шаблонный набор сообщений; channel_id подставляется из CLI-аргумента.
_TEMPLATE_MESSAGES: list[dict[str, str]] = [
    {
        "id": "1001",
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
        "text": """Важное обновление по безопасности!

Вчера мы обнаружили и исправили уязвимость в модуле аутентификации.
Все пользователи должны обновить приложение до версии 2.3.1.

Спасибо команде безопасности за быстрое реагирование.""",
    },
    {
        "id": "1003",
        "text": """Расписание вебинаров на следующую неделю:

📅 Понедельник, 10:00 - "Введение в машинное обучение" (спикер: Иван Петров)
📅 Среда, 14:00 - "Архитектура микросервисов" (спикер: Мария Сидорова)
📅 Пятница, 16:00 - "Тестирование Python приложений" (спикер: Алексей Козлов)

Регистрация по ссылке в био.""",
    },
    {
        "id": "1004",
        "text": """Короткое сообщение для тестирования.""",
    },
    {
        "id": "1005",
        "text": """Python 3.13 released! 🎉

Major changes:
- Improved performance (15% faster on average)
- Better error messages
- New pattern matching features
- Enhanced type hints

Read more: https://python.org/downloads/release/python-3130/""",
    },
]


async def add_test_messages(channel_id: str) -> None:
    """Добавить тестовые сообщения в raw_storage для указанного канала."""
    config = DatabaseConfig()
    db = Database(config)
    await db.init()

    try:
        session = db.raw_storage_session()
        repo = SARawMessageRepo(session)

        added_count = 0

        for tpl in _TEMPLATE_MESSAGES:
            source_ref = make_source_ref(channel_id, MessageType.POST.value, tpl["id"])
            message = RawTelegramMessage(
                id=tpl["id"],
                message_type=MessageType.POST,
                source_ref=source_ref,
                channel_id=channel_id,
                date=datetime.now(UTC),
                text=tpl["text"],
            )

            created = await repo.upsert(message)

            if created:
                print(f"✓ Добавлено: {source_ref}")
                added_count += 1
            else:
                print(f"⊘ Уже существует: {source_ref}")

        await session.close()

        print(f"\n✅ Готово! Добавлено {added_count} новых сообщений")
        print(f"Всего в шаблоне: {len(_TEMPLATE_MESSAGES)} сообщений")
        print(
            f"\nТеперь можно запустить:\n  python -m tg_parser.cli process --channel {channel_id}"
        )

    finally:
        await db.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Добавить тестовые raw-сообщения в БД. --channel-id обязателен, "
            "плейсхолдеры (`test_channel`, `example_channel`, ...) отвергаются."
        )
    )
    parser.add_argument(
        "--channel-id",
        required=True,
        help="ID канала, в который записывать тестовые сообщения (обязательно).",
    )
    return parser.parse_args()


# Mitigation M2: тот же reject-список, что и в _exec_add_channel — чтобы скрипт
# не мог силой создать запись с placeholder'ом в обход bot/MCP guard'ов.
_BLOCKED_PLACEHOLDER_NAMES: frozenset[str] = frozenset(
    {
        "test_channel",
        "example_channel",
        "my_channel",
        "default",
        "channel_a",
        "channel_b",
        "test",
        "example",
    }
)


def _validate_channel_id(channel_id: str) -> str:
    normalized = channel_id.lstrip("@").strip()
    if not normalized:
        raise SystemExit("error: --channel-id is required and must be non-empty.")
    if normalized in _BLOCKED_PLACEHOLDER_NAMES:
        raise SystemExit(
            f"error: --channel-id='{normalized}' is a reserved placeholder; "
            "use a real channel_id (see BUG-002 mitigation)."
        )
    return normalized


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(add_test_messages(_validate_channel_id(args.channel_id)))
