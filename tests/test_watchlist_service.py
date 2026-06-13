"""Service-level tests for WatchlistService using in-memory fakes (no DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tg_parser.domain.models import (
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
    WatchMatch,
)
from tg_parser.services.watchlist_service import (
    KEYWORD_WEIGHT,
    MAX_DOCS_PER_TICK,
    SEMANTIC_WEIGHT,
    BackfillResult,
    ThresholdCalibration,
    WatchlistService,
    _cosine,
    _keyword_score,
    _load_calibration_settings,
    _post_url,
    _tokenize,
    build_canonical_interest_text,
    compose_match_notification,
    compute_watch_score,
    escape_markdown_v2,
    make_watchlist_service,
    suggest_threshold_from_scores,
)

# ----------------------------------------------------------------------------
# In-memory fakes
# ----------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for ``AsyncSession`` exposing only the methods the service
    touches on the race-retry path (BUG-029). Records ``rollback`` calls so
    tests can assert the aborted transaction was reset before the retry.
    """

    def __init__(self) -> None:
        self.rollback_calls: int = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _FakeInterestRepo:
    def __init__(self) -> None:
        self.store: dict[str, WatchInterest] = {}
        self.touch_checked_calls: list[tuple[str, datetime]] = []
        self.touch_match_calls: list[tuple[str, datetime]] = []
        # BUG-054 (ADR 0015): record update_embedding calls so the update-path
        # re-embed spy can assert it fires only on a text-field change.
        self.update_embedding_calls: list[str] = []
        # BUG-022 (Wave 1 step 3): toggle to simulate a UNIQUE
        # (user_id, title) race — the first create() raises and the
        # next find_by_user_and_title returns the row another caller
        # inserted in the meantime.
        self.simulate_race_on_create: bool = False
        self._race_already_fired: bool = False
        # BUG-029: the real SA repo exposes ``.session`` so the service can
        # ``rollback()`` an aborted transaction before the race-retry. The
        # fake mirrors that surface with a no-op rollback counter.
        self.session = _FakeSession()

    async def create(self, interest: WatchInterest) -> WatchInterest:
        # BUG-022 (Wave 1 step 3): when ``simulate_race_on_create`` is on
        # the fake mirrors the new ``UNIQUE (user_id, title)`` DB
        # constraint — every call that would otherwise collide raises
        # :class:`IntegrityError`, mirroring the real Postgres behaviour
        # under concurrent INSERTs (the first winner stores; every
        # subsequent caller gets the same conflict).
        if self.simulate_race_on_create:
            from sqlalchemy.exc import IntegrityError

            collision = next(
                (
                    existing
                    for existing in self.store.values()
                    if existing.user_id == interest.user_id and existing.title == interest.title
                ),
                None,
            )
            if collision is not None:
                raise IntegrityError(
                    "duplicate key value violates unique constraint",
                    params=None,
                    orig=Exception("uq_watch_interests_user_title"),
                )
            if not self._race_already_fired:
                # First call wins the race: store the row + signal that
                # any later create() reaching the fake races against it.
                self._race_already_fired = True
        new_id = interest.id or f"int-{len(self.store) + 1}"
        stored = interest.model_copy(update={"id": new_id})
        self.store[new_id] = stored
        return stored

    async def get(self, interest_id: str) -> WatchInterest | None:
        return self.store.get(interest_id)

    async def find_by_user_and_title(self, user_id: str, title: str) -> WatchInterest | None:
        for interest in self.store.values():
            if interest.user_id == user_id and interest.title == title:
                return interest
        return None

    async def update_subscribe_fields(
        self,
        interest_id: str,
        *,
        chat_id: int | None = None,
        description: str | None = None,
        keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        channel_ids: list[str] | None = None,
        threshold: float | None = None,
        threshold_source: str | None = None,
        notify_mode: Any = None,
        is_active: bool | None = None,
        workspace_id: str | None = None,
        unset_workspace_id: bool = False,
    ) -> WatchInterest | None:
        existing = self.store.get(interest_id)
        if existing is None:
            return None
        updates: dict[str, Any] = {}
        if chat_id is not None:
            updates["chat_id"] = chat_id
        if description is not None:
            updates["description"] = description
        if keywords is not None:
            updates["keywords"] = list(keywords)
        if exclude_keywords is not None:
            updates["exclude_keywords"] = list(exclude_keywords)
        if channel_ids is not None:
            updates["channel_ids"] = list(channel_ids)
        if threshold is not None:
            updates["threshold"] = float(threshold)
        if threshold_source is not None:
            updates["threshold_source"] = threshold_source
        if notify_mode is not None:
            updates["notify_mode"] = notify_mode
        if is_active is not None:
            updates["is_active"] = is_active
        if unset_workspace_id:
            updates["workspace_id"] = None
        elif workspace_id is not None:
            updates["workspace_id"] = workspace_id
        if not updates:
            return existing
        new_row = existing.model_copy(update=updates)
        self.store[interest_id] = new_row
        return new_row

    async def list_for_user(self, user_id: str) -> list[WatchInterest]:
        return [i for i in self.store.values() if i.user_id == user_id]

    async def list_all(self) -> list[WatchInterest]:
        return list(self.store.values())

    async def list_active_for_channel(self, channel_id: str) -> list[WatchInterest]:
        return [i for i in self.store.values() if i.is_active and channel_id in i.channel_ids]

    async def update_embedding(self, interest_id: str, embedding: list[float]) -> None:
        self.update_embedding_calls.append(interest_id)
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

    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ProcessedDocument]:
        def _aware(value: datetime) -> datetime:
            # Production columns are timestamptz; the fake coerces naive
            # datetimes (e.g. the model's default_factory created_at) to UTC so
            # comparisons never raise offset-naive/aware TypeErrors.
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        rows = [d for d in self.by_ref.values() if d.channel_id == channel_id]
        if from_date is not None:
            rows = [d for d in rows if _aware(d.processed_at) >= _aware(from_date)]
        if to_date is not None:
            rows = [d for d in rows if _aware(d.processed_at) <= _aware(to_date)]
        return rows


class _Stored:
    def __init__(self, value: list[float]):
        self.embedding = value


