# MCP Management Tools — Спецификация (Вариант C)

> **Scope (updated 2026-05-14).** Этот документ — **исходная проектная
> спецификация** (март 2026) для **первоначального набора** management-tools
> (channel management + pipeline control). Полный набор реализованных MCP
> tools на `main` (HEAD `47e1c72`, версия `4.3.0`) — **43 инструмента**:
> базовый набор + F4 multi-tenancy (user management) + F4-B Core workspaces
> (8 tools) + F5-C resummarize + F6 digests + F11 watchlist + export + LLM
> config + prompts reload. Source of truth для actual surface:
> `tg_parser/mcp_server.py` (`@mcp.tool()` декораторы) + полный список и
> JSON-schemas в [`docs/MCP_AGENT_GUIDE.md`](MCP_AGENT_GUIDE.md).
>
> Полная per-tool spec для всех 43 tools — backlog item, не блокирует MVP;
> этот документ остаётся как историческая фиксация design-rationale для
> management-слоя. См. также `docs/SERVER_ARCHITECTURE.md`,
> `PRODUCTION_DEPLOYMENT.md`.

---

> Лёгкий управляющий слой: быстрые безопасные операции в MCP + делегирование тяжёлых операций через REST API.

## 1. Мотивация

Текущий MCP-сервер (`tg_parser/mcp_server.py`) предоставляет **6 read-only инструментов** для навигации и поиска по базе знаний. Управление каналами (добавление, приостановка) и запуск пайплайна доступны только через CLI (`tg-parser add-source`, `tg-parser ingest` и т.д.) или REST API (`POST /api/v1/process`).

**Проблема:** AI-агент, работающий через MCP, не может выполнить полный цикл «подключить канал → обработать данные → ответить на вопросы». Нужно вручную переключаться на CLI/API.

**Решение:** Добавить в MCP минимальный набор управляющих инструментов:
- Быстрые операции (add/pause/resume channel) — выполняются напрямую в БД
- Тяжёлые операции (pipeline) — делегируются в REST API, возвращают `job_id`
- Мониторинг — статус пайплайна и scheduler'а

## 2. Новые MCP-инструменты

### 2.1 `add_channel` — добавление канала

**Тип:** write, быстрый (одна запись в БД)

**Параметры:**

| Параметр | Тип | Required | Default | Описание |
|---|---|---|---|---|
| `channel_id` | `str` | да | — | Telegram channel ID или username (без `@`) |
| `channel_username` | `str \| None` | нет | `None` | Username канала для отображения |
| `include_comments` | `bool` | нет | `false` | Собирать ли комментарии к постам |
| `batch_size` | `int` | нет | `100` | Размер батча для ingestion |

**Логика:**
1. Нормализовать `channel_id`: убрать `@` если есть
2. Использовать `channel_id` как `source_id` (для консистентности с остальной системой)
3. Через `ingestion_state_repo` выполнить `upsert_source` с `status="active"`
4. Если источник уже существует — обновить поля (сохранить `created_at`)
5. Вернуть структурированный результат

**Возвращаемая схема:**

```python
class AddChannelResult(BaseModel):
    channel_id: str
    source_id: str
    status: str  # "active"
    created: bool  # true если новый, false если обновлён
    message: str
```

**Пример docstring для MCP:**
```
Add a Telegram channel to the knowledge base.
The channel becomes active immediately. The background scheduler will
automatically start ingesting and processing its content on the next cycle.
To process immediately, use trigger_pipeline after adding.
```

**Реализация** — адаптировать логику из `tg_parser/cli/add_source_cmd.py`:

```python
@mcp.tool()
async def add_channel(
    channel_id: str,
    channel_username: str | None = None,
    include_comments: bool = False,
    batch_size: int = 100,
) -> AddChannelResult:
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.storage.ports import Source

    normalized = channel_id.lstrip("@")

    async with ingestion_state_repo() as (state_repo, _db):
        existing = await state_repo.get_source(normalized)

        source = Source(
            source_id=normalized,
            channel_id=normalized,
            channel_username=channel_username,
            status="active",
            include_comments=include_comments,
            batch_size=batch_size,
            created_at=existing.created_at if existing else None,
        )
        await state_repo.upsert_source(source)

    return AddChannelResult(
        channel_id=normalized,
        source_id=normalized,
        status="active",
        created=existing is None,
        message=f"Channel '{normalized}' {'added' if existing is None else 'updated'} (status=active)."
        + " Scheduler will pick it up on the next cycle, or use trigger_pipeline to start immediately.",
    )
```

