# WAVE1_TECH_DEBT — consolidated Wave 1 technical-debt inventory

**Дата:** 2026-06-12
**Scope:** Wave 1 (steps 1–4 + ops step 5), closed per
[`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md). This note
consolidates the technical-debt findings surfaced across two prior
investigations (the F11 watchlist S1–S3 sub-sessions and the Wave 1 closure
review) into a single, traceable inventory.
**Status of this document:** normative inventory + traceability map. It does
**not** replace [`BUG_LOG.md`](BUG_LOG.md) — every actionable item below is (or
becomes) a `BUG-NNN` / `TD-…` entry there. This note is the *map*; BUG_LOG is
the *backlog of record*.
**Maintainer convention:** when an item here is closed, flip its status in
BUG_LOG first, then update the cross-reference in § A below. Do not duplicate
fix narratives here — link to the BUG_LOG entry.

> **γ3 closeout 2026-07-20:** actionable §A inventory remains **closed** (only
> BUG-008 still `open` by-design → γ1′). §C F5-B Phase 1 disposition updated
> to **Rejected** (was stale «GATED»). Full prune/keep table:
> [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md).

---

## 0. Purpose & framing

Wave 1 delivered the Living-KB MVP surface parity, F4-B workspaces, the F6
digest + F11 watchlist features, and the ADR 0010–0014 watchlist scoring
rework. As with any MVP cut, a tail of **genuine technical debt** accumulated
alongside a set of **documented deferrals / intended-design decisions** that
are frequently *mistaken* for debt. This document separates the three classes
so a future Wave 2 planning session can triage without re-deriving the
analysis:

- **(A) Open actionable debt** — real gaps worth fixing; each tracked in
  BUG_LOG.
- **(B) Accepted / by-design** — recorded for traceability so they are not
  re-filed as bugs. Each anchored to an ADR.
- **(C) Forward-roadmap (MVP→P2)** — planned features, explicitly **out of
  Wave-1-debt scope**.

A quick-reference "genuine debt vs intended design" table is in § D.

---

## A. Open actionable debt

> **Track status: CLOSED 2026-06-13.** All actionable items below were resolved
> across the Wave A–C closure track (see per-row commit-refs); the only item
> still `open` is **BUG-008** (MCP transport hang), which is explicitly
> **deferred** and out of this tech-debt track. New entries were filed
> 2026-06-12 under BUG_LOG § "Wave 1 tech-debt consolidation"; pre-existing
> items are referenced by their existing ID (not re-filed).

### A.1 — Already tracked in BUG_LOG (reference only)

| ID | Description | Category | Severity | File refs | Status |
|---|---|---|---|---|---|
| [BUG-019](BUG_LOG.md) | LLM JSON-parse retry resends the identical prompt → deterministic triple-fail on the malformed-JSON path | pipeline / reliability | Medium | `tg_parser/processing/pipeline.py` (retry block); `processing/topicization.py` | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — retry-hint helper + non-retryable JSON reclass + `llm_json_parse_retry_total{stage}`) |
| [BUG-020](BUG_LOG.md) | No exponential backoff / jitter for Anthropic HTTP 5xx (520 / 529 / 503); bundle with BUG-019 | pipeline / reliability | Low | `tg_parser/processing/pipeline.py` (HTTP client wrapper) | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — `520` added to retryable 5xx + `anthropic_api_5xx_total{status}` + `test_520_retries_then_succeeds`) |
| [BUG-021](BUG_LOG.md) | `get_cross_channel_stats` ignores the `topic_links` table (keyword overlap only; semantic links never surfaced) | analytics / MCP | Medium | `tg_parser/services/analytics_service.py`; `mcp_server.py` `get_cross_channel_stats` | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — backward-compatible `topic_link_stats` section, scope-respecting; no `prompts/bot.yaml` bump needed) |
| [BUG-008](BUG_LOG.md) | MCP `list_channels` via `CallMcpTool` hung ~3.5 h; root cause unknown, repro flaky | MCP runtime / transport | pending (→ Med-High if it recurs) | MCP remote endpoint `mcp.tgp.efimov.mobi/mcp`; layer not localized | `open` (H1 server-side mitigation landed 2026-06-18, commit 5165875 — batched stats + read-scoped statement_timeout; still open pending live recurrence / transport H3) |

### A.2 — Code-level debt (filed 2026-06-12)

| ID | Description | Category | Severity | File refs | Status |
|---|---|---|---|---|---|
| [BUG-054](BUG_LOG.md) | Watchlist interest update path (`_apply_upsert`) updates keywords/description/channels but never re-embeds or recalibrates the threshold | backend correctness / watchlist | Medium | `tg_parser/services/watchlist_service.py:948–1086` | ✅ `resolved` (Wave B 2026-06-13; commit 24352bf — ADR-0015 HYBRID re-embed + recalibration; `threshold_source` provenance column + migration `b9c8d7e6f5a4`; MCP/bot/HTTP advisory) |
| [BUG-055](BUG_LOG.md) | `check_interests` hot-path N+1: per-ref `get_by_source_ref` while backfill/calibration use batched `get_many_by_source_refs` (partial ADR-0011 adoption); `notify()` re-fetches each interest in-loop as a secondary site | performance / watchlist | Low | `watchlist_service.py:1148` (+ `1508` notify); batched path at `1367` / `1762` | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — single batched `get_many_by_source_refs` + `notify()` interest map; N+1 regression test added) |
| TD-bot-confirm-coverage-completeness | `_WRITE_TOOLS_REQUIRING_CONFIRM` lacks admin write tools (`register_user`, `add_user_auth`, …); decision-matrix completeness gap | bot / safety | Low-Medium | `tg_parser/bot/tools.py:99–103` | ✅ `resolved` (Wave C 2026-06-13; commit a35bcb4 — admin write-tool quartet `register_user`/`update_user`/`add_user_auth`/`remove_user_auth` joined the two-phase preview/confirm contract: `confirm: BOOLEAN` in each declaration + frozenset membership + per-tool executor preview/confirm pattern; bot.yaml v1.7.8 → v1.7.9 consolidated admin-confirm HARD RULE; one parametrized confirm-flow test family (`tests/test_bot_admin_confirm_flow.py`) + guard baseline + version-floor updated. `reload_prompts` / `export_channel` deliberately left out of scope) |

### A.3 — Test / infra debt (filed 2026-06-12)

| ID | Description | Category | Severity | File refs | Status |
|---|---|---|---|---|---|
| [BUG-056](BUG_LOG.md) | `conftest._reset_test_db_schema` does `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public`; races under parallel Postgres runs → `DuplicateSchema` (transient 375-error PG run observed) | test infra | Medium | `tests/conftest.py:125–161` | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — `pg_advisory_lock` around reset + idempotent head-revision check; README parallel-mode note) |
| [BUG-057](BUG_LOG.md) | Stale pre-fix `skipif` guards remain after the gated helpers landed (always-imported now) | test hygiene | Low | `tests/test_bot_chat_target_resolution.py:240`; `tests/test_bot_channel_name_parser.py:282+` (6×); `tests/test_bot_delete_routing_bug047.py:823` | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — guards removed, helpers imported directly; broken import now hard-fails) |
| TD-confirm-flow-concurrency-integration | Skipped two-confirm race test, deferred to an integration harness | test coverage | Low | `tests/test_bot_confirm_flow.py` → `TestSerializedTwoConfirms::test_serialized_two_confirms_second_rejected` | ✅ **`resolved` (Wave A closure, option C — 2026-06-13; commit 759adfd)** — replaced the `@pytest.mark.skip` placeholder with a deterministic **sequenced** test (no real threads/parallelism). Models the post-serialization order: confirm #1 runs the real handler → real `execute_tool` → BUG-009 guard (passes) → exactly one executor side-effect, then the handler clears the FSM ConfirmFlow state; confirm #2 reaches `execute_tool` stateless (`confirm_flow_state=None`) → rejected with `error_class="ConfirmFlowMismatch"`, no second side-effect. aiogram's framework-owned per-(chat_id,user_id) serialization is explicitly out of scope. |
| TD-test-isolation-execute-tool-leak | Cross-module mock leak of `tg_parser.bot.handlers.execute_tool` under full-suite ordering — a bot test leaves the symbol patched without restoring it | test hygiene | Low | culprit localized: `tests/test_bot_clarify_concurrency_bug051.py::test_overlapping_clarify_responses_execute_once` (per-task `with patch(...handlers.execute_tool)` re-entered concurrently); victim `tests/test_bot_confirm_flow.py::TestSerializedTwoConfirms` | ✅ `resolved` (Wave 1 closure, 2026-06-13; **commit-ref: 128e5db**) — root cause: two overlapping `asyncio` tasks each entered the SAME `with patch("tg_parser.bot.handlers.execute_tool", new=slow_execute)`; the second `__enter__` ran while the first patch was still active and captured the *mock* as its "original", restoring the mock (not the genuine function) on exit → leak under collection order (`clarify` < `confirm`). Fix: hoist the patch to a single enclosing context wrapping the whole concurrent section (both turns still overlap). Defensive pin in `TestSerializedTwoConfirms` removed (BUG_LOG confirms it existed solely for this leak); replaced with a resolved-note comment. Proof: leaker→victim order fails without fix / pin removed; passes with fix. Full PG suite `3283 passed, 20 skipped, 2 deselected` (unchanged baseline); ruff clean. See BUG_LOG § TD-test-isolation-execute-tool-leak. |

### A.4 — Observability / CI debt (filed 2026-06-12)

| ID | Description | Category | Severity | File refs | Status |
|---|---|---|---|---|---|
| [BUG-058](BUG_LOG.md) | `tg_pipeline_trigger_total{surface}` only ever emits `surface="api"`; the `mcp` / `bot` label values are unreachable because MCP/bot dispatch through the same HTTP endpoint which hardcodes the label | observability | Low | `tg_parser/api/routes/pipeline.py:89`; `services/pipeline_dispatch_service.py:95–153` | ✅ `resolved` (Wave C 2026-06-13; commit bf26a72 — `X-Trigger-Surface` header threaded client→route, validated against `{api,mcp,bot}` + clamp-to-api; ADR-0007 addendum; client+route tests) |
| [BUG-059](BUG_LOG.md) | No GitHub Actions job brings up docker-compose and runs the `@compose_only` integration tests; default CI is `-m 'not integration'` so they never run in CI | CI coverage | Low | `.github/workflows/ci.yml`; `tests/test_compose_pipeline_dispatch_integration.py:27,90` | ✅ `resolved` (Wave A 2026-06-13; commit f254274 — `compose_only` marker registered, test implemented, nightly/main-push `compose-integration` CI job added) |
| [BUG-060](BUG_LOG.md) | Monitoring alert rules that assume `combined ≈ 0.4·kw + 0.6·sem` will false-flag keyword-only rows (combined=1.0 / semantic=0.0 when `semantic_available=False`). Alerts must gate on `semantic_available`. **Scoring is intended (see § B); only the alert rule is debt.** | ops / monitoring | Low | Grafana watchlist score rules; `watchlist_service.py` scoring path | ✅ `resolved` (2026-06-14 — provisioned the BUG-060-safe **delivery** alert `WatchlistDeliveryErrors` in `docker/prometheus/alerts.yml`, promtool-validated; targets `tg_watchlist_delivery_total{outcome="error"}`, independent of the score blend → no scoring/metric change. The literal **gated score alert** is **explicitly deferred to Wave 2** (see § C "Gated watchlist score alert") because `WATCHLIST_SCORE` has no `semantic_available` label to gate on — adding it is a metric/scoring-path change out of scope here. Earlier Wave C 2026-06-13 commit bf26a72 had landed the doc-only preventive groundwork — ⚠️ warning in `F5C_DEPLOY_AND_WATCH.md` + guide comment in `wave1_step4.yaml`.) |

### A.5 — Doc-hygiene tasks (noted, mostly not fixed inline)

These are documentation-drift items. Only one was trivially fixable inline in
this session (marked **fixed**); the rest are recorded as doc-hygiene tasks for
a future cleanup commit.

| Item | Where | Disposition |
|---|---|---|
| **DOC-001** — stale bot username `@smoke_tgparser_bot` (actual: `@Tgingest_bot`) | [`docs/prompts/DEV_RESURRECTION_PROMPT.md:26`](../prompts/DEV_RESURRECTION_PROMPT.md) | ✅ **resolved** (Wave C 2026-06-13; commit bf26a72) — live prompt already corrected in `a06f428` (now `@Tgingest_bot` at `:49`); grep confirms only historical notes/runbooks retain `@smoke_tgparser_bot` (intentionally not edited). Marked resolved in BUG_LOG § Documentation cleanup TODOs. |
| BUG-005-B narrative still reads `status: open` though the master Status field is `resolved` (Session F) | `BUG_LOG.md` (investigation narrative, ~L2096–2098) | **fixed inline** 2026-06-12 (added closure marker; historical narrative preserved) |
| Stale `START_PROMPT` inventory | [`REVIEW_2026-06-03_WAVE1_DONE.md` § 11](REVIEW_2026-06-03_WAVE1_DONE.md) | ✅ **updated** (Wave C 2026-06-13; commit bf26a72) — added a lightweight pointer in § 11 to `START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md` noting the inventory is superseded by the Wave A–C closure track; listed prompts not bulk-edited |
| ROADMAP Wave D + PLANNING_NEXT list F11 P2 / batch / threshold as "future" — superseded by ADR 0010–0014 | [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md` L312–316](ROADMAP_KARPATHY_LIKE_LIVING_KB.md); `PLANNING_NEXT_CONTRACT_PREP.md` | ✅ **updated** (Wave C 2026-06-13; commit bf26a72) — added ADR-0010–0014 supersession notes to ROADMAP Wave D and PLANNING_NEXT (Candidate 1 marked completed); structure preserved. The TD-bot-confirm-coverage-completeness backlog line in PLANNING_NEXT was subsequently flipped to resolved (commit a35bcb4) in the 2026-06-13 doc-hygiene pass. |

