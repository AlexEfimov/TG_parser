"""In-memory F11 watchlist fakes shared by the delivery test suites.

Extracted from ``test_watchlist_batch.py`` (ADR-0014) when BUG-095 added a
second delivery path and a third copy of the same fakes would have been the
alternative. The fakes model the three repositories ``WatchlistService`` talks
to plus a ``Bot`` stand-in that records ``send_message`` calls.

``FakeMatchRepo.list_unnotified_for_interests`` mirrors the SQL selector's
date-bound semantics (``since`` / ``before``) because that bound is the
BUG-095 watermark — a fake without it would make the watermark tests vacuous.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
    WatchMatch,
)
from tg_parser.services.watchlist_service import WatchlistService


class FakeInterestRepo:
    def __init__(self) -> None:
        self.store: dict[str, WatchInterest] = {}
        self.touch_checked_calls: list[tuple[str, datetime]] = []
        self.touch_match_calls: list[tuple[str, datetime]] = []

    async def create(self, interest: WatchInterest) -> WatchInterest:
        new_id = interest.id or f"int-{len(self.store) + 1}"
        stored = interest.model_copy(update={"id": new_id})
        self.store[new_id] = stored
        return stored

    async def get(self, interest_id: str) -> WatchInterest | None:
        return self.store.get(interest_id)

    async def list_for_user(self, user_id: str) -> list[WatchInterest]:
        return [i for i in self.store.values() if i.user_id == user_id]

    async def list_all(self) -> list[WatchInterest]:
        return list(self.store.values())

    async def list_active_for_channel(self, channel_id: str) -> list[WatchInterest]:
        return [i for i in self.store.values() if i.is_active and channel_id in i.channel_ids]

    async def update_embedding(self, interest_id: str, embedding: list[float]) -> None:
        if interest_id in self.store:
            self.store[interest_id] = self.store[interest_id].model_copy(
                update={"embedding": list(embedding)}
            )

    async def soft_delete(self, interest_id: str) -> bool:
        existing = self.store.get(interest_id)
        if existing is None or not existing.is_active:
            return False
        self.store[interest_id] = existing.model_copy(update={"is_active": False})
        return True

    async def resume(self, interest_id: str) -> bool:
        """Test helper — flip ``is_active`` back to True (mirrors re-subscribe)."""
        existing = self.store.get(interest_id)
        if existing is None:
            return False
        self.store[interest_id] = existing.model_copy(update={"is_active": True})
        return True

    async def touch_checked(self, interest_id: str, at: datetime) -> None:
        self.touch_checked_calls.append((interest_id, at))
        if interest_id in self.store:
            self.store[interest_id] = self.store[interest_id].model_copy(
                update={"last_checked_at": at}
            )

    async def touch_match(self, interest_id: str, at: datetime) -> None:
        self.touch_match_calls.append((interest_id, at))
        if interest_id in self.store:
            self.store[interest_id] = self.store[interest_id].model_copy(
                update={"last_match_at": at}
            )


class FakeMatchRepo:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], WatchMatch] = {}
        self.next_id = 1
        self.upsert_calls: int = 0
        self.mark_calls: list[list[int]] = []

    async def upsert_many(self, matches: list[WatchMatch]) -> list[WatchMatch]:
        """Insert-if-absent, returning the stored rows (``RETURNING`` semantics).

        ``created_at`` of a naive candidate is replaced with an aware UTC stamp:
        the real INSERT does not carry the column at all, so Postgres assigns
        ``NOW()`` on a ``TIMESTAMPTZ`` and the ``RETURNING`` row always comes
        back tz-aware. An aware value passed in is kept as-is so a test can seed
        historical rows for the BUG-095 watermark.
        """
        self.upsert_calls += 1
        inserted: list[WatchMatch] = []
        for match in matches:
            key = (match.interest_id, match.source_ref)
            if key in self.store:
                continue
            created_at = match.created_at
            if created_at is None or created_at.tzinfo is None:
                created_at = datetime.now(UTC)
            stored = match.model_copy(update={"id": self.next_id, "created_at": created_at})
            self.next_id += 1
            self.store[key] = stored
            inserted.append(stored)
        return inserted

    async def list_for_interest(
        self, interest_id: str, since: datetime | None = None
    ) -> list[WatchMatch]:
        rows = [m for m in self.store.values() if m.interest_id == interest_id]
        if since is not None:
            rows = [m for m in rows if m.created_at > since]
        return sorted(rows, key=lambda m: m.created_at)

    async def list_unnotified_for_interests(
        self,
        interest_ids: list[str],
        *,
        since: datetime | None = None,
        before: datetime | None = None,
    ) -> list[WatchMatch]:
        ids = set(interest_ids)
        rows = [m for m in self.store.values() if not m.notified and m.interest_id in ids]
        if since is not None:
            rows = [m for m in rows if m.created_at >= since]
        if before is not None:
            rows = [m for m in rows if m.created_at < before]
        return sorted(rows, key=lambda m: m.created_at)

    async def count_unnotified_for_interests(
        self,
        interest_ids: list[str],
        *,
        before: datetime | None = None,
    ) -> int:
        rows = await self.list_unnotified_for_interests(interest_ids, before=before)
        return len(rows)

    async def mark_notified(self, match_ids: list[int]) -> None:
        self.mark_calls.append(list(match_ids))
        for match_id in match_ids:
            for key, match in self.store.items():
                if match.id == match_id:
                    self.store[key] = match.model_copy(update={"notified": True})


class FakeProcessedDocRepo:
    def __init__(self, docs: list[ProcessedDocument]):
        self.by_ref = {d.source_ref: d for d in docs}

    async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
        return {ref: self.by_ref[ref] for ref in source_refs if ref in self.by_ref}

    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ProcessedDocument]:
        return [d for d in self.by_ref.values() if d.channel_id == channel_id]


class _Stored:
    def __init__(self, value: list[float]):
        self.embedding = value


class FakeEmbeddingRepo:
    def __init__(self, embeddings: dict[str, list[float] | None] | None = None):
        self.embeddings: dict[str, list[float] | None] = dict(embeddings or {})

    async def get_by_source_ref(self, source_ref: str) -> Any:
        emb = self.embeddings.get(source_ref)
        return _Stored(emb) if emb is not None else None

    async def get_many_by_source_refs(self, source_refs: list[str]) -> dict[str, Any]:
        return {
            ref: _Stored(self.embeddings[ref])
            for ref in source_refs
            if self.embeddings.get(ref) is not None
        }


class FakeBot:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.raises = raises

    async def send_message(self, *, chat_id: int, text: str, parse_mode: Any = None) -> None:
        if self.raises is not None:
            raise self.raises
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


def make_doc(
    *,
    source_ref: str,
    text: str,
    channel_id: str = "crypto_news",
    summary: str | None = None,
) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref.rsplit(":", 1)[-1],
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=text,
        summary=summary,
        topics=[],
    )


def make_interest(
    *,
    interest_id: str = "int-1",
    keywords: list[str] | None = None,
    threshold: float = 0.5,
    channel_ids: list[str] | None = None,
    is_active: bool = True,
    notify_mode: NotifyMode = NotifyMode.BATCH,
    chat_id: int = 12345,
    title: str = "MiCA / EU crypto regulation",
    user_id: str = "user-1",
) -> WatchInterest:
    return WatchInterest(
        id=interest_id,
        user_id=user_id,
        chat_id=chat_id,
        title=title,
        description="Watch for crypto regulation news",
        keywords=list(keywords or ["mica"]),
        exclude_keywords=[],
        channel_ids=list(channel_ids or ["crypto_news"]),
        threshold=threshold,
        notify_mode=notify_mode,
        is_active=is_active,
        embedding=None,
    )


def make_match(
    *,
    interest_id: str,
    source_ref: str,
    match_id: int = 0,
    combined: float = 0.7,
    channel_id: str = "crypto_news",
    notified: bool = False,
    created_at: datetime | None = None,
) -> WatchMatch:
    return WatchMatch(
        id=match_id,
        interest_id=interest_id,
        source_ref=source_ref,
        channel_id=channel_id,
        keyword_score=0.6,
        semantic_score=0.8,
        combined_score=combined,
        created_at=created_at or datetime.now(UTC),
        notified=notified,
    )


def make_service(
    *,
    interest_repo: FakeInterestRepo,
    match_repo: FakeMatchRepo,
    docs: list[ProcessedDocument] | None = None,
) -> WatchlistService:
    return WatchlistService(
        interest_repo=interest_repo,
        match_repo=match_repo,
        processed_doc_repo=FakeProcessedDocRepo(docs or []),
        embedding_repo=FakeEmbeddingRepo(),
        embedding_client=None,
    )
