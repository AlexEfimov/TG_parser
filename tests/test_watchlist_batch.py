"""F11 P2 — batch + silent delivery (ADR-0014).

Covers:

- ``flush_batch`` groups pending matches per batch-mode interest, sends one
  message each, and flips ``notified=True`` only on a successful send;
- SILENT interests journal the match (``notified=True`` at creation) but never
  push and are never batched;
- dedup across two consecutive flushes (the second is a no-op);
- blocked-chat → soft-delete the interest + preserve the matches
  (``notified=False``);
- empty window → no-op (no send);
- paused interest is skipped, then flushes on resume;
- instant mode is unchanged (regression): ``flush_batch`` ignores instant
  interests and ``notify`` still delivers them.
- the ``run_watchlist_batch_flush`` scheduler hook builds the service, calls
  ``flush_batch(get_bot())``, ``aclose()``s, and no-ops without a bot.

Uses the in-memory fakes pattern from ``tests/test_watchlist_service.py`` with a
``list_unnotified_for_interests`` addition on the match-repo fake (ADR-0014).
"""

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
from tg_parser.services.watchlist_service import WatchlistService

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


class _FakeMatchRepo:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], WatchMatch] = {}
        self.next_id = 1
        self.upsert_calls: int = 0
        self.mark_calls: list[list[int]] = []

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

    async def list_unnotified_for_interests(
        self, interest_ids: list[str]
    ) -> list[WatchMatch]:
        ids = set(interest_ids)
        rows = [m for m in self.store.values() if not m.notified and m.interest_id in ids]
        return sorted(rows, key=lambda m: m.created_at)

    async def mark_notified(self, match_ids: list[int]) -> None:
        self.mark_calls.append(list(match_ids))
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
        return [d for d in self.by_ref.values() if d.channel_id == channel_id]


class _Stored:
    def __init__(self, value: list[float]):
        self.embedding = value


class _FakeEmbeddingRepo:
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


