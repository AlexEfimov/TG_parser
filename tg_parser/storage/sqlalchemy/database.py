"""
База данных для TG_parser.

PostgreSQL-only через engine factory.
Реализует TR-14/TR-17/TR-42: три отдельных engine (по одному на каждую логическую БД).
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import create_engine_from_settings


class Database:
    """
    Контейнер для SQLAlchemy engines и sessionmakers.

    Использование:
    ```python
    from tg_parser.config.settings import settings
    db = Database.from_settings(settings)
    await db.init()

    session = db.processing_storage_session()
    try:
        # ...
    finally:
        await session.close()
        await db.close()
    ```
    """

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

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        """
        Создать Database из Settings.
        
        Args:
            settings: Application settings
            
        Returns:
            Database instance
        """
        return cls(settings=settings)

    async def init(self) -> None:
        """Инициализировать engines и sessionmakers."""
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

    async def close(self) -> None:
        """Закрыть engines."""
        if self.ingestion_state_engine:
            await self.ingestion_state_engine.dispose()
        if self.raw_storage_engine:
            await self.raw_storage_engine.dispose()
        if self.processing_storage_engine:
            await self.processing_storage_engine.dispose()

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
