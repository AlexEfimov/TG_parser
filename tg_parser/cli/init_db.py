"""
Инициализация баз данных TG_parser.

Создаёт SQLite файлы и таблицы через DDL схемы.
"""

import asyncio
from pathlib import Path

import typer

from tg_parser.config import settings
from tg_parser.storage.sqlite import (
    Database,
    DatabaseConfig,
    init_ingestion_state_schema,
    init_processing_storage_schema,
    init_raw_storage_schema,
)


async def init_databases(config: DatabaseConfig) -> None:
    """
    Асинхронная инициализация всех баз данных.
    
    Args:
        config: Конфигурация путей к SQLite файлам
    """
    db = Database(config)
    await db.init()
    
    try:
        # Создаём таблицы для каждого хранилища
        typer.echo("  📦 Создание ingestion_state.sqlite...")
        await init_ingestion_state_schema(db.ingestion_state_engine)
        
        typer.echo("  📦 Создание raw_storage.sqlite...")
        await init_raw_storage_schema(db.raw_storage_engine)
        
        typer.echo("  📦 Создание processing_storage.sqlite...")
        await init_processing_storage_schema(db.processing_storage_engine)
        
    finally:
        await db.close()


def init_databases_sync() -> None:
    """
    Синхронная обёртка для CLI команды.
    """
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )
    
    # Проверяем, что директории существуют
    for path in [config.ingestion_state_path, config.raw_storage_path, config.processing_storage_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
    
    # Запускаем async функцию
    asyncio.run(init_databases(config))


def check_databases_exist(config: DatabaseConfig) -> bool:
    """
    Проверить, существуют ли уже базы данных.
    
    Args:
        config: Конфигурация путей
        
    Returns:
        True если хотя бы одна база существует
    """
    return (
        config.ingestion_state_path.exists()
        or config.raw_storage_path.exists()
        or config.processing_storage_path.exists()
    )
