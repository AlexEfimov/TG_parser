# Digest Consumer — Track C

**Version:** 4.4.0 | **Audience:** read-only digest subscribers (no MCP, no install)

You receive **scheduled summaries** from a curated Telegram knowledge base — processed and written by LLM on a fixed schedule.

---

## What is a digest?

A digest is an automatic summary of **new content** since the last run from selected Telegram channels. Formats:

| Format | Style |
|--------|-------|
| `summary` | Short paragraph overview (default) |
| `bullets` | Bullet list of key points |
| `detailed` | Longer structured summary |

Language and schedule are set by the operator (e.g. daily at 09:00 UTC).

---

## C1 — Public digest channel (recommended)

**Simplest path:** subscribe to a Telegram channel where digests are published.

### Your steps

1. Open the invite link from your admin (e.g. `https://t.me/{DIGEST_CHANNEL}`).
2. Tap **Subscribe** in Telegram.
3. Wait for the next scheduled digest post.

### Timing

| Event | When |
|-------|------|
| Subscription | Immediate |
| **First digest** | Next cron tick (e.g. next day 09:00 UTC) — admin confirms schedule |

Subscribing ≠ receiving content instantly. If the channel is empty until the first cron run, that is expected.

### What to expect

- Posts appear in the channel on schedule.
- Each post summarizes **new** messages since the previous digest.
- Quiet days may produce shorter or empty digests.

### Feedback

If you think «I want to read the full source» or «where can I browse topics?» — tell the admin. That is valuable product signal.

---

## C2 — Private DM digest

Personal delivery to your Telegram chat via the TG_parser bot.

### Your steps

1. Admin registers your Telegram account (you do not do this yourself).
2. Open `{BOT_USERNAME}` in Telegram.
3. Send `/start` — you should see a personalized greeting with your name.
4. Digests arrive in DM on the configured schedule.

If `/start` says «not registered» — contact admin before retrying.

### Timing

Same as C1: first DM digest arrives on the next cron tick after admin creates the subscription.

---

## What digest consumers do NOT get

- MCP or API access
- Search or Q&A over the full knowledge base (unless admin offers Track B separately)
- Ability to add or change source channels
- Web catalog (not shipped in Wave 1)

---

## Giving feedback (Wave 1.5)

Send informal messages to your admin, for example:

- «Digest was useful / too short / missed topic X»
- «I'd like to click through to the original posts»
- «Wrong language or timezone»
- «Didn't receive anything after 48h»

No surveys or forms — free text is enough.

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| No posts after 48h | Confirm schedule with admin; channel may be new |
| `/start` — not registered (C2) | Admin must `register_user` + telegram auth first |
| Bot blocked | Unblock bot, `/start` again |
| Want deeper exploration | Ask admin about Track B (MCP curator access) |

Technical reference for operators: [USER_GUIDE.md](../USER_GUIDE.md) § Scheduled Digests (F6).
