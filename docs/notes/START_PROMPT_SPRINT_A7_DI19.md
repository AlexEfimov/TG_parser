# Sprint A.7 — DI-19 (drop legacy `EMBEDDING_DDL` / `init_*_schema()` + rewrite ~14 test fixtures)

**Дата подготовки:** 19 апреля 2026 (по итогам Sprint A.6 / DI-9 phase 2, Session 54).
**Тип сессии:** Refactor + cleanup (~1–1.5 сессии).
**HEAD:** `7a406b6` на `origin/main` (Sprint A.6 закрыт; CI зелёный — Test Python 3.12, Alembic Guardrails, Alembic ↔ Legacy DDL Parity (testcontainers), Lint Documentation, Docker Build).
**Связанные задачи в [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md):** DI-19 (~line 2838, статус **READY** — все блокеры сняты A.6).
**Roadmap:** A.5 ✅ (DI-7) → A.6 ✅ (DI-9 phase 2) → **A.7 (DI-19, эта)**. После A.7 migration tech-debt = 0.
**Прецеденты (читать перед стартом):** [`START_PROMPT_SPRINT_A6_DI9_PHASE2.md`](START_PROMPT_SPRINT_A6_DI9_PHASE2.md) (структура prompt'а; lessons про CI / ruff / pytest_plugins / testcontainers fixture API), `tests/_testcontainer_fixtures.py` (готовая инфраструктура для этой сессии — `alembic_upgrade_for_branch`, `dump_schema`), `tests/test_alembic_vs_legacy_ddl_parity.py` (формальное доказательство, что alembic == legacy DDL — основание удалять legacy).

---

## Цель сессии

Закрыть **DI-19** и завершить migration tech-debt sprint. Удалить параллельную «вторую правду» о схеме (legacy raw DDL helpers), оставив **alembic единственным источником**. Конкретно:

1. **Test fixtures (~14 файлов)** — заменить `await init_*_schema(engine)` на сессионный `alembic upgrade head` + per-test reset. Без overhead'а subprocess'а на каждый тест.
2. **`test_f5a_topic_rag.py` (особый случай)** — содержит ассерты на содержимое строки `EMBEDDING_DDL` (substring checks: `"entry_type"`, `"topic_id"`, `"REFERENCES processed_documents"`, `"idx_de_entry_type"`, `"DEFAULT 'message'"`). Переписать на семантические assertions через PG `information_schema` reflection (DI-9 phase 1 уже гарантирует, что миграции эти объекты создают; здесь мы лишь подтверждаем runtime-форму).
3. **Production fallback** — удалить `tg_parser/cli/init_db.py::init_databases_fallback` и dead branch `if not use_alembic` в `init_databases_sync`. Заменить на diagnostic error («alembic CLI failed at <path>; fix install with `pip install -e .` or check `migrations/alembic_<branch>.ini` exists»). Маскировать broken install молчаливым DDL-fallback опаснее, чем падать громко.
4. **Schemas package cleanup** — удалить из `tg_parser/storage/sqlalchemy/schemas/`:
   - Raw DDL strings: `EMBEDDING_DDL`, `EMBEDDING_INDEX_DDL`, `PROCESSING_STORAGE_DDL`, `INGESTION_STATE_DDL`, `RAW_STORAGE_DDL`.
   - Entry points: `init_processing_storage_schema`, `init_ingestion_state_schema`, `init_raw_storage_schema`, `init_embedding_index`.
   - Idempotent helpers: `_ensure_pgvector`, `_ensure_embedding_columns`, `_ensure_fts_columns`, `_ensure_content_hash_column`.
   - Reexports в `tg_parser/storage/sqlalchemy/schemas/__init__.py` и `tg_parser/storage/sqlalchemy/__init__.py`.
   - **Не удалять** сами `.py` файлы: оставить `ingestion_state.py` / `processing_storage.py` / `raw_storage.py` как пустышки с docstring-примечанием, что вся логика теперь в `migrations/versions/<db>/`. (В отдельном PR можно будет грохнуть совсем; пока — минимальный blast radius на git history.)
   - **Альтернатива:** удалить файлы целиком, если grep подтверждает, что никто кроме `__init__.py` их не импортирует. Решение принимается на Шаге 3, после grep'а.
5. **`tests/test_migrations.py`** — удалить целиком (его coverage полностью покрывается `tests/test_migrations_runtime_upgrade.py` из A.6: `pg_tables` inventory + critical indexes + `vector` extension; runtime path даже строже — alembic upgrade head на чистой БД, не idempotent CREATE IF NOT EXISTS).

### Не входит в сессию

- **DI-5** (operational backfill 4 каналов) — независимый ops-таск.
- Реорганизация `tg_parser/storage/sqlalchemy/schemas/__init__.py` структуры папки (например, перенос репо-классов выше / переименование пакета) — оставляем как есть.
- Изменения в самих миграциях (`migrations/versions/**/*.py`) — alembic chain заморожен с A.6 как ground truth. Если test rewrite найдёт реальный gap (объект используется в коде, но миграция не создаёт) — это новая миграция в отдельной сессии, **не** в этой.

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на 7a406b6
gh run list --branch main --limit 3              # CI на 7a406b6 зелёный?

# Local стек (нужен для регрессии test-сьюта против tg_parser_test PG)
docker compose ps                                # tg_parser_postgres healthy
PGPASSWORD=tg_parser_pass psql -h localhost -U tg_parser_user -d tg_parser_test -c "\dt" | head

# Docker daemon доступен — для прогона A.6 testcontainers тестов после рефакторинга
docker version

# Sanity: оба guardrail'а от A.6 зелёные на чистой БД (т.е. ничего не сломали с прошлой сессии)
TEST_TESTCONTAINERS=1 .venv/bin/pytest \
  tests/test_migrations_runtime_upgrade.py \
  tests/test_alembic_vs_legacy_ddl_parity.py -v --tb=short

# Прочитать DI-19 entry в FUTURE_FEATURES.md
grep -nE "^### DI-19:" docs/notes/FUTURE_FEATURES.md
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` (sustained lesson из Sprints A → A.6 — иначе CI красный на line-length / import order / B023).

**Pre-condition для всей сессии:** Sprint A.6 должен быть смерджен (commit `7a406b6` на `main`). Без `tests/_testcontainer_fixtures.py` и parity-proof невозможно безопасно удалять legacy DDL — мы потеряем единственное доказательство, что alembic покрывает 100% legacy объектов.

---

## Контекст: что мы знаем после аудита 19 апреля 2026

Все цифры/пути проверены в коде HEAD `7a406b6` через grep, не из памяти.

### Аудит call-sites legacy DDL helpers

**14 test-файлов** импортируют `init_*_schema` или `EMBEDDING_DDL` (полный grep: `grep -rln "init_processing_storage_schema\|init_ingestion_state_schema\|init_raw_storage_schema\|init_embedding_index\|EMBEDDING_DDL" tests/`):

| Файл | Что использует | Сложность переписывания |
|---|---|---|
| `tests/test_storage_integration.py` | ingestion + raw + processing | Trivial — заменить 3 строки на отсутствие (test_db уже подготовлен). |
| `tests/test_e2e_pipeline.py` | ingestion + raw + processing | Trivial. |
| `tests/test_f2_parse_only_export.py` | ingestion + raw + processing (lines 687–711) | Trivial. |
| `tests/test_f5a_phase3_dedup.py` | processing × 5 import sites | Mechanical. |
| `tests/test_f5a_hybrid_search.py` | processing × 4 import sites | Mechanical. |
| `tests/test_retrieval_hybrid_session.py` | processing × 1 | Trivial. |
| `tests/test_embedding.py` | processing × 1 | Trivial. |
| `tests/test_agents_observability.py` | processing × 1 (lazy import) | Trivial. |
| `tests/test_multi_agent.py` | processing × 1 (lazy import) | Trivial. |
| `tests/test_f6_scheduled_digests.py` | ingestion × 1 | Trivial. |
| `tests/test_migrate_users_cmd.py` | ingestion × 1 | Trivial. |
| `tests/test_cli_db_cleanup_orphan_admin.py` | ingestion × 1 | Trivial. |
| **`tests/test_f5a_topic_rag.py`** | **6 substring asserts на `EMBEDDING_DDL` строку!** | **Special — переписать на information_schema reflection.** |
| **`tests/test_migrations.py`** | **Сам тестирует `init_*_schema()` (3 теста + assertion на content_hash + topic_bundles uniques)** | **Special — удалить целиком, coverage уже в `test_migrations_runtime_upgrade.py`.** |

Дополнительные production call-sites:
- `tg_parser/cli/init_db.py:79` — `init_databases_fallback()` async фунция, вызывается из `init_databases_sync` (line 134) только если `run_alembic_upgrade` упал.
- `tg_parser/storage/sqlalchemy/__init__.py:17–21` — reexports `init_*_schema` (3 функции).
- `tg_parser/storage/sqlalchemy/schemas/__init__.py:7–16` — реэкспорт + `__all__`.

Никаких других call-sites вне `tests/` и `tg_parser/cli/init_db.py` нет (проверено grep'ом).

### Что уже работает (foundation, не трогать)

| Слой | Статус |
|---|---|
| Alembic chain (3 ветки, single head per branch) | DI-7 / DI-9 phase 1 + 3 ✅ — `tg-parser db upgrade --db <branch>` производит полную схему. |
| `tests/_testcontainer_fixtures.py` | Sprint A.6 ✅ — публичное API (`pgvector_container`, `alembic_upgrade_for_branch`, `make_async_engine`, `dump_schema`) готово к переиспользованию. |
| `tests/test_migrations_runtime_upgrade.py` | Sprint A.6 ✅ — runtime guardrail: `pg_tables` inventory + critical indexes + `vector` extension. Это полный замените `tests/test_migrations.py`. |
| `tests/test_alembic_vs_legacy_ddl_parity.py` | Sprint A.6 ✅ — parity proof. После A.7 этот тест **сам по себе становится мёртвой проверкой** (legacy DDL удалена); решение по нему — на Шаге 7 (см. ниже). |
| Static guardrails (`test_migrations_self_contained`, `test_repo_sql_references_declared_tables`, `test_metadata_matches_migrations`, `test_alembic_ini_consistency`) | DI-9 phase 1 / 3 + DI-1 + DI-7 ✅ — продолжают работать без изменений. |

### Hidden gotchas

1. **`test_db` fixture в `tests/conftest.py` (lines 58–75) — НЕ создаёт схему сама.** Просто открывает `Database` singleton, ожидая что схема уже существует в `tg_parser_test`. Сейчас тесты компенсируют это, вызывая `await init_*_schema(engine)` в начале каждого теста. После DI-19 эта компенсация исчезнет → нужно либо (a) обновить `test_db` чтобы он сам делал `alembic upgrade head` один раз, либо (b) подготовить схему через CI-step / dev-bootstrap. **Рекомендуется (a)**: session-scoped helper в `conftest.py` делает `alembic upgrade head` (idempotent — no-op после первого раза), плюс function-scoped `test_db` делает `TRUNCATE ... CASCADE` всех таблиц между тестами. Альтернатива (b) хрупка: тесты, запускаемые поодиночке (особенно после `git clean`), не получат подготовленную БД.

2. **`tests/test_storage_integration.py:33–55` имеет СВОЮ `test_db` fixture** (overrides conftest.py). Она делает `Database(test_settings)` напрямую через `_test_pg_settings()` и потом вызывает 3 `init_*_schema(...)`. Этот override после DI-19 нужно либо удалить (использовать conftest.py-вский), либо переписать чтобы не вызывал legacy. **Решение:** удалить override, использовать conftest.py — он после рефакторинга уже подготавливает схему.

3. **`tests/test_f5a_topic_rag.py:25–47` — substring asserts на `EMBEDDING_DDL` строку.** 6 проверок:
   - `assert "entry_type" in EMBEDDING_DDL`
   - `assert "topic_id" in EMBEDDING_DDL`
   - `assert "REFERENCES processed_documents" not in EMBEDDING_DDL` (FK явно отсутствует)
   - `assert "idx_de_entry_type" in EMBEDDING_DDL`
   - `assert "DEFAULT 'message'" in EMBEDDING_DDL`
   
   После удаления `EMBEDDING_DDL` все эти assertions сломаются. Переписать как **runtime reflection** против alembic-built схемы (через session test_db):
   ```python
   async def test_document_embeddings_has_entry_type(test_db):
       async with test_db.processing_storage_engine.connect() as conn:
           result = await conn.execute(text(
               "SELECT column_name, column_default, data_type "
               "FROM information_schema.columns "
               "WHERE table_name = 'document_embeddings' "
               "AND column_name = 'entry_type'"
           ))
           row = result.fetchone()
           assert row is not None, "entry_type column missing"
           assert row.column_default and "message" in row.column_default
   ```
   Аналогично для остальных. Это семантически даже сильнее: проверяем фактическую runtime-схему, не строку DDL которую кто-то мог обойти миграцией с тем же эффектом.

4. **`tests/test_migrations.py` — нельзя «переписать», нужно удалить.** Его 3 теста (`test_init_ingestion_state_schema`, `test_init_raw_storage_schema`, `test_init_processing_storage_schema`) — это smoke `init_*_schema()`. После DI-19 функций больше нет. Coverage полностью сохраняется в `tests/test_migrations_runtime_upgrade.py` (из A.6) + `tests/test_alembic_vs_legacy_ddl_parity.py` (из A.6, но только пока legacy жива; см. п. 7). Дополнительные ассерты в `test_migrations.py` (content_hash column, topic_bundles uniques, processing inventory) уже покрыты `EXPECTED_TABLES` + `CRITICAL_INDEXES` в `test_migrations_runtime_upgrade.py`. Перед удалением — diff'нуть оба expected set'а и убедиться, что `test_migrations_runtime_upgrade.py` ≥ `test_migrations.py` по coverage.

5. **`init_databases_sync`'s use_alembic flag is dead branch.** После DI-7 `migrations/alembic_<db>.ini` существует и subprocess стабилен. `if not use_alembic: asyncio.run(init_databases_fallback())` — последний оставшийся reason держать DDL helpers в production. Удалить ветку и саму fallback-функцию. Если subprocess упал — `typer.echo()` диагностику и `raise typer.Exit(1)`. Это поведение, корректное для сценария «alembic broken» — оно громко падает, не маскирует.

6. **`asyncio.run` в production fallback** — выкидывается вместе с функцией. Дополнительный плюс: одной точкой меньше где `asyncio.run()` создаёт новый loop (источник subtle bugs в pytest-окружении).

7. **`tests/test_alembic_vs_legacy_ddl_parity.py` после удаления legacy DDL — что с ним делать?** Тест сравнивает alembic-built schema с `init_*_schema()`-built schema. После DI-19 второй стороны сравнения не существует. Опции:
   - **(a) Удалить** — больше нечего сравнивать, тест мертвеет вместе с тем, что он проверял. Минус: теряем regression-плотность; если в будущем кто-то захочет верифицировать миграцию против внешней истины (например, dump прода) — придётся восстанавливать инфраструктуру.
   - **(b) Skip с явным маркером** — оставить файл с `pytest.mark.skip(reason="DI-19: legacy DDL removed; test kept as documentation of historical parity")`. Минус: технический мусор в test-tree.
   - **(c) Перепрофилировать** — оставить инфраструктуру (`pgvector_container` + `alembic_upgrade_for_branch` + `dump_schema`), но превратить тест в snapshot-проверку: сохранить нормализованный pg_dump в `tests/snapshots/alembic_<branch>.sql`, тест ассертит идентичность. Это превращает A.6 наследие в полезный регрессионный сейф против неосознанных schema-изменений в миграциях. **Рекомендуется (c)**, но это +0.5 сессии scope. **Pragmatic выбор: (a)**, документировать причину в commit message + DI-19 closure note. Snapshot-тест можно вытащить как DI-20 в отдельной сессии при появлении конкретной потребности.

   **По умолчанию: (a)** — удалить. Если на Шаге 5 появится время или конкретный повод (например, мы заметили что parity-нормализатор уже ловит interesting drift) — переключиться на (c).

8. **Imports, которых в `conftest.py` сейчас нет** (проверено grep'ом 19.04.2026): нет `from __future__ import annotations`, нет `from sqlalchemy import text`, нет `from pathlib import Path`, нет alembic-импортов. Добавить блоком при реализации Шага 1; ruff `I001` подскажет точное место в импорт-порядке. `__future__` — обязательно если используем PEP 604 union syntax (`Settings | None`), без него — опционально.

9. **CI `test` job**'s PG service создаёт пустую `tg_parser_test` БД (см. `.github/workflows/ci.yml:14–22`). После DI-19 первый тест с `test_db` fixture запустит alembic upgrade head — это первый раз, когда CI test-suite будет полагаться на migration chain (а не на DDL helpers). Время накатки ~5–8 секунд, окупится один раз.

10. **Session vs function fixture interplay с `cleanup_job_store` autouse.** В conftest.py:183 живёт `@pytest.fixture(autouse=True)` `cleanup_job_store`, который после каждого теста делает `Database.reset_instance()` + `JobStore.reset()`. Новый `test_db` (function-scope) тоже делает `Database.reset_instance()` в `finally`. Двойной reset безопасен (метод idempotent). Однако: новый session-scope `_alembic_initialized_test_db` НЕ должен возвращать сам `Database` instance — только `Settings`. Иначе session-scope cached engine разойдётся с тем, что autouse-reset обнулил. Поэтому в Шаге 1 фикстура yield'ит `Settings`, а `Database.get_instance(s)` создаётся заново в function-scope `test_db`.

11. **`alembic upgrade head` из `conftest.py` — sync subprocess или Python API?** Sync subprocess — простой, но требует разрешения путей и переменных окружения. Python API (`alembic.config.Config` + `command.upgrade`) — тот же подход, что в `_testcontainer_fixtures.py::alembic_upgrade_for_branch`, можно factor'нуть в общий helper. **Рекомендуется** перенести `alembic_upgrade_for_branch` (или вариант `alembic_upgrade_against_url(url, branch)`) в новый модуль `tests/_alembic_helpers.py` (или прямо в conftest), чтобы и testcontainers-вариант, и conftest-вариант дёргали одну реализацию. Избегаем дублирования и риска расхождения.

---

## План шагов

### Шаг 1: Подготовить session-scoped alembic-фикстуру в `conftest.py`

Цель: один раз за сессию накатить `alembic upgrade head` для всех 3 веток против существующей `tg_parser_test`. Function-scoped `test_db` fixture делает `TRUNCATE ... CASCADE` между тестами.

```python
# tests/conftest.py — добавить (рядом с _test_pg_settings)
from alembic import command
from alembic.config import Config

def _alembic_upgrade_against_settings(s: Settings, branch: str) -> None:
    """Run `alembic upgrade head` for one branch against `s.db_*` PostgreSQL.

    Uses the per-DB ini files from DI-7.  Idempotent — no-op when the
    DB is already at head, ~5–8 s on first invocation per session.
    """
    repo_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(repo_root / "migrations" / f"alembic_{branch}.ini"))
    # Build sync URL from Settings (asyncpg → psycopg2 for alembic subprocess; or use
    # asyncpg via env.py's async_engine_from_config — easier).
    cfg.set_main_option("sqlalchemy.url",
        f"postgresql+asyncpg://{s.db_user}:{s.db_password}@{s.db_host}:{s.db_port}/{s.db_name}")
    cfg.set_main_option("db_name", branch)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def _alembic_initialized_test_db():
    """Run alembic upgrade head once per session against tg_parser_test."""
    s = _test_pg_settings()
    for branch in ("ingestion", "raw", "processing"):
        _alembic_upgrade_against_settings(s, branch)
    yield s


