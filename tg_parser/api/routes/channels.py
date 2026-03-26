"""
Channels API routes (P6a): list channels and channel statistics.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["Channels"])
logger = structlog.get_logger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class ChannelInfo(BaseModel):
    channel_id: str
    channel_username: str | None = None
    status: str
    include_comments: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChannelListResponse(BaseModel):
    channels: list[ChannelInfo]
    total: int


class ChannelStatsResponse(BaseModel):
    channel_id: str
    channel_username: str | None = None
    raw_messages: int
    processed_documents: int
    topics_count: int
    covered_documents: int
    coverage_percent: float
    embeddings_count: int
    missing_embeddings: int


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/channels", response_model=ChannelListResponse)
async def list_channels():
    """List all connected channels."""
    from tg_parser.services.db_context import ingestion_state_repo

    logger.info("channels_list")

    async with ingestion_state_repo() as (state_repo, _db):
        sources = await state_repo.list_sources()

    channels = [
        ChannelInfo(
            channel_id=s.channel_id,
            channel_username=s.channel_username,
            status=s.status,
            include_comments=s.include_comments,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sources
    ]

    return ChannelListResponse(channels=channels, total=len(channels))


@router.get("/channels/{channel_id}/stats", response_model=ChannelStatsResponse)
async def get_channel_stats(channel_id: str):
    """Get aggregated statistics for a channel."""
    from tg_parser.services.channel_service import get_channel_stats as _get_stats

    logger.info("channel_stats", channel_id=channel_id)

    try:
        stats = await _get_stats(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ChannelStatsResponse(**stats)
