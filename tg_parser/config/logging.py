"""
Unified logging configuration with structlog.

Supports:
- JSON logging for production (LOG_FORMAT=json)
- Human-readable logging for development (LOG_FORMAT=text)
- Request ID propagation via context vars
- Structured metadata in all log entries
"""

import logging
import sys
from typing import Any

import structlog

from tg_parser.config.settings import Settings


def configure_logging(settings: Settings | None = None) -> None:
    """
    Configure structured logging for the application.
    
    Args:
        settings: Application settings (default: load from env)
    """
    if settings is None:
        from tg_parser.config import settings as default_settings
        settings = default_settings
    
    # Get log format from environment (default: text for development)
    log_format = getattr(settings, "log_format", "text").lower()
    log_level = getattr(settings, "log_level", "INFO").upper()
    
    # Common processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]
    
    # Format-specific processors
    if log_format == "json":
        # JSON format for production
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Human-readable format for development
        shared_processors.append(structlog.dev.set_exc_info)
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )
    
    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    
    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (default: calling module)
    
    Returns:
        Structured logger with bound context
    """
    return structlog.get_logger(name)


def bind_contextvars(**kwargs: Any) -> None:
    """
    Bind key-value pairs to context vars for all subsequent logs.
    
    Useful for propagating request_id, user_id, etc.
    
    Example:
        bind_contextvars(request_id="abc-123", user_id=42)
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_contextvars() -> None:
    """Clear all context vars."""
    structlog.contextvars.clear_contextvars()


def unbind_contextvars(*keys: str) -> None:
    """
    Remove specific keys from context vars.
    
    Example:
        unbind_contextvars("request_id", "user_id")
    """
    structlog.contextvars.unbind_contextvars(*keys)

