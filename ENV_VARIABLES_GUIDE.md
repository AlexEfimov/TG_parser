# Environment Variables Guide

**Version**: v4.3  
**Last Updated**: April 2026

Complete reference for all environment variables in TG_parser.

---

## 📋 Quick Start

Copy this template to `.env`:

```bash
# =============================================================================
# Database Configuration (PostgreSQL + pgvector)
# =============================================================================

DB_HOST=localhost   # Use 'postgres' in Docker Compose
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=your_secure_password

# Connection Pool Settings (optional)
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
# Logging Configuration
# =============================================================================

# Log format: "text" for development, "json" for production
LOG_FORMAT=text

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# =============================================================================
# Retry Settings
# =============================================================================

# Maximum retry attempts (1-10)
RETRY_MAX_ATTEMPTS=3

# Base backoff delay in seconds (0.1-60.0)
RETRY_BACKOFF_BASE=1.0

# Maximum backoff delay in seconds (1.0-300.0)
RETRY_BACKOFF_MAX=60.0

# Jitter factor for randomization (0.0-1.0)
RETRY_JITTER=0.3

# Sprint D.1: Anthropic billing-block backoff (seconds, min 60)
BILLING_BLOCK_BACKOFF_S=3600

# =============================================================================
# GPT-5 / Responses API Configuration
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

# =============================================================================
# Per-Stage LLM Overrides (Optional)
# =============================================================================

# PROCESSING_LLM_PROVIDER=gemini
# PROCESSING_LLM_MODEL=gemini-2.0-flash-exp
# TOPICIZATION_LLM_PROVIDER=anthropic
# TOPICIZATION_LLM_MODEL=claude-sonnet-4-20250514
# RAG_LLM_PROVIDER=openai
# RAG_LLM_MODEL=gpt-4o

# =============================================================================
# Embedding (for semantic search / RAG)
# =============================================================================

# EMBEDDING_PROVIDER=openai
# EMBEDDING_MODEL=text-embedding-3-small
# EMBEDDING_BATCH_SIZE=100

# =============================================================================
# Hybrid Retrieval (F5-A Phase 1)
# =============================================================================

# HYBRID_ENABLED=true
# HYBRID_RRF_K=60
# FTS_LANGUAGES=russian,english

# =============================================================================
# RAG Relevance Tuning (F5-A Phase 2)
# =============================================================================

# FTS_MIN_RANK=0.0
# RAG_TOPIC_QUOTA=2
# RAG_SEARCH_OVERFETCH_FACTOR=2

# =============================================================================
# Deduplication (F5-A Phase 3)
# =============================================================================

# DEDUP_ENABLED=true
# DEDUP_STRIP_URL_QUERY=true

# =============================================================================
# Multi-Tenancy (F4)
# =============================================================================

# DEFAULT_MAX_CHANNELS=20

# =============================================================================
# MCP Server (AI-agent interface)
# =============================================================================

# MCP_TRANSPORT=streamable-http
# MCP_HOST=0.0.0.0
# MCP_PORT=8080
# MCP_AUTH_ENABLED=false
# MCP_AUTH_TOKENS='{}'

# =============================================================================
# Telegram Bot
# =============================================================================

# TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
# BOT_ALLOWED_USERS=123456789,987654321
# BOT_GEMINI_MODEL=gemini-2.5-flash
# BOT_REQUEST_TIMEOUT=60
# BOT_RATE_LIMIT=10

# =============================================================================
# Monitoring (Grafana)
# =============================================================================

# GRAFANA_ADMIN_USER=admin
# GRAFANA_ADMIN_PASSWORD=changeme
# GRAFANA_PORT=3000
```

---

## 📚 Variable Reference

### Database Configuration (PostgreSQL + pgvector)

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

### Logging Configuration

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

### Retry Settings

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

