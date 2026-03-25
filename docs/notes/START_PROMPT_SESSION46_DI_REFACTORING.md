# Session 46: Dependency Injection в service layer (Tech Debt — Final)

**Дата:** [дата запуска]  
**Тип сессии:** Tech Debt — Dependency Injection Refactoring  
**Предыдущая сессия:** Session 45 (Tech Debt C — Test Coverage & Repo Housekeeping)  
**План:** `docs/notes/TECH_DEBT_CLOSURE_PLAN.md` → "Вне скоупа: DI в сервисах"  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md`  
**Code Review:** `docs/notes/SESSION40_CODE_REVIEW_REPORT.md` (§7, §8, §10)

---

## Цель сессии

Рефакторинг service layer для поддержки dependency injection: сервисные функции получают репозитории через параметры (опционально), `db_context.py` остаётся как default wiring. Исправляются проблема nested Database instances в `export_service`, отсутствие error handling при `init()` failure в CMs, и мёртвые импорты `settings`.

---

## Контекст проекта

### Текущее состояние (после Session 45)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17.9 (Docker: `pgvector/pgvector:pg17`), pgvector 0.8.2
- **Тесты:** 567 passed, 16 skipped, 0 failures
- **Последний коммит:** `fa9121c` (Session 43), Sessions 44-45 не закоммичены
- **Файловая структура (после Session 45):** benchmarks в `benchmarks/`, архивные docs в `docs/archive/` и `docs/notes/archive/`

### Что сделано в Session 45 (C)

- C1: `test_migrations.py` — 3 PostgreSQL DDL smoke теста вместо 8 скипнутых SQLite тестов
- C2: `test_rag_routes.py` — 5 HTTP тестов для RAG endpoints
- C3: `test_contract_validation.py` (8 тестов) + `test_json_utils.py` (13 тестов)
- C4: 34 файла перемещены из корня в `benchmarks/`, `docs/archive/`, `docs/notes/archive/`
- C5: `docs/USER_GUIDE.md` обновлён: `postgres:16-alpine` → `pgvector/pgvector:pg17`

---

## Текущая архитектура (что менять)

### `db_context.py` — централизованное wiring

Файл содержит **6 async context managers**, каждый из которых:
1. Создаёт `Database.from_settings(settings)` (жёстко привязан к глобальному `settings`)
2. Вызывает `await db.init()` → создаёт **3 engine** (ingestion, raw, processing) с connection pool
3. Открывает 1-2 session → создаёт конкретные `SA*Repo` → `yield`
4. В `finally` закрывает sessions и engines

**Context managers:**

| CM | Yields | Используется в |
|----|--------|----------------|
| `processing_repos()` | `SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database` | `topicization_service` (4×), `export_service` |
| `ingestion_repos()` | `SAIngestionStateRepo, SARawMessageRepo, Database` | `ingestion_service` |
| `raw_and_processed_repos()` | `SARawMessageRepo, SAProcessedDocumentRepo, SAProcessingFailureRepo, Database` | `processing_service` (2×) |
| `ingestion_state_repo()` | `SAIngestionStateRepo, Database` | `pipeline_service`, `export_service` (nested!), `scheduler_service`, `background_scheduler` |
| `ingestion_and_processing_repos()` | `SAIngestionStateRepo, SAProcessedDocumentRepo, Database` | `scheduler_service` |
| `embedding_repos()` | `SAEmbeddingRepo, SAProcessedDocumentRepo, Database` | `embedding_service` (2×), `retrieval_service` |

**Всего 16 call-sites** в 9 сервисных файлах.

### Проблемы

#### P1: Каждый вызов CM → новый Database с 3 engines

Каждый `async with processing_repos()` создаёт новый `Database.from_settings(settings)`, инициализирует 3 engines (= 3 connection pools). При `pool_size=5`, `max_overflow=10` → до 45 connections на один CM вызов. Даже если используется только 1 session.

#### P2: Nested CMs в `export_service` → 2× Database

```python
# export_service.py, строки 47+72
async with processing_repos() as (...):          # Database #1: 3 engines
    async with ingestion_state_repo() as (...):   # Database #2: 3 engines
