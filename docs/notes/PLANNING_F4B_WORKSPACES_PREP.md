# Планировочная prep — F4-B Workspaces

**Назначение:** prep-документ для **будущей** планирующей сессии,
которая зафиксирует scope F4-B (workspaces / тематические группы каналов
внутри одного пользователя) **в свете уже реализованного F4-A**
(multi-user). Этот файл — НЕ план, НЕ решение. Он собирает контекст,
изменившийся scope, open questions и criteria для обоснования
приоритета.

**Дата подготовки prep:** 2026-05-02 (после ADR 0006 / planning prep
для Wave D/E).

**Когда использовать:** в момент, когда (a) появляется product-driver
для F4-B (пользователь с >20 каналами в разных тематиках, multi-tenant
compliance, или эквивалентный signal); (b) в результате планирующей
сессии Wave D/E принимается решение, что F4-B уместнее как combo или
следующий контракт. До тех пор — этот документ остаётся справочным.

**Что должна произвести планирующая сессия:**

1. Зафиксированный scope F4-B (минимальный MVP vs полный, см. § 5).
2. Полный спринт-промпт по образцу [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md)
   с pre-flight, шагами, gotchas, рисками, PR-чеклистом.
3. Решения по 8 open design questions (§ 4).
4. Karpathy-like 7-checklist прохождение по [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md).
5. Решение про обновления интеграционных артефактов (F11 watchlist,
   F6 digest, MCP/Bot/API auth resolvers).

**Что планирующая сессия делать НЕ должна:**

- Реализовывать код (это делается отдельным спринтом).
- Изменять F4-A контракт (`CurrentUser`, `allowed_channel_ids`,
  ownership) — F4-B накладывается **сверху** на F4-A, не вместо.

---

## 1. Контекст: F4-B было задумано ДО F4-A, но реализовано ОБРАТНО

### Что говорит roadmap

[`FUTURE_FEATURES.md § F4 «Рекомендуемый путь»`](FUTURE_FEATURES.md):

```
Сценарий B (Workspaces) → Сценарий A (Multi-User)
    ~2 сессии              +1.5–2 сессии сверху
    нет auth               + auth + isolation
    один пользователь      много пользователей
```

### Что произошло на практике

- **F4-A landed**: 5 фаз DONE (Phase 1–5, Sessions 1–3) — см.
  [`docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`](../plans/F4_MULTI_TENANCY_FULL_PLAN.md).
  Реализованы: `users` + `user_auth_mappings`, `sources.owner_id`,
  `CurrentUser` dataclass, scoped data access на repo-уровне (SQL
  `WHERE channel_ids && ARRAY[:allowed]`), 3-surface auth resolution
  (Bot / MCP / API), 7 user management MCP tools, ~150 тестов в 8
  файлах `tests/test_f4_*.py`.
- **F4-B not started**: backlog в [`FUTURE_FEATURES.md § F4`](FUTURE_FEATURES.md)
  L517 (Сценарий B), priority «Низкий».

Причина обратного порядка (по моему анализу):

- F4-A был **product-need** — production deployment с несколькими
  реальными пользователями, telegram-bot allowlist уже маркировал
  «настоящих юзеров», нужна была изоляция данных.
- F4-B — **convenience-feature**, нет внешнего давления (один
  пользователь живёт со списком каналов и без группировки).

### Что это меняет для будущего F4-B

Прежний план в `FUTURE_FEATURES.md` § F4-B был написан с
предположением, что F4-A ещё не сделан. Теперь scope меняется:

- **Pro:** многие интеграционные точки уже существуют —
  `allowed_channel_ids` filter pattern переиспользуется; workspace
  будет просто **дополнительно сужать** уже существующий per-user
  scope.
