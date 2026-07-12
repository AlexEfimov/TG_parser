"""
Retrieval service (P5 RAG).

Provides semantic search and LLM-powered Q&A over the embedded document corpus.
Prompts are loaded from YAML via PromptLoader with fallback to built-in defaults.
LLM provider/model resolved via LLMConfigManager scope "rag".
"""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import structlog

from tg_parser.config import settings
from tg_parser.domain.models import ProcessedDocument, TopicCard
from tg_parser.services._ranking import rrf_fuse
from tg_parser.services.db_context import embedding_repos, topic_embedding_repos
from tg_parser.services.embedding_service import (
    create_embedding_client,
    get_embedding_client,
)
from tg_parser.storage.ports import EmbeddingRepo, ProcessedDocumentRepo, TopicCardRepo

SearchMode = Literal["semantic", "keyword", "hybrid"]

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
    mode: SearchMode = "hybrid",
    fts_min_rank: float | None = None,
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
) -> list[SearchResult]:
    """
    Hybrid retrieval over the processed corpus.

    Args:
        query: Natural language query
        channel_id: Optional single-channel filter
        limit: Max results to return
        threshold: Minimum cosine similarity score (semantic path only)
        include_topics: Include topic embeddings in search (hybrid RAG)
        allowed_channel_ids: Tenant scoping — None=admin (all), []=no access, [ch1,...]=filter
        mode: Retrieval strategy — ``"semantic"`` (pgvector cosine),
            ``"keyword"`` (FTS ts_rank_cd), or ``"hybrid"`` (both via
            Reciprocal Rank Fusion). Defaults to ``"hybrid"``. When the
            global ``hybrid_enabled`` setting is False, ``"hybrid"`` is
            silently downgraded to ``"semantic"``.
        fts_min_rank: Optional override for ``ts_rank_cd`` cutoff applied to
            the keyword branch (``keyword`` / ``hybrid`` modes). When
            ``None`` the global ``settings.fts_min_rank`` default is used.
            Ignored by the semantic branch (which uses ``threshold``).
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

    effective_mode: SearchMode = mode
    if effective_mode == "hybrid" and not settings.hybrid_enabled:
        effective_mode = "semantic"

    effective_min_rank = fts_min_rank if fts_min_rank is not None else settings.fts_min_rank

    entry_types = ["message", "topic"] if include_topics else ["message"]
    fetch_limit = limit * 2 if channel_id else limit

    query_vec: list[float] | None = None
    if effective_mode in ("semantic", "hybrid"):
        # O-9b (F-11): reuse one embedding client per event loop instead of a
        # per-request create/close. ``create_embedding_client`` is passed as the
        # factory so it stays patchable at this module seam (existing tests) and
        # is only invoked on the loop's first query. The client is closed once on
        # app shutdown via ``close_embedding_client``.
        client = get_embedding_client(factory=create_embedding_client)
        query_embeddings = await client.embed([query])
        query_vec = query_embeddings[0]

    async with contextlib.AsyncExitStack() as stack:
        # DI-15: when no DI is supplied, hybrid mode opens TWO independent
        # embedding_repos contexts so the parallel semantic+keyword tasks
        # below do not share a single AsyncSession. SQLAlchemy AsyncSession
        # forbids concurrent operations on the same session — `asyncio.gather`
        # over a shared session races on `_connection_for_bind()` and surfaces
        # as IllegalStateChangeError at session-close time.
        #
        # When emb_repo/proc_repo IS injected (tests with AsyncMock), we keep
        # backward compat: use the injected repo for both branches but execute
        # sequentially (mocks have no real session — safe).
        di_supplied = emb_repo is not None or proc_repo is not None
        run_hybrid_parallel = effective_mode == "hybrid" and not di_supplied

        if run_hybrid_parallel:
            emb_repo_sem, proc_repo, _db = await stack.enter_async_context(embedding_repos())
            emb_repo_kw, _proc_kw, _db_kw = await stack.enter_async_context(embedding_repos())
        else:
            if emb_repo is None or proc_repo is None:
                emb_repo, proc_repo, _db = await stack.enter_async_context(embedding_repos())
            emb_repo_sem = emb_repo_kw = emb_repo

        if topic_card_repo is None and include_topics:
            _emb2, topic_card_repo, _db2 = await stack.enter_async_context(topic_embedding_repos())

        if effective_mode == "semantic":
            similar = await emb_repo_sem.similarity_search(
                query_vec,
                limit=fetch_limit,
                threshold=threshold,
                entry_types=entry_types,
                channel_ids=effective_channel_ids,
            )
        elif effective_mode == "keyword":
            similar = await emb_repo_kw.keyword_search(
                query,
                limit=fetch_limit,
                entry_types=entry_types,
                channel_ids=effective_channel_ids,
                min_rank=effective_min_rank,
            )
        else:
            sem_task = emb_repo_sem.similarity_search(
                query_vec,
                limit=fetch_limit,
                threshold=threshold,
                entry_types=entry_types,
                channel_ids=effective_channel_ids,
            )
            kw_task = emb_repo_kw.keyword_search(
                query,
                limit=fetch_limit,
                entry_types=entry_types,
                channel_ids=effective_channel_ids,
                min_rank=effective_min_rank,
            )
            if run_hybrid_parallel:
                sem, kw = await asyncio.gather(sem_task, kw_task)
            else:
                # DI mode: sequential execution, no concurrent session access.
                sem = await sem_task
                kw = await kw_task
            similar = rrf_fuse(sem, kw, k=settings.hybrid_rrf_k)[:fetch_limit]

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
                results.append(
                    SearchResult(
                        source_ref=sim.source_ref,
                        score=sim.score,
                        document=doc,
                        entry_type="message",
                    )
                )
            elif sim.entry_type == "topic":
                card = card_map.get(sim.topic_id) if sim.topic_id else None
                if card:
                    if channel_id and channel_id not in card.sources:
                        continue
                    if allowed_channel_ids is not None:
                        if not any(s in allowed_channel_ids for s in card.sources):
                            continue
                results.append(
                    SearchResult(
                        source_ref=sim.source_ref,
                        score=sim.score,
                        entry_type="topic",
                        topic_card=card,
                    )
                )

            if len(results) >= limit:
                break

        return results


def _load_rag_config() -> dict:
    """Load RAG prompt config via PromptLoader."""
    from tg_parser.processing.prompt_loader import get_prompt_loader

    return get_prompt_loader().load("rag")


def _apply_type_quotas(
    results: list[SearchResult],
    limit: int,
    topic_quota: int,
) -> list[SearchResult]:
    """Split results by entry_type, apply quotas with underflow fallback.

    Rules:
    - Take up to ``topic_quota`` topics (score order preserved from ``search()``).
    - Fill remaining slots (``limit - len(picked_topics)``) with messages.
    - Underflow fallback: if too few messages, backfill remaining slots with
      extra topics (beyond the initial quota).
    - Output order: ALL topics first, then ALL messages (stable section-ordering
      for downstream ``_build_context``).
    - Never exceeds ``limit``; returns ``[]`` on empty input.

    This is a pure function — no DB, no I/O, no mutation of inputs.
    """
    if not results:
        return []

    topics = [r for r in results if r.entry_type == "topic"]
    messages = [r for r in results if r.entry_type != "topic"]

    picked_topics = topics[:topic_quota]
    remaining = limit - len(picked_topics)
    picked_messages = messages[:remaining]

    shortfall = limit - len(picked_topics) - len(picked_messages)
    if shortfall > 0 and len(topics) > len(picked_topics):
        extra_topics = topics[len(picked_topics) : len(picked_topics) + shortfall]
        picked_topics = picked_topics + extra_topics

    return picked_topics + picked_messages


def _build_context(results: list[SearchResult], char_limit: int) -> str:
    """Build structured RAG context with separate topic and message sections.

    Output format (both sections optional; empty when no matches of that type):

        ## Related Topics

        [T1] ref: <topic_id> | channels: <csv> | score: <float>
        Title: <card.title>
        Summary: <card.summary>
        Scope: <csv>            (when scope_in non-empty)
        Tags: <csv>             (when tags non-empty)

        ---

        [T2] ...

        ## Source Messages

        [M1] channel: <id> | ref: <source_ref> | score: <float>
        Title: <summary or text_clean[:80]>
        Text: <text_clean[:char_limit]>
        Topics: <csv>           (when topics non-empty)

        ---

        [M2] ...

    Rules:
    - Empty sections are omitted (no trailing "## Related Topics\n\n" left over).
    - Between blocks within a section: "\n\n---\n\n".
    - Between sections: "\n\n".
    - Score displayed with 3 decimals (".3f") for better hybrid-mode signal.
    - Order within a section is preserved from ``results`` (score-desc upstream).
    - Entries without an attached document/topic_card are silently skipped.
    """
    topics = [r for r in results if r.entry_type == "topic" and r.topic_card is not None]
    messages = [r for r in results if r.entry_type != "topic" and r.document is not None]

    sections: list[str] = []

    if topics:
        blocks: list[str] = []
        for i, r in enumerate(topics, 1):
            card = r.topic_card
            channels = ", ".join(card.sources) if card.sources else "unknown"
            header = f"[T{i}] ref: {r.source_ref} | channels: {channels} | score: {r.score:.3f}"
            body_lines = [f"Title: {card.title}", f"Summary: {card.summary}"]
            if card.scope_in:
                body_lines.append(f"Scope: {', '.join(card.scope_in)}")
            if card.tags:
                body_lines.append(f"Tags: {', '.join(card.tags)}")
            blocks.append(header + "\n" + "\n".join(body_lines))
        sections.append("## Related Topics\n\n" + "\n\n---\n\n".join(blocks))

    if messages:
        blocks = []
        for i, r in enumerate(messages, 1):
            doc = r.document
            title = doc.summary or doc.text_clean[:80]
            header = (
                f"[M{i}] channel: {doc.channel_id} | ref: {r.source_ref} | score: {r.score:.3f}"
            )
            body_lines = [f"Title: {title}", f"Text: {doc.text_clean[:char_limit]}"]
            if doc.topics:
                body_lines.append(f"Topics: {', '.join(doc.topics)}")
            blocks.append(header + "\n" + "\n".join(body_lines))
        sections.append("## Source Messages\n\n" + "\n\n---\n\n".join(blocks))

    return "\n\n".join(sections)


async def answer(
    question: str,
    channel_id: str | None = None,
    limit: int = 5,
    allowed_channel_ids: list[str] | None = None,
    mode: SearchMode = "hybrid",
    topic_quota: int | None = None,
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
        mode: Retrieval strategy forwarded to ``search()``.
        topic_quota: Optional override for number of topic cards reserved in
            the LLM context. Falls back to ``settings.rag_topic_quota`` when
            ``None``. Clamped to ``limit``. ``_apply_type_quotas`` performs
            underflow fallback when topics or messages are scarce.
        emb_repo: Optional DI for EmbeddingRepo
        proc_repo: Optional DI for ProcessedDocumentRepo
        llm_client: Optional DI for LLMClient (if None, created via factory)

    Returns:
        AnswerResult with generated answer and sources (≤ ``limit``).
    """
    effective_topic_quota = topic_quota if topic_quota is not None else settings.rag_topic_quota
    effective_topic_quota = min(effective_topic_quota, limit)
    overfetch = max(1, settings.rag_search_overfetch_factor)

    raw_results = await search(
        question,
        channel_id=channel_id,
        limit=limit * overfetch,
        allowed_channel_ids=allowed_channel_ids,
        mode=mode,
        emb_repo=emb_repo,
        proc_repo=proc_repo,
    )

    results = _apply_type_quotas(raw_results, limit=limit, topic_quota=effective_topic_quota)

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
