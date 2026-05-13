# TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

**Версия: 4.3** | [Changelog](CHANGELOG.md) | [Production Deployment](PRODUCTION_DEPLOYMENT.md) | [Server Architecture](docs/SERVER_ARCHITECTURE.md)

> ✅ **Production deployed** — 5 каналов, 5405 документов, 401 тема, 264 cross-channel links | Bot V1.2 deployed | Multi-tenancy (F4) done

## Возможности

**Ядро:**
- **Ingestion** — сбор сообщений и комментариев из Telegram-каналов через Telethon
- **Processing** — обработка через **Multi-LLM**: OpenAI, Anthropic Claude, Google Gemini, Ollama
- **Topicization** — автоматическая кластеризация контента по темам (инкрементальная, кросс-канальная)
- **Embedding + RAG** — семантический поиск и Q&A по базе знаний (pgvector)
- **Cross-channel analytics** — связи между темами из разных каналов (topic links, keyword overlaps)

**Интерфейсы:**
- **MCP Server** — 43 инструмента для AI-агентов (Claude Desktop, Cursor, Claude Code); Streamable HTTP + bearer auth
- **Telegram Bot** — Gemini-powered agent с 24 tools, free-form чат, two-phase confirmation для write-операций
- **REST API** — FastAPI с Auth, Rate Limiting, Webhooks, User Management API, Swagger UI
- **CLI** — Typer CLI для всех операций (ingestion, processing, topicization, export, pipeline, user migration)

**Multi-Tenancy (F4):**
- **User management** — роли (`admin` / `user`), per-user channel limits, auth mappings
- **Channel ownership** — `owner_id` на каждом канале, scoped data access
- **Auth types** — API key (SHA-256), MCP token (SHA-256), Telegram user ID
- **Migration CLI** — `tg-parser migrate-users` для миграции существующих credentials

**Workspaces (F4-B Core):**
- Тематические коллекции каналов внутри одного пользователя (Solo Knowledge Curator UX)
- 8 MCP tools + CLI surface (`tg-parser workspace …`); Bot integration deferred
- Optional `workspace_id` параметр на 8 scoped read-tools (search / ask / list / get) — F4-A backward-compat 100%
- Non-atomic move semantics: `remove_workspace_source` + `add_workspace_source` (O-1 deferred)

**Production:**
- **PostgreSQL + pgvector** — production database с connection pooling
- **Docker Compose** — полный стек: API, MCP, Bot, Prometheus, Grafana
- **Nginx + TLS** — Let's Encrypt auto-renewal, reverse proxy
- **Prometheus + Grafana** — метрики HTTP, LLM, pipeline, scheduler; 2 дашборда
- **Background Scheduler** — автоматический инкрементальный pipeline
- **Structured JSON Logging** — production-ready logs с request_id
- **DB Backups** — daily automated backups с ротацией

## 🚀 Quick Start

### 1. Установка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd TG_parser

# Создать виртуальное окружение
python3.12 -m venv .venv

# Активировать окружение
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Установить зависимости
pip install --upgrade pip
pip install -r requirements.txt

# Установить проект в режиме разработки
pip install -e .
```

### 2. Настройка конфигурации

```bash
# Скопировать пример конфигурации
cp .env.example .env

# Отредактировать .env файл с вашими credentials
```

### 3. Database Setup (PostgreSQL + pgvector)

TG_parser использует **PostgreSQL** с расширением **pgvector** для хранения данных и семантического поиска.

**С Docker Compose (рекомендуется):**

```bash
# Запустить PostgreSQL с pgvector
docker compose up -d postgres

