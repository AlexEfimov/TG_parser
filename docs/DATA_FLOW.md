# TG_parser — Data Flow

Документация потока данных через систему TG_parser.

## Содержание

1. [Обзор архитектуры](#обзор-архитектуры)
2. [Этап Ingestion](#этап-ingestion)
3. [Этап Processing](#этап-processing)
4. [Этап Topicization](#этап-topicization)
5. [Этап Export](#этап-export)
6. [Схемы данных](#схемы-данных)

---

## Обзор архитектуры

### Диаграмма потока данных

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              TG_parser Pipeline                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────────┐
                                    │  Telegram   │
                                    │  Channels   │
                                    └──────┬──────┘
                                           │
                                           │ Telethon MTProto
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Stage I: INGESTION                                                              │
│  ┌─────────────────┐    ┌─────────────────────┐    ┌─────────────────────────┐  │
│  │ TelethonClient  │───▶│ RawTelegramMessage  │───▶│   raw_storage.sqlite    │  │
│  └─────────────────┘    └─────────────────────┘    │   ├── raw_messages      │  │
│                                                     │   └── raw_conflicts     │  │
│  ┌─────────────────────────────────────────────┐   └─────────────────────────┘  │
│  │        ingestion_state.sqlite               │                                 │
│  │        ├── sources (курсоры, статусы)       │                                 │
│  │        ├── comment_cursors                  │                                 │
│  │        └── source_attempts                  │                                 │
│  └─────────────────────────────────────────────┘                                 │
└──────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           │ source_ref
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Stage II: PROCESSING                                                            │
│  ┌─────────────────┐    ┌─────────────────────┐                                  │
│  │ RawTelegramMsg  │───▶│ ProcessingPipeline  │                                  │
│  └─────────────────┘    │  + OpenAI LLM       │                                  │
│                         └──────────┬──────────┘                                  │
│                                    │                                             │
│                                    ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                    processing_storage.sqlite                            │    │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                       │    │
│  │  │ ProcessedDocument   │  │ processing_failures │                       │    │
│  │  │ • text_clean        │  │ • source_ref        │                       │    │
│  │  │ • summary           │  │ • error_class       │                       │    │
│  │  │ • topics            │  │ • attempts          │                       │    │
│  │  │ • entities          │  └─────────────────────┘                       │    │
│  │  │ • language          │                                                 │    │
│  │  └─────────────────────┘                                                 │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           │ ProcessedDocument[]
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Stage II (cont.): TOPICIZATION                                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐                              │
│  │ ProcessedDocument[] │───▶│TopicizationPipeline │                              │
│  └─────────────────────┘    │  + OpenAI LLM       │                              │
│                             └──────────┬──────────┘                              │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                    processing_storage.sqlite                            │    │
│  │  ┌─────────────────────┐  ┌─────────────────────┐                       │    │
│  │  │     TopicCard       │  │    TopicBundle      │                       │    │
│  │  │ • id (topic:...)    │  │ • topic_id          │                       │    │
│  │  │ • title, summary    │  │ • items[]           │                       │    │
│  │  │ • scope_in/out      │  │   - anchors         │                       │    │
│  │  │ • type (singleton/  │  │   - supporting      │                       │    │
│  │  │        cluster)     │  │ • updated_at        │                       │    │
│  │  │ • anchors[]         │  └─────────────────────┘                       │    │
│  │  └─────────────────────┘                                                 │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           │ TopicCard + TopicBundle + ProcessedDocument
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Stage III: EXPORT                                                               │
│  ┌─────────────────────┐    ┌─────────────────────┐                              │
│  │ KBExporter          │───▶│ KnowledgeBaseEntry  │                              │
│  │ TopicsExporter      │    │ • message-entry     │                              │
│  └─────────────────────┘    │ • topic-entry       │                              │
│                             └──────────┬──────────┘                              │
│                                        │                                         │
│                                        ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         Output Directory                                │    │
│  │  ├── kb_entries.ndjson      (NDJSON: message + topic entries)          │    │
│  │  ├── topics.json            (JSON: каталог тем)                         │    │
│  │  └── topic_<id>.json        (JSON: детальная карточка темы)            │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Связи между компонентами

| Источник | Назначение | Ключ связи | Описание |
|----------|------------|------------|----------|
| Telegram API | RawTelegramMessage | `message_id` | Оригинальные сообщения |
| RawTelegramMessage | ProcessedDocument | `source_ref` | 1:1 трансформация |
| ProcessedDocument | TopicCard | `anchor_ref` | N:M (документ может быть якорем нескольких тем) |
| TopicCard | TopicBundle | `topic_id` | 1:1 (одна подборка на тему в MVP) |
| ProcessedDocument | KnowledgeBaseEntry | `source_ref` | 1:1 маппинг (message-entry) |
| TopicCard | KnowledgeBaseEntry | `topic_id` | 1:1 маппинг (topic-entry) |

---

## Этап Ingestion

### Входные данные

**Источник:** Telegram API через Telethon MTProto клиент

**Типы сообщений:**
- `post` — сообщения в канале
- `comment` — комментарии к постам (если `include_comments=true`)

### Трансформация

```
Telethon Message Object
        │
        ▼
┌───────────────────────────────────────┐
│        Normalization Layer            │
│  • Извлечение id, date, text          │
│  • Формирование source_ref            │
│  • Опционально: усечение raw_payload  │
└───────────────────────────────────────┘
        │
        ▼
    RawTelegramMessage
```

**Формирование `source_ref`:**
```
source_ref = "tg:<channel_id>:<message_type>:<message_id>"

Примеры:
- tg:@durov:post:123
- tg:-1001234567890:post:456
- tg:@channel:comment:789
```

### Выходные данные

**Таблица:** `raw_storage.sqlite.raw_messages`

| Поле | Тип | Описание |
|------|-----|----------|
| `source_ref` | TEXT PK | Канонический идентификатор `tg:<channel>:<type>:<id>` |
| `id` | TEXT | Message ID из Telegram |
| `message_type` | TEXT | `post` или `comment` |
| `channel_id` | TEXT | ID канала |
| `date` | TEXT | ISO 8601 datetime (UTC) |
| `text` | TEXT | Текст сообщения |
| `thread_id` | TEXT | ID треда (для комментариев) |
| `parent_message_id` | TEXT | ID родительского сообщения |
| `language` | TEXT | Определённый язык |
| `raw_payload_json` | TEXT | Оригинальный объект Telethon (JSON) |
| `inserted_at` | TEXT | Время вставки записи |

**Таблица:** `ingestion_state.sqlite.sources`

Хранит состояние источников:
- `last_post_id` — high-watermark постов
- `status` — `active`, `paused`, `error`
- `fail_count` — счётчик ошибок

### Пример данных

**RawTelegramMessage (JSON):**
```json
{
  "id": "12345",
  "message_type": "post",
  "source_ref": "tg:@durov:post:12345",
  "channel_id": "@durov",
  "date": "2025-12-13T10:00:00Z",
  "text": "Hello, world! This is a test message.",
  "thread_id": null,
  "parent_message_id": null,
  "language": null,
  "raw_payload": { ... }
}
```

---

## Этап Processing

### Входные данные

**Источник:** `raw_storage.sqlite.raw_messages`

**Модель:** `RawTelegramMessage`

### Вызов LLM

**Провайдер:** OpenAI API (или OpenAI-compatible)

**Модель:** Настраивается через `LLM_MODEL` (default: `gpt-4o-mini`)

**Параметры запроса:**
```json
{
  "model": "gpt-4o-mini",
  "temperature": 0.0,
  "max_tokens": 4096,
  "response_format": { "type": "json_object" },
  "messages": [
    { "role": "system", "content": "<PROCESSING_SYSTEM_PROMPT>" },
    { "role": "user", "content": "<PROCESSING_USER_PROMPT>" }
  ]
}
```

**Temperature = 0.0:** Обеспечивает детерминизм ответов (TR-38).

### Трансформация

```
RawTelegramMessage
        │
        ▼
┌───────────────────────────────────────┐
│         Processing Pipeline           │
│  1. Формирование промпта              │
│  2. Вызов OpenAI API                  │
│  3. Парсинг JSON ответа               │
│  4. Формирование ProcessedDocument    │
│  5. Сохранение в БД (upsert)          │
└───────────────────────────────────────┘
        │
        ▼
    ProcessedDocument
```

**Извлекаемые поля:**

| Поле | Источник | Описание |
|------|----------|----------|
| `text_clean` | LLM | Очищенный и нормализованный текст |
| `summary` | LLM | Краткое резюме (1-2 предложения) |
| `topics` | LLM | Список тем/категорий |
| `entities` | LLM | Извлечённые сущности (person, org, location) |
| `language` | LLM | Определённый язык (ISO 639-1: ru, en, de) |

### Выходные данные

**Таблица:** `processing_storage.sqlite.processed_documents`

| Поле | Тип | Описание |
|------|-----|----------|
| `source_ref` | TEXT PK | Канонический идентификатор |
| `id` | TEXT | `doc:<source_ref>` |
| `source_message_id` | TEXT | Ссылка на RawTelegramMessage.id |
| `channel_id` | TEXT | ID канала |
| `processed_at` | TEXT | Время обработки (UTC) |
| `text_clean` | TEXT | Очищенный текст |
| `summary` | TEXT | Резюме |
| `topics_json` | TEXT | JSON array тем |
| `entities_json` | TEXT | JSON array сущностей |
| `language` | TEXT | Язык |
| `metadata_json` | TEXT | Метаданные (pipeline_version, model_id, prompt_id) |

**Таблица:** `processing_storage.sqlite.processing_failures`

Записи о неудачной обработке:

| Поле | Тип | Описание |
|------|-----|----------|
| `source_ref` | TEXT PK | Идентификатор сообщения |
| `channel_id` | TEXT | ID канала |
| `attempts` | INTEGER | Количество попыток |
| `last_attempt_at` | TEXT | Время последней попытки |
| `error_class` | TEXT | Класс ошибки |
| `error_message` | TEXT | Текст ошибки |

### Пример данных

**ProcessedDocument (JSON):**
```json
{
  "id": "doc:tg:@durov:post:12345",
  "source_ref": "tg:@durov:post:12345",
  "source_message_id": "12345",
  "channel_id": "@durov",
  "processed_at": "2025-12-13T12:00:00Z",
  "text_clean": "Hello, world! This is a test message.",
  "summary": "A greeting message from the channel.",
  "topics": ["greeting", "test"],
  "entities": [
    { "type": "concept", "value": "test", "confidence": 0.8 }
  ],
  "language": "en",
  "metadata": {
    "pipeline_version": "processing:v1.0.0",
    "model_id": "gpt-4o-mini",
    "prompt_id": "sha256:abc123...",
    "prompt_name": "processing_v1",
    "parameters": {
      "temperature": 0.0,
      "max_tokens": 4096
    }
  }
}
```

---

## Этап Topicization

### Входные данные

**Источник:** `processing_storage.sqlite.processed_documents`

**Модель:** Список `ProcessedDocument` для канала

### Алгоритм кластеризации

```
ProcessedDocument[]
        │
        ▼
┌───────────────────────────────────────┐
│       Topicization Pipeline           │
│  1. Подготовка корпуса                │
│  2. Выбор кандидатов в якоря          │
│  3. Генерация тем через LLM           │
│  4. Нормализация и детерминизация     │
│  5. Применение критериев качества     │
│  6. Формирование TopicBundle          │
└───────────────────────────────────────┘
        │
        ▼
    TopicCard + TopicBundle
```

### Критерии качества тем (TR-35)

**Singleton (тема-статья):**
- Один якорный материал
- `score >= 0.75`
- `text_clean.length >= 300` символов

**Cluster (тема-кластер):**
- Минимум 2 якоря
- `score >= 0.6` для всех якорей
- Top-N якорей (N=3)

### Детерминизм (TR-IF-4)

Порядок anchors детерминирован:
1. Сортировка по `score` (по убыванию)
2. Tie-break по `anchor_ref` (по возрастанию)
3. `TopicCard.id = "topic:" + anchors[0].anchor_ref`

### Выходные данные

**Таблица:** `processing_storage.sqlite.topic_cards`

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | TEXT PK | `topic:<primary_anchor_ref>` |
| `title` | TEXT | Название темы |
| `summary` | TEXT | Описание темы |
| `scope_in_json` | TEXT | Что относится к теме |
| `scope_out_json` | TEXT | Что не относится |
| `type` | TEXT | `singleton` или `cluster` |
| `anchors_json` | TEXT | JSON array якорей |
| `sources_json` | TEXT | JSON array каналов |
| `updated_at` | TEXT | Время обновления |
| `tags_json` | TEXT | Теги |
| `metadata_json` | TEXT | Метаданные |

**Таблица:** `processing_storage.sqlite.topic_bundles`

| Поле | Тип | Описание |
|------|-----|----------|
| `topic_id` | TEXT | FK на TopicCard.id |
| `updated_at` | TEXT | Время обновления |
| `items_json` | TEXT | JSON array элементов (anchors + supporting) |
| `channels_json` | TEXT | JSON array каналов |
| `metadata_json` | TEXT | Метаданные |

### Пример данных

**TopicCard (JSON):**
```json
{
  "id": "topic:tg:@channel:post:123",
  "title": "Технологии искусственного интеллекта",
  "summary": "Обзор современных подходов к ИИ и машинному обучению.",
  "scope_in": ["Машинное обучение", "Нейронные сети", "GPT модели"],
  "scope_out": ["Традиционное программирование", "Базы данных"],
  "type": "cluster",
  "anchors": [
    {
      "channel_id": "@channel",
      "message_id": "123",
      "message_type": "post",
      "anchor_ref": "tg:@channel:post:123",
      "score": 0.95
    },
    {
      "channel_id": "@channel",
      "message_id": "456",
      "message_type": "post",
      "anchor_ref": "tg:@channel:post:456",
      "score": 0.82
    }
  ],
  "sources": ["@channel"],
  "updated_at": "2025-12-13T14:00:00Z",
  "tags": ["AI", "ML", "technology"],
  "metadata": {
    "topicization_run_id": "run_20251213_140000",
    "pipeline_version": "topicization:v1.0.0",
    "model_id": "gpt-4o-mini",
    "algorithm": "llm_clustering"
  }
}
```

**TopicBundle (JSON):**
```json
{
  "topic_id": "topic:tg:@channel:post:123",
  "items": [
    {
      "channel_id": "@channel",
      "message_id": "123",
      "message_type": "post",
      "source_ref": "tg:@channel:post:123",
      "role": "anchor",
      "score": 0.95
    },
    {
      "channel_id": "@channel",
      "message_id": "456",
      "message_type": "post",
      "source_ref": "tg:@channel:post:456",
      "role": "anchor",
      "score": 0.82
    },
    {
      "channel_id": "@channel",
      "message_id": "789",
      "message_type": "post",
      "source_ref": "tg:@channel:post:789",
      "role": "supporting",
      "score": 0.65,
      "justification": "Related discussion about neural networks"
    }
  ],
  "updated_at": "2025-12-13T14:05:00Z",
  "channels": ["@channel"]
}
```

---

## Этап Export

### Входные данные

**Источники:**
- `ProcessedDocument` — для message-entries
- `TopicCard` + `TopicBundle` — для topic-entries

### Маппинг в KnowledgeBaseEntry

**Message Entry (TR-61):**
```
ProcessedDocument
        │
        ▼
┌───────────────────────────────────────┐
│  id = "kb:msg:" + source_ref          │
│  source.type = "telegram_message"     │
│  created_at = processed_at            │
│  content = summary + text_clean       │
│  topics = ProcessedDocument.topics    │
└───────────────────────────────────────┘
        │
        ▼
    KnowledgeBaseEntry
```

**Topic Entry (TR-61):**
```
TopicCard + TopicBundle
        │
        ▼
┌───────────────────────────────────────┐
│  id = "kb:topic:" + topic_id          │
│  source.type = "topic"                │
│  created_at = updated_at              │
│  title = TopicCard.title              │
│  content = summary + scope_in/out     │
│  resolved_sources = [...]             │
└───────────────────────────────────────┘
        │
        ▼
    KnowledgeBaseEntry
```

### Форматы вывода

**NDJSON (Newline-delimited JSON):**
- Файл: `kb_entries.ndjson`
- Одна JSON-запись на строку
- Подходит для стриминговой обработки

**JSON:**
- Файл: `topics.json` — массив TopicCard
- Файлы: `topic_<id>.json` — детальные карточки

### Структура файлов

```
output/
├── kb_entries.ndjson      # Все KB entries (message + topic)
├── topics.json            # Каталог тем
│   [
│     { "id": "topic:...", "title": "...", ... },
│     ...
│   ]
└── topic_<id>.json        # Детальная карточка темы
    {
      "topic_card": { ... },
      "topic_bundle": { ... },
      "resolved_sources": [ ... ],
      "exported_at": "2025-12-13T15:00:00Z",
      "export_version": "export:v1.0.0"
    }
```

### Telegram URL Resolution (TR-65)

**Алгоритм построения URL:**

1. Если известен `channel_username`:
   ```
   https://t.me/<channel_username>/<message_id>
   ```

2. Если `channel_id` начинается с `-100`:
   ```
   internal_id = channel_id без префикса "-100"
   https://t.me/c/<internal_id>/<message_id>
   ```

3. Если `channel_id` похож на username (`^[A-Za-z0-9_]{5,}$`):
   ```
   https://t.me/<channel_id>/<message_id>
   ```

4. Иначе: `telegram_url = null`

### Пример данных

**KnowledgeBaseEntry — Message (NDJSON строка):**
```json
{"id":"kb:msg:tg:@durov:post:12345","source":{"type":"telegram_message","channel_id":"@durov","message_id":"12345","message_type":"post","source_ref":"tg:@durov:post:12345"},"created_at":"2025-12-13T12:00:00Z","title":"Message 12345","content":"A greeting message from the channel.\n\nHello, world! This is a test message.","topics":["greeting","test"],"tags":[],"metadata":{"telegram_url":"https://t.me/durov/12345"}}
```

**KnowledgeBaseEntry — Topic (NDJSON строка):**
```json
{"id":"kb:topic:topic:tg:@channel:post:123","source":{"type":"topic","topic_id":"topic:tg:@channel:post:123"},"created_at":"2025-12-13T14:00:00Z","title":"Технологии искусственного интеллекта","content":"Обзор современных подходов к ИИ и машинному обучению.\n\n**Scope In:** Машинное обучение, Нейронные сети, GPT модели\n**Scope Out:** Традиционное программирование, Базы данных","topics":["topic:tg:@channel:post:123"],"tags":["AI","ML","technology"]}
```

---

## Схемы данных

### JSON Schema контракты

Все схемы данных определены в `docs/contracts/`:

| Файл | Модель | Описание |
|------|--------|----------|
| `raw_telegram_message.schema.json` | RawTelegramMessage | Сырое сообщение Telegram |
| `processed_document.schema.json` | ProcessedDocument | Обработанный документ |
| `topic_card.schema.json` | TopicCard | Карточка темы |
| `topic_bundle.schema.json` | TopicBundle | Подборка по теме |
| `knowledge_base_entry.schema.json` | KnowledgeBaseEntry | Запись базы знаний |

### Идентификаторы и ключи

**Формат `source_ref`:**
```
tg:<channel_id>:<message_type>:<message_id>

Regex: ^tg:[^:]+:(post|comment):[^:]+$
```

**Формат идентификаторов:**

| Модель | Формат ID | Пример |
|--------|-----------|--------|
| RawTelegramMessage | `<message_id>` | `12345` |
| ProcessedDocument | `doc:<source_ref>` | `doc:tg:@durov:post:12345` |
| TopicCard | `topic:<anchor_ref>` | `topic:tg:@channel:post:123` |
| KnowledgeBaseEntry (msg) | `kb:msg:<source_ref>` | `kb:msg:tg:@durov:post:12345` |
| KnowledgeBaseEntry (topic) | `kb:topic:<topic_id>` | `kb:topic:topic:tg:@channel:post:123` |

### Метаданные трассируемости

Каждый ProcessedDocument и TopicCard содержит `metadata` для воспроизводимости:

```json
{
  "metadata": {
    "pipeline_version": "processing:v1.0.0",
    "model_id": "gpt-4o-mini",
    "prompt_id": "sha256:abc123def456...",
    "prompt_name": "processing_v1",
    "parameters": {
      "temperature": 0.0,
      "max_tokens": 4096
    }
  }
}
```

---

## Связанные документы

- [User Guide](USER_GUIDE.md) — руководство пользователя
- [LLM Prompts](LLM_PROMPTS.md) — документация промптов
- [Architecture](architecture.md) — архитектура и DDL схемы
- [Pipeline](pipeline.md) — детали pipeline
- [Technical Requirements](technical-requirements.md) — технические требования

