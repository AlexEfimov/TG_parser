"""
Retrieval service (P5 RAG).

Provides semantic search and LLM-powered Q&A over the embedded document corpus.
Prompts are loaded from YAML via PromptLoader with fallback to built-in defaults.
LLM provider/model resolved via LLMConfigManager scope "rag".
"""

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from tg_parser.config import settings
from tg_parser.domain.models import ProcessedDocument, TopicCard
from tg_parser.services.db_context import embedding_repos, topic_embedding_repos
from tg_parser.services.embedding_service import create_embedding_client
from tg_parser.storage.ports import EmbeddingRepo, ProcessedDocumentRepo, TopicCardRepo

if TYPE_CHECKING:
    from tg_parser.processing.ports import LLMClient

logger = structlog.get_logger(__name__)


@dataclass
class SearchResult:
    """A document or topic returned by similarity search."""
    source_ref: str
    score: float
    document: ProcessedDocument | None = None
    entry_type: str = "message"
    topic_card: TopicCard | None = None


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
    include_topics: bool = True,
    allowed_channel_ids: list[str] | None = None,
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
) -> list[SearchResult]:
    """
    Hybrid semantic search: embed query, find similar documents and topics via pgvector.

    Args:
        query: Natural language query
        channel_id: Optional single-channel filter
        limit: Max results to return
        threshold: Minimum cosine similarity score
        include_topics: Include topic embeddings in search (hybrid RAG)
        allowed_channel_ids: Tenant scoping — None=admin (all), []=no access, [ch1,...]=filter
        emb_repo: Optional DI for EmbeddingRepo
        proc_repo: Optional DI for ProcessedDocumentRepo
        topic_card_repo: Optional DI for TopicCardRepo

    Returns:
        Ranked list of SearchResult (messages and topics mixed by score)
    """
    from tg_parser.auth.ownership import PermissionDenied

    if allowed_channel_ids is not None and len(allowed_channel_ids) == 0:
        return []

    if channel_id and allowed_channel_ids is not None:
        if channel_id not in allowed_channel_ids:
            raise PermissionDenied(f"No access to channel {channel_id}")

    effective_channel_ids: list[str] | None
    if channel_id:
        effective_channel_ids = [channel_id]
    elif allowed_channel_ids is not None:
        effective_channel_ids = allowed_channel_ids
    else:
        effective_channel_ids = None

    client = create_embedding_client()
    try:
        query_embeddings = await client.embed([query])
        query_vec = query_embeddings[0]
    finally:
        await client.close()

    entry_types = ["message", "topic"] if include_topics else ["message"]

    async with contextlib.AsyncExitStack() as stack:
        if emb_repo is None or proc_repo is None:
            emb_repo, proc_repo, _db = await stack.enter_async_context(
                embedding_repos()
            )
        if topic_card_repo is None and include_topics:
            _emb2, topic_card_repo, _db2 = await stack.enter_async_context(
                topic_embedding_repos()
            )

        similar = await emb_repo.similarity_search(
            query_vec,
            limit=limit * 2 if channel_id else limit,
            threshold=threshold,
            entry_types=entry_types,
            channel_ids=effective_channel_ids,
        )

        msg_refs = [s.source_ref for s in similar if s.entry_type == "message"]
        topic_ids = [s.topic_id for s in similar if s.entry_type == "topic" and s.topic_id]

        doc_map = await proc_repo.get_by_source_refs(msg_refs) if msg_refs else {}

        card_map: dict[str, TopicCard] = {}
        if topic_ids and topic_card_repo is not None:
            for tid in topic_ids:
                card = await topic_card_repo.get_by_id(tid)
                if card is not None:
                    card_map[tid] = card

        results: list[SearchResult] = []
        for sim in similar:
            if sim.entry_type == "message":
                doc = doc_map.get(sim.source_ref)
                results.append(SearchResult(
                    source_ref=sim.source_ref,
                    score=sim.score,
                    document=doc,
                    entry_type="message",
                ))
            elif sim.entry_type == "topic":
                card = card_map.get(sim.topic_id) if sim.topic_id else None
                if card:
                    if channel_id and channel_id not in card.sources:
                        continue
                    if allowed_channel_ids is not None:
                        if not any(s in allowed_channel_ids for s in card.sources):
                            continue
                results.append(SearchResult(
                    source_ref=sim.source_ref,
                    score=sim.score,
                    entry_type="topic",
                    topic_card=card,
                ))

            if len(results) >= limit:
                break

        return results


