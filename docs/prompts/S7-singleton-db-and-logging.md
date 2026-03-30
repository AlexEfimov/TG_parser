# Стартовый промпт: S7 — Singleton Database + унификация логирования

## Задача

Закрыть оставшийся технический долг из `docs/technical-debt-roadmap.md`:
1. **S7a:** Singleton Database — устранить пересоздание 3 engines на каждый запрос
2. **S7b:** Устранить дублирование DB lifecycle в `cli/add_source_cmd.py`
3. **S7c:** Унифицировать логирование (structlog vs stdlib logging)
4. **S7d:** Заменить f-string в logger-вызовах на lazy formatting

## Контекст

В S6 были закрыты: баг coverage metric, remove_channel cleanup, hardcoded timeouts, export-тесты, type:ignore, pytest-cov. Все 646 тестов проходят (1 skipped — OpenAI network). MCP smoke-тесты пройдены.

Текущая архитектура DB: `Database.from_settings()` каждый раз создаёт новый объект → `init()` создаёт 3 engines → `close()` делает `dispose()`. Это повторяется в 10 context managers в `db_context.py` и в нескольких местах через `_wiring.py`.

## Текущее состояние файлов

### S7a: `tg_parser/storage/sqlalchemy/database.py`

```python
class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ingestion_state_engine: AsyncEngine | None = None
        self.raw_storage_engine: AsyncEngine | None = None
        self.processing_storage_engine: AsyncEngine | None = None
        self._ingestion_state_sessionmaker: sessionmaker | None = None
        self._raw_storage_sessionmaker: sessionmaker | None = None
        self._processing_storage_sessionmaker: sessionmaker | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(settings=settings)  # КАЖДЫЙ ВЫЗОВ — новый инстанс

    async def init(self) -> None:
        # Создаёт 3 engines КАЖДЫЙ РАЗ
        self.ingestion_state_engine = create_engine_from_settings(...)
        self.raw_storage_engine = create_engine_from_settings(...)
        self.processing_storage_engine = create_engine_from_settings(...)
        # + 3 sessionmakers

    async def close(self) -> None:
        # dispose() КАЖДЫЙ РАЗ
        await self.ingestion_state_engine.dispose()
        await self.raw_storage_engine.dispose()
        await self.processing_storage_engine.dispose()
```

### S7a: `tg_parser/services/db_context.py`

10 context managers, все повторяют один и тот же паттерн:
```python
@asynccontextmanager
async def some_repos():
    db = Database.from_settings(settings)  # новый Database
    try:
        await db.init()                     # 3 новых engines
        session = db.xxx_session()
        try:
            yield (SomeRepo(session), ..., db)
        finally:
            await session.close()
        finally:
            await db.close()                # dispose 3 engines
```

Полный список context managers:
1. `processing_repos()` — 1 session (processing)
2. `ingestion_repos()` — 2 sessions (ingestion, raw)
3. `raw_and_processed_repos()` — 2 sessions (raw, processing)
4. `ingestion_state_repo()` — 1 session (ingestion)
5. `ingestion_and_processing_repos()` — 2 sessions (ingestion, processing)
6. `embedding_repos()` — 1 session (processing)
7. `export_repos()` — 2 sessions (processing, ingestion)
8. `stats_repos()` — 3 sessions (ingestion, raw, processing)
9. `removal_repos()` — 3 sessions (ingestion, raw, processing) + SAJobRepo, SATaskHistoryRepo
10. (неявный 10-й — через `_wiring.py` в health_checks, scheduler, agents)

### S7a: `tg_parser/services/_wiring.py`

Ещё один путь создания engine (для agent persistence):
```python
def create_processing_engine(echo=False) -> AsyncEngine:
    return create_engine_from_settings(settings, "processing", echo=echo)

def create_session_factory(engine) -> sessionmaker:
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

Вызывается из: `health_checks.py`, `background_scheduler.py`, `cli/agents_cmd.py` (4 раза), `api/routes/agents.py`.

### S7a: `tg_parser/api/main.py` — lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: scheduler, metrics
    # НЕ создаёт Database singleton
    yield
    # shutdown: scheduler stop
```

