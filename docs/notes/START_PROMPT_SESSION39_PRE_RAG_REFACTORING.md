# Session 39: Pre-RAG рефакторинг

**Дата:** [дата запуска]  
**Тип сессии:** Рефакторинг → подготовка фундамента для P5 (RAG)  
**Предыдущая сессия:** Session 38 (Code Review)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md`

---

## Цель сессии

Реализовать рефакторинги #1, #2 и #3 из roadmap, подготовив чистый архитектурный фундамент перед добавлением RAG-слоя. Исправить pre-existing test failures.

Общая оценка: **~500 строк изменений, ~1 сессия, риск низкий-средний**.

---

## Контекст проекта

Полная структура проекта, доменные модели, сервисные API, storage ports, CLI команды и LLM конфигурация описаны в `docs/notes/START_PROMPT_SESSION38_CODE_REVIEW.md` (разделы "Структура проекта", "Ключевые доменные модели", "Ключевые сервисные API", "Storage Ports", "CLI-команды", "LLM конфигурация", "Конфигурация"). Этот документ остаётся актуальным и является **обязательным справочником** для данной сессии — читать при необходимости.

Ключевые пути, затрагиваемые этой сессией:

```
tg_parser/
├── config/settings.py                    # Удаление db_type + SQLite path полей
├── storage/
│   ├── engine_factory.py                 # Удаление SQLite engine config
│   └── sqlalchemy/
│       ├── database.py                   # Удаление DatabaseConfig + legacy ветки
│       └── __init__.py                   # Удаление re-export DatabaseConfig
├── services/
│   ├── db_context.py                     # НОВЫЙ: context managers для repos
│   ├── background_scheduler.py           # НОВЫЙ: перемещено из api/scheduler.py
│   ├── topicization_service.py           # Замена boilerplate на CM
│   ├── processing_service.py             # Замена boilerplate на CM
│   ├── ingestion_service.py              # Замена boilerplate на CM
│   ├── export_service.py                 # Замена boilerplate на CM
│   ├── pipeline_service.py               # Замена boilerplate на CM
│   └── scheduler_service.py              # Замена boilerplate + incremental_pipeline_task
├── cli/init_db.py                        # Переписать на Database.from_settings
├── api/
│   ├── scheduler.py                      # Удалить / shim после перемещения
│   └── health_checks.py                  # Удаление SQLite ветки
└── tests/ (~9 файлов)                    # Миграция на PostgreSQL test DB
```

---

## Текущее состояние проекта

| Метрика | Значение |
|---------|----------|
| Python version | 3.12 |
| Версия проекта | v3.4.0 |
| Database backend | PostgreSQL (Homebrew local) |
| LLM provider | Anthropic Claude Sonnet 4 (topicization), Haiku 4.5 (processing) |
| Processed documents | 1130 (906 posts + 224 comments) |
| Topic cards | 83 (71 cluster + 12 singleton, 3 discovered) |
| Coverage | 92.4% (1044/1130 documents) |
| Test suite | 520 passed, 3 pre-existing failures, 24 skipped |

---

## 1. Каталог Database lifecycle

### 1.1 API класса Database

`tg_parser/storage/sqlalchemy/database.py`:

- `Database.from_settings(settings)` → `Database(settings=settings)`
- `await db.init()` — создаёт три async engine (ingestion / raw / processing) + три sessionmaker
- `db.ingestion_state_session()`, `db.raw_storage_session()`, `db.processing_storage_session()` → `AsyncSession`
- `await db.close()` — dispose всех трёх engines
- **Нет** `__aenter__`/`__aexit__` — lifecycle ручной `init` / `close`

### 1.2 Все точки создания Database (13 call sites)

| Файл | Функция | Repos | Lifecycle pattern | Проблемы |
|------|---------|-------|-------------------|----------|
| `cli/init_db.py` | `init_databases_fallback` | нет (DDL) | `Database(config)` → `init` → DDL → `finally: close` | Legacy path, `DatabaseConfig` |
| `cli/add_source_cmd.py` | `run_add_source` | `SQLiteIngestionStateRepo` | `from_settings` → `init` → session → `finally: session.close` → `db.close` | Чисто |
| `services/ingestion_service.py` | `run_ingestion` | `SQLiteIngestionStateRepo`, `SQLiteRawMessageRepo` | 2 sessions параллельно → `finally` обе закрыты → `db.close` | OK |
| `services/processing_service.py` | `run_processing` | `SQLiteRawMessageRepo`, `SQLiteProcessedDocumentRepo`, `SQLiteProcessingFailureRepo` | 2 sessions → `finally` закрыты → `db.close` | OK |
| `services/processing_service.py` | `run_multi_agent_processing` | `SQLiteRawMessageRepo`, `SQLiteProcessedDocumentRepo` | Дублирует pattern из `run_processing` | **Дубль** |
| `services/topicization_service.py` | `run_topicization` | `SQLiteProcessedDocumentRepo`, `SQLiteTopicCardRepo`, `SQLiteTopicBundleRepo` | 1 session → `finally` close → `db.close` | OK |
| `services/topicization_service.py` | `run_incremental_topicization` | то же | 1 session → `finally` close → `db.close` | OK |
| `services/topicization_service.py` | `run_incremental_topicization_for_uncovered` | Segment1: `ProcessedDocumentRepo`, `TopicBundleRepo` | **DB #1**: init → session → discover uncovered_refs → **close db** → **DB #2**: calls `run_incremental_topicization` or `_run_assign_only` → new full db cycle | **Двойная инициализация** |
| `services/topicization_service.py` | `_run_assign_only` | 3 processing repos | 1 session → `finally: db.close` | Вызывается из `run_incremental_for_uncovered` → 2-й DB |
| `services/export_service.py` | `run_export` | `SQLiteProcessedDocumentRepo`, `SQLiteTopicCardRepo`, `SQLiteTopicBundleRepo`, `SQLiteIngestionStateRepo` | processing session + nested ingestion session → `finally` обе → `db.close` | **Nested sessions** на одном db |
| `services/pipeline_service.py` | `_get_channel_id_from_source` | `SQLiteIngestionStateRepo` | Отдельный DB cycle, закрывается до основного pipeline | Отдельный DB от stages |
| `services/pipeline_service.py` | `run_full_pipeline` | делегирует | Calls `_get_channel_id_from_source` (1x DB) + up to 4 stage services (each creates own DB) | **До 5 DB lifecycles** за один pipeline run |
| `services/scheduler_service.py` | `run_incremental_for_all_sources` | `SQLiteIngestionStateRepo`, `SQLiteProcessedDocumentRepo` | Long-lived sessions + per-source `run_full_pipeline` (additional DBs) → `finally` close → `db.close` | **Overlapping lifetimes** — scheduler holds sessions while nested pipeline creates more |
| `services/scheduler_service.py` | `get_scheduler_status` | `SQLiteIngestionStateRepo` | Short session → close → `db.close` | Чисто |

### 1.3 Repos, чаще всего создаваемые вместе

| Комбинация | Где используется |
|------------|-----------------|
| **ProcessedDocumentRepo + TopicCardRepo + TopicBundleRepo** | `run_topicization`, `run_incremental_topicization`, `_run_assign_only`, `run_export` |
| **RawMessageRepo + ProcessedDocumentRepo** | `run_processing`, `run_multi_agent_processing` |
| **IngestionStateRepo + RawMessageRepo** | `run_ingestion` |
| **IngestionStateRepo alone** | `run_add_source`, `_get_channel_id_from_source`, `get_scheduler_status` |

### 1.4 Предлагаемый API context managers

```python
# tg_parser/services/db_context.py

