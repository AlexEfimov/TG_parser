"""CLI for the F11 Topic Watchlist (admin-shaped surface).

Mirrors the MCP / bot tools but is intended for power users + on-call:

    tg-parser watchlist add --user <uuid> --chat-id 123 --title "..." \
        --channels @c1,@c2 --keywords k1,k2 --threshold 0.6
    tg-parser watchlist list [--user <uuid>] [--include-inactive]
    tg-parser watchlist remove <interest_id> [--user <uuid>]
    tg-parser watchlist matches <interest_id> [--since 2026-04-25] [--limit 50]

The CLI runs outside the bot process so ``--chat-id`` is mandatory for ``add``
and ``--user`` defaults to the system admin (so ``ops`` can manage interests
on behalf of users when needed).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import typer

app = typer.Typer(
    name="watchlist",
    help="Manage Topic Watchlist interests (F11).",
)


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated list and normalise each token.

    Used for channel IDs and (incidentally) keyword lists. Routes
    every token through ``normalize_channel_id`` so the channel
    handling stays consistent with bot/MCP tools (Session F /
    BUG-003); for keywords this is a no-op for the common case
    (alphanumeric tokens) and only strips an accidental leading
    ``@`` or surrounding quote pair if the user copy-pasted one.
    """
    from tg_parser.utils.channel_id import normalize_channel_id

    if not value:
        return []
    return [n for n in (normalize_channel_id(chunk) for chunk in value.split(",")) if n]


async def _resolve_acting_user(user_arg: str | None) -> Any:
    """Return the ``CurrentUser`` to act as.

    ``--user`` accepts a UUID (admin operates on someone else's behalf). When
    omitted we fall back to the default admin so the CLI is fully usable on
    a freshly bootstrapped install.
    """
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
    return CurrentUser(
        id=user.id,
        name=user.name,
        role=user.role,
        allowed_channel_ids=None if user.role == "admin" else await _user_owned_channels(user.id),
        max_channels=user.max_channels
        if user.max_channels is not None
        else app_settings.default_max_channels,
    )


async def _user_owned_channels(user_id: str) -> list[str]:
    from tg_parser.services.db_context import user_repo

    async with user_repo() as (repo, _db):
        return await repo.get_owned_channel_ids(user_id)


def _print_interest(interest: Any) -> None:
    typer.echo(f"  • {interest.id}")
    typer.echo(f"      title:       {interest.title}")
    typer.echo(f"      user_id:     {interest.user_id}")
    typer.echo(f"      chat_id:     {interest.chat_id}")
    typer.echo(f"      channels:    {', '.join(interest.channel_ids)}")
    if interest.keywords:
        typer.echo(f"      keywords:    {', '.join(interest.keywords)}")
    if interest.exclude_keywords:
        typer.echo(f"      exclude:     {', '.join(interest.exclude_keywords)}")
    typer.echo(f"      threshold:   {interest.threshold}")
    typer.echo(f"      notify_mode: {interest.notify_mode.value}")
    typer.echo(f"      active:      {'yes' if interest.is_active else 'no'}")
    if interest.last_match_at:
        typer.echo(f"      last_match:  {interest.last_match_at.isoformat()}")


