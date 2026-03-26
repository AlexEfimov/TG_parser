# Session 50: P6b — MCP Server

**Дата:** [дата запуска]
**Тип сессии:** Feature — MCP Server для AI-агентов
**Предыдущая сессия:** Session 49 (P6a API Enrichment)
**Roadmap:** `docs/notes/SESSION48_ROADMAP_V2.md` → Phase P6b

---

## Цель сессии

Создать MCP (Model Context Protocol) сервер, превращающий TG_parser в набор инструментов для любого AI-агента (Claude Desktop, Cursor, ChatGPT). MCP Server вызывает существующие сервисные функции и API, предоставляя инструменты для поиска, Q&A, навигации по темам и каналам.

---

## Контекст проекта

### Текущее состояние (после Session 49)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17 + pgvector 0.8.2
- **Тесты:** 580 passed, 0 failures
- **API endpoints (P6a, все работают):**

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/v1/topics` | GET | Список тем (channel_id, type, limit, offset) |
| `/api/v1/topics/{topic_id:path}` | GET | Карточка темы |
| `/api/v1/topics/{topic_id:path}/bundle` | GET | Bundle items темы |
| `/api/v1/channels` | GET | Список каналов |
| `/api/v1/channels/{channel_id}/stats` | GET | Статистика канала |
| `/api/v1/documents?source_ref=...` | GET | Документ по source_ref |
| `/api/v1/search` | POST | Семантический поиск |
| `/api/v1/ask` | POST | RAG Q&A |

- **Сервисный слой (DI-ready):**
  - `retrieval_service.search(query, channel_id?, limit)` → `list[SearchResult]`
  - `retrieval_service.answer(question, channel_id?, llm_client?)` → `AnswerResult`
  - `channel_service.get_channel_stats(channel_id)` → `dict`
  - DB context managers в `services/db_context.py`

- **Данные:** 1 канал (@labdiagnostica_logical), 1130 raw → 1128 processed, 80 тем, embeddings + RAG работают

### Архитектурные решения

1. **MCP SDK:** Использовать Python MCP SDK (`mcp` package, PyPI). Текущая версия SDK поддерживает `FastMCP` (v1) / `MCPServer` (v2) — проверить актуальный import при установке.
2. **Transport:** stdio (для Claude Desktop / Cursor) — стандартный и самый простой.
3. **Вызов данных:** Напрямую через сервисные функции и db_context (не через HTTP API), чтобы избежать двойного сетевого хопа.
4. **Конфигурация:** Через `.env` (те же переменные, что у основного приложения — DB, LLM).

---

## Задачи

### T1: Установка и настройка MCP SDK

**Действия:**
1. Добавить зависимость `mcp` в `pyproject.toml` (секция `[project].dependencies`):
   ```
   pip install mcp
   ```
   Проверить актуальную версию на PyPI.

2. Создать файл `tg_parser/mcp_server.py` — основная точка входа MCP-сервера.

3. Структура файла:

```python
from mcp.server.fastmcp import FastMCP  # или MCPServer в v2

mcp = FastMCP(
    "TG_parser Knowledge Base",
    instructions="MCP server для навигации и поиска по базе знаний Telegram-каналов. "
                 "Используй search_knowledge_base для поиска, ask_question для Q&A, "
                 "list_topics и get_topic_details для навигации по темам.",
)
```

4. Добавить CLI команду для запуска: расширить `tg_parser/cli.py` командой `tg-parser mcp` (или отдельный скрипт).

---

### T2: MCP Tools — Поиск и Q&A

#### `search_knowledge_base`

Семантический поиск по базе знаний.

```python
@mcp.tool()
async def search_knowledge_base(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
) -> list[SearchResultItem]:
    """
    Semantic search across the Telegram knowledge base.
    Returns documents ranked by relevance with scores and summaries.
    Use this to find specific information in channel posts.
    """
```

**Реализация:** Вызвать `retrieval_service.search()` → маппинг `SearchResult` → Pydantic-модель/dict для structured output.

**Важно:** Сервисные функции используют db_context managers, которые сами создают DB-соединения. Для MCP tools это подходит — каждый вызов tool создаёт соединение, использует, закрывает.

#### `ask_question`

RAG Q&A с источниками.

```python
@mcp.tool()
async def ask_question(
    question: str,
    channel_id: str | None = None,
) -> AnswerResultItem:
    """
    Ask a question about Telegram channel content.
    Uses RAG: retrieves relevant documents and generates an answer with LLM.
    Returns answer text with source references.
    """
```

**Реализация:** Вызвать `retrieval_service.answer()`.

**Существующие сигнатуры (reference):**

```python
# services/retrieval_service.py
async def search(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    threshold: float = 0.0,
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
) -> list[SearchResult]