# Настроить в .env:
DB_HOST=localhost   # 'postgres' для Docker network
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=SECURE_PASSWORD_HERE
```

**Без Docker:**

```bash
# Установите PostgreSQL 17+ и pgvector
# Создайте базу данных и пользователя, затем:
psql -U postgres -c "CREATE DATABASE tg_parser;"
psql -U postgres -d tg_parser -c "CREATE EXTENSION vector;"
```

**Connection pool settings** (опционально, defaults работают хорошо):

```env
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
```

#### Database tuning — `max_connections` formula

PostgreSQL `max_connections` (см. `docker-compose.yml`, `command: ["postgres", "-c", "max_connections=200", ...]`) рассчитан под текущий стек как:

```
services × pools_per_service × (DB_POOL_SIZE + DB_MAX_OVERFLOW) < max_connections
3       × 3                 × (10               + 10)              = 180 < 200
```

Где:

- **services** = `tg_parser` (API), `mcp`, `tg_bot` (3 контейнера, делящих один Postgres).
- **pools_per_service** = 3 логические БД (ingestion / raw / processing); каждая использует свой `AsyncEngine` с собственным пулом.
- **DB_POOL_SIZE** + **DB_MAX_OVERFLOW** — env-vars из `.env`/`docker-compose.yml`. Defaults: `10 + 10` для API/MCP, `3 + 5` для bot.

**Когда пересчитывать (и менять `-c max_connections=N` в compose):**

1. Добавляешь новый сервис в `docker-compose.yml`, который ходит в Postgres → `services += 1`.
2. Поднимаешь `DB_POOL_SIZE` или `DB_MAX_OVERFLOW` глобально (например, ради нагрузочных тестов F8-A) → пересчитать формулу.
3. Видишь `psycopg2.OperationalError: FATAL: sorry, too many clients already` или `asyncpg.TooManyConnectionsError` → срочно поднять `max_connections` или урезать пулы.

Headroom 10–20% (180 vs 200) специально оставлен под `psql`-сессии разработчика, backup-job'ы (`pg_dump`) и Postgres internal workers.

См. также: [F8-A Hardening notes](docs/notes/FUTURE_FEATURES.md#f8-a) — план для adaptive pool sizing.

**См. также**: [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) — полный production setup guide

### 4. Получение Telegram API credentials

1. Перейдите на https://my.telegram.org
2. Войдите под своим аккаунтом Telegram
3. Нажмите "API development tools"
4. Создайте приложение (любое имя и описание)
5. Скопируйте `api_id` и `api_hash`
6. Добавьте их в `.env` файл:
   ```env
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   TELEGRAM_PHONE=+79001234567
   ```

### 5. Настройка LLM API (выберите один или несколько)

**v1.2: Multi-LLM поддержка** — OpenAI (+ GPT-5), Anthropic, Gemini, Ollama

```env
# OpenAI (default)
OPENAI_API_KEY=sk-...your-api-key...
LLM_MODEL=gpt-4o-mini  # or gpt-5.2, gpt-5-mini, gpt-5-nano

# GPT-5 specific (v3.1)
LLM_REASONING_EFFORT=low  # minimal/low/medium/high
LLM_VERBOSITY=low         # low/medium/high

# Anthropic Claude (опционально)
ANTHROPIC_API_KEY=sk-ant-...your-key...

# Google Gemini (опционально)
GEMINI_API_KEY=AI...your-key...

# Ollama (локальный, бесплатно)
LLM_BASE_URL=http://localhost:11434
```

**См. также**: [LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md), [ENV_VARIABLES_GUIDE.md](ENV_VARIABLES_GUIDE.md)

**Сравнение провайдеров:**

| Провайдер | Скорость | Качество | Стоимость |
|-----------|----------|----------|-----------|
| **Gemini** | ⚡ Быстрый (0.34 msg/s) | Отличное | Низкая |
| **OpenAI** | Средняя (0.12 msg/s) | Хорошее | Средняя |
| **Anthropic** | Средняя (0.12 msg/s) | Лучшее | Высокая |
| **Ollama** | Медленный (0.02 msg/s) | Хорошее | Бесплатно |

### 6. Первый запуск

```bash
# Инициализация баз данных
python -m tg_parser.cli init

# Добавить источник (канал)
python -m tg_parser.cli add-source --source-id my_channel --channel-id @channel_username

