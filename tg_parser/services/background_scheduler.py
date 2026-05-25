"""
Background task scheduler (moved from api/scheduler.py).

Phase 3D: APScheduler integration for periodic background tasks.
Lives in services/ to avoid circular dependency: services → api → services.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from apscheduler.job import Job

    from tg_parser.domain.models import DigestSubscription

logger = structlog.get_logger(__name__)


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
            logger.warning("Task %s already exists, replacing", task_id)
            self.remove_task(task_id)

        # Wrap function to record metrics
        async def wrapped_func() -> None:
            from tg_parser.api.metrics import record_scheduler_task

            start_time = datetime.now(UTC)
            try:
                await func(**kwargs)
                record_scheduler_task(task_id, success=True)
                duration = (datetime.now(UTC) - start_time).total_seconds()
                logger.debug("Task %s completed in %.2fs", task_id, duration)
            except Exception as e:
                record_scheduler_task(task_id, success=False)
                logger.exception("Task %s failed: %s", task_id, e)

        trigger = IntervalTrigger(seconds=interval_seconds)

        self._scheduler.add_job(
            wrapped_func,
            trigger=trigger,
            id=task_id,
            name=task_id,
            replace_existing=True,
        )

        self._tasks[task_id] = func
        logger.info("Added task %s with interval %ss", task_id, interval_seconds)

        # Run immediately if requested
        if start_immediately and self._is_running:
            self._scheduler.modify_job(task_id, next_run_time=datetime.now(UTC))

    def add_cron_task(
        self,
        task_id: str,
        func: Callable,
        cron_expression: str,
        *,
        timezone: str = "UTC",
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
    ) -> "Job":
        """Add a task driven by a 5-field cron expression.

        Wraps APScheduler's ``CronTrigger.from_crontab(...)`` and reuses the
        same metric-recording wrapper as ``add_task``. ``timezone`` must be a
        valid IANA name (validated via :class:`zoneinfo.ZoneInfo`); the call
        raises ``ValueError`` on bad input so callers (bot/MCP tools) can
        surface a clean error to the user instead of crashing the scheduler.

        Replaces an existing task with the same ``task_id`` (mirrors
        ``add_task`` semantics).
        """
        try:
            trigger = CronTrigger.from_crontab(cron_expression, timezone=ZoneInfo(timezone))
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(
                f"invalid cron task spec ({cron_expression!r} / tz={timezone!r}): {exc}"
            ) from exc

        if task_id in self._tasks:
            logger.debug("cron_task_replacing_existing", task_id=task_id)
            self.remove_task(task_id)

        call_args = args
        call_kwargs = dict(kwargs or {})

        async def wrapped_func() -> None:
            from tg_parser.api.metrics import record_scheduler_task

            start_time = datetime.now(UTC)
            try:
                await func(*call_args, **call_kwargs)
                record_scheduler_task(task_id, success=True)
                duration = (datetime.now(UTC) - start_time).total_seconds()
                logger.debug("cron_task_completed", task_id=task_id, duration=duration)
            except Exception as exc:  # noqa: BLE001
                record_scheduler_task(task_id, success=False)
                logger.exception("cron_task_failed", task_id=task_id, error=str(exc))

        job = self._scheduler.add_job(
            wrapped_func,
            trigger=trigger,
            id=task_id,
            name=task_id,
            replace_existing=True,
        )

        self._tasks[task_id] = func
        logger.info(
            "added_cron_task",
            task_id=task_id,
            cron_expression=cron_expression,
            timezone=timezone,
        )
        return job

    def remove_task(self, task_id: str, *, reason: str | None = None) -> bool:
        """Remove a task synchronously from APScheduler **and** the local
        bookkeeping dict.

        BUG-035 hardening: we now always attempt
        :meth:`AsyncIOScheduler.remove_job` even when ``task_id`` is missing
        from ``self._tasks``.  The two pieces of state can legitimately
        diverge — for example after a reconciliation loop tick removed the
        job but the caller still holds a stale id, or in a multi-process
        deployment where the in-memory dict tracks only registrations made
        in *this* process while the APScheduler instance may have been
        seeded from another path.  Always trying ``remove_job`` makes the
        helper genuinely idempotent.

        Args:
            task_id: Task identifier.
            reason: Optional short tag (e.g. ``"unsubscribe"`` /
                ``"reconcile"``) included in the structured log event so
                operators can correlate scheduler-state mutations with
                their trigger.

        Returns:
            ``True`` if the job was present in either the in-memory
            ``_tasks`` dict or the APScheduler job store (i.e. *something*
            was actually removed); ``False`` if the call was a complete
            no-op (job not tracked anywhere — race with reconcile, double
            unsubscribe, or unknown id).
        """
        had_tracked = task_id in self._tasks
        had_scheduled = False
        try:
            self._scheduler.remove_job(task_id)
            had_scheduled = True
        except JobLookupError:
            # APScheduler-native "job missing" — idempotent path; the
            # reconcile loop or a sibling tool may have removed it
            # already.  This is the expected branch in cross-process
            # MCP↔bot deployments where the in-memory ``_tasks`` dict
            # in the MCP process never held the job to begin with.
            pass

        self._tasks.pop(task_id, None)

        if had_tracked or had_scheduled:
            logger.info(
                "scheduler_job_removed",
                task_id=task_id,
                reason=reason or "unspecified",
                from_memory=had_tracked,
                from_scheduler=had_scheduled,
            )
            return True

        logger.debug(
            "scheduler_job_remove_noop",
            task_id=task_id,
            reason=reason or "unspecified",
        )
        return False

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

            tasks.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "pending": job.pending,
                    "next_run": next_run,
                    "trigger": str(job.trigger),
                }
            )
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

    from tg_parser.agents.archiver import AgentHistoryArchiver
    from tg_parser.services._wiring import get_agent_persistence

    logger.info("Starting cleanup of records older than %s days", retention_days)

    persistence = await get_agent_persistence()

    stats = {"task_records_deleted": 0, "handoff_records_deleted": 0, "archived": False}

    if archive_path:
        archiver = AgentHistoryArchiver(Path(archive_path))

        expired_tasks = await persistence.get_expired_task_records()
        if expired_tasks:
            await archiver.archive_task_history(expired_tasks)
            stats["archived"] = True

        expired_handoffs = await persistence.get_expired_handoff_records()
        if expired_handoffs:
            await archiver.archive_handoff_history(expired_handoffs)
            stats["archived"] = True

    task_count = await persistence.cleanup_expired_task_history()
    handoff_count = await persistence.cleanup_expired_handoff_history()

    stats["task_records_deleted"] = task_count
    stats["handoff_records_deleted"] = handoff_count

    logger.info(
        "Cleanup complete: %s task records, %s handoff records deleted",
        task_count,
        handoff_count,
    )

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
            logger.warning("Health check: %s is %s", component, status)

    return results


def setup_default_tasks(
    scheduler: BackgroundScheduler,
    *,
    cleanup_interval_hours: int = 24,
    health_check_interval_minutes: int = 5,
    retention_days: int = 30,
    archive_path: str | None = None,
    incremental_pipeline_interval: int | None = None,
) -> None:
    """
    Setup default background tasks.

    Args:
        scheduler: Scheduler instance
        cleanup_interval_hours: Interval for cleanup task in hours
        health_check_interval_minutes: Interval for health checks in minutes
        retention_days: Retention period for records
        archive_path: Optional archive path for expired records
        incremental_pipeline_interval: Override for incremental pipeline interval (seconds).
            Defaults to ``settings.scheduler_default_interval``.
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

    # Incremental pipeline task (Session 30)
    from tg_parser.config import settings as _settings
    from tg_parser.services.scheduler_service import incremental_pipeline_task

    interval = incremental_pipeline_interval or _settings.scheduler_default_interval
    scheduler.add_task(
        task_id="incremental_pipeline",
        func=incremental_pipeline_task,
        interval_seconds=interval,
    )

    # Incremental embedding task (P5 RAG) — runs after pipeline at same interval
    scheduler.add_task(
        task_id="incremental_embedding",
        func=_incremental_embedding_task,
        interval_seconds=interval,
    )

    # Idempotency-Key cleanup (Wave 1 step 3 commit 4/4, ADR 0009 Q-OPEN-2).
    # Hourly cron at the top of every hour: DELETE rows older than 24h +
    # update the ``tg_idempotency_keys_table_size`` gauge. Cron (vs interval)
    # is used so the deploy timestamp doesn't shift the cleanup phase
    # day-over-day — predictable cadence helps operators correlate
    # cleanup beats with cache-size dips on dashboards.
    from tg_parser.services.scheduler_service import cleanup_stale_idempotency_keys

    scheduler.add_cron_task(
        task_id="idempotency_keys_cleanup",
        func=cleanup_stale_idempotency_keys,
        cron_expression="0 * * * *",
        timezone="UTC",
    )

    logger.info(
        "Default background tasks configured (incl. incremental pipeline + embedding + idempotency cleanup, interval=%ds)",
        interval,
    )


