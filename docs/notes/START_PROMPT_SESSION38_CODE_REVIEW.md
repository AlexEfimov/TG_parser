# Session 38: Code Review + подготовка Pre-RAG рефакторинга

**Дата:** [дата запуска]  
**Тип сессии:** Code review → план рефакторинга → подготовка к P5 (RAG)  
**Предыдущие сессии:** Session 37 (CLI + integration), Sessions 34-36 (incremental topicization), Session 33 (topicization fix), Sessions 29-32 (refactoring + processing)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md` (раздел "Pre-RAG рефакторинг")

---

## Цель сессии

Провести code review и собрать всю информацию, необходимую для Session 39 (Pre-RAG рефакторинг):

1. **Ревью архитектуры** — оценить layering, DRY, error handling, naming
2. **Аудит Database lifecycle** — найти и каталогизировать все места дублирования паттерна `Database → session → repos → close`
3. **Аудит инверсии services → api** — точно определить что и куда переносить
4. **Аудит DI в services** — оценить текущие прямые импорты repo, подготовить план поэтапной миграции
5. **Подготовить детальный план рефакторинга для Session 39** — конкретные файлы, функции, порядок изменений

---

## Текущее состояние проекта

### Ключевые метрики

| Метрика | Значение |
|---------|----------|
| Python version | 3.12 |
| Версия проекта | v3.4.0 |
| Database backend | PostgreSQL (Homebrew local) |
| LLM provider | Anthropic Claude Sonnet 4 (topicization), Haiku 4.5 (processing) |
| Processed documents | 1130 (906 posts + 224 comments) |
| Topic cards | 83 (71 cluster + 12 singleton, 3 discovered) |
| Topic bundles | 83 |
| Coverage | 92.4% (1044/1130 documents) |
| Uncovered | 86 docs (mostly short/greeting messages) |
| Test suite | 520 passed, 3 pre-existing failures, 24 skipped |
| Test definitions | ~550 across 29 test files |
| Python modules | 156 .py files |
| Тестовый канал | @labdiagnostica_logical |

### Архитектурный flow

```
Telegram → Ingestion → Raw Storage (PostgreSQL)
                              ↓
                         Processing (LLM: Haiku 4.5)
                              ↓
                    Processed Documents (PostgreSQL)
                              ↓
                      ┌───────┴────────┐
                      ↓                ↓
              Full Topicization   Incremental Topicization
              (LLM: Sonnet 4)    Phase 1: keyword (0 tokens)
                      ↓           Phase 2: LLM discover (~20K tokens)
                      ↓                ↓
              Topic Cards + Topic Bundles (PostgreSQL)
                              ↓
                         KB Export (NDJSON + JSON)
```

### Scheduler flow

```
APScheduler (interval=3600s)
    → run_incremental_for_all_sources()
        → per source: ingest → process → incremental topicize
        → record attempt in source_attempts
