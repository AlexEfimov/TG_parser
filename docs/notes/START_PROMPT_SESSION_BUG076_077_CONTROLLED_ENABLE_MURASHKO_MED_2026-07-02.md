# START_PROMPT — BUG-076/077: CONTROLLED FIRST EXERCISE of checkpointed full-topicization resume on `murashko_med`

**Created:** 2026-07-02. This is an **OPERATIONAL RUNBOOK-STYLE** start-prompt (executing a controlled production exercise), **NOT** a code-implementation start-prompt. No code should need to change to complete this session — this is a settings-flip + resume + watch exercise.
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**Local HEAD == origin/main HEAD == prod HEAD:** `4f8a326` (`fix(topicization): close residual token-leak surfaces in checkpointed full topicization (BUG-077)`), on top of `596fe30` (BUG-076 checkpoint/resume feature) and `b7285d7` (tip of the BUG-071→075 token-burn hardening chain). **Verify before doing anything else** — see §1 pre-flight.
**Deployed status (verified in a prior session step, re-verify in §1):** prod host reachable via `ssh prod` (`212.72.189.15:2296`), app dir `/home/user/TG_parser`, all 6 default-profile services healthy, Prometheus force-recreated with the BUG-077 alert group loaded, `topicization_full_resume_enabled` confirmed `False` at runtime, `murashko_med` confirmed `status='paused'`.
**Rollback refs (verified with `git log`):**
- `b7285d7` — **the correct target for a "BUG-076/077 misbehaves" rollback.** BUG-075 tip; the last code commit before BUG-076 (`596fe30`). Reverting to it removes BUG-076 **and** BUG-077 code (the checkpoint/resume feature + its hardening) while **keeping** BUG-071..075 (truncation/shrink-split/cooldown/reconcile/R1) fully intact. Use this if the checkpoint/resume machinery itself needs to disappear but the rest of the token-burn hardening chain should stay.
- `23764b7` — **the BUG-072 commit itself** (`fix(topicization): add non-blocking per-channel advisory lock … (BUG-072)`). Checking it out **keeps BUG-071/072** and **removes BUG-073→077** (advisory locks on processing/incremental, `repair_json`, the reconcile hook, checkpoint/resume + hardening). Use only to strip the entire BUG-073→077 chain back to the bare BUG-072 baseline. It does **NOT** revert BUG-071 or BUG-072, and there is **no single "revert BUG-071..075" ref** in this range — so it is the wrong target for a BUG-076/077-specific problem (that is `b7285d7`, above).
- (Not a rollback target) `596fe30` — has BUG-076 but **not** the BUG-077 F1/F4 enable-blocking hardening. Do not roll back to this commit while the feature could be enabled — it reintroduces the unbounded no-progress drip (F1) and the reconcile double-spend (F4).
**Status:** BUG-076/077 code is **live in prod** but the resume feature is **DARK** (`topicization_full_resume_enabled=False`). This session's goal is the **FIRST controlled enable** — a small-budget, closely-watched exercise of the exact scenario that motivated the fix (`murashko_med`, 0 cards, ~15.5K-doc backlog).

