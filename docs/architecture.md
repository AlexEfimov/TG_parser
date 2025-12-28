# TG_parser – Архитектура

## Цель

TG_parser предназначен для:
- сбора сообщений из Telegram‑каналов;
- обработки и структурирования информации с помощью ИИ;
- пополнения тематической базы знаний.

## Высокоуровневый обзор

Основные подсистемы (MVP‑срез):
- **Ingestion (Telegram)** – получение сырых сообщений из каналов;
- **Processing (LLM)** – очистка текста, нормализация, извлечение структуры и смысловых сущностей;
- **Storage** – сохранение raw/processed артефактов (SQLite → PostgreSQL по мере роста);
- **Access / Export** – в MVP: **CLI‑экспорт** (без HTTP API), далее возможно API/сервисы.

Поток данных (упрощённо, MVP):
Telegram Channel → `RawTelegramMessage` → `ProcessedDocument` (+ `TopicCard`/`TopicBundle`) → **CLI‑экспорт** → `KnowledgeBaseEntry`.

## Архитектурный стиль и правило зависимостей

Поверх слоёв ADR‑0001 используется стиль **Hexagonal / Clean Architecture** (см. ADR‑0004):
- **Домен** (модели/контракты) не зависит от инфраструктуры.
- **Бизнес-логика** ingestion/processing/topicization/export зависит только от домена и портов (интерфейсов).
- **Адаптеры** (Telethon/LLM/DB/CLI) зависят от домена/портов, но не наоборот.

Цель: смена Telegram‑клиента, LLM‑провайдера или СУБД должна требовать замены адаптера, а не переписывания пайплайна (ADR‑0001/0003).

## Модули

### Agents (Multi-Agent Architecture) — Phase 3A ⭐ NEW

Начиная с v3.0.0 система поддерживает **Multi-Agent Architecture** для координированной обработки:

**Компоненты:**
- **BaseAgent** — абстрактный базовый класс для всех агентов
- **AgentRegistry** — центральный реестр для регистрации, поиска и мониторинга агентов
- **OrchestratorAgent** — координатор workflow, управляет handoffs между агентами
- **ProcessingAgent** — специализированный агент для обработки сообщений (Simple/Deep/Auto режимы)
- **TopicizationAgent** — агент для семантической кластеризации
- **ExportAgent** — агент для экспорта данных

**Handoff Protocol:**
- `HandoffRequest` — запрос на передачу задачи между агентами
- `HandoffResponse` — ответ с результатом или ошибкой
- `HandoffStatus` — статусы: PENDING, ACCEPTED, IN_PROGRESS, COMPLETED, FAILED

**Архитектурный паттерн A + C:**
- **A (Specialized Agents)**: каждый этап pipeline имеет свой агент
- **C (Router Pattern)**: внутренняя маршрутизация в ProcessingAgent между Simple/Deep режимами

**CLI интеграция:**
```bash
# Multi-agent mode
tg-parser process --channel test_channel --multi-agent
```

**Структура кода:**
```
tg_parser/agents/
├── base.py           # BaseAgent, AgentCapability, AgentType, Handoff protocol
├── registry.py       # AgentRegistry (регистрация, поиск, статистика)
├── persistence.py    # AgentPersistence (Phase 3B: сохранение состояния)
├── orchestrator.py   # OrchestratorAgent (координация workflow)
└── specialized/
    ├── processing.py    # ProcessingAgent (Simple/Deep/Auto)
    ├── topicization.py  # TopicizationAgent
    └── export.py        # ExportAgent
```

### Agent State Persistence — Phase 3B ⭐ NEW

Начиная с v3.0.0-alpha.2 система поддерживает **сохранение состояния агентов** для восстановления после рестарта и мониторинга:

**Компоненты:**
- **AgentPersistence** — unified слой для работы с persistence
- **AgentStateRepo** — хранение метаданных и статистики агентов
- **TaskHistoryRepo** — полная история задач с TTL (input/output)
- **AgentStatsRepo** — агрегированная статистика по дням
- **HandoffHistoryRepo** — история handoffs между агентами

**Таблицы в processing_storage.sqlite:**
- `agent_states` — состояние агентов (metadata, capabilities, statistics)
- `task_history` — история задач с полным input/output
- `agent_stats` — ежедневная агрегированная статистика
- `handoff_history` — история handoffs

