# Session 3: F4 Multi-Tenancy -- Phase 5

## Purpose of this session

Implement Phase 5 of F4 Multi-Tenancy as described in the full plan at `docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`.

This is an **implementation session**. The plan is already agreed.

**Scope:** Phase 5 (User Management Tools + Migration Script)

---

## Baseline: what is already done (after Session 1 + Session 2)

- **Tests:** 1202 passed (including 98 F4-specific tests across 6 files), 0 failures
- **Branch:** `feature/f4-multi-tenancy-phase1-2`, commit `c58da84`
- **Phase 1 complete:** `users` + `user_auth_mappings` tables, `Source.owner_id`, `DocumentEmbedding.channel_ids`, `SAUserRepo`, Alembic migrations
- **Phase 2 complete:** `CurrentUser` dataclass, `tg_parser/auth/` package, `resolve_user_by_auth()`, `resolve_current_user()`, `UserResolutionMiddleware`, `BearerTokenVerifier`
- **Phase 3 complete:** Channel ownership enforcement across MCP/Bot/API -- `add_channel` sets `owner_id`, `remove/pause/resume` require owner or admin, `list_channels` scoped by owner, `max_channels` per-user limit, admin-only for `set_llm_config`/`reset_llm_config`/`reload_prompts`
- **Phase 4 complete:** Scoped data access -- `similarity_search` with `channel_ids` SQL filter, `retrieval_service.search/answer` with `allowed_channel_ids`, `topic_card_repo.list_by_channels()`, all MCP tools with `ctx: Context`, bot `current_user` propagation chain, all API routes with `resolve_current_user`, IVFFlat probes tuning, admin-only `/agents/*` endpoints

> **Note:** Confirm baseline by running `TEST_POSTGRES=1 pytest tests/` before starting. All 1202 tests must pass.

---

## Ready-made infrastructure (DO NOT recreate)

Phase 5 builds on top of existing components created in Phases 1-2. **Read them, use them, do not rewrite.**

### UserRepo ABC (`tg_parser/storage/ports.py`)

All methods already exist and are implemented in `SAUserRepo`:

| Method | Signature |
|--------|-----------|
| `create_user` | `async def create_user(self, name: str, role: str = "user", max_channels: int \| None = None) -> User` |
| `get_by_id` | `async def get_by_id(self, user_id: str) -> User \| None` |
| `update_user` | `async def update_user(self, user_id: str, *, name: str \| None = None, role: str \| None = None, max_channels: Any = ...) -> User \| None` |
| `delete_user` | `async def delete_user(self, user_id: str) -> bool` |
| `list_users` | `async def list_users(self) -> list[User]` |
| `resolve_auth` | `async def resolve_auth(self, auth_type: str, auth_identifier: str) -> User \| None` |
| `get_owned_channel_ids` | `async def get_owned_channel_ids(self, user_id: str) -> list[str]` |
| `add_auth_mapping` | `async def add_auth_mapping(self, user_id: str, auth_type: str, auth_identifier: str, client_name: str \| None = None) -> UserAuthMapping` |
| `remove_auth_mapping` | `async def remove_auth_mapping(self, mapping_id: str) -> bool` |

**Important:** `update_user` uses `...` (Ellipsis) as sentinel for `max_channels` -- `None` means "reset to global default", `...` means "don't change".

### Domain types (`tg_parser/storage/ports.py`)

```python
@dataclass
class User:
    id: str
    name: str
    role: str  # "admin" | "user"
    max_channels: int | None
    created_at: datetime
    updated_at: datetime

@dataclass
class UserAuthMapping:
    id: str
    user_id: str
    auth_type: str       # "api_key" | "telegram" | "mcp_token"
    auth_identifier: str  # hashed for api_key/mcp_token, plain for telegram
    client_name: str | None
    created_at: datetime
```

### Auth resolvers (`tg_parser/auth/resolvers.py`)

| Function | Purpose |
|----------|---------|
| `hash_credential(raw: str) -> str` | SHA-256 hex digest. Use for api_key and mcp_token before storing. |
| `invalidate_user_cache(auth_type: str, auth_identifier: str)` | Drop one entry from TTL cache. Call after add/remove auth mapping. |
| `resolve_user_by_auth(auth_type, auth_identifier) -> CurrentUser \| None` | TTL-cached (60s) lookup. `auth_identifier` must be **already hashed** for api_key/mcp_token. |
| `get_default_admin() -> CurrentUser` | Synthetic admin with `id="00000000-0000-0000-0000-000000000000"`. |
| `clear_cache()` | Clear entire cache (for tests). |

