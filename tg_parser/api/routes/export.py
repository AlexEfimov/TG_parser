"""
Export endpoints with persistent job storage.

Phase 2F: Persistent Job Storage.
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from tg_parser.api.auth import verify_api_key
from tg_parser.api.job_store import ensure_job_store_initialized
from tg_parser.api.middleware import limiter
from tg_parser.api.schemas import (
    ErrorResponse,
    ExportFormat,
    ExportRequest,
    ExportResponse,
    JobStatus as APIJobStatus,
)
from tg_parser.api.webhooks import create_job_completion_payload, send_webhook
from tg_parser.config import settings
from tg_parser.storage.ports import Job, JobStatus, JobType

router = APIRouter(prefix="/api/v1", tags=["Export"])
logger = logging.getLogger(__name__)


def _job_status_to_api(status: JobStatus) -> APIJobStatus:
    """Convert storage JobStatus to API JobStatus."""
    return APIJobStatus(status.value)


async def _run_export_job(job_id: str, request: ExportRequest) -> None:
    """
    Background task to run export.
    
    Sends webhook notification on completion if configured.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)
    
    if not job:
        logger.error(f"Export job {job_id} not found")
        return
    
    try:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await job_store.update_job(job)
        
        logger.info(f"Starting export job {job_id}")
        
        # TODO: Implement actual export logic
        # For now, use existing output directory
        output_dir = Path(settings.output_dir)
        
        if request.format == ExportFormat.NDJSON:
            export_file = output_dir / "kb_entries.ndjson"
        else:
            export_file = output_dir / "topics.json"
        
        if not export_file.exists():
            raise FileNotFoundError(f"Export file not found: {export_file}")
        
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.file_path = str(export_file)
        job.download_url = f"/api/v1/export/download/{job_id}"
        job.result = {
            "format": request.format.value,
            "file_size": export_file.stat().st_size,
        }
        await job_store.update_job(job)
        
        logger.info(f"Completed export job {job_id}")
        
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
        
    except Exception as e:
        logger.exception(f"Export job {job_id} failed: {e}")
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
    client: str | None = Depends(verify_api_key),
) -> ExportResponse:
    """
    Start async export of processed data.
    
    Creates a background job and returns immediately with job_id.
    When complete, download_url will be available.
    
    **Authentication**: Required if API_KEY_REQUIRED=true
    **Rate Limit**: 20 requests per minute
    """
    job_store = await ensure_job_store_initialized()
    
    job_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    
    job = Job(
        job_id=job_id,
        job_type=JobType.EXPORT,
        status=JobStatus.PENDING,
        created_at=created_at,
        channel_id=body.channel_id,
        client=client,
        export_format=body.format.value,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
    )
    await job_store.create_job(job)
    
    background_tasks.add_task(_run_export_job, job_id, body)
    
    logger.info(
        f"Created export job {job_id}",
        extra={"client": client, "format": body.format.value},
    )
    
    return ExportResponse(
        job_id=job_id,
        status=APIJobStatus.PENDING,
        format=body.format,
        created_at=created_at,
        download_url=None,
        message=f"Export job created. Check status for download URL.",
    )


@router.get(
    "/export/status/{job_id}",
    response_model=ExportResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_export_status(job_id: str) -> ExportResponse:
    """
    Get status of an export job.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {job_id} not found",
        )
    
    # Parse export format from stored value
    export_format = ExportFormat(job.export_format) if job.export_format else ExportFormat.NDJSON
    
    return ExportResponse(
        job_id=job.job_id,
        status=_job_status_to_api(job.status),
        format=export_format,
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
async def download_export(job_id: str) -> FileResponse:
    """
    Download completed export file.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)
    
    if not job:
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
            detail=f"Export file not found",
        )
    
    # Determine media type
    export_format = ExportFormat(job.export_format) if job.export_format else ExportFormat.NDJSON
    
    if export_format == ExportFormat.NDJSON:
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
