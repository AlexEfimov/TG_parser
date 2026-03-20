"""Tests for Session 27 LLMRateLimiter."""

import asyncio
import time

import pytest
from httpx import Headers

from tg_parser.processing.llm.rate_limiter import LLMRateLimiter


@pytest.mark.asyncio
async def test_acquire_allows_immediate_when_bucket_full():
    lim = LLMRateLimiter(rpm=60, input_tokens_per_minute=10_000, output_tokens_per_minute=4_000)
    t0 = time.monotonic()
    await lim.acquire(100, 50)
    assert time.monotonic() - t0 < 0.2


@pytest.mark.asyncio
async def test_acquire_waits_when_request_bucket_empty():
    lim = LLMRateLimiter(rpm=120, input_tokens_per_minute=60_000, output_tokens_per_minute=60_000)
    for _ in range(120):
        await lim.acquire(0, 0)
    t0 = time.monotonic()
    await asyncio.wait_for(lim.acquire(0, 0), timeout=3.0)
    assert time.monotonic() - t0 > 0.25


@pytest.mark.asyncio
async def test_refund_restores_tokens():
    lim = LLMRateLimiter(rpm=60, input_tokens_per_minute=1000, output_tokens_per_minute=1000)
    before = lim._in_tokens  # noqa: SLF001
    await lim.acquire(500, 100)
    after_acquire = lim._in_tokens  # noqa: SLF001
    assert after_acquire < before
    await lim.refund_acquire(500, 100)
    assert lim._in_tokens >= before - 1e-6  # noqa: SLF001


@pytest.mark.asyncio
async def test_sync_remaining_from_headers_clamps_bucket():
    lim = LLMRateLimiter(rpm=100, input_tokens_per_minute=10_000, output_tokens_per_minute=4_000)
    h = Headers(
        {
            "anthropic-ratelimit-requests-remaining": "3",
            "anthropic-ratelimit-input-tokens-remaining": "500",
            "anthropic-ratelimit-output-tokens-remaining": "200",
        }
    )
    await lim.sync_remaining_from_headers(h)
    assert lim._req_tokens <= 3  # noqa: SLF001
    assert lim._in_tokens <= 500  # noqa: SLF001
    assert lim._out_tokens <= 200  # noqa: SLF001


def test_suggested_parallel_cap_without_snapshot():
    lim = LLMRateLimiter(rpm=60, input_tokens_per_minute=1000, output_tokens_per_minute=1000)
    assert lim.suggested_parallel_cap(10) == 10


def test_suggested_parallel_cap_with_low_remaining():
    lim = LLMRateLimiter(rpm=60, input_tokens_per_minute=1000, output_tokens_per_minute=1000)
    lim._last_requests_remaining = 4.0  # noqa: SLF001
    assert lim.suggested_parallel_cap(20) == 2  # int(4 * 0.6) = 2


@pytest.mark.asyncio
async def test_reconcile_usage_returns_overestimated_tokens():
    lim = LLMRateLimiter(rpm=60, input_tokens_per_minute=10_000, output_tokens_per_minute=4_000)
    await lim.acquire(2000, 500)
    in_before = lim._in_tokens  # noqa: SLF001
    await lim.reconcile_usage(2000, 500, 800, 200)
    assert lim._in_tokens > in_before  # noqa: SLF001
