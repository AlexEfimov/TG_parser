# 🤖 Documentation Session 02: LLM Processing & Prompts

**Дата создания:** 31 декабря 2025  
**Тип сессии:** Справочная (Documentation Review)  
**Связанная версия:** v3.1.1  
**Предыдущая сессия:** [DOC-01: User Documentation](START_PROMPT_DOC_SESSION_01_USER_DOCS.md)

---

## 📋 О сессии DOC-02

Эта сессия посвящена детальному изучению:
1. LLM обработки данных в TG_parser
2. Промптов для processing и topicization
3. Возможностей тонкой настройки обработки
4. Кастомизации под специфические домены

---

## 🎯 Цели сессии

- [ ] Разобраться в структуре промптов
- [ ] Понять механизм настройки temperature и детерминизма
- [ ] Изучить возможности кастомизации для доменных задач
- [ ] Понять как добавить новые поля extraction
- [ ] Разобраться в настройке topicization (пороги, score, clustering)

---

## 📁 Источники информации

### 1. Основная документация

| Документ | Путь | Содержание | Строк |
|----------|------|------------|-------|
| **LLM Prompts** ⭐ | `docs/LLM_PROMPTS.md` | Полная документация всех промптов | ~796 |
| **LLM Setup Guide** ⭐ | `LLM_SETUP_GUIDE.md` | Настройка провайдеров (OpenAI, Anthropic, Gemini, Ollama) | ~347 |
| **ENV Variables** | `ENV_VARIABLES_GUIDE.md` | Переменные LLM_*, TOPICIZATION_* | ~300 |
| **Data Architecture** | `docs/DATA_ARCHITECTURE.md` | Связь с output (score, anchors) | ~789 |

### 2. YAML промпты (редактируемые)

| Файл | Путь | Назначение |
|------|------|------------|
| **processing.yaml** ⭐ | `prompts/processing.yaml` | Extraction: text_clean, summary, topics, entities |
| **topicization.yaml** ⭐ | `prompts/topicization.yaml` | Кластеризация в темы, score, anchors |
| **supporting_items.yaml** | `prompts/supporting_items.yaml` | Поиск supporting items для тем |
| **README.md** | `prompts/README.md` | Документация формата YAML промптов |

### 3. Код обработки (Python)

#### Промпты и загрузка

| Файл | Путь | Содержание |
|------|------|------------|
| `prompt_loader.py` | `tg_parser/processing/prompt_loader.py` | Загрузка YAML промптов |
| `prompts.py` | `tg_parser/processing/prompts.py` | Встроенные default промпты |
| `topicization_prompts.py` | `tg_parser/processing/topicization_prompts.py` | Default промпты для topicization |

#### LLM клиенты

| Файл | Путь | Провайдер |
|------|------|-----------|
| `factory.py` | `tg_parser/processing/llm/factory.py` | Фабрика LLM клиентов |
| `openai_client.py` | `tg_parser/processing/llm/openai_client.py` | OpenAI (GPT-4o, GPT-5) |
| `anthropic_client.py` | `tg_parser/processing/llm/anthropic_client.py` | Anthropic Claude |
| `gemini_client.py` | `tg_parser/processing/llm/gemini_client.py` | Google Gemini |
| `ollama_client.py` | `tg_parser/processing/llm/ollama_client.py` | Ollama (локальный) |

#### Pipeline обработки

| Файл | Путь | Содержание |
|------|------|------------|
| `pipeline.py` | `tg_parser/processing/pipeline.py` | Основной processing pipeline |
| `topicization.py` | `tg_parser/processing/topicization.py` | Логика topicization |
| `ports.py` | `tg_parser/processing/ports.py` | Интерфейсы LLM |

### 4. Конфигурация

| Файл | Путь | Содержание |
|------|------|------------|
| `settings.py` | `tg_parser/config/settings.py` | Pydantic Settings, ENV переменные |
| `.env.example` | `env.example` | Примеры переменных |

### 5. Агенты (Multi-Agent v3.0)

| Файл | Путь | Содержание |
|------|------|------------|
| `processing_agent.py` | `tg_parser/agents/processing_agent.py` | ProcessingAgent с LLM |
| `topicization.py` | `tg_parser/agents/specialized/topicization.py` | TopicizationAgent |
| `text_tools.py` | `tg_parser/agents/tools/text_tools.py` | LLM tools |

---

## ⚙️ Переменные окружения для LLM

### Выбор провайдера

```env
# Основной провайдер
LLM_PROVIDER=openai          # openai | anthropic | gemini | ollama

# API ключи (по провайдеру)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
OLLAMA_BASE_URL=http://localhost:11434
```

### Параметры модели

```env
# Модель (optional, defaults работают хорошо)
LLM_MODEL=gpt-4o-mini         # или claude-3-5-sonnet, gemini-2.0-flash, llama3.2

# Temperature (0 для детерминизма, TR-38)
LLM_TEMPERATURE=0

# GPT-5 специфичные
LLM_REASONING_EFFORT=low      # minimal | low | medium | high
LLM_VERBOSITY=low             # low | medium | high
```

