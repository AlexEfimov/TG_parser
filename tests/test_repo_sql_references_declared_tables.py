"""Cross-check: every table referenced via raw SQL in repos is declared.

DI-9 phase 3 (Sprint A.3, 19.04.2026)
-------------------------------------

Phase 1 (``tests/test_migrations_self_contained.py``) catches "ALTER without
CREATE" within a single branch's migration chain. Phase 1 does NOT catch
"the repo issues ``text('INSERT INTO foo ...')`` against a table that no
migration ever creates" — that's the bug class which produced the
``topic_links`` outage during Dev Resurrection (Sprint A, Session 50,
see DI-8 audit). It was caught by manual audit, not by tests.

After DI-1 (Sprint A.2) every migrated table is also declared in
``tg_parser/storage/sqlalchemy/_metadata.py`` (and a sibling test —
``tests/test_metadata_matches_migrations.py`` — proves the equivalence).
That makes the reverse direction trivial: extract every identifier
following ``INSERT INTO`` / ``UPDATE`` / ``DELETE FROM`` / ``FROM`` /
``JOIN`` inside a ``text(...)`` call in
``tg_parser/storage/sqlalchemy/`` and check it is either:

- a table declared in any of ``METADATA_BY_DB[branch].tables`` (3 logical
  DBs), or
- a CTE name introduced by a ``WITH name AS (...)`` clause inside the
  same query string, or
- a Postgres system identifier (``pg_*``, ``information_schema.*``), or
- a small allow-list of SQL keywords sometimes following ``FROM`` /
  ``JOIN`` (``ONLY``, ``LATERAL``, ``unnest`` etc.).

When this test fails the most likely cause is one of:

1. **Missing migration** — repo was added to query a table that no
   migration creates. Add the migration (and the corresponding
   ``Table()`` in ``_metadata.py``).
2. **Renamed table** — repo still references the old name; update the
   SQL.
3. **Typo** in the SQL string (``processed_doucments`` etc.).
4. **CTE the regex didn't recognize** — extend ``_CTE_TAIL_RE``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tg_parser.storage.sqlalchemy._metadata import METADATA_BY_DB

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_DIR = _REPO_ROOT / "tg_parser" / "storage" / "sqlalchemy"

_DECLARED_TABLES: set[str] = set()
for _branch_meta in METADATA_BY_DB.values():
    _DECLARED_TABLES |= set(_branch_meta.tables.keys())

# Identifiers that may legally appear after FROM / JOIN / UPDATE but are
# not table names. Extend conservatively — every addition weakens the
# guardrail.
_SQL_WORD_ALLOWLIST = {
    "ONLY",  # SELECT ... FROM ONLY parent
    "LATERAL",  # SELECT ... FROM LATERAL (subquery)
    "UNNEST",  # SELECT ... FROM UNNEST(:arr)
    "VALUES",  # SELECT ... FROM (VALUES (...)) AS t(...)
    # SQL keywords that may follow UPDATE / INSERT INTO / FROM / JOIN
    # in non-table positions (e.g., "DO UPDATE SET col = ..." in
    # ON CONFLICT clauses). Added defensively — the word-boundary check
    # in _TABLE_RE should already prevent most of these.
    "SET",
    "WHERE",
    "ORDER",
    "GROUP",
    "LIMIT",
    "RETURNING",
    "AS",
    "ON",
    "IS",
}

_PG_SYSTEM_PREFIXES = ("pg_", "information_schema")


def _extract_text_strings(tree: ast.AST) -> list[str]:
    """Yield raw SQL strings passed to ``text(...)`` calls.

    Handles both ``text("...")`` (``Constant``) and ``text(f"...")``
    (``JoinedStr``).  For f-strings, ``FormattedValue`` parts (``{var}``)
    are replaced with a single space so we don't accidentally concatenate
    two SQL keywords across an interpolation point.
    """

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "text"):
            continue
        if not node.args:
            continue

        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
        elif isinstance(arg, ast.JoinedStr):
            parts: list[str] = []
            for v in arg.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append(" ")
            out.append("".join(parts))
    return out


# Identifier with optional schema qualifier and optional double-quoting.
# group(1) = schema (may be None), group(2) = bare name.
_IDENT = r'"?(?:([a-zA-Z_][a-zA-Z0-9_]*)\.)?([a-zA-Z_][a-zA-Z0-9_]*)"?'
_TABLE_RE = re.compile(
    # Word boundary (\b) is critical: without it ``time_from IS NULL`` matches
    # as ``FROM IS`` and flags ``IS`` as a fake table.
    rf"\b(?:INSERT\s+(?:IGNORE\s+)?INTO|UPDATE|DELETE\s+FROM|FROM|JOIN)\s+{_IDENT}",
    re.IGNORECASE,
)
_CTE_RE = re.compile(
    r"\bWITH\s+(?:RECURSIVE\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\b",
    re.IGNORECASE,
)
# Tail CTEs introduced by ", name AS (...)" inside a WITH chain.
_CTE_TAIL_RE = re.compile(r",\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(", re.IGNORECASE)


def _extract_cte_names(sql: str) -> set[str]:
    head = _CTE_RE.search(sql)
    if not head:
        return set()
    names = {head.group(1)}
    for m in _CTE_TAIL_RE.finditer(sql, head.end()):
        names.add(m.group(1))
    return names


def _is_system(schema: str | None, name: str) -> bool:
    haystacks = [name.lower()]
    if schema:
        haystacks.append(schema.lower())
    return any(h.startswith(p) for h in haystacks for p in _PG_SYSTEM_PREFIXES)


def _extract_referenced_tables(sql: str) -> set[str]:
    refs: set[str] = set()
    for m in _TABLE_RE.finditer(sql):
        schema, name = m.group(1), m.group(2)
        if not name:
            continue
        if _is_system(schema, name):
            continue
        if name in _SQL_WORD_ALLOWLIST or name.upper() in _SQL_WORD_ALLOWLIST:
            continue
        refs.add(name)
    return refs


def _all_text_strings_in_repo() -> dict[Path, list[str]]:
    out: dict[Path, list[str]] = {}
    for path in sorted(_REPO_DIR.rglob("*.py")):
        # Skip private modules (`_metadata.py`, `__init__.py`) — they hold
        # SQLAlchemy declarations / re-exports, not raw repo SQL.
        if path.name.startswith("_"):
            continue
        # Skip legacy DDL helpers (planned removal in DI-19); they hold
        # CREATE TABLE strings, not the INSERT/UPDATE/DELETE/FROM/JOIN
        # patterns this guardrail targets.
        if path.parent.name == "schemas":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            pytest.fail(f"Could not parse {path}: {exc}")
        strings = _extract_text_strings(tree)
        if strings:
            out[path] = strings
    return out


def test_repo_sql_only_references_declared_tables() -> None:
    findings: list[str] = []
    for path, strings in _all_text_strings_in_repo().items():
        for sql in strings:
            ctes = _extract_cte_names(sql)
            referenced = _extract_referenced_tables(sql)
            unknown = sorted(t for t in referenced if t not in _DECLARED_TABLES and t not in ctes)
            if unknown:
                snippet = " ".join(sql.split())[:80]
                findings.append(
                    f"  {path.relative_to(_REPO_ROOT)}: unknown table(s) "
                    f"{unknown} in SQL «{snippet}…»"
                )

    assert not findings, (
        "Repo SQL references tables not declared in METADATA_BY_DB.\n"
        "Most likely cause is one of:\n"
        "  - the table was renamed/typo'd in the repo SQL,\n"
        "  - a migration is missing for it (add migration AND _metadata.py decl),\n"
        "  - it's a CTE the regex didn't recognize (extend _CTE_TAIL_RE),\n"
        "  - it's a SQL keyword the regex shouldn't treat as a table name\n"
        "    (extend _SQL_WORD_ALLOWLIST sparingly).\n\n" + "\n".join(findings)
    )


def test_extract_referenced_tables_handles_cte() -> None:
    """Self-test of the CTE filter to lock the contract."""

    sql = """
        WITH q AS (SELECT plainto_tsquery('simple', :query) AS tsq)
        SELECT pd.source_ref, ts_rank_cd(search_vector, q.tsq) AS score
        FROM q
        JOIN processed_documents pd ON true
        WHERE search_vector @@ q.tsq
    """
    ctes = _extract_cte_names(sql)
    refs = _extract_referenced_tables(sql)
    assert ctes == {"q"}
    assert "q" in refs and "processed_documents" in refs
    assert refs - _DECLARED_TABLES - ctes == set(), (
        "After subtracting CTEs and declared tables there should be nothing left"
    )


def test_extract_referenced_tables_handles_join_and_subquery() -> None:
    sql = """
        SELECT pd.source_ref
        FROM processed_documents pd
        LEFT JOIN document_embeddings de ON pd.source_ref = de.source_ref
        WHERE de.source_ref IN (SELECT source_ref FROM topic_cards)
    """
    refs = _extract_referenced_tables(sql)
    assert refs == {"processed_documents", "document_embeddings", "topic_cards"}
    assert refs.issubset(_DECLARED_TABLES)


def test_extract_referenced_tables_skips_system_catalogs() -> None:
    sql = "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
    assert _extract_referenced_tables(sql) == set()


def test_extract_referenced_tables_does_not_match_inside_identifier() -> None:
    """Word boundary: ``time_from IS NULL`` must NOT match as ``FROM IS``."""

    sql = "SELECT topic_id FROM topic_bundles WHERE time_from IS NULL"
    refs = _extract_referenced_tables(sql)
    assert refs == {"topic_bundles"}, refs


def test_extract_referenced_tables_flags_unknown_table() -> None:
    """Negative regression: a typo / forgotten migration is flagged."""

    sql = "SELECT * FROM totally_fake_table_xyz WHERE id = :id"
    refs = _extract_referenced_tables(sql)
    assert refs == {"totally_fake_table_xyz"}
    assert refs - _DECLARED_TABLES == {"totally_fake_table_xyz"}


def test_on_conflict_do_update_set_does_not_flag_set_as_table() -> None:
    """``DO UPDATE SET col = excluded.col`` must not extract ``SET`` as table."""

    sql = (
        "INSERT INTO topic_links (topic_id_a, topic_id_b) VALUES (:a, :b) "
        "ON CONFLICT (topic_id_a, topic_id_b) DO UPDATE SET topic_id_a = excluded.topic_id_a"
    )
    refs = _extract_referenced_tables(sql)
    assert "SET" not in refs and "set" not in refs
    assert refs == {"topic_links"}