**Настройка:**
```env
AGENT_RETENTION_DAYS=14           # TTL для task_history
AGENT_RETENTION_MODE=delete       # delete | export
AGENT_STATS_ENABLED=true          # агрегированная статистика
AGENT_PERSISTENCE_ENABLED=true    # включить persistence
```

**Использование:**
```python
from tg_parser.agents import AgentPersistence, AgentRegistry
from tg_parser.storage.sqlite import SQLiteAgentStateRepo, SQLiteTaskHistoryRepo

# Создать persistence layer
persistence = AgentPersistence(
    agent_state_repo=SQLiteAgentStateRepo(session_factory),
    task_history_repo=SQLiteTaskHistoryRepo(session_factory),
)

# Registry с persistence
registry = AgentRegistry(persistence=persistence)

# Регистрация с восстановлением статистики
await registry.register_with_persistence(agent)

# Запись задачи
await registry.record_task_completion_with_persistence(
    name="ProcessingAgent",
    task_type="process_message",
    input_data={...},
    output_data={...},
    processing_time_ms=150,
)

# Очистка истёкших записей
await persistence.cleanup_expired_tasks()
```

### Agent Observability — Phase 3C ⭐ NEW

Начиная с v3.0.0-alpha.3 система предоставляет **CLI и API инструменты для мониторинга агентов**:

**CLI группа `agents`:**
```bash
# Список агентов
tg-parser agents list
tg-parser agents list --type processing --active

# Статистика агента
tg-parser agents status ProcessingAgent --days 30

# История задач
tg-parser agents history ProcessingAgent --limit 50 --errors

# Очистка с архивацией
tg-parser agents cleanup --archive --include-handoffs

# Статистика handoff'ов
tg-parser agents handoffs --stats
```

**API Endpoints:**
- `GET /api/v1/agents` — список агентов
- `GET /api/v1/agents/{name}` — информация об агенте
- `GET /api/v1/agents/{name}/stats` — статистика за период
- `GET /api/v1/agents/{name}/history` — история задач
- `GET /api/v1/agents/stats/handoffs` — статистика handoff'ов

**AgentHistoryArchiver:**
- Архивация истёкших записей в NDJSON.gz
- Поддержка task_history и handoff_history
- Автоматическая очистка после архивации

**Структура кода:**
```
tg_parser/agents/
├── archiver.py       # AgentHistoryArchiver (экспорт в NDJSON.gz)
...

tg_parser/cli/
├── agents_cmd.py     # CLI группа agents (list, status, history, cleanup, handoffs, archives)
...

tg_parser/api/routes/
├── agents.py         # API endpoints для observability
...
```

### Ingestion (Telegram)
- Интеграция с Telegram API/клиентом.
- Планирование и повторный запуск задач сбора.
- Дедупликация и идемпотентность.
- Выходные данные: объекты `RawTelegramMessage` (см. `docs/contracts/raw_telegram_message.schema.json`).

### Processing / LLM
- Препроцессинг сообщений (очистка, нормализация, разбиение).
- Запросы к LLM/классификаторам (MVP: **облачный LLM**, провайдер выбирается пользователем через конфигурацию; см. `docs/tech-stack.md`).
- Формирование структурированных `ProcessedDocument`.
- Внутри этапа II выделяется отдельная доменная операция **topicization** (TR‑27..TR‑37): формирование `TopicCard` и `TopicBundle` по набору `ProcessedDocument`.

### Storage
- В MVP хранит raw/processed артефакты (SQLite → PostgreSQL по мере роста).
- `KnowledgeBaseEntry` в MVP формируется на этапе **экспорта** (CLI), а не обязательно хранится как отдельная таблица/сущность.
- При добавлении поиска/серверного режима возможны индексы (например, полнотекстовый/векторный).

### Access / Export
- В MVP интерфейс доступа — CLI‑экспорт (без HTTP API) (см. TR‑55..TR‑64).

### Observability и управление
- Логирование ключевых шагов пайплайна.
- Метрики (объём, задержка, ошибки).
- Конфигурация моделей, лимитов Telegram, параметров шедулера.

## Ключевые инварианты и идемпотентность

Источник истины по инвариантам — `docs/technical-requirements.md` (TR‑IF‑*), ниже — обязательные правила, которые влияют на проектирование кода и хранилищ:

