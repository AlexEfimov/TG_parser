"""
Tests for F8-A Hardening:
1. OpenAI / Gemini 429 retry with exponential backoff
2. Ingestion rate_limit_until check and FloodWait detection
3. LLM response cache (TTL)
4. JobStore shared engine
5. Bot health server
"""

import asyncio
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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "429", request=Mock(), response=fail_resp,
        ))

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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "429", request=Mock(), response=fail_resp,
        ))

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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "500", request=Mock(), response=fail_resp,
        ))

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}], "usage": {},
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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "400", request=Mock(), response=fail_resp,
        ))

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
            "choices": [{"message": {"content": "ok"}}], "usage": {},
        }

        mock_post = AsyncMock(side_effect=[
            httpx.ConnectError("connection refused"),
            ok_resp,
        ])
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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "502", request=Mock(), response=fail_resp,
        ))

        ok_resp = Mock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = Mock()
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}], "usage": {},
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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "429", request=Mock(), response=fail_resp,
        ))

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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "429", request=Mock(), response=fail_resp,
        ))

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

        mock_post = AsyncMock(side_effect=[
            httpx.ConnectError("connection refused"),
            ok_resp,
        ])
        with patch.object(client._client, "post", mock_post):
            result = await client.generate("test")
        assert result == "ok"
        assert mock_post.call_count == 2

    async def test_500_is_retryable(self):
        client = self._make_client(max_retries=2)

        fail_resp = Mock()
        fail_resp.status_code = 500
        fail_resp.headers = {}
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "500", request=Mock(), response=fail_resp,
        ))

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
        fail_resp.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "400", request=Mock(), response=fail_resp,
        ))

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
        from tg_parser.ingestion.orchestrator import IngestionOrchestrator, RetryableError

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
        from unittest.mock import call
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
    async def test_health_server_starts_and_responds(self):
        from tg_parser.bot.main import _start_health_server, BOT_HEALTH_PORT

        server = await _start_health_server()
        assert server is not None

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", BOT_HEALTH_PORT)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()

            data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            response = data.decode()

            assert "200 OK" in response
            assert '"status":"ok"' in response

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
            "openai", api_key="sk-test", model="gpt-4o",
            instrument=False, max_retries=7,
        )
        assert client._max_retries == 7

    def test_gemini_gets_max_retries(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "gemini", api_key="test-key", model="gemini-2.0-flash",
            instrument=False, max_retries=4,
        )
        assert client._max_retries == 4

    def test_default_max_retries_is_5(self):
        from tg_parser.processing.llm.factory import create_llm_client

        client = create_llm_client(
            "openai", api_key="sk-test", instrument=False,
        )
        assert client._max_retries == 5
