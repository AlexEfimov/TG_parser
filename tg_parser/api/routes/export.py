"""
Export endpoints with persistent job storage.

Phase 2F: Persistent Job Storage.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.job_store import ensure_job_store_initialized
from tg_parser.api.middleware import limiter
from tg_parser.api.schemas import (
    ErrorResponse,
    ExportFormat,
    ExportLevel,
    ExportRequest,
    ExportResponse,
)
from tg_parser.api.schemas import (
    JobStatus as APIJobStatus,
)
from tg_parser.api.webhooks import create_job_completion_payload, send_webhook
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import assert_channel_access
from tg_parser.config import settings
from tg_parser.services.export_job_access import (
    export_job_visible_to as _export_job_visible_to,
)
from tg_parser.services.export_job_access import (
    resolve_job_level as _resolve_job_level,
)
from tg_parser.services.export_service import run_export
from tg_parser.storage.ports import Job, JobStatus, JobType

router = APIRouter(prefix="/api/v1", tags=["Export"])
logger = structlog.get_logger(__name__)


def _job_status_to_api(status: JobStatus) -> APIJobStatus:
    """Convert storage JobStatus to API JobStatus."""
    return APIJobStatus(status.value)


def _resolve_export_file(*, output_dir: Path, level: ExportLevel, format: ExportFormat) -> Path:
    """Pick the export artefact path based on level + format (F2).

    - ``level=RAW``: ``raw_messages.{ndjson,json}``.
    - ``level=PROCESSED`` / ``level=FULL`` + ``format=NDJSON``: ``kb_entries.ndjson``.
    - ``level=FULL`` + ``format=JSON``: ``topics.json`` (legacy).
    """
    if level == ExportLevel.RAW:
        ext = "ndjson" if format == ExportFormat.NDJSON else "json"
        return output_dir / f"raw_messages.{ext}"

    if format == ExportFormat.NDJSON or level == ExportLevel.PROCESSED:
        return output_dir / "kb_entries.ndjson"

    return output_dir / "topics.json"


async def _run_export_job(job_id: str, request: ExportRequest) -> None:
    """
    Background task to run export.

    Sends webhook notification on completion if configured.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)

    if not job:
        logger.error("Export job %s not found", job_id)
        return

    try:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await job_store.update_job(job)

        logger.info(
            "Starting export job %s (level=%s, format=%s)",
            job_id,
            request.level.value,
            request.format.value,
        )

        # BUG-096: key the artefact by job_id so two exports of the same
        # level cannot overwrite each other. Path() is required — F2 tests
        # patch settings.output_dir as str.
        output_dir = Path(settings.output_dir) / job_id

        export_stats = await run_export(
            output_dir=str(output_dir),
            channel_id=request.channel_id,
            level=request.level,
            format=request.format,
            from_date=request.from_date,
            to_date=request.to_date,
        )
        logger.info("Export job %s stats: %s", job_id, export_stats)

        export_file = _resolve_export_file(
            output_dir=output_dir, level=request.level, format=request.format
        )

        if not export_file.exists():
            raise FileNotFoundError(
                f"Export produced no file: {export_file} (stats: {export_stats})"
            )

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.file_path = str(export_file)
        job.download_url = f"/api/v1/export/download/{job_id}"
        job.result = {
            "format": request.format.value,
            "level": request.level.value,
            "file_size": export_file.stat().st_size,
        }
        await job_store.update_job(job)

        logger.info("Completed export job %s", job_id)

        # Send webhook if configured
        if request.webhook_url:
            payload = create_job_completion_payload(
                job_id=job_id,
                job_type="export",
                status="completed",
                result={
                    "format": request.format.value,
                    "download_url": job.download_url,
                },
            )
            await send_webhook(
                url=request.webhook_url,
                payload=payload,
                secret=request.webhook_secret,
            )

    except (
        SQLAlchemyError,
        httpx.HTTPError,
        ConnectionError,
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        TypeError,
        KeyError,
    ) as e:
        logger.exception("Export job %s failed: %s", job_id, e)
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.error = str(e)
        await job_store.update_job(job)

        # Send failure webhook if configured
        if request.webhook_url:
            payload = create_job_completion_payload(
                job_id=job_id,
                job_type="export",
                status="failed",
                error=str(e),
            )
            await send_webhook(
                url=request.webhook_url,
                payload=payload,
                secret=request.webhook_secret,
            )