- **Единый ключ материала**: `source_ref` — канонический идентификатор материала (TR‑IF‑5, схемы `raw_telegram_message`/`processed_document`/`topic_*`). Таблицы, индексы и дедупликация строятся вокруг `source_ref`, а не вокруг “голого” `message_id`.
- **Raw snapshot**: raw‑хранилище — снимок на момент ingestion; не допускается “тихая” перезапись полей `text/date` при совпадающем `source_ref` (TR‑8).
- **Атомарность курсоров ingestion**: курсоры (`last_post_id`, per‑post `last_comment_id`) обновляются только после успешной записи raw (TR‑10).
- **Processing 1→1**: `RawTelegramMessage` порождает ровно один “актуальный” `ProcessedDocument` (TR‑21/22), upsert по `source_ref`.
- **Детерминированные id**:
  - `ProcessedDocument.id = "doc:" + source_ref` (TR‑41);
  - `TopicCard.id = "topic:" + anchors[0].anchor_ref` (TR‑IF‑4);
  - экспортные `KnowledgeBaseEntry.id` детерминированы правилами TR‑61.
- **Детерминизм topicization**: сортировка anchors и tie‑break по `anchor_ref` (TR‑IF‑4), чтобы повторные прогоны не “плодили” новые темы.

## Маппинг на кодовую структуру проекта

Рекомендуемая структура пакетов (соответствует выбранному стилю и текущему skeleton):

- `tg_parser/domain/` — доменные модели (Pydantic v2) и функции канонизации идентификаторов (`source_ref`, `anchor_ref`, правила `doc:/topic:/kb:`).
- `tg_parser/config/` — конфигурация (`pydantic-settings`): пути БД, параметры ретраев, LLM провайдер/модель/base_url, лимиты.
- `tg_parser/ingestion/` — порты ingestion + адаптер `ingestion.telegram` (Telethon) + оркестрация режимов backfill/online.
- `tg_parser/processing/` — порты processing + LLM адаптеры + topicization (как часть stage II).
- `tg_parser/storage/` — порты репозиториев и реализации для SQLite/PostgreSQL (SQLAlchemy 2.x async).
- `tg_parser/cli/` — команды Typer: ingestion/processing/topicization/export/one-shot (MVP).

## Модель хранения (SQLite, MVP)

Источник истины по хранилищам — ADR‑0003 и TR‑14/TR‑17/TR‑42/TR‑43. Здесь фиксируем практическую модель “какие сущности где живут” (без жёсткой привязки к конкретным именам таблиц, но с обязательными ключами):

- **`ingestion_state.sqlite`**
  - *назначение*: конфигурация источников, статусы, курсоры, история попыток (TR‑14/TR‑15)
  - *ключи/инварианты*:
    - источник идентифицируется `source_id`/`channel_id`
    - статусы `active/paused/error`
    - курсоры: `last_post_id`, и per‑post курсор комментариев `thread_id -> last_comment_id` (TR‑7/TR‑15)

- **`raw_storage.sqlite`**
  - *назначение*: хранение `RawTelegramMessage` (TR‑18..TR‑20)
  - *ключи/инварианты*:
    - UNIQUE/PK по `source_ref` (TR‑18, TR‑IF‑5)
    - поведение при повторной записи: идемпотентный upsert без “тихой” перезаписи raw‑снимка (TR‑8)
    - `raw_payload` может быть ограничен по размеру (TR‑20)

- **`processing_storage.sqlite`**
  - *назначение*: хранение результатов stage II: `ProcessedDocument`, `TopicCard`, `TopicBundle` (TR‑42..TR‑45)
  - *ключи/инварианты*:
    - `ProcessedDocument`: UNIQUE по `source_ref` (TR‑22/TR‑43)
    - `TopicCard`: PK по `id` (TR‑43), где `id` детерминирован (TR‑IF‑4)
    - `TopicBundle`: UNIQUE по `topic_id` (TR‑43) и upsert по `topic_id` в MVP

Примечание: сложные поля (`metadata`, массивы topics/entities/anchors/items) допускается хранить как JSON/Text в SQLite (TR‑43).

## Целевая минимальная схема таблиц (SQLite, MVP)

Ниже — **минимальная целевая схема** таблиц для трёх SQLite‑файлов. Это “контракт реализации” для слоя хранения: имена таблиц и набор полей могут расширяться, но **ключи идемпотентности/UNIQUE‑ограничения и смысл полей должны сохраняться**.

