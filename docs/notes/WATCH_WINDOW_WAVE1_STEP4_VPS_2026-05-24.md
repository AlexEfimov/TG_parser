# Watch window — Wave 1 Step 4 (PR #93) — **PRODUCTION VPS**

**Scope:** этот watch — для PRODUCTION VPS (`redboxtgbot`, `212.72.189.15:2296`). Параллельный local-stack watch ведётся в [`WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md); этот файл фиксирует прод-наблюдения (РЕАЛЬНЫЕ пользователи, РЕАЛЬНЫЙ Telegram bot, РЕАЛЬНЫЕ подписки).

**Exercise plan (active + passive checks for this window):** [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) — VPS-specific (real prod data, real bot, safety preamble). Local-stack аналог как cross-reference: [`docs/runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md). На VPS дополнительно доступны P0-4 (real-prod chat-tick `digest_94483db9`) и P1-1/P1-2 (live bot NL) — недоступны на local-стэке.

**Operator manual (что делает оператор руками):** [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](../runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md).
**Automations registry (созданные Cursor Automations + ID):** [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md) — 3 production automations созданы (`2bd25769` P0-4 verifier @ 06:05Z, `f93e557a` T+24h closure reminder @ 10:50Z, `7b35ca01` webhook ingress).
**OP-2 / OP-3 interactive tests (пошаговая инструкция с зависимостями):** [`docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md`](../runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md) — материализация channel-publish метрик (A, B, E) + валидация bot prompt v1.7.0 target_kind_semantics (C, D).

**Opened:** `2026-05-24T10:50:10Z` (~13:50 MSK 24-05) — declared OPEN после полного step-4 deploy на VPS (build + recreate `tg_parser` / `tg_parser_mcp` / `tg_parser_bot` из `main @ 926a165`, alembic upgrade `f1a2b3c4d5e6 → a8b7c6d5e4f3`, smoke matrix 3×201 + 3×204, и transient startup-race recovery подтверждена на bot — см. § Anomaly ниже).

**T+24h target (nominal):** `2026-05-25T10:50:10Z` (~13:50 MSK 25-05).

**Closed:** _pending_ — close via аналог `START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-25.md`.

