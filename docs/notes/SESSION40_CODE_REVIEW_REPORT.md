# Session 40: Code Review Report

**Дата:** 25 марта 2026  
**Тип:** Code review (read-only audit)  
**Проверяемая сессия:** Session 39 (Pre-RAG Refactoring)  
**Вердикт:** **PASSED** — ревью пройдено, готовы к P5 RAG

---

## 1. Результаты тестов

```
Run 1: 517 passed, 24 skipped, 1 deselected, 4 warnings — 63.02s
Run 2: 517 passed, 24 skipped, 1 deselected, 4 warnings — 59.81s
```

Стабильно, 0 flaky, 0 failures. Warnings — корутины AsyncMock в нескольких тестах (не регрессия).

---

## 2. Чеклист 2.1: Удаление SQLite

| # | Проверка | Результат |
|---|----------|-----------|
| 1 | Нет `aiosqlite` в deps | ✅ 0 matches в `requirements.txt` и `pyproject.toml` |
| 2 | Нет `sqlite+aiosqlite://` в runtime | ✅ 0 matches в `tg_parser/` |
| 3 | Нет `db_type` в Settings | ✅ Удалено. Settings содержит только PostgreSQL поля: `db_host`, `db_port`, `db_name`, `db_user`, `db_password`, `db_pool_*` |
| 4 | Нет `DatabaseConfig` в коде | ✅ 0 matches в `tg_parser/` |
| 5 | Нет `AUTOINCREMENT` в DDL | ✅ 0 matches в `tg_parser/` |
| 6 | DDL используют `SERIAL PRIMARY KEY` | ✅ `source_attempts.id` и `raw_conflicts.id` используют `SERIAL PRIMARY KEY` |
| 7 | `engine_factory.py` — только PostgreSQL | ✅ Нет `_build_sqlite_url`, нет `NullPool`. Только `_build_postgres_url`, `QueuePool` |
| 8 | `migrations/env.py` — без SQLite веток | ✅ Нет `if db_type`. Единственный путь — `_build_postgres_url(settings)` |
| 9 | `health_checks.py` — без SQLite логики | ✅ Нет `Path` checks, `type: "postgresql"`, только `create_engine_from_settings` + `SELECT 1` + `pg_tables` |
| 10 | CI PostgreSQL сервис | ✅ `services: postgres:` (postgres:16-alpine), env: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| 11 | Тестовые фикстуры PostgreSQL | ✅ `_test_pg_settings()` в `conftest.py`, `e2e_db` с full cleanup в `test_e2e_pipeline.py` |

### Допустимые remnants (confirmed):

- Имена классов `SQLite*Repo` — 8 классов в `__init__.py`, используются в `db_context.py`, `_wiring.py`, type hints. Работают с PostgreSQL. Переименование — задача #4.
- Docstrings — косметика, не влияет на runtime.
- `test_migrations.py` — skip'd полностью.

---

## 3. Чеклист 2.2: Database Lifecycle

| # | Проверка | Результат |
|---|----------|-----------|
| 1 | `db_context.py` имеет 5 CMs | ✅ `processing_repos`, `ingestion_repos`, `raw_and_processed_repos`, `ingestion_state_repo`, `ingestion_and_processing_repos` |
| 2 | `Database.from_settings` не в сервисах (кроме `db_context.py`) | ✅ 5 вызовов — все в `db_context.py` (строки 32, 50, 69, 89, 102). 1 в docstring (строка 4) |
| 3 | `topicization_service.py` — нет двойного init | ✅ Все функции используют `async with processing_repos() as (...)`. `llm_client.close()` в отдельном `try/finally` |
| 4 | `pipeline_service.py` — использует CM | ✅ `_get_channel_id_from_source` — `async with ingestion_state_repo()` |
| 5 | `scheduler_service.py` — 2 функции с CM | ✅ `get_scheduler_status` → `async with ingestion_state_repo()`, `run_incremental_for_all_sources` → `async with ingestion_and_processing_repos()` |
| 6 | `ingestion_service.py` — CM для repos | ✅ `async with ingestion_repos()`, telegram connect/disconnect вне CM в отдельном `try/finally` |
| 7 | `export_service.py` — вложенные CM | ✅ `async with processing_repos()` + nested `async with ingestion_state_repo()` |
| 8 | `processing_service.py` — оба метода | ✅ `run_processing` → `async with raw_and_processed_repos()`, `run_multi_agent_processing` → `async with raw_and_processed_repos()` |
| 9 | `llm_client.close()` в finally | ✅ `topicization_service.py` (lines 112-113, 236-238), `processing_service.py` (lines 150-152) |

