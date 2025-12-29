"""
Инициализация баз данных TG_parser.

Session 22: Обновлено для использования Alembic миграций.
Создаёт SQLite файлы и таблицы через Alembic upgrade.
"""

import subprocess
import sys
from pathlib import Path

import typer

from tg_parser.config import settings
from tg_parser.storage.sqlite import DatabaseConfig


def run_alembic_upgrade(db_name: str, project_root: Path) -> bool:
    """
    Запустить alembic upgrade для конкретной базы.
    
    Args:
        db_name: Имя базы (ingestion/raw/processing)
        project_root: Корень проекта
    
    Returns:
        True если успешно
    """
    alembic_ini = project_root / "migrations" / "alembic.ini"
    
    if not alembic_ini.exists():
        typer.echo(f"  ⚠️  Файл {alembic_ini} не найден, используем fallback", err=True)
        return False
    
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(alembic_ini),
        "-x",
        f"db_name={db_name}",
        "upgrade",
        "head",
    ]
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            check=False,
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            typer.echo(f"  ⚠️  Alembic upgrade failed для {db_name}", err=True)
            if result.stderr:
                typer.echo(f"  {result.stderr}", err=True)
            return False
        
        return True
        
    except FileNotFoundError:
        typer.echo("  ⚠️  Alembic не установлен, используем fallback", err=True)
        return False
    except Exception as e:
        typer.echo(f"  ⚠️  Ошибка Alembic: {e}", err=True)
        return False


async def init_databases_fallback(config: DatabaseConfig) -> None:
    """
    Fallback: Инициализация через прямой DDL (для обратной совместимости).
    
    Args:
        config: Конфигурация путей к SQLite файлам
    """
    from tg_parser.storage.sqlite import (
        Database,
        init_ingestion_state_schema,
        init_processing_storage_schema,
        init_raw_storage_schema,
    )
    
    db = Database(config)
    await db.init()

    try:
        typer.echo("  📦 Создание ingestion_state.sqlite (DDL)...")
        await init_ingestion_state_schema(db.ingestion_state_engine)

        typer.echo("  📦 Создание raw_storage.sqlite (DDL)...")
        await init_raw_storage_schema(db.raw_storage_engine)

        typer.echo("  📦 Создание processing_storage.sqlite (DDL)...")
        await init_processing_storage_schema(db.processing_storage_engine)

    finally:
        await db.close()


def init_databases_sync() -> None:
    """
    Синхронная обёртка для CLI команды.
    
    Session 22: Использует Alembic миграции вместо прямого DDL.
    """
    import asyncio
    
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )

    # Проверяем, что директории существуют
    for path in [
        config.ingestion_state_path,
        config.raw_storage_path,
        config.processing_storage_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)

    # Получаем корень проекта
    project_root = Path(__file__).parent.parent.parent
    
    # Пытаемся использовать Alembic
    use_alembic = True
    databases = ["ingestion", "raw", "processing"]
    
    typer.echo("  🔄 Применение миграций через Alembic...")
    
    for db_name in databases:
        typer.echo(f"  📦 База: {db_name}")
        success = run_alembic_upgrade(db_name, project_root)
        
        if not success:
            use_alembic = False
            break
    
    # Fallback на старый DDL метод если Alembic не работает
    if not use_alembic:
        typer.echo("\n  ⚠️  Alembic недоступен, используем прямой DDL...")
        asyncio.run(init_databases_fallback(config))


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