class _FakeEmbeddingRepo:
    def __init__(self, embeddings: dict[str, list[float] | None] | None = None):
        self.embeddings: dict[str, list[float] | None] = dict(embeddings or {})
        # ADR-0011: count batched-fetch calls so parity/perf tests can assert
        # the N+1 per-ref loop is gone (one batched call, not one per doc).
        self.get_many_calls: int = 0
        # BUG-055: also count per-ref calls so check_interests can assert the
        # N+1 single-ref path is no longer taken on a multi-doc tick.
        self.get_one_calls: int = 0

    async def get_by_source_ref(self, source_ref: str) -> Any:
        self.get_one_calls += 1
        emb = self.embeddings.get(source_ref)
        if emb is None:
            return None
        return _Stored(emb)

    async def get_many_by_source_refs(self, source_refs: list[str]) -> dict[str, Any]:
        # ADR-0011: mirror SAEmbeddingRepo.get_many_by_source_refs — refs with no
        # stored embedding are simply absent from the returned dict.
        self.get_many_calls += 1
        out: dict[str, Any] = {}
        for ref in source_refs:
            emb = self.embeddings.get(ref)
            if emb is not None:
                out[ref] = _Stored(emb)
        return out


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
    processed_at: datetime | None = None,
) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref.rsplit(":", 1)[-1],
        channel_id=channel_id,
        processed_at=processed_at or datetime.now(UTC),
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
    async def test_touches_checked_but_matches_nothing_when_no_new_doc_refs(self):
        # ENH-001: a quiet tick (empty new_doc_refs) returns no matches but
        # MUST still stamp ``last_checked_at`` on every active interest of the
        # channel — ``last_checked_at`` is a "last evaluated" / matcher-liveness
        # signal, not "last tick that carried new docs".
        ir = _FakeInterestRepo()
        created = await ir.create(_make_interest())
        svc = _make_service(interest_repo=ir, docs=[])
        result = await svc.check_interests("crypto_news", [])
        assert result == []
        # Active interest was evaluated this tick → last_checked_at advanced.
        assert [c[0] for c in ir.touch_checked_calls] == [created.id]
        # But nothing matched, so last_match_at is untouched.
        assert ir.touch_match_calls == []

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

    async def test_batched_embedding_fetch_single_call_no_n_plus_1(self):
        # BUG-055: a multi-doc tick must fetch embeddings via ONE batched
        # get_many_by_source_refs call and never fall back to the per-ref
        # get_by_source_ref N+1 path. The missing-embedding ref maps to None
        # (keyword-only scoring), exercising the None branch.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        interest_vec = [1.0] + [0.0] * 1535
        await ir.create(
            _make_interest(
                interest_id="int-1",
                keywords=["mica"],
                threshold=0.5,
                embedding=interest_vec,
            )
        )
        docs = [
            _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA one"),
            _make_doc(source_ref="tg:crypto_news:post:2", text="MiCA two"),
            _make_doc(source_ref="tg:crypto_news:post:3", text="MiCA three"),
        ]
        # post:3 intentionally has no stored embedding (None path).
        embeddings = {
            docs[0].source_ref: list(interest_vec),
            docs[1].source_ref: list(interest_vec),
        }
        emb_repo = _FakeEmbeddingRepo(embeddings)
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo(docs),
            embedding_repo=emb_repo,
            embedding_client=None,
        )

        result = await svc.check_interests("crypto_news", [d.source_ref for d in docs])

        assert emb_repo.get_many_calls == 1
        assert emb_repo.get_one_calls == 0
        # All three docs clear the keyword gate; the two with aligned embeddings
        # additionally score semantic 1.0, the embedding-less one is keyword-only.
        assert len(result) == 3
        semantic_by_ref = {m.source_ref: m.semantic_score for m in result}
        assert semantic_by_ref[docs[0].source_ref] == pytest.approx(1.0)
        assert semantic_by_ref[docs[2].source_ref] == pytest.approx(0.0)

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

    def test_escapes_backslash(self):
        # Backslash is itself in _MD_V2_SPECIAL — must be doubled, otherwise
        # Telegram interprets the escape sequence rather than rendering the slash.
        assert escape_markdown_v2("a\\b") == "a\\\\b"

    def test_empty_returns_empty(self):
        assert escape_markdown_v2("") == ""

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

    def test_compose_falls_back_to_source_ref_when_doc_missing(self):
        # docs_by_ref empty → composer should still produce a valid message
        # with the source_ref as the body, no exception.
        interest = _make_interest(interest_id="int-1")
        match = _make_match(
            interest_id="int-1",
            source_ref="tg:crypto_news:post:42",
            match_id=10,
        )
        text = compose_match_notification(interest, [match], {})
        # Source ref should appear (escaped) so the user can still navigate.
        assert "crypto_news" in text or "post" in text
        assert "42" in text

    def test_compose_emits_t_me_link_for_public_channel(self):
        interest = _make_interest(interest_id="int-1")
        doc = _make_doc(source_ref="tg:crypto_news:post:7", text="MiCA")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        text = compose_match_notification(interest, [match], {doc.source_ref: doc})
        assert "https://t.me/crypto_news/7" in text

    def test_compose_orders_matches_by_combined_score_desc(self):
        # Highest-scoring match should appear first.  Use distinct channel
        # names so the rendered t.me URLs are unique substrings.
        interest = _make_interest(interest_id="int-1")
        d_low = _make_doc(source_ref="tg:lowchan:post:11", text="low score body")
        d_high = _make_doc(source_ref="tg:highchan:post:22", text="high score body")
        matches = [
            _make_match(
                interest_id="int-1",
                source_ref=d_low.source_ref,
                match_id=1,
                combined=0.55,
            ),
            _make_match(
                interest_id="int-1",
                source_ref=d_high.source_ref,
                match_id=2,
                combined=0.95,
            ),
        ]
        text = compose_match_notification(
            interest, matches, {d_low.source_ref: d_low, d_high.source_ref: d_high}
        )
        assert text.index("highchan") < text.index("lowchan")


# ----------------------------------------------------------------------------
# Pure helpers: tokenizer + cosine + post URL + canonical text
# ----------------------------------------------------------------------------


class TestTokenize:
    def test_lowercases_and_drops_short(self):
        # MIN_TOKEN_LENGTH = 2 so single chars like "a" and punctuation should drop.
        toks = _tokenize("MiCA, a Reg # 2026")
        assert "mica" in toks
        assert "reg" in toks
        assert "2026" in toks
        assert "a" not in toks
        assert "#" not in toks

    def test_handles_cyrillic(self):
        toks = _tokenize("ЦБ повысил ставку")
        assert "цб" in toks
        assert "повысить" in toks
        assert "ставка" in toks

    def test_none_returns_empty(self):
        assert _tokenize(None) == set()

    def test_empty_returns_empty(self):
        assert _tokenize("") == set()


