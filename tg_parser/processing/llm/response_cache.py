"""
F8-A: In-memory TTL cache for LLM responses.

Caches identical prompts for a configurable TTL (default 5 minutes)
to avoid redundant API calls for repeated queries.

Only caches successful responses. Thread-safe via dict operations.
"""

import hashlib
import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_ENTRIES = 500


@dataclass(slots=True)
class _CacheEntry:
    value: str
    expires_at: float


class LLMResponseCache:
    """Simple in-memory TTL cache for LLM string responses."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: dict[str, _CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        raw = f"{system_prompt or ''}|{prompt}|{temperature}|{max_tokens}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str | None:
        key = self._make_key(prompt, system_prompt, temperature, max_tokens)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if time.monotonic() > entry.expires_at:
            self._store.pop(key, None)
            self._misses += 1
            return None
        self._hits += 1
        return entry.value

    def put(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        value: str,
    ) -> None:
        if len(self._store) >= self._max_entries:
            self._evict_expired()
        if len(self._store) >= self._max_entries:
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)

        key = self._make_key(prompt, system_prompt, temperature, max_tokens)
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + self._ttl,
        )

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if now > v.expires_at]
        for k in expired:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict:
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (
                round(self._hits / (self._hits + self._misses), 3)
                if (self._hits + self._misses) > 0
                else 0.0
            ),
        }


_global_cache: LLMResponseCache | None = None


def get_llm_cache() -> LLMResponseCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = LLMResponseCache()
    return _global_cache
