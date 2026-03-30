# Стартовый промпт: S2 — MCP Management Tools

## Задача

Добавить в MCP-сервер (`tg_parser/mcp_server.py`) **5 управляющих инструментов**: `add_channel`, `pause_channel`, `resume_channel`, `get_pipeline_status`, `trigger_pipeline`. Обновить `instructions` FastMCP и создать `INSTRUCTIONS.md`.

Полная спецификация: **`docs/mcp-management-tools-spec.md`** — внимательно прочитай перед началом работы.

## Контекст

Текущий MCP-сервер содержит 6 read-only инструментов для навигации и поиска по базе знаний. AI-агент не может выполнить цикл «подключить канал → обработать → искать» без переключения на CLI/API.

S1 (исправление логирования) уже выполнено — stdout чистый для JSON-RPC.

## Текущее состояние `mcp_server.py`

Файл содержит:
- Строки 1–31: импорты, `logger`, `ArgModelBase` конфигурация
- Строки 37–45: `FastMCP` конструктор с `instructions`
- Строки 47–114: Pydantic-схемы (`SearchResultItem`, `AnswerResultItem`, `TopicSummary`, `TopicListResult`, `TopicDetail`, `ChannelSummary`, `DocumentDetail`)
- Строки 116–357: MCP Tools (T2: Search & Q&A, T3: Navigation)
- Строки 359–393: MCP Resources (T4)
- Строки 395–421: `_configure_mcp_logging()` (S1)
- Строки 423–429: Entrypoint (`__main__`)

## Что нужно сделать (по порядку)

### S2.1: Pydantic-схемы

Добавить **после** существующих схем (после строки 114), **перед** секцией T2:

```python
class AddChannelResult(BaseModel):
    channel_id: str
    source_id: str
    status: str
    created: bool
    message: str

class ChannelStatusResult(BaseModel):
    channel_id: str
    status: str
    previous_status: str
    changed: bool
    message: str

class PipelineSourceStatus(BaseModel):
    source_id: str
    channel_id: str
    status: str
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    fail_count: int = 0
    last_error: str | None = None

class PipelineStatusResult(BaseModel):
    scheduler_enabled: bool
    default_interval_seconds: int
    sources: list[PipelineSourceStatus]

class TriggerPipelineResult(BaseModel):
    channel_id: str
    triggered: bool
    message: str
```

### S2.2: `add_channel`

Новая секция **после** T3 (Navigation), **перед** T4 (Resources):

```
# T5: MCP Tools — Channel Management
```

**Параметры:** `channel_id: str`, `channel_username: str | None = None`, `include_comments: bool = False`, `batch_size: int = 100`

**Логика:**
1. Нормализовать: `normalized = channel_id.lstrip("@")`
2. Через `ingestion_state_repo()` → `state_repo.get_source(normalized)` проверить существование
3. Проверить лимит active sources (`MAX_ACTIVE_SOURCES = 20`) — только для **новых** каналов
4. Создать `Source(source_id=normalized, channel_id=normalized, ...)` и вызвать `state_repo.upsert_source(source)`
5. Вернуть `AddChannelResult` с `created=True/False`

**Импорты (lazy):**
```python
from tg_parser.services.db_context import ingestion_state_repo
from tg_parser.storage.ports import Source
```

**API `Source.__init__`** (из `tg_parser/storage/ports.py`):
```python
Source(
    source_id: str,
    channel_id: str,
    status: str,              # "active"|"paused"|"error"
    include_comments: bool,
    channel_username: str | None = None,
    batch_size: int | None = None,
    created_at: datetime | None = None,  # передать existing.created_at если update
    # ... остальные поля имеют defaults
)
```

**API `IngestionStateRepo`:**
- `get_source(source_id: str) -> Source | None`
- `list_sources(status: str | None = None) -> list[Source]`
- `upsert_source(source: Source) -> None`

### S2.3: `pause_channel` / `resume_channel`

В той же секции T5.

**`pause_channel(channel_id: str) -> ChannelStatusResult`:**
1. `normalized = channel_id.lstrip("@")`
2. `state_repo.get_source(normalized)` — если None → ошибка в `message`, `changed=False`
3. Если уже `paused` → вернуть `changed=False` (идемпотентно)
4. Иначе: обновить `source.status = "paused"`, `upsert_source(source)`, вернуть `changed=True`

**`resume_channel(channel_id: str) -> ChannelStatusResult`:**
1. Аналогично, но `status = "active"`
2. **Дополнительно:** если предыдущий статус `error` — сбросить `fail_count = 0` и `last_error = None`

### S2.4: `get_pipeline_status`

Новая секция:
```
# T6: MCP Tools — Pipeline Control
```

