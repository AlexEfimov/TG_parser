# Handoff for new chat — Wave 1 step 4 VPS watch (ongoing)

**Created:** 2026-05-24T18:30Z (T+7h40m в открытом watch window).
**Purpose:** continue OP-2 / OP-3 interactive tests + (eventually) T+24h closure session в новом Cursor chat без потери context.

---

## Текущий статус watch window

**Opened:** `2026-05-24T10:50:10Z` (T+0)
**Nominal close:** `2026-05-25T10:50:10Z` (T+24h)
**Now:** ~T+7h40m
**Time until P0-4 automation fires:** ~11h35m (`2026-05-25T06:05Z`)
**Time until T+24h closure reminder fires:** ~16h20m (`2026-05-25T10:50Z`)

**Verdict (interim):** GREEN-pending. Infrastructure full setup verified end-to-end через 4 GitHub issues #94-#97 + recurring DatasourceNoData (#96, #98) → patched.

---

## Что уже сделано (для context)

### Phase 1 — Cursor Automations infrastructure
3 production automations созданы + valid:
* **`2bd25769-52b1-4525-a0c5-239d589d231f`** — P0-4 `digest_94483db9` verifier (cron `5 6 25 5 *` UTC = 06:05Z 25-05). MCP server `tg-parser-vps` (URL `https://mcp.tgp.efimov.mobi/mcp`, Bearer auth) attached. End-to-end `list_digests` test passed.
* **`f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f`** — T+24h closure reminder (cron `50 10 25 5 *` UTC = 10:50Z 25-05). Opens GitHub issue with C-1…C-8 закрытие чеклистом.
* **`7b35ca01-a7d1-4c3a-bb8b-940918e506d6`** — incident webhook ingress. Webhook URL: `https://api2.cursor.sh/automations/webhook/7b35ca01-a7d1-4c3a-bb8b-940918e506d6`. Auth: `Authorization: Bearer crsr_*` (см. `$TG_PARSER_WATCH_WEBHOOK_AUTH` env var).

7 probe automations переименованы `[DELETE_ME] schema-probe-*` (disabled, manual UI delete pending).

### Phase 2 — Operator env vars (на local Mac, `~/.zshrc`)
```bash
export TG_PARSER_WATCH_WEBHOOK="https://api2.cursor.sh/automations/webhook/7b35ca01-a7d1-4c3a-bb8b-940918e506d6"
export TG_PARSER_WATCH_WEBHOOK_AUTH="Bearer crsr_<token>"
```