### 2.2 `pause_channel` — приостановка канала

**Тип:** write, быстрый

**Параметры:**

| Параметр | Тип | Required | Описание |
|---|---|---|---|
| `channel_id` | `str` | да | Channel ID (= source_id) |

**Логика:**
1. Найти source по `source_id = channel_id.lstrip("@")`
2. Если не найден — вернуть ошибку
3. Если уже `paused` — вернуть без изменений с `changed: false`
4. Установить `status = "paused"`, `updated_at = now()`
5. Scheduler перестанет обрабатывать канал на следующем цикле

**Возвращаемая схема:**

```python
class ChannelStatusResult(BaseModel):
    channel_id: str
    status: str
    previous_status: str
    changed: bool
    message: str
```

### 2.3 `resume_channel` — возобновление канала

**Тип:** write, быстрый

**Параметры и логика:** аналогично `pause_channel`, но устанавливает `status = "active"`.

Дополнительно: если канал в статусе `error`, `resume_channel` сбрасывает `fail_count = 0` и `last_error = None`, чтобы scheduler не пропускал его.

### 2.4 `get_pipeline_status` — статус пайплайна

**Тип:** read

**Параметры:**

| Параметр | Тип | Required | Default | Описание |
|---|---|---|---|---|
| `channel_id` | `str \| None` | нет | `None` | Фильтр по каналу |

**Логика:**
Переиспользовать `scheduler_service.get_scheduler_status()` — он уже собирает нужную информацию:
- Список источников со статусами
- `last_attempt_at`, `last_success_at`, `fail_count`, `last_error`
- Настройки scheduler'а (enabled, interval, threshold)

Если задан `channel_id` — отфильтровать до одного источника.

**Возвращаемая схема:**

```python
class PipelineSourceStatus(BaseModel):
    source_id: str
    channel_id: str
    status: str
    last_attempt_at: str | None
    last_success_at: str | None
    fail_count: int
    last_error: str | None

class PipelineStatusResult(BaseModel):
    scheduler_enabled: bool
    default_interval_seconds: int
    sources: list[PipelineSourceStatus]
```

### 2.5 `trigger_pipeline` — запуск пайплайна

**Тип:** write, делегирующий (HTTP-запрос к REST API)

**Параметры:**

| Параметр | Тип | Required | Default | Описание |
|---|---|---|---|---|
| `channel_id` | `str` | да | — | Channel ID для обработки |
| `force` | `bool` | нет | `false` | Переобработать уже обработанные документы |

**Логика:**
1. Проверить что source с данным `channel_id` существует и `status == "active"`
2. Запустить пайплайн **напрямую** через сервисный слой (без HTTP), используя fire-and-forget паттерн:
   - Вызвать `asyncio.create_task()` для `run_full_pipeline()`
   - Немедленно вернуть результат с информацией что пайплайн запущен
3. Последующий мониторинг — через `get_pipeline_status`

**Альтернативный вариант реализации — через REST API (если API-сервер гарантированно запущен):**
1. Сделать HTTP POST к `http://localhost:{api_port}/api/v1/process`
2. Вернуть `job_id` из ответа
3. Мониторинг — через `get_pipeline_status` или `GET /api/v1/status/{job_id}`

**Рекомендация:** Использовать прямой вызов через сервисный слой (вариант 1), так как:
- MCP-сервер уже имеет доступ к тем же сервисам и БД
- Не требуется зависимость от запущенного REST API
- Проще реализация

**Возвращаемая схема:**

```python
class TriggerPipelineResult(BaseModel):
    channel_id: str
    triggered: bool
    message: str
```

**Пример реализации:**

