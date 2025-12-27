"""
Anthropic Claude LLM клиент.

Реализует LLMClient интерфейс для Claude models.
"""

import hashlib
import logging
from typing import Any

import httpx

from tg_parser.processing.ports import LLMClient

logger = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    """
    Anthropic Claude клиент через Messages API.
    
    Поддерживаемые модели:
    - claude-3-5-sonnet-20241022
    - claude-3-5-haiku-20241022
    - claude-3-opus-20240229
    """

    BASE_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ):
        """
        Args:
            api_key: Anthropic API key
            model: Model name (default: claude-3-5-sonnet-20241022)
            max_tokens: Maximum tokens in response
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Генерировать ответ через Anthropic Messages API.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            temperature: Temperature (0-1)
            max_tokens: Max tokens в ответе
            response_format: {"type": "json_object"} для JSON mode
            
        Returns:
            Текст ответа
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

        messages = [{"role": "user", "content": prompt}]

        # Claude использует system prompt отдельно
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system_prompt:
            payload["system"] = system_prompt

        # JSON mode hint в prompt (Claude не имеет response_format)
        if response_format and response_format.get("type") == "json_object":
            # Добавляем hint о JSON в конец prompt
            if "JSON" not in prompt and "json" not in prompt:
                messages[0]["content"] = prompt + "\n\nRespond with valid JSON only."

        logger.debug(
            "Anthropic API request",
            extra={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens or self.max_tokens,
            },
        )

        try:
            response = await self._client.post(
                self.BASE_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            content = data["content"][0]["text"]

            logger.debug(
                "Anthropic response received",
                extra={
                    "model": self.model,
                    "input_tokens": data.get("usage", {}).get("input_tokens"),
                    "output_tokens": data.get("usage", {}).get("output_tokens"),
                },
            )

            return content

        except httpx.HTTPStatusError as e:
            logger.error(f"Anthropic API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Anthropic request failed: {e}")
            raise

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

