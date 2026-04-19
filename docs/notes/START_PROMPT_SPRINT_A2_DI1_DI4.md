# Sprint A.2 — DI-1 + DI-4 (alembic `target_metadata` + hard-fail CI check)

**Дата подготовки:** 19 апреля 2026 (по итогам Sprint A, Session 50).
**Тип сессии:** Execution + lightweight review (~1–1.5 сессии, атомарно).
**HEAD:** `6107fe3` на `origin/main` (CI all green: lint, pytest **1645 passed**, alembic-guardrails, docker build).
**Связанные задачи в FUTURE_FEATURES.md:** DI-1 (~line 2238), DI-4 (~line 2298). После Sprint A.2 разблокируются: DI-2 (alembic.ini cleanup, ~line 2272), DI-3 (Safe migration runbook, ~line 2282), DI-9 phase 3 (~line 2405). DI-19 (~line 2779) — отдельной сессией.

---

## Цель сессии

Подключить `target_metadata` к `migrations/env.py` для всех трёх логических БД (ingestion / raw / processing) и поднять `alembic check` в CI с advisory до hard-failing. Это закрывает Sprint A полностью и снимает многолетний technical-debt блок.

**Требования атомарности:** делать все три ветки в одном PR. Частичный DI-1 (одна БД из трёх) запрещён — создаст fake drift на неподключённых таблицах и заблокирует DI-4.

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на 6107fe3
gh run list --branch main --limit 3              # CI на 6107fe3 зелёный?
                                                 # если красный — fix first

# Прочитать в FUTURE_FEATURES.md re-scoped DI-1 entry (~line 2238) и DI-4 entry (~line 2298):
# в DI-1 — детальный план шагов после Sprint A audit'а (route a, 19 таблиц, follow-ups DI-2/DI-3/DI-9p3).
grep -nE "^### DI-(1|2|3|4|9|10|19):" docs/notes/FUTURE_FEATURES.md
```

**Local стек:** должен быть up. Проверка: `docker compose ps` должен показать `tg_parser_postgres` healthy. Если нет — `DB_HOST=postgres docker compose up -d postgres`.

**Critical reminder (lesson из Sprint A):** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` — иначе CI красный на line-length, как в `6ea3934` и `6107fe3`. Можно один раз прогнать `.venv/bin/ruff format tg_parser/ tests/ migrations/` всем массивом перед serial-коммитами.

---

## Контекст: почему Sprint A.2 = отдельная сессия

В Sprint A (Session 50) DI-1 был re-scoped с Small (~0.3 сессии) до Medium (~1–1.5 сессии) после finding'а: **в `tg_parser/storage/` нет ни одного `DeclarativeBase` / `Mapped[...]` / `Table(...)`** — вся схема живёт как raw DDL strings в `tg_parser/storage/sqlalchemy/schemas/*.py` + `text("SELECT ...")` в repos. Поэтому `target_metadata = Base.metadata` подключать **не к чему** — нужно сначала задекларировать ~19 таблиц как `sqlalchemy.Table(...)`.

Полный re-scope finding и план route (a) — в `docs/notes/FUTURE_FEATURES.md` DI-1 entry (~line 2238 после Sprint A apdate).

---

## План шагов

### Шаг 1: Создать `tg_parser/storage/sqlalchemy/_metadata.py`

Новый модуль с тремя `MetaData()` экземплярами и `Table(...)` декларациями для всех таблиц. Точная инвентаризация (19 таблиц):

#### Ingestion (6 таблиц)

| Table | Migration source | Текущий head |
|---|---|---|
| `sources` | `89f91e768b9b` (initial) +`b2c3d4e5f6a7` (owner_id) | f6a1b2c3d4e5 |
| `comment_cursors` | `89f91e768b9b` | |
| `source_attempts` | `89f91e768b9b` | |
| `users` | `b2c3d4e5f6a7` | |
| `user_auth_mappings` | `b2c3d4e5f6a7` | |
| `digest_subscriptions` | `f6a1b2c3d4e5` | |

#### Raw (2 таблицы)

| Table | Migration | Head |
|---|---|---|
| `raw_messages` | `5c658f04eff0` | 5c658f04eff0 |
| `raw_conflicts` | `5c658f04eff0` | |

#### Processing (11 таблиц)

