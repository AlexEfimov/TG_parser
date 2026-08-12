"""
BUG-093 — `add_channel` on an EXISTING foreign channel must be rejected.

An existing channel id turns `add_channel` into an update of that source row
(`status` / `include_comments` / `batch_size` reach `upsert_source`), while
`owner_id` is preserved. Before the fix a non-owner therefore could not gain
read access but *could* silently reconfigure — and, in the bot, preview — the
operator's channels. That is exactly the exposure created by handing MCP tokens
to test users on an instance that already curates channels.

Covers the shared guard plus both surfaces that call `upsert_source` behind
auth (MCP tool, bot tool). CLI `add-source` is operator-local and unauthenticated.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import PermissionDenied, assert_source_mutable

OWNER_ID = "user-1"
FOREIGN_OWNER_ID = "user-2"


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


def _user(channels: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id=OWNER_ID,
        name="alice",
        role="user",
        allowed_channel_ids=channels if channels is not None else ["ch1"],
        max_channels=5,
    )


def _source(owner_id: str | None, channel_id: str = "curated_ch") -> MagicMock:
    source = MagicMock()
    source.source_id = channel_id
    source.channel_id = channel_id
    source.owner_id = owner_id
    source.status = "active"
    source.include_comments = False
    source.batch_size = 100
    source.created_at = None
    return source


@asynccontextmanager
async def _fake_ingestion_ctx(state_repo):
    yield (state_repo, MagicMock())


def _state_repo(existing) -> AsyncMock:
    repo = AsyncMock()
    repo.get_source.return_value = existing
    repo.get_source_by_username.return_value = None  # BUG-010 (Session I)
    repo.list_sources.return_value = []
    repo.upsert_source = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# assert_source_mutable
# ---------------------------------------------------------------------------


class TestAssertSourceMutable:
    def test_owner_passes(self):
        assert_source_mutable(_user(), _source(OWNER_ID))

    def test_admin_passes_on_foreign_source(self):
        assert_source_mutable(_admin(), _source(FOREIGN_OWNER_ID))

    def test_foreign_owner_raises_with_channel_id_in_message(self):
        with pytest.raises(PermissionDenied, match="No access to channel curated_ch"):
            assert_source_mutable(_user(), _source(FOREIGN_OWNER_ID))

    def test_unowned_legacy_row_is_admin_only(self):
        with pytest.raises(PermissionDenied, match="No access to channel"):
            assert_source_mutable(_user(), _source(None))
        assert_source_mutable(_admin(), _source(None))

    def test_ownership_is_read_from_row_not_from_cached_allowed_list(self):
        """A channel just added by the caller may be missing from the 60s-cached
        `allowed_channel_ids`; the source row is the fresh source of truth."""
        stale_user = _user(channels=[])
        assert_source_mutable(stale_user, _source(OWNER_ID))


# ---------------------------------------------------------------------------
# MCP add_channel
# ---------------------------------------------------------------------------


class TestMcpAddChannelForeignSource:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_foreign_existing_source_is_rejected_without_upsert(self, mock_resolve):
        mock_resolve.return_value = _user()
        state_repo = _state_repo(_source(FOREIGN_OWNER_ID))

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel(
                "curated_ch", include_comments=True, batch_size=500, ctx=None
            )

        assert result.created is False
        assert result.status == "rejected"
        assert "No access to channel curated_ch" in result.message
        state_repo.upsert_source.assert_not_awaited()

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_own_existing_source_still_updatable(self, mock_resolve):
        mock_resolve.return_value = _user()
        state_repo = _state_repo(_source(OWNER_ID, channel_id="ch1"))

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("ch1", include_comments=True, ctx=None)

        assert result.created is False
        assert result.status != "rejected"
        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.include_comments is True
        assert upserted.owner_id == OWNER_ID

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_admin_can_still_update_any_source(self, mock_resolve):
        mock_resolve.return_value = _admin()
        state_repo = _state_repo(_source(FOREIGN_OWNER_ID))

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.mcp_server import add_channel

            result = await add_channel("curated_ch", ctx=None)

        assert result.status != "rejected"
        upserted = state_repo.upsert_source.call_args[0][0]
        assert upserted.owner_id == FOREIGN_OWNER_ID, "admin update must not steal ownership"


# ---------------------------------------------------------------------------
# Bot _exec_add_channel (parity)
# ---------------------------------------------------------------------------


class TestBotAddChannelForeignSource:
    async def test_confirm_on_foreign_source_is_rejected_without_upsert(self):
        state_repo = _state_repo(_source(FOREIGN_OWNER_ID))

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "curated_ch", "confirm": True, "include_comments": True},
                current_user=_user(),
            )

        assert result["created"] is False
        assert "No access to channel curated_ch" in result["message"]
        state_repo.upsert_source.assert_not_awaited()

    async def test_preview_on_foreign_source_leaks_no_status(self):
        state_repo = _state_repo(_source(FOREIGN_OWNER_ID))

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "curated_ch"},
                current_user=_user(),
            )

        assert result.get("preview") is not True
        assert "current_status" not in result
        assert "No access to channel curated_ch" in result["message"]

    async def test_owner_preview_still_works(self):
        # Bot-side ids additionally pass `validate_channel_username` (BUG-034),
        # so the fixture uses a Telegram-valid username.
        state_repo = _state_repo(_source(OWNER_ID, channel_id="own_channel"))

        with patch(
            "tg_parser.services.db_context.ingestion_state_repo",
            lambda: _fake_ingestion_ctx(state_repo),
        ):
            from tg_parser.bot.tools import _exec_add_channel

            result = await _exec_add_channel(
                {"channel_id": "own_channel"}, current_user=_user(["own_channel"])
            )

        assert result["preview"] is True
        assert result["action"] == "update"
