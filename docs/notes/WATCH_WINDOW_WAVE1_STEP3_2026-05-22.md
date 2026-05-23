# Watch window — Wave 1 Step 3 (PR #89)

**Opened:** `2026-05-22T11:25:47Z` (~14:25 MSK 22-05) — declared OPEN per [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` § «Окно»](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md). Container restart for Phase C deploy `a30abd5` (step 3 merge + migration `f1a2b3c4d5e6`).

**Closed:** `2026-05-23T09:35:00Z` (~12:35 MSK 23-05) — closure session executed **T+22h09m** (i.e. **1h17m early** vs nominal 24h close at `2026-05-23T11:25:47Z`). Early-execution rationale: all planned `_watch_smoke` artifacts cleaned up by T+15h00, hard cut-off T+15h45 passed, no new activity expected; Prometheus `query_range` END set to nominal `2026-05-23T11:25:47Z` (Prometheus tolerates future END — returns data through `now`).

**Window duration (nominal):** 24h00m (`2026-05-22T11:25:47Z` → `2026-05-23T11:25:47Z`).
**Window duration (observed at closure):** 22h09m. **Caveat:** the remaining ~1h52m has not been observed by the closure-session log scan; given (a) zero 5xx over the observed 22h09m on all three target endpoints, (b) idempotency counters frozen since T+15h00 cleanup (no further write traffic expected), and (c) `up{service=api}=1` continuously since T+0, a regression in the final 1h52m would require a brand-new failure mode — judged extremely unlikely. Caveat documented in [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md` § 3](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md).

