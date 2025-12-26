# 📄 Форматы выходных файлов

Подробное описание форматов файлов, создаваемых TG_parser при экспорте данных.

---

## 📦 Обзор выходных файлов

После выполнения команды `export` или `run` создаётся директория с файлами:

```
output/
├── kb_entries.ndjson          # Knowledge Base entries (NDJSON)
├── topics.json                # Каталог тем (JSON)
└── topic_<id>.json (N файлов) # Детальные карточки тем (JSON)
```

---

## 1️⃣ `kb_entries.ndjson`

### Описание

- **Формат**: NDJSON (Newline-Delimited JSON)
- **Назначение**: Основной файл с записями базы знаний для RAG-систем
- **Структура**: Одна JSON-запись на строку
- **Кодировка**: UTF-8

### Преимущества NDJSON

✅ Потоковая обработка (можно читать построчно)  
✅ Легко парсить большие файлы  
✅ Стандарт для векторных баз данных  
✅ Совместим с ElasticSearch, MongoDB, и др.

### Схема данных

Каждая строка — это объект `KnowledgeBaseEntry`:

```typescript
{
  id: string;           // Уникальный ID: "kb:msg:tg:<channel>:<type>:<msg_id>"
  source: {             // Информация об источнике
    type: string;       // "telegram_message" или "topic"
    channel_id: string;
    message_id: string;
    message_type: "post" | "comment";
    source_ref: string; // Каноническая ссылка
    topic_id?: string;  // Для topic entries
  };
  created_at: string;   // ISO 8601 datetime
  title: string;        // Заголовок записи
  content: string;      // Основной контент (summary)
  topics: string[];     // Темы/категории
  tags: string[];       // Теги
  vector?: number[];    // Опционально: embedding
  metadata?: object;    // Дополнительные данные
}
```

### Пример записи (message entry)

```json
{"id":"kb:msg:tg:labdiagnostica_logical:post:955","source":{"type":"telegram_message","channel_id":"labdiagnostica_logical","message_id":"955","message_type":"post","source_ref":"tg:labdiagnostica_logical:post:955","topic_id":null},"created_at":"2025-12-25T06:03:43","title":"Message 955","content":"The message refers to a continuation of the topic of prenatal diagnostics, specifically NIPT.\n\nПродолжение темы пренатальной диагностики НИПТ","topics":["пренатальная диагностика","НИПТ"],"tags":[],"vector":null,"metadata":{"processing":{"model_id":"gpt-4o-mini","parameters":{"max_tokens":4096,"temperature":0.0},"pipeline_version":"processing:v1.0.0","prompt_id":"sha256:9ce699f16f0e947c","prompt_name":"processing_v1"},"telegram_url":"https://t.me/labdiagnostica_logical/955"}}
```

### Пример записи (topic entry)

```json
{"id":"kb:topic:topic:tg:channel:post:123","source":{"type":"topic","topic_id":"topic:tg:channel:post:123"},"created_at":"2025-12-25T10:00:00Z","title":"Пренатальная диагностика и НИПТ","content":"Тема объединяет сообщения о неинвазивном пренатальном тестировании.\n\n**Scope In:** НИПТ методы, пренатальная диагностика, скрининг\n**Scope Out:** Постнатальная диагностика","topics":["topic:tg:channel:post:123"],"tags":["медицина","диагностика","НИПТ"]}
```

### Использование

**Python:**
```python
import json

# Чтение всех записей
entries = []
with open('kb_entries.ndjson', 'r', encoding='utf-8') as f:
    for line in f:
        entry = json.loads(line)
        entries.append(entry)

# Потоковая обработка (для больших файлов)
with open('kb_entries.ndjson', 'r', encoding='utf-8') as f:
    for line in f:
        entry = json.loads(line)
        # Обработка каждой записи
        print(entry['title'])
```

**JavaScript/Node.js:**
```javascript
const fs = require('fs');
const readline = require('readline');

const stream = fs.createReadStream('kb_entries.ndjson');
const rl = readline.createInterface({ input: stream });

rl.on('line', (line) => {
  const entry = JSON.parse(line);
  console.log(entry.title);
});
```

**jq (командная строка):**
```bash
# Извлечь все заголовки
jq -r '.title' kb_entries.ndjson

# Фильтровать по топику
jq 'select(.topics[] | contains("НИПТ"))' kb_entries.ndjson

# Подсчитать записи
wc -l kb_entries.ndjson
```

