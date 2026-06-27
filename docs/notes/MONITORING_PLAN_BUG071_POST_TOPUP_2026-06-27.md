# MONITORING / OBSERVATION PLAN — BUG-071 post-Anthropic-top-up watch

**Created:** 2026-06-27. **Repo:** `/Users/alexanderefimov/TG_parser`. **Prod HEAD this plan targets:** `bdca97f` (BUG-071 fix shipped). **Rollback ref:** `61637d1`.
**Prod:** VPS `ssh prod` (`212.72.189.15:2296`, user `user`, app dir `/home/user/TG_parser`), Docker compose.
**Scope:** read-only observation plan for the window right after Anthropic credit is restored (which re-enables the processing stage → new processed docs → re-arms the incremental topicization path). **This doc changes nothing in prod and does not top up billing.**

> Why this matters: while processing is billing-blocked the BUG-071 token-burn loop is dormant (no new docs → the zero-card re-escalation branch is never taken). Top-up is the exact moment the fix gets exercised for real. This plan is the safety net for that first window.

---

## 0. What shipped in `bdca97f` (one-line recap, for grounding)

- **Fix 1** — `LLMResponse.stop_reason` surfaced; `stop_reason=="max_tokens"` in the three topicization loops (`_generate_topics_batch` / `_merge_topics` / `_discover_single_batch`, `tg_parser/processing/topicization.py`) shrinks/scales instead of a 3× identical re-burn; a fully-truncated batch raises `TopicizationBatchTruncatedError` and is counted in `failed_batches` (`topicization.py:52`, `:255-270`, `:419`, `:495-511`; cap `_TRUNCATION_MAX_TOKENS_CAP = 32768` at `:49`).
- **Fix 2** — full re-escalation in `tg_parser/services/topicization_service.py` gated behind a persisted cooldown `topicization_reescalation_cooldown_s` (default **3600s**, `tg_parser/config/settings.py:388`), stored in `processing_failures` under synthetic key `topicization:reescalation:<channel_id>` (`error_class="TopicizationReEscalation"`). Marker arms/clears on the **actually persisted** card count (`topicization_service.py:50-52`, `:269-372`).
- **Fix 3** — Counter `tg_parser_llm_truncation_total{provider,model,stage}` + `record_llm_truncation` (`tg_parser/api/metrics.py:111-116`, `:730-743`). Stages: `topicization_generate` / `topicization_merge` / `topicization_discover`.

---

## 1. Metric surface to watch (exact names + labels, from `tg_parser/api/metrics.py`)

| Metric | Labels | Role in this watch | Source |
|---|---|---|---|
| `tg_parser_llm_truncation_total` | `provider, model, stage` | **Primary BUG-071 signal.** Each `max_tokens` truncation at a topicization site. | `metrics.py:111` |
| `tg_parser_topicization_failed_batches_total` | `stage, channel_id` | **Direct failed-batch signal** — mirrors `failed_batches` (BUG-018); counts truncation-drops AND non-truncation batch failures. Only `topicization_generate` emitted today. | `metrics.py` (after `LLM_TRUNCATION_TOTAL`) |
| `tg_parser_llm_tokens_total` | `provider, model, token_type` (`prompt`/`completion`) | **Token burn / cost.** Watch Sonnet `completion` rate + avg-per-call near the cap. ⚠ label is `token_type`, not bare `{model}`. | `metrics.py:96` |
| `tg_parser_llm_json_parse_retry_total` | `stage` | Genuine JSON-repair retries (BUG-019 path, preserved). A truncation should **no longer** masquerade here. | `metrics.py:153` |
| `tg_parser_llm_requests_total` | `provider, model, status` (`success`/`error`) | Denominator for avg-tokens-per-call + error ratio. Note a charged-but-truncated reply still counts `success`. | `metrics.py:83` |
| `tg_parser_llm_request_duration_seconds` | `provider, model` | LLM latency (existing `HighLLMLatency` alert). | `metrics.py:89` |
| `tg_parser_anthropic_billing_block_total` | `stage` | Confirms the billing block is actually cleared after top-up (rate → 0). | `metrics.py:144` |
| `tg_parser_anthropic_api_5xx_total` | `status` | Provider 5xx noise that can masquerade as failures. | `metrics.py:164` |
| `tg_parser_messages_processed_total` | `channel_id, status` (`success`/`error`) | **Processing throughput / backlog drain** — the thing that should resume after top-up. | `metrics.py:41` |
| `tg_parser_topics_created_total` | `channel_id` | **Topicization actually producing cards** (the recovery signal that disarms the cooldown). | `metrics.py:47` |
| `tg_parser_channel_processed_coverage_ratio` | `channel_id` | Per-channel processed/raw coverage gauge (BUG-067/B3). | `metrics.py:943` |
| `tg_parser_scheduler_tasks_total` | `task_name, status` | Tick liveness. | `metrics.py:138` |

