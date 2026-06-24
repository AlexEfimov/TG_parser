# START PROMPT — Break handoff after α2 deploy + BUG-064 filing

> **Status:** `ACTIVE` — resume point after operator break (~2026-06-25).  
> **Назначение:** self-contained промпт для следующей сессии. α2 seed-map extend **DEPLOYED to prod** (`284436c`); root-cause **BUG-064** found & filed (`32c7ac9`). Next session = **BUG-064 Option A fix-first**, then restart the 7-day ADR-0016 Phase-0 window.

| Метаданные | Значение |
|---|---|
| **Дата handoff** | 2026-06-25 (~01:20 UTC+4) |
| **Wave** | 1.5 operational dogfooding (active) |
| **Prod HEAD (code)** | `284436c` (α2 deploy; HEAD 339940e→284436c, all services healthy, live-code verified) |
| **Docs tip (local==GitHub)** | `32c7ac9` (docs-only `6eded89`/`32c7ac9` are **NOT deployed**) |
| **Previous prod (code)** | `339940e` (Anthropic empty-content guard) |
| **Prior handoff** | [`START_PROMPT_BREAK_2026-06-20.md`](START_PROMPT_BREAK_2026-06-20.md) |
| **Living tracker** | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §11 |

---

## §1 — TL;DR