#### `BILLING_BLOCK_BACKOFF_S`
- **Type**: integer (seconds)
- **Default**: `3600` (1 hour)
- **Range**: ≥ 60
- **Description**: Sprint D.1 — pause window applied to a source when Anthropic returns a `400 invalid_request_error` with the `credit balance is too low` message. Pipeline retry-loops do **not** retry this error class (`AnthropicBillingError`); the scheduler instead:
  1. records the failed attempt with `source_attempts.failed_stage`,
  2. increments the Prometheus counter `tg_parser_anthropic_billing_block_total{stage=...}`,
  3. sets `sources.rate_limit_until = now + BILLING_BLOCK_BACKOFF_S` so the source is skipped on subsequent ticks until the operator tops up the Anthropic balance.

**Example:**
```bash
# Pause for 30 minutes after a billing block (useful in staging)
BILLING_BLOCK_BACKOFF_S=1800
```

---

### GPT-5 / Responses API Configuration

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

### Multi-Tenancy (F4)

User management with roles (`admin` / `user`), per-user channel ownership and limits. Existing deployments should run `tg-parser migrate-users` once after upgrade to map credentials from `API_KEYS`, `MCP_AUTH_TOKENS`, and `BOT_ALLOWED_USERS` into the new user model.

#### `DEFAULT_MAX_CHANNELS`
- **Type**: integer
- **Default**: `20`
- **Range**: ≥ 1
- **Description**: Default maximum number of channels a user can own. Applied when `users.max_channels` is NULL in the database (i.e. no per-user override has been set).
- **Used by**: `resolve_user_by_auth()`, `get_default_admin()`, `GET /api/v1/users/me`

**Example:**
```bash
DEFAULT_MAX_CHANNELS=50
```

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
- **Multi-Tenancy**: Keys listed here are also mapped to the admin user during `tg-parser migrate-users`. After migration, user resolution happens via DB lookup (SHA-256 hash of the key).
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

#### `RATE_LIMIT_EXPORT`
- **Type**: string
- **Default**: `20/minute`
- **Description**: Rate limit for POST /api/v1/export (applies to all export levels: `raw`, `processed`, `full`; see F2 Parse-Only Export in `docs/USER_GUIDE.md`). For large raw exports, prefer the CLI over the API.

#### `CORS_ORIGINS`
- **Type**: JSON array
- **Default**: `["*"]`
- **Example**: `["http://localhost:3000", "https://myapp.com"]`

---

### Per-Stage LLM Overrides

Override the global LLM provider/model for specific pipeline stages. Useful for running a cheaper model for processing and a stronger one for topicization.

#### `PROCESSING_LLM_PROVIDER`
- **Type**: string
- **Default**: *(falls back to `LLM_PROVIDER`)*
- **Values**: `openai`, `anthropic`, `gemini`, `ollama`
- **Description**: LLM provider for message processing stage

#### `PROCESSING_LLM_MODEL`
- **Type**: string
- **Default**: *(falls back to `LLM_MODEL`)*
- **Description**: Model override for processing stage (e.g. `claude-haiku-4-5-20251001`)

#### `TOPICIZATION_LLM_PROVIDER`
- **Type**: string
- **Default**: *(falls back to `LLM_PROVIDER`)*
- **Description**: LLM provider for topicization stage

#### `TOPICIZATION_LLM_MODEL`
- **Type**: string
- **Default**: *(falls back to `LLM_MODEL`)*
- **Description**: Model override for topicization stage (e.g. `claude-sonnet-4-20250514`)

#### `RAG_LLM_PROVIDER`
- **Type**: string
- **Default**: *(falls back to `LLM_PROVIDER`)*
- **Values**: `openai`, `anthropic`, `gemini`, `ollama`
- **Description**: LLM provider for RAG Q&A stage

#### `RAG_LLM_MODEL`
- **Type**: string
- **Default**: *(falls back to `LLM_MODEL`)*
- **Description**: Model override for RAG Q&A stage (e.g. `gpt-4o`)

---

### Embedding Configuration

