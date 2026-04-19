"""
Инициализация баз данных TG_parser.

Session 22: Обновлено для использования Alembic миграций.
Session 39: PostgreSQL-only, удалён SQLite support.
"""

import subprocess
import sys
from pathlib import Path

import typer


def run_alembic_upgrade(db_name: str, project_root: Path) -> bool:
    """
    Запустить alembic upgrade для конкретной базы.

    После DI-7 используем per-DB статический ini (``alembic_<db>.ini``).
    Раньше этот хелпер указывал на общий ``alembic.ini`` и работал только
    благодаря тому, что для команды ``upgrade`` ``env.py`` успевает
    переопределить ``version_locations`` через ``set_main_option``
    до момента, как alembic построит ``ScriptDirectory``. Это race-condition
    в маскировке: любой ``check``/``heads``/``current`` отсюда упал бы на
    «Multiple head revisions». Per-DB ini убирает оба риска.

    Args:
        db_name: Имя базы (ingestion/raw/processing)
        project_root: Корень проекта

    Returns:
        True если успешно
    """
    alembic_ini = project_root / "migrations" / f"alembic_{db_name}.ini"

    if not alembic_ini.exists():
        # DI-19 (Sprint A.7): the legacy DDL fallback was removed; alembic
        # is the only source of truth for the schema, so a missing per-db
        # ini file is now fatal (was previously a soft warning + raw DDL).
        typer.echo(
            f"  ❌  {alembic_ini} not found — alembic is the sole source of "
            f"truth post-DI-19; cannot continue.",
            err=True,
        )
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
            typer.echo(f"  ❌  Alembic upgrade failed для {db_name}", err=True)
            if result.stderr:
                typer.echo(f"  {result.stderr}", err=True)
            return False

        return True

    except FileNotFoundError:
        # DI-19: alembic must be installed (declared in pyproject.toml);
        # missing alembic is a packaging bug, not a recoverable runtime
        # condition.
        typer.echo(
            "  ❌  alembic not installed — should be a hard dependency (see pyproject.toml).",
            err=True,
        )
        return False
    except Exception as e:
        typer.echo(f"  ❌  Ошибка Alembic: {e}", err=True)
        return False


def init_databases_sync() -> None:
    """
    Синхронная обёртка для CLI команды.

    Session 22: Alembic-only since DI-19 (Sprint A.7); the raw-DDL fallback
    branch was removed alongside ``init_*_schema`` helpers — alembic is the
    sole source of truth for schema state.
    """
    from tg_parser.cli.db_cmd import get_project_root

    project_root = get_project_root()
    databases = ["ingestion", "raw", "processing"]

    typer.echo("  🔄 Применение миграций через Alembic...")

    failed: list[str] = []
    for db_name in databases:
        typer.echo(f"  📦 База: {db_name}")
        if not run_alembic_upgrade(db_name, project_root):
            failed.append(db_name)

    if failed:
        # Diagnostic-only: no fallback path remains; surface the failed
        # branches so the operator can inspect logs / fix migrations
        # before retrying.  See docs/notes/SAFE_MIGRATION_ON_DEV.md.
        typer.echo(
            f"\n  ❌  Alembic upgrade failed for: {', '.join(failed)}.\n"
            f"     Inspect the per-branch error above; alembic is the only "
            f"path to a valid schema (DI-19).",
            err=True,
        )
        raise typer.Exit(code=1)
