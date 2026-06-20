# START PROMPT — Break handoff after Wave 1.5 review #1

> **Status:** `ACTIVE` — resume point after operator break (~2026-06-24).  
> **Назначение:** self-contained промпт для первой сессии после перерыва. Wave 1.5 review #1 проведён 2026-06-20; code-change work (α2) **не начинался** в closure-сессии — ждёт confirm или defer.

| Метаданные | Значение |
|---|---|
| **Дата handoff** | 2026-06-20 |
| **Break until** | ~2026-06-24 (operator) |
| **Wave** | 1.5 operational dogfooding (active) |
| **Prod HEAD** | `55e85b5` (local == GitHub == prod) |
| **Previous prod** | `b533b1d` (review prep baseline) |
| **Parent review** | [`REVIEW_WAVE1_5_1_2026-06-20.md`](REVIEW_WAVE1_5_1_2026-06-20.md) |
| **Living tracker** | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §11 |

---

## §1 — TL;DR

Wave 1.5 **review #1 complete** (period 1: 2026-06-06→2026-06-20). Decision Point matrix **0/0/0** — **continue dogfooding**, not Wave 2 pivot. α1 recall-lift **material** (Handoff B/C). **α2 seed-map extend: `<α2 GO|DEFER>` — PENDING** operator confirm (one-pager recommends **GO**). F5-C age-drain **115/116** complete; 1 topic stuck; `RESUMMARIZE_MAX_AGE_DAYS=14` live via compose OS-env fix (`55e85b5`). T2 formal gate **deferred ~2026-06-26**. labdiagnostica coverage fix **may be in flight** — check parallel worker / `main` before acting.

---

## §2 — What was done this session (2026-06-20)

| Item | Outcome |
|---|---|
| **Wave 1.5 review #1** | One-pager finalized; PLAN §11 period-1 row filled; decisions §9 in review doc |
| **α1 recall-lift** | Confirmed material — [`REPORT_ALPHA1_RECALL_LIFT_2026-06-18.md`](REPORT_ALPHA1_RECALL_LIFT_2026-06-18.md) |
| **α2 decision** | **`<α2 GO|DEFER>` — PENDING** at handoff time; recommended **GO** if watchlist-quality remains priority |
| **F5-C freshness** | Drain 115/116 stale topics; `RESUMMARIZE_MAX_AGE_DAYS=14` live; compose passes env (`55e85b5`) |
| **Prod hotfixes since review prep** | `ec78ff1`/`#297` llm_error metric; `b533b1d`/`#298` markdown fence strip; `55e85b5` compose RESUMMARIZE OS env |
| **Dogfood logging** | Discipline committed: ≥1 `[wave1.5-dogfood]`/week (γ3 found 0 tagged entries — friction not captured) |
| **labdiagnostica fix** | In progress (parallel worker) — verify merge status on resume |

---

## §3 — Current prod state

```text
git rev-parse HEAD   # expect 55e85b5 (or newer if labdiagnostica fix merged)
```

| Component | State |
|---|---|
| **Prod SHA** | `55e85b5` — `fix(compose): pass RESUMMARIZE_MAX_AGE_DAYS via OS env for tg_parser` |
| **F5-C age trigger** | `RESUMMARIZE_MAX_AGE_DAYS=14` live (explicit owner go) |
| **F5-C drain** | **115/116** topics re-summarized; **1 topic stuck** — monitor on next ticks / force-resummarize if needed |
| **T7 observability** | Grafana row + `tg:resummarize_age_trigger:ratio14d` gate provisioned |
| **T2 Phase-0 observer** | Deployed 2026-06-19; **0 Prometheus samples** as of 2026-06-20 → formal gate deferred |
| **Decision Point** | 0/0/0 (2A/2B/2C); not triggered |

---

## §4 — Do NOT reopen

| Item | Reason |
|---|---|
| **BUG-008 close** | By-design `open`; H1 fixed (`5165875`); H3 transport external |
| **D2 scoring formula** | Deferred, ADR-gated; D1 RARE (~0.83%) |
| **T2 formal ADR-0016 gate** | Before **~2026-06-26** — need 7d post-deploy Prometheus samples |
| **Wave 2 direction commit** | DP matrix empty; continue dogfooding per review #1 |
| **RxNorm / general FTS synonymy** | Out of α2 scope; seed-map curated only |

