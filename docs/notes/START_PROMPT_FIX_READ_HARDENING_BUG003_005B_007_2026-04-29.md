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
из BUG-fix-сессий (~2.5 ч; +30 мин на shared-util refactor по F-7).

**Дата подготовки промпта:** 2026-04-27.
**Updated:** 2026-04-29 (post-Session-E production deploy + live smoke).

**Когда использовать:** **только** после того как:

1. Phase 1 / Phase 2 / Session B+ landed.
2. **Session D landed** (FSM scaffolding) — потому что меняется
   `_format_*_result` и подмешивание suggestion'ов в response — лучше
   единым контрактом; иначе двойная редактура `prompts/bot.yaml`.
3. **Session E landed + production-deployed** (✅ as of 2026-04-29 11:49 UTC,
   merge SHA `b92a6f5` deployed на VPS `mcp.tgp.efimov.mobi`). Session E
   выбрала **Option A** (`thinkingBudget=0` + `maxOutputTokens=8192`),
   **не** Option B (split TOOL_DECLARATIONS) — наши изменения tools.py
   совместимы с current TOOL_DECLARATIONS shape. **24h watch metric**
   `tg_bot_gemini_empty_parts_total` активен до **2026-04-30 11:49 UTC** —
   Session F deploy на VPS можно делать ТОЛЬКО после closure (исключаем
   confound при regression-расследовании). До closure — только code +
   tests + PR + merge to main; deploy откладывается.
4. `BUG_LOG.md` § BUG-003, § BUG-005, § BUG-007 прочитаны целиком.

---

## 0. Production observations from 2026-04-29 smoke (post-Session-E)

В ходе live smoke на VPS 2026-04-29 16:11-16:13 UTC+4 (BUG_LOG § BUG-006
Update «Production deploy»), для интента «удалить канал `test_channel`»
бот выдал **четыре разных ответа** на семантически эквивалентные input'ы:

| Input | Bot response | Code path |
|---|---|---|
| `Удали канал @test_channel` | «Канал @test_channel не найден» | `remove_channel` без normalize |
| `test_channel` (standalone msg) | «Извините, не могу использовать зарезервированные названия каналов» | LLM routing → `add_channel` → M2 guard |
| `Удали канал test_channel` | «Канал test_channel не найден» | `remove_channel` без normalize |
| `Удали канал 'test_channel'` (quotes) | «Канал 'test_channel' не найден» (with literal quotes) | `remove_channel` без normalize **или** quote-strip |

Что это значит для Session F scope:

- **Прямая мотивация для F-1**: input `'test_channel'` (с кавычками) → tool
  получил literal quoted string → не нашёл match. `_normalize_channel_id`
  helper **должен стрипать `'` и `"` тоже**, не только `@`. См. F-1 default
  (обновлён) + F-8 ниже.
- **`@test_channel` vs `test_channel`**: те же data, разные ответы. Это
  ровно root cause BUG-003 (read-tool → storage path не нормализует `@`,
  но read-tools здесь идут через `remove_channel` write-path, который
  тоже без нормализации в этой ветке — confound с BUG-003).
- **`test_channel` standalone → M2 guard**: это OK behavior, M2 защищает
  от создания нового placeholder. Но inconsistency между «Удали канал
  test_channel» (no M2) и «test_channel» (M2 hits через add_channel
  intent) — это известный artefact (LLM intent routing зависит от
  фразировки), **out of scope** для Session F. Симметризация M2 на
  remove/read-tools — anti-feature: уже existing placeholder каналы в DB
  должны быть deletable.
- **Pre-existing data orphan**: `test_channel (0 docs/0 messages)` уже
  существует в БД (создан до landing M2). M2 guard будет блокировать
  пересоздание после удаления, но сейчас канал виден в `list_channels` —
  это data-quality issue для отдельного admin task, **не** Session F.

