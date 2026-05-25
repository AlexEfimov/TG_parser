# Runbook — Wave 1 Step 4 VPS Watch Window: CURSOR AUTOMATIONS REGISTRY

**Created:** 2026-05-24 (immediately после step-4 VPS deploy + watch open T+0 = `2026-05-24T10:50:10Z`).

**Owner:** Alexander Efimov (scope=private, личные Cursor automations).

**Purpose:** registry создаваемых Cursor Automations для VPS watch window. Дополняет [`WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md) (что делает оператор руками) и [`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) (полный план observations).

---

## 0. Discovered canonical workflow schema

В процессе создания этих automations была опытно установлена форма payload-а для `cursor-backend-control.create_automation` (документация Cursor публично shape не описывает; tests шли через protobuf error messages):

```json
{
  "name": "...",
  "description": "...",
  "workflow": {
    "triggers": [
      { "cron": { "cron": "<5-field cron UTC, no timezone field>" } }
      // или { "webhook": {} }
    ],
    "model": "claude-sonnet-4.5",            // optional
    "actions": [
      // { "slack": {...} } — accepted but field names unknown
      // { "mcp": {...} }   — accepted but field names unknown
      // Остальные ("github", "linear", "email", "webhook", "agent",
      // "memory", "open_pull_request", "open_github_issue") отвергнуты.
      // ⇒ Все side-effects делаются ИЗ prompt-а агента через MCP server tools.
    ],
    "prompts": [
      { "prompt": "<task description for the agent — see each automation below>" }
    ]
  }
}
```

**Что НЕ нашло Place в API payload (нужно задавать через UI после `create_automation`):**

| Поле | Где задавать | Зачем |
|---|---|---|
| `repositories` (repo allow-list) | Cursor UI → Automations → Edit → Repositories | агент сможет читать/писать в repo |
| `mcp_servers` (URLs + auth) | Cursor UI → Automations → Edit → MCP servers | агент сможет вызвать `mcp.tgp.efimov.mobi` |
| Secrets (для bearer-токенов MCP) | Cursor UI → Automations → Secrets | secure storage |
| Webhook URL (для `webhook` trigger) | Cursor UI → Automations → Edit → Webhook | копировать после создания, передать в Grafana/Sentry |
| Timezone для cron | **нет такого поля** — cron всегда UTC | задавать cron в UTC явно |

⚠️ **Гарантия скрытой конфигурации:** при `create_automation` MCP automation создаётся БЕЗ привязанных repo / MCP servers / secrets. **Оператор обязан** открыть каждую automation в UI и догрузить эту конфигурацию **до первого срабатывания**. Без этого `2bd25769` (P0-4 verifier) попробует вызвать `list_digests`, не найдёт MCP server `tg-parser-vps`, и (по prompt-у) откроет fallback issue «P0-4 verifier blocked: MCP server tg-parser-vps not configured».

---

## 1. Registry — созданные automations

### 1.1 `2bd25769-52b1-4525-a0c5-239d589d231f` — P0-4 verifier (`digest_94483db9` next-tick)