JSON‑поля:
- хранятся как `TEXT` (JSON string) или `JSON` (если используется SQLite JSON1);
- сериализация должна быть стабильной (для тестов/диффов) и совместимой с Pydantic v2.

Временные поля:
- все `*_at`, `date`, `history_from/history_to`, `rate_limit_until`, `time_from/time_to` хранятся как `TEXT` в ISO 8601 (UTC, например `2025-12-13T10:00:00Z`), чтобы совпадать с контрактами JSON Schema (`format: date-time`).

### DDL-шаблоны (как ориентир)

Ниже приведены укороченные DDL‑шаблоны для реализации. Они не обязаны совпасть посимвольно с кодом миграций, но должны обеспечить те же ключи/UNIQUE/индексы.

**`ingestion_state.sqlite`**

```sql
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  channel_username TEXT,
  status TEXT NOT NULL,
  include_comments INTEGER NOT NULL,
  history_from TEXT,
  history_to TEXT,
  poll_interval_seconds INTEGER,
  batch_size INTEGER,
  last_post_id TEXT,
  backfill_completed_at TEXT,
  last_attempt_at TEXT,
  last_success_at TEXT,
  fail_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  rate_limit_until TEXT,
  comments_unavailable INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sources_status_idx ON sources(status);
CREATE INDEX IF NOT EXISTS sources_channel_id_idx ON sources(channel_id);

CREATE TABLE IF NOT EXISTS comment_cursors (
  source_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  last_comment_id TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (source_id, thread_id)
);

CREATE INDEX IF NOT EXISTS comment_cursors_thread_idx ON comment_cursors(thread_id);

CREATE TABLE IF NOT EXISTS source_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  attempt_at TEXT NOT NULL,
  success INTEGER NOT NULL,
  error_class TEXT,
  error_message TEXT,
  details_json TEXT
);

CREATE INDEX IF NOT EXISTS source_attempts_source_time_idx
ON source_attempts(source_id, attempt_at);
```

**`raw_storage.sqlite`**

```sql
CREATE TABLE IF NOT EXISTS raw_messages (
  source_ref TEXT PRIMARY KEY,
  id TEXT NOT NULL,
  message_type TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  date TEXT NOT NULL,
  text TEXT NOT NULL,
  thread_id TEXT,
  parent_message_id TEXT,
  language TEXT,
  raw_payload_json TEXT,
  raw_payload_truncated INTEGER NOT NULL DEFAULT 0,
  raw_payload_original_size_bytes INTEGER,
  inserted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS raw_messages_channel_date_idx ON raw_messages(channel_id, date);
CREATE INDEX IF NOT EXISTS raw_messages_thread_idx ON raw_messages(thread_id);
CREATE INDEX IF NOT EXISTS raw_messages_type_idx ON raw_messages(message_type);

-- TR-8: журнал коллизий/наблюдений при повторном ingestion
CREATE TABLE IF NOT EXISTS raw_conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_ref TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  reason TEXT NOT NULL,
  new_payload_json TEXT,
  new_text TEXT,
  new_date TEXT
);

CREATE INDEX IF NOT EXISTS raw_conflicts_source_time_idx
ON raw_conflicts(source_ref, observed_at);
```

**`processing_storage.sqlite`**

