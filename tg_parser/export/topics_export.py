"""
Экспорт тематических артефактов.

Реализует TR-56/TR-59/TR-63: topics.json, topic_<id>.json с детерминизмом.
"""

from datetime import UTC, datetime
from pathlib import Path

from tg_parser.domain.models import TopicBundle, TopicCard
from tg_parser.export.telegram_url import resolve_telegram_url
from tg_parser.storage.sqlite.json_utils import stable_json_dumps


def export_topics_json(
    cards: list[TopicCard],
    output_path: Path,
    pretty: bool = False,
) -> None:
    """
    Экспортировать каталог тем в topics.json (TR-56).

    TR-63: детерминированная сортировка по TopicCard.id.

    Args:
        cards: Список TopicCard
        output_path: Путь к выходному файлу
        pretty: Использовать pretty-print
    """
    # Сортировка по id (TR-63)
    sorted_cards = sorted(cards, key=lambda c: c.id)

    # Сериализация через Pydantic
    data = [card.model_dump(mode="json") for card in sorted_cards]

    output_path.write_text(stable_json_dumps(data, pretty=pretty), encoding="utf-8")


def export_topic_detail_json(
    card: TopicCard,
    bundle: TopicBundle,
    channel_username_map: dict[str, str | None],  # channel_id -> username
    output_path: Path,
    pretty: bool = False,
    export_version: str = "export:v1.0.0",
) -> None:
    """
    Экспортировать детальную информацию о теме в topic_<topic_id>.json (TR-59).

    Структура:
    - topic_card: TopicCard
    - topic_bundle: TopicBundle
    - resolved_sources: таблица резолюции источников
    - exported_at: ISO datetime
    - export_version: версия формата

    TR-59: resolved_sources[] для всех материалов из anchors + bundle items.

    Args:
        card: TopicCard
        bundle: TopicBundle
        channel_username_map: Маппинг channel_id → username для резолюции URL
        output_path: Путь к выходному файлу
        pretty: Использовать pretty-print
        export_version: Версия формата экспорта
    """
    # Собираем все source_ref из anchors и bundle items
    source_refs = set()

    # Из anchors
    for anchor in card.anchors:
        source_refs.add(anchor.anchor_ref)

    # Из bundle items
    for item in bundle.items:
        source_refs.add(item.source_ref)

    # Формируем resolved_sources[] с merge правилами (docs/pipeline.md)
    resolved_sources = []

    for source_ref in sorted(source_refs):  # Детерминированный порядок
        # Ищем anchor
        anchor = next((a for a in card.anchors if a.anchor_ref == source_ref), None)

        # Ищем bundle item
        item = next((it for it in bundle.items if it.source_ref == source_ref), None)

        # Merge правила (docs/pipeline.md, раздел "Слияние (merge) данных"):
        # - role: anchor побеждает
        # - score: anchor побеждает, иначе item
        # - justification: только из item

        if anchor:
            role = "anchor"
            score = anchor.score
            justification = None
        elif item:
            role = item.role.value
            score = item.score
            justification = item.justification
        else:
            continue  # Не должно случиться

        # Парсим source_ref для получения channel_id, message_id, message_type
        # Формат: tg:<channel_id>:<message_type>:<message_id>
        parts = source_ref.split(":")
        if len(parts) != 4:
            continue

        channel_id = parts[1]
        message_type = parts[2]
        message_id = parts[3]

        # Резолюция telegram_url (best-effort)
        channel_username = channel_username_map.get(channel_id)
        telegram_url = resolve_telegram_url(channel_id, message_id, channel_username)

        resolved_entry = {
            "source_ref": source_ref,
            "channel_id": channel_id,
            "message_id": message_id,
            "message_type": message_type,
            "role": role,
        }

        if score is not None:
            resolved_entry["score"] = score
        if justification:
            resolved_entry["justification"] = justification
        if telegram_url:
            resolved_entry["telegram_url"] = telegram_url

        resolved_sources.append(resolved_entry)

    # Детерминированная сортировка resolved_sources (TR-63, docs/pipeline.md):
    # 1) role (anchor first)
    # 2) score desc (null в конце)
    # 3) source_ref asc (tie-break)
    resolved_sources.sort(
        key=lambda x: (
            0 if x["role"] == "anchor" else 1,
            -(x.get("score") or -1),  # None/отсутствующие как -1 → в конец
            x["source_ref"],
        )
    )

    # Формируем финальный объект
    export_data = {
        "topic_card": card.model_dump(mode="json"),
        "topic_bundle": bundle.model_dump(mode="json"),
        "resolved_sources": resolved_sources,
        "exported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "export_version": export_version,
    }

    output_path.write_text(stable_json_dumps(export_data, pretty=pretty), encoding="utf-8")
