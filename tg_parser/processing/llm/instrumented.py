"""
Instrumented LLM client wrapper.

Automatically records Prometheus metrics (request count, duration, tokens)
for every generate/generate_with_usage call, regardless of provider.
F8-A: in-memory TTL cache for identical prompts.
"""

import sys
import time

import structlog

from tg_parser.api.metrics import record_llm_request
from tg_parser.processing.llm.response_cache import get_llm_cache
from tg_parser.processing.ports import LLMClient, LLMResponse

logger = structlog.get_logger(__name__)


class InstrumentedLLMClient(LLMClient):
    """Transparent wrapper that records Prometheus metrics and caches LLM responses."""

    def __init__(self, client: LLMClient, provider: str, model: str) -> None:
        self._client = client
        self._provider = provider
        self._model = model
        self._cache = get_llm_cache()

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
        **kwargs,
    ) -> str:
        cached = self._cache.get(
            prompt, system_prompt, temperature, max_tokens, self._provider, self._model
        )
        if cached is not None:
            return cached

        t0 = time.monotonic()
        try:
            result = await self._client.generate(
                prompt,
                system_prompt,
                temperature,
                max_tokens,
                response_format,
                **kwargs,
            )
            self._cache.put(
                prompt,
                system_prompt,
                temperature,
                max_tokens,
                result,
                self._provider,
                self._model,
            )
            return result
        finally:
            record_llm_request(
                provider=self._provider,
                model=self._model,
                success=sys.exc_info()[1] is None,
                duration_seconds=time.monotonic() - t0,
            )

    async def generate_with_usage(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
        **kwargs,
    ) -> LLMResponse:
        t0 = time.monotonic()
        result: LLMResponse | None = None
        try:
            result = await self._client.generate_with_usage(
                prompt,
                system_prompt,
                temperature,
                max_tokens,
                response_format,
                **kwargs,
            )
            return result
        finally:
            duration = time.monotonic() - t0
            record_llm_request(
                provider=self._provider,
                model=self._model,
                success=sys.exc_info()[1] is None,
                duration_seconds=duration,
                prompt_tokens=result.input_tokens if result else 0,
                completion_tokens=result.output_tokens if result else 0,
            )

    async def close(self):
        if hasattr(self._client, "close"):
            await self._client.close()

    def compute_prompt_id(self, system_prompt: str | None, user_prompt_template: str) -> str:
        if hasattr(self._client, "compute_prompt_id"):
            return self._client.compute_prompt_id(system_prompt, user_prompt_template)
        return "unknown"

    def suggest_processing_concurrency(self, requested: int) -> int:
        if hasattr(self._client, "suggest_processing_concurrency"):
            return self._client.suggest_processing_concurrency(requested)
        return requested
