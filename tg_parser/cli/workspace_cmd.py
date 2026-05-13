"""CLI for F4-B Core Workspaces.

Mirrors the MCP surface for power users + on-call ops:

    tg-parser workspace list
    tg-parser workspace create --name "AI/ML" --description "Anthropic, OpenAI"
    tg-parser workspace rename <ws_id> "new name"
    tg-parser workspace delete <ws_id>
    tg-parser workspace add-source <ws_id> --channel <channel_id>
    tg-parser workspace remove-source <ws_id> --channel <channel_id>
    tg-parser workspace list-sources <ws_id>
    tg-parser workspace list-all [--owner-id <user_id>]   # admin only

Notes
-----
``--user <uuid>`` is the F4-A convention for "act on behalf of this user"
(default: system admin) — same shape as :mod:`watchlist_cmd`. Move between
workspaces = ``remove-source`` + ``add-source`` (non-atomic — O-1
deferred to Wave 1 step 3 / Wave 2).
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer

app = typer.Typer(
    name="workspace",
    help="Manage F4-B workspaces (thematic channel collections).",
)


async def _resolve_acting_user(user_arg: str | None) -> Any:
    """Return the ``CurrentUser`` to act as (mirror of watchlist_cmd helper)."""
    from tg_parser.auth.models import CurrentUser
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.config import settings as app_settings
    from tg_parser.services.db_context import user_repo

    if not user_arg:
        return await get_default_admin()
    async with user_repo() as (repo, _db):
        user = await repo.get_by_id(user_arg)
    if user is None:
        raise typer.BadParameter(f"user {user_arg!r} not found")
    allowed: list[str] | None
    if user.role == "admin":
        allowed = None
    else:
        async with user_repo() as (repo2, _db2):
            allowed = await repo2.get_owned_channel_ids(user.id)
    return CurrentUser(
        id=user.id,
        name=user.name,
        role=user.role,
        allowed_channel_ids=allowed,
        max_channels=user.max_channels
        if user.max_channels is not None
        else app_settings.default_max_channels,
    )


def _print_workspace(ws: Any) -> None:
    typer.echo(f"  • {ws.id}")
    typer.echo(f"      name:        {ws.name}")
    typer.echo(f"      owner_id:    {ws.owner_id}")
    if ws.description:
        typer.echo(f"      description: {ws.description}")
    if ws.created_at:
        created_str = (
            ws.created_at.isoformat() if hasattr(ws.created_at, "isoformat") else str(ws.created_at)
        )
        typer.echo(f"      created_at:  {created_str}")


@app.command("list")
def list_workspaces(
    user: str = typer.Option(
        None,
        "--user",
        help="UUID of the user to list workspaces for (default: caller / admin)",
    ),
) -> None:
    """List workspaces owned by ``--user`` (or by the default admin)."""

    async def _run() -> list[Any]:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.list_workspaces(acting)
        finally:
            await Database.close_instance()

    try:
        workspaces = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not workspaces:
        typer.echo("⚠️  Workspaces not found")
        return

    typer.echo(f"📁 Workspaces ({len(workspaces)}):\n")
    for ws in workspaces:
        _print_workspace(ws)
        typer.echo()


@app.command("create")
def create_workspace(
    name: str = typer.Option(..., "--name", help="Workspace name (unique per owner)"),
    description: str = typer.Option(
        "",
        "--description",
        help="Optional free-form description",
    ),
    user: str = typer.Option(
        None,
        "--user",
        help="UUID of the owner (default: admin)",
    ),
) -> None:
    """Create a new workspace."""
    description_arg = description.strip() or None

    async def _run() -> Any:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.create_workspace(
                    acting,
                    name=name,
                    description=description_arg,
                )
        finally:
            await Database.close_instance()

    try:
        ws = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("✅ Workspace создан:")
    _print_workspace(ws)


@app.command("rename")
def rename_workspace(
    workspace_id: str = typer.Argument(..., help="Workspace UUID to rename"),
    new_name: str = typer.Argument(..., help="New name (unique per owner)"),
    user: str = typer.Option(None, "--user", help="UUID of the actor (default: admin)"),
) -> None:
    """Rename a workspace."""

    async def _run() -> Any:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.rename_workspace(acting, workspace_id, new_name)
        finally:
            await Database.close_instance()

    try:
        ws = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("✅ Workspace renamed:")
    _print_workspace(ws)


@app.command("delete")
def delete_workspace(
    workspace_id: str = typer.Argument(..., help="Workspace UUID to delete"),
    user: str = typer.Option(None, "--user", help="UUID of the actor (default: admin)"),
) -> None:
    """Delete a workspace (M2M membership cascades; sources are preserved)."""

    async def _run() -> bool:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.delete_workspace(acting, workspace_id)
        finally:
            await Database.close_instance()

    try:
        existed = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if existed:
        typer.echo(f"✅ Workspace {workspace_id} deleted")
    else:
        typer.echo(f"⚠️  Workspace {workspace_id} delete had no effect")


@app.command("add-source")
def add_source(
    workspace_id: str = typer.Argument(..., help="Workspace UUID"),
    channel: str = typer.Option(..., "--channel", help="channel_id (or @username)"),
    user: str = typer.Option(None, "--user", help="UUID of the actor (default: admin)"),
) -> None:
    """Attach a channel to a workspace (idempotent — duplicates are no-op)."""

    async def _run() -> bool:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database
        from tg_parser.utils.channel_id import normalize_channel_id

        acting = await _resolve_acting_user(user)
        normalized = normalize_channel_id(channel) or channel
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.add_source(acting, workspace_id, normalized)
        finally:
            await Database.close_instance()

    try:
        inserted = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if inserted:
        typer.echo(f"✅ Channel {channel} added to workspace {workspace_id}")
    else:
        typer.echo(f"ℹ️  Channel {channel} was already in workspace {workspace_id}")


@app.command("remove-source")
def remove_source(
    workspace_id: str = typer.Argument(..., help="Workspace UUID"),
    channel: str = typer.Option(..., "--channel", help="channel_id (or @username) to detach"),
    user: str = typer.Option(None, "--user", help="UUID of the actor (default: admin)"),
) -> None:
    """Detach a channel from a workspace (M2M row only; source remains).

    To move a channel between workspaces: ``remove-source`` + ``add-source``.
    Per Q4 R2 / O-1 the move is **not** atomic in MVP.
    """

    async def _run() -> bool:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database
        from tg_parser.utils.channel_id import normalize_channel_id

        acting = await _resolve_acting_user(user)
        normalized = normalize_channel_id(channel) or channel
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.remove_source(acting, workspace_id, normalized)
        finally:
            await Database.close_instance()

    try:
        removed = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if removed:
        typer.echo(f"✅ Channel {channel} removed from workspace {workspace_id}")
    else:
        typer.echo(f"ℹ️  Channel {channel} was not in workspace {workspace_id}")


@app.command("list-sources")
def list_sources(
    workspace_id: str = typer.Argument(..., help="Workspace UUID"),
    user: str = typer.Option(None, "--user", help="UUID of the actor (default: admin)"),
) -> None:
    """List channel_ids attached to a workspace."""

    async def _run() -> list[str]:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.list_workspace_sources(acting, workspace_id)
        finally:
            await Database.close_instance()

    try:
        channels = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not channels:
        typer.echo("⚠️  Workspace has no channels")
        return
    typer.echo(f"📺 Channels in workspace {workspace_id} ({len(channels)}):")
    for ch in channels:
        typer.echo(f"  • {ch}")


@app.command("list-all")
def list_all(
    owner_id: str = typer.Option(None, "--owner-id", help="Optional owner filter"),
    user: str = typer.Option(None, "--user", help="UUID of the actor (default: admin)"),
) -> None:
    """Admin-only: list every workspace in the system."""

    async def _run() -> list[Any]:
        from tg_parser.services.db_context import workspace_repo
        from tg_parser.services.workspace_service import WorkspaceService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with workspace_repo() as (repo, _db):
                service = WorkspaceService(repo)
                return await service.list_all_workspaces(acting, owner_id=owner_id)
        finally:
            await Database.close_instance()

    try:
        workspaces = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not workspaces:
        typer.echo("⚠️  No workspaces found")
        return
    typer.echo(f"📁 All workspaces ({len(workspaces)}):\n")
    for ws in workspaces:
        _print_workspace(ws)
        typer.echo()
