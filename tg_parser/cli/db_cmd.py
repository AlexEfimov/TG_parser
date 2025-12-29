"""
CLI команды для управления миграциями базы данных (Session 22).

Использует Alembic для версионирования схемы БД.
"""

import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="db",
    help="Управление миграциями базы данных (Alembic)",
)


def get_project_root() -> Path:
    """Получить корень проекта."""
    return Path(__file__).parent.parent.parent


def run_alembic_command(args: list[str], db_name: str = "ingestion") -> int:
    """
    Запустить команду alembic.
    
    Args:
        args: Аргументы для alembic
        db_name: Имя базы данных (ingestion/raw/processing)
    
    Returns:
        Exit code
    """
    project_root = get_project_root()
    alembic_ini = project_root / "migrations" / "alembic.ini"
    
    if not alembic_ini.exists():
        typer.echo(f"❌ Файл конфигурации не найден: {alembic_ini}", err=True)
        typer.echo("   Убедитесь, что вы находитесь в корне проекта.", err=True)
        return 1
    
    # Собираем команду alembic
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(alembic_ini),
        "-x",
        f"db_name={db_name}",
    ] + args
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            check=False,
        )
        return result.returncode
    except FileNotFoundError:
        typer.echo("❌ Alembic не установлен. Установите: pip install alembic", err=True)
        return 1
    except Exception as e:
        typer.echo(f"❌ Ошибка при выполнении команды: {e}", err=True)
        return 1


@app.command()
def upgrade(
    db: str = typer.Option(
        "all",
        "--db",
        help="База данных: ingestion, raw, processing, или all",
    ),
    revision: str = typer.Argument("head", help="Целевая ревизия (по умолчанию: head)"),
):
    """
    Применить миграции (upgrade).
    
    Примеры:
        tg-parser db upgrade                 # Все базы до head
        tg-parser db upgrade --db ingestion  # Только ingestion
        tg-parser db upgrade 0001            # До конкретной ревизии
    """
    databases = ["ingestion", "raw", "processing"] if db == "all" else [db]
    
    if db not in ["all", "ingestion", "raw", "processing"]:
        typer.echo(f"❌ Неизвестная база данных: {db}", err=True)
        typer.echo("   Используйте: ingestion, raw, processing, или all", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"🔄 Применение миграций до {revision}...\n")
    
    failed = []
    for db_name in databases:
        typer.echo(f"📦 База: {db_name}")
        exit_code = run_alembic_command(["upgrade", revision], db_name=db_name)
        
        if exit_code != 0:
            failed.append(db_name)
            typer.echo(f"❌ Ошибка в базе {db_name}\n", err=True)
        else:
            typer.echo(f"✅ {db_name} обновлена\n")
    
    if failed:
        typer.echo(f"\n❌ Ошибки в базах: {', '.join(failed)}", err=True)
        raise typer.Exit(code=1)
    
    typer.echo("\n✅ Все миграции применены успешно!")


@app.command()
def downgrade(
    db: str = typer.Option(
        ...,
        "--db",
        help="База данных: ingestion, raw, или processing",
    ),
    revision: str = typer.Argument("-1", help="Целевая ревизия (по умолчанию: -1)"),
):
    """
    Откатить миграции (downgrade).
    
    ⚠️  Внимание: downgrade может привести к потере данных!
    
    Примеры:
        tg-parser db downgrade --db ingestion      # Откат на 1 ревизию назад
        tg-parser db downgrade --db raw base       # Откат до base (удалит все таблицы)
        tg-parser db downgrade --db processing 0001  # Откат до конкретной ревизии
    """
    if db not in ["ingestion", "raw", "processing"]:
        typer.echo(f"❌ Неизвестная база данных: {db}", err=True)
        typer.echo("   Используйте: ingestion, raw, или processing", err=True)
        raise typer.Exit(code=1)
    
    # Подтверждение для откатов
    if not typer.confirm(
        f"⚠️  Вы уверены, что хотите откатить миграции базы {db} до {revision}?"
    ):
        typer.echo("Отменено.")
        return
    
    typer.echo(f"\n🔄 Откат миграций базы {db} до {revision}...\n")
    
    exit_code = run_alembic_command(["downgrade", revision], db_name=db)
    
    if exit_code != 0:
        typer.echo(f"\n❌ Ошибка при откате миграций", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"\n✅ Откат выполнен успешно!")


@app.command()
def current(
    db: str = typer.Option(
        "all",
        "--db",
        help="База данных: ingestion, raw, processing, или all",
    ),
):
    """
    Показать текущую версию схемы.
    
    Примеры:
        tg-parser db current                 # Все базы
        tg-parser db current --db ingestion  # Только ingestion
    """
    databases = ["ingestion", "raw", "processing"] if db == "all" else [db]
    
    if db not in ["all", "ingestion", "raw", "processing"]:
        typer.echo(f"❌ Неизвестная база данных: {db}", err=True)
        raise typer.Exit(code=1)
    
    typer.echo("📊 Текущие версии схем:\n")
    
    for db_name in databases:
        typer.echo(f"📦 База: {db_name}")
        run_alembic_command(["current"], db_name=db_name)
        typer.echo()


@app.command()
def history(
    db: str = typer.Option(
        "ingestion",
        "--db",
        help="База данных: ingestion, raw, или processing",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Подробный вывод"),
):
    """
    Показать историю миграций.
    
    Примеры:
        tg-parser db history --db ingestion    # История ingestion
        tg-parser db history --db raw -v       # История raw с деталями
    """
    if db not in ["ingestion", "raw", "processing"]:
        typer.echo(f"❌ Неизвестная база данных: {db}", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"📜 История миграций базы {db}:\n")
    
    args = ["history"]
    if verbose:
        args.append("-v")
    
    run_alembic_command(args, db_name=db)


@app.command()
def stamp(
    db: str = typer.Option(
        ...,
        "--db",
        help="База данных: ingestion, raw, или processing",
    ),
    revision: str = typer.Argument(..., help="Ревизия для stamp"),
):
    """
    Пометить текущее состояние БД определенной ревизией (без изменений схемы).
    
    Используется для синхронизации существующей БД с миграциями.
    
    Примеры:
        tg-parser db stamp --db ingestion head  # Пометить как head
        tg-parser db stamp --db raw 0001        # Пометить как 0001
    """
    if db not in ["ingestion", "raw", "processing"]:
        typer.echo(f"❌ Неизвестная база данных: {db}", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"🏷️  Помечаем базу {db} как {revision}...\n")
    
    exit_code = run_alembic_command(["stamp", revision], db_name=db)
    
    if exit_code != 0:
        typer.echo(f"\n❌ Ошибка при stamp", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"\n✅ База {db} помечена как {revision}")


if __name__ == "__main__":
    app()

