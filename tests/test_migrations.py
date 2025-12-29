"""
Тесты для Alembic миграций (Session 22).

Проверяет:
- Применение миграций на пустую БД
- Откат миграций (downgrade)
- Multi-database support
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def temp_db_dir():
    """Создать временную директорию для тестовых БД."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def project_root():
    """Получить корень проекта."""
    return Path(__file__).parent.parent


# Mapping of database names to their head revision IDs (Session 22/23)
DB_HEAD_REVISIONS = {
    "ingestion": "89f91e768b9b",
    "raw": "5c658f04eff0",
    "processing": "f40d85317f03",
}


def run_alembic(project_root: Path, db_name: str, command: str, revision: str = "head") -> subprocess.CompletedProcess:
    """
    Запустить команду alembic.
    
    Args:
        project_root: Корень проекта
        db_name: Имя базы (ingestion/raw/processing)
        command: Команда (upgrade/downgrade/current)
        revision: Ревизия (head/-1/base)
    
    Returns:
        CompletedProcess
    """
    alembic_ini = project_root / "migrations" / "alembic.ini"
    
    # Если revision="head", используем конкретную head для этой БД
    # (Session 23: fix for multiple heads issue)
    if revision == "head" and db_name in DB_HEAD_REVISIONS:
        revision = DB_HEAD_REVISIONS[db_name]
    
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(alembic_ini),
        "-x",
        f"db_name={db_name}",
        command,
    ]
    
    if command in ["upgrade", "downgrade"]:
        cmd.append(revision)
    
    return subprocess.run(
        cmd,
        cwd=str(project_root),
        check=False,
        capture_output=True,
        text=True,
    )


def get_tables(db_path: Path) -> set[str]:
    """
    Получить список таблиц в БД.
    
    Args:
        db_path: Путь к SQLite БД
    
    Returns:
        Множество имён таблиц
    """
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()
    return tables


def test_ingestion_migration_upgrade(project_root):
    """Тест: миграция ingestion на пустую БД."""
    # Удаляем существующую БД
    db_path = project_root / "ingestion_state.sqlite"
    if db_path.exists():
        db_path.unlink()
    
    # Применяем миграцию
    result = run_alembic(project_root, "ingestion", "upgrade", "head")
    
    assert result.returncode == 0, f"Migration failed: {result.stderr}"
    assert db_path.exists(), "Database file was not created"
    
    # Проверяем созданные таблицы
    tables = get_tables(db_path)
    expected_tables = {
        "sources",
        "comment_cursors",
        "source_attempts",
        "alembic_version_ingestion",
    }
    
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"


def test_raw_migration_upgrade(project_root):
    """Тест: миграция raw на пустую БД."""
    db_path = project_root / "raw_storage.sqlite"
    if db_path.exists():
        db_path.unlink()
    
    result = run_alembic(project_root, "raw", "upgrade", "head")
    
    assert result.returncode == 0, f"Migration failed: {result.stderr}"
    assert db_path.exists(), "Database file was not created"
    
    tables = get_tables(db_path)
    expected_tables = {
        "raw_messages",
        "raw_conflicts",
        "alembic_version_raw",
    }
    
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"


def test_processing_migration_upgrade(project_root):
    """Тест: миграция processing на пустую БД."""
    db_path = project_root / "processing_storage.sqlite"
    if db_path.exists():
        db_path.unlink()
    
    result = run_alembic(project_root, "processing", "upgrade", "head")
    
    assert result.returncode == 0, f"Migration failed: {result.stderr}"
    assert db_path.exists(), "Database file was not created"
    
    tables = get_tables(db_path)
    expected_tables = {
        "processed_documents",
        "processing_failures",
        "topic_cards",
        "topic_bundles",
        "api_jobs",
        "agent_states",
        "task_history",
        "agent_stats",
        "handoff_history",
        "alembic_version_processing",
    }
    
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"