### DB context (`tg_parser/services/db_context.py`)

```python
@asynccontextmanager
async def user_repo() -> AsyncIterator[tuple[SAUserRepo, Database]]:
    """Short-lived session for user operations."""
```

### Ownership helpers (`tg_parser/auth/ownership.py`)

```python
class PermissionDenied(Exception): ...
async def assert_channel_access(user: CurrentUser, channel_id: str) -> None: ...
def assert_admin(user: CurrentUser) -> None: ...
def check_channel_limit(user: CurrentUser, current_count: int) -> None: ...
```

### Settings (`tg_parser/config/settings.py`)

| Field | Type | Purpose (for migration) |
|-------|------|------------------------|
| `api_keys` | `dict[str, str]` | Map of raw_key → client_name |
| `mcp_auth_tokens` | `dict[str, str]` | Map of raw_token → client_name |
| `bot_allowed_user_ids` | `list[int]` (property) | Parsed from `bot_allowed_users` comma string |
| `default_max_channels` | `int` (default 20) | Used when user has `max_channels=NULL` in DB |

---

## Phase 5: User Management Tools + Migration Script

### 5.1 New MCP tools

**File:** `tg_parser/mcp_server.py`

Add 6 new tools following the existing pattern (with `ctx: Context | None = None`):

#### 5.1.1 `register_user` -- Admin only

```python
@mcp.tool()
async def register_user(
    name: str,
    role: str = "user",
    max_channels: int | None = None,
    ctx: Context | None = None,
) -> RegisterUserResult:
    """Register a new user. Admin only.
    max_channels: per-user channel limit (None = use global default from settings)."""
    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return RegisterUserResult(success=False, user_id=None, message=e.message)

    async with user_repo() as (repo, _db):
        new_user = await repo.create_user(name, role, max_channels)

    return RegisterUserResult(
        success=True,
        user_id=new_user.id,
        message=f"User '{name}' created with role '{role}'.",
    )
```

Result model:
```python
class RegisterUserResult(BaseModel):
    success: bool
    user_id: str | None
    message: str
```

#### 5.1.2 `update_user` -- Admin only

```python
@mcp.tool()
async def update_user(
    user_id: str,
    name: str | None = None,
    role: str | None = None,
    max_channels: int | None = None,
    ctx: Context | None = None,
) -> UpdateUserResult:
    """Update user properties. Admin only.
    Only provided fields are changed. max_channels=None resets to global default."""
```

