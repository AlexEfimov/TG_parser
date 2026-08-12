# Session 29: Модульный рефакторинг — планирование

**Дата:** 21 марта 2026  
**Версия:** v3.3.0  
**Приоритет:** High  
**Тип сессии:** Планирование (без написания кода)

---

## Цель Session 29

Обсудить, сформулировать и утвердить **детальный план рефакторинга проекта** с целью сделать модули максимально независимыми друг от друга. В рамках этого плана также решить проблему SQLite-наследия — проект перешёл на PostgreSQL, но в коде осталось значительное количество SQLite-специфичных артефактов.

Результат сессии — документ-план с конкретными шагами, приоритетами и критериями готовности. Код в этой сессии не пишем.

---

## Мотивация

Проект вырос до 91 Python-файла в 9 модулях. Две ключевые проблемы:

### A. Модульная связанность
Модули формально разделены по папкам, но имеют неявные и нежелательные зависимости:
- Затрудняют тестирование модулей в изоляции
- Создают хрупкие связи (изменение в одном модуле ломает другой)
- Мешают потенциальному переиспользованию модулей (например, замена Telegram-источника на RSS)
- Усложняют онбординг — трудно понять, где заканчивается один модуль и начинается другой

### B. SQLite-наследие
Проект перешёл на PostgreSQL как основную БД, но повсюду остались SQLite-артефакты:
- Папка `storage/sqlite/` — название вводит в заблуждение (код внутри работает с обеими БД через SQLAlchemy)
- 52 Python-файла упоминают sqlite
- Есть реальные баги при работе с PostgreSQL (см. раздел ниже)
- `pyproject.toml` не содержит PostgreSQL-драйверов (`asyncpg`, `psycopg2-binary`)
- Дефолт `db_type` в settings — `"sqlite"`

Эти две проблемы переплетены: SQLite-cleanup — естественная часть рефакторинга модуля `storage/`.

---

## Текущая архитектура

### 9 модулей проекта

```
tg_parser/
├── domain/       — доменные модели (Pydantic v2), ID-хелперы, валидация
├── config/       — Pydantic-settings конфигурация, настройка логирования
├── storage/      — абстракции репозиториев (ports) + реализация в sqlite/
├── ingestion/    — скачивание сообщений из Telegram через Telethon
├── processing/   — AI-обработка сообщений (pipeline) + топикизация + LLM-клиенты
├── export/       — экспорт тем и KB в NDJSON/JSON
├── agents/       — мульти-агентная система (OpenAI Agents SDK)
├── api/          — FastAPI HTTP-сервер, маршруты, middleware
└── cli/          — Typer CLI — оркестрирует все модули
```

### Граф зависимостей (текущий)

```
              domain         config
             (leaf)          (leaf)
               │                │
    ┌──────────┼────────────────┼──────────────┐
    │          │                │              │
    ▼          ▼                ▼              ▼
 storage    processing      ingestion      export
    │          │  ▲             │
    │          │  │             │
    │          ▼  │             │
    │       agents             │
    │          │               │
    ▼          ▼               ▼
    └──────── api ─────────────┘
               │
               ▼
              cli  (верхний уровень — связывает всё)
```

Направление импортов: стрелка показывает «зависит от».

### Оценка автономности модулей

| Модуль | Автономность | Зависит от | Проблемы |
|--------|-------------|------------|----------|
| `domain` | **100%** | ничего из tg_parser | Идеально — чистый shared kernel |
| `config` | **100%** | ничего из tg_parser | Идеально — leaf module |
| `storage` | **~90%** | domain, config | Нормально для инфраструктурного слоя |
| `ingestion` | **~85%** | domain, config, storage.ports | Работает через абстракции — хорошо |
| `processing` | **~70%** | domain, config, storage.ports | `factory.py` читает глобальный config напрямую |
| `export` | **~75%** | domain, storage.sqlite.json_utils | Прямая зависимость на конкретную реализацию |
| `agents` | **~50%** | domain, config, processing, storage (конкретные sqlite-репо) | Много прямых зависимостей |
| `api` | **~40%** | config, storage, agents, **cli.process_cmd** | Импорт из CLI — инверсия слоёв |
| `cli` | Оркестратор | всё | Содержит бизнес-логику, которая должна жить отдельно |