def test_ingestion_downgrade_cycle(project_root):
    """Тест: upgrade -> downgrade цикл для ingestion."""
    db_path = project_root / "ingestion_state.sqlite"
    if db_path.exists():
        db_path.unlink()
    
    # Upgrade to head
    result = run_alembic(project_root, "ingestion", "upgrade", "head")
    assert result.returncode == 0, f"Upgrade failed: {result.stderr}"
    
    tables_after_upgrade = get_tables(db_path)
    assert len(tables_after_upgrade) > 1, "No tables created after upgrade"
    
    # Downgrade to base
    result = run_alembic(project_root, "ingestion", "downgrade", "base")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"
    
    tables_after_downgrade = get_tables(db_path)
    # После downgrade должна остаться только alembic_version_ingestion
    assert tables_after_downgrade == {"alembic_version_ingestion"}, \
        f"Tables remaining after downgrade: {tables_after_downgrade}"


def test_raw_downgrade_cycle(project_root):
    """Тест: upgrade -> downgrade цикл для raw."""
    db_path = project_root / "raw_storage.sqlite"
    if db_path.exists():
        db_path.unlink()
    
    # Upgrade
    result = run_alembic(project_root, "raw", "upgrade", "head")
    assert result.returncode == 0
    
    tables_after_upgrade = get_tables(db_path)
    assert len(tables_after_upgrade) > 1
    
    # Downgrade
    result = run_alembic(project_root, "raw", "downgrade", "base")
    assert result.returncode == 0
    
    tables_after_downgrade = get_tables(db_path)
    assert tables_after_downgrade == {"alembic_version_raw"}


def test_processing_downgrade_cycle(project_root):
    """Тест: upgrade -> downgrade цикл для processing."""
    db_path = project_root / "processing_storage.sqlite"
    if db_path.exists():
        db_path.unlink()
    
    # Upgrade
    result = run_alembic(project_root, "processing", "upgrade", "head")
    assert result.returncode == 0
    
    tables_after_upgrade = get_tables(db_path)
    assert len(tables_after_upgrade) > 1
    
    # Downgrade
    result = run_alembic(project_root, "processing", "downgrade", "base")
    assert result.returncode == 0
    
    tables_after_downgrade = get_tables(db_path)
    assert tables_after_downgrade == {"alembic_version_processing"}


def test_multi_database_independence(project_root):
    """Тест: миграции баз данных независимы друг от друга."""
    # Удаляем все БД
    for db_name in ["ingestion_state", "raw_storage", "processing_storage"]:
        db_path = project_root / f"{db_name}.sqlite"
        if db_path.exists():
            db_path.unlink()
    
    # Применяем миграцию только для ingestion
    result = run_alembic(project_root, "ingestion", "upgrade", "head")
    assert result.returncode == 0
    
    ingestion_path = project_root / "ingestion_state.sqlite"
    raw_path = project_root / "raw_storage.sqlite"
    processing_path = project_root / "processing_storage.sqlite"
    
    # Проверяем, что создана только ingestion
    assert ingestion_path.exists(), "Ingestion DB not created"
    assert not raw_path.exists(), "Raw DB should not be created"
    assert not processing_path.exists(), "Processing DB should not be created"
    
    # Применяем остальные
    run_alembic(project_root, "raw", "upgrade", "head")
    run_alembic(project_root, "processing", "upgrade", "head")
    
    # Все БД существуют
    assert raw_path.exists()
    assert processing_path.exists()


def test_alembic_version_table_per_database(project_root):
    """Тест: у каждой БД своя таблица версий alembic."""
    # Убедимся, что все БД мигрированы
    for db_name in ["ingestion", "raw", "processing"]:
        run_alembic(project_root, db_name, "upgrade", "head")
    
    # Проверяем наличие отдельных version таблиц
    ingestion_tables = get_tables(project_root / "ingestion_state.sqlite")
    raw_tables = get_tables(project_root / "raw_storage.sqlite")
    processing_tables = get_tables(project_root / "processing_storage.sqlite")
    
    assert "alembic_version_ingestion" in ingestion_tables
    assert "alembic_version_raw" in raw_tables
    assert "alembic_version_processing" in processing_tables
    
    # Проверяем, что версии записаны
    for db_path, table_name in [
        (project_root / "ingestion_state.sqlite", "alembic_version_ingestion"),
        (project_root / "raw_storage.sqlite", "alembic_version_raw"),
        (project_root / "processing_storage.sqlite", "alembic_version_processing"),
    ]:
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT version_num FROM {table_name}"))
            version = result.fetchone()
            assert version is not None, f"No version recorded in {table_name}"
        engine.dispose()

