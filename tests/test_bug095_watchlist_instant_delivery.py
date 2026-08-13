"""BUG-095 — instant watchlist matches are delivered from the bot process (form B).

Red/green for the R8 session. The defect: the instant matcher runs inside the
``tg_parser`` process, where ``get_bot()`` is permanently ``None``, and
``check_interests`` skipped delivery silently — matches piled up with
``notified=false`` for two months and nobody was told.

The fix mirrors the already-working ``flush_batch``: a second flush task,
registered in the **bot** process (the only process with a live ``Bot``),
selects ``notified=false`` matches of active INSTANT interests and delivers
them through the same ``_send_group``.

What each section pins:

1. ``TestCauseIsReproducible`` — the cause itself: ``bot=None`` + a non-empty
   ``inserted`` writes the match and sends nothing, while the same call with a
   ``Bot`` sends. Both halves pass before and after the fix; they are the
   executable statement of the root cause.
2. ``TestNoBotIsSaidOutLoud`` — the second defect named in BUG-095: the path
   that cannot deliver must say so. The batch neighbour already logs
   ``reason="no_bot"``; the instant path was silent.
3. ``TestInstantFlushDelivers`` — the fix. A match written without a bot
   becomes ``notified=true`` after the bot-process flush runs. RED before §3.2.
4. ``TestInstantFlushWatermark`` — the trap named in the plan:
   ``list_unnotified_for_interests`` has no date bound, so without a cutoff the
   first flush would ship the whole two-month backlog as one burst.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from structlog.testing import capture_logs

from tg_parser.domain.models import NotifyMode


@pytest.mark.asyncio
class TestCauseIsReproducible:
    """§3.1 — the root cause, stated as a test rather than as prose."""

    async def test_without_bot_the_match_is_recorded_and_nothing_is_sent(self):
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

        inserted = await svc.check_interests("crypto_news", [doc.source_ref], bot=None)

        # Matching, scoring and persistence all work — that is exactly why the
        # outage was invisible for two months.
        assert len(inserted) == 1
        assert inserted[0].notified is False
        # ...and the delivery watermark is never flipped, so the match stays
        # claimable by the bot-process flush.
        assert all(m.notified is False for m in mr.store.values())
        assert mr.mark_calls == []

    async def test_with_a_bot_the_same_call_sends(self):
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
        assert len(bot.sent) == 1
        assert all(m.notified is True for m in mr.store.values())


@pytest.mark.asyncio
class TestNoBotIsSaidOutLoud:
    """§3.4 — a path that cannot deliver must say so (the silence was a defect
    of its own: the batch neighbour logs ``reason="no_bot"``, the instant path
    logged nothing at all).
    """

    async def test_skipped_delivery_is_logged_with_a_reason(self):
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

        with capture_logs() as logs:
            await svc.check_interests("crypto_news", [doc.source_ref], bot=None)

        deferred = [r for r in logs if r.get("event") == "watchlist.instant_delivery_deferred"]
        assert len(deferred) == 1
        assert deferred[0]["reason"] == "no_bot"
        assert deferred[0]["pending"] == 1

    async def test_silent_mode_does_not_log_a_deferral(self):
        """SILENT matches are journal-only by design (ADR-0014) — they are born
        ``notified=True`` and are not waiting for anybody, so reporting them as
        deferred would be a false alarm.
        """
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

        with capture_logs() as logs:
            await svc.check_interests("crypto_news", [doc.source_ref], bot=None)

        assert [r for r in logs if r.get("event") == "watchlist.instant_delivery_deferred"] == []


@pytest.mark.asyncio
class TestInstantFlushDelivers:
    """§3.1 green half — the acceptance criterion of the whole session:
    "after a match on an instant interest, ``notified`` becomes ``true``".
    """

    async def test_match_written_without_a_bot_is_delivered_by_the_flush(self):
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

        # The tg_parser process: match written, delivery impossible.
        await svc.check_interests("crypto_news", [doc.source_ref], bot=None)
        assert all(m.notified is False for m in mr.store.values())

        # The bot process, one flush later.
        bot = FakeBot()
        outcomes = await svc.flush_instant(bot, since=_an_hour_ago())

        assert outcomes == {"int-1": "sent"}
        assert len(bot.sent) == 1
        assert bot.sent[0]["chat_id"] == 12345
        assert all(m.notified is True for m in mr.store.values())

    async def test_second_flush_is_a_noop(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
        first = await svc.flush_instant(bot, since=_an_hour_ago())
        second = await svc.flush_instant(bot, since=_an_hour_ago())

        assert first == {"int-1": "sent"}
        assert second == {}
        assert len(bot.sent) == 1

    async def test_one_grouped_message_per_interest(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        d1 = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA a")
        d2 = make_doc(source_ref="tg:crypto_news:post:2", text="MiCA b")
        await mr.upsert_many(
            [
                make_match(interest_id="int-1", source_ref=d1.source_ref),
                make_match(interest_id="int-1", source_ref=d2.source_ref),
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[d1, d2])

        bot = FakeBot()
        assert await svc.flush_instant(bot, since=_an_hour_ago()) == {"int-1": "sent"}
        assert len(bot.sent) == 1

    async def test_batch_interests_are_left_to_the_batch_flush(self):
        """§3.7 — the batch path is out of scope and must stay untouched: a
        BATCH interest's pending match belongs to the daily cron, not here.
        """
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-batch", notify_mode=NotifyMode.BATCH))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        await mr.upsert_many([make_match(interest_id="int-batch", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
        assert await svc.flush_instant(bot, since=_an_hour_ago()) == {}
        assert bot.sent == []
        assert all(m.notified is False for m in mr.store.values())

    async def test_paused_interest_is_skipped_and_flushes_on_resume(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])
        await ir.soft_delete("int-1")

        bot = FakeBot()
        assert await svc.flush_instant(bot, since=_an_hour_ago()) == {}
        assert bot.sent == []

        await ir.resume("int-1")
        assert await svc.flush_instant(bot, since=_an_hour_ago()) == {"int-1": "sent"}

    async def test_failed_send_leaves_the_match_pending(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA news")
        await mr.upsert_many([make_match(interest_id="int-1", source_ref=doc.source_ref)])
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        failing = FakeBot(raises=Exception("temporary network error"))
        assert await svc.flush_instant(failing, since=_an_hour_ago()) == {"int-1": "send_failed"}
        assert all(m.notified is False for m in mr.store.values())

        # The watermark is the ``notified`` flag, so the next flush retries.
        healthy = FakeBot()
        assert await svc.flush_instant(healthy, since=_an_hour_ago()) == {"int-1": "sent"}


@pytest.mark.asyncio
class TestInstantFlushWatermark:
    """§3.2 trap — ``list_unnotified_for_interests`` has no date bound. Without
    a cutoff the first flush after the deploy would ship every match accumulated
    since 2026-06-15 in one burst: the fix itself would produce exactly the
    flood the backlog decision exists to avoid.
    """

    async def test_matches_older_than_the_cutoff_are_never_delivered(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        old_doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA june")
        await mr.upsert_many(
            [
                make_match(
                    interest_id="int-1",
                    source_ref=old_doc.source_ref,
                    created_at=datetime(2026, 6, 20, tzinfo=UTC),
                )
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[old_doc])

        bot = FakeBot()
        cutoff = datetime(2026, 8, 13, tzinfo=UTC)
        assert await svc.flush_instant(bot, since=cutoff) == {}
        assert bot.sent == []
        # Untouched: the backlog belongs to the reconciliation, not to the flush.
        assert all(m.notified is False for m in mr.store.values())

    async def test_the_cutoff_separates_backlog_from_go_forward(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        old = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA june")
        new = make_doc(source_ref="tg:crypto_news:post:2", text="MiCA today")
        cutoff = datetime(2026, 8, 13, tzinfo=UTC)
        await mr.upsert_many(
            [
                make_match(
                    interest_id="int-1",
                    source_ref=old.source_ref,
                    created_at=cutoff - timedelta(days=54),
                ),
                make_match(
                    interest_id="int-1",
                    source_ref=new.source_ref,
                    created_at=cutoff + timedelta(minutes=5),
                ),
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[old, new])

        bot = FakeBot()
        assert await svc.flush_instant(bot, since=cutoff) == {"int-1": "sent"}
        # Exactly one message, and it covers only the post-cutoff match.
        assert len(bot.sent) == 1
        by_ref = {m.source_ref: m for m in mr.store.values()}
        assert by_ref[new.source_ref].notified is True
        assert by_ref[old.source_ref].notified is False


def _an_hour_ago() -> datetime:
    return datetime.now(UTC) - timedelta(hours=1)
