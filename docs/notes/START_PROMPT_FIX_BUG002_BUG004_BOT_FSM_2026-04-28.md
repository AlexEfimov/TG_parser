# Fix Sprint — BUG-002 (full FSM) + BUG-004 (pagination) Bot State (Session D, 2026-04-28)

**Назначение:** закрывает Critical-баг **BUG-002** (statelessness bot'а
ведёт к hallucination'у на «да»-confirm'е) и Medium-баг **BUG-004**
(pagination теряет channel-context). Оба бага — следствие одной
архитектурной дыры: у bot'а нет conversation state. Делаются вместе
потому что shared scaffolding (FSMContext + StateGroup pattern).

После Session B+ severity BUG-002 уже снижена до High, но архитектурный
gap остаётся. Эта сессия закрывает его properly.

**Тип сессии:** writing — code, tests, prompt updates, PR. **Самая
объёмная** из BUG-fix-сессий (~4-5 ч).

**Дата подготовки промпта:** 2026-04-27.

**Когда использовать:** **только** после того как:

1. Phase 1 / Phase 2 / Session B+ landed.
2. Session C **может** быть в работе параллельно (independent track) или
   уже landed.
3. `BUG_LOG.md` § BUG-002 (особенно § Proposed fix Variant B) и § BUG-004
   прочитаны целиком; D4 default (`MemoryStorage`) подтверждён или
   пересмотрен.

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/BUG_LOG.md` § BUG-002 — целиком, **особенно**:
   - § «Root cause (проверенный)» — три гарантии statelessness'а.
   - § «Proposed fix» Variant B — FSMContext + storage (это и есть scope).
   - § «Mitigation backlog» — что уже сделано в Session B+ (M1+M2+M3).
2. `docs/notes/BUG_LOG.md` § BUG-004 — целиком, **особенно**:
   - § «Root cause» — три уровня (FSM + LLM-prompt + numbering).
   - § «Proposed fix» — pagination state piggybacks на BUG-002 scaffolding.
3. `docs/notes/BUG_LOG.md` § Session planning — D4 default (MemoryStorage).
4. `tg_parser/bot/main.py:98–212` — `run_bot()`, `Dispatcher()` initialization.
   Это место куда внедряем `MemoryStorage`.
5. `tg_parser/bot/handlers.py:89–149` — `cmd_start`, `cmd_help`, `handle_text`.
   `handle_text` — основной hot-path, требует FSM-aware-refactor.
6. `tg_parser/bot/agent.py:36–192` — `GeminiAgent.process_message` и
   `_call_gemini`. На текущий момент функция stateless; будет принимать
   `conversation_history` опционально для full-context передачи.
7. `tg_parser/bot/tools.py:759–800` — `execute_tool` wrapper. Анализ: какие
   tool'ы возвращают `preview=True` payload (=> нужен FSM-trigger).
8. `tg_parser/bot/tools.py:854–906` — `_exec_list_topics` (BUG-004 hot-path);
   в этой сессии добавляется numbering + pagination FSM-trigger.
9. `prompts/bot.yaml` — целиком; будет добавлена секция
   «pagination & confirmation handling».
10. **aiogram docs** — `aiogram.fsm.context.FSMContext`, `aiogram.fsm.state.StatesGroup`,
    `aiogram.fsm.storage.memory.MemoryStorage`. Найти примеры в codebase
    (`rg "FSMContext|StatesGroup" tg_parser/`) — возможно уже есть
    вспомогательные паттерны.

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. Phase 1/2 + Session B+ landed
git log --oneline main -30 | rg "Session B\+|BUG-002 mitigations"
rg "Session B\+ \(2026" docs/notes/BUG_LOG.md

# 2. Session C может быть либо landed либо в работе параллельно — оба ок.
#    Если в работе и есть rebase-conflict в mcp_server.py — ОК, это
#    не наш файл; разрешать локально или дождаться.

# 3. Working tree чист, branch
git checkout main
git pull --ff-only origin main
.venv/bin/pytest -q 2>&1 | tail -20  # baseline зелёный

git checkout -b fix/bug-002-bug-004-bot-fsm-2026-04-28
```

### 1.3 Gating decisions (must answer before code-changes)

