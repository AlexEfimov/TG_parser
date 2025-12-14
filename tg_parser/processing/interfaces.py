"""
Базовые интерфейсы для слоя обработки (Processing / LLM).

Опираются на доменные модели RawTelegramMessage и ProcessedDocument.
"""

from __future__ import annotations

from typing import Protocol

from tg_parser.domain.models import ProcessedDocuments, RawMessages


class ProcessingPipeline(Protocol):
    """
    Интерфейс пайплайна обработки сообщений.
    """

    def process(self, messages: RawMessages) -> ProcessedDocuments:
        """
        Преобразовать сырые сообщения Telegram в обработанные документы.
        """