#### `EMBEDDING_PROVIDER`
- **Type**: string
- **Default**: `openai`
- **Description**: Provider for generating text embeddings (search/RAG)

#### `EMBEDDING_MODEL`
- **Type**: string
- **Default**: `text-embedding-3-small`
- **Description**: Embedding model name

#### `EMBEDDING_BATCH_SIZE`
- **Type**: integer
- **Default**: `100`
- **Description**: Number of texts to embed per API call

---

### Hybrid Retrieval (F5-A Phase 1)

Hybrid retrieval combines keyword FTS (`ts_rank_cd`) with semantic pgvector
similarity and fuses the two ranked lists via Reciprocal Rank Fusion (RRF).
Use `mode` on the REST `/api/v1/search` and `/api/v1/ask` endpoints to
override per-request (`"semantic" | "keyword" | "hybrid"`).

#### `HYBRID_ENABLED`
- **Type**: boolean
- **Default**: `true`
- **Description**: Master switch for hybrid retrieval. When `false`, the
  service silently downgrades `mode="hybrid"` requests to `semantic` (useful
  for debugging or if FTS infrastructure is unavailable).

#### `HYBRID_RRF_K`
- **Type**: integer (>= 1)
- **Default**: `60`
- **Description**: Reciprocal Rank Fusion constant. Lower values increase
  discrimination between top-ranked hits; higher values flatten the curve.
  The canonical value from Cormack et al. (SIGIR 2009) is 60.

#### `FTS_LANGUAGES`
- **Type**: string (comma-separated)
- **Default**: `russian,english`
- **Description**: Informational — advertises the text-search configurations
  blended into the STORED `search_vector` columns (`simple` A + `russian` B
  + `english` B). Changing this value alone does NOT rebuild the tsvector;
  new languages require a migration.

**Migrations:** `d4e5f6a7b8c9` (`processed_documents.search_vector`) and
`e5f6a7b8c9d0` (`topic_cards.search_vector`). WARNING: `ADD COLUMN ...
GENERATED ... STORED` triggers a full table rewrite in PostgreSQL. Apply
during a maintenance window for production databases > 1M rows.

---

### RAG Relevance Tuning (F5-A Phase 2)

Fine-tune keyword cutoffs and topic/message quotas in the RAG pipeline. All
three settings are consumed inside `retrieval_service`: `fts_min_rank` is
forwarded to `emb_repo.keyword_search` on keyword/hybrid paths; `rag_topic_quota`
and `rag_search_overfetch_factor` drive `answer()` behaviour
(`_apply_type_quotas` + overfetch). Callers can override per-request via
`search(fts_min_rank=...)` / `answer(topic_quota=...)`.

#### `FTS_MIN_RANK`
- **Type**: float (>= 0.0)
- **Default**: `0.0`
- **Description**: Default `ts_rank_cd` cutoff for keyword search. `0.0`
  disables the cutoff (all hits are returned). Typical useful range for
  noisy corpora is `0.001`–`0.05`: raise this to drop marginal FTS matches
  from the keyword branch. The semantic branch is unaffected (it uses
  `threshold` for pgvector cosine cutoffs).

#### `RAG_TOPIC_QUOTA`
- **Type**: integer (0..20)
- **Default**: `2`
- **Description**: Number of topic cards reserved in the RAG context before
  filling the remainder with messages. `0` → topics disabled for RAG.
  Raise to `3–4` for overview-style questions; keep `2` for factual
  queries. Clamped to `limit` inside `answer()`.

#### `RAG_SEARCH_OVERFETCH_FACTOR`
- **Type**: integer (1..10)
- **Default**: `2`
- **Description**: `answer()` fetches `limit * factor` candidates from
  `search()` to give `_apply_type_quotas` headroom for the underflow
  fallback. Increasing this helps when the corpus skews toward one type
  (e.g. many messages, few topics) but doubles/triples retrieval work.

---

### Deduplication (F5-A Phase 3)

