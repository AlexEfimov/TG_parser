# Fix Sprint — BUG-001 MCP auth identity extraction (Session C, 2026-04-28)

**Назначение:** закрывает Critical-баг **BUG-001** —
`Context.client_id` в FastMCP читает client-supplied `_meta.client_id`
из JSON-RPC вместо реальной OAuth/Bearer-идентичности, что приводит к
silent fallback'у на synthetic admin (`00000000-…`) для всех
аутентифицированных вызовов.

**Тип сессии:** writing — code, tests, PR. Изолированный security-track,
**не зависит** от bot-FSM-сессий и может выполняться параллельно с
Session D в отдельном worktree, если есть multi-developer setup.

**Дата подготовки промпта:** 2026-04-27 (одновременно со всем BUG-fix-rosters).

**Когда использовать:** **только** после того как:

1. Phase 1 sprint и Phase 2 sprint завершены (post-watch report committed);
2. Session B+ landed (mitigations) — **рекомендуется**, но не блокирующее
   (mitigations и BUG-001 на разных code path'ах);
3. `BUG_LOG.md` § BUG-001 прочитан целиком, root cause подтверждён.

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/BUG_LOG.md` § BUG-001 — целиком, **особенно**:
   - § «Root cause (проверенный)» — `ctx.client_id` читает не тот атрибут.
   - § «Bonus-мина (вторая, ниже по severity)» — `mcp_auth_enabled` AND
     `mcp_auth_tokens` cabinetry; будет частью fix'а как BUG-001b.
2. `docs/notes/BUG_LOG.md` § Session planning — context, dependencies graph.
3. `tg_parser/mcp_server.py:148–243` — `BearerTokenVerifier`,
   `create_mcp_server`, `resolve_mcp_user`. Эти три функции и их 30+
   call-site'ов — ключевая поверхность.
4. `tg_parser/auth/resolvers.py:1–120` — `resolve_user_by_auth`,
   `get_default_admin`, `_DEFAULT_ADMIN_ID`. Понять текущие сигнатуры,
   решить — менять `resolve_mcp_user` сигнатуру или внутреннюю логику.
5. `tg_parser/config/settings.py:330–360` — `mcp_auth_enabled`,
   `mcp_auth_tokens` (через `parse_json_dict`); понять, как баг с
   silent JSON-parse-failure'ом мог приводить к BUG-001b.
6. **MCP SDK source** для понимания контракта (через локальный venv):
   - `.venv/lib/python*/site-packages/mcp/server/fastmcp/server.py`
     — `Context.client_id` property (≈ L1285-1290).
   - `.venv/lib/python*/site-packages/mcp/server/auth/middleware/auth_context.py`
     — `auth_context_var` contextvar.
   - `.venv/lib/python*/site-packages/mcp/server/auth/middleware/bearer_auth.py`
     — как middleware кладёт `AuthenticatedUser` в scope.
7. `tests/test_f4_auth_resolution.py` — текущий blind-spot (см.
   BUG-001 § Why CI didn't catch).
8. `tests/test_mcp_management.py` — где `resolve_mcp_user` мокается;
   эти моки потенциально маскировали баг, придётся их тоже починить.

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. На main, working tree чист
git checkout main
git pull --ff-only origin main
git status --short

# 2. Phase 1 + Phase 2 + Session B+ уже landed
rg "Phase 2 landing log|Session B\+" docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md \
    docs/notes/BUG_LOG.md

# 3. Baseline pytest зелёный
.venv/bin/pytest -q 2>&1 | tail -20

# 4. Reproduce баг локально (sanity-проверка root cause):
#    Запустить локальный MCP-сервер с MCP_AUTH_ENABLED=true и валидным токеном,
#    дёрнуть `whoami` через mcp-remote — ожидать synthetic admin response.
#    Это смоук-проверка что мы чиним то, что наблюдалось.

# 5. Branch
git checkout -b fix/bug-001-mcp-auth-identity-2026-04-28
```

### 1.3 Gating decisions (must answer before code-changes)

| ID | Вопрос | Default per BUG_LOG § Session planning |
|---|---|---|
| C-1 | Менять сигнатуру `resolve_mcp_user(client_id: str \| None)` или внутреннюю логику? | **Внутреннюю логику** — добавить helper `_extract_authenticated_user_id(ctx)` который читает scope/contextvar; `resolve_mcp_user` параметр становится legacy fallback. Меньше mass-edit'а на 30+ call-site'ах. |
| C-2 | Что делать с silent fallback на default admin при `client_id=None`? | **Fail-loud** — если `mcp_auth_enabled=true` И extracted user-id=None → raise `AuthenticationError`; SDK middleware перехватит в 401. Default admin path остаётся **только** для `mcp_auth_enabled=false` (dev-mode). |
| C-3 | Чинить BUG-001b (cabinetry в `create_mcp_server`) в этом же PR? | **Да, тем же PR'ом** — это часть auth-flow и коротко (~15 строк). Не разделять. |
| C-4 | Логирование auth-decision'ов (для будущей debug'а)? | **Да, structlog `auth.identity_extracted`** с полями: `transport`, `auth_enabled`, `extracted_user_id`, `fallback_used`. Без PII (только UUID). |