| Table | Migration source | Текущий head |
|---|---|---|
| `processed_documents` | `f40d85317f03` + `d4e5f6a7b8c9` (search_vector) + `f5a3c0d7e8b9` (content_hash) | b8e2f7c1d9a3 |
| `processing_failures` | `f40d85317f03` | |
| `topic_cards` | `f40d85317f03` + `e5f6a7b8c9d0` (search_vector) | |
| `topic_bundles` | `f40d85317f03` + `b8e2f7c1d9a3` (partial unique indexes) | |
| `api_jobs` | `f40d85317f03` | |
| `agent_states` | `f40d85317f03` | |
| `task_history` | `f40d85317f03` | |
| `agent_stats` | `f40d85317f03` | |
| `handoff_history` | `f40d85317f03` | |
| `document_embeddings` | `a1b2c3d4e5f6` (defensive bootstrap, см. `4b48214`) + `c3d4e5f6a7b8` (channel_ids) | |
| `topic_links` | `b8e2f7c1d9a3` (DI-8 audit, см. `31fb9de`) | |

**Источник истины для деклараций:** не файл `processing_storage.py` (legacy, deprecated), а `migrations/versions/{ingestion,raw,processing}/*.py` — каждая `op.create_table(...)` + последующие `op.add_column` / `op.create_index` дают полный набор колонок и индексов.

**Особые случаи (требуют внимания):**

- **`MetaData()` БЕЗ `naming_convention=...`** — существующие миграции не используют convention; добавление вызовет fake drift на каждом индексе/constraint при первом `alembic check`. Если очень хочется — отдельной задачей после DI-1 + миграция-renamer.
- **`document_embeddings`** — содержит `vector(1536)` колонку (pgvector). Используй `from pgvector.sqlalchemy import Vector`. **Уже в зависимостях**: `pgvector>=0.3.0` в `requirements.txt:25` и `pyproject.toml:22`.
- **`processed_documents.search_vector`** + **`topic_cards.search_vector`** — это `tsvector GENERATED ALWAYS AS (...) STORED`. SQLAlchemy не имеет нативной поддержки computed columns; объяви как `Computed(...)` (`from sqlalchemy import Computed`). Документация: `Computed("setweight(...) || setweight(...)", persisted=True)`.
- **`channel_ids` (document_embeddings)** — `ARRAY(Text)` с `server_default="{}"`.
- **`processed_documents.processed_at`** — оставить `String()` (DI-10 решит судьбу VARCHAR vs TIMESTAMPTZ отдельно). НЕ менять тип в `_metadata.py` пока DI-10 OPEN — иначе drift.
- **Partial unique indexes на `topic_bundles`** — `Index("topic_bundles_current_unique_idx", "topic_id", unique=True, postgresql_where=text("time_from IS NULL AND time_to IS NULL"))` и `Index("topic_bundles_snapshot_unique_idx", "topic_id", "time_from", "time_to", unique=True, postgresql_where=text("time_from IS NOT NULL AND time_to IS NOT NULL"))`. ВАЖНО: рядом с unique partial-индексами существует **non-unique** `topic_bundles_snapshot_idx ON (topic_id, time_from, time_to)` из initial-миграции `f40d85317f03` — это intentional duplicate (старый широкий индекс), оба надо объявить.
- **`users.id` UUID + `gen_random_uuid()`** — `Column(UUID(as_uuid=True), server_default=text("gen_random_uuid()"))`.
- **CheckConstraints** — обязательно перенести (`sources.status`, `topic_cards.type`, `api_jobs.job_type/status`, `handoff_history.status`, `digest_subscriptions.channel_ids_nonempty`).
- **Defensive bootstrap pattern в миграциях** (`a1b2c3d4e5f6` → `document_embeddings`, `b8e2f7c1d9a3` → `topic_links`): миграции содержат `if not inspector.has_table(...): CREATE TABLE`. В `_metadata.py` объявляй таблицу нормально — `alembic check` сравнивает финальную schema, не код миграций.

**Структура модуля:**