Content-hash deduplication in the processing pipeline. SHA-256 digest of
normalized `text_clean` (lowercase + whitespace-collapse + optional URL
query strip) is stored in `processed_documents.content_hash`. When the
pipeline sees a document whose hash already exists *in the same channel*,
the new message is skipped — it is neither upserted nor embedded.

| Variable | Type | Default | Description |
|---|---|---|---|
| `DEDUP_ENABLED` | bool | `true` | Enable SHA-256 content-hash dedup in the processing pipeline (within-channel scope). Set `false` to restore pre-Phase-3 behaviour. |
| `DEDUP_STRIP_URL_QUERY` | bool | `true` | Strip `?query` and `#fragment` from URLs before hashing — catches tracking-param-only variants (`?utm_*`, etc.). |

**Metric:** `tg_dedup_duplicates_detected_total{channel_id}` —
increments once per detected duplicate (single-path + batch-path).

**Backfill:** for data persisted before Phase 3, run
`tg_parser backfill-content-hash [--channel-id X] [--batch-size 500]
[--dry-run]` to populate `content_hash` for existing rows. Uses
cursor-style pagination (safe for large tables) and is idempotent.

---

### MCP Server Configuration

#### `MCP_TRANSPORT`
- **Type**: string
- **Default**: `stdio`
- **Values**: `stdio`, `streamable-http`
- **Description**: MCP transport protocol. Use `streamable-http` for production.

#### `MCP_HOST`
- **Type**: string
- **Default**: `127.0.0.1`
- **Description**: Host to bind MCP server (use `0.0.0.0` in Docker)

#### `MCP_PORT`
- **Type**: integer
- **Default**: `8080`
- **Description**: MCP server port

#### `MCP_PATH`
- **Type**: string
- **Default**: `/mcp`
- **Description**: HTTP path for MCP endpoint

#### `MCP_AUTH_ENABLED`
- **Type**: boolean
- **Default**: `false`
- **Description**: Enable bearer token authentication for MCP

#### `MCP_AUTH_TOKENS`
- **Type**: JSON object
- **Default**: `{}`
- **Format**: `{"token": "client_name"}`
- **Multi-Tenancy**: Tokens listed here are mapped to the admin user during `tg-parser migrate-users`. After migration, user resolution happens via DB lookup (SHA-256 hash of the token).
- **Example**: `{"sk-mcp-abc123": "production_agent"}`

---

### Telegram Bot Configuration

