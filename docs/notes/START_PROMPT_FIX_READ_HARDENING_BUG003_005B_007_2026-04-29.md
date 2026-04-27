# Fix Sprint — Read-tool Hardening Batch (BUG-003 + BUG-005-B + BUG-007) (Session F, 2026-04-29)

**Назначение:** последняя BUG-fix-сессия из волны 2026-04-27..29.
Закрывает три read-side баги одним батчем (shared touch-points в
`tools.py` executors и `prompts/bot.yaml`):

- **BUG-003** (Low/Medium) — read-tool'ы не нормализуют `@` в `channel_id`
  (`@AgeManagement` ≠ `AgeManagement` → пустой результат при прямом MCP).
- **BUG-005-B** (Medium) — `_call_tool_safe` (через `execute_tool`)
  выбрасывает generic `"internal error"`, теряя specific exception-message;
  как следствие, BUG-005-A проявлялся как «генерик» вместо «credit balance low».
- **BUG-007** (Medium) — read-tool'ы тихо отдают `total: 0` без suggestion'а
  при опечатанном `channel_id` — UX-ловушка, маскирует другие баги.

**По D5 default** (см. `BUG_LOG.md` § Session planning) — этот sprint
**не** закрывает storage-side LIKE→JSONB переход для BUG-007;
storage-fix вынесен в отдельный TD после Session F. Здесь — только
tool-executor + prompt + typed-catch.

**Тип сессии:** writing — code, tests, prompt updates, PR. Самая мелкая
из BUG-fix-сессий (~2.5 ч).

**Дата подготовки промпта:** 2026-04-27.

**Когда использовать:** **только** после того как:

1. Phase 1 / Phase 2 / Session B+ landed.
2. **Session D landed** (FSM scaffolding) — потому что меняется
   `_format_*_result` и подмешивание suggestion'ов в response — лучше
   единым контрактом; иначе двойная редактура `prompts/bot.yaml`.
3. Session E **landed или в работе** — если Session E выбрала Option B
   (split TOOL_DECLARATIONS), убедиться что наши изменения совместимы.
4. `BUG_LOG.md` § BUG-003, § BUG-005, § BUG-007 прочитаны целиком.

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/BUG_LOG.md` § BUG-003 — целиком, **особенно**:
   - § «Update 2026-04-26 23:39 — confirmed via MCP».
   - § «Update 2026-04-26 23:45 — cross-provider LLM masking».
2. `docs/notes/BUG_LOG.md` § BUG-005 — целиком, **особенно**:
   - § «BUG-005-B (generic catch)» — секция, оставшаяся открытой
     после resolution BUG-005-A.
3. `docs/notes/BUG_LOG.md` § BUG-007 — целиком, **особенно**:
   - § «Root cause» — три слоя (storage / tool executor / system prompt).
   - § «Notes / status updates» — связь с BUG-003 confound.
4. `docs/notes/BUG_LOG.md` § Session planning — D-5 default
   (только tool+prompt в этой сессии).
5. `tg_parser/bot/tools.py:759–795` — `execute_tool` (BUG-005-B target).
6. `tg_parser/bot/tools.py:802–824` — `_exec_ask_question`.
7. `tg_parser/bot/tools.py:827–851` — `_exec_search`.
8. `tg_parser/bot/tools.py:854–906` — `_exec_list_topics` (BUG-003 + BUG-007 target).
9. `tg_parser/bot/tools.py:909–958` — `_exec_get_topic_details`.
10. `tg_parser/bot/tools.py:1038–1051` — `_exec_get_cross_channel_stats`.
11. `tg_parser/bot/tools.py:960–982` — `_exec_list_channels` (нужен для
    suggestion'ов в BUG-007 fix).
12. `tg_parser/mcp_server.py:752–852` — параллельные MCP read-tool'ы
    (для symmetric fix'а).
13. `prompts/bot.yaml` — текущий system prompt; будет дополнен secций
    по fallback-discovery + suggestion'ов.

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. Phase 1/2 + Session B+/D/E landed
git log --oneline main -50 | rg "Session [BDE]"
rg "Session [BDE] \(2026" docs/notes/BUG_LOG.md

# 2. Reproduce BUG-003 (через прямой MCP, без LLM):
#    curl или CallMcpTool: list_topics(channel_id="@Lab4health") → ожидать total=0
#    list_topics(channel_id="Lab4health") → 165 тем
#    Это smoke-проверка что баг ещё открыт.

# 3. Reproduce BUG-007:
#    list_topics(channel_id="AgeManagement") → ожидать total=0 (без suggestion'а)
#    Это smoke-проверка.

# 4. Working tree чист, branch
git checkout main
git pull --ff-only origin main
.venv/bin/pytest -q 2>&1 | tail -20
git checkout -b fix/read-hardening-bug-003-005b-007-2026-04-29
```

