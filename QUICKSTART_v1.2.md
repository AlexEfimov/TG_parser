# Quick Start Guide: TG_parser v3.1.1 Production Tested

> **ARCHIVED — do not use.** This guide targets SQLite-era TG_parser (v3.1.1, Dec 2025).
> Use instead:
> - [README.md](README.md) Quick Start
> - [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) (Wave 1.5 user paths)
> - [docs/guides/SELF_HOST.md](docs/guides/SELF_HOST.md) (operator checklist)

**Обновлено:** 30 декабря 2025

> ✅ **Протестировано на реальном канале** — @BiocodebySechenov

**Новое в v3.1.1:**
- ✅ **Реальное тестирование** — полный pipeline на живом канале
- ✅ **CLI PostgreSQL Ready** — все команды работают с PostgreSQL
- ✅ 411 Tests (100% pass rate)

**v3.1.0:**
- ✅ **PostgreSQL Support** — production-grade database с connection pooling
- ✅ **Multi-user Ready** — concurrent access, horizontal scaling
- ✅ **Production Docker** — docker-compose с PostgreSQL
- ✅ Structured JSON Logging
- ✅ GPT-5 Support (gpt-5.2, gpt-5-mini, gpt-5-nano)
- ✅ Configurable Retry Settings
- ✅ **Production Ready** для enterprise deployment

## 🚀 5-минутная настройка

### 1. Установка

```bash
# Клонируйте репозиторий
git clone <repo-url>
cd TG_parser

# Создайте виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate  # Windows

# Установите зависимости
pip install -r requirements.txt
pip install -e .
```

### 2. Настройка API ключей

```bash
# Скопируйте пример конфигурации
cp .env.example .env

# Откройте .env и добавьте API ключи
# Минимум нужен один из:
# - OPENAI_API_KEY (получить на platform.openai.com) - для GPT-4o, GPT-5
# - ANTHROPIC_API_KEY (получить на console.anthropic.com) - для Claude
# - GEMINI_API_KEY (получить на aistudio.google.com) - для Gemini
# - Или используйте Ollama (бесплатно, локально)

# Опционально: настройте логирование (для production)
LOG_FORMAT=json  # или text для development
LOG_LEVEL=INFO   # или DEBUG для troubleshooting

# Опционально: PostgreSQL для production (v3.1.0) ⭐ NEW
DB_TYPE=postgresql  # или sqlite (default)
DB_HOST=postgres
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=SECURE_PASSWORD_HERE
```

### 2.5. Database Setup (v3.1.0) ⭐ NEW

**Option A: SQLite (Development, Default)**
```bash
# SQLite работает из коробки, не требует настройки
DB_TYPE=sqlite  # default
```

**Option B: PostgreSQL (Production)**
```bash
# 1. Start PostgreSQL
docker compose up -d postgres

# 2. В .env:
DB_TYPE=postgresql
DB_HOST=postgres
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=SECURE_PASSWORD_HERE
```

**Guides:**
- 📖 [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)
- 🚀 [MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md)

### 3. Инициализация

```bash
# Создайте базы данных (SQLite или PostgreSQL)
python -m tg_parser.cli init
```

### 4. Использование

```bash
# Добавьте источник (Telegram канал)
python -m tg_parser.cli add-source \
  --source-id my_channel \
  --channel-id 1234567890

# Соберите сообщения
python -m tg_parser.cli ingest --source my_channel

# Обработайте через LLM (выберите провайдера)
python -m tg_parser.cli process --channel my_channel --provider openai
# или
python -m tg_parser.cli process --channel my_channel --provider anthropic
# или
python -m tg_parser.cli process --channel my_channel --provider gemini
# или (локально, бесплатно)
python -m tg_parser.cli process --channel my_channel --provider ollama

# Экспортируйте результаты
python -m tg_parser.cli export --out ./output
```

---

## ⚡ Быстрые команды v3.1

### Multi-LLM Support

