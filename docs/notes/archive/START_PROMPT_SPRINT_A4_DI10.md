# Sprint A.4 — DI-10 (`processed_documents.processed_at`: VARCHAR → TIMESTAMPTZ)

**Дата подготовки:** 19 апреля 2026 (по итогам Sprint A.3 closing sweep, Session 51).
**Тип сессии:** Decision (~10 мин) + Execution (~20–40 мин зависит от выбранного варианта).
**HEAD:** `6e6882b` на `origin/main` (после Sprint A.3: 6 коммитов закрывают DI-2/3/6/9p3/18; CI зелёный).
**Связанные задачи в `docs/notes/FUTURE_FEATURES.md`:** DI-10 (~line 2447). Разблокирует чище реализацию F6 (cron-планировщик) и F7 (freshness analytics).

---

## Цель сессии

Принять и реализовать решение по типу `processed_documents.processed_at` — сейчас `VARCHAR` (наследие initial migration `f40d85317f03`). После этого закрыть DI-10 и снять последний значимый блок из «миграционного» tech-debt стека.

**Не входит в сессию:** DI-7 (per-DB `alembic.ini`), DI-9 phase 2 (testcontainers smoke), DI-19 (drop legacy `EMBEDDING_DDL`/`init_*_schema`). Они независимые и крупнее.

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на 6e6882b
gh run list --branch main --limit 3              # CI на 6e6882b зелёный?

# Local стек
docker compose ps                                # tg_parser_postgres — healthy
# если нет — DB_HOST=postgres docker compose up -d postgres

# Прочитать DI-10 entry в FUTURE_FEATURES.md (~line 2447)
grep -nE "^### DI-10:" docs/notes/FUTURE_FEATURES.md
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` (lesson из Sprint A — иначе CI красный на line-length).

---

## Контекст: что мы знаем после аудита 19 апреля

Перед написанием этого prompt'а проведён мини-аудит. Состояние такое (всё проверено в коде, не из памяти):

### Storage layer

| Слой | Текущий тип / поведение |
|---|---|
| Initial migration `f40d85317f03` (line 34) | `sa.Column("processed_at", sa.String(), nullable=False)` |
| Index | `processed_documents_processed_at_idx` btree on `processed_at` (lex-sort) |
| Postgres canonical type (свежая БД) | `character varying` (без `(N)`) |
| `_metadata.py` (line 287–289) | `Column("processed_at", String(), nullable=False)` + TODO-comment про DI-10 |
| Legacy DDL `processing_storage.py:58` | `processed_at TEXT NOT NULL` (пометка DI-19, всё равно удаляется) |

### Writers (`tg_parser/storage/sqlalchemy/processed_document_repo.py`)

```python
# line 68 (single insert) + line 121 (bulk)
"processed_at": doc.processed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
```

Формат всегда **второ-precision UTC ISO-8601 с `Z` suffix** — никаких микросекунд, никаких offset'ов. Это важно: значит all rows are canonical и `::timestamptz` cast будет lossless.

### Readers

- `_row_to_model` (line 326): `processed_at=parse_iso_datetime(row.processed_at)` — возвращает **naive datetime** (см. `tg_parser/domain/json_utils.py:80`, отрезает `Z`, не добавляет `tzinfo`).
- Filter queries (lines 180/184/235/239): `processed_at >= :from_date` где `from_date` — строка (`from_date.strftime("%Y-%m-%dT%H:%M:%SZ")`). **Строковое сравнение** — работает только потому что ISO-8601 lex-sortable.

### Domain model

```python
# tg_parser/domain/models.py:125
processed_at: datetime = Field(description="...")
```

Pydantic-уровень — `datetime`. То есть конверсия string ↔ datetime инкапсулирована в repo, но writers/readers «не знают», что в БД лежит string.

### F6 digest cursor (`tg_parser/services/digest_service.py`)

- `last_digest_cursor` — `TIMESTAMP(timezone=True)` (см. `_metadata.py:193` и migration `20260418_add_digest_subscriptions.py:38`). **Уже TIMESTAMPTZ.**
- Comparison `processed_at > last_digest_cursor` — делается **в Python**, не в SQL. SQL filter использует `from_date.strftime(...)` (строка), а потом Python-сторона делает `_to_utc(d.processed_at) > _to_utc(cursor)` (line 169).
- `_to_utc` (line 451): `return dt if dt.tzinfo else dt.replace(tzinfo=UTC)` — добавляет UTC к naive datetime'у, который вернул `parse_iso_datetime`.

**Итог:** текущая схема работает, но на двух хрупких допущениях:
1. Все writers пишут **точно** `"%Y-%m-%dT%H:%M:%SZ"` (любая микросекунда / другая зона сломает lex-sort и SQL-сравнения).
2. Любые «свежие за 24 часа» / `BETWEEN now() - interval` запросы потребуют либо string round-trip в Python, либо `processed_at::timestamptz` в каждом запросе.

### Volume (для оценки migration risk)

- Local DB (только что проверено): `processed_documents` — **0 rows**. Ноль риска.
- Prod (Hetzner): см. backup, но аудит истории показывает, что писались только канонические строки (writer один, формат hardcoded). Если у тебя есть live prod backup, перед миграцией прогнать sanity check (см. Шаг 2 ниже).

---

## Решение: 3 варианта

### Вариант A — мигрировать на `TIMESTAMPTZ` (рекомендую)

**Почему:**
- Lossless конверсия (writer уже пишет UTC ISO-8601 → `::timestamptz` без потерь).
- Симметрия с `last_digest_cursor` (TIMESTAMPTZ) → больше нет implicit string-vs-tz сравнения, можно делать `WHERE processed_at > :cursor` прямо в SQL.
- Открывает SQL-арифметику дат (`now() - interval '24 hours'`) для F7 / freshness queries без round-trip в Python.
- Repo код упрощается: дроп `.strftime(...)` в writers и `parse_iso_datetime(...)` в readers (asyncpg сам конвертит).
- Index `processed_documents_processed_at_idx` остаётся валидным после ALTER (Postgres rebuilds btree автоматически).

**Цена:**
- 1 новая миграция (~25 строк).
- Правки в `processed_document_repo.py` (4 места писателей/ридеров + 4 SQL filter expressions).
- Правки в `_metadata.py` (1 строка + удалить DI-10 TODO).
- Тесты `test_storage_integration.py` — уже передают `datetime(...)`, так что compatible. Возможно `test_f6_scheduled_digests.py` потребует подкрутки (см. Шаг 5).

**Размер:** ~30–40 мин execution.

### Вариант B — оставить `VARCHAR` + задокументировать как design decision

**Почему:** zero migration risk, если есть основания опасаться prod-данных.

**Цена:**
- Update comment в `_metadata.py` — поменять «DI-10 will decide» на «intentionally VARCHAR because <reason>».
- Добавить runbook entry «как делать time-range queries» (round-trip в Python или `::timestamptz` cast).
- Закрыть DI-10 как «WONTFIX, documented».
- Тех-debt остаётся: F7 / future analytics будут писать workaround'ы.

**Размер:** ~10–15 мин (только docs).

### Вариант C — гибрид: оставить VARCHAR + добавить computed `processed_at_ts TIMESTAMPTZ`

**Почему:** zero migration risk + получаем native timestamptz column для analytics.

```sql
ALTER TABLE processed_documents
  ADD COLUMN processed_at_ts TIMESTAMPTZ
  GENERATED ALWAYS AS (processed_at::timestamptz) STORED;
