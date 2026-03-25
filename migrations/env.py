"""
Alembic environment for TG_parser multi-database setup.

Session 22: Foundation & Tech Debt
Session 24: PostgreSQL Support
Session 39: PostgreSQL-only (SQLite support removed)

Multi-database support for 3 logical areas:
- ingestion (ingestion state tables)
- raw (raw message tables)
- processing (processed docs, topics, agents, jobs)
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.insert(0, str(Path(__file__).parent.parent))

from tg_parser.config.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _build_postgres_url(settings: Settings) -> str:
    """Build PostgreSQL connection URL from settings."""
    return (
        f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def _get_settings() -> Settings:
    """Get Settings from environment."""
    try:
        return Settings()
    except Exception as e:
        print(f"Warning: Failed to load settings: {e}")
        return Settings()


def get_db_name() -> str:
    """
    Get database name from command line or context.
    
    Returns:
        Database name: "ingestion", "raw", or "processing"
    """
    db_name = context.get_x_argument(as_dictionary=True).get("db_name")
    
    if db_name:
        return db_name
    
    db_name = config.get_main_option("db_name")
    
    if db_name:
        return db_name
    
    return "ingestion"


def get_url() -> str:
    """Get SQLAlchemy URL for current database."""
    db_name = get_db_name()
    
    if db_name not in ("ingestion", "raw", "processing"):
        raise ValueError(
            f"Unknown database: {db_name}. "
            f"Must be one of: ingestion, raw, processing"
        )
    
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    
    env_url = os.environ.get("ALEMBIC_DATABASE_URL")
    if env_url:
        return env_url
    
    settings = _get_settings()
    return _build_postgres_url(settings)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    db_name = get_db_name()
    
    version_path = Path(__file__).parent / "versions" / db_name
    config.set_main_option("version_locations", str(version_path))
    
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=f"alembic_version_{db_name}",
        include_schemas=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with given connection."""
    db_name = get_db_name()
    
    version_path = Path(__file__).parent / "versions" / db_name
    config.set_main_option("version_locations", str(version_path))
    
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table=f"alembic_version_{db_name}",
        include_schemas=False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode (async)."""
    url = get_url()
    
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url
    
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
