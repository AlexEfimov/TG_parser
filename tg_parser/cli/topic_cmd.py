"""CLI for F5-C topic surface (audit history + manual re-summarize).

Companion to the F5-C MCP tools (``get_topic_versions`` /
``force_resummarize``). Runs outside the bot/MCP process so on-call can
introspect or refresh a topic's summary directly:

    tg-parser topic versions <topic_id> [--limit 10]
    tg-parser topic diff <topic_id> [--version-a N] [--version-b N|current]
    tg-parser topic resummarize <topic_id> [--dry-run]

``versions`` and ``diff`` are read-only. ``resummarize`` is admin-only and respects
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


@app.command("diff")
def diff(
    topic_id: str = typer.Argument(..., help="Topic ID, e.g. topic:tg:channel:post:123"),
    version_a: int = typer.Option(
        1,
        "--version-a",
        min=1,
        help="Older (left) side version_no. Default 1 (genesis).",
    ),
    version_b: str = typer.Option(
        "current",
        "--version-b",
        help=(
            "Newer (right) side: a version_no OR the token 'current'/'latest' "
            "(the live card). Default 'current'."
        ),
    ),
) -> None:
    """Diff two versions of a topic's evolving summary (F5-C #15 item #2).

    Companion to ``topic versions`` — shows what *changed* between two
    versions: the ``summary`` text delta (stdlib difflib unified-diff) plus
    ``scope_in`` / ``scope_out`` set deltas (``+`` added / ``-`` removed).

    ``--version-a`` is the older side (archival ``version_no``);
    ``--version-b`` is the newer side, either an archival ``version_no`` or
    the token ``current`` / ``latest`` which reads the live card
    (``topic_cards``, ``summary_version = N``, not stored in the versions
    table). Default = genesis (v1) → current.

    A version reclaimed by the retention policy (ADR-0018 gaps) prints a
    typed not-found and exits 1 (never a traceback). Genesis (v1) and the
    last N are always present.
    """
    version_b_norm = version_b.strip().lower()
    right_is_current = version_b_norm in {"current", "latest"}
    version_b_int: int | None = None
    if not right_is_current:
        try:
            version_b_int = int(version_b)
        except ValueError:
            typer.echo(
                f"❌ --version-b должен быть числом или 'current'/'latest' (получено {version_b!r})",
                err=True,
            )
            raise typer.Exit(code=1) from None
        if version_b_int < 1:
            typer.echo("❌ --version-b должен быть >= 1", err=True)
            raise typer.Exit(code=1)

    async def _run() -> dict[str, Any]:
        from tg_parser.domain.topic_history_diff import (
            diff_topic_summaries,
            snapshot_from_card,
            snapshot_from_version,
        )
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

                if right_is_current:
                    fetched = await version_repo.get_two_versions(topic_id, version_a, version_a)
                    if version_a not in fetched:
                        return {"error": "missing_version", "missing_version": version_a}
                    left = snapshot_from_version(fetched[version_a])
                    right = snapshot_from_card(card)
                else:
                    fetched = await version_repo.get_two_versions(
                        topic_id, version_a, version_b_int
                    )
                    for missing in (version_a, version_b_int):
                        if missing not in fetched:
                            return {"error": "missing_version", "missing_version": missing}
                    left = snapshot_from_version(fetched[version_a])
                    right = snapshot_from_version(fetched[version_b_int])

                return {"diff": diff_topic_summaries(left, right)}
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
    if payload.get("error") == "missing_version":
        mv = payload["missing_version"]
        typer.echo(
            f"❌ Версия v{mv} не найдена (reclaimed by retention policy).",
            err=True,
        )
        raise typer.Exit(code=1)

    result = payload["diff"]
    left_label = result["left"].get("label", f"v{version_a}")
    right_label = result["right"].get("label", version_b)

    typer.echo(f"🔀 Diff summary для {topic_id}")
    typer.echo(f"   • {left_label}  →  {right_label}\n")

    typer.echo("── summary ──")
    if not result["summary_diff"]:
        typer.echo("  (без изменений)")
    else:
        for line in result["summary_diff"]:
            typer.echo(f"  {line}")
    typer.echo()

    for scope_name in ("scope_in", "scope_out"):
        sd = result[scope_name]
        typer.echo(f"── {scope_name} ──")
        if not sd["added"] and not sd["removed"]:
            typer.echo(f"  (без изменений, unchanged={sd['unchanged_count']})")
        else:
            for x in sd["added"]:
                typer.echo(f"  + {x}")
            for x in sd["removed"]:
                typer.echo(f"  - {x}")
            typer.echo(f"  (unchanged={sd['unchanged_count']})")
        typer.echo()


@app.command("purge-versions")
def purge_versions(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Count the rows that WOULD be purged (same predicate incl. "
            "version_no > 1) without deleting anything."
        ),
    ),
    keep_last_n: int | None = typer.Option(
        None,
        "--keep-last-n",
        min=1,
        max=10000,
        help="Recent-floor override (default: RESUMMARIZE_VERSION_KEEP_LAST_N).",
    ),
    retention_days: int | None = typer.Option(
        None,
        "--retention-days",
        min=1,
        max=3650,
        help="Age cutoff (days) override (default: RESUMMARIZE_VERSION_RETENTION_DAYS).",
    ),
) -> None:
    """Hard-DELETE stale ``topic_card_versions`` rows (F5-C #15 item #1, ADR-0018).

    Canonical predicate: a row is removed iff it is (a) outside the newest N
    versions of its topic AND (b) older than M days AND (c) version_no > 1
    (genesis snapshot is never purged). Use ``--dry-run`` first — the count
    uses the exact same predicate as the DELETE.

    Defaults come from Settings; ``--keep-last-n`` / ``--retention-days``
    override them for a manual run. When the effective retention is 0
    (Settings default kill-switch and no ``--retention-days``), nothing is
    purged and the command exits without touching the DB.
    """
    from datetime import UTC, datetime, timedelta

    from tg_parser.config import settings

    eff_keep_last_n = (
        keep_last_n if keep_last_n is not None else (settings.resummarize_version_keep_last_n)
    )
    eff_retention_days = (
        retention_days
        if retention_days is not None
        else (settings.resummarize_version_retention_days)
    )

    if eff_retention_days <= 0:
        typer.echo(
            "⚠️  Retention disabled (RESUMMARIZE_VERSION_RETENTION_DAYS=0 and no "
            "--retention-days). Nothing to purge; DB untouched."
        )
        return

    cutoff = datetime.now(UTC) - timedelta(days=eff_retention_days)

    async def _run() -> dict[str, Any]:
        from tg_parser.services.db_context import resummarization_repos
        from tg_parser.storage.sqlalchemy.database import Database

        try:
            async with resummarization_repos() as (
                _card_repo,
                _bundle_repo,
                version_repo,
                _proc_repo,
                _db,
            ):
                before = await version_repo.count()
                affected = await version_repo.purge_stale(
                    keep_last_n=eff_keep_last_n,
                    older_than=cutoff,
                    dry_run=dry_run,
                )
                after = await version_repo.count()
                return {"before": before, "affected": affected, "after": after}
        finally:
            await Database.close_instance()

    typer.echo("🧹 topic_card_versions retention purge")
    typer.echo(f"   • mode:            {'DRY-RUN (no DELETE)' if dry_run else 'DELETE'}")
    typer.echo(f"   • keep_last_n (N): {eff_keep_last_n}")
    typer.echo(f"   • retention_days:  {eff_retention_days} (cutoff {cutoff.isoformat()})")
    typer.echo("   • predicate:       rn > N AND created_at < cutoff AND version_no > 1\n")

    try:
        payload = asyncio.run(_run())
    except Exception as exc:
        typer.echo(f"\n❌ Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if dry_run:
        typer.echo(f"   • rows total:      {payload['before']}")
        typer.echo(f"   • WOULD purge:     {payload['affected']}")
        typer.echo("\n⚠️  --dry-run: ничего не удалено.")
    else:
        typer.echo(f"   • rows before:     {payload['before']}")
        typer.echo(f"   • purged:          {payload['affected']}")
        typer.echo(f"   • rows after:      {payload['after']}")
        typer.echo("\n✅ Готово (hard-DELETE необратим — восстановление только из backup).")


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