```python
@mcp.tool()
async def trigger_pipeline(
    channel_id: str,
    force: bool = False,
) -> TriggerPipelineResult:
    import asyncio
    from tg_parser.services.db_context import ingestion_state_repo
    from tg_parser.services.pipeline_service import run_full_pipeline

    normalized = channel_id.lstrip("@")

    async with ingestion_state_repo() as (state_repo, _db):
        source = await state_repo.get_source(normalized)

    if not source:
        return TriggerPipelineResult(
            channel_id=normalized,
            triggered=False,
            message=f"Source '{normalized}' not found. Use add_channel first.",
        )

    if source.status != "active":
        return TriggerPipelineResult(
            channel_id=normalized,
            triggered=False,
            message=f"Source '{normalized}' is '{source.status}'. Use resume_channel to activate it first.",
        )

    asyncio.create_task(
        _run_pipeline_background(normalized, force),
        name=f"mcp-pipeline-{normalized}",
    )

    return TriggerPipelineResult(
        channel_id=normalized,
        triggered=True,
        message=f"Pipeline started for '{normalized}'. Use get_pipeline_status to monitor progress.",
    )


async def _run_pipeline_background(source_id: str, force: bool) -> None:
    """Background wrapper with logging."""
    try:
        logger.info("MCP-triggered pipeline started for %s", source_id)
        stats = await run_full_pipeline(
            source_id=source_id,
            mode="incremental",
            force=force,
        )
        logger.info("MCP-triggered pipeline completed for %s: %s", source_id, stats)

        from tg_parser.services.embedding_service import run_embedding
        embed_stats = await run_embedding(channel_id=source_id, force=False)
        logger.info("MCP-triggered embedding completed for %s: %s", source_id, embed_stats)

    except Exception as exc:
        logger.error("MCP-triggered pipeline failed for %s: %s", source_id, exc, exc_info=True)
```

## 3. Pydantic-схемы

Все новые схемы добавляются в `mcp_server.py` рядом с существующими (`SearchResultItem`, `ChannelSummary` и т.д.):

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

## 4. Структура кода

Все новые инструменты добавляются в существующий файл `tg_parser/mcp_server.py`.

Рекомендуемая организация секций:

```
# T2: MCP Tools — Search & Q&A         (существующие: search_knowledge_base, ask_question)
# T3: MCP Tools — Navigation            (существующие: list_topics, get_topic_details, list_channels, get_document)
# T5: MCP Tools — Channel Management    (новые: add_channel, pause_channel, resume_channel)
# T6: MCP Tools — Pipeline Control      (новые: trigger_pipeline, get_pipeline_status)
# T4: MCP Resources                     (существующие ресурсы)
```

## 5. Обновление instructions FastMCP

Обновить строку `instructions` в конструкторе `FastMCP`:

```python
mcp = FastMCP(
    "TG_parser Knowledge Base",
    instructions=(
        "MCP server for managing and searching a Telegram-channel knowledge base. "
        "Use add_channel to connect new channels, pause_channel/resume_channel to control them. "
        "Use trigger_pipeline to start processing, get_pipeline_status to monitor progress. "
        "Use search_knowledge_base for semantic search, ask_question for RAG Q&A, "
        "list_topics / get_topic_details for topic navigation, "
        "list_channels for channel overview, get_document for full document content."
    ),
)
```

## 6. Обновление INSTRUCTIONS.md для MCP-клиентов

Файл, который Cursor читает при подключении к MCP-серверу. Обновить:

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

## 7. Валидация и защита

### 7.1 `add_channel` — ограничение количества каналов

Опциональная защита от чрезмерного добавления каналов AI-агентом:

```python
MAX_ACTIVE_SOURCES = 20  # Конфигурируемо через settings

async with ingestion_state_repo() as (state_repo, _db):
    active_sources = await state_repo.list_sources(status="active")
    if len(active_sources) >= MAX_ACTIVE_SOURCES and existing is None:
        return AddChannelResult(
            channel_id=normalized,
            source_id=normalized,
            status="rejected",
            created=False,
            message=f"Maximum active channels limit ({MAX_ACTIVE_SOURCES}) reached. Pause or remove unused channels first.",
        )
```

### 7.2 `trigger_pipeline` — защита от дублирования

Не запускать пайплайн если для этого канала уже запущен:

```python
_running_pipelines: set[str] = set()

if normalized in _running_pipelines:
    return TriggerPipelineResult(
        channel_id=normalized,
        triggered=False,
        message=f"Pipeline for '{normalized}' is already running.",
    )

_running_pipelines.add(normalized)
# ... в _run_pipeline_background: finally: _running_pipelines.discard(normalized)
```

