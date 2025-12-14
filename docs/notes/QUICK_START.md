# Quick Start для нового агента

## 📋 Что нужно знать за 5 минут

### Статус: Processing + Topicization + Export MVP полностью работает ✅

**Файл с деталями**: `docs/notes/SESSION_HANDOFF.md` (700+ строк)

---

## ✅ ЧТО УЖЕ СДЕЛАНО (Sessions 2-3)

### 1. Все 4 бага исправлены ✅
- ✅ `.gitignore`: `run s/` → `runs/`
- ✅ `processing/__init__.py`: удалён дублирующий `__all__`
- ✅ `pipeline.py`: `clear_failure()` → `delete_failure()`
- ✅ `pipeline.py`: исправлена сигнатура `record_failure()`

### 2. ProcessingFailureRepo реализован ✅
- ✅ SQLite backend с 3 методами (record, delete, list)
- ✅ 6 integration тестов
- ✅ Интеграция в CLI process

### 3. CLI Export работает ✅
- ✅ Команда `export` с фильтрами
- ✅ Экспорт в kb_entries.ndjson
- ✅ Экспорт topics.json и topic_<id>.json ✅ **НОВОЕ**
- ✅ Протестировано на реальных данных

### 4. Topicization Pipeline работает ✅ **НОВОЕ В SESSION 3**
- ✅ TopicCardRepo и TopicBundleRepo (SQLite)
- ✅ LLM-based кластеризация документов
- ✅ Детерминизация anchors (TR-IF-4)
- ✅ Критерии качества тем (TR-35)
- ✅ Формирование TopicBundle
- ✅ CLI команда `topicize`
- ✅ 6 integration тестов

---

## 🚀 Что работает ПРЯМО СЕЙЧАС

```bash
# Полный E2E сценарий (с тестовыми данными)
python -m tg_parser.cli init
python scripts/add_test_messages.py
python -m tg_parser.cli process --channel test_channel
python -m tg_parser.cli topicize --channel test_channel  # НОВОЕ
python -m tg_parser.cli export --channel test_channel --out ./output

# ✅ Результат:
# - Processed: 5 документов
# - Topics: N тем
# - Files: kb_entries.ndjson, topics.json, topic_*.json
```

---

## 📊 Статистика

- ✅ **Все 65 тестов проходят** (+6 новых для топиков)
- ✅ **Ruff linter: 0 ошибок**
- ✅ **10 коммитов в текущей ветке**
- ✅ **4 основные задачи завершены** (Sessions 2-3)

---

## 🎯 Следующие задачи (по приоритету)

### ВЫСОКИЙ ПРИОРИТЕТ

#### Задача 5: Ingestion (Telethon) (~10-15 часов) 🔥
**Файлы**: `tg_parser/ingestion/telegram/`, `ingestion/orchestrator.py`, `storage/sqlite/ingestion_state_repo.py`

**Что делать**:
1. SQLiteIngestionStateRepo (~2 часа)
   - CRUD для Source
   - Управление курсорами
   
2. TelethonClient (~3-4 часа)
   - Async wrapper для Telethon
   - get_messages(), get_comments()
   - Error handling
   
3. IngestionOrchestrator (~3-4 часа)
   - Координация сбора данных
   - Режимы: snapshot, incremental
   - Интеграция с RawMessageRepo
   
4. CLI команды (~2 часа)
   - add-source, ingest
   
5. Тесты (~2-3 часа)
   - Integration тесты
   - E2E с mock Telegram API

**Требования**: TR-4..TR-17 (см. `technical-requirements.md`)

**DDL уже готов** в `ingestion_state.sqlite`:
- Таблица: `sources`
- Таблицы: `ingestion_attempts`, `ingestion_comment_cursors`

**Алгоритм**: см. `docs/architecture.md` раздел Ingestion

#### Задача 6: E2E тесты и документация (3-5 часов)
После Task 5:
- E2E тесты полного pipeline
- Обновление README
- Документация по настройке Telethon

#### Задача 7: CLI команда `run` (2-3 часа)
Полный pipeline: ingest → process → topicize → export

---

## 💻 Основные команды

```bash
# Setup
source .venv/bin/activate

# Тесты
pytest                                     # Все (65 тестов)
pytest tests/test_processing_pipeline.py   # Processing
pytest tests/test_storage_integration.py   # Storage (включая топики)

# Код
ruff format .
ruff check .

# CLI
python -m tg_parser.cli --help
python -m tg_parser.cli process --help
python -m tg_parser.cli topicize --help    # НОВОЕ
python -m tg_parser.cli export --help
```

---

## 🎯 Git состояние

```
On branch main
Your branch is ahead of 'origin/main' by 10 commits.

Последние коммиты:
- f9f45a0 Implement topicization pipeline (Task 4)  # Session 3
- 18cce94 Update QUICK_START for Implementation Session 2
- 85c7303 Update SESSION_HANDOFF with completed tasks
- f45d188 Implement CLI export command
- a2abf8d Integrate ProcessingFailureRepo
```

---

## 📚 Ключевые документы

- `docs/notes/SESSION_HANDOFF.md` — **полная документация** (700+ строк)
- `docs/architecture.md` — DDL схемы, Ingestion алгоритм
- `docs/pipeline.md` — алгоритмы
- `docs/technical-requirements.md` — TR-* требования
- `docs/tech-stack.md` — Telethon выбор

---

## 🔑 Что важно для Ingestion

### Технические требования:
- TR-4: snapshot vs incremental
- TR-5: режим сбора (posts-only, with-comments)
- TR-6: включение комментариев
- TR-7: per-thread курсоры для комментариев
- TR-8: идемпотентность (ON CONFLICT DO NOTHING)
- TR-10: атомарность обновления курсоров
- TR-11..TR-17: error handling

### Конфигурация (добавить в settings.py):
```python
telegram_api_id: int
telegram_api_hash: str
telegram_phone: str | None = None
```

### Пример использования (целевой):
```bash
# Добавить источник
python -m tg_parser.cli add-source --channel-id my_channel --username my_channel_username

# Первичная загрузка
python -m tg_parser.cli ingest --channel my_channel --mode snapshot

# Инкрементальная загрузка
python -m tg_parser.cli ingest --channel my_channel --mode incremental

# Полный pipeline
python -m tg_parser.cli run --channel my_channel --out ./output
```

---

**Начни с**: Прочитать `SESSION_HANDOFF.md` раздел "Технические детали для Ingestion", затем реализовать Task 5.1 (IngestionStateRepo).