**`get_pipeline_status(channel_id: str | None = None) -> PipelineStatusResult`:**

Переиспользовать `scheduler_service.get_scheduler_status()`:

```python
from tg_parser.services.scheduler_service import get_scheduler_status
```

**API `get_scheduler_status(*, repo=None) -> dict`** возвращает:
```python
{
    "scheduler_enabled": bool,
    "default_interval_seconds": int,
    "retopicize_threshold": int,
    "sources": [
        {
            "source_id": str,
            "channel_id": str,
            "status": str,
            "poll_interval_seconds": int,
            "last_attempt_at": str | None,  # ISO format
            "last_success_at": str | None,
            "fail_count": int,
            "last_error": str | None,
        },
        ...
    ],
}
```

Если `channel_id` задан — отфильтровать `sources` до одного канала.
Маппить каждый dict в `PipelineSourceStatus`, обернуть в `PipelineStatusResult`.

### S2.5: `trigger_pipeline`

В секции T6, после `get_pipeline_status`.

**`trigger_pipeline(channel_id: str, force: bool = False) -> TriggerPipelineResult`:**

1. `normalized = channel_id.lstrip("@")`
2. Проверить source exists через `ingestion_state_repo`
3. Если не найден → `triggered=False`, message
4. Если `status != "active"` → `triggered=False`, message
5. Проверить `_running_pipelines: set[str]` на дубликат → `triggered=False`
6. `asyncio.create_task(_run_pipeline_background(normalized, force))`
7. Вернуть `triggered=True`

**Модуль-уровневая переменная:**
```python
_running_pipelines: set[str] = set()
```

**Вспомогательная функция `_run_pipeline_background`:**
```python
async def _run_pipeline_background(source_id: str, force: bool) -> None:
    try:
        from tg_parser.services.pipeline_service import run_full_pipeline
        from tg_parser.services.embedding_service import run_embedding

        logger.info("MCP-triggered pipeline started for %s", source_id)
        await run_full_pipeline(source_id=source_id, mode="incremental", force=force)
        await run_embedding(channel_id=source_id, force=False)
        logger.info("MCP-triggered pipeline completed for %s", source_id)
    except Exception:
        logger.exception("MCP-triggered pipeline failed for %s", source_id)
    finally:
        _running_pipelines.discard(source_id)
```

**API `run_full_pipeline`:**
```python
async def run_full_pipeline(
    source_id: str,
    output_dir: str = "./output",
    mode: Literal["snapshot", "incremental"] = "incremental",
    force: bool = False,
    ...
) -> dict
```

**API `run_embedding`:**
```python
async def run_embedding(
    channel_id: str,
    force: bool = False,
    ...
) -> dict[str, int]
```

### S2.6: Обновление instructions и INSTRUCTIONS.md

**1. Обновить `instructions` в конструкторе `FastMCP` (строки 39–44):**

```python
instructions=(
    "MCP server for managing and searching a Telegram-channel knowledge base. "
    "Use add_channel to connect new channels, pause_channel/resume_channel to control them. "
    "Use trigger_pipeline to start processing, get_pipeline_status to monitor progress. "
    "Use search_knowledge_base for semantic search, ask_question for RAG Q&A, "
    "list_topics / get_topic_details for topic navigation, "
    "list_channels for channel overview, get_document for full document content."
),
```

**2. Создать `INSTRUCTIONS.md` в корне проекта:**

```markdown
MCP server for navigating, searching, and managing a Telegram-channel knowledge base.

**Channel Management:**
- `add_channel` — add a new Telegram channel (becomes active immediately)
- `pause_channel` / `resume_channel` — control channel ingestion
- `trigger_pipeline` — start processing pipeline for a channel
- `get_pipeline_status` — check pipeline and scheduler status

**Search & Q&A:**
- `search_knowledge_base` — semantic search across channel content
- `ask_question` — RAG-powered Q&A with source citations

**Navigation:**
- `list_channels` — list all channels with statistics
- `list_topics` / `get_topic_details` — browse extracted topics
- `get_document` — get full processed document content
```

## Файлы для изменения

| Файл | Что делать |
|---|---|
| `tg_parser/mcp_server.py` | Схемы + 5 инструментов + `_run_pipeline_background` + `_running_pipelines` + обновить instructions |
| `INSTRUCTIONS.md` | Создать (новый файл) |
| `tests/test_mcp_management.py` | Создать (новый файл с тестами) |

**Другие файлы менять НЕ нужно.** Не трогать `ports.py`, `db_context.py`, `scheduler_service.py`, `pipeline_service.py`, `embedding_service.py`.

## Тестирование

### Unit-тесты (`tests/test_mcp_management.py`)

Создать **отдельный** файл тестов. Использовать тот же паттерн мокирования что в `tests/test_mcp_server.py` — мокать `db_context` context managers.