---

## SQLite-наследие: детальный аудит

### Реальные баги при работе с PostgreSQL

| # | Проблема | Файл | Строки | Суть |
|---|----------|------|--------|------|
| 1 | Хардкод SQLite URL | `api/health_checks.py` | ~246 | `check_agent_registry()` всегда строит `sqlite+aiosqlite:///` URL, полностью игнорируя `db_type` — **баг на продакшене** |
| 2 | Отсутствует partial index | `scripts/init_postgres.py` | — | `topic_bundle_repo.py:85-95` использует `ON CONFLICT` с `WHERE` clause, который требует partial unique index; этот индекс есть в SQLite-схеме, но отсутствует в PostgreSQL DDL — **UPSERT падает на PostgreSQL** |
| 3 | `sqlite_master` в health check | `api/health_checks.py` | ~77-79 | Запрос `SELECT name FROM sqlite_master` — уже есть ветвление по `db_type`, но код хрупкий |

### Вводящие в заблуждение названия и дефолты

| Проблема | Где | Суть |
|----------|-----|------|
| Папка `storage/sqlite/` | вся папка | Название подразумевает SQLite, но код внутри — универсальный SQLAlchemy + `text()`, работает с обеими БД |
| `DatabaseConfig` legacy-класс | `storage/sqlite/database.py:39-46` | Методы всегда возвращают `sqlite+aiosqlite:///` URL; используется только при создании через `Database(config)`, а не через `Database.from_settings()` |
| `db_type` дефолт = `"sqlite"` | `config/settings.py` | Дефолтное значение — sqlite, хотя основная БД — PostgreSQL |
| DDL-схемы под SQLite | `storage/sqlite/schemas/` | `AUTOINCREMENT`, `INTEGER` для boolean, `CHECK(x IN (0, 1))` — SQLite-специфичный синтаксис |

### Отсутствующие зависимости

| Файл | Проблема |
|------|----------|
| `pyproject.toml` | **Нет** `asyncpg` и `psycopg2-binary` — PostgreSQL-драйверы есть только в `requirements.txt` |

### Масштаб

- **52 Python-файла** упоминают sqlite (в коде, не только в пути)
- **9 Python-файлов** содержат PostgreSQL-специфичный код
- Репозитории используют `text()` SQL — в основном портабельный, но с исключениями выше

---

## Выявленные проблемы связанности модулей

### 1. `api` → `cli` (критическая инверсия слоёв)

`api/routes/process.py` импортирует `run_processing` из `cli/process_cmd.py`. API-сервер не должен зависеть от CLI — это нарушение направления зависимостей. Оба модуля (api и cli) должны вызывать общий сервисный слой.

### 2. `export` → `storage.sqlite.json_utils` (утечка реализации)

`export/kb_export.py` импортирует `stable_json_dumps` из `storage/sqlite/json_utils.py`. Модуль экспорта завязан на конкретную реализацию хранилища. Утилита сериализации должна быть в `domain` или отдельном `utils`.

### 3. Бизнес-логика в `cli/` (размытие ответственности)

CLI-команды (`process_cmd.py`, `topicize_cmd.py`, `run_cmd.py`) содержат логику создания пайплайнов, конфигурирования LLM-клиентов, wiring зависимостей. Это затрудняет переиспользование той же логики из `api/` или `agents/`.

### 4. `processing.llm.factory` читает глобальный config

`resolve_llm_config()` в `factory.py` напрямую импортирует и читает `config.settings`. Модуль обработки не получает конфигурацию через инъекцию — он сам её достаёт.

### 5. `agents/` использует конкретные sqlite-репозитории

`agents/persistence.py` и специализированные агенты импортируют конкретные реализации из `storage/sqlite/` вместо абстракций из `storage/ports.py`.

### 6. Отсутствие сервисного слоя (services)

