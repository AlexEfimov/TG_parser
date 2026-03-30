"""
База данных для TG_parser.

PostgreSQL-only через engine factory.
Реализует TR-14/TR-17/TR-42: три отдельных engine (по одному на каждую логическую БД).

S7a: Singleton pattern — engines создаются один раз, переиспользуются
всеми context managers и сервисами.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import create_engine_from_settings


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
        self.raw_storage_engine = create_engine_from_settings(
            self.settings, "raw", echo=False
        )
        self.processing_storage_engine = create_engine_from_settings(
            self.settings, "processing", echo=False
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

    @property
    def processing_session_factory(self) -> sessionmaker:
        """Return the processing sessionmaker (for repos that need factory)."""
        if not self._processing_storage_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._processing_storage_sessionmaker
