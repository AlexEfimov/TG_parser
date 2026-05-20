# BUG-014B — Storage-Boundary Fix DONE marker

**Дата:** 2026-05-20 (verdict ~14h after 24h watch window close)
**Закрывает:** Single-bug sprint per
[`START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md`](START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md)
(orchestrator-side naive-vs-aware `rate_limit_until` comparison at
`orchestrator.py:110`; Option B storage-boundary coerce in
`SAIngestionStateRepo._row_to_source`)
**Packaging:** squash-merged PR [#84](https://github.com/AlexEfimov/TG_parser/pull/84)
(`39da8cc`); closes [#83](https://github.com/AlexEfimov/TG_parser/issues/83)
**Surface mirror:** [`REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md)
(joint-sprint DONE template; § 4.2 previously tracked BUG-014B as OPEN partial)

---

## 1. Что закрыто

| Sprint | PR | Squash SHA | Deployed (prod) | 24h watch verdict |
|---|---|---|---|---|
| BUG-014B storage-boundary `coerce_aware_utc` | [#84](https://github.com/AlexEfimov/TG_parser/pull/84) | `39da8cc` | 2026-05-18T20:08:08Z | **GREEN (8/8)** |

> **Watch window:**
> - Open: 2026-05-18T20:08:08Z (`docker inspect tg_parser` → `State.StartedAt`).
> - Close: 2026-05-19T20:08:08Z (24h elapsed).
> - Verdict captured: 2026-05-20T10:31Z (~14.4h post-close buffer).
> - Evidence span scanned: `docker compose logs tg_parser --since 24h` plus
>   post-deploy slice `--since 2026-05-18T20:08:00Z` (38 hourly ticks observed).
> - First post-deploy completion log:
>   `2026-05-18T21:11:34Z` (`succeeded=9, failed=0`).
> - Last tick in scan: `2026-05-20T10:09:58Z`.

## 2. Acceptance signals (§ 5.3 — 8/8 GREEN)

| # | Signal | Pre-fix (28h joint watch) | Post-fix observed | Verdict |
|---|---|---|---|---|
| 1 | `TypeError.*offset` from orchestrator path | **56** (28 ticks × 2 sources) | **0** (`--since 24h` and `--since 2026-05-18T20:08:00Z`) | ✅ GREEN |
| 2 | `kdl_ru.last_success_at` non-null | null | `2026-05-20T10:08:56Z` (MCP + prod SQL) | ✅ GREEN |
| 3 | `profendocrinologist.last_success_at` non-null | null | `2026-05-20T10:09:58Z` (MCP + prod SQL) | ✅ GREEN |
| 4 | `kdl_ru.fail_count` | 29 | **0** | ✅ GREEN |
| 5 | `profendocrinologist.fail_count` | 29 | **0** | ✅ GREEN |
| 6 | Healthy sources + per-tick shape | `succeeded=7, failed=2` | **38/38** ticks `succeeded=9, failed=0`; 9/9 active sources `has_success=true` | ✅ GREEN |
| 7 | Joint BUG-013/14/24 signals | 6/6 GREEN (with BUG-014B partial) | `IllegalStateChangeError` **0**, `scheduler_unhandled_escape` **0**, orchestrator `TypeError.*offset` **0** since deploy; per-tick gather completes | ✅ GREEN |
| 8 | `_row_to_source.rate_limit_until.tzinfo` aware UTC | naive | CI gate: `tests/test_ingestion_state_repo_datetime_coerce.py` T-1 (param ×8) | ✅ GREEN |

**Closure statement:** BUG-014B is **functionally closed** in production.
The permanent fail-loop on `kdl_ru` + `profendocrinologist` is cleared.

## 3. Per-source post-window state (affected sources)

Captured 2026-05-20T10:31Z via prod SQL + `user-tg-parser` MCP `get_pipeline_status`.

| Source | `last_attempt_at` | `last_success_at` | `fail_count` | `last_error` | `rate_limit_until` (DB) |
|---|---|---|---|---|---|
| `kdl_ru` | 2026-05-20T10:08:56Z | 2026-05-20T10:08:56Z | 0 | null | 2026-05-06T22:58:30Z (expired; no longer blocks) |
| `profendocrinologist` | 2026-05-20T10:09:58Z | 2026-05-20T10:09:58Z | 0 | null | 2026-05-14T08:33:31Z (expired; no longer blocks) |

All 9 active sources: `fail_count=0`, `last_success_at` non-null.

## 4. Evidence commands (reproducible)

```bash
# §5.3 #1
ssh prod 'cd ~/TG_parser && docker compose logs tg_parser --since 24h 2>&1 | grep -cE "TypeError.*offset"'
# → 0

# §5.3 #6 (per-tick shape since deploy)
ssh prod 'cd ~/TG_parser && docker compose logs tg_parser --since 2026-05-18T20:08:00Z 2>&1 \
  | grep -E "Incremental pipeline completed" | grep -v "failed=0"'
# → (empty — all ticks succeeded=9, failed=0)

# §5.3 #2–#5 (DB)
ssh prod 'cd ~/TG_parser && docker compose exec -T postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT source_id, last_success_at, fail_count, last_error FROM sources \
      WHERE source_id IN ('"'"'kdl_ru'"'"', '"'"'profendocrinologist'"'"');"'
```

## 5. Cross-references

| Документ | Зачем |
|---|---|
| [`START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md`](START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md) | Planning + § 5.3 acceptance matrix |
| [`BUG_LOG.md`](BUG_LOG.md) § BUG-014B | Canonical entry + Update 2026-05-18 closure row |
| [`REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md) § 4.2 | Prior «known partial» classification (now superseded) |
| [PR #84](https://github.com/AlexEfimov/TG_parser/pull/84) (`39da8cc`) | Squash merge |
| [`docs/notes/mcp_testing/2026-05-16_claude_session/analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) | Option B rationale |

## 6. Recommended next actions

1. **Optional M-15 hygiene:** move BUG-014B (and joint BUG-013/14/24) from Active → Resolved
   section in `BUG_LOG.md` (deferred per planning § 7 — no functional blocker).
2. **Monitor rate_limit_until housekeeping:** both affected sources retain stale
   `rate_limit_until` ISO strings in DB (expired wall-clock); comparison now succeeds
   because values are tz-aware on read. Clearing columns is cosmetic only.
3. **No code reopen** unless `TypeError.*offset` reappears after a future deploy.

## 7. Lessons learned

1. **Storage-boundary coerce closes all `Source` datetime consumers at once** — the
   orchestrator site required no call-site patch once `_row_to_source` was fixed.
2. **First post-deploy tick already showed `succeeded=9, failed=0`** — fix effect
   visible within one hourly cron cycle (~63 min after container start).
3. **MCP `get_pipeline_status` on local stack may fail if Postgres is down** — prod
   SQL via `ssh prod` + `docker compose exec postgres psql` is the reliable fallback
   for deploy verdicts.
