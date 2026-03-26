"""
Google Gemini LLM клиент.

Реализует LLMClient интерфейс для Gemini models.
"""

import hashlib
import logging
from typing import Any

import httpx

from tg_parser.processing.ports import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


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
            prompt, system_prompt, temperature, max_tokens, response_format, **kwargs,
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

        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()

            if "candidates" not in data or len(data["candidates"]) == 0:
                logger.error(f"Gemini API returned no candidates: {data}")
                raise ValueError("No candidates in Gemini response")

            candidate = data["candidates"][0]
            if "content" not in candidate or "parts" not in candidate["content"]:
                logger.error(f"Gemini API invalid structure: {data}")
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

        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Gemini request failed: {e}")
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