# ============================================================================
# F6 — Scheduled Digests: subscription job lifecycle helpers
# ============================================================================


def _digest_job_id(subscription_id: str) -> str:
    """Stable per-subscription scheduler job id used for register/remove/diff."""
    return f"digest:{subscription_id}"


def register_digest_subscription(
    subscription: "DigestSubscription",
    scheduler: BackgroundScheduler | None = None,
) -> "Job | None":
    """Add (or replace) the cron job for ``subscription`` on the singleton scheduler.

    Returns the new ``Job`` on success and ``None`` if the subscription is
    inactive. Invalid cron expression / timezone propagate as ``ValueError`` so
    bot/MCP tools surface a clean error to the user.
    """
    if not subscription.is_active:
        logger.debug(
            "digest_skip_register_inactive",
            subscription_id=subscription.id,
        )
        return None

    sched = scheduler or get_scheduler()
    from tg_parser.services.scheduler_service import run_scheduled_digests_task

    return sched.add_cron_task(
        task_id=_digest_job_id(subscription.id),
        func=run_scheduled_digests_task,
        cron_expression=subscription.cron_expression,
        timezone=subscription.timezone,
        args=(subscription.id,),
    )


def unregister_digest_subscription(
    subscription_id: str,
    scheduler: BackgroundScheduler | None = None,
    *,
    reason: str = "unsubscribe",
) -> bool:
    """Remove the cron job for ``subscription_id`` if present. Idempotent.

    BUG-035 fix: ``reason`` is forwarded to :meth:`BackgroundScheduler.remove_task`
    so operators can distinguish call sites in the structured
    ``scheduler_job_removed`` log event (``mcp_unsubscribe_digest`` vs
    ``bot_unsubscribe_digest`` vs ``reconcile`` vs ``api_*``).  Defaults to
    the generic ``"unsubscribe"`` tag for backward-compatible call sites
    that do not yet pass a reason.
    """
    sched = scheduler or get_scheduler()
    return sched.remove_task(_digest_job_id(subscription_id), reason=reason)