---

## B. Accepted / by-design — NOT debt (recorded for traceability)

The following were surfaced during the same investigations and **look like
debt but are intentional**. They are listed here so they are not re-filed as
bugs. Each is anchored to its governing ADR.

| Item | Why it is by-design | ADR |
|---|---|---|
| `combined = 1.0` / `semantic = 0.0` for keyword-only rows | Keyword-only mode (when `semantic_available=False`) is the intended fallback scoring shape; combined is not the weighted blend in that mode | ADR-0010 / ADR-0011 |
| `min_threshold = 0.45` precision floor | Deliberate floor to avoid pathological low cutoffs | ADR-0013 |
| Synchronous calibration latency at interest create | Full-corpus scoring runs synchronously; acceptable at current scale | ADR-0012 §R4 |
| Batch cron lives in the bot process | Single-replica deployment; co-locating the batch scheduler is intended | ADR-0014 |
| SILENT journal entries marked `notified=True` | Intentional bookkeeping for silent-delivery batch | ADR-0014 |
| `skipped_non_instant` behaviour | Intended batch-delivery semantics | ADR-0014 |
| O-1 non-atomic workspace move (remove + add) | MVP decision; atomic move explicitly deferred | F4-B Core MVP (ADR-0004 boundaries) |
| Q6 polymorphic targets absent from HTTP schemas | Intended HTTP surface cut for Wave 1 | ADR-0008 |
| Idempotency-key scope | Deliberately scoped | ADR-0009 |
| Streaming scorer deferred | Sync full-corpus scoring is the chosen MVP path | ADR-0011 / ADR-0012 |
| Knee / gap threshold detection rejected | Fragile on small samples; explicitly rejected | ADR-0012 / ADR-0013 |

