# MCP Connect — Track B (Curator)

**Version:** 4.4.0 | **Audience:** hosted MCP validators (own channels)

Connect Cursor, Claude Desktop, or Claude Code to a TG_parser MCP server, add your first channel, and run a smoke test.

**Prerequisites:** MCP bearer token from admin (sent out-of-band). Replace `{MCP_URL}` with the URL from your onboarding message (e.g. `https://mcp.example.com/mcp`).

---

## 1. Configure your client

### Cursor

Add to `.cursor/mcp.json` (project) or global MCP settings:

```json
{
  "mcpServers": {
    "tg-parser": {
      "url": "{MCP_URL}",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

Restart Cursor or reload MCP servers.

### Claude Desktop (remote HTTP)

Settings → Connectors → Add:

- **URL:** `{MCP_URL}`
- **Auth:** Bearer token `YOUR_MCP_TOKEN`

### Claude Code

```bash
claude mcp add --transport http tg-parser {MCP_URL} \
  --header "Authorization: Bearer YOUR_MCP_TOKEN"
```

### Other clients

See [mcp-clients-compatibility.md](../mcp-clients-compatibility.md) for ChatGPT, Gemini, Windsurf, VS Code Copilot.

---

## 2. Smoke test — connection

Ask your AI assistant to call MCP tools (or use an MCP inspector):

```
whoami
```

Expected: your user name, role `user`, `max_channels` (typically 3).

```
list_channels
```

Expected: empty list or only channels you previously added.

If `401 Unauthorized`: wrong token or `MCP_AUTH_ENABLED` not configured on server — contact admin.

---

## 3. Add your first channel

```
add_channel(channel_id="@public_channel_username")
```

Or a numeric id: `add_channel(channel_id="-1001234567890")`.

### Telethon caveat (hosted instances)

Ingestion runs through the **server's** Telegram account, not yours.

- **Works:** public channels; channels the server account has joined.
- **Fails:** private channels where the server account is not a member.

Start with one small **public** channel for the fastest cold start.

---

## 4. Wait for processing (cold start)

After `add_channel`, documents are not searchable until the pipeline ingests and processes messages.

**Monitor progress:**

```
get_pipeline_status(channel_id="@public_channel_username")
```

Wait until `last_success_at` is non-null (often 5–30 minutes on first run). Optionally ask admin to call `trigger_pipeline` for your channel to speed this up.

**What happens between add and ask:**

1. Scheduler (or manual trigger) fetches Telegram messages (ingestion).
2. LLM processing extracts structured documents.
3. Topicization and embeddings run.
4. Then `ask_question` / `search_knowledge_base` return results.

---

## 5. Smoke test — query

```
ask_question(question="What are the main topics discussed in this channel?")
```

Or:

```
search_knowledge_base(query="recent announcements", mode="hybrid")
```

If empty results immediately after `add_channel`, pipeline is not finished — recheck `get_pipeline_status`.

---

## 6. Optional next steps

| Tool | Purpose |
|------|---------|
| `list_topics` | Browse auto-clustered topics |
| `subscribe_watchlist` | Alerts when new content matches keywords |
| `subscribe_digest` | Scheduled summary — **only your own** `channel_ids` |
| `create_workspace` | Group channels thematically |

You **cannot** subscribe to digest or search over channels you do not own.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| 401 on all tools | Invalid/expired token | Ask admin for new token |
| `add_channel` rejected, limit | `max_channels` reached | Remove a channel or ask admin to raise limit |
| Pipeline never succeeds | Private channel / Telethon access | Use a public channel |
| `ask_question` empty | Cold start not complete | `get_pipeline_status` → wait or `trigger_pipeline` |
| MCP tools not visible in Cursor | Config path / reload | Check `mcp.json`, restart Cursor |

More detail: [USER_GUIDE.md](../USER_GUIDE.md) § Troubleshooting, [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md) § Connecting AI Agents.

---

## Feedback

Tell your admin what worked or frustrated you — free text is fine. Tag mentally as «MCP curator» (Track B) feedback.
