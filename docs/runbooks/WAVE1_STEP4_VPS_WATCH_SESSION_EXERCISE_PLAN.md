# Runbook — Wave 1 Step 4 VPS Watch Session Exercise Plan

**Last reviewed:** 2026-05-24 (immediately после VPS step-4 deploy, watch open T+0=`2026-05-24T10:50:10Z`).

**Scope:** этот runbook — для **PRODUCTION VPS** (`redboxtgbot`, `212.72.189.15:2296`). Параллельный local-stack runbook: [`WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md) — используется как структурный шаблон, но **НЕ применять команды оттуда на VPS** без адаптации под реальную прод-среду.

**Назначение:** structured exercise plan для VPS watch window после деплоя ADR 0008. **Главное отличие от local plan:** реальный prod bot LIVE, реальные пользователи, реальная подписка `digest_94483db9`. P0-4 (legacy chat regression) выполняется **passive** — на real prod data.

**Связанные документы:**
* **Watch note (где фиксируются наблюдения):** [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)
* **Operator manual (действия руками):** [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md)
* **Automations registry (созданные Cursor Automations с ID):** [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md)
* Deploy runbook: [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](WAVE1_STEP4_DEPLOY_AND_WATCH.md)
* Local-stack exercise plan (cross-reference): [`docs/runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md)
* Step-3 VPS watch precedent: [`docs/notes/WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](../notes/WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md)
* ADR 0008 (OQ#3 channel-publish best-effort): [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md)
* Cursor Automations docs: [cursor.com/docs/cloud-agent/automations](https://cursor.com/docs/cloud-agent/automations)

---

## 0. SAFETY preamble — PRODUCTION CONSTRAINTS

> ⚠️ **Это production**. Реальные пользователи, реальный bot отправляет реальные сообщения, реальные подписки получают cron-tick'и. Любое нарушение правил ниже = инцидент.

### Hard rules

| # | Правило | Почему |
|---|---|---|
| S-1 | **НЕ удалять и не модифицировать `digest_94483db9`** (id `94483db9-9351-4f99-9aec-46949d9ddd09`, name «Эндокринология», owner `5445781511`) — НИ через MCP, НИ через SQL, НИ через HTTP API. Только passive observation. | Это real prod подписка real user'а с дневным cron `0 9 * * * Europe/Nicosia`. P0-4 = passive regression guard. |
| S-2 | **НЕ использовать `chat_id=5445781511`** (или любой другой реальный user_id из `users`/`watch_interests`) для test subscriptions. Использовать только **свой** Telegram chat_id оператора. | Real user получит спам/test-сообщения в свой Telegram. |
| S-3 | **НЕ subscribe на real user's owned channels** — только operator-owned test channels R-1 / R-2. | Real owner не давал согласия на test publish. |
| S-4 | **Все test subscriptions name-prefix `vps_watch_*`**, ВСЕ создаются с `cron_expression='*/2 * * * *'` (быстрый tick для observation) и **немедленно удаляются** после verify. | Cleanup discovery + safe blast radius. |
| S-5 | **Test channels R-1 / R-2 должны быть operator-owned**. R-2 (где бот НЕ admin) — НЕ выбирать real third-party channel; создать свой test channel и НЕ добавлять бота. | Permission_denied path должен быть detectable и предсказуемый. |
| S-6 | **НЕ запускать `tg-parser db downgrade`** без явного operator authorization + restore plan из backup `~/TG_parser/backups/pre_step4_vps_backup_20260524T104149Z.sql`. | Real prod data на кону. |
| S-7 | **Все MCP-вызовы оператора через свой user_id** (auth через `mcp.tgp.efimov.mobi` с personal API key) — НЕ admin-impersonate если admin-уровень не нужен. | Aud-trail в `users` / `audit_log`. |

### Soft rules

* После каждого P0/P1 action — записать timestamp + result в watch note секцию «24h watch observations» (создать при первом наблюдении).
* При любом непредсказуемом результате — STOP, документировать в watch note, не пытаться workaround.
* `digest_94483db9` next tick = `2026-05-25T06:00:00Z` (`Europe/Nicosia` EEST = UTC+3, 09:00 local), это T+19h09m, **в окне**. Не пытаться force-trigger.

---

## 1. Pre-requisites (operator-side)

| # | Ресурс | Зачем | Verify |
|---|---|---|---|
| R-1 | **Operator-owned тестовый Telegram-канал, где бот = admin + Post messages** | P0-1, P0-3 success path | `@username_test1` или `-100…`; бот добавлен через Channel Settings → Administrators |
| R-2 | **Operator-owned тестовый канал, где бот НЕ добавлен или не имеет post-прав** | P0-2 permission_denied path (гарантированный controlled failure) | `@username_test2`; бот заведомо НЕ член |
| R-3 | **DM-канал operator ↔ prod bot** | Fallback notification verification после soft-deactivate | Отправить `/start` боту в свой private chat — если ответил, DM работает |
| R-4 | **SSH access на VPS** | P2 monitoring (Prometheus только через `docker exec`) | `ssh -p 2296 user@212.72.189.15 'whoami'` → `user` |
| R-5 | **API_KEY для prod HTTP** | P1-3 (HTTP mutual-exclusion test), общий HTTP smoke | `ssh ... 'docker compose exec -T tg_parser python3 -c "import json,os; print(next(iter(json.loads(os.environ[\"API_KEYS\"]).keys())))"'` |
| R-6 | **MCP-клиент с подключённым `https://mcp.tgp.efimov.mobi`** | P0/P1 MCP actions; public TLS endpoint! | `subscribe_digest(name="ping", channel_ids=[], chat_id=0)` → expect validation error «channel_ids must be non-empty» (= MCP жив и отвечает) |
| R-7 | **Telegram chat operator'а с prod bot для NL** | P1-1, P1-2 — тест prompt v1.7.0 `target_kind_semantics` | Bot отвечает на `/help` |
| R-8 | **Свой `chat_id` оператора** (НЕ `5445781511`!) | Создание test subscriptions без affecting real users | Узнать через `@userinfobot` или из bot logs после `/start` |

### Discovery commands

```bash
# Endpoint sanity
ssh -p 2296 user@212.72.189.15 'docker compose ps'
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- http://localhost:9090/-/healthy'

# API_KEY extraction
API_KEY=$(ssh -p 2296 user@212.72.189.15 'docker compose exec -T tg_parser python3 -c "import json,os; print(next(iter(json.loads(os.environ[\"API_KEYS\"]).keys())))"')

# Operator's chat_id (replace 5445781511 if you, the operator, are NOT that user)
OPERATOR_CHAT_ID=<your_telegram_id>
```

---

## 2. P0 чеклист (mandatory для GREEN closure)

### P0-1 — Success path (operator-owned channel где бот admin)

**Цель:** материализовать `tg_digest_channel_publish_total{result="success"}` ≥ 1 на real prod stack.

| Шаг | Команда / действие | Ожидание |
|---|---|---|
| 1.1 | Назначить бота admin в R-1 с Post messages permission | Telegram UI |
| 1.2 | MCP (через `mcp.tgp.efimov.mobi`): `subscribe_digest(name="vps_watch_p0_1_success", channel_ids=["profendocrinologist"], target={"kind":"channel","channel_id":"<R-1>"}, cron_expression="*/2 * * * *", timezone="UTC", format="summary", language="ru")` | `success=true`, response.subscription.target.kind="channel" |
| 1.3 | Подождать 2-3 минуты | scheduler fires `_digest_job_id(subscription.id)` |
| 1.4 | Проверка R-1 канала | Дайджест опубликован ботом |
| 1.5 | `ssh user@VPS 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total{result=\"success\"}"'` | value ≥ 1 |
| 1.6 | **Cleanup IMMEDIATELY:** `unsubscribe_digest(subscription_id="<id из 1.2>")` | success=true |
| 1.7 | `ssh ... 'docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "SELECT COUNT(*) FROM digest_subscriptions WHERE name LIKE '"'"'vps_watch_p0_1%'"'"';"'` | 0 (cleanup verify) |

**Recovery если 1.4 не дал сообщения но `{result="failed"}` инкрементилась:** read `ssh ... 'docker logs --since 5m tg_parser'`, classify exception — если permanent → permission misconfig в R-1, повторить 1.1.

### P0-2 — Permission denied path (controlled failure на R-2)

**Цель:** материализовать `{result="permission_denied"}` ≥ 1; проверить **soft-deactivate**, лог `channel_publish_permission_denied`, fallback DM в operator chat (R-3).

| Шаг | Команда / действие | Ожидание |
|---|---|---|
| 2.1 | Убедиться: бот НЕ член R-2 | проверить в Channel Settings R-2 |
| 2.2 | MCP: `subscribe_digest(name="vps_watch_p0_2_denied", channel_ids=["profendocrinologist"], target={"kind":"channel","channel_id":"<R-2>"}, cron_expression="*/2 * * * *", chat_id=<OPERATOR_CHAT_ID>)` | success=true (note: `chat_id` здесь — owner's chat для fallback DM; конфликта target/chat_id нет потому что target.kind=channel и chat_id используется как owner contact только для fallback) |
| 2.3 | Подождать 2-3 минуты | scheduler tick |
| 2.4 | `ssh ... 'docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "SELECT id, is_active, target_kind, channel_id, chat_id FROM digest_subscriptions WHERE name='"'"'vps_watch_p0_2_denied'"'"';"'` | `is_active=false` ✅ |
| 2.5 | `ssh ... 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total{result=\"permission_denied\"}"'` | value ≥ 1 ✅ |
| 2.6 | `ssh ... 'docker logs --since 5m tg_parser \| grep channel_publish_permission_denied'` | ≥ 1 structured event ✅ |
| 2.7 | Проверить Telegram DM от бота в R-3 | Сообщение типа «Подписка vps_watch_p0_2_denied деактивирована: бот не админ в \<R-2\>» ✅ |
| 2.8 | **Cleanup:** `unsubscribe_digest(subscription_id="<id>")` | success=true |

**Permanent error fragments** (из `tg_parser/services/digest_service.py:95-106`, для контекста): `chat not found`, `bot was blocked`, `user is deactivated`, `forbidden`, `not enough rights`, `need administrator`, `have no rights`, `bot is not a member`, `channel_private`, `administrator`.

### P0-3 — Watchlist channel target (parallel surface)

**Цель:** покрыть watchlist surface; проверить fix `WatchInterestInfo` (channel_id field + chat_id Optional, см. commit 3 PR #93).

| Шаг | Команда / действие | Ожидание |
|---|---|---|
| 3.1 | MCP: `subscribe_watchlist(title="vps_watch_p0_3", channel_ids=["profendocrinologist"], target={"kind":"channel","channel_id":"<R-1>"}, keywords=["тест","сахар"], threshold=0.05)` | success=true, interest.target.kind="channel" |
| 3.2 | Дождаться natural incremental tick (~15-30 минут на prod канале с активным потоком) ИЛИ MCP `trigger_pipeline(channel_id="profendocrinologist", force=true)` затем ждать ~60s | Новый ProcessedDocument scored против interest |
| 3.3 | Если есть match — push в R-1 | Match-уведомление в R-1 |
| 3.4 | MCP: `list_watchlists()` | Response **без ValidationError**; interest содержит `channel_id="<R-1>"`, `target_kind="channel"`, `chat_id=null` |
| 3.5 | **Cleanup:** `unsubscribe_watchlist(interest_id="<id>")` | success=true |

> Если step 3.4 поднимает `pydantic.ValidationError` — **CRITICAL**, регрессия `WatchInterestInfo` fix'а. STOP, escalate как hotfix immediately.

### P0-4 — Legacy chat-path passive regression (REAL PROD)

**Цель:** убедиться что новый dispatch `_publish_to_target(kind="chat")` не сломал legacy chat-таргет на REAL prod `digest_94483db9`.

| Шаг | Действие | Ожидание | Когда |
|---|---|---|---|
| 4.1 | **PASSIVE** — дождаться `2026-05-25T06:00:00Z` (= 09:00 Europe/Nicosia EEST = ~09:00 MSK) | Cron tick для `digest_94483db9` | T+19h09m, в окне |
| 4.2 | Real user `5445781511` получает дайджест в Telegram | Verify через user / DB | T+19h10m |
| 4.3 | `ssh ... 'docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "SELECT last_sent_at FROM digest_subscriptions WHERE id::text LIKE '"'"'94483db9%'"'"';"'` | `last_sent_at` advance к ~`2026-05-25 06:00:0X+00` | T+19h10m |
| 4.4 | `ssh ... 'docker logs --since 2026-05-25T05:55Z tg_parser_bot \| grep 94483db9'` | Clean run, no exceptions | T+19h10m |
| 4.5 | `ssh ... 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total"'` | НЕ инкрементировано для chat-target (метрика только для channel) | T+19h10m |
| 4.6 | `ssh ... 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_runs_total"'` | ≥ 1 для chat-runs (общая метрика digest runs) | T+19h10m |

> **Critical:** если P0-4 failed (no message, no last_sent_at advance, или exceptions в логах) — это блокирующая регрессия `_publish_to_target` chat dispatch. STOP closure, escalate hotfix, rollback considerable.

---

## 3. P1 чеклист (high-value gap closure)

| ID | Действие | Команда | Валидирует |
|---|---|---|---|
| P1-1 | Bot NL via Telegram chat operator'а → real prod bot: «Подпиши меня на ежедневный дайджест канала @profendocrinologist, доставка в @MyTestChannel» (`MyTestChannel` = R-1) | Live Telegram message | `target_kind_semantics` prompt v1.7.0 → LLM резолвит в `target={kind:"channel", channel_id:"@MyTestChannel"}` |
| P1-2 | Bot NL: «Подпиши меня на дайджест канала @profendocrinologist» (без target spec) | Live Telegram | Backward-compat fallback: `kind=chat`, `chat_id=<operator's current chat>` |
| P1-3 | HTTP mutual-exclusion (через public API): `curl -sS -X POST "https://tgp.efimov.mobi/api/v1/digests" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"name":"vps_watch_p1_3","channel_ids":["profendocrinologist"],"chat_id":<OPERATOR_CHAT_ID>,"target":{"kind":"chat","chat_id":67890},"cron_expression":"0 9 * * *"}'` | curl | **422** с `error_class` указывающим на conflict; body содержит «mutually exclusive» |
| P1-4 | CLI mutual-exclusion (через SSH + docker exec): `ssh user@VPS 'docker compose exec -T tg_parser tg-parser digest add --user $(docker compose exec -T tg_parser_postgres psql -U tg_parser_user -d tg_parser -At -c "SELECT id FROM users WHERE role='"'"'admin'"'"' LIMIT 1") --chat-id 12345 --channel-id @X --name "vps_watch_p1_4" --channels @profendocrinologist'` | CLI | exit-code != 0 с сообщением о взаимной исключительности |
| P1-5 | MCP `list_digests()` после P0-1/P0-2 (когда ephemeral подписки ещё активны) | MCP call | Response показывает `target_kind` + `chat_id`/`channel_id` для смешанных подписок без ValidationError; включает `digest_94483db9` с `target_kind="chat"` |
| P1-6 | Idempotency target-swap: MCP `subscribe_digest(name="vps_watch_p1_6", channel_ids=[...], chat_id=<OPERATOR_CHAT_ID>)` → потом `subscribe_digest(name="vps_watch_p1_6", channel_ids=[...], target={"kind":"channel","channel_id":"<R-1>"})` | MCP × 2 | Вторая попытка: `created=false`, `changed_fields` содержит `["target_kind", "channel_id", "chat_id"]` (или подмножество); cleanup после verify |

---

## 4. P2 monitoring loop (passive, ~4h cadence)

| ID | Что | Как | Threshold | Action на breach |
|---|---|---|---|---|
| P2-1 | Latent BUG-029 (race-retry без rollback) | `ssh ... 'docker logs --since 4h tg_parser \| grep -E "InFailedSQLTransactionError\|IntegrityError"'` | 0 occurrences | ≥1 ⇒ escalate BUG-029 из follow-up в hotfix-приоритет |
| P2-2 | **NEW: BUG-030 recurrence** — `digest_scheduler_initial_load_failed` после restart-window | `ssh ... 'docker logs --since 4h tg_parser_bot \| grep digest_scheduler_initial_load_failed'` | 0 (recovery был discrete event при deploy) | ≥1 без последующего successful reconcile = hotfix-pri BUG-030 |
| P2-3 | Transient publish failures | `ssh ... 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total{result=\"failed\"}"'` | 0 | ≥1 ⇒ classification drift в `_CHANNEL_PUBLISH_PERMANENT_FRAGMENTS`, review |
| P2-4 | Uptime continuity | `ssh ... 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=up{job=~\"tg_parser.*\"}"'` | api/mcp/bot = 1 | api/mcp = 0 любой bucket → STOP, incident; bot=0 любой bucket после deploy = elevation BUG-030 |
| P2-5 | 5xx на subscribe endpoints | `ssh ... 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_api_requests_total{path=~\"/api/v1/(digests\|watchlists).*\",status=~\"5..\"}"'` | 0 за окно | ≥1 ⇒ capture path+code+body, read tg_parser logs за минуту до 5xx |
| P2-6 | Reactivate flow (после P0-2) | После P0-2 повторить `subscribe_digest(name="vps_watch_p0_2_denied", ..., target={"kind":"channel","channel_id":"<R-1>"})` (где бот ESTь admin), затем cleanup | Должно reactivate: `is_active: false → true`, `changed_fields` содержит `is_active` | Если НЕ reactivates ⇒ ValidationError в upsert path |
| P2-7 | `digest_94483db9` health (passive) | `ssh ... 'docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "SELECT is_active, target_kind, last_sent_at FROM digest_subscriptions WHERE id::text LIKE '"'"'94483db9%'"'"';"'` | `is_active=true, target_kind=chat`; `last_sent_at` НЕ деградирует к старым значениям | Любая mutation = inconsistency, STOP escalate |

---

## 5. Cursor Automations feasibility (VPS — переоценено)

**Ключевое отличие от local plan:** VPS публично экспонирует:
* `https://tgp.efimov.mobi` — HTTP API
* `https://mcp.tgp.efimov.mobi` — **MCP endpoint (HTTPS, public TLS)**
* `https://grafana.tgp.efimov.mobi` — Grafana UI
* Prometheus НЕ публичен (per watch note line 92)

Это означает Cursor cloud automation **МОЖЕТ**: (a) вызывать наш MCP server через MCP-tool action, (b) триггериться от Grafana webhook (если настроить Grafana alerting → Cursor webhook), (c) опрашивать `tgp.efimov.mobi` REST endpoints, (d) использовать GitHub triggers как в local-plan. **НЕ может:** SSH, docker exec, прямой read Prometheus.

### Feasibility table (VPS context)

| Item | Local verdict | **VPS verdict** | Rationale |
|---|---|---|---|
| P0-1 success path | MANUAL | **SEMI** | Cloud automation может вызвать MCP `subscribe_digest`+`unsubscribe_digest` через `mcp.tgp.efimov.mobi` ⇒ instrumented test cycle. **Но** validation что сообщение реально лендится в R-1 (`_publish_to_target` success) требует либо ручного eyeball, либо Telegram MTProto-проверки (вне scope Cursor automation). |
| P0-2 permission_denied | MANUAL | **SEMI** | То же что P0-1: MCP-side можно автоматизировать, но fallback DM verification требует Telegram observer |
| P0-3 watchlist | MANUAL | **SEMI** | MCP-callable, но trigger_pipeline result + match delivery нужно eyeball |
| P0-4 legacy chat | MANUAL | **AUTOMATABLE (read-only)** | Scheduled automation at `2026-05-25T06:05Z`: вызывает MCP `list_digests()` через `mcp.tgp.efimov.mobi`, проверяет `digest_94483db9` `target_kind == "chat"` и `last_sent_at >= 2026-05-25T06:00Z`. Если нет — создать GitHub Issue / Slack alert. |
| P1-1, P1-2 bot NL | MANUAL | MANUAL | Требует live Telegram chat oprerator'а с bot; не automatable |
| P1-3 HTTP mutex 422 | MANUAL | **AUTOMATABLE** | Scheduled automation: POST на `https://tgp.efimov.mobi/api/v1/digests` с conflict body; expect 422; alert на отклонение |
| P1-4 CLI mutex | MANUAL | MANUAL | CLI требует docker exec — нет surface для cloud |
| P1-5 list_digests | MANUAL | **AUTOMATABLE** | MCP `list_digests` через public endpoint; structural validation |
| P1-6 idempotency swap | MANUAL | **AUTOMATABLE** | Двухкратный MCP `subscribe_digest` + assert `changed_fields` |
| P2-1 BUG-029 logs | SEMI | MANUAL | Логи на VPS, недоступны Cursor sandbox |
| P2-2 BUG-030 logs | SEMI | MANUAL | Same |
| P2-3, P2-4, P2-5 Prometheus | MANUAL | **SEMI** | Prometheus НЕ публичен. **НО** Grafana публичен — если настроить Grafana alerting rule + Cursor webhook receiver, можно push-based automation на threshold breach (`up{bot}==0 for 5m`, `tg_digest_channel_publish_total{result="failed"} > 0`, etc.) |
| P2-6 reactivate | MANUAL | **AUTOMATABLE** | MCP-side test cycle |
| P2-7 `digest_94483db9` health | MANUAL | **AUTOMATABLE** | См. P0-4 |
| **T+24h closure reminder** | AUTOMATABLE | AUTOMATABLE | Scheduled cron + GitHub Issue creation — общий для local и VPS |

### Драфт 1 — Scheduled MCP health probe (T+24h `digest_94483db9` check)

```json
{
  "name": "TG_parser VPS — digest_94483db9 next-tick verifier (T+19h)",
  "description": "At 2026-05-25T06:05Z (5 min after expected digest_94483db9 cron tick at 06:00Z Europe/Nicosia), call MCP list_digests via mcp.tgp.efimov.mobi and verify digest_94483db9 target_kind='chat' + last_sent_at advanced past 06:00Z. Create GitHub Issue if assertion fails (P0-4 legacy chat regression guard).",
  "workflow": {
    "triggers": [
      {
        "schedule": {
          "cron": "5 6 25 5 *",
          "timezone": "UTC"
        }
      }
    ],
    "model": "claude-sonnet-4.5",
    "repositories": [],
    "permissions": "private",
    "memoryEnabled": false,
    "mcp_servers": [
      {
        "name": "tg-parser-vps",
        "url": "https://mcp.tgp.efimov.mobi",
        "auth": { "type": "bearer", "secret_name": "TG_PARSER_VPS_MCP_KEY" }
      }
    ],
    "actions": [
      {
        "open_github_issue_on_failure": {
          "repo": "AlexEfimov/TG_parser",
          "title": "Wave 1 step 4 — digest_94483db9 P0-4 regression check FAILED at T+19h",
          "body_template": "P0-4 legacy chat regression guard failed. digest_94483db9 either: (a) target_kind != 'chat' after migration, OR (b) last_sent_at did not advance past 2026-05-25T06:00Z (i.e. cron didn't fire OR _publish_to_target broke chat dispatch). Inspect logs: ssh -p 2296 user@212.72.189.15 'docker logs --since 2026-05-25T05:55Z tg_parser_bot | grep 94483db9'. Possible rollback candidate."
        }
      }
    ],
    "prompt": "Using the tg-parser-vps MCP server, call list_digests. Find the entry where id matches '94483db9-9351-4f99-9aec-46949d9ddd09'. Assert: (1) target_kind == 'chat', (2) chat_id == 5445781511, (3) is_active == true, (4) last_sent_at >= '2026-05-25T06:00:00Z' (parse as ISO datetime). If ALL pass — exit cleanly with no action. If ANY fail — open GitHub Issue using the body_template, including the actual returned JSON in the body for forensics. DO NOT modify the subscription. DO NOT call unsubscribe_digest. Read-only operation."
  }
}
```

### Драфт 2 — Webhook-triggered Grafana alert ingress

> **Prerequisite:** Grafana alerting rule с webhook receiver на Cursor automation URL (генерируется после save automation). Detailed setup: в Grafana UI → Alerting → Contact points → New (`type=Webhook`, URL = Cursor automation webhook URL, content-type `application/json`).

```json
{
  "name": "TG_parser VPS — Grafana alert ingress (BUG-030 / up{bot}=0 / 5xx spike)",
  "description": "Triggered by Grafana alerting rule webhook when one of: (1) up{job='tg_parser_bot'} == 0 for 5m, (2) digest_scheduler_initial_load_failed recurrence rate > 0 over 10m, (3) tg_api_requests_total{path=~'/api/v1/(digests|watchlists).*',status=~'5..'} rate > 0. Creates GitHub Issue with link to Grafana panel + auto-attaches step-4 watch context.",
  "workflow": {
    "triggers": [
      {
        "webhook": {
          "schema_hint": "Grafana webhook v9 payload (status, alerts[].annotations, alerts[].labels)"
        }
      }
    ],
    "model": "claude-sonnet-4.5",
    "repositories": ["AlexEfimov/TG_parser"],
    "permissions": "private",
    "memoryEnabled": true,
    "actions": [
      {
        "open_github_issue": {
          "repo": "AlexEfimov/TG_parser",
          "title_template": "ALERT: {{alert.labels.alertname}} (Wave 1 step 4 watch)",
          "labels": ["wave1-step4-watch", "alert"]
        }
      }
    ],
    "prompt": "Parse the Grafana webhook payload. Extract: alertname, severity, fingerprint, annotations.summary, annotations.description, labels (especially service/job/result), generatorURL (link to Grafana panel). If alertname matches 'digest_scheduler_initial_load_failed_recurrence' — title prefix [BUG-030 elevation]. If 'tg_parser_bot_down' — title prefix [bot down]. If 'tg_api_5xx_spike' — title prefix [5xx]. Body: include payload JSON, link Grafana panel, link to docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md and docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md. Use memory to dedupe — if fingerprint already issued an Issue in last 4h, comment on existing Issue instead of creating new one."
  }
}
```

### Драфт 3 — T+24h closure reminder (общий для local + VPS)

См. local exercise plan § 4 «Драфт `CreateAutomationRequest` для T+24h closure reminder» — переиспользовать as-is, изменив только cron timestamp на `50 10 25 5 *` (T+24h VPS = `2026-05-25T10:50Z`).

### Workflow JSON shape — caveat

`workflow` proto JSON shape **частично восстановлен** из публичных docs и tool descriptor (который говорит `additionalProperties: true` без полной schema). Точные поля `triggers[].schedule.cron`, `actions[].open_github_issue`, `mcp_servers[]`, `actions[].open_github_issue_on_failure` — **conjectural**.

**Рекомендованный workflow для оператора:**
1. Не вызывать `create_automation` напрямую с этими JSON.
2. Передать каждый workflow JSON в MCP-вызов `build_automation_prefill_url(workflow=...)` — получить URL на cursor.com/automations.
3. Открыть URL → cursor.com развернёт prefill-форму → доработать триггер/permissions/MCP-server/secrets → save.

---

## 6. GREEN closure criteria

`REVIEW_2026-05-24_WAVE1_STEP4_DONE.md` помечается GREEN на VPS ⇔ ВСЕ следующие условия выполнены:

| Critère | Метрика / артефакт | Threshold |
|---|---|---|
| C-1 | P0-1 выполнен | `tg_digest_channel_publish_total{result="success"}` ≥ 1 |
| C-2 | P0-2 выполнен | `{result="permission_denied"}` ≥ 1 + `is_active=false` row + DM получен в operator chat |
| C-3 | P0-3 выполнен | watchlist channel-match доставлен; `list_watchlists` без ValidationError |
| C-4 | **P0-4 без регрессии** (CRITICAL) | `digest_94483db9` tick T+19h PASS: message landed, `last_sent_at` advanced, 0 errors в логах |
| C-5 | P2-1 чисто | 0 `InFailedSQLTransactionError` за окно. Если ≥1 → BUG-029 hotfix |
| C-6 | P2-2 чисто (NEW для VPS) | 0 recurrence `digest_scheduler_initial_load_failed` после deploy reconcile. Если ≥1 → BUG-030 hotfix |
| C-7 | P2-3 чисто | `{result="failed"}` = 0 (transient publish) |
| C-8 | P2-4 чисто | `up{api}=1, up{mcp}=1, up{bot}=1` во всех buckets; единственный bot startup-glitch допустим (already documented) |
| C-9 | P2-5 чисто | 0 × 5xx на `/api/v1/(digests\|watchlists)` |
| C-10 | P2-7 чисто | `digest_94483db9` row unchanged from post-deploy state (`target_kind=chat, chat_id=5445781511, is_active=true`, `last_sent_at` только advance) |
| C-11 | Watch note completed | `docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` секция «24h watch observations» заполнена |
| C-12 | BUG-029 + BUG-030 filed | `docs/notes/BUG_LOG.md` content для BUG-029 и BUG-030 готов |

---

## 7. Escalation matrix (VPS-specific)

| Триггер | Действие | Документировать |
|---|---|---|
| C-4 (P0-4) fail — `digest_94483db9` regression | **CRITICAL** — потенциальный rollback. Verify: real user не получил сообщение → contact user immediately; check forward-fix (e.g. manually trigger via `register_digest_subscription` reconcile). Если forward-fix невозможен в 30 мин — rollback (см. ниже) | watch note + IMMEDIATE Slack/Telegram alert operator |
| `{result="failed"}` ≥ 1 | Read logs, classify (transient retry vs real bug). Classification drift → patch `_CHANNEL_PUBLISH_PERMANENT_FRAGMENTS` | `BUG_LOG.md`, watch note, new PR |
| `InFailedSQLTransactionError` recurrence (P2-1) | BUG-029 elevation из follow-up в hotfix. One-liner PR: `await session.rollback()` между failed `create()` и retry SELECT в `digest_service.py:265-272` | `BUG_LOG.md` BUG-029 update, new PR |
| `digest_scheduler_initial_load_failed` recurrence (P2-2) без 60s reconcile recovery | BUG-030 elevation: добавить retry-with-backoff в bot's `_initial_load()` + настроить `structlog.processors.format_exc_info` | `BUG_LOG.md` BUG-030 update, new PR |
| ValidationError на `list_watchlists` для channel-target | Hotfix: проверить `WatchInterestInfo` Optional fields в `mcp_server.py` (regression of commit 3 PR #93 fix) | `BUG_LOG.md`, hotfix PR |
| 5xx на `/api/v1/digests` или `/api/v1/watchlists` ≥ 1 | Capture request, path, body, response. Read tg_parser logs за минуту до 5xx | `BUG_LOG.md`, watch note |
| `up{api}` или `up{mcp}` = 0 на bucket | STOP — деградация. `ssh ... docker compose ps`, `docker logs`, healthcheck inspect | watch note блок «incidents», SOSE-style postmortem если > 5min |
| **Любая регрессия `target.kind=chat` legacy path** | **CRITICAL** — potential rollback. Real users affected | `BUG_LOG.md` + IMMEDIATE escalation |

### Rollback (emergency only — REAL PROD)

```bash
# On VPS:
ssh -p 2296 user@212.72.189.15
cd ~/TG_parser

# 1. Stop services
docker compose stop tg_parser tg_parser_bot tg_parser_mcp

# 2. Restore data from backup (PRE step-4)
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "DROP TABLE digest_subscriptions CASCADE; DROP TABLE watch_interests CASCADE;"
docker exec -i tg_parser_postgres psql -U tg_parser_user -d tg_parser < backups/pre_step4_vps_backup_20260524T104149Z.sql

# 3. Downgrade migration
docker exec tg_parser tg-parser db downgrade --db ingestion -1
# expect: a8b7c6d5e4f3 -> f1a2b3c4d5e6

# 4. Rebuild from pre-step-4 commit
git checkout 26d03a5  # BUG-028 hotfix
docker compose --profile bot build tg_parser tg_bot mcp
docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot
```

**После rollback:** немедленно создать GitHub Issue с timeline, root-cause, и hot-fix proposal перед next deploy attempt.

---

## 8. Когда закрывать VPS watch

* **Nominal close:** `2026-05-25T10:50:10Z` (~13:50 MSK 25-05).
* **Critical checkpoint:** `2026-05-25T06:00:00Z` (T+19h09m) — P0-4 `digest_94483db9` tick observation. Если fail — closure откладывается, escalation per matrix.
* **Early close OK ⇔** C-1..C-12 все PASS до nominal T+24h, P0-4 successful, никаких open incidents.
* **Extended watch ⇔** любой P2 показал non-zero hit; продлить ещё +24h после fix.

После closure: финализировать `REVIEW_2026-05-24_WAVE1_STEP4_DONE.md` (VPS verdict block + ссылка на этот runbook), обновить ADR 0008 история-row («GREEN at T+24h on VPS prod»), commit + push (одним коммитом `docs(watch): WAVE1 step 4 VPS GREEN closure`).
