# Стартовый промпт для Implementation Agent Session 7

Привет! Ты агент-разработчик для проекта TG_parser (роль из `docs/notes/agents-roles.md` строки 50-52).

## 📍 Текущее состояние проекта

**Статус**: Full MVP — Все компоненты работают, включая CLI команду `run` ✅  
**Последняя сессия**: Implementation Agent Session 6 (завершена)  
**Git**: 16+ коммитов впереди origin/main, working tree clean

### ✅ Что УЖЕ работает:

- **Ingestion (Telethon)**: сбор raw сообщений из Telegram через Telethon ✅
  - TelethonClient с методами get_messages() и get_comments()
  - IngestionOrchestrator с retry logic и error handling
  - Режимы snapshot и incremental (TR-4)
  - Per-thread курсоры комментариев (TR-7)
- **Storage**: все 6/6 репозиториев реализованы ✅
  - SQLiteIngestionStateRepo, SQLiteRawMessageRepo
  - SQLiteProcessedDocumentRepo, SQLiteProcessingFailureRepo
  - SQLiteTopicCardRepo, SQLiteTopicBundleRepo
- **Processing**: raw messages → ProcessedDocument через OpenAI LLM ✅
- **Topicization**: ProcessedDocument → TopicCard + TopicBundle ✅
- **Export**: KB entries + topics.json + topic_<id>.json ✅
- **CLI**: init, add-source, ingest, process, topicize, export, **run** ✅
- **CLI команда `run`**: one-shot pipeline (ingest → process → topicize → export) ✅ **НОВОЕ В SESSION 6**
  - `tg_parser/cli/run_cmd.py` — async run_full_pipeline()
  - Параметры: --source, --out, --mode
  - Опции: --skip-ingest, --skip-process, --skip-topicize, --force, --limit
  - Детальная статистика по каждому этапу
  - Error handling с указанием последнего успешного этапа
- **E2E Tests**: 7 тестов с mock Telegram API ✅ **ОБНОВЛЕНО В SESSION 6**
  - test_full_pipeline_e2e
  - test_incremental_mode_ingestion (TR-4)
  - test_comments_ingestion_with_per_thread_cursors (TR-6, TR-7)
  - test_error_handling_and_retry_logic (TR-12, TR-13)
  - test_run_command_full_pipeline ✅ **НОВОЕ**
  - test_run_command_with_skip_options ✅ **НОВОЕ**
  - test_run_command_error_handling ✅ **НОВОЕ**
- **Mock LLM**: ProcessingMockLLM + TopicizationMockLLM ✅ **ОБНОВЛЕНО В SESSION 6**
- **Тесты**: 85/85 проходят ✅ (+3 новых теста для команды `run` + 4 исправленных E2E теста)

### 🎯 Что НЕ работает (требует реализации):

- ❌ **Документация** — README с примерами, настройка Telethon, .env.example

## 📚 Где найти информацию

### Обязательно прочитай ПЕРВЫМ:

1. **`docs/notes/SESSION_HANDOFF.md`** (600+ строк)
   - Полное состояние всех модулей
   - Ключевые инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)

2. **`docs/notes/QUICK_START.md`** (короткий)
   - Быстрая справка за 5 минут
   - E2E сценарий что работает
   - Приоритетные задачи

### Для понимания реализованной команды `run`:

- **`tg_parser/cli/run_cmd.py`** — реализация run_full_pipeline()
- **`tg_parser/cli/app.py`** — интеграция команды `run` в CLI
- **`tests/test_e2e_pipeline.py`** (строки 740+) — тесты для команды `run`

## 🎯 Рекомендуемые задачи (по приоритету)

### Task 8: Документация (~2-3 часа) 🔥 ПРИОРИТЕТ #1

**Файлы для обновления/создания**:
- `README.md` — основная документация
- `.env.example` — пример конфигурации
- `docs/INSTALLATION.md` — инструкция по установке (опционально)

**Что делать**:

1. **README.md** (~1-2 часа)
   - Описание проекта (что делает, зачем нужен)
   - Quick Start (установка + первый запуск)
   - Примеры использования всех команд (включая новую `run`)
   - Требования и установка
   - Структура проекта

2. **Telethon Setup** (~0.5-1 час)
   - Получение API credentials (api.telegram.org)
   - Настройка .env файла
   - Первый запуск и авторизация
   - Troubleshooting

3. **.env.example** (~0.5 часа)
   - Пример всех настроек с комментариями
   - Обязательные и опциональные параметры

### Дополнительные задачи (низкий приоритет):

- Исправить deprecation warning: `datetime.utcnow()` → `datetime.now(UTC)` в `tg_parser/export/topics_export.py:152`
- Добавить dry-run режим для команды `run`
- Улучшить прогресс-бары в CLI

---

## 🚀 Быстрая проверка состояния