**`failed_batches` is now a direct Prometheus metric** (was log/CLI-only). The new Counter `tg_parser_topicization_failed_batches_total{stage, channel_id}` (`metrics.py`, helper `record_topicization_failed_batch`) is incremented at the exact sites where `TopicizationPipelineImpl.failed_batches` is counted in `topicize_channel` (`topicization.py:262/270/310`), so the series matches the `run_topicization` return dict / CLI exit code (BUG-018) / log number. It counts BOTH truncation-drops (corroborating `tg_parser_llm_truncation_total`) AND genuine non-truncation batch failures (the broader class the truncation counter does not cover). Only `stage="topicization_generate"` is emitted today (merge falls back to unmerged, discover marks docs unassignable — neither is a counted failed batch). Alert: §7 P3b `TopicizationFailedBatchesHigh`. The log (§3) / `topics_created` proxy is retained as a complement, not the only signal.

---

## 2. Prometheus / alerting / dashboards — current state (grounded)

- **Scrape** (`docker/prometheus.yml`): `scrape_interval: 15s`; jobs `tg_parser_api` → `tg_parser:8000/metrics`, `tg_parser_mcp` → `mcp:8080/metrics`, `tg_parser_bot` → `tg_bot:8081/metrics`. Topicization runs in the `tg_parser` (api) container → use `job="tg_parser_api"` (or `service="api"`) to scope queries.
- **Rules** (`rule_files: /etc/prometheus/alerts.yml` → repo `docker/prometheus/alerts.yml`): rules exist but are **infra/feature-health only** — `HighHTTPErrorRate`, `HighLLMErrorRate` (>20% `llm_requests` error 5m), `HighLLMLatency`, `DBPoolNearLimit`, `APIServiceDown`, `MCPServiceDown`, `NoMessagesProcessed`, plus F11/F5-B/F5-C gates. **There is NO truncation / token-burn / topicization-failure alert today.** This watch is therefore rule-light for exactly the BUG-071 failure class → §7 proposes concrete rules. `HighLLMErrorRate` will *not* catch BUG-071 because truncated calls are `status="success"`.
- **promtool unit tests:** `docker/prometheus/alerts_test.yml` (pattern to mirror for any new rule).
- **Grafana** (`docker/grafana/dashboards/pipeline.json`, datasource uid `prometheus` @ `http://prometheus:9090`): has "LLM Tokens Consumed (rate/cumulative)", "LLM Requests", "Topics Created (total)" — but **no truncation panel**. A new panel for `tg_parser_llm_truncation_total` would slot in here.
- **Access on prod:** Prometheus API/UI at `prometheus:9090` (compose network). From the host: `curl -s localhost:9090/api/v1/query --data-urlencode 'query=...'`. Raw fallback: `docker compose exec tg_parser curl -s localhost:8000/metrics | grep -E 'tg_parser_llm_truncation_total|tg_parser_llm_tokens_total'`.

---

## 3. The two failure signatures to watch

### (a) Truncation re-burn (Fix 1) — all THREE stages
`tg_parser_llm_truncation_total` is incremented at all three topicization LLM sites (verified): `topicization_generate` (`topicization.py:420`), `topicization_merge` (`:591`), `topicization_discover` (`:1339`). The discover stage is the **incremental** Phase-2 path (`_discover_single_batch`), which runs every tick on new docs for channels that already have cards — so truncation/re-burn can occur there **independently of the zero-card re-escalation** in §(b). Always watch the counter `by (stage)` so a discover-stage burn isn't hidden behind a quiet generate stage.
- **Healthy:** `tg_parser_llm_truncation_total` essentially flat on all stages (occasional single increments when one oversized batch triggers a split are acceptable). Sonnet **avg completion tokens per call well below the 8192 cap** (a few hundred–low thousands). `topics_created_total` advancing.
- **Pathological (the pre-fix prod signature):** truncation counter climbing steadily on any stage, Sonnet `completion` token rate high, and **avg completion ÷ call ≈ the cap (~8097 ≈ 8192)** — i.e. essentially every call maxing its output budget — while `topics_created_total` stays flat. Post-fix this should NOT recur (shrink ladder + cooldown), so any sustained climb is the canary that Fix 1 is not converging (prompt still too large even at min batch / cap). Note a truncated reply is charged and returns HTTP 200, so `record_llm_request` records it as `status="success"` — that is *why* both the completion-token counter and the success-request counter include it, which makes the §5.3 avg-near-cap ratio valid.

