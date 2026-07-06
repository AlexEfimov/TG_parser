"""BUG-080: streaming (SSE) code path for AnthropicClient.

These tests mock the httpx transport — NO live Anthropic API is hit. They prove
the flag-gated streaming path (``stream=true``) parses the Messages API
``text/event-stream`` into the SAME ``LLMResponse`` contract as the
non-streaming path, that a mid-stream stall surfaces the read timeout FAST
(well before the aggregate ``call_timeout``), that truncation is still detected,
and that with streaming OFF (default) the non-streaming path is untouched.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from tg_parser.processing.llm.anthropic_client import AnthropicClient
from tg_parser.processing.llm.errors import AnthropicBillingError


def _sse(event_type: str, data: dict) -> bytes:
    """Format one Anthropic SSE frame (``event:`` + ``data:`` + blank line)."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode()


class _CannedStream(httpx.AsyncByteStream):
    """Yield a fixed list of byte chunks as an httpx streaming body."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        pass


class _StallStream(httpx.AsyncByteStream):
    """Emit ``message_start`` then stall and surface a read timeout.

    MockTransport does not go through the real connection pool, so httpx cannot
    enforce a wall-clock read timeout on a canned stream. We therefore emulate
    what the httpx read timeout would raise on a genuinely dead socket: emit the
    first frame, pause briefly, then raise ``httpx.ReadTimeout``. This proves our
    code surfaces the per-attempt read timeout FAST rather than blocking to the
    aggregate ``call_timeout``.
    """

    def __init__(self, stall_s: float = 0.05):
        self._stall_s = stall_s

    async def __aiter__(self):
        yield _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}})
        await asyncio.sleep(self._stall_s)
        raise httpx.ReadTimeout("simulated inter-chunk stall")

    async def aclose(self) -> None:
        pass


class _FakeRateLimiter:
    """Minimal LLMRateLimiter stand-in recording reservation accounting.

    Tracks how many times each accounting hook fired so tests can assert the
    refund-once invariant (a retried attempt refunds; a successful attempt
    reconciles) without touching real token-bucket state.
    """

    def __init__(self):
        self.acquired = 0
        self.refunded = 0
        self.reconciled = 0
        self.synced = 0

    async def acquire(self, in_est: int, out_est: int) -> None:
        self.acquired += 1

    async def refund_acquire(self, in_est: int, out_est: int) -> None:
        self.refunded += 1

    async def reconcile_usage(self, in_est, out_est, in_actual, out_actual) -> None:
        self.reconciled += 1

    async def sync_remaining_from_headers(self, headers) -> None:
        self.synced += 1


def _streaming_client(
    handler,
    *,
    max_retries: int = 1,
    call_timeout: float | None = None,
    rate_limiter=None,
) -> AnthropicClient:
    client = AnthropicClient(
        api_key="test",
        max_retries=max_retries,
        streaming=True,
        call_timeout=call_timeout,
        rate_limiter=rate_limiter,
    )
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


_HAPPY_CHUNKS = [
    _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}}),
    _sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "streamed "}}),
    _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "world"}}),
    _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 42}}),
    _sse("message_stop", {"type": "message_stop"}),
]


@pytest.mark.asyncio
async def test_streaming_sse_happy_path():
    """Text == concatenated deltas; input from message_start; output from final
    message_delta (cumulative, NOT summed); stop_reason == end_turn."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    client = _streaming_client(handler)
    try:
        result = await client.generate_with_usage(
            prompt="{}", response_format={"type": "json_object"}
        )
    finally:
        await client.close()

    assert result.text == "Hello streamed world"
    assert result.input_tokens == 8400
    assert result.output_tokens == 42  # final cumulative, not 1 + summed deltas
    assert result.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_streaming_success_with_limiter_never_refunds():
    """A clean streaming success with a limiter reconciles exactly once and
    NEVER refunds — pins the "success never refunds" invariant against the
    Change 1 terminal-refund hoist."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=1, rate_limiter=limiter)
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.text == "Hello streamed world"
    assert limiter.acquired == 1
    assert limiter.refunded == 0
    assert limiter.reconciled == 1


@pytest.mark.asyncio
async def test_streaming_gap_stall_trips_read_timeout_fast():
    """A stalled stream surfaces the read timeout well before the aggregate
    call_timeout (the inter-chunk stall-guard fires FAST)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_StallStream(stall_s=0.05))

    # Aggregate budget is generous (5s) — the per-attempt read timeout must fire
    # long before it. max_retries=1 so the read timeout is not retried.
    client = _streaming_client(handler, max_retries=1, call_timeout=5.0)
    start = time.monotonic()
    try:
        with pytest.raises(httpx.ReadTimeout):
            await client.generate_with_usage(
                prompt="{}", response_format={"type": "json_object"}
            )
    finally:
        await client.close()
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"stall guard should fire fast, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_streaming_healthy_stream_completes_before_budget():
    """Contrast to the stall test: a healthy stream drains quickly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    client = _streaming_client(handler, max_retries=1, call_timeout=5.0)
    start = time.monotonic()
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()
    elapsed = time.monotonic() - start
    assert result.text == "Hello streamed world"
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_streaming_truncation_surfaces_max_tokens_stop_reason():
    """A final message_delta with stop_reason=max_tokens surfaces so the
    topicization shrink-and-retry path still fires (BUG-071)."""

    chunks = [
        _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": '{"topics": ['}}),
        _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 8192}}),
        _sse("message_stop", {"type": "message_stop"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(chunks))

    client = _streaming_client(handler)
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.stop_reason == "max_tokens"
    assert result.output_tokens == 8192
    assert result.text == '{"topics": ['


@pytest.mark.asyncio
async def test_streaming_empty_content_returns_empty_text_not_exception():
    """A stream with no text_delta frames yields '' (mirrors
    _extract_text_content empty-content semantics), never an exception."""

    chunks = [
        _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 0}}}),
        _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 0}}),
        _sse("message_stop", {"type": "message_stop"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(chunks))

    client = _streaming_client(handler)
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.text == ""
    assert result.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_non_streaming_path_unchanged_when_flag_off():
    """Non-regression: with streaming=False (default) the existing
    post()+response.json() path is untouched and returns the same LLMResponse."""

    client = AnthropicClient(api_key="test", max_retries=1)
    assert client._streaming is False
    response = httpx.Response(
        200,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        json={
            "content": [{"type": "text", "text": "Hello streamed world"}],
            "usage": {"input_tokens": 8400, "output_tokens": 42},
            "stop_reason": "end_turn",
        },
    )
    post_mock = AsyncMock(return_value=response)
    client._client.post = post_mock

    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert post_mock.await_count == 1
    assert result.text == "Hello streamed world"
    assert result.input_tokens == 8400
    assert result.output_tokens == 42
    assert result.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_streamed_and_non_streamed_produce_same_llmresponse_shape():
    """Contract-equivalence: given equivalent inputs, the streamed and
    non-streamed paths populate the identical LLMResponse fields, so downstream
    token accounting is unchanged."""

    # Non-streaming
    ns_client = AnthropicClient(api_key="test", max_retries=1)
    ns_response = httpx.Response(
        200,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        json={
            "content": [{"type": "text", "text": "Hello streamed world"}],
            "usage": {"input_tokens": 8400, "output_tokens": 42},
            "stop_reason": "end_turn",
        },
    )
    ns_client._client.post = AsyncMock(return_value=ns_response)
    try:
        ns_result = await ns_client.generate_with_usage(prompt="{}")
    finally:
        await ns_client.close()

    # Streaming
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    s_client = _streaming_client(handler)
    try:
        s_result = await s_client.generate_with_usage(prompt="{}")
    finally:
        await s_client.close()

    assert s_result.text == ns_result.text
    assert s_result.input_tokens == ns_result.input_tokens
    assert s_result.output_tokens == ns_result.output_tokens
    assert s_result.stop_reason == ns_result.stop_reason
    assert s_result.total_tokens == ns_result.total_tokens


@pytest.mark.asyncio
async def test_streaming_billing_400_raises_terminal_and_not_retried():
    """Test A (BUG-080 follow-up): a 400 billing error during the streaming path
    surfaces as a terminal ``AnthropicBillingError`` and is NEVER retried.

    The streaming branch pulls the error body (``await response.aread()``) then
    delegates to ``_handle_error_status``, which is IDENTICAL to the
    non-streaming billing handling. This should PASS with no code change.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your credit balance is too low to access the Claude API",
                }
            },
        )

    client = _streaming_client(handler, max_retries=1)
    try:
        with pytest.raises(AnthropicBillingError):
            await client.generate_with_usage(
                prompt="{}", response_format={"type": "json_object"}
            )
    finally:
        await client.close()

    assert calls == 1, f"billing is terminal, must not retry; got {calls} calls"


