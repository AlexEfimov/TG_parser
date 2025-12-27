"""
Tools for TG Processing Agent.

Function tools for text cleaning, topic extraction, and entity extraction.
Includes both basic (regex-based) and LLM-enhanced versions.
Phase 2E: Added pipeline_tool for hybrid mode.
"""

from .text_tools import (
    # Basic tools (no LLM required)
    clean_text,
    extract_entities,
    extract_topics,
    # LLM-enhanced tools (Phase 2C)
    analyze_text_deep,
    extract_entities_llm,
    extract_topics_llm,
    # Context for LLM access
    AgentContext,
    # Result models
    CleanTextResult,
    DeepAnalysisResult,
    EntitiesResult,
    EntityItem,
    ProcessingResult,
    TopicsResult,
)

# Phase 2E: Pipeline tool for hybrid mode
from .pipeline_tool import PipelineResult, process_with_pipeline

__all__ = [
    # Basic tools
    "clean_text",
    "extract_topics",
    "extract_entities",
    # LLM-enhanced tools
    "analyze_text_deep",
    "extract_topics_llm",
    "extract_entities_llm",
    # Pipeline tool (Phase 2E)
    "process_with_pipeline",
    # Context
    "AgentContext",
    # Models
    "CleanTextResult",
    "DeepAnalysisResult",
    "EntitiesResult",
    "EntityItem",
    "ProcessingResult",
    "TopicsResult",
    "PipelineResult",
]

