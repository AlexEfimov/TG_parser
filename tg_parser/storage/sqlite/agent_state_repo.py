"""
SQLite implementation of AgentStateRepo for agent state persistence.

Phase 3B: Agent State Persistence.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import AgentState, AgentStateRepo

logger = logging.getLogger(__name__)


class SQLiteAgentStateRepo(AgentStateRepo):
    """
    SQLite implementation of agent state storage.
    
    Uses processing_storage.sqlite (agent_states table).
    """

    def __init__(self, session_factory):
        """
        Initialize with session factory.
        
        Args:
            session_factory: Callable that returns AsyncSession
        """
        self._session_factory = session_factory

    def _state_to_row(self, state: AgentState) -> dict:
        """Convert AgentState to database row dict."""
        return {
            "name": state.name,
            "agent_type": state.agent_type,
            "version": state.version,
            "description": state.description,
            "capabilities_json": json.dumps(state.capabilities),
            "model": state.model,
            "provider": state.provider,
            "is_active": bool(state.is_active),
            "metadata_json": json.dumps(state.metadata) if state.metadata else None,
            "total_tasks_processed": state.total_tasks_processed,
            "total_errors": state.total_errors,
            "avg_processing_time_ms": state.avg_processing_time_ms,
            "last_used_at": state.last_used_at.isoformat() if state.last_used_at else None,
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        }

    def _row_to_state(self, row) -> AgentState:
        """Convert database row to AgentState."""
        return AgentState(
            name=row.name,
            agent_type=row.agent_type,
            version=row.version,
            description=row.description or "",
            capabilities=json.loads(row.capabilities_json) if row.capabilities_json else [],
            model=row.model,
            provider=row.provider,
            is_active=bool(row.is_active),
            metadata=json.loads(row.metadata_json) if row.metadata_json else {},
            total_tasks_processed=row.total_tasks_processed,
            total_errors=row.total_errors,
            avg_processing_time_ms=row.avg_processing_time_ms,
            last_used_at=datetime.fromisoformat(row.last_used_at) if row.last_used_at else None,
            created_at=datetime.fromisoformat(row.created_at),
            updated_at=datetime.fromisoformat(row.updated_at),
        )

    async def save(self, state: AgentState) -> None:
        """Save or update agent state."""
        state.updated_at = datetime.now(UTC)
        row = self._state_to_row(state)
        
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO agent_states (
                        name, agent_type, version, description, capabilities_json,
                        model, provider, is_active, metadata_json,
                        total_tasks_processed, total_errors, avg_processing_time_ms,
                        last_used_at, created_at, updated_at
                    ) VALUES (
                        :name, :agent_type, :version, :description, :capabilities_json,
                        :model, :provider, :is_active, :metadata_json,
                        :total_tasks_processed, :total_errors, :avg_processing_time_ms,
                        :last_used_at, :created_at, :updated_at
                    )
                    ON CONFLICT(name) DO UPDATE SET
                        agent_type = :agent_type,
                        version = :version,
                        description = :description,
                        capabilities_json = :capabilities_json,
                        model = :model,
                        provider = :provider,
                        is_active = :is_active,
                        metadata_json = :metadata_json,
                        total_tasks_processed = :total_tasks_processed,
                        total_errors = :total_errors,
                        avg_processing_time_ms = :avg_processing_time_ms,
                        last_used_at = :last_used_at,
                        updated_at = :updated_at
                """),
                row,
            )
            await session.commit()
        
        logger.debug(f"Saved agent state: {state.name}")

    async def get(self, name: str) -> AgentState | None:
        """Get agent state by name."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM agent_states WHERE name = :name"),
                {"name": name},
            )
            row = result.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_state(row)

    async def list_all(self, agent_type: str | None = None) -> list[AgentState]:
        """List all agent states, optionally filtered by type."""
        query = "SELECT * FROM agent_states WHERE 1=1"
        params: dict = {}
        
        if agent_type is not None:
            query += " AND agent_type = :agent_type"
            params["agent_type"] = agent_type
        
        query += " ORDER BY name"
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_state(row) for row in rows]

    async def delete(self, name: str) -> bool:
        """Delete agent state. Returns True if deleted."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("DELETE FROM agent_states WHERE name = :name"),
                {"name": name},
            )
            await session.commit()
            
            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"Deleted agent state: {name}")
            
            return deleted

    async def update_statistics(
        self,
        name: str,
        processing_time_ms: float,
        success: bool,
    ) -> None:
        """
        Update agent statistics after task completion.
        
        Uses incremental update for rolling average.
        """
        async with self._session_factory() as session:
            # First, get current stats
            result = await session.execute(
                text("""
                    SELECT total_tasks_processed, total_errors, avg_processing_time_ms 
                    FROM agent_states WHERE name = :name
                """),
                {"name": name},
            )
            row = result.fetchone()
            
            if row is None:
                logger.warning(f"Cannot update statistics: agent {name} not found")
                return
            
            # Calculate new values
            total_tasks = row.total_tasks_processed + 1
            total_errors = row.total_errors + (0 if success else 1)
            old_avg = row.avg_processing_time_ms
            new_avg = old_avg + (processing_time_ms - old_avg) / total_tasks
            
            # Update
            await session.execute(
                text("""
                    UPDATE agent_states SET
                        total_tasks_processed = :total_tasks,
                        total_errors = :total_errors,
                        avg_processing_time_ms = :avg_time,
                        last_used_at = :last_used,
                        updated_at = :updated_at
                    WHERE name = :name
                """),
                {
                    "name": name,
                    "total_tasks": total_tasks,
                    "total_errors": total_errors,
                    "avg_time": new_avg,
                    "last_used": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            await session.commit()
        
        logger.debug(f"Updated statistics for agent {name}: tasks={total_tasks}, errors={total_errors}")

