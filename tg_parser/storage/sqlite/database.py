"""
База данных SQLite для TG_parser (MVP).

Реализует TR-14/TR-17/TR-42: три отдельных SQLite-файла.
"""

from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


class DatabaseConfig:
    """
    Конфигурация путей к SQLite-файлам.
    
    TR-17: разделение на 3 файла.
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
    
    Использование:
    ```python
    config = DatabaseConfig()
    db = Database(config)
    await db.init()
    
    async with db.ingestion_state_session() as session:
        # ...
    ```
    """
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        
        # Engines
        self.ingestion_state_engine: Optional[AsyncEngine] = None
        self.raw_storage_engine: Optional[AsyncEngine] = None
        self.processing_storage_engine: Optional[AsyncEngine] = None
        
        # Sessionmakers
        self._ingestion_state_sessionmaker: Optional[sessionmaker] = None
        self._raw_storage_sessionmaker: Optional[sessionmaker] = None
        self._processing_storage_sessionmaker: Optional[sessionmaker] = None
    
    async def init(self) -> None:
        """Инициализировать engines и sessionmakers."""
        # Ingestion state
        self.ingestion_state_engine = create_async_engine(
            self.config.get_ingestion_state_url(),
            echo=False,
        )
        self._ingestion_state_sessionmaker = sessionmaker(
            self.ingestion_state_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        # Raw storage
        self.raw_storage_engine = create_async_engine(
            self.config.get_raw_storage_url(),
            echo=False,
        )
        self._raw_storage_sessionmaker = sessionmaker(
            self.raw_storage_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        # Processing storage
        self.processing_storage_engine = create_async_engine(
            self.config.get_processing_storage_url(),
            echo=False,
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
