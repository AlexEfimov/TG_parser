# Wave 1 Step 2 — DONE marker

**Дата:** 2026-05-14 (closure date = day 24h F4-B watch window expired)
**Закрывает:** Wave 1 step 2 (F4-B Core — Workspaces) per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)
**Packaging:** decision A3-mirror (Session F-style: single PR с 5 atomic
commits, mirror Wave 1 step 1 hybrid pattern) per
[`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 2.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md)

---

## 1. Что закрыто

| Sprint | PR | Squash SHA | Deployed | 24h watch verdict |
|---|---|---|---|---|
| F4-B Core (Workspaces) — schema + service + MCP/CLI + scoping + tests | [#67](https://github.com/AlexEfimov/TG_parser/pull/67) | `7953302` | 2026-05-13T19:30:28Z | **GREEN** |

> **Deploy timestamp** — `tg_parser`/`tg_parser_bot`/`tg_parser_mcp`
> container restart logged at `2026-05-13T19:30:28Z` per F4-B Core
> deploy SSH transcript (см. parent session conversation timeline).
> Watch window opened `2026-05-13T19:30:28Z`, expected close
> `2026-05-14T19:30:28Z`. Verdict captured 2026-05-15 ~10:30 UTC (this
> document's authoring session, ~15h past watch-close due to handoff
> gap between parent session #67-#71 sequence and DONE-marker session;
> all watch-window metric/log queries scoped to the exact 24h window
> via Prometheus `query_range` + `docker logs --since/--until`).

> **Post-merge docs sync (not deploy-affecting):** PRs
> [#68](https://github.com/AlexEfimov/TG_parser/pull/68) (user-facing
> docs + pyproject 4.2.0 → 4.3.0, +357/-29 across 7 files), [#69](https://github.com/AlexEfimov/TG_parser/pull/69)
> (M-1..M-16 docs hygiene, 4 atomic commits, ~+257/-89), [#70](https://github.com/AlexEfimov/TG_parser/pull/70)
> (planning artifact commit, 401 LOC), [#71](https://github.com/AlexEfimov/TG_parser/pull/71)
> (`.gitignore` exclude personal Cursor notes, 3 lines) — docs-only,
> no production redeploy required.

## 2. Verification (watch verdict — GREEN)

### 2.1 Prometheus gauges over 24h watch window

| Metric | Query | Verdict | Result |
|---|---|---|---|
| `up{service="bot"}` | `query_range`, start=2026-05-13T19:30Z, end=2026-05-14T19:30Z, step=900s | ✅ GREEN | 97 samples, all `value=1` (no flapping) |
| `up{service="api"}` | same range query | ✅ GREEN | 97 samples, all `value=1` |
| `up{service="mcp"}` | same range query | ✅ GREEN | 97 samples, all `value=1` |
| `confirm_flow_mismatch_total` (24h delta) | `query?query=confirm_flow_mismatch_total` | ✅ GREEN | time series **does not exist** in Prometheus (counter never incremented since deploy = canonical zero events) |
| `gemini_*_total` (errors, 24h delta) | label `__name__` survey for `gemini_*` patterns | ✅ GREEN | no `gemini_empty/no_candidates/blocked/api_error` time series exist (counters never incremented = canonical zero) |
| `tg_workspace_resolver_seconds` p99 (new F4-B metric, 24h) | `histogram_quantile(0.99, sum by(le)(rate(tg_workspace_resolver_seconds_bucket[24h])))` | ✅ GREEN | **4.96 ms** (well within latency budget; no pre-F4-B baseline available — metric is new in F4-B Core) |

### 2.2 Container health snapshot (post-watch, 2026-05-15 ~10:30 UTC)

```
tg_parser              Up 39 hours (healthy)
tg_parser_mcp          Up 39 hours (healthy)
tg_parser_bot          Up 39 hours (healthy)
tg_parser_prometheus   Up 2 weeks
tg_parser_postgres     Up 3 weeks (healthy)
tg_parser_grafana      Up 6 weeks
```

All 6 production containers healthy. The three F4-B-affected containers
(`tg_parser` API, `tg_parser_mcp`, `tg_parser_bot`) report uptime
exactly matching the deploy (39h = 24h watch + ~15h handoff gap).

### 2.3 Bot / API / MCP error-log scan over watch window

| Container | Pattern | Verdict | Result |
|---|---|---|---|
| `tg_parser_bot` | `grep -iE "(error\|exception\|traceback)"` | ✅ GREEN | Only 9 transient `aiogram.dispatcher: TelegramNetworkError / ClientConnectorError to api.telegram.org` events on 2026-05-14 15:26-15:58 UTC (Telegram API network blips; aiogram self-recovers on next polling cycle; not bot-side regression). **Zero** `confirm_flow_mismatch`, **zero** Gemini errors, **zero** FSM-related issues. |
| `tg_parser` (API + scheduler) | same | ⚠️ Pre-existing observability noise (BUG-013 / BUG-014 — see § 4) | 3482 lines containing error/exception/traceback patterns; error-class breakdown (`grep -oE`): **18** `sqlalchemy.exc.IllegalStateChangeError`, **6** `TypeError: can't compare offset-naive and offset-aware datetimes`, **3** cascading `sqlalchemy.exc.InterfaceError`. All from `incremental_pipeline` scheduler ticks. **Zero workspace-related errors**, **zero F4-A regression patterns**. |
| `tg_parser_mcp` | same | ⚠️ Pre-existing config issue (out of F4-B scope) | 1 ingestion failure 2026-05-14T05:45:30Z due to `ValueError: Missing Telegram API credentials. Please set TELEGRAM_API_ID and TELEGRAM_API_HASH` — MCP container env not populated with telethon creds (config drift, pre-existing, unrelated to F4-B; affects user-initiated `trigger_pipeline` from MCP only — scheduler-driven ingest works because main `tg_parser` container has creds). Not filed as a new BUG entry per parent prompt scope (BUG-013/014 only), but worth flagging for the operator runbook. |

### 2.4 Workspace-tool surface — zero errors

```
ssh prod 'docker logs --since 2026-05-13T19:30:00Z --until 2026-05-14T19:30:00Z \
  tg_parser 2>&1 | grep -iE "workspace" | grep -iE "(error|fail|exception)"'
[empty]
# same query against tg_parser_bot / tg_parser_mcp
[empty]
```

No workspace-related errors across api / bot / mcp containers during
the watch window. F4-B Core surface landed cleanly: no regressions, no
exceptions, no F4-A back-compat breakage.

### 2.5 Scheduler tick counter — observability impact note

```
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=increase(tg_parser_scheduler_tasks_total\
   {task_name=\"incremental_pipeline\"}[24h])"'
→ status="error":  ~24 ticks (all over watch window)
→ status="success": (time series absent — counter never incremented)
```

100% of `incremental_pipeline` ticks counted as `status="error"` over
the watch window. **This is the BUG-013 / BUG-014 surface** (see § 4),
**not a F4-B regression** — the same metric was degraded pre-F4-B too;
the F4-B container restart simply reset the visible log buffer and
made the issue newly conspicuous. Data-side, `incremental_embedding`
task succeeded 39/39 times over the same period and `processed_documents`
rows continued to advance — pipeline payload is completing, only the
wrapper close-time / rollback fails.

## 3. Monitoring-only / unresolved

| Item | Reason | Re-evaluate trigger |
|---|---|---|
| O-1 (atomic `move_workspace_source`) — deferred per [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § 3 | F4-B Core MVP shipped non-atomic remove+add per Q4 refined decision (preemptive flag без pain-driven evidence). Watch window did not produce signal'а к promote. | New evidence: remove×add ratio ≈ 1:1 с small temporal gap (или single user-pain report) → promote atomic tool в Wave 1 step 3 / Wave 2. Re-check в Wave 1 step 3 planning sub-session per `HANDOFF § 6 #3`. |
| F4-B Bot integration (Q3 — skip-bot MVP) | Conscious scope exclusion per [`PLANNING_F4B_WORKSPACES_PREP.md` § 4 Q3](PLANNING_F4B_WORKSPACES_PREP.md). | Wave 1 step 3+ / Wave 2 audience-shift (A2/A3 sharing). |
| F11 watchlist `workspace_id` (Q7) | Conscious scope exclusion per Q7 = C (skip F11). | Wave 1 step 3 если P-1 (Watchlist HTTP API parity) выбран — natural pair с workspace narrowing. |
| F6 digest `workspace_id` (Q8) | Conscious scope exclusion per Q8 = C (skip F6). | Wave 1 step 3 если P-2 (Digest HTTP API parity) выбран — natural pair. |
| MCP-container env drift (`TELEGRAM_API_ID/HASH` missing) | Surfaced once in watch-window logs (§ 2.3); pre-existing config-only issue unrelated to F4-B. | If user-initiated MCP `trigger_pipeline` becomes an explicit Wave 1 step 3 surface or part of P-1/P-2 parity sprint. |

## 4. Pre-existing bugs surfaced by watch window (NOT F4-B regression)

24h F4-B watch window's fresh log buffer (containers restarted on
deploy) surfaced two pre-existing scheduler bug-classes that are now
filed in [`BUG_LOG.md` § Active](BUG_LOG.md). Both are
structurally outside F4-B Core scope — verified by
`git diff 7953302^ 7953302 -- tg_parser/services/scheduler_service.py
tg_parser/services/db_context.py` showing **0 lines** changed in
`scheduler_service.py` + **+12 additive** lines in `db_context.py`
(new `workspace_repo()` context manager only; the
`ingestion_and_processing_repos()` block where BUG-013 surfaces at
line 192 is untouched).

| ID | Title | Severity | Frequency over 24h watch | F4-B relationship | Fix-sprint planned |
|---|---|---|---|---|---|
| [BUG-013](BUG_LOG.md#bug-013--scheduler-shares-one-asyncsession-pair-across-asynciogather-tasks--illegalstatechangeerror--cascading-interfaceerror-on-every-incremental_pipeline-tick) | Scheduler shares one `AsyncSession` pair across `asyncio.gather` tasks → `IllegalStateChangeError` + cascading `InterfaceError` | Medium (observability-only; 0 user-visible data impact — inner pipeline sessions complete; `tg_parser_scheduler_tasks_total{status="success",task_name="incremental_pipeline"}` time series absent since deploy, every tick `status="error"`) | 18 IllegalStateChangeError + 3 cascading InterfaceError tracebacks (~75% of 24 ticks) | **NOT a F4-B regression.** F4-B touched 0 lines in `scheduler_service.py` (`scheduler_service.py:61-65,81,89` unchanged; `db_context.py:192` inside `ingestion_and_processing_repos()` block which was not modified — F4-B added a new `workspace_repo()` context manager) | next session per [`HANDOFF § 6 #2`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md) — ~30 LOC delta in scheduler_service (per-task sessions, drop `repo_lock`) + 2 integration tests, half-day effort |
| [BUG-014](BUG_LOG.md#bug-014--scheduler-_process_source-compares-offset-naive-sourcerate_limit_until-against-datetimenowutc--typeerror-aborts-the-tick-before-any-pipeline-work-runs) | Scheduler `_process_source` line 89 compares offset-naive `source.rate_limit_until` against `datetime.now(UTC)` → `TypeError` aborts tick before any pipeline work | Medium (observability + per-source advancement stalled until `rate_limit_until` clears; 0 data integrity impact) | 6 TypeError tracebacks (~25% of 24 ticks) — co-fires with BUG-013 in same stacktrace on most ticks | **NOT a F4-B regression.** Same proof — `scheduler_service.py:89` unchanged since well before F4-B Core. | joint fix with BUG-013 same session (small ~5-10 LOC fix: defensive tz coercion or column-level `DateTime(timezone=True)` enforcement) |

**Why surfaced now:** F4-B deploy restarted `tg_parser` / `tg_parser_bot`
/ `tg_parser_mcp` containers at 2026-05-13T19:30:28Z, which (a) reset
the visible `docker logs` history (no longer paginating 2-week-old
noise into operator's grep'ы), (b) zeroed the deploy-local
`scheduler_tasks_total` counters so the 100%-error ratio became newly
prominent. Bug behaviour itself unchanged.

## 5. Accumulated observations

### 5.1 Parity tracker entries

Refer to [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md)
§ 3 for the canonical observation registry. F4-B Core watch window
did NOT produce new parity observations beyond the pre-existing
**O-1** (atomic `move_workspace_source`) and **O-2** (BUG-007
fuzzy-suggestion gap on status-check pathway). O-1 specifically:
watch window did not record any user-driven remove×add sequences
on `workspace_sources` (workspace tools are new — natural usage
ramp-up; signal-collection window will continue into Wave 1 step 3).
Verify-action for O-1 is scheduled for Wave 1 step 3 planning
sub-session per `HANDOFF § 6 #3`.

### 5.2 New FUTURE_FEATURES items

**Нет нового FUTURE_FEATURES** — F4-B Core landed on locked
Q1–Q8 decisions с zero scope-creep over the sprint. The two
pre-existing bugs surfaced (BUG-013 / BUG-014) are technical-debt
items filed into `BUG_LOG.md` per the bug-log workflow, not
product-feature items.

### 5.3 Signals collected (для Decision Point — § 5 `PLANNING_WAVE1_EXECUTION_PLAN`)

**Нет внешних signals** на момент закрытия step 2 — F4-B Core
audience activation (A2 "Curator" via shareable workspace + A3
"Team subset" via per-user workspace boundary) requires Wave 1
step 3 (Surface Parity P-1/P-2 — Watchlist/Digest HTTP API) +
step 4 (Shareable Digest) before external signal-collection ramp
makes sense. Owner-as-A1 dogfooding continues; first non-owner
signals expected after step 3.

## 6. Pre-next-step readiness checklist

- [x] Sole deploy 24h watch GREEN — все три `up{service=...}` gauges
      hold value=1 across 97 samples; counter time-series for
      `confirm_flow_mismatch_total` / `gemini_*_total` are absent
      (canonical zero); workspace resolver p99 = 4.96 ms healthy;
      zero workspace-tool errors in logs (см. § 2 above).
- [x] 0 регрессий по существующим тестам — F4-B Core PR #67 landed
      с 134 новых F4-B тестов поверх существующих ~2050 (см.
      [PR #67 description](https://github.com/AlexEfimov/TG_parser/pull/67))
      + post-merge sync PRs #68-#71 не трогали test suite. Production
      smoke ("zero workspace-related errors") confirms F4-A bit-for-bit
      parity invariant holds.
- [x] CHANGELOG.md обновлён под `Unreleased` для F4-B Core — done в
      PR #67 / #68 (см. CHANGELOG entries для `4.3.0` block).
- [x] Cross-link на этот marker в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) —
      добавлен в этом же PR (commit 2).
- [x] BUG-013 + BUG-014 filed в [`BUG_LOG.md` § Active](BUG_LOG.md) —
      done в этом же PR (commit 1, SHA `d7cda84`).

## 7. Lessons learned

1. **Fresh log buffer surfaces pre-existing bugs.** Each deploy
   restarts containers and zeroes the visible `docker logs` history.
   Bugs that were structurally present but hidden in 2-week-old log
   noise (BUG-013 / BUG-014 here) become newly visible. **Action for
   future Wave-step DONE markers:** explicitly distinguish "new
   bug surfaced by watch" vs "regression introduced by sprint" using
   `git diff <merge_sha>^ <merge_sha> -- <suspect_files>` as the
   adjudicator. Файл BUG entry с явным "NOT a regression" subsection
   when applicable (BUG-013/BUG-014 entries demonstrate the pattern).
2. **24h watch-close ≠ DONE-marker creation.** Watch window 2026-05-13
   19:30Z → 2026-05-14 19:30Z, DONE-marker authored 2026-05-15 ~10:30 UTC
   (15h gap due to handoff between parent session #67-#71 sequence
   and this session). **Action for future Wave-step planning:** put
   the DONE-marker authoring task explicitly into the same fresh
   chat that opens after watch-close, not deferred to next-chat
   handoff. Mitigation для текущего gap: queries were scoped to the
   exact 24h window via Prometheus `query_range&start=...&end=...`
   + `docker logs --since=... --until=...`, so the verdict is
   factually accurate despite the authoring delay.
3. **`tg_workspace_resolver_seconds` baseline = N/A (new metric).**
   F4-B introduced new Prometheus instrumentation for workspace
   resolution latency. The 24h watch p99 of 4.96 ms is healthy by
   absolute standards but cannot be compared to a "pre-F4-B baseline"
   because no such baseline exists. **Action for future feature
   sprints:** when a sprint introduces new metrics, record the
   first-day p99 in the DONE marker as the going-forward baseline
   that subsequent watch windows can compare against (i.e. this
   marker establishes the F4-B workspace-resolver baseline).
4. **MCP container env drift visible only via runtime trace.** A user
   `trigger_pipeline` from MCP hit `ValueError: Missing
   TELEGRAM_API_ID/HASH` because the MCP container's env file lacked
   credentials present in the main `tg_parser` container env. Not a
   F4-B issue, but a latent operational gap that would have stayed
   invisible without the watch-window log scan. **Action:** add an
   MCP-container env-parity check (or compose env_file consolidation)
   to the post-merge sync checklist for any future deploy that
   restarts MCP. Possibly file as BUG-015 in a future housekeeping
   pass — currently out of scope per parent prompt (BUG-013/014 only).

## 8. Следующий шаг

**BUG-013 fix-sprint** (Wave 1 step 2 → step 3 bridge cleanup) per
[`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md` § 6 sequence step #2](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md).

Recommended sequence:

```
[этот PR mergeт]
  ↓
BUG-013 + BUG-014 fix-sprint (~half-day = ~0.5 session)
  branch → fix → tests → commit → PR → CI → merge → deploy → 24h watch
  ↓ (24h GREEN на BUG-013/014 fix)
DONE marker для bug-fix (mirror Session G / Session J pattern)
  ↓
Wave 1 step 3 planning sub-session (~0.3 session) — re-read
PARITY_DECISION_TRACKING.md § 3 P-1..P-5 + O-1/O-2 observations,
выбрать P-1 (Watchlist HTTP API parity) or P-2 (Digest HTTP API
parity) per signals
  ↓
Wave 1 step 3 sprint (~1-2 sessions) — single PR pattern
  ↓
[в любой удобный момент] BUG-009 cleanup в § Resolved (~0.05 session)
```

**Обоснование fix-before-step-3:** входить в крупный новый scope
(Wave 1 step 3 surface parity) с чистым observability baseline
(BUG-013/014 fixed → scheduler 100%-error noise removed) лучше, чем
тянуть его в next sprint и потенциально маскировать новые регрессии.

---

## Appendix — Cross-references

| Документ | Зачем |
|----------|-------|
| [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) § 4 | Canonical DONE marker template (decision C1) |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 5.1 | Wave 1 sequence (Bot UX → F4-B → Surface Parity → Shareable Digest) |
| [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § 3 | O-1 + O-2 observations carried forward (§ 5.1) |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Cross-link target (§ 6 readiness checklist) — entry added в same PR (commit 2) |
| [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) | Template / structural mirror (Wave 1 step 1 precedent) |
| [`START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`](START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md) | Sprint prompt (LANDED — PR #67 #68 banner added в #68) |
| [`PLAN_DOCS_HYGIENE_F4B_POST_MERGE_2026-05-13.md`](PLAN_DOCS_HYGIENE_F4B_POST_MERGE_2026-05-13.md) | Post-merge hygiene plan (executed PR #70) |
| [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md) | Handoff context — input для current session (DONE-marker + BUG filing) |
| [`BUG_LOG.md`](BUG_LOG.md) § Active | BUG-013 + BUG-014 entries (filed в same PR commit 1) |
| F4-B Core merge: [PR #67](https://github.com/AlexEfimov/TG_parser/pull/67) (`7953302`) | Source of truth для § 1 «Что закрыто» + non-regression proof via `git diff` |
| Post-merge docs PRs: [#68](https://github.com/AlexEfimov/TG_parser/pull/68) [#69](https://github.com/AlexEfimov/TG_parser/pull/69) [#70](https://github.com/AlexEfimov/TG_parser/pull/70) [#71](https://github.com/AlexEfimov/TG_parser/pull/71) | Docs/gitignore hygiene that followed F4-B Core — no production redeploy required |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | Karpathy-like principles ADR (workspace concept aligns with Principle "Persistent entities" + "Provenance / evidence") |