class TestCosine:
    def test_orthogonal_vectors_score_zero(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_identical_vectors_score_one(self):
        v = [0.5] * 8
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_negative_cosine_clipped_to_zero(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine(a, b) == 0.0

    def test_length_mismatch_returns_zero(self):
        assert _cosine([1.0, 0.0], [1.0]) == 0.0

    def test_empty_inputs_return_zero(self):
        assert _cosine([], [1.0]) == 0.0
        assert _cosine([1.0], []) == 0.0
        assert _cosine([], []) == 0.0

    def test_zero_norm_returns_zero(self):
        # All-zero vector has norm 0 → guard against ZeroDivisionError.
        assert _cosine([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0


class TestPostUrl:
    def test_public_channel_returns_t_me_link(self):
        assert _post_url("tg:crypto_news:post:42") == "https://t.me/crypto_news/42"

    def test_strips_at_prefix(self):
        # Some legacy source_refs include the leading @; should still work.
        assert _post_url("tg:@crypto_news:post:42") == "https://t.me/crypto_news/42"

    def test_non_tg_scheme_returns_none(self):
        assert _post_url("twitter:elon:tweet:123") is None

    def test_too_few_parts_returns_none(self):
        assert _post_url("tg:crypto_news") is None

    def test_non_numeric_msg_id_returns_none(self):
        assert _post_url("tg:crypto_news:post:abc") is None

    def test_empty_channel_returns_none(self):
        assert _post_url("tg::post:42") is None


class TestCanonicalInterestText:
    def test_uses_description_title_keywords_when_all_present(self):
        interest = _make_interest(interest_id="int-1", keywords=["mica", "psd3"])
        text = build_canonical_interest_text(interest)
        # Description (in fixture) + title + space-joined keywords.
        assert "Watch for crypto regulation news" in text
        assert "MiCA / EU crypto regulation" in text
        assert "mica psd3" in text

    def test_falls_back_to_title_when_no_description_or_keywords(self):
        bare = WatchInterest(
            id="x",
            user_id="u",
            chat_id=1,
            title="JustTitle",
            description=None,
            keywords=[],
            exclude_keywords=[],
            channel_ids=["c"],
            threshold=0.5,
            notify_mode=NotifyMode.INSTANT,
            is_active=True,
            embedding=None,
        )
        assert build_canonical_interest_text(bare) == "JustTitle"

    def test_strips_whitespace_only_keywords(self):
        interest = _make_interest(interest_id="x", keywords=["   ", "mica", " "])
        text = build_canonical_interest_text(interest)
        # Whitespace-only kw must not show up as a stray separator.
        assert "mica" in text
        assert "  " not in text  # no double-space hole

    def test_never_returns_empty_for_minimal_title(self):
        # Pydantic model enforces ``title`` min_length=1, so the canonical
        # text is guaranteed non-empty even when description/keywords are
        # absent — protects the OpenAI embed call from 400 "empty input"
        # (gotcha #1).
        minimal = WatchInterest(
            id="x",
            user_id="u",
            chat_id=1,
            title="A",
            description=None,
            keywords=[],
            exclude_keywords=[],
            channel_ids=["c"],
            threshold=0.5,
            notify_mode=NotifyMode.INSTANT,
            is_active=True,
            embedding=None,
        )
        text = build_canonical_interest_text(minimal)
        assert text == "A"


# ----------------------------------------------------------------------------
# compute_watch_score (hybrid scoring)
# ----------------------------------------------------------------------------


class TestComputeWatchScore:
    def test_full_keyword_overlap_no_embedding_returns_keyword_only(self):
        # No embeddings on either side → semantic_available=False, formula
        # collapses to pure keyword score (no SEMANTIC_WEIGHT * 0 dilution).
        interest = _make_interest(interest_id="int-1", keywords=["mica"], embedding=None)
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA news")
        score = compute_watch_score(interest, doc, None)
        assert score.semantic_available is False
        assert score.keyword == pytest.approx(1.0)
        assert score.combined == pytest.approx(1.0)
        assert score.excluded is False

    def test_partial_overlap_recall_like(self):
        interest = _make_interest(
            interest_id="int-1",
            keywords=["mica", "psd3", "nis2", "dora"],
            embedding=None,
        )
        doc = _make_doc(source_ref="tg:c:post:1", text="Only MiCA mention")
        score = compute_watch_score(interest, doc, None)
        # ADR 0010: 1 hit out of 4 keywords. Under the default "topk" scheme
        # (K=3) keyword = min(1, 3)/3 = 1/3 (the old mean was 1/4 = 0.25).
        assert score.keyword == pytest.approx(1 / 3)
        assert score.combined == pytest.approx(1 / 3)

    def test_hybrid_formula_when_both_embeddings_present(self):
        # keyword=1.0, semantic=1.0 → combined = 0.4*1 + 0.6*1 = 1.0
        # keyword=0.0, semantic=1.0 → combined = 0.6
        interest = _make_interest(
            interest_id="int-1",
            keywords=["mica"],
            embedding=[1.0] + [0.0] * 1535,
        )
        doc = _make_doc(source_ref="tg:c:post:1", text="totally unrelated body text")
        score = compute_watch_score(interest, doc, [1.0] + [0.0] * 1535)
        assert score.keyword == pytest.approx(0.0)
        assert score.semantic == pytest.approx(1.0)
        assert score.combined == pytest.approx(SEMANTIC_WEIGHT)

    def test_exclude_keywords_force_combined_to_zero(self):
        interest = _make_interest(
            interest_id="int-1",
            keywords=["mica"],
            embedding=None,
        ).model_copy(update={"exclude_keywords": ["meme"]})
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA meme nonsense")
        score = compute_watch_score(interest, doc, None)
        assert score.excluded is True
        assert score.combined == 0.0
        assert score.keyword > 0  # raw keyword still computed for telemetry

    def test_empty_keywords_zero_score(self):
        interest = _make_interest(interest_id="int-1", keywords=[], embedding=None)
        doc = _make_doc(source_ref="tg:c:post:1", text="anything")
        score = compute_watch_score(interest, doc, None)
        assert score.keyword == 0.0

    def test_combined_never_exceeds_one_or_below_zero(self):
        # Synthetic worst-case to verify the [0, 1] clamp.
        interest = _make_interest(
            interest_id="int-1",
            keywords=["mica"],
            embedding=[1.0] + [0.0] * 1535,
        )
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA")
        score = compute_watch_score(interest, doc, [1.0] + [0.0] * 1535)
        assert 0.0 <= score.combined <= 1.0
        # Sanity-check the formula coefficients haven't drifted.
        assert KEYWORD_WEIGHT + SEMANTIC_WEIGHT == pytest.approx(1.0)


# ----------------------------------------------------------------------------
# check_interests — branches not covered by the headline tests
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckInterestsBranches:
    async def test_skips_match_when_excluded(self):
        # exclude_keywords overrides positive keyword overlap → no match
        # persisted, no notification sent.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        interest = _make_interest(keywords=["mica"], threshold=0.4, embedding=None).model_copy(
            update={"exclude_keywords": ["meme"]}
        )
        await ir.create(interest)
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA meme thread")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        result = await svc.check_interests("crypto_news", [doc.source_ref])
        assert result == []
        assert len(mr.store) == 0
        # Interest is still touched (we did look at it this tick).
        assert any(call[0] == interest.id or call[0] == "int-1" for call in ir.touch_checked_calls)

    async def test_no_processed_docs_branch_still_touches_interests(self):
        # Refs supplied but processed_doc_repo returns nothing (e.g. RAG
        # pipeline lag) → no scoring, but every active interest must still
        # have last_checked_at advanced so the next tick can rely on it.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"]))
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[])

        result = await svc.check_interests("crypto_news", ["tg:c:post:missing"])
        assert result == []
        touched_ids = {call[0] for call in ir.touch_checked_calls}
        assert touched_ids == {"int-1"}

    async def test_notify_invoked_when_bot_supplied(self):
        # check_interests with bot=... must dispatch notifications and
        # mark_notified the inserted matches.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        result = await svc.check_interests("crypto_news", [doc.source_ref], bot=bot)
        assert len(result) == 1
        assert len(bot.sent) == 1
        # Persisted match was flipped to notified.
        stored = next(iter(mr.store.values()))
        assert stored.notified is True

    async def test_notify_failure_does_not_mask_inserted(self):
        # If notify() raises, check_interests must still RETURN the inserted
        # matches (they live in the DB) — graceful degradation contract.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot(raises=Exception("temporary network error"))
        result = await svc.check_interests("crypto_news", [doc.source_ref], bot=bot)
        # Match inserted, notify failed (transient — interest still active).
        assert len(result) == 1
        stored_interest = await ir.get(result[0].interest_id)
        assert stored_interest is not None
        assert stored_interest.is_active is True


# ----------------------------------------------------------------------------
# notify — error / id-zero branches not covered above
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNotifyEdgeCases:
    async def test_skips_mark_notified_when_match_id_is_zero(self):
        # Synthetic match_id=0 means the row has not been persisted yet (e.g.
        # caller passed an in-memory candidate). mark_notified must not be
        # invoked with `0` — the SQL would silently match no rows but the
        # spurious call is wasted DB I/O. We verify by tracking calls.
        ir = _FakeInterestRepo()

        class _RecordingMatchRepo(_FakeMatchRepo):
            def __init__(self):
                super().__init__()
                self.mark_calls: list[list[int]] = []

            async def mark_notified(self, match_ids: list[int]) -> None:
                self.mark_calls.append(list(match_ids))
                await super().mark_notified(match_ids)

        mr = _RecordingMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA")
        match_zero = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=0)
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        outcomes = await svc.notify([match_zero], _FakeBot())
        assert outcomes["int-1"] == "sent"
        # Either mark_notified was never called, or it was called with [].
        assert all(call == [] for call in mr.mark_calls)

    async def test_mark_notified_failure_does_not_propagate(self):
        # mark_notified is a soft-fail: if it raises, the user has already
        # received the message, so we must not bubble the error up to the
        # scheduler (would block the next tick).
        ir = _FakeInterestRepo()

        class _BrokenMatchRepo(_FakeMatchRepo):
            async def mark_notified(self, match_ids):
                raise RuntimeError("DB temporarily unavailable")

        mr = _BrokenMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        doc = _make_doc(source_ref="tg:c:post:1", text="MiCA")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        # Must not raise.
        outcomes = await svc.notify([match], _FakeBot())
        assert outcomes["int-1"] == "sent"

    async def test_continues_after_single_group_failure(self):
        # One interest's bot send fails; the second group must still be
        # delivered.  Scheduler-style "errors don't poison neighbours".
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1"))
        await ir.create(_make_interest(interest_id="int-2").model_copy(update={"chat_id": 999}))
        doc1 = _make_doc(source_ref="tg:c:post:1", text="MiCA 1")
        doc2 = _make_doc(source_ref="tg:c:post:2", text="MiCA 2")
        m1 = _make_match(interest_id="int-1", source_ref=doc1.source_ref, match_id=10)
        m2 = _make_match(interest_id="int-2", source_ref=doc2.source_ref, match_id=20)
        await mr.upsert_many([m1, m2])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc1, doc2])

        # Bot raises on first chat_id, succeeds on second.
        class _SelectiveBot:
            def __init__(self):
                self.sent = []

            async def send_message(self, *, chat_id, text, parse_mode=None):
                if chat_id == 12345:
                    raise Exception("temporary")
                self.sent.append({"chat_id": chat_id, "text": text})

        bot = _SelectiveBot()
        outcomes = await svc.notify([m1, m2], bot)
        assert outcomes["int-1"] == "send_failed"
        assert outcomes["int-2"] == "sent"
        assert len(bot.sent) == 1
        assert bot.sent[0]["chat_id"] == 999


