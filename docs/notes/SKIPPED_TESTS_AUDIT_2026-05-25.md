# Skipped-tests audit — Wave 1, Step 4 follow-up

**Date:** 2026-05-25
**Scope:** PRs #108 (BUG-033, merged into `main` as `e50449b`) and #109 (BUG-034, branch `fix/bug-034-channel-name-parser@e925437`).
**Driver:** Operator concern that Postgres-gated skips during PR verification could hide regressions in the fixed code paths.
**Status:** Investigation complete. **One real coverage gap discovered** — see verdict.

> **Update 2026-06-08:** канонические команды прогона зафиксированы в
> [`tests/README.md`](../../tests/README.md) § «Режимы прогона». Максимальный
> локальный прогон: `TEST_POSTGRES=1 TEST_TESTCONTAINERS=1 .venv/bin/python -m pytest -q`
> → ~3142 passed, 1 skipped (confirm-flow TD), 2 deselected.

## Top-line verdict

**Real coverage gap discovered for BUG-034 (PR #109). Pre-existing test
`tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_validates_cron_expression`
fails on the BUG-034 branch because the new `validate_channel_username`
helper rejects the test's `channel_ids=["@x"]` input before the cron
validator can run. The test was silently skipped during PR-#109
verification (Postgres-gated, `@pg_only`).**

- **BUG-033 (PR #108, merged):** No coverage gap. With infrastructure up, all
  168 Postgres-gated tests in the BUG-033 surface pass.
- **BUG-034 (PR #109, open):** 1 regression. The fix itself is correct
  (it rightly rejects `"@x"` as too short); the test needs to be updated
  to use a valid channel name (e.g. `"@validch"`) so the cron-validation
  branch is exercised.

## Recommendation

**Hold PR #109 for a tiny follow-up commit** that updates the test fixture
in `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_validates_cron_expression`
from `channel_ids=["@x"]` to `channel_ids=["@validch"]` (or similar 5+ char
ASCII), then re-verify with `TEST_POSTGRES=1`.

No other code/test changes are required. The fix's runtime behavior is
correct — only the test scaffolding lags.

---

## Phase A — Enumeration (tests/ baseline)

Pytest invocation (BUG-034 branch, `.venv/bin/pytest`):

| Run | Command | Total | Passed | Failed | Skipped | Deselected |
|---|---|---|---|---|---|---|
| Focus suites, **no `TEST_POSTGRES`** | `tests/test_bot_*.py tests/test_f4b_*.py tests/test_f6_*.py tests/test_f11_*.py tests/test_subscribe_*.py tests/test_bot_channel_name_parser.py tests/test_bot_chat_target_resolution.py tests/test_prompt_loader.py tests/test_api_*.py` | 726 | 542 | 0 | **184** | 0 |
| Full `tests/`, **no `TEST_POSTGRES`** | `tests/` | 2672 | 2341 | 0 | **329** | 2 |
| Full `tests/`, **with `TEST_POSTGRES=1`** (BUG-034) | `tests/` | 2672 | 2654 | **1** | 15 | 2 |
| Full `tests/`, **with `TEST_POSTGRES=1`** (`main`) | `tests/` | 2607 | 2590 | 0 | 15 | 2 |

The difference between BUG-034 and `main` totals (2672 vs 2607) is the 65
new tests in `tests/test_bot_channel_name_parser.py` that BUG-034 adds.

### Per-file skip breakdown (full `tests/`, baseline w/o `TEST_POSTGRES`)

| Tests skipped | Test file |
|---:|---|
| 27 | tests/test_api_watchlists.py |
| 26 | tests/test_api_digests.py |
| 25 | tests/test_f4_user_model.py |
| 24 | tests/test_f4b_scoping_read_tools.py |
| 22 | tests/test_f6_scheduled_digests.py |
| 16 | tests/test_f5c_resummarization_service.py |
| 16 | tests/test_f5a_phase3_dedup.py |
| 16 | tests/test_f11_watchlist_repo.py |
| 15 | tests/test_f4b_workspace_repo.py |
| 14 | tests/test_f4_embedding_channel_ids.py |
| 13 | tests/test_f5a_hybrid_search.py |
| 12 | tests/test_f5c_topic_card_repo.py |
| 12 | tests/test_f4b_mcp_tools.py |
| 9  | tests/test_postgres_integration.py |
| 9  | tests/test_f4b_backward_compat.py |
| 8  | tests/test_idempotency_key_middleware.py |
| 7  | tests/test_postgres_concurrency.py |
| 6  | tests/test_f4b_workspace_isolation.py |
| 6  | tests/test_f4b_schema.py |
| 6  | tests/test_f4b_metrics.py |
| 6  | tests/test_alembic_subscription_target_migration.py |
| 4  | tests/test_ingestion_state_repo_username_alias.py |
| 3  | tests/test_idempotency_cleanup_job.py |
| 3  | tests/test_f5c_counter_increment.py |
| 3  | tests/test_f4_auth_resolution.py |
| 2  | tests/test_migrations_runtime_upgrade.py |
| 2  | tests/test_f4b_workspace_service.py |
| 1  | tests/test_ingestion_state_repo_soft_delete.py |
| 1  | tests/test_f4b_golden_path.py |
| 1  | tests/test_f2_parse_only_export.py |
| 1  | tests/test_api_pipeline_trigger.py |
| **329** | **total** |

## Phase B — Classification of skip reasons

All 329 skips fall into exactly three buckets — there are **no
unknown / suspicious skips** in the suite.

| Bucket | Gate | Count | How to satisfy locally | Risk if left skipped |
|---|---|---:|---|---|
| **Postgres** | `TEST_POSTGRES=1` env var; conftest then runs `alembic upgrade head` against `tg_parser_test` on `localhost:5432`. | **303** (286 + 16 + 1, three slightly different reason strings) | Docker container `tg_parser_postgres` (pgvector/pgvector:pg17) already running; `tg_parser_test` DB pre-exists; conftest handles the rest. | High — hides regressions in any code path that touches the DB, including bot tools, API endpoints, MCP server, schedulers, repos, and migrations. |
| **Testcontainers** | `TEST_TESTCONTAINERS=1` + `testcontainers[postgres]>=4.8` installed + reachable Docker daemon. | **13** | Already satisfied (Docker is running). `pip install testcontainers[postgres]` then export `TEST_TESTCONTAINERS=1`. Spins up an ephemeral pgvector container per test class. | Low for BUG-033/BUG-034 (these tests cover migration smoke / username-alias backfill on a fresh schema — not the bot tool path). |
| **Integration marker** | `pyproject.toml` `addopts = "-m 'not integration'"` auto-deselects `@pytest.mark.integration`. | **2** (deselected, not skipped) | Run with `-m integration`; tests in this class talk to OpenAI etc. | None for BUG-033/BUG-034 (the only marked tests are `test_agents.py::test_real_openai_*` which hit live OpenAI). |

**Notably absent:** no Redis, OS, or "bare `@pytest.mark.skip` with vague
reason" gates. No tests gated on Telegram session or other operator-only
credentials. The default-deselected `@pytest.mark.integration` tests are
2 in number and unrelated to BUG-033/BUG-034.

## Phase C — Infrastructure-up and rerun

### Infrastructure brought up

Already running in the workspace (verified at audit start):

- Container `tg_parser_postgres` — image `pgvector/pgvector:pg17`,
  healthy, exposing `127.0.0.1:5432`.
- `tg_parser` and `tg_parser_test` databases both exist; conftest auto-
  drops/recreates the `public` schema in `tg_parser_test` and runs
  alembic upgrade head × 3 branches (ingestion / raw / processing) on
  the first test of each session.
- Docker Compose: `docker-compose.yml` defines `postgres` service with
  user `tg_parser_user` / password `test_password` (from `.env`); MCP
  server (`tg_parser_mcp`) and API (`tg_parser`) containers also up.

No additional commands needed — `TEST_POSTGRES=1` was the only env
variable required.

### Before/after skip counts on BUG-034 branch

| | Baseline (no `TEST_POSTGRES`) | After `TEST_POSTGRES=1` | Delta |
|---|---:|---:|---:|
| Passed | 2341 | 2654 | **+313** |
| Failed | 0 | **1** | **+1** |
| Skipped | 329 | 15 | **−314** |

The 15 remaining skips are entirely testcontainers-gated (migration
smoke / alembic subscription-target migration / soft-delete repo /
username-alias repo). None are in the BUG-033 / BUG-034 fix surface.

### Newly-running tests' pass/fail breakdown (Postgres-on rerun)

**168 Postgres-gated tests in the BUG-033/034 fix surface
(`test_f6_scheduled_digests` + `test_f11_mcp_tools` + `test_subscribe_*`
+ `test_api_digests` + `test_api_watchlists` + `test_api_pipeline_trigger`):**

- On `main@e50449b` (BUG-033 only): **168 passed, 0 failed**.
- On `fix/bug-034-channel-name-parser@e925437`: **167 passed, 1 failed**.

The single new failure on BUG-034 is documented below.

### New failure discovered

```
FAILED tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_validates_cron_expression
```

**Root cause:** The pre-existing test passes `channel_ids=["@x"]` and
asserts that an error message containing `"cron"` is returned. BUG-034
adds `validate_channel_username` (5-32 ASCII chars, alphanumeric +
underscore, must start with a letter) to `_exec_subscribe_digest` *before*
the cron validator. `"@x"` is 1 character, so the new validator rejects
it first, returning:

> «x» не является валидным Telegram username — требуется 5-32 ASCII-символа, начиная с буквы, далее буквы / цифры / подчёркивания.

…which contains no `"cron"` substring, breaking the assertion.

**Behavioural correctness:** the fix is doing the right thing — `"@x"`
is structurally invalid and would never have been deliverable. The test
predates the new validator and needs its fixture updated.

**Branch-by-branch confirmation:**

```text
TEST_POSTGRES=1 pytest tests/test_f6_scheduled_digests.py::\
TestBotDigestTools::test_subscribe_digest_validates_cron_expression
```

- on `main@e50449b`:    PASSED
- on `fix/bug-034-...`: FAILED (assertion on `"cron"` substring)

## Phase D — Coverage-gap analysis per fix

### BUG-033 (PR #108, merged)

Touched files: `tg_parser/bot/tools.py` (`_resolve_target_for_bot_subscribe`,
`_exec_subscribe_digest`, `_exec_subscribe_watchlist`).

Pg-gated tests that exercise these paths:

- `tests/test_f6_scheduled_digests.py::TestBotDigestTools::*` — 6 tests
  on `_exec_subscribe_digest`, all pass on `main`.
- `tests/test_f6_scheduled_digests.py::TestMCPDigestTools::*` — 5 tests
  on MCP `subscribe_digest` (not the bot tool, different code path), all
  pass on `main`.
- `tests/test_subscribe_legacy_chat_id.py` (NOT pg-gated — already ran
  in PR-verification). All pass.

**Verdict: no real coverage gap.** All BUG-033 paths exercise cleanly
once Postgres is up. BUG-033 PR-verification skipped these but the
underlying behavior is correct on both branches.

### BUG-034 (PR #109, open)

Touched files: `tg_parser/bot/tools.py` (validation injected in
`_exec_subscribe_digest`, `_exec_subscribe_watchlist`, `_exec_add_channel`),
`tg_parser/utils/channel_id.py` (new `validate_channel_username`),
`prompts/bot.yaml` (v1.7.0 → v1.7.1).

Pg-gated tests that exercise these paths and were silently skipped:

- `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_validates_cron_expression`
  — **FAILS** (the regression). Uses `channel_ids=["@x"]` which is now
  rejected by the new validator before cron is checked.
- `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_persists_and_registers`
  — passes (uses `"@durov"`, valid).
- `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_rejects_unauthorized_channel`
  — passes (uses `"@forbidden"`, valid 9-char ASCII).
- `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_list_digests_*`
  — pass (no channel-name input).
- `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_unsubscribe_digest_*`
  — pass (no channel-name input).

The MCP path (`tg_parser/mcp_server.py::subscribe_digest`) uses the
permissive `normalize_channel_id` and is *not* affected by BUG-034. The
two MCP tests using `"@x"` (`test_mcp_subscribe_digest_validates_cron`,
`test_rejects_threshold_outside_range` in `test_f11_mcp_tools.py`)
continue to pass.

The `test_f11_bot_tools.py::TestSubscribeWatchlistExec::test_rejects_invalid_threshold`
test was *already updated* by the BUG-034 author (the change is
documented with an inline `# BUG-034: bumped channel name from "@x"…`
comment) — that one is fine. The author simply missed the equivalent in
`test_f6_scheduled_digests.py` because that file's `TestBotDigestTools`
class is wrapped in `@pg_only` and never ran in the PR-verification
context.

**Verdict: 1 real coverage gap.** The `test_subscribe_digest_validates_cron_expression`
fix is a one-line test-fixture update (rename `"@x"` to e.g. `"@validch"`).
The runtime fix itself is correct.

## Phase E — Recommendations

### For BUG-034 PR #109 specifically

1. **Hold the merge** until the test fixture is updated. Recommended
   one-line change:

   ```python
   # tests/test_f6_scheduled_digests.py, line 985
   -        "channel_ids": ["@x"],
   +        "channel_ids": ["@validch"],
   ```

   (Mirroring the rename the author already made in
   `tests/test_f11_bot_tools.py::TestSubscribeWatchlistExec::test_rejects_invalid_threshold`
   — keep it consistent with the existing in-tree convention.)

2. After the fix, re-verify with:

   ```bash
   TEST_POSTGRES=1 .venv/bin/pytest \
       tests/test_f6_scheduled_digests.py::TestBotDigestTools \
       tests/test_f11_mcp_tools.py \
       tests/test_subscribe_legacy_chat_id.py \
       tests/test_subscribe_idempotency.py \
       tests/test_api_digests.py \
       tests/test_api_watchlists.py \
       tests/test_api_pipeline_trigger.py \
       -v --no-header -ra
   ```

   Expected: **168 passed, 0 failed**.

### Process-level recommendations

1. **Add a Postgres-gated stage to the PR-verification workflow.**
   Currently the documented PR verification command runs without
   `TEST_POSTGRES=1`, which silently masks **303 tests** across 31
   files. Containerized Postgres is already part of the dev workflow
   (`tg_parser_postgres` is running locally and in docker-compose), so
   the cost is one extra env var and a slightly longer run (~190 s vs
   ~135 s on this machine — well within tolerance).

   Concretely: when running PR verification for any bot/MCP/API/repo
   fix, run the targeted suite *both* with and without `TEST_POSTGRES=1`
   and report both numbers. The "Postgres-gated skips" line in the
   handoff should be replaced with "Postgres-gated reruns: N passed,
   M failed".

2. **Consider tagging the validator-touching test fixtures.**
   The `validate_channel_username` change is a cross-cutting tightening
   that will catch *any* test relying on the previously-permissive
   pre-`normalize_channel_id` behavior. Three test fixtures used `"@x"`
   as a "throwaway channel name":
   - `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_subscribe_digest_validates_cron_expression`
     (bot path → broke).
   - `tests/test_f11_mcp_tools.py::TestSubscribeWatchlistRejection::*` × 2
     (MCP path → safe today, but **fragile** if BUG-034 is ever extended
     to the MCP surface — which would be a sensible defense-in-depth
     change).
   - `tests/test_f11_bot_tools.py::TestSubscribeWatchlistExec::test_rejects_invalid_threshold`
     (already updated by the BUG-034 author).

   A grep convention (e.g. a `# REGRESSION_GATE: validate_channel_username`
   comment near every `channel_ids=["@x"]` literal) would make the audit
   trail explicit and let future authors find these sites without
   running the whole Pg-gated suite.

3. **No tests need to be moved off the Postgres gate.** All 303 Pg-gated
   tests genuinely require a live DB (alembic upgrade, repository
   ownership checks, ENUM round-trips, etc.). Mocking would be
   value-destroying. The right answer is "run the gate in CI", not
   "drop the gate".

4. **Suspicious skips: none.** Every skip in the suite has a clear
   reason string pointing at a documented env var. No bare
   `@pytest.mark.skip` or `xfail` instances.

5. **Testcontainers (13 skips) — leave as-is.** These tests cover
   migration smoke and ephemeral-DB repo behavior that's orthogonal to
   bot-fix work. Enabling them adds ~30 s per run and an extra Docker
   pull on first invocation. They're already run nightly per the
   existing CI matrix; no need to gate PRs on them.

## Run artifacts

All audit logs saved under `/tmp/skip_audit/`:

| File | Description |
|---|---|
| `01_bot_focus.log` | BUG-033/034 focus tests (no Pg). 95 passed. |
| `02_focus_no_pg.log` | Phase A focus suites (no Pg). 542 passed / 184 skipped. |
| `03_all_no_pg.log` | Full tests/ (no Pg, system-py, 4 collection errors). 2227/329. |
| `04_all_no_pg_full.log` | Full tests/ (no Pg, .venv). 2341 passed / 329 skipped. |
| `05_postgres_gated_rerun.log` | Pg-gated focus suites on BUG-034. 167 passed / 1 failed. |
| `06_all_with_pg.log` | Full tests/ with TEST_POSTGRES=1 on BUG-034. 2654 passed / 1 failed / 15 skipped. |
| `07_main_with_pg.log` | Pg-gated focus suites on main. 168 passed. |
| `08_main_all_with_pg.log` | Full tests/ with TEST_POSTGRES=1 on main. 2590 passed / 15 skipped. |

## Constraints honored

- No `.py` files were modified.
- No test files, `pyproject.toml`, or `requirements.txt` were modified.
- Git branch was switched to `main` and back to
  `fix/bug-034-channel-name-parser` once each (read-only); no commits
  or pushes were made on either branch.
- No external API calls were issued (OpenAI / Anthropic / Telegram /
  Gemini all left alone; only the local Postgres container and the
  local file system were touched).
- This document is the only new artifact landed in the repo; it is
  intentionally left untracked for operator review.
