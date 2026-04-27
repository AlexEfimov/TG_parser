# Fix Sprint — BUG-006 Bot Gemini-flash empty `parts` (Session E, 2026-04-29)

**Назначение:** закрывает Critical-баг **BUG-006** — `gemini-2.5-flash`
возвращает HTTP 200 с пустым `candidates[].content.parts=[]` на сложных
tool-disambiguation запросах (напр. «Покажи LLM конфиг»), а
`agent.process_message` нормализует это в generic ответ
«Не удалось получить ответ от LLM» без диагностики.

Сессия начинается с **research-spike** для выбора между тремя fix-опциями
(D-3 default per § Session planning), затем code-changes по выбранной опции
+ improved error-classification.

**Тип сессии:** writing (после spike) — code, tests, possibly model migration.
**Объём зависит от выбора опции** (2-4 ч).

**Дата подготовки промпта:** 2026-04-27.

**Когда использовать:** **только** после того как:

1. Phase 1 / Phase 2 / Session B+ landed.
2. **Session D landed** (FSM scaffolding) — нужна стабильная bot-loop.
3. Session C **может** быть в работе параллельно (independent).
4. `BUG_LOG.md` § BUG-006 прочитан целиком, особенно § «Hypotheses
   ranked» (HG-1..HG-4).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/BUG_LOG.md` § BUG-006 — целиком, **особенно**:
   - § «Root cause» — empty `parts=[]` без явного `finishReason`.
   - § «Hypotheses ranked» — HG-1 (filter), HG-2 (thinking-budget),
     HG-3 (overload), HG-4 (tool-set bloat).
   - § «Update from set_llm_config trace (23:51)» — детерминизм для
     класса tool-disambiguation запросов.
2. `docs/notes/BUG_LOG.md` § Session planning — D-3 default
   (research-spike в начале сессии).
3. `tg_parser/bot/agent.py` — целиком (≈205 строк), особенно
   `_call_gemini` (L142-191) и empty-parts handling (L97-98).
4. `tg_parser/bot/tools.py:43–760` — `TOOL_DECLARATIONS` (30+ tools);
   замерить общий размер JSON-описаний (token estimate).
5. `tg_parser/config/settings.py:738` — `bot_gemini_model` config.
6. `prompts/bot.yaml` — system prompt; знать его текущий размер.
7. **Gemini docs** для `gemini-2.5-flash` особенностей:
   - Thinking budget (`thinkingBudget` parameter).
   - Output token limit (per model).
   - Tool-calling-mode behavior.
8. `tests/test_bot_*.py` — текущий test coverage agent'а; будет нужен
   regression-test для empty-parts.

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. Phase 1/2 + Session B+ + Session D landed
git log --oneline main -50 | rg "Session D \(2026|BUG-002 + BUG-004"
rg "Session D \(2026" docs/notes/BUG_LOG.md

# 2. Reproduce баг локально:
#    Запустить bot на dev, отправить «Покажи LLM конфиг» — ожидать
#    «Не удалось получить ответ от LLM».
#    Это smoke-проверка что баг ещё не закрыт случайно.

# 3. Working tree чист, branch
git checkout main
git pull --ff-only origin main
.venv/bin/pytest -q 2>&1 | tail -20
git checkout -b fix/bug-006-bot-gemini-2026-04-29
```

### 1.3 Gating decisions (must answer DURING research-spike, before code-changes)

| ID | Вопрос | Default per BUG_LOG § Session planning |
|---|---|---|
| E-spike | Research-spike (~30 мин): протестировать 3 опции на reproducible-query | **Обязательно** — без spike code-changes не делаем |
| E-1 | Какая fix-опция выбрана после spike'а? | **Решает spike** — см. § 3.1 ниже |
| E-2 | Improved empty-parts error message — какие fields в payload? | **Default**: payload-dump в logger.error на `INFO` для admin-канала, generic-message для пользователя; различать по `finishReason` если есть |
| E-3 | Logging payload size cap | **2048 char**, превышение → truncate с маркером |
| E-4 | Telemetry — добавить metric `bot_gemini_empty_parts_total`? | **Да** — для мониторинга после fix'а; Counter по `model`, `tool_count`, `query_class` |