### (b) Re-escalation loop (Fix 2) — observable end-to-end
The three lifecycle transitions and how to see each:
- **Arm:** after a 0-card full run, a synthetic `processing_failures` row `topicization:reescalation:<channel_id>` appears (written by `record_failure`, `error_class="TopicizationReEscalation"`, `topicization_service.py:360`). §6 SQL.
- **Skip while in cooldown:** subsequent ticks log `topicization re-escalation skipped (cooldown)` (`topicization_service.py:304`) and run the cheap incremental Phase 1/2 instead. The marker's `attempts` increments slowly (≤ ~1 per TTL = 3600s), NOT a full re-topicization every tick.
- **Clear on recovery:** a full re-escalation that **persists >0 cards** deletes the marker (`delete_failure`, `topicization_service.py:357`) — the §6 SQL row for that channel disappears and `tg_parser_topics_created_total{channel_id=...}` advances.
- **Pathological:** repeated `escalating to full topicization` (`topicization_service.py:313`) for the same channel on consecutive ticks (cooldown NOT arming), `attempts` not advancing or marker absent, and Sonnet token rate spiking each tick. Or `reescalation_marker_write_failed` / `reescalation_persisted_recount_failed` in logs — the persisted marker isn't being read/written (DB/repo issue) → the gate degrades to "no cooldown" → same unbounded burn as pre-fix.

---

## 4. Pre-top-up checklist (confirm GREEN before restoring credit)

Run from `ssh prod`, app dir `/home/user/TG_parser`:

1. **HEAD is the fix:** `git -C /home/user/TG_parser rev-parse HEAD` → `bdca97f...`. `docker compose ps` all healthy.
2. **Truncation metric is registered & scraped (currently 0):**
   `curl -s localhost:9090/api/v1/query --data-urlencode 'query=tg_parser_llm_truncation_total'` → series present (or absent-but-defined; it appears on first increment). Confirm endpoint exposes it: `docker compose exec tg_parser curl -s localhost:8000/metrics | grep -c tg_parser_llm_truncation_total`.
3. **Cooldown setting value:** `docker compose exec tg_parser python -c "from tg_parser.config import settings; print(settings.topicization_reescalation_cooldown_s)"` → `3600` (or the intended override). Also confirm models: `TOPICIZATION_LLM_MODEL=claude-sonnet-4-6`, `PROCESSING_LLM_MODEL=claude-haiku-4-5-...`.
4. **No stale re-escalation markers** from a prior run (clean baseline): SQL in §6 → expect 0 rows, or only expected stuck channels.
5. **Current backlog snapshot** (so you can measure drain): record unprocessed backlog (~16,489 at handoff; raw ~55,979 / processed ~39,489) and `murashko_med` coverage (~0.503). `tg_parser_channel_processed_coverage_ratio` per channel.
6. **Billing-block counter baseline:** note current `tg_parser_anthropic_billing_block_total` value; after top-up its `rate` must fall to 0.

---

## 5. What to watch — exact PromQL (scope with `job="tg_parser_api"` where relevant)

**Threshold arithmetic (so thresholds are defensible, not arbitrary).** Prod incident window 09:21–10:19 UTC (≈ 58 min = **3480 s**), `murashko_med`, one full re-topicization: **334 batches, 328 failed, 0 cards, ~2.38M Sonnet tokens** (1.56M prompt + 0.82M completion).
- Total token rate = 2.38e6 / 3480 = **684 tok/s** (≈ 41k/min).
- Completion rate = 0.82e6 / 3480 = **236 tok/s**.
- Failed-batch rate = 328 / 3480 = **0.094 batches/s** (≈ 5.6/min). The truncation *counter* is ≥ this (one oversized batch can record several truncations as it splits in halves), so the real `tg_parser_llm_truncation_total` rate in an incident is ≥ ~0.094/s and plausibly a small multiple.
- avg completion ÷ call ≈ **8097 ≈ the 8192 cap** (every call maxed its output budget). NB this divides by *all* calls (truncated calls are charged & counted), which is exactly what §5.3 reproduces.

**⚠ Scoping caveat for §5.2/5.3/5.8.** `tg_parser_llm_requests_total` and `tg_parser_llm_tokens_total` are **NOT stage-scoped** — they aggregate every Sonnet call (topicization generate/merge/discover **plus** any RAG/`ask`/resummarize traffic that also uses `claude-sonnet-4-6`). During a burn incident topicization dominates Sonnet volume by orders of magnitude, so these queries still fire; but treat them as *corroborating* signals. The **precise, stage-scoped** BUG-071 signal is `tg_parser_llm_truncation_total{stage=...}` (§5.1). Non-topicization Sonnet calls (smaller completions) bias §5.3 *downward* → the near-cap detector is conservative (fewer false positives, slight risk of masking).

