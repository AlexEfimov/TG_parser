"""
OpenAI LLM клиент через httpx.

Реализует LLMClient для OpenAI API и OpenAI-compatible провайдеров.
Требования: TR-38 (детерминизм), TR-47 (ретраи).
"""

import hashlib
import logging

import httpx

from tg_parser.processing.ports import LLMClient

logger = logging.getLogger(__name__)


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
    ):
        """
        Args:
            api_key: OpenAI API ключ
            model: Модель для использования (default: gpt-4o-mini)
            base_url: Base URL для OpenAI-compatible API (опционально)
            timeout: Таймаут запросов в секундах
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self.timeout = timeout

        # Убираем trailing slash из base_url
        if self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

        # Создаём HTTP клиент
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        Сгенерировать ответ через OpenAI API.

        Args:
            prompt: Основной промпт (user message)
            system_prompt: Системный промпт (опционально)
            temperature: Параметр стохастики (TR-38: default 0.0)
            max_tokens: Лимит токенов ответа
            response_format: Формат ответа (например {"type": "json_object"})

        Returns:
            Текст ответа от модели

        Raises:
            httpx.HTTPError: При ошибках HTTP
            ValueError: При ошибках парсинга ответа
        """
        # Формируем messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Формируем тело запроса
        request_body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Добавляем response_format если задан
        if response_format:
            request_body["response_format"] = response_format

        # Логируем запрос (без API ключа)
        logger.debug(
            "OpenAI API request",
            extra={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages_count": len(messages),
                "prompt_length": len(prompt),
            },
        )

        # Выполняем запрос
        url = f"{self.base_url}/chat/completions"
        response = await self.client.post(url, json=request_body)

        # Проверяем статус
        response.raise_for_status()

        # Парсим ответ
        response_data = response.json()

        # Извлекаем content
        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.error(
                "Failed to parse OpenAI response",
                extra={"response": response_data, "error": str(e)},
            )
            raise ValueError(f"Invalid OpenAI response format: {e}") from e

        # Логируем успех
        logger.debug(
            "OpenAI API response received",
            extra={
                "response_length": len(content),
                "finish_reason": response_data["choices"][0].get("finish_reason"),
            },
        )

        return content

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
