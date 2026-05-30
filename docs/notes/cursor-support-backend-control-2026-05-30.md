# Cursor Support Ticket — `cursor-backend-control` not registered at runtime

**Дата:** 2026-05-30
**Связанная заметка:** [`cursor-automations-app-control-workaround.md`](cursor-automations-app-control-workaround.md)

Поддержка Cursor работает на английском — основной текст ниже на английском, в конце краткая русская версия и способы отправки.

---

## Support ticket (EN) — ready to send

**Subject:** Managed MCP server `cursor-backend-control` is declared but not registered at runtime (`MCP server does not exist`)

**Severity:** Blocking — cannot use Cursor Automations programmatically via MCP.

**Environment:**
- Cursor version: **3.6.21**
- OS: macOS (darwin 25.2.0)
- Privacy Mode: `PRIVACY_MODE_NO_TRAINING` (storage-eligible)

**Steps to reproduce:**
1. Open an agent chat in Cursor 3.6.21 (macOS) with the managed MCP servers active.
2. Confirm `cursor-backend-control` is advertised in the agent's tool context (tool descriptions for `list_automations` etc. are visible).
3. Have the agent call any `cursor-backend-control` tool (e.g. `list_automations` with `{}`).
4. Observe the immediate error `MCP server does not exist: cursor-backend-control` — the server is absent from the runtime "Available servers" list.
5. For contrast, call `cursor-app-control` → `open_automation` with `{}`: it succeeds (`Opened Glass Automations`), proving other managed servers register normally.

**Summary:**
The managed MCP server `cursor-backend-control` appears in the agent's static tool context (its tool descriptions are visible: `list_automations`, `get_automation`, `create_automation`, `update_automation`, `build_automation_prefill_url`), but it is **not registered in the runtime** of the agent session. Any call to it fails immediately with:

```
Error: MCP server does not exist: cursor-backend-control.
Available servers: cursor-app-control, cursor-ide-browser, project-0-TG_parser-tg-parser, user-Ref, user-tg-parser
```

Notably, the two **other managed servers** declared in the same context — `cursor-app-control` and `cursor-ide-browser` — **work fine**. `cursor-backend-control` is the only managed server missing from the runtime "Available servers" list.

**Expected behavior:**
`cursor-backend-control` tools (e.g. `list_automations`) should be callable, since the server is advertised in the tool context and the Automations feature itself is available.

**Actual behavior:**
The server is absent from the runtime registry; every call returns `MCP server does not exist`. This is **not** a permission/allowlist denial (the error is "does not exist", not "denied").

**What we verified / ruled out (all local causes excluded):**
1. `~/.cursor/permissions.json` — **does not exist**; no `mcpAllowlist` defined anywhere in `~/.cursor`.
2. Cursor hooks — no `hooks.json` and no `~/.cursor/hooks/` (global or project); no `beforeMCPExecution` / `failClosed` anywhere.
3. Not a permission-deny — error string is `MCP server does not exist`, not a block/deny.
4. **Restarting Cursor** — already tried, did not help.
5. Privacy Mode — `PRIVACY_MODE_NO_TRAINING` (storage-eligible; not `NO_STORAGE` / `UNSPECIFIED`), and `hasReconciledNewPrivacyModeWithServerOnUpgrade = true`, grace period = 0. Per the server's own docs, only `UNSPECIFIED` and `NO_STORAGE` block these tools — so privacy is not the cause.
6. Automations entitlement — the **Glass Automations UI opens successfully** via `cursor-app-control` → `open_automation`, so the Automations product itself is available to this account.

**Cross-check that proves the runtime is otherwise healthy:**
`cursor-app-control` → `open_automation` returns `Opened Glass Automations` successfully. So the managed-MCP invocation path works; only `cursor-backend-control` fails to instantiate.

**Conclusion / hypothesis:**
A registration defect for the `cursor-backend-control` managed MCP server specifically — its tool spec is shipped to the agent context, but the server is not actually instantiated/registered in the session runtime. This is independent of local configuration or account privacy settings.

**Request:**
1. Please confirm whether `cursor-backend-control` is expected to be enabled for this Cursor version/account, and what controls its runtime registration.
2. If it's a known rollout/version issue, advise the version where it's fixed.
3. If account/org-level gating applies, please indicate what setting governs it.

---

## Краткая версия (RU)

> Managed MCP-сервер `cursor-backend-control` виден в контексте инструментов агента (описания tools отображаются), но **не регистрируется в рантайме** сессии — вызов даёт `MCP server does not exist`. Два других managed-сервера (`cursor-app-control`, `cursor-ide-browser`) работают. Это **не** блокировка по правам (ошибка «не существует», не «denied»). Исключено: отсутствует `permissions.json`/`mcpAllowlist`; нет hooks; перезапуск Cursor не помог; Privacy Mode = `NO_TRAINING` (storage-eligible); фича Automations доступна (Glass Automations UI открывается). Версия Cursor 3.6.21, macOS. Похоже на дефект регистрации именно этого managed-сервера. Прошу подтвердить ожидаемую доступность и/или версию с исправлением.

---

## Как отправить

- В приложении: палитра команд → `Cursor: Report Issue`, либо Help → Report Issue.
- Форум: https://forum.cursor.com
- Почта: hi@cursor.com
