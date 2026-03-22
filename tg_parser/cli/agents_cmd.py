"""
CLI commands for agent observability.

Phase 3C: Agent monitoring and cleanup commands.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Optional

import typer

from tg_parser.config import settings

logger = logging.getLogger(__name__)

# Create Typer app for agents subcommand group
app = typer.Typer(
    name="agents",
    help="Agent monitoring and management commands",
)


async def _get_persistence_and_db():
    """Get AgentPersistence instance with all repositories and database."""
    from tg_parser.services._wiring import (
        create_agent_persistence,
        create_processing_engine,
        create_session_factory,
    )

    engine = create_processing_engine()
    session_factory = create_session_factory(engine)
    persistence = create_agent_persistence(session_factory)
    return persistence, engine


@app.command("list")
def list_agents(
    agent_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by agent type"),
    active_only: bool = typer.Option(False, "--active", help="Show only active agents"),
):
    """
    List all registered agents.
    
    Shows agent name, type, capabilities, and basic statistics.
    """
    async def _list():
        persistence, engine = await _get_persistence_and_db()
        try:
            agents = await persistence.list_all_agent_states(agent_type)
            
            if active_only:
                agents = [a for a in agents if a.is_active]
            
            return agents
        finally:
            await engine.dispose()
    
    agents = asyncio.run(_list())
    
    if not agents:
        typer.echo("No agents found.")
        return
    
    typer.echo(f"\n📋 Registered Agents ({len(agents)})")
    typer.echo("=" * 70)
    
    for agent in agents:
        status = "🟢" if agent.is_active else "🔴"
        
        typer.echo(f"\n{status} {agent.name}")
        typer.echo(f"   Type: {agent.agent_type}")
        typer.echo(f"   Version: {agent.version}")
        if agent.capabilities:
            typer.echo(f"   Capabilities: {', '.join(agent.capabilities)}")
        if agent.model:
            typer.echo(f"   Model: {agent.model}")
        if agent.provider:
            typer.echo(f"   Provider: {agent.provider}")
        
        # Statistics
        typer.echo(f"   Tasks: {agent.total_tasks_processed} | Errors: {agent.total_errors}")
        if agent.avg_processing_time_ms > 0:
            typer.echo(f"   Avg Time: {agent.avg_processing_time_ms:.1f}ms")
        if agent.last_used_at:
            typer.echo(f"   Last Used: {agent.last_used_at.isoformat()}")
    
    typer.echo()


@app.command("status")
def agent_status(
    name: str = typer.Argument(..., help="Agent name"),
    days: int = typer.Option(30, "--days", "-d", help="Statistics period in days"),
):
    """
    Show detailed status and statistics for an agent.
    """
    async def _status():
        persistence, engine = await _get_persistence_and_db()
        try:
            # Get agent state
            state = await persistence.load_agent_state(name)
            if not state:
                return None, None
            
            # Get summary statistics
            summary = await persistence.get_agent_summary(name, days=days)
            
            return state, summary
        finally:
            await engine.dispose()
    
    state, summary = asyncio.run(_status())
    
    if not state:
        typer.echo(f"❌ Agent '{name}' not found.", err=True)
        raise typer.Exit(code=1)
    
    status_icon = "🟢" if state.is_active else "🔴"
    
    typer.echo(f"\n{status_icon} Agent: {state.name}")
    typer.echo("=" * 60)
    
    # Basic info
    typer.echo("\n📌 Configuration:")
    typer.echo(f"   Type: {state.agent_type}")
    typer.echo(f"   Version: {state.version}")
    typer.echo(f"   Description: {state.description or 'N/A'}")
    if state.capabilities:
        typer.echo(f"   Capabilities: {', '.join(state.capabilities)}")
    if state.model:
        typer.echo(f"   Model: {state.model}")
    if state.provider:
        typer.echo(f"   Provider: {state.provider}")
    
    # Lifetime statistics
    typer.echo("\n📊 Lifetime Statistics:")
    typer.echo(f"   Total Tasks: {state.total_tasks_processed}")
    typer.echo(f"   Total Errors: {state.total_errors}")
    if state.total_tasks_processed > 0:
        error_rate = (state.total_errors / state.total_tasks_processed) * 100
        typer.echo(f"   Error Rate: {error_rate:.1f}%")
    typer.echo(f"   Avg Processing Time: {state.avg_processing_time_ms:.1f}ms")
    
    # Summary for period
    if summary:
        typer.echo(f"\n📈 Last {days} Days:")
        typer.echo(f"   Tasks: {summary.get('total_tasks', 0)}")
        typer.echo(f"   Successful: {summary.get('successful_tasks', 0)}")
        typer.echo(f"   Failed: {summary.get('failed_tasks', 0)}")
        if summary.get('total_tasks', 0) > 0:
            success_rate = summary.get('success_rate', 0) * 100
            typer.echo(f"   Success Rate: {success_rate:.1f}%")
        typer.echo(f"   Avg Time: {summary.get('avg_processing_time_ms', 0):.1f}ms")
        if summary.get('by_task_type'):
            typer.echo(f"   Task Types: {', '.join(summary['by_task_type'].keys())}")
    
    # Timestamps
    typer.echo("\n🕐 Timestamps:")
    typer.echo(f"   Created: {state.created_at.isoformat()}")
    typer.echo(f"   Updated: {state.updated_at.isoformat()}")
    if state.last_used_at:
        typer.echo(f"   Last Used: {state.last_used_at.isoformat()}")
    
    typer.echo()


@app.command("history")
def agent_history(
    name: str = typer.Argument(..., help="Agent name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of records to show"),
    from_date: Optional[str] = typer.Option(None, "--from", help="From date (YYYY-MM-DD)"),
    to_date: Optional[str] = typer.Option(None, "--to", help="To date (YYYY-MM-DD)"),
    show_errors: bool = typer.Option(False, "--errors", help="Show only failed tasks"),
):
    """
    Show task execution history for an agent.
    """
    async def _history():
        persistence, engine = await _get_persistence_and_db()
        try:
            # Parse dates
            from_dt = None
            to_dt = None
            if from_date:
                from_dt = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
            if to_date:
                to_dt = datetime.fromisoformat(to_date).replace(tzinfo=UTC)
            
            records = await persistence.get_task_history(
                agent_name=name,
                from_date=from_dt,
                to_date=to_dt,
                limit=limit,
            )
            
            return records
        finally:
            await engine.dispose()
    
    records = asyncio.run(_history())
    
    if not records:
        typer.echo(f"No history found for agent '{name}'.")
        return
    
    # Filter errors if requested
    if show_errors:
        records = [r for r in records if not r.success]
        if not records:
            typer.echo(f"No failed tasks found for agent '{name}'.")
            return
    
    typer.echo(f"\n📜 Task History for '{name}' ({len(records)} records)")
    typer.echo("=" * 80)
    
    for record in records:
        status = "✅" if record.success else "❌"
        time_str = f"{record.processing_time_ms}ms" if record.processing_time_ms else "N/A"
        
        typer.echo(f"\n{status} {record.id[:8]}... | {record.task_type}")
        typer.echo(f"   Time: {record.created_at.isoformat()} | Duration: {time_str}")
        
        if record.source_ref:
            typer.echo(f"   Source: {record.source_ref}")
        if record.channel_id:
            typer.echo(f"   Channel: {record.channel_id}")
        
        if not record.success and record.error:
            typer.echo(f"   ❗ Error: {record.error[:100]}...")
    
    typer.echo()


@app.command("cleanup")
def cleanup_history(
    archive: bool = typer.Option(
        False, "--archive", "-a",
        help="Archive expired records before deletion"
    ),
    include_handoffs: bool = typer.Option(
        False, "--include-handoffs",
        help="Also archive handoff history (requires --archive)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show what would be deleted without actually deleting"
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Skip confirmation prompt"
    ),
):
    """
    Clean up expired task history records.
    
    By default, deletes expired records. Use --archive to save them first.
    Use --include-handoffs with --archive to also archive handoff records.
    """
    async def _get_expired():
        from tg_parser.services._wiring import create_processing_engine, create_session_factory
        from tg_parser.storage.sqlalchemy.task_history_repo import SQLiteTaskHistoryRepo

        engine = create_processing_engine()
        session_factory = create_session_factory(engine)
        task_repo = SQLiteTaskHistoryRepo(session_factory)
        expired_records = await task_repo.get_expired_for_archive(limit=10000)
        await engine.dispose()
        return expired_records
    
    expired_records = asyncio.run(_get_expired())
    
    expired_count = len(expired_records)
    
    if expired_count == 0:
        typer.echo("✅ No expired records to clean up.")
        return
    
    typer.echo(f"\n🗑️  Found {expired_count} expired task history records")
    
    if dry_run:
        typer.echo("\n⚠️  Dry-run mode - no changes will be made")
        typer.echo(f"   Would delete: {expired_count} task records")
        if archive:
            typer.echo(f"   Would archive to: {settings.agent_archive_path}")
            if include_handoffs:
                typer.echo("   Would include handoff history")
        return
    
    # Confirmation
    if not force:
        typer.echo()
        confirm = typer.confirm(
            f"Delete {expired_count} expired records" + 
            (" (with archive)" if archive else "") + "?"
        )
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(code=0)
    
    async def _do_cleanup_and_archive():
        persistence, engine = await _get_persistence_and_db()
        try:
            archive_result = None
            
            # Archive if requested
            if archive:
                from tg_parser.agents.archiver import AgentHistoryArchiver
                
                archiver = AgentHistoryArchiver(settings.agent_archive_path)
                
                handoff_records = None
                if include_handoffs:
                    from sqlalchemy import text

                    from tg_parser.services._wiring import create_processing_engine, create_session_factory
                    from tg_parser.storage.sqlalchemy.handoff_history_repo import SQLiteHandoffHistoryRepo

                    temp_engine = create_processing_engine()
                    temp_session_factory = create_session_factory(temp_engine)
                    handoff_repo = SQLiteHandoffHistoryRepo(temp_session_factory)

                    async with temp_session_factory() as session:
                        result = await session.execute(
                            text("""
                                SELECT * FROM handoff_history 
                                WHERE status IN ('completed', 'failed')
                                ORDER BY created_at DESC
                                LIMIT 10000
                            """)
                        )
                        rows = result.fetchall()
                        handoff_records = [handoff_repo._row_to_record(row) for row in rows]

                    await temp_engine.dispose()
                
                archive_result = await archiver.archive_all(expired_records, handoff_records)
            
            # Delete expired records
            deleted = await persistence.cleanup_expired_tasks()
            
            return archive_result, deleted
        finally:
            await engine.dispose()
    
    archive_result, deleted_count = asyncio.run(_do_cleanup_and_archive())
    
    if archive_result:
        if archive_result.get("task_history"):
            typer.echo(f"📦 Archived task history: {archive_result['task_history']}")
        if archive_result.get("handoff_history"):
            typer.echo(f"📦 Archived handoff history: {archive_result['handoff_history']}")
    
    typer.echo(f"✅ Deleted {deleted_count} expired records")


@app.command("handoffs")
def show_handoffs(
    agent_name: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent name"),
    as_source: bool = typer.Option(True, "--as-source/--as-target", help="Filter as source or target"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of records"),
    stats: bool = typer.Option(False, "--stats", help="Show statistics instead of records"),
):
    """
    Show handoff history between agents.
    """
    async def _handoffs():
        persistence, engine = await _get_persistence_and_db()
        try:
            if stats:
                return None, await persistence.get_handoff_statistics()
            
            if not agent_name:
                return [], {}
            
            records = await persistence.get_handoff_history(
                agent_name=agent_name,
                as_source=as_source,
                status=status,
                limit=limit,
            )
            
            return records, {}
        finally:
            await engine.dispose()
    
    if not stats and not agent_name:
        typer.echo("❌ Agent name required. Use --agent <name> or --stats for statistics.", err=True)
        raise typer.Exit(code=1)
    
    records, statistics = asyncio.run(_handoffs())
    
    if stats:
        typer.echo("\n🔄 Handoff Statistics")
        typer.echo("=" * 60)
        typer.echo(f"   Total Handoffs: {statistics.get('total_handoffs', 0)}")
        typer.echo(f"   Completed: {statistics.get('completed', 0)}")
        typer.echo(f"   Failed: {statistics.get('failed', 0)}")
        typer.echo(f"   Rejected: {statistics.get('rejected', 0)}")
        typer.echo(f"   In Progress: {statistics.get('in_progress', 0)}")
        typer.echo(f"   Success Rate: {statistics.get('success_rate', 0) * 100:.1f}%")
        typer.echo(f"   Avg Time: {statistics.get('avg_processing_time_ms', 0):.1f}ms")
        
        if statistics.get('top_agent_pairs'):
            typer.echo("\n   Top Agent Pairs:")
            for pair in statistics['top_agent_pairs'][:5]:
                typer.echo(f"      {pair['source']} → {pair['target']}: {pair['count']}")
        
        typer.echo()
        return
    
    if not records:
        direction = "from" if as_source else "to"
        typer.echo(f"No handoffs found {direction} agent '{agent_name}'.")
        return
    
    direction = "from" if as_source else "to"
    typer.echo(f"\n🔄 Handoffs {direction} '{agent_name}' ({len(records)} records)")
    typer.echo("=" * 80)
    
    for record in records:
        status_icons = {
            "pending": "⏳",
            "accepted": "🔄",
            "in_progress": "🔄",
            "completed": "✅",
            "failed": "❌",
            "rejected": "🚫",
        }
        icon = status_icons.get(record.status, "❓")
        
        typer.echo(f"\n{icon} {record.id[:8]}... | {record.task_type}")
        typer.echo(f"   {record.source_agent} → {record.target_agent}")
        typer.echo(f"   Status: {record.status} | Priority: {record.priority}")
        typer.echo(f"   Created: {record.created_at.isoformat()}")
        
        if record.processing_time_ms:
            typer.echo(f"   Duration: {record.processing_time_ms}ms")
        if record.error:
            typer.echo(f"   ❗ Error: {record.error[:80]}...")
    
    typer.echo()


@app.command("archives")
def list_archives():
    """
    List archived history files.
    """
    from tg_parser.agents.archiver import AgentHistoryArchiver
    
    archiver = AgentHistoryArchiver(settings.agent_archive_path)
    archives = archiver.list_archives()
    
    if not archives:
        typer.echo(f"No archives found in {settings.agent_archive_path}")
        return
    
    typer.echo(f"\n📦 Archives in {settings.agent_archive_path}")
    typer.echo("=" * 70)
    
    for archive in archives:
        size_kb = archive['size_bytes'] / 1024
        typer.echo(f"\n   {archive['filename']}")
        typer.echo(f"      Size: {size_kb:.1f} KB | Created: {archive['created_at']}")
    
    typer.echo(f"\n   Total: {len(archives)} archive(s)")
    typer.echo()

