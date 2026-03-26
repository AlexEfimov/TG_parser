# Session 49: P6a — API Enrichment (Foundation)

**Дата:** [дата запуска]
**Тип сессии:** Feature — REST API расширение
**Предыдущая сессия:** Session 48 (Product Strategy, Roadmap v2)
**Roadmap:** `docs/notes/SESSION48_ROADMAP_V2.md` → Phase P6a

---

## Цель сессии

Расширить REST API так, чтобы **все данные** (темы, каналы, документы) были доступны программно. Это фундамент для MCP Server (P6b), Web UI (P6c/P6d) и внешних интеграций.

Дополнительно: рефакторинг `_call_llm()` в `retrieval_service.py` — замена hardcoded httpx на `LLMClient` абстракцию.

---

## Контекст проекта

### Текущее состояние (после Session 47)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17 + pgvector 0.8.2
- **Тесты:** 571 passed, 0 failures
- **DI:** Реализован для 14 сервисных функций через optional repo-параметры + `AsyncExitStack`
- **Данные:** 1 канал (@labdiagnostica_logical), 1130 raw → 1128 processed, 80 тем, embeddings + RAG работают

### Существующие API endpoints

| Endpoint | Метод | Файл |
|----------|-------|------|
| `/health`, `/status`, `/status/detailed` | GET | `routes/health.py` |
| `/api/v1/process`, `/api/v1/status/{job_id}`, `/api/v1/jobs` | POST/GET | `routes/process.py` |
| `/api/v1/export`, `/api/v1/export/status/{job_id}`, `/api/v1/export/download/{job_id}` | POST/GET | `routes/export.py` |
| `/api/v1/search`, `/api/v1/ask` | POST | `routes/rag.py` |
| `/api/v1/agents/*` | GET | `routes/agents.py` |

### Архитектурные паттерны (следовать!)

1. **Route-файл** создаёт `router = APIRouter(prefix="/api/v1", tags=["..."])`, определяет inline Pydantic schemas, lazy-импортирует сервисы.
2. **Регистрация:** добавить import в `routes/__init__.py` + `include_router()` в `api/main.py`.
3. **DB доступ:** через context managers из `services/db_context.py` (e.g. `processing_repos()`, `ingestion_repos()`).
4. **DI:** сервисные функции принимают optional repo-параметры; если не переданы — создают сами через db_context.
5. **Логирование:** `structlog.get_logger(__name__)`.

---

## Задачи

### T1: Topics API (`routes/topics.py`)

Создать новый route-файл `tg_parser/api/routes/topics.py`.

**Endpoints:**

#### `GET /api/v1/topics`

Список тем с опциональной фильтрацией по каналу.

**Query params:**
- `channel_id: str | None` — фильтр по каналу
- `type: str | None` — фильтр по типу (`singleton` / `cluster`)
- `limit: int = 50` (1–200) — пагинация
- `offset: int = 0` — смещение

**Response schema `TopicListResponse`:**

```python
class TopicListItem(BaseModel):
    id: str
    title: str
    type: str               # "singleton" | "cluster"
    summary: str
    items_count: int         # len(bundle.items) — нужен join с TopicBundleRepo
    sources: list[str]       # каналы
    updated_at: datetime

class TopicListResponse(BaseModel):
    topics: list[TopicListItem]
    total: int
    limit: int
    offset: int
```

**Реализация:**
- Lazy-import + вызвать `processing_repos()` из `db_context` для получения `(proc_repo, topic_card_repo, topic_bundle_repo, db)`
- Если `channel_id` — `topic_card_repo.list_by_channel(channel_id)`, иначе `topic_card_repo.list_all()`
- Для `items_count` — нужно загрузить bundle для каждой темы через `topic_bundle_repo.get_by_topic_id(topic_id)`. **Важно:** это N+1 запрос; для MVP допустимо, в будущем можно добавить batch-метод или SQL join
- Пост-фильтрация по `type` если указан
- Применить `offset` и `limit` к отфильтрованному списку

#### `GET /api/v1/topics/{topic_id}`

Полная карточка темы.

**Response schema `TopicDetailResponse`:**

