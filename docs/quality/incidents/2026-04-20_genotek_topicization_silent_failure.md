# genotek topicization stuck at 0 topics after VPS reinstall — silent failure

**Date:** 2026-04-20
**Observed in:** production (VPS `redboxtgbot`)
**Component(s):** `topicization` · `scheduler` · `processing` · `observability`
**Severity:** P1 (silent failure on a production channel; manual CLI required to recover)
**Status:** fixed in code on 2026-04-25 (Sprint D.1 implemented, pending merge/deploy to production)
**Author:** external Claude agent on VPS, ingested into repo 2026-04-20

---

## Summary

After a full VPS reinstall on 2026-04-19, all 5 channels were re-ingested and a one-off full pipeline run was launched. Topicization succeeded for 4 channels. On the 5th channel (`genotek`) the pipeline hit Anthropic API `400 invalid_request_error` with body `"Your credit balance is too low..."` **on batch 6 of 22**. Batches 1–5 had already produced topics in memory, but because the exception propagated up to `scheduler_service._process_source`, the entire topicization transaction for the channel was rolled back. Zero `topic_cards` persisted.

Subsequent hourly scheduler runs never retry full topicization — they only call incremental topicization, which exits early with `"No topic cards found for channel genotek — all docs unassigned"` and never escalates back to full mode. The channel remained at 0 topics indefinitely, with no user-visible error (`get_pipeline_status` reports `success=true` every hour, `fail_count=0`, `last_error=null`).

After the Anthropic balance was topped up, the channel was repaired by running the full topicization CLI directly in the worker container. Result: 31 topics, 31 bundles, 83.81% coverage.

The incident surfaces three latent defects — see §5.

## 2. Final state (for verification)

```sql
SELECT src AS channel, COUNT(*) AS topics
FROM topic_cards, jsonb_array_elements_text(sources_json::jsonb) AS src
GROUP BY src ORDER BY src;
```

| Channel | raw_messages | processed_documents | topic_cards | coverage |
|---|---:|---:|---:|---:|
| AgeManagment | 1087 | 1083 | 75 | 74.52% |
| Lab4health | 1818 | 1790 | 165 | 92.91% |
| LongevityClub | 339 | 339 | 36 | 89.38% |
| labdiagnostica_logical | 1146 | 1130 | 79 | 77.43% |
| **genotek** | **1086** | **1081** | **31** | **83.81%** |

Repair run cost: 377 305 input + 56 515 output = 433 820 tokens.

## 3. Reproduction (incident timeline)

All timestamps UTC, sourced from `docker logs tg_parser` on `redboxtgbot`.

### 3.1 Initial failure (2026-04-19)

| Time | Event |
|---|---|
| 19:53:19 | `[1/4] Starting ingestion: source=genotek, mode=incremental` |
| 20:01:00 | `rate_limit_otpm_adjusted from=200000 to=160000` — rate limiter self-downgrades. Early warning sign. |
| 20:09:15 | `Running incremental topicization for genotek (1081 new docs)` |
| 20:09:16 | `No topic cards found for channel genotek — all docs unassigned` (expected after reinstall — no prior cards) |
| 20:09:16 | `Loaded 355 cross-channel topics as context (excluding channel=genotek)` |
| 20:09:16 → 20:11:55 | Batches 1/22 → 5/22 discover successfully: 14 + 2 + 1 + 1 + 0 = 18 new topics, 187 docs assigned. Still in-memory, uncommitted. |
| 20:11:56 | Batch 6/22 → API returns 400: `"Your credit balance is too low to access the Anthropic API..."`. `HTTPStatusError` raised from `anthropic_client.generate_with_usage`. |
| 20:11:56 | `Incremental topicization failed for genotek` — exception propagates to `scheduler_service._process_source`. Transaction rolls back. |
| 20:11:56 | `Source genotek completed: new_messages=1086, processed=1081` — scheduler logs success anyway. |

### 3.2 Dormant phase (2026-04-19 21:00 → 2026-04-20 13:50)

Every hourly scheduler tick logs for `genotek`:

```
[3/4] Topicization skipped (--skip-topicize)
```

This is **not** a per-channel config; it's how the scheduler's pipeline path is invoked. The scheduler uses `run_full_pipeline(skip_topicize=True)` and then separately calls `run_incremental_topicization` (in `scheduler_service._process_source`). Incremental mode requires prior topic cards to seed assignments — since there are none for `genotek`, every run short-circuits:

```
No topic cards found for channel genotek — all docs unassigned
```

and returns without calling the LLM. Result: 0 topics, forever, with no error.

In parallel, 5 specific messages (`post:823, 827, 1486, 1666, 1970`) keep failing in the processing stage (3 retries each, every hour) — but this is unrelated coincidence: they're stable dedup duplicates that hit the same 400 during message-level processing while the balance is empty. They populate `processing_failures` with 5 `ProcessingError` rows.

### 3.3 Repair (2026-04-20 ~15:50 UTC)