---

## 2. Out of scope

| Категория | Куда отложить | Причина |
|---|---|---|
| **MCP-side tool refactor / описаний** | отдельный TD | TOOL_DECLARATIONS shared с MCP-server |
| **Новые tool'ы** | отдельный feature TD | Сейчас сокращаем, не добавляем |
| **Conversation history (multi-turn memory)** | отдельный feature TD | Не требуется для BUG-006 |
| **Bot-side caching of tool-results** | отдельный TD | Возможно полезно, но не для BUG-006 |
| **Cross-LLM provider abstraction для bot'а** | большой refactor | Если выбирается Option C — switch model — это локальный config-change, не abstraction |
| **Rate-limiting per-user / per-model** | отдельный TD | Не root cause |
| **`prompts/bot.yaml` mass-rewrite** | отдельный TD | Можно minor-update в этом sprint'е (для адаптации к выбранной опции) |
| **MCP-tool-side fix BUG-005-B (`_call_tool_safe`)** | Session F | Read-side hardening |

---

## 3. Sprint scope (Session E)

### 3.1 Research-spike (≈30 мин, до code-changes)

**Цель:** определить какая опция (A/B/C) реально решает BUG-006 на
**том же** reproducible query («Покажи LLM конфиг»), без regression
для других классов запросов.

**Reproducible query set:**

```
Q1 (BUG-006 trigger): "Покажи LLM конфиг"
Q2 (BUG-006 trigger): "выведи текущий llm config"
Q3 (BUG-006 trigger): "Что говорится по теме <тема> в каналах X, Y, Z?"
   (multi-channel + topic — high tool-disambiguation)
Q4 (control, должно работать всегда): "перечисли темы канала Lab4health"
Q5 (control): "покажи список каналов"
```

**Опции для тестирования:**

#### Option A — bump `maxOutputTokens` 4096 → 8192

**Гипотеза**: thinking-budget исчерпывает токены до того, как модель сгенерит
функ-call (HG-2). Increase даёт буфер.

**Мини-PoC**:
```python
# tg_parser/bot/agent.py:155
"maxOutputTokens": 8192,  # было 4096
```

**Тест**: запустить Q1-Q5 5 раз каждый, посчитать success rate.
- ✅ если success-rate Q1+Q2 > 80% и Q4+Q5 без degradation.
- ❌ если success-rate Q1+Q2 < 50%.
- 🔶 если 50-80% — возможно надо 16384, или Option A не root cause.

**Cost impact**: +tokens на запрос, ~2x cost для bot-calls (но rare-path,
не critical).

#### Option B — split `TOOL_DECLARATIONS` (smart routing)

**Гипотеза**: 30+ tools в одном payload'е насыщает context (HG-4).
Если разделить на 2-3 группы (read / write / admin) и подавать в Gemini
только нужную группу через intent-classification, payload падает в 3-5×.

**Мини-PoC**:
```python
TOOLS_READ = [d for d in TOOL_DECLARATIONS if d["name"].startswith(("list_", "search_", "get_", "ask_question"))]
TOOLS_WRITE = [d for d in TOOL_DECLARATIONS if d["name"].startswith(("add_", "remove_", "pause_", "resume_", "set_", "subscribe_", ...))]
TOOLS_ADMIN = [d for d in TOOL_DECLARATIONS if d["name"].startswith(("register_user", "update_user", "list_users", "add_user_auth", "remove_user_auth"))]
TOOLS_CONFIG = [d for d in TOOL_DECLARATIONS if d["name"].startswith(("get_llm_config", "set_llm_config", "reset_llm_config", "reload_prompts"))]

# Pre-classify user_message via cheap heuristic OR via small Gemini call:
if "config" in lower(user_message) or "llm" in lower(user_message):
    tools_subset = TOOLS_CONFIG + TOOLS_READ
elif "удали" or "пауз" or "возобнов" in lower(user_message):
    tools_subset = TOOLS_WRITE
else:
    tools_subset = TOOLS_READ + TOOLS_CONFIG
```

**Тест**: тот же Q1-Q5 set.
- ✅ если Q1+Q2 success > 80% (правильное routing) и Q4+Q5 unchanged.
- ❌ если Q3 (cross-channel) ломается — heuristic неполный.
- 🔶 если возникает нужда в meta-LLM для routing — это option C-mini.

