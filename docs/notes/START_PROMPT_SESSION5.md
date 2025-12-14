# Стартовый промпт для Implementation Agent Session 5

Привет! Ты агент-разработчик для проекта TG_parser (роль из `docs/notes/agents-roles.md` строки 50-52).

## 📍 Текущее состояние проекта

**Статус**: Full MVP — Ingestion + Processing + Topicization + Export полностью работают ✅  
**Последняя сессия**: Implementation Agent Session 4 (завершена)  
**Git**: 13 коммитов впереди origin/main, working tree clean

### ✅ Что УЖЕ работает:

- **Ingestion (Telethon)**: сбор raw сообщений из Telegram через Telethon ✅ **НОВОЕ В SESSION 4**
  - TelethonClient с методами get_messages() и get_comments()
  - IngestionOrchestrator с retry logic и error handling
  - Режимы snapshot и incremental (TR-4)
  - Per-thread курсоры комментариев (TR-7)
- **Storage**: все 6/6 репозиториев реализованы ✅ **ЗАВЕРШЕНО В SESSION 4**
  - SQLiteIngestionStateRepo (CRUD для Source, курсоры) ✅ **НОВОЕ**
  - SQLiteRawMessageRepo
  - SQLiteProcessedDocumentRepo
  - SQLiteProcessingFailureRepo
  - SQLiteTopicCardRepo
  - SQLiteTopicBundleRepo
- **Processing**: raw messages → ProcessedDocument через OpenAI LLM
- **Topicization**: ProcessedDocument → TopicCard + TopicBundle
- **Export**: KB entries + topics.json + topic_<id>.json
- **CLI**: init, add-source, ingest, process, topicize, export ✅ **add-source и ingest НОВЫЕ**
- **Тесты**: 78/78 проходят ✅ (+13 новых в Session 4)

### 🎯 Что НЕ работает (требует реализации):

- ❌ **E2E тесты** — полный pipeline с mock Telegram API
- ❌ **CLI команда `run`** — one-shot: ingest → process → topicize → export
- ❌ **Документация** — README с примерами, настройка Telethon

## 📚 Где найти информацию

### Обязательно прочитай ПЕРВЫМ:

1. **`docs/notes/SESSION_HANDOFF.md`** (600+ строк)
   - Полное состояние всех модулей
   - Завершённая задача Session 4 (Ingestion + Telethon)
   - Следующие приоритеты с оценкой времени
   - Ключевые инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)

2. **`docs/notes/QUICK_START.md`** (короткий)
   - Быстрая справка за 5 минут
   - E2E сценарий что работает
   - Приоритетные задачи

### Для реализации следующих задач:

**E2E тесты (Task 6)** 🔥 ПРИОРИТЕТ #1:
- Существующие тесты как примеры: `tests/test_*.py`
- Mock Telegram API для тестирования ingestion
- E2E сценарий: add-source → ingest → process → topicize → export

**CLI команда `run` (Task 7)**:
- Существующие CLI команды: `tg_parser/cli/*_cmd.py`
- Последовательный вызов всех этапов pipeline

## 🎯 Рекомендуемые задачи (по приоритету)

### Task 6: E2E тесты (~3-4 часа) 🔥 ПРИОРИТЕТ #1

**Файлы для создания**:
- `tests/test_e2e_pipeline.py` — E2E тесты полного pipeline
- Mock helpers для Telethon

**Что делать**:

1. **Mock Telegram API** (~1 час)
   - Создать mock для Telethon client
   - Mock Message objects из Telethon
   - Симуляция get_messages() и get_comments()

2. **E2E тест полного pipeline** (~2-3 часа)
   - Создать тестовый источник (add-source)
   - Ingest с mock Telegram
   - Process через mock LLM (уже есть)
   - Topicize
   - Export
   - Проверить все артефакты

3. **Дополнительные тесты**
   - Incremental mode ingestion
   - Комментарии (TR-6, TR-7)
   - Error handling и retry logic

### Task 7: CLI команда `run` (~2-3 часа)

**Файлы для создания**:
- `tg_parser/cli/run_cmd.py` — one-shot pipeline

**Что делать**:

1. **RunCommand** (~1-2 часа)
   - Последовательный вызов: add-source (if needed) → ingest → process → topicize → export
   - Параметры: --source, --channel, --out, --mode
   - Статистика каждого этапа

2. **Интеграция в CLI** (~0.5 часа)
   - Обновить `cli/app.py` с реальной реализацией
   - Опции: --dry-run, --force, --skip-existing

### Task 8: Документация (~2-3 часа)

**Файлы для обновления**:
- `README.md` — основная документация
- `.env.example` — пример конфигурации
- `docs/INSTALLATION.md` — инструкция по установке

**Что делать**:

1. **README.md** (~1-2 часа)
   - Описание проекта
   - Quick Start
   - Примеры использования всех команд
   - Требования и установка

2. **Telethon Setup** (~0.5-1 час)
   - Получение API credentials
   - Настройка .env файла
   - Первый запуск и авторизация

3. **Примеры сценариев** (~0.5 часа)
   - Полный E2E пример
   - Инкрементальное обновление
   - Работа с несколькими каналами

---

## 🚀 Быстрая проверка состояния

```bash
# Активировать окружение
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверить тесты
pytest  # Должно быть: 78 passed

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

- ✅ Все изменения должны проходить `pytest` (78+ тестов)
- ✅ Форматирование: `ruff format .` и `ruff check .`
- ✅ Следовать контрактам из `docs/contracts/*.schema.json`
- ✅ Соблюдать инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)
- ✅ Создавать тесты для новой функциональности
- ❌ НЕ менять архитектуру без ADR
- ❌ НЕ добавлять новые зависимости без обоснования

---

## 🎬 Как начать

1. Прочитай `docs/notes/SESSION_HANDOFF.md` полностью
2. Изучи существующие тесты в `tests/`
3. Посмотри на структуру CLI команд в `tg_parser/cli/`
4. Начни с Task 6 (E2E тесты) — создай mock для Telethon
5. Пиши тесты параллельно с кодом

---

## 💡 Полезные подсказки

### Mock Telethon для тестов:

```python
from unittest.mock import AsyncMock, Mock

# Mock Telethon Message
mock_message = Mock()
mock_message.id = 123
mock_message.text = "Test message"
mock_message.date = datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC)
mock_message.reply_to = None

# Mock TelethonClient
mock_client = AsyncMock()
mock_client.get_messages = AsyncMock(return_value=[...])
mock_client.get_comments = AsyncMock(return_value=[...])
```

### E2E тест структура:

```python
@pytest.mark.asyncio
async def test_full_pipeline_e2e(test_db, mock_telegram):
    """Тест полного pipeline: ingest → process → topicize → export."""
    # 1. Add source
    # 2. Ingest with mock Telegram
    # 3. Process with mock LLM
    # 4. Topicize
    # 5. Export
    # 6. Verify artifacts
```

### CLI команда `run`:

```python
async def run_full_pipeline(
    source_id: str,
    channel_id: str,
    output_dir: str,
    mode: str = "incremental",
) -> dict:
    """One-shot: ingest → process → topicize → export."""
    # Step 1: Ingest
    # Step 2: Process
    # Step 3: Topicize
    # Step 4: Export
    # Return combined stats
```

---

**Вопросы?** Все детали в `docs/notes/SESSION_HANDOFF.md`

**Готов начать?** Скажи "начинаю работу" и приступай к Task 6! 🚀