### S7b: `tg_parser/cli/add_source_cmd.py`

Дублирует lifecycle из `db_context.py`:
```python
db = Database.from_settings(settings)
await db.init()
try:
    state_session = db.ingestion_state_session()
    try:
        state_repo = SAIngestionStateRepo(state_session)
        # ... работа с repo ...
    finally:
        await state_session.close()
finally:
    await db.close()
```

Должен использовать `async with ingestion_state_repo() as (state_repo, _db):`.

### S7c: Смешанное логирование

| Файлы с `structlog` | Файлы с `logging` (stdlib) |
|----------------------|----------------------------|
| `api/routes/channels.py` | `agents/base.py` |
| `api/routes/topics.py` | `services/ingestion_service.py` |
| `api/routes/documents.py` | `services/topicization_service.py` |
| `api/main.py` | `processing/topicization.py` |
| `services/channel_service.py` | `api/health_checks.py` |
| `processing/llm/openai_client.py` | `mcp_server.py` |
| `storage/engine_factory.py` | `storage/sqlalchemy/*.py` (все repos) |
| | `services/pipeline_service.py` |
| | `services/processing_service.py` |
| | `cli/add_source_cmd.py` |
| | `agents/` (все) |

В `config/logging.py` уже есть настройка structlog. MCP-сервер конфигурирует structlog в `_configure_mcp_logging()`.

### S7d: f-string в logger

~150+ мест. Наиболее затронутые файлы (по количеству):
- `services/processing_service.py` — 17
- `services/pipeline_service.py` — 11
- `agents/orchestrator.py` — 9
- `services/export_service.py` — 8
- `cli/app.py` — 109 (в основном `typer.echo`, не logger)

## Что нужно сделать

### S7a: Singleton Database (2–3 часа)

1. **Превратить `Database` в singleton:**
```python
class Database:
    _instance: "Database | None" = None
    _initialized: bool = False

    @classmethod
    def get_instance(cls, settings: Settings | None = None) -> "Database":
        if cls._instance is None:
            if settings is None:
                from tg_parser.config import settings as default_settings
                settings = default_settings
            cls._instance = cls(settings=settings)
        return cls._instance

    @classmethod
    async def close_instance(cls) -> None:
        if cls._instance and cls._instance._initialized:
            await cls._instance.close()
            cls._instance = None

    async def init(self) -> None:
        if self._initialized:
            return
        # ... создать engines ...
        self._initialized = True

    async def close(self) -> None:
        # ... dispose engines ...
        self._initialized = False
```

2. **Упростить `db_context.py`:**
```python
async def _get_db() -> Database:
    db = Database.get_instance()
    await db.init()
    return db

@asynccontextmanager
async def processing_repos():
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SAProcessedDocumentRepo(session),
            SATopicCardRepo(session),
            SATopicBundleRepo(session),
            db,
        )
    finally:
        await session.close()
    # НЕ вызываем db.close() — singleton живёт до shutdown
```

3. **Упростить `_wiring.py`** — использовать singleton вместо `create_processing_engine()`.

4. **Добавить lifecycle в `api/main.py`:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database.get_instance()
    await db.init()
    try:
        # ... scheduler, metrics ...
        yield
    finally:
        await Database.close_instance()
```

5. **Добавить lifecycle в MCP-сервер** (`mcp_server.py`).

6. **Обновить тесты:** тесты mockают `db_context`, а не `Database` напрямую — **ничего не ломается**. Добавить `Database._instance = None` в conftest fixture для изоляции.

### S7b: Устранить дубликат в add_source_cmd.py (10 мин)

Заменить ручной lifecycle на:
```python
async with ingestion_state_repo() as (state_repo, _db):
    # ... работа с state_repo ...
