# Wave 1 Step 3 — DONE marker (24h watch closed GREEN)

**Дата создания:** 2026-05-22 (immediately after commit 4/4 lands).
**Deploy (Phase C):** 2026-05-22 — prod `a30abd5`, migration `f1a2b3c4d5e6` applied; see [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) + runbook [`WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md).
**Step 3.1 deploy:** 2026-05-22T14:01:40Z — `b875faf` (PR #90, MCP HTTP dispatch per ADR 0007 Accepted).
**Follow-ups deploy:** 2026-05-22T17:42:42Z — `d143e5d` (PR #91, idempotency replay normalization + tests + compose harness).
**24h watch closed:** **2026-05-23T09:35Z** (T+22h09m, 1h17m early vs nominal — caveat documented in § 3) — **verdict GREEN** per [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).
**Закрывает:** Wave 1 step 3 «Surface Parity MVP» per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).
**Packaging:** single PR + 4 atomic commits (mirror Wave 1 step 1 / step 2 hybrid pattern) per sprint prompt § 8.

---

## 1. Что закрыто

| Sprint slot | Commit (4/4) | Squash SHA | Deployed | 24h watch verdict |
|---|---|---|---|---|
| ENH-9 + BUG-022 service-layer foundation | 1/4 | `56e65e2` | 2026-05-22 | ✅ **PASS** (no service-layer errors on `/api/v1/watchlists` or `/api/v1/digests` over 22h09m observed window; 0 × 5xx) |
| P-1 Watchlist HTTP API (5 endpoints) | 2/4 | `6efb20b` | 2026-05-22 | ✅ **PASS** (HTTP window-1 K1 at T+3h and HTTP window-2 K2 at T+14h46 both passed miss/hit/mismatch path; Prometheus counters increment correctly) |
| P-2 Digest HTTP API (4 endpoints) | 3/4 | `0e450eb` | 2026-05-22 | ✅ **PASS** (smoke 422 cron validation + DELETE 204→404 + MCP `subscribe_digest` `digest_watch_smoke` create/delete clean; daily digest cron failure surfaced at T+18h35 is BUG-028, NOT a step 3 regression — see § 3 + Open items) |
| Idempotency-Key HTTP middleware + cleanup + docs | 4/4 | `5b828cf` | 2026-05-22 | ✅ **PASS** (all 3 `result` labels populated: `miss=4, hit=4, mismatch=3`; `table_size{api}=5` non-zero; hourly cleanup tick fired at T+1h, T+2h, …) |

**Merge:** [PR #89](https://github.com/AlexEfimov/TG_parser/pull/89) → `a30abd5` (2026-05-22T10:38:12Z UTC).

**Закрытые bug / feature IDs:**

* **BUG-022** — `subscribe_watchlist` / `subscribe_digest` now idempotent on natural keys (`(user_id, title)` / `(owner_id, name)`). Service-layer pre-flight lookup updates mutable fields and returns existing UUID with `created=false`. Cross-surface fix (MCP / Bot / CLI / HTTP).
* **ENH-9** — `workspace_id` параметр на subscribe-tools на всех четырёх поверхностях; FK to `workspaces` с `ON DELETE SET NULL`.
* **P-1** — Watchlist HTTP API landed.
* **P-2** — Digest HTTP API landed.

## 2. Acceptance signals table (per sprint prompt § 6)

| # | Criterion | Source of truth | Status (pre-watch) | Watch verdict |
|---|---|---|---|---|
| 1 | `2175+ / 300+ / 0` default-mode pytest | `pytest -q --tb=line` | ✅ **2175 / 311 / 0** (verified pre-merge) | n/a |
| 2 | `2475+ / 9 / 0` `TEST_POSTGRES=1` pytest | `TEST_POSTGRES=1 pytest -q --tb=line` | ✅ **2477 / 9 / 0** (verified pre-merge) | n/a |
| 3 | `ruff format` + `ruff check` clean | repo-wide | ✅ verified pre-merge | n/a |
| 4 | 0 regressions on `test_api_watchlists`, `test_api_digests`, `test_subscribe_idempotency`, `test_watchlist_workspace_id`, `test_f4*`, `test_f6*`, `test_f11*` | targeted pytest | ✅ verified pre-merge (84 regression tests) | n/a |
| 5 | `tg_idempotency_keys_hit_total{result=hit\|miss\|mismatch}` time-series visible in Prometheus 24h post-deploy | `query?query=tg_idempotency_keys_hit_total` | deploy smoke: 0 series at T+0 | ✅ **PASS** — final values `miss=4, hit=4, mismatch=3` (all three `result` labels populated; `service=api` instance) |
| 6 | `tg_idempotency_keys_table_size` gauge updates after first hourly cleanup tick (T+1h post-deploy) | `query?query=tg_idempotency_keys_table_size` | T+1h30 readout: `api=3` (non-zero) | ✅ **PASS** — `table_size{api}=5` at closure; T+1h30 = 3, T+3h = 3, T+14h46 = 4, T+15h00 = 5, post-watch = 5 (gauge alive + updates monotonically through HTTP windows + hourly cleanup cycles) |

## 3. Post-watch state

**Immediate deploy smoke (2026-05-22, localhost on VPS, pre-follow-ups):** watchlist 201; digest invalid-cron 422; digest DELETE 204→404; workspace foreign 404; idempotency mismatch 422. Idempotency replay: same `watchlist_id`, no duplicate row; `created` JSON field was `true` on replay (verbatim cache) — flagged for watch + immediately fixed in follow-ups PR #91 (`d143e5d`) with normalization to `created: false` on replay.

**Bot session smoke (2026-05-22 23:45 → 00:10 MSK 23-05):** 11 dialog turns — `whoami` + `list_channels` + bot-side `trigger_pipeline(mind_rise)` with FSM-confirm + `subscribe_watchlist(wl_bot_watch_smoke)` + 8 unsubscribe attempts (5 success by UUID, 3 BUG-025 occurrences by name). All write-flows landed correctly in DB cross-check. Detail: [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6 Observations](WATCH_24H_BOT_ACTIONS_2026-05-22.md).

**MCP catch-up triggers (2026-05-23 08:29Z / 12:29 MSK):** `trigger_pipeline(mind_rise)` + `trigger_topicization(genotek)` + `trigger_link_topics(AgeManagment)` all `triggered=true`; status `success` confirmed at T+15h00 Prometheus snapshot. Detail: [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` § 7 T+14h46 catch-up row](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md).

