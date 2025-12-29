"""
Engine factory для создания SQLAlchemy engines.

Session 24: поддержка SQLite и PostgreSQL с connection pooling.
"""

import structlog
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, QueuePool

from tg_parser.config.settings import Settings

logger = structlog.get_logger(__name__)


DatabaseType = Literal["sqlite", "postgresql"]


class EngineConfig:
    """
    Конфигурация для создания SQLAlchemy engine.
    
    Attributes:
        url: SQLAlchemy connection URL
        pool_class: Pool class (QueuePool или NullPool)
        pool_size: Base number of connections in pool
        max_overflow: Additional connections when pool exhausted
        pool_timeout: Timeout to get connection from pool (seconds)
        pool_recycle: Recycle connections after N seconds
        pool_pre_ping: Check connection health before use
        echo: Log SQL queries (for debugging)
    """
    
    def __init__(
        self,
        url: str,
        pool_class: type | None = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30.0,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo: bool = False,
    ):
        self.url = url
        self.pool_class = pool_class
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo = echo


def _build_sqlite_url(db_path: Path | str) -> str:
    """
    Построить SQLite connection URL.
    
    Args:
        db_path: Path to SQLite database file
        
    Returns:
        SQLAlchemy URL for SQLite with aiosqlite driver
    """
    return f"sqlite+aiosqlite:///{db_path}"


