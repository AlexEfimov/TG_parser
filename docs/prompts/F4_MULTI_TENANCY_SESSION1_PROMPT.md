# Session: F4 Multi-Tenancy -- Phase 1 + Phase 2

## Purpose of this session

Implement Phases 1 and 2 of F4 Multi-Tenancy as described in the full plan at `.cursor/plans/f4_multi-tenancy_final_3f48b1a3.plan.md`.

This is an **implementation session**. The plan is already agreed.

**Scope:** Phase 1 (Data Model + Migrations) + Phase 2 (Auth Resolution + CurrentUser)

---

## Baseline: what is already done

- **Version:** 4.2.0 (commit `53f402e`, 15 April 2026)
- **Tests:** 1038 passed
- **F5-A done:** `document_embeddings` has `entry_type` + `topic_id`; hybrid RAG (messages + topics)
- **F8-A done:** unified retry, DB pool metrics, Prometheus alerts, LLM cache
- **RAG config done:** YAML prompts, PromptLoader, scope `rag` in LLMConfigManager
- **Current auth:** API keys -> `client_name` (logging only); MCP tokens -> `client_id` (transport-level, not passed to tools); Bot allowlist by Telegram user ID
- **No user model:** no `users` table, no `owner_id` on sources, no `channel_ids` on embeddings, no scoped data access

---

## Key architecture decisions (already agreed)

### User context flow

```
Interface layer          Service layer              Repo layer
(API/Bot/MCP)            (retrieval, analytics)     (embedding_repo, etc.)
     |                        |                          |
CurrentUser --resolve--> allowed_channel_ids --param--> WHERE channel_ids && ARRAY[...]
```

- `CurrentUser` lives only at the interface layer; services and repos take `allowed_channel_ids: list[str] | None`
- `None` = admin (all channels, no WHERE filter)
- MCP: `ctx: Context` injection (`ctx.client_id` from `AccessToken`)
- Bot: `UserResolutionMiddleware` -> `data["current_user"]`
- API: `Depends(resolve_current_user)` replaces `Depends(verify_api_key)`

### Auth identifier hashing

`user_auth_mappings.auth_identifier` stores SHA-256 hash for api_key/mcp_token, plain text for telegram_user_id. Lookup: `hash(incoming_raw_key)` -> DB query. Raw keys never stored in DB.

---

## Phase 1: Data Model + Migrations

### 1.1 DDL: users + user_auth_mappings

Add to `tg_parser/storage/sqlalchemy/schemas/ingestion_state.py` (append to `INGESTION_STATE_DDL`):

```sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    max_channels INTEGER DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_auth_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auth_type TEXT NOT NULL CHECK (auth_type IN ('api_key', 'telegram', 'mcp_token')),
    auth_identifier TEXT NOT NULL,
    client_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(auth_type, auth_identifier)
);
CREATE INDEX IF NOT EXISTS idx_uam_lookup ON user_auth_mappings(auth_type, auth_identifier);

ALTER TABLE sources ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_sources_owner ON sources(owner_id);
```

### 1.2 DDL: document_embeddings.channel_ids

Add to `tg_parser/storage/sqlalchemy/schemas/processing_storage.py`:
- Extend `EMBEDDING_DDL` with `channel_ids TEXT[] DEFAULT '{}'`
- Extend `_ensure_embedding_columns()` to add `channel_ids` column + GIN index idempotently

```sql
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS channel_ids TEXT[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_de_channel_ids ON document_embeddings USING GIN(channel_ids);
```

### 1.3 Domain: ports.py

- Add `User` dataclass: `id`, `name`, `role`, `max_channels: int | None`, `created_at`, `updated_at`
- Add `UserAuthMapping` dataclass: `id`, `user_id`, `auth_type`, `auth_identifier`, `client_name`, `created_at`
- Add `UserRepo` ABC: `create_user`, `get_by_id`, `resolve_auth`, `get_owned_channel_ids`, `add_auth_mapping`, `remove_auth_mapping`, `list_users`, `delete_user`, `update_user`
- Extend `Source.__init__`: add `owner_id: str | None = None`
- Extend `DocumentEmbedding`: add `channel_ids: list[str] = field(default_factory=list)`
- Extend `EmbeddingRepo.save()`: add `channel_ids: list[str] | None = None` param
- Extend `EmbeddingRepo.similarity_search()`: add `channel_ids: list[str] | None = None` param