```bash
# OpenAI GPT-4o (default)
python -m tg_parser.cli process --channel my_channel

# GPT-5 (v3.1) ⭐ NEW
python -m tg_parser.cli process --channel my_channel \
  --provider openai \
  --model gpt-5.2  # или gpt-5-mini, gpt-5-nano

# GPT-5 с настройками reasoning
LLM_REASONING_EFFORT=high LLM_VERBOSITY=medium \
  python -m tg_parser.cli process --channel my_channel --model gpt-5.2

# Anthropic Claude (рекомендуется для production)
python -m tg_parser.cli process --channel my_channel \
  --provider anthropic \
  --model claude-sonnet-4-20250514

# Google Gemini (самый быстрый и дешёвый)
python -m tg_parser.cli process --channel my_channel \
  --provider gemini \
  --model gemini-2.0-flash-exp

# Ollama (бесплатно, локально)
python -m tg_parser.cli process --channel my_channel \
  --provider ollama \
  --model llama3.2
```

### JSON Logging (v3.1) ⭐ NEW

```bash
# Development (human-readable)
LOG_FORMAT=text LOG_LEVEL=DEBUG \
  python -m tg_parser.cli process --channel my_channel

# Production (structured JSON)
LOG_FORMAT=json LOG_LEVEL=INFO \
  python -m tg_parser.cli process --channel my_channel

# Фильтрация JSON логов
LOG_FORMAT=json python -m tg_parser.cli process --channel my_channel 2>&1 | \
  jq 'select(.level == "error")'
```

### PostgreSQL Support (v3.1.0) ⭐ NEW

```bash
# Development: SQLite (default)
DB_TYPE=sqlite python -m tg_parser.cli process --channel my_channel

# Production: PostgreSQL
docker compose up -d postgres
DB_TYPE=postgresql python -m tg_parser.cli process --channel my_channel

# Migration: SQLite → PostgreSQL
python scripts/migrate_sqlite_to_postgres.py --verify
```

### Configurable Retries (v3.1) ⭐ NEW

```bash
# Агрессивные retry (для нестабильных API)
RETRY_MAX_ATTEMPTS=5 RETRY_BACKOFF_BASE=2.0 RETRY_BACKOFF_MAX=120.0 \
  python -m tg_parser.cli process --channel my_channel

# Минимальные retry (для стабильных API)
RETRY_MAX_ATTEMPTS=2 RETRY_BACKOFF_BASE=0.5 \
  python -m tg_parser.cli process --channel my_channel
```

### Параллельная обработка (ускорение в 3-5x)

```bash
# Последовательная обработка (по умолчанию)
python -m tg_parser.cli process --channel my_channel

# Параллельная обработка (быстрее!)
python -m tg_parser.cli process --channel my_channel --concurrency 5

# Максимальная производительность (с локальным Ollama)
python -m tg_parser.cli process --channel my_channel \
  --provider ollama \
  --concurrency 10
```

### One-shot pipeline

```bash
# Полный цикл: ingest → process → topicize → export
python -m tg_parser.cli run \
  --source my_channel \
  --out ./output \
  --provider anthropic \
  --concurrency 5
```

---

## 🤖 Agent-based Processing (v2.0) ⭐ NEW

Альтернативный режим обработки через OpenAI Agents SDK:

### Agent Basic (без LLM, ~0.3ms/сообщение)

```bash
# Быстрая обработка без API вызовов
python -m tg_parser.cli process --channel my_channel --agent

# С параллельной обработкой
python -m tg_parser.cli process --channel my_channel --agent --concurrency 10
```

### Agent LLM (с глубоким анализом)

```bash
# Семантический анализ с LLM
python -m tg_parser.cli process --channel my_channel --agent --agent-llm

# С конкретным провайдером
python -m tg_parser.cli process --channel my_channel \
  --agent --agent-llm \
  --provider openai
```

### Сравнение режимов

| Режим | Скорость | LLM | Качество |
|-------|----------|-----|----------|
| Pipeline v1.2 | ~500-2000ms | ✅ | Высокое |
| **Agent Basic** | **~0.3ms** | ❌ | Среднее |
| Agent LLM | ~500-1500ms | ✅ | Высокое |
| **Multi-Agent v3.0** | Адаптивно | ✅ | Лучшее |