```

Одновременно до 90 idle connections. Session 40 (§8) зафиксировал как Medium severity.

#### P3: Нет DI — нет тестируемости

Сервисные функции не принимают repos как параметры. Для unit-тестирования приходится мокать `tg_parser.services.db_context.processing_repos` целиком, что хрупко и скрывает зависимости.

**Исключение:** `create_processing_pipeline()` уже принимает `processed_doc_repo`, `failure_repo`, `raw_repo` через параметры — это хороший паттерн.

#### P4: `db_context` не обрабатывает init() failure

5 из 6 CM не защищают `await db.init()` — при exception engines могут leak'нуть. Только `embedding_repos()` обёрнут правильно. Session 40 (§7) зафиксировал.

```python
# Текущий (неправильный) паттерн — 5 CM:
db = Database.from_settings(settings)
await db.init()     # ← если упадёт, finally ниже НЕ выполнится
session = db.processing_storage_session()
try:
    yield (...)
finally:
    await session.close()
    await db.close()

# Правильный паттерн (как в embedding_repos):
db = Database.from_settings(settings)
try:
    await db.init()
    session = db.processing_storage_session()
    try:
        yield (...)
    finally:
        await session.close()
finally:
    await db.close()
```

#### P5: Мёртвые импорты `settings`

`export_service.py` и `topicization_service.py` импортируют `from tg_parser.config import settings`, но не используют его в runtime-коде (только `db_context` неявно использует).

#### P6: Type hints ссылаются на конкретные SA*Repo, не на абстрактные порты

`processing_service.py`, `scheduler_service.py`, `topicization_service.py` импортируют конкретные `SA*Repo` для type hints вместо абстрактных портов из `storage/ports.py`.

---

## Задачи

### Задача D1: Добавить optional DI параметры в сервисные функции (HIGH)

**Принцип:** Каждая public-функция сервиса получает optional-параметры для repos. Если не переданы — функция сама вызывает CM из `db_context`. Если переданы — использует напрямую.

**Паттерн:**

```python
# ДО:
async def run_processing(channel_id: str, ...) -> dict[str, int]:
    async with raw_and_processed_repos() as (raw_repo, processed_repo, failure_repo, _db):
        # ... business logic ...

