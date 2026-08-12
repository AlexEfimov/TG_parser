# Wave 1.5 — Validator Onboarding Runbook

**Version:** 4.4.0 | **Audience:** TG_parser operator (admin only)

Operational checklist for onboarding external validators during Wave 1.5 dogfooding. Not a product launch — informal access, friction logging, no roadmap promises.

**Recommended caps:** ~3 Track B (MCP curators) + ~5 Track C (digest consumers).

**Friction log:** tag entries `[track-b]` or `[track-c]` in `docs/runbooks/WAVE1_5_VALIDATION_LOG.md` (create when ≥3 observations).

**Mechanics of handing out access** (token issuance, verification, revocation, cost and isolation limits, `scripts/onboard_test_users.py`): [`TEST_ACCESS_MULTI_USER.md`](TEST_ACCESS_MULTI_USER.md). This runbook stays the *programme* — who to invite per track and what to observe.

---

## §0 — Prod pre-flight (run once before any external user)

Complete before issuing tokens or invite links.

### Multi-tenancy

- [ ] `tg-parser migrate-users` executed (or `--dry-run` shows already migrated)
- [ ] Admin user exists; you can `whoami` as admin via MCP

### MCP (Track B)

- [ ] `MCP_AUTH_ENABLED=true` in production `.env`
- [ ] MCP service healthy: `curl -sf {MCP_URL}` or MCP client `whoami` as admin
- [ ] Reverse proxy / TLS terminates correctly for `{MCP_URL}`

### Bot (Track C2 only)

- [ ] `docker compose --profile bot up -d` (or equivalent) — bot container running
- [ ] `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY` set
- [ ] Bot responds to admin `/start`

### Digest channel (Track C1)

- [ ] Telegram channel `{DIGEST_CHANNEL}` created
- [ ] **Bot is channel admin** with **Post Messages** permission ([USER_GUIDE](../USER_GUIDE.md) § Channel publish)
- [ ] Manual smoke: publish a test message to channel via bot (or wait for one cron digest)
- [ ] `subscribe_digest` configured (see § Track C1) — subscription `is_active=true`

### Scheduler

- [ ] Background scheduler enabled; digests fire on expected cron
- [ ] Prod KB has processed documents (digest non-empty on tick)

### Secrets hygiene

- [ ] Real URLs/tokens **not** committed to git — use onboarding message templates below with live values OOB

---

## § Track B — MCP curator (own channels)

### 1. Generate MCP token

```bash
# Example — use a cryptographically random string
openssl rand -hex 32
```

Store the raw token securely; it is shown to the user **once**. DB stores SHA-256 hash only.

### 2. Register user

Via MCP (as admin):

```
register_user(name="validator-alice", role="user", max_channels=3)
```

Note returned `user_id` (UUID).

### 3. Bind token

```
add_user_auth(
  user_id="<uuid>",
  auth_type="mcp_token",
  identifier="<raw-token-from-step-1>",
  client_name="alice-cursor"
)
```

### 4. Optional — accelerate cold start

After validator calls `add_channel`, you may run:

```
trigger_pipeline(channel_id="@their_channel")
```

### 5. Send onboarding message (template)

```text
Привет! Доступ к TG_parser (Track B — свой curator).

1. Док: docs/guides/MCP_CONNECT.md (или PDF/ссылка)
2. MCP URL: {MCP_URL}
3. Token: <paste once>
4. Шаги: whoami → add_channel (1 публичный канал) → get_pipeline_status → ask_question
5. Важно: приватные каналы без доступа server-account не заработают.
6. Friction — просто напиши мне текстом.

Лимит: 3 канала.
```

### 6. Smoke test (admin verifies)

- [ ] Validator `whoami` shows correct name, role `user`, max_channels=3
- [ ] Validator `add_channel` succeeds for a public test channel
- [ ] `get_pipeline_status` → eventually `last_success_at` set
- [ ] `ask_question` returns non-empty (after pipeline)

---

## § Track C1 — Public digest channel

One-time setup; then mass-invite consumers.

### 1. Create / verify digest channel

- [ ] Channel `{DIGEST_CHANNEL}` exists
- [ ] Bot added as **administrator** with **Post Messages**

### 2. Create digest subscription (admin MCP)

