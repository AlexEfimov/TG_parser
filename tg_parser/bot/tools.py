"""
Tool definitions and execution for the Gemini agent.

Each tool maps to an internal service call (same capabilities as MCP tools,
but invoked directly without MCP protocol).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from tg_parser.auth.models import CurrentUser

if TYPE_CHECKING:
    from aiogram import Bot

logger = structlog.get_logger(__name__)

# Telegram Bot API limit on send_document: 50 MB.
TG_BOT_DOCUMENT_LIMIT_BYTES: int = 50 * 1024 * 1024

# Tools that need access to the bot instance / chat_id (e.g. to upload files).
_TOOLS_NEEDING_BOT_CONTEXT: set[str] = {
    "export_channel",
    "subscribe_digest",
    "subscribe_watchlist",
}

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
    {
        "name": "add_channel",
        "description": (
            "Add a new Telegram channel to the knowledge base or update an existing one. "
            "WRITE: ALWAYS call with confirm=false first — the tool returns a preview showing "
            "what will be created/updated and the active sources count vs limit. "
            "Only after the user explicitly agrees, call again with confirm=true."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Telegram channel ID or username (with or without @)",
                },
                "channel_username": {
                    "type": "STRING",
                    "description": "Optional display username for the channel",
                },
                "include_comments": {
                    "type": "BOOLEAN",
                    "description": "Whether to collect post comments (default false)",
                },
                "batch_size": {
                    "type": "INTEGER",
                    "description": "Ingestion batch size (default 100)",
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
        "name": "remove_channel",
        "description": (
            "Soft-delete a channel: mark its source row as deleted_at=now() and stop ingestion. "
            "Associated raw messages, processed documents, topics, and embeddings are PRESERVED "
            "(an admin can later reanimate the channel by re-adding it via add_channel). "
            "WRITE: ALWAYS call with confirm=false first — the tool shows current data counts. "
            "Only after the user explicitly agrees, call again with confirm=true."
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
                    "description": "Must be false for preview, true to execute after user confirmation (default false)",
                },
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "get_llm_config",
        "description": (
            "Show the current active LLM configuration: provider/model per stage, "
            "available providers, and any runtime overrides. Read-only, no confirmation needed."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "set_llm_config",
        "description": (
            "Change the LLM provider/model at runtime (no restart needed). "
            "WRITE: ALWAYS call with confirm=false first — the tool shows current config "
            "and what will change. Only after the user explicitly agrees, call with confirm=true."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "scope": {
                    "type": "STRING",
                    "description": "Which config to change: 'global', 'processing', 'topicization', or 'rag'",
                },
                "provider": {
                    "type": "STRING",
                    "description": "LLM provider: 'openai', 'anthropic', 'gemini', or 'ollama'",
                },
                "model": {
                    "type": "STRING",
                    "description": "Optional model name (e.g. 'gpt-4o', 'claude-sonnet-4-20250514'). Omit for provider default.",
                },
                "temperature": {
                    "type": "NUMBER",
                    "description": "Optional temperature override (0.0-2.0). Only applied for this scope.",
                },
                "max_tokens": {
                    "type": "INTEGER",
                    "description": "Optional max_tokens override. Only applied for this scope.",
                },
                "confirm": {
                    "type": "BOOLEAN",
                    "description": "Must be false for preview, true to execute after user confirmation (default false)",
                },
            },
            "required": ["scope", "provider"],
        },
    },
    {
        "name": "reset_llm_config",
        "description": (
            "Reset runtime LLM overrides, reverting to .env defaults. "
            "WRITE: ALWAYS call with confirm=false first — the tool shows which overrides "
            "will be cleared. Only after the user explicitly agrees, call with confirm=true."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "scope": {
                    "type": "STRING",
                    "description": "Scope to reset: 'global', 'processing', 'topicization', or 'rag'. Omit to reset ALL overrides.",
                },
                "confirm": {
                    "type": "BOOLEAN",
                    "description": "Must be false for preview, true to execute after user confirmation (default false)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "reload_prompts",
        "description": (
            "Reload prompt templates from YAML files (no restart needed). "
            "Use after editing prompts/*.yaml files on disk."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": (
                        "Optional prompt name: 'rag', 'bot', 'processing', "
                        "'topicization', 'incremental_discover', 'merge', 'supporting_items'. "
                        "Omit to reload ALL."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "register_user",
        "description": "Register a new user (admin only). Creates user with specified name, role, and channel limit.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "User display name"},
                "role": {
                    "type": "STRING",
                    "enum": ["user", "admin"],
                    "description": "User role (default: user)",
                },
                "max_channels": {
                    "type": "INTEGER",
                    "description": "Max channels limit (omit for global default)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_user",
        "description": (
            "Update user properties (admin only). Only provided fields are changed. "
            "Set reset_max_channels=true to reset limit to global default."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "User ID to update"},
                "name": {"type": "STRING", "description": "New display name"},
                "role": {"type": "STRING", "enum": ["user", "admin"], "description": "New role"},
                "max_channels": {"type": "INTEGER", "description": "New channel limit"},
                "reset_max_channels": {
                    "type": "BOOLEAN",
                    "description": "Reset max_channels to global default (default: false)",
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "list_users",
        "description": "List all users with their channel counts (admin only).",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "whoami",
        "description": "Show current user's profile: name, role, owned channels, and channel limit.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "add_user_auth",
        "description": (
            "Add auth mapping for a user (admin only). "
            "Supports api_key, telegram, and mcp_token types. "
            "API keys and MCP tokens are hashed automatically."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "User ID to add auth for"},
                "auth_type": {
                    "type": "STRING",
                    "enum": ["api_key", "telegram", "mcp_token"],
                    "description": "Auth type",
                },
                "identifier": {
                    "type": "STRING",
                    "description": "Raw credential value (hashed automatically for api_key/mcp_token)",
                },
                "client_name": {"type": "STRING", "description": "Optional client name label"},
            },
            "required": ["user_id", "auth_type", "identifier"],
        },
    },
    {
        "name": "remove_user_auth",
        "description": "Remove an auth mapping by ID (admin only).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mapping_id": {"type": "STRING", "description": "Auth mapping ID to remove"},
            },
            "required": ["mapping_id"],
        },
    },
    {
        "name": "export_channel",
        "description": (
            "Export channel content (F2 Parse-Only). "
            "level='raw' produces raw Telegram messages without LLM processing "
            "(default for parse-only use); 'processed' produces KnowledgeBaseEntry[]; "
            "'full' (legacy) produces processed + topics. "
            "format='json' or 'ndjson' applies to level='raw'. "
            "Sends the result file directly into the chat when its size is within "
            "Telegram's 50 MB document limit; otherwise returns a download URL. "
            "raw_payload is never included (privacy)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "channel_id": {
                    "type": "STRING",
                    "description": "Telegram channel ID (required for level='raw')",
                },
                "level": {
                    "type": "STRING",
                    "enum": ["raw", "processed", "full"],
                    "description": "Export level (default 'raw')",
                },
                "format": {
                    "type": "STRING",
                    "enum": ["json", "ndjson"],
                    "description": "Output format for level='raw' (default 'json')",
                },
                "from_date": {
                    "type": "STRING",
                    "description": "Optional ISO-8601 UTC datetime filter (inclusive)",
                },
                "to_date": {
                    "type": "STRING",
                    "description": "Optional ISO-8601 UTC datetime filter (inclusive)",
                },
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "subscribe_digest",
        "description": (
            "Create a recurring digest subscription (F6). The bot will summarize "
            "new processed documents from the selected channels and deliver them "
            "to the current chat on the cron schedule. Cron expression is the "
            "standard 5-field format (minute hour day month weekday). Default "
            "schedule is '0 9 * * *' (daily at 09:00 in the chosen timezone). "
            "format controls style: 'summary' (1-2 paragraphs per channel), "
            "'bullets' (one-line bullets), 'detailed' (paragraph + key quotes)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": "Subscription name (used by list/unsubscribe)",
                },
                "channel_ids": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Channel IDs (or @usernames) to include in the digest",
                },
                "cron_expression": {
                    "type": "STRING",
                    "description": "5-field cron expression (default '0 9 * * *')",
                },
                "timezone": {
                    "type": "STRING",
                    "description": "IANA timezone such as 'Europe/Moscow' (default 'UTC')",
                },
                "format": {
                    "type": "STRING",
                    "enum": ["summary", "bullets", "detailed"],
                    "description": "Digest formatting style (default 'summary')",
                },
                "language": {
                    "type": "STRING",
                    "description": "Output language code (default 'ru')",
                },
            },
            "required": ["name", "channel_ids"],
        },
    },
    {
        "name": "list_digests",
        "description": (
            "List the caller's digest subscriptions (F6). Admins see every "
            "subscription, regular users see only their own."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "unsubscribe_digest",
        "description": (
            "Delete a digest subscription by id (F6). Owner-only for non-admins; "
            "admins can delete any subscription."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "subscription_id": {
                    "type": "STRING",
                    "description": "Subscription UUID returned by subscribe_digest / list_digests",
                },
            },
            "required": ["subscription_id"],
        },
    },
    {
        "name": "subscribe_watchlist",
        "description": (
            "Create a persistent thematic alert (F11 Topic Watchlist). After "
            "every incremental pipeline tick, new processed messages from the "
            "selected channels are scored against this interest using a hybrid "
            "keyword + semantic match (weights 0.4 / 0.6). Matches above "
            "threshold are pushed to the current chat by the bot. The chat_id "
            "is taken from the bot context — no need to pass it explicitly. "
            "Default threshold is 0.6 (lower = more matches, higher = fewer)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Short human label (used in push notifications)",
                },
                "channel_ids": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Channel IDs (or @usernames) to watch",
                },
                "keywords": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Positive keywords (recall-like overlap component)",
                },
                "description": {
                    "type": "STRING",
                    "description": (
                        "Optional free-form text used as embedding source. "
                        "If omitted, embedding falls back to title + keywords."
                    ),
                },
                "exclude_keywords": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Negative filter — any matching token zeroes the score",
                },
                "threshold": {
                    "type": "NUMBER",
                    "description": "Combined-score cutoff in [0, 1] (default 0.6)",
                },
            },
            "required": ["title", "channel_ids"],
        },
    },
    {
        "name": "list_watchlists",
        "description": (
            "List the caller's topic watchlists (F11). Admins see every interest "
            "in the system; regular users see only their own. Inactive interests "
            "are included so the caller can audit / re-create them."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "unsubscribe_watchlist",
        "description": (
            "Soft-delete a topic watchlist by id (F11). Owner-only for "
            "non-admins; admins can delete any interest. Match history is "
            "preserved so historical queries still work."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "interest_id": {
                    "type": "STRING",
                    "description": "Interest UUID returned by subscribe_watchlist / list_watchlists",
                },
            },
            "required": ["interest_id"],
        },
    },
    {
        "name": "get_watchlist_matches",
        "description": (
            "Return saved matches for a watchlist interest (F11). Owner-only "
            "for non-admins; admins can read any interest. since_iso is an "
            "optional ISO-8601 datetime filter for incremental polling."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "interest_id": {
                    "type": "STRING",
                    "description": "Interest UUID",
                },
                "since_iso": {
                    "type": "STRING",
                    "description": "Optional ISO-8601 datetime cursor (created_at >= since_iso)",
                },
            },
            "required": ["interest_id"],
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
    current_user: CurrentUser | None = None,
    bot: Bot | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """Execute a tool by name, calling the corresponding internal service.

    ``bot`` and ``chat_id`` are forwarded only to executors that need them
    (e.g. ``export_channel`` uses them to deliver files via aiogram).

    Returns a JSON-serializable dict with the result or error.
    """
    executor = _TOOL_EXECUTORS.get(name)
    if executor is None:
        return {"error": f"Unknown tool: {name}"}

    kwargs: dict[str, Any] = {"current_user": current_user}
    if name in _TOOLS_NEEDING_BOT_CONTEXT:
        kwargs["bot"] = bot
        kwargs["chat_id"] = chat_id

    try:
        result = await asyncio.wait_for(
            executor(args, **kwargs),
            timeout=timeout,
        )
        return result
    except TimeoutError:
        logger.warning("tool_timeout", tool=name, timeout=timeout)
        return {"error": f"Tool '{name}' timed out after {timeout}s"}
    except Exception:
        logger.exception("tool_execution_error", tool=name)
        return {"error": f"Tool '{name}' failed with an internal error"}


# ---------------------------------------------------------------------------
# Individual tool executors
# ---------------------------------------------------------------------------


async def _exec_ask_question(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.retrieval_service import answer

    user = current_user or await get_default_admin()
    result = await answer(
        question=args["question"],
        channel_id=args.get("channel_id"),
        allowed_channel_ids=user.allowed_channel_ids,
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


async def _exec_search(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.retrieval_service import search

    user = current_user or await get_default_admin()
    results = await search(
        query=args["query"],
        channel_id=args.get("channel_id"),
        limit=args.get("limit", 10),
        allowed_channel_ids=user.allowed_channel_ids,
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


async def _exec_list_topics(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import processing_repos

    user = current_user or await get_default_admin()
    channel_id = args.get("channel_id")
    topic_type = args.get("topic_type")
    offset = args.get("offset", 0)
    limit = args.get("limit", 20)

    async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
        if channel_id:
            cards = await topic_card_repo.list_by_channel(channel_id)
            bundles = await topic_bundle_repo.list_by_channel(channel_id)
        elif user.allowed_channel_ids is not None:
            cards = await topic_card_repo.list_by_channels(user.allowed_channel_ids)
            bundles = await topic_bundle_repo.list_all()
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
            items.append(
                {
                    "id": card.id,
                    "title": card.title,
                    "type": card.type.value,
                    "summary": card.summary,
                    "items_count": len(bundle.items) if bundle else 0,
                    "sources": card.sources,
                }
            )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "items": items,
    }


async def _exec_get_topic_details(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from sqlalchemy.exc import SQLAlchemyError

    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import processing_repos
    from tg_parser.services.topic_linking_service import get_related_topics_for

    user = current_user or await get_default_admin()
    topic_id = args["topic_id"]

    async with processing_repos() as (_proc_repo, topic_card_repo, topic_bundle_repo, _db):
        card = await topic_card_repo.get_by_id(topic_id)
        if card is None:
            return {"error": f"Topic not found: {topic_id}"}

        if user.allowed_channel_ids is not None:
            if not any(s in user.allowed_channel_ids for s in card.sources):
                return {"error": f"No access to topic: {topic_id}"}

        bundle = await topic_bundle_repo.get_by_topic_id(topic_id)
        items = [item.model_dump(mode="json") for item in bundle.items] if bundle else None

        related_topics = list(card.related_topics) if card.related_topics else []
        try:
            linked = await get_related_topics_for(
                topic_id,
                allowed_channel_ids=user.allowed_channel_ids,
            )
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


async def _exec_list_channels(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.channel_service import get_all_channel_stats

    user = current_user or await get_default_admin()
    all_stats = await get_all_channel_stats(allowed_channel_ids=user.allowed_channel_ids)
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


async def _exec_get_document(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import processing_repos

    user = current_user or await get_default_admin()
    source_ref = args["source_ref"]

    async with processing_repos() as (proc_repo, _tc, _tb, _db):
        doc = await proc_repo.get_by_source_ref(source_ref)

    if doc is None:
        return {"error": f"Document not found: {source_ref}"}

    if user.allowed_channel_ids is not None and doc.channel_id not in user.allowed_channel_ids:
        return {"error": f"No access to document: {source_ref}"}

    return {
        "id": doc.id,
        "source_ref": doc.source_ref,
        "channel_id": doc.channel_id,
        "text_clean": doc.text_clean[:2000],
        "summary": doc.summary,
        "topics": doc.topics,
    }


async def _exec_get_related_topics(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.topic_linking_service import get_related_topics_for

    user = current_user or await get_default_admin()
    related = await get_related_topics_for(
        args["topic_id"],
        allowed_channel_ids=user.allowed_channel_ids,
    )
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


async def _exec_get_cross_channel_stats(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.analytics_service import get_cross_channel_analytics

    user = current_user or await get_default_admin()
    return await get_cross_channel_analytics(
        channel_id=args.get("channel_id"),
        allowed_channel_ids=user.allowed_channel_ids,
    )


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


async def _exec_trigger_pipeline(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.channel_service import get_channel_stats
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.services.scheduler_service import get_scheduler_status

    user = current_user or await get_default_admin()
    normalized = str(args["channel_id"]).lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return {"error": e.message}
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
            f"Pipeline started for '{normalized}'. Use get_pipeline_status to monitor progress."
        ),
    }


async def _exec_get_pipeline_status(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.scheduler_service import get_scheduler_status

    user = current_user or await get_default_admin()
    channel_id = args.get("channel_id")
    status = await get_scheduler_status()

    sources_raw = status["sources"]
    if channel_id:
        normalized = str(channel_id).lstrip("@")
        sources_raw = [s for s in sources_raw if str(s["channel_id"]).lstrip("@") == normalized]

    if user.allowed_channel_ids is not None:
        sources_raw = [
            s for s in sources_raw if str(s["channel_id"]).lstrip("@") in user.allowed_channel_ids
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


async def _exec_pause_channel(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import ingestion_state_repo

    user = current_user or await get_default_admin()
    normalized = str(args["channel_id"]).lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return {"error": e.message}
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


async def _exec_resume_channel(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import ingestion_state_repo

    user = current_user or await get_default_admin()
    normalized = str(args["channel_id"]).lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return {"error": e.message}
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


async def _exec_add_channel(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, check_channel_limit
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.channel_placeholders import (
        blocked_message,
        get_blocked_placeholder_names,
        is_blocked_placeholder,
    )
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.storage.ports import Source

    user = current_user or await get_default_admin()
    normalized = str(args["channel_id"]).lstrip("@")
    channel_username = args.get("channel_username")
    include_comments = bool(args.get("include_comments", False))
    batch_size = int(args.get("batch_size", 100))
    confirm = bool(args.get("confirm", False))

    # M2 (BUG-002): refuse placeholder channel ids before touching the DB
    # so a hallucinated `add_channel(channel_id="test_channel", confirm=True)`
    # cannot create the row that BUG-002's destructive turn-2 path could
    # then target. Symmetrical with the MCP `add_channel` guard.
    if is_blocked_placeholder(normalized):
        blocked = get_blocked_placeholder_names()
        logger.warning(
            "add_channel rejected blocked placeholder",
            channel_id=normalized,
            blocked_list_size=len(blocked),
        )
        return {
            "success": False,
            "error": "blocked_placeholder_name",
            "channel_id": normalized,
            "message": blocked_message(normalized),
            "blocked_list_size": len(blocked),
        }

    async with ingestion_state_repo() as (state_repo, _db):
        existing = await state_repo.get_source(normalized)
        if user.is_admin:
            user_sources = await state_repo.list_sources(status="active")
        else:
            user_sources = await state_repo.list_sources(status="active", owner_id=user.id)

    user_active_count = len(user_sources)

    if not confirm:
        limit_reached = False
        if existing is None:
            try:
                check_channel_limit(user, user_active_count)
            except PermissionDenied:
                limit_reached = True
        return {
            "preview": True,
            "channel_id": normalized,
            "action": "update" if existing else "create",
            "current_status": existing.status if existing else None,
            "settings": {
                "channel_username": channel_username,
                "include_comments": include_comments,
                "batch_size": batch_size,
            },
            "active_sources": user_active_count,
            "max_active_sources": user.max_channels,
            "limit_reached": limit_reached,
            "message": (
                "Preview only. Ask the user to confirm, then call again with confirm=true."
            ),
        }

    if existing is None:
        try:
            check_channel_limit(user, user_active_count)
        except PermissionDenied as e:
            return {"channel_id": normalized, "created": False, "message": e.message}

    source = Source(
        source_id=normalized,
        channel_id=normalized,
        channel_username=channel_username,
        status="active",
        include_comments=include_comments,
        batch_size=batch_size,
        created_at=existing.created_at if existing else None,
        owner_id=existing.owner_id if existing else user.id,
    )

    async with ingestion_state_repo() as (state_repo, _db):
        await state_repo.upsert_source(source)

    created = existing is None
    return {
        "channel_id": normalized,
        "created": created,
        "status": "active",
        "message": (
            f"Channel '{normalized}' {'added' if created else 'updated'} (status=active). "
            "Scheduler will pick it up on the next cycle, or use trigger_pipeline to start immediately."
        ),
    }


async def _exec_remove_channel(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.channel_service import get_channel_stats
    from tg_parser.services.db_context import ingestion_state_repo

    user = current_user or await get_default_admin()
    normalized = str(args["channel_id"]).lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return {"channel_id": normalized, "removed": False, "message": e.message}
    confirm = bool(args.get("confirm", False))

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)

    if source is None:
        return {
            "channel_id": normalized,
            "removed": False,
            "message": f"Channel '{normalized}' not found.",
        }

    if not confirm:
        stats: dict[str, Any] = {}
        try:
            stats = await get_channel_stats(normalized)
        except (ValueError, Exception):
            pass

        return {
            "preview": True,
            "channel_id": normalized,
            "current_status": source.status,
            "processed_documents": stats.get("processed_documents", 0),
            "topics_count": stats.get("topics_count", 0),
            "raw_messages": stats.get("raw_messages", 0),
            "warning": (
                "Soft-delete: the source row will be marked deleted_at=now() and "
                "ingestion will stop. Existing raw_messages, processed_documents, "
                "topics, and embeddings are preserved and can be reanimated by an admin."
            ),
            "message": (
                "Preview only. Ask the user to confirm, then call again with confirm=true."
            ),
        }

    if normalized in _running_pipelines:
        return {
            "channel_id": normalized,
            "removed": False,
            "message": (
                f"Pipeline for '{normalized}' is currently running. "
                "Wait for it to finish before removing."
            ),
        }

    async with ingestion_state_repo() as (state_repo, _db):
        soft_deleted = await state_repo.delete_source(normalized)

    return {
        "channel_id": normalized,
        "removed": soft_deleted,
        "message": (
            f"Channel '{normalized}' marked as deleted (soft-delete). "
            "Data preserved; ingestion stopped."
        ),
        "details": {"source": 1 if soft_deleted else 0, "soft_delete": True},
    }


async def _exec_get_llm_config(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.config import llm_config

    return {"config": llm_config.get_all()}


async def _exec_set_llm_config(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.config import llm_config

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    scope = args["scope"]
    provider = args["provider"]
    model = args.get("model")
    temperature = args.get("temperature")
    max_tokens = args.get("max_tokens")
    confirm = bool(args.get("confirm", False))

    if not confirm:
        will_set: dict[str, Any] = {
            "scope": scope,
            "provider": provider,
            "model": model,
        }
        if temperature is not None:
            will_set["temperature"] = temperature
        if max_tokens is not None:
            will_set["max_tokens"] = max_tokens
        return {
            "preview": True,
            "current_config": llm_config.get_all(),
            "will_set": will_set,
            "message": (
                "Preview only. Ask the user to confirm, then call again with confirm=true."
            ),
        }

    try:
        updated = llm_config.set(
            scope=scope,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ValueError as exc:
        return {"error": str(exc), "config": llm_config.get_all()}

    return {
        "success": True,
        "message": (
            f"LLM config updated: scope={scope}, provider={provider}"
            + (f", model={model}" if model else "")
        ),
        "config": updated,
    }


async def _exec_reset_llm_config(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.config import llm_config

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    scope = args.get("scope")
    confirm = bool(args.get("confirm", False))

    if not confirm:
        current = llm_config.get_all()
        return {
            "preview": True,
            "current_overrides": current.get("runtime_overrides", {}),
            "scope_to_reset": scope or "all",
            "message": (
                "Preview only. Ask the user to confirm, then call again with confirm=true."
            ),
        }

    updated = llm_config.clear(scope=scope)
    label = scope or "all scopes"
    return {
        "success": True,
        "message": f"LLM config reset for {label}. Now using .env defaults.",
        "config": updated,
    }


async def _exec_reload_prompts(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.processing.prompt_loader import get_prompt_loader

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    name = args.get("name")
    loader = get_prompt_loader()
    loader.reload(name)
    return {"reloaded": name or "all", "success": True}


async def _exec_register_user(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    async with user_repo() as (repo, _db):
        new_user = await repo.create_user(
            name=args["name"],
            role=args.get("role", "user"),
            max_channels=args.get("max_channels"),
        )
    return {"user_id": new_user.id, "name": new_user.name, "role": new_user.role}


async def _exec_update_user(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    mc_val: Any = ...
    if args.get("reset_max_channels"):
        mc_val = None
    elif args.get("max_channels") is not None:
        mc_val = args["max_channels"]

    async with user_repo() as (repo, _db):
        updated = await repo.update_user(
            args["user_id"],
            name=args.get("name"),
            role=args.get("role"),
            max_channels=mc_val,
        )
    if updated is None:
        return {"error": f"User '{args['user_id']}' not found."}
    return {"success": True, "user_id": updated.id, "name": updated.name, "role": updated.role}


async def _exec_list_users(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    async with user_repo() as (repo, _db):
        all_users = await repo.list_users()
        users = []
        for u in all_users:
            channel_ids = await repo.get_owned_channel_ids(u.id)
            users.append(
                {
                    "id": u.id,
                    "name": u.name,
                    "role": u.role,
                    "max_channels": u.max_channels,
                    "owned_channels_count": len(channel_ids),
                }
            )
    return {"users": users, "count": len(users)}


async def _exec_whoami(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.config import settings as app_settings
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()

    async with user_repo() as (repo, _db):
        channel_ids = await repo.get_owned_channel_ids(user.id)
        db_user = await repo.get_by_id(user.id)

    effective_max = user.max_channels
    if db_user and db_user.max_channels is not None:
        effective_max = db_user.max_channels
    elif db_user:
        effective_max = app_settings.default_max_channels

    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "max_channels": effective_max,
        "owned_channels": channel_ids,
        "owned_channels_count": len(channel_ids),
    }


async def _exec_add_user_auth(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import (
        get_default_admin,
        hash_credential,
        invalidate_user_cache,
    )
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    auth_type = args["auth_type"]
    valid_types = {"api_key", "telegram", "mcp_token"}
    if auth_type not in valid_types:
        return {
            "error": f"Invalid auth_type '{auth_type}'. Must be one of: {', '.join(sorted(valid_types))}"
        }

    identifier = args["identifier"]
    stored = hash_credential(identifier) if auth_type in ("api_key", "mcp_token") else identifier

    async with user_repo() as (repo, _db):
        mapping = await repo.add_auth_mapping(
            args["user_id"],
            auth_type,
            stored,
            args.get("client_name"),
        )

    invalidate_user_cache(auth_type, stored)
    return {"mapping_id": mapping.id, "auth_type": auth_type}


async def _exec_export_channel(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
    bot: Bot | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """Run a channel export and deliver the file via Telegram (F2: Parse-Only).

    Runs synchronously (in-process) — there is no need for the persistent-job
    machinery here because the bot already controls the user's chat session.
    For files within the Telegram 50 MB document limit the file is sent as a
    document via ``FSInputFile``; otherwise we return a download URL hint.
    """
    from datetime import datetime as _dt

    from aiogram.types import FSInputFile

    from tg_parser.api.schemas import ExportFormat, ExportLevel
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.config import settings
    from tg_parser.services.export_service import run_export

    user = current_user or await get_default_admin()

    raw_channel_id = args.get("channel_id")
    if not raw_channel_id:
        return {"error": "channel_id is required"}
    normalized = str(raw_channel_id).lstrip("@")

    level_raw = str(args.get("level", "raw"))
    format_raw = str(args.get("format", "json"))

    try:
        level_enum = ExportLevel(level_raw)
    except ValueError:
        return {
            "error": (
                f"invalid level: {level_raw!r}; expected one of {[lv.value for lv in ExportLevel]}"
            )
        }
    try:
        format_enum = ExportFormat(format_raw)
    except ValueError:
        return {
            "error": (
                f"invalid format: {format_raw!r}; expected one of "
                f"{[fm.value for fm in ExportFormat]}"
            )
        }

    if level_enum == ExportLevel.RAW and not normalized:
        return {"error": "level='raw' requires channel_id"}

    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return {"error": e.message}

    def _parse_iso(value: Any, *, field: str) -> Any:
        if value is None:
            return None
        try:
            return _dt.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return f"__INVALID__:{field}"

    parsed_from = _parse_iso(args.get("from_date"), field="from_date")
    if isinstance(parsed_from, str) and parsed_from.startswith("__INVALID__"):
        return {"error": f"invalid from_date: {args.get('from_date')!r}"}
    parsed_to = _parse_iso(args.get("to_date"), field="to_date")
    if isinstance(parsed_to, str) and parsed_to.startswith("__INVALID__"):
        return {"error": f"invalid to_date: {args.get('to_date')!r}"}

    progress_message_id: int | None = None
    if bot is not None and chat_id is not None:
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⏳ Готовлю экспорт канала <code>{normalized}</code> "
                    f"(level={level_enum.value}, format={format_enum.value})..."
                ),
                parse_mode="HTML",
            )
            progress_message_id = getattr(msg, "message_id", None)
        except Exception:
            logger.warning("bot_export_progress_send_failed", exc_info=True)

    output_dir = Path(settings.output_dir)

    try:
        export_stats = await run_export(
            output_dir=str(output_dir),
            channel_id=normalized,
            level=level_enum,
            format=format_enum,
            from_date=parsed_from,
            to_date=parsed_to,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    if level_enum == ExportLevel.RAW:
        ext = "ndjson" if format_enum == ExportFormat.NDJSON else "json"
        export_file = output_dir / f"raw_messages.{ext}"
    elif format_enum == ExportFormat.NDJSON or level_enum == ExportLevel.PROCESSED:
        export_file = output_dir / "kb_entries.ndjson"
    else:
        export_file = output_dir / "topics.json"

    if not export_file.exists():
        return {"error": (f"Export produced no file: {export_file.name} (stats: {export_stats})")}

    file_size = export_file.stat().st_size
    file_size_mb = round(file_size / (1024 * 1024), 2)

    summary: dict[str, Any] = {
        "channel_id": normalized,
        "level": level_enum.value,
        "format": format_enum.value,
        "file_name": export_file.name,
        "file_size": file_size,
        "file_size_mb": file_size_mb,
        "stats": export_stats,
    }

    if progress_message_id is not None and bot is not None and chat_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=progress_message_id)
        except Exception:
            logger.debug("bot_export_progress_delete_failed", exc_info=True)

    if file_size > TG_BOT_DOCUMENT_LIMIT_BYTES:
        summary["sent"] = False
        summary["reason"] = "file_too_large"
        summary["limit_bytes"] = TG_BOT_DOCUMENT_LIMIT_BYTES
        summary["message"] = (
            f"Файл экспорта ({file_size_mb} MB) превышает лимит Telegram "
            f"(50 MB). Используйте CLI или API для скачивания: путь на сервере "
            f"{export_file}."
        )
        return summary

    if bot is None or chat_id is None:
        summary["sent"] = False
        summary["reason"] = "no_bot_context"
        summary["message"] = (
            f"Бот не имеет контекста чата для отправки файла; экспорт сохранён в {export_file}."
        )
        return summary

    try:
        await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(str(export_file), filename=export_file.name),
            caption=(f"📎 {export_file.name} (level={level_enum.value}, {file_size_mb} MB)"),
        )
        summary["sent"] = True
        summary["message"] = (
            f"Файл {export_file.name} отправлен в чат "
            f"({file_size_mb} MB, level={level_enum.value})."
        )
    except Exception as exc:
        logger.exception("bot_export_send_document_failed")
        summary["sent"] = False
        summary["reason"] = "send_failed"
        summary["message"] = f"Не удалось отправить файл: {exc}"

    return summary


async def _exec_subscribe_digest(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
    bot: Bot | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """Create a new digest subscription and register it with the scheduler.

    The subscription is owned by ``current_user`` and delivered to the
    current chat (``chat_id`` from the message context). Each ``channel_id``
    must be accessible by the user (``assert_channel_access``). Cron
    expression and timezone are validated by the scheduler before persisting
    so an invalid spec yields a clean error rather than a half-saved row.
    """
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.config import settings
    from tg_parser.domain.models import DigestFormat, DigestSubscription
    from tg_parser.services.background_scheduler import (
        get_scheduler,
        register_digest_subscription,
    )
    from tg_parser.services.db_context import digest_subscription_repo

    user = current_user or await get_default_admin()

    if chat_id is None:
        return {"error": "chat_id is required (call from a chat context)"}

    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}

    raw_channels = args.get("channel_ids") or []
    if not isinstance(raw_channels, list) or not raw_channels:
        return {"error": "channel_ids must be a non-empty list"}
    channel_ids = [str(c).lstrip("@").strip() for c in raw_channels if str(c).strip()]
    if not channel_ids:
        return {"error": "channel_ids must contain at least one channel"}

    for cid in channel_ids:
        try:
            await assert_channel_access(user, cid)
        except PermissionDenied as exc:
            return {"error": exc.message, "channel_id": cid}

    cron_expression = (args.get("cron_expression") or "0 9 * * *").strip()
    timezone = (args.get("timezone") or settings.digest_default_timezone or "UTC").strip()
    format_raw = (args.get("format") or "summary").strip()
    language = (args.get("language") or "ru").strip()

    try:
        format_enum = DigestFormat(format_raw)
    except ValueError:
        return {
            "error": (
                f"invalid format: {format_raw!r}; expected one of "
                f"{[fm.value for fm in DigestFormat]}"
            )
        }

    import uuid as _uuid
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    subscription = DigestSubscription(
        id=str(_uuid.uuid4()),
        owner_id=user.id,
        chat_id=chat_id,
        name=name,
        channel_ids=channel_ids,
        cron_expression=cron_expression,
        timezone=timezone,
        format=format_enum,
        language=language,
        is_active=True,
        last_sent_at=None,
        last_digest_cursor=None,
        created_at=_dt.now(_UTC),
        updated_at=_dt.now(_UTC),
    )

    try:
        register_digest_subscription(subscription, get_scheduler())
    except ValueError as exc:
        return {"error": f"cron/timezone validation failed: {exc}"}

    try:
        async with digest_subscription_repo() as (repo, _db):
            created = await repo.create(subscription)
    except Exception as exc:
        from tg_parser.services.background_scheduler import unregister_digest_subscription

        unregister_digest_subscription(subscription.id)
        logger.exception("subscribe_digest_persist_failed")
        return {"error": f"failed to persist subscription: {exc}"}

    if bot is not None:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"📰 Подписка <b>{created.name}</b> создана. "
                    f"Расписание: <code>{created.cron_expression}</code> ({created.timezone}). "
                    f"Каналов: {len(created.channel_ids)}."
                ),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("subscribe_digest_confirmation_failed", exc_info=True)

    return {
        "subscription_id": created.id,
        "name": created.name,
        "chat_id": created.chat_id,
        "channel_ids": created.channel_ids,
        "cron_expression": created.cron_expression,
        "timezone": created.timezone,
        "format": created.format.value,
        "language": created.language,
        "is_active": created.is_active,
    }


async def _exec_list_digests(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    """Return the caller's subscriptions (admins see all)."""
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import digest_subscription_repo

    user = current_user or await get_default_admin()

    async with digest_subscription_repo() as (repo, _db):
        if user.is_admin:
            subs = await repo.list_all()
        else:
            subs = await repo.list_by_owner(user.id)

    return {
        "count": len(subs),
        "subscriptions": [
            {
                "id": s.id,
                "owner_id": s.owner_id,
                "chat_id": s.chat_id,
                "name": s.name,
                "channel_ids": s.channel_ids,
                "cron_expression": s.cron_expression,
                "timezone": s.timezone,
                "format": s.format.value,
                "language": s.language,
                "is_active": s.is_active,
                "last_sent_at": s.last_sent_at.isoformat() if s.last_sent_at else None,
                "last_digest_cursor": (
                    s.last_digest_cursor.isoformat() if s.last_digest_cursor else None
                ),
            }
            for s in subs
        ],
    }


