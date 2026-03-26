"""
OpenAI LLM клиент через httpx.

Реализует LLMClient для OpenAI API и OpenAI-compatible провайдеров.
Требования: TR-38 (детерминизм), TR-47 (ретраи).
Session 23: GPT-5 Responses API support (/v1/responses).
"""

import hashlib

import httpx
import structlog

from tg_parser.processing.ports import LLMClient, LLMResponse

logger = structlog.get_logger(__name__)


class OpenAIClient(LLMClient):
    """
    OpenAI API клиент с поддержкой ретраев и детерминизма.

    Реализует TR-38: temperature=0 для детерминизма.
    Использует httpx для async HTTP запросов.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        timeout: float = 60.0,
        reasoning_effort: str = "low",
        verbosity: str = "low",
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

        # Убираем trailing slash из base_url
        if self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

        # Создаём HTTP клиент
        # Используем увеличенный read timeout для длинных LLM ответов
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
            prompt, system_prompt, temperature, max_tokens, response_format,
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
        response = await self.client.post(url, json=request_body)
        response.raise_for_status()

        response_data = response.json()

        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.error(
                "failed_to_parse_openai_response",
                response=response_data,
                error=str(e),
            )
            raise ValueError(f"Invalid OpenAI response format: {e}") from e

        usage = response_data.get("usage", {})
        logger.debug(
            "openai_chat_completions_response",
            response_length=len(content),
            finish_reason=response_data["choices"][0].get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

        return LLMResponse(
            text=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

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
        response = await self.client.post(url, json=request_body)
        response.raise_for_status()

        response_data = response.json()

        try:
            if "output_text" in response_data:
                content = response_data["output_text"]
            elif "choices" in response_data and len(response_data["choices"]) > 0:
                choice = response_data["choices"][0]
                if "output_text" in choice:
                    content = choice["output_text"]
                elif "message" in choice and "content" in choice["message"]:
                    content = choice["message"]["content"]
                else:
                    raise ValueError("No output_text or message.content in choice")
            else:
                raise ValueError("No output_text or choices in response")
        except (KeyError, IndexError, ValueError) as e:
            logger.error(
                "failed_to_parse_responses_api",
                response=response_data,
                error=str(e),
            )
            raise ValueError(f"Invalid Responses API format: {e}") from e

        usage = response_data.get("usage", {})
        logger.debug(
            "openai_responses_api_response",
            response_length=len(content),
            finish_reason=response_data.get("finish_reason", "unknown"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

        return LLMResponse(
            text=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

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
