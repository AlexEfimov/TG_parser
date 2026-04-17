"""
Embedding service (P5 RAG).

Orchestrates embedding generation for processed documents
using OpenAI's text-embedding API and stores results via EmbeddingRepo.
"""

import contextlib
import time
from typing import Any, Protocol

import structlog

from tg_parser.config import settings
from tg_parser.services.db_context import embedding_repos, topic_embedding_repos
from tg_parser.storage.ports import EmbeddingRepo, ProcessedDocumentRepo, TopicCardRepo

logger = structlog.get_logger(__name__)


class EmbeddingClient(Protocol):
    """Minimal interface for an embedding provider."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def close(self) -> None: ...


class OpenAIEmbeddingClient:
    """OpenAI embeddings via httpx (no extra SDK dependency)."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client: Any = None

    async def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60.0,
            )
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        response = await client.post(
            "/embeddings",
            json={"input": texts, "model": self.model},
        )
        response.raise_for_status()
        data = response.json()
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def create_embedding_client() -> OpenAIEmbeddingClient:
    """Create an embedding client from global settings."""
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for embedding generation")
    return OpenAIEmbeddingClient(
        api_key=api_key,
        model=settings.embedding_model,
        base_url=settings.openai_base_url,
    )


def _prepare_text(text_clean: str, summary: str | None) -> str:
    """Build the text to embed: summary + truncated text_clean."""
    parts: list[str] = []
    if summary:
        parts.append(summary)
    if text_clean:
        parts.append(text_clean[:500])
    return "\n".join(parts) or ""


async def run_embedding(
    channel_id: str,
    force: bool = False,
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
) -> dict[str, int]:
    """
    Embed all processed documents for a channel.

    Args:
        channel_id: Channel identifier
        force: Re-embed documents that already have embeddings
        emb_repo: Optional DI for EmbeddingRepo
        proc_repo: Optional DI for ProcessedDocumentRepo

    Returns:
        Statistics dict (embedded_count, skipped_count, total_count)
    """
    client = create_embedding_client()
    batch_size = settings.embedding_batch_size
    model = settings.embedding_model

    try:
        async with contextlib.AsyncExitStack() as stack:
            if emb_repo is None or proc_repo is None:
                emb_repo, proc_repo, _db = await stack.enter_async_context(embedding_repos())

            if force:
                docs = await proc_repo.list_by_channel(channel_id)
                source_refs_to_embed = [d.source_ref for d in docs]
            else:
                source_refs_to_embed = await emb_repo.list_missing(channel_id)
                doc_map_loaded = await proc_repo.get_by_source_refs(source_refs_to_embed)
                docs = [
                    doc_map_loaded[ref] for ref in source_refs_to_embed if ref in doc_map_loaded
                ]

            total_count = len(docs)
            if not docs:
                logger.info("No documents to embed for channel %s", channel_id)
                return {"embedded_count": 0, "skipped_count": 0, "total_count": 0}

            doc_map = {d.source_ref: d for d in docs}
            refs_to_embed = [ref for ref in source_refs_to_embed if ref in doc_map]

            embedded_count = 0
            total_api_time = 0.0
            total_db_time = 0.0

            for i in range(0, len(refs_to_embed), batch_size):
                batch_refs = refs_to_embed[i : i + batch_size]
                texts = [
                    _prepare_text(doc_map[ref].text_clean, doc_map[ref].summary)
                    for ref in batch_refs
                ]

                api_t0 = time.perf_counter()
                embeddings = await client.embed(texts)
                total_api_time += time.perf_counter() - api_t0

                items = []
                for ref, emb in zip(batch_refs, embeddings, strict=False):
                    items.append((ref, emb, model, None))

                db_t0 = time.perf_counter()
                saved = await emb_repo.save_batch(items, channel_ids=[channel_id])
                total_db_time += time.perf_counter() - db_t0
                embedded_count += saved

                logger.info(
                    "Embedded batch %d-%d / %d",
                    i + 1,
                    min(i + batch_size, len(refs_to_embed)),
                    len(refs_to_embed),
                )

            skipped_count = total_count - embedded_count
            logger.info(
                "embedding_complete_timing",
                channel_id=channel_id,
                embedded_count=embedded_count,
                skipped_count=skipped_count,
                total_count=total_count,
                api_time_sec=round(total_api_time, 3),
                db_time_sec=round(total_db_time, 3),
            )

            return {
                "embedded_count": embedded_count,
                "skipped_count": skipped_count,
                "total_count": total_count,
                "api_time_seconds": round(total_api_time, 3),
                "db_time_seconds": round(total_db_time, 3),
            }
    finally:
        await client.close()