> **NB on BUG-060:** the *scoring* shape (`combined=1.0`, `semantic=0.0` in
> keyword-only mode) is by-design and lives in this table. The *alert rule*
> that fails to account for it is the debt and lives in § A.4.

---

## C. Forward-roadmap (MVP → P2) — out of Wave-1-debt scope

These are **planned features**, not Wave-1 cut corners. Listed only to avoid
conflating roadmap with debt.

- **F5-C P2** — evolving topic-summary phase 2 (issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15)).
  - ✅ **Wave 2 (2026-06-14, T7):** item **#4 time-based re-summarize trigger**
    (`RESUMMARIZE_MAX_AGE_DAYS`, OR-predicate keeping `new_items > 0`) +
    item **#10 per-channel re-summarize metric** (real `channel_id` in
    `tg_resummarize_total{channel_id}`) shipped. Remaining #15 backlog
    (TTL, diff-API, F6 topic-digest, bot-tools, type-promotion, topic-dedup,
    item-removal, HTTP API) stays open.
- **F5-B near-duplicate dedup** — ADR-0016. ✅ **Wave 2 (2026-06-14, T1):**
  Phase 0 observation-only counter (intra+cross axes) shipped. **Phase 1
  (actual dedup) — `Rejected — rate below threshold` (2026-07-20):** measured
  intra 0.055 % / cross 0.000 % (N=32 805) ≪ 5 % gate → not built; Phase-0
  counter remains permanent observability. Do not reopen without new signal.
