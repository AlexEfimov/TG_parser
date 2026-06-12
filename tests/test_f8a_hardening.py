"""
Tests for F8-A Hardening:
1. OpenAI / Gemini 429 retry with exponential backoff
2. Ingestion rate_limit_until check and FloodWait detection
3. LLM response cache (TTL)
4. JobStore shared engine
5. Bot health server
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from tg_parser.processing.llm.response_cache import LLMResponseCache

# ---------------------------------------------------------------------------
# 1. OpenAI retry
# ---------------------------------------------------------------------------


class TestOpenAIRetry:
    def _make_client(self, max_retries=3):
        from tg_parser.processing.llm.openai_client import OpenAIClient

        return OpenAIClient(api_key="sk-test", model="gpt-4o-mini", max_retries=max_retries)

    async def test_success_no_retry(self):
        client = self._make_client()
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        with patch.object(client.client, "post", new=AsyncMock(return_value=mock_resp)):
            result = await client.generate("test")
        assert result == "ok"

    async def test_429_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)

        fail_resp = Mock()
        fail_resp.status_code = 429
        fail_resp.headers = {"retry-after": "0.01"}
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "429",
                request=Mock(),
                response=fail_resp,
            )
        )

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "recovered"}}],
            "usage": {},
        }

        mock_post = AsyncMock(side_effect=[fail_resp, ok_resp])
        with patch.object(client.client, "post", mock_post):
            result = await client.generate("test")

        assert result == "recovered"
        assert mock_post.call_count == 2

    async def test_exhausted_retries_raises(self):
        client = self._make_client(max_retries=2)

        fail_resp = Mock()
        fail_resp.status_code = 429
        fail_resp.headers = {"retry-after": "0.01"}
        fail_resp.text = "rate limited"
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "429",
                request=Mock(),
                response=fail_resp,
            )
        )

        mock_post = AsyncMock(return_value=fail_resp)
        with patch.object(client.client, "post", mock_post):
            with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
                await client.generate("test")
        assert mock_post.call_count == 2

    async def test_500_is_retryable(self):
        client = self._make_client(max_retries=2)

        fail_resp = Mock()
        fail_resp.status_code = 500
        fail_resp.headers = {}
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "500",
                request=Mock(),
                response=fail_resp,
            )
        )

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        mock_post = AsyncMock(side_effect=[fail_resp, ok_resp])
        with patch.object(client.client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"

    async def test_400_not_retried(self):
        client = self._make_client(max_retries=3)

        fail_resp = Mock()
        fail_resp.status_code = 400
        fail_resp.headers = {}
        fail_resp.text = "bad request"
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "400",
                request=Mock(),
                response=fail_resp,
            )
        )

        mock_post = AsyncMock(return_value=fail_resp)
        with patch.object(client.client, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await client.generate("test")
        assert mock_post.call_count == 1

    def test_parse_retry_after_header(self):
        from tg_parser.processing.llm.openai_client import OpenAIClient

        resp = Mock()
        resp.headers = {"retry-after": "15"}
        resp.status_code = 429
        assert OpenAIClient._parse_retry_after(resp) == 15.0

    def test_parse_retry_after_missing(self):
        from tg_parser.processing.llm.openai_client import OpenAIClient

        resp = Mock()
        resp.headers = {}
        resp.status_code = 429
        delay = OpenAIClient._parse_retry_after(resp)
        assert delay >= 10.0

    def test_max_retries_stored(self):
        client = self._make_client(max_retries=7)
        assert client._max_retries == 7

    async def test_network_error_retries_then_succeeds(self):
        """httpx.HTTPError (network-level) is retried."""
        client = self._make_client(max_retries=3)

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        mock_post = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                ok_resp,
            ]
        )
        with patch.object(client.client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    async def test_network_error_exhausted_raises(self):
        """Network error on all attempts raises the original error."""
        client = self._make_client(max_retries=2)

        mock_post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        with patch.object(client.client, "post", mock_post):
            with pytest.raises(httpx.ConnectError):
                await client.generate("test")
        assert mock_post.call_count == 2

    def test_parse_retry_after_non_429(self):
        from tg_parser.processing.llm.openai_client import OpenAIClient

        resp = Mock()
        resp.headers = {}
        resp.status_code = 503
        delay = OpenAIClient._parse_retry_after(resp)
        assert 2.0 <= delay <= 3.0

    def test_parse_retry_after_invalid_header(self):
        from tg_parser.processing.llm.openai_client import OpenAIClient

        resp = Mock()
        resp.headers = {"retry-after": "not-a-number"}
        resp.status_code = 429
        delay = OpenAIClient._parse_retry_after(resp)
        assert delay >= 10.0

    async def test_parse_error_not_retried(self):
        """Invalid JSON response raises ValueError, no retry."""
        client = self._make_client(max_retries=3)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {"unexpected": "format"}

        mock_post = AsyncMock(return_value=mock_resp)
        with patch.object(client.client, "post", mock_post):
            with pytest.raises((ValueError, KeyError)):
                await client.generate("test")
        assert mock_post.call_count == 1

    async def test_502_is_retryable(self):
        client = self._make_client(max_retries=2)

        fail_resp = Mock()
        fail_resp.status_code = 502
        fail_resp.headers = {}
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "502",
                request=Mock(),
                response=fail_resp,
            )
        )

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        mock_post = AsyncMock(side_effect=[fail_resp, ok_resp])
        with patch.object(client.client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"


# ---------------------------------------------------------------------------
# 2. Gemini retry
# ---------------------------------------------------------------------------


class TestGeminiRetry:
    def _make_client(self, max_retries=3):
        from tg_parser.processing.llm.gemini_client import GeminiClient

        return GeminiClient(api_key="test-key", model="gemini-2.0-flash", max_retries=max_retries)

    async def test_success_no_retry(self):
        client = self._make_client()
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_resp)):
            result = await client.generate("test")
        assert result == "ok"

    async def test_429_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)

        fail_resp = Mock()
        fail_resp.status_code = 429
        fail_resp.headers = {"retry-after": "0.01"}
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "429",
                request=Mock(),
                response=fail_resp,
            )
        )

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "recovered"}]}}],
            "usageMetadata": {},
        }

        mock_post = AsyncMock(side_effect=[fail_resp, ok_resp])
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")

        assert result == "recovered"
        assert mock_post.call_count == 2

    async def test_exhausted_retries_raises(self):
        client = self._make_client(max_retries=2)

        fail_resp = Mock()
        fail_resp.status_code = 429
        fail_resp.headers = {"retry-after": "0.01"}
        fail_resp.text = "rate limited"
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "429",
                request=Mock(),
                response=fail_resp,
            )
        )

        mock_post = AsyncMock(return_value=fail_resp)
        with patch.object(client._client, "post", mock_post):
            with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
                await client.generate("test")
        assert mock_post.call_count == 2

    def test_max_retries_stored(self):
        client = self._make_client(max_retries=4)
        assert client._max_retries == 4

    async def test_network_error_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {},
        }

        mock_post = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                ok_resp,
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    async def test_500_is_retryable(self):
        client = self._make_client(max_retries=2)

        fail_resp = Mock()
        fail_resp.status_code = 500
        fail_resp.headers = {}
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "500",
                request=Mock(),
                response=fail_resp,
            )
        )

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {},
        }

        mock_post = AsyncMock(side_effect=[fail_resp, ok_resp])
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"

    async def test_400_not_retried(self):
        client = self._make_client(max_retries=3)

        fail_resp = Mock()
        fail_resp.status_code = 400
        fail_resp.headers = {}
        fail_resp.text = "bad request"
        fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "400",
                request=Mock(),
                response=fail_resp,
            )
        )

        mock_post = AsyncMock(return_value=fail_resp)
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await client.generate("test")
        assert mock_post.call_count == 1

    async def test_invalid_response_raises_value_error(self):
        client = self._make_client()

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {"candidates": []}  # empty candidates

        mock_post = AsyncMock(return_value=mock_resp)
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(ValueError, match="No candidates"):
                await client.generate("test")

    def test_compute_delay_with_retry_after_header(self):
        from tg_parser.processing.llm.gemini_client import GeminiClient

        resp = Mock()
        resp.headers = {"retry-after": "20"}
        delay = GeminiClient._compute_delay(resp, 1)
        assert delay == 20.0

    def test_compute_delay_invalid_header_fallback(self):
        from tg_parser.processing.llm.gemini_client import GeminiClient

        resp = Mock()
        resp.headers = {"retry-after": "invalid"}
        delay = GeminiClient._compute_delay(resp, 2)
        # 2^2 = 4, + jitter
        assert 4.0 <= delay <= 5.2


# ---------------------------------------------------------------------------
# 3. Ingestion rate_limit_until
# ---------------------------------------------------------------------------


class TestIngestionRateLimit:
    def _make_orchestrator(self, source=None):
        from tg_parser.ingestion.orchestrator import IngestionOrchestrator

        mock_settings = MagicMock()
        mock_settings.ingestion_max_attempts_per_run = 3
        mock_settings.ingestion_retry_backoff_base = 0.001
        mock_settings.ingestion_retry_jitter_max = 0.001

        mock_state_repo = AsyncMock()
        if source:
            mock_state_repo.get_source.return_value = source
        mock_raw_repo = AsyncMock()
        mock_client = AsyncMock()

        orch = IngestionOrchestrator(
            telegram_client=mock_client,
            state_repo=mock_state_repo,
            raw_repo=mock_raw_repo,
            settings=mock_settings,
        )
        return orch, mock_state_repo

    def _make_source(self, rate_limit_until=None, status="active"):
        from tg_parser.storage.ports import Source

        return Source(
            source_id="ch1",
            channel_id="ch1",
            channel_username="test",
            status=status,
            include_comments=False,
            rate_limit_until=rate_limit_until,
        )

    async def test_rate_limited_source_raises_retryable(self):
        from tg_parser.ingestion.orchestrator import RetryableError

        future = datetime.now(UTC) + timedelta(minutes=5)
        source = self._make_source(rate_limit_until=future)
        orch, _ = self._make_orchestrator(source)

        with pytest.raises(RetryableError, match="rate-limited"):
            await orch.ingest_source(source_id="ch1", mode="incremental")

    async def test_expired_rate_limit_proceeds(self):
        past = datetime.now(UTC) - timedelta(minutes=5)
        source = self._make_source(rate_limit_until=past)
        orch, state_repo = self._make_orchestrator(source)

        # It should proceed past the rate limit check (may fail later on actual ingestion)
        try:
            await orch.ingest_source(source_id="ch1", mode="incremental")
        except Exception:
            pass

        # The key assertion: get_source was called (we got past the rate_limit check)
        state_repo.get_source.assert_awaited_once_with("ch1")

    async def test_no_rate_limit_proceeds(self):
        source = self._make_source(rate_limit_until=None)
        orch, state_repo = self._make_orchestrator(source)

        try:
            await orch.ingest_source(source_id="ch1", mode="incremental")
        except Exception:
            pass

        state_repo.get_source.assert_awaited_once_with("ch1")

    async def test_maybe_set_rate_limit_flood_wait(self):
        source = self._make_source()
        orch, state_repo = self._make_orchestrator(source)

        error = Exception("A wait of 42 seconds is required (caused by FloodWaitError)")
        await orch._maybe_set_rate_limit(source, error)

        assert source.rate_limit_until is not None
        diff = (source.rate_limit_until - datetime.now(UTC)).total_seconds()
        assert 30 < diff < 50  # ~42 seconds
        state_repo.upsert_source.assert_awaited_once()

    async def test_maybe_set_rate_limit_generic_429(self):
        source = self._make_source()
        orch, state_repo = self._make_orchestrator(source)

        error = Exception("429 Too Many Requests")
        await orch._maybe_set_rate_limit(source, error)

        assert source.rate_limit_until is not None
        diff = (source.rate_limit_until - datetime.now(UTC)).total_seconds()
        assert 290 < diff < 310  # ~300 seconds default

    async def test_maybe_set_rate_limit_no_match(self):
        source = self._make_source()
        orch, state_repo = self._make_orchestrator(source)

        error = Exception("Some random error")
        await orch._maybe_set_rate_limit(source, error)

        assert source.rate_limit_until is None
        state_repo.upsert_source.assert_not_awaited()

    async def test_maybe_set_rate_limit_flood_keyword(self):
        """Bare 'flood' keyword without seconds gets 300s default."""
        source = self._make_source()
        orch, state_repo = self._make_orchestrator(source)

        error = Exception("flood error happened")
        await orch._maybe_set_rate_limit(source, error)

        assert source.rate_limit_until is not None
        diff = (source.rate_limit_until - datetime.now(UTC)).total_seconds()
        assert 290 < diff < 310

    async def test_maybe_set_rate_limit_upsert_fails_gracefully(self):
        """If upsert_source fails, rate_limit_until is still set on object."""
        source = self._make_source()
        orch, state_repo = self._make_orchestrator(source)
        state_repo.upsert_source.side_effect = RuntimeError("DB error")

        error = Exception("A wait of 10 seconds is required")
        await orch._maybe_set_rate_limit(source, error)

        assert source.rate_limit_until is not None


# ---------------------------------------------------------------------------
# 3b. DB pool metrics registration
# ---------------------------------------------------------------------------


class TestDBPoolMetrics:
    def test_register_pool_metrics_attaches_listeners(self):
        """_register_pool_metrics attaches checkout/checkin listeners to each pool."""

        from tg_parser.storage.sqlalchemy.database import Database

        db = Database.__new__(Database)
        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 0

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        db.ingestion_state_engine = mock_engine
        db.raw_storage_engine = mock_engine
        db.processing_storage_engine = mock_engine

        with patch("tg_parser.storage.sqlalchemy.database.event") as mock_event:
            with patch("tg_parser.storage.sqlalchemy.database.DB_CONNECTIONS_ACTIVE", create=True):
                db._register_pool_metrics()

        # 3 engines × 2 events (checkout + checkin) = 6 listen calls
        assert mock_event.listen.call_count == 6


# ---------------------------------------------------------------------------
# 4. LLM response cache
# ---------------------------------------------------------------------------


class TestLLMResponseCache:
    def test_put_and_get(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", "s", 0.0, 4096, "result")
        assert cache.get("p", "s", 0.0, 4096) == "result"

    def test_miss_different_prompt(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p1", "s", 0.0, 4096, "r1")
        assert cache.get("p2", "s", 0.0, 4096) is None

    def test_miss_different_temperature(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", "s", 0.0, 4096, "r")
        assert cache.get("p", "s", 0.5, 4096) is None

    def test_ttl_expiry(self):
        cache = LLMResponseCache(ttl_seconds=0.001)
        cache.put("p", "s", 0.0, 4096, "r")
        time.sleep(0.01)
        assert cache.get("p", "s", 0.0, 4096) is None

    def test_max_entries_eviction(self):
        cache = LLMResponseCache(ttl_seconds=60, max_entries=2)
        cache.put("p1", "s", 0.0, 4096, "r1")
        cache.put("p2", "s", 0.0, 4096, "r2")
        cache.put("p3", "s", 0.0, 4096, "r3")
        assert cache.stats()["size"] == 2
        assert cache.get("p3", "s", 0.0, 4096) == "r3"

    def test_clear(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", "s", 0.0, 4096, "r")
        cache.clear()
        assert cache.get("p", "s", 0.0, 4096) is None
        assert cache.stats()["size"] == 0

    def test_stats(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", "s", 0.0, 4096, "r")
        cache.get("p", "s", 0.0, 4096)  # hit
        cache.get("other", "s", 0.0, 4096)  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_none_system_prompt(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", None, 0.0, 4096, "r")
        assert cache.get("p", None, 0.0, 4096) == "r"

    def test_stats_zero_calls(self):
        cache = LLMResponseCache()
        stats = cache.stats()
        assert stats["hit_rate"] == 0.0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_evict_expired_on_put_full(self):
        """When cache is full and expired entries exist, evict them first."""
        cache = LLMResponseCache(ttl_seconds=0.001, max_entries=2)
        cache.put("p1", "s", 0.0, 4096, "r1")
        cache.put("p2", "s", 0.0, 4096, "r2")
        time.sleep(0.01)  # let both expire
        cache.put("p3", "s", 0.0, 4096, "r3")
        assert cache.stats()["size"] == 1
        assert cache.get("p3", "s", 0.0, 4096) == "r3"

    def test_different_max_tokens_is_separate_key(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", "s", 0.0, 4096, "r1")
        cache.put("p", "s", 0.0, 8192, "r2")
        assert cache.get("p", "s", 0.0, 4096) == "r1"
        assert cache.get("p", "s", 0.0, 8192) == "r2"

    def test_overwrite_same_key(self):
        cache = LLMResponseCache(ttl_seconds=60)
        cache.put("p", "s", 0.0, 4096, "old")
        cache.put("p", "s", 0.0, 4096, "new")
        assert cache.get("p", "s", 0.0, 4096) == "new"

    def test_global_singleton(self):
        from tg_parser.processing.llm.response_cache import get_llm_cache

        c1 = get_llm_cache()
        c2 = get_llm_cache()
        assert c1 is c2


# ---------------------------------------------------------------------------
# 4b. InstrumentedLLMClient cache integration
# ---------------------------------------------------------------------------


class TestInstrumentedCacheIntegration:
    async def test_cache_hit_skips_api_call(self):
        from tg_parser.processing.llm.instrumented import InstrumentedLLMClient
        from tg_parser.processing.llm.response_cache import LLMResponseCache

        mock_client = AsyncMock()
        instrumented = InstrumentedLLMClient(mock_client, provider="openai", model="gpt-4o")
        instrumented._cache = LLMResponseCache(ttl_seconds=60)

        # Pre-populate cache
        instrumented._cache.put("hello", None, 0.0, 4096, "cached_response")

        with patch("tg_parser.processing.llm.instrumented.record_llm_request"):
            result = await instrumented.generate("hello")

        assert result == "cached_response"
        mock_client.generate.assert_not_awaited()

    async def test_cache_miss_calls_api_and_caches(self):
        from tg_parser.processing.llm.instrumented import InstrumentedLLMClient
        from tg_parser.processing.llm.response_cache import LLMResponseCache

        mock_client = AsyncMock()
        mock_client.generate.return_value = "api_response"
        instrumented = InstrumentedLLMClient(mock_client, provider="openai", model="gpt-4o")
        instrumented._cache = LLMResponseCache(ttl_seconds=60)

        with patch("tg_parser.processing.llm.instrumented.record_llm_request"):
            result = await instrumented.generate("hello")

        assert result == "api_response"
        mock_client.generate.assert_awaited_once()
        assert instrumented._cache.get("hello", None, 0.0, 4096) == "api_response"

    async def test_api_error_not_cached(self):
        from tg_parser.processing.llm.instrumented import InstrumentedLLMClient
        from tg_parser.processing.llm.response_cache import LLMResponseCache

        mock_client = AsyncMock()
        mock_client.generate.side_effect = RuntimeError("API down")
        instrumented = InstrumentedLLMClient(mock_client, provider="openai", model="gpt-4o")
        instrumented._cache = LLMResponseCache(ttl_seconds=60)

        with patch("tg_parser.processing.llm.instrumented.record_llm_request"):
            with pytest.raises(RuntimeError, match="API down"):
                await instrumented.generate("hello")

        assert instrumented._cache.get("hello", None, 0.0, 4096) is None


# ---------------------------------------------------------------------------
# 5. JobStore shared engine
# ---------------------------------------------------------------------------


class TestJobStoreSharedEngine:
    async def test_jobstore_does_not_create_own_engine(self):
        """JobStore.init() reuses Database.processing_storage_engine."""
        from tg_parser.api.job_store import JobStore
        from tg_parser.storage.sqlalchemy import Database

        JobStore.reset()
        Database.reset_instance()

        mock_engine = AsyncMock()
        mock_engine.begin = MagicMock()

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            store = JobStore.get_instance()
            # Patch out _init_schema to avoid DB calls
            with patch.object(store, "_init_schema", new=AsyncMock()):
                await store.init()

        assert store._engine is mock_engine
        assert store._owns_engine is False

        JobStore.reset()
        Database.reset_instance()

    async def test_jobstore_close_does_not_dispose_shared_engine(self):
        """When _owns_engine is False, close() must NOT call engine.dispose()."""
        from tg_parser.api.job_store import JobStore
        from tg_parser.storage.sqlalchemy import Database

        JobStore.reset()
        Database.reset_instance()

        mock_engine = AsyncMock()
        mock_engine.begin = MagicMock()

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            store = JobStore.get_instance()
            with patch.object(store, "_init_schema", new=AsyncMock()):
                await store.init()

        await store.close()
        mock_engine.dispose.assert_not_awaited()

        JobStore.reset()
        Database.reset_instance()

    async def test_jobstore_init_idempotent(self):
        """Second call to init() is a no-op."""
        from tg_parser.api.job_store import JobStore
        from tg_parser.storage.sqlalchemy import Database

        JobStore.reset()
        Database.reset_instance()

        mock_engine = AsyncMock()
        mock_engine.begin = MagicMock()

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            store = JobStore.get_instance()
            with patch.object(store, "_init_schema", new=AsyncMock()) as mock_schema:
                await store.init()
                await store.init()  # second call

        mock_schema.assert_awaited_once()

        JobStore.reset()
        Database.reset_instance()


# ---------------------------------------------------------------------------
# 6. Bot health server
# ---------------------------------------------------------------------------


class TestBotHealthServer:
    async def _request(self, port: int, request_line: bytes) -> str:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(request_line + b"Host: localhost\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            return data.decode("utf-8", errors="replace")
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_health_server_starts_and_responds(self):
        from tg_parser.bot.main import BOT_HEALTH_PORT, _start_health_server

        server = await _start_health_server()
        assert server is not None

        try:
            response = await self._request(
                BOT_HEALTH_PORT,
                b"GET /health HTTP/1.1\r\n",
            )
            assert "200 OK" in response
            assert "Content-Type: application/json" in response
            assert '"status":"ok"' in response
        finally:
            server.close()
            await server.wait_closed()

    async def test_metrics_endpoint_returns_prometheus_text(self):
        """TD-bot-prometheus-scrape (#53): /metrics serves prometheus text format."""
        # Importing api.metrics registers all bot-relevant counters
        # (BOT_GEMINI_EMPTY_PARTS_TOTAL etc.) into the default REGISTRY.
        from tg_parser.api.metrics import BOT_GEMINI_EMPTY_PARTS_TOTAL
        from tg_parser.bot.main import BOT_HEALTH_PORT, _start_health_server

        BOT_GEMINI_EMPTY_PARTS_TOTAL.labels(model="gemini-2.5-flash", finish_reason="STOP").inc(0)

        server = await _start_health_server()
        assert server is not None

        try:
            response = await self._request(
                BOT_HEALTH_PORT,
                b"GET /metrics HTTP/1.1\r\n",
            )
            assert "200 OK" in response
            assert "text/plain" in response.lower()
            assert "tg_bot_gemini_empty_parts_total" in response
            assert "# HELP tg_bot_gemini_empty_parts_total" in response
        finally:
            server.close()
            await server.wait_closed()

    async def test_metrics_endpoint_handles_query_string(self):
        """Path normalisation: ``/metrics?since=1d`` resolves the same as ``/metrics``."""
        from tg_parser.bot.main import BOT_HEALTH_PORT, _start_health_server

        server = await _start_health_server()
        assert server is not None

        try:
            response = await self._request(
                BOT_HEALTH_PORT,
                b"GET /metrics?ts=42 HTTP/1.1\r\n",
            )
            assert "200 OK" in response
            assert "text/plain" in response.lower()
        finally:
            server.close()
            await server.wait_closed()

    async def test_unknown_path_returns_404(self):
        """Read-only HTTP surface: anything other than /health and /metrics is 404."""
        from tg_parser.bot.main import BOT_HEALTH_PORT, _start_health_server

        server = await _start_health_server()
        assert server is not None

        try:
            response = await self._request(
                BOT_HEALTH_PORT,
                b"GET /admin HTTP/1.1\r\n",
            )
            assert "404 Not Found" in response
            assert '"error":"not_found"' in response
        finally:
            server.close()
            await server.wait_closed()

    async def test_post_method_returns_404(self):
        """Bot HTTP surface is read-only; POST /metrics is 404 (not 405)."""
        from tg_parser.bot.main import BOT_HEALTH_PORT, _start_health_server

        server = await _start_health_server()
        assert server is not None

        try:
            response = await self._request(
                BOT_HEALTH_PORT,
                b"POST /metrics HTTP/1.1\r\n",
            )
            assert "404 Not Found" in response
        finally:
            server.close()
            await server.wait_closed()

    async def test_malformed_request_returns_404(self):
        """Robustness: garbage on the wire does not crash the handler."""
        from tg_parser.bot.main import BOT_HEALTH_PORT, _start_health_server

        server = await _start_health_server()
        assert server is not None

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", BOT_HEALTH_PORT)
            writer.write(b"\xff\xfe\x00\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            response = data.decode("utf-8", errors="replace")
            assert "404 Not Found" in response
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


# ---------------------------------------------------------------------------
# 7. Factory wires max_retries
# ---------------------------------------------------------------------------


class TestFactoryRetryWiring:
    def test_openai_gets_max_retries(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "openai",
            api_key="sk-test",
            model="gpt-4o",
            instrument=False,
            max_retries=7,
        )
        assert client._max_retries == 7

    def test_gemini_gets_max_retries(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "gemini",
            api_key="test-key",
            model="gemini-2.0-flash",
            instrument=False,
            max_retries=4,
        )
        assert client._max_retries == 4

    def test_default_max_retries_is_5(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "openai",
            api_key="sk-test",
            instrument=False,
        )
        assert client._max_retries == 5

    def test_anthropic_gets_max_retries(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "anthropic",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
            instrument=False,
            max_retries=7,
        )
        assert client._max_retries == 7

    def test_ollama_gets_max_retries(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "ollama",
            model="llama3.2",
            instrument=False,
            max_retries=4,
        )
        assert client._max_retries == 4

    def test_ollama_default_max_retries_is_5(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "ollama",
            instrument=False,
        )
        assert client._max_retries == 5


# ---------------------------------------------------------------------------
# 8. Anthropic retry (F8-A Phase 1)
# ---------------------------------------------------------------------------


class TestAnthropicRetry:
    def _make_client(self, max_retries=3, rate_limiter=None):
        from tg_parser.processing.llm.anthropic_client import AnthropicClient

        return AnthropicClient(
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
            max_retries=max_retries,
            rate_limiter=rate_limiter,
        )

    def _ok_resp(self, text="ok"):
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.headers = {}
        resp.json.return_value = {
            "content": [{"text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        return resp

    def _fail_resp(self, status_code, headers=None):
        resp = Mock()
        resp.status_code = status_code
        resp.headers = headers or {}
        resp.text = f"error {status_code}"
        resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                str(status_code),
                request=Mock(),
                response=resp,
            )
        )
        return resp

    async def test_success_no_retry(self):
        client = self._make_client()
        mock_post = AsyncMock(return_value=self._ok_resp())
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 1

    async def test_429_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(429, {"retry-after": "0.01"}),
                self._ok_resp("recovered"),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "recovered"
        assert mock_post.call_count == 2

    async def test_500_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(500),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"

    async def test_502_retries_then_succeeds(self):
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(502),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"

    async def test_503_retries_then_succeeds(self):
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(503),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"

    async def test_529_overloaded_retries_then_succeeds(self):
        """529 is Anthropic's overloaded status — must be retried."""
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(529),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"

    async def test_520_retries_then_succeeds(self):
        """BUG-020: 520 (Cloudflare edge error) must retry with 5xx backoff."""
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(520),
                self._ok_resp("recovered"),
            ]
        )
        sleep_calls: list[float] = []

        async def _fake_sleep(delay):
            sleep_calls.append(delay)

        with (
            patch.object(client._client, "post", mock_post),
            patch(
                "tg_parser.processing.llm.anthropic_client.asyncio.sleep",
                side_effect=_fake_sleep,
            ),
        ):
            result = await client.generate("test")
        assert result == "recovered"
        assert mock_post.call_count == 2
        # Exactly one exp-backoff sleep with a strictly positive delay.
        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0

    async def test_exhausted_retries_raises(self):
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(return_value=self._fail_resp(500))
        with patch.object(client._client, "post", mock_post):
            with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
                await client.generate("test")
        assert mock_post.call_count == 2

    async def test_400_not_retried(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(return_value=self._fail_resp(400))
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await client.generate("test")
        assert mock_post.call_count == 1

    async def test_network_error_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    async def test_network_error_exhausted_raises(self):
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(httpx.ConnectError):
                await client.generate("test")
        assert mock_post.call_count == 2

    async def test_parse_error_not_retried(self):
        """json.JSONDecodeError / KeyError / TypeError are never retried."""
        client = self._make_client(max_retries=3)
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.json.return_value = {"unexpected": "format"}
        mock_post = AsyncMock(return_value=resp)
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(KeyError):
                await client.generate("test")
        assert mock_post.call_count == 1

    async def test_rate_limiter_refund_on_retryable(self):
        """rate_limiter.refund_acquire is called for any retryable status."""
        mock_rl = AsyncMock()
        client = self._make_client(max_retries=3, rate_limiter=mock_rl)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(500),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            await client.generate("test")
        mock_rl.refund_acquire.assert_awaited_once()

    async def test_rate_limiter_refund_on_429(self):
        """rate_limiter.refund_acquire is called on 429 as well."""
        mock_rl = AsyncMock()
        client = self._make_client(max_retries=3, rate_limiter=mock_rl)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(429, {"retry-after": "0.01"}),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            await client.generate("test")
        mock_rl.refund_acquire.assert_awaited_once()

    def test_parse_retry_after_header(self):
        from tg_parser.processing.llm.anthropic_client import _parse_retry_after_seconds

        resp = Mock()
        resp.headers = {"retry-after": "15"}
        assert _parse_retry_after_seconds(resp) == 15.0

    def test_parse_retry_after_missing_defaults_60(self):
        from tg_parser.processing.llm.anthropic_client import _parse_retry_after_seconds

        resp = Mock()
        resp.headers = {}
        assert _parse_retry_after_seconds(resp) == 60.0

    def test_parse_retry_after_invalid_defaults_60(self):
        from tg_parser.processing.llm.anthropic_client import _parse_retry_after_seconds

        resp = Mock()
        resp.headers = {"retry-after": "not-a-number"}
        assert _parse_retry_after_seconds(resp) == 60.0

    def test_parse_retry_after_clamps_to_1(self):
        from tg_parser.processing.llm.anthropic_client import _parse_retry_after_seconds

        resp = Mock()
        resp.headers = {"retry-after": "0.001"}
        assert _parse_retry_after_seconds(resp) == 1.0

    def test_compute_retry_delay_429_uses_retry_after(self):
        from tg_parser.processing.llm.anthropic_client import _compute_retry_delay

        resp = Mock()
        resp.status_code = 429
        resp.headers = {"retry-after": "20"}
        assert _compute_retry_delay(resp, 1) == 20.0

    def test_compute_retry_delay_5xx_uses_backoff(self):
        from tg_parser.processing.llm.anthropic_client import _compute_retry_delay

        resp = Mock()
        resp.status_code = 500
        resp.headers = {}
        delay = _compute_retry_delay(resp, 2)
        assert 4.0 <= delay <= 5.2

    def test_compute_retry_delay_caps_at_60(self):
        from tg_parser.processing.llm.anthropic_client import _compute_retry_delay

        resp = Mock()
        resp.status_code = 503
        resp.headers = {}
        delay = _compute_retry_delay(resp, 10)
        assert delay <= 60 * 1.3 + 1

    def test_max_retries_stored(self):
        client = self._make_client(max_retries=7)
        assert client._max_retries == 7


# ---------------------------------------------------------------------------
# 9. Ollama retry (F8-A Phase 2)
# ---------------------------------------------------------------------------


class TestOllamaRetry:
    def _make_client(self, max_retries=3):
        from tg_parser.processing.llm.ollama_client import OllamaClient

        return OllamaClient(model="llama3.2", max_retries=max_retries)

    def _ok_resp(self, text="ok"):
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.headers = {}
        resp.json.return_value = {
            "choices": [{"message": {"content": text}}],
        }
        return resp

    def _fail_resp(self, status_code, headers=None):
        resp = Mock()
        resp.status_code = status_code
        resp.headers = headers or {}
        resp.text = f"error {status_code}"
        resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                str(status_code),
                request=Mock(),
                response=resp,
            )
        )
        return resp

    async def test_success_no_retry(self):
        client = self._make_client()
        mock_post = AsyncMock(return_value=self._ok_resp())
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 1

    async def test_429_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(429, {"retry-after": "0.01"}),
                self._ok_resp("recovered"),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "recovered"
        assert mock_post.call_count == 2

    async def test_500_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                self._fail_resp(500),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    async def test_network_error_retries_then_succeeds(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                self._ok_resp(),
            ]
        )
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    async def test_network_error_exhausted_raises(self):
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(httpx.ConnectError):
                await client.generate("test")
        assert mock_post.call_count == 2

    async def test_exhausted_retries_raises(self):
        client = self._make_client(max_retries=2)
        mock_post = AsyncMock(return_value=self._fail_resp(500))
        with patch.object(client._client, "post", mock_post):
            with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
                await client.generate("test")
        assert mock_post.call_count == 2

    async def test_400_not_retried(self):
        client = self._make_client(max_retries=3)
        mock_post = AsyncMock(return_value=self._fail_resp(400))
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(httpx.HTTPStatusError):
                await client.generate("test")
        assert mock_post.call_count == 1

    async def test_parse_error_not_retried(self):
        """Invalid response structure raises ValueError, no retry."""
        client = self._make_client(max_retries=3)
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.json.return_value = {"unexpected": "format"}
        mock_post = AsyncMock(return_value=resp)
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(ValueError, match="Invalid Ollama response"):
                await client.generate("test")
        assert mock_post.call_count == 1

    async def test_json_decode_error_not_retried(self):
        """Malformed JSON body is not retried."""
        client = self._make_client(max_retries=3)
        resp = Mock()
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
        mock_post = AsyncMock(return_value=resp)
        with patch.object(client._client, "post", mock_post):
            with pytest.raises(json.JSONDecodeError):
                await client.generate("test")
        assert mock_post.call_count == 1

    def test_max_retries_stored(self):
        client = self._make_client(max_retries=6)
        assert client._max_retries == 6

    def test_compute_delay_with_retry_after_header(self):
        from tg_parser.processing.llm.ollama_client import OllamaClient

        resp = Mock()
        resp.headers = {"retry-after": "20"}
        delay = OllamaClient._compute_delay(resp, 1)
        assert delay == 20.0

    def test_compute_delay_exponential_backoff(self):
        from tg_parser.processing.llm.ollama_client import OllamaClient

        resp = Mock()
        resp.headers = {}
        delay = OllamaClient._compute_delay(resp, 2)
        assert 4.0 <= delay <= 5.2

    def test_compute_delay_invalid_header_fallback(self):
        from tg_parser.processing.llm.ollama_client import OllamaClient

        resp = Mock()
        resp.headers = {"retry-after": "invalid"}
        delay = OllamaClient._compute_delay(resp, 3)
        assert 8.0 <= delay <= 10.4