### 1.3 Gating decisions

| ID | Вопрос | Default per BUG_LOG § Session planning |
|---|---|---|
| F-1 | Где делать `@`-strip — в каждом executor'е или в общем helper'е? | **Общий helper** `_normalize_channel_id(value: str | None) -> str | None`; импорт во всех read-executor'ах + write-executor'ах (где они уже есть в Session B+ M2). |
| F-2 | Suggestion-emit format | **Default**: при `total=0` добавить в payload `available_channel_ids: list[str]` (top 10 most-active каналов user'а) + `suggestion: str | None` (если есть Levenshtein < 3 from input — указать closest match). |
| F-3 | Fuzzy-match implementation | **`difflib.get_close_matches`** stdlib, threshold cutoff=0.7, n=3. Минимум зависимостей. |
| F-4 | Typed catch для `_call_tool_safe` (BUG-005-B) | **Capture exception class + message**; preserve в payload как `error_class: str`, `error_message: str` (truncated to 500 chars); generic fallback только для UnboundLocalError / KeyError / etc — реальные API errors сохраняются. |
| F-5 | Backward compatibility для existing tool consumers | **Не ломать** — новые поля (`available_channel_ids`, `suggestion`, `error_class`) добавляются как **optional**; existing fields (`total`, `items`, `error`) сохраняются. |
| F-6 | Symmetric fix для MCP `mcp_server.py` read-tool'ов? | **Да** — те же изменения; иначе bot-tool и MCP расходятся в поведении. Это часть scope'а. |

---

## 2. Out of scope

| Категория | Куда отложить | Причина |
|---|---|---|
| **Storage-side LIKE → JSONB ?** | отдельный TD-NN после Session F | D-5 default; миграции, отдельное review |
| **`AgeManagment` → `AgeManagement` data-quality fix** | отдельный admin-task | Возможно реальный typo в Telegram-username; pause/add/remove с правильным id |
| **Cross-language fuzzy match (translit)** | отдельный feature | Сейчас только difflib stdlib |
| **Search-tool re-ranking based on suggestion'ах** | отдельный feature | Вне scope'а UX-hardening'а |
| **Bot-side typo correction в user-input** | отдельный feature | Сложно без broader UX-overhaul'а |
| **Replacement существующих error-payload contracts** | wontfix | F-5 default — backward compatible |
| **`prompts/bot.yaml` mass-rewrite** | wontfix | Только append fallback + suggestion sections |
| **MCP-side new tools** | wontfix | Только existing fix |

---

## 3. Sprint scope (Session F)

### 3.1 BUG-003 fix — `_normalize_channel_id` helper (F-1)

**Files to touch:**

- `tg_parser/bot/tools.py` — добавить helper в верх файла (after imports):

  ```python
  def _normalize_channel_id(value: str | None) -> str | None:
      """Normalize channel_id by stripping @ prefix and whitespace.

      Read- and write-tools accept channel_id with or without @ prefix;
      DB stores values without prefix. This normalization is the
      single source of truth for the convention.

      See BUG-003.
      """
      if value is None:
          return None
      return value.strip().lstrip("@") or None
  ```

- `tg_parser/bot/tools.py` — все read-tool executors:
  ```python
  async def _exec_list_topics(args, ...):
      channel_id = _normalize_channel_id(args.get("channel_id"))
      ...
  ```

  Где это нужно (минимум):
  - `_exec_ask_question`
  - `_exec_search`
  - `_exec_list_topics`
  - `_exec_get_topic_details`
  - `_exec_get_cross_channel_stats`
  - `_exec_get_related_topics`
  - `_exec_get_document`
  - **Все write-executor'ы тоже** для consistency: `_exec_add_channel`,
    `_exec_pause_channel`, `_exec_resume_channel`, `_exec_remove_channel`,
    `_exec_trigger_pipeline`, `_exec_get_pipeline_status`,
    `_exec_subscribe_digest`, `_exec_subscribe_watchlist`, и т.д.

  (write-executor'ы уже могут иметь свой `lstrip("@")` локально — заменить
  на `_normalize_channel_id` для consistency.)

- `tg_parser/mcp_server.py` — symmetric fix (F-6 default):
  - Если MCP-handler делегирует через bot's `execute_tool` → fix
    автоматически распространяется (no-op для MCP).
  - Если MCP-handler имеет отдельную implementation — добавить тот же
    `_normalize_channel_id` или импортировать из `bot.tools`.

### 3.2 BUG-007 fix — suggestion-emit on `total=0` (F-2 + F-3)

**Files to touch:**

- `tg_parser/bot/tools.py` — добавить второй helper:

  ```python
  import difflib

  async def _build_no_results_suggestion(
      requested_channel_id: str,
      current_user: CurrentUser | None,
  ) -> dict[str, Any]:
      """Build suggestion payload for tools that returned total=0.

      Returns a dict with:
      - `available_channel_ids`: list[str] — top 10 most-active channels
        user has access to.
      - `suggestion`: str | None — if a close match exists in
        available channels, hint at the typo correction.

      See BUG-007.
      """
      from tg_parser.auth.resolvers import get_default_admin
      from tg_parser.services import channel_service  # actual import path may differ

      user = current_user or await get_default_admin()
      available = await channel_service.list_channel_ids_for_user(user)
      # cap to 10 for response-size discipline
      available_top = available[:10] if len(available) > 10 else available

      suggestion: str | None = None
      if requested_channel_id and available:
          matches = difflib.get_close_matches(
              requested_channel_id, available, n=1, cutoff=0.7
          )
          if matches:
              suggestion = (
                  f"Возможно, имелся в виду '{matches[0]}'? "
                  f"(вы запросили '{requested_channel_id}')"
              )

      return {
          "available_channel_ids": available_top,
          "suggestion": suggestion,
      }
  ```

- `tg_parser/bot/tools.py::_exec_list_topics` (и аналогично `_exec_search`,
  `_exec_get_topic_details`, `_exec_get_cross_channel_stats`):

  ```python
  async def _exec_list_topics(args, current_user=None):
      channel_id = _normalize_channel_id(args.get("channel_id"))
      ...
      result = {"total": total, "items": items, ...}
      if total == 0 and channel_id:
          result.update(await _build_no_results_suggestion(channel_id, current_user))
      return result
  ```

- `tg_parser/mcp_server.py` — symmetric fix.

### 3.3 BUG-005-B fix — typed catch в `execute_tool` (F-4)

**Files to touch:**

- `tg_parser/bot/tools.py:759–795` — `execute_tool`:

  ```python
  async def execute_tool(...):
      executor = _TOOL_EXECUTORS.get(name)
      if executor is None:
          return {"error": f"Unknown tool: {name}", "error_class": "UnknownTool"}

      kwargs: dict[str, Any] = {"current_user": current_user}
      if name in _TOOLS_NEEDING_BOT_CONTEXT:
          kwargs["bot"] = bot
          kwargs["chat_id"] = chat_id

      try:
          result = await asyncio.wait_for(executor(args, **kwargs), timeout=timeout)
          return result
      except TimeoutError:
          logger.warning("tool_timeout", tool=name, timeout=timeout)
          return {
              "error": f"Tool '{name}' timed out after {timeout}s",
              "error_class": "TimeoutError",
          }
      except PermissionError as exc:
          logger.warning("tool_permission_denied", tool=name, message=str(exc))
          return {
              "error": str(exc) or "Permission denied",
              "error_class": "PermissionError",
          }
      except (ValueError, KeyError) as exc:
          logger.warning("tool_validation_error", tool=name, error_class=type(exc).__name__, message=str(exc))
          return {
              "error": str(exc) or f"Validation error in '{name}'",
              "error_class": type(exc).__name__,
          }
      except Exception as exc:
          # NEW: preserve exception class + truncated message
          logger.exception("tool_execution_error", tool=name)
          return {
              "error": str(exc)[:500] if str(exc) else f"Tool '{name}' failed with an internal error",
              "error_class": type(exc).__name__,
          }
  ```

  **Ключевое изменение**: generic `Exception` ветка теперь сохраняет
  `error_class` + `error_message` вместо обнуления. Это позволяет
  bot-агенту в `agent.py` сформулировать осмысленный ответ
  пользователю (не «внутренняя ошибка»).

### 3.4 System prompt update (`prompts/bot.yaml`)

**Files to touch:**

- `prompts/bot.yaml` — дополнить:

  ```yaml
  system:
    prompt: |
      ... existing prompt + Session D additions ...

      ## Channel ID нормализация

      User может писать имя канала с `@` или без — это эквивалентно.
      Tool'ы автоматически strip'ают `@`. Не валидируй на этом
      уровне; передавай value как есть.

      ## Fallback при пустом результате

      Если tool возвращает `total: 0`:
      1. Если в payload'е есть `suggestion: str` — **процитируй его**
         пользователю буквально, это вероятная подсказка про typo.
      2. Если в payload'е есть `available_channel_ids: list[str]` —
         **покажи 3-5 примеров** пользователю, чтобы он мог увидеть
         какие каналы доступны.
      3. Если ни того, ни другого нет — generic message «канал не
         найден или ещё не обработан» допустим.

      ## Error classification

      Если tool возвращает `error_class: str` — учитывай в формулировке:
      - `TimeoutError` → «запрос занял слишком много времени, попробуйте
        упростить»
      - `PermissionError` → «у вас нет доступа к этому ресурсу»
      - другое → парафраз `error` в осмысленный русский текст.

      Никогда не возвращай generic «внутренняя ошибка» если в payload'е
      есть конкретный `error_class` + `error` message.
  ```

### 3.5 Tests

**Files to touch:**

- `tests/test_bot_tools.py` (новый файл или дополнить):

  - **BUG-003 normalization:**
    - `test_normalize_channel_id_strips_at_prefix`:
      `_normalize_channel_id("@AgeManagement") == "AgeManagement"`.
    - `test_normalize_channel_id_strips_whitespace`.
    - `test_normalize_channel_id_handles_none`: returns None.
    - `test_normalize_channel_id_handles_empty_string`: returns None.
    - `test_exec_list_topics_with_at_prefix_returns_same_as_without`:
      mock storage возвращает 5 items для `Lab4health`; вызов с
      `channel_id="@Lab4health"` тоже возвращает 5.

  - **BUG-007 suggestion:**
    - `test_no_results_suggestion_provides_close_match`:
      mock channel_repo возвращает `["AgeManagment", "Lab4health"]`;
      query `"AgeManagement"` → suggestion указывает на `AgeManagment`.
    - `test_no_results_suggestion_provides_no_match_for_far_input`:
      query `"xyz_unknown"` → suggestion is None.
    - `test_no_results_includes_available_channel_ids`:
      payload содержит `available_channel_ids` после `total=0`.
    - `test_no_results_does_not_emit_suggestion_when_total_nonzero`.

  - **BUG-005-B typed catch:**
    - `test_execute_tool_preserves_value_error_message`:
      executor raises `ValueError("invalid arg X")`; payload содержит
      `error_class="ValueError"`, `error_message="invalid arg X"`.
    - `test_execute_tool_preserves_permission_error_message`.
    - `test_execute_tool_truncates_long_exception_message`:
      executor raises `Exception("a"*1000)`; payload `error` ≤ 500.
    - `test_execute_tool_timeout_returns_typed_class`.
    - **Regression** для BUG-005 case: mock executor raises
      `Exception("Your credit balance is too low...")` →
      payload содержит этот message, не generic.

---

## 4. Per-step playbook

### 4.1 Helper extraction (3.1)

```bash
# 1. Edit tg_parser/bot/tools.py — add _normalize_channel_id helper.
# 2. Replace lstrip("@") в каждом executor'е через helper.
# 3. Add to MCP-side если есть отдельная implementation.

# 4. Smoke
.venv/bin/pytest tests/test_bot_tools.py -q -v -k "normalize"

# 5. Commit
git commit -m "fix(bug-003) part 1/4: _normalize_channel_id helper

Adds central helper for stripping @ prefix from channel_id input.
Applied across all read- and write-executors in tools.py and
symmetrically in mcp_server.py. Resolves BUG-003 — read-tools no
longer return total=0 when user passes @ChannelName.

Refs: BUG_LOG.md BUG-003, Session F."
```

### 4.2 Suggestion-emit (3.2)

```bash
# 1. Add _build_no_results_suggestion helper.
# 2. Wire into _exec_list_topics, _exec_search, _exec_get_topic_details,
#    _exec_get_cross_channel_stats.
# 3. Symmetric MCP-side.
# 4. Tests

.venv/bin/pytest tests/test_bot_tools.py -q -v -k "suggestion"

git commit -m "fix(bug-007) part 2/4: emit available_channel_ids + suggestion on total=0

Read-tools now include `available_channel_ids` (top-10 user-accessible)
and optional `suggestion` (Levenshtein-close match via difflib) in
their response payload when total=0. Helps user differentiate 'channel
absent' from 'typo'. Closes the diagnostic confound that masked
BUG-003 in the original BUG-003 thread.

Refs: BUG_LOG.md BUG-007, Session F."
```

### 4.3 Typed catch (3.3)

```bash
# 1. Edit execute_tool — replace generic except.
# 2. Tests

.venv/bin/pytest tests/test_bot_tools.py -q -v -k "execute_tool"

git commit -m "fix(bug-005-b) part 3/4: typed exception catches in execute_tool

execute_tool now distinguishes TimeoutError, PermissionError,
ValueError/KeyError, and generic Exception — each preserves
exception_class + truncated message in the payload. Generic
'internal error' is no longer the default for known exception
types; the bot agent can now formulate specific user-facing
responses. Recovery from the BUG-005-A 'credit balance too low'
case would now show the actual message.

Refs: BUG_LOG.md BUG-005-B, Session F."
```

### 4.4 System prompt update (3.4)

```bash
# 1. Edit prompts/bot.yaml — append channel-normalization, fallback,
#    error-classification sections.

# 2. Verify reload via reload_prompts MCP tool на staging.
# 3. Final pytest sweep
.venv/bin/pytest -q 2>&1 | tail -10

git commit -m "fix(bug-003+007+005-b) part 4/4: system prompt — fallback + error guidance

prompts/bot.yaml now teaches the LLM about: (a) @-prefix being
optional, (b) using `suggestion` and `available_channel_ids`
fallbacks on total=0, (c) classifying error_class for user-facing
messages. Behavior is correct even if LLM ignores guidelines
(deterministic helpers in tools.py); this is supplementary UX.

Refs: BUG_LOG.md BUG-003 + BUG-005-B + BUG-007, Session F."
```

---

## 5. Testing & verification (full run)

```bash
.venv/bin/pytest -q 2>&1 | tail -20
# Ожидаемо: count = baseline + 12-15 (broadest test additions).

.venv/bin/pytest tests/test_bot_tools.py -q -v
```

Manual smoke на dev-bot и через MCP:

1. **BUG-003 confirm (через MCP)**:
   - `list_topics(channel_id="@Lab4health")` → ожидать 165 тем (как
     `Lab4health` без `@`).
2. **BUG-003 confirm (через bot)**:
   - «темы канала @AgeManagment» → ожидать список тем (нормализация
     транспарентна).
3. **BUG-007 confirm**:
   - «темы канала AgeManagement» → ожидать «возможно AgeManagment?
     Вот доступные каналы: [...]».
4. **BUG-005-B confirm** (искусственный тест):
   - Временно зарейзить `ValueError("test message")` в одном executor'е;
     вызов через bot → bot формулирует осмысленный ответ, не «внутренняя
     ошибка». Откатить.

---

## 6. PR / commit conventions

- **PR title**: `fix(bug-003+005-b+007): read-tool hardening — channel-normalize + suggestions + typed catches`.
- **PR body** должен содержать:
  - Цель: closure trio Low/Medium-багов одним батчем.
  - Reference на BUG_LOG.md секции для каждого bug'а.
  - Backward-compat note: existing fields сохраняются, новые поля optional.
  - Out-of-scope note: storage-side LIKE→JSONB вынесен в follow-up TD.
- **CHANGELOG entry**:
  ```markdown
  ## Bug fix BUG-003 + BUG-005-B + BUG-007 — Read-tool hardening (2026-04-29)

  ### Closes Low + Medium

  Read-tools bot/MCP теперь:
  - Прозрачно strip'ают `@` prefix в `channel_id` (BUG-003).
  - На `total=0` возвращают `available_channel_ids` и optional `suggestion`
    через difflib (BUG-007).
  - В `execute_tool` сохраняют exception_class + message; generic
    «internal error» больше не маскирует реальные API errors (BUG-005-B
    — recovery от BUG-005-A scenarios).

  See BUG_LOG.md.
  ```
- **Commit footer на финальном merge-commit'е**:
  `Refs: BUG_LOG.md BUG-003 + BUG-005-B + BUG-007, Session F. Closes: BUG-003, BUG-005-B, BUG-007.`
- **PR labels**: `bug-fix`, `bug-003`, `bug-005-b`, `bug-007`, `bot`,
  `mcp_server`, `read-hardening`.

---

## 7. Acceptance criteria

Session F считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 gating decisions F-1..F-6 закрыты
- [ ] **`_normalize_channel_id` helper** landed; все read- и write-executor'ы
      используют его (`rg "lstrip..@" tg_parser/` пусто кроме helper'а)
- [ ] **`_build_no_results_suggestion` helper** landed; wired в 4+ read-executor'ов
- [ ] **`execute_tool` typed catches** landed; preserve exception_class +
      message
- [ ] **`prompts/bot.yaml` обновлён** тремя секциями
- [ ] **MCP-side symmetric fix** landed
- [ ] full pytest suite зелёный (count ≥ baseline + 12)
- [ ] CHANGELOG обновлён trio-bug-fix-разделом
- [ ] PR merged в main с зелёным CI
- [ ] **`BUG_LOG.md` BUG-003, BUG-005-B, BUG-007 перенесены в § Resolved bugs**
      с PR# + commit-SHA каждый
- [ ] **`BUG_LOG.md` § Session planning § Updates** содержит:
  ```
  Session F (2026-04-NN) — landed: PR #NN, commit <SHA>, +N tests;
  bugs resolved: BUG-003, BUG-005-B, BUG-007.
  ```

---

## 8. Handoff

Перед закрытием Session F:

1. **Production deploy verification**:
   - Manual smoke (§ 5) проходит.
   - **24h watch metric'ом** — никаких metric `bot_gemini_empty_parts`-spike'ов
     (если Session E landed).
2. **Уведомить пользователя** что:
   - **Все 7 багов из BUG_LOG.md обработаны** (4 resolved через сессии C+D+E+F,
     1 mitigated через B+, 1 resolved билинг-фиксом, 1 partial Critical → resolved).
   - BUG-fix-волна 2026-04-27..29 завершена.
   - Можно стартовать **отдельный housekeeping-sprint** для TD-05..08
     (отложенные P1 stretch из Phase 2; см. D-1 default из § Session planning).
3. **Open follow-up TD**:
   - **TD-storage-jsonb-channel-id** (BUG-007 storage-side, deferred per D-5):
     `LIKE '%"channel_id"%'` → `sources @> ARRAY['channel_id']` или
     `sources ? 'channel_id'` (зависит от JSONB shape'а). Affects
     `topic_card_repo.list_by_channel`, `topic_bundle_repo.list_by_channel`.
   - **TD-data-quality-AgeManagment**: проверить нужна ли rename
     channel'а (если это typo, не реальный username).
4. **Финальное сообщение юзеру** должно содержать:
   - PR# и SHA.
   - Подтверждение что bug-fix-волна **закрыта** для backlog'а 2026-04-26..27.
   - Backlog dump: TD-05..08 + TD-storage-jsonb-channel-id +
     TD-data-quality-AgeManagment.

---

## 9. Citation back

- **Bug sources:**
  - `docs/notes/BUG_LOG.md` § BUG-003 (читать целиком + Update 23:39 / 23:45).
  - `docs/notes/BUG_LOG.md` § BUG-005 § BUG-005-B subsection.
  - `docs/notes/BUG_LOG.md` § BUG-007.
- **Predecessor sessions:**
  - `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md` (Session D).
  - `docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` (Session E).
- **Session planning:** `docs/notes/BUG_LOG.md` § Session planning (D-5 default).
- **Independent track:**
  `docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md` (Session C).
- **Related code:**
  - `tg_parser/bot/tools.py` (target, ~30+ executors).
  - `tg_parser/mcp_server.py` (symmetric fix).
  - `prompts/bot.yaml` (system prompt).
  - `tg_parser/storage/sqlalchemy/topic_card_repo.py:130–143` (NOT touched
    here per D-5; future TD).

В commit-message'ах достаточно `Refs: BUG_LOG.md BUG-003 + BUG-005-B + BUG-007, Session F.`
