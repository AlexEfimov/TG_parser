# Handoff — post Wave 1 step 2 (F4-B Core) — 2026-05-15

**Дата:** 2026-05-15 14:24 UTC+4
**Назначение:** контекст для нового агент-окна, продолжающего работу с проектом TG_parser. Использовать как первое сообщение / системный контекст в новом чате.

---

## Текущее состояние main

- **HEAD:** `cbbe116 chore(gitignore): exclude personal Cursor learning notes from project scope (#71)`
- **Working tree:** clean (CURSOR_QUICKSTART_2026.md теперь в `.gitignore`).
- **Branch:** `main`, in sync с `origin/main`.

## Что landed в предыдущей сессии (2026-05-13 → 2026-05-15)

| PR | SHA | Содержание |
|---|---|---|
| #67 | `7953302` | F4-B Core (Workspaces) — 5 atomic commits + 6-й self-review (134 F4-B тестов, ~+4.7k LOC) |
| #68 | `47e1c72` | Post-merge docs sync + pyproject 4.2.0 → 4.3.0 (7 файлов, +357/-29) |
| #69 | `a94b591` | M-1..M-16 docs hygiene — 4 atomic commits C1-C4 (~+257/-89, 12 files) |
| #70 | `5eb036e` | Planning artifact commit `PLAN_DOCS_HYGIENE_F4B_POST_MERGE_2026-05-13.md` (401 LOC) |
| #71 | `cbbe116` | `.gitignore` exclude `CURSOR_QUICKSTART_2026.md` (3 lines) |

## Prod state

