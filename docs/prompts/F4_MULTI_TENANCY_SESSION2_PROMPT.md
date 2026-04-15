# Session 2: F4 Multi-Tenancy -- Phase 3 + Phase 4

## Purpose of this session

Implement Phases 3 and 4 of F4 Multi-Tenancy as described in the full plan at `.cursor/plans/f4_multi-tenancy_final_3f48b1a3.plan.md`.

This is an **implementation session**. The plan is already agreed.

**Scope:** Phase 3 (Channel Ownership Enforcement) + Phase 4 (Scoped Data Access)

---

## Baseline: what is already done (after Session 1)

- **Tests:** 1128 passed (including 74 F4-specific tests)
- **Phase 1 complete:** `users` + `user_auth_mappings` tables, `Source.owner_id`, `DocumentEmbedding.channel_ids`, `SAUserRepo`, Alembic migrations with backfill, `EmbeddingRepo.similarity_search(channel_ids=...)` SQL filter
- **Phase 2 complete:** `CurrentUser` dataclass, `tg_parser/auth/` package (`resolvers.py` + `models.py`), `resolve_user_by_auth()` with LRU cache, `hash_credential()`, `get_default_admin()`
- **API:** `resolve_current_user()` dependency **exists** in `tg_parser/api/auth.py` but is **NOT used** by any route -- all routes still use `Depends(verify_api_key)`
- **Bot:** `UserResolutionMiddleware` **exists** in `tg_parser/bot/middleware.py` but is **NOT registered** -- `main.py` still uses `AllowlistMiddleware`
- **MCP:** `BearerTokenVerifier` resolves tokens via DB; `resolve_mcp_user()` helper **exists** but is **NOT called** by any tool -- no tool accepts `ctx: Context`
- **No enforcement anywhere:** all data access is global, no ownership checks, no scoping

---

## Key architecture decisions (already agreed)

### User context flow (interface -> service -> repo)

```
Interface layer             Service layer                  Repo layer
(API/Bot/MCP)               (retrieval, analytics)         (embedding_repo, etc.)
      |                           |                             |
CurrentUser --resolve--> allowed_channel_ids: list|None ---> WHERE channel_ids && ARRAY[...]
```

- `CurrentUser` lives **only** at the interface layer; services take `allowed_channel_ids: list[str] | None`
- `None` = admin (all channels, no WHERE filter in SQL)
- Empty list `[]` = user with no channels (returns nothing)
- MCP: `ctx: Context` parameter -> `ctx.client_id` -> `resolve_mcp_user()`
- Bot: `data["current_user"]` from middleware -> handlers -> agent -> tools
- API: `Depends(resolve_current_user)` replaces `Depends(verify_api_key)`

### Backward compatibility (MUST preserve)

- Single-user deployment without auth -> `get_default_admin()` -> `allowed_channel_ids=None` -> no WHERE filter -> same behavior as before
- API `api_key_required=False` + no key -> admin -> full access
- MCP stdio mode: `ctx.client_id = None` -> admin -> full access
- Bot empty allowlist (dev mode) -> admin -> full access

---

## Phase 3: Channel Ownership Enforcement

### 3.1 New file: `tg_parser/auth/ownership.py`

Common helpers used by all three interfaces. Keeps ownership logic in one place.

```python
from tg_parser.auth.models import CurrentUser

class PermissionDenied(Exception):
    """Raised when user lacks required permission."""
    def __init__(self, message: str = "Permission denied"):
        self.message = message
        super().__init__(message)

async def assert_channel_access(user: CurrentUser, channel_id: str) -> None:
    """Raise PermissionDenied if user cannot access this channel.
    Admin (allowed_channel_ids=None) always passes."""
    if user.allowed_channel_ids is None:
        return
    if channel_id not in user.allowed_channel_ids:
        raise PermissionDenied(f"No access to channel {channel_id}")

def assert_admin(user: CurrentUser) -> None:
    """Raise PermissionDenied if user is not admin."""
    if not user.is_admin:
        raise PermissionDenied("Admin access required")

def check_channel_limit(user: CurrentUser, current_count: int) -> None:
    """Raise PermissionDenied if user reached max_channels.
    Admin (is_admin=True) has no limit."""
    if user.is_admin:
        return
    if current_count >= user.max_channels:
        raise PermissionDenied(
            f"Channel limit reached ({current_count}/{user.max_channels})"
        )
```

