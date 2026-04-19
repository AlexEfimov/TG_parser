"""
Tests for F4 Multi-Tenancy Phase 5: User Management Tools + Migration Script.

Unit tests (mock DB) for MCP tools, Bot tools, API routes, and migration CLI.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import User, UserAuthMapping

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _user(channels: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id="user-1",
        name="alice",
        role="user",
        allowed_channel_ids=channels if channels is not None else ["ch1"],
        max_channels=5,
    )


def _db_user(
    user_id: str = "new-id",
    name: str = "alice",
    role: str = "user",
    max_channels: int | None = None,
) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id, name=name, role=role, max_channels=max_channels, created_at=now, updated_at=now
    )


def _db_mapping(
    mapping_id: str = "map-1", user_id: str = "new-id", auth_type: str = "api_key"
) -> UserAuthMapping:
    return UserAuthMapping(
        id=mapping_id,
        user_id=user_id,
        auth_type=auth_type,
        auth_identifier="hashed",
        client_name="test",
        created_at=datetime.now(UTC),
    )


def _fake_user_repo(mock_repo):
    @asynccontextmanager
    async def _ctx():
        yield (mock_repo, MagicMock())

    return _ctx


# ===========================================================================
# MCP Tool Tests
# ===========================================================================


class TestMCPRegisterUser:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_register_user_creates_user(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.create_user.return_value = _db_user()

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import register_user

            result = await register_user("alice", ctx=None)

        assert result.success is True
        assert result.user_id == "new-id"
        mock_repo.create_user.assert_awaited_once_with("alice", "user", None)

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_register_user_with_role_and_max_channels(self, mock_resolve):
        mock_resolve.return_value = _admin()
        mock_repo = AsyncMock()
        mock_repo.create_user.return_value = _db_user(role="admin")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import register_user

            result = await register_user("ops", role="admin", max_channels=50, ctx=None)

        assert result.success is True
        mock_repo.create_user.assert_awaited_once_with("ops", "admin", 50)

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_register_user_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import register_user

        result = await register_user("bob", ctx=None)

        assert result.success is False
        assert "Admin" in result.message


class TestMCPUpdateUser:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_update_user_changes_properties(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user(name="bob_updated", role="admin")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import update_user

            result = await update_user("new-id", name="bob_updated", role="admin", ctx=None)

        assert result.success is True
        assert "updated" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_update_user_not_found(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = None

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import update_user

            result = await update_user("nonexistent", ctx=None)

        assert result.success is False
        assert "not found" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_update_user_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import update_user

        result = await update_user("u1", name="x", ctx=None)

        assert result.success is False
        assert "Admin" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_update_user_reset_max_channels_passes_none_to_repo(self, mock_resolve):
        mock_resolve.return_value = _admin()
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user()

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import update_user

            result = await update_user("u1", reset_max_channels=True, ctx=None)

        assert result.success is True
        assert mock_repo.update_user.call_args[1]["max_channels"] is None

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_update_user_explicit_max_channels(self, mock_resolve):
        mock_resolve.return_value = _admin()
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user()

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import update_user

            result = await update_user("u1", max_channels=42, ctx=None)

        assert result.success is True
        assert mock_repo.update_user.call_args[1]["max_channels"] == 42


class TestMCPListUsers:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_list_users_returns_all_with_counts(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.list_users.return_value = [
            _db_user("u1", "alice"),
            _db_user("u2", "bob"),
        ]
        mock_repo.get_owned_channel_ids.side_effect = [["ch1", "ch2"], ["ch3"]]

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import list_users

            result = await list_users(ctx=None)

        assert result.success is True
        assert len(result.users) == 2
        assert result.users[0].owned_channels_count == 2
        assert result.users[1].owned_channels_count == 1

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_list_users_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import list_users

        result = await list_users(ctx=None)

        assert result.success is False
        assert "Admin" in result.message


class TestMCPWhoami:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_whoami_returns_profile(self, mock_resolve):
        mock_resolve.return_value = _user(["ch1", "ch2"])

        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = ["ch1", "ch2"]
        mock_repo.get_by_id.return_value = _db_user("user-1", "alice")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import whoami

            result = await whoami(ctx=None)

        assert result.id == "user-1"
        assert result.name == "alice"
        assert result.owned_channels_count == 2
        assert result.owned_channels == ["ch1", "ch2"]

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_whoami_when_db_user_missing_uses_current_user_max(self, mock_resolve):
        """Synthetic / unresolved DB row: effective limit stays on CurrentUser."""
        mock_resolve.return_value = CurrentUser(
            id="orphan-id",
            name="ghost",
            role="user",
            allowed_channel_ids=["x"],
            max_channels=7,
        )
        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = ["x"]
        mock_repo.get_by_id.return_value = None

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import whoami

            result = await whoami(ctx=None)

        assert result.id == "orphan-id"
        assert result.max_channels == 7
        assert result.owned_channels_count == 1


# ===========================================================================
# Auth Mapping MCP Tests
# ===========================================================================


class TestMCPUserAuth:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_auth_hashes_api_key(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.add_auth_mapping.return_value = _db_mapping()

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.auth.resolvers.invalidate_user_cache") as mock_invalidate,
        ):
            from tg_parser.mcp_server import add_user_auth

            result = await add_user_auth("u1", "api_key", "raw-key-123", ctx=None)

        assert result.success is True
        assert result.mapping_id == "map-1"
        call_args = mock_repo.add_auth_mapping.call_args
        stored_identifier = call_args[0][2]
        assert stored_identifier != "raw-key-123"  # hashed
        assert len(stored_identifier) == 64  # SHA-256 hex
        mock_invalidate.assert_called_once()

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_auth_plain_telegram(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.add_auth_mapping.return_value = _db_mapping(auth_type="telegram")

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.auth.resolvers.invalidate_user_cache"),
        ):
            from tg_parser.mcp_server import add_user_auth

            result = await add_user_auth("u1", "telegram", "12345", ctx=None)

        assert result.success is True
        call_args = mock_repo.add_auth_mapping.call_args
        stored_identifier = call_args[0][2]
        assert stored_identifier == "12345"  # plain, not hashed

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_auth_invalid_type(self, mock_resolve):
        mock_resolve.return_value = _admin()

        from tg_parser.mcp_server import add_user_auth

        result = await add_user_auth("u1", "invalid_type", "key", ctx=None)

        assert result.success is False
        assert "Invalid auth_type" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_remove_auth_mapping(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.remove_auth_mapping.return_value = True

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import remove_user_auth

            result = await remove_user_auth("map-1", ctx=None)

        assert result.success is True
        mock_repo.remove_auth_mapping.assert_awaited_once_with("map-1")

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_remove_auth_not_found(self, mock_resolve):
        mock_resolve.return_value = _admin()

        mock_repo = AsyncMock()
        mock_repo.remove_auth_mapping.return_value = False

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.mcp_server import remove_user_auth

            result = await remove_user_auth("nonexistent", ctx=None)

        assert result.success is False
        assert "not found" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_user_auth_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import add_user_auth

        result = await add_user_auth("u1", "api_key", "k", ctx=None)

        assert result.success is False
        assert "Admin" in result.message

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_add_user_auth_mcp_token_hashed(self, mock_resolve):
        mock_resolve.return_value = _admin()
        mock_repo = AsyncMock()
        mock_repo.add_auth_mapping.return_value = _db_mapping(auth_type="mcp_token")

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.auth.resolvers.invalidate_user_cache"),
        ):
            from tg_parser.mcp_server import add_user_auth

            result = await add_user_auth("u1", "mcp_token", "secret-token", ctx=None)

        assert result.success is True
        stored = mock_repo.add_auth_mapping.call_args[0][2]
        assert stored != "secret-token"
        assert len(stored) == 64

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_remove_user_auth_rejected_for_non_admin(self, mock_resolve):
        mock_resolve.return_value = _user()

        from tg_parser.mcp_server import remove_user_auth

        result = await remove_user_auth("map-1", ctx=None)

        assert result.success is False
        assert "Admin" in result.message


# ===========================================================================
# Bot Tool Tests
# ===========================================================================


class TestBotWhoami:
    async def test_exec_whoami_returns_profile(self):
        user = _user(["ch1", "ch2"])

        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = ["ch1", "ch2"]
        mock_repo.get_by_id.return_value = _db_user("user-1", "alice")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_whoami

            result = await _exec_whoami({}, current_user=user)

        assert result["id"] == "user-1"
        assert result["name"] == "alice"
        assert result["owned_channels_count"] == 2


class TestBotRegisterUser:
    async def test_exec_register_user_admin_creates(self):
        admin = _admin()

        mock_repo = AsyncMock()
        mock_repo.create_user.return_value = _db_user("new-id", "bob", "user")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_register_user

            result = await _exec_register_user({"name": "bob"}, current_user=admin)

        assert result["user_id"] == "new-id"
        assert result["name"] == "bob"

    async def test_exec_register_user_rejected_for_non_admin(self):
        from tg_parser.bot.tools import _exec_register_user

        result = await _exec_register_user({"name": "bob"}, current_user=_user())

        assert "error" in result
        assert "Admin" in result["error"]


class TestBotListUsers:
    async def test_exec_list_users_admin(self):
        mock_repo = AsyncMock()
        mock_repo.list_users.return_value = [_db_user("u1", "alice")]
        mock_repo.get_owned_channel_ids.return_value = ["ch1"]

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_list_users

            result = await _exec_list_users({}, current_user=_admin())

        assert result["count"] == 1
        assert result["users"][0]["name"] == "alice"

    async def test_exec_list_users_rejected_for_non_admin(self):
        from tg_parser.bot.tools import _exec_list_users

        result = await _exec_list_users({}, current_user=_user())

        assert "error" in result
        assert "Admin" in result["error"]


class TestBotUpdateUser:
    async def test_exec_update_user_admin_success(self):
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user("u1", "new", "user")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_update_user

            result = await _exec_update_user(
                {"user_id": "u1", "name": "new"},
                current_user=_admin(),
            )

        assert result.get("success") is True
        assert result["name"] == "new"

    async def test_exec_update_user_non_admin(self):
        from tg_parser.bot.tools import _exec_update_user

        result = await _exec_update_user({"user_id": "u1", "name": "x"}, current_user=_user())

        assert "error" in result
        assert "Admin" in result["error"]

    async def test_exec_update_user_reset_max_channels(self):
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user("u1", "a", "user")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_update_user

            result = await _exec_update_user(
                {"user_id": "u1", "reset_max_channels": True},
                current_user=_admin(),
            )

        assert result.get("success") is True
        assert mock_repo.update_user.call_args[1]["max_channels"] is None


class TestBotRemoveUserAuth:
    async def test_exec_remove_user_auth_success(self):
        mock_repo = AsyncMock()
        mock_repo.remove_auth_mapping.return_value = True

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_remove_user_auth

            result = await _exec_remove_user_auth({"mapping_id": "m1"}, current_user=_admin())

        assert result["success"] is True
        mock_repo.remove_auth_mapping.assert_awaited_once_with("m1")

    async def test_exec_remove_user_auth_not_found(self):
        mock_repo = AsyncMock()
        mock_repo.remove_auth_mapping.return_value = False

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.bot.tools import _exec_remove_user_auth

            result = await _exec_remove_user_auth({"mapping_id": "x"}, current_user=_admin())

        assert "error" in result

    async def test_exec_remove_user_auth_non_admin(self):
        from tg_parser.bot.tools import _exec_remove_user_auth

        result = await _exec_remove_user_auth({"mapping_id": "m1"}, current_user=_user())

        assert "error" in result


class TestBotAddUserAuth:
    async def test_exec_add_user_auth_hashes_api_key(self):
        mock_repo = AsyncMock()
        mock_repo.add_auth_mapping.return_value = _db_mapping()

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.auth.resolvers.invalidate_user_cache"),
        ):
            from tg_parser.bot.tools import _exec_add_user_auth

            result = await _exec_add_user_auth(
                {"user_id": "u1", "auth_type": "api_key", "identifier": "raw-key"},
                current_user=_admin(),
            )

        assert result["mapping_id"] == "map-1"
        call_args = mock_repo.add_auth_mapping.call_args
        stored = call_args[0][2]
        assert stored != "raw-key"
        assert len(stored) == 64

    async def test_exec_add_user_auth_plain_telegram(self):
        mock_repo = AsyncMock()
        mock_repo.add_auth_mapping.return_value = _db_mapping(auth_type="telegram")

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.auth.resolvers.invalidate_user_cache"),
        ):
            from tg_parser.bot.tools import _exec_add_user_auth

            result = await _exec_add_user_auth(
                {"user_id": "u1", "auth_type": "telegram", "identifier": "999"},
                current_user=_admin(),
            )

        assert result["mapping_id"] == "map-1"
        assert mock_repo.add_auth_mapping.call_args[0][2] == "999"

    async def test_exec_add_user_auth_invalid_type(self):
        from tg_parser.bot.tools import _exec_add_user_auth

        result = await _exec_add_user_auth(
            {"user_id": "u1", "auth_type": "oauth", "identifier": "x"},
            current_user=_admin(),
        )

        assert "error" in result
        assert "Invalid auth_type" in result["error"]

    async def test_exec_add_user_auth_non_admin(self):
        from tg_parser.bot.tools import _exec_add_user_auth

        result = await _exec_add_user_auth(
            {"user_id": "u1", "auth_type": "api_key", "identifier": "k"},
            current_user=_user(),
        )

        assert "error" in result
        assert "Admin" in result["error"]


# ===========================================================================
# API Route Tests
# ===========================================================================


class TestAPIUsers:
    async def test_get_me_returns_profile(self):
        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = ["ch1"]
        mock_repo.get_by_id.return_value = _db_user("user-1", "alice")

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import get_me

            result = await get_me(user=_user(["ch1"]))

        assert result.id == "user-1"
        assert result.owned_channels == ["ch1"]

    async def test_create_user_admin_only(self):
        """Non-admin should raise PermissionDenied."""
        from tg_parser.api.routes.users import CreateUserRequest, create_user
        from tg_parser.auth.ownership import PermissionDenied

        with pytest.raises(PermissionDenied, match="Admin access required"):
            await create_user(body=CreateUserRequest(name="bob"), user=_user())

    async def test_create_user_success(self):
        mock_repo = AsyncMock()
        mock_repo.create_user.return_value = _db_user("new-id", "bob")
        mock_repo.get_owned_channel_ids.return_value = []

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import CreateUserRequest, create_user

            result = await create_user(body=CreateUserRequest(name="bob"), user=_admin())

        assert result.id == "new-id"
        assert result.name == "bob"

    async def test_delete_user_cascades(self):
        mock_repo = AsyncMock()
        mock_repo.delete_user.return_value = True

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import delete_user

            await delete_user("user-to-delete", user=_admin())

        mock_repo.delete_user.assert_awaited_once_with("user-to-delete")

    async def test_delete_user_not_found(self):
        from fastapi import HTTPException

        mock_repo = AsyncMock()
        mock_repo.delete_user.return_value = False

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import delete_user

            with pytest.raises(HTTPException) as exc_info:
                await delete_user("nonexistent", user=_admin())
            assert exc_info.value.status_code == 404

    async def test_list_users_admin_only(self):
        from tg_parser.api.routes.users import list_users
        from tg_parser.auth.ownership import PermissionDenied

        with pytest.raises(PermissionDenied, match="Admin access required"):
            await list_users(user=_user())

    async def test_list_users_admin_returns_rows(self):
        mock_repo = AsyncMock()
        mock_repo.list_users.return_value = [_db_user("a", "u1", "user")]
        mock_repo.get_owned_channel_ids.return_value = ["c1"]

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import list_users

            rows = await list_users(user=_admin())

        assert len(rows) == 1
        assert rows[0].owned_channels_count == 1

    async def test_update_user_admin_success(self):
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user("u1", "x", "admin", max_channels=3)
        mock_repo.get_owned_channel_ids.return_value = []

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import UpdateUserRequest, update_user

            row = await update_user(
                "u1", body=UpdateUserRequest(name="x", role="admin", max_channels=3), user=_admin()
            )

        assert row.name == "x"
        assert mock_repo.update_user.await_args[1]["max_channels"] == 3

    async def test_update_user_non_admin_raises(self):
        from tg_parser.api.routes.users import UpdateUserRequest, update_user
        from tg_parser.auth.ownership import PermissionDenied

        with pytest.raises(PermissionDenied):
            await update_user("u1", body=UpdateUserRequest(name="x"), user=_user())

    async def test_update_user_not_found_http(self):
        from fastapi import HTTPException

        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = None

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import UpdateUserRequest, update_user

            with pytest.raises(HTTPException) as ei:
                await update_user("missing", body=UpdateUserRequest(name="a"), user=_admin())
            assert ei.value.status_code == 404

    async def test_get_me_uses_default_max_when_user_max_null_in_db(self):
        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = []
        mock_repo.get_by_id.return_value = _db_user("u1", "alice", "user", max_channels=None)

        with patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)):
            from tg_parser.api.routes.users import get_me

            row = await get_me(user=_user([]))

        assert row.max_channels >= 1


# ===========================================================================
# Migration Tests
# ===========================================================================


class TestMigrateUsers:
    async def test_migration_creates_admin_and_maps(self):
        mock_repo = AsyncMock()
        admin_user = _db_user("admin-uuid", "admin", "admin")
        mock_repo.create_user.return_value = admin_user
        mock_repo.resolve_auth.return_value = None
        mock_repo.find_first_by_role.return_value = None  # DI-11: simulate empty DB
        mock_repo.add_auth_mapping.return_value = _db_mapping()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_session.execute.return_value = mock_result
        mock_repo.session = mock_session

        fake_settings = MagicMock()
        fake_settings.api_keys = {"key1": "client1", "key2": "client2"}
        fake_settings.mcp_auth_tokens = {"tok1": "mcp_client"}
        fake_settings.bot_allowed_user_ids = [111, 222]

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.config.settings", fake_settings),
            patch("tg_parser.storage.sqlalchemy.Database") as mock_db_cls,
        ):
            mock_db = AsyncMock()
            mock_db_cls.get_instance.return_value = mock_db
            mock_db_cls.close_instance = AsyncMock()

            from tg_parser.cli.migrate_users_cmd import run_migrate_users

            stats = await run_migrate_users(dry_run=False)

        assert stats["admin_created"] is True
        assert stats["api_keys_mapped"] == 2
        assert stats["mcp_tokens_mapped"] == 1
        assert stats["telegram_users_mapped"] == 2
        assert stats["orphan_sources_assigned"] == 3

    async def test_migration_idempotent(self):
        existing_admin = _db_user("admin-uuid", "admin", "admin")

        mock_repo = AsyncMock()
        mock_repo.resolve_auth.return_value = existing_admin
        mock_repo.add_auth_mapping.return_value = _db_mapping()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result
        mock_repo.session = mock_session

        fake_settings = MagicMock()
        fake_settings.api_keys = {"key1": "client1"}
        fake_settings.mcp_auth_tokens = {}
        fake_settings.bot_allowed_user_ids = []

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.config.settings", fake_settings),
            patch("tg_parser.storage.sqlalchemy.Database") as mock_db_cls,
        ):
            mock_db = AsyncMock()
            mock_db_cls.get_instance.return_value = mock_db
            mock_db_cls.close_instance = AsyncMock()

            from tg_parser.cli.migrate_users_cmd import run_migrate_users

            stats = await run_migrate_users(dry_run=False)

        assert stats["admin_created"] is False
        assert stats["skipped_existing"] == 1
        assert stats["api_keys_mapped"] == 0

    async def test_migration_empty_settings(self):
        mock_repo = AsyncMock()
        admin_user = _db_user("admin-uuid", "admin", "admin")
        mock_repo.create_user.return_value = admin_user
        mock_repo.resolve_auth.return_value = None
        mock_repo.find_first_by_role.return_value = None  # DI-11: simulate empty DB

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result
        mock_repo.session = mock_session

        fake_settings = MagicMock()
        fake_settings.api_keys = {}
        fake_settings.mcp_auth_tokens = {}
        fake_settings.bot_allowed_user_ids = []

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.config.settings", fake_settings),
            patch("tg_parser.storage.sqlalchemy.Database") as mock_db_cls,
        ):
            mock_db = AsyncMock()
            mock_db_cls.get_instance.return_value = mock_db
            mock_db_cls.close_instance = AsyncMock()

            from tg_parser.cli.migrate_users_cmd import run_migrate_users

            stats = await run_migrate_users(dry_run=False)

        assert stats["admin_created"] is True
        assert stats["api_keys_mapped"] == 0
        assert stats["mcp_tokens_mapped"] == 0
        assert stats["telegram_users_mapped"] == 0

    async def test_migration_dry_run_no_writes(self):
        mock_repo = AsyncMock()
        mock_repo.resolve_auth.return_value = None
        mock_repo.find_first_by_role.return_value = None  # DI-11: simulate empty DB

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (5,)
        mock_session.execute.return_value = mock_result
        mock_repo.session = mock_session

        fake_settings = MagicMock()
        fake_settings.api_keys = {"k1": "c1"}
        fake_settings.mcp_auth_tokens = {}
        fake_settings.bot_allowed_user_ids = []

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.config.settings", fake_settings),
            patch("tg_parser.storage.sqlalchemy.Database") as mock_db_cls,
        ):
            mock_db = AsyncMock()
            mock_db_cls.get_instance.return_value = mock_db
            mock_db_cls.close_instance = AsyncMock()

            from tg_parser.cli.migrate_users_cmd import run_migrate_users

            stats = await run_migrate_users(dry_run=True)

        assert stats["dry_run"] is True
        mock_repo.create_user.assert_not_awaited()
        mock_repo.add_auth_mapping.assert_not_awaited()
        assert stats["api_keys_mapped"] == 1
        assert stats["admin_created"] is True

    async def test_migration_creates_admin_when_only_mcp_tokens(self):
        """No API keys: first block skipped; create_user still runs for admin."""
        mock_repo = AsyncMock()
        admin_user = _db_user("adm", "admin", "admin")
        mock_repo.create_user.return_value = admin_user
        mock_repo.resolve_auth.return_value = None
        mock_repo.find_first_by_role.return_value = None  # DI-11: simulate empty DB
        mock_repo.add_auth_mapping.return_value = _db_mapping()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result
        mock_repo.session = mock_session

        fake_settings = MagicMock()
        fake_settings.api_keys = {}
        fake_settings.mcp_auth_tokens = {"tok": "cli"}
        fake_settings.bot_allowed_user_ids = []

        with (
            patch("tg_parser.services.db_context.user_repo", _fake_user_repo(mock_repo)),
            patch("tg_parser.config.settings", fake_settings),
            patch("tg_parser.storage.sqlalchemy.Database") as mock_db_cls,
        ):
            mock_db = AsyncMock()
            mock_db_cls.get_instance.return_value = mock_db
            mock_db_cls.close_instance = AsyncMock()

            from tg_parser.cli.migrate_users_cmd import run_migrate_users

            stats = await run_migrate_users(dry_run=False)

        assert stats["admin_created"] is True
        assert stats["mcp_tokens_mapped"] == 1
        mock_repo.create_user.assert_awaited_once_with("admin", role="admin")
