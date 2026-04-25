"""Service-level tests for WatchlistService using in-memory fakes (no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
    WatchMatch,
)
from tg_parser.services.watchlist_service import (
    MAX_DOCS_PER_TICK,
    WatchlistService,
    compose_match_notification,
    escape_markdown_v2,
)

# ----------------------------------------------------------------------------
# In-memory fakes
# ----------------------------------------------------------------------------


class _FakeInterestRepo:
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


class _FakeMatchRepo:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], WatchMatch] = {}
        self.next_id = 1
        self.upsert_calls: int = 0

    async def upsert_many(self, matches: list[WatchMatch]) -> list[WatchMatch]:
        self.upsert_calls += 1
        inserted: list[WatchMatch] = []
        for match in matches:
            key = (match.interest_id, match.source_ref)
            if key in self.store:
                continue
            stored = match.model_copy(update={"id": self.next_id})
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

    async def mark_notified(self, match_ids: list[int]) -> None:
        for match_id in match_ids:
            for key, match in self.store.items():
                if match.id == match_id:
                    self.store[key] = match.model_copy(update={"notified": True})


class _FakeProcessedDocRepo:
    def __init__(self, docs: list[ProcessedDocument]):
        self.by_ref = {d.source_ref: d for d in docs}

    async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
        return {ref: self.by_ref[ref] for ref in source_refs if ref in self.by_ref}


class _FakeEmbeddingRepo:
    def __init__(self, embeddings: dict[str, list[float] | None] | None = None):
        self.embeddings: dict[str, list[float] | None] = dict(embeddings or {})

    async def get_by_source_ref(self, source_ref: str) -> Any:
        emb = self.embeddings.get(source_ref)
        if emb is None:
            return None

        class _Stored:
            def __init__(self, value: list[float]):
                self.embedding = value

        return _Stored(emb)


class _FakeEmbeddingClient:
    def __init__(self, vector: list[float] | None = None):
        self.calls: list[list[str]] = []
        self.vector = vector or [0.1] * 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [list(self.vector) for _ in texts]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_doc(
    *,
    source_ref: str,
    text: str,
    channel_id: str = "crypto_news",
    summary: str | None = None,
    topics: list[str] | None = None,
) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref.rsplit(":", 1)[-1],
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=text,
        summary=summary,
        topics=list(topics or []),
    )


def _make_interest(
    *,
    interest_id: str = "int-1",
    keywords: list[str] | None = None,
    threshold: float = 0.6,
    embedding: list[float] | None = None,
    channel_ids: list[str] | None = None,
    is_active: bool = True,
) -> WatchInterest:
    return WatchInterest(
        id=interest_id,
        user_id="user-1",
        chat_id=12345,
        title="MiCA / EU crypto regulation",
        description="Watch for crypto regulation news",
        keywords=list(keywords or ["mica"]),
        exclude_keywords=[],
        channel_ids=list(channel_ids or ["crypto_news"]),
        threshold=threshold,
        notify_mode=NotifyMode.INSTANT,
        is_active=is_active,
        embedding=embedding,
    )


def _make_service(
    *,
    interest_repo: _FakeInterestRepo | None = None,
    match_repo: _FakeMatchRepo | None = None,
    docs: list[ProcessedDocument] | None = None,
    embeddings: dict[str, list[float] | None] | None = None,
    embedding_client: _FakeEmbeddingClient | None = None,
) -> WatchlistService:
    return WatchlistService(
        interest_repo=interest_repo or _FakeInterestRepo(),
        match_repo=match_repo or _FakeMatchRepo(),
        processed_doc_repo=_FakeProcessedDocRepo(docs or []),
        embedding_repo=_FakeEmbeddingRepo(embeddings),
        embedding_client=embedding_client,
    )


# ----------------------------------------------------------------------------
# check_interests
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckInterests:
    async def test_returns_empty_when_no_new_doc_refs(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest())
        svc = _make_service(interest_repo=ir, docs=[])
        result = await svc.check_interests("crypto_news", [])
        assert result == []
        # Without new refs we don't even touch active interests.
        assert ir.touch_checked_calls == []

    async def test_returns_empty_when_no_active_interests(self):
        svc = _make_service(
            interest_repo=_FakeInterestRepo(),
            docs=[_make_doc(source_ref="tg:c:post:1", text="MiCA")],
        )
        result = await svc.check_interests("crypto_news", ["tg:c:post:1"])
        assert result == []

    async def test_records_match_above_threshold(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(keywords=["mica"], embedding=None, threshold=0.5))
        doc = _make_doc(
            source_ref="tg:crypto_news:post:1",
            text="MiCA regulation news",
            channel_id="crypto_news",
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        result = await svc.check_interests("crypto_news", [doc.source_ref])

        assert len(result) == 1
        assert result[0].source_ref == doc.source_ref
        assert result[0].combined_score >= 0.5
        assert result[0].notified is False

    async def test_skips_match_below_threshold(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(
            _make_interest(
                interest_id="int-strict",
                keywords=["mica", "psd3", "nis2", "dora"],
                threshold=0.6,
                embedding=None,
            )
        )
        doc = _make_doc(
            source_ref="tg:crypto_news:post:1",
            text="MiCA discussion (only one of four kw)",
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        result = await svc.check_interests("crypto_news", [doc.source_ref])
        assert result == []

    async def test_idempotent_on_rerun(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        first = await svc.check_interests("crypto_news", [doc.source_ref])
        second = await svc.check_interests("crypto_news", [doc.source_ref])

        assert len(first) == 1
        # Re-run on the same (interest, source_ref) returns no new matches.
        assert second == []
        assert mr.upsert_calls == 2
        assert len(mr.store) == 1

    async def test_caps_at_max_docs_per_tick(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(keywords=["mica"], threshold=0.5))

        many_docs = [
            _make_doc(source_ref=f"tg:crypto_news:post:{i}", text="MiCA")
            for i in range(MAX_DOCS_PER_TICK + 5)
        ]
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=many_docs)

        refs = [d.source_ref for d in many_docs]
        result = await svc.check_interests("crypto_news", refs)

        assert len(result) == MAX_DOCS_PER_TICK

    async def test_lazy_embeds_interest_when_missing(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        client = _FakeEmbeddingClient(vector=[0.5] * 1536)
        await ir.create(_make_interest(keywords=["mica"], embedding=None, threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        svc = _make_service(
            interest_repo=ir,
            match_repo=mr,
            docs=[doc],
            embeddings={doc.source_ref: [0.5] * 1536},
            embedding_client=client,
        )

        await svc.check_interests("crypto_news", [doc.source_ref])

        assert len(client.calls) == 1
        # The interest is updated in-place with the cached embedding.
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.embedding is not None
        assert len(stored.embedding) == 1536

    async def test_touches_last_checked_for_every_active_interest(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.5))
        await ir.create(
            _make_interest(interest_id="i-2", keywords=["unrelated_keyword_xyz"], threshold=0.5)
        )
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        await svc.check_interests("crypto_news", [doc.source_ref])

        touched_ids = {call[0] for call in ir.touch_checked_calls}
        assert touched_ids == {"i-1", "i-2"}

    async def test_touches_last_match_only_for_matched_interests(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1", keywords=["mica"], threshold=0.5))
        await ir.create(
            _make_interest(interest_id="i-2", keywords=["unrelated_keyword_xyz"], threshold=0.5)
        )
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        await svc.check_interests("crypto_news", [doc.source_ref])

        touched_match_ids = {call[0] for call in ir.touch_match_calls}
        assert touched_match_ids == {"i-1"}


# ----------------------------------------------------------------------------
# create_interest / soft_delete_interest
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateInterest:
    async def test_persists_and_eagerly_embeds(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient(vector=[0.7] * 1536)
        svc = _make_service(interest_repo=ir, embedding_client=client)

        created = await svc.create_interest(
            user_id="user-1",
            chat_id=42,
            title="MiCA",
            channel_ids=["crypto_news"],
            description="Watch crypto regulation",
            keywords=["mica"],
        )

        assert created.id != ""
        assert created.embedding is not None
        assert len(created.embedding) == 1536
        # And the stored row reflects the embedding too.
        stored = await ir.get(created.id)
        assert stored is not None
        assert stored.embedding is not None
        # Embedding client was called exactly once with the canonical text.
        assert len(client.calls) == 1
        assert any("MiCA" in t or "mica" in t for t in client.calls[0])

    async def test_works_without_embedding_client(self):
        # When OpenAI is not configured the interest is still created, just
        # without a cached embedding (lazy fallback in check_interests).
        ir = _FakeInterestRepo()
        svc = _make_service(interest_repo=ir, embedding_client=None)

        created = await svc.create_interest(
            user_id="user-1",
            chat_id=42,
            title="MiCA",
            channel_ids=["crypto_news"],
            keywords=["mica"],
        )
        assert created.embedding is None


@pytest.mark.asyncio
class TestSoftDelete:
    async def test_marks_inactive(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        svc = _make_service(interest_repo=ir)

        ok = await svc.soft_delete_interest("int-1")
        assert ok is True
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is False

    async def test_returns_false_when_already_inactive(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1", is_active=False))
        svc = _make_service(interest_repo=ir)

        ok = await svc.soft_delete_interest("int-1")
        assert ok is False


# ----------------------------------------------------------------------------
# delete_interest_for_user / list_user_interests / get_matches
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOwnershipAwareCRUD:
    async def test_delete_blocks_non_owner(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        svc = _make_service(interest_repo=ir)

        deleted, err = await svc.delete_interest_for_user(
            "int-1",
            requesting_user_id="someone-else",
            is_admin=False,
        )
        assert deleted is False
        assert err is not None
        assert "permission" in err.lower()
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is True

    async def test_delete_allows_owner(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        svc = _make_service(interest_repo=ir)

        deleted, err = await svc.delete_interest_for_user(
            "int-1",
            requesting_user_id="user-1",
            is_admin=False,
        )
        assert deleted is True
        assert err is None
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is False

    async def test_delete_allows_admin_for_other_user(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        svc = _make_service(interest_repo=ir)

        deleted, err = await svc.delete_interest_for_user(
            "int-1",
            requesting_user_id="admin",
            is_admin=True,
        )
        assert deleted is True
        assert err is None

    async def test_delete_returns_not_found(self):
        svc = _make_service()
        deleted, err = await svc.delete_interest_for_user(
            "missing",
            requesting_user_id="user-1",
            is_admin=False,
        )
        assert deleted is False
        assert err == "interest not found"

    async def test_list_user_interests_filters_by_owner(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        await ir.create(
            _make_interest(interest_id="int-2").model_copy(update={"user_id": "other-user"})
        )
        svc = _make_service(interest_repo=ir)

        owned = await svc.list_user_interests("user-1")
        assert {i.id for i in owned} == {"int-1"}

    async def test_get_matches_filters_by_since(self):
        mr = _FakeMatchRepo()
        old = WatchMatch(
            id=1,
            interest_id="int-1",
            source_ref="tg:c:post:1",
            channel_id="c",
            keyword_score=0.5,
            semantic_score=0.0,
            combined_score=0.5,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            notified=True,
        )
        new = WatchMatch(
            id=2,
            interest_id="int-1",
            source_ref="tg:c:post:2",
            channel_id="c",
            keyword_score=0.5,
            semantic_score=0.0,
            combined_score=0.5,
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
            notified=False,
        )
        await mr.upsert_many([old, new])
        svc = _make_service(match_repo=mr)

        recent = await svc.get_matches(
            "int-1",
            since=datetime(2026, 4, 1, tzinfo=UTC),
        )
        refs = {m.source_ref for m in recent}
        assert refs == {"tg:c:post:2"}


# ----------------------------------------------------------------------------
# notify(matches, bot)
# ----------------------------------------------------------------------------


class _FakeBot:
    """Minimal Bot stub matching the subset of aiogram.Bot used by notify()."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.raises = raises

    async def send_message(self, *, chat_id: int, text: str, parse_mode: Any = None) -> None:
        if self.raises is not None:
            raise self.raises
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


