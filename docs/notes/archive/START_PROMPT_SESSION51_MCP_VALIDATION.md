# Session 51: P6b-validation — Глубокая валидация MCP + подключение новых каналов

**Дата:** [дата запуска]
**Тип сессии:** Планирование + Execution — Валидация MCP Server, подключение каналов
**Предыдущая сессия:** Session 50 (P6b MCP Server)
**Roadmap:** `docs/notes/SESSION48_ROADMAP_V2.md` → Phase P6b-validation

---

## Цель сессии

Подробно спланировать и начать глубокую валидацию MCP Server в реальных условиях. Включает:
1. Подключение MCP Server к Cursor (рабочий конфиг)
2. Подключение 2–3 новых Telegram-каналов через pipeline
3. Прогон 10–15 пользовательских сценариев через MCP tools
4. Фиксация проблем и итеративное исправление
5. Оптимизация tool descriptions и форматов ответов

---

## Контекст проекта

### Текущее состояние (после Session 50)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17 + pgvector 0.8.2
- **Тесты:** 607 passed, 0 failures
- **Данные:** 1 канал (@labdiagnostica_logical), 1130 raw → 1128 processed, 80 тем, embeddings + RAG работают

### MCP Server (реализован в Session 50)

**Файл:** `tg_parser/mcp_server.py`

**6 MCP Tools:**

| Tool | Сигнатура | Источник данных |
|------|-----------|-----------------|
| `search_knowledge_base` | `(query, channel_id?, limit=10) → list[SearchResultItem]` | `retrieval_service.search()` |
| `ask_question` | `(question, channel_id?) → AnswerResultItem` | `retrieval_service.answer()` |
| `list_topics` | `(channel_id?, topic_type?, limit=50) → list[TopicSummary]` | `processing_repos()` → topic_card_repo, topic_bundle_repo |
| `get_topic_details` | `(topic_id) → TopicDetail \| str` | `processing_repos()` → topic_card_repo, topic_bundle_repo |
| `list_channels` | `() → list[ChannelSummary]` | `ingestion_state_repo()` + `channel_service.get_channel_stats()` |
| `get_document` | `(source_ref) → DocumentDetail \| str` | `processing_repos()` → proc_repo |

**3 MCP Resources:**
- `tgparser://channels` — JSON список каналов
- `tgparser://channels/{channel_id}/topics` — темы канала
- `tgparser://topics/{topic_id}` — карточка темы

**Запуск:**
```bash
# Прямой запуск (stdio, для Cursor/Claude Desktop):
python -m tg_parser.mcp_server

# Через CLI:
tg-parser mcp                          # stdio (default)
tg-parser mcp --transport sse          # SSE
tg-parser mcp --transport streamable-http
```

**Structured output:**
- `ask_question` → `AnswerResultItem` напрямую (Pydantic model, `wrap_output: false`, чистейший формат)
- `search_knowledge_base`, `list_topics`, `list_channels` → `list[Model]` (обёрнуты в `{"result": [...]}`)
- `get_topic_details`, `get_document` → `Union[Model, str]` (обёрнуты в `{"result": ...}`, `anyOf` schema)