# ----------------------------------------------------------------------------
# WatchlistService.aclose
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAclose:
    async def test_no_op_when_client_is_none(self):
        svc = _make_service(embedding_client=None)
        # Should not raise.
        await svc.aclose()

    async def test_closes_underlying_client(self):
        class _ClosingClient:
            def __init__(self):
                self.closed = False

            async def embed(self, texts):
                return [[0.1] * 1536 for _ in texts]

            async def close(self):
                self.closed = True

        client = _ClosingClient()
        svc = _make_service(embedding_client=client)
        await svc.aclose()
        assert client.closed is True

    async def test_swallows_close_failure(self):
        class _FailingClient:
            async def embed(self, texts):
                return []

            async def close(self):
                raise RuntimeError("connection already torn down")

        svc = _make_service(embedding_client=_FailingClient())
        # Must not propagate — scheduler hook calls aclose() in finally.
        await svc.aclose()


# ----------------------------------------------------------------------------
# make_watchlist_service factory
# ----------------------------------------------------------------------------


class TestMakeWatchlistService:
    def test_without_embedding_client(self):
        svc = make_watchlist_service(
            interest_repo=_FakeInterestRepo(),
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            with_embedding_client=False,
        )
        assert svc.embedding_client is None
        assert isinstance(svc, WatchlistService)

    def test_with_embedding_client_falls_back_when_create_raises(self, monkeypatch):
        # Simulate "OPENAI_API_KEY missing" by making create_embedding_client
        # raise — the factory must downgrade to keyword-only mode, not crash.
        import tg_parser.services.embedding_service as embedding_service

        def _boom(*_a, **_kw):
            raise RuntimeError("OPENAI_API_KEY not configured")

        monkeypatch.setattr(embedding_service, "create_embedding_client", _boom)

        svc = make_watchlist_service(
            interest_repo=_FakeInterestRepo(),
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            with_embedding_client=True,
        )
        assert svc.embedding_client is None

    def test_with_embedding_client_uses_factory(self, monkeypatch):
        import tg_parser.services.embedding_service as embedding_service

        sentinel = object()

        def _make(*_a, **_kw):
            return sentinel

        monkeypatch.setattr(embedding_service, "create_embedding_client", _make)

        svc = make_watchlist_service(
            interest_repo=_FakeInterestRepo(),
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            with_embedding_client=True,
        )
        assert svc.embedding_client is sentinel