| ID | Вопрос | Default per BUG_LOG § Session planning |
|---|---|---|
| D-1 | Storage backend: MemoryStorage или Redis? | **MemoryStorage** (single replica, проще; см. D4 default) |
| D-2 | Confirmation parsing: regex / nlp / LLM? | **Regex / lowercased prefix-match** — `да|yes|подтвержд|ok|ага|подтверди` для confirm; `нет|no|отмена|cancel|no` для reject. Просто и детерминированно. |
| D-3 | TTL для pending-action и pagination state | **5 минут** — после этого state очищается; user'у show`ется «pending action expired» если он отвечает после TTL. Это важно — иначе stale state. |
| D-4 | Что делать если user в `awaiting_confirmation` пишет не «да/нет»? | **Очистить state + обработать как новый запрос** через агента. Альтернатива: «вы в ожидании подтверждения, ответьте да/нет» — UX worse. |
| D-5 | Pagination: numbering глобальный или per-page? | **Глобальный** — например, темы 21-40 на странице 2 (а не 1-20 на каждой). Это даёт user'у точку привязки между страницами. |
| D-6 | Pagination max-pages limit? | **Soft-cap 10 страниц** — после 200 items предложить sub-query (filter / channel-filter / search). Hard-cap = 50 на безопасность. |
| D-7 | Conversation history в `process_message`? | **Не сейчас** — BUG-002 и BUG-004 решаются через FSM, а не conversation memory. Conversation history — отдельная feature (см. § 2 out-of-scope), отдельный TD. |

Если у юзера нет blessing'а — взять default и явно сообщить в финальном
summary.

### 1.4 Branch / PR strategy

**Один большой PR**, разделённый на ~5-6 атомарных коммитов:

1. `commit 1: introduce FSMContext + MemoryStorage in Dispatcher`
2. `commit 2: ConfirmFlow state group + handler refactor (BUG-002 fix)`
3. `commit 3: regression tests for two-turn confirm-flow`
4. `commit 4: PaginationFlow state group + list-tools state-trigger (BUG-004 fix)`
5. `commit 5: pagination tests + numbering test`
6. `commit 6: prompts/bot.yaml — confirmation + pagination guidance`

Single PR упрощает review (это одна архитектурная feature: bot
state-management). Дробить не нужно, кроме если в ходе work'а появится
независимая часть (тогда — отдельный PR).

- Branch: `fix/bug-002-bug-004-bot-fsm-2026-04-28`.
- PR title: `fix(bug-002+004): introduce bot FSMContext for confirm-flow and pagination`.
- PR labels: `bug-fix`, `bug-002`, `bug-004`, `bot`, `architecture`.

---

## 2. Out of scope

| Категория | Куда отложить | Причина |
|---|---|---|
| **Conversation memory / chat history persistence** | отдельный feature TD | Не нужно для BUG-002/004 closure'а |
| **Redis-backed FSM storage** | scale-out sprint | См. D-1 default (MemoryStorage) |
| **Multi-bot replicas / leader-election** | scale-out sprint | Один replica сейчас |
| **Voice / image input parsing** | feature sprint | Out of bot-text scope |
| **`/start`, `/help` reformatting** | wontfix | Команды короткие, не требуют FSM |
| **MCP-side pagination consistency** | отдельный TD | MCP-handlers возвращают pagination-data, читать его пользователь должен по-старому |
| **Bot rate-limiting / throttling** | отдельный TD | Уже есть RateLimitMiddleware |
| **Bot Gemini fix (BUG-006)** | Session E | Отдельная сессия, разные code path'ы внутри agent.py |
| **Test_channel hallucination через другой placeholder** | wontfix | Closed by Session B+ M2 reject-list |
| **Изменение tool schemas (TOOL_DECLARATIONS)** | Session E (если необходимо) | Не для BUG-002/004 |
| **Audit log для bot-actions** | feature TD | Logging'а LoggingMiddleware достаточно сейчас |

---

## 3. Sprint scope (Session D)

### 3.1 FSMContext + MemoryStorage в Dispatcher

**Files to touch:**

- `tg_parser/bot/main.py:161` — `Dispatcher()` → `Dispatcher(storage=MemoryStorage())`:

  ```python
  from aiogram.fsm.storage.memory import MemoryStorage

  storage = MemoryStorage()
  dp = Dispatcher(storage=storage)
  ```

  Если в `run_bot()` есть других middleware'ов или handler'ов, которые
  прокидывают state — убедиться что не ломаются.

