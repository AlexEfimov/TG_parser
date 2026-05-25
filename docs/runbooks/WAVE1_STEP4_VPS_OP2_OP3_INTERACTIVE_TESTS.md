# Runbook — Wave 1 Step 4 VPS Watch Window: OP-2 / OP-3 INTERACTIVE TESTS

**Last updated:** 2026-05-24 (during active VPS watch window opened `2026-05-24T10:50:10Z`, T+24h close `2026-05-25T10:50:10Z`).

**Audience:** оператор во время открытого watch window — выполняет interactive (через MCP + Telegram UI) тесты для материализации step-4 метрик и валидации bot prompt v1.7.0 `target_kind_semantics`.

**Estimated total effort:** ~20-30 минут полного прохода (PRE + A + B + C + D), +5-10 минут на бонус E (M-4 watchlist).

**Safety:** см. § 0 «SAFETY preamble» в [`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) (S-1…S-7). Особенно **S-1** (не трогать `digest_94483db9`), **S-2** (не использовать `chat_id=5445781511`), **S-5** (только operator-owned test channels).

**Source for steps:** разворачивает M-2/M-3/M-4 (§ 1 в [`WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md)) + M-6 (P1-1/P1-2 bot NL) в interactive script с зависимостями + порядком выполнения.

---

## Priority и зависимости

| # | Шаг | Приоритет | Зависит от | Время |
|---|---|---|---|---|
| PRE | Pre-flight: env vars + R-1 + R-2 + bot DM + OPERATOR_CHAT_ID | MUST (без него остальное blocked) | — | 10-15 мин |
| A | M-2 — Channel-publish SUCCESS (`tg_digest_channel_publish_total{result="success"}≥1`) | ⭐⭐⭐ MUST | PRE (R-1, KB_CHANNEL) | 5 мин |
| B | M-3 — Channel-publish DENIED (`{result="permission_denied"}≥1` + soft-deactivate + fallback DM) | ⭐⭐ HIGH | PRE (R-2, DM), желательно после A | 5 мин |
| C | P1-1 — Bot NL для channel target (validates `target_kind_semantics`) | ⭐⭐ HIGH | PRE (R-1, DM), независимо от A/B | 3-5 мин |
| D | P1-2 — Bot NL для chat target | ⭐⭐ HIGH | PRE (OPERATOR_CHAT_ID, DM), независимо от A/B/C | 3 мин |
| E | M-4 — Watchlist channel target (`WatchInterestInfo` schema + match delivery) | ⭐ MEDIUM | PRE (R-1, KB_CHANNEL) | 5-10 мин |
| FIN | Записать результаты в watch note | MUST | A/B/C/D/E завершены | 2 мин |

---

## PRE — Pre-flight (10-15 минут, MUST)

### PRE-1. Env vars (если ещё не сделано)

```bash
# Local Mac ~/.zshrc должно содержать (из § 1.7 operator manual):
echo "$TG_PARSER_WATCH_WEBHOOK" | head -c 50
echo "$TG_PARSER_WATCH_WEBHOOK_AUTH" | head -c 30
# должны быть непусты
```

### PRE-2. MCP клиент готов

Cursor → проверить, что `tg-parser` MCP server подключён и отвечает:

```text
list_digests()
```

✅ Acceptance: возвращает `count=1` с `digest_94483db9`. Если 401/403 — токен в `~/.cursor/mcp.json` истёк, обновить.

### PRE-3. Создать R-1 (test channel где бот = admin)

1. Telegram → New Channel → Name «vps-watch-test-r1», Type Private или Public (любой)
2. Add Subscribers → найти username prod бота → Add
3. Channel Settings → Administrators → "+" → выбрать бота → permissions: **Post Messages ✓** (минимум; остальные optional)
4. Сохранить
5. Записать identifier:
   * Если Public: `R1_CHANNEL="@vps_watch_test_r1"` (точное @ username)
   * Если Private: открыть info → копировать link или ID (формат `-100...`)

```bash
# Запиши локально как переменную для удобства:
R1_CHANNEL="@vps_watch_test_r1"   # или "-1001234567890"
```

✅ Acceptance: бот в списке Administrators канала с галочкой Post Messages.

### PRE-4. Создать R-2 (test channel где бота НЕТ)

