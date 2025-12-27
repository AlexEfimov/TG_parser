"""
LLM Client Factory.

Создаёт LLM клиент по провайдеру.
"""

import logging
from typing import Any

from tg_parser.processing.ports import LLMClient

logger = logging.getLogger(__name__)


def create_llm_client(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> LLMClient:
    """
    Создать LLM клиент по провайдеру.
    
    Args:
        provider: "openai" | "anthropic" | "gemini" | "ollama"
        api_key: API ключ провайдера (не требуется для Ollama)
        model: Модель (default зависит от провайдера)
        base_url: Custom base URL (для Ollama или OpenAI-compatible прокси)
        **kwargs: Дополнительные параметры для клиента
        
    Returns:
        LLMClient instance
        
    Raises:
        ValueError: Неизвестный провайдер или отсутствует API key
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
        
        return AnthropicClient(
            api_key=api_key,
            model=model or "claude-3-5-sonnet-20241022",
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