---

## 2️⃣ `topics.json`

### Описание

- **Формат**: JSON (массив)
- **Назначение**: Каталог всех тем по каналу
- **Структура**: Массив объектов `TopicCard`

### Схема данных

```typescript
[
  {
    id: string;              // Уникальный ID темы
    title: string;           // Название темы
    summary: string;         // Краткое описание
    scope_in: string[];      // Что включено в тему
    scope_out: string[];     // Что исключено из темы
    anchor_count: number;    // Количество якорных сообщений
    anchors: Array<{         // Якорные сообщения
      anchor_ref: string;
      channel_id: string;
      message_id: string;
      message_type: "post" | "comment";
      score: number;
      parent_message_id?: string;
      thread_id?: string;
    }>;
    type: "cluster" | "singleton";
    metadata: {              // Метаданные обработки
      model_id: string;
      algorithm: string;
      pipeline_version: string;
      // ...
    };
    created_at: string;      // ISO 8601
    updated_at: string;      // ISO 8601
  },
  // ... другие темы
]
```

### Пример файла

```json
[
  {
    "id": "topic:tg:labdiagnostica_logical:post:956",
    "title": "Пренатальная диагностика и НИПТ",
    "summary": "Тема объединяет сообщения о неинвазивном пренатальном тестировании (НИПТ), его методологии, ограничениях и клиническом применении.",
    "scope_in": [
      "НИПТ методы и технологии",
      "Пренатальная диагностика",
      "Скрининг плода"
    ],
    "scope_out": [
      "Постнатальная диагностика",
      "Инвазивные методы диагностики"
    ],
    "anchor_count": 3,
    "anchors": [
      {
        "anchor_ref": "tg:labdiagnostica_logical:post:956",
        "channel_id": "labdiagnostica_logical",
        "message_id": "956",
        "message_type": "post",
        "score": 0.9,
        "parent_message_id": null,
        "thread_id": null
      },
      {
        "anchor_ref": "tg:labdiagnostica_logical:post:957",
        "channel_id": "labdiagnostica_logical",
        "message_id": "957",
        "message_type": "post",
        "score": 0.8,
        "parent_message_id": null,
        "thread_id": null
      }
    ],
    "type": "cluster",
    "metadata": {
      "model_id": "gpt-4o-mini",
      "algorithm": "llm_clustering",
      "pipeline_version": "topicization:v1.0.0",
      "input_scope": {
        "channel_id": "labdiagnostica_logical",
        "mode": "full_history"
      }
    },
    "created_at": "2025-12-25T06:08:14",
    "updated_at": "2025-12-25T06:08:14"
  }
]
```

### Использование

**Python:**
```python
import json

# Чтение каталога тем
with open('topics.json', 'r', encoding='utf-8') as f:
    topics = json.load(f)

# Вывести все названия тем
for topic in topics:
    print(f"{topic['id']}: {topic['title']}")
    print(f"  Якорей: {topic['anchor_count']}")
    print(f"  Scope In: {', '.join(topic['scope_in'][:3])}")
    print()

# Найти темы по ключевому слову
medical_topics = [t for t in topics if 'медицина' in t['title'].lower()]
```

**JavaScript:**
```javascript
const fs = require('fs');
const topics = JSON.parse(fs.readFileSync('topics.json', 'utf-8'));

// Сортировать по количеству якорей
topics.sort((a, b) => b.anchor_count - a.anchor_count);

// Топ-5 тем
topics.slice(0, 5).forEach(topic => {
  console.log(`${topic.title} (${topic.anchor_count} anchors)`);
});
```

---

## 3️⃣ `topic_<id>.json`

### Описание

- **Формат**: JSON (объект)
- **Назначение**: Детальная карточка одной темы
- **Количество**: По файлу на каждую тему
- **Имя файла**: `topic_<topic_id с заменой ':' на '_'>.json`

### Схема данных

```typescript
{
  topic_card: TopicCard;        // Полная информация о теме
  topic_bundle: {               // Подборка связанных сообщений
    id: string;
    topic_id: string;
    items: Array<{              // Список документов в подборке
      doc_id: string;
      role: "anchor" | "supporting";
      score: number;
      justification?: string;
    }>;
    created_at: string;
    updated_at: string;
  };
  resolved_sources: Array<{     // Детали источников с URL
    source_ref: string;
    channel_id: string;
    message_id: string;
    message_type: string;
    role: string;
    score: number;
    telegram_url: string;       // Ссылка на сообщение в Telegram
    justification?: string;
  }>;
  exported_at: string;          // ISO 8601
  export_version: string;       // Версия формата export
}
```

