# Plan — F4-B Core post-merge docs hygiene (2026-05-13)

**Дата подготовки:** 13 мая 2026 (planning sub-session ~0.2 сессии, post-merge audit follow-up).
**Тип сессии:** Docs-only (~0.4 сессии, **Single PR + 1 commit** рекомендовано; split-commit как alternative).
**HEAD на момент написания плана:** `7953302 feat(F4-B Core): thematic workspaces over F4-A multi-tenancy (#67)` на `origin/main` (Wave 1 step 2 landed).
**Closes:** post-merge documentation drift между user-facing surface и F4-B Core feature, делянка которой landed в [`PR #67`](https://github.com/AlexEfimov/TG_parser/pull/67).
**Parent reference:** [`START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`](START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md) (LANDED — этот план добавит ему top-banner).

**Прецеденты (читать перед стартом):**

- [`START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`](START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md) — source of truth для феатуры (5 phases, Q1–Q8 locked, 8 MCP tools + `workspace_id` на 8 read tools).
- [`START_PROMPT_DOC_HYGIENE_2026-05-XX.md`](START_PROMPT_DOC_HYGIENE_2026-05-XX.md) — параллельный hygiene sprint (M-1..M-16 backlog). **Anti-scope этого плана** — не пересекаться с M-1..M-16; см. § 3 ниже.
- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — actual MCP surface (factual baseline для tool counts).
- [`tg_parser/cli/workspace_cmd.py`](../../tg_parser/cli/workspace_cmd.py) — actual CLI surface для workspaces (factual baseline для USER_GUIDE CLI examples).
- [`docs/contracts/workspace.schema.json`](../contracts/workspace.schema.json) — JSON contract (already current, не трогать).

---

## 1. Цель и контекст

После merge'а F4-B Core (PR #67 → `main 7953302`) user-facing surface (USER_GUIDE / MCP_AGENT_GUIDE / README / SERVER_ARCHITECTURE / ROADMAP_V3) **не знает о workspaces**: новой главы нет, 8 workspace MCP tools не задокументированы, `workspace_id` параметр на 8 scoped read-tools не аннотирован, tool counts расходятся с реальностью, sprint-prompt не помечен как landed. Этот mini-sprint синкает только то, что **прямо относится к F4-B**, и оставляет broader hygiene backlog (M-1..M-16) отдельной сессии.

**Re-verified audit findings (HEAD `7953302`):**

1. **Actual MCP tool count = 43** (см. `grep -c '^@mcp\.tool()' tg_parser/mcp_server.py`). **Audit recap говорил «35» — это устаревший counter.** Реальные claims в docs:
   - `README.md` L19, L733, L734, L805 → «24 tools» (× MCP, bot, и cross-reference);
   - `docs/USER_GUIDE.md` L9, L1541 → «24 инструмента»;
   - `docs/MCP_AGENT_GUIDE.md` L3 → «Tools: 26»; L792 → «Version: 4.3» (header L3 говорит 4.4 — внутренний drift внутри одного файла);
   - `docs/SERVER_ARCHITECTURE.md` L72 → «Tools (17):» — самая устаревшая цифра.
2. **`workspace_id` параметр** в `mcp_server.py` присутствует **на 8 scoped read tools** (verified `grep 'workspace_id: str \| None'`):
   `search_knowledge_base` (L853), `ask_question` (L914), `list_topics` (L986), `get_topic_details` (L1084), `list_channels` (L1157), `get_document` (L1196), `get_related_topics` (L1247), `get_cross_channel_stats` (L1290) — **ни один из них** не задокументирован в `MCP_AGENT_GUIDE.md` Tool Schemas (всё ещё F4-A-only signatures).
3. **8 workspace MCP tools** (`list_workspaces`, `create_workspace`, `rename_workspace`, `delete_workspace`, `add_workspace_source`, `remove_workspace_source`, `list_workspace_sources`, `list_all_workspaces`) присутствуют в `mcp_server.py` (L3097–L3379), но **полностью отсутствуют** в `MCP_AGENT_GUIDE.md` (ни Tools by Category, ни Tool Schemas).
4. **`pyproject.toml` = `4.2.0`** (`grep '^version' pyproject.toml`) — `README.md` L5/L728, `USER_GUIDE.md` L3, `MCP_AGENT_GUIDE.md` footer L792 говорят «4.3» / header L3 говорит «4.4». Это **version-cut decision**, **не** docs-fix; этот план фиксирует только factual claims о feature surface, не bump'ает версию.
5. **`docs/INSTRUCTIONS.md`** — **не существует** (verified `glob`); audit recap correctly hedged "(if exists)". Не в scope.
6. **`docs/notes/START_PROMPT_DOC_HYGIENE_2026-05-XX.md`** — **существует** и описывает M-1..M-16 backlog в составе 4 atomic commits, включая M-1 (tools count drift) и M-2 (version asynchrony). **Overlap warning:** наш план чинит tool-count claims **только в файлах, которые трогает по F4-B-причинам** (USER_GUIDE / MCP_AGENT_GUIDE / README / SERVER_ARCHITECTURE) — оставшиеся файлы M-1 (`mcp-management-tools-spec.md`, `chatgpt-mcp-compatibility.md`, `mcp-clients-compatibility.md`) уходят целиком в hygiene sprint.

**Что НЕ делаем:** не редактируем `pyproject.toml`; не трогаем `CHANGELOG.md` / `ROADMAP_KARPATHY_LIKE_LIVING_KB.md` / `FUTURE_FEATURES.md § F4-B` / `PARITY_DECISION_TRACKING.md § O-1` / `docs/contracts/workspace.schema.json` / `tests/test_f4b_deferred_surface_guard.py` (все уже current per audit); не создаём `REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md` (post-deploy + 24h-watch артефакт); не запускаем M-1..M-16 backlog; не пишем новых ADR / контрактов / методологии.

---

## 2. Scope (что входит)

### Категория A — User-facing sync (F4-B surface annotations)

#### A.1 `docs/USER_GUIDE.md`

**Edit type:** добавить новую главу + локально освежить tool-count в footer.

**Конкретно:**

1. После главы «Topic Watchlist (F11)» (после строки L734) или перед главой «Evolving Topic Summaries (F5-C)» (L738) — **новая глава «Workspaces (F4-B Core)»** со структурой:
   - **Intro** — что такое workspace, Q1 (opt-in, no default), F4-A backward-compat invariant («workspace_id=None → identical to F4-A»).
   - **CLI examples** — cross-checked против `tg_parser/cli/workspace_cmd.py` (см. § 5 verification checklist):
     ```
     tg-parser workspace list
     tg-parser workspace create --name "AI/ML" --description "Anthropic, OpenAI"
     tg-parser workspace rename <ws_id> "new name"
     tg-parser workspace delete <ws_id>
     tg-parser workspace add-source <ws_id> --channel @durov
     tg-parser workspace remove-source <ws_id> --channel @durov
     tg-parser workspace list-sources <ws_id>
     tg-parser workspace list-all [--owner-id <user_id>]   # admin only
     ```
     Все команды принимают опциональный `--user <uuid>` (F4-A convention — act on behalf of user; default = admin).
   - **MCP examples** — короткий блок «через MCP то же доступно — см. `MCP_AGENT_GUIDE.md` § Workspaces (F4-B Core)».
   - **Q4 R2 move semantics note** — «Перенос канала между workspaces = `remove-source` + `add-source`, **не атомарно** (O-1 deferred per `PARITY_DECISION_TRACKING.md § 3`). В gap window между двумя calls канал виден только через null-workspace.»
   - **Q4 R3 get-details note** — «`get_topic_details(topic_id, workspace_id=...)` возвращает full bundle items независимо от `workspace_id`; workspace = scope-narrowing для list/search, не access control для get-details.»
   - **Что НЕ в MVP** — Bot tools (Q3), F11+workspace_id (Q7), F6+workspace_id (Q8), atomic move (O-1), sharing — короткий bullet list с cross-link на `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md § «Anti-scope»`.
2. **L1541 footer:** `«оптимизированный справочник с полными schema всех 24 инструментов»` → `«… всех 43 инструментов»` (factual sync; **тонкая правка только в F4-B-touched секции**).

**LOC delta:** ~+140 / -2.

**Requires reading implementation:** **да** — обязательно cross-check `tg_parser/cli/workspace_cmd.py` (8 typer commands, signatures, --user / --description / --owner-id options) **и** `tg_parser/mcp_server.py:3097-3379` (8 workspace tools для cross-link integrity).

**User-facing behavior claims bar:** **высший** — это первая user-visible документация workspaces; ошибка здесь повторится в каждой downstream цитировании.

#### A.2 `docs/MCP_AGENT_GUIDE.md`

**Edit type:** добавить 8 новых tool entries (table + schema), аннотировать `workspace_id` на 8 scoped read tools, синкнуть version / tool-count claims внутри файла.

**Конкретно:**

1. **L3 header:** `«Version: 4.4 | Tools: 26 | …»` → `«Version: 4.3 | Tools: 43 | …»` (привести в соответствие с footer L792, fix внутренний drift в одном файле).
2. **L792 footer:** уже `«Version: 4.3 | Last updated: April 2026»` → `«Version: 4.3 | Last updated: May 2026»` (single-line edit, factual).
3. **Tools by Category** (между L100 «remove_user_auth» и L103 «Prompt Management», или новой секцией перед «Prompt Management»):
   ```
   ### Workspaces (F4-B Core)

   | Tool | Auth | Description |
   |------|------|-------------|
   | `list_workspaces` | any | List the caller's workspaces. Owner-scoped. |
   | `create_workspace` | any | Create a new workspace (UNIQUE per owner_id, name). |
   | `rename_workspace` | any | Rename a workspace (ownership-checked). |
   | `delete_workspace` | any | Delete a workspace; ON DELETE CASCADE removes membership rows; sources preserved. |
   | `add_workspace_source` | any | Attach a channel to a workspace (idempotent; ON CONFLICT DO NOTHING). |
   | `remove_workspace_source` | any | Detach a channel from a workspace (M2M row only; source remains). |
   | `list_workspace_sources` | any | List channel_ids attached to a workspace. |
   | `list_all_workspaces` | admin | Admin-only: list every workspace, optionally filtered by owner_id. |
   ```
4. **Tool Schemas** — между `### reload_prompts` (~L592–L602) и `## Common Workflows` (L605), либо в новой `### Workspaces` секции, добавить 8 schemas. Каждая mirror'ит существующий стиль schema-блока (Parameters / Returns / 1–2-line behaviour note). Ключевые behaviour notes:
   - В `add_workspace_source` / `remove_workspace_source` — обязательная Q4 R2 note: «To move a channel between workspaces use `remove_workspace_source` + `add_workspace_source`. The move is **not atomic** (O-1 deferred per `PARITY_DECISION_TRACKING.md § 3`); concurrent reads during the gap window may return inconsistent results.»
   - В `list_all_workspaces` — admin-only marker + 404-like behaviour для non-admin caller.
5. **Annotate `workspace_id` parameter** на 8 существующих scoped read-tool schemas:
   - `### search_knowledge_base` (L117) — Parameters block: add `workspace_id: str | null = None       # Workspace scope (F4-B); None = F4-A behavior`.
   - `### ask_question` (L144) — same parameter line.
   - `### list_topics` (L167) — same.
   - `### get_topic_details` (L184) — same **+ Q4 R3 note:** «`workspace_id` is used for access-check only; bundle items are returned in full (workspace = scope-narrowing for list/search, not access control for get-details).»
   - `### list_channels` (L194) — same.
   - `### get_document` (L209) — same **+ Q4 R3 note (mirror).**
   - `### get_cross_channel_stats` (L219) — same.
   - `### get_related_topics` (L230) — same.
6. **Common Workflows** (L605–L727) — добавить новый workflow «9. Manage Workspaces (F4-B Core)» с end-to-end примером (`create_workspace` → `add_workspace_source` × 2 → `list_topics(workspace_id=...)` → `remove_workspace_source` + `add_workspace_source` move) + явное упоминание non-atomic move semantics.
7. **REST API endpoints table (L753–L788)** — **НЕ редактировать.** F4-B Core MVP не выставляет HTTP API endpoints для workspaces (per Q анти-scope в sprint prompt — «HTTP API endpoints для workspaces — NOT в MVP. MCP + CLI достаточно»). Если кто-то по ошибке предложит добавить — STOP, скоуп ограничен MCP + CLI.

**LOC delta:** ~+200 / -10.

**Requires reading implementation:** **да** — критически. Каждое поле в schemas должно matchить actual Pydantic args в `tg_parser/mcp_server.py:3097-3379` (workspace tools) и existing read-tool defs (L847–L1290).

**User-facing behavior claims bar:** **высший** — это primary документ для AI-агентов (Cursor / Claude Desktop); ошибки парам приводят к broken tool calls.

#### A.3 `README.md`

**Edit type:** освежить feature list + tool-count claims; **НЕ** трогать version.

**Конкретно:**

1. **L5 header:** `«**Версия: 4.3**»` — **не трогать** (это release-cut decision; см. § 3 anti-scope).
2. **L19 (Интерфейсы / MCP Server):** `«24 инструмента для AI-агентов»` → `«43 инструмента для AI-агентов»`.
3. **L20 (Telegram Bot):** `«24 tools, free-form чат»` → **оставить 24** (Bot tools не получили workspace surface per Q3 = skip-Bot-MVP — проверить актуальный `len(TOOL_DECLARATIONS)` если есть сомнение; **не путать** с MCP count).
4. **L9–L37 «Возможности»** — после блока «Multi-Tenancy (F4)» (L24–L28) добавить ~5-строчный блок «Workspaces (F4-B Core)»:
   ```
   **Workspaces (F4-B Core):**
   - Тематические коллекции каналов внутри одного пользователя (Solo Knowledge Curator UX)
   - 8 MCP tools + CLI surface (`tg-parser workspace …`); Bot tools defer
   - Optional `workspace_id` параметр на scoped read-tools (list/search/ask) — F4-A backward-compat 100%
   - Per-query scope narrowing через `effective_channel_ids` resolver
   ```
5. **L733 (Deployment Readiness table):** `«MCP Server | ✅ Deployed | Streamable HTTP + bearer auth, 24 tools»` → `«… 43 tools»`.
6. **L734:** `«Telegram Bot | ✅ Deployed | Gemini agent, 24 tools, V1.2»` — **не трогать** (Bot tools count независим от MCP, F4-B их не менял).
7. **L805 «MCP Agent Guide»:** `«справочник для AI-агентов (24 MCP tools, …)»` → `«… (43 MCP tools, …)»`.

**LOC delta:** ~+10 / -4.

**Requires reading implementation:** **да** — для cross-check Bot tools count (L20, L734) **не трогать**, если только не verified что F4-B их не добавил. Per Q3 = skip-Bot-MVP: Bot count неизменен.

**User-facing behavior claims bar:** **средний** — README не описывает per-tool surface; ошибки тут менее критичны, чем в MCP_AGENT_GUIDE.

#### A.4 `docs/SERVER_ARCHITECTURE.md`

**Edit type:** освежить outdated tool count (L72), добавить short mention workspace tables в data-flow если структурная секция есть.

**Конкретно:**

1. **L72:** `«**Tools** (17):»` → `«**Tools** (43):»`. Ниже idёт bulleted list 12 tool names (L73–L82), который **outdated по другому измерению** (там перечислены только legacy tools без F4 / F5-C / F6 / F11 / F4-B). Два варианта:
   - **A (рекомендуется):** заменить bulleted list на cross-link: `«Полный список — см. [`docs/MCP_AGENT_GUIDE.md § Tools by Category`](MCP_AGENT_GUIDE.md). Категории: Search & Q&A (2), Navigation (4), Cross-channel Analytics (2), Channel Management (4), Pipeline Control (2), Export F2 (2), Digests F6 (3), Topic Watchlist F11 (4), LLM Configuration (3), User Management F4 (7), Prompt Management (1), Channel Export Status (1), Resummarize F5-C (2), Workspaces F4-B Core (8) = 43.»`
   - **B:** аккуратно дополнить bulleted list до полных 43 имён. Дороже по maintenance (next sprint снова устареет).
2. **Поиск структурных секций** про DB tables / data flow / resolver — quick `Grep -n 'workspaces\|workspace_sources\|effective_channel_ids' docs/SERVER_ARCHITECTURE.md`. Если ничего нет (вероятно) — **НЕ добавлять** новые секции в этом плане; SERVER_ARCHITECTURE — runtime-deployment doc (Nginx, Docker, TLS, ports), а не data-model doc. Workspace tables (`workspaces`, `workspace_sources`) уже описаны в `docs/contracts/workspace.schema.json` + `migrations/versions/ingestion/*workspaces*.py`; добавлять копию сюда — duplication. **Решение:** только tool-count fix; structural секции — defer.

**LOC delta:** ~+5 / -12.

**Requires reading implementation:** **да** — для choice между A и B надо посчитать tools per category; см. baseline counts в § 5 verification checklist.

**User-facing behavior claims bar:** **низкий** — SERVER_ARCHITECTURE редко читается AI-агентами; основной reader — ops-engineer при deploy/troubleshoot.

#### A.5 `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`

**Edit type:** **decision-pending** — см. § 8 open questions.

**Вариант 1 (рекомендуется по умолчанию):** короткий cross-link «Wave 1 step 2 (F4-B Core Workspaces) landed 2026-05-13 — см. `ROADMAP_KARPATHY_LIKE_LIVING_KB.md § «Wave 1 step 2 DONE»` + `CHANGELOG.md § Unreleased`». Добавить в конец секции «Done — Living-KB contract (Wave 1)» (после L28) или в новый «Done — Audience-driven Wave 1» блок. ~+5 / -0 LOC.

**Вариант 2:** mark `ROADMAP_V3_PRODUCTION_FIRST.md` как **superseded by `ROADMAP_KARPATHY_LIKE_LIVING_KB.md`** (deprecation banner в L1). Mirror precedent для `SESSION48_*` docs (если они marked в Session K extended scope). ~+8 / -0 LOC. **Решение:** не делать в этом sprint'е без явного пользовательского sign-off, т.к. это product-strategy decision, не docs-fix. M-1..M-16 hygiene sprint имеет C-3 entry «Двойное определение Wave 1 (Living-KB vs Audience) в ROADMAP_V3_PRODUCTION_FIRST.md» — там это будет решаться в составе общей disambiguation.

**Заключение:** в этом mini-sprint'е выполняем **Вариант 1** (cross-link). Полная supersede-decision — defer до C-3 в hygiene sprint.

**LOC delta:** ~+5 / -0.

**Requires reading implementation:** нет (только cross-link, code-shape не цитируется).

**User-facing behavior claims bar:** **низкий** (planning doc, не behavior claim).

### Категория C — Post-merge housekeeping

#### C.1 `docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`

**Edit type:** top banner.

**Конкретно:** добавить в L1 (перед `# Sprint F4-B Core — …`) banner:

```markdown
> ✅ **LANDED 2026-05-13 — main HEAD `7953302` — [PR #67](https://github.com/AlexEfimov/TG_parser/pull/67) squash-merged.**
> Wave 1 step 2 closed pending 24h prod-watch + DONE marker
> (`REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md` to be drafted in a follow-up
> post-deploy session — см. [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)).
> Этот промпт сохранён as-is как historical artifact; правки запрещены.

---
```

**LOC delta:** ~+8 / -0.

**Requires reading implementation:** нет.

**User-facing behavior claims bar:** **низкий** (статус-маркер на planning artifact'е).

#### C.2 Другие planning prompts с terminal status

**Pre-check:** `grep -l 'LANDED\|DONE\|SUPERSEDED' docs/notes/START_PROMPT_*.md` — посмотреть, какие планы уже имеют terminal banner. Если есть другой post-merge planning prompt без banner — добавить (только если он напрямую относится к Wave 1 step 2 / F4-B Core).

**Expected result:** скорее всего никаких других не требуется — только `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md` относится прямо к этому merge.

**LOC delta:** 0 (если ничего не найдено) или ~+5 / -0 (если ещё один prompt найден).

**Requires reading implementation:** нет.

---

## 3. Anti-scope (что НЕ входит)

Эти **9** пунктов **намеренно НЕ входят** в этот mini-sprint. Любое UX-soft pressure типа «давай заодно» — STOP, document signal, не флипать scope.

1. **M-1..M-16 backlog** (separate hygiene sprint, см. [`START_PROMPT_DOC_HYGIENE_2026-05-XX.md`](START_PROMPT_DOC_HYGIENE_2026-05-XX.md)). Overlap notice: M-1 (tools count drift) и M-2 (version asynchrony) затрагивают часть тех же файлов; этот план фиксит tool counts **только в файлах, которые трогает по F4-B-причинам** (USER_GUIDE / MCP_AGENT_GUIDE / README / SERVER_ARCHITECTURE). Файлы `docs/mcp-management-tools-spec.md`, `docs/chatgpt-mcp-compatibility.md`, `docs/mcp-clients-compatibility.md` (M-1 scope) **не трогаются** этим планом — целиком уходят в hygiene sprint.
2. **`pyproject.toml = 4.2.0 → 4.3.x`** — release-cut decision, не docs-fix. Этот план фиксит **factual feature claims** в docs, но не bump'ает версию. Version-drift (pyproject `4.2.0` vs `README.md / USER_GUIDE.md` «4.3» vs `MCP_AGENT_GUIDE.md` header «4.4» vs footer «4.3») остаётся unfixed; обсуждается в § 8 open question.
3. **`docs/methodology/**`** — отдельный worktree (см. `AGENTS.md`).
4. **ADR edits** — audit не флагнул ни одного drifted ADR; ADR 0001/0003/0004 без implementation-status — это M-3 (hygiene sprint), не F4-B.
5. **JSON contracts** — `docs/contracts/workspace.schema.json` уже current (audit).
6. **`CHANGELOG.md`** — уже current (audit; F4-B Core block добавлен в `## [Unreleased]` в Phase 5).
7. **`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`** — уже current (audit; `## 2026-05-13 — Wave 1 step 2 DONE` секция добавлена в Phase 5).
8. **`FUTURE_FEATURES.md § F4-B`** — уже current (audit; `✅ Core MVP DONE 2026-05-13` маркер).
9. **`PARITY_DECISION_TRACKING.md § O-1`** — уже current (audit; deferred decision noted).
10. **`REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md` creation** — это post-deploy + 24h-watch артефакт, не часть docs sprint'а. Создаётся отдельной post-deploy сессией.
11. **Новые ADR / contracts / методология / runbooks** — none required для F4-B docs sync.
12. **Bot tools count refresh** в README L20 / L734 — Bot не получил workspace surface (Q3 = skip-Bot-MVP); count неизменен. Не трогать без проверки `len(TOOL_DECLARATIONS)`.

---

## 4. PR shape — Single commit recommended

### Recommended: **1 atomic commit** (~0.4 сессии)

**Reasoning:** все правки — derivative от одного underlying change (F4-B Core landed); split на 2 commits не даёт independent rollback value (Cat A.1–A.5 без C.1 LANDED-banner = inconsistent; C.1 без Cat A = banner на promised-but-undocumented state). Single commit + atomic = чистая git history + single revert path.

**Commit message draft:**

```
docs(F4-B): post-merge user-facing sync + LANDED banner

Sync user-facing surface to F4-B Core (Workspaces) landed in #67
(main 7953302). Wave 1 step 2 closes pending 24h prod-watch + DONE
marker (REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md follow-up session).

- USER_GUIDE: new chapter "Workspaces (F4-B Core)" — intro,
  CLI examples (cross-checked vs cli/workspace_cmd.py), MCP cross-link,
  Q4 R2 non-atomic move note, Q4 R3 get-details full-bundle note,
  deferred list (Q3 Bot / Q7 F11 / Q8 F6 / O-1).
- MCP_AGENT_GUIDE: 8 new workspace tools (table + schemas) + workspace_id
  parameter docs on 8 scoped read-tools + Q4 R3 note on get_topic_details
  / get_document + new workflow #9 "Manage Workspaces" + tool count
  claim corrected (24/26 → 43); header/footer version drift fixed.
- README: feature list += Workspaces block; MCP tool count refresh
  (24 → 43) in 3 spots; Bot count unchanged (Q3 = skip-Bot-MVP).
- SERVER_ARCHITECTURE: tool count 17 → 43 + cross-link to
  MCP_AGENT_GUIDE for full list (replaces stale bulleted list).
- ROADMAP_V3_PRODUCTION_FIRST: cross-link "Wave 1 step 2 (F4-B Core)
  landed 2026-05-13" → ROADMAP_KARPATHY.
- START_PROMPT_SPRINT_F4B_CORE_2026-05-13: ✅ LANDED banner with
  PR #67 + main HEAD 7953302 + 24h-watch reference.

Verification (per docs/notes/PLAN_DOCS_HYGIENE_F4B_POST_MERGE_2026-05-13.md
§ 5):
- grep -c '^@mcp\.tool()' tg_parser/mcp_server.py = 43 (verified).
- CLI examples cross-checked vs tg_parser/cli/workspace_cmd.py (8 typer
  commands, --user / --description / --owner-id options).
- workspace_id parameter on exactly 8 scoped read-tools (grep
  'workspace_id: str \\| None' tg_parser/mcp_server.py = 8 hits in
  scoped tools, plus 1 in _resolve_workspace_scope helper).
- Q4 R3 (full-bundle) mentioned in BOTH get_topic_details and
  get_document schemas.
- Q4 R2 (non-atomic move) mentioned in add_workspace_source AND
  remove_workspace_source schemas + USER_GUIDE chapter.
- No new claims about deferred items (Q3 Bot / Q7 F11 / Q8 F6 / O-1)
  being available — only deferred-status mention with cross-link.
- LANDED banner links to PR #67 + main HEAD 7953302.
- No pyproject.toml edits (release-cut decision, separate).
- ruff format / check unaffected (markdown-only).

Out of scope (per START_PROMPT_DOC_HYGIENE_2026-05-XX): M-1..M-16
backlog (broader tools-count + version + ADR drift sprint).
Out of scope (per planning sub-session 2026-05-13): pyproject.toml
version bump (4.2.0 → 4.3.x is a release-cut decision).
Out of scope: ROADMAP_V3 supersede decision (defer to C-3 in hygiene
sprint).

Closes audit findings § 2 «🔴 Critical» (user-facing F4-B drift) +
§ 2 «🟡 Substantive» (LANDED banner + tool-count claims).
```

### Alternative: **2 atomic commits** (если pre-review требует разделения)

- **Commit A — user-facing sync (Cat A):** `USER_GUIDE.md` + `MCP_AGENT_GUIDE.md` + `README.md` + `SERVER_ARCHITECTURE.md` + `ROADMAP_V3_PRODUCTION_FIRST.md`. ~+360 / -28 LOC. Сообщение: `docs(F4-B): user-facing sync to F4-B Core landed in #67`.
- **Commit B — post-merge housekeeping (Cat C):** `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md` LANDED banner. ~+8 / -0 LOC. Сообщение: `docs(F4-B): LANDED banner on sprint prompt`.

**Why split-альтернатива** именно в этом порядке: если PR-reviewer хочет независимо проревьюить «правда ли surface синкнут с кодом» (Cat A — высокий verification bar, требует cross-check с code) vs «банальный banner» (Cat B — low-risk). Split позволяет первый принять conservative reviewer, второй пройти rubber-stamp. **Trade-off:** между two commits репозиторий в incongruent state (banner promises landed feature без synced docs). Single commit избегает этого.

**Recommendation:** single commit, unless explicit reviewer-process reason требует split.

---

## 5. Verification checklist

Каждый чекбокс — выполняется **до** `git add` / commit; провал любого → fix in place, не commit.

### Factual baselines (run once перед началом правок)

- [ ] `grep -c '^@mcp\.tool()' tg_parser/mcp_server.py` → **expected 43**. Use this number in USER_GUIDE L1541 / MCP_AGENT_GUIDE L3 / README L19, L733, L805 / SERVER_ARCHITECTURE L72.
- [ ] `grep -c 'workspace_id: str \| None' tg_parser/mcp_server.py` → **expected ≥9** (8 scoped read-tools + 1 helper `_resolve_workspace_scope`). Filter to scoped read-tools only via `grep -B 3 'workspace_id: str \| None' tg_parser/mcp_server.py | grep '^@mcp.tool()'` — должно вернуть ровно 8 occurrence-в-функциях.
- [ ] `python3 -c "from tg_parser.bot.tools import TOOL_DECLARATIONS; print(len(TOOL_DECLARATIONS))"` → **record actual number**. Use ONLY if Bot count requires update; default per Q3 — **не трогать**.
- [ ] `ls tg_parser/cli/workspace_cmd.py` → exists; `head -40` confirms 8 typer commands (`list`, `create`, `rename`, `delete`, `add-source`, `remove-source`, `list-sources`, `list-all`).

### Per-file content checks

- [ ] **USER_GUIDE Workspaces chapter:** все 8 CLI examples bit-by-bit matchsят `tg_parser/cli/workspace_cmd.py` (signature → flag names → default behavior).
- [ ] **MCP_AGENT_GUIDE Workspaces table:** 8 tools, auth correctly marked (`any` для 7 user tools, `admin` для `list_all_workspaces`).
- [ ] **MCP_AGENT_GUIDE workspace tool schemas:** Pydantic args matchsят `tg_parser/mcp_server.py` L3097-L3379 — `name`, `description?`, `workspace_id`, `new_name`, `channel_id`, `owner_id?` etc.
- [ ] **MCP_AGENT_GUIDE 8 scoped read-tools:** каждая schema (search_knowledge_base / ask_question / list_topics / get_topic_details / list_channels / get_document / get_related_topics / get_cross_channel_stats) имеет `workspace_id: str | null = None` строку в Parameters.
- [ ] **Q4 R3 (full-bundle) note** упоминается в `get_topic_details` schema **И** в `get_document` schema **И** в USER_GUIDE Workspaces chapter.
- [ ] **Q4 R2 (non-atomic move) note** упоминается в `add_workspace_source` schema **И** в `remove_workspace_source` schema **И** в USER_GUIDE Workspaces chapter.
- [ ] **Deferred items (Q3 Bot / Q7 F11 / Q8 F6 / O-1)** упомянуты только как **deferred-status** с cross-link на `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md § Anti-scope`; **никаких claims** что они available.
- [ ] **LANDED banner** в `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md` содержит: `2026-05-13`, `main HEAD 7953302`, `PR #67`, cross-link на `ROADMAP_KARPATHY_LIKE_LIVING_KB.md`.
- [ ] **No `pyproject.toml` edits** — `git diff pyproject.toml` empty.
- [ ] **No `docs/methodology/**` edits** — `git diff docs/methodology/` empty (или папки нет).
- [ ] **No new files outside `docs/`** — `git status --short | grep -v '^.. docs/'` пустой результат (modulo этот plan-файл который уже создан и не коммитится).
- [ ] **Markdown lint clean** — если есть pre-commit hook / lint config, прогнать; иначе manual eyeball на broken links + table syntax.
- [ ] **Cross-links integrity** — все `[...](...)` references resolvable (особенно `MCP_AGENT_GUIDE.md → USER_GUIDE.md`, `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md → ROADMAP_KARPATHY_LIKE_LIVING_KB.md`, etc.).

### Final gate

- [ ] `git diff --stat` показывает ровно файлы из § 2 Cat A + Cat C, **никаких** code/test/contract/methodology файлов.
- [ ] Total diff: ~+370 / -38 LOC (refined from audit's ~+400 / -75); если значительно outside range — re-verify scope creep.

---

## 6. Estimated effort

- **LOC:** ~+370 / -38 (refined from audit's ~+400 / -75 after re-reading actual file sizes + scope shrink на SERVER_ARCHITECTURE / ROADMAP_V3).
- **Files touched:** **6 файлов** (5 Cat A + 1 Cat C). Не 11, как audit предположил.
  1. `docs/USER_GUIDE.md` (+140 / -2)
  2. `docs/MCP_AGENT_GUIDE.md` (+200 / -10)
  3. `README.md` (+10 / -4)
  4. `docs/SERVER_ARCHITECTURE.md` (+5 / -12)
  5. `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` (+5 / -0)
  6. `docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md` (+8 / -0)
- **Session size:** ~0.4 сессии (single-commit path) или **0.5 сессии** total (split-commit path — overhead per-commit message + review).
- **Dependencies:** none beyond чтения `tg_parser/mcp_server.py` (L3097-L3379 для workspace tool schemas, L853-L1290 для scoped read-tools) и `tg_parser/cli/workspace_cmd.py` (для USER_GUIDE CLI examples).
- **Quality bar:** **высший** для MCP_AGENT_GUIDE (AI-агенты читают это как machine-readable contract); **средний** для USER_GUIDE / README; **низкий** для SERVER_ARCHITECTURE / ROADMAP_V3 / sprint-prompt banner.

---

## 7. Sequencing relative to other deliverables

### Strict ordering

- **MUST be after `main 7953302`** — already satisfied (HEAD verified `git log -1 --oneline`).
- **MUST be before `REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md` creation** — DONE marker должен ссылаться на synced user-facing surface, не на half-updated docs. Если DONE marker создаётся раньше — повторно цитирует stale tool counts.

### Recommended ordering

- **Execute this mini-sprint BEFORE drafting `REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md`.** Wave 1 step 2 DONE marker — это closing artifact для feature delivery cycle; он должен closing'аться поверх synced surface.

### Also acceptable

- **Execute AFTER 24h prod-watch GREEN** — позволяет docs reflect'ить «deployed + watched + DONE» state. **Trade-off:** не строго required, т.к. docs reflect *codebase shape*, не *prod status*. 24h watch gating действует для DONE marker, не для docs sync.

### Concurrent / independent

- **M-1..M-16 hygiene sprint** (per [`START_PROMPT_DOC_HYGIENE_2026-05-XX.md`](START_PROMPT_DOC_HYGIENE_2026-05-XX.md)) — может идти **параллельно** этому mini-sprint'у разным агентом. File sets minimal overlap (наш план fix'ит tool counts в USER_GUIDE / MCP_AGENT_GUIDE / README / SERVER_ARCHITECTURE — те же файлы, но **только в F4-B-touched секциях**). Чтобы исключить merge conflict:
  - **Если параллельно:** F4-B post-merge sprint берётся **первым**, M-1..M-16 второй ребейзит и адаптирует свои edits к уже-synced state.
  - **Если последовательно:** F4-B post-merge сначала; M-1..M-16 после — overlap уже solved.

### Out-of-band

- **Decision on `pyproject.toml` version bump** — не блокирует этот sprint; обсуждается в § 8.
- **Decision on `ROADMAP_V3_PRODUCTION_FIRST.md` supersede** — не блокирует; deferred до C-3 в hygiene sprint.

---

## 8. Open questions for user

Эти 4 решения **не блокируют** этот mini-sprint (план содержит default решение для каждого), но user может flip любое:

1. **`pyproject.toml = 4.2.0 → 4.3.x` (или `4.4.0`) bump?** Не входит в этот план. Это release-cut decision (semver — какой incremental tag для F4-B?). Документы уже claim'ят `4.3` (USER_GUIDE / README) или `4.4` (MCP_AGENT_GUIDE header — internal drift). Default: defer до отдельного release-cut sub-session.
2. **Split single commit на Commit A + Commit B?** Default: **single commit** (recommended). Flip → split per § 4 alternative shape.
3. **`ROADMAP_V3_PRODUCTION_FIRST.md` supersede by `ROADMAP_KARPATHY_LIKE_LIVING_KB.md`?** Default: **defer до C-3 в hygiene sprint**, в этом плане только cross-link Wave 1 step 2 landed. Flip → добавить deprecation banner в L1 ROADMAP_V3 в этом же commit.
4. **Execute timing — immediately or after 24h prod-watch GREEN?** Default: **immediately** (docs reflect codebase shape, not prod status). Flip → wait for 24h watch GREEN, чтобы LANDED banner mог cite «watched + DONE» вместо «pending watch».

---

## 9. История промпта

| Дата | Изменение |
|------|-----------|
| 2026-05-13 | Первая версия. Создана planning sub-session ~0.2 сессии после merge F4-B Core (PR #67 → main `7953302`) на основе read-only audit. Re-verified findings: actual MCP tool count = **43** (audit recap говорил 35, ошибка audit'а — устаревший counter); `MCP_AGENT_GUIDE.md` имеет внутренний version drift (header 4.4 / footer 4.3 / file claims 26 tools); `docs/INSTRUCTIONS.md` не существует; `START_PROMPT_DOC_HYGIENE_2026-05-XX.md` существует и описывает M-1..M-16 separate sprint — anti-scope clean. Single-commit path recommended (~0.4 сессии, ~+370/-38 LOC across 6 files); split-commit alternative documented. Anti-scope: M-1..M-16 (отдельный sprint), pyproject bump (release-cut decision), ROADMAP_V3 supersede (defer C-3 в hygiene sprint). Open questions для user: pyproject bump? split? supersede? timing? |
