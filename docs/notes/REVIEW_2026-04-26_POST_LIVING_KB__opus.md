# Code & Docs Review — Post-Living-KB-Contract Audit

**Reviewer:** opus
**Date:** 2026-04-26
**HEAD (review baseline):** `eb9756a` (chore(F5C): add 24h watch helper + post-watch report template)
**HEAD (at deliverable write):** `4008f36` (gpt55 deliverable was committed mid-review by the parallel reviewer; see § 6)
**Started:** 2026-04-26T11:30Z (UTC)
**Finished:** 2026-04-26T12:10Z (UTC)
**Mode:** strict read-only audit, ensemble side A

---

## 1. Executive summary

**Verdict: 🟡 YELLOW** — Living-KB contract is closed in code (D.1 + F11 + F5-C all delivered, prod healthy, all migrations linear, all expected tables/indexes present), but the audit surfaces **1 critical observability gap (F11 watchlist has zero Prometheus metrics)**, **3 major LLM-config / prompt-loader bugs that ship today** (resummarize stage invisible in `get_llm_config`, undeclared anthropic-cap settings, missing default prompts for `digest`/`resummarize`), and **a doc-suite that has not been closed for the contract** (no "CLOSED 2026-04-26" marker in ROADMAP_KARPATHY, no issue #15 links in FUTURE_FEATURES, ~105 still-active prompts in `docs/notes/`). Recommendation: dedicate the next sprint to a **debt-fix / housekeeping sprint** (docs closure + observability hardening) before opening the next Karpathy wave. Production watch needs ≥24 h before any verdict — only one cron tick observed.

---

## 2. Code findings

### CODE-001 — F11 watchlist has no Prometheus metrics

- severity: **major**
- category: **observability**
- confidence: **high**
- Where: `tg_parser/api/metrics.py` (entire file), `tg_parser/services/watchlist_service.py:21`, `tg_parser/storage/models.py` watch-interest hook sites
- Zone: 6.6
- Observation: `tg_parser/api/metrics.py` defines metrics for ingestion, processing, scheduler, anthropic-billing and F5-C resummarize, but contains **zero `tg_parser_watchlist_*` / `tg_watchlist_*` counters or histograms**. Yet F11 ships a full keyword + semantic matcher and a Telegram push pipeline. There is a TODO-style mention in `watchlist_service.py:21` indicating metrics were planned, but they were never wired.
- Why it matters: F11 is the user-visible alert engine of the Living-KB contract; without `matches_total{result=delivered|filtered_keywords|filtered_threshold|blocked|error}` and a `score` histogram, operators cannot answer (a) "is the matcher firing at all?", (b) "are users being silently filtered out by exclude_keywords?", (c) "did the bot get blocked and we auto-deactivated the interest?". Today this is observable only via SQL on `watch_matches` — invisible to Prometheus/Grafana and dashboards.
- Suggested action: add `tg_watchlist_match_total{result}`, `tg_watchlist_score` histogram, `tg_watchlist_delivery_total{outcome}` (sent/blocked/error), `tg_watchlist_active_interests` gauge, and increment them in `WatchlistService.run_for_documents` and the bot push helper. Mirror the F5-C metric layout in `metrics.py`.

### CODE-002 — `LLMConfigManager.get_all()` silently drops the `resummarize` stage

- severity: **major**
- category: **observability** / dead-code
- confidence: **high**
- Where: `tg_parser/config/settings.py:976-981`
- Zone: 6.2 / 6.6
- Observation: `LLM_SCOPES = {"global", "processing", "topicization", "rag", "digest", "resummarize"}` is defined at module top, and `set_llm_config(scope="resummarize", …)` is accepted by the manager. But `get_all()` returns `stages = {processing, topicization, rag, digest}` — the `resummarize` stage is **omitted from the response payload**. The MCP/REST `get_llm_config` tool therefore cannot show the F5-C runtime configuration even after the user has overridden it.
- Why it matters: This is a dead-letter override — set works, get does not. Any operator inspecting "what model is the resummarizer using right now" gets a misleading answer (no row at all). Combined with CODE-003, the resummarize stage is effectively unobservable through the supported API.
- Suggested action: add `"resummarize": _stage_config("resummarize")` to the `stages` dict (one line). Add a regression test in `tests/test_llm_config_manager.py` that asserts every member of `LLM_SCOPES \ {"global"}` appears in `get_all()["stages"]`.

### CODE-003 — `set_llm_config` MCP docstring omits `resummarize` scope

- severity: **minor**
- category: **observability** (docs-as-code)
- confidence: **high**
- Where: `tg_parser/mcp_server.py:1469-1474` (docstring of `set_llm_config`)
- Zone: 6.6 / 6.7
- Observation: The MCP tool description for `scope` lists `'global' | 'processing' | 'topicization' | 'rag' | 'digest'`. `resummarize` is missing despite being supported by the underlying manager and a documented F5-C control surface (§ runbooks/F5C_DEPLOY_AND_WATCH).
- Why it matters: MCP tool descriptors are the agent-facing contract. An LLM calling `set_llm_config` will not consider `resummarize` as a valid scope and will refuse or pick the wrong one. This breaks F5-C runtime tuning from any agent UI.
- Suggested action: extend the docstring `scope` enumeration to include `'resummarize'`. Same fix lands a one-line diff in the MCP descriptor JSON if it is auto-generated.

### CODE-004 — Three Anthropic cap/cache settings read via `getattr` but undeclared in `Settings`

- severity: **major**
- category: **deadcode** / config
- confidence: **high**
- Where: `tg_parser/processing/llm/factory.py` (around the AnthropicClient construction), settings declared (or rather not declared) in `tg_parser/config/settings.py`
- Zone: 6.2
- Observation: `factory.py` reads `getattr(settings, "anthropic_prompt_caching_enabled", True)`, `getattr(settings, "processing_anthropic_input_token_estimate", 8000)`, and `getattr(settings, "processing_anthropic_output_token_estimate", 1500)`. None of these three attributes is declared on `Settings` (Pydantic v2 model). With Pydantic v2 + `extra="ignore"` (or default), env vars `ANTHROPIC_PROMPT_CACHING_ENABLED`, `PROCESSING_ANTHROPIC_INPUT_TOKEN_ESTIMATE`, `PROCESSING_ANTHROPIC_OUTPUT_TOKEN_ESTIMATE` are silently dropped, and the hardcoded defaults are always used.
- Why it matters: D.1 added the `_pause_source_for_billing` flow whose token cap directly drives the pre-flight Anthropic credit estimate. Operators cannot tune the estimate per-environment, even though `.env.example` (per recent commits) is the documented knob. This is a class of bug that silently regresses billing safety.
- Suggested action: declare the three fields as `Settings` fields with the same defaults, types, and an `EnvVar` description; remove the `getattr` fallbacks in `factory.py`. Add a one-shot test that boots `Settings(_env_file=None)` and asserts each attribute exists.

### CODE-005 — Default prompts for `digest` and `resummarize` are empty strings

- severity: **major**
- category: **prompts**
- confidence: **high**
- Where: `tg_parser/processing/prompt_loader.py` `_get_default(name)` (lines ~80-284)
- Zone: 6.7
- Observation: `_get_default` returns hardcoded fallback prompts for `processing`, `topicization`, `rag`, `bot`, `merge`, `incremental_discover`, `resummarize` — but the entries for `digest` and `resummarize` either return `{}` or are missing entirely. If `prompts/digest.yaml` or `prompts/resummarize.yaml` is missing/unreadable on disk, `prompt_loader.get(...)` will hand the LLM **empty system + empty user template strings** rather than raise.
- Why it matters: Silent empty prompts to a paid LLM call are the worst kind of failure — the request goes through, costs tokens, and returns garbage that downstream code treats as a real summary. F5-C `resummarization_service.py` does have a defensive non-empty check, but `digest_service` does not. Resilience to a missing YAML must be "fail loudly", not "degrade silently".
- Suggested action: either (a) add full default prompt bodies for both stages in `_get_default`, or (b) raise `PromptLoaderError("missing default for stage=…")` when both the YAML and the default are absent. Add `tests/test_prompt_loader.py::test_no_silent_empty_default` covering all 9 stages.

### CODE-006 — `resolve_llm_config` docstring lists only 2 of 6 supported stages

- severity: **minor**
- category: **prompts** (docs-in-code) / deadcode
- confidence: **high**
- Where: `tg_parser/processing/llm/factory.py` (docstring of `resolve_llm_config`, lines ~33-45)
- Zone: 6.7
- Observation: The docstring states `stage` is one of `"processing"` or `"topicization"`, but the function is invoked from `resummarization_service`, `digest_service`, `retrieval_service` (rag), and the watchlist embedding path. Behaviour is correct; the doc is stale.
- Why it matters: Maintainers debugging a stage routing question will follow the docstring and get the wrong answer.
- Suggested action: update the docstring to enumerate the actual `LLM_SCOPES \ {"global"}` set.

### CODE-007 — `RESUMMARIZE_TOTAL` always emits `channel_id="-"`

- severity: **minor**
- category: **observability**
- confidence: **high**
- Where: `tg_parser/api/metrics.py:113-156` (`record_resummarize_outcome`)
- Zone: 6.6
- Observation: The metric declares a `channel_id` label and the call site hard-codes `channel_id="-"`. Comment acknowledges Phase-2 deferral. Today every per-channel split shows a single bar.
- Why it matters: Multi-tenant deployments cannot answer "did F5-C explode for `@genotek` specifically?" The label is paid for (cardinality slot) but not used.
- Suggested action: either pass the real `channel_id` from `ResummarizationService.resummarize_topic` (low cardinality — one per channel) or drop the label until phase 2 lands. Half-implemented labels are worse than no label.

### CODE-008 — Asymmetric `AnthropicBillingError` handling between F5-C and F11 scheduler hooks

- severity: **minor**
- category: **errors**
- confidence: **medium**
- Where: `tg_parser/services/scheduler_service.py` (≈ lines 220-280, F5-C and F11 hook bodies)
- Zone: 6.5
- Observation: The F5-C re-summarize hook explicitly checks `isinstance(stage_errors[0][1], AnthropicBillingError)` and escalates via `_pause_source_for_billing`. The F11 watchlist hook calls `WatchlistService.run_for_documents` inside a generic `try/except Exception` that silently logs and continues. Watchlist embeddings default to OpenAI today, so the gap is theoretical, but if a user reconfigures `embedding_provider=anthropic` (the manager allows it), a billing block will be silently swallowed by the F11 path.
- Why it matters: Decision #13 (silent-log + billing-escalation) needs to be uniform across all scheduled hooks; otherwise the hook that misses the escalation is the one that will eat the credit balance during an outage.
- Suggested action: extract a `_handle_stage_errors(channel_id, stage_errors)` helper that does the `AnthropicBillingError` escalation + `_pause_source_for_billing` and call it from every hook; replace the per-hook duplicated block.

### CODE-009 — `assert_channel_access` / `assert_topic_access` are `async def` with no `await`

- severity: **minor**
- category: **deadcode** (style)
- confidence: **high**
- Where: `tg_parser/auth/ownership.py` (definitions of `assert_channel_access`, `assert_topic_access`, plus `PermissionDenied`)
- Zone: 6.1 / 6.2
- Observation: Both functions are declared `async def` but their bodies are pure synchronous DB lookups via `DatabaseSession` context manager (which is sync). Caller code awaits them, which works, but the async signature is a lie.
- Why it matters: Tiny perf cost (event-loop hop per check), and it tricks readers/static-analyzers into thinking these are I/O-suspending. Also mildly increases the chance someone adds `await` to a real-async caller and then drifts the contract again.
- Suggested action: drop `async` from both functions and adjust call sites (most callers already are sync — the awaits become direct calls). Add a `ruff` rule (`ASYNC100`) to prevent regression.

### CODE-010 — Late in-function import of `PermissionDenied` in retrieval_service

- severity: **minor**
- category: **dependency**
- confidence: **medium**
- Where: `tg_parser/services/retrieval_service.py:91` — `from tg_parser.auth.ownership import PermissionDenied`
- Zone: 6.1
- Observation: A single in-function import for a pure exception class. The rest of the file imports cleanly at module top. This is the classic shape of "I had an import cycle once, papered over".
- Why it matters: Either (a) there is a real cycle that should be resolved structurally, or (b) the late import is unnecessary cargo-culting. Either way it is a code-smell that hides intent.
- Suggested action: try to move the import to the top of `retrieval_service.py`. If that triggers a cycle, the right fix is to lift `PermissionDenied` (and just the exception) into `tg_parser/auth/exceptions.py` and have `ownership.py` re-export it.

### CODE-011 — `topic_card_versions.scope_in_json` / `scope_out_json` are `TEXT`, not `JSONB`

- severity: **minor**
- category: **schema**
- confidence: **high**
- Where: `migrations/versions/processing/20260426_add_topic_card_versions.py` (column declarations for `topic_card_versions`)
- Zone: 6.4
- Observation: The two scope columns are declared as `sa.Text()`. The corresponding live columns on `topic_cards` are JSONB (per the original F5 migration). The version row therefore has to round-trip through `json.dumps` and clients reading the audit table cannot use JSONB operators (`->`, `@>`).
- Why it matters: Audit-only storage as TEXT is a defensible choice (cheaper, immutable, simpler restore), but it diverges from the source-of-truth column type. If the diff was intentional, it deserves a comment in the migration.
- Suggested action: either upgrade the columns to `JSONB` (cleaner, matches `topic_cards`), or add a docstring/comment to the migration explicitly stating "TEXT is intentional — versions are immutable JSON blobs, not queryable structures". Pick a side, document it.

### CODE-012 — `embedding vector(1536)` hardcoded in F11 migration

- severity: **minor**
- category: **schema**
- confidence: **high**
- Where: `migrations/versions/ingestion/20260425_add_watchlist.py:46` (column for `watch_interests.embedding`)
- Zone: 6.4
- Observation: The new `watch_interests` table declares `embedding vector(1536)` literally. `Settings.embedding_dimension` defaults to 1536 but is configurable. Any future deployment that flips the embedding model to e.g. `text-embedding-3-large` (3072) or BGE-Large (1024) will break F11 silently — the embedding write will succeed in code but Postgres will reject (or worse, truncate) the cast.
- Why it matters: Ingestion-side embedding columns are typically bound to `settings.embedding_dimension`. F11 violates that pattern.
- Suggested action: either parameterize the migration via `op.execute(f"ALTER TABLE … vector({settings.embedding_dimension})")`, or add a startup-time assert in `WatchlistService` that compares column metadata to current embedding dim. Document the constraint in `docs/architecture/EMBEDDINGS.md` (if it does not yet say "all embedding columns must match `settings.embedding_dimension`").

### CODE-013 — `Database.from_settings` used inside a `cli/` command rather than via the singleton

- severity: **minor**
- category: **dependency**
- confidence: **medium**
- Where: `tg_parser/cli/backfill_content_hash_cmd.py:47`
- Zone: 6.1
- Observation: `services/db_context.py` standardizes on `Database.get_instance()` (singleton). The backfill CLI builds a fresh `Database.from_settings(settings)` inline. CLIs are short-lived processes so this is not a leak, but the divergence is the kind of thing that gets cargo-culted into a new long-lived script.
- Why it matters: Two ways to get a `Database` is one too many; the next contributor will copy the wrong one and accidentally instantiate a second engine in a long-lived service.
- Suggested action: switch the CLI to `Database.get_instance()` for consistency, or document explicitly in `db_context.py` that CLIs may use `from_settings` and services must use `get_instance()`. Pick one rule, write it down.

---

## 3. Docs findings

### DOCS-001 — ROADMAP_KARPATHY missing "Living-KB contract CLOSED 2026-04-26" marker

- severity: **major**
- category: docs
- confidence: **high**
- Where: `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` (whole file)
- Zone: 7.2
- Observation: The Living-KB contract is now feature-complete (D.1 + F11 + F5-C all merged, runbooks updated, prod healthy). The Karpathy roadmap was the contract's home document, but contains no "CLOSED 2026-04-26" / "Contract delivered" / "Wave A+B+C complete" closure marker. The revision history block from 2026-04-26 still says Wave C is "READY к реализации"; Wave B is described as "текущий фокус после D.1" despite being merged the same day; Wave A has no explicit `✅` marker.
- Why it matters: Roadmaps that don't close cleanly accumulate stale status; new contributors and the next planning session cannot tell what is done. The whole point of the Karpathy iteration cadence is "close one contract, formulate the next" — neither half is reflected here.
- Suggested action: add a top-level "## 2026-04-26 — Contract closed ✅" section that lists all three D.1/F11/F5-C waves with their deliverable links and `✅`, then either (a) formulate the next contract (working title + 1-paragraph scope), or (b) add a placeholder `## Next contract — TBD (see planning session …)` so the gap is explicit.

### DOCS-002 — FUTURE_FEATURES has no links to GitHub issue #15

- severity: **major**
- category: docs
- confidence: **high**
- Where: `docs/notes/FUTURE_FEATURES.md` (whole file, especially the "F5-C P2 backlog" section if present)
- Zone: 7.4
- Observation: The F5-C planning session deferred 10 items to a P2 backlog and explicitly asked that each be linked to GitHub issue #15. `FUTURE_FEATURES.md` does not mention `#15` anywhere (`grep #15` returns nothing), so the deferred items are floating without a tracker entry.
- Why it matters: Deferred items without an issue link are the canonical way features get lost. The whole F5-C self-review explicitly requested traceability.
- Suggested action: list the 10 deferred items as a bullet block under an "F5-C P2 backlog" heading; each bullet ends with `(see #15 — <subtask>)`. If issue #15 has sub-tasks, copy the sub-task IDs. If #15 is monolithic, link each bullet to the same issue.

### DOCS-003 — PRODUCTION_DEPLOYMENT.md not updated for D.1 / F11 / F5-C

- severity: **major**
- category: docs
- confidence: **high**
- Where: `PRODUCTION_DEPLOYMENT.md` (root of repo)
- Zone: 7.5
- Observation: The deploy guide still says `TG_parser v4.3 Production Deployment` and contains zero references to: `topic_card_versions`, F5-C migration head `a4b5c6d7e8f9`, F11 migration head `c8e9f0a1b2c3`, D.1 migration `ac6a4414ac58`, `RESUMMARIZE_*` env vars, `f5c-watch` cron, watchlist setup, `_pause_source_for_billing` operational notes.
- Why it matters: A green-field deploy following this guide today would skip three migrations and run with cap settings undocumented. Combined with CODE-004 (undeclared anthropic cap settings), a fresh prod deploy is a billing landmine.
- Suggested action: add a "v4.4 Living-KB upgrade notes" section that lists the three new migration heads, the new env vars (`RESUMMARIZE_*`, `WATCHLIST_*`), the new cron entry (`f5c_watch.sh`), and the new metrics endpoints. Bump version string to v4.4. Cross-link to `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` and `docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md`.

### DOCS-004 — CHANGELOG references wrong CLI module name and a non-existent directory

- severity: **minor**
- category: docs
- confidence: **high**
- Where: `CHANGELOG.md` Sprint F11 section (≈ line 80) and Sprint references to `tg_parser/storage/ports/` (≈ lines 75, 78)
- Zone: 7.3
- Observation: (a) `tg_parser/cli/watchlist.py` does not exist; the actual file is `tg_parser/cli/watchlist_cmd.py`. (b) `tg_parser/storage/ports/` is referenced as a directory but the path is a single file `tg_parser/storage/ports.py`.
- Why it matters: CHANGELOG is the canonical artifact for git-archaeology and external links. Wrong paths are dead links from day one.
- Suggested action: rename `watchlist.py` → `watchlist_cmd.py` in the F11 entry, and `ports/` → `ports.py` in the affected entries. Add a CI hook (one shell line) that scans CHANGELOG for `tg_parser/[^ )]*\.py` and `git ls-files` to catch broken paths.

### DOCS-005 — `docs/notes/` accumulates ~105 active prompts without an archive

- severity: **minor**
- category: docs
- confidence: **high**
- Where: `docs/notes/` (entire directory)
- Zone: 7.7
- Observation: `ls docs/notes | wc -l` ≈ 105. Many `START_PROMPT_SESSION{1..48}_*.md`, multiple superseded `START_PROMPT_*` for completed sprints (D.1, F11, F5-C), no `archive/` subfolder. Only the latest planning prompts are operationally relevant.
- Why it matters: Cognitive load on every grep over notes/. Risk of replaying a stale prompt as if it were current.
- Suggested action: create `docs/notes/archive/` and move all notes whose corresponding sprint has shipped (matched against CHANGELOG sections). Keep a `docs/notes/README.md` index pointing to live vs archived. Target: live ≤ 25 files.

### DOCS-006 — ROADMAP_KARPATHY revision-history entry for 2026-04-26 contradicts current state

- severity: **minor**
- category: docs
- confidence: **high**
- Where: `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` (revision history table, 2026-04-26 row, ≈ line 106)
- Zone: 7.2
- Observation: The 2026-04-26 row says Wave C is "READY к реализации". By the same date Wave C had been merged (PR #14, MVP DONE).
- Why it matters: Self-contradicting documentation. Two readers will get two different answers depending on which section they read.
- Suggested action: update the 2026-04-26 row to "Wave C MVP merged (PR #14)" and add a 2026-04-26 follow-up row for the post-merge audit.

### DOCS-007 — Living-KB contract has no formulated successor

- severity: **minor**
- category: docs
- confidence: **medium**
- Where: `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` ("Next contract" section is missing)
- Zone: 7.2
- Observation: The Karpathy iteration calls for "close contract → formulate next contract → start". Today the contract is closed but no successor exists in the roadmap or in `FUTURE_FEATURES.md`. Plausible candidates that recur in code/notes (cross-channel synthesis, evaluation harness, bot UX-contract) are not formalized.
- Why it matters: Without a written next contract, the next planning session has to start from scratch, and the codebase will accumulate unaligned drive-by improvements.
- Suggested action: hold a 30-minute planning session, draft a 1-page "Contract NEXT — <name>" with goal, in-scope, out-of-scope, exit criteria; commit it as `docs/notes/CONTRACT_NEXT_<slug>.md` and link from ROADMAP_KARPATHY.

### DOCS-008 — INBOX/TRIAGED in good shape (positive observation)

- severity: minor (informational)
- category: docs
- confidence: **high**
- Where: `docs/quality/INBOX.md`, `docs/quality/TRIAGED.md`
- Zone: 7.8
- Observation: `INBOX.md` empty (as expected at a contract close). `TRIAGED.md` contains exactly one entry (`genotek topicization silent failure`, status `fixed in production`) with cadence note present. This matches the contract's "no debt left behind" expectation.
- Why it matters: Confirms the quality-tracker discipline survived a 3-sprint contract — keep doing this.
- Suggested action: none. Recorded so the merger does not re-flag this as an open item.

---

## 4. Tech-debt backlog (advisory)

These are low/medium-priority items I would add to the next sprint backlog but do not consider blocking.

1. **Async-signature audit** — sweep `tg_parser/auth/ownership.py` and similar files for `async def` without `await`; add `ruff ASYNC100` (CODE-009).
2. **`Database` access uniformity** — pick singleton vs. factory for CLIs vs. services and document; CODE-013.
3. **Late-import cleanup** — `retrieval_service.py:91` and any other in-function imports surfaced by a quick grep; lift the offending exception to a leaf module (CODE-010).
4. **Per-channel `RESUMMARIZE_TOTAL`** — drop the `channel_id="-"` placeholder once Phase 2 metrics land (CODE-007).
5. **Migration linter** — add `tests/test_migrations_runtime_upgrade.py` assertion that no embedding column is `vector(<literal>)` mismatching `settings.embedding_dimension` (CODE-012).
6. **Prompt-loader hard-fail** — convert silent-empty fallbacks to a loud error (CODE-005, can be combined with adding default bodies).
7. **Resummarize stage parity** — ensure every `LLM_SCOPES` member appears in `LLMConfigManager.get_all()`, MCP `set_llm_config` docstring, and `factory.resolve_llm_config` docstring; one shared list of truth (CODE-002, CODE-003, CODE-006).
8. **`docs/notes/` archive sweep** — move ≥ 50 stale prompts (DOCS-005). Pure mechanical work.
9. **CHANGELOG path linter** — CI step that greps `tg_parser/...py` paths from CHANGELOG against `git ls-files` (DOCS-004).
10. **Prod-deploy v4.4 doc bump** — DOCS-003.

---

## 5. Recommendation for next sprint

**Start NOW (debt-fix / housekeeping sprint, ~3 days):**

- 🔴 **F11 metrics** (CODE-001): land `tg_watchlist_*` Prometheus surface — biggest blind spot in production today.
- 🟠 **LLM-config consolidation** (CODE-002, CODE-003, CODE-004, CODE-006): one PR, one shared `LLM_SCOPES` source of truth, declared `Settings` fields, regression test.
- 🟠 **Prompt-loader hard-fail + defaults for `digest`/`resummarize`** (CODE-005): ship before the next prompt-iteration session, otherwise an editor mistake corrupts production silently.
- 🟠 **Doc closure** (DOCS-001, DOCS-002, DOCS-003): close the Living-KB contract in ROADMAP_KARPATHY, link issue #15 from FUTURE_FEATURES, bump PRODUCTION_DEPLOYMENT to v4.4. ~1 hour each, blocks the next planning session.

**Defer:**

- The next Karpathy wave (cross-channel synthesis / evaluation / bot UX contract) — do not start until DOCS-001 + DOCS-007 are written down. Otherwise we drift.
- `RESUMMARIZE_TOTAL` per-channel labels — wait for Phase 2 capacity work.
- Async-signature sweep (CODE-009) — defer to the same pass as ruff config tightening.

**Hold:** another 24 h of `f5c-watch` data before any change to F5-C internals; only one cron tick observed at audit time.

---

## 6. Open questions / signals

- **Ensemble-protocol signal**: while writing this deliverable I observed a new commit `4008f36 docs(review): post-Living-KB audit by gpt55 — 15 findings` that committed `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md` (36 KB). Per § 3 of the start prompt, the parallel reviewer's deliverable must not be read by the other side. I did **not** read it; I noted only its existence (file name and commit metadata visible via `git log --oneline`). The merge session should reconcile.
- **Test coverage map (Zone 6.3)**: I did not run `pytest --cov` because the start prompt's allowlist for shell does not explicitly grant the time budget for a full suite (~1881 tests). Headcount and presence of new tests (`tests/test_resummarization_service.py`, `tests/test_topic_card_versions_repo.py`, `tests/test_watchlist_*.py`) was confirmed via `git ls-files`. A CI-side coverage delta vs. pre-D.1 baseline would be a strong addition to this audit; out of scope for read-only.
- **Watch verdict (§ 9)**: only one `~/f5c-watch/cron.log` entry visible (`GREEN (idle)` at `2026-04-26T11:07:13Z`). The full 24 h watch window has not yet elapsed. **No tripwire fired so far**, but verdict cannot be promoted to GREEN until ≥ 24 h of cron data accumulates. Recommend a follow-up audit after 2026-04-27T11:07Z.
- **`topic_card_versions` JSONB-vs-TEXT decision**: CODE-011 needs intent confirmation from the F5-C author. If the choice is intentional (audit immutability), a one-line comment in the migration closes the question.
- **F11 watchlist embedding-dim guard**: CODE-012 — there may already be a runtime check I missed; please confirm during merge.
- **Karpathy "next contract"**: the merger should treat DOCS-007 as a meta-question — it might be intentional to wait. If so, DOCS-001 still stands (close marker is mandatory regardless of next contract).

---

## 7. Metrics snapshot

- **Files changed in last 7 days**: 46 commits
- **Files changed in last 30 days**: 148 commits
- **LOC delta in last 30 days**: +91 904 / −12 392 (net +79 512)
- **Tests file count (workspace)**: ≈ 43 070 LOC across `tests/` (full pytest count not run — see § 6)
- **`tg_parser/` LOC**: 41 668
- **Migration heads**:
  - `processing` = `a4b5c6d7e8f9` (`20260426_add_topic_card_versions`)
  - `ingestion` = `c8e9f0a1b2c3` (`20260425_add_watchlist`)
  - `raw` = `5c658f04eff0` (`20251229_1859_initial_raw_schema`)
- **Local HEAD at review baseline**: `eb9756a`
- **Prod HEAD (verified via SSH `git -C ~/TG_parser rev-parse --short HEAD`)**: `eb9756a` — **same as local baseline** ✓
- **Prod services**: all healthy (api, mcp, scheduler, bot — verified via `systemctl status` ssh probe)
- **Prod cron `f5c_watch.sh`**: 1 entry, `GREEN (idle)`, no tripwire

---

*End of opus-side deliverable.*