**5.0 Confirm the exact Sonnet model label FIRST** (model strings can carry date suffixes — e.g. processing uses `claude-haiku-4-5-20251001`; the topicization Sonnet label is whatever `TOPICIZATION_LLM_MODEL` resolves to, from `factory.create_llm_client` `resolved_model`). The queries below use a `=~"claude-sonnet-4-6.*"` regex to be robust, but verify the real series first and tighten if needed:
```promql
count by (provider, model) (tg_parser_llm_tokens_total)
```

**5.1 Truncation rate (primary, stage-scoped — covers generate/merge/discover):**
```promql
sum(rate(tg_parser_llm_truncation_total[5m])) by (stage)
```
Healthy ≈ 0. **Warn** if `> 0.05/s` sustained 15m; **Critical** if `> 0.2/s` for 10m (≈ the pre-fix failed-batch rate — means the fix is not converging).

**5.2 Sonnet completion-token burn rate:**
```promql
sum(rate(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*",token_type="completion"}[5m]))
```
Baseline-bad ≈ 236 tok/s sustained. **Warn** if `> 150` tok/s for 15m with topics flat (see 5.4). Also watch total:
```promql
sum(rate(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}[5m]))
```

**5.3 Avg completion tokens per successful Sonnet call (near-cap detector):**
```promql
sum(rate(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*",token_type="completion"}[10m]))
/
sum(rate(tg_parser_llm_requests_total{model=~"claude-sonnet-4-6.*",status="success"}[10m]))
```
Healthy: hundreds–low thousands. **Alarm** if `> 6000` (approaching the 8192 cap = truncation pattern; baseline-bad ≈ 8097).

**5.4 Topicization producing cards (recovery signal):**
```promql
sum(rate(tg_parser_topics_created_total[15m]))
```
Verified to fire on **both** the full path (`topicization_service.py:139`) and the incremental discover path (`:490`), so it is a valid recovery signal for either. After top-up this should go **> 0**. The danger combo: 5.1/5.2 high while this stays 0 → burning without progress. ⚠ When the metric has *no* series yet (no card ever created), `sum(rate(...))` returns an empty vector, not `0` — so any rule comparing it to `0` must wrap it `(... or vector(0))` (see §7 P3) or it silently never fires.

**5.5 json-parse-retry rate by stage (should NOT absorb truncations now):**
```promql
sum(rate(tg_parser_llm_json_parse_retry_total{stage=~"topicization_.*"}[5m])) by (stage)
```
Watch it does not spike in lockstep with 5.1 (would mean truncations still misclassified as parse errors). `stage` ∈ {`topicization_generate`, `topicization_merge`, `topicization_discover`} (verified — generate retry at `topicization.py:406`); the `=~"topicization_.*"` matcher covers all three.

**5.6 Processing throughput / backlog drain:**
```promql
sum(rate(tg_parser_messages_processed_total{status="success"}[15m]))                 # should rise > 0 after top-up
sum(rate(tg_parser_messages_processed_total{status="error"}[15m]))
   / clamp_min(sum(rate(tg_parser_messages_processed_total[15m])), 1)                 # error share
min(tg_parser_channel_processed_coverage_ratio)                                       # lowest-covered channel trending up
```

**5.7 Billing block actually cleared:**
```promql
sum(rate(tg_parser_anthropic_billing_block_total[10m]))   # → 0 after a successful top-up
```

**5.8 Re-escalation detection (Prometheus proxy).** No direct metric for the cooldown; proxy = Sonnet token rate spiking once per tick while cards flat. The authoritative check is logs + SQL (§6). Useful proxy:
```promql
# Per-tick Sonnet token step. If this jumps ~hundreds-of-K each scheduler tick
# (hourly) for a 0-card channel, the cooldown is NOT arming.
increase(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}[1h])
```

---

## 6. Log lines / DB checks (exact patterns)

**Logs** (`docker compose logs -f tg_parser`, or `--since 15m`):

