"""
Aiogram middleware for the Telegram bot.

- AllowlistMiddleware: legacy reject for non-allowlisted users
- UserResolutionMiddleware: F4 multi-tenancy DB-based user resolution
- RateLimitMiddleware: per-user sliding-window rate limiting
- LoggingMiddleware: structured logging with telegram_user_id and request_id
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = structlog.get_logger(__name__)


class AllowlistMiddleware(BaseMiddleware):
    """Reject messages from users not in the allowlist.

    If the allowlist is empty, all users are allowed (dev mode).
    Kept for backward compatibility; prefer UserResolutionMiddleware for F4.
    """

    def __init__(self, allowed_user_ids: list[int]) -> None:
        self._allowed = set(allowed_user_ids)

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._allowed:
            return await handler(event, data)

        if isinstance(event, Message) and event.from_user:
            if event.from_user.id not in self._allowed:
                logger.warning(
                    "access_denied",
                    user_id=event.from_user.id,
                    username=event.from_user.username,
                )
                await event.answer(
                    "⛔ Доступ запрещён. Обратитесь к администратору."
                )
                return None

        return await handler(event, data)


class UserResolutionMiddleware(BaseMiddleware):
    """Resolve Telegram user to CurrentUser via DB (F4 Multi-Tenancy).

    If the allowlist is empty (dev mode) and user is not in DB,
    falls back to default admin for backward compatibility.
    Otherwise, unregistered users are rejected.
    """

    def __init__(self, allowed_user_ids: list[int] | None = None) -> None:
        self._legacy_allowed = set(allowed_user_ids or [])

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id

        from tg_parser.auth.resolvers import get_default_admin, resolve_user_by_auth

        current_user = await resolve_user_by_auth("telegram", str(user_id))

        if current_user is None:
            if not self._legacy_allowed:
                # Dev mode: no allowlist configured -> default admin
                current_user = await get_default_admin()
            else:
                logger.warning(
                    "unregistered_telegram_user",
                    user_id=user_id,
                    username=event.from_user.username,
                )
                await event.answer(
                    "⛔ Вы не зарегистрированы. Обратитесь к администратору."
                )
                return None

        data["current_user"] = current_user
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Per-user sliding-window rate limiter.

    Tracks message timestamps per user and rejects requests exceeding
    the configured rate (requests per minute).
    """

    def __init__(self, max_per_minute: int = 10) -> None:
        self._max = max_per_minute
        self._window = 60.0
        self._timestamps: dict[int, list[float]] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.monotonic()
        cutoff = now - self._window

        timestamps = self._timestamps[user_id]
        self._timestamps[user_id] = [t for t in timestamps if t > cutoff]

        if len(self._timestamps[user_id]) >= self._max:
            logger.warning("rate_limit_exceeded", user_id=user_id)
            await event.answer(
                f"⏳ Слишком много запросов. Лимит: {self._max}/мин. Подождите немного."
            )
            return None

        self._timestamps[user_id].append(now)
        return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """Attach structured logging context (user_id, request_id) to each request."""

    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        request_id = str(uuid.uuid4())[:8]

        user_id = None
        username = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username

        with structlog.contextvars.bound_contextvars(
            request_id=request_id,
            telegram_user_id=user_id,
            telegram_username=username,
        ):
            start = time.monotonic()
            try:
                result = await handler(event, data)
                elapsed = time.monotonic() - start
                logger.info(
                    "request_completed",
                    elapsed_ms=round(elapsed * 1000),
                )
                return result
            except Exception:
                elapsed = time.monotonic() - start
                logger.exception(
                    "request_failed",
                    elapsed_ms=round(elapsed * 1000),
                )
                raise
