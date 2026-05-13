"""F4-B Core — :class:`WorkspaceService`.

Owner-scoped CRUD for ``workspaces`` plus the ``effective_channel_ids``
resolver — the single point where F4-A ``allowed_channel_ids`` is
intersected with F4-B workspace channel-membership.

Hard invariants (Q1 + Q2 locked semantics, see
``docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md``):

* ``workspace_id is None`` → bit-for-bit F4-A behavior
  (``return user.allowed_channel_ids`` — no repo I/O).
* Unknown / foreign ``workspace_id`` → :class:`WorkspaceNotFound`
  (404-like, never leak existence).
* Valid workspace with empty M2M → ``[]`` (explicit empty list — **NOT**
  ``None``, **NOT** silent fallback to "all channels"; that would be a
  data leak — see hidden gotcha § 3).
* Admin (``user.allowed_channel_ids is None``) → workspace
  channel_ids verbatim (no intersection — admin has no user-scope to
  intersect with).
"""

from __future__ import annotations

import structlog

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import (
    PermissionDenied,
    WorkspaceNotFound,
    assert_workspace_access,
)
from tg_parser.domain.models import Workspace
from tg_parser.storage.ports import WorkspaceRepo

logger = structlog.get_logger(__name__)


class WorkspaceSourceNotFound(Exception):
    """Raised when a channel cannot be resolved to a ``sources`` row.

    Surfaces both ``unknown channel_id`` and ``foreign channel_id``
    (channel belongs to another owner) as a single 404-like error so the
    MCP / CLI surface never leaks existence.
    """

    def __init__(self, message: str = "Channel not found"):
        self.message = message
        super().__init__(message)


