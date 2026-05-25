# Wave 1 Step 4 — DONE marker (24h VPS watch closure draft, PASS-WITH-CAVEATS)

**Дата создания:** 2026-05-24 (immediately after PR #93 squash-merge).
**Финализация (this draft):** 2026-05-25T06:22Z — pre-closure session, ~4h до nominal close `2026-05-25T10:50:10Z`.
**Watch closed:** `2026-05-25T10:50:10Z` (nominal T+24h reached; closure-session reminder #105 fired automatically at `2026-05-25T10:51:02Z`). Closure-session executed at `2026-05-25T11:15Z` by automated coordinator agent under operator approval. Final verdict: **PASS-WITH-CAVEATS**.

**Закрывает:** Wave 1 step 4 «Shareable Digest / ADR 0008 polymorphic subscription target» per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) and ADR [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) Option B (polymorphic `target` discriminator on digest + watchlist subscribe across HTTP, MCP, Bot, CLI).

**Reviewer (agent):** automated coordinator agent (Wave 1 Step 4 closure pre-flight session, 2026-05-25T06:22Z).
**Reviewer (operator):** @alexanderefimov.

---

## 1. Header / metadata

| Field | Value |
|---|---|
| **Sprint scope** | Wave 1 Step 4 — ADR 0008 polymorphic subscription target (channel-publish path for digests + watchlists) |
| **PR** | [#93](https://github.com/AlexEfimov/openai/TG_parser/pull/93) — «feat(wave1-step4): shareable-digest / ADR-0008 polymorphic target» |
| **Merge commit** | `926a165` (squash-merged 2026-05-24T09:39:52Z by AlexEfimov) |
| **Alembic head** | `a8b7c6d5e4f3` (single forward step from step-3 baseline `f1a2b3c4d5e6`; no dedupe required — step 4 migration has no natural-key UNIQUE constraints that could conflict with existing rows) |
| **Deploy target** | PRODUCTION VPS (`redboxtgbot`, `212.72.189.15:2296`); local-stack parallel sibling watch in [`WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md) |
| **Container `StartedAt`** | All three (`tg_parser`, `tg_parser_mcp`, `tg_parser_bot`) recreated `2026-05-24T10:46:28Z` from `tg_parser:latest` (sha256 `1a3cb6b8…`, rebuilt from `main @ 926a165`); all healthy by `2026-05-24T10:47:13Z` (~44s) |
| **Watch opened** | `2026-05-24T10:50:10Z` (~13:50 MSK 24-05) — declared OPEN after full deploy + alembic upgrade + smoke matrix 3×201 + 3×204 + transient-startup-race recovery confirmed |
| **Watch nominal close** | `2026-05-25T10:50:10Z` (~13:50 MSK 25-05) — T+24h |
| **Pre-deploy backup** | `~/TG_parser/backups/pre_step4_vps_backup_20260524T104149Z.sql` (239 KB, md5 `27da1fa9e3c752196489dfb218d55855`, `pg_dump -t digest_subscriptions -t watch_interests`); local mirror `backups/pre_step4_backup_20260524T094610Z.sql` |

---

## 2. Scope (Wave 1 Step 4)

**Sprint goal:** materialize ADR 0008 Option B — replace `chat_id INT NOT NULL` with a polymorphic `target` discriminator across all subscription surfaces (HTTP, MCP, Bot, CLI), enabling channel-publish for digests + watchlists in addition to the legacy chat-publish path.

**Concrete deliverables landed in PR #93:**

* **Schema:** alembic migration `a8b7c6d5e4f3` — `digest_subscriptions.target_kind` (enum `chat|channel`, NOT NULL, default `chat` for backfilled rows), `digest_subscriptions.channel_id` (varchar, nullable), `digest_subscriptions.chat_id` nullable (was NOT NULL); symmetric columns on `watch_interests`.
* **HTTP API:** `POST /api/v1/digests` + `POST /api/v1/watchlists` accept `target={kind:chat, chat_id:...}` or `target={kind:channel, channel_id:"@..."}`; legacy top-level `chat_id` still accepted via backward-compat shim that translates to `target={kind:chat, chat_id:...}` in the response.
* **MCP:** `subscribe_digest` / `subscribe_watchlist` tools accept polymorphic `target` argument; `list_digests` / `list_watchlists` return projection with `target_kind` + `channel_id` fields.
* **Bot:** `prompts/bot.yaml` v1.7.0 with new `target_kind_semantics` section teaching the LLM to disambiguate «в канал @username» (→ `target_kind=channel`) from «в этот чат» / DM (→ `target_kind=chat`).
* **CLI:** `tg-parser sub digest …` + `tg-parser sub watchlist …` flags propagate `target` shape to MCP.
* **Channel publish path:** `digest_service.py` + `watchlist_service.py` resolve `target.kind=channel` to a `bot.send_message(chat_id=channel_id)` call with best-effort soft-deactivation (`is_active=false`) on permanent permission errors (e.g. `Forbidden: bot is not a member` → `result="permission_denied"` Prometheus counter increment + sub auto-deactivated).
* **Observability:** `tg_digest_channel_publish_total{result="success|permission_denied|failed"}` Prometheus counter; symmetric counter for watchlist matching path.
* **Tests:** Phase 9 self-review +32 default-mode + +42 `TEST_POSTGRES=1` (see § 3 «Phase 9 self-review additions»).
* **Anti-scope (NOT in this sprint):** PATCH target update; test-publish endpoints; middleware broadening; `kind=webhook`; BUG-025/026/027 bot UX (deferred to Wave 2A / housekeeping per sprint prompt).

---

## 3. Quality gates (pre-merge, local)

| Gate | Result |
|---|---|
| Default pytest | **2246 passed / 0 failed** (post Phase 9 self-review +32) |
| `TEST_POSTGRES=1` pytest | **2560 passed / 0 failed** (post Phase 9 self-review +42) |
| Ruff | clean on all branch-touched files (1 pre-existing UP038 in `tg_parser/services/scheduler_service.py` from `main`, unrelated) |
| `prompts/bot.yaml` diff | version bump + `target_kind_semantics` section only (no other behavioural drift) |

### Phase 9 self-review additions (2026-05-24, pre-merge)

Strengthened test coverage in a follow-up self-review pass before merge:

* **`tests/test_subscribe_legacy_chat_id.py`** — added neither/instance-passthrough/invalid-dict edge cases, watch-interest round-trips (chat + channel), storage-field symmetry, and an explicit unresolvable-target guardrail.
* **`tests/test_digest_channel_publish.py`** — parametrised over all known permanent-error fragments, asserted `record_digest_channel_publish` labels for `success` / `permission_denied` / `failed`, fallback-DM happy path, fallback-DM-fails-and-is-swallowed path, and chat-target failure propagation (no soft-deactivate).
* **`tests/test_alembic_subscription_target_migration.py`** — symmetric `watch_interests` columns, `pg_enum` value pin, idempotent re-upgrade, downgrade success when no channel rows, downgrade-blocks-on-channel-rows guardrail.
* **`tests/test_contracts_subscription_target.py`** — additional negative cases (extra fields, type mismatch, channel_id on chat variant) + self-consistency check on `examples`.
* **`tests/test_api_digests.py` + `tests/test_api_watchlists.py`** — explicit HTTP `target=channel` happy path, explicit `target=chat`, `chat_id`+`target` 422 conflict, neither-set 422, idempotent replay with `target=channel`.

One small lint hygiene fix in production code: `tests/test_subscribe_legacy_chat_id.py` revealed UP038 on `isinstance(target, (TargetChat, TargetChannel))` in `tg_parser/domain/models.py` → switched to `TargetChat | TargetChannel` (no behaviour change).

---

## 4. Quality gate verdict — PASS-WITH-CAVEATS

**Verdict (this draft, finalized at closure session):** **PASS-WITH-CAVEATS.**

Closure criteria materialization (from [`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) C-1…C-12, primary criteria only listed here):

| Criterion | Status | Evidence |
|---|---|---|
| **C-1** `tg_digest_channel_publish_total{result="success"} ≥ 1` | ✅ **MATERIALIZED** | Test A: digest delivered to R-1 (`@vps_watch_test_r1_Alex`); counter 0 → 1 at 2026-05-24T~20:55Z. |
| **C-2** `tg_digest_channel_publish_total{result="permission_denied"} ≥ 1` | ✅ **MATERIALIZED** | Test B: R-2 (`@vps_watch_test_r2_Alex`, bot NOT member) → soft-deactivated `is_active=false`; counter 1 → 2 (1 pre-existing baseline from deploy verification + 1 new). |
| **C-3** `tg_digest_channel_publish_total{result="failed"} ≥ 1` | ⚠️ **UNTESTED** | No real-fail path exercised in OP-2 / OP-3 tests; would require Telegram API timeout / rate-limit conditions that we did not reproduce. Not blocking closure — `failed` label is structurally registered + Prometheus-visible; only the «materialize the increment» step deferred. |
| **Bot prompt v1.7.0 `target_kind_semantics`** | ⚠️ **PARTIAL** | **Disambiguation: GREEN** — Tests C+D both inferred `target_kind` correctly from NL («в канал @username» → `channel`; «в этот чат» → `chat`). **Payload: BROKEN in D** — `chat_id=123` placeholder leak (BUG-033 Critical) + `channel_ids=["pro_fendocrinologist"]` misparsed from typo «pro fendocrinologist» with space (BUG-034 Medium). |

**OP-2 / OP-3 interactive tests (T+10h45m batched section):** see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) for the full results table (A=GREEN, B=GREEN-with-caveat, C=GREEN-on-disambig/RED-on-flow, D=PARTIAL, E=GREEN-on-schema).