# Запустить полный pipeline одной командой (рекомендуется)
python -m tg_parser.cli run --source my_channel --out ./output
```

При первом запуске ingestion Telethon попросит авторизацию — введите код из Telegram.

## 📖 CLI команды

| Команда | Описание |
|---------|----------|
| `init` | Инициализация БД (Alembic migrations) |
| `auth` | Авторизация Telegram сессии |
| `add-source` | Добавить канал/источник |
| `ingest` | Сбор сообщений из Telegram |
| `process` | Обработка через LLM / Agent |
| `topicize` | Тематизация документов |
| `embed` | Генерация embeddings для поиска |
| `link-topics` | Связывание тем между каналами |
| `search` | Семантический поиск (CLI) |
| `ask` | RAG Q&A (CLI) |
| `export` | Экспорт артефактов |
| `run` | One-shot полный pipeline |
| `api` | Запуск HTTP API сервера |
| `bot` | Запуск Telegram бота |
| `mcp` | Запуск MCP-сервера |
| `scheduler start\|status\|run-once` | Планировщик инкрементальных обновлений |
| `db upgrade\|downgrade\|backup\|...` | Управление базой данных |
| `agents list\|status\|history\|...` | Мониторинг агентов |
| `migrate-users` | Миграция legacy credentials в multi-tenancy |

### `init` — Инициализация БД

Создаёт таблицы через Alembic миграции.

```bash
python -m tg_parser.cli init

# Или напрямую через Alembic
python -m tg_parser.cli db upgrade --db all
```

### `add-source` — Добавление источника

Регистрирует Telegram канал для последующего сбора данных.

```bash
python -m tg_parser.cli add-source --source-id my_source --channel-id @channel_name

# С комментариями
python -m tg_parser.cli add-source --source-id my_source --channel-id @channel_name --include-comments
```

### `ingest` — Сбор сообщений

Собирает raw сообщения из Telegram канала.

```bash
# Инкрементальный сбор (только новые сообщения)
python -m tg_parser.cli ingest --source my_source --mode incremental

# Полный snapshot (все сообщения)
python -m tg_parser.cli ingest --source my_source --mode snapshot

# С ограничением количества
python -m tg_parser.cli ingest --source my_source --limit 100
```

### `process` — Обработка через LLM

Обрабатывает raw сообщения через LLM (v1.2: Multi-LLM, v2.0: Agents).

```bash
# Использовать default провайдер (из .env или openai)
python -m tg_parser.cli process --channel @channel_name

# Выбрать провайдер и модель
python -m tg_parser.cli process --channel @channel_name --provider anthropic --model claude-sonnet-4-20250514
python -m tg_parser.cli process --channel @channel_name --provider gemini --model gemini-2.0-flash-exp
python -m tg_parser.cli process --channel @channel_name --provider ollama --model qwen3:8b

# Параллельная обработка (v1.2) — ускорение в 3-5x для облачных провайдеров
python -m tg_parser.cli process --channel @channel_name --concurrency 5

# Принудительная переобработка
python -m tg_parser.cli process --channel @channel_name --force
```

**Опции v1.2:**
- `--provider` — LLM провайдер: `openai`, `anthropic`, `gemini`, `ollama`
- `--model` — переопределить модель
- `--concurrency` / `-c` — параллельные запросы (default: 1, рекомендуется 3-5 для cloud)

**Опции v2.0 (Agent-based):**
- `--agent` — использовать agent-based processing
- `--agent-llm` — включить LLM-enhanced tools
- `--hybrid` — включить v1.2 pipeline как tool агента (Phase 2E)

**Опции v3.0 (Multi-Agent):**
- `--multi-agent` — использовать Multi-Agent Orchestration (Phase 3A)

```bash
# Agent Basic — быстрая обработка без LLM (~0.3ms/сообщение)
python -m tg_parser.cli process --channel @channel_name --agent

# Agent LLM — глубокий семантический анализ
python -m tg_parser.cli process --channel @channel_name --agent --agent-llm

# Hybrid Mode — agent + v1.2 pipeline tool (адаптивная обработка)
python -m tg_parser.cli process --channel @channel_name --agent --hybrid

# Full Hybrid — LLM agent + pipeline tool (максимальное качество)
python -m tg_parser.cli process --channel @channel_name --agent --agent-llm --hybrid