```

---

## Структура проекта

```
TG_parser/
├── .env                          # Production config (PostgreSQL, Anthropic keys)
├── .env.example
├── pyproject.toml                # Package config, pytest settings
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── migrations/                   # Alembic DB migrations
│
├── tg_parser/                    # Main package
│   ├── cli/                      # Typer CLI commands
│   │   ├── app.py                # Main CLI app (8 commands + 3 sub-apps)
│   │   ├── topicize_cmd.py       # Thin re-export wrapper
│   │   ├── process_cmd.py        # Processing runner
│   │   ├── run_cmd.py            # Full pipeline runner
│   │   ├── export_cmd.py         # Export runner
│   │   ├── ingest_cmd.py         # Ingestion runner
│   │   ├── init_db.py            # Database initialization
│   │   ├── scheduler_cmd.py      # Scheduler commands
│   │   ├── agents_cmd.py         # Agent management
│   │   ├── db_cmd.py             # DB admin commands
│   │   ├── add_source_cmd.py     # Source management
│   │   └── api_cmd.py            # API server launcher
│   │
│   ├── config/                   # Settings (Pydantic BaseSettings)
│   │   ├── settings.py           # 80+ config fields
│   │   └── logging.py            # structlog configuration
│   │
│   ├── domain/                   # Domain models (Pydantic v2)
│   │   ├── models.py             # RawTelegramMessage, ProcessedDocument,
│   │   │                         # TopicCard, TopicBundle, KnowledgeBaseEntry,
│   │   │                         # TopicAssignment, IncrementalTopicizeResult
│   │   ├── ids.py                # Deterministic ID generation
│   │   ├── json_utils.py         # JSON helpers
│   │   └── contract_validation.py
│   │
│   ├── ingestion/                # Telegram data collection
│   │   ├── orchestrator.py       # Ingestion orchestrator
│   │   ├── interfaces.py         # Ingestion ports
│   │   └── telegram/
│   │       └── telethon_client.py # Telethon wrapper
│   │
│   ├── processing/               # LLM processing pipeline
│   │   ├── ports.py              # LLMClient, ProcessingPipeline, TopicizationPipeline ABCs
│   │   ├── pipeline.py           # ProcessingPipelineImpl
│   │   ├── topicization.py       # TopicizationPipelineImpl (full + incremental)
│   │   ├── topicization_prompts.py # Topicization + incremental discover prompts
│   │   ├── prompts.py            # Processing prompts
│   │   ├── prompt_loader.py      # YAML prompt loader
│   │   ├── mock_llm.py           # Mock LLM for testing
│   │   └── llm/
│   │       ├── factory.py        # create_llm_client(), resolve_llm_config()
│   │       ├── anthropic_client.py
│   │       ├── openai_client.py
│   │       ├── gemini_client.py
│   │       ├── ollama_client.py
│   │       └── rate_limiter.py   # Token-aware rate limiter
│   │
│   ├── services/                 # Application services (business logic orchestration)
│   │   ├── topicization_service.py  # run_topicization, run_incremental_*, _run_assign_only
│   │   ├── scheduler_service.py     # run_incremental_for_all_sources, scheduler daemon
│   │   ├── pipeline_service.py      # run_full_pipeline (one-shot)
│   │   ├── processing_service.py    # Processing service
│   │   ├── ingestion_service.py     # Ingestion service
│   │   ├── export_service.py        # Export service
│   │   └── _wiring.py               # DI wiring helpers
│   │
│   ├── storage/                  # Persistence layer
│   │   ├── ports.py              # Abstract repos: ProcessedDocumentRepo, TopicCardRepo,
│   │   │                         # TopicBundleRepo, RawMessageRepo, IngestionStateRepo,
│   │   │                         # JobRepo, AgentStateRepo, TaskHistoryRepo, etc.
│   │   ├── engine_factory.py     # SQLite + PostgreSQL engine creation
│   │   └── sqlalchemy/
│   │       ├── database.py       # Database class (session factories)
│   │       ├── processed_document_repo.py
│   │       ├── topic_card_repo.py
│   │       ├── topic_bundle_repo.py
│   │       ├── raw_message_repo.py
│   │       ├── ingestion_state_repo.py
│   │       ├── job_repo.py
│   │       ├── agent_state_repo.py
│   │       ├── agent_stats_repo.py
│   │       ├── task_history_repo.py
│   │       ├── handoff_history_repo.py
│   │       ├── processing_failure_repo.py
│   │       └── schemas/          # SQLAlchemy table definitions
│   │           ├── ingestion_state.py
│   │           ├── raw_storage.py
│   │           └── processing_storage.py
│   │
│   ├── export/                   # Data export (NDJSON, JSON)
│   │   ├── kb_export.py          # KnowledgeBase export
│   │   ├── kb_mapping.py         # Doc → KBEntry mapping
│   │   ├── topics_export.py      # Topics export
│   │   └── telegram_url.py       # URL builder
│   │
│   ├── api/                      # FastAPI HTTP API
│   │   ├── main.py               # App factory
│   │   ├── auth.py               # API key auth
│   │   ├── scheduler.py          # BackgroundScheduler, APScheduler tasks
│   │   ├── health_checks.py
│   │   ├── job_store.py
│   │   ├── metrics.py
│   │   ├── schemas.py
│   │   ├── webhooks.py
│   │   ├── middleware/           # Logging, rate limiting
│   │   └── routes/              # HTTP endpoints
│   │
│   └── agents/                   # Multi-agent system (v2.0/Phase 3)
│       ├── base.py               # BaseAgent
│       ├── orchestrator.py       # OrchestratorAgent
│       ├── processing_agent.py
│       ├── persistence.py
│       ├── registry.py
│       ├── specialized/          # Export, processing, topicization agents
│       └── tools/                # Agent tools (pipeline, text)
│
├── tests/                        # 29 test files, ~550 test definitions
├── scripts/                      # Operational scripts
├── prompts/                      # YAML prompt files
├── docs/                         # Documentation (84 .md + 5 JSON schemas)
│   ├── contracts/                # JSON Schema for domain models
│   ├── adr/                      # Architecture Decision Records
│   └── notes/                    # Session logs, roadmaps, start prompts
└── output/                       # Export output directory
```

---

## Ключевые доменные модели

### ProcessedDocument
```python
class ProcessedDocument(BaseModel):
    id: str                        # "doc:" + source_ref
    source_ref: str                # "tg:<channel>:<type>:<id>"
    source_message_id: str
    channel_id: str
    processed_at: datetime
    text_clean: str
    summary: str | None
    topics: list[str]              # Извлечённые темы (из LLM processing)
    entities: list[Entity]
    language: str | None
    metadata: dict[str, Any] | None