@pytest.fixture
async def test_db(_alembic_initialized_test_db):
    """Fresh per-test Database — schema already up via session fixture, data truncated."""
    Database.reset_instance()
    s = _alembic_initialized_test_db
    db = Database.get_instance(s)
    await db.init()
    # Truncate all user tables in dependency order (CASCADE).
    async with db.processing_storage_engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_PROCESSING_SQL))
    async with db.raw_storage_engine.begin() as conn:
        await conn.execute(text("TRUNCATE raw_messages, raw_conflicts CASCADE"))
    async with db.ingestion_state_engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_INGESTION_SQL))
    try:
        yield db
    finally:
        await db.close()
        Database.reset_instance()
```

`_TRUNCATE_*_SQL` — список таблиц по веткам, без `alembic_version_<branch>`. Источник истины — `EXPECTED_TABLES` из `tests/test_migrations_runtime_upgrade.py` (импортируем). **Не truncate'ить `alembic_version_<branch>`** — иначе следующий test триггернёт повторный upgrade.

> ⚠️ **Watch out:** `cleanup_job_store` autouse fixture в conftest.py (line 184) уже делает `Database.reset_instance()` после теста. Новый `test_db` тоже делает reset — двойной reset безопасен, но проверить, что autouse fixture не получает уже-закрытый Database.

### Шаг 2: Удалить override `test_db` в `tests/test_storage_integration.py`

Lines 33–55 — локальная `test_db` fixture, которая сама делает 3× `init_*_schema()`. Удалить целиком, тест автоматически подхватит conftest-шный `test_db` (после Шага 1).

### Шаг 3: Mechanical rewrite — удалить `await init_*_schema(...)` из 12 «trivial» файлов

Точечно по grep-списку, без изменения логики тестов. Только убрать import + соответствующий `await init_*_schema(engine)` line.

```bash
# Список файлов:
tests/test_e2e_pipeline.py
tests/test_f2_parse_only_export.py
tests/test_f5a_phase3_dedup.py            # × 5 import sites — careful
tests/test_f5a_hybrid_search.py           # × 4 import sites
tests/test_retrieval_hybrid_session.py
tests/test_embedding.py
tests/test_agents_observability.py        # lazy import inside test fn
tests/test_multi_agent.py                 # lazy import inside test fn
tests/test_f6_scheduled_digests.py
tests/test_migrate_users_cmd.py
tests/test_cli_db_cleanup_orphan_admin.py
```

Smoke-проверка после каждого файла: `pytest tests/<file>.py -v --tb=short -x` (без `TEST_TESTCONTAINERS`).

### Шаг 4: Special — переписать `tests/test_f5a_topic_rag.py`

6 substring asserts на `EMBEDDING_DDL` → information_schema reflection. Шаблон:

```python
# Было:
def test_entry_type_in_embedding_ddl():
    from tg_parser.storage.sqlalchemy.schemas.processing_storage import EMBEDDING_DDL
    assert "entry_type" in EMBEDDING_DDL