# Multi-Agent Mode — OrchestratorAgent координирует специализированные агенты (v3.0)
python -m tg_parser.cli process --channel @channel_name --multi-agent
```

| Режим | Скорость | LLM вызовы | Tools | Качество |
|-------|----------|------------|-------|----------|
| Pipeline v1.2 | ~500-2000ms | 1 | N/A | Высокое |
| Agent Basic | **~0.3ms** | 1 | 3 | Среднее |
| Agent LLM | ~500-1500ms | 2+ | 1 | Высокое |
| **Hybrid Basic** | Адаптивно | 1-2 | 4 | Высокое |
| **Hybrid LLM** | Адаптивно | 2-3 | 2 | Лучшее |

> ⚠️ **Ollama**: используйте `--concurrency 1` для локальных моделей

### `topicize` — Тематизация

Кластеризует документы по темам.

```bash
python -m tg_parser.cli topicize --channel @channel_name

# Без формирования bundles
python -m tg_parser.cli topicize --channel @channel_name --no-bundles

# Принудительная переобработка
python -m tg_parser.cli topicize --channel @channel_name --force
```

### `export` — Экспорт артефактов

Экспортирует данные в файлы.

```bash
python -m tg_parser.cli export --channel @channel_name --out ./output

# С фильтрами по дате
python -m tg_parser.cli export --channel @channel_name --from-date 2025-01-01 --to-date 2025-12-31

# Pretty print (форматированный JSON)
python -m tg_parser.cli export --channel @channel_name --out ./output --pretty
```

**Выходные файлы:**
- `kb_entries.ndjson` — записи базы знаний (NDJSON)
- `topics.json` — каталог тем
- `topic_<id>.json` — детальные карточки тем

### `run` — One-shot Pipeline ⭐

Запускает полный pipeline одной командой: ingest → process → topicize → export.

```bash
# Базовый запуск
python -m tg_parser.cli run --source my_channel --out ./output

# С режимом snapshot
python -m tg_parser.cli run --source my_channel --out ./output --mode snapshot

# Пропустить некоторые этапы
python -m tg_parser.cli run --source my_channel --out ./output --skip-ingest
python -m tg_parser.cli run --source my_channel --out ./output --skip-process --skip-topicize

# Force режим (переобработка всех документов)
python -m tg_parser.cli run --source my_channel --out ./output --force

# С ограничением для отладки
python -m tg_parser.cli run --source my_channel --out ./output --limit 10
```

**Опции:**
- `--source` — ID источника (обязательно)
- `--out` — директория вывода (по умолчанию `./output`)
- `--mode` — режим ingestion: `snapshot` или `incremental` (по умолчанию)
- `--skip-ingest` — пропустить этап сбора
- `--skip-process` — пропустить этап обработки
- `--skip-topicize` — пропустить этап тематизации
- `--force` — принудительная переобработка
- `--limit` — лимит сообщений для ingestion

### `api` — HTTP API сервер

Запускает HTTP API сервер для интеграций.

```bash
# Запустить на порту 8000 (по умолчанию)
python -m tg_parser.cli api

# Указать порт и хост
python -m tg_parser.cli api --port 8080 --host 0.0.0.0

# Режим разработки с auto-reload
python -m tg_parser.cli api --reload
```

**API Endpoints:**
- `GET /health` — health check
- `GET /status` — статус системы с компонентами
- `GET /status/detailed` — детальный health check (api_key)
- `GET /scheduler` — статус background scheduler (api_key)
- `GET /metrics` — Prometheus метрики
- `POST /api/v1/process` — запуск обработки
- `GET /api/v1/status/{job_id}` — статус job
- `GET /api/v1/jobs` — список jobs
- `POST /api/v1/export` — запуск экспорта
- `GET /api/v1/export/status/{job_id}` — статус экспорта
- `GET /api/v1/export/download/{job_id}` — скачать результат
- `POST /api/v1/search` — семантический поиск
- `POST /api/v1/ask` — RAG Q&A
- `GET /api/v1/topics` — список тем (пагинация, фильтры)
- `GET /api/v1/topics/{topic_id}` — детали темы
- `GET /api/v1/topics/{topic_id}/bundle` — bundle темы
- `GET /api/v1/channels` — список каналов
- `GET /api/v1/channels/{channel_id}/stats` — статистика канала (owner/admin)
- `GET /api/v1/documents?source_ref=...` — документ по source_ref
- `GET /llm/config` — конфигурация LLM
- `PUT /llm/config` — изменение LLM provider/model (admin)
- `POST /llm/config/reset` — сброс LLM config (admin)
- `GET /api/v1/agents` — список агентов (admin)
- `GET /api/v1/agents/{name}` — детали агента (admin)
- `GET /api/v1/agents/{name}/stats` — статистика агента (admin)
- `GET /api/v1/agents/{name}/history` — история агента (admin)
- `GET /api/v1/agents/stats/handoffs` — статистика handoffs (admin)
- `GET /api/v1/users/me` — профиль текущего пользователя
- `GET /api/v1/users` — список пользователей (admin)
- `POST /api/v1/users` — создание пользователя (admin)
- `PATCH /api/v1/users/{user_id}` — обновление пользователя (admin)
- `DELETE /api/v1/users/{user_id}` — удаление пользователя (admin)

**API Security (Phase 2F):**

```bash
# Включить аутентификацию (.env)
API_KEY_REQUIRED=true
API_KEYS='{"sk-prod-xxx": "production", "sk-dev-yyy": "development"}'

