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
        typer.echo("\n❌ Ошибка при откате миграций", err=True)
        raise typer.Exit(code=1)

    typer.echo("\n✅ Откат выполнен успешно!")


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
        typer.echo("\n❌ Ошибка при stamp", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"\n✅ База {db} помечена как {revision}")


@app.command()
def backup(
    output: str = typer.Option(
        None,
        "--output", "-o",
        help="Путь к файлу бэкапа (по умолчанию: data/backups/postgres_YYYYMMDD_HHMMSS.sql.gz)",
    ),
):
    """
    Создать бэкап PostgreSQL (pg_dump + gzip).

    Примеры:
        tg-parser db backup
        tg-parser db backup --output /tmp/my_backup.sql.gz
    """
    import gzip
    import shutil
    from datetime import datetime

    from tg_parser.config import settings

    if output:
        backup_path = Path(output)
    else:
        backup_dir = get_project_root() / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"postgres_{timestamp}.sql.gz"

    backup_path.parent.mkdir(parents=True, exist_ok=True)

    typer.echo("💾 Создание бэкапа PostgreSQL...")
    typer.echo(f"   • Host: {settings.db_host}:{settings.db_port}")
    typer.echo(f"   • Database: {settings.db_name}")
    typer.echo(f"   • Output: {backup_path}")

    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        typer.echo(
            "❌ pg_dump не найден. Установите PostgreSQL client или используйте docker/backup.sh",
            err=True,
        )
        raise typer.Exit(code=1)

    env = {
        **__import__("os").environ,
        "PGPASSWORD": settings.db_password,
    }
    cmd = [
        pg_dump,
        "--clean", "--if-exists",
        "-h", settings.db_host,
        "-p", str(settings.db_port),
        "-U", settings.db_user,
        settings.db_name,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, env=env, check=False)
        if result.returncode != 0:
            typer.echo(f"❌ pg_dump error: {result.stderr.decode().strip()}", err=True)
            raise typer.Exit(code=1)

        with gzip.open(backup_path, "wb") as f:
            f.write(result.stdout)

        size_mb = backup_path.stat().st_size / (1024 * 1024)
        typer.echo(f"\n✅ Бэкап создан: {backup_path} ({size_mb:.1f} MB)")

    except FileNotFoundError:
        typer.echo("❌ pg_dump не найден", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def restore(
    file: str = typer.Option(
        ...,
        "--file", "-f",
        help="Путь к файлу бэкапа (.sql.gz или .sql)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Пропустить подтверждение"),
):
    """
    Восстановить PostgreSQL из бэкапа.

    ⚠️  Внимание: текущие данные будут перезаписаны!

    Примеры:
        tg-parser db restore --file data/backups/postgres_20260331.sql.gz
        tg-parser db restore -f backup.sql.gz --yes
    """
    import gzip
    import shutil

    from tg_parser.config import settings

    backup_path = Path(file)
    if not backup_path.exists():
        typer.echo(f"❌ Файл не найден: {backup_path}", err=True)
        raise typer.Exit(code=1)

    psql_bin = shutil.which("psql")
    if not psql_bin:
        typer.echo(
            "❌ psql не найден. Установите PostgreSQL client или используйте docker/restore.sh",
            err=True,
        )
        raise typer.Exit(code=1)

    size_mb = backup_path.stat().st_size / (1024 * 1024)
    typer.echo("🔄 Восстановление из бэкапа:")
    typer.echo(f"   • File: {backup_path} ({size_mb:.1f} MB)")
    typer.echo(f"   • Target: {settings.db_host}:{settings.db_port}/{settings.db_name}")

    if not yes:
        if not typer.confirm("\n⚠️  Текущие данные будут перезаписаны. Продолжить?"):
            typer.echo("Отменено.")
            return

    env = {
        **__import__("os").environ,
        "PGPASSWORD": settings.db_password,
    }
    psql_cmd = [
        psql_bin,
        "-h", settings.db_host,
        "-p", str(settings.db_port),
        "-U", settings.db_user,
        "-d", settings.db_name,
        "-v", "ON_ERROR_STOP=1",
    ]

    try:
        if str(backup_path).endswith(".gz"):
            with gzip.open(backup_path, "rb") as f:
                sql_data = f.read()
        else:
            sql_data = backup_path.read_bytes()

        result = subprocess.run(
            psql_cmd,
            input=sql_data,
            capture_output=True,
            env=env,
            check=False,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode().strip()
            typer.echo(f"❌ Ошибка восстановления:\n{stderr}", err=True)
            raise typer.Exit(code=1)

        typer.echo("\n✅ Восстановление завершено!")

    except Exception as e:
        typer.echo(f"❌ Ошибка: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command("list-backups")
def list_backups(
    directory: str = typer.Option(
        None,
        "--dir", "-d",
        help="Директория с бэкапами (по умолчанию: data/backups/)",
    ),
):
    """
    Список существующих бэкапов.

    Примеры:
        tg-parser db list-backups
        tg-parser db list-backups --dir /custom/backups
    """
    from datetime import datetime

    backup_dir = Path(directory) if directory else get_project_root() / "data" / "backups"

    if not backup_dir.exists():
        typer.echo(f"📂 Директория не существует: {backup_dir}")
        typer.echo("   Бэкапы ещё не создавались.")
        return

    backups = sorted(backup_dir.glob("postgres_*.sql.gz"), reverse=True)

    if not backups:
        typer.echo(f"📂 Бэкапы не найдены в {backup_dir}")
        return

    typer.echo(f"📂 Бэкапы в {backup_dir}:\n")
    typer.echo(f"  {'#':<4} {'Файл':<40} {'Размер':<10} {'Дата'}")
    typer.echo(f"  {'─'*4} {'─'*40} {'─'*10} {'─'*20}")

    for i, bp in enumerate(backups, 1):
        size = bp.stat().st_size
        if size >= 1024 * 1024:
            size_str = f"{size / (1024*1024):.1f} MB"
        else:
            size_str = f"{size / 1024:.0f} KB"

        mtime = datetime.fromtimestamp(bp.stat().st_mtime)
        typer.echo(f"  {i:<4} {bp.name:<40} {size_str:<10} {mtime:%Y-%m-%d %H:%M}")

    typer.echo(f"\n  Всего: {len(backups)} бэкап(ов)")


if __name__ == "__main__":
    app()