# Стало:
async def test_document_embeddings_has_entry_type(test_db):
    async with test_db.processing_storage_engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='document_embeddings' AND column_name='entry_type'"
        ))
        row = result.fetchone()
    assert row is not None, "entry_type column missing on document_embeddings"
    assert row.column_default and "'message'" in row.column_default, (
        "entry_type DEFAULT must be 'message' (per migration a1b2c3d4e5f6)"
    )
```

Замечание про `"REFERENCES processed_documents" not in EMBEDDING_DDL` — это **negative** check (FK явно отсутствует — потому что embeddings могут быть orphan'ами после удаления документа). Переписать как:

```python
async def test_document_embeddings_no_fk_to_processed_documents(test_db):
    async with test_db.processing_storage_engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT conname FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname='document_embeddings' AND c.contype='f'"
        ))
        fks = {row.conname for row in result.fetchall()}
    assert not any("processed_documents" in f for f in fks), (
        f"document_embeddings must NOT have FK to processed_documents (allow orphans); found: {fks}"
    )
```

Все 6 asserts — за один проход. Smoke: `pytest tests/test_f5a_topic_rag.py -v -x`.

### Шаг 5: Удалить `tests/test_migrations.py`

```bash
rm tests/test_migrations.py
```

Перед удалением:
1. Сравнить `EXPECTED_TABLES` в `test_migrations.py` (3 hardcoded sets) с `EXPECTED_TABLES` в `test_migrations_runtime_upgrade.py`. Должны быть ⊆.
2. Проверить, что `topic_bundles_current_unique_idx` / `topic_bundles_snapshot_unique_idx` присутствуют в `CRITICAL_INDEXES["processing"]` — да, проверено (см. A.6 commit `7a406b6`).
3. `content_hash` column check — проверить, что хотя бы один тест в `test_migrations_runtime_upgrade.py` или другом suite убеждается, что колонка существует. Если нет — добавить в `test_migrations_runtime_upgrade.py` (мини-расширение, не отдельный файл).

### Шаг 6: Удалить production fallback в `tg_parser/cli/init_db.py`

```python
# Удалить функцию:
async def init_databases_fallback() -> None: ...     # lines 79–104