### 1.4 New file: user_repo.py

`tg_parser/storage/sqlalchemy/user_repo.py` -- SAUserRepo implementing UserRepo:
- `create_user(name, role='user', max_channels=None) -> User`
- `get_by_id(user_id) -> User | None`
- `resolve_auth(auth_type, auth_identifier) -> User | None` -- key method, single query with JOIN
- `get_owned_channel_ids(user_id) -> list[str]` -- via JOIN sources WHERE owner_id
- `add_auth_mapping(user_id, auth_type, auth_identifier, client_name=None)`
- `remove_auth_mapping(mapping_id)`
- `list_users() -> list[User]`
- `delete_user(user_id)`
- `update_user(user_id, name?, role?, max_channels?) -> User`

### 1.5 Settings

`tg_parser/config/settings.py`: add `default_max_channels: int = 20` (env: `DEFAULT_MAX_CHANNELS`)

### 1.6 embedding_repo.py changes

- `save()`: add `channel_ids: list[str] | None = None` param -> INSERT includes `channel_ids` column
- `save_batch()`: add `channel_ids: list[str] | None = None` kwarg -> applied to all items in batch
- `similarity_search()`: add `channel_ids: list[str] | None = None` -> when not None, add `WHERE channel_ids && ARRAY[:allowed_channels]` to SQL

### 1.7 ingestion_state_repo.py changes

- `upsert_source()`: persist `owner_id` (new column in INSERT/UPDATE)
- `list_sources()`: add optional `owner_id: str | None = None` filter
- `_row_to_source()`: parse `owner_id` from row

### 1.8 db_context.py

Add `user_repo()` async context manager (like existing `ingestion_state_repo()`)

### 1.9 embedding_service.py changes

- `run_embedding()`: pass `channel_ids=[channel_id]` to `save_batch()`
- `run_topic_embedding()`: extract channel_ids from `topic_card.sources`, pass to `save()`

### 1.10 Alembic migrations

- `migrations/versions/ingestion/20260416_add_users_and_ownership.py`: CREATE users + user_auth_mappings, ALTER sources ADD owner_id, seed admin user
- `migrations/versions/processing/20260416_add_embedding_channel_ids.py`: ADD channel_ids + GIN index + backfill:

```sql
UPDATE document_embeddings de
SET channel_ids = ARRAY[pd.channel_id]
FROM processed_documents pd
WHERE de.source_ref = pd.source_ref
  AND de.entry_type = 'message'
  AND (de.channel_ids IS NULL OR de.channel_ids = '{}');
```

Topic embeddings backfill in Python: parse `sources_json` from `topic_cards`.

### 1.11 Tests (~15)

`tests/test_f4_user_model.py`: UserRepo CRUD, resolve_auth, get_owned_channel_ids, seed admin
`tests/test_f4_embedding_channel_ids.py`: save/save_batch populate channel_ids, similarity_search with/without channel_ids filter, backfill correctness

---

## Phase 2: Auth Resolution + CurrentUser

### 2.1 New package: tg_parser/auth/

- `tg_parser/auth/__init__.py`
- `tg_parser/auth/models.py` -- CurrentUser dataclass:

```python
@dataclass
class CurrentUser:
    id: str
    name: str
    role: str  # 'admin' | 'user'
    allowed_channel_ids: list[str] | None  # None = admin (all channels)
    max_channels: int  # from users.max_channels or settings.default_max_channels

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
```

- `tg_parser/auth/resolvers.py` -- shared resolver with LRU cache (TTL 60s):