### 7.3 `pause_channel` / `resume_channel` — идемпотентность

Операции идемпотентны: повторная пауза уже приостановленного канала не является ошибкой, а возвращает `changed: false`.

## 8. Тестирование

### 8.1 Unit-тесты

Добавить в `tests/test_mcp_server.py` (или отдельный `tests/test_mcp_management.py`):

- `test_add_channel_new` — добавление нового канала
- `test_add_channel_update` — обновление существующего
- `test_add_channel_normalizes_at` — `@channel` → `channel`
- `test_add_channel_limit` — проверка лимита active sources
- `test_pause_channel_active` — приостановка active канала
- `test_pause_channel_already_paused` — идемпотентность
- `test_pause_channel_not_found` — несуществующий канал
- `test_resume_channel_paused` — возобновление
- `test_resume_channel_error_resets` — сброс fail_count при resume из error
- `test_get_pipeline_status` — проверка структуры ответа
- `test_get_pipeline_status_filter` — фильтрация по channel_id
- `test_trigger_pipeline_success` — успешный запуск
- `test_trigger_pipeline_not_found` — несуществующий канал
- `test_trigger_pipeline_paused` — отказ для paused канала
- `test_trigger_pipeline_duplicate` — защита от дублирования

### 8.2 Подход к тестированию

Использовать тот же паттерн что в существующих тестах MCP: мокать `db_context` context managers, проверять вызовы к репозиториям.

Для `trigger_pipeline` — мокать `asyncio.create_task` и `run_full_pipeline`, проверять что task создаётся с правильными параметрами.

## 9. Порядок реализации

1. **Схемы** — добавить Pydantic-модели в `mcp_server.py`
2. **`add_channel`** — реализовать инструмент + тесты
3. **`pause_channel` / `resume_channel`** — реализовать + тесты
4. **`get_pipeline_status`** — реализовать (переиспользуя `scheduler_service`) + тесты
5. **`trigger_pipeline`** — реализовать с fire-and-forget + тесты
6. **Валидация** — добавить лимиты и защиту от дублирования
7. **Обновить instructions** — FastMCP instructions + INSTRUCTIONS.md
8. **Интеграционный тест** — полный цикл add → trigger → status → search

## 10. Что НЕ входило в первоначальный этап (исторический контекст)

> **Update 2026-05-14:** все четыре «не-в-scope» пункта ниже были закрыты в
> последующих волнах. Сохранено для исторического контекста design-rationale.

- **Удаление канала** — деструктивная операция; реализовано как `remove_channel`
  (soft-delete: `deleted_at` стамп; raw_messages / processed_documents / topics
  не каскадятся, скрываются из read-tools).
- **Управление scheduler'ом** — частично реализовано: `trigger_pipeline`
  даёт ручной запуск; `get_pipeline_status` даёт observability. Start/stop
  scheduler'а целиком всё ещё out-of-scope (через `.env` + рестарт).
- **Авторизация MCP** — MVP работал локально (stdio); production deploy
  использует HTTPS + Bearer token (см. `PRODUCTION_DEPLOYMENT.md`); F4
  multi-tenancy добавил per-user auth mappings (`add_user_auth` /
  `remove_user_auth`).
- **Управление настройками LLM** — реализовано через runtime override:
  `get_llm_config` / `set_llm_config` / `reset_llm_config` (per-stage
  scopes: global / processing / topicization / rag / digest / resummarize).

## 11. Зависимости от существующего кода

| Модуль | Как используется | Модификации |
|---|---|---|
| `tg_parser/storage/ports.py` → `Source`, `IngestionStateRepo` | Создание/обновление source | Без изменений |
| `tg_parser/services/db_context.py` → `ingestion_state_repo()` | DB context manager | Без изменений |
| `tg_parser/services/scheduler_service.py` → `get_scheduler_status()` | Статус пайплайна | Без изменений |
| `tg_parser/services/pipeline_service.py` → `run_full_pipeline()` | Запуск пайплайна | Без изменений |
| `tg_parser/services/embedding_service.py` → `run_embedding()` | Эмбеддинг после пайплайна | Без изменений |
| `tg_parser/mcp_server.py` | Основной файл для изменений | Добавление инструментов |

Все новые инструменты используют **существующие сервисы** без модификации их кода.