# Заменить в init_databases_sync (lines 107–134):
def init_databases_sync() -> None:
    import typer

    from tg_parser.cli.db_cmd import get_project_root

    project_root = get_project_root()
    typer.echo("  🔄 Применение миграций через Alembic...")

    for db_name in ("ingestion", "raw", "processing"):
        typer.echo(f"  📦 База: {db_name}")
        if not run_alembic_upgrade(db_name, project_root):
            typer.echo(
                f"  ❌ Alembic upgrade failed for {db_name!r}. "
                f"Diagnostic checks:\n"
                f"     1) {project_root / 'migrations' / f'alembic_{db_name}.ini'} exists?\n"
                f"     2) `python -m alembic --version` works in this venv?\n"
                f"     3) `pip install -e .` was run after pulling latest?\n"
                f"  Legacy DDL fallback removed in DI-19 (Sprint A.7) — see "
                f"docs/notes/FUTURE_FEATURES.md DI-19 entry.",
                err=True,
            )
            raise typer.Exit(code=1)
```

Также обновить docstring `init_databases_sync` — убрать упоминание DDL fallback.

### Шаг 7: Удалить раздачи DDL helpers из schemas package + reexports

**`tg_parser/storage/sqlalchemy/schemas/processing_storage.py`** (490 строк → ~20 строк placeholder):
- Удалить: `EMBEDDING_DDL`, `EMBEDDING_INDEX_DDL`, `PROCESSING_STORAGE_DDL`, `init_processing_storage_schema`, `init_embedding_index`, `_ensure_pgvector`, `_ensure_embedding_columns`, `_ensure_fts_columns`, `_ensure_content_hash_column`.
- Оставить только docstring-stub:
  ```python
  """Processing storage schema — REMOVED in DI-19 (Sprint A.7, 19.04.2026).

  Schema is now managed exclusively by alembic migrations in
  ``migrations/versions/processing/``.  See:
  - ``tg_parser/storage/sqlalchemy/_metadata.py`` for the SQLAlchemy
    Table declarations (target_metadata for ``alembic check``).
  - ``tests/test_migrations_runtime_upgrade.py`` for runtime smoke.
  """
  ```

Аналогично `ingestion_state.py` и `raw_storage.py`.

**`tg_parser/storage/sqlalchemy/schemas/__init__.py`** — очистить imports + `__all__`:
```python
"""Schema declarations — see individual modules for the post-DI-19 stubs."""

