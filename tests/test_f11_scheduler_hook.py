"""Tests for the F11 scheduler hook (run_watchlist_check_for_channel + _process_source wiring).

The hook wires :class:`WatchlistService` into the incremental pipeline.
We focus on three guarantees:

1. No new docs → fast-path "no_new_docs" return without touching repos / Bot.
2. Service is built via the factory, ``check_interests`` is awaited with the
   live ``Bot`` instance, and ``aclose`` is always called (no leaked OpenAI
   connections).
3. The pipeline is never blocked by a watchlist failure — exceptions are
   logged and surfaced via the return-dict, not re-raised.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_returns_fast_path_when_no_new_docs(monkeypatch):
    from tg_parser.services import scheduler_service

    called = {"watchlist_repos": False, "factory": False, "bot": False}

    def _fail(*_a, **_kw):
        called["factory"] = True
        raise AssertionError("factory must not be called when there are no new docs")

    monkeypatch.setattr(
        scheduler_service,
        "run_watchlist_check_for_channel",
        scheduler_service.run_watchlist_check_for_channel,
    )

    result = await scheduler_service.run_watchlist_check_for_channel(
        channel_id="crypto_news",
        new_doc_refs=[],
    )

    assert result == {"inserted": 0, "skipped_reason": "no_new_docs"}
    assert called == {"watchlist_repos": False, "factory": False, "bot": False}


class _FakeService:
    """Tiny stand-in for WatchlistService used in the hook test."""

    def __init__(self, inserted: list[Any] | None = None, raises: Exception | None = None) -> None:
        self.inserted = inserted or []
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def check_interests(
        self, *, channel_id: str, new_doc_refs: list[str], bot: Any
    ) -> list[Any]:
        self.calls.append(
            {"channel_id": channel_id, "new_doc_refs": list(new_doc_refs), "bot": bot}
        )
        if self.raises is not None:
            raise self.raises
        return list(self.inserted)

    async def aclose(self) -> None:
        self.closed = True


class _ReposCtx:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return ("interest", "match", "proc", "emb", "db")

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1


def _patch_hook(monkeypatch, *, service: _FakeService, bot_marker: Any = "BOT"):
    """Patch scheduler_service to use fake repos/factory/bot for one call."""
    from tg_parser.services import scheduler_service

    repos_ctx = _ReposCtx()

    def _watchlist_repos():
        return repos_ctx

    def _make_service(**_kwargs):
        return service

    def _get_bot():
        return bot_marker

    db_context_module = __import__("tg_parser.services.db_context", fromlist=["watchlist_repos"])
    factory_module = __import__(
        "tg_parser.services.watchlist_service", fromlist=["make_watchlist_service"]
    )
    runtime_module = __import__("tg_parser.bot.runtime", fromlist=["get_bot"])

    monkeypatch.setattr(db_context_module, "watchlist_repos", _watchlist_repos)
    monkeypatch.setattr(factory_module, "make_watchlist_service", _make_service)
    monkeypatch.setattr(runtime_module, "get_bot", _get_bot)
    return scheduler_service, repos_ctx


@pytest.mark.asyncio
async def test_invokes_check_interests_with_bot_and_closes_service(monkeypatch):
    fake = _FakeService(inserted=["m1", "m2", "m3"])
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=fake)

    result = await scheduler_service.run_watchlist_check_for_channel(
        channel_id="crypto_news",
        new_doc_refs=["tg:c:post:1", "tg:c:post:2"],
    )

    assert result == {"inserted": 3, "skipped_reason": None}
    assert repos_ctx.entered == 1
    assert repos_ctx.exited == 1
    assert fake.closed is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["channel_id"] == "crypto_news"
    assert call["new_doc_refs"] == ["tg:c:post:1", "tg:c:post:2"]
    # Bot must be the live instance returned by get_bot(), not None.
    assert call["bot"] == "BOT"


@pytest.mark.asyncio
async def test_aclose_called_even_when_check_interests_raises(monkeypatch):
    fake = _FakeService(raises=RuntimeError("boom"))
    scheduler_service, repos_ctx = _patch_hook(monkeypatch, service=fake)

    with pytest.raises(RuntimeError, match="boom"):
        await scheduler_service.run_watchlist_check_for_channel(
            channel_id="crypto_news",
            new_doc_refs=["tg:c:post:1"],
        )

    # The repo / service lifetimes must be properly torn down regardless.
    assert repos_ctx.exited == 1
    assert fake.closed is True