---

## 🤖 Multi-Agent Architecture (v3.0) ⭐ NEW

Мультиагентная архитектура с оркестратором и специализированными агентами:

### Базовое использование

```bash
# Multi-Agent режим
python -m tg_parser.cli process --channel my_channel --multi-agent

# С конкретным провайдером
python -m tg_parser.cli process --channel my_channel --multi-agent --provider anthropic

# С параллельной обработкой
python -m tg_parser.cli process --channel my_channel --multi-agent --concurrency 3
```

### Архитектура

```
┌──────────────────────────┐
│    OrchestratorAgent     │  ← Координация workflow
└──────────────────────────┘
     │         │         │
     ▼         ▼         ▼
┌─────────┐ ┌──────────┐ ┌───────────┐
│Process- │ │Topiciz-  │ │Export-    │
│ingAgent │ │ationAgent│ │Agent      │
└─────────┘ └──────────┘ └───────────┘
```

### Когда использовать Multi-Agent?

- Сложные документы требующие специализированной обработки
- Расширяемые workflow с возможностью добавления новых агентов
- Детальный мониторинг по агентам

---

## 🐳 Docker

```bash
# Build
docker build -t tg_parser .

# Инициализация
docker-compose run tg_parser init

# Processing с выбранным провайдером
docker-compose run tg_parser process --channel my_channel \
  --provider anthropic \
  --concurrency 5

# С локальным Ollama
docker-compose up -d ollama
docker-compose exec ollama ollama pull llama3.2
docker-compose run tg_parser process --channel my_channel \
  --provider ollama
```

---

## 📚 Документация

- **[LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md)** — Полная инструкция по настройке LLM провайдеров
- **[SESSION_HANDOFF_v1.2.md](docs/notes/SESSION_HANDOFF_v1.2.md)** — Детали реализации v1.2
- **[CHANGELOG.md](CHANGELOG.md)** — История изменений
- **[README.md](README.md)** — Полная документация

---

## ✅ Что нового?

### v1.2
- ⭐ **4 LLM провайдера**: OpenAI, Anthropic, Gemini, Ollama
- ⚡ **Параллельная обработка**: `--concurrency` флаг (ускорение в 3-5x)
- 🐳 **Docker support**: Dockerfile и docker-compose.yml

### v2.0
- 🌐 **HTTP API**: REST API с FastAPI на `/docs`
- 🤖 **Agent-based Processing**: OpenAI Agents SDK
- 🚀 **Agent Basic**: обработка без LLM (~0.3ms/сообщение)
- 🧠 **Agent LLM**: глубокий семантический анализ

### v3.0 ⭐ NEW
- 🤖 **Multi-Agent Architecture**: OrchestratorAgent + специализированные агенты
- 📋 **Agent Registry**: централизованное управление агентами
- 🔄 **Handoff Protocol**: стандартизированный обмен данными между агентами
- 🎯 **Specialized Agents**: ProcessingAgent, TopicizationAgent, ExportAgent

### v3.0.0 Features
- 💾 **Agent State Persistence**: сохранение состояния агентов в SQLite
- 📊 **Task History**: полный input/output с TTL и ретенцией
- 📈 **Agent Stats**: ежедневная агрегированная статистика
- 🔗 **Handoff History**: отслеживание передач между агентами
- 📊 **Agent Observability**: CLI команды `agents` для мониторинга
- 🌐 **API Endpoints**: `/api/v1/agents/*` для агентов
- 📦 **Archiver**: архивация истории в NDJSON.gz

### v3.0.0 ⭐ RELEASE (Phase 3 Complete)
- 📈 **Prometheus Metrics**: endpoint `/metrics` для мониторинга
- ⏰ **Background Scheduler**: APScheduler для периодических задач
- 🏥 **Health Checks v2**: `/status/detailed`, `/scheduler` endpoints
- 🧪 **E2E Integration Tests**: полный CLI и API workflow
- 🧪 **373+ тестов** (было 366)

---

**v3.0.0 готова к production использованию!** 🚀

