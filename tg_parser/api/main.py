"""
FastAPI application for TG_parser HTTP API.

Usage:
    # Development
    uvicorn tg_parser.api.main:app --reload
    
    # Production
    uvicorn tg_parser.api.main:app --host 0.0.0.0 --port 8000
    
    # Or use the CLI command
    tg-parser api --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from tg_parser.api.job_store import get_job_store
from tg_parser.api.middleware import RequestLoggingMiddleware, limiter
from tg_parser.api.routes import agents_router, export_router, health_router, process_router
from tg_parser.api.schemas import ErrorResponse
from tg_parser.config import settings

logger = logging.getLogger(__name__)

# API metadata
API_TITLE = "TG_parser API"
API_DESCRIPTION = """
## TG_parser HTTP API v2.0

Telegram message processing and knowledge base extraction API.

### Features

- **Processing**: Process raw Telegram messages through LLM pipeline
- **Export**: Export processed data in various formats
- **Multi-LLM**: Support for OpenAI, Anthropic, Gemini, Ollama
- **Webhooks**: Receive callbacks when jobs complete
- **Rate Limiting**: Protection against API overuse
- **Prometheus Metrics**: `/metrics` endpoint for monitoring

### Quick Start

1. Start processing:
```bash
curl -X POST http://localhost:8000/api/v1/process \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: your-api-key" \\
  -d '{"channel_id": "labdiagnostica", "concurrency": 5}'
```

2. Check status:
```bash
curl http://localhost:8000/api/v1/status/{job_id}
```

3. Export results:
```bash
curl -X POST http://localhost:8000/api/v1/export \\
  -H "Content-Type: application/json" \\
  -d '{"format": "ndjson"}'
```

### Authentication

Set `API_KEY_REQUIRED=true` and configure `API_KEYS` environment variable:

```bash
API_KEY_REQUIRED=true
API_KEYS='{"sk-prod-xxx": "production_client", "sk-dev-yyy": "dev_team"}'
```

Then include the key in requests:
```bash
curl -H "X-API-Key: sk-prod-xxx" http://localhost:8000/api/v1/process
```

### Webhooks

Add `webhook_url` to receive notifications when jobs complete:
```json
{
  "channel_id": "test",
  "webhook_url": "https://myapp.com/webhook",
  "webhook_secret": "optional-hmac-secret"
}
```

### Rate Limits

- `POST /api/v1/process`: 10 requests/minute
- `POST /api/v1/export`: 20 requests/minute
- `GET /*`: 100 requests/minute

Response headers include:
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Unix timestamp when limit resets

### Metrics

Prometheus metrics available at `/metrics`:
- HTTP request metrics (count, latency, errors)
- Agent task metrics
- LLM request metrics
- Background scheduler metrics
"""

API_VERSION = "2.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    
    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting {API_TITLE} v{API_VERSION}")
    logger.info(f"Environment: LLM provider={settings.llm_provider}, model={settings.llm_model}")
    
    # Initialize persistent job storage
    job_store = get_job_store()
    await job_store.init()
    logger.info("Job storage initialized")
    
    # Initialize background scheduler
    scheduler = None
    if settings.scheduler_enabled:
        from tg_parser.api.scheduler import get_scheduler, setup_default_tasks
        
        scheduler = get_scheduler()
        setup_default_tasks(
            scheduler,
            cleanup_interval_hours=settings.scheduler_cleanup_interval_hours,
            health_check_interval_minutes=settings.scheduler_health_check_interval_minutes,
            retention_days=settings.agent_retention_days,
            archive_path=str(settings.agent_archive_path) if settings.agent_retention_mode == "export" else None,
        )
        scheduler.start()
        logger.info("Background scheduler started")
    
    yield
    
    # Shutdown
    if scheduler:
        scheduler.shutdown(wait=True)
        logger.info("Background scheduler stopped")
    
    await job_store.close()
    logger.info(f"Shutting down {API_TITLE}")


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.
    
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    
    # Rate limiter state
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    # Request logging middleware (must be added first to wrap all requests)
    app.add_middleware(RequestLoggingMiddleware)
    
    # CORS middleware (configured via settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )
    
    # Prometheus metrics instrumentation
    if settings.metrics_enabled:
        from tg_parser.api.metrics import create_instrumentator
        
        instrumentator = create_instrumentator()
        instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)
        logger.info("Prometheus metrics enabled at /metrics")
    
    # Include routers
    app.include_router(health_router)
    app.include_router(process_router)
    app.include_router(export_router)
    app.include_router(agents_router)
    
    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                message=str(exc),
            ).model_dump(),
        )
    
    return app


# Application instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "tg_parser.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
