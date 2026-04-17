"""
Google Gemini LLM клиент.

Реализует LLMClient интерфейс для Gemini models.
F8-A: 429/5xx retry с exponential backoff.
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


class GeminiClient(LLMClient):
    """
    Google Gemini клиент через REST API.

    Поддерживаемые модели:
    - gemini-2.0-flash-exp
    - gemini-1.5-flash
    - gemini-1.5-pro
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash-exp",
        timeout: float = 120.0,
        max_retries: int = 5,
    ):
        """
        Args:
            api_key: Google AI API key
            model: Model name (default: gemini-2.0-flash-exp)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=timeout)
        self._max_retries = max_retries

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
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
        max_tokens: int = 4096,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        if response_format and response_format.get("type") == "json_object":
            if "JSON" not in full_prompt and "json" not in full_prompt:
                full_prompt = full_prompt + "\n\nRespond with valid JSON only."

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if response_format and response_format.get("type") == "json_object":
            payload["generationConfig"]["response_mime_type"] = "application/json"

        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"

        logger.debug(
            "Gemini API request",
            extra={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )

        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.post(url, json=payload)

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    retry_after = self._compute_delay(response, attempt)
                    if attempt < self._max_retries:
                        logger.warning(
                            "gemini_retryable_%d",
                            response.status_code,
                            attempt=attempt,
                            max_retries=self._max_retries,
                            retry_after=retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    response.raise_for_status()

                response.raise_for_status()
                return self._parse_response(response.json())

            except httpx.HTTPStatusError as e:
                if (
                    e.response.status_code in _RETRYABLE_STATUS_CODES
                    and attempt < self._max_retries
                ):
                    retry_after = self._compute_delay(e.response, attempt)
                    logger.warning(
                        "gemini_retryable_%d",
                        e.response.status_code,
                        attempt=attempt,
                        max_retries=self._max_retries,
                        retry_after=retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    last_exc = e
                    continue
                logger.error("Gemini API error: %s - %s", e.response.status_code, e.response.text)
                raise

            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    delay = min(2**attempt + random.uniform(0, 1), 60)
                    logger.warning(
                        "gemini_network_error",
                        attempt=attempt,
                        error=str(e),
                        retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("Gemini request failed: %s", e)
                raise

            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
                logger.error("Gemini response parse error: %s", e)
                raise

        raise RuntimeError(f"Exhausted {self._max_retries} retries for Gemini API") from last_exc

    @staticmethod
    def _compute_delay(response: httpx.Response, attempt: int) -> float:
        val = response.headers.get("retry-after")
        if val:
            try:
                return max(1.0, float(val))
            except (ValueError, TypeError):
                pass
        base = min(2**attempt, 60)
        return base + random.uniform(0, base * 0.3)

    def _parse_response(self, data: dict) -> LLMResponse:
        if "candidates" not in data or len(data["candidates"]) == 0:
            raise ValueError("No candidates in Gemini response")

        candidate = data["candidates"][0]
        if "content" not in candidate or "parts" not in candidate["content"]:
            raise ValueError("Invalid Gemini response structure")

        content = candidate["content"]["parts"][0]["text"]
        usage_meta = data.get("usageMetadata", {})

        logger.debug(
            "Gemini response received",
            extra={
                "model": self.model,
                "response_length": len(content),
                "input_tokens": usage_meta.get("promptTokenCount"),
                "output_tokens": usage_meta.get("candidatesTokenCount"),
            },
        )

        return LLMResponse(
            text=content,
            input_tokens=usage_meta.get("promptTokenCount", 0),
            output_tokens=usage_meta.get("candidatesTokenCount", 0),
        )

    async def close(self):
        """Закрыть HTTP клиент."""
        await self._client.aclose()

    def compute_prompt_id(
        self,
        system_prompt: str | None,
        user_prompt_template: str,
    ) -> str:
        """
        Вычислить prompt_id для детерминизма.

        Args:
            system_prompt: System prompt
            user_prompt_template: User prompt template

        Returns:
            prompt_id в формате "sha256:<hash>"
        """
        combined = f"{system_prompt or ''}\n---\n{user_prompt_template}"
        hash_obj = hashlib.sha256(combined.encode("utf-8"))
        return f"sha256:{hash_obj.hexdigest()[:16]}"
