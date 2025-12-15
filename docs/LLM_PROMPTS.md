# TG_parser — LLM Prompts

Документация всех промптов для взаимодействия с LLM.

## Содержание

1. [Processing Prompts](#processing-prompts)
2. [Topicization Prompts](#topicization-prompts)
3. [Supporting Items Prompts](#supporting-items-prompts)
4. [Мультиязычность](#мультиязычность)
5. [Механизм применения](#механизм-применения)

---

## Processing Prompts

Промпты для этапа обработки сообщений (Stage II: Processing).

### PROCESSING_SYSTEM_PROMPT

**Назначение:** Системный промпт для извлечения структурированной информации из Telegram-сообщений.

**Полный текст:**

```
You are a text processing assistant that extracts structured information from Telegram messages.

Your task is to analyze the message and extract:
1. text_clean: cleaned and normalized text (remove noise, fix formatting)
2. summary: brief summary (1-2 sentences) - can be null if not meaningful
3. topics: list of relevant topics/categories
4. entities: list of named entities (person, organization, location, etc.)
5. language: detected language code (ISO 639-1: ru, en, etc.)

Output MUST be valid JSON matching this structure:
{
  "text_clean": "string (required)",
  "summary": "string or null (optional)",
  "topics": ["string", ...],
  "entities": [{"type": "string", "value": "string", "confidence": 0.0-1.0}, ...],
  "language": "string"
}

Important:
- text_clean is REQUIRED and should be the cleaned version of the original text
- summary can be null if the message is too short or not meaningful
- topics can be empty list if no clear topics
- entities should include confidence scores (0.0-1.0)
- language should be ISO 639-1 code (ru, en, de, etc.)
```

### PROCESSING_USER_PROMPT_TEMPLATE

**Назначение:** Шаблон user-промпта с текстом сообщения.

**Полный текст:**

```
Process this Telegram message:

---
{text}
---

Extract structured information as JSON.
```

**Переменные:**
- `{text}` — текст сообщения из `RawTelegramMessage.text`

### Параметры LLM

| Параметр | Значение | Описание |
|----------|----------|----------|
| `temperature` | `0.0` | Детерминизм ответов (TR-38) |
| `max_tokens` | `4096` | Максимум токенов ответа |
| `response_format` | `{"type": "json_object"}` | Гарантия JSON ответа |

### Формат ответа (JSON Schema)

```json
{
  "type": "object",
  "required": ["text_clean", "language"],
  "properties": {
    "text_clean": {
      "type": "string",
      "description": "Очищенный и нормализованный текст"
    },
    "summary": {
      "type": ["string", "null"],
      "description": "Краткое резюме (1-2 предложения)"
    },
    "topics": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Список тем/категорий"
    },
    "entities": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "value"],
        "properties": {
          "type": { "type": "string" },
          "value": { "type": "string" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      },
      "description": "Извлечённые сущности"
    },
    "language": {
      "type": "string",
      "description": "ISO 639-1 код языка (ru, en, de, ...)"
    }
  }
}
```

### Примеры

**Вход:**
```
Process this Telegram message:

---
🚀 Выпустили новую версию Claude 3.5 Sonnet!

Anthropic представила обновлённую модель с улучшенной производительностью:
- Быстрее на 30%
- Лучше работает с кодом
- Расширен контекст до 200K токенов

Подробности: anthropic.com/news
---

Extract structured information as JSON.
```

**Выход:**
```json
{
  "text_clean": "Выпустили новую версию Claude 3.5 Sonnet!\n\nAnthropic представила обновлённую модель с улучшенной производительностью:\n- Быстрее на 30%\n- Лучше работает с кодом\n- Расширен контекст до 200K токенов\n\nПодробности: anthropic.com/news",
  "summary": "Anthropic выпустила обновлённую версию Claude 3.5 Sonnet с улучшениями в скорости, работе с кодом и увеличенным контекстом.",
  "topics": ["AI", "LLM", "Anthropic", "Claude", "новости технологий"],
  "entities": [
    {"type": "organization", "value": "Anthropic", "confidence": 0.95},
    {"type": "product", "value": "Claude 3.5 Sonnet", "confidence": 0.98},
    {"type": "url", "value": "anthropic.com/news", "confidence": 1.0}
  ],
  "language": "ru"
}
```

---

## Topicization Prompts

Промпты для этапа тематизации (Stage II: Topicization).

### TOPICIZATION_SYSTEM_PROMPT

**Назначение:** Системный промпт для идентификации и кластеризации сообщений в темы.

**Полный текст:**

```
You are a topic analysis assistant that identifies and clusters messages into coherent topics.

Your task is to analyze a collection of messages and identify distinct topics. For each topic, you should:

1. Determine if it's a SINGLETON (one comprehensive anchor message) or CLUSTER (multiple related messages)
2. Identify anchor messages (the most representative messages for the topic)
3. Assign relevance scores (0.0-1.0) to each anchor
4. Create a descriptive title and summary
5. Define scope_in (what belongs to the topic) and scope_out (what doesn't)

IMPORTANT: Generate title, summary, scope_in, scope_out, and tags in the SAME LANGUAGE as the source messages.
Detect the dominant language of the input content and use it for all output fields. This applies to any language.

Output MUST be valid JSON matching this structure:
{
  "topics": [
    {
      "type": "singleton" or "cluster",
      "anchors": [
        {
          "source_ref": "tg:channel_id:post:message_id",
          "score": 0.0-1.0
        }
      ],
      "title": "Topic title",
      "summary": "Brief 1-3 sentence description",
      "scope_in": ["aspect 1", "aspect 2", ...],
      "scope_out": ["excluded aspect 1", "excluded aspect 2", ...],
      "tags": ["tag1", "tag2", ...] // optional
    }
  ]
}

Quality criteria:
- SINGLETON: requires score >= 0.75 and text length >= 300 characters
- CLUSTER: requires minimum 2 anchors with score >= 0.6
- Anchors should be deduplicated by source_ref
- Each topic must have clear boundaries (scope_in/scope_out)

Important:
- Be conservative: only create topics with clear coherence
- Assign meaningful scores based on message centrality to the topic
- Ensure anchor source_refs exactly match the provided message references
```

### TOPICIZATION_USER_PROMPT_TEMPLATE

**Назначение:** Шаблон user-промпта со списком сообщений для тематизации.

**Полный текст:**

```
Analyze these messages and identify distinct topics:

{messages_text}

For each topic, identify:
1. Type (singleton for comprehensive single message, cluster for related group)
2. Anchor messages with relevance scores
3. Descriptive title and summary
4. Clear scope boundaries (what's in/out)

Return structured JSON.
```

**Переменные:**
- `{messages_text}` — форматированный список сообщений

**Формат `{messages_text}`:**
```
Message 1:
Reference: tg:@channel:post:123
Text: <первые 500 символов text_clean>...
Summary: <summary или "N/A">
Topics: <topics через запятую или "N/A">
---
Message 2:
...
```

### Критерии качества тем (TR-35)

**Singleton (тема-статья):**
- Один якорный материал, который является полноценной статьёй/постом
- `score >= 0.75` — высокая релевантность
- `text_clean.length >= 300` символов — достаточный объём

**Cluster (тема-кластер):**
- Несколько связанных материалов, объединённых общей темой
- `>= 2` якорей обязательно
- `score >= 0.6` для всех якорей
- Top-N якорей (N=3) после сортировки

### Формат ответа (JSON Schema)

```json
{
  "type": "object",
  "required": ["topics"],
  "properties": {
    "topics": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "anchors", "title", "summary", "scope_in", "scope_out"],
        "properties": {
          "type": {
            "type": "string",
            "enum": ["singleton", "cluster"]
          },
          "anchors": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "object",
              "required": ["source_ref", "score"],
              "properties": {
                "source_ref": { "type": "string" },
                "score": { "type": "number", "minimum": 0, "maximum": 1 }
              }
            }
          },
          "title": { "type": "string" },
          "summary": { "type": "string" },
          "scope_in": {
            "type": "array",
            "items": { "type": "string" },
            "minItems": 1
          },
          "scope_out": {
            "type": "array",
            "items": { "type": "string" },
            "minItems": 1
          },
          "tags": {
            "type": "array",
            "items": { "type": "string" }
          }
        }
      }
    }
  }
}
```

### Пример

**Вход (фрагмент):**
```
Analyze these messages and identify distinct topics:

Message 1:
Reference: tg:@techblog:post:101
Text: Введение в машинное обучение: основные концепции и алгоритмы. ML (Machine Learning) — это подраздел искусственного интеллекта, который позволяет компьютерам учиться на данных...
Summary: Обзор основ машинного обучения и ключевых алгоритмов.
Topics: AI, ML, обучение
---
Message 2:
Reference: tg:@techblog:post:102
Text: GPT-4 vs Claude 3: сравнительный анализ крупнейших языковых моделей. Обе модели демонстрируют впечатляющие результаты...
Summary: Сравнение GPT-4 и Claude 3 по ключевым параметрам.
Topics: AI, LLM, сравнение
---
Message 3:
Reference: tg:@techblog:post:103
Text: Практическое руководство по fine-tuning LLM моделей. Рассмотрим пошаговый процесс дообучения...
Summary: Пошаговое руководство по fine-tuning языковых моделей.
Topics: AI, LLM, fine-tuning
---

For each topic, identify:
1. Type (singleton for comprehensive single message, cluster for related group)
2. Anchor messages with relevance scores
3. Descriptive title and summary
4. Clear scope boundaries (what's in/out)

Return structured JSON.
```

**Выход:**
```json
{
  "topics": [
    {
      "type": "cluster",
      "anchors": [
        {
          "source_ref": "tg:@techblog:post:101",
          "score": 0.85
        },
        {
          "source_ref": "tg:@techblog:post:102",
          "score": 0.78
        },
        {
          "source_ref": "tg:@techblog:post:103",
          "score": 0.72
        }
      ],
      "title": "Искусственный интеллект и языковые модели",
      "summary": "Серия материалов об основах машинного обучения, сравнении крупных языковых моделей и практическом применении LLM.",
      "scope_in": [
        "Машинное обучение",
        "Языковые модели (LLM)",
        "GPT и Claude",
        "Fine-tuning"
      ],
      "scope_out": [
        "Компьютерное зрение",
        "Робототехника",
        "Традиционное программирование"
      ],
      "tags": ["AI", "ML", "LLM", "GPT", "Claude"]
    }
  ]
}
```

---

## Supporting Items Prompts

Промпты для поиска дополнительных материалов по теме.

### SUPPORTING_ITEMS_SYSTEM_PROMPT

**Назначение:** Системный промпт для оценки релевантности сообщений к теме.

**Полный текст:**

```
You are an assistant that evaluates message relevance to a specific topic.

Your task is to review messages and determine which ones support or relate to the given topic. For each relevant message, assign:
1. A relevance score (0.0-1.0)
2. A brief justification explaining why it's relevant

IMPORTANT: Write justifications in the SAME LANGUAGE as the source messages.

Output MUST be valid JSON matching this structure:
{
  "supporting_items": [
    {
      "source_ref": "tg:channel_id:post:message_id",
      "score": 0.5-1.0,
      "justification": "Brief explanation of relevance"
    }
  ]
}

Quality criteria:
- Only include messages with score >= 0.5
- Exclude anchor messages (they're already in the topic)
- Be selective: not every message needs to be included
- Justifications should be concise (1 sentence)

Important:
- Focus on messages that genuinely add value to the topic
- Lower scores (0.5-0.6) for tangentially related content
- Higher scores (0.7-0.9) for directly relevant content
- Ensure source_refs exactly match the provided message references
```

### SUPPORTING_ITEMS_USER_PROMPT_TEMPLATE

**Назначение:** Шаблон user-промпта для поиска supporting items.

**Полный текст:**

```
Topic: {topic_title}

Summary: {topic_summary}

Scope (what's included): {scope_in}

Scope (what's excluded): {scope_out}

Anchor messages (already included):
{anchor_refs}

Evaluate these messages for relevance to the topic:

{messages_text}

Return supporting items with scores and justifications in JSON.
```

**Переменные:**
- `{topic_title}` — название темы из TopicCard
- `{topic_summary}` — описание темы
- `{scope_in}` — что относится к теме (список через `\n- `)
- `{scope_out}` — что не относится (список через `\n- `)
- `{anchor_refs}` — ссылки на якорные сообщения (список через `\n- `)
- `{messages_text}` — форматированный список кандидатов

### Формат ответа (JSON Schema)

```json
{
  "type": "object",
  "required": ["supporting_items"],
  "properties": {
    "supporting_items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["source_ref", "score"],
        "properties": {
          "source_ref": { "type": "string" },
          "score": { "type": "number", "minimum": 0.5, "maximum": 1 },
          "justification": { "type": "string" }
        }
      }
    }
  }
}
```

### Пример

**Вход:**
```
Topic: Искусственный интеллект и языковые модели

Summary: Серия материалов об основах машинного обучения и языковых моделей.

Scope (what's included):
- Машинное обучение
- Языковые модели (LLM)
- GPT и Claude

Scope (what's excluded):
- Компьютерное зрение
- Робототехника

Anchor messages (already included):
- tg:@techblog:post:101
- tg:@techblog:post:102
- tg:@techblog:post:103

Evaluate these messages for relevance to the topic:

Message 4:
Reference: tg:@techblog:post:104
Text: Советы по оптимизации промптов для ChatGPT...
Summary: Практические советы по prompt engineering.
---
Message 5:
Reference: tg:@techblog:post:105
Text: Обзор новинок в мире смартфонов: iPhone 16 и Samsung Galaxy...
Summary: Обзор новых смартфонов.
---

Return supporting items with scores and justifications in JSON.
```

**Выход:**
```json
{
  "supporting_items": [
    {
      "source_ref": "tg:@techblog:post:104",
      "score": 0.72,
      "justification": "Прямо связан с практическим использованием LLM через prompt engineering."
    }
  ]
}
```

> **Примечание:** Сообщение 105 о смартфонах не включено, так как не относится к теме AI/LLM.

---

## Мультиязычность

### Определение языка контента

LLM автоматически определяет доминирующий язык входных данных и генерирует ответ на этом языке.

**Инструкция в промптах:**
```
IMPORTANT: Generate title, summary, scope_in, scope_out, and tags in the SAME LANGUAGE as the source messages.
Detect the dominant language of the input content and use it for all output fields. This applies to any language.
```

### Поддерживаемые языки

Система поддерживает любые языки, которые понимает используемая LLM модель:
- Русский (ru)
- Английский (en)
- Немецкий (de)
- Французский (fr)
- И другие

### Примеры многоязычного вывода

**Русский контент → Русский вывод:**
```json
{
  "title": "Основы машинного обучения",
  "summary": "Обзор ключевых концепций ML и алгоритмов.",
  "scope_in": ["Нейронные сети", "Обучение с учителем"],
  "scope_out": ["Базы данных", "Веб-разработка"]
}
```

**English content → English output:**
```json
{
  "title": "Machine Learning Fundamentals",
  "summary": "Overview of key ML concepts and algorithms.",
  "scope_in": ["Neural networks", "Supervised learning"],
  "scope_out": ["Databases", "Web development"]
}
```

---

## Механизм применения

### Когда вызывается каждый промпт

| Промпт | Этап | Команда CLI | Триггер |
|--------|------|-------------|---------|
| Processing | Processing | `process`, `run` | Для каждого RawTelegramMessage |
| Topicization | Topicization | `topicize`, `run` | Один раз для всех ProcessedDocument канала |
| Supporting Items | Topicization | `topicize`, `run` | Для каждой созданной темы |

### Как формируются параметры

**Processing:**
```python
# tg_parser/processing/pipeline.py

user_prompt = build_processing_prompt(message.text)
# → Подставляет текст сообщения в шаблон

response = await llm_client.generate(
    prompt=user_prompt,
    system_prompt=PROCESSING_SYSTEM_PROMPT,
    temperature=settings.llm_temperature,      # 0.0
    max_tokens=settings.llm_max_tokens,        # 4096
    response_format={"type": "json_object"},
)
```

**Topicization:**
```python
# tg_parser/processing/topicization.py

candidates = [
    {
        "source_ref": doc.source_ref,
        "text_clean": doc.text_clean,
        "summary": doc.summary,
        "topics": doc.topics or [],
    }
    for doc in documents
]

prompt = build_topicization_prompt(candidates)
# → Форматирует список сообщений в текст

response = await llm_client.generate(
    prompt=prompt,
    system_prompt=TOPICIZATION_SYSTEM_PROMPT,
    temperature=0.0,
    response_format={"type": "json_object"},
)
```

**Supporting Items:**
```python
# tg_parser/processing/topicization.py

prompt = build_supporting_items_prompt(
    topic_title=topic_card.title,
    topic_summary=topic_card.summary,
    scope_in=topic_card.scope_in,
    scope_out=topic_card.scope_out,
    anchor_refs=anchor_refs,
    messages=candidate_docs,
)

response = await llm_client.generate(
    prompt=prompt,
    system_prompt=SUPPORTING_ITEMS_SYSTEM_PROMPT,
    temperature=0.0,
    response_format={"type": "json_object"},
)
```

### Как парсится ответ

**Общий паттерн:**
```python
import json

# 1. Получить текст ответа от LLM
response_text = await llm_client.generate(...)

# 2. Распарсить JSON
try:
    response_data = json.loads(response_text)
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid JSON response from LLM: {e}")

# 3. Извлечь нужные поля
text_clean = response_data.get("text_clean")
if not text_clean:
    raise ValueError("LLM response missing required field: text_clean")
```

**Processing — извлечение полей:**
```python
text_clean = response_data.get("text_clean")      # обязательно
summary = response_data.get("summary")             # опционально (может быть null)
topics = response_data.get("topics", [])           # default: []
entities = response_data.get("entities", [])       # default: []
language = response_data.get("language")           # опционально
```

**Topicization — извлечение тем:**
```python
raw_topics = response_data.get("topics", [])

for raw_topic in raw_topics:
    topic_type = raw_topic.get("type", "cluster")
    anchors = raw_topic.get("anchors", [])
    title = raw_topic.get("title", "Untitled Topic")
    summary = raw_topic.get("summary", "")
    scope_in = raw_topic.get("scope_in", [])
    scope_out = raw_topic.get("scope_out", [])
    tags = raw_topic.get("tags")
```

### Обработка ошибок

**Ретраи per-message (TR-47):**
```python
# Processing: 3 попытки с экспоненциальным backoff
max_attempts = 3
backoff = [1, 2, 4]  # секунды + jitter 0-30%

for attempt in range(1, max_attempts + 1):
    try:
        processed = await self._process_single_message(message)
        return processed
    except Exception as e:
        if attempt < max_attempts:
            delay = backoff[attempt - 1] + random.uniform(0, delay * 0.3)
            await asyncio.sleep(delay)
        else:
            # Записать в processing_failures
            await self.failure_repo.record_failure(...)
            raise
```

**Типы ошибок:**

| Тип ошибки | Действие | Ретрай |
|------------|----------|--------|
| `JSONDecodeError` | Логировать, ретрай | Да |
| `ValueError` (missing field) | Логировать, ретрай | Да |
| `httpx.HTTPError` (5xx) | Логировать, ретрай | Да |
| `httpx.HTTPError` (401/403) | Прервать | Нет |
| Rate Limit (429) | Backoff, ретрай | Да |

**Запись неудачной обработки:**
```python
# После исчерпания попыток
await self.failure_repo.record_failure(
    source_ref=message.source_ref,
    channel_id=message.channel_id,
    attempts=max_attempts,
    error_class=type(last_error).__name__,
    error_message=str(last_error),
)
```

### Prompt ID для трассируемости (TR-40)

Каждый промпт имеет уникальный идентификатор для воспроизводимости:

```python
# tg_parser/processing/llm/openai_client.py

def compute_prompt_id(
    self,
    system_prompt: str | None,
    user_prompt_template: str,
) -> str:
    """
    Вычислить prompt_id для детерминизма (TR-40).
    Формат: "sha256:<hash>"
    """
    combined = f"{system_prompt or ''}\n---\n{user_prompt_template}"
    hash_obj = hashlib.sha256(combined.encode("utf-8"))
    hash_hex = hash_obj.hexdigest()
    return f"sha256:{hash_hex[:16]}"
```

**Пример prompt_id:** `sha256:a1b2c3d4e5f6g7h8`

### Версионирование промптов

| Промпт | Версия | Имя |
|--------|--------|-----|
| Processing | v1 | `processing_v1` |
| Topicization | v1 | `topicization_v1` |
| Supporting Items | v1 | `supporting_items_v1` |

При изменении промптов необходимо:
1. Увеличить версию в `pipeline_version`
2. Обновить `prompt_name`
3. Пересчитать `prompt_id`

---

## Связанные документы

- [User Guide](USER_GUIDE.md) — руководство пользователя
- [Data Flow](DATA_FLOW.md) — поток данных
- [Architecture](architecture.md) — архитектура системы
- [Pipeline](pipeline.md) — детали pipeline
- [Technical Requirements](technical-requirements.md) — технические требования

