# Стартовый промпт для Implementation Agent Session 4

Привет! Ты агент-разработчик для проекта TG_parser (роль из `docs/notes/agents-roles.md` строки 50-52).

## 📍 Текущее состояние проекта

**Статус**: Processing + Topicization + Export MVP полностью работают ✅  
**Последняя сессия**: Implementation Agent Session 3 (завершена)  
**Git**: 10 коммитов впереди origin/main, working tree clean

### ✅ Что УЖЕ работает:

- **Processing**: raw messages → ProcessedDocument через OpenAI LLM
- **Topicization**: ProcessedDocument → TopicCard + TopicBundle ✅ **НОВОЕ**
- **Storage**: SQLite с полным набором репозиториев (5/6 готовы)
- **Export**: KB entries + topics.json + topic_<id>.json ✅ **ОБНОВЛЕНО**
- **Failure tracking**: ProcessingFailureRepo логирует ошибки
- **CLI**: `init`, `process`, `topicize`, `export` полностью функциональны
- **Тесты**: 65/65 проходят ✅ (+6 новых для топиков)

### 🎯 Что НЕ работает (требует реализации):

- ❌ **Ingestion**: сбор данных из Telegram через Telethon
- ❌ **IngestionStateRepo**: управление источниками и курсорами
- ❌ **CLI команды**: `ingest`, `add-source`, `run`

## 📚 Где найти информацию

### Обязательно прочитай ПЕРВЫМ:

1. **`docs/notes/SESSION_HANDOFF.md`** (700+ строк)
   - Полное состояние всех модулей
   - Завершённые задачи Session 3 (Topicization)
   - Следующие приоритеты с оценкой времени
   - Ключевые инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)
   - Раздел "Технические детали для Ingestion" в конце

2. **`docs/notes/QUICK_START.md`** (короткий)
   - Быстрая справка за 5 минут
   - E2E сценарий что работает
   - Приоритетные задачи

### Для реализации следующих задач:

**Ingestion (Task 5)** 🔥 ПРИОРИТЕТ #1:
- `docs/architecture.md` — DDL для ingestion_state
- `docs/technical-requirements.md` — TR-4..TR-17
- `docs/tech-stack.md` — выбор Telethon
- `tg_parser/storage/ports.py` — интерфейс IngestionStateRepo
- Существующие репозитории как примеры: `storage/sqlite/raw_message_repo.py`

## 🎯 Рекомендуемые задачи (по приоритету)

### Task 5: Ingestion (Telethon) (~10-15 часов) 🔥 ПРИОРИТЕТ #1

**Файлы для создания**:
- `tg_parser/ingestion/telegram/telethon_client.py`
- `tg_parser/ingestion/orchestrator.py`
- `tg_parser/storage/sqlite/ingestion_state_repo.py`
- `tg_parser/cli/ingest_cmd.py`
- `tg_parser/cli/add_source_cmd.py`
- Тесты в `tests/test_ingestion.py`

**Что делать**:

1. **SQLiteIngestionStateRepo** (~2 часа)
   - Реализовать интерфейс из `storage/ports.py`
   - CRUD для Source
   - Методы: `upsert_source()`, `get_source()`, `list_sources()`, `update_cursors()`, `record_attempt()`
   - DDL уже готов в `ingestion_state.sqlite`
   - Integration тесты

2. **TelethonClient** (~3-4 часа)
   - Async wrapper для Telethon
   - Методы: `get_messages()`, `get_comments()`
   - Конфигурация API credentials
   - Error handling и retry logic (TR-11..TR-17)

3. **IngestionOrchestrator** (~3-4 часа)
   - Координация сбора данных
   - Режимы: snapshot, incremental (TR-4, TR-5)
   - Управление курсорами (TR-7, TR-10)
   - Интеграция с RawMessageRepo
   - Идемпотентность (TR-8)

4. **CLI команды** (~2 часа)
   - `add-source`: добавление источника
   - `ingest`: запуск ingestion
   - Опции: --mode (snapshot/incremental), --include-comments, --dry-run

5. **Тесты** (~2-3 часа)
   - Unit тесты для TelethonClient (с mock Telethon)
   - Integration тесты для IngestionStateRepo
   - E2E тест с mock Telegram API

**Алгоритм**: см. `docs/architecture.md` раздел Ingestion

### Task 6: E2E тесты и документация (~3-5 часов)

После Task 5:
- E2E тесты полного pipeline
- Обновление README
- Документация по настройке Telethon

### Task 7: CLI команда `run` (one-shot) (~2-3 часа)

Полный pipeline: ingest → process → topicize → export

---

## 🚀 Быстрая проверка состояния

```bash
# Активировать окружение
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверить тесты
pytest  # Должно быть: 65 passed

# Проверить CLI
python -m tg_parser.cli --help

# Проверить текущий работающий pipeline
python -m tg_parser.cli init
python scripts/add_test_messages.py
python -m tg_parser.cli process --channel test_channel
python -m tg_parser.cli topicize --channel test_channel  # НОВОЕ
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

- ✅ Все изменения должны проходить `pytest` (65+ тестов)
- ✅ Форматирование: `ruff format .` и `ruff check .`
- ✅ Следовать контрактам из `docs/contracts/*.schema.json`
- ✅ Соблюдать инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)
- ✅ Создавать integration тесты для новых репозиториев
- ❌ НЕ менять архитектуру без ADR
- ❌ НЕ добавлять новые зависимости без обоснования

---

## 🎬 Как начать

1. Прочитай `docs/notes/SESSION_HANDOFF.md` полностью
2. Изучи раздел "Технические детали для Ingestion" в конце SESSION_HANDOFF
3. Посмотри на интерфейс IngestionStateRepo в `storage/ports.py`
4. Изучи требования TR-4..TR-17 в `technical-requirements.md`
5. Начни с реализации SQLiteIngestionStateRepo (Task 5.1)
6. Пиши тесты параллельно с кодом

---

## 💡 Полезные подсказки для Ingestion

### Telethon setup:

```python
from telethon import TelegramClient
from telethon.tl.types import Message

# Async client
client = TelegramClient(
    'session_name',
    api_id=settings.telegram_api_id,
    api_hash=settings.telegram_api_hash
)

# Get messages
async for message in client.iter_messages(channel, limit=100):
    # Process message
    pass
```

### Конфигурация (добавить в settings.py):

```python
# Telegram API credentials
telegram_api_id: int
telegram_api_hash: str
telegram_phone: str | None = None
```

### Структура Source (уже есть в domain/models.py):

```python
class Source(BaseModel):
    id: str  # channel_id
    channel_username: str | None
    include_comments: bool
    mode: str  # "snapshot" | "incremental"
    status: str  # "active" | "paused"
    last_post_id: str | None
    comment_cursors: dict[str, str]  # thread_id -> last_comment_id
    # ... other fields
```

---

**Вопросы?** Все детали в `docs/notes/SESSION_HANDOFF.md`

**Готов начать?** Скажи "начинаю работу" и приступай к Task 5! 🚀