class _FakeBot:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.raises = raises

    async def send_message(self, *, chat_id: int, text: str, parse_mode: Any = None) -> None:
        if self.raises is not None:
            raise self.raises
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_doc(
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


def _make_interest(
    *,
    interest_id: str = "int-1",
    keywords: list[str] | None = None,
    threshold: float = 0.5,
    channel_ids: list[str] | None = None,
    is_active: bool = True,
    notify_mode: NotifyMode = NotifyMode.BATCH,
    chat_id: int = 12345,
) -> WatchInterest:
    return WatchInterest(
        id=interest_id,
        user_id="user-1",
        chat_id=chat_id,
        title="MiCA / EU crypto regulation",
        description="Watch for crypto regulation news",
        keywords=list(keywords or ["mica"]),
        exclude_keywords=[],
        channel_ids=list(channel_ids or ["crypto_news"]),
        threshold=threshold,
        notify_mode=notify_mode,
        is_active=is_active,
        embedding=None,
    )


def _make_match(
    *,
    interest_id: str,
    source_ref: str,
    match_id: int = 0,
    combined: float = 0.7,
    channel_id: str = "crypto_news",
    notified: bool = False,
) -> WatchMatch:
    return WatchMatch(
        id=match_id,
        interest_id=interest_id,
        source_ref=source_ref,
        channel_id=channel_id,
        keyword_score=0.6,
        semantic_score=0.8,
        combined_score=combined,
        created_at=datetime.now(UTC),
        notified=notified,
    )


def _make_service(
    *,
    interest_repo: _FakeInterestRepo,
    match_repo: _FakeMatchRepo,
    docs: list[ProcessedDocument] | None = None,
) -> WatchlistService:
    return WatchlistService(
        interest_repo=interest_repo,
        match_repo=match_repo,
        processed_doc_repo=_FakeProcessedDocRepo(docs or []),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


# ----------------------------------------------------------------------------
# flush_batch — happy path / dedup / empty window
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFlushBatch:
    async def test_flushes_grouped_message_and_marks_notified(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc1 = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news 1")
        doc2 = _make_doc(source_ref="tg:crypto_news:post:2", text="MiCA news 2")
        await mr.upsert_many(
            [
                _make_match(interest_id="int-1", source_ref=doc1.source_ref),
                _make_match(interest_id="int-1", source_ref=doc2.source_ref),
            ]
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc1, doc2])

        bot = _FakeBot()
        outcomes = await svc.flush_batch(bot)

        assert outcomes == {"int-1": "sent"}
        # ONE grouped message for the interest (both matches collapsed).
        assert len(bot.sent) == 1
        assert bot.sent[0]["chat_id"] == 12345
        # Watermark advanced for every match in the group.
        assert all(m.notified is True for m in mr.store.values())

    async def test_groups_per_interest(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        await ir.create(
            _make_interest(interest_id="int-2", notify_mode=NotifyMode.BATCH, chat_id=999)
        )
        d1 = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA a")
        d2 = _make_doc(source_ref="tg:crypto_news:post:2", text="MiCA b")
        await mr.upsert_many(
            [
                _make_match(interest_id="int-1", source_ref=d1.source_ref),
                _make_match(interest_id="int-2", source_ref=d2.source_ref),
            ]
        )
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[d1, d2])

        outcomes = await svc.flush_batch(_FakeBot())
        assert outcomes == {"int-1": "sent", "int-2": "sent"}

    async def test_dedup_second_flush_is_noop(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([_make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        first = await svc.flush_batch(bot)
        second = await svc.flush_batch(bot)

        assert first == {"int-1": "sent"}
        # No new notified=False rows → the second flush sends nothing.
        assert second == {}
        assert len(bot.sent) == 1

    async def test_empty_window_is_noop(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        # No matches at all.
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[])

        bot = _FakeBot()
        outcomes = await svc.flush_batch(bot)
        assert outcomes == {}
        assert bot.sent == []

    async def test_no_batch_interests_is_noop(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        # Even with a pending match, an instant interest is never batched.
        await mr.upsert_many([_make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        outcomes = await svc.flush_batch(bot)
        assert outcomes == {}
        assert bot.sent == []
        # The instant interest's match is untouched (still pending for notify()).
        assert all(m.notified is False for m in mr.store.values())


# ----------------------------------------------------------------------------
# blocked chat → soft-delete + preserve matches
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFlushBatchBlocked:
    async def test_blocked_chat_soft_deletes_and_preserves_matches(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([_make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot(raises=Exception("Bad Request: bot was blocked by the user"))
        outcomes = await svc.flush_batch(bot)

        assert outcomes == {"int-1": "send_failed"}
        # Interest soft-deleted to stop retry storms...
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is False
        # ...but the matches are preserved AND stay pending (watermark not moved).
        assert all(m.notified is False for m in mr.store.values())

    async def test_transient_failure_keeps_matches_pending(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([_make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot(raises=Exception("temporary network error"))
        outcomes = await svc.flush_batch(bot)

        assert outcomes == {"int-1": "send_failed"}
        # Transient → interest stays active and a later flush retries.
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is True
        assert all(m.notified is False for m in mr.store.values())

        # A retry with a healthy bot delivers the still-pending match.
        retry = await svc.flush_batch(_FakeBot())
        assert retry == {"int-1": "sent"}


# ----------------------------------------------------------------------------
# paused interest → flush on resume
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPausedFlushOnResume:
    async def test_paused_not_flushed_then_flushed_after_resume(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([_make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        # Pause the interest before any flush.
        await ir.soft_delete("int-1")

        bot = _FakeBot()
        paused_outcome = await svc.flush_batch(bot)
        # Inactive → skipped entirely; matches stay pending (not stranded).
        assert paused_outcome == {}
        assert bot.sent == []
        assert all(m.notified is False for m in mr.store.values())

        # Resume → the still-pending match flushes.
        await ir.resume("int-1")
        resumed_outcome = await svc.flush_batch(bot)
        assert resumed_outcome == {"int-1": "sent"}
        assert len(bot.sent) == 1
        assert all(m.notified is True for m in mr.store.values())


# ----------------------------------------------------------------------------
# SILENT — journal only (via check_interests)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSilentJournal:
    async def test_silent_records_notified_true_and_never_sends(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(
            _make_interest(
                interest_id="int-silent",
                keywords=["mica"],
                threshold=0.5,
                notify_mode=NotifyMode.SILENT,
            )
        )
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation news")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        # check_interests with a bot would push for INSTANT; SILENT must not.
        inserted = await svc.check_interests("crypto_news", [doc.source_ref], bot=bot)

        assert len(inserted) == 1
        # Born delivered → never pushed.
        assert inserted[0].notified is True
        assert bot.sent == []
        # Visible in history.
        history = await svc.get_matches("int-silent")
        assert len(history) == 1
        assert history[0].notified is True

    async def test_silent_never_picked_up_by_batch_flush(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(
            _make_interest(
                interest_id="int-silent",
                keywords=["mica"],
                threshold=0.5,
                notify_mode=NotifyMode.SILENT,
            )
        )
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation news")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        await svc.check_interests("crypto_news", [doc.source_ref])

        # SILENT match is notified=True, so the flush selects nothing.
        bot = _FakeBot()
        outcomes = await svc.flush_batch(bot)
        assert outcomes == {}
        assert bot.sent == []


# ----------------------------------------------------------------------------
# instant mode regression — flush ignores instant, notify still works
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInstantUnchanged:
    async def test_check_interests_instant_keeps_notified_false_and_pushes(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(
            _make_interest(
                interest_id="int-1",
                keywords=["mica"],
                threshold=0.5,
                notify_mode=NotifyMode.INSTANT,
            )
        )
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation news")
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        inserted = await svc.check_interests("crypto_news", [doc.source_ref], bot=bot)

        assert len(inserted) == 1
        # Instant push happened immediately and flipped the watermark.
        assert len(bot.sent) == 1
        assert all(m.notified is True for m in mr.store.values())

    async def test_notify_instant_path_still_delivers(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = _make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        match = _make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = _make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = _FakeBot()
        outcomes = await svc.notify(list(mr.store.values()), bot)
        assert outcomes == {"int-1": "sent"}
        assert len(bot.sent) == 1
        assert all(m.notified is True for m in mr.store.values())


# ----------------------------------------------------------------------------
# scheduler hook — run_watchlist_batch_flush
# ----------------------------------------------------------------------------


class _ReposCtx:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return ("interest", "match", "proc", "emb", "db")

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1


class _FlushService:
    def __init__(self, outcomes: dict[str, str] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[Any] = []
        self.closed = False

    async def flush_batch(self, bot: Any) -> dict[str, str]:
        self.calls.append(bot)
        return dict(self.outcomes)

    async def aclose(self) -> None:
        self.closed = True


def _patch_hook(monkeypatch, *, service: _FlushService, bot_marker: Any = "BOT"):
    from tg_parser.services import scheduler_service

    repos_ctx = _ReposCtx()
    db_context_module = __import__("tg_parser.services.db_context", fromlist=["watchlist_repos"])
    factory_module = __import__(
        "tg_parser.services.watchlist_service", fromlist=["make_watchlist_service"]
    )
    runtime_module = __import__("tg_parser.bot.runtime", fromlist=["get_bot"])

    monkeypatch.setattr(db_context_module, "watchlist_repos", lambda: repos_ctx)
    monkeypatch.setattr(factory_module, "make_watchlist_service", lambda **_kw: service)
    monkeypatch.setattr(runtime_module, "get_bot", lambda: bot_marker)
    return scheduler_service, repos_ctx


@pytest.mark.asyncio
async def test_hook_flushes_and_closes_service(monkeypatch):
    svc = _FlushService(outcomes={"int-1": "sent", "int-2": "send_failed"})
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc)

    result = await scheduler_service.run_watchlist_batch_flush()

    assert result == {"flushed": 1, "interests": 2, "skipped_reason": None}
    assert repos_ctx.entered == 1
    assert repos_ctx.exited == 1
    assert svc.closed is True
    assert svc.calls == ["BOT"]


@pytest.mark.asyncio
async def test_hook_noop_when_bot_unavailable(monkeypatch):
    svc = _FlushService()
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc, bot_marker=None)

    result = await scheduler_service.run_watchlist_batch_flush()

    assert result == {"flushed": 0, "skipped_reason": "no_bot"}
    # Without a bot the repos context is never entered and no flush is attempted.
    assert repos_ctx.entered == 0
    assert svc.calls == []
    assert svc.closed is False


@pytest.mark.asyncio
async def test_hook_closes_service_even_when_flush_raises(monkeypatch):
    class _BoomService(_FlushService):
        async def flush_batch(self, bot: Any) -> dict[str, str]:
            self.calls.append(bot)
            raise RuntimeError("boom")

    svc = _BoomService()
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc)

    with pytest.raises(RuntimeError, match="boom"):
        await scheduler_service.run_watchlist_batch_flush()

    assert repos_ctx.exited == 1
    assert svc.closed is True
