"""
Tool definitions and execution for the Gemini agent.

Each tool maps to an internal service call (same capabilities as MCP tools,
but invoked directly without MCP protocol).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Bot-local pipeline run tracking (separate from MCP server process).
_running_pipelines: set[str] = set()
_background_tasks: set[asyncio.Task[None]] = set()

# ---------------------------------------------------------------------------
# Gemini function declarations (OpenAPI-like schema)
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "ask_question",
        "description": (
            "Ask a question about Telegram channel content. "
            "Uses RAG: retrieves relevant documents and generates an answer with an LLM. "
            "Returns the answer text with source references. "
            "Use this for factual questions that need synthesized answers."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {
                    "type": "STRING",
                    "description": "Question in natural language",
                },
                "channel_id": {
                    "type": "STRING",
                    "description": "Optional channel filter (e.g. 'labdiagnostica_logical')",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "Semantic search across the Telegram knowledge base. "
            "Returns documents ranked by relevance with scores and summaries. "
            "Use this to find specific information or explore what's available."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Natural-language search query",
                },
                "channel_id": {
                    "type": "STRING",
                    "description": "Optional channel filter",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum number of results (default 10)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_topics",
        "description": (
            "List topics (knowledge themes) extracted from channel content. "
            "Each topic has a title, summary, type (singleton/cluster), and item count. "
            "Use channel_id to filter by a specific channel."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Optional channel filter",
                },
                "topic_type": {
                    "type": "STRING",
                    "description": "Optional type filter: 'singleton' or 'cluster'",
                },
                "offset": {
                    "type": "INTEGER",
                    "description": "Number of topics to skip (for pagination, default 0)",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum topics to return (default 20)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_topic_details",
        "description": (
            "Get full details of a specific topic: scope, anchors, related topics, "
            "and bundle items. Use after list_topics to explore a topic in depth."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic_id": {
                    "type": "STRING",
                    "description": "The topic ID",
                },
            },
            "required": ["topic_id"],
        },
    },
    {
        "name": "list_channels",
        "description": (
            "List all connected Telegram channels with statistics: "
            "raw messages, processed documents, topics count, and coverage percentage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_document",
        "description": (
            "Get the full content of a processed document by its source reference. "
            "Source refs have format: tg:channel_id:post:123 or tg:channel_id:comment:456."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source_ref": {
                    "type": "STRING",
                    "description": "Document source reference",
                },
            },
            "required": ["source_ref"],
        },
    },
    {
        "name": "get_related_topics",
        "description": (
            "Get topics from other channels that are related to a given topic. "
            "Returns related topics sorted by similarity score with shared keywords."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic_id": {
                    "type": "STRING",
                    "description": "The topic ID to find related topics for",
                },
            },
            "required": ["topic_id"],
        },
    },
    {
        "name": "get_cross_channel_stats",
        "description": (
            "Get cross-channel analytics: topic counts, coverage, and keyword overlaps. "
            "Without channel_id: aggregated stats for all channels. "
            "With channel_id: detailed stats for a specific channel."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Optional channel filter for single-channel detail view",
                },
            },
            "required": [],
        },
    },
    {
        "name": "trigger_pipeline",
        "description": (
            "Start the processing pipeline for a channel (ingest → process → embedding) in the background. "
            "WRITE: ALWAYS call with confirm=false first — the tool returns a preview (doc counts, last run, status). "
            "Only after the user explicitly agrees, call again with confirm=true. "
            "Requires channel status active; use resume_channel if paused/error."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Channel ID or username (with or without @)",
                },
                "force": {
                    "type": "BOOLEAN",
                    "description": "Re-process already processed documents (default false)",
                },
                "confirm": {
                    "type": "BOOLEAN",
                    "description": "Must be false for preview, true to execute after user confirmation (default false)",
                },
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "get_pipeline_status",
        "description": (
            "Read-only: scheduler and pipeline status — last attempt/success times, fail counts, per-source status. "
            "Optional channel_id filters to one channel; omit for all sources."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Optional channel filter",
                },
            },
            "required": [],
        },
    },
    {
        "name": "pause_channel",
        "description": (
            "Pause ingestion/processing for a channel (scheduler skips it). "
            "WRITE: call with confirm=false first for a preview; after explicit user confirmation, call with confirm=true."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Channel ID (with or without @)",
                },
                "confirm": {
                    "type": "BOOLEAN",
                    "description": "false = preview only; true = apply after user confirms (default false)",
                },
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "resume_channel",
        "description": (
            "Resume a paused or errored channel (sets active; clears error counters if was in error). "
            "WRITE: call with confirm=false first for a preview; after explicit user confirmation, call with confirm=true."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Channel ID (with or without @)",
                },
                "confirm": {
                    "type": "BOOLEAN",
                    "description": "false = preview only; true = apply after user confirms (default false)",
                },
            },
            "required": ["channel_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution — dispatch to internal services
# ---------------------------------------------------------------------------


async def execute_tool(
    name: str,
    args: dict[str, Any],
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Execute a tool by name, calling the corresponding internal service.

    Returns a JSON-serializable dict with the result or error.
    """
    executor = _TOOL_EXECUTORS.get(name)
    if executor is None:
        return {"error": f"Unknown tool: {name}"}

    try:
        result = await asyncio.wait_for(executor(args), timeout=timeout)
        return result
    except asyncio.TimeoutError:
        logger.warning("tool_timeout", tool=name, timeout=timeout)
        return {"error": f"Tool '{name}' timed out after {timeout}s"}
    except Exception:
        logger.exception("tool_execution_error", tool=name)
        return {"error": f"Tool '{name}' failed with an internal error"}


