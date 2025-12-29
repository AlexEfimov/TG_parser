#!/usr/bin/env python3
"""
Migrate data from SQLite to PostgreSQL.

Session 24: Production-ready migration script.

Usage:
    # Dry run (no changes)
    python scripts/migrate_sqlite_to_postgres.py --dry-run
    
    # Real migration with verification
    python scripts/migrate_sqlite_to_postgres.py --verify
    
    # Migration without verification (faster)
    python scripts/migrate_sqlite_to_postgres.py
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import create_engine_from_settings

logger = structlog.get_logger(__name__)


class MigrationStats:
    """Track migration statistics."""
    
    def __init__(self):
        self.tables: dict[str, dict[str, int]] = {}
        self.start_time = datetime.now()
        self.end_time: datetime | None = None
        
    def add_table(self, table_name: str, source_count: int, migrated_count: int):
        """Add table statistics."""
        self.tables[table_name] = {
            "source_count": source_count,
            "migrated_count": migrated_count,
            "success": source_count == migrated_count,
        }
        
    def finish(self):
        """Mark migration as finished."""
        self.end_time = datetime.now()
        
    def duration(self) -> float:
        """Get migration duration in seconds."""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()
        
    def total_records(self) -> int:
        """Get total migrated records."""
        return sum(t["migrated_count"] for t in self.tables.values())
        
    def is_success(self) -> bool:
        """Check if all tables migrated successfully."""
        return all(t["success"] for t in self.tables.values())
        
    def print_summary(self):
        """Print migration summary."""
        print("\n" + "=" * 70)
        print("MIGRATION SUMMARY")
        print("=" * 70)
        
        for table_name, stats in self.tables.items():
            status = "✅ OK" if stats["success"] else "❌ FAIL"
            print(
                f"{status} {table_name:30s} "
                f"{stats['source_count']:5d} → {stats['migrated_count']:5d}"
            )
        
        print("-" * 70)
        print(f"Total records migrated: {self.total_records()}")
        print(f"Duration: {self.duration():.2f} seconds")
        print(f"Status: {'SUCCESS' if self.is_success() else 'FAILED'}")
        print("=" * 70 + "\n")


async def count_records(session: AsyncSession, table_name: str) -> int:
    """Count records in table."""
    result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    return result.scalar_one()


async def migrate_table(
    source_session: AsyncSession,
    target_session: AsyncSession,
    table_name: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Migrate single table from source to target.
    
    Args:
        source_session: Source database session (SQLite)
        target_session: Target database session (PostgreSQL)
        table_name: Table name
        dry_run: If True, don't commit changes
        
    Returns:
        Tuple of (source_count, migrated_count)
    """
    logger.info("migrating_table", table=table_name, dry_run=dry_run)
    
    # Count source records
    source_count = await count_records(source_session, table_name)
    logger.info("source_records", table=table_name, count=source_count)
    
    if source_count == 0:
        logger.info("table_empty", table=table_name)
        return 0, 0
    
    if dry_run:
        logger.info("dry_run_skipping_migration", table=table_name)
        return source_count, source_count
    
    # Fetch all records from source
    result = await source_session.execute(text(f"SELECT * FROM {table_name}"))
    rows = result.fetchall()
    columns = result.keys()
    
    logger.info("fetched_records", table=table_name, count=len(rows))
    
    # Insert into target
    migrated = 0
    for row in rows:
        try:
            # Build INSERT statement
            placeholders = ", ".join([f":{col}" for col in columns])
            insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
            
            # Convert row to dict
            row_dict = dict(zip(columns, row))
            
            # Execute insert
            await target_session.execute(text(insert_sql), row_dict)
            migrated += 1
            
        except Exception as e:
            logger.error(
                "record_migration_failed",
                table=table_name,
                error=str(e),
            )
            # Continue with next record
            continue
    
    # Commit changes
    await target_session.commit()
    
    logger.info("migration_complete", table=table_name, migrated=migrated)
    
    return source_count, migrated


async def verify_migration(
    source_session: AsyncSession,
    target_session: AsyncSession,
    table_names: list[str],
) -> bool:
    """
    Verify migration by comparing record counts.
    
    Args:
        source_session: Source database session
        target_session: Target database session
        table_names: List of table names
        
    Returns:
        True if verification passed
    """
    logger.info("verifying_migration")
    
    all_ok = True
    
    for table_name in table_names:
        source_count = await count_records(source_session, table_name)
        target_count = await count_records(target_session, table_name)
        
        if source_count == target_count:
            logger.info("verification_ok", table=table_name, count=source_count)
        else:
            logger.error(
                "verification_failed",
                table=table_name,
                source_count=source_count,
                target_count=target_count,
            )
            all_ok = False
    
    return all_ok


