"""
MCP Server for TG_parser Knowledge Base (P6b, D1).

Exposes search, Q&A, topic navigation, and channel statistics
as MCP tools/resources for AI agents (Claude Desktop, Cursor, etc.).

Transports:
    - stdio (default) — for local development and Claude Desktop
    - streamable-http — for production deployment on remote servers

Usage:
    python -m tg_parser.mcp_server          # stdio
    tg-parser mcp                           # stdio (via CLI)
    tg-parser mcp --transport streamable-http --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_args

import structlog
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
from pydantic import AnyHttpUrl, BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Reject unknown tool parameters instead of silently ignoring them.
# Must be set before @mcp.tool() decorators run (they create Pydantic
# subclasses of ArgModelBase that inherit this config).
ArgModelBase.model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

_MCP_INSTRUCTIONS = (
    "MCP server for managing and searching a Telegram-channel knowledge base.\n\n"
    "Channel Management: "
    "add_channel to connect new channels, pause_channel/resume_channel to control them, "
    "remove_channel to permanently delete a channel and all its data. "
    "trigger_pipeline to start processing, get_pipeline_status to monitor progress.\n\n"
    "Search & Q&A: "
    "search_knowledge_base for hybrid search (mode=semantic|keyword|hybrid; "
    "default hybrid), ask_question for topic-weighted RAG Q&A (same mode param).\n\n"
    "Navigation: "
    "list_topics / get_topic_details for topic navigation, "
    "list_channels for channel overview, get_document for full document content.\n\n"
    "Cross-channel Analytics: "
    "get_cross_channel_stats for topic counts, coverage and keyword overlaps, "
    "get_related_topics to find linked topics across channels.\n\n"
    "Channel Export (F2 Parse-Only): "
    "export_channel(channel_id, level=raw|processed|full, format=json|ndjson, "
    "from_date?, to_date?) creates a background export job. Use level='raw' "
    "for pure parse-only output of raw Telegram messages (no LLM); "
    "'processed' for KnowledgeBaseEntry[]; 'full' (legacy) for processed + "
    "topics. Poll get_export_status(job_id) until completed, then fetch via "
    "download_url. raw_payload is never included (privacy invariant).\n\n"
    "LLM Configuration (runtime switching without restart): "
    "get_llm_config to view current provider/model per stage and available providers. "
    "set_llm_config to switch provider/model — scopes: global, processing, topicization, rag, digest, resummarize; "
    "providers: openai, anthropic, gemini, ollama. "
    "reset_llm_config to revert runtime overrides to .env defaults. "
    "Resolution priority: stage override → global override → stage .env → global .env. "
    "Changes are immediate for new requests; in-flight requests finish with the old provider. "
    "Changes are NOT persisted — restart reverts to .env defaults. "
    "Always call get_llm_config first to see what is available.\n\n"
    "User Management (admin only unless noted): "
    "register_user to create users, update_user to change role/name/max_channels, "
    "list_users to see all users with channel counts. "
    "whoami (any user) to see own profile. "
    "add_user_auth / remove_user_auth to manage auth credentials.\n\n"
    "Scheduled Digests (F6): "
    "subscribe_digest(name, channel_ids, chat_id, cron_expression?, timezone?, "
    "format?, language?) creates a recurring digest delivered to chat_id by "
    "the bot scheduler. cron_expression is the standard 5-field syntax "
    "(default '0 9 * * *'), timezone is an IANA name (default 'UTC'), "
    "format is 'summary'|'bullets'|'detailed' (default 'summary'). "
    "list_digests returns the caller's subscriptions (admins see all). "
    "unsubscribe_digest(subscription_id) deletes a subscription (owner-only "
    "for non-admins). Channels in channel_ids must be accessible to the "
    "caller. The 'digest' LLM stage is configurable via DIGEST_LLM_PROVIDER "
    "/ DIGEST_LLM_MODEL or set_llm_config(scope='digest', ...).\n\n"
    "Topic Watchlist (F11): "
    "subscribe_watchlist(title, channel_ids, chat_id, keywords?, description?, "
    "exclude_keywords?, threshold?) creates a persistent thematic alert. After "
    "every incremental pipeline tick, new ProcessedDocuments are scored against "
    "every active interest using a hybrid keyword + semantic match (weights 0.4 "
    "/ 0.6). Matches with combined score >= threshold (default 0.6) are stored "
    "in watch_matches and pushed to chat_id via the bot. "
    "list_watchlists returns the caller's interests (admins see all). "
    "unsubscribe_watchlist(interest_id) soft-deletes the interest while "
    "preserving its match history. "
    "get_watchlist_matches(interest_id, since_iso?) returns saved matches with "
    "scores. Channels in channel_ids must be accessible to the caller. "
    "exclude_keywords act as a hard filter (any token match zeroes the score "
    "for that document). When the bot has been blocked by chat_id, the orphan "
    "interest is auto-deactivated to stop retry storms.\n\n"
    "Evolving Topic Summaries (F5-C): "
    "get_topic_versions(topic_id, limit?) returns the audit trail of past "
    "summaries for a topic — each successful re-summarize stores the "
    "previous TopicCard.summary / scope_in / scope_out plus LLM "
    "provenance. Visibility mirrors get_topic_details (access to at least "
    "one of the topic's sources). force_resummarize(topic_id) is an "
    "admin-only manual trigger that bypasses the N-threshold counter "
    "(advisory-lock applies — concurrent resummarize returns "
    "status='locked'). The scheduler hook itself runs after every "
    "incremental tick when new_items_since_last_summary >= "
    "RESUMMARIZE_TRIGGER_N.\n\n"
    "Prompt Management: reload_prompts to reload YAML prompt files without restart. "
    "Prompts live in prompts/ directory (processing, topicization, rag, bot, merge, "
    "incremental_discover, resummarize). Each YAML has system.prompt, user.template, "
    "and model settings. Custom directory via PROMPTS_DIR env var. "
    "Per-stage LLM: RAG_LLM_PROVIDER/RAG_LLM_MODEL env vars."
)


# ---------------------------------------------------------------------------
# D1b: Lifespan — Database singleton lifecycle for all transports
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _mcp_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Initialize Database singleton on startup, close on shutdown."""
    from tg_parser.storage.sqlalchemy import Database

    db = Database.get_instance()
    await db.init()
    try:
        yield {}
    finally:
        await Database.close_instance()


# ---------------------------------------------------------------------------
# D1c: Bearer-token authentication
# ---------------------------------------------------------------------------