from contextlib import asynccontextmanager
from tg_parser.config import settings
from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.processed_document_repo import SQLiteProcessedDocumentRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SQLiteTopicCardRepo
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SQLiteTopicBundleRepo
from tg_parser.storage.sqlalchemy.raw_message_repo import SQLiteRawMessageRepo
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SQLiteIngestionStateRepo
from tg_parser.storage.sqlalchemy.processing_failure_repo import SQLiteProcessingFailureRepo

@asynccontextmanager
async def processing_repos():
    """Context manager for processing repos (topicization, export)."""
    db = Database.from_settings(settings)
    await db.init()
    session = db.processing_storage_session()
    try:
        yield (
            SQLiteProcessedDocumentRepo(session),
            SQLiteTopicCardRepo(session),
            SQLiteTopicBundleRepo(session),
            db,  # for llm_client.close() ordering if needed
        )
    finally:
        await session.close()
        await db.close()

@asynccontextmanager
async def ingestion_repos():
    """Context manager for ingestion repos."""
    db = Database.from_settings(settings)
    await db.init()
    state_session = db.ingestion_state_session()
    raw_session = db.raw_storage_session()
    try:
        yield (
            SQLiteIngestionStateRepo(state_session),
            SQLiteRawMessageRepo(raw_session),
            db,
        )
    finally:
        await state_session.close()
        await raw_session.close()
        await db.close()

@asynccontextmanager
async def raw_and_processed_repos():
    """Context manager for processing pipeline (raw → processed)."""
    db = Database.from_settings(settings)
    await db.init()
    raw_session = db.raw_storage_session()
    proc_session = db.processing_storage_session()
    try:
        yield (
            SQLiteRawMessageRepo(raw_session),
            SQLiteProcessedDocumentRepo(proc_session),
            SQLiteProcessingFailureRepo(proc_session),
            db,
        )
    finally:
        await raw_session.close()
        await proc_session.close()
        await db.close()

@asynccontextmanager
async def ingestion_state_repo():
    """Context manager for single IngestionStateRepo (add-source, status)."""
    db = Database.from_settings(settings)
    await db.init()
    session = db.ingestion_state_session()
    try:
        yield SQLiteIngestionStateRepo(session), db
    finally:
        await session.close()
        await db.close()
