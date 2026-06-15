# TG_parser — MCP Agent Guide

**Version:** 4.4.0 | **Tools:** 43 | **Transport:** Streamable HTTP | **Auth:** Bearer token

This guide is optimized for AI agents interacting with TG_parser via MCP. For human-oriented documentation, see [USER_GUIDE.md](USER_GUIDE.md) and [GETTING_STARTED.md](GETTING_STARTED.md).

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
| `search_knowledge_base` | any | Hybrid (FTS + pgvector) search over processed documents |
| `ask_question` | any | RAG-powered Q&A with source citations (hybrid retrieval) |

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
| `trigger_pipeline` | any | Queue full pipeline on `tg_parser` (HTTP dispatch) |
| `trigger_topicization` | any | Queue topicization for a channel |
| `trigger_link_topics` | any | Queue cross-channel topic linking (RBAC via `channel_id`) |
| `get_pipeline_status` | any | Scheduler status and per-source pipeline state |

### Export (F2)

| Tool | Auth | Description |
|------|------|-------------|
| `export_channel` | owner/admin | Submit export job for a channel (level=raw/processed/full) |
| `get_export_status` | owner/admin | Poll job status + download URL when completed |

### Digests (F6)

| Tool | Auth | Description |
|------|------|-------------|
| `subscribe_digest` | owner/admin | Create a cron-driven digest subscription delivering to a Telegram chat |
| `list_digests` | any | List subscriptions (admin: all; user: own only) |
| `unsubscribe_digest` | owner/admin | Delete a subscription and unregister its scheduler job |

### Topic Watchlist (F11)

| Tool | Auth | Description |
|------|------|-------------|
| `subscribe_watchlist` | owner/admin | Create a persistent thematic alert (hybrid keyword+semantic). Channels are checked via `assert_channel_access`; chat_id receives instant pushes after each scheduler tick. |
| `list_watchlists` | any | List interests (admin: all; user: own only). Inactive (soft-deleted) interests are included so callers can audit / re-create them. |
| `unsubscribe_watchlist` | owner/admin | Soft-delete an interest by id. Match history (`watch_matches`) is preserved. |
| `get_watchlist_matches` | owner/admin | Return saved matches for an interest, optionally filtered via `since_iso` (ISO-8601). Use for incremental polling without dropping the persistent log. |
| `backfill_watchlist` | owner/admin | Retroactively score an interest against historical `processed_documents` (the scheduler only scores per-tick new docs, so a corpus ingested before the interest existed is never matched). Dry-run by default; idempotent; capped at 2000 docs. |

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

### Workspaces (F4-B Core)

Workspaces are thematic collections of the caller's channels — a scope-narrowing overlay over F4-A multi-tenancy. All 8 scoped read tools (`search_knowledge_base`, `ask_question`, `list_topics`, `get_topic_details`, `list_channels`, `get_document`, `get_related_topics`, `get_cross_channel_stats`) accept an optional `workspace_id` parameter. Omitting it or passing `null` preserves F4-A behavior bit-for-bit; unknown / foreign `workspace_id` returns an empty / 404-like result and never leaks workspace existence.

| Tool | Auth | Description |
|------|------|-------------|
| `list_workspaces` | any | List the caller's workspaces. Owner-scoped. |
| `create_workspace` | any | Create a new workspace (UNIQUE per `(owner_id, name)`). |
| `rename_workspace` | any | Rename a workspace (ownership-checked). |
| `delete_workspace` | any | Delete a workspace; `ON DELETE CASCADE` removes M2M membership; sources preserved. |
| `add_workspace_source` | any | Attach a channel to a workspace (idempotent via `ON CONFLICT DO NOTHING`). |
| `remove_workspace_source` | any | Detach a channel from a workspace (M2M row only; source remains). |
| `list_workspace_sources` | any | List `channel_id`s attached to a workspace. |
| `list_all_workspaces` | admin | Admin-only: list every workspace, optionally filtered by `owner_id`. |

> **Q4 R2 — non-atomic move.** Moving a channel between workspaces is the documented pair `remove_workspace_source(from_ws, ch)` + `add_workspace_source(to_ws, ch)`. The two calls are **not atomic** (O-1 deferred per `PARITY_DECISION_TRACKING.md § 3`); concurrent reads during the gap window may see the channel only through the null-workspace scope.

