# START PROMPT — Conversational-layer: D1 (delete_suggest re-resolve) + D2 (FSM intent-break)

**Дата:** 2026-06-01 · **Автор контекста:** перенос из «уставшего» окна (71% контекста).
**Прошлый transcript (для справки, не цитировать пользователю дословно):** `9bdeb3bf-6301-4dc0-b4af-576764a29dcb`.
**Предыдущий start-prompt серии:** `docs/notes/START_PROMPT_FIX_BUG039_042_CONVERSATION_LAYER_2026-05-31.md`.

> Рабочий режим: **Multitask Mode** (асинхронные subagents, `run_in_background: true`). Коммит — только по явному запросу пользователя (AGENTS.md). Деплой/мерж — только с отмашкой. Каждый смоук пользователь гоняет вручную в живом Telegram и присылает транскрипт.

---

## 1. Где мы сейчас (состояние на 2026-06-01 ~01:52 UTC+4)

Закрыт и **смержен в `main`** весь кластер разговорного слоя:

| Bug | Что | PR | merge SHA | Прод-подтверждение |
|---|---|---|---|---|
| BUG-039..042 + ревью-хардненинг | clarify-dead-end, stateless misroute, LLM-нормализация канала, cron-truncation | #158 | `a1dd040` | смоук clean |
| G2 / BUG-045 | subscribe not-found → «да» уезжал в `list_topics`, терялся доп.канал | #158 | `a1dd040` | смоук clean |
| G1 / BUG-046 | delete/unsubscribe confirm «да»/«yes» dead-end → детерминированный confirm-контракт для `unsubscribe_digest`/`unsubscribe_watchlist` | #161 | `712cf00` | смоук clean |

**`main` HEAD = `712cf00`.**

### В работе: BUG-047 — детерминированная delete-маршрутизация
- **PR #162** — branch `fix/bug047-delete-routing`, base `main`. **OPEN, НЕ смержён.**
- Коммиты на ветке:
  - `9f427bb` — MVP (B-1 owner-scoped name-резолвер в `unsubscribe_*`; B-2 контекст «последней подписки» `LastSubscriptionData`; B-3 delete/anaphora pre-router `_handle_delete_prerouter`; prompt **v1.7.5**).
  - `7148d6b` — фикс «да»-dead-end на первой fuzzy-подсказке: `delete_suggest` clarify (`_SUGGEST_FUZZY_CUTOFF=0.5`, `_build_delete_suggest_clarify`, `_route_delete_match`, `_handle_delete_suggest_selection`).
- **Прод сейчас задеплоен на `7148d6b`** (Variant B). Rollback-точка: `9f427bb`.
- CI на #162: `Test Python 3.12` ✅ green. `Lint Documentation` 🔴 — **известный non-blocker** (репо-вайд markdown link-checker, не required; падает на пред-существующих битых ссылках, в т.ч. мёртвый grafana-URL).

### Что подтверждено РАБОЧИМ в проде (ре-смоук `7148d6b`)
- Анафора «удали эту подписку» → confirm-preview на последнюю → confirm → delete. ✅
- Голое имя «удали Ежечасный дайджест Genotek» → delete confirm-preview (не subscribe). ✅
- «удали подписку на канал genotek» → «Возможно, вы имели в виду «Ежечасный дайджест Genotek»? Ответьте «да»…» → «да» → confirm-preview → confirm → delete. ✅ (целевой `delete_suggest` фикс)
- «нет»/«no» отмена; «ok»/«да»/«yes» подтверждение — все классифицируются. ✅
- G2/BUG-045, BUG-043, BUG-046 не регрессировали. ✅

---

## 2. ДВА ОТКРЫТЫХ ДЕФЕКТА (план = вариант A: сначала D1 → мерж #162, потом D2 отдельным PR)