```

### 1.5 Refactoring plan: порядок замен

**Шаг 1.** Создать `tg_parser/services/db_context.py` с 4 context managers.

**Шаг 2.** Заменить boilerplate в сервисах (от простого к сложному):

| # | Файл | Функция | CM | Строк экономии |
|---|------|---------|-----|----------------|
| 1 | `pipeline_service.py` | `_get_channel_id_from_source` | `ingestion_state_repo()` | ~10 |
| 2 | `scheduler_service.py` | `get_scheduler_status` | `ingestion_state_repo()` | ~10 |
| 3 | `topicization_service.py` | `run_topicization` | `processing_repos()` | ~15 |
| 4 | `topicization_service.py` | `run_incremental_topicization` | `processing_repos()` | ~15 |
| 5 | `topicization_service.py` | `_run_assign_only` | `processing_repos()` | ~12 |
| 6 | `topicization_service.py` | `run_incremental_for_uncovered` | Fix double init: single `processing_repos()` | ~20 |
| 7 | `processing_service.py` | `run_processing` | `raw_and_processed_repos()` | ~15 |
| 8 | `processing_service.py` | `run_multi_agent_processing` | `raw_and_processed_repos()` | ~12 |
| 9 | `ingestion_service.py` | `run_ingestion` | `ingestion_repos()` | ~12 |
| 10 | `export_service.py` | `run_export` | `processing_repos()` + nested `ingestion_state_repo()` | ~15 |

**Шаг 3.** Особый случай — `run_incremental_topicization_for_uncovered`:

Текущий код (строки 288–337 `topicization_service.py`):
- DB#1 → discover uncovered_refs → **close DB** → вызов `run_incremental_topicization()` или `_run_assign_only()`
- Каждая из этих функций создаёт свой DB#2

**Проблема:** нельзя просто обернуть в один CM, т.к. вызываемые функции — самостоятельные с собственным DB lifecycle.

**Решение: извлечь core-логику в internal helpers, принимающие repos:**

```python
# Шаг 1: Извлечь логику из _run_assign_only и run_incremental_topicization
# в helpers _do_assign_only(repos, channel_id, doc_refs) и _do_incremental(repos, ...)
# Эти helpers НЕ создают свой DB — принимают repos как аргументы.

# Шаг 2: Публичные функции становятся тонкими обёртками:
async def run_incremental_topicization(channel_id, new_doc_refs):
    async with processing_repos() as (doc_repo, card_repo, bundle_repo, db):
        return await _do_incremental(doc_repo, card_repo, bundle_repo, ...)

# Шаг 3: run_incremental_topicization_for_uncovered — один CM:
async def run_incremental_topicization_for_uncovered(channel_id, assign_only=False):
    async with processing_repos() as (doc_repo, card_repo, bundle_repo, db):
        uncovered_refs = ... # discover
        if assign_only:
            return await _do_assign_only(doc_repo, card_repo, bundle_repo, ...)
        else:
            return await _do_incremental(doc_repo, card_repo, bundle_repo, ...)
```

Это частично пересекается с DI миграцией (Этап B), но только внутри одного файла и не меняет public API.

**Шаг 4.** `scheduler_service.py` `run_incremental_for_all_sources`: рассмотреть передачу DB контекста в stage-сервисы вместо per-stage создания (более глубокий рефакторинг, можно делать параллельно с RAG).

**Ожидаемый результат:** ~15 try/finally блоков заменяются на ~10 `async with` → экономия **~150 строк**, устранение двойной инициализации.

---

## 2. План инверсии services → api

### 2.1 Текущая проблема

`tg_parser/services/scheduler_service.py` → `_run_scheduler_async()` импортирует из `tg_parser/api/scheduler.py`:
- `BackgroundScheduler` (APScheduler wrapper, 162 строки)
- `setup_default_tasks` (wiring, 47 строк)

Это создаёт цикл: `api/scheduler.py` → `services/scheduler_service.py` (через `incremental_pipeline_task`) → `api/scheduler.py`.

### 2.2 Содержимое `api/scheduler.py` (336 строк)

| Строки | Символ | Категория | Действие |
|--------|--------|-----------|----------|
| 19–162 | `BackgroundScheduler` | INFRA (APScheduler) | **Переместить** в `services/` |
| 70–80 | `wrapped_func` (внутри BackgroundScheduler) | INFRA + OBS | Вместе с классом |
| 165–174 | `_scheduler`, `get_scheduler` | Singleton | **Переместить** с классом |
| 182–245 | `cleanup_expired_records` | DOMAIN (archiver + persistence) | **Переместить** в `services/` |
| 248–266 | `health_check_task` | API-LEAK (зависит от `api.health_checks`) | **Переместить** + инжектировать `check_all_components` |
| 269–316 | `setup_default_tasks` | ORCH (composition) | **Переместить** в `services/` |
| 319–334 | `incremental_pipeline_task` | DOMAIN (thin delegation) | **Переместить** в `scheduler_service.py` |
| 14 | `record_scheduler_task` import | OBS | Перенести `tg_parser.api.metrics` → `tg_parser.metrics` (или инжектировать) |

### 2.3 Конкретный план перемещения

**Файл назначения:** `tg_parser/services/background_scheduler.py` (новый)

| Что | Откуда | Куда |
|-----|--------|------|
| `BackgroundScheduler` class | `api/scheduler.py:19–162` | `services/background_scheduler.py` |
| `_scheduler`, `get_scheduler` | `api/scheduler.py:165–174` | `services/background_scheduler.py` |
| `cleanup_expired_records` | `api/scheduler.py:182–245` | `services/background_scheduler.py` |
| `health_check_task` | `api/scheduler.py:248–266` | `services/background_scheduler.py` |
| `setup_default_tasks` | `api/scheduler.py:269–316` | `services/background_scheduler.py` |
| `incremental_pipeline_task` | `api/scheduler.py:319–334` | `services/scheduler_service.py` (рядом с `run_incremental_for_all_sources`) |

**После перемещения:** `api/scheduler.py` → удалить или оставить shim с re-exports для обратной совместимости на 1 сессию.

### 2.4 Файлы для обновления импортов

| Файл | Текущий импорт | Новый импорт |
|------|----------------|-------------|
| `api/main.py` | `from tg_parser.api.scheduler import ...` | `from tg_parser.services.background_scheduler import ...` |
| `api/routes/health.py` | `from tg_parser.api.scheduler import get_scheduler` | `from tg_parser.services.background_scheduler import get_scheduler` |
| `api/health_checks.py` | `from tg_parser.api.scheduler import get_scheduler` | `from tg_parser.services.background_scheduler import get_scheduler` |
| `services/scheduler_service.py` | `from tg_parser.api.scheduler import BackgroundScheduler, setup_default_tasks` | `from tg_parser.services.background_scheduler import ...` |
| `tests/test_phase3d_advanced.py` | `from tg_parser.api.scheduler import ...` | `from tg_parser.services.background_scheduler import ...` |
| `tests/test_scheduler_service.py` | `tg_parser.api.scheduler.*` в `@patch` | `tg_parser.services.background_scheduler.*` |

### 2.5 Зависимость `record_scheduler_task`

`BackgroundScheduler.add_task` → `wrapped_func` → `record_scheduler_task` (из `api.metrics`).

**Решение:** На этом этапе оставить импорт `from tg_parser.api.metrics import record_scheduler_task` — это одна тонкая зависимость, которая не создаёт цикла. Перенос `metrics.py` в `tg_parser/metrics/` можно сделать в будущем.

### 2.6 Зависимость `health_check_task` → `api.health_checks`

**Решение:** Передавать `check_all_components` как callable в `setup_default_tasks`:

```python
def setup_default_tasks(
    scheduler: BackgroundScheduler,
    *,
    health_check_func: Callable | None = None,  # inject from api layer
    ...
):
    if health_check_func:
        scheduler.add_task(
            task_id="health_check",
            func=health_check_func,
            interval_seconds=health_check_interval_minutes * 60,
        )
