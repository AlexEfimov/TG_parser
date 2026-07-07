"""CLI for F5-C topic surface (audit history + manual re-summarize).

Companion to the F5-C MCP tools (``get_topic_versions`` /
``force_resummarize``). Runs outside the bot/MCP process so on-call can
introspect or refresh a topic's summary directly:

    tg-parser topic versions <topic_id> [--limit 10]
    tg-parser topic resummarize <topic_id> [--dry-run]

``versions`` is read-only. ``resummarize`` is admin-only and respects
the same advisory-lock semantics as the scheduler hook — if another tick
is already re-summarizing this topic, the command reports
``status=locked`` instead of blocking.
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer

app = typer.Typer(
    name="topic",
    help="Inspect topic summary history and manually trigger F5-C re-summarize.",
)


@app.command("versions")
def versions(
    topic_id: str = typer.Argument(..., help="Topic ID, e.g. topic:tg:channel:post:123"),
    limit: int = typer.Option(10, min=1, max=200, help="Max versions to print (newest first)"),
) -> None:
    """Print the F5-C audit trail for one topic."""

    async def _run() -> dict[str, Any]:
        from tg_parser.services.db_context import resummarization_repos
        from tg_parser.storage.sqlalchemy.database import Database

        try:
            async with resummarization_repos() as (
                card_repo,
                _bundle_repo,
                version_repo,
                _proc_repo,
                _db,
            ):
                card = await card_repo.get_by_id(topic_id)
                if card is None:
                    return {"error": "not_found"}
                versions_list = await version_repo.list_by_topic(topic_id, limit=limit)
                return {
                    "card": card,
                    "versions": versions_list,
                }
        finally:
            await Database.close_instance()

    try:
        payload = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if payload.get("error") == "not_found":
        typer.echo(f"❌ Topic {topic_id} не найден", err=True)
        raise typer.Exit(code=1)

    card = payload["card"]
    versions_list = payload["versions"]

    typer.echo(f"📜 Версии summary для {topic_id}\n")
    typer.echo(f"   • current_version:               {card.summary_version}")
    typer.echo(
        f"   • last_summarized_at:            "
        f"{card.last_summarized_at.isoformat() if card.last_summarized_at else 'never'}"
    )
    typer.echo(f"   • new_items_since_last_summary:  {card.new_items_since_last_summary}")
    typer.echo(f"   • history rows:                  {len(versions_list)} (limit={limit})\n")

    if not versions_list:
        typer.echo("⚠️  История пуста — тема ещё ни разу не пересуммаризировалась.")
        return

    for v in versions_list:
        typer.echo(f"  • v{v.version_no}  ({v.created_at.isoformat()})")
        typer.echo(f"      items_count_at_time: {v.supporting_items_count_at_time}")
        if v.llm_provider or v.llm_model:
            typer.echo(f"      llm:                 {v.llm_provider or '?'}/{v.llm_model or '?'}")
        if v.prompt_version:
            typer.echo(f"      prompt_version:      {v.prompt_version}")
        summary_preview = v.summary if len(v.summary) <= 240 else v.summary[:237] + "..."
        typer.echo(f"      summary:             {summary_preview}")
        typer.echo()


@app.command("resummarize")
def resummarize(
    topic_id: str = typer.Argument(..., help="Topic ID to re-summarize"),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Don't actually re-summarize — just print the candidate context "
            "(card.summary_version, bundle.items count, sources)."
        ),
    ),
) -> None:
    """Manually trigger F5-C re-summarize for one topic.

    Bypasses the N-threshold counter. Subject to the same advisory-lock
    contract as the scheduler hook — concurrent attempts return
    ``status=locked`` instead of blocking.
    """

    async def _dry() -> dict[str, Any]:
        from tg_parser.services.db_context import resummarization_repos
        from tg_parser.storage.sqlalchemy.database import Database

        try:
            async with resummarization_repos() as (
                card_repo,
                bundle_repo,
                _version_repo,
                _proc_repo,
                _db,
            ):
                card = await card_repo.get_by_id(topic_id)
                if card is None:
                    return {"error": "not_found"}
                bundle = await bundle_repo.get_by_topic_id(topic_id)
                return {
                    "card": card,
                    "bundle_items_count": len(bundle.items) if bundle else 0,
                }
        finally:
            await Database.close_instance()

    async def _run() -> dict[str, Any]:
        from tg_parser.services.db_context import resummarization_repos
        from tg_parser.services.resummarization_service import ResummarizationService
        from tg_parser.storage.sqlalchemy.database import Database

        try:
            async with resummarization_repos() as (
                card_repo,
                bundle_repo,
                version_repo,
                proc_repo,
                _db,
            ):
                service = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=version_repo,
                    processed_document_repo=proc_repo,
                )
                try:
                    return await service.resummarize_topic(topic_id)
                finally:
                    await service.aclose()
        finally:
            await Database.close_instance()

    if dry_run:
        try:
            payload = asyncio.run(_dry())
        except Exception as exc:
            typer.echo(f"\n❌ Ошибка: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if payload.get("error") == "not_found":
            typer.echo(f"❌ Topic {topic_id} не найден", err=True)
            raise typer.Exit(code=1)

        card = payload["card"]
        typer.echo(f"🔍 Dry-run для {topic_id}\n")
        typer.echo(f"   • title:                         {card.title}")
        typer.echo(f"   • current_version:               {card.summary_version}")
        typer.echo(f"   • new_items_since_last_summary:  {card.new_items_since_last_summary}")
        typer.echo(f"   • bundle items:                  {payload['bundle_items_count']}")
        typer.echo(f"   • sources:                       {', '.join(card.sources) or '∅'}")
        typer.echo("\n⚠️  --dry-run: LLM не вызывался, версия не записывалась.")
        return

    typer.echo(f"♻️  Re-summarizing {topic_id} ...\n")

    try:
        outcome = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    status = outcome.get("status", "unknown")
    typer.echo(f"   • status:    {status}")
    # Accept both `version_no` (current ResummarizationService contract) and
    # `summary_version` (legacy / future-proof in case the field is renamed
    # to match the topic_cards column).  Without this dual-key read, the
    # CLI silently dropped the version on every successful run because the
    # service returns `version_no`, not `summary_version`.
    new_version = outcome.get("version_no", outcome.get("summary_version"))
    if new_version is not None:
        typer.echo(f"   • new_version: {new_version}")
    if "tokens" in outcome:
        typer.echo(f"   • tokens:    {outcome['tokens']}")
    if "duration_s" in outcome:
        typer.echo(f"   • duration:  {outcome['duration_s']}s")
    if status == "ok":
        typer.echo("\n✅ Готово")
    elif status == "locked":
        typer.echo("\n⚠️  Тема уже пересуммаризируется другим воркером — повторите позже.")
    else:
        typer.echo(f"\n⚠️  Re-summarize не выполнен: {status}")
        raise typer.Exit(code=1)
