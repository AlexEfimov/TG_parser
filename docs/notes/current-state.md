# Текущее состояние разработки TG_parser (Session Summary)

**Дата**: 14 декабря 2025  
**Статус**: Базовая инфраструктура MVP завершена, готова к разработке пайплайна

---

## 🎯 Что полностью реализовано (DONE)

### 1. Domain Layer (100% готов)
**Файлы**: `tg_parser/domain/`

- ✅ **Pydantic v2 модели** строго по контрактам `docs/contracts/*.schema.json`:
  - `RawTelegramMessage` — сырые сообщения из Telegram
  - `ProcessedDocument` — обработанные документы
  - `TopicCard` — карточки тем
  - `TopicBundle` — тематические подборки
  - `KnowledgeBaseEntry` — записи базы знаний
  - Все Enums: `MessageType`, `TopicType`, `BundleItemRole`

- ✅ **Канонизация идентификаторов** (`tg_parser/domain/ids.py`):
  ```python
  make_source_ref(channel_id, message_type, message_id) → "tg:ch:post:123"
  make_processed_document_id(source_ref) → "doc:tg:ch:post:123"
  make_topic_id(primary_anchor_ref) → "topic:tg:ch:post:123"
  make_kb_message_id(source_ref) → "kb:msg:tg:ch:post:123"
  make_kb_topic_id(topic_id) → "kb:topic:topic:tg:ch:post:123"
  ```

- ✅ **Валидация JSON Schema** (`tg_parser/domain/contract_validation.py`):
  - `ContractValidator` — валидация против `docs/contracts/*.schema.json`
  - Проверка на границах слоёв (TR-IF-1)

- ✅ **Исправлены все warnings**:
  - Pydantic v2: `class Config` → `model_config = ConfigDict(...)`
  - Python 3.12: `datetime.utcnow()` → `datetime.now(timezone.utc)`

### 2. Storage Layer (90% готов)
**Файлы**: `tg_parser/storage/`

#### 2.1 Порты (интерфейсы) — `storage/ports.py`
- ✅ `IngestionStateRepo` — состояние источников
- ✅ `RawMessageRepo` — raw-сообщения
- ✅ `ProcessedDocumentRepo` — обработанные документы
- ✅ `ProcessingFailureRepo` — журнал ошибок
- ✅ `TopicCardRepo` — карточки тем
- ✅ `TopicBundleRepo` — подборки

#### 2.2 SQLite реализации — `storage/sqlite/`
- ✅ **Database инфраструктура** (`database.py`):
  - `DatabaseConfig` — конфигурация 3 SQLite файлов
  - `Database` — контейнер engines и sessionmakers
  - Async SQLAlchemy 2.x + aiosqlite

- ✅ **DDL схемы** (`schemas/`):
  - `ingestion_state.sqlite`: sources, comment_cursors, source_attempts
  - `raw_storage.sqlite`: raw_messages, raw_conflicts
  - `processing_storage.sqlite`: processed_documents, processing_failures, topic_cards, topic_bundles
  - Все индексы и UNIQUE constraints из `docs/architecture.md`

- ✅ **Реализованные репозитории**:
  - `SQLiteRawMessageRepo` — с TR-8 (snapshot), TR-18 (идемпотентность)
  - `SQLiteProcessedDocumentRepo` — с TR-22 (upsert), TR-48 (exists check)

- ✅ **JSON сериализация** (`json_utils.py`):
  - `stable_json_dumps()` — детерминированная сериализация (TR-63)
  - Сортировка ключей, стабильные разделители

- ⚠️ **TODO**: остальные репозитории (Ingestion state, Topic card/bundle) — можно реализовать по аналогии с Raw/Processed

### 3. Export Layer (100% готов)
**Файлы**: `tg_parser/export/`

- ✅ **Резолюция Telegram URL** (`telegram_url.py`):
  - `resolve_telegram_url()` — best-effort по TR-58/TR-65
  - Эвристики: username, -100 prefix, публичные каналы

