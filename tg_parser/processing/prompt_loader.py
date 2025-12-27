"""
Загрузчик промптов из YAML файлов.

Реализует конфигурируемые промпты с fallback на defaults (v1.1).
Требования: v1.1 Configurable Prompts.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class PromptLoader:
    """
    Загрузчик промптов из YAML файлов с fallback на defaults.

    Поддерживает:
    - Загрузка из кастомной директории prompts/
    - Fallback на встроенные defaults (из prompts.py, topicization_prompts.py)
    - Кэширование загруженных промптов
    """

    def __init__(self, prompts_dir: Path | str | None = None):
        """
        Args:
            prompts_dir: Директория с YAML файлами промптов.
                         Если None, используется ./prompts или defaults.
        """
        if prompts_dir is not None:
            self.prompts_dir = Path(prompts_dir)
        else:
            # Default: ./prompts в текущей рабочей директории
            self.prompts_dir = Path("prompts")

        self._cache: dict[str, dict[str, Any]] = {}

        logger.debug("PromptLoader initialized with prompts_dir=%s", self.prompts_dir)

    def load(self, name: str) -> dict[str, Any]:
        """
        Загрузить конфигурацию промпта из YAML файла.

        Args:
            name: Имя промпта (e.g., "processing", "topicization", "supporting_items")

        Returns:
            Dict с конфигурацией промпта (system, user, model секции)
        """
        if name in self._cache:
            return self._cache[name]

        path = self.prompts_dir / f"{name}.yaml"

        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

                logger.info("Loaded prompt '%s' from %s", name, path)
                self._cache[name] = config
                return config

            except yaml.YAMLError as e:
                logger.error("Failed to parse YAML file %s: %s", path, e)
                # Fall through to defaults
            except Exception as e:
                logger.error("Failed to read file %s: %s", path, e)
                # Fall through to defaults

        # Fallback to built-in defaults
        logger.debug("Using default prompts for '%s' (file not found: %s)", name, path)
        config = self._get_default(name)
        self._cache[name] = config
        return config

    def _get_default(self, name: str) -> dict[str, Any]:
        """
        Получить default промпты (текущие hardcoded значения).

        Args:
            name: Имя промпта

        Returns:
            Dict с default конфигурацией
        """
        from . import prompts, topicization_prompts

        defaults: dict[str, dict[str, Any]] = {
            "processing": {
                "metadata": {
                    "version": "1.0.0",
                    "description": "Processing prompts for extracting structured data",
                },
                "system": {
                    "prompt": prompts.PROCESSING_SYSTEM_PROMPT,
                },
                "user": {
                    "template": prompts.PROCESSING_USER_PROMPT_TEMPLATE,
                    "variables": ["text"],
                },
                "model": {
                    "temperature": 0,
                    "max_tokens": 4096,
                },
            },
            "topicization": {
                "metadata": {
                    "version": "1.0.0",
                    "description": "Topicization prompts for clustering messages into topics",
                },
                "system": {
                    "prompt": topicization_prompts.TOPICIZATION_SYSTEM_PROMPT,
                },
                "user": {
                    "template": topicization_prompts.TOPICIZATION_USER_PROMPT_TEMPLATE,
                    "variables": ["messages_text"],
                },
                "model": {
                    "temperature": 0,
                    "max_tokens": 8192,
                },
            },
            "supporting_items": {
                "metadata": {
                    "version": "1.0.0",
                    "description": "Supporting items prompts for finding related messages",
                },
                "system": {
                    "prompt": topicization_prompts.SUPPORTING_ITEMS_SYSTEM_PROMPT,
                },
                "user": {
                    "template": topicization_prompts.SUPPORTING_ITEMS_USER_PROMPT_TEMPLATE,
                    "variables": [
                        "topic_title",
                        "topic_summary",
                        "scope_in",
                        "scope_out",
                        "anchor_refs",
                        "messages_text",
                    ],
                },
                "model": {
                    "temperature": 0,
                    "max_tokens": 8192,
                },
            },
        }

        return defaults.get(name, {})

    def get_system_prompt(self, name: str) -> str:
        """
        Получить system prompt для указанного типа.

        Args:
            name: Имя промпта (e.g., "processing")

        Returns:
            System prompt строка
        """
        config = self.load(name)
        return config.get("system", {}).get("prompt", "")

    def get_user_template(self, name: str) -> str:
        """
        Получить user prompt template.

        Args:
            name: Имя промпта

        Returns:
            User prompt template строка
        """
        config = self.load(name)
        return config.get("user", {}).get("template", "")

    def get_model_settings(self, name: str) -> dict[str, Any]:
        """
        Получить настройки модели (temperature, max_tokens, etc.).

        Args:
            name: Имя промпта

        Returns:
            Dict с настройками модели
        """
        config = self.load(name)
        return config.get("model", {})

    def get_metadata(self, name: str) -> dict[str, Any]:
        """
        Получить metadata промпта (version, description, etc.).

        Args:
            name: Имя промпта

        Returns:
            Dict с metadata
        """
        config = self.load(name)
        return config.get("metadata", {})

    def clear_cache(self) -> None:
        """Очистить кэш загруженных промптов."""
        self._cache.clear()
        logger.debug("Prompt cache cleared")

    def reload(self, name: str | None = None) -> None:
        """
        Перезагрузить промпты из файлов.

        Args:
            name: Имя конкретного промпта для перезагрузки, или None для всех
        """
        if name is not None:
            self._cache.pop(name, None)
            self.load(name)
        else:
            self.clear_cache()


# Global instance (можно переопределить через CLI)
_default_loader: PromptLoader | None = None


def get_prompt_loader() -> PromptLoader:
    """Получить глобальный PromptLoader instance."""
    global _default_loader
    if _default_loader is None:
        _default_loader = PromptLoader()
    return _default_loader


def set_prompt_loader(loader: PromptLoader) -> None:
    """Установить глобальный PromptLoader instance."""
    global _default_loader
    _default_loader = loader
