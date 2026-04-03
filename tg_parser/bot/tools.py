"""
Tool definitions and execution for the Gemini agent.

Each tool maps to an internal service call (same capabilities as MCP tools,
but invoked directly without MCP protocol).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

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


_TOOL_EXECUTORS: dict[str, Any] = {
    "ask_question": _exec_ask_question,
    "search_knowledge_base": _exec_search,
    "list_topics": _exec_list_topics,
    "get_topic_details": _exec_get_topic_details,
    "list_channels": _exec_list_channels,
    "get_document": _exec_get_document,
    "get_related_topics": _exec_get_related_topics,
    "get_cross_channel_stats": _exec_get_cross_channel_stats,
}