1. Telegram → New Channel → Name «vps-watch-test-r2»
2. **НЕ добавлять бота** в members
3. Записать identifier: `R2_CHANNEL="@vps_watch_test_r2"`

✅ Acceptance: бот **НЕ** в Subscribers/Administrators канала.

### PRE-5. Warmup DM с ботом

1. Открыть в Telegram DM с prod ботом
2. Отправить `/start` (если новый чат) или `/help`
3. Бот должен ответить

✅ Acceptance: бот реагирует на команды.

### PRE-6. OPERATOR_CHAT_ID

Из DM → отправить `/whoami` (если бот поддерживает) ИЛИ форвардить любое сообщение из DM боту → переслать в `@userinfobot` → он покажет твой numeric ID.

```bash
OPERATOR_CHAT_ID="<your_numeric_id>"
# проверить, что НЕ совпадает с 5445781511 (real prod user)
[[ "$OPERATOR_CHAT_ID" == "5445781511" ]] && echo "STOP: same as real user" || echo "OK"
```

✅ Acceptance: знаешь свой `OPERATOR_CHAT_ID` ≠ `5445781511`.

### PRE-7. Baseline Prometheus counters (snapshot ДО тестов)

```bash
ssh -p 2296 user@212.72.189.15 \
  'docker exec tg_parser_prometheus wget -qO- \
   "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total" 2>/dev/null'
```

Запиши baseline (обычно `{"data":{"result":[]}}` если ещё не было ни одного channel-publish event — это OK, после A и B counter появится впервые).

---

## A — M-2 Channel-publish SUCCESS path (5 минут, ⭐⭐⭐ MUST)

**Цель:** материализовать `tg_digest_channel_publish_total{result="success"} ≥ 1` через real prod stack.

### A-1. Subscribe

В Cursor MCP клиенте:

```text
subscribe_digest(
  name="vps_watch_p0_1_success",
  channel_ids=["profendocrinologist"],
  target={"kind": "channel", "channel_id": "@vps_watch_test_r1"},
  cron_expression="*/2 * * * *",
  language="ru",
  format="summary"
)
```

Замени `@vps_watch_test_r1` на свой `R1_CHANNEL`.

**Acceptance:** возвращает success c `subscription_id`. Запиши:
```bash
SUB_M2="<uuid>"
```

### A-2. Wait

Ждать **3 минуты** wall-clock (минимум один tick `*/2`, плюс buffer на dispatch).

### A-3. Verify — channel получил digest

Открыть `R1_CHANNEL` в Telegram → последнее сообщение от бота должно быть свежий summary digest эндокринологии (timestamp в окне A-1 + 0..3 мин).

✅ Acceptance: digest пришёл; нет error-сообщений в R-1.

### A-4. Verify — Prometheus counter

```bash
ssh -p 2296 user@212.72.189.15 \
  'docker exec tg_parser_prometheus wget -qO- \
   "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total%7Bresult%3D%22success%22%7D" 2>/dev/null' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(r) for r in d['data']['result']]"
```

✅ Acceptance: `value` ≥ 1 (counter материализовался).

### A-5. CLEANUP — отписать

```text
unsubscribe_digest(subscription_id="<SUB_M2>")
```

✅ Acceptance: success; повторный `list_digests()` не показывает `vps_watch_p0_1_success`.

---

## B — M-3 Channel-publish DENIED path (5 минут, ⭐⭐ HIGH)

**Цель:** материализовать `{result="permission_denied"} ≥ 1` + проверить soft-deactivation + fallback DM в operator.

### B-1. Subscribe (на канал где бот НЕ admin)

```text
subscribe_digest(
  name="vps_watch_p0_2_denied",
  channel_ids=["profendocrinologist"],
  target={"kind": "channel", "channel_id": "@vps_watch_test_r2"},
  cron_expression="*/2 * * * *",
  language="ru",
  format="summary"
)
```

```bash
SUB_M3="<uuid>"
```

### B-2. Wait 3 минуты

### B-3. Verify — R-2 ПУСТ

Открыть `R2_CHANNEL` → **никакого сообщения** от бота быть не должно.

### B-4. Verify — fallback DM пришёл в operator

Открыть DM с prod ботом → должно быть свежее сообщение типа:
> «I tried to publish to @vps_watch_test_r2 but I'm not admin there — soft-deactivating subscription `vps_watch_p0_2_denied`»

