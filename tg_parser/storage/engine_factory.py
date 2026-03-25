"""
Engine factory для создания SQLAlchemy engines.

PostgreSQL-only с connection pooling.
"""

import structlog
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import QueuePool

from tg_parser.config.settings import Settings

logger = structlog.get_logger(__name__)


class EngineConfig:
    """
    Конфигурация для создания SQLAlchemy engine.
    
    Attributes:
        url: SQLAlchemy connection URL
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
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30.0,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo: bool = False,
    ):
        self.url = url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo = echo


def _build_postgres_url(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> str:
    """
    Построить PostgreSQL connection URL.
    
    Returns:
        SQLAlchemy URL for PostgreSQL with asyncpg driver
    """
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


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
    """
    url = _build_postgres_url(host, port, database, user, password)
    
    return EngineConfig(
        url=url,
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
    """
    kwargs = {
        "echo": config.echo,
        "pool_size": config.pool_size,
        "max_overflow": config.max_overflow,
        "pool_timeout": config.pool_timeout,
        "pool_recycle": config.pool_recycle,
        "pool_pre_ping": config.pool_pre_ping,
    }
    
    engine = create_async_engine(config.url, **kwargs)
    
    logger.info(
        "engine_created",
        url=_mask_password(config.url),
        pool_size=config.pool_size,
    )
    
    return engine


def _mask_password(url: str) -> str:
    """Mask password in connection URL for logging."""
    if "://" not in url:
        return url
        
    protocol, rest = url.split("://", 1)
    
    if "@" not in rest:
        return url
        
    credentials, host_part = rest.split("@", 1)
    
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
    
    Args:
        settings: Application settings
        db_name: Which database: 'ingestion', 'raw', or 'processing'
        echo: Enable SQL query logging (for debugging)
        
    Returns:
        Configured AsyncEngine
        
    Raises:
        ValueError: If db_name is invalid
    """
    if db_name not in ("ingestion", "raw", "processing"):
        raise ValueError(f"Invalid db_name: {db_name}. Must be 'ingestion', 'raw', or 'processing'")
    
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
    
    return create_engine_from_config(config)


def get_pool_status(engine: AsyncEngine) -> dict[str, int | str]:
    """
    Получить статус connection pool.
    """
    pool = engine.pool
    pool_type = type(pool).__name__
    
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
    
    return {
        "type": pool_type,
        "status": "unknown",
    }