- **Bot-UX hygiene (TD-D-01/02/03)** — ✅ **Wave 2 (2026-06-14, T3/T4/T5):**
  pagination_pending coverage + rich-deterministic renderer unification +
  `_format_tool_result` fallback + contract-tests. See `BUG_LOG.md`
  "TD from Session D" resolution block.
- **F11 HTTP CRUD** — watchlist CRUD over the HTTP API surface.
- **S4 multilang tokenizer** — multi-language keyword tokenization.
- **F1 Full** — DB-backed prompts / versioning / A-B testing.
- **Webhook subscription target** — ADR-0008 polymorphic target → Wave 2A.
- **Gated watchlist semantic-availability alert — ✅ DONE (T6, commit `eead91e`).**
  - *Why:* catches silent degradation of F11 semantic scoring (e.g.,
    embedding provider down → everything falls back to keyword-only). The
    provisioned `WatchlistDeliveryErrors` alert (BUG-060, see § A.4) only
    catches push-delivery failures, **not** match-quality degradation.
  - *How shipped (option B — dedicated counter):* added a dedicated
    `tg_watchlist_semantic_unavailable_total{reason}` counter
    ([`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py)) incremented
    on the `semantic_available=False` branch of the scoring path in
    [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py),
    plus the `WatchlistSemanticUnavailableHigh` Prometheus rule. A **dedicated
    counter was chosen over a `WATCHLIST_SCORE` histogram relabel** to avoid
    adding cardinality to the score metric and to sidestep the false-fire risk
    on keyword-only rows (`combined=1.0`, § B, by-design per ADR-0010/0011).
  - *Background:* originally swapped out of Wave 2 for T7 F5-C P2 freshness
    (see `PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md` §3 Fork 4 / §4a); picked up
    and shipped this session. Cross-ref: BUG-060 (§ A.4, delivery alert; this
    semantic-availability alert was its deferred follow-up, now done).

---

## D. Quick reference — genuine debt vs intended design

| Symptom you might observe | Verdict | Anchor |
|---|---|---|
| Updated watchlist keeps stale threshold / embeddings | ✅ resolved (Wave B) | BUG-054 / ADR-0015 |
| `check_interests` slow on large corpora (per-ref fetch) | ✅ resolved (Wave A) | BUG-055 / ADR-0011 |
| Admin write tools not gated behind confirm | ✅ resolved (Wave C) | TD-bot-confirm-coverage-completeness |
| `DuplicateSchema` under parallel pytest | ✅ resolved (Wave A) | BUG-056 |
| Tests skipped though the helper now exists | ✅ resolved (Wave A) | BUG-057 |
| `tg_pipeline_trigger_total` never shows `surface="mcp"`/`"bot"` | ✅ resolved (Wave C) | BUG-058 |
| `@compose_only` tests never run in CI | ✅ resolved (Wave A) | BUG-059 |
| Alert fires on keyword-only rows (combined=1.0) | ✅ resolved (delivery alert provisioned; semantic-availability alert shipped via dedicated counter, T6 `eead91e`, § C) | BUG-060 |
| `combined=1.0` / `semantic=0.0` in keyword-only mode | **by-design** | ADR-0010/0011 (§ B) |
| Calibration takes a moment at interest create | **by-design** | ADR-0012 §R4 (§ B) |
| Workspace move is two non-atomic steps | **by-design** | O-1 (§ B) |
| No streaming scorer | **by-design** | ADR-0011/0012 (§ B) |

---

## E. Cross-links

- **BUG_LOG entries:** BUG-008, BUG-019, BUG-020, BUG-021 (pre-existing);
  BUG-054…060 (filed 2026-06-12); TD-bot-confirm-coverage-completeness,
  TD-confirm-flow-concurrency-integration (existing TD ids).
- **ADRs:** [0010](../adr/0010-watchlist-keyword-aggregation.md),
  [0011](../adr/0011-watchlist-backfill-rework.md),
  [0012](../adr/0012-watchlist-threshold-calibration.md),
  [0013](../adr/0013-watchlist-threshold-precision-floor.md),
  [0014](../adr/0014-watchlist-batch-silent-delivery.md),
  [0008](../adr/0008-subscription-target-model.md),
  [0009](../adr/0009-idempotency.md),
  [0007](../adr/0007-mcp-scheduler-dispatch.md).
- **Wave 1 framing:** [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md).