- `tg_parser/bot/states.py` (новый файл):

  ```python
  """FSM state groups for bot conversation flows."""
  from aiogram.fsm.state import StatesGroup, State


  class ConfirmFlow(StatesGroup):
      awaiting_confirmation = State()


  class PaginationFlow(StatesGroup):
      has_active_list = State()
  ```

### 3.2 BUG-002 fix — ConfirmFlow handler (главный)

**Files to touch:**

- `tg_parser/bot/handlers.py:120–149` — `handle_text` refactor:

  ```python
  from aiogram.fsm.context import FSMContext
  from tg_parser.bot.states import ConfirmFlow, PaginationFlow

  CONFIRM_PATTERNS = re.compile(r"^(да|yes|ок|ok|подтвержд|ага)\b", re.IGNORECASE)
  REJECT_PATTERNS = re.compile(r"^(нет|no|отмена|cancel)\b", re.IGNORECASE)

  async def handle_text(
      message: Message,
      state: FSMContext,
      current_user: CurrentUser | None = None,
  ) -> None:
      current_state = await state.get_state()

      if current_state == ConfirmFlow.awaiting_confirmation.state:
          await _handle_confirmation_response(message, state, current_user)
          return

      # ... обычная обработка через agent.process_message ...
      # NEW: после ответа агента, если result содержит preview-payload,
      # выставить state и сохранить pending action.
  ```

- `tg_parser/bot/handlers.py` — новая функция
  `_handle_confirmation_response`:

  ```python
  async def _handle_confirmation_response(
      message: Message,
      state: FSMContext,
      current_user: CurrentUser | None,
  ) -> None:
      data = await state.get_data()
      pending_action = data.get("pending_action")
      created_at = data.get("created_at")

      # TTL check (D-3 default)
      if created_at and (utcnow() - created_at).total_seconds() > 300:
          await state.clear()
          await message.answer("⏱️ Время на подтверждение истекло. "
                                "Повторите запрос если нужно.")
          return

      text = message.text or ""
      if CONFIRM_PATTERNS.match(text):
          # Execute pending action with confirm=True deterministically —
          # NOT через agent.process_message, чтобы избежать LLM-hallucination.
          tool_name = pending_action["tool_name"]
          args = {**pending_action["args"], "confirm": True}
          result = await execute_tool(tool_name, args, current_user)
          await state.clear()
          await message.answer(_format_tool_result(tool_name, result))
      elif REJECT_PATTERNS.match(text):
          await state.clear()
          await message.answer("❌ Отменено.")
      else:
          # D-4 default: clear state + treat as new message
          await state.clear()
          # Recursively handle as a fresh message
          await handle_text(message, state, current_user)
  ```

- `tg_parser/bot/agent.py` — `GeminiAgent.process_message` должна
  возвращать **structured result** для tool-call'ов с preview, чтобы
  handler мог записать в FSM:

  ```python
  @dataclass
  class AgentResult:
      response_text: str
      preview_pending: dict[str, Any] | None = None  # {tool_name, args}
      pagination_pending: dict[str, Any] | None = None  # {tool_name, args, total, offset}

  # process_message теперь возвращает AgentResult
  ```

  Это требует minor refactor'а внутри `process_message` — после
  tool-call'а, если результат содержит `"preview": True`, заполнить
  `preview_pending`.

- `tg_parser/bot/handlers.py` — после `agent.process_message`:

  ```python
  result = await agent.process_message(...)
  await message.answer(result.response_text)

  if result.preview_pending:
      await state.set_state(ConfirmFlow.awaiting_confirmation)
      await state.update_data(
          pending_action=result.preview_pending,
          created_at=utcnow(),
      )

  if result.pagination_pending:
      await state.set_state(PaginationFlow.has_active_list)
      await state.update_data(
          pagination=result.pagination_pending,
          created_at=utcnow(),
      )
  ```

### 3.3 BUG-004 fix — PaginationFlow handler + numbering

**Files to touch:**

