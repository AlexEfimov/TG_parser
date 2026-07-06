"""
Anthropic Claude LLM клиент.

Реализует LLMClient интерфейс для Claude models.
F8-A: 429/5xx retry с exponential backoff и опциональную интеграцию с LLMRateLimiter.
"""

import asyncio
import hashlib
import json
import random
from typing import Any

import httpx
import structlog

from tg_parser.processing.llm.errors import AnthropicBillingError, LLMCallTimeoutError
from tg_parser.processing.ports import LLMClient, LLMResponse

logger = structlog.get_logger(__name__)

# BUG-020: 520 (Cloudflare "Web Server Returned an Unknown Error") is a
# transient Anthropic edge failure and uses the same 5xx exp-backoff+jitter.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 520, 529}


def _parse_retry_after_seconds(response: httpx.Response) -> float:
    """Extract retry-after from Anthropic 429 response (default 60s)."""
    val = response.headers.get("retry-after")
    if val:
        try:
            return max(1.0, float(val))
        except (ValueError, TypeError):
            pass
    return 60.0


def _compute_retry_delay(response: httpx.Response, attempt: int) -> float:
    """Compute retry delay: retry-after header for 429, exponential backoff for 5xx."""
    if response.status_code == 429:
        return _parse_retry_after_seconds(response)
    base = min(2**attempt, 60)
    return base + random.uniform(0, base * 0.3)