Если у юзера нет blessing'а — взять default и явно сообщить в финальном
summary.

### 1.4 Branch / PR strategy

**Один большой PR**, потому что fix трогает:
- security-critical helper (`_extract_authenticated_user_id`),
- 30+ call-site'ов через mass-replacement (`ctx.client_id if ctx else None`
  → `_extract_authenticated_user_id(ctx)`),
- `create_mcp_server` cabinetry (BUG-001b),
- 2-3 интеграционных теста.

Логически — единое security-fix. Дробить на N PR'ов = повышать window'ы
inconsistency в проде между PR'ами.

- Branch: `fix/bug-001-mcp-auth-identity-2026-04-28`.
- PR title: `fix(bug-001): extract real authenticated identity from MCP context`.
- PR labels: `bug-fix`, `bug-001`, `security`, `mcp_server`.

---

## 2. Out of scope

| Категория | Куда отложить | Причина |
|---|---|---|
| **OAuth flow / refresh-token / token rotation** | future security TD | BUG-001 — это identity extraction, не token lifecycle |
| **Rate limiting per user** | отдельный TD | Не требуется для closure'а BUG-001 |
| **Audit log для auth-events** | отдельный TD (опционально следующая сессия) | Logging C-4 default достаточен; persistent audit — больше work |
| **Multi-tenant isolation** | отдельный sprint после нескольких use-case реальных tenant'ов | Сейчас single-tenant; isolation overkill |
| **WebSocket-transport auth** | отдельный TD если когда-нибудь будет | Сейчас только HTTP/JSON-RPC |
| **`prompts/bot.yaml` / bot-side identity** | другой track | Bot не идёт через MCP-auth (другая модель) |
| **Изменение схемы `users` / `user_auth` таблиц** | wontfix | Schema корректна; меняется только extraction-logic |

---

## 3. Sprint scope (Session C)

### 3.1 Helper: `_extract_authenticated_user_id`

**Files to touch:**