async def migrate_database(
    db_name: str,
    table_names: list[str],
    sqlite_settings: Settings,
    postgres_settings: Settings,
    dry_run: bool = False,
    verify: bool = False,
) -> MigrationStats:
    """
    Migrate single database.
    
    Args:
        db_name: Database name ('ingestion', 'raw', or 'processing')
        table_names: List of table names to migrate
        sqlite_settings: Settings for SQLite
        postgres_settings: Settings for PostgreSQL
        dry_run: If True, don't commit changes
        verify: If True, verify record counts after migration
        
    Returns:
        Migration statistics
    """
    logger.info("starting_database_migration", db_name=db_name)
    
    stats = MigrationStats()
    
    # Create engines
    sqlite_engine = create_engine_from_settings(sqlite_settings, db_name)
    postgres_engine = create_engine_from_settings(postgres_settings, db_name)
    
    try:
        # Create sessions
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.ext.asyncio import AsyncSession as AsyncSessionClass
        
        SqliteSession = sessionmaker(
            sqlite_engine, class_=AsyncSessionClass, expire_on_commit=False
        )
        PostgresSession = sessionmaker(
            postgres_engine, class_=AsyncSessionClass, expire_on_commit=False
        )
        
        async with SqliteSession() as sqlite_session, PostgresSession() as postgres_session:
            # Migrate each table
            for table_name in table_names:
                source_count, migrated_count = await migrate_table(
                    sqlite_session,
                    postgres_session,
                    table_name,
                    dry_run=dry_run,
                )
                stats.add_table(table_name, source_count, migrated_count)
            
            # Verify if requested
            if verify and not dry_run:
                verification_ok = await verify_migration(
                    sqlite_session, postgres_session, table_names
                )
                if not verification_ok:
                    logger.error("verification_failed", db_name=db_name)
    
    finally:
        # Clean up
        await sqlite_engine.dispose()
        await postgres_engine.dispose()
    
    stats.finish()
    return stats


async def run_migration(
    dry_run: bool = False,
    verify: bool = False,
) -> bool:
    """
    Run full migration from SQLite to PostgreSQL.
    
    Args:
        dry_run: If True, don't commit changes
        verify: If True, verify record counts after migration
        
    Returns:
        True if migration successful
    """
    logger.info("starting_migration", dry_run=dry_run, verify=verify)
    
    # Create settings for both databases
    sqlite_settings = Settings(db_type="sqlite")
    postgres_settings = Settings(db_type="postgresql")
    
    logger.info(
        "settings_loaded",
        sqlite_ingestion=str(sqlite_settings.ingestion_state_db_path),
        postgres_host=postgres_settings.db_host,
        postgres_db=postgres_settings.db_name,
    )
    
    # Define tables for each database
    ingestion_tables = [
        "sources",
        "comment_cursors",
        "source_attempts",
    ]
    
    raw_tables = [
        "raw_messages",
    ]
    
    processing_tables = [
        "processed_documents",
        "processing_failures",
        "topics",
        "topic_bundles",
        "agent_registry",
        "task_history",
        "handoff_history",
        "jobs",
        "agent_stats",
    ]
    
    all_stats: list[MigrationStats] = []
    
    # Migrate each database
    for db_name, table_names in [
        ("ingestion", ingestion_tables),
        ("raw", raw_tables),
        ("processing", processing_tables),
    ]:
        stats = await migrate_database(
            db_name, table_names, sqlite_settings, postgres_settings, dry_run, verify
        )
        all_stats.append(stats)
    
    # Print summary for all databases
    print("\n" + "=" * 70)
    print("FULL MIGRATION SUMMARY")
    print("=" * 70)
    
    total_records = 0
    total_duration = 0.0
    all_success = True
    
    for stats in all_stats:
        stats.print_summary()
        total_records += stats.total_records()
        total_duration += stats.duration()
        all_success = all_success and stats.is_success()
    
    print(f"Total records: {total_records}")
    print(f"Total duration: {total_duration:.2f} seconds")
    print(f"Overall status: {'✅ SUCCESS' if all_success else '❌ FAILED'}")
    print("=" * 70 + "\n")
    
    return all_success


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate TG_parser data from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run migration without committing changes",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify record counts after migration",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging_level=20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    
    # Run migration
    success = asyncio.run(run_migration(dry_run=args.dry_run, verify=args.verify))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

