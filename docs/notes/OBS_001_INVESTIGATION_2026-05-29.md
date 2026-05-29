# OBS-001 Investigation — 2026-05-29 (read-only spike)

**Repo:** TG_parser @ main (af7790f) · **Mode:** read-only code + live VPS SELECT/logs
**Verdict:** OBS-001 = EXPECTED BEHAVIOUR. Matcher healthy. Recommend CLOSE (+ optional Low ENH).

## Hypotheses
- A — SPLIT. CONFIRMED: matcher runs only from hourly scheduler tick (`_process_source`, gated on
  `new_doc_refs`); `trigger_pipeline` (pipeline_dispatch_service._run_pipeline_job_background) never
  calls it. REJECTED that the hook is failing/unconfigured — live log `watchlist.check_interests`
  @2026-05-29T17:04:43Z; all 5 active interests last_checked_at advanced to 2026-05-29.
- B — REJECTED. touch_checked() unconditional (watchlist_service.py:821-822, separate from touch_match).
  watch_matches empty for all; last_match_at null for all; last_checked_at still advances (log candidates=0).
- C — REJECTED. list_active_for_channel filters on channel_ids[] (F11 source array), orthogonal to
  ADR-0008 target_kind/channel_id (delivery). Migration could not break selection.
- D — REJECTED. No last_checked_at time-gate exists; only gate is new_doc_refs non-empty.

## Root cause
last_checked_at = "last hourly tick that found NEW docs for a watched channel." trigger_pipeline does
not run the matcher. Test row 2184bced: created 21:12:40, soft-deleted 21:28:33 (is_active=f) → never
covered by a new-doc tick while active → null forever. The "5 stuck @11:48Z" rows were between
new-doc ticks; all advanced to 2026-05-29 today.

## Live evidence (VPS, read-only)
- 5 active interests, all last_checked_at = 2026-05-29 (08:48 / 10:48 / 17:04), last_match_at all null.
- watch_matches: 0 rows for all interests.
- Log: {"channel_id":"AgeManagment","interests":3,"docs":2,"candidates":0,"inserted":0,
  "event":"watchlist.check_interests","timestamp":"2026-05-29T17:04:43.541459Z"}
- 2184bced: is_active=f, last_checked_at=null, last_match_at=null, created=21:12:40, updated=21:28:33.

## Recommendation
CLOSE OBS-001 as expected-behaviour. Optional Low ENH: fix misleading freshness telemetry — either
add a true matcher-liveness gauge / rename field semantics, OR touch_checked on every tick (incl.
empty new_doc_refs). Regression test: assert touch_checked called when candidates=0.

## Decisive operator experiment (optional)
subscribe_watchlist(target.kind=channel, channel_ids=["AgeManagment"], broad keyword, threshold=0.3)
→ wait one scheduler interval after new docs → expect last_checked_at advances + matches appear →
unsubscribe. (Do NOT expect trigger_pipeline to run the matcher.)

## Key code references
- Matcher selection (target-kind-agnostic): `tg_parser/storage/sqlalchemy/watch_interest_repo.py:213-222`
- Unconditional `touch_checked` vs `touch_match`: `tg_parser/services/watchlist_service.py:820-824`; `new_doc_refs` guard at `:747`
- Matcher wired only to scheduler tick: `tg_parser/services/scheduler_service.py:297-301` (+ interval reg via `background_scheduler.py:412-417`, default 3600s `config/settings.py:482`)
- `trigger_pipeline` does NOT call matcher: `tg_parser/services/pipeline_dispatch_service.py:170-214`
