"""
Alembic environment for TG_parser multi-database setup.

Session 22: Foundation & Tech Debt
Multi-database support for 3 SQLite databases:
- ingestion_state.sqlite
- raw_storage.sqlite
- processing_storage.sqlite
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tg_parser.storage.sqlite.database import DatabaseConfig

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Database configurations mapping
DATABASES = {
    "ingestion": {
        "url": "sqlite+aiosqlite:///ingestion_state.sqlite",
        "schema_module": "tg_parser.storage.sqlite.schemas.ingestion_state",
        "ddl_name": "INGESTION_STATE_DDL",
    },
    "raw": {
        "url": "sqlite+aiosqlite:///raw_storage.sqlite",
        "schema_module": "tg_parser.storage.sqlite.schemas.raw_storage",
        "ddl_name": "RAW_STORAGE_DDL",
    },
    "processing": {
        "url": "sqlite+aiosqlite:///processing_storage.sqlite",
        "schema_module": "tg_parser.storage.sqlite.schemas.processing_storage",
        "ddl_name": "PROCESSING_STORAGE_DDL",
    },
}


def get_db_name() -> str:
    """
    Get database name from command line or context.
    
    Returns:
        Database name: "ingestion", "raw", or "processing"
    """
    # Check command line for --name option
    db_name = context.get_x_argument(as_dictionary=True).get("db_name")
    
    if db_name:
        return db_name
    
    # Check config main option
    db_name = config.get_main_option("db_name")
    
    if db_name:
        return db_name
    
    # Default to ingestion for safety
    return "ingestion"


def get_url() -> str:
    """Get SQLAlchemy URL for current database."""
    db_name = get_db_name()
    
    if db_name not in DATABASES:
        raise ValueError(
            f"Unknown database: {db_name}. "
            f"Must be one of: {', '.join(DATABASES.keys())}"
        )
    
    db_config = DATABASES[db_name]
    
    # Allow override from environment
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    
    return db_config["url"]


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url()
    db_name = get_db_name()
    
    # Set version_locations dynamically
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
    
    # Set version_locations dynamically
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
    db_name = get_db_name()
    url = get_url()
    
    # Create async engine
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