**Cleanup verification (2026-05-23 09:17Z / 13:17 MSK, T+15h00):** all 4 created artifacts (`wl_watch_smoke`, `digest_watch_smoke`, `workspace_watch_smoke`, `wl_bot_watch_smoke` already user-deleted earlier) are soft-deleted or hard-removed; `list_watchlists count=12` shows 0 active `_watch_smoke` rows; `list_digests count=1` (only prod endocrinology); `list_workspaces count=3` (only prod). Pipeline state clean (`get_pipeline_status` all 3 channels `fail_count=0`, all `success` after catch-up).

**Idempotency replay PASS on prod (post-`d143e5d`):**

* T+0 immediate smoke (`d143e5d`): replay returns `created=false` (verified at T+0 via SSH curl loopback).
* T+3h HTTP window-1 (K1=`50056815-…`, body B1): B2 replay → `201 created=false`, same `watchlist_id=128901f2-…`; B3 mismatch → `422 IdempotencyKeyMismatch`.
* T+14h46 HTTP window-2 (K2=`353e972c-…`, body B1): B2 replay → `201 created=false`, same `watchlist_id=f75326de-…`; B3 mismatch → `422 IdempotencyKeyMismatch`.
* Prometheus counter `tg_idempotency_keys_hit_total{result=hit}=4` reflects the 4 replay events (2 immediate-smoke + 2 watch HTTP windows).

This closes the immediate-smoke flag (`created=true` on replay) recorded pre-watch — `d143e5d` deployed the canonical-body fix and prod confirms `created=false` on three independent replay events over the watch window.

