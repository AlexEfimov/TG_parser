"""
Topics API routes (P6a): list, detail, and bundle endpoints for topics.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from tg_parser.api.auth import resolve_current_user
from tg_parser.auth.models import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["Topics"])
logger = structlog.get_logger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class TopicListItem(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    items_count: int
    sources: list[str]
    updated_at: datetime


class TopicListResponse(BaseModel):
    topics: list[TopicListItem]
    total: int
    limit: int
    offset: int


class AnchorInfo(BaseModel):
    anchor_ref: str
    score: float | None = None
    label: str | None = None


class TopicDetailResponse(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    scope_in: list[str]
    scope_out: list[str]
    anchors: list[AnchorInfo]
    sources: list[str]
    tags: list[str] | None = None
    related_topics: list[str] | None = None
    updated_at: datetime


class BundleItemInfo(BaseModel):
    source_ref: str
    channel_id: str
    message_id: str
    message_type: str
    role: str


class TopicBundleResponse(BaseModel):
    topic_id: str
    items: list[BundleItemInfo]
    total_items: int
    updated_at: datetime
    time_range: dict | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/topics", response_model=TopicListResponse)
async def list_topics(
    channel_id: str | None = Query(default=None, description="Filter by channel"),
    type: str | None = Query(default=None, description="Filter by type: singleton | cluster"),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Offset"),
    user: CurrentUser = Depends(resolve_current_user),
):
    """List topics with optional filtering by channel and type."""
    from tg_parser.services.db_context import processing_repos

    logger.info("topics_list", channel_id=channel_id, type=type, limit=limit, offset=offset)

    async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
        if channel_id:
            if user.allowed_channel_ids is not None and channel_id not in user.allowed_channel_ids:
                cards = []
            else:
                cards = await topic_card_repo.list_by_channel(channel_id)
        elif user.allowed_channel_ids is not None:
            cards = await topic_card_repo.list_by_channels(user.allowed_channel_ids)
        else:
            cards = await topic_card_repo.list_all()

        if type:
            cards = [c for c in cards if c.type.value == type]

        total = len(cards)
        page = cards[offset : offset + limit]

        items: list[TopicListItem] = []
        for card in page:
            bundle = await topic_bundle_repo.get_by_topic_id(card.id)
            items_count = len(bundle.items) if bundle else 0
            items.append(
                TopicListItem(
                    id=card.id,
                    title=card.title,
                    type=card.type.value,
                    summary=card.summary,
                    items_count=items_count,
                    sources=card.sources,
                    updated_at=card.updated_at,
                )
            )

    return TopicListResponse(topics=items, total=total, limit=limit, offset=offset)


@router.get("/topics/{topic_id:path}/bundle", response_model=TopicBundleResponse)
async def get_topic_bundle(topic_id: str, user: CurrentUser = Depends(resolve_current_user)):
    """Get bundle items (materials) for a topic."""
    from tg_parser.services.db_context import processing_repos

    logger.info("topic_bundle", topic_id=topic_id)

    async with processing_repos() as (_proc_repo, topic_card_repo, topic_bundle_repo, _db):
        card = await topic_card_repo.get_by_id(topic_id)
        if card is not None and user.allowed_channel_ids is not None:
            if not any(s in user.allowed_channel_ids for s in card.sources):
                raise HTTPException(status_code=403, detail=f"No access to topic: {topic_id}")
        bundle = await topic_bundle_repo.get_by_topic_id(topic_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail=f"Bundle not found for topic: {topic_id}")

        time_range_dict = None
        if bundle.time_range:
            time_range_dict = {
                "start": bundle.time_range.from_.isoformat(),
                "end": bundle.time_range.to.isoformat(),
            }

        return TopicBundleResponse(
            topic_id=bundle.topic_id,
            items=[
                BundleItemInfo(
                    source_ref=item.source_ref,
                    channel_id=item.channel_id,
                    message_id=item.message_id,
                    message_type=item.message_type.value,
                    role=item.role.value,
                )
                for item in bundle.items
            ],
            total_items=len(bundle.items),
            updated_at=bundle.updated_at,
            time_range=time_range_dict,
        )


@router.get("/topics/{topic_id:path}", response_model=TopicDetailResponse)
async def get_topic(topic_id: str, user: CurrentUser = Depends(resolve_current_user)):
    """Get full topic card by ID."""
    from tg_parser.services.db_context import processing_repos

    logger.info("topic_detail", topic_id=topic_id)

    async with processing_repos() as (_proc_repo, topic_card_repo, _topic_bundle_repo, _db):
        card = await topic_card_repo.get_by_id(topic_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Topic not found: {topic_id}")

        if user.allowed_channel_ids is not None:
            if not any(s in user.allowed_channel_ids for s in card.sources):
                raise HTTPException(status_code=403, detail=f"No access to topic: {topic_id}")

        return TopicDetailResponse(
            id=card.id,
            title=card.title,
            type=card.type.value,
            summary=card.summary,
            scope_in=card.scope_in,
            scope_out=card.scope_out,
            anchors=[
                AnchorInfo(
                    anchor_ref=a.anchor_ref,
                    score=a.score,
                )
                for a in card.anchors
            ],
            sources=card.sources,
            tags=card.tags,
            related_topics=card.related_topics,
            updated_at=card.updated_at,
        )
