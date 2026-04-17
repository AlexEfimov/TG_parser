# TG_parser — MCP Agent Guide

**Version:** 4.3 | **Tools:** 24 | **Transport:** Streamable HTTP | **Auth:** Bearer token

This guide is optimized for AI agents interacting with TG_parser via MCP. For human-oriented documentation, see [USER_GUIDE.md](USER_GUIDE.md).

---

## Connection

```
URL: https://<host>/mcp
Transport: streamable-http
Auth: Bearer <MCP_AUTH_TOKEN>
```

---

## Tools by Category

### Search & Q&A

| Tool | Auth | Description |
|------|------|-------------|
| `search_knowledge_base` | any | Semantic search over processed documents |
| `ask_question` | any | RAG-powered Q&A with source citations |

### Navigation

| Tool | Auth | Description |
|------|------|-------------|
| `list_topics` | any | Paginated topic list (offset/limit) |
| `get_topic_details` | any | Full topic card with anchors and items |
| `list_channels` | any | Channel overview: status, counts, coverage |
| `get_document` | any | Full document by `source_ref` |

### Cross-channel Analytics

| Tool | Auth | Description |
|------|------|-------------|
| `get_cross_channel_stats` | any | Topic counts, coverage, keyword overlaps |
| `get_related_topics` | any | Related topics across channels by similarity |

### Channel Management

| Tool | Auth | Description |
|------|------|-------------|
| `add_channel` | any | Connect a new Telegram channel |
| `pause_channel` | any | Pause ingestion for a channel |
| `resume_channel` | any | Resume paused channel |
| `remove_channel` | owner/admin | Permanently delete channel and all its data |

### Pipeline Control

| Tool | Auth | Description |
|------|------|-------------|
| `trigger_pipeline` | any | Start ingestion+processing for a channel |
| `get_pipeline_status` | any | Scheduler status and per-source pipeline state |

### LLM Configuration

| Tool | Auth | Description |
|------|------|-------------|
| `get_llm_config` | any | View current provider/model per stage |
| `set_llm_config` | admin | Switch provider/model at runtime |
| `reset_llm_config` | admin | Revert to .env defaults |

### User Management (F4)

| Tool | Auth | Description |
|------|------|-------------|
| `register_user` | admin | Create a new user |
| `update_user` | admin | Update name, role, max_channels |
| `list_users` | admin | List all users with channel counts |
| `whoami` | any | Current user profile + channels |
| `add_user_auth` | admin | Add auth mapping (api_key/mcp_token/telegram) |
| `remove_user_auth` | admin | Remove auth mapping by ID |

### Prompt Management

| Tool | Auth | Description |
|------|------|-------------|
| `reload_prompts` | admin | Reload prompt YAML files without restart |

All LLM prompts are stored in YAML files (`prompts/` directory): `processing.yaml`, `topicization.yaml`, `rag.yaml`, `bot.yaml`, `merge.yaml`, `incremental_discover.yaml`. Each file contains `system.prompt`, `user.template`, and `model` settings (temperature, max_tokens). Edit YAML files and call `reload_prompts` to apply changes at runtime without restart. Custom prompts directory can be set via `PROMPTS_DIR` env var.

Per-stage LLM provider/model can be overridden via env vars: `RAG_LLM_PROVIDER`/`RAG_LLM_MODEL`, `PROCESSING_LLM_PROVIDER`/`PROCESSING_LLM_MODEL`, `TOPICIZATION_LLM_PROVIDER`/`TOPICIZATION_LLM_MODEL`, or at runtime via `set_llm_config`.

---

## Tool Schemas

### `search_knowledge_base`

```
Parameters:
  query: str                    # Search query (natural language)
  channel_id: str | null        # Filter by channel (optional)
  limit: int = 10               # Max results

Returns: list[SearchResultItem]
  source_ref: str
  score: float
  summary: str | null
  text_preview: str | null
  channel_id: str | null
```

### `ask_question`

```
Parameters:
  question: str                 # Natural language question
  channel_id: str | null        # Filter by channel (optional)

Returns: AnswerResultItem
  answer: str
  sources: list[SearchResultItem]
  model: str | null
```

### `list_topics`

```
Parameters:
  channel_id: str | null        # Filter by channel (optional)
  topic_type: str | null        # Filter by type: "singleton" | "cluster" (optional)
  offset: int = 0
  limit: int = 50

Returns: TopicListResult
  total: int
  offset: int
  limit: int
  has_more: bool
  items: list[TopicSummary]     # id, title, type, summary, items_count, sources
```

### `get_topic_details`

```
Parameters:
  topic_id: str                 # Topic ID from list_topics

Returns: TopicDetail
  id, title, type, summary, scope_in, scope_out, anchors, sources, tags, related_topics, items
```

### `list_channels`