```bash
# Активировать окружение
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверить тесты (должно быть 85 passed)
pytest

# Проверить lint
ruff check .

# Проверить CLI (все команды)
python -m tg_parser.cli --help

# Проверить команду run
python -m tg_parser.cli run --help

# Полный one-shot pipeline (требует настроенный Telethon)
python -m tg_parser.cli run --source my_channel --out ./output

# Git статус
git log --oneline -5
git status
```

---

## 📋 Твоя роль (из agents-roles.md)

> Ты агент-разработчик для проекта TG_parser.  
> Пиши и изменяй только код, строго следуя контрактам из `docs/contracts/*.schema.json`, архитектурным документам (`docs/architecture.md`, `docs/pipeline.md`) и ADR в `docs/adr/`.  
> Не редактируй бизнес- и технические документы, если явно не попросили.

---

## ⚠️ Важные правила

- ✅ Все изменения должны проходить `pytest` (85+ тестов)
- ✅ Форматирование: `ruff format .` и `ruff check .`
- ✅ Следовать контрактам из `docs/contracts/*.schema.json`
- ✅ Соблюдать инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)
- ✅ Создавать тесты для новой функциональности
- ❌ НЕ менять архитектуру без ADR
- ❌ НЕ добавлять новые зависимости без обоснования

---

## 🎬 Как начать

1. Прочитай `docs/notes/SESSION_HANDOFF.md` полностью
2. Изучи текущий README.md (если есть)
3. Посмотри существующие CLI команды для примеров использования
4. Начни с Task 8 (Документация) — обнови/создай README.md
5. Создай .env.example с примерами конфигурации

---

## 💡 Что было сделано в Session 6

### CLI команда `run` (Task 7) — ЗАВЕРШЕНО ✅

**Созданные файлы**:
- `tg_parser/cli/run_cmd.py` — async run_full_pipeline()

**Изменённые файлы**:
- `tg_parser/cli/app.py` — интеграция команды `run`
- `tg_parser/processing/mock_llm.py` — добавлен TopicizationMockLLM
- `tests/test_e2e_pipeline.py` — 3 новых теста + исправления 4 существующих

### Исправленные E2E тесты:

1. **test_full_pipeline_e2e** — использует TopicizationMockLLM для topicization
2. **test_incremental_mode_ingestion** — mock использует convert_func для RawTelegramMessage
3. **test_comments_ingestion_with_per_thread_cursors** — исправлен post_id вместо thread_id
4. **test_error_handling_and_retry_logic** — mock использует convert_func

### Ключевые исправления:

- `ProcessingMockLLM` возвращает JSON для processing (text_clean, summary, topics, entities)
- `TopicizationMockLLM` возвращает JSON для topicization (topics с anchors и score)
- Mock TelethonClient.get_comments() использует `post_id` (не `thread_id`)
- Mock функции используют `convert_func` для создания правильных RawTelegramMessage

---

## 📝 README.md структура (рекомендация)

```markdown
# TG_parser

Парсер Telegram каналов для создания структурированной базы знаний.

## Features

- 📥 Сбор сообщений и комментариев из Telegram каналов (Telethon)
- 🤖 Обработка через LLM (OpenAI) для извлечения структуры
- 🏷️ Автоматическая тематизация контента
- 📤 Экспорт в формате JSONL для RAG систем

## Quick Start

### 1. Установка

```bash
git clone <repo>
cd TG_parser
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройка

```bash
cp .env.example .env
# Отредактируй .env с твоими credentials
```

### 3. Telegram API

1. Перейди на https://my.telegram.org
2. Создай приложение и получи API_ID + API_HASH
3. Добавь в .env

### 4. Первый запуск

```bash
# Инициализация БД
python -m tg_parser.cli init

# Добавить источник
python -m tg_parser.cli add-source --source-id my_source --channel-id @channel_name

# One-shot pipeline (рекомендуется)
python -m tg_parser.cli run --source my_source --out ./output

# Или пошагово
python -m tg_parser.cli ingest --source my_source
python -m tg_parser.cli process --channel @channel_name
python -m tg_parser.cli topicize --channel @channel_name
python -m tg_parser.cli export --channel @channel_name --out ./output
```

## CLI Commands

- `init` — инициализация БД
- `add-source` — добавить источник
- `ingest` — собрать сообщения
- `process` — обработать через LLM
- `topicize` — тематизировать
- `export` — экспортировать
- `run` — полный pipeline одной командой

## Configuration

См. `.env.example` для всех настроек.

## Project Structure

...

## Testing

```bash
pytest  # 85 tests
```

## License

...
```

---

**Вопросы?** Все детали в `docs/notes/SESSION_HANDOFF.md`

**Готов начать?** Скажи "начинаю работу" и приступай к Task 8 (Документация)! 🚀
