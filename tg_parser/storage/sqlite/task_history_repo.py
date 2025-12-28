"""
SQLite implementation of TaskHistoryRepo for task execution history.

Phase 3B: Agent State Persistence.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import TaskHistoryRepo, TaskRecord

logger = logging.getLogger(__name__)


class SQLiteTaskHistoryRepo(TaskHistoryRepo):
    """
    SQLite implementation of task history storage.
    
    Uses processing_storage.sqlite (task_history table).
    """

    def __init__(self, session_factory, default_retention_days: int = 14):
        """
        Initialize with session factory.
        
        Args:
            session_factory: Callable that returns AsyncSession
            default_retention_days: Default retention period for task records
        """
        self._session_factory = session_factory
        self._default_retention_days = default_retention_days

    def _record_to_row(self, record: TaskRecord) -> dict:
        """Convert TaskRecord to database row dict."""
        return {
            "id": record.id,
            "agent_name": record.agent_name,
            "task_type": record.task_type,
            "source_ref": record.source_ref,
            "channel_id": record.channel_id,
            "input_json": json.dumps(record.input_data),
            "output_json": json.dumps(record.output_data) if record.output_data else None,
            "success": 1 if record.success else 0,
            "error": record.error,
            "processing_time_ms": record.processing_time_ms,
            "created_at": record.created_at.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        }

    def _row_to_record(self, row) -> TaskRecord:
        """Convert database row to TaskRecord."""
        return TaskRecord(
            id=row.id,
            agent_name=row.agent_name,
            task_type=row.task_type,
            input_data=json.loads(row.input_json) if row.input_json else {},
            output_data=json.loads(row.output_json) if row.output_json else None,
            source_ref=row.source_ref,
            channel_id=row.channel_id,
            success=bool(row.success),
            error=row.error,
            processing_time_ms=row.processing_time_ms,
            created_at=datetime.fromisoformat(row.created_at),
            expires_at=datetime.fromisoformat(row.expires_at) if row.expires_at else None,
        )

    async def record(
        self,
        agent_name: str,
        task_type: str,
        input_data: dict,
        output_data: dict | None = None,
        success: bool = True,
        error: str | None = None,
        processing_time_ms: int | None = None,
        source_ref: str | None = None,
        channel_id: str | None = None,
        retention_days: int | None = None,
    ) -> str:
        """
        Record a task execution.
        
        Returns: Task ID
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        
        retention = retention_days or self._default_retention_days
        expires_at = now + timedelta(days=retention)
        
        record = TaskRecord(
            id=task_id,
            agent_name=agent_name,
            task_type=task_type,
            input_data=input_data,
            output_data=output_data,
            source_ref=source_ref,
            channel_id=channel_id,
            success=success,
            error=error,
            processing_time_ms=processing_time_ms,
            created_at=now,
            expires_at=expires_at,
        )
        
        row = self._record_to_row(record)
        
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO task_history (
                        id, agent_name, task_type, source_ref, channel_id,
                        input_json, output_json, success, error, processing_time_ms,
                        created_at, expires_at
                    ) VALUES (
                        :id, :agent_name, :task_type, :source_ref, :channel_id,
                        :input_json, :output_json, :success, :error, :processing_time_ms,
                        :created_at, :expires_at
                    )
                """),
                row,
            )
            await session.commit()
        
        logger.debug(f"Recorded task {task_id} for agent {agent_name}")
        return task_id

    async def get(self, task_id: str) -> TaskRecord | None:
        """Get task record by ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM task_history WHERE id = :id"),
                {"id": task_id},
            )
            row = result.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_record(row)

    async def list_by_agent(
        self,
        agent_name: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        """List task records for an agent."""
        query = "SELECT * FROM task_history WHERE agent_name = :agent_name"
        params: dict = {"agent_name": agent_name, "limit": limit}
        
        if from_date is not None:
            query += " AND created_at >= :from_date"
            params["from_date"] = from_date.isoformat()
        
        if to_date is not None:
            query += " AND created_at <= :to_date"
            params["to_date"] = to_date.isoformat()
        
        query += " ORDER BY created_at DESC LIMIT :limit"
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_record(row) for row in rows]

    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        """List task records for a channel."""
        query = "SELECT * FROM task_history WHERE channel_id = :channel_id"
        params: dict = {"channel_id": channel_id, "limit": limit}
        
        if from_date is not None:
            query += " AND created_at >= :from_date"
            params["from_date"] = from_date.isoformat()
        
        if to_date is not None:
            query += " AND created_at <= :to_date"
            params["to_date"] = to_date.isoformat()
        
        query += " ORDER BY created_at DESC LIMIT :limit"
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_record(row) for row in rows]

    async def cleanup_expired(self) -> int:
        """
        Delete expired records.
        
        Returns: Number of deleted records
        """
        now = datetime.now(UTC).isoformat()
        
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    DELETE FROM task_history 
                    WHERE expires_at IS NOT NULL AND expires_at < :now
                """),
                {"now": now},
            )
            await session.commit()
            
            deleted = result.rowcount
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired task history records")
            
            return deleted

    async def get_expired_for_archive(
        self,
        limit: int = 1000,
    ) -> list[TaskRecord]:
        """Get expired records for archiving before deletion."""
        now = datetime.now(UTC).isoformat()
        
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM task_history 
                    WHERE expires_at IS NOT NULL AND expires_at < :now
                    ORDER BY expires_at ASC
                    LIMIT :limit
                """),
                {"now": now, "limit": limit},
            )
            rows = result.fetchall()
            
            return [self._row_to_record(row) for row in rows]

    async def list_expired(self, limit: int = 1000) -> list[TaskRecord]:
        """Alias for get_expired_for_archive for consistency."""
        return await self.get_expired_for_archive(limit=limit)

