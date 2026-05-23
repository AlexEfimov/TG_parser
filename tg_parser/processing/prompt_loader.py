"""
Загрузчик промптов из YAML файлов.

Реализует конфигурируемые промпты с fallback на defaults (v1.1).
Требования: v1.1 Configurable Prompts.

Fail-loud contract (TD-03c, post-Living-KB Phase 2): для стадий из
``REQUIRED_PROMPT_STAGES`` пустая конфигурация (отсутствует YAML *и*
встроенный default возвращает ``{}``) — не молчаливое вырождение, а
:class:`PromptLoaderError`. Стадии вне списка (``bot``, ``merge``,
``supporting_items``, ``incremental_discover``) сохраняют старое
поведение «вернуть пустой dict».
"""

from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)


class PromptLoaderError(RuntimeError):
    """Raised when a required prompt stage cannot be resolved.

    Triggered when *both* the on-disk YAML and the built-in Python default
    are missing/empty for a stage that the runtime depends on (LLM-config
    scopes excluding ``global``). Produces a loud failure instead of the
    pre-TD-03c silent empty-string fallback that would have handed the LLM
    a no-op system prompt.
    """


REQUIRED_PROMPT_STAGES: frozenset[str] = frozenset(
    {"processing", "topicization", "rag", "digest", "resummarize", "bot"}
)
"""Stages that must resolve to a non-empty system prompt.

Mirrors ``tg_parser.config.settings.LLM_SCOPES`` minus the synthetic
``global`` entry. Kept as an explicit literal here to avoid an import
cycle with :mod:`tg_parser.config.settings`; a regression test asserts
the two stay in sync.
"""


