# Session 16 — Phase 2F: API Production

**Дата**: 28 декабря 2025  
**Branch**: `feature/v2.0-agents`  
**Предыдущий этап**: Phase 2E (Session 15) — Hybrid Agent Mode  
**Фокус**: Production-ready HTTP API с аутентификацией и rate limiting

---

## 📋 Цель Phase 2F

Превратить HTTP API skeleton в **production-ready** сервис с:
1. **API Key Authentication** — защита endpoints
2. **Rate Limiting** — защита от перегрузки
3. **Webhooks** — callback при завершении job'ов
4. **Request Logging** — structured logging с request IDs
5. **Persistent Job Storage** — Redis/SQLite вместо in-memory

---

## 🔧 Текущее состояние API

### Что уже есть (Phase 2A):

```
tg_parser/api/
├── __init__.py
├── main.py              # FastAPI app, CORS, exception handler
├── schemas.py           # Pydantic models (24 models)
└── routes/
    ├── __init__.py
    ├── health.py        # GET /health, GET /status
    ├── process.py       # POST /api/v1/process, GET /status/{id}, GET /jobs
    └── export.py        # POST /api/v1/export, GET /status/{id}, GET /download/{id}
```

### Endpoints (8):

| Method | Endpoint | Описание |
|--------|----------|----------|
| GET | `/health` | Health check |
| GET | `/status` | Detailed status with components |
| POST | `/api/v1/process` | Start processing job |
| GET | `/api/v1/status/{job_id}` | Get job status |
| GET | `/api/v1/jobs` | List all jobs |
| POST | `/api/v1/export` | Start export job |
| GET | `/api/v1/export/status/{job_id}` | Get export status |
| GET | `/api/v1/export/download/{job_id}` | Download export file |

### Что требует улучшения:

```python
# main.py — TODO в коде:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configure for production
    ...
)

# API description:
### Authentication
Currently no authentication required (development mode).
Production deployments should add API key authentication.

# process.py — In-memory storage:
_jobs: dict[str, dict[str, Any]] = {}  # Replace with Redis/DB
```

---

## 🎯 Целевая архитектура Phase 2F

### 1. API Key Authentication

```python
# tg_parser/api/auth.py

from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader
from tg_parser.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Verify API key and return user/client identifier."""
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    # Validate against configured keys
    valid_keys = settings.api_keys  # Dict[key, client_name]
    
    if api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return valid_keys[api_key]  # Return client name for logging


# Usage in routes:
@router.post("/process")
async def start_processing(
    request: ProcessRequest,
    client: str = Depends(verify_api_key),  # Authenticated!
) -> ProcessResponse:
    logger.info(f"Client {client} started processing")
    ...
```

### 2. Rate Limiting

```python
# tg_parser/api/middleware/rate_limit.py

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

# In main.py:
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Usage in routes:
@router.post("/process")
@limiter.limit("10/minute")  # 10 requests per minute
async def start_processing(request: Request, ...):
    ...
```

**Лимиты:**

