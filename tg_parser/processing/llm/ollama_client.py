"""
Ollama LLM клиент.

Реализует LLMClient интерфейс для локальных Ollama models.
Ollama API совместим с OpenAI Chat Completions API.
F8-A: 429/5xx retry с exponential backoff.
"""

import asyncio
import hashlib
import json
import random
from typing import Any

import httpx
import structlog

from tg_parser.processing.ports import LLMClient

logger = structlog.get_logger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


class OllamaClient(LLMClient):
    """
    Ollama локальный клиент через OpenAI-compatible API.

    Поддерживаемые модели (примеры):
    - llama3.2
    - mistral
    - qwen2.5
    - phi3

    Требует запущенный Ollama server (default: http://localhost:11434)
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
        max_retries: int = 5,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
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
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"

        url = f"{self.base_url}/v1/chat/completions"

        logger.debug(
            "Ollama API request",
            extra={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "base_url": self.base_url,
            },
        )

        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.post(url, json=payload)

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt < self._max_retries:
                        delay = self._compute_delay(response, attempt)
                        logger.warning(
                            "ollama_retryable_%d", response.status_code,
                            attempt=attempt, max_retries=self._max_retries,
                            retry_after=delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()

                response.raise_for_status()

                data = response.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as e:
                    raise ValueError(f"Invalid Ollama response format: {e}") from e

                logger.debug(
                    "Ollama response received",
                    extra={
                        "model": self.model,
                        "response_length": len(content),
                    },
                )
                return content

            except httpx.HTTPStatusError as e:
                if (
                    e.response.status_code in _RETRYABLE_STATUS_CODES
                    and attempt < self._max_retries
                ):
                    delay = self._compute_delay(e.response, attempt)
                    logger.warning(
                        "ollama_retryable_%d", e.response.status_code,
                        attempt=attempt, max_retries=self._max_retries,
                        retry_after=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("Ollama API error: %s - %s", e.response.status_code, e.response.text)
                raise

            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    delay = min(2 ** attempt + random.uniform(0, 1), 60)
                    logger.warning(
                        "ollama_network_error",
                        attempt=attempt, error=str(e), retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("Ollama request failed: %s", e)
                raise

            except (json.JSONDecodeError, ValueError) as e:
                logger.error("Ollama response parse error: %s", e)
                raise

        raise RuntimeError(
            f"Exhausted {self._max_retries} retries for Ollama API"
        ) from last_exc

    @staticmethod
    def _compute_delay(response: httpx.Response, attempt: int) -> float:
        """Compute retry delay from retry-after header or exponential backoff."""
        val = response.headers.get("retry-after")
        if val:
            try:
                return max(1.0, float(val))
            except (ValueError, TypeError):
                pass
        base = min(2 ** attempt, 60)
        return base + random.uniform(0, base * 0.3)

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