**Обязательные тесты (15 штук):**

#### add_channel (4 теста)
- `test_add_channel_new` — новый канал, `created=True`, `status="active"`
- `test_add_channel_update` — существующий канал, `created=False`, `status="active"`
- `test_add_channel_normalizes_at` — `"@my_channel"` → `channel_id="my_channel"`
- `test_add_channel_limit_reached` — 20+ active sources → `status="rejected"`, `created=False`

#### pause_channel (3 теста)
- `test_pause_channel_active` — active→paused, `changed=True`
- `test_pause_channel_already_paused` — paused→paused, `changed=False`
- `test_pause_channel_not_found` — `changed=False`, message содержит "not found"

#### resume_channel (3 теста)
- `test_resume_channel_paused` — paused→active, `changed=True`
- `test_resume_channel_error_resets` — error→active, `fail_count=0`, `last_error=None`, `changed=True`
- `test_resume_channel_not_found` — `changed=False`

#### get_pipeline_status (2 теста)
- `test_get_pipeline_status_all` — возвращает все sources с правильной структурой
- `test_get_pipeline_status_filter` — `channel_id="ch"` → только один source

#### trigger_pipeline (3 теста)
- `test_trigger_pipeline_success` — source exists + active → `triggered=True`, `create_task` вызван
- `test_trigger_pipeline_not_found` — `triggered=False`
- `test_trigger_pipeline_paused` — source paused → `triggered=False`

### Паттерн мокирования для `ingestion_state_repo`

В `tests/test_mcp_server.py` уже есть `_mock_ingestion_state_repo()` — скопируй и расширь. Для новых тестов нужен `get_source` mock:

```python
def _mock_ingestion_state_repo(sources=None, get_source_result=None):
    sources = sources or []
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.list_sources.return_value = sources
    state_repo.get_source.return_value = get_source_result
    state_repo.upsert_source.return_value = None

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo  # возвращай state_repo для assert-ов на upsert_source
```

Для `trigger_pipeline` — мокать `asyncio.create_task`:
```python
with patch("tg_parser.mcp_server.asyncio") as mock_asyncio:
    result = await trigger_pipeline("ch")
    mock_asyncio.create_task.assert_called_once()
```

Не забудь очистить `_running_pipelines` в `setUp` / fixture:
```python
from tg_parser.mcp_server import _running_pipelines
_running_pipelines.clear()
```

### Для `get_pipeline_status` — мокать `scheduler_service`:

```python
SCHEDULER_STATUS_PATCH = "tg_parser.services.scheduler_service.get_scheduler_status"

mock_status = {
    "scheduler_enabled": True,
    "default_interval_seconds": 600,
    "retopicize_threshold": 5,
    "sources": [
        {
            "source_id": "ch",
            "channel_id": "ch",
            "status": "active",
            "poll_interval_seconds": 600,
            "last_attempt_at": "2026-03-30T10:00:00",
            "last_success_at": "2026-03-30T10:00:00",
            "fail_count": 0,
            "last_error": None,
        }
    ],
}
with patch(SCHEDULER_STATUS_PATCH, return_value=mock_status):
    result = await get_pipeline_status()
```

### Проверка существующих тестов

```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_mcp_management.py -v
```

**Известные pre-existing failures:** 5 тестов в `TestListTopicsTool` падают (не связаны с S2, `list_topics` возвращает `TopicListResult` а тесты ожидают `list`). Игнорировать.

## Чего НЕ делать

- **Не менять** существующие инструменты (search, ask, list_topics, get_topic_details, list_channels, get_document)
- **Не менять** существующие Pydantic-схемы
- **Не менять** сервисный слой (`pipeline_service.py`, `scheduler_service.py`, `embedding_service.py`, `db_context.py`, `ports.py`)
- **Не добавлять** зависимостей
- **Не реализовывать** `delete_channel` — деструктивная операция, вне скоупа
- **Не оптимизировать** DB-вызовы — это задача S3

## Критерии приёмки

1. ✅ 5 новых инструментов (`add_channel`, `pause_channel`, `resume_channel`, `get_pipeline_status`, `trigger_pipeline`) зарегистрированы в MCP
2. ✅ `instructions` в FastMCP обновлены
3. ✅ `INSTRUCTIONS.md` создан
4. ✅ Все существующие инструменты продолжают работать
5. ✅ 15+ тестов в `tests/test_mcp_management.py` проходят
6. ✅ Существующие тесты в `tests/test_mcp_server.py` не ломаются (кроме pre-existing failures)
7. ✅ Защита: лимит active sources в `add_channel`, дедупликация в `trigger_pipeline`, идемпотентность в `pause/resume`