# Настроить rate limits
RATE_LIMIT_PROCESS=10/minute
RATE_LIMIT_EXPORT=20/minute

# Настроить CORS
CORS_ORIGINS='["https://app.example.com"]'
```

```bash
# Пример вызова с аутентификацией и webhook
curl http://localhost:8000/api/v1/process \
  -H "X-API-Key: sk-prod-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "my_channel",
    "webhook_url": "https://myapp.com/webhook"
  }'
```

**Документация API**: http://localhost:8000/docs (Swagger UI)

### `db` — Управление миграциями

Команды для управления миграциями базы данных через Alembic.

```bash
# Применить миграции для всех баз
tg-parser db upgrade --db all

# Применить миграции для конкретной базы
tg-parser db upgrade --db ingestion
tg-parser db upgrade --db raw
tg-parser db upgrade --db processing

# Показать текущую версию схемы
tg-parser db current
tg-parser db current --db ingestion

# История миграций
tg-parser db history --db processing -v

# Откатить миграции (ОСТОРОЖНО!)
tg-parser db downgrade --db raw

# Пометить текущее состояние БД
tg-parser db stamp --db ingestion head
```

**Особенности**:
- Multi-schema support: 3 логические группы таблиц в PostgreSQL
- Отдельные version tables для каждой группы
- Безопасные upgrade/downgrade операции
- Автоматическое применение при `init`

### `migrate-users` — Миграция пользователей (F4)

Одноразовая миграция существующих credentials в мульти-тенантную модель пользователей.

```bash
# Предварительный просмотр (без изменений)
tg-parser migrate-users --dry-run

# Выполнить миграцию
tg-parser migrate-users
```

**Что делает:**
- Создаёт пользователя `admin`
- Маппит `API_KEYS` → `api_key` auth mappings (SHA-256)
- Маппит `MCP_AUTH_TOKENS` → `mcp_token` auth mappings (SHA-256)
- Маппит `BOT_ALLOWED_USERS` → `telegram` auth mappings
- Назначает `owner_id` на каналы без владельца
- Идемпотентна: безопасно запускать повторно

### `agents` — Мониторинг агентов (v3.0)

Команды для мониторинга и управления агентами.

```bash
# Список всех агентов
tg-parser agents list
tg-parser agents list --type processing --active

# Статистика агента
tg-parser agents status ProcessingAgent
tg-parser agents status ProcessingAgent --days 30

# История задач агента
tg-parser agents history ProcessingAgent
tg-parser agents history ProcessingAgent --limit 50 --errors

# Очистка истёкших записей
tg-parser agents cleanup --dry-run
tg-parser agents cleanup --archive
tg-parser agents cleanup --archive --include-handoffs

# Статистика handoff'ов между агентами
tg-parser agents handoffs --stats
tg-parser agents handoffs --agent OrchestratorAgent

