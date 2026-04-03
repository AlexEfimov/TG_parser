"""
Модуль конфигурации TG_parser.

Настройки через pydantic-settings (ENV + файлы).
"""

from .settings import (
    LLMConfigManager,
    RetrySettings,
    Settings,
    llm_config,
    retry_settings,
    settings,
)

__all__ = [
    "LLMConfigManager",
    "Settings",
    "llm_config",
    "retry_settings",
    "settings",
    "RetrySettings",
]
