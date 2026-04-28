"""
Bot entrypoint — initialize services, register handlers, start polling.
F8-A: HTTP health probe for Docker healthcheck.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from asyncio import StreamReader, StreamWriter
from typing import Any

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from tg_parser.bot.agent import GeminiAgent
from tg_parser.bot.handlers import router
from tg_parser.bot.middleware import (
    LoggingMiddleware,
    RateLimitMiddleware,
    UserResolutionMiddleware,
)

logger = structlog.get_logger(__name__)

BOT_HEALTH_PORT = 8081


async def _health_handler(reader: StreamReader, writer: StreamWriter) -> None:
    """Minimal HTTP/1.1 health endpoint for Docker healthcheck."""
    try:
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
    except Exception:
        pass
    body = b'{"status":"ok"}'
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )
    writer.write(response)
    await writer.drain()
    writer.close()


async def _start_health_server() -> asyncio.Server | None:
    """Start a tiny TCP health server on BOT_HEALTH_PORT."""
    try:
        server = await asyncio.start_server(_health_handler, "0.0.0.0", BOT_HEALTH_PORT)
        logger.info("bot_health_server_started", port=BOT_HEALTH_PORT)
        return server
    except OSError as e:
        logger.warning("bot_health_server_failed", error=str(e))
        return None


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
            "TELEGRAM_BOT_TOKEN is not set. Get a token from @BotFather and add it to .env"
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

    from tg_parser.bot.runtime import set_bot

    set_bot(bot)

    # BUG-002 + BUG-004: bot needs conversation state for two-turn flows
    # (ConfirmFlow, PaginationFlow). MemoryStorage is sufficient for the
    # current single-replica deployment; switch to RedisStorage when
    # scaling out. See docs/notes/BUG_LOG.md § Session planning D-4.
    dp = Dispatcher(storage=MemoryStorage())

    # Register middleware (order matters: logging first, then auth, then rate limit)
    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(UserResolutionMiddleware(settings.bot_allowed_user_ids))
    dp.message.middleware(RateLimitMiddleware(settings.bot_rate_limit))

    dp.include_router(router)

    logger.info(
        "bot_starting",
        model=settings.bot_gemini_model,
        allowed_users=len(settings.bot_allowed_user_ids),
        rate_limit=settings.bot_rate_limit,
    )

    health_server = await _start_health_server()

    digest_scheduler = None
    digest_reconcile_task: asyncio.Task[None] | None = None
    if settings.digest_scheduler_enabled:
        digest_scheduler, digest_reconcile_task = await _start_digest_scheduler()

    try:
        await dp.start_polling(
            bot,
            agent=agent,
            allowed_updates=["message"],
        )
    finally:
        logger.info("bot_shutting_down")
        if digest_reconcile_task is not None:
            digest_reconcile_task.cancel()
            try:
                await digest_reconcile_task
            except (asyncio.CancelledError, Exception):
                pass
        if digest_scheduler is not None:
            try:
                digest_scheduler.shutdown(wait=False)
            except Exception:
                logger.warning("digest_scheduler_shutdown_failed", exc_info=True)
        from tg_parser.bot.runtime import clear_bot

        clear_bot()
        if health_server:
            health_server.close()
            await health_server.wait_closed()
        await agent.close()
        await Database.close_instance()
        logger.info("bot_stopped")


async def _start_digest_scheduler() -> tuple[Any, asyncio.Task[None] | None]:
    """Initialize the F6 digest scheduler inside the bot process.

    Returns ``(scheduler, reconciliation_task)``. Scheduler is started and the
    initial set of active subscriptions registered before the polling loop
    begins. The reconciliation task wakes up every
    ``digest_refresh_interval`` seconds and diffs DB ↔ scheduler so MCP-side
    create/delete (or another bot replica) propagate without a restart.
    """
    from tg_parser.config import settings
    from tg_parser.services.background_scheduler import (
        get_scheduler,
        register_digest_subscription,
    )
    from tg_parser.services.db_context import digest_subscription_repo
    from tg_parser.services.scheduler_service import reconcile_digest_subscriptions

    scheduler = get_scheduler()
    if not scheduler.is_running:
        scheduler.start()

    try:
        async with digest_subscription_repo() as (repo, _db):
            active = await repo.list_active()
    except Exception:
        logger.exception("digest_scheduler_initial_load_failed")
        active = []

    for sub in active:
        try:
            register_digest_subscription(sub, scheduler)
        except ValueError as exc:
            logger.warning(
                "digest_subscription_invalid_skip",
                subscription_id=sub.id,
                error=str(exc),
            )

    logger.info(
        "digest_scheduler_started",
        active_subscriptions=len(active),
        refresh_interval=settings.digest_refresh_interval,
    )

    async def _reconcile_loop() -> None:
        while True:
            try:
                await asyncio.sleep(settings.digest_refresh_interval)
                await reconcile_digest_subscriptions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("digest_reconcile_tick_failed")

    task = asyncio.create_task(_reconcile_loop(), name="digest-reconcile-loop")
    return scheduler, task


def run_bot_sync() -> None:
    """Synchronous wrapper for ``run_bot()``."""
    asyncio.run(run_bot())
