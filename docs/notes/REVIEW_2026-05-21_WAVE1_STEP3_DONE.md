# Wave 1 Step 3 — DONE marker (deployed; 24h watch OPEN)

**Дата создания:** 2026-05-22 (immediately after commit 4/4 lands).
**Deploy (Phase C):** 2026-05-22 — prod `a30abd5`, migration `f1a2b3c4d5e6` applied; see [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) + runbook [`WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md).
**Закрывает:** Wave 1 step 3 «Surface Parity MVP» per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).
**Packaging:** single PR + 4 atomic commits (mirror Wave 1 step 1 / step 2 hybrid pattern) per sprint prompt § 8.

> **STATUS NOTE.** This marker is a **stub**. Sections marked **TBD** will be filled after the 24h watch window closes GREEN per sprint prompt § 6. Authoring procedure mirrors `REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` (Wave 1 step 2 precedent).

---

## 1. Что закрыто

| Sprint slot | Commit (4/4) | Squash SHA | Deployed | 24h watch verdict |
|---|---|---|---|---|
| ENH-9 + BUG-022 service-layer foundation | 1/4 | `56e65e2` | 2026-05-22 | _pending 24h_ |
| P-1 Watchlist HTTP API (5 endpoints) | 2/4 | `6efb20b` | 2026-05-22 | _pending 24h_ |
| P-2 Digest HTTP API (4 endpoints) | 3/4 | `0e450eb` | 2026-05-22 | _pending 24h_ |
| Idempotency-Key HTTP middleware + cleanup + docs | 4/4 | `5b828cf` | 2026-05-22 | _pending 24h_ |

**Merge:** [PR #89](https://github.com/AlexEfimov/TG_parser/pull/89) → `a30abd5` (2026-05-22T10:38:12Z UTC).

**Закрытые bug / feature IDs:**

* **BUG-022** — `subscribe_watchlist` / `subscribe_digest` now idempotent on natural keys (`(user_id, title)` / `(owner_id, name)`). Service-layer pre-flight lookup updates mutable fields and returns existing UUID with `created=false`. Cross-surface fix (MCP / Bot / CLI / HTTP).
* **ENH-9** — `workspace_id` параметр на subscribe-tools на всех четырёх поверхностях; FK to `workspaces` с `ON DELETE SET NULL`.
* **P-1** — Watchlist HTTP API landed.
* **P-2** — Digest HTTP API landed.

## 2. Acceptance signals table (per sprint prompt § 6)

| # | Criterion | Source of truth | Status (pre-watch) | Watch verdict |
|---|---|---|---|---|
| 1 | `2175+ / 300+ / 0` default-mode pytest | `pytest -q --tb=line` | ✅ **2175 / 311 / 0** (verified pre-merge) | n/a |
| 2 | `2475+ / 9 / 0` `TEST_POSTGRES=1` pytest | `TEST_POSTGRES=1 pytest -q --tb=line` | ✅ **2477 / 9 / 0** (verified pre-merge) | n/a |
| 3 | `ruff format` + `ruff check` clean | repo-wide | ✅ verified pre-merge | n/a |
| 4 | 0 regressions on `test_api_watchlists`, `test_api_digests`, `test_subscribe_idempotency`, `test_watchlist_workspace_id`, `test_f4*`, `test_f6*`, `test_f11*` | targeted pytest | ✅ verified pre-merge (84 regression tests) | n/a |
| 5 | `tg_idempotency_keys_hit_total{result=hit\|miss\|mismatch}` time-series visible in Prometheus 24h post-deploy | `query?query=tg_idempotency_keys_hit_total` | deploy smoke: 0 series at T+0 | _pending 24h_ |
| 6 | `tg_idempotency_keys_table_size` gauge updates after first hourly cleanup tick (T+1h post-deploy) | `query?query=tg_idempotency_keys_table_size` | _pending 24h watch_ | _pending 24h_ |

## 3. Post-watch state

**Immediate deploy smoke (2026-05-22, localhost on VPS):** watchlist 201; digest invalid-cron 422; digest DELETE 204→404; workspace foreign 404; idempotency mismatch 422. Idempotency replay: same `watchlist_id`, no duplicate row; `created` JSON field still `true` on replay — flag for watch (middleware cache shape vs sprint §6 wording). Full table: [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).

**Pre-migration prod admin:** 3× `(user_id, title)` duplicate groups deduped ([`wave1_step3_idempotency_dedupe.md`](../runbooks/wave1_step3_idempotency_dedupe.md)).

_TBD after 24h watch closes._ Will include:

* Prometheus query_range snapshots over the watch window (`up{service=api|bot|mcp}` gauges, scheduler tick counter, new metrics from commit 4/4).
* Container health snapshot (`docker ps` table).
* Bot / API / MCP error-log scan over the watch window (`docker logs --since/--until`).
* Workspace + watchlist + digest surface zero-error proof.
* New-vs-regression bug class adjudication (mirror Wave 1 step 2 precedent — `git diff <merge_sha>^ <merge_sha>` as the discriminator).

## 4. Known partials / monitoring-only

| Item | Reason | Re-evaluate trigger |
|---|---|---|
| **ADR 0008** chat_id-only target (locked for this sprint) | Polymorphic webhook / channel target consciously deferred per sprint prompt anti-scope. Wave 1 step 4 (Shareable Digest) + Wave 2A (webhook surface) carry the follow-up. | Wave 1 step 4 planning sub-session re-reads ADR 0008 § Options + this marker. |
| **Idempotency-Key middleware opt-in per endpoint (Q-OPEN-7)** | Wired only on POST `/api/v1/watchlists` + POST `/api/v1/digests`. Broadening to other POST endpoints (`/api/v1/process`, `/api/v1/export`, …) is intentionally deferred. | Future PR if production usage shows broader transient-retry pain. ADR 0009 already prescribes the pattern. |
| **idempotency_keys schema `UNIQUE(key)` (not composite)** | PK is `key` alone (migration `f1a2b3c4d5e6`, commit 1/4 — locked, not amend-able per AGENTS.md § Hard rules). Cross-user same-key collisions degrade gracefully (security invariant «no cross-user cache leakage» holds; only second user loses retry-cache benefit). | If production tracking shows non-trivial cross-user `Idempotency-Key` collisions (low expected rate — clients typically use UUIDv4), file as a follow-up to migrate to composite PK in a future schema sprint. |
| **MCP / Bot / CLI surfaces** | No HTTP header equivalent of `Idempotency-Key`. Service-layer natural-key upsert (Option A from ADR 0009) is the sole protection. Adequate for these surfaces (no transient-retry concern equivalent to HTTP timeout). | n/a (architecturally complete). |

## 5. Cross-references

| Document | Зачем |
|---|---|
| Sprint prompt | [`docs/notes/START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md) — locked decisions Q1–Q9 + acceptance criteria. |
| Merge PR #89 | https://github.com/AlexEfimov/TG_parser/pull/89 — `a30abd5` |
| Deploy + watch | [`WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md), [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) |
| Step 3.1 planning | [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md), ADR 0007 Accepted |
| ADR 0009 (Accepted) | [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) — Option C hybrid (service-layer + HTTP header). |
| ADR 0008 (Draft) | [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — target model; chat_id-only for this sprint, polymorphic deferred. |
| CHANGELOG | [`CHANGELOG.md`](../../CHANGELOG.md) — `[Unreleased]` § «Wave 1 step 3 — Surface Parity» consolidates all 4 commits. |
| USER_GUIDE | [`docs/USER_GUIDE.md`](../USER_GUIDE.md) — new «HTTP API — Watchlist + Digest» section. |
| MCP_AGENT_GUIDE | [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) — REST table + parity note. |
| Wave 1 step 2 DONE marker (template) | [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) — structural mirror for the post-watch update. |
| Wave 1 step 1 DONE marker | [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) — earliest precedent. |

## 6. Lessons learned

_TBD after 24h watch._ Mirror Wave 1 step 2's pattern: 3-5 short bullet-points distinguishing «new bug surfaced by watch» vs «regression introduced by sprint» via `git diff` adjudication, plus any unanticipated operational gaps (e.g., env drift, fresh-log-buffer revelations).

## 7. Pre-next-step

**Wave 1 step 3.1 — MCP dispatch (ADR 0007 Accepted):** [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md) — closes BUG-015, ENH-1, ENH-2, O-3. **Can start in parallel** with step 3 24h watch.

**Wave 1 step 4 — Shareable Digest** — after step 3 watch GREEN + step 3.1 execution.

Recommended sequence (updated 2026-05-22):

```
PR #89 merged (a30abd5)
  ↓
Deploy + dedupe + migration (DONE 2026-05-22)
  ↓
24h watch OPEN → close → finalize this DONE marker § 2–3, § 6
  ∥ (parallel)
Wave 1 step 3.1 execution (START_PROMPT_SPRINT_WAVE1_STEP3_1)
  ↓
Wave 1 step 4 planning sub-session (~0.3 session) —
  read PARITY_DECISION_TRACKING.md § 3 (shareable digest signals + O-1/O-2),
  ADR 0008 § Options (polymorphic target promotion?),
  Wave 1 step 4 scope refinement
  ↓
Wave 1 step 4 sprint (Shareable Digest — channel-publish target,
  shareable links, audience activation A2 «Curator»)
```

Wave 1 step 3 sets up the prerequisites for shareable digests by establishing:

* HTTP API surface that downstream sharing tooling can consume.
* `workspace_id` scoping across both subscribe-tools.
* `Idempotency-Key` middleware reusable for any future POST that involves shareable-link generation (per ADR 0009 generalisation note).
* Natural-key idempotency contract on `digest_subscriptions` — guarantees that batched share invitations (potential Wave 1 step 4 surface) don't duplicate rows.

---

## Appendix — Sprint metrics (provisional, pre-watch)

| Metric | Value |
|---|---|
| Commits | 4 (atomic) |
| Files touched (cumulative) | _TBD (final diff aggregate)_ |
| LOC delta (cumulative) | _TBD (target was 1000–1400; final TBD after diff)_ |
| New tests | ~50+ across watchlist HTTP, digest HTTP, service-layer idempotency, middleware, cleanup (final count TBD after diff) |
| New Prometheus metrics | 2 (`tg_idempotency_keys_hit_total{result}`, `tg_idempotency_keys_table_size`) |
| New scheduler task | 1 (`idempotency_keys_cleanup`, cron `0 * * * *`) |
| New ADR transitions | 1 (ADR 0009 Draft → Accepted) |
| Migrations | 1 (`f1a2b3c4d5e6`, commit 1/4) |

_Final aggregates filled in the post-watch update._