- `tg_parser/mcp_server.py` (новая функция, ≈ L240-280):

  ```python
  async def _extract_authenticated_user_id(ctx: Context | None) -> str | None:
      """Extract real authenticated user-id from MCP context.

      Resolution order:
      1. ScopedAuthenticatedUser from ASGI scope (if BearerTokenVerifier ran).
      2. auth_context_var contextvar (set by auth middleware).
      3. None — caller must decide between fail-loud or dev-mode fallback.

      Does NOT read ctx.client_id — that field is JSON-RPC params._meta,
      attacker-controlled. See BUG-001.
      """
      if ctx is None:
          return None

      # Try scope-based extraction (HTTP/SSE transport).
      try:
          request = ctx.request_context.request
          scope = request.scope if request else None
          if scope:
              user = scope.get("user")
              if user is not None and hasattr(user, "client_id"):
                  return str(user.client_id)
      except (AttributeError, RuntimeError):
          pass

      # Try contextvar-based extraction (alternative path).
      try:
          from mcp.server.auth.middleware.auth_context import auth_context_var
          token = auth_context_var.get()
          if token is not None and hasattr(token, "client_id"):
              return str(token.client_id)
      except (LookupError, ImportError):
          pass

      return None
  ```

  **Important**: точный API extraction зависит от MCP SDK версии. Перед
  фиксацией кода **прочитать** `.venv/.../mcp/server/auth/middleware/`
  и подтвердить какие контракты доступны в нашей версии. Возможные
  shape'ы: `AccessToken` vs `AuthenticatedUser` vs `ScopedAuthenticatedUser`.

### 3.2 Refactor `resolve_mcp_user` для fail-loud

**Files to touch:**

- `tg_parser/mcp_server.py:202–243` — изменить:

  ```python
  async def resolve_mcp_user(client_id: str | None = None):
      """Resolve a CurrentUser from authenticated identity.

      Identity extraction must happen at call-site via
      _extract_authenticated_user_id(ctx); this function takes the
      already-extracted id (or None for dev-mode fallback).
      """
      from tg_parser.auth.resolvers import get_default_admin
      from tg_parser.config import get_settings

      settings = get_settings()

      # Production-mode: auth enabled + identity must be present.
      if settings.mcp_auth_enabled:
          if client_id is None:
              raise PermissionError(
                  "MCP auth enabled but no authenticated identity in context. "
                  "See BUG-001."
              )
          # ... existing DB-lookup path with the real client_id ...

      # Dev-mode: auth disabled → default admin only.
      logger.debug("resolve_mcp_user: dev-mode fallback to default admin")
      return await get_default_admin()
  ```

### 3.3 Call-site mass-replacement

**Files to touch:**

- `tg_parser/mcp_server.py` — все 30+ строк
  `user = await resolve_mcp_user(ctx.client_id if ctx else None)`
  заменить на:

  ```python
  user_id = await _extract_authenticated_user_id(ctx)
  user = await resolve_mcp_user(user_id)
  ```

  (можно через `sed` / IDE multi-cursor; **обязательно** ручной review
  каждого hit'а — некоторые могут быть в специальных context'ах.)

  **Verification после mass-edit:**

  ```bash
  rg -n "ctx\.client_id" tg_parser/mcp_server.py
  # Ожидаемо: пусто (все use-case'ы перешли на helper).
  ```

### 3.4 Fix BUG-001b — token-verifier cabinetry

**Files to touch:**

- `tg_parser/mcp_server.py:189–194`:

  ```python
  # СТАРОЕ (BUG-001b):
  # if settings.mcp_auth_enabled and settings.mcp_auth_tokens:

  # НОВОЕ:
  if settings.mcp_auth_enabled:
      if not settings.mcp_auth_tokens:
          raise RuntimeError(
              "MCP_AUTH_ENABLED=true but MCP_AUTH_TOKENS is empty. "
              "Either provide tokens or disable auth. See BUG-001b."
          )
      kwargs["token_verifier"] = BearerTokenVerifier(settings.mcp_auth_tokens)
      kwargs["auth"] = AuthSettings(...)
  ```

  Server **НЕ запускается** с inconsistent config'ом вместо silent
  «всё anonymous → admin» fallback'а.

### 3.5 Logging (C-4 default)

**Files to touch:**

- `tg_parser/mcp_server.py` — внутри `_extract_authenticated_user_id`:

  ```python
  logger.info(
      "mcp.auth.identity_extracted",
      transport=...,
      auth_enabled=settings.mcp_auth_enabled,
      extracted_user_id=result,
      fallback_used=(result is None),
  )
  ```

  Без PII (только UUID-форма user_id).

### 3.6 Tests

**Files to touch:**

