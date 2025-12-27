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

from tg_parser.api.routes import export_router, health_router, process_router
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

### Quick Start

1. Start processing:
```bash
curl -X POST http://localhost:8000/api/v1/process \\
  -H "Content-Type: application/json" \\
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

Currently no authentication required (development mode).
Production deployments should add API key authentication.
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
    
    yield
    
    # Shutdown
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
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Configure for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health_router)
    app.include_router(process_router)
    app.include_router(export_router)
    
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

