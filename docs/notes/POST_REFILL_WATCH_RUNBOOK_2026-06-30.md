# POST-REFILL WATCH RUNBOOK — token-burn fixes BUG-071..075 + R1

**Created:** 2026-06-30. **Repo:** `/Users/alexanderefimov/TG_parser`, branch `main`.
**Prod HEAD this runbook targets:** `73d9a58` (BUG-075 R1 observability shipped — the tip of the BUG-071→075 token-burn hardening chain).
**Rollback ref:** `23764b7` (`fix(topicization): add non-blocking per-channel advisory lock … (BUG-072)`) — the last commit BEFORE the BUG-073/074/075 + R1 ship; everything after it is what this watch validates.
**Prod:** VPS `ssh prod`, Docker compose, app dir `/home/user/TG_parser`.
**Scope:** read-only observation plan for the window right after the Anthropic balance is refilled (which re-enables processing → new processed docs → re-arms the incremental topicization + the BUG-075 reconcile hook). **This runbook changes nothing in prod and does not top up billing.** It extends [`MONITORING_PLAN_BUG071_POST_TOPUP_2026-06-27.md`](MONITORING_PLAN_BUG071_POST_TOPUP_2026-06-27.md) (still valid for BUG-071) to the fixes that shipped after it.

> Why now: while processing is billing-blocked the whole token-burn surface is dormant (no new docs → no topicization → no reconcile). Refill is the exact moment all five fixes get exercised for real. This is the safety net for that first window.

---

## 0. What shipped since the BUG-071 plan (one-line recap, for grounding)

| Fix | Commit | What it stops | The "did it hold?" signal |
|---|---|---|---|
| **BUG-072** | `23764b7` | Two concurrent FULL topicizations of one channel (advisory lock `0x70C1`). | No duplicate `escalating to full topicization` for one channel from two callers; logs `topicization_run_skipped_already_in_flight`. |
| **BUG-073** | `bbd7c35` | Concurrent processing (F1, lock `0x9C40`) + incremental (F3, lock `0x70C2`) re-burn. | Logs `processing_run_skipped_already_in_flight` / `deferred_locked`; no double-billed backlog. |
| **BUG-074** | `e0f517d` | Up-to-3× re-issue of a malformed-JSON topicization batch (now `repair_json` first, cap 2). | `tg_parser_llm_json_parse_retry_total{stage=~"topicization_.*"}` ~0. |
| **BUG-075** | `c99b4b5` | Permanent abandonment of processed-but-uncovered docs (standing reconcile hook, at-most-one discover). | Uncovered backlog drains; reconcile discover stays ~0 in steady state. |
| **R1** | `73d9a58` | Silent (debug-only) bounded re-feed when the `discover_attempted` marker write fails. | `tg_parser_topicization_discover_attempted_mark_failed_total` = 0. |

Key safety property to remember: the BUG-075 reconcile hook runs `run_incremental_topicization(reconcile_only=True)` → it can **NEVER** trigger a full re-escalation (`should_reescalate` is forced `False`) and **NEVER** takes `0x70C1`. So reconcile is, by construction, bounded re-burn at worst (cap `topicization_reconcile_max_docs=200` + random sampling), never a storm.

---

## 1. The monitoring package (what's deployed vs. drafted)

**Already LIVE in prod** (shipped with the BUG-071 watch, group `tg_parser_bug071_topicization` in `docker/prometheus/alerts.yml` — *only if* that group was force-recreated onto prod prometheus; confirm with §2): `TopicizationTruncationSpike` / `…Burst`, `SonnetCompletionNearCap`, `TopicizationBurnNoProgress`, `TopicizationFailedBatchesHigh`, `AnthropicBillingStillBlocked`.

**Drafted in this package (UNCOMMITTED, NOT deployed):**
- **New alert group** `tg_parser_bug075_reconcile_postrefill` (appended to `docker/prometheus/alerts.yml`): `TopicizationDiscoverMarkerWriteFailing` (R1), `TopicizationJsonRepairRetrySpike` (BUG-074), plus three `TODO` gap comments for the missing metrics (§4). promtool unit tests in `docker/prometheus/alerts_test.yml`.
- **New Grafana dashboard** `docker/grafana/dashboards/token_burn.json` (uid `tg-parser-token-burn`, title "TG_parser — Token-Burn Watch (BUG-071..075)") — auto-provisioned from `docker/grafana/dashboards/` on Grafana boot.

