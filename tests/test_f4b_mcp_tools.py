"""F4-B Core — MCP tool surface tests (Phase 3)."""

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
    name: str = "alice",
    role: str = "user",
    allowed: list[str] | None = None,
    max_channels: int = 10,
) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=None if role == "admin" else (allowed or []),
        max_channels=max_channels,
    )


@pytest.fixture
async def _mcp_db(test_db):
    """Seed minimal users + sources so the MCP tools can resolve ownership."""
    return test_db


@pytest.fixture
async def user_repo_for_mcp(_mcp_db):
    session = _mcp_db.ingestion_state_session()
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
class TestMCPWorkspaceCRUDTools:
    async def test_create_workspace_returns_workspace(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import create_workspace

        owner = await user_repo_for_mcp.create_user("alice_mcp_create")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await create_workspace(name="AI/ML", description="Anthropic")
        assert result.success is True
        assert result.workspace is not None
        assert result.workspace.name == "AI/ML"
        assert result.workspace.owner_id == owner.id

    async def test_create_workspace_rejects_blank(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import create_workspace

        owner = await user_repo_for_mcp.create_user("alice_mcp_blank")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await create_workspace(name="   ")
        assert result.success is False

    async def test_create_workspace_rejects_duplicate(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import create_workspace

        owner = await user_repo_for_mcp.create_user("alice_mcp_dup")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            r1 = await create_workspace(name="dup")
            r2 = await create_workspace(name="dup")
        assert r1.success is True
        assert r2.success is False
        assert "fail" in r2.message.lower() or "duplicate" in r2.message.lower()

    async def test_list_workspaces_filters_to_caller(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import create_workspace, list_workspaces

        alice = await user_repo_for_mcp.create_user("alice_mcp_list")
        bob = await user_repo_for_mcp.create_user("bob_mcp_list")
        alice_user = _make_user(alice.id, allowed=[])
        bob_user = _make_user(bob.id, allowed=[])

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await create_workspace(name="alice_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            await create_workspace(name="bob_ws")
            result = await list_workspaces()
        assert {ws.name for ws in result.workspaces} == {"bob_ws"}

    async def test_rename_workspace_404_on_unknown(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import rename_workspace

        owner = await user_repo_for_mcp.create_user("alice_mcp_rn")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await rename_workspace(
                workspace_id="00000000-0000-0000-0000-000000000999",
                new_name="x",
            )
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_delete_workspace_owner_only_for_non_admin(self, _mcp_db, user_repo_for_mcp):
        """Foreign workspace must not be deletable by another user."""
        from tg_parser.mcp_server import create_workspace, delete_workspace

        alice = await user_repo_for_mcp.create_user("alice_del")
        bob = await user_repo_for_mcp.create_user("bob_del")
        alice_user = _make_user(alice.id, allowed=[])
        bob_user = _make_user(bob.id, allowed=[])

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            created = await create_workspace(name="alice_del_ws")
        assert created.success is True
        target_id = created.workspace.id

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            result = await delete_workspace(workspace_id=target_id)
        assert result.success is False
        assert "not found" in result.message.lower()


@pg_only
class TestMCPWorkspaceMembershipTools:
    async def test_add_and_remove_source_idempotent(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import (
            add_workspace_source,
            create_workspace,
            list_workspace_sources,
            remove_workspace_source,
        )

        owner = await user_repo_for_mcp.create_user("alice_mem")
        await _seed_source(_mcp_db, "tg:src_mcp", "ch_mcp", owner.id)
        user = _make_user(owner.id, allowed=["ch_mcp"])

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            ws = (await create_workspace(name="mem_ws")).workspace
            add_r1 = await add_workspace_source(workspace_id=ws.id, channel_id="ch_mcp")
            add_r2 = await add_workspace_source(workspace_id=ws.id, channel_id="ch_mcp")
            listed = await list_workspace_sources(workspace_id=ws.id)
            rm_r1 = await remove_workspace_source(workspace_id=ws.id, channel_id="ch_mcp")
            rm_r2 = await remove_workspace_source(workspace_id=ws.id, channel_id="ch_mcp")

        assert add_r1.success is True and add_r1.changed is True
        assert add_r2.success is True and add_r2.changed is False
        assert listed.channel_ids == ["ch_mcp"]
        assert rm_r1.success is True and rm_r1.changed is True
        assert rm_r2.success is True and rm_r2.changed is False

    async def test_add_source_denies_non_accessible_channel(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import add_workspace_source, create_workspace

        owner = await user_repo_for_mcp.create_user("alice_deny")
        user = _make_user(owner.id, allowed=["only_this"])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            ws = (await create_workspace(name="deny_ws")).workspace
            result = await add_workspace_source(workspace_id=ws.id, channel_id="forbidden")
        assert result.success is False
        assert "no access" in result.message.lower() or "not found" in result.message.lower()

    async def test_list_workspace_sources_unknown_workspace_returns_empty(
        self, _mcp_db, user_repo_for_mcp
    ):
        from tg_parser.mcp_server import list_workspace_sources

        owner = await user_repo_for_mcp.create_user("alice_emp")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await list_workspace_sources(
                workspace_id="00000000-0000-0000-0000-000000000999"
            )
        assert result.count == 0
        assert result.channel_ids == []


@pg_only
class TestMCPListAllWorkspaces:
    async def test_admin_sees_every_workspace(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import create_workspace, list_all_workspaces

        alice = await user_repo_for_mcp.create_user("alice_la")
        bob = await user_repo_for_mcp.create_user("bob_la")
        alice_user = _make_user(alice.id, allowed=[])
        bob_user = _make_user(bob.id, allowed=[])
        admin = _make_user(alice.id, role="admin")

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await create_workspace(name="alice_la_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            await create_workspace(name="bob_la_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=admin)):
            result = await list_all_workspaces()
        names = {ws.name for ws in result.workspaces}
        assert "alice_la_ws" in names
        assert "bob_la_ws" in names

    async def test_non_admin_gets_empty_list_not_403(self, _mcp_db, user_repo_for_mcp):
        from tg_parser.mcp_server import create_workspace, list_all_workspaces

        alice = await user_repo_for_mcp.create_user("alice_403")
        bob = await user_repo_for_mcp.create_user("bob_403")
        alice_user = _make_user(alice.id, allowed=[])
        bob_user = _make_user(bob.id, allowed=[])

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=alice_user)):
            await create_workspace(name="alice_403_ws")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)):
            result = await list_all_workspaces()
        assert result.count == 0
        assert result.workspaces == []