α2 seed-map extend (priority #1 from prior handoff) **DONE → DEPLOYED** (`284436c`): 5 GLP-1 clusters in `_ALIAS_TO_CANONICAL` (liraglutide / orforglipron / retatrutide / mazdutide / dulaglutide + brand/RU). Post-deploy uncapped `backfill_watchlist(dry_run=true)` on GLP-1 interest `9f23fd49` → would_match=249, **Δ=0 vs baseline — EXPECTED** (interest carries only `лираглутид` of the 5; no brand-only docs above threshold 0.45 in corpus). RESUMMARIZE_LLM pin — investigated, **NOT needed** (resummarize=anthropic/claude-sonnet-4-6, llm_error=0/96h, no refusals). Dogfood DF-1/2/3 filed (`6eded89`). **Root-cause found & filed: BUG-064** (`32c7ac9`) — near-dup observer **emits 0 samples**: message embeddings never produced before the hook (observer wiring-gap). T2 ~06-26 gate is **void / not achievable**. **Agreed plan: fix-first** → BUG-064 Option A → deploy → THEN the genuine 7-day Phase-0 window starts. Earliest realistic ADR-0016 gate ≈ **2026-07-04/05** (folds into review #2).

---

## §2 — What was done this session (2026-06-25)

| Item | Outcome |
|---|---|
| **α2 seed-map extend** | Implemented (5 GLP-1 clusters in `_ALIAS_TO_CANONICAL`) → self-reviewed READY → committed `284436c` → **deployed to prod** (HEAD 339940e→284436c, all services healthy, live-code verified) |
| **α2 post-deploy verify** | Uncapped `backfill_watchlist(dry_run=true)` on GLP-1 interest `9f23fd49` → would_match=249, **Δ=0 vs baseline = EXPECTED** (interest keywords only `лираглутид`; brand-only docs above threshold 0.45 don't exist in corpus) |
| **RESUMMARIZE_LLM pin** | Investigated → **NOT needed** (resummarize=anthropic/claude-sonnet-4-6; llm_error=0/96h; no recurring refusals). Sonnet default stays |
| **Dogfood logging** | DF-1/DF-2/DF-3 filed in [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) (`6eded89`) — closes prior γ3 "0 tagged entries" gap |
| **T2 sanity** | Near-dup gate metric `tg_dedup_near_duplicates_detected_total` still **0 samples** (same as 06-20) |
| **Root-cause: BUG-064** | Filed (`32c7ac9`) — near-dup observer wiring-gap (see §3 + §6) |

### Key decisions made this session

- **T2 formal gate ~06-26 is NOT achievable; the "wait 7 days" framing is void** — under current code the 7-day window accrues ~0 gate-valid samples (the observer cannot fire). "Fix now vs wait 7d" is a **false dichotomy**.
- **Agreed plan: fix-first.** Do BUG-064 Option A fix → deploy → THEN the 7-day Phase-0 observation window genuinely starts → THEN the ADR-0016 Phase-1 3-way decision (build / Rejected-rate-below-5% / extend) is data-grounded.
- The fix is a **bugfix-to-already-deployed Phase-0 observability**, NOT new Wave 2 feature work → it does **not** violate "no Wave 2 until DP exit" (Phase 1 / actual dedup remains gated = the real Wave 2 commitment).

---

## §3 — Current prod state

```text
git rev-parse --short HEAD   # docs tip 32c7ac9; prod CODE tip 284436c
```

| Component | State |
|---|---|
| **Prod SHA (code)** | `284436c` — `feat(watchlist): extend α2 seed-map with 5 GLP-1 molecule clusters` (DEPLOYED; all services healthy) |
| **Docs tip (un-deployed)** | `32c7ac9` (BUG-064 entry), `6eded89` (DF-1..3) — docs-only, NOT on prod |
| **α2 seed-map** | 5 GLP-1 clusters live; backfill Δ=0 EXPECTED (see §2) |
| **Resummarize LLM** | Default **anthropic/claude-sonnet-4-6**; pin not needed (llm_error=0/96h) |
| **T2 Phase-0 observer** | Deployed 2026-06-19; **0 Prometheus samples** — root-caused as **BUG-064** (observer wiring-gap), NOT a transient |
| **Decision Point** | 0/0/0 (2A/2B/2C); not triggered — continue dogfooding |

---

## §4 — Do NOT reopen

| Item | Reason |
|---|---|
| **α2 seed-map** | **DONE & deployed** (`284436c`) — do NOT re-extend the seed map without a new GO |
| **BUG-008 close** | By-design `open`; H1 fixed; H3 transport external |
| **D2 scoring formula** | Deferred, ADR-gated |
| **Wave 2 direction commit** | DP matrix 0/0/0 → continue dogfooding |
| **RxNorm / general FTS synonymy** | Out of α2 scope; seed-map curated only |
| **Option B (decouple near-dup hook)** | NOT required — observer is a no-op without new docs (early-return); decoupling adds churn, no samples |

---

## §5 — Next actions when back (~2026-06-25+)

### Priority stack

1. **BUG-064 Option A fix (priority #1).** Sequence `run_incremental_embedding(new_doc_refs)` **before** `run_near_duplicate_check_for_channel` inside the existing `if new_doc_refs:` block in `scheduler_service.py` `_process_source`. Option B (decouple hook from `new_doc_refs`) is **NOT** required. ~3–6 LOC in one file + one new scheduler-wiring test; risk **low** (batched embeds capped 100/tick; `run_embedding(force=False)` skips already-embedded → no meaningful double-embedding).
2. **Test.** Extend/leverage [`tests/test_near_duplicate_observe.py`](../../tests/test_near_duplicate_observe.py); add a scheduler-wiring test asserting message embeddings exist **before** the near-dup call (observer reaches `checked > 0`, `skipped_no_embedding == 0`).
3. **Deploy** via standard VPS path ([`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)): `ssh -p 2296 user@212.72.189.15` → `git pull` → `docker compose --profile bot build/up tg_parser mcp tg_bot`. **No migration.**
4. **Start the 7d Phase-0 watch** post-deploy; sanity-peek `tg_dedup_near_duplicates_detected_total` accumulating.
5. **ADR-0016 Phase-1 3-way decision** at review #2 (~07-04), using Phase-0 `dimension`-distribution (intra/cross), threshold 0.92 calibration, window 50.

### Date-gated calendar

| Date | Action |
|---|---|
| ~2026-06-25+ (next session) | BUG-064 Option A fix → deploy → start 7d Phase-0 watch |
| ~2026-07-02 | Earliest possible gate if fix deployed today (unlikely) |
| ~2026-07-04 | Wave 1.5 review #2 (period 2) + realistic ADR-0016 Phase-1 decision point |
| ~2026-07-04/05 | Earliest realistic ADR-0016 gate (fix-deploy + 7d, + `for: 6h` dwell) |
| 2026-07-06 | Market scan deep dive deadline if still skipped (PLAN §10 R-6) |

---

## §6 — BUG-064 Option A quick-reference (next-session priority #1)

**Symptom:** `tg_dedup_near_duplicates_detected_total` = 0 samples since the 2026-06-19 deploy → ADR-0016 Phase-1 gate has no data.

**Root cause (code-traced):** Inside the `if new_doc_refs:` block the scheduler runs `run_topic_embedding(...)` — **topic-cards only** (`scheduler_service.py:243–245`) — NOT message embeddings. The observer (the near-dup hook at `scheduler_service.py:268–291`) loads per-doc message embeddings; when absent it does `skipped += 1; continue` and increments NO metric. `run_incremental_embedding(doc_refs)` already exists for exactly this purpose (`embedding_service.py:191–242`) but is **UNWIRED**. Observer is forward-only; all manual paths (`trigger_pipeline` / `tg-parser embed` / `scheduler run-once --source` / `backfill_watchlist`) bypass it. **Observe-only → no user impact / no data corruption.**

**Fix (Option A — minimal):**
1. In `tg_parser/services/scheduler_service.py` `_process_source`, insert `await run_incremental_embedding(new_doc_refs)` immediately **before** the `run_near_duplicate_check_for_channel(...)` call (the `:268–291` hook), still inside the existing `if new_doc_refs:` block.
2. Wrap so a non-billing embed failure does not pollute `stage_errors` (post-processing-must-not-lie contract — mirror the existing hook's `try/except`).
3. Add a scheduler-wiring test (see §5 #2).
4. Deploy (§5 #3); **the 7-day window restarts from zero at deploy time** (counter accrues forward only).

> Full decision-ready scoping (Option A vs A+B, effort/risk/test/rollout, earliest gate date) is in [`BUG_LOG.md`](BUG_LOG.md) → **BUG-064 → Fix assessment** sub-section.

---

## §7 — Pre-flight on resume

```bash
cd /Users/alexanderefimov/TG_parser
git fetch origin && git status
git log --oneline -5
# Expect docs tip 32c7ac9 (or later); prod CODE tip 284436c (α2)

# Optional prod sanity (MCP):
# get_pipeline_status
# get_llm_config        # confirm resummarize=anthropic/claude-sonnet-4-6
```

---

## §8 — Key links

| Doc | Path |
|---|---|
| Prior handoff | [`START_PROMPT_BREAK_2026-06-20.md`](START_PROMPT_BREAK_2026-06-20.md) |
| BUG-064 + Fix assessment | [`BUG_LOG.md`](BUG_LOG.md) (BUG-064) |
| ADR-0016 (gate blocked) | [`docs/adr/0016-near-duplicate-dedup.md`](../adr/0016-near-duplicate-dedup.md) |
| Deploy runbook | [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) |
| T1/T2 gate | [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4 (T1/T2) |
| Wave 1.5 plan + §11 log | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §11 |
| Dogfood DF-1..3 | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) |
| Seed-map code | `tg_parser/services/watchlist_tokenizer.py` `_ALIAS_TO_CANONICAL` |

### Session commit refs (2026-06-25)

| SHA | Summary | Deployed? |
|---|---|---|
| `284436c` | feat(watchlist): extend α2 seed-map with 5 GLP-1 molecule clusters | ✅ **prod code tip** |
| `6eded89` | docs(notes): log Wave 1.5 dogfood friction (DF-1..DF-3) | docs-only |
| `32c7ac9` | docs(notes): file BUG-064 — near-dup observer wiring-gap (ADR-0016 gate blocker) | docs-only (**docs tip**) |

---

> **Reminder:** Wave 1.5 = habit, not sprint. The BUG-064 fix is a bugfix-to-deployed-Phase-0-observability, NOT Wave 2 feature work — Phase 1 / actual dedup stays gated. Commit only on explicit user request ([`AGENTS.md`](../../AGENTS.md)).
