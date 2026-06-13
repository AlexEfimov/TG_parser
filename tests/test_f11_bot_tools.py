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

# Canonical test UUID — valid UUID format so BUG-025 UUID pre-validation passes.
# All executor-arg ``interest_id`` references must use this (or another valid UUID).
_INTEREST_UUID: str = "99999999-1111-4000-8888-000000000001"

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
                    # BUG-031: confirm=True required to reach persistence;
                    # bot framework adds it on the FSM confirm-turn.
                    "confirm": True,
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

    async def test_manual_interest_update_surfaces_threshold_calibration(self):
        # BUG-054 / ADR 0015: a text-field update of a manual interest keeps the
        # pinned threshold but returns + surfaces a calibration advisory.
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            first = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.42,
                    "confirm": True,
                },
                current_user=_admin("user-1"),
                bot=bot,
                chat_id=987,
            )
            updated = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica", "regulation"],
                    "confirm": True,
                },
                current_user=_admin("user-1"),
                bot=bot,
                chat_id=987,
            )
        finally:
            _exit_all(patches)

        assert "error" not in first
        assert first["created"] is True
        assert updated["created"] is False
        assert updated["threshold_calibration"] is not None
        assert updated["threshold"] == pytest.approx(0.42)
        # The confirmation message surfaces the advisory line.
        assert any("Рекомендуемый порог" in m["text"] for m in bot.sent)

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
            # BUG-034: bumped channel name from "@x" (1 char, fails the new
            # Telegram username regex) to a 5+ char synthetic so the
            # executor reaches the threshold validation branch under test.
            result = await _exec_subscribe_watchlist(
                {"title": "MiCA", "channel_ids": ["@validch"], "threshold": -0.1},
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
    async def test_owner_preview_does_not_delete(self):
        """BUG-046 (G1) two-phase gate: a ``confirm``-less call returns a
        preview naming the interest + its ID and does NOT soft-delete."""
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": _INTEREST_UUID},
                current_user=_scoped("user-1", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert result["preview"] is True
        assert result["user_facing_message"] is True
        assert _INTEREST_UUID in result["message"]
        assert "[да/нет]" in result["message"]
        # Nothing deleted on the preview turn.
        stored = await ir.get(_INTEREST_UUID)
        assert stored is not None
        assert stored.is_active is True

    async def test_owner_can_delete(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            # BUG-046 (G1): the actual delete now requires confirm=True
            # (the framework replays the previewed call deterministically).
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": _INTEREST_UUID, "confirm": True},
                current_user=_scoped("user-1", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert result["deleted"] is True
        stored = await ir.get(_INTEREST_UUID)
        assert stored is not None
        assert stored.is_active is False

    async def test_non_owner_blocked(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": _INTEREST_UUID},
                current_user=_scoped("intruder", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert result["deleted"] is False
        assert "error" in result

    async def test_admin_can_delete_others(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": _INTEREST_UUID, "confirm": True},
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
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        await mr.upsert_many(
            [
                _make_match(
                    interest_id=_INTEREST_UUID,
                    source_ref="tg:c:post:1",
                    match_id=10,
                    channel_id="c",
                ),
                _make_match(
                    interest_id=_INTEREST_UUID,
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
                {"interest_id": _INTEREST_UUID},
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
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        await mr.upsert_many(
            [
                _make_match(
                    interest_id=_INTEREST_UUID,
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
                {"interest_id": _INTEREST_UUID},
                current_user=_scoped("intruder", allowed={"crypto_news"}),
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "permission" in result["error"].lower()

    async def test_invalid_since_iso_returns_error(self):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID))
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_get_watchlist_matches(
                {"interest_id": _INTEREST_UUID, "since_iso": "not-a-date"},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "since_iso" in result["error"].lower()


# ---------------------------------------------------------------------------
# BUG-025 — UUID pre-validation for executor ID arguments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBug025UUIDValidation:
    """BUG-025: executors that accept interest_id / subscription_id must reject
    non-UUID strings with error_class=InvalidUUID BEFORE opening a DB
    connection, so the LLM sees a friendly error instead of a raw asyncpg
    traceback.
    """

    _INVALID_FORMS = [
        "my-watchlist",
        "_smoke_post91_20260522T174541Z",
        "S3 smoke",
        "wl_bot_watch_smoke",
        "123",
        "not-a-uuid-at-all",
        "604632d4-23e9-4e50-a992-GGGG",  # bad hex
    ]

    @pytest.mark.parametrize("bad_id", _INVALID_FORMS)
    async def test_unsubscribe_watchlist_rejects_non_uuid(self, bad_id: str):
        ir = _FakeInterestRepo()
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": bad_id},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == "InvalidUUID", result
        assert "interest_id" in result["error"]
        assert "UUID" in result["error"]

    @pytest.mark.parametrize("bad_id", _INVALID_FORMS)
    async def test_get_watchlist_matches_rejects_non_uuid(self, bad_id: str):
        ir = _FakeInterestRepo()
        mr = _FakeMatchRepo()
        svc = _make_service(ir, mr)
        patches = _patch_bot(svc, ir, mr)
        _enter_all(patches)
        try:
            result = await _exec_get_watchlist_matches(
                {"interest_id": bad_id},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == "InvalidUUID", result
        assert "UUID" in result["error"]


# ---------------------------------------------------------------------------
# BUG-027 — already-inactive watchlist returns clean already_inactive=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBug027AlreadyInactive:
    """BUG-027: when the target watchlist exists but is already is_active=False,
    the executor must return already_inactive=True instead of bubbling up the
    ambiguous «delete failed (already inactive?)» error string.
    """

    async def test_unsubscribe_already_inactive_returns_typed_result(self):
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID, is_active=False))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": _INTEREST_UUID},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        assert result.get("already_inactive") is True, result
        assert result.get("deleted") is False
        assert "error" not in result or result.get("error") is None or result.get("already_inactive")
        assert "message" in result
        # Must NOT contain the legacy ambiguous wording.
        assert "already inactive?" not in result.get("message", "")

    async def test_unsubscribe_already_inactive_no_preview_emitted(self):
        """already_inactive guard fires BEFORE the confirm-preview gate — the
        user should NOT see «будет удалён [да/нет]» for an already-inactive item."""
        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID, is_active=False))
        svc = _make_service(ir, _FakeMatchRepo())
        patches = _patch_bot(svc, ir, _FakeMatchRepo())
        _enter_all(patches)
        try:
            result = await _exec_unsubscribe_watchlist(
                {"interest_id": _INTEREST_UUID},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)
        # Must NOT be a preview — the item is already gone.
        assert result.get("preview") is not True

    async def test_service_delete_already_inactive_returns_sentinel(self):
        """Service layer BUG-027: delete_interest_for_user must return the
        typed 'already_inactive' sentinel, not 'delete failed (already inactive?)'."""
        from tg_parser.services.watchlist_service import WatchlistService

        ir = _FakeInterestRepo()
        await ir.create(_make_interest(interest_id=_INTEREST_UUID, is_active=False))
        svc = WatchlistService(
            interest_repo=ir,
            match_repo=_FakeMatchRepo(),
            processed_doc_repo=_FakeProcessedDocRepo([]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )
        deleted, err = await svc.delete_interest_for_user(
            _INTEREST_UUID,
            requesting_user_id="user-1",
            is_admin=True,
        )
        assert deleted is False
        assert err == "already_inactive", f"got {err!r}"


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
