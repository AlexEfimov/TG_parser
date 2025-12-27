"""
Processing endpoints.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from tg_parser.api.schemas import (
    ErrorResponse,
    JobStatus,
    JobStatusResponse,
    ProcessRequest,
    ProcessResponse,
)
from tg_parser.cli.process_cmd import run_processing

router = APIRouter(prefix="/api/v1", tags=["Processing"])
logger = logging.getLogger(__name__)

# In-memory job storage (for MVP; replace with Redis/DB in production)
_jobs: dict[str, dict[str, Any]] = {}


async def _run_processing_job(job_id: str, request: ProcessRequest) -> None:
    """
    Background task to run processing.
    
    Updates job status as processing progresses.
    """
    job = _jobs.get(job_id)
    if not job:
        logger.error(f"Job {job_id} not found")
        return
    
    try:
        # Update status to running
        job["status"] = JobStatus.RUNNING
        job["started_at"] = datetime.now(UTC)
        
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
        job["status"] = JobStatus.COMPLETED
        job["completed_at"] = datetime.now(UTC)
        job["result"] = result
        job["progress"] = {
            "processed": result.get("processed_count", 0),
            "skipped": result.get("skipped_count", 0),
            "failed": result.get("failed_count", 0),
            "total": result.get("total_count", 0),
        }
        
        logger.info(f"Completed processing job {job_id}: {result}")
        
    except Exception as e:
        logger.exception(f"Processing job {job_id} failed: {e}")
        job["status"] = JobStatus.FAILED
        job["completed_at"] = datetime.now(UTC)
        job["error"] = str(e)


@router.post(
    "/process",
    response_model=ProcessResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def start_processing(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
) -> ProcessResponse:
    """
    Start async processing of messages from a channel.
    
    Creates a background job and returns immediately with job_id.
    Use GET /api/v1/status/{job_id} to check progress.
    """
    # Generate job ID
    job_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    
    # Create job record
    job = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "channel_id": request.channel_id,
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "progress": {},
        "error": None,
        "result": None,
    }
    _jobs[job_id] = job
    
    # Schedule background processing
    background_tasks.add_task(_run_processing_job, job_id, request)
    
    logger.info(f"Created processing job {job_id} for channel {request.channel_id}")
    
    return ProcessResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        channel_id=request.channel_id,
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
    job = _jobs.get(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found",
        )
    
    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        channel_id=job["channel_id"],
        created_at=job["created_at"],
        started_at=job["started_at"],
        completed_at=job["completed_at"],
        progress=job.get("progress", {}),
        error=job.get("error"),
        result=job.get("result"),
    )


@router.get(
    "/jobs",
    response_model=list[JobStatusResponse],
)
async def list_jobs(
    status: JobStatus | None = None,
    limit: int = 50,
) -> list[JobStatusResponse]:
    """
    List processing jobs.
    
    Optionally filter by status. Returns most recent first.
    """
    jobs = list(_jobs.values())
    
    # Filter by status if provided
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    
    # Sort by created_at descending
    jobs.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Apply limit
    jobs = jobs[:limit]
    
    return [
        JobStatusResponse(
            job_id=j["job_id"],
            status=j["status"],
            channel_id=j["channel_id"],
            created_at=j["created_at"],
            started_at=j["started_at"],
            completed_at=j["completed_at"],
            progress=j.get("progress", {}),
            error=j.get("error"),
            result=j.get("result"),
        )
        for j in jobs
    ]