def _load_rag_config() -> dict:
    """Load RAG prompt config via PromptLoader."""
    from tg_parser.processing.prompt_loader import get_prompt_loader
    return get_prompt_loader().load("rag")


def _build_context(results: list[SearchResult], char_limit: int) -> str:
    """Build context string from search results (messages and topics)."""
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        if r.entry_type == "topic" and r.topic_card is not None:
            card = r.topic_card
            channels = ", ".join(card.sources) if card.sources else "unknown"
            header = f"[{i}] [TOPIC] channels: {channels} | ref: {r.source_ref} | score: {r.score:.2f}"
            body = f"Title: {card.title}\nSummary: {card.summary}"
            scope = ", ".join(card.scope_in) if card.scope_in else ""
            if scope:
                body += f"\nScope: {scope}"
            tags = ", ".join(card.tags) if card.tags else ""
            if tags:
                body += f"\nTags: {tags}"
            parts.append(f"{header}\n{body}")
        elif r.document is not None:
            doc = r.document
            title = doc.summary or doc.text_clean[:100]
            topics_str = ", ".join(doc.topics) if doc.topics else ""

            header = f"[{i}] channel: {doc.channel_id} | ref: {r.source_ref} | source_ref: {r.source_ref} | score: {r.score:.2f}"
            body = f"Title: {title}\nText: {doc.text_clean[:char_limit]}"
            if topics_str:
                body += f"\nTopics: {topics_str}"

            parts.append(f"{header}\n{body}")

    return "\n---\n".join(parts)


async def answer(
    question: str,
    channel_id: str | None = None,
    limit: int = 5,
    allowed_channel_ids: list[str] | None = None,
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
        allowed_channel_ids: Tenant scoping — None=admin (all)
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
        allowed_channel_ids=allowed_channel_ids,
        emb_repo=emb_repo,
        proc_repo=proc_repo,
    )

    rag_config = _load_rag_config()

    if not results:
        no_results_msg = (
            rag_config.get("no_results", {}).get("message")
            or "Не найдено релевантных документов для ответа на вопрос."
        )
        return AnswerResult(answer=no_results_msg, sources=[])

    model_settings = rag_config.get("model", {})
    char_limit = model_settings.get("context_char_limit", 1500)

    context = _build_context(results, char_limit)

    system_prompt = rag_config.get("system", {}).get("prompt", "")
    user_template = rag_config.get("user", {}).get(
        "template",
        "<context>\n{context}\n</context>\n\n<question>\n{question}\n</question>",
    )
    user_prompt = user_template.format(context=context, question=question)

    default_temperature = model_settings.get("temperature", 0.2)
    default_max_tokens = model_settings.get("max_tokens", 2048)

    answer_text, model_used = await _call_llm(
        user_prompt,
        system_prompt=system_prompt,
        temperature=default_temperature,
        max_tokens=default_max_tokens,
        llm_client=llm_client,
    )

    return AnswerResult(
        answer=answer_text,
        sources=results,
        model=model_used,
    )


async def _call_llm(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 2048,
    llm_client: "LLMClient | None" = None,
) -> tuple[str, str | None]:
    """Call the LLM for answer generation. Returns (answer_text, model_name)."""
    from tg_parser.config import llm_config

    rag_full = llm_config.resolve_full("rag")

    if llm_client is None:
        from tg_parser.processing.llm.factory import create_llm_client

        llm_client = create_llm_client(
            provider=rag_full["provider"],
            api_key=rag_full["api_key"],
            model=rag_full["model"],
            base_url=settings.openai_base_url if rag_full["provider"] == "openai" else None,
        )

    _rt = rag_full.get("temperature")
    effective_temp = _rt if _rt is not None else temperature
    _rm = rag_full.get("max_tokens")
    effective_max = _rm if _rm is not None else max_tokens

    text = await llm_client.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=effective_temp,
        max_tokens=effective_max,
    )
    model_name = getattr(llm_client, "model", None) or settings.llm_model
    return text.strip(), model_name