### REST API (P6a, работает)

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/v1/topics` | GET | Список тем |
| `/api/v1/topics/{topic_id:path}` | GET | Карточка темы |
| `/api/v1/topics/{topic_id:path}/bundle` | GET | Bundle items |
| `/api/v1/channels` | GET | Список каналов |
| `/api/v1/channels/{channel_id}/stats` | GET | Статистика канала |
| `/api/v1/documents?source_ref=...` | GET | Документ |
| `/api/v1/search` | POST | Семантический поиск |
| `/api/v1/ask` | POST | RAG Q&A |

### Незакоммиченные изменения (Session 50)

```
Modified:   pyproject.toml          (добавлена зависимость mcp>=1.25)
Modified:   tg_parser/cli/app.py    (добавлена команда mcp)
Untracked:  tg_parser/mcp_server.py (новый — MCP Server)
Untracked:  tests/test_mcp_server.py (новый — 18 тестов)
Untracked:  docs/notes/START_PROMPT_SESSION50_MCP_SERVER.md
```

---

## Часть 1: Подключение MCP к Cursor

### Шаг 1: Создание конфигурации `.cursor/mcp.json`

Файл `.cursor/mcp.json` НЕ существует — нужно создать.

```json
{
  "mcpServers": {
    "tg-parser": {
      "command": "/Users/alexanderefimov/TG_parser/.venv/bin/python",
      "args": ["-m", "tg_parser.mcp_server"],
      "cwd": "/Users/alexanderefimov/TG_parser",
      "env": {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "tg_parser",
        "DB_USER": "<из .env>",
        "DB_PASSWORD": "<из .env>"
      }
    }
  }
}
```

**Критические env-переменные:** MCP Server запускается как отдельный процесс, и ему нужен доступ к:
- **PostgreSQL** (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD) — для всех tools
- **OpenAI / LLM API key** (OPENAI_API_KEY или др.) — для `ask_question` (RAG) и `search_knowledge_base` (embedding)
- **Embedding config** (EMBEDDING_MODEL) — для семантического поиска

**Вариант:** Вместо перечисления env-переменных в JSON, можно загружать `.env` автоматически. Проверить: `tg_parser/config/settings.py` использует `pydantic-settings` с `env_file=".env"`. Но `cwd` MCP-процесса может отличаться от корня проекта. Нужно убедиться, что `.env` находится или указать путь.

### Шаг 2: Верификация подключения

После создания конфига:
1. Перезапустить Cursor (или перечитать MCP config)
2. Открыть чат, проверить что MCP tools доступны
3. Выполнить простой вызов: спросить "list channels" или вызвать `list_channels`

### Возможные проблемы при подключении

| Проблема | Симптом | Решение |
|----------|---------|---------|
| `.env` не найден | DB connection error | Добавить `cwd` в конфиг или полные env-переменные |
| PostgreSQL не запущен | Connection refused | `pg_isready` / запустить PostgreSQL |
| Нет OpenAI API key | `search`/`ask` падают | Убедиться что ключ в env |
| venv не содержит `mcp` | ModuleNotFoundError | `.venv/bin/pip install mcp` |
| Порт DB занят | psycopg2.OperationalError | Проверить DB_PORT |

---

## Часть 2: Подключение новых каналов

### Pipeline для нового канала (команды CLI)

```bash
# 1. Зарегистрировать источник
tg-parser add-source \
  --source-id <channel_id> \
  --channel-id <channel_id> \
  --channel-username <username> \
  --include-comments

# 2. Ingestion (сбор raw-сообщений из Telegram)
tg-parser ingest --source <channel_id>

# 3. Processing (LLM-обработка raw → ProcessedDocument)
tg-parser process --channel <channel_id> --concurrency 3

# 4. Topicization (формирование тем)
tg-parser topicize --channel <channel_id>

# 5. Embedding (генерация векторов для RAG)
tg-parser embed --channel <channel_id>
```

**Или one-shot:**
```bash
tg-parser run --source <channel_id> --out ./output
```

### Выбор каналов

По roadmap: подключить 2–3 новых канала к моменту валидации. Выбор каналов — на усмотрение владельца проекта (пользователя). Факторы:
- Русскоязычный контент (pipeline, промпты, RAG — настроены на русский)
- Достаточный объём постов (50–300 для репрезентативности)
- Разнообразная тематика (для кросс-канального поиска)
- Наличие комментариев (для тестирования `include_comments`)

### Требования к инфраструктуре

- **Telegram API:** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`, `TELEGRAM_SESSION_NAME` — должны быть в `.env`
- **LLM для processing:** Токены будут потрачены на обработку (от 50 до 300 сообщений × ~500 tokens/msg)
- **Embedding:** Токены на text-embedding-3-small (дёшево)
- **PostgreSQL:** Место на диске (минимально при 3–4 каналах)

### Ожидаемое время pipeline на канал

