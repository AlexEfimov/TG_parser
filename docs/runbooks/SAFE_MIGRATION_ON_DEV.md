# Runbook — Safe Migration on Dev

**Назначение:** безопасно создать и накатить новую alembic-миграцию на dev-стенд так, чтобы (а) схема в проде → миграция → схема на dev оставались консистентны и (б) не накапливался drift, который потребовал бы [Dev Resurrection](DEV_RESURRECTION.md) (взрывной rebuild).

**Когда применять:** при любой schema change — добавил поле в модель, новый индекс, новая таблица, миграция типа колонки. Особенно — если PR трогает `tg_parser/storage/sqlalchemy/_metadata.py` или `migrations/versions/**/*.py`.

**Время:** ~10–20 минут активной работы (без учёта самой работы по дизайну схемы).

**Связанные задачи:** DI-1 (`target_metadata` wiring → `alembic check` теперь работает), DI-4 (CI hard-fails на drift), DI-9 phase 1/2/3 (статические + runtime гарантии целостности миграционной цепочки, repo SQL и alembic↔legacy parity), DI-7 (per-DB `alembic.ini`).

---

## Prerequisites

| Что | Минимум |
|-----|---------|
| Локальный Postgres-стенд | поднят и `tg-parser db check --db all` зелёный (нулевой baseline) |
| `git` | working tree clean, на `main`, актуальный pull |
| `.venv` | активирован, `pip install -e .` свежий |

> ⚠️ **Перед стартом всегда** убедись, что `tg-parser db check --db ingestion && tg-parser db check --db raw && tg-parser db check --db processing` выводят `No new upgrade operations detected.` для всех трёх веток. Если уже виден drift — разбираться с ним отдельно (это либо текущий PR коллеги, либо незаписанная ручная правка), не накладывая поверх ещё одну миграцию.

---

## Шаги

### 1. Изменить SQLAlchemy-модель в `_metadata.py`

DI-1 сделал `_metadata.py` источником правды для `alembic check`. Любое schema-change начинается здесь:

- Новая таблица → добавить `Table("foo", METADATA, ...)` в нужный branch (`INGESTION_METADATA`, `RAW_METADATA` или `PROCESSING_METADATA`).
- Новая колонка → добавить `Column(...)` в существующий `Table(...)`.
- Новый индекс → добавить `Index(...)` (либо в `Table.__table_args__`, либо отдельным `Index("foo_idx", ...).table = ...`).

> ℹ️ Если меняешь только `repo`-код (запросы), но не схему — этот шаг можно пропустить. Тест `tests/test_repo_sql_references_declared_tables.py` (DI-9 phase 3) поймает использование таблицы, которой нет в `_metadata.py` / миграциях.

### 2. Сгенерировать миграцию через autogenerate

```bash
tg-parser db revision --db <branch> --autogenerate -m "<short slug>"
```

`<branch>` — `ingestion` / `raw` / `processing` (та же ветка, в которую добавил `Table()`/`Column()`/`Index()`).

`<short slug>` — `add_foo_table_to_processing`, `alter_processed_at_to_timestamptz` и т.п. (нижний регистр, snake_case, ≤40 символов — alembic обрежет).

Alembic создаст файл вида `migrations/versions/<branch>/YYYYMMDD_HHMM_<rev>_<slug>.py` с заполненными `upgrade()` / `downgrade()`.

