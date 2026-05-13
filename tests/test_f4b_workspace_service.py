"""F4-B Core — :class:`WorkspaceService` tests (Phase 2).

Covers the resolver matrix from
``docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`` § Q2/Q4:

* ``workspace_id is None`` → F4-A behavior, no repo I/O.
* Unknown workspace → :class:`WorkspaceNotFound`.
* Foreign workspace (different owner, non-admin) → :class:`WorkspaceNotFound`.
* Valid empty workspace → ``[]`` (NOT ``None``, NOT silent "all").
* Valid + overlap → intersection list.
* Admin (``allowed_channel_ids is None``) → workspace channel_ids verbatim.

The Postgres-backed leg exercises CRUD + idempotent ``add_source`` /
``remove_source`` through the service interface.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import (
    PermissionDenied,
    WorkspaceNotFound,
)
from tg_parser.domain.models import Workspace
from tg_parser.services.workspace_service import WorkspaceService
from tg_parser.storage.ports import Source, WorkspaceRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ============================================================================
# Pure-logic resolver matrix (in-memory fake repo)
# ============================================================================


class _FakeWorkspaceRepo(WorkspaceRepo):
    def __init__(
        self,
        workspaces: dict[str, Workspace],
        channels_by_workspace: dict[str, list[str]],
    ):
        self._workspaces = workspaces
        self._channels = channels_by_workspace
        self.list_channel_ids_calls = 0

    async def get(self, workspace_id: str) -> Workspace | None:
        return self._workspaces.get(workspace_id)

    async def create(self, **_kw: Any) -> Workspace:  # pragma: no cover
        raise NotImplementedError

    async def list_by_owner(self, owner_id: str) -> list[Workspace]:
        return [ws for ws in self._workspaces.values() if ws.owner_id == owner_id]

    async def list_all(self, owner_id: str | None = None) -> list[Workspace]:
        rows = list(self._workspaces.values())
        if owner_id is None:
            return rows
        return [ws for ws in rows if ws.owner_id == owner_id]

    async def rename(
        self, workspace_id: str, new_name: str
    ) -> Workspace | None:  # pragma: no cover
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            return None
        renamed = Workspace(
            id=ws.id,
            owner_id=ws.owner_id,
            name=new_name,
            description=ws.description,
        )
        self._workspaces[workspace_id] = renamed
        return renamed

    async def delete(self, workspace_id: str) -> bool:
        return self._workspaces.pop(workspace_id, None) is not None

    async def add_source(
        self,
        workspace_id: str,
        source_id: str,
    ) -> bool:
        members = self._channels.setdefault(workspace_id, [])
        if source_id in members:
            return False
        members.append(source_id)
        return True

    async def remove_source(self, workspace_id: str, source_id: str) -> bool:
        members = self._channels.get(workspace_id, [])
        if source_id not in members:
            return False
        members.remove(source_id)
        return True

    async def list_source_ids(self, workspace_id: str) -> list[str]:
        return list(self._channels.get(workspace_id, []))

    async def list_channel_ids(self, workspace_id: str) -> list[str]:
        self.list_channel_ids_calls += 1
        return list(self._channels.get(workspace_id, []))

    async def resolve_source_id_for_channel(
        self,
        *,
        owner_id: str | None,  # noqa: ARG002
        channel_id: str,
    ) -> str | None:
        return channel_id


def _make_user(
    *,
    user_id: str | None = None,
    role: str = "user",
    allowed: list[str] | None = None,
) -> CurrentUser:
    return CurrentUser(
        id=user_id or str(uuid.uuid4()),
        name="alice",
        role=role,
        allowed_channel_ids=allowed if role != "admin" else None,
        max_channels=10,
    )


def _make_workspace(owner_id: str, name: str = "ws") -> Workspace:
    return Workspace(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        name=name,
    )


class TestEffectiveChannelIdsResolver:
    async def test_none_workspace_returns_user_allowed_channel_ids(self) -> None:
        user = _make_user(allowed=["ch1", "ch2"])
        repo = _FakeWorkspaceRepo({}, {})
        service = WorkspaceService(repo)
        result = await service.effective_channel_ids(user, None)
        assert result == ["ch1", "ch2"]
        assert repo.list_channel_ids_calls == 0  # no repo I/O on F4-A fallback

    async def test_unknown_workspace_raises_not_found(self) -> None:
        user = _make_user(allowed=["ch1"])
        repo = _FakeWorkspaceRepo({}, {})
        service = WorkspaceService(repo)
        with pytest.raises(WorkspaceNotFound):
            await service.effective_channel_ids(user, str(uuid.uuid4()))

    async def test_foreign_workspace_raises_not_found(self) -> None:
        owner_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        ws = _make_workspace(owner_id)
        user = _make_user(user_id=other_id, allowed=["ch1"])
        repo = _FakeWorkspaceRepo({ws.id: ws}, {ws.id: ["ch1"]})
        service = WorkspaceService(repo)
        with pytest.raises(WorkspaceNotFound):
            await service.effective_channel_ids(user, ws.id)

    async def test_empty_workspace_returns_explicit_empty_not_none(self) -> None:
        owner_id = str(uuid.uuid4())
        ws = _make_workspace(owner_id)
        user = _make_user(user_id=owner_id, allowed=["ch1", "ch2"])
        repo = _FakeWorkspaceRepo({ws.id: ws}, {ws.id: []})
        service = WorkspaceService(repo)
        result = await service.effective_channel_ids(user, ws.id)
        assert result == []
        assert result is not None  # hidden gotcha § 3: NOT silent fallback

    async def test_intersection_filters_out_non_owned_channels(self) -> None:
        owner_id = str(uuid.uuid4())
        ws = _make_workspace(owner_id)
        user = _make_user(user_id=owner_id, allowed=["ch1", "ch2"])
        repo = _FakeWorkspaceRepo({ws.id: ws}, {ws.id: ["ch1", "ch_foreign"]})
        service = WorkspaceService(repo)
        result = await service.effective_channel_ids(user, ws.id)
        assert result == ["ch1"]

    async def test_admin_returns_workspace_channels_verbatim(self) -> None:
        owner_id = str(uuid.uuid4())
        ws = _make_workspace(owner_id)
        admin = _make_user(role="admin")
        repo = _FakeWorkspaceRepo({ws.id: ws}, {ws.id: ["ch1", "ch2"]})
        service = WorkspaceService(repo)
        result = await service.effective_channel_ids(admin, ws.id)
        assert result == ["ch1", "ch2"]


class TestServiceCreateAndOwnership:
    async def test_create_strips_name(self) -> None:
        owner_id = str(uuid.uuid4())
        user = _make_user(user_id=owner_id, allowed=[])

        captured: dict[str, Any] = {}

        class _StubRepo(_FakeWorkspaceRepo):
            async def create(  # type: ignore[override]
                self,
                *,
                owner_id: str,
                name: str,
                description: str | None = None,
            ) -> Workspace:
                captured["name"] = name
                captured["owner_id"] = owner_id
                return Workspace(
                    id=str(uuid.uuid4()),
                    owner_id=owner_id,
                    name=name,
                    description=description,
                )

        service = WorkspaceService(_StubRepo({}, {}))
        await service.create_workspace(user, name="  AI/ML  ")
        assert captured["name"] == "AI/ML"
        assert captured["owner_id"] == owner_id

    async def test_create_rejects_blank_name(self) -> None:
        user = _make_user(allowed=[])
        service = WorkspaceService(_FakeWorkspaceRepo({}, {}))
        with pytest.raises(ValueError):
            await service.create_workspace(user, name="   ")

    async def test_list_all_workspaces_requires_admin(self) -> None:
        user = _make_user(allowed=[])
        service = WorkspaceService(_FakeWorkspaceRepo({}, {}))
        with pytest.raises(PermissionDenied):
            await service.list_all_workspaces(user)

    async def test_admin_can_list_all(self) -> None:
        admin = _make_user(role="admin")
        owner_id = str(uuid.uuid4())
        ws = _make_workspace(owner_id)
        service = WorkspaceService(_FakeWorkspaceRepo({ws.id: ws}, {}))
        result = await service.list_all_workspaces(admin)
        assert len(result) == 1

    async def test_add_source_requires_user_channel_access(self) -> None:
        owner_id = str(uuid.uuid4())
        ws = _make_workspace(owner_id)
        user = _make_user(user_id=owner_id, allowed=["ch_ok"])
        repo = _FakeWorkspaceRepo({ws.id: ws}, {})
        service = WorkspaceService(repo)
        with pytest.raises(PermissionDenied):
            await service.add_source(user, ws.id, "ch_foreign")


# ============================================================================
# Hidden gotcha § 4 / Q4 R2 — move = non-atomic remove + add
# ============================================================================


class TestMoveSourceComposition:
    """Hidden gotcha § 4 of the start prompt: ``move_workspace_source`` is NOT
    a single atomic operation in MVP — clients compose ``remove_source`` +
    ``add_source``. These tests pin the *compositional* contract so that a
    future drift in either primitive (e.g. silently turning ``remove_source``
    into a no-op while leaving the M2M row in place) cannot pass review."""

    async def _make_service_with_two_workspaces(
        self,
    ) -> tuple[WorkspaceService, CurrentUser, Workspace, Workspace, _FakeWorkspaceRepo]:
        owner_id = str(uuid.uuid4())
        ws_a = _make_workspace(owner_id, name="src_ws")
        ws_b = _make_workspace(owner_id, name="dst_ws")
        user = _make_user(user_id=owner_id, allowed=["ch_move"])
        repo = _FakeWorkspaceRepo(
            {ws_a.id: ws_a, ws_b.id: ws_b},
            {ws_a.id: ["ch_move"], ws_b.id: []},
        )
        return WorkspaceService(repo), user, ws_a, ws_b, repo

    async def test_remove_then_add_moves_channel_between_workspaces(self) -> None:
        """After ``remove_source(A) + add_source(B)`` channel must be only in B."""
        svc, user, ws_a, ws_b, repo = await self._make_service_with_two_workspaces()

        assert await svc.list_workspace_sources(user, ws_a.id) == ["ch_move"]
        assert await svc.list_workspace_sources(user, ws_b.id) == []

        removed = await svc.remove_source(user, ws_a.id, "ch_move")
        assert removed is True
        inserted = await svc.add_source(user, ws_b.id, "ch_move")
        assert inserted is True

        assert await svc.list_workspace_sources(user, ws_a.id) == []
        assert await svc.list_workspace_sources(user, ws_b.id) == ["ch_move"]

    async def test_gap_window_makes_channel_invisible_in_both_workspaces(self) -> None:
        """Between the two calls the channel is in **neither** workspace.

        Pin this — it's the documented non-atomicity (Q4 R2 / O-1). If a
        future change accidentally introduced an atomic move, this test
        would fail and the contract would need to be re-evaluated (and the
        documentation in ``add_workspace_source`` + MCP descriptions
        updated).
        """
        svc, user, ws_a, ws_b, _ = await self._make_service_with_two_workspaces()
        await svc.remove_source(user, ws_a.id, "ch_move")
        assert await svc.list_workspace_sources(user, ws_a.id) == []
        assert await svc.list_workspace_sources(user, ws_b.id) == []

    async def test_effective_channel_ids_observes_move(self) -> None:
        """End-to-end: resolver flips the effective scope after a move."""
        svc, user, ws_a, ws_b, _ = await self._make_service_with_two_workspaces()
        assert await svc.effective_channel_ids(user, ws_a.id) == ["ch_move"]
        assert await svc.effective_channel_ids(user, ws_b.id) == []

        await svc.remove_source(user, ws_a.id, "ch_move")
        await svc.add_source(user, ws_b.id, "ch_move")

        assert await svc.effective_channel_ids(user, ws_a.id) == []
        assert await svc.effective_channel_ids(user, ws_b.id) == ["ch_move"]


# ============================================================================
# Postgres integration legs
# ============================================================================


@pytest.fixture
async def workspace_service_pg(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield WorkspaceService(SAWorkspaceRepo(session)), test_db
    finally:
        await session.close()


@pytest.fixture
async def user_repo_pg(test_db):
    session = test_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


async def _create_source(test_db, source_id: str, channel_id: str, owner_id: str) -> None:
    session = test_db.ingestion_state_session()
    try:
        from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo

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
class TestWorkspaceServicePostgresE2E:
    async def test_create_get_rename_delete_roundtrip(self, workspace_service_pg, user_repo_pg):
        service, _ = workspace_service_pg
        db_user = await user_repo_pg.create_user("alice_svc")
        user = CurrentUser(
            id=db_user.id,
            name="alice",
            role="user",
            allowed_channel_ids=[],
            max_channels=10,
        )
        ws = await service.create_workspace(user, name="AI/ML", description="desc")
        assert ws.name == "AI/ML"
        fetched = await service.get_workspace(user, ws.id)
        assert fetched.id == ws.id
        renamed = await service.rename_workspace(user, ws.id, "AI")
        assert renamed.name == "AI"
        existed = await service.delete_workspace(user, ws.id)
        assert existed is True
        with pytest.raises(WorkspaceNotFound):
            await service.get_workspace(user, ws.id)

    async def test_effective_channel_ids_e2e_intersection(
        self,
        workspace_service_pg,
        user_repo_pg,
    ):
        service, db = workspace_service_pg
        db_user = await user_repo_pg.create_user("alice_ec")
        await _create_source(db, "tg:ch_owned_a", "ch_owned_a", db_user.id)
        await _create_source(db, "tg:ch_owned_b", "ch_owned_b", db_user.id)
        user = CurrentUser(
            id=db_user.id,
            name="alice",
            role="user",
            allowed_channel_ids=["ch_owned_a", "ch_owned_b"],
            max_channels=10,
        )
        ws = await service.create_workspace(user, name="ec_ws")
        await service.add_source(user, ws.id, "ch_owned_a")
        effective = await service.effective_channel_ids(user, ws.id)
        assert effective == ["ch_owned_a"]
        none_effective = await service.effective_channel_ids(user, None)
        assert none_effective == user.allowed_channel_ids
