"""
Ollama LLM клиент.

Реализует LLMClient интерфейс для локальных Ollama models.
Ollama API совместим с OpenAI Chat Completions API.
"""

import hashlib
import json
import structlog
from typing import Any

import httpx

from tg_parser.processing.ports import LLMClient

logger = structlog.get_logger(__name__)


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
    ):
        """
        Args:
            model: Model name (например: llama3.2, mistral)
            base_url: Ollama server URL (default: http://localhost:11434)
            timeout: Request timeout in seconds
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Генерировать ответ через Ollama API.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            temperature: Temperature (0-1)
            max_tokens: Max tokens в ответе (Ollama: num_predict)
            response_format: {"type": "json_object"} для JSON mode
            
        Returns:
            Текст ответа
        """
        # Формируем messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Ollama использует OpenAI-compatible format
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        # JSON mode для Ollama (если поддерживается моделью)
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

        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()

            # Извлекаем content (OpenAI-compatible format)
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                logger.error(
                    "Failed to parse Ollama response: %s, response: %s",
                    e,
                    data,
                )
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
            logger.error(
                "Ollama API error: %s - %s",
                e.response.status_code,
                e.response.text,
            )
            raise
        except httpx.HTTPError as e:
            logger.error("Ollama request failed: %s", e)
            raise
        except json.JSONDecodeError as e:
            logger.error("Ollama request failed: %s", e)
            raise
        except ValueError as e:
            logger.error("Ollama request failed: %s", e)
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