```python
class AnchorInfo(BaseModel):
    anchor_ref: str
    score: float | None = None
    label: str | None = None

class TopicDetailResponse(BaseModel):
    id: str
    title: str
    type: str
    summary: str
    scope_in: list[str]
    scope_out: list[str]
    anchors: list[AnchorInfo]
    sources: list[str]
    tags: list[str] | None = None
    related_topics: list[str] | None = None
    updated_at: datetime
```

**Реализация:**
- `topic_card_repo.get_by_id(topic_id)` → если None, вернуть 404
- Маппинг TopicCard → TopicDetailResponse

#### `GET /api/v1/topics/{topic_id}/bundle`

Bundle items (материалы, входящие в тему).

**Response schema `TopicBundleResponse`:**

```python
class BundleItemInfo(BaseModel):
    source_ref: str
    channel_id: str
    message_id: str
    message_type: str       # "post" | "comment"
    role: str               # "anchor" | "supporting"

class TopicBundleResponse(BaseModel):
    topic_id: str
    items: list[BundleItemInfo]
    total_items: int
    updated_at: datetime
    time_range: dict | None = None  # {"start": ..., "end": ...}
```

**Реализация:**
- `topic_bundle_repo.get_by_topic_id(topic_id)` → если None, вернуть 404
- Маппинг TopicBundle + BundleItem → response

**Существующие порты (reference):**

```python
# storage/ports.py — TopicCardRepo
async def get_by_id(self, topic_id: str) -> TopicCard | None
async def list_by_channel(self, channel_id: str) -> list[TopicCard]
async def list_all(self) -> list[TopicCard]

# storage/ports.py — TopicBundleRepo
async def get_by_topic_id(self, topic_id: str) -> TopicBundle | None
async def list_by_channel(self, channel_id: str) -> list[TopicBundle]
```

**DB context:** `processing_repos()` → `(SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database)`

---

### T2: Channels API (`routes/channels.py`)

Создать новый route-файл `tg_parser/api/routes/channels.py`.

**Endpoints:**

#### `GET /api/v1/channels`

Список подключённых каналов.

**Response schema `ChannelListResponse`:**

```python
class ChannelInfo(BaseModel):
    channel_id: str
    channel_username: str | None = None
    status: str                         # "active" | "paused" | "error"
    include_comments: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

class ChannelListResponse(BaseModel):
    channels: list[ChannelInfo]
    total: int
```

**Реализация:**
- `ingestion_state_repo.list_sources()` → маппинг `Source` → `ChannelInfo`
- DB context: `ingestion_state_repo()` → `(SAIngestionStateRepo, Database)` из db_context

#### `GET /api/v1/channels/{channel_id}/stats`

Статистика канала: количества, покрытие, темы.

**Response schema `ChannelStatsResponse`:**

```python
class ChannelStatsResponse(BaseModel):
    channel_id: str
    channel_username: str | None = None
    raw_messages: int
    processed_documents: int
    topics_count: int
    covered_documents: int       # документы, привязанные хотя бы к одной теме
    coverage_percent: float      # covered / processed * 100
    embeddings_count: int
    missing_embeddings: int      # документы без embeddings
```

**Реализация:**

Этот endpoint требует данных из нескольких repo:
- `ingestion_state_repo.get_source(channel_id)` — для channel_username и валидации что канал существует
- `raw_message_repo.list_by_channel(channel_id)` → `len(...)` для raw_messages (или добавить `count_by_channel` метод)
- `processed_document_repo.list_by_channel(channel_id)` → `len(...)` для processed_documents
- `topic_card_repo.list_by_channel(channel_id)` → `len(...)` для topics_count
- Для covered_documents: собрать все `source_ref` из bundle items всех тем канала → пересечение с processed docs
- `embedding_repo.list_missing(channel_id)` → для missing_embeddings

**Важно:** Этот endpoint потребует нового db_context или расширения существующего, т.к. нужны данные из нескольких storage domains (ingestion + processing + embedding). Варианты:
1. Создать новый `channel_stats_repos()` context manager
2. Или создать сервисную функцию `get_channel_stats(channel_id)` в новом/существующем сервисе, которая внутри делает несколько db_context вызовов
3. Или (прагматичный MVP) — несколько последовательных async with внутри endpoint

**Рекомендация:** Вариант 2 — создать `services/channel_service.py` с функцией `get_channel_stats()`, которая агрегирует данные. Это будет полезно и для MCP tool `list_channels` позже.