async def _exec_unsubscribe_digest(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    """Delete a subscription by id (owner-only for non-admins)."""
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.background_scheduler import unregister_digest_subscription
    from tg_parser.services.db_context import digest_subscription_repo

    user = current_user or await get_default_admin()
    sub_id = (args.get("subscription_id") or "").strip()
    if not sub_id:
        return {"error": "subscription_id is required"}

    async with digest_subscription_repo() as (repo, _db):
        existing = await repo.get(sub_id)
        if existing is None:
            return {"error": f"subscription {sub_id!r} not found", "subscription_id": sub_id}
        if not user.is_admin and existing.owner_id != user.id:
            return {"error": "permission denied", "subscription_id": sub_id}
        deleted = await repo.delete(sub_id)

    if deleted:
        unregister_digest_subscription(sub_id)
        return {"subscription_id": sub_id, "deleted": True}
    return {"subscription_id": sub_id, "deleted": False, "error": "delete failed"}


async def _exec_remove_user_auth(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    async with user_repo() as (repo, _db):
        removed = await repo.remove_auth_mapping(args["mapping_id"])

    if not removed:
        return {"error": f"Mapping '{args['mapping_id']}' not found."}
    return {"success": True, "message": f"Auth mapping '{args['mapping_id']}' removed."}


# ---------------------------------------------------------------------------
# F11 — Topic Watchlist executors
# ---------------------------------------------------------------------------


def _watch_interest_to_dict(interest: Any) -> dict[str, Any]:
    return {
        "interest_id": interest.id,
        "user_id": interest.user_id,
        "chat_id": interest.chat_id,
        "title": interest.title,
        "description": interest.description,
        "keywords": list(interest.keywords),
        "exclude_keywords": list(interest.exclude_keywords),
        "channel_ids": list(interest.channel_ids),
        "threshold": interest.threshold,
        "notify_mode": interest.notify_mode.value,
        "is_active": interest.is_active,
        "last_checked_at": (
            interest.last_checked_at.isoformat() if interest.last_checked_at else None
        ),
        "last_match_at": interest.last_match_at.isoformat() if interest.last_match_at else None,
    }


def _watch_match_to_dict(match: Any) -> dict[str, Any]:
    return {
        "id": match.id,
        "interest_id": match.interest_id,
        "source_ref": match.source_ref,
        "channel_id": match.channel_id,
        "keyword_score": match.keyword_score,
        "semantic_score": match.semantic_score,
        "combined_score": match.combined_score,
        "notified": match.notified,
        "created_at": match.created_at.isoformat() if match.created_at else None,
    }


async def _exec_subscribe_watchlist(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
    bot: Bot | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    """Create a F11 Topic Watchlist interest from the bot context.

    The chat_id is taken from the message context (so the bot delivers
    notifications back to the same chat the user typed from). Each
    channel_id is checked via ``assert_channel_access`` so non-admins
    cannot subscribe to channels they do not own.
    """
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    user = current_user or await get_default_admin()

    if chat_id is None:
        return {"error": "chat_id is required (call from a chat context)"}

    title = (args.get("title") or "").strip()
    if not title:
        return {"error": "title is required"}

    raw_channels = args.get("channel_ids") or []
    if not isinstance(raw_channels, list) or not raw_channels:
        return {"error": "channel_ids must be a non-empty list"}
    channel_ids = [str(c).lstrip("@").strip() for c in raw_channels if str(c).strip()]
    if not channel_ids:
        return {"error": "channel_ids must contain at least one channel"}

    threshold = args.get("threshold")
    if threshold is None:
        threshold = 0.6
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return {"error": f"threshold must be a number, got {threshold!r}"}
    if threshold < 0.0 or threshold > 1.0:
        return {"error": f"threshold must be in [0.0, 1.0], got {threshold}"}

    for cid in channel_ids:
        try:
            await assert_channel_access(user, cid)
        except PermissionDenied as exc:
            return {"error": exc.message, "channel_id": cid}

    try:
        async with watchlist_repos() as (
            interest_repo,
            match_repo,
            processed_doc_repo,
            embedding_repo,
            _db,
        ):
            service = make_watchlist_service(
                interest_repo=interest_repo,
                match_repo=match_repo,
                processed_doc_repo=processed_doc_repo,
                embedding_repo=embedding_repo,
            )
            try:
                created = await service.create_interest(
                    user_id=user.id,
                    chat_id=chat_id,
                    title=title,
                    channel_ids=channel_ids,
                    keywords=list(args.get("keywords") or []),
                    description=args.get("description"),
                    exclude_keywords=list(args.get("exclude_keywords") or []),
                    threshold=threshold,
                )
            finally:
                await service.aclose()
    except Exception as exc:
        logger.exception("subscribe_watchlist_persist_failed")
        return {"error": f"failed to persist interest: {exc}"}

    if bot is not None:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🔔 Watchlist <b>{created.title}</b> создан.\n"
                    f"Каналов: {len(created.channel_ids)}, threshold: {created.threshold}."
                ),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("subscribe_watchlist_confirmation_failed", exc_info=True)

    return _watch_interest_to_dict(created)


async def _exec_list_watchlists(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    """Return the caller's interests (admins see all)."""
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import watchlist_repos

    user = current_user or await get_default_admin()

    async with watchlist_repos() as (
        interest_repo,
        _match_repo,
        _proc_repo,
        _emb_repo,
        _db,
    ):
        if user.is_admin:
            interests = await interest_repo.list_all()
        else:
            interests = await interest_repo.list_for_user(user.id)

    return {
        "count": len(interests),
        "interests": [_watch_interest_to_dict(i) for i in interests],
    }


async def _exec_unsubscribe_watchlist(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    """Soft-delete an interest by id (owner-only for non-admins)."""
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    user = current_user or await get_default_admin()
    interest_id = (args.get("interest_id") or "").strip()
    if not interest_id:
        return {"error": "interest_id is required"}

    async with watchlist_repos() as (
        interest_repo,
        match_repo,
        processed_doc_repo,
        embedding_repo,
        _db,
    ):
        service = make_watchlist_service(
            interest_repo=interest_repo,
            match_repo=match_repo,
            processed_doc_repo=processed_doc_repo,
            embedding_repo=embedding_repo,
            with_embedding_client=False,
        )
        try:
            deleted, error = await service.delete_interest_for_user(
                interest_id,
                requesting_user_id=user.id,
                is_admin=user.is_admin,
            )
        finally:
            await service.aclose()

    if deleted:
        return {"interest_id": interest_id, "deleted": True}
    return {
        "interest_id": interest_id,
        "deleted": False,
        "error": error or "delete failed",
    }


async def _exec_get_watchlist_matches(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    """Return saved matches for an interest (owner-only for non-admins)."""
    from datetime import datetime as _dt

    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    user = current_user or await get_default_admin()
    interest_id = (args.get("interest_id") or "").strip()
    if not interest_id:
        return {"error": "interest_id is required"}

    parsed_since: Any = None
    since_iso = (args.get("since_iso") or "").strip()
    if since_iso:
        try:
            parsed_since = _dt.fromisoformat(since_iso)
        except ValueError:
            return {"error": f"invalid since_iso: {since_iso!r}"}

    async with watchlist_repos() as (
        interest_repo,
        match_repo,
        processed_doc_repo,
        embedding_repo,
        _db,
    ):
        service = make_watchlist_service(
            interest_repo=interest_repo,
            match_repo=match_repo,
            processed_doc_repo=processed_doc_repo,
            embedding_repo=embedding_repo,
            with_embedding_client=False,
        )
        try:
            interest = await service.get_interest(interest_id)
            if interest is None:
                return {"error": f"interest {interest_id!r} not found"}
            if not user.is_admin and interest.user_id != user.id:
                return {"error": "permission denied", "interest_id": interest_id}
            matches = await service.get_matches(interest_id, since=parsed_since)
        finally:
            await service.aclose()

    return {
        "count": len(matches),
        "interest_id": interest_id,
        "matches": [_watch_match_to_dict(m) for m in matches],
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
    "add_channel": _exec_add_channel,
    "remove_channel": _exec_remove_channel,
    "get_llm_config": _exec_get_llm_config,
    "set_llm_config": _exec_set_llm_config,
    "reset_llm_config": _exec_reset_llm_config,
    "reload_prompts": _exec_reload_prompts,
    "register_user": _exec_register_user,
    "update_user": _exec_update_user,
    "list_users": _exec_list_users,
    "whoami": _exec_whoami,
    "add_user_auth": _exec_add_user_auth,
    "remove_user_auth": _exec_remove_user_auth,
    "export_channel": _exec_export_channel,
    "subscribe_digest": _exec_subscribe_digest,
    "list_digests": _exec_list_digests,
    "unsubscribe_digest": _exec_unsubscribe_digest,
    "subscribe_watchlist": _exec_subscribe_watchlist,
    "list_watchlists": _exec_list_watchlists,
    "unsubscribe_watchlist": _exec_unsubscribe_watchlist,
    "get_watchlist_matches": _exec_get_watchlist_matches,
}