- ✅ **Маппинг в KnowledgeBaseEntry** (`kb_mapping.py`):
  - `map_message_to_kb_entry()` — ProcessedDocument → KB entry (TR-61)
  - `map_topic_to_kb_entry()` — TopicCard → KB entry (TR-61)

- ✅ **Экспорт артефактов**:
  - `export_topics_json()` — каталог тем (TR-56)
  - `export_topic_detail_json()` — детальная информация о теме + resolved_sources (TR-59)
  - `export_kb_entries_ndjson()` — плоский экспорт KB (TR-56)
  - `filter_kb_entries()` — фильтры по channel/topic/dates (TR-62)

### 4. Config (100% готов)
**Файлы**: `tg_parser/config/settings.py`

- ✅ **Pydantic Settings**:
  - Пути к SQLite файлам
  - LLM настройки (provider, model, base_url, API keys)
  - Processing параметры (температура, ретраи)
  - Ingestion параметры (ретраи, backoff)
  - Topicization параметры (пороги, top_n_anchors)
  - Pipeline версии

### 5. CLI (базовая структура готова)
**Файлы**: `tg_parser/cli/`

- ✅ **Команда `init`** — ПОЛНОСТЬЮ РАБОТАЕТ:
  ```bash
  python -m tg_parser.cli init        # Создать базы
  python -m tg_parser.cli init --force # Пересоздать
  ```
  - Создаёт все 3 SQLite файла
  - Выполняет DDL через async схемы
  - Проверяет существование

- ⚠️ **Команды-заглушки** (TODO):
  - `add-source` — добавить источник
  - `ingest` — сбор raw сообщений
  - `process` — обработка raw → processed
  - `topicize` — формирование тем
  - `export` — экспорт артефактов
  - `run` — one-shot запуск всего пайплайна

### 6. Processing (порты + mock)
**Файлы**: `tg_parser/processing/`

- ✅ **Порты** (`ports.py`):
  - `LLMClient` — интерфейс для LLM
  - `ProcessingPipeline` — интерфейс обработки

- ✅ **Mock LLM** (`mock_llm.py`):
  - `MockLLMClient` — базовый mock
  - `DeterministicMockLLM` — детерминированный
  - `ProcessingMockLLM` — специализированный для processing

- ⚠️ **TODO**: реальные реализации (OpenAI adapter, processing pipeline)

### 7. Тесты (37 тестов, 100% проходят)
**Файлы**: `tests/`

- ✅ **Unit тесты**:
  - `test_ids.py` — канонизация ID (TR-IF-5, TR-41, TR-IF-4, TR-61)
  - `test_models.py` — валидация Pydantic моделей
  - `test_telegram_url.py` — резолюция URL (TR-58/TR-65)

- ✅ **Integration тесты**:
  - `test_storage_integration.py` — SQLite репозитории:
    - TR-8: raw snapshot идемпотентность
    - TR-18: уникальность по source_ref
    - TR-22: upsert processed documents
    - TR-48: exists check

- ✅ **Результаты**: `37 passed in 0.34s` — БЕЗ WARNINGS

### 8. Документация
- ✅ `README.md` — обновлён с инструкциями установки
- ✅ `.gitignore` — настроен для Python/SQLite/secrets
- ✅ `requirements.txt` — все зависимости
- ✅ `docs/notes/implementation-plan.md` — полный план реализации
- ✅ `tests/README.md` — описание тестов

---

## 📂 Структура проекта (текущая)

