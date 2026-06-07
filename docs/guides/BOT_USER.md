# Telegram Bot — User Guide

**Version:** 4.4.0 | **Audience:** Track C2 digest consumers and bot power users

The TG_parser Telegram bot provides free-form chat with access to knowledge-base tools (search, Q&A, digests, watchlist). Wave 1.5 digest consumers on **Track C2** need bot access; Track C1 consumers do not.

---

## Getting started

### Registration

The bot only responds to **registered** users. If you send `/start` and see:

> You are not registered. Contact the administrator.

Ask your admin to register your Telegram user ID before trying again.

### /start

After registration, `/start` shows:

- Your display name and role
- Number of channels available to you (0 for digest-only C2 users)

---

## Track C2 — digest in DM

Once admin creates a `subscribe_digest` subscription targeting your `chat_id`:

1. `/start` the bot (registration check).
2. Wait for the cron schedule (e.g. daily 09:00).
3. Digest messages arrive in this chat automatically.

See [DIGEST_CONSUMER.md](DIGEST_CONSUMER.md) § C2 for timing expectations.

You do **not** need to send commands to receive digests.

---

## What the bot can do (registered users)

The bot is a Gemini-powered agent with a subset of MCP tools (32 tools). Examples in natural language:

| You might ask | Bot capability |
|---------------|----------------|
| «Search for articles about X» | `search_knowledge_base` |
| «What did channel Y say about Z?» | `ask_question` |
| «List my topics» | `list_topics` |
| «Subscribe me to a daily digest» | `subscribe_digest` (with confirmation flow) |

**Scope:** you only see channels you **own**. Digest-only C2 users typically have **no owned channels** — search/ask over admin's KB is **not** available unless admin assigns channel ownership (Track B uses MCP instead).

Write operations (`add_channel`, `subscribe_digest`, etc.) use a **two-phase confirmation** — the bot previews the action and asks you to confirm before executing.

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Not registered | Contact admin |
| No digest in DM | Confirm admin created subscription; check schedule |
| «I don't understand» on UUID | Use full sentences; for deletes, ask bot to list items first |
| Bot silent | Check bot not blocked; try `/start` |

---

## More documentation

- [DIGEST_CONSUMER.md](DIGEST_CONSUMER.md) — digest-only path
- [GETTING_STARTED.md](../GETTING_STARTED.md) — choose Track B vs C
- [USER_GUIDE.md](../USER_GUIDE.md) — full bot and F6 reference