```

### TopicCard
```python
class TopicCard(BaseModel):
    id: str                        # "topic:" + primary_anchor_ref
    title: str
    summary: str
    scope_in: list[str]            # Что входит в тему
    scope_out: list[str]           # Что не входит
    type: TopicType                # singleton | cluster
    anchors: list[Anchor]          # Min 1, cluster requires 2+
    sources: list[str]             # Channel IDs
    updated_at: datetime
    tags: list[str] | None
    related_topics: list[str] | None
    status: str | None
    metadata: dict[str, Any] | None  # origin, algorithm, pipeline_version...
```

### TopicBundle
```python
class TopicBundle(BaseModel):
    topic_id: str                  # FK → TopicCard.id
    items: list[BundleItem]        # Anchors + supporting items
    updated_at: datetime
    time_range: TimeRange | None
    channels: list[str] | None
    metadata: dict[str, Any] | None
```

### KnowledgeBaseEntry
```python
class KnowledgeBaseEntry(BaseModel):
    id: str                        # "kb:msg:<source_ref>" или "kb:topic:<topic_id>"
    source: KnowledgeBaseEntrySource
    created_at: datetime
    title: str
    content: str
    topics: list[str]
    tags: list[str]
    vector: list[float] | None     # ← Пустое поле для будущих embeddings (P5 RAG)
    metadata: dict[str, Any] | None
```

### TopicAssignment + IncrementalTopicizeResult
```python
class TopicAssignment(BaseModel):
    source_ref: str
    topic_id: str
    score: float                   # 0.0–1.0
    method: str                    # "keyword" | "llm"

class IncrementalTopicizeResult(BaseModel):
    assigned_keyword: list[TopicAssignment] = []
    assigned_llm: list[TopicAssignment] = []
    new_topics: list[TopicCard] = []
    unassignable: list[str] = []
    tokens_used: int = 0           # TODO: fill from LLM response
    coverage_before: float = 0.0
    coverage_after: float = 0.0
```

---

## Ключевые сервисные API

### topicization_service.py
```python
async def run_topicization(channel_id, force=False, build_bundles=True) -> dict[str, int]
async def run_incremental_topicization(channel_id, new_doc_refs) -> IncrementalTopicizeResult
async def run_incremental_topicization_for_uncovered(channel_id, assign_only=False) -> IncrementalTopicizeResult
```

### scheduler_service.py
```python
async def run_incremental_for_all_sources(output_dir="./output") -> dict[str, Any]
async def run_incremental_for_source(source_id, output_dir="./output") -> dict[str, Any]
async def get_scheduler_status() -> dict[str, Any]
def run_scheduler_blocking(interval_seconds=None) -> None
```

### pipeline_service.py
```python
async def run_full_pipeline(source_id, output_dir, mode, skip_ingest, skip_process,
                            skip_topicize, force, limit, concurrency) -> dict
