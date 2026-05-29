# Handoff for next chat — Wave 1 step 4 post-watch follow-up

**Created:** 2026-05-25T14:30Z (~T+27h от момента открытия watch window `2026-05-24T10:50:10Z`).
**Purpose:** continue Wave 1 step 4 post-watch BUG-fix work в новом Cursor chat без потери context.
**Watch window:** **CLOSED** at `2026-05-25T10:50:10Z` (commit `209637f` запушен в `origin/main`).

---

## 1. Current state

| Аспект | Состояние |
|---|---|
| Wave 1 step 4 main work | merged в PR **#93** (commit `926a165`) |
| Watch-closure commit | `209637f` pushed to `origin/main` |
| Prod stack | **healthy** — prod digest `digest_94483db9` доставлен сегодня `2026-05-25T06:00:05Z` в `chat_id=5445781511` |
| Alembic head | `a8b7c6d5e4f3` |
| Cursor automations | 3 остались (1 active `7b35ca01` incident-webhook, 2 disabled single-shot — `2bd25769`, `f93e557a`) |
| Findings filed | **7 BUGs + 1 OBS + 1 DOC** (BUG-029..037, OBS-001, DOC-001) |
| BUG-029, BUG-030 | **STUBS** в `BUG_LOG.md` — нужно flesh out (high priority, low effort) |
| BUG-031..037 | full descriptions present, ready для fix-PR session |
| Branch | `main`, ahead 0 (pushed) |

---

## 2. Agreed priority order

(Per operator decision **2026-05-25T18:24Z UTC+4** — three phases, smallest blast radius first.)

### Phase 1 — Quick wins (~30-60 min total)

#### 1.1. DOC-001 — trivial fix

* **File:** [`docs/prompts/DEV_RESURRECTION_PROMPT.md`](../prompts/DEV_RESURRECTION_PROMPT.md), **line 26**.
* **Change:** `@smoke_tgparser_bot` → `@Tgingest_bot` (production bot username, id `8657845219`).
* **Tests:** none needed (docs-only one-line edit).
* **Cross-ref:** `BUG_LOG.md` § DOC-001 (already filed 2026-05-24).

#### 1.2. BUG-029 detail fill-in

* **File:** [`tg_parser/services/digest_service.py`](../../tg_parser/services/digest_service.py), **lines 263-284** (verify — current snapshot shows `try / except IntegrityError` block at exactly these lines).
* **What:** race-retry branch re-attempts `find_by_owner_and_name` + `_apply_digest_upsert` после `IntegrityError` **БЕЗ предварительного** `await session.rollback()` — это оставляет `AsyncSession` в "aborted transaction" state и роняет последующие операции с `PendingRollbackError`.
* **Action для next chat:**
  1. Re-read lines 263-284 in `digest_service.py` to confirm exact code shape (file evolves — line numbers may drift).
  2. Write detailed BUG-029 entry в `docs/notes/BUG_LOG.md` covering:
     * **exact code excerpt** (`except IntegrityError:` block + the missing `await session.rollback()` insertion point);
     * **why CI didn't catch** — no concurrent-update test exists for `subscribe_digest`; existing tests serialize all subscribe calls;
     * **proposed fix** — insert `await session.rollback()` immediately after the `logger.info("digest.subscribe_race_retry_update", ...)` log line and BEFORE `find_by_owner_and_name`; add регрессионный unit-test that fires two concurrent `subscribe_digest` calls with same `(owner_id, name)` через `asyncio.gather` and asserts both either succeed-as-update or one raises a typed error (no `PendingRollbackError` leak).
  3. Update BUG_LOG.md entry (currently filed as stub on `2026-05-25T06:22Z`).

#### 1.3. BUG-030 detail fill-in

