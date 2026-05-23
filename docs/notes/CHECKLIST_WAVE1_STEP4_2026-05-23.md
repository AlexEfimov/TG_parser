# Чеклист — Wave 1 step 4 (Shareable Digest, ADR 0008 Accepted)

> Зеркало DoD из [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md).
> Отмечать по ходу execution-сессии. Single PR + ~4–5 атомарных коммитов.
> **Authoritative scope source:** [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md) § 4.1 + § 7 + § 8.1.

**Статус планирования:** `668946e` baseline + 2026-05-23 formalization session commits (PLAN + ADR 0008 Accepted + strategy § 5.4 + START_PROMPT + this checklist).

---

## 0. Pre-flight (блокер старта кода)

- [ ] `git fetch && git checkout main && git pull --ff-only` → HEAD ≥ formalization-session commit SHA
- [ ] `.venv/bin/pytest -q --tb=line` → **~2201 passed, ~313 skipped, 0 failed** (default mode baseline)
- [ ] `TEST_POSTGRES=1 .venv/bin/pytest -q --tb=line` → **~2505 passed, ~9 skipped, 0 failed**
- [ ] `ruff format --check . && ruff check .` — clean
- [ ] Ветка: `feat/wave1-step4-shareable-digest-2026-05-XX` от `origin/main`
- [ ] **Не трогать:** `pyproject.toml`, `requirements*.txt`, `uv.lock`, `docs/methodology/**`
- [ ] ADR 0008 status = **Accepted** ✅ (formalization session, 2026-05-23)
- [ ] ADR 0009 idempotency middleware = wired ✅ (step 3 acceptance)
- [ ] BUG-028 closed ✅ (PR #92 / `26d03a5` / DONE-marker `668946e`)
- [ ] Working tree clean on `main`

---

## 1. Phase 1 — Storage migration (commit 1/5 candidate)

- [ ] Alembic migration: create Postgres ENUM type `target_kind` with values **`('chat', 'channel')`** (extension-friendly for additive `'webhook'` Wave 2A)
- [ ] Add `target_kind target_kind NOT NULL DEFAULT 'chat'` + nullable `channel_id VARCHAR` on `digest_subscriptions`
- [ ] Add `target_kind target_kind NOT NULL DEFAULT 'chat'` + nullable `channel_id VARCHAR` on `watch_interests`
- [ ] Backfill: `UPDATE … SET target_kind = 'chat'` (existing `chat_id` already populated; no-op effectively)
- [ ] Downgrade DROPs both columns + type
- [ ] Migration smoke test: testcontainer Postgres upgrade + downgrade + row count invariant assertion (mirror ADR 0009 precedent)
- [ ] `pytest` + `ruff` green после Phase 1

---

## 2. Phase 2 — Domain models (commit 1/5 candidate)

- [ ] `tg_parser/domain/models.py`: Pydantic discriminated union `TargetChat | TargetChannel` with `kind: Literal['chat' | 'channel']`
- [ ] Service-layer dispatch in `digest_service.py` + `watchlist_service.py` on `target.kind`
- [ ] Backward-compat shim: `chat_id: int` auto-wraps to `TargetChat(chat_id=...)`
- [ ] Tests: discriminator round-trip + backward-compat shim + invalid kind rejection
- [ ] `pytest` + `ruff` green после Phase 2

---

## 3. Phase 3 — HTTP API (commit 2/5 candidate)

- [ ] `tg_parser/api/schemas.py`: extend `DigestCreateRequest` + `WatchlistCreateRequest` with optional `target: TargetChat | TargetChannel | None`
- [ ] Backward-compat: legacy `chat_id` arg without `target` → auto-construct `TargetChat`
- [ ] Conflict path: both `chat_id` and `target` set → 400 «provide one of chat_id (legacy) or target (new)»
- [ ] Response shape includes `target: {kind, ...}`
- [ ] `Idempotency-Key` middleware reused unchanged (step 3 already wired)
- [ ] **No new POST or PATCH endpoints**
- [ ] Tests: target=chat path + target=channel path + legacy chat_id path + conflict 400 + idempotency replay
- [ ] `pytest` + `ruff` green после Phase 3

---

## 4. Phase 4 — MCP surface (commit 2/5 candidate)

- [ ] `tg_parser/mcp_server.py` `subscribe_watchlist` + `subscribe_digest`: accept optional `target: dict` arg
- [ ] Mutually exclusive enforcement: typed error if both `chat_id` and `target` set
- [ ] Tests parametrized: kind=chat / kind=channel / legacy chat_id / both-set conflict

---

## 5. Phase 5 — Bot surface (commit 3/5 candidate)

- [ ] `tg_parser/bot/tools.py` `_exec_subscribe_digest` + `_exec_subscribe_watchlist`: accept `target` arg, dispatch on kind
- [ ] **`prompts/bot.yaml` v1.6.0 → v1.7.0**: add single new `target_kind_semantics` section (**≤15 lines**) — kind=chat vs kind=channel disambiguation + backward-compat fallback semantics
- [ ] Version metadata header updated (line 2 + line 8)
- [ ] **HARD GATE:** `git diff prompts/bot.yaml` shows ONLY the new section + version bump; **no other sections modified**
- [ ] If structural need surfaces to touch other sections → STOP, flag as new under-question, do **NOT** silently expand prompt scope (BUG-029-class risk)
- [ ] Tests: bot executor dispatch + prompt regression sanity
- [ ] `pytest` + `ruff` green после Phase 5

---

## 6. Phase 6 — CLI surface (commit 2/5 candidate)

- [ ] `tg_parser/cli/app.py` `tg-parser watchlist add` + `tg-parser digest add`: mutually-exclusive `--chat-id <int>` / `--channel-id <str>` flags
- [ ] Old `--chat-id`-only callers continue to work (kind inferred as `chat`)
- [ ] Tests parametrized: --chat-id only / --channel-id only / both-set conflict / neither-set conflict

---

## 7. Phase 7 — Channel-publish service layer (commit 4/5 candidate)

- [ ] `digest_service.py` `_publish_to_target(target, payload)`: dispatch on `target.kind`
  - [ ] `kind=chat` → existing `bot.send_message(target.chat_id, ...)` (zero behaviour change)
  - [ ] `kind=channel` → `bot.send_message(target.channel_id, ...)` with best-effort policy
- [ ] Permission-denied path: catch aiogram «bot not admin» / «chat not found» / «not enough rights» → soft-deactivate subscription (`is_active = False`) + typed log `channel_publish_permission_denied` + fallback notification to owner `chat_id` if available
- [ ] Prometheus metric `tg_digest_channel_publish_total{result=success|permission_denied|failed}` (mirror F11 metric pattern)
- [ ] Tests: success path (mocked aiogram) + permission-denied path + fallback notification path + retry on transient
- [ ] Per [ADR 0008 § Open questions OQ#3](../adr/0008-subscription-target-model.md) (resolved 2026-05-23)

---

## 8. Phase 8 — Contracts (commit 5/5 candidate)

- [ ] New file `docs/contracts/subscription_target.schema.json` (discriminated union, chat | channel variants)
- [ ] OpenAPI spec cross-reference from `POST /api/v1/digests` + `POST /api/v1/watchlists` request shapes
- [ ] `tests/test_contracts_subscription_target.py` validating example JSON instances against schema

---

## 9. Phase 9 — Tests (aggregate / integration)

- [ ] Service-layer regression: subscribe with `kind=chat` (existing behaviour unchanged) + `kind=channel` (new) + legacy `chat_id` shim mapping
- [ ] `ChannelAdminRequired` graceful + deactivation path
- [ ] Idempotent upsert: same `(owner_id, name)` different `target.kind` → UPDATE with `changed_fields=["target_kind", "channel_id", "chat_id"]`
- [ ] Integration: full subscribe → cron tick → publish to channel; mocked aiogram `bot.send_message(channel_id, ...)`
- [ ] Migration runtime smoke: testcontainer Postgres with seeded `digest_subscriptions` rows; assert `target_kind='chat'` for all existing rows, no row count change
- [ ] Backward-compat regression file `tests/test_subscribe_legacy_chat_id.py` per [ADR 0008 § Test strategy](../adr/0008-subscription-target-model.md)

---

## 10. Phase 10 — Docs (commit 5/5 candidate)

- [ ] ADR 0008 история-row appended with sprint PR SHA + verdict
- [ ] USER_GUIDE «Digest Subscription» section extended (target shape + channel publish UX)
- [ ] MCP_AGENT_GUIDE `subscribe_digest` target shape note
- [ ] New runbook `docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` (mirror [`WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md) shape — pre-deploy checklist, deploy commands, post-deploy smoke matrix, 24h watch matrix)
- [ ] CHANGELOG entry under `[Unreleased]` § «Wave 1 step 4 — Shareable Digest»
- [ ] REVIEW marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` (mirror step 3 structure) — landed post-watch-GREEN

---

## 11. Quality bar (перед PR)

- [ ] Default pytest: **~2226–2251 passed, 0 failed** (baseline +25–50 per Option B headline)
- [ ] `TEST_POSTGRES=1` pytest: **~2530–2555 passed, 0 failed**
- [ ] `ruff format --check . && ruff check .` — clean
- [ ] 0 regressions on `test_api_digests`, `test_api_watchlists`, `test_subscribe_idempotency`, `test_f6_*`, `test_f11_*`
- [ ] New tests: `test_subscribe_legacy_chat_id` + `test_subscribe_digest_channel_target` + `test_contracts_subscription_target` + migration smoke
- [ ] Karpathy P1 (persistent entity for target shape) + P7 (graceful degradation for channel publish best-effort) checklist в PR description
- [ ] **Git:** commit/push/PR — **только по явному запросу пользователя** ([`AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) § 8)

---

## 12. Acceptance / DoD (закрытие спринта)

- [ ] All 4 surfaces (HTTP / MCP / Bot / CLI) accept `target: {kind, chat_id|channel_id}` AND backward-compat `chat_id: int`
- [ ] Channel-publish smoke: `tg_digest_channel_publish_total{result="success"}` ≥ 1 post-deploy
- [ ] Permission-denied path tested via mocked aiogram + soft-deactivation verified
- [ ] Migration upgrade + downgrade smoke on testcontainer Postgres PASS
- [ ] `docs/contracts/subscription_target.schema.json` lands + OpenAPI cross-ref
- [ ] `prompts/bot.yaml` v1.6.0 → v1.7.0 ships ONLY new `target_kind_semantics` section
- [ ] ADR 0008 история-row updated с PR SHA
- [ ] CHANGELOG entry под `[Unreleased]`
- [ ] DONE marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` published post 24h GREEN watch

---

## 13. Anti-scope (HARD — STOP если потянуло)

| Запрещено | Куда отложено |
|---|---|
| (a) PATCH target update endpoint | Future PR if production usage shows real PATCH need |
| (b) test-publish / publish-now endpoints | Wave 2A if A4 integrators ask |
| (c) Middleware broadening to non-subscribe endpoints | Separate «middleware broadening» follow-up PR (production transient-retry signal-gated) |
| (d) `kind=webhook` in primary enum | Wave 2A (additive `ALTER TYPE` non-breaking; per ADR 0008 § Recommendation) |
| (e) `prompts/bot.yaml` changes outside `target_kind_semantics` section | Step 4.1 sub-sprint (BUG-025/026/027 HARD RULES, v1.7.0 → v1.8.0) |
| (f) Bot UX cluster (BUG-025 / BUG-026 / BUG-027) | Step 4.1 sub-sprint (scope-locked per PLAN § 8.1) |
| (g) Wording «forbidden forever» | Use «not in this sprint» everywhere — per user guidance «на текущий момент» |

---

## 14. После merge (вне этого PR, по запросу пользователя)

- [ ] Deploy per `docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` (Phase 10 deliverable)
- [ ] 24h watch window открыт; close T+24h GREEN
- [ ] DONE marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md`
- [ ] Следующий шаг: **Wave 1 step 4.1** (Bot UX cluster — BUG-025/026/027 + `prompts/bot.yaml` v1.7.0 → v1.8.0). **Step 4.1 planning = separate planning session** post-step-4-closure (NOT formalized in 2026-05-23 session).

---

## Ссылки

| Документ | Назначение |
|---|---|
| [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md) | Authoritative scope source |
| [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md) | Sprint prompt with phases + acceptance + anti-scope |
| [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) | Accepted 2026-05-23; primary enum `{chat, channel}` only |
| [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) | Companion ADR; middleware reused as-is |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist for Karpathy compliance |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | Quality lifecycle, no auto-commit |
| [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md) | Template for upcoming step 4 deploy runbook |
| [`CHECKLIST_WAVE1_STEP3_1_2026-05-22.md`](CHECKLIST_WAVE1_STEP3_1_2026-05-22.md) | Format-precedent for this checklist |