---

## 4. Чеклист 2.3: Инверсия services → api

| # | Проверка | Результат |
|---|----------|-----------|
| 1 | `services/background_scheduler.py` существует | ✅ 320 строк |
| 2 | Содержит 5 символов | ✅ `BackgroundScheduler` (L20), `get_scheduler` (L170), `cleanup_expired_records` (L183), `health_check_task` (L249), `setup_default_tasks` (L270) |
| 3 | `incremental_pipeline_task` в `scheduler_service.py` | ✅ L299 |
| 4 | `api/scheduler.py` — shim | ✅ 17 строк, re-exports из `services.background_scheduler` + `services.scheduler_service` |
| 5 | `scheduler_service._run_scheduler_async` импортирует из `services/` | ✅ L252: `from tg_parser.services.background_scheduler import` |
| 6 | Остальные `api/` файлы используют shim | ✅ `api/main.py` L140, `api/routes/health.py` L14, `api/health_checks.py` L248 — все через `tg_parser.api.scheduler` (shim) |
| 7 | Тесты используют shim | ✅ `test_phase3d_advanced.py` и `test_scheduler_service.py` — через shim (допустимо) |

### Циклические импорты:

Проверено: `services/background_scheduler.py` импортирует `from tg_parser.api.metrics` (top-level) и `from tg_parser.api.health_checks` (lazy, inside function). Это **не циклическая зависимость** `services → api → services`, т.к.:
- `api.metrics` — утилита без обратных импортов из `services/`
- `api.health_checks.check_all_components` — lazy import, не создаёт cycle при module load

**Нет циклических импортов services → api → services.**

---

## 5. Чеклист 2.4: Исправления pre-existing failures

| # | Тест | Результат |
|---|------|-----------|
| 1 | `test_process_message_with_agent` | ✅ Маркер `@pytest.mark.integration` (L356 test_agents.py) + `addopts = "-m 'not integration'"` в pyproject.toml (L50) |
| 2 | `test_full_pipeline_e2e` | ✅ `msg1.replies = Mock(replies=1)` (L181), `raw_payload["replies"]` корректно сериализуется через `mock_convert_message` (L63-64) |
| 3 | `test_comments_ingestion_with_per_thread_cursors` | ✅ `post_100.replies = Mock(replies=2)` (L577), `post_200.replies = Mock(replies=1)` (L584) |

---

## 6. Чеклист 2.5: Тестовая инфраструктура

| # | Проверка | Результат |
|---|----------|-----------|
| 1 | `conftest.py::test_db` — cleanup | ⚠️ **Нет cleanup.** Фикстура создаёт `Database.from_settings()` + `init()` + `yield` + `close()`. Нет `DELETE FROM`. Однако: `conftest.py::test_db` используется только тестами, которые либо (a) не пишут в БД, либо (b) имеют собственные фикстуры с cleanup. **Не блокер**, но рекомендуется добавить cleanup. |
| 2 | `test_storage_integration.py::test_db` | ✅ Полная очистка: DELETE FROM по всем таблицам (3 engines, 11 таблиц) перед yield |
| 3 | `test_e2e_pipeline.py::e2e_db` | ✅ Полная очистка: 11 таблиц перед yield |
| 4 | `test_agents_observability.py::persistence_with_data` | ✅ Очистка 4 agent таблиц (processing engine) перед yield |
| 5 | Нет flaky при повторном запуске | ✅ 2 прогона — идентичный результат: 517/24/1 |
| 6 | CI workflow PostgreSQL | ✅ Корректные env vars, `postgres:16-alpine`, health checks |

---

## 7. Corner Cases: db_context.py

### 7.1. Если `await db.init()` бросит исключение

```python
db = Database.from_settings(settings)  # OK — sync, just sets attributes
await db.init()                        # May throw (e.g. connection refused)
session = db.processing_storage_session()
try:
    yield (...)
finally:
    await session.close()
    await db.close()
```

**Проблема:** Если `db.init()` бросит исключение, `finally` блок **НЕ выполнится** — он защищает только блок `try/yield`. Engines, частично созданные в `init()`, не будут disposed.

**Severity:** Low. При connection refused engines не создаются (exception в `create_async_engine` или первом connect). При частичном создании (1-й engine OK, 2-й fail) — 1 engine будет leak'd. При одноразовом запуске — GC собирает. При частых retry — potential pool leak.

**Рекомендация для Session 41:** Обернуть `init()` в try/except с `await db.close()` в except:

```python
db = Database.from_settings(settings)
try:
    await db.init()
except BaseException:
    await db.close()
    raise
```

### 7.2. Если session creation бросит — закрывается ли db?

`db.processing_storage_session()` — sync метод, вызывает `sessionmaker()`. Если `_sessionmaker` is None (не инициализирован), бросает `RuntimeError`. Аналогично п.7.1 — `db.close()` не вызовется.

**Severity:** Minimal. Вызов всегда идёт сразу после `init()`, sessionmaker будет инициализирован. RuntimeError здесь — programming error, не runtime condition.

---

## 8. Pool Exhaustion: export_service nested CMs

`export_service.run_export()` открывает 2 `Database` инстанса одновременно:

```python
async with processing_repos() as (...):          # Database #1: 3 engines × pool_size=5 = 15 connections
    async with ingestion_state_repo() as (...):   # Database #2: 3 engines × pool_size=5 = 15 connections
```

**Анализ:**
- `processing_repos()` создаёт `Database` с **3 engines** (ingestion, raw, processing) — каждый с `pool_size=5`, `max_overflow=10`. Итого до 45 connections.
- `ingestion_state_repo()` создаёт **ещё один** `Database` с 3 engines — ещё до 45 connections.
- В реальности: используются только 2 session из первого DB и 1 из второго, значит фактически 3 connections checked out.
- Но **90 connections allocated** (pool idle) — при defaults (`pool_size=5`, 6 engines).

**Severity:** Medium. При `pool_size=5` и одном worker — ОК. При параллельных вызовах (scheduler + API) — каждый вызов аллоцирует 6 engines. PostgreSQL default `max_connections=100`. С 2-3 параллельными export вызовами — можно упереться в лимит.

**Рекомендация:** В будущем (Session 41+) рассмотреть:
1. Shared engine pool (один `Database` на запрос через DI)
2. Или `ingestion_state_repo()` вызывать через session из существующего `Database` — не создавать второй

---

## 9. Архитектурный аудит: готовность к RAG

| # | Проверка | Результат |
|---|----------|-----------|
| 1 | `db_context.py` расширяется | ✅ Добавить `embedding_repos()` CM — ~15 строк по шаблону. Паттерн стабилен. |
| 2 | `engine_factory` поддерживает произвольный `db_name` | ⚠️ Сигнатура `create_engine_from_settings` ограничена `Literal["ingestion", "raw", "processing"]`. Для RAG нужно либо (a) добавить `"embedding"` в Literal, либо (b) использовать тот же `"processing"` engine (предпочтительно — embedding таблицы в той же БД). |
| 3 | Settings имеют все PostgreSQL поля | ✅ `db_host`, `db_port`, `db_name`, `db_user`, `db_password`, `db_pool_*` |
| 4 | pgvector не конфликтует с DDL | ✅ DDL используют `text()`. `CREATE EXTENSION IF NOT EXISTS vector` можно добавить в processing DDL. |

---

## 10. Remaining Technical Debt (confirmed)

| # | Что | Severity | Влияние на RAG |
|---|-----|----------|----------------|
| 1 | Имена `SQLite*Repo` (~8 классов, ~25 файлов) | Low (cosmetic) | Нулевое |
| 2 | Docstrings "*.sqlite" в repo файлах | Low (cosmetic) | Нулевое |
| 3 | `test_migrations.py` — skip'd | Low | Нулевое |
| 4 | `api/scheduler.py` shim | Low | Нулевое |
| 5 | DI в сервисах | Medium | RAG-сервис писать с DI сразу |
| 6 | `conftest.py::test_db` без cleanup | Low | Добавить при расширении тестов |
| 7 | Nested CMs → duplicate Database instances | Medium | Рассмотреть shared engine pool |
| 8 | `db_context.py` — no cleanup on `init()` failure | Low | Исправить при добавлении embedding CM |
| 9 | `background_scheduler.py` → `api.metrics` top-level import | Low | Не циклическая, но не идеальная layering |

---

## 11. Вердикт

### Все критерии пройдены:

- [x] Все пункты чеклистов 2.1–2.5 подтверждены
- [x] `pytest` стабилен при повторном запуске (0 flaky)
- [x] Нет runtime references на SQLite (кроме class names)
- [x] `Database.from_settings` только в `db_context.py`
- [x] Нет циклических импортов `services → api → services`
- [x] Corner cases `db_context.py` оценены (severity: low)
- [x] Remaining debt задокументирован

**Ревью пройдено. Готовы к P5 RAG-интеграции.**