**Cost impact**: -50-70% per-call tokens (smaller payload).
**Complexity**: medium — нужна heuristic + edge-case coverage.

#### Option C — switch model

**Гипотеза**: `gemini-2.5-flash` имеет известные empty-response issues
для large-tool calls; другая модель устойчивее.

**Кандидаты:**

| Модель | Цена in/out | Pro | Con |
|---|---|---|---|
| `gemini-2.5-pro` | ~10× flash | Стабильнее на complex reasoning | Дороже |
| `claude-haiku-4-5-20251001` | ~$0.80/MTok | Дёшево, function-calling зрелый | Не Gemini-специфичный flow, нужен Anthropic SDK refactor agent.py |
| `gpt-4o-mini` | ~$0.15/MTok in / $0.60 out | Function-calling robust | Нужен OpenAI SDK refactor |
| `gemini-2.0-flash` | similar к 2.5-flash | Less thinking-budget overhead | Quality regression |

**Мини-PoC**: для каждого кандидата дёрнуть Q1-Q5 raw API-call'ом
(без agent loop), посчитать parse-success rate (где `parts` непустой).

**Cost impact**: разный — см. таблицу.
**Complexity**: для Gemini-вариантов — config-change; для Anthropic/OpenAI —
~50-100 строк refactor `_call_gemini` → `_call_llm`.

#### Recommendation framework для выбора

| Если spike показал... | Выбираем |
|---|---|
| Option A success > 80% Q1+Q2, Q4+Q5 OK | **A** — простейший, минимум диффа |
| Option A < 80%, Option B success > 80% | **B** — больше work, но root-cause-aware |
| Option A < 80%, Option B < 80%, gemini-2.5-pro success > 90% | **C-Gemini** — config-change |
| Все Gemini < 80%, Anthropic/OpenAI > 90% | **C-cross-provider** — большой refactor |

### 3.2 Implementation (после spike)

**Files to touch (зависит от опции):**

#### Если Option A:

- `tg_parser/bot/agent.py:155` — bump `maxOutputTokens`.
- Optional: добавить `thinkingBudget` если SDK позволяет (Gemini 2.5+
  поддерживает `generationConfig.thinkingConfig.thinkingBudget`).
- 1-комитный fix.

#### Если Option B:

- `tg_parser/bot/tools.py` — добавить tool-grouping constants:
  `TOOLS_READ`, `TOOLS_WRITE`, `TOOLS_ADMIN`, `TOOLS_CONFIG`,
  `TOOLS_DEFAULT = TOOLS_READ + TOOLS_CONFIG`.
- `tg_parser/bot/agent.py` — добавить функцию
  `_classify_intent(user_message: str) -> set[str]` (heuristic-based;
  возвращает группу tools).
- `tg_parser/bot/agent.py:_call_gemini` — принимать `tools_subset`
  параметром, передавать в payload.
- `tg_parser/bot/agent.py:process_message` — вызывать
  `_classify_intent` на первом turn'е, передавать subset; на последующих
  turn'ах — full set (если LLM решил что-то докрутить).
- 3-4 commit'а.

#### Если Option C-Gemini:

- `tg_parser/config/settings.py:738` — изменить default `bot_gemini_model`.
- ENV: `BOT_GEMINI_MODEL=gemini-2.5-pro` для production.
- Optional: добавить `thinkingBudget` если pro-model его поддерживает.
- 1-комитный config-change + 1 коммит docs/CHANGELOG.

#### Если Option C-cross-provider (Anthropic / OpenAI):

- `tg_parser/bot/agent.py` — переименовать `GeminiAgent` → `BotAgent`
  (или оставить, добавив адаптер).
- Новый файл `tg_parser/bot/llm_clients.py` (или подобный) — провайдер-
  agnostic интерфейс с реализациями для Gemini / Anthropic / OpenAI.
- `_call_gemini` → `_call_llm`, шаблонит payload по провайдеру.
- `_call_anthropic` / `_call_openai` — новые функции.
- `tg_parser/config/settings.py` — добавить `bot_llm_provider`,
  `bot_llm_model`.
