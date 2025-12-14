# Стартовый промпт для Implementation Agent Session 3

Привет! Ты агент-разработчик для проекта TG_parser (роль из `docs/notes/agents-roles.md` строки 50-52).

## 📍 Текущее состояние проекта

**Статус**: Processing Pipeline + Export MVP полностью работают ✅  
**Последняя сессия**: Implementation Agent Session 2 (завершена)  
**Git**: 9 коммитов впереди origin/main, working tree clean

### ✅ Что УЖЕ работает:
- Processing: raw messages → ProcessedDocument через OpenAI LLM
- Storage: SQLite с тремя БД (ingestion, raw, processing)
- Export: ProcessedDocument → KnowledgeBaseEntry → kb_entries.ndjson
- Failure tracking: ProcessingFailureRepo логирует ошибки
- CLI: `init`, `process`, `export` полностью функциональны
- Тесты: 59/59 проходят ✅

### 🎯 Что НЕ работает (требует реализации):
- ❌ Topicization: формирование TopicCard и TopicBundle
- ❌ TopicCardRepo и TopicBundleRepo
- ❌ topics.json export
- ❌ Ingestion: сбор данных из Telegram

## 📚 Где найти информацию

### Обязательно прочитай ПЕРВЫМ:
1. **`docs/notes/SESSION_HANDOFF.md`** (620 строк)
   - Полное состояние всех модулей
   - Завершённые задачи сессии 2
   - Следующие приоритеты с оценкой времени
   - Ключевые инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)

2. **`docs/notes/QUICK_START.md`** (короткий)
   - Быстрая справка за 5 минут
   - E2E сценарий что работает
   - Приоритетные задачи

### Для реализации следующих задач:

**Topicization (Task 4)**:
- `docs/pipeline.md` строки 114-163 — алгоритм topicization
- `docs/technical-requirements.md` — TR-27..TR-37
- `docs/architecture.md` — DDL для topic_cards, topic_bundles
- `tg_parser/domain/models.py` — модели TopicCard, TopicBundle

**TopicCardRepo/BundleRepo (Task 5)**:
- `tg_parser/storage/ports.py` — интерфейсы
- `tg_parser/storage/sqlite/processed_document_repo.py` — пример реализации
- `tg_parser/storage/sqlite/schemas/processing_storage.py` — DDL

## 🎯 Рекомендуемые задачи (по приоритету)

### Task 4: Topicization Pipeline (~7 часов) 🔥 ПРИОРИТЕТ #1
**Файлы для создания**:
- `tg_parser/processing/topicization.py`
- `tg_parser/processing/topicization_prompts.py`
- `tg_parser/cli/topicize_cmd.py`
- Тесты в `tests/test_topicization.py`

**Что делать**:
1. LLM-based кластеризация ProcessedDocument → темы
2. Формирование TopicCard (anchors, title, summary, scope_in/out)
3. Формирование TopicBundle (items с ролями: anchor/supporting/context)
4. Детерминизация: `sort by (score desc, anchor_ref asc)` (TR-IF-4)
5. Критерии качества: MIN_ANCHORS=2, MIN_TOPIC_SCORE=0.6
6. CLI команда `topicize --channel <ch>`
7. Интеграция тестов

**Алгоритм**: см. `docs/pipeline.md` строки 114-163

### Task 5: TopicCardRepo + TopicBundleRepo (2-3 часа)
**После Task 4 или параллельно**:
- SQLite реализации репозиториев
- Методы: upsert(), get_by_id(), list_all()
- DDL уже готов в processing_storage.sqlite

### Task 6: Export topics.json (1 час)
**После Task 5**:
- Обновить `cli/export_cmd.py`
- Использовать готовые функции из `export/`

### Task 7: Ingestion (~15 часов)
**Низкий приоритет для текущей сессии**

## 🚀 Быстрая проверка состояния

```bash
# Активировать окружение
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверить тесты
pytest  # Должно быть: 59 passed

# Проверить CLI
python -m tg_parser.cli --help

# Проверить текущий E2E сценарий
python -m tg_parser.cli init
python scripts/add_test_messages.py
python -m tg_parser.cli process --channel test_channel
python -m tg_parser.cli export --channel test_channel --out ./test_output

# Git статус
git log --oneline -5
git status
```

## 📋 Твоя роль (из agents-roles.md)

> Ты агент-разработчик для проекта TG_parser.  
> Пиши и изменяй только код, строго следуя контрактам из `docs/contracts/*.schema.json`, архитектурным документам (`docs/architecture.md`, `docs/pipeline.md`) и ADR в `docs/adr/`.  
> Не редактируй бизнес- и технические документы, если явно не попросили.

## ⚠️ Важные правила

- ✅ Все изменения должны проходить `pytest` (59 тестов)
- ✅ Форматирование: `ruff format .` и `ruff check .`
- ✅ Следовать контрактам из `docs/contracts/*.schema.json`
- ✅ Соблюдать инварианты (TR-8, TR-22, TR-41, TR-IF-4, TR-63)
- ✅ Создавать integration тесты для новых репозиториев
- ❌ НЕ менять архитектуру без ADR
- ❌ НЕ добавлять новые зависимости без обоснования

## 🎬 Как начать

1. Прочитай `docs/notes/SESSION_HANDOFF.md` полностью
2. Изучи алгоритм topicization в `docs/pipeline.md` строки 114-163
3. Посмотри на модели TopicCard/TopicBundle в `domain/models.py`
4. Начни с реализации topicization pipeline (Task 4)
5. Пиши тесты параллельно с кодом

---

**Вопросы?** Все детали в `docs/notes/SESSION_HANDOFF.md`

**Готов начать?** Скажи "начинаю работу" и приступай к Task 4! 🚀
