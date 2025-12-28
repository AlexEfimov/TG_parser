"""
Agent State Persistence Layer.

Phase 3B: Integrates AgentRegistry with persistent storage.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from tg_parser.storage.ports import (
    AgentDailyStats,
    AgentState,
    AgentStateRepo,
    AgentStatsRepo,
    HandoffHistoryRepo,
    HandoffRecord,
    TaskHistoryRepo,
    TaskRecord,
)

from .base import AgentMetadata, BaseAgent, HandoffRequest, HandoffResponse

logger = logging.getLogger(__name__)


class AgentPersistence:
    """
    Persistence layer for agent state and history.
    
    Provides a unified interface for:
    - Saving/restoring agent state
    - Recording task execution history
    - Tracking handoffs between agents
    - Aggregating statistics
    
    Can be attached to AgentRegistry for automatic persistence.
    """
    
    def __init__(
        self,
        agent_state_repo: AgentStateRepo | None = None,
        task_history_repo: TaskHistoryRepo | None = None,
        agent_stats_repo: AgentStatsRepo | None = None,
        handoff_history_repo: HandoffHistoryRepo | None = None,
        retention_days: int = 14,
        stats_enabled: bool = True,
    ):
        """
        Initialize persistence layer.
        
        All repositories are optional - only enabled features will work.
        
        Args:
            agent_state_repo: Repository for agent state
            task_history_repo: Repository for task history
            agent_stats_repo: Repository for aggregated statistics
            handoff_history_repo: Repository for handoff history
            retention_days: Default retention period for task history
            stats_enabled: Whether to record aggregated statistics
        """
        self._agent_state_repo = agent_state_repo
        self._task_history_repo = task_history_repo
        self._agent_stats_repo = agent_stats_repo
        self._handoff_history_repo = handoff_history_repo
        self._retention_days = retention_days
        self._stats_enabled = stats_enabled
    
    @property
    def is_enabled(self) -> bool:
        """Check if any persistence is enabled."""
        return any([
            self._agent_state_repo,
            self._task_history_repo,
            self._agent_stats_repo,
            self._handoff_history_repo,
        ])
    
    # =========================================================================
    # Agent State
    # =========================================================================
    
    async def save_agent_state(self, agent: BaseAgent) -> None:
        """
        Save agent state to persistent storage.
        
        Called when agent is registered or updated.
        """
        if not self._agent_state_repo:
            return
        
        metadata = agent.metadata
        state = AgentState(
            name=metadata.name,
            agent_type=metadata.agent_type.value,
            version=metadata.version,
            description=metadata.description,
            capabilities=[c.value for c in metadata.capabilities],
            model=metadata.model,
            provider=metadata.provider,
            is_active=True,
            metadata=metadata.extra,
        )
        
        await self._agent_state_repo.save(state)
        logger.debug(f"Saved agent state: {metadata.name}")
    
    async def load_agent_state(self, name: str) -> AgentState | None:
        """
        Load agent state from persistent storage.
        
        Returns None if agent not found or persistence disabled.
        """
        if not self._agent_state_repo:
            return None
        
        return await self._agent_state_repo.get(name)
    
    async def restore_agent_statistics(
        self,
        agent: BaseAgent,
    ) -> dict[str, Any] | None:
        """
        Restore agent statistics from persistent storage.
        
        Returns dict with restored stats or None if not found.
        """
        if not self._agent_state_repo:
            return None
        
        state = await self._agent_state_repo.get(agent.name)
        if not state:
            return None
        
        return {
            "total_tasks_processed": state.total_tasks_processed,
            "total_errors": state.total_errors,
            "avg_processing_time_ms": state.avg_processing_time_ms,
            "last_used_at": state.last_used_at,
        }
    
    async def mark_agent_inactive(self, name: str) -> None:
        """Mark agent as inactive in persistent storage."""
        if not self._agent_state_repo:
            return
        
        state = await self._agent_state_repo.get(name)
        if state:
            state.is_active = False
            state.updated_at = datetime.now(UTC)
            await self._agent_state_repo.save(state)
            logger.debug(f"Marked agent inactive: {name}")
    
    async def delete_agent_state(self, name: str) -> bool:
        """Delete agent state from persistent storage."""
        if not self._agent_state_repo:
            return False
        
        return await self._agent_state_repo.delete(name)
    
    async def list_all_agent_states(
        self,
        agent_type: str | None = None,
    ) -> list[AgentState]:
        """List all saved agent states."""
        if not self._agent_state_repo:
            return []
        
        return await self._agent_state_repo.list_all(agent_type)
    
    # =========================================================================
    # Task History
    # =========================================================================
    
    async def record_task(
        self,
        agent_name: str,
        task_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        processing_time_ms: int | None = None,
        source_ref: str | None = None,
        channel_id: str | None = None,
    ) -> str | None:
        """
        Record a task execution.
        
        Also updates agent statistics if enabled.
        
        Returns: Task ID or None if persistence disabled
        """
        task_id = None
        
        # Record full task history
        if self._task_history_repo:
            task_id = await self._task_history_repo.record(
                agent_name=agent_name,
                task_type=task_type,
                input_data=input_data,
                output_data=output_data,
                success=success,
                error=error,
                processing_time_ms=processing_time_ms,
                source_ref=source_ref,
                channel_id=channel_id,
                retention_days=self._retention_days,
            )
        
        # Update aggregated statistics
        if self._stats_enabled and self._agent_stats_repo and processing_time_ms is not None:
            await self._agent_stats_repo.record(
                agent_name=agent_name,
                task_type=task_type,
                success=success,
                processing_time_ms=processing_time_ms,
            )
        
        # Update agent state statistics
        if self._agent_state_repo and processing_time_ms is not None:
            await self._agent_state_repo.update_statistics(
                name=agent_name,
                processing_time_ms=processing_time_ms,
                success=success,
            )
        
        return task_id
    
    async def get_task_history(
        self,
        agent_name: str | None = None,
        channel_id: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        """Get task history with filters."""
        if not self._task_history_repo:
            return []
        
        if agent_name:
            return await self._task_history_repo.list_by_agent(
                agent_name=agent_name,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
            )
        elif channel_id:
            return await self._task_history_repo.list_by_channel(
                channel_id=channel_id,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
            )
        
        return []
    
    async def cleanup_expired_tasks(self) -> int:
        """Clean up expired task history records."""
        if not self._task_history_repo:
            return 0
        
        return await self._task_history_repo.cleanup_expired()
    
    # =========================================================================
    # Handoff History
    # =========================================================================
    
    async def record_handoff_request(
        self,
        request: HandoffRequest,
    ) -> None:
        """Record a handoff request."""
        if not self._handoff_history_repo:
            return
        
        await self._handoff_history_repo.record(
            source_agent=request.source_agent,
            target_agent=request.target_agent,
            task_type=request.task_type,
            handoff_id=request.id,
            priority=request.priority,
            payload=request.payload,
            context=request.context,
        )
    
    async def record_handoff_response(
        self,
        response: HandoffResponse,
    ) -> None:
        """Record a handoff response."""
        if not self._handoff_history_repo:
            return
        
        await self._handoff_history_repo.update_status(
            handoff_id=response.handoff_id,
            status=response.status.value if hasattr(response.status, 'value') else response.status,
            result=response.result,
            error=response.error,
            processing_time_ms=response.processing_time_ms,
        )
    
    async def get_handoff_history(
        self,
        agent_name: str,
        as_source: bool = True,
        status: str | None = None,
        limit: int = 100,
    ) -> list[HandoffRecord]:
        """Get handoff history for an agent."""
        if not self._handoff_history_repo:
            return []
        
        return await self._handoff_history_repo.list_by_agent(
            agent_name=agent_name,
            as_source=as_source,
            status=status,
            limit=limit,
        )
    
    async def get_handoff_statistics(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Get handoff statistics."""
        if not self._handoff_history_repo:
            return {}
        
        return await self._handoff_history_repo.get_statistics(
            from_date=from_date,
            to_date=to_date,
        )
    
    # =========================================================================
    # Agent Statistics
    # =========================================================================
    
    async def get_agent_summary(
        self,
        agent_name: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get summary statistics for an agent."""
        if not self._agent_stats_repo:
            return {}
        
        return await self._agent_stats_repo.get_summary(
            agent_name=agent_name,
            days=days,
        )
    
    async def get_daily_stats(
        self,
        agent_name: str,
        date: str,
        task_type: str | None = None,
    ) -> list[AgentDailyStats]:
        """Get daily statistics for an agent."""
        if not self._agent_stats_repo:
            return []
        
        return await self._agent_stats_repo.get_daily(
            agent_name=agent_name,
            date=date,
            task_type=task_type,
        )
    
    async def get_stats_range(
        self,
        agent_name: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[AgentDailyStats]:
        """Get statistics for a date range."""
        if not self._agent_stats_repo:
            return []
        
        return await self._agent_stats_repo.get_range(
            agent_name=agent_name,
            from_date=from_date,
            to_date=to_date,
        )