- ENV: `BOT_LLM_PROVIDER=anthropic`, `BOT_LLM_MODEL=claude-haiku-4-5-20251001`.
- 5-7 commit'ов; **самый объёмный** option.

### 3.3 Improved empty-parts error classification (always, irrespective of option)

**Files to touch:**

- `tg_parser/bot/agent.py:81–98` — детальная classification:

  ```python
  candidates = response.get("candidates", [])
  if not candidates:
      block_reason = response.get("promptFeedback", {}).get("blockReason")
      if block_reason:
          logger.warning("gemini_blocked", reason=block_reason)
          return "Запрос был заблокирован фильтрами безопасности LLM."
      logger.error(
          "gemini_no_candidates",
          response_keys=list(response.keys()),
          response_dump=str(response)[:2048],
      )
      return "LLM не вернул ни одного кандидата ответа. Попробуйте позже."

  candidate = candidates[0]
  finish_reason = candidate.get("finishReason", "")

  if finish_reason == "SAFETY":
      logger.warning("gemini_safety_stop")
      return "Ответ был заблокирован фильтрами безопасности LLM."

  parts = candidate.get("content", {}).get("parts", [])

  if not parts:
      # NEW: classify empty-parts по finish_reason
      logger.error(
          "gemini_empty_parts",
          finish_reason=finish_reason,
          usage=response.get("usageMetadata"),
          model=self._model,
          tool_count=len(TOOL_DECLARATIONS),
      )
      # Metric (E-4 default)
      bot_gemini_empty_parts_total.labels(
          model=self._model,
          finish_reason=finish_reason or "unknown",
      ).inc()

      if finish_reason == "MAX_TOKENS":
          return ("LLM исчерпал бюджет ответа на этот запрос. "
                   "Попробуйте упростить вопрос или разбейте на части.")
      elif finish_reason == "RECITATION":
          return "LLM отказался ответить (recitation guard). Попробуйте переформулировать."
      else:
          return ("LLM вернул пустой ответ. "
                   "Возможно, сейчас перегрузка — попробуйте через минуту.")
  ```

### 3.4 Telemetry (E-4 default)

**Files to touch:**

- `tg_parser/api/metrics.py` (если существует) или новый
  `tg_parser/bot/metrics.py`:

  ```python
  from prometheus_client import Counter

  bot_gemini_empty_parts_total = Counter(
      "tg_bot_gemini_empty_parts_total",
      "Bot Gemini API returned empty parts (BUG-006 monitoring)",
      labelnames=("model", "finish_reason"),
  )
  ```

- Импорт + увеличение в `agent.py` (см. § 3.3).

### 3.5 Tests

**Files to touch:**

- `tests/test_bot_agent.py` (новый файл или дополнить существующий):

  - **Empty-parts classification:**
    - `test_empty_parts_max_tokens_returns_specific_message`: mock
      response с `finishReason="MAX_TOKENS"`, ожидать сообщение про
      «исчерпан бюджет», metric incremented.
    - `test_empty_parts_no_finish_reason`: mock response с пустым
      `parts` без finishReason, ожидать generic «вернул пустой ответ»
      + metric incremented.
    - `test_block_reason_returns_safety_message`: mock с
      `promptFeedback.blockReason`.

  - **Если Option B (intent classification):**
    - `test_classify_intent_config_query`: «покажи llm config» →
      group `{config, read}`.
    - `test_classify_intent_write_query`: «удали канал @x» → group `{write}`.
    - `test_classify_intent_default`: «привет» → group `{read, config}`.
    - `test_call_gemini_uses_subset_for_first_turn`: mock,
      assertion что `tools` в payload содержит subset, не full.
    - `test_call_gemini_uses_full_for_followup_turn`: mock,
      assertion что turn>0 использует full set.

  - **Если Option C-cross-provider:**
    - `test_anthropic_provider_calls_correct_endpoint`.
    - `test_openai_provider_calls_correct_endpoint`.
    - `test_provider_switching_via_env`: env-mock переключение.

  - **Regression для оригинального BUG-006:**
    - `test_bug_006_reproduction_now_succeeds`: mock сценарий с
      query «Покажи LLM конфиг», assert что не возвращает generic
      «Не удалось получить ответ» (точная assertion зависит от опции).

