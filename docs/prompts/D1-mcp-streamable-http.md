# Стартовый промпт: D1 — MCP Streamable HTTP транспорт

## Задача

Перевести MCP-сервер на Streamable HTTP транспорт для продакшн-развёртывания на удалённом сервере:
1. **D1a:** Добавить MCP-настройки в `settings.py` (host, port, transport, auth)
2. **D1b:** Реализовать FastMCP lifespan для Database singleton lifecycle
3. **D1c:** Реализовать bearer-токен аутентификацию через SDK `TokenVerifier`
4. **D1d:** Рефакторинг `mcp_server.py` (factory-функция) и CLI (убрать SSE, добавить --host/--port)
5. **D1e:** Добавить MCP-сервис в `docker-compose.yml`
6. **D1f:** Добавить тесты для HTTP-транспорта и аутентификации
7. **D1g:** Обновить `.env.example`, docstrings и roadmap

## Контекст

В S7 были закрыты: singleton Database, structlog унификация, lazy formatting. Все 646+ тестов проходят. MCP-сервер (12 tools, 3 resources) работает через stdio. CLI уже имеет `--transport` флаг, но ветки `sse`/`streamable-http` **не инициализируют Database** — это баг.

SDK: `mcp` v1.26.0 (official Anthropic SDK). Актуальная документация рекомендует `stateless_http=True, json_response=True` для продакшна. SSE transport deprecated и перестаёт поддерживаться с апреля 2026.

## Текущее состояние файлов

### `tg_parser/mcp_server.py` — основной сервер (852 строки)

Создание FastMCP-инстанса (L41-53):
```python
mcp = FastMCP(
    "TG_parser Knowledge Base",
    instructions=("MCP server for managing and searching..."),
)
```

Entrypoint для stdio (L835-851):
```python
async def _run_mcp() -> None:
    """Initialize Database singleton, run MCP server, then clean up."""
    from tg_parser.storage.sqlalchemy import Database

    db = Database.get_instance()
    await db.init()

    try:
        await mcp.run_stdio_async()
    finally:
        await Database.close_instance()

if __name__ == "__main__":
    _configure_mcp_logging()
    import asyncio
    asyncio.run(_run_mcp())
```

Logging (L807-827):
```python
def _configure_mcp_logging() -> None:
    """Redirect all logging to stderr so stdout carries only JSON-RPC."""
    import structlog
    structlog.configure(
        processors=[...],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    ...
```

### `tg_parser/cli/app.py` — CLI команда `mcp` (L650-682)

```python
@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="Transport: stdio, sse, or streamable-http"),
):
    valid_transports = ("stdio", "sse", "streamable-http")
    if transport not in valid_transports:
        typer.echo(f"❌ Invalid transport: {transport}...", err=True)
        raise typer.Exit(code=1)

    typer.echo("🔌 Starting TG_parser MCP server...")
    typer.echo(f"   • Transport: {transport}")

    if transport == "stdio":
        import asyncio
        from tg_parser.mcp_server import _run_mcp
        asyncio.run(_run_mcp())
    else:
        from tg_parser.mcp_server import mcp as mcp_server
        mcp_server.run(transport=transport)  # БАГ: нет Database.init()!
```

### `tg_parser/config/settings.py` — нет MCP-секции

API-секция уже существует (L242-252) — паттерн для переиспользования:
```python
# API Security (Phase 2F)
api_keys: Annotated[dict[str, str], BeforeValidator(parse_json_dict)] = Field(
    default_factory=dict,
    description="API keys mapping: key -> client_name",
)
api_key_required: bool = Field(
    default=False,
    description="Require API key for all requests",
)
```

### `docker-compose.yml` — нет MCP-сервиса

Есть `postgres`, `tg_parser` (command: `["--help"]`), `ollama` (optional). MCP-сервис отсутствует. Порт 8080 свободен.

### SDK API (mcp v1.26.0)

FastMCP constructor (ключевые параметры):
```python
FastMCP(
    name: str,
    instructions: str | None = None,
    token_verifier: TokenVerifier | None = None,  # bearer auth
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
    json_response: bool = False,
    stateless_http: bool = False,
    lifespan: Callable[[FastMCP], AbstractAsyncContextManager] | None = None,
    auth: AuthSettings | None = None,  # RFC 9728 metadata
)
```

TokenVerifier protocol:
```python
class TokenVerifier(Protocol):
    async def verify_token(self, token: str) -> AccessToken | None: ...

class AccessToken(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None
    resource: str | None = None
```

AuthSettings (нужен вместе с token_verifier для RFC 9728):
```python
class AuthSettings(BaseModel):
    issuer_url: AnyHttpUrl          # OAuth AS URL (для self-hosted = свой URL)
    resource_server_url: AnyHttpUrl  # URL MCP-сервера
    required_scopes: list[str] | None = None
```

