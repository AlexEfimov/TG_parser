"""
Agent Registry for Multi-Agent Architecture.

Phase 3A: Central registry for agent discovery, registration, and lookup.
Phase 3B: Added persistence support for state recovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .base import (
    AgentCapability,
    AgentMetadata,
    AgentType,
    BaseAgent,
)

if TYPE_CHECKING:
    from .persistence import AgentPersistence

logger = logging.getLogger(__name__)


# ============================================================================
# Agent Registration Entry
# ============================================================================


@dataclass
class AgentRegistration:
    """Entry in the agent registry."""
    
    agent: BaseAgent
    metadata: AgentMetadata
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True
    
    # Statistics
    total_tasks_processed: int = 0
    total_errors: int = 0
    avg_processing_time_ms: float = 0.0
    last_used_at: datetime | None = None


# ============================================================================
# Agent Registry
# ============================================================================


class AgentRegistry:
    """
    Central registry for managing agents.
    
    Provides:
    - Agent registration and unregistration
    - Lookup by name, type, or capability
    - Health monitoring
    - Statistics tracking
    - Persistence support (Phase 3B)
    """
    
    def __init__(self, persistence: AgentPersistence | None = None):
        """
        Initialize empty registry.
        
        Args:
            persistence: Optional persistence layer for state recovery
        """
        self._agents: dict[str, AgentRegistration] = {}
        self._by_type: dict[AgentType, list[str]] = {}
        self._by_capability: dict[AgentCapability, list[str]] = {}
        self._created_at = datetime.now(UTC)
        self._persistence = persistence
    
    # =========================================================================
    # Registration
    # =========================================================================
    
    def register(self, agent: BaseAgent) -> None:
        """
        Register an agent with the registry.
        
        Args:
            agent: Agent instance to register
            
        Raises:
            ValueError: If agent with same name already registered
        """
        name = agent.name
        
        if name in self._agents:
            raise ValueError(f"Agent '{name}' is already registered")
        
        # Create registration entry
        registration = AgentRegistration(
            agent=agent,
            metadata=agent.metadata,
        )
        
        # Store in main registry
        self._agents[name] = registration
        
        # Index by type
        agent_type = agent.agent_type
        if agent_type not in self._by_type:
            self._by_type[agent_type] = []
        self._by_type[agent_type].append(name)
        
        # Index by capabilities
        for capability in agent.capabilities:
            if capability not in self._by_capability:
                self._by_capability[capability] = []
            self._by_capability[capability].append(name)
        
        logger.info(
            f"Registered agent: {name} (type={agent_type.value}, "
            f"capabilities={[c.value for c in agent.capabilities]})"
        )
    
    async def register_with_persistence(self, agent: BaseAgent) -> None:
        """
        Register an agent and save to persistent storage.
        
        Also restores statistics if available.
        
        Args:
            agent: Agent instance to register
        """
        # First register normally
        self.register(agent)
        
        # Then persist and restore stats
        if self._persistence:
            # Save agent state
            await self._persistence.save_agent_state(agent)
            
            # Restore statistics if available
            stats = await self._persistence.restore_agent_statistics(agent)
            if stats:
                registration = self._agents.get(agent.name)
                if registration:
                    registration.total_tasks_processed = stats.get("total_tasks_processed", 0)
                    registration.total_errors = stats.get("total_errors", 0)
                    registration.avg_processing_time_ms = stats.get("avg_processing_time_ms", 0.0)
                    registration.last_used_at = stats.get("last_used_at")
                    logger.info(f"Restored statistics for agent {agent.name}")
    
    def unregister(self, name: str) -> bool:
        """
        Unregister an agent from the registry.
        
        Args:
            name: Name of agent to unregister
            
        Returns:
            True if agent was unregistered, False if not found
        """
        if name not in self._agents:
            return False
        
        registration = self._agents[name]
        agent = registration.agent
        
        # Remove from type index
        agent_type = agent.agent_type
        if agent_type in self._by_type:
            self._by_type[agent_type] = [n for n in self._by_type[agent_type] if n != name]
        
        # Remove from capability index
        for capability in agent.capabilities:
            if capability in self._by_capability:
                self._by_capability[capability] = [
                    n for n in self._by_capability[capability] if n != name
                ]
        
        # Remove from main registry
        del self._agents[name]
        
        logger.info(f"Unregistered agent: {name}")
        return True
    
    async def unregister_with_persistence(self, name: str) -> bool:
        """
        Unregister an agent and mark as inactive in storage.
        
        Args:
            name: Name of agent to unregister
            
        Returns:
            True if agent was unregistered, False if not found
        """
        result = self.unregister(name)
        
        if result and self._persistence:
            await self._persistence.mark_agent_inactive(name)
        
        return result
    
    # =========================================================================
    # Lookup
    # =========================================================================
    
    def get(self, name: str) -> BaseAgent | None:
        """
        Get agent by name.
        
        Args:
            name: Agent name
            
        Returns:
            Agent instance or None if not found
        """
        registration = self._agents.get(name)
        return registration.agent if registration else None
    
    def get_registration(self, name: str) -> AgentRegistration | None:
        """
        Get full registration entry by name.
        
        Args:
            name: Agent name
            
        Returns:
            Registration entry or None if not found
        """
        return self._agents.get(name)
    
    def get_by_type(self, agent_type: AgentType) -> list[BaseAgent]:
        """
        Get all agents of a specific type.
        
        Args:
            agent_type: Type of agents to find
            
        Returns:
            List of matching agents
        """
        names = self._by_type.get(agent_type, [])
        return [self._agents[n].agent for n in names if n in self._agents]
    
    def get_by_capability(self, capability: AgentCapability) -> list[BaseAgent]:
        """
        Get all agents with a specific capability.
        
        Args:
            capability: Capability to search for
            
        Returns:
            List of agents with that capability
        """
        names = self._by_capability.get(capability, [])
        return [self._agents[n].agent for n in names if n in self._agents]
    
    def get_active(self) -> list[BaseAgent]:
        """
        Get all active agents.
        
        Returns:
            List of active agents
        """
        return [
            reg.agent for reg in self._agents.values() 
            if reg.is_active
        ]
    
    def find_best_for_capability(
        self,
        capability: AgentCapability,
        prefer_type: AgentType | None = None,
    ) -> BaseAgent | None:
        """
        Find the best agent for a specific capability.
        
        Uses heuristics to select:
        1. Prefer specified agent type if provided
        2. Prefer agents with fewer errors
        3. Prefer agents with lower average processing time
        
        Args:
            capability: Required capability
            prefer_type: Preferred agent type (optional)
            
        Returns:
            Best matching agent or None
        """
        candidates = self.get_by_capability(capability)
        
        if not candidates:
            return None
        
        if len(candidates) == 1:
            return candidates[0]
        
        # Filter by preferred type if specified
        if prefer_type:
            typed_candidates = [a for a in candidates if a.agent_type == prefer_type]
            if typed_candidates:
                candidates = typed_candidates
        
        # Sort by error rate and processing time
        def score(agent: BaseAgent) -> tuple[float, float]:
            reg = self._agents.get(agent.name)
            if not reg:
                return (1.0, float("inf"))
            
            # Error rate (lower is better)
            total = reg.total_tasks_processed or 1
            error_rate = reg.total_errors / total
            
            # Processing time (lower is better)
            avg_time = reg.avg_processing_time_ms
            
            return (error_rate, avg_time)
        
        candidates.sort(key=score)
        return candidates[0]
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def record_task_completion(
        self,
        name: str,
        processing_time_ms: float,
        success: bool = True,
    ) -> None:
        """
        Record task completion statistics for an agent.
        
        Args:
            name: Agent name
            processing_time_ms: Time taken to process
            success: Whether task succeeded
        """
        registration = self._agents.get(name)
        if not registration:
            return
        
        registration.total_tasks_processed += 1
        if not success:
            registration.total_errors += 1
        
        # Update rolling average
        n = registration.total_tasks_processed
        old_avg = registration.avg_processing_time_ms
        registration.avg_processing_time_ms = old_avg + (processing_time_ms - old_avg) / n
        
        registration.last_used_at = datetime.now(UTC)
    
    async def record_task_completion_with_persistence(
        self,
        name: str,
        task_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None = None,
        processing_time_ms: float = 0,
        success: bool = True,
        error: str | None = None,
        source_ref: str | None = None,
        channel_id: str | None = None,
    ) -> str | None:
        """
        Record task completion with full persistence.
        
        Updates in-memory stats and persists to storage.
        
        Args:
            name: Agent name
            task_type: Type of task executed
            input_data: Task input data
            output_data: Task output data
            processing_time_ms: Time taken to process
            success: Whether task succeeded
            error: Error message if failed
            source_ref: Source reference
            channel_id: Channel ID
            
        Returns:
            Task ID if persistence enabled, None otherwise
        """
        # Update in-memory stats
        self.record_task_completion(name, processing_time_ms, success)
        
        # Persist if enabled
        if self._persistence:
            return await self._persistence.record_task(
                agent_name=name,
                task_type=task_type,
                input_data=input_data,
                output_data=output_data,
                success=success,
                error=error,
                processing_time_ms=int(processing_time_ms),
                source_ref=source_ref,
                channel_id=channel_id,
            )
        
        return None
    
    def get_statistics(self) -> dict[str, Any]:
        """
        Get registry statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "total_agents": len(self._agents),
            "active_agents": len([r for r in self._agents.values() if r.is_active]),
            "by_type": {
                t.value: len(names) for t, names in self._by_type.items()
            },
            "by_capability": {
                c.value: len(names) for c, names in self._by_capability.items()
            },
            "agents": {
                name: {
                    "type": reg.metadata.agent_type.value,
                    "capabilities": [c.value for c in reg.metadata.capabilities],
                    "is_active": reg.is_active,
                    "total_tasks": reg.total_tasks_processed,
                    "total_errors": reg.total_errors,
                    "avg_processing_time_ms": round(reg.avg_processing_time_ms, 2),
                    "last_used": reg.last_used_at.isoformat() if reg.last_used_at else None,
                }
                for name, reg in self._agents.items()
            },
        }
    
    # =========================================================================
    # Health
    # =========================================================================
    
    async def health_check_all(self) -> dict[str, bool]:
        """
        Run health check on all registered agents.
        
        Returns:
            Dictionary mapping agent name to health status
        """
        results = {}
        
        for name, registration in self._agents.items():
            try:
                healthy = await registration.agent.health_check()
                results[name] = healthy
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                results[name] = False
        
        return results
    
    async def initialize_all(self) -> dict[str, bool]:
        """
        Initialize all registered agents.
        
        Returns:
            Dictionary mapping agent name to initialization status
        """
        results = {}
        
        for name, registration in self._agents.items():
            try:
                await registration.agent.initialize()
                results[name] = True
            except Exception as e:
                logger.error(f"Initialization failed for {name}: {e}")
                results[name] = False
                registration.is_active = False
        
        return results
    
    async def shutdown_all(self) -> dict[str, bool]:
        """
        Shutdown all registered agents.
        
        Returns:
            Dictionary mapping agent name to shutdown status
        """
        results = {}
        
        for name, registration in self._agents.items():
            try:
                await registration.agent.shutdown()
                registration.is_active = False
                results[name] = True
            except Exception as e:
                logger.error(f"Shutdown failed for {name}: {e}")
                results[name] = False
        
        return results
    
    # =========================================================================
    # Iteration
    # =========================================================================
    
    def __len__(self) -> int:
        return len(self._agents)
    
    def __contains__(self, name: str) -> bool:
        return name in self._agents
    
    def __iter__(self):
        return iter(self._agents.values())
    
    def names(self) -> list[str]:
        """Get list of all registered agent names."""
        return list(self._agents.keys())


# ============================================================================
# Global Registry Instance
# ============================================================================


_global_registry: AgentRegistry | None = None


def get_registry(persistence: AgentPersistence | None = None) -> AgentRegistry:
    """
    Get the global agent registry.
    
    Creates a new registry if one doesn't exist.
    
    Args:
        persistence: Optional persistence layer (only used when creating new registry)
    
    Returns:
        Global AgentRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = AgentRegistry(persistence=persistence)
    return _global_registry


def reset_registry() -> None:
    """
    Reset the global registry.
    
    Used primarily for testing.
    """
    global _global_registry
    _global_registry = None


def set_registry_persistence(persistence: AgentPersistence) -> None:
    """
    Set persistence layer for the global registry.
    
    Args:
        persistence: Persistence layer to use
    """
    global _global_registry
    if _global_registry is not None:
        _global_registry._persistence = persistence

