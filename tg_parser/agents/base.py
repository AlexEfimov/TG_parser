"""
Base classes and protocols for Multi-Agent Architecture.

Phase 3A: Defines the foundation for specialized agents and orchestration.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Agent Capabilities
# ============================================================================


class AgentCapability(str, Enum):
    """Capabilities that agents can have."""
    
    TEXT_PROCESSING = "text_processing"
    TOPIC_EXTRACTION = "topic_extraction"
    ENTITY_EXTRACTION = "entity_extraction"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    SUMMARIZATION = "summarization"
    DEEP_ANALYSIS = "deep_analysis"
    TOPICIZATION = "topicization"
    EXPORT = "export"
    ORCHESTRATION = "orchestration"


class AgentType(str, Enum):
    """Types of agents in the system."""
    
    PROCESSING = "processing"
    TOPICIZATION = "topicization"
    EXPORT = "export"
    ORCHESTRATOR = "orchestrator"
    CLASSIFIER = "classifier"


# ============================================================================
# Agent Metadata
# ============================================================================


@dataclass
class AgentMetadata:
    """Metadata describing an agent's identity and capabilities."""
    
    name: str
    agent_type: AgentType
    version: str = "1.0.0"
    description: str = ""
    capabilities: list[AgentCapability] = field(default_factory=list)
    model: str = "gpt-4o-mini"
    provider: str = "openai"
    
    # Performance hints
    max_concurrent_tasks: int = 5
    avg_processing_time_ms: int | None = None
    
    # Extra metadata
    extra: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Handoff Protocol
# ============================================================================


