"""
Backup directory resolution.

Regression guard: dumps must not silently land on the deployment's system
partition when the project root lives there (redboxtgbot, 2026-08-03).
"""

from pathlib import Path

from tg_parser.cli.db_cmd import get_backup_dir, get_project_root


def test_defaults_to_project_data(monkeypatch):
    monkeypatch.delenv("TG_PARSER_BACKUP_DIR", raising=False)
    assert get_backup_dir() == get_project_root() / "data" / "backups"


def test_honours_env(monkeypatch):
    monkeypatch.setenv("TG_PARSER_BACKUP_DIR", "/mnt/data/backups/tg_parser/nightly")
    assert get_backup_dir() == Path("/mnt/data/backups/tg_parser/nightly")


def test_empty_env_falls_back(monkeypatch):
    """Пустая переменная — это «не задано», а не «писать в корень ФС»."""
    monkeypatch.setenv("TG_PARSER_BACKUP_DIR", "")
    assert get_backup_dir() == get_project_root() / "data" / "backups"