__all__: list[str] = []
```

**`tg_parser/storage/sqlalchemy/__init__.py`** — удалить lines 17–21 + соответствующие `__all__` записи (lines 30–33).

**Решение «удалять файлы целиком vs оставлять stubs»** — принимается на этом шаге после `grep -rn "from tg_parser.storage.sqlalchemy.schemas import\|from tg_parser.storage.sqlalchemy.schemas.processing_storage\|from tg_parser.storage.sqlalchemy.schemas.ingestion_state\|from tg_parser.storage.sqlalchemy.schemas.raw_storage" .`. Если после Шагов 2–6 grep даёт 0 результатов в `tg_parser/` и `tests/` — удалять файлы целиком (плюс пакет `schemas/` если пустой). Если хотя бы один import остался (вероятно зачищающий тест зависимости — например, `from .schemas import ...` в каком-нибудь legacy unit) — оставить stubs, чтобы import работал.

### Шаг 8: Решение по `tests/test_alembic_vs_legacy_ddl_parity.py`

По умолчанию **удалить** (см. Hidden gotcha #7). Если на этом шаге есть бюджет +30 минут — конвертировать в snapshot-тест: дампим один раз `alembic_ingestion.sql` / `alembic_raw.sql` / `alembic_processing.sql` в `tests/snapshots/`, тест ассертит идентичность. Это превращает A.6 нормализатор в постоянный регрессионный сейф против неосознанных schema-изменений (DI-9 phase 1 ловит «ALTER без CREATE», но не «случайно добавили колонку и забыли всем рассказать»). Если выбираем snapshot — добавить `tests/snapshots/README.md` с инструкцией «как пересоздавать после намеренного schema change».

**Default action:** удалить файл, удалить `_normalize_pg_dump` + `_sort_create_table_columns` из `_testcontainer_fixtures.py` (мертвеют без потребителя), но оставить остальной API (`pgvector_container`, `alembic_upgrade_for_branch`, `make_async_engine`) — он используется `test_migrations_runtime_upgrade.py` и пригодится для будущих smoke-тестов.

### Шаг 9: Обновить CI

**`.github/workflows/ci.yml::alembic-parity` job** — runs только parity test, который мы возможно удаляем. Опции:
- Если parity test удалён: оставить job с одним `test_migrations_runtime_upgrade.py` (переименовать в `alembic-runtime-smoke`).
- Если parity test → snapshot: переименовать в `alembic-snapshot` и оставить.
- В обоих случаях: пересмотреть `pytest tests/test_migrations_runtime_upgrade.py tests/test_alembic_vs_legacy_ddl_parity.py` строку, оставить только runtime test (или snapshot test).

`test` job — ничего не меняем; он автоматически выиграет от `alembic upgrade head` в conftest при первом тесте.

### Шаг 10: Регрессионный пробег

```bash
# 1. Без TEST_TESTCONTAINERS — основной suite (должен полностью совпасть с 1549 baseline из A.6)
.venv/bin/pytest --tb=short -q

