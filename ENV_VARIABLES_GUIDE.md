# Environment Variables Guide

**Version**: v3.1.0  
**Session**: 24 (PostgreSQL Support)  
**Date**: 29 декабря 2025

Complete reference for all environment variables in TG_parser.

---

## 📋 Quick Start

Copy this template to `.env`:

```bash
# =============================================================================
# Database Configuration (Session 24: PostgreSQL Support)
# =============================================================================

# Database type: "sqlite" (development) or "postgresql" (production)
DB_TYPE=sqlite

# --- SQLite Configuration (when DB_TYPE=sqlite) ---
INGESTION_STATE_DB_PATH=ingestion_state.sqlite
RAW_STORAGE_DB_PATH=raw_storage.sqlite
PROCESSING_STORAGE_DB_PATH=processing_storage.sqlite

# --- PostgreSQL Configuration (when DB_TYPE=postgresql) ---
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=your_secure_password

# --- Connection Pool Settings (PostgreSQL only) ---
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true

# =============================================================================
# LLM Provider Configuration
# =============================================================================

LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Optional: Override default model
# LLM_MODEL=gpt-4o-mini

# =============================================================================
# Telegram Credentials (for ingestion)
# =============================================================================

TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890

# =============================================================================
# Logging Configuration (Session 23)
# =============================================================================

# Log format: "text" for development, "json" for production
LOG_FORMAT=text

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# =============================================================================
# Retry Settings (Session 23)
# =============================================================================

# Maximum retry attempts (1-10)
RETRY_MAX_ATTEMPTS=3

# Base backoff delay in seconds (0.1-60.0)
RETRY_BACKOFF_BASE=1.0

# Maximum backoff delay in seconds (1.0-300.0)
RETRY_BACKOFF_MAX=60.0

# Jitter factor for randomization (0.0-1.0)
RETRY_JITTER=0.3

# =============================================================================
# GPT-5 / Responses API Configuration (Session 23)
# =============================================================================

# Reasoning effort for GPT-5 models: minimal, low, medium, high
LLM_REASONING_EFFORT=low

# Verbosity for GPT-5 models: low, medium, high
LLM_VERBOSITY=low

# =============================================================================
# Other LLM Providers (Optional)
# =============================================================================

# Anthropic Claude
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
# LLM_PROVIDER=gemini
# GEMINI_API_KEY=AIza...
# GOOGLE_API_KEY=AIza...  # Alias for GEMINI_API_KEY

# Ollama (local)
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://localhost:11434
# LLM_MODEL=llama3.2
```

---

## 📚 Variable Reference

### Database Configuration (Session 24)

#### `DB_TYPE`
- **Type**: string
- **Default**: `sqlite`
- **Values**: `sqlite`, `postgresql`
- **Description**: Database type to use
- **Production**: Use `postgresql` for production deployments

#### `INGESTION_STATE_DB_PATH`
- **Type**: path
- **Default**: `ingestion_state.sqlite`
- **Description**: Path to ingestion state SQLite database (used when `DB_TYPE=sqlite`)

#### `RAW_STORAGE_DB_PATH`
- **Type**: path
- **Default**: `raw_storage.sqlite`
- **Description**: Path to raw storage SQLite database (used when `DB_TYPE=sqlite`)

#### `PROCESSING_STORAGE_DB_PATH`
- **Type**: path
- **Default**: `processing_storage.sqlite`
- **Description**: Path to processing storage SQLite database (used when `DB_TYPE=sqlite`)

#### PostgreSQL Connection (when `DB_TYPE=postgresql`)

#### `DB_HOST`
- **Type**: string
- **Default**: `localhost`
- **Description**: PostgreSQL server hostname or IP address
- **Docker**: Use service name (e.g., `postgres`) when using Docker Compose

#### `DB_PORT`
- **Type**: integer
- **Default**: `5432`
- **Description**: PostgreSQL server port

#### `DB_NAME`
- **Type**: string
- **Default**: `tg_parser`
- **Description**: PostgreSQL database name

#### `DB_USER`
- **Type**: string
- **Default**: `tg_parser_user`
- **Description**: PostgreSQL user for authentication

#### `DB_PASSWORD`
- **Type**: string
- **Default**: *(empty)*
- **Required**: Yes (for PostgreSQL)
- **Description**: PostgreSQL password
- **Security**: Use strong passwords (32+ characters) in production

#### Connection Pool Settings (PostgreSQL only)

#### `DB_POOL_SIZE`
- **Type**: integer
- **Default**: `5`
- **Range**: 1-50
- **Description**: Base number of connections in the pool
- **Recommendation**: 
  - Development: 2-3
  - Production (light): 5-10
  - Production (heavy): 10-20