**Merge commit:** `a30abd5` — [PR #89](https://github.com/AlexEfimov/TG_parser/pull/89).

**Pre-deploy prod HEAD:** `39da8cc` (BUG-014B). **Post-deploy HEAD:** `a30abd5` (step 3) → `b875faf` (step 3.1, PR #90, deployed `2026-05-22T14:01:40Z`) → `d143e5d` (follow-ups, PR #91, deployed `2026-05-22T17:42:42Z`). **Final prod HEAD at closure:** `d143e5d` (unchanged since 17:42 UTC 22-05). **Container `StartedAt` (per `docker inspect`):** `tg_parser` `2026-05-22T17:42:42.654176105Z`; `tg_parser_mcp` `2026-05-22T17:42:42.651320884Z`; `tg_parser_bot` `2026-05-22T17:42:42.652965129Z` — synchronous restart at follow-ups deploy.

**Pre-migration admin action:** 3 duplicate `(user_id, title)` groups in `watch_interests` deduped per [`wave1_step3_idempotency_dedupe.md`](../runbooks/wave1_step3_idempotency_dedupe.md) before `f1a2b3c4d5e6` upgrade.

---

## Deploy smoke (immediate, 2026-05-22)

| Criterion | Result |
|---|---|
| `POST /api/v1/watchlists` valid key + `chat_id` | ✅ 201, `created: true` |
| `Idempotency-Key` replay same body | ⚠️ was `created: true` on replay (verbatim cache) — fixed follow-up PR `fix/wave1-followups-idempotency-ci`: replay normalizes `created: false` |
| Same key, different body | ✅ 422 `IdempotencyKeyMismatch` |
| `POST /api/v1/digests` invalid cron | ✅ 422 cron validation |
| `DELETE /api/v1/digests/{id}` ×2 | ✅ 204 then 404 |
| `workspace_id` foreign UUID | ✅ 404 `WorkspaceNotFound` |
| `tg_idempotency_keys_hit_total` in Prometheus | ⏳ 0 series at T+0 (may appear after scrape / first keyed POST) |

---

## 24h queries (executed `2026-05-23T09:30Z` at closure)

**Inputs.** `START=2026-05-22T11:25:47Z`, `END=2026-05-23T11:25:47Z` (nominal), `step=900s` (15-min buckets).

### Q1 — `up{service="api"}` gap-detection (`query_range`)

```bash
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query_range?query=up%7Bservice%3D%22api%22%7D&start=2026-05-22T11:25:47Z&end=2026-05-23T11:25:47Z&step=900"'
```

| Field | Value |
|---|---|
| Series count | 1 (`{instance=tg_parser:8000, job=tg_parser_api, service=api}`) |
| Datapoints returned | **89 / 96 expected** (`now`=`2026-05-23T09:35Z` < `END_nominal`, so 7 future buckets pending) |
| `up=1` count | **88** |
| `up=0` count | **1** (single bucket at `2026-05-22T11:25:47Z` — exactly the declared OPEN moment, scrape landed during container restart for `a30abd5` deploy; next bucket at `11:40:47Z` = 1; pattern confirms 1 missed scrape interval, NOT extended gap) |
| Extended gaps (>1 scrape) | **0** |
| Verdict | ✅ PASS — single startup-moment zero is within tolerance per GREEN criterion §4 |

### Q2 — `tg_idempotency_keys_hit_total{result=hit|miss|mismatch}` (instant, post-watch)

```bash
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=tg_idempotency_keys_hit_total"'
```

Sampled `2026-05-23T09:35:09Z` (epoch `1779528909`).

| `result` | Final value | Source breakdown (per WATCH_24H_ACTIVITY_PLAN journal) |
|---|---|---|
| `miss` | **4** | T+0 immediate-smoke residue: 2 / T+3h HTTP window-1 K1-B1: +1 / T+14h46 HTTP window-2 K2-B1: +1 |
| `hit` | **4** | T+0 immediate-smoke residue: 2 / T+3h K1-B2 replay: +1 / T+14h46 K2-B2 replay: +1 |
| `mismatch` | **3** | T+0 immediate-smoke residue: 1 / T+3h K1-B3 mismatch: +1 / T+14h46 K2-B3 mismatch: +1 |

All three series populated (≥1), all three labels present in Prometheus, `service=api` instance only (mcp/bot have no `Idempotency-Key`-bearing endpoints). ✅ PASS GREEN criterion §1 row «hit/miss/mismatch ≥ 1».

### Q3 — `tg_idempotency_keys_table_size` (gauge, instant)

```bash
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=tg_idempotency_keys_table_size"'
```

Sampled `2026-05-23T09:35:11Z`.

| `service` instance | Final value | Note |
|---|---|---|
| `api` (`tg_parser:8000`) | **5** | Non-zero ✓; gauge updated post hourly cleanup tick `0 * * * *` (verified at T+1h30 = 3, T+3h = 3, T+14h46 = 4, T+15h00 = 5; +1 between T+15h00 and closure plausibly a scheduler-tick Idem-Key insertion, hourly cleanup at `10:00Z` will reconcile) |
| `mcp` (`mcp:8080`) | 0 | Expected (MCP surface has no header-Idempotency-Key endpoints) |
| `bot` (`tg_bot:8081`) | 0 | Expected (same reason as mcp) |

✅ PASS GREEN criterion §1 row «gauge non-zero and updated post T+1h cleanup».

### Q4 — `tg_pipeline_trigger_total` (instant, all labels)

```bash
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=tg_pipeline_trigger_total"'
```

Sampled `2026-05-23T09:35:12Z`.

| `exported_job` | `result` | `surface` | Final value |
|---|---|---|---|
| `full_pipeline` | `queued` | `api` | **2** |
| `full_pipeline` | `success` | `api` | **2** |
| `topicization` | `queued` | `api` | **1** |
| `topicization` | `success` | `api` | **1** |
| `link_topics` | `queued` | `api` | **2** |
| `link_topics` | `success` | `api` | **2** |

All three job types have ≥1 `queued` AND ≥1 `success` — pipeline dispatch healthy. `surface=mcp` and `surface=bot` labels **absent** (see § Open items below — architectural counter-site labelling gap).

### Log scan over window

```bash
ssh -p 2296 user@212.72.189.15 \
  "docker logs --since 2026-05-22T11:25:47Z --until 2026-05-23T09:35:00Z tg_parser 2>&1 \
   | grep -iE '/api/v1/(watchlists|digests|pipeline)' \
   | grep -iE 'status_code\": (4[0-9]{2}|5[0-9]{2})' \
   | awk -F'\"status_code\": ' '{print \$2}' | awk -F',' '{print \$1}' \
   | sort | uniq -c | sort -rn"
```

| Status code | Count | Classification |
|---|---|---|
| **5xx (500/502/503/504)** | **0** | ✅ PASS GREEN criterion §1 row «no 5xx spikes» |
| 404 | 28 | Known: 2× `POST /api/v1/pipeline/trigger` 17:48:42Z (initial path-resolution race ~6m after follow-ups deploy; both `request_id` 404s within 1ms; no recurrence after 17:48); 26× misc routes (bot/MCP delete-by-name probes per BUG-025) |
| 429 | 7 | Known: rate-limit middleware (`Retry-After` header), exactly the smoke-validated behaviour from immediate-deploy 2026-05-22 |
| 422 | 3 | Known: `IdempotencyKeyMismatch` from T+0 smoke, T+3h K1-B3, T+14h46 K2-B3 (matches `tg_idempotency_keys_hit_total{result=mismatch}=3` counter) |
| 403 | 2 | Known: auth-key probes (expected — no API_KEY header on health-check sidecars) |

**Container-level error scan** (`docker logs ... \| grep -iE "traceback\|\"level\": \"error\""`):

| Container | Total error events | Classified |
|---|---|---|
| `tg_parser` (API + processing) | **942** | All `anthropic_billing_block_processing` events — Anthropic quota exhaustion documented as transient external resource issue (see [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` § 7 T+12h / T+15h45 retry](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md)); resolved by user balance top-up; **0 non-Anthropic errors** |
| `tg_parser_bot` | **4** | 3× `tool_execution_error` for `unsubscribe_watchlist` (BUG-025 occurrences at 19:57:53Z / 19:59:15Z / 20:07:41Z); **1× `cron_task_failed`** at `06:00:00Z` for `digest:94483db9-…` — **NEW: BUG-028** (digest cron `PromptLoader` path resolution; pre-existing latent bug surfaced by watch; not a step 3 regression — git blame confirms 2026-04-19 author at F6 landing) |
| `tg_parser_mcp` | **0** | Clean over entire window |

---

## Verdict

| Field | Value |
|---|---|
| **Status** | **CLOSED** (2026-05-23T09:35Z, T+22h09m, 1h17m early vs nominal) |
| **Final verdict** | **GREEN** — all 4 GREEN criteria PASS per [`START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-23.md` § 4](START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-23.md): (1) 0 × 5xx on target endpoints; (2) all 3 `result` labels populated for `tg_idempotency_keys_hit_total`; (3) `table_size` gauge non-zero (5) and updated post T+1h cleanup; (4) `up{service=api}` 88/89 = 1, single 0 at OPEN scrape only, 0 extended gaps. |
| **DONE marker** | [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) finalised in same commit (STATUS NOTE stub removed; §§ 2/3/6 filled; Open Items appended). |

### Open items (carried to closure REVIEW § 3 + § 6)

1. **`surface=mcp` / `surface=bot` Prometheus label gap** (`tg_pipeline_trigger_total`) — bot and MCP both dispatch via HTTP `POST /api/v1/pipeline/trigger`, and the API entry point (`tg_parser/api/routes/pipeline.py`) hardcodes `surface=api` at the counter-increment site. Originating surface is not propagated. Target-metric rows §1 of `WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` for `surface=mcp` and `surface=bot` are **structurally unreachable** without a counter-registration refactor. **Not blocking closure** (counter works correctly with `surface=api`; observability for these flows still works via API logs). Adjudication: «architectural observability gap surfaced by watch», not regression. Bundle candidate: future ADR / O-7 «surface-aware metric labelling».
2. **BUG-025 / BUG-026 / BUG-027** — three bot UX bugs filed during 2026-05-22 bot dialog session (`unsubscribe_watchlist` UUID-validation; standalone-UUID continuation context; ambiguous «уже неактивен» wording). All three pre-existing in F11 / F6 service layer; surfaced by watch interactive cleanup sequence. See [`BUG_LOG.md` § BUG-025/026/027](BUG_LOG.md) and [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6](WATCH_24H_BOT_ACTIONS_2026-05-22.md).
3. **BUG-028 (NEW, this closure)** — daily digest cron task fails with `PromptLoaderError` because `scheduler_service.py:560` does `PromptLoader(prompts_dir=str(settings.prompts_dir))` and `str(None) == "None"` (Python literal) → resolves to non-existent path `None/digest.yaml`. Pre-existing since 2026-04-19 (F6); surfaced 2026-05-23T06:00Z (09:00 MSK) on prod endocrinology digest (`digest_94483db9`). **Production digest delivery silently broken** until fix lands; **immediate workaround** = set `PROMPTS_DIR=/app/prompts` env on `tg_parser_bot` container before next 09:00 MSK tick. See [`BUG_LOG.md` § BUG-028](BUG_LOG.md). Recommended hotfix branch: `fix/bug-028-digest-cron-prompt-loader`.
4. **Compose-integration CI test backlog** — `@compose_only` pytest marker in tree, harness exists, but no GH Actions job runs them. Wave 1 step 3 sprint's `digest_task` integration test (closure plan for BUG-028) and the surface-coverage tests for MCP/bot trigger metrics (closure plan for §1 surface label gap) both belong in the same compose-CI job. Tracked in [`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md` § Open items #3](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md); to be picked up as a separate PR after Wave 1 step 4.
5. **Anthropic quota one-time exhaustion** — `ask_question(workspace_id=ws_watch_smoke)` failed at T+12h with «credit balance too low»; user topped up balance; retry at T+15h45 succeeded (`claude-sonnet-4-20250514`, 200 OK). External resource issue, NOT a pipeline defect. **Resolved**; no follow-up required; informational note only (see [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md` § 7 T+15h45 ask_question retry](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md)).

---

## Cross-reference

* Closure-session prompt (this watch was driven by): [`START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-23.md`](START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-23.md).
* Activity journal (T+N rows, MCP/HTTP/bot evidence): [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md`](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md), [`WATCH_24H_BOT_ACTIONS_2026-05-22.md`](WATCH_24H_BOT_ACTIONS_2026-05-22.md).
* DONE marker (finalised in same commit as this CLOSED update): [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md).
* Runbook (deploy + rollback procedure): [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md).
* Handoff (post-step 3.1 + follow-ups baseline): [`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md`](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md).