- **Prod HEAD:** `7953302` (F4-B Core landed 2026-05-13 19:30 UTC; subsequent docs+gitignore PRs #68-#71 redeploy не требуют).
- **Migration:** `e9f0a1b2c3d5 (head)` — workspaces + workspace_sources tables applied.
- **Containers:** 6 healthy (`tg_parser` / `tg_parser_bot` / `tg_parser_mcp` / `tg_parser_postgres` / `tg_parser_prometheus` / `tg_parser_grafana`).
- **24h watch window:** opened `2026-05-13T19:30:28Z`, expected close `2026-05-14T19:30:28Z` — **истёк ~19h назад на момент handoff'а**. Final verdict GREEN не зафиксирован в DONE marker (см. pending #1).

## Pending очереди

### 1. Wave 1 step 2 DONE marker — IMMEDIATE

**Файл:** `docs/notes/REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` (не существует, создать).

**Template / mirror:** `docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`.

**Workflow:**
1. Подтвердить финальный 24h watch verdict — Prometheus + bot/api/mcp логи за полное окно 2026-05-13 19:30 → 2026-05-14 19:30 UTC. Проверки: `up{service="bot"} = 1`, `confirm_flow_mismatch` 24h = 0, `gemini_*` 24h = 0, `tg_workspace_resolver_seconds` p99 без drift.
2. Создать DONE marker по template C1 из `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md § 4`.
3. **Critical inclusion:** **BUG-013** (`sqlalchemy.exc.IllegalStateChangeError`) как **pre-existing observation surfaced by F4-B watch window** (НЕ F4-B regression — F4-B Core touched `db_context.py` purely additively + zero changes в `scheduler_service.py`). 77% scheduler-tick failure rate. Plus side-issue: **offset-naive datetime `TypeError`** at `scheduler_service.py:89` (~23% ticks).
4. Cross-link в `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — добавить раздел `## 2026-05-XX — Wave 1 step 2 (F4-B Core) DONE ✅`.
5. Сделать через PR (single commit, `docs(milestone): ...`).

**Estimated effort:** ~0.2 session.

**Без этого:** Wave 1 step 2 остаётся "landed но не закрытым".

### 2. BUG-013 fix-sprint — RECOMMENDED NEXT

**Issue:** `sqlalchemy.exc.IllegalStateChangeError` at `services/db_context.py:192` в `proc_session.close()`. Investigation report content:

- **Frequency:** 27 errors / ~35h since `2026-05-13T20:28:37Z` (first occurrence tick #1 post-F4B-deploy). ~77% hourly `incremental_pipeline` ticks fail. Steady, near-deterministic, **not** compounding.
- **Root cause (HIGH confidence):** `run_incremental_for_all_sources` (`scheduler_service.py:61-65`) opens ОДНУ `AsyncSession` pair via `ingestion_and_processing_repos()`, затем `asyncio.gather`-ит `_process_source` over 12 active sources — все closures share same `proc_session` / `state_session`. The `repo_lock` band-aid (`scheduler_service.py:81`) частично serializes `processed_repo` reads, но НЕ covers `state_repo` writes в per-task `finally` block. SQLAlchemy 2.x explicitly forbids sharing `AsyncSession` across asyncio tasks regardless of user-space locking.
- **F4-B relationship:** `git diff 7953302^ 7953302` proves F4-B Core only **added** `workspace_repo()` to `db_context.py` and made **zero** changes к `scheduler_service.py`. Bug is **structurally pre-existing**; deploy дал ему fresh log buffer.
- **User-visible impact:** 0 (data pipeline runs в separate inner sessions и completes до close-time error). Но 77% failure rate делает `scheduler_task_total{success="false"}` метрику бесполезной + "completed" log lines теряются.

**Proposed fix:**
- Move `ingestion_and_processing_repos()` INSIDE каждого `_process_source` task (per-task sessions); drop `repo_lock`.
- ~30 LOC в `tg_parser/services/scheduler_service.py` + 2 new tests.
- Half-day effort.
- Filed as **BUG-013** в `docs/notes/BUG_LOG.md § Active`.

**Plus side-issue (тикетировать рядом):** `scheduler_service.py:89` offset-naive vs offset-aware datetime `TypeError`, ~23% ticks. Скорее всего `datetime.now()` vs `datetime.now(timezone.utc)` confusion в timestamp comparison. Маленький fix.

**Workflow:**
1. Файл BUG-013 + BUG-014 (datetime) в `BUG_LOG.md § Active`.
2. Создать `docs/notes/START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_*.md` planning prompt.
3. Sprint execution: branch → fix → tests → commit → PR → CI → merge → deploy → 24h watch.
4. После 24h GREEN — DONE marker для bug fix (mirror Session G / Session J pattern).

**Pro:** убирает реальный technical-debt, очищает observability baseline до старта Wave 1 step 3.

### 3. Wave 1 step 3 planning — Wave 1 closure path

**Scope:** MCP/API/CLI Surface Parity (per `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md § 5.1`).

**Workflow:**
1. Planning sub-session: re-read `docs/notes/PARITY_DECISION_TRACKING.md § 3` P-1..P-5 + O-1 / O-2 observations.
2. **O-1 verify-action repeat:** atomic `move_workspace_source` — есть ли evidence от F4-B Core period (с 2026-05-13)? Если remove×add ratio ≈ 1:1 с small temporal gap → promote atomic tool. Иначе defer.
3. Текущая гипотеза по `START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md § «После F4-B Core»`: **P-1 (Watchlist HTTP API parity)** или **P-2 (Digest HTTP API parity)**; final choice по signals от dogfooding.
4. Output: новый `docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_*.md` planning artifact.

**Estimated effort:** ~0.3 planning session + ~1-2 execution sessions.

**Audience impact:** unblocks A4 (AI Agent Builder) + A6 (Domain Curator) light-MVP.

### 4. Backlog cleanup (low priority)

- **BUG-009 audit:** упомянуто в PR #69 anti-scope что "also resolved Session G 2026-05-02 но outside explicit M-14 scope (audit names 010/011/012)". Перенести в `BUG_LOG.md § Resolved` отдельным мини-PR (effectively 1 LOC + section move). ~0.05 session.

---

## Рекомендуемый sequence для нового окна

```
DONE marker (#1, ~0.2 session)
  ↓
BUG-013 fix-sprint (#2, ~half-day = ~0.5 session)
  ↓ (после 24h watch на BUG-013 fix GREEN)
Wave 1 step 3 planning (#3, ~0.3 planning + 1-2 execution)
  ↓
[в любой удобный момент] BUG-009 cleanup (#4, ~0.05 session)
```

**Обоснование:** входить в крупный новый scope (Wave 1 step 3) с чистым observability baseline (BUG-013 fixed) лучше, чем тянуть 77% scheduler noise.

---

## Sustained operational lessons (из предыдущей сессии)

| Lesson | Detail |
|---|---|
| **Sandbox SSH DNS** | `git@github.com:...` SSH push hangs (DNS не резолвит). Используй HTTPS override: `git -c url."https://github.com/".insteadOf=git@github.com: <cmd>` |
| **gh keyring "протухает"** | gh CLI auth keyring валиден ~10-30 мин после `gh auth login`. Если `gh pr create` возвращает `Forbidden` — попросить user `gh auth login -h github.com` и retry |
| **Container nomenclature** | На prod: `tg_parser` / `tg_parser_bot` / `tg_parser_mcp` / `tg_parser_postgres` / `tg_parser_prometheus` / `tg_parser_grafana`. НЕ `tg-parser-bot`, НЕ `tg_bot` (Session K § 5.4 sustained lesson) |
| **Prod SSH** | `ssh -p 2296 user@212.72.189.15`, repo at `/home/user/TG_parser` |
| **Migration safety** | F4-B was additive (2 new tables, no `ALTER`). Rollback: `docker compose run --rm tg_parser tg-parser db downgrade --db ingestion --revisions 1 --yes` |
| **Prometheus check pattern** | `ssh prod 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=<metric>" \| python3 -m json.tool'` |
| **Required permissions** | `git_write` недостаточно для git push в SSH-form; `full_network` нужен для gh CLI; `all` (unrestricted) нужен только в крайнем случае |
| **AGENTS.md hard rules** | NO `pyproject.toml` / `requirements.txt` edits без явного запроса. NO `docs/methodology/**` (separate worktree). NO commits без явного запроса |
| **Sandbox `.git/config` warning** | "could not write config file .git/config: Operation not permitted" — cosmetic, не влияет на git operations |

---

## Ключевые cross-links

- **Roadmap:** `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` (living source-of-truth)
- **Audience strategy:** `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md § 5.1` (Wave 1 sequence)
- **Execution plan template:** `docs/notes/PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md § 4` (DONE marker template C1)
- **Parity tracker:** `docs/notes/PARITY_DECISION_TRACKING.md` (P-1..P-5 pre-references + O-1 / O-2 observations)
- **Bug log:** `docs/notes/BUG_LOG.md` (workflow per L1-15; нужно добавить BUG-013, BUG-014; переместить BUG-009 в Resolved)
- **Prior DONE marker (template):** `docs/notes/REVIEW_2026-05-08_WAVE1_STEP1_DONE.md` (~11K, mirror for Wave 1 step 2)
- **F4-B sprint prompt (LANDED):** `docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md` (с LANDED banner от PR #68)
- **F4-B post-merge plan (executed):** `docs/notes/PLAN_DOCS_HYGIENE_F4B_POST_MERGE_2026-05-13.md` (landed PR #70)
- **Docs hygiene sprint prompt (executed):** `docs/notes/START_PROMPT_DOC_HYGIENE_2026-05-XX.md` (landed PR #69)
- **ADRs:** `docs/adr/0001-0006-*.md` (особенно 0006 Karpathy-like Living-KB principles + 0005 ADR mini-refactor)
- **Architecture:** `docs/SERVER_ARCHITECTURE.md` (synced PR #68, tool count 43)
- **MCP catalog:** `docs/MCP_AGENT_GUIDE.md` (8 workspace tools + workspace_id on 8 scoped read tools landed PR #68)

---

## История промпта

| Дата | Изменение |
|------|-----------|
| 2026-05-15 14:24 UTC+4 | Первая версия. Создан в конце agent-сессии 2026-05-13 → 2026-05-15 после landed PRs #67-#71 (Wave 1 step 2 / F4-B Core + post-merge sync + M-cluster hygiene + planning artifact + gitignore). Pending: DONE marker (#1), BUG-013 fix-sprint (#2), Wave 1 step 3 planning (#3). Context window 93% — handoff to new window. |
