"""
Embedding service (P5 RAG).

Orchestrates embedding generation for processed documents
using OpenAI's text-embedding API and stores results via EmbeddingRepo.
"""

import asyncio
import contextlib
import random
import re
import time
import weakref
from collections.abc import Callable
from typing import Any, Protocol

import structlog

from tg_parser.config import settings
from tg_parser.services.db_context import embedding_repos, topic_embedding_repos
from tg_parser.storage.ports import EmbeddingRepo, ProcessedDocumentRepo, TopicCardRepo

logger = structlog.get_logger(__name__)

# BUG-084: HTTP statuses that are ALWAYS transient (retry with backoff). ``429``
# is deliberately NOT in this set — it is classified by ``error.code`` first:
# ``rate_limit_exceeded`` is transient (retry), ``insufficient_quota`` is terminal
# (billing/tier state — retrying only burns latency/attempts). Provider overload
# is ``503``, not ``429`` (see BUG_LOG §BUG-084 Update 2026-07-12).
_RETRYABLE_STATUS_CODES = {500, 502, 503, 529}


class EmbeddingError(Exception):
    """Base error for embedding-provider failures (BUG-084)."""


class EmbeddingRateLimitError(EmbeddingError):
    """Transient rate-limit exhausted.

    Raised after the retry budget is spent on a transient ``429``
    (``rate_limit_exceeded``) or a retryable ``5xx`` — the condition is expected
    to clear on its own, so callers may degrade gracefully (RAG → keyword) and
    the situation is observable as ``outcome="rate_limited"``.
    """


class EmbeddingQuotaError(EmbeddingError):
    """Terminal insufficient-quota — retry is futile.

    Raised IMMEDIATELY (no retry) on a ``429`` whose ``error.code`` is
    ``insufficient_quota``: the credit / usage cap is exhausted, which is a
    billing/tier state that code cannot recover from. Observable as
    ``outcome="quota_exhausted"``.
    """


class EmbeddingClient(Protocol):
    """Minimal interface for an embedding provider."""

    async def embed(
        self, texts: list[str], *, max_retries: int | None = None
    ) -> list[list[float]]: ...
    async def close(self) -> None: ...


class OpenAIEmbeddingClient:
    """OpenAI embeddings via httpx (no extra SDK dependency)."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1",
        max_retries: int = 5,
        retry_max_wait_s: float = 60.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._max_retries = max_retries
        self._retry_max_wait_s = retry_max_wait_s
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

    async def embed(
        self, texts: list[str], *, max_retries: int | None = None
    ) -> list[list[float]]:
        """Embed ``texts`` with classify-by-``error.code`` retry/backoff (BUG-084).

        Retries ONLY transient ``rate_limit_exceeded`` (+ ``{500,502,503,529}``),
        honoring ``Retry-After`` → ``x-ratelimit-reset-*`` → jittered exponential
        backoff. On exhausting the (per-call) budget raises
        :class:`EmbeddingRateLimitError`. A terminal ``insufficient_quota`` raises
        :class:`EmbeddingQuotaError` IMMEDIATELY (no retry). ``max_retries``
        overrides the client's default budget per call site (the RAG query path
        passes a smaller budget than background/ingestion).
        """
        client = await self._get_client()
        attempts = self._max_retries if max_retries is None else max_retries
        attempts = max(1, attempts)

        for attempt in range(1, attempts + 1):
            response = await client.post(
                "/embeddings",
                json={"input": texts, "model": self.model},
            )
            status = getattr(response, "status_code", 200)

            if status == 429:
                code = self._classify_error_code(response)
                if code == "insufficient_quota":
                    logger.error(
                        "embedding_quota_exhausted",
                        code=code,
                        request_id=response.headers.get("x-request-id"),
                    )
                    raise EmbeddingQuotaError(
                        "OpenAI embeddings insufficient_quota (terminal — billing/tier "
                        "action required, retry is futile)"
                    )
                # Transient rate_limit_exceeded (or an unclassified 429): retryable.
                if attempt < attempts:
                    wait = self._compute_backoff(response, attempt)
                    logger.warning(
                        "embedding_rate_limited_retry",
                        code=code or "rate_limit_exceeded",
                        attempt=attempt,
                        max_retries=attempts,
                        retry_in=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error(
                    "embedding_rate_limit_exhausted",
                    code=code or "rate_limit_exceeded",
                    attempts=attempts,
                )
                raise EmbeddingRateLimitError(
                    f"OpenAI embeddings rate-limited after {attempts} attempts"
                )

            if status in _RETRYABLE_STATUS_CODES:
                if attempt < attempts:
                    wait = self._compute_backoff(response, attempt)
                    logger.warning(
                        "embedding_5xx_retry",
                        status=status,
                        attempt=attempt,
                        max_retries=attempts,
                        retry_in=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error("embedding_5xx_exhausted", status=status, attempts=attempts)
                raise EmbeddingRateLimitError(
                    f"OpenAI embeddings HTTP {status} after {attempts} attempts"
                )

            response.raise_for_status()
            data = response.json()
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

        # Defensive: the loop always returns or raises above.
        raise EmbeddingRateLimitError(
            f"OpenAI embeddings exhausted {attempts} attempts"
        )

    @staticmethod
    def _classify_error_code(response: Any) -> str:
        """Extract OpenAI ``error.code`` (falling back to ``error.type``) from a body."""
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — a non-JSON body just means "unclassified"
            return ""
        if not isinstance(body, dict):
            return ""
        err = body.get("error") or {}
        if not isinstance(err, dict):
            return ""
        return err.get("code") or err.get("type") or ""

    def _compute_backoff(self, response: Any, attempt: int) -> float:
        """Honor ``Retry-After`` → ``x-ratelimit-reset-*`` → jittered exp backoff."""
        headers = getattr(response, "headers", {}) or {}
        cap = self._retry_max_wait_s

        val = headers.get("retry-after")
        if val:
            try:
                return min(max(1.0, float(val)), cap)
            except (ValueError, TypeError):
                pass

        for h in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
            parsed = _parse_reset_duration(headers.get(h))
            if parsed is not None:
                return min(max(0.5, parsed), cap)

        return min(2**attempt + random.uniform(0, 1), cap)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _parse_reset_duration(value: str | None) -> float | None:
    """Parse an OpenAI ``x-ratelimit-reset-*`` value into seconds.

    Accepts a bare number (seconds) or a compound duration like ``"1s"``,
    ``"500ms"``, ``"6m0s"``, ``"1h2m3s"``. Returns ``None`` when unparseable.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    total = 0.0
    matched = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)", value):
        matched = True
        num = float(amount)
        if unit == "ms":
            total += num / 1000.0
        elif unit == "s":
            total += num
        elif unit == "m":
            total += num * 60.0
        elif unit == "h":
            total += num * 3600.0
    return total if matched else None