---

## §5 — Next actions when back (~2026-06-24)

### Priority stack

1. **Resolve α2 placeholder** — read operator decision from review meeting or ask:
   - **If GO:** extend `_ALIAS_TO_CANONICAL` per [`REVIEW_WAVE1_5_1_2026-06-20.md`](REVIEW_WAVE1_5_1_2026-06-20.md) §3 + §7; golden tests; optional uncapped `backfill_watchlist(dry_run=true)` verify. **Do not** touch D2/RxNorm.
   - **If DEFER:** skip code; focus dogfood capture + F5-C cost-watch + validator setup (R-5).
2. **labdiagnostica fix** — if merged: confirm prod deploy + coverage delta; if not: check parallel worker status.
3. **F5-C stuck topic** — investigate 1 remaining stale topic; force-resummarize if appropriate.
4. **Dogfood logging** — log real friction with `[wave1.5-dogfood]` tag this week.
5. **T2 sanity (optional ~2026-06-21)** — peek PromQL for first samples; **not** formal gate.
6. **T2 formal gate ~2026-06-26** — ADR-0016 Phase 1 go/no-go only with real `tg_dedup_near_duplicates_detected_total` data.
7. **Review #2 ~2026-07-04** — period 2 per PLAN §11 cadence.

### Date-gated calendar

| Date | Action |
|---|---|
| ~2026-06-24 | Resume work (this handoff) |
| ~2026-06-21 | T2 sanity check optional (non-binding) |
| ~2026-06-26 | T2 formal gate (ADR-0016) |
| ~2026-07-04 | Wave 1.5 review #2 (period 2) |
| 2026-07-06 | Market scan deep dive deadline if still skipped (PLAN §10 R-6) |

---

## §6 — α2 branch quick-reference

### If `<α2 GO|DEFER>` → **GO**

1. Edit `tg_parser/services/watchlist_tokenizer.py` `_ALIAS_TO_CANONICAL` — clusters: liraglutide, orforglipron, retatrutide, mazdutide, dulaglutide (+ brand aliases per review §3).
2. Golden tests in `tests/` (alias collapse + no cross-molecule bleed).
3. Optional read-only verify: uncapped `backfill_watchlist(dry_run=true)` on GLP-1 interest.
4. Update PLAN §11 α2 placeholder → `α2 GO`; append BUG_LOG/FUTURE_FEATURES only if friction found.

### If `<α2 GO|DEFER>` → **DEFER**

1. Update PLAN §11 α2 placeholder → `α2 DEFER`.
2. Priority: (a) T2 formal ~06-26; (b) dogfood signals; (c) F5-C cost-watch; (d) 2–3 external validators.
3. Revisit α2 at review #2 (~2026-07-04).

---

## §7 — Pre-flight on resume

```bash
cd /Users/alexanderefimov/TG_parser
git fetch origin && git status
git log --oneline -5
# Expect HEAD >= 55e85b5; check if labdiagnostica fix landed

# Optional prod sanity (MCP):
# get_pipeline_status
# get_llm_config
```

---

## §8 — Key links

| Doc | Path |
|---|---|
| Review #1 one-pager | [`REVIEW_WAVE1_5_1_2026-06-20.md`](REVIEW_WAVE1_5_1_2026-06-20.md) |
| Wave 1.5 plan + §11 log | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) |
| α1 report | [`REPORT_ALPHA1_RECALL_LIFT_2026-06-18.md`](REPORT_ALPHA1_RECALL_LIFT_2026-06-18.md) |
| Track-selection brief | [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) |
| F5-C runbook | [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) |
| T2 gate / ADR-0016 | [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4; [ADR-0016](../adr/0016-near-duplicate-dedup.md) |
| Watchlist handoff | [`HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md`](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) |
| Seed-map code | `tg_parser/services/watchlist_tokenizer.py:53` |

---

> **Reminder:** Wave 1.5 = habit, not sprint. No Wave 2 work until Decision Point exit. Commit only on explicit user request ([`AGENTS.md`](../../AGENTS.md)).