* **File:** [`tg_parser/bot/main.py`](../../tg_parser/bot/main.py), **lines 285-340** (verify — `_start_digest_scheduler` async function with un-retried `try / except Exception:` at lines 306-311 in current snapshot).
* **What:** initial-load DB read (`async with digest_subscription_repo() as (repo, _db): active = await repo.list_active()`) catches **bare `Exception`** and falls through to `active = []` on Postgres startup race. Recovery happens only via 60s reconcile-loop — between bot start and первый reconcile tick scheduler runs с пустым job-set. Self-healing within ~60s наблюдалось эмпирически 2026-05-24T10:46:40Z (см. WATCH_WINDOW evidence row in BUG_LOG.md).
* **Action для next chat:**
  1. Re-read lines 285-340 in `bot/main.py` to confirm exact code shape.
  2. Write detailed BUG-030 entry в `BUG_LOG.md` covering:
     * **exact code excerpt** (the `try / except Exception:` at lines 306-311);
     * **why CI didn't catch** — no compose-startup-ordering test that exercises `bot` container booting against still-migrating `postgres` container; всё CI запускает Alembic upgrade synchronously before bot start;
     * **proposed fix** — wrap initial-load read с `tenacity.AsyncRetrying(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=15), retry=retry_if_exception_type((OperationalError, InterfaceError)))` — backoffs 2-3-5-10-15s; на финальном failure → `logger.critical("digest_scheduler_initial_load_exhausted_retries", ...)` instead of silent `active = []`; also narrow `except Exception` → `except (OperationalError, InterfaceError, DatabaseError)` so schema-shape errors (`IntegrityError` on half-migrated table SELECT) fail loud.
  3. Update BUG_LOG.md entry (currently filed as stub on `2026-05-25T06:22Z`).

**Phase 1 acceptance:** все три pungs (DOC-001 fix + BUG-029 stub fleshed out + BUG-030 stub fleshed out) → single commit + push (docs + BUG_LOG only; нет source code changes на этом шаге).

---

### Phase 2 — Critical bot regressions (fix PRs, ~2-4 hours total)

**Каждый BUG = отдельный PR** (или BUG-pair если tightly coupled, см. ниже).

#### 2.1. BUG-033 (**CRITICAL** — fix FIRST in Phase 2)

* **Symptom:** bot inserts `chat_id=123` placeholder в `subscribe_digest` arg payload когда NL intent issued из группового чата (e.g. user пишет «Подпиши этот чат на дайджест» в `vps-watch-test-grp`); вместо реального `update.message.chat.id = -5279672667` подставляется хардкод `123` → создаётся подписка которая невозможна для доставки.
* **Discovery:** search for the hardcoded `123` value before deciding на shape of the fix:
  ```bash
  rg "chat_id\s*=\s*123" tg_parser/bot/
  rg "['\"]chat_id['\"]\s*:\s*123" tg_parser/bot/
  rg "\b123\b" tg_parser/bot/ | rg -v test
  ```
* **Likely path:** `tg_parser/bot/handlers/` or `tg_parser/bot/conversations/` — NL flow для `subscribe_digest` когда вызывается из группы (не DM).
* **Fix:** в handler для `subscribe_digest` NL intent → правильно резолвить chat target из `update.message.chat.id` когда `target_kind="chat"` и контекст groupchat; убрать placeholder `123` из default args / fixture seed.
* **Regression test:** `tests/test_bot_chat_target_resolution.py`:
  * DM context → `chat_id == update.message.chat.id` (positive `user_id`);
  * group context → `chat_id == update.message.chat.id` (negative `-100...`);
  * never falls back to `123`.
* **Severity:** blocks broader bot rollout — fix **BEFORE** any UX expansion.

#### 2.2. BUG-034

* **Symptom:** operator typed «pro fendocrinologist» (с пробелом) → bot нормализовал в `pro_fendocrinologist` (с подчёркиванием) вместо распознавания исходного намерения `profendocrinologist` (валидный канал) ИЛИ rejection с clarification prompt.
* **Likely path:** source-channel parser в `tg_parser/bot/` или `tg_parser/services/` — поиск `replace(" ", "_")` / username sanitization helper.
* **Fix options (choose one or combine):**
  * **(a)** reject typo input с clarification prompt («Канал `pro fendocrinologist` не найден — вы имели в виду `profendocrinologist`?»);
  * **(b)** normalize whitespace away (concat `"".join(text.split())`), NOT to underscore;
  * **(c)** fuzzy match against existing source channels (Levenshtein ≤ 2) + ask if ambiguous.