```

Вызов из `api/main.py`:

```python
from tg_parser.api.health_checks import check_all_components
setup_default_tasks(scheduler, health_check_func=health_check_task_wrapper(check_all_components))
```

---

## 3. План DI миграции в services

### 3.1 Текущее состояние

| Сервис | Конкретные repo импорты | Функций | DI pattern | Сложность миграции |
|--------|-------------------------|---------|------------|-------------------|
| `_wiring.py` | 4 SQLite*Repo (agent stack) | 3 | Composition root для agents | Low–medium |
| `ingestion_service.py` | `Database`, `SQLiteIngestionStateRepo`, `SQLiteRawMessageRepo` | 1 | Нет. Repos внутри функции. Downstream `IngestionOrchestrator` уже принимает ports | Low |
| `pipeline_service.py` | `Database`, `SQLiteIngestionStateRepo` | 3 | Orchestration делегирует другим сервисам. `_get_channel_id_from_source` создаёт repo внутри | Low |
| `export_service.py` | `Database`, 4 SQLite repos | 1 | Нет DI. Одна функция, 4 repo типа / 2 DB области | Medium |
| `scheduler_service.py` | `Database`, `SQLiteIngestionStateRepo`, `SQLiteProcessedDocumentRepo` | 8 | Mixed: `_safe_record_failure` получает repo как аргумент (но тип — конкретный SQLite*) | Medium |
| `topicization_service.py` | `Database`, 3 SQLite processing repos | 6 | Нет boundary DI. Helpers `_update_bundles_for_assignments`, `_compute_coverage` принимают repos как args, но с конкретными типами. `TopicizationPipelineImpl` уже принимает ports | Medium |
| `processing_service.py` | `Database`, 3 SQLite repos | 4 | Нет boundary DI. `run_processing` / `run_multi_agent_processing` инстанцируют SQLite repos. Pipeline ctor уже принимает ports | Medium–high |

### 3.2 Важное наблюдение

Downstream слой **уже использует ports**:
- `IngestionOrchestrator(raw_repo: RawMessageRepo, state_repo: IngestionStateRepo)`
- `ProcessingPipelineImpl(..., processed_doc_repo: ProcessedDocumentRepo)`
- `TopicizationPipelineImpl(..., processed_doc_repo: ProcessedDocumentRepo, topic_card_repo: TopicCardRepo, topic_bundle_repo: TopicBundleRepo)`

**Проблема только в composition** — сервисный слой сам конструирует конкретные SQLite* классы вместо получения через параметры.

### 3.3 Рекомендуемый порядок миграции

| # | Сервис | Причина приоритета | Влияние на тесты |
|---|--------|-------------------|-----------------|
| 1 | `pipeline_service.py` | Минимум repo (1 тип), helper function | ~5 patches |
| 2 | `ingestion_service.py` | 1 public function, orchestrator уже port-based | ~3 patches |
| 3 | `export_service.py` | 1 function, линейный control flow | ~5 patches |
| 4 | `scheduler_service.py` | Уточнить типы в `_safe_record_failure`, inject repos в loop | ~8 patches |
| 5 | `_wiring.py` | Alignment с global DI story | ~3 patches |
| 6 | `topicization_service.py` | Dedupe session/repo setup + change annotations | ~12 patches |
| 7 | `processing_service.py` | Два mode (regular + multi-agent), agent helper typing | ~10 patches |

### 3.4 Стратегия миграции

**Этап A (Session 39):** context managers из раздела 1 — убирают boilerplate, но repos по-прежнему конструируются внутри CM.

**Этап B (параллельно с RAG):** Вынести конструирование repos из CM, передавать через параметры:

```python
# Before (Session 39 — after CM refactoring):
async def run_topicization(channel_id, ...):
    async with processing_repos() as (doc_repo, card_repo, bundle_repo, db):
        ...