> ℹ️ Если в выводе `INFO  [alembic.autogenerate.compare] Detected ...` строки нет — значит autogenerate ничего не нашёл (нет diff'а с БД). Это нормально, если ты ещё не накатил предыдущие миграции; иначе — что-то с `_metadata.py` не сходится.

### 3. Прочитать сгенерированную миграцию

Autogenerate **не идеален**. Что обязательно проверить:

- **Server defaults / `text(...)`** — для `gen_random_uuid()`, `now()`, `'user'::text` autogenerate иногда генерит просто `nullable=False` без `server_default`. Дописать руками.
- **`Computed(...)` колонки** (`GENERATED ALWAYS AS ... STORED`) — autogenerate не умеет распознавать, обычно показывает как обычную колонку. Добавить `Computed("...", persisted=True)` руками.
- **GIN-индексы** (`USING GIN`) — autogenerate ставит `postgresql_using=` корректно, но проверить.
- **Partial unique indexes** (`WHERE` clause) — `postgresql_where=` нужно ставить руками, autogenerate их не подхватывает.
- **Drop'ы** — autogenerate **легко** генерит `op.drop_table(...)` / `op.drop_column(...)` если думает, что чего-то нет в metadata. **Всегда** перечитывать `downgrade()` глазами; ошибочные drop'ы — самый острый класс багов на dev (потеря данных) и проде.
- **`down_revision`** — alembic ставит автоматически, проверить что указывает на текущий `head` ветки (`tg-parser db heads --db <branch>`).
- **Docstring миграции** — заменить шаблонный «add column foo» на `"""Foo table for X feature (rev: <rev>, F-XX, see PR #NNN)."""`.

### 4. Локальный smoke: upgrade → downgrade → upgrade

**Это главный шаг runbook'а.** Цель — гарантировать, что миграция round-trip (`upgrade → downgrade → upgrade`) даёт стабильную схему, без нарастания.

```bash
# Снапшот текущего head (для отката если что-то пойдёт не так)
PREV=$(tg-parser db current --db <branch> 2>&1 | tail -1)

# Upgrade на новый head
tg-parser db upgrade --db <branch>

# Downgrade на одну ревизию назад (откатывает только что накатанное)
tg-parser db downgrade --db <branch> -1

# Upgrade обратно
tg-parser db upgrade --db <branch>

# Drift-чек: должно быть "No new upgrade operations detected."
tg-parser db check --db <branch>
```

**Критерий приёмки:**
1. Все три команды (`upgrade`, `downgrade`, `upgrade`) завершились без ошибок.
2. `db check` возвращает `No new upgrade operations detected.` (зелёный).
3. Если миграция трогает данные — после round-trip данные уцелели (или сознательно lost — задокументировать).

> 💡 **Если downgrade падает** — миграция non-reversible. Это не всегда блокер (например, миграции типа «`ALTER COLUMN TYPE TIMESTAMPTZ USING ...::timestamptz`» downgrade на `VARCHAR` теоретически возможен, но lossy). Если осознанно — добавить `# downgrade is best-effort, see PR description` в `downgrade()` и `raise NotImplementedError(...)` если backwards-incompatible. Не оставлять `pass` молча.

### 5. Проверить тесты

```bash
pytest tests/test_migrations_self_contained.py \
       tests/test_metadata_matches_migrations.py \
       tests/test_repo_sql_references_declared_tables.py -v
```

Эти три теста — статические гарантии:
- `test_migrations_self_contained` (DI-9 phase 1) — каждый ALTER имеет upstream CREATE.
- `test_metadata_matches_migrations` (DI-1 follow-up) — `_metadata.py` ↔ migration `CREATE` chain.
- `test_repo_sql_references_declared_tables` (DI-9 phase 3) — repo SQL ↔ `_metadata.py`.

Для полной гарантии (runtime mirror) — опционально локально, обязательно в CI:

```bash
TEST_TESTCONTAINERS=1 pytest \
  tests/test_migrations_runtime_upgrade.py \
  tests/test_alembic_vs_legacy_ddl_parity.py
```

Эти тесты (DI-9 phase 2, Sprint A.6) поднимают свежий `pgvector/pgvector:pg17` контейнер, выполняют `alembic upgrade head` для каждой ветки, и:
- проверяют через `pg_tables` что все ожидаемые таблицы + критические индексы (partial unique'ы, FTS GIN, document_embeddings uniques) созданы;
- дампят `pg_dump --schema-only` и сравнивают с schema, которую производит legacy `init_*_schema()` — alembic должен быть identical (с точностью до документированных cosmetic-различий; см. `_normalize_pg_dump` в `tests/_testcontainer_fixtures.py`).

Требуется доступный Docker daemon; без него тесты skip-ятся тихо. В CI работа `alembic-parity` в `.github/workflows/ci.yml` делает это автоматически на `ubuntu-latest`.

Все три должны быть зелёными после миграции. Если красные — фиксить **до** PR.

Дальше — полный pytest, чтобы убедиться, что repo / pipeline тесты не сломались на новой схеме:

```bash
pytest -x  # -x = fail-fast
```

### 6. PR-checklist

Перед открытием PR убедиться, что:

- [ ] `_metadata.py` обновлён (если меняется схема).
- [ ] Миграция сгенерирована **через autogenerate** (не написана с нуля), потом просмотрена и при необходимости подправлена руками (см. §3).
- [ ] Round-trip `upgrade → downgrade → upgrade` локально прошёл (см. §4).
- [ ] `tg-parser db check --db <branch>` зелёный после round-trip.
- [ ] `pytest -x` зелёный.
- [ ] Docstring миграции описывает **что** и **зачем** (не «autogenerated» из шаблона).
- [ ] В описании PR — ссылка на эту runbook (для review reference).

CI запустит `alembic check` как hard-failing шаг (DI-4) — drift между `_metadata.py` и фактической схемой после `alembic upgrade head` заблокирует merge.

---

## FAQ

### Q: `db revision --autogenerate` падает с `Multiple head revisions are present`.

**A:** Кто-то параллельно открыл другую миграцию в той же ветке (или ты переключался между ветками git и забыл откатить миграцию). Решение:

```bash
tg-parser db heads --db <branch>          # посмотреть все heads
# Если 2+ heads — нужен merge migration:
tg-parser db merge --db <branch> -m "merge X and Y" <head_a> <head_b>
```

После merge — снова §4 (round-trip).

### Q: Когда уместен hand-written SQL вместо autogenerate?

**A:**

1. **Bootstrap legacy таблиц** (как `b8e2f7c1d9a3` в DI-8 follow-up) — `CREATE TABLE IF NOT EXISTS` для идемпотентности, чтобы миграция работала и на свежей БД, и на проде, где таблица уже создана через legacy DDL helper. Это исключение, а не правило; новые миграции почти всегда `op.create_table(...)`.
2. **Type conversion с `USING` clause** — `ALTER COLUMN ... TYPE TIMESTAMPTZ USING processed_at::timestamptz`. Autogenerate такого не умеет.
3. **GENERATED ALWAYS AS** — pgvector / FTS computed columns. См. примеры в `f5a3c0d7e8b9` (`processing` ветка).
4. **Partial unique indexes** — `CREATE UNIQUE INDEX ... WHERE ...`. Autogenerate ставит `postgresql_where=` иногда, но не всегда корректно.

Во всех случаях `_metadata.py` должен **точно отражать** результат — иначе `alembic check` сразу же сигналит drift на следующем PR.

### Q: Миграция конфликтует с веткой коллеги (multiple heads, не merge).

**A:** Самый частый сценарий: ты открыл PR с миграцией `revA → revB`, коллега смержил в main `revA → revC`. После `git pull --rebase` — два heads (`revB`, `revC`).

Решение:

1. `tg-parser db heads --db <branch>` → подтвердить два heads.
2. **Линейный rebase** (предпочтительно): в твоей миграции поменять `down_revision = "revA"` на `down_revision = "revC"`. Файл миграции переименовать если нужно (timestamp в имени файла), `down_revision` строкой внутри файла. После — `tg-parser db downgrade --db <branch> base && tg-parser db upgrade --db <branch>` чтобы переиграть с нуля.
3. **Merge migration** (если linear rebase невозможен — миграции зависимы от исходного линка): `tg-parser db merge --db <branch> -m "merge revB and revC" revB revC`.

Линейный rebase лучше, потому что merge migration оставляет «вилку» в истории, что усложняет последующие autogenerate.

### Q: `db check` показывает drift, но я ничего не менял.

**A:** Возможные причины:

1. **Кто-то ALTER'ил БД руками через `psql`** (типичный антипаттерн dev-стенда). Сделать [Dev Resurrection](DEV_RESURRECTION.md) — иначе любая последующая миграция будет накладываться на грязное состояние.
2. **`include_object` в `migrations/env.py` пропускает что-то**, что не должен. Проверить, что таблица из drift-репорта объявлена в правильной ветке `_metadata.py`.
3. **`server_default` несоответствие** — в БД default `'user'::text`, в `_metadata.py` — `text("'user'::text")`. Иногда autogenerate видит косметическую разницу (например, `now()` vs `CURRENT_TIMESTAMP`). Если разница только косметическая — задокументировать в комментарии у Column().

### Q: Я случайно накатил миграцию на VPS до того, как закоммитил её — как откатить чтобы не остался drift?

**A:**

1. Всегда `tg-parser db downgrade --db <branch> -1` на VPS.
2. Удалить файл миграции из локального git working tree.
3. Закоммитить «правильную» версию миграции (после code review).
4. На VPS — `git pull && tg-parser db upgrade --db <branch>`.

Если миграция уже была закоммичена и смержена — изменения нужно откатывать через **новую** миграцию, не через правку файлов в git history.

---

## Troubleshooting → Dev Resurrection

Если что-то пошло необратимо не так (рассинхрон между миграциями локально и на VPS, потерялся `alembic_version_*`, два разработчика накатили взаимоисключающие изменения и т.п.) — runbook становится недостаточным, переходи к [DEV_RESURRECTION.md](DEV_RESURRECTION.md).

Сигналы что пора в Dev Resurrection:

- `tg-parser db heads --db <branch>` стабильно >1 head после нескольких попыток rebase / merge.
- `tg-parser db check --db <branch>` показывает drift, который не объясним последними коммитами.
- Локальная схема не соответствует ни одной alembic revision (Frankenstein).
- `pytest` падает с `UndefinedTableError` / `UndefinedColumnError` на таблицах, которые есть в `_metadata.py`.

---

## Связанные документы

- [DEV_RESURRECTION.md](DEV_RESURRECTION.md) — взрывной rebuild стенда (когда runbook не помог).
- [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) — DI-1, DI-4, DI-7, DI-9 (контекст guardrails).
- [`tests/test_migrations_self_contained.py`](../../tests/test_migrations_self_contained.py) — DI-9 phase 1 static guardrail.
- [`tests/test_migrations_runtime_upgrade.py`](../../tests/test_migrations_runtime_upgrade.py) — DI-9 phase 2 runtime smoke (testcontainers).
- [`tests/test_alembic_vs_legacy_ddl_parity.py`](../../tests/test_alembic_vs_legacy_ddl_parity.py) — DI-9 phase 2 parity-proof for DI-19.
- [`tests/test_metadata_matches_migrations.py`](../../tests/test_metadata_matches_migrations.py) — `_metadata.py` ↔ migrations.
- [`tests/test_repo_sql_references_declared_tables.py`](../../tests/test_repo_sql_references_declared_tables.py) — repo SQL ↔ `_metadata.py`.
