"""BUG-099 / R1 — resolve_mcp_user must not degrade a lost identity into admin.

The six existing MCP auth tests cover forgery (BUG-001) and the empty
static-mapping guard (BUG-001b). None of them describe «identity is present
but does not resolve». These tests do: four resolve branches plus the
deeper get_owned_channel_ids failure, the Prometheus counter, and DB-only
startup (empty MCP_AUTH_TOKENS with auth still on).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.storage.ports import User

_UUID_ALICE = str(uuid4())
_UUID_MISSING = str(uuid4())
_LEGACY_CLIENT = "claude-desktop"


def _user_repo_cm(repo: AsyncMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=(repo, MagicMock()))
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _repo(*, get_by_id=None, get_owned_channel_ids=None) -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=get_by_id)
    repo.get_owned_channel_ids = AsyncMock(return_value=get_owned_channel_ids or [])
    return repo


class TestResolveBranches:
    """§3.1 — four branches plus get_owned_channel_ids. Red on today's code
    wherever that code returns default admin."""

    async def test_uuid_that_resolves_returns_that_user(self):
        from tg_parser.mcp_server import resolve_mcp_user

        alice = User(id=_UUID_ALICE, name="alice", role="user", max_channels=5)
        repo = _repo(get_by_id=alice, get_owned_channel_ids=["ch1"])

        with patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)):
            user = await resolve_mcp_user(_UUID_ALICE)

        assert user.id == _UUID_ALICE
        assert user.is_admin is False
        assert user.allowed_channel_ids == ["ch1"]

    async def test_uuid_missing_from_db_is_permission_error(self):
        from tg_parser.mcp_server import resolve_mcp_user

        repo = _repo(get_by_id=None)

        with (
            patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)),
            pytest.raises(PermissionError),
        ):
            await resolve_mcp_user(_UUID_MISSING)

    async def test_uuid_db_error_is_permission_error(self):
        from tg_parser.mcp_server import resolve_mcp_user

        repo = AsyncMock()
        repo.get_by_id = AsyncMock(side_effect=SQLAlchemyError("db down"))

        with (
            patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)),
            pytest.raises(PermissionError),
        ):
            await resolve_mcp_user(_UUID_MISSING)

    async def test_legacy_static_client_name_still_returns_admin(self):
        from tg_parser.mcp_server import resolve_mcp_user

        repo = _repo(get_by_id=None)

        with patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)):
            user = await resolve_mcp_user(_LEGACY_CLIENT)

        assert user.is_admin is True

    async def test_owned_channels_error_for_non_admin_is_permission_error(self):
        from tg_parser.mcp_server import resolve_mcp_user

        alice = User(id=_UUID_ALICE, name="alice", role="user", max_channels=5)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=alice)
        repo.get_owned_channel_ids = AsyncMock(side_effect=SQLAlchemyError("db down"))

        with (
            patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)),
            pytest.raises(PermissionError),
        ):
            await resolve_mcp_user(_UUID_ALICE)

    async def test_dev_mode_none_still_returns_admin(self):
        from tg_parser.config import settings
        from tg_parser.mcp_server import resolve_mcp_user

        with patch.object(settings, "mcp_auth_enabled", False):
            user = await resolve_mcp_user(None)

        assert user.is_admin is True


class TestIdentityResolveCounter:
    """§3.3 — one counter, outcome label, no client_id cardinality."""

    def _value(self, outcome: str) -> float:
        from tg_parser.api.metrics import MCP_IDENTITY_RESOLVE_TOTAL

        return MCP_IDENTITY_RESOLVE_TOTAL.labels(outcome=outcome)._value.get()

    async def test_resolved_outcome_increments(self):
        from tg_parser.mcp_server import resolve_mcp_user

        alice = User(id=_UUID_ALICE, name="alice", role="user", max_channels=5)
        repo = _repo(get_by_id=alice, get_owned_channel_ids=["ch1"])
        before = self._value("resolved")

        with patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)):
            await resolve_mcp_user(_UUID_ALICE)

        assert self._value("resolved") == pytest.approx(before + 1.0)

    async def test_unresolved_uuid_increments(self):
        from tg_parser.mcp_server import resolve_mcp_user

        repo = _repo(get_by_id=None)
        before = self._value("unresolved_uuid")

        with (
            patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)),
            pytest.raises(PermissionError),
        ):
            await resolve_mcp_user(_UUID_MISSING)

        assert self._value("unresolved_uuid") == pytest.approx(before + 1.0)

    async def test_db_error_increments(self):
        from tg_parser.mcp_server import resolve_mcp_user

        repo = AsyncMock()
        repo.get_by_id = AsyncMock(side_effect=SQLAlchemyError("db down"))
        before = self._value("db_error")

        with (
            patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)),
            pytest.raises(PermissionError),
        ):
            await resolve_mcp_user(_UUID_MISSING)

        assert self._value("db_error") == pytest.approx(before + 1.0)

    async def test_static_fallback_increments(self):
        from tg_parser.mcp_server import resolve_mcp_user

        repo = _repo(get_by_id=None)
        before = self._value("static_fallback")

        with patch("tg_parser.services.db_context.user_repo", return_value=_user_repo_cm(repo)):
            await resolve_mcp_user(_LEGACY_CLIENT)

        assert self._value("static_fallback") == pytest.approx(before + 1.0)


class TestDbOnlyStartup:
    """§3.5 — auth on + empty tokens is DB-only, not a silent skip."""

    def test_auth_enabled_with_empty_tokens_wires_verifier(self):
        from tg_parser.config import settings
        from tg_parser.mcp_server import BearerTokenVerifier, create_mcp_server

        with (
            patch.object(settings, "mcp_auth_enabled", True),
            patch.object(settings, "mcp_auth_tokens", {}),
        ):
            server = create_mcp_server()

        assert isinstance(server._token_verifier, BearerTokenVerifier)
