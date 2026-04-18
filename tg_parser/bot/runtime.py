"""
Process-local Bot singleton (F6).

Background tasks (e.g. scheduled-digest delivery) need access to the running
``aiogram.Bot`` instance to push messages to chats outside the polling loop.
The bot stores itself here on startup; background tasks fetch the reference
on demand. If no bot is registered, ``get_bot`` returns ``None`` and the
caller is expected to skip delivery (and *not* advance the digest cursor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from aiogram import Bot


logger = structlog.get_logger(__name__)

_bot: "Bot | None" = None


def set_bot(bot: "Bot") -> None:
    """Register the current ``Bot`` instance for background tasks.

    Idempotent: replacing an existing reference logs a debug message but does
    not raise. Useful for test fixtures that swap the runtime bot.
    """
    global _bot
    if _bot is not None and _bot is not bot:
        logger.debug("bot_runtime_replacing_existing_bot")
    _bot = bot


def get_bot() -> "Bot | None":
    """Return the registered ``Bot`` instance, or ``None`` when not started."""
    return _bot


def clear_bot() -> None:
    """Drop the registered ``Bot`` reference (call on shutdown)."""
    global _bot
    _bot = None


__all__ = ["clear_bot", "get_bot", "set_bot"]