| Grep pattern | Meaning | Source |
|---|---|---|
| `re-escalation skipped (cooldown)` | ✅ Fix 2 working — full run suppressed, cheap incremental ran instead. | `topicization_service.py:304` |
| `escalating to full topicization` | A full re-escalation actually fired. Expected once per channel, then suppressed. **Repeated every tick for one channel = cooldown NOT arming.** | `topicization_service.py:313-317` |
| `Single batch dropped at the max_tokens cap (truncation)` | ✅ Fix 1 dropped a fully-truncated single batch (counts as `failed_batches=1`). | `topicization.py:264` |
| `truncated on a single candidate at the max_tokens cap` | A single candidate couldn't be shrunk further — investigate prompt size. | `topicization.py:508` |
| `TopicizationBatchTruncatedError` | Batch fully lost to truncation (raised). Frequency = the real failed-batch rate. | `topicization.py:52` |
| `reescalation_marker_read_failed` / `reescalation_marker_write_failed` / `reescalation_persisted_recount_failed` | ⚠ The cooldown store is erroring → gate degrading to "no cooldown" → burn risk. | `topicization_service.py:290,344,371` |
| `record_failure` ... `AnthropicBillingError` / `anthropic_billing_block` | Billing still blocking (top-up not effective). | scheduler/pipeline |

Quick one-liners:
```bash
docker compose logs --since 1h tg_parser | grep -c "re-escalation skipped (cooldown)"
docker compose logs --since 1h tg_parser | grep -c "escalating to full topicization"
docker compose logs --since 1h tg_parser | grep -E "TopicizationBatchTruncatedError|max_tokens cap"
docker compose logs --since 1h tg_parser | grep -E "reescalation_(marker|persisted)_"   # MUST be empty
```

**DB — synthetic cooldown markers** (table `processing_failures`; columns `source_ref, channel_id, attempts, last_attempt_at, error_class, error_message` per `processing_failure_repo.py`):
```sql
-- All armed re-escalation cooldowns + age. Healthy: few rows, attempts low,
-- last_attempt_at within the last TTL (3600s). attempts climbing fast or many
-- rows = channels stuck at 0 cards (expected to be throttled, NOT re-burning).
SELECT source_ref, channel_id, attempts, last_attempt_at, error_class
FROM processing_failures
WHERE source_ref LIKE 'topicization:reescalation:%'
ORDER BY last_attempt_at DESC;
```
Run on prod, e.g.:
```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
"SELECT source_ref, channel_id, attempts, last_attempt_at FROM processing_failures WHERE source_ref LIKE 'topicization:reescalation:%' ORDER BY last_attempt_at DESC;"
```
Interpretation: a row that **persists** with `attempts` incrementing ~once per TTL = the cooldown is correctly throttling a still-failing channel. A row whose `attempts` jumps every few minutes, OR `escalating to full topicization` logs with **no** matching marker row = the marker isn't persisting (investigate immediately — this is the unbounded-burn condition).

---

## 7. Alert rules (IMPLEMENTED — committed, NOT yet deployed)

**Status:** approved + implemented. The four rules below now live in group `tg_parser_bug071_topicization` in `docker/prometheus/alerts.yml`, with promtool unit tests in `docker/prometheus/alerts_test.yml` (firing + negative cases per rule, incl. the `or vector(0)` no-series scenario). Validated locally: `promtool check rules` (19 rules OK) + `promtool test rules` (SUCCESS) on promtool v3.12.0 (prod Prometheus is `prom/prometheus:v2.53.0` — rule/test schema compatible). **Not deployed:** Prometheus on prod has NOT been force-recreated; rolling them out is a separate `PRODUCTION_DEPLOYMENT.md` step. Thresholds grounded in the baseline (§5).

> **Self-review finding fixed during implementation:** the P2 draft used `clamp_min(denominator, 1)` to guard divide-by-zero. promtool exposed that this *defeats the rule at production scale*: topicization runs at ~0.03 req/s, so flooring the denominator at 1 collapses the avg-per-call ratio to the raw completion rate (~235) and it could never cross 6000. Fixed by dropping `clamp_min` (0/0 = NaN is naturally false) and adding an explicit `requests > 0` guard; the description now renders a clean integer via `printf "%.0f"`.

