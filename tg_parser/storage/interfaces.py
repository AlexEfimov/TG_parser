"""
Базовые интерфейсы для слоя хранения (Storage / Knowledge Base).

Опираются на доменную модель KnowledgeBaseEntry.
"""

from __future__ import annotations

from typing import Protocol

from tg_parser.domain.models import KnowledgeBaseEntries


class KnowledgeBaseWriter(Protocol):
    """
    Интерфейс компонента, который записывает данные в базу знаний.
    """

    def upsert(self, entries: KnowledgeBaseEntries) -> None:
        """
        Сохранить или обновить набор записей в базе знаний.
        """






