"""
RAG API routes (P5): search and Q&A endpoints.
"""

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from tg_parser.api.auth import resolve_current_user
from tg_parser.auth.models import CurrentUser

SearchMode = Literal["semantic", "keyword", "hybrid"]

router = APIRouter(prefix="/api/v1", tags=["RAG"])
logger = structlog.get_logger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """Hybrid/semantic/keyword search request."""

    query: str = Field(description="Natural language search query")
    channel_id: str | None = Field(default=None, description="Optional channel filter")
    limit: int = Field(default=10, ge=1, le=100, description="Max results")
    mode: SearchMode = Field(
        default="hybrid",
        description=(
            "Retrieval mode: 'semantic' (pgvector cosine), 'keyword' (FTS ts_rank_cd), "
            "or 'hybrid' (both via RRF)."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"query": "анализ крови норма", "limit": 5, "mode": "hybrid"}]
        }
    }


class SearchResultItem(BaseModel):
    source_ref: str
    score: float
    summary: str | None = None
    text_preview: str | None = None
    channel_id: str | None = None
    entry_type: str = "message"
    title: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str
    total: int
    degraded: bool = Field(
        default=False,
        description=(
            "BUG-084: True when semantic/hybrid retrieval fell back to keyword-only "
            "because the query embedding failed (terminal quota exhaustion or an "
            "exhausted transient rate-limit). Results are still returned but the "
            "semantic ranking signal was unavailable."
        ),
    )


class AskRequest(BaseModel):
    """RAG Q&A request."""

    question: str = Field(description="Question in natural language")
    channel_id: str | None = Field(default=None, description="Optional channel filter")
    mode: SearchMode = Field(
        default="hybrid",
        description=("Retrieval mode forwarded to search: 'semantic', 'keyword', or 'hybrid'."),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"question": "Когда назначают анализ СОЭ?", "mode": "hybrid"}]
        }
    }


class AskResponse(BaseModel):
    answer: str
    sources: list[SearchResultItem]
    model: str | None = None
    degraded: bool = Field(
        default=False,
        description=(
            "BUG-084: True when the underlying retrieval fell back to keyword-only "
            "because the query embedding failed (terminal quota exhaustion or an "
            "exhausted transient rate-limit). The answer is still generated but over "
            "keyword-retrieved context only."
        ),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    body: SearchRequest, request: Request, user: CurrentUser = Depends(resolve_current_user)
):
    """Semantic search over embedded documents."""
    from tg_parser.services.retrieval_service import search

    logger.info("rag_search", query=body.query[:80], channel_id=body.channel_id, mode=body.mode)

    results = await search(
        query=body.query,
        channel_id=body.channel_id,
        limit=body.limit,
        allowed_channel_ids=user.allowed_channel_ids,
        mode=body.mode,
    )

    from tg_parser.services.search_result_projection import project_search_result

    items = [SearchResultItem(**project_search_result(r, preview_limit=200)) for r in results]

    return SearchResponse(
        results=items,
        query=body.query,
        total=len(items),
        degraded=getattr(results, "degraded", False),
    )


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    body: AskRequest, request: Request, user: CurrentUser = Depends(resolve_current_user)
):
    """RAG Q&A: answer a question using retrieved context + LLM."""
    from tg_parser.services.retrieval_service import answer

    logger.info("rag_ask", question=body.question[:80], channel_id=body.channel_id, mode=body.mode)

    result = await answer(
        question=body.question,
        channel_id=body.channel_id,
        allowed_channel_ids=user.allowed_channel_ids,
        mode=body.mode,
    )

    from tg_parser.services.search_result_projection import project_search_result

    sources = [
        SearchResultItem(**project_search_result(s, preview_limit=200)) for s in result.sources
    ]

    return AskResponse(
        answer=result.answer,
        sources=sources,
        model=result.model,
        degraded=getattr(result, "degraded", False),
    )