# Список архивов
tg-parser agents archives
```

## 📚 Работа с несколькими каналами

TG_parser поддерживает работу с любым количеством Telegram каналов одновременно.

### Хранение данных

**База данных (PostgreSQL)**:
- ✅ Все каналы хранятся **вместе** в одной базе данных
- ✅ При добавлении нового канала данные **добавляются**, а не заменяются
- ✅ Каждый канал идентифицируется по уникальному `channel_id`

**Export файлы**:
- ⚠️ Файлы в директории export **перезаписываются** при каждом запуске
- ✅ **Решение**: используйте разные директории для каждого канала

### Рекомендуемый подход

```bash
# Канал 1
python -m tg_parser.cli run \
  --source channel1 \
  --out ./output_channel1

# Канал 2
python -m tg_parser.cli add-source \
  --source-id channel2 \
  --channel-id @channel2_username

python -m tg_parser.cli run \
  --source channel2 \
  --out ./output_channel2

# Канал 3
python -m tg_parser.cli add-source \
  --source-id channel3 \
  --channel-id @channel3_username

python -m tg_parser.cli run \
  --source channel3 \
  --out ./output_channel3
```

**Результат**:
```
TG_parser/
├── (PostgreSQL)          # Все каналы в одной БД
├── output_channel1/      # Export канала 1
│   ├── kb_entries.ndjson
│   └── topics.json
├── output_channel2/      # Export канала 2
│   ├── kb_entries.ndjson
│   └── topics.json
└── output_channel3/      # Export канала 3
    ├── kb_entries.ndjson
    └── topics.json
```

### Альтернативный подход: раздельный export

```bash
# Собрать и обработать данные всех каналов
python -m tg_parser.cli run --source channel1 --out ./output_channel1
python -m tg_parser.cli run --source channel2 --out ./output_channel2
python -m tg_parser.cli run --source channel3 --out ./output_channel3

# Экспортировать отдельно позже (при необходимости)
python -m tg_parser.cli export --channel channel1_id --out ./output_channel1
python -m tg_parser.cli export --channel channel2_id --out ./output_channel2
python -m tg_parser.cli export --channel channel3_id --out ./output_channel3
```

**Преимущества**:
- Все данные накапливаются в базе данных PostgreSQL
- Export можно делать в любой момент
- Гибкий контроль над выходными файлами

**Подробнее**: См. [`MULTI_CHANNEL_GUIDE.md`](MULTI_CHANNEL_GUIDE.md) для детального руководства.

## 🏗️ Архитектура

```
tg_parser/
├── domain/          # Pydantic v2 модели, ID утилиты, валидация контрактов
├── config/          # Настройки (pydantic-settings)
├── storage/         # Порты репозиториев + PostgreSQL реализации
├── ingestion/       # Telegram ingestion (Telethon)
├── processing/      # LLM обработка и topicization
├── export/          # Формирование экспортных артефактов
├── cli/             # Typer CLI команды (включая agents subcommand)
├── api/             # FastAPI HTTP API (v2.0)
│   └── routes/      # Endpoints: health, process, export, agents
└── agents/          # Multi-Agent Architecture (v3.0)
    ├── base.py          # BaseAgent, AgentCapability, AgentType
    ├── registry.py      # AgentRegistry
    ├── persistence.py   # AgentPersistence layer
    ├── archiver.py      # AgentHistoryArchiver (Phase 3C) ⭐
    ├── orchestrator.py  # OrchestratorAgent
    ├── tools/           # Function tools for agents
    └── specialized/     # ProcessingAgent, TopicizationAgent, ExportAgent
```

### Data Pipeline

```
RawTelegramMessage → ProcessedDocument → (TopicCard/TopicBundle) → KnowledgeBaseEntry
```

### Базы данных (PostgreSQL + pgvector)

Единая PostgreSQL база с логическими группами таблиц:
- **ingestion** — состояние источников, курсоры, статусы каналов
- **raw** — raw сообщения из Telegram
- **processing** — обработанные документы, темы, embeddings, ошибки

## ⚙️ Конфигурация

Все настройки задаются через переменные окружения или `.env` файл.

См. [`.env.example`](.env.example) для полного списка настроек.

### Основные настройки

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `TELEGRAM_API_ID` | Telegram API ID | — |
| `TELEGRAM_API_HASH` | Telegram API Hash | — |
| `TELEGRAM_PHONE` | Номер телефона для авторизации | — |
| `LLM_PROVIDER` | LLM провайдер (v1.2) | `openai` |
| `LLM_MODEL` | Модель LLM | (зависит от провайдера) |
| `OPENAI_API_KEY` | API ключ OpenAI | — |
| `ANTHROPIC_API_KEY` | API ключ Anthropic (v1.2) | — |
| `GEMINI_API_KEY` | API ключ Google Gemini (v1.2) | — |
| `LLM_BASE_URL` | URL для Ollama (v1.2) | `http://localhost:11434` |

