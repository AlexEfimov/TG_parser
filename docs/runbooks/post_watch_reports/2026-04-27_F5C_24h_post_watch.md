# F5-C MVP — 24h Post-Watch Report

**Period (UTC):** `2026-04-26T11:07:13Z` → `2026-04-27T13:35:00Z` (≈26.5h, 24h target met +2h diagnostic tail)
**Release:** tag `f5c-mvp-2026-04-26` / merge commit `29679e0` (PR #14)
**Watch helper:** `docker/f5c_watch.sh --quiet` via cron (`0 */4 * * *`)
**Verdict log:** `~/f5c-watch/cron.log` on `prod`, 7 verdict rows
**Phase 1 closed (mid-window):** 2026-04-26 13:04Z – 13:19Z, 5 TDs landed (see [`MERGED_PLAN.md` § 9](../../notes/REVIEW_2026-04-26_MERGED_PLAN.md#phase-1-landing-log-2026-04-26))
**Phase 2 opened:** 2026-04-27 13:35Z (this report — **operational GREEN declared**)

---

## Executive summary

- **System health (end-of-watch):** healthy. Direct authenticated probe at `2026-04-27T13:35Z` from inside the prod container returned `200 OK` with a real LLM completion (`POST /v1/messages` → `"Pong! 🏓"` from `claude-haiku-4-5-20251001`).
- **Watch verdict (end-of-watch):** TRIPWIRE — but **not** a real incident; entirely explained by two structural artefacts in the watch tooling itself (cumulative-counter design + buggy health-check endpoint). Both filed as new TDs (see § 7).
- **Source state (end-of-watch):** 5/5 sources `active`, 0 paused, 0 with `AnthropicBillingError` in `last_error`, 0 with `rate_limit_until` set.
- **Counter trajectory:** `tg_parser_anthropic_billing_block_total{stage="processing"}` rose `16 → 60` in one window, then **flat at 60 for 4 consecutive ticks (≥16h)** — i.e. no new billing errors since 2026-04-26 ~22:00Z.
- **F5-C resummarize activity:** zero successful or failed runs (`tg_resummarize_total = 0` across all outcomes). No topic in the 5 active sources hit the N-threshold during the watch window. Side-effect: § 1–4 metrics are zero, which is **expected** for a quiet 24h with no triggering content, **not** a degradation.
- **Decision:** Phase 2 cleared to commence; TD-03c committed under `fix/post-living-kb-debt-phase2-2026-04-27`. Two newly-discovered TDs (health-check probe, watch-tripwire-cumulative) folded into the sprint and **both landed**: TD-NEW-A (health probe) commit `afba6b0`, TD-NEW-B (watch delta) commit `d0d5b5e`.

---

## Verdict timeline (verbatim from `cron.log`)

| Tick (UTC)              | Verdict | Alert | Note |
|-------------------------|---------|-------|------|
| `2026-04-26T11:07:13Z`  | GREEN (idle) | — | Deploy time. No re-summarize ticks yet. |
| `2026-04-26T14:00:02Z`  | GREEN (idle) | — | First scheduled tick after deploy. |
| `2026-04-26T18:00:02Z`  | TRIPWIRE | `#4 anthropic billing block fired 16 time(s)` | First billing-pause incident (real). |
| `2026-04-26T22:00:02Z`  | TRIPWIRE | `#4 anthropic billing block fired 60 time(s)` | Counter plateau — no new billing errors after this. |
| `2026-04-27T02:00:02Z`  | TRIPWIRE | `#4 anthropic billing block fired 60 time(s)` | **Stale** — same cumulative counter, no new events. |
| `2026-04-27T06:00:02Z`  | TRIPWIRE | `#4 anthropic billing block fired 60 time(s)` | Stale (cumulative). |
| `2026-04-27T10:00:02Z`  | TRIPWIRE | `#4 anthropic billing block fired 60 time(s)` | Stale (cumulative). |
| `2026-04-27T13:32:23Z` (manual run) | TRIPWIRE | `#4 anthropic billing block fired 60 time(s)` | Stale (cumulative). DB confirms 0 paused sources. Real LLM probe succeeds (see § Diagnostic). |

**Counts:** 2 GREEN / 0 YELLOW / 5 TRIPWIRE / 0 RED. All 5 TRIPWIRE entries are
the same alert family (`#4 anthropic billing block`). The first one (18:00Z) is
real; the next four are **the same 60-count counter, never updated**, because
the watch-helper compares an absolute counter against an absolute threshold.

---

## Tripwire #4 — RCA (revised after diagnostic)

**Class:** real billing event followed by silent recovery; subsequent TRIPWIRE
verdicts are **false-positives caused by tooling artefacts**, not by the
underlying production incident.

**Two-layer breakdown:**

### Layer 1 — Real billing event (resolved)

1. Anthropic balance fell low on 2026-04-26 ~17:00Z; first
   `AnthropicBillingError` raised in the processing stage.
2. Scheduler called `_pause_source_for_billing` and set
   `sources.rate_limit_until = now + BILLING_BLOCK_BACKOFF_S` for the affected
   source(s).
3. Counter `tg_parser_anthropic_billing_block_total{stage="processing"}` rose
   from 0 → 16 → 60 in two windows.
4. Operator topped up Anthropic balance on 2026-04-26 (per user, "balance was
   topped up yesterday").
5. `rate_limit_until` expired naturally; sources transitioned back to `active`
   with no manual SQL intervention required (DB confirms 0 rows with
   `rate_limit_until` set at end of watch).
6. From 2026-04-26 ~22:00Z onward, **no new** `AnthropicBillingError` was
   raised — the counter stopped growing. **This is the actual recovery
   moment.**

### Layer 2 — Why the watch never returned to GREEN despite recovery

**Two independent structural flaws in the watch + health-check tooling**:

#### Flaw A — Cumulative-counter tripwire (`docker/f5c_watch.sh` `#4`)

The watch helper reads `tg_parser_anthropic_billing_block_total` directly and
alarms whenever the absolute value > 0. Once any billing event has ever
happened, the counter is monotonic and can only reset via process restart →
**there is no path back to GREEN through normal operational recovery**.
Correct design: rate over a window (`increase(metric[1h]) > N`), or compare
the timestamp of the last counter increment against `now`.

→ Filed and **landed as TD-NEW-B** in this same sprint (commit `d0d5b5e` — see CHANGELOG → Sprint Debt-Fix Post-Living-KB — Phase 2 → TD-NEW-B for the implementation note). Helper now persists prev-tick value in `${F5C_WATCH_STATE_DIR:-~/.f5c-watch}/billing_block_state` and alarms only on positive delta.

#### Flaw B — Anthropic health-check probe is buggy

`tg_parser/api/health_checks.py::_check_anthropic` probes
`https://api.anthropic.com/v1/` (root) and accepts only `{200, 404}`.
Anthropic apparently changed root-endpoint behaviour from `404` → `403` at
some point, so the probe **always fails with 403** regardless of billing or
auth state. This explains the every-5-min log line:

```
{"event": "LLM provider health check failed: Client error '403 Forbidden' for url 'https://api.anthropic.com/v1/'", ...}
```

The probe also doesn't actually exercise auth or billing — `/v1/` rejects
unauthenticated probes the same way as well-funded ones. Both signal value
and signal accuracy are zero. Replacing with `GET /v1/models` (which
returns `200 OK` only when both API key and org are valid) is a 5-LOC fix.

→ Filed as **TD-NEW-A** (land this sprint).

### End-of-watch diagnostic transcript (proof of operational GREEN)

Run from inside the running prod `tg_parser` container at `2026-04-27T13:35Z`,
using the same `ANTHROPIC_API_KEY` env var the application uses:

| Probe                                      | Status | Body excerpt |
|--------------------------------------------|--------|---------------|
| `GET https://api.anthropic.com/v1/`        | **403** | `{"error":{"type":"forbidden","message":"Request not allowed"}}` — confirms current `/v1/` root behaviour |
| `GET https://api.anthropic.com/v1/models`  | **200** | `{"data":[{"type":"model","id":"claude-opus-4-7", ...}, ...]}` — auth valid, catalog returned |
| `POST https://api.anthropic.com/v1/messages` (model `claude-haiku-4-5-20251001`, max_tokens=8) | **200** | `{"content":[{"type":"text","text":"Pong! 🏓"}], ..., "usage":{"input_tokens":8, "output_tokens":8, "service_tier":"standard"}}` — real billed call succeeded |

**Conclusion:** Anthropic API key + org + balance are all healthy. No
operator-facing remediation remains for layer 1.

### Operator action log

| Step                                  | UTC                  | Result |
|---------------------------------------|----------------------|--------|
| Anthropic balance topped up            | 2026-04-26 (per user) | balance non-zero on console |
| Sources auto-recovered (no SQL ran)    | 2026-04-26 ~22:00Z – 2026-04-27 02:00Z | `rate_limit_until` expired naturally; counter flat after this |
| Watch-helper TRIPWIRE persisted       | 2026-04-27 02:00Z – 13:32Z | counter cumulative; tooling artefact (Flaw A) |
| Diagnostic probe run                  | 2026-04-27 13:35Z    | `POST /v1/messages` → 200 + completion; verified real LLM healthy |
| Decision: declare operational GREEN   | 2026-04-27 13:36Z    | proceed with Phase 2; file TD-NEW-A, TD-NEW-B |

**Post-recovery follow-up issues:** _<TBD — link to GH issues for TD-NEW-A and TD-NEW-B once filed>_

---

## 1. Outcome distribution

PromQL: `sum by(outcome) (increase(tg_resummarize_total[24h]))` evaluated
at `2026-04-27T13:35Z` via `/metrics` snapshot.

| outcome        | count | %     | comment |
|----------------|-------|-------|---------|
| ok             | **0** | n/a   | no triggering content |
| locked         | **0** | n/a   |         |
| llm_error      | **0** | n/a   | no calls attempted; recovered before `_pause_source_for_billing` window expired with content waiting |
| version_raced  | **0** | n/a   |         |
| empty_scope    | **0** | n/a   |         |
| no_card        | **0** | n/a   |         |
| no_bundle      | **0** | n/a   |         |
| unknown        | **0** | n/a   |         |
| **TOTAL**      | **0** | 100%  | **expected for a quiet 24h with no topic crossing the N-threshold** |

**Acceptance:** the `ok ≥ 80%` threshold is **not applicable** when total = 0.
This is **not a degradation**: the F5-C scheduler hook fires only when
`new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N`, and during this
window the 5 active channels accumulated below threshold. → **green by
no-op**.

---

## 2. Cost (LLM tokens)

PromQL: `sum by(model) (increase(tg_resummarize_tokens_total[24h]))`.

| model                | prompt tokens | completion tokens | est. USD |
|----------------------|---------------|-------------------|----------|
| _(no resummarize calls)_ | 0         | 0                 | $0       |

**Acceptance:** trivially below planning upper bound (1.2M tokens/day/channel).
→ **green**.

---

## 3. Duration

- **p50:** n/a (no observations)
- **p95:** n/a (no observations)
- **p99:** n/a (no observations)

**Acceptance:** p95 < 30s threshold not testable on a zero-call window.
→ **n/a (green by no-op)**.

---

## 4. SQL snapshot — `topic_card_versions`

```sql
SELECT COUNT(*),
       pg_size_pretty(pg_total_relation_size('topic_card_versions')),
       COUNT(DISTINCT topic_id),
       MAX(version_no),
       AVG(version_no)::numeric(10, 2)
FROM topic_card_versions;
```

| rows  | size    | topics_with_history | max_version | avg_version |
|-------|---------|---------------------|-------------|-------------|
| **0** | **32 kB** | **0**               | **0**       | **n/a**     |

**Acceptance:** `rows == counter(outcome=ok) == 0` ✓; size in kB. → **green**.

---

## 5. F11 watchlist health (Phase 1 TD-02)

Phase 1 landed `tg_watchlist_*` Prometheus metrics on
`2026-04-26T13:10:19Z` (commit `134a172`). 24h calibration window for F11
P2 starts from that timestamp; thresholds-tuning analysis can begin no
earlier than `2026-04-27T13:10:19Z`.

DB-side snapshot at `2026-04-27T13:34Z`:

```sql
SELECT
  (SELECT COUNT(*) FROM watch_interests)            AS interests_total,
  (SELECT COUNT(*) FROM watch_interests WHERE is_active) AS interests_active,
  (SELECT COUNT(*) FROM watch_matches)              AS matches_total;
```

| metric                        | value | comment |
|-------------------------------|-------|---------|
| `watch_interests` (total)     | **0** | no F11 subscribers yet |
| `watch_interests` (active)    | **0** | no F11 subscribers yet |
| `watch_matches` (total)       | **0** | calibration window started but no traffic |

**Note:** `tg_watchlist_*` metrics on `/metrics` returned empty (counter is
metric-type `counter`, hidden until the first non-zero increment).
This matches the empty-table state above.

**Acceptance:** TD-02 metric registry is wired and exposed (verified Phase 1);
calibration-data scoring deferred until first real F11 subscriber lands.

---

## 6. Tripwires fired

- [ ] `#1 llm_error > 10%` — **no**
- [ ] `#2 version_raced > 5%` — **no**
- [ ] `#3 duration p95 > 30s` — **no**
- [x] `#4 anthropic billing pause` — **yes (5 windows)** — but only the first
      window (18:00Z) reflects a real billing event. Windows 2–5 are
      **false-positive** verdicts caused by Flaw A (cumulative-counter
      tripwire). End-of-watch diagnostic confirms zero current incident.

---

## 7. Производственный сигнал → приоритет Phase 2 / future

| Item                                                          | Signal from 24h                                                               | Priority |
|---------------------------------------------------------------|-------------------------------------------------------------------------------|----------|
| #1 TTL for `topic_card_versions`                              | rows growth: 0/24h, projected: <1 MB/year                                     | P2       |
| #4 Time-based trigger                                         | topics with `last_summarized_at < deploy_time AND new_items > 0`: 0           | P2       |
| #5 Bot tools                                                  | UX requests: none                                                             | P2       |
| #10 Per-channel metric                                        | per-channel skew observable: yes (5 active sources) — wire after first F11 traffic | P2       |
| **TD-05 (billing-error helper consolidation)**                | 1 real burst (`16 → 60`) before silent recovery; helper extraction motivated | **P1 (this sprint)** |
| **TD-NEW-A (health-check Anthropic probe)**                   | every-5-min false-negative log spam since deploy; 5-LOC fix; lands this sprint | **P1 (this sprint)** |
| **TD-NEW-B (watch helper `#4` cumulative → delta)**           | tooling design flaw; 4/5 TRIPWIRE in this watch were false-positive          | **P1 (landed this sprint, commit `d0d5b5e`)** |
| TD-06 (observability ownership / F5-C lifecycle edges)        | no signal in this window (zero traffic) — leave at master `MERGED_PLAN.md`   | P2 stretch |
| TD-07 (changelog + architecture drift)                        | drift exists (independent of watch); land if capacity allows                 | P2 stretch |
| TD-08 (F5-C/F11 schema/config invariants)                     | watch surfaced `topic_interests` vs `watch_interests` table-name drift in tooling — informative, low risk | P2 stretch |

---

## 8. Final verdict

- [x] **GREEN (operational, evidence-based)** — F5-C MVP production-stable.
      Phase 2 cleared to start. Justification:
  - **0 paused sources, 0 billing-error sources, 5/5 active**;
  - **counter flat for ≥16h** (no new billing errors after 2026-04-26 22:00Z);
  - **`POST /v1/messages` returned 200 + actual completion** at end-of-watch
    (positive proof, not just absence of negative signal);
  - The 4 TRIPWIRE windows after the real recovery are **fully explained**
    by two distinct watch-tooling flaws (Flaw A + Flaw B), both filed as TDs.
- [ ] ~~YELLOW~~ — not applicable (no in-flight incident).
- [ ] ~~RED~~ — not applicable (production verified healthy).

> **Caveat (resolved):** when first written, this report noted that
> follow-up cron ticks would continue to report TRIPWIRE on `#4` until
> TD-NEW-B landed. TD-NEW-B has since landed in the same sprint
> (commit `d0d5b5e`); after deploy of `fix/post-living-kb-debt-phase2-2026-04-27`,
> the first tick will write the baseline state file (warm-up — no
> alarm), and subsequent ticks will alarm only on positive delta. So
> the false-positive TRIPWIRE chain documented above is now self-healing
> on next deploy.

---

## 9. Artefacts

- Watch verdict log (`~/f5c-watch/cron.log` on prod, 7 verdict rows + manual run).
- Phase 1 landing log: [`MERGED_PLAN.md` § 9](../../notes/REVIEW_2026-04-26_MERGED_PLAN.md#phase-1-landing-log-2026-04-26).
- Recovery runbook: [`ANTHROPIC_BILLING_RECOVERY.md`](../ANTHROPIC_BILLING_RECOVERY.md).
- F5-C deploy + watch runbook: [`F5C_DEPLOY_AND_WATCH.md`](../F5C_DEPLOY_AND_WATCH.md).
- Diagnostic transcript (3 probes): inline in § "Tripwire #4 — RCA → End-of-watch diagnostic transcript" above.
- Grafana snapshots: _<not attached — zero-traffic window has no informative panels>_
- env-tunable changes during window: none.

---

## 10. Cross-link

This report is referenced from
[`MERGED_PLAN.md` § 9](../../notes/REVIEW_2026-04-26_MERGED_PLAN.md#phase-1-landing-log-2026-04-26)
and from `MERGED_PLAN.md` § 9 **Phase 2 landing log** (added in the closeout commit of Phase 2).
