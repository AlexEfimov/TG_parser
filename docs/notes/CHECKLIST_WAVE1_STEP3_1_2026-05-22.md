# Чеклист — Wave 1 step 3.1 (MCP↔scheduler dispatch, ADR 0007)

> Зеркало DoD из [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md).
> Отмечать по ходу execution-сессии. Один PR, 2–3 атомарных коммита.

**Статус планирования:** `84f63ff` на `origin/main` (2026-05-22).

---

## 0. Pre-flight (блокер старта кода)

- [ ] `git fetch && git checkout main && git pull --ff-only` → HEAD ≥ `84f63ff`
- [ ] `.venv/bin/pytest -q` → **≥2175 passed, 0 failed** (default)
- [ ] `TEST_POSTGRES=1 .venv/bin/pytest -q` → **≥2477 passed, 0 failed** (если трогаем ingestion/API)
- [ ] `ruff format --check . && ruff check .` — clean
- [ ] Ветка: `fix/wave1-step3-1-mcp-dispatch-2026-05-22` от `origin/main`
- [ ] **Не трогать:** `pyproject.toml`, `requirements*.txt`, `uv.lock`, `docs/methodology/**`
- [ ] Wave 1 step 3 Phase C / 24h watch **OPEN** — не блокирует этот спринт

**Оператор до commit 2 (пока HTTP dispatch нет):**

- [ ] Не доверять MCP `trigger_pipeline` → `{triggered: true}` (BUG-015)
- [ ] Workaround: `docker compose exec tg_parser tg-parser ingest --source <id>` на VPS
- [ ] Runbook: [`mcp_testing/2026-05-15_claude_session/04-operational-runbook.md`](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md) § 1, § 5

---

## 1. Phase A — commit 1/3 (Option A safety)

- [ ] `tg_parser/mcp_server.py` `trigger_pipeline`: при недоступном dispatch → `triggered=false`, `error_class=DispatchNotImplemented`, `workaround` с SSH-командой
- [ ] `tg_parser/bot/tools.py` `_exec_trigger_pipeline`: то же поведение (не врать об успехе)
- [ ] Удалить/загейтить мёртвый in-process `_run_pipeline_background` в MCP **не в commit 1** (полное удаление — commit 2/3 с HTTP)
- [ ] USER_GUIDE + MCP_AGENT_GUIDE: однострочное предупреждение оператору (до commit 2)
- [ ] Тесты: регрессия — mock-пути не возвращают `{triggered: true}` без dispatch
- [ ] `pytest` + `ruff` green после commit 1

---

## 2. Phase B — commit 2/3 (Option B HTTP API)

### 2.1 Контракт API (locked ADR 0007)

- [ ] `POST /api/v1/pipeline/trigger` на `tg_parser` (FastAPI)
- [ ] Body: `{ "channel_id", "job": "full_pipeline"|"topicization"|"link_topics", "force": false }`
- [ ] Response: `{ "job_id", "created", "status": "queued" }`
- [ ] `created: true` — первый enqueue; replay `Idempotency-Key` + тот же body → тот же `job_id`, `created: false`
- [ ] Auth: forward `X-API-Key` (RBAC как у step 3); cross-tenant → 403
- [ ] Rate limit → 429 + `Retry-After`
- [ ] Telethon re-auth → typed error + SSH runbook (не MCP `code_callback`)
- [ ] Prometheus: `tg_pipeline_trigger_total{job,result,surface}`

### 2.2 Wiring

- [ ] Scheduler принимает one-shot job в процессе `tg_parser`
- [ ] `get_pipeline_status` — минимальное расширение только если нужен `job` discriminator
- [ ] `tests/test_api_pipeline_trigger.py` — auth, enum, 403, rate limit, idempotency optional
- [ ] Убрать предупреждение из USER_GUIDE / MCP_AGENT_GUIDE (dispatch live)
- [ ] `pytest` + `ruff` green после commit 2

---

## 3. Phase B tail — commit 3/3 (MCP/Bot proxy + closure docs)

- [ ] MCP: `httpx` POST `http://tg_parser:8000/api/v1/pipeline/trigger`; forward `X-API-Key`; **нет** dual in-process path
- [ ] **ENH-1:** MCP tool `trigger_topicization` → `job=topicization`
- [ ] **ENH-2:** MCP tool `trigger_link_topics` → `job=link_topics`
- [ ] Bot `trigger_pipeline` → тот же HTTP proxy
- [ ] `tests/test_mcp_pipeline_dispatch.py` — unit mock httpx + при возможности compose integration
- [ ] Integration: MCP trigger → log `Starting ingestion` на **`tg_parser`** ≤60s (не `tg_parser_mcp`)
- [ ] `docs/notes/BUG_LOG.md` BUG-015 → **resolved** + PR SHA
- [ ] `docs/notes/PARITY_DECISION_TRACKING.md` § O-3 → closed в step 3.1 row
- [ ] Регрессия: `test_api_watchlists`, `test_f11*` без изменений поведения

---

## 4. Quality bar (перед PR)

- [ ] Default pytest: **≥2175 passed, 0 failed**
- [ ] `ruff format --check . && ruff check .`
- [ ] ~20–30 новых тестов (оценка спринта); 0 регрессий на F4/F11/F6 suites
- [ ] Karpathy P7: MCP не врёт об успехе без verified dispatch (ADR 0006)
- [ ] **Git:** commit/push/PR — **только по явному запросу пользователя** ([`AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) §8)

---

## 5. Acceptance / DoD (закрытие спринта)

- [ ] MCP `trigger_pipeline` после deploy → ingestion log на `tg_parser` ≤60s
- [ ] `trigger_topicization` / `trigger_link_topics` существуют, тот же async contract
- [ ] BUG-015 resolved в BUG_LOG
- [ ] O-3 closed в PARITY_DECISION_TRACKING
- [ ] Optional prod smoke: один MCP trigger через Cursor MCP post-deploy

---

## 6. Anti-scope (STOP если потянуло)

| Запрещено | Куда отложено |
|---|---|
| Redis / NATS queue | F8-B / Wave 4 |
| Postgres LISTEN/NOTIFY | deferred |
| gRPC Unix socket | rejected |
| Channels CRUD API (P1) | future parity |
| BUG-013/14 scheduler fixes | unless dispatch wiring only |
| ADR 0008 polymorphic targets | Wave 1 step 4 |
| Shareable digest | step 4 |

---

## 7. После merge (вне этого PR, по запросу пользователя)

- [ ] Deploy + optional 24h watch (не блокер step 3.1)
- [ ] Следующий шаг: Wave 1 step 4 (Shareable Digest, ADR 0008)

---

## Ссылки

| Документ | Назначение |
|---|---|
| [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) | Accepted contract |
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) § BUG-015 | Blocker |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | Quality lifecycle, no auto-commit |
