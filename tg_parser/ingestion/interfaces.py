"""
Базовые интерфейсы для слоя Ingestion.

Реализации должны соответствовать контракту RawTelegramMessage
(`docs/contracts/raw_telegram_message.schema.json`).
"""

from __future__ import annotations

from typing import Protocol

from tg_parser.domain.models import RawMessages


class TelegramIngestion(Protocol):
    """
    Интерфейс сервиса, который получает сообщения из Telegram.

    Конкретная реализация может использовать разные клиенты/библиотеки,
    но снаружи возвращает только доменные модели RawTelegramMessage.
    """

    def fetch_history(self) -> RawMessages:
        """
        Загрузить исторические сообщения (backfill) по настроенным каналам.
        """

    def fetch_new(self) -> RawMessages:
        """
        Загрузить новые сообщения с момента последнего успешного запуска.
        """
