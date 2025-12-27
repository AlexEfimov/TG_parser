"""
Agents module for TG Parser.

OpenAI Agents SDK integration for message processing.
Phase 2B: Basic agent with pattern-based tools.
Phase 2C: LLM-enhanced tools and multi-provider support.
"""

from .processing_agent import (
    TGProcessingAgent,
    process_batch_with_agent,
    process_message_with_agent,
)
from .tools import AgentContext, DeepAnalysisResult

__all__ = [
    "TGProcessingAgent",
    "process_message_with_agent",
    "process_batch_with_agent",
    "AgentContext",
    "DeepAnalysisResult",
]

