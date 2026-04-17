"""
Tests for F4 Multi-Tenancy Phase 2: Auth resolution + CurrentUser.

Unit tests (mock DB) + integration tests (TEST_POSTGRES=1).
"""

import hashlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.resolvers import (
    clear_cache,
    get_default_admin,
    hash_credential,
    resolve_user_by_auth,
)

# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------


class TestCurrentUser:
    def test_admin_is_admin(self):
        user = CurrentUser(
            id="1", name="admin", role="admin", allowed_channel_ids=None, max_channels=20,
        )
        assert user.is_admin is True
        assert user.allowed_channel_ids is None

    def test_regular_user_not_admin(self):
        user = CurrentUser(
            id="2", name="alice", role="user", allowed_channel_ids=["ch1"], max_channels=5,
        )
        assert user.is_admin is False
        assert user.allowed_channel_ids == ["ch1"]


class TestDefaultAdmin:
    async def test_default_admin_is_admin(self):
        admin = await get_default_admin()
        assert admin.is_admin is True
        assert admin.role == "admin"
        assert admin.allowed_channel_ids is None

    async def test_default_admin_consistent_id(self):
        a1 = await get_default_admin()
        a2 = await get_default_admin()
        assert a1.id == a2.id


class TestHashCredential:
    def test_sha256(self):
        raw = "sk-test-123"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert hash_credential(raw) == expected

    def test_deterministic(self):
        assert hash_credential("abc") == hash_credential("abc")

    def test_different_inputs(self):
        assert hash_credential("a") != hash_credential("b")