```

### S7c: Унификация логирования (1 час)

1. Во всех файлах заменить `import logging` + `logger = logging.getLogger(__name__)` на `import structlog` + `logger = structlog.get_logger(__name__)`.
2. Структура structlog уже настроена в `config/logging.py`.
3. **Не трогать** `cli/app.py` (typer.echo для CLI output — не logging).

### S7d: f-string → lazy formatting (1 час)

Заменить `logger.info(f"message {var}")` → `logger.info("message %s", var)` во всех файлах.

**Исключения:**
- `typer.echo(f"...")` — это CLI output, не logging, не трогать
- structlog использует kwargs: `logger.info("message", var=var)` — это уже lazy, не трогать

## Тестирование

### Юнит-тесты (обязательно)
```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_management.py tests/test_mcp_server.py tests/test_channels_routes.py -v
```

### Полный набор
```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_postgres_integration.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_migrations.py --ignore=tests/test_storage_integration.py -v
```

### Все тесты включая integration
```bash
.venv/bin/python -m pytest tests/ -v -m ""
```

### MCP live smoke test
- `list_channels()` — проверить что работает через singleton
- `list_topics(limit=5)` — пагинация
- `search_knowledge_base(query="гипогликемия", limit=3)` — поиск

**Ожидаемый результат:** все 646+ тестов проходят, MCP-инструменты работают, engines создаются один раз при старте.

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `tg_parser/storage/sqlalchemy/database.py` | S7a: singleton pattern |
| `tg_parser/services/db_context.py` | S7a: убрать `from_settings/init/close` из каждого CM |
| `tg_parser/services/_wiring.py` | S7a: использовать singleton |
| `tg_parser/api/main.py` | S7a: lifecycle init/close в lifespan |
| `tg_parser/mcp_server.py` | S7a: lifecycle init/close |
| `tg_parser/api/health_checks.py` | S7a: использовать singleton вместо `create_processing_engine()` |
| `tg_parser/services/background_scheduler.py` | S7a: использовать singleton |
| `tg_parser/cli/agents_cmd.py` | S7a: использовать singleton |
| `tg_parser/api/routes/agents.py` | S7a: использовать singleton |
| `tg_parser/cli/add_source_cmd.py` | S7b: заменить на `ingestion_state_repo()` |
| `tests/conftest.py` | S7a: reset singleton между тестами |
| ~30 файлов в `tg_parser/` | S7c: `logging` → `structlog` |
| ~25 файлов в `tg_parser/` | S7d: f-string → lazy formatting |

## Чего НЕ делать

- **Не менять** сигнатуры context managers в `db_context.py` (yield tuple shape) — они mockаются в тестах
- **Не менять** `engine_factory.py` (factory остаётся, singleton — на уровне `Database`)
- **Не менять** сигнатуры MCP tools и REST API
- **Не трогать** `typer.echo()` — это CLI output, не logging
- **Не рефакторить** SA-репозитории (session_factory vs session — отдельная задача)

## Порядок выполнения

1. **S7b** (10 мин) — самый простой, разогрев
2. **S7a** (2–3 ч) — ядро: singleton Database + упрощение db_context + lifecycle
3. **S7c** (1 ч) — унификация logging после стабилизации S7a
4. **S7d** (1 ч) — механическая замена f-string → lazy

## Критерии приёмки

1. `Database.from_settings()` / `Database.get_instance()` возвращает singleton
2. Engines создаются **один раз** при первом использовании, не на каждый запрос
3. `db_context.py` context managers не вызывают `db.init()`/`db.close()` на каждый вход/выход
4. `add_source_cmd.py` использует `ingestion_state_repo()` вместо ручного lifecycle
5. Все файлы используют `structlog` (кроме `cli/app.py` для `typer.echo`)
6. Нет `logger.xxx(f"...")` — только lazy formatting
7. Все 646+ тестов проходят
8. MCP smoke-тесты проходят