**Deploying the new alert rules requires a Prometheus force-recreate** (the rules file is a bind-mount; a hot reload keeps the stale inode — see `PRODUCTION_DEPLOYMENT.md` § Updating step 4b):
```bash
docker compose up -d --force-recreate --no-deps prometheus   # only after docker/prometheus/* changed
```
The new dashboard needs only a Grafana restart (or it appears on next boot); no Prometheus recreate.

---

## 2. Pre-refill checklist (confirm GREEN before restoring credit)

Run from `ssh prod`, app dir `/home/user/TG_parser`:

1. **HEAD is the fix:** `git -C /home/user/TG_parser rev-parse --short HEAD` → `73d9a58`. `docker compose ps` all healthy.
2. **The R1 metric is registered & scraped:**
   ```bash
   docker compose exec tg_parser curl -s localhost:8000/metrics | grep -c tg_parser_topicization_discover_attempted_mark_failed_total
   ```
   It appears on first increment; if absent, it's defined-but-never-incremented (the healthy state). Also confirm the BUG-071 surface: `… | grep -E 'tg_parser_llm_truncation_total|tg_parser_topicization_failed_batches_total'`.
3. **Which alert rules are live:** `curl -s localhost:9090/api/v1/rules | python3 -m json.tool | grep -E 'Topicization|Anthropic'`. Decide whether to deploy the new group (§1) BEFORE or DURING the watch.
4. **Reconcile cap setting:** `docker compose exec tg_parser python -c "from tg_parser.config import settings; print(settings.topicization_reconcile_max_docs, settings.topicization_reescalation_cooldown_s)"` → `200 3600` (or intended).
5. **No stale markers** (clean baseline): §6 SQL → note current re-escalation markers AND `discover_attempted` marker count.
6. **Backlog snapshot** (to measure drain): record processed/raw counts + `min(tg_parser_channel_processed_coverage_ratio)`.
7. **Billing-block baseline:** note current `tg_parser_anthropic_billing_block_total` value; after refill its `rate` must fall to 0.

---

## 3. Steady-state expectations (what GREEN looks like)

| Signal | Metric / source | Healthy steady state | Red flag |
|---|---|---|---|
| Full re-topicization storm | logs `escalating to full topicization` + §6 re-escalation SQL; proxy `TopicizationBurnNoProgress` | ≤1 full re-escalation per stuck channel per cooldown TTL (3600s); then `re-escalation skipped (cooldown)` | Same channel re-escalating on ≥3 consecutive ticks with NO marker row |
| Truncation re-burn | `tg_parser_llm_truncation_total` by stage | ~0 on all stages (occasional single increment OK) | Sustained > 0.05/s (warn) / > 0.2/s (critical) |
| Failed batches | `tg_parser_topicization_failed_batches_total` by stage | ~0 | > 0.05/s sustained |
| JSON-repair re-burn (BUG-074) | `tg_parser_llm_json_parse_retry_total{stage=~"topicization_.*"}` | ~0 (repair handles it on attempt 1) | > 0.05/s sustained on any topicization stage |
| **Reconcile re-burn** | reconcile logs (§6) + discover-stage truncation/retry proxies | discover calls from reconcile ≈ 0 once backlog drained (at-most-one-discover) | Sustained non-zero reconcile discover after backlog should be empty |
| **R1 marker-write** | `tg_parser_topicization_discover_attempted_mark_failed_total` | **EXACTLY 0** | ANY sustained > 0 (warn) — bounded re-feed |
| Anthropic spend | `tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}`; avg/call | hundreds–low-thousands completion tok/call; spend tracks card production | avg/call > 6000 (→8192 cap); spend high while topics flat |
| Billing / 429 | `tg_parser_anthropic_billing_block_total`, `…_5xx_total` | rate → 0 after refill | Sustained > 0 (refill ineffective) |
| Lock contention / defer | logs `*_skipped_already_in_flight`, `deferred_locked=True` | occasional (benign — concurrent triggers) | sustained high (stuck convergence / wedged long run) |

---

## 4. GAPS — token-burn signals NOT yet first-class metrics

These have **no direct Prometheus series** at HEAD `73d9a58`; watch them via logs/DB (§6) until a (separately-approved) tiny metric lands. The alert group carries the same TODOs.