**Important:** `UserRepo.update_user` uses `...` sentinel for max_channels.
- If MCP caller provides `max_channels=None` → pass `max_channels=None` (reset to default)
- If MCP caller does NOT provide `max_channels` → pass `max_channels=...` (don't change)

Since MCP tool parameters don't support Ellipsis, use a convention: if all three optional params are None and the caller clearly wants to update something, treat max_channels=None as "don't change". **Better approach:** add a `reset_max_channels: bool = False` flag or document that `max_channels=0` is invalid and None means "don't change" while providing explicit value sets it. Pick the simplest approach that doesn't confuse the MCP user.

Result model:
```python
class UpdateUserResult(BaseModel):
    success: bool
    message: str
```

#### 5.1.3 `list_users` -- Admin only

```python
@mcp.tool()
async def list_users(ctx: Context | None = None) -> ListUsersResult:
    """List all users with their channel counts. Admin only."""
```

For each user, call `repo.get_owned_channel_ids(user.id)` to get channel count.

Result model:
```python
class UserInfo(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int | None
    owned_channels_count: int

class ListUsersResult(BaseModel):
    success: bool
    users: list[UserInfo]
    message: str = ""
```

#### 5.1.4 `whoami` -- Any authenticated user

```python
@mcp.tool()
async def whoami(ctx: Context | None = None) -> WhoamiResult:
    """Show current user's profile: name, role, channels count / limit."""
```

No admin check. Uses resolved user + `repo.get_owned_channel_ids(user.id)`.

Result model:
```python
class WhoamiResult(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int
    owned_channels: list[str]
    owned_channels_count: int
```

#### 5.1.5 `add_user_auth` -- Admin only

```python
@mcp.tool()
async def add_user_auth(
    user_id: str,
    auth_type: str,
    identifier: str,
    client_name: str | None = None,
    ctx: Context | None = None,
) -> AddUserAuthResult:
    """Add auth mapping for a user. Admin only.
    auth_type: 'api_key' | 'telegram' | 'mcp_token'
    identifier: raw value (hashed automatically for api_key/mcp_token)."""
```

Logic:
1. `assert_admin(user)`
2. Validate `auth_type` in `{"api_key", "telegram", "mcp_token"}`
3. For `api_key`/`mcp_token`: `hashed = hash_credential(identifier)` before storing
4. For `telegram`: store identifier as-is (plain string)
5. `repo.add_auth_mapping(user_id, auth_type, hashed_or_plain, client_name)`
6. `invalidate_user_cache(auth_type, hashed_or_plain)` to clear TTL cache

Result model:
```python
class AddUserAuthResult(BaseModel):
    success: bool
    mapping_id: str | None
    message: str
```

#### 5.1.6 `remove_user_auth` -- Admin only

```python
@mcp.tool()
async def remove_user_auth(
    mapping_id: str,
    ctx: Context | None = None,
) -> RemoveUserAuthResult:
    """Remove an auth mapping by ID. Admin only."""
```

Logic: `assert_admin(user)` → `repo.remove_auth_mapping(mapping_id)`.

Result model:
```python
class RemoveUserAuthResult(BaseModel):
    success: bool
    message: str
```

### 5.2 New Bot tools

**File:** `tg_parser/bot/tools.py`

Add 6 new `_exec_*` functions following the existing pattern:

```python
async def _exec_register_user(
    args: dict[str, Any], current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.ownership import PermissionDenied, assert_admin
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.db_context import user_repo

    user = current_user or await get_default_admin()
    try:
        assert_admin(user)
    except PermissionDenied as e:
        return {"error": e.message}

    async with user_repo() as (repo, _db):
        new_user = await repo.create_user(
            name=args["name"],
            role=args.get("role", "user"),
            max_channels=args.get("max_channels"),
        )
    return {"user_id": new_user.id, "name": new_user.name, "role": new_user.role}
```

Same pattern for:
- `_exec_update_user(args, current_user)` -- admin only
- `_exec_list_users(args, current_user)` -- admin only
- `_exec_whoami(args, current_user)` -- **any user** (no assert_admin)
- `_exec_add_user_auth(args, current_user)` -- admin only, hash for api_key/mcp_token
- `_exec_remove_user_auth(args, current_user)` -- admin only

**Update `_TOOL_EXECUTORS` dict** (~line 1343):

```python
_TOOL_EXECUTORS: dict[str, Any] = {
    # ... existing entries ...
    "register_user": _exec_register_user,
    "update_user": _exec_update_user,
    "list_users": _exec_list_users,
    "whoami": _exec_whoami,
    "add_user_auth": _exec_add_user_auth,
    "remove_user_auth": _exec_remove_user_auth,
}
```

**Update `TOOL_DECLARATIONS` list** -- add Gemini function-calling declarations:

```python
{
    "name": "register_user",
    "description": "Register a new user (admin only). Creates user with specified name, role, and channel limit.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "User display name"},
            "role": {"type": "string", "enum": ["user", "admin"], "description": "User role (default: user)"},
            "max_channels": {"type": "integer", "description": "Max channels limit (omit for global default)"},
        },
        "required": ["name"],
    },
},
```

Add similar declarations for `update_user`, `list_users`, `whoami`, `add_user_auth`, `remove_user_auth`.

### 5.3 New API routes

**New file:** `tg_parser/api/routes/users.py`

```python
router = APIRouter(prefix="/api/v1/users", tags=["Users"])
```

#### Endpoints:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/users` | Admin only | List all users with owned channel counts |
| `POST` | `/api/v1/users` | Admin only | Create user |
| `GET` | `/api/v1/users/me` | Any user | Current user profile + owned channels |
| `PATCH` | `/api/v1/users/{user_id}` | Admin only | Update user name/role/max_channels |
| `DELETE` | `/api/v1/users/{user_id}` | Admin only | Delete user (cascades auth mappings) |

**Pydantic schemas** (in the same file):

```python
class CreateUserRequest(BaseModel):
    name: str
    role: str = "user"
    max_channels: int | None = None

class UpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    max_channels: int | None = None

class UserResponse(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int | None
    owned_channels_count: int
    created_at: datetime

class UserMeResponse(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int
    owned_channels: list[str]
    owned_channels_count: int
```

**IMPORTANT: `/me` route must be declared BEFORE `/{user_id}`** in the router to avoid FastAPI matching "me" as a user_id.

**Register in `tg_parser/api/main.py`:**

```python
from tg_parser.api.routes import users_router
# ...
app.include_router(users_router)
```

Also update `tg_parser/api/routes/__init__.py` to export `users_router`.

### 5.4 Bot UX for unregistered users

**File:** `tg_parser/bot/handlers.py`

Update `cmd_start` to accept `current_user` and show registration status:

```python
@router.message(Command("start"))
async def cmd_start(message: Message, current_user: CurrentUser | None = None) -> None:
    if current_user is None or current_user.id == "00000000-0000-0000-0000-000000000000":
        await message.answer(
            "Вы не зарегистрированы в системе. Обратитесь к администратору для получения доступа.",
        )
        return

    greeting = (
        f"Привет, {current_user.name}! 👋\n\n"
        f"Роль: {current_user.role}\n"
        f"Каналов: {len(current_user.allowed_channel_ids) if current_user.allowed_channel_ids else 'все'}\n\n"
        "Отправьте текстовое сообщение для начала работы."
    )
    await message.answer(greeting, parse_mode="HTML")
```

The default admin UUID `00000000-0000-0000-0000-000000000000` indicates a synthetic fallback user (no real DB record), which means the Telegram user was not found in auth mappings.

### 5.5 Migration helper: CLI command

**New file:** `tg_parser/cli/migrate_users_cmd.py`

```python
"""
One-time migration: map existing API keys, MCP tokens, and bot user IDs
to the multi-tenancy user model.
"""

async def run_migrate_users(dry_run: bool = False) -> dict[str, Any]:
    """
    1. Create admin user (if not exists)
    2. Map settings.api_keys -> add_auth_mapping(admin, 'api_key', hash(key), client_name)
    3. Map settings.mcp_auth_tokens -> add_auth_mapping(admin, 'mcp_token', hash(token), client_name)
    4. Map settings.bot_allowed_user_ids -> add_auth_mapping(admin, 'telegram', str(uid))
    5. UPDATE sources SET owner_id = admin.id WHERE owner_id IS NULL
    """
```

**Register in `tg_parser/cli/app.py`:**

```python
@app.command(name="migrate-users")
def migrate_users(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes"),
):
    """Migrate existing API keys, MCP tokens, and bot user IDs to multi-tenancy user model.
    
    One-time utility for existing deployments upgrading to F4 multi-tenancy.
    Safe to run multiple times (idempotent).
    """
    import asyncio
    from tg_parser.cli.migrate_users_cmd import run_migrate_users

    typer.echo("🔄 Migrating to multi-tenancy user model...\n")
    if dry_run:
        typer.echo("   ⚠️  Dry-run mode: no changes will be made\n")

    try:
        stats = asyncio.run(run_migrate_users(dry_run=dry_run))
        # Print stats...
    except Exception as e:
        typer.echo(f"\n❌ Migration error: {e}", err=True)
        raise typer.Exit(code=1) from e
```

**Idempotency strategy:**

For each auth mapping, before calling `add_auth_mapping`, check if it already exists via `repo.resolve_auth(auth_type, hashed_identifier)`. If found, skip. This avoids unique constraint errors on repeated runs.

For `owner_id` assignment: `UPDATE sources SET owner_id = :admin_id WHERE owner_id IS NULL` is naturally idempotent.

**Migration flow:**

```
1. async with user_repo() as (repo, _db):
2.   admin = await repo.resolve_auth("api_key", hash_credential(first_api_key))
3.   if not admin:
4.       admin_user = await repo.create_user("admin", role="admin")
5.   else:
6.       admin_user = admin  # reuse existing
7.
8.   for raw_key, client_name in settings.api_keys.items():
9.       hashed = hash_credential(raw_key)
10.      existing = await repo.resolve_auth("api_key", hashed)
11.      if not existing:
12.          await repo.add_auth_mapping(admin_user.id, "api_key", hashed, client_name)
13.          mapped_api_keys += 1
14.
15.  # Same for mcp_auth_tokens...
16.  # Same for bot_allowed_user_ids (no hashing, plain str(uid))...
17.
18.  # Assign orphan sources
19.  result = await session.execute(
20.      text("UPDATE sources SET owner_id = :admin_id WHERE owner_id IS NULL"),
21.      {"admin_id": admin_user.id},
22.  )
23.  orphan_sources = result.rowcount
```

### 5.6 Tests Phase 5

**New file:** `tests/test_f4_user_management.py` (~15+ tests)

#### MCP tool tests (6):

```python
class TestMCPRegisterUser:
    async def test_register_user_creates_user(self):
        """Admin registers new user -> success, user_id returned."""

    async def test_register_user_rejected_for_non_admin(self):
        """Non-admin -> success=False, 'Admin' in message."""

class TestMCPUpdateUser:
    async def test_update_user_changes_properties(self):
        """Admin updates user name/role -> success."""

class TestMCPListUsers:
    async def test_list_users_returns_all_with_counts(self):
        """Admin sees all users with owned_channels_count."""

    async def test_list_users_rejected_for_non_admin(self):
        """Non-admin -> success=False."""

class TestMCPWhoami:
    async def test_whoami_returns_profile(self):
        """Any user sees their own profile."""
```

#### Auth mapping tests (3):

```python
class TestMCPUserAuth:
    async def test_add_auth_hashes_api_key(self):
        """add_user_auth('api_key', raw_key) -> stored as hash_credential(raw_key)."""

    async def test_add_auth_plain_telegram(self):
        """add_user_auth('telegram', '12345') -> stored as '12345' (no hashing)."""

    async def test_remove_auth_mapping(self):
        """remove_user_auth(mapping_id) -> removed."""
```

#### Bot tool tests (2):

```python
class TestBotWhoami:
    async def test_exec_whoami_returns_profile(self):
        """_exec_whoami with regular user -> correct profile dict."""

class TestBotRegisterUser:
    async def test_exec_register_user_rejected_for_non_admin(self):
        """Non-admin -> {'error': 'Admin access required'}."""
```

#### API tests (3):

```python
class TestAPIUsers:
    async def test_get_me_returns_profile(self):
        """GET /api/v1/users/me -> current user info."""

    async def test_create_user_admin_only(self):
        """POST /api/v1/users -> 403 for non-admin."""

    async def test_delete_user_cascades(self):
        """DELETE /api/v1/users/{id} -> user and mappings removed."""
```

#### Migration tests (3):

```python
class TestMigrateUsers:
    async def test_migration_creates_admin_and_maps(self):
        """Fresh migration: creates admin, maps keys/tokens/uids, assigns owner_id."""

    async def test_migration_idempotent(self):
        """Running twice produces same result, no errors."""

    async def test_migration_empty_settings(self):
        """No api_keys/mcp_tokens/bot_users -> creates admin, no mappings."""
```

**Mocking pattern** for tests (same as existing F4 tests):

```python
@patch("tg_parser.mcp_server.resolve_mcp_user")
async def test_register_user_creates_user(self, mock_resolve):
    mock_resolve.return_value = _admin()

    mock_repo = AsyncMock()
    mock_repo.create_user.return_value = MagicMock(id="new-id", name="alice", role="user")

    @asynccontextmanager
    async def fake_user_repo():
        yield (mock_repo, MagicMock())

    with patch("tg_parser.services.db_context.user_repo", fake_user_repo):
        from tg_parser.mcp_server import register_user
        result = await register_user("alice", ctx=None)

    assert result.success is True
    assert result.user_id == "new-id"
    mock_repo.create_user.assert_awaited_once_with("alice", "user", None)
```

---

## Critical files to read first

Before writing any code, read these files to understand current implementation:

1. `tg_parser/storage/ports.py` -- UserRepo ABC (all method signatures), User + UserAuthMapping dataclasses
2. `tg_parser/storage/sqlalchemy/user_repo.py` -- SAUserRepo implementation (SQL patterns, commit behavior)
3. `tg_parser/auth/models.py` -- CurrentUser dataclass (`id`, `name`, `role`, `allowed_channel_ids`, `max_channels`, `is_admin`)
4. `tg_parser/auth/ownership.py` -- `assert_admin`, `PermissionDenied` (created in Session 2)
5. `tg_parser/auth/resolvers.py` -- `resolve_user_by_auth`, `hash_credential`, `invalidate_user_cache`, `get_default_admin`
6. `tg_parser/services/db_context.py` -- `user_repo()` context manager
7. `tg_parser/mcp_server.py` -- existing MCP tools pattern (with `ctx: Context` after Session 2), `resolve_mcp_user()`, result model pattern
8. `tg_parser/bot/tools.py` -- existing `_exec_*` pattern (with `current_user` after Session 2), `_TOOL_EXECUTORS` dict, `TOOL_DECLARATIONS` list
9. `tg_parser/bot/handlers.py` -- `cmd_start` handler (currently just sends static text)
10. `tg_parser/api/main.py` -- router registration pattern, PermissionDenied handler
11. `tg_parser/api/routes/__init__.py` -- router exports
12. `tg_parser/api/routes/channels.py` -- example of `resolve_current_user` + `assert_admin` usage (reference for users.py)
13. `tg_parser/config/settings.py` -- `api_keys`, `mcp_auth_tokens`, `bot_allowed_user_ids`, `default_max_channels`
14. `tg_parser/cli/app.py` -- CLI command registration pattern (Typer)

---

## Recommended implementation order

Work in this order to minimize broken intermediate states:

1. **MCP result models** -- define all 6 Pydantic result models in `mcp_server.py`
2. **MCP tools** -- add 6 new `@mcp.tool()` functions
3. **Bot tools** -- add 6 new `_exec_*` + `_TOOL_EXECUTORS` entries + `TOOL_DECLARATIONS`
4. **API routes** -- create `users.py`, register in `main.py` and `__init__.py`
5. **Bot UX** -- update `cmd_start` in `handlers.py`
6. **Migration CLI** -- create `migrate_users_cmd.py`, register in `app.py`
7. **Tests** -- `test_f4_user_management.py` (~15+ tests)
8. **Full test suite** -- `TEST_POSTGRES=1 pytest tests/` -- verify 0 failures, 0 regressions

---

## Key implementation details

### Hashing policy

- `api_key` / `mcp_token` → `hash_credential(raw)` (SHA-256) before storing in `auth_identifier`
- `telegram` → store plain string `str(telegram_user_id)` (no hashing)
- This matches the existing `resolve_user_by_auth()` expectations

### Cache invalidation

After any `add_user_auth` or `remove_user_auth`:

```python
from tg_parser.auth.resolvers import hash_credential, invalidate_user_cache

hashed = hash_credential(identifier) if auth_type in ("api_key", "mcp_token") else identifier
invalidate_user_cache(auth_type, hashed)
```

### update_user sentinel

`UserRepo.update_user(user_id, *, name=None, role=None, max_channels=...)` uses `...` (Ellipsis) as sentinel:
- `max_channels=...` → don't change
- `max_channels=None` → reset to NULL (global default)
- `max_channels=42` → set to 42

For MCP/Bot/API, decide a simple convention: if the caller omits `max_channels`, pass `...` (don't change). If they explicitly set it, pass the value.

### Default admin detection in bot `/start`

`get_default_admin()` returns `CurrentUser(id="00000000-0000-0000-0000-000000000000", ...)`. This UUID indicates a synthetic fallback = user not found in DB. Check for this specific ID to detect unregistered users.

---

## Verification checklist

After implementing Phase 5:

- [ ] `TEST_POSTGRES=1 pytest tests/` passes (existing 1202 + new ~15 tests = ~1217)
- [ ] MCP `register_user` creates user correctly (admin only)
- [ ] MCP `update_user` changes name/role/max_channels
- [ ] MCP `list_users` returns all users with channel counts (admin only)
- [ ] MCP `whoami` shows correct profile for any authenticated user
- [ ] MCP `add_user_auth` creates hashed mapping for api_key, plain for telegram
- [ ] MCP `remove_user_auth` removes mapping and invalidates cache
- [ ] Bot `_exec_whoami` works for any user
- [ ] Bot `_exec_register_user` rejected for non-admin
- [ ] API `GET /api/v1/users` admin-only
- [ ] API `POST /api/v1/users` admin-only
- [ ] API `GET /api/v1/users/me` returns current user info
- [ ] API `PATCH /api/v1/users/{id}` admin-only
- [ ] API `DELETE /api/v1/users/{id}` cascades auth mappings
- [ ] Bot `/start` shows registration status (personalized or "not registered")
- [ ] Migration script creates admin, maps api_keys/mcp_tokens/bot_users
- [ ] Migration script is idempotent (safe to run twice)
- [ ] Migration script handles empty settings gracefully
- [ ] Cache invalidated after auth mapping changes
- [ ] Existing 1202 tests still pass (no regressions)

---

## References

- Full plan: `docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`
- Session 1 prompt: `docs/prompts/F4_MULTI_TENANCY_SESSION1_PROMPT.md`
- Session 2 prompt: `docs/prompts/F4_MULTI_TENANCY_SESSION2_PROMPT.md`
- Session 2 handoff: `docs/notes/F4_SESSION2_HANDOFF.md`
