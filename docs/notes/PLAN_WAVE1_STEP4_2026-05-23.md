# Wave 1 Step 4 — Planning (2026-05-23)

**Author:** planning sub-session, ~22:00 UTC+4, 2026-05-23 (after BUG-028 closure session).
**Status:** **DRAFT — pending user resolution of § 7 open questions** before formalization / commit.
**Не start-prompt и не execution-pack.** Output этой сессии — scope-инвентарь + recommendation; sprint-prompt и checklist рождаются **в следующей сессии** после ответа на § 7.

---

## 1. Context

### 1.1 State of Wave 1

Wave 1 (Solo Polish, ~4.5–6 sessions per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)) исполнена строго по плану из [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md):

| Step | Scope | Closure | Verdict |
|---|---|---|---|
| 1 | Bot UX hardening (Sessions H/I/J + Session K extended) | [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) | DONE, 24h × 3 watches GREEN |
| 2 | F4-B Core Workspaces | [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) | DONE, 24h watch GREEN |
| 3 | Surface Parity (P-1 watchlist HTTP, P-2 digest HTTP, ENH-9 `workspace_id`, BUG-022 idempotency, ADR 0009 hybrid) | [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) | DONE, 24h watch GREEN (T+22h09m early-close, documented) |
| 3.1 | MCP HTTP dispatch (ADR 0007, BUG-015 closure) | rolled into § 3 review § 1, deploy `b875faf` | DONE, observed под общим step 3 watch |
| **4** | **Shareable Digest** (this planning artifact) | — | NOT STARTED |

**Current prod HEAD:** `668946e` (docs(bug-log): mark BUG-028 as resolved). Working tree clean on `main`. No outstanding deploys; всё что было выкачено в step 3 — стабильно на проде с 2026-05-22T17:42:42Z (`d143e5d`) + hotfix `26d03a5` от 2026-05-23 ≈19:23Z.

### 1.2 Step 3 closure summary

Step 3 закрыт **GREEN** 2026-05-23T09:35Z (T+22h09m, см. [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md)). Все 6 acceptance criteria PASS; 0 регрессий step 3; 5 open items вынесены в § 4a (см. § 3 ниже — Open Items inventory).

Baseline на момент step 4 planning:
* Pytest default: **2195 / 311 / 0**.
* Pytest `TEST_POSTGRES=1`: **2499 / 9 / 0**.
* Ruff: clean.
* ADR transitions step 3: ADR 0009 **Draft → Accepted** (hybrid Option C — service-layer natural-key upsert + HTTP `Idempotency-Key` middleware); ADR 0007 **Draft → Accepted** (MCP HTTP dispatch).
* Prometheus metrics step 3: `tg_idempotency_keys_hit_total{result}` + `tg_idempotency_keys_table_size` gauge — populated, monotonic, healthy.
* Migrations step 3: `f1a2b3c4d5e6` applied on prod (`idempotency_keys` table + `UNIQUE (user_id, title)` on `watch_interests` + `UNIQUE (owner_id, name)` on `digest_subscriptions`, pre-migration dedupe per [`docs/runbooks/wave1_step3_idempotency_dedupe.md`](../runbooks/wave1_step3_idempotency_dedupe.md)).

### 1.3 BUG-028 closure confirmation

[BUG-028](BUG_LOG.md) (digest cron `PromptLoader(prompts_dir=str(settings.prompts_dir))` → literal `"None"`) — **RESOLVED** хотфикс-сессией 2026-05-23:

