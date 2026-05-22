# Watch window — Wave 1 Step 3 (PR #89)

**Opened:** 2026-05-22 (S3.1 Phase C deploy — containers recreated on prod after `a30abd5` pull + `f1a2b3c4d5e6` migration).

**Expected close:** 2026-05-23 ~same UTC offset + 24h (fill exact close timestamp when watch completes).

**Merge commit:** `a30abd5` — [PR #89](https://github.com/AlexEfimov/TG_parser/pull/89).

**Pre-deploy prod HEAD:** `39da8cc` (BUG-014B). **Post-deploy HEAD:** `a30abd5`.

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

## 24h queries (fill at watch close)

```bash
# Replace START/END with deploy window ISO timestamps
START=2026-05-22T...Z
END=2026-05-23T...Z

ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query_range?query=up{service=\"api\"}&start='"$START"'&end='"$END"'&step=900"'

# idempotency + subscribe counters
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=tg_idempotency_keys_hit_total"'
```

**Log scan:**

```bash
docker logs --since "$START" --until "$END" tg_parser 2>&1 \
  | grep -iE '/api/v1/(watchlists|digests)' | grep -iE 'error|5xx|exception'
```

---

## Verdict

| Field | Value |
|---|---|
| **Status** | `OPEN` — 24h window in progress |
| **Final verdict** | _TBD_ → update `REVIEW_2026-05-21_WAVE1_STEP3_DONE.md` |
