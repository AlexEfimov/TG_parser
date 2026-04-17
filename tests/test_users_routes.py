"""
HTTP tests for Users API (F4 Phase 5): /api/v1/users and /api/v1/users/me.

Uses ASGITransport + httpx.AsyncClient; mocks user_repo to avoid a real DB.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import User

PATCH_USER_REPO = "tg_parser.services.db_context.user_repo"

NOW = datetime(2025, 12, 13, 12, 0, 0, tzinfo=UTC)


def _db_user(
    user_id: str = "admin-1",
    name: str = "admin",
    role: str = "admin",
    max_channels: int | None = None,
) -> User:
    return User(
        id=user_id,
        name=name,
        role=role,
        max_channels=max_channels,
        created_at=NOW,
        updated_at=NOW,
    )


def _mock_user_repo(mock_repo):
    @asynccontextmanager
    async def ctx():
        yield (mock_repo, MagicMock())

    return ctx


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestUsersMe:
    async def test_get_me_ok(self, client):
        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = ["ch1", "ch2"]
        mock_repo.get_by_id.return_value = _db_user(
            "00000000-0000-0000-0000-000000000000", "admin", "admin"
        )

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.get("/api/v1/users/me")

        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "00000000-0000-0000-0000-000000000000"
        assert data["owned_channels"] == ["ch1", "ch2"]
        assert data["owned_channels_count"] == 2
        assert "max_channels" in data


class TestUsersList:
    async def test_list_users_ok_for_admin(self, client):
        mock_repo = AsyncMock()
        mock_repo.list_users.return_value = [
            _db_user("u1", "alice", "user"),
            _db_user("u2", "bob", "user"),
        ]
        mock_repo.get_owned_channel_ids.side_effect = [["c1"], ["c2", "c3"]]

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.get("/api/v1/users")

        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        assert body[0]["name"] == "alice"
        assert body[0]["owned_channels_count"] == 1
        assert body[1]["owned_channels_count"] == 2

    async def test_list_users_403_for_non_admin(self, app, client):
        async def _non_admin():
            return CurrentUser(
                id="user-1",
                name="alice",
                role="user",
                allowed_channel_ids=["ch1"],
                max_channels=5,
            )

        app.dependency_overrides[resolve_current_user] = _non_admin
        try:
            r = await client.get("/api/v1/users")
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 403
        assert "Admin" in r.json().get("detail", "")


class TestUsersCreate:
    async def test_post_users_201(self, client):
        mock_repo = AsyncMock()
        mock_repo.create_user.return_value = _db_user("new-id", "carol", "user")
        mock_repo.get_owned_channel_ids.return_value = []

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.post(
                "/api/v1/users",
                json={"name": "carol", "role": "user"},
            )

        assert r.status_code == 201
        data = r.json()
        assert data["id"] == "new-id"
        assert data["name"] == "carol"
        mock_repo.create_user.assert_awaited_once_with("carol", "user", None)

    async def test_post_users_403_non_admin(self, app, client):
        async def _non_admin():
            return CurrentUser(
                id="user-1",
                name="alice",
                role="user",
                allowed_channel_ids=["ch1"],
                max_channels=5,
            )

        app.dependency_overrides[resolve_current_user] = _non_admin
        try:
            r = await client.post("/api/v1/users", json={"name": "x"})
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 403


class TestUsersPatch:
    async def test_patch_user_200(self, client):
        mock_repo = AsyncMock()
        updated = _db_user("u1", "newname", "admin", max_channels=10)
        mock_repo.update_user.return_value = updated
        mock_repo.get_owned_channel_ids.return_value = []

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.patch(
                "/api/v1/users/u1",
                json={"name": "newname", "role": "admin", "max_channels": 10},
            )

        assert r.status_code == 200
        assert r.json()["name"] == "newname"
        mock_repo.update_user.assert_awaited_once()
        call_kw = mock_repo.update_user.call_args
        assert call_kw[0][0] == "u1"
        assert call_kw[1]["name"] == "newname"
        assert call_kw[1]["role"] == "admin"
        assert call_kw[1]["max_channels"] == 10

    async def test_patch_user_reset_max_channels(self, client):
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = _db_user("u1", "a", "user", max_channels=None)
        mock_repo.get_owned_channel_ids.return_value = []

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.patch(
                "/api/v1/users/u1",
                json={"reset_max_channels": True},
            )

        assert r.status_code == 200
        assert mock_repo.update_user.call_args[1]["max_channels"] is None

    async def test_patch_user_404(self, client):
        mock_repo = AsyncMock()
        mock_repo.update_user.return_value = None

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.patch("/api/v1/users/missing", json={"name": "x"})

        assert r.status_code == 404

    async def test_patch_user_403_non_admin(self, app, client):
        async def _non_admin():
            return CurrentUser(
                id="user-1",
                name="alice",
                role="user",
                allowed_channel_ids=["ch1"],
                max_channels=5,
            )

        app.dependency_overrides[resolve_current_user] = _non_admin
        try:
            r = await client.patch("/api/v1/users/u1", json={"name": "x"})
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 403


class TestUsersDelete:
    async def test_delete_user_204(self, client):
        mock_repo = AsyncMock()
        mock_repo.delete_user.return_value = True

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.delete("/api/v1/users/u1")

        assert r.status_code == 204
        assert r.content == b""
        mock_repo.delete_user.assert_awaited_once_with("u1")

    async def test_delete_user_404(self, client):
        mock_repo = AsyncMock()
        mock_repo.delete_user.return_value = False

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.delete("/api/v1/users/missing")

        assert r.status_code == 404

    async def test_delete_user_403_non_admin(self, app, client):
        async def _non_admin():
            return CurrentUser(
                id="user-1",
                name="alice",
                role="user",
                allowed_channel_ids=["ch1"],
                max_channels=5,
            )

        app.dependency_overrides[resolve_current_user] = _non_admin
        try:
            r = await client.delete("/api/v1/users/u1")
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 403


class TestUsersRoutingOrder:
    """Regression: /me must not be captured as {user_id}."""

    async def test_me_not_shadowed_by_user_id_route(self, client):
        mock_repo = AsyncMock()
        mock_repo.get_owned_channel_ids.return_value = []
        mock_repo.get_by_id.return_value = _db_user()

        with patch(PATCH_USER_REPO, _mock_user_repo(mock_repo)):
            r = await client.get("/api/v1/users/me")

        assert r.status_code == 200
        assert r.json()["id"] is not None
