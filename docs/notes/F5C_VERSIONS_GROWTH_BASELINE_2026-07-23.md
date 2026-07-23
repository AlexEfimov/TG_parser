# F5-C `topic_card_versions` growth baseline — 2026-07-23

**Purpose:** read-only evidence for the #15 item #1 TTL/retention slice (ADR-0018).
Confirms current size / growth so the owner can validate the chosen prod knobs
`RESUMMARIZE_VERSION_RETENTION_DAYS=180` / `RESUMMARIZE_VERSION_KEEP_LAST_N=50`.

**Source:** prod (`ssh prod`), processing DB `tg_parser`, read-only. Snapshot
taken 2026-07-23 (~15:30Z).

## Table snapshot

```sql
SELECT COUNT(*) AS rows,
       pg_size_pretty(pg_total_relation_size('topic_card_versions')) AS size,
       COUNT(DISTINCT topic_id) AS topics_with_history,
       MAX(version_no) AS max_version,
       AVG(version_no)::numeric(10,2) AS avg_version
FROM topic_card_versions;
```

| rows | size | topics_with_history | max_version | avg_version |
|------|------|---------------------|-------------|-------------|
| 1124 | 2352 kB (~2.3 MB) | 581 | 14 | 1.94 |

- Avg row size ≈ 2352 kB / 1124 ≈ **~2.1 KB/row**.

## Growth rate (rows/day proxy)

`sum(increase(tg_resummarize_total{outcome="ok"}[…]))` via Prometheus:

| window | rows/day |
|--------|----------|
| last 24h | ≈ 6.0 |
| 7d avg | ≈ 19.3 |

## Projection

At the 7d-avg rate (~19.3 rows/day, conservative-high):

- ≈ 19.3 × 365 ≈ **~7 045 rows/year** × ~2.1 KB ≈ **~14.7 MB/year**.

**Growth is MB-scale, not GB-scale.** The window-CTE full-scan (ADR-0018
Последствия / watch-item) is comfortably fine at this volume.

## Retention implications (why default-off is correct now)

- `max_version = 14`, `avg_version = 1.94` ⇒ **no topic currently has > 50
  versions** — so `KEEP_LAST_N=50` protects essentially the entire table today.
- The `M=180d` cutoff means a version is only eligible for purge once it is both
  **> 180 days old AND outside the newest 50 of its topic**. Given the above,
  a prod purge run today would delete **≈ 0 rows**; retention starts biting only
  after ~6 months of accumulation on high-churn topics.
- Conclusion: `RETENTION_DAYS=0` code-default (kill-switch) is the right ship
  state; enabling `180`/`50` in prod is a **safety bound for the future**, not an
  urgent reclaim. Freshness bump (MAX_AGE_DAYS 14→21, Track δ/T7) will slowly
  raise the daily rate, reinforcing the value of the bound over time.

## Sanity floor check

`RETENTION_DAYS (180) ≥ 2 × RESUMMARIZE_MAX_AGE_DAYS (LIVE=21)` ⇒ 42 ≤ 180 ✓.

## Links

- ADR: [`0018-topic-card-versions-retention.md`](../adr/0018-topic-card-versions-retention.md)
- Plan: [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
- Runbook: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § «Retention / purge»