### D1 — dead-end на «другом имени» внутри `delete_suggest` (НАШ код, гэп фикса `7148d6b`) — БЛОКИРУЕТ мерж #162
**Симптом (ре-смоук 01:41:11→01:41:17):**
```
bot: Подписка «Genotek» не найдена. Возможно, вы имели в виду «Ежечасный дайджест Genotek»? Ответьте «да», чтобы удалить её, пришлите другое название или «нет» для отмены.
user: lf                       (прислал ДРУГОЕ имя вместо «да»)
bot: Подписка с названием «lf» не найдена. Ближайшее совпадение: «wl_watch_smoke».   ← НЕактивно, FSM НЕ армлен
user: да
bot: Я не совсем понимаю ваш ответ…   ← DEAD-END (G1-класс)
```
**Корень:** в `delete_suggest` ветке «прислать другое название» (`_handle_delete_suggest_selection` / `_route_delete_match`, `tg_parser/bot/handlers.py` ~`1461`/`1542`) повторный резолв присланного имени, если у него есть near-miss, выдаёт **неактивный** not-found «Ближайшее совпадение: X» и **не ре-армит** `delete_suggest`. Асимметрия: первый проход армится (`tools.py` resolver), повторный — нет.
**Фикс (в ветке `fix/bug047-delete-routing`, БЕЗ мержа/деплоя воркером):**
- Повторный резолв присланного имени должен идти ровно тем же путём, что и первый: single near-miss → ре-армить `delete_suggest` (actionable «Ответьте да…»); >1 → `delete_disambig`; zero+no-suggestion → чистый not-found с **очисткой FSM** (snapshot-restore `read_context`/`last_subscription`), чтобы случайное «да» было inert.
- **Failing-first тест** в `tests/test_bot_delete_routing_bug047.py`: suggest-clarify → присылаем другое имя с near-miss → assert FSM ре-армлен и следующее «да» ведёт в confirm-preview (не opaque fallback). Red на `7148d6b` → green после фикса.
- Регресс-гварды зелёные: анафора, bare-name, первая подсказка, G2/BUG-043/BUG-046.
**После D1:** ре-деплой нового tip (Variant B, rollback `7148d6b`) → пользовательский ре-смоук (фокус: suggest → другое имя → «да») → **мерж #162** (squash, после green `Test Python 3.12`).

### D2 — СИСТЕМНЫЙ FSM-wedge (пред-существующий, Severe) — ОТДЕЛЬНЫЙ PR (вероятно BUG-048)
**Симптом (ре-смоук 01:42:01→01:44:01):** armed `ClarifyFlow` (subscribe channel-not-found) и `ConfirmFlow` **жадно потребляют любое следующее сообщение**:
```
(после того как «Ежечасный дайджест Genotek» без delete-глагола ушло в subscribe channel-clarify)
01:42:01 user: удали Ежечасный дайджест Genotek  → bot: «Не понял ваш ответ. Подтвердите…»   (proглочено pending ConfirmFlow как confirm-токен)
…channel-ClarifyFlow заклинило…
01:42:44 user: удали Ежечасный дайджест Genotek  → bot: «Канал «удали Ежечасный дайджест Genotek» не найден в базе…»
01:43:08 user: удали подписку Ежечасный …        → bot: «Канал «удали подписку …» не найден…»
01:43:29 user: покажи подписки на дайджесты       → bot: «Канал «покажи подписки…» не найден…»
01:44:01 user: какие у тебя есть подписки         → bot: «Канал «какие у тебя…» не найден…»
```
Любой ввод съедается как «имя канала» / «confirm-токен»; выход только «нет».
**Корень (системный лейтмотив всей серии, BUG-039/040):** armed FSM (ClarifyFlow channel-kind, ConfirmFlow) **не уступает место явному НОВОМУ интенту** (команда-глагол `удали/создай/покажи/...`, вопрос), а потребляет сообщение как название/токен. Не регресс BUG-047 (channel-clarify мы не трогали) — дыра была в проде и раньше.
**Подход к D2 (новый PR, начинать с investigation+design, как для BUG-047):**
1. Read-only расследование: перечислить ВСЕ surfaces, где armed FSM греется (`tg_parser/bot/handlers.py` `handle_text` dispatch ~`329-350`; `ConfirmFlow` `_handle_confirmation_response`; `ClarifyFlow` subscribe/read/`delete_suggest`/`delete_disambig`; `PaginationFlow`). Где и как «съедается» новый интент.
2. Дизайн **intent-break / escape**: если входящее сообщение — явная новая команда (delete/create/show/list verb) или вопрос, armed clarify/confirm должен **отпускаться** (или ре-роутиться), а не потреблять ввод. Аккуратно с «именами», которые легитимно совпадают с глаголами; сохранить G2/BUG-043/BUG-046/BUG-047 поведение на их законных surface.
3. Failing-first тесты на каждый wedge-сценарий + регресс-гварды.
4. Деплой → смоук → мерж.

---

## 3. Прод / деплой / инфра (нормативно)

