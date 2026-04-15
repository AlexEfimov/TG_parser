"""
Tests for F4 Multi-Tenancy Phase 3: Channel Ownership Enforcement.

Unit tests (mock DB) for ownership helpers and tool-level enforcement.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import (
    PermissionDenied,
    assert_admin,
    assert_channel_access,
    check_channel_limit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin",
        allowed_channel_ids=None, max_channels=100,
    )


def _user(channels: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id="user-1", name="alice", role="user",
        allowed_channel_ids=channels if channels is not None else ["ch1", "ch2"],
        max_channels=5,
    )


# ---------------------------------------------------------------------------
# assert_channel_access
# ---------------------------------------------------------------------------

class TestAssertChannelAccess:
    async def test_admin_always_passes(self):
        await assert_channel_access(_admin(), "any_channel")

    async def test_user_with_channel_passes(self):
        await assert_channel_access(_user(["ch1", "ch2"]), "ch1")

    async def test_user_without_channel_raises(self):
        with pytest.raises(PermissionDenied, match="No access to channel ch3"):
            await assert_channel_access(_user(["ch1"]), "ch3")

    async def test_user_empty_channels_raises(self):
        with pytest.raises(PermissionDenied):
            await assert_channel_access(_user([]), "ch1")


# ---------------------------------------------------------------------------
# assert_admin
# ---------------------------------------------------------------------------

class TestAssertAdmin:
    def test_admin_passes(self):
        assert_admin(_admin())

    def test_user_raises(self):
        with pytest.raises(PermissionDenied, match="Admin access required"):
            assert_admin(_user())


# ---------------------------------------------------------------------------
# check_channel_limit
# ---------------------------------------------------------------------------

class TestCheckChannelLimit:
    def test_under_limit_passes(self):
        check_channel_limit(_user(), current_count=3)

    def test_at_limit_raises(self):
        with pytest.raises(PermissionDenied, match="Channel limit reached"):
            check_channel_limit(_user(), current_count=5)

    def test_over_limit_raises(self):
        with pytest.raises(PermissionDenied, match="Channel limit reached"):
            check_channel_limit(_user(), current_count=10)

    def test_admin_unlimited(self):
        check_channel_limit(_admin(), current_count=999)


# ---------------------------------------------------------------------------
# MCP add_channel sets owner_id
# ---------------------------------------------------------------------------

class TestMCPAddChannelOwnership:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_channel_sets_owner_id(self, mock_resolve):
        user = _user(["ch1"])
        mock_resolve.return_value = user

        mock_state_repo = AsyncMock()
        mock_state_repo.get_source.return_value = None
        mock_state_repo.list_sources.return_value = []
        mock_state_repo.upsert_source = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_ingestion():
            yield (mock_state_repo, MagicMock())

        with patch("tg_parser.services.db_context.ingestion_state_repo", fake_ingestion):
            from tg_parser.mcp_server import add_channel
            result = await add_channel("test_ch", ctx=None)

        assert result.created is True
        call_args = mock_state_repo.upsert_source.call_args[0][0]
        assert call_args.owner_id == user.id

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_channel_enforces_per_user_limit(self, mock_resolve):
        user = CurrentUser(
            id="user-1", name="alice", role="user",
            allowed_channel_ids=["ch1"], max_channels=1,
        )
        mock_resolve.return_value = user

        mock_state_repo = AsyncMock()
        mock_state_repo.get_source.return_value = None
        mock_state_repo.list_sources.return_value = [MagicMock()]

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_ingestion():
            yield (mock_state_repo, MagicMock())

        with patch("tg_parser.services.db_context.ingestion_state_repo", fake_ingestion):
            from tg_parser.mcp_server import add_channel
            result = await add_channel("new_ch", ctx=None)

        assert result.created is False
        assert "limit" in result.message.lower()


# ---------------------------------------------------------------------------
# MCP remove_channel ownership enforcement
# ---------------------------------------------------------------------------

class TestMCPRemoveChannelOwnership:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_remove_channel_denied_for_non_owner(self, mock_resolve):
        user = _user(["ch1"])
        mock_resolve.return_value = user

        from tg_parser.mcp_server import remove_channel
        result = await remove_channel("ch3", confirm=True, ctx=None)
        assert result.removed is False
        assert "No access" in result.message


# ---------------------------------------------------------------------------
# MCP pause/resume ownership enforcement
# ---------------------------------------------------------------------------

class TestMCPPauseResumeOwnership:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_pause_denied_for_non_owner(self, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])

        from tg_parser.mcp_server import pause_channel
        result = await pause_channel("ch3", ctx=None)
        assert result.changed is False
        assert "No access" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_resume_denied_for_non_owner(self, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])

        from tg_parser.mcp_server import resume_channel
        result = await resume_channel("ch3", ctx=None)
        assert result.changed is False
        assert "No access" in result.message


# ---------------------------------------------------------------------------
# MCP list_channels scoping
# ---------------------------------------------------------------------------

class TestMCPListChannelsScoped:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    @patch("tg_parser.services.channel_service.get_all_channel_stats")
    async def test_admin_sees_all(self, mock_stats, mock_resolve):
        mock_resolve.return_value = _admin()
        mock_stats.return_value = [
            {"channel_id": "ch1", "status": "active", "raw_messages": 10,
             "processed_documents": 5, "topics_count": 2, "coverage_percent": 50.0},
            {"channel_id": "ch2", "status": "active", "raw_messages": 20,
             "processed_documents": 15, "topics_count": 5, "coverage_percent": 75.0},
        ]
        from tg_parser.mcp_server import list_channels
        result = await list_channels(ctx=None)
        assert len(result) == 2
        mock_stats.assert_called_once_with(allowed_channel_ids=None)

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    @patch("tg_parser.services.channel_service.get_all_channel_stats")
    async def test_user_sees_only_owned(self, mock_stats, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])
        mock_stats.return_value = [
            {"channel_id": "ch1", "status": "active", "raw_messages": 10,
             "processed_documents": 5, "topics_count": 2, "coverage_percent": 50.0},
        ]
        from tg_parser.mcp_server import list_channels
        result = await list_channels(ctx=None)
        assert len(result) == 1
        mock_stats.assert_called_once_with(allowed_channel_ids=["ch1"])


# ---------------------------------------------------------------------------
# MCP admin-only tools
# ---------------------------------------------------------------------------

class TestMCPAdminOnlyTools:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_set_llm_config_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import set_llm_config
        result = await set_llm_config(scope="global", provider="openai", ctx=None)
        assert result.success is False
        assert "Admin" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_reset_llm_config_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import reset_llm_config
        result = await reset_llm_config(ctx=None)
        assert result.success is False
        assert "Admin" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_reload_prompts_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import reload_prompts
        result = await reload_prompts(ctx=None)
        assert result.get("success") is False
        assert "Admin" in result.get("error", "")


# ---------------------------------------------------------------------------
# Bot _exec_add_channel with current_user sets ownership
# ---------------------------------------------------------------------------

class TestBotAddChannelOwnership:
    async def test_exec_add_channel_sets_owner_id(self):
        user = _user(["ch1"])

        mock_state_repo = AsyncMock()
        mock_state_repo.get_source.return_value = None
        mock_state_repo.list_sources.return_value = []
        mock_state_repo.upsert_source = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_ingestion():
            yield (mock_state_repo, MagicMock())

        with patch("tg_parser.services.db_context.ingestion_state_repo", fake_ingestion):
            from tg_parser.bot.tools import _exec_add_channel
            result = await _exec_add_channel(
                {"channel_id": "new_ch", "confirm": True},
                current_user=user,
            )

        assert result["created"] is True
        source = mock_state_repo.upsert_source.call_args[0][0]
        assert source.owner_id == user.id
