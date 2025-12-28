"""
Agents module for TG Parser.

OpenAI Agents SDK integration for message processing.
Phase 2B: Basic agent with pattern-based tools.
Phase 2C: LLM-enhanced tools and multi-provider support.
Phase 2E: Hybrid mode with v1.2 pipeline as agent tool.
Phase 3A: Multi-Agent Architecture with orchestration.
Phase 3B: Agent State Persistence.
"""

# Original v2.0 exports
from .processing_agent import (
    TGProcessingAgent,
    process_batch_with_agent,
    process_message_with_agent,
)
from .tools import AgentContext, DeepAnalysisResult, PipelineResult, process_with_pipeline

# Phase 3A: Multi-Agent Architecture
from .base import (
    AgentCapability,
    AgentInput,
    AgentMetadata,
    AgentOutput,
    AgentType,
    BaseAgent,
    HandoffRequest,
    HandoffResponse,
    HandoffStatus,
)
from .registry import (
    AgentRegistry,
    get_registry,
    reset_registry,
    set_registry_persistence,
)
from .orchestrator import OrchestratorAgent, Workflow, WorkflowStep

# Specialized Agents
from .specialized import ProcessingAgent, TopicizationAgent, ExportAgent

# Phase 3B: Persistence
from .persistence import AgentPersistence

__all__ = [
    # Original v2.0
    "TGProcessingAgent",
    "process_message_with_agent",
    "process_batch_with_agent",
    "AgentContext",
    "DeepAnalysisResult",
    "process_with_pipeline",
    "PipelineResult",
    # Phase 3A: Base
    "AgentCapability",
    "AgentInput",
    "AgentMetadata",
    "AgentOutput",
    "AgentType",
    "BaseAgent",
    "HandoffRequest",
    "HandoffResponse",
    "HandoffStatus",
    # Phase 3A: Registry
    "AgentRegistry",
    "get_registry",
    "reset_registry",
    "set_registry_persistence",
    # Phase 3A: Orchestrator
    "OrchestratorAgent",
    "Workflow",
    "WorkflowStep",
    # Phase 3A: Specialized Agents
    "ProcessingAgent",
    "TopicizationAgent",
    "ExportAgent",
    # Phase 3B: Persistence
    "AgentPersistence",
]