def _build_postgres_url(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> str:
    """
    Построить PostgreSQL connection URL.
    
    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        database: Database name
        user: Username
        password: Password
        
    Returns:
        SQLAlchemy URL for PostgreSQL with asyncpg driver
    """
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def create_sqlite_engine_config(db_path: Path | str, echo: bool = False) -> EngineConfig:
    """
    Создать конфигурацию engine для SQLite.
    
    SQLite использует NullPool (no pooling) т.к. это file-based database.
    
    Args:
        db_path: Path to SQLite database file
        echo: Enable SQL query logging
        
    Returns:
        EngineConfig for SQLite
    """
    url = _build_sqlite_url(db_path)
    
    return EngineConfig(
        url=url,
        pool_class=NullPool,  # SQLite doesn't need connection pooling
        echo=echo,
    )


def create_postgres_engine_config(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: float = 30.0,
    pool_recycle: int = 3600,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> EngineConfig:
    """
    Создать конфигурацию engine для PostgreSQL.
    
    PostgreSQL использует QueuePool для эффективного переиспользования connections.
    
    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        database: Database name
        user: Username
        password: Password
        pool_size: Base number of connections in pool
        max_overflow: Additional connections when pool exhausted
        pool_timeout: Timeout to get connection from pool (seconds)
        pool_recycle: Recycle connections after N seconds
        pool_pre_ping: Check connection health before use
        echo: Enable SQL query logging
        
    Returns:
        EngineConfig for PostgreSQL
    """
    url = _build_postgres_url(host, port, database, user, password)
    
    return EngineConfig(
        url=url,
        pool_class=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
    )


def create_engine_from_config(config: EngineConfig) -> AsyncEngine:
    """
    Создать AsyncEngine из EngineConfig.
    
    Args:
        config: Engine configuration
        
    Returns:
        Configured AsyncEngine
    """
    # Build kwargs for create_async_engine
    kwargs = {
        "echo": config.echo,
    }
    
    # For async engines, SQLAlchemy automatically uses appropriate pool class
    # (AsyncAdaptedQueuePool for most drivers, NullPool for aiosqlite)
    # We should NOT specify poolclass directly for async engines
    
    # Add pooling parameters for PostgreSQL (QueuePool-like behavior)
    if config.pool_class == QueuePool:
        # Don't set poolclass, but set pool parameters
        # SQLAlchemy will use AsyncAdaptedQueuePool automatically
        kwargs.update({
            "pool_size": config.pool_size,
            "max_overflow": config.max_overflow,
            "pool_timeout": config.pool_timeout,
            "pool_recycle": config.pool_recycle,
            "pool_pre_ping": config.pool_pre_ping,
        })
    elif config.pool_class == NullPool:
        # For SQLite with NullPool
        kwargs["poolclass"] = NullPool
    
    engine = create_async_engine(config.url, **kwargs)
    
    logger.info(
        "engine_created",
        url=_mask_password(config.url),
        pool_class=config.pool_class.__name__ if config.pool_class else "default",
        pool_size=config.pool_size if config.pool_class == QueuePool else "N/A",
    )
    
    return engine


def _mask_password(url: str) -> str:
    """
    Mask password in connection URL for logging.
    
    Args:
        url: Connection URL
        
    Returns:
        URL with password replaced by '***'
    """
    if "://" not in url:
        return url
        
    # Split protocol and rest
    protocol, rest = url.split("://", 1)
    
    # Check if there's authentication
    if "@" not in rest:
        return url
        
    # Split credentials and host
    credentials, host_part = rest.split("@", 1)
    
    # Split username and password
    if ":" in credentials:
        username, _ = credentials.split(":", 1)
        return f"{protocol}://{username}:***@{host_part}"
    
    return url


def create_engine_from_settings(
    settings: Settings,
    db_name: Literal["ingestion", "raw", "processing"],
    echo: bool = False,
) -> AsyncEngine:
    """
    Создать AsyncEngine из Settings для указанной БД.
    
    Автоматически выбирает SQLite или PostgreSQL на основе settings.db_type.
    
    Args:
        settings: Application settings
        db_name: Which database: 'ingestion', 'raw', or 'processing'
        echo: Enable SQL query logging (for debugging)
        
    Returns:
        Configured AsyncEngine
        
    Raises:
        ValueError: If db_type is invalid or db_name is invalid
    """
    # Validate db_name
    if db_name not in ("ingestion", "raw", "processing"):
        raise ValueError(f"Invalid db_name: {db_name}. Must be 'ingestion', 'raw', or 'processing'")
    
    db_type = settings.db_type.lower()
    
    if db_type == "sqlite":
        # Get SQLite path for specific database
        if db_name == "ingestion":
            db_path = settings.ingestion_state_db_path
        elif db_name == "raw":
            db_path = settings.raw_storage_db_path
        else:  # processing
            db_path = settings.processing_storage_db_path
        
        config = create_sqlite_engine_config(db_path, echo=echo)
        
        logger.info(
            "creating_sqlite_engine",
            db_name=db_name,
            db_path=str(db_path),
        )
        
    elif db_type == "postgresql":
        # PostgreSQL uses single database with different schemas/tables
        # All three databases use the same connection parameters
        config = create_postgres_engine_config(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
            echo=echo,
        )
        
        logger.info(
            "creating_postgres_engine",
            db_name=db_name,
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            pool_size=settings.db_pool_size,
        )
        
    else:
        raise ValueError(
            f"Invalid db_type: {db_type}. Must be 'sqlite' or 'postgresql'"
        )
    
    return create_engine_from_config(config)


def get_pool_status(engine: AsyncEngine) -> dict[str, int | str]:
    """
    Получить статус connection pool.
    
    Args:
        engine: AsyncEngine instance
        
    Returns:
        Dictionary with pool metrics
    """
    pool = engine.pool
    pool_type = type(pool).__name__
    
    # NullPool doesn't have these attributes
    if isinstance(pool, NullPool):
        return {
            "type": "NullPool",
            "status": "no_pooling",
        }
    
    # AsyncAdaptedQueuePool (used by async engines) or QueuePool
    # Both have similar interface
    if hasattr(pool, 'size') and hasattr(pool, 'checkedout'):
        try:
            return {
                "type": pool_type,
                "size": pool.size(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow() if hasattr(pool, 'overflow') else 0,
                "status": "healthy",
            }
        except Exception:
            return {
                "type": pool_type,
                "status": "error",
            }
    
    # Unknown pool type
    return {
        "type": pool_type,
        "status": "unknown",
    }