**Оптимизация (по необходимости):** Сейчас нет `count_by_channel` методов в портах. Для MVP допустимо использовать `len(await repo.list_by_channel(...))`, но если это окажется медленным, добавить `count_by_channel()` в соответствующие порты и реализации (простой `SELECT count(*) ... WHERE channel_id = :channel_id`).

**Существующие порты (reference):**

```python
# storage/ports.py — IngestionStateRepo
async def get_source(self, source_id: str) -> Source | None
async def list_sources(self, status: str | None = None) -> list[Source]
async def get_channel_usernames(self) -> dict[str, str | None]

# Source fields: source_id, channel_id, channel_username, status, include_comments, ...
```

**DB context:** `ingestion_state_repo()` → `(SAIngestionStateRepo, Database)`

---

### T3: Documents API (`routes/documents.py`)

Создать новый route-файл `tg_parser/api/routes/documents.py`.

**Endpoints:**

#### `GET /api/v1/documents/{source_ref:path}`

Детали ProcessedDocument по source_ref.

**Примечание:** `source_ref` содержит двоеточия (e.g. `tg:channel_id:post:123`), поэтому нужен path-параметр или URL-encoding. Рекомендация: использовать query param вместо path param — `GET /api/v1/documents?source_ref=tg:...` — чтобы избежать проблем с URL-encoding.

**Альтернативный вариант:** `GET /api/v1/documents/{source_ref:path}` с FastAPI path converter.

**Response schema `DocumentDetailResponse`:**

```python
class DocumentDetailResponse(BaseModel):
    id: str
    source_ref: str
    channel_id: str
    text_clean: str
    summary: str | None = None
    topics: list[str] = []
    key_facts: list[str] = []
    message_type: str | None = None
    processed_at: datetime
    metadata: dict | None = None
```

**Реализация:**
- `processed_document_repo.get_by_source_ref(source_ref)` → если None, вернуть 404
- DB context: `processing_repos()` (ProcessedDocumentRepo уже включён)

**Существующие порты (reference):**

```python
# storage/ports.py — ProcessedDocumentRepo
async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None
async def list_by_channel(self, channel_id, from_date, to_date) -> list[ProcessedDocument]
```

---

### T4: Рефакторинг `_call_llm()` в `retrieval_service.py`

**Проблема:** Функция `_call_llm()` (строки 160–187) использует hardcoded httpx для прямого вызова OpenAI API, обходя абстракцию `LLMClient`:

```python
async def _call_llm(prompt: str) -> tuple[str, str | None]:
    import httpx
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for Q&A")
    model = settings.llm_model or "gpt-4o-mini"
    async with httpx.AsyncClient(
        base_url=settings.openai_base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60.0,
    ) as client:
        response = await client.post("/chat/completions", json={...})
        ...
```

**Целевое решение:**

Заменить на вызов `LLMClient.generate()` через `create_llm_client()` из `processing/llm/factory.py`.

```python
# Целевой код (концепт)
async def _call_llm(prompt: str, *, llm_client: LLMClient | None = None) -> tuple[str, str | None]:
    if llm_client is None:
        from tg_parser.processing.llm.factory import create_llm_client
        llm_client = create_llm_client()
    
    text = await llm_client.generate(
        prompt=prompt,
        temperature=0.2,
        max_tokens=2048,
    )
    model_name = getattr(llm_client, 'model', None) or settings.llm_model
    return text, model_name
```

**Ценность:**
- Работает со всеми 4 провайдерами (OpenAI, Anthropic, Gemini, Ollama), а не только OpenAI
- Использует общую систему rate limiting
- Тестируемо через DI (можно передать mock LLMClient)
- Подготовка к conversation history (P6d)

**Файлы:**
- `services/retrieval_service.py` — заменить `_call_llm()`, обновить `answer()` если нужно
- Удалить `import httpx` из файла (если больше не используется)

**Тесты:**
- Проверить что `answer()` работает (lazy-создание LLM клиента)
- Проверить DI: `answer(llm_client=mock)` использует переданный mock

**Интерфейс LLMClient (reference):**

```python
# processing/ports.py
class LLMClient(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
```

**Factory (reference):**

```python
# processing/llm/factory.py
def create_llm_client(settings=None) -> LLMClient:
    # Создаёт клиент по settings.llm_provider (openai|anthropic|gemini|ollama)
```

---

### T5: Регистрация новых роутеров