**Test scope addition** (см. § 3.5): regression test для каждого из 4
input'ов выше — все должны давать **один и тот же** payload после
Session F (с suggestion'ами/available_channel_ids там, где `total=0`).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

> **Note:** line numbers verified 2026-04-29 после Session D+E landing.
> Если git log показывает дальнейшие правки в `tools.py` — искать по
> функциям через `rg "^async def _exec_" tg_parser/bot/tools.py -n`,
> не по absolute line numbers.

1. `docs/notes/BUG_LOG.md` § BUG-003 — целиком, **особенно**:
   - § «Update 2026-04-26 23:39 — confirmed via MCP».
   - § «Update 2026-04-26 23:45 — cross-provider LLM masking».
2. `docs/notes/BUG_LOG.md` § BUG-005 — целиком, **особенно**:
   - § «BUG-005-B (generic catch)» — секция, оставшаяся открытой
     после resolution BUG-005-A.
3. `docs/notes/BUG_LOG.md` § BUG-007 — целиком, **особенно**:
   - § «Root cause» — три слоя (storage / tool executor / system prompt).
   - § «Notes / status updates» — связь с BUG-003 confound.
4. `docs/notes/BUG_LOG.md` § BUG-006 «Update 2026-04-29 11:49 UTC —
   Production deploy» — для контекста сегодняшних observations
   (Q1-Q5 + F1-F2 smoke; metric watch активен).
5. `docs/notes/BUG_LOG.md` § Session planning — D-5 default
   (только tool+prompt в этой сессии).
6. `tg_parser/bot/tools.py` — `execute_tool` (line ~760, BUG-005-B target).
7. `tg_parser/bot/tools.py` — `_exec_ask_question` (line ~803).
8. `tg_parser/bot/tools.py` — `_exec_search` (line ~828).
9. `tg_parser/bot/tools.py` — `_exec_list_topics` (line ~855, BUG-003 + BUG-007 target).
10. `tg_parser/bot/tools.py` — `_exec_get_topic_details` (line ~934).
11. `tg_parser/bot/tools.py` — `_exec_list_channels` (line ~985, нужен для
    suggestion'ов в BUG-007 fix).
12. `tg_parser/bot/tools.py` — `_exec_get_cross_channel_stats` (line ~1063).
13. `tg_parser/bot/tools.py` — `_exec_get_related_topics` (line ~1038).
14. `tg_parser/bot/tools.py` — `_exec_get_document` (line ~1009).
15. `tg_parser/services/channel_placeholders.py` — Session B+ M2 module
    (`is_blocked_placeholder`, `blocked_message`, `get_blocked_placeholder_names`).
    Используется ТОЛЬКО в `_exec_add_channel` (line ~1449); НЕ симметризовать
    в Session F — см. § 0 production observations + § 2 out-of-scope.
16. Existing `lstrip("@")` call-sites (для F-7 consolidation):
    - `tg_parser/bot/tools.py` — 14 occurrences (lines ~1082, 1136, 1233, 1234, 1238, 1271, 1345, 1439, 1540, 1916, 2096, 2343).
    - `tg_parser/mcp_server.py` — 9 occurrences (lines ~1117, 1184, 1241, 1312, 1406, 1449, 2063, 2263, 2516).
    - `tg_parser/services/scheduler_service.py:85`,
      `tg_parser/services/watchlist_service.py:303`,
      `tg_parser/services/pipeline_service.py:30`.
    - `tg_parser/cli/watchlist_cmd.py:33`.
    - `tg_parser/ingestion/telegram/telethon_client.py:197`.
    - `scripts/add_test_messages.py:150`.
    Все они должны импортировать новый shared helper (см. F-7).
17. `tg_parser/mcp_server.py:752–852` — параллельные MCP read-tool'ы
    (для symmetric fix'а).
18. `prompts/bot.yaml` — текущий system prompt v1.1.0 (Session D); будет
    дополнен секциями по fallback-discovery + suggestion'ов → bump до v1.2.0.

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. Phase 1/2 + Session B+/C/D/E landed (verified 2026-04-29):
#    expect to see SHAs: b5f7121 (B+), c29f4c1, 59ec116 (C), 8332aa3 (D),
#    b92a6f5 (E), 1f70f33 (E docs follow-up).
git log --oneline main -50 | rg "Session [BCDE]|BUG-00[1-7]|read-hardening"
rg "Session [BCDE] \(2026" docs/notes/BUG_LOG.md

# 2. Working tree чист, branch
git checkout main
git pull --ff-only origin main
.venv/bin/pytest -q 2>&1 | tail -20
# Expected baseline: 1877 passed (Session E delta = +14 from 1863). Если
# меньше — что-то отвалилось post-E; разобраться ДО старта Session F.

# 3. Reproduce BUG-003 (через прямой MCP, без LLM):
#    list_topics(channel_id="@Lab4health") → ожидать total=0
#    list_topics(channel_id="Lab4health") → 165 тем
#    Smoke-проверка что баг ещё открыт.

# 4. Reproduce BUG-007:
#    list_topics(channel_id="AgeManagement") → ожидать total=0 (без suggestion'а)
#    Smoke-проверка.

# 5. Reproduce BUG-005-B (synthetic — без живого Anthropic billing-fail):
#    Временно зарейзить ValueError("test bug-005-b") в одном executor'е,
#    вызвать через bot, увидеть "internal error" вместо message — confirm,
#    откатить.

# 6. Verify 24h watch metric для BUG-006 (Session E) — НЕ должен spike'нуть:
ssh -p 2296 user@212.72.189.15 \
  "docker exec tg_parser_bot python -c \"from tg_parser.api.metrics import BOT_GEMINI_EMPTY_PARTS_TOTAL; \
   print({s.labels: s.value for s in BOT_GEMINI_EMPTY_PARTS_TOTAL.collect()[0].samples})\""
# Expected: пусто или 0 events. Если spike — STOP, разобраться (regression
# Session E или новый класс), Session F deploy блокируется до closure.

# 7. Branch
git checkout -b fix/read-hardening-bug-003-005b-007-2026-04-29
```

### 1.3 Gating decisions

| ID | Вопрос | Default per BUG_LOG § Session planning |
|---|---|---|
| F-1 | Где делать input-нормализацию (`@`-strip + quote-strip + whitespace) — в каждом executor'е или в общем helper'е? | **Общий helper** `normalize_channel_id(value: str \| None) -> str \| None`. Стрипает `@` prefix, surrounding `'`/`"` quotes (см. § 0 — production observation `'test_channel'` 2026-04-29), whitespace. Импорт во всех read-executor'ах + write-executor'ах (где `lstrip("@")` уже есть в Session B+ M2 → consolidate via shared helper). |
| F-2 | Suggestion-emit format | **Default**: при `total=0` добавить в payload `available_channel_ids: list[str]` (top 10 most-active каналов user'а) + `suggestion: str \| None` (если есть Levenshtein < 3 from input — указать closest match). |
| F-3 | Fuzzy-match implementation | **`difflib.get_close_matches`** stdlib, threshold cutoff=0.7, n=3. Минимум зависимостей. |
| F-4 | Typed catch для `_call_tool_safe` (BUG-005-B) | **Capture exception class + message**; preserve в payload как `error_class: str`, `error_message: str` (truncated to 500 chars); generic fallback только для UnboundLocalError / KeyError / etc — реальные API errors сохраняются. |
| F-5 | Backward compatibility для existing tool consumers | **Не ломать** — новые поля (`available_channel_ids`, `suggestion`, `error_class`) добавляются как **optional**; existing fields (`total`, `items`, `error`) сохраняются. |
| F-6 | Symmetric fix для MCP `mcp_server.py` read-tool'ов? | **Да** — те же изменения; иначе bot-tool и MCP расходятся в поведении. Это часть scope'а. |
| F-7 | Где жить нормализующему helper'у? `bot/tools.py` создаст cyclic-import risk для `services/*` и `mcp_server.py`. | **Новый shared util** `tg_parser/utils/channel_id.py` (`normalize_channel_id`). Все 14+ existing call-sites (`bot/tools.py`, `mcp_server.py`, `services/scheduler_service.py`, `services/watchlist_service.py`, `services/pipeline_service.py`, `cli/watchlist_cmd.py`, `ingestion/telegram/telethon_client.py`, `scripts/add_test_messages.py`) импортируют отсюда → single source of truth, нет циклов. |
| F-8 | Стрипать ли surrounding quotes (`'channel'`, `"channel"`) с input'а? | **Да** — production observation 2026-04-29 (`Удали канал 'test_channel'` → bot получил literal quoted string → `total=0`). Helper стрипает в порядке: `.strip()` → strip enclosing `'`/`"` если match парный → `lstrip("@")` → final `.strip()`. Пишется как regex или stepwise loop, не как `.strip("'\"@")` (который бы removed mismatched chars). |
| F-9 | Backport-тест для Session E regression watch | **Один smoke-тест**, который запускает helper'нормализованный input против всех 4 input-варианта из § 0 (production observations 2026-04-29) и assert что они все идут в один и тот же storage call. Защищает от regression если кто-то в будущем добавит back `lstrip("@")` локально. |

---

## 2. Out of scope

| Категория | Куда отложить | Причина |
|---|---|---|
| **Storage-side LIKE → JSONB ?** | отдельный TD-NN после Session F | D-5 default; миграции, отдельное review |
| **`AgeManagment` → `AgeManagement` data-quality fix** | отдельный admin-task | Возможно реальный typo в Telegram-username; pause/add/remove с правильным id |
| **Pre-existing orphan `test_channel` (0 docs/0 messages) в БД** | отдельный admin-task | Создан до landing M2 guard; не блокирует Session F. Через `remove_channel` deletable правомерно (см. § 0). |
| **M2 placeholder-guard симметризация на read/remove tools** | wontfix / anti-feature | Существующие placeholder-каналы в БД должны быть удаляемы; M2 защищает только от **создания**. Сегодняшняя inconsistency для `test_channel` — LLM intent-routing artefact, не баг. |
| **Cross-language fuzzy match (translit)** | отдельный feature | Сейчас только difflib stdlib |
| **Search-tool re-ranking based on suggestion'ах** | отдельный feature | Вне scope'а UX-hardening'а |
| **Bot-side typo correction в user-input** | отдельный feature | Сложно без broader UX-overhaul'а |
| **Replacement существующих error-payload contracts** | wontfix | F-5 default — backward compatible |
| **`prompts/bot.yaml` mass-rewrite** | wontfix | Только append fallback + suggestion sections (bump 1.1.0 → 1.2.0) |
| **MCP-side new tools** | wontfix | Только existing fix |
| **Production deploy на VPS до 2026-04-30 11:49 UTC** | defer 24 часа | Session E `tg_bot_gemini_empty_parts_total` watch активен до закрытия (см. § 1.2 step 6). Confound-free metric data приоритет над скоростью deploy. PR может merge'нуться в main раньше. |

---

## 3. Sprint scope (Session F)

### 3.1 BUG-003 fix — `normalize_channel_id` shared helper (F-1 + F-7 + F-8)

**Files to touch:**

- **NEW** `tg_parser/utils/channel_id.py` — shared util module (F-7):

  ```python
  """Channel ID normalization — single source of truth.

  See BUG-003 (read-tools didn't normalize @ prefix); BUG_LOG.md
  Session F production observation 2026-04-29 (quoted input
  `'test_channel'` reached storage as literal quoted string).
  """
  from __future__ import annotations


  def normalize_channel_id(value: str | None) -> str | None:
      """Normalize a user-supplied channel_id to canonical DB form.

      Strips:
      1. Surrounding whitespace.
      2. Surrounding matching quotes (`'…'` or `"…"`) — exactly one
         pair. Mismatched quotes (`'…"`) are left as-is to flag
         malformed input upstream.
      3. Leading `@` (Telegram username convention).
      4. Trailing/leading whitespace again, in case quote-strip
         exposed padding.

      Returns None if input is None or normalizes to empty string.
      Idempotent: ``normalize(normalize(x)) == normalize(x)``.

      Examples:
          >>> normalize_channel_id("@AgeManagement")
          'AgeManagement'
          >>> normalize_channel_id("'test_channel'")
          'test_channel'
          >>> normalize_channel_id('  "@Lab4health"  ')
          'Lab4health'
          >>> normalize_channel_id(None) is None
          True
          >>> normalize_channel_id("@") is None
          True
      """
      if value is None:
          return None
      stripped = value.strip()
      if (
          len(stripped) >= 2
          and stripped[0] in ("'", '"')
          and stripped[-1] == stripped[0]
      ):
          stripped = stripped[1:-1]
      stripped = stripped.lstrip("@").strip()
      return stripped or None
  ```

- `tg_parser/bot/tools.py` — все read-tool executors импортируют helper:

  ```python
  from tg_parser.utils.channel_id import normalize_channel_id

  async def _exec_list_topics(args, ...):
      channel_id = normalize_channel_id(args.get("channel_id"))
      ...
  ```

  Где это нужно (read-tools — currently БЕЗ нормализации):
  - `_exec_ask_question` (~line 803)
  - `_exec_search` (~line 828)
  - `_exec_list_topics` (~line 855)
  - `_exec_get_topic_details` (~line 934)
  - `_exec_list_channels` (~line 985) — для нормализации filter args
  - `_exec_get_document` (~line 1009)
  - `_exec_get_related_topics` (~line 1038)
  - `_exec_get_cross_channel_stats` (~line 1063)

  Где **consolidate** existing `lstrip("@")` через helper (write/mixed):
  - `_exec_pause_channel` (~line 1271 `str(args["channel_id"]).lstrip("@")`)
  - `_exec_resume_channel` (~line 1345)
  - `_exec_add_channel` (~line 1439) — критично, M2 guard ниже зависит от normalized
  - `_exec_remove_channel` (~line 1540)
  - `_exec_export_channel` (~line 1916)
  - `_exec_subscribe_digest` (~line 2096 — list-comprehension над channel_ids)
  - `_exec_subscribe_watchlist` (~line 2343 — list-comprehension)
  - Internal helpers (~lines 1082, 1136, 1233-1238) — заменить на `normalize_channel_id`.

- `tg_parser/mcp_server.py` — symmetric fix (F-6 default):
  - Импорт того же `normalize_channel_id` из `tg_parser.utils.channel_id`.
  - Replace 9 occurrences `channel_id.lstrip("@")` (~lines 1117, 1184, 1241, 1312, 1406, 1449, 2063, 2263, 2516).

- Other call-sites consolidation:
  - `tg_parser/services/scheduler_service.py:85`,
    `tg_parser/services/watchlist_service.py:303`,
    `tg_parser/services/pipeline_service.py:30` — replace via helper.
  - `tg_parser/cli/watchlist_cmd.py:33` — replace.
  - `tg_parser/ingestion/telegram/telethon_client.py:197` — replace.
  - `scripts/add_test_messages.py:150` — replace.

- **Acceptance grep**: `rg "lstrip..@.." tg_parser/ scripts/` после landing
  должен вернуть **только** строку из `tg_parser/utils/channel_id.py` (helper
  body) + ничего больше (см. § 7 acceptance criteria).

### 3.2 BUG-007 fix — suggestion-emit on `total=0` (F-2 + F-3)

**Files to touch:**

- `tg_parser/bot/tools.py` — добавить второй helper:

  ```python
  import difflib

  async def _build_no_results_suggestion(
      requested_channel_id: str,
      user: CurrentUser,
  ) -> dict[str, Any]:
      """Build suggestion payload for tools that returned total=0.

      Returns a dict with:
      - `available_channel_ids`: list[str] — up to 10 channels user
        has access to (filtered by `user.allowed_channel_ids` or
        `list_sources` for admin).
      - `suggestion`: str | None — if a close match exists in
        available channels, hint at the typo correction.

      See BUG-007.
      """
      # Real import — verified 2026-04-29 в _exec_list_channels (line 985+).
      from tg_parser.services.db_context import ingestion_state_repo

      sources_raw = await ingestion_state_repo.list_sources()
      all_ids = [str(s["channel_id"]) for s in sources_raw if s.get("channel_id")]
      if user.allowed_channel_ids is not None:
          # Non-admin: filter to user's allowed channels.
          all_ids = [cid for cid in all_ids if cid in user.allowed_channel_ids]

      # cap to 10 for response-size discipline.
      available_top = all_ids[:10]

      suggestion: str | None = None
      if requested_channel_id and all_ids:
          matches = difflib.get_close_matches(
              requested_channel_id, all_ids, n=1, cutoff=0.7
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

  > **Note:** `user` параметр обязательный (не `Optional`) — каждый
  > read-executor уже получает `user` через `current_user` в kwargs.
  > Для MCP-side эквивалент через `resolve_mcp_user(...)` (Session C).

- `tg_parser/bot/tools.py::_exec_list_topics` (и аналогично `_exec_search`,
  `_exec_get_topic_details`, `_exec_get_cross_channel_stats`):

  ```python
  async def _exec_list_topics(args, user=None, **kwargs):
      channel_id = normalize_channel_id(args.get("channel_id"))
      ...
      result = {"total": total, "items": items, ...}
      if total == 0 and channel_id and user is not None:
          result.update(await _build_no_results_suggestion(channel_id, user))
      return result
  ```

- `tg_parser/mcp_server.py` — symmetric fix через тот же helper.

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

- **NEW** `tests/test_utils_channel_id.py` (helper unit tests, F-1 + F-8):
  - `test_strips_at_prefix`: `normalize_channel_id("@AgeManagement") == "AgeManagement"`.
  - `test_strips_whitespace`: `normalize_channel_id("  Lab4health  ") == "Lab4health"`.
  - `test_strips_single_quotes`: `normalize_channel_id("'test_channel'") == "test_channel"`. **Direct regression на 2026-04-29 production observation.**
  - `test_strips_double_quotes`: `normalize_channel_id('"Lab4health"') == "Lab4health"`.
  - `test_strips_quotes_then_at`: `normalize_channel_id('"@Lab4health"') == "Lab4health"`.
  - `test_strips_at_inside_quotes`: `normalize_channel_id("'@Lab4health'") == "Lab4health"`.
  - `test_preserves_mismatched_quotes`: `normalize_channel_id('"foo\'') == "foo'"` (no quote stripped).
  - `test_handles_none`: `normalize_channel_id(None) is None`.
  - `test_handles_empty_string`: `normalize_channel_id("") is None`.
  - `test_handles_only_at`: `normalize_channel_id("@") is None`.
  - `test_handles_only_quotes`: `normalize_channel_id("''") is None`.
  - `test_idempotent`: `normalize_channel_id(normalize_channel_id(x)) == normalize_channel_id(x)` for several inputs.

- `tests/test_bot_tools.py` (новый файл или дополнить):

  - **BUG-003 read-tool normalization (end-to-end через executor):**
    - `test_exec_list_topics_with_at_prefix_returns_same_as_without`:
      mock storage возвращает 5 items для `Lab4health`; вызов с
      `channel_id="@Lab4health"` тоже возвращает 5.
    - `test_exec_search_normalizes_at_prefix`.
    - `test_exec_get_topic_details_normalizes_at_prefix`.
    - **F-9 regression (production scenarios from 2026-04-29 § 0):**
      `test_remove_channel_handles_quoted_at_and_bare_input` — все 4
      input'а (`@test_channel`, `test_channel`, `'test_channel'`,
      `"@test_channel"`) reach storage с `channel_id="test_channel"`
      (через mock на storage; M2 placeholder guard сработает в
      `_exec_add_channel`-варианте отдельно — не путать).

  - **BUG-007 suggestion:**
    - `test_no_results_suggestion_provides_close_match`:
      mock `ingestion_state_repo.list_sources` возвращает
      `["AgeManagment", "Lab4health"]`; query `"AgeManagement"` →
      suggestion указывает на `AgeManagment`.
    - `test_no_results_suggestion_no_match_for_far_input`:
      query `"xyz_unknown"` → suggestion is None.
    - `test_no_results_includes_available_channel_ids`:
      payload содержит `available_channel_ids` после `total=0`.
    - `test_no_results_does_not_emit_suggestion_when_total_nonzero`.
    - `test_no_results_filters_by_user_allowed_channel_ids`:
      non-admin user видит **только** свои allowed_channel_ids в
      `available_channel_ids`, не все каналы системы (RBAC respect).

  - **BUG-005-B typed catch:**
    - `test_execute_tool_preserves_value_error_message`:
      executor raises `ValueError("invalid arg X")`; payload содержит
      `error_class="ValueError"`, `error_message="invalid arg X"`.
    - `test_execute_tool_preserves_permission_error_message`.
    - `test_execute_tool_truncates_long_exception_message`:
      executor raises `Exception("a"*1000)`; payload `error` ≤ 500.
    - `test_execute_tool_timeout_returns_typed_class`.
    - **Regression** для BUG-005-A case: mock executor raises
      `Exception("Your credit balance is too low...")` →
      payload содержит этот message, не generic.

- **MCP symmetric tests** (`tests/test_mcp_server.py` дополнить):
  - `test_mcp_list_topics_normalizes_at_prefix` — паритет с bot-side.
  - `test_mcp_normalize_helper_called_for_export_channel_filter`.

---

## 4. Per-step playbook

### 4.1 Helper extraction (3.1) — shared util + consolidation

```bash
# 1. Create tg_parser/utils/channel_id.py with normalize_channel_id helper.
# 2. Add tests/test_utils_channel_id.py (12 unit tests per § 3.5).
# 3. Replace lstrip("@") в bot/tools.py (~14 occurrences), mcp_server.py
#    (9 occurrences), services/{scheduler,watchlist,pipeline}_service.py,
#    cli/watchlist_cmd.py, ingestion/telegram/telethon_client.py,
#    scripts/add_test_messages.py — все импортируют из utils/channel_id.py.
# 4. Add normalize() call в read-tool executors (8 read-executors).

# 5. Smoke
.venv/bin/pytest tests/test_utils_channel_id.py -q -v
.venv/bin/pytest tests/test_bot_tools.py -q -v -k "normalize or at_prefix"

# 6. Acceptance grep — должна вернуть только helper body:
rg "lstrip..@.." tg_parser/ scripts/

# 7. Commit
git commit -m "fix(bug-003) part 1/4: shared normalize_channel_id util

Adds tg_parser/utils/channel_id.py with normalize_channel_id helper.
Strips @ prefix, surrounding ' or \" quotes, and whitespace; idempotent.
Consolidates 25+ existing lstrip(\"@\") call-sites across bot/tools.py,
mcp_server.py, services/, cli/, ingestion/, and scripts/ — single
source of truth, no cyclic imports. All read-tool executors in
tg_parser/bot/tools.py now normalize channel_id input. Resolves
BUG-003 — read-tools no longer return total=0 for @ChannelName or
'ChannelName' inputs.

Quote-strip directly addresses 2026-04-29 production observation
(BUG_LOG § BUG-006 Update): \`Удали канал 'test_channel'\` reached
storage as literal quoted string.

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
#    error-classification sections; bump version footer 1.1.0 → 1.2.0.

# 2. Verify reload via reload_prompts MCP tool на staging.
# 3. Final pytest sweep
.venv/bin/pytest -q 2>&1 | tail -10
ruff check . && ruff format --check .

git commit -m "fix(bug-003+007+005-b) part 4/4: system prompt v1.2.0 — fallback + error guidance

prompts/bot.yaml v1.2.0 now teaches the LLM about: (a) @-prefix and
quotes being optional in channel_id, (b) using \`suggestion\` and
\`available_channel_ids\` fallbacks on total=0, (c) classifying
error_class for user-facing messages. Behavior is correct even if
LLM ignores guidelines (deterministic helpers in tools.py); this is
supplementary UX.

Refs: BUG_LOG.md BUG-003 + BUG-005-B + BUG-007, Session F."
```

---

## 5. Testing & verification (full run)

```bash
.venv/bin/pytest -q 2>&1 | tail -20
# Baseline (post-Session-E): 1877 passed.
# Expected post-Session-F: 1895-1900 passed (≈+18-23 tests от F-1 helper unit
# tests + read-tool normalization + suggestion + typed-catch + MCP symmetric).

.venv/bin/pytest tests/test_utils_channel_id.py tests/test_bot_tools.py -q -v
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

- [ ] § 1.2 sanity-checks прошли до старта работ (вкл. step 6 — 24h watch metric Session E без spike'ов)
- [ ] § 1.3 gating decisions F-1..F-9 закрыты
- [ ] **`tg_parser/utils/channel_id.py` shared util** создан; `normalize_channel_id` стрипает `@`, surrounding `'`/`"` quotes, whitespace; idempotent
- [ ] **All `lstrip("@")` consolidated**: `rg "lstrip..@.." tg_parser/ scripts/` возвращает **только** строку из `tg_parser/utils/channel_id.py` helper body (ноль других call-sites)
- [ ] **All read-tool executors** в `tg_parser/bot/tools.py` нормализуют `channel_id` через helper (8 read-executors per § 3.1)
- [ ] **`_build_no_results_suggestion` helper** landed; wired в `_exec_list_topics`, `_exec_search`, `_exec_get_topic_details`, `_exec_get_cross_channel_stats`
- [ ] **`execute_tool` typed catches** landed; preserve `error_class` + truncated `error` message; regression test для BUG-005-A "credit balance" case проходит
- [ ] **`prompts/bot.yaml` v1.2.0** — добавлены секции channel-normalization + fallback + error-classification (bump version footer)
- [ ] **MCP-side symmetric fix** landed (9 occurrences в `mcp_server.py`)
- [ ] **F-9 production regression test** проходит — все 4 input'а из § 0 reach storage с одинаковым `channel_id="test_channel"`
- [ ] full pytest suite зелёный (count ≥ 1895; baseline 1877 + ≈18 новых)
- [ ] `ruff check . && ruff format --check .` clean
- [ ] CHANGELOG обновлён trio-bug-fix-разделом
- [ ] PR merged в main с зелёным CI
- [ ] **`BUG_LOG.md` BUG-003, BUG-005-B, BUG-007 перенесены в § Resolved bugs**
      с PR# + commit-SHA каждый (BUG-005 уже в Resolved — обновить B-suffix entry)
- [ ] **`BUG_LOG.md` § Session planning § Updates** содержит:
  ```
  - **Session F (2026-04-NN) — landed:** PR #NN ([SHA]); +N tests;
    bugs resolved: BUG-003, BUG-005-B, BUG-007. Architecture: shared
    `normalize_channel_id` util; suggestion-emit on total=0; typed
    catches in execute_tool. Pytest 1895+ passed.
  ```

---

## 8. Handoff

Перед закрытием Session F:

1. **Pre-deploy gate**: 24h watch metric `tg_bot_gemini_empty_parts_total`
   из Session E **закрыт** (closure 2026-04-30 11:49 UTC). Если metric
   spike'ов **нет** → можно деплоить bundle. Если spike'и были — root-cause
   analysis Session E regression первым приоритетом, Session F deploy ждёт.

2. **Production deploy verification** (после metric closure):
   - VPS bundle deploy: `git pull --ff-only origin main` + `docker compose
     build tg_parser` + `up -d --no-deps --force-recreate tg_parser mcp tg_bot`.
   - Manual smoke (§ 5) проходит на VPS:
     - BUG-003: `@Lab4health` через bot и через MCP — total > 0.
     - BUG-007: `AgeManagement` (typo) → suggestion указывает на
       `AgeManagment`.
     - BUG-005-B: synthetic ValueError (откатить после теста).
     - F-9 production scenarios: все 4 input'а из § 0 идут одним
       payload-shape'ом.
   - 24h post-deploy watch на тех же metric'ах (`empty_parts` не должен
     spike'нуть от изменений в `execute_tool`).

3. **Уведомить пользователя** что:
   - **Все 7 функциональных bug'ов из BUG_LOG.md обработаны** (BUG-001/001b/002/004/006 resolved через C/D/E; BUG-005-A resolved billing-fix'ом; BUG-003/005-B/007 resolved через Session F; BUG-002 также имеет mitigations через B+).
   - **BUG-008 остаётся open** — отдельный diagnostic spike (~1 ч) для
     `list_channels` MCP hang; flaky repro, не блокирует продакшн.
   - **BUG-fix-волна 2026-04-26..29 завершена**: 5 sessions (B+, C, D, E, F),
     5 PR merged, ~140 новых тестов, 0 regressions, два production deploy
     bundle'а (Session C 2026-04-27 19:00 UTC + Session E 2026-04-29 11:49 UTC).
   - Можно стартовать **отдельный housekeeping-sprint** для TD-05..08 +
     carry-forward TD ниже.

4. **Open follow-up TD** (для будущих housekeeping sessions):
   - **TD-storage-jsonb-channel-id** (BUG-007 storage-side, deferred per D-5):
     `LIKE '%"channel_id"%'` → `sources @> ARRAY['channel_id']` или
     `sources ? 'channel_id'` (зависит от JSONB shape'а). Affects
     `topic_card_repo.list_by_channel`, `topic_bundle_repo.list_by_channel`.
   - **TD-data-quality-AgeManagment**: проверить нужна ли rename
     channel'а (если это typo, не реальный username).
   - **TD-data-quality-test_channel-orphan**: pre-existing orphan
     `test_channel (0 docs)` — soft-delete через VPS SQL или через bot
     `Удали канал test_channel` (M2 НЕ блокирует remove).
   - **TD-bot-intent-router** (Session E carry-forward, Option B):
     split TOOL_DECLARATIONS via intent classification — отложено до
     post-Session-E metric data (≥7 дней usage). Если 24h+ watch
     показал стабильно <1% empty_parts → можно deferred indefinitely.
   - **TD-bot-nightly-health-check** (Session E carry-forward):
     синтетический «Покажи LLM конфиг» каждый час + alert при empty-parts
     spike >5%. Реализуется как cron job вне основного code base'а.
   - **BUG-008 diagnostic spike** (Session D carry-forward): MCP remote
     endpoint hang — отдельный 1-часовой runbook.
   - **GH issues #39 #40 #41** (Session D carry-forward, all `tech-debt`+`priority/p1`):
     - [#39 renderer unification](https://github.com/AlexEfimov/TG_parser/issues/39)
     - [#40 pagination_pending coverage](https://github.com/AlexEfimov/TG_parser/issues/40)
     - [#41 `_format_tool_result` fallback](https://github.com/AlexEfimov/TG_parser/issues/41)

5. **Финальное сообщение юзеру** должно содержать:
   - PR# и merge SHA.
   - Production deploy SHA (после 30.04 11:49 UTC closure metric watch'а).
   - Подтверждение что bug-fix-волна **закрыта** для backlog'а 2026-04-26..29
     (7/7 functional bugs resolved или mitigated; BUG-008 — diagnostic).
   - Backlog dump (см. список TD выше).

---

## 9. Citation back

- **Bug sources:**
  - `docs/notes/BUG_LOG.md` § BUG-003 (читать целиком + Update 23:39 / 23:45).
  - `docs/notes/BUG_LOG.md` § BUG-005 § BUG-005-B subsection.
  - `docs/notes/BUG_LOG.md` § BUG-007.
  - `docs/notes/BUG_LOG.md` § BUG-006 «Update 2026-04-29 11:49 UTC — Production deploy + live smoke PASSED» — для production observations § 0 (4 input variants for `test_channel` deletion intent).
  - `docs/notes/BUG_LOG.md` § BUG-008 — для контекста (отдельный diagnostic, **out of scope**).
- **Predecessor sessions:**
  - `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md` (Session D).
  - `docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` (Session E).
- **Session planning:** `docs/notes/BUG_LOG.md` § Session planning (D-5 default).
- **Independent track:**
  `docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md` (Session C).
- **Related code:**
  - `tg_parser/utils/channel_id.py` (NEW — F-7 shared util).
  - `tg_parser/bot/tools.py` (target, 32 executors per `rg "^async def _exec_"`).
  - `tg_parser/mcp_server.py` (symmetric fix; 9 normalize call-sites).
  - `tg_parser/services/{scheduler,watchlist,pipeline}_service.py`,
    `tg_parser/cli/watchlist_cmd.py`,
    `tg_parser/ingestion/telegram/telethon_client.py`,
    `scripts/add_test_messages.py` (consolidate via shared util).
  - `tg_parser/services/channel_placeholders.py` (Session B+ M2 — НЕ
    модифицируется в Session F per § 2 out-of-scope).
  - `prompts/bot.yaml` (system prompt; bump 1.1.0 → 1.2.0).
  - `tg_parser/storage/sqlalchemy/topic_card_repo.py:130–143` (NOT touched
    here per D-5; future TD-storage-jsonb-channel-id).

В commit-message'ах достаточно `Refs: BUG_LOG.md BUG-003 + BUG-005-B + BUG-007, Session F.`
