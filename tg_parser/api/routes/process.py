"""
Processing endpoints with persistent job storage.

Phase 2F: Persistent Job Storage.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from tg_parser.api.auth import verify_api_key
from tg_parser.api.job_store import ensure_job_store_initialized
from tg_parser.api.middleware import limiter
from tg_parser.api.schemas import (
    ErrorResponse,
    JobStatus as APIJobStatus,
    JobStatusResponse,
    ProcessRequest,
    ProcessResponse,
)
from tg_parser.api.webhooks import create_job_completion_payload, send_webhook
from tg_parser.cli.process_cmd import run_processing
from tg_parser.config import settings
from tg_parser.storage.ports import Job, JobStatus, JobType

router = APIRouter(prefix="/api/v1", tags=["Processing"])
logger = logging.getLogger(__name__)


def _job_status_to_api(status: JobStatus) -> APIJobStatus:
    """Convert storage JobStatus to API JobStatus."""
    return APIJobStatus(status.value)


async def _run_processing_job(job_id: str, request: ProcessRequest) -> None:
    """
    Background task to run processing.
    
    Updates job status as processing progresses.
    Sends webhook notification on completion if configured.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)
    
    if not job:
        logger.error(f"Job {job_id} not found")
        return
    
    try:
        # Update status to running
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await job_store.update_job(job)
        
        logger.info(f"Starting processing job {job_id} for channel {request.channel_id}")
        
        # Run the actual processing
        result = await run_processing(
            channel_id=request.channel_id,
            force=request.force,
            retry_failed=request.retry_failed,
            provider=request.provider,
            model=request.model,
            concurrency=request.concurrency,
        )
        
        # Update job with results
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.result = result
        job.progress = {
            "processed": result.get("processed_count", 0),
            "skipped": result.get("skipped_count", 0),
            "failed": result.get("failed_count", 0),
            "total": result.get("total_count", 0),
        }
        await job_store.update_job(job)
        
        logger.info(f"Completed processing job {job_id}: {result}")
        
        # Send webhook if configured
        if request.webhook_url:
            payload = create_job_completion_payload(
                job_id=job_id,
                job_type="processing",
                status="completed",
                result=result,
            )
            await send_webhook(
                url=request.webhook_url,
                payload=payload,
                secret=request.webhook_secret,
            )
        
    except Exception as e:
        logger.exception(f"Processing job {job_id} failed: {e}")
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.error = str(e)
        await job_store.update_job(job)
        
        # Send failure webhook if configured
        if request.webhook_url:
            payload = create_job_completion_payload(
                job_id=job_id,
                job_type="processing",
                status="failed",
                error=str(e),
            )
            await send_webhook(
                url=request.webhook_url,
                payload=payload,
                secret=request.webhook_secret,
            )


@router.post(
    "/process",
    response_model=ProcessResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "API key required"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
@limiter.limit(settings.rate_limit_process)
async def start_processing(
    request: Request,
    body: ProcessRequest,
    background_tasks: BackgroundTasks,
    client: str | None = Depends(verify_api_key),
) -> ProcessResponse:
    """
    Start async processing of messages from a channel.
    
    Creates a background job and returns immediately with job_id.
    Use GET /api/v1/status/{job_id} to check progress.
    
    **Authentication**: Required if API_KEY_REQUIRED=true
    **Rate Limit**: 10 requests per minute
    """
    job_store = await ensure_job_store_initialized()
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    
    # Create job record
    job = Job(
        job_id=job_id,
        job_type=JobType.PROCESSING,
        status=JobStatus.PENDING,
        created_at=created_at,
        channel_id=body.channel_id,
        client=client,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
    )
    await job_store.create_job(job)
    
    # Schedule background processing
    background_tasks.add_task(_run_processing_job, job_id, body)
    
    logger.info(
        f"Created processing job {job_id} for channel {body.channel_id}",
        extra={"client": client, "channel_id": body.channel_id},
    )
    
    return ProcessResponse(
        job_id=job_id,
        status=APIJobStatus.PENDING,
        channel_id=body.channel_id,
        created_at=created_at,
        message=f"Processing job created. Use GET /api/v1/status/{job_id} to check progress.",
    )


@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Get status of a processing job.
    
    Returns current status, progress, and result when completed.
    """
    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found",
        )
    
    return JobStatusResponse(
        job_id=job.job_id,
        status=_job_status_to_api(job.status),
        channel_id=job.channel_id or "",
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=job.progress,
        error=job.error,
        result=job.result,
    )


@router.get(
    "/jobs",
    response_model=list[JobStatusResponse],
)
async def list_jobs(
    status: APIJobStatus | None = None,
    limit: int = 50,
) -> list[JobStatusResponse]:
    """
    List processing jobs.
    
    Optionally filter by status. Returns most recent first.
    """
    job_store = await ensure_job_store_initialized()
    
    # Convert API status to storage status
    storage_status = JobStatus(status.value) if status else None
    
    jobs = await job_store.list_jobs(
        job_type=JobType.PROCESSING,
        status=storage_status,
        limit=limit,
    )
    
    return [
        JobStatusResponse(
            job_id=job.job_id,
            status=_job_status_to_api(job.status),
            channel_id=job.channel_id or "",
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            progress=job.progress,
            error=job.error,
            result=job.result,
        )
        for job in jobs
    ]
