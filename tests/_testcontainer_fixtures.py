"""Testcontainers-based PostgreSQL fixtures for migration smoke / parity tests.

Sprint A.6 / DI-9 phase 2 (19.04.2026).

Used by
-------
- ``tests/test_migrations_runtime_upgrade.py`` — runtime mirror of the static
  ``test_migrations_self_contained`` guardrail (DI-9 phase 1).  Boots one
  pgvector PG17 container per test session, runs ``alembic upgrade head``
  against a clean DB for each logical branch, asserts tables/indexes that
  AST analysis cannot see (``IF NOT EXISTS`` idempotency, runtime-only DDL
  via ``op.execute(text(...))``).
- ``tests/test_alembic_vs_legacy_ddl_parity.py`` — parity proof for Sprint
  A.7 / DI-19.  Dumps ``pg_dump --schema-only`` of the alembic-built schema
  and of the legacy ``init_*_schema()`` helper and diffs them modulo a
  stable normalization.
- (future, Sprint A.7) alembic-only fixtures replacing the legacy helpers
  in the ~11 remaining test files that still call ``init_*_schema()``.

Public API (stable for downstream reuse):
- ``pgvector_container``                — session fixture, one container.
- ``sync_url_for_db(container, db)``    — build ``postgresql://...`` URL.
- ``async_url_for_db(container, db)``   — build ``postgresql+asyncpg://...`` URL.
- ``create_database(container, db)``    — fresh DB + ``CREATE EXTENSION vector``.
- ``make_async_engine(container, db)``  — per-test ``AsyncEngine``.
- ``alembic_upgrade_for_branch(...)``   — create DB + ``alembic upgrade head``.
- ``dump_schema(container, db)``        — normalized ``pg_dump --schema-only``.
- ``requires_testcontainers``           — ``pytest.mark.skipif`` marker.

Design notes (see docs/notes/START_PROMPT_SPRINT_A6_DI9_PHASE2.md):
- Tests are opt-in via ``TEST_TESTCONTAINERS=1`` so that the default pytest
  run on a Docker-less host (e.g. CI's ``test`` job) skips them silently.
- ``pg_dump`` is invoked via ``container.exec([...])`` so we don't depend on
  a host-side postgres-client install.  The pgvector/pgvector:pg17 image
  ships with pg_dump.
- ``asyncio`` loop lifetime: ``pytest-asyncio`` uses a per-function loop;
  the session-scoped ``pgvector_container`` is sync and does not hold any
  asyncpg engine.  Each test builds its own ``AsyncEngine`` via
  ``make_async_engine`` and disposes it in the same loop.
"""

from __future__ import annotations

import os
import re
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover — dep is opt-in for test infra
    PostgresContainer = None  # type: ignore[assignment,misc]


REPO_ROOT = Path(__file__).resolve().parent.parent
PGVECTOR_IMAGE = "pgvector/pgvector:pg17"
# PostgresContainer's default admin DB is "test"; we pin to "postgres" to
# match the conventional superuser DB used for CREATE DATABASE / DROP
# DATABASE statements and avoid confusion with test helper DBs (e.g.
# ``alembic_<branch>`` / ``legacy_<branch>``) that live alongside it.
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
    migration smoke / parity tests.  Each test builds its own per-test
    database via :func:`create_database` or :func:`alembic_upgrade_for_branch`
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


def make_async_engine(container: PostgresContainer, db_name: str) -> AsyncEngine:
    """Create a fresh async SQLAlchemy engine for a per-test DB.

    Engines are bound to the asyncio loop they're created on, so
    callers **must** build a new engine per test (not reuse one from a
    session fixture) to interop with pytest-asyncio's per-function loop.
    """
    return create_async_engine(async_url_for_db(container, db_name), pool_pre_ping=True)