async def run_incremental_embedding(
    doc_refs: list[str],
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
) -> dict[str, int]:
    """
    Embed only specific documents (used by scheduler after processing).

    Args:
        doc_refs: List of source_refs to embed
        emb_repo: Optional DI for EmbeddingRepo
        proc_repo: Optional DI for ProcessedDocumentRepo

    Returns:
        Statistics dict
    """
    if not doc_refs:
        return {"embedded_count": 0, "total_count": 0}

    client = create_embedding_client()
    batch_size = settings.embedding_batch_size
    model = settings.embedding_model

    try:
        async with contextlib.AsyncExitStack() as stack:
            if emb_repo is None or proc_repo is None:
                emb_repo, proc_repo, _db = await stack.enter_async_context(embedding_repos())

            doc_map_loaded = await proc_repo.get_by_source_refs(doc_refs)
            docs = [doc_map_loaded[ref] for ref in doc_refs if ref in doc_map_loaded]

            if not docs:
                return {"embedded_count": 0, "total_count": 0}

            embedded_count = 0
            for i in range(0, len(docs), batch_size):
                batch = docs[i : i + batch_size]
                texts = [_prepare_text(d.text_clean, d.summary) for d in batch]

                embeddings = await client.embed(texts)

                items = [
                    (d.source_ref, emb, model, None)
                    for d, emb in zip(batch, embeddings, strict=False)
                ]
                saved = await emb_repo.save_batch(items)
                embedded_count += saved

            return {"embedded_count": embedded_count, "total_count": len(docs)}
    finally:
        await client.close()


def _prepare_topic_text(summary: str, scope_in: list[str]) -> str:
    """Build embedding text from topic card summary and scope."""
    parts = [summary]
    if scope_in:
        parts.append(" | ".join(scope_in))
    return " | ".join(parts)


async def run_topic_embedding(
    channel_id: str,
    topic_ids: list[str] | None = None,
    force: bool = False,
    *,
    emb_repo: EmbeddingRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
) -> dict[str, int]:
    """
    Generate embeddings for topic cards of a channel.

    Args:
        channel_id: Channel identifier
        topic_ids: Specific topic IDs to embed (None = all for channel)
        force: Re-embed topics that already have embeddings
        emb_repo: Optional DI for EmbeddingRepo
        topic_card_repo: Optional DI for TopicCardRepo

    Returns:
        Statistics dict (embedded_count, skipped_count, total_count)
    """
    client = create_embedding_client()
    batch_size = settings.embedding_batch_size
    model = settings.embedding_model

    try:
        async with contextlib.AsyncExitStack() as stack:
            if emb_repo is None or topic_card_repo is None:
                emb_repo, topic_card_repo, _db = await stack.enter_async_context(
                    topic_embedding_repos()
                )

            if topic_ids:
                cards = []
                for tid in topic_ids:
                    card = await topic_card_repo.get_by_id(tid)
                    if card is not None:
                        cards.append(card)
            else:
                cards = await topic_card_repo.list_by_channel(channel_id)

            if not force:
                filtered = []
                for card in cards:
                    existing = await emb_repo.get_by_source_ref(card.id)
                    if existing is None:
                        filtered.append(card)
                cards = filtered

            total_count = len(cards)
            if not cards:
                logger.info("No topic cards to embed for channel %s", channel_id)
                return {"embedded_count": 0, "skipped_count": 0, "total_count": 0}

            embedded_count = 0
            for i in range(0, len(cards), batch_size):
                batch = cards[i : i + batch_size]
                texts = [_prepare_topic_text(c.summary, c.scope_in) for c in batch]

                embeddings = await client.embed(texts)

                for card, emb in zip(batch, embeddings, strict=False):
                    await emb_repo.save(
                        source_ref=card.id,
                        embedding=emb,
                        model=model,
                        entry_type="topic",
                        topic_id=card.id,
                        channel_ids=list(card.sources),
                    )
                embedded_count += len(batch)

            skipped_count = total_count - embedded_count
            logger.info(
                "topic_embedding_complete",
                channel_id=channel_id,
                embedded_count=embedded_count,
                skipped_count=skipped_count,
                total_count=total_count,
            )
            return {
                "embedded_count": embedded_count,
                "skipped_count": skipped_count,
                "total_count": total_count,
            }
    finally:
        await client.close()
