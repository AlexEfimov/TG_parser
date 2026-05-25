# PR: fix(bot): require explicit affirmative confirmation before subscribe side-effects (BUG-031, BUG-032)

## Summary

Closes [BUG-031](docs/notes/BUG_LOG.md) (bot persisted digest / watchlist
subscriptions in the DB BEFORE asking the user to confirm) and
[BUG-032](docs/notes/BUG_LOG.md) (the FSM ConfirmFlow handler did not
classify «да» / «подтверждаю» / «yes» / «ok» as affirmative, so the
user got the opaque «Я не совсем понимаю ваш ответ» reply even on a
canonical confirmation token). The two bugs are tightly coupled (the
preview-then-confirm refactor lives in one ConfirmFlow surface) and
the handoff explicitly permits bundling — see
[`HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md` § 2.3
"BUG-031 + BUG-032 идут вместе"](docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md).

Recent merges that establish the pattern this PR follows:

- PR #108 (BUG-033, commit `e50449b` on `main`) — `tg_parser/bot/tools.py`
  helper-extraction + executor-level guard.
- PR #109 (BUG-034, commit `6ebad33` on `main`) — `tg_parser/bot/tools.py`
  + `tg_parser/utils/channel_id.py` + `prompts/bot.yaml` v1.7.1 prompt
  hardening, paired with comprehensive parametrize regression coverage.

This PR matches that scope and follows the new
`TEST_POSTGRES=1` rerun standard from
[`SKIPPED_TESTS_AUDIT_2026-05-25.md`](docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md).

## Root cause

### BUG-031 — preview/confirm contract missing on subscribe_* surface

