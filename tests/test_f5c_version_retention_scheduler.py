"""F5-C #15 item #1 — retention purge scheduler hook tests (mocked, no PG).

Covers ``scheduler_service.purge_stale_topic_card_versions``:

1. skip-path — ``RESUMMARIZE_VERSION_RETENTION_DAYS=0`` (default kill-switch)
   returns ``{"deleted": 0, "skipped": True}`` and never opens a DB session
   nor touches the metrics (bit-for-bit MVP "keep everything").
2. on-path — ``retention_days > 0`` calls ``purge_stale`` with the resolved
   ``keep_last_n`` + a cutoff ``retention_days`` in the past, refreshes the
   gauge with the post-purge ``count()`` and bumps the purged counter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


class _FakeVersionRepo:
    def __init__(self, *, deleted: int, count_after: int) -> None:
        self._deleted = deleted
        self._count_after = count_after
        self.purge_calls: list[dict[str, Any]] = []
        self.count_calls = 0

    async def purge_stale(self, *, keep_last_n: int, older_than: datetime) -> int:
        self.purge_calls.append({"keep_last_n": keep_last_n, "older_than": older_than})
        return self._deleted

    async def count(self) -> int:
        self.count_calls += 1
        return self._count_after


class _ReposCtx:
    def __init__(self, version_repo: _FakeVersionRepo) -> None:
        self.version_repo = version_repo
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return ("card_repo", "bundle_repo", self.version_repo, "proc_repo", "db")

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1


def _patch(monkeypatch, *, ctx: _ReposCtx | None):
    """Patch db_context + metrics; return (scheduler_module, captured)."""
    from tg_parser.services import scheduler_service

    captured: dict[str, Any] = {"gauge": None, "purged": None}

    db_context_module = __import__(
        "tg_parser.services.db_context", fromlist=["resummarization_repos"]
    )
    metrics_module = __import__(
        "tg_parser.api.metrics",
        fromlist=["set_topic_card_versions_rows", "record_topic_card_versions_purged"],
    )

    def _resummarization_repos():
        assert ctx is not None, "DB session must NOT be opened on the skip-path"
        return ctx

    monkeypatch.setattr(db_context_module, "resummarization_repos", _resummarization_repos)
    monkeypatch.setattr(
        metrics_module,
        "set_topic_card_versions_rows",
        lambda n: captured.__setitem__("gauge", n),
    )
    monkeypatch.setattr(
        metrics_module,
        "record_topic_card_versions_purged",
        lambda n: captured.__setitem__("purged", n),
    )
    return scheduler_service, captured


@pytest.mark.asyncio
async def test_skip_path_when_retention_disabled(monkeypatch):
    monkeypatch.setattr("tg_parser.config.settings.resummarize_version_retention_days", 0)
    scheduler_service, captured = _patch(monkeypatch, ctx=None)

    result = await scheduler_service.purge_stale_topic_card_versions()

    assert result == {"deleted": 0, "skipped": True}
    # No DB session, no metrics emitted on the skip-path.
    assert captured["gauge"] is None
    assert captured["purged"] is None


@pytest.mark.asyncio
async def test_on_path_purges_and_emits_metrics(monkeypatch):
    monkeypatch.setattr("tg_parser.config.settings.resummarize_version_retention_days", 180)
    monkeypatch.setattr("tg_parser.config.settings.resummarize_version_keep_last_n", 50)

    repo = _FakeVersionRepo(deleted=7, count_after=93)
    ctx = _ReposCtx(repo)
    scheduler_service, captured = _patch(monkeypatch, ctx=ctx)

    before = datetime.now(UTC)
    result = await scheduler_service.purge_stale_topic_card_versions()
    after = datetime.now(UTC)

    assert result == {"deleted": 7, "table_size": 93}
    assert ctx.entered == 1 and ctx.exited == 1
    assert repo.count_calls == 1

    # purge_stale called once with the resolved knobs + a cutoff ~180d ago.
    assert len(repo.purge_calls) == 1
    call = repo.purge_calls[0]
    assert call["keep_last_n"] == 50
    expected_lo = before - timedelta(days=180)
    expected_hi = after - timedelta(days=180)
    assert expected_lo <= call["older_than"] <= expected_hi

    # Gauge = post-purge count; counter bumped by deleted.
    assert captured["gauge"] == 93
    assert captured["purged"] == 7
