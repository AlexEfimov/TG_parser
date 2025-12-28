"""
Background task scheduler.

Phase 3D: APScheduler integration for periodic background tasks.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tg_parser.api.metrics import record_scheduler_task

logger = logging.getLogger(__name__)


class BackgroundScheduler:
    """
    Background task scheduler using APScheduler.
    
    Manages periodic tasks like:
    - Expired records cleanup
    - Health checks
    - Metrics aggregation
    """
    
    def __init__(self):
        """Initialize scheduler."""
        self._scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={
                "coalesce": True,  # Combine missed runs into one
                "max_instances": 1,  # Only one instance of each job
                "misfire_grace_time": 60,  # Allow 60s misfire grace period
            },
        )
        self._tasks: dict[str, Callable] = {}
        self._is_running = False
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running
    
    def add_task(
        self,
        task_id: str,
        func: Callable,
        interval_seconds: int,
        *,
        start_immediately: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Add a periodic task.
        
        Args:
            task_id: Unique task identifier
            func: Async function to execute
            interval_seconds: Interval between executions in seconds
            start_immediately: Whether to run task immediately on start
            **kwargs: Additional arguments to pass to the function
        """
        if task_id in self._tasks:
            logger.warning(f"Task {task_id} already exists, replacing")
            self.remove_task(task_id)
        
        # Wrap function to record metrics
        async def wrapped_func() -> None:
            start_time = datetime.now(UTC)
            try:
                await func(**kwargs)
                record_scheduler_task(task_id, success=True)
                duration = (datetime.now(UTC) - start_time).total_seconds()
                logger.debug(f"Task {task_id} completed in {duration:.2f}s")
            except Exception as e:
                record_scheduler_task(task_id, success=False)
                logger.exception(f"Task {task_id} failed: {e}")
        
        trigger = IntervalTrigger(seconds=interval_seconds)
        
        self._scheduler.add_job(
            wrapped_func,
            trigger=trigger,
            id=task_id,
            name=task_id,
            replace_existing=True,
        )
        
        self._tasks[task_id] = func
        logger.info(f"Added task {task_id} with interval {interval_seconds}s")
        
        # Run immediately if requested
        if start_immediately and self._is_running:
            self._scheduler.modify_job(task_id, next_run_time=datetime.now(UTC))
    
    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if task was removed, False if not found
        """
        if task_id not in self._tasks:
            return False
        
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass  # Job might not exist in scheduler
        
        del self._tasks[task_id]
        logger.info(f"Removed task {task_id}")
        return True
    
    def get_tasks(self) -> list[dict[str, Any]]:
        """
        Get list of scheduled tasks.
        
        Returns:
            List of task info dictionaries
        """
        tasks = []
        for job in self._scheduler.get_jobs():
            # next_run_time may not be available until scheduler is running
            try:
                next_run = job.next_run_time.isoformat() if job.next_run_time else None
            except AttributeError:
                next_run = None  # Job is pending, scheduler not started
            
            tasks.append({
                "id": job.id,
                "name": job.name,
                "pending": job.pending,
                "next_run": next_run,
                "trigger": str(job.trigger),
            })
        return tasks
    
    def start(self) -> None:
        """Start the scheduler."""
        if not self._is_running:
            self._scheduler.start()
            self._is_running = True
            logger.info("Background scheduler started")
    
    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the scheduler.
        
        Args:
            wait: Whether to wait for running tasks to complete
        """
        if self._is_running:
            self._scheduler.shutdown(wait=wait)
            self._is_running = False
            logger.info("Background scheduler stopped")


# Global scheduler instance
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Get global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


# ============================================================================
# Built-in Tasks
# ============================================================================


