# TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

**Версия: 3.1.1** | [Changelog](CHANGELOG.md) | [Migration Guide v2→v3](docs/archive/MIGRATION_GUIDE_v2_to_v3.md) | [Production Deployment](PRODUCTION_DEPLOYMENT.md)

> ✅ **Протестировано на реальном канале** — @BiocodebySechenov (8 постов → processing → export)

## ✨ Возможности

- 📥 **Ingestion** — сбор сообщений и комментариев из Telegram-каналов через Telethon
- 🤖 **Processing** — обработка через **Multi-LLM**: OpenAI, Anthropic Claude, Google Gemini, Ollama
- 🏷️ **Topicization** — автоматическая кластеризация контента по темам
- 📤 **Export** — экспорт в форматах NDJSON/JSON для интеграции с RAG-системами
- ⚡ **Parallel Processing** — параллельная обработка через `--concurrency`
- 🌐 **HTTP API** — REST API с Auth, Rate Limiting, Webhooks (v2.0)
- 🤖 **Agents SDK** — OpenAI Agents с function tools (v2.0)
- 🔄 **Hybrid Mode** — agent + v1.2 pipeline для адаптивной обработки (v2.0)
- 🎭 **Multi-Agent Architecture** — OrchestratorAgent, ProcessingAgent, TopicizationAgent, ExportAgent (v3.0)
- 💾 **Agent State Persistence** — сохранение состояния агентов, истории задач, статистики (v3.0)
- 📊 **Agent Observability** — CLI команды `agents`, API endpoints, архивация истории (v3.0)
- 📈 **Prometheus Metrics** — `/metrics` endpoint для мониторинга (v3.0)
- ⏰ **Background Scheduler** — автоматическая очистка и health checks (v3.0)
- 🗄️ **Alembic Migrations** — версионирование схемы БД (v3.1)
- ⚙️ **Configurable Retry** — настройка retry параметров через ENV (v3.1)
- 📝 **Structured JSON Logging** — production-ready logs с request_id (v3.1)
- 🤖 **GPT-5 Support** — Responses API для gpt-5.* моделей (v3.1)
- 🗄️ **PostgreSQL Support** — production-ready database с connection pooling (v3.1) ⭐ NEW
- 🔄 **SQLite → PostgreSQL Migration** — автоматическая миграция данных (v3.1) ⭐ NEW
- 🐳 **Docker** — полная поддержка Docker и Docker Compose

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
cp env.example .env

# Отредактировать .env файл с вашими credentials
```

### 3. Database Setup (v3.1 PostgreSQL Support)

**Выберите database backend:**

**Option A: SQLite (Development, рекомендуется для начала)**

```env
# В .env файле:
DB_TYPE=sqlite
```

SQLite работает "из коробки", не требует настройки. Идеально для:
- Development и testing
- Single-user usage
- Малые объемы данных (<10K сообщений)

**Option B: PostgreSQL (Production)**

```bash
# 1. Start PostgreSQL с Docker Compose
docker compose up -d postgres

# 2. Configure в .env:
DB_TYPE=postgresql
DB_HOST=localhost  # используйте 'postgres' для Docker network
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=SECURE_PASSWORD_HERE

# Connection pool settings (optional, defaults работают хорошо)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
```

```bash
# 3. Initialize PostgreSQL schema (для новых установок):
DB_PASSWORD=your_password python scripts/init_postgres.py
```

PostgreSQL рекомендуется для:
- Production deployments
- Multi-user/concurrent access
- Большие объемы данных (>10K сообщений)
- Advanced queries и performance

**Новая установка (без данных):**

```bash
# Быстрый старт с PostgreSQL
docker compose up -d postgres
DB_PASSWORD=your_password python scripts/init_postgres.py
# Готово!
```

**Миграция SQLite → PostgreSQL (с данными):**

```bash
# Backup текущих данных
cp *.sqlite backups/