# 2. С TEST_TESTCONTAINERS=1 — testcontainers-based smoke (должен дать 4 passed, parity tests
#    либо удалены либо converted)
TEST_TESTCONTAINERS=1 .venv/bin/pytest \
  tests/test_migrations_runtime_upgrade.py \
  -v --tb=short
```

Ожидаемое: count тестов = 1549 (baseline) − 3 (test_migrations.py) + 0 (legacy → semantic переписаны 1:1 в test_f5a_topic_rag) − 3 (parity if removed) = **~1543 passed**, 119 skipped (без изменений). Отклонения > ±5 — разбираться.

### Шаг 11: Lint + format

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
```

Зачистить любые F401 (unused imports после Шага 3), B023, RUF012 etc.

### Шаг 12: Документация

| Файл | Что обновить |
|---|---|
| `docs/notes/FUTURE_FEATURES.md` | DI-19 → **FIXED** (commit-pattern «closing sweep»), с verification log + breaking changes summary. Roadmap-таблица: A.7 ✅. Раздел «Migration tech-debt zero-out roadmap» → итоговая фраза «migration tech-debt = 0 by 19.04.2026». |
| `docs/runbooks/SAFE_MIGRATION_ON_DEV.md` | Раздел «Static guardrails» — упомянуть, что legacy DDL helpers **удалены** (DI-19), alembic = единственный источник. Обновить ссылки на `test_migrations.py` (теперь не существует) → `test_migrations_runtime_upgrade.py`. |
| `docs/runbooks/DEV_RESURRECTION.md` | FAQ «`db upgrade` упал на `relation X already exists`» — упомянуть, что fallback в DDL удалён, alembic должен работать; диагностика по error message в `init_databases_sync`. |
| Возможно `tg_parser/cli/init_db.py` docstring модуля | Обновить session-историю — DI-19 убрал DDL fallback. |
| Если `tests/test_alembic_vs_legacy_ddl_parity.py` удалён | Обновить `tests/_testcontainer_fixtures.py` docstring — убрать упоминание parity-теста. |

