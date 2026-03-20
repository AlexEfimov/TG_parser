# 📊 Архитектура данных TG_parser

Полное описание структуры данных, создаваемых TG_parser: таблицы базы данных, выходные файлы, поля и связи между ними.

**Версия документа:** 1.0  
**Дата:** 31 декабря 2025  
**Версия TG_parser:** v3.1.1

---

## 📋 Содержание

1. [Обзор архитектуры](#обзор-архитектуры)
2. [База данных PostgreSQL](#база-данных-postgresql)
3. [Выходные файлы](#выходные-файлы)
4. [Связи между данными](#связи-между-данными)
5. [Примеры использования](#примеры-использования)
6. [FAQ](#faq)

---

## Обзор архитектуры

### Поток данных

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TG_parser Pipeline                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐   │
│  │  Telegram  │────▶│  Ingestion │────▶│ Processing │────▶│   Export   │   │
│  │    API     │     │  (Stage I) │     │ (Stage II) │     │ (Stage III)│   │
│  └────────────┘     └─────┬──────┘     └─────┬──────┘     └─────┬──────┘   │
│                           │                  │                   │          │
│                           ▼                  ▼                   ▼          │
│                    ┌────────────┐     ┌────────────┐     ┌────────────┐    │
│                    │    raw_    │     │ processed_ │     │  Output    │    │
│                    │  messages  │     │ documents  │     │  Files     │    │
│                    │            │     │   topics   │     │ (.ndjson,  │    │
│                    │            │     │  bundles   │     │   .json)   │    │
│                    └────────────┘     └────────────┘     └────────────┘    │
│                           │                  │                   │          │
│                           └──────────────────┴───────────────────┘          │
│                                              │                               │
│                                              ▼                               │
│                                    ┌──────────────────┐                     │
│                                    │    PostgreSQL    │                     │
│                                    │   (все данные)   │                     │
│                                    └──────────────────┘                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Принцип хранения

После обработки канала **все данные сохраняются локально** в PostgreSQL:
- ❌ Telegram API больше НЕ нужен для доступа к текстам
- ✅ Все тексты, метаданные и обработанные результаты — в БД
- ✅ Выходные файлы — для интеграции с внешними системами (RAG, KB)

---

## База данных PostgreSQL

### Общая структура

```
PostgreSQL Database: tg_parser
│
├── INGESTION STATE (Stage I)
│   ├── sources              ← Состояние источников (каналов)
│   ├── comment_cursors      ← Курсоры комментариев
│   └── source_attempts      ← История попыток ingestion
│
├── RAW STORAGE (Stage I)
│   ├── raw_messages         ← 🔥 СЫРЫЕ ТЕКСТЫ из Telegram
│   └── raw_conflicts        ← Журнал конфликтов при ingestion
│
├── PROCESSING STORAGE (Stage II)
│   ├── processed_documents  ← 🔥 ОБРАБОТАННЫЕ ДОКУМЕНТЫ
│   ├── processing_failures  ← Журнал ошибок обработки
│   ├── topic_cards          ← Карточки тем (TopicCard)
│   └── topic_bundles        ← Подборки по темам (TopicBundle)
│
├── API (Phase 2F)
│   └── api_jobs             ← Async jobs (processing, export)
│
└── AGENTS (Phase 3B)
    ├── agent_states         ← Состояние агентов
    ├── task_history         ← История выполнения задач
    ├── agent_stats          ← Статистика агентов
    └── handoff_history      ← История передачи между агентами
```

---

### Таблица: `sources`

**Назначение:** Хранит состояние источников (Telegram каналов) и курсоры для incremental ingestion.

**Создаётся на этапе:** Stage I (Ingestion)

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `source_id` | TEXT (PK) | Уникальный ID источника | `news` |
| `channel_id` | TEXT | ID канала в Telegram | `BiocodebySechenov` |
| `channel_username` | TEXT | Username канала | `@BiocodebySechenov` |
| `status` | TEXT | Статус источника | `active`, `paused`, `error` |
| `include_comments` | INTEGER | Собирать комментарии | `0` или `1` |
| `history_from` | TEXT | Начало периода сбора | `2025-01-01T00:00:00` |
| `history_to` | TEXT | Конец периода сбора | `null` |
| `poll_interval_seconds` | INTEGER | Интервал опроса | `3600` |
| `batch_size` | INTEGER | Размер батча | `100` |
| `last_post_id` | TEXT | High-watermark постов | `163` |
| `backfill_completed_at` | TEXT | Когда завершён backfill | ISO 8601 или `null` |
| `last_attempt_at` | TEXT | Последняя попытка | ISO 8601 |
| `last_success_at` | TEXT | Последний успех | ISO 8601 |
| `fail_count` | INTEGER | Счётчик ошибок | `0` |
| `last_error` | TEXT | Последняя ошибка | `null` или текст ошибки |
| `rate_limit_until` | TEXT | Rate limit до | ISO 8601 или `null` |
| `comments_unavailable` | INTEGER | Комментарии недоступны | `0` или `1` |
| `created_at` | TEXT | Время создания | ISO 8601 |
| `updated_at` | TEXT | Время обновления | ISO 8601 |

**Индексы:**
- `sources_status_idx(status)`
- `sources_channel_id_idx(channel_id)`

---

### Таблица: `raw_messages`

**Назначение:** Хранит оригинальные сообщения из Telegram без изменений.

**Создаётся на этапе:** Stage I (Ingestion)

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `source_ref` | TEXT (PK) | Уникальный идентификатор | `tg:BiocodebySechenov:post:153` |
| `id` | TEXT | Message ID из Telegram | `153` |
| `message_type` | TEXT | Тип сообщения | `post` или `comment` |
| `channel_id` | TEXT | ID канала | `BiocodebySechenov` |
| `date` | TEXT | Дата публикации (ISO 8601) | `2025-12-29T10:30:00` |
| `text` | TEXT | **Оригинальный текст сообщения** | `Доброе утро, друзья!...` |
| `thread_id` | TEXT | ID треда (для комментариев) | `123` или `null` |
| `parent_message_id` | TEXT | ID родительского сообщения | `120` или `null` |
| `language` | TEXT | Определённый язык | `ru` |
| `raw_payload_json` | TEXT | Полный объект Telethon (JSON) | `{"_": "Message", ...}` |
| `raw_payload_truncated` | INTEGER | Флаг усечения payload | `0` или `1` |
| `raw_payload_original_size_bytes` | INTEGER | Размер оригинала | `4096` |
| `inserted_at` | TEXT | Время вставки в БД | `2025-12-29T10:35:00` |

**Индексы:**
- `raw_messages_channel_date_idx(channel_id, date)`
- `raw_messages_thread_idx(thread_id)`
- `raw_messages_type_idx(message_type)`

**Ключевое поле для RAG:** `text` — оригинальный текст сообщения.

---

### Таблица: `processed_documents`

**Назначение:** Хранит обработанные LLM документы с очищенным текстом, резюме и извлечёнными темами.

**Создаётся на этапе:** Stage II (Processing)

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `source_ref` | TEXT (PK) | Уникальный идентификатор | `tg:BiocodebySechenov:post:153` |
| `id` | TEXT | ID документа | `doc:tg:BiocodebySechenov:post:153` |
| `source_message_id` | TEXT | Message ID из Telegram | `153` |
| `channel_id` | TEXT | ID канала | `BiocodebySechenov` |
| `processed_at` | TEXT | Время обработки (ISO 8601) | `2025-12-29T20:48:17` |
| `text_clean` | TEXT | **Очищенный текст** | `Доброе утро, дорогие друзья!...` |
| `summary` | TEXT | **LLM-резюме сообщения** | `Сообщение обсуждает влияние...` |
| `topics_json` | TEXT | Извлечённые темы (JSON array) | `["здоровье", "экраны"]` |
| `entities_json` | TEXT | Извлечённые сущности (JSON) | `[{"type": "org", "value": "WHO"}]` |
| `language` | TEXT | Определённый язык | `ru` |
| `metadata_json` | TEXT | Метаданные обработки (JSON) | `{"model_id": "gpt-4o-mini", ...}` |

**Индексы:**
- `processed_documents_channel_idx(channel_id)`
- `processed_documents_processed_at_idx(processed_at)`

**Ключевые поля для RAG:**
- `text_clean` — очищенный полный текст (рекомендуется для embeddings)
- `summary` — краткое резюме (для preview)
- `topics_json` — для фильтрации по категориям

---

### Таблица: `topic_cards`

**Назначение:** Хранит карточки тем (TopicCard) — результат кластеризации сообщений.

**Создаётся на этапе:** Stage II (Topicization)

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `id` | TEXT (PK) | ID темы | `topic:tg:BiocodebySechenov:post:153` |
| `title` | TEXT | Название темы | `Влияние экранного времени на здоровье` |
| `summary` | TEXT | Описание темы | `Сообщения рассматривают влияние...` |
| `type` | TEXT | Тип темы | `cluster` или `singleton` |
| `scope_in_json` | TEXT | Что включено (JSON array) | `["экранное время", "здоровье"]` |
| `scope_out_json` | TEXT | Что исключено (JSON array) | `["психическое здоровье"]` |
| `anchors_json` | TEXT | Якорные сообщения (JSON) | `[{"anchor_ref": "...", "score": 0.9}]` |
| `tags_json` | TEXT | Теги (JSON array) | `["здоровье", "профилактика"]` |
| `sources_json` | TEXT | Источники (JSON array) | `["BiocodebySechenov"]` |
| `related_topics_json` | TEXT | Связанные темы (JSON) | `null` или `["topic:..."]` |
| `status` | TEXT | Статус темы | `null` (для будущего использования) |
| `metadata_json` | TEXT | Метаданные (JSON) | `{"model_id": "gpt-4o-mini", ...}` |
| `updated_at` | TEXT | Время обновления | `2025-12-29T20:51:16` |

**Индексы:**
- `topic_cards_updated_at_idx(updated_at)`

**Ключевые поля для Knowledge Graph:**
- `anchors_json` — связи с сообщениями
- `scope_in_json` / `scope_out_json` — семантические границы

---

### Таблица: `topic_bundles`

**Назначение:** Хранит подборки сообщений по темам (anchor + supporting items).

**Создаётся на этапе:** Stage II (Topicization)

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `topic_id` | TEXT | ID связанной темы | `topic:tg:BiocodebySechenov:post:153` |
| `updated_at` | TEXT | Время обновления | `2025-12-29T20:51:21` |
| `time_from` | TEXT | Начало периода (для снапшотов) | `null` (в MVP) |
| `time_to` | TEXT | Конец периода (для снапшотов) | `null` (в MVP) |
| `items_json` | TEXT | Элементы подборки (JSON) | `[{"source_ref": "...", "role": "anchor"}]` |
| `channels_json` | TEXT | Каналы (JSON array) | `["BiocodebySechenov"]` |
| `metadata_json` | TEXT | Метаданные (JSON) | `{"algorithm": "llm_relevance", ...}` |

**Индексы:**
- `topic_bundles_current_unique_idx(topic_id)` — для текущих подборок (time_from/time_to = NULL)
- `topic_bundles_snapshot_unique_idx(topic_id, time_from, time_to)` — для снапшотов (будущее)

**Примечание:** В MVP одна актуальная подборка на тему (без time_range).

**Структура `items_json`:**
```json
[
  {
    "channel_id": "BiocodebySechenov",
    "message_id": "153",
    "message_type": "post",
    "source_ref": "tg:BiocodebySechenov:post:153",
    "role": "anchor",
    "score": 0.9,
    "justification": null,
    "parent_message_id": null,
    "thread_id": null
  },
  {
    "channel_id": "BiocodebySechenov",
    "message_id": "163",
    "message_type": "post",
    "source_ref": "tg:BiocodebySechenov:post:163",
    "role": "supporting",
    "score": 0.8,
    "justification": "Связано с темой экранного времени...",
    "parent_message_id": null,
    "thread_id": null
  }
]
```

---

## Выходные файлы

### Структура директории экспорта

```
output/<channel>/
├── kb_entries.ndjson          # Knowledge Base entries (NDJSON)
├── topics.json                # Каталог всех тем (JSON array)
└── topic_<id>.json (N файлов) # Детальные карточки тем (JSON object)
```

---

### Файл: `kb_entries.ndjson`

**Формат:** NDJSON (Newline-Delimited JSON) — одна JSON-запись на строку.

**Назначение:** Основной файл для интеграции с RAG-системами и базами знаний.

**Каждая строка содержит объект `KnowledgeBaseEntry`:**

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `id` | string | ✅ | Уникальный ID записи KB |
| `title` | string | ✅ | Заголовок записи |
| `content` | string | ✅ | **Основной контент** (summary + "\n\n" + text_clean) |
| `topics` | array[string] | ❌ | Темы/категории |
| `tags` | array[string] | ❌ | Дополнительные теги |
| `source` | object | ✅ | Информация об источнике |
| `source.type` | string | ✅ | `telegram_message` или `topic` |
| `source.channel_id` | string | ❌ | ID канала |
| `source.message_id` | string | ❌ | ID сообщения |
| `source.message_type` | string | ❌ | `post` или `comment` |
| `source.source_ref` | string | ❌ | **Ключ связи с БД** |
| `source.topic_id` | string | ❌ | ID темы (для topic entries) |
| `metadata` | object | ❌ | Дополнительные данные |
| `metadata.telegram_url` | string | ❌ | Ссылка на сообщение в Telegram |
| `metadata.processing` | object | ❌ | Информация об обработке |
| `vector` | array[number] | ❌ | Опциональный embedding |
| `created_at` | string | ✅ | Время создания (ISO 8601) |

**Пример записи:**
```json
{
  "id": "kb:msg:tg:BiocodebySechenov:post:153",
  "title": "Message 153",
  "content": "Сообщение обсуждает влияние экранного времени на здоровье...\n\nДоброе утро, дорогие друзья!...",
  "topics": ["здоровье", "экранное время", "сердечно-сосудистые заболевания"],
  "tags": [],
  "source": {
    "type": "telegram_message",
    "channel_id": "BiocodebySechenov",
    "message_id": "153",
    "message_type": "post",
    "source_ref": "tg:BiocodebySechenov:post:153",
    "topic_id": null
  },
  "metadata": {
    "telegram_url": "https://t.me/BiocodebySechenov/153",
    "processing": {
      "model_id": "gpt-4o-mini",
      "pipeline_version": "processing:v1.0.0"
    }
  },
  "vector": null,
  "created_at": "2025-12-29T20:48:17"
}
```

**✅ Поле `content`:** Содержит `summary + "\n\n" + text_clean` — то есть **полный очищенный текст** с резюме в начале. Это основное поле для RAG embeddings.

---

### Файл: `topics.json`

**Формат:** JSON array

**Назначение:** Каталог всех тем канала.

**Структура массива (каждый элемент — TopicCard):**

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | string | Уникальный ID темы |
| `title` | string | Название темы |
| `summary` | string | Краткое описание темы |
| `type` | string | `cluster` (несколько сообщений) или `singleton` (одно) |
| `scope_in` | array[string] | Что включено в тему |
| `scope_out` | array[string] | Что исключено из темы |
| `anchors` | array[object] | **Якорные сообщения** |
| `anchors[].anchor_ref` | string | **Ключ связи с БД** |
| `anchors[].channel_id` | string | ID канала |
| `anchors[].message_id` | string | ID сообщения |
| `anchors[].message_type` | string | `post` или `comment` |
| `anchors[].score` | number | Оценка релевантности (0.0–1.0) |
| `anchors[].parent_message_id` | string | ID родительского сообщения (для comment) |
| `anchors[].thread_id` | string | ID треда (для comment) |
| `tags` | array[string] | Теги темы |
| `sources` | array[string] | Источники (каналы) |
| `related_topics` | array[string] | Связанные темы (опционально) |
| `status` | string | Статус темы (опционально) |
| `metadata` | object | Метаданные обработки |
| `updated_at` | string | Время обновления |

**Пример:**
```json
[
  {
    "id": "topic:tg:BiocodebySechenov:post:153",
    "title": "Влияние экранного времени и праздников на здоровье",
    "summary": "Сообщения рассматривают влияние экранного времени на здоровье...",
    "type": "cluster",
    "scope_in": ["экранное время", "сердечно-сосудистые заболевания"],
    "scope_out": ["психическое здоровье"],
    "anchors": [
      {
        "anchor_ref": "tg:BiocodebySechenov:post:153",
        "channel_id": "BiocodebySechenov",
        "message_id": "153",
        "message_type": "post",
        "score": 0.9
      },
      {
        "anchor_ref": "tg:BiocodebySechenov:post:158",
        "channel_id": "BiocodebySechenov",
        "message_id": "158",
        "message_type": "post",
        "score": 0.7
      }
    ],
    "tags": ["здоровье", "праздники"],
    "sources": ["BiocodebySechenov"],
    "metadata": {
      "algorithm": "llm_clustering",
      "model_id": "gpt-4o-mini",
      "parameters": {
        "min_cluster_score": 0.6,
        "max_anchors": 3
      }
    },
    "updated_at": "2025-12-29T20:51:16"
  }
]
```

---

### Файлы: `topic_<id>.json`

**Формат:** JSON object

**Назначение:** Детальная карточка одной темы с полным списком связанных сообщений.

**Имя файла:** `topic_<topic_id с заменой ':' на '_'>.json`

Пример: `topic_topic_tg_BiocodebySechenov_post_153.json`

**Структура:**

| Поле | Тип | Описание |
|------|-----|----------|
| `topic_card` | object | Полная карточка темы (см. topics.json) |
| `topic_bundle` | object | Подборка сообщений |
| `topic_bundle.topic_id` | string | ID темы |
| `topic_bundle.items` | array[object] | **Все связанные сообщения** |
| `topic_bundle.items[].source_ref` | string | **Ключ связи с БД** |
| `topic_bundle.items[].channel_id` | string | ID канала |
| `topic_bundle.items[].message_id` | string | ID сообщения |
| `topic_bundle.items[].message_type` | string | `post` или `comment` |
| `topic_bundle.items[].role` | string | `anchor` или `supporting` |
| `topic_bundle.items[].score` | number | Оценка релевантности |
| `topic_bundle.items[].justification` | string | Обоснование (для supporting) |
| `topic_bundle.items[].parent_message_id` | string | ID родительского (для comment) |
| `topic_bundle.items[].thread_id` | string | ID треда (для comment) |
| `topic_bundle.channels` | array[string] | Каналы, входящие в подборку |
| `topic_bundle.time_range` | object | Опциональный диапазон дат |
| `topic_bundle.updated_at` | string | Время обновления подборки |
| `topic_bundle.metadata` | object | Метаданные подборки |
| `resolved_sources` | array[object] | Источники с URL |
| `resolved_sources[].source_ref` | string | **Ключ связи с БД** |
| `resolved_sources[].channel_id` | string | ID канала |
| `resolved_sources[].message_id` | string | ID сообщения |
| `resolved_sources[].message_type` | string | `post` или `comment` |
| `resolved_sources[].telegram_url` | string | **Ссылка на Telegram** |
| `resolved_sources[].role` | string | `anchor` или `supporting` |
| `resolved_sources[].score` | number | Оценка релевантности |
| `exported_at` | string | Время экспорта |
| `export_version` | string | Версия формата |

**Пример:**
```json
{
  "topic_card": {
    "id": "topic:tg:BiocodebySechenov:post:153",
    "title": "Влияние экранного времени и праздников на здоровье",
    "summary": "...",
    "anchors": [...]
  },
  "topic_bundle": {
    "topic_id": "topic:tg:BiocodebySechenov:post:153",
    "updated_at": "2025-12-29T20:51:21",
    "channels": ["BiocodebySechenov"],
    "time_range": null,
    "items": [
      {
        "source_ref": "tg:BiocodebySechenov:post:153",
        "channel_id": "BiocodebySechenov",
        "message_id": "153",
        "message_type": "post",
        "role": "anchor",
        "score": 0.9,
        "justification": null,
        "parent_message_id": null,
        "thread_id": null
      },
      {
        "source_ref": "tg:BiocodebySechenov:post:163",
        "channel_id": "BiocodebySechenov",
        "message_id": "163",
        "message_type": "post",
        "role": "supporting",
        "score": 0.8,
        "justification": "Связано с темой экранного времени...",
        "parent_message_id": null,
        "thread_id": null
      }
    ],
    "metadata": {
      "algorithm": "llm_relevance",
      "pipeline_version": "topicization:v1.0.0"
    }
  },
  "resolved_sources": [
    {
      "source_ref": "tg:BiocodebySechenov:post:153",
      "channel_id": "BiocodebySechenov",
      "message_id": "153",
      "telegram_url": "https://t.me/BiocodebySechenov/153",
      "role": "anchor",
      "score": 0.9
    }
  ],
  "exported_at": "2025-12-29T20:52:02Z",
  "export_version": "export:v1.0.0"
}
```

---

## Связи между данными

### Диаграмма связей

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           КЛЮЧ СВЯЗИ: source_ref                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Формат: tg:<channel_id>:<message_type>:<message_id>                        │
│  Пример: tg:BiocodebySechenov:post:153                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

        OUTPUT FILES                                    DATABASE
        ────────────                                    ────────

┌─────────────────────────┐                    ┌─────────────────────────┐
│   kb_entries.ndjson     │                    │     raw_messages        │
│                         │                    │                         │
│ source.source_ref ──────┼────────────────────┼──▶ source_ref (PK)     │
│                         │                    │     text                │
│                         │                    │     raw_payload_json    │
└─────────────────────────┘                    └─────────────────────────┘
           │                                              │
           │                                              │
           │ source_ref                                   │ source_ref
           │                                              │
           ▼                                              ▼
┌─────────────────────────┐                    ┌─────────────────────────┐
│      topics.json        │                    │  processed_documents    │
│                         │                    │                         │
│ anchors[].anchor_ref ───┼────────────────────┼──▶ source_ref (PK)     │
│                         │                    │     text_clean          │
│                         │                    │     summary             │
└─────────────────────────┘                    │     topics_json         │
           │                                   │     entities_json       │
           │                                   └─────────────────────────┘
           │ topic_id
           │
           ▼
┌─────────────────────────┐                    ┌─────────────────────────┐
│    topic_*.json         │                    │      topic_cards        │
│                         │                    │                         │
│ topic_bundle.items[].   │                    │     id (PK)             │
│   source_ref ───────────┼────────────────────┼──▶ (через anchors_json) │
│                         │                    │     title               │
│ resolved_sources[].     │                    │     summary             │
│   source_ref ───────────┼────────────────────┼──▶                      │
│   telegram_url          │                    └─────────────────────────┘
└─────────────────────────┘
                                               ┌─────────────────────────┐
                                               │     topic_bundles       │
                                               │                         │
                                               │     topic_id            │
                                               │     items_json          │
                                               └─────────────────────────┘
```

### Таблица связей

| Из | Поле | В | Поле | Тип связи |
|----|------|---|------|-----------|
| `kb_entries.ndjson` | `source.source_ref` | `raw_messages` | `source_ref` | 1:1 |
| `kb_entries.ndjson` | `source.source_ref` | `processed_documents` | `source_ref` | 1:1 |
| `topics.json` | `anchors[].anchor_ref` | `processed_documents` | `source_ref` | N:1 |
| `topic_*.json` | `topic_bundle.items[].source_ref` | `processed_documents` | `source_ref` | N:1 |
| `topic_*.json` | `topic_card.id` | `topic_cards` | `id` | 1:1 |
| `topic_bundles` | `topic_id` | `topic_cards` | `id` | 1:1 |

---

## Примеры использования

### 1. RAG напрямую из kb_entries (без БД)

Поскольку `content` уже содержит полный текст, можно использовать напрямую:

```python
import json

def load_rag_corpus(ndjson_path: str) -> list[dict]:
    """Загрузить корпус для RAG из kb_entries.ndjson."""
    corpus = []
    with open(ndjson_path) as f:
        for line in f:
            entry = json.loads(line)
            corpus.append({
                'id': entry['id'],
                'text': entry['content'],      # Полный текст (summary + text_clean)
                'topics': entry['topics'],
                'telegram_url': entry['metadata'].get('telegram_url'),
                'source_ref': entry['source']['source_ref']
            })
    return corpus

# Использование
corpus = load_rag_corpus('output/BiocodebySechenov/kb_entries.ndjson')
for doc in corpus[:3]:
    print(f"ID: {doc['id']}")
    print(f"Text length: {len(doc['text'])} chars")
    print(f"Topics: {doc['topics']}")
    print()
```

### 2. Получить text_clean из БД (если нужен без summary)

```python
import json
import asyncpg

async def get_text_clean(source_ref: str) -> str:
    """Получить только text_clean из БД по source_ref."""
    conn = await asyncpg.connect(
        host='localhost',
        database='tg_parser',
        user='tg_parser_user',
        password='password'
    )
    
    row = await conn.fetchrow("""
        SELECT text_clean FROM processed_documents
        WHERE source_ref = $1
    """, source_ref)
    
    await conn.close()
    return row['text_clean'] if row else None
```

### 3. Найти все сообщения по теме

```python
import json

def get_messages_for_topic(topic_file: str) -> list[str]:
    """Получить все source_ref для темы."""
    with open(topic_file) as f:
        topic = json.load(f)
    
    source_refs = []
    for item in topic['topic_bundle']['items']:
        source_refs.append(item['source_ref'])
    
    return source_refs

# Использование
refs = get_messages_for_topic('output/BiocodebySechenov/topic_topic_tg_BiocodebySechenov_post_153.json')
# → ['tg:BiocodebySechenov:post:153', 'tg:BiocodebySechenov:post:158', ...]
```

### 4. RAG с полными текстами

```python
import json
import asyncpg

async def build_rag_corpus(channel_id: str) -> list[dict]:
    """Построить корпус для RAG из полных текстов."""
    conn = await asyncpg.connect(...)
    
    # Получаем все processed documents для канала
    rows = await conn.fetch("""
        SELECT 
            source_ref,
            text_clean,
            summary,
            topics_json,
            channel_id
        FROM processed_documents
        WHERE channel_id = $1
    """, channel_id)
    
    corpus = []
    for row in rows:
        corpus.append({
            'id': row['source_ref'],
            'text': row['text_clean'],      # Полный текст для embedding
            'summary': row['summary'],       # Для preview
            'topics': json.loads(row['topics_json'] or '[]'),
            'telegram_url': f"https://t.me/{channel_id}/{row['source_ref'].split(':')[-1]}"
        })
    
    await conn.close()
    return corpus
```

### 5. SQL-запросы для RAG

```sql
-- Получить все тексты канала
SELECT source_ref, text_clean, summary, topics_json
FROM processed_documents
WHERE channel_id = 'BiocodebySechenov';

-- Найти сообщения по теме
SELECT source_ref, text_clean
FROM processed_documents
WHERE topics_json::jsonb @> '["здоровье"]';

-- Получить оригинальный текст
SELECT source_ref, text, date
FROM raw_messages
WHERE source_ref = 'tg:BiocodebySechenov:post:153';

-- Получить все anchor сообщения для темы
SELECT p.source_ref, p.text_clean, p.summary
FROM processed_documents p
JOIN topic_cards tc ON tc.anchors_json::jsonb @> jsonb_build_array(
    jsonb_build_object('anchor_ref', p.source_ref)
)
WHERE tc.id = 'topic:tg:BiocodebySechenov:post:153';
```

---

## FAQ

### Q: Где хранятся полные тексты сообщений?

**A:** В PostgreSQL:
- `raw_messages.text` — оригинальный текст из Telegram
- `processed_documents.text_clean` — очищенный текст (рекомендуется для RAG)

### Q: Что содержит `content` в kb_entries.ndjson?

**A:** Полный текст: `summary + "\n\n" + text_clean`. Это **полный очищенный текст** сообщения с резюме в начале. Поле `content` подходит для RAG embeddings напрямую.

### Q: Как связаны выходные файлы с БД?

**A:** Через поле `source_ref` (формат: `tg:<channel>:<type>:<id>`). Это Primary Key в таблицах `raw_messages` и `processed_documents`.

### Q: Нужен ли Telegram API после обработки?

**A:** Нет. Все данные сохраняются локально в PostgreSQL. Telegram API нужен только для получения новых сообщений.

### Q: Какой текст использовать для RAG embeddings?

**A:** Два варианта:
1. **`kb_entries.ndjson` → `content`** — готовый текст (summary + text_clean), можно использовать напрямую
2. **`processed_documents.text_clean`** — только очищенный текст без summary

Рекомендуется использовать `content` из kb_entries — он уже содержит полный текст.

### Q: Как получить ссылку на оригинал в Telegram?

**A:** 
- Из `kb_entries.ndjson`: `metadata.telegram_url`
- Из `topic_*.json`: `resolved_sources[].telegram_url`
- Вручную: `https://t.me/<channel_id>/<message_id>`

---

## См. также

- [OUTPUT_FORMATS.md](../OUTPUT_FORMATS.md) — детали форматов файлов
- [DATA_FLOW.md](DATA_FLOW.md) — поток данных через pipeline
- [USER_GUIDE.md](USER_GUIDE.md) — руководство пользователя
- [docs/contracts/](contracts/) — JSON Schema контракты

---

**Версия документа:** 1.0  
**Дата создания:** 31 декабря 2025