```
subscribe_digest(
  name="wave15-public",
  channel_ids=["@your_prod_channel_1", "@your_prod_channel_2"],
  target={"kind": "channel", "channel_id": "@YourDigestChannel"},
  cron_expression="0 9 * * *",
  timezone="UTC",
  format="summary",
  language="ru"
)
```

`channel_ids` must be channels **you** own (admin sees all). Legacy alternative: `chat_id=` instead of `target` — prefer `target` dict (ADR 0008).

### 3. Verify first publish

- [ ] Wait for cron tick OR temporarily shorten cron for test
- [ ] Digest post appears in `{DIGEST_CHANNEL}`
- [ ] If soft-deactivated: check bot admin rights, re-subscribe after fix

### 4. Mass invite template

```text
Подписка на digest (Track C — только чтение):

1. Док: docs/guides/DIGEST_CONSUMER.md
2. Канал: https://t.me/{DIGEST_CHANNEL}
3. Расписание: ежедневно 09:00 UTC (первая сводка — после следующего тика)
4. Если захочешь копать глубже — напиши, обсудим MCP-доступ (Track B).
5. Feedback — свободным текстом.
```

**Do not:** `register_user`, MCP token, or `add_channel` for C1 consumers.

---

## § Track C2 — Private DM digest

Per consumer; more admin work.

### 1. Get consumer Telegram user ID

From `@userinfobot`, forwarded message, or bot logs.

### 2. Register user

```
register_user(name="consumer-bob", role="user", max_channels=0)
```

(`max_channels=0` or `1` — they won't add channels.)

### 3. Bind Telegram auth

```
add_user_auth(
  user_id="<uuid>",
  auth_type="telegram",
  identifier="<telegram_user_id>",
  client_name="bob-telegram"
)
```

### 4. Consumer /start

Ask consumer to open `{BOT_USERNAME}` and send `/start`. Must succeed before digest delivery.

### 5. Create digest subscription

```
subscribe_digest(
  name="bob-daily",
  channel_ids=["@your_prod_channel_1"],
  target={"kind": "chat", "chat_id": <consumer_telegram_id>},
  cron_expression="0 9 * * *",
  timezone="Europe/Moscow",
  format="bullets"
)
```

Legacy: `chat_id=<id>` without `target` dict still works.

### 6. Onboarding template

```text
Digest в личку (Track C2):

1. Док: docs/guides/DIGEST_CONSUMER.md + docs/guides/BOT_USER.md
2. Бот: @{BOT_USERNAME} → /start
3. Первая свodka: {schedule}
4. Feedback — текстом.
```

---

## § Teardown (after validation period)

### Track B

```
# As admin — revoke access
remove_user_auth(mapping_id="<mapping-uuid>")

# Optional — pause validator channels (validator or admin)
pause_channel(channel_id="@their_channel")
# Or remove entirely:
remove_channel(channel_id="@their_channel")
```

### Track C

- **C1:** consumers unsubscribe themselves; optionally `unsubscribe_digest(subscription_id=…)` if retiring the public channel digest
- **C2:** `unsubscribe_digest` + `remove_user_auth` for telegram mapping

---

## § Validation log template

Create `docs/runbooks/WAVE1_5_VALIDATION_LOG.md` when observations accumulate:

```markdown
# Wave 1.5 Validation Log

| Date | Track | Observer | Observation | Signal (2A/2B/A6) |
|------|-------|----------|-------------|-------------------|
| 2026-06-10 | [track-c] | alice | «where see full articles?» | 2B |
| 2026-06-11 | [track-b] | bob | cold start confusing | A6 |
```

---

## § Operator reference (placeholders)

Fill in your deployment — **do not commit live secrets**.

| Placeholder | Example (replace) |
|-------------|-------------------|
| `{MCP_URL}` | `https://mcp.example.com/mcp` |
| `{BOT_USERNAME}` | `@YourTgParserBot` |
| `{DIGEST_CHANNEL}` | `@YourCuratedDigest` |

Prod infrastructure topology: generic guide in [SERVER_ARCHITECTURE.md](../SERVER_ARCHITECTURE.md). Host-specific values live in your private ops notes (not in this repo).

---

## Related docs

- [GETTING_STARTED.md](../GETTING_STARTED.md) — user-facing path fork
- [PLAN_WAVE1_5_DOGFOODING_2026-06-06.md](../notes/PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) — dogfooding tracker
- [USER_GUIDE.md](../USER_GUIDE.md) — F6 digest, multi-tenancy, channel publish
