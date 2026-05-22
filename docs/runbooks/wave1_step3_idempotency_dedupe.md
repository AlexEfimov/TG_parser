# Runbook — Wave 1 step 3 pre-migration dedupe (BUG-022)

**Trigger:** Alembic migration `f1a2b3c4d5e6` (`20260521_wave1_step3_foundation`)
raises `RuntimeError` with a message like:

```
Migration aborted: <N> duplicate (user_id, title) group(s) found in
watch_interests. ... Dedupe by hand per
docs/runbooks/wave1_step3_idempotency_dedupe.md before re-running
`alembic upgrade head`.
```

**Why:** the migration introduces two natural-key UNIQUE constraints
(`uq_watch_interests_user_title`, `uq_digest_subscriptions_owner_name`)
to close BUG-022 (`subscribe_*` was not idempotent — repeated calls
created duplicate rows). The constraint applies to ALL rows (active
or soft-deleted) so the service-layer upsert can resurrect
soft-deleted interests when the user re-subscribes with the same
label. Pre-existing duplicates would block the constraint
installation; the migration's self-defensive pre-flight catches that
and aborts cleanly instead of mid-table partial state.

## 1. Inspect

Run both inspection queries against the ingestion DB
(`tg_parser` in production; `tg_parser_test` locally):

```sql
SELECT user_id, title, COUNT(*) AS n
FROM watch_interests
GROUP BY user_id, title
HAVING COUNT(*) > 1
ORDER BY n DESC, user_id;

SELECT owner_id, name, COUNT(*) AS n
FROM digest_subscriptions
GROUP BY owner_id, name
HAVING COUNT(*) > 1
ORDER BY n DESC, owner_id;
```

Note each `(user_id, title)` / `(owner_id, name)` pair plus the
duplicate count.

## 2. Resolve

For each duplicate group keep exactly one row (preferably the most
recently touched — highest `updated_at`) and delete the rest. Example
SQL pattern for watchlist (adapt to digest by swapping table /
columns):

```sql
-- Inspect candidates per group:
SELECT id, user_id, title, is_active, updated_at, created_at
FROM watch_interests
WHERE (user_id, title) IN (
    SELECT user_id, title FROM watch_interests
    GROUP BY user_id, title HAVING COUNT(*) > 1
)
ORDER BY user_id, title, updated_at DESC;

-- Delete all but the latest per group (preserve provenance — the
-- caller can also merge keywords / channel_ids manually before
-- DELETE if the rows are semantically distinct):
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id, title
                              ORDER BY updated_at DESC, created_at DESC) AS rn
    FROM watch_interests
)
DELETE FROM watch_interests
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
```

> ⚠️ Hard DELETE drops match history (`watch_matches` rows CASCADE on
> `interest_id`). If preserving match log of the older row matters,
> instead UPDATE the older row's `title` to a suffixed variant
> (e.g. `<title> (archived 2026-05-21)`) before re-running the
> migration; that defuses the UNIQUE collision while keeping all
> rows.

For digest the audit blast radius is smaller (no `watch_matches`
analogue — digest sends are observability-only metrics) so the
DELETE path is usually safe.

## 3. Verify

Re-run both inspection queries from § 1 — expect 0 rows.

```sql
SELECT COUNT(*) FROM (
    SELECT 1 FROM watch_interests
    GROUP BY user_id, title HAVING COUNT(*) > 1
) AS d;
-- Expected: 0

SELECT COUNT(*) FROM (
    SELECT 1 FROM digest_subscriptions
    GROUP BY owner_id, name HAVING COUNT(*) > 1
) AS d;
-- Expected: 0
```

## 4. Restart migration

```bash
.venv/bin/alembic -c migrations/alembic_ingestion.ini upgrade head
# or, via the project CLI wrapper if it exposes `db check`:
# .venv/bin/tg-parser db upgrade --branch ingestion
```

Expected output: clean `Running upgrade e9f0a1b2c3d5 -> f1a2b3c4d5e6,
Wave 1 step 3 — Surface Parity foundation (ENH-9 + BUG-022)`.

## 5. Cross-references

- BUG_LOG.md § BUG-022 (issue) — service-layer upsert closes the
  bug; this runbook covers the one-off pre-existing-row cleanup
  needed before the constraint can be installed.
- ADR 0009 (idempotency) — Option C hybrid; service-layer half is
  the natural-key UNIQUE this runbook protects.
- Sprint prompt
  `docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md` § 3 Q2
  + § 8 R-3 (risk register).
