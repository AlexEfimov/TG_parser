"""
MCP Server for TG_parser Knowledge Base (P6b).

Exposes search, Q&A, topic navigation, and channel statistics
as MCP tools/resources for AI agents (Claude Desktop, Cursor, etc.).

Transport: stdio (default).

Usage:
    python -m tg_parser.mcp_server
    # or via CLI:
    tg-parser mcp
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# Reject unknown tool parameters instead of silently ignoring them.
# Must be set before @mcp.tool() decorators run (they create Pydantic
# subclasses of ArgModelBase that inherit this config).
ArgModelBase.model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "TG_parser Knowledge Base",
    instructions=(
        "MCP server for navigating and searching a Telegram-channel knowledge base. "
        "Use search_knowledge_base for semantic search, ask_question for RAG Q&A, "
        "list_topics / get_topic_details for topic navigation, "
        "list_channels for channel overview, get_document for full document content."
    ),
)

# ---------------------------------------------------------------------------
# Pydantic schemas (T5) — structured output for MCP tools
# ---------------------------------------------------------------------------


class SearchResultItem(BaseModel):
    source_ref: str
    score: float
    summary: str | None = None
    text_preview: str | None = None
    channel_id: str | None = None


class AnswerResultItem(BaseModel):
    answer: str
    sources: list[SearchResultItem]
    model: str | None = None


class TopicSummary(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    items_count: int
    sources: list[str]


class TopicListResult(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool
    items: list[TopicSummary]


class TopicDetail(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    scope_in: list[str]
    scope_out: list[str]
    anchors: list[dict[str, Any]]
    sources: list[str]
    tags: list[str] | None = None
    related_topics: list[str] | None = None
    items: list[dict[str, Any]] | None = None


class ChannelSummary(BaseModel):
    channel_id: str
    channel_username: str | None = None
    status: str
    raw_messages: int
    processed_documents: int
    topics_count: int
    coverage_percent: float


class DocumentDetail(BaseModel):
    id: str
    source_ref: str
    channel_id: str
    text_clean: str
    summary: str | None = None
    topics: list[str] = []


# ---------------------------------------------------------------------------
# T2: MCP Tools — Search & Q&A
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_knowledge_base(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
) -> list[SearchResultItem]:
    """Semantic search across the Telegram knowledge base.
Returns documents ranked by relevance with scores and summaries.
Use this to find specific information in channel posts.

Args:
    query: Natural-language search query.
    channel_id: Optional channel filter (e.g. "labdiagnostica_logical").
    limit: Maximum number of results (default 10)."""
    if not query or not query.strip():
        return []

    from tg_parser.services.retrieval_service import search

    results = await search(query=query, channel_id=channel_id, limit=limit)
    items: list[SearchResultItem] = []
    for r in results:
        doc = r.document
        items.append(
            SearchResultItem(
                source_ref=r.source_ref,
                score=round(r.score, 4),
                summary=doc.summary if doc else None,
                text_preview=doc.text_clean[:300] if doc else None,
                channel_id=doc.channel_id if doc else None,
            )
        )
    return items


@mcp.tool()
async def ask_question(
    question: str,
    channel_id: str | None = None,
) -> AnswerResultItem:
    """Ask a question about Telegram channel content.
Uses RAG: retrieves relevant documents and generates an answer with an LLM.
Returns the answer text with source references.

Args:
    question: Question in natural language.
    channel_id: Optional channel filter."""
    if not question or not question.strip():
        return AnswerResultItem(answer="Please provide a non-empty question.", sources=[], model=None)

    from tg_parser.services.retrieval_service import answer

    result = await answer(question=question, channel_id=channel_id)
    sources = [
        SearchResultItem(
            source_ref=s.source_ref,
            score=round(s.score, 4),
            summary=s.document.summary if s.document else None,
            text_preview=s.document.text_clean[:300] if s.document else None,
            channel_id=s.document.channel_id if s.document else None,
        )
        for s in result.sources
    ]
    return AnswerResultItem(
        answer=result.answer,
        sources=sources,
        model=result.model,
    )


# ---------------------------------------------------------------------------
# T3: MCP Tools — Navigation
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_topics(
    channel_id: str | None = None,
    topic_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> TopicListResult:
    """List topics (knowledge themes) extracted from channel content.
Returns a paginated result with total count and has_more flag.
When has_more is true, increase offset by limit to fetch the next page.

Each topic has a title, summary, type (singleton/cluster), and item count.
Use channel_id to filter by a specific channel, topic_type to filter by
'singleton' or 'cluster'.

