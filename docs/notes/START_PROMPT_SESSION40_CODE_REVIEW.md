# Session 40: Code Review — валидация Session 39 перед RAG

**Дата:** 24 марта 2026  
**Тип:** Code review (read-only audit)  
**Цель:** Убедиться в корректности и полноте трёх рефакторингов Session 39, зафиксировать remaining debt, подготовить чистый стартовый промпт для P5 RAG.

---

## 1. Контекст: что было сделано в Session 39

Session 39 выполнил три рефакторинга по плану из `START_PROMPT_SESSION39_PRE_RAG_REFACTORING.md`:

| # | Рефакторинг | Файлов | +/- строк | Статус |
|---|-------------|--------|-----------|--------|
| R1 | Database lifecycle dedup (context managers) | 8 | ~-150 | ✅ |
| R2 | Инверсия services → api (BackgroundScheduler) | 3+shim | ~-15 net | ✅ |
| R3 | Удаление SQLite support | 20+ | ~-820 net | ✅ |
| Fix | 3 pre-existing test failures | 3 | ~+30 | ✅ |

**Итог:** 36 файлов изменено, -990 insertions / +1814 deletions (net ~-824 строки). Тесты: **517 passed, 24 skipped, 1 deselected, 0 failures**.

**Новые файлы:**
- `tg_parser/services/db_context.py` — 5 async context managers для DB lifecycle
- `tg_parser/services/background_scheduler.py` — BackgroundScheduler + built-in tasks (из `api/scheduler.py`)

---

## 2. Чеклист ревью

### 2.1 Рефакторинг #3: Удаление SQLite

