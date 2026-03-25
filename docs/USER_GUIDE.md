# TG_parser — Руководство пользователя

**Версия:** 3.1.1 — Production Tested 🎉  
**Обновлено:** 30 декабря 2025

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

**Новое в v3.1.1:**
- ✅ **Протестировано на реальном канале** — @BiocodebySechenov (8 постов → processing → export)
- ✅ **CLI PostgreSQL Ready** — все команды работают с PostgreSQL
- ✅ **Boolean type fixes** — полная совместимость с asyncpg/PostgreSQL
- ✅ 411 тестов (100% pass rate)

**v3.1.0:**
- ✅ **PostgreSQL Support** — production-grade database с connection pooling
- ✅ **Multi-user Ready** — concurrent access, horizontal scaling
- ✅ **Migration Tools** — автоматическая миграция SQLite → PostgreSQL
- ✅ **Production Docker** — docker-compose с PostgreSQL service
- ✅ Structured JSON logging для production
- ✅ GPT-5 поддержка (gpt-5.2, gpt-5-mini, gpt-5-nano)
- ✅ Конфигурируемые retry параметры
- ✅ **Production Ready** для enterprise deployment

## Содержание

1. [Установка и настройка](#установка-и-настройка)
2. [Database Setup (PostgreSQL/SQLite)](#database-setup)
3. [Конфигурация](#конфигурация)
4. [CLI команды](#cli-команды)
5. [HTTP API](#http-api)
6. [Logging](#logging)
7. [Мониторинг](#мониторинг)
8. [Примеры использования](#примеры-использования)
9. [Production Deployment](#production-deployment)
10. [Troubleshooting](#troubleshooting)

---

## Установка и настройка

### Требования

- **Python 3.12+**
- **pip** или **uv** для управления зависимостями
- Аккаунт Telegram с возможностью получить API credentials
- API ключ OpenAI

### 1. Установка проекта

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

### 2. Получение Telegram API credentials

1. Перейдите на https://my.telegram.org
2. Войдите с номером телефона вашего Telegram-аккаунта
3. Перейдите в раздел **"API development tools"**
4. Создайте новое приложение:
   - **App title** — любое название (например, "TG Parser")
   - **Short name** — короткое имя латиницей (например, "tgparser")
   - **Platform** — выберите "Desktop"
5. После создания скопируйте:
   - `api_id` — числовой ID
   - `api_hash` — строка из букв и цифр

> ⚠️ **Важно:** API credentials привязаны к вашему аккаунту. Не передавайте их третьим лицам.

### 3. Настройка LLM API (v1.2: Multi-LLM)

**TG_parser v1.2** поддерживает 4 LLM провайдера. Выберите один или несколько:

#### OpenAI (default)
1. Перейдите на https://platform.openai.com/api-keys
2. Создайте новый API ключ
3. Добавьте в `.env`: `OPENAI_API_KEY=sk-...`

> ✅ **GPT-5 (gpt-5.2 / gpt-5-mini / gpt-5-nano):**
> - **Полная поддержка** с v3.1.0-alpha.2 (Session 23)
> - Автоматический routing через **Responses API** (`/v1/responses`)
> - Параметры `reasoning.effort` (minimal/low/medium/high)
> - Параметры `verbosity` (low/medium/high)
> - Backward compatible с GPT-4o-mini
> - См. [LLM_SETUP_GUIDE.md](../LLM_SETUP_GUIDE.md) для деталей

#### Anthropic Claude
1. Перейдите на https://console.anthropic.com/
2. Создайте API ключ
3. Добавьте в `.env`: `ANTHROPIC_API_KEY=sk-ant-...`

#### Google Gemini
1. Перейдите на https://aistudio.google.com/apikey
2. Создайте API ключ
3. Добавьте в `.env`: `GEMINI_API_KEY=AI...`

#### Ollama (локальный, бесплатно)
1. Установите Ollama: https://ollama.ai
2. Скачайте модель: `ollama pull qwen3:8b`
3. Добавьте в `.env`: `LLM_BASE_URL=http://localhost:11434`

> 💡 **Рекомендации:**
> - **Gemini** — самый быстрый (0.34 msg/s), отличное соотношение цена/качество
> - **Claude** — лучшее качество извлечения entities
> - **Ollama** — бесплатно, приватно, для разработки

### 4. Настройка конфигурации

Создайте файл `.env` в корне проекта:

```bash
cp .env.example .env
```

Отредактируйте `.env`:

```env
# Telegram API credentials (обязательно)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_PHONE=+79001234567

# === LLM Configuration (v1.2: Multi-LLM) ===

# Провайдер по умолчанию: openai | anthropic | gemini | ollama
LLM_PROVIDER=openai

# API ключи (укажите нужные)
OPENAI_API_KEY=sk-...your-api-key...
ANTHROPIC_API_KEY=sk-ant-...your-key...
GEMINI_API_KEY=AI...your-key...

# Для Ollama (локальный LLM)
LLM_BASE_URL=http://localhost:11434

# Модель LLM (опционально, default зависит от провайдера)
# LLM_MODEL=gpt-4o-mini
# LLM_MODEL=gpt-5.2
# LLM_MODEL=gpt-5-mini
# LLM_MODEL=gpt-5-nano
# LLM_MODEL=claude-sonnet-4-20250514
# LLM_MODEL=gemini-2.0-flash-exp
# LLM_MODEL=qwen3:8b
```

### Полный список настроек

> 💡 **Полный справочник**: См. [ENV_VARIABLES_GUIDE.md](../../ENV_VARIABLES_GUIDE.md) для всех переменных с примерами

| Переменная | Описание | Обязательно | По умолчанию |
|------------|----------|-------------|--------------|
| **Telegram** |||
| `TELEGRAM_API_ID` | Telegram API ID | Да | — |
| `TELEGRAM_API_HASH` | Telegram API Hash | Да | — |
| `TELEGRAM_PHONE` | Номер телефона для авторизации | Да | — |
| `TELEGRAM_SESSION_NAME` | Имя файла сессии | Нет | `tg_parser_session` |
| **LLM Configuration** |||
| `LLM_PROVIDER` | Провайдер: openai/anthropic/gemini/ollama | Нет | `openai` |
| `OPENAI_API_KEY` | API ключ OpenAI | Да* | — |
| `ANTHROPIC_API_KEY` | API ключ Anthropic | Да* | — |
| `GEMINI_API_KEY` | API ключ Google Gemini | Да* | — |
| `LLM_MODEL` | Модель LLM | Нет | По провайдеру |
| `LLM_BASE_URL` | Base URL для OpenAI-compatible API | Нет | По провайдеру |
| `LLM_TEMPERATURE` | Temperature для LLM (0.0 = детерминизм) | Нет | `0.0` |
| `LLM_MAX_TOKENS` | Максимум токенов ответа | Нет | `4096` |
| **GPT-5 Support (v3.1)** ⭐ |||
| `LLM_REASONING_EFFORT` | Reasoning effort: minimal/low/medium/high | Нет | `low` |
| `LLM_VERBOSITY` | Verbosity: low/medium/high | Нет | `low` |
| **Logging (v3.1)** ⭐ |||
| `LOG_FORMAT` | Формат логов: json/text | Нет | `text` |
| `LOG_LEVEL` | Уровень: DEBUG/INFO/WARNING/ERROR | Нет | `INFO` |
| **Retry Configuration (v3.1)** ⭐ |||
| `RETRY_MAX_ATTEMPTS` | Макс. попыток retry (1-10) | Нет | `3` |
| `RETRY_BACKOFF_BASE` | Базовая задержка в секундах (0.1-60.0) | Нет | `1.0` |
| `RETRY_BACKOFF_MAX` | Макс. задержка в секундах (1.0-300.0) | Нет | `60.0` |
| `RETRY_JITTER` | Jitter фактор (0.0-1.0) | Нет | `0.3` |

\* Требуется для соответствующего провайдера

---

## Database Setup

**v3.1.0** поддерживает 2 database backend: **SQLite** (development) и **PostgreSQL** (production).

### Option A: SQLite (Development, Default)

```env
# В .env:
DB_TYPE=sqlite  # default
```

**SQLite базы создаются автоматически:**
- `ingestion_state.sqlite` — состояние источников
- `raw_storage.sqlite` — сырые сообщения
- `processing_storage.sqlite` — обработанные документы и темы

**Идеально для:**
- Development и testing
- Single-user usage
- Малые объемы данных (<10K сообщений)

**Пути можно переопределить:**
```env
INGESTION_STATE_DB_PATH=./data/ingestion_state.sqlite
RAW_STORAGE_DB_PATH=./data/raw_storage.sqlite
PROCESSING_STORAGE_DB_PATH=./data/processing_storage.sqlite
```

### Option B: PostgreSQL (Production) ⭐ TESTED

> ✅ **Протестировано в v3.1.1** на реальном канале @BiocodebySechenov

```bash
# 1. Start PostgreSQL с Docker Compose
docker compose up -d postgres

# 2. Configure в .env:
DB_TYPE=postgresql
DB_HOST=localhost      # или 'postgres' внутри Docker
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=SECURE_PASSWORD_HERE

# 3. Initialize PostgreSQL schema
python scripts/init_postgres.py

# Connection pool settings (optional, defaults работают хорошо)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true
```

**Проверка подключения:**
```bash
# Проверить что PostgreSQL доступен
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c '\dt'

# Должно показать 14 таблиц
```

**Рекомендуется для:**
- Production deployments
- Multi-user/concurrent access
- Большие объемы данных (>10K сообщений)
- Enterprise environments

**Преимущества:**
- ✅ Native multi-user support
- ✅ Connection pooling для производительности
- ✅ Horizontal scaling
- ✅ Enterprise-grade reliability
- ✅ Advanced indexing (11 performance indexes)

**Migration (SQLite → PostgreSQL):**

Если у вас уже есть данные в SQLite:

```bash
# 1. Backup
mkdir -p backups
cp *.sqlite backups/

# 2. Setup PostgreSQL
docker compose up -d postgres

# 3. Migrate data
python scripts/migrate_sqlite_to_postgres.py --verify

# 4. Switch
echo "DB_TYPE=postgresql" >> .env
```

**Guides:**
- 📖 [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md) — полный production guide
- 🚀 [MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](../../MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md) — migration guide
- ⚙️ [ENV_VARIABLES_GUIDE.md](../../ENV_VARIABLES_GUIDE.md) — все DB_* переменные

---

## Конфигурация

### Примеры конфигурации для разных сценариев

#### Development (локально)
```env
# Logging
LOG_FORMAT=text           # Colored, human-readable
LOG_LEVEL=DEBUG

# LLM
LLM_PROVIDER=ollama       # Бесплатно
LLM_MODEL=llama3.2

# Retry
RETRY_MAX_ATTEMPTS=3
```

#### Production (Docker)
```env
# Logging
LOG_FORMAT=json           # Structured JSON logs
LOG_LEVEL=INFO

# LLM
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.2         # Latest GPT-5
LLM_REASONING_EFFORT=medium
LLM_VERBOSITY=low

# Retry (более агрессивный)
RETRY_MAX_ATTEMPTS=5
RETRY_BACKOFF_BASE=2.0
RETRY_BACKOFF_MAX=120.0
```

#### Staging (тестирование GPT-5)
```env
# Logging
LOG_FORMAT=json
LOG_LEVEL=DEBUG           # Детальные логи

# LLM (GPT-5 testing)
LLM_PROVIDER=openai
LLM_MODEL=gpt-5-mini      # Дешевле для тестов
LLM_REASONING_EFFORT=low
LLM_VERBOSITY=high        # Подробные ответы

# Retry
RETRY_MAX_ATTEMPTS=3
```

---

## CLI команды

Все команды запускаются через:

```bash
python -m tg_parser.cli <команда> [опции]
```

### Справка

```bash
# Общая справка
python -m tg_parser.cli --help

# Справка по команде
python -m tg_parser.cli <команда> --help
```

### `init` — Инициализация баз данных

Создаёт SQLite базы данных и таблицы.

```bash
python -m tg_parser.cli init
```

**Опции:**
- `--force` — пересоздать базы даже если существуют

**Пример:**
```bash
# Первая инициализация
python -m tg_parser.cli init

# Пересоздание (удалит все данные!)
python -m tg_parser.cli init --force
```

### `add-source` — Добавление источника

Регистрирует Telegram канал для сбора данных.

```bash
python -m tg_parser.cli add-source --source-id <id> --channel-id <channel>
```

**Обязательные опции:**
- `--source-id` — уникальный ID источника (произвольная строка)
- `--channel-id` — ID канала в Telegram (username или numeric ID)

**Дополнительные опции:**
- `--channel-username` — username канала (для генерации ссылок)
- `--include-comments` — собирать комментарии к постам
- `--batch-size` — размер батча (default: 100)

**Примеры:**
```bash
# Добавить публичный канал по username
python -m tg_parser.cli add-source --source-id news --channel-id @durov

# Добавить с комментариями
python -m tg_parser.cli add-source --source-id blog --channel-id @channel --include-comments

# Добавить по numeric ID (для приватных каналов)
python -m tg_parser.cli add-source --source-id private --channel-id -1001234567890
```

### `ingest` — Сбор сообщений

Собирает raw сообщения из Telegram канала.

```bash
python -m tg_parser.cli ingest --source <source-id>
```

**Обязательные опции:**
- `--source` — ID источника (из `add-source`)

**Дополнительные опции:**
- `--mode` — режим сбора: `incremental` (default) или `snapshot`
- `--limit` — лимит сообщений (для отладки)

**Режимы:**
- `incremental` — собирает только новые сообщения с последнего запуска
- `snapshot` — собирает все доступные сообщения

**Примеры:**
```bash
# Инкрементальный сбор
python -m tg_parser.cli ingest --source news --mode incremental

# Полный snapshot
python -m tg_parser.cli ingest --source news --mode snapshot

# С лимитом для тестирования
python -m tg_parser.cli ingest --source news --limit 10
```

> 📱 **Первый запуск:** При первом запуске Telethon запросит код подтверждения из Telegram. Введите код в терминале.

### `process` — Обработка через LLM

Обрабатывает raw сообщения через LLM: очистка текста, саммари, извлечение тем и сущностей.

**v1.2: Multi-LLM поддержка** — OpenAI, Anthropic Claude, Google Gemini, Ollama.
**v2.0: Agent-based processing** — альтернативный режим на базе OpenAI Agents SDK.
**v3.0: Multi-Agent Architecture** — мультиагентная архитектура с оркестратором и специализированными агентами.

```bash
python -m tg_parser.cli process --channel <channel-id> [OPTIONS]
```

**Обязательные опции:**
- `--channel` — идентификатор канала

**Дополнительные опции:**
- `--provider` — LLM провайдер: `openai`, `anthropic`, `gemini`, `ollama`
- `--model` — переопределить модель
- `--concurrency` / `-c` — количество параллельных запросов (default: 1)
- `--force` — переобработать уже обработанные сообщения
- `--retry-failed` — повторить только failed сообщения
- `--agent` — использовать agent-based processing (v2.0)
- `--agent-llm` — включить LLM-enhanced tools для агента
- `--hybrid` — включить v1.2 pipeline как tool агента (Phase 2E)
- `--multi-agent` — использовать Multi-Agent Architecture (v3.0) ⭐ NEW
- `--dry-run` — режим проверки

**Примеры:**
```bash
# Обработать с default провайдером (v1.2 pipeline)
python -m tg_parser.cli process --channel @durov

# Использовать Anthropic Claude
python -m tg_parser.cli process --channel @durov --provider anthropic

# Использовать Gemini с параллельной обработкой
python -m tg_parser.cli process --channel @durov --provider gemini -c 5

# Использовать локальный Ollama
python -m tg_parser.cli process --channel @durov --provider ollama --model qwen3:8b

# Принудительная переобработка
python -m tg_parser.cli process --channel @durov --force

# Multi-Agent Architecture (v3.0)
python -m tg_parser.cli process --channel @durov --multi-agent

# Multi-Agent с конкретным провайдером
python -m tg_parser.cli process --channel @durov --multi-agent --provider anthropic
```

#### Multi-Agent Architecture (v3.0) ⭐ NEW

Новый режим с мультиагентной архитектурой, где специализированные агенты координируются оркестратором:

```bash
# Базовый multi-agent режим
python -m tg_parser.cli process --channel @durov --multi-agent

# С конкретным LLM провайдером
python -m tg_parser.cli process --channel @durov --multi-agent --provider anthropic

# С параллельной обработкой
python -m tg_parser.cli process --channel @durov --multi-agent -c 3
```

**Архитектура Multi-Agent:**

| Компонент | Роль |
|-----------|------|
| **OrchestratorAgent** | Координация workflow, маршрутизация задач |
| **ProcessingAgent** | Очистка текста, извлечение тем/entities |
| **TopicizationAgent** | Кластеризация документов по темам |
| **ExportAgent** | Экспорт в NDJSON/JSON форматы |

> 💡 **Когда использовать Multi-Agent:**
> - Сложные документы требующие специализированной обработки
> - Расширяемые workflow с возможностью добавления новых агентов
> - Адаптивная маршрутизация на основе контента

#### Agent-based Processing (v2.0)

Альтернативный режим обработки на базе OpenAI Agents SDK:

```bash
# Agent с базовыми tools (быстро, без LLM вызовов, ~0.3ms/сообщение)
python -m tg_parser.cli process --channel @durov --agent

# Agent с LLM-enhanced tools (качественно, семантический анализ)
python -m tg_parser.cli process --channel @durov --agent --agent-llm

# Agent с конкретным провайдером
python -m tg_parser.cli process --channel @durov --agent --agent-llm --provider openai

# Hybrid mode — agent + v1.2 pipeline (адаптивная обработка)
python -m tg_parser.cli process --channel @durov --agent --hybrid

# Full Hybrid — LLM agent + pipeline tool (максимальное качество)
python -m tg_parser.cli process --channel @durov --agent --agent-llm --hybrid
```

**Сравнение режимов:**

| Режим | Время обработки | Качество | LLM вызовы | Tools |
|-------|-----------------|----------|------------|-------|
| **Pipeline v1.2** | 500-2000ms | Высокое | 1 | N/A |
| **Agent Basic** | ~0.3ms | Среднее | 1 | 3 |
| **Agent LLM** | 500-1500ms | Высокое | 2+ | 1 |
| **Hybrid Basic** | Адаптивно | Высокое | 1-2 | 4 |
| **Hybrid LLM** | Адаптивно | Лучшее | 2-3 | 2 |
| **Multi-Agent** ⭐ | Адаптивно | Лучшее | N (распределено) | Специализированные |

> 💡 **Когда использовать Agent Basic:**
> - Быстрая предобработка больших объёмов данных
> - Работа без интернета (офлайн режим)
> - Снижение затрат на API

> 💡 **Когда использовать Agent LLM:**
> - Качественный семантический анализ
> - Извлечение key_points и sentiment

> 💡 **Когда использовать Hybrid Mode:**
> - Сочетание скорости и качества
> - Agent сам выбирает: простые сообщения → basic tools, сложные → pipeline
> - Максимальная адаптивность
> - Работа с важными документами

> ⚠️ **Рекомендации по concurrency:**
> - **Cloud провайдеры** (OpenAI, Anthropic, Gemini): `-c 3` до `-c 5`
> - **Ollama** (локальный): `-c 1` (параллелизация замедляет!)

### `topicize` — Тематизация

Кластеризует обработанные документы по темам.

```bash
python -m tg_parser.cli topicize --channel <channel-id>
```

**Обязательные опции:**
- `--channel` — идентификатор канала

**Дополнительные опции:**
- `--force` — переформировать темы даже если уже есть
- `--no-bundles` — не создавать topic bundles

**Примеры:**
```bash
# Создать темы
python -m tg_parser.cli topicize --channel @durov

# Только карточки тем без bundles
python -m tg_parser.cli topicize --channel @durov --no-bundles

# Принудительное переформирование
python -m tg_parser.cli topicize --channel @durov --force
```

### `export` — Экспорт артефактов

Экспортирует данные в файлы для внешних систем.

```bash
python -m tg_parser.cli export --out <directory>
```

**Опции:**
- `--out` — директория вывода (default: `./output`)
- `--channel` — фильтр по каналу
- `--topic-id` — фильтр по теме
- `--from-date` — фильтр по дате от (формат: YYYY-MM-DD)
- `--to-date` — фильтр по дате до (формат: YYYY-MM-DD)
- `--pretty` — форматированный JSON

**Выходные файлы:**
- `kb_entries.ndjson` — записи базы знаний (NDJSON формат)
- `topics.json` — каталог всех тем
- `topic_<id>.json` — детальные карточки отдельных тем

**Примеры:**
```bash
# Экспорт всех данных
python -m tg_parser.cli export --out ./output

# Экспорт конкретного канала
python -m tg_parser.cli export --channel @durov --out ./output

# Экспорт за период
python -m tg_parser.cli export --from-date 2025-01-01 --to-date 2025-12-31 --out ./output

# Форматированный JSON для чтения
python -m tg_parser.cli export --out ./output --pretty
```

### `run` — One-shot Pipeline ⭐

**Рекомендуемая команда** — запускает полный pipeline одной командой:
1. `ingest` — сбор сообщений
2. `process` — обработка через LLM
3. `topicize` — тематизация
4. `export` — экспорт результатов

```bash
python -m tg_parser.cli run --source <source-id> --out <directory>
```

**Обязательные опции:**
- `--source` — ID источника

**Дополнительные опции:**
- `--out` — директория вывода (default: `./output`)
- `--mode` — режим ingestion: `incremental` или `snapshot`
- `--skip-ingest` — пропустить этап сбора
- `--skip-process` — пропустить этап обработки
- `--skip-topicize` — пропустить этап тематизации
- `--force` — принудительная переобработка
- `--limit` — лимит сообщений для ingestion

**Примеры:**
```bash
# Базовый запуск (полный pipeline)
python -m tg_parser.cli run --source news --out ./output

# Режим snapshot (все сообщения)
python -m tg_parser.cli run --source news --out ./output --mode snapshot

# Пропустить ingestion (если данные уже собраны)
python -m tg_parser.cli run --source news --out ./output --skip-ingest

# Только экспорт (пропустить обработку и тематизацию)
python -m tg_parser.cli run --source news --out ./output --skip-ingest --skip-process --skip-topicize

# С лимитом для тестирования
python -m tg_parser.cli run --source news --out ./output --limit 10

# Принудительная переобработка всего
python -m tg_parser.cli run --source news --out ./output --force
```

### `agents` — Мониторинг агентов (v3.0) ⭐ NEW

Команды для мониторинга и управления агентами Multi-Agent системы.

```bash
tg-parser agents <command>
```

**Доступные подкоманды:**

| Команда | Описание |
|---------|----------|
| `list` | Список всех зарегистрированных агентов |
| `status` | Статистика агента |
| `history` | История задач агента |
| `cleanup` | Очистка истёкших записей |
| `handoffs` | Статистика handoff'ов |
| `archives` | Список архивных файлов |

**Примеры:**

```bash
# Список всех агентов
tg-parser agents list

# Только активные агенты типа processing
tg-parser agents list --type processing --active

# Список в JSON формате
tg-parser agents list --format json

# Статистика агента за 30 дней
tg-parser agents status ProcessingAgent --days 30

# История задач с ошибками
tg-parser agents history ProcessingAgent --errors --limit 50

# Просмотр того, что будет удалено (dry run)
tg-parser agents cleanup --dry-run

# Очистка с архивацией в NDJSON.gz
tg-parser agents cleanup --archive

# Архивация включая handoff'ы
tg-parser agents cleanup --archive --include-handoffs

# Статистика handoff'ов между агентами
tg-parser agents handoffs --stats

# Handoff'ы конкретного агента
tg-parser agents handoffs --agent OrchestratorAgent

# Список архивных файлов
tg-parser agents archives
```

**Формат архивов:**
- `task_history_YYYYMMDD_HHMMSS.ndjson.gz` — архив task_history
- `handoff_history_YYYYMMDD_HHMMSS.ndjson.gz` — архив handoff_history

> 💡 **Совет**: Используйте `--dry-run` перед `cleanup` чтобы увидеть, какие записи будут удалены.

---

## Logging (v3.1) ⭐ NEW

### Форматы логов

TG_parser поддерживает два формата логирования:

#### Text Format (Development)

Colored, human-readable логи для локальной разработки:

```env
LOG_FORMAT=text
LOG_LEVEL=DEBUG
```

**Пример вывода:**
```
2025-12-29T12:34:56.789Z [info    ] request_started method=GET path=/health request_id=abc-123
2025-12-29T12:34:56.890Z [info    ] message_processed_successfully source_ref=tg:channel:post:123
```

#### JSON Format (Production)

Structured JSON логи для production (один JSON объект на строку):

```env
LOG_FORMAT=json
LOG_LEVEL=INFO
```

**Пример вывода:**
```json
{"timestamp":"2025-12-29T12:34:56.789Z","level":"info","event":"request_started","method":"GET","path":"/health","request_id":"abc-123"}
{"timestamp":"2025-12-29T12:34:56.890Z","level":"info","event":"message_processed_successfully","source_ref":"tg:channel:post:123","attempt":1}
```

### Request ID Tracing

Все API запросы автоматически получают `request_id` для трейсинга:

```bash
curl -H "X-Request-ID: my-trace-123" http://localhost:8000/api/v1/process
```

Если заголовок не указан, генерируется автоматически (UUID).

### Фильтрация JSON логов с jq

```bash
# Показать только errors
docker logs tg_parser | jq 'select(.level == "error")'

# Найти логи для конкретного request_id
docker logs tg_parser | jq 'select(.request_id == "abc-123")'

# Медленные запросы (>1000ms)
docker logs tg_parser | jq 'select(.duration_ms > 1000)'

# Группировка errors по типу
docker logs tg_parser | jq -r 'select(.level == "error") | .error_type' | sort | uniq -c

# Подсчет запросов по path
docker logs tg_parser | jq -r 'select(.path) | .path' | sort | uniq -c | sort -rn

# Статистика по request_id
docker logs tg_parser | jq -r '.request_id' | sort | uniq | wc -l
```

### Log Levels

| Level | Описание | Когда использовать |
|-------|----------|--------------------|
| `DEBUG` | Детальная отладочная информация | Development, troubleshooting |
| `INFO` | Общая информация о работе | Production (default) |
| `WARNING` | Предупреждения | Production |
| `ERROR` | Ошибки | Production |
| `CRITICAL` | Критические ошибки | Production |

### Примеры конфигурации

**Development:**
```env
LOG_FORMAT=text
LOG_LEVEL=DEBUG
```

**Production (Docker):**
```env
LOG_FORMAT=json
LOG_LEVEL=INFO
```

**Debugging Production:**
```env
LOG_FORMAT=json
LOG_LEVEL=DEBUG
```

> 💡 **Совет**: Используйте `LOG_FORMAT=json` + `LOG_LEVEL=INFO` в production для лучшего анализа логов.

---

## Мониторинг

### Prometheus Metrics

TG_parser предоставляет Prometheus-совместимые метрики через endpoint `/metrics`:

```bash
# Запустить API сервер
tg-parser api --port 8000

# Получить метрики
curl http://localhost:8000/metrics
```

**Доступные метрики:**

| Метрика | Описание |
|---------|----------|
| `tg_parser_http_requests_total` | Общее количество HTTP запросов |
| `tg_parser_http_request_duration_seconds` | Latency HTTP запросов |
| `tg_parser_agent_tasks_total` | Задачи агентов (по типу и статусу) |
| `tg_parser_agent_task_duration_seconds` | Время выполнения задач |
| `tg_parser_llm_requests_total` | Запросы к LLM |
| `tg_parser_llm_tokens_total` | Использованные токены LLM |
| `tg_parser_messages_processed_total` | Обработанные сообщения |
| `tg_parser_scheduler_tasks_total` | Выполнения scheduled tasks |

**Prometheus конфигурация:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'tg_parser'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Health Checks

#### Базовый health check

```bash
curl http://localhost:8000/health
# {"status": "ok", "version": "processing:v1.0.0", "timestamp": "..."}
```

#### Детальный статус

```bash
curl http://localhost:8000/status/detailed
```

Ответ включает статус всех компонентов:
- **database** — подключение к БД, latency, размер
- **llm** — доступность LLM провайдера
- **agents** — количество активных агентов
- **scheduler** — статус background scheduler

#### Статус scheduler

```bash
curl http://localhost:8000/scheduler
# {"running": true, "tasks": [...], "enabled": true}
```

### Background Scheduler

TG_parser автоматически выполняет фоновые задачи:

| Задача | Интервал | Описание |
|--------|----------|----------|
| `cleanup_expired_records` | 24 часа | Очистка expired task_history и handoff_history |
| `health_check` | 5 минут | Проверка здоровья компонентов |

**Настройка через переменные окружения:**

```env
SCHEDULER_ENABLED=true                        # Включить scheduler
SCHEDULER_CLEANUP_INTERVAL_HOURS=24           # Интервал очистки
SCHEDULER_HEALTH_CHECK_INTERVAL_MINUTES=5     # Интервал health check
```

### Отключение мониторинга

```env
# Отключить Prometheus metrics
METRICS_ENABLED=false

# Отключить background scheduler
SCHEDULER_ENABLED=false
```

---

## Примеры использования

### Quick Start — минимальный пример

```bash
# 1. Инициализировать базы
python -m tg_parser.cli init

# 2. Добавить канал
python -m tg_parser.cli add-source --source-id test --channel-id @durov

# 3. Запустить полный pipeline
python -m tg_parser.cli run --source test --out ./output --limit 10
```

Результаты будут в директории `./output/`.

### Полный pipeline для нового канала

```bash
# 1. Инициализировать базы (один раз)
python -m tg_parser.cli init

# 2. Добавить источник
python -m tg_parser.cli add-source \
    --source-id tech_news \
    --channel-id @techcrunchchannel \
    --include-comments

# 3. Собрать все сообщения (snapshot)
python -m tg_parser.cli ingest --source tech_news --mode snapshot

# 4. Обработать через LLM
python -m tg_parser.cli process --channel @techcrunchchannel

# 5. Создать темы
python -m tg_parser.cli topicize --channel @techcrunchchannel

# 6. Экспортировать
python -m tg_parser.cli export --channel @techcrunchchannel --out ./tech_news_output --pretty
```

### Incremental обновление (регулярный сбор)

```bash
# Собрать только новые сообщения и обработать
python -m tg_parser.cli run --source tech_news --out ./tech_news_output --mode incremental
```

Можно добавить в cron для регулярного обновления:

```bash
# Каждый час собирать новые сообщения
0 * * * * cd /path/to/TG_parser && .venv/bin/python -m tg_parser.cli run --source tech_news --out ./output
```

### Экспорт с фильтрами

```bash
# Экспорт за определённый период
python -m tg_parser.cli export \
    --from-date 2025-01-01 \
    --to-date 2025-06-30 \
    --out ./q1_q2_2025

# Экспорт конкретной темы
python -m tg_parser.cli export \
    --topic-id "topic:tg:channel:post:123" \
    --out ./single_topic

# Экспорт только одного канала с pretty-print
python -m tg_parser.cli export \
    --channel @durov \
    --out ./durov_export \
    --pretty
```

### Работа с несколькими каналами

```bash
# Добавить несколько источников
python -m tg_parser.cli add-source --source-id channel1 --channel-id @channel1
python -m tg_parser.cli add-source --source-id channel2 --channel-id @channel2
python -m tg_parser.cli add-source --source-id channel3 --channel-id @channel3

# Собрать и обработать каждый отдельно
for source in channel1 channel2 channel3; do
    python -m tg_parser.cli run --source $source --out ./output
done

# Или экспортировать всё вместе
python -m tg_parser.cli export --out ./all_channels
```

### Тестирование без Telegram

Для тестирования без реального Telegram API используйте скрипт добавления тестовых данных:

```bash
# Добавить тестовые сообщения
python scripts/add_test_messages.py

# Обработать тестовые данные
python -m tg_parser.cli process --channel test_channel

# Просмотреть результаты
python scripts/view_processed.py --channel test_channel
```

---

## Troubleshooting

### Проблемы с авторизацией Telegram

#### `FloodWaitError: You must wait X seconds`

Telegram ограничивает частоту запросов авторизации.

**Решение:** Подождите указанное время (X секунд) и повторите попытку.

#### `SessionPasswordNeededError`

Ваш аккаунт защищён двухфакторной аутентификацией.

**Решение:** Введите пароль 2FA при запросе в терминале.

#### `PhoneCodeInvalidError`

Введён неверный код подтверждения.

**Решение:** 
1. Проверьте, что код введён корректно
2. Убедитесь, что код не истёк (действует ~5 минут)
3. Запросите новый код повторным запуском

#### `ApiIdInvalidError`

Неверный API ID или API Hash.

**Решение:**
1. Проверьте значения `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` в `.env`
2. Убедитесь, что нет лишних пробелов
3. Создайте новое приложение на https://my.telegram.org если нужно

#### Файл сессии повреждён

Если возникают странные ошибки авторизации:

**Решение:**
```bash
# Удалить файл сессии и авторизоваться заново
rm tg_parser_session.session
python -m tg_parser.cli ingest --source <source>
```

### Проблемы с OpenAI API

#### `AuthenticationError: Invalid API Key`

**Решение:**
1. Проверьте `OPENAI_API_KEY` в `.env`
2. Убедитесь, что ключ начинается с `sk-`
3. Проверьте, что ключ не деактивирован в OpenAI Dashboard

#### `RateLimitError`

Превышен лимит запросов к OpenAI API.

**Решение:**
1. Подождите несколько минут
2. Проверьте лимиты в OpenAI Dashboard
3. Используйте `--limit` для уменьшения объёма обработки

#### `InsufficientQuotaError`

Исчерпан баланс OpenAI.

**Решение:**
1. Пополните баланс в OpenAI Dashboard
2. Проверьте billing limits

### Проблемы с данными

#### Пустой вывод при export

**Причины и решения:**
1. **Не выполнен ingest:** Запустите `ingest` для сбора данных
2. **Не выполнен process:** Запустите `process` для обработки
3. **Не выполнен topicize:** Запустите `topicize` для создания тем
4. **Неверный фильтр:** Проверьте параметры `--channel`, `--from-date`, `--to-date`

**Рекомендация:** Используйте команду `run` для автоматического выполнения всех этапов:
```bash
python -m tg_parser.cli run --source <source> --out ./output
```

#### `ChannelPrivateError` или `ChannelInvalidError`

Канал недоступен или не существует.

**Решение:**
1. Убедитесь, что вы подписаны на канал (для приватных)
2. Проверьте правильность написания username
3. Для приватных каналов используйте numeric ID (`-100...`)

#### Ошибки при обработке отдельных сообщений

Processing продолжает работу при ошибках отдельных сообщений (записывает их в `processing_failures`).

**Для просмотра ошибок:**
```bash
sqlite3 processing_storage.sqlite "SELECT source_ref, error_class, error_message FROM processing_failures;"
```

### Общие проблемы

#### `ModuleNotFoundError: No module named 'tg_parser'`

**Решение:**
```bash
# Установить проект в режиме разработки
pip install -e .
```

#### База данных заблокирована

`sqlite3.OperationalError: database is locked`

**Решение:**
1. Убедитесь, что не запущено несколько экземпляров CLI
2. Подождите завершения предыдущей операции
3. При необходимости завершите зависшие процессы

#### Недостаточно памяти при обработке больших каналов

**Решение:**
1. Используйте `--limit` для ограничения объёма
2. Обрабатывайте данные порциями
3. Используйте incremental режим вместо snapshot

### Логирование

Для подробного вывода установите переменную окружения:

```bash
# Включить debug логирование
export LOG_LEVEL=DEBUG
python -m tg_parser.cli run --source test --out ./output
```

---

---

## Agent-based Processing (v2.0) ⭐ NEW

### Что это?

**Agent-based processing** — альтернативный подход к обработке сообщений, использующий [OpenAI Agents SDK](https://github.com/openai/openai-agents-python). Вместо фиксированного pipeline, агент динамически выбирает инструменты для анализа.

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    TGProcessingAgent                        │
├─────────────────────────────────────────────────────────────┤
│  Режим: Agent Basic (3 tools)                               │
│  ├── clean_text        → Regex очистка                      │
│  ├── extract_topics    → Keyword matching                   │
│  └── extract_entities  → Pattern matching (email, URL, etc) │
├─────────────────────────────────────────────────────────────┤
│  Режим: Agent LLM (1 tool)                                  │
│  └── analyze_text_deep → LLM для глубокого анализа          │
│       ├── Semantic topics                                    │
│       ├── NER entities                                       │
│       ├── Key points extraction                              │
│       └── Sentiment analysis                                 │
├─────────────────────────────────────────────────────────────┤
│  Режим: Hybrid Basic (4 tools) ⭐ Phase 2E                   │
│  ├── clean_text        → Regex очистка                      │
│  ├── extract_topics    → Keyword matching                   │
│  ├── extract_entities  → Pattern matching                   │
│  └── process_with_pipeline → v1.2 pipeline для сложных      │
├─────────────────────────────────────────────────────────────┤
│  Режим: Hybrid LLM (2 tools) ⭐ Phase 2E                     │
│  ├── analyze_text_deep     → LLM для глубокого анализа      │
│  └── process_with_pipeline → v1.2 pipeline как fallback     │
└─────────────────────────────────────────────────────────────┘
```

### Использование в CLI

```bash
# Agent Basic — быстро, без LLM (~0.3ms/сообщение)
python -m tg_parser.cli process --channel @durov --agent

# Agent LLM — семантический анализ через LLM
python -m tg_parser.cli process --channel @durov --agent --agent-llm

# Hybrid Basic — agent + pipeline tool (4 tools)
python -m tg_parser.cli process --channel @durov --agent --hybrid

# Hybrid LLM — LLM agent + pipeline tool (2 tools, максимальное качество)
python -m tg_parser.cli process --channel @durov --agent --agent-llm --hybrid

# Agent LLM — качественно, с LLM
python -m tg_parser.cli process --channel @durov --agent --agent-llm

# С параллельной обработкой
python -m tg_parser.cli process --channel @durov --agent -c 5
```

### Использование в Python

```python
from tg_parser.agents import TGProcessingAgent
from tg_parser.domain.models import RawTelegramMessage

# Agent Basic (без LLM)
agent = TGProcessingAgent(
    model="gpt-4o-mini",
    use_llm_tools=False,  # Только pattern matching
)

doc = await agent.process(message)
print(doc.topics)    # ['laboratory', 'medicine']
print(doc.entities)  # [Entity(type='email', value='test@lab.com')]

# Agent LLM (с глубоким анализом)
from tg_parser.processing.llm.factory import create_llm_client

llm_client = create_llm_client(
    provider="openai",
    api_key="sk-...",
)

agent_llm = TGProcessingAgent(
    model="gpt-4o-mini",
    provider="openai",
    use_llm_tools=True,
    llm_client=llm_client,
)

doc = await agent_llm.process(message)
print(doc.topics)                     # ['клинические рекомендации', 'диагностика']
print(doc.metadata.get('key_points')) # ['Важность преаналитики', ...]
print(doc.metadata.get('sentiment'))  # 'neutral'
```

### Сравнение качества

Скрипт для сравнения Agent vs Pipeline:

```bash
# Базовое сравнение на 10 сообщениях
python scripts/compare_agents_pipeline.py --limit 10

# С LLM агентом (требует OPENAI_API_KEY)
python scripts/compare_agents_pipeline.py --limit 5 --llm
```

### Когда что использовать?

| Сценарий | Рекомендуемый режим |
|----------|---------------------|
| Быстрая обработка миллионов сообщений | `--agent` |
| Офлайн работа без API | `--agent` |
| Качественный анализ документов | `--agent --agent-llm` |
| Production с балансом скорость/качество | Pipeline v1.2 |
| Максимальное качество entities | Pipeline v1.2 + Anthropic |
| Сложные документы, расширяемые workflow | `--multi-agent` ⭐ NEW |
| Кастомные pipeline с мониторингом | `--multi-agent` ⭐ NEW |

---

## Multi-Agent Architecture (v3.0) ⭐ NEW

### Что это?

**Multi-Agent Architecture** — продвинутый подход к обработке, использующий специализированных агентов для разных этапов pipeline. Вместо единого монолитного агента, система использует оркестратор и набор специализированных агентов.

### Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                     OrchestratorAgent                           │
│   • Координация workflow                                        │
│   • Маршрутизация задач между агентами                         │
│   • Управление состоянием обработки                            │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ ProcessingAgent │  │TopicizationAgent│  │   ExportAgent   │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ • clean_text    │  │ • cluster_docs  │  │ • export_ndjson │
│ • extract_topics│  │ • create_topic  │  │ • export_json   │
│ • extract_entities│ │   cards        │  │ • format_output │
│ • simple/deep   │  │ • update_topics │  │                 │
│   mode routing  │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Основные компоненты

| Компонент | Ответственность | Возможности |
|-----------|-----------------|-------------|
| **OrchestratorAgent** | Управление workflow | Маршрутизация, координация, мониторинг |
| **ProcessingAgent** | Обработка текста | Очистка, topics, entities, routing (simple/deep) |
| **TopicizationAgent** | Кластеризация | Topic cards, bundles, обновление тем |
| **ExportAgent** | Экспорт | NDJSON, JSON, форматирование |

### Handoff Protocol

Агенты обмениваются данными через стандартизированный протокол:

```python
# Запрос на передачу задачи
HandoffRequest(
    source_agent="ProcessingAgent",
    target_agent="TopicizationAgent", 
    task="cluster_documents",
    payload={"documents": [...]},
    priority="normal"
)

# Ответ
HandoffResponse(
    request_id="...",
    status="completed",
    output={"topics": [...]},
    processing_time=1.5
)
```

### Использование в CLI

```bash
# Базовый multi-agent режим
python -m tg_parser.cli process --channel @durov --multi-agent

# С конкретным LLM провайдером  
python -m tg_parser.cli process --channel @durov --multi-agent --provider anthropic

# С параллельной обработкой
python -m tg_parser.cli process --channel @durov --multi-agent -c 3
```

### Использование в Python

```python
from tg_parser.agents import (
    AgentRegistry,
    OrchestratorAgent,
    ProcessingAgent,
    TopicizationAgent,
    ExportAgent,
    AgentInput,
)

# Инициализация registry
registry = AgentRegistry()

# Регистрация агентов
processing = ProcessingAgent(llm_client=llm_client)
topicization = TopicizationAgent(llm_client=llm_client)
export = ExportAgent(llm_client=llm_client)

registry.register(processing)
registry.register(topicization)
registry.register(export)

# Создание оркестратора
orchestrator = OrchestratorAgent(registry=registry, llm_client=llm_client)
await orchestrator.initialize()

# Выполнение workflow
result = await orchestrator.execute_workflow("full_pipeline", documents)

await orchestrator.shutdown()
```

### Когда использовать?

| Сценарий | Рекомендуемый режим |
|----------|---------------------|
| Простая обработка | Pipeline v1.2 или Agent Basic |
| Качественный анализ | Agent LLM или Hybrid |
| Сложные документы, расширяемость | **Multi-Agent (v3.0)** |
| Кастомные workflow | **Multi-Agent (v3.0)** |
| Мониторинг по агентам | **Multi-Agent (v3.0)** |

### Agent Registry

Централизованный реестр агентов с возможностями:

- **Регистрация/отмена регистрации** агентов
- **Поиск по типу и capabilities**
- **Статистика** выполнения задач
- **Health checks** для всех агентов

```python
# Получить агента по типу
agent = registry.get_by_type(AgentType.PROCESSING)

# Найти агента по capability
agent = registry.find_best_for_capability(AgentCapability.ENTITY_EXTRACTION)

# Статистика
stats = registry.get_statistics()
print(stats)  # {'ProcessingAgent': {'tasks_completed': 100, 'success_rate': 0.98}}
```

---

## Agent State Persistence ⭐

### Что это?

**Agent State Persistence** — возможность сохранения состояния агентов в базу данных для:
- Восстановления статистики после рестарта
- Полного хранения input/output задач
- Мониторинга производительности агентов
- Отслеживания истории handoffs

### Настройка

Добавьте в `.env`:

```env
# Agent State Persistence (Phase 3B)
AGENT_RETENTION_DAYS=14           # Сколько дней хранить историю задач
AGENT_RETENTION_MODE=delete       # Что делать с истёкшими: delete | export
AGENT_STATS_ENABLED=true          # Включить агрегированную статистику
AGENT_PERSISTENCE_ENABLED=true    # Включить persistence
```

### Возможности

| Компонент | Описание |
|-----------|----------|
| **AgentStateRepo** | Хранение метаданных и статистики агентов |
| **TaskHistoryRepo** | Полная история задач с input/output и TTL |
| **AgentStatsRepo** | Ежедневная агрегированная статистика |
| **HandoffHistoryRepo** | История handoffs между агентами |

### Использование в Python

```python
from tg_parser.agents import AgentPersistence, AgentRegistry
from tg_parser.storage.sqlite import (
    SAAgentStateRepo,
    SATaskHistoryRepo,
    SAAgentStatsRepo,
    SAHandoffHistoryRepo,
)

# Создать persistence layer
persistence = AgentPersistence(
    agent_state_repo=SAAgentStateRepo(session_factory),
    task_history_repo=SATaskHistoryRepo(session_factory, default_retention_days=14),
    agent_stats_repo=SAAgentStatsRepo(session_factory),
    handoff_history_repo=SAHandoffHistoryRepo(session_factory),
)

# Registry с persistence
registry = AgentRegistry(persistence=persistence)

# Регистрация с восстановлением статистики
await registry.register_with_persistence(agent)

# Запись задачи с полным input/output
task_id = await registry.record_task_completion_with_persistence(
    name="ProcessingAgent",
    task_type="process_message",
    input_data={"text": "...", "source_ref": "tg_test_1"},
    output_data={"summary": "...", "topics": ["..."]},
    processing_time_ms=150,
    success=True,
)

# Получить статистику агента за 30 дней
summary = await persistence.get_agent_summary("ProcessingAgent", days=30)
print(f"Total tasks: {summary['total_tasks']}")
print(f"Success rate: {summary['success_rate']:.1%}")
print(f"Avg time: {summary['avg_processing_time_ms']:.0f}ms")

# Очистка истёкших записей
deleted = await persistence.cleanup_expired_tasks()
print(f"Cleaned up {deleted} expired records")
```

### Таблицы в processing_storage.sqlite

| Таблица | Назначение |
|---------|------------|
| `agent_states` | Метаданные агентов, capabilities, накопленная статистика |
| `task_history` | Полный input/output задач с expires_at для TTL |
| `agent_stats` | Ежедневные агрегаты: total_tasks, successful, failed, avg_time |
| `handoff_history` | История handoffs: source → target, status, processing_time |

---

## Production Deployment

**v3.1.0** полностью готов к production deployment!

### Quick Start (Production)

```bash
# 1. Clone проект
git clone <repo-url>
cd TG_parser

# 2. Setup environment
cp env.production.example .env
# Отредактируйте .env с вашими credentials

# 3. Start services (PostgreSQL + TG_parser)
docker compose up -d

# 4. Verify
curl http://localhost:8000/health
```

### Production Features ✅

- ✅ **PostgreSQL 16** — production-grade database
- ✅ **Connection Pooling** — efficient connection management
- ✅ **Multi-user Support** — concurrent access
- ✅ **Docker Compose** — полный stack (PostgreSQL + TG_parser)
- ✅ **Health Checks** — database + pool metrics
- ✅ **Structured Logging** — JSON logs для ELK/Loki
- ✅ **Prometheus Metrics** — `/metrics` endpoint
- ✅ **435 Tests** — 100% pass rate

### Production Guides

**Обязательно прочитайте:**

1. **[PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md)** (500+ lines)
   - Server setup (Ubuntu 22.04)
   - PostgreSQL configuration
   - Docker Compose deployment
   - SSL/TLS setup (Nginx)
   - Monitoring (Prometheus, CloudWatch, Datadog)
   - Backup strategy (automated daily)
   - Troubleshooting
   - Security checklist

2. **[MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](../MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md)** (400+ lines)
   - When to migrate (decision matrix)
   - Pre-migration checklist
   - Step-by-step instructions
   - Verification procedures
   - Rollback strategy
   - Troubleshooting
   - FAQ (10+ вопросов)

3. **[ENV_VARIABLES_GUIDE.md](../ENV_VARIABLES_GUIDE.md)**
   - Все DB_* переменные
   - Connection pool parameters
   - Production recommendations

### Docker Compose

**Production stack:**

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  tg_parser:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DB_TYPE: postgresql
      DB_HOST: postgres
      # ... other vars from .env
    ports:
      - "8000:8000"
```

**Start:**
```bash
docker compose up -d
```

**Logs:**
```bash
# Structured JSON logs
docker compose logs tg_parser -f | jq '.'
```

**Health:**
```bash
curl http://localhost:8000/health | jq '.'
```

### Monitoring

**Prometheus metrics:**
```bash
curl http://localhost:8000/metrics
```

**Grafana:**
- См. [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md) для dashboard setup

---

## Дополнительная информация

### Guides & Documentation

**Production:**
- 🚀 [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md) — production deployment guide
- 🔄 [MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](../MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md) — database migration
- ⚙️ [ENV_VARIABLES_GUIDE.md](../ENV_VARIABLES_GUIDE.md) — environment variables

**Migration:**
- [Migration Guide v2→v3](../MIGRATION_GUIDE_v2_to_v3.md) — v2 to v3 upgrade guide

**Architecture:**
- [Architecture](architecture.md) — система архитектура
- [Data Architecture](DATA_ARCHITECTURE.md) ⭐ — архитектура данных: таблицы БД, файлы, связи
- [Pipeline](pipeline.md) — детали обработки данных
- [Data Flow](DATA_FLOW.md) — поток данных
- [Data Contracts](contracts/) — JSON Schema контракты

**Configuration:**
- [LLM Setup Guide](../LLM_SETUP_GUIDE.md) — LLM провайдеры setup
- [LLM Prompts](LLM_PROMPTS.md) — промпты для LLM
- [Technical Requirements](technical-requirements.md) — технические требования

**Session Summaries:**
- [SESSION24_COMPLETE_SUMMARY.md](../SESSION24_COMPLETE_SUMMARY.md) — PostgreSQL + Production Ready
- [SESSION23_SUMMARY.md](../SESSION23_SUMMARY.md) — Structured Logging + GPT-5
- [SESSION22_SUMMARY.md](../SESSION22_SUMMARY.md) — Alembic Migrations