- `tests/test_f4_auth_resolution.py` — добавить новые testcase'ы:
  - `test_extract_authenticated_user_id_from_scope_user` — мок ASGI scope
    с `AuthenticatedUser`, ожидать корректное extraction.
  - `test_extract_authenticated_user_id_from_contextvar` — мок
    `auth_context_var`, ожидать корректное extraction.
  - `test_extract_authenticated_user_id_no_auth_returns_none` — пустой
    ctx → None.
  - `test_extract_authenticated_user_id_does_not_read_meta_client_id` —
    ctx.request_context.meta.client_id="evil_id", scope.user отсутствует
    → return None (или auth-error в production-mode); НЕ "evil_id".

- `tests/test_mcp_auth_integration.py` (новый файл, integration-level):
  - **Происходит через httpx + mcp-remote-эмуляцию**:
    - case 1: bearer-токен валидный → `whoami` возвращает реального user'а.
    - case 2: bearer-токен невалидный → 401.
    - case 3: bearer-токен отсутствует, `mcp_auth_enabled=true` →
      `whoami` возвращает 401 (не synthetic admin!).
    - case 4: `mcp_auth_enabled=false` → `whoami` возвращает default admin
      (dev-mode fallback по C-2 default).
    - case 5: `mcp_auth_enabled=true`, токены пустые → server fail-loud при
      startup (BUG-001b).

- `tests/test_mcp_management.py` — **снять `@patch("tg_parser.mcp_server.resolve_mcp_user")`**
  декораторы (или большинство из них) и заменить на использование realistic
  bearer-фикстуры. Это закрывает blind-spot, документированный в BUG-001
  § Why CI didn't catch.

  **Aggressive scope warning:** возможно потребуется ~20-30 теста переписать;
  если объём слишком большой — оставить часть моков, но **минимум 5-7
  ключевых тестов** должны идти через realistic auth-flow.

---

## 4. Per-step playbook

### 4.1 Helper extraction (3.1) — playbook

```bash
# 1. Прочитать MCP SDK
ls .venv/lib/python*/site-packages/mcp/server/auth/middleware/
cat .venv/lib/python*/site-packages/mcp/server/auth/middleware/bearer_auth.py
cat .venv/lib/python*/site-packages/mcp/server/auth/middleware/auth_context.py

# 2. Подтвердить shape — `AuthenticatedUser` или `AccessToken`?
#    Записать в commit-message что увидели.

# 3. Реализовать helper, добавить unit-тесты в test_f4_auth_resolution.

# 4. Smoke-тест
.venv/bin/pytest tests/test_f4_auth_resolution.py -q -v

# 5. Commit (НЕ landing — продолжаем до 3.6)
git add tg_parser/mcp_server.py tests/
git commit -m "fix(bug-001) part 1/4: add _extract_authenticated_user_id helper

Helper reads identity from ASGI scope (BearerTokenVerifier-populated)
or auth_context_var contextvar; explicitly does NOT read ctx.client_id
which is attacker-controlled JSON-RPC _meta field.

Refs: BUG_LOG.md BUG-001, Session C."
```

### 4.2 resolve_mcp_user fail-loud (3.2) + cabinetry (3.4)

```bash
# 1. Edit mcp_server.py:202-243 (resolve_mcp_user)
# 2. Edit mcp_server.py:189-194 (cabinetry)

# 3. Tests (всё ещё на старых call-site'ах через моки — это ОК на этом шаге)
.venv/bin/pytest tests/test_f4_auth_resolution.py -q -v

# 4. Commit
git commit -m "fix(bug-001) part 2/4: resolve_mcp_user fail-loud + cabinetry

resolve_mcp_user now requires non-None client_id when mcp_auth_enabled
is true (raises PermissionError). create_mcp_server fails loudly at
startup if MCP_AUTH_ENABLED=true but MCP_AUTH_TOKENS is empty
(was: silent admin-fallback, BUG-001b).

Refs: BUG_LOG.md BUG-001 + BUG-001b, Session C."
```