```

### TopicizationPipelineImpl (processing/topicization.py)
```python
async def topicize_channel(channel_id, force=False) -> list[TopicCard]
async def build_topic_bundle(topic_card, channel_id, documents=None) -> TopicBundle
async def assign_documents_to_topics(new_docs, channel_id) -> (assignments, unassigned_refs)
async def discover_new_topics(channel_id, unassigned_docs) -> (llm_assigns, new_cards, unassignable)
```

---

## Storage Ports (абстрактные интерфейсы)

### ProcessedDocumentRepo
```python
async def upsert(doc) -> None
async def get_by_source_ref(source_ref) -> ProcessedDocument | None
async def list_by_channel(channel_id, from_date?, to_date?) -> list[ProcessedDocument]
async def exists(source_ref) -> bool
async def list_all(from_date?, to_date?, limit?) -> list[ProcessedDocument]
```

### TopicCardRepo
```python
async def upsert(card) -> None
async def get_by_id(topic_id) -> TopicCard | None
async def list_by_channel(channel_id) -> list[TopicCard]
async def list_all() -> list[TopicCard]
async def delete_by_channel(channel_id) -> int
```

### TopicBundleRepo
```python
async def upsert(bundle) -> None
async def get_by_topic_id(topic_id) -> TopicBundle | None
async def list_by_channel(channel_id) -> list[TopicBundle]
async def add_items(topic_id, new_items) -> TopicBundle
async def delete_by_channel(channel_id) -> int
```

### LLMClient (processing/ports.py)
```python
async def generate(prompt, system_prompt?, temperature=0.0, max_tokens=4096, response_format?) -> str
```

---

## CLI-команды

| Команда | Описание |
|---------|----------|
| `tg-parser init [--force]` | Инициализация БД |
| `tg-parser add-source --source-id X --channel-id Y` | Добавить канал |
| `tg-parser ingest --source X [--mode incremental]` | Сбор сообщений |
| `tg-parser process --channel X [--concurrency 20]` | LLM обработка |
| `tg-parser topicize --channel X [--mode full\|incremental\|assign-only] [--force]` | Топикизация |
| `tg-parser export [--channel X] [--out ./output]` | Экспорт KB + topics |
| `tg-parser run --source X [--mode incremental]` | One-shot full pipeline |
| `tg-parser api [--port 8000]` | HTTP API сервер |
| `tg-parser scheduler start` | Daemon-режим scheduler |

---

## LLM конфигурация

```
Processing:  anthropic / claude-haiku-4-5-20251001  (cheap, fast)
Topicization: anthropic / claude-sonnet-4-20250514  (quality)
Per-stage override: PROCESSING_LLM_PROVIDER, TOPICIZATION_LLM_PROVIDER
Rate limiter: token-aware (RPM=1000, ITPM=450K, OTPM=90K)
Concurrency: PROCESSING_CONCURRENCY=20
```

---

## Конфигурация (settings.py, ~80 полей)

Основные группы:
- **Database:** db_type, host/port/name/user/password, pool settings
- **LLM:** provider, model, API keys, per-stage overrides, temperature, max_tokens
- **Processing:** concurrency, retry settings, prompt loader
- **Topicization:** anchor/score thresholds, batch concurrency, token length
- **Ingestion:** Telegram credentials, retry settings
- **API:** auth, rate limiting, CORS, webhooks
- **Scheduler:** intervals, thresholds, max concurrent sources
- **Agents:** persistence, retention, stats
- **Logging:** format, level

---

## Тесты

| Категория | Файлы | Тест-функции |
|-----------|-------|-------------|
| Incremental topicization | 1 | 39 |
| Topicization (full) | 1 | 24 |
| Processing pipeline | 1 | 39 |
| Scheduler service | 1 | 10 |
| E2E pipeline | 1 | 7 |
| Storage integration | 1 | 28 |
| Postgres integration | 1 | 20 |
| Postgres concurrency | 1 | 11 |
| API + security | 2 | 46 |
| Agents (all phases) | 5 | 160 |
| LLM clients/factory/limiter | 3 | 39 |
| Models/IDs | 2 | 19 |
| Migrations | 1 | 8 |
| Prompt loader | 1 | 18 |
| Logging/retry | 2 | 15 |
| Telegram URL/client | 2 | 17 |
| Job storage | 1 | 16 |
| GPT-5 responses | 1 | 9 |
| **Итого** | **29** | **~550** |

Результат последнего запуска: **520 passed, 3 pre-existing failures, 24 skipped**

Pre-existing failures (не связаны с текущей работой):
1. `test_agents.py::test_process_message_with_agent` — APIConnectionError (нет сети/ключа)
2. `test_e2e_pipeline.py::test_full_pipeline_e2e` — mock issue
3. `test_e2e_pipeline.py::test_comments_ingestion_with_per_thread_cursors` — mock issue

---

## Инкрементальная топикизация (Sessions 34-37)

### Flow

```
CLI/Scheduler → find uncovered docs → Phase 1: Keyword Assign (0 tokens)
                                              ↓
                                    ┌─────────┴──────────┐
                                    ↓                    ↓
                              assigned docs         unassigned docs
                              (add to bundles)           ↓
                                               Phase 2: LLM Discover
                                               (~20K tokens per batch)
                                                        ↓
                                           ┌────────────┼─────────────┐
                                           ↓            ↓             ↓
                                   assigned to     new topics     unassignable
                                   existing        created        (logged)
                                   (add to bundles) (+ bundles)
                                                        ↓
                                                Recompute coverage
