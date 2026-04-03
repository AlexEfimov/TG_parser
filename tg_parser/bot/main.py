"""
Bot entrypoint — initialize services, register handlers, start polling.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from tg_parser.bot.agent import GeminiAgent
from tg_parser.bot.handlers import router
from tg_parser.bot.middleware import (
    AllowlistMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
)

logger = structlog.get_logger(__name__)


def _configure_logging() -> None:
    """Configure structlog and stdlib logging for the bot process."""
    from tg_parser.config import settings

    if settings.log_format == "json":
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"),
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Suppress noisy aiogram and httpx loggers
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run_bot() -> None:
    """Initialize Database, create the agent and aiogram bot, start polling."""
    _configure_logging()

    from tg_parser.config import settings
    from tg_parser.storage.sqlalchemy import Database

    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Get a token from @BotFather and add it to .env"
        )

    gemini_key = settings.gemini_api_key or settings.google_api_key
    if not gemini_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "The bot agent requires Gemini for reasoning and tool-calling."
        )

    # Validate that RAG/search dependencies are available
    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not set — search and Q&A tools will fail "
            "(embeddings require OpenAI by default)"
        )

    from tg_parser.processing.llm.factory import resolve_llm_config
    rag_provider, rag_key, rag_model = resolve_llm_config("processing")
    if rag_provider != "ollama" and not rag_key:
        logger.warning(
            "api_key_missing_for_rag",
            provider=rag_provider,
            hint=f"ask_question tool uses {rag_provider} for answer generation, "
            f"but no API key is configured",
        )
    else:
        logger.info(
            "rag_config",
            provider=rag_provider,
            model=rag_model or "default",
        )

    # Initialize database
    db = Database.get_instance()
    await db.init()
    logger.info("database_initialized")

    agent = GeminiAgent(
        api_key=gemini_key,
        model=settings.bot_gemini_model,
        timeout=settings.bot_request_timeout,
    )

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )

    dp = Dispatcher()

    # Register middleware (order matters: logging first, then auth, then rate limit)
    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(AllowlistMiddleware(settings.bot_allowed_user_ids))
    dp.message.middleware(RateLimitMiddleware(settings.bot_rate_limit))

    dp.include_router(router)

    logger.info(
        "bot_starting",
        model=settings.bot_gemini_model,
        allowed_users=len(settings.bot_allowed_user_ids),
        rate_limit=settings.bot_rate_limit,
    )

    try:
        await dp.start_polling(
            bot,
            agent=agent,
            allowed_updates=["message"],
        )
    finally:
        logger.info("bot_shutting_down")
        await agent.close()
        await Database.close_instance()
        logger.info("bot_stopped")


def run_bot_sync() -> None:
    """Synchronous wrapper for ``run_bot()``."""
    asyncio.run(run_bot())
