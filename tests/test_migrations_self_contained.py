"""Static guardrail: alembic migrations must be self-contained per branch.

DI-9 phase 1 (Sprint A, Session 50, 19.04.2026)
-----------------------------------------------

Catches the class of bug uncovered by DI-8 — an ALTER / ADD COLUMN /
CREATE INDEX targeting a table that no migration upstream in the same
branch ever creates.  Historically these were silently masked by the
legacy DDL fallback (``init_*_schema``) firing whenever the alembic CLI
itself failed; once the multi-head bug was fixed (DI-14, ``7adc07c``)
they became active failures on any clean DB.  See the DI-8 audit
matrix in ``docs/notes/FUTURE_FEATURES.md`` for the two latent cases
this guardrail would have caught (``topic_links`` table; ``topic_bundles``
partial unique indexes).

This is purely **static analysis** (AST + light regex over raw SQL
strings inside ``sa.text(...)`` / ``op.execute(text(...))``).  No
PostgreSQL is required and no alembic subprocess is spawned, so it is
cheap to run on every commit.

The runtime equivalent — ``alembic upgrade head`` against a clean test
PostgreSQL for each branch with a follow-up ``\\dt`` assertion — is
deferred to **DI-9 phase 2** (test fixture work, will share scaffolding
with the eventual DI-19 alembic-based test fixtures).

What this catches
~~~~~~~~~~~~~~~~~

For each branch (``ingestion`` / ``raw`` / ``processing``):

1. **Orphan ALTER**: any ``op.add_column / alter_column / create_index``
   or any raw-SQL ``ALTER TABLE foo`` / ``CREATE INDEX ... ON foo``
   whose target table ``foo`` has no upstream ``CREATE TABLE foo`` in
   the same revision chain (or in the *same* migration's defensive
   bootstrap).

2. **Duplicate revision id**: two migration files declaring the same
   ``revision = "abc..."``.  Alembic refuses to resolve heads when this
   happens; we already had this bug once (``e5f6a7b8c9d0`` linearised
   in ``189db2a``) — keep a guardrail.

3. **Multiple heads per branch**: a branch where more than one revision
   has no child pointing at it as ``down_revision``.  CI guardrail
   (``alembic-guardrails`` job) already checks this, but a unit-level
   duplicate here makes the failure deterministic and offline-debuggable.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "migrations" / "versions"
BRANCHES = ("ingestion", "raw", "processing")

_RE_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_RE_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:public\.)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_RE_CREATE_INDEX_ON = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?[A-Za-z_][A-Za-z0-9_]*\s+ON\s+"
    r"(?:public\.)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _migration_files(branch: str) -> list[Path]:
    return sorted(
        p
        for p in (MIGRATIONS_ROOT / branch).glob("*.py")
        if p.name != "__init__.py"
    )


def _string_arg(node: ast.AST) -> str | None:
    """Best-effort: return the literal string content of an AST node.

    Handles plain ``"foo"``, ``sa.text("foo")`` / ``text("foo")`` and the
    static parts of an f-string.  Returns ``None`` for anything else.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call):
        if node.args:
            inner = _string_arg(node.args[0])
            if inner is not None:
                return inner
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts) if parts else None
    return None


def _scan_sql_strings(tree: ast.AST) -> list[str]:
    """Collect every literal string passed as the first arg to a Call."""
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for arg in node.args:
                sql = _string_arg(arg)
                if sql is not None:
                    out.append(sql)
    return out


