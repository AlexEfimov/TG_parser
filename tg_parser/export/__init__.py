"""
Слой экспорта TG_parser.

Формирование экспортных артефактов и KnowledgeBaseEntry.
"""

from .kb_export import export_kb_entries_ndjson, filter_kb_entries
from .kb_mapping import map_message_to_kb_entry, map_topic_to_kb_entry
from .telegram_url import resolve_telegram_url
from .topics_export import export_topic_detail_json, export_topics_json

__all__ = [
    # Telegram URL
    "resolve_telegram_url",
    # KB mapping
    "map_message_to_kb_entry",
    "map_topic_to_kb_entry",
    # Topics export
    "export_topics_json",
    "export_topic_detail_json",
    # KB export
    "export_kb_entries_ndjson",
    "filter_kb_entries",
]