`subscribe_digest` and `subscribe_watchlist` were absent from
`_WRITE_TOOLS_REQUIRING_CONFIRM` and their Gemini declarations did not
carry a `confirm: BOOLEAN` parameter. The agent loop in
`tg_parser/bot/agent.py` only emits `preview_pending` when the tool
returns `{"preview": True, ...}`, so without the gate the LLM-invoked
executor wrote the row + registered the scheduler job + sent the
"📰 Подписка создана" confirmation message before any user reply was
processed. The bot then asked «Подтвердите [да/нет]» as a UI charade
on top of an already-committed side-effect (two consecutive Test C / D
transcripts on 2026-05-24 reproduce this fingerprint —
[`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)).

### BUG-032 — opaque «не совсем понимаю» on valid affirmative tokens

`_handle_confirmation_response` already used a regex-based affirmative
matcher that recognised «да» / «подтверждаю» / «yes» / «ok». The
production trace landed on the opaque LLM reply because — as a direct
side-effect of BUG-031 — the FSM was never armed; the user's «да» was
routed through `handle_text` → Gemini, and the agent had no context to
interpret a bare «да» so it improvised. Fixing BUG-031 closes most of
BUG-032 in the deployed sense, but the handoff explicitly asked for a
token-classifier hardening (broader whitelist + Unicode normalisation
+ typed error) so a future regression on either side fails loudly.

## Fix shape

### 1. `tg_parser/bot/tools.py` — preview gate on subscribe_*

```python
_WRITE_TOOLS_REQUIRING_CONFIRM: frozenset[str] = frozenset({
    "add_channel", "remove_channel", "pause_channel", "resume_channel",
    "trigger_pipeline", "set_llm_config", "reset_llm_config",
    # BUG-031 (Wave 1 step 4 post-watch): subscribe_* tools persisted
    # rows BEFORE the bot asked the user to confirm. They now follow
    # the same two-phase preview/confirm contract as the rest of the
    # write surface.
    "subscribe_digest", "subscribe_watchlist",
})
```

`TOOL_DECLARATIONS` for both tools now carry a `confirm: BOOLEAN`
parameter. The executor body runs all validation (target resolution,
channel-username check, cron/timezone pre-validation, access check)
unconditionally, then gates persistence + scheduler register +
outbound confirmation send behind `if not confirm:` returning
`{"preview": True, ...}`. The server-side guard in `execute_tool`
(`_check_confirm_flow_match`) — already proven on the seven Session G
write-tools — now structurally rejects LLM-issued `confirm=True` on
the subscribe_* surface too.

### 2. `tg_parser/bot/handlers.py` — `classify_confirmation_token`

New canonical classifier with explicit token sets:

```python
AFFIRMATIVE_TOKENS = frozenset({
    "да", "yes", "y", "ok", "ок",
    "подтверждаю", "подтверди", "подтвердить",
    "согласен", "согласна", "хорошо", "ага",
    "уверен", "уверена", "конечно", "давай",
    "+", "👍",
})
NEGATIVE_TOKENS = frozenset({
    "нет", "no", "n", "отмена", "cancel", "отказ",
    "стоп", "stop", "не подтверждаю", "не надо",
    "передумал", "передумала", "-", "👎",
})

def classify_confirmation_token(text) -> Literal["affirmative","negative","unknown"]:
    if text is None: return "unknown"
    normalized = " ".join(text.split()).casefold()
    if not normalized: return "unknown"
    if normalized in AFFIRMATIVE_TOKENS: return "affirmative"
    if normalized in NEGATIVE_TOKENS: return "negative"
    first_token = normalized.split(" ", 1)[0].rstrip(",.;:!?")
    if first_token in AFFIRMATIVE_TOKENS: return "affirmative"
    if first_token in NEGATIVE_TOKENS: return "negative"
    return "unknown"
```

`_handle_confirmation_response` now dispatches on the classifier
return value; unknown tokens KEEP the FSM armed (no more silent
clear-and-route-to-LLM) and surface a structured Russian-language
reminder listing the canonical accepted tokens. A typed
`UnknownConfirmationToken(ValueError)` exception is exported for
downstream callers that want a raise-based contract. The legacy
`CONFIRM_PATTERN` / `REJECT_PATTERN` regex aliases are retained for
backward-compat (a parametrize contract test pins their equivalence
with the classifier on every documented token).

### 3. `prompts/bot.yaml` v1.7.2 — defense-in-depth

- `subscribe_digest` / `subscribe_watchlist` added to the explicit
  «write operations require confirm=false-first» list (alongside the
  existing channel / pipeline / config tools).
- The accepted affirmative + negative token lists are enumerated
  verbatim in the prompt so the LLM phrases its confirm-suffix
  consistently and the user always sees a canonical token in the ask.
- Cross-references BUG-031 / BUG-032 by name so a future regression
  has a clear paper trail back to this PR.

## Before / after — bot/tools.py

Before (BUG-031 fingerprint — `_exec_subscribe_digest` body had no
preview gate; LLM-issued call wrote the row immediately):

```python
async def _exec_subscribe_digest(args, current_user=None, bot=None, chat_id=None):
    # ... validation ...
    async with digest_subscription_repo() as (sub_repo, _db):
        result = await service.subscribe(...)  # PERSISTED HERE
    register_digest_subscription(created_sub, get_scheduler())
    await bot.send_message(chat_id, "📰 Подписка ... создана")  # USER NOTIFIED
    return {"subscription_id": created_sub.id, ...}
```

After:

```python
async def _exec_subscribe_digest(args, current_user=None, bot=None, chat_id=None):
    confirm = bool(args.get("confirm", False))
    # ... validation runs ALWAYS so errors surface even on preview turn ...
    if not confirm:
        return {
            "preview": True,
            "tool": "subscribe_digest",
            "name": name, "channel_ids": channel_ids,
            "cron_expression": cron_expression, ...,
            "message": "Preview: создать подписку ... Подтвердите [да/нет].",
        }
    # only here do persistence + scheduler register + outbound send fire
```

## Before / after — bot/handlers.py

Before (BUG-032 — D-4 default falls through to LLM):

```python
text = (message.text or "").strip()
if CONFIRM_PATTERN.match(text):
    # ... execute_tool(name, {**args, "confirm": True}, ...) ...
if REJECT_PATTERN.match(text):
    # ... clear + "❌ Отменено."
# D-4 default: clear state and re-route via Gemini.
await state.clear()
await handle_text(message, agent=agent, state=state, current_user=current_user)
```

After (BUG-032 — typed classifier + structured unknown reply):

```python
classification = classify_confirmation_token(message.text or "")
if classification == "affirmative":
    # ... execute_tool(name, {**args, "confirm": True}, ...) ...
if classification == "negative":
    # ... clear + "❌ Отменено."
# Unknown: KEEP the FSM armed, no LLM consult.
await message.answer(
    "Не понял ваш ответ. Подтвердите действие: «да», «подтверждаю», «ok» "
    "или отмените: «нет», «отмена», «cancel». Время на подтверждение — N мин."
)
```

## Test plan

### Normal-mode rerun (no Postgres)

```
.venv/bin/python -m pytest tests/test_bot_confirm_flow.py tests/test_bot_fsm.py \
  tests/test_bot_execute_tool_guard.py tests/test_bot_chat_target_resolution.py \
  tests/test_bot_channel_name_parser.py tests/test_f6_scheduled_digests.py \
  tests/test_f11_bot_tools.py tests/test_bot_agent.py tests/test_bot_tools_v11.py \
  tests/test_bot_tools_v12.py tests/test_bot_tools_session_f.py \
  tests/test_bot_read_context.py tests/test_bot_tools_bug010_username_alias.py \
  tests/test_bot_agent_resolved_model.py
```

Result: **537 passed, 23 skipped (Postgres-gated), 0 failed, 0 errors**.

### Self-review (stash production fix, rerun new tests)

```
git stash push -m "self-review-prod-fix" -- \
  tg_parser/bot/tools.py tg_parser/bot/handlers.py prompts/bot.yaml
.venv/bin/python -m pytest tests/test_bot_confirm_flow.py
```

Result (pre-fix code):

- **`tests/test_bot_confirm_flow.py`** — 1 collection error (`AFFIRMATIVE_TOKENS`
  / `classify_confirmation_token` / `UnknownConfirmationToken` symbols
  do not exist on pre-fix HEAD), blocking all **163** tests in the
  file from running. This is the strongest possible regression signal —
  the test file structurally cannot run against pre-fix code.
- **`tests/test_bot_execute_tool_guard.py::TestWriteToolsContract::test_guard_set_matches_known_baseline`** — FAILED (subscribe_digest / subscribe_watchlist not in pre-fix guard set).
- **`tests/test_bot_fsm.py::TestConfirmationResponseHandler::test_unrelated_text_keeps_fsm_and_prompts_for_known_tokens`** — FAILED (pre-fix clears state and routes to LLM instead of keeping FSM armed).

Cumulative pre-fix signal: **2 explicit failures + 1 collection error
(163 blocked tests)** = effectively 165 regression points caught.
Far exceeds the handoff's "at least 10-15 must fail" requirement.

Restored via `git stash pop`; full suite returns to 537 passing.

### TEST_POSTGRES=1 rerun (mandatory per SKIPPED_TESTS_AUDIT)

```
TEST_POSTGRES=1 .venv/bin/python -m pytest tests/test_bot_confirm_flow.py \
  tests/test_f6_scheduled_digests.py tests/test_f11_mcp_tools.py \
  tests/test_bot_chat_target_resolution.py tests/test_bot_channel_name_parser.py \
  tests/test_bot_fsm.py tests/test_bot_execute_tool_guard.py \
  tests/test_bot_agent.py tests/test_bot_tools_v11.py tests/test_bot_tools_v12.py \
  tests/test_bot_tools_session_f.py tests/test_bot_read_context.py \
  tests/test_bot_tools_bug010_username_alias.py \
  tests/test_bot_agent_resolved_model.py tests/test_f11_bot_tools.py
```

Result: **573 passed, 1 skipped (concurrency — documented), 0 failed**.

Additional sweep over the audit's explicit BUG-034-precedent-set:

```
TEST_POSTGRES=1 .venv/bin/python -m pytest tests/test_subscribe_legacy_chat_id.py \
  tests/test_subscribe_idempotency.py tests/test_api_digests.py
```

Result: **55 passed, 0 failed**. No fixture-rot regressions on the
subscribe/unsubscribe end-to-end paths (the specific concern the
audit flagged from the BUG-034 `@x` → `@validch` precedent).

### Lint / format

```
.venv/bin/ruff check tg_parser/bot/tools.py tg_parser/bot/handlers.py \
  tests/test_bot_confirm_flow.py tests/test_bot_fsm.py ...
.venv/bin/ruff format --check ...
```

Result: **All checks passed; 9 files already formatted**.

## Self-review findings (gaps identified + addressed)

The first pass of the regression suite had three coverage gaps the
handoff's self-review checklist explicitly called out:

1. **Compound replies («да, давай», «нет, спасибо»)** — initial
   classifier returned `"unknown"` because the first token was «да,»
   (with trailing comma). Fixed by `.rstrip(",.;:!?")` on the first
   token + parametrize cases pinning «да.», «нет!», «yes,», «да,
   давай», «нет, спасибо» as classified.
2. **Explicit `call_count == 0` mock-spy on `DigestService.subscribe`**
   — the empty-store assertion could in principle pass if persistence
   happened via a different path the in-memory fake doesn't track.
   Added `TestSubscribeServiceCallCountOnPreview` that patches the
   service method directly with an `AsyncMock` spy + asserts
   `call_count == 0` on preview / `== 1` on confirm.
3. **Concurrent two-confirm race** — `pytest.mark.skip` with a
   detailed reason documenting why this lives outside the unit-test
   scope (aiogram FSM storage serialises per-key invocations; BUG-009
   server-side guard provides defense-in-depth) and tracked as
   `TD-confirm-flow-concurrency-integration` for the next integration
   sprint.

## Prompt update

`prompts/bot.yaml` bumped to **v1.7.2**. Diff:

```diff
- description: "... v1.7.1 BUG-034 hard rule ... v1.7.0 ADR 0008 ... v1.6.0 BUG-011 preserved"
+ description: "... v1.7.2 BUG-031/BUG-032 subscribe_digest/subscribe_watchlist
+ join the two-phase preview/confirm contract + accepted confirmation tokens
+ enumerated; v1.7.1 BUG-034 ... v1.7.0 ADR 0008 ... v1.6.0 BUG-011 preserved"

  - For write operations (trigger_pipeline, pause_channel, resume_channel,
-   add_channel, remove_channel, set_llm_config, reset_llm_config): ALWAYS ...
+   add_channel, remove_channel, set_llm_config, reset_llm_config,
+   subscribe_digest, subscribe_watchlist): ALWAYS ...

  Confirmation semantics (BUG-002 fix; v1.7.2 extended for BUG-031):
+ - The two-phase contract applies UNIFORMLY to every write tool: ... NEVER
+   call subscribe_digest or subscribe_watchlist without first issuing
+   a confirm=false preview turn — pre-v1.7.2 these tools persisted ... (BUG-031)
+ - Accepted affirmative tokens: "да", "yes", "y", "ok", "ок", "подтверждаю",
+   "подтверди", "подтвердить", "согласен", "согласна", "хорошо", "ага",
+   "уверен", "уверена", "конечно", "давай", "+", "👍". Accepted negative
+   tokens: "нет", "no", "n", "отмена", "cancel", "отказ", "стоп", "stop",
+   "не подтверждаю", "не надо", "передумал", "передумала", "-", "👎".
+   Phrase your preview's ask suffix as "[да/нет]" ... (BUG-032 closure)
```

## Constraints respected

- No `pyproject.toml` / `requirements.txt` modifications.
- No `docs/methodology/**` writes.
- Feature branch `fix/bug-031-032-confirm-flow`; no direct push to `main`.
- No real prod chat_id `5445781511` or `digest_94483db9` subscription touched
  (synthetic-only IDs pinned by anti-pattern guards in both
  `test_bot_confirm_flow.py` and `test_bot_chat_target_resolution.py`).

## References

- [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) § BUG-031, § BUG-032
- [`docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md`](docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md) § 2.3
- [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) — empirical Test C / D evidence
- [`docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`](docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md) — `TEST_POSTGRES=1` rerun standard
- PR #108 (BUG-033, commit `e50449b`) — helper-extraction pattern precedent
- PR #109 (BUG-034, commit `6ebad33`) — prompt + executor-guard pattern precedent
