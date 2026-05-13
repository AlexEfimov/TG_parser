"""F4-B Core — Phase 5 multi-user workspace isolation tests.

Verifies that:

* user A cannot see user B's workspaces via ``list_workspaces``;
* user A passing user B's ``workspace_id`` through any scoped read tool
  receives a 404-like empty response (no leak via differentiating error
  messages — see Q2 edge case 2 of the start prompt);
* admin can see every workspace through ``list_all_workspaces`` but
  non-admin callers get an empty list, not 403;
* deleting user A's workspace does not affect user B's parallel workspaces.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _make_user(
    user_id: str,
    *,
    name: str = "user",
    role: str = "user",
    allowed: list[str] | None = None,
) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=None if role == "admin" else (allowed or []),
        max_channels=10,
    )


@pytest.fixture
async def _iso_db(test_db):
    return test_db


@pytest.fixture
async def user_repo_for_iso(_iso_db):
    session = _iso_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


async def _seed_source(test_db, source_id: str, channel_id: str, owner_id: str) -> None:
    session = test_db.ingestion_state_session()
    try:
        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=source_id,
                channel_id=channel_id,
                status="active",
                include_comments=False,
                fail_count=0,
                comments_unavailable=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                owner_id=owner_id,
            )
        )
    finally:
        await session.close()


@pg_only
class TestWorkspaceCrossUserIsolation:
    async def test_list_workspaces_does_not_leak_other_users(self, _iso_db, user_repo_for_iso):
        from tg_parser.mcp_server import create_workspace, list_workspaces

        alice = await user_repo_for_iso.create_user("alice_iso_list")
        bob = await user_repo_for_iso.create_user("bob_iso_list")
        alice_user = _make_user(alice.id)
        bob_user = _make_user(bob.id)

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await create_workspace(name="alice_iso_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            result = await list_workspaces()
        assert {ws.name for ws in result.workspaces} == set()

    async def test_foreign_workspace_id_via_search_returns_empty_no_leak(
        self, _iso_db, user_repo_for_iso
    ):
        """Cross-user workspace_id MUST look identical to an unknown UUID."""
        from tg_parser.mcp_server import create_workspace, search_knowledge_base

        alice = await user_repo_for_iso.create_user("alice_iso_search")
        bob = await user_repo_for_iso.create_user("bob_iso_search")
        alice_user = _make_user(alice.id, allowed=["ch_x"])
        bob_user = _make_user(bob.id, allowed=["ch_x"])
        await _seed_source(_iso_db, "tg:src_iso", "ch_x", alice.id)

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            ws = (await create_workspace(name="alice_iso_search_ws")).workspace

        search_mock = AsyncMock()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)),
            patch("tg_parser.services.retrieval_service.search", search_mock),
        ):
            results = await search_knowledge_base(query="x", workspace_id=ws.id)

        assert results == []
        search_mock.assert_not_called()

    async def test_foreign_workspace_id_via_list_topics_returns_empty(
        self, _iso_db, user_repo_for_iso
    ):
        from tg_parser.mcp_server import create_workspace, list_topics

        alice = await user_repo_for_iso.create_user("alice_iso_lt")
        bob = await user_repo_for_iso.create_user("bob_iso_lt")
        alice_user = _make_user(alice.id)
        bob_user = _make_user(bob.id, allowed=["ch_z"])

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            ws = (await create_workspace(name="alice_iso_lt_ws")).workspace

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            result = await list_topics(workspace_id=ws.id)
        assert result.total == 0
        assert result.items == []

    async def test_admin_sees_every_workspace_via_list_all(self, _iso_db, user_repo_for_iso):
        from tg_parser.mcp_server import create_workspace, list_all_workspaces

        alice = await user_repo_for_iso.create_user("alice_iso_admin")
        bob = await user_repo_for_iso.create_user("bob_iso_admin")
        alice_user = _make_user(alice.id)
        bob_user = _make_user(bob.id)
        admin = _make_user(alice.id, role="admin")

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await create_workspace(name="alice_iso_admin_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            await create_workspace(name="bob_iso_admin_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=admin)):
            result = await list_all_workspaces()

        names = {ws.name for ws in result.workspaces}
        assert "alice_iso_admin_ws" in names
        assert "bob_iso_admin_ws" in names

    async def test_non_admin_list_all_returns_empty_not_403(self, _iso_db, user_repo_for_iso):
        from tg_parser.mcp_server import create_workspace, list_all_workspaces

        alice = await user_repo_for_iso.create_user("alice_iso_403")
        bob = await user_repo_for_iso.create_user("bob_iso_403")
        alice_user = _make_user(alice.id)
        bob_user = _make_user(bob.id)

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await create_workspace(name="alice_iso_403_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            result = await list_all_workspaces()
        assert result.count == 0

    async def test_delete_workspace_does_not_affect_other_user(self, _iso_db, user_repo_for_iso):
        from tg_parser.mcp_server import (
            create_workspace,
            delete_workspace,
            list_workspaces,
        )

        alice = await user_repo_for_iso.create_user("alice_iso_del")
        bob = await user_repo_for_iso.create_user("bob_iso_del")
        alice_user = _make_user(alice.id)
        bob_user = _make_user(bob.id)

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            alice_ws = (await create_workspace(name="alice_iso_del_ws")).workspace
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            await create_workspace(name="bob_iso_del_ws")

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await delete_workspace(workspace_id=alice_ws.id)

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            result = await list_workspaces()
        assert {ws.name for ws in result.workspaces} == {"bob_iso_del_ws"}