- `tg_parser/bot/handlers.py` — добавить `_handle_pagination_response`:

  ```python
  PAGINATION_NEXT_PATTERNS = re.compile(
      r"^(ещё|еще|next|дальше|следующая|more|continue)\b", re.IGNORECASE
  )
  PAGINATION_STOP_PATTERNS = re.compile(
      r"^(стоп|stop|хватит|enough|закрой)\b", re.IGNORECASE
  )

  async def _handle_pagination_response(
      message: Message, state: FSMContext, current_user: CurrentUser | None
  ) -> None:
      data = await state.get_data()
      pagination = data.get("pagination")
      created_at = data.get("created_at")

      if created_at and (utcnow() - created_at).total_seconds() > 300:
          await state.clear()

      text = message.text or ""
      if PAGINATION_NEXT_PATTERNS.match(text):
          new_offset = pagination["offset"] + pagination["limit"]
          if new_offset >= pagination["total"]:
              await state.clear()
              await message.answer("Это все темы канала.")
              return

          # Soft-cap (D-6 default)
          max_pages = 10
          page_size = pagination["limit"]
          if new_offset >= max_pages * page_size:
              await state.clear()
              await message.answer(
                  f"Показано {new_offset} тем из {pagination['total']}. "
                  "Чтобы увидеть остальные, уточните запрос — например, "
                  "поищите по ключевому слову или укажите конкретный канал."
              )
              return

          updated_args = {**pagination["args"], "offset": new_offset}
          result = await execute_tool(pagination["tool_name"], updated_args, current_user)
          response_text = _format_paginated_result(
              pagination["tool_name"], result, new_offset
          )
          await state.update_data(
              pagination={**pagination, "offset": new_offset},
              created_at=utcnow(),
          )
          await message.answer(response_text)
      elif PAGINATION_STOP_PATTERNS.match(text):
          await state.clear()
      else:
          await state.clear()
          await handle_text(message, state, current_user)
  ```

- `tg_parser/bot/tools.py:854–906` — `_exec_list_topics` modifications:

  В payload результата добавить `pagination_pending: dict[str, Any] | None`:

  ```python
  if total > offset + len(items):
      result["pagination_pending"] = {
          "tool_name": "list_topics",
          "args": {"channel_id": channel_id, "limit": limit, "offset": offset},
          "total": total,
          "offset": offset,
          "limit": limit,
      }
  ```

  Где это нужно: `_exec_list_topics`, `_exec_search`,
  `_exec_list_channels`, `_exec_list_users` (если у них есть pagination).

- `tg_parser/bot/handlers.py` — `_format_paginated_result` и
  `_format_tool_result` — добавить **глобальную нумерацию** (D-5 default):

  ```python
  def _format_paginated_result(tool_name: str, result: dict, offset: int) -> str:
      if tool_name == "list_topics":
          lines = []
          for i, item in enumerate(result["items"], start=offset + 1):
              lines.append(f"{i}. {item['title']} ({item['document_count']} док.)")
          ...
          return "\n".join(lines)
      ...
  ```

### 3.4 System prompt update (`prompts/bot.yaml`)

**Files to touch:**

- `prompts/bot.yaml` — добавить секцию (не overwrite, **дополнить** существующую
  `system.prompt`):

  ```yaml
  system:
    prompt: |
      ... existing prompt ...

      ## Pagination и нумерация

      При отображении списка items (`list_topics`, `list_channels`,
      `list_users`, `search`) — если в результате есть
      `pagination_pending`, ОБЯЗАТЕЛЬНО:
      1. Показать первые N items с **глобальной нумерацией**:
         `1. item_one`, `2. item_two`, etc.
      2. В конце сообщения добавить строку:
         «Всего N items. Показаны 1–{count}. Чтобы увидеть следующие,
         напишите "ещё".»
      3. **Не** возвращать pagination_pending payload в текст — он
         используется handler'ом для FSM, не для пользователя.

      ## Confirmation

      Никогда не повторяй tool-call с `confirm=True` после preview.
      Handler автоматически выполнит подтверждённое действие на
      следующем сообщении пользователя — твоя задача только
      сформулировать preview-message правильно.
  ```

  **Важно**: это **гайдлайны для LLM**, а не контракт. FSM-handler ведёт
  себя детерминированно даже если LLM нарушит. System prompt просто
  улучшает UX.