Lifespan pattern (официальный пример SDK):
```python
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        await db.disconnect()

mcp = FastMCP("My App", lifespan=app_lifespan)
```

Методы запуска:
```python
mcp.run(transport="streamable-http")         # sync
await mcp.run_streamable_http_async()         # async
await mcp.run_stdio_async()                   # async (stdio)
starlette_app = mcp.streamable_http_app()     # для mount в Starlette
```

## Что нужно сделать

### D1a: Настройки MCP в settings.py (10 мин)

Добавить секцию после API Security (~L253):
```python
# ==========================================================================
# MCP Server Configuration (D1)
# ==========================================================================

mcp_host: str = Field(
    default="127.0.0.1",
    description="MCP server bind host",
)
mcp_port: int = Field(
    default=8080,
    description="MCP server bind port",
)
mcp_transport: str = Field(
    default="stdio",
    description="MCP transport: stdio or streamable-http",
)
mcp_path: str = Field(
    default="/mcp",
    description="Streamable HTTP endpoint path",
)
mcp_auth_enabled: bool = Field(
    default=False,
    description="Require bearer token for MCP HTTP transport",
)
mcp_auth_tokens: Annotated[dict[str, str], BeforeValidator(parse_json_dict)] = Field(
    default_factory=dict,
    description="MCP auth tokens mapping: token -> client_name",
)
```

### D1b: Lifespan для Database singleton (15 мин)

В `mcp_server.py` добавить lifespan-функцию:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

@asynccontextmanager
async def _mcp_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    from tg_parser.storage.sqlalchemy import Database
    db = Database.get_instance()
    await db.init()
    try:
        yield {}
    finally:
        await Database.close_instance()
```

Передать в конструктор FastMCP. Это решает баг: DB будет инициализирована для ВСЕХ транспортов.

### D1c: Bearer-токен аутентификация (20 мин)

Создать `BearerTokenVerifier`:
```python
from mcp.server.auth.provider import AccessToken, TokenVerifier

class BearerTokenVerifier(TokenVerifier):
    def __init__(self, tokens: dict[str, str]):
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        client = self._tokens.get(token)
        if not client:
            return None
        return AccessToken(token=token, client_id=client, scopes=[])
```

Создаётся условно в factory-функции: только если `mcp_auth_enabled=True` и есть `mcp_auth_tokens`. Для stdio — auth не подключается.

Вместе с `token_verifier` нужен `AuthSettings` (RFC 9728):
```python
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

auth=AuthSettings(
    issuer_url=AnyHttpUrl(f"http://{settings.mcp_host}:{settings.mcp_port}"),
    resource_server_url=AnyHttpUrl(f"http://{settings.mcp_host}:{settings.mcp_port}"),
)
```

### D1d: Рефакторинг mcp_server.py и CLI (1 час)

#### mcp_server.py

Вынести создание `FastMCP` в factory-функцию:
```python
def create_mcp_server() -> FastMCP:
    from tg_parser.config import settings

    kwargs: dict[str, Any] = dict(
        name="TG_parser Knowledge Base",
        instructions="...",
        host=settings.mcp_host,
        port=settings.mcp_port,
        streamable_http_path=settings.mcp_path,
        stateless_http=True,
        json_response=True,
        lifespan=_mcp_lifespan,
    )

    if settings.mcp_auth_enabled and settings.mcp_auth_tokens:
        kwargs["token_verifier"] = BearerTokenVerifier(settings.mcp_auth_tokens)
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(f"http://{settings.mcp_host}:{settings.mcp_port}"),
            resource_server_url=AnyHttpUrl(f"http://{settings.mcp_host}:{settings.mcp_port}"),
        )

    return FastMCP(**kwargs)

mcp = create_mcp_server()
```

Обновить entrypoints:
```python
async def _run_mcp() -> None:
    """Run MCP server via stdio (local development)."""
    _configure_mcp_logging()
    await mcp.run_stdio_async()

async def _run_http() -> None:
    """Run MCP server via Streamable HTTP (production)."""
    await mcp.run_streamable_http_async()
```

Lifespan заботится о DB init/close для обоих транспортов. `_configure_mcp_logging()` нужен только для stdio (stdout = JSON-RPC).

#### CLI (`app.py`)

```python
@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="Transport: stdio or streamable-http"),
    host: str = typer.Option(None, help="Bind host (default from settings)"),
    port: int = typer.Option(None, help="Bind port (default from settings)"),
):
    valid_transports = ("stdio", "streamable-http")
    ...

    if host or port:
        from tg_parser.mcp_server import mcp as mcp_server
        if host: mcp_server.settings.host = host
        if port: mcp_server.settings.port = port

    if transport == "stdio":
        import asyncio
        from tg_parser.mcp_server import _run_mcp
        asyncio.run(_run_mcp())
    else:
        import asyncio
        from tg_parser.mcp_server import _run_http
        asyncio.run(_run_http())