| Gap | Today's only Prometheus proxy | Minimal metric to close it |
|---|---|---|
| **Reconcile discover re-burn** (discover calls from the BUG-075 hook) | `stage="topicization_discover"` on `tg_parser_llm_truncation_total` / `…json_parse_retry_total` + un-stage-scoped Sonnet tokens | Counter `tg_parser_topicization_reconcile_discover_docs_total{channel_id}` (docs fed to reconcile discover per tick) |
| **Full re-escalation events** (the storm trigger) | indirect: `TopicizationBurnNoProgress` / truncation; logs + re-escalation SQL | Counter `tg_parser_topicization_reescalation_total{channel_id,outcome=fired\|skipped_cooldown\|cleared}` |
| **Advisory-lock defer/skip** (stuck convergence) | logs only | Counter `tg_parser_channel_lock_skip_total{stage,outcome=skipped\|deferred\|proceeded}` |

R1's `tg_parser_topicization_discover_attempted_mark_failed_total` is the example of closing exactly this kind of gap (it converted a debug-only quiet path into an alertable series); the three above would do the same for their signals. **Decision needed from the user** on whether to implement any (each is a small `metrics.py` counter + one emit site).

---

## 5. PromQL quick-reference (works-today)

```promql
# R1 — marker-write failures (headline new signal; healthy = 0)
sum(rate(tg_parser_topicization_discover_attempted_mark_failed_total[15m])) by (channel_id)

# BUG-074 — topicization JSON-parse-retry rate (healthy ~0 post-repair)
sum(rate(tg_parser_llm_json_parse_retry_total{stage=~"topicization_.*"}[15m])) by (stage)

# BUG-071 — truncation rate by stage (covers reconcile via the discover stage)
sum(rate(tg_parser_llm_truncation_total[5m])) by (stage)

# Failed batches (direct) + recovery
sum(rate(tg_parser_topicization_failed_batches_total[15m])) by (stage)
sum(rate(tg_parser_topics_created_total[15m])) by (channel_id)

# Sonnet avg completion tokens / call (near-cap detector; > 6000 = bad)
sum(rate(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*",token_type="completion"}[10m]))
  / sum(rate(tg_parser_llm_requests_total{model=~"claude-sonnet-4-6.*",status="success"}[10m]))

# Billing cleared + backlog drain
sum(rate(tg_parser_anthropic_billing_block_total[10m]))
sum(rate(tg_parser_messages_processed_total{status="success"}[15m]))
min(tg_parser_channel_processed_coverage_ratio)

# Cost guardrail (rollback trigger 5): Sonnet spend/hr while topics flat
sum(increase(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}[1h]))
  and (sum(rate(tg_parser_topics_created_total[1h])) or vector(0)) == 0
```

---

## 6. Log / DB checks (the authoritative ground truth for the gaps in §4)

**Logs** (`docker compose logs -f tg_parser`, or `--since 15m`):
```bash
docker compose logs --since 1h tg_parser | grep -c "re-escalation skipped (cooldown)"        # ✅ cooldown working
docker compose logs --since 1h tg_parser | grep -c "escalating to full topicization"           # expect ≤1 per stuck channel
docker compose logs --since 1h tg_parser | grep -E "TopicizationBatchTruncatedError|max_tokens cap"
docker compose logs --since 1h tg_parser | grep -E "reescalation_(marker|persisted)_"           # MUST be empty
docker compose logs --since 1h tg_parser | grep -iE "discover_attempted.*(fail|warn)"            # R1 marker-write failures (warning)
docker compose logs --since 1h tg_parser | grep -cE "skipped_already_in_flight|deferred_locked"  # lock contention (benign if occasional)
```

**DB — re-escalation cooldown markers** (storm gate):
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT source_ref, channel_id, attempts, last_attempt_at FROM processing_failures WHERE source_ref LIKE 'topicization:reescalation:%' ORDER BY last_attempt_at DESC;"
```
Healthy: few rows, `attempts` climbing ≤ ~1/hr. Red flag: `attempts` jumping every few minutes, OR `escalating to full topicization` logs with NO matching row (cooldown not arming → unbounded burn condition).

**DB — discover_attempted markers** (reconcile convergence; one row per uncovered-after-discover doc):
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT channel_id, count(*) FROM processing_failures WHERE source_ref LIKE 'topicization:discover_attempted:%' GROUP BY channel_id ORDER BY 2 DESC;"
```
Healthy: count GROWS as the backlog drains, then PLATEAUS (each uncovered doc marked at-most-once → reconcile discover settles to ~0). Red flag: count NOT growing while uncovered backlog persists AND R1 metric > 0 = markers failing to persist → re-feed.

---

## 7. Observation timeline

**T+0 (refill moment):** record timestamp. Tail logs: `docker compose logs -f --since 1m tg_parser`. Open dashboards: "Token-Burn Watch (BUG-071..075)" + the existing "Pipeline".