def _stage_has_content(config: dict[str, Any]) -> bool:
    """Return True iff ``config`` carries a non-empty system prompt.

    Used to distinguish a structurally-present stage entry (e.g. metadata
    only) from one that would actually drive an LLM call.
    """

    if not config:
        return False
    system = config.get("system") or {}
    prompt = system.get("prompt")
    if not isinstance(prompt, str):
        return False
    return bool(prompt.strip())


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

        # BUG-028 Layer B: defense-in-depth against call-sites that
        # accidentally pass ``str(None) == "None"`` (the literal Python
        # repr of None) instead of a real path. Without this guard,
        # ``Path("None")`` is a valid relative path that silently resolves
        # to non-existent ``None/<stage>.yaml`` files, defeating the
        # fail-loud contract for required stages.
        if str(self.prompts_dir) == "None":
            logger.warning(
                "PromptLoader received literal 'None' string for prompts_dir; "
                "falling back to default Path('prompts')",
                received=prompts_dir,
            )
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

        Raises:
            PromptLoaderError: Если ``name`` ∈ :data:`REQUIRED_PROMPT_STAGES` и
                ни YAML, ни встроенный default не дают непустой
                ``system.prompt`` (post-TD-03c fail-loud контракт).
        """
        if name in self._cache:
            return self._cache[name]

        path = self.prompts_dir / f"{name}.yaml"
        yaml_config: dict[str, Any] | None = None

        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    yaml_config = yaml.safe_load(f) or {}

                logger.info("Loaded prompt '%s' from %s", name, path)

            except yaml.YAMLError as e:
                logger.error("Failed to parse YAML file %s: %s", path, e)
            except (OSError, UnicodeDecodeError) as e:
                logger.error("Failed to read file %s: %s", path, e)

        if yaml_config and _stage_has_content(yaml_config):
            self._cache[name] = yaml_config
            return yaml_config

        logger.debug("Using default prompts for '%s' (file not found: %s)", name, path)
        config = self._get_default(name)

        if name in REQUIRED_PROMPT_STAGES and not _stage_has_content(config):
            raise PromptLoaderError(
                f"missing prompt for required stage={name!r}: "
                f"YAML at {path!s} did not provide a non-empty system.prompt "
                f"and the built-in default is empty"
            )

        self._cache[name] = config
        return config

    def _get_default(self, name: str) -> dict[str, Any]:
        """
        Получить default промпты (текущие hardcoded значения).

        Returns ``{}`` for any name not in the built-in registry. Callers
        must NOT treat ``{}`` as success for required stages — that check
        lives in :meth:`load`, which raises :class:`PromptLoaderError`
        when a required stage cannot be resolved.

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
                "user_comment": {
                    "template": prompts.PROCESSING_COMMENT_USER_PROMPT_TEMPLATE,
                    "variables": ["text", "parent_text"],
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
            "rag": {
                "metadata": {
                    "version": "1.1.0",
                    "description": "RAG Q&A prompt for answering questions over the knowledge base",
                },
                "system": {
                    "prompt": (
                        "You are a knowledge base assistant that answers questions "
                        "using content from Telegram channels.\n\n"
                        "Instructions:\n"
                        "- Answer ONLY based on the provided context. Do not use prior knowledge.\n"
                        "- If the context does not contain enough information to answer, say so explicitly.\n"
                        "- Cite sources using their original reference identifiers "
                        "(e.g. [tg:channel:post:123]).\n"
                        "  Each context block starts with a header like "
                        '"[1] channel: ... | ref: tg:channel:post:123".\n'
                        "  Use the ref value for citations, not the numeric index.\n"
                        "- When the context includes TOPIC entries, use their title, summary, and scope "
                        "to provide broader thematic context alongside specific message citations.\n"
                        "- Structure your answer clearly: start with a direct answer, then supporting details.\n"
                        "- Respond in the SAME LANGUAGE as the user's question.\n"
                        "- Be concise but thorough.\n"
                        "- Do NOT wrap your response in markdown code blocks unless showing code."
                    ),
                },
                "user": {
                    "template": (
                        "<context>\n{context}\n</context>\n\n<question>\n{question}\n</question>"
                    ),
                    "variables": ["context", "question"],
                },
                "no_results": {
                    "message": "Не найдено релевантных документов для ответа на вопрос.",
                },
                "model": {
                    "temperature": 0.2,
                    "max_tokens": 2048,
                    "context_char_limit": 2000,
                },
            },
            "bot": {
                "metadata": {
                    "version": "1.0.0",
                    "description": "Telegram Bot Gemini agent system prompt",
                },
                "system": {
                    "prompt": (
                        "You are a knowledge base assistant for Telegram channels. "
                        "You help users explore and find information in the connected channel content.\n\n"
                        "Your capabilities:\n"
                        "1. Answer questions using RAG (retrieves relevant documents and generates answers)\n"
                        "2. Search for specific information across channels\n"
                        "3. List and explore topics extracted from channel content\n"
                        "4. Show channel overview and statistics\n"
                        "5. Look up specific documents by reference\n"
                        "6. Find related topics across different channels\n"
                        "7. Provide cross-channel analytics\n"
                        "8. Start the processing pipeline for a channel (after user confirmation)\n"
                        "9. Check pipeline and scheduler status (read-only)\n"
                        "10. Pause or resume a channel for ingestion/processing (after user confirmation)\n"
                        "11. Add a new channel to the system (after user confirmation)\n"
                        "12. Remove a channel and all its data — IRREVERSIBLE (after user confirmation)\n"
                        "13. View and switch LLM provider/model configuration (view is read-only; switch/reset require confirmation)\n\n"
                        "Instructions:\n"
                        "- ALWAYS use tools to retrieve information before answering. Never make up facts.\n"
                        "- For write operations (trigger_pipeline, pause_channel, resume_channel, add_channel, "
                        "remove_channel, set_llm_config, reset_llm_config): ALWAYS call the tool with confirm=false first "
                        "to obtain a preview, show the user what will happen, ask for explicit confirmation (e.g. yes/no), "
                        "and only then call the same tool again with confirm=true. Never skip the preview step.\n"
                        "- IMPORTANT: remove_channel is IRREVERSIBLE and permanently deletes ALL data for the channel. "
                        "Make sure the user fully understands the consequences before confirming.\n"
                        "- Respond in the SAME LANGUAGE as the user's message.\n"
                        "- Structure your responses clearly:\n"
                        "  * Start with a brief summary or direct answer\n"
                        "  * List key points if applicable (use bullet points)\n"
                        "  * Cite sources when available (document references like tg:channel:post:123)\n"
                        "- If the search returns no results, say so honestly.\n"
                        "- For topic and channel listings, present the data in a readable format.\n"
                        "- Keep responses concise but informative.\n"
                        "- When showing lists, include the most important fields (title, summary, counts).\n"
                        "- Do NOT wrap your response in markdown code blocks unless showing code."
                    ),
                },
            },
            "incremental_discover": {
                "metadata": {
                    "version": "1.0.0",
                    "description": "Incremental topic discovery prompt",
                },
                "system": {
                    "prompt": topicization_prompts.INCREMENTAL_DISCOVER_SYSTEM_PROMPT,
                },
                "model": {
                    "temperature": 0,
                    "max_tokens": 8192,
                },
            },
            "merge": {
                "metadata": {
                    "version": "1.0.0",
                    "description": "Topic merge/deduplication prompt",
                },
                "system": {
                    "prompt": "You are a topic deduplication expert. Return compact JSON with only group ID arrays.",
                },
                "user": {
                    "template": (
                        "You have {topic_count} topics extracted from different batches of messages "
                        "from the same Telegram channel.\n"
                        "Many topics will overlap or cover the same subject — group them aggressively.\n\n"
                        "Topics:\n{topics_json}\n\n"
                        'Return JSON:\n{{"groups": [[0, 5, 12], [3], [1, 7]]}}\n\n'
                        "Rules:\n"
                        "- Each topic ID must appear in exactly one group\n"
                        "- Merge topics that cover the same subject even if titles differ slightly\n"
                        "- Be aggressive: prefer fewer, broader groups over many narrow ones\n"
                        "- Singletons: [3] (topic with truly no overlap)\n"
                        "- Merged: [0, 5, 12] (same or overlapping subjects grouped together)\n"
                        '- Return ONLY the "groups" array of arrays of integer IDs, nothing else'
                    ),
                    "variables": ["topic_count", "topics_json"],
                },
                "model": {
                    "temperature": 0.0,
                    "max_tokens": 16384,
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

    def get_comment_user_template(self, name: str) -> str:
        """
        Получить comment-specific user prompt template.

        Falls back to regular user template if comment template not defined.

        Args:
            name: Имя промпта (e.g., "processing")

        Returns:
            Comment user prompt template строка
        """
        config = self.load(name)
        template = config.get("user_comment", {}).get("template", "")
        if not template:
            template = self.get_user_template(name)
        return template

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

    def validate_required_stages(self) -> None:
        """Eagerly resolve every required stage to surface config drift early.

        Designed as a startup-time invariant check (e.g. from FastAPI
        ``lifespan`` or scheduler bootstrap): walk
        :data:`REQUIRED_PROMPT_STAGES` and force a :meth:`load` for each;
        any missing YAML+default combo raises :class:`PromptLoaderError`
        before the first LLM tick rather than mid-pipeline.

        Caches successful loads as a side effect, which keeps the first
        real call cheap.
        """
        for stage in sorted(REQUIRED_PROMPT_STAGES):
            self.load(stage)


# Global instance (можно переопределить через CLI)
_default_loader: PromptLoader | None = None


def get_prompt_loader() -> PromptLoader:
    """Получить глобальный PromptLoader instance."""
    global _default_loader
    if _default_loader is None:
        from tg_parser.config import settings as _settings

        _default_loader = PromptLoader(prompts_dir=_settings.prompts_dir)
    return _default_loader


def set_prompt_loader(loader: PromptLoader) -> None:
    """Установить глобальный PromptLoader instance."""
    global _default_loader
    _default_loader = loader