#### `TELEGRAM_BOT_TOKEN`
- **Type**: string
- **Required**: For bot service
- **Format**: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
- **Get it**: Create a bot via [@BotFather](https://t.me/BotFather)

#### `GEMINI_API_KEY`
- **Type**: string
- **Required**: For bot service (Gemini powers agent reasoning)
- **Get it**: https://aistudio.google.com/app/apikey

#### `BOT_ALLOWED_USERS`
- **Type**: comma-separated integers
- **Default**: *(empty — allows all users, dev only!)*
- **Description**: Allowlist of Telegram user IDs
- **Multi-Tenancy**: User IDs listed here are mapped to the admin user during `tg-parser migrate-users` as `telegram` auth type. After migration, bot identifies users via DB lookup by Telegram user ID.
- **Example**: `123456789,987654321`
- **Get your ID**: Send `/start` to [@userinfobot](https://t.me/userinfobot)

#### `BOT_GEMINI_MODEL`
- **Type**: string
- **Default**: `gemini-2.5-flash`
- **Description**: Gemini model for bot agent reasoning

#### `BOT_REQUEST_TIMEOUT`
- **Type**: integer
- **Default**: `60`
- **Description**: Timeout in seconds for agent processing

#### `BOT_RATE_LIMIT`
- **Type**: integer
- **Default**: `10`
- **Description**: Maximum requests per minute per user

---

### Monitoring (Grafana)

#### `GRAFANA_ADMIN_USER`
- **Type**: string
- **Default**: `admin`
- **Description**: Grafana admin username

#### `GRAFANA_ADMIN_PASSWORD`
- **Type**: string
- **Default**: `admin`
- **Description**: Grafana admin password (change in production!)

#### `GRAFANA_PORT`
- **Type**: integer
- **Default**: `3000`
- **Description**: Grafana HTTP port

---

### Docker Compose Port Overrides

Override default host port mappings when they conflict with other services on the host.

#### `API_PORT`
- **Type**: integer
- **Default**: `8000`
- **Description**: Host port for REST API (`127.0.0.1:API_PORT:8000`)

#### `MCP_PORT`
- **Type**: integer
- **Default**: `8080`
- **Description**: Host port for MCP server (`127.0.0.1:MCP_PORT:8080`)

#### `GRAFANA_PORT`
- **Type**: integer
- **Default**: `3000`
- **Description**: Host port for Grafana (`127.0.0.1:GRAFANA_PORT:3000`)

---

### Reverse Proxy (Caddy — Docker profile)

#### `DOMAIN_MCP`
- **Type**: string
- **Default**: `mcp.localhost`
- **Description**: Domain for MCP endpoint (Caddy auto-TLS)

#### `DOMAIN_API`
- **Type**: string
- **Default**: `api.localhost`
- **Description**: Domain for REST API (Caddy auto-TLS)

#### `DOMAIN_GRAFANA`
- **Type**: string
- **Default**: `grafana.localhost`
- **Description**: Domain for Grafana (Caddy auto-TLS)

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

### Scheduled Digests (F6)

#### `DIGEST_SCHEDULER_ENABLED`
- **Type**: boolean
- **Default**: `true`
- **Description**: Run digest cron jobs in the bot process (only the bot
  delivers digests; API/CLI daemon never send to avoid duplicates).

#### `DIGEST_DEFAULT_TIMEZONE`
- **Type**: string (`zoneinfo` key)
- **Default**: `Europe/Moscow`
- **Description**: Fallback timezone for new subscriptions when the user
  did not specify one.

#### `DIGEST_MAX_DOCS_PER_RUN`
- **Type**: integer
- **Default**: `50`
- **Description**: Per-channel cap on `ProcessedDocument`s included in one
  digest tick. Prevents an outlier-noisy channel from blowing the LLM
  budget. When `len(filtered) > cap`, the **oldest** slice is delivered and
  the cursor advances to the last delivered doc — leftover newer docs are
  picked up on the next tick (no message loss).

#### `DIGEST_FIRST_RUN_LOOKBACK_HOURS`
- **Type**: integer
- **Default**: `24`
- **Description**: Lookback window used when a subscription has no
  `last_digest_cursor` yet (first ever run).

#### `DIGEST_REFRESH_INTERVAL`
- **Type**: integer (seconds)
- **Default**: `60`
- **Description**: How often the bot reconciles its in-memory scheduler
  jobs against `digest_subscriptions` rows. Picks up subscriptions
  created/deleted via MCP (in another process) without restart.

#### `DIGEST_MESSAGE_MAX_CHARS`
- **Type**: integer
- **Default**: `4096`
- **Description**: Max characters per Telegram message before splitting.
  Telegram's hard limit is 4096; lower values create more parts.

#### `DIGEST_MAX_MESSAGE_PARTS`
- **Type**: integer
- **Default**: `10`
- **Description**: Max number of split parts before falling back to a
  `BufferedInputFile` (the full digest is sent as a `.md` attachment built
  in memory — no temp file on disk).

#### `DIGEST_LLM_PROVIDER`
- **Type**: string (`openai` | `anthropic` | `gemini` | `ollama`)
- **Default**: empty (falls back to `LLM_PROVIDER`)
- **Description**: Per-stage override for the digest summarization LLM.
  Can also be switched at runtime via
  `set_llm_config(scope="digest", provider=...)`.

#### `DIGEST_LLM_MODEL`
- **Type**: string
- **Default**: empty (falls back to `LLM_MODEL`)
- **Description**: Per-stage model override paired with
  `DIGEST_LLM_PROVIDER`.

### Evolving Topic Summaries (F5-C — Sprint, 2026-04-26)

When ≥ `RESUMMARIZE_TRIGGER_N` new supporting items have been
appended to a topic's bundle, the topic re-summarizes itself
(LLM call), re-embeds the result, and persists an append-only
`topic_card_versions` snapshot (audit trail). Triggered between
`run_topic_embedding(force=False)` and `run_watchlist_check_for_channel`
in every scheduler tick — F11 watchlist scoring runs against the
freshest summary. Default model is intentionally cheap
(`openai/gpt-4o-mini`) — F5-C is meant to keep summaries living
cheaply between full topicization runs.

#### `RESUMMARIZE_ENABLED`
- **Type**: boolean (`true` | `false`)
- **Default**: `true`
- **Description**: Kill-switch for the entire F5-C feature. When
  `false`, the scheduler hook becomes a no-op and the counter
  `new_items_since_last_summary` still increments (so re-enabling
  picks up where it left off).

#### `RESUMMARIZE_TRIGGER_N`
- **Type**: integer (`1` ≤ N ≤ `1000`)
- **Default**: `5`
- **Description**: Number of new supporting items before a topic
  becomes a re-summarize candidate. Lower = fresher summaries +
  more LLM cost.

#### `RESUMMARIZE_INPUT_WINDOW_N`
- **Type**: integer (`1` ≤ N ≤ `200`)
- **Default**: `10`
- **Description**: How many top-N items (sorted: anchors first,
  then top-score supports) feed the LLM input. Cap on prompt
  size; lower = cheaper but less context.

#### `RESUMMARIZE_MAX_PER_TICK`
- **Type**: integer (`1` ≤ N ≤ `200`)
- **Default**: `10`
- **Description**: Cap on topics re-summarized per scheduler tick
  per channel. Protects against backfill flood when a channel
  catches up after downtime.

#### `RESUMMARIZE_MAX_DURATION_S`
- **Type**: integer (`10` ≤ N ≤ `3600`)
- **Default**: `60`
- **Description**: Wall-clock cap (seconds) per scheduler tick.
  When hit, the run breaks out of the candidates loop and reports the
  early exit via the `cap_duration` key in the run summary
  (`run_for_channel(...)["skipped_breakdown"]`); remaining candidates
  are picked up on the next tick. Note: this is a **run-level**
  breakdown counter, not a per-topic outcome label — there is no
  `tg_resummarize_total{outcome="cap"}` series.

#### `RESUMMARIZE_MAX_TOKENS_PER_TICK`
- **Type**: integer (`1000` ≤ N ≤ `10_000_000`)
- **Default**: `50000`
- **Description**: Token cap per scheduler tick (input + output).
  Runaway-protection upper bound on cost. Like `MAX_DURATION_S`, hits
  are reported via `cap_tokens` in the run breakdown (run-level
  counter, not a per-topic metric outcome).

#### `RESUMMARIZE_LLM_PROVIDER`
- **Type**: string (`openai` | `anthropic` | `gemini` | `ollama`)
- **Default**: empty (falls back to `LLM_PROVIDER`)
- **Description**: Per-stage override for the re-summarize LLM.
  Can also be switched at runtime via
  `set_llm_config(scope="resummarize", provider=...)` without
  restart.

#### `RESUMMARIZE_LLM_MODEL`
- **Type**: string
- **Default**: empty (falls back to `LLM_MODEL`)
- **Description**: Per-stage model override paired with
  `RESUMMARIZE_LLM_PROVIDER`. Default `gpt-4o-mini` is ~100×
  cheaper than topicization Sonnet 4 (~$0.15/1M input tokens).

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
- [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) — Production deployment guide
- [SERVER_ARCHITECTURE.md](docs/SERVER_ARCHITECTURE.md) — Server architecture
- [README.md](README.md) — Main documentation

---

**Last Updated**: April 2026