# ----------------------------------------------------------------------------
# DIAG 2026-06-07 Tier 3: phrase-level keyword scoring (multi-word fix)
# ----------------------------------------------------------------------------


class TestPhraseKeywordScore:
    def test_single_token_keywords_behave_like_old_overlap(self):
        # Backward-compat (mean-math, ADR 0010): each single-token keyword is
        # its own phrase, so the recall fraction is identical to the previous
        # token-set intersection. Pins aggregation="mean" since the default is
        # now "topk" (which would give min(1,3)/3 = 1/3 for the 4-keyword pack).
        doc_tokens = _tokenize("Only MiCA mention here")
        assert _keyword_score(
            ["mica", "psd3", "nis2", "dora"], doc_tokens, aggregation="mean"
        ) == pytest.approx(0.25)
        assert _keyword_score(["mica"], doc_tokens) == pytest.approx(1.0)

    def test_multiword_keyword_requires_all_tokens_present(self):
        # "агонисты дофамина" only counts when BOTH tokens are present; a doc
        # mentioning just one token does not partially credit the phrase.
        partial = _tokenize("новость про агонисты рецепторов")
        full = _tokenize("агонисты дофамина в терапии")
        assert _keyword_score(["агонисты дофамина"], partial) == pytest.approx(0.0)
        assert _keyword_score(["агонисты дофамина"], full) == pytest.approx(1.0)

    def test_denominator_is_phrase_count_not_token_count(self):
        # Two keywords, one of them two words: denominator is 2 (phrases), not
        # 3 (tokens). Matching only the single-word keyword yields 0.5, whereas
        # the old token-union logic would have returned 1/3.
        doc_tokens = _tokenize("семаглутид показан при диабете")
        score = _keyword_score(["агонисты дофамина", "семаглутид"], doc_tokens)
        assert score == pytest.approx(0.5)

    def test_empty_keywords_zero(self):
        assert _keyword_score([], _tokenize("anything")) == pytest.approx(0.0)
        assert _keyword_score(["   "], _tokenize("anything")) == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# DIAG 2026-06-07 Tier 3: configurable hybrid weights
# ----------------------------------------------------------------------------


class TestConfigurableWeights:
    def test_custom_weights_rebalance_combined(self):
        # keyword=0.0, semantic=1.0 → with default weights combined=0.6; with
        # a keyword-heavy 0.8/0.2 split the same pair yields 0.2.
        interest = _make_interest(keywords=["mica"], embedding=[1.0] + [0.0] * 1535)
        doc = _make_doc(source_ref="tg:c:post:1", text="totally unrelated body")
        default = compute_watch_score(interest, doc, [1.0] + [0.0] * 1535)
        assert default.combined == pytest.approx(SEMANTIC_WEIGHT)
        rebalanced = compute_watch_score(
            interest,
            doc,
            [1.0] + [0.0] * 1535,
            keyword_weight=0.8,
            semantic_weight=0.2,
        )
        assert rebalanced.combined == pytest.approx(0.2)

    def test_service_threads_injected_weights(self):
        svc = WatchlistService(
            interest_repo=_FakeInterestRepo(),
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
            keyword_weight=0.7,
            semantic_weight=0.3,
        )
        assert svc._keyword_weight == pytest.approx(0.7)
        assert svc._semantic_weight == pytest.approx(0.3)


