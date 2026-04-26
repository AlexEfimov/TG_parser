# Post-Living-KB Audit — Merged Plan

**Merged from:**
- `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__gpt55.md` (commit `4008f36`)
- `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__opus.md` (uncommitted at merge time; file present in working tree)

**Merge agent:** Claude Opus 4.7
**Merged (UTC):** 2026-04-26T12:25:18Z
**Base commit at merge:** `4008f36`
**Watch state at merge:** 1 verdict row; latest: `f5c_watch[2026-04-26T11:07:13Z]: GREEN (idle) — no re-summarize ticks yet (legit if no new items in channels)`

**Source statistics:**
- Reviewer 1 (`gpt55`): C=1/M=4/m=10, OQ=4
- Reviewer 2 (`opus`): body list C=0/M=7/m=13 plus 1 positive informational finding, OQ=6; executive summary describes CODE-001 as "critical observability gap" while the finding row marks it `major`

**Merged statistics:**
- Confirmed (both reviewers): 7 findings (C=0/M=4/m=3)
- Single (one reviewer only): 16 findings (C=1/M=4/m=11)
- Contested (conflict): 0 findings
- Total dedupe ratio: 34.3% (`(35 source issue-findings - 23 merged findings) / 35`)

**Disclosure events:**
- Source baselines differ: `gpt55` used base `ef952b4`; `opus` used baseline `eb9756a` and observed HEAD `4008f36` at deliverable write.
- `opus` deliverable is untracked at merge time, so it has no landed commit SHA yet.
- `opus` reports it noticed the `gpt55` deliverable commit metadata mid-review but did not read the deliverable.
- `opus` does not include a machine-parseable findings-count header; counts above are derived from the body.

---

## 1. Executive summary

Both reviewers converge on the same next-step recommendation: run a debt-fix / housekeeping sprint before starting the next Karpathy wave. The Living-KB contract is functionally closed, prod watch is currently GREEN-idle, and the highest-risk remaining work is not a new feature gap but observability/config/documentation drift around shipped D.1/F11/F5-C behavior.

Top findings:
- `S-001` critical single: scheduler persists `error_message` at 500 chars while D.1 docs promise 4096 chars.
- `C-001` major confirmed: F11 watchlist shipped without the promised Prometheus metrics surface.
- `S-002`/`S-003`/`S-004` major single cluster: resummarize/LLM/prompt configuration is not fully observable or fail-loud.
- `C-002`/`C-003`/`C-004` major confirmed docs cluster: deploy guide, Karpathy roadmap, and Future Features do not close or trace the delivered Living-KB contract.

Recommendation: **debt-fix sprint, high confidence**. Open P0 issues for TD-01 through TD-04, land them before feature work, and keep F5-C internals stable until a full 24h watch window has elapsed.

---

## 2. Confirmed findings (both reviewers)

### Observability

#### C-001 — major | observability | merge-status: confirmed

**Where:** `tg_parser/api/metrics.py`, `tg_parser/services/watchlist_service.py`

**Source findings:**
- `gpt55-002` (severity: major, confidence: high)
- `opus CODE-001` (severity: major, confidence: high)

**Merged observation:** F11 watchlist matching/delivery has no Prometheus metrics. Both reviewers found that `metrics.py` exports scheduler/F5-C/billing metrics but no watchlist match/delivery/score counters or histograms, while docs/planning expected a threshold-calibration metric.

**Why it matters (merged):** Operators cannot tell from Prometheus/Grafana whether watchlists are firing, filtered, blocked, or failing. This blocks F11 P2 tuning because the default threshold cannot be calibrated from production signal.

**Suggested action (merged):** Add a watchlist metrics surface in `tg_parser/api/metrics.py` and wire it from `WatchlistService`: at minimum match counts by outcome/result, score buckets or histogram, delivery outcomes, and active interests gauge. Include a regression test and a PromQL/runbook example.

**Notes:** `gpt55` proposed `tg_watchlist_matches_total{interest_id,score_bucket}`; `opus` proposed a broader `tg_watchlist_*` surface. Start with the broader shape but keep cardinality bounded.

### Documentation

#### C-002 — major | deploy-stale | merge-status: confirmed

**Where:** `PRODUCTION_DEPLOYMENT.md`

**Source findings:**
- `gpt55-010` (severity: major, confidence: high)
- `opus DOCS-003` (severity: major, confidence: high)

