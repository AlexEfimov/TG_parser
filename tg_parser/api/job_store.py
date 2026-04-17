"""
Job storage singleton for API routes.

Phase 2F: Persistent Job Storage.

Provides a single instance of job repository that can be used
across all API routes and background tasks.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.storage.ports import Job, JobRepo, JobStatus, JobType
from tg_parser.storage.sqlalchemy.job_repo import SAJobRepo

logger = structlog.get_logger(__name__)


class JobStore:
    """
    Singleton job storage manager.

    Manages database connection and provides job repository.
    """

    _instance: "JobStore | None" = None
    _initialized: bool = False

    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._repo: JobRepo | None = None

    @classmethod
    def get_instance(cls) -> "JobStore":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = JobStore()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
        cls._initialized = False

    async def init(self) -> None:
        """Initialize job storage, reusing the Database singleton's processing engine."""
        if self._initialized:
            return

        from tg_parser.storage.sqlalchemy import Database

        db = Database.get_instance()
        if not db._initialized:
            await db.init()

        self._engine = db.processing_storage_engine
        self._owns_engine = False

        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        await self._init_schema()

        self._repo = SAJobRepo(self._session_factory)

        self._initialized = True
        logger.info("Job storage initialized (shared processing engine)")

    async def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        # Extract just the api_jobs table DDL
        api_jobs_ddl = """
        CREATE TABLE IF NOT EXISTS api_jobs (
          job_id TEXT PRIMARY KEY,
          job_type TEXT NOT NULL CHECK(job_type IN ('processing', 'export')),
          status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
          created_at TEXT NOT NULL,
          channel_id TEXT,
          client TEXT,
          started_at TEXT,
          completed_at TEXT,
          progress_json TEXT,
          result_json TEXT,
          error TEXT,
          file_path TEXT,
          download_url TEXT,
          export_format TEXT,
          webhook_url TEXT,
          webhook_secret TEXT
        );

        CREATE INDEX IF NOT EXISTS api_jobs_status_idx ON api_jobs(status);
        CREATE INDEX IF NOT EXISTS api_jobs_created_at_idx ON api_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS api_jobs_job_type_idx ON api_jobs(job_type);
        """

        async with self._engine.begin() as conn:
            for statement in api_jobs_ddl.split(";"):
                statement = statement.strip()
                if statement:
                    await conn.execute(text(statement))

    async def close(self) -> None:
        """Close job storage (engine lifecycle is managed by Database singleton)."""
        if self._engine and getattr(self, "_owns_engine", True):
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        self._repo = None
        self._initialized = False
        logger.info("Job storage closed")

    @property
    def repo(self) -> JobRepo:
        """Get job repository."""
        if self._repo is None:
            raise RuntimeError("Job storage not initialized. Call await init() first.")
        return self._repo

    @property
    def is_initialized(self) -> bool:
        """Check if storage is initialized."""
        return self._initialized

    # Convenience methods that delegate to repo

    async def create_job(self, job: Job) -> None:
        """Create a new job."""
        await self.repo.create(job)

    async def get_job(self, job_id: str) -> Job | None:
        """Get job by ID."""
        return await self.repo.get(job_id)

    async def update_job(self, job: Job) -> None:
        """Update existing job."""
        await self.repo.update(job)

    async def list_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """List jobs with optional filters."""
        return await self.repo.list_jobs(job_type, status, limit)


# Global instance accessor
def get_job_store() -> JobStore:
    """Get the global job store instance."""
    return JobStore.get_instance()


async def ensure_job_store_initialized() -> JobStore:
    """
    Ensure job store is initialized and return it.

    Automatically initializes if not already done.
    Thread-safe for async context.
    """
    store = get_job_store()
    if not store.is_initialized:
        await store.init()
    return store


# FastAPI dependency
async def get_job_repo() -> JobRepo:
    """FastAPI dependency to get job repository."""
    store = await ensure_job_store_initialized()
    return store.repo