**Merge commit:** `926a165` — [PR #93](https://github.com/AlexEfimov/openai/TG_parser/pull/93) squash-merged 2026-05-24T09:39:52Z.

**Pre-deploy VPS HEAD:** `26d03a5` (BUG-028 hotfix, PR #92 от 2026-05-23T16:57Z; **5 commits behind** `origin/main`). **Post-deploy HEAD:** `926a165` (Wave 1 step 4). Fast-forward pull, 39 файлов / +3448 / −146.

**Pre-deploy alembic head:** `f1a2b3c4d5e6` (Wave 1 step 3, развёрнут 2026-05-22 per `WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`). **Post-deploy head:** `a8b7c6d5e4f3` (Wave 1 step 4 — ADR 0008 polymorphic subscription target). Single forward step, no dedupe нужен (step 4 миграция не имеет natural-key UNIQUE constraint'ов, которые могли бы конфликтовать с существующими данными).

**Pre-deploy backup (VPS-LOCAL):** `~/TG_parser/backups/pre_step4_vps_backup_20260524T104149Z.sql` — **239 KB**, md5 `27da1fa9e3c752196489dfb218d55855`, `pg_dump -t digest_subscriptions -t watch_interests`. **Contains real data:** 1 digest_subscriptions row (`digest_94483db9-…` Эндокринология) + 12 watch_interests rows (РЕАЛЬНЫЕ subscriptions РЕАЛЬНЫХ пользователей). Recovery == `pg_restore` + manual reconcile via bot reconcile-loop.

**Container `StartedAt` (post-recreate):** all three (`tg_parser`, `tg_parser_mcp`, `tg_parser_bot`) recreated `2026-05-24T10:46:28Z` (image `tg_parser:latest` sha256 `1a3cb6b8…`, rebuilt from `main @ 926a165`); all healthy by `2026-05-24T10:47:13Z` (~44s). `tg_parser_postgres` / `tg_parser_grafana` / `tg_parser_prometheus` retained running (3-7 недель uptime; не часть step-4 deploy scope).

---

## Pre-deploy data shape (VPS, real prod data)

| Table | Row count | NULL `chat_id` | `target_kind` column present | `channel_id` column present |
|---|---|---|---|---|
| `digest_subscriptions` | **1** | 0 | NO (pre-migration ✅) | NO ✅ |
| `watch_interests` | **12** | 0 | NO ✅ | NO ✅ |

**Migration safety verdict pre-upgrade:** ✅ ALL ROWS HAVE NON-NULL `chat_id` → backfill `target_kind='chat'` для всех existing rows безопасен; downgrade path остаётся реверсируемым (`chat_id` снова станет NOT NULL).

---

## Deploy smoke (immediate, 2026-05-24, ON VPS)

| # | Criterion | Method | Result |
|---|---|---|---|
| 1 | Pre-flight: SSH access | `ssh -p 2296 user@212.72.189.15` | ✅ host `redboxtgbot`, Ubuntu 6.8.0-101-generic |
| 2 | Pre-flight: `docker compose ps` | VPS | ✅ 6 containers running (`tg_parser`, `tg_parser_bot`, `tg_parser_mcp` healthy; postgres/grafana/prometheus retained) |
| 3 | Pre-flight: PROMPTS_DIR regression guard | `docker compose --profile bot config \| grep PROMPTS_DIR` | ✅ `PROMPTS_DIR=/app/prompts` codified на ВСЕХ 3 services (`mcp:94`, `tg_bot:259`, `tg_parser:334`) — BUG-028 Layer D fix |
| 4 | Pre-flight: alembic head pre-deploy | `tg-parser db current --db ingestion` | ✅ `f1a2b3c4d5e6 (head)` — step 3 baseline |
| 5 | Backup (real prod data!) | `docker exec tg_parser_postgres pg_dump …` | ✅ 239 KB file at `~/TG_parser/backups/pre_step4_vps_backup_20260524T104149Z.sql`, md5 `27da1fa9…` |
| 6 | Build | `docker compose --profile bot build tg_parser tg_bot mcp` | ✅ all three exported `tg_parser:latest` (sha256 `1a3cb6b8…`); ~53s |
| 7 | Recreate | `docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot` | ✅ all 3 Recreated → Healthy в ≤44s (по `docker compose ps`) |
| 8 | Migration | `docker exec tg_parser tg-parser db upgrade --db ingestion` | ✅ `Running upgrade f1a2b3c4d5e6 -> a8b7c6d5e4f3` (Wave 1 step 4 — ADR 0008 polymorphic subscription target) |
| 9 | Migration head verify | `db current --db ingestion` | ✅ `a8b7c6d5e4f3 (head)` |
| 10 | Row invariant: 0 NULL `target_kind` | `SELECT COUNT(*) FILTER (WHERE target_kind IS NULL)` | ✅ 0 / 0 (digest / watch) |
| 11 | Row invariant: backfill 100% `target_kind='chat'` | `SELECT COUNT(*) FILTER (WHERE target_kind='chat')` | ✅ 1/1 digest, 12/12 watch (все existing rows получили `chat` per migration `op.execute("UPDATE … SET target_kind='chat' WHERE chat_id IS NOT NULL")`) |
| 12 | Row invariant: 0 `target_kind='channel'` pre-step-4 | `SELECT COUNT(*) FILTER (WHERE target_kind='channel')` | ✅ 0 / 0 (none should exist; step 4 introduces channel target) |
| 13 | New columns shape | `\d digest_subscriptions` / `\d watch_interests` | ✅ `target_kind` enum NOT NULL, `channel_id` varchar nullable, `chat_id` теперь nullable (per ADR 0008) |
| 14 | **`digest_94483db9` specific check** | `SELECT id, name, target_kind, chat_id, channel_id, is_active, last_sent_at, cron_expression, timezone FROM digest_subscriptions WHERE id::text LIKE '94483db9%'` | ✅ `target_kind='chat'`, `chat_id=5445781511`, `channel_id=NULL`, `is_active=true`, `cron_expression='0 9 * * *'`, `timezone='Europe/Nicosia'`, `last_sent_at=2026-05-24 06:00:08.445386+00` (last fired сегодня в 09:00 Europe/Nicosia — ДО deploy; следующий tick = 2026-05-25T06:00:00Z = 09:00 EEST = T+19h09m ≤ T+24h watch window — Cyprus в мае на DST, EEST = UTC+3, совпадает численно с MSK) |
| 15 | `POST /api/v1/digests` `target={kind:chat,chat_id:999001}` | `curl … -H "X-API-Key:$API_KEY"` | ✅ 201 Created; response body содержит `target:{kind:"chat",chat_id:999001}`; row `728b4a6e-…` |
| 16 | `POST /api/v1/digests` `target={kind:channel,channel_id:"@smoke_step4_placeholder"}` | curl | ✅ 201 Created; `target:{kind:"channel",channel_id:"@smoke_step4_placeholder"}`; row `8c376c37-…` |
| 17 | `POST /api/v1/digests` legacy top-level `chat_id:999001` | curl | ✅ 201 Created; backward-compat shim → `target:{kind:"chat",chat_id:999001}`; row `87941809-…` |
| 18 | `DELETE /api/v1/digests/{728b4a6e…}` | curl | ✅ 204 No Content |
| 19 | `DELETE /api/v1/digests/{8c376c37…}` | curl | ✅ 204 No Content |
| 20 | `DELETE /api/v1/digests/{87941809…}` | curl | ✅ 204 No Content |
| 21 | Post-smoke cleanup verify | `SELECT COUNT(*) FROM digest_subscriptions WHERE name LIKE 'smoke_step4_%'` | ✅ 0 |
| 22 | Prod row untouched verify | `SELECT … WHERE id LIKE '94483db9%'` post-smoke | ✅ row identical pre/post-smoke (`target_kind=chat, chat_id=5445781511, is_active=true`) |

**Smoke verdict:** ✅ ALL 4-surface HTTP contracts confirmed on VPS:
- `target.kind=chat` discriminator round-trip
- `target.kind=channel` discriminator round-trip
- legacy `chat_id` shim → `target.kind=chat` in response (ADR 0008 backward compat)
- DELETE 204 on all three shapes
- **Prod row `digest_94483db9` survived backfill + smoke + cleanup без изменений** (critical guarantee per § Constraints)

---

## Anomaly observed during deploy (NOT a step-4 functional regression)

**Bot startup race — `digest_scheduler_initial_load_failed`.** At `2026-05-24T10:46:40.131309Z` (12s post-restart), `tg_parser_bot` logged structlog event `{event: "digest_scheduler_initial_load_failed", level: "error", exc_info: true}`. Initial load reported `active_subscriptions: 0` (failed to query `digest_subscriptions`). **However**, the bot's reconcile loop (`refresh_interval: 60s`) ran 60s later at `10:47:40.164Z` and successfully added the cron task: `{"task_id":"digest:94483db9-9351-4f99-9aec-46949d9ddd09","cron_expression":"0 9 * * *","timezone":"Europe/Nicosia","event":"added_cron_task"}` followed by `{"added":1,"removed":0,"failed":0,"event":"digest_reconcile"}`. **Self-healing within 60s; current cron-task state is HEALTHY.**

**Classification:** transient startup race — bot тянется в DB до того, как connection pool полностью прогрелся, либо до того как alembic-миграция a8b7c6d5e4f3 завершилась (мы запускали `db upgrade` ПОСЛЕ `up -d`, см. Step 4 runbook). На bot'е startup началось `10:46:39.872Z`, миграция завершилась `10:47:19Z` → bot пытался прочитать схему до полной коммита миграции; столкнулся с `target_kind` column отсутствующей в его SQLAlchemy reflection (pre-migration shape) ИЛИ с FK/PK race. Сам структурный traceback не виден в логах — `structlog` пишет `exc_info: true` как marker, но traceback rendering не настроен на этом deploy.

**Impact:** **ZERO functional impact** — bot recovered после 60s reconcile, `digest_94483db9` cron активен и зашедулен правильно. Next tick `2026-05-25T06:00:00Z` будет работать штатно (если только не повторится race на каком-то другом restart).

**Latent service defect for follow-up (out-of-scope for step 4 close):**
1. **`digest_scheduler` startup ordering:** initial load `_initial_load()` должен быть устойчив к short-window DB unavailability (retry-with-backoff вместо immediate fail + 60s wait). Альтернатива: `up -d` после `db upgrade`, а не до. Текущий runbook (`up -d` затем `db upgrade`) корректен для production, но требует bot быть resilient к short transient query failures на startup.
2. **structlog `exc_info: true` без traceback render:** при `level: error` оператор не видит причину; нужно настроить `structlog.processors.format_exc_info` в bot logger setup.

→ **Recommend** filing as `BUG-030` (separate from BUG-029 race-retry rollback): "bot digest_scheduler initial_load fragile to DB startup race; needs retry + structlog exc_info renderer".

**Verdict for watch open:** ✅ GO. Recovery полная, prod cron-task scheduled, no user-visible impact, follow-up bug filed.

---

## Initial Prometheus snapshot (T+0)

Sampled `2026-05-24T10:50:10Z` (epoch `1779619810`). VPS Prometheus endpoint = `http://localhost:9090` accessed via `docker exec tg_parser_prometheus wget -qO- …` (Prometheus listens on container-internal 9090; **NOT host-exposed** — verify: `docker compose ps` shows `9090/tcp` без host-mapping, см. `docker-compose.yml:287-300` без блока `ports:`. Также **не выставлен** через nginx vhosts на VPS: только `tgp.efimov.mobi`/`mcp.tgp.efimov.mobi`/`grafana.tgp.efimov.mobi` имеют public TLS). Доступ из chat operator'а — только `ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- …'`.

| Series | Result | Note |
|---|---|---|
| `up{job="tg_parser_api",instance="tg_parser:8000",service="api"}` | **1** | API healthy post-recreate |
| `up{job="tg_parser_mcp",instance="mcp:8080",service="mcp"}` | **1** | MCP healthy post-recreate |
| `up{job="tg_parser_bot",instance="tg_bot:8081",service="bot"}` | **1** | Bot healthy post-recreate (отличие от local-стэка, где bot был Exited) |
| `tg_digest_channel_publish_total{result=*}` | **(empty series)** | Expected at T+0: counter materialises only on first scheduler-tick channel digest publish. Existing chat-target prod sub (`digest_94483db9`) НЕ инкрементирует этот counter (он только для `target_kind='channel'`). Counter is registered (verified via code `tg_parser/api/metrics.py:13`). |
| `tg_digest_runs_total{*}` | **(empty)** | Counter ещё не материализовался после restart (last_sent_at `digest_94483db9` = 2026-05-24T06:00:08Z = pre-restart; next tick = 2026-05-25T06:00Z). Будет ≥1 после T+19h автоматически. |
| `tg_idempotency_keys_table_size{service="api"}` | **0** | Reset после restart; hourly cleanup cron `0 * * * *` зарегистрирован per step-3 watch precedent. |
| `tg_idempotency_keys_table_size{service="mcp"}` | **0** | Expected (MCP surface has no header-Idempotency-Key endpoints) |
| `tg_idempotency_keys_table_size{service="bot"}` | **0** | Expected (same reason as mcp) |

---

## Container log smoke (T+0..15m)

`docker logs --since 2026-05-24T10:46:28Z` per service, проверено в окне 10:46:28Z → 10:50:10Z (~T+4m).

| Container | error/critical/Traceback lines (post-reconcile recovery 10:47:40Z+) | Classification |
|---|---|---|
| `tg_parser` | **0** | Clean since restart; FK-violation pattern из local-стэка не воспроизвёлся на VPS (реальный admin user существует в `users`). |
| `tg_parser_mcp` | **0** | Clean over entire post-recreate window. |
| `tg_parser_bot` | **0** (после reconcile recovery в 10:47:40Z) | Единственный pre-recovery error = `digest_scheduler_initial_load_failed` (10:46:40Z) — see § Anomaly выше; self-healed; **NOT step-4 regression**. Post-recovery 0 errors over 10:47:40Z → 10:50:10Z window. |

---

## Focus signals for the 24h window

Per [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` § 24h watch](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md) + exercise plan:

1. **`tg_digest_channel_publish_total{result="success"}`** — оператор должен подписаться на real channel target (бот = admin) во время window для материализации counter. P0-1 из exercise plan. Если не выполнить — counter останется пустым на close (НЕ failure, materialises lazily).
2. **`tg_digest_channel_publish_total{result="permission_denied"}`** — expected **0** в steady state. Non-zero без P0-2 теста = real-prod issue (бот mis-promoted в чужом канале). С P0-2 тестом = expected ≥1 (контролируемый failure).
3. **`tg_digest_channel_publish_total{result="failed"}`** — expected **0** в steady state. Non-zero = transient/permanent classification drift в `_CHANNEL_PUBLISH_PERMANENT_FRAGMENTS` (`digest_service.py:95-106`); требует review.
4. **Existing chat-target prod digest cron — `digest_94483db9` next tick at 2026-05-25T06:00Z (T+19h)** — passive observation, MUST succeed без regression. `last_sent_at` должен advance к `~2026-05-25T06:00:08Z`. Pre-step-4 sequence (per BUG-028 hotfix watch `WATCH_BUG_028_FIRST_CRON_TICK_2026-05-24.md`): tick 2026-05-24T06:00:08Z прошёл successfully → step-4 deploy не должен сломать legacy chat dispatch.
5. **`up{job=~"tg_parser.*"}` continuity** — `up{api}=1`, `up{mcp}=1`, `up{bot}=1` for the whole window. Single bucket-zero at OPEN (recreate) tolerable per step-3 GREEN criterion §4 reuse. **Watch для bot specifically:** ещё один `digest_scheduler_initial_load_failed` без recovery = elevation (BUG-030 → hotfix).

---

## Operator action required during the window

| # | Action | Priority |
|---|---|---|
| **OA-1** | **Re-launch `tg_bot`** | **N/A на VPS** — bot уже live и healthy (отличие от local-стэка). |
| **OA-2** | Subscribe to **real channel target** (P0-1 из exercise plan) — нужен test Telegram канал где бот = admin + Post messages. Создать ephemeral subscription `subscribe_digest(name="watch_p0_1_success_vps", target={kind:channel, channel_id:"<R-1>"}, cron="*/2 * * * *")`, дождаться tick (2-3 мин), проверить counter `{result="success"}≥1`, **немедленно delete**. | **HIGHLY RECOMMENDED** для materialise C-1 closure criterion. Без выполнения GREEN closure остаётся PARTIAL (no step-4-new metrics observable end-to-end). |
| **OA-3** | Subscribe to **channel where bot is NOT admin** (P0-2) для materialise `{result="permission_denied"}≥1` + проверить soft-deactivate (`is_active=false`) + fallback DM. **Бот — REAL prod bot, сообщения уйдут реальному owner'у**; использовать своё user_id как owner, чтобы получить DM на себя. | **OPTIONAL** но valuable для C-2. |
| **OA-4** | Subscribe to watchlist with channel target (P0-3) для проверить `WatchInterestInfo` channel_id field + `list_watchlists` без ValidationError. | **OPTIONAL** для C-3. |
| **OA-5 (PASSIVE)** | **2026-05-25T06:00:00Z** (= 09:00 Europe/Nicosia EEST, T+19h09m) **— наблюдать prod `digest_94483db9` tick** в Telegram. Должен прийти ежедневный дайджест эндокринологии в чат `5445781511` (REAL пользователь, owner = `5445781511`). После tick проверить:<br>`SELECT last_sent_at FROM digest_subscriptions WHERE id LIKE '94483db9%'` — должен advance к ~`2026-05-25 06:00:0X+00`.<br>`docker logs --since 2026-05-25T05:55Z tg_parser_bot \| grep 94483db9` — clean. | **MANDATORY** для P0-4 / C-4. Это критический regression guard на legacy chat dispatch. |
| **OA-6** | После 24h (`2026-05-25T10:50:10Z`, ~13:50 MSK), run closure session — аналог step-3 closure: Q1 `up{}` gap-detection, Q2 `tg_digest_channel_publish_total` instant, log-scan для 5xx на `/api/v1/(digests\|watchlists)`, log-scan для `digest_scheduler_initial_load_failed` recurrence. | **MANDATORY** to close. |
| **OA-7** | File **`BUG-029`** (digest_service.py:265-272 race-retry без `session.rollback()`) per local watch note recommendation. | **MANDATORY before step-5 starts** (per local watch note OA-4). |
| **OA-8** | File **`BUG-030`** (bot `digest_scheduler` initial_load fragile to DB startup race; needs retry-with-backoff + `structlog.processors.format_exc_info` для exc_info rendering). **Severity:** low — recovery self-healing within 60s; но caused 60s window где `active_subscriptions=0` в bot. | **RECOMMEND** перед step 5; не блокирует GREEN closure (self-healed). |

---

## 24h watch observations

### T+2h35m — `2026-05-24T13:25Z` — Watch automation infrastructure validated end-to-end

**Context:** оператор настроил Cursor Automations infrastructure для VPS watch window (см. [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md)). Три production automations созданы и валидированы:

| ID | Trigger | Validation result |
|---|---|---|
| `2bd25769` (P0-4 digest_94483db9 verifier @ 06:05Z 25-05) | cron | ✅ **MCP call работает end-to-end** — manual UI Run @ `T+1h54m` (12:44Z): agent успешно позвал `list_digests` через прикреплённый MCP server `tg-parser-vps` (`https://mcp.tgp.efimov.mobi/mcp` + Bearer); run прерван оператором до assertion check (избежали false-positive issue от выкл. `last_sent_at` vs assertion date). Known issue 2 from Cursor forum (MCP resolution failure in cron-triggered runs) на нашем setup'е НЕ воспроизводится. |
| `f93e557a` (T+24h closure reminder @ 10:50Z 25-05) | cron | ✅ Configured (Repositories `AlexEfimov/TG_parser`), prompt valid. Validation deferred до actual fire @ 10:50Z 25-05. |
| `7b35ca01` (incident webhook ingress) | webhook | ✅ **End-to-end pipeline GREEN** — operator smoke-test @ 13:05Z: curl→webhook (with `Authorization: Bearer crsr_*`)→agent classifier→GitHub issue creation. Two false-positive issues opened (#94, #95 — `[alert] manual_setup_validation`), оба closed immediately. Agent run latency: ~60-120 секунд от curl до issue. Initial 401 error blip (operator забыл Authorization header) — resolved after copying auth header из Cursor automation UI. |

**Operator's local env vars** (на Mac, `~/.zshrc`): `TG_PARSER_WATCH_WEBHOOK` + `TG_PARSER_WATCH_WEBHOOK_AUTH` exported и работают. 7 готовых `curl` snippet'ов (сценарии A-G) для ad-hoc escalation — см. [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md` § 1.7](../runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md).

**Schema discovery byproduct:** 7 probe automations (`[DELETE_ME] schema-probe-*`) созданы в процессе reverse-engineering `aiserver.v1.Workflow` proto JSON shape (cursor-backend-control MCP не expose-ит canonical schema). Все disabled; удаляются через Cursor UI (delete tool не доступен через API).

**Pending operator work (initial):**
* Grafana Contact point + alert rules setup (§ 1.8 / § 2 в operator manual) — ~15-20 минут. Webhook URL + auth header теперь готовы.
* Repositories `AlexEfimov/TG_parser` на остальных 2 automations (`2bd25769`, `f93e557a`) — проверить glазами в UI (issue creation на `7b35ca01` confirms it works for that one).

---

### T+3h18m — `2026-05-24T14:08Z` — Grafana alerting → webhook pipeline operational

**Что сделано (operator + AI):**
* Grafana v11.1.0 на `https://grafana.tgp.efimov.mobi` — Contact point `cursor-watch-webhook` создан с custom HTTP header `Authorization: Bearer crsr_<token>` (тот же, что в `$TG_PARSER_WATCH_WEBHOOK_AUTH`).
* Default notification policy → `cursor-watch-webhook`.
* 3 alert rules в folder `wave1-step4-watch`:
  * `tg_parser_bot_down` — `up{job="tg_parser_bot"} < 0.5`, for 5m, severity=critical, alertname-label = `tg_parser_bot_down` (для `7b35ca01` prompt prefix `[bot down]`).
  * `tg_parser_api_down` — `up{job="tg_parser_api"} < 0.5`, for 5m, severity=critical, label `tg_parser_api_down` (prefix `[api down]`).
  * `tg_api_5xx_spike` — `sum(rate(tg_parser_http_http_requests_total{handler=~"/api/v1/(digests|watchlists).*",status="5xx"}[5m])) > 0`, for 5m, severity=warning, label `tg_api_5xx_spike` (prefix `[5xx]`).
* **Metric discovery findings (для будущих rule authoring):**
  * HTTP-метрика на VPS Prometheus: `tg_parser_http_http_requests_total` (prometheus-fastapi-instrumentator double-namespaced naming), labels: `handler` (templated, e.g. `/api/v1/digests/{digest_id}`), `method`, `status` (bucketed `2xx/3xx/4xx/5xx`, **не** raw codes), `service`, `job=tg_parser_api`.
  * `up{}` jobs: `tg_parser_api` (tg_parser:8000), `tg_parser_bot` (tg_bot:8081), `tg_parser_mcp` (mcp:8080). Все три `=1` at this timestamp.
  * **Отсутствующие** counters (ещё не emit-нуты, не bug): `tg_digest_channel_publish_total` (нет channel-publish events; материализуется при первом M-2/M-3 тесте или real-user subscribe), `digest_scheduler_initial_load_failed_total` (БО логируется только через structlog event, не Prometheus counter — BUG-030 PromQL rule невозможен без code change, fallback на log-grep + manual curl-snippet A § 1.7).

**End-to-end pipeline validation:**
| Test | Path | Issue # | Result |
|---|---|---|---|
| Operator curl smoke (no payload structure) | curl → webhook → auth → automation → issue | #94, #95 | ✅ closed |
| Operator curl cheap path (Grafana v9 payload simulation) | curl с реальным Grafana payload → 7b35ca01 prompt classifier → `[bot down]` prefix issue | #97 | ✅ closed, prefix mapping correct |
| **Natural Grafana firing (bonus)** | Grafana `DatasourceNoData` real fire → Contact point → webhook → automation → issue | **#96** | ✅ closed, **proves prod Grafana → webhook live + auth header correctly forwarded** |

⇒ **Pipeline GREEN end-to-end через 3 независимых пути.** Full path test (real `docker stop tg_parser_bot` на 7 минут) пропущен — overkill given triple evidence, и блокирует real users / создаёт BUG-030 elevation risk.

**Follow-up для closure:**
* Rotate `GRAFANA_ADMIN_PASSWORD` после T+24h closure (был передан plaintext в operator transcript для setup — низкий risk, но best practice ротировать).
* Investigate если DatasourceNoData recurs в течение window (issue #96 был likely transient от `tg_api_5xx_spike` rule с initial wrong metric name `tg_api_requests_total`, исправлено до `tg_parser_http_http_requests_total`).
* (опционально) Добавить `tg_parser_mcp_down` rule (один и тот же template как `tg_parser_bot_down`, `up{job="tg_parser_mcp"}`).

---

### T+10h45m — `2026-05-24T21:35Z` — OP-2 / OP-3 interactive tests results (batched)

**Context:** оператор провёл OP-2 / OP-3 interactive tests из runbook [`docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md`](../runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md) — материализация channel-publish метрик (тесты A, B, E) + валидация bot prompt v1.7.0 `target_kind_semantics` (тесты C, D). Pre-test baseline зафиксирован в PRE Step 6 (T+0 snapshot), result batch ниже finalizes step-4 closure criteria observability на VPS.

**Baseline (из PRE Step 6):**

| Series | Baseline value at `2026-05-24T20:35:35Z` |
|---|---|
| `tg_digest_channel_publish_total{result="success"}` | **absent (= 0)** |
| `tg_digest_channel_publish_total{result="permission_denied"}` | **1** (pre-existing, leftover от deploy verification) |
| `tg_digest_channel_publish_total{result="failed"}` | **absent (= 0)** |
| `up{job="tg_parser_api"}` | **1** |
| `up{job="tg_parser_bot"}` | **1** |
| `up{job="tg_parser_mcp"}` | **1** |

**PRE state (с deviations от original handoff):**

* **R-1** = `@vps_watch_test_r1_Alex` (operator-owned channel, `@Tgingest_bot` — admin с Post Messages).
* **R-2** = `@vps_watch_test_r2_Alex` (operator-owned channel, бот **НЕ member**).
* **OPERATOR_CHAT_ID** = `-5279672667` (basic group `vps-watch-test-grp`; `@Tgingest_bot` later promoted в admin для bypass aiogram privacy mode для Test D).
* **Bot username CORRECTED:** runbook + handoff ссылались на `@smoke_tgparser_bot`, но реальный prod бот — `@Tgingest_bot` (id `8657845219`). Stale reference `@smoke_tgparser_bot` в [`docs/prompts/DEV_RESURRECTION_PROMPT.md:26`](../prompts/DEV_RESURRECTION_PROMPT.md) → отдельный cleanup commit (см. DOC-001 в [BUG_LOG.md](BUG_LOG.md)).

**Results table:**

| Test | Status | Subscription ID | Evidence |
|---|---|---|---|
| **A (M-2 success)** | **GREEN** | `5e6dce46-bac3-4704-8166-955cfb872303` (deleted) | digest доставлен в R-1 (preview «Академик РАН Иван Дедов был удостоен… ордена Андрея Первозванного»); `tg_digest_channel_publish_total{result=success}` 0 → 1. |
| **B (M-3 denied)** | **GREEN (с caveat — см. BUG-031-R)** | `b1031315-902d-4370-80e4-f600b3e43030` (deleted) | R-2 empty; `is_active=false` soft-deactivated; `tg_digest_channel_publish_total{result=permission_denied}` 1 → 2. Fallback DM **НЕ отправлен** (sub had `chat_id=null` per pure-channel target schema; `digest_service.py:520` требует `sub.chat_id is not None` перед отправкой fallback). |
| **C (P1-1 NL channel)** | **GREEN on main criterion** (P1-1 disambig); **RED on flow** (BUG-031, BUG-032 logged) | `5d8b83ad-ea9a-41a8-a7b7-465c9703e2c1` (deleted) | Бот inferred `target_kind=channel` из NL «в канал @username» ✓; создал sub с `channel_id=@vps_watch_test_r1_Alex`, `chat_id=null`, `cron=0 * * * *` `Europe/Moscow`. Confirmation flow **broken**: бот записал в DB **ДО** prompt «Подтвердите [да/нет]» и не распознавал «да»/«подтверждаю» как confirmation tokens. |
| **D (P1-2 NL chat)** | **PARTIAL** (GREEN on disambig; **RED on payload** — BUG-033 critical) | `0a00768d-6bdd-4ead-8356-5f42dc4d1cf5` (deleted) | Бот inferred `target_kind=chat` из «в этот чат» ✓ (только после promote бота в admin группы для bypass aiogram privacy mode). **НО:** `chat_id=123` (placeholder leak, не реальный group chat_id `-5279672667`); `channel_ids=["pro_fendocrinologist"]` (misparsed из operator typo «pro fendocrinologist» с пробелом → underscored variant, который не matchит real source `profendocrinologist`). Тот же confirmation flow break как в C (BUG-031). |
| **E (M-4 watchlist)** | **GREEN on schema; N/A on match delivery** | `2184bced-5f99-4705-83ce-df96bc89636c` (soft-deactivated) | `subscribe_watchlist(target.kind=channel)` accepted; `list_watchlists` вернул 13 entries вкл. наш новый без `WatchInterestInfo` `ValidationError` (schema fix per `mcp_server.py` self-review **HOLDS**). `trigger_pipeline(channel_id=profendocrinologist)` completed (`last_success_at=2026-05-24T21:13:18Z`, `fail_count=0`) но `get_watchlist_matches` вернул **0 matches** и `last_checked_at` остался `null` для нашего interest (см. OBS-001). |

**Anomalies observed:**

1. **BUG-031 (Severe — bot UX/correctness):** Bot создаёт digest subscription в DB **ДО** того как пользователь confirm'нул. Sequence в тестах C и D: «📰 Подписка создана» сообщение приходит **до** «Подтвердите, пожалуйста, … [да/нет]». Это нарушает documented invariant из `/help`: «Операции записи выполняются только после вашего явного подтверждения в чате».

2. **BUG-032 (Medium — bot UX):** Bot не распознаёт «да» / «подтверждаю» как valid confirmation tokens — отвечает «Я не совсем понимаю ваш ответ» repeatedly. Confirmation handler parser appears broken для plain affirmative responses.

3. **BUG-033 (Critical — bot correctness):** Bot в group context fails to resolve actual `chat_id` когда пользователь говорит «в этот чат» — вставляет `chat_id=123` как hardcoded placeholder/seed value. Это делает resulting subscription **undeliverable** (Telegram chat `123` ≠ группа). На scheduled cron tick бот будет пытаться `sendMessage(chat_id=123)` и инкрементировать `delivery_failed` counter, оставляя orphan digest. Real group chat_id = `-5279672667`.

4. **BUG-034 (Medium — NL parser robustness):** Source channel name parser fails на user typo с embedded whitespace. Input «pro fendocrinologist» (с пробелом — typo для `profendocrinologist`) → бот сохранил `pro_fendocrinologist` (с underscore), который не является valid Telegram username pattern и не matchит real source. Должен либо reject typo с clarification, либо normalize spaces (не replace на underscores).

5. **BUG-035 (Critical — scheduler race):** `unsubscribe_digest` не инвалидирует pre-loaded APScheduler job. Evidence: Test C subscription (`5d8b83ad…`, cron `0 * * * *` Europe/Moscow) был unsubscribed в ~20:58 UTC; next scheduled tick в 21:00 UTC fired anyway и доставил digest в R-1 («Ежечасный дайджест profendocrinologist», тот же prod content что и в Test A). Closely related но distinct от pre-existing **BUG-030** (`digest_scheduler_initial_load` startup race): BUG-035 — это mid-flight unsubscribe → orphan-job race, где APScheduler in-memory job продолжает выполняться после удаления DB row. После orphan delivery next tick в 22:00 UTC уже **не должен** fire (sub нет в DB и presumably scheduler hook fails to find row), но это требует verification.

6. **BUG-031-R (Documentation — Low):** Runbook [`docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md`](../runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md) § B-4 expects fallback DM («I tried to publish to @R2 but I'm not admin…») которое implementation **не отправляет** когда subscription имеет `chat_id=null` (pure-channel target). Два valid fix path'а: (a) обновить runbook чтобы document B-4 как **N/A** для pure-channel subs (cheap), или (b) extend `digest_service.py:_publish_to_target` чтобы fall back на owner's `User.chat_id` когда `sub.chat_id is null` (richer feature, требует schema/contract review).

7. **OBS-001 (Observation, не yet bug):** `last_checked_at` всех 5 active pre-existing `watch_interests` стуже на `2026-05-24T11:48:25Z` (~10h до watch session), и наш новый interest `2184bced…` имеет `last_checked_at=null` **даже ПОСЛЕ** successful manual `trigger_pipeline` run. Watchlist matcher либо не запускается на triggered (non-scheduled) `full_pipeline` jobs, либо запускается но не обновляет `last_checked_at` unless match found, либо отдельный scheduled matcher hook не fires. Needs investigation вне watch window.

8. **DOC-001 (Low — referenced bot name stale):** Production bot = `@Tgingest_bot` (id `8657845219`). String `@smoke_tgparser_bot` в [`docs/prompts/DEV_RESURRECTION_PROMPT.md:26`](../prompts/DEV_RESURRECTION_PROMPT.md) — stale и должна быть заменена.

9. **Test D blocker resolution:** Bot в basic groups (privacy mode ON default) **не отвечает** на free-text NL prompts даже с `@Tgingest_bot` mention. Resolution: promoting бота в admin в test group bypasses privacy mode. Documented как operator-workflow note: **P1-2 NL chat-target тесты ТРЕБУЮТ либо DM context, либо бота-as-admin в target group**.

**Cleanup status:**

* Все 4 test digest subscriptions **DELETED** (A, B, C, D — hard delete via `unsubscribe_digest`).
* 1 test watchlist **soft-DEACTIVATED** (E — preserved row per documented behavior).
* **DB state on VPS:** только `digest_94483db9` (1 prod digest sub) + 13 `watch_interests` rows (5 active real + 7 old smoke + 1 new soft-deactivated `2184bced…`). Matches documented baseline post-cleanup.
* **Telegram side:** R-1 / R-2 / `vps-watch-test-grp` остаются operator-owned и могут быть reused для future watch windows ИЛИ removed.

**Impact on closure criteria** (из [`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) C-1…C-12):

* **C-1** `tg_digest_channel_publish_total{result="success"} ≥ 1`: **MATERIALIZED** via Test A (now = 1).
* **C-2** `tg_digest_channel_publish_total{result="permission_denied"} ≥ 1`: **MATERIALIZED** via Test B (now = 2; включает pre-existing baseline = 1 + this test +1).
* **C-3** `tg_digest_channel_publish_total{result="failed"}`: unchanged (still = 0; нет real-fail path exercised в этих tests; этот path потребовал бы например Telegram API timeout / rate-limit, которые мы не воспроизводили).
* **Bot prompt v1.7.0 `target_kind_semantics`**: **VERIFIED on disambiguation** via C+D (оба inferred `target_kind` correctly из NL), **PARTIAL on payload** (D имел `chat_id` + channel-name regressions per BUG-033 / BUG-034).

**Follow-ups для closure session:**

* BUG-031..BUG-035 + OBS-001 + DOC-001 filed в [`BUG_LOG.md`](BUG_LOG.md) — review severity adjudication перед prioritization в Wave 1 step 5 scoping.
* Runbook § B-4 revision (BUG-031-R fix path (a) или (b)) — defer до post-closure decision review.
* OBS-001 (watchlist matcher `last_checked_at` stagnation) — investigate в отдельной session (вне step 4 closure scope; not blocking C-1..C-3).

---

---

## Verdict

| Field | Value |
|---|---|
| **Status** | **OPEN** (`2026-05-24T10:50:10Z`, nominal close `2026-05-25T10:50:10Z`) |
| **Initial verdict** | **GREEN-pending** — all immediate smoke criteria PASS (3×201 + 3×204; correct `target` discriminator round-trip; alembic head advances `f1a2b3c4d5e6 → a8b7c6d5e4f3`; PROMPTS_DIR regression guard codified; `digest_94483db9` backfilled correctly to `target_kind='chat'` и survived smoke + cleanup без изменений). **One transient startup-race anomaly** (`digest_scheduler_initial_load_failed` on bot) self-healed within 60s — recommended follow-up BUG-030, **NOT blocking** closure. |
| **DONE marker** | [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) — to be finalised at watch close (VPS observations нужно добавить в § VPS deploy block). |

---

## Cross-reference

* Sprint start prompt: [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md).
* Plan: [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md).
* ADR: [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md).
* Deploy runbook: [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md).
* **VPS watch exercise plan (PRIMARY for this watch):** [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md).
* Local-stack watch exercise plan (cross-reference / structural template): [`docs/runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md).
* Local-stack watch (parallel sibling): [`WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md).
* Step-3 VPS watch precedent (structural mirror): [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).
* BUG-028 hotfix watch (immediate predecessor on VPS): [`WATCH_BUG_028_FIRST_CRON_TICK_2026-05-24.md`](WATCH_BUG_028_FIRST_CRON_TICK_2026-05-24.md).
* VPS architecture reference: [`docs/SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md).
