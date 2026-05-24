# ADR 0008 – Subscription target model for watchlist / digest

## Статус

**Accepted (2026-05-23).** Promoted from Draft after Wave 1 step 4 planning sub-session locked Q1 (Option B), Q2 (defer webhook to Wave 2A, no enum reservation), and related anti-scope (see [`PLAN_WAVE1_STEP4_2026-05-23.md` § 7](../notes/PLAN_WAVE1_STEP4_2026-05-23.md)). Original Draft framing (2026-05-21) scope-bound the **target-addressing model** for `subscribe_watchlist` / `subscribe_digest` across all four surfaces (MCP, Bot, CLI, **HTTP API**) **before** the HTTP API surface lands — so the new endpoint would not calcify a model the system later regrets. Step 3 shipped chat-only HTTP shape (per its Q6); step 4 promotes the polymorphic model with the **primary enum locked to `{chat, channel}` only**, webhook deferred to Wave 2A as additive migration.

## Контекст

### Current state (post-F11 + F6 + F4-B Core)

Both `watch_interests` (F11) and `digest_subscriptions` (F6) carry a
single addressing field — **`chat_id`** — pointing to an aiogram chat
where the bot pushes matches / scheduled digests.

```
subscribe_watchlist(title, channel_ids, chat_id, keywords?, ...)
subscribe_digest(name, channel_ids, chat_id, cron_expression?, ...)
```

This works for the original audience (A1 owner with personal Telegram
chat). Three signals from 2026-04-26 → 2026-05-20 stretch the model:

1. **A4 AI Agent Builder** (programmatic integration). The agent
   doesn't have a Telegram chat — it wants a `webhook_url` or an HTTP
   callback to its own service. Today this is impossible.
2. **A6 Domain Curator → shareable digest** (Wave 1 step 4 preview).
   Subscription target is the curator's own Telegram **channel**
   (publish-to-channel, not chat). Different aiogram API surface, but
   structurally adjacent to `chat_id`.
3. **ENH-9 `workspace_id` on subscriptions** (filed in
   [`mcp_testing/2026-05-15_claude_session/02-enhancements.md`](../notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md)).
   Subscriptions should carry **workspace context** so push payloads
   can hyperlink to the user's workspace dashboard / can scope match
   relevance to workspace channels (instead of replicating
   `channel_ids[]` per subscription).

### Why HTTP API forces the decision now

Wave 1 step 3 lands `POST /api/v1/watchlists` + `POST /api/v1/digests`
(P-1 / P-2). Once an HTTP contract is public, **changing the target
model is a breaking change** — clients depend on the request shape.
The MCP / Bot / CLI surfaces internally normalize, but HTTP is the
external commitment.

If the HTTP endpoint locks `chat_id` as the only target — A4 (AI
agents) are blocked; ENH-9 becomes a half-fix; shareable digest needs
its own special-case endpoint. Better: pick the target model **once**,
expose it across all surfaces.

### BUG-022 idempotency interaction

[`BUG_LOG.md` § BUG-022](../notes/BUG_LOG.md) notes that `subscribe_*`
calls are not idempotent. ADR 0009 addresses the idempotency policy;
the natural keys are asymmetric (mirror current schemas):
`watch_interests` uses `(user_id, title)` (label field is `title`);
`digest_subscriptions` uses `(owner_id, name)` (label field is `name`).
If the target model expands (chat_id OR webhook_url OR channel_id),
the natural keys could need expansion — but the simpler stance is that
two subscriptions with the same `(label, owner)` are «the same logical
subscription» regardless of target (target is mutable). This ADR
therefore aligns with ADR 0009 on the «what makes two subscriptions
structurally the same» question: **label + owner**, not target.

## Options matrix (decision converging)

Three candidates for the target-addressing model. Final shape will be
locked in Wave 1 step 3 execution sub-session (this ADR captures the
direction, not the wire format).

### Option A — Status quo (`chat_id` only)

Keep `chat_id` as the only addressing field. A4 / webhook / channel
targets remain explicitly unsupported.

**Pros:**

- Zero migration; existing MCP / Bot / CLI contract preserved
  bit-for-bit.
- Simplest implementation for P-1 / P-2 (HTTP endpoints just expose
  the existing surface).

**Cons:**

- Blocks A4 entirely (an AI agent has no Telegram chat).
- Forces shareable digest (Wave 1 step 4) to introduce a separate
  endpoint or a special-case argument.