def reschedule_digest_subscription(
    subscription: "DigestSubscription",
    scheduler: BackgroundScheduler | None = None,
) -> "Job | None":
    """Re-register a subscription job to pick up cron / timezone / activity changes.

    Inactive subscriptions are removed instead of re-registered.
    """
    sched = scheduler or get_scheduler()
    if not subscription.is_active:
        unregister_digest_subscription(subscription.id, sched)
        return None
    return register_digest_subscription(subscription, sched)


def get_registered_digest_subscription_ids(
    scheduler: BackgroundScheduler | None = None,
) -> set[str]:
    """Return the set of subscription IDs that currently have a scheduler job."""
    sched = scheduler or get_scheduler()
    prefix = "digest:"
    out: set[str] = set()
    for task_id in sched._tasks:  # noqa: SLF001 — minimal helper, no public iter
        if task_id.startswith(prefix):
            out.add(task_id[len(prefix) :])
    return out


async def _incremental_embedding_task() -> None:
    """Embed any processed documents that lack embeddings (all active sources)."""
    from tg_parser.services.db_context import ingestion_state_repo

    try:
        async with ingestion_state_repo() as (state_repo, _db):
            sources = await state_repo.list_sources(status="active")
    except Exception as exc:
        logger.warning("Failed to list active sources for embedding: %s", exc)
        return

    if not sources:
        return

    from tg_parser.services.embedding_service import run_embedding, run_topic_embedding

    for source in sources:
        try:
            stats = await run_embedding(channel_id=source.channel_id, force=False)
            if stats["embedded_count"] > 0:
                logger.info(
                    "Auto-embedded %d documents for %s",
                    stats["embedded_count"],
                    source.channel_id,
                )
        except Exception as exc:
            logger.warning("Auto-embedding failed for %s: %s", source.channel_id, exc)

        try:
            t_stats = await run_topic_embedding(channel_id=source.channel_id, force=False)
            if t_stats["embedded_count"] > 0:
                logger.info(
                    "Auto-embedded %d topic cards for %s",
                    t_stats["embedded_count"],
                    source.channel_id,
                )
        except Exception as exc:
            logger.warning("Topic auto-embedding failed for %s: %s", source.channel_id, exc)
