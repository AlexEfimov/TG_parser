"""
Модуль получения сырых сообщений из Telegram.

Содержит интерфейсы поверх доменной модели `RawTelegramMessage`.
"""

from .interfaces import TelegramIngestion
from .orchestrator import IngestionError, IngestionOrchestrator, NonRetryableError, RetryableError

__all__ = [
    "TelegramIngestion",
    "IngestionOrchestrator",
    "IngestionError",
    "RetryableError",
    "NonRetryableError",
]
