"""
Retrieval service (P5 RAG).

Provides semantic search and LLM-powered Q&A over the embedded document corpus.
"""

import logging
from dataclasses import dataclass
from typing import Any

from tg_parser.config import settings
from tg_parser.domain.models import ProcessedDocument
from tg_parser.services.db_context import embedding_repos
from tg_parser.services.embedding_service import OpenAIEmbeddingClient

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A document returned by similarity search."""
    source_ref: str
    score: float
    document: ProcessedDocument | None = None


@dataclass
class AnswerResult:
    """LLM-generated answer with supporting sources."""
    answer: str
    sources: list[SearchResult]
    model: str | None = None


def _create_embedding_client() -> OpenAIEmbeddingClient:
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for retrieval")
    return OpenAIEmbeddingClient(
        api_key=api_key,
        model=settings.embedding_model,
    )


async def search(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    threshold: float = 0.0,
) -> list[SearchResult]:
    """
    Semantic search: embed query, find similar documents via pgvector.

    Args:
        query: Natural language query
        channel_id: Optional filter (post-filter, not pre-filter)
        limit: Max results to return
        threshold: Minimum cosine similarity score

    Returns:
        Ranked list of SearchResult
    """
    client = _create_embedding_client()
    try:
        query_embeddings = await client.embed([query])
        query_vec = query_embeddings[0]
    finally:
        await client.close()

    async with embedding_repos() as (emb_repo, proc_repo, _db):
        similar = await emb_repo.similarity_search(
            query_vec,
            limit=limit * 2 if channel_id else limit,
            threshold=threshold,
        )

        results: list[SearchResult] = []
        for sim in similar:
            doc = await proc_repo.get_by_source_ref(sim.source_ref)
            if channel_id and doc and doc.channel_id != channel_id:
                continue
            results.append(
                SearchResult(
                    source_ref=sim.source_ref,
                    score=sim.score,
                    document=doc,
                )
            )
            if len(results) >= limit:
                break

        return results


async def answer(
    question: str,
    channel_id: str | None = None,
    limit: int = 5,
) -> AnswerResult:
    """
    RAG Q&A: retrieve relevant documents, build prompt, call LLM for answer.

    Args:
        question: User question in natural language
        channel_id: Optional channel filter
        limit: Number of context documents to retrieve

    Returns:
        AnswerResult with generated answer and sources
    """
    results = await search(question, channel_id=channel_id, limit=limit)

    if not results:
        return AnswerResult(
            answer="Не найдено релевантных документов для ответа на вопрос.",
            sources=[],
        )

    context_parts: list[str] = []
    for i, r in enumerate(results, 1):
        if r.document:
            title = r.document.summary or r.document.text_clean[:100]
            context_parts.append(
                f"[{i}] (score={r.score:.3f}) {title}\n{r.document.text_clean[:800]}"
            )

    context = "\n---\n".join(context_parts)

    prompt = (
        "Ты — ассистент, отвечающий на вопросы по контенту Telegram-каналов.\n"
        "Используй только предоставленный контекст для ответа.\n"
        "Если контекст не содержит ответа — скажи об этом.\n"
        "Ссылайся на источники по номерам [1], [2], ...\n\n"
        f"Контекст:\n{context}\n\n"
        f"Вопрос: {question}\n\n"
        "Ответ:"
    )

    answer_text, model_used = await _call_llm(prompt)

    return AnswerResult(
        answer=answer_text,
        sources=results,
        model=model_used,
    )


async def _call_llm(prompt: str) -> tuple[str, str | None]:
    """Call the LLM for answer generation. Returns (answer_text, model_name)."""
    import httpx

    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for Q&A")

    model = settings.llm_model or "gpt-4o-mini"

    async with httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60.0,
    ) as client:
        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 2048,
            },
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        return text.strip(), model
