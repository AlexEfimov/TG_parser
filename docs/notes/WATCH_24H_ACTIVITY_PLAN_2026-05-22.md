# 24h Watch Activity Plan — Wave 1 Step 3 (2026-05-22)

**Назначение:** план конкретных MCP / прямых HTTP действий на время 24h окна
watch step 3, чтобы по closure-сессии (~14:25 MSK 23-05) у нас были
**ненулевые** series по всем целевым метрикам и чистый log scan.

**Окно (UTC):** OPEN `2026-05-22T11:25:47Z` → CLOSE `~2026-05-23T11:25:47Z`.
**T+0 точка отсчёта расписания** — deploy follow-ups: `2026-05-22T17:42:42Z` = `21:42 MSK` (`d143e5d`).
**Closure-сессия запускается:** `~14:25 MSK 23-05` ⇒ T+16h43m от follow-ups.
**Эффективное окно исполнения:** **T+0 → T+15h45m** (`~13:27 MSK 23-05`); за T+15h45 — только closure-prep, без новых артефактов.

> **Bot actions вынесены в отдельный файл** [`WATCH_24H_BOT_ACTIONS_2026-05-22.md`](WATCH_24H_BOT_ACTIONS_2026-05-22.md) — ручное исполнение пользователем через Telegram-бот для пополнения series `tg_pipeline_trigger_total{surface=bot}` и проверки bot-side health.

Связано: [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) (tracker, не редактировать), [`START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-23.md`](START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-23.md) (closure-промпт), [`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md`](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md) (handoff).

---

## 1. Цель и таргет-метрики