(точный текст зависит от impl в `tg_parser/services/digest_service.py:_publish_to_target` fallback branch)

### B-5. Verify — soft-deactivation в DB

```text
list_digests()
```

Найти entry `vps_watch_p0_2_denied` (или прямой id `SUB_M3`):
* ✅ `is_active == false` (soft-deactivated)
* ✅ `target_kind == "channel"`, `channel_id == "@vps_watch_test_r2"`

### B-6. Verify — Prometheus counter

```bash
ssh -p 2296 user@212.72.189.15 \
  'docker exec tg_parser_prometheus wget -qO- \
   "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total%7Bresult%3D%22permission_denied%22%7D" 2>/dev/null' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(r) for r in d['data']['result']]"
```

✅ Acceptance: `value` ≥ 1.

### B-7. CLEANUP

```text
unsubscribe_digest(subscription_id="<SUB_M3>")
```

(уже soft-deactivated, но удаление row важно — не оставлять test mess в DB).

---

## C — P1-1 Bot NL для channel target (3-5 минут, ⭐⭐ HIGH)

**Цель:** проверить, что `prompts/bot.yaml v1.7.0` `target_kind_semantics` секция корректно дизамбигуирует **channel target** из natural language.

### C-1. В DM с ботом — warmup

`/help` → бот отвечает help-меню.

### C-2. NL prompt

Отправить **дословно или близко по смыслу**:

> Хочу получать дайджест в канал @vps_watch_test_r1 раз в час про эндокринологию

(подставить свой R1_CHANNEL)

### C-3. Diaolog с ботом

Бот может:
* (a) сразу confirm subscription;
* (b) спросить clarification (например «какие источники?»)
  * → ответить: `profendocrinologist`
* (c) спросить cron подтвердить
  * → `да` / `каждый час подойдёт`

Финальный confirmation от бота должен включать что-то типа:
> Created subscription **«название»** to channel @vps_watch_test_r1 with cron `0 * * * *` (каждый час) for sources [profendocrinologist]

✅ Acceptance: бот САМ выбрал `target_kind=channel` без явного указания пользователем — **на основе слов «в канал @username»**.

### C-4. Verify через MCP

```text
list_digests()
```

Найти свежую запись (по name или recent createdAt):
* ✅ `target_kind == "channel"`
* ✅ `channel_id == "@vps_watch_test_r1"`
* ✅ `chat_id == null` (правильно — channel target)

Запиши `SUB_C` id.

### C-5. CLEANUP

В DM боту: `/unsubscribe <SUB_C>` ИЛИ через MCP `unsubscribe_digest(subscription_id="<SUB_C>")`.

---

## D — P1-2 Bot NL для chat target (3 минуты, ⭐⭐ HIGH)

**Цель:** counterpart C — бот должен выбрать **chat target** на основе слов «мне в личку» / «мне».

### D-1. NL prompt

В том же DM с ботом отправить:

> Хочу получать дайджест мне в личку каждое утро в 8 про эндокринологию

### D-2. Dialog

Бот может спросить clarification (источники) → `profendocrinologist`.

Финальный confirmation должен включать:
> Created subscription to your personal chat with cron `0 8 * * *` for sources [profendocrinologist]

✅ Acceptance: бот выбрал `target_kind=chat`, `chat_id=<OPERATOR_CHAT_ID>` (твой ID, не `5445781511`).

### D-3. Verify через MCP

```text
list_digests()
```

Свежая запись:
* ✅ `target_kind == "chat"`
* ✅ `chat_id == <OPERATOR_CHAT_ID>` (НЕ `5445781511`!)
* ✅ `channel_id == null` (правильно — chat target)
* ✅ `cron_expression == "0 8 * * *"`

`SUB_D` id запиши.

### D-4. CLEANUP

`/unsubscribe <SUB_D>` ИЛИ MCP `unsubscribe_digest`.

---

## E — M-4 Watchlist channel target (5-10 минут, ⭐ MEDIUM bonus)

**Цель:** проверить, что watchlist subscription с channel target работает + `WatchInterestInfo` schema не падает в `list_watchlists()` на `channel_id` field (была регрессия, ловившаяся в self-review раньше).

### E-1. Subscribe watchlist