### 3.5 Tests

**Files to touch:**

- `tests/test_bot_fsm.py` (новый файл):

  - **Confirm-flow tests:**
    - `test_first_turn_returns_preview_sets_state`: первый turn возвращает
      preview tool-call → `state == ConfirmFlow.awaiting_confirmation`,
      `pending_action` записан.
    - `test_yes_executes_pending_action_with_confirm_true`: state
      `awaiting_confirmation`, message «да» → tool вызван с теми же args
      + `confirm=True`, state очищен.
    - `test_no_clears_state`: state, message «нет» → state очищен,
      tool не вызван.
    - `test_unrelated_text_clears_state_and_routes_to_agent`: state,
      message «покажи каналы» → state очищен, route в agent (D-4 default).
    - `test_ttl_expiry`: state установлен, прошло > 300 sec, любое
      сообщение → state очищен, ответ «время истекло».
    - **Hallucination protection** (regression для BUG-002):
      `test_yes_does_not_call_llm_for_confirmation`: mock LLM с
      assertion что process_message **не вызван** в ConfirmFlow path.

  - **Pagination-flow tests:**
    - `test_list_topics_returns_pagination_pending`: list_topics с
      `total > limit` → `pagination_pending` в результате.
    - `test_eshche_increments_offset_correctly`: state установлен с
      offset=0, message «ещё» → tool вызван с offset=20.
    - `test_global_numbering`: page 2 — items нумерованы 21-40, не 1-20.
    - `test_max_pages_softcap`: после 10 страниц предложение sub-query.
    - `test_stop_clears_pagination_state`: state установлен, message
      «стоп» → state очищен.

- `tests/test_rag_prompt_config.py:947–977` — обновить под новый shape
  `process_message` (возвращает `AgentResult`).

---

## 4. Per-step playbook

### 4.1 FSMContext infra (3.1)

```bash
# 1. New file: tg_parser/bot/states.py — две StateGroup'ы.
# 2. Edit tg_parser/bot/main.py:161 — Dispatcher(storage=MemoryStorage()).

# 3. Smoke
.venv/bin/pytest tests/test_bot*.py -q -v
# В этой точке тестов FSM ещё нет, но baseline должен пройти.

# 4. Commit
git commit -m "fix(bug-002+004) part 1/6: introduce MemoryStorage + StateGroups

Adds aiogram MemoryStorage to Dispatcher and defines ConfirmFlow /
PaginationFlow state groups in tg_parser/bot/states.py. No behavior
change yet — scaffolding for follow-up commits.

Refs: BUG_LOG.md BUG-002 + BUG-004, Session D."
```

### 4.2 ConfirmFlow handler (3.2 + 3.3 confirm-related)

```bash
# 1. Edit tg_parser/bot/handlers.py — handle_text + _handle_confirmation_response.
# 2. Edit tg_parser/bot/agent.py — AgentResult dataclass, process_message refactor.
# 3. Tests: tests/test_bot_fsm.py — добавить confirm-flow секцию.

.venv/bin/pytest tests/test_bot_fsm.py -q -v -k "confirm"

# 4. Commit
git commit -m "fix(bug-002) part 2/6: ConfirmFlow handler with deterministic execution

handle_text now routes ConfirmFlow.awaiting_confirmation messages to
_handle_confirmation_response, which detects yes/no via regex and
executes pending action with confirm=True directly via execute_tool —
NOT through LLM. This eliminates BUG-002 hallucination class.

Refs: BUG_LOG.md BUG-002 § Proposed fix Variant B, Session D."
```

### 4.3 Confirm-flow tests (3.5 confirm part)

```bash
# Расширить tests/test_bot_fsm.py всеми confirm-flow testcase'ами

.venv/bin/pytest tests/test_bot_fsm.py -q -v
# Должны пройти все confirm-flow tests.

git commit -m "fix(bug-002) part 3/6: regression tests for two-turn confirm flow

Adds tests/test_bot_fsm.py covering: preview→state, yes→exec,
no→clear, unrelated→clear+reroute, TTL expiry, and the critical
'yes does NOT call LLM' regression for BUG-002.

Refs: BUG_LOG.md BUG-002 § Why CI didn't catch, Session D."
```

