"""
OpenAI LLM клиент через httpx.

Реализует LLMClient для OpenAI API и OpenAI-compatible провайдеров.
Требования: TR-38 (детерминизм), TR-47 (ретраи).
Session 23: GPT-5 Responses API support (/v1/responses).
F8-A: 429 retry с exponential backoff (паритет с Anthropic).
"""

import asyncio
import hashlib
import random

import httpx
import structlog

from tg_parser.processing.ports import LLMClient, LLMResponse

logger = structlog.get_logger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


class OpenAIClient(LLMClient):
    """
    OpenAI API клиент с поддержкой ретраев и детерминизма.

    Реализует TR-38: temperature=0 для детерминизма.
    F8-A: 429/5xx retry с exponential backoff.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        timeout: float = 60.0,
        reasoning_effort: str = "low",
        verbosity: str = "low",
        max_retries: int = 5,
    ):
        """
        Args:
            api_key: OpenAI API ключ
            model: Модель для использования (default: gpt-4o-mini)
            base_url: Base URL для OpenAI-compatible API (опционально)
            timeout: Таймаут запросов в секундах
            reasoning_effort: Reasoning effort для GPT-5 (minimal/low/medium/high)
            verbosity: Verbosity для GPT-5 (low/medium/high)
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self._max_retries = max_retries

        if self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=max(self.timeout, 120.0),  # Минимум 120 секунд на чтение ответа
                write=30.0,
                pool=10.0,
            ),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def _is_gpt5_model(self) -> bool:
        """Check if the model is GPT-5 series (requires Responses API)."""
        return self.model.startswith("gpt-5")

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        result = await self.generate_with_usage(
            prompt,
            system_prompt,
            temperature,
            max_tokens,
            response_format,
        )
        return result.text

    async def generate_with_usage(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> LLMResponse:
        if self._is_gpt5_model():
            return await self._generate_responses_api(
                prompt, system_prompt, temperature, max_tokens, response_format
            )
        else:
            return await self._generate_chat_completions(
                prompt, system_prompt, temperature, max_tokens, response_format
            )

    async def _generate_chat_completions(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
    ) -> LLMResponse:
        """Generate response using Chat Completions API (/chat/completions)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            request_body["response_format"] = response_format

        logger.debug(
            "openai_chat_completions_request",
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages_count=len(messages),
            prompt_length=len(prompt),
        )

        url = f"{self.base_url}/chat/completions"
        return await self._request_with_retry(url, request_body, "chat_completions")

    async def _generate_responses_api(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
    ) -> LLMResponse:
        """Generate response using Responses API (/responses) for GPT-5.* models."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning": {
                "effort": self.reasoning_effort,
            },
            "verbosity": self.verbosity,
        }

        if response_format:
            logger.debug(
                "response_format_with_responses_api",
                note="response_format not directly supported in Responses API, ensure prompt requests JSON",
            )

        logger.debug(
            "openai_responses_api_request",
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=self.reasoning_effort,
            verbosity=self.verbosity,
            messages_count=len(messages),
            prompt_length=len(prompt),
        )

        url = f"{self.base_url}/responses"
        return await self._request_with_retry(url, request_body, "responses_api")

    # ------------------------------------------------------------------
    # Retry logic (F8-A)
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        url: str,
        request_body: dict,
        api_label: str,
    ) -> LLMResponse:
        """Execute an HTTP request with exponential backoff on retryable errors."""
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self.client.post(url, json=request_body)

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    retry_after = self._parse_retry_after(response)
                    if attempt < self._max_retries:
                        logger.warning(
                            "openai_%s_retryable_%d",
                            api_label,
                            response.status_code,
                            attempt=attempt,
                            max_retries=self._max_retries,
                            retry_after=retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    response.raise_for_status()

                response.raise_for_status()
                return self._parse_response(response.json(), api_label)

            except httpx.HTTPStatusError as e:
                if (
                    e.response.status_code in _RETRYABLE_STATUS_CODES
                    and attempt < self._max_retries
                ):
                    retry_after = self._parse_retry_after(e.response)
                    logger.warning(
                        "openai_%s_retryable_%d",
                        api_label,
                        e.response.status_code,
                        attempt=attempt,
                        max_retries=self._max_retries,
                        retry_after=retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    last_exc = e
                    continue
                logger.error("OpenAI API error: %s - %s", e.response.status_code, e.response.text)
                raise

            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    delay = min(2**attempt + random.uniform(0, 1), 60)
                    logger.warning(
                        "openai_%s_network_error",
                        api_label,
                        attempt=attempt,
                        error=str(e),
                        retry_in=delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = e
                    continue
                logger.error("OpenAI request failed: %s", e)
                raise

        raise RuntimeError(
            f"Exhausted {self._max_retries} retries for OpenAI {api_label}"
        ) from last_exc

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float:
        """Extract Retry-After or compute exponential backoff."""
        val = response.headers.get("retry-after")
        if val:
            try:
                return max(1.0, float(val))
            except (ValueError, TypeError):
                pass
        if response.status_code == 429:
            return 10.0 + random.uniform(0, 5)
        return 2.0 + random.uniform(0, 1)

    def _parse_response(self, response_data: dict, api_label: str) -> LLMResponse:
        """Parse successful response from either Chat Completions or Responses API."""
        try:
            if api_label == "responses_api":
                content = self._extract_responses_api_content(response_data)
            else:
                content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            label = "Responses API" if api_label == "responses_api" else "OpenAI"
            logger.error(
                "failed_to_parse_openai_%s", api_label, response=response_data, error=str(e)
            )
            raise ValueError(f"Invalid {label} format: {e}") from e

        usage = response_data.get("usage", {})
        logger.debug(
            "openai_%s_response",
            api_label,
            response_length=len(content),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
        return LLMResponse(
            text=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    @staticmethod
    def _extract_responses_api_content(data: dict) -> str:
        if "output_text" in data:
            return data["output_text"]
        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            if "output_text" in choice:
                return choice["output_text"]
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"]
        raise ValueError("No output_text or choices in response")

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

    def compute_prompt_id(
        self,
        system_prompt: str | None,
        user_prompt_template: str,
    ) -> str:
        """
        Вычислить prompt_id для детерминизма (TR-40).

        Args:
            system_prompt: Системный промпт
            user_prompt_template: Шаблон user промпта (без подстановки данных)

        Returns:
            prompt_id в формате "sha256:<hash>"
        """
        # Конкатенируем промпты
        combined = f"{system_prompt or ''}\n---\n{user_prompt_template}"

        # Вычисляем SHA256
        hash_obj = hashlib.sha256(combined.encode("utf-8"))
        hash_hex = hash_obj.hexdigest()

        return f"sha256:{hash_hex[:16]}"  # Используем первые 16 символов для краткости


class OpenAIError(Exception):
    """Базовая ошибка OpenAI клиента."""

    pass


class OpenAIRateLimitError(OpenAIError):
    """Ошибка rate limit."""

    pass


class OpenAIAPIError(OpenAIError):
    """Общая ошибка API."""

    pass