```text
subscribe_watchlist(
  title="vps_watch_p0_3_watchlist",
  channel_ids=["profendocrinologist"],
  target={"kind": "channel", "channel_id": "@vps_watch_test_r1"},
  keywords=["диабет", "инсулин", "гормон"],
  threshold=0.3
)
```

```bash
WL_E="<interest_id>"
```

### E-2. Schema validation

```text
list_watchlists()
```

✅ Acceptance: возвращает запись `WL_E` **без** ValidationError. Поля:
* `channel_id == "@vps_watch_test_r1"`
* `chat_id == null` (optional поле, теперь nullable per ADR-0008)

(Это и есть проверка, что fix в `WatchInterestInfo` (mcp_server.py, моя замечание из self-review) держит.)

### E-3. (опц.) Триггер pipeline для ускорения

Если есть admin role:
```text
trigger_pipeline()
```

Иначе ждать ~5-10 минут (естественный incremental tick).

### E-4. Verify match delivery (если был matching content)

* Telegram R-1 → должно прийти match-уведомление (формат: «watch hit для «vps_watch_p0_3_watchlist»: <content>») — **только если** в KB поступил свежий контент с matching keywords за окно теста.
* MCP: `get_watchlist_matches(interest_id="<WL_E>")` → список с ≥ 0 матчей.

✅ Acceptance: schema valid (mandatory) + match delivered (best-effort, зависит от content)

### E-5. CLEANUP

```text
unsubscribe_watchlist(interest_id="<WL_E>")
```

---

## FIN — Final reporting (2 минуты, MUST)

После завершения всех выполненных шагов скажи AI assistant'у (или сам обнови файл) — добавить секцию в [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md):

```markdown
### T+<XX>h<MM>m — `2026-05-24T<HH:MM>Z` — OP-2 / OP-3 interactive tests results

| Test | Status | Evidence |
|---|---|---|
| A (M-2 success) | GREEN / RED / SKIP | sub=<SUB_M2>, success counter: <X→Y>, digest пришёл в R-1: YES/NO |
| B (M-3 denied) | GREEN / RED / SKIP | sub=<SUB_M3>, permission_denied counter: <X→Y>, soft-deactivate=YES/NO, fallback DM=YES/NO |
| C (P1-1 NL channel) | GREEN / RED / SKIP | sub=<SUB_C>, bot inferred target_kind=channel=YES/NO; bot prompt: «<exact phrase used>» |
| D (P1-2 NL chat) | GREEN / RED / SKIP | sub=<SUB_D>, target_kind=chat=YES, chat_id=<OPERATOR_CHAT_ID> (not 5445781511)=YES/NO |
| E (M-4 watchlist) | GREEN / RED / SKIP | interest=<WL_E>, WatchInterestInfo schema valid=YES/NO, matches=<N> |

**Cleanup status:** все test subscriptions удалены через unsubscribe_*: YES / NO (если NO — перечислить orphan IDs).

**Anomalies observed (если есть):** ...

**Impact on closure criteria:**
* C-1 (success counter): MATERIALIZED via A / not materialised
* C-2 (permission_denied counter): MATERIALIZED via B / not materialised
* C-3 (channel-publish-fail counter): unchanged (expected — нет real fail path в этих тестах)
* Bot prompt v1.7.0 disambiguation: VERIFIED via C+D / partial / not tested
```

---

## Cleanup verification (после FIN)

Перед закрытием watch — убедиться, что **нет orphan test subscriptions**:

```text
list_digests()
list_watchlists()
```

Должны быть видны **только** real prod subscriptions (digest_94483db9 + 12 watch_interests pre-existing). Если видишь `vps_watch_*` или `vps-watch-*` — удалить.

Также можно удалить R-1, R-2 каналы из Telegram (опционально — они полезны для будущих watch windows).

---

## Связанные документы

* Watch note: [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)
* Full exercise plan: [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) (содержит P0/P1/P2 framing, escalation matrix, GREEN closure criteria C-1…C-12)
* Operator manual (broader): [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md) (§ M-2..M-4 и M-6 — этот файл их разворачивает с зависимостями)
* Automations registry: [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md)
* ADR 0008: [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md)
* Bot prompts v1.7.0 (target_kind_semantics секция): [`prompts/bot.yaml`](../../prompts/bot.yaml)