```
TG_parser/
├── tg_parser/
│   ├── domain/                    # ✅ Domain models (Pydantic v2)
│   │   ├── __init__.py
│   │   ├── models.py              # RawMessage, Processed, Topic*, KB*
│   │   ├── ids.py                 # Канонизация ID
│   │   └── contract_validation.py # JSON Schema валидация
│   │
│   ├── config/                    # ✅ Settings (pydantic-settings)
│   │   ├── __init__.py
│   │   └── settings.py
│   │
│   ├── storage/                   # ✅ Storage layer
│   │   ├── __init__.py
│   │   ├── ports.py               # Интерфейсы репозиториев
│   │   └── sqlite/                # SQLite реализации
│   │       ├── __init__.py
│   │       ├── database.py        # Database, Config
│   │       ├── json_utils.py      # Стабильная JSON сериализация
│   │       ├── raw_message_repo.py       # ✅ Реализован
│   │       ├── processed_document_repo.py # ✅ Реализован
│   │       └── schemas/           # DDL схемы
│   │           ├── __init__.py
│   │           ├── ingestion_state.py
│   │           ├── raw_storage.py
│   │           └── processing_storage.py
│   │
│   ├── export/                    # ✅ Export layer
│   │   ├── __init__.py
│   │   ├── telegram_url.py        # Резолюция URL
│   │   ├── kb_mapping.py          # Маппинг в KB entries
│   │   ├── topics_export.py       # topics.json, topic_<id>.json
│   │   └── kb_export.py           # kb_entries.ndjson
│   │
│   ├── processing/                # ⚠️ Порты + mock (TODO: реализация)
│   │   ├── __init__.py
│   │   ├── ports.py               # LLMClient, ProcessingPipeline
│   │   └── mock_llm.py            # ✅ Mock реализации
│   │
│   ├── ingestion/                 # ⚠️ TODO: Telethon адаптер
│   │   ├── __init__.py
│   │   └── interfaces.py
│   │
│   └── cli/                       # ⚠️ Базовая структура
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py                 # Typer команды
│       └── init_db.py             # ✅ init команда работает
│
├── tests/                         # ✅ 37 тестов, 100% pass
│   ├── conftest.py
│   ├── test_ids.py                # Unit: ID канонизация
│   ├── test_models.py             # Unit: Pydantic модели
│   ├── test_telegram_url.py       # Unit: URL резолюция
│   └── test_storage_integration.py # Integration: SQLite
│
├── docs/
│   ├── contracts/                 # JSON Schema контракты
│   ├── adr/                       # ADR 0001-0004 (Accepted)
│   ├── architecture.md            # Архитектура + DDL
│   ├── pipeline.md                # Pipeline описание
│   ├── technical-requirements.md  # TR-* требования
│   └── notes/
│       ├── implementation-plan.md # План реализации
│       └── current-state.md       # ← ЭТОТ ФАЙЛ
│
├── requirements.txt               # ✅ Все зависимости
├── README.md                      # ✅ Обновлён
├── .gitignore                     # ✅ Настроен
└── pyproject.toml                 # pytest конфиг
```

---

## 🚀 Следующие шаги (приоритезировано)

### ВЫСОКИЙ ПРИОРИТЕТ (для рабочего прототипа)

#### 4. **Processing Pipeline** — NEXT TODO
**Цель**: Запускать `python -m tg_parser.cli process --channel mychannel`

**Что нужно**:
1. **OpenAI LLM adapter** (`processing/llm/openai_client.py`):
   - Реализация `LLMClient` через `httpx`
   - API key из `settings.openai_api_key`
   - Параметры: temperature=0, model_id из config
   - Обработка ошибок и ретраи

2. **Processing pipeline** (`processing/pipeline.py`):
   - Реализация `ProcessingPipeline`
   - `process_message()`: RawTelegramMessage → ProcessedDocument
   - LLM промпты для извлечения:
     - `text_clean` — очистка текста
     - `summary` — краткое резюме
     - `topics` — список тем
     - `entities` — извлечённые сущности
     - `language` — определение языка
   - Ретраи per-message (TR-47): 3 попытки, backoff 1/2/4s
   - Запись в `processing_failures` при исчерпании