```python
async def resolve_user_by_auth(auth_type: str, auth_identifier: str) -> CurrentUser | None
async def get_default_admin() -> CurrentUser  # singleton admin for backward compat
def invalidate_user_cache(auth_type: str, auth_identifier: str) -> None
```

### 2.2 API auth changes

`tg_parser/api/auth.py`:
- Replace `verify_api_key()` with `resolve_current_user()` FastAPI dependency
- `api_key_required=False` + no key -> `get_default_admin()`
- `api_key_required=True` + no key -> 401
- Invalid key -> 403
- Key not mapped to user -> 403 ("register key with admin")
- Keep `get_optional_client()` as `get_optional_user()` for backward compat

### 2.3 Bot middleware changes

`tg_parser/bot/middleware.py`:
- Replace `AllowlistMiddleware` with `UserResolutionMiddleware`
- `from_user.id` -> `resolve_user_by_auth('telegram', str(user_id))` -> `data["current_user"]`
- Unregistered user -> reject with "contact admin" message
- Empty allowlist (dev mode) -> default admin for all users

### 2.4 MCP auth changes

`tg_parser/mcp_server.py`:
- `BearerTokenVerifier.verify_token()`: resolve token via DB -> `AccessToken(client_id=str(user_id))`
- Fallback: token from settings without DB entry -> admin
- Add helper: `resolve_mcp_user(client_id: str | None) -> CurrentUser` (cached)
- None client_id (stdio mode) -> default admin

### 2.5 Tests (~20)

`tests/test_f4_auth_resolution.py`:
- API key -> correct user
- Telegram ID -> correct user
- MCP token -> correct user
- Anonymous (no auth) -> admin
- Invalid key -> 403
- Unregistered Telegram user -> reject
- Cache hit/miss behavior
- Admin vs user role differences
- Hash-at-lookup correctness

---

## Critical files to read first

Before writing any code, read these files to understand current implementation:

1. `tg_parser/storage/sqlalchemy/schemas/ingestion_state.py` -- current DDL
2. `tg_parser/storage/sqlalchemy/schemas/processing_storage.py` -- embedding DDL + `_ensure_embedding_columns`
3. `tg_parser/storage/ports.py` -- all ABC repos, Source class, DocumentEmbedding, EmbeddingRepo
4. `tg_parser/storage/sqlalchemy/embedding_repo.py` -- save, save_batch, similarity_search
5. `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` -- source CRUD
6. `tg_parser/services/db_context.py` -- repo context managers
7. `tg_parser/services/embedding_service.py` -- run_embedding, run_topic_embedding
8. `tg_parser/api/auth.py` -- current verify_api_key
9. `tg_parser/bot/middleware.py` -- current AllowlistMiddleware
10. `tg_parser/mcp_server.py` -- BearerTokenVerifier + first 140 lines
11. `tg_parser/config/settings.py` -- api_keys, mcp_auth_tokens, bot_allowed_users sections
12. `migrations/versions/processing/20260415_add_entry_type_to_embeddings.py` -- latest migration as template

---

## Verification checklist

After implementing Phase 1 + Phase 2:

- [ ] `pytest` passes (existing 1038 + new ~35 tests)
- [ ] Alembic migrations apply cleanly (`tg-parser db upgrade`)
- [ ] Default admin user created on first startup
- [ ] Existing API keys / MCP tokens / bot users still work (backward compat)
- [ ] `similarity_search(channel_ids=None)` returns same results as before (admin = no filter)
- [ ] `similarity_search(channel_ids=['genotek'])` returns only genotek embeddings
- [ ] New embeddings saved with `channel_ids` populated
- [ ] `resolve_current_user()` dependency works in at least one API route
- [ ] `UserResolutionMiddleware` rejects unknown Telegram users
- [ ] MCP tools still work in stdio mode (admin)

---

## Subsequent sessions

- **Session 2:** Phase 3 (Channel Ownership) + Phase 4 (Scoped Data Access)
- **Session 3:** Phase 5 (User Management Tools + Migration Script)

Full plan with all 5 phases: `.cursor/plans/f4_multi-tenancy_final_3f48b1a3.plan.md`