# ---------------------------------------------------------------------------
# 10. Health DB ping (F8-A Phase 3)
# ---------------------------------------------------------------------------


class TestHealthDBPing:
    async def test_healthy_db(self):
        from tg_parser.api.routes.health import _check_db_ping
        from tg_parser.storage.sqlalchemy.database import Database

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            result = await _check_db_ping()
        assert result == "ok"

    async def test_degraded_db_unreachable(self):
        from tg_parser.api.routes.health import _check_db_ping
        from tg_parser.storage.sqlalchemy.database import Database

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(
            side_effect=ConnectionError("cannot connect"),
        )

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            result = await _check_db_ping()
        assert result == "unreachable"

    async def test_not_initialized(self):
        from tg_parser.api.routes.health import _check_db_ping
        from tg_parser.storage.sqlalchemy.database import Database

        mock_db = MagicMock()
        mock_db._initialized = False

        with patch.object(Database, "get_instance", return_value=mock_db):
            result = await _check_db_ping()
        assert result == "not_initialized"

    async def test_engine_none_returns_not_initialized(self):
        """_initialized=True but engine is None → not_initialized."""
        from tg_parser.api.routes.health import _check_db_ping
        from tg_parser.storage.sqlalchemy.database import Database

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = None

        with patch.object(Database, "get_instance", return_value=mock_db):
            result = await _check_db_ping()
        assert result == "not_initialized"

    async def test_sqlalchemy_error_returns_unreachable(self):
        """SQLAlchemy-level error during SELECT 1 → unreachable."""
        from sqlalchemy.exc import OperationalError

        from tg_parser.api.routes.health import _check_db_ping
        from tg_parser.storage.sqlalchemy.database import Database

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock(
            side_effect=OperationalError("select", {}, Exception("conn lost")),
        )

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            result = await _check_db_ping()
        assert result == "unreachable"

    async def test_timeout_returns_unreachable(self):
        """If SELECT 1 takes >3s, asyncio.TimeoutError → unreachable."""
        from tg_parser.api.routes.health import _check_db_ping
        from tg_parser.storage.sqlalchemy.database import Database

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = slow_execute

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        mock_db = MagicMock()
        mock_db._initialized = True
        mock_db.processing_storage_engine = mock_engine

        with patch.object(Database, "get_instance", return_value=mock_db):
            result = await _check_db_ping()
        assert result == "unreachable"

    async def test_health_endpoint_returns_200_degraded(self):
        """Full endpoint: degraded DB still returns HTTP 200."""
        from tg_parser.api.routes.health import health_check

        with patch(
            "tg_parser.api.routes.health._check_db_ping", new=AsyncMock(return_value="unreachable")
        ):
            resp = await health_check()
        assert resp.status == "degraded"
        assert resp.database == "unreachable"

    async def test_health_endpoint_returns_200_ok(self):
        from tg_parser.api.routes.health import health_check

        with patch("tg_parser.api.routes.health._check_db_ping", new=AsyncMock(return_value="ok")):
            resp = await health_check()
        assert resp.status == "ok"
        assert resp.database == "ok"

    async def test_health_endpoint_not_initialized_is_degraded(self):
        from tg_parser.api.routes.health import health_check

        with patch(
            "tg_parser.api.routes.health._check_db_ping",
            new=AsyncMock(return_value="not_initialized"),
        ):
            resp = await health_check()
        assert resp.status == "degraded"
        assert resp.database == "not_initialized"