class BearerTokenVerifier(TokenVerifier):
    """Bearer-token verifier: DB lookup first, then static mapping fallback."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        from tg_parser.auth.resolvers import hash_credential, resolve_user_by_auth

        hashed = hash_credential(token)
        user = await resolve_user_by_auth("mcp_token", hashed)
        if user is not None:
            return AccessToken(token=token, client_id=str(user.id), scopes=[])

        # Fallback to static token mapping (backward compat -> admin)
        client = self._tokens.get(token)
        if not client:
            return None
        return AccessToken(token=token, client_id=client, scopes=[])


# ---------------------------------------------------------------------------
# D1d: Factory function — creates FastMCP with settings-driven config
# ---------------------------------------------------------------------------


def create_mcp_server() -> FastMCP:
    """Build FastMCP instance from application settings."""
    from tg_parser.config import settings

    kwargs: dict[str, Any] = {
        "name": "TG_parser Knowledge Base",
        "instructions": _MCP_INSTRUCTIONS,
        "host": settings.mcp_host,
        "port": settings.mcp_port,
        "streamable_http_path": settings.mcp_path,
        "stateless_http": True,
        "json_response": True,
        "lifespan": _mcp_lifespan,
    }

    if settings.mcp_auth_enabled and settings.mcp_auth_tokens:
        kwargs["token_verifier"] = BearerTokenVerifier(settings.mcp_auth_tokens)
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(f"http://{settings.mcp_host}:{settings.mcp_port}"),
            resource_server_url=AnyHttpUrl(f"http://{settings.mcp_host}:{settings.mcp_port}"),
        )

    return FastMCP(**kwargs)


mcp = create_mcp_server()


async def resolve_mcp_user(client_id: str | None = None):
    """Resolve MCP client_id to CurrentUser.

    - None (stdio mode) -> default admin
    - UUID client_id from DB-resolved token -> look up user by id
    - Legacy string client_id -> default admin
    """
    from tg_parser.auth.resolvers import get_default_admin

    if client_id is None:
        return await get_default_admin()

    try:
        from tg_parser.services.db_context import user_repo

        async with user_repo() as (repo, _db):
            db_user = await repo.get_by_id(client_id)
        if db_user is not None:
            from tg_parser.auth.models import CurrentUser
            from tg_parser.config import settings

            if db_user.role == "admin":
                allowed = None
            else:
                async with user_repo() as (repo2, _db2):
                    allowed = await repo2.get_owned_channel_ids(db_user.id)
            max_ch = (
                db_user.max_channels
                if db_user.max_channels is not None
                else settings.default_max_channels
            )
            return CurrentUser(
                id=db_user.id,
                name=db_user.name,
                role=db_user.role,
                allowed_channel_ids=allowed,
                max_channels=max_ch,
            )
    except Exception:
        logger.debug("resolve_mcp_user: DB lookup failed, using admin", client_id=client_id)

    return await get_default_admin()


# ---------------------------------------------------------------------------
# Health endpoint (exposed without auth for monitoring / Docker healthcheck)
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def mcp_health_check(request):
    from starlette.responses import JSONResponse

    db_status = "unknown"
    try:
        from tg_parser.storage.sqlalchemy import Database

        db = Database.get_instance()
        if db._initialized and db.processing_storage_engine:
            from sqlalchemy import text

            async with db.processing_storage_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_status = "ok"
        else:
            db_status = "not_initialized"
    except Exception as e:
        db_status = f"error: {e}"

    return JSONResponse(
        {"status": "ok" if db_status == "ok" else "degraded", "database": db_status},
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint for MCP service
# ---------------------------------------------------------------------------


@mcp.custom_route("/metrics", methods=["GET"])
async def mcp_metrics(request):
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.responses import Response

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
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
    summary_version: int = 1
    last_summarized_at: str | None = None
    new_items_since_last_summary: int = 0


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


class CrossChannelStatsResult(BaseModel):
    total_documents: int | None = None
    total_topics: int | None = None
    channels: list[dict[str, Any]] | None = None
    keyword_overlaps: list[dict[str, Any]] | None = None
    overlap_count: int | None = None
    # Single-channel fields
    channel_id: str | None = None
    processed_documents: int | None = None
    singleton_count: int | None = None
    cluster_count: int | None = None
    topics_count: int | None = None
    coverage_percent: float | None = None
    all_keywords: list[str] | None = None
    related_channels: list[dict[str, Any]] | None = None
    error: str | None = None


class RelatedTopicItem(BaseModel):
    topic_id: str
    title: str
    channel_id: str
    similarity_score: float
    shared_keywords: list[str]


# ---------------------------------------------------------------------------
# F4 Phase 5: User Management result models
# ---------------------------------------------------------------------------


class RegisterUserResult(BaseModel):
    success: bool
    user_id: str | None
    message: str


class UpdateUserResult(BaseModel):
    success: bool
    message: str


class UserInfo(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int | None
    owned_channels_count: int


class ListUsersResult(BaseModel):
    success: bool
    users: list[UserInfo]
    message: str = ""


class WhoamiResult(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int
    owned_channels: list[str]
    owned_channels_count: int


class AddUserAuthResult(BaseModel):
    success: bool
    mapping_id: str | None
    message: str


class RemoveUserAuthResult(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# F2: Parse-Only Export — result models
# ---------------------------------------------------------------------------


class ExportChannelResult(BaseModel):
    """Result of submitting an export job (F2: Parse-Only Export)."""

    job_id: str
    status: str
    channel_id: str
    level: str
    format: str
    download_url: str | None = None
    message: str


class ExportStatusResult(BaseModel):
    """Status of an export job."""

    job_id: str
    status: str
    channel_id: str | None = None
    level: str
    format: str
    download_url: str | None = None
    file_size: int | None = None
    message: str


# ---------------------------------------------------------------------------
# F6: Scheduled Digests — result models
# ---------------------------------------------------------------------------


class DigestSubscriptionInfo(BaseModel):
    """Public projection of a ``DigestSubscription``."""

    id: str
    owner_id: str
    chat_id: int
    name: str
    channel_ids: list[str]
    cron_expression: str
    timezone: str
    format: str
    language: str
    is_active: bool
    last_sent_at: str | None = None
    last_digest_cursor: str | None = None


class SubscribeDigestResult(BaseModel):
    """Result of ``subscribe_digest``."""

    success: bool
    subscription: DigestSubscriptionInfo | None = None
    message: str


class ListDigestsResult(BaseModel):
    """Result of ``list_digests``."""

    count: int
    subscriptions: list[DigestSubscriptionInfo]


class UnsubscribeDigestResult(BaseModel):
    """Result of ``unsubscribe_digest``."""

    success: bool
    subscription_id: str
    message: str


# ---------------------------------------------------------------------------
# F11: Topic Watchlist — result models
# ---------------------------------------------------------------------------


class WatchInterestInfo(BaseModel):
    """Public projection of a ``WatchInterest``."""

    id: str
    user_id: str
    chat_id: int
    title: str
    description: str | None = None
    keywords: list[str]
    exclude_keywords: list[str]
    channel_ids: list[str]
    threshold: float
    notify_mode: str
    is_active: bool
    last_checked_at: str | None = None
    last_match_at: str | None = None
    created_at: str | None = None


class WatchMatchInfo(BaseModel):
    """Public projection of a ``WatchMatch``."""

    id: int
    interest_id: str
    source_ref: str
    channel_id: str
    keyword_score: float
    semantic_score: float
    combined_score: float
    notified: bool
    created_at: str | None = None


class SubscribeWatchlistResult(BaseModel):
    """Result of ``subscribe_watchlist``."""

    success: bool
    interest: WatchInterestInfo | None = None
    message: str


class ListWatchlistsResult(BaseModel):
    """Result of ``list_watchlists``."""

    count: int
    interests: list[WatchInterestInfo]


class UnsubscribeWatchlistResult(BaseModel):
    """Result of ``unsubscribe_watchlist``."""

    success: bool
    interest_id: str
    message: str


class GetWatchlistMatchesResult(BaseModel):
    """Result of ``get_watchlist_matches``."""

    count: int
    interest_id: str
    matches: list[WatchMatchInfo]


# ---------------------------------------------------------------------------
# T2: MCP Tools — Search & Q&A
# ---------------------------------------------------------------------------


def _validate_search_mode(mode: str) -> str:
    """Validate ``mode`` against ``SearchMode`` literal from retrieval_service.

    Centralised to keep the single source of truth inside the service module and
    to avoid duplicating the string literals in MCP / API / CLI layers.
    """
    from tg_parser.services.retrieval_service import SearchMode

    valid = set(get_args(SearchMode))
    if mode not in valid:
        raise ValueError(f"invalid mode: {mode!r}; expected one of {sorted(valid)}")
    return mode


@mcp.tool()
async def search_knowledge_base(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    mode: str = "hybrid",
    ctx: Context | None = None,
) -> list[SearchResultItem]:
    """Hybrid search across the Telegram knowledge base.
    Returns documents ranked by relevance with scores and summaries.
    Use this to find specific information in channel posts.

    Args:
        query: Natural-language search query.
        channel_id: Optional channel filter (e.g. "labdiagnostica_logical").
        limit: Maximum number of results (default 10).
        mode: Retrieval strategy — 'semantic' (pgvector cosine), 'keyword'
            (FTS ts_rank_cd), or 'hybrid' (RRF fusion). Defaults to 'hybrid'.
    """
    _validate_search_mode(mode)
    if not query or not query.strip():
        return []

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    from tg_parser.services.retrieval_service import search

    results = await search(
        query=query,
        channel_id=channel_id,
        limit=limit,
        allowed_channel_ids=user.allowed_channel_ids,
        mode=mode,
    )
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
    mode: str = "hybrid",
    ctx: Context | None = None,
) -> AnswerResultItem:
    """Ask a question about Telegram channel content.
    Uses RAG: retrieves relevant documents and generates a topic-weighted
    answer with an LLM. Returns the answer text with source references.

    Args:
        question: Question in natural language.
        channel_id: Optional channel filter.
        mode: Retrieval strategy — 'semantic', 'keyword', or 'hybrid' (default).
    """
    _validate_search_mode(mode)
    if not question or not question.strip():
        return AnswerResultItem(
            answer="Please provide a non-empty question.", sources=[], model=None
        )

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    from tg_parser.services.retrieval_service import answer

    result = await answer(
        question=question,
        channel_id=channel_id,
        allowed_channel_ids=user.allowed_channel_ids,
        mode=mode,
    )
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
    ctx: Context | None = None,
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

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

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

        summaries: list[TopicSummary] = []
        for card in page:
            bundle = bundle_map.get(card.id)
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
async def get_topic_details(topic_id: str, ctx: Context | None = None) -> TopicDetail | str:
    """Get full details of a topic: scope, anchors, related topics, and bundle items.
    Use this after list_topics to dive deeper into a specific topic.

    Args:
        topic_id: The topic ID (e.g. 'topic:tg:channel:post:123')."""
    from tg_parser.services.db_context import processing_repos
    from tg_parser.services.topic_linking_service import get_related_topics_for

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    async with processing_repos() as (_proc_repo, topic_card_repo, topic_bundle_repo, _db):
        card = await topic_card_repo.get_by_id(topic_id)
        if card is None:
            return f"Topic not found: {topic_id}"

        if user.allowed_channel_ids is not None:
            if not any(s in user.allowed_channel_ids for s in card.sources):
                return f"No access to topic: {topic_id}"

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
            logger.warning("failed_to_enrich_related_topics", topic_id=topic_id, exc_info=True)

        return TopicDetail(
            id=card.id,
            title=card.title,
            type=card.type.value,
            summary=card.summary,
            scope_in=card.scope_in,
            scope_out=card.scope_out,
            anchors=[
                {**a.model_dump(mode="json"), "source_ref": a.anchor_ref} for a in card.anchors
            ],
            sources=card.sources,
            tags=card.tags,
            related_topics=related_topics if related_topics else None,
            items=items,
            summary_version=card.summary_version,
            last_summarized_at=(
                card.last_summarized_at.isoformat() if card.last_summarized_at else None
            ),
            new_items_since_last_summary=card.new_items_since_last_summary,
        )


@mcp.tool()
async def list_channels(ctx: Context | None = None) -> list[ChannelSummary]:
    """List all connected Telegram channels with statistics.
    Shows raw/processed message counts, topics, and coverage percentage."""
    from tg_parser.services.channel_service import get_all_channel_stats

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    all_stats = await get_all_channel_stats(allowed_channel_ids=user.allowed_channel_ids)
    return [
        ChannelSummary(
            channel_id=s["channel_id"],
            channel_username=s.get("channel_username"),
            status=s["status"],
            raw_messages=s["raw_messages"],
            processed_documents=s["processed_documents"],
            topics_count=s["topics_count"],
            coverage_percent=s["coverage_percent"],
        )
        for s in all_stats
    ]


@mcp.tool()
async def get_document(source_ref: str, ctx: Context | None = None) -> DocumentDetail | str:
    """Get the full content of a processed document by its source reference.
    Source refs have format: tg:channel_id:post:123 or tg:channel_id:comment:456.

    Args:
        source_ref: Document source reference."""
    from tg_parser.services.db_context import processing_repos

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    async with processing_repos() as (proc_repo, _tc, _tb, _db):
        doc = await proc_repo.get_by_source_ref(source_ref)

    if doc is None:
        return f"Document not found: {source_ref}"

    if user.allowed_channel_ids is not None and doc.channel_id not in user.allowed_channel_ids:
        return f"No access to document: {source_ref}"

    return DocumentDetail(
        id=doc.id,
        source_ref=doc.source_ref,
        channel_id=doc.channel_id,
        text_clean=doc.text_clean,
        summary=doc.summary,
        topics=doc.topics,
    )


# ---------------------------------------------------------------------------
# T7: MCP Tools — Cross-channel Analytics
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_related_topics(topic_id: str, ctx: Context | None = None) -> list[RelatedTopicItem]:
    """Get topics from other channels that are related to the given topic.

    Requires link-topics to have been run first (CLI: tg-parser link-topics).
    Returns related topics sorted by similarity score.

    Args:
        topic_id: The topic ID to find related topics for."""
    from tg_parser.services.topic_linking_service import get_related_topics_for

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    related = await get_related_topics_for(
        topic_id,
        allowed_channel_ids=user.allowed_channel_ids,
    )
    return [
        RelatedTopicItem(
            topic_id=r["topic_id"],
            title=r["title"],
            channel_id=r["channel_id"],
            similarity_score=round(r["similarity_score"], 4),
            shared_keywords=r["shared_keywords"],
        )
        for r in related
    ]


@mcp.tool()
async def get_cross_channel_stats(
    channel_id: str | None = None,
    ctx: Context | None = None,
) -> CrossChannelStatsResult:
    """Get cross-channel analytics: topic counts, coverage, and keyword overlaps.

    Without channel_id: returns aggregated stats for all channels with keyword
    intersections (which topics appear in 2+ channels).

    With channel_id: returns detailed stats for a specific channel including
    all keywords and related channels by shared keywords.

    Args:
        channel_id: Optional channel filter for single-channel detail view."""
    from tg_parser.services.analytics_service import get_cross_channel_analytics

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    result = await get_cross_channel_analytics(
        channel_id=channel_id,
        allowed_channel_ids=user.allowed_channel_ids,
    )
    return CrossChannelStatsResult(**result)


# ---------------------------------------------------------------------------
# T5: MCP Tools — Channel Management
# ---------------------------------------------------------------------------


@mcp.tool()
async def add_channel(
    channel_id: str,
    channel_username: str | None = None,
    include_comments: bool = False,
    batch_size: int = 100,
    ctx: Context | None = None,
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
    from tg_parser.auth.ownership import PermissionDenied, check_channel_limit
    from tg_parser.services.channel_placeholders import (
        blocked_message,
        is_blocked_placeholder,
    )
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.storage.ports import Source

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    normalized = channel_id.lstrip("@")

    # M2 (BUG-002): symmetrical guard with the bot tool. Reject any
    # known-placeholder channel id before any DB lookup, so the MCP
    # surface cannot be coerced into materialising a hallucinated
    # placeholder either. See `tg_parser/services/channel_placeholders.py`.
    if is_blocked_placeholder(normalized):
        return AddChannelResult(
            channel_id=normalized,
            source_id=normalized,
            status="rejected",
            created=False,
            message=blocked_message(normalized),
        )

    async with ingestion_state_repo() as (state_repo, _db):
        existing = await state_repo.get_source(normalized)

        if existing is None:
            if user.is_admin:
                user_sources = await state_repo.list_sources(status="active")
            else:
                user_sources = await state_repo.list_sources(status="active", owner_id=user.id)
            try:
                check_channel_limit(user, len(user_sources))
            except PermissionDenied as e:
                return AddChannelResult(
                    channel_id=normalized,
                    source_id=normalized,
                    status="rejected",
                    created=False,
                    message=e.message,
                )

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
async def pause_channel(channel_id: str, ctx: Context | None = None) -> ChannelStatusResult:
    """Pause ingestion for a channel. The scheduler will skip it on subsequent cycles.
    Idempotent: pausing an already-paused channel returns changed=false.

    Args:
        channel_id: Channel ID (with or without @)."""
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.services.db_context import ingestion_state_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    normalized = channel_id.lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return ChannelStatusResult(
            channel_id=normalized,
            status="error",
            previous_status="unknown",
            changed=False,
            message=e.message,
        )

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
async def resume_channel(channel_id: str, ctx: Context | None = None) -> ChannelStatusResult:
    """Resume ingestion for a paused or errored channel.
    If the channel was in error state, resets fail_count and last_error.
    Idempotent: resuming an already-active channel returns changed=false.

    Args:
        channel_id: Channel ID (with or without @)."""
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.services.db_context import ingestion_state_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    normalized = channel_id.lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return ChannelStatusResult(
            channel_id=normalized,
            status="error",
            previous_status="unknown",
            changed=False,
            message=e.message,
        )

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
    ctx: Context | None = None,
) -> RemoveChannelResult:
    """Permanently remove a channel and ALL its data from the knowledge base.
    This action is IRREVERSIBLE. You must set confirm=true to proceed.
    Removes: source config, raw messages, processed documents, embeddings,
    topics, and processing failures.

    Args:
        channel_id: Channel ID (with or without @).
        confirm: Safety flag — must be true to actually delete data."""
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    normalized = channel_id.lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return RemoveChannelResult(
            channel_id=normalized,
            removed=False,
            message=e.message,
            details={},
        )

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
        state_repo,
        raw_repo,
        proc_repo,
        failure_repo,
        embedding_repo,
        topic_card_repo,
        topic_bundle_repo,
        job_repo,
        task_history_repo,
        _db,
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
        counts["api_jobs"] = await job_repo.delete_by_channel(normalized)
        counts["task_history"] = await task_history_repo.delete_by_channel(normalized)

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
    ctx: Context | None = None,
) -> PipelineStatusResult:
    """Check pipeline and scheduler status for all or a specific channel.
    Shows last attempt/success times, fail counts, and scheduler configuration.

    Args:
        channel_id: Optional channel filter. If omitted, returns all sources."""
    from tg_parser.services.scheduler_service import get_scheduler_status

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    status = await get_scheduler_status()

    sources_raw = status["sources"]
    if channel_id:
        normalized = channel_id.lstrip("@")
        sources_raw = [s for s in sources_raw if s["channel_id"] == normalized]

    if user.allowed_channel_ids is not None:
        sources_raw = [s for s in sources_raw if s["channel_id"] in user.allowed_channel_ids]

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
    ctx: Context | None = None,
) -> TriggerPipelineResult:
    """Start the processing pipeline for a channel (fire-and-forget).
    Runs ingestion, processing, and embedding in the background.
    Use get_pipeline_status to monitor progress.

    Args:
        channel_id: Channel ID (with or without @).
        force: Re-process already processed documents (default false)."""
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.services.db_context import ingestion_state_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    normalized = channel_id.lstrip("@")
    try:
        await assert_channel_access(user, normalized)
    except PermissionDenied as e:
        return TriggerPipelineResult(
            channel_id=normalized,
            triggered=False,
            message=e.message,
        )

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
        except RuntimeError:
            pipeline_failed = True
            logger.exception(
                "Pipeline failed for %s, proceeding to embedding",
                source_id,
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
# T8: MCP Tools — LLM Configuration
# ---------------------------------------------------------------------------


class LLMConfigResult(BaseModel):
    config: dict[str, Any]


class LLMConfigSetResult(BaseModel):
    success: bool
    message: str
    config: dict[str, Any]


@mcp.tool()
async def get_llm_config(ctx: Context | None = None) -> LLMConfigResult:
    """Show the current active LLM configuration.

    Returns global and per-stage (processing, topicization) provider/model,
    whether each is overridden at runtime, and which providers have API keys
    configured.  Use this before set_llm_config to see available options."""
    from tg_parser.config import llm_config

    return LLMConfigResult(config=llm_config.get_all())


@mcp.tool()
async def set_llm_config(
    scope: str,
    provider: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    ctx: Context | None = None,
) -> LLMConfigSetResult:
    """Change the LLM provider/model at runtime (no restart needed).

    New pipeline runs will use the updated provider immediately.
    In-flight requests keep the old provider until they finish.
    Changes are NOT persisted to .env — a restart reverts to defaults.

    Args:
        scope: Which config to change: 'global', 'processing', 'topicization', 'rag', 'digest', or 'resummarize'.
        provider: LLM provider name: 'openai', 'anthropic', 'gemini', or 'ollama'.
        model: Optional model name override (e.g. 'gpt-4o', 'claude-sonnet-4-20250514').
               If omitted, the provider's default model is used.
        temperature: Optional temperature override (0.0-2.0).
        max_tokens: Optional max_tokens override."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.config import llm_config

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return LLMConfigSetResult(success=False, message=e.message, config=llm_config.get_all())

    try:
        updated = llm_config.set(
            scope=scope,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ValueError as exc:
        return LLMConfigSetResult(
            success=False,
            message=str(exc),
            config=llm_config.get_all(),
        )

    return LLMConfigSetResult(
        success=True,
        message=f"LLM config updated: scope={scope}, provider={provider}"
        + (f", model={model}" if model else ""),
        config=updated,
    )


@mcp.tool()
async def reset_llm_config(
    scope: str | None = None,
    ctx: Context | None = None,
) -> LLMConfigSetResult:
    """Reset runtime LLM overrides, reverting to .env defaults.

    Args:
        scope: Scope to reset ('global', 'processing', 'topicization', 'rag', 'digest', or 'resummarize').
               If omitted, resets ALL runtime overrides."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.config import llm_config

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return LLMConfigSetResult(success=False, message=e.message, config=llm_config.get_all())

    updated = llm_config.clear(scope=scope)
    label = scope or "all scopes"
    return LLMConfigSetResult(
        success=True,
        message=f"LLM config reset for {label}. Now using .env defaults.",
        config=updated,
    )


# ---------------------------------------------------------------------------
# F4 Phase 5: User Management MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def register_user(
    name: str,
    role: str = "user",
    max_channels: int | None = None,
    ctx: Context | None = None,
) -> RegisterUserResult:
    """Register a new user. Admin only.
    max_channels: per-user channel limit (None = use global default from settings)."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.services.db_context import user_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return RegisterUserResult(success=False, user_id=None, message=e.message)

    async with user_repo() as (repo, _db):
        new_user = await repo.create_user(name, role, max_channels)

    return RegisterUserResult(
        success=True,
        user_id=new_user.id,
        message=f"User '{name}' created with role '{role}'.",
    )


@mcp.tool()
async def update_user(
    user_id: str,
    name: str | None = None,
    role: str | None = None,
    max_channels: int | None = None,
    reset_max_channels: bool = False,
    ctx: Context | None = None,
) -> UpdateUserResult:
    """Update user properties. Admin only.
    Only provided fields are changed.
    To reset max_channels to global default, set reset_max_channels=true.
    To set a specific limit, provide max_channels with an integer value."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.services.db_context import user_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return UpdateUserResult(success=False, message=e.message)

    mc_val: Any = ...
    if reset_max_channels:
        mc_val = None
    elif max_channels is not None:
        mc_val = max_channels

    async with user_repo() as (repo, _db):
        updated = await repo.update_user(user_id, name=name, role=role, max_channels=mc_val)

    if updated is None:
        return UpdateUserResult(success=False, message=f"User '{user_id}' not found.")

    return UpdateUserResult(success=True, message=f"User '{user_id}' updated.")


@mcp.tool()
async def list_users(ctx: Context | None = None) -> ListUsersResult:
    """List all users with their channel counts. Admin only."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.services.db_context import user_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return ListUsersResult(success=False, users=[], message=e.message)

    async with user_repo() as (repo, _db):
        all_users = await repo.list_users()
        infos: list[UserInfo] = []
        for u in all_users:
            channel_ids = await repo.get_owned_channel_ids(u.id)
            infos.append(
                UserInfo(
                    id=u.id,
                    name=u.name,
                    role=u.role,
                    max_channels=u.max_channels,
                    owned_channels_count=len(channel_ids),
                )
            )

    return ListUsersResult(success=True, users=infos)


@mcp.tool()
async def whoami(ctx: Context | None = None) -> WhoamiResult:
    """Show current user's profile: name, role, channels count / limit."""
    from tg_parser.config import settings as app_settings
    from tg_parser.services.db_context import user_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    async with user_repo() as (repo, _db):
        channel_ids = await repo.get_owned_channel_ids(user.id)
        db_user = await repo.get_by_id(user.id)

    effective_max = user.max_channels
    if db_user and db_user.max_channels is not None:
        effective_max = db_user.max_channels
    elif db_user:
        effective_max = app_settings.default_max_channels

    return WhoamiResult(
        id=user.id,
        name=user.name,
        role=user.role,
        max_channels=effective_max,
        owned_channels=channel_ids,
        owned_channels_count=len(channel_ids),
    )


@mcp.tool()
async def add_user_auth(
    user_id: str,
    auth_type: str,
    identifier: str,
    client_name: str | None = None,
    ctx: Context | None = None,
) -> AddUserAuthResult:
    """Add auth mapping for a user. Admin only.
    auth_type: 'api_key' | 'telegram' | 'mcp_token'
    identifier: raw value (hashed automatically for api_key/mcp_token)."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import hash_credential, invalidate_user_cache
    from tg_parser.services.db_context import user_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return AddUserAuthResult(success=False, mapping_id=None, message=e.message)

    valid_types = {"api_key", "telegram", "mcp_token"}
    if auth_type not in valid_types:
        return AddUserAuthResult(
            success=False,
            mapping_id=None,
            message=f"Invalid auth_type '{auth_type}'. Must be one of: {', '.join(sorted(valid_types))}",
        )

    stored_identifier = (
        hash_credential(identifier) if auth_type in ("api_key", "mcp_token") else identifier
    )

    async with user_repo() as (repo, _db):
        mapping = await repo.add_auth_mapping(user_id, auth_type, stored_identifier, client_name)

    invalidate_user_cache(auth_type, stored_identifier)

    return AddUserAuthResult(
        success=True,
        mapping_id=mapping.id,
        message=f"Auth mapping added for user '{user_id}' (type={auth_type}).",
    )


@mcp.tool()
async def remove_user_auth(
    mapping_id: str,
    ctx: Context | None = None,
) -> RemoveUserAuthResult:
    """Remove an auth mapping by ID. Admin only."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.services.db_context import user_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return RemoveUserAuthResult(success=False, message=e.message)

    async with user_repo() as (repo, _db):
        removed = await repo.remove_auth_mapping(mapping_id)

    if not removed:
        return RemoveUserAuthResult(success=False, message=f"Mapping '{mapping_id}' not found.")

    return RemoveUserAuthResult(success=True, message=f"Auth mapping '{mapping_id}' removed.")


# ---------------------------------------------------------------------------
# F5-C: Evolving Topic Summaries — version history + manual trigger
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_topic_versions(
    topic_id: str,
    limit: int = 10,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Return the F5-C summary version history for a topic (audit trail).

    Each successful re-summarize appends one row to ``topic_card_versions``
    with the *previous* summary, scope_in, scope_out, supporting items
    count, and the LLM provenance (provider/model/prompt version). Use
    this to inspect how a topic's understanding has evolved as new
    supporting items landed in its bundle.

    Visibility: a topic is readable if the caller has access to **at
    least one** of its ``sources`` channels (mirrors
    ``TopicCardRepo.list_by_channels``). Admins always pass.

    Args:
        topic_id: The topic ID, e.g. ``topic:tg:channel:post:123``.
        limit: Max versions to return (newest first), 1..200, default 10.
    """
    from tg_parser.auth.ownership import PermissionDenied, assert_topic_access
    from tg_parser.services.db_context import resummarization_repos

    if limit < 1 or limit > 200:
        return {"error": "limit must be between 1 and 200", "topic_id": topic_id}

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    async with resummarization_repos() as (
        card_repo,
        _bundle_repo,
        version_repo,
        _db,
    ):
        card = await card_repo.get_by_id(topic_id)
        if card is None:
            return {"error": f"Topic not found: {topic_id}", "topic_id": topic_id}

        try:
            await assert_topic_access(user, card.sources)
        except PermissionDenied as e:
            return {"error": e.message, "topic_id": topic_id}

        versions = await version_repo.list_by_topic(topic_id, limit=limit)

    return {
        "topic_id": topic_id,
        "current_version": card.summary_version,
        "last_summarized_at": (
            card.last_summarized_at.isoformat() if card.last_summarized_at else None
        ),
        "new_items_since_last_summary": card.new_items_since_last_summary,
        "versions": [v.model_dump(mode="json") for v in versions],
    }


@mcp.tool()
async def force_resummarize(
    topic_id: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Manually trigger F5-C re-summarize for one topic (admin only).

    Bypasses the N-threshold counter and immediately re-summarizes the
    topic. Subject to the same advisory-lock semantics as the scheduler:
    if another tick (or another manual call) is already re-summarizing
    this topic, returns ``status='locked'`` instead of blocking.

    Useful for debugging prompts, refreshing a stale topic before a
    digest run, or recovering from a transient LLM error without waiting
    for the next bundle item to bump the trigger counter.

    Returns the same shape as the internal
    :meth:`ResummarizationService.resummarize_topic` outcome dict —
    ``status`` is one of ``ok``, ``locked``, ``no_card``, ``no_bundle``,
    ``empty_scope``, ``llm_error``, ``version_raced``.
    """
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.services.db_context import resummarization_repos
    from tg_parser.services.resummarization_service import ResummarizationService

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message, "topic_id": topic_id}

    async with resummarization_repos() as (
        card_repo,
        bundle_repo,
        version_repo,
        _db,
    ):
        service = ResummarizationService(
            topic_card_repo=card_repo,
            topic_bundle_repo=bundle_repo,
            topic_card_version_repo=version_repo,
        )
        try:
            outcome = await service.resummarize_topic(topic_id)
        finally:
            await service.aclose()

    return {"topic_id": topic_id, **outcome}


# ---------------------------------------------------------------------------
# T3b: Prompt Management
# ---------------------------------------------------------------------------


@mcp.tool()
async def reload_prompts(
    name: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Reload prompt templates from YAML files (no restart needed).

    Clears the prompt cache so that next use picks up changes from disk.
    Use after editing prompts/*.yaml files.

    Args:
        name: Optional prompt name to reload ('rag', 'bot', 'processing',
              'topicization', 'incremental_discover', 'merge', 'supporting_items').
              If omitted, reloads ALL prompts."""
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.processing.prompt_loader import get_prompt_loader

    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message, "success": False}

    loader = get_prompt_loader()
    loader.reload(name)
    return {"reloaded": name or "all", "success": True}


# ---------------------------------------------------------------------------
# F2: Parse-Only Export — MCP tools
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: str | None, *, field: str) -> Any:
    """Parse an ISO-8601 datetime string (UTC). Accepts 'YYYY-MM-DD' too."""
    from datetime import datetime as _dt

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string, got {type(value).__name__}")
    try:
        return _dt.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 datetime: {value!r}") from exc


@mcp.tool()
async def export_channel(
    channel_id: str,
    level: str = "raw",
    format: str = "json",
    from_date: str | None = None,
    to_date: str | None = None,
    ctx: Context | None = None,
) -> ExportChannelResult:
    """Submit a channel export job (F2: Parse-Only Export).

    Creates a background job that exports channel content at the requested
    ``level``. Use ``get_export_status`` to poll for completion, then fetch
    the file via ``download_url``.

    Args:
        channel_id: Telegram channel ID (required for level='raw').
        level: 'raw' (parse-only, no LLM; default) | 'processed'
            (KnowledgeBaseEntry[]) | 'full' (legacy: processed + topics).
        format: 'json' | 'ndjson' — applies to level='raw'; for
            processed/full the legacy convention (kb_entries.ndjson +
            topics.json) is used.
        from_date: Optional ISO-8601 UTC datetime filter (inclusive).
        to_date: Optional ISO-8601 UTC datetime filter (inclusive).

    Returns:
        ``ExportChannelResult`` with ``job_id`` and ``status='pending'``.
        Poll via ``get_export_status(job_id)`` until ``status='completed'``,
        then download from ``download_url``.
    """
    import asyncio as _asyncio
    import uuid as _uuid
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from tg_parser.api.job_store import ensure_job_store_initialized
    from tg_parser.api.routes.export import _run_export_job
    from tg_parser.api.schemas import ExportFormat, ExportLevel, ExportRequest
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.storage.ports import Job, JobStatus, JobType

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    try:
        level_enum = ExportLevel(level)
    except ValueError as exc:
        raise ValueError(
            f"invalid level: {level!r}; expected one of {[lv.value for lv in ExportLevel]}"
        ) from exc

    try:
        format_enum = ExportFormat(format)
    except ValueError as exc:
        raise ValueError(
            f"invalid format: {format!r}; expected one of {[fm.value for fm in ExportFormat]}"
        ) from exc

    normalized = channel_id.lstrip("@") if channel_id else channel_id

    if level_enum == ExportLevel.RAW and not normalized:
        raise ValueError("level='raw' requires channel_id")

    if normalized:
        try:
            await assert_channel_access(user, normalized)
        except PermissionDenied as e:
            return ExportChannelResult(
                job_id="",
                status="rejected",
                channel_id=normalized,
                level=level_enum.value,
                format=format_enum.value,
                download_url=None,
                message=e.message,
            )

    parsed_from = _parse_iso_datetime(from_date, field="from_date")
    parsed_to = _parse_iso_datetime(to_date, field="to_date")

    request = ExportRequest(
        channel_id=normalized,
        level=level_enum,
        format=format_enum,
        from_date=parsed_from,
        to_date=parsed_to,
    )

    job_store = await ensure_job_store_initialized()
    job_id = str(_uuid.uuid4())
    created_at = _dt.now(_UTC)

    job = Job(
        job_id=job_id,
        job_type=JobType.EXPORT,
        status=JobStatus.PENDING,
        created_at=created_at,
        channel_id=normalized,
        client=user.name,
        export_format=format_enum.value,
        progress={"level": level_enum.value},
    )
    await job_store.create_job(job)

    task = _asyncio.create_task(
        _run_export_job(job_id, request),
        name=f"mcp-export-{job_id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info(
        "mcp_export_channel_submitted",
        job_id=job_id,
        channel_id=normalized,
        level=level_enum.value,
        format=format_enum.value,
    )

    return ExportChannelResult(
        job_id=job_id,
        status=JobStatus.PENDING.value,
        channel_id=normalized or "",
        level=level_enum.value,
        format=format_enum.value,
        download_url=None,
        message=(
            f"Export job created for channel '{normalized}' "
            f"(level={level_enum.value}, format={format_enum.value}). "
            "Poll with get_export_status until status='completed'."
        ),
    )


@mcp.tool()
async def get_export_status(
    job_id: str,
    ctx: Context | None = None,
) -> ExportStatusResult:
    """Check the status of a previously submitted export job (F2).

    Args:
        job_id: Job identifier returned by ``export_channel``.
    """
    from tg_parser.api.job_store import ensure_job_store_initialized
    from tg_parser.api.routes.export import _resolve_job_level
    from tg_parser.api.schemas import ExportFormat

    _user = await resolve_mcp_user(ctx.client_id if ctx else None)

    job_store = await ensure_job_store_initialized()
    job = await job_store.get_job(job_id)

    if job is None:
        return ExportStatusResult(
            job_id=job_id,
            status="unknown",
            channel_id=None,
            level="full",
            format="ndjson",
            download_url=None,
            file_size=None,
            message=f"Export job {job_id} not found.",
        )

    export_format = ExportFormat(job.export_format) if job.export_format else ExportFormat.NDJSON
    export_level = _resolve_job_level(job)

    file_size: int | None = None
    if job.result and isinstance(job.result, dict):
        size = job.result.get("file_size")
        if isinstance(size, int):
            file_size = size

    return ExportStatusResult(
        job_id=job.job_id,
        status=job.status.value,
        channel_id=job.channel_id,
        level=export_level.value,
        format=export_format.value,
        download_url=job.download_url,
        file_size=file_size,
        message=job.error or f"Status: {job.status.value}",
    )


# ---------------------------------------------------------------------------
# F6: Scheduled Digests — MCP tools
# ---------------------------------------------------------------------------


def _digest_to_info(sub: Any) -> DigestSubscriptionInfo:
    return DigestSubscriptionInfo(
        id=sub.id,
        owner_id=sub.owner_id,
        chat_id=sub.chat_id,
        name=sub.name,
        channel_ids=list(sub.channel_ids),
        cron_expression=sub.cron_expression,
        timezone=sub.timezone,
        format=sub.format.value,
        language=sub.language,
        is_active=sub.is_active,
        last_sent_at=sub.last_sent_at.isoformat() if sub.last_sent_at else None,
        last_digest_cursor=sub.last_digest_cursor.isoformat() if sub.last_digest_cursor else None,
    )


@mcp.tool()
async def subscribe_digest(
    name: str,
    channel_ids: list[str],
    chat_id: int,
    cron_expression: str = "0 9 * * *",
    timezone: str = "UTC",
    format: str = "summary",
    language: str = "ru",
    ctx: Context | None = None,
) -> SubscribeDigestResult:
    """Create a recurring digest subscription (F6).

    The subscription is owned by the calling user and delivered to ``chat_id``
    on the cron schedule. For private chats ``chat_id`` equals the user's
    Telegram id; for groups/supergroups it is a negative integer (Telegram
    convention). Each ``channel_id`` must be accessible by the caller
    (admin sees all, regular user sees only owned channels).

    Args:
        name: Human-readable subscription name (used by list/unsubscribe).
        channel_ids: One or more channel ids (or @usernames) to digest.
        chat_id: Telegram chat id to deliver into.
        cron_expression: Standard 5-field cron (default '0 9 * * *' = 09:00 daily).
        timezone: IANA timezone for the cron (default 'UTC').
        format: 'summary' | 'bullets' | 'detailed' (default 'summary').
        language: Output language code (default 'ru').
    """
    import uuid as _uuid
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.domain.models import DigestFormat, DigestSubscription
    from tg_parser.services.background_scheduler import (
        get_scheduler,
        register_digest_subscription,
        unregister_digest_subscription,
    )
    from tg_parser.services.db_context import digest_subscription_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    if not name or not name.strip():
        return SubscribeDigestResult(success=False, subscription=None, message="name is required")
    if not channel_ids:
        return SubscribeDigestResult(
            success=False, subscription=None, message="channel_ids must be non-empty"
        )

    normalized = [str(c).lstrip("@").strip() for c in channel_ids if str(c).strip()]
    if not normalized:
        return SubscribeDigestResult(
            success=False,
            subscription=None,
            message="channel_ids must contain at least one channel",
        )

    for cid in normalized:
        try:
            await assert_channel_access(user, cid)
        except PermissionDenied as exc:
            return SubscribeDigestResult(
                success=False,
                subscription=None,
                message=f"{exc.message} (channel_id={cid})",
            )

    try:
        format_enum = DigestFormat(format)
    except ValueError:
        return SubscribeDigestResult(
            success=False,
            subscription=None,
            message=(
                f"invalid format: {format!r}; expected one of {[fm.value for fm in DigestFormat]}"
            ),
        )

    subscription = DigestSubscription(
        id=str(_uuid.uuid4()),
        owner_id=user.id,
        chat_id=chat_id,
        name=name.strip(),
        channel_ids=normalized,
        cron_expression=cron_expression.strip(),
        timezone=timezone.strip(),
        format=format_enum,
        language=language.strip(),
        is_active=True,
        last_sent_at=None,
        last_digest_cursor=None,
        created_at=_dt.now(_UTC),
        updated_at=_dt.now(_UTC),
    )

    try:
        register_digest_subscription(subscription, get_scheduler())
    except ValueError as exc:
        return SubscribeDigestResult(
            success=False,
            subscription=None,
            message=f"cron/timezone validation failed: {exc}",
        )

    try:
        async with digest_subscription_repo() as (repo, _db):
            created = await repo.create(subscription)
    except SQLAlchemyError as exc:
        unregister_digest_subscription(subscription.id)
        logger.exception("mcp_subscribe_digest_persist_failed")
        return SubscribeDigestResult(
            success=False,
            subscription=None,
            message=f"failed to persist subscription: {exc}",
        )

    logger.info(
        "mcp_subscribe_digest_created",
        subscription_id=created.id,
        owner_id=created.owner_id,
        channel_count=len(created.channel_ids),
    )
    return SubscribeDigestResult(
        success=True,
        subscription=_digest_to_info(created),
        message=(
            f"Subscription '{created.name}' created. "
            f"Schedule: {created.cron_expression} ({created.timezone}). "
            f"Channels: {len(created.channel_ids)}."
        ),
    )


@mcp.tool()
async def list_digests(ctx: Context | None = None) -> ListDigestsResult:
    """List digest subscriptions (F6).

    Admins see every subscription in the system; regular users see only their
    own. Inactive (paused) subscriptions are included so the caller can
    inspect / re-create them.
    """
    from tg_parser.services.db_context import digest_subscription_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    async with digest_subscription_repo() as (repo, _db):
        if user.is_admin:
            subs = await repo.list_all()
        else:
            subs = await repo.list_by_owner(user.id)

    return ListDigestsResult(
        count=len(subs),
        subscriptions=[_digest_to_info(s) for s in subs],
    )


@mcp.tool()
async def unsubscribe_digest(
    subscription_id: str,
    ctx: Context | None = None,
) -> UnsubscribeDigestResult:
    """Delete a digest subscription by id (F6).

    Owner-only for non-admins; admins can delete any subscription. The
    matching scheduler job is removed atomically — the next reconciliation
    tick is *not* required for the deletion to take effect inside the bot
    process.
    """
    from tg_parser.services.background_scheduler import unregister_digest_subscription
    from tg_parser.services.db_context import digest_subscription_repo

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    sub_id = subscription_id.strip()
    if not sub_id:
        return UnsubscribeDigestResult(
            success=False,
            subscription_id=subscription_id,
            message="subscription_id is required",
        )

    async with digest_subscription_repo() as (repo, _db):
        existing = await repo.get(sub_id)
        if existing is None:
            return UnsubscribeDigestResult(
                success=False,
                subscription_id=sub_id,
                message=f"Subscription {sub_id!r} not found.",
            )
        if not user.is_admin and existing.owner_id != user.id:
            return UnsubscribeDigestResult(
                success=False,
                subscription_id=sub_id,
                message="Permission denied (owner-only).",
            )
        deleted = await repo.delete(sub_id)

    if deleted:
        unregister_digest_subscription(sub_id)
        return UnsubscribeDigestResult(
            success=True,
            subscription_id=sub_id,
            message=f"Subscription {sub_id!r} deleted.",
        )
    return UnsubscribeDigestResult(
        success=False,
        subscription_id=sub_id,
        message=f"Subscription {sub_id!r} delete failed.",
    )


# ---------------------------------------------------------------------------
# F11: Topic Watchlist — MCP tools
# ---------------------------------------------------------------------------


def _interest_to_info(interest: Any) -> WatchInterestInfo:
    return WatchInterestInfo(
        id=interest.id,
        user_id=interest.user_id,
        chat_id=interest.chat_id,
        title=interest.title,
        description=interest.description,
        keywords=list(interest.keywords),
        exclude_keywords=list(interest.exclude_keywords),
        channel_ids=list(interest.channel_ids),
        threshold=interest.threshold,
        notify_mode=interest.notify_mode.value,
        is_active=interest.is_active,
        last_checked_at=interest.last_checked_at.isoformat() if interest.last_checked_at else None,
        last_match_at=interest.last_match_at.isoformat() if interest.last_match_at else None,
        created_at=interest.created_at.isoformat() if interest.created_at else None,
    )


def _watch_match_to_info(match: Any) -> WatchMatchInfo:
    return WatchMatchInfo(
        id=match.id,
        interest_id=match.interest_id,
        source_ref=match.source_ref,
        channel_id=match.channel_id,
        keyword_score=match.keyword_score,
        semantic_score=match.semantic_score,
        combined_score=match.combined_score,
        notified=match.notified,
        created_at=match.created_at.isoformat() if match.created_at else None,
    )


@mcp.tool()
async def subscribe_watchlist(
    title: str,
    channel_ids: list[str],
    chat_id: int,
    keywords: list[str] | None = None,
    description: str | None = None,
    exclude_keywords: list[str] | None = None,
    threshold: float = 0.6,
    ctx: Context | None = None,
) -> SubscribeWatchlistResult:
    """Create a persistent thematic alert (F11 Topic Watchlist).

    The interest is owned by the calling user. After every incremental
    pipeline tick, new ProcessedDocuments from the listed channels are
    scored against this interest using a hybrid keyword + semantic match;
    scores at or above ``threshold`` are saved in ``watch_matches`` and
    pushed to ``chat_id`` via the bot (notify_mode=instant).

    Args:
        title: Short human label (used in push notifications).
        channel_ids: Non-empty list of channels to watch (must be accessible).
        chat_id: Telegram chat to deliver pushes into. For private chats this
            equals the user's Telegram id; for groups/supergroups the bot must
            be a member of that chat.
        keywords: Optional positive keywords (recall-like overlap component).
        description: Optional free-form text used as the embedding source. If
            omitted, the embedding falls back to ``title`` + ``keywords``.
        exclude_keywords: Optional negative filter — any matching token zeroes
            the score for that document.
        threshold: Combined-score cutoff in [0, 1] (default 0.6). Lower =
            more matches (less precise); higher = fewer (more precise).
    """
    from tg_parser.auth.ownership import PermissionDenied, assert_channel_access
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    if not title or not title.strip():
        return SubscribeWatchlistResult(success=False, interest=None, message="title is required")
    if not channel_ids:
        return SubscribeWatchlistResult(
            success=False, interest=None, message="channel_ids must be non-empty"
        )
    if threshold < 0.0 or threshold > 1.0:
        return SubscribeWatchlistResult(
            success=False,
            interest=None,
            message=f"threshold must be in [0.0, 1.0], got {threshold}",
        )

    normalized = [str(c).lstrip("@").strip() for c in channel_ids if str(c).strip()]
    if not normalized:
        return SubscribeWatchlistResult(
            success=False,
            interest=None,
            message="channel_ids must contain at least one non-empty channel",
        )

    for cid in normalized:
        try:
            await assert_channel_access(user, cid)
        except PermissionDenied as exc:
            return SubscribeWatchlistResult(
                success=False,
                interest=None,
                message=f"{exc.message} (channel_id={cid})",
            )

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
                    title=title.strip(),
                    channel_ids=normalized,
                    keywords=list(keywords or []),
                    description=description,
                    exclude_keywords=list(exclude_keywords or []),
                    threshold=threshold,
                )
            finally:
                await service.aclose()
    except SQLAlchemyError as exc:
        logger.exception("mcp_subscribe_watchlist_persist_failed")
        return SubscribeWatchlistResult(
            success=False,
            interest=None,
            message=f"failed to persist interest: {exc}",
        )

    logger.info(
        "mcp_subscribe_watchlist_created",
        interest_id=created.id,
        owner_id=created.user_id,
        channel_count=len(created.channel_ids),
    )
    return SubscribeWatchlistResult(
        success=True,
        interest=_interest_to_info(created),
        message=(
            f"Interest {created.title!r} created. "
            f"Channels: {len(created.channel_ids)}, threshold: {created.threshold}."
        ),
    )


@mcp.tool()
async def list_watchlists(ctx: Context | None = None) -> ListWatchlistsResult:
    """List the caller's topic watchlists (F11).

    Admins see every interest in the system; regular users see only their
    own. Inactive (soft-deleted) interests are included so the caller can
    inspect / re-create them.
    """
    from tg_parser.services.db_context import watchlist_repos

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

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

    return ListWatchlistsResult(
        count=len(interests),
        interests=[_interest_to_info(i) for i in interests],
    )


@mcp.tool()
async def unsubscribe_watchlist(
    interest_id: str,
    ctx: Context | None = None,
) -> UnsubscribeWatchlistResult:
    """Soft-delete a topic watchlist by id (F11).

    Owner-only for non-admins; admins can delete any interest. Soft-delete
    preserves match history (``watch_matches`` rows stay) so historical
    queries continue to work.
    """
    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    target_id = (interest_id or "").strip()
    if not target_id:
        return UnsubscribeWatchlistResult(
            success=False,
            interest_id=interest_id,
            message="interest_id is required",
        )

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
                target_id,
                requesting_user_id=user.id,
                is_admin=user.is_admin,
            )
        finally:
            await service.aclose()

    if deleted:
        return UnsubscribeWatchlistResult(
            success=True,
            interest_id=target_id,
            message=f"Interest {target_id!r} deactivated.",
        )
    return UnsubscribeWatchlistResult(
        success=False,
        interest_id=target_id,
        message=error or "delete failed",
    )


@mcp.tool()
async def get_watchlist_matches(
    interest_id: str,
    since_iso: str | None = None,
    ctx: Context | None = None,
) -> GetWatchlistMatchesResult:
    """Return saved matches for a watchlist interest (F11).

    Owner-only for non-admins; admins can read any interest. ``since_iso`` is
    an optional ISO-8601 datetime filter (``created_at >= since_iso``) used
    for incremental polling without dropping the persistent log.
    """
    from datetime import datetime as _dt

    from tg_parser.services.db_context import watchlist_repos
    from tg_parser.services.watchlist_service import make_watchlist_service

    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    target_id = (interest_id or "").strip()
    if not target_id:
        return GetWatchlistMatchesResult(
            count=0,
            interest_id=interest_id,
            matches=[],
        )

    parsed_since: Any = None
    if since_iso:
        try:
            parsed_since = _dt.fromisoformat(since_iso)
        except ValueError:
            return GetWatchlistMatchesResult(
                count=0,
                interest_id=target_id,
                matches=[],
            )

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
            interest = await service.get_interest(target_id)
            if interest is None:
                return GetWatchlistMatchesResult(
                    count=0,
                    interest_id=target_id,
                    matches=[],
                )
            if not user.is_admin and interest.user_id != user.id:
                return GetWatchlistMatchesResult(
                    count=0,
                    interest_id=target_id,
                    matches=[],
                )
            matches = await service.get_matches(target_id, since=parsed_since)
        finally:
            await service.aclose()

    return GetWatchlistMatchesResult(
        count=len(matches),
        interest_id=target_id,
        matches=[_watch_match_to_info(m) for m in matches],
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
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def _run_mcp() -> None:
    """Run MCP server via stdio (local development).

    Lifespan handles Database init/close automatically.
    Logging is redirected to stderr to keep stdout clean for JSON-RPC.
    """
    _configure_mcp_logging()
    await mcp.run_stdio_async()


async def _run_http() -> None:
    """Run MCP server via Streamable HTTP (production)."""
    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(_run_mcp())
