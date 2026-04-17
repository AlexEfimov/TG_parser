"""
Response formatter for Telegram messages.

Handles HTML escaping, message splitting (4096 char limit), and
fallback for errors/timeouts.
"""

from __future__ import annotations

import html
import re

DEFAULT_MAX_LENGTH = 4096


def escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return html.escape(text, quote=False)


def split_message(text: str, max_length: int = DEFAULT_MAX_LENGTH) -> list[str]:
    """Split a long message into Telegram-safe chunks.

    Tries to split at paragraph boundaries first, then sentence boundaries,
    then forces a hard split if necessary.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_pos = _find_split_point(remaining, max_length)
        chunks.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()

    return [c for c in chunks if c.strip()]


def _find_split_point(text: str, max_length: int) -> int:
    """Find the best position to split text within max_length."""
    # Try splitting at double newline (paragraph boundary)
    pos = text.rfind("\n\n", 0, max_length)
    if pos > max_length // 3:
        return pos + 1

    # Try splitting at single newline
    pos = text.rfind("\n", 0, max_length)
    if pos > max_length // 3:
        return pos + 1

    # Try splitting at sentence end
    for pattern in (". ", "! ", "? ", ".\n"):
        pos = text.rfind(pattern, 0, max_length)
        if pos > max_length // 3:
            return pos + len(pattern)

    # Hard split at max_length
    return max_length


def format_error(message: str) -> str:
    """Format an error message for the user."""
    return f"⚠️ {escape_html(message)}"


def format_timeout() -> str:
    """Format a timeout message."""
    return "⏱ Запрос занял слишком много времени. Попробуйте упростить вопрос или повторить позже."


_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_HEADER_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def markdown_to_html(text: str) -> str:
    """Best-effort conversion of common Markdown patterns to Telegram HTML.

    Handles: bold, italic, code blocks, inline code, headers.
    Telegram supports a limited HTML subset, so we keep it simple.
    """
    # Protect code blocks from other transformations
    code_blocks: list[str] = []

    def _stash_code(m: re.Match) -> str:
        idx = len(code_blocks)
        code_blocks.append(f"<pre>{escape_html(m.group(2))}</pre>")
        return f"\x00CODE{idx}\x00"

    text = _CODE_BLOCK_RE.sub(_stash_code, text)

    # Inline code
    text = _INLINE_CODE_RE.sub(lambda m: f"<code>{escape_html(m.group(1))}</code>", text)

    # Bold **text**
    text = _BOLD_RE.sub(r"<b>\1</b>", text)

    # Italic *text* (only single asterisks not adjacent to other asterisks)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)

    # Headers → bold
    text = _HEADER_RE.sub(r"<b>\1</b>", text)

    # Restore code blocks
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODE{idx}\x00", block)

    return text