```sql
CREATE TABLE IF NOT EXISTS processed_documents (
  source_ref TEXT PRIMARY KEY,
  id TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  processed_at TEXT NOT NULL,
  text_clean TEXT NOT NULL,
  summary TEXT,
  topics_json TEXT,
  entities_json TEXT,
  language TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS processed_documents_channel_idx ON processed_documents(channel_id);
CREATE INDEX IF NOT EXISTS processed_documents_processed_at_idx ON processed_documents(processed_at);

-- TR-47: журнал неудачной обработки per-message
CREATE TABLE IF NOT EXISTS processing_failures (
  source_ref TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  last_attempt_at TEXT NOT NULL,
  error_class TEXT,
  error_message TEXT,
  error_details_json TEXT
);

CREATE INDEX IF NOT EXISTS processing_failures_channel_idx ON processing_failures(channel_id);
CREATE INDEX IF NOT EXISTS processing_failures_last_attempt_idx ON processing_failures(last_attempt_at);

CREATE TABLE IF NOT EXISTS topic_cards (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  scope_in_json TEXT NOT NULL,
  scope_out_json TEXT NOT NULL,
  type TEXT NOT NULL,
  anchors_json TEXT NOT NULL,
  sources_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  tags_json TEXT,
  related_topics_json TEXT,
  status TEXT,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS topic_cards_updated_at_idx ON topic_cards(updated_at);

CREATE TABLE IF NOT EXISTS topic_bundles (
  topic_id TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  time_from TEXT,
  time_to TEXT,
  items_json TEXT NOT NULL,
  channels_json TEXT,
  metadata_json TEXT,
  UNIQUE(topic_id, time_from, time_to)
);

-- MVP: "одна актуальная подборка на тему"
CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_current_unique_idx
ON topic_bundles(topic_id)
WHERE time_from IS NULL AND time_to IS NULL;

-- ============================================================================
-- Agent State Persistence (Phase 3B)
-- ============================================================================

-- Agent states (metadata, statistics, lifecycle)
CREATE TABLE IF NOT EXISTS agent_states (
  name TEXT PRIMARY KEY,
  agent_type TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '1.0.0',
  description TEXT,
  capabilities_json TEXT NOT NULL,
  model TEXT,
  provider TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT,
  total_tasks_processed INTEGER NOT NULL DEFAULT 0,
  total_errors INTEGER NOT NULL DEFAULT 0,
  avg_processing_time_ms REAL NOT NULL DEFAULT 0.0,
  last_used_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS agent_states_type_idx ON agent_states(agent_type);
CREATE INDEX IF NOT EXISTS agent_states_active_idx ON agent_states(is_active);

-- Task execution history (full input/output with TTL)
CREATE TABLE IF NOT EXISTS task_history (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  task_type TEXT NOT NULL,
  source_ref TEXT,
  channel_id TEXT,
  input_json TEXT NOT NULL,
  output_json TEXT,
  success INTEGER NOT NULL DEFAULT 1,
  error TEXT,
  processing_time_ms INTEGER,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  FOREIGN KEY (agent_name) REFERENCES agent_states(name)
);

CREATE INDEX IF NOT EXISTS task_history_agent_idx ON task_history(agent_name);
CREATE INDEX IF NOT EXISTS task_history_channel_idx ON task_history(channel_id);
CREATE INDEX IF NOT EXISTS task_history_created_idx ON task_history(created_at DESC);
CREATE INDEX IF NOT EXISTS task_history_expires_idx ON task_history(expires_at);

-- Aggregated agent statistics by day
CREATE TABLE IF NOT EXISTS agent_stats (
  agent_name TEXT NOT NULL,
  date TEXT NOT NULL,
  task_type TEXT NOT NULL,
  total_tasks INTEGER NOT NULL DEFAULT 0,
  successful_tasks INTEGER NOT NULL DEFAULT 0,
  failed_tasks INTEGER NOT NULL DEFAULT 0,
  total_processing_time_ms INTEGER NOT NULL DEFAULT 0,
  min_processing_time_ms INTEGER,
  max_processing_time_ms INTEGER,
  PRIMARY KEY (agent_name, date, task_type)
);

CREATE INDEX IF NOT EXISTS agent_stats_agent_idx ON agent_stats(agent_name);
CREATE INDEX IF NOT EXISTS agent_stats_date_idx ON agent_stats(date DESC);

-- Handoff history between agents
CREATE TABLE IF NOT EXISTS handoff_history (
  id TEXT PRIMARY KEY,
  source_agent TEXT NOT NULL,
  target_agent TEXT NOT NULL,
  task_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'in_progress', 'completed', 'failed', 'rejected')),
  payload_json TEXT,
  context_json TEXT,
  result_json TEXT,
  error TEXT,
  processing_time_ms INTEGER,
  created_at TEXT NOT NULL,
  accepted_at TEXT,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS handoff_history_source_idx ON handoff_history(source_agent);
CREATE INDEX IF NOT EXISTS handoff_history_target_idx ON handoff_history(target_agent);
CREATE INDEX IF NOT EXISTS handoff_history_status_idx ON handoff_history(status);
CREATE INDEX IF NOT EXISTS handoff_history_created_idx ON handoff_history(created_at DESC);
```

### `ingestion_state.sqlite` (состояние ingestion)

