"""
Retrieval service (P5 RAG).

Provides semantic search and LLM-powered Q&A over the embedded document corpus.
"""

import contextlib
import logging
from dataclasses import dataclass

from typing import TYPE_CHECKING

from tg_parser.config import settings
from tg_parser.domain.models import ProcessedDocument
from tg_parser.services.db_context import embedding_repos
from tg_parser.services.embedding_service import create_embedding_client
from tg_parser.storage.ports import EmbeddingRepo, ProcessedDocumentRepo

if TYPE_CHECKING:
    from tg_parser.processing.ports import LLMClient

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


async def search(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    threshold: float = 0.0,
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
) -> list[SearchResult]:
    """
    Semantic search: embed query, find similar documents via pgvector.

    Args:
        query: Natural language query
        channel_id: Optional filter (post-filter, not pre-filter)
        limit: Max results to return
        threshold: Minimum cosine similarity score
        emb_repo: Optional DI for EmbeddingRepo
        proc_repo: Optional DI for ProcessedDocumentRepo

    Returns:
        Ranked list of SearchResult
    """
    client = create_embedding_client()
    try:
        query_embeddings = await client.embed([query])
        query_vec = query_embeddings[0]
    finally:
        await client.close()

    async with contextlib.AsyncExitStack() as stack:
        if emb_repo is None or proc_repo is None:
            emb_repo, proc_repo, _db = await stack.enter_async_context(
                embedding_repos()
            )

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
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
    llm_client: "LLMClient | None" = None,
) -> AnswerResult:
    """
    RAG Q&A: retrieve relevant documents, build prompt, call LLM for answer.

    Args:
        question: User question in natural language
        channel_id: Optional channel filter
        limit: Number of context documents to retrieve
        emb_repo: Optional DI for EmbeddingRepo
        proc_repo: Optional DI for ProcessedDocumentRepo
        llm_client: Optional DI for LLMClient (if None, created via factory)

    Returns:
        AnswerResult with generated answer and sources
    """
    results = await search(
        question,
        channel_id=channel_id,
        limit=limit,
        emb_repo=emb_repo,
        proc_repo=proc_repo,
    )

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

    answer_text, model_used = await _call_llm(prompt, llm_client=llm_client)

    return AnswerResult(
        answer=answer_text,
        sources=results,
        model=model_used,
    )


async def _call_llm(
    prompt: str,
    *,
    llm_client: "LLMClient | None" = None,
) -> tuple[str, str | None]:
    """Call the LLM for answer generation. Returns (answer_text, model_name)."""
    if llm_client is None:
        from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config

        provider, api_key, model = resolve_llm_config("processing")
        llm_client = create_llm_client(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=settings.openai_base_url if provider == "openai" else None,
        )

    text = await llm_client.generate(
        prompt=prompt,
        temperature=0.2,
        max_tokens=2048,
    )
    model_name = getattr(llm_client, "model", None) or settings.llm_model
    return text.strip(), model_name
