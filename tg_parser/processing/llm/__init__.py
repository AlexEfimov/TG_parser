"""
LLM адаптеры для processing layer.

Реализации LLMClient для различных провайдеров.
"""

from tg_parser.processing.llm.openai_client import OpenAIClient

__all__ = ["OpenAIClient"]
