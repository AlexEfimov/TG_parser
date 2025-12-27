"""
Health check endpoints.
"""

from datetime import UTC, datetime

from fastapi import APIRouter

from tg_parser.api.schemas import HealthResponse, StatusResponse
from tg_parser.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Basic health check endpoint.
    
    Returns simple health status for load balancers and monitoring.
    """
    return HealthResponse(
        status="ok",
        version=settings.pipeline_version_processing,
        timestamp=datetime.now(UTC),
    )


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    """
    Detailed status endpoint.
    
    Returns component health and statistics.
    """
    # Check components
    components = {
        "api": "ok",
        "database": "ok",  # TODO: actual DB health check
        "llm": "ok",  # TODO: LLM connectivity check
    }
    
    # TODO: Add actual stats from database
    stats = {
        "raw_messages": 0,
        "processed_documents": 0,
        "topics": 0,
    }
    
    return StatusResponse(
        status="ok",
        version=settings.pipeline_version_processing,
        timestamp=datetime.now(UTC),
        components=components,
        stats=stats,
    )