# ----------------------------------------------------------------------------
# DIAG 2026-06-07 Tier 2: retroactive backfill scorer
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBackfillInterest:
    async def test_dry_run_scores_without_persisting(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        # Historical doc that would match, ingested "before" the interest.
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        result = await svc.backfill_interest(
            "int-1", since=datetime(2020, 1, 1, tzinfo=UTC), dry_run=True
        )
        assert isinstance(result, BackfillResult)
        assert result.dry_run is True
        assert result.scored_docs == 1
        assert result.would_match == 1
        assert result.inserted == 0
        # Nothing persisted, no match/checked stamp on a dry run.
        assert len(mr.store) == 0
        assert ir.touch_match_calls == []

    async def test_apply_persists_matches_and_stamps(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        result = await svc.backfill_interest(
            "int-1", since=datetime(2020, 1, 1, tzinfo=UTC), dry_run=False
        )
        assert result.dry_run is False
        assert result.inserted == 1
        assert len(mr.store) == 1
        assert any(call[0] == "int-1" for call in ir.touch_match_calls)

    async def test_apply_is_idempotent_on_rerun(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        since = datetime(2020, 1, 1, tzinfo=UTC)
        first = await svc.backfill_interest("int-1", since=since, dry_run=False)
        second = await svc.backfill_interest("int-1", since=since, dry_run=False)
        assert first.inserted == 1
        assert second.inserted == 0  # already matched → no duplicate
        assert len(mr.store) == 1

    async def test_missing_interest_returns_error(self):
        svc = _make_service()
        result = await svc.backfill_interest("does-not-exist")
        assert result.error == "interest not found"
        assert result.scored_docs == 0

    async def test_inactive_interest_returns_error(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], is_active=False))
        svc = _make_service(interest_repo=ir)
        result = await svc.backfill_interest("int-1")
        assert result.error == "interest is inactive"

    async def test_limit_caps_scored_docs_newest_first(self):
        # ADR-0011: an *explicit* limit is still honoured as a newest-first
        # preview cap (the implicit MAX_BACKFILL_DOCS cap was retired).
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        old = _make_doc(
            source_ref="tg:crypto_news:post:1",
            text="MiCA old",
            processed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        new = _make_doc(
            source_ref="tg:crypto_news:post:2",
            text="MiCA new",
            processed_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[old, new])

        result = await svc.backfill_interest(
            "int-1", since=datetime(2020, 1, 1, tzinfo=UTC), limit=1, dry_run=False
        )
        assert result.scored_docs == 1
        # The newest doc (post:2) is the one that got scored/persisted.
        assert ("int-1", "tg:crypto_news:post:2") in mr.store

    # ---- ADR-0011 S3: full-corpus default + decoupled budgets ----

    async def test_since_none_scores_full_corpus_for_fresh_interest(self):
        # ADR-0011 Problem A: a freshly created interest has created_at ~= now,
        # so the OLD default (cutoff = interest.created_at) yielded an empty
        # window → 0 candidates. The new default (since=None → full corpus)
        # scores the whole history.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        # Interest created "now"; the doc was ingested long before.
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        old_doc = _make_doc(
            source_ref="tg:crypto_news:post:1",
            text="MiCA regulation update",
            processed_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[old_doc])

        # since=None (the new default) must NOT collapse to created_at.
        result = await svc.backfill_interest("int-1", dry_run=True)
        assert result.scored_docs == 1
        assert result.would_match == 1

    async def test_full_scoring_pass_not_truncated_beyond_old_cap(self):
        # ADR-0011 Problem B: the old MAX_BACKFILL_DOCS=2000 newest-first cap hid
        # old on-topic docs from calibration. With no explicit limit the whole
        # matched corpus is scored — assert >2000 docs are all scored.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        n_docs = 2050
        docs = [
            _make_doc(
                source_ref=f"tg:crypto_news:post:{i}",
                text="MiCA regulation update",
                processed_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=i),
            )
            for i in range(n_docs)
        ]
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=docs)

        result = await svc.backfill_interest("int-1", dry_run=True)
        assert result.scored_docs == n_docs  # not clamped at the retired 2000 cap
        assert result.would_match == n_docs

    async def test_batched_embedding_fetch_single_call_and_parity(self):
        # ADR-0011: the per-ref get_by_source_ref N+1 is replaced by ONE batched
        # get_many_by_source_refs call; scores must match what the embedding
        # would have produced per-ref (semantic component is exercised).
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        interest_vec = [1.0] + [0.0] * 1535
        await ir.create(
            _make_interest(
                interest_id="int-1",
                keywords=["mica"],
                threshold=0.5,
                embedding=interest_vec,
            )
        )
        docs = [
            _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA one"),
            _make_doc(source_ref="tg:crypto_news:post:2", text="MiCA two"),
            _make_doc(source_ref="tg:crypto_news:post:3", text="MiCA three"),
        ]
        embeddings = {d.source_ref: list(interest_vec) for d in docs}
        emb_repo = _FakeEmbeddingRepo(embeddings)
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo(docs),
            embedding_repo=emb_repo,
            embedding_client=None,
        )

        result = await svc.backfill_interest("int-1", dry_run=False)
        # Exactly one batched fetch — not one round-trip per doc.
        assert emb_repo.get_many_calls == 1
        assert result.scored_docs == 3
        # Parity: with a perfectly-aligned embedding the semantic component is
        # 1.0, so every doc clears and the persisted semantic_score reflects it.
        assert result.inserted == 3
        for match in mr.store.values():
            assert match.semantic_score == pytest.approx(1.0)

    async def test_apply_materializes_silently_with_notified_true(self):
        # ADR-0011 Part C: backfill matches are "seen" (notified=True) so they
        # land in history but are NOT pushed retroactively.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        result = await svc.backfill_interest("int-1", dry_run=False)
        assert result.inserted == 1
        assert all(m.notified is True for m in mr.store.values())

    async def test_go_forward_matches_still_notify_unchanged(self):
        # ADR-0011: contrast — per-tick scheduler matches keep notified=False so
        # notify() still pushes them (go-forward behaviour is untouched).
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        await svc.check_interests("crypto_news", [doc.source_ref])
        assert mr.store, "go-forward tick should persist a match"
        assert all(m.notified is False for m in mr.store.values())

    async def test_apply_does_not_invoke_notify(self):
        # ADR-0011 Part C: backfill materializes silently — it must NEVER call
        # notify() (the flood-risk surface). The notified=True flag guards the
        # passive ``notified=False`` selector; this spy guards the active push
        # path so a future regression that wires notify() into backfill fails
        # loudly here. Complements test_apply_materializes_silently_with_notified_true.
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", keywords=["mica"], threshold=0.5))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation update")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        notify_calls: list[tuple[Any, ...]] = []

        async def _spy_notify(*args: Any, **kwargs: Any) -> dict[str, str]:
            notify_calls.append((args, kwargs))
            return {}

        svc.notify = _spy_notify  # type: ignore[method-assign]

        result = await svc.backfill_interest("int-1", dry_run=False)
        assert result.inserted == 1
        # Match landed in history, but no push was attempted.
        assert notify_calls == []

    async def test_mixed_embedding_presence_scores_all_and_falls_back(self):
        # ADR-0011 batched-fetch contract: get_many_by_source_refs returns only
        # the refs that HAVE an embedding; refs without one are simply absent
        # from the dict and the scorer must fall back to keyword-only for them
        # (semantic_available=False → semantic_score 0.0) instead of raising.
        # Pins the "refs with NO embedding → absent/None handled" parity edge in
        # ONE batched call (not an N+1, not a KeyError).
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        interest_vec = [1.0] + [0.0] * 1535
        await ir.create(
            _make_interest(
                interest_id="int-1",
                keywords=["mica"],
                threshold=0.5,
                embedding=interest_vec,
            )
        )
        with_emb = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA one")
        without_emb = _make_doc(source_ref="tg:crypto_news:post:2", text="MiCA two")
        # Only post:1 has a stored embedding; post:2 is intentionally absent.
        emb_repo = _FakeEmbeddingRepo({with_emb.source_ref: list(interest_vec)})
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo([with_emb, without_emb]),
            embedding_repo=emb_repo,
            embedding_client=None,
        )

        result = await svc.backfill_interest("int-1", dry_run=False)
        # Both docs scored in a single batched fetch (no N+1, no crash).
        assert emb_repo.get_many_calls == 1
        assert result.scored_docs == 2
        assert result.inserted == 2
        semantic_by_ref = {m.source_ref: m.semantic_score for m in mr.store.values()}
        # Aligned embedding → semantic 1.0; missing embedding → keyword-only (0.0).
        assert semantic_by_ref[with_emb.source_ref] == pytest.approx(1.0)
        assert semantic_by_ref[without_emb.source_ref] == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# ADR 0012 (S2): threshold auto-calibration