**Цель проверки:** Убедиться, что SQLite полностью вычищен из runtime кода; допустимы только имена классов `SQLite*Repo` (переименование — отложенная задача #4).

| # | Проверка | Как | Ожидание |
|---|----------|-----|----------|
| 1 | Нет `aiosqlite` в deps | `grep aiosqlite requirements.txt pyproject.toml` | 0 matches |
| 2 | Нет `sqlite+aiosqlite://` в runtime коде | `grep -r 'sqlite+aiosqlite' tg_parser/` | 0 matches |
| 3 | Нет `db_type` в Settings | Читать `tg_parser/config/settings.py` | Поле удалено |
| 4 | Нет `DatabaseConfig` в коде | `grep -r DatabaseConfig tg_parser/` | 0 matches |
| 5 | Нет `AUTOINCREMENT` в DDL | `grep -r AUTOINCREMENT tg_parser/` | 0 matches |
| 6 | DDL используют `SERIAL PRIMARY KEY` | Читать `schemas/ingestion_state.py`, `raw_storage.py` | Заменено |
| 7 | `engine_factory.py` — только PostgreSQL | Читать файл | Нет `_build_sqlite_url`, нет `NullPool` | 
| 8 | `migrations/env.py` — без SQLite веток | Читать файл | Нет `if db_type == "sqlite"` |
| 9 | `health_checks.py` — без SQLite логики | Читать `check_database()` | Нет Path checks, только pg |
| 10 | CI добавлен PostgreSQL сервис | Читать `.github/workflows/ci.yml` | `services: postgres:` + env vars |
| 11 | Тестовые фикстуры используют PostgreSQL | `conftest.py`, `test_storage_integration.py` | `_test_pg_settings()` + cleanup |

**Known remnants (допустимые):**
- Имена классов `SQLite*Repo` в ~25 файлах — отложено (задача #4)
- Docstrings вида "Хранилище: processing_storage.sqlite" в repo файлах — косметика
- `tests/test_migrations.py` — весь модуль skip'd (SQLite-only Alembic tests)
- `docs/architecture.md` — ссылки на `.sqlite` в документации

### 2.2 Рефакторинг #1: Database Lifecycle

**Цель проверки:** Все сервисы используют context managers; нет `Database.from_settings()` вне `db_context.py`.

| # | Проверка | Как | Ожидание |
|---|----------|-----|----------|
| 1 | `db_context.py` имеет 5 CMs | Читать файл | `processing_repos`, `ingestion_repos`, `raw_and_processed_repos`, `ingestion_state_repo`, `ingestion_and_processing_repos` |
| 2 | `Database.from_settings` не в сервисах | `grep -r 'Database.from_settings' tg_parser/services/` | Только в `db_context.py` |
| 3 | `topicization_service.py` — нет двойного init | Читать `run_incremental_topicization_for_uncovered` | Один `async with processing_repos()` |
| 4 | `pipeline_service.py` — использует CM | Читать `_get_channel_id_from_source` | `async with ingestion_state_repo()` |
| 5 | `scheduler_service.py` — 2 функции с CM | Читать `get_scheduler_status`, `run_incremental_for_all_sources` | `async with ingestion_state_repo()` и `async with ingestion_and_processing_repos()` |
| 6 | `ingestion_service.py` — CM для repos | Читать `run_ingestion` | `async with ingestion_repos()`, telegram outside CM |
| 7 | `export_service.py` — вложенные CM | Читать `run_export` | `async with processing_repos()` + nested `async with ingestion_state_repo()` |
| 8 | `processing_service.py` — оба метода | Читать `run_processing`, `run_multi_agent_processing` | `async with raw_and_processed_repos()` |
| 9 | llm_client.close() в finally | `topicization_service.py`, `processing_service.py` | Сохранён отдельный `try/finally` для llm cleanup |

### 2.3 Рефакторинг #2: Инверсия services → api

**Цель проверки:** `BackgroundScheduler` и связанные символы живут в `services/`; `api/scheduler.py` — shim.

| # | Проверка | Как | Ожидание |
|---|----------|-----|----------|
| 1 | `services/background_scheduler.py` существует | `ls` | Файл есть |
| 2 | Содержит: `BackgroundScheduler`, `get_scheduler`, `cleanup_expired_records`, `health_check_task`, `setup_default_tasks` | Читать файл | Все 5 символов |
| 3 | `incremental_pipeline_task` в `scheduler_service.py` | Читать файл | Функция есть |
| 4 | `api/scheduler.py` — только re-exports | Читать файл | ~15 строк, `from services.background_scheduler import ...` |
| 5 | `scheduler_service.py._run_scheduler_async` импортирует из `services/` | Grep | `from tg_parser.services.background_scheduler import` |
| 6 | Остальные `api/` файлы используют shim | Grep | `api/main.py`, `api/routes/health.py`, `api/health_checks.py` → всё через shim |
| 7 | Тесты используют shim или `services/` | Grep | Работают через shim (допустимо на 1 сессию) |

### 2.4 Исправления pre-existing failures

| # | Тест | Исправление | Проверка |
|---|------|-------------|----------|
| 1 | `test_process_message_with_agent` | `@pytest.mark.integration` + `addopts = "-m 'not integration'"` | `pyproject.toml`, `tests/test_agents.py` |
| 2 | `test_full_pipeline_e2e` | `msg1.replies = Mock(replies=1)` + `"replies"` в `raw_payload` | `tests/test_e2e_pipeline.py` lines ~160, ~62-72 |
| 3 | `test_comments_ingestion_with_per_thread_cursors` | `post_100.replies = Mock(replies=2)`, `post_200.replies = Mock(replies=1)` | Тот же файл, lines ~572-610 |

### 2.5 Тестовая инфраструктура (shared PostgreSQL)

**Критический вопрос:** тесты используют общую PostgreSQL БД, данные чистятся в фикстурах.

| # | Проверка | Как | Ожидание |
|---|----------|-----|----------|
| 1 | `conftest.py::test_db` — cleanup в фикстуре | Читать `conftest.py` | ⚠️ **Возможно нет cleanup** — проверить |
| 2 | `test_storage_integration.py::test_db` — cleanup | Читать файл | DELETE FROM всех таблиц перед yield |
| 3 | `test_e2e_pipeline.py::e2e_db` — cleanup | Читать файл | DELETE FROM всех таблиц перед yield |
| 4 | `test_agents_observability.py::persistence_with_data` — cleanup | Читать файл | DELETE FROM agent tables |
| 5 | Нет test isolation issues при `pytest -x` vs full run | Запустить `pytest` 2 раза подряд | 517 passed оба раза |
| 6 | CI workflow PostgreSQL service | Читать `.github/workflows/ci.yml` | Корректные env vars: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD |

---

## 3. Архитектурный аудит: готовность к RAG

### 3.1 Dependency graph (services → storage)

Проверить, что RAG-сервис сможет использовать тот же паттерн:

```
rag_service.py
  → db_context.py (processing_repos() / new embedding_repos())
    → Database.from_settings(settings)
    → engine_factory.create_engine_from_settings(settings, "processing")
    → SQLiteProcessedDocumentRepo / EmbeddingRepo (будущий)
```

| # | Проверка | Как |
|---|----------|-----|
| 1 | `db_context.py` легко расширяется новым CM для embeddings | Читать файл |
| 2 | `engine_factory` поддерживает произвольный `db_name` | Читать `create_engine_from_settings` |
| 3 | Settings имеют все нужные PostgreSQL поля | Выше уже проверено: `db_host..db_pool_timeout` |
| 4 | pgvector не конфликтует с текущими DDL | Схемы используют `text()` для DDL → pgvector `CREATE EXTENSION` можно добавить |

### 3.2 Remaining technical debt

Зафиксировать что **НЕ** было сделано (для будущего prompt):

| # | Что | Почему | Влияние на RAG |
|---|-----|--------|----------------|
| 1 | Класс-имена `SQLite*Repo` → `*Repo` | Косметика, ~25 файлов | Нулевое (работают с PostgreSQL) |
| 2 | Docstrings "*.sqlite" в repo файлах (~13 мест) | Не критично | Нулевое |
| 3 | `test_migrations.py` — skip'd (SQLite Alembic tests) | Нужны PG migration tests | Низкое |
| 4 | `api/scheduler.py` shim — удалить через 1 сессию | 3 API файла + 2 test файла ещё используют shim | Нулевое |
| 5 | DI в сервисах (repos через параметры) | Параллельно с RAG | Среднее — RAG писать с DI сразу |
| 6 | `tests/test_migrations.py` содержит SQLite paths | Скиппается целиком | Нулевое |

---

## 4. Задания для ревьюера

1. **Прочитать** каждый файл из чеклистов 2.1–2.5, подтвердить ожидания
2. **Запустить** `pytest` дважды подряд — убедиться в стабильности
3. **Проверить** `db_context.py` на corner cases:
   - Что если `await db.init()` бросит исключение — корректен ли cleanup?
   - Что если session creation бросит — закрывается ли `db`?
4. **Оценить** export_service: вложенный `async with ingestion_state_repo()` внутри `async with processing_repos()` — это 2 одновременных `Database` инстанса. Есть ли risk pool exhaustion?
5. **Написать** `START_PROMPT_SESSION41_RAG.md` если ревью пройдено

---

## 5. Метрики для сравнения

| Метрика | До (Session 38) | После (Session 39) | Δ |
|---------|-----------------|---------------------|---|
| Tests passed | ~520 | 517 | -3 (integration deselect) |
| Tests skipped | 24 | 24 | 0 |
| Tests failed | 3 pre-existing | 0 | -3 ✅ |
| `try/finally` в services | ~15 | ~2 (llm cleanup only) | -13 |
| `Database.from_settings` call sites | 13 | 5 (all in db_context.py) | -8 |
| SQLite code paths | ~10 branches | 0 | -10 |
| Net lines | baseline | -824 | Чище |

---

## 6. Файлы для чтения (в порядке приоритета)

### Новые файлы (обязательно):
1. `tg_parser/services/db_context.py` — ядро R1
2. `tg_parser/services/background_scheduler.py` — ядро R2
3. `tg_parser/api/scheduler.py` — shim

### Изменённые (ключевые):
4. `tg_parser/config/settings.py` — удалены SQLite поля
5. `tg_parser/storage/sqlalchemy/database.py` — упрощён конструктор
6. `tg_parser/storage/engine_factory.py` — только PostgreSQL
7. `tg_parser/services/topicization_service.py` — крупнейший рефакторинг (-100 строк)
8. `tg_parser/services/processing_service.py` — CM pattern
9. `tg_parser/services/scheduler_service.py` — CM + incremental_pipeline_task
10. `tg_parser/services/export_service.py` — вложенные CM

### Тесты (выборочно):
11. `tests/conftest.py` — PostgreSQL fixtures
12. `tests/test_e2e_pipeline.py` — replies fix + cleanup
13. `tests/test_scheduler_service.py` — переписаны mock CM
14. `tests/test_storage_integration.py` — cleanup fixture

### Инфраструктура:
15. `.github/workflows/ci.yml` — PostgreSQL service
16. `pyproject.toml` — integration marker
17. `tg_parser/storage/sqlalchemy/schemas/ingestion_state.py` — SERIAL PRIMARY KEY

---

## 7. Критерии прохождения ревью

Ревью считается пройденным, если:

- [ ] Все пункты чеклистов 2.1–2.5 подтверждены
- [ ] `pytest` стабилен при повторном запуске (0 flaky)
- [ ] Нет runtime references на SQLite (кроме class names)
- [ ] `Database.from_settings` только в `db_context.py`
- [ ] Нет циклических импортов `services → api → services`
- [ ] Corner cases `db_context.py` оценены
- [ ] Remaining debt задокументирован

**После прохождения:** Подготовить `START_PROMPT_SESSION41_RAG.md` для реализации P5 RAG-интеграции.
