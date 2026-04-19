"""Testcontainers-based PostgreSQL fixtures for the migration runtime smoke.

Sprint A.6 / DI-9 phase 2 (19.04.2026); pruned in Sprint A.7 / DI-19 once
the legacy ``init_*_schema()`` helpers and the alembic-vs-legacy parity
test were dropped.

Used by
-------
- ``tests/test_migrations_runtime_upgrade.py`` — runtime mirror of the static
  ``test_migrations_self_contained`` guardrail (DI-9 phase 1).  Boots one
  pgvector PG17 container per test session, runs ``alembic upgrade head``
  against a clean DB for each logical branch, asserts tables/indexes that
  AST analysis cannot see (``IF NOT EXISTS`` idempotency, runtime-only DDL
  via ``op.execute(text(...))``).

Public API (stable for downstream reuse):
- ``pgvector_container``                — session fixture, one container.
- ``sync_url_for_db(container, db)``    — build ``postgresql://...`` URL.
- ``async_url_for_db(container, db)``   — build ``postgresql+asyncpg://...`` URL.
- ``create_database(container, db)``    — fresh DB + ``CREATE EXTENSION vector``.
- ``alembic_upgrade_for_branch(...)``   — create DB + ``alembic upgrade head``.
- ``requires_testcontainers``           — ``pytest.mark.skipif`` marker.

The legacy parity-test helpers (``make_async_engine``, ``dump_schema``,
``_normalize_pg_dump``, ``_sort_create_table_columns``) lived here through
DI-9; they were removed alongside ``test_alembic_vs_legacy_ddl_parity.py``
in DI-19 — alembic is now the sole source of truth, so a normalized
pg_dump diff against the legacy DDL has no test left to serve.

Design notes (see docs/notes/START_PROMPT_SPRINT_A6_DI9_PHASE2.md):
- Tests are opt-in via ``TEST_TESTCONTAINERS=1`` so that the default pytest
  run on a Docker-less host (e.g. CI's ``test`` job) skips them silently.
- ``asyncio`` loop lifetime: ``pytest-asyncio`` uses a per-function loop;
  the session-scoped ``pgvector_container`` is sync and does not hold any
  asyncpg engine.  Each test builds its own ``AsyncEngine`` if needed and
  disposes it in the same loop.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover — dep is opt-in for test infra
    PostgresContainer = None  # type: ignore[assignment,misc]


REPO_ROOT = Path(__file__).resolve().parent.parent
PGVECTOR_IMAGE = "pgvector/pgvector:pg17"
# PostgresContainer's default admin DB is "test"; we pin to "postgres" to
# match the conventional superuser DB used for CREATE DATABASE / DROP
# DATABASE statements and avoid confusion with test helper DBs (e.g.
# ``alembic_<branch>``) that live alongside it.
_ADMIN_DB_NAME = "postgres"

# Opt-in: testcontainers needs a Docker daemon reachable at the host socket
# (Docker Desktop / OrbStack on macOS, ``/var/run/docker.sock`` on Linux).
# Defaulting to skip keeps ``pytest`` green on hosts without Docker.
_TESTCONTAINERS_ENABLED = bool(int(os.environ.get("TEST_TESTCONTAINERS", "0")))
requires_testcontainers = pytest.mark.skipif(
    not _TESTCONTAINERS_ENABLED or PostgresContainer is None,
    reason=(
        "set TEST_TESTCONTAINERS=1 and install testcontainers[postgres]>=4.8 "
        "(requires a reachable Docker daemon) to enable these tests"
    ),
)


@pytest.fixture(scope="session")
def pgvector_container() -> Generator[PostgresContainer, None, None]:
    """Spin one pgvector PG17 container for the whole test session.

    Session scope amortises the ~5–10 s container startup over all
    migration smoke tests.  Each test builds its own per-test database
    via :func:`create_database` or :func:`alembic_upgrade_for_branch`
    so there is no shared mutable state at the SQL level.
    """
    assert PostgresContainer is not None, "testcontainers[postgres] is not installed"
    container = PostgresContainer(PGVECTOR_IMAGE, dbname=_ADMIN_DB_NAME)
    container.start()
    try:
        # Sanity-enable pgvector on the admin DB; per-test DBs enable it
        # again in create_database() so that DROP DATABASE ... + recreate
        # doesn't leak the extension across tests.
        eng = create_engine(
            sync_url_for_db(container, _ADMIN_DB_NAME),
            isolation_level="AUTOCOMMIT",
        )
        with eng.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        eng.dispose()
        yield container
    finally:
        container.stop()


def sync_url_for_db(container: PostgresContainer, db_name: str) -> str:
    """Build a sync ``postgresql://`` URL for a specific DB in the container."""
    return (
        f"postgresql://{container.username}:{container.password}@"
        f"{container.get_container_host_ip()}:{container.get_exposed_port(5432)}/{db_name}"
    )


def async_url_for_db(container: PostgresContainer, db_name: str) -> str:
    """Build a ``postgresql+asyncpg://`` URL for a specific DB in the container."""
    return sync_url_for_db(container, db_name).replace("postgresql://", "postgresql+asyncpg://", 1)


def create_database(container: PostgresContainer, db_name: str) -> None:
    """(Re)create ``db_name`` inside the container and enable pgvector on it.

    Idempotent: existing DB is dropped first so tests see a deterministic
    blank slate.  Uses AUTOCOMMIT because PostgreSQL refuses ``CREATE
    DATABASE`` / ``DROP DATABASE`` inside a transaction block.
    """
    admin = create_engine(
        sync_url_for_db(container, _ADMIN_DB_NAME),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin.dispose()

    target = create_engine(
        sync_url_for_db(container, db_name),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with target.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        target.dispose()


def alembic_upgrade_for_branch(container: PostgresContainer, branch: str) -> str:
    """Create a fresh DB + run ``alembic upgrade head`` for one logical branch.

    Uses the per-DB ini files landed in DI-7 (Sprint A.5).  ``env.py``'s
    :func:`get_db_name` reads ``config.get_main_option("db_name")`` as a
    fallback after ``-x db_name=<branch>``; setting it via
    :meth:`Config.set_main_option` works without needing to fake the
    ``cmd_opts`` namespace.

    Returns the DB name (``alembic_<branch>``) so callers can build
    further engines against it.
    """
    assert branch in ("ingestion", "raw", "processing"), branch
    db = f"alembic_{branch}"
    create_database(container, db)
    cfg = Config(str(REPO_ROOT / "migrations" / f"alembic_{branch}.ini"))
    # env.py::get_url() prefers config's sqlalchemy.url over env / Settings.
    # async_engine_from_config in the online path expects an async-driver URL.
    cfg.set_main_option("sqlalchemy.url", async_url_for_db(container, db))
    cfg.set_main_option("db_name", branch)
    command.upgrade(cfg, "head")
    return db