### Пример файла

```json
{
  "topic_card": {
    "id": "topic:tg:labdiagnostica_logical:post:956",
    "title": "Пренатальная диагностика и НИПТ",
    "summary": "Тема объединяет сообщения о неинвазивном пренатальном тестировании...",
    "scope_in": ["НИПТ методы", "Пренатальная диагностика"],
    "scope_out": ["Постнатальная диагностика"],
    "anchor_count": 3,
    "anchors": [/* ... */],
    "type": "cluster",
    "metadata": {/* ... */},
    "created_at": "2025-12-25T06:08:14",
    "updated_at": "2025-12-25T06:08:14"
  },
  "topic_bundle": {
    "id": "bundle:topic:tg:labdiagnostica_logical:post:956",
    "topic_id": "topic:tg:labdiagnostica_logical:post:956",
    "items": [
      {
        "doc_id": "proc_doc:tg:labdiagnostica_logical:post:956",
        "role": "anchor",
        "score": 0.9,
        "justification": null
      },
      {
        "doc_id": "proc_doc:tg:labdiagnostica_logical:post:982",
        "role": "supporting",
        "score": 0.8,
        "justification": "Курс по лабораторной медицине акцентирует внимание на интерпретации тестов, что связано с НИПТ."
      }
    ],
    "created_at": "2025-12-25T06:08:14",
    "updated_at": "2025-12-25T06:08:14"
  },
  "resolved_sources": [
    {
      "source_ref": "tg:labdiagnostica_logical:post:956",
      "channel_id": "labdiagnostica_logical",
      "message_id": "956",
      "message_type": "post",
      "role": "anchor",
      "score": 0.9,
      "telegram_url": "https://t.me/labdiagnostica_logical/956"
    },
    {
      "source_ref": "tg:labdiagnostica_logical:post:982",
      "channel_id": "labdiagnostica_logical",
      "message_id": "982",
      "message_type": "post",
      "role": "supporting",
      "score": 0.8,
      "telegram_url": "https://t.me/labdiagnostica_logical/982",
      "justification": "Курс по лабораторной медицине акцентирует внимание на интерпретации тестов..."
    }
  ],
  "exported_at": "2025-12-25T06:09:01Z",
  "export_version": "export:v1.0.0"
}
```

### Использование

**Python:**
```python
import json
import glob

# Чтение всех детальных карточек тем
for filepath in glob.glob('topic_*.json'):
    with open(filepath, 'r', encoding='utf-8') as f:
        topic_detail = json.load(f)
    
    print(f"Тема: {topic_detail['topic_card']['title']}")
    print(f"Сообщений в подборке: {len(topic_detail['topic_bundle']['items'])}")
    print(f"Ссылки на источники:")
    for source in topic_detail['resolved_sources'][:3]:
        print(f"  - {source['telegram_url']}")
    print()
```

---

## 📊 Сравнение форматов

| Характеристика | kb_entries.ndjson | topics.json | topic_*.json |
|----------------|-------------------|-------------|--------------|
| **Формат** | NDJSON | JSON | JSON |
| **Размер** | Большой (все записи) | Средний | Маленький (1 тема) |
| **Назначение** | RAG/Vector DB | Каталог тем | Детали темы |
| **Потоковое чтение** | ✅ Да | ❌ Нет | ❌ Нет |
| **Количество файлов** | 1 | 1 | N (по теме) |
| **Telegram URLs** | ✅ В metadata | ❌ Только refs | ✅ Полные URLs |

---

## 🔗 Интеграция с популярными системами

### ElasticSearch

```bash
# Импорт в ElasticSearch
curl -X POST "localhost:9200/knowledge_base/_bulk" \
  -H 'Content-Type: application/x-ndjson' \
  --data-binary @kb_entries.ndjson
```

### MongoDB

```javascript
const fs = require('fs');
const { MongoClient } = require('mongodb');

async function importToMongo() {
  const client = new MongoClient('mongodb://localhost:27017');
  await client.connect();
  const db = client.db('telegram_kb');
  const collection = db.collection('entries');
  
  const entries = fs.readFileSync('kb_entries.ndjson', 'utf-8')
    .split('\n')
    .filter(line => line.trim())
    .map(line => JSON.parse(line));
  
  await collection.insertMany(entries);
  await client.close();
}
```

