"""
SQLite implementation of HandoffHistoryRepo for handoff tracking.

Phase 3B: Agent State Persistence.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import HandoffHistoryRepo, HandoffRecord

logger = logging.getLogger(__name__)


class SQLiteHandoffHistoryRepo(HandoffHistoryRepo):
    """
    SQLite implementation of handoff history storage.
    
    Uses processing_storage.sqlite (handoff_history table).
    """

    def __init__(self, session_factory):
        """
        Initialize with session factory.
        
        Args:
            session_factory: Callable that returns AsyncSession
        """
        self._session_factory = session_factory

    def _row_to_record(self, row) -> HandoffRecord:
        """Convert database row to HandoffRecord."""
        return HandoffRecord(
            id=row.id,
            source_agent=row.source_agent,
            target_agent=row.target_agent,
            task_type=row.task_type,
            status=row.status,
            priority=row.priority,
            payload=json.loads(row.payload_json) if row.payload_json else {},
            context=json.loads(row.context_json) if row.context_json else {},
            result=json.loads(row.result_json) if row.result_json else {},
            error=row.error,
            processing_time_ms=row.processing_time_ms,
            created_at=datetime.fromisoformat(row.created_at),
            accepted_at=datetime.fromisoformat(row.accepted_at) if row.accepted_at else None,
            completed_at=datetime.fromisoformat(row.completed_at) if row.completed_at else None,
        )

    async def record(
        self,
        source_agent: str,
        target_agent: str,
        task_type: str,
        handoff_id: str,
        priority: int = 5,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a new handoff request."""
        now = datetime.now(UTC).isoformat()
        
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO handoff_history (
                        id, source_agent, target_agent, task_type, priority,
                        status, payload_json, context_json, created_at
                    ) VALUES (
                        :id, :source_agent, :target_agent, :task_type, :priority,
                        'pending', :payload_json, :context_json, :created_at
                    )
                """),
                {
                    "id": handoff_id,
                    "source_agent": source_agent,
                    "target_agent": target_agent,
                    "task_type": task_type,
                    "priority": priority,
                    "payload_json": json.dumps(payload) if payload else None,
                    "context_json": json.dumps(context) if context else None,
                    "created_at": now,
                },
            )
            await session.commit()
        
        logger.debug(f"Recorded handoff {handoff_id}: {source_agent} -> {target_agent}")

    async def update_status(
        self,
        handoff_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        processing_time_ms: int | None = None,
    ) -> None:
        """Update handoff status and result."""
        now = datetime.now(UTC).isoformat()
        
        # Determine which timestamp to update based on status
        accepted_at_update = ""
        completed_at_update = ""
        
        if status == "accepted":
            accepted_at_update = ", accepted_at = :now"
        elif status in ("completed", "failed", "rejected"):
            completed_at_update = ", completed_at = :now"
        
        async with self._session_factory() as session:
            await session.execute(
                text(f"""
                    UPDATE handoff_history SET
                        status = :status,
                        result_json = :result_json,
                        error = :error,
                        processing_time_ms = :processing_time_ms
                        {accepted_at_update}
                        {completed_at_update}
                    WHERE id = :id
                """),
                {
                    "id": handoff_id,
                    "status": status,
                    "result_json": json.dumps(result) if result else None,
                    "error": error,
                    "processing_time_ms": processing_time_ms,
                    "now": now,
                },
            )
            await session.commit()
        
        logger.debug(f"Updated handoff {handoff_id} status to {status}")

    async def get(self, handoff_id: str) -> HandoffRecord | None:
        """Get handoff record by ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM handoff_history WHERE id = :id"),
                {"id": handoff_id},
            )
            row = result.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_record(row)

    async def list_by_agent(
        self,
        agent_name: str,
        as_source: bool = True,
        status: str | None = None,
        limit: int = 100,
    ) -> list[HandoffRecord]:
        """List handoffs for an agent (as source or target)."""
        column = "source_agent" if as_source else "target_agent"
        query = f"SELECT * FROM handoff_history WHERE {column} = :agent_name"
        params: dict = {"agent_name": agent_name, "limit": limit}
        
        if status is not None:
            query += " AND status = :status"
            params["status"] = status
        
        query += " ORDER BY created_at DESC LIMIT :limit"
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_record(row) for row in rows]

    async def get_statistics(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Get handoff statistics."""
        query = """
            SELECT 
                COUNT(*) as total_handoffs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status IN ('pending', 'accepted', 'in_progress') THEN 1 ELSE 0 END) as in_progress,
                AVG(processing_time_ms) as avg_processing_time_ms,
                MIN(processing_time_ms) as min_processing_time_ms,
                MAX(processing_time_ms) as max_processing_time_ms
            FROM handoff_history 
            WHERE 1=1
        """
        params: dict = {}
        
        if from_date is not None:
            query += " AND created_at >= :from_date"
            params["from_date"] = from_date.isoformat()
        
        if to_date is not None:
            query += " AND created_at <= :to_date"
            params["to_date"] = to_date.isoformat()
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            row = result.fetchone()
            
            if row is None or row.total_handoffs == 0:
                return {
                    "total_handoffs": 0,
                    "completed": 0,
                    "failed": 0,
                    "rejected": 0,
                    "in_progress": 0,
                    "success_rate": 0.0,
                    "avg_processing_time_ms": 0.0,
                    "min_processing_time_ms": None,
                    "max_processing_time_ms": None,
                }
            
            total = row.total_handoffs
            completed = row.completed or 0
            
            # Get agent pair statistics
            pair_result = await session.execute(
                text("""
                    SELECT source_agent, target_agent, COUNT(*) as count
                    FROM handoff_history
                    WHERE 1=1
                    """ + (" AND created_at >= :from_date" if from_date else "") +
                    (" AND created_at <= :to_date" if to_date else "") + """
                    GROUP BY source_agent, target_agent
                    ORDER BY count DESC
                    LIMIT 10
                """),
                params,
            )
            top_pairs = [
                {"source": r.source_agent, "target": r.target_agent, "count": r.count}
                for r in pair_result.fetchall()
            ]
            
            return {
                "total_handoffs": total,
                "completed": completed,
                "failed": row.failed or 0,
                "rejected": row.rejected or 0,
                "in_progress": row.in_progress or 0,
                "success_rate": completed / total if total > 0 else 0.0,
                "avg_processing_time_ms": row.avg_processing_time_ms or 0.0,
                "min_processing_time_ms": row.min_processing_time_ms,
                "max_processing_time_ms": row.max_processing_time_ms,
                "top_agent_pairs": top_pairs,
            }

    async def list_expired(
        self,
        retention_days: int = 30,
        limit: int = 1000,
    ) -> list[HandoffRecord]:
        """
        Get expired handoff records for archiving before deletion.
        
        Args:
            retention_days: Records older than this are considered expired
            limit: Maximum number of records to return
            
        Returns:
            List of expired HandoffRecord objects
        """
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM handoff_history 
                    WHERE created_at < :cutoff
                    ORDER BY created_at ASC
                    LIMIT :limit
                """),
                {"cutoff": cutoff, "limit": limit},
            )
            rows = result.fetchall()
            
            return [self._row_to_record(row) for row in rows]

    async def cleanup_expired(
        self,
        retention_days: int = 30,
    ) -> int:
        """
        Delete expired handoff records.
        
        Args:
            retention_days: Records older than this will be deleted
            
        Returns:
            Number of deleted records
        """
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    DELETE FROM handoff_history 
                    WHERE created_at < :cutoff
                """),
                {"cutoff": cutoff},
            )
            await session.commit()
            
            deleted = result.rowcount
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired handoff history records")
            
            return deleted