* PR **[#92](https://github.com/AlexEfimov/TG_parser/pull/92)** «fix(bug-028): digest cron PromptLoader None-string regression (hotfix)» → squash [`26d03a5`](https://github.com/AlexEfimov/TG_parser/commit/26d03a5b9e40b64fa7f75f3a3de5576c67fca8ef), merged `2026-05-23T16:57:45Z`.
* All four layers landed (A — call-site guard; B — literal-`"None"` fallback in `PromptLoader`; C — settings.py default `Path("prompts")`; D — `PROMPTS_DIR=${PROMPTS_DIR:-/app/prompts}` on three services in `docker-compose.yml`).
* Prod deploy `~19:23Z`, all containers `healthy`, scheduler reloaded with the digest cron job.
* Status row + closure update в [`BUG_LOG.md` § BUG-028](BUG_LOG.md) (`Update 2026-05-23 — PR #92 landed → BUG-028 RESOLVED`).
* DONE-marker housekeeping commit `668946e` ставит explicit ✅ marker; REVIEW step 3 § 4a row #5 явно помечен closed.
* Pending operational follow-up (not blocking step 4): 24h watch на next digest cron tick `2026-05-24T06:00:00Z` (09:00 MSK) — handled by a separate watch session.

**Net effect for step 4 planning:** BUG-028 не блокирует. Других open critical-/high-severity scheduler bugs нет. Step 4 starts from a clean slate.

---

## 2. Inputs (read-list with cross-links)

Документы, фактически прочитанные в этой планирующей сессии. Каждая строка = relevance к step 4 scoping.

| # | Документ | Релевантность |
|---|---|---|
| 1 | [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) (§§ 2, 3, 4, 4a, 5, 6) | Primary input. § 4a Open Items #1–#7 = scope candidates pool. § 4 Known partials (ADR 0008 carry-forward + idempotency middleware opt-in) = directly references step 4. § 6 Lessons #1 + #3 = constraints. |
| 2 | [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) (§ 3.2) | Authoritative scope statement for step 4: «Light extension F6 (~0.3 сессии): `subscribe_digest(..., publish_to_channel="@my_curated_digest")` вместо private chat». Estimate baseline. |
| 3 | [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) (§§ 5.1 шаг 4, 3.3 A6) | Audience-driven rationale: A6 Domain Curator enabler без Web. Gating-validation для Wave 2B (Web Consumer). |
| 4 | [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) (§ 1 P-2, § 3) | P-2 digest scope explicitly мечется на «сцепка с step 4» (shareable digest enabler — `publish_to_channel`). Pre-references подтверждают, что HTTP-API параллельность step 3 была сделана с расчётом на step 4 расширение. |
| 5 | [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) (**Draft**) | **Critical input.** Lock target-addressing model для всех 4 surface'ов. Option B (polymorphic discriminator `chat\|channel\|webhook`) рекомендован, но не финализирован. Option C (parallel optional fields) backup. ADR explicitly references «Wave 1 step 4 enabler» в § Recommendation § Migration path. |
| 6 | [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) (Accepted, 2026-05-22) | Companion ADR. `digest_subscriptions` natural key = `(owner_id, name)`. ADR 0009 § Open questions Q-OPEN-7 (Idempotency-Key middleware opt-in per endpoint) → может расширяться в step 4 на digest target updates. |
| 7 | [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) (Accepted, 2026-05-22) | Контекст. Шаблон HTTP-proxy через `tg_parser`. Не блокирует step 4. |
| 8 | [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | Принципы 1 (persistent entity) + 7 (graceful degradation per failure mode) — нормативно для нового `target` shape. |
| 9 | [`docs/contracts/`](../contracts/) (full inventory: 7 schemas — `topic_card`, `topic_card_version`, `processed_document`, `topic_bundle`, `knowledge_base_entry`, `raw_telegram_message`, `workspace`) | High-level: ни одна существующая schema не описывает `digest_subscription` / `watch_interest` / `target` shape. Step 4 либо добавляет новую `subscription_target.schema.json`, либо расширяет implicit shape — ADR 0008 указывает что webhook payload должна получить отдельный schema (per Karpathy 1). |
| 10 | [`BUG_LOG.md`](BUG_LOG.md) — open bugs scan | BUG-019, BUG-020, BUG-021, BUG-025, BUG-026, BUG-027 (всё что осталось open после step 3 + закрытий 2026-05-21..23). См. § 3 ниже. |
| 11 | [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) (§ quality lifecycle) | Quality gates применимы к step 4. Pytest baselines + ruff + TEST_POSTGRES counters должны не упасть. |
| 12 | [`docs/notes/agents-roles.md`](agents-roles.md) | Architecture & ADR — для ADR 0008 promotion. Implementation — для код-сессии. Tests & QA — для contract + integration tests. |
| 13 | [`docs/runbooks/`](../runbooks/) (file names + headers: `WAVE1_STEP3_DEPLOY_AND_WATCH.md`, `wave1_step3_idempotency_dedupe.md`, `F5C_DEPLOY_AND_WATCH.md`, `SAFE_MIGRATION_ON_DEV.md`, `DEV_RESURRECTION.md`, `BOT_LLM_FALLBACK.md`, `ANTHROPIC_BILLING_RECOVERY.md`) | Step 4 потребует новый runbook `WAVE1_STEP4_DEPLOY_AND_WATCH.md` (mirror step 3 precedent) и потенциально pre-migration runbook если scheme touch. `SAFE_MIGRATION_ON_DEV.md` — нормативный процесс для любой migration. |
| 14 | [`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md`](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md) (§ Next session prompt suggestion) | Прямой pointer на эту сессию: «планирующая сессия Wave 1 step 4 (Shareable Digest, ADR 0008): re-read ADR 0008 § Options + `PARITY_DECISION_TRACKING.md § 3` + audience hints A2». |
| 15 | `git log --oneline -50 main` | Delivery cadence Wave 1: step 1 `aa32f6e`; step 2 `7953302`; step 3 `a30abd5`; step 3.1 `b875faf`; follow-ups `d143e5d`; closure `ed6d69e`; BUG-028 hotfix `26d03a5` + DONE-marker `668946e`. Все шаги — single-PR-multi-commit pattern на main; docs-only коммиты push'атся напрямую (precedent `2774890`, `84a3932`, `668946e`). |

---

## 3. Open Items inventory

Объединённая таблица: REVIEW step 3 § 4a + open BUG_LOG entries + sticky items из § 4 Known partials. Назначение — `fit-for-step-4` колонка → input для § 4 candidate scopes.

| # | Source | Item | Status | Fit step 4? | Notes |
|---|---|---|---|---|---|
| 1 | REVIEW § 4a #1 | `tg_pipeline_trigger_total{surface=mcp\|bot}` structurally unreachable (hardcoded `surface=api` at counter site) | open (architectural observability gap) | **no — defer** | Architectural ADR-class decision (header propagation contract vs counter-registration refactor). Bundle с surface-aware structlog request_id propagation в future observability sprint. Не имеет отношения к Shareable Digest scope. |
| 2 | REVIEW § 4a #2 + [BUG-025](BUG_LOG.md) | Bot `unsubscribe_watchlist` UUID validation (raw asyncpg traceback leaks to user) | open (Bot UX Medium) | **maybe — opportunistic** | Бундлится с любым next bot-side touch. Step 4 потенциально touch'нет `prompts/bot.yaml` (bot subscribe-tool semantics for `target` shape) — natural co-location. Independent fix ~30 LOC + 5-10 tests. |
| 3 | REVIEW § 4a #3 + [BUG-026](BUG_LOG.md) | Bot context loss on standalone-UUID continuation после bot suggestion (structural analogue BUG-011 write-side) | open (Bot UX Low) | **maybe — opportunistic** | Bundle with #2 (same prompt v1.5.0 + same `prompts/bot.yaml` touch). Option A prompt-only ~10 LOC; Option B FSM `SuggestionFlow` extension ~50 LOC если A insufficient. |
| 4 | REVIEW § 4a #4 + [BUG-027](BUG_LOG.md) | Service-layer typed return для already-inactive soft-delete (BUG-022 idempotency class) | open (Service UX Low) | **maybe — bundle with ADR 0009 next iteration** | Service-layer ~20 LOC + bot mapping ~5 LOC + prompt ~3 lines. Step 4 не touch'ает delete pathway directly — но если ADR 0008 расширяет subscription update semantics (mutable target), хорошее место синхронизировать idempotent-update сообщения. |
| 5 | REVIEW § 4a #5 + [BUG-028](BUG_LOG.md) | Digest cron PromptLoader literal-`"None"` regression | **✅ closed** (PR #92 `26d03a5`, deployed 2026-05-23 ≈19:23Z) | **n/a — already done** | Cross-check confirmed: BUG_LOG status `resolved`, prod containers `healthy`, four-layer fix landed. Pending only 24h watch on next cron tick `2026-05-24T06:00:00Z` (separate session, not step 4 scope). |
| 6 | REVIEW § 4a #6 + [HANDOFF § 3](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md) | Compose-integration CI test backlog (`@compose_only` marker exists, no GH Actions job) | open (CI infra) | **no — defer separate PR** | Per HANDOFF: «Separate PR after Wave 1 step 4». Not domain-bundled with Shareable Digest. Bundle с #1 (surface-label test) если/когда тот landed. |
| 7 | REVIEW § 4a #7 | Anthropic quota one-time exhaustion + fallback-provider policy для RAG `ask_question` on `credit_balance_too_low` | open (operational note / Lessons #4) | **no — defer** | External resource issue, not pipeline defect. Fallback-policy enhancement потенциально Wave 2A scope; не aligned со step 4 audience (A6 curator). |
| 8 | REVIEW § 4 Known partials | ADR 0008 chat_id-only target locked для step 3 sprint — promotion для polymorphic deferred to step 4 | open (ADR Draft) | **YES — primary input** | **This is the step 4 entry point.** ADR 0008 explicitly cites Wave 1 step 4 в § Recommendation § Migration path step 1–4 + § Open questions Q3 (channel publish best-effort). Promotion Draft → Accepted = blocking deliverable. |
| 9 | REVIEW § 4 Known partials | Idempotency-Key middleware opt-in per endpoint (Q-OPEN-7) — broadening to other POST endpoints | open (deferred) | **maybe — narrow scope** | Если step 4 добавляет PATCH `/api/v1/digests/<id>/target` (target update endpoint), idempotency middleware estimate +0 LOC (just wire on new endpoint). Если только POST через ADR 0008 polymorphic shape — already covered by step 3 middleware. |
| 10 | REVIEW § 4 Known partials | `idempotency_keys` schema `UNIQUE(key)` (not composite) — cross-user collision rare | open (production tracking) | **no — defer** | Не относится к Shareable Digest scope. Tracking-only до появления non-trivial collision evidence. |
| 11 | [BUG-019](BUG_LOG.md) | LLM JSON-parse retry uses identical prompt → deterministic triple-fail | open (Medium reliability/cost) | **no — defer** | Processing pipeline scope, не digest delivery. Bundle с next processing-pipeline touch. |
| 12 | [BUG-020](BUG_LOG.md) | No exp-backoff for Anthropic HTTP 5xx (520/529/503) | open (Low reliability) | **no — defer** | Same as #11. Processing/HTTP-client scope. |
| 13 | [BUG-021](BUG_LOG.md) | `get_cross_channel_stats` ignores `topic_links` table (returns keyword overlap only) | open (Medium analytics blindness) | **no — defer** | Analytics endpoint, not digest delivery. Per BUG_LOG: «Bundle with ENH-4 (workspace-overlap analytics)». Separate sprint. |
| 14 | [PARITY_DECISION_TRACKING.md § 3 O-1](PARITY_DECISION_TRACKING.md) | Atomic `move_workspace_source` — defer до signal'а | open (preemptive flag) | **no — defer** | F4-B follow-up, not digest scope. |

**Headcount:** 14 surveyed (7 from REVIEW § 4a + 4 from REVIEW § 4 Known partials + 3 standalone open bugs/observations).

**Fit for step 4:**

* `yes` — **1** (#8, ADR 0008 promotion = primary).
* `maybe / opportunistic` — **4** (#2 BUG-025, #3 BUG-026, #4 BUG-027, #9 idempotency broadening).
* `no / defer` — **8** (#1, #6, #7, #10, #11, #12, #13, #14).
* `closed` — **1** (#5 BUG-028 ✅).

---

## 4. Candidate scopes

### 4.1 Candidate A — Shareable Digest (ADR 0008 promotion + channel target)

**One-line summary:** Promote ADR 0008 Draft → Accepted (primary enum **`{chat, channel}`** only — webhook deferred to Wave 2A as additive migration per § 7 Q1/Q2); ship subscription target model across all four surfaces (chat + channel); enable A6 curator to publish scheduled digest to their TG-channel.

**Locked sizing (post-§ 7 resolution, 2026-05-23):** **~500–800 LOC, ~1.5–2 sessions** per Option B scope (confirmed in § 7 Q1).

**Source of the candidate:**

* [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) шаг 4 — explicit Wave 1 step 4 scope statement.
* [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 3.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) — sequencing + estimate baseline (~0.3 session, may combine with step 3 — was not combined).
* [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) (Draft) — entire ADR.
* [`PARITY_DECISION_TRACKING.md § 1 P-2`](PARITY_DECISION_TRACKING.md) — «сцепка с step 4: shareable digest расширяет F6 через `publish_to_channel=...`».
* [REVIEW § 4 Known partials](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) — explicit carry-forward.

**In-scope deliverables:**

1. **ADR 0008** promoted Draft → Accepted with locked target shape (см. § 7 Open Questions Q1 — Option B vs C).
2. **Storage migration** (Alembic):
   * `digest_subscriptions`: add `target_kind` (enum `'chat' | 'channel'`; ENUM type extension-friendly for future `'webhook'`) + nullable `channel_id` (VARCHAR — Telegram canonical channel id, e.g. `"@my_digest"` or `"-1001234567890"`). Existing `chat_id` retained (filled на `target_kind='chat'`, NULL на `target_kind='channel'`); deprecation cycle отдельный sprint.
   * `watch_interests` — symmetric, для consistency (даже если F11 channel publish не в scope step 4 — per ADR 0008 § «Что НЕ меняется этим ADR»: target model единый, но behaviour для F11 channel target можно отложить на Wave 2A).
   * Alembic migration runs cleanly on prod current state (no pre-migration dedupe needed — existing rows trivially `target_kind='chat'`).
3. **Domain models** ([`tg_parser/domain/models.py`](../../tg_parser/domain/models.py)):
   * Pydantic discriminated union `TargetChat | TargetChannel` с `kind: Literal[...]` tag (если Option B).
   * Либо additive optional fields (если Option C).
4. **Service layer** ([`tg_parser/services/digest_service.py`](../../tg_parser/services/digest_service.py)):
   * `subscribe_digest(target=..., ...)` пре-проверяет `target.kind`, dispatch'ит на `bot.send_message(chat_id)` или `bot.send_message(channel_id)`.
   * Existing `chat_id: int` argument остаётся как legacy shim → maps to `TargetChat(chat_id=...)` (per ADR 0008 § Recommendation step 3).
   * Channel publish: try-publish; on `ChatAdminRequired` raise typed error `error_class="ChannelAdminRequired"` + deactivate subscription per ADR 0008 § Open questions Q3 «best-effort + graceful» (per ADR 0006 principle 7 graceful degradation).
   * Per BUG-022 / ADR 0009 natural key `(owner_id, name)` unchanged; target field mutable (per ADR 0008 § BUG-022 idempotency interaction).
5. **HTTP API** ([`tg_parser/api/`](../../tg_parser/api/) — `POST /api/v1/digests` + new `PATCH /api/v1/digests/<id>` или extend POST upsert payload):
   * Request body accepts new `target: {kind, chat_id | channel_id}` discriminator (per Option B) или parallel fields (per Option C).
   * Backward-compat: legacy `chat_id: int` accepted with shim (per § 7 Q1 decision).
   * Response shape includes `target: {kind, ...}`.
   * Existing `Idempotency-Key` middleware reused (per ADR 0009; no broadening required → § 7 Q4 = «no» default).
6. **MCP / Bot / CLI surfaces** (parity):
   * MCP `subscribe_digest` tool: legacy `chat_id` arg + new `target: dict` arg (mutually exclusive).
   * Bot: extend `_exec_subscribe_digest` to accept either; prompt v1.5.0 hard rule «when user says "publish to my channel @X", use target={kind:channel, channel_id:'@X'}».
   * CLI: `tg-parser digest add --chat-id X` | `--channel-id @X` (mutually exclusive flags).
7. **JSON Schema** ([`docs/contracts/subscription_target.schema.json`](../contracts/) — new file):
   * Discriminator `kind` + variant schemas (per ADR 0008 § Test strategy + ADR 0006 principle 1 «persistent entity»).
   * Cross-link from existing `digest_subscriptions` shape (currently implicit).
   * If Option B chosen — webhook variant included as `"webhook"` enum value with explicit «not implemented in Wave 1; reserved for Wave 2A» note.
8. **Tests:**
   * Service-layer: subscribe with `kind=chat` (regression — existing behaviour unchanged); `kind=channel` (new); legacy `chat_id` shim mapping; `ChannelAdminRequired` graceful + deactivation; idempotent upsert (same `(owner_id, name)` different `target.kind` → UPDATE with `changed_fields=["target_kind", "channel_id", "chat_id"]`).
   * Integration: full subscribe → cron tick → publish to channel; mocked aiogram `bot.send_message(channel_id, ...)`.
   * Migration: Alembic dry-run on testcontainers PG with seeded `digest_subscriptions` rows; assert `target_kind='chat'` for all existing rows, no row count change.
   * Contract: `tests/test_contracts_subscription_target.py` validating example JSON instances against new schema.
9. **Docs:**
   * USER_GUIDE «Digest Subscription» section extended.
   * MCP_AGENT_GUIDE с `subscribe_digest` target shape.
   * `docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` (mirror step 3 precedent — pre-deploy checklist, deploy, post-deploy smoke, 24h watch matrix).
   * CHANGELOG entry под `[Unreleased]` § «Wave 1 step 4 — Shareable Digest».
   * REVIEW marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` (mirror step 3 structure).

**Out-of-scope (explicit defer — locked 2026-05-23 per § 7):**

* **`kind=webhook` in primary enum** — webhook target deferred to Wave 2A per ADR 0008 § Recommendation (Accepted 2026-05-23). Step 4 ships `target_kind` enum **`('chat', 'channel')` only**. Wave 2A adds `webhook` via additive `ALTER TYPE … ADD VALUE 'webhook'` + new Pydantic `TargetWebhook` variant — fully non-breaking. HMAC signing, retry policy, payload schema → Wave 2A.
* **No PATCH target update endpoint** — target change workflow = `unsubscribe + resubscribe` (natural-key idempotency per ADR 0009 makes this safe). Per § 7 Q4.
* **No test-publish / publish-now endpoints** — no new POST endpoints in step 4 beyond what existing `POST /api/v1/digests` shape extension naturally requires. Per § 7 Q4.
* **Middleware broadening to non-subscribe endpoints** (`/api/v1/channels`, `/api/v1/workspaces`, dispatch endpoints `/api/v1/process` / `/api/v1/export`) — out of scope. Service-layer natural-key idempotency already covers them. ADR 0007 dispatch middleware integration (`trigger_pipeline`, `/process`, `/export`) is a follow-up ADR 0007 concern, **not step 4 scope**. Wording: «not in this sprint», not «forbidden forever» — production signal → separate «middleware broadening» follow-up PR. Per § 7 Q4.
* **`prompts/bot.yaml` scope limit** — step 4 PR adds a single new `target_kind_semantics` section (≤15 lines) covering when LLM should pick `kind=chat` vs `kind=channel` and backward-compat fallback semantics. Bump current **v1.6.0 → v1.7.0**. **All other prompt sections untouched.** If a structural need surfaces during execution → flag as a new under-question, **do not silently expand prompt scope** (BUG-029-class risk). Per § 7 Q3-under (X1). _Note (2026-05-23): user-supplied lock referenced v1.4.0 → v1.5.0 → v1.6.0, but `prompts/bot.yaml` is already at v1.6.0 (last bumped in `41a925c` BUG-011 Session H); intent preserved (one bump per scope-focused sprint), numbers re-anchored to current baseline._
* **Bot UX cluster (BUG-025 / BUG-026 / BUG-027)** — out of scope; deferred to **step 4.1 sub-sprint** with locked scope (Layer A executor pre-validation + Layer B prompt + Layer C executor mapping, single `prompts/bot.yaml` v1.7.0 → v1.8.0 bump). Mirror step 3 → step 3.1 precedent. See § 8.1. Per § 7 Q3.
* **F11 watchlist channel target** — symmetric storage column may be added (consistency), but F11 service-layer dispatch on `kind=channel` deferred to Wave 2A (F11 cross-target use case is A4 push-to-Slack-equivalent, not A6 publish).
* **Public read-only API for embeddable widgets** — Wave 2B (Web Consumer).
* **Workspace `workspace_id` integration with subscription channel publish payload hyperlinks** — already landed in step 3 ENH-9 (the field is on subscriptions). Step 4 не touch'ает scoping logic.
* **`chat_id` field deprecation / removal** — legacy shim retained минимум для 1 minor version; removal в отдельном sprint v5.0.0.
* **Multi-channel publish per subscription** (one subscription → N channels) — not in ADR 0008; defer entirely.

**Pre-requisites:**

* ✅ Step 3 GREEN + step 3.1 GREEN + BUG-028 closed (все met).
* ✅ ADR 0009 (idempotency) Accepted — natural-key upsert pattern reused.
* ✅ **ADR 0008 promotion Draft → Accepted — done in this formalization session (2026-05-23).**
* ✅ `digest_subscriptions` schema currently `(owner_id, name)` unique — natural key stable.
* ⚠️ Telegram bot account must have admin rights в channels пользователя для publish — operational pre-flight, not code; documented in runbook (Phase 10 deliverable).

**Quality gates:**

* Pytest default: expect **2230+ / 311+ / 0** (baseline 2195 + ~35-50 new tests).
* Pytest `TEST_POSTGRES=1`: expect **2515+ / 9 / 0** (baseline 2499 + ~15-20 PG-specific tests for migration + integration).
* Ruff: clean.
* New Prometheus metric: `tg_digest_delivery_total{target_kind, outcome}` (counter, labels `kind=chat|channel`, `outcome=success|admin_required|other_failure`) — observability per ADR 0006 principle 6.
* New JSON Schema: 1 (`subscription_target.schema.json`).
* New migration: 1 (additive, no destructive ops).
* Per AGENT_PLAYBOOK quality lifecycle: any new contract → bundle с contract test; any new error class → entry in BUG_LOG если surfaces in production.

**Risk profile:** **Medium.**

* (a) ADR 0008 promotion has unresolved options (B vs C) — § 7 Q1 must answer first or sprint cannot start. Migration shape differs between options.
* (b) Channel publish operational risk: bot must be admin in user's channel; failure modes (kicked from channel, channel deleted, channel private without invite) need defensive code + graceful deactivation. Mitigation per ADR 0008 Q3 «best-effort + deactivate».
* (c) Migration is additive and reversible — low risk. Pre-existing rows trivially `target_kind='chat'`.
* (d) Backward-compat shim для legacy `chat_id` argument — well-precedented pattern (см. step 3 idempotency `created` field — additive). Low risk при дисциплинированном тесте `tests/test_subscribe_legacy_chat_id.py` (per ADR 0008 § Test strategy).

**Effort estimate:** **multi-session, single-PR-multi-commit** (mirror step 3 pattern: 4-5 atomic commits → 1 PR).

* Strategy doc estimate (~0.3 session) **stale** — was authored before ADR 0008 widened scope. Realistic estimate: **1.5–2 sessions** + 24h watch.
* LOC ballpark: **~500–800 LOC** (storage +100; service +150; HTTP +80; MCP/Bot/CLI +150; contract +50; tests +200-300).
* Если Option C minimal-viable instead of Option B — possibly **0.7–1 session**, ~300–500 LOC.

**Dependencies on open BUG-NN / ENH-NN:**

* **None blocking.** All blocking items closed (BUG-028, ADR 0009 Accepted, step 3 + 3.1 deployed).
* **Naturally bundles** (opportunistic, see § 4.2): BUG-025 + BUG-026 (если prompt v1.5.0 touch); BUG-027 (если ADR 0009 idempotency-message harmonization). All optional.

**Migration / deploy considerations:**

* 1 Alembic migration (additive — `ALTER TABLE digest_subscriptions ADD COLUMN target_kind ... ADD COLUMN channel_id ...`). Reversible (downgrade DROPs).
* Docker compose: **no env changes** (BUG-028 hotfix уже зашит `PROMPTS_DIR`).
* Telegram bot side: prod bot account already has Telethon credentials + aiogram session; no infra change required for bot.
* Pre-migration: `digest_subscriptions` row count check (assert all existing rows can map to `target_kind='chat'` без потерь — trivial).
* New runbook required: `WAVE1_STEP4_DEPLOY_AND_WATCH.md`.

**Definition of «step 4 DONE»** (mirror REVIEW step 3 § 6 closure criteria):

1. PR merged to `main`; 4–5 atomic commits per sprint prompt packaging.
2. Acceptance signals:
   * Pytest default ≥ 2230 / 311+ / 0.
   * Pytest `TEST_POSTGRES=1` ≥ 2515 / 9 / 0.
   * Ruff clean.
   * 0 regressions on `test_api_digests`, `test_subscribe_idempotency`, `test_f6_*`, новый `test_subscribe_legacy_chat_id`, новый `test_subscribe_digest_channel_target`.
3. Migration applied на prod cleanly; pre-migration row count = post-migration row count; spot-check 3 random `digest_subscriptions` rows → `target_kind='chat'`.
4. ADR 0008 status flipped Draft → Accepted with history row 2026-05-XX.
5. Deploy + 24h watch:
   * `up{service=api|bot|mcp}` = 1 (97/97 samples).
   * `tg_digest_delivery_total{target_kind="channel", outcome="success"}` ≥ 1 (smoke test: subscribe to channel target, force cron tick, verify message lands in test channel + Prometheus counter increments).
   * `tg_digest_delivery_total{outcome="admin_required"}` = 0 (no operational misconfiguration).
   * 0 × 5xx on `/api/v1/digests` over watch window.
   * Existing `digest_94483db9` (prod endocrinology, `target_kind='chat'`) — daily 09:00 MSK cron tick continues to PASS (regression guard against step 3 BUG-028 closure).
6. REVIEW marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` published; CHANGELOG entry под `[Unreleased]`.
7. Verdict **GREEN** documented; ADR 0008 marked Accepted in `docs/adr/`.

---

### 4.2 Candidate B — Bot UX Bundle (BUG-025 + BUG-026 + BUG-027)

**One-line summary:** Close 3 bot UX bugs surfaced by step 3 24h watch (BUG-025 UUID validation, BUG-026 standalone-UUID continuation, BUG-027 ambiguous «уже неактивен» wording) — single prompt v1.5.0 + executor pre-validation + service-layer typed return harmonization.

**Source of the candidate:**

* [REVIEW § 4a #2, #3, #4](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md).
* [BUG_LOG.md § BUG-025, § BUG-026, § BUG-027](BUG_LOG.md).
* [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6 Observations](WATCH_24H_BOT_ACTIONS_2026-05-22.md) (primary evidence).
* Lessons learned [REVIEW § 6 #2](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md): «Bot UX cleanups expose write-tool input validation gaps that read-tool tests never reach» → закрытие этого cluster — direct response to Lessons #2.

**In-scope deliverables:**

1. **BUG-025 Layer A + B** (per BUG_LOG):
   * Executor pre-validation in `_exec_unsubscribe_watchlist` and 5 sibling executors (`_exec_unsubscribe_digest`, `_exec_get_watchlist_matches`, MCP-side equivalents): `try: uuid.UUID(...) except ValueError: return {"error_class": "InvalidUUID", "error": "...use list_watchlists to find the ID by name."}`. ~30 LOC.
   * `prompts/bot.yaml` v1.5.0 hard rule «UUID-typed arguments»: «To delete / inspect a watchlist or digest by name, ALWAYS call `list_watchlists` / `list_digests` first». ~5 lines.
   * Parametrized tests ≥ 5 invalid forms per executor × 6 executors = ~30 tests.
2. **BUG-026 Option A** (prompt-only, structural Option B deferred):
   * `prompts/bot.yaml` v1.5.0 hard rule for standalone-UUID continuation: «If your previous turn emitted a UUID candidate and the next user message is just that UUID, treat as confirmation of the previously-suggested action.» ~10 LOC prompt.
   * Integration test `test_bug026_standalone_uuid_after_suggestion_resumes_intent`. ~3-5 tests.
3. **BUG-027 Layer A + B + C** (per BUG_LOG):
   * Service-layer typed return `(False, "already_inactive")` in `watchlist_service.delete_interest_for_user` + symmetric `digest_service.delete_subscription_for_user`. ~20 LOC.
   * Bot executor mapping: `error="already_inactive"` → `{"already_inactive": True, "message": "Watchlist is already inactive (soft-deleted previously)..."}`. ~5 LOC.
   * `prompts/bot.yaml` v1.5.0 soft-delete semantics section: «If unsubscribe returns `already_inactive=True`, tell the user the watchlist was already removed». ~3 lines.
   * ~3 tests (parametrized service-layer + bot mapping + prompt sanity).

**Out-of-scope:**

* BUG-026 Option B (FSM `SuggestionFlow` structural extension) — defer unless Option A smoke fails post-deploy.
* Adding `unsubscribe_watchlist` / `unsubscribe_digest` к `_WRITE_TOOLS_REQUIRING_CONFIRM` (TD-bot-confirm-coverage-completeness ~400 LOC, ~25 tests) — explicit out-of-scope per Session G locked decision A.
* MCP-side `unsubscribe_watchlist` / `unsubscribe_digest` / `get_watchlist_matches` symmetric coverage — included as part of BUG-025 Layer A (executors), but only basic validation; full audit deferred.

**Pre-requisites:** None. All BUG-022 / ADR 0009 / step 3 already deployed.

**Quality gates:**

* Pytest default: expect **2230+ / 311+ / 0** (baseline 2195 + ~35-40 new tests across 3 bugs).
* Pytest `TEST_POSTGRES=1`: expect **2500+ / 9 / 0** (baseline 2499; minimal PG-specific additions).
* Ruff: clean.
* `prompts/bot.yaml` version bump 1.4.0 → 1.5.0.
* No new contracts, no migrations.

**Risk profile:** **Low.**

* Smallest possible blast radius — bot executor pre-validation + prompt update + service-layer typed return.
* Direct user-evidence cluster (3 bugs, all in same 25-minute dialog).
* Each fix layer is well-precedented (Session F suggestion-emit pattern, Session G confirm-guard pattern).
* Risk: prompt v1.5.0 regression in BUG-009 hard-rule semantics → mitigation: existing `confirm_flow_mismatch_total` Prometheus counter remains zero post-deploy.

**Effort estimate:** **single session, single PR, ~3 atomic commits**, ~150–250 LOC + 35-40 tests.

**Dependencies on open BUG-NN / ENH-NN:**

* **None blocking.**
* Bundles naturally as carried в HANDOFF / BUG_LOG: «bundle with next bot-side touch» (per BUG-025 § Planned fix; BUG-026 § Planned fix; BUG-027 § Planned fix).

**Migration / deploy considerations:**

* No migrations.
* No compose changes.
* Bot container restart only (no image rebuild required if prompts bind-mounted — see Session F deploy precedent).
* New runbook NOT required (mirror Session F deploy pattern; bundle with `WAVE1_STEP3_DEPLOY_AND_WATCH.md` runbook update or skip).

**Definition of «B DONE»:**

1. PR merged to `main`; 3 atomic commits (1 per BUG).
2. Pytest baselines hit.
3. Production smoke (mirror BUG-025 § Symptoms trace reproduction):
   * Send «Удали watchlist _smoke_xxx» → bot responds с typed `InvalidUUID` error mentioning `list_watchlists` (NOT raw asyncpg traceback).
   * Send `list_watchlists` → bot emits UUID candidates; reply standalone UUID → bot executes `unsubscribe_watchlist(interest_id=<UUID>)`.
   * Delete already-inactive watchlist → bot responds «Watchlist is already inactive (soft-deleted previously)» (NOT «Возможно, он уже неактивен»).
4. 24h watch GREEN; existing `confirm_flow_mismatch_total` = 0.
5. BUG-025/026/027 entries flipped `open` → `resolved` in BUG_LOG.

---

### 4.3 Candidate C — Combined (A + B)

**One-line summary:** Ship Shareable Digest (A) + Bot UX Bundle (B) в одном sprint, эксплуатируя co-location of `prompts/bot.yaml` v1.5.0 touch (A потенциально касается prompt для subscribe-tool target semantics; B already требует v1.5.0).

**Source:** Composition. Not a separately documented direction в strategy / planning docs.

**In-scope deliverables:** Union of § 4.1 + § 4.2.

**Pros:**

* `prompts/bot.yaml` v1.5.0 touched once (A may need «when user says publish to my channel @X, use target={kind:channel, channel_id:'@X'}» rule; B needs UUID-arg + standalone-UUID-continuation rules) — consolidating saves one deploy cycle.
* `_exec_subscribe_digest` / `_exec_subscribe_watchlist` executor work in A overlaps with `_exec_unsubscribe_*` UUID-validation work в B (same module `tg_parser/bot/tools.py`) — single touch for cross-cutting hygiene.
* Pytest counter movement consolidated → simpler delta interpretation.
* Single 24h watch window covers both fixes.

**Cons:**

* Sprint scope balloons → multi-PR risk, or single-PR with 7-8 commits (above step 3 precedent of 4).
* Adjudication «A regression vs B regression» harder если что-то падает на watch (cross-contamination diagnostic).
* B has its own user-evidence trail (2026-05-22 dialog) — closing it separately is cleaner audit-wise.
* Strategy doc explicitly says step 4 = «light extension F6» — adding bot UX cluster contradicts the «light» characterization, weakens the audience-driven discipline.

**Pre-requisites + quality gates + risk:** Aggregate of A + B; risk bumps to **Medium-High** due to scope creep.

**Effort estimate:** **2-3 sessions, single-PR-multi-commit** (~6-8 commits) or **2 separate PRs sequenced step-4 then step-4.1**. LOC ~700–1050.

**Definition of «C DONE»:** Union of A DONE + B DONE.

---

## 5. Comparison matrix

| Axis | Candidate A (Shareable Digest) | Candidate B (Bot UX Bundle) | Candidate C (A + B combined) |
|---|---|---|---|
| **Source authority** | ✅ Strategy § 5.1 шаг 4 + Planning § 3.2 + ADR 0008 Draft (explicit Wave 1 step 4 statement) | ⚠️ REVIEW § 4a #2–#4 + BUG_LOG (carry-forward, no Wave 1 step assignment) | ⚖️ Mixed (A authoritative + B opportunistic) |
| **Audience driver** | A6 Domain Curator (publish-to-channel enabler без Web) — direct strategy alignment | A1 (owner) + A5 (journalist) + A6 — UX polish across audiences | All 4 solo segments |
| **Closes Wave 1 step 4 per strategy?** | ✅ Yes (entirely) | ❌ No (parallel/side-quest) | ✅ Yes (A part) + bonus |
| **ADR transitions** | ADR 0008 Draft → Accepted (required) | None | ADR 0008 Draft → Accepted |
| **Migrations** | 1 (additive, low risk) | 0 | 1 |
| **New contracts (JSON Schema)** | 1 (`subscription_target.schema.json`) | 0 | 1 |
| **LOC ballpark** | ~500–800 (Option B) / ~300–500 (Option C) | ~150–250 | ~700–1050 |
| **Test delta** | ~35–50 new tests | ~35–40 new tests | ~70–90 new tests |
| **Effort** | 1.5–2 sessions (multi-commit PR) | 1 session (single PR, ~3 commits) | 2–3 sessions (multi-PR or 6–8-commit PR) |
| **Risk** | Medium (Q1 option choice; channel publish operational pre-flight) | Low (well-precedented patterns) | Medium-High (scope creep; cross-contamination) |
| **Blocking dependencies** | None (BUG-028 closed; ADR 0009 Accepted) | None | None |
| **Open questions to resolve before start** | 4 (§ 7 Q1–Q4) | 0 | 4 + 1 (combination scope discipline) |
| **Time-sensitive operational angle** | No (no cron tick risk; daily digest on `target_kind='chat'` continues working under additive migration) | No (3 bugs are persistent UX gaps; no cron tick involvement) | No |
| **Mirror Wave 1 step pattern** | ✅ Step 3 mirror (single-PR-multi-commit, migration + service + HTTP + tests + docs) | ⚠️ Session F / Session G mirror (bug-cluster sprint, not Wave-step sprint) | ❌ Hybrid (no clean precedent) |
| **Audience-driven discipline** | ✅ Strong (single-purpose, A6) | ⚠️ Bot UX cluster — diffuse audience | ⚠️ Mixed |
| **«Done» definition crispness** | ✅ High (REVIEW § 6 mirror; channel publish smoke testable) | ✅ High (3 direct symptom reproductions) | ⚖️ Moderate |
| **Rollback complexity** | Medium (Alembic downgrade + revert) | Low (revert PR; prompt-only hotfix possible) | High (entangled) |

---

## 6. Recommendation

### 6.1 Primary recommendation: **Candidate A (Shareable Digest)** with **Option B locked** (per § 7 Q1 resolution 2026-05-23). Candidate B (Bot UX Bundle) deferred to **step 4.1 sub-sprint** per § 7 Q3 resolution.

> **Status update (2026-05-23 later):** All four blocking questions § 7 Q1–Q4 + the Q3 under-question (X1) are **resolved** (→ § 7). This planning artifact is formalized and ready for sprint-prompt drafting (see § 8.1).

**Why:**

1. **Authority alignment.** Strategy § 5.1 + Planning § 3.2 + HANDOFF «Next session prompt suggestion» + ADR 0008 Draft all converge на «Wave 1 step 4 = Shareable Digest, ADR 0008 Accepted». Honoring this is the single highest-leverage move for closing Wave 1 audience-driven roadmap.
2. **Audience-driven discipline.** Per [`PRODUCT_STRATEGY § 5.1 Wave 1 шаг 4`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md): «A6-enabler **без Web**. Минимальный exit point для curators.» Step 4 — единственный Wave 1 step, который активирует A6 (Domain Curator) — без него Wave 1 closure теряет audience symmetry. A6 is the Wave 2B validation gate; without step 4 the «do users actually subscribe to curator's TG channel?» signal cannot accumulate.
3. **Architectural cleanliness.** ADR 0008 (Draft) already locks the direction (Option B polymorphic recommended); promoting it Draft → Accepted before P-3 (Topics/Channels read API enrichment, Wave 2A candidate) или any future subscription extension lands prevents calcifying chat-only contract on more endpoints.
4. **Step 3 leaves it half-done.** Step 3 § 4 Known partials explicitly defers ADR 0008 to step 4. Idempotency-Key middleware (step 3 commit 4/4) was designed to be reusable for «any future POST that involves shareable-link generation» (ADR 0009 generalisation note) — step 4 IS that future POST.
5. **Risk vs value.** Medium risk, high value (closes Wave 1 audience-driven scope completely). No urgency (no cron tick concern; BUG-028 closed). Scope can be narrowed (Option C minimal-viable) если planning Q1 trends to «light extension» interpretation.
6. **Bot UX Bundle (B) can land subsequently** as a sub-sprint «step 4.1 bot hygiene tail» (mirror step 3.1 sub-sprint pattern) — losing nothing.

### 6.2 Recommended sequencing

```
PLAN_WAVE1_STEP4_2026-05-23.md (this artifact)
   ↓ user answers § 7 Q1–Q4
START_PROMPT_SPRINT_WAVE1_STEP4_<date>.md (next planning sub-session)
   ↓ ~0.3 session
Wave 1 step 4 sprint execution (1.5–2 sessions per Option B; 0.7–1 per Option C)
   → single PR with ~4-5 atomic commits per Wave 1 packaging convention
   ↓ deploy + 24h watch
REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md
   ↓
[optional] Wave 1 step 4.1 — Bot UX Bundle (Candidate B carved out separately)
   ↓ ~1 session
[optional] Wave 1 closure marker (ROADMAP_KARPATHY_LIKE_LIVING_KB.md update + decision-point trigger eval)
```

### 6.3 Alternatives and when they'd be preferred

* **Candidate B alone, defer A.** Preferred if (a) user wants to reset Wave 1 scope to pure A1/A5 (drop A6 enabler from Wave 1, push step 4 → Wave 2B/2C), or (b) bot UX bugs surface escalation evidence (additional sightings of BUG-025/026/027 in production beyond the 25-minute 2026-05-22 cluster), or (c) ADR 0008 option choice deadlocks (Q1 indecision → bypass with B while thinking).
* **Candidate C combined.** Preferred only if user explicitly opts into bundle scope and accepts the multi-PR / 6-8 commit packaging risk + harder regression adjudication. Not recommended absent clear ask.
* **No step 4 at all (skip to Wave 1 closure marker + Decision Point eval).** Preferred only if user reclassifies Wave 1 as «step 1+2+3 sufficient; A6 deferred to Wave 2B». Would require strategy doc update.

---

## 7. Open questions — RESOLVED 2026-05-23

These four questions blocked sprint-prompt drafting. **All resolved in formalization sub-session 2026-05-23 (later)**; planning artifact now committed.

### Q1. ADR 0008 — Option B (polymorphic discriminator) vs Option C (multiple optional target fields)?

* **Option B** (per ADR 0008 § Recommendation preliminary): `target: {kind: chat|channel, chat_id|channel_id}` discriminated union. Pydantic + Alembic enum + service-layer switch. ~500–800 LOC, ~1.5–2 sessions. Future-proof for `kind=webhook` Wave 2A addition (additive enum + new variant).
* **Option C** (per ADR 0008 § Option C): parallel optional `chat_id: int | None`, `channel_id: str | None`. Validation «exactly one of» at each layer. ~300–500 LOC, ~0.7–1 session. Closer to strategy doc «light extension» estimate but introduces validation-bloat anti-pattern (ADR 0008 explicitly rejects this — but user may have reasons to prefer minimal scope here).

**Recommended:** Option B per ADR preliminary recommendation + alignment с workspace_id (single explicit field) + add_channel patterns (discriminated semantics). User decision needed because the LOC / session-count delta is significant.

**Decision (2026-05-23):** **Option B (polymorphic discriminator).** Discriminated union `target: {kind: chat | channel, chat_id | channel_id}` (per ADR 0008 § Recommendation, now Accepted). Rationale: alignment with single-explicit-field conventions (workspace_id, add_channel) + ADR 0006 principle 1 (persistent entity for target shape) + future-proof for Wave 2A webhook extension (additive enum, non-breaking). LOC/session estimate locked: **~500–800 LOC, ~1.5–2 sessions**.

### Q2. Webhook target (`kind=webhook`) — include в step 4 or defer to Wave 2A?

* **Include:** matches ADR 0008 Option B fully; A4 audience benefit; HMAC + retry policy + payload schema + outbound-HTTP failure modes all in scope. Sprint balloons +~200 LOC + ~10 tests + 1 new schema. Pushes step 4 to ~2–2.5 sessions.
* **Defer to Wave 2A:** matches strategy § 5.4 (A4 = Wave 2A territory); ADR 0008 enum reserves `'webhook'` value but service-layer raises `NotImplementedError`. Step 4 stays focused on A6.

**Recommended:** Defer. Strategy doc puts A4-targeted webhook surface in Wave 2A explicitly. Including it in step 4 would dilute A6 audience focus + violate «one step = one audience push» Wave 1 discipline.

**Decision (2026-05-23):** **Defer to Wave 2A; NO primary-enum reservation in step 4.** Step 4 ships `target_kind` enum **`('chat', 'channel')` only**. Wave 2A adds webhook via additive Postgres `ALTER TYPE target_kind ADD VALUE 'webhook'` + new Pydantic `TargetWebhook` variant — fully non-breaking. ADR 0008 Accepted text explicitly documents this migration path so a future developer doesn't re-open the question. Strategy § 5.4 Wave 2A list amended with explicit «webhook target (per ADR 0008)» line binding webhook to Wave 2A roadmap. Rationale: avoids reserving an enum value the service layer must immediately reject, keeps step 4 audience focus narrow on A6, no architectural risk because additive enum extension is bit-for-bit non-breaking.

### Q3. Bundle Candidate B (Bot UX cluster BUG-025/026/027) into step 4 sprint?

* **Bundle (Candidate C):** saves one prompt-touch + one deploy cycle; +~150 LOC + 35 tests; risk of scope creep + cross-contamination on watch.
* **Defer to step 4.1 sub-sprint:** clean separation; mirrors step 3 → step 3.1 precedent; closes bugs independently auditable; loses one prompt cycle.

**Recommended:** Defer to step 4.1. Mirror step 3.1 sub-sprint pattern (small, focused, sequential). Step 4 stays «single-purpose A6 push» per audience-driven discipline.

**Decision (2026-05-23):** **Defer to step 4.1 sub-sprint with scope-lock.** Mirror step 3 → step 3.1 precedent. Step 4.1 scope-locked to exactly: BUG-025 (Layer A executor pre-validation + Layer B prompt rule), BUG-026 (Option A prompt-only), BUG-027 (Layer A service-layer typed return + Layer B executor mapping + Layer C prompt update). All three Bot UX fixes share **one** `prompts/bot.yaml` v1.7.0 → v1.8.0 bump in step 4.1 (rebased from user-supplied lock v1.5.0 → v1.6.0 — see § 4.1 Out-of-scope note for rationale). **`START_PROMPT_SPRINT_WAVE1_STEP4_1_*.md` drafting is a SEPARATE planning session** after step 4 closes — NOT formalized in this session. See § 8.1 scope-lock subsection.

### Q3-under (X1) — Step 4 prompt touch for `target_kind_semantics`

Emergent under-question from Q3 resolution: «If step 4 defers all Bot UX prompt rules to step 4.1, should step 4 itself touch `prompts/bot.yaml` at all?»

* **Option X1 — Bend Q3 «no prompt touch in step 4» consistency:** Step 4 PR does touch `prompts/bot.yaml`, but ONLY a new dedicated `target_kind_semantics` section (≤15 lines) covering when LLM should pick `kind=chat` vs `kind=channel` and backward-compat fallback semantics. Step 4 prompt bump: **v1.6.0 → v1.7.0** (target_kind_semantics section only — rebased from user-supplied v1.4.0 → v1.5.0 because current `prompts/bot.yaml` already at v1.6.0 per `41a925c`). Step 4.1 prompt bump: **v1.7.0 → v1.8.0** (BUG-025/026/027 HARD RULES — rebased from user-supplied v1.5.0 → v1.6.0).
* **Option X2 — No prompt touch in step 4 at all:** target semantics rely on tool descriptor JSON schema + service-layer defaults. Risk: LLM has no narrative guidance for «channel vs chat» disambiguation; BUG-029-class «silent mis-route» risk on first prod usage.

**Decision (2026-05-23):** **Option X1 (step 4 prompt touch limited to `target_kind_semantics` ≤15 lines).** Step 4 PR must NOT touch any other section of `prompts/bot.yaml`. If a structural need for additional prompt changes surfaces during step 4 implementation — flag as new under-question, **do NOT silently expand prompt scope**. Rationale: X2 (no prompt touch) had high BUG-029-class risk (silent mis-routing of channel publish to chat); X1 keeps each prompt bump thematically focused (step 4 = target semantics; step 4.1 = unsubscribe UX HARD RULES). Each bump = single coherent commit story, easy rollback if regression emerges.

### Q4. Idempotency-Key middleware broadening (ADR 0009 Q-OPEN-7) — include в step 4?

* If step 4 adds **new POST endpoint** (e.g. `POST /api/v1/digests/<id>/target` for target update) — middleware auto-applies if wired (~0 LOC).
* If step 4 only **extends existing POST** (`POST /api/v1/digests` with new `target` field) — middleware already wired.
* No new POST endpoints needed if Option C parallel-fields chosen.

**Recommended:** Default «no broadening beyond what step 4's API shape naturally requires». Q-OPEN-7 broader scope (`/api/v1/process`, `/api/v1/export`) defer per REVIEW § 4 Known partials — «Future PR if production usage shows broader transient-retry pain».

**Decision (2026-05-23):** **No broadening, no new POST/PATCH endpoints.**

* No new POST endpoints in step 4 (no `test-publish`, no `publish-now`).
* No PATCH endpoints in step 4 — target change workflow = `unsubscribe + resubscribe` (natural-key idempotency per ADR 0009 makes this safe).
* No middleware broadening to non-subscribe endpoints (`/api/v1/channels`, `/api/v1/workspaces`, etc.) — service-layer natural-key idempotency already covers them.
* ADR 0007 dispatch middleware integration (`trigger_pipeline`, `/process`, `/export`) is a **follow-up ADR 0007 concern**, NOT step 4 scope.
* Wording in artifacts is «**not in this sprint**», not «forbidden forever» — production signal → separate «middleware broadening» follow-up PR, not bound to step 4.

---

## 8. Next step

### 8.1 Formalized 2026-05-23

**Status (post-formalization sub-session, 2026-05-23 later):** Q1–Q4 + Q3-under (X1) all resolved (→ § 7). Planning artifact committed.

**Outputs of this formalization session:**

1. ✅ [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — header flipped «Draft» → «Accepted (2026-05-23)». § Recommendation updated to lock Option B with primary enum **`{chat, channel}` only** + Wave 2A webhook migration path. § Open questions resolved (OQ#3/#4/#6/#7) or marked N/A for step 4 (OQ#1/#2/#5 → Wave 2A). § История row appended.
2. ✅ [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.4 Wave 2A](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) — added explicit «webhook target (per ADR 0008)» line in «2A: A4-focused (AI integrators)» list, binding webhook delivery to Wave 2A roadmap. § 12 История row appended.
3. ✅ This PLAN file — § 4.1 anti-scope locked, § 6 status note added, § 7 renamed «RESOLVED 2026-05-23» with Decision lines + Q3-under (X1) sub-section, § 8.1 rewritten as «Formalized», § История row appended.
4. ✅ [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md) drafted (mirror step 3 start-prompt structure) — § 0 context + Q1–Q4 + X1 recap, § 1 scope (in/out/pre-req), § 2 phases (10 phases storage → service → HTTP → MCP → Bot → CLI → channel-publish → contracts → tests → docs), § 3 pre-flight gate, § 4 acceptance criteria, § 5 anti-scope HARD list (a)–(g), § 6 quality gates, § 7 deploy + 24h watch plan, workflow appendix.
5. ✅ [`CHECKLIST_WAVE1_STEP4_2026-05-23.md`](CHECKLIST_WAVE1_STEP4_2026-05-23.md) drafted (mirror [`CHECKLIST_WAVE1_STEP3_1_2026-05-22.md`](CHECKLIST_WAVE1_STEP3_1_2026-05-22.md) shape).

**Commits (placeholder SHAs filled post-push):**

* **Commit 1** `docs(planning): Wave 1 step 4 planning artifact + ADR 0008 Accepted + strategy webhook→Wave 2A` — touches PLAN + ADR 0008 + strategy.
* **Commit 2** `docs(planning): start-prompt for Wave 1 step 4 sprint (+ checklist)` — touches START_PROMPT + CHECKLIST.

#### Next sprint after step 4 = step 4.1 sub-sprint (LOCKED 2026-05-23)

**Scope-locked to:** BUG-025 (Layer A executor pre-validation + Layer B prompt rule) + BUG-026 (Option A prompt-only) + BUG-027 (Layer A service-layer typed return + Layer B executor mapping + Layer C prompt update); one `prompts/bot.yaml` v1.7.0 → v1.8.0 bump (rebased from user-supplied v1.5.0 → v1.6.0 — current baseline is v1.6.0 per `41a925c`); **NO other items merged in** to prevent junk-drawer creep — specifically:

* No Q4 broadening (no middleware extension to non-subscribe endpoints).
* No BUG-019 / BUG-020 / BUG-021 (processing-pipeline + analytics bundles — separate sprints).
* No ADR 0007 follow-ups (dispatch middleware integration — separate ADR 0007 concern).

**Step 4.1 start-prompt drafting is a SEPARATE planning session after step 4 closes** — NOT formalized here.

### 8.2 If user answers § 7 with changes / new constraints

Re-plan: update this artifact in-place (revise § 4 candidate scopes + § 6 recommendation), re-commit, request next iteration.

### 8.3 What the ORIGINAL planning sub-session does NOT do (anti-scope confirmation — preserved as historical record)

> _Snapshot of the original 2026-05-23 planning session's anti-scope discipline. The formalization sub-session (later that day, see § 8.1) expanded scope to include sprint-prompt drafting + ADR 0008 promotion + strategy § 5.4 amendment + companion checklist — but only after Q1–Q4 + X1 were resolved._

* Does NOT draft sprint prompt. (Superseded by § 8.1 formalization once Q1–Q4 + X1 resolved.)
* Does NOT touch code / tests / configs / contracts / ADRs / runbooks. (Formalization later touched ADR 0008 promotion Draft → Accepted + strategy § 5.4 amendment — both pure docs changes, no code.)
* Does NOT modify any other `docs/notes/*` file.
* Does NOT modify `docs/methodology/**` (does not exist in this workspace per AGENTS.md).
* Does NOT modify `pyproject.toml` / `requirements*.txt` / `uv.lock`.
* Does NOT create new branches; does NOT force-push.

---

## Appendix — Cross-link inventory used in this artifact

| Path | Why |
|---|---|
| [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) | Step 3 closure (primary § 4a Open Items input) |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | Wave 1 sequence + audience filter + § 5.1 step 4 statement |
| [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) | Operational packaging conventions for Wave 1 steps |
| [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) | Step 4 primary input (Draft → Accepted gate) |
| [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) | Companion ADR; natural keys `(owner_id, name)` |
| [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) | Step 3.1 HTTP-proxy template, not blocking step 4 |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | Persistent-entity + graceful-degradation principles |
| [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) | P-2 step 4 «sцепка» + observations |
| [`BUG_LOG.md`](BUG_LOG.md) | Open bug inventory (BUG-019/020/021/025/026/027); BUG-028 closure confirmation |
| [`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md`](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md) | Pointer to this planning session |
| [`WATCH_24H_BOT_ACTIONS_2026-05-22.md`](WATCH_24H_BOT_ACTIONS_2026-05-22.md) | Primary evidence for BUG-025/026/027 (Candidate B input) |
| [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) | Watch closure verdict (step 3 GREEN) |
| [`docs/contracts/workspace.schema.json`](../contracts/workspace.schema.json) | Contract surface reference (new `subscription_target.schema.json` will mirror style) |
| [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md) | Template for upcoming `WAVE1_STEP4_DEPLOY_AND_WATCH.md` |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | Quality lifecycle conventions (pytest baselines, label taxonomy, INBOX-vs-incident triage) |
| [`docs/notes/agents-roles.md`](agents-roles.md) | Agent-role assignment for ADR / implementation / tests |
| `git log --oneline -50 main` | Delivery cadence + commit packaging precedent |

---

## История

| Date | Change |
|---|---|
| 2026-05-23 | First draft, planning sub-session post BUG-028 closure (commit `668946e`). Author: Wave 1 step 4 planning agent. Artifact left **uncommitted** pending user resolution of § 7 Q1–Q4. |
| 2026-05-23 (later) | Q1=Option B, Q2=defer webhook (no enum reservation), Q3=defer Bot UX to step 4.1 with scope-lock, Q3-under=X1 (step 4 prompt touch limited to `target_kind_semantics` ≤15 lines), Q4=no broadening + no new POST/PATCH. Formalized via PLAN edits + ADR 0008 promotion Draft→Accepted + strategy § 5.4 Wave 2A webhook line + `START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md` drafted + `CHECKLIST_WAVE1_STEP4_2026-05-23.md` drafted. **Version-numbering correction:** user-supplied lock referenced `prompts/bot.yaml` v1.4.0 → v1.5.0 (step 4) → v1.6.0 (step 4.1), but current `prompts/bot.yaml` is at **v1.6.0** (last bumped in `41a925c` BUG-011 Session H, 2026-04-30 era). Re-anchored monotonically to **v1.6.0 → v1.7.0 (step 4) → v1.8.0 (step 4.1)** preserving the «one bump per scope-focused sprint» intent. Note repeated in § 4.1 Out-of-scope + § 7 Q3-under (X1) + § 8.1 scope-lock. |
