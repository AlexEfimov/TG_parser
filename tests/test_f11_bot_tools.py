"""F11 bot-tool executors — pure-mock tests (no Postgres / no aiogram bot).

Exercises the four executors registered in ``_TOOL_EXECUTORS``:

- ``_exec_subscribe_watchlist``   (``chat_id`` injected from message context)
- ``_exec_list_watchlists``       (admin sees all, scoped sees own)
- ``_exec_unsubscribe_watchlist`` (owner-only for non-admins)
- ``_exec_get_watchlist_matches`` (owner-only for non-admins)

The executors share the same DB-context / service-factory entry points as
the MCP tools, so we patch the same surfaces.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeBot,
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
    _make_interest,
    _make_match,
)

from tg_parser.auth.models import CurrentUser  # noqa: E402
from tg_parser.bot.tools import (  # noqa: E402
    _exec_get_watchlist_matches,
    _exec_list_watchlists,
    _exec_subscribe_watchlist,
    _exec_unsubscribe_watchlist,
)
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin(user_id: str = "admin-1") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _scoped(user_id: str, *, allowed: set[str]) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="user",
        role="user",
        allowed_channel_ids=list(allowed),
        max_channels=10,
    )


@asynccontextmanager
async def _fake_repos(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


def _patch_bot(svc: WatchlistService, ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    """Patch the surfaces used by the bot-tool executors."""

    def _make(**_kwargs):
        return svc

    return [
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _fake_repos(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            _make,
        ),
    ]


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


def _make_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


# ---------------------------------------------------------------------------
# subscribe_watchlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubscribeWatchlistExec:
    async def test_uses_bot_chat_id_and_persists(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
                current_user=_admin("user-1"),
                bot=bot,
                chat_id=987,
            )
        finally:
            _exit_all(patches)

        assert "error" not in result
        assert result["title"] == "MiCA"
        assert result["chat_id"] == 987
        # Confirmation message was attempted
        assert len(bot.sent) == 1
        # Persisted to fake repo
        assert len(ir.store) == 1
        stored = next(iter(ir.store.values()))
        assert stored.user_id == "user-1"
        assert stored.chat_id == 987
        assert stored.channel_ids == ["crypto_news"]

    async def test_rejects_when_chat_id_missing(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {"title": "MiCA", "channel_ids": ["@x"]},
                current_user=_admin(),
                bot=None,
                chat_id=None,
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "chat_id" in result["error"].lower()

    async def test_rejects_invalid_threshold(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {"title": "MiCA", "channel_ids": ["@x"], "threshold": -0.1},
                current_user=_admin(),
                bot=None,
                chat_id=10,
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "threshold" in result["error"].lower()

    async def test_blocks_unauthorized_channel_for_scoped_user(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        user = _scoped("user-2", allowed={"owned"})
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {"title": "MiCA", "channel_ids": ["@forbidden"]},
                current_user=user,
                bot=None,
                chat_id=10,
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert result.get("channel_id") == "forbidden"
        assert len(ir.store) == 0


# ---------------------------------------------------------------------------
# list_watchlists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListWatchlistsExec:
    async def test_admin_sees_all(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="a"))
        await ir.create(_make_interest(interest_id="b").model_copy(update={"user_id": "user-bob"}))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_list_watchlists({}, current_user=_admin())
        finally:
            _exit_all(patches)
        assert result["count"] == 2
        ids = {item["interest_id"] for item in result["interests"]}
        assert ids == {"a", "b"}

    async def test_non_admin_sees_only_own(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="a"))
        await ir.create(_make_interest(interest_id="b").model_copy(update={"user_id": "user-bob"}))
        svc = _make_service(ir, _FakeMatchRepo())
        bob = _scoped("user-bob", allowed={"crypto_news"})
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_list_watchlists({}, current_user=bob)
        finally:
            _exit_all(patches)
        assert result["count"] == 1
        assert result["interests"][0]["interest_id"] == "b"


# ---------------------------------------------------------------------------
# unsubscribe_watchlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUnsubscribeWatchlistExec:
    async def test_owner_can_delete(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": "i-1"},
                current_user=_scoped("user-1", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert result["deleted"] is True
        stored = await ir.get("i-1")
        assert stored is not None
        assert stored.is_active is False

    async def test_non_owner_blocked(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": "i-1"},
                current_user=_scoped("intruder", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert result["deleted"] is False
        assert "error" in result

    async def test_admin_can_delete_others(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": "i-1"},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result["deleted"] is True

    async def test_missing_id_returns_error(self):
        ir = _FakeInterestRepo()
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": ""},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_watchlist_matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetWatchlistMatchesExec:
    async def test_owner_receives_matches(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        await mr.upsert_many(
            [
                _make_match(
                    interest_id="i-1",
                    source_ref="tg:c:post:1",
                    match_id=10,
                    channel_id="c",
                ),
                _make_match(
                    interest_id="i-1",
                    source_ref="tg:c:post:2",
                    match_id=11,
                    channel_id="c",
                ),
            ]
        )
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_get_watchlist_matches(
                {"interest_id": "i-1"},
                current_user=_scoped("user-1", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert result["count"] == 2
        refs = {m["source_ref"] for m in result["matches"]}
        assert refs == {"tg:c:post:1", "tg:c:post:2"}

    async def test_non_owner_gets_permission_error(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        await mr.upsert_many(
            [
                _make_match(
                    interest_id="i-1",
                    source_ref="tg:c:post:1",
                    match_id=10,
                    channel_id="c",
                )
            ]
        )
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_get_watchlist_matches(
                {"interest_id": "i-1"},
                current_user=_scoped("intruder", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "permission" in result["error"].lower()

    async def test_invalid_since_iso_returns_error(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id="i-1"))
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_get_watchlist_matches(
                {"interest_id": "i-1", "since_iso": "not-a-date"},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "since_iso" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tool registry: declarations + executors hooked up + chat_id flag
# ---------------------------------------------------------------------------


def test_watchlist_tools_registered_in_executor_map():
    from tg_parser.bot.tools import _TOOL_EXECUTORS

    for name in (
        "subscribe_watchlist",
        "list_watchlists",
        "unsubscribe_watchlist",
        "get_watchlist_matches",
    ):
        assert name in _TOOL_EXECUTORS, f"missing executor for {name}"


def test_subscribe_watchlist_marked_as_needing_chat_context():
    from tg_parser.bot.tools import _TOOLS_NEEDING_BOT_CONTEXT

    assert "subscribe_watchlist" in _TOOLS_NEEDING_BOT_CONTEXT