- **Pro:** auth-resolvers и cache в [`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py)
  готовы; добавление поля «active workspace» в `CurrentUser` —
  small extension.
- **Con:** появляются 8 новых open design questions (§ 4), которых
  не было в первоначальном плане.
- **Con:** F11 watchlist (`channel_ids: TEXT[]`) и F6 digest
  (`channel_ids: TEXT[]`) — обе уже работают per-user. Решить, что
  делать с их `channel_ids` в контексте workspace'ов, — отдельный
  design choice (eager-resolve в subscription time? lazy-resolve в
  delivery time? optional `workspace_id` параметр?).
- **Con:** Bot UX — `notes/PHASE3_IMPLEMENTATION_PLAN.md` определил
  free-form chat без специальных команд. «Переключить контекст в
  workspace» не вписывается в free-form парадигму прямо. Нужен
  явный design choice.

**Updated cost estimate:** прежняя оценка ~2 сессии устарела. Новая
оценка с учётом интеграционного долга: **~2.5–3.5 сессии**, в
зависимости от scope (минимальный MVP без F11/F6 интеграции = ~2.5;
полный с интеграциями = ~3.5).

---

## 2. Где F4-B сидит в общей траектории

| Источник | Что говорит |
|----------|-------------|
| [`FUTURE_FEATURES.md § F4-B`](FUTURE_FEATURES.md) L517–576 | Исходный design (DDL `workspaces` + `workspace_sources`, 7 шагов реализации, RAG vector search SQL-rewrite). Был написан до F4-A — нужна сверка. |
| [`FUTURE_FEATURES.md § F4 рекомендуемый путь`](FUTURE_FEATURES.md) L612–618 | B → A порядок, **не выполненный**. F4-B теперь идёт ПОСЛЕ F4-A. |
| [`docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`](../plans/F4_MULTI_TENANCY_FULL_PLAN.md) | F4-A finalized plan; статусы Phase 1–5 DONE; точки интеграции, которые F4-B будет переиспользовать. |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist; F4-B обязан пройти до фиксации scope. |
| [`PLANNING_NEXT_CONTRACT_PREP.md § 3`](PLANNING_NEXT_CONTRACT_PREP.md) | F4-B перечислен среди альтернативных кандидатов; promotion в первичные требует concrete-driver'а. |
| [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | F4-B не входит ни в Wave D, ни в Wave E — это **параллельный track** Multi-Tenancy. |

> **North star одной строкой:** F4-B даёт пользователю возможность
> группировать свои каналы в **тематические коллекции** (workspaces) и
> работать с ними раздельно, **не теряя** F4-A изоляции от других
> пользователей. Workspace — это **сужение** existing
> `allowed_channel_ids`, не замена.

---

## 3. Pre-condition state — что уже есть, что F4-B будет переиспользовать

| Слой | Артефакт | Файл |
|------|----------|------|
| Schema (ingestion) | `sources.owner_id UUID FK users.id` + `idx_sources_owner` | [`tg_parser/storage/sqlalchemy/_metadata.py:83`](../../tg_parser/storage/sqlalchemy/_metadata.py) (sources Table) |
| Schema (ingestion) | `users` + `user_auth_mappings` | [`tg_parser/storage/sqlalchemy/_metadata.py:125`](../../tg_parser/storage/sqlalchemy/_metadata.py) |
| Schema (processing) | `document_embeddings.channel_ids TEXT[]` + GIN index | [`tg_parser/storage/sqlalchemy/embedding_repo.py`](../../tg_parser/storage/sqlalchemy/embedding_repo.py) |
| Domain | `CurrentUser` dataclass с `allowed_channel_ids: list[str] \| None` | [`tg_parser/auth/models.py`](../../tg_parser/auth/models.py) |
| Auth | `resolve_user_by_auth` + 60s cache | [`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py) |
| Ownership | `assert_channel_access`, `assert_topic_access`, `assert_admin`, `check_channel_limit` | [`tg_parser/auth/ownership.py`](../../tg_parser/auth/ownership.py) |
| Service scoping | `retrieval_service.search/answer`, `analytics_service.get_cross_channel_analytics`, `topic_linking_service.get_related_topics_for`, `channel_service.get_all_channel_stats` — все принимают `allowed_channel_ids` | [`tg_parser/services/`](../../tg_parser/services/) |
| Surface | Bot `UserResolutionMiddleware` injects `current_user` | [`tg_parser/bot/middleware.py`](../../tg_parser/bot/middleware.py) |
| Surface | MCP `resolve_mcp_user(ctx)` | [`tg_parser/mcp_server.py:254`](../../tg_parser/mcp_server.py) |
| Surface | API `Depends(resolve_current_user)` | [`tg_parser/api/auth.py`](../../tg_parser/api/auth.py) |
| Per-user features | F11 `watch_interests.user_id + channel_ids[]` | [`tg_parser/storage/sqlalchemy/_metadata.py:235`](../../tg_parser/storage/sqlalchemy/_metadata.py) (watch_interests Table) |
| Per-user features | F6 `digest_subscriptions.owner_id + channel_ids[]` | [`tg_parser/storage/sqlalchemy/_metadata.py:168`](../../tg_parser/storage/sqlalchemy/_metadata.py) (digest_subscriptions Table) |