```yaml
  - name: tg_parser_bug071_topicization
    rules:
      # P1 — truncation rate spike: the BUG-071 re-burn canary. Healthy ~0.
      - alert: TopicizationTruncationSpike
        expr: sum(rate(tg_parser_llm_truncation_total[5m])) > 0.05
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Topicization max_tokens truncations sustained (>0.05/s)"
          description: "{{ $value }} truncations/s over 5m for 15m — Fix-1 shrink ladder may not be converging; check prompt/batch size."

      - alert: TopicizationTruncationBurst
        expr: sum(rate(tg_parser_llm_truncation_total[5m])) > 0.2
        for: 10m
        labels: { severity: critical }
        annotations:
          summary: "Topicization truncation burst (~pre-fix failed-batch rate)"
          description: "{{ $value }} truncations/s — at or above the pre-fix incident rate. Consider rollback / re-pause billing."

      # P2 — Sonnet near-cap completion (truncation pattern even if counter lags).
      # NB: do NOT clamp_min(denominator, 1) — topicization runs at ~0.03 req/s,
      # so flooring the denominator at 1 collapses the ratio to the raw completion
      # rate (~235) and the alert could never fire at production scale. 0/0 = NaN
      # (false) handles the no-calls case; the `requests > 0` guard rules out the
      # impossible +Inf case (completion tokens with no recorded request).
      - alert: SonnetCompletionNearCap
        expr: >
          sum(rate(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*",token_type="completion"}[10m]))
          /
          sum(rate(tg_parser_llm_requests_total{model=~"claude-sonnet-4-6.*",status="success"}[10m]))
          > 6000
          and
          sum(rate(tg_parser_llm_requests_total{model=~"claude-sonnet-4-6.*",status="success"}[10m])) > 0
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Sonnet avg completion tokens/call approaching 8192 cap"
          description: "Avg {{ $value | printf \"%.0f\" }} completion tok/call over 10m (cap 8192, baseline-bad ~8097) — output routinely maxing out = truncation."

      # P3 — burning without progress: token spend up, zero cards produced.
      # NOTE: `or vector(0)` on the topics side is REQUIRED — if topics_created_total
      # has no series yet (no card ever created post-deploy), sum(rate(...)) returns
      # an empty vector and `== 0` would never match, silently disabling the alert in
      # exactly the worst case (topicization producing nothing).
      - alert: TopicizationBurnNoProgress
        expr: >
          sum(rate(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*",token_type="completion"}[15m])) > 150
          and
          (sum(rate(tg_parser_topics_created_total[15m])) or vector(0)) == 0
        for: 30m
        labels: { severity: critical }
        annotations:
          summary: "Sonnet tokens burning but 0 topic cards created"
          description: "Completion-token rate high while topics_created flat for 30m — the BUG-071 burn-without-progress signature."

      # P3b — DIRECT failed-batch signal (replaces the failed-batch proxy; P3 kept
      # as a backstop for merge/discover/re-escalation burn that doesn't increment
      # failed_batches). Threshold mirrors P1 (0.05/s ≈ half the 0.094/s incident rate).
      - alert: TopicizationFailedBatchesHigh
        expr: sum(rate(tg_parser_topicization_failed_batches_total[15m])) by (stage) > 0.05
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Topicization failed-batch rate high ({{ $labels.stage }})"
          description: "{{ $value | printf \"%.3f\" }} failed batches/s on stage {{ $labels.stage }} over 15m — batches producing 0 usable topics (truncation-drops or hard errors). Drill down by channel_id on tg_parser_topicization_failed_batches_total."

      # P4 — billing block did not clear after top-up.
      - alert: AnthropicBillingStillBlocked
        expr: sum(rate(tg_parser_anthropic_billing_block_total[10m])) > 0
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Anthropic billing blocks still occurring after top-up"
          description: "Top-up may not be effective / wrong key — processing won't drain."
```
(There is no `failed_batches` series, so P1–P3 are the Prometheus-side stand-ins for "failed-batch ratio high"; pair them with the §6 log/DB checks for ground truth.)

---

## 8. Rollback triggers (concrete) → revert to `61637d1` and/or re-pause billing

Roll back (`git checkout 61637d1 && docker compose build tg_parser && docker compose up -d`) **and/or re-pause billing** (stop spend) if ANY of:

Every trigger below is measurable from a signal this plan already defines (no orphan triggers):

1. **Unbounded re-escalation** (signal: §6 logs + SQL) — `escalating to full topicization` for the same channel on ≥3 consecutive ticks with NO corresponding `processing_failures` marker row (cooldown not arming) → Fix 2 ineffective. **Re-pause billing immediately**, then roll back.
2. **Truncation burst** (signal: §5.1 / alert P1 `TopicizationTruncationBurst`) — `sum(rate(tg_parser_llm_truncation_total[5m])) > 0.2` sustained 10m, i.e. at/above the pre-fix incident rate, with `topics_created` flat.
3. **Burn-without-progress** (signal: §5.2 + §5.4 / alert P3) — Sonnet completion token rate > 150 tok/s for 30m while `topics_created` rate == 0.
4. **Cooldown store erroring** (signal: §6 logs) — any `reescalation_marker_write_failed` / `reescalation_persisted_recount_failed` (gate degrades to no-cooldown → burn risk).
5. **Cost guardrail** (signal: §5.8) — cumulative Sonnet tokens since top-up exceed a pre-agreed budget before any cards persist. Measure with:
```promql
sum(increase(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}[1h])) > 2.4e6
   and (sum(rate(tg_parser_topics_created_total[1h])) or vector(0)) == 0
```
(2.4e6 ≈ the single-incident ~2.38M/hr figure; tune the budget to the agreed spend ceiling.)