| Сигнал | Тип | Что хотим увидеть на closure |
|---|---|---|
| `up{service="api"}` | gauge (range) | **Без gap'ов** > 1 scrape (15s) подряд за всё окно |
| `tg_idempotency_keys_hit_total{result="hit"}` | counter | **≥ 2** инкремента (два HTTP-replay окна: watchlist + digest) |
| `tg_idempotency_keys_hit_total{result="miss"}` | counter | **≥ 2** (первичные POST'ы HTTP-окон) |
| `tg_idempotency_keys_hit_total{result="mismatch"}` | counter | **≥ 2** (mismatch-сценарии в обоих окнах) |
| `tg_idempotency_keys_table_size` | gauge | Ненулевой; видны изменения после T+1h cleanup (`0 * * * *`) |
| `tg_pipeline_trigger_total{job="parse_pipeline",result="ok",surface="mcp"}` | counter | **≥ 1** на `mind_rise` |
| `tg_pipeline_trigger_total{job="topicization",result="ok",surface="mcp"}` | counter | **≥ 1** на `genotek` |
| `tg_pipeline_trigger_total{job="link_topics",result="ok",surface="mcp"}` | counter | **≥ 1** на `AgeManagment` |
| `tg_pipeline_trigger_total{surface="bot"}` | counter | **≥ 1** — покрывается [`WATCH_24H_BOT_ACTIONS_2026-05-22.md`](WATCH_24H_BOT_ACTIONS_2026-05-22.md) |
| `/api/v1/(watchlists\|digests\|pipeline/trigger)` log scan | grep | **Пусто** по `error|5xx|exception` (известные 409/422/429 — не блокер) |

---

## 2. Безопасность

- **Все** созданные через MCP/HTTP артефакты — с суффиксом `_watch_smoke` (watchlist title, digest name, workspace name). На cleanup (§ 5) удалить только их. Bot-side артефакты используют отдельный суффикс `_bot_watch_smoke` (см. companion-файл).
- **Никаких** `add_channel` / `remove_channel` / `pause_channel` / `resume_channel` — ingestion baseline не трогаем.
- **Никаких** `set_llm_config` / `reset_llm_config` / `reload_prompts` — LLM-конфиг прода замёрз на время watch.
- `trigger_pipeline` — **только** на каналы из smoke (`mind_rise`, `genotek`, `AgeManagment`), и по одному вызову на канал (если 409 `JobAlreadyRunning` — норм, переходим дальше).
- HTTP-вызовы с `Idempotency-Key` — на новые `_watch_smoke` объекты, не на чужие.
- **Все действия завершить к T+15h45 (~13:27 MSK 23-05)**; за этим — только closure-session prep (тихий мониторинг, без новых артефактов).

---

## 3. Расписание (T+N от `2026-05-22T17:42:42Z` = `21:42 MSK`)

| Время (MSK) | T+N | Действие | Ожидаемая метрика / лог |
|---|---|---|---|
| 21:57 22-05 | T+0h15 | MCP read-only baseline sweep (whoami / list_channels / list_topics / list_workspaces / get_pipeline_status) | `up=1` стабилен; baseline counters |
| 23:12 22-05 | T+1h30 | Пассивный мониторинг: проверить `tg_idempotency_keys_table_size` после `0 * * * *` cleanup tick (T+1h) | gauge изменился (если в БД были stale-ключи) |
| 00:42 23-05 | T+3h00 | MCP `subscribe_watchlist` (`wl_watch_smoke`) + `subscribe_digest` (`digest_watch_smoke`); **HTTP window-1** (watchlists): miss → hit → mismatch | `tg_watchlist_subscribe_total` +1; `tg_digest_subscribe_total` +1; `result=miss/hit/mismatch` +1/+1/+1 |
| 03:42 23-05 | T+6h00 | MCP `trigger_pipeline` на `mind_rise` | `tg_pipeline_trigger_total{job=parse_pipeline,surface=mcp}` +1 |
| 05:42 23-05 | T+8h00 | MCP `trigger_topicization` на `genotek` (off-peak) | `tg_pipeline_trigger_total{job=topicization,surface=mcp}` +1 |
| 07:42 23-05 | T+10h00 | MCP `trigger_link_topics` на `AgeManagment` | `tg_pipeline_trigger_total{job=link_topics,surface=mcp}` +1 |
| 09:42 23-05 | T+12h00 | MCP workspace CRUD: `create_workspace(ws_watch_smoke)` → `add_workspace_source(mind_rise)` → `list_workspace_sources` → `rename_workspace` → `remove_workspace_source`; затем `search_knowledge_base(mode=hybrid)` + `ask_question(mode=semantic)` | workspace lifecycle логи без exception; search/ask 200 |
| 10:42 23-05 | T+13h00 | **HTTP window-2** (digests): POST с `Idempotency-Key=K2` → miss → replay → hit → mismatch → 422 | `result=miss/hit/mismatch` ещё +1/+1/+1 |
| 11:42 23-05 | T+14h00 | MCP `export_channel(channel_id=<mind_rise>, level=raw, format=json)` → polled `get_export_status` | export job done, ingestion не задета |
| 12:42 23-05 | T+15h00 | **CLEANUP** (§ 5) + final MCP read-only sweep | `_watch_smoke` artifacts удалены; `get_pipeline_status` — все job'ы `done`; `list_workspaces` / `list_watchlists` / `list_digests` без `_watch_smoke` |
| 13:27 23-05 | T+15h45 | **Жёсткий cut-off** — никаких новых артефактов, только пассивный мониторинг до closure | — |
| 14:25 23-05 | T+16h43 | **Closure session can start** | — |

---

## 4. Конкретные команды / вызовы

### MCP (Cursor MCP `project-0-TG_parser-tg-parser`)

```jsonc
// T+0h15 — baseline (read-only)
whoami{} ; list_channels{} ; list_topics{"limit":20} ; list_workspaces{} ; get_pipeline_status{}

// T+3h00 — subscribe watchlist + digest (MCP-сторона; HTTP-сторона ниже)
subscribe_watchlist{"title":"wl_watch_smoke","channel_ids":["mind_rise","genotek"],
  "chat_id":<твой_chat_id>,"keywords":["health","longevity"],"threshold":0.6,
  "description":"24h watch smoke — DELETE on cleanup"}
subscribe_digest{"name":"digest_watch_smoke","channel_ids":["mind_rise"],
  "chat_id":<твой_chat_id>,"cron_expression":"0 9 * * *","timezone":"Europe/Moscow","format":"summary"}

// T+6h00 / T+8h00 / T+10h00 — surface=mcp pipeline triggers (по одному на канал)
trigger_pipeline{"channel":"mind_rise"}            // T+6h00
trigger_topicization{"channel":"genotek"}          // T+8h00
trigger_link_topics{"channel":"AgeManagment"}      // T+10h00

// T+12h00 — workspace CRUD (создание → членство → переименование → разотрыв) + search/ask
create_workspace{"name":"ws_watch_smoke","description":"24h watch"}
add_workspace_source{"workspace_id":"<ws_id>","channel_id":"<mind_rise_id>"}
list_workspace_sources{"workspace_id":"<ws_id>"}
rename_workspace{"workspace_id":"<ws_id>","new_name":"ws_watch_smoke_renamed"}
remove_workspace_source{"workspace_id":"<ws_id>","channel_id":"<mind_rise_id>"}
search_knowledge_base{"query":"longevity biomarkers","mode":"hybrid","limit":5}
ask_question{"question":"What recent insights on epigenetic clocks?","mode":"semantic"}

// T+14h00 — export raw + poll
export_channel{"channel_id":"<mind_rise_id>","level":"raw","format":"json","from_date":"2026-05-21T00:00:00Z"}
get_export_status{"job_id":"<export_job_id>"}
```

### Telegram bot

Все bot-действия (включая bot-side `trigger_pipeline` для `surface=bot` series) — в companion-файле [`WATCH_24H_BOT_ACTIONS_2026-05-22.md`](WATCH_24H_BOT_ACTIONS_2026-05-22.md). Этот план их не дублирует.

### Прямой HTTP на VPS (через SSH) — генерация `result=hit`/`mismatch` series

> MCP не выставляет `Idempotency-Key` header, поэтому `hit`/`mismatch` метрика
> подымается **только** прямыми `curl` через VPS-loopback.

```bash
# Пре-сетап на VPS (один раз)
ssh -p 2296 user@212.72.189.15
API_KEY=$(docker compose -f ~/TG_parser/docker-compose.yml exec -T tg_parser python3 -c \
  'import json,os; print(next(iter(json.loads(os.environ["API_KEYS"]).keys())))')
BASE=http://127.0.0.1:8000/api/v1 ; CHAT=<твой_chat_id> ; H="X-API-Key: $API_KEY"

# T+3h00 — HTTP window-1 (watchlist): miss → hit → mismatch
K1=$(uuidgen); B1='{"title":"wl_http_smoke","channel_ids":["mind_rise"],"chat_id":'$CHAT'}'
curl -sS -X POST "$BASE/watchlists" -H "$H" -H "Idempotency-Key: $K1" -H "Content-Type: application/json" -d "$B1"  # 201 miss
sleep 60
curl -sS -X POST "$BASE/watchlists" -H "$H" -H "Idempotency-Key: $K1" -H "Content-Type: application/json" -d "$B1"  # created:false hit
sleep 60
curl -sS -X POST "$BASE/watchlists" -H "$H" -H "Idempotency-Key: $K1" -H "Content-Type: application/json" \
  -d '{"title":"wl_http_smoke_DIFF","channel_ids":["mind_rise"],"chat_id":'$CHAT'}'                                  # 422 mismatch

# T+13h00 — HTTP window-2 (digest): miss → hit → mismatch
K2=$(uuidgen); B2='{"name":"d_http_smoke","channel_ids":["mind_rise"],"chat_id":'$CHAT',"cron_expression":"0 9 * * *","timezone":"UTC","format":"summary"}'
curl -sS -X POST "$BASE/digests" -H "$H" -H "Idempotency-Key: $K2" -H "Content-Type: application/json" -d "$B2"      # 201 miss
sleep 60
curl -sS -X POST "$BASE/digests" -H "$H" -H "Idempotency-Key: $K2" -H "Content-Type: application/json" -d "$B2"      # hit
sleep 60
curl -sS -X POST "$BASE/digests" -H "$H" -H "Idempotency-Key: $K2" -H "Content-Type: application/json" \
  -d '{"name":"d_http_smoke","channel_ids":["mind_rise","genotek"],"chat_id":'$CHAT',"cron_expression":"0 9 * * *","timezone":"UTC","format":"summary"}'  # 422 mismatch
```

---

## 5. Cleanup перед closure (≤ T+15h00)

| # | Действие | Команда |
|---|---|---|
| 1 | Снять watchlist (MCP) | `unsubscribe_watchlist(interest_id=<wl_watch_smoke id>)` |
| 2 | Снять digest (MCP) | `unsubscribe_digest(subscription_id=<digest_watch_smoke id>)` |
| 3 | Удалить workspace (если осталось после T+12h CRUD) | `delete_workspace(workspace_id=<ws_watch_smoke id>)` |
| 4 | DELETE HTTP-watchlist (curl на VPS) | `curl -X DELETE "$BASE/watchlists/<wl_http_smoke id>" -H "X-API-Key: $API_KEY"` → 204 |
| 5 | DELETE HTTP-digest | `curl -X DELETE "$BASE/digests/<d_http_smoke id>" -H "X-API-Key: $API_KEY"` → 204 |
| 6 | Проверить состояние jobs | `get_pipeline_status` — `parse_pipeline / topicization / link_topics` все `done`, нет `running` |
| 7 | Проверить, что `_watch_smoke` ушло | `list_watchlists`, `list_digests`, `list_workspaces` — пусто на эти суффиксы |
| 8 | Кросс-проверить bot-side cleanup | `list_watchlists`, `list_digests` — `_bot_watch_smoke` тоже пусто (см. companion-файл §Cleanup) |

Если что-то не удаляется — **записать в closure-сессии под Open Items**, не блокировать closure.

---

## 6. Что НЕ делать

- **LLM:** `set_llm_config` / `reset_llm_config` / `reload_prompts` — конфиг прода замёрз.
- **Channel CRUD:** `add_channel` / `remove_channel` / `pause_channel` / `resume_channel` — ingestion baseline не трогаем.
- **Force-resummarize:** `force_resummarize` — не дёргаем, может сбить counter.
- **User CRUD:** `register_user` / `update_user` / `add_user_auth` / `remove_user_auth` — auth surface замёрз.
- **Массовый hammer rate-limit:** 429+`Retry-After` уже подтверждён в immediate smoke; не нужно генерить >1 burst.
- **Изменения LLM provider/модели** через env или MCP — без вариантов.
- **Прямые SQL DELETE / UPDATE на проде** — никаких ручных вмешательств в БД.
- **Деплои / rebuild / `docker compose build`** — прод уже на `d143e5d`, ничего пересобирать не нужно.
- **Любые новые артефакты после T+15h45** — окно закрыто, до closure только пассивный мониторинг.

---

## 7. Журнал выполнения (опциональный)

| T+N | Действие | ✅/❌/— | Заметка |
|---|---|---|---|
| T+0h15 | MCP baseline sweep | [x] | `2026-05-22T19:27Z` (23:27 MSK 22-05) · target=**MCP `user-tg-parser` (prod, `mcp.tgp.efimov.mobi`)** · `whoami=admin c59d42b4 (13 owned)`; `list_channels=9 active` (raw 312–3465, coverage 80–99%); `list_workspaces=3`; `list_watchlists=8` (5 prod + 3 smoke remnants: `S3 smoke 1779449293`, `Idem 1779449293` (active, chat_id=999001), `_smoke_post91_…` (inactive)); `list_digests=1`; `list_topics?limit=10 total=642`; `get_pipeline_status(mind_rise)=active, fail_count=0, last_success=2026-05-22T18:50:06Z`. **Anomaly:** 2 active smoke-remnant watchlists с chat_id=999001 (от immediate smoke); удалить в § 5 cleanup или оставить — не блокер. **MCP target verdict:** `project-0-TG_parser-tg-parser` (workspace stdio) указывает на **локальную пустую БД** (admin `00000000…`, 0 channels); сweep выполнен через `user-tg-parser` (user-level HTTPS bearer) — клейкий prod. |
| T+1h30 | passive monitor: idempotency table_size after T+1h tick | [x] | `2026-05-22T19:31Z` (23:31 MSK 22-05) · target=**SSH + `docker exec tg_parser_prometheus`** · `tg_idempotency_keys_table_size{service=api}=**3**` (non-zero ✓; cleanup tick `0 * * * *` уже отработал на 19:00Z), `{service=mcp}=0`, `{service=bot}=0`; `tg_idempotency_keys_hit_total{service=api}` = `miss:**2**, hit:**2**, mismatch:**1**` — соответствует immediate smoke residue at T+0. Target series ненулевые на api, mcp/bot пустые (ожидаемо: hit/miss поднимаются только HTTP-окнами). **Anomaly:** нет. |
| T+3h00 | subscribe_watchlist + subscribe_digest + HTTP window-1 (miss/hit/mismatch) | | |
| T+6h00 | trigger_pipeline mind_rise | | |
| T+8h00 | trigger_topicization genotek | | |
| T+10h00 | trigger_link_topics AgeManagment | | |
| T+12h00 | workspace CRUD + search/ask | | |
| T+13h00 | HTTP window-2 (miss/hit/mismatch) | | |
| T+14h00 | export_channel raw mind_rise | | |
| T+15h00 | CLEANUP (§ 5) + final sweep — clean state | | |
| T+15h45 | hard cut-off, passive monitor only | | |