**Pre-deploy data shape was migration-safe** (see watch note § Pre-deploy data shape): all 1 `digest_subscriptions` row + 12 `watch_interests` rows had non-NULL `chat_id` → backfill `target_kind='chat'` for all existing rows was safe; downgrade path remained reversible.

**Deploy smoke verdict (immediate, 2026-05-24, on VPS):** ALL 4-surface HTTP contracts confirmed: `target.kind=chat` discriminator round-trip; `target.kind=channel` discriminator round-trip; legacy `chat_id` shim → `target.kind=chat` in response; DELETE 204 on all three shapes. **Prod row `digest_94483db9` survived backfill + smoke + cleanup unchanged.**

---

## 5. Bugs filed during watch window

The watch window surfaced 7 new BUGs + 1 OBS + 2 retroactive stubs filed during pre-closure pre-flight (2026-05-25T06:22Z). Severity adjudication and disposition:

| ID | Severity | Surface | Summary | Disposition |
|---|---|---|---|---|
| **BUG-029** | Medium | Backend correctness | `digest_service.subscribe_digest` race-retry branch missing `await session.rollback()` before retry → cascading session-state errors on concurrent `IntegrityError`. Lines 263-284 of `digest_service.py`. | **Stub filed retroactively** 2026-05-25T06:22Z per OA-7 commitment. Defer to Step 5 quality work; bundle with BUG-013 family scheduler-hardening PR. |
| **BUG-030** | Medium | Backend startup | Bot `_start_digest_scheduler` (`tg_parser/bot/main.py:285-340`) initial-load fragile to Postgres startup race — silent fallback to `active_subscriptions=0` on first read failure, recovery only via 60s reconcile-loop, no retry-with-backoff. Empirically observed once at deploy 2026-05-24T10:46:40Z; self-healed within 60s. | **Stub filed retroactively** 2026-05-25T06:22Z per OA-8 commitment. Defer to Step 5 quality work; bundle with BUG-029 + BUG-035 in single scheduler-hardening PR. |
| **BUG-031** | Severe | Bot UX | Bot creates digest subscription in DB **BEFORE** user confirms — preview-then-confirm contract inverted; «📰 Подписка создана» message precedes the «Подтвердите [да/нет]» prompt. Observed Tests C + D. | Open; file fix PR before user-facing bot rollout to other groups; bundle with BUG-032 (companion confirmation parser) and BUG-009 pattern (server-side guard). |
| **BUG-032** | Medium | Bot UX | Bot does not parse «да» / «подтверждаю» as valid confirmation tokens — responds «Я не совсем понимаю ваш ответ» to all plain affirmatives. Observed Tests C + D. | Open; bundle with BUG-031 (single FSM `ConfirmFlow` PR). |
| **BUG-033** | **Critical** | Bot correctness | Bot in group context inserts `chat_id=123` hardcoded placeholder for «в этот чат» NL intent instead of consuming `Message.chat.id`; resulting subscription is undeliverable (Telegram chat `123` ≠ real group `-5279672667`). Observed Test D. | Open; treat as Critical step-4 hotfix candidate; file before any user-facing bot rollout to additional groups. |
| **BUG-034** | Medium | NL parser | Source channel name parser fails on user typo with embedded whitespace («pro fendocrinologist» → underscored `pro_fendocrinologist` mismatch against real source `profendocrinologist`). Observed Test D. | Open; bundle with BUG-033 (Test D `subscribe_digest` correctness batch); add Layer 8 `get_source_by_username` pre-validation on write surfaces (mirrors BUG-010 read-side pattern). |
| **BUG-035** | **Critical** | Scheduler race | `unsubscribe_digest` does not invalidate pre-loaded APScheduler job — orphan-tick after mid-flight unsubscribe. Observed Test C cleanup: Test C sub (`5d8b83ad…`, cron `0 * * * *`) unsubscribed at ~20:58Z; 21:00Z tick fired anyway and delivered orphan digest to R-1. **Post-watch follow-up confirmed BOUNDED_1FIRE empirically 2026-05-25T06:05Z** — no further deliveries observed in R-1 across 9 cron-tick opportunities (22:00, 23:00, 00:00, 01:00, 02:00, 03:00, 04:00, 05:00, 06:00 UTC); after the single orphan tick fires, the in-memory APScheduler job ages out / next reconcile-loop tick removes it, and no further orphan deliveries materialize. | Open; treat as Critical step-4 hotfix candidate; bundle with BUG-030 in single scheduler-hardening PR (closely related — both touch scheduler ↔ DB consistency at different lifecycle phases). |
| **BUG-036** | Low | Ops / observability | Grafana alert-rule UI-state drift; `noDataState: OK` for `tg_api_5xx_spike` rule (folder `wave1-step4-watch`) did not persist between 2026-05-24T18:30Z UI patch and 22:11Z (#100) / 02:16Z (#101) re-fires with identical fingerprint `47991b0914dd7148`. Root cause: rule state not provisioned-as-code; Grafana restart or sync resets non-provisioned state. | Open; defer to Step 5 — provision all 3 alert rules (`tg_parser_bot_down`, `tg_parser_api_down`, `tg_api_5xx_spike`) via file-based provisioning at `docker/grafana/provisioning/alerting/wave1_step4.yaml`. |
| **BUG-037** | Low | Ops / automation | Cursor webhook automation classifier `7b35ca01-a7d1-4c3a-bb8b-940918e506d6` routes identical Grafana payload (fingerprint `47991b0914dd7148`, rule `tg_api_5xx_spike`, identical `startsAt`) to different GitHub issue title prefixes (#100 → `[5xx]`, #101 → `[alert]`). Inconsistent triage / dashboard search. | Open; defer to Step 5 or earlier if `7b35ca01` automation logic is easily readable from Cursor UI. |
| **OBS-001** | Observation | Watchlist matcher | `watch_interests.last_checked_at` stagnation — all 5 active pre-existing interests stuck at `2026-05-24T11:48:25Z` (~10h before watch session); our new Test E interest `2184bced…` shows `last_checked_at=null` even **after** successful manual `trigger_pipeline` run. Four hypotheses (matcher only on scheduled hook, matcher only updates on match found, step-4 schema migration broke matcher query, threshold gate too long). | Open / observation; investigate in separate session (~1-2h spike) outside step-4 closure scope; **not blocking C-1..C-3**. Promote to BUG-NNN if Hypotheses A or C confirm (matcher silently not running for `target.kind=channel` watchlists would be a step-4 regression). |
| **DOC-001** | Trivial | Documentation | Production bot is `@Tgingest_bot` (id `8657845219`), but `docs/prompts/DEV_RESURRECTION_PROMPT.md:26` still references stale `@smoke_tgparser_bot`. | Open; trivial cleanup — can ride along any near-term commit touching `docs/prompts/`. |

---

## 6. GitHub issues touched during watch window

All issues opened during the watch window have been triaged and closed:

* **#94, #95, #96, #97, #98** — deploy verification round + handled noData firings during 2026-05-24 watch day (all CLOSED with deferral / resolution comments).
* **#99, #100, #101** — late-watch noData re-fires (BUG-036 / BUG-037 root cause); all CLOSED at finalization 2026-05-25T06:11Z with deferral comments linking to BUG-036 / BUG-037.

No issues remain open from this watch window. All 8 issues either resolved or explicitly deferred-to-step-5 with rationale recorded in BUG-036 / BUG-037.

---

## 7. Production stack health at closure

**MCP `list_digests` snapshot (2026-05-25T06:22Z pre-closure pre-flight, the only ALLOWED MCP read for this session):**

```json
{
  "id": "94483db9-9351-4f99-9aec-46949d9ddd09",
  "owner_id": "c59d42b4-8e05-42a7-be7e-50e9d1f4b951",
  "chat_id": 5445781511,
  "channel_id": null,
  "target_kind": "chat",
  "name": "Эндокринология — ежедневный дайджест",
  "channel_ids": ["profendocrinologist"],
  "cron_expression": "0 9 * * *",
  "timezone": "Europe/Nicosia",
  "format": "summary",
  "language": "ru",
  "is_active": true,
  "last_sent_at": "2026-05-25T06:00:05.145122+00:00",
  "last_digest_cursor": "2026-05-25T05:48:17.533872+00:00",
  "workspace_id": null
}
```

**Interpretation:**

* `digest_94483db9` (prod endocrinology daily digest) ticks fired successfully on both consecutive days inside the watch window:
  * **2026-05-24T06:00:08Z** (per watch note § Deploy smoke row 14 — `last_sent_at=2026-05-24 06:00:08.445386+00`, pre-deploy state).
  * **2026-05-25T06:00:05.145122+00:00** (per MCP `list_digests` snapshot above — post-deploy state; OA-5 PASSIVE check ✅).
* `target_kind='chat'` preserved through deploy + migration + cleanup (no drift to `channel`).
* `chat_id=5445781511` (REAL user, owner = same) unchanged.
* `is_active=true`, `fail_count` not surfaced in this projection but per OA-5 was clean.
* **Cron-tick regression guard: PASS** — the critical legacy-chat-dispatch path that BUG-028 hotfix unblocked continues to deliver end-to-end with the new ADR 0008 schema.

**Container health snapshot:** All three (`tg_parser`, `tg_parser_mcp`, `tg_parser_bot`) healthy since `2026-05-24T10:46:28Z` recreate; zero restarts in 19h+ since. `tg_parser_postgres` / `tg_parser_grafana` / `tg_parser_prometheus` retained running (3-7 weeks uptime, not part of step-4 deploy scope).

**Up-series:** `up{job="tg_parser_api"}=1`, `up{job="tg_parser_bot"}=1`, `up{job="tg_parser_mcp"}=1` per OP-2 / OP-3 baseline (T+10h45m); no scrape failures observed in interim per OA-1 / OA-2 active checks (see watch note § Targets for closure session).

---

## 8. Open follow-ups (not blocking closure)

| # | Item | Class | Timing | Tracking |
|---|---|---|---|---|
| 1 | **BUG-029 / BUG-030 stubs** need code-detail fill-in (exact line ranges re-verified, CI test plan elaborated) during Step 5 quality sprint scoping. | Backend correctness / startup (Medium) | Step 5 quality work | `BUG_LOG.md` § BUG-029, § BUG-030 |
| 2 | **BUG-033 / BUG-034** are bot-prompt regressions — file fix PR BEFORE user-facing bot rollout to other groups (current rollout is operator-only). BUG-033 is Critical (placeholder `chat_id=123` would cause silent orphan deliveries to bogus chat). BUG-034 is Medium (silent semantic failure for typo'd channel names). | Bot correctness (Critical / Medium) | Before bot rollout broadening; bundle as «Test D fix batch» | `BUG_LOG.md` § BUG-033, § BUG-034; `WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md` § Closure decision review |
| 3 | **BUG-035** scheduler unsubscribe atomicity — confirmed BOUNDED_1FIRE empirically (only 1 orphan tick before in-memory job ages out / next reconcile cleans it); treat as Critical step-5 hotfix candidate; bundle with BUG-030 in single scheduler-hardening PR per BUG-035 closure plan. | Scheduler race (Critical) | Step 5 hotfix | `BUG_LOG.md` § BUG-035 |
| 4 | **BUG-031 / BUG-032** — FSM `ConfirmFlow` preview-then-confirm hardgate + confirmation token parser expansion; bundle in single bot-prompt-v1.7.x PR with Layer A whitelist expansion + Layer B server-side hardgate (mirrors BUG-009 pattern). | Bot UX (Severe / Medium) | Before bot rollout broadening | `BUG_LOG.md` § BUG-031, § BUG-032 |
| 5 | **BUG-036** needs Grafana provisioning-as-code work in Step 5 (file-based provisioning at `docker/grafana/provisioning/alerting/wave1_step4.yaml` for all 3 alert rules + contact-point binding). | Ops / observability (Low) | Step 5 | `BUG_LOG.md` § BUG-036 |
| 6 | **BUG-037** Cursor automation `7b35ca01` classifier branch determinism (`labels.rulename` first, then `labels.alertname`, then generic `[alert]` only if both absent). | Ops / automation (Low) | Step 5 or earlier if UI-readable | `BUG_LOG.md` § BUG-037 |
| 7 | **OBS-001** watchlist matcher `last_checked_at` stagnation — investigate in separate session (~1-2h spike) to distinguish the four hypotheses; promote to BUG-NNN if structural bug confirmed. | Observation (potentially backend regression) | Separate spike, post-closure | `BUG_LOG.md` § OBS-001 |
| 8 | **DOC-001** (`@smoke_tgparser_bot` → `@Tgingest_bot` cleanup in `docs/prompts/DEV_RESURRECTION_PROMPT.md:26`) — trivial fix can ride along any near-term commit. | Documentation (Trivial) | Opportunistic | `BUG_LOG.md` § DOC-001; watch note § OP-2/OP-3 anomalies #8 |
| 9 | **Cursor automations cleanup** — `2bd25769-52b1-4525-a0c5-239d589d231f` (P0-4 verifier, single-shot, already fired) and `f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f` (T+24h closure reminder, single-shot, will fire at 10:50Z) MUST be `update_automation({enabled: false})`'d AFTER closure (10:50Z). **DO NOT do it now** — `f93e557a` fires the closure reminder itself; disabling pre-fire would suppress the reminder. Documented in [`WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` § A](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md). | Cleanup (operator-orchestrated) | Post-closure (after 10:50Z) | `WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`; `WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` § A |
| 10 | **7 `[DELETE_ME] schema-probe-*` Cursor automations** must be deleted in Cursor UI (manual — no MCP delete tool exposed; only `update_automation` available, which can disable but not remove). | Cleanup (operator-manual) | Post-closure, opportunistic | `WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` § B |
| 11 | **Grafana `GRAFANA_ADMIN_PASSWORD` rotation** — was passed plaintext earlier in operator transcript during 2026-05-24 deploy verification; rotate per standard credential-hygiene protocol. | Security / ops | Post-closure, opportunistic | `WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` § C |

---

## 9. Cross-references

| Document | Purpose |
|---|---|
| Sprint prompt | [`docs/notes/START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md) — locked decisions + acceptance criteria. |
| Plan | [`docs/notes/PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md) — phase breakdown + ADR 0008 implementation map. |
| ADR | [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — Option B polymorphic discriminator (accepted). |
| Deploy runbook | [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md). |
| VPS watch exercise plan (PRIMARY) | [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md). |
| VPS watch window log | [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) — full chronological observation log. |
| Local-stack watch (parallel sibling) | [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md). |
| OP-2 / OP-3 interactive tests runbook | [`docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md`](../runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md). |
| VPS operator-manual actions | [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](../runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md). |
| Cursor Automations registry | [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md). |
| Post-closure cleanup runbook | [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) — created this session. |
| Step-3 VPS watch precedent (structural mirror) | [`docs/notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md). |
| BUG_LOG (BUG-029 through BUG-037 + OBS-001 + DOC-001) | [`docs/notes/BUG_LOG.md`](BUG_LOG.md). |

---

## 10. Sign-off block

```
- Reviewer (agent):    automated coordinator agent (Wave 1 Step 4 closure pre-flight session)
- Reviewer (operator): @alexanderefimov
- Watch window opened: 2026-05-24T10:50:10Z
- Watch window closed: 2026-05-25T10:50:10Z (nominal T+24h); closure-session executed 2026-05-25T11:15Z
- Closure-session by:  automated coordinator agent under operator approval at 2026-05-25T11:15Z
- Final verdict:       PASS-WITH-CAVEATS (closure criteria C-1, C-2 materialized;
                       C-3 untested but structurally registered;
                       bot prompt v1.7.0 disambiguation verified with payload caveats;
                       7 new BUGs filed (BUG-031..037);
                       2 stubs filled retroactively (BUG-029, BUG-030);
                       1 OBS noted (OBS-001 — watchlist matcher investigation);
                       1 DOC fix noted (DOC-001 — stale bot username))
```

**Closure-session 2026-05-25T11:15Z addendum:**

- **BUG-036 severity bump (Low → Medium):** Grafana `tg_api_5xx_spike` no-data fired three further ops-noise issues (#102 at 06:20Z, #103 at 10:25Z, #104 at 10:31Z) — #102 was a race-acceptable fire ~1 min before operator's `noDataState=Normal` UI patch at 06:21Z, but #103 and #104 re-appeared **4h+** after the same UI patch, confirming that the change did not persist across Grafana's evaluation cycle. The rule must be provisioned as code in step 5 (`docker/grafana/provisioning/alerting/wave1_step4.yaml`) — see BUG_LOG.md BUG-036.
- **Final issue tally:** 12 GitHub issues touched the watch window: #94–#101 (8 ops-noise during window, all closed during window) + #102–#104 (3 BUG-036 re-fires, closed at closure-session 11:15Z) + #105 (closure-reminder, closed at closure-session 11:15Z) = **9 closed during watch + 3 + closure-reminder = 12 total**.
- **Closure-session executor:** automated coordinator agent under operator approval at 2026-05-25T11:15Z.


**Closure session checklist (executed at 2026-05-25T11:15Z — all DONE):**

1. [x] Replaced closure-timestamp placeholder in § Header + § 10 sign-off block with actual values (`2026-05-25T10:50:10Z` nominal close; `2026-05-25T11:15Z` closure-session execution).
2. [x] MCP `list_digests` health check executed prior to closure (see § 6 of WATCH_WINDOW log) — `digest_94483db9.last_sent_at` healthy.
3. [x] Cursor automations `2bd25769-52b1-4525-a0c5-239d589d231f` (P0-4 verifier) + `f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f` (T+24h closure reminder) disabled at 11:15Z via `cursor-backend-control` MCP. `7b35ca01-aa3b-4cb8-b8bb-940918e506d6` (Grafana webhook ingress) retained for future watch windows.
4. [x] Three new ops-noise issues added to § 5/§ 8 (#102, #103, #104 — same fingerprint as BUG-036; severity bumped Low → Medium in `docs/notes/BUG_LOG.md`).
5. [x] Closure-session changes committed by operator-authorized commit (single commit, no `git push`; operator will push manually).
