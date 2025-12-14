"""
Telegram ingestion через Telethon.

Реализует TR-4..TR-17: сбор raw-сообщений из Telegram каналов.
"""

from .telethon_client import TelethonClient

__all__ = ["TelethonClient"]