@app.command("add")
def add(
    title: str = typer.Option(..., help="Short human label (used in push notifications)"),
    chat_id: int = typer.Option(..., "--chat-id", help="Telegram chat to deliver pushes into"),
    channels: str = typer.Option(..., "--channels", help="Comma-separated channel IDs / usernames"),
    keywords: str = typer.Option("", "--keywords", help="Comma-separated positive keywords"),
    description: str = typer.Option(
        "",
        "--description",
        help="Optional free-form text used as embedding source",
    ),
    exclude_keywords: str = typer.Option(
        "",
        "--exclude-keywords",
        help="Comma-separated negative-filter keywords",
    ),
    threshold: float = typer.Option(0.6, help="Combined-score cutoff in [0, 1]"),
    user: str = typer.Option(
        None,
        "--user",
        help="UUID of the user that owns the interest (default: system admin)",
    ),
    workspace_id: str = typer.Option(
        None,
        "--workspace-id",
        help=(
            "Optional workspace UUID context (ENH-9). Validated against the "
            "acting user's workspaces; admin can pass any UUID."
        ),
    ),
) -> None:
    """Create or update a Topic Watchlist interest (idempotent on (user, title))."""
    if threshold < 0.0 or threshold > 1.0:
        typer.echo(f"❌ threshold must be in [0.0, 1.0], got {threshold}", err=True)
        raise typer.Exit(code=1)

    channel_list = _split_csv(channels)
    if not channel_list:
        typer.echo("❌ --channels must contain at least one entry", err=True)
        raise typer.Exit(code=1)

    keyword_list = _split_csv(keywords)
    exclude_list = _split_csv(exclude_keywords)
    description_arg = description.strip() or None
    workspace_arg = (workspace_id or "").strip() or None

    async def _run() -> Any:
        from tg_parser.auth.ownership import WorkspaceNotFound
        from tg_parser.services.db_context import watchlist_repos, workspace_repo
        from tg_parser.services.watchlist_service import make_watchlist_service
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with watchlist_repos() as (
                interest_repo,
                match_repo,
                processed_doc_repo,
                embedding_repo,
                _db,
            ):
                if workspace_arg is not None:
                    async with workspace_repo() as (ws_repo_inst, _db2):
                        service = make_watchlist_service(
                            interest_repo=interest_repo,
                            match_repo=match_repo,
                            processed_doc_repo=processed_doc_repo,
                            embedding_repo=embedding_repo,
                            workspace_repo=ws_repo_inst,
                        )
                        try:
                            return await service.subscribe(
                                user_id=acting.id,
                                chat_id=chat_id,
                                title=title.strip(),
                                channel_ids=channel_list,
                                keywords=keyword_list,
                                description=description_arg,
                                exclude_keywords=exclude_list,
                                threshold=threshold,
                                workspace_id=workspace_arg,
                                is_admin=acting.is_admin,
                            )
                        except WorkspaceNotFound as exc:
                            raise typer.BadParameter(exc.message) from exc
                        finally:
                            await service.aclose()
                service = make_watchlist_service(
                    interest_repo=interest_repo,
                    match_repo=match_repo,
                    processed_doc_repo=processed_doc_repo,
                    embedding_repo=embedding_repo,
                )
                try:
                    return await service.subscribe(
                        user_id=acting.id,
                        chat_id=chat_id,
                        title=title.strip(),
                        channel_ids=channel_list,
                        keywords=keyword_list,
                        description=description_arg,
                        exclude_keywords=exclude_list,
                        threshold=threshold,
                        workspace_id=None,
                        is_admin=acting.is_admin,
                    )
                finally:
                    await service.aclose()
        finally:
            await Database.close_instance()

    typer.echo(f"🔔 Подписка watchlist '{title.strip()}' для chat_id={chat_id}\n")

    try:
        result = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    verb = "создан" if result.created else "обновлён"
    typer.echo(f"✅ Watchlist {verb}:")
    _print_interest(result.interest)
    if not result.created:
        typer.echo(
            f"      changed:     {', '.join(result.changed_fields) if result.changed_fields else '(no-op)'}"
        )


@app.command("list")
def list_interests(
    user: str = typer.Option(
        None,
        "--user",
        help="UUID of the user to list interests for (default: caller / admin)",
    ),
    include_inactive: bool = typer.Option(
        True,
        "--include-inactive/--active-only",
        help="Include soft-deleted interests in the listing (default: yes)",
    ),
) -> None:
    """List watchlists owned by --user (or every interest when called as admin without --user)."""

    async def _run() -> list[Any]:
        from tg_parser.services.db_context import watchlist_repos
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with watchlist_repos() as (
                interest_repo,
                _match_repo,
                _proc_repo,
                _emb_repo,
                _db,
            ):
                if user:
                    interests = await interest_repo.list_for_user(user)
                elif acting.is_admin:
                    interests = await interest_repo.list_all()
                else:
                    interests = await interest_repo.list_for_user(acting.id)
        finally:
            await Database.close_instance()
        if not include_inactive:
            interests = [i for i in interests if i.is_active]
        return interests

    try:
        interests = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not interests:
        typer.echo("⚠️  Watchlists не найдены")
        return

    typer.echo(f"📋 Watchlists ({len(interests)}):\n")
    for interest in interests:
        _print_interest(interest)
        typer.echo()