# ---------------------------------------------------------------------------
# Individual tool executors
# ---------------------------------------------------------------------------


async def _exec_ask_question(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.retrieval_service import answer

    result = await answer(
        question=args["question"],
        channel_id=args.get("channel_id"),
    )
    sources = [
        {
            "source_ref": s.source_ref,
            "score": round(s.score, 4),
            "summary": s.document.summary if s.document else None,
            "channel_id": s.document.channel_id if s.document else None,
        }
        for s in result.sources
    ]
    return {"answer": result.answer, "sources": sources, "model": result.model}


async def _exec_search(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.retrieval_service import search

    results = await search(
        query=args["query"],
        channel_id=args.get("channel_id"),
        limit=args.get("limit", 10),
    )
    items = [
        {
            "source_ref": r.source_ref,
            "score": round(r.score, 4),
            "summary": r.document.summary if r.document else None,
            "text_preview": r.document.text_clean[:300] if r.document else None,
            "channel_id": r.document.channel_id if r.document else None,
        }
        for r in results
    ]
    return {"results": items, "count": len(items)}


async def _exec_list_topics(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.db_context import processing_repos

    channel_id = args.get("channel_id")
    topic_type = args.get("topic_type")
    offset = args.get("offset", 0)
    limit = args.get("limit", 20)

    async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
        if channel_id:
            cards = await topic_card_repo.list_by_channel(channel_id)
            bundles = await topic_bundle_repo.list_by_channel(channel_id)
        else:
            cards = await topic_card_repo.list_all()
            bundles = await topic_bundle_repo.list_all()

        bundle_map = {b.topic_id: b for b in bundles}

        if topic_type:
            cards = [c for c in cards if c.type.value == topic_type]

        total = len(cards)
        page = cards[offset : offset + limit]

        items = []
        for card in page:
            bundle = bundle_map.get(card.id)
            items.append({
                "id": card.id,
                "title": card.title,
                "type": card.type.value,
                "summary": card.summary,
                "items_count": len(bundle.items) if bundle else 0,
                "sources": card.sources,
            })

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "items": items,
    }


async def _exec_get_topic_details(args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.exc import SQLAlchemyError

    from tg_parser.services.db_context import processing_repos
    from tg_parser.services.topic_linking_service import get_related_topics_for

    topic_id = args["topic_id"]

    async with processing_repos() as (_proc_repo, topic_card_repo, topic_bundle_repo, _db):
        card = await topic_card_repo.get_by_id(topic_id)
        if card is None:
            return {"error": f"Topic not found: {topic_id}"}

        bundle = await topic_bundle_repo.get_by_topic_id(topic_id)
        items = (
            [item.model_dump(mode="json") for item in bundle.items]
            if bundle
            else None
        )

        related_topics = list(card.related_topics) if card.related_topics else []
        try:
            linked = await get_related_topics_for(topic_id)
            for lt in linked:
                label = f"{lt['title']} ({lt['channel_id']}, score={lt['similarity_score']:.2f})"
                related_topics.append(label)
        except (SQLAlchemyError, ValueError):
            pass

        return {
            "id": card.id,
            "title": card.title,
            "type": card.type.value,
            "summary": card.summary,
            "scope_in": card.scope_in,
            "scope_out": card.scope_out,
            "sources": card.sources,
            "tags": card.tags,
            "related_topics": related_topics or None,
            "items_count": len(items) if items else 0,
        }


async def _exec_list_channels(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.channel_service import get_all_channel_stats

    all_stats = await get_all_channel_stats()
    channels = [
        {
            "channel_id": s["channel_id"],
            "channel_username": s.get("channel_username"),
            "status": s["status"],
            "raw_messages": s["raw_messages"],
            "processed_documents": s["processed_documents"],
            "topics_count": s["topics_count"],
            "coverage_percent": s["coverage_percent"],
        }
        for s in all_stats
    ]
    return {"channels": channels, "count": len(channels)}


async def _exec_get_document(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.db_context import processing_repos

    source_ref = args["source_ref"]

    async with processing_repos() as (proc_repo, _tc, _tb, _db):
        doc = await proc_repo.get_by_source_ref(source_ref)

    if doc is None:
        return {"error": f"Document not found: {source_ref}"}

    return {
        "id": doc.id,
        "source_ref": doc.source_ref,
        "channel_id": doc.channel_id,
        "text_clean": doc.text_clean[:2000],
        "summary": doc.summary,
        "topics": doc.topics,
    }


async def _exec_get_related_topics(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.topic_linking_service import get_related_topics_for

    related = await get_related_topics_for(args["topic_id"])
    items = [
        {
            "topic_id": r["topic_id"],
            "title": r["title"],
            "channel_id": r["channel_id"],
            "similarity_score": round(r["similarity_score"], 4),
            "shared_keywords": r["shared_keywords"],
        }
        for r in related
    ]
    return {"related_topics": items, "count": len(items)}


async def _exec_get_cross_channel_stats(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.analytics_service import get_cross_channel_analytics

    return await get_cross_channel_analytics(channel_id=args.get("channel_id"))


def _scheduler_row_for_channel(
    sources: list[dict[str, Any]],
    normalized: str,
) -> dict[str, Any] | None:
    for s in sources:
        cid = str(s["channel_id"]).lstrip("@")
        if cid == normalized:
            return s
    return None


async def _run_pipeline_background(source_id: str, force: bool) -> None:
    try:
        from tg_parser.services.embedding_service import run_embedding
        from tg_parser.services.pipeline_service import run_full_pipeline

        logger.warning("bot_triggered_pipeline_started", channel_id=source_id)

        pipeline_failed = False
        try:
            await run_full_pipeline(
                source_id=source_id,
                mode="incremental",
                force=force,
                output_dir=str(_PROJECT_ROOT / "output"),
            )
        except RuntimeError:
            pipeline_failed = True
            logger.exception(
                "bot_triggered_pipeline_run_failed",
                channel_id=source_id,
            )

        await run_embedding(channel_id=source_id, force=False)

        if pipeline_failed:
            logger.warning(
                "bot_triggered_embedding_done_pipeline_had_errors",
                channel_id=source_id,
            )
        else:
            logger.warning("bot_triggered_pipeline_completed", channel_id=source_id)
    except Exception:
        logger.exception("bot_triggered_pipeline_failed", channel_id=source_id)
    finally:
        _running_pipelines.discard(source_id)


async def _exec_trigger_pipeline(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.channel_service import get_channel_stats
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.services.scheduler_service import get_scheduler_status

    normalized = str(args["channel_id"]).lstrip("@")
    force = bool(args.get("force", False))
    confirm = bool(args.get("confirm", False))

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)

    sched = await get_scheduler_status()
    sched_row = _scheduler_row_for_channel(sched["sources"], normalized)

    processed_documents: int | None = None
    if source is not None:
        try:
            st = await get_channel_stats(normalized)
            processed_documents = st["processed_documents"]
        except ValueError:
            processed_documents = None

    preview_base: dict[str, Any] = {
        "preview": True,
        "channel_id": normalized,
        "source_exists": source is not None,
        "source_status": source.status if source else None,
        "processed_documents": processed_documents,
        "last_attempt_at": sched_row.get("last_attempt_at") if sched_row else None,
        "last_success_at": sched_row.get("last_success_at") if sched_row else None,
        "fail_count": sched_row.get("fail_count") if sched_row else None,
        "last_error": sched_row.get("last_error") if sched_row else None,
        "pipeline_running_in_bot": normalized in _running_pipelines,
        "force": force,
    }

    if not confirm:
        preview_base["message"] = (
            "Preview only. Ask the user to confirm, then call again with confirm=true to start the pipeline."
        )
        return preview_base

    if not source:
        return {
            "triggered": False,
            "channel_id": normalized,
            "message": f"Source '{normalized}' not found. Add the channel via MCP first.",
        }

    if source.status != "active":
        return {
            "triggered": False,
            "channel_id": normalized,
            "message": (
                f"Source '{normalized}' is '{source.status}'. "
                "Use resume_channel (with confirmation) to activate it first."
            ),
        }

    if normalized in _running_pipelines:
        return {
            "triggered": False,
            "channel_id": normalized,
            "message": f"Pipeline for '{normalized}' is already running in this bot process.",
        }

    _running_pipelines.add(normalized)
    task = asyncio.create_task(
        _run_pipeline_background(normalized, force),
        name=f"bot-pipeline-{normalized}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "triggered": True,
        "channel_id": normalized,
        "force": force,
        "message": (
            f"Pipeline started for '{normalized}'. "
            "Use get_pipeline_status to monitor progress."
        ),
    }


async def _exec_get_pipeline_status(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.scheduler_service import get_scheduler_status

    channel_id = args.get("channel_id")
    status = await get_scheduler_status()

    sources_raw = status["sources"]
    if channel_id:
        normalized = str(channel_id).lstrip("@")
        sources_raw = [
            s for s in sources_raw
            if str(s["channel_id"]).lstrip("@") == normalized
        ]

    sources = [
        {
            "source_id": s["source_id"],
            "channel_id": s["channel_id"],
            "status": s["status"],
            "last_attempt_at": s.get("last_attempt_at"),
            "last_success_at": s.get("last_success_at"),
            "fail_count": s.get("fail_count", 0),
            "last_error": s.get("last_error"),
        }
        for s in sources_raw
    ]

    return {
        "scheduler_enabled": status["scheduler_enabled"],
        "default_interval_seconds": status["default_interval_seconds"],
        "retopicize_threshold": status.get("retopicize_threshold"),
        "sources": sources,
    }


async def _exec_pause_channel(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.db_context import ingestion_state_repo

    normalized = str(args["channel_id"]).lstrip("@")
    confirm = bool(args.get("confirm", False))

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)

    if source is None:
        if not confirm:
            return {
                "preview": True,
                "channel_id": normalized,
                "error": "not_found",
                "message": f"Channel '{normalized}' not found. Add the channel via MCP first.",
            }
        return {
            "channel_id": normalized,
            "status": "unknown",
            "previous_status": "unknown",
            "changed": False,
            "message": f"Channel '{normalized}' not found. Add the channel via MCP first.",
        }

    if not confirm:
        return {
            "preview": True,
            "channel_id": normalized,
            "current_status": source.status,
            "action": "pause",
            "will_set_status": "paused",
            "already_effectively_done": source.status == "paused",
            "message": (
                "Preview: pausing will set status to 'paused' (scheduler skips this channel). "
                "Ask the user to confirm, then call again with confirm=true."
                if source.status != "paused"
                else "Preview: channel is already paused; confirming will make no change."
            ),
        }

    previous_status = source.status
    if source.status == "paused":
        return {
            "channel_id": normalized,
            "status": "paused",
            "previous_status": previous_status,
            "changed": False,
            "message": f"Channel '{normalized}' is already paused.",
        }

    source.status = "paused"
    async with ingestion_state_repo() as (state_repo, _db):
        await state_repo.upsert_source(source)

    return {
        "channel_id": normalized,
        "status": "paused",
        "previous_status": previous_status,
        "changed": True,
        "message": f"Channel '{normalized}' paused (was '{previous_status}').",
    }


async def _exec_resume_channel(args: dict[str, Any]) -> dict[str, Any]:
    from tg_parser.services.db_context import ingestion_state_repo

    normalized = str(args["channel_id"]).lstrip("@")
    confirm = bool(args.get("confirm", False))

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)

    if source is None:
        if not confirm:
            return {
                "preview": True,
                "channel_id": normalized,
                "error": "not_found",
                "message": f"Channel '{normalized}' not found. Add the channel via MCP first.",
            }
        return {
            "channel_id": normalized,
            "status": "unknown",
            "previous_status": "unknown",
            "changed": False,
            "message": f"Channel '{normalized}' not found. Add the channel via MCP first.",
        }

    if not confirm:
        return {
            "preview": True,
            "channel_id": normalized,
            "current_status": source.status,
            "action": "resume",
            "will_set_status": "active",
            "fail_count": source.fail_count,
            "last_error": source.last_error,
            "clears_error_counters": source.status == "error",
            "already_effectively_done": source.status == "active",
            "message": (
                (
                    "Preview: resuming will set status to 'active'"
                    + (
                        " and clear fail_count/last_error (channel was in error)."
                        if source.status == "error"
                        else "."
                    )
                    + " Ask the user to confirm, then call again with confirm=true."
                )
                if source.status != "active"
                else "Preview: channel is already active; confirming will make no change."
            ),
        }

    previous_status = source.status
    if source.status == "active":
        return {
            "channel_id": normalized,
            "status": "active",
            "previous_status": previous_status,
            "changed": False,
            "message": f"Channel '{normalized}' is already active.",
        }

    if source.status == "error":
        source.fail_count = 0
        source.last_error = None

    source.status = "active"
    async with ingestion_state_repo() as (state_repo, _db):
        await state_repo.upsert_source(source)

    return {
        "channel_id": normalized,
        "status": "active",
        "previous_status": previous_status,
        "changed": True,
        "message": f"Channel '{normalized}' resumed (was '{previous_status}').",
    }


_TOOL_EXECUTORS: dict[str, Any] = {
    "ask_question": _exec_ask_question,
    "search_knowledge_base": _exec_search,
    "list_topics": _exec_list_topics,
    "get_topic_details": _exec_get_topic_details,
    "list_channels": _exec_list_channels,
    "get_document": _exec_get_document,
    "get_related_topics": _exec_get_related_topics,
    "get_cross_channel_stats": _exec_get_cross_channel_stats,
    "trigger_pipeline": _exec_trigger_pipeline,
    "get_pipeline_status": _exec_get_pipeline_status,
    "pause_channel": _exec_pause_channel,
    "resume_channel": _exec_resume_channel,
}
