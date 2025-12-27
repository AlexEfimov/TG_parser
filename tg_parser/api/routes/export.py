"""
Export endpoints.
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from tg_parser.api.schemas import (
    ErrorResponse,
    ExportFormat,
    ExportRequest,
    ExportResponse,
    JobStatus,
)
from tg_parser.config import settings

router = APIRouter(prefix="/api/v1", tags=["Export"])
logger = logging.getLogger(__name__)

# In-memory export job storage (for MVP)
_export_jobs: dict[str, dict[str, Any]] = {}


async def _run_export_job(job_id: str, request: ExportRequest) -> None:
    """
    Background task to run export.
    """
    job = _export_jobs.get(job_id)
    if not job:
        logger.error(f"Export job {job_id} not found")
        return
    
    try:
        job["status"] = JobStatus.RUNNING
        job["started_at"] = datetime.now(UTC)
        
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
        
        job["status"] = JobStatus.COMPLETED
        job["completed_at"] = datetime.now(UTC)
        job["file_path"] = str(export_file)
        job["download_url"] = f"/api/v1/export/download/{job_id}"
        
        logger.info(f"Completed export job {job_id}")
        
    except Exception as e:
        logger.exception(f"Export job {job_id} failed: {e}")
        job["status"] = JobStatus.FAILED
        job["completed_at"] = datetime.now(UTC)
        job["error"] = str(e)


@router.post(
    "/export",
    response_model=ExportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def start_export(
    request: ExportRequest,
    background_tasks: BackgroundTasks,
) -> ExportResponse:
    """
    Start async export of processed data.
    
    Creates a background job and returns immediately with job_id.
    When complete, download_url will be available.
    """
    job_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    
    job = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "format": request.format,
        "channel_id": request.channel_id,
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "file_path": None,
        "download_url": None,
        "error": None,
    }
    _export_jobs[job_id] = job
    
    background_tasks.add_task(_run_export_job, job_id, request)
    
    logger.info(f"Created export job {job_id}")
    
    return ExportResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        format=request.format,
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
    job = _export_jobs.get(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {job_id} not found",
        )
    
    return ExportResponse(
        job_id=job["job_id"],
        status=job["status"],
        format=job["format"],
        created_at=job["created_at"],
        download_url=job.get("download_url"),
        message=job.get("error") or f"Status: {job['status'].value}",
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
    job = _export_jobs.get(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job {job_id} not found",
        )
    
    if job["status"] != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Export job {job_id} not completed (status: {job['status'].value})",
        )
    
    file_path = job.get("file_path")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"Export file not found",
        )
    
    # Determine media type
    if job["format"] == ExportFormat.NDJSON:
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

