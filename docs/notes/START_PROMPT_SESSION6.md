# Стартовый промпт для Implementation Agent Session 6

Привет! Ты агент-разработчик для проекта TG_parser (роль из `docs/notes/agents-roles.md` строки 50-52).

## 📍 Текущее состояние проекта

**Статус**: Full MVP — Ingestion + Processing + Topicization + Export + E2E Tests полностью работают ✅  
**Последняя сессия**: Implementation Agent Session 5 (завершена)  
**Git**: 15 коммитов впереди origin/main, working tree clean

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
- **CLI**: init, add-source, ingest, process, topicize, export ✅
- **E2E Tests**: 4 теста с mock Telegram API ✅ **НОВОЕ В SESSION 5**
  - test_full_pipeline_e2e
  - test_incremental_mode_ingestion (TR-4)
  - test_comments_ingestion_with_per_thread_cursors (TR-6, TR-7)
  - test_error_handling_and_retry_logic (TR-12, TR-13)
- **Тесты**: 82/82 проходят ✅ (+4 E2E теста в Session 5)

### 🎯 Что НЕ работает (требует реализации):

- ❌ **CLI команда `run`** — one-shot: ingest → process → topicize → export
- ❌ **Документация** — README с примерами, настройка Telethon

## 📚 Где найти информацию

### Обязательно прочитай ПЕРВЫМ:

1. **`docs/notes/SESSION_HANDOFF.md`** (600+ строк)
   - Полное состояние всех модулей
   - Завершённая задача Session 5 (E2E Tests)
   - Следующие приоритеты с оценкой времени
   - Ключевые инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)

2. **`docs/notes/QUICK_START.md`** (короткий)
   - Быстрая справка за 5 минут
   - E2E сценарий что работает
   - Приоритетные задачи

### Для реализации следующих задач:

**CLI команда `run` (Task 7)** 🔥 ПРИОРИТЕТ #1:
- Существующие CLI команды: `tg_parser/cli/*_cmd.py`
- Последовательный вызов всех этапов pipeline
- Статистика каждого этапа

**Документация (Task 8)**:
- README.md — основная документация
- .env.example — пример конфигурации
- docs/INSTALLATION.md — инструкция по установке

## 🎯 Рекомендуемые задачи (по приоритету)

### Task 7: CLI команда `run` (~2-3 часа) 🔥 ПРИОРИТЕТ #1

**Файлы для создания**:
- `tg_parser/cli/run_cmd.py` — one-shot pipeline

**Что делать**:

1. **RunCommand** (~1-2 часа)
   - Последовательный вызов: ingest → process → topicize → export
   - Параметры: --source, --channel, --out, --mode
   - Опции: --skip-ingest, --skip-process, --skip-topicize
   - Статистика каждого этапа с итоговым отчётом
   - Error handling: если один этап провалился, показать где остановились

2. **Интеграция в CLI** (~0.5 часа)
   - Обновить `cli/app.py` с реальной реализацией команды `run`
   - Опции: --force, --dry-run

3. **Тесты** (~0.5-1 час)
   - Добавить unit тесты для run_cmd
   - Можно добавить в test_e2e_pipeline.py

### Task 8: Документация (~2-3 часа)

**Файлы для обновления/создания**:
- `README.md` — основная документация
- `.env.example` — пример конфигурации
- `docs/INSTALLATION.md` — инструкция по установке (опционально)

**Что делать**:

1. **README.md** (~1-2 часа)
   - Описание проекта (что делает, зачем нужен)
   - Quick Start (установка + первый запуск)
   - Примеры использования всех команд
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

---

## 🚀 Быстрая проверка состояния

```bash
# Активировать окружение
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверить тесты (должно быть 82 passed)
pytest

# Проверить CLI
python -m tg_parser.cli --help

# Проверить текущий работающий pipeline (с тестовыми данными)
python -m tg_parser.cli init
python scripts/add_test_messages.py
python -m tg_parser.cli process --channel test_channel
python -m tg_parser.cli topicize --channel test_channel
python -m tg_parser.cli export --channel test_channel --out ./test_output

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

- ✅ Все изменения должны проходить `pytest` (82+ тестов)
- ✅ Форматирование: `ruff format .` и `ruff check .`
- ✅ Следовать контрактам из `docs/contracts/*.schema.json`
- ✅ Соблюдать инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)
- ✅ Создавать тесты для новой функциональности
- ❌ НЕ менять архитектуру без ADR
- ❌ НЕ добавлять новые зависимости без обоснования

---

## 🎬 Как начать

1. Прочитай `docs/notes/SESSION_HANDOFF.md` полностью
2. Изучи существующие CLI команды в `tg_parser/cli/`
3. Посмотри как они интегрированы в `cli/app.py`
4. Начни с Task 7 (CLI команда `run`) — создай run_cmd.py
5. Добавь тесты для новой команды

---

## 💡 Полезные подсказки

### CLI команда `run` структура:

```python
async def run_full_pipeline(
    source_id: str,
    channel_id: str | None = None,
    output_dir: str = "./output",
    mode: str = "incremental",
    skip_ingest: bool = False,
    skip_process: bool = False,
    skip_topicize: bool = False,
    force: bool = False,
) -> dict:
    """One-shot: ingest → process → topicize → export."""
    
    stats = {
        "ingest": None,
        "process": None,
        "topicize": None,
        "export": None,
        "total_duration": 0,
    }
    
    # Step 1: Ingest (если не skip)
    if not skip_ingest:
        stats["ingest"] = await run_ingestion(...)
    
    # Step 2: Process (если не skip)
    if not skip_process:
        stats["process"] = await run_processing(...)
    
    # Step 3: Topicize (если не skip)
    if not skip_topicize:
        stats["topicize"] = await run_topicization(...)
    
    # Step 4: Export (всегда)
    stats["export"] = await run_export(...)
    
    return stats
```

### README.md структура:

```markdown
# TG_parser

Парсер Telegram каналов для создания структурированной базы знаний.

## Features

- Сбор сообщений и комментариев из Telegram каналов
- Обработка через LLM (OpenAI) для извлечения структуры
- Автоматическая тематизация контента
- Экспорт в формате JSONL для RAG систем

## Quick Start

1. Установка
2. Настройка Telegram API
3. Первый запуск

## Usage

### Полный pipeline
```bash
python -m tg_parser.cli run --source my_channel --out ./output
```

### Пошаговый запуск
...

## Configuration

...
```

---

**Вопросы?** Все детали в `docs/notes/SESSION_HANDOFF.md`

**Готов начать?** Скажи "начинаю работу" и приступай к Task 7! 🚀