#### `DB_MAX_OVERFLOW`
- **Type**: integer
- **Default**: `10`
- **Range**: 0-50
- **Description**: Additional connections when pool is exhausted
- **Formula**: Total max connections = `DB_POOL_SIZE + DB_MAX_OVERFLOW`

#### `DB_POOL_TIMEOUT`
- **Type**: float
- **Default**: `30.0`
- **Range**: 1.0-300.0
- **Description**: Timeout in seconds to get a connection from pool
- **Recommendation**: 10-30 seconds for production

#### `DB_POOL_RECYCLE`
- **Type**: integer
- **Default**: `3600`
- **Range**: 60-7200
- **Description**: Recycle connections after N seconds (default: 1 hour)
- **Purpose**: Prevents stale connections and handles connection limits

#### `DB_POOL_PRE_PING`
- **Type**: boolean
- **Default**: `true`
- **Description**: Check connection health before using it
- **Recommendation**: Always `true` for production

---

### LLM Provider Configuration

#### `LLM_PROVIDER`
- **Type**: string
- **Default**: `openai`
- **Values**: `openai`, `anthropic`, `gemini`, `ollama`
- **Description**: LLM provider to use for processing

#### `LLM_MODEL`
- **Type**: string
- **Default**: Provider-specific
  - OpenAI: `gpt-4o-mini`
  - Anthropic: `claude-sonnet-4-20250514`
  - Gemini: `gemini-2.0-flash-exp`
  - Ollama: `llama3.2`
- **Description**: Override default model for the selected provider

#### `LLM_BASE_URL`
- **Type**: string
- **Default**: Provider-specific
- **Description**: Custom base URL for OpenAI-compatible proxies or Ollama

#### `LLM_TEMPERATURE`
- **Type**: float
- **Default**: `0.0`
- **Range**: 0.0-2.0
- **Description**: Temperature for LLM generation (0.0 = deterministic)

#### `LLM_MAX_TOKENS`
- **Type**: integer
- **Default**: `4096`
- **Description**: Maximum tokens for LLM response

---

### API Keys

#### `OPENAI_API_KEY`
- **Type**: string
- **Required**: If `LLM_PROVIDER=openai`
- **Format**: `sk-proj-...` or `sk-...`
- **Get it**: https://platform.openai.com/api-keys

#### `ANTHROPIC_API_KEY`
- **Type**: string
- **Required**: If `LLM_PROVIDER=anthropic`
- **Format**: `sk-ant-...`
- **Get it**: https://console.anthropic.com/

#### `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- **Type**: string
- **Required**: If `LLM_PROVIDER=gemini`
- **Format**: `AIza...`
- **Get it**: https://aistudio.google.com/app/apikey

---

### Logging Configuration (Session 23)

#### `LOG_FORMAT`
- **Type**: string
- **Default**: `text`
- **Values**: `text`, `json`
- **Description**: Log format
  - `text`: Human-readable, colored output (development)
  - `json`: Structured JSON logs (production)

#### `LOG_LEVEL`
- **Type**: string
- **Default**: `INFO`
- **Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Description**: Minimum log level to output

**Example (Production):**
```bash
LOG_FORMAT=json
LOG_LEVEL=INFO
```

**Example (Development):**
```bash
LOG_FORMAT=text
LOG_LEVEL=DEBUG
```

---

### Retry Settings (Session 23)

#### `RETRY_MAX_ATTEMPTS`
- **Type**: integer
- **Default**: `3`
- **Range**: 1-10
- **Description**: Maximum number of retry attempts for failed operations

#### `RETRY_BACKOFF_BASE`
- **Type**: float
- **Default**: `1.0`
- **Range**: 0.1-60.0
- **Description**: Base delay for exponential backoff (seconds)

#### `RETRY_BACKOFF_MAX`
- **Type**: float
- **Default**: `60.0`
- **Range**: 1.0-300.0
- **Description**: Maximum backoff delay cap (seconds)

#### `RETRY_JITTER`
- **Type**: float
- **Default**: `0.3`
- **Range**: 0.0-1.0
- **Description**: Jitter factor for randomizing delays (0.3 = 0-30% random jitter)

**Backoff Formula:**
```
delay = min(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)), RETRY_BACKOFF_MAX)
total_delay = delay + random(0, delay * RETRY_JITTER)
```

**Example:**
```bash
RETRY_MAX_ATTEMPTS=5
RETRY_BACKOFF_BASE=2.0
RETRY_BACKOFF_MAX=120.0
RETRY_JITTER=0.5
```

---

### GPT-5 / Responses API Configuration (Session 23)