```python
"""SQLAlchemy Table() declarations for alembic target_metadata (DI-1).

Three independent MetaData() instances — one per logical database.
Used by migrations/env.py to feed alembic check / autogenerate.
"""

from sqlalchemy import (
    ARRAY, Boolean, CheckConstraint, Column, Computed, Float, ForeignKey,
    Index, Integer, MetaData, PrimaryKeyConstraint, Table, Text,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from pgvector.sqlalchemy import Vector

INGESTION_METADATA = MetaData()
RAW_METADATA = MetaData()
PROCESSING_METADATA = MetaData()

# ---- Ingestion ----
sources = Table("sources", INGESTION_METADATA, ...)
# ... etc
```

### Шаг 2: Wire `target_metadata` в `migrations/env.py`

Текущее (на `6107fe3`, lines 99–106 и 119–124):

```python
context.configure(
    url=url,
    target_metadata=None,  # <-- DI-1 здесь
    ...
)
```

Заменить на:

```python
from tg_parser.storage.sqlalchemy._metadata import (
    INGESTION_METADATA, RAW_METADATA, PROCESSING_METADATA,
)

_METADATA_BY_DB = {
    "ingestion": INGESTION_METADATA,
    "raw": RAW_METADATA,
    "processing": PROCESSING_METADATA,
}

# в run_migrations_offline() и do_run_migrations():
context.configure(
    url=url,
    target_metadata=_METADATA_BY_DB[db_name],
    ...
)
```

### Шаг 3: Smoke check на dev compose

```bash
DB_HOST=postgres docker compose run --rm \
  -v "$(pwd)/migrations:/app/migrations" \
  -v "$(pwd)/tg_parser:/app/tg_parser" \
  tg_parser db check --db ingestion
# Ожидание: "No new upgrade operations detected." (нулевой diff)

# Аналогично для raw и processing.
```

Если diff не нулевой — это и есть real drift между migration chain и `_metadata.py` декларацией. **Каждый diff item — реальная задача:**
- Лишняя колонка в декларации, которой нет в миграции → удалить из `_metadata.py` или добавить миграцию.
- Лишний индекс / constraint в миграции, которого нет в декларации → добавить в `_metadata.py`.
- Несовпадение типов / nullability / server_default → fix в декларации (миграция = ground truth).

**Идеальный итог:** все 3 ветки возвращают `No new upgrade operations detected.` без правок миграций.

### Шаг 4: Negative regression test

Локально добавить искусственный `Column("test_drift_column", Text)` в одну из таблиц `_metadata.py` (НЕ коммитить). Прогнать `tg-parser db check --db <branch>` — должен показать diff с этой колонкой. Убрать колонку, проверить что diff снова нулевой.

Это подтверждает что `target_metadata` работает реально, а не возвращает "no diff" по какой-то технической причине (например, отключённый сравниватель).

### Шаг 4.5: Удалить устаревший NOTE из CLI docstring

В `tg_parser/cli/db_cmd.py:296-297` функция `check()` имеет docstring:

```python
"""
Alembic check — обнаружить drift между моделями SQLAlchemy и миграциями.

NOTE: пока в `migrations/env.py` target_metadata=None, alembic check
структурно работает (возвращает no-op). Полное включение — follow-up DI-1.
"""
```

После DI-1 удалить блок `NOTE: ... follow-up DI-1.` (две строки), оставить только первую строку docstring + примеры.

### Шаг 5: DI-4 — flip CI step с advisory на hard-failing

В `.github/workflows/ci.yml`, job `alembic-guardrail` (строка 123) → шаг `Alembic check` на строках **205–212**:

```yaml
- name: Alembic check (model vs migration drift; advisory)
  # NOTE: target_metadata=None in migrations/env.py — drift check is no-op until DI-1 lands.
  # Kept as informational step; flip to failing once target_metadata is wired.
  run: |
    for db in ingestion raw processing; do
      echo "--- check $db ---"
      tg-parser db check --db "$db" || echo "(advisory only — DI-1 follow-up)"
    done
```

Заменить на:

```yaml
- name: Alembic check (model vs migration drift)
  run: |
    set -e
    for db in ingestion raw processing; do
      echo "--- check $db ---"
      tg-parser db check --db "$db"
    done
```

### Шаг 6: Опциональный `tests/test_metadata_matches_migrations.py`

Cross-check на уровне unit-теста: каждая `Table` в `_metadata.py` должна иметь соответствующую `op.create_table` в alembic-цепочке (и наоборот). Это страхует от ситуации когда `alembic check` flaky или silently skipped.