> Re-pausing billing is the fastest kill-switch (it re-makes the loop dormant) and is reversible; rollback is the code-level fix-the-fix. Prefer re-pause first if burn is active, then roll back calmly.

---

## 9. Observation timeline

**T+0 (top-up moment):** record the timestamp. Tail logs: `docker compose logs -f --since 1m tg_parser`.

**First 15 min:**
- Confirm billing cleared: 5.7 → 0; no `AnthropicBillingError` in logs.
- Processing resuming: 5.6 `messages_processed_total{status=success}` rate > 0.
- Watch 5.1 truncation rate and 5.4 topics-created as the first ticks with new docs hit topicization. Expect first `escalating to full topicization` for any 0-card channel — then verify a `re-escalation skipped (cooldown)` follows on the next tick and a marker row appears (§6 SQL).
- Hard stop check: if 5.1 ≥ 0.2/s or P3 conditions appear → §8.

**First 1 hour (≈ one scheduler tick cycle, TTL = 3600s):**
- Verify the cooldown completed a full cycle: at most ONE full re-escalation per stuck channel within the hour; `attempts` in the marker advanced by ~1, not by N.
- `topics_created_total` advancing for at least the active channels (recovery → markers being cleared via `delete_failure`).
- Avg completion/call (5.3) staying well below cap (< 6000).
- Backlog drain visible: processed count up vs the §4 snapshot; `min(coverage_ratio)` trending up.
- Token spend sane: `increase(tg_parser_llm_tokens_total{model=~"claude-sonnet-4-6.*"}[1h])` nowhere near the ~2.38M single-incident figure.

**First 24 hours:**
- Truncation counter flat or only occasional single increments; no `Burst`-level rates.
- No channel stuck re-escalating: re-run §6 SQL — markers should be transient (clear once a channel recovers) or stably throttled (attempts climbing ≤ ~1/hr), never a leaderboard of fast-climbing attempts.
- Backlog steadily draining; `murashko_med` coverage rising from ~0.503.
- Decide: if clean for 24h, close BUG-071 watch and (optionally, with approval) land the §7 alert rules + a Grafana truncation panel as permanent guardrails.

---

## 10. Notes / open items
- The §7 rules and a Grafana `tg_parser_llm_truncation_total` panel are **proposals**; deploying them is a separate, approval-gated change (and would force-recreate prometheus per `PRODUCTION_DEPLOYMENT.md`).
- All file:line anchors verified against working tree at HEAD `bdca97f`.

### Recommended FUTURE instrumentation (does NOT exist today — separate from the works-today queries above)
These would make the BUG-071 signals first-class in Prometheus instead of log/DB-only:
1. ~~**`tg_parser_topicization_failed_batches_total{channel_id, stage}`** (Counter)~~ — **DONE** (this change). `failed_batches` is now a direct Prometheus series incremented at the same sites as `TopicizationPipelineImpl.failed_batches`; alert P3b `TopicizationFailedBatchesHigh`. Counts truncation-drops AND non-truncation batch failures.
2. **Stage-scoped token counter** (still open) (e.g. add a `stage` label to a topicization-only token counter, or a `tg_parser_topicization_tokens_total{stage, token_type}`) — today `tg_parser_llm_tokens_total` mixes topicization with RAG/resummarize Sonnet traffic (see the §5 scoping caveat), so §5.2/5.3/5.8 can only be channel-/stage-blind.
3. **Re-escalation event counter** (e.g. `tg_parser_topicization_reescalation_total{channel_id, outcome=fired|skipped_cooldown|cleared}`) — Fix 2 is currently observable only via logs + the `processing_failures` SQL row; a counter would make §3(b) and rollback-trigger 1 alertable in Prometheus directly instead of via log-grep.

---

## Self-review changelog (adversarial review of the first draft)