### Шаг 13: Атомарный commit + push + watch CI

```bash
git add -A
git status   # sanity-check — что именно удаляется/модифицируется

git commit -m "$(cat <<'EOF'
refactor(storage): drop legacy EMBEDDING_DDL / init_*_schema helpers (DI-19)

Closes the migration tech-debt sprint (A.5 → A.6 → A.7).  After Sprint
A.6's parity proof (tests/test_alembic_vs_legacy_ddl_parity.py)
demonstrated that alembic-built schema is identical to legacy raw DDL
schema, removing the legacy helpers is mechanical:

- 14 test files migrated off ``init_*_schema(engine)`` to a session-
  scoped ``alembic upgrade head`` fixture in tests/conftest.py.
  Per-test isolation via TRUNCATE ... CASCADE between tests.
- tests/test_f5a_topic_rag.py — 6 substring asserts on the
  EMBEDDING_DDL string rewritten as runtime information_schema
  reflection (semantically stronger).
- tests/test_migrations.py removed (its 3 init_*_schema smoke tests
  are fully covered by tests/test_migrations_runtime_upgrade.py from
  Sprint A.6: pg_tables inventory + critical indexes + pgvector ext).
- tg_parser/cli/init_db.py::init_databases_fallback removed; the
  ``if not use_alembic`` dead branch in init_databases_sync replaced
  with diagnostic error + typer.Exit(1).  A broken alembic install
  must fail loudly, not silently fall back to a parallel "second
  truth" DDL.
- tg_parser/storage/sqlalchemy/schemas/{ingestion_state,
  processing_storage,raw_storage}.py reduced to docstring stubs (or
  deleted entirely if no remaining import).  All raw DDL strings
  (EMBEDDING_DDL, EMBEDDING_INDEX_DDL, PROCESSING_STORAGE_DDL,
  INGESTION_STATE_DDL, RAW_STORAGE_DDL) and entry points
  (init_*_schema, init_embedding_index, _ensure_*) gone.
- tests/test_alembic_vs_legacy_ddl_parity.py removed (no second
  side to compare); _normalize_pg_dump + _sort_create_table_columns
  pruned from tests/_testcontainer_fixtures.py.
- CI alembic-parity job [renamed to alembic-runtime-smoke / removed].

Verification: full pytest --tb=short -q ⇒ ~1543 passed, 119 skipped
(was 1549 / 119 in A.6; delta = test_migrations.py 3 tests + parity
3 tests removed, no real regressions).  ruff format + check clean.
TEST_TESTCONTAINERS=1 runtime smoke still green for all 3 branches.

Migration tech-debt = 0 after this commit.  See FUTURE_FEATURES.md
DI-19 closing note for full roadmap retrospective.
EOF
)"

git push origin main
gh run watch
```

---

## Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| `alembic upgrade head` в conftest медленный (~5–8 s × 3 ветки) на каждом локальном `pytest` запуске | Medium | Session-scoped — один раз за весь pytest run, не за тест. Идемпотентен — на N+1 запуске занимает <1 s (alembic_version_X уже at head). Сравнить с текущим `init_*_schema()`-баззом × N тестов — будет быстрее или равно. |
| TRUNCATE CASCADE между тестами не сбрасывает identity sequences (если есть SERIAL) | Medium | Наша схема использует TEXT id (UUID-стиль) почти везде. Проверить на этапе Шага 1: `grep -rn "BIGSERIAL\|SERIAL\|GENERATED" migrations/versions/`. Если найдём SERIAL — добавить `TRUNCATE ... RESTART IDENTITY CASCADE`. |
| Тест полагается на UNIQUE constraint, который ловит дубликат после первого теста | Medium | TRUNCATE снимает строки; UNIQUE constraint на пустой таблице не срабатывает. Если flaky — конкретный тест разбирать индивидуально. |
| `Database` singleton не освобождает connection-pool между тестами после изменения conftest fixture | Low | Существующий `cleanup_job_store` autouse делает `Database.reset_instance()`. Новый `test_db` fixture делает то же самое в `finally`. Двойной reset безопасен. |
| Удаление `init_databases_fallback` ломает прод-deploy на VPS, где alembic CLI broken | Very Low | На VPS alembic запускается через `docker compose run`, образ собран с `pip install -e .` — alembic заведомо есть. Если когда-то сломается — exit code + diagnostic message покажут точно что чинить (точнее, чем silent DDL fallback который потом разойдётся со схемой и устроит invisible drift). |
| `test_f5a_topic_rag.py` reflection-тесты не покрывают всё, что substring-asserts покрывали | Low | substring asserts проверяли наличие токенов в DDL string. Reflection проверяет реальные runtime-объекты. Семантически сильнее, не слабее. Если найдём забытое — добавим reflection assertion. |
| Удаление parity-теста = потеря ценности A.6 нормализатора | Medium | Документировано как «accepted tech debt». Если позже потребуется — DI-20 восстановит как snapshot test (~30 мин работы). Альтернатива (snapshot прямо сейчас) — Шаг 8 опция (c). |
| Rollback после push — нужно ли восстанавливать legacy DDL? | Low | `git revert <commit>`. Никаких production schema changes (миграции не трогали). Test fixtures возвращаются. |