**Pre-migration prod admin:** 3× `(user_id, title)` duplicate groups deduped ([`wave1_step3_idempotency_dedupe.md`](../runbooks/wave1_step3_idempotency_dedupe.md)) before `f1a2b3c4d5e6` upgrade.

**Container health snapshot (closure, 2026-05-23 09:30Z):** `docker inspect StartedAt` shows `tg_parser/tg_parser_mcp/tg_parser_bot` all started `2026-05-22T17:42:42.65…Z` (synchronous restart at follow-ups deploy); zero restarts in 16h+ since.

**Early-closure caveat (T+22h09m vs nominal T+24h00):** closure session executed 1h17m early because (a) all planned MCP/HTTP/bot `_watch_smoke` artifacts cleaned by T+15h00, (b) hard cut-off T+15h45 passed, (c) no further write traffic planned. The remaining ~1h52m has NOT been observed by closure log scan; risk of regression in the residual window is judged extremely low (zero 5xx over the observed 22h09m, frozen counters, stable `up=1`). End epoch for Prometheus `query_range` was set to nominal `2026-05-23T11:25:47Z` (Prometheus tolerates future END — returns data through `now`).

**Bug-class adjudication (`git diff a30abd5^ a30abd5` discriminator, mirroring Wave 1 step 2 precedent):**

| Bug | Surface | Adjudication | Evidence |
|---|---|---|---|
| BUG-025 / 026 / 027 | bot UX | **New bug surfaced by watch** (pre-existing F11/F6 service-layer + bot prompt gaps; bot interactive cleanup sequence exercised the cleanup paths for the first time at scale) | `git blame tg_parser/bot/tools.py` for unsubscribe call-sites → predates step 3 by months; `git show 5b828cf` did not touch `_exec_unsubscribe_*` or `delete_interest_for_user` |
| BUG-028 | digest scheduler | **New bug surfaced by watch** (pre-existing F6 latent bug since 2026-04-19; daily 09:00 MSK cron tick of prod `digest_94483db9` landed inside watch window for first time post-`d143e5d` restart) | `git blame -L 555,565 tg_parser/services/scheduler_service.py` → `410452a6` (2026-04-19, F6); `git show 5b828cf --stat tg_parser/services/scheduler_service.py` → 34 insertions, 0 modifications to `digest_task` path |
| **Regressions introduced by step 3** | — | **NONE** | All 4 GREEN criteria PASS; no `tg_idempotency_keys_*` series regressions; no `/api/v1/(watchlists\|digests\|pipeline)` 5xx; no Wave 1 step 1 / step 2 metric series degraded |

## 4. Known partials / monitoring-only

| Item | Reason | Re-evaluate trigger |
|---|---|---|
| **ADR 0008** chat_id-only target (locked for this sprint) | Polymorphic webhook / channel target consciously deferred per sprint prompt anti-scope. Wave 1 step 4 (Shareable Digest) + Wave 2A (webhook surface) carry the follow-up. | Wave 1 step 4 planning sub-session re-reads ADR 0008 § Options + this marker. |
| **Idempotency-Key middleware opt-in per endpoint (Q-OPEN-7)** | Wired only on POST `/api/v1/watchlists` + POST `/api/v1/digests`. Broadening to other POST endpoints (`/api/v1/process`, `/api/v1/export`, …) is intentionally deferred. | Future PR if production usage shows broader transient-retry pain. ADR 0009 already prescribes the pattern. |
| **idempotency_keys schema `UNIQUE(key)` (not composite)** | PK is `key` alone (migration `f1a2b3c4d5e6`, commit 1/4 — locked, not amend-able per AGENTS.md § Hard rules). Cross-user same-key collisions degrade gracefully (security invariant «no cross-user cache leakage» holds; only second user loses retry-cache benefit). | If production tracking shows non-trivial cross-user `Idempotency-Key` collisions (low expected rate — clients typically use UUIDv4), file as a follow-up to migrate to composite PK in a future schema sprint. |
| **MCP / Bot / CLI surfaces** | No HTTP header equivalent of `Idempotency-Key`. Service-layer natural-key upsert (Option A from ADR 0009) is the sole protection. Adequate for these surfaces (no transient-retry concern equivalent to HTTP timeout). | n/a (architecturally complete). |