#### `LLM_REASONING_EFFORT`
- **Type**: string
- **Default**: `low`
- **Values**: `minimal`, `low`, `medium`, `high`
- **Description**: Reasoning effort for GPT-5.* models (Responses API)
- **Note**: Only applies when `LLM_MODEL` starts with `gpt-5`

#### `LLM_VERBOSITY`
- **Type**: string
- **Default**: `low`
- **Values**: `low`, `medium`, `high`
- **Description**: Verbosity level for GPT-5.* models (Responses API)
- **Note**: Only applies when `LLM_MODEL` starts with `gpt-5`

**Example (GPT-5 with high reasoning):**
```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.2
LLM_REASONING_EFFORT=high
LLM_VERBOSITY=medium
```

---

### Telegram Credentials

#### `TELEGRAM_API_ID`
- **Type**: integer
- **Required**: For ingestion commands
- **Get it**: https://my.telegram.org/apps

#### `TELEGRAM_API_HASH`
- **Type**: string
- **Required**: For ingestion commands
- **Get it**: https://my.telegram.org/apps

#### `TELEGRAM_PHONE`
- **Type**: string
- **Required**: For ingestion commands
- **Format**: `+1234567890` (with country code)

#### `TELEGRAM_SESSION_NAME`
- **Type**: string
- **Default**: `tg_parser_session`
- **Description**: Session file name for Telethon

---

### Database Paths

#### `INGESTION_STATE_DB_PATH`
- **Type**: path
- **Default**: `ingestion_state.sqlite`

#### `RAW_STORAGE_DB_PATH`
- **Type**: path
- **Default**: `raw_storage.sqlite`

#### `PROCESSING_STORAGE_DB_PATH`
- **Type**: path
- **Default**: `processing_storage.sqlite`

---

### API Configuration

#### `API_KEY_REQUIRED`
- **Type**: boolean
- **Default**: `false`
- **Description**: Require X-API-Key header for API requests

#### `API_KEYS`
- **Type**: JSON object
- **Default**: `{}`
- **Format**: `{"key1": "client_name", "key2": "client_name2"}`
- **Example**:
```bash
API_KEY_REQUIRED=true
API_KEYS='{"sk-prod-abc123": "production", "sk-dev-xyz789": "development"}'
```

#### `RATE_LIMIT_ENABLED`
- **Type**: boolean
- **Default**: `true`
- **Description**: Enable rate limiting for API endpoints

#### `RATE_LIMIT_PROCESS`
- **Type**: string
- **Default**: `10/minute`
- **Description**: Rate limit for POST /api/v1/process

#### `CORS_ORIGINS`
- **Type**: JSON array
- **Default**: `["*"]`
- **Example**: `["http://localhost:3000", "https://myapp.com"]`

---

### Observability

#### `METRICS_ENABLED`
- **Type**: boolean
- **Default**: `true`
- **Description**: Enable Prometheus metrics at /metrics

#### `SCHEDULER_ENABLED`
- **Type**: boolean
- **Default**: `true`
- **Description**: Enable background scheduler for cleanup/health checks

#### `AGENT_PERSISTENCE_ENABLED`
- **Type**: boolean
- **Default**: `true`
- **Description**: Enable agent state persistence

---

## 🔍 How to Use Logs

### Development (Text Format)

```bash
LOG_FORMAT=text
LOG_LEVEL=DEBUG

# Run API
tg-parser api

# Logs appear colored and human-readable:
# 2025-12-29T12:34:56.789Z [info     ] request_started method=GET path=/health request_id=abc-123
```

### Production (JSON Format)

```bash
LOG_FORMAT=json
LOG_LEVEL=INFO

# Run in Docker
docker-compose up

# Logs are JSON (one object per line):
# {"timestamp":"2025-12-29T12:34:56.789Z","level":"info","event":"request_started","method":"GET","path":"/health","request_id":"abc-123"}
```

### Filtering JSON Logs with `jq`

```bash
# Show only errors
docker logs tg_parser | jq 'select(.level == "error")'

# Find logs for specific request_id
docker logs tg_parser | jq 'select(.request_id == "abc-123")'

# Show slow requests (>1000ms)
docker logs tg_parser | jq 'select(.duration_ms > 1000)'

# Count errors per hour
docker logs tg_parser | jq -r 'select(.level == "error") | .timestamp' | cut -c1-13 | uniq -c
```

---

## 📖 See Also

- [LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md) — LLM provider setup
- [USER_GUIDE.md](docs/USER_GUIDE.md) — User guide
- [README.md](README.md) — Main documentation

---

**Last Updated**: Session 23 (29 декабря 2025)