### 4.4 PaginationFlow handler (3.3)

```bash
# 1. Edit tg_parser/bot/handlers.py — _handle_pagination_response.
# 2. Edit tg_parser/bot/tools.py — добавить pagination_pending в результаты.
# 3. Edit tg_parser/bot/handlers.py — _format_paginated_result с numbering.

.venv/bin/pytest tests/test_bot_fsm.py -q -v -k "paginat"

git commit -m "fix(bug-004) part 4/6: PaginationFlow handler with global numbering

handle_text routes PaginationFlow.has_active_list to a new handler
that handles 'ещё/next' and 'стоп/stop' deterministically. Global
numbering (e.g. 21-40 on page 2) maintains user reference across
pages. Soft-cap at 10 pages (200 items) suggests sub-query.

Refs: BUG_LOG.md BUG-004, Session D."
```

### 4.5 Pagination tests (3.5 pagination part)

```bash
.venv/bin/pytest tests/test_bot_fsm.py -q -v
# Все pagination-flow tests должны пройти.

git commit -m "fix(bug-004) part 5/6: pagination regression tests + numbering test

Tests cover: pagination_pending payload, offset increment, global
numbering across pages, max-pages soft-cap, stop behavior.

Refs: BUG_LOG.md BUG-004, Session D."
```

### 4.6 System prompt update (3.4)

```bash
# 1. Edit prompts/bot.yaml — append pagination + confirmation guidance.
# 2. Verify reload via reload_prompts MCP tool на staging.

.venv/bin/pytest -q 2>&1 | tail -10
# Final sweep.

git commit -m "fix(bug-002+004) part 6/6: system prompt — pagination & confirmation guidance

prompts/bot.yaml now teaches the LLM about: (a) global numbering
when paginated lists are returned, (b) NOT to call confirm=True
on its own — the FSM handler does that deterministically.

This is supplementary; FSM behavior is correct even if LLM ignores
these guidelines.

Refs: BUG_LOG.md BUG-002 + BUG-004, Session D."
```

---

## 5. Testing & verification (full run)

```bash
# Full pytest suite после landing'а всех 6 частей
.venv/bin/pytest -q 2>&1 | tail -20
# Ожидаемо: count = baseline + 10-15.

# Bot-specific sweep
.venv/bin/pytest tests/test_bot*.py -q -v

# FSM-specific
.venv/bin/pytest tests/test_bot_fsm.py -q -v
```

Manual smoke на dev-bot:

1. **Confirm-flow**: «добавь канал @some_real_xyz» → preview → «да» →
   ожидать success или соответствующий fail (НЕ `test_channel`!).
2. **Confirm-flow rejection**: «добавь канал @yyy» → preview → «нет» →
   ожидать «отменено».
3. **Confirm-flow unrelated**: «добавь канал @yyy» → preview →
   «покажи список каналов» → ожидать список (state очищен).
4. **TTL**: «добавь канал @yyy» → preview → wait 5+ min → «да» →
   ожидать «время истекло».
5. **Pagination**: «покажи темы канала Lab4health» → ожидать
   нумерованный список 1-20 + «всего 165 тем, показаны 1-20» →
   «ещё» → ожидать 21-40 → «ещё» → 41-60 → ... до softcap → suggestion.
6. **Pagination interrupt**: page 2 → «покажи каналы» → state очищен,
   список каналов.

---

## 6. PR / commit conventions

- **PR title**: `fix(bug-002+004): introduce bot FSMContext for confirm-flow and pagination`.
- **PR body** должен содержать:
  - Цель: closure'е BUG-002 (severity High после Session B+ → resolved)
    и BUG-004 (Medium → resolved).
  - Reference на BUG_LOG.md § BUG-002 + § BUG-004.
  - Architectural note: bot теперь имеет state-management через aiogram FSM
    + MemoryStorage; не multi-replica safe (см. D-1 default).
  - Список изменённых файлов: bot/main.py, bot/states.py (new),
    bot/handlers.py, bot/agent.py, bot/tools.py, prompts/bot.yaml,
    tests/test_bot_fsm.py (new).
