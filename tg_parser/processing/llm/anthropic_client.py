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
        timeout: float = 120.0,
        rate_limiter: Any | None = None,
        prompt_caching_enabled: bool = True,
        rate_limit_input_estimate: int = 2000,
        rate_limit_output_estimate: int = 2048,
        max_retries: int = 5,
        call_timeout: float | None = None,
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

        in_est = kwargs.pop("input_estimate", self._input_estimate)
        out_est = kwargs.pop("output_estimate", self._output_estimate)

        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            if self.rate_limiter:
                await self.rate_limiter.acquire(in_est, out_est)

            try:
                response = await self._client.post(
                    self.BASE_URL,
                    headers=headers,
                    json=payload,
                )

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
                        await asyncio.sleep(delay)
                        continue
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
                    if (
                        err_type == "invalid_request_error"
                        and "credit balance" in err_message.lower()
                    ):
                        raise AnthropicBillingError(
                            err_message or "Anthropic credit balance exhausted",
                            request_id=response.headers.get("request-id"),
                        )

                response.raise_for_status()

                data = response.json()
                content = self._extract_text_content(data)
                usage = data.get("usage", {})

                if self.rate_limiter:
                    await self.rate_limiter.sync_remaining_from_headers(response.headers)
                    await self.rate_limiter.reconcile_usage(
                        in_est,
                        out_est,
                        usage.get("input_tokens"),
                        usage.get("output_tokens"),
                    )

                logger.debug(
                    "Anthropic response received",
                    extra={
                        "model": self.model,
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                    },
                )

                return LLMResponse(
                    text=content,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                )

            except httpx.HTTPStatusError as e:
                if (
                    e.response.status_code in _RETRYABLE_STATUS_CODES
                    and attempt < self._max_retries
                ):
                    if self.rate_limiter:
                        await self.rate_limiter.refund_acquire(in_est, out_est)
                    delay = _compute_retry_delay(e.response, attempt)
                    logger.warning(
                        "anthropic_retryable_%d",
                        e.response.status_code,
                        attempt=attempt,
                        max_retries=self._max_retries,
                        retry_after=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error(
                    "Anthropic API error: %s - %s", e.response.status_code, e.response.text
                )
                raise

            except httpx.HTTPError as e:
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
