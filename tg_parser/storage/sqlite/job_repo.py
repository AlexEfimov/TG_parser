"""
SQLite implementation of JobRepo for persistent API job storage.

Phase 2F: Persistent Job Storage.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import Job, JobRepo, JobStatus, JobType

logger = logging.getLogger(__name__)


class SQLiteJobRepo(JobRepo):
    """
    SQLite implementation of job storage.
    
    Uses processing_storage.sqlite (api_jobs table).
    """

    def __init__(self, session_factory):
        """
        Initialize with session factory.
        
        Args:
            session_factory: Callable that returns AsyncSession
        """
        self._session_factory = session_factory

    def _job_to_row(self, job: Job) -> dict:
        """Convert Job to database row dict."""
        return {
            "job_id": job.job_id,
            "job_type": job.job_type.value,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "channel_id": job.channel_id,
            "client": job.client,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "progress_json": json.dumps(job.progress) if job.progress else None,
            "result_json": json.dumps(job.result) if job.result else None,
            "error": job.error,
            "file_path": job.file_path,
            "download_url": job.download_url,
            "export_format": job.export_format,
            "webhook_url": job.webhook_url,
            "webhook_secret": job.webhook_secret,
        }

    def _row_to_job(self, row) -> Job:
        """Convert database row to Job."""
        return Job(
            job_id=row.job_id,
            job_type=JobType(row.job_type),
            status=JobStatus(row.status),
            created_at=datetime.fromisoformat(row.created_at),
            channel_id=row.channel_id,
            client=row.client,
            started_at=datetime.fromisoformat(row.started_at) if row.started_at else None,
            completed_at=datetime.fromisoformat(row.completed_at) if row.completed_at else None,
            progress=json.loads(row.progress_json) if row.progress_json else {},
            result=json.loads(row.result_json) if row.result_json else None,
            error=row.error,
            file_path=row.file_path,
            download_url=row.download_url,
            export_format=row.export_format,
            webhook_url=row.webhook_url,
            webhook_secret=row.webhook_secret,
        )

    async def create(self, job: Job) -> None:
        """Create a new job."""
        row = self._job_to_row(job)
        
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO api_jobs (
                        job_id, job_type, status, created_at, channel_id, client,
                        started_at, completed_at, progress_json, result_json, error,
                        file_path, download_url, export_format, webhook_url, webhook_secret
                    ) VALUES (
                        :job_id, :job_type, :status, :created_at, :channel_id, :client,
                        :started_at, :completed_at, :progress_json, :result_json, :error,
                        :file_path, :download_url, :export_format, :webhook_url, :webhook_secret
                    )
                """),
                row,
            )
            await session.commit()
        
        logger.debug(f"Created job {job.job_id}")

    async def get(self, job_id: str) -> Job | None:
        """Get job by ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM api_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
            row = result.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_job(row)

    async def update(self, job: Job) -> None:
        """Update existing job."""
        row = self._job_to_row(job)
        
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    UPDATE api_jobs SET
                        status = :status,
                        started_at = :started_at,
                        completed_at = :completed_at,
                        progress_json = :progress_json,
                        result_json = :result_json,
                        error = :error,
                        file_path = :file_path,
                        download_url = :download_url
                    WHERE job_id = :job_id
                """),
                row,
            )
            await session.commit()
        
        logger.debug(f"Updated job {job.job_id} to status {job.status.value}")

    async def list_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """List jobs with optional filters."""
        query = "SELECT * FROM api_jobs WHERE 1=1"
        params: dict = {"limit": limit}
        
        if job_type is not None:
            query += " AND job_type = :job_type"
            params["job_type"] = job_type.value
        
        if status is not None:
            query += " AND status = :status"
            params["status"] = status.value
        
        query += " ORDER BY created_at DESC LIMIT :limit"
        
        async with self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [self._row_to_job(row) for row in rows]

    async def delete_old_jobs(self, older_than: datetime) -> int:
        """Delete jobs older than specified date."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    DELETE FROM api_jobs 
                    WHERE created_at < :older_than
                    AND status IN ('completed', 'failed')
                """),
                {"older_than": older_than.isoformat()},
            )
            await session.commit()
            
            deleted = result.rowcount
            if deleted > 0:
                logger.info(f"Deleted {deleted} old jobs")
            
            return deleted