CREATE INDEX processed_documents_processed_at_ts_idx ON processed_documents(processed_at_ts);
```

**Цена:**
- 2 column'а вместо 1 — confusing для будущих контрибьюторов.
- Двойной storage cost (~16 байт на строку × N rows).
- F6/F7 переключаются на `processed_at_ts`, writer не меняется. Но в `_metadata.py` обе колонки нужны.
- Migration необратима без хака (drop generated column).

**Размер:** ~25 мин. Не рекомендую — best-of-neither-world.

---

## Recommended path: Вариант A (детальный план)

### Шаг 1: Pre-flight санити-чек (если есть live prod данные)

Прогнать на prod БД (через ssh tunnel или локально на копии prod backup):

```sql
-- Все строки должны матчить canonical regex
SELECT
  count(*) FILTER (WHERE processed_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$') AS non_canonical,
  count(*) FILTER (WHERE processed_at IS NULL) AS null_count,
  count(*) AS total
FROM processed_documents;
```

Ожидание: `non_canonical = 0`, `null_count = 0`. Если есть отклонения — либо пофиксить руками (один-разовый UPDATE), либо принять решение о data normalization до ALTER.

Local (только что проверено): `total=0` — ноль риска для local upgrade/downgrade smoke.

### Шаг 2: Создать миграцию

```bash
# Используем новый CLI из Sprint A.3 (DI-3)
.venv/bin/tg-parser db revision -m "convert processed_at to timestamptz" \
  --branch processing
```

Альтернативно (manual, если revision-команда не подхватит multi-head): создать вручную `migrations/versions/processing/20260420_processed_at_to_timestamptz.py`.

**Параметры:**
- `revision: str = "<auto>"` (короткий hex, e.g. `c9d8e7f6a5b4`)
- `down_revision: str = "b8e2f7c1d9a3"` (текущий processing head — `bootstrap_topic_links_and_bundle_uniques`)
- `branch_labels = None`, `depends_on = None`

**`upgrade()`:**

```python
def upgrade() -> None:
    # Idempotent: only ALTER if column is still text/varchar.
    # (Re-running on already-migrated DB should be a no-op.)
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF (
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'processed_documents'
                  AND column_name = 'processed_at'
            ) IN ('character varying', 'text') THEN
                ALTER TABLE processed_documents
                  ALTER COLUMN processed_at TYPE TIMESTAMPTZ
                  USING processed_at::timestamptz;
            END IF;
        END
        $$;
    """))
```

Index НЕ трогаем — Postgres автоматически rebuild'ит btree при ALTER COLUMN TYPE.

**`downgrade()`:**

```python
def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE processed_documents
          ALTER COLUMN processed_at TYPE VARCHAR
          USING to_char(processed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
    """))