```

### D1e: Docker Compose (15 мин)

Добавить сервис `mcp` в `docker-compose.yml`:
```yaml
  # MCP Server (Streamable HTTP for AI agents)
  mcp:
    build:
      context: .
      dockerfile: Dockerfile
    image: tg_parser:latest
    container_name: tg_parser_mcp
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env:ro
      - ./prompts:/app/prompts:ro
    ports:
      - "${MCP_PORT:-8080}:8080"
    environment:
      # Database
      - DB_HOST=${DB_HOST:-postgres}
      - DB_PORT=${DB_PORT:-5432}
      - DB_NAME=${DB_NAME:-tg_parser}
      - DB_USER=${DB_USER:-tg_parser_user}
      - DB_PASSWORD=${DB_PASSWORD:?Database password required}
      # LLM
      - LLM_PROVIDER=${LLM_PROVIDER:-openai}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      # MCP
      - MCP_TRANSPORT=streamable-http
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8080
      - MCP_AUTH_ENABLED=${MCP_AUTH_ENABLED:-false}
      - MCP_AUTH_TOKENS=${MCP_AUTH_TOKENS:-{}}
      # Logging
      - LOG_FORMAT=${LOG_FORMAT:-json}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    command: ["mcp", "--transport", "streamable-http"]
    restart: unless-stopped
    networks:
      - tg_parser_network
```

### D1f: Тесты (1 час)

Создать `tests/test_mcp_http.py`:
- **`TestBearerTokenVerifier`**: valid token → AccessToken, invalid → None, empty dict → None
- **`TestCreateMcpServer`**: проверить что factory возвращает FastMCP с правильными settings
- **`TestMcpHttpTransport`**: запустить `mcp.streamable_http_app()` через `httpx.AsyncClient(transport=ASGITransport(app))`, отправить JSON-RPC initialize, проверить ответ
- **`TestMcpHttpAuth`**: с `mcp_auth_enabled=True` — запрос без токена → 401, с валидным → 200

Существующие тесты (`test_mcp_server.py`, `test_mcp_management.py`) вызывают tool-функции напрямую — **не ломаются**.

### D1g: Документация (15 мин)

1. Обновить docstring в начале `mcp_server.py`
2. Добавить MCP-секцию в `.env.example`
3. Обновить `docs/technical-debt-roadmap.md` — отметить D1

## Тестирование

### Юнит-тесты (быстрые)
```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_http.py tests/test_mcp_server.py tests/test_mcp_management.py -v
```

### Полный набор
```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_postgres_integration.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_migrations.py --ignore=tests/test_storage_integration.py -v
```

### Smoke test (Streamable HTTP)
```bash
# Запустить MCP-сервер
tg-parser mcp --transport streamable-http --host 0.0.0.0 --port 8080

# В другом терминале — проверить MCP initialize
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `tg_parser/config/settings.py` | D1a: добавить MCP-секцию настроек |
| `tg_parser/mcp_server.py` | D1b+D1c+D1d: lifespan, auth, factory-функция |
| `tg_parser/cli/app.py` | D1d: убрать SSE, добавить --host/--port |
| `docker-compose.yml` | D1e: добавить MCP-сервис |
| `.env.example` | D1g: добавить MCP-переменные |
| `docs/technical-debt-roadmap.md` | D1g: отметить D1 |
| `tests/test_mcp_http.py` (новый) | D1f: тесты HTTP-транспорта и auth |

## Чего НЕ делать

- **Не менять** сигнатуры существующих MCP tools и resources — только транспорт и lifecycle
- **Не трогать** существующие тесты `test_mcp_server.py` и `test_mcp_management.py` — они вызывают tool-функции напрямую
- **Не реализовывать** OAuth Authorization Server — только простая проверка bearer-токенов
- **Не добавлять** TLS/HTTPS — это задача reverse proxy (nginx/caddy)
- **Не убирать** поддержку stdio — он остаётся для локальной разработки и Claude Desktop

## Порядок выполнения

1. **D1a** (10 мин) — настройки в settings.py
2. **D1b** (15 мин) — lifespan для DB lifecycle
3. **D1c** (20 мин) — BearerTokenVerifier
4. **D1d** (1 ч) — рефакторинг mcp_server.py + CLI
5. **D1f** (1 ч) — тесты
6. **D1e** (15 мин) — Docker Compose
7. **D1g** (15 мин) — документация

## Критерии приёмки

1. `tg-parser mcp --transport streamable-http` запускает HTTP-сервер на настроенном порту
2. `tg-parser mcp` (stdio) работает как прежде — обратная совместимость
3. MCP initialize через HTTP возвращает корректный JSON-RPC ответ
4. При `MCP_AUTH_ENABLED=true` запросы без bearer-токена отклоняются
5. Database singleton инициализируется через lifespan для обоих транспортов
6. Docker `mcp` сервис запускается и отвечает на health-запросы
7. Все 646+ существующих тестов проходят
8. Новые тесты в `test_mcp_http.py` проходят
