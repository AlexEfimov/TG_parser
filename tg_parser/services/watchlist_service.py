"""Watchlist service (F11 Topic Watchlist).

Persistent user-defined interests scored by a hybrid keyword+semantic model.
The scheduler hook calls :meth:`WatchlistService.check_interests` once per
source per tick after :func:`run_incremental_topicization` returns; matches
above ``interest.threshold`` are persisted in ``watch_matches`` and (in
commit 2/2) dispatched through the bot.

Karpathy-like invariants:

- **Persistent entities:** ``WatchInterest`` is the long-lived "page of
  attention"; ``WatchMatch`` is the append-only evidence log.
- **Idempotency:** ``WatchMatchRepo.upsert_many`` uses
  ``ON CONFLICT (interest_id, source_ref) DO NOTHING RETURNING``, so a
  re-run of the pipeline never duplicates matches or notifications.
- **Cheap retrieval cycles:** lazy embedding cache on the interest, single
  ``list_active_for_channel`` per tick, no LLM calls in the hot path.
- **Graceful degradation:** if the document has no embedding (e.g. RAG
  pipeline failed), scoring falls back to the keyword component only.
- **Observability:** :class:`WatchScore` keeps the keyword/semantic
  components separate so a future ``tg_watchlist_matches_total`` metric
  can bucket by score component.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
    WatchMatch,
)
from tg_parser.storage.ports import (
    EmbeddingRepo,
    ProcessedDocumentRepo,
    WatchInterestRepo,
    WatchMatchRepo,
)

if TYPE_CHECKING:
    from tg_parser.services.embedding_service import EmbeddingClient


logger = structlog.get_logger(__name__)


# ----------------------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------------------

#: Combined-score formula: ``combined = KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem``.
#: Sum is exactly 1.0 so the result stays in ``[0, 1]``.
KEYWORD_WEIGHT: float = 0.4
SEMANTIC_WEIGHT: float = 0.6

#: Minimum token length used by :func:`_tokenize`. Mirrors the topicization
#: tokenizer (``MIN_TOKEN_LENGTH = 2``) so short medical/regulatory abbreviations
#: such as "MiCA", "ETF", "ЦБ" are not dropped.
MIN_TOKEN_LENGTH: int = 2

#: Hard cap on the number of new documents scored in a single tick. Protects
#: the scheduler from a back-filled channel producing thousands of new
#: ``new_doc_refs`` at once (notification flood / OpenAI rate-limit risk).
MAX_DOCS_PER_TICK: int = 100


# ----------------------------------------------------------------------------
# Score model
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class WatchScore:
    """Decomposed match score for a single (interest, document) pair.

    ``combined`` is the headline value compared against ``interest.threshold``.
    ``keyword`` and ``semantic`` are kept for telemetry and tuning.
    ``excluded`` is set when an ``exclude_keywords`` token matched the doc;
    in that case ``combined`` is forced to ``0.0`` regardless of the other
    components (negative filter wins).
    ``semantic_available`` reports whether both embeddings were present;
    when False the formula collapses to pure keyword scoring.
    """

    keyword: float
    semantic: float
    combined: float
    excluded: bool
    semantic_available: bool


# ----------------------------------------------------------------------------
# Pure scoring helpers (no I/O — easy to unit-test)
# ----------------------------------------------------------------------------


_TOKEN_RE = re.compile(rf"[a-zA-Zа-яА-ЯёЁ0-9]{{{MIN_TOKEN_LENGTH},}}")


def _tokenize(value: str | None) -> set[str]:
    """Lowercase word tokens of length >= ``MIN_TOKEN_LENGTH``.

    Digits are included because regulatory keywords frequently embed numbers
    (``"MiCA2"``, ``"PSD3"``, ``"NIS2"``).
    """
    if not value:
        return set()
    return {match.lower() for match in _TOKEN_RE.findall(value)}


def _build_doc_tokens(doc: ProcessedDocument) -> set[str]:
    """Tokens used by the keyword scorer.

    Combines structured signal (``topics``, ``summary``) with the cleaned text.
    Topicization may not have run yet (gotcha #10) — falling back to
    ``text_clean`` keeps the watchlist usable in degraded mode.
    """
    tokens: set[str] = set()
    for topic in doc.topics or []:
        tokens |= _tokenize(topic)
    tokens |= _tokenize(doc.summary)
    tokens |= _tokenize(doc.text_clean)
    return tokens


def _keyword_score(interest_keywords: set[str], doc_tokens: set[str]) -> float:
    """Recall-like overlap: ``|interest ∩ doc| / |interest|``.

    Picked over Jaccard because the user explicitly named the keywords they
    care about; a long document with many other words must not dilute the
    signal.
    """
    if not interest_keywords:
        return 0.0
    hits = interest_keywords & doc_tokens
    return len(hits) / len(interest_keywords)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity clipped to ``[0.0, 1.0]``.

    OpenAI ``text-embedding-3-small`` vectors are L2-normalised at the API
    boundary, but the explicit norms keep the formula correct for any client
    (and for the tests, where embeddings are arbitrary fixtures).
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for ai, bi in zip(a, b, strict=True):
        dot += ai * bi
        norm_a += ai * ai
        norm_b += bi * bi
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    sim = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    if sim < 0.0:
        return 0.0
    if sim > 1.0:
        return 1.0
    return sim


def compute_watch_score(
    interest: WatchInterest,
    doc: ProcessedDocument,
    doc_embedding: list[float] | None,
) -> WatchScore:
    """Score a single ``(interest, document)`` pair.

    Returns a :class:`WatchScore` with the full breakdown. The caller compares
    ``score.combined >= interest.threshold`` to decide whether to materialise
    a :class:`WatchMatch`.
    """
    doc_tokens = _build_doc_tokens(doc)

    exclude_tokens: set[str] = set()
    for kw in interest.exclude_keywords:
        exclude_tokens |= _tokenize(kw)
    excluded = bool(exclude_tokens & doc_tokens)

    interest_kw_tokens: set[str] = set()
    for kw in interest.keywords:
        interest_kw_tokens |= _tokenize(kw)

    keyword = _keyword_score(interest_kw_tokens, doc_tokens)

    semantic_available = bool(interest.embedding) and bool(doc_embedding)
    semantic = _cosine(interest.embedding or [], doc_embedding or []) if semantic_available else 0.0

    if excluded:
        combined = 0.0
    elif semantic_available:
        combined = KEYWORD_WEIGHT * keyword + SEMANTIC_WEIGHT * semantic
    else:
        combined = keyword

    if combined < 0.0:
        combined = 0.0
    if combined > 1.0:
        combined = 1.0

    return WatchScore(
        keyword=keyword,
        semantic=semantic,
        combined=combined,
        excluded=excluded,
        semantic_available=semantic_available,
    )


def build_canonical_interest_text(interest: WatchInterest) -> str:
    """Canonical text used to embed an interest.

    Always non-empty — never embed an empty string (gotcha #1: OpenAI 400).
    Order: ``description`` (free-form intent) → ``title`` (short label) →
    keywords joined by spaces. Falls back to ``title + keywords`` if
    description is missing.
    """
    parts: list[str] = []
    if interest.description and interest.description.strip():
        parts.append(interest.description.strip())
    if interest.title and interest.title.strip():
        parts.append(interest.title.strip())
    if interest.keywords:
        parts.append(" ".join(kw for kw in interest.keywords if kw.strip()))
    text = " ".join(part for part in parts if part).strip()
    if not text:
        text = interest.title or "watch interest"
    return text


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------


class WatchlistService:
    """Hybrid keyword+semantic matcher driven by the incremental scheduler.

    Constructor injection mirrors :class:`tg_parser.services.digest_service.DigestService`:
    repositories and the embedding client are passed in explicitly so the
    scheduler can wire production deps and tests can pass fakes.

    Notification dispatch (Bot push, batch grouping) is intentionally out of
    scope for commit 1/2 and lives in :meth:`notify` (added in commit 2/2).
    """

    def __init__(
        self,
        interest_repo: WatchInterestRepo,
        match_repo: WatchMatchRepo,
        processed_doc_repo: ProcessedDocumentRepo,
        embedding_repo: EmbeddingRepo,
        embedding_client: EmbeddingClient | None,
    ) -> None:
        self.interest_repo = interest_repo
        self.match_repo = match_repo
        self.processed_doc_repo = processed_doc_repo
        self.embedding_repo = embedding_repo
        self.embedding_client = embedding_client

    # ---- High-level CRUD helpers (used by bot/MCP/CLI in commit 2/2) ----

    async def create_interest(
        self,
        *,
        user_id: str,
        chat_id: int,
        title: str,
        channel_ids: list[str],
        description: str | None = None,
        keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        threshold: float = 0.6,
        notify_mode: NotifyMode = NotifyMode.INSTANT,
    ) -> WatchInterest:
        """Persist a new interest and eagerly compute its embedding.

        The eager embedding keeps the first scheduler tick fast (no first-tick
        embed latency) and is safe because :func:`build_canonical_interest_text`
        guarantees a non-empty input.
        """
        draft = WatchInterest(
            id="",
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            description=description,
            keywords=list(keywords or []),
            exclude_keywords=list(exclude_keywords or []),
            channel_ids=list(channel_ids),
            threshold=threshold,
            notify_mode=notify_mode,
            is_active=True,
            embedding=None,
        )
        stored = await self.interest_repo.create(draft)

        embedding = await self._embed_interest(stored)
        if embedding is not None:
            await self.interest_repo.update_embedding(stored.id, embedding)
            stored = stored.model_copy(update={"embedding": embedding})

        return stored

    async def soft_delete_interest(self, interest_id: str) -> bool:
        """Mark an interest inactive while preserving its match history."""
        return await self.interest_repo.soft_delete(interest_id)

    # ---- Scheduler hook ----

    async def check_interests(self, channel_id: str, new_doc_refs: list[str]) -> list[WatchMatch]:
        """Score ``new_doc_refs`` against active interests for ``channel_id``.

        Returns the freshly inserted matches (idempotent on re-run thanks to
        the unique constraint). Side-effects:

        - Persists matches via ``WatchMatchRepo.upsert_many``.
        - Updates ``last_checked_at`` on every active interest of the channel.
        - Updates ``last_match_at`` on interests that produced at least one
          new match this tick.
        """
        if not new_doc_refs:
            return []

        active = await self.interest_repo.list_active_for_channel(channel_id)
        if not active:
            logger.debug("watchlist.no_active_interests", channel_id=channel_id)
            return []

        capped_refs = new_doc_refs[:MAX_DOCS_PER_TICK]
        if len(new_doc_refs) > MAX_DOCS_PER_TICK:
            logger.warning(
                "watchlist.docs_capped",
                channel_id=channel_id,
                seen=len(new_doc_refs),
                cap=MAX_DOCS_PER_TICK,
            )

        docs_by_ref = await self.processed_doc_repo.get_by_source_refs(capped_refs)
        if not docs_by_ref:
            logger.debug(
                "watchlist.no_processed_docs",
                channel_id=channel_id,
                refs=len(capped_refs),
            )
            now = datetime.now(UTC)
            for interest in active:
                await self.interest_repo.touch_checked(interest.id, now)
            return []

        embeddings_by_ref: dict[str, list[float] | None] = {}
        for ref in docs_by_ref:
            stored = await self.embedding_repo.get_by_source_ref(ref)
            embeddings_by_ref[ref] = stored.embedding if stored else None

        all_candidates: list[WatchMatch] = []
        match_count_by_interest: dict[str, int] = {}

        for interest in active:
            if interest.embedding is None:
                lazy = await self._embed_interest(interest)
                if lazy is not None:
                    await self.interest_repo.update_embedding(interest.id, lazy)
                    interest = interest.model_copy(update={"embedding": lazy})

            for ref, doc in docs_by_ref.items():
                doc_emb = embeddings_by_ref.get(ref)
                score = compute_watch_score(interest, doc, doc_emb)
                if score.combined < interest.threshold:
                    continue
                all_candidates.append(
                    WatchMatch(
                        id=0,
                        interest_id=interest.id,
                        source_ref=ref,
                        channel_id=doc.channel_id,
                        keyword_score=score.keyword,
                        semantic_score=score.semantic,
                        combined_score=score.combined,
                        notified=False,
                    )
                )
                match_count_by_interest[interest.id] = (
                    match_count_by_interest.get(interest.id, 0) + 1
                )

        inserted = await self.match_repo.upsert_many(all_candidates)

        now = datetime.now(UTC)
        for interest in active:
            await self.interest_repo.touch_checked(interest.id, now)
        for interest_id in match_count_by_interest:
            await self.interest_repo.touch_match(interest_id, now)

        logger.info(
            "watchlist.check_interests",
            channel_id=channel_id,
            interests=len(active),
            docs=len(docs_by_ref),
            candidates=len(all_candidates),
            inserted=len(inserted),
        )
        return inserted

    # ---- Internal: embedding helpers ----

    async def _embed_interest(self, interest: WatchInterest) -> list[float] | None:
        """Compute an embedding for an interest using the canonical text.

        Returns ``None`` if the embedding client is not configured (e.g. tests
        that exercise pure keyword scoring) or if the client raises — caller
        keeps the interest in pure-keyword mode.
        """
        if self.embedding_client is None:
            return None
        text = build_canonical_interest_text(interest)
        try:
            vectors = await self.embedding_client.embed([text])
        except Exception as exc:
            logger.warning(
                "watchlist.embedding_failed",
                interest_id=interest.id,
                error=str(exc),
            )
            return None
        if not vectors:
            return None
        return list(vectors[0])
