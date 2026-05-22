# Handoff — Wave 1 step 3.1 + follow-ups (watch step 3 OPEN) — 2026-05-22

**Дата:** 2026-05-22, конец рабочей сессии (UTC+4).
**Назначение:** контекст для следующего агент-окна. **НЕ** финальный DONE marker для step 3 — тот живёт в [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) и не трогается до закрытия 24h watch (~2026-05-23T11:25:47Z, 14:25 MSK).

---

## Summary

За сессию закрыты **Wave 1 step 3.1** (MCP → HTTP pipeline dispatch, ADR 0007) и follow-ups (idempotency replay shape, `Retry-After`, compose-harness, flaky fix). Оба landed на `main` и развернуты на prod, immediate smoke зелёный по всем трём батареям. 24h watch для **step 3** (PR #89, `a30abd5`) остаётся **OPEN** — отдельная задача step 3.1 watch не открывалась (deploy 3.1 поверх уже идущего watch step 3; step 3.1 идёт под общим зонтом). Step 4 (Shareable Digest, ADR 0008) — планирующая сессия после GREEN verdict.

---

## Delivered (factual)

### Step 3.1 — MCP pipeline dispatch (ADR 0007)

* **PR:** [#90](https://github.com/AlexEfimov/TG_parser/pull/90) → squash `b875faf` (merge `2026-05-22T13:44:48Z`).
* **Scope:**
  * `POST /api/v1/pipeline/trigger` + `pipeline_dispatch_service` (preflight `409 JobAlreadyRunning`, не silent no-op).
  * MCP tools `trigger_pipeline` / `trigger_topicization` / `trigger_link_topics` переведены на HTTP-proxy в `tg_parser`.
  * Bot-команда `/admin trigger ...` — на тот же proxy.
  * `X-API-Key` forwarding end-to-end; Prometheus counter `tg_pipeline_trigger_total{tool,outcome}`.
  * Closes **BUG-015**; **O-3** в `PARITY_DECISION_TRACKING.md` → Closed.
* **Tests:** **2179 / 311 / 0** default, **2477+ / 9 / 0** `TEST_POSTGRES=1`; ruff clean.
* **Prod deploy:** `2026-05-22T14:01:40Z`, prod HEAD → `b875faf`. Immediate smoke — 3/3 MCP tools PASS (логи job-ID видны на `tg_parser`, не на MCP-контейнере — ожидаемо для HTTP-dispatch). `409 JobAlreadyRunning` подтверждён как корректный preflight.

### Follow-ups (PR #91 squash)

* **PR:** [#91](https://github.com/AlexEfimov/TG_parser/pull/91) → squash `d143e5d` (merge `2026-05-22T17:25:41Z`).
* **Scope:**
  * Idempotency replay теперь возвращает `created: false` на повтор того же body (нормализация в middleware вокруг кэша). Закрывает smoke-флаг S3 из [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).
  * `Retry-After: <seconds>` header на 429 rate-limit.
  * Compose-integration harness: `tests/test_compose_pipeline_dispatch_integration.py` + pytest marker `@compose_only` (выключен по умолчанию; в CI отдельным проходом — backlog).
  * Flaky fix: правильное место `store()` в `replay_idempotency_body` + canonical hash test (предотвращает повторение flakiness).
* **Tests:** **2195 / 311 / 0** default, **2499 / 9 / 0** PG; ruff clean.
* **Prod deploy:** `2026-05-22T17:42:42Z`, prod HEAD → `d143e5d`. Immediate smoke:
  * **A** — Watchlist replay → `created: false`; mismatch body → 422; DELETE → 204/404. PASS.
  * **B** — Pipeline trigger replay → тот же `job_id`, `created: false`. PASS.
  * **C** — Rate-limit → 429 c `Retry-After: 12`. PASS.

---

## Open items (carry-forward)

| # | Item | Owner / status |
|---|---|---|
| 1 | **24h watch step 3** — close ~`2026-05-23T11:25:47Z` (14:25 MSK). Tracker: [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md). После закрытия: прогнать Prometheus / log scan по [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md), заполнить verdict в WATCH_WINDOW, финализировать §2–3 и §6 в [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md). | **IMMEDIATE next session** |
| 2 | **Step 4 — Shareable Digest** (ADR 0008). Планирующая сессия (~0.3 session) после GREEN watch step 3: re-read ADR 0008 § Options, `PARITY_DECISION_TRACKING.md § 3`, audience hints A2. | next-after-#1 |
| 3 | **Compose-integration full test in CI** — harness и `@compose_only` уже в дереве; backlog: отдельный PR с CI job (compose up → pytest -m compose_only → tear-down). | backlog |
| 4 | **Stale `uv.lock` local mod** — оставлен нетронутым per AGENTS.md hard rules (`pyproject.toml` / `requirements*.txt` / lockfiles — только по явному запросу). | observed-only |

---

## Pointers / artifacts

| Артефакт | Путь |
|---|---|
| ADR 0007 (Accepted) | [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) |
| ADR 0008 (Draft) — step 4 input | [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) |
| Execution pack 3.1 | [`START_PROMPT_EXECUTION_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_EXECUTION_WAVE1_STEP3_1_2026-05-22.md), [`CHECKLIST_WAVE1_STEP3_1_2026-05-22.md`](CHECKLIST_WAVE1_STEP3_1_2026-05-22.md) |
| Runbook deploy + watch | [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md) |
| Watch tracker (OPEN) | [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) |
| DONE marker (stub, **не трогать до GREEN**) | [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) |
| BUG_LOG | [`BUG_LOG.md`](BUG_LOG.md) — BUG-015 Resolved |
| Parity tracker | [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) — O-3 Closed |
| Compose harness | [`tests/test_compose_pipeline_dispatch_integration.py`](../../tests/test_compose_pipeline_dispatch_integration.py) |

### Prod versions

| When | HEAD | Note |
|---|---|---|
| `2026-05-22T14:01:40Z` | `b875faf` | step 3.1 deploy (PR #90) |
| `2026-05-22T17:42:42Z` | `d143e5d` | follow-ups deploy (PR #91) |

---

## Next session prompt suggestion

> «После ~14:25 MSK 23-05-2026: закрыть 24h watch step 3 — прогнать Prometheus + log scan по [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md), заполнить verdict в [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md), финализировать §2–3 и §6 в [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) (single PR `docs(milestone): wave1 step 3 DONE — 24h watch GREEN`). Затем — планирующая сессия Wave 1 step 4 (Shareable Digest, ADR 0008): re-read ADR 0008 § Options + `PARITY_DECISION_TRACKING.md § 3` + audience hints A2, output → `docs/notes/START_PROMPT_SPRINT_WAVE1_STEP4_*.md`.»
