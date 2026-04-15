# Session 3: F4 Multi-Tenancy -- Phase 5

## Purpose of this session

Implement Phase 5 of F4 Multi-Tenancy as described in the full plan at `docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`.

This is an **implementation session**. The plan is already agreed.

**Scope:** Phase 5 (User Management Tools + Migration Script)

---

## Baseline: what is already done (after Session 1 + Session 2)

- **Phase 1 complete:** `users` + `user_auth_mappings` tables, `Source.owner_id`, `DocumentEmbedding.channel_ids`, `SAUserRepo`, Alembic migrations
- **Phase 2 complete:** `CurrentUser` dataclass, `tg_parser/auth/` package, `resolve_user_by_auth()`, `resolve_current_user()`, `UserResolutionMiddleware`, `BearerTokenVerifier`
- **Phase 3 complete:** Channel ownership enforcement across MCP/Bot/API -- `add_channel` sets `owner_id`, `remove/pause/resume` require owner or admin, `list_channels` scoped by owner, `max_channels` per-user limit, admin-only for `set_llm_config`/`reset_llm_config`/`reload_prompts`
- **Phase 4 complete:** Scoped data access -- `similarity_search` with `channel_ids` SQL filter, `retrieval_service.search/answer` with `allowed_channel_ids`, `topic_card_repo.list_by_channels()`, all MCP tools with `ctx: Context`, bot `current_user` propagation chain, all API routes with `resolve_current_user`, IVFFlat probes tuning, admin-only `/agents/*` endpoints

> **Note:** Confirm baseline by running `TEST_POSTGRES=1 pytest tests/` before starting. All tests from Sessions 1-2 must still pass.

---

## Phase 5: User Management Tools + Migration Script

### 5.1 New MCP tools

All tools added to `tg_parser/mcp_server.py` with `ctx: Context`:

```python
@mcp.tool()
async def register_user(
    name: str,
    role: str = "user",
    max_channels: int | None = None,
    ctx: Context,
) -> RegisterUserResult:
    """Register a new user. Admin only.
    max_channels: per-user channel limit (None = global default from settings)."""
    user = await resolve_mcp_user(ctx.client_id)
    assert_admin(user)
    # UserRepo.create_user(name, role, max_channels)

@mcp.tool()
async def update_user(
    user_id: str,
    name: str | None = None,
    role: str | None = None,
    max_channels: int | None = None,
    ctx: Context,
) -> UpdateUserResult:
    """Update user properties. Admin only."""

@mcp.tool()
async def list_users(ctx: Context) -> ListUsersResult:
    """List all users with their channels count. Admin only.
    Returns: name, role, max_channels, owned_channels_count for each user."""

@mcp.tool()
async def whoami(ctx: Context) -> WhoamiResult:
    """Show current user's profile: name, role, channels count / limit."""

@mcp.tool()
async def add_user_auth(
    user_id: str,
    auth_type: str,
    identifier: str,
    client_name: str | None = None,
    ctx: Context,
) -> AddUserAuthResult:
    """Add auth mapping for a user. Admin only.
    auth_type: 'api_key' | 'telegram' | 'mcp_token'
    identifier: raw value (will be hashed for api_key/mcp_token)."""

@mcp.tool()
async def remove_user_auth(
    mapping_id: str,
    ctx: Context,
) -> RemoveUserAuthResult:
    """Remove an auth mapping. Admin only."""
```

### 5.2 New Bot tools

Add to `tg_parser/bot/tools.py`:

- `_exec_register_user(args, current_user)` -- admin only
- `_exec_update_user(args, current_user)` -- admin only
- `_exec_list_users(args, current_user)` -- admin only
- `_exec_whoami(args, current_user)` -- any authenticated user
- `_exec_add_user_auth(args, current_user)` -- admin only
- `_exec_remove_user_auth(args, current_user)` -- admin only

Add corresponding entries to `_TOOL_EXECUTORS` dict and `TOOL_DECLARATIONS` for Gemini function calling.

### 5.3 New API routes

**New file:** `tg_parser/api/routes/users.py`

```python
router = APIRouter(prefix="/api/v1/users", tags=["Users"])

@router.get("")
async def list_users(user: CurrentUser = Depends(resolve_current_user)):
    """List all users. Admin only."""
    assert_admin(user)
    # UserRepo.list_users() + get_owned_channel_ids for each

@router.post("")
async def create_user(body: CreateUserRequest, user: CurrentUser = Depends(resolve_current_user)):
    """Register a new user. Admin only."""
    assert_admin(user)
    # UserRepo.create_user(...)

@router.get("/me")
async def get_current_user_info(user: CurrentUser = Depends(resolve_current_user)):
    """Current user's profile (whoami)."""
    # Return user info + owned channels count

@router.patch("/{user_id}")
async def update_user(user_id: str, body: UpdateUserRequest, user: CurrentUser = Depends(resolve_current_user)):
    """Update user. Admin only."""
    assert_admin(user)
    # UserRepo.update_user(...)

@router.delete("/{user_id}")
async def delete_user(user_id: str, user: CurrentUser = Depends(resolve_current_user)):
    """Delete user. Admin only."""
    assert_admin(user)
    # UserRepo.delete_user(...)
```