### Retry настройки

| Переменная | Описание | По умолчанию | Диапазон |
|------------|----------|--------------|----------|
| `RETRY_MAX_ATTEMPTS` | Максимум попыток retry | `3` | 1-10 |
| `RETRY_BACKOFF_BASE` | Базовая задержка (сек) | `1.0` | 0.1-60.0 |
| `RETRY_BACKOFF_MAX` | Максимальная задержка (сек) | `60.0` | 1.0-300.0 |
| `RETRY_JITTER` | Jitter фактор | `0.3` | 0.0-1.0 |

```env
# Пример: более агрессивный retry
RETRY_MAX_ATTEMPTS=5
RETRY_BACKOFF_BASE=2.0
RETRY_BACKOFF_MAX=120.0
RETRY_JITTER=0.5
```

## Docker

### Production Stack (Docker Compose)

```bash
# Запустить основные сервисы (API + Scheduler + PostgreSQL)
docker compose up -d

# Добавить мониторинг (Prometheus + Grafana)
docker compose --profile monitoring up -d

# Добавить MCP-сервер
docker compose --profile mcp up -d

# Добавить Telegram-бота
docker compose --profile bot up -d

# Добавить reverse proxy (Nginx / Caddy)
docker compose --profile proxy up -d

# Или запустить всё сразу
docker compose --profile monitoring --profile mcp --profile bot --profile proxy up -d
```

### Development

```bash
docker build -t tg_parser .
docker run --rm -v $(pwd)/.env:/app/.env:ro tg_parser --help
```

См. подробнее: [docker-compose.yml](docker-compose.yml), [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)

### Deployment Readiness

**Текущая версия: v4.3 — Production Deployed**

| Компонент | Статус | Примечания |
|-----------|--------|------------|
| API + Scheduler | ✅ Deployed | FastAPI, Prometheus metrics, User Management API |
| MCP Server | ✅ Deployed | Streamable HTTP + bearer auth, 43 tools |
| Telegram Bot | ✅ Deployed | Gemini agent, 24 tools, V1.2 |
| PostgreSQL + pgvector | ✅ Deployed | Connection pooling, embeddings |
| Multi-Tenancy | ✅ Implemented | Roles, channel ownership, auth mappings |
| Nginx + TLS | ✅ Deployed | Let's Encrypt auto-renewal |
| Prometheus + Grafana | ✅ Deployed | 2 дашборда, alerting |

**Production каналы (5405 документов, 401 тема, 264 cross-channel links):**
labdiagnostica_logical, Lab4health, AgeManagment, genotek, LongevityClub

См. подробнее: [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md), [SERVER_ARCHITECTURE.md](docs/SERVER_ARCHITECTURE.md)

## 🧪 Тестирование

```bash
# Все тесты (1266 тестов)
pytest

# С verbose выводом
pytest -v

# Конкретный файл
pytest tests/test_e2e_pipeline.py

# Тесты HTTP API
pytest tests/test_api.py -v

# Тесты Agents
pytest tests/test_agents.py -v

# Тесты Agent Observability (Phase 3C)
pytest tests/test_agents_observability.py -v

# С покрытием
pytest --cov=tg_parser
```

**Test Results**: См. [TESTING_RESULTS_v1.2.md](docs/archive/TESTING_RESULTS_v1.2.md)

### Работа с тестовыми данными

```bash
# Добавить тестовые сообщения (без Telegram, укажите свой канал):
python scripts/add_test_messages.py --channel-id my_dev_channel

# Просмотреть обработанные документы
python scripts/view_processed.py --channel test_channel
```

## 🔧 Разработка

```bash
# Форматирование кода
ruff format .

# Проверка линтером
ruff check .

# Автоисправление
ruff check . --fix
```

## Документация