**Verified REAL — exact name + labels confirmed in `tg_parser/api/metrics.py` (and emit paths):**
| Metric | Labels | Emit verified |
|---|---|---|
| `tg_parser_llm_truncation_total` | `provider, model, stage` | `metrics.py:111`; recorded at all 3 stages `topicization.py:420` (generate) / `:591` (merge) / `:1339` (discover) via `_record_truncation` (`:372`). `stage` values exactly `topicization_generate`/`topicization_merge`/`topicization_discover`. |
| `tg_parser_llm_tokens_total` | `provider, model, token_type` (`prompt`/`completion`) | `metrics.py:96`; emitted per call in `InstrumentedLLMClient.generate_with_usage` → `record_llm_request` (`instrumented.py:89-96`). prompt vs completion is the `token_type` label (NOT separate metrics). |
| `tg_parser_llm_requests_total` | `provider, model, status` (`success`/`error`) | `metrics.py:83`; same emit path. A charged-but-truncated reply = `status="success"` (no exception) → validates §5.3. |
| `tg_parser_llm_json_parse_retry_total` | `stage` | `metrics.py:153`; generate retry at `topicization.py:406`. |
| `tg_parser_llm_request_duration_seconds` | `provider, model` | `metrics.py:89`. |
| `tg_parser_anthropic_billing_block_total` | `stage` | `metrics.py:144`. |
| `tg_parser_anthropic_api_5xx_total` | `status` | `metrics.py:164`. |
| `tg_parser_messages_processed_total` | `channel_id, status` | `metrics.py:41`. |
| `tg_parser_topics_created_total` | `channel_id` | `metrics.py:47`; fires on full path (`topicization_service.py:139`) **and** incremental discover (`:490`). |
| `tg_parser_channel_processed_coverage_ratio` | `channel_id` | `metrics.py:943` (Gauge — use raw/`min`, not `rate`). |
| `tg_parser_scheduler_tasks_total` | `task_name, status` | `metrics.py:138`. |

**No hallucinated series.** Every metric referenced in PromQL/alerts/checklists exists as written.

**Corrections made (before → after):**
1. **Sonnet model matcher hardened** — `model="claude-sonnet-4-6"` → `model=~"claude-sonnet-4-6.*"` (9 sites). The label value is `factory.create_llm_client`'s `resolved_model` (= `TOPICIZATION_LLM_MODEL`); since other stages carry date suffixes (`claude-haiku-4-5-20251001`), the regex is robust if the deployed Sonnet label is dated. Added **§5.0** `count by (provider, model)(tg_parser_llm_tokens_total)` to confirm the real label first.
2. **`== 0` empty-vector gotcha fixed** — alert P3 and rollback-trigger-5 now wrap the topics term `(... or vector(0)) == 0`. Before: if `tg_parser_topics_created_total` had no series (no card ever created), `sum(rate(...)) == 0` returned empty → the alert silently never fired in the worst case. After: `or vector(0)` guarantees a `0` sample.
3. **Stage coverage made explicit** — §3(a), §5.1 (`by (stage)`), and §5.5 (`stage=~"topicization_.*"`) now explicitly cover generate **+ merge + discover**, not just generate. Called out that `topicization_discover` (incremental `_discover_single_batch`) can re-burn **independently** of the zero-card re-escalation.
4. **Scoping caveat added** — flagged that `tg_parser_llm_tokens_total` / `tg_parser_llm_requests_total` are NOT stage-scoped (mix RAG/resummarize Sonnet), so §5.2/5.3/5.8 are corroborating signals while §5.1 truncation_total is the precise one. Noted the dilution biases §5.3 downward (conservative).
5. **Threshold arithmetic shown** — §5 now derives 684 tok/s, 236 tok/s completion, 0.094 failed-batch/s, ~8097≈8192 from the incident (3480 s window), so P1/P2/P3 thresholds are defensible. Noted the truncation counter rate is ≥ the failed-batch rate (split fan-out).
6. **Fix-2 cooldown made observable end-to-end** — §3(b) now lists Arm (`record_failure` `:360`) / Skip (`:304` log) / Clear (`delete_failure` `:357`, marker row disappears) with the exact source lines and the matching §6 SQL.
7. **Rollback triggers de-orphaned** — each §8 trigger now cites the specific §5/§6 signal it reads from; trigger 5 got an explicit PromQL.
8. **Future-instrumentation gaps separated** — moved `failed_batches`-as-metric and added stage-scoped token + re-escalation event counters into a clearly-marked "does NOT exist today" subsection, distinct from works-today queries.

**Remaining caveats / assumptions:**
- §5.2/5.3/5.8 cannot be scoped to topicization-only until a stage-scoped token counter exists (future item #2); they rely on topicization dominating Sonnet volume during a burn (true in the incident).
- The truncation counter's `model`/`provider` labels come from `self.model_id` / `get_provider_from_client` and should equal the tokens/requests labels (both derive from the same `resolved_model`); confirm with §5.0 if a cross-metric join is ever needed.
- PromQL is hand-verified, not executed against a live Prometheus (none reachable from this environment); validate `count by (model)` and the P3 `or vector(0)` shape on prod before relying on the alerts. Proposed rules remain approval-gated and should ship with promtool cases in `alerts_test.yml`.
