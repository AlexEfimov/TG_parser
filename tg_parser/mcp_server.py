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

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

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
        "MCP server for managing and searching a Telegram-channel knowledge base. "
        "Use add_channel to connect new channels, pause_channel/resume_channel to control them, "
        "remove_channel to permanently delete a channel and all its data. "
        "Use trigger_pipeline to start processing, get_pipeline_status to monitor progress. "
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


class AddChannelResult(BaseModel):
    channel_id: str
    source_id: str
    status: str
    created: bool
    message: str


class ChannelStatusResult(BaseModel):
    channel_id: str
    status: str
    previous_status: str
    changed: bool
    message: str


class PipelineSourceStatus(BaseModel):
    source_id: str
    channel_id: str
    status: str
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    fail_count: int = 0
    last_error: str | None = None


class PipelineStatusResult(BaseModel):
    scheduler_enabled: bool
    default_interval_seconds: int
    sources: list[PipelineSourceStatus]


class TriggerPipelineResult(BaseModel):
    channel_id: str
    triggered: bool
    message: str


class RemoveChannelResult(BaseModel):
    channel_id: str
    removed: bool
    message: str
    details: dict[str, int]


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
# T5: MCP Tools — Channel Management
# ---------------------------------------------------------------------------

MAX_ACTIVE_SOURCES = 20


@mcp.tool()
async def add_channel(
    channel_id: str,
    channel_username: str | None = None,
    include_comments: bool = False,
    batch_size: int = 100,
) -> AddChannelResult:
    """Add a Telegram channel to the knowledge base.
The channel becomes active immediately. The background scheduler will
automatically start ingesting and processing its content on the next cycle.
To process immediately, use trigger_pipeline after adding.

Args:
    channel_id: Telegram channel ID or username (with or without @).
    channel_username: Optional display username.
    include_comments: Whether to collect post comments (default false).
    batch_size: Ingestion batch size (default 100)."""
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.storage.ports import Source

    normalized = channel_id.lstrip("@")

    async with ingestion_state_repo() as (state_repo, _db):
        existing = await state_repo.get_source(normalized)

        if existing is None:
            active_sources = await state_repo.list_sources(status="active")
            if len(active_sources) >= MAX_ACTIVE_SOURCES:
                return AddChannelResult(
                    channel_id=normalized,
                    source_id=normalized,
                    status="rejected",
                    created=False,
                    message=f"Maximum active channels limit ({MAX_ACTIVE_SOURCES}) reached. "
                    "Pause or remove unused channels first.",
                )

        source = Source(
            source_id=normalized,
            channel_id=normalized,
            channel_username=channel_username,
            status="active",
            include_comments=include_comments,
            batch_size=batch_size,
            created_at=existing.created_at if existing else None,
        )
        await state_repo.upsert_source(source)

    return AddChannelResult(
        channel_id=normalized,
        source_id=normalized,
        status="active",
        created=existing is None,
        message=f"Channel '{normalized}' {'added' if existing is None else 'updated'} (status=active)."
        " Scheduler will pick it up on the next cycle, or use trigger_pipeline to start immediately.",
    )


@mcp.tool()
async def pause_channel(channel_id: str) -> ChannelStatusResult:
    """Pause ingestion for a channel. The scheduler will skip it on subsequent cycles.
Idempotent: pausing an already-paused channel returns changed=false.

Args:
    channel_id: Channel ID (with or without @)."""
    from tg_parser.services.db_context import ingestion_state_repo

    normalized = channel_id.lstrip("@")

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)
        if source is None:
            return ChannelStatusResult(
                channel_id=normalized,
                status="unknown",
                previous_status="unknown",
                changed=False,
                message=f"Channel '{normalized}' not found. Use add_channel first.",
            )

        previous_status = source.status
        if source.status == "paused":
            return ChannelStatusResult(
                channel_id=normalized,
                status="paused",
                previous_status=previous_status,
                changed=False,
                message=f"Channel '{normalized}' is already paused.",
            )

        source.status = "paused"
        await state_repo.upsert_source(source)

    return ChannelStatusResult(
        channel_id=normalized,
        status="paused",
        previous_status=previous_status,
        changed=True,
        message=f"Channel '{normalized}' paused (was '{previous_status}').",
    )


