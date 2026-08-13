"""BUG-095 — wiring of the instant flush: process topology, watermark, backlog.

Separate from ``test_bug095_watchlist_instant_delivery.py``, which pins the
service behaviour. This file pins the decisions *around* the service, each of
which is a place BUG-095 could come back:

- the flush is registered in the bot process and nowhere else (registering it in
  ``setup_default_tasks`` is the bug, verbatim);
- the hook refuses to run without a bot or without a watermark, and says which;
- the backlog reconciliation sends one summary per chat, is idempotent, and
  never touches matches the flush owns;
- the undelivered gauge measures matches past their delivery window.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from structlog.testing import capture_logs

from tg_parser.domain.models import NotifyMode

_WATERMARK = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

# MarkdownV2 specials that must carry a backslash outside code spans. ``*`` and
# backtick are omitted: the composer uses them as live formatting markers.
_MD_V2_MUST_ESCAPE = "_[]()~>#+-=|{}.!"


def _assert_markdown_v2_escaped(text: str) -> None:
    in_code = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "`":
            in_code = not in_code
        elif char == "\\":
            index += 2
            continue
        elif not in_code and char in _MD_V2_MUST_ESCAPE:
            context = text[max(0, index - 30) : index + 30]
            raise AssertionError(f"unescaped MarkdownV2 {char!r} near: {context!r}")
        index += 1
    assert not in_code, "unbalanced code span"


# ----------------------------------------------------------------------------
# Process topology — the actual root cause
# ----------------------------------------------------------------------------


class TestDeliveryRunsInTheBotProcess:
    def test_instant_flush_is_registered_by_the_bot_and_not_by_default_tasks(self) -> None:
        """The one structural guarantee of form B.

        ``setup_default_tasks`` runs in the API / tg_parser process, where
        ``get_bot()`` is permanently ``None``. The batch flush was removed from
        it in 2026-06 for exactly that reason; putting the instant flush there
        would reproduce BUG-095 with a new task.
        """
        bot_main = Path("tg_parser/bot/main.py").read_text(encoding="utf-8")
        assert "_register_watchlist_instant_flush" in bot_main
        assert "run_watchlist_instant_flush" in bot_main

        scheduler_src = Path("tg_parser/services/background_scheduler.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(scheduler_src)
        setup = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "setup_default_tasks"
        )
        registered = {
            kw.value.value
            for call in ast.walk(setup)
            if isinstance(call, ast.Call)
            for kw in call.keywords
            if kw.arg == "task_id" and isinstance(kw.value, ast.Constant)
        }
        assert "watchlist_instant_flush" not in registered
        assert "watchlist_batch_flush" not in registered

    def test_registration_sets_the_watermark_before_scheduling_the_task(self) -> None:
        """A tick that fires before the watermark exists cannot deliver
        anything (the hook refuses), so ordering here is the difference between
        a working feature and a silent one for the first interval.
        """
        source = Path("tg_parser/bot/main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_register_watchlist_instant_flush"
        )
        calls = [
            node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
        ]
        assert calls.index("set_instant_flush_watermark") < calls.index("add_task")


# ----------------------------------------------------------------------------
# Scheduler hook — run_watchlist_instant_flush
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
    def __init__(self, outcomes: dict[str, str] | None = None, undelivered: int = 0) -> None:
        self.outcomes = outcomes or {}
        self.undelivered = undelivered
        self.calls: list[dict[str, Any]] = []
        self.count_calls: list[datetime] = []
        self.closed = False

    async def flush_instant(self, bot: Any, *, since: datetime) -> dict[str, str]:
        self.calls.append({"bot": bot, "since": since})
        return dict(self.outcomes)

    async def count_undelivered(self, *, older_than: datetime) -> int:
        self.count_calls.append(older_than)
        return self.undelivered

    async def aclose(self) -> None:
        self.closed = True


def _patch_hook(
    monkeypatch,
    *,
    service: _FlushService,
    bot_marker: Any = "BOT",
    watermark: datetime | None = _WATERMARK,
):
    from tg_parser.services import scheduler_service

    repos_ctx = _ReposCtx()
    db_context_module = __import__("tg_parser.services.db_context", fromlist=["watchlist_repos"])
    factory_module = __import__(
        "tg_parser.services.watchlist_service", fromlist=["make_watchlist_service"]
    )
    runtime_module = __import__("tg_parser.bot.runtime", fromlist=["get_bot"])

    monkeypatch.setattr(db_context_module, "watchlist_repos", lambda: repos_ctx)
    monkeypatch.setattr(factory_module, "make_watchlist_service", lambda **_kw: service)
    monkeypatch.setattr(factory_module, "get_instant_flush_watermark", lambda: watermark)
    monkeypatch.setattr(runtime_module, "get_bot", lambda: bot_marker)
    return scheduler_service, repos_ctx


@pytest.mark.asyncio
class TestInstantFlushHook:
    async def test_flushes_from_the_watermark_and_closes_the_service(self, monkeypatch):
        svc = _FlushService(outcomes={"int-1": "sent", "int-2": "send_failed"})
        scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc)

        result = await scheduler_service.run_watchlist_instant_flush()

        assert result == {
            "flushed": 1,
            "interests": 2,
            "undelivered": 0,
            "skipped_reason": None,
        }
        assert repos_ctx.entered == 1 and repos_ctx.exited == 1
        assert svc.closed is True
        assert svc.calls[0]["bot"] == "BOT"
        assert svc.calls[0]["since"] == _WATERMARK

    async def test_no_bot_is_a_loud_noop(self, monkeypatch):
        svc = _FlushService()
        scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc, bot_marker=None)

        with capture_logs() as logs:
            result = await scheduler_service.run_watchlist_instant_flush()

        assert result == {"flushed": 0, "skipped_reason": "no_bot"}
        assert repos_ctx.entered == 0
        assert svc.calls == []
        skipped = [r for r in logs if r.get("event") == "watchlist_instant_flush_skipped"]
        assert [r["reason"] for r in skipped] == ["no_bot"]

    async def test_without_a_watermark_the_flush_refuses_to_run(self, monkeypatch):
        """Fail closed. The selector has no date bound, so "no watermark" must
        never degrade into "deliver everything pending" — that is the burst the
        watermark exists to prevent.
        """
        svc = _FlushService()
        scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc, watermark=None)

        with capture_logs() as logs:
            result = await scheduler_service.run_watchlist_instant_flush()

        assert result == {"flushed": 0, "skipped_reason": "no_watermark"}
        assert repos_ctx.entered == 0
        assert svc.calls == []
        skipped = [r for r in logs if r.get("event") == "watchlist_instant_flush_skipped"]
        assert [r["reason"] for r in skipped] == ["no_watermark"]

    async def test_gauge_counts_only_matches_past_their_delivery_window(self, monkeypatch):
        from tg_parser.api.metrics import WATCHLIST_UNDELIVERED

        svc = _FlushService(undelivered=7)
        scheduler_service, _ = _patch_hook(monkeypatch, service=svc)

        before = datetime.now(UTC)
        result = await scheduler_service.run_watchlist_instant_flush()

        assert result["undelivered"] == 7
        assert WATCHLIST_UNDELIVERED._value.get() == 7
        # The staleness bound is "one flush interval ago", never "now" — matches
        # inside the current window are pending, not missed.
        (older_than,) = svc.count_calls
        interval = scheduler_service._instant_flush_interval_seconds()
        assert before - timedelta(seconds=interval + 5) <= older_than <= before

    async def test_service_is_closed_even_when_the_flush_raises(self, monkeypatch):
        class _Boom(_FlushService):
            async def flush_instant(self, bot: Any, *, since: datetime) -> dict[str, str]:
                raise RuntimeError("boom")

        svc = _Boom()
        scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=svc)

        with pytest.raises(RuntimeError, match="boom"):
            await scheduler_service.run_watchlist_instant_flush()

        assert repos_ctx.exited == 1
        assert svc.closed is True


# ----------------------------------------------------------------------------
# Watermark resolution
# ----------------------------------------------------------------------------


class TestWatermarkResolution:
    def test_pinned_setting_wins_over_the_in_memory_capture(self, monkeypatch):
        from tg_parser.config import settings
        from tg_parser.services import watchlist_service as ws

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", "2026-08-13T12:00:00Z")
        assert ws.set_instant_flush_watermark(datetime(2020, 1, 1, tzinfo=UTC)) == _WATERMARK
        assert ws.get_instant_flush_watermark() == _WATERMARK

    def test_unpinned_capture_is_now_and_excludes_all_history(self, monkeypatch):
        from tg_parser.config import settings
        from tg_parser.services import watchlist_service as ws

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", None)
        before = datetime.now(UTC)
        captured = ws.set_instant_flush_watermark()
        assert before <= captured <= datetime.now(UTC)

    def test_a_malformed_pin_is_ignored_rather_than_fatal(self, monkeypatch):
        """A bad timestamp must not take the bot process down, and must not
        widen the window either — the in-memory watermark below it is safe.
        """
        from tg_parser.config import settings
        from tg_parser.services import watchlist_service as ws

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", "not-a-timestamp")
        with capture_logs() as logs:
            captured = ws.set_instant_flush_watermark()
        assert captured.tzinfo is not None
        assert any(r.get("event") == "watchlist.instant_flush_cutoff_invalid" for r in logs)

    def test_a_naive_pin_is_read_as_utc(self, monkeypatch):
        from tg_parser.config import settings
        from tg_parser.services import watchlist_service as ws

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", "2026-08-13T12:00:00")
        assert ws.set_instant_flush_watermark() == _WATERMARK


# ----------------------------------------------------------------------------
# Backlog reconciliation (§3.3)
# ----------------------------------------------------------------------------


async def _seed_backlog() -> tuple[FakeInterestRepo, FakeMatchRepo, list[Any]]:
    """Two interests in one chat plus a third in another, all with history."""
    ir = FakeInterestRepo()
    mr = FakeMatchRepo()
    await ir.create(
        make_interest(
            interest_id="int-1", notify_mode=NotifyMode.INSTANT, chat_id=111, title="MiCA"
        )
    )
    await ir.create(
        make_interest(
            interest_id="int-2", notify_mode=NotifyMode.INSTANT, chat_id=111, title="Stablecoins"
        )
    )
    await ir.create(
        make_interest(
            interest_id="int-3", notify_mode=NotifyMode.INSTANT, chat_id=222, title="ETF flows"
        )
    )
    docs = [make_doc(source_ref=f"tg:crypto_news:post:{i}", text=f"MiCA {i}") for i in range(1, 6)]
    await mr.upsert_many(
        [
            make_match(
                interest_id="int-1",
                source_ref=docs[0].source_ref,
                created_at=datetime(2026, 6, 20, tzinfo=UTC),
            ),
            make_match(
                interest_id="int-1",
                source_ref=docs[1].source_ref,
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            make_match(
                interest_id="int-2",
                source_ref=docs[2].source_ref,
                created_at=datetime(2026, 7, 4, tzinfo=UTC),
            ),
            make_match(
                interest_id="int-3",
                source_ref=docs[3].source_ref,
                created_at=datetime(2026, 7, 9, tzinfo=UTC),
            ),
        ]
    )
    return ir, mr, docs


@pytest.mark.asyncio
class TestBacklogSummary:
    async def test_one_message_per_chat_with_a_per_interest_breakdown(self):
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        bot = FakeBot()
        summaries = await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=False)

        # Two chats → two messages, never one per interest and never one per match.
        assert [s.chat_id for s in summaries] == [111, 222]
        assert [m["chat_id"] for m in bot.sent] == [111, 222]

        chat_111 = summaries[0]
        assert chat_111.match_count == 3
        assert {(e.title, e.missed) for e in chat_111.entries} == {("MiCA", 2), ("Stablecoins", 1)}
        # A chat is told about its own interests only.
        assert "ETF flows" not in bot.sent[0]["text"]

    async def test_the_message_reports_counts_and_periods_not_posts(self):
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        bot = FakeBot()
        await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=False)

        text = bot.sent[0]["text"]
        assert "3 missed" in text
        # MarkdownV2 escapes the hyphens; assert the wire form actually sent.
        assert r"2026\-06\-20 — 2026\-08\-01" in text
        assert "get_watchlist_matches" in text
        # Not a replay: no post permalinks, no per-match preview lines.
        assert "t.me/" not in text
        for doc in docs:
            assert doc.source_ref not in text

    async def test_every_special_char_outside_code_spans_is_escaped(self):
        """A single unescaped MarkdownV2 char makes Telegram reject the send,
        which here would look like the backlog quietly refusing to close. The
        interest title is attacker-adjacent input (user-supplied free text), so
        it gets the hostile version.
        """
        from tg_parser.services.watchlist_service import BacklogEntry, compose_backlog_summary

        entries = [
            BacklogEntry(
                interest_id="int-1",
                title="MiCA (EU) — regulation_v2! [draft] #3 *bold* `code`",
                missed=4,
                oldest=datetime(2026, 6, 20, tzinfo=UTC),
                newest=datetime(2026, 8, 1, tzinfo=UTC),
            )
        ]

        _assert_markdown_v2_escaped(compose_backlog_summary(entries))

    async def test_a_long_breakdown_stays_under_the_telegram_limit(self):
        """One chat owns fourteen interests in production, so the breakdown is
        already long; overflowing 4096 chars would fail the send and leave the
        backlog stuck in a retry loop.
        """
        from tg_parser.services.watchlist_service import (
            MESSAGE_HARD_LIMIT,
            BacklogEntry,
            compose_backlog_summary,
        )

        entries = [
            BacklogEntry(
                interest_id=f"int-{i}",
                title=f"Interest {i} with a title long enough to matter " + "x" * 40,
                missed=i + 1,
                oldest=datetime(2026, 6, 20, tzinfo=UTC),
                newest=datetime(2026, 8, 1, tzinfo=UTC),
            )
            for i in range(80)
        ]

        text = compose_backlog_summary(entries)

        assert len(text) <= MESSAGE_HARD_LIMIT
        assert "more interests" in text
        # The total is still honest even though the breakdown is truncated, and
        # the pointer to the full history survives the truncation.
        assert f"{sum(e.missed for e in entries)} missed" in text
        assert "get_watchlist_matches" in text
        _assert_markdown_v2_escaped(text)

    async def test_second_run_sends_nothing(self):
        """Idempotency comes from the delivery watermark itself: a successful
        summary flips ``notified``, so the second run has an empty working set.
        """
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        bot = FakeBot()
        first = await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=False)
        second = await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=False)

        assert len(first) == 2
        assert second == []
        assert len(bot.sent) == 2
        assert all(m.notified is True for m in mr.store.values())

    async def test_dry_run_changes_nothing(self):
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        bot = FakeBot()
        summaries = await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=True)

        assert len(summaries) == 2
        assert all(s.sent is False for s in summaries)
        assert bot.sent == []
        assert all(m.notified is False for m in mr.store.values())

    async def test_dry_run_needs_no_bot_and_sending_refuses_without_one(self):
        """The preview is run from wherever the operator is; only the real send
        needs a token, and asking for one without a bot must fail loudly rather
        than report a summary nobody received.
        """
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        assert len(await svc.summarize_backlog(None, before=_WATERMARK, dry_run=True)) == 2
        with pytest.raises(ValueError, match="needs a live Bot"):
            await svc.summarize_backlog(None, before=_WATERMARK, dry_run=False)

    async def test_a_failed_chat_keeps_its_matches_for_the_next_run(self):
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        failing = FakeBot(raises=Exception("temporary network error"))
        summaries = await svc.summarize_backlog(failing, before=_WATERMARK, dry_run=False)

        assert all(s.sent is False for s in summaries)
        assert all(m.notified is False for m in mr.store.values())

        healthy = FakeBot()
        retried = await svc.summarize_backlog(healthy, before=_WATERMARK, dry_run=False)
        assert all(s.sent for s in retried)

    async def test_matches_after_the_watermark_belong_to_the_flush(self):
        """The two partitions must not overlap: whatever the flush will deliver
        must not also be summarised as missed.
        """
        ir, mr, docs = await _seed_backlog()
        fresh = make_doc(source_ref="tg:crypto_news:post:99", text="MiCA today")
        await mr.upsert_many(
            [
                make_match(
                    interest_id="int-1",
                    source_ref=fresh.source_ref,
                    created_at=_WATERMARK + timedelta(minutes=1),
                )
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[*docs, fresh])

        bot = FakeBot()
        summaries = await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=False)

        assert sum(s.match_count for s in summaries) == 4
        by_ref = {m.source_ref: m for m in mr.store.values()}
        assert by_ref[fresh.source_ref].notified is False

        # ...and the flush picks up exactly that one.
        assert await svc.flush_instant(FakeBot(), since=_WATERMARK) == {"int-1": "sent"}

    async def test_batch_interests_are_not_swept(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-batch", notify_mode=NotifyMode.BATCH))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        await mr.upsert_many(
            [
                make_match(
                    interest_id="int-batch",
                    source_ref=doc.source_ref,
                    created_at=datetime(2026, 7, 1, tzinfo=UTC),
                )
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        bot = FakeBot()
        assert await svc.summarize_backlog(bot, before=_WATERMARK, dry_run=False) == []
        assert bot.sent == []
        # Still pending for the daily batch cron, which owns them.
        assert all(m.notified is False for m in mr.store.values())


# ----------------------------------------------------------------------------
# Undelivered gauge (§3.4)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCountUndelivered:
    async def test_counts_pending_instant_matches_past_the_window(self):
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        assert await svc.count_undelivered(older_than=_WATERMARK) == 4

    async def test_delivered_matches_do_not_count(self):
        ir, mr, docs = await _seed_backlog()
        svc = make_service(interest_repo=ir, match_repo=mr, docs=docs)

        await svc.summarize_backlog(FakeBot(), before=_WATERMARK, dry_run=False)

        assert await svc.count_undelivered(older_than=_WATERMARK) == 0

    async def test_matches_inside_the_delivery_window_do_not_count(self):
        ir = FakeInterestRepo()
        mr = FakeMatchRepo()
        await ir.create(make_interest(interest_id="int-1", notify_mode=NotifyMode.INSTANT))
        doc = make_doc(source_ref="tg:crypto_news:post:1", text="MiCA")
        await mr.upsert_many(
            [
                make_match(
                    interest_id="int-1",
                    source_ref=doc.source_ref,
                    created_at=datetime.now(UTC),
                )
            ]
        )
        svc = make_service(interest_repo=ir, match_repo=mr, docs=[doc])

        stale_before = datetime.now(UTC) - timedelta(seconds=300)
        assert await svc.count_undelivered(older_than=stale_before) == 0
