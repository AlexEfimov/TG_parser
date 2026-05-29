## Summary

Fixes BUG-033 (CRITICAL bot regression). The Gemini agent has no factual access to `Message.chat.id`; the v1.7.0 system prompt instructs the LLM to "use the current Telegram chat_id from context", but the bot framework never injects the value into the prompt. The LLM hallucinated `chat_id=123` for an NL «подпиши этот чат на дайджест» intent issued from group `vps-watch-test-grp` (chat_id `-5279672667`) and the executors honoured the placeholder verbatim — the resulting digest subscription was undeliverable.

## Root cause (post-investigation; replaces handoff hypothesis)

`_exec_subscribe_digest` and `_exec_subscribe_watchlist` accepted whatever `target.chat_id` / legacy `chat_id` arg the LLM emitted, even though the bot framework already forwarded the real `Message.chat.id` to the executor as a kwarg. The handoff's "Hypothesis A" (fixture-seed leak in `agent.py`) was wrong — there is no `chat_id=123` literal in `tg_parser/bot/`. The placeholder was a pure LLM hallucination because the prompt asks for a value the model has no way to know. The structural fix is **at the executor**: when bot context is available it is the source of truth for `kind=chat` deliveries.

## Before / after (call site)

Before — duplicated in both executors (here showing `_exec_subscribe_digest`):

```python
target_arg = args.get("target")
legacy_chat_arg = args.get("chat_id")
try:
    if target_arg is not None:
        if legacy_chat_arg is not None:
            return {"error": "...conflict...", "error_class": "SubscriptionTargetConflict"}
        resolved_target = resolve_subscription_target(target=target_arg)
    elif legacy_chat_arg is not None:
        resolved_target = resolve_subscription_target(chat_id=int(legacy_chat_arg))
    elif chat_id is not None:
        resolved_target = resolve_subscription_target(chat_id=chat_id)
    else:
        return {"error": "chat_id or target is required..."}
except SubscriptionTargetConflictError as exc:
    return {"error": str(exc), "error_class": "SubscriptionTargetConflict"}
except ValueError as exc:
    return {"error": str(exc)}
```

After — both executors call a shared helper that treats bot-context `chat_id` as authoritative for `kind=chat`:

```python
resolved_target, error_payload = _resolve_target_for_bot_subscribe(args, chat_id)
if error_payload is not None:
    return error_payload
```

The helper:

- validates the `target` / legacy `chat_id` mutual-exclusivity (`SubscriptionTargetConflict`);
- for `kind=channel` passes the LLM target through unchanged (publish-to-channel is explicit user intent);
- for `kind=chat` (or no target at all) returns `TargetChat(chat_id=bot_context_chat_id)` whenever bot context is present, logging `subscribe_target_chat_id_overridden` if the LLM-supplied value diverged;
- falls back to the original LLM/legacy-arg resolution when no bot context is available (CLI / MCP shape preserved);
- returns a typed error when neither bot context nor a valid arg is present (callback-query / `update.message=None` edge case).

## Scope decision

The same hallucination class affects both `_exec_subscribe_digest` and `_exec_subscribe_watchlist` — identical resolution code shape, both registered in `_TOOLS_NEEDING_BOT_CONTEXT`. Per handoff guidance ("fix all instances in this PR if they're tightly coupled, e.g. shared resolver helper"), both surfaces use the new helper. No follow-up BUG entry is needed — the fix is structurally symmetric across the two executors.

## Test plan

New regression file `tests/test_bot_chat_target_resolution.py` (30 tests):

- **Helper unit (18 tests)** — `_resolve_target_for_bot_subscribe` direct contract: DM / group / supergroup contexts, group placeholder override, DM placeholder override, legacy `chat_id` arg override (int + string), warning-on-divergence + no-warning-on-match, channel target pass-through (`@username` and `-100…`), conflict typed error, no-bot-context typed error, no-bot-context arg pass-through, malformed-target with/without context.
- **`subscribe_digest` end-to-end (7 tests)** — group placeholder NEVER persisted, DM context persisted, DM placeholder override persisted, legacy `chat_id` placeholder override persisted, channel target unchanged, missing-message typed error, conflict typed error.
- **`subscribe_watchlist` end-to-end (4 tests)** — symmetric coverage.
- **Anti-pattern guard (1 test)** — synthetic chat IDs only; `S-2` (operator's prod chat) cannot leak into prod code or test fixtures.

Self-review-and-rerun loop:

- [x] Initial green run on the new file (30/30 passed).
- [x] Stashed the production fix (`git stash push -- tg_parser/bot/tools.py`) and reran on pre-fix `main@a06f428` shape: **5 executor-level tests fail** (`test_group_context_persists_real_chat_id_not_placeholder` for both digest and watchlist, `test_dm_context_overrides_llm_placeholder_in_persisted_row`, `test_legacy_chat_id_arg_overridden_in_persisted_row` for both digest and watchlist) with `assert 123 == -100500002`-shape failures — proves the regressions are not no-ops. Helper unit tests skip cleanly via a defensive import.
- [x] Self-review identified two coverage gaps after the first green run (DM-with-placeholder at executor level for digest; legacy-chat-id-arg at executor level for watchlist); both added and confirmed to fail on pre-fix.
- [x] Restored fix and reran the full affected suite: `tests/test_bot_chat_target_resolution.py tests/test_bot_*.py tests/test_f11_bot_tools.py tests/test_subscribe_idempotency.py tests/test_f4b_deferred_surface_guard.py` → **290 passed**, 0 regressions.
- [x] `tests/test_f6_scheduled_digests.py tests/test_f11_mcp_tools.py` → 50 passed, 48 skipped (Postgres-gated).
- [x] `tests/test_api_digests.py::TestAuthGates::test_create_digest_invalid_api_key_returns_403` fails locally — pre-existing infra flake (Postgres connection refused), confirmed identical failure on pre-fix HEAD; not introduced by this PR.
- [x] `ruff check` + `ruff format` clean on changed files.

## References

- [`docs/notes/BUG_LOG.md` § BUG-033](docs/notes/BUG_LOG.md)
- [`docs/adr/0008-subscription-target-model.md` § Migration path Wave 1 step 4](docs/adr/0008-subscription-target-model.md)
- Watch closure commit `209637f` (empirical evidence trail — 2026-05-25T10:50:10Z)

## Operator action required

- **DO NOT MERGE** without sign-off (per `AGENTS.md` + handoff anti-patterns).
- Prompt update (optional, follow-up): `prompts/bot.yaml` v1.7.x could explicitly tell the LLM "for `kind=chat` the bot framework injects the chat_id automatically; do not include `chat_id` in `target`". The structural fix is now sufficient regardless, but a prompt update would silence the new `subscribe_target_chat_id_overridden` warning in normal traffic.