* **Recommended:** Layer A (executor pre-validation regex `^[a-zA-Z][a-zA-Z0-9_]{4,31}$` + `get_source_by_username` existence check) + Layer B (prompt v1.7.x hard rule «never replace spaces with underscores»). See BUG_LOG.md § BUG-034 «Proposed fix» for full text.
* **Regression test:** `tests/test_bot_channel_name_parser.py`:
  * typo `"pro fendocrinologist"` → rejection OR correct normalization to `profendocrinologist`;
  * double-space `"pro  fendocrinologist"` → same;
  * leading/trailing whitespace → strip;
  * exact match `"profendocrinologist"` → pass-through.

#### 2.3. BUG-031 + BUG-032 (confirmation flow refactor — **bundle в один PR**)

* **BUG-031:** bot создаёт DB row для подписки **ДО** того как спросит «Подтвердите [да/нет]» → нарушает `/help` invariant «записи только после явного подтверждения».
* **BUG-032:** bot не парсит «да» / «подтверждаю» / «yes» / «ok» / «ок» как confirmation tokens → даже если ordering исправить, FSM застревает на confirm step.
* **Likely files:** search for `ConfirmFlow` class и `subscribe_digest` handler в `tg_parser/bot/`:
  ```bash
  rg "ConfirmFlow|awaiting_confirmation" tg_parser/bot/
  rg "не совсем понимаю" tg_parser/bot/
  ```
* **Fix:**
  * BUG-031: ensure `subscribe_digest` MCP call происходит **AFTER** user confirms в чате (move side-effect inside the «yes» branch of confirm dispatcher; preview message не должен touch DB).
  * BUG-032: expand affirmative whitelist to `{"да", "yes", "y", "подтверждаю", "ok", "ок", "согласен", "согласна", "хорошо", "+", "👍"}` (case-insensitive, whitespace-stripped); negative whitelist `{"нет", "no", "n", "отмена", "cancel", "отказ", "не подтверждаю", "стоп", "-", "👎"}`.
* **Regression tests:**
  * `tests/test_bot_confirm_flow.py` — accept paths («да», «подтверждаю», «yes», «ok», «ок»), reject paths («нет», «cancel», «отмена»), unknown token → typed `UnknownConfirmationToken` error (not opaque «не совсем понимаю»);
  * write-before-confirm regression: assert `subscribe_digest` MCP call NOT issued до того как user reply detected as «affirmative».

---

### Phase 3 — Architectural hotfix (~1-2 hours)

#### 3.1. BUG-035

* **Symptom:** `unsubscribe_digest` MCP tool удаляет DB row, но APScheduler in-memory job продолжает существовать and fires once на следующем cron tick (empirically bounded to ≤1 fire в окне ~2 min между delete и next reconcile tick).
* **Likely files:**
  * `tg_parser/services/background_scheduler.py` / `tg_parser/services/scheduler_service.py`;
  * `unsubscribe_digest` MCP tool implementation in `tg_parser/services/digest_service.py`.
* **Fix:** когда `unsubscribe_digest` deletes the row → также вызвать `scheduler.remove_job(job_id)` **синхронно** before returning (within same MCP call). Job-ID convention is `digest:<subscription_id>` (see `register_digest_subscription`).
* **Symmetry check:** same fix likely applies к `unsubscribe_watchlist` — verify в `WatchInterestService` и применить тот же паттерн (один PR может покрыть оба, либо два PR с одинаковым shape).
* **Regression test:** `tests/test_scheduler_invalidation_on_unsubscribe.py`:
  * subscribe digest с cron `*/1 * * * *` → wait → unsubscribe → wait one cron interval → assert no delivery happened, Prometheus `tg_digest_channel_publish_total` не инкрементируется;
  * same flow for watchlist.

---

## 3. Key reference paths and IDs

