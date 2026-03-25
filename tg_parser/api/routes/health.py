"""
Health check endpoints.

Phase 3D: Enhanced health checks with component-level details.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

from tg_parser.api.health_checks import check_all_components, get_detailed_health
from tg_parser.api.schemas import HealthResponse, StatusResponse
from tg_parser.api.scheduler import get_scheduler
from tg_parser.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Basic health check endpoint.
    
    Returns simple health status for load balancers and monitoring.
    This is a lightweight check that always returns quickly.
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
    This performs actual health checks on all components.
    """
    # Check all components
    components = await check_all_components()
    
    # Determine overall status
    statuses = list(components.values())
    if "error" in statuses:
        overall_status = "degraded"
    elif "warning" in statuses:
        overall_status = "warning"
    else:
        overall_status = "ok"
    
    # Get basic stats from database
    stats = await _get_basic_stats()
    
    return StatusResponse(
        status=overall_status,
        version=settings.pipeline_version_processing,
        timestamp=datetime.now(UTC),
        components=components,
        stats=stats,
    )


@router.get("/status/detailed")
async def detailed_status() -> dict[str, Any]:
    """
    Detailed status with component-level health information.
    
    Returns comprehensive health information including:
    - Database connectivity and latency
    - LLM provider status
    - Agent registry status
    - Background scheduler status
    """
    detailed = await get_detailed_health()
    
    # Determine overall status
    statuses = [c["status"] for c in detailed.values()]
    if "error" in statuses:
        overall_status = "degraded"
    elif "warning" in statuses:
        overall_status = "warning"
    else:
        overall_status = "ok"
    
    return {
        "status": overall_status,
        "version": settings.pipeline_version_processing,
        "timestamp": datetime.now(UTC).isoformat(),
        "components": detailed,
    }


@router.get("/scheduler")
async def scheduler_status() -> dict[str, Any]:
    """
    Get background scheduler status and scheduled tasks.
    
    Returns:
        Scheduler status and list of scheduled tasks
    """
    scheduler = get_scheduler()
    
    return {
        "running": scheduler.is_running,
        "tasks": scheduler.get_tasks(),
        "enabled": settings.scheduler_enabled,
    }


async def _get_basic_stats() -> dict[str, int]:
    """
    Get basic statistics from database.
    
    Returns:
        Dictionary with basic stats
    """
    from sqlalchemy import text

    from tg_parser.storage.engine_factory import create_engine_from_settings

    stats = {
        "raw_messages": 0,
        "processed_documents": 0,
        "topics": 0,
    }
    
    try:
        # Check raw storage
        engine = create_engine_from_settings(settings, "raw", echo=False)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT COUNT(*) FROM raw_messages")
                )
                stats["raw_messages"] = result.scalar() or 0
        except Exception as e:
            logger.debug("Failed to query raw_messages: %s", e)
        finally:
            await engine.dispose()
        
        # Check processing storage
        engine = create_engine_from_settings(settings, "processing", echo=False)
        try:
            async with engine.connect() as conn:
                try:
                    result = await conn.execute(
                        text("SELECT COUNT(*) FROM processed_documents")
                    )
                    stats["processed_documents"] = result.scalar() or 0
                except Exception as e:
                    logger.debug("Failed to query processed_documents: %s", e)
                
                try:
                    result = await conn.execute(
                        text("SELECT COUNT(*) FROM topics")
                    )
                    stats["topics"] = result.scalar() or 0
                except Exception as e:
                    logger.debug("Failed to query topics: %s", e)
        except Exception as e:
            logger.debug("Failed to connect to processing storage: %s", e)
        finally:
            await engine.dispose()
                
    except Exception as e:
        logger.debug("Failed to gather basic stats: %s", e)
    
    return stats