Args:
    channel_id: Optional channel filter.
    topic_type: Optional type filter ('singleton' or 'cluster').
    offset: Number of topics to skip (default 0). Use for pagination.
    limit: Maximum topics to return per page (default 50)."""
    from tg_parser.services.db_context import processing_repos

    async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
        if channel_id:
            cards = await topic_card_repo.list_by_channel(channel_id)
        else:
            cards = await topic_card_repo.list_all()

        if topic_type:
            cards = [c for c in cards if c.type.value == topic_type]

        total = len(cards)
        page = cards[offset : offset + limit]

        summaries: list[TopicSummary] = []
        for card in page:
            bundle = await topic_bundle_repo.get_by_topic_id(card.id)
            items_count = len(bundle.items) if bundle else 0
            summaries.append(
                TopicSummary(
                    id=card.id,
                    title=card.title,
                    type=card.type.value,
                    summary=card.summary,
                    items_count=items_count,
                    sources=card.sources,
                )
            )

    return TopicListResult(
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
        items=summaries,
    )


@mcp.tool()
async def get_topic_details(topic_id: str) -> TopicDetail | str:
    """Get full details of a topic: scope, anchors, related topics, and bundle items.
Use this after list_topics to dive deeper into a specific topic.

Args:
    topic_id: The topic ID (e.g. 'topic:tg:channel:post:123')."""
    from tg_parser.services.db_context import processing_repos

    async with processing_repos() as (_proc_repo, topic_card_repo, topic_bundle_repo, _db):
        card = await topic_card_repo.get_by_id(topic_id)
        if card is None:
            return f"Topic not found: {topic_id}"

        bundle = await topic_bundle_repo.get_by_topic_id(topic_id)
        items = (
            [item.model_dump(mode="json") for item in bundle.items]
            if bundle
            else None
        )

        return TopicDetail(
            id=card.id,
            title=card.title,
            type=card.type.value,
            summary=card.summary,
            scope_in=card.scope_in,
            scope_out=card.scope_out,
            anchors=[
                {**a.model_dump(mode="json"), "source_ref": a.anchor_ref}
                for a in card.anchors
            ],
            sources=card.sources,
            tags=card.tags,
            related_topics=card.related_topics,
            items=items,
        )


@mcp.tool()
async def list_channels() -> list[ChannelSummary]:
    """List all connected Telegram channels with statistics.
Shows raw/processed message counts, topics, and coverage percentage."""
    from tg_parser.services.channel_service import get_channel_stats
    from tg_parser.services.db_context import ingestion_state_repo

    async with ingestion_state_repo() as (state_repo, _db):
        sources = await state_repo.list_sources()

    summaries: list[ChannelSummary] = []
    for src in sources:
        try:
            stats = await get_channel_stats(src.channel_id)
            summaries.append(
                ChannelSummary(
                    channel_id=stats["channel_id"],
                    channel_username=stats.get("channel_username"),
                    status=src.status,
                    raw_messages=stats["raw_messages"],
                    processed_documents=stats["processed_documents"],
                    topics_count=stats["topics_count"],
                    coverage_percent=stats["coverage_percent"],
                )
            )
        except Exception:
            logger.exception("Failed to get stats for channel %s", src.channel_id)
            summaries.append(
                ChannelSummary(
                    channel_id=src.channel_id,
                    channel_username=src.channel_username,
                    status=src.status,
                    raw_messages=0,
                    processed_documents=0,
                    topics_count=0,
                    coverage_percent=0.0,
                )
            )
    return summaries


@mcp.tool()
async def get_document(source_ref: str) -> DocumentDetail | str:
    """Get the full content of a processed document by its source reference.
Source refs have format: tg:channel_id:post:123 or tg:channel_id:comment:456.

Args:
    source_ref: Document source reference."""
    from tg_parser.services.db_context import processing_repos

    async with processing_repos() as (proc_repo, _tc, _tb, _db):
        doc = await proc_repo.get_by_source_ref(source_ref)

    if doc is None:
        return f"Document not found: {source_ref}"

    return DocumentDetail(
        id=doc.id,
        source_ref=doc.source_ref,
        channel_id=doc.channel_id,
        text_clean=doc.text_clean,
        summary=doc.summary,
        topics=doc.topics,
    )


# ---------------------------------------------------------------------------
# T4: MCP Resources
# ---------------------------------------------------------------------------


@mcp.resource("tgparser://channels")
async def resource_channels() -> str:
    """List of connected Telegram channels with statistics."""
    channels = await list_channels()
    return json.dumps(
        [ch.model_dump() for ch in channels],
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("tgparser://channels/{channel_id}/topics")
async def resource_channel_topics(channel_id: str) -> str:
    """Topics for a specific channel."""
    topics = await list_topics(channel_id=channel_id)
    return json.dumps(
        [t.model_dump() for t in topics],
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("tgparser://topics/{topic_id}")
async def resource_topic(topic_id: str) -> str:
    """Topic card details."""
    detail = await get_topic_details(topic_id)
    if isinstance(detail, str):
        return json.dumps({"error": detail})
    return json.dumps(detail.model_dump(), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