def _make_match(
    *,
    interest_id: str,
    source_ref: str,
    match_id: int = 1,
    combined: float = 0.7,
    keyword: float = 0.6,
    semantic: float = 0.8,
    channel_id: str = "crypto_news",
) -> WatchMatch:
    return WatchMatch(
        id=match_id,
        interest_id=interest_id,
        source_ref=source_ref,
        channel_id=channel_id,
        keyword_score=keyword,
        semantic_score=semantic,
        combined_score=combined,
        created_at=datetime.now(UTC),
        notified=False,
    )


@pytest.mark.asyncio
class TestNotify:
    async def test_groups_matches_per_interest_and_marks_notified(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        await ir.create(_make_interest(interest_id="int-2").model_copy(update={"chat_id": 999}))
        doc1 = _make_doc(source_ref="tg:c:post:1", text="MiCA news 1")
        doc2 = _make_doc(source_ref="tg:c:post:2", text="MiCA news 2")
        await mr.upsert_many(
            [
                _make_match(interest_id="int-1", source_ref=doc1.source_ref, match_id=10),
                _make_match(interest_id="int-2", source_ref=doc2.source_ref, match_id=20),
            ]
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc1, doc2])

        bot = _FakeBot()
        outcomes = await svc.notify(list(mr.store.values()), bot)

        assert outcomes == {"int-1": "sent", "int-2": "sent"}
        assert len(bot.sent) == 2
        chat_ids = {msg["chat_id"] for msg in bot.sent}
        assert chat_ids == {12345, 999}
        for stored in mr.store.values():
            assert stored.notified is True

    async def test_skips_inactive_interest(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", is_active=False))
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA news")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        outcomes = await svc.notify([match], _FakeBot())
        assert outcomes["int-1"] == "skipped_inactive"
        stored = next(iter(mr.store.values()))
        assert stored.notified is False

    async def test_skips_non_instant_notify_mode(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        interest = _make_interest(interest_id="int-1").model_copy(
            update={"notify_mode": NotifyMode.BATCH}
        )
        await ir.create(interest)
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA news")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        outcomes = await svc.notify([match], _FakeBot())
        assert outcomes["int-1"] == "skipped_non_instant"

    async def test_returns_interest_missing_when_repo_returns_none(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        match = _make_match(interest_id="ghost", source_ref="tg:c:post:1", match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr)

        outcomes = await svc.notify([match], _FakeBot())
        assert outcomes["ghost"] == "interest_missing"

    async def test_soft_deletes_on_permanent_bot_failure(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA news")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot(raises=Exception("Bad Request: chat not found"))
        outcomes = await svc.notify([match], bot)

        assert outcomes["int-1"] == "send_failed"
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is False
        assert mr.store[("int-1", doc.source_ref)].notified is False

    async def test_does_not_soft_delete_on_transient_bot_failure(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot(raises=Exception("temporary network error"))
        outcomes = await svc.notify([match], bot)

        assert outcomes["int-1"] == "send_failed"
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is True

    async def test_returns_empty_for_empty_input(self):
        svc = _make_service()
        bot = _FakeBot()
        assert await svc.notify([], bot) == {}
        assert bot.sent == []

    async def test_lazy_loads_missing_docs(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA news")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        # Pass docs to repo but NOT to docs_by_ref - notify must lazy-fetch.
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        outcomes = await svc.notify([match], bot, docs_by_ref={})
        assert outcomes["int-1"] == "sent"
        assert "MiCA" in bot.sent[0]["text"] or "post" in bot.sent[0]["text"]


# ----------------------------------------------------------------------------
# MarkdownV2 escape + compose_match_notification (pure helpers)
# ----------------------------------------------------------------------------


class TestMarkdownV2Helpers:
    def test_escapes_all_special_chars(self):
        # All MarkdownV2 special chars should be backslash-escaped at least once.
        for ch in r"_*[]()~`>#+-=|{}.!":
            escaped = escape_markdown_v2(f"a{ch}b")
            assert "\\" + ch in escaped, f"char {ch!r} not escaped: {escaped!r}"

    def test_passthrough_for_plain_text(self):
        assert escape_markdown_v2("hello world") == "hello world"

    def test_compose_includes_title_and_preview(self):
        interest = _make_interest(interest_id="int-1")
        doc = _make_doc(
            source_ref="tg:crypto_news:post:1",
            text="MiCA enters into force tomorrow",
            summary="Short MiCA summary",
        )
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        text = compose_match_notification(interest, [match], {doc.source_ref: doc})

        # Title fragments should appear (escaped).
        assert "MiCA" in text
        assert "Short MiCA summary" in text or "MiCA enters into force" in text

    def test_compose_caps_at_max_previews(self):
        interest = _make_interest(interest_id="int-1")
        docs = [_make_doc(source_ref=f"tg:c:post:{i}", text=f"snippet {i}") for i in range(20)]
        matches = [
            _make_match(interest_id="int-1", source_ref=d.source_ref, match_id=i + 1)
            for i, d in enumerate(docs)
        ]
        text = compose_match_notification(
            interest,
            matches,
            {d.source_ref: d for d in docs},
        )
        # The composer must collapse the tail into a "+N more" footer, not
        # render every single match inline.
        assert "more" in text.lower()
        assert len(text) < 4096