> **Read in order before touching anything:**
> 1. [`DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md`](DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md) §10 "Rollout / roll-forward sketch" — the controlled-first-exercise sketch and roll-forward criteria this session executes.
> 2. [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md) in full, especially §10 "BUG-077 (F7) — re-enable hygiene" (the pre-enable checkpoint-hygiene SQL) and the kill-switch table in §8.
> 3. The `### BUG-076` and `### BUG-077` rows in [`BUG_LOG.md`](BUG_LOG.md) (BUG-077 is logged as its own row, `Status: in-progress`, linked to BUG-076).
> 4. [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (repo root) — deploy/rollback procedure, in case a rollback is needed mid-exercise.
> 5. For deep background on *why* the feature exists and *how* it was built: [`START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md`](START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md) and [`START_PROMPT_SESSION_BUG076_TOKENLEAK_HARDENING_IMPL_2026-07-02.md`](START_PROMPT_SESSION_BUG076_TOKENLEAK_HARDENING_IMPL_2026-07-02.md). Not required to execute this session, but essential if anything looks wrong and you need to understand the code, not just the runbook.

---

## ⛔ OPERATIONAL WARNINGS — READ FIRST

1. **This is a PRODUCTION-AFFECTING operation on a real channel.** `murashko_med`'s last full re-topicization burned **~6.6M Sonnet tokens for ZERO persisted cards** (the original BUG-076 incident, 2026-07-01) because the legacy monolithic path crashed at the final merge and discarded everything. The fix makes that scenario recoverable, but it does **not** make tokens free — this exercise will spend real money. Proceed **deliberately, one step at a time**, with **explicit verification between steps**. Do not batch steps together to save time.
2. **The single most dangerous mistake is resuming `murashko_med` while `topicization_full_resume_enabled` is not actually live in the running process.** The primary burn-bound for this exercise is the chunked path itself: enabling the flag switches the full path to chunked with `topicization_full_max_chunks_per_invocation=1`, so each scheduler tick runs at most **one chunk** (~374K tokens, §4a) then halts durably. If the flag is NOT actually live in the running process (e.g. the `.env` edit didn't take, or the container restart didn't apply it) and you resume the channel anyway, the 0-card `should_reescalate` path runs the **legacy monolithic all-or-nothing** run and recreates the original ~6.6M-token incident. This is why §4b verifies the flag is live in the running process **BEFORE** §4c resumes the channel — do not skip that verification. Treat "resumed with the flag not actually live" — **not** "budget=0" — as the catastrophic case.
3. **Set the token budget too — but understand it is a secondary, auditable safety net at `max_chunks_per_invocation=1`, not the primary throttle.** `topicization_full_run_token_budget` defaults to `0` (disabled). It is enforced only at **chunk boundaries** and cannot interrupt an in-flight chunk; at `max_chunks_per_invocation=1` each tick already runs at most one chunk and returns due to the chunk cap regardless of the budget — so budget=`0` **with the flag actually on** does **not** recreate the original unbounded incident. The budget only becomes the primary throttle if `max_chunks_per_invocation` is later raised (§9). Still set it (§4a) as the explicit, auditable "we chose a number and it held" signal. **Order matters: budget (§4a) → flag + verify-live (§4b) → resume (§4c).**
4. **Know the instant kill-switch before you start** (full detail in §7): `pause_channel(channel_id="murashko_med")` (MCP tool) or the raw-SQL fallback re-pauses the channel and the scheduler skips it on the next tick — this is the fastest way to stop new spend. It does **not** undo tokens already spent on an in-flight chunk (a chunk in flight cannot be interrupted — only the *next* chunk is prevented).
5. **`topicization_full_resume_enabled` is a GLOBAL flag, not per-channel.** The instant you flip it on, the chunked path applies to **every** active channel and the scheduler resume driver (`scheduler_service.py`) starts consulting the checkpoint marker for every active channel, every tick — not just `murashko_med`. Any *other* active channel that is 0-card + backlogged will run the first-time-live chunked path on its next `should_reescalate` tick, possibly concurrently with `murashko_med`. This is why §1's pre-flight checks both for **stray live checkpoints on other channels** (§1 item 5) **and** for **other active 0-card/backlog channels** (§1 item 5b) before enabling.
6. **If anything looks anomalous — STOP and re-pause immediately. Do not "wait and see."** Anomalous means any of: runaway spend (tokens climbing far faster than the §6 arithmetic predicts — in particular, a single invocation spending well past one chunk's worth without the chunk committing and the invocation returning, which would mean the `max_chunks_per_invocation=1` cap is not halting the tick), no chunks persisting (`tg_parser_topicization_full_run_chunks{kind="done"}` gauge not advancing after a tick where tokens clearly rose), or storm-like behavior (any BUG-071..077 alert firing, `escalating to full topicization` logging repeatedly without a cooldown marker). See §5 for the full watch list and §7 for the kill-switch.
7. **AGENTS.md conventions apply.** No `git commit` without an explicit user request (nothing in this runbook requires a commit — it is a settings + DB + MCP-tool exercise). Do not create/edit `docs/methodology/**`. Do not edit `pyproject.toml` / `requirements.txt`. Accepted ADRs (`docs/adr/`) and JSON Schemas (`docs/contracts/`) are binding.

---

## TL;DR

The BUG-076/077 fix makes FULL topicization crash-safe, resumable, and budget-bounded: the corpus is chunked (default 20 batches ≈ 1000 docs/chunk), each chunk is generated, merged, and **atomically** persisted together with a checkpoint, and a scheduler-driven resume loop carries a partial run to completion across ticks. It ships **dark** behind `topicization_full_resume_enabled=False`; the legacy all-or-nothing path is byte-for-byte unchanged while the flag is off.

This session performs the **first real-world exercise** of that machinery, on the **exact channel and scenario that motivated the fix**: `murashko_med`, currently `status='paused'`, 0 topic cards, ~15.5K-doc backlog. The plan is: enable the flag (which switches the full path to the chunked, one-chunk-per-tick machinery — with `max_chunks_per_invocation=1` the very first tick halts-and-persists after ~one chunk rather than attempting the whole ~6M-token backlog in one shot), set a **small, conservative token budget** as a secondary auditable safety net, **verify the flag is actually live in the running process**, resume the channel, and then **watch it converge over multiple ticks** — verifying at each step that chunks are landing durably, tokens are visible, `topics_created` is rising, and none of the BUG-071..077 safety nets (cooldown, circuit-breaker, reconcile gate, no-storm) are tripping in an unexpected way.

This is a **planning-and-execution** runbook: it does not require writing or reviewing code. If anything in the observed behavior contradicts what the code is documented to do, STOP and treat it as a new bug, not something to work around live.

---

## 1. Pre-flight checklist — verify BEFORE touching anything

Run every item below and get a clean answer before proceeding to §4 (the enable sequence). Do not proceed on an assumption — confirm.

1. **Prod HEAD is `4f8a326`:**
   ```bash
   ssh prod "cd /home/user/TG_parser && git rev-parse --short HEAD"
   # expect: 4f8a326
   ssh prod "cd /home/user/TG_parser && docker compose ps"
   # expect: all default-profile services healthy (postgres, tg_parser, mcp, prometheus, grafana)
   ```
2. **`topicization_full_resume_enabled` is currently `False` at runtime:**
   ```bash
   ssh prod "cd /home/user/TG_parser && docker compose exec tg_parser python -c \
     'from tg_parser.config import settings; print(settings.topicization_full_resume_enabled)'"
   # expect: False
   ```
3. **`murashko_med` is currently `status='paused'`:**
   ```bash
   ssh prod "cd /home/user/TG_parser && docker compose exec postgres psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \
     \"SELECT source_id, channel_id, status FROM sources WHERE channel_id = 'murashko_med' OR source_id = 'murashko_med';\""
   # expect: status = 'paused'
   ```
   (Use whichever of `source_id`/`channel_id` actually matches — `sources.source_id` is the primary key; for a plain single-source channel the two are normally identical, but confirm rather than assume.)
4. **Prometheus/Grafana are healthy and the BUG-077 alert group is loaded:**
   ```bash
   ssh prod "curl -s localhost:9090/api/v1/rules | python3 -m json.tool | grep -A2 tg_parser_bug077_full_run_hardening"
   # expect: 3 rules — TopicizationFullRunResumeNoProgress, TopicizationFullRunChunkFailedSustained, TopicizationFullRunCircuitOpen — all state=inactive (armed, not firing)
   ssh prod "curl -s -o /dev/null -w '%{http_code}' http://localhost:3001/api/health"
   # Grafana is on host port 3001 (not 3000) per the watch runbook §1 — expect 200
   ```
5. **No other channel has a live full-run checkpoint** (the flag is global — enabling it makes the resume driver consult every channel's marker, every tick):
   ```bash
   ssh prod "cd /home/user/TG_parser && docker compose exec postgres psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \
     \"SELECT source_ref, channel_id, attempts AS chunks_done, last_attempt_at, error_details_json FROM processing_failures WHERE source_ref LIKE 'topicization:full_checkpoint:%';\""
   ```
   Expected: either zero rows, or only a (stale, pre-exercise) row for `murashko_med` itself. If a row exists for a **different** channel, STOP and inspect it (BUG-077 F7 hygiene, runbook §10) before enabling anything — an unexpected channel could start resuming the instant the flag flips.

   **5b. No other active 0-card channel with a backlog.** The global flag makes the chunked path apply to **every** active channel, so any active channel that is 0-card + backlogged will run the first-time-live chunked path on its next `should_reescalate` tick — possibly concurrently with `murashko_med` (up to the scheduler's max concurrent sources, `scheduler_max_concurrent_sources`). Enumerate active channels and their topic-card counts; expect **only** `murashko_med` to be 0-card + large-backlog, and investigate/pause any other active 0-card channel before enabling. **Verified schema note:** `topic_cards` has **no `channel_id` column** — a card's channel(s) are stored in its `sources_json` **JSON array**, so the count uses the jsonb array-membership operator `?` (this mirrors `SATopicCardRepo.count_by_channel_grouped`, which unnests `sources_json::jsonb` — `tg_parser/storage/sqlalchemy/topic_card_repo.py:183-190`; the per-channel `list_by_channel` at `:154-167` uses an equivalent `sources_json LIKE '%"<channel>"%'` match):
   ```bash
   ssh prod "cd /home/user/TG_parser && docker compose exec postgres psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \
     \"SELECT s.channel_id, s.status,
         (SELECT count(*) FROM topic_cards tc WHERE tc.sources_json::jsonb ? s.channel_id) AS cards
       FROM sources s
       WHERE s.status = 'active' AND s.deleted_at IS NULL
       ORDER BY cards ASC;\""
   ```
   (The `?` operator tests whether the `sources_json` array contains the channel id as an element — exact membership, no substring false-positives, and no fragile embedded-quote escaping in the nested `ssh`/`psql` string. Any active channel with `cards = 0` and a non-trivial processed-doc backlog is a candidate to pause before enabling.)
6. **Current Anthropic billing balance is sufficient for the planned budget.** `[CONFIRM WITH USER]` — this is the exact trigger that caused the original BUG-076 incident (the balance was exhausted mid-run). There is no MCP tool or repo command to check the live Anthropic balance; this must be checked in the Anthropic console (or wherever billing is tracked) by a human before proceeding. Confirm the balance covers at least the §4a budget with comfortable headroom (the budget is a per-invocation cap enforced at chunk boundaries — see §4a — not a hard ceiling on cumulative spend across ticks).
7. **Record a baseline snapshot** for later comparison (backlog size, current token/topic metrics):
   ```bash
   ssh prod "curl -s http://localhost:8000/metrics | grep -E 'tg_parser_topicization_full_run|tg_parser_topics_created_total\{channel_id=\"murashko_med\"'"
   # expect: the full_run_* series either absent (never emitted) or all zero for murashko_med
   ```

---

## 2. Settings quoted exactly from the repo (do not guess — these are read from `tg_parser/config/settings.py` at HEAD `4f8a326`)

All of these are Pydantic `Settings` fields (`tg_parser/config/settings.py`), loaded once at process start from `.env` (env var name = field name, case-insensitive; e.g. `TOPICIZATION_FULL_RESUME_ENABLED`). **Because `settings = Settings()` is instantiated once at import time, a settings change requires a container restart to take effect — see §4b.**

| Setting | Default | Meaning | BUG |
|---|---|---|---|
| `topicization_full_resume_enabled` | `False` | Master switch. `False` = legacy monolithic full topicization, byte-for-byte unchanged. `True` = chunked, per-chunk-atomic, resumable, budget-aware full topicization + the scheduler resume driver. | BUG-076 |
| `topicization_full_chunk_batches` | `20` | Number of 50-doc generate batches per resumable chunk (~1000 docs/chunk at default). A crash/halt loses at most one chunk. | BUG-076 |
| `topicization_full_max_chunks_per_invocation` | `1` | Max chunks a single invocation processes before returning a benign partial/resumable result (also the per-invocation wall-clock bound — the 1800s scheduler watchdog does **not** wrap the topicization stage). | BUG-076 |
| `topicization_full_run_token_budget` | `0` (disabled) | Per-invocation token budget; the run halts cleanly at the **next chunk boundary** once this invocation's input+output tokens reach it. `0` = disabled/unbounded. Set it first in the enable sequence (§4a), but at `max_chunks_per_invocation=1` it is a **secondary, auditable safety net**, not the primary throttle — see §4a and ⛔ warning 3. | BUG-076 |
| `topicization_full_merge_threshold` | `0.6` | Combined cosine+Jaccard similarity threshold above which two same-channel cards are merged (loser deleted) by the idempotent cross-chunk consolidation pass run after all chunks land. | BUG-076 |
| `topicization_full_resume_noprogress_limit` | `3` | Consecutive no-progress full-run resumes after which the F1 circuit-breaker opens and further resumes are skipped/cooled-down. `0` = breaker disabled (do not disable it for this exercise). | BUG-077 (F1) |
| `topicization_full_resume_noprogress_cooldown_s` | `3600` | Seconds the open no-progress breaker skips resumes before allowing one probe attempt. `0` = hard-open (manual intervention required). | BUG-077 (F1) |

**Do not change** `topicization_full_resume_noprogress_limit` / `_cooldown_s` for this exercise — leave them at their defaults (`3` / `3600`). They are safety nets for a stalled run, not tunables for a first exercise.

---

## 3. Observability — exact metric, alert, and log names (from the repo, HEAD `4f8a326`)

### 3.1 Metrics (`tg_parser/api/metrics.py`)

All of the `TOPICIZATION_FULL_RUN_*` series are emitted **only** on the chunked/resumable path (i.e. only once the flag is `True` and a run is active) — they stay flat/absent while dark.

| Metric | Type | Labels | What it means |
|---|---|---|---|
| `tg_parser_topicization_full_run_tokens_total` | Counter | `channel_id` | Cumulative input+output tokens spent by the resumable full run. Feeds the budget guard + cost dashboard. Emitted post-commit **and** pre-commit on a failed/halted chunk (BUG-077 F9 closed the "drip invisible" gap). |
| `tg_parser_topicization_full_run_chunks` | Gauge | `channel_id`, `kind` (`done`\|`total`) | Live chunk progress. `done == total` just before the checkpoint clears. |
| `tg_parser_topicization_full_run_budget_halt_total` | Counter | `channel_id` | Clean per-invocation token-budget halts (benign — durable + resumed next tick). |
| `tg_parser_topicization_full_run_resume_total` | Counter | `channel_id` | Resume-driver invocations that continued a live checkpoint. A sustained rate with no chunk progress = the F1 drip signature. |
| `tg_parser_topicization_full_run_chunk_failed_total` | Counter | `channel_id`, `reason` (`merge_halt`\|`malformed_merge`\|`empty_after_failure`\|`commit_failed`) | Chunks that halted **without** advancing the checkpoint (BUG-077 F9). Sustained non-zero = the F1 drip signature. |
| `tg_parser_topicization_full_run_noprogress_skip_total` | Counter | `channel_id` | Ticks the F1 circuit-breaker held a resume off (`skipped_reason="noprogress_circuit_open"`). |
| `tg_parser_topics_created_total` (pre-existing) | Counter | `channel_id` | Now wired **per-chunk** into the full path (the original BUG-076 observability gap) — should rise during a productive run, not stay flat until the end. |

### 3.2 Alert groups (`docker/prometheus/alerts.yml`)

**`tg_parser_bug077_full_run_hardening`** (3 rules — the new group for this feature):

| Alert | Expression (sketch) | For | Meaning |
|---|---|---|---|
| `TopicizationFullRunResumeNoProgress` | `resume_total` increase ≥3 in 30m **and** `chunks{kind="done"}` delta == 0 over 30m | 30m | Channel resumed ≥3× without advancing a single chunk — the F1 drip; the breaker should have tripped before this fires. |
| `TopicizationFullRunChunkFailedSustained` | `rate(chunk_failed_total[30m]) > 0` by `channel_id, reason` | 1h | The same chunk keeps failing deterministically without advancing. |
| `TopicizationFullRunCircuitOpen` | `rate(noprogress_skip_total[30m]) > 0` | 1h | The F1 breaker is open — spend is bounded (1 probe/cooldown) but the run is stuck and needs a human. |

**`tg_parser_bug071_topicization`** (6 rules, pre-existing, still relevant): `TopicizationTruncationSpike`, `TopicizationTruncationBurst`, `SonnetCompletionNearCap`, `TopicizationBurnNoProgress`, `TopicizationFailedBatchesHigh`, `AnthropicBillingStillBlocked`.

**`tg_parser_bug075_reconcile_postrefill`** (3 rules, pre-existing, still relevant): `TopicizationDiscoverMarkerWriteFailing`, `TopicizationJsonRepairRetrySpike`, `TopicizationReconcileDiscoverSustained`.

### 3.3 PromQL sketches

```promql
# Full-run chunk progress for murashko_med (watch this rise each tick)
tg_parser_topicization_full_run_chunks{channel_id="murashko_med"}

# Cumulative tokens spent by the resumable run
tg_parser_topicization_full_run_tokens_total{channel_id="murashko_med"}

# Topics created — should rise DURING the run, not stay flat until the end
sum(rate(tg_parser_topics_created_total{channel_id="murashko_med"}[15m]))

# Budget halts — at max_chunks_per_invocation=1 with budget (~450K) > one chunk (~374K),
# expect this to stay ~0 (the per-tick halt is the CHUNK CAP, not the budget). A non-zero
# value means a chunk cost MORE than the budget — worth noting but still a clean, durable halt.
increase(tg_parser_topicization_full_run_budget_halt_total{channel_id="murashko_med"}[1h])

# Resume-without-progress check (the F1 drip signature, matches the alert)
sum(increase(tg_parser_topicization_full_run_resume_total{channel_id="murashko_med"}[30m]))
and
sum(delta(tg_parser_topicization_full_run_chunks{channel_id="murashko_med",kind="done"}[30m])) == 0

# Any non-advancing chunk failures
sum(rate(tg_parser_topicization_full_run_chunk_failed_total{channel_id="murashko_med"}[30m])) by (reason)

# Circuit-breaker open?
increase(tg_parser_topicization_full_run_noprogress_skip_total{channel_id="murashko_med"}[1h])

# Pre-existing storm/burn proxies (BUG-071..075) — must stay clean
sum(rate(tg_parser_llm_truncation_total{channel_id="murashko_med"}[5m])) by (stage)
sum(rate(tg_parser_topicization_failed_batches_total{channel_id="murashko_med"}[15m])) by (stage)
```

### 3.4 Log greps

```bash
# BUG-076: scheduler-side resume-driver failure (log-only, no metric — investigate immediately)
docker compose logs --since 1h tg_parser | grep bug076_full_resume_failed

# BUG-076: clean budget halt (benign). At max_chunks=1 with budget > one chunk, expect ~none
# (the chunk cap ends each tick, not the budget); only appears if a chunk's own cost exceeds the budget.
docker compose logs --since 1h tg_parser | grep topicization_full_run_budget_halt

# BUG-077: finalize-only failure did NOT trip the breaker (benign — free consolidation retry)
docker compose logs --since 1h tg_parser | grep bug077_resume_finalize_failed_no_chunk_breaker_trip

# BUG-077: an internal checkpoint-read abort did NOT trip the breaker (benign — zero-cost)
docker compose logs --since 1h tg_parser | grep bug077_resume_checkpoint_read_aborted_no_chunk_breaker_trip

# BUG-077: reconcile deferred closed on a read error (benign defer, not abandonment)
docker compose logs --since 1h tg_parser | grep bug077_reconcile_gate_read_error_deferring_closed

# skipped_reason values worth grepping for context (locked / noprogress_circuit_open / checkpoint_read_error / full_run_in_progress)
docker compose logs --since 1h tg_parser | grep -E "skipped_reason=(locked|noprogress_circuit_open|checkpoint_read_error|full_run_in_progress)"

# Pre-existing BUG-071/072 storm proxies — must stay clean
docker compose logs --since 1h tg_parser | grep -c "escalating to full topicization"          # expect <=1 for murashko_med at kickoff
docker compose logs --since 1h tg_parser | grep -c "re-escalation skipped (cooldown)"          # benign, expected after kickoff
docker compose logs --since 1h tg_parser | grep -cE "skipped_already_in_flight|deferred_locked" # lock contention, occasional is fine
```

**DB — the checkpoint row itself** (ground truth for chunk progress, corroborates the metrics):
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT source_ref, channel_id, attempts AS chunks_done, last_attempt_at, error_details_json \
 FROM processing_failures WHERE source_ref = 'topicization:full_checkpoint:murashko_med';"
```
`error_details_json` carries `{run_id, planned_refs (or ref hash), chunks_total, chunks_done, batches_done, tokens_spent_cumulative, final_merge_done, last_chunk_at, consecutive_noprogress_resumes, last_noprogress_at, cards_stamped}` — cross-check `chunks_done`/`chunks_total`/`tokens_spent_cumulative` against the Prometheus gauges each time you check in.

---

## 4. The enable sequence (ordered — do not reorder or batch)

### (a) Set a conservative, non-zero `topicization_full_run_token_budget`

**Arithmetic (from the repo + the original incident, `[CONFIRM WITH USER]` on the final number):**
- The original burned run: ~6.6M Sonnet tokens across ~353 batches (BUG_LOG BUG-076 row) → **~18,700 tokens/batch** (back-of-envelope: 6,600,000 / 353).
- `topicization_full_chunk_batches = 20` (default, unchanged for this exercise) → **one chunk ≈ 20 × 18,700 ≈ 374,000 tokens**.
- **How the budget actually behaves — read carefully, it is easy to over-credit it.** The budget is checked **only at chunk boundaries** and **cannot interrupt an in-flight chunk** (a chunk's batches run under a single `asyncio.gather` that cannot be cut off mid-flight). With `topicization_full_max_chunks_per_invocation = 1` (default, unchanged for this exercise) each scheduler tick already runs **at most one chunk** and returns because of the **chunk cap**, not the budget — and since there is no "next chunk" in the same invocation, the budget check has nothing to gate on this tick. So for this exercise the budget **neither bounds a single runaway chunk** (a chunk always completes and persists first) **nor can it "waste a probe"** (there is no second chunk to refuse). It becomes a real throttle only if `max_chunks_per_invocation` is later raised above 1 (§9).
- **Recommendation:** set it to roughly **1–1.5× one chunk's estimated cost, e.g. ~400,000–550,000 tokens**, purely as an **auditable "headroom over one chunk" marker** — a deliberate, stated number that documents "we expected ~374K/chunk and set the guard just above it," and that is already correctly sized should `max_chunks_per_invocation` be raised later. Do **not** rely on it to cap this exercise's spend (the chunk cap does that); do **not** set it *below* one chunk's cost thinking it will halt a chunk early (it won't — the chunk runs to completion regardless, then the budget only matters for a *next* chunk that never comes at `max_chunks=1`). **`[CONFIRM WITH USER]`** — the operator's risk tolerance and the confirmed billing balance (§1 item 6) should set the final figure; do not proceed with a number you invented without the user's explicit sign-off.
- Set it in `.env` on the prod host (`/home/user/TG_parser/.env`):
  ```env
  TOPICIZATION_FULL_RUN_TOKEN_BUDGET=450000
  ```

### (b) Enable `topicization_full_resume_enabled=True`

Settings are read once at process start (`settings = Settings()` module-level singleton in `tg_parser/config/settings.py`) from `.env`, which is bind-mounted read-only into the `tg_parser` container (`./.env:/app/.env:ro` in `docker-compose.yml`). **A settings change therefore requires restarting the `tg_parser` container** — a hot edit of `.env` alone has no effect until restart.

```env
# .env on prod host
TOPICIZATION_FULL_RESUME_ENABLED=true
```

Apply it:
```bash
ssh prod "cd /home/user/TG_parser && docker compose up -d --no-deps tg_parser"
# no image rebuild needed (no code changed) — this only restarts the process to re-read .env
```
**No Prometheus force-recreate is needed for this step** — you are not touching `docker/prometheus/alerts.yml` (that already happened when the BUG-077 group was deployed). Only restart `tg_parser` (and only `tg_parser` — do not restart `mcp`/`postgres`/`prometheus`/`grafana` for this).

**⛔ HARD GATE — this verification MUST pass before you touch §4c.** This is the single most important check in the runbook (⛔ warning 2): if the flag is not actually live in the running process and you resume the channel anyway, the legacy monolithic path recreates the ~6.6M-token incident. Confirm the flag is live **in the running process** (not just written to `.env`):
```bash
ssh prod "cd /home/user/TG_parser && docker compose exec tg_parser python -c \
  'from tg_parser.config import settings; print(settings.topicization_full_resume_enabled, settings.topicization_full_run_token_budget)'"
# expect EXACTLY: True 450000  (or whatever budget you set)
# If it prints `False ...`, the restart did NOT pick up the .env change — STOP.
# Do NOT proceed to §4c (resume) until this prints True. A False here + a resume = the catastrophic case.
```

### (c) Resume `murashko_med`

**Preferred — MCP tool** (per the `user-tg-parser` / `project-0-TG_parser-tg-parser` MCP server tool set):
```
resume_channel(channel_id="murashko_med")
```
This is idempotent, resets `fail_count`/`last_error` if the channel was in `'error'` state, and is the safe path (goes through ownership checks). Confirm the tool's response reports `changed=true` (or `changed=false` only if it was already active — it should not be, per §1 item 3).

**Raw-SQL fallback** (only if the MCP path is unavailable):
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"UPDATE sources SET status = 'active', updated_at = now() WHERE channel_id = 'murashko_med' AND deleted_at IS NULL;"
```
**Caveat:** unlike the MCP `resume_channel` tool, this raw `UPDATE` does **not** reset `fail_count` / `last_error`. That is harmless when the channel is `paused` (which it is, per §1 item 3 — those fields only carry state for a channel in `'error'` status). Prefer the MCP tool regardless. If you ever use the SQL path on a channel that is in `'error'` state, clear the error fields in the same statement (e.g. add `, fail_count = 0, last_error = NULL`) so the resumed channel starts clean.

### (d) No further apply step needed

Steps (a) and (b) already required a `tg_parser` restart to take effect (settings are process-start-only); step (c) is a plain DB write picked up by the scheduler on its next poll (no restart). There is nothing further to "apply" — the scheduler will pick up the resumed, active `murashko_med` on its next tick and (because it now has 0 cards and new docs) `should_reescalate` will fire, kick off chunk 1 of the chunked path, and write the first checkpoint.

---

## 5. What to watch, and how

Watch continuously for at least the first few ticks, then per the cadence in §6. For each tick where you expect a chunk to have run, check **all** of the following together (a single green signal in isolation is not sufficient — cross-check):

1. **Tokens rising per chunk** — `tg_parser_topicization_full_run_tokens_total{channel_id="murashko_med"}` should jump by roughly one chunk's worth (§4a arithmetic) each tick a chunk actually ran.
2. **`chunks{done}` gauge advancing** — `tg_parser_topicization_full_run_chunks{channel_id="murashko_med",kind="done"}` should increase by 1 each successful tick; `kind="total"` should be stable (set once, at plan time) at roughly 16–18 (see §6 arithmetic).
3. **Per-tick halt is the chunk cap, and it halts durably** — at `max_chunks_per_invocation=1` each tick runs one chunk, commits it, then returns. The primary signal is `chunks{done}` advancing by 1 (item 2), not a budget halt. `tg_parser_topicization_full_run_budget_halt_total` normally stays **0** at budget (~450K) > one chunk (~374K); it only increments if a chunk's own cost exceeds the budget, in which case it should fire **after** that chunk commits (never before any chunk starts, and never silently absent while tokens climb far past the budget within a single invocation). Either way, the invariant to confirm is: the tick ends promptly and the chunk it ran is durably persisted.
4. **No BUG-077 alerts firing** — `TopicizationFullRunResumeNoProgress`, `TopicizationFullRunChunkFailedSustained`, `TopicizationFullRunCircuitOpen` must all stay `inactive`. If any fires, treat it as the STOP trigger in §7 — these alerts exist specifically to catch a stuck/leaking resume.
5. **`record_topic_created` / `tg_parser_topics_created_total` rising** during the run — this was the original false-positive source for `TopicizationBurnNoProgress` (BUG-076's own observability gap); it must now rise per-chunk, not stay flat until the very end.
6. **No BUG-071..075 storm signals** — `tg_parser_llm_truncation_total`, `tg_parser_topicization_failed_batches_total`, `escalating to full topicization` log frequency, and lock-contention logs should all stay in the "healthy steady state" band described in the watch runbook §3.
7. **Cooldown markers behaving** — check the `processing_failures` table for `topicization:reescalation:murashko_med` (should NOT be repeatedly re-arming — BUG-076/077 round-2/3 fixes specifically prevent a live checkpoint from arming the BUG-071 cooldown) and `topicization:full_checkpoint:murashko_med` (should show `chunks_done` monotonically increasing, `consecutive_noprogress_resumes` staying at 0 in the healthy case).

Use §3.3's PromQL and §3.4's log greps for the concrete queries. Check in via Grafana ("Token-Burn Watch (BUG-071..075)" dashboard, host port **3001**) alongside raw PromQL/psql — do not rely on Grafana panels alone since the new BUG-076/077 series are not yet on that dashboard (only the alert rules and raw metrics exist for them at this HEAD).

---

## 6. Convergence expectation

Arithmetic from the settings in §2 and the original-incident numbers (BUG_LOG BUG-076 row), **caveated: actual per-chunk token cost is unknown until observed — this run itself is the calibration data point**:

- Backlog: ~15.5K docs, 0 existing cards.
- `BATCH_SIZE=50` (hard-coded in the full generate path) → **~310 batches** (15,500 / 50); the original incident recorded **~353 batches** for essentially the same corpus (likely inflated by BUG-071 shrink/split retries on oversized batches) — treat **310–353** as the plausible range.
- `topicization_full_chunk_batches=20` → **chunks_total ≈ 16–18** (`ceil(310/20)=16` to `ceil(353/20)=18`).
- `topicization_full_max_chunks_per_invocation=1` (default) → **1 chunk per scheduler tick**, in the healthy case.
- `scheduler_default_interval=3600s` (1 hour, per-source poll interval, `tg_parser/config/settings.py`) → roughly **one resume opportunity per hour** for `murashko_med` (exact cadence depends on the scheduler's global loop across all active sources — do not treat this as an exact clock).
- **Expected convergence: roughly 16–18 ticks ≈ 16–18 hours of wall-clock time** for `murashko_med`'s full backlog to be chunked, persisted, and finalized (plus one final, comparatively cheap cross-chunk consolidation pass — a similarity-based merge over the *persisted* card set, not a fresh LLM pass over the corpus).
- **Total token spend over full convergence, if nothing halts early for other reasons, is expected to land in the same ballpark as the original incident (~6–7M tokens)** — the fix does not make the topicization itself cheaper, it makes the spend **durable and resumable** instead of vaporized. Do not be alarmed that the cumulative total approaches the original figure; the entire point is that this time every token buys a persisted card.

If the actual per-chunk token cost observed in tick 1 differs meaningfully from the ~374K estimate, **recompute** chunks_total and expected convergence time before assuming anything is wrong.

---

## 7. Kill-switch / rollback

### Instant kill-switch (re-pause the channel — does not touch code or the flag)

**Preferred — MCP tool:**
```
pause_channel(channel_id="murashko_med")
```
Idempotent; the scheduler skips any source whose `status != 'active'` on its next tick. This does **not** interrupt a chunk already in flight (a `gather` over a chunk's batches cannot be interrupted mid-flight — only the *next* chunk is prevented from starting).

**Raw-SQL fallback:**
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"UPDATE sources SET status = 'paused', updated_at = now() WHERE channel_id = 'murashko_med' AND deleted_at IS NULL;"
```

### Disable the flag again (without a code rollback)

Since `topicization_full_resume_enabled` is a plain env-var-backed setting read once at process start:
```env
# .env on prod host
TOPICIZATION_FULL_RESUME_ENABLED=false
```
```bash
ssh prod "cd /home/user/TG_parser && docker compose up -d --no-deps tg_parser"
```
This reverts the scheduler + pipeline to the byte-for-byte-unchanged legacy monolithic path immediately (no chunking, no resume driver, no checkpoint writes). Any leftover `topicization:full_checkpoint:murashko_med` row goes **inert** (BUG-077 round-4 fix: `_has_live_full_checkpoint` short-circuits to `False` when the flag is off) — it does not need to be deleted for safety, though you may want to clear it before ever re-enabling (BUG-077 F7 hygiene, runbook §10) to avoid resuming a stale plan.

### When a full code rollback is warranted vs just re-pausing

- **Re-pause first, always** (§7 top — the instant kill-switch) — it is instant, reversible, and stops new spend within one tick. This is the correct FIRST move for almost every anomaly in §5 / the ⛔ warnings.
- **Disabling the flag** (above) is the correct SECOND move if the anomaly looks specific to the chunked/resume machinery (e.g. a BUG-077 alert firing, checkpoint state looking corrupt) rather than a general LLM/billing issue.
- **A full code rollback is warranted only if** disabling the flag does not resolve the anomaly (i.e. the legacy monolithic path itself is misbehaving — which would indicate the anomaly was never actually about BUG-076/077), or if you need to remove the checkpoint/resume code entirely. In that case, choose the target deliberately (see the verified rollback-ref descriptions in the header):
  - **`b7285d7` — the correct target for a BUG-076/077 problem.** It removes BUG-076 **and** BUG-077 code while keeping BUG-071..075 intact:
    ```bash
    git checkout b7285d7 && docker compose build tg_parser && docker compose up -d
    ```
  - **`23764b7` — the rare "strip the whole BUG-073→077 chain back to bare BUG-072" case only.** It is the BUG-072 commit itself, so it **keeps BUG-071/072** but **removes BUG-073/074/075/076/077** (advisory locks on processing/incremental, `repair_json`, the reconcile hook, checkpoint/resume + hardening). It does **NOT** revert BUG-071..075 — there is no single "revert BUG-071..075" ref in this range. Use it only if the entire BUG-073→077 chain (not just BUG-076/077) needs to go:
    ```bash
    git checkout 23764b7 && docker compose build tg_parser && docker compose up -d
    ```
  - Either way, follow `PRODUCTION_DEPLOYMENT.md` § Rollback Procedures / § Updating for the full sequence (pre-rollback backup, smoke checks, etc.) — do not skip the backup step.

---

## 8. Success criteria

The controlled first exercise **succeeded** if, over the observation window:

- **Chunks persist durably** — `chunks_done` (both the Prometheus gauge and the checkpoint row) advances monotonically tick over tick, and a `docker compose restart tg_parser` (or any transient failure) does not lose progress already committed.
- **`topics_created` rises DURING the run**, not only at the very end — confirms the original BUG-076 observability gap stays closed.
- **A clean chunk-cap-halt-and-resume pattern is observed across multiple ticks** — each tick runs one chunk (`chunks_done` +1), commits it durably, and returns because of the `max_chunks_per_invocation=1` cap; the next tick's resume driver picks up the following chunk. (At budget > one chunk this is a *chunk-cap* halt, not a budget halt — `budget_halt_total` normally stays 0.) This continues until full convergence is reached (`chunks_done == chunks_total`, `final_merge_done=true`, the checkpoint row clears).
- **No BUG-071..077 regression signals**: none of `TopicizationFullRunResumeNoProgress` / `TopicizationFullRunChunkFailedSustained` / `TopicizationFullRunCircuitOpen` / the pre-existing BUG-071/075 alerts fire; `chunk_failed_total` stays at (or near) 0; `noprogress_skip_total` stays at 0 (the breaker never needed to open); no storm-like `escalating to full topicization` pattern; the BUG-071 re-escalation cooldown is not seen arming repeatedly for `murashko_med` while the checkpoint is live.
- **No duplicate/orphan cards** — spot-check `topic_cards` for `murashko_med` for any obviously duplicated topics after a few chunks land (the atomic per-chunk commit is supposed to make this structurally impossible, but this is the first time it is exercised against a real LLM in production, not just tests).

This mirrors the design note §10 roll-forward criteria: *"cards persist incrementally, a mid-run halt/crash loses ≤1 chunk, resume completes coverage, `TopicizationBurnNoProgress` no longer false-positives, BUG-071..075 signals steady."*

---

## 9. Post-exercise steps (once satisfied)

Once the success criteria in §8 are met (either full convergence, or several clean chunk-cap-halt-and-resume cycles with no red flags), the following decisions remain to fully "graduate" the feature — **all `[CONFIRM WITH USER]`, none of them should be decided unilaterally by a session executing this runbook**:

1. **Decide on a steady-state budget policy** — at `max_chunks_per_invocation=1` the budget is not the throttle (the chunk cap is), so this decision is really about what happens *if* you raise `max_chunks` (item 2): keep a per-invocation budget near one chunk's cost (effectively still one chunk/tick, very safe), set a larger budget to allow several chunks per tick (faster convergence, more spend exposure per tick), or set it to `0` (unbounded per invocation, relying solely on the F1 circuit-breaker + the per-invocation chunk cap for safety) once the machinery has proven itself over one full `murashko_med` convergence.
2. **Decide whether to raise `topicization_full_max_chunks_per_invocation`** above `1` — this is what would make the token budget the *primary* throttle (multiple chunks per invocation, budget-checked between them) instead of the secondary safety net it is at `1` (see §4a). Only consider this after `murashko_med` has converged cleanly at the default `1`.
3. **Decide whether to enable the flag for other channels** — remember it is a global switch; once any other 0-card, large-backlog channel exists, it will go through the exact same chunked path automatically via `should_reescalate`. Confirm there's no channel that should stay on the legacy path for some reason before treating "enabled" as a permanent, unconditional state.
4. **Decide whether to raise the default budget** in `tg_parser/config/settings.py` (currently `0`/disabled) now that a real-world calibration point exists from this exercise — this WOULD be a code change (a settings default edit) and needs its own explicit-approval workflow per AGENTS.md, not something to do inside this runbook.
5. **Close out the BUG_LOG rows.** BUG-077's `Status` is currently `in-progress` (awaiting the controlled first exercise per its own row); BUG-076's `Status` is `in-progress` pending the same. Once this exercise succeeds, update both rows to `resolved` with a summary of the observed real-world behavior (actual per-chunk token cost, actual convergence time, any surprises) — this is a documentation follow-up, and per AGENTS.md should only be done with the user's awareness (it's a `docs/notes/BUG_LOG.md` edit, not itself a commit — committing still requires explicit request).
6. **Consider adding the new BUG-076/077 metrics to the Grafana "Token-Burn Watch" dashboard** (`docker/grafana/dashboards/token_burn.json`) — they currently exist only as raw Prometheus series + alert rules, not dashboard panels. This is a `[CONFIRM WITH USER]` follow-up, not part of this exercise.

---

## 10. Reading list / pointers

**Primary sources for this session (read in §"Read in order" above):**
- [`DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md`](DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md) — the architecture, especially §10 (rollout sketch) and §11 (open tunables).
- [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md) — the general token-burn watch discipline this exercise borrows its cadence/kill-switch structure from, plus §10's BUG-077 F7 re-enable hygiene section (already incorporated into §1 item 5 and the §7 disable-flag note above).
- [`BUG_LOG.md`](BUG_LOG.md) — `### BUG-076` and `### BUG-077` rows (full incident history, all four Bugbot review rounds for BUG-077, the exact code anchors).
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (repo root) — § Updating, § Rollback Procedures.

**Deep background (not required to execute this session, but the source of truth if something contradicts this runbook):**
- [`START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md`](START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md) — the BUG-076 implementation start-prompt (how the chunked/atomic/checkpoint/budget/resume-driver machinery was built).
- [`START_PROMPT_SESSION_BUG076_TOKENLEAK_HARDENING_IMPL_2026-07-02.md`](START_PROMPT_SESSION_BUG076_TOKENLEAK_HARDENING_IMPL_2026-07-02.md) — the BUG-077 follow-up (F1 circuit-breaker, F4 reconcile gate, F3/F5/F7/F9 hardening) that makes enabling the flag safe in the first place.

**Source code anchors, if you need to verify behavior directly rather than trust this runbook:**
- `tg_parser/config/settings.py` — all `topicization_full_*` settings (§2 above quotes them verbatim).
- `tg_parser/api/metrics.py` — all `TOPICIZATION_FULL_RUN_*` series definitions (§3.1).
- `docker/prometheus/alerts.yml` — `tg_parser_bug077_full_run_hardening` group (§3.2).
- `tg_parser/processing/topicization.py` — `_topicize_channel_chunked`, `_commit_chunk_atomically`, `_finalize_full_run`.
- `tg_parser/services/topicization_service.py` — `run_full_topicization_resume_for_channel` (the resume driver), `run_reconciliation_for_channel` (the F4 gate), `_has_live_full_checkpoint`.
- `tg_parser/services/scheduler_service.py` — where the resume driver is hooked into `_process_source` (ordered before the BUG-075 reconcile hook).
