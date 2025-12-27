"""
Agents module for TG Parser.

OpenAI Agents SDK integration for message processing.
Phase 2B: Basic agent with pattern-based tools.
Phase 2C: LLM-enhanced tools and multi-provider support.
Phase 2E: Hybrid mode with v1.2 pipeline as agent tool.
"""

from .processing_agent import (
    TGProcessingAgent,
    process_batch_with_agent,
    process_message_with_agent,
)
from .tools import AgentContext, DeepAnalysisResult, PipelineResult, process_with_pipeline

__all__ = [
    "TGProcessingAgent",
    "process_message_with_agent",
    "process_batch_with_agent",
    "AgentContext",
    "DeepAnalysisResult",
    # Phase 2E
    "process_with_pipeline",
    "PipelineResult",
]