Всё это **остаётся неизменным** при F4-B; меняется только
вычисление `effective_channel_ids` для запроса = `user.allowed_channel_ids ∩ active_workspace.channel_ids`.

---

## 4. Open design questions для планирующей сессии

### Q1. Default workspace — есть или нет?

- **Вариант A (default workspace):** при создании user'а автоматически
  создаётся «My Channels» workspace, в который попадают все его каналы.
  Pro: всегда есть active workspace, нет null-state. Con: лишняя
  сущность для пользователей, которые workspace'ы вообще не хотят.
- **Вариант B (no default):** если у user'а 0 workspaces — поведение
  идентично F4-A (доступ ко всем своим каналам). Workspaces —
  опциональная overlay. Pro: backward-compatible, no migration noise.
  Con: код везде должен handle'ить null-workspace fallback.
- **Вариант C (lazy default):** workspace создаётся только когда
  пользователь явно зовёт `create_workspace`. До этого — F4-A
  поведение.

Рекомендация (preliminary): **Вариант B/C** — не насаждать workspace,
если нет явного запроса; opt-in feature.

### Q2. Workspace identity в tools — параметр или session-state?

- **Вариант A (explicit param):** каждый MCP/Bot tool принимает
  optional `workspace_id` параметр. Если не указан — fallback на
  user-scope. Pro: stateless, явно. Con: пользователь должен помнить,
  в каком workspace он работает; verbose.
- **Вариант B (active workspace in CurrentUser):** `CurrentUser`
  расширяется полем `active_workspace_id: UUID | None`. Tool автоматом
  use'ит. Switch через `set_active_workspace(ws_id)`. Pro: UX
  естественнее. Con: state — где живёт? В `users.active_workspace_id`?
  Это persistent. Per-session? Нужен session storage.
- **Вариант C (per-surface state):** Bot — workspace из FSM state
  (chat-session-scoped); MCP — `ctx.metadata['active_workspace_id']`;
  API — header `X-Active-Workspace-Id`. Pro: нет состояния в DB. Con:
  inconsistent UX между surface'ами.

### Q3. Bot UX — как переключать workspace в free-form chat?

[Phase 3 plan](PHASE3_IMPLEMENTATION_PLAN.md) фиксирует «free-form чат
без специальных команд». Workspace switching ломает эту парадигму, но
нужно как-то.

- **Вариант A (slash-commands):** `/workspace AI/ML` — slash, но
  slash. Нарушает «без специальных команд» декларацию.
- **Вариант B (natural language через LLM tool-call):** «Перейди в
  workspace AI/ML» → LLM зовёт `set_active_workspace("AI/ML")`. Чище,
  но добавляет ещё один write-tool в `_WRITE_TOOLS_REQUIRING_CONFIRM`
  (BUG-009 contract — см.
  [`Session G prompt`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md)).
  Решение про confirm для workspace switch отдельный вопрос.
