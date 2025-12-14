# TG_parser – стек технологий (зафиксировано для MVP)

Документ фиксирует **выбранный стек** под требования из `docs/technical-requirements.md` / `docs/business-requirements.md` и ADR `0001..0004` (статус **Accepted**).

## 1) Язык, окружение, зависимости

- **Язык**: Python **3.12** (TR‑1).
- **Окружение**: локально `.venv`.
- **Зависимости**: `requirements.txt` (совместимо с TR‑1); допускается использовать `uv` как быстрый installer, но артефакт фиксации — всё равно `requirements.txt`.

## 2) Контракты данных и валидация

- **Модели**: `pydantic` v2 (структуры `RawTelegramMessage`, `ProcessedDocument`, `KnowledgeBaseEntry`, `TopicCard`, `TopicBundle`).
- **Валидация контрактов JSON Schema** (инварианты/AC на стыках слоёв): `jsonschema`.
- **Быстрая JSON‑сериализация** (опционально): `orjson`.

## 3) Telegram ingestion

### 3.1 Клиент Telegram (выбор)

- **Telegram MTProto‑клиент**: `Telethon`.

Причина: Bot API‑библиотеки (например, `python-telegram-bot`) не подходят для полноценного чтения истории каналов/обсуждений “как пользователь” и упираются в ограничения Bot API. Для задач UC‑2/UC‑3/FR‑4/FR‑5 нужен MTProto‑клиент.

### 3.2 Конкурентность и ретраи

- **Конкурентность**: `asyncio` (native для Telethon) + параллельная обработка источников (TR‑2).
- **HTTP/сети (если нужно)**: `httpx` (используется и для LLM‑провайдеров).
- **Ретраи/backoff**: реализуем в коде (экспоненциальный backoff + jitter по TR‑12..TR‑13), без “магии” внешнего фреймворка.

## 4) Storage (MVP) и путь миграции

### 4.1 MVP: локальные SQLite‑хранилища (3 файла)

Согласно TR‑14/TR‑17/TR‑42 выбираем SQLite и **разделяем файлы**:
- `ingestion_state.sqlite` — источники/статусы/курсоры (TR‑14..TR‑17).
- `raw_storage.sqlite` — raw‑сообщения (TR‑18..TR‑20).
- `processing_storage.sqlite` — `ProcessedDocument` + `TopicCard` + `TopicBundle` (TR‑42..TR‑45).

### 4.2 Доступ к БД (единый слой для SQLite и Postgres)

- **DB layer**: `SQLAlchemy 2.x` (async).
  - SQLite драйвер: `aiosqlite`.
  - PostgreSQL драйвер (для серверного режима): `asyncpg`.

Причина: единый код доступа к данным при переходе SQLite → PostgreSQL (TR‑16) без изменения контрактов/логики upsert.

### 4.3 Индексы/поиск (в MVP без отдельного движка)

- В MVP полнотекст/векторный поиск **не обязателен** (интерфейс доступа — CLI‑экспорт, TR‑55..TR‑64).
- На будущее (когда появится API/поиск): PostgreSQL + **FTS** (tsvector) и/или **pgvector** для embeddings.

## 5) Processing и Topicization (ИИ)

### 5.1 Облачный LLM по умолчанию (фиксируем)

- **Провайдер по умолчанию**: облачный LLM через API (MVP) — **OpenAI**.
- **Выбор провайдера пользователем**: через конфигурацию (ENV/конфиг‑файл), например:
  - `LLM_PROVIDER=openai` (default)
  - `LLM_PROVIDER=anthropic` / `LLM_PROVIDER=openai_compatible` / и т.п.
  - дополнительно: `LLM_MODEL=<model_id>` (переопределение модели без смены провайдера)
  - дополнительно: `LLM_BASE_URL=<url>` (для OpenAI‑compatible прокси/шлюзов)
  Реализация обязана использовать **единый адаптерный интерфейс** (напр. `LLMClient.generate(...)`), чтобы смена провайдера не требовала переделки пайплайна (ADR‑0001).
- **Клиент**: `httpx` (HTTP вызовы API провайдера).
- **Секреты**: ключи/токены только через переменные окружения, без хранения в репозитории:
  - для OpenAI: `OPENAI_API_KEY`
  - для Anthropic: `ANTHROPIC_API_KEY`

### 5.2 Локальный LLM (опционально, не целевой для вашего окружения)

- **Локальный раннер** (если понадобится позже): Ollama.
- Используется только как альтернативный backend, но **не является целевым** для MVP, т.к. предполагается недостаточная мощность локального оборудования.

### 5.3 Детерминизм и воспроизводимость (обязательно)

- Для processing и topicization по умолчанию использовать параметры, минимизирующие стохастику (например `temperature=0`) и фиксировать их (TR‑38).
- В `metadata` обязательно сохранять: `pipeline_version`, `model_id`, `prompt_id` и параметры генерации (TR‑23/TR‑38/TR‑39/TR‑40).

## 6) CLI (MVP интерфейс продукта)

- **CLI**: `typer` (команды ingestion/processing/topicization/export, TR‑44/TR‑55..TR‑64).
- **Конфигурация**: `pydantic-settings` (ENV + файлы конфигурации), чтобы параметры источников/БД/LLM были воспроизводимы. В частности, LLM настраивается через `LLM_PROVIDER`/`LLM_MODEL`/`LLM_BASE_URL` и ключи провайдеров.

## 7) Качество, тестирование, стиль

- **Тесты**: `pytest`.
- **Линтер/форматтер**: `ruff` (включая `ruff format`).
- **Типизация**: `mypy` (по мере роста проекта; критично для контрактов/хранилища).
- **pre-commit**: хуки для ruff/pytest (по мере необходимости).

## 8) Наблюдаемость (MVP)

- **Логирование**: стандартный `logging` + структурирование в JSON через `structlog` (удобно для CI/серверного режима).
- Метрики запусков (TR‑50/TR‑51) — как JSON‑отчёты + логирование ключевых счётчиков.

## 9) Деплой и локальная разработка

- **Локально**: Python + `.venv`, SQLite файлы рядом с проектом (пути конфигурируемые).
- **Серверный режим (позже)**: Docker/Compose (PostgreSQL + сервис), при необходимости отдельный контейнер для Ollama.

## 10) Ключевые параметры конфигурации (MVP)

Рекомендуемые имена переменных окружения/настроек (могут быть оформлены через `pydantic-settings`):

- **SQLite пути (MVP)**:
  - `INGESTION_STATE_DB_PATH=ingestion_state.sqlite`
  - `RAW_STORAGE_DB_PATH=raw_storage.sqlite`
  - `PROCESSING_STORAGE_DB_PATH=processing_storage.sqlite`
- **LLM**:
  - `LLM_PROVIDER=openai` (default)
  - `LLM_MODEL=<model_id>`
  - `LLM_BASE_URL=<url>` (для OpenAI‑compatible)
  - `OPENAI_API_KEY=...` / `ANTHROPIC_API_KEY=...`

