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

Uses the shared in-memory fakes from ``tests/_watchlist_fakes.py`` (extracted
from this file when BUG-095 added the second delivery path).
"""

from __future__ import annotations

from typing import Any

import pytest
from _watchlist_fakes import (
    FakeBot,
    FakeInterestRepo,
    FakeMatchRepo,
    make_doc,
    make_interest,
    make_match,
    make_service,
)

from tg_parser.domain.models import NotifyMode

# ----------------------------------------------------------------------------
# flush_batch — happy path / dedup / empty window
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFlushBatch:
    async def test_flushes_grouped_message_and_marks_notified(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc1 = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news 1")
        doc2 = make_doc(source_ref="tg:crypto_news:post:2", text="MiCA news 2")
        await mr.upsert_many(
            [
                make_match(interest_id="int-1", source_ref=doc1.source_ref),
                make_match(interest_id="int-1", source_ref=doc2.source_ref),
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc1, doc2])

        bot = FakeBot()
        outcomes = await svc.flush_batch(bot)

        assert outcomes == {"int-1": "sent"}
        # ONE grouped message for the interest (both matches collapsed).
        assert len(bot.sent) == 1
        assert bot.sent[0]["chat_id"] == 12345
        # Watermark advanced for every match in the group.
        assert all(m.notified is True for m in mr.store.values())

    async def test_groups_per_interest(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        await ir.create(
            make_interest(interest_id="int-2", notify_mode=NotifyMode.BATCH, chat_id=999)
        )
        d1 = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA a")
        d2 = make_doc(source_ref="tg:crypto_news:post:2", text="MiCA b")
        await mr.upsert_many(
            [
                make_match(interest_id="int-1", source_ref=d1.source_ref),
                make_match(interest_id="int-2", source_ref=d2.source_ref),
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[d1, d2])

        outcomes = await svc.flush_batch(FakeBot())
        assert outcomes == {"int-1": "sent", "int-2": "sent"}

    async def test_dedup_second_flush_is_noop(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
        first = await svc.flush_batch(bot)
        second = await svc.flush_batch(bot)

        assert first == {"int-1": "sent"}
        # No new notified=False rows → the second flush sends nothing.
        assert second == {}
        assert len(bot.sent) == 1

    async def test_empty_window_is_noop(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        # No matches at all.
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[])

        bot = FakeBot()
        outcomes = await svc.flush_batch(bot)
        assert outcomes == {}
        assert bot.sent == []

    async def test_no_batch_interests_is_noop(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        # Even with a pending match, an instant interest is never batched.
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
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
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot(raises=Exception("Bad Request: bot was blocked by the user"))
        outcomes = await svc.flush_batch(bot)

        assert outcomes == {"int-1": "send_failed"}
        # Interest soft-deleted to stop retry storms...
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is False
        # ...but the matches are preserved AND stay pending (watermark not moved).
        assert all(m.notified is False for m in mr.store.values())

    async def test_transient_failure_keeps_matches_pending(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot(raises=Exception("temporary network error"))
        outcomes = await svc.flush_batch(bot)

        assert outcomes == {"int-1": "send_failed"}
        # Transient → interest stays active and a later flush retries.
        stored = await ir.get("int-1")
        assert stored is not None
        assert stored.is_active is True
        assert all(m.notified is False for m in mr.store.values())

        # A retry with a healthy bot delivers the still-pending match.
        retry = await svc.flush_batch(FakeBot())
        assert retry == {"int-1": "sent"}


# ----------------------------------------------------------------------------
# paused interest → flush on resume
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPausedFlushOnResume:
    async def test_paused_not_flushed_then_flushed_after_resume(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.BATCH))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        # Pause the interest before any flush.
        await ir.soft_delete("int-1")

        bot = FakeBot()
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
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(
            make_interest(
                interest_id="int-silent",
                keywords=["mica"],
                threshold=0.5,
                notify_mode=NotifyMode.SILENT,
            )
        )
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation news")
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
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
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(
            make_interest(
                interest_id="int-silent",
                keywords=["mica"],
                threshold=0.5,
                notify_mode=NotifyMode.SILENT,
            )
        )
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation news")
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        await svc.check_interests("crypto_news", [doc.source_ref])

        # SILENT match is notified=True, so the flush selects nothing.
        bot = FakeBot()
        outcomes = await svc.flush_batch(bot)
        assert outcomes == {}
        assert bot.sent == []


# ----------------------------------------------------------------------------
# instant mode regression — flush ignores instant, notify still works
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInstantUnchanged:
    async def test_check_interests_instant_keeps_notified_false_and_pushes(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(
            make_interest(
                interest_id="int-1",
                keywords=["mica"],
                threshold=0.5,
                notify_mode=NotifyMode.INSTANT,
            )
        )
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA regulation news")
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
        inserted = await svc.check_interests("crypto_news", [doc.source_ref], bot=bot)

        assert len(inserted) == 1
        # Instant push happened immediately and flipped the watermark.
        assert len(bot.sent) == 1
        assert all(m.notified is True for m in mr.store.values())

    async def test_notify_instant_path_still_delivers(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        match = make_match(interest_id="int-1", source_ref=doc.source_ref, match_id=10)
        await mr.upsert_many([match])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
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


# ----------------------------------------------------------------------------
# O-7 (F-08) — each document is lemmatised once per tick, not once per interest
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_interests_tokenizes_each_doc_once_per_tick(monkeypatch):
    """The hot nested loop is O(interests × docs); building doc tokens inside
    ``compute_watch_score`` would re-run pymorphy3 on the same doc for every
    interest (O(I×D)). O-7 precomputes them once (O(D)). This spy asserts
    ``_build_doc_tokens`` fires exactly D times (once per doc), not I×D.
    """
    import tg_parser.services.watchlist_service as ws

    ir = FakeInterestRepo()
    mr = FakeMatchRepo()
    # I = 3 interests, all active on the same channel.
    for i in range(3):
        await ir.create(
            make_interest(
                interest_id=f"int-{i}",
                keywords=["mica"],
                threshold=0.9,  # high → nothing delivered; scoring still runs
                notify_mode=NotifyMode.SILENT,
            )
        )
    # D = 4 docs.
    docs = [
        make_doc(source_ref=f"tg:crypto_news:post:{d}", text=f"MiCA regulation {d}")
        for d in range(4)
    ]
    svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

    real_build = ws._build_doc_tokens
    calls: list[str] = []

    def _spy(doc):
        calls.append(doc.source_ref)
        return real_build(doc)

    monkeypatch.setattr(ws, "_build_doc_tokens", _spy)

    await svc.check_interests("crypto_news", [d.source_ref for d in docs])

    # Exactly D calls (once per doc), NOT I×D (== 12).
    assert len(calls) == len(docs)
    assert sorted(calls) == sorted(d.source_ref for d in docs)
