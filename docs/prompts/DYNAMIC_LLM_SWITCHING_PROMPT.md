# Session: Dynamic LLM Provider Switching

## Goal
Add the ability to switch LLM provider/model at runtime without container restart.

## Context
Currently LLM config is static — set via `.env` and read once at startup. Changing provider requires editing `.env` + `docker compose up -d`. This is slow and disruptive.

## Current Architecture
- `tg_parser/config/settings.py` — `Settings` singleton, loaded once at import time
- `tg_parser/processing/llm/factory.py` — `create_llm_client()` reads from settings
- `tg_parser/processing/llm/instrumented.py` — `InstrumentedLLMClient` wraps clients with metrics
- Per-stage overrides: `PROCESSING_LLM_PROVIDER/MODEL`, `TOPICIZATION_LLM_PROVIDER/MODEL`
- Available providers: `openai`, `anthropic`, `gemini`, `ollama`
- All API keys already in `.env` on server

## Requirements

### 1. MCP Tool: `set_llm_config`
- Change global or per-stage LLM provider/model at runtime
- Parameters: `scope` (global | processing | topicization), `provider`, `model` (optional)
- Validate: provider is supported, API key is available
- Persist to runtime state (not .env — that stays as default)
- Return current config after change

### 2. MCP Tool: `get_llm_config`
- Show current active LLM config (global + per-stage overrides)
- Show available providers and which have API keys configured

### 3. API Endpoints (optional)
- `GET /api/llm/config` — current config
- `PUT /api/llm/config` — update config

### 4. Implementation Approach
- Add a `RuntimeSettings` or `LLMConfigManager` singleton that wraps the static settings
- `create_llm_client()` reads from runtime config instead of static settings
- On change, new requests use the new provider; in-flight requests finish with the old one
- No need to recreate existing client instances — factory creates new ones per call

### 5. Safety
- Validate API key exists before switching
- Log all config changes
- Don't persist to .env (restart reverts to defaults — safe fallback)

## Files to Modify
- `tg_parser/config/settings.py` — add RuntimeSettings or LLMConfigManager
- `tg_parser/processing/llm/factory.py` — read from runtime config
- `tg_parser/mcp_server.py` — add `set_llm_config` and `get_llm_config` tools
- `tg_parser/api/routes/` — optional API endpoints
- `tests/` — test switching logic

## Out of Scope
- Persistent config changes (editing .env)
- Hot-reload of non-LLM settings
- Provider-specific rate limit adjustments on switch
