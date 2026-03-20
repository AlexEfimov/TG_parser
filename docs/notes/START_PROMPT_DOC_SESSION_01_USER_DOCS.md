# 📚 Documentation Session 01: User Documentation & Output Formats

**Дата создания:** 30 декабря 2025  
**Тип сессии:** Справочная (Documentation Review)  
**Связанная версия:** v3.1.1

---

## 📋 О справочных сессиях

**Справочные сессии (DOC-XX)** — это сессии, посвящённые изучению документации, форматов данных, и ответам на вопросы пользователей. Они нумеруются отдельно от сессий разработки (Session XX).

| Тип сессии | Формат нумерации | Назначение |
|------------|------------------|------------|
| Development Session | `Session XX` | Разработка, тестирование, новые фичи |
| Documentation Session | `DOC-XX` | Изучение документации, справка, Q&A |

---

## 🎯 Цель сессии DOC-01

Ответы на вопросы пользователей о:
1. Пользовательской документации TG_parser
2. Форматах выходных данных (NDJSON, JSON)
3. Структуре экспортируемых файлов
4. Примерах использования

---

## 📁 Карта документации проекта

### Основная структура

```
TG_parser/
├── README.md                           # Точка входа, Quick Start
├── docs/
│   ├── USER_GUIDE.md                   # 📖 ГЛАВНОЕ: Полное руководство пользователя
│   ├── architecture.md                 # Архитектура системы
│   ├── pipeline.md                     # Детали processing pipeline
│   ├── DATA_FLOW.md                    # Поток данных через систему
│   ├── LLM_PROMPTS.md                  # Документация промптов
│   ├── contracts/                      # JSON Schema контракты
│   │   ├── knowledge_base_entry.json
│   │   ├── topic_card.json
│   │   └── ...
│   └── notes/                          # Session notes и start prompts
│       ├── SESSION25_TEST_REPORT.md    # Отчёт о тестировании
│       └── ...
├── OUTPUT_FORMATS.md                   # 📤 Форматы выходных файлов
├── MULTI_CHANNEL_GUIDE.md              # Работа с несколькими каналами
├── LLM_SETUP_GUIDE.md                  # Настройка LLM провайдеров
├── ENV_VARIABLES_GUIDE.md              # Переменные окружения
├── PRODUCTION_DEPLOYMENT.md            # Production deployment
├── MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md
└── DOCUMENTATION_INDEX.md              # 📚 Полное оглавление
```

---

## 📖 Ключевые документы для изучения

### 1. Пользовательская документация

| Документ | Путь | Описание | Размер |
|----------|------|----------|--------|
| **User Guide** | `docs/USER_GUIDE.md` | Полное руководство пользователя | ~1700 строк |
| **Output Formats** | `OUTPUT_FORMATS.md` | Форматы NDJSON/JSON, примеры | ~650 строк |
| **Multi-Channel** | `MULTI_CHANNEL_GUIDE.md` | Работа с несколькими каналами | ~200 строк |
| **README** | `README.md` | Quick Start, CLI команды | ~840 строк |

### 2. Форматы выходных данных

| Документ | Путь | Описание |
|----------|------|----------|
| **Output Formats** | `OUTPUT_FORMATS.md` | Главный документ по форматам |
| **Data Flow** | `docs/DATA_FLOW.md` | Трансформации данных |
| **Contracts** | `docs/contracts/*.json` | JSON Schema спецификации |

### 3. Примеры данных

| Путь | Описание |
|------|----------|
| `output/session25/durov/` | Экспорт @durov (46 записей) |
| `output/session25/telegram/` | Экспорт @telegram (50 записей) |
| `output/session25/tproger/` | Экспорт @tproger (43 записи) |
| `output/session25/habr_com/` | Экспорт @habr_com (98 записей) |
| `output/BiocodebySechenov/` | Экспорт @BiocodebySechenov (8 записей) |

---

## 📤 Структура выходных файлов

### Экспортируемые файлы

При выполнении `export` создаются:

```
output/<channel>/
├── kb_entries.ndjson      # Knowledge Base entries (NDJSON)
├── topics.json            # Каталог всех тем
└── topic_*.json           # Детальные карточки тем
```

### Формат kb_entries.ndjson

**NDJSON** (Newline Delimited JSON) — каждая строка = один JSON объект:

```json
{"id":"kb:msg:tg:durov:post:414","title":"Message 414","content":"...","topics":["contest","Telegram"],"metadata":{...}}
{"id":"kb:msg:tg:durov:post:415","title":"Message 415","content":"...","topics":["privacy","security"],"metadata":{...}}
```

**Структура записи:**

```json
{
  "id": "kb:msg:tg:<channel>:post:<msg_id>",
  "title": "Message <msg_id>",
  "content": "Очищенный и обработанный текст...",
  "topics": ["тема1", "тема2"],
  "tags": [],
  "source": {
    "type": "telegram_message",
    "source_ref": "tg:<channel>:post:<msg_id>",
    "channel_id": "<channel>",
    "message_id": "<msg_id>",
    "message_type": "post"
  },
  "metadata": {
    "telegram_url": "https://t.me/<channel>/<msg_id>",
    "processing": {
      "model_id": "gpt-4o-mini",
      "pipeline_version": "processing:v1.0.0"
    }
  },
  "created_at": "2025-12-30T15:20:50"
}
```

### Формат topics.json

```json
[
  {
    "id": "topic:tg:<channel>:post:<anchor_msg_id>",
    "title": "Название темы",
    "description": "Описание темы...",
    "anchors": [
      {
        "anchor_ref": "tg:<channel>:post:<msg_id>",
        "score": 0.8
      }
    ],
    "metadata": {
      "algorithm": "llm_clustering",
      "model_id": "gpt-4o-mini"
    }
  }
]
```

