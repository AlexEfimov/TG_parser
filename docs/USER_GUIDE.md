# TG_parser — Руководство пользователя

**Версия:** 4.3  
**Обновлено:** April 2026

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

**v4.3:**
- **MCP Server** — 24 инструмента для AI-агентов (Claude Desktop, Cursor)
- **Telegram Bot** — Gemini-powered agent с 24 tools и free-form чатом
- **Multi-Tenancy** — пользователи, роли (admin/user), channel ownership, auth mappings
- **REST API** — User Management endpoints (`/api/v1/users`)
- **Migration CLI** — `tg-parser migrate-users` для перехода на мульти-тенантную модель
- **Embedding + RAG** — семантический поиск и Q&A по базе знаний
- **Cross-channel analytics** — связи между темами из разных каналов
- **Production stack** — Docker Compose, Nginx + TLS, Prometheus + Grafana
- 1266 тестов (100% pass rate)
- ✅ **Production Ready** для enterprise deployment

## Содержание

1. [Установка и настройка](#установка-и-настройка)
2. [Database Setup (PostgreSQL)](#database-setup)
3. [Конфигурация](#конфигурация)
4. [Scheduled Digests (F6)](#scheduled-digests-f6)
5. [CLI команды](#cli-команды)
5. [Multi-Tenancy и управление пользователями](#multi-tenancy-и-управление-пользователями)
6. [HTTP API](#http-api)
7. [Logging](#logging)
8. [Мониторинг](#мониторинг)
9. [Примеры использования](#примеры-использования)
10. [Production Deployment](#production-deployment)
11. [Troubleshooting](#troubleshooting)

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

TG_parser использует **PostgreSQL** с расширением **pgvector** для хранения данных и семантического поиска.

> ✅ **Production deployed**: 5 каналов, 5400+ документов

```bash
# 1. Start PostgreSQL с Docker Compose
docker compose up -d postgres

# 2. Configure в .env:
DB_HOST=localhost      # или 'postgres' внутри Docker
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=SECURE_PASSWORD_HERE

# 3. Initialize schema (via Alembic migrations)
tg-parser db upgrade

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
```

**Преимущества:**
- ✅ Native multi-user support
- ✅ Connection pooling для производительности
- ✅ pgvector для семантического поиска
- ✅ Enterprise-grade reliability
- ✅ Advanced indexing

**Guides:**
- [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md) — полный production guide
- [ENV_VARIABLES_GUIDE.md](../../ENV_VARIABLES_GUIDE.md) — все DB_* переменные

### Connection Pool Tuning

TG_parser creates **3 separate SQLAlchemy engine pools** — one for each logical database role:

| Pool | Purpose |
|------|---------|
| `ingestion` | Ingestion state tracking (sources, attempts) |
| `raw` | Raw message storage |
| `processing` | Processed documents, topics, embeddings |

Each pool uses `DB_POOL_SIZE` persistent connections and can burst up to `DB_MAX_OVERFLOW` additional connections.

**Capacity formula:**

```
replicas × 3 × (DB_POOL_SIZE + DB_MAX_OVERFLOW)  <  pg max_connections
```

**Defaults:** `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=10` → one process uses 3 × 15 = **45 connections**.

| Deployment | Processes | Max connections needed | PostgreSQL `max_connections` |
|---|---|---|---|
| Dev (single) | 1 | 45 | 100 (default) ✅ |
| Production (2 replicas) | 2 | 90 | 100 (tight — raise to 150+) |
| Production (3+ replicas) | 3+ | 135+ | Set to `replicas × 50` or use PgBouncer |

**Tuning recommendations:**

```bash
# Conservative settings for a single process
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10

# Higher throughput (more parallel pipeline workers)
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
# → 1 process = 3 × 30 = 90 connections (raise pg max_connections to 200+)
```

If you run multiple replicas behind a load balancer, consider [PgBouncer](https://www.pgbouncer.org/) in front of PostgreSQL to multiplex connections.

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

### Конфигурация промптов (YAML)

Все LLM-промпты хранятся в YAML файлах в директории `prompts/`. Их можно редактировать без перезапуска — изменения подхватываются через `reload_prompts` (MCP/bot tool, admin-only).

**Файлы промптов:**

| Файл | Назначение |
|------|-----------|
| `processing.yaml` | Извлечение структурированных данных из сообщений |
| `topicization.yaml` | Кластеризация сообщений в темы |
| `rag.yaml` | RAG Q&A — ответы по базе знаний |
| `bot.yaml` | System prompt для Telegram-бота |
| `merge.yaml` | Дедупликация тем при мультибатчинге |
| `incremental_discover.yaml` | Инкрементальное обнаружение новых тем |

**Кастомная директория:**

```env
# В .env — переопределить путь к промптам (по умолчанию: ./prompts)
PROMPTS_DIR=/path/to/custom/prompts
```

**Каждый YAML содержит:**
- `system.prompt` — системный промпт
- `user.template` — шаблон пользовательского промпта с `{переменными}`
- `model.temperature`, `model.max_tokens` — параметры генерации

**Per-stage LLM overrides:**

```env
# Отдельный LLM для RAG (по умолчанию — глобальный LLM_PROVIDER/LLM_MODEL)
RAG_LLM_PROVIDER=openai
RAG_LLM_MODEL=gpt-4o

# Другие stage overrides
PROCESSING_LLM_PROVIDER=anthropic
PROCESSING_LLM_MODEL=claude-haiku-4-5-20251001
TOPICIZATION_LLM_PROVIDER=anthropic
TOPICIZATION_LLM_MODEL=claude-sonnet-4-20250514
```

Приоритет: stage override → global override → stage .env → global .env.

---

## Hybrid Search (F5-A Phase 1)

Поиск и RAG Q&A по базе знаний по умолчанию используют **hybrid retrieval** — комбинацию семантического поиска (pgvector cosine) и полнотекстового поиска (PostgreSQL FTS `ts_rank_cd`) с объединением результатов через **Reciprocal Rank Fusion (RRF)**. Это даёт лучшую отдачу на коротких запросах с редкими терминами/именами и на запросах, где семантика рушится из-за жаргона.

### Режимы (`mode`)

| Режим | Что делает | Когда использовать |
|-------|-----------|--------------------|
| `semantic` | Только pgvector cosine | Парафразы, смысловые запросы |
| `keyword` | Только FTS (`plainto_tsquery` + `ts_rank_cd`) | Точные термины, имена, аббревиатуры |
| `hybrid` (default) | `semantic` + `keyword` через RRF | Общий случай — безопасный дефолт |

`POST /api/v1/search` и `/api/v1/ask` принимают поле `mode` в теле запроса. Начиная с Phase 2 MCP-инструменты `search_knowledge_base` и `ask_question` также принимают параметр `mode` (значения те же: `semantic` | `keyword` | `hybrid`, дефолт `hybrid`).

### Multilingual FTS

STORED `tsvector` столбцы `processed_documents.search_vector` и `topic_cards.search_vector` содержат три слоя: `simple` (A-вес), `russian` (B) и `english` (B). Это позволяет одному и тому же полю матчиться как русскому, так и английскому запросу без дублирования данных.

### Конфигурация

```env
HYBRID_ENABLED=true          # false → silent downgrade hybrid→semantic
HYBRID_RRF_K=60              # RRF-константа; 60 — канонический дефолт
FTS_LANGUAGES=russian,english  # informational; зашито в DDL search_vector
```

### Миграции и table rewrite

Hybrid search требует двух миграций (`d4e5f6a7b8c9`, `e5f6a7b8c9d0`), которые добавляют STORED столбцы `search_vector` с `GENERATED ALWAYS AS ... STORED` и GIN-индексы. **Важно:** `ADD COLUMN ... GENERATED ... STORED` в PostgreSQL вызывает **table rewrite** — для продакшн-БД с > 1M строк применять в maintenance-окно.

```bash
# Применить миграции
python -m tg_parser.cli migrate --target head

# Проверить текущий head
python -m tg_parser.cli migrate --show-current
```

---

## RAG Context Structure & Type Quotas (F5-A Phase 2)

Начиная с Phase 2 RAG Q&A (`ask_question` / `POST /api/v1/ask`) собирает контекст для LLM из **двух отдельных секций**:

- `## Related Topics` — блоки с префиксом `[T1]`, `[T2]`, …, содержат `title`, `summary`, `scope`, `tags` и список каналов-источников. Используются LLM для тематического обрамления ответа.
- `## Source Messages` — блоки с префиксом `[M1]`, `[M2]`, …, содержат `channel`, `ref`, текст (truncated до `context_char_limit`) и темы. Используются для конкретных фактов.

Префиксы `[T1]` / `[M1]` — **только визуальные метки** внутри контекста. Для цитирования LLM просят использовать `ref`-значение (например, `[tg:channel:post:123]` или `[topic:…]`), а не индекс. Версия промпта — `prompts/rag.yaml` v1.2.0.

### Квотирование тем и сообщений

`answer()` теперь:

1. Делает `search(limit=limit * RAG_SEARCH_OVERFETCH_FACTOR)` для «headroom».
2. Применяет `_apply_type_quotas`: берёт до `RAG_TOPIC_QUOTA` карточек тем, остальное — сообщениями.
3. При недоборе в одну сторону backfill-ит за счёт другой (если тем меньше квоты — добирает сообщениями; если сообщений нет — добирает темами).
4. Возвращает `≤ limit` источников (overfetch — внутренняя оптимизация; бот/CLI получают ровно то число, что просили).

### Настройка релевантности

```env
# FTS score cutoff для keyword-ветки (0.0 = без cutoff). Типично 0.001–0.05.
FTS_MIN_RANK=0.0
# Сколько тем резервировать в контексте RAG перед заполнением сообщениями.
RAG_TOPIC_QUOTA=2
# Множитель overfetch для headroom против недобора после квотирования.
RAG_SEARCH_OVERFETCH_FACTOR=2
```

Явный вызов `search(fts_min_rank=…)` / `answer(topic_quota=…)` переопределяет дефолты на один запрос. Semantic-ветка использует отдельный `threshold` (pgvector cosine) и `FTS_MIN_RANK` игнорирует.

> 💡 **Когда повышать `FTS_MIN_RANK`:** если в корпусе много коротких сообщений с шумной лексикой и keyword-mode возвращает слабо-релевантный хвост. Диапазон 0.001–0.05 обычно отсекает «случайные» совпадения без потери полезных.
>
> 💡 **Когда менять `RAG_TOPIC_QUOTA`:** поднимайте до 3–4 для обзорных вопросов «что было на тему X?», оставляйте `2` для фактических запросов. `0` — если темы не нужны совсем.

---

## Deduplication (F5-A Phase 3)

Processing pipeline вычисляет SHA-256 хэш от нормализованного `text_clean`
(lowercase + collapse whitespace + strip URL query strings). Если в том же
канале уже есть документ с таким же hash — новое сообщение пропускается
(не пишется в `processed_documents`, embedding не генерируется).

**Scope:** только в пределах одного `channel_id` — тот же пост в разных
каналах дубликатом не считается (multi-tenancy требует keep-separate).

**Видимое поведение:** `process_batch(...)` может вернуть список короче
`len(messages)`, если в батче были дубликаты. Caller интерпретирует diff
как «N было, M осталось после dedup».

**Конфигурация:**
- `DEDUP_ENABLED=true` (default) — выключите, чтобы вернуть поведение до
  Phase 3.
- `DEDUP_STRIP_URL_QUERY=true` (default) — снимает `?utm_*` / `#fragment`
  перед хэшированием (catches tracking-param-only variants).

**Метрика:** `tg_dedup_duplicates_detected_total{channel_id}` —
инкрементируется ровно один раз per detected duplicate.

**Backfill существующих данных:**

```bash
# Пересчитать hash для всех строк, где content_hash IS NULL
tg_parser backfill-content-hash --batch-size 1000

# Только один канал, без записи (dry-run для оценки scope'а)
tg_parser backfill-content-hash --channel-id my_channel --dry-run
```

Backfill использует cursor-пагинацию (`WHERE content_hash IS NULL LIMIT N`
в цикле), безопасно для больших таблиц. Идемпотентен: повторный запуск
пропустит уже-хэшированные строки.

---

## Scheduled Digests (F6)

Подписки на автоматические сводки (digests) по выбранным каналам с доставкой
в Telegram-чат по cron-расписанию. На каждом тике планировщик берёт
`ProcessedDocument`-ы, появившиеся **после** `last_digest_cursor` подписки,
прогоняет их через LLM с промптом `prompts/digest.yaml` и отправляет
итоговый Markdown в указанный `chat_id`.

### Как это работает

1. Пользователь создаёт подписку через Telegram-бот ("подпишись на дайджест по
   @durov каждое утро в 9") или через MCP (`subscribe_digest`).
2. Подписка сохраняется в таблице `digest_subscriptions` (БД `ingestion`) и
   регистрируется в `BackgroundScheduler` через `CronTrigger`.
3. По cron-тику запускается `run_scheduled_digests_task(subscription_id)`:
   - `DigestService.generate(...)` загружает новые документы (фильтр
     `processed_at > last_digest_cursor`, кап `DIGEST_MAX_DOCS_PER_RUN`),
     группирует их по каналам, вызывает LLM в стейдже `digest`.
   - `DigestService.deliver(...)` экранирует MarkdownV2, при необходимости
     режет сообщение на куски ≤4096 символов; если кусков больше
     `DIGEST_MAX_MESSAGE_PARTS` — отправляет полный текст файлом
     (`FSInputFile`, паттерн F2 size-gate).
   - При успешной доставке `last_digest_cursor` сдвигается до максимального
     `processed_at` среди отправленных документов; `last_sent_at = now()`.
4. Раз в `DIGEST_REFRESH_INTERVAL` секунд бот реконсилирует список jobs со
   снимком `repo.list_active()` — так подписки, созданные через MCP в другом
   процессе, подхватываются без рестарта бота.

### Cron cheat-sheet

| Cron        | Когда срабатывает                  |
| ----------- | ----------------------------------- |
| `0 9 * * *` | Каждый день в 09:00 (timezone подписки) |
| `0 */4 * * *` | Каждые 4 часа                     |
| `0 9 * * 1-5` | Будни в 09:00                     |
| `0 18 * * 5` | Каждую пятницу в 18:00              |
| `0 9 1 * *` | Первое число каждого месяца в 09:00 |

Таймзона валидируется через `zoneinfo.ZoneInfo(...)` при создании подписки —
неверное значение возвращает понятную ошибку, не 500.

### Поддерживаемые форматы

- `summary` (default) — связный краткий пересказ (3–6 абзацев).
- `bullets` — компактные пункты по каналам.
- `detailed` — расширенный обзор с подзаголовками per-channel.

Формат прокидывается в шаблон `prompts/digest.yaml` через переменную
`{format}`; LLM сам подгоняет стиль ответа.

### Настройка LLM

Стейдж `digest` поддерживает per-stage переопределение провайдера и модели:

```bash
# В .env
DIGEST_LLM_PROVIDER=anthropic
DIGEST_LLM_MODEL=claude-sonnet-4-5-20250929
```

Runtime-переключение без рестарта (через MCP):

```text
set_llm_config(scope="digest", provider="openai", model="gpt-4o-mini")
```

При отсутствии stage-override — fallback на `global` → дефолт из `.env`.

### Управление подписками

**Через бота (естественным языком):**

```text
Пользователь: подпишись на дайджест по @durov и @meduza каждое утро в 9
Bot: 📰 Подписка morning создана. Расписание: 0 9 * * * (Europe/Moscow). Каналов: 2.

Пользователь: покажи мои подписки
Bot: <list_digests output>

Пользователь: отпиши меня от дайджеста <id>
Bot: ✅ Подписка отменена.
```

**Через MCP:**

```text
subscribe_digest(name="morning", channel_ids=["@durov"], chat_id=12345,
                 cron_expression="0 9 * * *", timezone="Europe/Moscow")
list_digests()             # admin: все подписки; user: только свои
unsubscribe_digest(subscription_id="...")
```

### Ownership и лимиты

- `digest_subscriptions.owner_id` ссылается на `users.id` (FK с
  `ON DELETE CASCADE`).
- Не-админ видит/редактирует только свои подписки; админ — все.
- Каналы в `channel_ids[]` обязаны проходить `assert_channel_access(user, cid)`
  — для restricted user'а попытка подписаться на чужой канал отклоняется
  ошибкой "no access to channel ...".
- `DIGEST_MAX_DOCS_PER_RUN` (default 50) — кап документов per channel per
  тик (исключает out-of-budget runs на шумных каналах).

### Включение

```bash
# В .env
SCHEDULER_ENABLED=true       # общий switch для BackgroundScheduler
DIGEST_SCHEDULER_ENABLED=true # запускать digest-jobs в bot-процессе
DIGEST_DEFAULT_TIMEZONE=Europe/Moscow
DIGEST_REFRESH_INTERVAL=60    # секунд между реконсиляциями DB ↔ scheduler
```

Доставка происходит **только в bot-процессе** — API/CLI daemon дайджесты не
шлют, чтобы исключить дубль.

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

### `init` — Инициализация

Инициализирует конфигурацию и проверяет подключение к базе данных.

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
- `--level` — уровень экспорта: `raw` | `processed` | `full` (default: `full`, см. ниже)
- `--format` — формат для `--level raw`: `json` | `ndjson` (default: `json`)

**Выходные файлы (по уровням):**
- `full` (default): `kb_entries.ndjson` + `topics.json` + `topic_<id>.json` (legacy)
- `processed`: только `kb_entries.ndjson` (без topics)
- `raw`: `raw_messages.json` или `raw_messages.ndjson`

**Примеры:**
```bash
python -m tg_parser.cli export --out ./output

python -m tg_parser.cli export --channel @durov --out ./output

python -m tg_parser.cli export --from-date 2025-01-01 --to-date 2025-12-31 --out ./output

python -m tg_parser.cli export --out ./output --pretty
```

### Parse-Only Export (F2) — `--level raw`

**Назначение:** экспорт сырых Telegram-сообщений (`raw_messages`) без LLM-обработки.
Полезно для использования системы как чистого парсера (ETL-пайплайны, архивация, внешний анализ).

**Поддерживаемые уровни (`--level`):**

| Level | Что экспортирует | Файлы |
|-------|------------------|-------|
| `raw` | Сырые Telegram-сообщения (посты + комментарии, без LLM) | `raw_messages.{json,ndjson}` |
| `processed` | `ProcessedDocument[]` → `KnowledgeBaseEntry[]` (после LLM) | `kb_entries.ndjson` |
| `full` | `processed` + `topics.json` + `topic_<id>.json` (legacy default) | все три |

**Ограничения `--level raw`:**
- Требует `--channel` (per-channel экспорт; экспорт всех каналов сразу не поддерживается в F2).
- `--topic-id` игнорируется.
- `raw_payload` (приватные Telethon-структуры, session artifacts) **не включается** в вывод — это намеренное ограничение приватности, изменение требует отдельной фичи.

**JSON envelope vs NDJSON:**

`--format json` (envelope) — удобно для небольших каналов, агрегированная структура с группировкой комментариев под постами:

```json
{
  "schema_version": "raw_channel_export.v1",
  "channel_id": "1234567890",
  "channel_username": "example_channel",
  "exported_at": "2026-04-18T12:00:00Z",
  "filters": {"from_date": null, "to_date": null},
  "messages_count": 542,
  "comments_count": 1287,
  "orphan_comments_count": 3,
  "messages": [
    {
      "id": "987",
      "source_ref": "tg:1234567890:post:987",
      "message_type": "post",
      "date": "2026-01-15T10:30:00Z",
      "text": "Текст поста...",
      "comments": [
        {"id": "988", "parent_message_id": "987", "text": "Ответ...", "date": "..."}
      ]
    }
  ],
  "orphan_comments": []
}
```

**Orphan comments** — комментарии, чей родительский пост вне диапазона `--from-date`/`--to-date`. Сохраняются в отдельном bucket'е, чтобы не теряться молча.

`--format ndjson` (stream) — рекомендуется для больших каналов (>10K сообщений) или ETL-пайплайнов: одно сообщение на строку, без envelope, без группировки (сначала все посты по дате, потом все комментарии по дате).

**Примеры CLI:**

```bash
python -m tg_parser.cli export \
  --level raw \
  --channel @durov \
  --format json \
  --out ./raw_export

python -m tg_parser.cli export \
  --level raw \
  --channel @durov \
  --format ndjson \
  --out ./raw_export

python -m tg_parser.cli export \
  --level raw \
  --channel @durov \
  --from-date 2026-01-01 \
  --to-date 2026-03-31 \
  --format ndjson \
  --out ./raw_q1

python -m tg_parser.cli export \
  --level processed \
  --channel @durov \
  --out ./processed_export
```

**Пример API (`POST /api/v1/export`):**

```bash
curl -X POST http://localhost:8000/api/v1/export \
  -H "X-API-Key: $TG_PARSER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "1234567890",
    "level": "raw",
    "format": "json",
    "from_date": "2026-01-01T00:00:00Z"
  }'

curl http://localhost:8000/api/v1/export/status/$JOB_ID \
  -H "X-API-Key: $TG_PARSER_API_KEY"

curl -O -J http://localhost:8000/api/v1/export/download/$JOB_ID \
  -H "X-API-Key: $TG_PARSER_API_KEY"
```

Rate-limit API: 20 запросов/минуту (настройка `RATE_LIMIT_EXPORT`). Для больших каналов предпочтительнее CLI.

**Пример через Telegram-бот:**

Достаточно попросить ассистента на естественном языке:

> "Экспортируй канал @durov в raw JSON"

Бот вызовет tool `export_channel`, дождётся завершения фонового задания и:
- отправит файл в чат (если < 50 MB — лимит Telegram Bot API);
- вернёт download URL и короткую статистику (если ≥ 50 MB).

**Пример через MCP:** см. `docs/MCP_AGENT_GUIDE.md` §"export_channel".

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

### `auth` — Авторизация Telegram

Авторизует Telegram-сессию для сбора сообщений из каналов.

```bash
tg-parser auth
tg-parser auth --force   # пересоздать session-файл
```

### `embed` — Генерация embeddings

Генерирует embeddings для обработанных документов канала (необходимо для семантического поиска).

```bash
tg-parser embed --channel @durov
tg-parser embed --channel @durov --force   # переэмбеддить все
```

### `search` — Семантический поиск (CLI)

```bash
tg-parser search --query "ключевая тема"
tg-parser search --query "ключевая тема" --channel @durov --limit 5
```

### `ask` — Q&A (CLI)

```bash
tg-parser ask --question "Какие основные темы обсуждались?"
tg-parser ask --question "Какие основные темы?" --channel @durov
```

### `link-topics` — Связывание тем

Вычисляет similarity между темами разных каналов и создаёт связи.

```bash
tg-parser link-topics
tg-parser link-topics --threshold 0.5   # порог similarity (default: 0.3)
```

### `bot` — Запуск Telegram бота

```bash
tg-parser bot
```

Требует: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`.

### `mcp` — Запуск MCP-сервера

```bash
tg-parser mcp                                   # stdio (default)
tg-parser mcp --transport streamable-http        # HTTP
tg-parser mcp --transport streamable-http --host 0.0.0.0 --port 8080
```

### `scheduler` — Управление планировщиком

```bash
tg-parser scheduler start                  # daemon mode
tg-parser scheduler start --interval 1800  # каждые 30 минут
tg-parser scheduler status                 # текущее состояние
tg-parser scheduler run-once               # одноразовый запуск
tg-parser scheduler run-once --source my_channel
```

### `db` — Управление базой данных

```bash
tg-parser db upgrade          # применить миграции
tg-parser db downgrade        # откатить последнюю миграцию
tg-parser db current          # текущая ревизия
tg-parser db history          # история миграций
tg-parser db stamp <revision> # отметить ревизию без выполнения
tg-parser db backup           # создать backup
tg-parser db restore          # восстановить из backup
tg-parser db list-backups     # список backup'ов
```

### `migrate-users` — Миграция пользователей (F4)

Одноразовая миграция legacy credentials в multi-tenancy модель.

```bash
tg-parser migrate-users --dry-run   # предварительный просмотр
tg-parser migrate-users             # выполнить миграцию
```

---

## Multi-Tenancy и управление пользователями

### Обзор

Начиная с v4.3, TG_parser поддерживает мульти-тенантность: у каждого пользователя есть роль, набор привязанных credentials и лимит каналов.

| Понятие | Описание |
|---------|----------|
| **Роль** | `admin` — полный доступ ко всем каналам и операциям; `user` — доступ только к своим каналам |
| **Channel ownership** | Каждый канал (source) имеет `owner_id`; non-admin видит только свои каналы |
| **Auth mapping** | Связь «credential → user»; типы: `api_key`, `mcp_token`, `telegram` |
| **`max_channels`** | Per-user лимит каналов; `NULL` = глобальный default (`DEFAULT_MAX_CHANNELS`, по умолчанию 20) |

### Telegram Bot: команда `/start`

При отправке `/start` бот проверяет регистрацию:

- **Незарегистрированный пользователь** — бот отвечает: «Вы не зарегистрированы в системе. Обратитесь к администратору для получения доступа.»
- **Зарегистрированный пользователь** — персонализированное приветствие с именем, ролью и числом доступных каналов.

Для регистрации Telegram-пользователя администратор должен создать пользователя (`register_user`) и добавить mapping (`add_user_auth` с типом `telegram` и Telegram user ID).

### Первоначальная настройка (миграция)

Если у вас уже есть работающий deployment, запустите одноразовую миграцию:

```bash
# Предварительный просмотр (ничего не меняет)
tg-parser migrate-users --dry-run

# Выполнить миграцию
tg-parser migrate-users
```

**Что происходит:**
1. Создаётся пользователь `admin`
2. Все API-ключи из `API_KEYS` маппятся как `api_key` auth mappings (хешируются SHA-256)
3. Все MCP-токены из `MCP_AUTH_TOKENS` маппятся как `mcp_token` auth mappings (хешируются SHA-256)
4. Все Telegram user ID из `BOT_ALLOWED_USERS` маппятся как `telegram` auth mappings
5. Каналы без `owner_id` назначаются admin-пользователю

Миграция идемпотентна — безопасно запускать повторно.

### Управление пользователями

Пользователями можно управлять через MCP, Telegram Bot или REST API:

#### Через MCP / Bot

| Инструмент | Доступ | Описание |
|---|---|---|
| `register_user` | admin | Создать нового пользователя |
| `update_user` | admin | Обновить роль, имя, `max_channels` |
| `list_users` | admin | Список всех пользователей |
| `whoami` | любой | Профиль текущего пользователя |
| `add_user_auth` | admin | Привязать credential к пользователю |
| `remove_user_auth` | admin | Удалить привязку credential |

#### Через REST API

```bash
# Профиль текущего пользователя
curl -H "X-API-Key: sk-xxx" http://localhost:8000/api/v1/users/me

# Список пользователей (admin)
curl -H "X-API-Key: sk-xxx" http://localhost:8000/api/v1/users

# Создать пользователя (admin)
curl -X POST -H "X-API-Key: sk-xxx" -H "Content-Type: application/json" \
  -d '{"name": "analyst", "role": "user", "max_channels": 5}' \
  http://localhost:8000/api/v1/users

# Обновить пользователя (admin)
curl -X PATCH -H "X-API-Key: sk-xxx" -H "Content-Type: application/json" \
  -d '{"max_channels": 10}' \
  http://localhost:8000/api/v1/users/{user_id}

# Удалить пользователя (admin)
curl -X DELETE -H "X-API-Key: sk-xxx" \
  http://localhost:8000/api/v1/users/{user_id}
```

### Настройка

```env
# Лимит каналов по умолчанию (для пользователей без явного лимита)
DEFAULT_MAX_CHANNELS=20
```

> 💡 **Для AI-агентов**: см. [MCP_AGENT_GUIDE.md](MCP_AGENT_GUIDE.md) — оптимизированный справочник с полными schema всех 24 инструментов.

---

## Logging (v3.1)

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
docker compose exec postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT source_ref, error_class, error_message FROM processing_failures;"
```

### Общие проблемы

#### `ModuleNotFoundError: No module named 'tg_parser'`

**Решение:**
```bash
# Установить проект в режиме разработки
pip install -e .
```

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
from tg_parser.storage.sqlalchemy import (
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

### Таблицы для Agent Persistence (PostgreSQL)

| Таблица | Назначение |
|---------|------------|
| `agent_states` | Метаданные агентов, capabilities, накопленная статистика |
| `task_history` | Полный input/output задач с expires_at для TTL |
| `agent_stats` | Ежедневные агрегаты: total_tasks, successful, failed, avg_time |
| `handoff_history` | История handoffs: source → target, status, processing_time |

---

## Production Deployment

**v4.3** полностью готов к production deployment!

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
- ✅ **1266 Tests** — 100% pass rate

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

2. **[MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](archive/MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md)** (400+ lines, archived — SQLite больше не поддерживается)
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
- 🔄 [MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](archive/MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md) — database migration (archived)
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