# After (Этап B):
async def run_topicization(
    channel_id,
    doc_repo: ProcessedDocumentRepo,
    card_repo: TopicCardRepo,
    bundle_repo: TopicBundleRepo,
    ...
):
    ...
```

**Новый `rag_service.py`** сразу писать с DI (принимает repos через параметры).

---

## 4. Обнаруженные проблемы (Code Review findings)

### 4.1 Критические — Нарушения layering

| Нарушение | Файл | Детали |
|-----------|------|--------|
| CLI → storage | `cli/init_db.py` | Импортирует `DatabaseConfig`, `storage.sqlalchemy` напрямую — **будет исправлено рефакторингом #3** |
| CLI → storage | `cli/add_source_cmd.py` | Импортирует `storage.ports`, `storage.sqlalchemy` |
| CLI → processing | `cli/app.py` | Импортирует `processing.llm.factory.resolve_llm_config` |
| CLI → storage | `cli/agents_cmd.py` | Импортирует `SQLiteTaskHistoryRepo`, `SQLiteHandoffHistoryRepo` |
| API → storage | `api/job_store.py` | Импортирует `engine_factory`, `storage.ports`, `SQLiteJobRepo` |
| API → storage | `api/routes/process.py` | Импортирует `storage.ports` (Job, JobStatus, JobType) |
| API → storage | `api/routes/export.py` | Импортирует `storage.ports` (Job, ...) |
| API → storage | `api/routes/health.py` | `_get_basic_stats` использует `engine_factory`, raw SQL |
| API → storage | `api/health_checks.py` | `check_database` использует `engine_factory`; `check_agent_registry` использует `SQLiteAgentStateRepo` |
| Services → API | `services/scheduler_service.py` | Импортирует `api.scheduler.BackgroundScheduler`, `setup_default_tasks` |

**Чистые слои:** `processing/` и `storage/` не имеют обратных зависимостей (confirmed via grep).

### 4.2 Medium — DRY нарушения

| Проблема | Детали |
|----------|--------|
| DB/repo wiring дублируется | 4 функции в `topicization_service.py` повторяют один и тот же pattern |
| Phase 1 duplicated | `run_incremental_topicization` и `_run_assign_only` оба строят `TopicizationPipelineImpl(llm_client=None)`, вызывают `assign_documents_to_topics`, затем `_update_bundles_for_assignments` |
| CLI try/except | `app.py` повторяет `try / except Exception / typer.echo / typer.Exit` в 8+ командах |
| Cross-service DB pattern | 6 сервисов повторяют `Database.from_settings` + session lifecycle |

### 4.3 Medium — Error handling

| Проблема | Файл | Строки |
|----------|------|--------|
| Silent `except Exception` → returns 0, no logging | `api/routes/health.py` | `_get_basic_stats`: failures silently return `0` counts |
| `except Exception: pass` | `api/scheduler.py:114–115` | `remove_job` swallows all errors |
| No logging of exception | `api/health_checks.py:299–302` | `check_scheduler` sets error but doesn't log `e` |

### 4.4 Medium — Async/sync issues

| Проблема | Файл | Детали |
|----------|------|--------|
| Sync gzip in async def | `agents/archiver.py:84–87, 113–116` | `gzip.open` + loop `f.write` blocks event loop |
| Sync file I/O on async path | `processing/prompt_loader.py:60` | `open()` в `get_prompt_loader()`, вызывается из async pipeline setup |

### 4.5 Low — Naming

Все 12 concrete repo классов именуются `SQLite*` (`SQLiteProcessedDocumentRepo`, `SQLiteTopicCardRepo`, etc.), хотя работают и с PostgreSQL. Косметика, не блокирует RAG.

---

## 5. Рефакторинг #3: Удаление SQLite support

### 5.1 Обоснование

- Production использует **только PostgreSQL** (`db_type = "postgresql"` по умолчанию)
- SQLite-код существует только для тестов — ~90 строк мёртвого production кода
- P5 (RAG) добавит pgvector — это **только PostgreSQL**, SQLite-тесты не смогут покрыть этот функционал
- Тесты на SQLite дают ложную уверенность: поведение SQLite и PostgreSQL различается (типы, блокировки, JSONB vs TEXT)
- `DatabaseConfig` уже помечен как `Deprecated`
- Session 39 рефакторит `Database` class — идеальный момент убрать legacy ветку

### 5.2 Что удалить / изменить в production коде (~150 строк)

| Что | Файл | Строк | Действие |
|-----|------|-------|----------|
| `DatabaseConfig` class целиком | `storage/sqlalchemy/database.py` | ~30 | Удалить |
| Legacy ветка `if config` в `Database.__init__` и `Database.init()` | `storage/sqlalchemy/database.py` | ~15 | Удалить, оставить только `settings` path |
| `create_sqlite_engine_config()`, `_build_sqlite_url()` | `storage/engine_factory.py` | ~25 | Удалить |
| SQLite ветка в `create_engine_from_settings()` (`if db_type == "sqlite"`) | `storage/engine_factory.py` | ~18 | Удалить, оставить только PostgreSQL path |
| `NullPool` ветка в `create_engine_from_config()` + `get_pool_status()` | `storage/engine_factory.py` | ~10 | Удалить, убрать `NullPool` import |
| 3 поля `ingestion_state_db_path`, `raw_storage_db_path`, `processing_storage_db_path` | `config/settings.py` | ~3 | Удалить |
| `db_type` поле | `config/settings.py` | ~3 | **Удалить** (все code paths теперь PostgreSQL-only; оставление поля позволит пользователю выставить `"sqlite"` и получить cryptic error) |
| Re-export `DatabaseConfig` | `storage/sqlalchemy/__init__.py` | ~2 | Удалить из import и `__all__` |
| SQLite ветки (`if db_type == "sqlite"`, `sqlite_master` query) | `api/health_checks.py` | ~15 | Удалить, оставить только PostgreSQL check |
| `init_databases_fallback`, `check_databases_exist`, SQLite-specific логика в `init_databases_sync` | `cli/init_db.py` | ~60 | Переписать: `init_databases_fallback` → использовать `Database.from_settings(settings)`, удалить `check_databases_exist` (проверяла `.sqlite` файлы), убрать создание директорий для `.sqlite` |
| `aiosqlite` dependency | `requirements.txt` **и** `pyproject.toml` | 2 | Удалить из обоих |

### 5.3 Что обновить в тестах (~9 файлов)

Все тесты, использующие `DatabaseConfig`, `db_type="sqlite"`, или SQLite tmpdir, нужно перевести на PostgreSQL:

| Файл | Текущий подход | Новый подход |
|------|---------------|-------------|
| `tests/conftest.py` | `DatabaseConfig(tmppath / "*.sqlite")` в `test_db`; SQLite path поля в `test_settings` | PostgreSQL test DB через `Settings` override (без `db_type`, без `*_db_path`) |
| `tests/test_storage_integration.py` | `DatabaseConfig` + tmpdir | PostgreSQL test DB |
| `tests/test_e2e_pipeline.py` | `db_type="sqlite"` в e2e_settings | Убрать `db_type`, использовать PostgreSQL |
| `tests/test_migrations.py` | Физические `.sqlite` файлы | PostgreSQL test DB (Alembic уже поддерживает PostgreSQL) |
| `tests/test_phase3d_advanced.py` | `mock_settings.db_type = "sqlite"` | Убрать mock `db_type`, использовать PostgreSQL mock |
| `tests/test_processing_pipeline.py` | `db_type="sqlite"` в 3 местах (строки 622, 635, 646) | Убрать `db_type` из `Settings(...)` конструкций |
| `tests/test_postgres_integration.py` | `Settings(db_type="sqlite")` в фикстуре + тест `invalid_db_type` | Удалить SQLite фикстуру, удалить тест валидации `db_type`, убрать `skipif` |
| `tests/test_postgres_concurrency.py` | `db_type="postgresql"` | Убрать `db_type` из Settings конструкции |
| `tests/test_multi_agent.py` | Возможно использует SQLite settings | Проверить и обновить при необходимости |

**Рекомендуемый подход для тестов:**

1. В `conftest.py` создать фикстуру `test_db`, которая:
   - Читает PostgreSQL connection из env vars (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`) с разумными defaults для локального dev
   - Использует `Database.from_settings(test_settings)` вместо `Database(DatabaseConfig(...))`
   - Перед тестами: создать все таблицы через DDL (`init_*_schema`)
   - После тестов: `TRUNCATE` всех таблиц (быстрее, чем `DROP DATABASE`)