# ----------------------------------------------------------------------------


class TestSuggestThresholdFromScores:
    def test_target_fraction_picks_nth_highest(self):
        # 100 scores descending 1.0 .. 0.01 — 3% → target 10 (min clamp).
        scores = [i / 100.0 for i in range(100, 0, -1)]
        cal = suggest_threshold_from_scores(
            scores,
            strategy="target_fraction",
            target_fraction=0.03,
            target_min_matches=10,
            target_max_matches=150,
        )
        assert cal.fallback_used is False
        assert cal.target_matches == 10
        assert cal.suggested_threshold == pytest.approx(0.91)
        assert cal.would_match == 10

    def test_empty_corpus_falls_back_to_default(self):
        cal = suggest_threshold_from_scores([], default_threshold=0.55)
        assert cal.fallback_used is True
        assert cal.reason == "empty_corpus"
        assert cal.suggested_threshold == pytest.approx(0.55)

    def test_small_corpus_marks_low_confidence(self):
        scores = [0.8, 0.7, 0.6]
        cal = suggest_threshold_from_scores(
            scores,
            min_corpus_size=20,
            target_min_matches=2,
            target_max_matches=150,
            target_fraction=0.5,
        )
        assert cal.confidence == "low"
        assert cal.fallback_used is False

    def test_percentile_strategy(self):
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        cal = suggest_threshold_from_scores(
            scores,
            strategy="percentile",
            percentile=90.0,
            target_min_matches=1,
        )
        assert cal.strategy == "percentile"
        assert cal.suggested_threshold >= 0.8

    # ------------------------------------------------------------------
    # ADR 0013: absolute precision floor
    # ------------------------------------------------------------------

    def test_narrow_distribution_is_floored(self):
        """NARROW interest (thin tail, most scores < floor) → floored cutoff.

        Without the floor the target-fraction cutoff lands in the noise band
        (the 10th-highest score is 0.15) and matches the whole low cluster.
        The floor caps the cutoff at ``min_threshold`` and ``would_match`` is
        recomputed against the floored threshold (only the 3 real matches).
        """
        scores = [0.62, 0.55, 0.48] + [0.15] * 97
        cal = suggest_threshold_from_scores(
            scores,
            strategy="target_fraction",
            target_fraction=0.03,
            target_min_matches=10,
            target_max_matches=150,
            min_threshold=0.45,
        )
        assert cal.floor_applied is True
        assert cal.suggested_threshold == pytest.approx(0.45)
        assert cal.pre_floor_threshold == pytest.approx(0.15)
        # PRE-floor volume target is preserved for transparency...
        assert cal.target_matches == 10
        # ...but the recomputed match count reflects the floored cutoff.
        assert cal.would_match == 3

    def test_broad_distribution_is_unaffected_by_floor(self):
        """BROAD interest (fraction threshold already > floor) → no change.

        Identical to the pre-ADR-0013 behaviour: same suggested_threshold and
        would_match whether or not ``min_threshold`` is supplied.
        """
        scores = [i / 100.0 for i in range(100, 0, -1)]
        floored = suggest_threshold_from_scores(
            scores,
            strategy="target_fraction",
            target_fraction=0.03,
            target_min_matches=10,
            target_max_matches=150,
            min_threshold=0.45,
        )
        baseline = suggest_threshold_from_scores(
            scores,
            strategy="target_fraction",
            target_fraction=0.03,
            target_min_matches=10,
            target_max_matches=150,
        )
        assert floored.floor_applied is False
        assert floored.pre_floor_threshold is None
        assert floored.suggested_threshold == pytest.approx(0.91)
        assert floored.would_match == 10
        # Bit-for-bit identical to the no-floor call.
        assert floored.suggested_threshold == pytest.approx(baseline.suggested_threshold)
        assert floored.would_match == baseline.would_match
        assert floored.target_matches == baseline.target_matches

    def test_floor_wins_over_min_matches(self):
        """Floor-vs-min_matches precedence: the floor wins (precision-first).

        Flooring drops ``would_match`` (3) below ``target_min_matches`` (10),
        yet the threshold stays at the floor (0.45) — it is NOT lowered back to
        the pre-floor 0.2 to recover the missing 7 matches.
        """
        scores = [0.9, 0.8, 0.7] + [0.2] * 97
        cal = suggest_threshold_from_scores(
            scores,
            strategy="target_fraction",
            target_fraction=0.03,
            target_min_matches=10,
            target_max_matches=150,
            min_threshold=0.45,
        )
        assert cal.floor_applied is True
        assert cal.suggested_threshold == pytest.approx(0.45)
        assert cal.pre_floor_threshold == pytest.approx(0.2)
        assert cal.target_matches == 10
        # Floor wins: fewer matches than the volume target, not lowered.
        assert cal.would_match == 3
        assert cal.would_match < cal.target_matches

    def test_floor_defaults_to_zero_preserving_legacy_behaviour(self):
        """Default ``min_threshold=0.0`` is a no-op (ADR-0012 behaviour intact)."""
        scores = [0.62, 0.55, 0.48] + [0.15] * 97
        cal = suggest_threshold_from_scores(
            scores,
            strategy="target_fraction",
            target_fraction=0.03,
            target_min_matches=10,
        )
        assert cal.floor_applied is False
        assert cal.pre_floor_threshold is None
        assert cal.suggested_threshold == pytest.approx(0.15)

    def test_settings_default_min_threshold_is_045(self):
        """Backward-compat: the settings-surfaced floor default is 0.45."""
        settings = _load_calibration_settings()
        assert settings["min_threshold"] == pytest.approx(0.45)