class WorkspaceService:
    """Thin service on top of :class:`WorkspaceRepo`.

    All mutating methods enforce ownership via
    :func:`assert_workspace_access`. Admins can target any user's
    workspace (Q2 edge case 3 — mirrors F4-A admin semantics).

    Channel-id translation: the MCP / CLI surface speaks in
    ``channel_id`` (the identifier living in
    ``CurrentUser.allowed_channel_ids``), while ``workspace_sources``
    is FK'd to ``sources.source_id``. The service translates
    ``channel_id`` → ``source_id`` via
    :meth:`WorkspaceRepo.resolve_source_id_for_channel` so the storage
    layer never sees the user-facing identifier.
    """

    def __init__(self, repo: WorkspaceRepo):
        self.repo = repo

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_workspace(
        self,
        user: CurrentUser,
        *,
        name: str,
        description: str | None = None,
    ) -> Workspace:
        """Create a workspace owned by ``user``.

        The :class:`Workspace` Pydantic model already strips + length-checks
        the ``name`` (gotcha § 6). We bounce the request through Pydantic
        first so the service-layer error message is identical regardless of
        whether the rejection came from the schema CheckConstraint or the
        domain validator.
        """
        Workspace(
            id="00000000-0000-0000-0000-000000000000",
            owner_id=user.id,
            name=name,
            description=description,
        )
        cleaned_name = name.strip()
        return await self.repo.create(
            owner_id=user.id,
            name=cleaned_name,
            description=description,
        )

    async def get_workspace(self, user: CurrentUser, workspace_id: str) -> Workspace:
        """Return the workspace if ``user`` can see it, else raise."""
        return await assert_workspace_access(user, workspace_id, repo=self.repo)

    async def list_workspaces(self, user: CurrentUser) -> list[Workspace]:
        """List the caller's own workspaces.

        Admin tooling reaches :meth:`list_all_workspaces` instead; this
        method is consciously user-scoped (Q2 edge case 3 — admin acts as a
        regular user on their own workspaces and uses a dedicated tool for
        cross-user inspection).
        """
        return await self.repo.list_by_owner(user.id)

    async def list_all_workspaces(
        self,
        user: CurrentUser,
        *,
        owner_id: str | None = None,
    ) -> list[Workspace]:
        """Admin-only: list every workspace in the system."""
        if not user.is_admin:
            raise PermissionDenied("list_all_workspaces requires admin role")
        return await self.repo.list_all(owner_id=owner_id)

    async def rename_workspace(
        self,
        user: CurrentUser,
        workspace_id: str,
        new_name: str,
    ) -> Workspace:
        """Rename a workspace after ownership + name validation."""
        Workspace(
            id="00000000-0000-0000-0000-000000000000",
            owner_id=user.id,
            name=new_name,
        )
        await assert_workspace_access(user, workspace_id, repo=self.repo)
        renamed = await self.repo.rename(workspace_id, new_name.strip())
        if renamed is None:
            raise WorkspaceNotFound(f"Workspace {workspace_id} not found")
        return renamed

    async def delete_workspace(self, user: CurrentUser, workspace_id: str) -> bool:
        await assert_workspace_access(user, workspace_id, repo=self.repo)
        return await self.repo.delete(workspace_id)

    # ------------------------------------------------------------------
    # M2M membership
    # ------------------------------------------------------------------

    async def add_source(
        self,
        user: CurrentUser,
        workspace_id: str,
        channel_id: str,
    ) -> bool:
        """Attach a channel to a workspace.

        The caller must own the workspace AND have F4-A access to the
        channel (``channel_id`` ∈ ``user.allowed_channel_ids`` or admin).
        Returns True for a newly-inserted membership row, False if the
        channel was already in the workspace (idempotent ``ON CONFLICT``).
        """
        ws = await assert_workspace_access(user, workspace_id, repo=self.repo)
        if not user.is_admin and (
            user.allowed_channel_ids is None or channel_id not in user.allowed_channel_ids
        ):
            raise PermissionDenied(f"No access to channel {channel_id}")
        source_id = await self._resolve_source_id(ws.owner_id, channel_id, admin=user.is_admin)
        return await self.repo.add_source(workspace_id, source_id)

    async def remove_source(
        self,
        user: CurrentUser,
        workspace_id: str,
        channel_id: str,
    ) -> bool:
        ws = await assert_workspace_access(user, workspace_id, repo=self.repo)
        source_id = await self._resolve_source_id(ws.owner_id, channel_id, admin=user.is_admin)
        return await self.repo.remove_source(workspace_id, source_id)

    async def list_workspace_sources(
        self,
        user: CurrentUser,
        workspace_id: str,
    ) -> list[str]:
        """Return channels (channel_id list) in a workspace — surface-friendly.

        We deliberately return channel_ids rather than source_ids so the
        MCP / CLI surface stays consistent with F4-A
        ``allowed_channel_ids`` semantics.
        """
        await assert_workspace_access(user, workspace_id, repo=self.repo)
        return await self.repo.list_channel_ids(workspace_id)

    async def _resolve_source_id(
        self,
        owner_id: str,
        channel_id: str,
        *,
        admin: bool,
    ) -> str:
        """Translate a user-facing ``channel_id`` into the underlying ``source_id``.

        Scopes the lookup to ``owner_id`` for non-admin callers so that two
        users with the same ``channel_id`` (legacy F4-A behavior) never
        clash. Admin callers fall through to a global lookup.
        """
        source_id = await self.repo.resolve_source_id_for_channel(
            owner_id=None if admin else owner_id,
            channel_id=channel_id,
        )
        if source_id is None:
            raise WorkspaceSourceNotFound(f"Channel {channel_id} not found")
        return source_id

    # ------------------------------------------------------------------
    # Resolver (the core invariant)
    # ------------------------------------------------------------------

    async def effective_channel_ids(
        self,
        user: CurrentUser,
        workspace_id: str | None,
    ) -> list[str] | None:
        """Resolve the surface-level scope for a workspace-aware read tool.

        Semantics matrix:

        ===========================================  =================================
        ``workspace_id``                              return value
        ===========================================  =================================
        ``None``                                      ``user.allowed_channel_ids`` (F4-A)
        unknown / foreign UUID                        raises :class:`WorkspaceNotFound`
        valid + empty workspace                       ``[]`` (explicit empty, NOT None)
        valid + non-empty, admin caller               workspace's ``channel_ids``
        valid + non-empty, non-admin caller           intersection list (may be ``[]``)
        ===========================================  =================================

        ``user.allowed_channel_ids is None`` means F4-A admin scope ("see
        every channel"); for admin we therefore return the workspace's
        channel_ids verbatim (no intersection — there is no user-scope to
        intersect with). Non-admins always get a deterministic list,
        possibly empty.
        """
        if workspace_id is None:
            return user.allowed_channel_ids

        workspace = await assert_workspace_access(user, workspace_id, repo=self.repo)
        workspace_channel_ids = await self.repo.list_channel_ids(workspace.id)

        if user.allowed_channel_ids is None:
            effective = list(workspace_channel_ids)
        else:
            allowed_set = set(user.allowed_channel_ids)
            effective = [c for c in workspace_channel_ids if c in allowed_set]

        logger.debug(
            "workspace_effective_channel_ids",
            user_id=user.id,
            workspace_id=workspace.id,
            workspace_size=len(workspace_channel_ids),
            effective_count=len(effective),
        )
        return effective