## 4a. Open items (post-watch, carry to next sprints)

| # | Item | Class | Recommended timing | Tracking |
|---|---|---|---|---|
| 1 | **`tg_pipeline_trigger_total{surface=mcp\|bot}` series structurally unreachable** — bot + MCP both proxy through HTTP `POST /api/v1/pipeline/trigger`, API entry point hardcodes `surface=api` at counter-increment site. Originating surface not propagated. | Architectural observability gap | Future observability sprint (ADR-class — header propagation contract vs counter-registration refactor). Bundle with surface-aware structlog request_id propagation if that lands first. | `WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6.2; `WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict — Open items #1 |
| 2 | **BUG-025** (bot `unsubscribe_watchlist` UUID validation) | Bot UX (Medium) | Next bot-side touch; bundle with TD-bot-confirm-coverage-completeness if that lands first | `BUG_LOG.md` § BUG-025 |
| 3 | **BUG-026** (bot standalone-UUID continuation context) | Bot UX (Low; structural analogue to BUG-011) | Bundle with BUG-025 (same prompt v1.5.0 + same `prompts/bot.yaml` touch). Option A prompt-only first; Option B FSM-extension if A insufficient. | `BUG_LOG.md` § BUG-026 |
| 4 | **BUG-027** (ambiguous «уже неактивен» wording — service-layer typed return) | Service UX (Low; idempotency class) | Bundle with BUG-022 idempotency-policy follow-up when ADR 0009 next iteration lands | `BUG_LOG.md` § BUG-027 |
| 5 | **BUG-028 (NEW, surfaced by this watch)** — digest cron `PromptLoader(prompts_dir=str(settings.prompts_dir))` resolves to literal path `None/digest.yaml` → daily delivery fails silently | Scheduler (High — 100% delivery failure for active digest subs while `PROMPTS_DIR` env unset) | **Hotfix PR before next 09:00 MSK cron tick** (i.e. before `2026-05-24T06:00:00Z`). Recommended branch: `fix/bug-028-digest-cron-prompt-loader`. Layer A (scheduler_service.py guard) + Layer D (docker-compose env). **Immediate operational workaround** = `PROMPTS_DIR=/app/prompts` env on `tg_parser_bot` + restart, no rebuild. | `BUG_LOG.md` § BUG-028; `WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict — Open items #3 |
| 6 | **Compose-integration CI test backlog** — `@compose_only` marker in tree, harness exists, no GH Actions job runs them. BUG-028 closure plan (digest_task integration test) + §1 surface-label regression coverage both belong here. | CI infra | Separate PR after Wave 1 step 4. Tracked in [`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md` § Open items #3](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md). | Handoff doc + this row |
| 7 | **Anthropic quota one-time exhaustion (resolved)** — `ask_question` + 942 `anthropic_billing_block_processing` events at T+12h; user topped up balance; retry at T+15h45 succeeded (`claude-sonnet-4-20250514`, 200 OK). External resource issue, not a pipeline defect. | External resource / operational note | None (resolved). Future enhancement: fallback-provider policy for RAG `ask_question` on `credit_balance_too_low` (Lessons learned #4). | `WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` § 7 T+12h + T+15h45 rows |

## 5. Cross-references

| Document | Зачем |
|---|---|
| Sprint prompt | [`docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md) — locked decisions Q1–Q9 + acceptance criteria. |
| Merge PR #89 | https://github.com/AlexEfimov/TG_parser/pull/89 — `a30abd5` |
| Deploy + watch | [`WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md), [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) |
| Step 3.1 planning | [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md), ADR 0007 Accepted |
| ADR 0009 (Accepted) | [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) — Option C hybrid (service-layer + HTTP header). |
| ADR 0008 (Draft) | [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — target model; chat_id-only for this sprint, polymorphic deferred. |
| CHANGELOG | [`CHANGELOG.md`](../../CHANGELOG.md) — `[Unreleased]` § «Wave 1 step 3 — Surface Parity» consolidates all 4 commits. |
| USER_GUIDE | [`docs/USER_GUIDE.md`](../USER_GUIDE.md) — new «HTTP API — Watchlist + Digest» section. |
| MCP_AGENT_GUIDE | [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) — REST table + parity note. |
| Wave 1 step 2 DONE marker (template) | [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) — structural mirror for the post-watch update. |
| Wave 1 step 1 DONE marker | [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) — earliest precedent. |

## 6. Lessons learned

_(authored 2026-05-23 at closure; mirror Wave 1 step 2 precedent pattern)_

1. **Latent service-layer bugs hide behind sparse cron schedules.** BUG-028 (digest cron `PromptLoader(prompts_dir=str(None))`) has been broken since 2026-04-19 (F6 landing, ~5 weeks) but only surfaced when (a) at least one active `digest_subscriptions` row existed, (b) its cron tick landed inside a window when someone was watching logs. The bug is a 2-line type-coercion footgun (`str(None) == "None"`). **Takeaway:** include daily-cron deterministic execution in compose-CI (a `pytest -m compose_only` job that runs scheduler ticks in <1s using a frozen time-clock fixture would have caught this — backlog item, see Open Items #4). Bundle naturally with §1 surface-label test.

2. **Bot UX cleanups expose write-tool input validation gaps that read-tool tests never reach.** BUG-025 (name-vs-UUID validation) + BUG-026 (standalone-UUID continuation context) + BUG-027 («уже неактивен» wording) all came from a single 25-minute bot dialog session where the user attempted natural-language cleanup of leftover smoke watchlists. **Takeaway:** every new write-tool that accepts a UUID-typed argument should ship with a parametrized test for ≥ 5 invalid-input forms (name, partial UUID, integer-as-string, whitespace, alphanumeric collision) — closure plan in BUG-025 § «Why CI didn't catch». Symmetric coverage for all `unsubscribe_*` / `delete_*` / `remove_*` executors.

3. **Architectural counter-site labels need surface-aware propagation.** `tg_pipeline_trigger_total{surface=...}` was designed to differentiate api/mcp/bot origins, but bot and MCP both proxy through HTTP `POST /api/v1/pipeline/trigger`, and the counter increments at the API entry point with hardcoded `surface=api`. Result: `surface=mcp` and `surface=bot` time-series are structurally unreachable. **Takeaway:** any future Prometheus metric that wants per-surface labels needs either (a) header-propagation contract (e.g. `X-Origin-Surface: bot`) honored by the API counter, OR (b) the originating surface (bot/MCP wrapper) must increment its own pre-dispatch counter. ADR-class architectural decision; bundle with future observability sprint.

4. **Anthropic quota is a single-point-of-failure for processing AND RAG.** T+12h `ask_question` failure + 942 `anthropic_billing_block_processing` events during topicization both stemmed from one billing-balance exhaustion. Not a regression, but the impact radius was wider than expected (RAG `ask_question` + scheduled processing for 6 channels simultaneously affected). **Takeaway:** fallback policy for `ask_question` to a secondary provider on `credit_balance_too_low` (Gemini already used for bot; Ollama dev-only) would have kept the RAG surface alive while billing was restored. Track as informational note; not in this sprint scope.

5. **Early closure timing is acceptable when state is provably frozen.** T+22h09m vs nominal T+24h was 1h17m early; rationale was «all artifacts cleaned, hard cut-off T+15h45 passed, no further write traffic planned» (documented in § 3 caveat). The Prometheus `query_range` with future END handled gracefully (returned partial data 89/96 buckets through `now`); idempotency counters frozen for ~5h before closure (no T+15h45 → T+22h09 write traffic). **Takeaway:** future watches can confidently close 1-2h early once cleanup completes AND post-cleanup quiet period of ≥ 1h confirms counter stability; risk of last-hour regression is asymptotically small. Document the criterion in next watch sprint's runbook.

## 7. Pre-next-step

**Wave 1 step 3.1 — MCP dispatch (ADR 0007 Accepted):** [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md) — closes BUG-015, ENH-1, ENH-2, O-3. **Can start in parallel** with step 3 24h watch.

**Wave 1 step 4 — Shareable Digest** — after step 3 watch GREEN + step 3.1 execution.

Recommended sequence (updated 2026-05-22):

```
PR #89 merged (a30abd5)
  ↓
Deploy + dedupe + migration (DONE 2026-05-22)
  ↓
24h watch OPEN → close → finalize this DONE marker § 2–3, § 6
  ∥ (parallel)
Wave 1 step 3.1 execution (START_PROMPT_SPRINT_WAVE1_STEP3_1)
  ↓
Wave 1 step 4 planning sub-session (~0.3 session) —
  read PARITY_DECISION_TRACKING.md § 3 (shareable digest signals + O-1/O-2),
  ADR 0008 § Options (polymorphic target promotion?),
  Wave 1 step 4 scope refinement
  ↓
Wave 1 step 4 sprint (Shareable Digest — channel-publish target,
  shareable links, audience activation A2 «Curator»)
```

Wave 1 step 3 sets up the prerequisites for shareable digests by establishing:

* HTTP API surface that downstream sharing tooling can consume.
* `workspace_id` scoping across both subscribe-tools.
* `Idempotency-Key` middleware reusable for any future POST that involves shareable-link generation (per ADR 0009 generalisation note).
* Natural-key idempotency contract on `digest_subscriptions` — guarantees that batched share invitations (potential Wave 1 step 4 surface) don't duplicate rows.

---

## Appendix — Sprint metrics (final, post-watch)

| Metric | Value | Source |
|---|---|---|
| Commits (step 3 sprint) | 4 (atomic): `56e65e2`, `6efb20b`, `0e450eb`, `5b828cf` | Squash SHAs in § 1 table |
| Step 3.1 deploy | `b875faf` (PR #90, ADR 0007 Accepted — MCP HTTP dispatch) | Deployed 2026-05-22T14:01:40Z |
| Follow-ups deploy | `d143e5d` (PR #91 — idempotency replay normalization + compose harness + tests) | Deployed 2026-05-22T17:42:42Z |
| Final prod HEAD at closure | `d143e5d` (unchanged 16h+ from follow-ups deploy through closure) | `docker inspect` StartedAt all 3 containers |
| Pytest baseline (default) | 2195 / 311 / 0 | Handoff `816661d` post-`d143e5d` |
| Pytest baseline (TEST_POSTGRES=1) | 2499 / 9 / 0 | Handoff `816661d` post-`d143e5d` |
| New Prometheus metrics | 2 (`tg_idempotency_keys_hit_total{result}`, `tg_idempotency_keys_table_size`) | Commit 4/4 (`5b828cf`); 24h watch values: hit=4, miss=4, mismatch=3, table_size{api}=5 |
| New scheduler task | 1 (`idempotency_keys_cleanup`, cron `0 * * * *`) | Commit 4/4; fired hourly through 22 ticks observed by closure |
| New ADR transitions | 2 (ADR 0009 Draft → Accepted; ADR 0007 step 3.1 Accepted) | Sprint `5b828cf` + step 3.1 `b875faf` |
| Migrations | 1 (`f1a2b3c4d5e6`, commit 1/4 — `idempotency_keys` table + dedupe constraints on `watch_interests` / `digest_subscriptions`) | Migration runtime test passed pre-merge + applied to prod 2026-05-22 |
| 24h watch verdict | **GREEN** (T+22h09m closure, 0/4 GREEN criteria failed; 5 Open items, none blocking — see § 4a) | [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) |
| Bugs surfaced by watch (new) | 4 (BUG-025, BUG-026, BUG-027 bot UX; BUG-028 digest cron scheduler) | All pre-existing, none are step 3 regressions per § 3 adjudication |
| Regressions introduced by step 3 | **0** | § 3 bug-class adjudication table |