Обновить два файла:

**`tg_parser/api/routes/__init__.py`:**
```python
from tg_parser.api.routes.channels import router as channels_router
from tg_parser.api.routes.documents import router as documents_router
from tg_parser.api.routes.topics import router as topics_router

__all__ = [..., "topics_router", "channels_router", "documents_router"]
```

**`tg_parser/api/main.py`** — добавить в `create_app()`:
```python
from tg_parser.api.routes import ..., topics_router, channels_router, documents_router

app.include_router(topics_router)
app.include_router(channels_router)
app.include_router(documents_router)
```

---

## Порядок выполнения

| # | Задача | Файлы | Сложность |
|---|--------|-------|-----------|
| 1 | T1: Topics API | `routes/topics.py` (новый) | Средняя — 3 endpoints, join с bundles |
| 2 | T3: Documents API | `routes/documents.py` (новый) | Низкая — 1 endpoint, прямой маппинг |
| 3 | T2: Channels API | `routes/channels.py` (новый), возможно `services/channel_service.py` | Средняя — stats агрегация |
| 4 | T4: Рефакторинг `_call_llm()` | `services/retrieval_service.py` | Низкая — замена httpx на LLMClient |
| 5 | T5: Регистрация роутеров | `routes/__init__.py`, `api/main.py` | Тривиальная |
| 6 | Тесты | новые тест-файлы | Средняя |

**Совет:** T1 и T3 независимы, можно делать в любом порядке. T2 сложнее из-за агрегации статистик. T4 полностью независим.

---

## Критерии завершения

- [ ] `GET /api/v1/topics` — возвращает список тем, фильтрация по channel_id и type работает
- [ ] `GET /api/v1/topics/{id}` — возвращает полную карточку, 404 для несуществующих
- [ ] `GET /api/v1/topics/{id}/bundle` — возвращает bundle items, 404 для несуществующих
- [ ] `GET /api/v1/channels` — возвращает список каналов
- [ ] `GET /api/v1/channels/{id}/stats` — возвращает статистику с корректными counts и coverage
- [ ] `GET /api/v1/documents?source_ref=...` — возвращает ProcessedDocument, 404 для несуществующих
- [ ] `_call_llm()` в `retrieval_service.py` использует `LLMClient` вместо hardcoded httpx
- [ ] Все новые endpoints доступны в OpenAPI docs (`/docs`)
- [ ] Новые тесты для каждого endpoint
- [ ] Все 571+ существующих тестов + новые тесты проходят
- [ ] Технический коммит

---

## Справка по файлам

### API layer

```
tg_parser/api/main.py           — create_app(), lifespan, router registration
tg_parser/api/routes/__init__.py — aggregates routers (import + __all__)
tg_parser/api/routes/rag.py      — паттерн-образец: inline schemas, lazy imports, structlog
tg_parser/api/schemas.py         — shared schemas (health, process, export, ErrorResponse)
```

### Storage ports (abstract repos)

```
tg_parser/storage/ports.py       — TopicCardRepo, TopicBundleRepo, IngestionStateRepo,
                                   ProcessedDocumentRepo, RawMessageRepo, EmbeddingRepo
```

### Domain models

```
tg_parser/domain/models.py       — TopicCard, TopicBundle, BundleItem, ProcessedDocument,
                                   RawTelegramMessage, Anchor, TopicType, MessageType
```

### DB context managers

```
tg_parser/services/db_context.py:
  processing_repos()         → (SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database)
  ingestion_state_repo()     → (SAIngestionStateRepo, Database)
  ingestion_repos()          → (SAIngestionStateRepo, SARawMessageRepo, Database)
  embedding_repos()          → (SAEmbeddingRepo, SAProcessedDocumentRepo, Database)
  export_repos()             → (SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, SAIngestionStateRepo, Database)
```

### LLM абстракция

```
tg_parser/processing/ports.py           — LLMClient(ABC), generate()
tg_parser/processing/llm/factory.py     — create_llm_client(settings=None)
tg_parser/services/retrieval_service.py — _call_llm() (HARDCODED httpx — рефакторить)
```

---

**Подготовлено:** Session 48
**Следующий шаг:** T1 (Topics API) → T3 (Documents API) → T2 (Channels API) → T4 (Рефакторинг _call_llm) → T5 (Регистрация) → Тесты