- **Вариант C (показ context в каждом ответе):** «[В workspace
  AI/ML] Темы канала ai_news — ...» — visible feedback, но не
  switching. Нужен только при наличии Q1 default-workspace.

### Q4. Cross-workspace ops внутри одного пользователя

User имеет 2 workspaces (A, B). Может ли он:

- **Сделать cross-workspace search** (поиск по A∪B, оба своих
  workspace)? Pro: естественно. Con: сводит на нет workspace-scoping.
  Решение: по умолчанию scoped, opt-in cross через явный flag
  `--all-workspaces` или MCP-параметр.
- **Перенести канал из A в B?** Запрос: `move_channel(channel_id,
  from_ws, to_ws)` — нужен ли отдельный tool, или просто
  `remove_workspace_source(A, ch)` + `add_workspace_source(B, ch)`?
- **Cross-workspace topic-link visibility?** Topic в A связан с topic
  в B (один пользователь, оба свои) — показывать ли cross-link?

### Q5. Shared channels — один `source_id` в нескольких workspaces

- **Вариант A (shared):** один канал может быть в N workspaces одного
  пользователя (или даже разных пользователей — но это уже F4-A
  ownership спорно). Schema: `workspace_sources(workspace_id,
  source_id) PK` — это уже разрешает sharing. Pro: пользователь не
  хочет дубликата ingestion. Con: интерфейс «удалить канал из
  workspace» — это не «удалить канал».
- **Вариант B (exclusive):** канал принадлежит ровно одному
  workspace. Schema: `sources.workspace_id` FK. Pro: проще ментальная
  модель. Con: пользователь, который хочет канал в обоих темах,
  страдает.

### Q6. Topics + Workspaces

Topic spans channels (cross-channel topic). Если канал A в workspace
1, канал B в workspace 2, **топик spanning A+B** — где видим?

- **Вариант A (visible in both):** топик видим в любом workspace,
  чьи каналы — часть его `sources`. Mirror'ит F4-A `assert_topic_access`
  poведение (visible if user has access to AT LEAST ONE source).
- **Вариант B (visible only in active workspace):** топик видим
  только если **все** его sources в active workspace. Pro:
  workspace-isolation полная. Con: cross-channel топики становятся
  нерелевантными.
- **Вариант C (filtered by workspace, but linked):** топик видим в
  workspace 1, но supporting items из канала B (которого нет в
  workspace 1) — скрыты. Pro: гибкость. Con: сложно объяснить
  пользователю.

### Q7. F11 Watchlist + Workspaces

`watch_interests.channel_ids` — текущая модель: per-user интерес с
явным списком каналов. Как relate к workspace?

- **Вариант A (workspace-scoped subscription):** добавить
  `watch_interests.workspace_id NULL` (NULL = user-scoped legacy
  behavior). При создании subscription можно сказать «подпишись на
  все каналы workspace AI/ML» — взять channel_ids из workspace
  eager. Eager-resolve: добавление канала в workspace **не**
  обновляет существующие watchlists.
- **Вариант B (lazy resolve):** `watch_interests` хранит
  `workspace_id` или `channel_ids` (one-of). При проверке matches
  workspace_id resolve'ится в actual channel_ids в hot path. Pro:
  workspace `add_source` автоматом расширяет watchlists. Con: lookup
  cost в hot path.
- **Вариант C (no integration):** F11 продолжает работать только с
  явными `channel_ids[]`. F4-B не трогает F11. Pro: простота. Con:
  workspace UX не очень — пользователь, добавивший канал в
  workspace, должен ещё руками обновить все свои watchlists.

### Q8. F6 Digest + Workspaces

Аналогичен Q7 для `digest_subscriptions.channel_ids`. Те же три
варианта.

---

## 5. Implementation outline (revised after F4-A landed)

