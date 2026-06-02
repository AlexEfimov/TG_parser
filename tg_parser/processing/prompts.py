"""
Промпты для processing pipeline.

Шаблоны промптов для извлечения structured данных из сообщений.
Требования: TR-21..TR-26, TR-38 (детерминизм).
"""

# ============================================================================
# Processing промпты (TR-21..TR-26)
# ============================================================================

PROCESSING_SYSTEM_PROMPT = """You are a text processing assistant that extracts structured information from Telegram messages.

Your task is to analyze the message and extract:
1. text_clean: cleaned and normalized text (remove noise, fix formatting)
2. summary: brief summary (1-2 sentences) - can be null if not meaningful
3. topics: list of relevant topics/categories
4. entities: list of named entities (person, organization, location, etc.)
5. language: detected language code (ISO 639-1: ru, en, etc.)

Output MUST be valid JSON matching this structure:
{
  "text_clean": "string (required)",
  "summary": "string or null (optional)",
  "topics": ["string", ...],
  "entities": [{"type": "string", "value": "string", "confidence": 0.0-1.0}, ...],
  "language": "string"
}

Important:
- Preserve all URLs and markdown links [text](url) verbatim; never drop the URL part.
- text_clean is REQUIRED and should be the cleaned version of the original text
- summary can be null if the message is too short or not meaningful
- topics can be empty list if no clear topics
- entities should include confidence scores (0.0-1.0)
- language should be ISO 639-1 code (ru, en, de, etc.)

Additional rules for comments:
- For very short comments (emojis, "?", one-word replies), infer context from parent post
- text_clean should preserve the original comment text, even if short
- summary should reflect what the comment adds to the discussion
- topics should be inherited from parent post when the comment is a reaction"""

PROCESSING_USER_PROMPT_TEMPLATE = """Process this Telegram message:

---
{text}
---

Extract structured information as JSON."""

PROCESSING_COMMENT_USER_PROMPT_TEMPLATE = """Process this Telegram comment (reply to a post).

--- PARENT POST ---
{parent_text}
--- END PARENT POST ---

--- COMMENT ---
{text}
--- END COMMENT ---

Extract structured information as JSON.
For short comments (reactions, agreement, questions), use the parent post context
to determine topics and generate a meaningful summary."""


# ============================================================================
# Вспомогательные функции
# ============================================================================


def build_processing_prompt(text: str) -> str:
    """
    Построить user промпт для processing.

    Args:
        text: Текст сообщения

    Returns:
        Форматированный промпт
    """
    return PROCESSING_USER_PROMPT_TEMPLATE.format(text=text)


def build_comment_processing_prompt(text: str, parent_text: str) -> str:
    """
    Построить user промпт для processing комментария с контекстом поста.

    Args:
        text: Текст комментария
        parent_text: Текст родительского поста

    Returns:
        Форматированный промпт
    """
    return PROCESSING_COMMENT_USER_PROMPT_TEMPLATE.format(
        text=text,
        parent_text=parent_text,
    )


def get_processing_prompt_name() -> str:
    """Имя промпта для metadata (TR-40)."""
    return "processing_v1"