3. **CLI wiring** (`cli/app.py` → `process` команда):
   - Подключить Database, репозитории
   - Получить raw сообщения из `raw_storage.sqlite`
   - Фильтр по `--channel`
   - Инкрементальность: skip если `exists(source_ref)` (TR-48)
   - `--force` для переобработки
   - Формирование metadata (TR-23): `pipeline_version`, `model_id`, `prompt_id`
   - Вывод статистики

4. **Тесты processing**:
   - Unit: тест промптов и маппинга ответов
   - Integration: mock LLM + real storage

**Файлы для создания**:
- `tg_parser/processing/llm/openai_client.py`
- `tg_parser/processing/pipeline.py`
- `tg_parser/processing/prompts.py` (шаблоны промптов)
- `tests/test_processing_pipeline.py`

**Ссылки на требования**:
- TR-21..TR-26: обработка 1→1
- TR-38: детерминизм LLM (temperature=0)
- TR-41: ProcessedDocument.id = "doc:" + source_ref
- TR-46: инкрементальность
- TR-47: ретраи per-message
- TR-49: семантика processed_at

#### 5. **Export Wiring** — ПОСЛЕ 4
**Цель**: Запускать `python -m tg_parser.cli export --channel mychannel --out ./output`

**Что нужно**:
1. **CLI wiring** (`cli/app.py` → `export` команда):
   - Подключить Database, репозитории
   - Получить данные из `processing_storage.sqlite`
   - Применить фильтры (TR-62):
     - `--channel`: ограничить каналом
     - `--topic-id`: ограничить темой
     - `--from/--to`: фильтр по датам
   - Создать output директорию
   - Вызвать экспортные функции:
     - `export_topics_json()` → `topics.json`
     - Для каждой темы: `export_topic_detail_json()` → `topic_<id>.json`
     - `export_kb_entries_ndjson()` → `kb_entries.ndjson`
   - Поддержка флагов:
     - `--format json|ndjson`
     - `--pretty` для JSON
     - `--include-supporting` (default true)

2. **Резолюция channel_username**:
   - Получать из `ingestion_state.sqlite.sources.channel_username`
   - Передавать в `resolve_telegram_url()`

3. **Тесты export**:
   - Integration: создать processed/topics → проверить экспорт
   - Проверить детерминизм сортировки (TR-63)
   - Проверить фильтры

**Файлы для создания**:
- `tests/test_export_integration.py`

**Ссылки на требования**:
- TR-56..TR-64: экспорт артефактов
- TR-63: детерминизм вывода

#### 6. **Topicization** — ПОСЛЕ 4-5
**Цель**: Запускать `python -m tg_parser.cli topicize --channel mychannel`

**Что нужно**:
1. **Topicization pipeline** (`processing/topicization.py`):
   - Вход: список `ProcessedDocument` канала (TR-30)
   - LLM промпты для формирования тем:
     - Генерация кандидатов в якоря
     - Кластеризация по темам
     - Формирование `TopicCard` (title, summary, scope_in/out)
     - Расчёт score для anchors
   - Детерминизация anchors (TR-IF-4):
     - Сортировка `(score desc, anchor_ref asc)`
     - Top-N якорей (default N=3)
     - `TopicCard.id = "topic:" + anchors[0].anchor_ref`
   - Формирование `TopicBundle` (TR-36):
     - Anchors с `role="anchor"`
     - Supporting при `score >= 0.5`
     - Дедупликация по `source_ref`
   - Критерии качества (TR-35):
     - Singleton: len >= 300 символов, score >= 0.75
     - Cluster: min 2 anchors, score >= 0.6
   - Генерация `topicization_run_id` (ULID)
   - Формирование отчёта (TR-50/TR-51)

2. **CLI wiring** (`cli/app.py` → `topicize` команда):
   - Подключить Database, репозитории
   - Получить processed documents
   - Запустить topicization
   - Сохранить TopicCard, TopicBundle
   - Вывод метрик