Update `tg_parser/auth/__init__.py` to re-export these helpers.

### 3.2 MCP: `ctx: Context` for channel-management tools

**File:** `tg_parser/mcp_server.py`

**Delete** constant `MAX_ACTIVE_SOURCES = 20` (line 661). Replace with `user.max_channels` from resolved `CurrentUser`.

For each tool below, add `ctx: Context` parameter and resolve user:

```python
from mcp.server.fastmcp import Context

@mcp.tool()
async def add_channel(channel_id: str, ..., ctx: Context) -> AddChannelResult:
    user = await resolve_mcp_user(ctx.client_id)
    # count user's active sources (not global!) for limit check
    # source.owner_id = user.id on create
```

**Channel-management tools (owner or admin):**

| Tool | Current line | Change |
|------|-------------|--------|
| `add_channel` | 664 | +ctx, owner_id=user.id, limit via user.max_channels, count only user's sources |
| `remove_channel` | 721 | +ctx, assert_channel_access(user, channel_id) |
| `pause_channel` | 809 | +ctx, assert_channel_access |
| `resume_channel` | 849 | +ctx, assert_channel_access |
| `trigger_pipeline` | 892 | +ctx, assert_channel_access |
| `list_channels` | 939 | +ctx, pass owner_id=user.id to filtering (admin sees all) |
| `get_pipeline_status` | 967 | +ctx, filter sources by user's channels |

**Admin-only tools:**

| Tool | Current line | Change |
|------|-------------|--------|
| `set_llm_config` | 1104 | +ctx, assert_admin(user) |
| `reset_llm_config` | 1155 | +ctx, assert_admin(user) |
| `reload_prompts` | 1195 | +ctx, assert_admin(user) |

**Error handling pattern** for MCP tools:
```python
try:
    user = await resolve_mcp_user(ctx.client_id)
    assert_channel_access(user, normalized)
except PermissionDenied as e:
    return ErrorResult(error=e.message)  # or return appropriate typed result with error field
```

### 3.3 Bot: wire `UserResolutionMiddleware` + `current_user` propagation

**File: `tg_parser/bot/main.py` (line 160)**

Replace:
```python
dp.message.middleware(AllowlistMiddleware(settings.bot_allowed_user_ids))
```
With:
```python
dp.message.middleware(UserResolutionMiddleware(settings.bot_allowed_user_ids))
```

Import `UserResolutionMiddleware` instead of (or alongside) `AllowlistMiddleware`.

**File: `tg_parser/bot/handlers.py` (line 99-120)**

Update `handle_text` to extract and pass `current_user`:
```python
@router.message(F.text)
async def handle_text(message: Message, agent: GeminiAgent, current_user: CurrentUser | None = None) -> None:
    # ... existing logic ...
    response_text = await agent.process_message(user_text, current_user=current_user)
```

Aiogram injects `current_user` from `data["current_user"]` set by middleware automatically when declared as handler parameter.

**File: `tg_parser/bot/agent.py` (line 51, 103-105)**

Update `process_message` and `execute_tool` call:
```python
async def process_message(self, user_message: str, current_user: CurrentUser | None = None) -> str:
    # ... existing logic ...
    result = await execute_tool(
        tool_name, tool_args, current_user=current_user, timeout=self._tool_timeout,
    )
```

**File: `tg_parser/bot/tools.py`**

Update `execute_tool` signature (line 434):
```python
async def execute_tool(
    name: str,
    args: dict[str, Any],
    timeout: float = 60.0,
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
```

Pass `current_user` to each executor. **Two approaches** (pick one):
- **(A)** Change all `_exec_*` signatures to accept `current_user` parameter
- **(B)** Inject `current_user` into `args["_current_user"]` before calling executor

**Recommended: approach (A)** -- explicit is better than implicit:
```python
executor = _TOOL_EXECUTORS.get(name)
# ...
return await asyncio.wait_for(executor(args, current_user=current_user), timeout=timeout)
```

All `_exec_*` functions gain `current_user: CurrentUser | None = None` parameter.

**Delete** `MAX_ACTIVE_SOURCES = 20` (line 965).

**Channel-management bot tools (ownership enforcement):**

