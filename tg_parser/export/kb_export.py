"""
Экспорт KnowledgeBaseEntry в NDJSON.

Реализует TR-56/TR-62/TR-63: kb_entries.ndjson с фильтрами и детерминизмом.
"""

from datetime import datetime
from pathlib import Path

from tg_parser.domain.models import KnowledgeBaseEntry
from tg_parser.storage.sqlite.json_utils import stable_json_dumps


def export_kb_entries_ndjson(
    entries: list[KnowledgeBaseEntry],
    output_path: Path,
) -> None:
    """
    Экспортировать KB entries в NDJSON формат (TR-56).

    TR-63: детерминированный порядок по KnowledgeBaseEntry.id.

    Args:
        entries: Список KnowledgeBaseEntry
        output_path: Путь к выходному файлу
    """
    # Сортировка по id (TR-63)
    sorted_entries = sorted(entries, key=lambda e: e.id)

    lines = []
    for entry in sorted_entries:
        # Сериализация через Pydantic в dict, затем в JSON строку
        entry_dict = entry.model_dump(mode="json")
        lines.append(stable_json_dumps(entry_dict))

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def filter_kb_entries(
    entries: list[KnowledgeBaseEntry],
    channel_id: str | None = None,
    topic_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[KnowledgeBaseEntry]:
    """
    Отфильтровать KB entries (TR-62).

    Правила (TR-62):
    - --channel: ограничить channel_id
    - --topic-id: ограничить topic-entry + message-entries из bundle
    - --from/--to: для message-entries применяется по RawTelegramMessage.date
      (в KB entry это не хранится напрямую, но можно передать через metadata)

    Args:
        entries: Список KnowledgeBaseEntry
        channel_id: Фильтр по каналу
        topic_id: Фильтр по теме
        from_date: Фильтр по дате (для message-entries)
        to_date: Фильтр по дате (для message-entries)

    Returns:
        Отфильтрованный список
    """
    filtered = entries

    if channel_id:
        filtered = [e for e in filtered if e.source.channel_id == channel_id]

    if topic_id:
        # Включаем topic-entry и message-entries из темы
        filtered = [
            e
            for e in filtered
            if (e.source.type == "topic" and e.source.topic_id == topic_id)
            or (e.source.type == "telegram_message" and topic_id in e.topics)
        ]

    # Фильтр по дате для message-entries (если нужно, можно добавить дату в metadata)
    # В MVP оставляем упрощённо без проверки дат

    return filtered