@dataclass
class SearchResult:
    source_ref: str
    score: float
    document: ProcessedDocument | None = None

async def answer(
    question: str,
    channel_id: str | None = None,
    limit: int = 5,
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
    llm_client: LLMClient | None = None,
) -> AnswerResult

@dataclass
class AnswerResult:
    answer: str
    sources: list[SearchResult]
    model: str | None = None
```

---

### T3: MCP Tools — Навигация

#### `list_topics`

```python
@mcp.tool()
async def list_topics(
    channel_id: str | None = None,
    topic_type: str | None = None,
    limit: int = 50,
) -> list[TopicSummary]:
    """
    List topics (knowledge themes) extracted from channel content.
    Each topic has a title, summary, type (singleton/cluster), and item count.
    Use channel_id to filter by specific channel.
    """
```

**Реализация:** `processing_repos()` → `topic_card_repo.list_all()` / `.list_by_channel()` + `topic_bundle_repo.get_by_topic_id()` для items_count.

#### `get_topic_details`

```python
@mcp.tool()
async def get_topic_details(
    topic_id: str,
) -> TopicDetail:
    """
    Get full details of a topic: scope, anchors, related topics, and bundle items.
    Use this after list_topics to dive deeper into a specific topic.
    """
```

**Реализация:** `topic_card_repo.get_by_id()` + `topic_bundle_repo.get_by_topic_id()`.

#### `list_channels`

```python
@mcp.tool()
async def list_channels() -> list[ChannelSummary]:
    """
    List all connected Telegram channels with statistics.
    Shows raw/processed message counts, topics, coverage percentage.
    """
```

**Реализация:** `ingestion_state_repo.list_sources()` + для каждого канала: `channel_service.get_channel_stats()`.

**Оптимизация:** `get_channel_stats()` делает 3 DB-соединения на канал. Если каналов мало (1–4), это допустимо. Для 10+ каналов — нужен batch-метод позже (P7).

#### `get_document`

```python
@mcp.tool()
async def get_document(
    source_ref: str,
) -> DocumentDetail:
    """
    Get the full content of a processed document by its source reference.
    Source refs have format: tg:channel_id:post:123 or tg:channel_id:comment:456.
    """
```

**Реализация:** `processing_repos()` → `proc_repo.get_by_source_ref()`.

---

### T4: MCP Resources

Ресурсы — read-only data для AI-агентов (аналог GET endpoints).

```python
@mcp.resource("tgparser://channels")
async def resource_channels() -> str:
    """List of connected Telegram channels."""

@mcp.resource("tgparser://channels/{channel_id}/topics")
async def resource_channel_topics(channel_id: str) -> str:
    """Topics for a specific channel."""

@mcp.resource("tgparser://topics/{topic_id}")
async def resource_topic(topic_id: str) -> str:
    """Topic card details."""
```

**Формат ответа:** JSON-строка (MCP resources возвращают `str`).

---

### T5: Pydantic-модели для structured output

Создать Pydantic-модели для возвращаемых данных MCP tools (для structured output):

```python
class SearchResultItem(BaseModel):
    source_ref: str
    score: float
    summary: str | None = None
    text_preview: str | None = None
    channel_id: str | None = None

class AnswerResultItem(BaseModel):
    answer: str
    sources: list[SearchResultItem]
    model: str | None = None

