"""
Bot entrypoint — initialize services, register handlers, start polling.
F8-A: HTTP health probe for Docker healthcheck.
TD-bot-prometheus-scrape (#53): /metrics endpoint for Prometheus scrape.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from asyncio import StreamReader, StreamWriter
from collections.abc import Callable
from typing import Any

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import InterfaceError, OperationalError

from tg_parser.bot.agent import GeminiAgent
from tg_parser.bot.handlers import router
from tg_parser.bot.middleware import (
    LoggingMiddleware,
    RateLimitMiddleware,
    UserResolutionMiddleware,
)

logger = structlog.get_logger(__name__)

BOT_HEALTH_PORT = 8081
_HEALTH_BODY = b'{"status":"ok"}'
_NOT_FOUND_BODY = b'{"error":"not_found"}'

# BUG-030: hand-rolled retry budget for the digest scheduler initial-load DB
# read. Mirrors the in-tree retry idiom (anthropic_client.py / webhooks.py) —
# deliberately NOT tenacity (operator decision: no new dependency). Five total
# attempts with an explicit backoff schedule gives a worst-case ~20s of waiting,
# comfortably inside the 60s reconcile-loop self-healing window.
_INITIAL_LOAD_MAX_ATTEMPTS = 5
# Seconds to sleep BEFORE attempts 2..5 (no trailing sleep after the last try).
_INITIAL_LOAD_BACKOFF_SCHEDULE = (2, 3, 5, 10)


def _parse_request_line(raw: bytes) -> tuple[str, str]:
    """Parse the HTTP request line. Returns ``(method, path)``.

    Returns ``("", "")`` on malformed input — the caller treats that as 404.
    Path is normalized: query string stripped, leading whitespace stripped.
    Robust to clients that send `GET /metrics` without a Host header
    (Prometheus is one such client when scraping over HTTP/1.0 fallback).
    """
    try:
        first_line = raw.split(b"\r\n", 1)[0]
        parts = first_line.decode("ascii", errors="replace").split(" ")
        if len(parts) < 2:
            return "", ""
        method = parts[0].upper()
        path = parts[1].split("?", 1)[0]
        return method, path
    except Exception:
        return "", ""


def _build_response(
    status: str,
    body: bytes,
    *,
    content_type: str = "application/json",
) -> bytes:
    return (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body


async def _health_handler(reader: StreamReader, writer: StreamWriter) -> None:
    """Minimal HTTP/1.1 endpoint dispatcher.

    Routes:
      * ``GET /health``  → 200 ``{"status":"ok"}`` (Docker healthcheck contract).
      * ``GET /metrics`` → 200 Prometheus text format (TD-bot-prometheus-scrape).
      * everything else  → 404 ``{"error":"not_found"}``.

    Non-GET methods get the 404 response too — the bot HTTP surface is
    deliberately read-only.
    """
    raw = b""
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
    except Exception:
        pass

    method, path = _parse_request_line(raw)

    if method == "GET" and path == "/health":
        response = _build_response("200 OK", _HEALTH_BODY)
    elif method == "GET" and path == "/metrics":
        try:
            metrics_body = generate_latest()
        except Exception:
            logger.exception("bot_metrics_render_failed")
            metrics_body = b""
        response = _build_response(
            "200 OK",
            metrics_body,
            content_type=CONTENT_TYPE_LATEST,
        )
    else:
        response = _build_response("404 Not Found", _NOT_FOUND_BODY)

    try:
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def _start_health_server() -> asyncio.Server | None:
    """Start a tiny TCP HTTP server on BOT_HEALTH_PORT serving /health and /metrics."""
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
        max_output_tokens=settings.bot_gemini_max_output_tokens,
        thinking_budget=settings.bot_gemini_thinking_budget,
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


async def _load_active_subscriptions_with_retry(
    repo_cm_factory: Callable[[], Any] | None = None,
) -> list[Any]:
    """Load active digest subscriptions, retrying transient DB errors (BUG-030).

    The bot's first DB read happens at process boot, where Postgres may still be
    warming up (parallel ``docker compose up -d``) or an Alembic migration may be
    mid-flight. Previously the read was wrapped in a bare ``try/except Exception``
    that silently clamped ``active = []`` on *any* failure, degrading the
    scheduler to an empty job-set until the 60s reconcile loop self-healed.

    This helper uses a hand-rolled retry loop (mirroring the in-tree idiom in
    ``anthropic_client.py`` / ``webhooks.py`` — intentionally NOT ``tenacity``,
    so no new dependency) that retries ONLY transient connection-level errors:

    * :class:`~sqlalchemy.exc.OperationalError` / :class:`~sqlalchemy.exc.InterfaceError`
      → transient (DB warming up / pool reset). Warn + backoff + retry.
    * On exhaustion → ``logger.critical`` (unmistakable, NOT silent) then re-raise
      so the caller can apply the documented last-resort fallback.
    * Any OTHER exception (e.g. ``ProgrammingError`` / ``IntegrityError`` on a
      half-migrated table — a schema-shape error that will NOT self-heal) is left
      to propagate immediately so the bot fails loud instead of running degraded.

    ``repo_cm_factory`` is injectable for tests; defaults to the real
    ``digest_subscription_repo`` async context manager.
    """
    if repo_cm_factory is None:
        from tg_parser.services.db_context import digest_subscription_repo

        repo_cm_factory = digest_subscription_repo

    last_exc: Exception | None = None
    for attempt in range(1, _INITIAL_LOAD_MAX_ATTEMPTS + 1):
        try:
            async with repo_cm_factory() as (repo, _db):
                return await repo.list_active()
        except (OperationalError, InterfaceError) as exc:
            last_exc = exc
            if attempt < _INITIAL_LOAD_MAX_ATTEMPTS:
                backoff = _INITIAL_LOAD_BACKOFF_SCHEDULE[attempt - 1]
                logger.warning(
                    "digest_scheduler_initial_load_retry",
                    attempt=attempt,
                    max_attempts=_INITIAL_LOAD_MAX_ATTEMPTS,
                    retry_in=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)
                continue
            logger.critical(
                "digest_scheduler_initial_load_exhausted_retries",
                attempts=_INITIAL_LOAD_MAX_ATTEMPTS,
                error=str(exc),
                exc_info=True,
            )
            raise
    # Defensive: the loop either returns or raises on the final attempt.
    raise RuntimeError("digest scheduler initial-load retry loop exited unexpectedly") from last_exc


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
    from tg_parser.services.scheduler_service import reconcile_digest_subscriptions

    scheduler = get_scheduler()
    if not scheduler.is_running:
        scheduler.start()

    # BUG-030: bounded hand-rolled retry on transient DB errors. Schema-shape
    # errors (ProgrammingError / IntegrityError) are NOT caught here and crash
    # the bot loud (fast operator-visible restart). Only exhausted *transient*
    # errors fall through to an empty job-set as a LAST RESORT, preserving the
    # 60s reconcile-loop self-healing path — but now logged at CRITICAL.
    try:
        active = await _load_active_subscriptions_with_retry()
    except (OperationalError, InterfaceError):
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
