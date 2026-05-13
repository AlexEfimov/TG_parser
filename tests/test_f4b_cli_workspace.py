"""F4-B Core — CLI surface tests (Phase 3).

Pure-mock tests using Typer's ``CliRunner`` so they run without Postgres.
Validates command wiring + happy / error paths through the service.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from tg_parser.auth.models import CurrentUser
from tg_parser.cli.workspace_cmd import app as workspace_app
from tg_parser.domain.models import Workspace
from tg_parser.storage.ports import WorkspaceRepo

runner = CliRunner()


class _FakeWorkspaceRepo(WorkspaceRepo):
    """In-memory stub that supports the methods the CLI exercises."""

    def __init__(self) -> None:
        self.workspaces: dict[str, Workspace] = {}
        self.channels: dict[str, list[str]] = {}

    async def get(self, workspace_id: str) -> Workspace | None:
        return self.workspaces.get(workspace_id)

    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        description: str | None = None,
    ) -> Workspace:
        ws = Workspace(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            name=name,
            description=description,
        )
        self.workspaces[ws.id] = ws
        self.channels.setdefault(ws.id, [])
        return ws

    async def list_by_owner(self, owner_id: str) -> list[Workspace]:
        return [ws for ws in self.workspaces.values() if ws.owner_id == owner_id]

    async def list_all(self, owner_id: str | None = None) -> list[Workspace]:
        rows = list(self.workspaces.values())
        if owner_id is None:
            return rows
        return [ws for ws in rows if ws.owner_id == owner_id]

    async def rename(self, workspace_id: str, new_name: str) -> Workspace | None:
        ws = self.workspaces.get(workspace_id)
        if ws is None:
            return None
        renamed = Workspace(
            id=ws.id,
            owner_id=ws.owner_id,
            name=new_name,
            description=ws.description,
        )
        self.workspaces[workspace_id] = renamed
        return renamed

    async def delete(self, workspace_id: str) -> bool:
        return self.workspaces.pop(workspace_id, None) is not None

    async def add_source(self, workspace_id: str, source_id: str) -> bool:
        members = self.channels.setdefault(workspace_id, [])
        if source_id in members:
            return False
        members.append(source_id)
        return True

    async def remove_source(self, workspace_id: str, source_id: str) -> bool:
        members = self.channels.get(workspace_id, [])
        if source_id not in members:
            return False
        members.remove(source_id)
        return True

    async def list_source_ids(self, workspace_id: str) -> list[str]:
        return list(self.channels.get(workspace_id, []))

    async def list_channel_ids(self, workspace_id: str) -> list[str]:
        return list(self.channels.get(workspace_id, []))

    async def resolve_source_id_for_channel(
        self,
        *,
        owner_id: str | None,  # noqa: ARG002
        channel_id: str,
    ) -> str | None:
        return channel_id


def _admin(user_id: str = "admin-1") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _patch_cli(repo: _FakeWorkspaceRepo, *, user: CurrentUser) -> list[Any]:
    @asynccontextmanager
    async def _fake_repo_ctx():
        yield repo, None

    async def _fake_admin() -> CurrentUser:
        return user

    async def _fake_close():
        return None

    return [
        patch("tg_parser.services.db_context.workspace_repo", lambda: _fake_repo_ctx()),
        patch("tg_parser.auth.resolvers.get_default_admin", _fake_admin),
        patch(
            "tg_parser.storage.sqlalchemy.database.Database.close_instance",
            classmethod(lambda cls: _fake_close()),
        ),
    ]


class TestWorkspaceCLI:
    def test_create_workspace_command(self) -> None:
        repo = _FakeWorkspaceRepo()
        with (
            _patch_cli(repo, user=_admin())[0],
            _patch_cli(repo, user=_admin())[1],
            _patch_cli(repo, user=_admin())[2],
        ):
            result = runner.invoke(workspace_app, ["create", "--name", "AI/ML"])
        assert result.exit_code == 0, result.output
        assert "✅" in result.output or "created" in result.output.lower()
        assert len(repo.workspaces) == 1

    def test_list_empty(self) -> None:
        repo = _FakeWorkspaceRepo()
        with (
            _patch_cli(repo, user=_admin())[0],
            _patch_cli(repo, user=_admin())[1],
            _patch_cli(repo, user=_admin())[2],
        ):
            result = runner.invoke(workspace_app, ["list"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "⚠️" in result.output

    def test_create_then_list(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            r1 = runner.invoke(workspace_app, ["create", "--name", "Workspace A"])
            r2 = runner.invoke(workspace_app, ["list"])
        assert r1.exit_code == 0
        assert r2.exit_code == 0
        assert "Workspace A" in r2.output

    def test_create_rejects_blank(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            result = runner.invoke(workspace_app, ["create", "--name", "   "])
        assert result.exit_code != 0

    def test_add_source_then_list_sources(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            create_r = runner.invoke(workspace_app, ["create", "--name", "mem"])
        assert create_r.exit_code == 0
        ws_id = next(iter(repo.workspaces.keys()))

        patches2 = _patch_cli(repo, user=_admin())
        with patches2[0], patches2[1], patches2[2]:
            add_r = runner.invoke(workspace_app, ["add-source", ws_id, "--channel", "ch_x"])
            list_r = runner.invoke(workspace_app, ["list-sources", ws_id])
        assert add_r.exit_code == 0
        assert list_r.exit_code == 0
        assert "ch_x" in list_r.output

    def test_remove_source_no_op(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            runner.invoke(workspace_app, ["create", "--name", "rm"])
        ws_id = next(iter(repo.workspaces.keys()))

        patches2 = _patch_cli(repo, user=_admin())
        with patches2[0], patches2[1], patches2[2]:
            result = runner.invoke(workspace_app, ["remove-source", ws_id, "--channel", "ghost"])
        assert result.exit_code == 0
        assert "was not in" in result.output.lower() or "ℹ️" in result.output

    def test_delete_workspace(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            runner.invoke(workspace_app, ["create", "--name", "trash"])
        ws_id = next(iter(repo.workspaces.keys()))

        patches2 = _patch_cli(repo, user=_admin())
        with patches2[0], patches2[1], patches2[2]:
            del_r = runner.invoke(workspace_app, ["delete", ws_id])
        assert del_r.exit_code == 0
        assert ws_id not in repo.workspaces

    def test_rename_workspace(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            runner.invoke(workspace_app, ["create", "--name", "old"])
        ws_id = next(iter(repo.workspaces.keys()))

        patches2 = _patch_cli(repo, user=_admin())
        with patches2[0], patches2[1], patches2[2]:
            r = runner.invoke(workspace_app, ["rename", ws_id, "new"])
        assert r.exit_code == 0
        assert repo.workspaces[ws_id].name == "new"

    def test_list_all_admin(self) -> None:
        repo = _FakeWorkspaceRepo()
        patches = _patch_cli(repo, user=_admin())
        with patches[0], patches[1], patches[2]:
            runner.invoke(workspace_app, ["create", "--name", "x"])
            r = runner.invoke(workspace_app, ["list-all"])
        assert r.exit_code == 0
        assert "x" in r.output
