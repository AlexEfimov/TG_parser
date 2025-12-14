"""
Модуль получения сырых сообщений из Telegram.

Содержит интерфейсы поверх доменной модели `RawTelegramMessage`.
"""

from .interfaces import TelegramIngestion

__all__ = ["TelegramIngestion"]