@app.command("remove")
def remove(
    interest_id: str = typer.Argument(..., help="Interest UUID to soft-delete"),
    user: str = typer.Option(
        None,
        "--user",
        help="UUID of the user requesting the delete (default: admin)",
    ),
) -> None:
    """Soft-delete a watchlist interest (preserves match history)."""

    async def _run() -> tuple[bool, str | None]:
        from tg_parser.services.db_context import watchlist_repos
        from tg_parser.services.watchlist_service import make_watchlist_service
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with watchlist_repos() as (
                interest_repo,
                match_repo,
                processed_doc_repo,
                embedding_repo,
                _db,
            ):
                service = make_watchlist_service(
                    interest_repo=interest_repo,
                    match_repo=match_repo,
                    processed_doc_repo=processed_doc_repo,
                    embedding_repo=embedding_repo,
                    with_embedding_client=False,
                )
                try:
                    return await service.delete_interest_for_user(
                        interest_id,
                        requesting_user_id=acting.id,
                        is_admin=acting.is_admin,
                    )
                finally:
                    await service.aclose()
        finally:
            await Database.close_instance()

    try:
        deleted, error = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if deleted:
        typer.echo(f"✅ Interest {interest_id} деактивирован (история matches сохранена)")
        return
    typer.echo(f"❌ {error or 'delete failed'}", err=True)
    raise typer.Exit(code=1)


@app.command("matches")
def matches(
    interest_id: str = typer.Argument(..., help="Interest UUID"),
    since: str = typer.Option(
        None,
        "--since",
        help="ISO-8601 datetime cursor (e.g. 2026-04-25 or 2026-04-25T10:00:00)",
    ),
    limit: int = typer.Option(50, help="Max matches to print (most recent first)"),
    user: str = typer.Option(
        None,
        "--user",
        help="UUID of the user requesting the read (default: admin)",
    ),
) -> None:
    """Show matches for an interest (most recent first)."""
    parsed_since: datetime | None = None
    if since:
        try:
            parsed_since = datetime.fromisoformat(since)
        except ValueError as exc:
            typer.echo(f"❌ Неверный формат --since: {since}", err=True)
            raise typer.Exit(code=1) from exc

    async def _run() -> tuple[Any, list[Any]]:
        from tg_parser.services.db_context import watchlist_repos
        from tg_parser.services.watchlist_service import make_watchlist_service
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with watchlist_repos() as (
                interest_repo,
                match_repo,
                processed_doc_repo,
                embedding_repo,
                _db,
            ):
                service = make_watchlist_service(
                    interest_repo=interest_repo,
                    match_repo=match_repo,
                    processed_doc_repo=processed_doc_repo,
                    embedding_repo=embedding_repo,
                    with_embedding_client=False,
                )
                try:
                    interest = await service.get_interest(interest_id)
                    if interest is None:
                        return None, []
                    if not acting.is_admin and interest.user_id != acting.id:
                        return interest, []
                    matches = await service.get_matches(interest_id, since=parsed_since)
                finally:
                    await service.aclose()
        finally:
            await Database.close_instance()
        return interest, matches

    try:
        interest, found = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if interest is None:
        typer.echo(f"❌ Interest {interest_id} не найден", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"📋 Matches для {interest.title!r} (найдено: {len(found)}, лимит: {limit})\n")
    for match in sorted(found, key=lambda m: m.created_at or datetime.min, reverse=True)[:limit]:
        typer.echo(f"  • [{match.created_at.isoformat() if match.created_at else '?'}] ")
        typer.echo(f"      source_ref: {match.source_ref}")
        typer.echo(
            f"      scores: combined={match.combined_score:.3f} "
            f"keyword={match.keyword_score:.3f} semantic={match.semantic_score:.3f}"
        )
        typer.echo(f"      notified:   {'yes' if match.notified else 'no'}")
