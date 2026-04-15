"""
Agent observability API endpoints.

Phase 3C: Agent monitoring and statistics endpoints.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from tg_parser.api.auth import resolve_current_user
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import assert_admin
from tg_parser.services._wiring import get_agent_persistence

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])


# ============================================================================
# Schemas
# ============================================================================


class AgentInfo(BaseModel):
    """Agent information."""
    
    name: str = Field(description="Agent name")
    agent_type: str = Field(description="Agent type")
    version: str = Field(description="Agent version")
    description: str = Field(description="Agent description")
    capabilities: list[str] = Field(description="Agent capabilities")
    model: str | None = Field(description="LLM model")
    provider: str | None = Field(description="LLM provider")
    is_active: bool = Field(description="Whether agent is active")
    
    # Statistics
    total_tasks_processed: int = Field(description="Total tasks processed")
    total_errors: int = Field(description="Total errors")
    avg_processing_time_ms: float = Field(description="Average processing time in ms")
    last_used_at: datetime | None = Field(description="Last used timestamp")
    
    # Timestamps
    created_at: datetime = Field(description="Created timestamp")
    updated_at: datetime = Field(description="Updated timestamp")


class AgentListResponse(BaseModel):
    """Response for agent list."""
    
    agents: list[AgentInfo] = Field(description="List of agents")
    total: int = Field(description="Total number of agents")


class AgentStatsResponse(BaseModel):
    """Response for agent statistics."""
    
    agent_name: str = Field(description="Agent name")
    period_days: int = Field(description="Statistics period in days")
    
    # Summary statistics
    total_tasks: int = Field(description="Total tasks in period")
    successful_tasks: int = Field(description="Successful tasks")
    failed_tasks: int = Field(description="Failed tasks")
    success_rate: float = Field(description="Success rate (0-1)")
    avg_processing_time_ms: float = Field(description="Average processing time")
    
    # By task type
    by_task_type: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Statistics by task type"
    )


class TaskRecordInfo(BaseModel):
    """Task record information."""
    
    id: str = Field(description="Task ID")
    agent_name: str = Field(description="Agent name")
    task_type: str = Field(description="Task type")
    source_ref: str | None = Field(description="Source reference")
    channel_id: str | None = Field(description="Channel ID")
    success: bool = Field(description="Whether task succeeded")
    error: str | None = Field(description="Error message")
    processing_time_ms: int | None = Field(description="Processing time in ms")
    created_at: datetime = Field(description="Created timestamp")


class TaskHistoryResponse(BaseModel):
    """Response for task history."""
    
    records: list[TaskRecordInfo] = Field(description="Task records")
    total: int = Field(description="Total records returned")
    agent_name: str = Field(description="Agent name filter")


class HandoffStatsResponse(BaseModel):
    """Response for handoff statistics."""
    
    total_handoffs: int = Field(description="Total handoffs")
    completed: int = Field(description="Completed handoffs")
    failed: int = Field(description="Failed handoffs")
    rejected: int = Field(description="Rejected handoffs")
    in_progress: int = Field(description="In-progress handoffs")
    success_rate: float = Field(description="Success rate (0-1)")
    avg_processing_time_ms: float = Field(description="Average processing time")
    min_processing_time_ms: int | None = Field(description="Min processing time")
    max_processing_time_ms: int | None = Field(description="Max processing time")
    top_agent_pairs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top agent pairs by handoff count"
    )


# ============================================================================
# Helper Functions
# ============================================================================


async def _get_persistence():
    """Get AgentPersistence instance using Database singleton."""
    return await get_agent_persistence()


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_model=AgentListResponse)
async def list_agents(
    agent_type: str | None = Query(None, description="Filter by agent type"),
    active_only: bool = Query(False, description="Show only active agents"),
    user: CurrentUser = Depends(resolve_current_user),
) -> AgentListResponse:
    """
    List all registered agents.
    
    Returns agent metadata and basic statistics.
    """
    assert_admin(user)
    persistence = await _get_persistence()

    agents = await persistence.list_all_agent_states(agent_type)

    if active_only:
        agents = [a for a in agents if a.is_active]

    agent_list = [
        AgentInfo(
            name=a.name,
            agent_type=a.agent_type,
            version=a.version,
            description=a.description,
            capabilities=a.capabilities,
            model=a.model,
            provider=a.provider,
            is_active=a.is_active,
            total_tasks_processed=a.total_tasks_processed,
            total_errors=a.total_errors,
            avg_processing_time_ms=a.avg_processing_time_ms,
            last_used_at=a.last_used_at,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]

    return AgentListResponse(agents=agent_list, total=len(agent_list))


@router.get("/{name}", response_model=AgentInfo)
async def get_agent(name: str, user: CurrentUser = Depends(resolve_current_user)) -> AgentInfo:
    """
    Get information about a specific agent.
    """
    assert_admin(user)
    persistence = await _get_persistence()

    state = await persistence.load_agent_state(name)

    if not state:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    return AgentInfo(
        name=state.name,
        agent_type=state.agent_type,
        version=state.version,
        description=state.description,
        capabilities=state.capabilities,
        model=state.model,
        provider=state.provider,
        is_active=state.is_active,
        total_tasks_processed=state.total_tasks_processed,
        total_errors=state.total_errors,
        avg_processing_time_ms=state.avg_processing_time_ms,
        last_used_at=state.last_used_at,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


@router.get("/{name}/stats", response_model=AgentStatsResponse)
async def get_agent_stats(
    name: str,
    days: int = Query(30, ge=1, le=365, description="Statistics period in days"),
    user: CurrentUser = Depends(resolve_current_user),
) -> AgentStatsResponse:
    """
    Get statistics for an agent.
    
    Returns aggregated statistics over the specified period.
    """
    assert_admin(user)
    persistence = await _get_persistence()

    state = await persistence.load_agent_state(name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    summary = await persistence.get_agent_summary(name, days=days)

    return AgentStatsResponse(
        agent_name=name,
        period_days=days,
        total_tasks=summary.get("total_tasks", 0),
        successful_tasks=summary.get("successful_tasks", 0),
        failed_tasks=summary.get("failed_tasks", 0),
        success_rate=summary.get("success_rate", 0.0),
        avg_processing_time_ms=summary.get("avg_processing_time_ms", 0.0),
        by_task_type=summary.get("by_task_type", {}),
    )


@router.get("/{name}/history", response_model=TaskHistoryResponse)
async def get_agent_history(
    name: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
    from_date: str | None = Query(None, description="From date (ISO format)"),
    to_date: str | None = Query(None, description="To date (ISO format)"),
    user: CurrentUser = Depends(resolve_current_user),
) -> TaskHistoryResponse:
    """
    Get task execution history for an agent.
    """
    assert_admin(user)
    persistence = await _get_persistence()

    state = await persistence.load_agent_state(name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    from_dt = None
    to_dt = None
    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
        except ValueError as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid from_date format: {from_date}"
            ) from e
    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date).replace(tzinfo=UTC)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid to_date format: {to_date}"
            ) from e

    records = await persistence.get_task_history(
        agent_name=name,
        from_date=from_dt,
        to_date=to_dt,
        limit=limit,
    )

    record_list = [
        TaskRecordInfo(
            id=r.id,
            agent_name=r.agent_name,
            task_type=r.task_type,
            source_ref=r.source_ref,
            channel_id=r.channel_id,
            success=r.success,
            error=r.error,
            processing_time_ms=r.processing_time_ms,
            created_at=r.created_at,
        )
        for r in records
    ]

    return TaskHistoryResponse(
        records=record_list,
        total=len(record_list),
        agent_name=name,
    )


@router.get("/stats/handoffs", response_model=HandoffStatsResponse)
async def get_handoff_stats(user: CurrentUser = Depends(resolve_current_user)) -> HandoffStatsResponse:
    """
    Get overall handoff statistics between agents.
    """
    assert_admin(user)
    persistence = await _get_persistence()

    stats = await persistence.get_handoff_statistics()

    return HandoffStatsResponse(
        total_handoffs=stats.get("total_handoffs", 0),
        completed=stats.get("completed", 0),
        failed=stats.get("failed", 0),
        rejected=stats.get("rejected", 0),
        in_progress=stats.get("in_progress", 0),
        success_rate=stats.get("success_rate", 0.0),
        avg_processing_time_ms=stats.get("avg_processing_time_ms", 0.0),
        min_processing_time_ms=stats.get("min_processing_time_ms"),
        max_processing_time_ms=stats.get("max_processing_time_ms"),
        top_agent_pairs=stats.get("top_agent_pairs", []),
    )