@pytest.mark.asyncio
async def test_streaming_429_refunds_then_retries_and_reconciles():
    """Test B (BUG-080 follow-up): a 429 refunds the reservation, retries, and
    the successful retry reconciles usage exactly once."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "1"},
                json={"error": {"type": "rate_limit_error", "message": "Rate limited"}},
            )
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=2, rate_limiter=limiter)
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.text == "Hello streamed world"
    assert calls == 2
    assert limiter.refunded == 1
    assert limiter.reconciled == 1


@pytest.mark.asyncio
async def test_streaming_terminal_5xx_raises_and_refunds_every_attempt():
    """Test C (BUG-080 follow-up): a persistent 503 exhausts retries and raises
    HTTPStatusError.

    Every 503 flows through ``_handle_error_status``, which refunds the pre-flight
    reservation on EVERY retryable attempt (including the terminal one — the
    refund is unconditional, before the ``attempt < max_retries`` check). So the
    reservation is never leaked: ``refunded == acquired == max_retries``. (The
    plan's predicted ``max_retries - 1`` would represent a leak of one
    reservation, contradicting FIX 1's leak-free goal; the actual code is
    already correct here and is left unchanged.)
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503, json={"error": {"type": "overloaded_error", "message": "Overloaded"}}
        )

    max_retries = 2
    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=max_retries, rate_limiter=limiter)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert calls == max_retries
    assert limiter.acquired == max_retries
    assert limiter.refunded == max_retries
    assert limiter.reconciled == 0