```
Parameters: (none)

Returns: list[ChannelSummary]
  channel_id: str
  channel_username: str | null
  status: str                   # "active" | "paused" | "error"
  raw_messages: int
  processed_documents: int
  topics_count: int
  coverage_percent: float
```

### `get_document`

```
Parameters:
  source_ref: str               # Document ID (e.g. "tg:channel:post:123")

Returns: DocumentDetail
  id, source_ref, channel_id, text_clean, summary, topics
```

### `get_cross_channel_stats`

```
Parameters:
  channel_id: str | null        # null = cross-channel overview

Returns: CrossChannelStatsResult
  # Cross-channel mode: total_documents, total_topics, channels, keyword_overlaps, overlap_count
  # Single-channel mode: channel_id, processed_documents, topics_count, coverage_percent, all_keywords
```

### `get_related_topics`

```
Parameters:
  topic_id: str

Returns: list[RelatedTopicItem]
  topic_id, title, channel_id, similarity_score, shared_keywords
```

### `add_channel`

```
Parameters:
  channel_id: str               # Telegram channel ID or @username (without @)
  channel_username: str | null
  include_comments: bool = false
  batch_size: int = 100

Returns: AddChannelResult
  channel_id, source_id, status, created: bool, message
```

### `pause_channel` / `resume_channel`

```
Parameters:
  channel_id: str

Returns: ChannelStatusResult
  channel_id, status, previous_status, changed: bool, message
```

### `remove_channel`

```
Parameters:
  channel_id: str
  confirm: bool = false         # Must be true to proceed

Returns: RemoveChannelResult
  channel_id, removed: bool, message
  details: {embeddings, processed_documents, processing_failures,
            topic_cards, topic_bundles, api_jobs, task_history,
            raw_messages, source} — counts of deleted records per table
```

### `trigger_pipeline`

```
Parameters:
  channel_id: str
  force: bool = false           # Re-process already-processed documents

Returns: TriggerPipelineResult
  channel_id, triggered: bool, message
```

### `get_pipeline_status`

```
Parameters:
  channel_id: str | null        # Filter to a specific channel (optional)

Returns: PipelineStatusResult
  scheduler_enabled: bool
  default_interval_seconds: int
  sources: list[PipelineSourceStatus]
    # source_id, channel_id, status, last_attempt_at, last_success_at, fail_count, last_error
```

### `get_llm_config`

```
Parameters: (none)

Returns: LLMConfigResult
  config:
    global: {provider, model, overridden}
    stages: {processing: {...}, topicization: {...}, rag: {...}}
    available_providers: {openai: bool, anthropic: bool, gemini: bool, ollama: bool}
    runtime_overrides: dict
```

### `set_llm_config`

```
Parameters:
  scope: str                    # "global" | "processing" | "topicization" | "rag"
  provider: str                 # "openai" | "anthropic" | "gemini" | "ollama"
  model: str | null
  temperature: float | null
  max_tokens: int | null

Returns: LLMConfigSetResult
  success: bool, message, config: LLMConfigResult
```

### `reset_llm_config`

```
Parameters:
  scope: str | null             # null = reset all scopes

Returns: LLMConfigSetResult
  success: bool, message, config: LLMConfigResult
```

### `register_user`

```
Parameters:
  name: str
  role: str = "user"            # "admin" | "user"
  max_channels: int | null      # null = use DEFAULT_MAX_CHANNELS

Returns: RegisterUserResult
  success: bool, user_id: str | null, message
```

### `update_user`

```
Parameters:
  user_id: str
  name: str | null              # Only provided fields are changed
  role: str | null
  max_channels: int | null
  reset_max_channels: bool = false  # true = set max_channels to null (global default)

Returns: UpdateUserResult
  success: bool, message
```

### `list_users`

```
Parameters: (none)

Returns: ListUsersResult
  success: bool
  users: list[UserInfo]
    # id, name, role, max_channels, owned_channels_count
  message: str
```

### `whoami`

```
Parameters: (none)

Returns: WhoamiResult
  id, name, role, max_channels: int, owned_channels: list[str], owned_channels_count: int
```

### `add_user_auth`

```
Parameters:
  user_id: str
  auth_type: str                # "api_key" | "telegram" | "mcp_token"
  identifier: str               # Raw value; auto-hashed for api_key/mcp_token
  client_name: str | null

Returns: AddUserAuthResult
  success: bool, mapping_id: str | null, message
```

### `remove_user_auth`

```
Parameters:
  mapping_id: str               # Mapping ID from add_user_auth response

Returns: RemoveUserAuthResult
  success: bool, message
```

### `reload_prompts`

```
Parameters:
  name: str | null              # Prompt name (null = reload ALL)
                                # Values: rag, bot, processing, topicization,
                                #         incremental_discover, merge, supporting_items

Returns: dict
  success: bool, reloaded: str   # prompt name or "all"
```

