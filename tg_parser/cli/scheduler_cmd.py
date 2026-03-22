"""
CLI commands for the incremental-pipeline scheduler.

Session 30: ``tg-parser scheduler start|status|run-once``
"""

import asyncio

import typer

app = typer.Typer(
    name="scheduler",
    help="Manage the incremental-pipeline scheduler",
)


@app.command("run-once")
def run_once(
    source: str = typer.Option(
        None, help="Run for a single source (default: all active)"
    ),
    output_dir: str = typer.Option("./output", "--out", help="Export output directory"),
) -> None:
    """
    One-shot incremental pipeline run for active sources (or a single source).
    """
    from tg_parser.services.scheduler_service import (
        run_incremental_for_all_sources,
        run_incremental_for_source,
    )

    if source:
        typer.echo(f"🔄 Running incremental pipeline for source: {source}")
        stats = asyncio.run(run_incremental_for_source(source, output_dir=output_dir))
        typer.echo("\n✅ Pipeline completed:")
        _print_pipeline_stats(stats)
    else:
        typer.echo("🔄 Running incremental pipeline for all active sources...")
        result = asyncio.run(run_incremental_for_all_sources(output_dir=output_dir))
        typer.echo("\n✅ Incremental pipeline completed:")
        typer.echo(f"   • Sources total: {result['sources_total']}")
        typer.echo(f"   • Succeeded: {result['sources_succeeded']}")
        typer.echo(f"   • Failed: {result['sources_failed']}")
        typer.echo(f"   • New messages: {result['total_new_messages']}")
        typer.echo(f"   • Processed: {result['total_processed']}")
        if result.get("retopicized_sources"):
            typer.echo(
                f"   • Retopicized: {', '.join(result['retopicized_sources'])}"
            )
        typer.echo(f"   • Duration: {result['duration_seconds']:.2f}s")
        if result.get("errors"):
            typer.echo("\n⚠️  Errors:")
            for sid, err in result["errors"].items():
                typer.echo(f"   • {sid}: {err}")


@app.command("start")
def start(
    interval: int = typer.Option(
        None,
        help="Poll interval in seconds (default: from settings / 3600s)",
    ),
) -> None:
    """
    Start the scheduler in daemon mode (blocks until SIGTERM/SIGINT).
    """
    from tg_parser.config import settings
    from tg_parser.services.scheduler_service import run_scheduler_blocking

    effective_interval = interval or settings.scheduler_default_interval
    typer.echo(f"🕒 Starting scheduler daemon (interval={effective_interval}s)")
    typer.echo("   Press Ctrl+C to stop\n")
    run_scheduler_blocking(interval_seconds=effective_interval)
    typer.echo("\n✅ Scheduler stopped")


@app.command("status")
def status() -> None:
    """
    Show current scheduler configuration and source statuses.
    """
    from tg_parser.services.scheduler_service import get_scheduler_status

    info = asyncio.run(get_scheduler_status())

    typer.echo("📊 Scheduler status:\n")
    typer.echo(f"   Enabled:            {info['scheduler_enabled']}")
    typer.echo(f"   Default interval:   {info['default_interval_seconds']}s")
    typer.echo(f"   Retopicize after:   {info['retopicize_threshold']} new docs")
    typer.echo(f"\n   Sources ({len(info['sources'])}):")

    if not info["sources"]:
        typer.echo("     (no sources configured)")
        return

    for src in info["sources"]:
        status_icon = {"active": "🟢", "paused": "🟡", "error": "🔴"}.get(
            src["status"], "⚪"
        )
        typer.echo(
            f"     {status_icon} {src['source_id']}  "
            f"channel={src['channel_id']}  "
            f"interval={src['poll_interval_seconds']}s  "
            f"fails={src['fail_count']}"
        )
        if src["last_success_at"]:
            typer.echo(f"        last success: {src['last_success_at']}")
        if src["last_error"]:
            typer.echo(f"        last error:   {src['last_error']}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_pipeline_stats(stats: dict) -> None:
    """Pretty-print pipeline run stats."""
    if stats.get("ingest"):
        typer.echo(f"   📥 Ingestion: posts={stats['ingest']['posts_collected']}, "
                    f"comments={stats['ingest']['comments_collected']}")
    if stats.get("process"):
        typer.echo(f"   ⚙️  Processing: processed={stats['process']['processed_count']}, "
                    f"failed={stats['process']['failed_count']}")
    if stats.get("topicize"):
        typer.echo(f"   🏷️  Topicization: topics={stats['topicize']['topics_count']}, "
                    f"bundles={stats['topicize']['bundles_count']}")
    if stats.get("export"):
        typer.echo(f"   📤 Export: kb_entries={stats['export']['kb_entries_count']}, "
                    f"topics={stats['export']['topics_count']}")
    typer.echo(f"   ⏱️  Duration: {stats.get('total_duration_seconds', 0):.2f}s")