### Параметры topicization

```env
# Пороги для topicization
TOPICIZATION_TOP_N_ANCHORS=3            # Макс. anchors на cluster
TOPICIZATION_SINGLETON_MIN_LEN=300      # Мин. длина текста для singleton
TOPICIZATION_SINGLETON_MIN_SCORE=0.75   # Мин. score для singleton
TOPICIZATION_CLUSTER_MIN_ANCHOR_SCORE=0.6  # Мин. score для cluster anchor
TOPICIZATION_SUPPORTING_MIN_SCORE=0.5   # Мин. score для supporting item
```

---

## 📝 Структура YAML промпта

```yaml
metadata:
  version: "1.0.0"
  description: "Description"
  author: "TG_parser team"
  requirements:
    - "TR-38: LLM determinism"

system:
  prompt: |
    System prompt text...
    Defines LLM role and output format.

user:
  template: |
    User message template with {variables}...
  variables:
    - text      # Описание переменной

model:
  temperature: 0        # Детерминизм
  max_tokens: 4096      # Лимит токенов
```

---

## 🔍 Ключевые темы для изучения

### 1. Processing Pipeline

- Как работает extraction (text_clean, summary, topics, entities)?
- Как изменить формат вывода?
- Как добавить новые поля (например, sentiment, keywords)?

### 2. Topicization

- Как LLM определяет score для anchors?
- Что такое singleton vs cluster?
- Как настроить пороги?
- Как изменить критерии качества тем?

### 3. Детерминизм (TR-38)

- Почему temperature=0?
- Как обеспечить воспроизводимость?
- Что такое seed и когда использовать?

### 4. Multi-LLM

- Как переключиться между провайдерами?
- Различия в API (OpenAI vs Claude vs Gemini)?
- GPT-5 vs GPT-4o — когда что использовать?

### 5. Кастомизация

- Как добавить доменные сущности (medical, legal, etc.)?
- Как изменить язык вывода?
- Как добавить контекст (channel_name, date)?

---

## 📖 Рекомендуемый порядок изучения

1. **`prompts/README.md`** — понять структуру YAML
2. **`prompts/processing.yaml`** — изучить processing промпт
3. **`prompts/topicization.yaml`** — изучить topicization промпт
4. **`docs/LLM_PROMPTS.md`** — полная документация
5. **`LLM_SETUP_GUIDE.md`** — настройка провайдеров
6. **`ENV_VARIABLES_GUIDE.md`** — все ENV переменные
7. **`tg_parser/processing/prompt_loader.py`** — механизм загрузки
8. **`tg_parser/processing/pipeline.py`** — как промпты используются

---

## 💡 Практические задачи для сессии

1. **Изменить processing prompt** для добавления sentiment analysis
2. **Настроить topicization** для более строгой кластеризации
3. **Переключиться** с OpenAI на Anthropic Claude
4. **Создать domain-specific prompt** для медицинского контента
5. **Понять scoring** — как LLM определяет relevance score

---

## 🔗 Связанные документы

### Созданные в DOC-01
- [docs/DATA_ARCHITECTURE.md](../DATA_ARCHITECTURE.md) — архитектура данных, поля output

### Технические требования
- [docs/technical-requirements.md](../technical-requirements.md) — TR-21..TR-26 (Processing), TR-38 (Determinism)
- [docs/pipeline.md](../pipeline.md) — детали pipeline

### Session notes
- [SESSION23_SUMMARY.md](../../SESSION23_SUMMARY.md) — GPT-5 support
- [SESSION14_PHASE2B_COMPLETE.md](SESSION14_PHASE2B_COMPLETE.md) — Agents SDK

---

## 📊 Контекст из DOC-01

В сессии DOC-01 мы уже затронули:

1. **`score` в anchors** — LLM определяет по "центральности" сообщения к теме
2. **Пороги topicization** — настраиваются через ENV переменные
3. **`content` в kb_entries** — содержит summary + text_clean

Эти темы можно углубить в DOC-02.

---

## 📝 Шаблон ответов на вопросы

### Вопрос о промптах
→ Смотри `prompts/*.yaml` и `docs/LLM_PROMPTS.md`

### Вопрос о настройке
→ Смотри `ENV_VARIABLES_GUIDE.md` → LLM секция

### Вопрос о провайдерах
→ Смотри `LLM_SETUP_GUIDE.md`

### Вопрос о коде
→ Смотри `tg_parser/processing/` директорию

---

## ✅ Готовность к сессии

Для начала сессии DOC-02:

1. [x] Все источники каталогизированы
2. [x] Ключевые файлы идентифицированы
3. [x] Порядок изучения определён
4. [x] Практические задачи сформулированы

---

**Удачной справочной сессии!** 🤖📖


