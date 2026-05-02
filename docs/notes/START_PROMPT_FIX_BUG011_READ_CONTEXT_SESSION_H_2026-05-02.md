# Fix Sprint — Bot Read-Context Preservation Across Turns (BUG-011) (Session H, 2026-05-02)

---

## Pre-flight status — DRAFT (gate-1 to be executed at session start)

**Status:** DRAFT. Pre-flight gate-1 verification (§ 0) NOT yet executed —
must run at the start of the implementation session.

**Last edited:** Saturday 2026-05-02 (~17:00 UTC+4) on parent transcript
«Session G closure + Session H pre-flight».

### Gate-1 verification (§ 0) — TO BE EXECUTED AT SESSION START

VPS HEAD must be at Session G post-deploy SHA (>= `a8ccf9a` — Session G squash-
merge of [PR #55](https://github.com/AlexEfimov/TG_parser/pull/55)) **plus**
the BUG-012 prompt v1.5.0 deploy (PR #56, expected `~9XXXXXX` — to be filled
in after PR #56 merges and deploys).

Window opens 2026-05-03 ≥ 12:32 UTC (24h after Session G deploy at
2026-05-02 12:32 UTC, see `docs/notes/BUG_LOG.md` § BUG-009 Update 2026-05-02).
Verification path:

```bash
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool'
# Expected: {"status":"success","data":{"resultType":"vector","result":
#   [{"metric":{"__name__":"up","instance":"tg_bot:8081","job":"tg_parser_bot",
#     "service":"bot"},"value":[<unix>,"1"]}]}}

ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -cE "confirm_flow_mismatch"'
# Expected: 0 (no false-positive guard rejections of legitimate flows)

ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked"'
# Expected: 0 (Session E watch closure pattern still holds)
```

| Check | Expected | Actual | Status |
|---|---|---|---|
| Prometheus `up{service="bot"}` | `result: [{... value: [_, "1"]}]` (scrape live) | TBD | TBD |
| `docker logs --since 24h tg_parser_bot` grep `confirm_flow_mismatch` | `0` (no Session G guard false-positives) | TBD | TBD |
| `docker logs --since 24h tg_parser_bot` grep `gemini_empty\|gemini_no_candidates\|gemini_blocked` | `0` (Session E hold) | TBD | TBD |

If any check FAILS — pause Session H, investigate the regression first.
ConfirmFlowMismatch false-positives would suggest the FSM wiring missed
a legitimate confirm path; investigate `_handle_confirmation_response` +
all confirm-tools used in the 24h window.

### Locked decisions (do not relitigate at session start)

- **D-1**: Storage architecture — **data-only** (`FSMContext.update_data(read_context={...})`).
  No new StatesGroup. `read_context` lives alongside ConfirmFlow / PaginationFlow
  active states, accessible from any state via `state.get_data()`. Justification:
  read_context is a *value*, not a *flow* — the user is not "in a state of
  reading"; they are doing arbitrary read-ops with shadow context. Adding
  a new state would either conflict with ConfirmFlow/PaginationFlow or
  require nested state machines (overengineering).
- **D-4**: Resolution path — **programmatic injection** into the agent's
  `systemInstruction`, NOT prompt-discipline. Justification: BUG-002 history
  proved LLM prompt-discipline insufficient on edge cases (Gemini hallucinates
  on multi-turn boundaries). Programmatic injection at the agent boundary is
  deterministic and easy to test.
- **D-6**: Read-context MUST NOT influence write-tools — `add_channel`,
  `remove_channel`, `pause_channel`, `resume_channel`, `trigger_pipeline`,
  `set_llm_config`, `reset_llm_config` always require explicit `channel_id`
  in the user message. Read-context is read-side only. Justification: write-
  tools are guarded by Session D ConfirmFlow + Session G `execute_tool`
  guard; read_context as input to write-tools would re-open BUG-002 class
  via a different vector. The system prompt instruction must explicitly
  prohibit this.

### Decisions to confirm at session start (gating)

- **D-2**: Tool scope (which read-tools track context).
- **D-3**: Update logic (when to write `last_channel_id`).
- **D-5**: TTL value.
- **D-7**: Reset triggers.

See § 1.3 «Gating decisions» below for full options + recommendations.

### Implementation session opener

Open a fresh chat and paste:

> Стартую Session H — fix BUG-011 bot read-context preservation across turns.
> Pre-flight завершён в предыдущем окне (см. handover block в начале
> `docs/notes/START_PROMPT_FIX_BUG011_READ_CONTEXT_SESSION_H_2026-05-02.md`).
> Прочитай start prompt целиком + `BUG_LOG.md` § BUG-011, выполни gate-1
> verification из § 0, затем исполни § 3 (read_context plumbing → agent
> injection → prompt update v1.5.0 → tests → verify → PR → deploy → closure).
> Branch: `fix/bug-011-read-context-2026-05-XX` (XX = session start date).
> Локированные решения: **D-1** (data-only, no new StatesGroup), **D-4**
> (programmatic injection в systemInstruction), **D-6** (write-tools immune).
> Gating decisions (D-2, D-3, D-5, D-7) — обсудить в начале сессии.

---

**Назначение:** закрыть BUG-011 структурно — bot теряет subject-channel
context между read-tool turns ("темы канала AgeManagment" → "покажи 5 главных
тем" → возвращает global top-5 вместо channel-scoped). Добавить shadow read-
context (FSMContext data field) который persist'ится через turn boundary
plus programmatic injection в Gemini systemInstruction'е чтобы LLM
восстанавливал implicit channel reference.

**Источник:** [BUG_LOG.md § BUG-011](BUG_LOG.md), live Telegram observation
2026-04-30 by Alexander, after BUG-007 + BUG-003 closure validation.

**Tracker:** TD-bot-read-context-preservation (no GH issue filed yet — file
at session start, will become Session H tracker analogous to Session G #49).

**Тип сессии:** writing — code (handlers + agent + states), tests, prompt
update (мелкий — version bump + section), PR. Чуть шире Session G по scope
(plumbing через 3 модуля вместо 2), но архитектурно проще guard'а — нет
contract checking, только value propagation.

**Дата подготовки промпта:** 2026-05-02 ~17:00 UTC+4 (после Session G
deploy + BUG-012 prompt v1.5.0 PR #56 в процессе CI).

**Когда использовать:** ТОЛЬКО после того как:

1. Session G watch closure verified (≥24 часа после deploy `a8ccf9a` =
   2026-05-02 12:32 UTC → closure window opens **2026-05-03 12:32 UTC**).
   Gate-1 checks из § 0 GREEN.

2. PR #56 (BUG-012 prompt v1.5.0) merged + deployed. Post-deploy smoke на
   проде («темы канала AgeManagement» typo → response не содержит «1 из
   ['…']»). Без этого Session H будет править бот, который ещё несёт
   BUG-012 cosmetic regression.

3. **`BUG_LOG.md` § BUG-011 прочитано целиком** (включая Symptoms / Root
   cause / Why CI didn't catch / Proposed fix секции).

4. Production state confirmed clean: `tool=add_channel` log scrape за 24h
   возвращает 0 (BUG-009 guard mitigation держится — подтверждение через
   `docker logs --since 24h tg_parser_bot | grep "confirm_flow_mismatch"
   | grep -v "test"` показывает 0 false-positives).

---

## 0. Why this session is medium-sized (vs Session G small)

Session G был ~150 LOC / 13 tests / 1 contract change. Session H шире:

- **Plumbing across 3 modules**: `tg_parser/bot/handlers.py` (read tool result
  → store last_channel_id in FSMContext data), `tg_parser/bot/agent.py`
  (`process_message` accepts `read_context: dict | None = None`, injects
  into systemInstruction), `tg_parser/bot/states.py` (typed `ReadContextData`
  TypedDict — pure typing, no new StatesGroup per D-1).
- **One prompt section**: `prompts/bot.yaml` v1.5.0 → v1.6.0, new section
  «Implicit channel context (read-side)» explaining shadow read_context
  semantics + write-tool immunity rule (D-6).
- **Two execution surfaces**: read_context UPDATE path (after every
  successful read-tool call where args contained channel_id) + read_context
  READ path (in `handle_text` before agent call, inject into systemInstruction
  if last_channel_id present and not stale).
- **TTL semantics + reset rules**: longer than ConfirmFlow's 5 min (read
  sessions span 10-15 min naturally — D-5).

Estimate ~250 LOC + ~14 tests, ~2.5–3.5 часа. Higher than original BUG_LOG
estimate of ~200 LOC + 12-15 tests; refined upward after seeing the actual
plumbing surface during pre-flight (handler + agent + states + prompt + 4
test classes).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

> **Note:** line numbers verified 2026-05-02 после Session G + BUG-012 v1.5.0
> landing (HEAD will be `a8ccf9a` + PR #56 squash). Перепроверить если есть
> commits между подготовкой промпта и стартом сессии (`git log --since="2026-05-02 17:00 UTC+4"`).

1. `docs/notes/BUG_LOG.md` § BUG-011 — full entry (severity, root cause,
   symptoms, why CI didn't catch, proposed fix scope). Особое внимание на
   **«Why CI didn't catch»** — указывает что нужна integration-test
   `test_implicit_channel_context_preserved_across_read_turns`.
2. `docs/notes/BUG_LOG.md` § BUG-002 (Session D landed) — родительский
   context-loss class. BUG-002 — write-side; BUG-011 — read-side. Session D
   FSM решение (`ConfirmFlow.awaiting_confirmation` + deterministic handler)
   — analogous solution pattern для read_context, но subtler (read-context
   не имеет «yes/no» trigger).
3. `tg_parser/bot/handlers.py` L1–60 (router + FSM imports + TTL constant +
   patterns), L174–267 (`handle_text` — main routing entry point, where
   read_context UPDATE happens after agent call), L270–344
   (`_handle_confirmation_response` — should preserve read_context across
   confirm-clear). Read fully.
4. `tg_parser/bot/agent.py` L107–126 (`GeminiAgent.__init__` — system_prompt
   loading), L132–160 (`process_message` signature + contents construction),
   L310–333 (`_call_gemini` — payload[`systemInstruction`]). Здесь добавляем
   `read_context` parameter и injection в systemInstruction.
5. `tg_parser/bot/states.py` — current ConfirmFlow + PaginationFlow shape.
   Session H добавляет `ReadContextData` TypedDict (no new StatesGroup per
   D-1).
6. `tg_parser/bot/tools.py` L80–270 — TOOL_DECLARATIONS for read-tools.
   Identify which tools have `channel_id` in their schema (audit in § 1.3
   D-2). Verify per-tool: ask_question, search_knowledge_base, list_topics,
   get_topic_details, list_channels, get_document, get_related_topics,
   get_cross_channel_stats, get_pipeline_status.
7. `prompts/bot.yaml` v1.5.0 (post-PR-#56) — current sections: Instructions,
   Confirmation semantics, Pagination and numbering, Soft-delete semantics,
   Channel ID normalization, Fallback on empty results, Error classification.
   Session H adds new section «Implicit channel context (read-side)» between
   «Channel ID normalization» and «Fallback on empty results».
8. `tests/test_bot_fsm.py` L1–50 (FSM contract docstring), L286–319
   (`test_handler_passes_confirm_flow_state_matching_preview` — Session G
   wiring test, analogous structure for `test_handler_persists_read_context_after_list_topics`),
   L515–580 (`TestBug009SuggestionConfirmGuard` — Session G integration test
   pattern). Session H adds parallel `TestBug011ReadContextPreservation`
   class.
9. `tests/test_rag_prompt_config.py` `TestBotPromptBug012FormatDirective`
   class (BUG-012 PR #56 contract tests) — pattern для new
   `TestBotPromptBug011ReadContextDirective` class в Session H.

### 1.2 Required state

- Local repo на `origin/main` HEAD (≥ `a8ccf9a` Session G + PR #56 BUG-012
  squash). `git status` clean.
- VPS на Session G + BUG-012 deploy SHA. Session G watch closure GREEN
  (см. § 0 gate-1).
- Branch convention: `fix/bug-011-read-context-2026-05-XX` (XX = session
  start date, e.g. `03` if started 2026-05-03 morning, `04` if delayed).
- pytest baseline (default mode, без Postgres): **1995 passed** post-Session-G
  (verified 2026-05-02 with Postgres up; default mode produces 1869 — all
  bot+prompt tests included).

### 1.3 Gating decisions

- **D-1 (locked).** Storage: data-only via `FSMContext.update_data(read_context=...)`.
  No new StatesGroup. Read_context lives alongside ConfirmFlow / PaginationFlow.
- **D-2 (default — gating).** Tool scope (which read-tools track context):
  - **Phase 1 set** (5 tools): `ask_question`, `search_knowledge_base`,
    `list_topics`, `get_related_topics`, `get_cross_channel_stats` — все
    имеют `channel_id` параметр в Gemini schema, все operate on a specific
    channel's content.
  - **Excluded phase 1**: `get_topic_details` (operates on topic_id, not
    channel directly — channel embedded in topic data); `get_document`
    (operates on source_ref containing channel implicitly); `list_channels`
    (global by design — would always reset read_context); `get_pipeline_status`
    (admin/dev tool, не часто часть user reading session).
  - **Альт A**: 8 tools — include get_topic_details + get_document. **Reject**:
    expands surface unnecessarily; topic_id / source_ref carry channel info
    intrinsically.
  - **Альт B**: 1 tool — only `list_topics` (the production-trace tool).
    **Reject**: BUG-011 root cause is general read-context loss class, not
    specific to list_topics. The fix should be general (analogous to Session
    D PaginationFlow being general across list_*).
- **D-3 (default — gating).** Update logic (when to write `last_channel_id`):
  - **Default**: update on every read-tool call where `args["channel_id"]`
    is non-empty, regardless of result `total`. Even on empty results
    (`total=0` triggers BUG-007 suggestion path) — the user's *intent* was
    to read from that channel.
  - **Альт A**: only on `total > 0` success. **Reject**: conflicts with
    BUG-007 suggestion redirect — user typo'ing channel name then accepting
    suggestion would lose context. Also brittle: empty channels still count
    as «user is in this channel».
  - **Альт B**: don't update if read_context was *injected* (i.e. don't
    re-write the same value if LLM used the injection). **Recommendation**:
    accept this nuance — if `args["channel_id"] == read_context.last_channel_id`
    AND we just injected → don't touch (no-op write to refresh `created_at`
    is fine, doesn't loop). Treat as defensive idempotency, not an actual
    feedback-loop concern.
  - **Альт C**: update only when LLM passed `channel_id` in args (not from
    injection). **Reject**: introduces brittle semantic distinction; Альт B
    above is sufficient (timestamp refresh on equal value is harmless).
- **D-4 (locked).** Resolution path: programmatic injection в
  `systemInstruction`. Format candidate (to refine in implementation):
  ```
  Implicit channel context (BUG-011, Session H):
  - The user has been reading from channel "X" in the prior turns.
  - If their next request mentions a channel name explicitly — use the
    explicit one (НИКОГДА не override).
  - If their request is ambiguous re: channel ("покажи 5 главных тем",
    "найди про APOE") AND it would otherwise default to global/cross-channel —
    use channel "X" with a 1-sentence acknowledgement in your response
    (e.g. "Показываю топ-5 тем канала AgeManagment:").
  - This rule is read-side ONLY. NEVER apply it to write-tools (add_channel,
    remove_channel, pause_channel, resume_channel, trigger_pipeline,
    set_llm_config, reset_llm_config) — those always require an explicit
    channel_id from the user. (D-6 immunity rule — BUG-002 mitigation.)
  ```
  Append at end of `systemInstruction.parts[0].text` ONLY when read_context
  is non-stale (TTL check).
- **D-5 (default — gating).** TTL value:
  - **Default**: 15 минут. Justification: read sessions naturally span
    10–15 min as user explores topics, asks follow-ups, drills down. 5 min
    (ConfirmFlow / PaginationFlow value) too short — leads to surprise
    "where did context go". 30 min too long — user comes back next day,
    sees unexpected channel scoping.
  - **Альт A**: 5 min (match existing). **Pros**: consistency. **Cons**:
    too short for read flows.
  - **Альт B**: 30 min. **Pros**: matches typical reading session span.
    **Cons**: lingers across coffee breaks; surprise factor.
  - **Альт C**: configurable env var `BOT_READ_CONTEXT_TTL_SECONDS` (default
    900). **Pros**: tunable. **Cons**: extra config surface; unlikely to be
    tuned in practice. Defer until use-case appears.
- **D-6 (locked).** Read-context MUST NOT influence write-tools. Implementation:
  prompt rule above + integration test verifying write-tool calls with
  active read_context still require explicit channel_id from user.
- **D-7 (default — gating).** Reset triggers:
  - **Default**: TTL only. No active reset triggers.
  - **Альт A**: clear on `/start` and `/help` commands. **Pros**: aligns with
    user expectation that /start = fresh session. **Cons**: marginal benefit;
    /start is rare during active session.
  - **Альт B**: clear when LLM emits `list_channels` (user is browsing
    globally). **Reject**: brittle heuristic; user might browse channels
    then return to a specific one — clearing breaks that flow.
  - **Recommendation**: take Альт A as a low-risk addition (1 LOC + 1
    test). Otherwise default = TTL only.

---

## 2. Reproduction context

### 2.1 BUG-011 production observation (2026-04-30, by Alexander)

```
[turn 1] User:  темы канала AgeManagment
[turn 1] Bot:   list_topics(channel_id="AgeManagment")
                → total=75, items=[...первая страница 10 тем...]
[turn 1] Bot:   "Темы канала AgeManagment (показано 1–10 из 75): ..."

[turn 2] User:  покажи 5 главных тем
[turn 2] Bot:   list_topics()  ← BUG-011 manifests here
                → returns global top-5 across ALL channels
[turn 2] Bot:   "Главные темы (топ-5 по всей базе): ..."

EXPECTED:       list_topics(channel_id="AgeManagment", limit=5)
                → channel-scoped top-5 from AgeManagment
EXPECTED:       "Топ-5 тем канала AgeManagment: ..."
```

User's natural conversational flow assumes the bot remembers the implicit
subject. The agent loop receives only `[{role:user, parts:[{text:"покажи 5
главных тем"}]}]` with no carry-over — Gemini correctly treats it as a
fresh global query.

### 2.2 Why prompt-only is insufficient

Same lesson as BUG-002: prompt-discipline asking LLM to «remember context»
is unreliable across turns when **the LLM has no state to remember**. Gemini
2.5 receives only the current user turn + system instruction; no chat
history. Adding «remember last channel» to system prompt without
programmatic injection is wishful thinking.

Programmatic injection (Session H D-4) makes the context **part of the
systemInstruction** for the duration of the read-context window — the LLM
sees the channel name as authoritative system context, not as memory it has
to maintain.

### 2.3 What Session H does NOT do

- **No conversation history** — Session H does not introduce a per-chat
  message history that gets sent to Gemini. That would be a much larger
  change (token budget, summarization, eviction policy). Session H tracks
  ONLY the most-recent read channel as a single value.
- **No write-tool context** — read_context is never passed to write-tools
  (D-6). Write tools require explicit user mention of channel.
- **No multi-channel tracking** — only `last_channel_id`, not a list of
  recent channels. If user switches channels, prior channel is overwritten.
- **No LLM-side decision injection** — read_context resolution always goes
  through the LLM's interpretation (system prompt rule + agent injection).
  The handler does NOT deterministically replay the last tool with the new
  user query — that's PaginationFlow's job for the specific «ещё» case.

---

## 3. Implementation plan

### 3.1 Step 1 — TypedDict for read_context (5 мин)

`tg_parser/bot/states.py`:

```python
# Add at end of file, after PaginationFlow class:

from typing import TypedDict

class ReadContextData(TypedDict):
    """Shadow read-context preserved across read-tool turns (BUG-011, Session H).

    Stored as ``FSMContext.update_data(read_context=...)`` — NOT a state.
    Coexists with active ``ConfirmFlow.awaiting_confirmation`` /
    ``PaginationFlow.has_active_list`` states; persists across state.clear()
    via explicit re-write in handler.

    See ``handlers._refresh_read_context`` for update sites and
    ``handlers._read_context_for_agent`` for resolution path.
    """

    last_channel_id: str
    last_tool: str
    created_at: str  # ISO UTC timestamp, used for TTL check
```

### 3.2 Step 2 — Tool scope manifest (5 мин)

`tg_parser/bot/tools.py` — add after `_WRITE_TOOLS_REQUIRING_CONFIRM` frozenset
(introduced in Session G):

```python
# BUG-011 (Session H): read-tools whose Gemini declarations carry a
# `channel_id` parameter — the agent loop tracks the most-recent
# channel_id from these calls into FSMContext.read_context so the LLM
# can resolve implicit channel references on subsequent turns.
# Excluded: get_topic_details (topic_id-based), get_document (source_ref-based),
# list_channels (global by design), get_pipeline_status (admin tool).
# See BUG_LOG.md § BUG-011 § Proposed fix and Session H runbook D-2.
_READ_TOOLS_TRACKED_FOR_CONTEXT: frozenset[str] = frozenset(
    {
        "ask_question",
        "search_knowledge_base",
        "list_topics",
        "get_related_topics",
        "get_cross_channel_stats",
    }
)
```

Re-export from `tg_parser/bot/tools.py` so handlers can import it for
update-site logic.

### 3.3 Step 3 — Update site in handlers (15 мин)

`tg_parser/bot/handlers.py`:

1. Import `_READ_TOOLS_TRACKED_FOR_CONTEXT` from `bot.tools` and
   `ReadContextData` from `bot.states`.
2. Add TTL constant near `PENDING_TTL_SECONDS`:
   ```python
   READ_CONTEXT_TTL_SECONDS = 15 * 60  # 15 min, see Session H D-5
   ```
3. Add helper `_refresh_read_context(state, tool_name, args)`:
   ```python
   async def _refresh_read_context(
       state: FSMContext, tool_name: str, args: dict[str, Any]
   ) -> None:
       """Update FSMContext data with the latest read_context after a
       tracked read-tool call (BUG-011, Session H)."""
       if tool_name not in _READ_TOOLS_TRACKED_FOR_CONTEXT:
           return
       channel_id = args.get("channel_id")
       if not channel_id:  # None / empty / missing
           return
       data = await state.get_data()
       data["read_context"] = ReadContextData(
           last_channel_id=channel_id,
           last_tool=tool_name,
           created_at=_utcnow_iso(),
       )
       await state.update_data(**data)
   ```
4. Add helper `_read_context_for_agent(state)`:
   ```python
   async def _read_context_for_agent(
       state: FSMContext,
   ) -> ReadContextData | None:
       """Return non-stale read_context for agent injection, or None."""
       data = await state.get_data()
       rc = data.get("read_context")
       if not rc or not isinstance(rc, dict):
           return None
       created_at_iso = rc.get("created_at")
       if _is_stale(created_at_iso, READ_CONTEXT_TTL_SECONDS):
           return None
       return rc  # type: ignore[return-value]
   ```
   `_is_stale` — generalize existing `_is_pending_expired` to take TTL
   parameter; rename or add second helper.
5. Wire `_read_context_for_agent` into `handle_text` BEFORE `agent.process_message`:
   ```python
   read_context = await _read_context_for_agent(state)
   ...
   result = await agent.process_message(
       user_text,
       current_user=current_user,
       bot=message.bot,
       chat_id=message.chat.id,
       read_context=read_context,
   )
   ```
6. Wire `_refresh_read_context` into the agent result handling — but
   actually, since the agent makes the tool calls internally, `_refresh_read_context`
   needs to be called from `agent.process_message` itself (or from a
   callback the handler registers). **Decision point**: the cleanest place
   is to have `agent.process_message` return `read_tools_called: list[tuple[str, dict]]`
   in `AgentResult`, and have the handler iterate after the agent returns.
   See § 3.4 for AgentResult expansion.

### 3.4 Step 4 — Agent injection + result expansion (30 мин)

`tg_parser/bot/agent.py`:

1. Expand `AgentResult` dataclass with `read_tools_called` field:
   ```python
   @dataclass
   class AgentResult:
       response_text: str
       preview_pending: dict[str, Any] | None = None
       pagination_pending: dict[str, Any] | None = None
       read_tools_called: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
       # Each tuple = (tool_name, args). Handler iterates in order to
       # update FSMContext.read_context with the LATEST channel-bound
       # read-tool call (BUG-011, Session H).
   ```
2. Add `read_context: ReadContextData | None = None` parameter to
   `process_message`. Forward to `_call_gemini` via instance attr or
   parameter chain.
3. In `_call_gemini`, append read_context block to `systemInstruction`
   when present:
   ```python
   system_text = self._system_prompt
   if read_context is not None:
       chan = read_context["last_channel_id"]
       system_text += (
           f"\n\nImplicit channel context (read-side, BUG-011):\n"
           f"- The user has been reading from channel \"{chan}\" "
           f"in the prior turns.\n"
           f"- If their next request mentions a channel name explicitly — "
           f"use the explicit one. Never override an explicit reference.\n"
           f"- If their request is ambiguous re: channel — use \"{chan}\" "
           f"and acknowledge it in 1 sentence (e.g. \"Показываю темы канала "
           f"{chan}: ...\").\n"
           f"- This rule is read-side ONLY. NEVER apply to write-tools."
       )
   payload["systemInstruction"]["parts"][0]["text"] = system_text
   ```
4. In the agent loop, append to `read_tools_called` after each successful
   tracked-tool call:
   ```python
   if tool_name in _READ_TOOLS_TRACKED_FOR_CONTEXT and tool_args.get("channel_id"):
       read_tools_called.append((tool_name, dict(tool_args)))
   ```
5. Return `read_tools_called` in the final `AgentResult`.

### 3.5 Step 5 — Handler post-call refresh (10 мин)

`tg_parser/bot/handlers.py:handle_text` — after `_send_text_response`:

```python
for tool_name, tool_args in result.read_tools_called:
    await _refresh_read_context(state, tool_name, tool_args)
```

This persists across `state.set_state(ConfirmFlow.awaiting_confirmation)`
because aiogram's MemoryStorage stores `data` separately from `state`.
Verify via test: state-set followed by data-write does not lose data.

`_handle_confirmation_response` — at the END (before final `await state.clear()`),
preserve read_context across clear:

```python
data_before = await state.get_data()
read_context = data_before.get("read_context")
await state.clear()
if read_context is not None:
    await state.update_data(read_context=read_context)
```

Same for `_handle_pagination_response`. (Session H expansion of D-1.)

### 3.6 Step 6 — Reset trigger (5 мин, optional per D-7)

If D-7 Альт A accepted: clear read_context in `cmd_start` and `cmd_help`:

```python
@router.message(Command("start"))
async def cmd_start(...):
    await state.clear()  # Already clears state, but data lingers.
    await state.update_data(read_context=None)  # Explicit reset.
    ...
```

### 3.7 Step 7 — Prompt update (10 мин)

`prompts/bot.yaml` v1.5.0 → v1.6.0:

- Bump version + description: «v1.6.0 BUG-011 implicit channel context
  (read-side) preserved across turns; write-tools immune (D-6)».
- Add new section between «Channel ID normalization» (current section) and
  «Fallback on empty results»:

```yaml
    Implicit channel context for read-tools (Session H, BUG-011):
    - The agent framework injects an «Implicit channel context» block into
      systemInstruction at runtime when the user has been reading from a
      specific channel in prior turns (TTL 15 min). When you see a block
      like «The user has been reading from channel "X" in the prior turns»,
      treat it as authoritative system context — apply it ONLY to read-tools
      (ask_question, search_knowledge_base, list_topics, get_related_topics,
      get_cross_channel_stats) AND ONLY when the user's request is
      ambiguous re: channel.
    - HARD RULE (D-6 immunity): NEVER apply implicit channel context to
      write-tools (add_channel, remove_channel, pause_channel, resume_channel,
      trigger_pipeline, set_llm_config, reset_llm_config). Write tools
      always require an explicit channel_id from the user message — re-using
      implicit context would re-open the BUG-002 hallucination class on a
      different vector.
    - When using implicit context: acknowledge it in 1 sentence (e.g.
      «Показываю топ-5 тем канала AgeManagment: ...»). The user expects to
      see WHICH channel you scoped to.
    - When the user explicitly mentions a different channel — that ALWAYS
      overrides implicit context. Never override an explicit reference.
    - When implicit context is absent or stale (>15 min since last
      read-tool call), default to global cross-channel behavior as before.
```

### 3.8 Step 8 — BUG_LOG + CHANGELOG updates (10 мин)

- `BUG_LOG.md` § BUG-011 — add «Update 2026-05-XX — Session H landed» row
  (mirror Session G's BUG-009 update format).
- `CHANGELOG.md` — add new section under `## [Unreleased]`, BEFORE the
  prompt v1.5.0 BUG-012 section. Title: «Session H — Bot read-context
  preservation across turns: BUG-011 structural close (2026-05-XX)».

---

## 4. Testing strategy

### 4.1 Unit tests (new file or extend `test_bot_fsm.py`)

**Decision** (default): extend `tests/test_bot_fsm.py` since BUG-011 is
in same FSM-class as BUG-002 / BUG-004 / BUG-009. If new tests > 15 →
split to `tests/test_bot_read_context.py`.

#### Class A — `_refresh_read_context` update logic (5 tests)
- A1: tracked tool + channel_id present → data updated.
- A2: tracked tool + channel_id missing/None → no-op.
- A3: untracked tool (e.g. `add_channel`) + channel_id → no-op (write-tools
  must NOT influence read_context, D-6).
- A4: tracked tool + empty-string channel_id → no-op.
- A5: idempotency — calling twice with same args refreshes `created_at`
  but doesn't loop.

#### Class B — `_read_context_for_agent` resolution + TTL (4 tests)
- B1: no data → returns None.
- B2: fresh data → returns ReadContextData.
- B3: stale data (created_at > 15 min ago) → returns None.
- B4: data without created_at → defensive None (don't crash).

#### Class C — Agent injection (3 tests)
- C1: `process_message` with `read_context=None` → systemInstruction
  unchanged (no injection).
- C2: `process_message` with `read_context={...}` → systemInstruction
  contains «channel \"X\"» literal.
- C3: agent returns `read_tools_called` populated when LLM calls
  `list_topics(channel_id=X)` → handler can iterate for refresh.

#### Class D — Integration / end-to-end (3 tests)
- D1: `test_implicit_channel_context_preserved_across_read_turns` — direct
  BUG-011 regression. Mock GeminiAgent: turn 1 returns
  `read_tools_called=[("list_topics", {"channel_id": "AgeManagment"})]`,
  turn 2 user says «покажи 5 главных тем» — assert agent called with
  `read_context={"last_channel_id": "AgeManagment", ...}`.
- D2: explicit channel mention overrides implicit context — turn 2 user
  says «топ темы канала Lab4health» → agent receives read_context but
  must call `list_topics(channel_id="Lab4health")` (verify via prompt
  block instructing to use explicit channel).
- D3: write-tools immune (D-6) — turn 1 read sets context, turn 2 user
  says «удали канал» without specifying which → bot must ASK for explicit
  channel, NOT use implicit context.

#### Class E — FSM-state interaction (3 tests)
- E1: read_context preserved across `ConfirmFlow.awaiting_confirmation`
  — read sets context, write-preview triggers ConfirmFlow, user says «да»,
  confirm executes, read_context still in data after `state.clear()`.
- E2: read_context preserved across `PaginationFlow` — same shape.
- E3: read_context cleared on `/start` (per D-7 Альт A if accepted).

#### Class F — Prompt content contracts (3 tests, mirror BUG-012 pattern)
- F1: `test_bot_yaml_version_at_least_1_6_0` — semver pin.
- F2: `test_bot_yaml_mentions_bug_011_implicit_context` — section presence.
- F3: `test_bot_yaml_d6_write_tool_immunity` — explicit «NEVER apply to
  write-tools» phrase + write-tool list enumerated.

**Total: ~21 tests**, but several can be parametrized → ~14–15 tests in
practice.

### 4.2 Risk mitigations (R-1, R-2, R-3 pattern)

- **R-1**: contract drift between `_READ_TOOLS_TRACKED_FOR_CONTEXT`
  frozenset and actual TOOL_DECLARATIONS — analogous to Session G
  bidirectional contract. **Mitigation**: bidirectional contract test in
  Class A (forward: every tool in frozenset has `channel_id` parameter
  in its declaration; reverse: NOT applicable since we deliberately
  exclude some channel_id-bearing tools per D-2).
- **R-2**: read_context bleeds into write-tools through prompt-rule
  failure — covered by D3.
- **R-3**: pre-existing tests touching `agent.process_message` signature
  break due to new `read_context` parameter. **Mitigation**: default
  `read_context=None` → backwards-compatible. Audit existing call sites
  via `rg "process_message\("` before commit. Update only if a test
  asserts specific signature — should be rare.

---

## 5. Verification gates

### 5.1 Local (before commit)

- [ ] All new tests pass (`pytest tests/test_bot_fsm.py
  tests/test_bot_read_context.py tests/test_rag_prompt_config.py -q`).
- [ ] Full pytest (default mode) — baseline 1869 passed → expect ~1882–1885
  passed (+13–16 new), 0 regressions.
- [ ] Full pytest (with Postgres) — baseline 1995 → expect ~2008–2010.
- [ ] `ruff check .` clean. `ruff format --check .` clean.
- [ ] Manual smoke (local Docker if available): «темы канала X» → «5
  главных тем» → assert second response references X.

### 5.2 CI (PR open)

- [ ] All 5 CI checks GREEN (Test Python 3.12, Lint Documentation,
  Alembic Guardrails, Alembic Runtime Upgrade Smoke, Docker Build).
- [ ] PR description includes `Closes BUG-011 (#XX)` once issue filed.

### 5.3 Production deploy gate

Code change (not config-only — requires Docker rebuild + `tg_bot` recreate):

```bash
ssh prod 'cd ~/TG_parser && git pull --ff-only origin main \
  && docker compose build tg_parser \
  && docker compose up -d --no-deps --force-recreate tg_bot'
```

### 5.4 Smoke verification (post-deploy)

**BUG-011 direct regression** (real Telegram bot):
1. User: «темы канала AgeManagment» → bot returns ~75 topics for
   AgeManagment.
2. User: «покажи 5 главных тем» (no channel reference) → bot MUST return
   5 topics from AgeManagment + acknowledge in 1 sentence.

**Explicit-override regression**:
3. User: «топ темы канала Lab4health» → bot MUST switch to Lab4health
   (NOT use implicit AgeManagment context).

**Write-tool immunity (D-6) regression**:
4. After step 1+2, user says «удали канал» (no channel ref) → bot MUST
   NOT auto-fill AgeManagment; instead ask which channel.

**Session D regression preserved**:
5. «Удали канал mind_rise» → preview → «да» → soft-delete works
   (legitimate ConfirmFlow path, read_context should not interfere).

**TTL expiry**:
6. After step 1, wait >15 min, then «5 главных тем» → bot returns global
   top-5 (TTL expired, no context).

---

## 6. PR / commit plan

Single PR (mirrors Session G — small enough for atomic review):

**Branch**: `fix/bug-011-read-context-2026-05-XX`

**Commit structure** (suggested):
1. `feat(bot): add ReadContextData TypedDict + tracked-tools frozenset` —
   states.py + tools.py constants.
2. `feat(bot): plumb read_context through agent.process_message` —
   agent.py changes (signature, AgentResult expansion, systemInstruction
   injection).
3. `feat(bot): wire read_context update + retrieval in handlers` —
   handlers.py (helpers, handle_text, FSM-state preservation).
4. `prompts(bot): v1.6.0 implicit channel context section` — prompts/bot.yaml.
5. `test(bot): BUG-011 read_context preservation contract + integration` —
   test_bot_fsm.py + test_rag_prompt_config.py.
6. `docs(session-h): BUG_LOG + CHANGELOG closure rows` — docs/notes/BUG_LOG.md
   + CHANGELOG.md.

**PR title**: `fix(bug-011): bot read-context preservation across turns
(Session H)`

**PR body template** (use file body via `/tmp/pr_body_bug011.md` to avoid
heredoc shell hangs — lesson from Session G/PR #56):

```
## Summary
Closes BUG-011 — bot lost subject channel context across turns
(«темы канала X» → «5 главных тем» returned global instead of X-scoped).

## Architecture
- read_context lives in FSMContext data alongside ConfirmFlow / PaginationFlow.
- Tracked tools (5): ask_question, search_knowledge_base, list_topics,
  get_related_topics, get_cross_channel_stats.
- TTL 15 min. Programmatic injection into Gemini systemInstruction. D-6
  immunity for write-tools.

## Test plan
- [x] Class A guard logic (5 tests)
- [x] Class B resolution + TTL (4 tests)
- [x] Class C agent injection (3 tests)
- [x] Class D integration (3 tests, incl. direct BUG-011 regression)
- [x] Class E FSM-state interaction (3 tests)
- [x] Class F prompt content (3 tests)
- [x] Full pytest 0 regressions
- [x] ruff check + format clean

## Smoke (post-deploy)
[copy from § 5.4 above]

## Out of scope
- TD-bot-source-username-alias (BUG-010)
- TD-bot-confirm-coverage-completeness (Session G TD)
```

---

## 7. Out of scope / TD carry-forward

Session H закрывает только BUG-011. НЕ касается:

- **BUG-010** (`get_source_by_username` PK vs username UX mismatch) —
  отдельная сессия, ~80 LOC + 4 testcontainers tests. TD-bot-source-username-
  alias.
- **TD-bot-confirm-coverage-completeness** (Session G TD) — расширение
  preview/confirm на 6 user-management tools без current `confirm`
  parameter. ~400 LOC + 25 tests. Defer until concrete pain-driven
  use-case.
- **Multi-channel context tracking** — Session H tracks only
  `last_channel_id`, single value. Tracking «recently visited channels»
  list would be Session H-2 if user feedback shows the need.
- **Conversation history sent to Gemini** — Session H is shadow-state
  only; no chat history threaded into `contents`. Full chat memory is
  a separate scope (token budget, summarization, eviction — too large
  for one session).
- **Cross-chat read_context** — same `last_channel_id` carried between
  multiple chats / sessions of the same user. Out of scope; per-chat
  isolation matches existing FSMContext semantics.

---

## 8. Risks (R-1 .. R-N)

- **R-1** — frozenset contract drift (see § 4.2 R-1).
- **R-2** — write-tools accidentally use read_context (see § 4.2 R-2).
- **R-3** — `agent.process_message` signature break (see § 4.2 R-3).
- **R-4** — read_context lost across `state.clear()` in
  `_handle_confirmation_response`. **Mitigation**: explicit re-write in §
  3.5 (data_before snapshot + post-clear restore). Tests E1, E2.
- **R-5** — TTL clock skew between handler and agent. **Mitigation**:
  TTL check happens ONCE in handler (`_read_context_for_agent`), result
  passed to agent. Agent does not re-validate TTL (agent is stateless re:
  time).
- **R-6** — read_context corruption from concurrent writes (e.g. two
  user messages racing). **Mitigation**: aiogram FSMContext is
  per-chat-locked at the dispatcher level (single-shot `update_data`).
  Verify via existing FSMContext concurrency tests (no new tests needed).
- **R-7** — Gemini's interpretation of «implicit channel context» block
  inconsistent across versions. **Mitigation**: explicit «acknowledge in
  1 sentence» rule + integration test asserting acknowledgement substring
  («Показываю темы канала X»). If Gemini drifts, prompt-bump fixes it
  without code changes.
- **R-8** — TTL=15min surprise factor (user comes back later expecting
  fresh state). **Mitigation**: D-7 Альт A reset on `/start` reduces
  exposure. Prompt section mentions «when implicit context is absent or
  stale, default to global» — LLM mentions this in response.

---

## 9. Open questions for session-start

Before starting implementation, confirm the following with the user:

1. **D-2 final**: 5-tool scope (`ask_question`, `search_knowledge_base`,
   `list_topics`, `get_related_topics`, `get_cross_channel_stats`) — accept,
   or expand to include `get_topic_details` / `get_document` / others?
2. **D-3 final**: update on every read-tool call (ignoring result `total`)
   — accept, or restrict to successful results?
3. **D-5 final**: TTL = 15 min — accept, or adjust to 5 min (consistency)
   / 30 min (longer reading sessions) / configurable via env var?
4. **D-7 final**: reset on `/start` and `/help` commands — accept (small
   addition, low risk), or default to TTL-only?
5. **Branch name**: `fix/bug-011-read-context-2026-05-XX` — confirm date.
6. **Test file split threshold**: extend `tests/test_bot_fsm.py` (current
   default if ≤ 15 new tests) or create `tests/test_bot_read_context.py`
   (if > 15 new tests)?
7. **Issue filing**: file new GH issue for Session H tracker (analogous
   to #49 for Session G), or reference TD-bot-read-context-preservation
   informally? Recommend file — provides cross-link from CHANGELOG +
   PR body.

Defaults answer all questions affirmatively where applicable. The
session can proceed with defaults if the user confirms «proceed with
locked + default decisions» at session start.

---

## Appendix A — File ranges quick reference (after Session G + PR #56)

| File | Section | Lines |
|---|---|---|
| `tg_parser/bot/handlers.py` | imports + constants + patterns | 1–60 |
| `tg_parser/bot/handlers.py` | `handle_text` main entry | 174–267 |
| `tg_parser/bot/handlers.py` | `_handle_confirmation_response` | 270–344 |
| `tg_parser/bot/handlers.py` | `_handle_pagination_response` | 347–434 |
| `tg_parser/bot/handlers.py` | helpers (`_format_*`, `_utcnow_iso`, `_is_pending_expired`) | 437–545 |
| `tg_parser/bot/agent.py` | imports + constants | 1–75 |
| `tg_parser/bot/agent.py` | `AgentResult` dataclass | 77–98 |
| `tg_parser/bot/agent.py` | `GeminiAgent.__init__` | 108–127 |
| `tg_parser/bot/agent.py` | `process_message` | 132–308 |
| `tg_parser/bot/agent.py` | `_call_gemini` | 310–368 |
| `tg_parser/bot/states.py` | full file | 1–36 (will become ~50 after Session H) |
| `tg_parser/bot/tools.py` | imports + frozensets | 1–80 |
| `tg_parser/bot/tools.py` | TOOL_DECLARATIONS read-tools | 80–270 |
| `tg_parser/bot/tools.py` | TOOL_DECLARATIONS write-tools | 270–620 |
| `tg_parser/bot/tools.py` | `_TOOL_EXECUTORS` map | 770–800 |
| `tg_parser/bot/tools.py` | `_check_confirm_flow_match` (Session G guard) | 802–860 |
| `tg_parser/bot/tools.py` | `execute_tool` | 863–900 |
| `tg_parser/bot/tools.py` | tool executors (`_exec_*`) | 1030+ |
| `prompts/bot.yaml` | metadata | 1–10 |
| `prompts/bot.yaml` | system.prompt | 11–80 (will grow ~20 lines after Session H) |
| `tests/test_bot_fsm.py` | imports + fixtures + 9 existing test classes | 1–1050 |
| `tests/test_rag_prompt_config.py` | `TestBotPromptBug012FormatDirective` | 1521–1593 |

---

**End of Session H pre-flight document.** Ready for execution after
gate-1 verification (§ 0) GREEN.
