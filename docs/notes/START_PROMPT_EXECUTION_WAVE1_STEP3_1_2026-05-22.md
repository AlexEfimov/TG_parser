# EXECUTION — Wave 1 step 3.1 (MCP↔scheduler dispatch)

> **Открой этот файл в новом Cursor-чате** (fresh context). Workspace:
> `/Users/alexanderefimov/TG_parser`.

---

## Что читать

| Файл | Роль |
|---|---|
| **Этот файл** | Entrypoint: pre-flight, ветка, порядок коммитов, git-правила |
| [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md) | Полный scope, locked Q1–Q5, anti-scope |
| [`CHECKLIST_WAVE1_STEP3_1_2026-05-22.md`](CHECKLIST_WAVE1_STEP3_1_2026-05-22.md) | Пошаговый чеклист / DoD |
| [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) | Binding ADR (Accepted) |
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) § BUG-015 | Blocker + workaround до deploy |

---

## Параметры сессии

| Поле | Значение |
|---|---|
| **Тип** | Code execution (не planning) |
| **Wave / step** | Wave 1 — **3.1** |
| **Closes** | BUG-015, ENH-1, ENH-2, O-3 |
| **Branch** | `fix/wave1-step3-1-mcp-dispatch-2026-05-22` |
| **Base** | `origin/main` @ ≥ `84f63ff` |
| **PR shape** | Single PR, **3 atomic commits** (см. ниже) |

---

## Opener (вставь агенту первым сообщением)

```
Wave 1 step 3.1 execution — MCP↔scheduler dispatch per ADR 0007.

Follow in order:
1. docs/notes/START_PROMPT_EXECUTION_WAVE1_STEP3_1_2026-05-22.md (this file)
2. docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md
3. docs/notes/CHECKLIST_WAVE1_STEP3_1_2026-05-22.md

Branch: fix/wave1-step3-1-mcp-dispatch-2026-05-22 from origin/main (HEAD ≥ 84f63ff).
Run pre-flight before any code. Implement Phase A → B in 3 commits per sprint §4.
Do NOT git commit or push unless I explicitly ask. When I ask for PR — one PR, CI green.

Operator note until HTTP dispatch lands: do not trust MCP trigger_pipeline success;
workaround is docker compose exec tg_parser tg-parser ingest --source <id>.
```

---

## Pre-flight (обязательно до кода)

```bash
cd /Users/alexanderefimov/TG_parser
git fetch origin
git checkout main
git pull --ff-only origin main
git rev-parse HEAD   # ≥ 84f63ff

.venv/bin/pytest -q 2>&1 | tail -3
# expect: 2175+ passed, 0 failed

ruff format --check . && ruff check .

git checkout -b fix/wave1-step3-1-mcp-dispatch-2026-05-22 origin/main
```

**Не редактировать:** `pyproject.toml`, `requirements*.txt`, `uv.lock`, `docs/methodology/**`.

**Phase C (step 3 deploy/watch):** если 24h watch ещё OPEN — **не ждать** закрытия для кода 3.1.

---

## Порядок коммитов (3/N)

| # | Scope | Ключевые файлы |
|---|---|---|
| **1/3** | Phase A — honest `DispatchNotImplemented` + docs warning | `tg_parser/mcp_server.py`, `tg_parser/bot/tools.py`, USER_GUIDE, MCP_AGENT_GUIDE |
| **2/3** | `POST /api/v1/pipeline/trigger` + scheduler + metrics + API tests | `tg_parser/api/`, scheduler wiring, `tests/test_api_pipeline_trigger.py`; **снять** docs warning |
| **3/3** | MCP ENH-1/2 + httpx proxy + bot proxy + BUG_LOG/PARITY closure | `mcp_server.py`, `tests/test_mcp_pipeline_dispatch.py`, BUG_LOG, PARITY |

После каждого коммита: `pytest` relevant subset + `ruff`.

---

## Locked API contract (не менять без ADR amend)

```
POST /api/v1/pipeline/trigger
Body:  { channel_id, job: full_pipeline|topicization|link_topics, force: false }
Resp:  { job_id, created, status: "queued" }
```

- `created: true` — первый enqueue
- Replay `Idempotency-Key` + same body → same `job_id`, `created: false`
- MCP/Bot: `httpx` → `http://tg_parser:8000`, forward caller `X-API-Key`
- Internal URL on Docker network only

---

## Git / PR правила

- **Не делать `git commit`, `git push`, `gh pr create` без явного запроса пользователя**
  ([`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) §8, workspace `AGENTS.md`).
- Когда пользователь просит PR: один PR, 3 коммита, CI 5/5 green, описание с BUG-015/ENH-1/ENH-2/O-3.
- Deploy/smoke — только по запросу пользователя после merge.

---

## DoD (кратко)

См. [`CHECKLIST_WAVE1_STEP3_1_2026-05-22.md`](CHECKLIST_WAVE1_STEP3_1_2026-05-22.md) §5:

1. MCP `trigger_pipeline` → реальная работа на `tg_parser` ≤60s post-deploy
2. `trigger_topicization` / `trigger_link_topics` MCP tools
3. BUG-015 + O-3 docs closed
4. `2175+ / 0 failed` pytest; ruff clean

---

## История

| Дата | Событие |
|------|---------|
| 2026-05-22 | Execution entrypoint created post-planning push `84f63ff`. |