After topping up the Anthropic balance, run directly inside the worker container:

```bash
docker exec tg_parser bash -c \
  'tg-parser topicize --channel genotek --mode full > /tmp/topicize_genotek.log 2>&1'
```

Completed in ~4 minutes. Log confirms 22 batches processed in parallel (up to 5 concurrent), topics generated, bundles built via programmatic matching, final write:

```
Created 31 topic bundles
Coverage: 83.8% (906/1081 documents)
```

## 4. Root cause — exact API response

Recovered from `docker logs tg_parser`, logger `tg_parser.processing.llm.anthropic_client`:

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."
  },
  "request_id": "req_011CaDjqFatESLi6VfRb2ncm"
}
```

HTTP status: `400 Bad Request`. Important for the agent: Anthropic returns **400**, not 402 or 429, for insufficient credits. `error.type` is `invalid_request_error` — the same class used for malformed requests, oversized contexts, unsupported models, etc. Distinguishing features are **the message body** and (reliably) **the absence of credit in the billing API**.

Why `genotek` specifically: scheduling order. The other 4 channels completed topicization between 09:20 and 20:07; `genotek` started at 20:09. The balance hit zero at ~20:11. Any channel running at that moment would have been the victim.

## 5. Defects to fix

### 5.1 **[HIGH]** Incremental topicization becomes a permanent no-op if first full topicization fails

**Where:** `tg_parser/services/scheduler_service.py::_process_source` and `tg_parser/services/topicization_service.py::run_incremental_topicization`.

**Current behavior:** If a channel has 0 `topic_cards`, `run_incremental_topicization` logs a warning and returns without doing anything. The scheduler never escalates to full topicization.

**Impact:** Any transient failure during the first-ever topicization of a channel → channel is stuck at 0 topics until manual CLI intervention. No error surfaced to users (`list_channels` shows `topics_count: 0` but `status: active`, `get_pipeline_status` shows success).

**Fix:**
- In `run_incremental_topicization`, when no existing topic cards are found: fall through to full discovery (`run_full_topicization`) instead of returning early. The condition "no topic cards yet" is indistinguishable from "first run ever" and from "previous run rolled back" — both need the same treatment.
- Alternatively, maintain a `topicization_state` per source (`never_run`, `running`, `committed`, `failed`) in the `sources` table and dispatch to full or incremental accordingly.

**Acceptance:**
- Given a channel with processed_documents > 0 and topic_cards = 0, a scheduler tick completes with topic_cards > 0 (no manual CLI).
- A failure mid-run is visible: `sources.last_error` populated, metric `tg_parser_topicization_failures_total` incremented.

### 5.2 **[HIGH]** Whole-batch rollback wastes successful batches 1..N-1

**Where:** `tg_parser/processing/topicization.py::discover_new_topics` and its caller in `topicization_service`.

**Current behavior:** Batches are processed in-memory; the commit happens only after the whole loop finishes. A single failed batch → all prior batches discarded. In the incident, ~18 valid topics and 187 assignments from batches 1–5 were lost.

**Fix options** (pick one, prefer A):

- **A. Per-batch checkpoint.** After each batch returns successfully, persist its new topic cards + assignments inside a savepoint. On failure, the loop can abort but saved savepoints are kept. Requires idempotency if the batch is re-run (use `ON CONFLICT (id) DO NOTHING` for `topic_cards`).
- **B. Resumable run.** Track `last_completed_batch_idx` per (channel, run_id) in a new table `topicization_runs`. On failure, next scheduled call can resume at `last_completed_batch_idx + 1`.

**Acceptance:**
- Inject a 400 at batch 6 in an integration test. After the failure, `topic_cards` count for the channel ≥ number of topics created in batches 1–5. Re-running the pipeline does not duplicate topics.

### 5.3 **[MEDIUM]** `invalid_request_error: credit balance` is treated as retryable

**Where:** `tg_parser/processing/pipeline.py` (processing retries, 3× per message) and LLM wrapper `tg_parser/processing/llm/anthropic_client.py`.

**Current behavior:** Every 400 is raised as a generic `HTTPStatusError`. Processing retries 3 times per message. With 5 stuck messages × 3 retries × N hourly ticks, this burns `~15 × N` doomed API calls. When credit is eventually restored, the same retries keep happening at their scheduled cadence — fine — but during the outage they're pure noise and inflate error logs.

**Fix:**
- In `anthropic_client`, parse the JSON body of 400 responses. If `error.type == "invalid_request_error"` and `"credit balance"` in message (or use a more robust substring set), raise a typed exception `AnthropicBillingError` instead of `HTTPStatusError`.
- In `pipeline.py` retry loop and in `scheduler_service`, catch `AnthropicBillingError` and short-circuit: mark the channel with `rate_limit_until = now + backoff`, log once per window at ERROR level, emit a Prometheus metric `anthropic_billing_block_total`, do not retry in-process.

**Acceptance:**
- With a mocked 400 credit-balance response, a single run produces exactly 1 ERROR log, 0 retries, and increments the billing-block metric. No entries in `processing_failures`.

### 5.4 **[MEDIUM]** Scheduler reports success when topicization failed

**Where:** `scheduler_service._process_source`.

**Current log (from 2026-04-19 20:11:56):**

```
Incremental topicization failed for genotek: Client error '400 Bad Request'...
Source genotek completed: new_messages=1086, processed=1081
```

These two lines in the same second contradict each other. `source_attempts.success = true` is stored despite a critical stage failing. This is why the user-facing `get_pipeline_status` showed clean state while the channel was broken.

**Fix:**
- Aggregate per-stage outcome in `_process_source`. Mark `success=false` if any stage raised, even if others succeeded. Store the triggering exception class/message in `source_attempts.error_class` / `error_message`.
- `get_pipeline_status` already reads these fields; no API change needed.

**Acceptance:**
- In the incident's log window, `source_attempts` for `genotek` at 20:11:56 has `success = false, error_class = 'HTTPStatusError'` (or `AnthropicBillingError` after 5.3).

### 5.5 **[LOW]** `list_channels` coverage computed vs documents, not messages

Not a bug, but a clarification the agent should be aware of when working on §5.1 metrics: `coverage_percent` in `list_channels` is `(docs with at least one topic assignment) / processed_documents`, not `/ raw_messages`. Values around 74–93% are normal because raw messages include media-only posts, ads, and very short messages that processing drops.

## 6. Operational note: two ways to run topicization

The agent should not confuse these paths — they behave differently and use different code:

| Path | Entry point | Does ingestion? | Does full topicize? |
|---|---|---|---|
| MCP tool `trigger_pipeline` | `mcp_server._run_pipeline_background` → `run_full_pipeline` | **Yes** — requires `TELEGRAM_API_ID/HASH` | No (`skip_topicize=True` by default), then calls incremental |
| Scheduler hourly tick | `scheduler_service._process_source` | Yes | No — calls incremental |
| Worker CLI `tg-parser topicize --channel X --mode full` | `cli.topicize_cmd` → `run_full_topicization` directly | **No** | **Yes** |

During the repair, the MCP path failed with `ValueError: Missing Telegram API credentials` because the `tg_parser_mcp` container does not have Telegram secrets in its environment — it only needs them for ingestion, which is irrelevant to repair. **The CLI path was the only correct repair tool.**

Consider exposing the CLI path (full topicization on existing documents, no ingestion, no Telegram deps) as a dedicated MCP tool, e.g. `force_retopicize(channel_id)`. This would make repair operations doable from the Claude UI without SSH.

## 7. Suggested PR outline

1. **Core fix** (§5.1): make `run_incremental_topicization` fall through to full discovery when no prior cards exist. +tests.
2. **Durability** (§5.2): per-batch savepoint in `discover_new_topics`. +integration test that injects mid-run failure.
3. **Typed billing error** (§5.3): new exception class, parser in `anthropic_client`, short-circuit in retry loop. +metric.
4. **Observability** (§5.4): correct `source_attempts.success` on any stage failure. +alert rule suggestion in Grafana.
5. **Repair UX** (§6): new MCP tool `force_retopicize(channel_id, mode='full')` bound to `run_full_topicization`.

Each can ship independently. §5.1 + §5.4 are the minimum to prevent a silent repeat of this incident.

## 8. Reference artifacts

- Raw 400 response body: §4 above.
- Repair command: `docker exec tg_parser bash -c 'tg-parser topicize --channel genotek --mode full > /tmp/topicize_genotek.log 2>&1'`
- DB verification query: §2 above.
- Affected code modules (verified via stacktrace in log):
  - `tg_parser/services/scheduler_service.py:146` — `_process_source`
  - `tg_parser/services/topicization_service.py:264` — `run_incremental_topicization`
  - `tg_parser/processing/topicization.py:993` — `discover_new_topics`
  - `tg_parser/processing/topicization.py:1062` — `_discover_single_batch`
  - `tg_parser/processing/llm/instrumented.py:78` — `generate_with_usage` wrapper
  - `tg_parser/processing/llm/anthropic_client.py:173` — raw `response.raise_for_status()` (fix point for §5.3)
  - `tg_parser/services/pipeline_service.py:107, 132, 269` — pipeline orchestration, failure path
  - `tg_parser/mcp_server.py:1291, 1295, 1303, 1311` — MCP-triggered pipeline wrapper (context for §6)
- Ingress of evidence:
  - `docker logs tg_parser --since 48h` on `redboxtgbot`
  - `docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser`
  - MCP tools `tg-parser:list_channels`, `tg-parser:get_pipeline_status`

---

## Cross-references

- Triage: `docs/quality/TRIAGED.md` → Sprint D.1
- Sprint scope: `docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`
- Roadmap slot: `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` § "Параллельный трек — Sprint D (production hardening)"
- Future features: `docs/notes/FUTURE_FEATURES.md` § "Sprint D.1 — Topicization Hardening"