---

## Common Workflows

### 1. Add a channel and start processing

```
1. add_channel(channel_id="mychannel")
2. trigger_pipeline(channel_id="mychannel")
3. get_pipeline_status()                    # poll until complete
4. list_topics(channel_id="mychannel")      # browse results
```

### 2. Search and Q&A

```
1. search_knowledge_base(query="vitamin D deficiency treatment")
2. ask_question(question="What are the latest recommendations for vitamin D supplementation?")
```

### 3. Cross-channel analysis

```
1. list_channels()                          # see all channels
2. get_cross_channel_stats()                # overview with keyword overlaps
3. get_related_topics(topic_id="topic:...")  # find linked topics
```

### 4. User management (admin)

```
1. whoami()                                  # verify admin role
2. register_user(name="analyst", role="user", max_channels=5)
3. add_user_auth(user_id="<id>", auth_type="api_key", identifier="sk-new-key-123")
4. list_users()                              # verify
```

### 5. Switch LLM provider at runtime

```
1. get_llm_config()                         # see current config + available providers
2. set_llm_config(scope="processing", provider="gemini", model="gemini-2.5-flash")
3. trigger_pipeline(channel_id="mychannel") # uses new provider
4. reset_llm_config()                       # revert to .env defaults
```

---

## Auth Model

| Auth type | Identifier stored | Used by |
|-----------|------------------|---------|
| `api_key` | SHA-256(raw_key) | REST API (`X-API-Key` header) |
| `mcp_token` | SHA-256(raw_token) | MCP Server (`Bearer` token) |
| `telegram` | Plain user ID string | Telegram Bot |

Roles:
- **admin**: full access to all channels and all tools
- **user**: access only to owned channels; `register_user`, `update_user`, `list_users`, `add_user_auth`, `remove_user_auth`, `set_llm_config`, `reset_llm_config`, `reload_prompts` are admin-only; `remove_channel` requires channel ownership or admin

---

## Error Handling

Admin-only tools return `{success: false, message: "Admin access required"}` when called by non-admin users. Tools that look up entities return `{success: false, message: "... not found"}` when the target doesn't exist.

Channel-scoped tools enforce ownership: non-admin users can only access channels where `owner_id` matches their user ID. Attempting to access another user's channel raises `PermissionDenied`.

---

## REST API Endpoints (alternative to MCP)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | Health check |
| `GET` | `/status` | — | Basic status |
| `GET` | `/status/detailed` | api_key | Detailed status |
| `GET` | `/scheduler` | api_key | Scheduler state |
| `GET` | `/metrics` | — | Prometheus metrics |
| `POST` | `/api/v1/process` | any | Trigger processing job |
| `GET` | `/api/v1/status/{job_id}` | any | Job status |
| `GET` | `/api/v1/jobs` | any | List jobs |
| `POST` | `/api/v1/export` | any | Trigger export |
| `GET` | `/api/v1/export/status/{job_id}` | any | Export job status |
| `GET` | `/api/v1/export/download/{job_id}` | any | Download export |
| `POST` | `/api/v1/search` | any | Semantic search |
| `POST` | `/api/v1/ask` | any | RAG Q&A |
| `GET` | `/api/v1/topics` | any | List topics (pagination, filters) |
| `GET` | `/api/v1/topics/{topic_id}` | any | Topic details |
| `GET` | `/api/v1/topics/{topic_id}/bundle` | any | Topic bundle |
| `GET` | `/api/v1/channels` | any | List channels |
| `GET` | `/api/v1/channels/{channel_id}/stats` | owner/admin | Channel stats |
| `GET` | `/api/v1/documents` | any | Document by `source_ref` query param |
| `GET` | `/llm/config` | any | LLM configuration |
| `PUT` | `/llm/config` | admin | Set LLM provider/model |
| `POST` | `/llm/config/reset` | admin | Reset LLM config to defaults |
| `GET` | `/api/v1/agents` | admin | List agents |
| `GET` | `/api/v1/agents/{name}` | admin | Agent details |
| `GET` | `/api/v1/agents/{name}/stats` | admin | Agent stats |
| `GET` | `/api/v1/agents/{name}/history` | admin | Agent history |
| `GET` | `/api/v1/agents/stats/handoffs` | admin | Agent handoff stats |
| `GET` | `/api/v1/users/me` | any | Current user profile |
| `GET` | `/api/v1/users` | admin | List users |
| `POST` | `/api/v1/users` | admin | Create user |
| `PATCH` | `/api/v1/users/{user_id}` | admin | Update user |
| `DELETE` | `/api/v1/users/{user_id}` | admin | Delete user + auth mappings |

---

**Version:** 4.3 | **Last updated:** April 2026