---

## 4. Per-step playbook

### 4.1 Research-spike

```bash
# 1. Создать tmp-script tools/spike_bug_006.py с reproducible queries
#    Q1-Q5, прогнать через текущую реализацию (capture full payload).

mkdir -p /tmp/bug-006-spike
.venv/bin/python tools/spike_bug_006.py --option current > /tmp/bug-006-spike/baseline.log

# 2. Прогнать Option A (bump maxOutputTokens):
.venv/bin/python tools/spike_bug_006.py --option a > /tmp/bug-006-spike/option-a.log

# 3. Прогнать Option B (split tools):
.venv/bin/python tools/spike_bug_006.py --option b > /tmp/bug-006-spike/option-b.log

# 4. Прогнать Option C-Gemini (model swap):
.venv/bin/python tools/spike_bug_006.py --option c-gemini-pro > /tmp/bug-006-spike/option-c-gemini-pro.log

# 5. Зафиксировать результаты в коммите:
git add tools/spike_bug_006.py /tmp/bug-006-spike/  # NB: возможно нужно копировать в docs/
git commit -m "spike(bug-006): research results for fix option selection

Tested options A (bump maxOutputTokens), B (split TOOL_DECLARATIONS),
C-Gemini-pro (model swap) on 5 reproducible queries (Q1-Q5).

Results: <fill in>
Decision: Option <X> per BUG_LOG E-1 default.

Refs: BUG_LOG.md BUG-006, Session E."
```

**ВАЖНО**: spike-script `tools/spike_bug_006.py` пишется во время сессии,
**не** до сессии. Это часть scope'а.

### 4.2 Implementation per chosen option

См. § 3.2 — playbook зависит от выбора. Все option'ы предполагают:

1. Code-changes per option.
2. § 3.3 empty-parts classification (всегда).
3. § 3.4 telemetry (всегда).
4. § 3.5 tests (full coverage).

```bash
# After implementation:
.venv/bin/pytest tests/test_bot_agent.py -q -v
.venv/bin/pytest -q 2>&1 | tail -10

git commit -m "fix(bug-006): <option-specific summary>

<detailed description per option>

Refs: BUG_LOG.md BUG-006, Session E."
```

### 4.3 Final sweep + manual smoke

```bash
# Manual smoke: bot на dev, прогнать Q1-Q5 руками.
# Verify metric:
curl localhost:8000/metrics | grep bot_gemini_empty_parts
```

---

## 5. Testing & verification (full run)

```bash
.venv/bin/pytest -q 2>&1 | tail -20
# Ожидаемо: count = baseline + 7-15 (зависит от опции).

.venv/bin/pytest tests/test_bot_agent.py -q -v
```

Manual smoke на dev-bot:

1. Q1: «Покажи LLM конфиг» → ожидать осмысленный ответ (НЕ generic).
2. Q2: «выведи текущий llm config» → success.
3. Q3: «Что говорится по теме <тема>?» → success.
4. Q4: «перечисли темы канала Lab4health» → success (control).
5. Q5: «покажи список каналов» → success (control).
6. **Edge case**: длинный сложный запрос с 3-4 cross-channel ссылками —
   проверить что либо success, либо specific MAX_TOKENS-message
   (а не generic).
7. **Metric**: после 10-20 manual queries — `curl /metrics | grep
   bot_gemini_empty_parts` — счётчик стал 0 на success-сценариях,
   увеличился на edge-case'ах.

---

## 6. PR / commit conventions

- **PR title**: `fix(bug-006): <option-specific> + improved empty-parts classification`
  (например, `fix(bug-006): bump maxOutputTokens to 8192 + classify finish reason`).
- **PR body** должен содержать:
  - Цель: closure BUG-006 (Critical).
  - Reference на BUG_LOG.md § BUG-006 + spike-результаты.
  - Sproke-summary: какая опция выбрана и почему.
  - Cost impact: какие токены/деньги/latency меняются.
  - Backward compatibility: env-vars, миграция.
