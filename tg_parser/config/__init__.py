"""
Модуль конфигурации TG_parser.

Настройки через pydantic-settings (ENV + файлы).
"""

from .settings import Settings, settings

__all__ = ["Settings", "settings"]
