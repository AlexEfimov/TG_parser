"""
SQLite implementation of AgentStatsRepo for aggregated statistics.

Phase 3B: Agent State Persistence.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import AgentDailyStats, AgentStatsRepo

logger = logging.getLogger(__name__)


class SQLiteAgentStatsRepo(AgentStatsRepo):
    """
    SQLite implementation of agent statistics storage.
    
    Uses processing_storage.sqlite (agent_stats table).
    Stores aggregated daily statistics that persist even after task history cleanup.
    """

    def __init__(self, session_factory):
        """
        Initialize with session factory.
        
        Args:
            session_factory: Callable that returns AsyncSession
        """
        self._session_factory = session_factory

    def _row_to_stats(self, row) -> AgentDailyStats:
        """Convert database row to AgentDailyStats."""
        return AgentDailyStats(
            agent_name=row.agent_name,
            date=row.date,
            task_type=row.task_type,
            total_tasks=row.total_tasks,
            successful_tasks=row.successful_tasks,
            failed_tasks=row.failed_tasks,
            total_processing_time_ms=row.total_processing_time_ms,
            min_processing_time_ms=row.min_processing_time_ms,
            max_processing_time_ms=row.max_processing_time_ms,
        )

    async def record(
        self,
        agent_name: str,
        task_type: str,
        success: bool,
        processing_time_ms: int,
    ) -> None:
        """Record a task in daily statistics (upsert)."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        
        async with self._session_factory() as session:
            # Try to get existing record
            result = await session.execute(
                text("""
                    SELECT total_tasks, successful_tasks, failed_tasks,
                           total_processing_time_ms, min_processing_time_ms, max_processing_time_ms
                    FROM agent_stats 
                    WHERE agent_name = :agent_name AND date = :date AND task_type = :task_type
                """),
                {"agent_name": agent_name, "date": today, "task_type": task_type},
            )
            row = result.fetchone()
            
            if row is None:
                # Insert new record
                await session.execute(
                    text("""
                        INSERT INTO agent_stats (
                            agent_name, date, task_type,
                            total_tasks, successful_tasks, failed_tasks,
                            total_processing_time_ms, min_processing_time_ms, max_processing_time_ms
                        ) VALUES (
                            :agent_name, :date, :task_type,
                            1, :success, :failed,
                            :time, :time, :time
                        )
                    """),
                    {
                        "agent_name": agent_name,
                        "date": today,
                        "task_type": task_type,
                        "success": 1 if success else 0,
                        "failed": 0 if success else 1,
                        "time": processing_time_ms,
                    },
                )
            else:
                # Update existing record
                new_min = min(row.min_processing_time_ms or processing_time_ms, processing_time_ms)
                new_max = max(row.max_processing_time_ms or processing_time_ms, processing_time_ms)
                
                await session.execute(
                    text("""
                        UPDATE agent_stats SET
                            total_tasks = total_tasks + 1,
                            successful_tasks = successful_tasks + :success,
                            failed_tasks = failed_tasks + :failed,
                            total_processing_time_ms = total_processing_time_ms + :time,
                            min_processing_time_ms = :min_time,
                            max_processing_time_ms = :max_time
                        WHERE agent_name = :agent_name AND date = :date AND task_type = :task_type
                    """),
                    {
                        "agent_name": agent_name,
                        "date": today,
                        "task_type": task_type,
                        "success": 1 if success else 0,
                        "failed": 0 if success else 1,
                        "time": processing_time_ms,
                        "min_time": new_min,
                        "max_time": new_max,
                    },
                )
            
            await session.commit()
        
        logger.debug(f"Recorded stats for {agent_name}/{task_type} on {today}")

    async def get_daily(
        self,
        agent_name: str,
        date: str,
        task_type: str | None = None,
    ) -> list[AgentDailyStats]:
        """Get daily statistics for an agent."""
        query = "SELECT * FROM agent_stats WHERE agent_name = :agent_name AND date = :date"
        params: dict = {"agent_name": agent_name, "date": date}
        
        if task_type is not None:
            query += " AND task_type = :task_type"
            params["task_type"] = task_type
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_stats(row) for row in rows]

    async def get_range(
        self,
        agent_name: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[AgentDailyStats]:
        """Get statistics for a date range."""
        query = "SELECT * FROM agent_stats WHERE 1=1"
        params: dict = {}
        
        if agent_name is not None:
            query += " AND agent_name = :agent_name"
            params["agent_name"] = agent_name
        
        if from_date is not None:
            query += " AND date >= :from_date"
            params["from_date"] = from_date
        
        if to_date is not None:
            query += " AND date <= :to_date"
            params["to_date"] = to_date
        
        query += " ORDER BY date DESC, agent_name"
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_stats(row) for row in rows]

    async def get_summary(
        self,
        agent_name: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Get summary statistics for an agent.
        
        Returns aggregated stats over the specified number of days.
        """
        from_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT 
                        SUM(total_tasks) as total_tasks,
                        SUM(successful_tasks) as successful_tasks,
                        SUM(failed_tasks) as failed_tasks,
                        SUM(total_processing_time_ms) as total_time,
                        MIN(min_processing_time_ms) as min_time,
                        MAX(max_processing_time_ms) as max_time,
                        COUNT(DISTINCT date) as active_days,
                        COUNT(DISTINCT task_type) as task_types
                    FROM agent_stats 
                    WHERE agent_name = :agent_name AND date >= :from_date
                """),
                {"agent_name": agent_name, "from_date": from_date},
            )
            row = result.fetchone()
            
            if row is None or row.total_tasks is None:
                return {
                    "agent_name": agent_name,
                    "period_days": days,
                    "total_tasks": 0,
                    "successful_tasks": 0,
                    "failed_tasks": 0,
                    "success_rate": 0.0,
                    "avg_processing_time_ms": 0.0,
                    "min_processing_time_ms": None,
                    "max_processing_time_ms": None,
                    "active_days": 0,
                    "task_types": 0,
                }
            
            total_tasks = row.total_tasks or 0
            successful = row.successful_tasks or 0
            
            return {
                "agent_name": agent_name,
                "period_days": days,
                "total_tasks": total_tasks,
                "successful_tasks": successful,
                "failed_tasks": row.failed_tasks or 0,
                "success_rate": successful / total_tasks if total_tasks > 0 else 0.0,
                "avg_processing_time_ms": (row.total_time or 0) / total_tasks if total_tasks > 0 else 0.0,
                "min_processing_time_ms": row.min_time,
                "max_processing_time_ms": row.max_time,
                "active_days": row.active_days or 0,
                "task_types": row.task_types or 0,
            }