**Merged observation:** The production deployment guide is stale for D.1/F11/F5-C. It lacks the new migrations, F5-C/F11 env vars, cron/watch references, metrics checks, billing-pause notes, and links to the F5-C runbook.

**Why it matters (merged):** A cold deploy or DR run following the canonical guide can miss shipped operational requirements, especially resummarize caps, watchlist setup, and billing safety behavior.

**Suggested action (merged):** Add a `v4.4 Living-KB upgrade notes` section covering migrations `ac6a4414ac58`, `c8e9f0a1b2c3`, `a4b5c6d7e8f9`, relevant env vars, verification commands, cron/watch setup, and links to `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` and `docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md`.

#### C-003 — major | roadmap-stale | merge-status: confirmed

**Where:** `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`

**Source findings:**
- `gpt55-011` (severity: minor, confidence: high)
- `opus DOCS-001` (severity: major, confidence: high)
- `opus DOCS-006` (severity: minor, confidence: high)
- `opus DOCS-007` (severity: minor, confidence: medium)

**Merged observation:** The Karpathy roadmap does not clearly mark the Living-KB contract as closed on 2026-04-26, contains stale revision-history language around Wave C, and has no explicit next-contract placeholder.

**Why it matters (merged):** This roadmap is the contract home. Without a closure marker and successor placeholder, the next planning session starts from stale state and contributors can misread completed work as active scope.

**Suggested action (merged):** Add a top-level `2026-04-26 — Contract closed` section listing D.1/F11/F5-C deliverables, update the revision history, and add either a one-page next-contract stub or an explicit `Next contract — TBD` placeholder.

#### C-004 — major | future-features-stale | merge-status: confirmed

**Where:** `docs/notes/FUTURE_FEATURES.md`

**Source findings:**
- `gpt55-015` (severity: minor, confidence: low)
- `opus DOCS-002` (severity: major, confidence: high)

**Merged observation:** F5-C P2 backlog items are not linked to GitHub issue #15 from `FUTURE_FEATURES.md`.

**Why it matters (merged):** Deferred P2 items lose traceability when the file and tracker are not cross-linked. `gpt55` could not verify the issue body, but both reviewers agree the file lacks the link.

**Suggested action (merged):** Add an issue #15 reference to the F5-C P2 backlog and, if possible, link each deferred item/subtask to the corresponding tracker entry. Verify the issue body and the file describe the same backlog.

#### C-005 — minor | notes-archive | merge-status: confirmed

**Where:** `docs/notes/`

**Source findings:**
- `gpt55-014` (severity: minor, confidence: high)
- `opus DOCS-005` (severity: minor, confidence: high)

**Merged observation:** `docs/notes/` has roughly 105 markdown files and mixes active prompts with completed sprint/session prompts.

**Why it matters (merged):** Search results and onboarding context are noisy; stale prompts are easy to replay accidentally.

**Suggested action (merged):** Create `docs/notes/archive/` plus an index/readme and move shipped or superseded prompts there. Keep the current audit/merge prompts live until this review workflow is closed.

### Error handling

#### C-006 — minor | error-handling | merge-status: confirmed

**Where:** `tg_parser/services/scheduler_service.py`

**Source findings:**
- `gpt55-004` (severity: minor, confidence: high)
- `opus CODE-008` (severity: minor, confidence: medium)

**Merged observation:** Scheduler billing-error handling is ad hoc across hooks. `gpt55` found duplicated adjacent `AnthropicBillingError` guards in `_process_source`; `opus` found an asymmetry where the F11 hook may swallow billing blocks under a generic exception path.

**Why it matters (merged):** Decision #13 style billing escalation should be uniform across scheduled hooks; duplication and asymmetry make future edits risky.

**Suggested action (merged):** Extract a small helper for billing-error escalation / pause / metric recording and call it from every relevant scheduler hook. Collapse the duplicate adjacent guard as part of the same PR.

### Changelog hygiene

#### C-007 — minor | changelog-incomplete | merge-status: confirmed

**Where:** `CHANGELOG.md`

**Source findings:**
- `gpt55-013` (severity: minor, confidence: high)
- `opus DOCS-004` (severity: minor, confidence: high)

**Merged observation:** CHANGELOG contains stale or wrong repo paths: `gpt55` found the non-existent `tests/test_f11_watch_match_repo.py` reference; `opus` found wrong CLI/module path references.