2. Фикстура `test_settings` → убрать `db_type` и `*_db_path` поля, добавить PostgreSQL connection params
3. Для изоляции: использовать отдельную test database (`tg_parser_test`) или schema per test session

### 5.4 Обновить CI

В `.github/workflows/ci.yml` добавить PostgreSQL service:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: tg_parser_test
          POSTGRES_USER: tg_parser_test
          POSTGRES_PASSWORD: test_password
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DB_HOST: localhost
      DB_PORT: 5432
      DB_NAME: tg_parser_test
      DB_USER: tg_parser_test
      DB_PASSWORD: test_password
```

**Примечание:** `DB_TYPE` не нужен — после рефакторинга PostgreSQL единственный backend.

### 5.5 Что оставить

- `engine_factory.py` — оставить PostgreSQL path (`create_postgres_engine_config`, `create_engine_from_settings` без ветвления), `EngineConfig` class, `get_pool_status` (без NullPool ветки)
- Имена классов `SQLite*Repo` — **не переименовывать** в этой сессии (косметика, отдельная задача)
- DDL-файлы в `storage/sqlalchemy/schemas/` — SQL совместим и с PostgreSQL (TEXT типы работают), обновить только docstring-комментарии с "sqlite" на generic

---

## 6. Исправление pre-existing test failures

### 6.1 `test_agents.py::test_process_message_with_agent` — APIConnectionError

**Диагноз:** Тест вызывает реальный OpenAI API. `@pytest.mark.skipif(not _has_openai_api_key())` пропускает без ключа, но с ключом и без сети — `APIConnectionError`.

**Исправление:** Добавить `@pytest.mark.integration` + исключить из default runs. Или: mock `Runner.run` для стабильности в CI.

### 6.2 `test_e2e_pipeline.py::test_full_pipeline_e2e` и `test_comments_ingestion_with_per_thread_cursors`

**Диагноз:** `_ingest_comments` в `ingestion/orchestrator.py` проверяет `raw_payload.get("replies", 0) > 0` перед вызовом `get_comments`. Тестовые mock-данные создают `raw_payload` без ключа `"replies"` → `replies_count == 0` → `get_comments` никогда не вызывается → assertions на `comments_collected` fail.

**Исправление:** В `tests/test_e2e_pipeline.py`, функция `create_mock_convert_message()` (или тестовые данные) — добавить `"replies": N` в `raw_payload` для постов, которые должны получать комментарии:

```python
# test_full_pipeline_e2e: post 1 needs "replies": 1
raw_payload={"id": 1, "text": "...", "date": "...", "replies": 1}

