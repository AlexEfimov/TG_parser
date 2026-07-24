"""CLI for F6 scheduled digests (admin-shaped surface).

    tg-parser digest add --user <uuid> --chat-id 123 --name "..." \\
        --channels @c1,@c2
    tg-parser digest add --user <uuid> --channel-id @MyDigest --name "..." \\
        --channels @c1,@c2
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer

from tg_parser.cli.watchlist_cmd import _resolve_acting_user, _split_csv

app = typer.Typer(
    name="digest",
    help="Manage scheduled digest subscriptions (F6).",
)


@app.command("add")
def add(
    name: str = typer.Option(..., help="Human label (natural key per owner)"),
    chat_id: int | None = typer.Option(
        None, "--chat-id", help="Telegram chat for delivery (mutually exclusive with --channel-id)"
    ),
    channel_id: str | None = typer.Option(
        None,
        "--channel-id",
        help="Telegram channel for publish-to-channel (mutually exclusive with --chat-id)",
    ),
    channels: str = typer.Option(..., "--channels", help="Comma-separated channel IDs / usernames"),
    cron_expression: str = typer.Option("0 9 * * *", "--cron", help="5-field cron expression"),
    timezone: str = typer.Option("UTC", help="IANA timezone for cron"),
    digest_format: str = typer.Option("summary", "--format", help="summary|bullets|detailed"),
    language: str = typer.Option("ru", help="Output language code"),
    mode: str = typer.Option(
        "channel", "--mode", help="channel (raw-doc digest) | topic (topic-summary delta)"
    ),
    topics: str | None = typer.Option(
        None, "--topics", help="Comma-separated topic ids for --mode topic"
    ),
    user: str = typer.Option(None, "--user", help="Owner UUID (default: system admin)"),
    workspace_id: str | None = typer.Option(None, "--workspace-id", help="Optional workspace UUID"),
) -> None:
    """Create or update a digest subscription (idempotent on (owner, name))."""
    if chat_id is not None and channel_id is not None:
        typer.echo("❌ provide one of --chat-id or --channel-id, not both", err=True)
        raise typer.Exit(code=1)
    if chat_id is None and channel_id is None:
        typer.echo("❌ either --chat-id or --channel-id is required", err=True)
        raise typer.Exit(code=1)

    from tg_parser.domain.models import DigestFormat, DigestMode, TargetChannel, TargetChat

    cli_target = (
        TargetChannel(channel_id=channel_id.strip())
        if channel_id is not None
        else TargetChat(chat_id=chat_id)  # type: ignore[arg-type]
    )

    channel_list = _split_csv(channels)
    if not channel_list:
        typer.echo("❌ --channels must contain at least one entry", err=True)
        raise typer.Exit(code=1)

    try:
        format_enum = DigestFormat(digest_format)
    except ValueError:
        typer.echo(f"❌ invalid --format: {digest_format!r}", err=True)
        raise typer.Exit(code=1) from None

    try:
        mode_enum = DigestMode(mode)
    except ValueError:
        typer.echo(f"❌ invalid --mode: {mode!r} (expected channel|topic)", err=True)
        raise typer.Exit(code=1) from None

    topic_list = _split_csv(topics) if topics else None
    if mode_enum == DigestMode.TOPIC and not topic_list:
        typer.echo("❌ --mode topic requires --topics", err=True)
        raise typer.Exit(code=1)

    workspace_arg = (workspace_id or "").strip() or None

    async def _run() -> Any:
        from tg_parser.auth.ownership import WorkspaceNotFound
        from tg_parser.services.db_context import digest_subscription_repo, workspace_repo
        from tg_parser.services.digest_service import DigestService
        from tg_parser.storage.sqlalchemy.database import Database

        acting = await _resolve_acting_user(user)
        try:
            async with digest_subscription_repo() as (sub_repo, _db):
                if workspace_arg is not None:
                    async with workspace_repo() as (ws_repo_inst, _db2):
                        service = DigestService(
                            processed_repo=None,
                            subscription_repo=sub_repo,
                            prompt_loader=None,
                            llm_client_factory=None,
                            workspace_repo=ws_repo_inst,
                        )
                        try:
                            return await service.subscribe(
                                owner_id=acting.id,
                                target=cli_target,
                                name=name.strip(),
                                channel_ids=channel_list,
                                cron_expression=cron_expression,
                                timezone=timezone,
                                format=format_enum,
                                language=language,
                                mode=mode_enum,
                                topic_ids=topic_list,
                                workspace_id=workspace_arg,
                                is_admin=acting.is_admin,
                            )
                        except WorkspaceNotFound as exc:
                            raise typer.BadParameter(exc.message) from exc
                service = DigestService(
                    processed_repo=None,
                    subscription_repo=sub_repo,
                    prompt_loader=None,
                    llm_client_factory=None,
                    workspace_repo=None,
                )
                return await service.subscribe(
                    owner_id=acting.id,
                    target=cli_target,
                    name=name.strip(),
                    channel_ids=channel_list,
                    cron_expression=cron_expression,
                    timezone=timezone,
                    format=format_enum,
                    language=language,
                    mode=mode_enum,
                    topic_ids=topic_list,
                    workspace_id=None,
                    is_admin=acting.is_admin,
                )
        finally:
            await Database.close_instance()

    dest = f"channel {channel_id}" if channel_id else f"chat_id={chat_id}"
    typer.echo(f"📰 Digest '{name.strip()}' → {dest}\n")

    try:
        result = asyncio.run(_run())
    except typer.BadParameter:
        raise
    except Exception as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(code=1) from exc

    sub = result.subscription
    typer.echo(
        f"✅ {'created' if result.created else 'updated'} id={sub.id} "
        f"changed_fields={result.changed_fields or '[]'}"
    )