> Отметка: это **первая чернова** outline'а. Планирующая сессия может
> переоформить под выбранные ответы на § 4.

### Минимальный MVP (~2.5 сессии — Q1=B, Q2=A, Q3=B, Q4-Q8 conservative defaults)

**Schema (Phase 1 — ~0.3 сессии):**

- Новые таблицы:
  ```sql
  CREATE TABLE workspaces (
      id UUID PK DEFAULT gen_random_uuid(),
      owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name VARCHAR(200) NOT NULL,
      description TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE (owner_id, name)
  );
  CREATE TABLE workspace_sources (
      workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
      source_id UUID NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
      added_at TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY (workspace_id, source_id)
  );
  CREATE INDEX idx_workspace_sources_source ON workspace_sources(source_id);
  ```
- Alembic ingestion-branch migration (новая ревизия после
  `d7e8f9a0b1c4`).
- `Workspace` + `WorkspaceSource` Pydantic в [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py).
- `WorkspaceRepo` ABC в [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py).
- `SAWorkspaceRepo` в `tg_parser/storage/sqlalchemy/workspace_repo.py`.
- JSON-схема в [`docs/contracts/workspace.schema.json`](../contracts/workspace.schema.json).
- `processing_repos()` extension в [`tg_parser/services/db_context.py`](../../tg_parser/services/db_context.py).

**Service layer (Phase 2 — ~0.4 сессии):**

- `WorkspaceService`: CRUD (`create`, `list_by_owner`, `add_source`,
  `remove_source`, `delete`).
- Workspace ownership check: `assert_workspace_access(user, ws_id)`
  в [`tg_parser/auth/ownership.py`](../../tg_parser/auth/ownership.py).
- Optional: `effective_channel_ids(user, workspace_id) -> list[str]`
  helper — `user.allowed_channel_ids ∩ workspace.channel_ids`.

**MCP/CLI surface (Phase 3 — ~0.5 сессии):**

- 4 MCP tools: `create_workspace(name, description, channel_ids?)`,
  `list_workspaces()`, `add_workspace_source(ws_id, channel_id)`,
  `remove_workspace_source(ws_id, channel_id)`, `delete_workspace(ws_id)`.
- 4 CLI commands: `tg-parser workspace create`, `list`, `add`,
  `remove`, `delete`.
- **Bot tools — НЕ в MVP** (по аналогии с F5-C MVP — see
  [`FUTURE_FEATURES.md § F5-C`](FUTURE_FEATURES.md) L745: «Bot tools —
  только при UX-сигнале»). Подключаются Phase 2 при сигнале.

**Scoping integration (Phase 4 — ~0.6 сессии):**

- MCP tool `set_active_workspace(ws_id | none)` (Q2 = A или B
  определяет, как именно).
- В каждом scoped MCP tool — accept optional `workspace_id` param
  ИЛИ resolve из `ctx.metadata`. `effective_channel_ids` =
  `allowed_channel_ids ∩ workspace.channel_ids`.
- Existing service-методы НЕ меняют сигнатуру — они уже принимают
  `allowed_channel_ids`. Меняется только вычисление этого списка на
  surface-уровне.

**Tests (Phase 5 — ~0.7 сессии):**

- `tests/test_f4b_workspace_repo.py` — CRUD.
- `tests/test_f4b_workspace_service.py` — ownership, effective_channel_ids.
- `tests/test_f4b_workspace_mcp.py` — MCP tool surface.
- `tests/test_f4b_workspace_scoping.py` — end-to-end search/answer
  scoped by workspace.
- `tests/test_f4b_workspace_isolation.py` — user A не видит workspace
  user B; admin видит всё.

### Полный scope (~3.5 сессии — добавляет F11 + F6 интеграцию)

К минимальному MVP добавляется (Phase 6, ~1 сессия):

