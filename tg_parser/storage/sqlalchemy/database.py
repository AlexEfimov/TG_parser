"""
База данных для TG_parser.

PostgreSQL-only через engine factory.
Реализует TR-14/TR-17/TR-42: три отдельных engine (по одному на каждую логическую БД).

S7a: Singleton pattern — engines создаются один раз, переиспользуются
всеми context managers и сервисами.
F8-A: DB pool metrics via SQLAlchemy pool events.
"""

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import (
    create_advisory_lock_engine_from_settings,
    create_engine_from_settings,
)

logger = structlog.get_logger(__name__)


class Database:
    """
    Singleton-контейнер для SQLAlchemy engines и sessionmakers.

    Engines создаются один раз при первом вызове ``init()`` и живут
    до явного ``close_instance()``.

    Использование:
        db = Database.get_instance()
        await db.init()
        session = db.processing_storage_session()
    """

    _instance: "Database | None" = None
    _initialized: bool = False

    def __init__(self, settings: Settings):
        self.settings = settings

        # Engines
        self.ingestion_state_engine: AsyncEngine | None = None
        self.raw_storage_engine: AsyncEngine | None = None
        self.processing_storage_engine: AsyncEngine | None = None
        self.advisory_lock_engine: AsyncEngine | None = None

        # Sessionmakers
        self._ingestion_state_sessionmaker: sessionmaker | None = None
        self._raw_storage_sessionmaker: sessionmaker | None = None
        self._processing_storage_sessionmaker: sessionmaker | None = None

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, settings: Settings | None = None) -> "Database":
        """Return the singleton, creating it on first call."""
        if cls._instance is None:
            if settings is None:
                from tg_parser.config import settings as default_settings

                settings = default_settings
            cls._instance = cls(settings=settings)
        return cls._instance

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        """Backwards-compatible alias for ``get_instance``."""
        return cls.get_instance(settings)

    @classmethod
    async def close_instance(cls) -> None:
        """Dispose engines and drop the singleton reference."""
        if cls._instance is not None and cls._instance._initialized:
            await cls._instance._dispose_engines()
        cls._instance = None

    @classmethod
    def reset_instance(cls) -> None:
        """Drop the singleton reference without async disposal (tests only)."""
        cls._instance = None
        cls._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Создать engines и sessionmakers (idempotent)."""
        if self._initialized:
            return

        self.ingestion_state_engine = create_engine_from_settings(
            self.settings, "ingestion", echo=False
        )
        self.raw_storage_engine = create_engine_from_settings(self.settings, "raw", echo=False)
        self.processing_storage_engine = create_engine_from_settings(
            self.settings, "processing", echo=False
        )
        self.advisory_lock_engine = create_advisory_lock_engine_from_settings(
            self.settings, echo=False
        )

        self._ingestion_state_sessionmaker = sessionmaker(
            self.ingestion_state_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._raw_storage_sessionmaker = sessionmaker(
            self.raw_storage_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._processing_storage_sessionmaker = sessionmaker(
            self.processing_storage_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._register_pool_metrics()
        self._initialized = True

    async def close(self) -> None:
        """Dispose engines and reset initialized flag."""
        await self._dispose_engines()

    async def _dispose_engines(self) -> None:
        if self.ingestion_state_engine:
            await self.ingestion_state_engine.dispose()
        if self.raw_storage_engine:
            await self.raw_storage_engine.dispose()
        if self.processing_storage_engine:
            await self.processing_storage_engine.dispose()
        if self.advisory_lock_engine:
            await self.advisory_lock_engine.dispose()
        self._initialized = False

    # ------------------------------------------------------------------
    # Session factories
    # ------------------------------------------------------------------

    def ingestion_state_session(self) -> AsyncSession:
        """Создать session для ingestion state storage."""
        if not self._ingestion_state_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._ingestion_state_sessionmaker()

    def raw_storage_session(self) -> AsyncSession:
        """Создать session для raw message storage."""
        if not self._raw_storage_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._raw_storage_sessionmaker()

    def processing_storage_session(self) -> AsyncSession:
        """Создать session для processing storage."""
        if not self._processing_storage_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._processing_storage_sessionmaker()

    def _register_pool_metrics(self) -> None:
        """Attach SQLAlchemy pool event listeners to update Prometheus gauges."""
        try:
            from tg_parser.api.metrics import DB_CONNECTIONS_ACTIVE
        except Exception:
            return

        engines = {
            "ingestion": self.ingestion_state_engine,
            "raw": self.raw_storage_engine,
            "processing": self.processing_storage_engine,
            "advisory_lock": self.advisory_lock_engine,
        }
        for label, engine in engines.items():
            if engine is None:
                continue
            sync_pool = engine.pool

            def _on_checkout(_conn, _rec, _proxy, db=label, pool=sync_pool):
                try:
                    DB_CONNECTIONS_ACTIVE.labels(database=db).set(pool.checkedout())
                except Exception:
                    pass

            def _on_checkin(_conn, _rec, db=label, pool=sync_pool):
                try:
                    DB_CONNECTIONS_ACTIVE.labels(database=db).set(pool.checkedout())
                except Exception:
                    pass

            event.listen(sync_pool, "checkout", _on_checkout)
            event.listen(sync_pool, "checkin", _on_checkin)

        logger.debug("db_pool_metrics_registered")

    @property
    def processing_session_factory(self) -> sessionmaker:
        """Return the processing sessionmaker (for repos that need factory)."""
        if not self._processing_storage_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._processing_storage_sessionmaker