| Этап | ~Время (100 сообщений) | Примечание |
|------|------------------------|------------|
| Ingestion | 1–5 мин | Зависит от Telegram rate limits |
| Processing | 5–15 мин | concurrency=3, зависит от LLM provider |
| Topicization | 2–5 мин | LLM batch processing |
| Embedding | 1–2 мин | OpenAI embedding API |
| **Итого** | **10–30 мин на канал** | |

---

## Часть 3: Сценарии валидации MCP

### 3.1. Базовые сценарии (проверка каждого tool)

| # | Сценарий | MCP Tool | Что проверяем |
|---|----------|----------|---------------|
| 1 | "Покажи список каналов" | `list_channels` | Все каналы видны, статистика корректна |
| 2 | "Какие темы есть в канале X?" | `list_topics(channel_id=X)` | Фильтрация по каналу, корректные items_count |
| 3 | "Покажи детали темы Y" | `get_topic_details(topic_id=Y)` | scope_in/out, anchors, bundle items |
| 4 | "Найди информацию про Z" | `search_knowledge_base("Z")` | Результаты ранжированы, summary понятны |
| 5 | "Что известно о Z?" | `ask_question("Что известно о Z?")` | RAG-ответ с источниками, адекватный текст |
| 6 | "Покажи содержимое документа tg:ch:post:123" | `get_document(source_ref)` | Полный текст, summary, topics |

### 3.2. Навигационные цепочки (multi-step)

| # | Сценарий | Цепочка tools |
|---|----------|---------------|
| 7 | Обзор базы знаний → глубокий dive | `list_channels` → `list_topics(ch)` → `get_topic_details(t)` → `get_document(ref)` |
| 8 | Поиск → чтение → углубление | `search(query)` → `get_document(ref)` → `list_topics` (найти тему документа) |
| 9 | Q&A → проверка источников | `ask_question(q)` → `get_document(source_ref)` (для каждого источника) |

### 3.3. Кросс-канальные сценарии (после подключения 2+ каналов)

| # | Сценарий | Что проверяем |
|---|----------|---------------|
| 10 | "Найди информацию про X по всем каналам" (без channel_id) | Кросс-канальный поиск: результаты из разных каналов |
| 11 | "Сравни темы в канале A и канале B" | `list_topics(A)` + `list_topics(B)` — AI-агент делает сравнение |
| 12 | "Задай вопрос по всем каналам" | `ask_question` без filter — контекст из нескольких каналов |
| 13 | "Покажи все singleton-темы" | `list_topics(topic_type="singleton")` — фильтрация по типу |

### 3.4. Edge cases и стресс-тесты

| # | Сценарий | Что проверяем |
|---|----------|---------------|
| 14 | Несуществующий topic_id | `get_topic_details("nonexistent")` → адекватное сообщение об ошибке |
| 15 | Несуществующий source_ref | `get_document("tg:ch:post:999999")` → адекватная ошибка |
| 16 | Пустой запрос или очень длинный | `search("")`, `search("очень длинный текст...")` |
| 17 | Канал без обработанных данных | `list_topics(channel_id="new_empty")` → пустой список |

---

## Часть 4: Критерии валидации (acceptance criteria)

Из `SESSION48_ROADMAP_V2.md`:

- [ ] **10–15 типичных пользовательских сценариев** протестированы в Cursor
- [ ] **Каждый MCP tool** вызван минимум **5 раз** в реальных диалогах
- [ ] **Проблемы с форматами ответов** зафиксированы и исправлены
- [ ] **Tool descriptions** оптимизированы для AI-агентов (чётко описывают когда и как использовать)
- [ ] **Кросс-канальный поиск** работает на 3–4 каналах

### Дополнительные критерии качества

- [ ] AI-агент (Cursor) корректно выбирает нужный tool для задачи пользователя
- [ ] Цепочки tools (навигация → детали → документ) работают без сбоев
- [ ] `ask_question` даёт осмысленные ответы с корректными ссылками на источники
- [ ] `search_knowledge_base` ранжирует результаты адекватно запросу
- [ ] Не-найденные ресурсы (not found) обрабатываются gracefully
- [ ] MCP Server не падает после серии вызовов (стабильность stdio-процесса)