@mcp.tool()
async def resume_channel(channel_id: str) -> ChannelStatusResult:
    """Resume ingestion for a paused or errored channel.
If the channel was in error state, resets fail_count and last_error.
Idempotent: resuming an already-active channel returns changed=false.

Args:
    channel_id: Channel ID (with or without @)."""
    from tg_parser.services.db_context import ingestion_state_repo

    normalized = channel_id.lstrip("@")

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)
        if source is None:
            return ChannelStatusResult(
                channel_id=normalized,
                status="unknown",
                previous_status="unknown",
                changed=False,
                message=f"Channel '{normalized}' not found. Use add_channel first.",
            )

        previous_status = source.status
        if source.status == "active":
            return ChannelStatusResult(
                channel_id=normalized,
                status="active",
                previous_status=previous_status,
                changed=False,
                message=f"Channel '{normalized}' is already active.",
            )

        if source.status == "error":
            source.fail_count = 0
            source.last_error = None

        source.status = "active"
        await state_repo.upsert_source(source)

    return ChannelStatusResult(
        channel_id=normalized,
        status="active",
        previous_status=previous_status,
        changed=True,
        message=f"Channel '{normalized}' resumed (was '{previous_status}').",
    )


@mcp.tool()
async def remove_channel(
    channel_id: str,
    confirm: bool = False,
) -> RemoveChannelResult:
    """Permanently remove a channel and ALL its data from the knowledge base.
    This action is IRREVERSIBLE. You must set confirm=true to proceed.
    Removes: source config, raw messages, processed documents, embeddings,
    topics, and processing failures.

    Args:
        channel_id: Channel ID (with or without @).
        confirm: Safety flag — must be true to actually delete data."""
    normalized = channel_id.lstrip("@")

    if not confirm:
        return RemoveChannelResult(
            channel_id=normalized,
            removed=False,
            message="Safety check: set confirm=true to permanently delete all data for this channel. "
            "This action is IRREVERSIBLE.",
            details={},
        )

    if normalized in _running_pipelines:
        return RemoveChannelResult(
            channel_id=normalized,
            removed=False,
            message=f"Pipeline for '{normalized}' is currently running. "
            "Wait for it to finish or restart the server before removing.",
            details={},
        )

    from tg_parser.services.db_context import removal_repos

    async with removal_repos() as (
        state_repo, raw_repo, proc_repo, failure_repo,
        embedding_repo, topic_card_repo, topic_bundle_repo, _db,
    ):
        source = await state_repo.get_source(normalized)
        if source is None:
            return RemoveChannelResult(
                channel_id=normalized,
                removed=False,
                message=f"Channel '{normalized}' not found.",
                details={},
            )

        counts: dict[str, int] = {}

        # Processing DB (embeddings first due to FK)
        counts["embeddings"] = await embedding_repo.delete_by_channel(normalized)
        counts["processed_documents"] = await proc_repo.delete_by_channel(normalized)
        counts["processing_failures"] = await failure_repo.delete_by_channel(normalized)
        counts["topic_cards"] = await topic_card_repo.delete_by_channel(normalized)
        counts["topic_bundles"] = await topic_bundle_repo.delete_by_channel(normalized)

        # Raw DB
        counts["raw_messages"] = await raw_repo.delete_by_channel(normalized)

        # Ingestion DB (source last)
        existed = await state_repo.delete_source(normalized)
        counts["source"] = 1 if existed else 0

    total = sum(counts.values())
    return RemoveChannelResult(
        channel_id=normalized,
        removed=True,
        message=f"Channel '{normalized}' removed. {total} records deleted across all tables.",
        details=counts,
    )


# ---------------------------------------------------------------------------
# T6: MCP Tools — Pipeline Control
# ---------------------------------------------------------------------------