def _extract_targets(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return (created_tables, altered_tables) for one migration AST."""
    creates: set[str] = set()
    alters: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        op_name: str | None = None
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "op"
        ):
            op_name = func.attr

        if op_name == "create_table":
            if node.args:
                name = _string_arg(node.args[0])
                if name:
                    creates.add(name)
        elif op_name in {"add_column", "alter_column", "drop_column", "drop_constraint"}:
            if node.args:
                name = _string_arg(node.args[0])
                if name:
                    alters.add(name)
        elif op_name == "create_index":
            if len(node.args) >= 2:
                name = _string_arg(node.args[1])
                if name:
                    alters.add(name)

    for sql in _scan_sql_strings(tree):
        for match in _RE_CREATE_TABLE.findall(sql):
            creates.add(match)
        for match in _RE_ALTER_TABLE.findall(sql):
            alters.add(match)
        for match in _RE_CREATE_INDEX_ON.findall(sql):
            alters.add(match)

    return creates, alters


def _parse_revisions(branch: str) -> list[dict]:
    revs: list[dict] = []
    for path in _migration_files(branch):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rev: str | None = None
        down: str | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is None:
                    continue
                target = node.target.id
                if target == "revision":
                    try:
                        rev = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        rev = None
                elif target == "down_revision":
                    try:
                        down = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        down = None
        if rev is None:
            continue
        creates, alters = _extract_targets(tree)
        revs.append(
            {
                "path": path,
                "rev": rev,
                "down": down,
                "creates": creates,
                "alters": alters,
            }
        )
    return revs


def _topological_chain(revs: list[dict]) -> list[dict]:
    """Order migrations from base (``down_revision=None``) to head.

    Tolerates branches with multiple roots (none of ours have any, but
    this keeps the analyzer honest if someone introduces one).
    """
    by_rev = {r["rev"]: r for r in revs}
    out: list[dict] = []
    visited: set[str] = set()

    def visit(node: dict) -> None:
        if node["rev"] in visited:
            return
        if node["down"] and node["down"] in by_rev:
            visit(by_rev[node["down"]])
        visited.add(node["rev"])
        out.append(node)

    for r in revs:
        visit(r)
    return out


@pytest.mark.parametrize("branch", BRANCHES)
def test_migrations_self_contained(branch: str) -> None:
    """Every ALTER target must have a CREATE TABLE upstream in the same chain.

    Catches the DI-8 bug class: ``op.add_column('document_embeddings', ...)``
    when no migration ever did ``op.create_table('document_embeddings', ...)``,
    or ``CREATE INDEX ... ON topic_links(...)`` when ``topic_links`` is never
    created by alembic.
    """
    revs = _parse_revisions(branch)
    assert revs, f"No migrations found for branch {branch!r} under {MIGRATIONS_ROOT}"

    chain = _topological_chain(revs)

    seen: set[str] = set()
    orphans: list[tuple[str, str, str]] = []
    for r in chain:
        seen |= r["creates"]
        missing = sorted(r["alters"] - seen)
        for tbl in missing:
            orphans.append((r["rev"], r["path"].name, tbl))

    assert not orphans, (
        f"Branch {branch!r}: migrations target tables that have no upstream "
        f"CREATE TABLE in the same chain (DI-9 phase 1):\n  "
        + "\n  ".join(
            f"{rev} ({fname}): missing CREATE for table {tbl!r}"
            for rev, fname, tbl in orphans
        )
        + "\nFix: add a defensive bootstrap (CREATE TABLE IF NOT EXISTS) "
        "inside the offending migration, or a new migration that creates "
        "the table before the ALTER.  See migration b8e2f7c1d9a3 for the "
        "canonical pattern."
    )


def test_no_duplicate_revision_ids() -> None:
    """No two migration files (across all branches) share a revision id.

    Alembic refuses to resolve heads when this happens
    (``UserWarning: Revision ... is present more than once``), as we
    discovered with ``e5f6a7b8c9d0`` linearised in ``189db2a``.
    """
    seen: dict[str, Path] = {}
    duplicates: list[tuple[str, Path, Path]] = []
    for branch in BRANCHES:
        for r in _parse_revisions(branch):
            if r["rev"] in seen:
                duplicates.append((r["rev"], seen[r["rev"]], r["path"]))
            else:
                seen[r["rev"]] = r["path"]
    assert not duplicates, "Duplicate alembic revision id(s):\n  " + "\n  ".join(
        f"{rev}: {a} vs {b}" for rev, a, b in duplicates
    )


@pytest.mark.parametrize("branch", BRANCHES)
def test_branch_has_single_head(branch: str) -> None:
    """Each branch terminates in exactly one revision.

    The ``alembic-guardrails`` CI job already enforces this at runtime;
    the offline duplicate here makes the failure deterministic and
    bisectable without spinning up alembic.
    """
    revs = _parse_revisions(branch)
    pointed_at = {r["down"] for r in revs if r["down"]}
    heads = sorted(r["rev"] for r in revs if r["rev"] not in pointed_at)
    assert len(heads) == 1, (
        f"Branch {branch!r} expected exactly 1 head, found {len(heads)}: {heads}.\n"
        f"Likely cause: a branched chain (two migrations sharing the same "
        f"down_revision) or a duplicate revision id (run the duplicate-id test)."
    )
