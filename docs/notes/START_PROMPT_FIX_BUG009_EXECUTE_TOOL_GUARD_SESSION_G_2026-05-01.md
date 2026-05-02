# Fix Sprint — `execute_tool` ConfirmFlow Guard (BUG-009 structural) (Session G, 2026-05-01)

---

## Pre-flight executed — READY FOR IMPLEMENTATION

**Status:** READY. Open a fresh chat and use the opener at the bottom of this
section. Do not relitigate the locked decisions below.

**Pre-flight performed:** Saturday 2026-05-02, 09:51 UTC (13:51 UTC+4) on
parent transcript «Session G pre-flight».

### Gate-1 verification (§ 0) — GREEN

VPS HEAD: `ec52060` (Session F + TD #53 deploy SHA, expected per § 1.2).
Window opened 2026-05-01 15:12 UTC (24h after Session F deploy `88e4337`),
verification ran ~18.5h into the post-watch window.

| Check | Expected | Actual | Status |
|---|---|---|---|
| Prometheus `tg_bot_gemini_empty_parts_total` | empty result vector OR isolated `finishReason=STOP` | `result: []` (empty) | GREEN |
| `docker logs --since 24h tg_parser_bot` grep `gemini_empty\|gemini_no_candidates\|gemini_blocked` | 0 | 0 | GREEN |
| `docker logs --since 24h tg_parser_bot` grep `tool=add_channel` (BUG-009 mitigation v1.3.0 hold) | 0 | 0 | GREEN |

### Prompt corrections applied

1. **§ 1.1 read 4** — `handlers.py` line ranges adjusted (FSM docstring
   actually L8–25; `_handle_confirmation_response` actually L270–340, was
   promised L240–330).
2. **§ 1.3 G-4 + § 3.1 step 1** — `_WRITE_TOOLS_REQUIRING_CONFIRM` set
   trimmed from 13 to **7** tools. Audit found that 6 of the originally
   listed tools (`subscribe_digest`, `subscribe_watchlist`, `register_user`,
   `update_user`, `add_user_auth`, `remove_user_auth`) lack a `confirm`
   parameter in their Gemini declarations, so the guard would be a no-op
   for them. Extending two-phase preview/confirm UX to those is tracked
   separately as **TD-bot-confirm-coverage-completeness** (out of scope:
   would blow Session G from ~150 LOC / ~10 tests to ~400+ LOC / ~25+
   tests).
3. **§ 7 R-1 mitigation** — contract test now bidirectional (`forall tool t:
   t has confirm BOOLEAN ⇔ t ∈ _WRITE_TOOLS_REQUIRING_CONFIRM`).

### Locked decisions (do not relitigate)

- **A** — trim variant for `_WRITE_TOOLS_REQUIRING_CONFIRM` (vs B — extend
  confirm coverage in this session).
- **X** — prompt-fix landed as doc-only commit on `main` directly (mirrors
  `d322afc` precedent). Implementation branch starts from corrected `main`.

### Implementation session opener

Open a fresh chat and paste:

> Стартую Session G — fix BUG-009 execute_tool ConfirmFlow guard.
> Pre-flight завершён в предыдущем окне (см. handover block в начале
> `docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`).
> Прочитай start prompt целиком + `BUG_LOG.md § BUG-009`, и исполни § 3
> (guard → wiring → prompt v1.4.0 → tests → verify → PR → deploy → closure).
> Branch: `fix/bug-009-execute-tool-guard-2026-05-01`. Локированные
> решения: **A** (trim _WRITE_TOOLS до 7), **X** (prompt-fix уже на main).

---

**Назначение:** закрыть BUG-009 структурно — добавить server-side guard в
`tg_parser/bot/tools.py:execute_tool`, отвергающий вызовы write-tool'ов с
`confirm=True` без matching `ConfirmFlow.awaiting_confirmation` FSM state.

**Источник:** [BUG_LOG.md § BUG-009](BUG_LOG.md), live production trace
2026-04-30 15:15:44 UTC, Phase B-(b) prompt-only mitigation (`prompts/bot.yaml`
v1.2.0 → v1.3.0) задеплоен 2026-04-30 15:59:41 UTC.

**Tracker:** GH issue [#49](https://github.com/AlexEfimov/TG_parser/issues/49)
(parent BUG: [#45](https://github.com/AlexEfimov/TG_parser/issues/45)).

**Тип сессии:** writing — code, tests, prompt update (мелкий — версия), PR.
Самая узкая из BUG-fix-сессий: единственный новый contract в `execute_tool`
плюс wiring через `agent.py` и `handlers.py`. ~1.5–2 часа.

**Дата подготовки промпта:** 2026-04-30 22:55 UTC+4 (Session F closure
вечер). Готов к старту утром 2026-05-01 после Session F watch closure.

**Когда использовать:** ТОЛЬКО после того как:

1. Session F watch closure verified (≥24 часа после deploy `88e4337` =
   2026-04-30 15:12 UTC → closure window opens **2026-05-01 15:12 UTC**).
   Verification path:
   ```bash
   ssh prod 'docker exec tg_parser_prometheus wget -qO- \
     "http://localhost:9090/api/v1/query?query=tg_bot_gemini_empty_parts_total" \
     | python3 -m json.tool'
   # Expected: empty result vector OR isolated finishReason=STOP only.

   ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 | grep -cE \
     "gemini_empty|gemini_no_candidates|gemini_blocked"'
   # Expected: 0
   ```
   Если spike → re-open BUG-006/Session F regression investigation, отложить
   Session G до post-investigation.

2. **`BUG_LOG.md` § BUG-009 прочитано целиком** (включая reproduction trace
   2026-04-30 15:15:44 UTC и «Why CI didn't catch» секцию).

3. Production state confirmed clean: `tool=add_channel` log scrape за 24h
   возвращает 0 (BUG-009 prompt mitigation v1.3.0 держится — см. checks
   2026-04-30 22:51 UTC).

---

## 0. Why this session is small

Session F (read-hardening) был ~98 тестов / 6 файлов / shared util. Session G
ощутимо уже:

- **Single contract change**: `execute_tool` принимает новый optional kwarg
  `confirm_flow_state` (typed). Default `None` → preserves Session D's
  agent-loop behaviour.
- **Single guard rule**: write-tool + `confirm=True` + FSM state mismatch =
  typed reject (`error_class="ConfirmFlowMismatch"`). Mismatch = `tool_name`
  не совпал ИЛИ `args` (без `confirm`) не совпали с тем что было в state.
- **Two call-site updates**: handlers.py `_handle_confirmation_response`
  (передаёт state), agent.py `process_message` (НЕ передаёт state — LLM
  calls идут без FSM context, что и было целью).
- **Prompt update минимальный**: `prompts/bot.yaml` v1.3.0 → v1.4.0,
  bump description («BUG-009 mitigation now defended structurally»). Хард-
  rule bullets из v1.3.0 остаются (defense-in-depth).
- **Tests**: ~10 unit tests в `tests/test_bot_tools.py` или новый
  `tests/test_bot_execute_tool_guard.py` + 1 integration test в
  `tests/test_bot_fsm.py` (regression: «da X» after suggestion → if LLM
  hallucinates confirm=True → reject).

Estimate ~150 LOC + ~10 tests, ~1.5–2 часа. Lower complexity than Session E
(empty-parts classification, ~14 tests + Prometheus metric) или Session F
(98 tests across 4 classes).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

> **Note:** line numbers verified 2026-04-30 после Session F+TD#53 landing
> (HEAD `d322afc`). Перепроверить если есть commits между подготовкой
> промпта и стартом сессии (`git log --since="2026-04-30 22:55 UTC+4"`).

1. `docs/notes/BUG_LOG.md` § BUG-009 — full entry (severity, status, root
   cause, reproduction trace 15:15:44 UTC, why CI didn't catch, proposed fix,
   mitigation history). Особое внимание на **«Why CI didn't catch»** —
   там перечислены три gap'а в существующих тестах, каждый из которых
   нужно закрыть в этой сессии.
2. `docs/notes/BUG_LOG.md` § BUG-002 (Session D landed) — родительский
   context-loss class. BUG-009 — специфичный manifestation: «LLM-issued
   `confirm=True` without matching FSM state». Session D закрыла
   deterministic-execute path; BUG-009 закрывает inverse failure mode.
3. `tg_parser/bot/tools.py` L762–833 — текущий `execute_tool` (Session F
   typed-catch). Здесь добавляем guard. Read fully.
4. `tg_parser/bot/handlers.py` L8–25 (FSM contract docstring — BUG-002 +
   BUG-004 closure rationale), L270–340 (`_handle_confirmation_response`).
   Это сторона, которая ЗАКОННО зовёт `execute_tool(name, {..., "confirm":
   True})` — она должна передавать `confirm_flow_state`.
5. `tg_parser/bot/agent.py` L138–310 (`process_message` agent loop). LLM
   tool calls идут отсюда. После guard — LLM-issued `confirm=True` без
   FSM state будет deterministically rejected.
6. `tg_parser/bot/states.py` — `ConfirmFlow.awaiting_confirmation` state
   data shape (`{tool_name: str, args: dict[str, Any], created_at: datetime}`).
   Нужен matching contract.
7. `prompts/bot.yaml` v1.3.0 (current production) — две HARD RULE bullets +
   Suggestion-confirmation flow bullet. После Session G они остаются как
   defense-in-depth, но добавляется явное упоминание structural guard
   (description bump).
8. `tests/test_bot_fsm.py` — Session D regression suite (67 tests). Особое
   внимание на `test_yes_after_remove_preview_does_not_call_add_channel`
   (BUG-002 direct regression) — Session G добавляет sibling
   `test_yes_after_suggestion_does_not_call_add_channel` (BUG-009 direct
   regression).

### 1.2 Required state

- Local repo на `origin/main` HEAD (≥ `d322afc`, Session F + TD #53 + closure
  doc landed). `git status` clean.
- VPS на `ec52060` (PR #54 deploy SHA). `d322afc` — doc-only, deploy не
  обязателен.
- Session F watch closure GREEN (см. § 0).
- Branch convention: `fix/bug-009-execute-tool-guard-2026-05-01`.

### 1.3 Gating decisions (recap from Session F backlog drafting)

- **G-1 (default).** Guard pattern: optional kwarg `confirm_flow_state` в
  `execute_tool`. Default `None` → backwards-compatible с agent-loop. Альт:
  query FSM context напрямую (но это binds tools.py к aiogram FSMContext,
  плохая layering; обоснование на default'е).
- **G-2 (default).** Match contract: exact `tool_name` + exact `args`
  modulo `confirm` (i.e. `{**state.args, "confirm": True} == call.args`).
  Альт: subset matching (state.args ⊂ call.args) — отвергнут, открывает
  attack vector через injected extra args.
- **G-3 (default).** Mismatch response: typed `error_class="ConfirmFlowMismatch"`
  + structured `error` message naming the mismatch reason (tool_name vs
  args). LLM получает специфичный класс, может извиниться корректно.
  Альт: exception raise — отвергнут, ломает existing typed-catch contract
  Session F.
- **G-4 (default, post pre-flight 2026-05-02).** Write-tool list:
  hardcoded в `tools.py` (`_WRITE_TOOLS_REQUIRING_CONFIRM = {"add_channel",
  "remove_channel", "pause_channel", "resume_channel", "trigger_pipeline",
  "set_llm_config", "reset_llm_config"}` — **7 tools**). Set покрывает
  только те tool'ы, чей Gemini-schema уже содержит `confirm: BOOLEAN`
  parameter (audit pre-flight 2026-05-02). Расширение coverage на
  `subscribe_digest`, `subscribe_watchlist`, `register_user`, `update_user`,
  `add_user_auth`, `remove_user_auth` — отдельный TD-bot-confirm-coverage-
  completeness (out of scope, ~400+ LOC). Sync с system prompt list. Альт:
  derive из tool declarations metadata — отвергнут, требует refactor
  TOOL_DECLARATIONS shape (out of scope).
- **G-5 (default).** Regression test target: 67 existing FSM tests must
  remain green. New tests добавляются в `tests/test_bot_fsm.py` (FSM-aware,
  same module как BUG-002) ИЛИ в новый `tests/test_bot_execute_tool_guard.py`
  (если получится >10 тестов — split). Default — same module, threshold
  для split = 12 тестов.

---

## 2. Reproduction context

### 2.1 BUG-009 production trace (2026-04-30 15:15:44 UTC, before mitigation)

```
[15:15:34] User:  каковы основные темы канала AgeManagement ?
[15:15:38] Bot:   list_topics(channel_id="AgeManagement")
                  → total=0, available_channel_ids=[..., "AgeManagment", ...],
                    suggestion="Возможно, имелся в виду 'AgeManagment'?
                                (вы запросили 'AgeManagement')"
[15:15:38] Bot:   К сожалению, я не нашел тем для канала "AgeManagement".
                  Возможно, имелся в виду 'AgeManagment'? Также есть:
                  AgeManagment, Lab4health, LongevityClub, ...
[15:15:42] User:  да AgeManagment
[15:15:44] Bot:   Я собираюсь добавить канал "AgeManagment" в систему.
                  ❌  ← BUG-009 manifests: add_channel(confirm=False) emitted
                       (should have re-run list_topics(channel_id="AgeManagment"))
                  Действие: Создать новый канал.
                  Подтвердите, пожалуйста: "да" или "нет".
[15:15:50] User:  нет
[15:15:51] Bot:   Действие отменено.   ← FSM correctly cancelled
```

В этом trace LLM выдал `add_channel(confirm=False)` — это **fresh preview**,
не `confirm=True` issue. Однако структурный guard всё равно нужен — потому
что Gemini может (и в edge cases будет) выдавать **`add_channel(confirm=True)`**
напрямую при context-loss (см. BUG-002 update 2026-04-28 00:04 trace, где
LLM выдал `remove_channel("test_channel", confirm=True)` после preview
`set_llm_config`). Современная prompt v1.3.0 mitigation покрывает текущий
attack surface, но не закрывает структурно — Gemini hallucination class
non-deterministic.

### 2.2 What v1.3.0 prompt mitigation does NOT cover

Prompt v1.3.0 (Phase B-(b), 2026-04-30) добавил:
- Hard rule в Instructions: «NEVER call any write tool with confirm=true
  yourself».
- Standalone HARD RULE в Confirmation semantics с упоминанием BUG-009.
- Suggestion-confirmation flow: «da X» after suggestion → re-run THE SAME
  read-tool, NOT a write-tool.

**Чего prompt НЕ делает:**
- Не block'ает на server-side (если LLM игнорирует rule на edge case —
  бот всё равно execute'нит).
- Не emit'ит typed error class на violation (`error_class` остаётся
  `"AnthropicAPIError"` или другой downstream класс, не `"ConfirmFlowMismatch"`).
- Не учит prompt о том, что server-side guard теперь ловит violations
  явно (post-Session-G prompt update подскажет LLM пересоздавать поток
  через preview если он по ошибке выдал confirm=true).

### 2.3 Phase B-(b) sanity check (2026-04-30 16:01 UTC) — confirms mitigation works

- F-1 BUG-002 confirm-flow regression guard: `Удали канал mind_rise` →
  preview → user «нет» → cancelled. **PASS** (Session D FSM intact).
- BUG-009 mitigation: typo `AgeManagement` → suggestion → user «да
  AgeManagment» → bot calls `list_topics(AgeManagment)`, NOT `add_channel`.
  **PASS** (prompt v1.3.0 holds).

После Session G сюда добавится: structural guard test — turn 1 LLM (mock)
returns suggestion → turn 2 «да X» → IF mock LLM is forced to call
`add_channel(confirm=True)` → execute_tool returns `error_class="ConfirmFlowMismatch"`,
no DB write happens.

---

## 3. Implementation plan

### 3.1 Step 1 — Add the guard (10 мин)

`tg_parser/bot/tools.py`:

1. Define hardcoded set (7 tools — see § 1.3 G-4 for trim rationale):
   ```python
   # BUG-009 (Session G): write-tools whose Gemini declarations carry a
   # `confirm: BOOLEAN` parameter — these are the tools the FSM ConfirmFlow
   # protects via two-phase preview/confirm. The guard below rejects any
   # call to one of these with confirm=True that is not paired with a
   # matching FSM snapshot. Extending coverage to subscribe_*, register_*,
   # *_user_auth tools is tracked as TD-bot-confirm-coverage-completeness.
   _WRITE_TOOLS_REQUIRING_CONFIRM: frozenset[str] = frozenset({
       "add_channel",
       "remove_channel",
       "pause_channel",
       "resume_channel",
       "trigger_pipeline",
       "set_llm_config",
       "reset_llm_config",
   })
   ```
   Place near top of file, after imports.

2. Add typed dataclass или `TypedDict` for FSM-state contract:
   ```python
   class ConfirmFlowSnapshot(TypedDict):
       tool_name: str
       args: dict[str, Any]   # without "confirm" — the original preview args
   ```
   Place near `_TOOL_EXECUTORS` def. Reused by handlers.py wiring.

3. Modify `execute_tool` signature:
   ```python
   async def execute_tool(
       name: str,
       args: dict[str, Any],
       timeout: float = 60.0,
       current_user: CurrentUser | None = None,
       bot: Bot | None = None,
       chat_id: int | None = None,
       confirm_flow_state: ConfirmFlowSnapshot | None = None,
   ) -> dict[str, Any]:
   ```

4. Add guard at the top of the function (before unknown-tool check, after
   `executor = _TOOL_EXECUTORS.get(name)` to know the name is well-formed):
   ```python
   # BUG-009 (Session G): server-side guard — LLM cannot bypass FSM
   # confirmation by calling write-tool with confirm=True directly.
   # The framework (handlers._handle_confirmation_response) is the only
   # entity allowed to set confirm=True; it must pass confirm_flow_state
   # matching the previewed action. See BUG_LOG.md § BUG-009.
   if (
       name in _WRITE_TOOLS_REQUIRING_CONFIRM
       and args.get("confirm") is True
   ):
       expected_args = {**(confirm_flow_state.get("args", {}) if confirm_flow_state else {}), "confirm": True}
       if confirm_flow_state is None:
           return {
               "error": (
                   f"Tool '{name}' was called with confirm=True without an "
                   f"active ConfirmFlow FSM state. The framework owns this "
                   f"path; LLM-issued confirm=True is rejected (BUG-009)."
               ),
               "error_class": "ConfirmFlowMismatch",
           }
       if confirm_flow_state["tool_name"] != name:
           return {
               "error": (
                   f"ConfirmFlow tool mismatch: state holds "
                   f"'{confirm_flow_state['tool_name']}' but call is "
                   f"'{name}'. Rejecting (BUG-009)."
               ),
               "error_class": "ConfirmFlowMismatch",
           }
       if expected_args != args:
           # Compute diff for diagnostic clarity.
           extra = {k: args[k] for k in args.keys() - expected_args.keys()}
           missing = {k: expected_args[k] for k in expected_args.keys() - args.keys()}
           changed = {
               k: (expected_args.get(k), args.get(k))
               for k in expected_args.keys() & args.keys()
               if expected_args[k] != args[k]
           }
           return {
               "error": (
                   f"ConfirmFlow args mismatch for '{name}': "
                   f"extra={extra} missing={missing} changed={changed}. "
                   f"Rejecting (BUG-009)."
               ),
               "error_class": "ConfirmFlowMismatch",
           }
       # Match — fall through to actual execution.
   ```

### 3.2 Step 2 — Wire from handlers (5 мин)

`tg_parser/bot/handlers.py:_handle_confirmation_response` — единственная
legitimate confirm=True call-site. Changes:

```python
# Before (current Session D wiring):
result = await execute_tool(
    tool_name,
    {**pending_args, "confirm": True},
    current_user=current_user,
    bot=bot,
    chat_id=chat_id,
)

# After Session G:
result = await execute_tool(
    tool_name,
    {**pending_args, "confirm": True},
    current_user=current_user,
    bot=bot,
    chat_id=chat_id,
    confirm_flow_state={
        "tool_name": tool_name,
        "args": pending_args,
    },
)
```

`agent.py:process_message` — NO changes. Agent loop never passes
`confirm_flow_state`, so any LLM-issued `confirm=True` will be rejected by
the guard. Это и есть точка фиксации BUG-009.

### 3.3 Step 3 — Prompt update (5 мин)

`prompts/bot.yaml` v1.3.0 → v1.4.0:
- Bump version + description: «Session G structural guard для BUG-009 active;
  prompt-side hard rules остаются для defense-in-depth».
- Optionally — add bullet в § Confirmation semantics: «If you accidentally
  call a write-tool with confirm=true, you will receive `error_class:
  "ConfirmFlowMismatch"` — recover by calling the tool again with
  confirm=false to re-issue a preview». Это учит LLM gracefully recover.
- Все existing v1.3.0 hard rules **сохраняются**. Не удаляем.

### 3.4 Step 4 — Tests (45–60 мин)

Новый module `tests/test_bot_execute_tool_guard.py` (если 10+ tests
ожидаются) ИЛИ extend `tests/test_bot_fsm.py` (если ≤10).

Required test cases:

**Class A — Guard reject paths (BUG-009 closure)**

1. `test_llm_issued_confirm_true_without_state_rejected` — call
   `execute_tool("add_channel", {"channel_id": "X", "confirm": True})`
   without `confirm_flow_state` kwarg → returns
   `{"error_class": "ConfirmFlowMismatch", "error": "...without an active
   ConfirmFlow FSM state..."}`. No DB write happens (mock executor not
   reached).

2. `test_tool_name_mismatch_rejected` — call
   `execute_tool("remove_channel", {"channel_id": "X", "confirm": True},
   confirm_flow_state={"tool_name": "add_channel", "args": {"channel_id": "X"}})`
   → `error_class="ConfirmFlowMismatch"`, mentions both tool names in
   error.

3. `test_args_mismatch_rejected_extra_keys` — call with extra arg not in
   state → reject, error mentions `extra=` diff.

4. `test_args_mismatch_rejected_missing_keys` — call with missing arg →
   reject, error mentions `missing=` diff.

5. `test_args_mismatch_rejected_changed_value` — call with same keys but
   different value → reject, error mentions `changed=` diff.

**Class B — Guard pass paths (Session D regression preservation)**

6. `test_legitimate_confirm_via_handler_executes` — `execute_tool(
   "add_channel", {"channel_id": "X", "confirm": True},
   confirm_flow_state={"tool_name": "add_channel",
   "args": {"channel_id": "X"}})` → executor IS called, returns success
   payload. Direct regression for Session D `_handle_confirmation_response`.

7. `test_read_tool_with_confirm_true_passthrough` — read-tool like
   `list_topics({"channel_id": "X", "confirm": True})` → guard does NOT
   apply (read-tools not in `_WRITE_TOOLS_REQUIRING_CONFIRM`), executor
   called normally.

8. `test_write_tool_with_confirm_false_passthrough` — `add_channel(
   {"channel_id": "X", "confirm": False})` → guard does NOT apply (this
   is a preview), executor called normally.

**Class C — Edge cases**

9. `test_confirm_true_with_state_for_unknown_tool` — guard runs ONLY for
   tools in `_WRITE_TOOLS_REQUIRING_CONFIRM`; unknown tools fall through
   to existing `Unknown tool` error (`error_class="UnknownTool"`).

10. `test_state_with_extra_unrelated_keys_passes_diff` — if
    `confirm_flow_state["args"]` is dict and call args + confirm matches
    exactly, guard passes regardless of dict ordering.

**Class D — Integration test (FSM end-to-end)**

11. `test_yes_after_suggestion_does_not_call_add_channel` (in
    `tests/test_bot_fsm.py`) — Direct BUG-009 regression. Mock
    GeminiAgent: turn 1 returns `list_topics` result with `suggestion=...`
    → turn 2 user replies «да X» → IF the mock agent is forced to call
    `add_channel(confirm=True)` (simulating BUG-009) → result must be
    `error_class="ConfirmFlowMismatch"`, no `_exec_add_channel` call,
    no DB row, user-facing message via `_format_tool_result` is
    «❗ ...» error (LLM-formatted via existing fallback path).

### 3.5 Step 5 — Verification

- Polный pytest (default mode): expected ≥1990 passed (1980 baseline +
  10–11 new). 0 regressions.
- `ruff check`, `ruff format --check` clean.
- Direct symptom-test: 67 Session D FSM tests must remain green
  (regression guard).
- Manual validation note for PR description: trace the BUG-009 production
  scenario through the test suite — `test_yes_after_suggestion_does_not_call_add_channel`
  is the direct regression for 2026-04-30 15:15:44 UTC trace.

---

## 4. Out of scope

- **#50** (TD-bot-source-username-alias, BUG-010 structural) — separate
  session; touches `IngestionStateRepo`, not bot. Quick-win batch
  candidate.
- **#51** (TD-bot-read-context-preservation, BUG-011) — Session H, larger
  refactor (read-context FSM).
- **#52** (TD-prompt-suggestion-format-clarity, BUG-012) — can be batched
  with this session's prompt update IF time permits (~30 мин); default —
  separate small PR.
- **TD-storage-jsonb-channel-id** (Session F D-5 deferred) — storage-side
  fuzzy match for BUG-007. Independent track.

---

## 5. PR / deploy / closure pattern (mirrors Session E/F)

1. Branch: `fix/bug-009-execute-tool-guard-2026-05-01`.
2. Commits: 1 atomic per logical change (guard, wiring, prompt, tests) =
   4 commits → squash on merge. Or all-in-one if review prefers.
3. PR title: `fix(bug-009): server-side execute_tool ConfirmFlow guard +
   regression tests`.
4. PR body — mirror Session F structure:
   - Closes: BUG-009 (#45), TD-bot-execute-tool-confirm-guard (#49).
   - Test plan checklist.
   - Smoke verification stub for post-deploy.
   - Out of scope.
5. Merge: squash, delete branch.
6. Deploy: same pattern as Session F deploy. Single line:
   ```bash
   ssh prod 'cd ~/TG_parser && git pull --ff-only origin main \
     && docker compose build tg_parser \
     && docker compose up -d --no-deps --force-recreate tg_bot'
   ```
   Only `tg_bot` needs restart (guard is in tools.py, used by bot agent
   loop and handlers). `mcp` and `tg_parser_api` use `execute_tool` only
   via shared module, but the guard is no-op for read-tools — so MCP
   container is technically also affected if any MCP tool path calls
   `execute_tool`. Verify by `rg "execute_tool" tg_parser/` before deploy.
7. Post-deploy smoke:
   - Synthetic test inside `tg_parser_bot` container:
     ```bash
     ssh prod 'docker exec tg_parser_bot python3 -c "
     import asyncio
     from tg_parser.bot.tools import execute_tool

     async def main():
         result = await execute_tool(
             \"add_channel\",
             {\"channel_id\": \"X\", \"confirm\": True},
         )
         print(result)

     asyncio.run(main())
     "'
     # Expected: {"error_class": "ConfirmFlowMismatch", "error": "...without an active..."}
     ```
   - Real-world smoke via Telegram bot: «темы канала AgeManagement» →
     suggestion → «да AgeManagment» → expected: `list_topics` (NOT
     `add_channel`); IF Gemini hallucinated `add_channel(confirm=True)`
     anyway → server returns ConfirmFlowMismatch, bot delivers «❗ Произошла
     ошибка...» to user (graceful degradation).
   - Verify Session D regression: `Удали канал mind_rise` → preview →
     «да» → soft-delete works (FSM legitimate path passes guard).
8. BUG_LOG.md update — move BUG-009 from § Active bugs to § Resolved bugs;
   update Bug → session mapping table; add Session G entry to § Updates
   log.
9. CHANGELOG.md — new Session G section under [Unreleased].
10. Close issues #45 (BUG-009 bug) + #49 (TD).

---

## 6. Acceptance criteria (the «we can stop» line)

- ✅ All 67 existing `tests/test_bot_fsm.py` tests still pass (Session D
  regression guard).
- ✅ All 10–11 new tests in Session G PASS.
- ✅ Full pytest (default mode) ≥1990 passed (1980 baseline + 10–11 new),
  0 regressions.
- ✅ `ruff check` + `ruff format --check` clean.
- ✅ Manual smoke (synthetic) in production container returns
  `error_class="ConfirmFlowMismatch"`.
- ✅ Manual smoke (real Telegram bot) — «да X»-after-suggestion routes to
  `list_topics` correctly (prompt v1.3.0/v1.4.0 + guard combined).
- ✅ Session D regression — `Удали канал mind_rise` flow works end-to-end
  (legitimate path).
- ✅ BUG_LOG.md + CHANGELOG.md updated, issues #45 + #49 closed.

---

## 7. Risks / known unknowns

- **R-1 (low):** if a future write-tool is added without being added to
  `_WRITE_TOOLS_REQUIRING_CONFIRM`, the guard silently doesn't apply →
  BUG-009 reopens for that tool. Mitigation: **bidirectional** contract
  test asserting `forall tool t: t has confirm BOOLEAN parameter in its
  Gemini declaration ⇔ t ∈ _WRITE_TOOLS_REQUIRING_CONFIRM`. Forward
  direction catches the original failure mode (new write-tool not added
  to the set); reverse direction catches accidental over-trim during
  future refactors (set still contains a tool whose confirm parameter
  was removed). Session G must include this static test in
  `tests/test_bot_execute_tool_guard.py` (or wherever the test module
  lands per § 3.4 split-threshold rule).
- **R-2 (low):** if `args` ordering changes between preview and confirm
  call (unlikely but possible if dict mutation happens upstream), exact
  match fails → false negative reject. Mitigation: match contract uses
  `==` on dicts (order-insensitive in Python). Plus integration test
  covering this case.
- **R-3 (medium):** existing tests that mock `execute_tool` directly
  (`@patch("tg_parser.bot.tools.execute_tool")`) won't trigger the guard
  — they pass mock args directly. NOT a regression because the goal is
  to test downstream behaviour, not the guard. But: if Session F or
  earlier tests passed `confirm=True` to a real `execute_tool` call
  expecting the executor to run, they'll now fail with ConfirmFlowMismatch.
  **Pre-Session-G grep**:
  ```bash
  rg 'execute_tool\([^)]*confirm[^)]*True' tests/
  ```
  Update any such test to either pass `confirm_flow_state` or use a
  mocked executor directly.

---

## 8. Stop-the-world conditions

If during the session one of the following becomes true, **STOP** and
escalate:

- BUG-002 regression test (`test_yes_after_remove_preview_does_not_call_add_channel`)
  starts FAILING. Means our guard breaks Session D legitimate path.
- More than 5 of the 67 existing FSM tests fail with ConfirmFlowMismatch.
  Means handler-side wiring is incomplete.
- `prompts/bot.yaml` parsing fails after v1.4.0 bump (YAML validation
  in tests).
- Session F or TD #53 metric (`tg_bot_gemini_empty_parts_total`) spikes
  during Session G implementation (could indicate a different regression
  has snuck in).

---

## 9. Reference materials

- BUG_LOG.md § BUG-009 — primary spec.
- BUG_LOG.md § BUG-002 (resolved Session D) — родительский context-loss
  class, scaffolding precedent.
- BUG_LOG.md § BUG-005-B (resolved Session F) — typed-catch contract в
  `execute_tool` (наш guard-output reuses `error_class` field convention).
- `tg_parser/bot/tools.py:execute_tool` — current implementation, our edit
  surface.
- `tg_parser/bot/handlers.py:_handle_confirmation_response` — legitimate
  call-site, our wiring target.
- `tg_parser/bot/states.py:ConfirmFlow` — FSM state shape contract.
- `tests/test_bot_fsm.py::test_yes_after_remove_preview_does_not_call_add_channel`
  — direct precedent for our new test.
- DEPLOY_CHECKLIST_SESSION_F_2026-04-30.md § Phase B-(b) — BUG-009 prompt
  mitigation history.
- GH issue [#49](https://github.com/AlexEfimov/TG_parser/issues/49) — TD
  tracker, contains the same plan in shorter form for at-a-glance
  reference.