**1) `sources`** — “шапка” источника (TR‑15):
- `source_id TEXT PRIMARY KEY` — идентификатор источника (в MVP допускается = `channel_id`)
- `channel_id TEXT NOT NULL` — исходный идентификатор канала/чата
- `channel_username TEXT` — опционально, для генерации URL на экспорте (TR‑65)
- `status TEXT NOT NULL` — enum: `active|paused|error` (TR‑11)
- `include_comments INTEGER NOT NULL` — 0/1 (TR‑5)
- `history_from TEXT` — ISO date-time
- `history_to TEXT` — ISO date-time
- `poll_interval_seconds INTEGER`
- `batch_size INTEGER`
- `last_post_id TEXT` — high-watermark постов (TR‑7)
- `backfill_completed_at TEXT` — ISO date-time
- `last_attempt_at TEXT` — ISO date-time
- `last_success_at TEXT` — ISO date-time
- `fail_count INTEGER NOT NULL DEFAULT 0`
- `last_error TEXT`
- `rate_limit_until TEXT` — ISO date-time (TR‑15)
- `comments_unavailable INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT NOT NULL` — ISO date-time
- `updated_at TEXT NOT NULL` — ISO date-time

Индексы:
- `INDEX sources_status_idx(status)`
- `INDEX sources_channel_id_idx(channel_id)`

**2) `comment_cursors`** — per‑post курсоры комментариев (TR‑7/TR‑15):
- `source_id TEXT NOT NULL` — FK → `sources.source_id`
- `thread_id TEXT NOT NULL`
- `last_comment_id TEXT`
- `updated_at TEXT NOT NULL`
- `PRIMARY KEY (source_id, thread_id)`

Индексы:
- `INDEX comment_cursors_thread_idx(thread_id)`

**3) `source_attempts`** — история попыток/ошибок (для observability, TR‑11/TR‑15):
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `source_id TEXT NOT NULL`
- `attempt_at TEXT NOT NULL`
- `success INTEGER NOT NULL` — 0/1
- `error_class TEXT`
- `error_message TEXT`
- `details_json TEXT` — JSON

Индексы:
- `INDEX source_attempts_source_time_idx(source_id, attempt_at)`

### `raw_storage.sqlite` (raw сообщения)

**1) `raw_messages`** — снимок `RawTelegramMessage` (TR‑18..TR‑20):
- `source_ref TEXT PRIMARY KEY` — `tg:<channel_id>:<message_type>:<id>` (TR‑IF‑5)
- `id TEXT NOT NULL` — `RawTelegramMessage.id`
- `message_type TEXT NOT NULL` — enum: `post|comment`
- `channel_id TEXT NOT NULL`
- `date TEXT NOT NULL` — ISO date-time (UTC)
- `text TEXT NOT NULL`
- `thread_id TEXT` — TR‑6
- `parent_message_id TEXT` — TR‑6
- `language TEXT`
- `raw_payload_json TEXT` — JSON (может быть усечённым, TR‑20)
- `raw_payload_truncated INTEGER NOT NULL DEFAULT 0`
- `raw_payload_original_size_bytes INTEGER`
- `inserted_at TEXT NOT NULL`

Индексы:
- `INDEX raw_messages_channel_date_idx(channel_id, date)`
- `INDEX raw_messages_thread_idx(thread_id)`
- `INDEX raw_messages_type_idx(message_type)`

Правило TR‑8 (“raw snapshot”):
- при конфликте по `source_ref` **нельзя** перезаписывать `text/date` “тихо”.
- минимальная реализация: `INSERT ... ON CONFLICT(source_ref) DO NOTHING`.

**2) `raw_conflicts`** — журнал коллизий/наблюдений при повторном ingestion (реализация TR‑8):
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `source_ref TEXT NOT NULL` — FK-like ссылка на `raw_messages.source_ref`
- `observed_at TEXT NOT NULL`
- `reason TEXT NOT NULL` — например `duplicate_seen|content_mismatch|payload_truncated`
- `new_payload_json TEXT` — JSON (best-effort)
- `new_text TEXT`
- `new_date TEXT`

Индексы:
- `INDEX raw_conflicts_source_time_idx(source_ref, observed_at)`

### `processing_storage.sqlite` (stage II: processed + topics)