class AnthropicClient(LLMClient):
    """
    Anthropic Claude клиент через Messages API.

    Поддерживаемые модели:
    - claude-sonnet-4-20250514
    - claude-3-5-haiku-20241022
    - claude-3-opus-20240229
    """

    BASE_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        timeout: float = 150.0,  # BUG-079: aligned with anthropic_http_timeout_s default (was 120.0)
        rate_limiter: Any | None = None,
        prompt_caching_enabled: bool = True,
        rate_limit_input_estimate: int = 2000,
        rate_limit_output_estimate: int = 2048,
        max_retries: int = 5,
        call_timeout: float | None = None,
        streaming: bool = False,
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=timeout)
        self.rate_limiter = rate_limiter
        self._prompt_caching = prompt_caching_enabled
        self._input_estimate = rate_limit_input_estimate
        self._output_estimate = rate_limit_output_estimate
        self._max_retries = max_retries
        # BUG-068 (A1): aggregate wall-clock budget for the WHOLE call
        # (rate_limiter.acquire + retry loop), distinct from the per-HTTP
        # attempt ``timeout`` above. ``None`` disables the aggregate guard.
        self._call_timeout = call_timeout
        # BUG-080: when True, consume the Messages API as a text/event-stream
        # (stream=true) so the per-attempt httpx read timeout guards inter-chunk
        # GAPS (a real dead-socket stall) instead of total generation latency.
        # The streamed path returns an IDENTICAL LLMResponse contract.
        self._streaming = streaming

    def suggest_processing_concurrency(self, requested: int) -> int:
        if self.rate_limiter and hasattr(self.rate_limiter, "suggested_parallel_cap"):
            return self.rate_limiter.suggested_parallel_cap(requested)
        return requested

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> str:
        result = await self.generate_with_usage(
            prompt,
            system_prompt,
            temperature,
            max_tokens,
            response_format,
            **kwargs,
        )
        return result.text

    async def generate_with_usage(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # BUG-068 (A1): bound the ENTIRE call — the unbounded
        # ``rate_limiter.acquire`` gate plus the full 429/5xx retry loop — with
        # one aggregate wall-clock budget. The per-attempt httpx ``timeout``
        # only bounds a single HTTP request and cannot stop the call from
        # hanging indefinitely while waiting for token-bucket capacity or
        # cycling 60s 429 retry-after sleeps. On timeout we raise
        # ``LLMCallTimeoutError`` so the failure propagates to the per-doc
        # handler (not swallowed) and the serial scheduler can move on.
        if self._call_timeout is None:
            return await self._generate_with_usage_inner(
                prompt,
                system_prompt,
                temperature,
                max_tokens,
                response_format,
                **kwargs,
            )
        try:
            return await asyncio.wait_for(
                self._generate_with_usage_inner(
                    prompt,
                    system_prompt,
                    temperature,
                    max_tokens,
                    response_format,
                    **kwargs,
                ),
                timeout=self._call_timeout,
            )
        except TimeoutError as exc:
            logger.error(
                "anthropic_call_timeout",
                timeout_s=self._call_timeout,
                model=self.model,
            )
            raise LLMCallTimeoutError(
                f"Anthropic generate_with_usage exceeded "
                f"{self._call_timeout}s aggregate wall-clock timeout"
            ) from exc

    async def _generate_with_usage_inner(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

        if self._prompt_caching:
            headers["anthropic-beta"] = "prompt-caching-2024-07-31"

        messages = [{"role": "user", "content": prompt}]

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system_prompt:
            if self._prompt_caching:
                payload["system"] = [
                    {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
                ]
            else:
                payload["system"] = system_prompt

        if response_format and response_format.get("type") == "json_object":
            if "JSON" not in prompt and "json" not in prompt:
                messages[0]["content"] = prompt + "\n\nRespond with valid JSON only."

        # BUG-080: request a text/event-stream so the per-attempt httpx read
        # timeout guards inter-chunk gaps rather than total generation latency.
        if self._streaming:
            payload["stream"] = True

        in_est = kwargs.pop("input_estimate", self._input_estimate)
        out_est = kwargs.pop("output_estimate", self._output_estimate)

        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            if self.rate_limiter:
                await self.rate_limiter.acquire(in_est, out_est)

            try:
                # BUG-080: the streamed path consumes an SSE body, but the status
                # handling (retryable codes, 429, 400/billing, raise_for_status)
                # and the success accounting (reconcile_usage, LLMResponse
                # contract) are IDENTICAL to the non-streaming path — only how the
                # response is fetched and how the body is decoded differ.
                if self._streaming:
                    async with self._client.stream(
                        "POST",
                        self.BASE_URL,
                        headers=headers,
                        json=payload,
                    ) as response:
                        if response.status_code != 200:
                            # The body is streamed lazily — pull it fully before
                            # inspecting an error body / raising.
                            await response.aread()
                            delay = await self._handle_error_status(
                                response, attempt, in_est, out_est
                            )
                            if delay is not None:
                                await asyncio.sleep(delay)
                                continue
                        (
                            content,
                            input_tokens,
                            output_tokens,
                            stop_reason,
                        ) = await self._parse_sse_stream(response)
                        response_headers = response.headers
                else:
                    response = await self._client.post(
                        self.BASE_URL,
                        headers=headers,
                        json=payload,
                    )
                    delay = await self._handle_error_status(
                        response, attempt, in_est, out_est
                    )
                    if delay is not None:
                        await asyncio.sleep(delay)
                        continue

                    data = response.json()
                    content = self._extract_text_content(data)
                    usage = data.get("usage", {})
                    input_tokens = usage.get("input_tokens")
                    output_tokens = usage.get("output_tokens")
                    stop_reason = data.get("stop_reason")
                    response_headers = response.headers

                if self.rate_limiter:
                    await self.rate_limiter.sync_remaining_from_headers(response_headers)
                    await self.rate_limiter.reconcile_usage(
                        in_est,
                        out_est,
                        input_tokens,
                        output_tokens,
                    )

                logger.debug(
                    "Anthropic response received",
                    extra={
                        "model": self.model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                )

                return LLMResponse(
                    text=content,
                    input_tokens=input_tokens or 0,
                    output_tokens=output_tokens or 0,
                    # BUG-071 (Fix 1): surface ``stop_reason`` so topicization can
                    # detect a ``max_tokens`` truncation (charged HTTP 200 whose
                    # JSON body is cut off mid-string) and shrink the request
                    # instead of re-issuing the identical oversized call.
                    stop_reason=stop_reason,
                )

            except httpx.HTTPStatusError as e:
                # _handle_error_status owns retryable-status refund + retry: for a
                # retryable status with attempt < max_retries it RETURNS a delay
                # (no raise), and only raises via raise_for_status on the terminal
                # retryable attempt (attempt == max_retries) or a non-retryable
                # status. So any HTTPStatusError reaching here is terminal — just
                # log + re-raise (the retryable-status refund/retry branch that
                # used to live here was unreachable dead code).
                logger.error(
                    "Anthropic API error: %s - %s", e.response.status_code, e.response.text
                )
                raise

            except httpx.HTTPError as e:
                # BUG-080 (Fix 1): refund the pre-flight rate-limiter reservation
                # on EVERY attempt (retry AND terminal), mirroring
                # _handle_error_status which refunds unconditionally before its
                # attempt < max_retries check. Without this a terminal stall /
                # mid-stream error / network error leaks the reservation (acquired
                # once, never reconciled/refunded). Refund-once still holds: this
                # arm is mutually exclusive with _handle_error_status's refund
                # (which raises via raise_for_status → HTTPStatusError, a SEPARATE
                # arm) and with reconcile_usage (only on the success return) within
                # a single attempt.
                if self.rate_limiter:
                    await self.rate_limiter.refund_acquire(in_est, out_est)
                if attempt < self._max_retries:
                    delay = min(2**attempt + random.uniform(0, 1), 60)
                    logger.warning(
                        "anthropic_network_error",
                        attempt=attempt,
                        error=str(e),
                        retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("Anthropic request failed: %s", e)
                raise

            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                logger.error("Anthropic response parse error: %s", e)
                raise

        raise RuntimeError(f"Exhausted {self._max_retries} retries for Anthropic API") from last_exc

    async def _handle_error_status(
        self,
        response: httpx.Response,
        attempt: int,
        in_est: int,
        out_est: int,
    ) -> float | None:
        """Shared HTTP status handling for the streaming + non-streaming paths.

        Returns a retry delay (seconds) when the caller should ``sleep`` and
        retry a retryable status; returns ``None`` when the response is OK to
        parse. Raises :class:`AnthropicBillingError` on an exhausted credit
        balance and re-raises via ``raise_for_status`` on terminal HTTP errors.

        NOTE: on a retryable status the pre-flight rate-limiter reservation is
        refunded here (mirroring the historical inline behavior), so the caller
        must only ``sleep`` — it must NOT refund again.
        """
        if response.status_code in _RETRYABLE_STATUS_CODES:
            if response.status_code >= 500:
                from tg_parser.api.metrics import record_anthropic_5xx

                record_anthropic_5xx(status=response.status_code)
            if self.rate_limiter:
                await self.rate_limiter.refund_acquire(in_est, out_est)
            if attempt < self._max_retries:
                delay = _compute_retry_delay(response, attempt)
                logger.warning(
                    "anthropic_retryable_%d",
                    response.status_code,
                    attempt=attempt,
                    max_retries=self._max_retries,
                    retry_after=delay,
                )
                return delay
            # Terminal: retries exhausted on a retryable 5xx — count the
            # terminal failure once more so it is observable on its own.
            if response.status_code >= 500:
                from tg_parser.api.metrics import record_anthropic_5xx

                record_anthropic_5xx(status=response.status_code)
            response.raise_for_status()

        if response.status_code == 400:
            try:
                body = response.json()
            except (json.JSONDecodeError, TypeError):
                body = {}
            err = body.get("error", {}) if isinstance(body, dict) else {}
            err_type = str(err.get("type", "")).lower()
            err_message = str(err.get("message", ""))
            if err_type == "invalid_request_error" and "credit balance" in err_message.lower():
                raise AnthropicBillingError(
                    err_message or "Anthropic credit balance exhausted",
                    request_id=response.headers.get("request-id"),
                )

        response.raise_for_status()
        return None

    @staticmethod
    async def _parse_sse_stream(
        response: httpx.Response,
    ) -> tuple[str, int | None, int | None, str | None]:
        """Parse an Anthropic Messages API ``text/event-stream`` (BUG-080).

        Returns ``(text, input_tokens, output_tokens, stop_reason)`` matching
        the non-streaming decode:

        - ``message_start`` → ``message.usage.input_tokens`` and the initial
          ``output_tokens``.
        - ``content_block_delta`` (``delta.type == "text_delta"``) → append
          ``delta.text`` to the text buffer.
        - ``message_delta`` → final ``delta.stop_reason`` and the CUMULATIVE
          ``usage.output_tokens`` (used verbatim — deltas are NOT summed).
        - ``message_stop`` → end of stream.

        Empty content yields ``""`` (never raises), preserving
        ``_extract_text_content`` semantics.
        """
        text_parts: list[str] = []
        input_tokens: int | None = None
        output_tokens: int | None = None
        stop_reason: str | None = None
        # BUG-080 (Fix 2): a truncated/dropped stream (dead socket after some
        # deltas but before the terminal frames) otherwise looks like a clean
        # short completion and is charged + accepted with partial text. Key on
        # ``message_delta`` (NOT ``message_stop``): the ``message_delta`` frame
        # carries the final stop_reason + cumulative usage, so a stream that
        # delivers it but drops before ``message_stop`` is still complete/valid.
        saw_message_delta = False

        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:") :].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "message_start":
                message = event.get("message", {}) or {}
                usage = message.get("usage", {}) or {}
                if usage.get("input_tokens") is not None:
                    input_tokens = usage.get("input_tokens")
                if usage.get("output_tokens") is not None:
                    output_tokens = usage.get("output_tokens")
                if message.get("stop_reason") is not None:
                    stop_reason = message.get("stop_reason")
            elif etype == "content_block_delta":
                delta = event.get("delta", {}) or {}
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", "") or "")
            elif etype == "message_delta":
                saw_message_delta = True
                delta = event.get("delta", {}) or {}
                if delta.get("stop_reason") is not None:
                    stop_reason = delta.get("stop_reason")
                usage = event.get("usage", {}) or {}
                # CUMULATIVE final output token count — take it verbatim.
                if usage.get("output_tokens") is not None:
                    output_tokens = usage.get("output_tokens")
            elif etype == "error":
                err = event.get("error", {}) or {}
                err_type = str(err.get("type") or "").strip()
                err_message = str(err.get("message") or "Anthropic stream error event")
                # BUG-080 (Fix 1): surface error.type in the message for
                # observability. Keep this a retryable httpx.HTTPError — do NOT
                # synthesize an HTTPStatusError or a new exception type, so the
                # retry loop treats a mid-stream error like a transient network
                # error (refunded + retried).
                msg = f"{err_type}: {err_message}" if err_type else err_message
                raise httpx.HTTPError(msg)
            elif etype == "message_stop":
                break

        if not saw_message_delta:
            # Truncated/incomplete stream: raise a RETRYABLE httpx.HTTPError
            # subclass so the retry loop refunds (Fix 1) and re-issues the call
            # rather than accepting partial text as a charged success.
            raise httpx.RemoteProtocolError(
                "Anthropic stream ended without a terminal message_delta "
                "(truncated/incomplete stream)"
            )

        return "".join(text_parts), input_tokens, output_tokens, stop_reason

    @staticmethod
    def _extract_text_content(data: dict[str, Any]) -> str:
        """Return the first text block from an Anthropic Messages API response.

        HTTP 200 with an empty ``content`` array (refusal / stop without text)
        must not raise ``IndexError`` — callers treat empty text as an LLM
        failure at their stage boundary (same pattern as resummarize parse path).
        """
        blocks = data.get("content") or []
        if not blocks:
            logger.warning(
                "anthropic_empty_content",
                stop_reason=data.get("stop_reason"),
            )
            return ""
        first = blocks[0]
        if not isinstance(first, dict):
            logger.warning("anthropic_empty_content", reason="non_dict_block")
            return ""
        if first.get("type") != "text":
            logger.warning(
                "anthropic_empty_content",
                reason="non_text_block",
                block_type=first.get("type"),
            )
            return ""
        return str(first.get("text") or "")

    async def close(self):
        await self._client.aclose()

    def compute_prompt_id(
        self,
        system_prompt: str | None,
        user_prompt_template: str,
    ) -> str:
        combined = f"{system_prompt or ''}\n---\n{user_prompt_template}"
        hash_obj = hashlib.sha256(combined.encode("utf-8"))
        return f"sha256:{hash_obj.hexdigest()[:16]}"