def alembic_upgrade_for_branch(container: PostgresContainer, branch: str) -> str:
    """Create a fresh DB + run ``alembic upgrade head`` for one logical branch.

    Uses the per-DB ini files landed in DI-7 (Sprint A.5).  ``env.py``'s
    :func:`get_db_name` reads ``config.get_main_option("db_name")`` as a
    fallback after ``-x db_name=<branch>``; setting it via
    :meth:`Config.set_main_option` works without needing to fake the
    ``cmd_opts`` namespace.

    Returns the DB name (``alembic_<branch>``) so callers can build
    further engines / dump schema against it.
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


def dump_schema(container: PostgresContainer, db_name: str) -> str:
    """Return a normalized ``pg_dump --schema-only`` for ``db_name``.

    pg_dump is invoked *inside* the container (``container.exec``) so the
    host doesn't need a postgres-client install.  ``PGPASSWORD`` is set
    explicitly even though the default postgres image uses ``trust`` on
    its local socket, to stay robust against hypothetical image rebuilds.
    Normalization strategy: drop SQL-comment lines (``-- Dumped from …``
    etc.) and sort top-level statements by (first token, full head line)
    so that OID-creation-order differences between alembic and the
    legacy DDL don't surface as false-positive diffs.
    """
    result = container.exec(
        [
            "env",
            f"PGPASSWORD={container.password}",
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--no-comments",
            "-U",
            container.username,
            db_name,
        ]
    )
    exit_code = getattr(result, "exit_code", None)
    output = getattr(result, "output", None)
    if exit_code is None:  # very old testcontainers shape: (code, output)
        exit_code, output = result  # type: ignore[misc]
    assert exit_code == 0, f"pg_dump failed for {db_name!r} (exit={exit_code}):\n{output!r}"
    raw = output.decode("utf-8") if isinstance(output, bytes) else output
    return _normalize_pg_dump(raw)


def _sort_create_table_columns(text_out: str) -> str:
    """Sort column / inline-constraint lines inside every CREATE TABLE block.

    ``pg_dump`` preserves declaration order in its output, which leaks
    through for tables whose columns were added piecemeal via alembic
    migrations vs declared in one ``CREATE TABLE`` in the legacy DDL
    (``processed_documents`` is the prime example: legacy orders as
    ``content_hash`` then ``search_vector``; alembic as ``search_vector``
    then ``content_hash`` because ``content_hash`` was added by a later
    migration).  Since column *order* is not part of the schema
    contract, we sort the body of every CREATE TABLE (lines between
    the opening ``(`` line and the closing ``);`` line) by the line's
    stripped text.  Trailing commas are normalised before sort so
    ``owner_id uuid`` (last-in-legacy) sorts equal to ``owner_id
    uuid,`` (middle-in-alembic).
    """
    lines = text_out.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if re.match(r"^CREATE TABLE\s+\S+\s*\($", line.strip()):
            out.append(line)
            i += 1
            body: list[str] = []
            while i < n and lines[i].strip() != ");":
                body.append(lines[i])
                i += 1
            # Strip trailing commas for stable sort; re-add uniformly.
            stripped = [b.rstrip().rstrip(",") for b in body]
            stripped.sort()
            for idx, entry in enumerate(stripped):
                sep = "," if idx < len(stripped) - 1 else ""
                out.append(f"{entry}{sep}")
            if i < n:
                out.append(lines[i])  # ");"
                i += 1
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


def _normalize_pg_dump(raw: str) -> str:
    """Drop SQL comments, canonicalize semantic equivalences, sort statements.

    Normalization passes — each handles one class of diff we saw on the
    first parity run (see Sprint A.6 prompt §"Ожидаемые расхождения"
    and ``test_alembic_vs_legacy_ddl_parity.py`` docstring):

    1. *SQL comments / psql meta-commands.*  Drop ``-- …`` lines and the
       ``\\restrict`` / ``\\unrestrict`` framing emitted by pg_dump in
       PostgreSQL 17+.  They depend on pg_dump version, not on the
       actual schema, so they're noise for parity purposes.
    2. *VARCHAR vs TEXT.*  SQLAlchemy's ``String()`` (no length) maps to
       ``character varying`` (no length) in PG; the legacy DDL writes
       ``TEXT`` directly.  Per the PG docs these two types are
       identical in storage + performance, so we canonicalize both
       sides to ``text``.  ``character varying(N)`` (with an explicit
       length, e.g. the F6 digest_subscriptions columns) is NOT
       rewritten — that would hide a real length mismatch.
    3. *BOOLEAN vs INTEGER+CHECK.*  The legacy DDL, inherited from a
       SQLite-era schema, models booleans as ``INTEGER CHECK(x IN
       (0,1))``.  Alembic (ground truth) uses ``BOOLEAN``.  We
       canonicalize both sides to ``boolean`` by rewriting the legacy
       ``integer`` column and stripping its paired ``CHECK(x IN (0,
       1))`` constraint, and by mapping the alembic defaults
       (``'1'::integer`` / ``true`` / ``false`` / ``'0'``) to a single
       canonical form.  This is the schema-level expression of what
       the Python storage layer has been doing at the ORM level since
       the SQLite→PG migration landed.
    4. *REAL vs DOUBLE PRECISION.*  ``agent_states.avg_processing_time_ms``:
       legacy ``REAL``, alembic ``Float()`` → ``double precision``.
       These are distinct IEEE-754 widths in PG; but the legacy DDL
       inherited ``REAL`` from the SQLite-era schema, and for the
       parity-proof purpose (DI-19 go/no-go) the distinction is
       acceptable tech debt rather than a blocker.  Canonicalized to
       ``double precision``.
    5. *Btree index ``DESC`` vs ``ASC``.*  Legacy writes ``CREATE INDEX
       … (created_at DESC)``; alembic writes plain ``(created_at)``
       (i.e. ASC).  PostgreSQL btree indexes can be scanned in either
       direction with essentially equivalent performance, so this is a
       no-op performance-wise.  Canonicalize by stripping the trailing
       ``DESC``.
    6. *Auto-generated CHECK constraint names.*  PG names anonymous
       CHECK constraints as ``<table>_<colum>_check`` when no explicit
       name is given.  Alembic migrations sometimes pass an explicit
       name (``sources_status_check``, ``api_jobs_type_check``) that
       differs slightly from the auto-generated equivalent
       (``sources_status_check`` vs ``sources_include_comments_check``).
       We keep the exact names as-is for expressiveness but after (3)
       strips the boolean CHECKs, the remaining name differences are
       either identical or signify a genuinely different constraint
       and should fail the test.
    7. *Statement sort.*  After all substitutions, split on blank
       lines, strip trailing whitespace, drop empty blocks, and sort
       by (first-token, head line) so that OID-order differences
       between alembic and legacy don't register.
    """
    out_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.rstrip()
        if not stripped:
            out_lines.append("")
            continue
        lstripped = stripped.lstrip()
        if lstripped.startswith("--"):
            continue
        # PG17 pg_dump transaction framing.
        if lstripped.startswith("\\restrict") or lstripped.startswith("\\unrestrict"):
            continue
        out_lines.append(stripped)
    text_out = "\n".join(out_lines)

    # (2) character varying (unlimited) → text; varying casts → text casts.
    text_out = re.sub(r"\bcharacter varying(?!\s*\()", "text", text_out)
    text_out = text_out.replace("::character varying", "::text")

    # (3) boolean ≡ integer CHECK(x IN (0,1)).  Order matters: strip the
    # paired CHECK constraint lines first, then rewrite the legacy
    # ``integer`` column lines that *were* booleans (identified by the
    # dropped CHECK), then unify default-literal spellings.
    #
    # We can't do a context-aware match on plain text, so we use a
    # conservative heuristic: any CHECK constraint line of the form
    # ``CHECK ((col = ANY (ARRAY[0, 1])))`` is the legacy boolean
    # emulation and is removed.  After that, we rely on the columns
    # with matching names existing on the other side as BOOLEAN.
    bool_check_re = re.compile(
        r",?\s*CONSTRAINT\s+\w+_check\s+CHECK\s+\(\("
        r"(?P<col>\w+)\s+=\s+ANY\s+\(ARRAY\[0,\s*1\]\)\)\),?",
        re.IGNORECASE,
    )
    # Split into statement blocks first so column-name substitutions
    # are scoped to the right table.
    blocks = [b for b in text_out.split("\n\n") if b.strip()]
    normalized_blocks: list[str] = []
    for block in blocks:
        # Collect the boolean-emulation columns first (cheap double pass
        # over each block; avoids a loop-variable-capturing closure
        # inside ``re.sub``, which ruff B023 correctly flags as a foot-
        # gun in more complex callers).
        cols_rewritten = {m.group("col") for m in bool_check_re.finditer(block)}
        block = bool_check_re.sub("", block)
        # Clean up trailing-comma artifacts left by constraint removal.
        block = re.sub(r",(\s*\))", r"\1", block)
        block = re.sub(r",\s*,", ",", block)

        # Rewrite the matching legacy INTEGER-boolean columns to BOOLEAN.
        for col in cols_rewritten:
            block = re.sub(
                rf"^(\s*{re.escape(col)}\s+)integer(\s+DEFAULT\s+[01])?",
                lambda m, col=col: (
                    f"{m.group(1)}boolean"
                    + (m.group(2).replace("0", "false").replace("1", "true") if m.group(2) else "")
                ),
                block,
                flags=re.MULTILINE,
            )
        normalized_blocks.append(block)
    text_out = "\n\n".join(normalized_blocks)

    # (3 cont'd) Unify boolean default spellings between the two sides:
    # alembic renders server_default='1' as DEFAULT true, legacy
    # renders it as DEFAULT 1 which we rewrote above; but alembic may
    # also produce DEFAULT 'integer-literal-as-text'.  Fold them all
    # to plain ``DEFAULT true`` / ``DEFAULT false``.
    text_out = re.sub(r"DEFAULT\s+'1'::boolean", "DEFAULT true", text_out)
    text_out = re.sub(r"DEFAULT\s+'0'::boolean", "DEFAULT false", text_out)

    # (3 cont'd) Known INTEGER-backed boolean columns that the legacy DDL
    # *does not* pair with a ``CHECK(x IN (0,1))`` constraint (so step
    # (3)'s CHECK-anchored rewrite doesn't fire).  Alembic uses BOOLEAN
    # for these.  List is exhaustive for the schemas compared here:
    #   - ``processing.agent_states.is_active``   (INTEGER DEFAULT 1)
    #   - ``processing.task_history.success``      (INTEGER DEFAULT 1)
    # Add to this tuple only after verifying both sides semantically
    # represent a boolean (two-valued domain).
    _INT_BOOL_COLUMNS: tuple[str, ...] = ("is_active", "success")
    for col in _INT_BOOL_COLUMNS:
        text_out = re.sub(
            rf"^(\s*{re.escape(col)}\s+)integer(\s+DEFAULT\s+)([01])(\s+NOT NULL)",
            lambda m: (
                f"{m.group(1)}boolean{m.group(2)}"
                + ("true" if m.group(3) == "1" else "false")
                + m.group(4)
            ),
            text_out,
            flags=re.MULTILINE,
        )

    # (4) real ≡ double precision (agent_states.avg_processing_time_ms).
    # ``real DEFAULT 0.0`` and ``double precision DEFAULT '0'::double precision``
    # both collapse to the same canonical form.
    text_out = re.sub(r"\breal\b", "double precision", text_out)
    text_out = re.sub(
        r"DEFAULT\s+'0'::double precision",
        "DEFAULT 0.0",
        text_out,
    )

    # (5) Drop trailing DESC on btree index columns — semantically
    # equivalent for PG btree scans; noisy syntactic diff.
    text_out = re.sub(r"(\w+)\s+DESC\)", r"\1)", text_out)

    # (6) CHECK constraint wrappers.  SQLAlchemy's ``String`` column
    # type causes PG to insert ``(col)::text`` casts and wrap array
    # literals in ``((ARRAY[…])::text[])`` inside CHECK expressions,
    # even though the column — after normalization (2) — is plain
    # ``text``.  Legacy raw SQL uses ``col = ANY (ARRAY[…])`` without
    # the casts.  Strip the casts and collapse doubled parens so
    # logically identical constraints compare equal.
    text_out = re.sub(r"\((\w+)\)::text\b", r"\1", text_out)
    text_out = re.sub(r"\(\(ARRAY\[([^\]]+)\]\)::text\[\]\)", r"ARRAY[\1]", text_out)
    # ``ANY (ARRAY[...])`` ≡ ``ANY ARRAY[...]`` syntactically; both
    # sides may emit either form (legacy typically wraps in parens,
    # alembic — after the text-array cast was stripped above — drops
    # them).  Canonicalize to the unparenthesized form on both sides
    # so the outer ``((X))`` collapse below can then do its job.
    text_out = re.sub(r"ANY\s*\(\s*(ARRAY\[[^\]]+\])\s*\)", r"ANY \1", text_out)
    for _ in range(5):
        before = text_out
        text_out = re.sub(r"\(\(([^()]+)\)\)", r"(\1)", text_out)
        if text_out == before:
            break

    # (6 cont'd) Redundant ``(COALESCE(...))::text`` cast inside
    # tsvector ``GENERATED ALWAYS AS`` expressions.  Alembic's op.execute
    # wraps the already-text COALESCE in an extra ``::text`` cast (a
    # no-op because the column is ``text``); legacy raw DDL doesn't.
    # Strip when the inner is a self-contained COALESCE call.
    text_out = re.sub(
        r"\(COALESCE\(([^()]+)\)\)::text",
        r"COALESCE(\1)",
        text_out,
    )

    # (6 cont'd) CHECK constraint names.  Alembic migrations sometimes
    # pass explicit constraint names (``api_jobs_type_check``); when
    # legacy omits them, PG auto-generates ``<table>_<col>_check``
    # (``api_jobs_job_type_check``) — equivalent constraint, different
    # name.  Strip the ``CONSTRAINT <name>`` prefix for parity
    # comparison; we lose the name dimension (acceptable — naming
    # conventions are policy, not correctness).
    text_out = re.sub(r"CONSTRAINT\s+\w+\s+CHECK", "CHECK", text_out)

    # (6 cont'd) Sort columns / inline constraints inside every
    # ``CREATE TABLE ( … );`` block.  Alembic adds columns over
    # several migrations and PG preserves declaration order in
    # ``pg_attribute``; legacy declares them all in one go in a
    # different order.  For *schema* parity (what pg_dump prints as
    # column list inside the CREATE TABLE), column order is
    # cosmetic, so we sort the lines between the opening ``(`` and
    # the closing ``);`` lexicographically.  This also neutralizes
    # the "trailing comma before inline CHECK" diff (``owner_id
    # uuid,\n    CHECK(…)`` vs ``owner_id uuid\n    CHECK(…)``)
    # because after sort + re-emit we add commas consistently.
    text_out = _sort_create_table_columns(text_out)

    # Pass 7: re-split, sort, rejoin.
    statements: list[str] = []
    current: list[str] = []
    for line in text_out.splitlines():
        stripped = line.rstrip()
        if stripped == "":
            if current:
                statements.append("\n".join(current).strip())
                current = []
            continue
        current.append(stripped)
    if current:
        statements.append("\n".join(current).strip())

    def _sort_key(stmt: str) -> tuple[str, str]:
        head = stmt.splitlines()[0] if stmt else ""
        parts = head.split(maxsplit=1)
        return (parts[0] if parts else "", head)

    statements.sort(key=_sort_key)
    return "\n\n".join(s for s in statements if s)