```

### Результаты на реальных данных

| Этап | Docs | Метод | Coverage после |
|------|------|-------|----------------|
| Baseline (Session 33) | 875 covered | full topicization | 77.4% |
| Phase 1 assign-only | +107 assigned | keyword (0 tokens) | 86.9% |
| Phase 2 incremental | +49 assigned, +3 topics | LLM discover | 92.4% |
| **Итого** | 1044/1130 covered | | **92.4%** |

Discovered topics (Phase 2 LLM):
1. Поздравления и праздничные пожелания (cluster, 3 anchors)
2. Образовательные мероприятия и анонсы (cluster, 3 anchors)
3. Личные достижения в спорте и беге (cluster, 3 anchors)

---

## Что готово к RAG (P5)

### Уже есть
- `KnowledgeBaseEntry.vector: list[float] | None` — поле для embeddings в доменной модели
- KB export: 1130 entries в NDJSON
- 83 темы с описаниями (scope_in, scope_out, summary)
- 92.4% coverage — большинство документов привязаны к темам
- PostgreSQL backend с connection pooling
- LLM factory с поддержкой OpenAI/Anthropic/Gemini

### Что потребуется для P5
- Embeddings generation (OpenAI text-embedding-3-small или аналог)
- Vector storage (pgvector extension или ChromaDB)
- Retrieval pipeline: query → embedding → similarity search → context
- Q&A endpoint в API
- CLI команда для генерации embeddings
- Инкрементальная генерация embeddings (для новых docs)

---

## Известный технический долг

1. **`tokens_used` в IncrementalTopicizeResult** — всегда 0, LLM client не отдаёт usage из API response
2. **Batch splitting** для `--mode incremental` при > 50 unassigned docs — пока все docs в одном запросе
3. **Двойная инициализация Database** в `run_incremental_topicization_for_uncovered` — создаёт db, закрывает, потом `run_incremental_topicization` создаёт снова
4. **Pre-existing test failures** (3 шт.) — mock issues в e2e pipeline и network в agents
5. **`processing/` читает global config** (3 файла) — optional DI уже есть
6. **`api/` и `services/` импортируют конкретные repo** вместо ports — единственная реализация
7. **Repo classes named `SQLite*`** — но работают и с PostgreSQL (исторические имена)

---

## Файлы, изменённые в Sessions 35-37

```
M  tg_parser/domain/models.py                     # TopicAssignment, IncrementalTopicizeResult
M  tg_parser/processing/topicization.py            # Phase 1 + Phase 2 methods
M  tg_parser/processing/topicization_prompts.py    # Incremental discover prompts
M  tg_parser/services/topicization_service.py      # run_incremental_*, _run_assign_only
M  tg_parser/services/scheduler_service.py         # Incremental topicize integration
M  tg_parser/storage/ports.py                      # add_items() on TopicBundleRepo
M  tg_parser/storage/sqlalchemy/topic_bundle_repo.py # add_items() implementation
M  tg_parser/cli/app.py                            # --mode parameter
M  tg_parser/cli/topicize_cmd.py                   # Re-exports
A  tests/test_incremental_topicization.py          # 39 tests
M  tests/test_scheduler_service.py                 # 10 tests (updated)
```

---

## Задачи для code review

### 1. Общее ревью архитектуры
- [ ] Проверить layering: cli → services → processing/storage — нет ли обратных зависимостей?
- [ ] Проверить, что ports (ABC) используются там, где это оправдано
- [ ] Проверить error handling: все ли exceptions обработаны корректно?
- [ ] DRY: есть ли дублирование логики между full и incremental topicization?
- [ ] Проверить: async vs sync — есть ли blocking вызовы в async контексте?

### 2. Аудит Database lifecycle (pre-RAG рефакторинг #1, ~250 строк)

**Цель:** Каталогизировать все места, где создаётся `Database`, открывается `session`, создаются repos и закрываются — для последующего вынесения в `@asynccontextmanager`.

- [ ] Найти все вхождения паттерна `Database.from_settings()` / `Database(...)` в services/
- [ ] Для каждого: записать файл, функцию, какие repos создаются, как закрывается session
- [ ] Выявить случаи двойной инициализации (как в `run_incremental_topicization_for_uncovered`)
- [ ] Определить, какие repos чаще всего создаются вместе (для группировки в context managers)
- [ ] Предложить сигнатуру context manager(ов): один universal или несколько специализированных?

**Ожидаемый выход:** Таблица `{файл, функция, repos, lifecycle_pattern}` + предложение API context manager.

### 3. Аудит инверсии services → api (pre-RAG рефакторинг #2, ~70 строк)

**Цель:** Точно определить что из `api/scheduler.py` переносить в `services/`, и какие импорты обновить.

- [ ] Прочитать `tg_parser/api/scheduler.py` — определить какие классы/функции относятся к бизнес-логике, а какие — к HTTP/API
- [ ] Прочитать `tg_parser/services/scheduler_service.py` — какие импорты из `api/` он использует
- [ ] Определить: какой код остаётся в `api/`, какой уходит в `services/`
- [ ] Список файлов, которые импортируют из `api/scheduler.py` (для обновления путей)

**Ожидаемый выход:** Конкретный план перемещения: `{что, откуда, куда, какие импорты обновить}`.

### 4. Аудит DI в services (инкрементальный рефакторинг #3, ~600 строк)

**Цель:** Подготовить поэтапный план миграции services на dependency injection для repos.

- [ ] Для каждого файла в `services/` — записать какие конкретные repo классы импортируются
- [ ] Определить, какие функции создают repos внутри себя, а какие получают извне
- [ ] Оценить: есть ли уже паттерн DI (через `_wiring.py` или иначе)?
- [ ] Предложить порядок миграции (от простого к сложному): какой сервис мигрировать первым?
- [ ] Определить влияние на тесты: какие `@patch()` заменятся на передачу mock через параметры

**Ожидаемый выход:** Таблица `{сервис, импорты repo, кол-во функций, кол-во тестов, сложность миграции}` + рекомендуемый порядок.

### 5. Ревью тестов
- [ ] Достаточно ли покрытие edge cases?
- [ ] Исправить 3 pre-existing failures?
- [ ] Добавить ли integration test с реальной DB?

### 6. Подготовка к RAG
- [ ] Оценить, как лучше хранить embeddings (pgvector vs отдельное хранилище)
- [ ] Определить, какие данные embed'ить: text_clean, summary, или оба?
- [ ] Спроектировать retrieval pipeline (high-level)

---

## Ожидаемые артефакты сессии

По итогам code review должен быть подготовлен документ `START_PROMPT_SESSION39_PRE_RAG_REFACTORING.md`:

1. **Каталог Database lifecycle** — таблица всех мест с паттерном init/close + API context manager
2. **План инверсии services → api** — конкретные перемещения кода с файлами и строками
3. **План DI миграции** — порядок сервисов, влияние на тесты, рекомендуемый API
4. **Список обнаруженных проблем** — баги, неоптимальности, пропущенный error handling
5. **Рекомендации для RAG** — storage strategy, embedding strategy, retrieval design

Этот документ станет входом для Session 39 (Pre-RAG рефакторинг).

---

## Чего НЕ делаем в этой сессии

- Реализация RAG — только ревью и планирование
- Выполнение рефакторинга — только аудит и подготовка плана
- Рефакторинги, которые ломают API/CLI контракты
- Изменения в production данных