# ПОСЛЕ:
async def run_processing(
    channel_id: str,
    ...,
    raw_repo: RawMessageRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> dict[str, int]:
    if raw_repo is not None and processed_repo is not None and failure_repo is not None:
        return await _run_processing_impl(channel_id, raw_repo, processed_repo, failure_repo, ...)
    async with raw_and_processed_repos() as (raw_repo, processed_repo, failure_repo, _db):
        return await _run_processing_impl(channel_id, raw_repo, processed_repo, failure_repo, ...)
```

**Альтернативный (более простой) паттерн — без выделения _impl:**

```python
async def run_processing(
    channel_id: str,
    ...,
    raw_repo: RawMessageRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> dict[str, int]:
    async with contextlib.AsyncExitStack() as stack:
        if raw_repo is None or processed_repo is None or failure_repo is None:
            raw_repo, processed_repo, failure_repo, _db = await stack.enter_async_context(
                raw_and_processed_repos()
            )
        # ... далее business logic без изменений ...
```

**Файлы и их функции:**

| Файл | Функция | Repos для DI |
|------|---------|--------------|
| `processing_service.py` | `run_processing()` | `RawMessageRepo`, `ProcessedDocumentRepo`, `ProcessingFailureRepo` |
| `processing_service.py` | `run_multi_agent_processing()` | `RawMessageRepo`, `ProcessedDocumentRepo`, `ProcessingFailureRepo` |
| `topicization_service.py` | `run_topicization()` | `ProcessedDocumentRepo`, `TopicCardRepo`, `TopicBundleRepo` |
| `topicization_service.py` | `run_incremental_topicization()` | `ProcessedDocumentRepo`, `TopicCardRepo`, `TopicBundleRepo` |
| `topicization_service.py` | `run_incremental_topicization_for_uncovered()` | `ProcessedDocumentRepo`, `TopicCardRepo`, `TopicBundleRepo` |
| `embedding_service.py` | `run_embedding()` | `EmbeddingRepo`, `ProcessedDocumentRepo` |
| `embedding_service.py` | `run_incremental_embedding()` | `EmbeddingRepo`, `ProcessedDocumentRepo` |
| `retrieval_service.py` | `search()` | `EmbeddingRepo`, `ProcessedDocumentRepo` |
| `retrieval_service.py` | `answer()` | (вызывает `search()` → DI тянется через параметры) |
| `ingestion_service.py` | `run_ingestion()` | `IngestionStateRepo`, `RawMessageRepo` |
| `export_service.py` | `run_export()` | `ProcessedDocumentRepo`, `TopicCardRepo`, `TopicBundleRepo`, `IngestionStateRepo` |
| `pipeline_service.py` | `_get_channel_id_from_source()` | `IngestionStateRepo` |
| `scheduler_service.py` | `run_incremental_for_all_sources()` | `IngestionStateRepo`, `ProcessedDocumentRepo` |
| `scheduler_service.py` | `get_scheduler_status()` | `IngestionStateRepo` |

**Типы для параметров берём из `storage/ports.py`** (абстрактные ABC), не из `sqlalchemy/`:
- `IngestionStateRepo`, `RawMessageRepo`, `ProcessedDocumentRepo`, `ProcessingFailureRepo`, `TopicCardRepo`, `TopicBundleRepo`, `EmbeddingRepo`

**Важно:**
- Сохранить обратную совместимость — все параметры optional с default `None`
- Не менять сигнатуры CLI/API вызовов — DI используется только при программном вызове или в тестах
- `pipeline_service.py` — оркестратор, вызывает `run_ingestion`, `run_processing`, `run_topicization`; DI в него самого можно пропустить (он не работает с repos напрямую, кроме `_get_channel_id_from_source`)

---

### Задача D2: Исправить nested Database в `export_service` (MEDIUM)

**Проблема:** Два одновременных `Database` инстанса (см. P2).

**Решение:** Объединить в один CM или один `Database` lifecycle. Варианты:

**Вариант A (рекомендуемый):** Создать новый CM `export_repos()` в `db_context.py`, который открывает ingestion + processing в одном `Database`:

```python
@asynccontextmanager
async def export_repos():
    """CM for export (processing + ingestion state in single Database)."""
    db = Database.from_settings(settings)
    try:
        await db.init()
        proc_session = db.processing_storage_session()
        state_session = db.ingestion_state_session()
        try:
            yield (
                SAProcessedDocumentRepo(proc_session),
                SATopicCardRepo(proc_session),
                SATopicBundleRepo(proc_session),
                SAIngestionStateRepo(state_session),
                db,
            )
        finally:
            await proc_session.close()
            await state_session.close()
    finally:
        await db.close()
```

**Вариант B:** В `run_export` с DI-параметрами (D1) передавать все 4 repo — вложенность уходит автоматически.

---

### Задача D3: Исправить init() error handling в db_context CMs (LOW)

**Что сделать:** Привести 5 CM к паттерну `embedding_repos()` — обернуть `await db.init()` во внешний `try/finally: await db.close()`.

**Файл:** `tg_parser/services/db_context.py`

**Текущий правильный паттерн (embedding_repos):**
```python
db = Database.from_settings(settings)
try:
    await db.init()
    session = db.processing_storage_session()
    try:
        yield (...)
    finally:
        await session.close()
finally:
    await db.close()
```

Применить к: `processing_repos`, `ingestion_repos`, `raw_and_processed_repos`, `ingestion_state_repo`, `ingestion_and_processing_repos`.

---

### Задача D4: Cleanup мёртвых импортов и type hints (LOW)

1. Удалить неиспользуемые `from tg_parser.config import settings` в `export_service.py` и `topicization_service.py`

2. Заменить type hints с конкретных SA*Repo на абстрактные порты:
   - `processing_service.py`: `SAProcessedDocumentRepo` → `ProcessedDocumentRepo`, `SARawMessageRepo` → `RawMessageRepo`
   - `scheduler_service.py`: `SAIngestionStateRepo` → `IngestionStateRepo`
   - `topicization_service.py`: `SAProcessedDocumentRepo` → `ProcessedDocumentRepo`, `SATopicBundleRepo` → `TopicBundleRepo`

3. Убедиться, что после замены `ruff check` не показывает ошибок

---

### Задача D5: Написать тесты с DI (MEDIUM)

Написать 2-3 unit-теста, демонстрирующих DI паттерн — repos передаются напрямую без db_context:

1. `test_processing_service_di` — вызвать `run_processing()` с mock repos переданными через параметры, без реального DB
2. `test_export_service_di` — аналогично для `run_export()` с mock repos
3. `test_topicization_service_di` — аналогично для `run_topicization()`

Эти тесты должны быть лёгкими (не требовать PostgreSQL) и демонстрировать, что DI работает.

**Добавить в существующий `tests/` или создать `tests/test_service_di.py`.**

---

## Справка по файлам

### Абстрактные порты (`storage/ports.py`)

```
IngestionStateRepo    — get_source, list_sources, upsert_source, update_cursors, ...
RawMessageRepo        — upsert, get_by_source_ref, list_by_channel, record_conflict
ProcessedDocumentRepo — upsert, get_by_source_ref, list_by_channel, exists, list_all
ProcessingFailureRepo — record_failure, delete_failure, list_failures
TopicCardRepo         — upsert, get_by_id, list_by_channel, list_all, delete_by_channel
TopicBundleRepo       — upsert, get_by_topic_id, list_by_channel, add_items, delete_by_channel
EmbeddingRepo         — save, get_by_source_ref, similarity_search, count, list_missing
JobRepo               — create, get, update, list_jobs, delete_old_jobs
AgentStateRepo        — save, get, list_all, delete, update_statistics
TaskHistoryRepo       — record, get, list_by_agent, list_by_channel, cleanup_expired
AgentStatsRepo        — record, get_daily, get_range, get_summary
HandoffHistoryRepo    — record, update_status, get, list_by_agent, get_statistics
```

### Сервисные файлы (16 call-sites на db_context)

```
topicization_service.py    — 4 вызова processing_repos()
processing_service.py      — 2 вызова raw_and_processed_repos()
embedding_service.py       — 2 вызова embedding_repos()
scheduler_service.py       — 1 ingestion_and_processing_repos() + 1 ingestion_state_repo()
export_service.py          — 1 processing_repos() + 1 ingestion_state_repo() (NESTED!)
retrieval_service.py       — 1 embedding_repos()
ingestion_service.py       — 1 ingestion_repos()
pipeline_service.py        — 1 ingestion_state_repo()
background_scheduler.py    — 1 ingestion_state_repo() (lazy import)
```

### Тестовые паттерны

- **Integration:** `test_db` fixture → real `Database` + `SA*Repo`
- **Unit:** `AsyncMock()` as repos (e.g. `test_processing_pipeline.py` — `ProcessingPipelineImpl` принимает repos через конструктор)
- **API:** `httpx.AsyncClient` + `patch("tg_parser.services.*.function")`

### `settings` usage в services (реальное)

| Файл | Что читает из `settings` |
|------|--------------------------|
| `db_context.py` | `Database.from_settings(settings)` — все 6 CM |
| `_wiring.py` | `create_engine_from_settings(settings, ...)`, `agent_retention_days`, `agent_stats_enabled` |
| `processing_service.py` | `processing_concurrency` (default для `concurrency` param) |
| `embedding_service.py` | `openai_api_key`, `embedding_model`, `openai_base_url`, `embedding_batch_size` |
| `retrieval_service.py` | `openai_api_key`, `llm_model`, `openai_base_url` (в `_call_llm`) |
| `ingestion_service.py` | `TelethonClient(settings)`, `IngestionOrchestrator(..., settings=settings)` |
| `scheduler_service.py` | `processing_concurrency`, `scheduler_*`, `retopicize_threshold`, intervals |
| `background_scheduler.py` | `setup_default_tasks` → lazy `settings` для interval |
| `pipeline_service.py` | **Только в docstring** (dead import) |
| `export_service.py` | **Не используется** (dead import) |
| `topicization_service.py` | **Не используется** (dead import) |

---

## Порядок выполнения

| # | Задача | Файлы | Риск |
|---|--------|-------|------|
| 1 | D3: init() error handling | `db_context.py` | Низкий |
| 2 | D4: Мёртвые импорты + type hints | 5 файлов | Низкий |
| 3 | D2: export_repos() CM | `db_context.py`, `export_service.py` | Средний |
| 4 | D1: DI параметры в сервисах | 9 файлов | Средний |
| 5 | D5: Unit-тесты с DI | `tests/test_service_di.py` | Низкий |
| 6 | Тесты | — | — |

**Совет:** D3 и D4 — быстрые правки, начать с них. D2 + D1 — основная работа. D5 — валидация.

---

## Критерии завершения

- [ ] Все 6 CM в `db_context.py` обрабатывают `init()` failure (внешний `try/finally`)
- [ ] Nested Database в `export_service` устранён (1 Database на вызов)
- [ ] Минимум 7 ключевых сервисных функций принимают optional repo-параметры:
  - `run_processing`, `run_multi_agent_processing`
  - `run_topicization`, `run_incremental_topicization_for_uncovered`
  - `run_embedding`, `run_export`
  - `search` (retrieval)
- [ ] Type hints используют абстрактные порты, не `SA*Repo`
- [ ] Нет мёртвых `import settings` в `export_service.py`, `topicization_service.py`, `pipeline_service.py`
- [ ] 2-3 unit-теста демонстрируют DI (mock repos без DB)
- [ ] Все 567+ тестов + новые тесты проходят
- [ ] Обратная совместимость: CLI и API вызовы без изменений
- [ ] Технический коммит

---

**Подготовлено:** Session 45  
**Следующий шаг:** D3 (init error handling) + D4 (cleanup) → D2 (export_repos) → D1 (DI параметры) → D5 (тесты)