class TopicSummary(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    items_count: int
    sources: list[str]

class TopicDetail(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    scope_in: list[str]
    scope_out: list[str]
    anchors: list[dict]
    sources: list[str]
    tags: list[str] | None = None
    items: list[dict] | None = None

class ChannelSummary(BaseModel):
    channel_id: str
    channel_username: str | None = None
    status: str
    raw_messages: int
    processed_documents: int
    topics_count: int
    coverage_percent: float

class DocumentDetail(BaseModel):
    id: str
    source_ref: str
    channel_id: str
    text_clean: str
    summary: str | None = None
    topics: list[str] = []
```

Разместить в `tg_parser/mcp_server.py` (inline, как в routes) или отдельным файлом `tg_parser/mcp_schemas.py`.

---

### T6: CLI-интеграция и запуск

**Вариант А (рекомендуемый):** Добавить команду в `tg_parser/cli.py`:

```python
@app.command()
def mcp():
    """Start MCP server (stdio transport for Claude Desktop / Cursor)."""
    from tg_parser.mcp_server import mcp as mcp_server
    mcp_server.run()  # stdio по умолчанию
```

**Вариант Б:** Прямой запуск:
```bash
python -m tg_parser.mcp_server
# или
uv run mcp run tg_parser/mcp_server.py
```

**Для Claude Desktop** — добавить конфигурацию в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tg-parser": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "tg_parser.mcp_server"],
      "env": {
        "DB_HOST": "localhost",
        "DB_NAME": "tg_parser"
      }
    }
  }
}
```

**Для Cursor** — добавить в `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "tg-parser": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "tg_parser.mcp_server"],
      "env": {
        "DB_HOST": "localhost",
        "DB_NAME": "tg_parser"
      }
    }
  }
}
```

---

### T7: Тесты

Тестировать MCP tools как обычные async-функции (они принимают аргументы и возвращают данные). Мокировать db_context (тот же паттерн, что в `test_topics_routes.py`).

**Тест-файл:** `tests/test_mcp_server.py`

**Примерная структура:**

```python
class TestSearchTool:
    async def test_search_returns_results(self):
        # mock retrieval_service.search
        # call search_knowledge_base("query")
        # assert structured output

class TestAskTool:
    async def test_ask_returns_answer(self):
        # mock retrieval_service.answer
        # call ask_question("question")

class TestListTopicsTool:
    async def test_list_topics_returns_topics(self):
        # mock processing_repos
        # call list_topics()

class TestGetTopicDetailsTool:
    async def test_get_topic_details_success(self):
    async def test_get_topic_details_not_found(self):

class TestListChannelsTool:
    async def test_list_channels_returns_channels(self):

class TestGetDocumentTool:
    async def test_get_document_success(self):
    async def test_get_document_not_found(self):
```

---

## DB Context managers (reference)

```python
# tg_parser/services/db_context.py
processing_repos()        → (SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database)
ingestion_state_repo()    → (SAIngestionStateRepo, Database)
ingestion_repos()         → (SAIngestionStateRepo, SARawMessageRepo, Database)
embedding_repos()         → (SAEmbeddingRepo, SAProcessedDocumentRepo, Database)
```

---

## Порядок выполнения

| # | Задача | Файлы | Сложность |
|---|--------|-------|-----------|
| 1 | T1: Установка MCP SDK + каркас | `pyproject.toml`, `tg_parser/mcp_server.py` (новый) | Низкая |
| 2 | T5: Pydantic-модели для structured output | `tg_parser/mcp_server.py` (inline) | Низкая |
| 3 | T2: Tools — search + ask | `tg_parser/mcp_server.py` | Средняя |
| 4 | T3: Tools — list_topics, get_topic_details, list_channels, get_document | `tg_parser/mcp_server.py` | Средняя |
| 5 | T4: Resources | `tg_parser/mcp_server.py` | Низкая |
| 6 | T6: CLI-команда + примеры конфигов | `tg_parser/cli.py`, README/docs | Низкая |
| 7 | T7: Тесты | `tests/test_mcp_server.py` (новый) | Средняя |

**Совет:** T1 + T5 + T2 можно делать последовательно как один блок. T3 и T4 независимы.

---

## Критерии завершения

- [ ] `mcp` package установлен в проекте
- [ ] MCP Server запускается через `python -m tg_parser.mcp_server`
- [ ] 6 MCP tools реализованы: `search_knowledge_base`, `ask_question`, `list_topics`, `get_topic_details`, `list_channels`, `get_document`
- [ ] 3 MCP resources реализованы: `tgparser://channels`, `tgparser://channels/{id}/topics`, `tgparser://topics/{id}`
- [ ] Tool descriptions оптимизированы для AI-агентов (чётко описывают когда и как использовать)
- [ ] Structured output — tools возвращают типизированные Pydantic-модели
- [ ] Тесты для каждого tool
- [ ] Все 580+ существующих тестов + новые проходят
- [ ] Пример конфигурации для Claude Desktop и Cursor в документации
- [ ] Технический коммит

---

## Справка по файлам

### Новые файлы (создать)

```
tg_parser/mcp_server.py           — MCP Server: FastMCP + tools + resources
tests/test_mcp_server.py          — Тесты для MCP tools
```

### Существующие файлы (модифицировать)

```
pyproject.toml                     — добавить зависимость `mcp`
tg_parser/cli.py                   — добавить команду `mcp` (опционально)
```

### Существующие файлы (reference, не менять)

```
tg_parser/services/retrieval_service.py  — search(), answer(), SearchResult, AnswerResult
tg_parser/services/channel_service.py    — get_channel_stats()
tg_parser/services/db_context.py         — processing_repos(), ingestion_state_repo(), etc.
tg_parser/domain/models.py               — TopicCard, TopicBundle, ProcessedDocument, etc.
tg_parser/storage/ports.py               — TopicCardRepo, TopicBundleRepo, etc.
tg_parser/config/settings.py             — Settings (DB, LLM, all env vars)
```

---

**Подготовлено:** Session 49
**Следующий шаг:** T1 (MCP SDK setup) → T5 (Pydantic models) → T2 (search/ask tools) → T3 (navigation tools) → T4 (resources) → T6 (CLI) → T7 (тесты)