Нет единого места для бизнес-логики уровня «запустить полный pipeline», «запустить обработку канала», «запустить топикизацию». Эта логика дублируется между CLI, API и agents.

---

## Файловый состав модулей (для справки)

### `domain/` (4 файла)
- `models.py` — RawTelegramMessage, ProcessedDocument, TopicCard, TopicBundle, Entity, KnowledgeBaseEntry
- `ids.py` — make_source_ref, make_processed_document_id, make_topic_id, make_kb_*
- `contract_validation.py` — валидация контрактов между слоями

### `config/` (3 файла)
- `settings.py` — Settings (Pydantic), включая per-stage LLM overrides, DB-настройки
- `logging.py` — настройка structlog

### `storage/` (22 файла)
- `ports.py` — абстрактные интерфейсы репозиториев (IngestionStateRepo, RawMessageRepo, ProcessedDocumentRepo, TopicCardRepo, TopicBundleRepo, ProcessingFailureRepo и др.)
- `engine_factory.py` — создание SQLAlchemy engine (поддерживает sqlite и postgresql)
- `sqlite/` — реализации всех репозиториев (название вводит в заблуждение — код универсальный):
  - `database.py` — Database class (dual-backend через `from_settings()`, legacy SQLite через `DatabaseConfig`)
  - `*_repo.py` — 10 репозиториев (raw_message, processed_document, topic_card, topic_bundle, ingestion_state, processing_failure, job, agent_state, agent_stats, handoff_history, task_history)
  - `json_utils.py` — утилиты сериализации JSON
  - `schemas/` — DDL-схемы (SQLite-специфичные: AUTOINCREMENT, INTEGER boolean)

### `ingestion/` (4 файла)
- `interfaces.py` — абстракция IngestionClient
- `orchestrator.py` — IngestionOrchestrator
- `telegram/telethon_client.py` — Telethon реализация

### `processing/` (14 файлов)
- `pipeline.py` — ProcessingPipelineImpl (обработка сообщений через LLM)
- `topicization.py` — TopicizationPipelineImpl (кластеризация в темы)
- `ports.py` — LLMClient абстракция
- `prompts.py`, `topicization_prompts.py` — шаблоны промптов
- `llm/` — фабрика и реализации: AnthropicClient, OpenAIClient, GeminiClient, OllamaClient, RateLimiter

### `export/` (5 файлов)
- `kb_export.py` — экспорт Knowledge Base в NDJSON
- `topics_export.py` — экспорт тем в JSON
- `kb_mapping.py` — маппинг моделей → KB-формат
- `telegram_url.py` — резолв URL Telegram-сообщений

### `agents/` (13 файлов)
- `base.py`, `orchestrator.py`, `processing_agent.py` — базовые агенты
- `persistence.py` — персистентность состояния агентов
- `registry.py` — реестр агентов
- `specialized/` — специализированные агенты (processing, topicization, export)
- `tools/` — инструменты агентов (pipeline_tool, text_tools)

### `api/` (12 файлов)
- `main.py` — FastAPI app
- `routes/` — маршруты (process, export, health, agents)
- `middleware/` — logging, rate_limit
- `auth.py`, `webhooks.py`, `scheduler.py`, `metrics.py`

### `cli/` (14 файлов)
- `app.py` — Typer app, все команды
- `*_cmd.py` — реализация команд (ingest, process, topicize, export, agents, api, db, run)

---

## Вопросы для обсуждения

### Стратегические решения

1. **Порядок: сначала hotfix PostgreSQL-багов или всё вместе?**
   - **Вариант A:** Сначала hotfix (30 мин) — починить 2 PostgreSQL-бага + добавить драйверы в `pyproject.toml`, затем полный рефакторинг
   - **Вариант B:** Включить всё в единый план рефакторинга

2. **Полностью отказаться от SQLite или сохранить dual-backend?**
   - **Вариант A:** Убрать SQLite полностью — упрощает код, но теряем возможность быстрого локального запуска без PostgreSQL
   - **Вариант B:** Сохранить dual-backend, но вычистить SQLite-специфичные артефакты и исправить naming
   - **Вариант C:** Сохранить dual-backend, но сделать PostgreSQL дефолтом (`db_type` default = `"postgresql"`)