# Запустить migration script
python scripts/migrate_sqlite_to_postgres.py --verify
```

**См. также**: 
- [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) — Production setup guide
- [MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](docs/archive/MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md) — Database migration

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

### `init` — Инициализация БД

Создает SQLite базы данных и таблицы через Alembic миграции (v3.1).

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

**Опции v3.0 (Multi-Agent):** ⭐ NEW
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

# Multi-Agent Mode — OrchestratorAgent координирует специализированные агенты (v3.0) ⭐ NEW
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

### `api` — HTTP API сервер (v2.0) ⭐ NEW

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
- `GET /status/detailed` — детальный health check ⭐ NEW
- `GET /scheduler` — статус background scheduler ⭐ NEW
- `GET /metrics` — Prometheus метрики ⭐ NEW
- `POST /api/v1/process` — запуск обработки
- `GET /api/v1/status/{job_id}` — статус job
- `GET /api/v1/jobs` — список jobs
- `POST /api/v1/export` — запуск экспорта
- `GET /api/v1/export/download/{job_id}` — скачать результат
- `GET /api/v1/agents` — список агентов
- `GET /api/v1/agents/{name}/stats` — статистика агента

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

### `db` — Управление миграциями (v3.1) ⭐ NEW

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
- Multi-database support: 3 независимые SQLite базы
- Отдельные version tables для каждой БД
- Безопасные upgrade/downgrade операции
- Автоматическое применение при `init`

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

**API Endpoints (Agent Observability):**
- `GET /api/v1/agents` — список агентов
- `GET /api/v1/agents/{name}` — информация об агенте
- `GET /api/v1/agents/{name}/stats` — статистика агента
- `GET /api/v1/agents/{name}/history` — история задач
- `GET /api/v1/agents/stats/handoffs` — статистика handoff'ов

## 📚 Работа с несколькими каналами

TG_parser поддерживает работу с любым количеством Telegram каналов одновременно.

### Хранение данных

**Базы данных (SQLite)**:
- ✅ Все каналы хранятся **вместе** в одних и тех же файлах `*.sqlite`
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
├── *.sqlite              # Все каналы вместе
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
# Собрать данные всех каналов (без export)
python -m tg_parser.cli run --source channel1 --skip-export
python -m tg_parser.cli run --source channel2 --skip-export
python -m tg_parser.cli run --source channel3 --skip-export

# Экспортировать отдельно по мере необходимости
python -m tg_parser.cli export --channel channel1_id --out ./output_channel1
python -m tg_parser.cli export --channel channel2_id --out ./output_channel2
python -m tg_parser.cli export --channel channel3_id --out ./output_channel3
```

**Преимущества**:
- Все данные накапливаются в базах данных
- Export можно делать в любой момент
- Гибкий контроль над выходными файлами

**Подробнее**: См. [`MULTI_CHANNEL_GUIDE.md`](MULTI_CHANNEL_GUIDE.md) для детального руководства.

## 🏗️ Архитектура

```
tg_parser/
├── domain/          # Pydantic v2 модели, ID утилиты, валидация контрактов
├── config/          # Настройки (pydantic-settings)
├── storage/         # Порты репозиториев + SQLite реализации
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

### Базы данных (SQLite)

- `ingestion_state.sqlite` — состояние источников и курсоры
- `raw_storage.sqlite` — raw сообщения из Telegram
- `processing_storage.sqlite` — обработанные документы, темы, ошибки

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

### Retry настройки (v3.1) ⭐ NEW

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

## 🐳 Docker (v1.2)

### Быстрый запуск

```bash
# Собрать образ
docker build -t tg_parser:v1.2.0 .

# Запустить команду
docker run --rm -v $(pwd)/.env:/app/.env:ro tg_parser:v1.2.0 --help

# Инициализация
docker run --rm -v $(pwd)/data:/app/data tg_parser:v1.2.0 init
```

### Docker Compose

```bash
# Собрать и запустить
docker-compose build
docker-compose run --rm tg_parser init
docker-compose run --rm tg_parser process --channel @channel --provider gemini -c 5
```

См. подробнее: [docker-compose.yml](docker-compose.yml)

### 🚢 Deployment Readiness

| Версия | Статус | Тип deploy | Примечания |
|--------|--------|------------|------------|
| v3.0.0 | ✅ Released | Dev/Demo | SQLite, 1 user |
| v3.1.0 | ✅ Released | Production | PostgreSQL, multi-user |
| v3.1.1 | ✅ **Текущая** | **Production Tested** | Session 25: 237 постов на 4 каналах |

**Сейчас (v3.1.1)** — **Production Ready** 🎉:
- ✅ Production deployment
- ✅ Multi-user concurrent access
- ✅ PostgreSQL с connection pooling
- ✅ Structured JSON logging
- ✅ GPT-5 models support
- ✅ **Протестировано на реальных каналах** (Session 25)

**Протестированные каналы (Session 25):**
- @durov (46 постов) — технологии/Telegram
- @telegram (50 постов) — официальный канал
- @tproger (43 поста) — IT/программирование
- @habr_com (98 постов) — IT новости

См. подробнее: [DEVELOPMENT_ROADMAP.md](docs/archive/DEVELOPMENT_ROADMAP.md#-deployment-strategy)

## 🧪 Тестирование

```bash
# Все тесты (411 тестов)
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
# Добавить тестовые сообщения (без Telegram)
python scripts/add_test_messages.py

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

