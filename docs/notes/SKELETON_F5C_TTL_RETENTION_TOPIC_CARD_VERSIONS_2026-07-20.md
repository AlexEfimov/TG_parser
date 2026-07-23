# SKELETON — F5-C #15 TTL/retention for `topic_card_versions`

> **✅ LANDED (2026-07-22) — this skeleton is superseded by the implementation.**  
> Code + tests + ADR shipped in the impl-session. Current SoT:
> [ADR-0018](../adr/0018-topic-card-versions-retention.md),
> [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md),
> [`START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md),
> runbook [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § «Retention / purge».
> Final decisions differ slightly from the sketch below (e.g. **genesis-pin
> `version_no=1`** added as a second provenance-floor). Kept for history.

> **SKELETON / docs-only / not ready to implement (historical).**  
> Contract sketch for GitHub issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item **TTL/retention**.  
> No Alembic, no Settings knobs, no prod SQL, no purge job in this document’s landing session.  
> Impl requires explicit owner GO + a dedicated START_PROMPT.

**Дата:** 2026-07-20  
**Track:** ζ (post-γ closeout) — [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md)  
**Anchors:** FUTURE_FEATURES F5-C «Что НЕ входит в MVP»; [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) (versions growth); ADR-0006 #1 / #2 / #4.

---

## 1. Goal (one-liner)

Bound unbounded growth of append-only `topic_card_versions` with an explicit retention policy that preserves enough provenance for audit, without breaking `get_topic_versions` or re-summarize idempotency.

---

## 2. Problem

MVP stores **every** pre-UPSERT snapshot in `topic_card_versions` (F5-C). Growth is expected to be roughly linear with successful re-summarize outcomes (`tg_resummarize_total{outcome="ok"}`), but there is **no** TTL, keep-last-N, or purge path today.

Ops signal (runbook): if row count / relation size grows too fast (MB→GB territory), Phase 2 #1 (TTL/retention) becomes priority. Signals 2A/2B/2C are still 0 — product impl stays gated; this skeleton only pre-writes the contract surface.

---

## 3. Options (policy candidates)

| Option | Idea | Pros | Cons |
|---|---|---|---|
| **A. Time-TTL** | Hard/soft drop versions older than `N` days (e.g. 90/180) | Simple ops mental model; matches age-trigger family (`RESUMMARIZE_MAX_AGE_DAYS`) | May erase rare audit trail for cold topics; needs timezone/cutoff clarity |
| **B. Keep-last-N** | Per `topic_id`, retain only the newest `N` versions (e.g. 20/50) | Protects hot topics’ recent history; bounds worst-case per topic | Global disk still grows with topic cardinality; old topics keep N forever |
| **C. Hybrid** | `keep-last-N` **and** time-TTL (delete if older than T **and** outside last N) | Safer provenance floor + global bound | More knobs; harder acceptance matrix |
| **Delete mode** | Soft-delete (`deleted_at`) vs hard `DELETE` | Soft = reversible, audit-friendly; hard = true reclaim | Soft needs index/filter on all readers; hard is irreversible without backups |

**Skeleton default leaning (non-binding):** hybrid **C** with **hard DELETE** after a dry-run/metrics window — but owner GO must pick numbers and soft vs hard before impl.

---

## 4. Karpathy checklist impact (ADR-0006)

| Principle | Impact |
|---|---|
| **#1 Persistent entities** | Versions remain first-class rows; retention is a lifecycle policy, not demotion to JSON blob. |
| **#2 Provenance / evidence** | **Critical:** deleting versions removes audit of past `summary` / `scope_*` / LLM provenance. Policy must state the minimum retained evidence (e.g. last N always kept). |
| **#4 Idempotency** | Purge must not race re-summarize snapshot writes (`UNIQUE(topic_id, version_no)`, advisory lock). Prefer purge of **sealed** old rows only; never renumber `version_no`. |
| **#6 Observability** | Need before/after metrics: row count, relation size, purge deleted count, errors — extend runbook Panel 4 / SQL snapshot. |

Do **not** silently truncate history without documenting the retention floor in FUTURE_FEATURES / runbook.

---

## 5. Blast-radius

| Surface | Touch? | Notes |
|---|---|---|
| Alembic (processing branch) | Likely if soft-delete column or partial index | Hard DELETE-only job may avoid schema change |
| MCP `get_topic_versions` | Yes (filter / limit semantics) | Must not 500 on purged gaps; document “missing versions = retained policy” |
| Bot tools / diff API | No (out of scope; not MVP) | |
| Re-summarize / scheduler | Careful | Purge job must not hold locks against snapshot path |
| F11 / digests / workspaces | No | |
| Prometheus | Optional | Gauge/counter for versions rows or purge outcomes |
| Prod data | **Never in skeleton session** | Impl needs backup + dry-run |

---

## 6. Acceptance / metrics to watch (before & after impl)

**Before GO / impl:**

- Baseline SQL (runbook §4): `COUNT(*)`, `pg_total_relation_size('topic_card_versions')`, rows/day estimate from `tg_resummarize_total{outcome="ok"}`.
- Confirm `get_topic_versions` callers and max `limit` usage.

**After impl (acceptance sketch):**

- [ ] Retention policy documented (N / T / hybrid + soft vs hard) with owner-chosen defaults.
- [ ] Purge is idempotent; concurrent re-summarize does not violate `UNIQUE(topic_id, version_no)`.
- [ ] `get_topic_versions` returns remaining versions only; no crash on gaps.
- [ ] Dry-run mode (or metrics-only) available before first destructive prod run.
- [ ] Relation size / row growth trend improves or plateaus under expected resummarize rate.
- [ ] Runbook updated (growth note + purge/ops section); FUTURE_FEATURES TTL bullet → DONE or partial.

---

## 7. Out of scope (this skeleton / next impl session unless GO expands)

- Bot tools for version history; `get_topic_history_diff` / diff API.
- Wave E graph retrieval; F11 HTTP CRUD; webhook 2A.
- Track δ / T7 knob bump (`RESUMMARIZE_MAX_AGE_DAYS`) — separate session after watch.
- **Any code, migration, or prod DELETE in the ε+ζ landing session.**
- «Wave 3» naming.

---

## 8. Open questions for owner GO (before impl START_PROMPT)

1. Soft-delete vs hard DELETE? (default lean: hard after dry-run)
2. Numbers: keep-last-N = ? time-TTL days = ? hybrid conjunction or disjunction?
3. Should `version_no` gaps be visible to API clients, or should API present a dense “history index”?
4. Purge trigger: cron in `tg_parser` scheduler vs external SQL job vs one-shot CLI?
5. Minimum provenance floor for legal/debug (“never drop last successful summary’s prior snapshot”)?
6. Is production growth already painful enough to prioritize over other #15 items (diff API / Bot tools)?

---

## Pointers

- Issue #15 — TTL/retention sub-item  
- [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) F5-C Phase 2 bullet  
- [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) — `topic_card_versions` size SQL  
- [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) Track ζ  
- ADR-0006 — persistent entities / provenance / idempotency  
