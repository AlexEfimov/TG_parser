# Sprint A.6 — DI-9 phase 2 (testcontainers smoke + alembic↔legacy DDL parity)

**Дата подготовки:** 19 апреля 2026 (по итогам Sprint A.5 / DI-7, Session 53).
**Тип сессии:** Test infra + verification (~1–1.5 сессии).
**HEAD:** `067e3c1` на `origin/main` (Sprint A.5 закрыт; CI зелёный — Test Python 3.12, Alembic Guardrails, Lint Documentation, Docker Build).
**Связанные задачи в [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md):** DI-9 phase 2 (~line 2454), DI-19 (~line 2838).
**Roadmap:** A.5 ✅ (DI-7) → **A.6 (DI-9 phase 2, эта)** → A.7 (DI-19 — drop legacy `EMBEDDING_DDL` / `init_*_schema()`). После A.7 migration tech-debt = 0.
**Прецеденты (читать перед стартом):** [`START_PROMPT_SPRINT_A5_DI7.md`](START_PROMPT_SPRINT_A5_DI7.md) (структура prompt'а, lessons про CI и ruff), `tests/test_alembic_ini_consistency.py` (template статического guardrail в стиле «одна параметризованная проверка на ветку»), `tests/test_migrations_self_contained.py` (DI-9 phase 1 — runtime-аналог которого мы сейчас пишем).

---

## Цель сессии

Заложить **общую testcontainers-based test-инфраструктуру** для миграционных smoke-тестов и закрыть DI-9 phase 2 двумя проверками:

1. **Runtime self-contained smoke** (буква DI-9 phase 2): для каждой логической ветки (`ingestion` / `raw` / `processing`) поднять чистый pgvector-контейнер, прогнать `tg-parser db upgrade --db <branch>` и проассертить, что `pg_tables` содержит ожидаемый набор таблиц + критичные индексы (uniques, partial). Это runtime mirror статического `tests/test_migrations_self_contained.py` — ловит drift, который AST не видит (вычисляемые имена, `IF NOT EXISTS` без CREATE upstream, runtime-only DDL в `op.execute(text(...))`).

2. **Parity proof для DI-19**: на том же контейнере параллельно поднять отдельную БД через legacy `init_*_schema()` и сравнить `pg_dump --schema-only` обеих. Должны быть идентичны (с whitelist'ом acceptable cosmetic diff'ов). Это даёт **доказательную базу для A.7 / DI-19** — без него удалять `init_*_schema()` стрёмно: нет уверенности, что alembic покрывает 100% legacy DDL.

Обе проверки используют одну и ту же session-scoped pgvector-фикстуру → инфра-расходы амортизируются.

### Не входит в сессию

- **DI-19** (A.7) — переписывание ~11 test-файлов на новую alembic-fixture, удаление `EMBEDDING_DDL` / `init_*_schema()` / `init_databases_fallback`. Это отдельная сессия, опирающаяся на parity proof из A.6.
- **DI-5** (operational backfill 4 каналов) — независимый ops-таск, отдельное окно.
- Перевод существующих ~11 тестов на новую фикстуру (любой `init_*_schema(engine)` в test-файле) — оставляем как есть до A.7 (см. список ниже).

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на 067e3c1
gh run list --branch main --limit 3              # CI на 067e3c1 зелёный?

# Local стек (не обязателен для A.6 — testcontainers поднимает свой PG)
docker compose ps                                # tg_parser_postgres — healthy (для smoke сравнения)

# Docker daemon доступен — testcontainers без него работать не будет
docker version

# Прочитать DI-9 phase 2 + DI-19 entry в FUTURE_FEATURES.md
grep -nE "^### DI-(9|19):" docs/notes/FUTURE_FEATURES.md
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` (sustained lesson из Sprint A — иначе CI красный на line-length / import order).

**Sandbox note:** `pg_dump` в локальном `PATH` отсутствует (проверено `which pg_dump` 19.04.2026 → not found). Solution: вызывать `pg_dump` через `container.exec(...)` API testcontainers — внутри образа `pgvector/pgvector:pg17` бинарь `pg_dump` есть (это postgres-server image, включает client-tools). Ровно тот же подход работает в CI runner — нужен только Docker daemon, который у GitHub Actions ubuntu-latest есть из коробки.

---

## Контекст: что мы знаем после аудита 19 апреля 2026

Перед написанием prompt'а проведён мини-аудит. Все цифры/пути проверены в коде HEAD `067e3c1`, не из памяти.

### Что уже работает (foundation, не трогать)

| Слой | Статус |
|---|---|
| Per-DB alembic ini (`migrations/alembic_<db>.ini`) | DI-7 ✅ — `alembic.config.Config("migrations/alembic_<db>.ini")` напрямую читается из Python. |
| `tg_parser.storage.sqlalchemy._metadata.METADATA_BY_DB` | DI-1 ✅ — три независимые `MetaData()` (`INGESTION_METADATA` / `RAW_METADATA` / `PROCESSING_METADATA`), все 19 таблиц объявлены. |
| Static migration guardrails | DI-9 phase 1 (`test_migrations_self_contained.py`, 5 тестов) + DI-9 phase 3 (`test_repo_sql_references_declared_tables.py`, 7 тестов) |
| CI alembic-guardrail job | `tg-parser db {heads,upgrade,downgrade base,check}` × 3 ветки на чистой test-DB. Это уже runtime smoke, но через postgres-service GitHub Actions, не testcontainers. A.6 даёт **локально-воспроизводимый аналог + parity diff**. |

### Что меняем / добавляем

| Файл | Действие |
|---|---|
| `requirements.txt`, `pyproject.toml::optional-dependencies.dev` | Добавить `testcontainers[postgres]>=4.8` (Python 3.12 совместимость подтверждена в upstream). Если extra `[postgres]` не резолвится в текущей версии — fallback на bare `testcontainers>=4.8` (psycopg2-binary уже есть в основном requirements.txt:23). |
| `tests/_testcontainer_fixtures.py` (новый) | Session-scoped pytest fixture `pgvector_container` — поднимает один `pgvector/pgvector:pg17` контейнер на всю сессию, returns `PostgresContainer` instance. Public helpers: `sync_url_for_db(c, db)` / `async_url_for_db(c, db)` — URL builders (без приватного underscore — это публичный API для будущих тестов из A.7). `create_database(c, db)` — создаёт чистую БД + `CREATE EXTENSION vector`. `make_async_engine(c, db)` — async SQLAlchemy engine. `alembic_upgrade_for_branch(c, branch) -> db_name` — единая точка для `alembic upgrade head` (используется в обоих новых test-файлах, чтобы избежать tests-importing-tests). `dump_schema(c, db)` + `_normalize_pg_dump(raw)` — pg_dump + нормализация. `requires_testcontainers` — pytest skip marker. |
| `tests/conftest.py` | НЕ трогать. Новые fixtures импортируются адресно теми тестами, которые их используют (избегаем session-scope side-effects на 100+ существующих тестов). |
| `tests/test_migrations_runtime_upgrade.py` (новый) | DI-9 phase 2 sub-goal 1: `alembic upgrade head` per branch на свежей БД + assert table inventory (`pg_tables`) + assert critical indexes (uniques + partial). |
| `tests/test_alembic_vs_legacy_ddl_parity.py` (новый) | DI-9 phase 2 sub-goal 2 / DI-19 prep: per branch — две БД в одном контейнере, alembic-built vs `init_*_schema()`-built, `pg_dump --schema-only` diff с whitelist'ом cosmetic differences. |
| `.github/workflows/ci.yml` | Новый job `alembic-parity` (или extend существующий `alembic-guardrail`): прогоняет два новых файла. Контейнер DinD: GitHub runners уже умеют, ничего экзотического. |
| `docs/runbooks/SAFE_MIGRATION_ON_DEV.md` | Добавить раздел «Parity check before merging schema PR» — как локально прогнать parity diff. |
| `docs/notes/FUTURE_FEATURES.md` | DI-9 phase 2 → FIXED с описанием. DI-19 entry освежить: «снят последний блокер — parity proof в `tests/test_alembic_vs_legacy_ddl_parity.py`». |

### Test files, которые остаются на legacy DDL до A.7 / DI-19

Эти файлы **намеренно НЕ трогаем** в A.6 (audit-only список для A.7):

```
tests/test_e2e_pipeline.py
tests/test_storage_integration.py
tests/test_embedding.py
tests/test_retrieval_hybrid_session.py
tests/test_f5a_topic_rag.py          # содержит assert на содержимое EMBEDDING_DDL string!
tests/test_f5a_hybrid_search.py
tests/test_f5a_phase3_dedup.py
tests/test_agents_observability.py
tests/test_multi_agent.py
tests/test_migrations.py             # сам тестирует init_*_schema() — заменится на runtime smoke в A.6 fixture
tests/test_f6_scheduled_digests.py
tests/test_f2_parse_only_export.py
tests/test_migrate_users_cmd.py
tests/test_cli_db_cleanup_orphan_admin.py
```

Полный grep: `grep -rln "init_processing_storage_schema\|init_ingestion_state_schema\|init_raw_storage_schema\|EMBEDDING_DDL" tests/` — 14 файлов (включая cache misses; реально импортирующих ~11). Используется как audit baseline для A.7.

### Hidden gotchas

1. **`asyncio` event loop в session fixture.** `pytest-asyncio` создаёт loop per-test (function scope). Если делать container session-scoped, async-engine'ы внутри тестов должны создаваться **per test** (не reuse'ить engine из fixture). Helper `make_engine(container, db_name)` возвращает свежий engine на каждый тест → правильно. Не возвращать engine из самой session-fixture.
2. **`alembic upgrade head` из Python** — используем `alembic.config.Config` + `alembic.command.upgrade`, **не** subprocess. Subprocess наследует cwd и env, что в pytest сложно контролировать. **Чистая версия (без cmd_opts hack'а):** `migrations/env.py::get_db_name()` уже умеет читать `db_name` через `config.get_main_option("db_name")` как fallback после `context.get_x_argument()` — проверено на HEAD `067e3c1`, lines 53–70. Поэтому достаточно:
   ```python
   from alembic.config import Config
   from alembic import command
   cfg = Config(str(REPO_ROOT / "migrations" / f"alembic_{branch}.ini"))
   cfg.set_main_option("sqlalchemy.url", sync_url_for_db(container, db))
   cfg.set_main_option("db_name", branch)  # env.py::get_db_name() reads this
   command.upgrade(cfg, "head")
   ```
   Если внезапно не подхватится — упадёт быстро в Шаге 6 smoke; `cmd_opts` hack как plan B.
3. **`pg_dump` и `--no-owner` / `--no-privileges`.** Без этих флагов dump содержит `OWNER TO postgres` строки, которые могут различаться (alembic vs DDL запускаются под одним пользователем — должны совпадать, но защита не вредит). Также `--no-comments` чтобы убрать `-- Dumped from database version 17.x` шапку.
4. **`pg_dump` ordering.** Постгрес может выдавать DDL в порядке OID создания, который у двух разных способов будет разный. Решение: после dump'а сортируем `CREATE TABLE` блоки по имени таблицы, `CREATE INDEX` — по имени индекса. Альтернатива: parser-based normalization через `sqlparse` (но это новая зависимость; начнём с грубой sort + сравнение по «statement set», не по точной строке).
5. **`pgvector` extension.** Migration `a1b2c3d4e5f6` делает `CREATE EXTENSION IF NOT EXISTS vector`. Legacy `init_processing_storage_schema` тоже. Контейнер `pgvector/pgvector:pg17` имеет extension доступным, но не активированным — оба flow его enable'ят, parity сохранится. Sanity: после fixture setup `SELECT * FROM pg_extension WHERE extname='vector'` должен дать row.
6. **«Не делать раньше DI-19 — придётся переписывать фикстуру дважды»** — оригинальный комментарий в DI-9 entry (line 2462). После A.5 порядок reorg'нут: A.6 (фикстура + parity) → A.7 (использует фикстуру для переписывания тестов + удаления legacy). «Дважды» не происходит, если мы сразу проектируем `pgvector_container` + `make_engine(container, db_name)` как stable public API для будущих тестов. Этот prompt и проектирует.
7. **CI runner и Docker-in-Docker.** GitHub `ubuntu-latest` runner имеет Docker socket доступным (это уже используется в `docker` job). Testcontainers-python работает через тот же socket. Дополнительный setup не нужен. Время старта pgvector-контейнера на runner — ~5–10 секунд (один раз на сессию).

---

## План шагов

### Шаг 1: Добавить testcontainers в dev deps

```bash
# requirements.txt — после "ruff==0.15.11" (в секции "# Testing")
testcontainers[postgres]>=4.8

# pyproject.toml — в [project.optional-dependencies] dev
"testcontainers[postgres]>=4.8",

# Локально
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "from testcontainers.postgres import PostgresContainer; print('ok')"
```

Если `[postgres]` extra не находится в текущем релизе testcontainers-python — fallback: убрать extra (`testcontainers>=4.8`); psycopg2 уже в основном `requirements.txt:23`.

### Шаг 2: Создать `tests/_testcontainer_fixtures.py`

Session-scoped pgvector container + helpers. Скелет:

```python
"""Testcontainers-based PostgreSQL fixture for migration smoke tests.

Used by:
- tests/test_migrations_runtime_upgrade.py (DI-9 phase 2)
- tests/test_alembic_vs_legacy_ddl_parity.py (DI-9 phase 2 / DI-19 prep)
- (future) test fixtures replacing init_*_schema() under DI-19 / Sprint A.7
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parent.parent
PGVECTOR_IMAGE = "pgvector/pgvector:pg17"

# Tests are slow (~10s startup + per-test work). Opt-in via env var.
_TESTCONTAINERS_ENABLED = bool(int(os.environ.get("TEST_TESTCONTAINERS", "0")))
requires_testcontainers = pytest.mark.skipif(
    not _TESTCONTAINERS_ENABLED,
    reason="set TEST_TESTCONTAINERS=1 to enable testcontainers-based tests",
)


@pytest.fixture(scope="session")
def pgvector_container() -> Generator[PostgresContainer, None, None]:
    """Spin one pgvector PG17 container for the whole session."""
    container = PostgresContainer(PGVECTOR_IMAGE)
    container.start()
    try:
        # Smoke: pgvector extension can be created (per-DB is done in create_database)
        eng = create_engine(sync_url_for_db(container, container.dbname),
                            isolation_level="AUTOCOMMIT")
        with eng.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        eng.dispose()
        yield container
    finally:
        container.stop()


def sync_url_for_db(container: PostgresContainer, db_name: str) -> str:
    """Build a sync postgresql:// URL for a specific DB inside the container."""
    return (
        f"postgresql://{container.username}:{container.password}@"
        f"{container.get_container_host_ip()}:{container.get_exposed_port(5432)}/{db_name}"
    )


def async_url_for_db(container: PostgresContainer, db_name: str) -> str:
    return sync_url_for_db(container, db_name).replace("postgresql://", "postgresql+asyncpg://")


def create_database(container: PostgresContainer, db_name: str) -> None:
    """Create a fresh DB inside the container and enable pgvector on it."""
    admin = create_engine(sync_url_for_db(container, container.dbname),
                          isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()
    target = create_engine(sync_url_for_db(container, db_name), isolation_level="AUTOCOMMIT")
    with target.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    target.dispose()


def make_async_engine(container: PostgresContainer, db_name: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for a per-test DB inside the container."""
    return create_async_engine(async_url_for_db(container, db_name), pool_pre_ping=True)


def alembic_upgrade_for_branch(container: PostgresContainer, branch: str) -> str:
    """Create a fresh DB and run `alembic upgrade head` for one branch.

    Returns the DB name (so the caller can build engines / dump schema against it).
    Uses the per-DB ini files landed in DI-7 (Sprint A.5).
    """
    db = f"alembic_{branch}"
    create_database(container, db)
    cfg = Config(str(REPO_ROOT / "migrations" / f"alembic_{branch}.ini"))
    cfg.set_main_option("sqlalchemy.url", sync_url_for_db(container, db))
    cfg.set_main_option("db_name", branch)  # env.py::get_db_name() reads this
    command.upgrade(cfg, "head")
    return db


def dump_schema(container: PostgresContainer, db_name: str) -> str:
    """Return normalized `pg_dump --schema-only` for `db_name`.

    Uses container.exec to invoke pg_dump from inside the image (avoids
    requiring a postgres-client install on the host). Normalization:
    drop comment-only / Dumped-from lines + sort top-level statements
    by (object kind, object name) so that OID-ordering differences
    between alembic and legacy DDL don't false-positive the parity diff.
    """
    result = container.exec(
        [
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
    # testcontainers 4.x returns ExecResult(exit_code, output) — both attr and tuple-unpack work
    rc = getattr(result, "exit_code", None)
    out = getattr(result, "output", None)
    if rc is None:  # legacy tuple-form
        rc, out = result
    assert rc == 0, f"pg_dump failed (rc={rc}):\n{out!r}"
    raw = out.decode("utf-8") if isinstance(out, bytes) else out
    return _normalize_pg_dump(raw)


def _normalize_pg_dump(raw: str) -> str:
    """Drop noise lines and sort top-level statements for stable diff."""
    statements: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("--"):  # SQL comment, includes "Dumped from", "Name:", etc.
            continue
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
        return (head.split()[0] if head else "", head)

    statements.sort(key=_sort_key)
    return "\n\n".join(s for s in statements if s)
```

### Шаг 3: `tests/test_migrations_runtime_upgrade.py` (DI-9 phase 2 sub-goal 1)

```python
"""Runtime mirror of test_migrations_self_contained (DI-9 phase 2).

For each branch: spin a clean DB inside the session pgvector container,
run alembic upgrade head, assert the resulting schema contains the
expected tables and critical indexes (the bits AST analysis can't see).
"""

import pytest
from sqlalchemy import create_engine, text

from tests._testcontainer_fixtures import (
    alembic_upgrade_for_branch,
    pgvector_container,  # noqa: F401  pytest fixture
    requires_testcontainers,
    sync_url_for_db,
)

BRANCHES = ("ingestion", "raw", "processing")

EXPECTED_TABLES = {
    "ingestion": {"sources", "comment_cursors", "source_attempts",
                  "users", "user_auth_mappings", "digest_subscriptions",
                  "alembic_version_ingestion"},
    "raw":       {"raw_messages", "raw_conflicts", "alembic_version_raw"},
    "processing": {
        "processed_documents", "topic_cards", "topic_bundles", "topic_links",
        "agent_state", "task_history", "agent_stats", "handoff_history",
        "processing_failures", "document_embeddings",
        "alembic_version_processing",
    },
}

CRITICAL_INDEXES = {
    "processing": {
        "topic_bundles_current_unique_idx",
        "topic_bundles_snapshot_unique_idx",
        # add others as discovered during smoke
    },
}


@requires_testcontainers
@pytest.mark.parametrize("branch", BRANCHES)
def test_alembic_upgrade_head_runtime(pgvector_container, branch):
    db = alembic_upgrade_for_branch(pgvector_container, branch)
    eng = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with eng.connect() as conn:
            tables = {r[0] for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ).fetchall()}
            indexes = {r[0] for r in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
            ).fetchall()}
    finally:
        eng.dispose()

    missing_tables = EXPECTED_TABLES[branch] - tables
    assert not missing_tables, f"branch {branch}: alembic upgrade missing tables: {missing_tables}"

    expected_indexes = CRITICAL_INDEXES.get(branch, set())
    missing_indexes = expected_indexes - indexes
    assert not missing_indexes, f"branch {branch}: missing critical indexes: {missing_indexes}"
```

> **EXPECTED_TABLES sanity-check:** перед коммитом сверить set против фактического `pg_tables` от живой БД (`tg-parser db upgrade --db <branch>` локально → `psql ... -c "\dt"` в docker compose) — не из памяти. Возможны таблицы, которых нет в моём списке (например, `digest_subscriptions` mapped по правам сейчас в ingestion ветке — проверить).

### Шаг 4: `tests/test_alembic_vs_legacy_ddl_parity.py` (DI-19 prep)

```python
"""Parity proof: alembic-built schema == legacy init_*_schema() schema.

Required as the safety gate for Sprint A.7 / DI-19 (drop EMBEDDING_DDL +
init_*_schema()). If this test goes green, removing the legacy helpers
becomes a mechanical refactor.
"""

import asyncio

import pytest

from tests._testcontainer_fixtures import (
    alembic_upgrade_for_branch,
    create_database, dump_schema, make_async_engine,
    pgvector_container,  # noqa: F401
    requires_testcontainers,
)

LEGACY_INIT = {
    "ingestion": "tg_parser.storage.sqlalchemy.schemas.ingestion_state.init_ingestion_state_schema",
    "raw": "tg_parser.storage.sqlalchemy.schemas.raw_storage.init_raw_storage_schema",
    "processing": "tg_parser.storage.sqlalchemy.schemas.processing_storage.init_processing_storage_schema",
}


def _resolve(dotted: str):
    mod, _, attr = dotted.rpartition(".")
    return getattr(__import__(mod, fromlist=[attr]), attr)


async def _run_legacy_init(container, branch: str) -> str:
    """Create `legacy_<branch>` DB and run init_*_schema() against it.

    Single-loop wrapper: asyncpg engines are bound to the loop they were
    created on. Calling create + init + dispose inside one `asyncio.run`
    keeps everything on the same loop.
    """
    legacy_db = f"legacy_{branch}"
    create_database(container, legacy_db)  # sync call, fine inside async fn
    init_fn = _resolve(LEGACY_INIT[branch])
    eng = make_async_engine(container, legacy_db)
    try:
        await init_fn(eng)
    finally:
        await eng.dispose()
    return legacy_db


@requires_testcontainers
@pytest.mark.parametrize("branch", ("ingestion", "raw", "processing"))
def test_alembic_schema_matches_legacy_ddl(pgvector_container, branch):
    alembic_db = alembic_upgrade_for_branch(pgvector_container, branch)
    legacy_db = asyncio.run(_run_legacy_init(pgvector_container, branch))

    alembic_dump = dump_schema(pgvector_container, alembic_db)
    legacy_dump = dump_schema(pgvector_container, legacy_db)

    # Whitelist: alembic_version_<branch> table only exists on alembic side.
    alembic_filtered = "\n\n".join(
        s for s in alembic_dump.split("\n\n")
        if f"alembic_version_{branch}" not in s
    )

    assert alembic_filtered == legacy_dump, (
        f"branch {branch}: alembic vs legacy DDL diverge.\n"
        f"--- alembic (alembic_version filtered) ---\n{alembic_filtered}\n"
        f"--- legacy ---\n{legacy_dump}"
    )
```

⚠️ **Ожидаемые расхождения** (если упадёт первый прогон — нормально, не паниковать; whitelist'им или фиксим):
- `alembic_version_<branch>` table — отсутствует в legacy (already filtered).
- Возможно cosmetic differences в default expressions (`now()` vs `CURRENT_TIMESTAMP`, etc.) — расширить нормализацию в `_normalize_pg_dump` если встретится.
- Возможно отсутствует partial unique index в legacy (если PROCESSING_STORAGE_DDL не догнал миграцию `b8e2f7c1d9a3`) — это **истинный bug в legacy**, который нужно либо пофиксить в legacy DDL, либо whitelist'ить с явным TODO для DI-19.

Strategy при первом красном прогоне: **печатаем diff, классифицируем построчно**: (a) cosmetic — обновляем `_normalize_pg_dump`; (b) acceptable structural (alembic-only bookkeeping) — whitelist; (c) **real divergence** — фиксим legacy DDL чтобы соответствовало (это и есть value этой проверки).

### Шаг 5: CI integration

Опции:

**(a) Extend `alembic-guardrail` job** новым step'ом (использует ту же postgres service — но testcontainers требует Docker socket, не postgres service. Не подходит).

**(b) Новый job `alembic-parity` с DinD.** Чище:

```yaml
  alembic-parity:
    name: Alembic Parity (testcontainers)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -e .
      - name: Run testcontainers migration tests
        env:
          TEST_TESTCONTAINERS: "1"
          # API key envs needed because conftest imports tg_parser.config
          OPENAI_API_KEY: sk-test
          ANTHROPIC_API_KEY: sk-ant-test
          GEMINI_API_KEY: test
        run: |
          pytest tests/test_migrations_runtime_upgrade.py \
                 tests/test_alembic_vs_legacy_ddl_parity.py \
                 -v --tb=short
```

GitHub `ubuntu-latest` runner has Docker daemon → testcontainers works without extra setup.

### Шаг 6: Smoke (локально)

```bash
# Один раз
.venv/bin/pip install "testcontainers[postgres]>=4.8"

# Прогон (Docker daemon должен быть запущен)
TEST_TESTCONTAINERS=1 .venv/bin/pytest \
  tests/test_migrations_runtime_upgrade.py \
  tests/test_alembic_vs_legacy_ddl_parity.py \
  -v --tb=short

# Если parity упало — посмотреть полный diff
TEST_TESTCONTAINERS=1 .venv/bin/pytest \
  tests/test_alembic_vs_legacy_ddl_parity.py::test_alembic_schema_matches_legacy_ddl[processing] \
  -v --tb=long --no-header
```

Ожидаемое время: ~30–60 секунд на полный прогон (10 сек pgvector startup + 6 alembic upgrade'ов × ~3 сек + 3 legacy init × ~2 сек + 6 pg_dump × <1 сек).

### Шаг 7: Регрессионный pytest на остальном суите

```bash
# Без testcontainers — убедиться что conftest.py не сломали
.venv/bin/pytest --tb=short -q
```

Полный existing suite (~377 passed / 32 skipped baseline после A.4) должен остаться зелёным. Если в `_testcontainer_fixtures.py` будет случайный module-level side effect (например, `PostgresContainer(...)` на import time) — упадёт здесь.

### Шаг 8: Lint + format

```bash
.venv/bin/ruff format \
  tests/_testcontainer_fixtures.py \
  tests/test_migrations_runtime_upgrade.py \
  tests/test_alembic_vs_legacy_ddl_parity.py
.venv/bin/ruff check tg_parser/ tests/ migrations/
```

### Шаг 9: Документация

| Файл | Что обновить |
|---|---|
| `docs/runbooks/SAFE_MIGRATION_ON_DEV.md` | Новый раздел «Parity check before merging schema PR»: запустить `TEST_TESTCONTAINERS=1 pytest tests/test_alembic_vs_legacy_ddl_parity.py -v` если миграция трогает структуру таблиц. |
| `docs/runbooks/DEV_RESURRECTION.md` | Новая FAQ Q: «Как локально проверить, что моя новая миграция эквивалентна legacy DDL?» → ссылка на parity test и `TEST_TESTCONTAINERS=1`. |
| `docs/notes/FUTURE_FEATURES.md` | DI-9 phase 2 → **FIXED** (с описанием 2 sub-goals + verification log). DI-19 entry — освежить блокер: "снят последний preq — parity proof в `tests/test_alembic_vs_legacy_ddl_parity.py`". Roadmap-таблица: A.6 ✅. |

### Шаг 10: Commit + push

Один атомарный коммит:

```bash
git add requirements.txt pyproject.toml \
        tests/_testcontainer_fixtures.py \
        tests/test_migrations_runtime_upgrade.py \
        tests/test_alembic_vs_legacy_ddl_parity.py \
        .github/workflows/ci.yml \
        docs/runbooks/SAFE_MIGRATION_ON_DEV.md \
        docs/runbooks/DEV_RESURRECTION.md \
        docs/notes/FUTURE_FEATURES.md
git commit -m "test(migrations): testcontainers smoke + alembic↔legacy DDL parity (DI-9 phase 2)"
git push origin main
gh run watch
```

---

## Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| Parity test находит **реальные** различия legacy DDL vs alembic | Medium-High | **Это и есть value сессии.** Каждое расхождение — либо bug в legacy (фиксим, добавляем смысловую миграцию если нужно), либо acceptable cosmetic (расширяем normalization). Документируем в коммите/runbook. |
| testcontainers не стартует в CI (Docker socket missing) | Low | GitHub `ubuntu-latest` имеет Docker из коробки (используется `docker` job уже сейчас). Если упадёт — проверить, что job не запущен на self-hosted runner без Docker. |
| Локально нет Docker daemon (mac пользователи запустили pytest без OrbStack/Docker Desktop) | Medium | Тесты opt-in через `TEST_TESTCONTAINERS=1`. По дефолту skip'аются — никто не получит false negative. Помечено в conftest. |
| `alembic.command.upgrade` API не пробрасывает `db_name` корректно | Low | Primary path: `cfg.set_main_option("db_name", branch)` — `migrations/env.py::get_db_name()` (lines 53–70) уже читает оба источника (`-x` через `context.get_x_argument` и main option через `config.get_main_option("db_name")`). Если внезапно отвалится — plan B: `cfg.cmd_opts = type("X", (), {"x": [f"db_name={branch}"]})()` (имитация `-x` flag). |
| testcontainers session-scope конфликтует с function-scoped `cleanup_job_store` autouse fixture | Low | Новые тесты используют только `pgvector_container` fixture (session) и свежий engine на каждый тест — никаких side-effects на JobStore / Database singleton. |
| pg_dump output format меняется от minor PG версии | Very low | Образ pinned (`pgvector/pgvector:pg17`). Минорные апдейты pg17 → cosmetic diff'ы в worst case → расширяем `_normalize_pg_dump`. |
| Parity diff большой (~сотни строк) при первом прогоне | High | Это **ожидается**. Strategy: запустить, ручной разбор, классификация (cosmetic/acceptable/real-bug), iterate. Может занять 30–60 минут first-pass. |

**Rollback:** `git revert <commit>`. Никаких production schema changes; новые тесты opt-in. Зависимость `testcontainers` остаётся в venv, но не вызывается без `TEST_TESTCONTAINERS=1`.

---

## PR checklist

- [ ] `testcontainers[postgres]>=4.8` добавлен в `requirements.txt` и `pyproject.toml::dev`.
- [ ] `tests/_testcontainer_fixtures.py` создан с публичным API: `pgvector_container` (session fixture) + `sync_url_for_db` / `async_url_for_db` + `create_database` + `make_async_engine` + `alembic_upgrade_for_branch` + `dump_schema` + `requires_testcontainers` marker (private: `_normalize_pg_dump`).
- [ ] `tests/test_migrations_runtime_upgrade.py` зелёный с `TEST_TESTCONTAINERS=1` (3 параметризованных теста, по одному на ветку).
- [ ] `tests/test_alembic_vs_legacy_ddl_parity.py` зелёный с `TEST_TESTCONTAINERS=1` (3 параметризованных теста). Любые whitelist-расхождения объяснены inline комментарием со ссылкой на DI-#.
- [ ] Полный `pytest --tb=short -q` (без `TEST_TESTCONTAINERS`) — суит как до сессии (новые тесты skip'аются по marker'у).
- [ ] CI: новый job `alembic-parity` зелёный (testcontainers под Docker-in-Docker на runner'е).
- [ ] Существующие 4 CI job'а зелёные.
- [ ] `ruff format` + `ruff check tg_parser/ tests/ migrations/` чистые.
- [ ] `docs/runbooks/SAFE_MIGRATION_ON_DEV.md` пополнен разделом про parity check.
- [ ] `docs/runbooks/DEV_RESURRECTION.md` FAQ дополнен.
- [ ] `docs/notes/FUTURE_FEATURES.md`: DI-9 phase 2 → **FIXED** с verification log; DI-19 entry освежён («снят preq — parity proof готов»); roadmap-таблица A.6 ✅.
- [ ] Если найдены real divergences (не cosmetic) — каждая зафиксирована либо новой миграцией, либо явным комментом в legacy DDL (с TODO под DI-19).

---

## После A.6 — Sprint A.7 / DI-19

Следующая (последняя в migration tech-debt серии) сессия — drop legacy `EMBEDDING_DDL` / `init_*_schema()`:

1. Используем `pgvector_container` + `make_async_engine` из A.6 для нового pytest fixture `alembic_initialized_db(branch)` — session-scoped, делает `alembic upgrade head` один раз, выдаёт engine.
2. Переписываем 11 test-файлов из аудит-списка (см. секцию «Test files, которые остаются на legacy DDL» выше) — заменяем `init_*_schema(engine)` на новый fixture.
3. **Особый случай `tests/test_f5a_topic_rag.py`** — содержит ассерты на содержимое `EMBEDDING_DDL` строки. Переписать на семантические assertions («после `alembic upgrade head` колонка `entry_type` существует с типом VARCHAR» через SQLAlchemy reflection).
4. Удалить `EMBEDDING_DDL`, `EMBEDDING_INDEX_DDL`, `PROCESSING_STORAGE_DDL`, `INGESTION_DDL`, `RAW_DDL`, `init_processing_storage_schema`, `init_ingestion_state_schema`, `init_raw_storage_schema`, `init_embedding_index`, `_ensure_pgvector`, `_ensure_embedding_columns`, `_ensure_fts_columns`, `_ensure_content_hash_column` из `tg_parser/storage/sqlalchemy/schemas/`.
5. Удалить `init_databases_fallback` из `tg_parser/cli/init_db.py` + reexports в `tg_parser/storage/sqlalchemy/__init__.py` + `schemas/__init__.py`. Если alembic CLI не стартует — это критичная ошибка деплоя, fallback в DDL только маскирует проблему. Заменить на чёткий error message.
6. Полный pytest зелёный + alembic-parity job всё ещё работает на чистой alembic-only сборке.

См. [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md) DI-19 entry (~line 2838).

После A.7 — migration tech-debt = 0.