def create_embedding_client() -> OpenAIEmbeddingClient:
    """Create an embedding client from global settings."""
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for embedding generation")
    return OpenAIEmbeddingClient(
        api_key=api_key,
        model=settings.embedding_model,
        base_url=settings.openai_base_url,
        max_retries=settings.embedding_max_retries,
        retry_max_wait_s=settings.embedding_retry_max_wait_s,
    )


# O-9b (review finding F-11, retrieval half): reuse the embedding client across
# RAG queries instead of building + closing a fresh ``httpx.AsyncClient`` per
# ``retrieval_service.search()`` call (a TLS handshake + socket setup every query).
#
# The client is cached PER RUNNING EVENT LOOP, not process-globally: an
# ``httpx.AsyncClient`` is bound to the loop that created it, and CLI commands /
# pytest spin up many short-lived loops (``asyncio.run`` per invocation). A single
# process-wide client would be reused on a *different* loop after its own loop
# closed and raise ``RuntimeError: Event loop is closed``. A ``WeakKeyDictionary``
# keyed by the loop drops each entry automatically once the loop is garbage
# collected, so dead loops never leak and their ids can never be reused.
_loop_embedding_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, EmbeddingClient]" = (
    weakref.WeakKeyDictionary()
)


def get_embedding_client(
    factory: Callable[[], EmbeddingClient] | None = None,
) -> EmbeddingClient:
    """Return a reusable embedding client cached for the current event loop.

    Unlike :func:`create_embedding_client` (a fresh client on every call), this
    returns one client per running loop so the RAG request path avoids a
    per-query TLS handshake. ``factory`` (defaults to
    :func:`create_embedding_client`) is consulted only on a cache miss; callers
    pass their own module reference so it stays patchable in tests.
    """
    loop = asyncio.get_running_loop()
    client = _loop_embedding_clients.get(loop)
    if client is None:
        client = (factory or create_embedding_client)()
        _loop_embedding_clients[loop] = client
    return client


async def close_embedding_client() -> None:
    """Close and drop the current loop's cached embedding client (idempotent).

    Wired into every long-lived shutdown seam (FastAPI lifespan, MCP lifespan,
    bot polling ``finally``) so the reused socket is released exactly once. A
    second call is a no-op. One-shot CLI ``asyncio.run`` loops tear the client
    down implicitly when the loop closes and need no explicit hook.
    """
    loop = asyncio.get_running_loop()
    client = _loop_embedding_clients.pop(loop, None)
    if client is not None:
        await client.close()


def reset_embedding_client_cache() -> None:
    """Drop all cached clients without closing them (test-isolation helper)."""
    _loop_embedding_clients.clear()


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

                # BUG-064: persist each message-embedding row with its per-doc
                # ``channel_ids`` (mirrors ``run_embedding``'s
                # ``channel_ids=[channel_id]``). Without this the rows land
                # with ``channel_ids=[]`` and the near-duplicate observer's
                # channel-scoped similarity search (``channel_ids && ARRAY[...]``)
                # never overlaps, so ``tg_dedup_near_duplicates_detected_total``
                # stays 0. ``save_batch`` applies one ``channel_ids`` list per
                # call, so group the batch by channel before persisting (docs
                # in one tick are normally a single channel, but this stays
                # correct if ``doc_refs`` ever spans channels).
                items_by_channel: dict[str, list[tuple[str, list[float], str, None]]] = {}
                for d, emb in zip(batch, embeddings, strict=False):
                    items_by_channel.setdefault(d.channel_id, []).append(
                        (d.source_ref, emb, model, None)
                    )
                for ch_id, items in items_by_channel.items():
                    saved = await emb_repo.save_batch(items, channel_ids=[ch_id])
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
