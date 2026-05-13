# Sprint F4-B Core — Workspaces (тематические коллекции каналов)

> ✅ **LANDED 2026-05-13** — F4-B Core merged into `main` (HEAD `7953302`, [PR #67](https://github.com/AlexEfimov/TG_parser/pull/67) squash-merged). Deployed to prod 2026-05-13 19:30 UTC. 24h watch in progress (baseline `2026-05-13T19:30:28Z`). Wave 1 step 2 closure pending DONE marker (`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` after 24h watch GREEN). See [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md § 2026-05-13 — Wave 1 step 2 (F4-B Core Workspaces) DONE`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md).
>
> The sections below describe the original sprint plan (preserved as historical contract). Locked decisions Q1–Q8 implemented as specified.

---

**Дата подготовки промпта:** 13 мая 2026 (planning sub-session ~0.3 сессии).
**Тип сессии:** Feature (~2.5 сессии, **Single PR + 5 atomic commits** — mirror Session F pattern, не F11 multi-PR).
**Wave 1 step:** 2 (per audience-driven roadmap).
**HEAD на момент написания промпта:** `aa32f6e` на `origin/main` (Session K landed —
[`PR #65`](https://github.com/AlexEfimov/TG_parser/pull/65) closed Wave 1 step 1).
**Closes:** F4-B Core MVP per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) (audience A1 Solo Knowledge Curator + foundation для A6 Domain Curator).
**Parent planning sub-session:** в этом же чате (planning sub-session 2026-05-13, parent agent transcript).
**DONE marker предыдущего шага:** [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) (cross-linked в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «2026-05-08 — Wave 1 step 1 DONE»).

**Прецеденты (читать перед стартом):**

- [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) — prep-документ с § 4 Q1–Q8 (Q2 + Q4 refined 2026-05-03 — **locked**), § 5 5-phase MVP outline, § 6 preliminary Karpathy walkthrough.
- [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 + § 8](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) — Wave 1 sequence (Bot UX → F4-B Core → Surface Parity → Shareable Digest), 8 open questions с preliminary рекомендациями.
- [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 2.1 + § 2.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) — operational companion: packaging Single PR + 5 atomic commits, quality bar (24h watch mirror Session G, **`tg_parser_bot` контейнер**), DONE marker template (C1).
- [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) — 7 принципов Living-KB, обязательный checklist для нового контракта.
- [`docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`](../plans/F4_MULTI_TENANCY_FULL_PLAN.md) — F4-A finalized plan; точки интеграции и pattern для re-use.
- [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — **format-precedent** (~673 строки) для структуры этого промпта.
- [`PARITY_DECISION_TRACKING.md` § 3](PARITY_DECISION_TRACKING.md) — O-1 (atomic `move_workspace_source` deferred — см. § «O-1 status» в конце этого промпта).
- [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` § 5](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) — lessons learned Session K (особенно § 5.4 pre-flight container nomenclature `tg_parser_bot`).

---

## Цель сессии

Добавить **F4-B Core: Workspaces** — owner (Solo Knowledge Curator, A1) группирует свои каналы
в **тематические коллекции** (workspaces) и работает с ними раздельно через MCP + CLI, не теряя
F4-A изоляции от других пользователей. **Workspace = сужение `allowed_channel_ids`, не замена.**

**MVP scope (~2.5 сессии, 5 atomic commits в одном PR):**

1. **Schema + migration** в `ingestion` БД: таблицы `workspaces` + `workspace_sources` с FK на
   `users.id` / `sources.source_id` (multi-tenancy наследуется от F4-A).
2. **Domain + ports + repo** — `Workspace` + `WorkspaceSource` Pydantic, `WorkspaceRepo` ABC +
   SQLAlchemy реализация.
3. **`WorkspaceService`** в `tg_parser/services/workspace_service.py` — CRUD + `effective_channel_ids`
   resolver (intersection `user.allowed_channel_ids ∩ workspace.channel_ids`).
4. **MCP + CLI surface** — 6 tools (`list_workspaces`, `create_workspace`, `rename_workspace`,
   `delete_workspace`, `add_workspace_source`, `remove_workspace_source`, `list_workspace_sources`)
   + optional admin-only `list_all_workspaces`. **Bot tools — НЕ в MVP** (Q3 = skip).
5. **Scoping integration** — каждый read-tool (`list_channels`, `list_topics`,
   `search_knowledge_base`, `ask_question`, `get_topic_details`, `get_document`) получает optional
   `workspace_id: str | None = None` параметр; `effective_channel_ids` вычисляется на
   surface-уровне; service-слой не меняет сигнатуру (по-прежнему принимает
   `allowed_channel_ids: list[str] | None`).

### Что НЕ входит в сессию (defer)

- **Bot tools для workspace operations** (Q3 = skip-in-MVP). Bot пользователи работают в
  user-scope без workspace-сужения. Добавятся отдельным sprint'ом при UX-сигнале.
- **F11 watchlist + workspace_id** (Q7 = C). `watch_interests.channel_ids[]` остаётся без
  workspace-поля. Subscription на «все каналы workspace AI/ML» — Wave 2 task.
- **F6 digest + workspace_id** (Q8 = C). Аналогично Q7.
- **Atomic `move_workspace_source(channel_id, from_ws, to_ws)`** — defer (O-1 в parity
  tracker). Перенос делается двумя вызовами `remove + add`.
- **Sharing между users** — F4-B Sharing (`workspace_members` M2M + ACL roles) deferred до
  Wave 2C по signal'у A3 (Team).
- **API endpoints** (`POST /api/v1/workspaces` etc.) — MCP/CLI достаточно для MVP. Если
  signal появится — будет частью Wave 1 step 3 (Surface Parity).
- **Bot UX для workspace context** (показ active workspace в каждом ответе, slash-commands,
  natural-language switching) — выводится из Q3 defer.
- **Documentation hygiene** (M-1 / M-2 / M-3 / M-7 / M-8 / M-15 / M-16 — см.
  [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` § 3.2](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md)) — отдельная
  ~0.5-сессия docs-only до или после F4-B Core, не смешивать.

---

## Pre-flight (gate-1, перед началом sprint'а)

> **Жёсткий gate:** все 4 проверки должны быть GREEN. Если хоть одна — STOP и report, не начинать
> sprint. Mirror execution plan § 2.2: «Pre-flight gate-1 = Wave 1 step 1 DONE marker valid + Bot
> 24h watch GREEN over 72h cumulative».

### 1. HEAD verification

```bash
cd /Users/alexanderefimov/TG_parser
git log -1 --format='%H %s'
# Expected: aa32f6ebec2c03d430721263a05cecc041284687 docs(milestone): Wave 1 Step 1 DONE ...
git status
# Expected: On branch main / nothing to commit, working tree clean / up to date with origin/main
```

Если HEAD отстал — `git pull --ff-only`. Если HEAD впереди / divergent — diagnose, не начинать.

### 2. DONE marker + cross-link

```bash
ls -la docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md
# Expected: file exists, ~11K size

grep -n "REVIEW_2026-05-08_WAVE1_STEP1_DONE" docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md
# Expected: line 44 (cross-link from § «2026-05-08 — Wave 1 step 1 DONE»)
```

### 3. Bot 24h watch GREEN over 72h cumulative

**ВАЖНО:** контейнер называется `tg_parser_bot` (не `tg-parser-bot`, не `tg_bot`) —
[`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` § 5.4 lesson](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md).

```bash
# Prometheus live check
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool'
# Expected: result vector, value=1

# 72h cumulative — confirm_flow_mismatch
ssh prod 'docker logs --since 72h tg_parser_bot 2>&1 \
  | grep -cE "confirm_flow_mismatch"'
# Expected: 0

# 72h cumulative — gemini soft-fail signals
ssh prod 'docker logs --since 72h tg_parser_bot 2>&1 \
  | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked|gemini_api_error"'
# Expected: 0
```

> Если за 72h окно с момента Session J deploy (2026-05-07 ~18:46 UTC) и до старта F4-B Core
> sprint'а accumulative счётчики `confirm_flow_mismatch` или `gemini_*` ≠ 0 — STOP и diagnose в
> отдельной hot-fix сессии до F4-B Core.

### 4. Local стек + базовая регрессия

```bash
docker compose ps                                # tg_parser_postgres healthy
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT * FROM alembic_version_ingestion;"
# Expected: d7e8f9a0b1c4 (последняя ingestion ревизия — это будет down_revision для F4-B миграции)

.venv/bin/pytest -q --tb=line | tail -5
# Expected: ~2047 passed (baseline после Session J / Session K) + 0 failures
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и
`.venv/bin/ruff check <files>` (sustained lesson из Sprints A → A.7 / F11 / F5-C — иначе CI красный
на line-length / I001 / B023).

---

## Locked design decisions (Q1–Q8)

> Эти 8 решений **зафиксированы** на planning sub-session 2026-05-13 и **не могут флипаться внутри
> sprint'а** без отдельной planning round-trip. Если по ходу реализации обнаружится substantive
> issue — STOP, report, дождаться нового planning.

### Q1 — Default workspace `[CONFIRMED 2026-05-13]`: **B (opt-in, no default)**

При создании user'а **никаких workspaces автоматически не создаётся**. Если у user'а 0 workspaces —
поведение **идентично F4-A** (доступ ко всем `allowed_channel_ids`). Workspaces — опциональная
overlay; пользователь активирует их через явный `create_workspace(...)`.

**Обоснование:**

- **Backward-compatibility 100%** с F4-A. Legacy MCP/CLI callers без `workspace_id` параметра
  работают **bit-for-bit** как сегодня. Существующие F4-A интеграции (Cursor / Claude Desktop с
  MCP) не требуют миграции.
- **No migration noise** — нет необходимости в data-migration для существующих users; их
  workspace-count просто остаётся = 0 до явного `create_workspace`.
- **Karpathy-like graceful degradation (принцип 7)** — workspace это feature-overlay, а не
  pipeline-stage; её отсутствие не должно деградировать ядро.
- **Согласовано с Q2 edge case 1** (`workspace_id=None` → F4-A behavior). Нет shadow-state «текущий
  default workspace для current user» — `effective_channel_ids` детерминирован чисто параметром.

### Q2 — Workspace identity в tools `[REFINED 2026-05-03 — locked]`: **A (explicit optional param, stateless)**

Каждый scoped MCP/CLI tool принимает optional `workspace_id: str | None = None` параметр.
**Никакого `active_workspace_id` в `CurrentUser`** — stateless API.

**Locked edge cases (deep-dive 2026-05-03, см. [`PLANNING_F4B_WORKSPACES_PREP.md` § 4 Q2 «Refined decisions»](PLANNING_F4B_WORKSPACES_PREP.md)):**

**Edge case 1: `workspace_id` missing OR `workspace_id=None`** → **F4-A behavior** (все каналы
user'а, без сужения). Python signature допускает оба варианта; семантика одна и та же. Defensive
`None` — это «explicit cross-workspace», не отдельная третья семантика.

**Edge case 2: Unknown / foreign `workspace_id`** → **404-like ошибка** `WorkspaceNotFound`
(новый exception в `tg_parser/auth/ownership.py` или `tg_parser/services/workspace_service.py`).
Mirror existing F4-A `assert_channel_access` pattern: не утечка существования (как hard 403
«exists, но not yours»). Конкретный exception class + error code определяется в Phase 2 (service
layer); поверхность MCP/CLI преобразует в structured error response.

**Edge case 3: Admin role + `workspace_id`** → admin **scoped как regular user** к своим
workspaces (нельзя передать `workspace_id` чужого user'а в обычный scoped tool). Cross-user
workspace inspection — через отдельный admin-only tool `list_all_workspaces(owner_id?)`,
опционально включаемый в Phase 3 sprint'а если admin-debugging UX нужен. Минимизирует
surface — отдельный admin tool лучше, чем admin-flag на каждом scoped tool.

**Обоснование:**

- **Stateless** — не задевает auth-resolver cache (60s в `tg_parser/auth/resolvers.py`), не
  требует session storage, нет concurrency-проблем («два конкурентных calls с разным active
  workspace одного user'а»).
- **Audience A4 (AI Agent Builder)** — explicit params natural для programmatic integration;
  agent сам решает, в каком workspace работать на каждом запросе.
- **Trade-off accepted:** verbose для UX (пользователь должен помнить workspace в каждом
  запросе). Mitigation — client-side wrappers могут хранить active workspace локально.

### Q3 — Bot integration `[CONFIRMED 2026-05-13]`: **skip Bot tools в F4-B Core MVP (MCP+CLI only)**

В Wave 1 step 2 **не добавляем workspace-tools в Bot**. Пользователи бота (A5 journalist, A6
curator) продолжают работать в user-scope без workspace-сужения. Owner проекта (A1) использует
workspaces через MCP (Cursor / Claude Desktop) и CLI.

**Обоснование:**

- **PHASE3_IMPLEMENTATION_PLAN.md «free-form чат без специальных команд»** — workspace switching
  через slash-commands ломает эту парадигму; natural-language switching через LLM tool-call
  требует расширения `_WRITE_TOOLS_REQUIRING_CONFIRM` (BUG-009 contract — см.
  [`START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md))
  и отдельного UX-mockup'а; всё это вне scope F4-B Core MVP.
- **Mirror F5-C MVP precedent** — Bot tools для F5-C тоже не были в MVP (см.
  [`FUTURE_FEATURES.md § F5-C`](FUTURE_FEATURES.md) L745 «Bot tools — только при UX-сигнале»);
  Bot подключается Phase 2 при концретном сигнале.
- **Уменьшает scope на ~0.5 сессии** + снижает риск регрессии Bot UX, который только что
  стабилизирован Wave 1 step 1 (Sessions H/I/J).
- **Audience A1 covered** — owner работает через MCP/CLI; это primary user F4-B Core по
  audience matrix.

### Q4 — Cross-workspace ops `[REFINED 2026-05-03 — locked]`

**Locked semantics (deep-dive 2026-05-03, см. [`PLANNING_F4B_WORKSPACES_PREP.md` § 4 Q4 «Refined decisions»](PLANNING_F4B_WORKSPACES_PREP.md)):**

**Refinement 1 — Cross-workspace search:** через `workspace_id=None` (или missing). Нет
отдельного `--all-workspaces` флага. Это closed by Q2 edge case 1 — минимизирует surface (один
параметр `workspace_id`, одна logical model None / specific).

**Refinement 2 — `move_workspace_source`:** **NOT в MVP**. Перенос канала между workspaces одного
user'а делается двумя non-atomic operations: `remove_workspace_source(from_ws, ch)` +
`add_workspace_source(to_ws, ch)`. **Risk acknowledged:** non-atomic — между двумя вызовами при
network/process crash канал оказывается «вне» обоих workspaces. **Mitigation:**

- Документировать в MCP/CLI tool descriptions что move = два calla.
- O-1 в [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) как «pending parity item»
  (см. § «O-1 status» в конце этого промпта — deferred per planning sub-session 2026-05-13).
- Если в Wave 1 step 3 / Wave 2 накопится evidence «move является common operation» — promote
  atomic tool. До того — defer per ADR 0006 принцип 6 (наблюдаемость → тюнинг).

**Refinement 3 — Cross-workspace topic-link visibility:** **workspace = scope-narrowing для
list/search, НЕ access control для get-details.**

- `list_topics(workspace_id="ws_1")` / `search_knowledge_base(workspace_id="ws_1")` /
  `ask_question(workspace_id="ws_1")` — применяют workspace-сужение через
  `effective_channel_ids`.
- `get_topic_details(topic_id, workspace_id=...)` — возвращает **full bundle items** (включая
  каналы из других workspaces user'а), независимо от `workspace_id` параметра. Mirror Q6
  any-source visibility. Workspace-фильтрация bundle items качественно меняет семантику data
  view (пользователь видит «обрезанный» topic) — это путает.

**Обоснование:**

- **Single user, multiple workspaces** — это просто scope-разделение, не privacy boundary.
  Privacy boundary — F4-A (per-user ownership). F4-B накладывается сверху как UX-фильтр.
- **Surface minimization** — один параметр (`workspace_id`) для всех scoped tools, единая
  logical model.

### Q5 — Shared channels (M2M внутри одного user'а) `[CONFIRMED 2026-05-13]`: **A (shared via `workspace_sources(workspace_id, source_id) PK`)**

Один `source_id` может быть в N workspaces одного пользователя. Schema:
`workspace_sources(workspace_id UUID, source_id UUID, added_at TIMESTAMPTZ, PRIMARY KEY (workspace_id, source_id))` —
композитный PK уже разрешает sharing внутри одного user'а.

**Обоснование:**

- **Audience A1 use-case** — пользователь хочет канал «Anthropic news» одновременно в workspace
  «AI/ML research» и в workspace «product updates»; дубликат ingestion (B exclusive scheme через
  `sources.workspace_id`) — anti-UX.
- **No duplicate ingestion** — все workspaces shar'ят один `ProcessedDocument` поток; ingestion /
  processing / topicization / embedding pipelines не меняются.
- **Удаление канала из workspace ≠ удаление канала** — `remove_workspace_source(ws, ch)` снимает
  только M2M row, source остаётся в `sources` (если ни в одном workspace не остался — это
  по-прежнему canal user'а, доступный через null-workspace).
- **Cross-user sharing — explicitly NOT в MVP.** Sharing между разными `owner_id` — это F4-B
  Sharing (Wave 2C по signal'у A3 Team). F4-B Core: один `owner_id` → N workspaces.

### Q6 — Topics + Workspaces `[CONFIRMED 2026-05-13]`: **A (visible if user has access to ANY source — mirror F4-A `assert_topic_access`)**

Topic spans channels A + B. Если канал A в workspace_1, канал B в workspace_2 (оба внутри одного
user'а) — topic visible **в обоих workspaces** (через scoped `list_topics`/`search`) **и** в
null-workspace.

**Зеркало F4-A pattern** в [`tg_parser/auth/ownership.py:29`](../../tg_parser/auth/ownership.py):

```python
async def assert_topic_access(user: CurrentUser, topic_sources: list[str]) -> None:
    """Raise PermissionDenied unless the user can see at least one source."""
    if user.allowed_channel_ids is None:
        return
    if not any(src in user.allowed_channel_ids for src in topic_sources):
        raise PermissionDenied(...)
```

В F4-B зеркало: «topic visible через workspace W если хотя бы один source из `topic.sources` ∈
`workspace_sources(W).source_ids`». Это применяется **только** в list/search контексте (Q4
refinement 3); `get_topic_details` показывает full bundle items.

**Обоснование:**

- **Mirror F4-A** — backward-compat 100%, никакой surprise UX для user'а который привык к
  cross-channel topic visibility.
- **Cross-channel темы** — главная ценность Living-KB; вариант B (visible only if **all**
  sources в active workspace) делает cross-channel топики нерелевантными.
- **No privacy concern в single-user contexte** — privacy concern появляется только при sharing
  (Wave 2C), там Q6 будет переоценён.

### Q7 — F11 Watchlist + Workspaces `[CONFIRMED 2026-05-13]`: **C (skip integration в MVP)**

`watch_interests.channel_ids[]` остаётся **без** workspace-поля. F11 watchlist продолжает работать
с явными `channel_ids[]`. Subscription на «все каналы workspace AI/ML» — Wave 2 task по сигналу.

**Обоснование:**

- **F11 уже работает** (commit `c1c9f35` 2026-04-25 — см.
  [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md` § Wave B](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)) — не ломать.
- **Eager vs lazy resolve** — design choice (eager-resolve в subscription time vs lazy в
  delivery time) требует отдельного analysis (см. prep § 4 Q7); неоправданно в Core MVP.
- **Уменьшает scope на ~0.5 сессии**, фокусирует MVP на core scoping integration.
- **Audience A5 (journalists)** — для них F11 без workspace-poля уже достаточно (one subscription
  = explicit list of channels).

### Q8 — F6 Digest + Workspaces `[CONFIRMED 2026-05-13]`: **C (skip integration в MVP)**

Аналогично Q7 для `digest_subscriptions.channel_ids[]`. F6 digest продолжает работать с явными
`channel_ids[]`. Integration через workspace_id — Wave 2 task.

**Обоснование:** идентичное Q7 + дополнительно **Wave 1 step 4 (Shareable Digest)** —
расширение F6 через `publish_to_channel`. Совмещать F4-B integration с shareable-digest extension
в одном sprint'е — accumulation риска. Workspace-integration F6 делается отдельным sprint'ом
**после** shareable-digest landed.

---

## Karpathy 7-checklist для F4-B Core контрактов

> Mirror ADR 0006 7-checklist. Каждая ячейка — `PASS` или `PASS with condition → <condition>`.
> Контракты-строки: 6 шт. (`workspaces` table → `effective_channel_ids` resolver). Принципы-столбцы:
> 7 шт. (Persistent → Graceful degradation). Финальный проход обязателен **до** старта Phase 1.

| Contract \ Principle | 1. Persistent entities | 2. Provenance | 3. Cheap retrieval | 4. Idempotency | 5. Living loop | 6. Observability | 7. Graceful degradation |
|---|---|---|---|---|---|---|---|
| **1. `workspaces` table** (schema) | PASS — explicit table, не `metadata: dict`; Pydantic `Workspace` в `domain/models.py`; JSON-схема `docs/contracts/workspace.schema.json` | PASS — `owner_id` FK + `created_at`/`updated_at` audit fields | PASS — pure SQL CRUD, no LLM | PASS with condition → `UNIQUE (owner_id, name)` гарантирует idempotent create по `(owner_id, name)`; `ON CONFLICT DO NOTHING` в repo | PASS — workspace это per-query filter, **не** pipeline-stage; ingestion / processing / topicization unchanged | PASS with condition → emit `tg_workspace_total{owner_id}` gauge + `tg_workspace_query_total{result}` counter в Phase 5 | PASS — отсутствие workspace = F4-A behavior (Q1 backward-compat) |
| **2. `workspace_sources` table** (M2M) | PASS — explicit M2M table с composite PK; не nullable column на `sources` | PASS — `added_at TIMESTAMPTZ` audit; FK ON DELETE CASCADE сохраняет referential integrity | PASS — pure SQL JOIN, index `idx_workspace_sources_source_id` для reverse lookup | PASS — composite PK `(workspace_id, source_id)` делает INSERT idempotent через `ON CONFLICT DO NOTHING` | PASS — M2M membership не trigger'ит pipeline; canal продолжает ingestion'иться независимо | PASS with condition → emit `tg_workspace_size` histogram (channels per workspace) в Phase 5 | PASS — empty `workspace_sources` для `ws_X` → `effective_channel_ids=[]` (explicit empty, не «all channels» — см. gotcha § 3) |
| **3. `WorkspaceRepo`** (data access) | PASS — ABC в `storage/ports.py`, SQLAlchemy реализация в `storage/sqlalchemy/workspace_repo.py` | PASS — repo возвращает `Workspace` domain models с traceable id / owner_id | PASS — все query через индексы (`owner_id`, `(workspace_id, source_id)`) | PASS — все upsert через `ON CONFLICT`; `delete` идемпотентен (return bool «existed»); `add_source` / `remove_source` идемпотентны | PASS — repo не интегрируется в pipeline; на чтение только | PASS with condition → repo emit'ит query latency через стандартный SQLAlchemy logging hook (re-use existing pattern из `digest_subscription_repo.py`) | PASS — repo isolated; DB down не валит другие slices |
| **4. `WorkspaceService`** (business logic + `effective_channel_ids` resolver) | PASS — service использует domain models, не raw dicts | PASS — service propagates `owner_id` + `workspace_id` в logs (`structlog.bind`) | PASS — все operations pure SQL через repo; no LLM | PASS — service-level checks reused (e.g. `assert_workspace_access(user, ws_id)` — idempotent permission check) | PASS — service не подписан на pipeline; на чтение только | PASS with condition → emit `tg_workspace_resolver_seconds` histogram + structured logs `effective_channel_ids_count` в каждом resolve call | PASS with condition → если `workspace_id` invalid → raise `WorkspaceNotFound` (Q2 edge case 2); если `workspace_id=None` → fallback F4-A; explicit error не silent degradation |
| **5. MCP/CLI tools** (7 user tools + 1 optional admin) | PASS — tool signatures explicit; не magic `kwargs` | PASS with condition → каждый tool emit'ит `structlog.bind(workspace_id=...)` для traceability «почему scoped just so» | PASS — tools pure SQL; no LLM | PASS — `create_workspace` UPSERT через `UNIQUE (owner_id, name)`; `add_workspace_source` / `remove_workspace_source` идемпотентны; `delete_workspace` ON DELETE CASCADE | PASS — tools surface, не pipeline | PASS with condition → emit `tg_workspace_tool_total{tool, result}` counter; reuse existing MCP/CLI logging | PASS — read-tools degradate `workspace_id` invalid → 404-like; write-tools idempotent → retry safe |
| **6. `effective_channel_ids` resolver** (`workspace_id=None / unknown / valid`) | PASS — pure-function resolver в `services/workspace_service.py`; не state | PASS — resolver вернёт {user_id, workspace_id, effective_channel_ids} для logging | PASS — single SQL query `SELECT source_id FROM workspace_sources WHERE workspace_id=:ws` + Python set intersection | PASS — pure deterministic function; idempotent by construction | PASS — resolver на per-query basis; не cached в session state | PASS with condition → emit `tg_workspace_effective_size` histogram (size of intersection result) | PASS — semantics: `workspace_id=None` → user.allowed_channel_ids (F4-A); `unknown ws_id` → `WorkspaceNotFound`; `valid empty ws` → `[]` (НЕ silently «all channels») |

**Conditions summary** (Phase 5 deliverables для observability):

- Phase 5 включает emit-метрики: `tg_workspace_total`, `tg_workspace_size`,
  `tg_workspace_query_total{result}`, `tg_workspace_effective_size`, `tg_workspace_resolver_seconds`,
  `tg_workspace_tool_total{tool, result}`.
- structlog bind `workspace_id` во всех scoped tool entry points (Phase 4).
- Test coverage для каждого edge case в conditions (Phase 5 testing).

---

## План шагов (5 phases / 5 atomic commits)

### Phase 1 — Schema + migration (~150–200 LOC, ~5 tests, ~0.3 сессии)

**Файлы:**

- `migrations/versions/ingestion/20260513_add_workspaces.py` (new) — next slot после
  `d7e8f9a0b1c4` (`20260427_soft_delete_sources`). Сначала `ls migrations/versions/ingestion/`,
  взять следующий timestamp.
- `tg_parser/storage/sqlalchemy/_metadata.py` — добавить `workspaces_table` + `workspace_sources_table`
  declarations (для `target_metadata` + `alembic check`).
- `tg_parser/domain/models.py` — `Workspace` + `WorkspaceSource` Pydantic.
- `docs/contracts/workspace.schema.json` (new) — JSON-схема (mirror `topic_card.schema.json`
  style).

**DDL:**

```python
def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_workspaces_owner_name"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_workspaces_name_nonempty"),
        sa.CheckConstraint("length(name) <= 200", name="ck_workspaces_name_length"),
    )
    op.create_index("idx_workspaces_owner_id", "workspaces", ["owner_id"])

    op.create_table(
        "workspace_sources",
        sa.Column("workspace_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "source_id",
                                name="pk_workspace_sources"),
    )
    op.create_index("idx_workspace_sources_source_id",
                    "workspace_sources", ["source_id"])


def downgrade() -> None:
    op.drop_index("idx_workspace_sources_source_id", table_name="workspace_sources")
    op.drop_table("workspace_sources")
    op.drop_index("idx_workspaces_owner_id", table_name="workspaces")
    op.drop_table("workspaces")
```

**Workspace name uniqueness — per-owner** (см. gotcha § 6). `UNIQUE (owner_id, name)` —
два пользователя могут иметь workspace «AI/ML»; один пользователь не может иметь два workspace
«AI/ML».

**Smoke:**

```bash
.venv/bin/tg-parser db check --db ingestion       # No new upgrade operations detected
.venv/bin/tg-parser db upgrade --db ingestion     # ровно 1 ревизия применена
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "\d workspaces" -c "\d workspace_sources"
```

**Tests (Phase 1):**

- `tests/test_f4b_schema.py` — alembic upgrade + downgrade smoke (in-memory psycopg pool); FK
  / unique / check constraints срабатывают; `gen_random_uuid()` default работает.

**Commit 1/5 message draft:**

```
feat(F4-B): schema for workspaces — tables + migration + Pydantic (1/5)

Adds the foundation for F4-B Core: тематические коллекции каналов внутри
одного пользователя. Schema only (additive), no behavior change yet.

- migrations/versions/ingestion/20260513_add_workspaces.py: workspaces +
  workspace_sources в tg_parser DB (per-domain alembic_version_ingestion);
  composite PK на workspace_sources гарантирует idempotent add_source.
  Q5 = A (M2M shared inside one owner).
- _metadata.py: Table() declarations.
- domain/models.py: Workspace + WorkspaceSource pydantic.
- docs/contracts/workspace.schema.json: JSON-схема для контракта.
- tests/test_f4b_schema.py: 5 alembic / constraint smoke tests.

Q1 = B (opt-in, no default) — миграция не создаёт workspace для существующих
users; их workspace-count остаётся = 0 до явного create_workspace.

Closes F4-B prep § 4 Q1/Q5 + design schema из PLANNING_F4B_WORKSPACES_PREP.md § 5.
```

### Phase 2 — Service layer + repo + ownership integration (~250–350 LOC, ~12 tests, ~0.5 сессии)

**Файлы:**

- `tg_parser/storage/ports.py` — `WorkspaceRepo` Protocol (ABC).
- `tg_parser/storage/sqlalchemy/workspace_repo.py` (new) — SAWorkspaceRepo по образцу
  `digest_subscription_repo.py`.
- `tg_parser/services/workspace_service.py` (new) — `WorkspaceService` + `effective_channel_ids`
  resolver.
- `tg_parser/auth/ownership.py` — `assert_workspace_access(user, workspace_id) -> Workspace`
  helper + `WorkspaceNotFound` exception (Q2 edge case 2).
- `tg_parser/services/db_context.py` — extend `processing_repos()` / `services_provider`
  factory для wiring `WorkspaceRepo` + `WorkspaceService`.

**`WorkspaceRepo` Protocol:**

```python
class WorkspaceRepo(Protocol):
    async def create(self, *, owner_id: UUID, name: str,
                     description: str | None = None) -> Workspace: ...
    async def get(self, workspace_id: UUID) -> Workspace | None: ...
    async def list_by_owner(self, owner_id: UUID) -> list[Workspace]: ...
    async def list_all(self) -> list[Workspace]: ...  # admin-only
    async def rename(self, workspace_id: UUID, new_name: str) -> Workspace: ...
    async def delete(self, workspace_id: UUID) -> bool: ...
    async def add_source(self, workspace_id: UUID, source_id: UUID) -> bool: ...
    async def remove_source(self, workspace_id: UUID, source_id: UUID) -> bool: ...
    async def list_sources(self, workspace_id: UUID) -> list[UUID]: ...
```

**`WorkspaceService.effective_channel_ids` resolver — core invariant:**

```python
async def effective_channel_ids(
    self,
    user: CurrentUser,
    workspace_id: str | None,
) -> list[str] | None:
    """Compute the intersection of user.allowed_channel_ids and workspace.channel_ids.

    Semantics (Q2 edge cases + Q1 backward-compat):
    - workspace_id is None: return user.allowed_channel_ids (F4-A behavior).
    - workspace_id unknown or owned by other user: raise WorkspaceNotFound.
    - workspace_id valid:
        - if user.allowed_channel_ids is None (admin): return workspace's channel_ids.
        - else: return list(set(allowed) & set(workspace_channels)) — может быть [].
                EMPTY list != None; не silently деградировать на «all channels».
    """
    if workspace_id is None:
        return user.allowed_channel_ids  # F4-A fallback

    workspace = await assert_workspace_access(user, workspace_id)  # raises WorkspaceNotFound
    workspace_channel_ids = await self.repo.list_source_channel_ids(workspace.id)

    if user.allowed_channel_ids is None:
        # admin without per-user scoping → workspace scope only
        return workspace_channel_ids

    return [c for c in workspace_channel_ids if c in set(user.allowed_channel_ids)]
```

**`assert_workspace_access` в `tg_parser/auth/ownership.py`:**

```python
async def assert_workspace_access(
    user: CurrentUser,
    workspace_id: str,
    *,
    repo: WorkspaceRepo,
) -> Workspace:
    """Raise WorkspaceNotFound if workspace is missing OR not owned by user.

    Admin (user.is_admin=True) gets access to ANY workspace via this helper
    (mirroring F4-A pattern); for admin cross-user inspection use the dedicated
    list_all_workspaces admin tool.
    """
    workspace = await repo.get(UUID(workspace_id))
    if workspace is None:
        raise WorkspaceNotFound(f"Workspace {workspace_id} not found")
    if not user.is_admin and workspace.owner_id != user.user_id:
        # 404-like: don't leak existence (Q2 edge case 2)
        raise WorkspaceNotFound(f"Workspace {workspace_id} not found")
    return workspace
```

**Tests (Phase 2):**

- `tests/test_f4b_workspace_repo.py` (~8 tests) — CRUD, `list_by_owner` фильтрует чужие;
  `add_source` идемпотентен; `remove_source` returns bool «existed»; `delete` cascade на
  `workspace_sources`; `UNIQUE (owner_id, name)` блокирует duplicate.
- `tests/test_f4b_workspace_service.py` (~10 tests) — `effective_channel_ids` для всех trex
  edge cases (None / unknown / valid-empty / valid-with-overlap / admin); ownership через
  `assert_workspace_access`; rename / delete.
- `tests/test_f4b_assert_workspace_access.py` (~4 tests) — `WorkspaceNotFound` для unknown /
  foreign / admin pass-through.

**Commit 2/5 message draft:**

```
feat(F4-B): service + repo + ownership (2/5)

WorkspaceRepo + WorkspaceService + assert_workspace_access ownership helper +
WorkspaceNotFound exception. Includes effective_channel_ids resolver — the
core invariant linking F4-A allowed_channel_ids and F4-B workspace scope.

- storage/ports.py: WorkspaceRepo Protocol.
- storage/sqlalchemy/workspace_repo.py: SAWorkspaceRepo по образцу digest.
- services/workspace_service.py: CRUD + effective_channel_ids resolver
  (Q2 edge cases 1–2 + Q1 backward-compat).
- auth/ownership.py: assert_workspace_access + WorkspaceNotFound (Q2 EC2 = 404-like).
- services/db_context.py / services_provider.py: wiring.
- 22 unit tests covering repo CRUD + service edge cases + ownership.

Locked semantics: workspace_id=None → F4-A behavior; unknown/foreign →
WorkspaceNotFound; valid empty ws → []; admin scoped как regular user
per Q2 edge case 3.

Closes F4-B prep § 4 Q2/Q4 (locked) + § 5 service layer.
```

### Phase 3 — MCP + CLI surface (~250–350 LOC, ~10 tests, ~0.5 сессии)

**Файлы:**

- `tg_parser/mcp_server.py` — 7 user tools + 1 optional admin tool.
- `tg_parser/cli/app.py` + `tg_parser/cli/workspace_cmd.py` (new) — typer sub-app.
- `docs/MCP_AGENT_GUIDE.md` — 7 новых tools с примерами.
- `docs/USER_GUIDE.md` — раздел «Workspaces (F4-B Core)».

**MCP tools (7 user + 1 admin):**

```python
@mcp.tool()
async def list_workspaces(ctx: Context | None = None) -> list[dict]:
    """List all workspaces of the calling user."""

@mcp.tool()
async def create_workspace(
    name: str, description: str | None = None, ctx: Context | None = None,
) -> dict:
    """Create a new workspace. UNIQUE (owner_id, name)."""

@mcp.tool()
async def rename_workspace(
    workspace_id: str, new_name: str, ctx: Context | None = None,
) -> dict:
    """Rename a workspace (ownership-checked)."""

@mcp.tool()
async def delete_workspace(workspace_id: str, ctx: Context | None = None) -> dict:
    """Delete a workspace (ON DELETE CASCADE removes workspace_sources rows;
    sources themselves are preserved)."""

@mcp.tool()
async def add_workspace_source(
    workspace_id: str, channel_id: str, ctx: Context | None = None,
) -> dict:
    """Add a channel to a workspace. Idempotent (ON CONFLICT DO NOTHING).
    Note: To move a channel between workspaces use remove_workspace_source +
    add_workspace_source (Q4 — atomic move deferred per O-1)."""

@mcp.tool()
async def remove_workspace_source(
    workspace_id: str, channel_id: str, ctx: Context | None = None,
) -> dict:
    """Remove a channel from a workspace (M2M row only; source remains)."""

@mcp.tool()
async def list_workspace_sources(
    workspace_id: str, ctx: Context | None = None,
) -> dict:
    """List channels in a workspace."""

# OPTIONAL admin tool (Q2 edge case 3):
@mcp.tool()
async def list_all_workspaces(
    owner_id: str | None = None, ctx: Context | None = None,
) -> list[dict]:
    """Admin-only: list all workspaces, optionally filtered by owner_id."""
```

**CLI commands:**

```
tg-parser workspace list
tg-parser workspace create --name "AI/ML" --description "..."
tg-parser workspace rename <ws_id> "new name"
tg-parser workspace delete <ws_id>
tg-parser workspace add-source <ws_id> --channel <channel_id>
tg-parser workspace remove-source <ws_id> --channel <channel_id>
tg-parser workspace list-sources <ws_id>
tg-parser admin list-all-workspaces [--owner-id <user_id>]
```

**Tests (Phase 3):**

- `tests/test_f4b_workspace_mcp.py` (~7 tests) — каждый tool ownership-aware; foreign
  workspace_id → 404-like error; admin-only `list_all_workspaces` rejects non-admin.
- `tests/test_f4b_workspace_cli.py` (~3 tests) — `create` / `add-source` / `delete` happy path
  через typer runner.

**Commit 3/5 message draft:**

```
feat(F4-B): MCP + CLI surface (3/5)

7 user tools + 1 admin tool for workspace operations. MCP + CLI only — Bot
deferred per Q3 (UX-сигнал нужен).

- mcp_server.py: list_workspaces, create_workspace, rename_workspace,
  delete_workspace, add_workspace_source, remove_workspace_source,
  list_workspace_sources + admin list_all_workspaces (optional).
- cli/workspace_cmd.py: tg-parser workspace {list,create,rename,delete,
  add-source,remove-source,list-sources}; admin list-all-workspaces.
- MCP_AGENT_GUIDE + USER_GUIDE updates.
- 10 new tests covering ownership + admin + idempotency.

Q3 = skip-bot-MVP per F4-B prep § 4 Q3 + strategy § 8.
```

### Phase 4 — Scoping integration в existing read-tools (~150–200 LOC, ~8 tests, ~0.4 сессии)

**Файлы (extends, no behavior change для null-workspace path):**

- `tg_parser/mcp_server.py` — add `workspace_id: str | None = None` to:
  - `list_channels`
  - `list_topics`
  - `get_topic_details`
  - `search_knowledge_base`
  - `ask_question`
  - `get_document`
  - `get_cross_channel_stats` / `get_related_topics`
- `tg_parser/cli/*` — mirror в существующих CLI commands.

**Surface-level resolver wrapper:**

```python
async def _resolve_for_query(
    user: CurrentUser, workspace_id: str | None,
    workspace_service: WorkspaceService,
) -> list[str] | None:
    """Resolve effective_channel_ids for any scoped read-tool.

    Q2 edge case 1: None or missing → F4-A behavior (user.allowed_channel_ids).
    Q2 edge case 2: unknown ws_id → propagates WorkspaceNotFound.
    Q2 edge case 3: admin → workspace-scoped same as regular user.
    """
    return await workspace_service.effective_channel_ids(user, workspace_id)
```

В каждом scoped tool:

```python
@mcp.tool()
async def list_topics(
    channel_id: str | None = None,
    workspace_id: str | None = None,  # NEW (Q2 = A)
    ctx: Context | None = None,
) -> list[dict]:
    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    effective = await _resolve_for_query(user, workspace_id, workspace_service)
    # existing service call signature не меняется:
    return await topic_card_service.list_by_channel(
        channel_id=channel_id, allowed_channel_ids=effective,
    )
```

**Q4 refinement 3 — `get_topic_details` exception:** для `get_*_details` tools workspace_id
**не** применяется к bundle items (full bundle visibility). В сигнатуре параметр всё ещё есть
для consistency, но используется только для access-check «есть ли у user'а доступ хоть к
одному source через workspace или через user-scope». Mirror F4-A `assert_topic_access`.

**Tests (Phase 4):**

- `tests/test_f4b_scoping_integration.py` (~6 tests) — каждый scoped tool с
  `workspace_id=None` → F4-A behavior identical; с `workspace_id=<valid>` → result сужен; с
  `workspace_id=<unknown>` → 404-like; empty workspace → empty result (НЕ all channels).
- `tests/test_f4b_get_details_full_bundle.py` (~2 tests) — Q4 refinement 3:
  `get_topic_details(topic_id, workspace_id="ws_1")` возвращает full bundle включая каналы
  из других workspaces user'а.

**Commit 4/5 message draft:**

```
feat(F4-B): scoping integration in read-tools (4/5)

Adds optional workspace_id parameter to all scoped MCP/CLI read-tools.
Q2 = A locked semantics: None|missing → F4-A behavior; valid → intersection;
unknown → WorkspaceNotFound 404-like. Service layer signatures UNCHANGED —
all surface-level via effective_channel_ids resolver from Phase 2.

- mcp_server.py: workspace_id param на 8 scoped tools.
- cli/app.py: --workspace-id на соответствующих subcommands.
- Q4 refinement 3 honored: get_*_details возвращают full bundle items
  независимо от workspace_id (workspace = scope-narrowing, не access control).
- 8 new tests covering Q2 edge cases × scoped tools + Q4 R3.

F4-A backward-compat 100%: legacy calls без workspace_id работают
bit-for-bit как F4-A (verified в test_f4b_backward_compat — следующий commit).
```

### Phase 5 — Tests + observability + docs (~250–350 LOC, ~15 tests, ~0.4 сессии)

**Файлы:**

- `tests/test_f4b_backward_compat.py` (new) — F4-A regression guard: для каждого scoped tool
  вызов без `workspace_id` параметра → identical output к F4-A baseline.
- `tests/test_f4b_workspace_isolation.py` (new) — user A не видит workspace user B;
  cross-user `workspace_id` → 404-like; admin pass-through через `list_all_workspaces`.
- `tests/test_f4b_metrics.py` (new) — Prometheus exporters emit
  `tg_workspace_total`, `tg_workspace_size`, `tg_workspace_query_total{result}`,
  `tg_workspace_effective_size`.
- `tg_parser/api/metrics.py` — добавить новые counters/histograms.
- `tg_parser/services/workspace_service.py` — инструментировать resolver structlog binds +
  metric emit.
- `docs/notes/FUTURE_FEATURES.md` § F4-B — статус `✅ Core MVP DONE 2026-05-XX`.
- `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — добавить раздел `## 2026-05-XX — Wave 1
  step 2 (F4-B Core) DONE ✅`.
- `CHANGELOG.md` § `Unreleased` — F4-B Core entry.
- `docs/contracts/workspace.schema.json` — финальная версия (если не закрыта в Phase 1).

**Golden-path test (`tests/test_f4b_golden_path.py`):**

End-to-end: создать user → создать 2 workspace («AI», «Product») → добавить 3 канала в «AI» (один
из них также в «Product») → `list_topics(workspace_id=AI)` возвращает topics только из «AI»
каналов → `list_topics(workspace_id=Product)` возвращает только из «Product» → `list_topics()`
(null-workspace) возвращает union обоих → cross-channel topic spanning AI ∪ Product visible в
обоих workspaces → `get_topic_details(...)` для cross-channel topic возвращает full bundle
items (Q4 R3) → `delete_workspace(AI)` → topics from AI channels still visible через
null-workspace (sources не удалены).

**Test count summary (across all phases):**

- Phase 1: ~5 tests (schema)
- Phase 2: ~22 tests (repo + service + ownership)
- Phase 3: ~10 tests (MCP + CLI)
- Phase 4: ~8 tests (scoping integration)
- Phase 5: ~15 tests (backward-compat + isolation + metrics + golden path)
- **Total ~60 new F4-B tests** (target 50–70 range — mirror F11 test pyramid density).

**Commit 5/5 message draft:**

```
test(F4-B): regression guards + observability + docs (5/5)

Final phase: regression guards для F4-A backward-compat, isolation tests
для multi-user safety, Prometheus metrics для observability, docs hygiene.

- tests/test_f4b_backward_compat.py: каждый scoped tool без workspace_id ≡
  F4-A baseline (verified via shared fixture compare).
- tests/test_f4b_workspace_isolation.py: cross-user 404-like guarantees.
- tests/test_f4b_metrics.py: Prometheus exporter shape (tg_workspace_*).
- tests/test_f4b_golden_path.py: end-to-end multi-workspace scenario.
- api/metrics.py: tg_workspace_total / size / query_total / effective_size /
  resolver_seconds histograms + counters (Karpathy 7-checklist principle 6).
- workspace_service.py: structlog binds + metric instrumentation.
- FUTURE_FEATURES.md § F4-B → ✅ Core MVP DONE; ROADMAP § Wave 1 step 2 DONE.
- CHANGELOG.md § Unreleased: F4-B Core block.

Verification: pytest --tb=short -q ⇒ baseline + ~60 passed, 0 failures,
0 new skips. ruff format + check clean. CI green (5/5 jobs).

Roadmap: F4-B Core ✅ → Wave 1 step 3 (Surface Parity) is next.
```

---

## Hidden gotchas

> Эти 6 пунктов — sustained lessons из F11 / F5-C / F4-A / Sessions H/I/J/K. Каждый — реальный
> precedent, не теоретический риск.

### 1. F4-A backward-compat — `workspace_id=None` MUST produce IDENTICAL behavior

Любой scoped tool, вызванный **без** параметра `workspace_id` или с `workspace_id=None`, ДОЛЖЕН
возвращать bit-for-bit identical output к F4-A baseline. Это **hard requirement**, проверяется
`tests/test_f4b_backward_compat.py` в Phase 5. **Не должно быть** ни одного существующего F4-A
теста, который ломается. Если ломается — design issue в resolver, STOP и diagnose.

**Конкретно:** в `effective_channel_ids(user, workspace_id=None)` early return
`user.allowed_channel_ids` **до** любых repo calls. Не должно быть skip-логики типа «если
у user нет workspaces — пропустить filter» — это antipattern, который случайно лечит правильное
поведение через wrong reasoning.

### 2. `assert_topic_access` mirror в F4-B — any-source visibility (Q6)

В Phase 2 / Phase 4 для топиков spanning несколько каналов: visibility check должен mirror'ить
F4-A pattern. Если topic spans канал A (в workspace_1) + канал B (в workspace_2 того же
user'а) — topic visible через **любой** scoped query (`list_topics(workspace_id=ws_1)` И
`list_topics(workspace_id=ws_2)` И `list_topics(workspace_id=None)`).

**Implementation:** в `topic_card_repo.list_by_channel(channel_ids=effective)` —
если хотя бы один из `topic.sources` ∈ `effective` → topic visible.

**`get_topic_details` (Q4 R3 exception):** возвращает full bundle items независимо от
`workspace_id` — workspace = scope-narrowing для list/search, **не** access control для
get-details. Тесты `test_f4b_get_details_full_bundle.py` в Phase 4 verify этого.

### 3. Empty workspace semantics — `effective_channel_ids = []` НЕ silently «all channels»

Если workspace существует, но пуст (`workspace_sources` для этого ws_id — empty set), то
`effective_channel_ids(...)` возвращает **explicit empty list `[]`**, **НЕ** `None` и **НЕ**
fallback на `user.allowed_channel_ids`.

`[]` means «не показывать ничего» — это правильная семантика для empty workspace. Silent
degradation на «all channels» — это data leak (пользователь думает он сужает scope, а получает
обратное).

**Repo / service layer должны различать:**

- `allowed_channel_ids=None` → admin scope «все каналы в системе» (F4-A semantics)
- `allowed_channel_ids=[]` → empty scope «ничего не показывать»
- `allowed_channel_ids=["c1", "c2"]` → specific scope

Existing F4-A services (`retrieval_service`, `analytics_service`, `topic_linking_service`)
проверить — все ли уже корректно handle'ят empty list. Если кто-то трактует `[] == None` (admin)
— это F4-A bug, который F4-B обнажит. Fix в той же phase, не deferring.

### 4. Non-atomic `remove + add` (Q4 R2 / O-1) — concurrent ingestion window risk

`move_workspace_source` НЕ реализуется в MVP. Перенос = два calla:

```python
remove_workspace_source(from_ws, channel_id)
# ← gap window: канал не в from_ws, не в to_ws
add_workspace_source(to_ws, channel_id)
```

**В gap window:**

- `list_topics(workspace_id=from_ws)` НЕ покажет topics этого канала.
- `list_topics(workspace_id=to_ws)` ТОЖЕ НЕ покажет.
- `list_topics(workspace_id=None)` покажет (null-workspace — все каналы user'а).

**Document это в MCP/CLI tool descriptions:** «To move a channel between workspaces use
remove_workspace_source + add_workspace_source. These calls are NOT atomic; concurrent reads
during the gap window may return inconsistent results. If atomicity is required, file a feature
request (tracked as O-1 in PARITY_DECISION_TRACKING.md).»

### 5. Pre-flight nomenclature — `tg_parser_bot` контейнер (Session K § 5.4 lesson)

**ВСЕ** pre-flight checks для bot-метрик ДОЛЖНЫ указывать контейнер `tg_parser_bot`, не
`tg_parser` (это API контейнер per `docker-compose.yml:36`), не `tg-parser-bot` (dash-form
не существует), не `tg_bot` (это compose service name, не runtime container name).

Это уже исправлено в [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 1.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md)
и runbook'ах (PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) 2026-05-08). Pre-flight § 3
этого промпта уже использует правильное имя.

**При написании любого нового pre-flight скрипта** — проверить `docker logs tg_parser_bot`, не
`tg_parser`. Если в Phase 5 будет emit-metric `tg_bot_*` для F4-B — её собирать с `tg_parser_bot`.

### 6. Workspace name uniqueness — **per-owner**, не global

`UNIQUE (owner_id, name)` — два разных user'а МОГУТ иметь workspace «AI/ML» (это
семантически разные сущности — каждый user имеет свой namespace). Один user НЕ МОЖЕТ иметь два
workspace с одинаковым name.

**Implication для error messages:**

- При `create_workspace("AI/ML")` если у user'а уже есть «AI/ML» → error «Workspace 'AI/ML'
  already exists for this user».
- При `rename_workspace(ws_id, "AI/ML")` если у user'а уже есть «AI/ML» (другой ws) →
  error «Cannot rename: workspace 'AI/ML' already exists».

Phase 2 tests должны cover оба cases.

**Length & whitespace:** `CheckConstraint` в Phase 1 schema гарантирует non-empty trimmed
name + max 200 chars. Phase 2 service layer должен делать `name = name.strip()` перед repo
call (defensive — schema поймает, но клиентам нужно дать чёткий error).

---

## Risks

| ID | Риск | Severity | Likelihood | Mitigation |
|----|------|----------|------------|------------|
| R-1 | Migration regression — `ALTER TABLE` / new FK ломает existing F4-A queries или `sources` integrity | Medium | Low | Migration строго **additive** (две новые таблицы, две FK на existing). Никакого `ALTER` на `sources` / `users`. Downgrade полностью обратим. Rollback plan: `tg-parser db downgrade --db ingestion --revisions 1 --yes` на VPS — таблицы дропаются, F4-A workflow остаётся работоспособным. |
| R-2 | Q3 / Q7 / Q8 flip mid-sprint — UX-driven request «давай добавим Bot tools / F11 integration в этот же sprint» | Medium | Low–Medium | Scope locked в planning sub-session 2026-05-13. Если внутри sprint'а UX-сигнал появится — STOP, document signal в [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) как observation, **не флипать** scope. Bot tools / F11+workspace_id / F6+workspace_id — отдельные sprint'ы по signal'у. |
| R-3 | O-1 deferred (atomic `move_workspace_source`) → пользователь делает unsafe move в gap window | Low | Very Low (single-user, no production multi-tenant) | Document в MCP/CLI tool descriptions (см. gotcha § 4); O-1 в parity tracker для Wave 1 step 3 / Wave 2 re-evaluation. Accepted risk per planning sub-session 2026-05-13. |
| R-4 | Q6 cross-channel topic visibility ломает F4-A `assert_topic_access` контракт | High | Very Low | Q6 решение **именно сохраняет** F4-A contract (mirror any-source visibility). Phase 5 backward-compat tests catch'ат любой drift. Если кто-то предложит «strict workspace isolation» — это анти-pattern для Core MVP, defer. |
| R-5 | Workspace ownership при удалении user'а — orphan workspaces | Low | Very Low | `ON DELETE CASCADE` уже в schema (`workspaces.owner_id → users.id`). Workspaces удаляются вместе с user'ом (sources остаются — соответствует F4-A `sources.owner_id` semantics). Phase 1 schema test покрывает. |
| R-6 | Vector search performance при добавлении workspace JOIN | Low | Low | F4-A уже использует `WHERE channel_ids && ARRAY[:allowed]` с GIN index в `document_embeddings.channel_ids`. Workspace resolve просто **сужает** массив на surface level **до** SQL call'а. SQL signature service-слоя не меняется. Ожидаемый overhead — +5–15% latency на `list_topics`/`search` из-за extra resolver call (~ms). Benchmark в Phase 5 если есть concern. |
| R-7 | Service layer signature drift — кто-то по случайно сменит `allowed_channel_ids: list[str] \| None` на `workspace_id` параметр | Medium | Low | Hard contract: service signatures **не меняются**. Workspace resolution живёт на surface level (`_resolve_for_query` wrapper). Code review во всех 5 PR commits. F4-A regression тесты ловят. |
| R-8 | Documentation drift — `docs/notes/FUTURE_FEATURES.md` § F4-B остаётся со старой scope-оценкой ~2.5 сессии без MVP-status update | Low | Low | Phase 5 explicit deliverable: update FUTURE_FEATURES § F4-B → ✅ Core MVP DONE + список deferred (Q3/Q7/Q8/O-1 + Bot integration + Sharing). |
| R-9 | Bot regression при Phase 4 scoping changes — даже без bot tools changes, изменения в shared MCP read-tools могут случайно сломать Bot's resolve_mcp_user flow | Medium | Very Low | Bot tools уже отдельный execution path (`tg_parser/bot/tools.py`). Phase 4 changes только signature extensions optional params. Bot integration tests (`tests/test_bot_*`) запускаются в baseline pytest + 24h watch после deploy. |
| R-10 | Scope creep по docs hygiene (M-1..M-16 backlog) — кто-то соблазнится «заодно поправить» | Medium | Medium | Anti-scope явно зафиксирован (см. § «Anti-scope»). Docs hygiene = отдельная ~0.5-сессия PR до или после F4-B Core. Не смешивать. |

**Rollback procedure:** `git revert HEAD~4..HEAD` (5 atomic commits) → `git push` → CI восстановит
код. Затем `docker compose run --rm tg_parser tg-parser db downgrade --db ingestion --revisions 1
--yes` на VPS — миграция откатится, таблицы исчезнут, F4-A продолжает работать (изоляция через
per-domain `alembic_version_ingestion` и отсутствие FK от других таблиц на `workspaces`).

---

## PR shape — Single PR + 5 atomic commits (Session F pattern)

> **Зафиксировано в planning sub-session 2026-05-13 + execution plan § 2.2.** НЕ multi-PR (F11
> pattern, который сейчас не подходит — F4-B Core это связный feature, не три independent bug
> fixes).

| Commit | Scope | LOC est. | Tests | Phase |
|--------|-------|----------|-------|-------|
| **1/5** `feat(F4-B): schema for workspaces — tables + migration + Pydantic` | Schema, migration, domain models, JSON contract | ~150–200 | ~5 | Phase 1 |
| **2/5** `feat(F4-B): service + repo + ownership` | Repo, service, `effective_channel_ids` resolver, `assert_workspace_access`, `WorkspaceNotFound` | ~250–350 | ~22 | Phase 2 |
| **3/5** `feat(F4-B): MCP + CLI surface` | 7 user tools + 1 admin tool + CLI subcommands + docs | ~250–350 | ~10 | Phase 3 |
| **4/5** `feat(F4-B): scoping integration in read-tools` | `workspace_id` param на 8 scoped MCP/CLI tools + Q4 R3 get-details exception | ~150–200 | ~8 | Phase 4 |
| **5/5** `test(F4-B): regression guards + observability + docs` | Backward-compat tests, isolation tests, Prometheus metrics, golden path, FUTURE_FEATURES/ROADMAP/CHANGELOG | ~250–350 | ~15 | Phase 5 |

**Total estimate:** ~1050–1450 LOC + ~60 new tests. Mirror F11 (~1200 LOC + ~30 tests) /
F5-C (~1500 LOC + ~58 tests).

**Quality bar (per execution plan § 2.2):**

- Все `tests/test_f4b_*.py` PASS в default mode + Postgres mode (TEST_POSTGRES gate).
- Baseline + ~60 новых тестов; **0 regressions** по существующим F4-A тестам (`tests/test_f4_*.py`).
- `ruff format` + `ruff check .` clean.
- CI green (5/5 jobs).
- После deploy — 24h watch (mirror Session G pattern, **`tg_parser_bot` container**) — нет
  `confirm_flow_mismatch` / `gemini_*` сигналов; нет `tg_workspace_resolver_seconds` p99
  drift на bot pipeline.

---

## PR checklist

> Канон для GitHub PR description (copy-paste sufficient). Расширенная версия с karpathy-like
> tagging — опционально создать `F4B_PR_CHECKLIST.md` по образцу `F11_PR_CHECKLIST.md` если
> needed; здесь — компактный список.

### Schema + migration

- [ ] Миграция `migrations/versions/ingestion/20260513_add_workspaces.py` создана;
      `down_revision = "d7e8f9a0b1c4"`; `tg-parser db check --db ingestion` →
      `No new upgrade operations detected.`
- [ ] `Table()` декларации `workspaces_table` + `workspace_sources_table` в
      `tg_parser/storage/sqlalchemy/_metadata.py` (drift check via alembic-guardrail CI job).
- [ ] `UNIQUE (owner_id, name)` + `CheckConstraint` (non-empty trimmed, max 200) на `workspaces`.
- [ ] `PRIMARY KEY (workspace_id, source_id)` на `workspace_sources`; `idx_workspace_sources_source_id`
      для reverse lookup.
- [ ] `ON DELETE CASCADE` на обоих FK (`workspaces.owner_id → users.id`,
      `workspace_sources.workspace_id → workspaces.id`, `workspace_sources.source_id → sources.source_id`).

### Domain + contract

- [ ] `Workspace` + `WorkspaceSource` Pydantic-модели в `tg_parser/domain/models.py`.
- [ ] JSON-схема `docs/contracts/workspace.schema.json` (mirror `topic_card.schema.json` style).

### Service + repo

- [ ] `WorkspaceRepo` Protocol в `tg_parser/storage/ports.py` (9 методов).
- [ ] `SAWorkspaceRepo` в `tg_parser/storage/sqlalchemy/workspace_repo.py` (mirror
      `digest_subscription_repo.py` pattern).
- [ ] `WorkspaceService` в `tg_parser/services/workspace_service.py` с CRUD методами +
      `effective_channel_ids(user, workspace_id) -> list[str] | None` resolver.
- [ ] `assert_workspace_access(user, workspace_id, repo) -> Workspace` в
      `tg_parser/auth/ownership.py`.
- [ ] `WorkspaceNotFound` exception class (Q2 edge case 2 = 404-like; не leak existence).
- [ ] `services_provider` / `db_context.processing_repos()` wiring для `WorkspaceRepo` +
      `WorkspaceService` (mirror digest pattern).

### MCP / CLI surface

- [ ] 7 user MCP tools (`list_workspaces`, `create_workspace`, `rename_workspace`,
      `delete_workspace`, `add_workspace_source`, `remove_workspace_source`,
      `list_workspace_sources`).
- [ ] 1 optional admin tool `list_all_workspaces(owner_id?)` (Q2 edge case 3).
- [ ] CLI: `tg-parser workspace {list,create,rename,delete,add-source,remove-source,list-sources}`
      + `tg-parser admin list-all-workspaces`.
- [ ] Tool descriptions включают note про `move = remove + add` non-atomic (Q4 R2 / O-1
      acknowledgement).

### Scoping integration

- [ ] `workspace_id: str | None = None` параметр добавлен на 8 scoped MCP tools
      (`list_channels`, `list_topics`, `get_topic_details`, `search_knowledge_base`,
      `ask_question`, `get_document`, `get_cross_channel_stats`, `get_related_topics`).
- [ ] CLI mirror — `--workspace-id` на соответствующих subcommands.
- [ ] `_resolve_for_query(user, workspace_id, workspace_service)` helper в MCP server module
      (surface-level wrapper над `WorkspaceService.effective_channel_ids`).
- [ ] **Q4 R3 honored:** `get_topic_details` / `get_document` возвращают full bundle items
      независимо от workspace_id (test `test_f4b_get_details_full_bundle.py`).
- [ ] **Service signatures unchanged:** `retrieval_service.search`, `analytics_service.*`,
      `topic_linking_service.*`, `channel_service.*` по-прежнему принимают
      `allowed_channel_ids: list[str] | None` — workspace resolution на surface level.

### Tests

- [ ] `tests/test_f4b_schema.py` — alembic + constraints (~5).
- [ ] `tests/test_f4b_workspace_repo.py` — CRUD + idempotency (~8).
- [ ] `tests/test_f4b_workspace_service.py` — `effective_channel_ids` × edge cases (~10).
- [ ] `tests/test_f4b_assert_workspace_access.py` — ownership + WorkspaceNotFound (~4).
- [ ] `tests/test_f4b_workspace_mcp.py` — MCP tools surface (~7).
- [ ] `tests/test_f4b_workspace_cli.py` — CLI subcommands (~3).
- [ ] `tests/test_f4b_scoping_integration.py` — `workspace_id` × 8 scoped tools (~6).
- [ ] `tests/test_f4b_get_details_full_bundle.py` — Q4 R3 (~2).
- [ ] `tests/test_f4b_backward_compat.py` — F4-A regression guard (~5).
- [ ] `tests/test_f4b_workspace_isolation.py` — multi-user isolation (~5).
- [ ] `tests/test_f4b_metrics.py` — Prometheus exporter shape (~3).
- [ ] `tests/test_f4b_golden_path.py` — end-to-end (~1).
- [ ] **Total ~60 новых тестов**, baseline + 60 passed, 0 failures, 0 new skips.
- [ ] **0 regressions** по существующим `tests/test_f4_*.py` (F4-A test suite).

### Observability + metrics (Karpathy 7-checklist principle 6 conditions)

- [ ] `tg_workspace_total{owner_id}` gauge в `tg_parser/api/metrics.py`.
- [ ] `tg_workspace_size` histogram (channels per workspace).
- [ ] `tg_workspace_query_total{result}` counter (`result=scoped|null_fallback|not_found`).
- [ ] `tg_workspace_effective_size` histogram (size of intersection result — F4-A ∩ workspace).
- [ ] `tg_workspace_resolver_seconds` histogram (resolver latency).
- [ ] `tg_workspace_tool_total{tool, result}` counter (per-tool usage).
- [ ] `structlog.bind(workspace_id=..., effective_count=...)` во всех scoped tool entry points.

### Docs

- [ ] `docs/USER_GUIDE.md` — новый раздел «Workspaces (F4-B Core)» с примерами CLI/MCP.
- [ ] `docs/MCP_AGENT_GUIDE.md` — 7 (+1) новых tools с примерами + Q4 R2 note про move.
- [ ] `docs/notes/FUTURE_FEATURES.md` § F4-B — `✅ Core MVP DONE 2026-05-XX`, deferred list
      (Q3 Bot / Q7 F11 / Q8 F6 / O-1 atomic move / Sharing).
- [ ] `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — раздел `## 2026-05-XX — Wave 1 step 2
      DONE ✅` с cross-link на DONE marker (создаваемый отдельной post-deploy сессией).
- [ ] `CHANGELOG.md` § `Unreleased` — F4-B Core block.
- [ ] `docs/contracts/workspace.schema.json` — финальная версия.

### Hygiene

- [ ] `ruff format` + `ruff check .` clean (sustained lesson Sprint A → F11 → F5-C).
- [ ] Commit messages: `feat(F4-B): <description> (N/5)` style; breaking changes — нет;
      verification numbers в каждом; cross-link на planning sub-session.
- [ ] CI: 5/5 jobs зелёные.
- [ ] 24h watch GREEN после deploy (mirror Session G pattern, `tg_parser_bot` container).

---

## Anti-scope

> Эти **9** пунктов **намеренно НЕ входят** в F4-B Core MVP. Mirror parent planning prep
> anti-scope. Любое UX-soft pressure типа «давай заодно» — STOP, document signal в parity
> tracker / FUTURE_FEATURES, **не флипать** scope.

1. **F4-A контракт НЕ трогается.** `CurrentUser.allowed_channel_ids` контракт остаётся
   нерушимым; F4-B накладывается **сверху** как surface-level resolver. Никаких изменений в
   `tg_parser/auth/models.py`, `tg_parser/auth/resolvers.py`, `tg_parser/auth/ownership.py`
   (кроме нового `assert_workspace_access` + `WorkspaceNotFound` — это additive).
2. **Bot tools для workspace operations — NOT в MVP** (Q3 = skip). Bot users работают в
   user-scope. Bot integration отдельным sprint'ом при UX-сигнале (slash-commands vs
   natural-language switching — design choice пунктов prep § 4 Q3 — резервируется).
3. **F11 watchlist integration с workspace_id — NOT в MVP** (Q7 = C). Wave 2 task при сигнале.
4. **F6 digest integration с workspace_id — NOT в MVP** (Q8 = C). Wave 2 task; не смешивать с
   Wave 1 step 4 (Shareable Digest).
5. **Atomic `move_workspace_source` — NOT в MVP** (Q4 R2 / O-1 deferred). Перенос =
   `remove + add` через два calla. Wave 1 step 3 / Wave 2 re-evaluation по evidence.
6. **Cross-user sharing (workspace_members M2M + ACL) — NOT в MVP.** F4-B Sharing — Wave 2C
   по signal'у A3 (Team).
7. **HTTP API endpoints для workspaces — NOT в MVP.** MCP + CLI достаточно. Если signal от A4
   появится — это Wave 1 step 3 (Surface Parity).
8. **Docs hygiene backlog (M-1 / M-2 / M-3 / M-7 / M-8 / M-15 / M-16)** — отдельная ~0.5-сессия
   docs-only до или после F4-B Core. Не смешивать с feature work.
9. **Bot UX для workspace context** (visible feedback в каждом ответе, slash-commands,
   natural-language switching) — Q3 defer; output Q3 = skip-Bot-MVP.

---

## O-1 status — **Deferred to Wave 1 step 3 / Wave 2**

> **Verify-action per Step 0 planning sub-session 2026-05-13:** Search
> [`PARITY_DECISION_TRACKING.md` § 3](PARITY_DECISION_TRACKING.md) O-1 entry — has evidence
> accumulated since DONE marker 2026-05-08?

**Result:** **NO new evidence found.** O-1 (atomic `move_workspace_source(channel_id, from_ws,
to_ws)`) accumulated **zero** production signals since added 2026-05-03; was preemptively flagged
based on theoretical risk («pain-driven evidence pending»). Wave 1 step 1 didn't surface
move-pattern usage because step 1 was inward-facing Bot UX (no workspace operations whatsoever).

**Decision:** **defer** O-1 atomic move tool to Wave 1 step 3 / Wave 2 per planning sub-session
2026-05-13. F4-B Core MVP implements **non-atomic** move via two calls (`remove_workspace_source`
+ `add_workspace_source`) — documented in Q4 R2 (locked) + gotcha § 4 + MCP/CLI tool descriptions.

**Mitigation for MVP gap window:**

- MCP/CLI tool descriptions explicitly document non-atomic semantics.
- `tg_workspace_tool_total{tool=remove_workspace_source}` +
  `tg_workspace_tool_total{tool=add_workspace_source}` counters позволяют после Wave 1 step 2
  closure measure'ить «remove → add» pattern frequency. Если ratio remove×add ≈ 1:1 с
  small temporal gap (< 1s между calls по одному `(channel_id, owner_id)`) → strong signal к
  promote atomic tool в Wave 1 step 3.
- O-1 остаётся в parity tracker как pending; verify-action repeat при Wave 1 step 3 planning
  sub-session.

**Bookkeeping follow-up (post-sprint, не часть этого sprint'а):** добавить в
[`PARITY_DECISION_TRACKING.md` § 3 O-1](PARITY_DECISION_TRACKING.md) entry footnote с датой
verify-action и decision (deferred 2026-05-13). Это journal note, делается отдельно после F4-B
Core landed (либо в Wave 1 step 2 DONE marker `REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md` § 3.1).

---

## Cross-links footer

| Документ | Зачем |
|----------|-------|
| **Parent planning sub-session:** этот чат (2026-05-13) | Source of truth для locked decisions Q1/Q3/Q5/Q6/Q7/Q8; Q2/Q4 inherit from 2026-05-03 deep-dive |
| [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) | DONE marker предыдущего шага (Bot UX hardening) — pre-flight gate-1 reference + lessons learned § 5 (container name `tg_parser_bot`) |
| [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) | Prep с Q1–Q8 + locked refinements Q2 / Q4 (2026-05-03 deep-dive); § 5 5-phase MVP outline; § 6 preliminary Karpathy walkthrough; § 7 reading list |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 + § 8](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | Wave 1 sequence + 8 preliminary Q-recommendations (this sprint locks them as `[CONFIRMED 2026-05-13]`) |
| [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 2.1 + § 2.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) | Operational companion: Single PR + 5 atomic commits, 24h watch с `tg_parser_bot`, DONE marker template, signal collection cadence |
| [`PARITY_DECISION_TRACKING.md` § 3](PARITY_DECISION_TRACKING.md) | O-1 (deferred per § «O-1 status» above) + O-2 (Bot fuzzy-suggestion gap — unrelated to F4-B) |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7 принципов Living-KB — финальный checklist в § «Karpathy 7-checklist» этого промпта |
| [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) | **Format-precedent** для структуры этого промпта (~673 строки, dense actionable content) |
| [`docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`](../plans/F4_MULTI_TENANCY_FULL_PLAN.md) | F4-A finalized plan — точки интеграции, pattern для re-use, контракт `CurrentUser.allowed_channel_ids` |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Roadmap-обзор + cross-link target для DONE marker (создаётся отдельной post-deploy сессией) |
| [`tg_parser/auth/ownership.py:29`](../../tg_parser/auth/ownership.py) | `assert_topic_access` — pattern для Q6 mirror в F4-B (any-source visibility) |
| [`tg_parser/storage/sqlalchemy/digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) | Pattern для `SAWorkspaceRepo` (CRUD + ownership-aware listing) |

---

## После F4-B Core — что дальше

Согласно audience-driven Wave 1 sequence per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md):

1. **Wave 1 step 3 — MCP/API/CLI Surface Parity** (~1–2 сессии). Planning sub-session: re-read
   [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) pre-references P-1..P-5 +
   observations from steps 1, 2 (особенно O-1 verify-action repeat). Текущая гипотеза — P-1
   (Watchlist HTTP API parity) или P-2 (Digest HTTP API parity), final choice по signals.
2. **Wave 1 step 4 — Shareable Digest via TG-channel** (~0.3 сессии). Light extension F6:
   `subscribe_digest(..., publish_to_channel="@my_curated_digest")`. Audience A6 enabler
   без Web. Может быть совмещён со step 3 если scope позволит — оценить на step 3 planning.
3. **Wave 1.5 Operational Dogfooding (parallel)** — daily TG_parser use + light external
   validation (2–3 знакомых через MCP / digest channel) + light market research.
4. **Wave 1 closure** — `REVIEW_2026-05-XX_WAVE1_DONE.md` + Decision Point per § 5.3 strategy.

**Совокупно:** F4-B Core MVP закрывает audience A1 (Solo Knowledge Curator) на 100% + foundation
для A6 (Domain Curator). Wave 1 шаги 3 + 4 закрывают A4 (AI Agent Builder) + A6 light-MVP. После
этого продукт имеет полный solo-полированный цикл (ingestion → processing → topicization →
тематические workspaces → user-defined алерты → scheduled digests → shareable digests),
готовый к Decision Point после ~3-4 месяцев Wave 1.5 dogfooding.

---

## История промпта

| Дата | Изменение |
|------|-----------|
| 2026-05-13 | Первая версия. Создана planning sub-session ~0.3 сессии в fresh chat (parent context: post-Session-K). Confirms Q1/Q3/Q5/Q6/Q7/Q8 preliminary recommendations as `[CONFIRMED 2026-05-13]`; inherits Q2/Q4 `[REFINED 2026-05-03 — locked]`. Karpathy 7-checklist filled (6 contracts × 7 principles — no empty cells). O-1 verify-action: **deferred** (no evidence). Sprint shape: Single PR + 5 atomic commits per execution plan § 2.2. |