| Executor | Line | Change |
|----------|------|--------|
| `_exec_add_channel` | 967 | owner_id=user.id, limit via user.max_channels (count only user's sources) |
| `_exec_remove_channel` | 1071 | assert_channel_access |
| `_exec_pause_channel` | 1113 | assert_channel_access |
| `_exec_resume_channel` | 1143 | assert_channel_access |
| `_exec_trigger_pipeline` | 843 | assert_channel_access |
| `_exec_list_channels` | 535 | pass owner filter |

**Admin-only bot tools:**

| Executor | Line | Change |
|----------|------|--------|
| `_exec_set_llm_config` | 788 | assert_admin |
| `_exec_reset_llm_config` | 825 | assert_admin |
| `_exec_reload_prompts` | 755 | assert_admin |

When `current_user` is None (fallback), use `get_default_admin()`.

### 3.4 API routes: channel ownership

**File: `tg_parser/api/routes/channels.py`**

Replace `Depends(verify_api_key)` with `Depends(resolve_current_user)`:
```python
from tg_parser.api.auth import resolve_current_user
from tg_parser.auth.models import CurrentUser

@router.get("/channels")
async def list_channels(user: CurrentUser = Depends(resolve_current_user)):
    # admin: list_sources() (all)
    # non-admin: list_sources(owner_id=user.id)
```

```python
@router.get("/channels/{channel_id}/stats")
async def get_channel_stats(channel_id: str, user: CurrentUser = Depends(resolve_current_user)):
    assert_channel_access(user, channel_id)  # raises -> 403
```

**File: `tg_parser/api/routes/process.py`**

Replace auth dependency:
```python
@router.post("/process")
async def start_processing(body, background_tasks, user: CurrentUser = Depends(resolve_current_user)):
    assert_channel_access(user, body.channel_id)
    # create job with user reference
```

Add `PermissionDenied` -> 403 exception handler in the route or via middleware.

### 3.5 Tests Phase 3

**New file: `tests/test_f4_ownership.py`** (~15 tests)

Tests to cover:
- `assert_channel_access`: admin passes, user with channel passes, user without channel raises
- `assert_admin`: admin passes, user raises
- `check_channel_limit`: under limit passes, at limit raises, admin unlimited
- MCP `add_channel` sets `owner_id` on new source
- MCP `add_channel` enforces `max_channels` per user (not global)
- MCP `remove_channel` only by owner or admin; unauthorized -> error
- MCP `pause_channel`/`resume_channel` ownership enforcement
- MCP `list_channels` scoped: admin sees all, user sees only owned
- MCP admin-only tools: `set_llm_config` rejected for non-admin
- Bot `_exec_add_channel` with `current_user` sets ownership
- API `list_channels` scoped by owner
- API `start_processing` rejects unauthorized channel

---

## Phase 4: Scoped Data Access

### 4.1 Repo layer: `TopicCardRepo.list_by_channels()`

**File: `tg_parser/storage/ports.py`** (TopicCardRepo ABC, after line 525)

Add abstract method:
```python
@abstractmethod
async def list_by_channels(self, channel_ids: list[str]) -> list[TopicCard]:
    """List topic cards visible to a user with these channels."""
    pass
```

**File: `tg_parser/storage/sqlalchemy/topic_card_repo.py`** (after `list_all` at line 122)

Implement with OR chain on `sources_json LIKE`:
```python
async def list_by_channels(self, channel_ids: list[str]) -> list[TopicCard]:
    if not channel_ids:
        return []
    conditions = " OR ".join(
        f"sources_json LIKE :p{i}" for i in range(len(channel_ids))
    )
    params = {f"p{i}": f'%"{cid}"%' for i, cid in enumerate(channel_ids)}
    query = text(f"SELECT * FROM topic_cards WHERE {conditions} ORDER BY updated_at DESC")
    result = await self.session.execute(query, params)
    return [self._row_to_model(r) for r in result.fetchall()]
```

### 4.2 Service layer: add `allowed_channel_ids` parameter

**File: `tg_parser/services/retrieval_service.py`**

`search()` (line 45) -- add `allowed_channel_ids: list[str] | None = None`:
```python
async def search(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    threshold: float = 0.0,
    include_topics: bool = True,
    allowed_channel_ids: list[str] | None = None,  # NEW
    *,
    emb_repo: ...,
) -> list[SearchResult]:
```

Logic:
- Compute effective channel filter: if `channel_id` is set AND `allowed_channel_ids` is not None, intersect (verify `channel_id in allowed_channel_ids`, raise error if not)
- If only `allowed_channel_ids`, pass to `similarity_search(channel_ids=allowed_channel_ids)`
- If only `channel_id`, pass `channel_ids=[channel_id]`
- If neither (admin), pass `channel_ids=None`
- **Remove** the existing Python post-filter loop that skips docs by `channel_id` -- replaced by SQL filter
- Topic results: similarly filter via `allowed_channel_ids` intersection with `card.sources`

`answer()` (line 176) -- same `allowed_channel_ids` param, pass through to `search()`.

**File: `tg_parser/services/analytics_service.py`**

`get_cross_channel_analytics()` (line 68) -- add `allowed_channel_ids: list[str] | None = None`:
- Filter `sources` list by `allowed_channel_ids`
- Filter topic cards/bundles by channel overlap
- Admin (None) -> no filter

**File: `tg_parser/services/channel_service.py`**

`get_all_channel_stats()` (line 81) -- add `allowed_channel_ids: list[str] | None = None`:
- Filter `list_sources()` result by `allowed_channel_ids` (or pass `owner_id`)
- `get_channel_stats(channel_id)` -- no change needed (called per-channel, access checked upstream)

**File: `tg_parser/services/topic_linking_service.py`**

`get_related_topics_for()` (line 163) -- add `allowed_channel_ids: list[str] | None = None`:
- Filter returned related topics: only include if topic's sources overlap with `allowed_channel_ids`
- Admin (None) -> return all

### 4.3 MCP tools: scoped data access (add `ctx: Context` to remaining tools)

All remaining data-access tools get `ctx: Context` + tenant scoping:

| Tool | Current line | Change |
|------|-------------|--------|
| `search_knowledge_base` | ~340 | +ctx, pass `allowed_channel_ids=user.allowed_channel_ids` to `search()` |
| `ask_question` | ~410 | +ctx, pass `allowed_channel_ids` to `answer()` |
| `list_topics` | ~460 | +ctx, use `list_by_channels(user.allowed_channel_ids)` for non-admin instead of `list_all()` |
| `get_topic_details` | ~530 | +ctx, verify topic sources overlap with `allowed_channel_ids` |
| `get_document` | ~580 | +ctx, verify `doc.channel_id` in `allowed_channel_ids` |
| `get_related_topics` | ~610 | +ctx, pass `allowed_channel_ids` to `get_related_topics_for()` |
| `get_cross_channel_stats` | ~645 | +ctx, pass `allowed_channel_ids` to `get_cross_channel_analytics()` |

### 4.4 Bot tools: scoped data access

All data-access `_exec_*` functions use `current_user.allowed_channel_ids`:

| Executor | Change |
|----------|--------|
| `_exec_search` | pass `allowed_channel_ids=user.allowed_channel_ids` to `search()` |
| `_exec_ask_question` | pass `allowed_channel_ids` to `answer()` |
| `_exec_list_topics` | use `list_by_channels()` for non-admin |
| `_exec_get_topic_details` | verify topic sources overlap |
| `_exec_get_document` | verify `doc.channel_id` access |
| `_exec_get_related_topics` | pass `allowed_channel_ids` to service |
| `_exec_get_cross_channel_stats` | pass `allowed_channel_ids` to service |

When `current_user` is None, call `get_default_admin()` -> `allowed_channel_ids=None` -> no filtering.

### 4.5 API routes: scoped data access

**All routes** below switch from `Depends(verify_api_key)` to `Depends(resolve_current_user)`.

**File: `tg_parser/api/routes/rag.py`**

```python
@router.post("/search")
async def search_documents(body: SearchRequest, user: CurrentUser = Depends(resolve_current_user)):
    # If body.channel_id set, verify it's in user.allowed_channel_ids
    results = await search(
        query=body.query,
        channel_id=body.channel_id,
        allowed_channel_ids=user.allowed_channel_ids,
        limit=body.limit,
    )
```

Same pattern for `/ask`.

**File: `tg_parser/api/routes/topics.py`**

- `GET /topics` -- use `list_by_channels(user.allowed_channel_ids)` for non-admin
- `GET /topics/{topic_id}` -- verify topic sources overlap with `allowed_channel_ids`
- `GET /topics/{topic_id}/bundle` -- same check

**File: `tg_parser/api/routes/documents.py`**

- `GET /documents?source_ref=...` -- after fetching doc, verify `doc.channel_id` in `allowed_channel_ids`

**File: `tg_parser/api/routes/export.py`**

- `POST /export` -- verify `body.channel_id` access; if `channel_id=None`, export only allowed channels
- `GET /export/status/{job_id}` -- verify job belongs to user (or admin)
- `GET /export/download/{job_id}` -- same

**File: `tg_parser/api/routes/agents.py`** -- make **admin-only**:

```python
@router.get("")
async def list_agents(..., user: CurrentUser = Depends(resolve_current_user)):
    assert_admin(user)  # 403 for non-admin
```

Apply to all 5 endpoints.

**File: `tg_parser/api/routes/llm_config.py`** -- make **admin-only**:

Apply `assert_admin(user)` to `set_llm_config` and `reset_llm_config`. `get_llm_config` can remain readable by all (or admin-only -- your choice, plan says admin-only for mutation).

**PermissionDenied -> HTTP 403 mapping:**

Add exception handler in `tg_parser/api/main.py` or in each route:
```python
from tg_parser.auth.ownership import PermissionDenied
from fastapi import HTTPException

# In route:
try:
    assert_channel_access(user, channel_id)
except PermissionDenied as e:
    raise HTTPException(status_code=403, detail=e.message)
```

Or register a global handler:
```python
@app.exception_handler(PermissionDenied)
async def permission_denied_handler(request, exc):
    return JSONResponse(status_code=403, content={"detail": exc.message})
```

### 4.6 IVFFlat probes tuning

**File: `tg_parser/storage/sqlalchemy/embedding_repo.py`** -- in `similarity_search()`:

When `channel_ids` is not None, set higher probes for better recall:
```python
if channel_ids is not None:
    await self.session.execute(text("SET ivfflat.probes = 20"))
```

This is a per-session hint; does not affect other queries. Default `ivfflat.probes` is 1, which may miss results when filtering by few channels.

### 4.7 Health/status endpoints

`GET /health`, `GET /status` -- leave **unchanged** (public probes, no tenant scoping needed). These endpoints don't use `verify_api_key` or can stay with optional auth.

### 4.8 Tests Phase 4

**New file: `tests/test_f4_scoped_access.py`** (~20 tests):

- `search()` with `allowed_channel_ids=["ch1"]` returns only ch1 data
- `search()` with `allowed_channel_ids=None` returns all (admin)
- `search()` with `channel_id="ch1"` + `allowed_channel_ids=["ch1","ch2"]` returns only ch1
- `search()` with `channel_id="ch3"` + `allowed_channel_ids=["ch1","ch2"]` raises/rejects
- `answer()` respects `allowed_channel_ids`
- `list_topics` scoped by channels
- `get_topic_details` rejects topic from unauthorized channel
- `get_document` rejects document from unauthorized channel
- `get_related_topics` filters by allowed channels
- `get_cross_channel_analytics` scoped
- `get_all_channel_stats` scoped
- API `/search` endpoint passes `allowed_channel_ids` from `CurrentUser`
- API `/topics` endpoint scoped
- API `/agents/*` admin-only enforcement
- API `/llm/config` admin-only enforcement
- Export scoped by channel ownership
- Admin sees all data across all test scenarios

**New file: `tests/test_f4_vector_search_isolation.py`** (~10 tests):

- SQL-level `channel_ids && ARRAY[...]` filter correctness
- IVFFlat + GIN interaction (search with probes=20)
- Empty `channel_ids=[]` returns nothing
- `channel_ids=None` returns all
- Intersection of `channel_id` + `allowed_channel_ids`
- Cross-channel topic embedding with multiple `channel_ids` found by either channel filter

---

## Critical files to read first

Before writing any code, read these files to understand current implementation:

1. `tg_parser/auth/models.py` -- CurrentUser dataclass
2. `tg_parser/auth/resolvers.py` -- resolve_user_by_auth, get_default_admin, hash_credential
3. `tg_parser/api/auth.py` -- resolve_current_user (existing but unused), verify_api_key (current)
4. `tg_parser/mcp_server.py` -- all @mcp.tool() functions, resolve_mcp_user, BearerTokenVerifier, MAX_ACTIVE_SOURCES
5. `tg_parser/bot/main.py` -- middleware registration (lines 158-161)
6. `tg_parser/bot/handlers.py` -- handle_text (line 99), agent.process_message call (line 120)
7. `tg_parser/bot/agent.py` -- process_message (line 51), execute_tool call (line 103)
8. `tg_parser/bot/tools.py` -- execute_tool (line 434), _TOOL_EXECUTORS (line 1201), MAX_ACTIVE_SOURCES (line 965), all _exec_* functions
9. `tg_parser/services/retrieval_service.py` -- search() (line 45), answer() (line 176)
10. `tg_parser/services/analytics_service.py` -- get_cross_channel_analytics() (line 68)
11. `tg_parser/services/channel_service.py` -- get_channel_stats() (line 35), get_all_channel_stats() (line 81)
12. `tg_parser/services/topic_linking_service.py` -- get_related_topics_for() (line 163)
13. `tg_parser/storage/sqlalchemy/topic_card_repo.py` -- list_all (line 122), list_by_channel (line 101)
14. `tg_parser/storage/ports.py` -- TopicCardRepo ABC (line 496), EmbeddingRepo (similarity_search)
15. `tg_parser/api/routes/channels.py` -- both endpoints
16. `tg_parser/api/routes/rag.py` -- search + ask endpoints
17. `tg_parser/api/routes/topics.py` -- list + detail + bundle endpoints
18. `tg_parser/api/routes/documents.py` -- get_document endpoint
19. `tg_parser/api/routes/export.py` -- export + status + download endpoints
20. `tg_parser/api/routes/agents.py` -- all endpoints (will become admin-only)
21. `tg_parser/api/routes/llm_config.py` -- all endpoints (mutations admin-only)
22. `tg_parser/api/routes/process.py` -- process + job status + list jobs

---

## Recommended implementation order

Work in this order to minimize broken intermediate states:

1. **`tg_parser/auth/ownership.py`** -- create helpers (no dependencies on other changes)
2. **Bot chain wiring** -- main.py (middleware) -> handlers.py -> agent.py -> tools.py (signatures only, no logic yet) -- one-time structural change
3. **Service layer** -- add `allowed_channel_ids` param to retrieval, analytics, channel, topic_linking services
4. **Repo layer** -- `TopicCardRepo.list_by_channels()` + IVFFlat probes
5. **MCP tools** -- add `ctx: Context` to ALL tools at once (Phase 3 + 4 together), wire resolve_mcp_user + ownership checks + scoped data access
6. **Bot tools** -- wire ownership checks + scoped data access in all `_exec_*` functions
7. **API routes** -- switch all to `resolve_current_user`, add scoping + ownership + admin-only
8. **Tests** -- `test_f4_ownership.py`, `test_f4_scoped_access.py`, `test_f4_vector_search_isolation.py`
9. **Full test suite** -- `TEST_POSTGRES=1 pytest tests/` -- verify 0 failures

---

## Verification checklist

After implementing Phase 3 + Phase 4:

- [ ] `pytest` passes (existing 1128 + new ~45 tests)
- [ ] MCP tools work in stdio mode (admin, full access)
- [ ] MCP `add_channel` assigns `owner_id` to new source
- [ ] MCP `add_channel` enforces per-user `max_channels` (not global constant)
- [ ] MCP `remove_channel` rejected for non-owner non-admin
- [ ] MCP `list_channels` returns only user's channels (admin sees all)
- [ ] MCP `search_knowledge_base` returns only data from user's channels
- [ ] MCP `set_llm_config` rejected for non-admin
- [ ] Bot `UserResolutionMiddleware` registered and working
- [ ] Bot tools receive `current_user` and enforce ownership
- [ ] API `Depends(resolve_current_user)` on all non-health routes
- [ ] API search returns only data from user's channels
- [ ] API `/agents/*` returns 403 for non-admin
- [ ] Admin user sees all data (backward compat with current behavior)
- [ ] `similarity_search` with `channel_ids` uses `ivfflat.probes = 20`
- [ ] Existing tests still pass (no regressions)
- [ ] `MAX_ACTIVE_SOURCES` constant removed from both `mcp_server.py` and `bot/tools.py`

---

## Subsequent sessions

- **Session 3:** Phase 5 (User Management Tools + Migration Script)

Full plan with all 5 phases: `.cursor/plans/f4_multi-tenancy_final_3f48b1a3.plan.md`