### Phase 3 — Grafana setup
* Contact point `cursor-watch-webhook` (URL + Authorization header) on https://grafana.tgp.efimov.mobi
* Default notification policy → `cursor-watch-webhook`
* Folder `wave1-step4-watch`, 3 alert rules:
  * `tg_parser_bot_down` — `up{job="tg_parser_bot"} < 0.5` for 5m, severity critical
  * `tg_parser_api_down` — `up{job="tg_parser_api"} < 0.5` for 5m, severity critical
  * `tg_api_5xx_spike` — `sum(rate(tg_parser_http_http_requests_total{handler=~"/api/v1/(digests|watchlists).*",status="5xx"}[5m])) > 0` for 5m, severity warning. **noData → OK** (patched 2026-05-24T18:30Z после recurring #96, #98).

### Phase 4 — End-to-end pipeline GREEN
Triple-verified: manual curl (#94, #95) + Grafana payload simulation (#97) + natural Grafana firing (#96, #98). Все closed.

---

## Что осталось — PENDING (важность по убыванию)

### MUST до 06:05Z 25-05
* **OP-1:** глазами проверить в Cursor UI, что `Repositories: AlexEfimov/TG_parser` стоит на `2bd25769` и `f93e557a` (на `7b35ca01` уже подтверждено через факт issue creation). Без этого `2bd25769` не сможет открыть regression issue в RED-сценарии.

### HIGH (interactive tests, ~20-30 минут — оптимально сегодня)
**Полная пошаговая инструкция в** [`docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md`](../runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md):
* **PRE** — pre-flight (env vars + R-1 + R-2 test channels + OPERATOR_CHAT_ID + DM с ботом + baseline Prometheus snapshot) ~10-15 мин
* **A (M-2)** — channel-publish SUCCESS path (материализует `tg_digest_channel_publish_total{result="success"}≥1`) ~5 мин ⭐⭐⭐
* **B (M-3)** — channel-publish DENIED path + soft-deactivate + fallback DM ~5 мин ⭐⭐
* **C (P1-1)** — bot NL → channel target (validates prompt v1.7.0 `target_kind_semantics`) ~3-5 мин ⭐⭐
* **D (P1-2)** — bot NL → chat target ~3 мин ⭐⭐
* **E (M-4)** — watchlist channel target (bonus, `WatchInterestInfo` schema validation) ~5-10 мин ⭐
* **FIN** — single batched report в watch note ~2 мин

### Passive (без вмешательства оператора)
* `2026-05-25T06:00Z` — `digest_94483db9` next tick (bot scheduler)
* `2026-05-25T06:05Z` — `2bd25769` P0-4 verifier (silent если GREEN, issue если RED)
* `2026-05-25T10:50Z` — `f93e557a` T+24h closure reminder (issue с C-1…C-8 чеклистом)
* Continuous — Grafana firing → webhook → issue с правильным prefix

### Cleanup после closure (T+24h+, ~5 минут)
* Disable `2bd25769` + `f93e557a` через `update_automation(enabled=false)` (single-shot отстреляли)
* Delete `[DELETE_ME] schema-probe-*` (7 шт.) через Cursor UI
* Rotate `GRAFANA_ADMIN_PASSWORD` (был передан plaintext в operator transcript)
* Finalize `docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`
* File **BUG-029** (digest_service.py:265-272 race-retry без rollback)
* File **BUG-030** (digest_scheduler_initial_load startup race; self-healing within 60s, но recurrence будет escalation)

---

## Critical safety rules (ALWAYS apply на VPS)

См. § 0 SAFETY preamble в [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md):

* **S-1:** НЕ трогать `digest_94483db9` (real prod subscription, only passive observation)
* **S-2:** НЕ использовать `chat_id=5445781511` (real user); только свой `OPERATOR_CHAT_ID`
* **S-3:** НЕ subscribe на чужие channels; только operator-owned R-1/R-2
* **S-4:** All test subscriptions name `vps_watch_*`, cron `*/2 * * * *`, **немедленно cleanup** через unsubscribe_*
* **S-5:** R-2 (denied path channel) — operator-owned, бот НЕ admin (никогда не использовать чужой канал!)
* **S-6:** НЕ запускать `db downgrade` без operator authorization + backup recovery plan
* **S-7:** Все MCP-вызовы через свой user_id (не admin-impersonate без необходимости)

---

## Документация (читать в этом порядке для full context)

1. [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) — VPS watch note (live observations, verdicts)
2. [`docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md`](../runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md) — **главный actionable next-step runbook** для нового chat'а
3. [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](../runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md) — broader operator manual (§ 1.7 curl snippets, § 1.8 Grafana steps)
4. [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md) — registry created automations с ID + canonical workflow schema
5. [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) — full P0/P1/P2 plan + safety preamble + GREEN closure criteria C-1…C-12 + escalation matrix
6. [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md) — deploy runbook (для context)
7. [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — ADR underlying step 4
8. [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) — review marker (будет finalised на closure)

---

## Что НЕ передавать в новый chat

* Pure curl Bearer токены / Grafana password — НЕ копировать в новый chat (для security). Они уже у оператора в `~/.zshrc` и в VPS `.env`.
* Полный diff Wave 1 step 4 — он merged в `main` через PR #93 (commit `926a165`), читается из git history если нужно.

## Suggested initial prompt для нового chat

Скопировать целиком в новый Cursor chat:

```text
@docs/notes/HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md

Продолжаем Wave 1 step 4 VPS watch window (open T+0=2026-05-24T10:50:10Z,
close T+24h=2026-05-25T10:50:10Z). Сейчас T+~7h40m+.

Все automations и Grafana уже настроены и pipeline triple-verified
(см. handoff doc § "Что уже сделано").

Готов начать OP-2/OP-3 interactive tests по runbook
docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md.

Entry point: PRE phase (env vars + R-1/R-2 test channels + OPERATOR_CHAT_ID
+ baseline Prometheus snapshot).

Multitask Mode ON.
```

---

## Anti-patterns (часто встречающиеся ошибки)

* Не пытаться запустить full path bot stop test — pipeline уже triple-verified, downtime прод бот = real users impact + BUG-030 risk.
* Не править `digest_94483db9` через MCP / SQL — это real prod subscription (S-1).
* Не использовать `chat_id=5445781511` нигде — это owner real prod user'а (S-2).
* НЕ менять `~/.cursor/mcp.json` под `tg-parser-vps` именем — `tg-parser` остаётся для desktop сессий, `tg-parser-vps` это name только в Cursor cloud automation config (через UI, не через mcp.json).
* НЕ commit-ить toкены в git (`~/.zshrc` не в git → ok, но не положить токены в файлы репозитория).

---

## Ключевые IDs (для быстрого reference)

| Что | Value |
|---|---|
| Critical real subscription | `94483db9-9351-4f99-9aec-46949d9ddd09` (digest_94483db9, owner `5445781511`, cron `0 9 * * *` Europe/Nicosia) |
| Real owner chat_id | `5445781511` (НЕ использовать в тестах!) |
| VPS SSH | `ssh -p 2296 user@212.72.189.15` |
| VPS MCP endpoint | `https://mcp.tgp.efimov.mobi/mcp` (Bearer auth, токен в `~/.cursor/mcp.json` под `tg-parser`) |
| VPS Grafana | `https://grafana.tgp.efimov.mobi` (admin / см. VPS `.env`) |
| VPS Prometheus | `tg_parser_prometheus` container на VPS (only через `docker exec`) |
| PR | #93 (merged `926a165`) |
| Alembic head | `a8b7c6d5e4f3` |