### Архитектурные решения

3. **Нужен ли отдельный слой `services/`?** Если да — что в нём должно быть? Варианты:
   - `ProcessingService` — создание pipeline, запуск обработки
   - `TopicizationService` — запуск топикизации
   - `ExportService` — экспорт данных
   - `FullPipelineService` — ingest → process → topicize → export

4. **Как передавать конфигурацию в модули?** Варианты:
   - **Текущий подход:** глобальный `from config import settings` (просто, но создаёт жёсткую связь)
   - **Dependency Injection:** передавать settings как параметр (гибко, но больше boilerplate)
   - **Service Locator:** registry зависимостей (компромисс)

5. **Что делать с `agents/`?** Модуль сильно связан и использует OpenAI Agents SDK. Варианты:
   - Рефакторить на ports + DI как остальные модули
   - Оставить как есть (опционный модуль, не используется в основном flow)
   - Вынести в отдельный пакет/плагин

6. **Стоит ли разделять `processing/` на два модуля?** Сейчас `pipeline.py` (обработка сообщений) и `topicization.py` (кластеризация) — это по сути разные задачи, объединённые в одном модуле. Разделение дало бы:
   - `processing/` — обработка отдельных сообщений через LLM
   - `topicization/` — кластеризация обработанных документов в темы

7. **Как переименовать `storage/sqlite/`?** Варианты:
   - `storage/repositories/` — нейтральное название
   - `storage/impl/` — подчёркивает, что это реализация портов
   - `storage/sqlalchemy/` — точно отражает технологию

8. **Нужен ли модуль `utils/` или `shared/`?** Для утилит вроде `json_utils`, `telegram_url`, которые используются несколькими модулями.

### Приоритеты

9. **Какие проблемы решать первыми?** Предлагаемый порядок:
   - P0 (hotfix): PostgreSQL-баги в `health_checks.py` и `topic_bundle_repo.py` + зависимости в `pyproject.toml`
   - P1: `api → cli` инверсия слоёв (ломает архитектуру)
   - P2: Сервисный слой (уменьшает дублирование)
   - P3: Переименование `storage/sqlite/` + вычистка SQLite-артефактов
   - P4: `export → sqlite` утечка реализации
   - P5: DI для `processing.llm.factory`
   - P6: `agents` → ports вместо конкретных репо

10. **Нужно ли менять структуру папок?** Или достаточно изменить только импорты?

### Ограничения

11. **Обратная совместимость CLI:** все команды (`tg-parser process`, `tg-parser topicize` и т.д.) должны работать как прежде
12. **Тесты:** существующие тесты не должны ломаться
13. **Инкрементальность:** рефакторинг нужно делать по шагам, каждый из которых оставляет проект в рабочем состоянии
14. **Dual-backend:** если решим сохранить поддержку SQLite — оба backend должны работать после каждого шага

---

## Ожидаемый результат сессии

1. **Утверждённый план рефакторинга** — конкретные шаги с описанием изменений
2. **Решение по SQLite** — убираем, сохраняем dual-backend или меняем дефолт
3. **Приоритеты** — порядок выполнения шагов
4. **Целевой граф зависимостей** — как должна выглядеть архитектура после рефакторинга
5. **Критерии готовности** — как проверить, что каждый шаг выполнен корректно
6. **Оценка трудозатрат** — примерная сложность каждого шага

---

## Контекст проекта

- **Стек:** Python 3.12+, Pydantic v2, SQLAlchemy 2.0 (async), Telethon, FastAPI, Typer, httpx, structlog
- **Внешние API:** Anthropic (Claude), OpenAI (GPT), Google (Gemini), Telegram
- **БД:** PostgreSQL (основная, production), SQLite (legacy, используется в тестах)
- **Драйверы:** `aiosqlite` (в pyproject.toml), `asyncpg` + `psycopg2-binary` (только в requirements.txt)
- **Тесты:** pytest, ~91 Python файлов в проекте
- **Git:** основная ветка `main`, последний коммит `b6965cd`