> **Q4 R3 — full-bundle in get-details.** `get_topic_details(topic_id, workspace_id=...)` and `get_document(source_ref, workspace_id=...)` return the full bundle / document regardless of workspace scope. `workspace_id` is used only as a 404-guard on the workspace itself; workspaces narrow list/search results, not access-control on get-details.

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
  mode: str = "hybrid"          # "semantic" | "keyword" | "hybrid"
  workspace_id: str | null = None  # F4-B: optional workspace scope; null = F4-A bit-for-bit

Returns: list[SearchResultItem]
  source_ref: str
  score: float
  summary: str | null
  text_preview: str | null
  channel_id: str | null
```

**Retrieval mode:** Since F5-A Phase 2, `mode` is forwarded through the MCP
wrapper into the retrieval service. Values: `semantic` (pgvector cosine
only), `keyword` (PostgreSQL FTS `ts_rank_cd` only), `hybrid` (both via
Reciprocal Rank Fusion; default). Invalid values raise `ValueError`.

> **Deduplication (F5-A Phase 3):** duplicate messages (exact text within a
> channel, detected via SHA-256 content-hash) are filtered at processing
> time and never appear in search results. See `USER_GUIDE.md` §
> Deduplication.

### `ask_question`

```
Parameters:
  question: str                 # Natural language question
  channel_id: str | null        # Filter by channel (optional)
  mode: str = "hybrid"          # "semantic" | "keyword" | "hybrid"
  workspace_id: str | null = None  # F4-B: optional workspace scope; null = F4-A bit-for-bit

Returns: AnswerResultItem
  answer: str
  sources: list[SearchResultItem]
  model: str | null
```

**Context structure (F5-A Phase 2):** The underlying RAG pipeline now
assembles the LLM context from two optional sections — `## Related Topics`
(topic cards, prefixed `[T1]`, `[T2]`, …) and `## Source Messages`
(individual posts, prefixed `[M1]`, `[M2]`, …). The bracket indices are
visual labels; the LLM is instructed to cite via the `ref` value (e.g.
`[tg:channel:post:123]`). Topic-weighted quotas (`RAG_TOPIC_QUOTA`) and
overfetch (`RAG_SEARCH_OVERFETCH_FACTOR`) are configurable via env vars —
see `USER_GUIDE.md` → “RAG Context Structure & Type Quotas”.

### `list_topics`

```
Parameters:
  channel_id: str | null        # Filter by channel (optional)
  topic_type: str | null        # Filter by type: "singleton" | "cluster" (optional)
  offset: int = 0
  limit: int = 50
  workspace_id: str | null = None  # F4-B: optional workspace scope; null = F4-A bit-for-bit

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
  workspace_id: str | null = None  # F4-B: optional 404-guard; bundle returned in full
                                   # (Q4 R3: workspace narrows list/search, NOT access-control
                                   # on get-details). Unknown / foreign workspace_id → 404-like
                                   # 'not found' message.

Returns: TopicDetail
  id, title, type, summary, scope_in, scope_out, anchors, sources, tags, related_topics, items
```

> **Q4 R3 — full-bundle.** The bundle items are returned in full regardless of `workspace_id`; workspaces narrow list/search results, not access-control on get-details. Use `workspace_id` here only as a guard against accessing a foreign / unknown workspace (returns "Topic not found" instead of leaking existence).

### `list_channels`

```
Parameters:
  workspace_id: str | null = None  # F4-B: optional workspace scope; null = F4-A bit-for-bit

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
  workspace_id: str | null = None  # F4-B: optional 404-guard; document returned in full
                                   # (Q4 R3: workspace narrows list/search, NOT access-control
                                   # on get-details). Unknown / foreign workspace_id → 404-like
                                   # 'not found' message.

Returns: DocumentDetail
  id, source_ref, channel_id, text_clean, summary, topics
```

> **Q4 R3 — full-document.** The document is returned in full regardless of `workspace_id`; workspaces narrow list/search results, not access-control on get-details. Use `workspace_id` here only as a guard against accessing a foreign / unknown workspace (returns "Document not found" instead of leaking existence).

### `get_cross_channel_stats`

```
Parameters:
  channel_id: str | null        # null = cross-channel overview
  workspace_id: str | null = None  # F4-B: optional workspace scope; null = F4-A bit-for-bit

Returns: CrossChannelStatsResult
  # Cross-channel mode: total_documents, total_topics, channels, keyword_overlaps, overlap_count
  # Single-channel mode: channel_id, processed_documents, topics_count, coverage_percent, all_keywords
```