@pytest.mark.asyncio
class TestThresholdCalibration:
    async def test_subscribe_without_threshold_calibrates_on_create(self):
        ir = _FakeInterestRepo()
        docs = [
            _make_doc(
                source_ref=f"tg:crypto_news:post:{i}",
                text="MiCA regulation update",
            )
            for i in range(1, 6)
        ]
        svc = _make_service(
            interest_repo=ir,
            docs=docs,
            embedding_client=_FakeEmbeddingClient(),
        )
        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        assert result.created is True
        assert result.threshold_calibration is not None
        assert result.interest.threshold != 0.6
        assert result.interest.threshold == result.threshold_calibration.suggested_threshold

    async def test_explicit_threshold_bypasses_calibration(self):
        ir = _FakeInterestRepo()
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        svc = _make_service(interest_repo=ir, docs=[doc])
        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.42,
        )
        assert result.threshold_calibration is None
        assert result.interest.threshold == pytest.approx(0.42)

    async def test_empty_corpus_subscribe_falls_back(self):
        ir = _FakeInterestRepo()
        svc = _make_service(interest_repo=ir, docs=[])
        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="Empty channel",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        assert result.threshold_calibration is not None
        assert result.threshold_calibration.fallback_used is True
        assert result.interest.threshold == pytest.approx(0.6)

    async def test_subscribe_update_without_threshold_preserves_existing(self):
        ir = _FakeInterestRepo()
        svc = _make_service(interest_repo=ir)
        first = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.45,
        )
        second = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        assert first.interest.threshold == pytest.approx(0.45)
        assert second.interest.threshold == pytest.approx(0.45)
        assert "threshold" not in second.changed_fields

    async def test_calibrate_threshold_matches_scoring_path(self):
        ir = _FakeInterestRepo()
        interest_vec = [1.0] + [0.0] * 1535
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation")
        embeddings = {doc.source_ref: list(interest_vec)}
        interest = _make_interest(
            keywords=["mica"],
            embedding=interest_vec,
            threshold=0.5,
        )
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([doc]),
            embedding_repo=_FakeEmbeddingRepo(embeddings),
            embedding_client=None,
        )
        cal = await svc.calibrate_threshold(interest)
        assert isinstance(cal, ThresholdCalibration)
        assert cal.scored_docs == 1
        assert cal.max_combined > 0.5
        assert cal.would_match >= 1


@pytest.mark.asyncio
class TestUpdatePathRecalibration:
    """BUG-054 / ADR 0015 — re-embed + provenance-aware recalibration on update."""

    @staticmethod
    def _docs() -> list[ProcessedDocument]:
        return [
            _make_doc(source_ref=f"tg:crypto_news:post:{i}", text="MiCA regulation update")
            for i in range(1, 6)
        ]

    # ---- create-path provenance ----

    async def test_create_explicit_threshold_marks_manual(self):
        ir = _FakeInterestRepo()
        svc = _make_service(interest_repo=ir, docs=self._docs())
        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.42,
        )
        assert result.interest.threshold_source == "manual"

    async def test_create_without_threshold_marks_auto(self):
        ir = _FakeInterestRepo()
        svc = _make_service(
            interest_repo=ir, docs=self._docs(), embedding_client=_FakeEmbeddingClient()
        )
        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        assert result.interest.threshold_source == "auto"

    async def test_create_without_threshold_calibration_disabled_marks_auto(self, monkeypatch):
        import tg_parser.services.watchlist_service as ws

        def _disabled() -> dict[str, object]:
            return {"enabled": False, "default_threshold": 0.6}

        monkeypatch.setattr(ws, "_load_calibration_settings", _disabled)
        ir = _FakeInterestRepo()
        svc = _make_service(interest_repo=ir, docs=self._docs())
        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        assert result.interest.threshold == pytest.approx(0.6)
        assert result.interest.threshold_source == "auto"

    # ---- update-path re-embed spy ----

    async def test_text_field_update_reembeds(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = _make_service(interest_repo=ir, docs=self._docs(), embedding_client=client)
        await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        embed_calls_before = len(client.calls)
        update_emb_before = len(ir.update_embedding_calls)

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica", "dora"],
            threshold=None,
        )

        assert "keywords" in result.changed_fields
        assert len(client.calls) == embed_calls_before + 1, "text-field update must re-embed"
        assert len(ir.update_embedding_calls) == update_emb_before + 1

    async def test_exclude_keywords_only_update_does_not_reembed(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = _make_service(interest_repo=ir, docs=self._docs(), embedding_client=client)
        await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        embed_calls_before = len(client.calls)
        update_emb_before = len(ir.update_embedding_calls)

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            exclude_keywords=["meme"],
            threshold=None,
        )

        assert result.changed_fields == ["exclude_keywords"]
        assert len(client.calls) == embed_calls_before, "exclude_keywords-only must NOT re-embed"
        assert len(ir.update_embedding_calls) == update_emb_before
        assert result.threshold_calibration is None

    async def test_threshold_only_update_does_not_reembed_and_marks_manual(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = _make_service(interest_repo=ir, docs=self._docs(), embedding_client=client)
        await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        embed_calls_before = len(client.calls)
        update_emb_before = len(ir.update_embedding_calls)

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.33,
        )

        assert "threshold" in result.changed_fields
        assert len(client.calls) == embed_calls_before, "threshold-only must NOT re-embed"
        assert len(ir.update_embedding_calls) == update_emb_before
        assert result.interest.threshold == pytest.approx(0.33)
        assert result.interest.threshold_source == "manual"

    # ---- provenance branches on text-field update ----

    async def test_auto_interest_persists_recalibrated_threshold(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = _make_service(interest_repo=ir, docs=self._docs(), embedding_client=client)
        first = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=None,
        )
        assert first.interest.threshold_source == "auto"

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica", "regulation"],
            threshold=None,
        )

        # Auto interest refreshes its threshold (no advisory — it was applied).
        assert result.threshold_calibration is None
        assert result.interest.threshold_source == "auto"
        stored = await ir.get(result.interest.id)
        assert stored is not None
        assert stored.threshold_source == "auto"

    async def test_manual_interest_keeps_threshold_returns_advisory(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = _make_service(interest_repo=ir, docs=self._docs(), embedding_client=client)
        await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.42,
        )

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica", "regulation"],
            threshold=None,
        )

        # Manual cutoff is preserved; the suggestion is advisory only.
        assert result.interest.threshold == pytest.approx(0.42)
        assert result.interest.threshold_source == "manual"
        assert result.threshold_calibration is not None
        assert "threshold" not in result.changed_fields

    async def test_legacy_interest_keeps_threshold_returns_advisory(self):
        ir = _FakeInterestRepo()
        client = _FakeEmbeddingClient()
        svc = _make_service(interest_repo=ir, docs=self._docs(), embedding_client=client)
        first = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica"],
            threshold=0.55,
        )
        # Force the row into the legacy-backfill state.
        ir.store[first.interest.id] = ir.store[first.interest.id].model_copy(
            update={"threshold_source": "legacy"}
        )

        result = await svc.subscribe(
            user_id="user-1",
            chat_id=12345,
            title="MiCA watch",
            channel_ids=["crypto_news"],
            keywords=["mica", "regulation"],
            threshold=None,
        )

        assert result.interest.threshold == pytest.approx(0.55)
        assert result.interest.threshold_source == "legacy"
        assert result.threshold_calibration is not None
        assert "threshold" not in result.changed_fields
