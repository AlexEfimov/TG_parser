"""
Модуль обработки сообщений (LLM, очистка, извлечение структуры).

Порты и реализации для ProcessedDocument и топикализации.
"""

from .mock_llm import DeterministicMockLLM, MockLLMClient, ProcessingMockLLM
from .pipeline import ProcessingPipelineImpl, create_processing_pipeline
from .ports import LLMClient, ProcessingPipeline, TopicizationPipeline
from .topicization import TopicizationPipelineImpl

__all__ = [
    "LLMClient",
    "ProcessingPipeline",
    "TopicizationPipeline",
    "MockLLMClient",
    "DeterministicMockLLM",
    "ProcessingMockLLM",
    "ProcessingPipelineImpl",
    "TopicizationPipelineImpl",
    "create_processing_pipeline",
]
