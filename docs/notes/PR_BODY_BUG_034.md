## Summary

Fixes [BUG-034](docs/notes/BUG_LOG.md) (Medium — bot channel-name parser
typo handling). In Test D (2026-05-24 ~21:11 UTC, see
`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`) the operator
typed «Подпиши этот чат на ежечасный дайджест канала
**pro fendocrinologist**» (with an embedded space — a typo for
`profendocrinologist`). The Gemini agent emitted
`subscribe_digest(channel_ids=["pro_fendocrinologist"], …)` — the
space was silently re-coerced to an underscore, producing a
structurally-invalid Telegram username that did NOT match the real
source `profendocrinologist`. The resulting subscription
(`0a00768d-…`) was undeliverable.

## Root cause (post-investigation; replaces handoff hypothesis)

The handoff's "Hypothesis B" (a Python-side `.replace(" ", "_")` in
`tg_parser/bot/`) was wrong — `rg "replace\(['\"] ['\"], ['\"]_['\"]\)"`
across the whole `tg_parser/` tree returned no matches. The bug class
is split across two layers:

* **Hypothesis A confirmed (LLM-side)** — the Gemini agent itself
  emitted the underscored form, almost certainly because the v1.7.0
  `prompts/bot.yaml` did not contain a hard rule against silent
  whitespace coercion. The model picked an underscore as a reasonable
  guess for "this looks like a Telegram username with an extra space".
* **Structural gap (executor-side)** — `_exec_subscribe_digest` /
  `_exec_subscribe_watchlist` / `_exec_add_channel` accepted whatever
  the LLM emitted after only `normalize_channel_id` ran. That helper
  is deliberately permissive (strips `@` / quotes / outer whitespace
  only — never collapses internal whitespace, never enforces the
  Telegram username regex). The pre-fix shape would have *also*
  accepted `"pro fendocrinologist"` verbatim if the LLM had passed
  it through unchanged — the resulting subscription would have been
  equally undeliverable. The executor was a structural enabler for
  any LLM-side channel-name typo, not just the underscore-coercion
  one observed in Test D.