**Why it matters (merged):** CHANGELOG is the git-archaeology artifact. Broken paths are low-severity but waste reviewer/operator time.

**Suggested action (merged):** Correct the F11/F5-C path references and consider a small CI check that validates `tg_parser/...py` and `tests/...py` paths mentioned in CHANGELOG against `git ls-files`.

---

## 3. Single findings (one reviewer only)

### Critical

#### S-001 — critical | error-handling | merge-status: single

**Where:** `tg_parser/services/scheduler_service.py:744`, `CHANGELOG.md`, `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-001` (severity: critical, confidence: high)
- `gpt55-009` (severity: major, confidence: high)

**Merged observation:** `_truncate_error_message` defaults to 500 chars, while D.1 documentation promises `error_message` is truncated to 4096 chars. This is the code finding plus its docs-side mirror.

**Why it matters (merged):** D.1's central promise is truthful persisted failure evidence. A 500-char cap can cut the part of billing/API/stack-trace messages needed for RCA, and docs tell operators they have eight times more context than the DB stores.

**Suggested action (merged):** Decide the actual policy, then align code and docs in one PR. Preferred fix: bump code to 4096, add a regression test for the persisted limit, and keep docs unchanged except for clarifying the invariant.

**Notes:** `opus` did not mention this item. Given severity and low fix cost, keep it P0 despite single-reviewer status.

### Major

#### S-002 — major | observability | merge-status: single

**Where:** `tg_parser/config/settings.py`, `tg_parser/mcp_server.py`, `tg_parser/processing/llm/factory.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-002` (severity: major, confidence: high)
- `opus CODE-003` (severity: minor, confidence: high)
- `opus CODE-006` (severity: minor, confidence: high)

**Merged observation:** `resummarize` is not consistently represented across LLM runtime configuration surfaces: `get_all()` omits it, MCP docstrings omit it, and `resolve_llm_config` docs list only older stages.

**Why it matters (merged):** F5-C runtime model/provider tuning is a shipped control surface. Operators and agents need `get_llm_config` and tool descriptors to show the same set of supported stages.

**Suggested action (merged):** Make `LLM_SCOPES` the single source of truth for config payloads and docs, add `resummarize` to `get_all()["stages"]`, update MCP/factory docstrings, and add a regression test that every non-global scope is visible.

#### S-003 — major | config | merge-status: single

**Where:** `tg_parser/processing/llm/factory.py`, `tg_parser/config/settings.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-004` (severity: major, confidence: high)

**Merged observation:** Anthropic prompt-cache/token-estimate knobs are read with `getattr(...)` but not declared as `Settings` fields, so documented env vars may be silently ignored.

**Why it matters (merged):** These values drive billing-safety estimates. Silent defaulting can defeat environment-specific tuning.

**Suggested action (merged):** Declare the three settings fields with defaults/types/descriptions, remove `getattr` fallbacks, and test that the settings object exposes them.

#### S-004 — major | prompts | merge-status: single

**Where:** `tg_parser/processing/prompt_loader.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-005` (severity: major, confidence: high)

**Merged observation:** Prompt-loader defaults for `digest` and/or `resummarize` may degrade to empty prompt strings if YAML files are missing or unreadable.

**Why it matters (merged):** Empty prompts to a paid LLM can produce garbage while looking like a successful call. F5-C has an extra guard, but digest does not appear to share the same protection.

**Suggested action (merged):** Either provide complete built-in defaults for every prompt stage or raise loudly when no YAML/default exists. Add a test covering all prompt stages.

**Notes:** `gpt55` verified prompt YAML presence and metadata, not fallback behavior; this is not a contested finding.

#### S-005 — major | roadmap-stale | merge-status: single