- **VPS:** `ssh -p 2296 user@212.72.189.15`, репо `~/TG_parser`.
- **Деплой (Variant B):** `git fetch origin <branch>` → checkout → `git reset --hard <SHA>` → `docker compose up -d --build` → **обязательно** `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` (бот под профилем `bot` — обычный `up` его НЕ пересоздаёт). Верифицировать `git rev-parse HEAD == <SHA>`, здоровье контейнеров, наличие нового кода в running-контейнере, чистые стартап-логи. Это правки только bot-Python/prompts/tests/docs → **миграций нет**.
- **Runbooks:** `docs/runbooks/BOT_LLM_FALLBACK.md`, `docs/notes/DEPLOY_CHECKLIST_SESSION_F_2026-04-30.md`, `PRODUCTION_DEPLOYMENT.md` § Updating.
- **CI gate:** required = `Test Python 3.12`. `Lint Documentation` (markdown link-checker) — НЕ required, красный на пред-существующих ссылках → игнор, если только он.
- **ruff:** CI пиннут `ruff==0.15.11`. Локальный `0.12.7` даёт ложный `UP038` и пропускает `format --check` → **всегда** гонять `uvx ruff@0.15.11 format --check . && uvx ruff@0.15.11 check .` перед коммитом. (Локально стоит обновить до 0.15.11.)
- **Известный пред-существующий non-blocker:** `tg_parser_grafana` крэш-лупит из-за битого `provisioning/.../wave1_step4.yaml` (contact point `cursor-watch-webhook` без `url`, мёртвый `https://grafana.tgp.efimov.mobi`). К боту отношения нет. Отдельный мелкий ops-тикет (не начат).

## 4. Ключевые файлы
- `tg_parser/bot/agent.py` — `process_message` (stateless `contents`, ~`197-199`), read-context инъекция (~`481-496`), `write_intent_this_turn` guard (~`314`), `mode="AUTO"`.
- `tg_parser/bot/handlers.py` — `handle_text` dispatch (~`329-350`), `_handle_confirmation_response`, `_handle_clarification_response` (kinds: `subscribe`/`read`/`delete_disambig`/`delete_suggest`, dispatch ~`696`), `_handle_delete_prerouter`, `_route_delete_match` (~`1461`), `_handle_delete_suggest_selection` (~`1542`), `_is_stale`/`READ_CONTEXT_TTL_SECONDS` (~`70`/`1103`).
- `tg_parser/bot/tools.py` — `unsubscribe_digest`/`unsubscribe_watchlist` декларации+executors (confirm-gate, name-резолвер `resolve_subscription_by_name`/`_match_subscription_items`/`_build_delete_disambig_clarify`/`_build_delete_suggest_clarify`, `_SUGGEST_FUZZY_CUTOFF=0.5`, `_NO_RESULTS_FUZZY_CUTOFF=0.7`), `_WRITE_TOOLS_REQUIRING_CONFIRM`, `_reject_nonexistent_channel`/`_build_subscribe_clarify_pending` (G2), `_build_read_clarify_pending` (BUG-043).
- `tg_parser/bot/states.py` — `ReadContextData`, `LastSubscriptionData`, FSM-группы (`ConfirmFlow`/`ClarifyFlow`/`PaginationFlow`).
- `prompts/bot.yaml` — **v1.7.5** (BUG-041 channel-norm hard rule; delete-семантика).
- `docs/notes/BUG_LOG.md` — backbone; записи до BUG-047 (status in-progress на #162).
- Тесты: `tests/test_bot_delete_routing_bug047.py`, `tests/test_bot_unsubscribe_confirm_gate_g1.py`, `tests/test_bot_conversation_layer_bug039_042.py`, `tests/test_bot_confirm_flow.py`, `tests/test_f11_bot_tools.py`, `tests/test_cron_humanize.py`.

## 5. Первое действие в новом окне
Подтвердить план (вариант A) и запустить **шаг D1**: background-воркер с задачей пофиксить re-resolve dead-end в `delete_suggest` на ветке `fix/bug047-delete-routing` (failing-first тест, прогон под `uvx ruff@0.15.11`, коммит+push, БЕЗ мержа/деплоя), затем — CI-gate → ре-деплой (Variant B, rollback `7148d6b`) → пользовательский ре-смоук → мерж #162. После — D2 отдельным PR (investigation+design сначала).

**Конвенции (AGENTS.md):** ветка `main`; не коммитить без явного запроса; не создавать `docs/methodology/**`; не править `pyproject.toml`/`requirements.txt` без запроса; ADR (`docs/adr/`) и контракты (`docs/contracts/`) нормативны.