```

(Downgrade сохраняет canonical-format invariant.)

### Шаг 3: Обновить `_metadata.py`

```python
# tg_parser/storage/sqlalchemy/_metadata.py:285-289
Column("source_message_id", String(), nullable=False),
Column("channel_id", String(), nullable=False),
Column("processed_at", TIMESTAMP(timezone=True), nullable=False),  # DI-10 closed: native TIMESTAMPTZ
Column("text_clean", Text(), nullable=False),
```

Удалить два-строчный TODO-коммент про DI-10.

### Шаг 4: Обновить `processed_document_repo.py`

**Writers** (lines 68 и 121):

```python
"processed_at": doc.processed_at,  # raw datetime; asyncpg → TIMESTAMPTZ
```

(Дроп `.strftime("%Y-%m-%dT%H:%M:%SZ")`. Убедиться, что `doc.processed_at` всегда timezone-aware UTC; если pipeline где-то создаёт naive — поправить там, не в repo.)

**Filter queries** (lines 180/184/235/239):

```python
if from_date:
    conditions.append("processed_at >= :from_date")
    params["from_date"] = from_date  # raw datetime, не строка
```

(Дроп `.strftime(...)` для `from_date` / `to_date`.)

**Reader** (line 326):

```python
processed_at=row.processed_at,  # asyncpg → datetime aware
```

(Дроп `parse_iso_datetime(row.processed_at)`.)

**Sanity:** проверить, что `row.processed_at` действительно aware (asyncpg по умолчанию возвращает `datetime` с `tzinfo=datetime.timezone.utc`). Если pipeline где-то ожидает naive — поправить там же.

### Шаг 5: Прогнать тесты

```bash
.venv/bin/pytest tests/test_storage_integration.py -x -v
.venv/bin/pytest tests/test_processing_pipeline.py -x -v
.venv/bin/pytest tests/test_f6_scheduled_digests.py -x -v
.venv/bin/pytest tests/test_models.py tests/test_documents_routes.py -x -v
```

**Ожидаемый сюрприз:** `test_storage_integration.py` уже передаёт `datetime(2025, 12, 14, 12, 0, 0)` без `tzinfo` (line 211). Если writer теперь шлёт raw, asyncpg может либо принять naive (трактуя как UTC), либо упасть. Возможно потребуется один из:
- (a) Patch теста: `datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC)`.
- (b) Добавить в writer `if doc.processed_at.tzinfo is None: doc.processed_at = doc.processed_at.replace(tzinfo=UTC)` (defensive).

Я бы выбрал (b) — менее хрупко для legacy callers.

### Шаг 6: Smoke `upgrade → downgrade → upgrade`

По runbook'у `docs/runbooks/SAFE_MIGRATION_ON_DEV.md`:

```bash
.venv/bin/tg-parser db upgrade --branch processing head
.venv/bin/tg-parser db downgrade --branch processing -1
.venv/bin/tg-parser db upgrade --branch processing head

# Проверить тип колонки в БД
docker compose exec postgres psql -U tg_parser -d tg_parser -c "
  SELECT data_type FROM information_schema.columns
  WHERE table_name='processed_documents' AND column_name='processed_at';"
# Expected: timestamp with time zone
```

### Шаг 7: alembic check

```bash
.venv/bin/alembic -c migrations/alembic.ini -x db_name=processing check
# Expected: "No new upgrade operations detected." — drift между _metadata.py и БД отсутствует.
```

### Шаг 8: Static guardrails + lint + format

```bash
.venv/bin/pytest tests/test_alembic_no_destructive.py tests/test_repo_sql_references_declared_tables.py -x
.venv/bin/ruff format migrations/versions/processing/20260420_processed_at_to_timestamptz.py \
  tg_parser/storage/sqlalchemy/_metadata.py tg_parser/storage/sqlalchemy/processed_document_repo.py