| Item | Value |
|---|---|
| Last commit | `209637f docs(wave1-step4): watch window closure...` |
| Branch | `main` (ahead 0 — pushed) |
| PR (Wave 1 step 4) | #93 (merged at `926a165`) |
| Alembic head | `a8b7c6d5e4f3` |
| Watch note | [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) |
| Watch handoff (prev chat) | [`docs/notes/HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) |
| Closure review | [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) |
| BUG_LOG | [`docs/notes/BUG_LOG.md`](BUG_LOG.md) — BUG-029..037 entries present; 029/030 are stubs |
| ADR | [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) |
| Bot prompts | `prompts/bot.yaml` v1.7.0 (`target_kind_semantics` section) |
| Post-closure cleanup | [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) |
| VPS SSH | `ssh -p 2296 user@212.72.189.15` |
| VPS MCP | `https://mcp.tgp.efimov.mobi/mcp` (Bearer auth в `~/.cursor/mcp.json` под `tg-parser` desktop session) |
| VPS Grafana | `https://grafana.tgp.efimov.mobi` |
| Bot username | `@Tgingest_bot` (id `8657845219`) |
| Real owner chat_id | `5445781511` (S-2 — **НЕ использовать в тестах**) |
| Real prod digest | `94483db9-9351-4f99-9aec-46949d9ddd09` (S-1 — **НЕ трогать**) |
| Test fixtures (persistent reuse) | R-1: `@vps_watch_test_r1_Alex` (bot admin), R-2: `@vps_watch_test_r2_Alex` (bot **не** member), group: `vps-watch-test-grp` chat_id `-5279672667` (bot admin) |

---

## 4. What NOT to do (anti-patterns)

* **НЕ** трогать `digest_94483db9` real prod subscription (S-1).
* **НЕ** использовать `chat_id=5445781511` для test subscriptions (S-2 — это owner real prod user'а).
* **НЕ** удалять / модифицировать 3 оставшиеся Cursor automations (1 active, 2 disabled — keep as-is для audit trail).
* **НЕ** push в `main` без operator sign-off на каждый PR.
* **НЕ** bundle multiple BUG-fixes в один PR — **one PR per BUG** (исключение: BUG-031 + BUG-032 идут вместе, т.к. ConfirmFlow refactor — tightly coupled).
* **НЕ** skip writing tests — каждый fix требует минимум один regression test (per code style в AGENTS.md).
* **НЕ** модифицировать `pyproject.toml` / `requirements.txt` без operator request (workspace forbidden action из AGENTS.md). Исключение: если BUG-030 fix реально требует `tenacity` — operator confirm требуется отдельным шагом.
* **НЕ** создавать `docs/methodology/**` файлы в этом workspace (workspace forbidden action).

---

## 5. Suggested initial prompt для нового chat

Скопировать целиком в новый Cursor chat:

```text
@docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md

Продолжаем Wave 1 step 4 post-watch follow-up. Watch window closed
2026-05-25T10:50:10Z, commit 209637f запушен.

Начинаем с Phase 1 (quick wins):
1.1. DOC-001 — @smoke_tgparser_bot → @Tgingest_bot
     в docs/prompts/DEV_RESURRECTION_PROMPT.md:26
1.2. BUG-029 detail fill-in — digest_service.py:263-284
1.3. BUG-030 detail fill-in — bot/main.py:285-340

После Phase 1: commit + push, потом Phase 2 (BUG-033 первым, как CRITICAL).

Multitask Mode ON.
```

---

## 6. Open infra TODOs (parallel, low priority)

* **Grafana password rotation** (operator-manual; per [`WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) § C).
* **Provision Grafana rules as code** — full BUG-036 fix; самостоятельная step-5 задача (alert rules currently configured через UI, не in repo).
* **Investigate OBS-001** — `watch_interests.last_checked_at` stuck с 11:48 UTC, без видимого функционального impact'а; separate spike, не блокирует Phase 1-3 BUG fixes.

---

## 7. Documentation reading order (для full context перед началом работы)

1. **Этот handoff** (top-down read) — primary entry point.
2. [`docs/notes/BUG_LOG.md`](BUG_LOG.md) — § BUG-029..037, OBS-001, DOC-001 (текущие entries, BUG-029/030 stubs).
3. [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) — full empirical evidence trail from 24h watch.
4. [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) — closure review marker.
5. [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) — оставшиеся cleanup steps (§ C Grafana password).
6. [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — ADR underlying step 4 (важно для BUG-033 chat-target context).
7. [`AGENTS.md`](../../AGENTS.md) — workspace conventions + forbidden actions reminder.
