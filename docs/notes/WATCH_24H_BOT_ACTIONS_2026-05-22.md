# 24h Watch — Bot Actions (Manual, 2026-05-22)

**Назначение:** пополнить series `tg_pipeline_trigger_total{surface=bot}` и проверить
bot-side health (FSM, agent routing, confirmation flow) **ручным** вводом через
Telegram-бот. Этот файл — companion к `[WATCH_24H_ACTIVITY_PLAN_2026-05-22.md](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md)`;
MCP/HTTP действия там, бот — здесь.

**Time anchors:**

- T+0 = `2026-05-22T17:42:42Z` = `21:42 MSK 22-05` (`d143e5d`).
- Окно ручных bot-действий: **T+0 → T+15h** (~`12:42 MSK 23-05`).
- Closure-сессия запускается `~14:25 MSK 23-05` (T+16h43).

**Интерфейс бота:** свободный текст (Gemini-агент роутит в tools); единственные slash-команды — `/start`, `/help`. Любая bot-write операция требует подтверждения в чате (FSM `ConfirmFlow`). Команды ниже — **шаблоны на русском**; формулировки можно адаптировать (агент толерантен), главное — сохранить намерение и суффиксы.

---

## 1. Безопасность

- **Суффикс** всех создаваемых через бот артефактов — `_bot_watch_smoke` (отдельно от MCP/HTTP `_watch_smoke`), чтобы cleanup был детерминирован.
- **Не** запускайте `add_channel` / `remove_channel` / `pause_channel` / `resume_channel` через бот — ingestion baseline замёрз.
- **Не** дёргайте `set_llm_config` / `reset_llm_config` / `reload_prompts` — LLM прод замёрз.
- `trigger_pipeline` через бот — **только один раз** на `mind_rise` (хватит для series `surface=bot`).
- Если бот ответил подтверждением (preview) — отвечайте **«да»** или **«нет»** текстом, без слэша; не отправляйте новый запрос поверх preview (FSM сожрёт его).
- **Все артефакты удалить к T+14h30** (см. §3 Cleanup), чтобы успеть до T+15h45 hard cut-off из основного плана.

---

## 2. Расписание ручных bot-действий

> Время указано как ориентир — ±15 минут допустимо. Главное — попасть в окно T+0…T+14h30 и пройти всю последовательность.


| #   | Время (MSK) | T+N     | Команда / текст в чат                                                                                  | Ожидаемая реакция бота                                                                                     |
| --- | ----------- | ------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 1   | 22:12 22-05 | T+0h30  | `/start` → затем «Кто я?» → затем «Покажи каналы»                                                      | greeting + role; `whoami` → роль/access; `list_channels` → список с `mind_rise`, `genotek`, `AgeManagment` |
| 2   | 01:42 23-05 | T+4h00  | «Запусти обработку канала `mind_rise`» → подтвердить **«да»** на preview                               | `trigger_pipeline` → 200 / job dispatched; **series `tg_pipeline_trigger_total{surface="bot"}` +1**        |
| 3   | 06:42 23-05 | T+9h00  |                                                                                                        | `subscribe_watchlist` → 201; `tg_watchlist_subscribe_total{surface=bot}` +1                                |
| 4   | 08:42 23-05 | T+11h00 | «Покажи мои watchlists» → затем «Статус пайплайна для `mind_rise`»                                     | `list_watchlists` → виден `wl_bot_watch_smoke`; `get_pipeline_status` → job `done` (после T+4h trigger)    |
| 5   | 12:12 23-05 | T+14h30 | «Отпишись от watchlist `wl_bot_watch_smoke`» → подтвердить **«да»** → затем «Статус» / «Покажи каналы» | `unsubscribe_watchlist` → 204; финальная проверка bot-side health                                          |


**Итого:** 5 точек, покрывающих read (1, 4), write-with-confirm (2, 3, 5), bot health check.

---

## 3. Cleanup через бот (≤ T+14h30)


| #   | Действие                  | Команда                                                     |
| --- | ------------------------- | ----------------------------------------------------------- |
| 1   | Снять bot watchlist       | «Отпишись от watchlist `wl_bot_watch_smoke`» → «да»         |
| 2   | Проверить, что чисто      | «Покажи мои watchlists» → не должно быть `_bot_watch_smoke` |
| 3   | Финальная sanity-проверка | «Статус» / `/start` (FSM clear)                             |


Если бот вернул ошибку при отписке — записать в `BUG_LOG.md` и в closure-сессии под Open Items; не блокировать closure.

---

## 4. Чек-лист (для отметки выполнено)