async def cleanup_expired_records(
    retention_days: int = 30,
    archive_path: str | None = None,
) -> dict[str, int]:
    """
    Cleanup expired task history and handoff records.
    
    Args:
        retention_days: Number of days to retain records
        archive_path: Optional path to archive expired records
        
    Returns:
        Dictionary with cleanup statistics
    """
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from tg_parser.agents.archiver import AgentHistoryArchiver
    from tg_parser.agents.persistence import AgentPersistence
    from tg_parser.config import settings
    from tg_parser.storage.sqlite.agent_state_repo import SQLiteAgentStateRepo
    from tg_parser.storage.sqlite.agent_stats_repo import SQLiteAgentStatsRepo
    from tg_parser.storage.sqlite.handoff_history_repo import SQLiteHandoffHistoryRepo
    from tg_parser.storage.sqlite.task_history_repo import SQLiteTaskHistoryRepo

    logger.info(f"Starting cleanup of records older than {retention_days} days")
    
    # Setup database connection
    db_url = f"sqlite+aiosqlite:///{settings.processing_storage_db_path}"
    engine = create_async_engine(db_url, echo=False)
    
    session_factory = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    persistence = AgentPersistence(
        agent_state_repo=SQLiteAgentStateRepo(session_factory),
        task_history_repo=SQLiteTaskHistoryRepo(session_factory),
        agent_stats_repo=SQLiteAgentStatsRepo(session_factory),
        handoff_history_repo=SQLiteHandoffHistoryRepo(session_factory),
        retention_days=retention_days,
        stats_enabled=True,
    )
    
    stats = {"task_records_deleted": 0, "handoff_records_deleted": 0, "archived": False}
    
    try:
        # Get expired records before deletion if archiving
        if archive_path:
            archiver = AgentHistoryArchiver(Path(archive_path))
            
            # Get expired task records
            expired_tasks = await persistence.get_expired_task_records()
            if expired_tasks:
                await archiver.archive_task_history(expired_tasks)
                stats["archived"] = True
            
            # Get expired handoff records  
            expired_handoffs = await persistence.get_expired_handoff_records()
            if expired_handoffs:
                await archiver.archive_handoff_history(expired_handoffs)
                stats["archived"] = True
        
        # Cleanup expired records
        task_count = await persistence.cleanup_expired_task_history()
        handoff_count = await persistence.cleanup_expired_handoff_history()
        
        stats["task_records_deleted"] = task_count
        stats["handoff_records_deleted"] = handoff_count
        
        logger.info(
            f"Cleanup complete: {task_count} task records, "
            f"{handoff_count} handoff records deleted"
        )
        
    finally:
        await engine.dispose()
    
    return stats


async def health_check_task() -> dict[str, str]:
    """
    Periodic health check task.
    
    Checks all components and logs warnings for unhealthy ones.
    
    Returns:
        Dictionary with component health status
    """
    from tg_parser.api.health_checks import check_all_components
    
    results = await check_all_components()
    
    # Log warnings for unhealthy components
    for component, status in results.items():
        if status != "ok":
            logger.warning(f"Health check: {component} is {status}")
    
    return results


def setup_default_tasks(
    scheduler: BackgroundScheduler,
    *,
    cleanup_interval_hours: int = 24,
    health_check_interval_minutes: int = 5,
    retention_days: int = 30,
    archive_path: str | None = None,
) -> None:
    """
    Setup default background tasks.
    
    Args:
        scheduler: Scheduler instance
        cleanup_interval_hours: Interval for cleanup task in hours
        health_check_interval_minutes: Interval for health checks in minutes
        retention_days: Retention period for records
        archive_path: Optional archive path for expired records
    """
    # Cleanup task
    scheduler.add_task(
        task_id="cleanup_expired_records",
        func=cleanup_expired_records,
        interval_seconds=cleanup_interval_hours * 3600,
        retention_days=retention_days,
        archive_path=archive_path,
    )
    
    # Health check task
    scheduler.add_task(
        task_id="health_check",
        func=health_check_task,
        interval_seconds=health_check_interval_minutes * 60,
    )
    
    logger.info("Default background tasks configured")