- ENH-9 `workspace_id` enrichment is orthogonal but the «target +
  context» model muddles together; explicit target-model decision
  cleans up the design space.
- Calcifies an audience-A1-only contract at the most public surface
  (HTTP).

### Option B — Polymorphic target field (recommended direction)

Replace `chat_id: int` with a single polymorphic `target` field that
encodes both kind and address:

```yaml
target:
  kind: chat | channel | webhook   # discriminator
  chat_id: int                     # required iff kind=chat
  channel_id: str                  # required iff kind=channel
  webhook_url: str                 # required iff kind=webhook
  headers: dict[str, str] | None   # optional, kind=webhook only
```

Service layer dispatches on `kind` to:

- `kind=chat` → existing aiogram `bot.send_message(chat_id, ...)`
  path (zero behaviour change).
- `kind=channel` → aiogram `bot.send_message(channel_id, ...)` —
  publish to a Telegram channel (Wave 1 step 4 enabler).
- `kind=webhook` → HTTP POST to `webhook_url` with the same payload
  body as the chat push (JSON envelope; A4 enabler).

Storage: extend `watch_interests` / `digest_subscriptions` with
`target_kind` (enum) + nullable `chat_id` / `channel_id` /
`webhook_url` columns; or store a single `target_jsonb` column with
JSON-schema check constraint. Per ADR 0006 principle 1 (persistent
entities, not metadata dicts), columns are preferred.

**Pros:**

- Single target field across all four surfaces — clean public API.
- Unblocks A4 (webhook) + Wave 1 step 4 (channel) in the same shape.
- Backward-compat path: `target: {kind: chat, chat_id: <int>}` is
  trivially mappable from existing `chat_id: <int>` arg via a thin
  shim — existing MCP / Bot / CLI callers don't break.
- Karpathy-like principle 1 (explicit persistent entity for target
  shape) — and principle 7 (each kind has its own failure mode →
  push-blocked chat soft-deletes interest; webhook 5xx retries with
  backoff; channel-publish requires admin in channel and fails
  gracefully).

**Cons:**

- Migration required (Alembic for new columns; service layer changes
  in 3+ services).
- Slight API verbosity increase (`target: {kind: chat, chat_id: 123}`
  vs `chat_id: 123` — but new callers can use the simple form via
  Pydantic discriminated unions / JSON-Schema oneOf).
- Webhook target adds outbound-HTTP failure modes (auth, retry,
  cert pinning, DNS). These need separate observability + retry
  policy.

### Option C — Multiple optional target fields (parallel)

Add `webhook_url: str | None`, `channel_id: str | None` as siblings
to existing `chat_id`. Service layer picks whichever is set.

**Pros:**

- Minimal migration (just additive columns, no enum / discriminator).
- Backward-compat trivial.

**Cons:**

- Validation surface grows quadratically: «exactly one of chat_id /
  channel_id / webhook_url is set» check at every layer.
- Service-layer dispatch is less clean (3 if-branches scattered, vs 1
  switch on `target.kind`).
- Future target kinds (Slack? Discord? Custom queue?) bloat the
  parallel-fields list.
- Inconsistent with how F4-B Core did workspace_id (single explicit
  field), F11 did channel_ids (single explicit list), etc.

## Recommendation (Accepted 2026-05-23)

**Option B (polymorphic target with discriminator) — ACCEPTED with primary enum `{chat, channel}` only.** Cleanest public API, aligns with Karpathy-like persistent-entity discipline, future-proof for additive webhook extension in Wave 2A. Webhook target is **deferred to Wave 2A** as additive enum migration; step 4 does **not** reserve the `'webhook'` enum value.

### Migration path for Wave 1 step 4 (execution sub-session deliverable)