@pytest.mark.asyncio
async def test_streaming_midstream_error_event_terminal_raises_http_error():
    """Test D-terminal (BUG-080 follow-up): a mid-stream ``error`` event raises a
    retryable httpx.HTTPError; with max_retries=1 it is terminal.

    Change 1 (terminal-refund symmetry): the terminal attempt now refunds the
    pre-flight reservation before re-raising, so refunded == 1."""

    chunks = [
        _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}}),
        _sse("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(chunks))

    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=1, rate_limiter=limiter)
    try:
        with pytest.raises(httpx.HTTPError):
            await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert limiter.refunded == 1  # Change 1: terminal attempt refunds
    assert limiter.reconciled == 0


@pytest.mark.asyncio
async def test_streaming_midstream_error_event_retries_and_refunds():
    """Test D-retry (BUG-080 follow-up): a mid-stream ``error`` event on the first
    attempt refunds + retries; the healthy retry succeeds."""
    calls = 0
    error_chunks = [
        _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}}),
        _sse("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, stream=_CannedStream(error_chunks))
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=2, rate_limiter=limiter)
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.text == "Hello streamed world"
    assert calls == 2
    assert limiter.refunded == 1


@pytest.mark.asyncio
async def test_streaming_truncated_no_message_delta_terminal_raises():
    """Test E-terminal (BUG-080 follow-up): a stream that drops before the
    terminal ``message_delta`` raises a retryable httpx.RemoteProtocolError
    instead of being accepted as a charged partial success.

    Change 1 (terminal-refund symmetry): the terminal attempt now refunds the
    pre-flight reservation before re-raising, so refunded == 1."""

    chunks = [
        _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": '{"topics": ['}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "..."}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(chunks))

    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=1, rate_limiter=limiter)
    try:
        with pytest.raises(httpx.RemoteProtocolError):
            await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert limiter.refunded == 1  # Change 1: terminal attempt refunds
    assert limiter.reconciled == 0