### Pinecone / Weaviate / Qdrant

```python
import json
from openai import OpenAI
import pinecone

# Генерация embeddings и загрузка в Pinecone
client = OpenAI()
pinecone.init(api_key="your-api-key")
index = pinecone.Index("telegram-kb")

with open('kb_entries.ndjson', 'r') as f:
    for line in f:
        entry = json.loads(line)
        
        # Генерация embedding
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=entry['content']
        )
        embedding = response.data[0].embedding
        
        # Загрузка в Pinecone
        index.upsert([(
            entry['id'],
            embedding,
            {
                'title': entry['title'],
                'content': entry['content'],
                'topics': entry['topics'],
                'channel_id': entry['source']['channel_id']
            }
        )])
```

---

## 🛠️ JSON Schema контракты

Полные JSON Schema определения доступны в:

- [`docs/contracts/knowledge_base_entry.schema.json`](docs/contracts/knowledge_base_entry.schema.json)
- [`docs/contracts/topic_card.schema.json`](docs/contracts/topic_card.schema.json)
- [`docs/contracts/topic_bundle.schema.json`](docs/contracts/topic_bundle.schema.json)

### Валидация данных

**Python (jsonschema):**
```python
import json
import jsonschema

# Загрузить схему
with open('docs/contracts/knowledge_base_entry.schema.json') as f:
    schema = json.load(f)

# Валидировать запись
with open('kb_entries.ndjson') as f:
    for line in f:
        entry = json.loads(line)
        try:
            jsonschema.validate(instance=entry, schema=schema)
        except jsonschema.ValidationError as e:
            print(f"Ошибка валидации: {e.message}")
```

---

## 🔍 Детали реализации

### Telegram URL Resolution

Система автоматически создаёт ссылки на сообщения в Telegram:

1. **С username канала**: `https://t.me/<username>/<message_id>`
2. **С channel_id (-100...)**: `https://t.me/c/<internal_id>/<message_id>`
3. **Username формат**: `https://t.me/<channel_id>/<message_id>`
4. **Иначе**: `telegram_url = null`

### Сортировка и детерминизм

Все выходные файлы имеют **детерминированный порядок**:

- `kb_entries.ndjson`: сортировка по `id`
- `topics.json`: сортировка по `id`
- `topic_bundle.items`: сортировка по `score` (убыв.) + `doc_id`

Это гарантирует **воспроизводимость** результатов.

### Версионирование

Каждый файл содержит информацию о версии:
- `metadata.pipeline_version` в KB entries
- `export_version` в topic detail files

Это позволяет отслеживать изменения формата при обновлениях.

---

## 🎯 Best Practices

### 1. Потоковая обработка больших файлов

```python
# ❌ Плохо: загружает весь файл в память
with open('kb_entries.ndjson') as f:
    data = [json.loads(line) for line in f]

# ✅ Хорошо: построчная обработка
with open('kb_entries.ndjson') as f:
    for line in f:
        entry = json.loads(line)
        process(entry)  # Обработка по одной записи
```

### 2. Фильтрация на уровне чтения

```python
# Фильтровать при чтении, а не после
def load_entries_by_topic(filepath, topic_filter):
    with open(filepath) as f:
        for line in f:
            entry = json.loads(line)
            if topic_filter in entry['topics']:
                yield entry
```

### 3. Использование индексов

```python
# Создать индекс по ID для быстрого поиска
entries_index = {}
with open('kb_entries.ndjson') as f:
    for line in f:
        entry = json.loads(line)
        entries_index[entry['id']] = entry

# Быстрый поиск по ID
entry = entries_index.get('kb:msg:tg:channel:post:123')
```

---

## 📚 См. также

- [README.md](README.md) — основная документация
- [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) — полное оглавление документации
- [DATA_FLOW.md](docs/DATA_FLOW.md) — детали потока данных
- [USER_GUIDE.md](docs/USER_GUIDE.md) — руководство пользователя
- [MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md) — работа с несколькими каналами
- [REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md) — примеры реальных данных
- [docs/contracts/](docs/contracts/) — JSON Schema контракты

---

**Версия документа**: 1.0  
**Последнее обновление**: 26 декабря 2025