# ---------------------------------------------------------------------------
# 11. Scheduler metric not doubled (F8-A Phase 4)
# ---------------------------------------------------------------------------


class TestSchedulerMetricNotDoubled:
    async def test_incremental_pipeline_task_does_not_call_record(self):
        """incremental_pipeline_task must NOT call record_scheduler_task directly."""
        mock_record = MagicMock()

        with (
            patch(
                "tg_parser.services.scheduler_service.run_incremental_for_all_sources",
                new=AsyncMock(return_value={"sources_succeeded": 0, "sources_failed": 0}),
            ),
            patch("tg_parser.api.metrics.record_scheduler_task", mock_record),
        ):
            from tg_parser.services.scheduler_service import incremental_pipeline_task

            await incremental_pipeline_task()

        mock_record.assert_not_called()

    async def test_wrapper_calls_record_once_on_success(self):
        """BackgroundScheduler.add_task wrapper calls record_scheduler_task exactly once on success."""
        from tg_parser.services.background_scheduler import BackgroundScheduler

        scheduler = BackgroundScheduler()
        mock_func = AsyncMock()
        calls = []

        def counting_record(task_name=None, task_id=None, success=True):
            calls.append(success)

        scheduler.add_task(
            task_id="test_task",
            func=mock_func,
            interval_seconds=3600,
        )

        job = scheduler._scheduler.get_job("test_task")
        with patch("tg_parser.api.metrics.record_scheduler_task", side_effect=counting_record):
            await job.func()

        assert len(calls) == 1
        assert calls[0] is True
        mock_func.assert_awaited_once()

    async def test_wrapper_calls_record_once_on_failure(self):
        """On task exception, wrapper calls record_scheduler_task(success=False) exactly once."""
        from tg_parser.services.background_scheduler import BackgroundScheduler

        scheduler = BackgroundScheduler()
        mock_func = AsyncMock(side_effect=RuntimeError("boom"))
        calls = []

        def counting_record(task_name=None, task_id=None, success=True):
            calls.append(success)

        scheduler.add_task(
            task_id="failing_task",
            func=mock_func,
            interval_seconds=3600,
        )

        job = scheduler._scheduler.get_job("failing_task")
        with patch("tg_parser.api.metrics.record_scheduler_task", side_effect=counting_record):
            await job.func()

        assert len(calls) == 1
        assert calls[0] is False

    async def test_incremental_task_exception_propagates(self):
        """When run_incremental_for_all_sources raises, the exception propagates."""
        with patch(
            "tg_parser.services.scheduler_service.run_incremental_for_all_sources",
            new=AsyncMock(side_effect=RuntimeError("pipeline failed")),
        ):
            from tg_parser.services.scheduler_service import incremental_pipeline_task

            with pytest.raises(RuntimeError, match="pipeline failed"):
                await incremental_pipeline_task()