- [x] T+0h30 — `/start` + whoami + list_channels (sanity baseline) — **executed 2026-05-22T19:45Z (23:45 MSK 22-05)**; `whoami` → admin (id `c59d42b4-…`, 13 owned), `list_channels` → 9 active.
- [x] T+4h00 — trigger_pipeline `mind_rise` через бот (подтверждено `да`) — **executed 2026-05-22T19:47:29Z → 19:47:39Z** (23:47 MSK 22-05); FSM flow: `agent_tool_call(trigger_pipeline, confirm=false)` → `fsm_confirm_armed` → user «да» → `fsm_confirm_execute(confirm=true)` → API-side `pipeline_trigger_queued`, `job_id=33ffa1b2-d426-4282-9883-83a6edee98e1`, `job=full_pipeline`. **NB: `tg_pipeline_trigger_total{surface=bot}` NOT incremented** — bot dispatches through API → counter records `surface=api` (architectural gap, see § 6 Observations).
- [x] T+9h00 — subscribe_watchlist `wl_bot_watch_smoke` — **executed 2026-05-22T19:54:38Z** (23:54 MSK 22-05) **but WITHOUT confirm flow** (subscribe_watchlist is not in `_WRITE_TOOLS_REQUIRING_CONFIRM` per current design — TD-bot-confirm-coverage-completeness); `watchlist_id=604632d4-23e9-4e50-a992-80aeefb9cf74`, `is_active=true` at creation.
- [x] T+11h00 — list_watchlists + get_pipeline_status — **executed 2026-05-22T19:56:43Z + 20:03:46Z**; `list_watchlists` returned 9 items (`wl_bot_watch_smoke` visible), `get_pipeline_status(mind_rise)` returned active + `last_success_at` advanced post-T+4h trigger.
- [x] T+14h30 — unsubscribe `wl_bot_watch_smoke` + cleanup of leftover smoke watchlists — **executed 2026-05-22T19:57Z … 20:08Z** (23:57 MSK 22-05 … 00:08 MSK 23-05). Successful deletes (by UUID): `385b4b41-…` (S3 smoke) at 19:59:57Z, `abfbfbf9-…` (Idem 1779449293) at 20:01:34Z, `604632d4-…` (wl_bot_watch_smoke) at 20:08:26Z. **Failed deletes** (passed name instead of UUID — see BUG-025): `_smoke_post91_…` (19:57:53Z), `S3 smoke` (19:59:15Z), `wl_bot_watch_smoke` (20:07:41Z) — all surfaced `tool_execution_error` (asyncpg invalid UUID).
- [x] Финальный `/start` / «Статус» (FSM clear, sanity) — **executed 2026-05-22T20:10:03Z** (00:10 MSK 23-05); `get_pipeline_status` returned all 9 channels active, `mind_rise.last_success_at = 2026-05-22T20:01:20Z` (post bot-triggered run from 19:47Z completed cleanly).

---

## 5. Примечания

