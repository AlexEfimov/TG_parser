"""
Embedding service (P5 RAG).

Orchestrates embedding generation for processed documents
using OpenAI's text-embedding API and stores results via EmbeddingRepo.
"""

import logging
from typing import Any, Protocol

from tg_parser.config import settings
from tg_parser.services.db_context import embedding_repos

logger = logging.getLogger(__name__)


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
    ):
        self.api_key = api_key
        self.model = model
        self._client: Any = None

    async def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url="https://api.openai.com/v1",
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


def _create_embedding_client() -> OpenAIEmbeddingClient:
    """Create an embedding client from global settings."""
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for embedding generation")
    return OpenAIEmbeddingClient(
        api_key=api_key,
        model=settings.embedding_model,
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
) -> dict[str, int]:
    """
    Embed all processed documents for a channel.

    Args:
        channel_id: Channel identifier
        force: Re-embed documents that already have embeddings

    Returns:
        Statistics dict (embedded_count, skipped_count, total_count)
    """
    client = _create_embedding_client()
    batch_size = settings.embedding_batch_size
    model = settings.embedding_model

    try:
        async with embedding_repos() as (emb_repo, proc_repo, _db):
            if force:
                docs = await proc_repo.list_by_channel(channel_id)
                source_refs_to_embed = [d.source_ref for d in docs]
            else:
                source_refs_to_embed = await emb_repo.list_missing(channel_id)
                docs = []
                for ref in source_refs_to_embed:
                    doc = await proc_repo.get_by_source_ref(ref)
                    if doc:
                        docs.append(doc)

            total_count = len(docs)
            if not docs:
                logger.info("No documents to embed for channel %s", channel_id)
                return {"embedded_count": 0, "skipped_count": 0, "total_count": 0}

            doc_map = {d.source_ref: d for d in docs}
            refs_to_embed = [ref for ref in source_refs_to_embed if ref in doc_map]

            embedded_count = 0

            for i in range(0, len(refs_to_embed), batch_size):
                batch_refs = refs_to_embed[i : i + batch_size]
                texts = [
                    _prepare_text(doc_map[ref].text_clean, doc_map[ref].summary)
                    for ref in batch_refs
                ]

                embeddings = await client.embed(texts)

                items = []
                for ref, emb in zip(batch_refs, embeddings):
                    items.append((ref, emb, model, None))

                saved = await emb_repo.save_batch(items)
                embedded_count += saved

                logger.info(
                    "Embedded batch %d-%d / %d",
                    i + 1,
                    min(i + batch_size, len(refs_to_embed)),
                    len(refs_to_embed),
                )

            skipped_count = total_count - embedded_count
            logger.info(
                "Embedding complete for %s: %d embedded, %d skipped, %d total",
                channel_id, embedded_count, skipped_count, total_count,
            )

            return {
                "embedded_count": embedded_count,
                "skipped_count": skipped_count,
                "total_count": total_count,
            }
    finally:
        await client.close()


async def run_incremental_embedding(doc_refs: list[str]) -> dict[str, int]:
    """
    Embed only specific documents (used by scheduler after processing).

    Args:
        doc_refs: List of source_refs to embed

    Returns:
        Statistics dict
    """
    if not doc_refs:
        return {"embedded_count": 0, "total_count": 0}

    client = _create_embedding_client()
    batch_size = settings.embedding_batch_size
    model = settings.embedding_model

    try:
        async with embedding_repos() as (emb_repo, proc_repo, _db):
            docs = []
            for ref in doc_refs:
                doc = await proc_repo.get_by_source_ref(ref)
                if doc:
                    docs.append(doc)

            if not docs:
                return {"embedded_count": 0, "total_count": 0}

            embedded_count = 0
            for i in range(0, len(docs), batch_size):
                batch = docs[i : i + batch_size]
                texts = [_prepare_text(d.text_clean, d.summary) for d in batch]

                embeddings = await client.embed(texts)

                items = [
                    (d.source_ref, emb, model, None)
                    for d, emb in zip(batch, embeddings)
                ]
                saved = await emb_repo.save_batch(items)
                embedded_count += saved

            return {"embedded_count": embedded_count, "total_count": len(docs)}
    finally:
        await client.close()