### `get_related_topics`

```
Parameters:
  topic_id: str
  workspace_id: str | null = None  # F4-B: optional workspace scope; null = F4-A bit-for-bit

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
  channel_id, triggered: bool, message, error_class?, job_id?, job?

Dispatches to `POST /api/v1/pipeline/trigger` on the `tg_parser` container.
`triggered: false` with `error_class` means no job was queued (never assume
success without `triggered: true` and a `job_id`).
```

### `trigger_topicization` / `trigger_link_topics`

Same result shape as `trigger_pipeline`; `job` is `topicization` or
`link_topics`. `link_topics` uses `channel_id` for access control only.

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

### `export_channel`

```
Parameters:
  channel_id: str                # Required. Channel to export.
  level: str = "raw"             # "raw" | "processed" | "full" (default: raw)
  format: str = "json"           # "json" | "ndjson" (for level=raw; ignored for processed/full)
  from_date: str | null          # ISO-8601 UTC datetime filter (optional)
  to_date: str | null            # ISO-8601 UTC datetime filter (optional)

Returns: ExportChannelResult
  job_id: str | null             # null if rejected
  status: str                    # "pending" | "rejected"
  channel_id: str
  level: str
  format: str
  download_url: str | null       # populated after job completes (via get_export_status)
  message: str                   # human-readable status line
```

Behaviour:

- `level="raw"` requires non-empty `channel_id` (per-channel export only in F2).
- Ownership is enforced via `assert_channel_access` — non-owners get a rejected result.
- Invalid `level` / `format` raises `ValueError`.
- The job runs in the background; poll `get_export_status(job_id)` until
  `status="completed"`, then fetch the file via `download_url`
  (`GET /api/v1/export/download/{job_id}`).

### `get_export_status`

```
Parameters:
  job_id: str                    # Required.

Returns: ExportStatusResult
  job_id: str
  status: str                    # "pending" | "running" | "completed" | "failed"
  channel_id: str | null
  level: str                     # "raw" | "processed" | "full"
  format: str                    # "json" | "ndjson"
  download_url: str | null       # populated when status == "completed"
  error: str | null              # populated when status == "failed"
```

### `subscribe_digest`

```
Parameters:
  name: str                      # Human label, e.g. "morning brief"
  channel_ids: list[str]         # Non-empty; each must pass assert_channel_access
  chat_id: int | null            # Legacy: Telegram chat to deliver into (mutually exclusive with target)
  target: dict | null            # ADR 0008 polymorphic target (mutually exclusive with chat_id)
  cron_expression: str = "0 9 * * *"
  timezone: str = "Europe/Moscow"  # any zoneinfo key (UTC, Europe/Moscow, ...)
  format: str = "summary"        # "summary" | "bullets" | "detailed"
  language: str = "ru"           # ISO-639-1 hint forwarded to the LLM

Returns: SubscribeDigestResult
  success: bool
  message: str
  subscription: DigestSubscriptionInfo | null  # `target_kind`, `chat_id`, `channel_id`
```

- **Delivery target (ADR 0008, Wave 1 step 4).** Pass either legacy
  `chat_id: int` OR new polymorphic `target: dict`. Exactly one of the
  two is required; supplying both returns
  `success=false, message="provide one of chat_id (legacy) or target (new)"`
  (validation error, no 500).
- `target` shape (discriminated union, validated against
  `docs/contracts/subscription_target.schema.json`):
  - `{"kind": "chat", "chat_id": <int>}` — deliver into a private chat,
    group, or supergroup. Equivalent to passing legacy `chat_id`
    alone.
  - `{"kind": "channel", "channel_id": "@username" | "-100..."}` —
    publish into a Telegram channel via `bot.send_message`. **The bot
    must be a channel admin** with «Post Messages» permission.