- **CHANGELOG entry**:
  ```markdown
  ## Bug fix BUG-006 — Bot Gemini empty parts (2026-04-29)

  ### Closes Critical

  Bot больше не возвращает «Не удалось получить ответ от LLM» на
  сложных tool-disambiguation запросах. <option-specific summary>.
  Empty-parts ситуации классифицируются по finish_reason
  (MAX_TOKENS / RECITATION / unknown) с разными user-facing
  сообщениями + Prometheus-метрика для мониторинга.

  См. BUG_LOG.md BUG-006.
  ```
- **Commit footer на финальном merge-commit'е**:
  `Refs: BUG_LOG.md BUG-006, Session E. Closes: BUG-006.`
- **PR labels**: `bug-fix`, `bug-006`, `bot`, `llm`, `critical`.

---

## 7. Acceptance criteria

Session E считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 gating decisions E-spike + E-1..E-4 закрыты
- [ ] **Spike completed** — результаты документированы (можно в commit-message
      или в `docs/notes/SPIKE_BUG006_RESULTS.md`)
- [ ] **Выбранная опция implemented** с code-changes per § 3.2
- [ ] **Empty-parts classification** работает (§ 3.3) для всех 3-х
      finish_reason cases
- [ ] **Prometheus metric** `bot_gemini_empty_parts_total` доступен
- [ ] **Q1-Q5 manual smoke** все success на dev-bot
- [ ] full pytest suite зелёный (count ≥ baseline + 7)
- [ ] CHANGELOG обновлён
- [ ] PR merged в main с зелёным CI
- [ ] **`BUG_LOG.md` BUG-006 перенесён в § Resolved bugs** (с PR# + commit-SHA);
      severity → resolved (или wontfix-with-mitigation если выбрана
      Option A/B и BUG-006 проявляется на extreme-edge-case'ах)
- [ ] **`BUG_LOG.md` § Session planning § Updates** содержит:
  ```
  Session E (2026-04-NN) — landed: PR #NN, commit <SHA>, +N tests;
  bugs resolved: BUG-006 (option <X>).
  ```

---

## 8. Handoff

Перед закрытием Session E:

1. **Production deploy verification**:
   - Manual smoke (§ 5) проходит на dev.
   - Watch metric `bot_gemini_empty_parts_total` первые 24 часа на
     production — ожидать ≤ 1% от total bot-Gemini-calls.
   - Если spike > 5% — **revert и переоткрыть BUG-006** с новым
     hypothesis.
2. **Уведомить пользователя** что:
   - BUG-006 closed; конкретный fix-option и cost impact.
   - Session F (read-tool hardening) теперь может стартовать
     (последняя BUG-fix-сессия).
3. **Open follow-up TD** (если capacity):
   - Если выбрана Option B — `TD-bot-intent-router-tests`: расширить
     coverage edge-case'ов routing (например multi-language).
   - Если выбрана Option C-cross — `TD-bot-llm-fallback-chain`: на
     случай если primary провайдер ляжет, fallback на secondary.
   - **TD-bot-cost-monitoring**: bot-LLM-tokens-per-day metric.
4. **Финальное сообщение юзеру** должно содержать:
   - PR# и SHA.
   - Опцию (A/B/C) + spike-summary.
   - Cost impact diff.
   - Если 24h-monitoring ещё не сделан — отметить как pending verification.

---

## 9. Citation back

- **Bug source:** `docs/notes/BUG_LOG.md` § BUG-006 + § Hypotheses ranked.
- **Predecessor session:** `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md`
  (Session D — bot FSM scaffolding).
- **Session planning:** `docs/notes/BUG_LOG.md` § Session planning (D-3 default).
- **Successor session:**
  `docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md`
  (Session F — read-tool hardening, последняя BUG-fix-сессия).
- **Related context:**
  - `tg_parser/bot/agent.py` (target file).
  - `tg_parser/bot/tools.py::TOOL_DECLARATIONS` (sizing).
  - **Gemini docs**: `generationConfig.thinkingConfig.thinkingBudget`
    (если выбирается Option A с thinking-budget tweak).
  - **Anthropic docs**: function-calling (если C-cross-Anthropic).
  - **OpenAI docs**: tools-parameter (если C-cross-OpenAI).

В commit-message'ах достаточно `Refs: BUG_LOG.md BUG-006, Session E.`
