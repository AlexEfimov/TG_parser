"""Parity proof: alembic-built schema ≈ legacy ``init_*_schema()`` schema.

Sprint A.6 / DI-9 phase 2 / DI-19 prep (19.04.2026).

This test is the safety gate for Sprint A.7 / DI-19 (drop
``EMBEDDING_DDL`` / ``PROCESSING_STORAGE_DDL`` / ``init_*_schema`` /
``init_databases_fallback``).  If the alembic-built schema matches the
legacy DDL-built one (modulo documented exceptions), deleting the
legacy helpers becomes a mechanical refactor with zero schema risk.

Design
------
For each branch (``ingestion`` / ``raw`` / ``processing``):

1. Create two fresh DBs inside the session pgvector container:
   ``alembic_<branch>`` (built by ``alembic upgrade head``) and
   ``legacy_<branch>`` (built by the corresponding ``init_*_schema``
   coroutine).
2. Capture a normalized ``pg_dump --schema-only`` of each.
3. Compare the two dumps after filtering per-branch expected
   divergences (the ``alembic_version_*`` bookkeeping table; documented
   acceptable cosmetic diffs).

Whitelist policy
----------------
- ``alembic_version_<branch>``: legitimate, alembic-only.
- Anything else that fails on first run belongs to one of three
  buckets (see Sprint A.6 prompt §"Ожидаемые расхождения"):
    (a) *Cosmetic*: semantically equivalent but textually different
        (``now()`` vs ``CURRENT_TIMESTAMP``, single- vs double-quoted
        defaults, different constraint naming).  Extend
        :func:`_testcontainer_fixtures._normalize_pg_dump`.
    (b) *Acceptable structural alembic-only*: e.g. explicit
        ``PRIMARY KEY`` constraint names that legacy left implicit.
        Add a one-line whitelist entry here with a comment.
    (c) *Real divergence*: the legacy DDL never caught up with a
        migration (DI-8 class of bug), or alembic and legacy differ on
        types (``BOOLEAN`` vs ``INTEGER CHECK IN (0,1)``).  **This is
        the bug the test exists to surface.**  Fix by either landing a
        migration that aligns reality with the metadata, or explicitly
        whitelist here with a ``TODO(DI-#)`` reference.

Opt-in via ``TEST_TESTCONTAINERS=1``.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from _testcontainer_fixtures import (
    alembic_upgrade_for_branch,
    create_database,
    dump_schema,
    make_async_engine,
    requires_testcontainers,
)

# ``pgvector_container`` fixture lives in ``_testcontainer_fixtures``;
# load it as a plugin so tests here can accept it as a parameter.
pytest_plugins = ("_testcontainer_fixtures",)

BRANCHES = ("ingestion", "raw", "processing")

LEGACY_INIT: dict[str, tuple[str, str]] = {
    "ingestion": (
        "tg_parser.storage.sqlalchemy.schemas.ingestion_state",
        "init_ingestion_state_schema",
    ),
    "raw": (
        "tg_parser.storage.sqlalchemy.schemas.raw_storage",
        "init_raw_storage_schema",
    ),
    "processing": (
        "tg_parser.storage.sqlalchemy.schemas.processing_storage",
        "init_processing_storage_schema",
    ),
}

# Per-branch substrings that, if present in a statement (post-normalization),
# cause it to be dropped from the alembic dump before comparison.  Extend
# with care — each entry must be either (a) legitimately alembic-only
# bookkeeping, or (b) accompanied by a DI-# reference documenting why we
# accept the divergence.
_ALEMBIC_ONLY_FILTERS: dict[str, tuple[str, ...]] = {
    "ingestion": ("alembic_version_ingestion",),
    "raw": ("alembic_version_raw",),
    "processing": (
        "alembic_version_processing",
        # topic_bundles non-unique helper indexes: alembic (DI-1 metadata)
        # declares them; the legacy ``PROCESSING_STORAGE_DDL`` only
        # ever created the *partial unique* indexes
        # (``topic_bundles_current_unique_idx`` /
        # ``topic_bundles_snapshot_unique_idx``).  These plain btree
        # indexes are a superset produced by alembic — acceptable
        # alembic-only, confirms A.7 / DI-19 can drop legacy DDL
        # without losing any index it ever created.
        "topic_bundles_topic_idx",
        "topic_bundles_snapshot_idx",  # distinct from topic_bundles_snapshot_UNIQUE_idx
    ),
}


def _resolve_legacy(branch: str):
    module_name, attr = LEGACY_INIT[branch]
    module = importlib.import_module(module_name)
    return getattr(module, attr)


async def _run_legacy_init(container, branch: str) -> str:
    """Create ``legacy_<branch>`` DB and run the legacy init coroutine.

    Single-loop wrapper: ``asyncpg`` engines are bound to the loop they
    were created on, so we build + use + dispose the engine inside one
    ``asyncio.run`` invocation.
    """
    legacy_db = f"legacy_{branch}"
    create_database(container, legacy_db)  # sync call is fine inside async fn
    init_fn = _resolve_legacy(branch)
    engine = make_async_engine(container, legacy_db)
    try:
        await init_fn(engine)
    finally:
        await engine.dispose()
    return legacy_db


def _drop_statements_containing(dump: str, needles: tuple[str, ...]) -> str:
    """Return ``dump`` with any top-level statement mentioning ``needles`` removed."""
    if not needles:
        return dump
    statements = dump.split("\n\n")
    kept = [s for s in statements if not any(n in s for n in needles)]
    return "\n\n".join(kept)


@requires_testcontainers
@pytest.mark.parametrize("branch", BRANCHES)
def test_alembic_schema_matches_legacy_ddl(pgvector_container, branch):
    """Schema built by alembic == schema built by legacy ``init_*_schema()``.

    First failure run is expected (and useful): it enumerates every
    point where alembic and the legacy DDL helper have drifted.  Each
    divergence is then triaged under the whitelist policy in this
    module's docstring.  Ground truth for production is alembic — the
    legacy helper is on its way out under Sprint A.7 / DI-19.
    """
    alembic_db = alembic_upgrade_for_branch(pgvector_container, branch)
    legacy_db = asyncio.run(_run_legacy_init(pgvector_container, branch))

    alembic_dump = dump_schema(pgvector_container, alembic_db)
    legacy_dump = dump_schema(pgvector_container, legacy_db)

    alembic_filtered = _drop_statements_containing(
        alembic_dump, _ALEMBIC_ONLY_FILTERS.get(branch, ())
    )

    if alembic_filtered == legacy_dump:
        return

    alembic_stmts = set(alembic_filtered.split("\n\n"))
    legacy_stmts = set(legacy_dump.split("\n\n"))
    only_alembic = sorted(alembic_stmts - legacy_stmts)
    only_legacy = sorted(legacy_stmts - alembic_stmts)

    sep = "\n" + ("-" * 72) + "\n"
    msg_parts = [
        f"branch {branch!r}: alembic vs legacy DDL diverge "
        f"(alembic-only: {len(only_alembic)} stmts, legacy-only: {len(only_legacy)} stmts).",
        "",
        "=== Only in alembic (filtered) ===",
        sep.join(only_alembic) if only_alembic else "(none)",
        "",
        "=== Only in legacy ===",
        sep.join(only_legacy) if only_legacy else "(none)",
    ]
    pytest.fail("\n".join(msg_parts), pytrace=False)
