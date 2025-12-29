"""
База данных для TG_parser.

Session 24: поддержка SQLite и PostgreSQL через engine factory.
Реализует TR-14/TR-17/TR-42: три отдельных БД (файлы или схемы).
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import create_engine_from_settings


class DatabaseConfig:
    """
    Конфигурация БД (backward compatibility).

    TR-17: разделение на 3 БД.
    Session 24: поддержка SQLite и PostgreSQL.
    
    Deprecated: используйте Settings напрямую с engine factory.
    """

    def __init__(
        self,
        ingestion_state_path: Path | str = "ingestion_state.sqlite",
        raw_storage_path: Path | str = "raw_storage.sqlite",
        processing_storage_path: Path | str = "processing_storage.sqlite",
    ):
        self.ingestion_state_path = Path(ingestion_state_path)
        self.raw_storage_path = Path(raw_storage_path)
        self.processing_storage_path = Path(processing_storage_path)

    def get_ingestion_state_url(self) -> str:
        """Получить SQLAlchemy URL для ingestion_state.sqlite."""
        return f"sqlite+aiosqlite:///{self.ingestion_state_path}"

    def get_raw_storage_url(self) -> str:
        """Получить SQLAlchemy URL для raw_storage.sqlite."""
        return f"sqlite+aiosqlite:///{self.raw_storage_path}"

    def get_processing_storage_url(self) -> str:
        """Получить SQLAlchemy URL для processing_storage.sqlite."""
        return f"sqlite+aiosqlite:///{self.processing_storage_path}"


class Database:
    """
    Контейнер для SQLAlchemy engines и sessionmakers.

    Session 24: поддержка SQLite и PostgreSQL через engine factory.

    Использование:
    ```python
    # Вариант 1: из Settings (рекомендуется)
    from tg_parser.config.settings import settings
    db = Database.from_settings(settings)
    await db.init()

    # Вариант 2: legacy с DatabaseConfig (backward compatibility)
    config = DatabaseConfig()
    db = Database(config)
    await db.init()

    async with db.ingestion_state_session() as session:
        # ...
    ```
    """

    def __init__(self, config: DatabaseConfig | None = None, settings: Settings | None = None):
        """
        Инициализация Database.
        
        Args:
            config: DatabaseConfig (legacy, backward compatibility)
            settings: Settings (новый способ, Session 24)
        """
        if config is None and settings is None:
            raise ValueError("Either config or settings must be provided")
            
        self.config = config
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
        Создать Database из Settings (рекомендуемый способ).
        
        Args:
            settings: Application settings
            
        Returns:
            Database instance
        """
        return cls(settings=settings)

    async def init(self) -> None:
        """Инициализировать engines и sessionmakers."""
        if self.settings is not None:
            # New way: use engine factory with settings
            self.ingestion_state_engine = create_engine_from_settings(
                self.settings, "ingestion", echo=False
            )
            self.raw_storage_engine = create_engine_from_settings(
                self.settings, "raw", echo=False
            )
            self.processing_storage_engine = create_engine_from_settings(
                self.settings, "processing", echo=False
            )
        else:
            # Legacy way: use DatabaseConfig (backward compatibility)
            from sqlalchemy.ext.asyncio import create_async_engine
            
            self.ingestion_state_engine = create_async_engine(
                self.config.get_ingestion_state_url(),
                echo=False,
            )
            self.raw_storage_engine = create_async_engine(
                self.config.get_raw_storage_url(),
                echo=False,
            )
            self.processing_storage_engine = create_async_engine(
                self.config.get_processing_storage_url(),
                echo=False,
            )

        # Create sessionmakers
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
        """Создать session для ingestion_state.sqlite."""
        if not self._ingestion_state_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._ingestion_state_sessionmaker()

    def raw_storage_session(self) -> AsyncSession:
        """Создать session для raw_storage.sqlite."""
        if not self._raw_storage_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._raw_storage_sessionmaker()

    def processing_storage_session(self) -> AsyncSession:
        """Создать session для processing_storage.sqlite."""
        if not self._processing_storage_sessionmaker:
            raise RuntimeError("Database not initialized. Call await db.init() first.")
        return self._processing_storage_sessionmaker()