* **Trigger:** cron `5 6 25 5 *` UTC = `2026-05-25T06:05Z` (≈5 min после ожидаемого tick'а `digest_94483db9` cron `0 9 * * *` Europe/Nicosia = `06:00Z` UTC в EEST).
* **Action:** prompt-based (no native actions); MCP `list_digests` на `tg-parser-vps`; condition check; opens GitHub issue в `AlexEfimov/TG_parser` если assertion fails.
* **Assertions (ALL must pass для GREEN):**
  1. `target_kind == 'chat'`
  2. `chat_id == 5445781511`
  3. `is_active == true`
  4. `last_sent_at >= 2026-05-25T06:00:00Z` (parse as ISO datetime)
* **Output on GREEN:** single-line log `P0-4 GREEN: digest_94483db9 ticked at <last_sent_at>`, никаких issue.
* **Output on RED:** GitHub issue `Wave 1 step 4 VPS — digest_94483db9 P0-4 regression check FAILED at T+19h` со JSON forensics, гипотезой, SSH inspection hint, rollback флагом.
* **Safety:** read-only — НИКОГДА не вызывает `unsubscribe_digest` или другие mutators. Hardcoded в prompt-е.
* **UI configuration TODO перед T+19h:**
  * Repositories: `AlexEfimov/TG_parser` (для open_issue).
  * MCP servers: name `tg-parser-vps`, URL `https://mcp.tgp.efimov.mobi/mcp` (**с `/mcp` суффиксом** — FastMCP `streamable_http_path`), Headers `Authorization: Bearer <token>` (скопировать готовый токен из локального `~/.cursor/mcp.json` поле `tg-parser.headers.Authorization` — тот же endpoint, та же auth, не нужно генерить новый). Tools: минимум `list_digests` enabled.
* **Verification (status as of 2026-05-24T12:42Z):** ✅ MCP server attached — `get_automation` показывает `actionTypes: ["mcp"]`, `actionCount: 1`. End-to-end MCP test через `user-tg-parser` MCP: `list_digests` вернул `digest_94483db9` со всеми expected полями (`target_kind="chat"`, `chat_id=5445781511`, `is_active=true`, `last_sent_at=2026-05-24T06:00:08Z`). ✅ **In-automation MCP test (manual Run в UI, T+1h54m):** оператор запустил test run `2bd25769`, agent успешно позвал `list_digests` через прикреплённый MCP server `tg-parser-vps`; run прерван оператором до assertion-check чтобы не создавать false-positive issue. ⇒ известный issue 2 (MCP resolution failure in cron-triggered runs) на нашем setup'е НЕ воспроизводится.
* **URL:** https://cursor.com/automations/2bd25769-52b1-4525-a0c5-239d589d231f

---

### 1.2 `f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f` — T+24h closure reminder

* **Trigger:** cron `50 10 25 5 *` UTC = `2026-05-25T10:50Z` (точно T+24h после VPS deploy в `2026-05-24T10:50:10Z`).
* **Action:** prompt-based; opens GitHub issue `Wave 1 step 4 VPS — watch window CLOSURE due (T+24h reached)` со полным closure чеклистом C-1…C-8 inline в body.
* **Safety:** automation НЕ выполняет closure checks сама (нет SSH access из cursor.com sandbox). Issue = живой чеклист, оператор прогоняет руками.
* **UI configuration TODO:**
  * Repositories: `AlexEfimov/TG_parser`.
  * MCP servers: НЕ требуется.
* **URL:** https://cursor.com/automations/f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f

---

### 1.3 `7b35ca01-a7d1-4c3a-bb8b-940918e506d6` — Incident webhook ingress (Grafana / curl / Sentry)

* **Trigger:** webhook — URL сгенерируется в UI после создания (формат `https://cursor.com/api/webhook/<token>`).
* **Action:** prompt-based; парсит входящий payload (Grafana v9, Sentry, free-form `curl`); skip-it'ит `DeadMansSwitch`/`Watchdog`/test-pings; opens GitHub issue с правильным title prefix для известных bucket-ов:
  * `[bot down]` — `up{job="tg_parser_bot"} == 0` >5m
  * `[api down]` — `up{job="tg_parser_api"} == 0` >5m
  * `[BUG-030 elevation]` — `digest_scheduler_initial_load_failed` recurrence >10m
  * `[5xx]` — 5xx spike on `/api/v1/{digests,watchlists}`
  * `[channel-publish-fail]` — `tg_digest_channel_publish_total{result="failed"}` rate >0
  * `[soft-deactivation]` — `tg_digest_channel_publish_total{result="permission_denied"}` unexpected spike
  * `[alert]` — fallback
* **Safety:** read-only — НИКОГДА не shellит на VPS, не пушит код. Один payload = максимум один issue.
* **Webhook URL:** `https://api2.cursor.sh/automations/webhook/7b35ca01-a7d1-4c3a-bb8b-940918e506d6` (опубликован 2026-05-24, scope=private).
* **UI configuration TODO:**
  * Repositories: `AlexEfimov/TG_parser`.
  * MCP servers: НЕ требуется (issue creation = чисто GitHub).
* **Wired sources (см. `WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md` § 1.7 / § 1.8):**
  * Operator `curl` ad-hoc — env var `TG_PARSER_WATCH_WEBHOOK` + 7 готовых snippet'ов под сценарии A-G.
  * Grafana Contact point `cursor-watch-webhook` + 3-6 alert rules (`tg_parser_bot_down`, `tg_parser_api_down`, `tg_api_5xx_spike`, optional BUG-030 / channel-publish-fail / soft-deactivation rules).
  * Sentry — пока не настроен (можно добавить позже, prompt parsing уже поддерживает).
* **URL:** https://cursor.com/automations/7b35ca01-a7d1-4c3a-bb8b-940918e506d6

---

## 2. Что **НЕ реализовано** через Automations (по дизайну) — выполняется руками

| Action | Почему не automated | Где описано |
|---|---|---|
| Channel publish success path (P0-1) — subscribe + verify + cleanup | Mutating MCP subscribe из cron-агента рискован (race-trigger, retry storms) + создаёт real Telegram messages | `WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md` § M-2 |
| Channel publish denied path (P0-2) | Same as M-2 + требует pre-created R-2 channel где бот НЕ admin (cursor.com не контролирует Telegram membership) | § M-3 |
| Watchlist channel target (P0-3) | Same as M-2 | § M-4 |
| Bot NL tests (P1-1, P1-2) | Cursor.com sandbox не имеет Telegram MTProto SDK + не залогинен как operator | § M-6 |
| Channel admin assignment (R-1 setup) | Telegram UI action, нет API | § M-1.4 |
| DM fallback verification | Требует чтения Telegram chat — нет API | § M-3.4 |
| Pre-flight ssh checks | Cursor.com cloud sandbox не имеет egress на private VPS (212.72.189.15:2296) | § M-1.1 |
| Prometheus spot-checks через ssh | Same — нет ssh egress | § M-8 |
| Closure C-1…C-8 SSH + Prometheus queries | Same — нет ssh egress; automation `f93e557a` только напоминает | § M-9 |
| `tg-parser db downgrade` (rollback) | Никогда не autonomous; всегда operator authorization | escalation matrix |

---

## 3. Cleanup после watch closure (T+24h+)

После того как closure session завершён GREEN/RED и решение принято:

```text
1. Disable обе scheduled automations через MCP `update_automation(automationId, enabled=false)` или UI toggle:
   - 2bd25769-52b1-4525-a0c5-239d589d231f (P0-4 verifier — single-shot 2026-05-25T06:05Z, технически уже сработала)
   - f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f (T+24h closure — single-shot, уже сработала)

2. (опционально) Оставить enabled для long-tail observations (>T+24h):
   - 7b35ca01-a7d1-4c3a-bb8b-940918e506d6 (incident webhook — webhook-driven, нагрузки нет если никто не push'ит)

3. (опционально) Delete полностью через Cursor UI после убеждения, что больше не нужны (MCP delete tool в descriptor-е не expose'нут).
```

---

## 4. Probe automations (для discovery schema; ВСЕ disabled + переименованы с префиксом `[DELETE_ME]`)

В процессе reverse-engineering payload schema было создано 7 probe automations с минимальными prompt'ами. Все **disabled** (enabled=false) + переименованы с префиксом `[DELETE_ME]` для visual cleanup в UI. `cursor-backend-control` MCP не expose-ит delete tool — удалить можно только через https://cursor.com/automations → list → каждую `[DELETE_ME] ...` → trash icon.

| ID | Display name (после rename) | Что подтвердил probe |
|---|---|---|
| `d3db307f-f7aa-4ab2-aaee-bb060b52a6ab` | `[DELETE_ME] schema-probe-8 (empty cron)` | `triggers[].cron == {}` works |
| `e700f0d8-42f1-4de6-b3c4-f2a6949c762c` | `[DELETE_ME] schema-probe-11 (cron.cron field)` | `triggers[].cron.cron == "5 6 25 5 *"` works |
| `942ed185-348f-43d2-8c60-84f3494b9c3f` | `[DELETE_ME] schema-probe-17 (slack action)` | `actions[].slack == {}` accepts |
| `366cebf6-c18b-42e8-bad2-f87d54938dd6` | `[DELETE_ME] schema-probe-18 (mcp action)` | `actions[].mcp == {}` valid action union member |
| `f7aed5ef-8033-4f28-bc5a-249b16474708` | `[DELETE_ME] schema-probe-22 (prompts field)` | `workflow.prompts[].prompt` canonical path |
| `1599436d-b0ec-4634-a864-3301e1897f0c` | `[DELETE_ME] schema-probe-30 (model field)` | `workflow.model` works |
| `9168a065-9eb5-43a9-abcc-24c6c47c4598` | `[DELETE_ME] schema-probe-43 (webhook trigger)` | `triggers[].webhook == {}` works |

---

## 5. Связанные документы

* Operator manual: [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md)
* Full exercise plan: [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md)
* Watch note: [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)
* Cursor Automations public docs: https://cursor.com/docs/cloud-agent/automations