**1) `processed_documents`** — текущее “актуальное” состояние processed (TR‑22/TR‑43):
- `source_ref TEXT PRIMARY KEY`
- `id TEXT NOT NULL` — `doc:` + `source_ref` (TR‑41)
- `source_message_id TEXT NOT NULL`
- `channel_id TEXT NOT NULL`
- `processed_at TEXT NOT NULL`
- `text_clean TEXT NOT NULL`
- `summary TEXT`
- `topics_json TEXT` — JSON array of strings
- `entities_json TEXT` — JSON array
- `language TEXT`
- `metadata_json TEXT` — JSON (pipeline_version/model_id/prompt_id/parameters, TR‑23/TR‑38..TR‑40)

Индексы:
- `INDEX processed_documents_channel_idx(channel_id)`
- `INDEX processed_documents_processed_at_idx(processed_at)`

**1a) `processing_failures`** — журнал неудачной обработки (TR‑47):

Назначение: хранить “что не обработалось” для CLI‑отчётов и отладки, не нарушая idempotency `processed_documents`.

- `source_ref TEXT PRIMARY KEY`
- `channel_id TEXT NOT NULL`
- `attempts INTEGER NOT NULL`
- `last_attempt_at TEXT NOT NULL`
- `error_class TEXT`
- `error_message TEXT`
- `error_details_json TEXT` — JSON (stacktrace/response codes и т.п., best-effort)

Индексы:
- `INDEX processing_failures_channel_idx(channel_id)`
- `INDEX processing_failures_last_attempt_idx(last_attempt_at)`

Семантика:
- запись создаётся/обновляется при исчерпании попыток per-message (TR‑47);
- при успешной обработке `ProcessedDocument` соответствующая запись в `processing_failures` должна удаляться (или помечаться resolved) — выбор реализации, но состояние “не обработано” должно быть однозначно определяемо.

**2) `topic_cards`** — текущее “актуальное” состояние карточки темы (TR‑43):
- `id TEXT PRIMARY KEY` — `topic:` + primary `anchor_ref` (TR‑IF‑4)
- `title TEXT NOT NULL`
- `summary TEXT NOT NULL`
- `scope_in_json TEXT NOT NULL` — JSON array
- `scope_out_json TEXT NOT NULL` — JSON array
- `type TEXT NOT NULL` — enum: `singleton|cluster`
- `anchors_json TEXT NOT NULL` — JSON array (уникальность по `anchor_ref` обеспечивается кодом/тестами, см. примечание TR‑204)
- `sources_json TEXT NOT NULL` — JSON array
- `updated_at TEXT NOT NULL`
- `tags_json TEXT`
- `related_topics_json TEXT`
- `status TEXT`
- `metadata_json TEXT`

Индексы:
- `INDEX topic_cards_updated_at_idx(updated_at)`

**3) `topic_bundles`** — текущее “актуальное” состояние подборки по теме (TR‑43):
- `topic_id TEXT NOT NULL` — FK-like ссылка на `topic_cards.id`
- `updated_at TEXT NOT NULL`
- `time_from TEXT` — ISO date-time (nullable)
- `time_to TEXT` — ISO date-time (nullable)
- `items_json TEXT NOT NULL` — JSON array (`TopicBundle.items`)
- `channels_json TEXT` — JSON array
- `metadata_json TEXT`

Индексы / ограничения:
- базовый вариант: `UNIQUE(topic_id, time_from, time_to)` (включая snapshot‑режим, если `time_range` задан)
- для MVP “одна актуальная подборка на тему” рекомендуется также **partial unique index**:
  - `UNIQUE(topic_id) WHERE time_from IS NULL AND time_to IS NULL`

Примечание по семантике:
- `TopicBundle.items[]` должны дедуплицироваться по `source_ref` в коде (TR‑36), в БД это хранится как JSON.

## Нефункциональные требования (сводка)

- Источник истины по NFR и наблюдаемости — `docs/technical-requirements.md` (раздел TR‑NF‑* и TR‑OBS‑*). Ниже — краткая сводка:
  - Масштабируемость по числу каналов и объёму истории.
  - Минимизация потерь сообщений (надёжная обработка ошибок и ретраи).
  - Прозрачность работы: логи, метрики, возможность аудита источников.
  - Чёткие интерфейсы между модулями (контракты в `docs/contracts/`).

## Связанные документы

- ADR: `docs/adr/0001-overall-architecture.md`, `docs/adr/0002-telegram-ingestion-approach.md`, `docs/adr/0003-storage-and-indexing.md`, `docs/adr/0004-hexagonal-architecture-and-module-boundaries.md`
- Стек технологий: `docs/tech-stack.md`
- Технические требования: `docs/technical-requirements.md`