**Where:** `ROADMAP_V3_PRODUCTION_FIRST.md`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-008` (severity: major, confidence: high)

**Merged observation:** `ROADMAP_V3_PRODUCTION_FIRST.md` still presents F11/F5-C as future or planned work despite Wave 1 being done.

**Why it matters (merged):** This is likely the first roadmap new contributors see; stale priority state can send planning work in the wrong direction.

**Suggested action (merged):** Add a Wave 1 closed banner, move D.1/F11/F5-C to done status, and re-rank Wave 2 candidates after the debt sprint.

### Minor

#### S-006 — minor | dependency-graph | merge-status: single

**Where:** `tg_parser/services/*`, `tg_parser/api/metrics.py`, `tg_parser/api/health_checks.py`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-003` (severity: minor, confidence: high)

**Merged observation:** Service-layer files import observability helpers from `tg_parser.api.*`, which violates the declared layering expectation even if there is no cycle today.

**Why it matters (merged):** `tg_parser.api.metrics` is observability infrastructure, not an HTTP surface; the naming makes the `services → api` invariant look broken on grep, and a careless future refactor (someone moves a route handler into `api.metrics`) would turn a cosmetic smell into a real cycle.

**Suggested action (merged):** Either extract metrics/health into `tg_parser.observability.*` or document `api.metrics`/`api.health_checks` as explicit exceptions.

#### S-007 — minor | observability | merge-status: single

**Where:** `tg_parser/services/scheduler_service.py`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-005` (severity: minor, confidence: high)

**Merged observation:** Some scheduler logs still use positional `%s` formatting instead of structlog key/value fields.

**Why it matters (merged):** Mixed log conventions in one hook chain mean Loki/JSON consumers see structured fields for some events and rendered strings for others — same scheduler tick, different shape. Dashboards filtering by `event="source_failed"` will miss the D.1 lines.

**Suggested action (merged):** Convert scheduler logs to event/key-value style and optionally add a lightweight lint/grep guard.

#### S-008 — minor | resource-lifecycle | merge-status: single

**Where:** `tg_parser/services/resummarization_service.py`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-006` (severity: minor, confidence: medium)

**Merged observation:** `ResummarizationService` creates and closes an LLM client per topic call, suppressing close failures.

**Why it matters (merged):** Per-tick HTTP keep-alive is lost on every call (small but real overhead under the 10 topics/tick × hourly cadence), and `contextlib.suppress(Exception)` silently swallows close failures — if a provider regression starts leaking sockets, the first signal will be `ulimit -n` exhaustion, not a log line.

**Suggested action (merged):** Consider a small `(provider, model)` keyed client cache closed from `aclose()`, preserving runtime reconfiguration and logging close failures.

#### S-009 — minor | dead-code | merge-status: single

**Where:** `tg_parser/cli/topic_cmd.py`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-007` (severity: minor, confidence: medium)

**Merged observation:** CLI reads both `version_no` and dead fallback `summary_version` from resummarization output.

**Why it matters (merged):** No caller emits `summary_version` today; carrying the fallback hides the service contract — readers can't tell whether the key is reserved for a future path or pure scar tissue from the original CLI version-printing bug fix.

**Suggested action (merged):** If no caller emits `summary_version`, drop the fallback and pin `version_no` in service docs/tests.

#### S-010 — minor | architecture-docs | merge-status: single

**Where:** `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`

**Found by:** `gpt55`

**Source findings:**
- `gpt55-012` (severity: minor, confidence: high)

**Merged observation:** The architecture reference does not list F5-C `resummarization_service.py` or F11 `watchlist_service.py` in key files / post-D.1 hook chain.

**Why it matters (merged):** New contributors reading this doc to understand the incremental flow will miss two of the three services that run in it. F5-C and F11 are first-class participants in the post-incremental tick chain, not external features.

**Suggested action (merged):** Add both services and a short post-D.1 hook-chain note.

#### S-011 — minor | observability | merge-status: single

**Where:** `tg_parser/api/metrics.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-007` (severity: minor, confidence: high)

**Merged observation:** `RESUMMARIZE_TOTAL` declares `channel_id` but currently emits `channel_id="-"` for all events.

**Why it matters (merged):** Multi-tenant deployments cannot answer "did F5-C explode for `@genotek` specifically?" The label is paid for (cardinality slot) but not used; half-implemented labels are worse than no label.

**Suggested action (merged):** Either pass real channel IDs when feasible or remove the label until F5-C Phase 2 needs it.

#### S-012 — minor | dead-code | merge-status: single

**Where:** `tg_parser/auth/ownership.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-009` (severity: minor, confidence: high)

**Merged observation:** `assert_channel_access` / `assert_topic_access` are `async def` but use synchronous DB calls and contain no `await`.

**Why it matters (merged):** Tiny per-call event-loop hop, and the async signature lies to readers/static-analysers about I/O behaviour, increasing the chance someone adds `await` to a real-async caller and drifts the contract again.

**Suggested action (merged):** Convert to sync functions if call-site churn is small, or defer to an async-signature lint pass.

#### S-013 — minor | dependency | merge-status: single

**Where:** `tg_parser/services/retrieval_service.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-010` (severity: minor, confidence: medium)

**Merged observation:** `PermissionDenied` is imported inside a function, likely as cycle scar tissue.

**Why it matters (merged):** Either there is a real cycle that should be resolved structurally, or the late import is cargo-culting. Either way it is a smell that hides intent and invites the next contributor to copy the pattern.

**Suggested action (merged):** Try a top-level import; if it cycles, lift the exception to a leaf module and re-export.

#### S-014 — minor | schema | merge-status: single

**Where:** `migrations/versions/processing/20260426_add_topic_card_versions.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-011` (severity: minor, confidence: high)

**Merged observation:** `topic_card_versions.scope_in_json` / `scope_out_json` use `TEXT` while live `topic_cards` columns use JSONB.

**Why it matters (merged):** Audit rows have to round-trip through `json.dumps`, and clients reading the audit table cannot use JSONB operators (`->`, `@>`). The divergence from the source-of-truth column type is either an intentional immutability choice or an oversight; the migration does not say which.

**Suggested action (merged):** Confirm intent. If immutable text blobs are deliberate, add a migration comment; otherwise plan a JSONB follow-up.

#### S-015 — minor | schema | merge-status: single

**Where:** `migrations/versions/ingestion/20260425_add_watchlist.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-012` (severity: minor, confidence: high)

**Merged observation:** F11 migration hardcodes `embedding vector(1536)` while embedding dimension is configurable.

**Why it matters (merged):** Ingestion-side embedding columns are typically bound to `settings.embedding_dimension`. Any future deployment that flips the embedding model (e.g. `text-embedding-3-large` 3072 or BGE-Large 1024) will break F11 silently — the embedding write succeeds in code but Postgres rejects or truncates the cast.

**Suggested action (merged):** Add a startup/runtime guard comparing DB vector dimension to settings, or document the fixed-dimension constraint.

#### S-016 — minor | dependency | merge-status: single

**Where:** `tg_parser/cli/backfill_content_hash_cmd.py`

**Found by:** `opus`

**Source findings:**
- `opus CODE-013` (severity: minor, confidence: medium)

**Merged observation:** CLI constructs `Database.from_settings(settings)` directly while service code standardizes on the singleton.

**Why it matters (merged):** Two ways to get a `Database` is one too many; the next contributor will copy the wrong one and accidentally instantiate a second engine in a long-lived service, doubling pool size silently.

**Suggested action (merged):** Pick and document the rule for CLI vs service database construction; change this CLI only if the project rule says all code should use the singleton.

---

## 4. Contested findings (conflict)

No contested findings after merge. Apparent near-conflicts were resolved as different scopes:
- `gpt55` found no prompt YAML drift; `opus` found fallback/default risk in `PromptLoader`.
- `gpt55` found schema chains healthy; `opus` raised type/embedding-dimension hygiene questions.

---

## 5. Recommendation для следующего спринта

**Recommendation:** run a **debt-fix / housekeeping sprint** before any new feature scope. **Confidence: high.**

Why:
- Both reviewers independently recommend debt-fix / housekeeping.
- The only merged critical item (`S-001`) and the main confirmed major item (`C-001`) are small, high-leverage observability fixes.
- The LLM config/prompt-loader cluster (`S-002`/`S-003`/`S-004`) is operationally important because it affects shipped runtime control surfaces.
- The docs closure cluster (`C-002`/`C-003`/`C-004`/`S-005`) blocks clean planning of the next contract.

Watch verdict: current prod watch state is **GREEN (idle)** with one row at `2026-04-26T11:07:13Z`. Do not change F5-C internals based on this alone; wait until at least 24h of watch data is available unless a tripwire fires.

Alternative: start F11 P2, but only after landing `C-001` watchlist metrics. Starting it before metrics would fold debt-fix into the feature sprint with worse visibility.

---

## 6. Tech-debt backlog (merged)

| ID | Title | Source findings | Status | Scope | Priority |
|---|---|---|---|---|---|
| TD-01 | Align scheduler `error_message` truncation contract | S-001 | single | S | P0 |
| TD-02 | Add F11 watchlist Prometheus metrics | C-001 | confirmed | S/M | P0 |
| TD-03 | Consolidate LLM scopes, Anthropic settings, and prompt-loader fail-loud behavior | S-002, S-003, S-004 | single | M | P0 |
| TD-04 | Close Living-KB docs in deploy guide, Karpathy roadmap, Future Features, and ROADMAP_V3 | C-002, C-003, C-004, S-005 | confirmed/single | M | P0 |
| TD-05 | Normalize scheduler billing-error handling and scheduler structured logs | C-006, S-007 | confirmed/single | S/M | P1 |
| TD-06 | Clean observability ownership and F5-C metric/client lifecycle edges | S-006, S-008, S-011 | single | M | P1 |
| TD-07 | Fix changelog and architecture reference drift | C-007, S-010 | confirmed/single | S | P1 |
| TD-08 | Document or guard schema/config invariants for F5-C/F11 storage | S-014, S-015 | single | S/M | P1 |
| TD-09 | Archive stale `docs/notes/` prompts and add an index | C-005 | confirmed | M | P2 |
| TD-10 | Sweep minor dead-code/dependency consistency issues | S-009, S-012, S-013, S-016 | single | M | P2 |

Priority key: `P0` next sprint before feature work; `P1` include if sprint capacity allows; `P2` later hygiene.

---

## 7. Action plan для юзера

1. Open GitHub issues for TD-01 through TD-04 first. These are the debt-fix sprint blockers.
2. Include TD-05 through TD-08 as stretch or follow-up issues. They are small enough to batch if the sprint is already touching scheduler/observability/docs/schema.
3. Do not open a fix issue for contested findings; there are none.
4. Keep F5-C internals stable until the 24h watch report is available. If watch remains GREEN, proceed with TD-01/TD-02/TD-03/TD-04 before feature scope.
5. After docs closure, choose the next contract explicitly: F11 P2 is the closest feature candidate, but it should start only after watchlist metrics exist.
6. Do not spend the first debt sprint on `docs/notes/` archive unless the P0/P1 items are already closed; it is useful but not a blocker.

Suggested issue grouping:
- Issue A: `fix(scheduler): align error_message truncation with D.1 contract`
- Issue B: `feat(watchlist): add Prometheus metrics for matching and delivery`
- Issue C: `fix(config): make LLM scopes/settings/prompts fail-loud and observable`
- Issue D: `docs: close Living-KB contract across deploy and roadmap docs`
- Issue E: `refactor(scheduler): centralize billing-error handling and structured logs`
- Issue F: `chore(review): clean post-audit docs/schema/dependency hygiene`

---

## 8. OPEN QUESTIONS (юзеру)

### Blocking

1. For `S-001`: should the true `error_message` persistence limit be 4096 as documented, or should docs be corrected to 500 with rationale?
2. For TD-03: should prompt-loader behavior prefer complete built-in defaults or fail-loud when YAML/defaults are absent?
3. For `C-004`: does GitHub issue #15 already contain the full F5-C P2 backlog, or should the file be treated as source of truth and the issue synced from it?
4. For `C-003`: should the next contract be drafted now, or should ROADMAP_KARPATHY explicitly say `Next contract — TBD` until a planning session?

### Non-blocking

1. For `S-014`: are `topic_card_versions.scope_*_json` TEXT columns intentional immutable blobs, or should they become JSONB?
2. For `S-015`: is `vector(1536)` an intentional deployment constraint for F11 watchlists?
3. For `S-006`: should metrics/health move to `tg_parser.observability.*`, or should `tg_parser.api.metrics` become an allowed layering exception?
4. For `S-009`: is the `summary_version` CLI fallback intentional forward-compatibility or removable scar tissue?
5. Should a second post-hoc reviewer re-check only `S-001` and the TD-03 cluster, since they were single-reviewer high-severity items?

---

## 9. Metrics snapshot (на момент merge)

- **HEAD:** `4008f36`
- **Review baselines:** `gpt55` base `ef952b4`; `opus` baseline `eb9756a`, write-time HEAD `4008f36`
- **Watch cron-log:** 1 verdict row; latest `GREEN (idle)` at `2026-04-26T11:07:13Z`
- **Tests:** not re-run during merge. `gpt55` cites `1881 passed, 4 skipped, 1 deselected` from CHANGELOG/no-PG context; `opus` did not run full coverage.
- **Gap from review baseline:** base commits differ by review-protocol commits only according to source notes; no independent code re-review performed in merge session.
- **Source files:** `gpt55` deliverable committed in `4008f36`; `opus` deliverable exists in working tree but is not committed.
