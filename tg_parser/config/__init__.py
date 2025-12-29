"""
Модуль конфигурации TG_parser.

Настройки через pydantic-settings (ENV + файлы).
"""

from .settings import RetrySettings, Settings, retry_settings, settings

__all__ = ["Settings", "settings", "RetrySettings", "retry_settings"]
