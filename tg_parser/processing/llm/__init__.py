"""
LLM адаптеры для processing layer.

Реализации LLMClient для различных провайдеров.
"""

from tg_parser.processing.llm.anthropic_client import AnthropicClient
from tg_parser.processing.llm.factory import create_llm_client, get_model_id_from_client, get_provider_from_client
from tg_parser.processing.llm.gemini_client import GeminiClient
from tg_parser.processing.llm.ollama_client import OllamaClient
from tg_parser.processing.llm.openai_client import OpenAIClient

__all__ = [
    "OpenAIClient",
    "AnthropicClient",
    "GeminiClient",
    "OllamaClient",
    "create_llm_client",
    "get_model_id_from_client",
    "get_provider_from_client",
]