@router.post(
    "/export",
    response_model=ExportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "API key required"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@limiter.limit(settings.rate_limit_export)
async def start_export(
    request: Request,
    body: ExportRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(resolve_current_user),
) -> ExportResponse:
    """
    Start async export of processed data.

    Creates a background job and returns immediately with job_id.
    When complete, download_url will be available.

    **Authentication**: Required if API_KEY_REQUIRED=true
    **Rate Limit**: 20 requests per minute
    """
    if body.level == ExportLevel.RAW and not body.channel_id:
        raise HTTPException(
            status_code=400,
            detail="level='raw' requires channel_id",
        )
    if body.channel_id:
        await assert_channel_access(user, body.channel_id)
    job_store = await ensure_job_store_initialized()

    job_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)

    job = Job(
        job_id=job_id,
        job_type=JobType.EXPORT,
        status=JobStatus.PENDING,
        created_at=created_at,
        channel_id=body.channel_id,
        client=user.name,
        export_format=body.format.value,
        progress={"level": body.level.value},
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
    )
    await job_store.create_job(job)

    background_tasks.add_task(_run_export_job, job_id, body)

    logger.info(
        "Created export job %s",
        job_id,
        extra={
            "client": user.name,
            "format": body.format.value,
            "level": body.level.value,
        },
    )

    return ExportResponse(
        job_id=job_id,
        status=APIJobStatus.PENDING,
        format=body.format,
        level=body.level,
        created_at=created_at,
        download_url=None,
        message="Export job created. Check status for download URL.",
    )


@router.get(
    "/export/status/{job_id}",
    response_model=ExportResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_export_status(
    job_id: str, user: CurrentUser = Depends(resolve_current_user)
) -> ExportResponse:
    """
    Get status of an export job.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)

    if not job or not _export_job_visible_to(user, job):
        raise HTTPException(
            status_code=404,
            detail=f"Export job {job_id} not found",
        )

    # Parse export format from stored value
    export_format = ExportFormat(job.export_format) if job.export_format else ExportFormat.NDJSON
    export_level = _resolve_job_level(job)

    return ExportResponse(
        job_id=job.job_id,
        status=_job_status_to_api(job.status),
        format=export_format,
        level=export_level,
        created_at=job.created_at,
        download_url=job.download_url,
        message=job.error or f"Status: {job.status.value}",
    )


@router.get(
    "/export/download/{job_id}",
    responses={
        404: {"model": ErrorResponse, "description": "Job not found or not ready"},
    },
)
async def download_export(
    job_id: str, user: CurrentUser = Depends(resolve_current_user)
) -> FileResponse:
    """
    Download completed export file.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)

    # Owner check before COMPLETED: a foreign pending job must look like
    # unknown (404), not «exists but not ready» (400).
    if not job or not _export_job_visible_to(user, job):
        raise HTTPException(
            status_code=404,
            detail=f"Export job {job_id} not found",
        )

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Export job {job_id} not completed (status: {job.status.value})",
        )

    file_path = job.file_path
    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Export file not found",
        )

    # Determine media type / filename by (level, format). F2 adds raw_messages.*.
    export_format = ExportFormat(job.export_format) if job.export_format else ExportFormat.NDJSON
    export_level = _resolve_job_level(job)

    if export_level == ExportLevel.RAW:
        if export_format == ExportFormat.NDJSON:
            media_type = "application/x-ndjson"
            filename = "raw_messages.ndjson"
        else:
            media_type = "application/json"
            filename = "raw_messages.json"
    elif export_format == ExportFormat.NDJSON or export_level == ExportLevel.PROCESSED:
        media_type = "application/x-ndjson"
        filename = "kb_entries.ndjson"
    else:
        media_type = "application/json"
        filename = "topics.json"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )
