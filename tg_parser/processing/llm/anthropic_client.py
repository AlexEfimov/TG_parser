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

from tg_parser.processing.ports import LLMClient, LLMResponse

logger = structlog.get_logger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


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
    base = min(2 ** attempt, 60)
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
            prompt, system_prompt, temperature, max_tokens, response_format, **kwargs,
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
                    if self.rate_limiter:
                        await self.rate_limiter.refund_acquire(in_est, out_est)
                    if attempt < self._max_retries:
                        delay = _compute_retry_delay(response, attempt)
                        logger.warning(
                            "anthropic_retryable_%d", response.status_code,
                            attempt=attempt, max_retries=self._max_retries,
                            retry_after=delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()

                response.raise_for_status()

                data = response.json()
                content = data["content"][0]["text"]
                usage = data.get("usage", {})

                if self.rate_limiter:
                    await self.rate_limiter.sync_remaining_from_headers(response.headers)
                    await self.rate_limiter.reconcile_usage(
                        in_est, out_est,
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
                        "anthropic_retryable_%d", e.response.status_code,
                        attempt=attempt, max_retries=self._max_retries,
                        retry_after=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("Anthropic API error: %s - %s", e.response.status_code, e.response.text)
                raise

            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    delay = min(2 ** attempt + random.uniform(0, 1), 60)
                    logger.warning(
                        "anthropic_network_error",
                        attempt=attempt, error=str(e), retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("Anthropic request failed: %s", e)
                raise

            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                logger.error("Anthropic response parse error: %s", e)
                raise

        raise RuntimeError(
            f"Exhausted {self._max_retries} retries for Anthropic API"
        ) from last_exc

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