The fix targets both layers (code-driven defense-in-depth + prompt
hardening per the handoff's "Recommended A + B").

## Layer A — executor pre-validation (`tg_parser/utils/channel_id.py`)

New helper `validate_channel_username(value) -> (value, error)`
returns either the canonical normalized form OR a typed-error dict
shaped for direct executor return:

```python
{
  "error": "<Russian-language human message>",
  "error_class": "InvalidChannelUsername",
  "raw_input": "<echo of what we received>",
  "suggestion": "<whitespace-stripped candidate, when applicable>",
}
```

Rejection cases (covered by the new test file):

1. **Embedded whitespace** — checked BEFORE
   `normalize_channel_id` runs so the raw form is preserved for
   the clarification suggestion. Covers space, tab, newline, and
   mixed-whitespace runs. Surfaces a Russian-language hint:
   «Канал «pro fendocrinologist» содержит пробелы — Telegram
   usernames не могут содержать пробелы. Возможно, вы имели в виду
   «profendocrinologist»?»
2. **Empty / `None` input** — typed `InvalidChannelUsername` error
   instead of the legacy free-form `"channel_id is required"` so
   callers can route on `error_class`.
3. **Non-numeric, non-username** — fails the Telegram regex
   `^[a-zA-Z][a-zA-Z0-9_]{4,31}$`. Catches invalid chars (`@` /
   `-` / `.` mid-token), too-short (< 5 chars), too-long (> 32
   chars), starts-with-digit, and non-ASCII (Cyrillic / Greek).

Numeric Telegram chat ids (`12345`, `-1001234567890`) bypass the
username regex via a dedicated `_is_numeric_chat_id` branch so
admin tooling and private-channel `add_channel` flows keep working.

The three write executors that accept channel ids from the LLM
were updated to use the new helper:

* `_exec_subscribe_digest` (the BUG-034 primary surface — observed
  in Test D);
* `_exec_subscribe_watchlist` (symmetric — same `channel_ids` list
  shape; the helper closes the same hallucination vector on this
  surface in case the LLM ever picks it for the same typo class);
* `_exec_add_channel` (single `channel_id` write surface — same
  hallucination class would create a row no ingestion worker can
  ever resolve).

Read-only surfaces (`list_topics`, `search_knowledge_base`, …)
keep the permissive `normalize_channel_id` contract — they have
their own "channel not found" / `suggestion` hint pathway
(BUG-007, v1.5.0) which handles read-side typo recovery
non-disruptively.

### Before / after (executor call site)

Before — `_exec_subscribe_digest` (mirrored in `_exec_subscribe_watchlist`):

```python
raw_channels = args.get("channel_ids") or []
if not isinstance(raw_channels, list) or not raw_channels:
    return {"error": "channel_ids must be a non-empty list"}
channel_ids = [n for n in (normalize_channel_id(c) for c in raw_channels) if n]
if not channel_ids:
    return {"error": "channel_ids must contain at least one channel"}
```

After:

```python
raw_channels = args.get("channel_ids") or []
if not isinstance(raw_channels, list) or not raw_channels:
    return {"error": "channel_ids must be a non-empty list"}
channel_ids: list[str] = []
for raw in raw_channels:
    validated, error = validate_channel_username(raw)
    if error is not None:
        return error
    assert validated is not None  # narrowing: helper post-condition
    channel_ids.append(validated)
if not channel_ids:
    return {"error": "channel_ids must contain at least one channel"}
```

`_exec_add_channel` updated symmetrically (single-value version).

## Layer B — prompt hardening (`prompts/bot.yaml` v1.7.0 → v1.7.1)

Added a HARD RULE in the existing "Channel ID normalization"
section forbidding silent space-to-underscore coercion. The full
rule (excerpted):

```yaml
- HARD RULE (BUG-034 mitigation): NEVER replace internal whitespace
  with an underscore when handling a channel name. Telegram
  usernames cannot contain whitespace, so the user's input must be
  EITHER stripped of all whitespace into a single token (e.g.
  "pro fendocrinologist" → "profendocrinologist") OR rejected with
  a clarification question — NEVER silently coerced to
  "pro_fendocrinologist". If you are not sure which underlying
  canonical username the user meant, ASK rather than guess. Since
  v1.7.1 a server-side guard structurally rejects whitespace-
  bearing usernames with error_class="InvalidChannelUsername" and
  surfaces a Russian-language clarification suggestion containing
  the whitespace-stripped candidate — relay that suggestion
  verbatim to the user and ask them to confirm or correct.
```

Prompt version bumped `1.7.0` → `1.7.1`; `metadata.description`
updated to mention the new rule. Reload via
`reload_prompts` (no restart needed).

Layer C (MCP server-side mirror in `mcp_server.py`) is the
defense-in-depth follow-up the BUG_LOG entry mentions; it is
intentionally deferred — Layer A in the executor closes the
bot-surface gap (the only surface the empirical BUG-034 evidence
observed), and Layer C would benefit from being bundled with a
broader MCP write-surface hardening sweep.

## Scope decision

Per handoff "one PR per BUG" + "primary defence is regex +
existence check": this PR applies Layer A to the three bot-write
executors that take LLM-derived channel ids, plus Layer B in
`prompts/bot.yaml`. The optional `get_source_by_username` existence
check (handoff Layer A optional addendum) is intentionally NOT
included — it would couple subscribe/add-channel write paths to
the source-resolution read path in a way that's a separate
architectural decision (does an unknown-channel subscribe become
"reject with available_channel_ids hint" symmetric with BUG-007 /
BUG-012?). The regex + whitespace check is sufficient defence for
the BUG-034 reproduction case; existence-check enhancement can
follow up.

The MCP `add_channel` / `subscribe_digest` server-side handlers
(non-bot surface — direct MCP-client callers) keep their pre-fix
permissive shape. The empirical bug fired only on the bot surface;
MCP callers are pure-programmatic (not LLM-driven) and should not
be subject to the same validation gate without a separate signal.
The BUG_LOG entry tracks Layer C for follow-up.

## Test plan

New regression file `tests/test_bot_channel_name_parser.py` —
**65 tests** total:

* **Helper unit tests (37 tests)** — `validate_channel_username`
  direct contract (skipped cleanly on pre-fix via defensive
  import):
  * Whitespace handling (8 tests) — single space, double space,
    tab, mixed `pro \t fendocrinologist`, newline, leading-only,
    trailing-only, both-sides.
  * Regex enforcement (17 tests) — exact match, `@` prefix,
    quoted form, special chars (`@` mid / `-` / `.`), length
    boundaries (4 / 5 / 32 / 33 chars), starts-with-digit, "pro"
    (handoff explicit case), Cyrillic, Greek, mixed-case
    preserved, underscore-only username accepted, underscore-after-
    letter accepted.
  * Numeric chat ids (3 tests) — positive, `-100…` supergroup,
    `int` coerced via `str`.
  * Empty / `None` (4 tests) — `None`, empty string, only
    whitespace, only `@`.
  * Idempotency (6 parametrized) — chained validate is a no-op.
  * Anti-regression (2 tests) — typo never produces the
    underscored form; underscored form passes on its own (the
    bug is in the *coercion*, not the underscored form).

* **`_exec_subscribe_digest` end-to-end (11 tests)** — typo (single
  / double space / tab / special char) rejected with `suggestion`,
  exact match persists, outer whitespace stripped, first-invalid /
  second-invalid both fail-fast (no partial persist), `None` /
  empty string entries return typed `InvalidChannelUsername`, `@`
  prefix typo suggests bare username (no leading `@` leak).
* **`_exec_subscribe_watchlist` end-to-end (3 tests)** — symmetric
  coverage on the watchlist surface.
* **`_exec_add_channel` end-to-end (7 tests)** — typo rejected in
  preview AND confirm phase, exact match preview succeeds, special
  chars rejected, missing channel_id typed-rejected, too-short
  rejected, numeric `-100…` id accepted.
* **Anti-regression — persisted forms (3 tests)** — no code path
  may persist `"pro_fendocrinologist"` from a space input across
  any of the three executors.
* **Synthetic-fixture guard (1 test)** — `R-1` / `R-2` /
  real-prod-chat-id / Test-D-group-id never leak into this module
  (per AGENTS.md + handoff Key reference paths). All forbidden
  tokens assembled at runtime so the guard does not trip on its
  own self-referencing string literals.

### Self-review-and-rerun loop

* [x] Initial green run on the new file (62/62 passed).
* [x] **Stashed the production fix** (`git stash push -- tg_parser/bot/tools.py tg_parser/utils/channel_id.py prompts/bot.yaml`)
      and reran on pre-fix `main@e50449b` shape: **13 executor-
      level tests fail** (6 `subscribe_digest`, 2
      `subscribe_watchlist`, 5 `add_channel`) — well above the
      operator's "≥5-7 must fail" threshold; proves the
      regressions are not no-ops. Helper unit tests (40) skip
      cleanly via the defensive import.
* [x] Self-review identified four additions:
  * `test_none_entry_in_list_rejected_with_typed_error` — pre-fix
    silently filtered `None` to the free-form
    `"channel_ids must contain at least one channel"` error;
    post-fix returns typed `InvalidChannelUsername`. Behavior
    change is intentional (caller routability).
  * `test_empty_string_entry_in_list_rejected_with_typed_error` —
    symmetric to `None`.
  * `test_at_prefix_typo_still_rejected` — pin that `@`-prefix
    typo gets the BARE username in the `suggestion` field, not
    `"@profendocrinologist"`. Without this fix the bot would
    leak the leading `@` to the user's clarification UX.
  * `test_mixed_whitespace_rejected_with_clarification` —
    operator-recommended combined-whitespace case.
* [x] Restored fix and reran: 65/65 passed.
* [x] **Second stash-and-rerun** — 16 executor-level fail, 9 pass,
      40 skipped (the 4 new tests joined the pre-fix-failing set).
* [x] Pre-existing test data fixups (test-side only, no
      production-code change):
  * `tests/test_bot_tools_v12.py::TestExecAddChannel::test_confirm_updates_existing`
    used `channel_id="ch"` (2 chars). Bumped to `"ch_alt"` (6
    chars) so the upsert path runs.
  * `tests/test_bot_tools_v12.py::TestExecAddChannelBlockedPlaceholder::test_env_var_extends_blocked_list`
    used `{foo, bar, baz}` (3 chars each). Bumped to
    `{foobar, barred, bazinga}` so the blocked-list branch runs.
  * `tests/test_f11_bot_tools.py::TestSubscribeWatchlistExec::test_rejects_invalid_threshold`
    used `channel_ids=["@x"]` (1 char). Bumped to `["@validch"]`
    so the threshold validation branch runs.
  All three are accidental test-data choices from before the
  Telegram spec was enforced; the test semantics are unchanged.
* [x] Full affected suite rerun:
  * `tests/test_bot_channel_name_parser.py tests/test_bot_*.py
    tests/test_f11_bot_tools.py tests/test_f4b_*.py
    tests/test_utils_channel_id.py` → **414 passed, 92 skipped**
    (skipped are Postgres-gated).
  * `tests/test_subscribe_idempotency.py tests/test_subscribe_legacy_chat_id.py
    tests/test_watchlist_service.py tests/test_watchlist_workspace_id.py
    tests/test_digest_channel_publish.py tests/test_watchlist_metrics.py
    tests/test_watchlist_score.py` → **164 passed**.
  * `tests/test_f11_watchlist_repo.py tests/test_f11_cli_watchlist.py
    tests/test_scheduler_digest_prompt_loader.py` → **13 passed,
    16 skipped**.
  * `tests/test_mcp_server.py` → **38 passed**.
  * `tests/test_channels_routes.py` → **4 passed**.
  * Prompt-validation suite: `tests/test_prompt_loader.py
    tests/test_rag_prompt_config.py tests/test_topicization_prompts.py
    tests/test_scheduler_digest_prompt_loader.py` → **153
    passed** (confirms `prompts/bot.yaml` v1.7.1 still loads).
  * **Grand total: 0 regressions.**
* [x] `ruff check` + `ruff format` clean on all changed files
      (`tg_parser/utils/channel_id.py`, `tg_parser/bot/tools.py`,
      `tests/test_bot_channel_name_parser.py`,
      `tests/test_bot_tools_v12.py`, `tests/test_f11_bot_tools.py`).

### Coverage gap analysis (operator-mandated self-review checklist)

* **Boundary regex** — 4 / 5 / 32 / 33 char tests all present.
* **Unicode edge cases** — Cyrillic (`канал_тест`) and Greek
  (`αβγδε`) explicitly rejected.
* **Case sensitivity** — `ProFendocrinologist` (mixed case)
  passes through unchanged; `normalize_channel_id` contract
  (BUG-003 § H3) preserved.
* **Multiple consecutive whitespace types** — `pro \t fendocrinologist`
  rejected, suggestion collapses to single token.
* **No false-positives in suite** — explicitly avoided "weak"
  tests like `assert result is not None` that would pass against
  the pre-fix code; every executor-level test asserts the BUG-034
  fingerprint (typed error class + no persisted row).

## References

* [`docs/notes/BUG_LOG.md` § BUG-034](docs/notes/BUG_LOG.md)
* [`docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md` § 2.2](docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md)
* [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § BUG-034 row](docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)
* PR #108 / commit `e50449b` (BUG-033 — companion Test D fix,
  style precedent for this PR shape and self-review loop format)

## Operator action required

* **DO NOT MERGE** without sign-off (per `AGENTS.md` + handoff
  anti-patterns).
* Optional follow-ups (out of scope for this PR):
  * Layer C (BUG_LOG mention) — mirror `validate_channel_username`
    in MCP `add_channel` / `subscribe_digest` server-side handlers
    for defense-in-depth on the direct MCP-client surface.
  * Optional Layer A addendum — `get_source_by_username` existence
    check in subscribe executors (would convert "unknown channel
    subscribed → silent" into "explicit reject with `available_channel_ids`
    hint", symmetric with BUG-007 read-side recovery).