3. **Репозитории для тем** (если ещё не сделано):
   - `SQLiteTopicCardRepo`
   - `SQLiteTopicBundleRepo`

4. **Тесты topicization**:
   - Unit: детерминизм anchors sorting
   - Integration: mock LLM + real storage

**Файлы для создания**:
- `tg_parser/processing/topicization.py`
- `tg_parser/processing/topicization_prompts.py`
- `tg_parser/storage/sqlite/topic_repo.py` (если нужно)
- `tests/test_topicization.py`

**Ссылки на требования**:
- TR-27..TR-37: topicization
- TR-IF-4: детерминизм тем
- TR-50/TR-51: метрики и отчёты

### СРЕДНИЙ ПРИОРИТЕТ (для полного MVP)

#### 7. **Ingestion (Telethon)** — ОПЦИОНАЛЬНО
**Цель**: Реальный сбор из Telegram

**Что нужно**:
- Telethon client setup
- Auth через session файл
- Backfill/online режимы
- Курсоры (posts + comments)
- Ретраи и rate limiting
- `IngestionStateRepo` реализации

**Файлы**:
- `tg_parser/ingestion/telegram/telethon_client.py`
- `tg_parser/ingestion/orchestrator.py`
- `tg_parser/storage/sqlite/ingestion_state_repo.py`

**Можно отложить**: для MVP достаточно mock данных в `raw_storage.sqlite`

#### 8. **E2E тесты**
- Тесты всего пайплайна с mock данными
- Проверка идемпотентности на уровне всей системы

#### 9. **CLI one-shot `run`**
- Последовательный запуск: ingest → process → topicize → export
- Единая транзакция/rollback при ошибках

---

## 🔧 Технические детали для продолжения

### Важные инварианты (обязательны к соблюдению)

1. **TR-8**: Raw snapshot не перезаписывается
   - `raw_messages`: `ON CONFLICT(source_ref) DO NOTHING`
   - Изменения логируются в `raw_conflicts`

2. **TR-10**: Атомарность курсоров
   - Обновлять `last_post_id` только после успешной записи raw

3. **TR-18**: Уникальность по `source_ref`
   - Все таблицы: UNIQUE или PK по `source_ref`

4. **TR-22**: ProcessedDocument — одно состояние
   - Upsert/replace по `source_ref`

5. **TR-41**: Детерминированные ID
   - `ProcessedDocument.id = "doc:" + source_ref`
   - `TopicCard.id = "topic:" + anchors[0].anchor_ref`
   - `KnowledgeBaseEntry.id` по правилам TR-61

6. **TR-IF-4**: Детерминизм тематизации
   - Anchors сортировка: `(score desc, anchor_ref asc)`
   - Top-N с tie-break

7. **TR-63**: Детерминизм экспорта
   - Стабильная сортировка всех выходных данных

### Формат промптов (рекомендации)

#### Processing промпт (пример):
```python
system_prompt = """
You are a text processing assistant. Extract structured information from Telegram messages.
Output valid JSON with fields: text_clean, summary, topics, entities, language.
"""

user_prompt = f"""
Process this Telegram message:

---
{raw_message.text}
---

Extract:
1. text_clean: cleaned and normalized text
2. summary: brief summary (1-2 sentences) or null if not applicable
3. topics: list of relevant topics/categories
4. entities: list of named entities (person, organization, etc.)
5. language: detected language code (ru, en, etc.)

Output as JSON.
"""
```

#### Topicization промпт (пример):
```python
system_prompt = """
You are a topic analysis assistant. Identify themes and create topic cards.
"""

user_prompt = f"""
Analyze these processed documents and identify themes:

{json.dumps([doc.model_dump() for doc in documents], indent=2)}

For each theme, provide:
1. title: topic title
2. summary: 1-3 sentence description
3. scope_in: list of what's included
4. scope_out: list of what's excluded
5. anchors: list of anchor documents with scores (0-1)
6. type: "singleton" or "cluster"

Output as JSON array of topics.
"""
```

