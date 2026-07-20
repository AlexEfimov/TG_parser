# BUG-008 recurrence checklist — MCP read-tool hang

> Short runbook when Cursor / MCP client appears to hang on a read tool (classic: `list_channels`).  
> Source of truth for status/mitigation: [`BUG_LOG.md`](BUG_LOG.md) **BUG-008** (esp. **Update 2026-06-14**).  
> Status of BUG-008 stays `open` until a reproduced occurrence is diagnosed.

**Terminology:** use **transport/client** (BUG-008 decision rule). Do **not** label this path «H3» — in BUG_LOG, H3 means other things; transport candidates under BUG-008 are **HG-2 / HG-4**.

---

## Checklist

### 1. Reproduce?

- [ ] Retry the hung tool **N×** (e.g. 5–10× consecutive `list_channels` via MCP).
- [ ] Note: hang is historically **flaky**; a single miss does not close the bug.

### 2. Server lifecycle logs

```bash
ssh prod   # see docs/runbooks/CURSOR_CLOUD_PROD_SSH.md
docker logs tg_parser_mcp --since 30m 2>&1 | rg 'mcp\.(request|tool)\.'
```

Look for the request’s chain:

| Event | Meaning |
|---|---|
| `mcp.request.received` | ASGI saw the request |
| `mcp.tool.start` → `mcp.tool.end` | Handler finished (guard path) |
| `mcp.tool.timeout` | `guard_read_tool` hit `mcp_read_tool_timeout` (default 180s) |
| `mcp.request.response_sent` | Server wrote the HTTP/SSE response |

### 3. Decision rule (BUG-008 Update 2026-06-14)

| Observation | Conclusion | Action |
|---|---|---|
| `mcp.request.response_sent` **fired** but client still hung | **transport/client** layer | Fix = request timeout in **Cursor MCP client** (outside this repo). Do **not** “fix” client timeout here. |
| `mcp.tool.end` **never** fired (and no `mcp.tool.timeout`) | **server stall** | Inspect Postgres: `pg_stat_activity` / `pg_locks` on `tg_parser_postgres`. |
| `mcp.tool.timeout` fired | Server bound the hang | Treat as diagnosable server-side slow/stuck path; still correlate with DB locks. |

Mitigation already in tree: `guard_read_tool` + `_RequestLifecycleMiddleware` in `tg_parser/mcp_server.py`. Tests: `tests/test_mcp_server.py::TestReadToolTimeoutGuard`.

### 4. Fallback (admin read-only)

If MCP is unusable and you need the data now:

```bash
ssh prod
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c \
  "SELECT channel_id, status FROM sources ORDER BY channel_id LIMIT 50;"
```

(Adjust SQL to the hung tool’s intent. Direct SQL during the original incident returned in &lt; 1s.)

### 5. Do **not**

- [ ] Patch this repo to “fix Cursor MCP client timeout” — that lives **outside** the codebase.
- [ ] Close BUG-008 without a log-backed diagnosis from a reproduced occurrence.
- [ ] Confuse this checklist’s **transport/client** outcome with unrelated BUG_LOG «H3» labels.

---

## Optional ops pointer

Prod SSH setup: [`../runbooks/CURSOR_CLOUD_PROD_SSH.md`](../runbooks/CURSOR_CLOUD_PROD_SSH.md).