### Deployment & Operations
- **[Production Deployment](PRODUCTION_DEPLOYMENT.md)** — развёртывание Docker Compose стека
- **[Server Architecture](docs/SERVER_ARCHITECTURE.md)** — описание сервисов на сервере
- **[ENV Variables Guide](ENV_VARIABLES_GUIDE.md)** — полный справочник переменных окружения
- **[LLM Setup Guide](LLM_SETUP_GUIDE.md)** — настройка LLM провайдеров (OpenAI, Anthropic, Gemini, Ollama)

### User Guides
- **[User Guide](docs/USER_GUIDE.md)** — полное руководство с примерами и сценариями
- **[MCP Agent Guide](docs/MCP_AGENT_GUIDE.md)** — справочник для AI-агентов (43 MCP tools, schemas, workflows)
- **[Output Formats](OUTPUT_FORMATS.md)** — форматы выходных файлов (NDJSON, JSON)
- **[Multi-Channel Guide](MULTI_CHANNEL_GUIDE.md)** — работа с несколькими каналами

### Architecture & Design
- **[Data Architecture](docs/DATA_ARCHITECTURE.md)** — таблицы БД, выходные файлы, связи
- **[Data Flow](docs/DATA_FLOW.md)** — поток данных через систему
- **[Architecture](docs/architecture.md)** — архитектура системы, DDL схемы
- **[Pipeline](docs/pipeline.md)** — детали обработки данных
- **[ADRs](docs/adr/)** — архитектурные решения

### Specifications
- **[Technical Requirements](docs/technical-requirements.md)** — технические требования
- **[Business Requirements](docs/business-requirements.md)** — бизнес-требования
- **[Data Contracts](docs/contracts/)** — JSON Schema контракты
- **[MCP Management Spec](docs/mcp-management-tools-spec.md)** — спецификация MCP management tools (historical)

### Development
- **[Roadmap](docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md)** — актуальный план развития
- **[Developer Guide](docs/notes/README.md)** — документация для разработчиков
- **[Documentation Index](docs/archive/DOCUMENTATION_INDEX.md)** — полный индекс документации

## Технологии

- **Python 3.12**
- **Pydantic v2** — валидация данных и настройки
- **SQLAlchemy 2.x + asyncpg** — async хранилище (PostgreSQL)
- **pgvector** — векторные embeddings для семантического поиска
- **Telethon** — Telegram MTProto клиент
- **aiogram 3** — Telegram Bot API framework
- **FastMCP** — Model Context Protocol сервер
- **httpx** — async HTTP клиент для LLM API
- **Typer** — CLI интерфейс
- **FastAPI + Uvicorn** — HTTP API
- **Prometheus + Grafana** — мониторинг
- **Docker Compose** — оркестрация сервисов
- **Nginx** — reverse proxy + TLS (Let's Encrypt)
- **pytest** — тестирование (1266 тестов)

## 🤝 Troubleshooting

### Ошибка авторизации Telethon

```
FloodWaitError: You must wait X seconds
```

Подождите указанное время. Telegram ограничивает частоту запросов авторизации.

### Ошибка API ключа

```
openai.AuthenticationError: Invalid API Key
```

Проверьте правильность `OPENAI_API_KEY` в `.env` файле.

### Пустой вывод при export

Убедитесь, что выполнены все предыдущие этапы:
1. `ingest` — собраны raw сообщения
2. `process` — обработаны через LLM
3. `topicize` — сформированы темы

Используйте команду `run` для автоматического выполнения всех этапов.

### Данные заменяются при работе с несколькими каналами

**Вопрос**: Если работать с другим каналом, данные заменятся?

**Ответ**:
- ✅ **База данных**: данные **НЕ заменяются**, новый канал добавляется к существующим
- ⚠️ **Export файлы**: **заменяются**, если использовать ту же директорию `--out`

**Решение**: Используйте разные директории для каждого канала:
```bash
python -m tg_parser.cli run --source channel1 --out ./output_channel1
python -m tg_parser.cli run --source channel2 --out ./output_channel2
```

Подробнее: [`MULTI_CHANNEL_GUIDE.md`](MULTI_CHANNEL_GUIDE.md)

## 📄 Лицензия

См. [LICENSE](LICENSE)