### 4.3 Mass-replacement (3.3)

```bash
# 1. Audit hits
rg -n "ctx\.client_id" tg_parser/mcp_server.py

# 2. Apply replacement (manually OR via sed):
# Pattern: user = await resolve_mcp_user(ctx.client_id if ctx else None)
# Replace: user_id = await _extract_authenticated_user_id(ctx)
#          user = await resolve_mcp_user(user_id)

# 3. Verify
rg -n "ctx\.client_id" tg_parser/mcp_server.py  # должно быть пусто

# 4. Smoke
.venv/bin/pytest tests/test_mcp_management.py -q  # моки ещё на месте,
#                                                    тесты должны пройти

# 5. Commit
git commit -m "fix(bug-001) part 3/4: replace 30+ call-sites with helper

Mass-replacement of 'ctx.client_id if ctx else None' pattern across
all MCP tool handlers in mcp_server.py. Each call-site now reads
identity through _extract_authenticated_user_id which provides the
correct extraction.

Refs: BUG_LOG.md BUG-001, Session C."
```

### 4.4 Integration tests + de-mocking (3.6)

```bash
# 1. Создать tests/test_mcp_auth_integration.py
#    (или дополнить существующий test_f4_auth_resolution.py)

# 2. Снять @patch'и в test_mcp_management.py выборочно

# 3. Full pytest sweep
.venv/bin/pytest -q 2>&1 | tail -30
# Ожидаемо: count = baseline + N новых тестов (≥ 5)

# 4. Commit
git commit -m "fix(bug-001) part 4/4: integration tests + de-mock CI blind-spot

Adds end-to-end auth tests via httpx+mcp-remote emulation; covers
real bearer-flow, missing-token rejection (no silent admin fallback),
and BUG-001b cabinetry. Removes @patch(resolve_mcp_user) decorators
in critical test_mcp_management cases — this was the blind-spot
that hid BUG-001 from CI.

Refs: BUG_LOG.md BUG-001 § 'Why CI didn't catch', Session C."
```

---

## 5. Testing & verification (full run)

```bash
# Full pytest suite после landing'а всех 4 частей
.venv/bin/pytest -q 2>&1 | tail -20
# Ожидаемо: count ≥ baseline + 5-10.

# Specific auth-test sweep
.venv/bin/pytest tests/test_f4_*.py tests/test_mcp_auth_*.py -q -v

# Verify mass-replacement
rg -n "ctx\.client_id" tg_parser/mcp_server.py
# Ожидаемо: empty.

# Verify cabinetry
.venv/bin/python -c "
import os
os.environ['MCP_AUTH_ENABLED'] = 'true'
os.environ['MCP_AUTH_TOKENS'] = ''  # empty
from tg_parser.mcp_server import create_mcp_server
try:
    create_mcp_server()
    print('FAIL: should have raised')
except RuntimeError as e:
    print(f'OK: cabinetry working: {e}')
"
```

Manual smoke (на dev-окружении или staging):

1. Запустить локальный MCP-сервер с `MCP_AUTH_ENABLED=true` и валидным токеном.
2. Через `mcp-remote` или `curl + bearer header`:
   - `whoami` → ожидать реального user'а (UUID из `users` table), **НЕ**
     `00000000-...`.
3. Через `add_channel(channel_id="some_test_xyz")`:
   - Должен пройти foreign-key check (owner_id — реальный UUID).
4. Без bearer-токена:
   - HTTP 401 (или MCP-error «authentication required»), **НЕ** silent admin.

---

## 6. PR / commit conventions

- **PR title**: `fix(bug-001): extract real authenticated identity from MCP context`.
- **PR body** должен содержать:
  - Цель: closure'е BUG-001 (Critical).
  - Reference на BUG_LOG.md § BUG-001 + § BUG-001b.
  - Список изменённых call-site'ов (~30+).
  - Подтверждение что blind-spot из § Why CI didn't catch закрыт
    integration-тестами.
  - Security advisory note: «До этого PR'а MCP-сервер с `auth_enabled=true`
    silently authenticated **все** запросы как admin».