- `watch_interests.workspace_id NULLABLE` migration (Q7 решение).
- `digest_subscriptions.workspace_id NULLABLE` migration (Q8 решение).
- WatchlistService + DigestService обновление для resolve workspace
  → channel_ids.
- Tests `test_f4b_watchlist_workspace.py`, `test_f4b_digest_workspace.py`.
- Optional: bot tools для workspace operations (если по Q3 решено
  «natural language через LLM»).

---

## 6. Karpathy-like 7-checklist (ADR 0006)

Предварительный walkthrough — финальный проход в планирующей сессии.

| # | Принцип | F4-B соответствие |
|---|---------|-------------------|
| 1 | Persistent entities | **PASS.** Новые таблицы `workspaces` + `workspace_sources` с FK / индексами. JSON-схема `docs/contracts/workspace.schema.json`. Pydantic-модели. Не «всё в metadata: dict». |
| 2 | Provenance / evidence | **PASS** (с условием). Workspace-context должен попадать в логи запросов (`structlog.bind(workspace_id=...)`) для traceability «почему этот ответ scoped just so». |
| 3 | Cheap retrieval cycles | **PASS.** Workspace filter — pure SQL `JOIN workspace_sources WHERE workspace_id = :ws`. Никакого LLM на documents. |
| 4 | Идемпотентность | **PASS.** `workspace_sources` PK = `(workspace_id, source_id)` — UPSERT idempotent. `workspaces.UNIQUE (owner_id, name)` — re-run create не плодит дубликаты. |
| 5 | Living loop | **PASS.** Pipeline (ingestion / processing / topicization / embedding / watchlist) **НЕ меняется** — workspace это per-query filter, не pipeline-stage. Hooks неизменны. |
| 6 | Observability | **PASS** (с условием). Нужны метрики: `tg_workspace_active_total` (gauge per-user), `tg_workspace_query_total{result}` (queries scoped vs unscoped), `tg_workspace_size` histogram (channels per workspace). |
| 7 | Graceful degradation | **PASS** (с условием). Если `workspace_sources` пуст / migration не накатилась — fallback на F4-A behavior (все user's каналы). Пользователь без workspaces работает идентично F4-A. |

---

## 7. Reading list

### Обязательные

| Файл | Зачем |
|------|-------|
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist обязателен для нового scope. |
| [`docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`](../plans/F4_MULTI_TENANCY_FULL_PLAN.md) | F4-A уже реализован; точки интеграции и pattern для re-use. |
| [`FUTURE_FEATURES.md § F4-B`](FUTURE_FEATURES.md) L517–576 | Исходный design (написан до F4-A) — нужна ревизия. |
| Этот файл (PLANNING_F4B_WORKSPACES_PREP.md) | Сам prep + open questions § 4. |

### Контекстные (зависит от глубины интеграции)

| Зачем | Reading |
|-------|---------|
| Auth / scoping pattern | [`tg_parser/auth/models.py`](../../tg_parser/auth/models.py), [`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py), [`tg_parser/auth/ownership.py`](../../tg_parser/auth/ownership.py) |
| MCP context injection | [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) `resolve_mcp_user`, `_extract_authenticated_user_id` |
| Bot middleware | [`tg_parser/bot/middleware.py`](../../tg_parser/bot/middleware.py) `UserResolutionMiddleware` |
| API auth | [`tg_parser/api/auth.py`](../../tg_parser/api/auth.py) `resolve_current_user` |
| Per-user feature integration (F11) | [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py), `watch_interests.channel_ids` schema |
| Per-user feature integration (F6) | [`tg_parser/services/digest_service.py`](../../tg_parser/services/digest_service.py), `digest_subscriptions.channel_ids` schema |
| Bot UX precedent | [`docs/notes/PHASE3_IMPLEMENTATION_PLAN.md`](PHASE3_IMPLEMENTATION_PLAN.md) (free-form chat constraint) + [`prompts/bot.yaml`](../../prompts/bot.yaml) (current system prompt) |
| BUG-009 confirm contract | [`docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md) (если workspace-write tools будут включаться в `_WRITE_TOOLS_REQUIRING_CONFIRM`) |

### Operational

| Файл | Зачем |
|------|-------|
| [`docs/architecture.md § Семантика данных и Living-KB`](../architecture.md) | Архитектурный обзор; F4-B попадает под те же 7 принципов. |
| [`tg_parser/storage/sqlalchemy/_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) | Текущая schema — как добавлять новые Table() declarations. |
| `migrations/versions/ingestion/` | Pattern для новой alembic ревизии (последняя head — `d7e8f9a0b1c4`). |

---

## 8. Format-precedent для результирующего sprint-промпта

После того как планирующая сессия выберет scope, она производит
sprint-промпт по образцу:

- **F11 (precedent #1):** [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md)
  — наиболее структурированный, с Hidden gotchas / Risks / PR
  checklist. F4-B по сложности ближе к F11 (новые таблицы + service +
  MCP/CLI surface), чем к F5-C.
- **Pair-precedent (planning prep → sprint prompt):**
  [`START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md) +
  [`START_PROMPT_SPRINT_F5C.md`](START_PROMPT_SPRINT_F5C.md) — точный
  пример того, как этот prep должен превратиться в sprint-промпт.

---

## 9. Risks (preliminary)

| ID | Риск | Severity | Mitigation |
|----|------|----------|------------|
| R-1 | Q3 Bot UX недостаточно проработана — пользователь не понимает, где он | Medium | В планирующей сессии — сделать UX-mockup на пример flow'ов «list_topics workspace AI/ML», «выйти из workspace», «search в active workspace». Если не сходится — отложить bot integration в Phase 2. |
| R-2 | Cross-channel topic visibility (Q6) ломает existing F4-A `assert_topic_access` контракт | Medium | Q6 решение должно явно сохранять backward-compat F4-A contract. Default — Вариант A (visible if user has access to ANY source — mirror F4-A). |
| R-3 | F11/F6 integration усложняет migration существующих subscriptions | Low | `workspace_id NULLABLE` + lazy migration — existing subscriptions продолжают работать без workspace, новые могут опционально привязываться. |
| R-4 | Vector search performance при добавлении workspace JOIN | Medium | F4-A уже использует `WHERE channel_ids && ARRAY[:allowed]` с GIN index. Workspace-resolve просто сужает массив. Добавляет ~5-15% latency overhead, не качественную проблему. Mitigation: benchmark на 100k+ docs / 50+ workspaces. |
| R-5 | Workspace ownership — что происходит при удалении user'а? | Low | `ON DELETE CASCADE` уже в schema (`workspaces.owner_id → users.id ON DELETE CASCADE`). Workspaces удаляются вместе с user'ом, source'ы остаются (соответствуют F4-A `sources.owner_id` semantics). |

---

## 10. История prep-документа

| Дата | Изменение |
|------|-----------|
| 2026-05-02 | Первая версия. Создана как ответ на вопрос «насколько у нас реализованы возможности notebooks vs multi-user» (F4-A done полностью / F4-B не начат). По аналогии с [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) — prep-doc, не sprint-промпт. Updated cost estimate ~2.5–3.5 сессии (vs original ~2 в FUTURE_FEATURES) с учётом F4-A интеграционного долга. |

---

## 11. Когда удалить этот файл

Когда планирующая сессия пройдёт и produced спринт-промпт landed —
этот prep-документ либо архивируется
(`PLANNING_F4B_WORKSPACES_PREP_<date>_archived.md`), либо удаляется
с заменой ссылкой на конкретный sprint-промпт. На усмотрение
планирующей сессии.

Альтернативный сценарий: если планирующая сессия решит, что F4-B
**не нужен** (например, F11 watchlist уже даёт достаточную
тематическую группировку для существующих пользователей) — этот
prep тоже архивируется с пометкой «decided not to pursue, see
<reference>».