# test_comments_ingestion_with_per_thread_cursors: posts 100, 200 need "replies"
raw_payload={"id": 100, "text": "...", "date": "...", "replies": 2}
raw_payload={"id": 200, "text": "...", "date": "...", "replies": 1}
```

---

## 7. Рекомендации для RAG (P5)

### 7.1 Что embed'ить

| Тип entry | Content для embedding | Обоснование |
|-----------|----------------------|-------------|
| **Message entry** (1130 шт.) | `summary + "\n\n" + text_clean` (как в текущем `kb_mapping.py`) | Summary даёт компактный семантический якорь, text_clean — полноту |
| **Topic entry** (83 шт.) | `title + "\n" + summary + "\n" + scope_in` | Тема как high-level navigational anchor |

Рекомендуемая модель: **OpenAI `text-embedding-3-small`** (1536 dims, дёшево, хорошее качество для русского текста). Fallback: `text-embedding-3-large` (3072 dims) если качество недостаточно.

### 7.2 Хранение embeddings — pgvector

**Рекомендация: pgvector** (расширение PostgreSQL) — лучший выбор для текущей архитектуры:

1. **Уже есть PostgreSQL** — не нужна отдельная инфраструктура
2. **1213 entries** (1130 messages + 83 topics) — pgvector легко справится, порог масштабирования ~1M vectors
3. **ACID гарантии** — embeddings хранятся рядом с source data в одной транзакции
4. **Инкрементальное обновление** — natural fit с `upsert` паттерном

**Установка:**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE processed_documents ADD COLUMN embedding vector(1536);
CREATE INDEX ON processed_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- Или отдельная таблица для всех KB entries:
CREATE TABLE kb_embeddings (
    id TEXT PRIMARY KEY,           -- kb:msg:... или kb:topic:...
    source_ref TEXT,               -- FK to processed_documents or topic_cards
    entry_type TEXT NOT NULL,      -- 'message' | 'topic'
    content_hash TEXT NOT NULL,    -- SHA256 of embedded content (для инкрементальности)
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    model TEXT NOT NULL            -- 'text-embedding-3-small'
);

CREATE INDEX ON kb_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
```

**Рекомендация:** Отдельная таблица `kb_embeddings` — чище, не требует миграции существующих таблиц, поддерживает оба типа entries (message + topic).

### 7.3 Retrieval pipeline (high-level)

```
User Query
    ↓
Embedding (text-embedding-3-small)
    ↓
pgvector similarity search (cosine, top-K=10)
    ↓
Post-filter: topic_id, channel_id, date range
    ↓
Re-rank: boost topic entries (navigational), penalize low-score matches
    ↓
Context Assembly (top 5 entries, <4K tokens)
    ↓
LLM Q&A (Claude Sonnet 4 or Haiku)
    ↓
Answer + Source References
```

### 7.4 Новые компоненты для P5

| Компонент | Расположение | Описание |
|-----------|-------------|----------|
| `EmbeddingClient` (port) | `processing/ports.py` | ABC: `async def embed(texts: list[str]) -> list[list[float]]` |
| `OpenAIEmbeddingClient` | `processing/llm/openai_embedding.py` | Реализация через OpenAI API |
| `KBEmbeddingRepo` (port) | `storage/ports.py` | ABC: `upsert`, `search_similar`, `get_by_id` |
| `PgVectorKBEmbeddingRepo` | `storage/sqlalchemy/kb_embedding_repo.py` | pgvector реализация |
| `rag_service.py` | `services/rag_service.py` | Orchestrates embed + search + LLM Q&A |
| `/api/routes/qa.py` | `api/routes/qa.py` | `POST /qa` endpoint |
| CLI: `tg-parser embed` | `cli/app.py` | Генерация embeddings (full + incremental) |

### 7.5 Инкрементальная генерация embeddings

Стратегия на основе `content_hash`:

1. При экспорте/обновлении KB entry — вычислить SHA256 от content
2. Если `content_hash` не изменился → skip embed
3. Если изменился или новый → embed + upsert в `kb_embeddings`
4. CLI: `tg-parser embed --channel X [--force]` — force re-embeds all