| Endpoint | Лимит | Причина |
|----------|-------|---------|
| POST /api/v1/process | 10/min | Expensive LLM calls |
| POST /api/v1/export | 20/min | I/O intensive |
| GET /* | 100/min | Read operations |

### 3. Webhooks

```python
# tg_parser/api/schemas.py — дополнение

class ProcessRequest(BaseModel):
    channel_id: str
    # ... existing fields ...
    webhook_url: str | None = Field(
        default=None, 
        description="URL to call when job completes"
    )
    webhook_secret: str | None = Field(
        default=None,
        description="HMAC secret for webhook signature"
    )


# tg_parser/api/webhooks.py

import hashlib
import hmac
import httpx

async def send_webhook(
    url: str,
    payload: dict,
    secret: str | None = None,
) -> bool:
    """Send webhook notification with optional HMAC signature."""
    headers = {"Content-Type": "application/json"}
    
    if secret:
        body = json.dumps(payload)
        signature = hmac.new(
            secret.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        return response.status_code < 400
```

### 4. Request Logging

```python
# tg_parser/api/middleware/logging.py

import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(request_id)
        
        start_time = time.time()
        
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None,
            }
        )
        
        response = await call_next(request)
        
        duration = time.time() - start_time
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            }
        )
        
        response.headers["X-Request-ID"] = request_id
        return response
```

### 5. Settings расширение

```python
# tg_parser/config/settings.py — дополнение

class Settings(BaseSettings):
    # ... existing ...
    
    # API Security
    api_keys: dict[str, str] = Field(
        default_factory=dict,
        description="API keys mapping: key -> client_name"
    )
    api_key_required: bool = Field(
        default=False,
        description="Require API key for all requests"
    )
    
    # Rate Limiting
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_process: str = Field(default="10/minute")
    rate_limit_export: str = Field(default="20/minute")
    rate_limit_default: str = Field(default="100/minute")
    
    # CORS
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins"
    )
```

**.env пример:**

```env
# API Security
API_KEY_REQUIRED=true
API_KEYS='{"sk-prod-xxx": "production_client", "sk-dev-yyy": "dev_team"}'

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PROCESS=10/minute
RATE_LIMIT_EXPORT=20/minute

# CORS
CORS_ORIGINS='["https://dashboard.example.com", "http://localhost:3000"]'
```

---

## 📁 Файлы для создания/изменения

```
tg_parser/api/
├── auth.py                    # NEW: API key authentication
├── webhooks.py                # NEW: Webhook sender
├── middleware/
│   ├── __init__.py            # NEW
│   ├── rate_limit.py          # NEW: Rate limiting
│   └── logging.py             # NEW: Request logging
├── main.py                    # UPDATE: Add middlewares
├── schemas.py                 # UPDATE: Add webhook fields
└── routes/
    ├── process.py             # UPDATE: Add auth, rate limit
    └── export.py              # UPDATE: Add auth, rate limit

tg_parser/config/
└── settings.py                # UPDATE: Add API settings

tests/
├── test_api.py                # UPDATE: Add auth tests
└── test_api_security.py       # NEW: Security-specific tests
```

---

## 🧪 Тесты

### Новые тесты для Phase 2F:

```python
# tests/test_api_security.py

class TestAPIKeyAuth:
    """Tests for API key authentication."""
    
    async def test_request_without_key_returns_401(self, client):
        response = await client.post("/api/v1/process", json={...})
        assert response.status_code == 401
    
    async def test_request_with_invalid_key_returns_403(self, client):
        response = await client.post(
            "/api/v1/process",
            json={...},
            headers={"X-API-Key": "invalid-key"}
        )
        assert response.status_code == 403
    
    async def test_request_with_valid_key_succeeds(self, client):
        response = await client.post(
            "/api/v1/process",
            json={...},
            headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 200


class TestRateLimiting:
    """Tests for rate limiting."""
    
    async def test_rate_limit_exceeded_returns_429(self, client):
        # Send 11 requests (limit is 10/min)
        for i in range(11):
            response = await client.post("/api/v1/process", ...)
        
        assert response.status_code == 429
    
    async def test_rate_limit_header_present(self, client):
        response = await client.post("/api/v1/process", ...)
        assert "X-RateLimit-Remaining" in response.headers


class TestWebhooks:
    """Tests for webhook notifications."""
    
    async def test_webhook_called_on_completion(self):
        ...
    
    async def test_webhook_signature_valid(self):
        ...


class TestRequestLogging:
    """Tests for request logging."""
    
    async def test_request_id_in_response(self, client):
        response = await client.get("/health")
        assert "X-Request-ID" in response.headers
    
    async def test_custom_request_id_preserved(self, client):
        response = await client.get(
            "/health",
            headers={"X-Request-ID": "my-custom-id"}
        )
        assert response.headers["X-Request-ID"] == "my-custom-id"
```

---

## ✅ Критерии завершения Phase 2F

1. [ ] API Key authentication реализована
2. [ ] Rate limiting работает (slowapi)
3. [ ] Webhooks отправляются при завершении job
4. [ ] Request logging с X-Request-ID
5. [ ] Settings расширены для production
6. [ ] CORS настраивается через env
7. [ ] 15+ новых тестов
8. [ ] Документация API обновлена
9. [ ] README обновлён с примерами auth

---

## 📊 Ожидаемые результаты

### До Phase 2F:

```bash
# Любой может вызвать API
curl http://localhost:8000/api/v1/process -d '{"channel_id": "test"}'
```

### После Phase 2F:

```bash
# Требуется API key
curl http://localhost:8000/api/v1/process \
  -H "X-API-Key: sk-prod-xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "test",
    "webhook_url": "https://myapp.com/webhook",
    "webhook_secret": "my-secret"
  }'

# Response включает request ID
# X-Request-ID: abc-123
# X-RateLimit-Remaining: 9
# X-RateLimit-Reset: 1703789400
```

---

## 🚀 Порядок реализации

1. **Settings** (15 мин) — добавить новые поля в settings.py
2. **Auth** (30 мин) — создать auth.py с API key verification
3. **Rate Limiting** (30 мин) — добавить slowapi middleware
4. **Request Logging** (20 мин) — создать logging middleware
5. **Webhooks** (30 мин) — реализовать webhook sender
6. **Update Routes** (20 мин) — добавить auth/rate limit в routes
7. **Tests** (40 мин) — написать 15+ тестов
8. **Docs** (15 мин) — обновить документацию

**Общее время: ~3 часа**

---

## 📎 Зависимости

```bash
# Добавить в requirements.txt
slowapi>=0.1.9        # Rate limiting
```

---

## 📚 Ссылки

- **Предыдущий этап**: `docs/notes/SESSION15_PHASE2E_COMPLETE.md`
- **Текущий API**: `tg_parser/api/main.py`
- **API Tests**: `tests/test_api.py`
- **FastAPI Security**: https://fastapi.tiangolo.com/tutorial/security/
- **SlowAPI**: https://github.com/laurentS/slowapi

---

## 🔮 После Phase 2F

| Этап | Название | Описание |
|------|----------|----------|
| **Phase 3A** | Multi-Agent | Специализированные агенты (cleaner, extractor, summarizer) |
| **Phase 3B** | RAG Integration | Векторный поиск, embeddings, knowledge base |
| **Phase 3C** | Web UI | Dashboard для управления обработкой |

---

**Готов к началу Phase 2F!**

