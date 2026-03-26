"""
Documents API routes (P6a): document lookup by source_ref.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["Documents"])
logger = structlog.get_logger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class DocumentDetailResponse(BaseModel):
    id: str
    source_ref: str
    channel_id: str
    text_clean: str
    summary: str | None = None
    topics: list[str] = []
    key_facts: list[str] = []
    message_type: str | None = None
    processed_at: datetime
    metadata: dict | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/documents", response_model=DocumentDetailResponse)
async def get_document(
    source_ref: str = Query(description="Source ref, e.g. tg:channel_id:post:123"),
):
    """Get a processed document by source_ref."""
    from tg_parser.services.db_context import processing_repos

    logger.info("document_detail", source_ref=source_ref)

    async with processing_repos() as (proc_repo, _topic_card_repo, _topic_bundle_repo, _db):
        doc = await proc_repo.get_by_source_ref(source_ref)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Document not found: {source_ref}")

        msg_type = None
        parts = source_ref.split(":")
        if len(parts) >= 3:
            msg_type = parts[2]

        return DocumentDetailResponse(
            id=doc.id,
            source_ref=doc.source_ref,
            channel_id=doc.channel_id,
            text_clean=doc.text_clean,
            summary=doc.summary,
            topics=doc.topics,
            key_facts=[],
            message_type=msg_type,
            processed_at=doc.processed_at,
            metadata=doc.metadata,
        )