---

## 8. Задачи для Session 39

### Обязательные (блокируют RAG)

- [ ] **Рефакторинг #1:** Создать `services/db_context.py` с 4 context managers (раздел 1.4)
- [ ] **Рефакторинг #1:** Заменить boilerplate в 6 service файлах (таблица 1.5)
- [ ] **Рефакторинг #1:** Устранить двойную инициализацию в `run_incremental_topicization_for_uncovered`
- [ ] **Рефакторинг #2:** Создать `services/background_scheduler.py` и переместить код (раздел 2.3)
- [ ] **Рефакторинг #2:** Обновить импорты в 6 файлах (таблица 2.4)
- [ ] **Рефакторинг #3:** Удалить `DatabaseConfig`, SQLite engine config, legacy ветки, `db_type` поле (раздел 5.2)
- [ ] **Рефакторинг #3:** Переписать `cli/init_db.py` на `Database.from_settings` (раздел 5.2)
- [ ] **Рефакторинг #3:** Удалить SQLite ветки в `api/health_checks.py` (раздел 5.2)
- [ ] **Рефакторинг #3:** Перевести ~9 тестовых файлов на PostgreSQL test DB (раздел 5.3)
- [ ] **Рефакторинг #3:** Добавить PostgreSQL service в `.github/workflows/ci.yml` (раздел 5.4)
- [ ] **Рефакторинг #3:** Удалить `aiosqlite` из `requirements.txt` и `pyproject.toml`
- [ ] **Тесты:** Исправить 3 pre-existing failures (раздел 6)

### Рекомендуемые (не блокируют, улучшают качество)

- [ ] Добавить logging в `api/routes/health.py::_get_basic_stats` silent except
- [ ] Добавить logging в `api/health_checks.py::check_scheduler`
- [ ] Заменить `except Exception: pass` в `api/scheduler.py` remove_job на logging
- [ ] Рассмотреть `asyncio.to_thread` для `agents/archiver.py` sync gzip

### Отложить

- [ ] DI миграция services (делать параллельно с RAG, раздел 3)
- [ ] Переименование `SQLite*Repo` → generic (косметика)
- [ ] CLI layering violations (не блокируют RAG, рефакторить при удобном случае)
- [ ] API layering violations (Job types в routes — допустимо, т.к. это DTOs)

---

## 9. Порядок выполнения в Session 39

```
 #  | Шаг                                                | Оценка
----+----------------------------------------------------+--------
    | --- Рефакторинг #3: Удаление SQLite ---             |
 1  | Удалить SQLite из storage: DatabaseConfig,           | 20 мин
    | legacy ветки Database, engine_factory SQLite path,   |
    | NullPool ветка, settings поля, db_type               |
 2  | Переписать cli/init_db.py на Database.from_settings  | 15 мин
 3  | Удалить SQLite ветки в api/health_checks.py          | 10 мин
 4  | Удалить aiosqlite из requirements.txt, pyproject.toml|  5 мин
 5  | Создать PostgreSQL test fixture в conftest.py        | 15 мин
 6  | Перевести ~9 тестовых файлов на PostgreSQL           | 35 мин
 7  | Добавить PostgreSQL service в CI workflow            |  5 мин
 8  | Прогнать тесты — убедиться в 0 regressions          |  5 мин
    |                                                      |
    | --- Рефакторинг #1: Database lifecycle ---            |
 9  | Создать services/db_context.py                       | 15 мин
10  | Заменить boilerplate в topicization_service.py       | 30 мин
    | (включая fix двойной инициализации)                  |
11  | Заменить boilerplate в остальных 5 сервисах          | 30 мин
12  | Прогнать тесты — убедиться в 0 regressions          |  5 мин
    |                                                      |
    | --- Рефакторинг #2: Инверсия services → api ---      |
13  | Создать services/background_scheduler.py             | 20 мин
14  | Обновить импорты в 6 файлах + удалить/shim           | 15 мин
    | api/scheduler.py                                     |
15  | Прогнать тесты — убедиться в 0 regressions          |  5 мин
    |                                                      |
    | --- Финализация ---                                  |
16  | Исправить 3 pre-existing test failures               | 20 мин
17  | Финальный прогон всех тестов                         |  5 мин
18  | Обновить DEVELOPMENT_ROADMAP                         | 10 мин
```

**Итого: ~5 часов, ~500 строк net change.**

**Порядок обоснован:**
- **SQLite удаляется первым** (шаги 1–8), т.к. упрощает `Database` class до однозначного PostgreSQL-only → context managers (шаги 9–12) не нужно поддерживать dual-path
- **Context managers вторым** (шаги 9–12), т.к. после упрощения `Database` писать CM проще
- **Инверсия третьей** (шаги 13–15) — независима от первых двух, но логично идёт после стабилизации service layer
- **Test fixes последними** (шаг 16) — E2E тесты уже переведены на PostgreSQL в шаге 6, остаётся только добавить `"replies"` в mock data

---

## Чего НЕ делаем в Session 39

- RAG implementation — только фундамент
- DI миграция services — делать параллельно с RAG (Session 40+)
- Переименование SQLite* repos — косметика
- Изменения в production данных
- CLI/API контрактные изменения