- Если бот не зарегистрировал вас — сначала просите админа `register_user` через MCP, иначе `/start` ответит «Вы не зарегистрированы».
- Если preview-confirmation истёк (TTL 5 минут) — повторите команду, бот пере-сгенерит preview.
- Если `trigger_pipeline` вернул 409 `JobAlreadyRunning` — нормально, series инкрементировался; идём дальше.
- Точные формулировки можно подстроить под реальную лексику бота — Gemini-агент толерантен к синонимам; **главное — намерение и суффикс** `_bot_watch_smoke`.
- Если вы используете только slash-команды (`/start`, `/help`) — этого **недостаточно** для bot-side series; нужен хотя бы один natural-language `trigger_pipeline` (точка #2).

---

## 6. Observations (post-session, 2026-05-23)

Полный execution log — 22-05 23:45 → 23-05 00:10 MSK. Cross-check выполнен по `docker logs tg_parser_bot` / `tg_parser` (API) и Prometheus snapshot. Подробности — в [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` § 7](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md) (строка T+2h00…T+2h25).

### 6.1 Classification of dialog turns

| Turn (MSK) | Bot action | Classification | Evidence |
|---|---|---|---|
| 23:45 | `whoami` + `list_channels` (read) | **OBSERVED & EXPECTED** | bot log `agent_tool_call` 19:45:23.798Z / 19:45:38.485Z |
| 23:47 | `trigger_pipeline(mind_rise)` + «да» | **OBSERVED & EXPECTED** (FSM-confirm flow works) | bot log `fsm_confirm_armed` (19:47:30Z) → `fsm_confirm_execute(confirm=true)` (19:47:39Z); API log `pipeline_trigger_queued/started` with `job_id=33ffa1b2-d426-4282-9883-83a6edee98e1`, **`surface=api`** (NOT `surface=bot` — architectural gap, see § 6.2) |
| 23:54 | `subscribe_watchlist(wl_bot_watch_smoke, …)` | **OBSERVED & EXPECTED** (subscribe не behind FSM-confirm by current design) | bot log `agent_tool_call` 19:54:38Z, single-shot execution; `subscribe_watchlist` is not in `_WRITE_TOOLS_REQUIRING_CONFIRM` set (`tg_parser/bot/tools.py:48-58`) — tracked as TD-bot-confirm-coverage-completeness per BUG-009 Session G runbook |
| 23:56 | «покажи мои подписки» → digests only | **UX NOTE** (different intent, not a bug) | bot called `list_digests` (19:56:05Z), not `list_watchlists` — «подписки» Russian polysemy (digests/watchlists/users) — LLM disambiguation choice; **not filed as bug** (low impact, easily worked around by saying «watchlists» explicitly) |
| 23:57 | `list_watchlists` → 9 items shown | **OBSERVED & EXPECTED** | bot log `agent_tool_call` 19:56:43Z |
| 23:58 | `unsubscribe_watchlist(interest_id="_smoke_post91_20260522T174541Z")` → asyncpg invalid UUID error | **UX BUG (BUG-025)** | bot log `tool_execution_error` 19:57:53Z; LLM passed name as UUID; `_exec_unsubscribe_watchlist` has no pre-validation → raw asyncpg traceback leaks to user as «invalid input for query argument $1» |
| 23:58 | `unsubscribe_watchlist("1eac40cd-…")` → «Не удалось … Возможно, он уже неактивен» | **UX BUG (BUG-027)** | bot log `agent_tool_call` 19:58:32Z; DB confirms target was already `is_active=f` since 2026-05-22 17:45:43Z (≈ 6h before user attempt); service returned `(deleted=False, error="delete failed (already inactive?)")` per `watchlist_service.py:697` — wording is parenthesised question, conflates with «not found» |
| 23:59 | `unsubscribe_watchlist("S3 smoke")` → «ID должен быть в формате UUID» | **UX BUG (BUG-025 variant)** | bot log `tool_execution_error` 19:59:15Z; same root cause as 23:58 invalid-UUID — LLM passed name; surfaced error wording differs because Gemini paraphrases asyncpg error |
| 00:00 | `unsubscribe_watchlist("385b4b41-…")` (quoted UUID) | **OBSERVED & EXPECTED** | bot log `agent_tool_call` 19:59:57Z, no error; DB `updated_at=2026-05-22 19:59:57.96303+00`, `is_active=f` ✓ |
| 00:01 | «удали watchlist Idem» → bot suggests candidate UUID | **OBSERVED & EXPECTED** (bot did list_watchlists at 20:00:45Z and returned candidate) | bot log `agent_tool_call(list_watchlists)` 20:00:45Z → `gemini_response` with suggestion text |
| 00:01 | user pastes standalone `abfbfbf9-…` (UUID alone, no verb) → «Я не понимаю …» | **UX BUG (BUG-026)** | bot log 20:01:05Z `user_message text_length=36` → `gemini_response` 47 output tokens, **no `agent_tool_call`** — LLM did not resume delete intent; no FSM-tracked «pending-target-id» context for write-tool continuations (analogue of `_READ_TOOLS_TRACKED_FOR_CONTEXT` exists for read-tools per BUG-011 Session H, but no symmetric mechanism for write-tool target IDs) |
| 00:01 | «Удали watchlist "abfbfbf9-…"» (explicit verb) | **OBSERVED & EXPECTED** | bot log `agent_tool_call(unsubscribe_watchlist, interest_id="abfbfbf9-…")` 20:01:34Z; DB `updated_at=2026-05-22 20:01:34.111604+00`, `is_active=f` ✓ |
| 00:02 | «покажи активные watchlists» → 6 active, footer «Показано 6 из 9» | **OBSERVED & EXPECTED** (math correct: 6 active + 3 inactive at that moment) | bot log `agent_tool_call(list_watchlists)` 20:02:17Z; DB cross-check confirms 6 owner-active rows at 20:02Z (cumulative 3 deletes by this point: `385b4b41`, `abfbfbf9`, plus pre-existing `1eac40cd`) |
| 00:07 | `unsubscribe_watchlist("wl_bot_watch_smoke")` (by name) → error | **UX BUG (BUG-025, third occurrence in same session)** | bot log `tool_execution_error` 20:07:41Z — same root cause |
| 00:08 | `unsubscribe_watchlist("604632d4-…")` (correct UUID) → SUCCESS | **OBSERVED & EXPECTED** (user-driven delete of `wl_bot_watch_smoke`) | bot log `agent_tool_call` 20:08:26Z; DB `updated_at=2026-05-22 20:08:26.659627+00`, `is_active=f` ✓ |
| 00:09 | «Покажи неактивные watchlists» → 4 inactive incl `wl_bot_watch_smoke` ← initially perceived as «unexpected auto-deactivation» | **REFUTED — NOT A BUG** | DB cross-check: `wl_bot_watch_smoke` `is_active=f`, `updated_at=2026-05-22 20:08:26.659627+00`. User had **just deleted it themselves 1 minute earlier** (00:08 MSK by UUID). Initial dialog read assumed it was auto-deactivated; reading bot logs in sequence shows the user delete event. No background scheduler / deactivation hook fires within 15 min of creation; the F11 «orphan interest auto-deactivation» mechanism only fires when bot is blocked by user's `chat_id` (see `user-tg-parser` MCP description). |
| 00:10 | «Статус» — все 9 channels active, mind_rise `last_success_at=2026-05-22T20:01:20Z` | **OBSERVED & EXPECTED** | bot log `agent_tool_call(get_pipeline_status)` 20:10:04Z; cross-confirms successful completion of bot-triggered pipeline run |

### 6.2 surface=bot Prometheus series — STILL EMPTY (architectural gap)

**Целевая метрика §1 row «`tg_pipeline_trigger_total{surface=bot}` ≥ 1» НЕ выполнена** даже после bot-triggered pipeline run at 23:47 MSK.

Reason (verified by `docker logs tg_parser` API container at 19:47:39Z):

```
{"job_id": "33ffa1b2-…", "channel_id": "mind_rise", "job": "full_pipeline",
 "surface": "api", "force": false, "event": "pipeline_trigger_queued", ...}
```

Bot's `_exec_trigger_pipeline` dispatches via HTTP `POST /api/v1/pipeline/trigger` against the loopback API; the API entry point in `tg_parser/api/routes/pipeline.py` increments `tg_pipeline_trigger_total` with **`surface=api`** label hardcoded at the counter site. The originating client (bot/MCP/HTTP) is not propagated as a label.

**Same architectural cause as the `surface=mcp` anomaly #2** in T+14h46 row (catch-up MCP triggers). Both `surface=mcp` and `surface=bot` series are structurally unreachable without a counter-registration refactor (either propagate originating-surface header through HTTP API, or have bot/MCP wrappers increment their own counter pre-dispatch). 

**Disposition:** report in closure-session under Open Items together with `surface=mcp` gap as a single architectural concern. Not blocking closure; not a regression (counter has worked correctly with `surface=api` throughout the watch window).

### 6.3 wl_bot_watch_smoke — explicit cleanup status

- **Created:** 2026-05-22 19:54:38.10235+00 (23:54 MSK 22-05) via bot, `subscribe_watchlist(title=wl_bot_watch_smoke, …)`, `watchlist_id=604632d4-23e9-4e50-a992-80aeefb9cf74`.
- **Deleted:** 2026-05-22 20:08:26.659627+00 (00:08 MSK 23-05) via bot, `unsubscribe_watchlist(interest_id="604632d4-…")` (correct UUID after preceding name-attempt failed).
- **Final state:** `is_active=f`, soft-deleted; row preserved per F11 soft-delete contract.
- **Cleanup at planned closure step (§ 5 of activity-plan T+15h00):** no action needed for `wl_bot_watch_smoke` — already deleted by user mid-session. Cleanup at T+15h00 will still address `wl_watch_smoke` / `digest_watch_smoke` (MCP-created artifacts).

### 6.4 BUG findings filed

- **BUG-025** — Bot `unsubscribe_watchlist` does not pre-validate UUID format; LLM passing watchlist name as `interest_id` causes raw asyncpg traceback to leak. Severity: Medium. Surface: bot. See [`BUG_LOG.md` § BUG-025](BUG_LOG.md).
- **BUG-026** — Bot context loss on standalone UUID continuation after «did you mean X?» bot prompt — LLM does not resume previous delete intent. Adjacent class to BUG-011 (read-context for `channel_id`) but no symmetric mechanism for write-tool target IDs. Severity: Low. Surface: bot. See [`BUG_LOG.md` § BUG-026](BUG_LOG.md).
- **BUG-027** — Bot soft-delete return wording «Не удалось удалить … Возможно, он уже неактивен» conflates «not found in DB» (which doesn't fire — `interest_repo.get` returned a row) and «found but already inactive» (the actual case). Severity: Low. Surface: bot. See [`BUG_LOG.md` § BUG-027](BUG_LOG.md).
- **REFUTED:** «wl_bot_watch_smoke auto-deactivated within 15 min of creation» — not a bug; user-driven delete by UUID at 00:08 MSK preceded the «покажи неактивные» query at 00:09 by 1 minute.
- **NOT FILED:** «Показано 6 из 9» footer math — verified correct (6 active + 3 inactive at the moment of query).