class TestResolveUserByAuth:
    """Tests with mocked DB layer."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_cache()
        yield
        clear_cache()

    async def test_resolve_returns_none_when_not_found(self):
        from tg_parser.storage.ports import User

        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("api_key", "nonexistent")

        assert result is None

    async def test_resolve_admin_has_none_channels(self):
        from tg_parser.storage.ports import User

        admin = User(id="admin-id", name="admin", role="admin")
        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=admin)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("api_key", "admin-hash")

        assert result is not None
        assert result.is_admin is True
        assert result.allowed_channel_ids is None

    async def test_resolve_user_gets_owned_channels(self):
        from tg_parser.storage.ports import User

        user = User(id="user-id", name="alice", role="user", max_channels=5)
        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=["ch1", "ch2"])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("telegram", "12345")

        assert result is not None
        assert result.is_admin is False
        assert result.allowed_channel_ids == ["ch1", "ch2"]
        assert result.max_channels == 5

    async def test_cache_hit_skips_db(self):
        from tg_parser.storage.ports import User

        user = User(id="cached-id", name="bob", role="user", max_channels=10)
        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=["ch_a"])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            r1 = await resolve_user_by_auth("telegram", "55555")
            r2 = await resolve_user_by_auth("telegram", "55555")

        assert r1 is not None
        assert r2 is not None
        assert r1.id == r2.id
        # DB should have been called only once (second call hit cache)
        assert mock_repo.resolve_auth.call_count == 1

    async def test_cache_invalidation(self):
        from tg_parser.auth.resolvers import invalidate_user_cache
        from tg_parser.storage.ports import User

        user = User(id="inv-id", name="carol", role="user")
        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            await resolve_user_by_auth("telegram", "77777")
            invalidate_user_cache("telegram", "77777")
            await resolve_user_by_auth("telegram", "77777")

        assert mock_repo.resolve_auth.call_count == 2

    async def test_default_max_channels_used_when_user_has_none(self):
        """settings.default_max_channels used when user.max_channels is None."""
        from tg_parser.storage.ports import User

        user = User(id="defmax-id", name="nolimit", role="user", max_channels=None)
        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("telegram", "88888")

        assert result is not None
        from tg_parser.config import settings
        assert result.max_channels == settings.default_max_channels

    async def test_clear_cache_empties_all(self):
        from tg_parser.storage.ports import User

        user = User(id="clr-id", name="x", role="user")
        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            await resolve_user_by_auth("telegram", "99999")
            clear_cache()
            await resolve_user_by_auth("telegram", "99999")

        assert mock_repo.resolve_auth.call_count == 2


# ---------------------------------------------------------------------------
# API auth dependency tests
# ---------------------------------------------------------------------------


class TestAPIAuth:
    async def test_no_key_no_requirement_returns_admin(self):
        from tg_parser.api.auth import resolve_current_user

        with patch("tg_parser.api.auth.settings") as mock_settings:
            mock_settings.api_key_required = False
            mock_settings.api_keys = {}
            mock_settings.default_max_channels = 20

            user = await resolve_current_user(api_key=None)
            assert user.is_admin is True

    async def test_no_key_with_requirement_raises_401(self):
        from fastapi import HTTPException

        from tg_parser.api.auth import resolve_current_user

        with patch("tg_parser.api.auth.settings") as mock_settings:
            mock_settings.api_key_required = True

            with pytest.raises(HTTPException) as exc_info:
                await resolve_current_user(api_key=None)
            assert exc_info.value.status_code == 401

    async def test_invalid_key_raises_403(self):
        from fastapi import HTTPException

        from tg_parser.api.auth import resolve_current_user

        with patch("tg_parser.api.auth.settings") as mock_settings:
            mock_settings.api_key_required = False
            mock_settings.api_keys = {"valid-key": "client1"}

            with pytest.raises(HTTPException) as exc_info:
                await resolve_current_user(api_key="bad-key")
            assert exc_info.value.status_code == 403

    async def test_valid_key_mapped_to_db_user(self):
        """Valid API key with a DB user mapping returns that user."""
        from tg_parser.api.auth import resolve_current_user

        mock_user = CurrentUser(
            id="db-user-id", name="db_alice", role="user",
            allowed_channel_ids=["ch1"], max_channels=5,
        )
        clear_cache()

        with patch("tg_parser.api.auth.settings") as mock_settings, \
             patch("tg_parser.api.auth.resolve_user_by_auth", return_value=mock_user):
            mock_settings.api_key_required = False
            mock_settings.api_keys = {"my-key": "client_alice"}
            mock_settings.default_max_channels = 20

            user = await resolve_current_user(api_key="my-key")

        assert user.name == "db_alice"
        assert user.is_admin is False
        assert user.allowed_channel_ids == ["ch1"]

    async def test_valid_key_not_mapped_falls_back_to_admin(self):
        """Valid API key without DB mapping falls back to default admin."""
        from tg_parser.api.auth import resolve_current_user

        clear_cache()

        with patch("tg_parser.api.auth.settings") as mock_settings, \
             patch("tg_parser.api.auth.resolve_user_by_auth", return_value=None):
            mock_settings.api_key_required = False
            mock_settings.api_keys = {"orphan-key": "client_orphan"}
            mock_settings.default_max_channels = 20

            user = await resolve_current_user(api_key="orphan-key")

        assert user.is_admin is True

    async def test_get_optional_user_no_key(self):
        from tg_parser.api.auth import get_optional_user

        result = await get_optional_user(api_key=None)
        assert result is None

    async def test_get_optional_user_invalid_key(self):
        from tg_parser.api.auth import get_optional_user

        with patch("tg_parser.api.auth.settings") as mock_settings:
            mock_settings.api_keys = {"good": "client"}

            result = await get_optional_user(api_key="bad")
        assert result is None

    async def test_get_optional_user_valid_key(self):
        from tg_parser.api.auth import get_optional_user

        mock_user = CurrentUser(
            id="opt-id", name="opt_user", role="user",
            allowed_channel_ids=[], max_channels=10,
        )
        clear_cache()

        with patch("tg_parser.api.auth.settings") as mock_settings, \
             patch("tg_parser.api.auth.resolve_user_by_auth", return_value=mock_user):
            mock_settings.api_keys = {"opt-key": "opt_client"}

            result = await get_optional_user(api_key="opt-key")
        assert result is not None
        assert result.name == "opt_user"


# ---------------------------------------------------------------------------
# Bot middleware tests
# ---------------------------------------------------------------------------


class TestUserResolutionMiddleware:
    async def test_dev_mode_unregistered_gets_admin(self):
        from tg_parser.bot.middleware import UserResolutionMiddleware

        mw = UserResolutionMiddleware(allowed_user_ids=[])

        msg = MagicMock()
        msg.from_user = MagicMock()
        msg.from_user.id = 999
        msg.from_user.username = "unknown"

        handler = AsyncMock()
        data: dict = {}

        with patch("tg_parser.services.db_context.user_repo") as mock_ur:
            mock_repo = AsyncMock()
            mock_repo.resolve_auth = AsyncMock(return_value=None)
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_ur.return_value = mock_cm

            clear_cache()
            # isinstance(event, Message) needs to be true
            with patch("tg_parser.bot.middleware.isinstance", side_effect=lambda o, t: True):
                await mw(handler, msg, data)

        assert "current_user" in data
        assert data["current_user"].is_admin is True

    async def test_unregistered_user_rejected_with_allowlist(self):
        """When allowlist is non-empty and user not in DB, reject."""
        from tg_parser.bot.middleware import UserResolutionMiddleware

        mw = UserResolutionMiddleware(allowed_user_ids=[100, 200])

        msg = MagicMock()
        msg.from_user = MagicMock()
        msg.from_user.id = 555
        msg.from_user.username = "stranger"
        msg.answer = AsyncMock()

        handler = AsyncMock()
        data: dict = {}

        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=None)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            clear_cache()
            with patch("tg_parser.bot.middleware.isinstance", side_effect=lambda o, t: True):
                result = await mw(handler, msg, data)

        assert result is None
        msg.answer.assert_called_once()
        handler.assert_not_called()
        assert "current_user" not in data

    async def test_non_message_event_passthrough(self):
        """Non-Message events are passed through without resolution."""
        from tg_parser.bot.middleware import UserResolutionMiddleware

        mw = UserResolutionMiddleware(allowed_user_ids=[100])

        event = MagicMock()
        event.from_user = None
        handler = AsyncMock(return_value="ok")
        data: dict = {}

        # isinstance returns False for non-Message
        with patch("tg_parser.bot.middleware.isinstance", return_value=False):
            result = await mw(handler, event, data)

        assert result == "ok"
        handler.assert_called_once()
        assert "current_user" not in data

    async def test_registered_user_resolved(self):
        from tg_parser.bot.middleware import UserResolutionMiddleware
        from tg_parser.storage.ports import User

        mw = UserResolutionMiddleware(allowed_user_ids=[123])

        msg = MagicMock(spec=["from_user", "answer"])
        msg.from_user = MagicMock()
        msg.from_user.id = 123
        msg.from_user.username = "alice"

        user = User(id="u1", name="alice", role="user", max_channels=5)
        handler = AsyncMock()
        data: dict = {}

        mock_repo = AsyncMock()
        mock_repo.resolve_auth = AsyncMock(return_value=user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=["ch1"])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            clear_cache()
            # We need isinstance checks to pass for Message
            with patch("tg_parser.bot.middleware.isinstance", side_effect=lambda o, t: True):
                await mw(handler, msg, data)

        assert "current_user" in data
        assert data["current_user"].name == "alice"
        assert data["current_user"].allowed_channel_ids == ["ch1"]


# ---------------------------------------------------------------------------
# Integration tests (TEST_POSTGRES=1)
# ---------------------------------------------------------------------------


pytestmark_pg = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


@pytestmark_pg
class TestAuthResolutionIntegration:
    @pytest.fixture(autouse=True)
    async def _cleanup_f4_tables(self, test_db):
        session = test_db.ingestion_state_session()
        try:
            from sqlalchemy import text
            await session.execute(text("DELETE FROM user_auth_mappings"))
            await session.execute(text("UPDATE sources SET owner_id = NULL"))
            await session.execute(text("DELETE FROM users"))
            await session.commit()
        finally:
            await session.close()
        clear_cache()
        yield

    @pytest.fixture
    async def user_repo(self, test_db):
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = test_db.ingestion_state_session()
        try:
            yield SAUserRepo(session)
        finally:
            await session.close()

    async def test_api_key_roundtrip(self, user_repo):
        clear_cache()
        user = await user_repo.create_user("api_test_user", role="user", max_channels=3)
        hashed = hash_credential("sk-api-test-key")
        await user_repo.add_auth_mapping(user.id, "api_key", hashed, client_name="test")

        mock_repo = AsyncMock(wraps=user_repo)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("api_key", hashed)

        assert result is not None
        assert result.name == "api_test_user"
        assert result.max_channels == 3

    async def test_telegram_roundtrip(self, user_repo):
        clear_cache()
        user = await user_repo.create_user("tg_test_user")
        await user_repo.add_auth_mapping(user.id, "telegram", "111222333")

        mock_repo = AsyncMock(wraps=user_repo)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("telegram", "111222333")

        assert result is not None
        assert result.name == "tg_test_user"

    async def test_mcp_token_roundtrip(self, user_repo):
        clear_cache()
        user = await user_repo.create_user("mcp_test_user")
        hashed = hash_credential("mcp-token-secret")
        await user_repo.add_auth_mapping(user.id, "mcp_token", hashed)

        mock_repo = AsyncMock(wraps=user_repo)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_user_by_auth("mcp_token", hashed)

        assert result is not None
        assert result.name == "mcp_test_user"


# ---------------------------------------------------------------------------
# MCP auth tests
# ---------------------------------------------------------------------------


class TestBearerTokenVerifier:
    """Unit tests for MCP BearerTokenVerifier."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_cache()
        yield
        clear_cache()

    async def test_db_resolved_token(self):
        from tg_parser.mcp_server import BearerTokenVerifier

        mock_user = CurrentUser(
            id="mcp-u1", name="mcp_user", role="user",
            allowed_channel_ids=["ch1"], max_channels=5,
        )
        verifier = BearerTokenVerifier({"static-token": "static_client"})

        with patch("tg_parser.auth.resolvers.resolve_user_by_auth", return_value=mock_user):
            token = await verifier.verify_token("db-backed-token")

        assert token is not None
        assert token.client_id == "mcp-u1"

    async def test_static_fallback_token(self):
        from tg_parser.mcp_server import BearerTokenVerifier

        verifier = BearerTokenVerifier({"static-token": "static_client"})

        with patch("tg_parser.auth.resolvers.resolve_user_by_auth", return_value=None):
            token = await verifier.verify_token("static-token")

        assert token is not None
        assert token.client_id == "static_client"

    async def test_unknown_token_rejected(self):
        from tg_parser.mcp_server import BearerTokenVerifier

        verifier = BearerTokenVerifier({"static-token": "client"})

        with patch("tg_parser.auth.resolvers.resolve_user_by_auth", return_value=None):
            token = await verifier.verify_token("unknown-token")

        assert token is None


class TestResolveMcpUser:
    """Unit tests for resolve_mcp_user helper."""

    async def test_none_client_id_returns_admin(self):
        from tg_parser.mcp_server import resolve_mcp_user

        result = await resolve_mcp_user(None)
        assert result.is_admin is True

    async def test_unknown_client_id_returns_admin(self):
        from tg_parser.mcp_server import resolve_mcp_user
        from tg_parser.storage.ports import User

        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=None)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_mcp_user("nonexistent-uuid")

        assert result.is_admin is True

    async def test_known_user_client_id(self):
        from tg_parser.mcp_server import resolve_mcp_user
        from tg_parser.storage.ports import User

        db_user = User(id="mcp-uid", name="mcp_alice", role="user", max_channels=8)

        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=db_user)
        mock_repo.get_owned_channel_ids = AsyncMock(return_value=["ch_a", "ch_b"])
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_repo, MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("tg_parser.services.db_context.user_repo", return_value=mock_cm):
            result = await resolve_mcp_user("mcp-uid")

        assert result.name == "mcp_alice"
        assert result.is_admin is False
        assert result.allowed_channel_ids == ["ch_a", "ch_b"]
        assert result.max_channels == 8