- **Channel publish best-effort (OQ#3).** On the first publish attempt
  that returns a permanent error (`bot is not a member`, `not enough
  rights`, `chat not found`, `forbidden`, etc.) the subscription is
  **soft-deactivated** (`is_active=false`) and the metric
  `tg_digest_channel_publish_total{result="permission_denied"}` is
  incremented. If `chat_id` was also stored on the row (legacy /
  fallback owner DM), the bot tries to deliver a one-line notice
  ("Digest «<name>» deactivated: bot cannot publish to channel
  <channel_id>…") to it. Transient errors increment
  `{result="failed"}` and re-raise without deactivating, so the next
  scheduler tick retries.
- The resolved target is exposed on the response via three fields
  (`subscription.target_kind ∈ {"chat", "channel"}`,
  `subscription.chat_id: int | null`, `subscription.channel_id: str |
  null`) — not as a nested `subscription.target` dict — so callers can
  confirm what was stored without round-tripping through
  `list_digests`.
- Cron is validated via `CronTrigger.from_crontab(...)`; invalid expressions
  produce `success=false` with a human-readable message (no 500).
- Timezone is validated via `zoneinfo.ZoneInfo(...)`; bad zones return a
  similar 4xx-style error.
- For each `channel_id`, ownership is enforced through
  `assert_channel_access(user, channel_id)`; non-owners get rejected.
- The subscription is persisted to `digest_subscriptions` and immediately
  registered with the bot-process scheduler (or picked up via the next
  reconciliation tick, every `DIGEST_REFRESH_INTERVAL` seconds).

### `list_digests`

```
Parameters: (none)

Returns: ListDigestsResult
  count: int
  subscriptions: list[DigestSubscriptionInfo]
```

- Admin sees all subscriptions across users (active + paused).
- Non-admin sees only subscriptions whose `owner_id == current_user.id`.

### `unsubscribe_digest`

```
Parameters:
  subscription_id: str           # UUID

Returns: UnsubscribeDigestResult
  success: bool
  message: str
  subscription_id: str | null
```

- Returns `success=false, message="not found"` if the subscription does not
  exist.
- Non-admin can only unsubscribe their own subscriptions; cross-owner
  attempts are rejected with `success=false`.
- On success the scheduler job is unregistered and the row is deleted.

### `subscribe_watchlist`

```
Parameters:
  title: str                     # Short label, used in push notifications
  channel_ids: list[str]         # Non-empty; each must pass assert_channel_access
  chat_id: int | null            # Legacy: Telegram chat to deliver pushes (mutually exclusive with target)
  target: dict | null            # ADR 0008 polymorphic target (mutually exclusive with chat_id)
  keywords: list[str] | null = []        # Positive overlap tokens
  description: str | null = null         # Free-form text used as embedding source
  exclude_keywords: list[str] | null = [] # Negative filter; any match zeros the score
  threshold: float = 0.6         # Combined-score cutoff in [0, 1]

Returns: SubscribeWatchlistResult
  success: bool
  message: str
  interest: WatchInterestInfo | null  # `target_kind`, `chat_id`, `channel_id`
```

- **Delivery target (ADR 0008).** Same discriminator as
  `subscribe_digest`: pass either `chat_id: int` (legacy) or
  `target: {"kind": "chat", "chat_id": <int>} |
  {"kind": "channel", "channel_id": "@username" | "-100..."}`. Exactly
  one of the two is required; supplying both returns
  `success=false` with a `provide one of chat_id (legacy) or target
  (new)` validation message. The resolved target is exposed on
  `interest` via the same three-field pattern as `subscribe_digest`
  (`target_kind`, `chat_id`, `channel_id`).
- For `target.kind="channel"` the bot must be an admin in that
  channel with «Post Messages» rights — otherwise the first match
  push will fail with a permanent error and the watchlist will be
  soft-deactivated (parallel to the digest channel-publish policy).
- The interest is owned by the calling user. After every incremental
  pipeline tick, new ProcessedDocuments from the listed channels are
  scored using `combined = kw_weight·keyword + sem_weight·semantic`
  (defaults `0.4`/`0.6`, tunable via `WATCHLIST_KEYWORD_WEIGHT` /
  `WATCHLIST_SEMANTIC_WEIGHT`); matches at or above `threshold` are
  saved in `watch_matches` and pushed to the resolved target via the
  bot (notify_mode=instant).
- `threshold` is **optional** — when omitted (`null`) new interests
  inherit `WATCHLIST_DEFAULT_THRESHOLD` (default `0.6`). Existing
  interests keep their stored value.
- **Keyword scoring is phrase-level.** A multi-word keyword (e.g.
  `"агонисты дофамина"`) counts as a hit only when *all* its tokens
  appear in the document; the keyword denominator is the number of
  keyword phrases, not the number of tokens. Single-token keywords are
  unchanged. Prefer concise / single-token keywords; multi-word phrases
  require every word to co-occur.
- Channels are normalized (`@durov` → `durov`); empty entries are
  rejected.
- For each channel, `assert_channel_access` enforces ownership; the call
  fails fast on the first denial.
- The interest's embedding is computed eagerly when `OPENAI_API_KEY` is
  configured (no first-tick latency); without it the watchlist falls
  back to keyword-only scoring.

### `list_watchlists`

```
Parameters: (none)

Returns: ListWatchlistsResult
  count: int
  interests: list[WatchInterestInfo]
```

- Admin sees every interest in the system; non-admin sees only their own.
- Inactive (soft-deleted) interests are included so the caller can
  inspect / re-create them.

### `unsubscribe_watchlist`

```
Parameters:
  interest_id: str               # UUID

Returns: UnsubscribeWatchlistResult
  success: bool
  interest_id: str
  message: str
```

- Owner-only for non-admins; admins can soft-delete any interest.
- Soft-delete preserves match history (`watch_matches` rows stay) so
  historical queries via `get_watchlist_matches` keep working.
- Returns `success=false, message="interest not found"` for unknown ids.

### `get_watchlist_matches`

```
Parameters:
  interest_id: str               # UUID
  since_iso: str | null = null   # ISO-8601 datetime; created_at >= since_iso

Returns: GetWatchlistMatchesResult
  count: int
  interest_id: str
  matches: list[WatchMatchInfo]  # source_ref, channel_id, scores, notified, created_at
```

- Owner-only for non-admins; non-owners get an empty list (silent) so
  watchlist ids are not leaked across users.
- Use `since_iso` for incremental polling — the persistent log is never
  truncated, so it's safe to walk it forward without losing entries.

### `backfill_watchlist`

```
Parameters:
  interest_id: str               # UUID
  since_iso: str | null = null   # ISO-8601 cutoff; default = interest.created_at
  limit: int = 2000              # Max historical docs (newest first; capped at 2000)
  dry_run: bool = true           # Preview only — no rows written, no push
  notify: bool = false           # With dry_run=false, also push a grouped notification

Returns: dict
  interest_id: str
  scored_docs: int               # Docs actually scored
  candidates: int                # Docs scoring at/above threshold
  inserted: int                  # New matches persisted (0 on dry-run)
  max_combined: float            # Highest combined score seen (threshold calibration)
  would_match: int               # Matches a non-dry-run would persist
  dry_run: bool
  error: str | null
```

- **Why it exists.** The scheduler only scores documents that become
  *new* within a tick, so a corpus ingested *before* the interest was
  created is never matched. `backfill_watchlist` walks each watched
  channel's `processed_documents` since `since_iso` and rescores them
  with the same hybrid matcher (DIAG 2026-06-07 hypothesis B2).
- Owner-only for non-admins; admins can backfill any interest.
- **Dry-run by default.** `dry_run=true` writes nothing and sends no
  push — inspect `would_match` / `max_combined` to gauge impact (and to
  see whether `threshold` sits above the real score ceiling) before
  committing with `dry_run=false`.
- Idempotent (`ON CONFLICT (interest_id, source_ref) DO NOTHING`), so a
  re-run never double-inserts or double-notifies.
- **Operational guardrail — run a manual / retroactive backfill
  *uncapped* (omit `limit`).** `limit` is a *newest-first* cap on the
  number of docs scored, so for a multi-channel interest it silently
  **under-counts** historical matches — the genuinely on-topic content is
  often old and falls outside the newest-N window. ADR-0011's default is
  uncapped (whole matched corpus); `limit` survives only as a newest-first
  preview cap. Evidence (2026-06-15): Микробиота with `limit=450` →
  `would_match=0` (`max_combined=0.331`); uncapped over the full 8004-doc
  corpus → `would_match=33` (`max_combined=0.789`). A prior session run
  with `limit=450` recorded only ~8 matches across 5 interests; the
  uncapped re-run recorded 342. For previews use `dry_run=true`
  *uncapped*; fall back to a `limit` only if an uncapped run actually
  times out (uncapped runs up to `scored_docs=8536` completed with no
  timeout — the cap was added "против таймаута" that never materialized).

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

### `list_workspaces`

```
Parameters: (none)

Returns: ListWorkspacesResult
  count: int
  workspaces: list[WorkspaceInfo]
    # id, owner_id, name, description, created_at, updated_at (ISO-8601)
```

- Lists workspaces owned by the calling user (owner-scoped). Admins see
  only their own here; cross-user inspection is exposed via
  `list_all_workspaces`.

### `create_workspace`

```
Parameters:
  name: str                      # Required. Unique per owner (UNIQUE (owner_id, name)).
  description: str | null        # Optional free-form description.

Returns: CreateWorkspaceResult
  success: bool
  workspace: WorkspaceInfo | null
  message: str
```

- Returns `success=false` (never raises) on whitespace-only names, on
  duplicate `(owner_id, name)` collisions, and on database errors.
- Per-owner namespace: two users can each have a workspace named
  "AI/ML" — they live in disjoint rows.

### `rename_workspace`

```
Parameters:
  workspace_id: str              # UUID. Must be owned by the caller.
  new_name: str                  # New name; subject to the same per-owner UNIQUE constraint.

Returns: RenameWorkspaceResult
  success: bool
  workspace: WorkspaceInfo | null
  message: str
```

- Returns `success=false, message="Workspace <id> not found"` for
  unknown or foreign IDs (existence never leaked).
- Duplicate-name / whitespace-name errors mirror `create_workspace`
  (structured 4xx-style result, no raise).

### `delete_workspace`

```
Parameters:
  workspace_id: str              # UUID. Must be owned by the caller.

Returns: DeleteWorkspaceResult
  success: bool
  workspace_id: str
  message: str
```

- `ON DELETE CASCADE` removes the workspace's M2M membership rows; the
  underlying `sources` themselves are preserved and remain visible
  through the null-workspace scope.
- Idempotent: re-deleting an unknown ID returns `success=false` with a
  benign "not found" message.

### `add_workspace_source`

```
Parameters:
  workspace_id: str              # UUID. Must be owned by the caller.
  channel_id: str                # channel_id or @username; normalized server-side.

Returns: WorkspaceSourceOpResult
  success: bool
  workspace_id: str
  channel_id: str
  changed: bool                  # true = inserted; false = idempotent no-op
  message: str
```

- Idempotent via `ON CONFLICT DO NOTHING`: `changed=false` means the
  channel was already attached.
- `assert_channel_access` enforces ownership on `channel_id`; non-owners
  get a structured `PermissionDenied` result.

> **Q4 R2 — non-atomic move.** To move a channel between workspaces use the documented pair `remove_workspace_source(from_ws, ch)` + `add_workspace_source(to_ws, ch)`. The two calls are **not atomic** (O-1 deferred per `PARITY_DECISION_TRACKING.md § 3`); concurrent reads during the gap window may see the channel only through the null-workspace scope.

### `remove_workspace_source`

```
Parameters:
  workspace_id: str              # UUID. Must be owned by the caller.
  channel_id: str                # channel_id or @username; normalized server-side.

Returns: WorkspaceSourceOpResult
  success: bool
  workspace_id: str
  channel_id: str
  changed: bool                  # true = removed; false = was not in the workspace
  message: str
```

- Removes only the M2M row; the underlying `sources` row is preserved
  and remains visible via the null-workspace scope.
- Used as the first half of the documented non-atomic move pair (see
  `add_workspace_source` above).

> **Q4 R2 — non-atomic move.** `remove_workspace_source(from_ws, ch)` + `add_workspace_source(to_ws, ch)` is the documented move pattern. The pair is **not atomic** in MVP (O-1 deferred); during the gap window the channel is visible only via the null-workspace scope.

### `list_workspace_sources`

```
Parameters:
  workspace_id: str              # UUID. Must be owned by the caller.

Returns: ListWorkspaceSourcesResult
  workspace_id: str
  count: int
  channel_ids: list[str]
```

- Returns `channel_id` values (not raw `source_id`) so the result is
  drop-in usable in any F4-A scoped tool's `channel_id` parameter.
- Unknown / foreign `workspace_id` returns `count=0, channel_ids=[]`
  (404-like, never leaks existence).

### `list_all_workspaces`

```
Parameters:
  owner_id: str | null = None    # Optional filter by owner.

Returns: ListWorkspacesResult
  count: int
  workspaces: list[WorkspaceInfo]
```

- **Admin-only.** Non-admin callers receive an empty list (no error),
  mirroring how `list_workspaces` reports zero rows so that probing the
  tool name cannot reveal whether admin access exists.
- Useful for cross-user inspection and ops audits.

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

### 5. Export a channel (F2 Parse-Only)

```
1. result = export_channel(channel_id="mychannel", level="raw", format="json")
   # returns {job_id, status: "pending", ...}
2. status = get_export_status(job_id=result.job_id)   # poll every 2-5 sec
   # status.status transitions: pending → running → completed
3. When status.status == "completed":
   # GET status.download_url with the same MCP/API credentials
   # -> raw_messages.json (or raw_messages.ndjson for format="ndjson")
```

Notes:
- `level="raw"` exports raw Telegram messages (parse-only, no LLM). Requires `channel_id`.
- `level="processed"` exports `kb_entries.ndjson` (post-LLM KnowledgeBaseEntry[]).
- `level="full"` (legacy default) adds `topics.json` + `topic_<id>.json`.
- `raw_payload` (private Telethon structures) is intentionally excluded from all levels.

### 6. Switch LLM provider at runtime

```
1. get_llm_config()                         # see current config + available providers
2. set_llm_config(scope="processing", provider="gemini", model="gemini-2.5-flash")
3. trigger_pipeline(channel_id="mychannel") # uses new provider
4. reset_llm_config()                       # revert to .env defaults
```

### 7. Subscribe and manage digests (F6)

```
1. result = subscribe_digest(
     name="morning brief",
     channel_ids=["@durov", "@telegram"],
     chat_id=12345,                       # personal chat or group/channel id
     cron_expression="0 9 * * 1-5",       # weekday mornings
     timezone="Europe/Moscow",
     format="summary",                    # or "bullets" / "detailed"
   )
   # returns {success: True, subscription: {...}}

2. list_digests()                         # admin: all; user: own only

3. unsubscribe_digest(subscription_id=result.subscription.id)
```

Notes:
- LLM stage `digest` can be tuned via env (`DIGEST_LLM_PROVIDER`/`_MODEL`)
  or runtime (`set_llm_config(scope="digest", ...)`).
- The bot-process scheduler picks up new MCP-created subscriptions within
  `DIGEST_REFRESH_INTERVAL` seconds (default 60s) without restart.

### 8. Subscribe and manage Topic Watchlists (F11)

```
1. result = subscribe_watchlist(
     title="MiCA crypto regulation",
     channel_ids=["@crypto_news", "@eth_news"],
     chat_id=12345,                          # personal chat or group/channel id
     keywords=["mica", "regulation"],        # positive overlap tokens
     description="Watch for crypto regulation news in EU",  # embedding source
     exclude_keywords=["meme", "shitcoin"],  # negative filter
     threshold=0.55,                         # combined-score cutoff in [0, 1]
   )
   # returns {success: True, interest: {...}}

2. list_watchlists()                          # admin: all; user: own only

3. # Incremental polling — never drops the persistent log
   matches = get_watchlist_matches(
     interest_id=result.interest.interest_id,
     since_iso="2026-04-25T00:00:00+00:00",
   )

4. # Retroactively score docs ingested before the interest existed.
   # Dry-run first to size the impact, then apply.
   preview = backfill_watchlist(interest_id=result.interest.interest_id)
   # → {scored_docs, max_combined, would_match, dry_run: True, ...}
   backfill_watchlist(interest_id=result.interest.interest_id,
                      dry_run=False, notify=True)

5. unsubscribe_watchlist(interest_id=result.interest.interest_id)
```

Notes:
- The hook fires after `run_incremental_topicization` per channel; matches
  above `threshold` are persisted in `watch_matches` (idempotent
  `ON CONFLICT DO NOTHING`) and pushed to `chat_id` via the bot.
- On a **no-match tick** the scheduler logs a structured
  `watchlist.score_ceiling` line (per-interest max combined / keyword /
  semantic vs threshold), so a persistent zero-matches situation is
  diagnosable from logs alone (previously sub-threshold scores lived
  only in the `tg_watchlist_score` histogram). If the ceiling sits below
  `threshold`, lower the threshold or rebalance
  `WATCHLIST_KEYWORD_WEIGHT` / `WATCHLIST_SEMANTIC_WEIGHT`.
- Use `backfill_watchlist` (dry-run) to check whether a freshly-created
  interest would have matched the *existing* corpus — the live hook only
  ever sees per-tick new docs.
- If the bot fails permanently (`chat not found`, `bot was blocked`,
  `forbidden`), the interest is **soft-deleted** to prevent retry storms;
  match history is preserved.
- Without `OPENAI_API_KEY` the watchlist falls back to keyword-only
  scoring — no hard dependency on OpenAI for the hot path.
- A single tick is capped at `MAX_DOCS_PER_TICK = 100` documents so a
  back-fill of a noisy channel cannot trigger a notification flood.

### 9. Manage Workspaces (F4-B Core)

```
1. ws = create_workspace(name="AI/ML", description="Anthropic, OpenAI")
   # returns {success: True, workspace: {id: <ws_id>, ...}}

2. add_workspace_source(workspace_id=ws.workspace.id, channel_id="anthropic_news")
   add_workspace_source(workspace_id=ws.workspace.id, channel_id="openai_news")

3. # Use the workspace as a scope on any read-tool:
   list_topics(workspace_id=ws.workspace.id)
   search_knowledge_base(query="Claude 4.5", workspace_id=ws.workspace.id)
   ask_question(question="What did Anthropic ship?", workspace_id=ws.workspace.id)

4. # Move a channel from one workspace to another (Q4 R2 — non-atomic):
   other_ws = create_workspace(name="AI/Anthropic-only")
   remove_workspace_source(workspace_id=ws.workspace.id, channel_id="anthropic_news")
   add_workspace_source(workspace_id=other_ws.workspace.id, channel_id="anthropic_news")
   # NOTE: between calls #4a and #4b, the channel is visible only via the
   # null-workspace scope. O-1 atomic move is deferred to Wave 1 step 3 / Wave 2.

5. # Admin inspection across users:
   list_all_workspaces()                      # admin: every workspace; non-admin: []
   list_all_workspaces(owner_id="<user_id>")  # admin: scoped to one owner
```

Notes:
- `workspace_id` on read-tools is an opt-in narrowing overlay; omitting
  it or passing `null` preserves F4-A behavior bit-for-bit.
- `get_topic_details` / `get_document` return their full payload
  regardless of `workspace_id` — Q4 R3 makes the workspace param a
  404-guard on the workspace itself, not an access-control filter on
  the bundle.
- Unknown / foreign `workspace_id` is treated as 404-like (empty
  result / "not found" message) so workspace existence is never leaked.

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
| `POST` | `/api/v1/watchlists` | api_key | Subscribe to a watchlist (idempotent upsert; `Idempotency-Key` header supported) |
| `GET` | `/api/v1/watchlists` | api_key | List caller's watchlists (offset/limit) |
| `GET` | `/api/v1/watchlists/{watchlist_id}` | api_key | Watchlist details (with `workspace_name` JOIN) |
| `DELETE` | `/api/v1/watchlists/{watchlist_id}` | api_key | Soft-delete watchlist (idempotent 204+204) |
| `GET` | `/api/v1/watchlists/{watchlist_id}/matches` | api_key | Match history (`?since=`, offset/limit) |
| `POST` | `/api/v1/digests` | api_key | Subscribe to a scheduled digest (idempotent upsert; `Idempotency-Key` supported) |
| `GET` | `/api/v1/digests` | api_key | List caller's digest subscriptions |
| `GET` | `/api/v1/digests/{digest_id}` | api_key | Digest subscription details |
| `DELETE` | `/api/v1/digests/{digest_id}` | api_key | HARD delete (second DELETE → 404; ASYMMETRIC vs watchlist) |

> **HTTP API ↔ MCP parity (Wave 1 step 3):** the 9 watchlist/digest HTTP endpoints above are a direct alternative to MCP `subscribe_watchlist` / `list_watchlists` / `unsubscribe_watchlist` / `get_watchlist_matches` / `subscribe_digest` / `list_digests` / `unsubscribe_digest`. Backend semantics are identical (service-layer natural-key upsert closes BUG-022 cross-surface); the HTTP surface additionally offers an optional Stripe-style `Idempotency-Key` header (24h TTL) for transient-retry safety. The `Idempotency-Key` mechanism is **HTTP-only** — MCP / Bot / CLI clients rely solely on the service-layer natural-key idempotency. `workspace_id` (ENH-9) is available on both surfaces.

---

**Version:** 4.3.0 | **Last updated:** May 2026