class HandoffStatus(str, Enum):
    """Status of a handoff between agents."""
    
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class HandoffRequest(BaseModel):
    """Request to hand off work from one agent to another."""
    
    model_config = {"use_enum_values": True}
    
    id: str = Field(description="Unique handoff ID")
    source_agent: str = Field(description="Name of the source agent")
    target_agent: str = Field(description="Name of the target agent")
    task_type: str = Field(description="Type of task being handed off")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task data")
    context: dict[str, Any] = Field(default_factory=dict, description="Shared context")
    priority: int = Field(default=5, ge=1, le=10, description="Priority 1-10 (10=highest)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HandoffResponse(BaseModel):
    """Response from a handoff operation."""
    
    model_config = {"use_enum_values": True}
    
    handoff_id: str = Field(description="ID of the original handoff request")
    status: HandoffStatus = Field(description="Status of the handoff")
    result: dict[str, Any] = Field(default_factory=dict, description="Result data if completed")
    error: str | None = Field(default=None, description="Error message if failed")
    processing_time_ms: int | None = Field(default=None, description="Time taken to process")
    completed_at: datetime | None = Field(default=None)


# ============================================================================
# Agent Input/Output Types
# ============================================================================


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class AgentInput(BaseModel):
    """Base class for agent input."""
    
    task_id: str = Field(description="Unique task identifier")
    data: dict[str, Any] = Field(default_factory=dict, description="Input data")
    context: dict[str, Any] = Field(default_factory=dict, description="Shared context")
    options: dict[str, Any] = Field(default_factory=dict, description="Processing options")


class AgentOutput(BaseModel):
    """Base class for agent output."""
    
    task_id: str = Field(description="Task identifier from input")
    success: bool = Field(default=True, description="Whether processing succeeded")
    result: dict[str, Any] = Field(default_factory=dict, description="Output data")
    error: str | None = Field(default=None, description="Error message if failed")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Processing metadata")
    processing_time_ms: int | None = Field(default=None)


# ============================================================================
# Base Agent Protocol
# ============================================================================


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """
    Abstract base class for all agents in the system.
    
    Defines the common interface that all agents must implement.
    Supports the A + C hybrid architecture pattern.
    """
    
    def __init__(self, metadata: AgentMetadata):
        """
        Initialize the agent with metadata.
        
        Args:
            metadata: Agent metadata describing capabilities
        """
        self._metadata = metadata
        self._is_initialized = False
        self._created_at = datetime.now(UTC)
    
    @property
    def metadata(self) -> AgentMetadata:
        """Get agent metadata."""
        return self._metadata
    
    @property
    def name(self) -> str:
        """Get agent name."""
        return self._metadata.name
    
    @property
    def agent_type(self) -> AgentType:
        """Get agent type."""
        return self._metadata.agent_type
    
    @property
    def capabilities(self) -> list[AgentCapability]:
        """Get agent capabilities."""
        return self._metadata.capabilities
    
    def has_capability(self, capability: AgentCapability) -> bool:
        """Check if agent has a specific capability."""
        return capability in self._metadata.capabilities
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the agent.
        
        Called once before the agent starts processing.
        Should set up any required resources.
        """
        pass
    
    @abstractmethod
    async def process(self, input_data: InputT) -> OutputT:
        """
        Process input and produce output.
        
        Args:
            input_data: Input data to process
            
        Returns:
            Processed output
        """
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """
        Shutdown the agent.
        
        Called when the agent is being stopped.
        Should clean up any resources.
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Check if the agent is healthy.
        
        Returns:
            True if agent is ready to process, False otherwise
        """
        return self._is_initialized
    
    async def handle_handoff(self, request: HandoffRequest) -> HandoffResponse:
        """
        Handle a handoff request from another agent.
        
        Default implementation accepts and processes the handoff.
        Subclasses can override for custom behavior.
        
        Args:
            request: Handoff request
            
        Returns:
            Handoff response with result
        """
        start_time = datetime.now(UTC)
        
        try:
            # Convert handoff payload to agent input
            agent_input = AgentInput(
                task_id=request.id,
                data=request.payload,
                context=request.context,
            )
            
            # Process the input
            result = await self.process(agent_input)  # type: ignore
            
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            # Build response based on result type
            if isinstance(result, AgentOutput):
                return HandoffResponse(
                    handoff_id=request.id,
                    status=HandoffStatus.COMPLETED if result.success else HandoffStatus.FAILED,
                    result=result.result,
                    error=result.error,
                    processing_time_ms=processing_time,
                    completed_at=end_time,
                )
            else:
                # Handle raw dict or other return types
                return HandoffResponse(
                    handoff_id=request.id,
                    status=HandoffStatus.COMPLETED,
                    result={"data": result} if not isinstance(result, dict) else result,
                    processing_time_ms=processing_time,
                    completed_at=end_time,
                )
                
        except Exception as e:
            logger.error(f"Handoff processing failed: {e}", exc_info=True)
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return HandoffResponse(
                handoff_id=request.id,
                status=HandoffStatus.FAILED,
                error=str(e),
                processing_time_ms=processing_time,
                completed_at=end_time,
            )
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, type={self.agent_type.value!r})"


# ============================================================================
# Specialized Agent Base Classes
# ============================================================================


class ProcessingAgentBase(BaseAgent[AgentInput, AgentOutput]):
    """Base class for message processing agents."""
    
    def __init__(
        self,
        name: str = "ProcessingAgent",
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        **kwargs,
    ):
        metadata = AgentMetadata(
            name=name,
            agent_type=AgentType.PROCESSING,
            capabilities=[
                AgentCapability.TEXT_PROCESSING,
                AgentCapability.ENTITY_EXTRACTION,
                AgentCapability.SUMMARIZATION,
            ],
            model=model,
            provider=provider,
            **kwargs,
        )
        super().__init__(metadata)


class TopicizationAgentBase(BaseAgent[AgentInput, AgentOutput]):
    """Base class for topicization agents."""
    
    def __init__(
        self,
        name: str = "TopicizationAgent",
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        **kwargs,
    ):
        metadata = AgentMetadata(
            name=name,
            agent_type=AgentType.TOPICIZATION,
            capabilities=[
                AgentCapability.TOPIC_EXTRACTION,
                AgentCapability.TOPICIZATION,
            ],
            model=model,
            provider=provider,
            **kwargs,
        )
        super().__init__(metadata)


class ExportAgentBase(BaseAgent[AgentInput, AgentOutput]):
    """Base class for export agents."""
    
    def __init__(
        self,
        name: str = "ExportAgent",
        **kwargs,
    ):
        metadata = AgentMetadata(
            name=name,
            agent_type=AgentType.EXPORT,
            capabilities=[AgentCapability.EXPORT],
            **kwargs,
        )
        super().__init__(metadata)


class OrchestratorAgentBase(BaseAgent[AgentInput, AgentOutput]):
    """Base class for orchestrator agents."""
    
    def __init__(
        self,
        name: str = "OrchestratorAgent",
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        **kwargs,
    ):
        metadata = AgentMetadata(
            name=name,
            agent_type=AgentType.ORCHESTRATOR,
            capabilities=[AgentCapability.ORCHESTRATION],
            model=model,
            provider=provider,
            **kwargs,
        )
        super().__init__(metadata)