- **CHANGELOG entry**:
  ```markdown
  ## Bug fix BUG-001 — MCP auth identity extraction (2026-04-28)

  ### Critical security fix

  MCP-сервер до этого фикса читал identity из JSON-RPC params._meta,
  что давало любому unauthenticated клиенту admin-доступ при
  включённом MCP_AUTH_ENABLED. Identity теперь корректно извлекается
  из ASGI scope.user / auth_context_var. См. BUG_LOG.md BUG-001.
  ```
- **Commit footer на финальном merge-commit'е**:
  `Refs: BUG_LOG.md BUG-001, Session C. Closes: BUG-001 + BUG-001b.`
- **PR labels**: `bug-fix`, `bug-001`, `security`, `critical`, `mcp_server`.

---

## 7. Acceptance criteria

Session C считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 gating decisions C-1..C-4 закрыты (default или explicit blessing)
- [ ] **Helper `_extract_authenticated_user_id` landed** с unit-тестами
- [ ] **resolve_mcp_user fail-loud** для production-mode
- [ ] **30+ call-site'ов rewritten**, `rg "ctx.client_id"` пусто
- [ ] **BUG-001b cabinetry** — fail-loud при `auth_enabled=true && tokens=empty`
- [ ] **Integration tests** покрывают: valid token / missing token / invalid token / dev-mode / cabinetry
- [ ] **CI blind-spot** закрыт — minimum 5-7 ключевых
      `tests/test_mcp_management.py` testcase'ов больше не мокают `resolve_mcp_user`
- [ ] full pytest suite зелёный (count ≥ baseline + 5)
- [ ] CHANGELOG обновлён критическим security-разделом
- [ ] PR merged в main с зелёным CI
- [ ] **`BUG_LOG.md` BUG-001 перенесён в § Resolved bugs** с PR# + commit-SHA
- [ ] **`BUG_LOG.md` § Session planning § Updates** содержит:
  ```
  Session C (2026-04-NN) — landed: PR #NN, commit <SHA>, +N tests;
  bugs resolved: BUG-001 (+ BUG-001b cabinetry).
  ```

---

## 8. Handoff

Перед закрытием Session C:

1. **Production deploy verification**:
   - На staging: запустить с `MCP_AUTH_ENABLED=true`, проверить
     `whoami` возвращает реального user'а, проверить
     `add_channel(...)` проходит без foreign-key error.
   - Production deploy с rollback-план: если что-то отказало — revert
     PR (commit чистый, можно).
2. **Уведомить пользователя** что:
   - BUG-001 закрыт (Critical → resolved).
   - Session D (BUG-002 full FSM) может стартовать как запланировано.
   - Session E / F не блокируются.
3. **Open follow-up TD** (если capacity):
   - Audit log для auth-events (отдельный TD после нескольких use-case'ов).
   - Rate-limiting per-user (отдельный TD).
4. **Финальное сообщение юзеру** должно содержать:
   - PR# и SHA.
   - Подтверждение что синтетический admin больше не аутентифицируется.
   - Если был manual deploy intervention — отдельный block.
   - Если bug на staging показал что-то новое — отдельный escalation.

---

## 9. Citation back

- **Bug source:** `docs/notes/BUG_LOG.md` § BUG-001 + BUG-001b.
- **Session planning:** `docs/notes/BUG_LOG.md` § Session planning.
- **Independent parallel session:**
  `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md`
  (Session D — bot FSM; разные code path'ы, может идти параллельно).
- **Related context:**
  - `tg_parser/mcp_server.py` (target file).
  - `tg_parser/auth/resolvers.py` (DB-resolution, не меняется).
  - MCP SDK source в `.venv` (для verification контрактов).

В commit-message'ах достаточно `Refs: BUG_LOG.md BUG-001, Session C.`