Скетч (можно расширить `tests/test_migrations_self_contained.py` из DI-9 phase 1 — там уже есть AST-парсер `_extract_targets`):

```python
# Импорт сетов creates из DI-9 анализатора + сравнение с {tbl.name for tbl in METADATA.tables.values()}.
def test_metadata_tables_match_migration_creates():
    for branch, metadata in [("ingestion", INGESTION_METADATA), ("raw", RAW_METADATA), ("processing", PROCESSING_METADATA)]:
        from tests.test_migrations_self_contained import _parse_revisions
        migrated = set()
        for r in _parse_revisions(branch):
            migrated |= r["creates"]
        declared = {t.name for t in metadata.tables.values()}
        assert declared == migrated, (
            f"{branch}: metadata vs migrations mismatch.\n"
            f"  declared but not migrated: {declared - migrated}\n"
            f"  migrated but not declared: {migrated - declared}"
        )
```

### Шаг 7: Коммиты (предлагаемая разбивка)

Опция A — три коммита по веткам (cleaner review):
1. `feat(metadata): SQLAlchemy Table() declarations for ingestion branch (DI-1)`
2. `feat(metadata): + raw branch declarations (DI-1)`
3. `feat(metadata): + processing branch declarations (DI-1) — wires target_metadata`

Опция B — один большой коммит (faster):
- `feat(metadata): wire target_metadata to migrations/env.py for all 3 DBs (DI-1)`

Затем:
- `ci(alembic): hard-fail on drift detection (DI-4)`
- (опционально) `test(metadata): cross-check Table() declarations match migration CREATE chain`

Рекомендация: **опция B + DI-4 + test = 3 коммита**. Trade-off: review больше, но сессия короче и atomicity лучше выражена.

### Шаг 8: Push + verify CI

```bash
.venv/bin/ruff format tg_parser/ tests/ migrations/  # обязательно перед commit
.venv/bin/ruff check tg_parser/ tests/ migrations/

git push origin main
sleep 30 && gh run list --branch main --limit 2
gh run view <run_id> --json jobs --jq '.jobs[] | {name, conclusion}'
# Особенно смотреть на Alembic Guardrails — теперь должна fail-fast на любом drift.
```

### Шаг 9: Update FUTURE_FEATURES.md

- DI-1 → **FIXED**, дата, ссылка на коммит, кратко "all 3 branches wired, alembic check returns 0 diff, 19 Tables declared".
- DI-4 → **FIXED**, дата, ссылка на коммит.
- DI-2 → отметить **разблокирован** (можно делать или оставить открытым — trivial).
- DI-3 → отметить **разблокирован** (autogenerate теперь работает).
- DI-9 phase 3 → стала тривиальной: можно закрыть в этой же сессии тестом `tests/test_repo_sql_refs_metadata.py` (grep таблиц из repos `text("... FROM <tbl> ...")`, проверка `⊆ {tbl.name for tbl in METADATA.tables.values()}`); либо оставить OPEN с заметкой "trivial after DI-1, do later".

Коммит: `docs(future-features): close DI-1 + DI-4 (Sprint A.2 done)`.

---

## Acceptance criteria

- [ ] `tg_parser/storage/sqlalchemy/_metadata.py` существует, объявляет 19 таблиц через 3 `MetaData()` (без `naming_convention`).
- [ ] `migrations/env.py` импортирует `_METADATA_BY_DB`, передаёт корректный `target_metadata` в обе `context.configure(...)` ветки.
- [ ] `tg_parser/cli/db_cmd.py:296-297` — устаревший `NOTE: ... follow-up DI-1` удалён.
- [ ] `tg-parser db check --db ingestion` / `raw` / `processing` возвращает `No new upgrade operations detected.` локально.
- [ ] CI step `Alembic check` в `.github/workflows/ci.yml:205-212` снять `|| echo`, hard-fail включён, NOTE на line 206 убран.
- [ ] Negative regression проведён вручную (искусственный column → diff виден → убран → 0 diff).
- [ ] CI зелёный на push'е (особенно job `alembic-guardrail`).
- [ ] FUTURE_FEATURES.md DI-1 + DI-4 → FIXED, DI-2 / DI-3 / DI-9 phase 3 помечены как «разблокированы».
- [ ] (опц.) `tests/test_metadata_matches_migrations.py` или расширенный `test_migrations_self_contained.py` ловит mismatch.

