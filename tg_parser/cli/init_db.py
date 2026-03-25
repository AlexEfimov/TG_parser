"""
Инициализация баз данных TG_parser.

Session 22: Обновлено для использования Alembic миграций.
Session 39: PostgreSQL-only, удалён SQLite support.
"""

import subprocess
import sys
from pathlib import Path

import typer

from tg_parser.config import settings


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


async def init_databases_fallback() -> None:
    """
    Fallback: Инициализация через прямой DDL (если Alembic недоступен).
    """
    from tg_parser.storage.sqlalchemy import (
        Database,
        init_ingestion_state_schema,
        init_processing_storage_schema,
        init_raw_storage_schema,
    )
    
    db = Database.from_settings(settings)
    await db.init()

    try:
        typer.echo("  📦 Создание ingestion state schema (DDL)...")
        await init_ingestion_state_schema(db.ingestion_state_engine)

        typer.echo("  📦 Создание raw storage schema (DDL)...")
        await init_raw_storage_schema(db.raw_storage_engine)

        typer.echo("  📦 Создание processing storage schema (DDL)...")
        await init_processing_storage_schema(db.processing_storage_engine)

    finally:
        await db.close()


def init_databases_sync() -> None:
    """
    Синхронная обёртка для CLI команды.
    
    Session 22: Использует Alembic миграции вместо прямого DDL.
    """
    import asyncio
    
    project_root = Path(__file__).parent.parent.parent
    
    use_alembic = True
    databases = ["ingestion", "raw", "processing"]
    
    typer.echo("  🔄 Применение миграций через Alembic...")
    
    for db_name in databases:
        typer.echo(f"  📦 База: {db_name}")
        success = run_alembic_upgrade(db_name, project_root)
        
        if not success:
            use_alembic = False
            break
    
    if not use_alembic:
        typer.echo("\n  ⚠️  Alembic недоступен, используем прямой DDL...")
        asyncio.run(init_databases_fallback())
