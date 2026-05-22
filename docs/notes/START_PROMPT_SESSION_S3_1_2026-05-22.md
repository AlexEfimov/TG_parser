# Старт сессии S3.1 — post-merge Phase C + Wave 1 step 3.1 planning prep

> **Создан:** 2026-05-22 (S3 closing handoff). Этот промпт открывает следующую сессию (S3.1) после Wave 1 step 3 sprint completion + merge PR #89.

## Workspace state (verify FIRST)

- **Path:** `/Users/alexanderefimov/TG_parser`
- **Branch:** `main` = `a30abd5` (Wave 1 step 3 merged via PR #89 on 2026-05-22T10:38:12Z UTC)
- **Pre-merge HEAD:** `2d48609` (post PR #86/87/88, pre-S3)
- **Merge commit:** `a30abd5` "Merge pull request #89 from AlexEfimov/feat/wave1-step3-foundation"
- **4 atomic S3 commits preserved on main** (visible via `git log` без `--first-parent`):
  - `56e65e2` — 1/4 ENH-9 + BUG-022 foundation
  - `6efb20b` — 2/4 P-1 Watchlist HTTP API
  - `0e450eb` — 3/4 P-2 Digest HTTP API
  - `5b828cf` — 4/4 Idempotency-Key middleware + cleanup + docs
- **Working tree:** clean (только `uv.lock` остаётся modified-unstaged per forbidden-paths)
- **Pytest baseline** (на `a30abd5` main HEAD; identical to pre-merge `5b828cf` content т.к. fast-forward merge):
  - Default: `2175 passed / 311 skipped / 0 failed`
  - `TEST_POSTGRES=1`: `2477 passed / 9 skipped / 0 failed`
  - **ВЕРИФИЦИРОВАТЬ перед любой работой** через `.venv/bin/pytest -q | tail -3` — если расхождение, STOP.
- **Ruff:** clean repo-wide (328 files)
- **CI на merge:** 5/5 green (Test Python 3.12, Lint Documentation, Alembic Guardrails, Alembic Runtime Upgrade Smoke (testcontainers), Docker Build)

## Workflow rules (НОРМАТИВНО)

- **AGENTS.md, docs/quality/AGENT_PLAYBOOK.md** — обязательны
- **НИКАКОГО `git commit` / `push` / `merge` без явного запроса пользователя**
- **НЕ трогать** (forbidden hard): `pyproject.toml`, `requirements*.txt`, `uv.lock`, `docs/methodology/**`
- **Methodology workspace отдельный:** если задача касается `docs/methodology/**` / методологии / agent-contracts / templates — переключиться в `/Users/alexanderefimov/TG_parser-methodology` (branch: `methodology`). НЕ предлагать правки `docs/methodology/**` из текущего workspace.
- **Untracked notes** (`HANDOFF_*`, `WATCH_WINDOW_*`, `mcp_testing/`) — не коммитить
- **S2 paths** (untouched в S3 — orthogonal): `tg_parser/processing/topicization.py`, `tg_parser/services/topicization_service.py`, `tg_parser/services/pipeline_service.py`, `tg_parser/cli/app.py` — не трогать без явной необходимости + signal'а

## Открытые workstreams

### Workstream 1 — S3 Phase C (post-deploy, closes S3 fully)

1. **Deploy main `a30abd5` на production VPS:**
   - Mechanism TBD — investigation:
     - Проверить `docs/runbooks/` на existing deploy runbook
     - Reference: `docs/notes/REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` (F4-B Core deploy precedent — как был выполнен)
   - Likely shape (на основе precedent): `ssh prod 'cd /opt/tg_parser && git pull && docker compose pull && docker compose up -d'` + `alembic upgrade head` (либо via service entrypoint)
   - Pre-deploy: убедиться что `docker compose ps` на prod healthy
   - Self-defensive migration aborts если duplicates существуют → admin runbook `docs/runbooks/wave1_step3_idempotency_dedupe.md`

2. **24h post-deploy watch** (per sprint prompt §6):
   - `tg_idempotency_keys_hit_total{result=hit|miss|mismatch}` — mismatch ~0 в normal traffic
   - `tg_watchlist_subscribe_total{result=created|updated|nochange}` — emit на subscribe paths
   - `tg_digest_subscribe_total{result}` — same для digests
   - `tg_idempotency_keys_table_size` (gauge) — verify hourly cleanup эффективность
   - HTTP `tg_api_requests_total{status=5xx}` на `/api/v1/watchlists` / `/api/v1/digests` — must be 0
   - Existing F11 (`tg_watchlist_score`) / F6 (`tg_digest_runs_total`) — no regression

3. **Production curl smoke** (per sprint prompt §6 acceptance criteria 1-5):
   - `POST /api/v1/watchlists` с valid `X-API-Key` → 201 + `{watchlist_id, created: true, changed_fields: []}`
   - Replay same body + `Idempotency-Key: foo` → cached response (`created: false`, no duplicate row)
   - Same key + different body → 422 `IdempotencyKeyMismatch`
   - `POST /api/v1/digests` с invalid cron → 422 `InvalidCron`
   - `DELETE /api/v1/digests/{id}` → 204; replay → 404 (HARD DELETE asymmetry vs watchlist soft)
   - `workspace_id=<foreign>` → 404 `WorkspaceNotFound`
   - Verify через DB: row создан с `workspace_id` FK; на subsequent `delete_workspace` → `workspace_id IS NULL` (ON DELETE SET NULL)
   - Prometheus `tg_idempotency_keys_hit_total{result=hit}` increments на cached response

4. **Update DONE marker** `docs/notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`:
   - §2 acceptance signals table — fill watch verdicts (each row 1-6)
   - §3 post-watch state — replace TBD с per-endpoint health
   - §5 cross-refs — add merge commit SHA `a30abd5` + PR #89 URL
   - §6 lessons learned — replace TBD
   - §7 Wave 1 step 4 readiness — verify

### Workstream 2 — Wave 1 step 3.1 planning sub-session

Per sprint prompt §10 — следующий шаг audience-driven roadmap.

**Scope:** ADR 0007 (MCP↔scheduler dispatch) ratify + close:

- **BUG-015** (MCP `trigger_pipeline` silent no-op — `docs/notes/BUG_LOG.md` § BUG-015)
- **ENH-1** (`trigger_topicization` MCP tool)
- **ENH-2** (`trigger_link_topics` MCP tool)
- **O-3 parity** (MCP write-tool asymmetry — `docs/notes/PARITY_DECISION_TRACKING.md` § 3 O-3)

**ADR 0007 status:** Draft (`docs/adr/0007-mcp-scheduler-dispatch.md`); options matrix готов (A: pre-ADR safety patch, B: HTTP API endpoint, C: LISTEN/NOTIFY, D: queue, E: gRPC). Preliminary rec = A + B layered.

**Pattern:** sprint planning sub-session (~0.5 chat) → execution sub-session — mirror S1→S2→S3 cadence.

### Workstream 3 — Wave 1 step 4 (shareable digest via TG-channel)

Per sprint prompt §10 (после step 3.1). Extension F6: `subscribe_digest(... publish_to_channel="@my_digest")`. Builds on ADR 0008 polymorphic target lane (channel publish vs chat send). Не блокирует step 3.1.

### Workstream 4 — Wave 1.5 Operational Dogfooding

Параллельно (per sprint prompt §10): daily TG_parser usage + light A4 external validation через новый HTTP API surface. Не требует sprint session — opportunistic feedback collection.

## Reference docs (tracked)

### Sprint context (S3)

- `docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md` — S3 sprint prompt (CLOSED, не править)
- `docs/notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md` — DONE marker (STUB; нужно finalize after watch)
- `docs/runbooks/wave1_step3_idempotency_dedupe.md` — admin runbook (NEW в S3)

### ADRs

- `docs/adr/0009-idempotency.md` — **Accepted 2026-05-22**
- `docs/adr/0008-subscription-target-model.md` — **Draft** (chat_id-only used in S3; polymorphic deferred Wave 1 step 4 + Wave 2A)
- `docs/adr/0007-mcp-scheduler-dispatch.md` — **Draft** (PRIMARY input для S3.1 ratify)
- `docs/adr/0006-karpathy-like-living-kb-principles.md` — 7-checklist (always-mandatory)

### Tracking + audit

- `docs/notes/BUG_LOG.md` — backbone для future fix-сессий (S3.1 будет туда писать BUG-015/ENH-1/ENH-2/O-3 closure)
- `docs/notes/PARITY_DECISION_TRACKING.md` — § 1 (P-1/P-2 closed in S3) + § 3 (O-3 still open; closes в S3.1)
- `CHANGELOG.md` — `[Unreleased]` entry с S3 changes (требует release-version flip при tag creation)

### Strategy

- `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 — Wave 1 sequence
- `docs/notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` — full parity inventory (P-1/P-2 done; A-1..A-13 CLI gap open)

### Quality + workflow

- `AGENTS.md` (workspace root) — workspace boundary rules
- `docs/quality/AGENT_PLAYBOOK.md` — quality lifecycle
- `docs/notes/agents-roles.md` — базовые роли

## Recommended starting action

Выбрать (или предложить другое):

1. **Phase C work first** — closes S3 fully: deploy → curl smoke → 24h watch → DONE marker finalize. Производственно-ориентированно. Не требует нового planning.
2. **Step 3.1 planning sub-session** — sprint prompt draft + ADR 0007 ratify. Architecturally-oriented. Можно стартовать параллельно с Phase C watch (24h занимает реальное время, не blocking compute).
3. **Step 3.1 + Phase C in parallel** — planning sub-session + watch window обе async-friendly.
4. **Pause / другое** (уточню при возобновлении).

## История parent sessions

- **S1 (planning, 2026-05-21):** sprint prompt + ADR drafts 0007/0008/0009 → [PR #86](https://github.com/AlexEfimov/TG_parser/pull/86) (SHA `d7a18f9`)
- **S2 (quick-wins, 2026-05-21):** BUG-017/018/023 closed → [PR #87](https://github.com/AlexEfimov/TG_parser/pull/87) (SHA `2e9213c`)
- **Pre-flight sync (2026-05-21):** baseline docs → [PR #88](https://github.com/AlexEfimov/TG_parser/pull/88) (SHA `2d48609`)
- **S3 (execution, 2026-05-21 → 2026-05-22):** 4 atomic commits → [PR #89](https://github.com/AlexEfimov/TG_parser/pull/89) (merged 2026-05-22T10:38:12Z UTC; merge commit `a30abd5`)
- **S3.1 — NEW SESSION** (this prompt opens it)

## Note on session mode

S3 проходила в **Multitask Mode** (background subagent delegation). S3.1 может быть в любом mode. Если хочешь Multitask Mode — engage его explicit'но в начале сессии; otherwise foreground работа default.
