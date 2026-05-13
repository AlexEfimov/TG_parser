"""F4-B Core — :func:`assert_workspace_access` ownership boundary tests.

Q2 edge case 2 + 3: foreign / unknown / admin pass-through semantics live
in the ownership module so MCP + CLI + service share one source of truth.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import WorkspaceNotFound, assert_workspace_access
from tg_parser.domain.models import Workspace
from tg_parser.storage.ports import WorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


class _FakeWorkspaceRepo(WorkspaceRepo):
    """In-memory stub so unit tests can run without Postgres."""

    def __init__(self, workspaces: dict[str, Workspace]):
        self._workspaces = workspaces

    async def get(self, workspace_id: str) -> Workspace | None:
        return self._workspaces.get(workspace_id)

    async def create(self, **_kw: Any) -> Workspace:  # pragma: no cover
        raise NotImplementedError

    async def list_by_owner(self, owner_id: str) -> list[Workspace]:  # pragma: no cover
        return [ws for ws in self._workspaces.values() if ws.owner_id == owner_id]

    async def list_all(self, owner_id: str | None = None) -> list[Workspace]:  # pragma: no cover
        rows = list(self._workspaces.values())
        if owner_id is None:
            return rows
        return [ws for ws in rows if ws.owner_id == owner_id]

    async def rename(
        self, workspace_id: str, new_name: str
    ) -> Workspace | None:  # pragma: no cover
        return None

    async def delete(self, workspace_id: str) -> bool:  # pragma: no cover
        return False

    async def add_source(
        self,
        workspace_id: str,  # noqa: ARG002
        source_id: str,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return False

    async def remove_source(
        self,
        workspace_id: str,  # noqa: ARG002
        source_id: str,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return False

    async def list_source_ids(self, workspace_id: str) -> list[str]:  # pragma: no cover
        return []

    async def list_channel_ids(self, workspace_id: str) -> list[str]:  # pragma: no cover
        return []

    async def resolve_source_id_for_channel(
        self,
        *,
        owner_id: str | None,  # noqa: ARG002
        channel_id: str,
    ) -> str | None:  # pragma: no cover
        return channel_id


def _make_user(*, user_id: str, role: str = "user") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="alice",
        role=role,
        allowed_channel_ids=[] if role != "admin" else None,
        max_channels=10,
    )


def _make_workspace(*, owner_id: str) -> Workspace:
    return Workspace(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        name="ws",
    )


class TestAssertWorkspaceAccess:
    async def test_unknown_workspace_raises_not_found(self) -> None:
        user = _make_user(user_id=str(uuid.uuid4()))
        repo = _FakeWorkspaceRepo({})
        with pytest.raises(WorkspaceNotFound):
            await assert_workspace_access(user, str(uuid.uuid4()), repo=repo)

    async def test_foreign_workspace_raises_not_found_not_permission(self) -> None:
        owner_id = str(uuid.uuid4())
        other_user = _make_user(user_id=str(uuid.uuid4()))
        ws = _make_workspace(owner_id=owner_id)
        repo = _FakeWorkspaceRepo({ws.id: ws})
        with pytest.raises(WorkspaceNotFound):
            await assert_workspace_access(other_user, ws.id, repo=repo)

    async def test_owner_passes(self) -> None:
        owner_id = str(uuid.uuid4())
        user = _make_user(user_id=owner_id)
        ws = _make_workspace(owner_id=owner_id)
        repo = _FakeWorkspaceRepo({ws.id: ws})
        result = await assert_workspace_access(user, ws.id, repo=repo)
        assert result.id == ws.id

    async def test_admin_passes_for_any_workspace(self) -> None:
        owner_id = str(uuid.uuid4())
        admin_id = str(uuid.uuid4())
        admin = _make_user(user_id=admin_id, role="admin")
        ws = _make_workspace(owner_id=owner_id)
        repo = _FakeWorkspaceRepo({ws.id: ws})
        result = await assert_workspace_access(admin, ws.id, repo=repo)
        assert result.id == ws.id