## 📚 Документация

**[📖 Полное оглавление документации](docs/archive/DOCUMENTATION_INDEX.md)** ⭐ — навигация по всем 31 документам проекта

### 👤 Руководства пользователя

#### Начало работы
- **[User Guide](docs/USER_GUIDE.md)** — полное руководство с примерами и сценариями
- **[Output Formats](OUTPUT_FORMATS.md)** ⭐ — форматы выходных файлов (NDJSON, JSON), примеры интеграции
- **[Multi-Channel Guide](MULTI_CHANNEL_GUIDE.md)** — как работать с несколькими каналами одновременно

#### Углублённое изучение
- **[Data Architecture](docs/DATA_ARCHITECTURE.md)** ⭐ NEW — архитектура данных: таблицы БД, выходные файлы, связи
- **[Data Flow](docs/DATA_FLOW.md)** — поток данных через систему, диаграммы, схемы
- **[LLM Prompts](docs/LLM_PROMPTS.md)** — документация всех промптов для LLM
- **[Real Channel Test Results](docs/archive/REAL_CHANNEL_TEST_RESULTS.md)** — результаты тестирования на 846 сообщениях

### 📈 Развитие проекта
- **[Development Roadmap](docs/archive/DEVELOPMENT_ROADMAP.md)** ⭐ — план развития v1.1, v1.2, v2.0

### 💻 Техническая документация

#### Архитектура и дизайн
- **[Architecture](docs/architecture.md)** — архитектура системы, DDL схемы баз данных
- **[Pipeline](docs/pipeline.md)** — детали обработки данных (ingestion, processing, topicization)
- **[ADRs](docs/adr/)** — архитектурные решения (4 документа)

#### Требования и спецификации
- **[Technical Requirements](docs/technical-requirements.md)** — технические требования (TR-*)
- **[Business Requirements](docs/business-requirements.md)** — бизнес-требования
- **[Data Contracts](docs/contracts/)** — JSON Schema контракты (5 схем)
- **[Tech Stack](docs/tech-stack.md)** — используемые технологии

#### Configuration & Setup
- **[ENV_VARIABLES_GUIDE.md](ENV_VARIABLES_GUIDE.md)** — полный справочник переменных окружения (v3.1) ⭐ NEW
- **[LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md)** — настройка LLM провайдеров (OpenAI GPT-5, Anthropic, Gemini, Ollama)

#### Для разработчиков
- **[Developer Guide](docs/notes/README.md)** — документация для разработчиков, handoff

## 🛠️ Технологии

- **Python 3.12**
- **Pydantic v2** — валидация данных и настройки
- **SQLAlchemy 2.x + aiosqlite** — async хранилище
- **Telethon** — Telegram MTProto клиент
- **httpx** — async HTTP клиент для LLM API
- **Typer** — CLI интерфейс
- **FastAPI + Uvicorn** — HTTP API (v2.0)
- **OpenAI Agents SDK** — агентный подход (v2.0 PoC)
- **pytest** — тестирование

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
- ✅ **Базы данных (SQLite)**: данные **НЕ заменяются**, новый канал добавляется к существующим
- ⚠️ **Export файлы**: **заменяются**, если использовать ту же директорию `--out`

**Решение**: Используйте разные директории для каждого канала:
```bash
python -m tg_parser.cli run --source channel1 --out ./output_channel1
python -m tg_parser.cli run --source channel2 --out ./output_channel2
```

Подробнее: [`MULTI_CHANNEL_GUIDE.md`](MULTI_CHANNEL_GUIDE.md)

## 📄 Лицензия

См. [LICENSE](LICENSE)