@pytest.mark.asyncio
async def test_streaming_truncated_then_retry_succeeds_and_refunds():
    """Test E-retry (BUG-080 follow-up): a truncated stream on the first attempt
    refunds + retries; the healthy retry produces the full LLMResponse."""
    calls = 0
    truncated_chunks = [
        _sse("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 8400, "output_tokens": 1}}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": '{"topics": ['}}),
        _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "..."}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, stream=_CannedStream(truncated_chunks))
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    limiter = _FakeRateLimiter()
    client = _streaming_client(handler, max_retries=2, rate_limiter=limiter)
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.text == "Hello streamed world"
    assert result.output_tokens == 42
    assert result.stop_reason == "end_turn"
    assert calls == 2
    assert limiter.refunded == 1


@pytest.mark.asyncio
async def test_non_streaming_network_error_refunds_then_retries_and_reconciles():
    """Non-streaming path (streaming=False): a ``httpx.ConnectError`` on attempt 1
    refunds the reservation + retries; the healthy 200 on attempt 2 reconciles.

    Locks in that the shared ``httpx.HTTPError`` arm behaves identically for the
    non-streaming path (Change 1 refund symmetry applies to both paths)."""

    ok_response = httpx.Response(
        200,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        json={
            "content": [{"type": "text", "text": "Hello streamed world"}],
            "usage": {"input_tokens": 8400, "output_tokens": 42},
            "stop_reason": "end_turn",
        },
    )

    limiter = _FakeRateLimiter()
    client = AnthropicClient(
        api_key="test", max_retries=2, rate_limiter=limiter
    )
    assert client._streaming is False
    client._client.post = AsyncMock(
        side_effect=[httpx.ConnectError("simulated connect failure"), ok_response]
    )

    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert client._client.post.await_count == 2
    assert result.text == "Hello streamed world"
    assert result.input_tokens == 8400
    assert result.output_tokens == 42
    assert result.stop_reason == "end_turn"
    assert limiter.refunded == 1
    assert limiter.reconciled == 1


# =============================================================================
# BUG-080 §2.6 — the streaming path applies the tight inter-event read timeout
# =============================================================================


@pytest.mark.asyncio
async def test_streaming_request_uses_short_read_timeout_only():
    """The streaming request overrides ONLY the httpx read timeout with the tight
    inter-event stall-guard (30s), keeping connect/write/pool at the base 150s.

    MockTransport bypasses the real pool so httpx can't enforce a wall-clock read
    timeout on a canned stream — instead we spy on the per-request ``timeout``
    kwarg passed to ``httpx.AsyncClient.stream`` and assert it is the decoupled
    ``httpx.Timeout(150.0, read=30.0)``."""

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CannedStream(list(_HAPPY_CHUNKS)))

    client = AnthropicClient(
        api_key="test",
        max_retries=1,
        streaming=True,
        timeout=150.0,
        streaming_read_timeout=30.0,
    )
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    orig_stream = client._client.stream

    def spy_stream(method, url, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return orig_stream(method, url, **kwargs)

    client._client.stream = spy_stream
    try:
        result = await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert result.text == "Hello streamed world"
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 30.0  # tight inter-event stall-guard
    assert timeout.connect == 150.0  # base per-attempt timeout preserved
    assert timeout.write == 150.0
    assert timeout.pool == 150.0


@pytest.mark.asyncio
async def test_non_streaming_post_does_not_receive_short_read_timeout():
    """Decoupling guarantee: the non-streaming path (streaming=False) never gets
    the short read timeout — ``post`` is called WITHOUT a per-request ``timeout``
    override, so the client default (150s) applies and BUG-079 cannot recur."""

    captured: dict[str, object] = {}

    client = AnthropicClient(
        api_key="test",
        max_retries=1,
        streaming=False,
        timeout=150.0,
        streaming_read_timeout=30.0,
    )
    assert client._streaming is False
    ok_response = httpx.Response(
        200,
        request=httpx.Request("POST", AnthropicClient.BASE_URL),
        json={
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "stop_reason": "end_turn",
        },
    )

    async def spy_post(url, **kwargs):
        captured["timeout"] = kwargs.get("timeout", "NOT_PASSED")
        return ok_response

    client._client.post = spy_post
    try:
        await client.generate_with_usage(prompt="{}")
    finally:
        await client.close()

    assert captured["timeout"] == "NOT_PASSED"
    assert client._client.timeout.read == 150.0