Register in `tg_parser/api/main.py`.

### 5.4 Bot UX for unregistered users

**File:** `tg_parser/bot/handlers.py`

Update `cmd_start` to check registration:
- If `current_user` exists and is not default admin -> show personalized greeting
- If user is unregistered -> "Вы не зарегистрированы. Обратитесь к администратору."

### 5.5 Migration helper: CLI command

`tg-parser migrate-users` -- one-time utility for existing deployments:

1. Create admin user (if not exists)
2. Map existing API keys from `settings.api_keys` to admin's auth_mappings (`auth_type='api_key'`, hashed)
3. Map existing MCP tokens from `settings.mcp_auth_tokens` to admin's auth_mappings (`auth_type='mcp_token'`, hashed)
4. Map existing `settings.bot_allowed_user_ids` to admin's auth_mappings (`auth_type='telegram'`)
5. Set `owner_id = admin.id` on all sources without owner

**Implementation:** Add CLI command to existing entry point (check `pyproject.toml` / `__main__.py` for CLI structure).

### 5.6 Tests Phase 5 (~15 tests)

**New file:** `tests/test_f4_user_management.py`

Tests to cover:
- `register_user` creates user with correct properties
- `register_user` rejected for non-admin
- `update_user` changes name/role/max_channels
- `list_users` shows all users with channel counts (admin only)
- `list_users` rejected for non-admin
- `whoami` returns correct profile for admin and regular user
- `add_user_auth` creates mapping (hashed for api_key/mcp_token, plain for telegram)
- `add_user_auth` rejected for non-admin
- `remove_user_auth` removes mapping
- `remove_user_auth` rejected for non-admin
- API `GET /api/v1/users/me` returns current user info
- API `POST /api/v1/users` admin-only enforcement
- API `DELETE /api/v1/users/{id}` cascade deletes auth mappings
- Migration script: creates admin, maps keys/tokens/user_ids, assigns owner_id
- Migration script: idempotent (safe to run twice)

---

## Critical files to read first

Before writing any code, read these files to understand current implementation:

1. `tg_parser/storage/ports.py` -- UserRepo ABC (create_user, update_user, add_auth_mapping, etc.)
2. `tg_parser/storage/sqlalchemy/user_repo.py` -- SAUserRepo implementation
3. `tg_parser/auth/models.py` -- CurrentUser dataclass
4. `tg_parser/auth/ownership.py` -- assert_admin, PermissionDenied (created in Session 2)
5. `tg_parser/auth/resolvers.py` -- resolve_user_by_auth, hash_credential, invalidate_user_cache
6. `tg_parser/mcp_server.py` -- existing MCP tools pattern (with ctx: Context after Session 2)
7. `tg_parser/bot/tools.py` -- existing bot tools pattern (with current_user after Session 2)
8. `tg_parser/bot/handlers.py` -- cmd_start handler
9. `tg_parser/api/main.py` -- router registration pattern
10. `tg_parser/api/routes/channels.py` -- example of resolve_current_user usage (after Session 2)
11. `tg_parser/config/settings.py` -- api_keys, mcp_auth_tokens, bot_allowed_user_ids (for migration)
12. `tg_parser/services/db_context.py` -- user_repo() context manager

---

## Verification checklist

After implementing Phase 5:

- [ ] `pytest` passes (existing + new ~15 tests)
- [ ] MCP `register_user` creates user correctly (admin only)
- [ ] MCP `whoami` shows correct profile
- [ ] MCP `list_users` returns all users with channel counts
- [ ] MCP `add_user_auth` creates hashed mapping for api_key
- [ ] API `GET /api/v1/users/me` returns current user info
- [ ] API `POST /api/v1/users` rejected for non-admin
- [ ] Bot `/start` shows registration status
- [ ] Migration script maps existing api_keys/mcp_tokens/bot_users
- [ ] Migration script is idempotent
- [ ] Cache invalidated after auth mapping changes
- [ ] Existing tests still pass (no regressions)

---

## References

- Full plan: `docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`
- Session 1 prompt: `docs/prompts/F4_MULTI_TENANCY_SESSION1_PROMPT.md`
- Session 2 prompt: `docs/prompts/F4_MULTI_TENANCY_SESSION2_PROMPT.md`