### Конфигурация (из settings.py)

```python
# LLM
llm_provider = "openai"
llm_temperature = 0.0
llm_max_tokens = 4096

# Processing ретраи
processing_max_attempts_per_message = 3
processing_retry_backoff_base = 1.0  # секунды

# Topicization пороги
topicization_top_n_anchors = 3
topicization_singleton_min_len = 300
topicization_singleton_min_score = 0.75
topicization_cluster_min_anchor_score = 0.6
topicization_supporting_min_score = 0.5

# Версии
pipeline_version_processing = "processing:v1.0.0"
pipeline_version_topicization = "topicization:v1.0.0"
```

### Команды для разработки

```bash
# Создать базы
python -m tg_parser.cli init

# Запустить тесты
pytest
pytest -v  # verbose
pytest tests/test_storage_integration.py  # только integration

# Форматирование
ruff format .
ruff check .

# Установка
pip install -e .
```

---

## 📚 Ключевые документы для справки

### Обязательные к изучению:
1. `docs/architecture.md` — целевая схема таблиц (DDL), инварианты
2. `docs/pipeline.md` — детали pipeline, алгоритмы, правила экспорта
3. `docs/technical-requirements.md` — все TR-* требования
4. `docs/contracts/*.schema.json` — JSON Schema контракты
5. `docs/adr/0001-0004` — архитектурные решения (статус Accepted)

### Для справок:
- `docs/tech-stack.md` — выбранный стек
- `docs/testing-strategy.md` — стратегия тестирования
- `docs/notes/implementation-plan.md` — исходный план

---

## 🎯 Критерии готовности MVP

- [ ] CLI `process` работает с mock или real LLM
- [ ] CLI `topicize` формирует темы
- [ ] CLI `export` создаёт все артефакты
- [ ] Все инварианты (TR-8, TR-22, TR-IF-4, etc.) соблюдены
- [ ] Тесты покрывают processing/topicization
- [ ] Можно запустить end-to-end на тестовых данных

---

## 💡 Советы для продолжения

1. **Начните с задачи 4 (Processing Pipeline)**:
   - Сначала реализуйте mock версию без реального LLM
   - Протестируйте на фиксированных данных
   - Добавьте real OpenAI adapter

2. **Используйте существующие mock LLM для тестов**:
   - `ProcessingMockLLM` уже возвращает реалистичные данные
   - `DeterministicMockLLM` для проверки идемпотентности

3. **Следуйте ADR-0004 (Hexagonal)**:
   - Порты → реализации → CLI wiring
   - Бизнес-логика независима от инфраструктуры

4. **Детерминизм критичен**:
   - Всегда фиксируйте `temperature=0`
   - Сохраняйте `prompt_id` (sha256 hash)
   - Тестируйте повторные прогоны

5. **Тесты перед реализацией**:
   - Пишите тесты для портов с mock
   - Потом реализуйте адаптеры

---

## 📞 Контекст для нового чата

**Скажите архитектору/разработчику**:
> "Я продолжаю разработку TG_parser. Базовая инфраструктура готова (domain, storage, export, CLI init, тесты). Следующий шаг — реализация Processing Pipeline (задача 4 из `docs/notes/current-state.md`). Нужно создать OpenAI LLM adapter и processing pipeline для команды `python -m tg_parser.cli process`. Все детали в файле `docs/notes/current-state.md`."

**Прикрепите файлы**:
- `docs/notes/current-state.md` (этот файл)
- `docs/architecture.md`
- `docs/pipeline.md`
- `docs/technical-requirements.md`

---

**Последнее обновление**: 14 декабря 2025  
**Версия проекта**: Базовая инфраструктура MVP  
**Следующая цель**: Processing Pipeline (задача 4)