**First 15 min:**
- Billing cleared: `tg_parser_anthropic_billing_block_total` rate → 0; no `AnthropicBillingError` in logs.
- Processing resuming: `messages_processed_total{status=success}` rate > 0.
- First topicization ticks: watch truncation (§5) + topics-created. Expect first `escalating to full topicization` for any 0-card channel → verify a `re-escalation skipped (cooldown)` follows next tick + a marker row appears.
- **Hard-stop check:** if truncation ≥ 0.2/s, R1 metric > 0, or burn-without-progress → §8.

**First 1 hour (≈ one cooldown TTL = 3600s):**
- ≤1 full re-escalation per stuck channel; marker `attempts` advanced by ~1, not N.
- `topics_created` advancing for active channels (markers being cleared).
- Avg completion/call < 6000.
- **R1 metric still 0**; `discover_attempted` marker count growing as expected.
- Backlog draining vs the §2 snapshot; `min(coverage_ratio)` rising.
- Sonnet spend nowhere near the ~2.38M single-incident figure.

**First 24 hours / first few days:**
- Truncation / failed-batch / json-retry counters flat (only occasional single increments).
- No channel stuck re-escalating (re-run §6 SQL — markers transient or stably throttled).
- Reconcile discover settling to ~0 once backlog drains; `discover_attempted` count plateaus.
- R1 metric stays 0; lock-defer logs only occasional.
- Decide: if clean for 24h+, close this watch and (with approval) deploy the §1 alert group + dashboard as permanent guardrails (Prometheus force-recreate required).

---

## 8. Rollback / kill-switch (concrete)

Each trigger reads from a signal defined above (no orphan triggers).

| # | Trigger (signal) | Action |
|---|---|---|
| 1 | **Unbounded re-escalation** — `escalating to full topicization` same channel ≥3 consecutive ticks, NO marker row (§6) | **Pause ingestion / re-pause billing first** (fastest kill-switch), then roll back |
| 2 | **Truncation burst** — `sum(rate(tg_parser_llm_truncation_total[5m])) > 0.2` 10m, topics flat (alert `TopicizationTruncationBurst`) | Re-pause billing, roll back |
| 3 | **Burn-without-progress** — Sonnet completion > 150 tok/s for 30m while `topics_created` rate == 0 (alert `TopicizationBurnNoProgress`) | Re-pause billing, roll back |
| 4 | **Cooldown / marker store erroring** — any `reescalation_marker_write_failed` / `reescalation_persisted_recount_failed` (§6) | Roll back (gate degrades to no-cooldown) |
| 5 | **Cost guardrail** — `sum(increase(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}[1h])) > 2.4e6 and topics flat` | Re-pause billing, review |
| 6 | **R1 sustained** — `tg_parser_topicization_discover_attempted_mark_failed_total` rate > 0 sustained (alert `TopicizationDiscoverMarkerWriteFailing`) | NOT a rollback trigger on its own (bounded re-feed). Investigate the channel's DB write path; rollback only if it coincides with #1–#5 |

**Rollback command** (revert to the pre-BUG-073/074/075 state):
```bash
git checkout 23764b7 && docker compose build tg_parser && docker compose up -d
```

**Pause ingestion** (fastest way to make the loop dormant without a rollback — stops new docs → no topicization → no reconcile):
```bash
# Per channel (preferred — surgical): via MCP pause_channel, or
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"UPDATE sources SET billing_paused_at = now(), billing_pause_reason = 'post-refill storm — manual pause' WHERE id = '<channel>';"
# Resume by setting billing_paused_at = NULL once safe.
```
Re-pausing billing / pausing ingestion is reversible and is the preferred FIRST move if burn is active; rollback is the code-level fix-the-fix — prefer pause first, then roll back calmly.

---

## 9. Open items / decisions for the user
- **Deploy the new alert group?** `tg_parser_bug075_reconcile_postrefill` is drafted + promtool-tested but NOT deployed; rolling it out needs a Prometheus **force-recreate** (`docker compose up -d --force-recreate --no-deps prometheus`).
- **Deploy the new dashboard?** `token_burn.json` is auto-provisioned on Grafana boot/restart (no Prometheus recreate).
- **Implement any of the §4 missing metrics?** Each is a small `metrics.py` counter + one emit site (no migration). Reconcile-discover-docs and re-escalation-event counters would remove the last log/DB-only blind spots. Out of scope for this monitoring-only task.
- All artifacts are **uncommitted** in the working tree for review.