---

## Часть 5: Процесс контроля и внесения правок

### Цикл валидации

```
Запустить сценарий → Оценить результат → Зафиксировать проблему →
  → Внести правку в код → Перезапустить MCP → Повторить сценарий
```

### Что именно может потребовать правок

| Область | Типичные проблемы | Файлы |
|---------|-------------------|-------|
| **Tool descriptions** | AI-агент неправильно выбирает tool | `tg_parser/mcp_server.py` — docstrings |
| **Формат ответов** | Слишком длинный text_preview, нечитаемые поля | Pydantic-модели в `mcp_server.py` |
| **text_preview длина** | 300 символов мало/много для контекста | `mcp_server.py`, строки с `[:300]` |
| **Ошибки not-found** | Сообщение непонятно AI-агенту | `mcp_server.py`, строки с `"not found"` |
| **RAG prompt** | Ответы нерелевантные, не ссылаются на источники | `retrieval_service.py` — prompt template |
| **Embedding quality** | Поиск не находит релевантные документы | Проверить embedding model / threshold |
| **Channel stats** | Неверные цифры coverage | `channel_service.py` |
| **Topicization** | Темы невнятные для нового канала | Промпты topicization / параметры |

### Журнал валидации

Для каждого прогнанного сценария фиксировать:
1. **Сценарий** (что запрошено)
2. **Какие tools вызвал агент** (правильно ли выбрал?)
3. **Результат** (адекватный / неадекватный)
4. **Проблема** (если есть)
5. **Решение** (что исправлено)
6. **Статус** (повторная проверка пройдена?)

---

## Часть 6: Технический коммит перед валидацией

Перед началом валидации нужно:

1. **Закоммитить Session 50** (MCP Server):
   ```bash
   git add pyproject.toml tg_parser/mcp_server.py tg_parser/cli/app.py tests/test_mcp_server.py
   git commit -m "feat: Session 50 — P6b MCP Server (6 tools, 3 resources, 18 tests)"
   ```

2. **Создать `.cursor/mcp.json`** — конфиг MCP для Cursor

3. **Проверить PostgreSQL** запущен и доступен

4. **Проверить `.env`** содержит актуальные DB и LLM credentials

---

## Справка по файлам

### Файлы для возможных правок

```
tg_parser/mcp_server.py              — MCP tools, resources, Pydantic-модели, descriptions
tg_parser/services/retrieval_service.py — RAG prompt, search/answer логика
tg_parser/services/channel_service.py   — статистика каналов
.cursor/mcp.json                      — конфиг MCP для Cursor (создать)
```

### Файлы reference (не менять)

```
tg_parser/config/settings.py          — все env-переменные
tg_parser/services/db_context.py       — DB context managers
tg_parser/domain/models.py            — доменные модели
tg_parser/storage/ports.py            — порты/интерфейсы
tg_parser/cli/app.py                  — CLI команды (add-source, ingest, process, topicize, embed)
docs/notes/SESSION48_ROADMAP_V2.md    — roadmap с acceptance criteria
```

---

## Порядок выполнения

| # | Задача | Сложность |
|---|--------|-----------|
| 1 | Коммит Session 50, создание `.cursor/mcp.json` | Низкая |
| 2 | Подключение MCP к Cursor, верификация базового вызова | Низкая |
| 3 | Выбор и подключение 2–3 новых каналов (pipeline) | Средняя |
| 4 | Прогон базовых сценариев (1–6) на существующем канале | Средняя |
| 5 | Прогон навигационных цепочек (7–9) | Средняя |
| 6 | Прогон кросс-канальных сценариев (10–13) после pipeline | Средняя |
| 7 | Прогон edge cases (14–17) | Низкая |
| 8 | Итеративное исправление найденных проблем | Зависит от проблем |
| 9 | Финальная проверка acceptance criteria | Низкая |
| 10 | Документирование результатов, технический коммит | Низкая |

---

**Подготовлено:** Session 50
**Следующий шаг:** Коммит Session 50 → Создать `.cursor/mcp.json` → Проверить подключение MCP → Начать валидацию
