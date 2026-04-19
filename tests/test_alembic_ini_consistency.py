"""Static guardrail for DI-7 per-DB alembic ini files.

Each ``migrations/alembic_<db>.ini`` must:

* exist;
* declare exactly one ``version_locations`` line;
* point that ``version_locations`` at the matching branch directory
  (``migrations/versions/<db>``);
* keep ``script_location`` aligned with the shared base
  (``migrations/alembic.ini``) so that logging / template paths cannot
  silently drift between branches.

This protects the invariants that DI-7 relies on without requiring a live
PostgreSQL instance — pure file-on-disk inspection.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "migrations"
SHARED_BASE = MIGRATIONS / "alembic.ini"

DB_BRANCHES = ("ingestion", "raw", "processing")


def _read_main_option(content: str, option: str) -> list[str]:
    """Return all ``option = value`` lines from the file content (stripped)."""
    pattern = rf"^{re.escape(option)}\s*=\s*(.*)$"
    return [m.strip() for m in re.findall(pattern, content, re.MULTILINE)]


@pytest.mark.parametrize("db_name", DB_BRANCHES)
def test_per_db_alembic_ini_exists_and_is_scoped(db_name: str) -> None:
    """Per-DB ini exists and ``version_locations`` is scoped to one branch."""
    ini_path = MIGRATIONS / f"alembic_{db_name}.ini"
    assert ini_path.exists(), f"Missing per-DB alembic ini: {ini_path}"

    content = ini_path.read_text(encoding="utf-8")
    matches = _read_main_option(content, "version_locations")
    assert len(matches) == 1, (
        f"{ini_path} must declare exactly one version_locations line, got {matches!r}"
    )
    assert matches[0] == f"migrations/versions/{db_name}", (
        f"{ini_path} version_locations must be migrations/versions/{db_name}, got {matches[0]!r}"
    )


@pytest.mark.parametrize("db_name", DB_BRANCHES)
def test_per_db_alembic_ini_script_location_matches_shared_base(db_name: str) -> None:
    """``script_location`` is identical across all per-DB ini and the shared base."""
    ini_path = MIGRATIONS / f"alembic_{db_name}.ini"

    shared = _read_main_option(SHARED_BASE.read_text(encoding="utf-8"), "script_location")
    per_db = _read_main_option(ini_path.read_text(encoding="utf-8"), "script_location")

    assert len(shared) == 1, f"{SHARED_BASE} must declare exactly one script_location: {shared!r}"
    assert len(per_db) == 1, f"{ini_path} must declare exactly one script_location: {per_db!r}"
    assert per_db[0] == shared[0], (
        f"{ini_path} script_location ({per_db[0]!r}) must match {SHARED_BASE} ({shared[0]!r})"
    )