**Rollback:** `git revert <commit>` → fixtures возвращают `init_*_schema()` calls, `init_databases_fallback` восстановлен, schemas package восстановлен. Никакой production-data degradation.

---

## PR checklist

- [ ] Session-scoped `_alembic_initialized_test_db` fixture в `tests/conftest.py` поднимает все 3 ветки (idempotent через alembic).
- [ ] `test_db` function-scoped fixture делает TRUNCATE между тестами (не трогает `alembic_version_*`).
- [ ] Локальный override `test_db` в `tests/test_storage_integration.py` удалён.
- [ ] 12 «trivial» тест-файлов: `init_*_schema` import + call удалены, тесты зелёные индивидуально.
- [ ] `tests/test_f5a_topic_rag.py` — 6 substring asserts заменены на reflection-asserts через `information_schema` / `pg_constraint`. Тест зелёный.
- [ ] `tests/test_migrations.py` удалён. Перед удалением сверено, что coverage перешёл в `tests/test_migrations_runtime_upgrade.py` (tables ⊆, indexes ⊆, content_hash column).
- [ ] `tg_parser/cli/init_db.py::init_databases_fallback` удалён. `init_databases_sync` падает с диагностическим error + `typer.Exit(1)` если alembic не отработал.
- [ ] `tg_parser/storage/sqlalchemy/schemas/processing_storage.py` / `ingestion_state.py` / `raw_storage.py` — DDL strings + helpers удалены (либо файлы целиком удалены если 0 imports).
- [ ] `tg_parser/storage/sqlalchemy/schemas/__init__.py` + `tg_parser/storage/sqlalchemy/__init__.py` — reexports + `__all__` зачищены.
- [ ] Решение по `tests/test_alembic_vs_legacy_ddl_parity.py` — удалить (default) или конвертировать в snapshot. Документировано в commit message.
- [ ] CI `alembic-parity` job — обновлён или удалён в соответствии с предыдущим пунктом.
- [ ] Полный `pytest --tb=short -q` — ~1543 passed, 119 skipped (delta объяснён в коммите). Никаких новых fail'ов.
- [ ] `TEST_TESTCONTAINERS=1 pytest tests/test_migrations_runtime_upgrade.py` — 4 passed (smoke остаётся как есть из A.6).
- [ ] `ruff format` + `ruff check .` чистые.
- [ ] CI: 4–5 jobs зелёные (Test Python 3.12, Alembic Guardrails, Alembic Runtime Smoke / Parity, Docker Build, Lint Documentation).
- [ ] `docs/notes/FUTURE_FEATURES.md` DI-19 → **FIXED** с verification log; roadmap-таблица A.7 ✅; раздел «Migration tech-debt zero-out roadmap» закрыт фразой «debt = 0».
- [ ] `docs/runbooks/SAFE_MIGRATION_ON_DEV.md` обновлён (legacy DDL helpers gone, alembic = single source of truth, ссылка на `test_migrations.py` заменена на `test_migrations_runtime_upgrade.py`).
- [ ] `docs/runbooks/DEV_RESURRECTION.md` FAQ обновлён (fallback removed, диагностика через error message).
- [ ] Commit message содержит: closing tag DI-19, breaking changes summary, verification numbers, ссылку на A.6 parity proof как обоснование.

---

## После A.7 — что дальше

**Migration tech-debt = 0.** Все 5 связанных DI задач закрыты:

| DI | Sprint | Статус |
|---|---|---|
| DI-1 (target_metadata wiring) | A.2 | ✅ |
| DI-4 (CI hard-fail on drift) | A.2 | ✅ |
| DI-7 (per-DB alembic.ini) | A.5 | ✅ |
| DI-9 phase 1 (static AST guardrail) | A | ✅ |
| DI-9 phase 2 (runtime smoke + parity) | A.6 | ✅ |
| DI-9 phase 3 (repo SQL ↔ metadata) | A.3 | ✅ |
| DI-19 (drop legacy DDL) | **A.7 (эта)** | ✅ |

Следующие крупные направления (см. FUTURE_FEATURES «После A.7»):

- **F8-A Hardening** — retry/pool metrics/circuit breaker. Большое feature-окно.
- **F9 phase 2** — security hardening (rate limiting, input validation gaps).
- **F5-B** — content dedup follow-up.
- **DI-5** (operational) — backfill 4 оставшихся каналов. Не требует фокусной сессии, в любое окно.
- (опциональный, +0.5 сессии) **DI-20** — конвертировать parity-нормализатор A.6 в snapshot-тест против `tests/snapshots/alembic_<branch>.sql`. Полезно если будет ощущение, что миграции stealthy edit'ятся без code review.

Сама по себе сессия A.7 — самая «mundane» в трио (refactor + delete), но самая ценная по итогу: после неё **schema PR'ы становятся trivial-review** (одна migration, нет «забыл синхронизировать в DDL»). Это и был оригинальный смысл всего sprint'а A → A.7.
