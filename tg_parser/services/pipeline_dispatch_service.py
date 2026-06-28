"""
One-shot pipeline job dispatch on the ``tg_parser`` container (ADR 0007 Option B).

MCP and Bot containers call ``POST /api/v1/pipeline/trigger`` which delegates
here. Telethon session ownership stays in this process.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

import structlog
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.services.db_context import ingestion_state_repo
from tg_parser.utils.channel_id import normalize_channel_id

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class PipelineJobKind(StrEnum):
    FULL_PIPELINE = "full_pipeline"
    TOPICIZATION = "topicization"
    LINK_TOPICS = "link_topics"


class PipelineDispatchError(Exception):
    """Base for dispatch preflight failures surfaced to HTTP/MCP callers."""

    def __init__(
        self,
        *,
        error_class: str,
        message: str,
        status_code: int = 400,
    ) -> None:
        self.error_class = error_class
        self.message = message
        self.status_code = status_code
        super().__init__(message)


_running_channel_jobs: set[str] = set()
_link_topics_running = False
_background_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class PipelineTriggerAccepted:
    job_id: str
    created: bool
    status: Literal["queued"] = "queued"


def is_channel_pipeline_busy(channel_id: str) -> bool:
    normalized = normalize_channel_id(channel_id) or channel_id
    return normalized in _running_channel_jobs


def is_link_topics_running() -> bool:
    return _link_topics_running


async def _resolve_active_source(channel_id: str):
    normalized = normalize_channel_id(channel_id) or channel_id
    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)
        if source is None:
            source = await state_repo.get_source_by_username(normalized)
        if source is None:
            raise PipelineDispatchError(
                error_class="SourceNotFound",
                message=f"Source '{normalized}' not found. Use add_channel first.",
                status_code=404,
            )
        if source.status != "active":
            raise PipelineDispatchError(
                error_class="SourceNotActive",
                message=(
                    f"Source '{normalized}' is '{source.status}'. "
                    "Use resume_channel to activate it first."
                ),
                status_code=409,
            )
        return normalized, source


async def trigger_pipeline_job(
    *,
    channel_id: str,
    job: PipelineJobKind | str,
    force: bool = False,
    surface: str = "api",
) -> PipelineTriggerAccepted:
    """Queue a one-shot pipeline job and return immediately."""
    kind = PipelineJobKind(job)
    normalized, _source = await _resolve_active_source(channel_id)

    global _link_topics_running

    if kind == PipelineJobKind.LINK_TOPICS:
        if _link_topics_running:
            raise PipelineDispatchError(
                error_class="JobAlreadyRunning",
                message="link_topics is already running on this server.",
                status_code=409,
            )
        _link_topics_running = True
        lock_key = "__link_topics__"
    else:
        if normalized in _running_channel_jobs:
            raise PipelineDispatchError(
                error_class="JobAlreadyRunning",
                message=f"Pipeline for '{normalized}' is already running.",
                status_code=409,
            )
        _running_channel_jobs.add(normalized)
        lock_key = normalized

    job_id = str(uuid.uuid4())
    task = asyncio.create_task(
        _run_pipeline_job_background(
            job_id=job_id,
            channel_id=normalized,
            job=kind,
            force=force,
            lock_key=lock_key,
            surface=surface,
        ),
        name=f"pipeline-trigger-{kind.value}-{normalized}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    from tg_parser.api.metrics import record_pipeline_trigger

    record_pipeline_trigger(job=kind.value, result="queued", surface=surface)
    logger.info(
        "pipeline_trigger_queued",
        job_id=job_id,
        channel_id=normalized,
        job=kind.value,
        surface=surface,
        force=force,
    )
    return PipelineTriggerAccepted(job_id=job_id, created=True)


async def _run_pipeline_job_background(
    *,
    job_id: str,
    channel_id: str,
    job: PipelineJobKind,
    force: bool,
    lock_key: str,
    surface: str,
) -> None:
    global _link_topics_running
    from tg_parser.api.metrics import record_pipeline_trigger

    output_dir = str(_PROJECT_ROOT / "output")
    try:
        if job == PipelineJobKind.FULL_PIPELINE:
            from tg_parser.services.embedding_service import run_embedding
            from tg_parser.services.pipeline_service import run_full_pipeline

            logger.warning(
                "pipeline_trigger_started",
                job_id=job_id,
                channel_id=channel_id,
                job=job.value,
                surface=surface,
            )
            pipeline_failed = False
            pipeline_skipped = False
            try:
                pipeline_stats = await run_full_pipeline(
                    source_id=channel_id,
                    mode="incremental",
                    force=force,
                    output_dir=output_dir,
                )
                # BUG-073 (F1): run_full_pipeline short-circuits with a benign
                # ``skipped_locked`` result when another run already owns the
                # per-channel lock (this dispatch job is itself a common F1
                # contender). Treat it as a DISTINCT benign outcome — not a
                # success, not a failure.
                pipeline_skipped = bool(pipeline_stats.get("skipped_locked"))
            except EOFError as exc:
                record_pipeline_trigger(job=job.value, result="telethon_reauth", surface=surface)
                logger.warning(
                    "pipeline_trigger_telethon_reauth",
                    job_id=job_id,
                    channel_id=channel_id,
                    error=str(exc),
                )
                return
            except RuntimeError:
                pipeline_failed = True
                logger.exception(
                    "pipeline_trigger_run_failed",
                    job_id=job_id,
                    channel_id=channel_id,
                )

            if pipeline_skipped:
                # Another run owns the channel end-to-end → skip embedding (no new
                # docs from this job) and record the skip distinctly. The finally
                # block still releases the in-process channel lock.
                record_pipeline_trigger(job=job.value, result="skipped", surface=surface)
                logger.warning(
                    "pipeline_trigger_skipped_lock_held",
                    job_id=job_id,
                    channel_id=channel_id,
                )
                return

            await run_embedding(channel_id=channel_id, force=False)
            result_label = "failed" if pipeline_failed else "success"
            record_pipeline_trigger(job=job.value, result=result_label, surface=surface)
            logger.warning(
                "pipeline_trigger_completed",
                job_id=job_id,
                channel_id=channel_id,
                pipeline_failed=pipeline_failed,
            )

        elif job == PipelineJobKind.TOPICIZATION:
            from tg_parser.services.topicization_service import run_topicization

            logger.warning(
                "pipeline_trigger_started",
                job_id=job_id,
                channel_id=channel_id,
                job=job.value,
                surface=surface,
            )
            await run_topicization(channel_id=channel_id, force=force)
            record_pipeline_trigger(job=job.value, result="success", surface=surface)
            logger.warning(
                "pipeline_trigger_completed",
                job_id=job_id,
                channel_id=channel_id,
                job=job.value,
            )

        elif job == PipelineJobKind.LINK_TOPICS:
            from tg_parser.services.topic_linking_service import link_topics as do_link

            logger.warning(
                "pipeline_trigger_started",
                job_id=job_id,
                job=job.value,
                surface=surface,
            )
            await do_link()
            record_pipeline_trigger(job=job.value, result="success", surface=surface)
            logger.warning("pipeline_trigger_completed", job_id=job_id, job=job.value)

    except (
        SQLAlchemyError,
        ConnectionError,
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        TypeError,
        KeyError,
    ):
        record_pipeline_trigger(job=job.value, result="error", surface=surface)
        logger.exception(
            "pipeline_trigger_failed",
            job_id=job_id,
            channel_id=channel_id,
            job=job.value,
        )
    finally:
        if lock_key == "__link_topics__":
            _link_topics_running = False
        else:
            _running_channel_jobs.discard(lock_key)


def telethon_reauth_workaround() -> str:
    return (
        "Telegram session needs interactive re-auth on the tg_parser container. "
        "Run: docker compose exec tg_parser tg-parser auth"
    )