1. **Storage (step 4)** — add `target_kind` Postgres ENUM with values **`('chat', 'channel')`** + nullable `chat_id` (int) + `channel_id` (str). Existing rows migrate via `target_kind='chat'` + populate `chat_id` from the existing column (trivially — every row today is `chat_id`-only). Alembic upgrade fills these atomically; downgrade drops the new columns back to plain `chat_id: int`. Migration runtime smoke covered by ADR 0009 testcontainer precedent.
2. **Domain models (step 4)** — Pydantic discriminated union `TargetChat | TargetChannel` with `kind: Literal['chat' | 'channel']` tags. Service layer dispatches on `target.kind`. `kind=webhook` is **NOT** yet a valid runtime kind — no need to even raise `NotImplementedError` because the Postgres enum literally rejects it (and the Pydantic union doesn't include the variant). Type-safety enforces the constraint at compile time.
3. **Surfaces (step 4)** — HTTP / MCP / Bot / CLI all accept `target: {kind, chat_id|channel_id}` shape. **Backward compat:** existing `chat_id: int` argument maps trivially to `target={'kind': 'chat', 'chat_id': <int>}` via thin shim on each surface; legacy callers don't break. Precedence: if both `chat_id` and `target` are set → 400 error «provide one of chat_id (legacy) or target (new)». Eventually deprecate `chat_id` (separate sprint, v5.0.0).
4. **Bot prompt (step 4)** — `prompts/bot.yaml` v1.6.0 → v1.7.0 adds a single new `target_kind_semantics` section (≤15 lines) covering when LLM should pick `kind=chat` vs `kind=channel` and backward-compat fallback semantics. All other prompt sections untouched in step 4 (Bot UX cluster BUG-025/026/027 = step 4.1 scope with separate v1.7.0 → v1.8.0 bump). See [`PLAN_WAVE1_STEP4_2026-05-23.md` § 7 Q3-under (X1)](../notes/PLAN_WAVE1_STEP4_2026-05-23.md) for the version-rebase rationale (current `prompts/bot.yaml` already at v1.6.0 per `41a925c`).
5. **HTTP API (step 4)** — extend existing `POST /api/v1/watchlists` + `POST /api/v1/digests` with new `target` field (Pydantic discriminated union) **AND** keep legacy `chat_id` arg for backward-compat. **No new POST or PATCH endpoints** in step 4. Target change workflow = `unsubscribe + resubscribe` (natural-key idempotency per ADR 0009 makes this safe).
6. **Channel publish semantics (step 4)** — best-effort: try the publish; on `ChatAdminRequired` / «bot not admin» / «channel not found» error → soft-deactivate the subscription with typed error `channel_publish_permission_denied`; send fallback notification to subscription owner's `chat_id` if available. Detailed retry policy + smoke test in implementation sprint. Per OQ#3 resolution below.

### Migration path for Wave 2A (additive webhook extension — non-breaking)

When A4 (AI integrator) signal accumulates and Wave 2A starts:

1. **Storage** — additive `ALTER TYPE target_kind ADD VALUE 'webhook'` + `ALTER TABLE … ADD COLUMN webhook_url TEXT NULL` + optional `headers JSONB NULL`. No existing-row migration needed (all current rows are `chat` or `channel`).
2. **Domain models** — extend Pydantic union with new `TargetWebhook` variant.
3. **Service layer** — add HTTP-POST dispatch path with HMAC signature + retry policy + dead-letter (per ADR 0008 OQ#1/#2 resolution in Wave 2A planning).
4. **Surfaces** — add `webhook_url` to HTTP / MCP / CLI / Bot tool descriptors. Pydantic discriminated union accepts new variant automatically.

This is **fully non-breaking** for chat/channel callers: Postgres enum extension is additive (existing values preserved); Pydantic discriminated union extension is backward-compatible (existing variants unchanged); HTTP API gets a new optional field. No version bump required for chat/channel clients.

### ENH-9 workspace_id is orthogonal

ENH-9 (workspace_id on subscriptions) is **already landed in step 3** (Wave 1) — adds a `workspace_id: str | None` parameter to `subscribe_*` (per F4-B Q7 / Q8). Stored in a separate column (`workspace_id` FK to `workspaces.id`). Used for (a) scoping match relevance, (b) push-payload hyperlinks, (c) future RBAC. **Not part of the target model.** Step 4 does not touch workspace scoping logic.

## Open questions — resolved at step 4 planning (2026-05-23)

1. **Webhook security** — HMAC signature? mTLS? IP allowlist? Bearer
   token in `Authorization` header (per ADR 0005 pattern)? Minimum
   safe: HMAC-SHA256 signature over body + `X-TGParser-Signature`
   header with shared secret per subscription.

   **Resolution (2026-05-23):** **N/A for step 4** — webhook deferred to Wave 2A per Q2. Detailed HMAC vs mTLS vs bearer-token shape will be designed in Wave 2A when ADR 0008 enum is extended (additive migration). Documenting here only that webhook security design is **not blocking step 4** and does **not** need to be locked now.

2. **Webhook retry policy** — `exponential backoff + jitter` like
   ADR 0006 principle 4. How many attempts? When to soft-disable the
   interest (mirror «push-blocked chat → deactivate interest» from F11
   today)? Lean: 3 attempts, exponential `2^n` seconds, then deactivate
   + emit `tg_watchlist_webhook_dead_total`.

   **Resolution (2026-05-23):** **N/A for step 4** — same as OQ#1; deferred to Wave 2A.

3. **Channel publish** — does the bot need admin rights in the
   channel? How is that verified? Probably best-effort: try the publish;
   on `ChatAdminRequired` raise typed error + deactivate interest.

   **Resolution (2026-05-23):** **Best-effort: try the publish; on `bot not admin` / `channel not found` error, soft-deactivate the subscription with typed error `channel_publish_permission_denied`; send fallback notification to subscription owner's `chat_id` if available.** Detailed retry policy + smoke test in implementation sprint (per [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md` § 2 Phase 7](../notes/START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md)). Operational pre-flight: bot must be admin in user's channel before subscription cron tick — documented in `WAVE1_STEP4_DEPLOY_AND_WATCH.md` runbook (step 4 deliverable).

4. **Target uniqueness** — can the same user subscribe two watchlists
   to the same target? Yes (different titles / keywords). Idempotency
   keys per ADR 0009 are `(user_id, title)` (watch_interests) or
   `(owner_id, name)` (digest_subscriptions), not `(*, target)`.

   **Resolution (2026-05-23):** **No change.** `watch_interests` keeps `(user_id, title)`; `digest_subscriptions` keeps `(owner_id, name)`. Two subscriptions with the same `(label, owner)` but different `target` are **the same logical subscription** — target change is a **mutation of an existing row**, not creation. Mutation workflow = `unsubscribe + resubscribe` (per [`PLAN_WAVE1_STEP4_2026-05-23.md` § 7 Q4](../notes/PLAN_WAVE1_STEP4_2026-05-23.md) decision — no PATCH endpoint). Idempotency natural keys per ADR 0009 remain authoritative.

5. **Payload schema** — separate JSON Schema in `docs/contracts/` for
   the webhook payload? Yes (per ADR 0006 principle 1). Field set:
   `subscription_id, match_id, source_ref, score, document_excerpt,
   matched_at, workspace_id?` (last optional, per ENH-9).

   **Resolution (2026-05-23):** **N/A for step 4** — webhook payload schema deferred to Wave 2A. Step 4 ships `docs/contracts/subscription_target.schema.json` describing the **target shape** (chat | channel discriminator), not the webhook payload. Webhook-payload schema designed alongside webhook implementation in Wave 2A.

6. **CLI representation** — `tg-parser watchlist add --webhook-url X`
   vs `--target-kind webhook --webhook-url X`? Lean: the former
   (shorter; mutually exclusive `--chat-id` / `--webhook-url` /
   `--channel-id` flags map to discriminator).

   **Resolution (2026-05-23):** **`tg-parser watchlist add` accepts mutually-exclusive `--chat-id <int>` / `--channel-id <str>` flags mapping to the discriminator** (no `--webhook-url` in step 4 per Q2). Same shape for `digest add`. Old `--chat-id`-only callers continue to work (kind inferred as `chat` via backward-compat shim). `--webhook-url` flag added in Wave 2A.

7. **Existing rows migration** — straightforward (`target_kind='chat'`
   default in Alembic). But: do we deprecate `chat_id` field on the
   row immediately or keep it filled for backward-compat? Lean: keep
   filled for one minor version; drop in v5.0.0.

   **Resolution (2026-05-23):** **Straightforward** — `target_kind='chat'`, `chat_id` populated from existing column, `channel_id` NULL. Alembic upgrade fills these atomically; downgrade drops them back to plain `chat_id: int`. Migration runtime smoke covered by ADR 0009 testcontainer precedent (Wave 1 step 3). Keep `chat_id` column filled for backward-compat shim through at least one minor version; full removal in v5.0.0 (separate sprint).

## Test strategy (preliminary)

- **Unit:** each `TargetUnion` variant has its own send-path; mocked
  bot / mocked HTTPX for webhook; assert payload shape per
  contract schema.
- **Integration:** sqlite + testcontainers; full subscribe → match →
  send-attempt → store result row.
- **Webhook:** HTTPX mock asserting HMAC signature; retry behaviour on
  5xx; deactivation on N consecutive failures.
- **Backward-compat:** legacy `chat_id`-only callers still work
  unchanged (regression-guard `tests/test_subscribe_legacy_chat_id.py`).
- **Cross-target idempotency:** two `subscribe_watchlist` calls with
  same `(user_id, title)` but different `target` → ADR 0009 decides
  (probably upsert: same row, target field UPDATEd).

## Последствия (preliminary)

### Положительные (when Option B lands)

- A4 (AI Agent Builder) unblocked via webhook target.
- Wave 1 step 4 (shareable digest) enabled — channel target is the
  natural primitive.
- ENH-9 workspace_id enrichment cleanly orthogonal — no design
  collision.
- HTTP API surface (P-1 / P-2) ships with the future-proof shape, not
  with a chat-only contract that needs breaking change later.
- Karpathy-like principle 1 honoured (persistent entity for target).

### Отрицательные / accepted debt

- One Alembic migration touching two tables.
- Three send-paths in the service layer (currently one). More tests,
  more failure modes.
- Webhook outbound-HTTP introduces a new dependency direction
  (TG_parser pushes to external services). Network security + retry
  policy must be designed.
- Legacy `chat_id` shim adds a few lines of complexity to every
  surface; deprecation cycle needed.

### Что НЕ меняется этим ADR (when it lands)

- F11 / F6 service-layer hooks (match-scoring, digest-format) — only
  the «how do I deliver» step is generalized.
- F4-B workspace scoping — workspace_id is orthogonal.
- Existing CLI / MCP / Bot behaviours for `chat_id` callers — backward-
  compat shim preserves them.

## Ссылки

- [`docs/notes/BUG_LOG.md` § BUG-022](../notes/BUG_LOG.md) — idempotency.
- [`docs/notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md` § ENH-9](../notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md) — workspace_id on subscriptions.
- [`docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 3](../notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) — A4 (AI Agent Builder) + A6 (Domain Curator) audience descriptions.
- [`docs/notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` § 4.B](../notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) P2 — F6 / F11 CRUD on API.
- [`docs/notes/PARITY_DECISION_TRACKING.md` § P-1 / P-2](../notes/PARITY_DECISION_TRACKING.md) — primary parity package shape.
- [`docs/notes/START_PROMPT_SPRINT_F11.md`](../notes/START_PROMPT_SPRINT_F11.md) — F11 watchlist contract (chat_id today).
- [`docs/contracts/`](../contracts/) — JSON Schema home. Step 4 lands `subscription_target.schema.json` (chat | channel discriminator); webhook payload schema deferred to Wave 2A alongside webhook implementation.
- ADR 0005 (bot LLM flexibility) — auth pattern precedent.
- ADR 0006 (Living-KB principles) — principle 1 (persistent entity), principle 7 (graceful degradation per target kind).
- ADR 0009 (idempotency) — companion ADR; defines asymmetric natural keys: `watch_interests = (user_id, title)`, `digest_subscriptions = (owner_id, name)`.

## История

| Дата | Изменение |
|------|-----------|
| 2026-05-21 | Draft created in S1 planning sub-session. Captures problem statement (A4 / Wave 1 step 4 / ENH-9 signals) + 3-option matrix + preliminary Option B recommendation. Final shape locked in step 3 execution sub-session. |
| 2026-05-23 | Promoted Draft → Accepted at Wave 1 step 4 planning sub-session. Q1 resolved = Option B; Q2 resolved = webhook deferred to Wave 2A without primary-enum reservation. Migration path documented for step 4 execution. Open questions OQ#1/#2/#5 deferred to Wave 2A; OQ#3/#4/#6/#7 resolved (see § Open questions). All anti-scope items locked. Cross-link: [`PLAN_WAVE1_STEP4_2026-05-23.md`](../notes/PLAN_WAVE1_STEP4_2026-05-23.md) § 7 Q1–Q4 + Q3-under (X1); [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](../notes/START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md). |
| 2026-05-24 | Implementation on branch `feat/wave1-step4-shareable-digest-2026-05-24` (uncommitted). Migration `a8b7c6d5e4f3`; 4-surface target discriminator + channel publish best-effort per OQ#3. Verdict: pending 24h watch / PR merge. |