---

## Гипотетические риски / fallback

| Риск | Симптом | Mitigation |
|---|---|---|
| `pgvector` SQLAlchemy import не работает | `from pgvector.sqlalchemy import Vector` падает | `pip show pgvector` → если нет, `.venv/bin/pip install pgvector` (он уже в зависимостях, но проверить) |
| `Computed()` для `tsvector` даёт неправильный SQL | `alembic check` показывает drift на search_vector | Можно использовать `info={"skip_autogenerate": True}` на колонке + явный комментарий, или объявить как обычную `Column(TSVECTOR)` без Computed (drift будет, но контролируемо) |
| `topic_bundles_current_unique_idx` не reproducible через `Index(..., postgresql_where=...)` | drift на индекс | Документировать в коде, использовать `info` для skip; alternative — explicit `op.create_index` в миграции с raw SQL и `MetaData(...)` без index'а |
| `gen_random_uuid()` server_default дрейфует | timestamp + UUID типы | Может потребоваться `server_default=text("gen_random_uuid()")` явно |
| Diff большой и реальный | 10+ items в `tg-parser db check` | Разбить на коммиты по веткам (опция A); фиксить incremental |

Если diff неустраним за разумное время — **rollback Шаг 5 (DI-4)**: оставить `|| true` в CI, закоммитить _metadata.py как partial-DI-1 milestone, открыть отдельную задачу на каждое расхождение.

---

## Что НЕ делаем в Sprint A.2

- ❌ DI-9 phase 2 (runtime alembic upgrade smoke под `migrations/env.py`) — отложено к DI-19.
- ❌ DI-19 (полное удаление `EMBEDDING_DDL` / `init_*_schema`) — отдельная сессия (требует замены тестовых fixtures на alembic).
- ❌ DI-10 (`processed_at` VARCHAR vs TIMESTAMPTZ) — отдельная задача, требует обсуждения writer'ов; `_metadata.py` повторяет текущий VARCHAR.
- ❌ Менять existing миграции — миграции = ground truth, `_metadata.py` подстраивается под них.
- ❌ Добавлять `MetaData(naming_convention=...)` — fake drift на каждом индексе/constraint, нужна отдельная rename-миграция.
- ❌ DI-2 (alembic.ini cleanup) — разблокируется этой сессией, но делать отдельно (хочется минимальный diff в Sprint A.2).

---

## Референсы

- **Sprint A итоги:** коммиты `31fb9de` + `1369c02` + `be42e38` + `dced2ea` + `6107fe3` (push 19.04.2026).
- **DI-9 phase 1 анализатор:** `tests/test_migrations_self_contained.py` — переиспользовать `_parse_revisions(branch)` и `_extract_targets(tree)` для cross-check теста.
- **Список миграций:**
  - ingestion: `89f91e768b9b` → `b2c3d4e5f6a7` → `f6a1b2c3d4e5` (head)
  - raw: `5c658f04eff0` (head)
  - processing: `f40d85317f03` → `a1b2c3d4e5f6` → `c3d4e5f6a7b8` → `d4e5f6a7b8c9` → `e5f6a7b8c9d0` → `f5a3c0d7e8b9` → `b8e2f7c1d9a3` (head)
- **CI workflow:** `.github/workflows/ci.yml`, job `alembic-guardrail` (line **123**, display name `Alembic Guardrails`); advisory шаг `Alembic check` — lines **205–212**, NOTE про DI-1 — line **206-207**.
- **CLI команда `db check`:** `tg_parser/cli/db_cmd.py:285-322` — реализация существует, делегирует в `run_alembic_command(["check"], ...)`. Docstring (`db_cmd.py:296-297`) содержит устаревшую заметку о target_metadata=None — удалить в Sprint A.2.
- **pgvector** уже в `requirements.txt:25` и `pyproject.toml:22` (`pgvector>=0.3.0`); импорт `from pgvector.sqlalchemy import Vector` должен работать out-of-the-box.

---

**Подготовлено:** Sprint A (Session 50) — 19.04.2026.
**Следующий шаг:** Открыть новое окно → запустить промпт ниже.
