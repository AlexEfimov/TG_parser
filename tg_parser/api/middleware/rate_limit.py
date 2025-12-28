"""
Rate limiting middleware using slowapi.

Provides configurable rate limits per endpoint type:
- POST /api/v1/process: 10/minute (expensive LLM calls)
- POST /api/v1/export: 20/minute (I/O intensive)
- GET /*: 100/minute (read operations)
"""

import logging
from typing import Callable

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from tg_parser.config import settings

logger = logging.getLogger(__name__)


def _get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key combining IP and API key (if present).
    
    This ensures rate limits apply per-client even through proxies
    when API keys are used.
    """
    ip = get_remote_address(request)
    api_key = request.headers.get("X-API-Key", "")
    
    if api_key:
        # Use first 8 chars of API key for identification
        return f"{ip}:{api_key[:8]}"
    return ip


def get_limiter() -> Limiter:
    """
    Create and configure rate limiter.
    
    Returns disabled limiter if rate_limit_enabled is False.
    """
    if not settings.rate_limit_enabled:
        # Return limiter that allows everything
        return Limiter(
            key_func=_get_rate_limit_key,
            enabled=False,
        )
    
    return Limiter(
        key_func=_get_rate_limit_key,
        default_limits=[settings.rate_limit_default],
    )


# Global limiter instance
limiter = get_limiter()


def rate_limit_process(func: Callable) -> Callable:
    """Decorator for process endpoint rate limit."""
    if not settings.rate_limit_enabled:
        return func
    return limiter.limit(settings.rate_limit_process)(func)


def rate_limit_export(func: Callable) -> Callable:
    """Decorator for export endpoint rate limit."""
    if not settings.rate_limit_enabled:
        return func
    return limiter.limit(settings.rate_limit_export)(func)