---

## 🔍 Как отвечать на вопросы

### Типичные вопросы пользователей

1. **"Как экспортировать данные?"**
   → См. `docs/USER_GUIDE.md` → секция "export"
   → Команда: `python -m tg_parser.cli export --channel <channel> --out ./output`

2. **"Какой формат у kb_entries.ndjson?"**
   → См. `OUTPUT_FORMATS.md` → секция "NDJSON Format"
   → Пример в `output/session25/durov/kb_entries.ndjson`

3. **"Как интегрировать с RAG системой?"**
   → См. `OUTPUT_FORMATS.md` → секция "Integration Examples"
   → Примеры для ElasticSearch, Pinecone, MongoDB

4. **"Какие темы были найдены?"**
   → Смотри `topics.json` в директории экспорта
   → Пример: `output/session25/habr_com/topics.json`

5. **"Как работать с несколькими каналами?"**
   → См. `MULTI_CHANNEL_GUIDE.md`
   → Используй разные `--out` директории

### Где искать информацию

| Тема | Документ | Секция |
|------|----------|--------|
| CLI команды | `README.md` | "📖 CLI команды" |
| Экспорт | `docs/USER_GUIDE.md` | "export — Экспорт артефактов" |
| Форматы файлов | `OUTPUT_FORMATS.md` | "Output Files" |
| Схемы данных | `docs/contracts/` | JSON Schema файлы |
| Примеры | `output/session25/` | Реальные экспортированные данные |

---

## 📊 Актуальное состояние проекта

**Версия:** v3.1.1 — Production Tested  
**Тестов:** 411 (100% pass)  
**Backend:** PostgreSQL 16 / SQLite

**Протестировано на реальных каналах:**
- @durov (46 постов)
- @telegram (50 постов)
- @tproger (43 поста)
- @habr_com (98 постов)
- @BiocodebySechenov (8 постов)
- @labdiagnostica_logical (846 сообщений, ранее)

**Всего обработано:** 1000+ сообщений с реальных каналов

---

## 📝 Рекомендации для агента

1. **Перед ответом** — прочитай соответствующий документ
2. **Используй примеры** из `output/session25/` для демонстрации
3. **Ссылайся на документацию** при ответах
4. **JSON Schema** — авторитетный источник для структуры данных

---

## 📚 Полезные команды для изучения данных

```bash
# Посмотреть структуру kb_entries
head -1 output/session25/durov/kb_entries.ndjson | python -m json.tool

# Посмотреть все темы канала
cat output/session25/habr_com/topics.json | python -m json.tool

# Подсчитать записи
wc -l output/session25/*/kb_entries.ndjson

# Найти конкретную тему
grep -l "тема" output/session25/*/topics.json
```

---

## 🔗 Связанные документы

- [DOCUMENTATION_INDEX.md](../../DOCUMENTATION_INDEX.md) — полное оглавление
- [OUTPUT_FORMATS.md](../../OUTPUT_FORMATS.md) — форматы выходных файлов
- [docs/USER_GUIDE.md](../USER_GUIDE.md) — руководство пользователя
- [docs/DATA_ARCHITECTURE.md](../DATA_ARCHITECTURE.md) — архитектура данных ⭐ NEW
- [SESSION25_TEST_REPORT.md](SESSION25_TEST_REPORT.md) — результаты тестирования

---

## 📝 Результаты сессии DOC-01 ✅ COMPLETE

**Дата завершения:** 31 декабря 2025

**Создан новый документ:**
- **[docs/DATA_ARCHITECTURE.md](../DATA_ARCHITECTURE.md)** ⭐ (~790 строк) — полное описание архитектуры данных:
  - 📊 **Структура таблиц PostgreSQL** — sources, raw_messages, processed_documents, topic_cards, topic_bundles, api_jobs, agent_*
  - 📤 **Формат выходных файлов** — kb_entries.ndjson, topics.json, topic_*.json с полным описанием всех полей
  - 🔗 **Связи между данными** — диаграмма связей через `source_ref`
  - 💡 **Примеры использования** — 5 практических примеров (RAG из NDJSON, SQL-запросы, Python код)
  - ❓ **FAQ** — ответы на частые вопросы о работе с данными

**Обновлённая документация:**
- ✅ [README.md](../../README.md) — добавлена ссылка в секцию "Углублённое изучение"
- ✅ [DOCUMENTATION_INDEX.md](../../DOCUMENTATION_INDEX.md) — добавлена запись в "Недавно добавлено", обновлены счётчики
- ✅ [docs/USER_GUIDE.md](../USER_GUIDE.md) — добавлена ссылка в секцию "Architecture"

**Ключевые выводы сессии:**
1. `source_ref` — универсальный ключ связи между всеми слоями данных
2. `content` в kb_entries.ndjson содержит полный текст (summary + text_clean) — готов для RAG
3. Все данные сохраняются локально в PostgreSQL — Telegram API не нужен после ingestion
4. Пороги topicization настраиваются через ENV переменные

---

## ➡️ Следующая сессия

**[DOC-02: LLM Processing & Prompts](START_PROMPT_DOC_SESSION_02_LLM_PROCESSING.md)**

Темы:
- Промпты processing и topicization
- Настройка LLM провайдеров
- Кастомизация под доменные задачи
- Детерминизм и воспроизводимость

---

**Сессия DOC-01 завершена успешно!** ✅ 📖

