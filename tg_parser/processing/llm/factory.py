"""
LLM Client Factory.

Создаёт LLM клиент по провайдеру.
"""

import structlog
from typing import Any

from tg_parser.processing.ports import LLMClient

logger = structlog.get_logger(__name__)

_rate_limiter_cache: dict[str, "LLMRateLimiter"] = {}


def _get_or_create_rate_limiter(api_key: str, settings: Any = None) -> "LLMRateLimiter":
    """Return shared rate limiter per API key (Anthropic org-level limits)."""
    from .rate_limiter import LLMRateLimiter

    if settings is None:
        from tg_parser.config import settings as settings

    if api_key not in _rate_limiter_cache:
        _rate_limiter_cache[api_key] = LLMRateLimiter.from_settings(settings)
    return _rate_limiter_cache[api_key]


def resolve_llm_config(
    stage: str,
    settings: Any = None,
) -> tuple[str, str | None, str | None]:
    """Return (provider, api_key, model) for a pipeline stage.

    Reads ``{stage}_llm_provider`` / ``{stage}_llm_model`` from settings,
    falling back to global ``llm_provider`` / ``llm_model`` when unset.

    Args:
        stage: ``"processing"`` or ``"topicization"``
        settings: Optional Settings object. Falls back to global singleton if not provided.
    """
    if settings is None:
        from tg_parser.config import settings as settings

    provider = getattr(settings, f"{stage}_llm_provider", None) or settings.llm_provider
    model = getattr(settings, f"{stage}_llm_model", None) or settings.llm_model

    api_key_map: dict[str, str | None] = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key or settings.google_api_key,
        "ollama": None,
    }
    api_key = api_key_map.get(provider)

    return provider, api_key, model


def create_llm_client(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    settings: Any = None,
    **kwargs: Any,
) -> LLMClient:
    """
    Create an LLM client for the given provider.
    
    Args:
        provider: "openai" | "anthropic" | "gemini" | "ollama"
        api_key: Provider API key (not required for Ollama)
        model: Model override (default depends on provider)
        base_url: Custom base URL (for Ollama or OpenAI-compatible proxies)
        settings: Optional Settings for provider-specific config. Falls back to global singleton.
        **kwargs: Additional client parameters
        
    Returns:
        LLMClient instance
        
    Raises:
        ValueError: Unknown provider or missing API key
    """
    provider = provider.lower()
    
    if provider == "openai":
        from .openai_client import OpenAIClient
        
        if not api_key:
            raise ValueError("OpenAI API key required")
        
        return OpenAIClient(
            api_key=api_key,
            model=model or "gpt-4o-mini",
            base_url=base_url,
            **kwargs,
        )
    
    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient

        if not api_key:
            raise ValueError("Anthropic API key required")

        if settings is None:
            from tg_parser.config import settings as settings

        rate_limiter = _get_or_create_rate_limiter(api_key, settings=settings)

        return AnthropicClient(
            api_key=api_key,
            model=model or "claude-sonnet-4-20250514",
            rate_limiter=rate_limiter,
            prompt_caching_enabled=getattr(settings, "anthropic_prompt_caching_enabled", True),
            rate_limit_input_estimate=getattr(settings, "processing_anthropic_input_token_estimate", 2000),
            rate_limit_output_estimate=getattr(settings, "processing_anthropic_output_token_estimate", 2048),
            max_retries_429=5,
            **kwargs,
        )
    
    elif provider == "gemini":
        from .gemini_client import GeminiClient
        
        if not api_key:
            raise ValueError("Gemini API key required")
        
        return GeminiClient(
            api_key=api_key,
            model=model or "gemini-2.0-flash-exp",
            **kwargs,
        )
    
    elif provider == "ollama":
        from .ollama_client import OllamaClient
        
        return OllamaClient(
            model=model or "llama3.2",
            base_url=base_url or "http://localhost:11434",
            **kwargs,
        )
    
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: openai, anthropic, gemini, ollama"
        )


def get_model_id_from_client(client: LLMClient) -> str:
    """
    Извлечь model_id из LLM клиента.
    
    Args:
        client: LLM клиент instance
        
    Returns:
        Model ID строка
    """
    if hasattr(client, "model"):
        return client.model
    return "unknown"


def get_provider_from_client(client: LLMClient) -> str:
    """
    Определить провайдера по типу клиента.
    
    Args:
        client: LLM клиент instance
        
    Returns:
        Provider name
    """
    class_name = client.__class__.__name__
    
    if "OpenAI" in class_name:
        return "openai"
    elif "Anthropic" in class_name:
        return "anthropic"
    elif "Gemini" in class_name:
        return "gemini"
    elif "Ollama" in class_name:
        return "ollama"
    else:
        return "unknown"

