# Runbook — Wave 1 Step 4 Watch Session Exercise Plan

**Last reviewed:** 2026-05-24 (immediately после step-4 deploy `926a165`, watch open T+0=`2026-05-24T09:54:35Z`).

**Назначение:** структурированный план оператора на 24h watch window после деплоя ADR 0008 (polymorphic subscription target). Покрывает MCP / Bot / CLI / HTTP действия для материализации новых метрик, валидации best-effort policy и регрессионной защиты legacy chat-пути.

**Когда применять:** один раз в течение текущего watch window. После закрытия — артефакт остаётся как референс для следующих шагов с похожей механикой (например, Wave 2A webhook target).

**Связанные документы:**
* Watch note: [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md) — фиксация фактических наблюдений.
* Deploy runbook: [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](WAVE1_STEP4_DEPLOY_AND_WATCH.md) — pre-deploy + 24h watch summary.
* Step-3 watch precedent: [`docs/notes/WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](../notes/WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) — структурный шаблон.
* ADR 0008: [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — OQ#3 channel-publish best-effort policy.

---

## 0. Pre-requisites (оператору)

| # | Ресурс | Зачем |
|---|---|---|
| R-1 | **Тестовый Telegram-канал, где бот = admin + Post messages** | P0-1, P0-3 — материализация `tg_digest_channel_publish_total{result="success"}` |
| R-2 | **Тестовый канал, где бота НЕТ / не admin** | P0-2 — материализация `{result="permission_denied"}` + soft-deactivate + fallback DM |
| R-3 | **Доступ к Telegram DM от бота к owner-аккаунту** | Проверка fallback notification при soft-deactivate |
| R-4 | **Prometheus UI** `http://localhost:9090` | P2 monitoring |
| R-5 | **Доступ к `docker exec tg_parser_postgres psql`** | Проверка `is_active` после soft-deactivate, row invariants |
| R-6 | **MCP-клиент** (Claude Desktop / Cursor MCP / `mcp` CLI) с подключённым `user-tg-parser` либо `project-0-TG_parser-tg-parser` | P0/P1 MCP-tool вызовы |
| R-7 | **Bot conversation** (live Telegram chat с production ботом) | P1-1, P1-2 — тест prompt v1.7.0 `target_kind_semantics` |

> **Важно**: `tg_bot` сейчас в Exited(0) (3 недели). Для P1-1/P1-2 оператору нужно re-launch: `docker compose --profile bot up -d tg_bot`. Этот шаг = OA-1 из watch note, **не блокирует** GREEN closure, но без bot-поверхности P1-1/P1-2 не покрыть.

---

## 1. P0 чеклист (mandatory для GREEN closure)

### P0-1 — Success path (real channel where bot IS admin)

**Цель:** материализовать `tg_digest_channel_publish_total{result="success"}` ≥ 1; убедиться что сообщение реально доходит в канал.

| Шаг | Команда / действие | Ожидание |
|---|---|---|
| 1.1 | Назначить бота администратором в тестовом канале (R-1) с правом Post messages | done в Telegram UI |
| 1.2 | Через MCP: `subscribe_digest(name="watch_p0_1_success", channel_ids=["<real_source_channel>"], target={"kind":"channel","channel_id":"<R-1>"}, cron_expression="*/2 * * * *", timezone="UTC", format="summary", language="ru")` | success=true, subscription.target.kind="channel" |
| 1.3 | Подождать 2-3 минуты (cron `*/2`) | scheduler tick по `_digest_job_id(subscription.id)` |
| 1.4 | Проверка в канале (R-1) | дайджест опубликован ботом |
| 1.5 | `curl -s 'http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total{result="success"}' \| jq` | value ≥ 1 |
| 1.6 | Cleanup: `unsubscribe_digest(subscription_id=<id>)` | success=true |

**Восстановление при сбое:** если step 1.4 не дал сообщения но метрика `{result="failed"}` инкрементилась — read `docker logs --since 5m tg_parser`, проверить classification (transient vs permanent). Если permanent — это P0-2 кейс, бот не админ; повторить шаг 1.1.

### P0-2 — Permission denied path (channel where bot is NOT admin)

**Цель:** материализовать `{result="permission_denied"}` ≥ 1, проверить **soft-deactivate** (`is_active=false`), типизированный лог `channel_publish_permission_denied`, fallback DM owner'у.

| Шаг | Команда / действие | Ожидание |
|---|---|---|
| 2.1 | Использовать R-2 (бот гарантированно НЕ имеет post-прав, либо вообще не член) | предварительная установка |
| 2.2 | MCP: `subscribe_digest(name="watch_p0_2_denied", channel_ids=["<real_source>"], target={"kind":"channel","channel_id":"<R-2>"}, cron_expression="*/2 * * * *")` | success=true |
| 2.3 | Подождать 2-3 минуты | scheduler tick |
| 2.4 | `docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "SELECT id, is_active, target_kind, channel_id FROM digest_subscriptions WHERE name='watch_p0_2_denied';"` | `is_active=false` |
| 2.5 | `curl -s 'http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total{result="permission_denied"}' \| jq` | value ≥ 1 |
| 2.6 | `docker logs --since 5m tg_parser \| grep channel_publish_permission_denied` | ≥ 1 структурный лог-event |
| 2.7 | Проверить DM от бота к owner | сообщение вида «Подписка watch_p0_2_denied деактивирована: бот не админ в \<R-2\>» (если у owner есть `chat_id`) |
| 2.8 | Cleanup: `unsubscribe_digest(subscription_id=<id>)` | success=true |

**Permanent error fragments** (из `tg_parser/services/digest_service.py:95-106`, для контекста):
`chat not found`, `bot was blocked`, `user is deactivated`, `forbidden`, `not enough rights`, `need administrator`, `have no rights`, `bot is not a member`, `channel_private`, `administrator`.

### P0-3 — Watchlist channel target (parallel surface)

**Цель:** покрыть watchlist surface (не только digest); проверить fix `WatchInterestInfo` (channel_id field + chat_id Optional).

| Шаг | Команда / действие | Ожидание |
|---|---|---|
| 3.1 | MCP: `subscribe_watchlist(title="watch_p0_3", channel_ids=["<source_with_recent_docs>"], target={"kind":"channel","channel_id":"<R-1>"}, keywords=["test", "wave1"], threshold=0.1)` | success=true, interest.target.kind="channel" |
| 3.2 | Подождать incremental pipeline tick (или вручную: MCP `trigger_pipeline(channel_id="<source>", force=true)`, ждать ~30-60s) | новый ProcessedDocument scored против interest |
| 3.3 | Если match с score ≥ 0.1 — push в R-1 | match-уведомление в канале |
| 3.4 | MCP: `list_watchlists()` | response без ValidationError, новый interest содержит `channel_id`, `target_kind="channel"`, `chat_id=null` |
| 3.5 | Cleanup: `unsubscribe_watchlist(interest_id=<id>)` | success=true |

> Если step 3.4 поднимает `pydantic.ValidationError` — это регрессия fix'а `WatchInterestInfo` (см. self-review note в коммите 3 PR #93). STOP, escalate как hotfix.

### P0-4 — Legacy chat-path regression (passive)

**Цель:** убедиться что новый dispatch `_publish_to_target(kind="chat")` не сломал legacy chat-таргет (BUG-028 regression guard).

| Шаг | Действие | Ожидание |
|---|---|---|
| 4.1 | (passive) Дождаться 06:00Z = 09:00 MSK 2026-05-25 — это T+20h | cron tick для **существующей** prod chat-подписки `digest_94483db9` (endocrinology) |
| 4.2 | Проверить: сообщение пришло в legacy chat | YES |
| 4.3 | `curl -s 'http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total' \| jq` | для chat-target счётчик **НЕ** инкрементируется (метрика только для channel-target — `_publish_to_target` ветвится) |
| 4.4 | `docker logs --since 1h tg_parser \| grep "digest_94483db9"` | clean run, no errors |

> На local-prod стэке `digest_94483db9` может отсутствовать (DB была пуста pre-migration). В таком случае P0-4 заменить на: до начала watch создать `subscribe_digest(name="watch_p0_4_legacy_chat", channel_ids=[...], chat_id=<test_chat>, cron_expression="*/5 * * * *")` и пронаблюдать первый tick.

---

## 2. P1 чеклист (high-value gap closure)

| ID | Действие | Команда | Валидирует |
|---|---|---|---|
| P1-1 | Bot natural-language: «Подпиши меня на ежедневный дайджест канала @durov_news, доставка в @MyDigest» | Telegram message → бот | `target_kind_semantics` prompt v1.7.0 → LLM резолвит в `target={kind:"channel", channel_id:"@MyDigest"}`, НЕ в legacy chat_id |
| P1-2 | Bot natural-language: «Подпиши меня на дайджест канала @durov_news» (без указания target) | Telegram message | Backward-compat fallback: bot должен взять `kind=chat, chat_id=<current_telegram_chat>` (per prompt v1.7.0 line 90) |
| P1-3 | MCP mutual-exclusion 422: `subscribe_digest(name="watch_p1_3", channel_ids=[...], chat_id=12345, target={"kind":"chat","chat_id":67890})` | MCP call | `success=false`, `message` содержит «mutually exclusive» (SubscriptionTargetConflictError) |
| P1-4 | CLI mutual-exclusion: `docker compose exec tg_parser tg-parser digest add --user <admin_uuid> --chat-id 12345 --channel-id @X --name "watch_p1_4" --channels @src` | CLI command | Typer error / exit-code != 0 с сообщением о взаимной исключительности |
| P1-5 | MCP `list_digests()` после P0-1/P0-2 (когда обе подписки ещё активны до cleanup) | MCP call | Response корректно показывает `target_kind` + либо `chat_id` либо `channel_id` для смешанных подписок |
| P1-6 | Idempotency target-swap: `subscribe_digest(name="watch_p1_6", channel_ids=[...], target={"kind":"chat","chat_id":777})` затем `subscribe_digest(name="watch_p1_6", channel_ids=[...], target={"kind":"channel","channel_id":"@X"})` | MCP × 2 | Вторая попытка: `created=false`, `changed_fields` содержит `["target_kind", "channel_id", "chat_id"]` (или подмножество) |

---

## 3. P2 monitoring loop (passive)

Опрашивать каждые ~4 часа в течение watch; результаты — в watch note секцию «24h watch observations» (создать при первом опросе).

| ID | Что | Как | Threshold |
|---|---|---|---|
| P2-1 | Latent BUG-029 (race-retry без rollback) | `docker logs --since 4h tg_parser \| grep -E "InFailedSQLTransactionError\|IntegrityError"` | 0 occurrences. ≥1 ⇒ escalate BUG-029 из follow-up в hotfix |
| P2-2 | Transient publish failures | `curl -s 'http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total{result="failed"}' \| jq` | 0 в установившемся режиме. ≥1 ⇒ проверить classification drift в `_CHANNEL_PUBLISH_PERMANENT_FRAGMENTS` |
| P2-3 | Uptime continuity | `curl -s 'http://localhost:9090/api/v1/query_range?query=up{job=~"tg_parser.*"}&start=<T+0>&end=<now>&step=15m' \| jq` | каждый bucket = 1 (учитывая что `tg_parser_bot` profile-gated, его 0 = expected) |
| P2-4 | 5xx на subscribe endpoints | `curl -s 'http://localhost:9090/api/v1/query?query=tg_api_requests_total{path=~"/api/v1/(digests\|watchlists).*",status=~"5.."}' \| jq` | 0 за всё окно. ≥1 ⇒ capture path+code, read logs |
| P2-5 | Reactivate flow (after P0-2) | После P0-2 повторить `subscribe_digest(name="watch_p0_2_denied", target={"kind":"channel","channel_id":"<R-1 — где бот admin>"})` | `is_active: false → true`, `changed_fields` содержит `is_active` |

---

## 4. Cursor Automations feasibility

**Резюме (per [Cursor Automations docs](https://cursor.com/docs/cloud-agent/automations)):** automations выполняются в cloud sandbox — **не имеют доступа к localhost** (Prometheus, postgres, tg_parser_bot DM). Доступны triggers (scheduled cron / GitHub / Slack / webhook / Linear / Sentry / PagerDuty) и actions (Open PR / Comment PR / Send Slack / MCP server / Memories).

| Item | Verdict | Rationale |
|---|---|---|
| P0-1 success path | **MANUAL** | требует Telegram MCP/bot + локальный admin status; cloud sandbox недоступен |
| P0-2 permission_denied | **MANUAL** | требует ручной подписки на сломанный канал + DM-проверка |
| P0-3 watchlist | **MANUAL** | требует подписки на live channel с активным document flow |
| P0-4 legacy chat regression | **MANUAL** | passive wait + ручная инспекция |
| P1-1..P1-2 bot NL | **MANUAL** | требует live Telegram chat с ботом |
| P1-3..P1-4 mutual-exclusion | **MANUAL** | one-shot tool/CLI call, проще руками |
| P1-5..P1-6 idempotency | **MANUAL** | требует чёткой последовательности MCP-вызовов с verify шагом |
| P2-1..P2-4 monitoring | **SEMI** (если Prometheus станет cloud-reachable) | сейчас MANUAL — Prometheus на localhost:9090, sandbox не достанет |
| **T+24h closure reminder** | **AUTOMATABLE** | scheduled cron trigger создаёт GitHub issue «Wave 1 step 4 watch closure due» с темплейтом |
| **Post-watch BUG-029 follow-up tracker** | **AUTOMATABLE** | GitHub PR-merged trigger на PR #93 → create issue для BUG-029 follow-up |

### Драфт `CreateAutomationRequest` для T+24h closure reminder

> ⚠️ **Caveat**: `workflow` shape — это «Automation Workflow proto JSON» (per descriptor); полный proto не задокументирован в публичных docs. Точная структура полей `triggers[].schedule`, `actions[].open_pull_request` etc. — частично восстановлена по docs (cursor.com/docs/cloud-agent/automations) и **может потребовать корректировки** через `build_automation_prefill_url` MCP tool, который откроет prefill-форму на cursor.com/automations для финального ручного review.

**Pre-existing automations:** `list_automations()` → `total=0` (пусто, нет precedent для shape).

**Рекомендованный flow для оператора:**
1. Не вызывать `create_automation` напрямую с этим драфтом.
2. Передать workflow JSON в `build_automation_prefill_url(workflow=...)` — получить URL.
3. Открыть URL → cursor.com автоматически разложит поля в UI → доработать триггер/permissions/repo/auth → save.

```json
{
  "name": "TG_parser Wave 1 step 4 — T+24h watch closure reminder",
  "description": "Scheduled reminder to run watch-closure session for Wave 1 step 4 (ADR 0008 polymorphic target). Creates a GitHub issue with closure template at T+24h.",
  "workflow": {
    "triggers": [
      {
        "schedule": {
          "cron": "35 9 25 5 *",
          "timezone": "UTC"
        }
      }
    ],
    "model": "claude-sonnet-4.5",
    "repositories": ["AlexEfimov/TG_parser"],
    "permissions": "private",
    "memoryEnabled": false,
    "agentOptions": {
      "openPullRequest": false
    },
    "actions": [
      {
        "open_github_issue": {
          "repo": "AlexEfimov/TG_parser",
          "title": "Wave 1 step 4 — watch closure due (T+24h reached)",
          "body_template": "Watch window opened 2026-05-24T09:54:35Z; T+24h reached. Per docs/notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md, run closure session covering: (1) up{} gap-detection, (2) tg_digest_channel_publish_total instant for success|permission_denied|failed, (3) 5xx scan on /api/v1/digests and /api/v1/watchlists, (4) BUG-029 follow-up creation. Finalize REVIEW_2026-05-24_WAVE1_STEP4_DONE.md."
        }
      }
    ],
    "prompt": "Open the watch closure GitHub issue using the provided body_template. Do not run any code, do not query metrics directly (Prometheus is on operator's localhost, not reachable from this sandbox). The operator will perform the actual closure check; this issue is a structured reminder only."
  }
}
```

Cron `35 9 25 5 *` = 2026-05-25T09:35Z (10 min earlier than nominal T+24h `09:54:35Z` — buffer for cloud agent spinup). При cancel/задержке watch — отключить automation вручную в UI.

---

## 5. GREEN closure criteria

`REVIEW_2026-05-24_WAVE1_STEP4_DONE.md` помечается GREEN ⇔ ВСЕ следующие условия выполнены:

| Critère | Метрика / артефакт | Threshold |
|---|---|---|
| C-1 | P0-1 выполнен | `tg_digest_channel_publish_total{result="success"}` ≥ 1 |
| C-2 | P0-2 выполнен | `{result="permission_denied"}` ≥ 1 + `is_active=false` row + DM получен |
| C-3 | P0-3 выполнен | watchlist channel-match доставлен; `list_watchlists` без ValidationError |
| C-4 | P0-4 без регрессии | legacy chat tick PASS; 0 errors в логах для existing chat-подписок |
| C-5 | P2-1 чисто | 0 `InFailedSQLTransactionError` за окно. Если ≥1 → BUG-029 hotfix-pri, GREEN откладывается |
| C-6 | P2-2 чисто | `{result="failed"}` = 0 (transient publish errors) |
| C-7 | P2-3 чисто | `up{api,mcp}` = 1 во всех bucket'ах (bot=0 OK, profile-gated) |
| C-8 | P2-4 чисто | 0 × 5xx на `/api/v1/(digests\|watchlists)` |
| C-9 | Watch note завершён | `docs/notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md` секция «24h watch observations» заполнена |
| C-10 | BUG-029 файл | `docs/notes/BUG_LOG.md` content для BUG-029 готов (даже если БЕЗ hotfix-приоритета) |

---

## 6. Escalation matrix

| Триггер | Действие | Куда документировать |
|---|---|---|
| `tg_digest_channel_publish_total{result="failed"}` ≥ 1 | Read logs, classify (transient retry vs real bug). Если classification drift в permanent-fragments — добавить fragment, патч в `digest_service.py:95`, новый bug | `BUG_LOG.md` + watch note |
| `InFailedSQLTransactionError` ≥ 1 | BUG-029 elevation из follow-up в hotfix. Подготовить one-line PR: `await session.rollback()` между failed `create()` и retry SELECT в `digest_service.py:265-272` | `BUG_LOG.md` BUG-029 update, new PR |
| ValidationError на `list_watchlists` для channel-target | Hotfix: проверить `WatchInterestInfo` Optional fields в `mcp_server.py` | `BUG_LOG.md`, new PR |
| 5xx на `/api/v1/digests` или `/api/v1/watchlists` ≥ 1 | Capture request, path, body, response. Read tg_parser logs за минуту до 5xx | `BUG_LOG.md`, watch note |
| `up{api}` или `up{mcp}` = 0 на любом bucket | STOP — деградация. `docker compose ps`, `docker logs`, healthcheck inspect | watch note блок «incidents», SOSE-style postmortem если > 5min |
| Любая регрессия `target.kind=chat` (legacy path) | **CRITICAL** — потенциальный rollback кандидат | `BUG_LOG.md` + IMMEDIATE escalation; `tg-parser db downgrade --db ingestion -1` ТОЛЬКО при ≥1 production пользователе affected и нет forward-fix path |

**Rollback** (emergency only): `docker exec tg_parser tg-parser db downgrade --db ingestion -1` — откатывает миграцию `a8b7c6d5e4f3 → f1a2b3c4d5e6`. Требует pg_restore из [`backups/pre_step4_backup_20260524T094610Z.sql`](../../backups/pre_step4_backup_20260524T094610Z.sql) если есть нежелательные `target_kind='channel'` rows. См. `downgrade()` в `migrations/versions/ingestion/20260524_wave1_step4_subscription_target.py` — guardrail: NOT NULL `chat_id` обязателен перед DROP `target_kind`.

---

## 7. Когда закрывать watch

* **Nominal close:** `2026-05-25T09:54:35Z` (T+24h).
* **Early close OK ⇔** C-1..C-10 все PASS до nominal T+24h, никаких open incidents.
* **Extended watch ⇔** любой P2 показал non-zero hit; продлить ещё +24h после fix.

После closure: финализировать `REVIEW_2026-05-24_WAVE1_STEP4_DONE.md` (verdict block + ссылка на этот runbook как использованный артефакт), обновить ADR 0008 история-row (acceptance verdict «GREEN at T+24h»), commit + push (одним коммитом `docs(watch): WAVE1 step 4 GREEN closure`).