_running_pipelines: set[str] = set()
_background_tasks: set[asyncio.Task[None]] = set()


@mcp.tool()
async def get_pipeline_status(
    channel_id: str | None = None,
) -> PipelineStatusResult:
    """Check pipeline and scheduler status for all or a specific channel.
Shows last attempt/success times, fail counts, and scheduler configuration.

Args:
    channel_id: Optional channel filter. If omitted, returns all sources."""
    from tg_parser.services.scheduler_service import get_scheduler_status

    status = await get_scheduler_status()

    sources_raw = status["sources"]
    if channel_id:
        normalized = channel_id.lstrip("@")
        sources_raw = [s for s in sources_raw if s["channel_id"] == normalized]

    sources = [
        PipelineSourceStatus(
            source_id=s["source_id"],
            channel_id=s["channel_id"],
            status=s["status"],
            last_attempt_at=s.get("last_attempt_at"),
            last_success_at=s.get("last_success_at"),
            fail_count=s.get("fail_count", 0),
            last_error=s.get("last_error"),
        )
        for s in sources_raw
    ]

    return PipelineStatusResult(
        scheduler_enabled=status["scheduler_enabled"],
        default_interval_seconds=status["default_interval_seconds"],
        sources=sources,
    )


@mcp.tool()
async def trigger_pipeline(
    channel_id: str,
    force: bool = False,
) -> TriggerPipelineResult:
    """Start the processing pipeline for a channel (fire-and-forget).
Runs ingestion, processing, and embedding in the background.
Use get_pipeline_status to monitor progress.

Args:
    channel_id: Channel ID (with or without @).
    force: Re-process already processed documents (default false)."""
    from tg_parser.services.db_context import ingestion_state_repo

    normalized = channel_id.lstrip("@")

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)

    if not source:
        return TriggerPipelineResult(
            channel_id=normalized,
            triggered=False,
            message=f"Source '{normalized}' not found. Use add_channel first.",
        )

    if source.status != "active":
        return TriggerPipelineResult(
            channel_id=normalized,
            triggered=False,
            message=f"Source '{normalized}' is '{source.status}'. Use resume_channel to activate it first.",
        )

    if normalized in _running_pipelines:
        return TriggerPipelineResult(
            channel_id=normalized,
            triggered=False,
            message=f"Pipeline for '{normalized}' is already running.",
        )

    _running_pipelines.add(normalized)
    task = asyncio.create_task(
        _run_pipeline_background(normalized, force),
        name=f"mcp-pipeline-{normalized}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return TriggerPipelineResult(
        channel_id=normalized,
        triggered=True,
        message=f"Pipeline started for '{normalized}'. Use get_pipeline_status to monitor progress.",
    )


async def _run_pipeline_background(source_id: str, force: bool) -> None:
    try:
        from tg_parser.services.embedding_service import run_embedding
        from tg_parser.services.pipeline_service import run_full_pipeline

        logger.warning("MCP-triggered pipeline started for %s", source_id)

        pipeline_failed = False
        try:
            await run_full_pipeline(
                source_id=source_id,
                mode="incremental",
                force=force,
                output_dir=str(_PROJECT_ROOT / "output"),
            )
        except Exception:
            pipeline_failed = True
            logger.exception(
                "Pipeline failed for %s, proceeding to embedding", source_id,
            )

        await run_embedding(channel_id=source_id, force=False)

        if pipeline_failed:
            logger.warning(
                "MCP-triggered embedding completed for %s (pipeline had errors)",
                source_id,
            )
        else:
            logger.warning("MCP-triggered pipeline completed for %s", source_id)
    except Exception:
        logger.exception("MCP-triggered pipeline failed for %s", source_id)
    finally:
        _running_pipelines.discard(source_id)


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
# MCP-specific logging (keep stdout clean for JSON-RPC)
# ---------------------------------------------------------------------------


def _configure_mcp_logging() -> None:
    """Redirect all logging to stderr so stdout carries only JSON-RPC."""
    import structlog

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _configure_mcp_logging()
    mcp.run()