.venv/bin/ruff check tg_parser/ tests/ migrations/
```

### Шаг 9: FUTURE_FEATURES.md → close DI-10

В DI-10 entry (~line 2447) добавить `**[FIXED 19 апреля 2026, Sprint A.4]**` блок:
- Какой вариант выбран (A / B / C).
- Migration revision (хеш).
- Что упрощено в `processed_document_repo.py`.
- Что разблокировано (F7 freshness queries в native SQL).

### Шаг 10: Commit + push

Атомарный коммит (1 шт):

```bash
git add migrations/versions/processing/20260420_*.py \
        tg_parser/storage/sqlalchemy/_metadata.py \
        tg_parser/storage/sqlalchemy/processed_document_repo.py \
        tests/test_storage_integration.py \
        docs/notes/FUTURE_FEATURES.md
git commit -m "feat(migrations): convert processed_at VARCHAR → TIMESTAMPTZ (DI-10)"
git push origin main
gh run watch
```

Если планируешь PR-флоу — два коммита: (1) migration + metadata + repo, (2) tests + docs.

---

## Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| Prod-данные содержат non-canonical строки | Low (один writer, hardcoded format) | Шаг 1 sanity-check на prod backup до запуска ALTER на prod. |
| asyncpg возвращает naive вместо aware datetime | Low (default — aware UTC) | Defensive `_to_utc()` в reader, тесты в Шаге 5 покрывают. |
| F6 digest_service сломается (cursor/processed_at сравнение) | Low | После миграции `_to_utc()` обоих становится no-op (оба уже aware) — логика та же, проще. |
| Index drop / FTS regenerate | None | `ALTER COLUMN TYPE` сохраняет btree index. GIN на `search_vector` не трогается. |
| Long-running ALTER blocks writes на prod | Low (table небольшая) | На prod выполнять в low-traffic окне. На текущем объёме (~5K rows) — миллисекунды. |

**Rollback:** `tg-parser db downgrade --branch processing -1`. Migration symmetric (см. Шаг 2 downgrade).

---

## PR checklist

- [ ] Шаг 1 sanity-check выполнен (или подтверждено, что prod ещё не задействован).
- [ ] Migration `upgrade()` идемпотентен (DO $$ guard).
- [ ] Migration `downgrade()` восстанавливает canonical-format string.
- [ ] `_metadata.py` обновлён, DI-10 TODO удалён.
- [ ] `processed_document_repo.py`: writers/readers/filters больше не делают string round-trip.
- [ ] Local smoke `upgrade → downgrade → upgrade` зелёный.
- [ ] `alembic check` (processing) — `No new upgrade operations detected.`
- [ ] `pytest tests/test_storage_integration.py tests/test_processing_pipeline.py tests/test_f6_scheduled_digests.py` зелёный.
- [ ] `pytest tests/test_alembic_no_destructive.py tests/test_repo_sql_references_declared_tables.py` зелёный.
- [ ] `ruff format` + `ruff check` чистые.
- [ ] `FUTURE_FEATURES.md` DI-10 → FIXED, описан выбранный вариант.
- [ ] CI зелёный после push.

---

## Quick decision tree (если хочешь сразу B или C)

- Если **B (оставить VARCHAR)** — пропустить Шаги 1–8, идти к Шагу 9 (просто переписать DI-10 entry: «WONTFIX, intentionally VARCHAR because…»). Вернуться к оставшимся открытым DI-7 / DI-19.
- Если **C (computed column)** — Шаг 2 переписывает migration на `ADD COLUMN ... GENERATED ALWAYS AS`, Шаги 3–4 трогают только F6/F7 callsites (не writer). Не рекомендую без сильной причины.

---

## После DI-10

Открытые tech-debt задачи в порядке убывания приоритета:

1. **DI-7** (Small, ~0.3–0.5 сессии) — Per-DB `alembic.ini` вместо runtime tempfile.
2. **DI-9 phase 2** (Medium) — runtime alembic-upgrade smoke в testcontainers (shared infra с DI-19).
3. **DI-19** (Medium, ~1 сессия) — drop legacy `EMBEDDING_DDL` / `init_*_schema()` после переписывания ~10 test fixtures на alembic.
4. **DI-5** (Trivial ops) — backfill оставшихся 4 каналов.

Альтернативный pivot — **F8-A Hardening** (~1 сессия): retry, DB pool metrics, circuit breaker. Уже не tech-debt, а фичи.