- **CHANGELOG entry**:
  ```markdown
  ## Bug fix BUG-002 + BUG-004 — Bot FSMContext (2026-04-28)

  ### Closes Critical / Medium

  Bot теперь использует aiogram FSMContext для two-turn flows (confirm
  на add/remove/pause/resume/set_llm_config) и pagination (ещё/стоп)
  по любому списочному tool'у. Confirmation-execute проходит
  деттерминированно через handler, не через LLM — это закрывает
  BUG-002 hallucination class. Pagination использует глобальную
  нумерацию items для UX continuity. См. BUG_LOG.md.

  Storage: MemoryStorage (single-replica). Redis отложен.
  ```
- **Commit footer на финальном merge-commit'е**:
  `Refs: BUG_LOG.md BUG-002 + BUG-004, Session D. Closes: BUG-002, BUG-004.`
- **PR labels**: `bug-fix`, `bug-002`, `bug-004`, `bot`, `architecture`.

---

## 7. Acceptance criteria

Session D считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 gating decisions D-1..D-7 закрыты
- [ ] **MemoryStorage в Dispatcher**, StateGroups defined
- [ ] **ConfirmFlow handler работает детерминированно** (НЕ через LLM)
- [ ] **PaginationFlow handler работает с offset increment + global numbering**
- [ ] **`prompts/bot.yaml` обновлён** confirmation + pagination секциями
- [ ] full pytest suite зелёный (count ≥ baseline + 10)
- [ ] **Regression-test для BUG-002 hallucination** (yes-NOT-via-LLM) ✅
- [ ] **Regression-test для BUG-004 pagination** (offset increment + numbering) ✅
- [ ] CHANGELOG обновлён bug-fix-разделом
- [ ] PR merged в main с зелёным CI
- [ ] **`BUG_LOG.md` BUG-002 перенесён в § Resolved bugs** (с PR# + commit-SHA);
      **BUG-004 перенесён в § Resolved bugs**
- [ ] **`BUG_LOG.md` § Session planning § Updates** содержит:
  ```
  Session D (2026-04-NN) — landed: PR #NN, commit <SHA>, +N tests;
  bugs resolved: BUG-002 (full), BUG-004.
  ```

---

## 8. Handoff

Перед закрытием Session D:

1. **Production deploy verification**:
   - Manual smoke (§ 5) проходит.
   - Watch logs первые 1-2 часа после deploy на наличие unexpected
     state-clearing или regression'ов.
2. **Уведомить пользователя** что:
   - BUG-002 closed (severity Critical → resolved); test_channel
     hallucination больше не страшна.
   - BUG-004 closed.
   - Session E (BUG-006) теперь может стартовать; bot Gemini-flash
     fix не зависит от FSM, но scaffolding D помог стабилизировать
     bot-loop.
   - Session F (read-tool hardening) тоже не блокируется.
3. **Open follow-up TD** (если capacity):
   - **TD-redis-fsm**: миграция MemoryStorage → RedisStorage когда понадобится scale-out.
   - **TD-conversation-history**: feature TD для multi-turn conversation
     memory (отличается от FSM-state — это другое).
   - **TD-bot-tests-coverage**: bot directory test coverage низкая;
     отдельный sweep.
4. **Финальное сообщение юзеру** должно содержать:
   - PR# и SHA.
   - Подтверждение что hallucination-class закрыт regression-тестом.
   - Если manual smoke выявил new bug — отдельный escalation в новый
     BUG-NNN entry.

---

## 9. Citation back

- **Bug source:**
  - `docs/notes/BUG_LOG.md` § BUG-002 (full FSM fix)
  - `docs/notes/BUG_LOG.md` § BUG-004 (pagination)
- **Predecessor session (mitigations):**
  `docs/notes/START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md`.
- **Session planning:** `docs/notes/BUG_LOG.md` § Session planning (D4 default).
- **Successor session (depends on this):**
  `docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md`
  (Session E — Gemini fix; scaffolding D полезно).
- **Independent parallel session:**
  `docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md`
  (Session C — MCP auth; разные code path'ы).
- **aiogram docs:**
  - `aiogram.fsm.context.FSMContext`
  - `aiogram.fsm.state.StatesGroup`
  - `aiogram.fsm.storage.memory.MemoryStorage`

В commit-message'ах достаточно `Refs: BUG_LOG.md BUG-002 + BUG-004, Session D.`
