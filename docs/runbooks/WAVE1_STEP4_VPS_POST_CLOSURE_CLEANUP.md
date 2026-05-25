# Runbook — Wave 1 Step 4 VPS Watch Window: POST-CLOSURE CLEANUP

**Created:** 2026-05-25T06:22Z (pre-closure pre-flight session, ~4h before T+24h close at `2026-05-25T10:50:10Z`).

**Owner:** Alexander Efimov (operator) + coordinator agent (cleanup orchestration).

**Purpose:** copy-paste-ready commands + step-by-step procedures for the **post-closure** cleanup phase of the Wave 1 Step 4 VPS watch window. **DO NOT EXECUTE ANY OF THESE PROCEDURES BEFORE T+24h NOMINAL CLOSE (`2026-05-25T10:50:10Z`).**

**Scope:** disables single-shot Cursor automations; documents manual UI cleanup of probe automations; documents Grafana credential rotation; documents Telegram-side cleanup choice; documents finalization of the DONE marker; documents optional commit message.

**Cross-references:**

* DONE marker draft: [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](../notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md).
* Cursor Automations registry: [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md).
* Watch window log: [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md).
* Handoff doc: [`docs/notes/HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md).

---

## ⚠️ Hard constraints

* **DO NOT EXECUTE BEFORE `2026-05-25T10:50:10Z`** (T+24h nominal close). `f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f` (T+24h closure reminder automation) fires AT this timestamp; disabling it pre-fire would suppress the reminder itself.
* All Cursor automation `update_automation` calls require an attached `cursor-backend-control` MCP server in the active session.
* All operator-manual steps (§ B, § C, § D) require Cursor UI or SSH access — they CANNOT be automated from this agent session because (a) Cursor UI has no DELETE-automation MCP tool, only `update_automation` (which can disable but not remove); (b) Grafana password rotation requires SSH + container restart; (c) Telegram-side decisions are operator-discretion.
* Section § E (finalize DONE marker) edits a document under `docs/notes/`, which IS within agent-write scope — but must be executed by the **closure session**, not this pre-flight session, because the closure timestamp is unknown until 10:50Z.
* Section § F (git commit) is **operator-explicit-request gated** per project AGENTS.md «Forbidden actions: `git commit` без явного запроса пользователя».

---

## A. Disable single-shot Cursor automations

Both automations below are single-shot (cron with year+month+day pinned) — they have either already fired by closure time (`2bd25769`) or fire exactly at closure time (`f93e557a`). After closure they are dead weight in the automations list and should be disabled (not deleted — disabling preserves audit trail in `WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`).

### A.1 `2bd25769-52b1-4525-a0c5-239d589d231f` — P0-4 verifier (fired at `2026-05-25T06:05Z`)

**Status check before disable** (optional sanity): `get_automation({automationId: "2bd25769-52b1-4525-a0c5-239d589d231f"})` to confirm it indeed fired and produced expected output (silent if GREEN; opened GitHub issue if assertion failed).

**Disable call:**

```json
{
  "server": "cursor-backend-control",
  "toolName": "update_automation",
  "arguments": {
    "automationId": "2bd25769-52b1-4525-a0c5-239d589d231f",
    "enabled": false
  }
}
```

**Verify:** schema for the tool is at `/Users/alexanderefimov/.cursor/projects/Users-alexanderefimov-TG-parser/mcps/cursor-backend-control/tools/update_automation.json` — confirms `automationId` (required, string) + `enabled` (optional, boolean) shape, no other required args; `additionalProperties: false`; does NOT require `workflow` or `replaceWorkflow` when only flipping the `enabled` flag.

### A.2 `f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f` — T+24h closure reminder (fires AT `2026-05-25T10:50Z`)

**Timing constraint:** disable ONLY after this automation has fired its closure reminder (i.e. AFTER `2026-05-25T10:50:10Z`). Disabling before fire would suppress the reminder, defeating the automation's purpose. If the closure session starts well after 10:50Z (e.g. operator delayed to 11:30Z), this automation has already fired by then — safe to disable immediately at session start.

**Disable call:**

```json
{
  "server": "cursor-backend-control",
  "toolName": "update_automation",
  "arguments": {
    "automationId": "f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f",
    "enabled": false
  }
}
```

### A.3 `7b35ca01-a7d1-4c3a-bb8b-940918e506d6` — Grafana webhook ingress automation

**DO NOT disable yet.** This automation is the Grafana → GitHub-issue webhook ingress; it is the active monitoring path for `tg_api_5xx_spike` / `tg_parser_bot_down` / `tg_parser_api_down` alerts and remains useful AFTER this watch window. The known instability described in BUG-037 (inconsistent title-prefix routing) is a Step 5 fix candidate, not a reason to disable the whole automation. **Leave enabled.**

---

## B. Delete 7 `[DELETE_ME] schema-probe-*` automations (operator-manual, Cursor UI)

**Background:** during the pre-deploy `create_automation` schema-discovery process (see [`WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md` § 0 «Discovered canonical workflow schema»](WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md)), the operator/agent created ~7 probe automations to reverse-engineer the protobuf payload shape from the validation error messages. Each was named with the `[DELETE_ME] schema-probe-*` prefix per a self-imposed naming convention so they are easily identifiable. **They have no scheduled triggers (cron set to obviously-past dates) and no actions** — they are inert, but they pollute the automations list and should be removed.

**Why operator-manual:** the `cursor-backend-control` MCP exposes only `list_automations`, `get_automation`, `create_automation`, `update_automation`, `build_automation_prefill_url` — **no `delete_automation` tool**. Deletion is only possible via the Cursor UI per Cursor's current automations API surface.

**Step-by-step:**

1. Open Cursor desktop app.
2. Open the Automations panel (Settings → Automations, or via `cursor_dialog` MCP if exposed — TBD; for now operator-manual).
3. For each automation whose name starts with `[DELETE_ME] schema-probe-` (expected count: 7 total per handoff doc — verify count matches):
   1. Tap the automation row.
   2. Open the actions menu (⋯ / kebab / context-menu icon).
   3. Select «Delete».
   4. Confirm deletion in the modal.
4. After completing all 7 deletions: confirm zero `[DELETE_ME] schema-probe-*` automations remain via `list_automations` call (filter results by name prefix).

**Verification call** (after manual deletes):

```json
{
  "server": "cursor-backend-control",
  "toolName": "list_automations",
  "arguments": {}
}
```

Then scan the returned list for any name starting with `[DELETE_ME] schema-probe-`. **Expected result: 0 matches.**

---

## C. Rotate Grafana admin password (operator-manual, VPS SSH)

**Background:** during the 2026-05-24 deploy verification, the operator transcript passed `GRAFANA_ADMIN_PASSWORD` plaintext via chat for emergency dashboard access. Per standard credential-hygiene protocol, rotate this credential post-closure to invalidate any captured value.

**Step-by-step:**

1. **SSH to VPS:**

   ```bash
   ssh -p 2296 user@212.72.189.15
   # host alias: redboxtgbot
   ```

2. **Locate env file:**

   ```bash
   cd ~/TG_parser
   ls -la .env  # or compose-specific env file if separate
   ```

3. **Generate new password** (cryptographically strong):

   ```bash
   openssl rand -base64 24
   ```

4. **Update `.env`** — replace `GRAFANA_ADMIN_PASSWORD=<old>` with the new value (use `${EDITOR:-vi}` or `nano`):

   ```bash
   # WARNING: do not echo the new password to history.
   ${EDITOR:-vi} .env
   # find line: GRAFANA_ADMIN_PASSWORD=<...>
   # replace with new value
   # save and exit
   ```

5. **Restart Grafana container** (env-only change, no rebuild needed):

   ```bash
   docker compose --profile observability up -d --no-deps grafana
   # OR: docker compose restart grafana  (if compose recognizes the env change without recreate)
   ```

6. **Verify new login:**

   ```bash
   # From operator laptop (not VPS):
   curl -u "admin:<new_password>" https://grafana.tgp.efimov.mobi/api/health
   # Expected: {"database":"ok","version":"X.Y.Z","commit":"..."}
   ```

7. **Document rotation** — record rotation timestamp in a secure operator-private log (NOT in this repo). Do NOT commit the new password to the repo even encrypted; per repo convention `.env` is gitignored.

**Rollback** (if Grafana fails to start with new password): restore `.env` from a pre-rotation backup (`cp .env.bak-grafana-rotate .env`) and re-run step 5.

---

## D. Cleanup Telegram side (optional, operator decision)

**Created during watch:**

* `@vps_watch_test_r1_Alex` — operator-owned channel; `@Tgingest_bot` was admin with «Post Messages» right.
* `@vps_watch_test_r2_Alex` — operator-owned channel; `@Tgingest_bot` was NOT a member (used for Test B permission-denied path).
* `vps-watch-test-grp` (basic group, chat_id `-5279672667`) — `@Tgingest_bot` promoted to admin to bypass aiogram privacy mode for Test D.

**Operator-discretion decisions:**

| Decision | Rationale | Recommended default |
|---|---|---|
| **Keep R-1 / R-2 / `vps-watch-test-grp`** | Reusable for future Wave 1 step N or Wave 2 watch windows; saves recreate-time + re-grant-admin-rights friction. Channels are operator-owned and non-public — no leak / SEO concern. | ✅ **KEEP (default).** |
| **Delete all three** | Maintenance hygiene; reduces operator's «orphan-test-artifacts» count. | ⚠️ Only if operator has explicit clean-account preference. |
| **Demote `@Tgingest_bot` from admin in `vps-watch-test-grp`** | Privacy mode re-engages; bot will no longer respond to free-text NL prompts in this group. Doesn't affect future re-promote if needed. | ✅ **DEMOTE if KEEP** — restores bot's default privacy posture and reduces surface for accidental NL processing of unrelated group messages. |
| **Delete subscription `digest_94483db9-9351-4f99-9aec-46949d9ddd09`** | This is the **REAL** prod endocrinology digest for the real user. **NEVER DELETE.** | ❌ **DO NOT DELETE.** |

**If choosing to delete R-1 / R-2 / group:** standard Telegram UI flow (channel Settings → Delete Channel; group Settings → Delete Group). No DB-side cleanup needed (subscriptions targeting these chats were already hard-deleted via `unsubscribe_digest` during OP-2 / OP-3 test cleanup at ~21:00 UTC 2026-05-24; verified via MCP `list_digests` at this pre-flight session — only `digest_94483db9` remains).

---

## E. Finalize `REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`

**Edit by closure session** (NOT by this pre-flight session — the closure timestamp is unknown until 10:50Z).

**Action:** open [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](../notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) and find every occurrence of `<to be filled in by closure session at 2026-05-25T10:50Z>`. Replace with the actual closure timestamp in ISO 8601 UTC format, e.g. `2026-05-25T10:50:42Z`.

**Expected occurrences:** 2 (one in § Header metadata block at the top, one in § 10 Sign-off block).

**Verification grep before sign-off:**

```bash
rg "to be filled" docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md
# Expected: no matches after edit complete
```

**Additional closure-session edits per § 10 «Closure session checklist» of the DONE marker:**

1. Re-run MCP `list_digests` and verify `digest_94483db9.last_sent_at` is still the 2026-05-25T06:00:05Z tick (or the next `2026-05-26T06:00Z` tick if closure runs late — both indicate scheduler health).
2. If any new BUG surfaced between 06:22Z (this pre-flight) and the closure timestamp, add it to § 5 and § 8 of the DONE marker before sign-off.

---

## F. Git commit (operator-explicit-request gated)

**Per project AGENTS.md:** «`git commit` без явного запроса пользователя» is a **forbidden action**. The agent does NOT commit anything during this watch closure unless the operator explicitly says «commit» (or equivalent).

**If the operator requests a commit**, suggested commit message (HEREDOC for correct formatting):

```bash
git add docs/notes/BUG_LOG.md \
        docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md \
        docs/notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-24.md \
        docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md \
        docs/notes/HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md \
        docs/runbooks/WAVE1_STEP4_VPS_OP2_OP3_INTERACTIVE_TESTS.md \
        docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md \
        docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md \
        docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md \
        docs/runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md \
        docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md \
        backups/pre_step4_backup_20260524T094610Z.sql

git commit -m "$(cat <<'EOF'
docs(wave1-step4): watch window closure 2026-05-24 → 2026-05-25 — review + BUGS-029..037 + OBS-001 + DOC-001

Closure of Wave 1 Step 4 (PR #93, commit 926a165, alembic head a8b7c6d5e4f3) VPS
24h watch window. Verdict: PASS-WITH-CAVEATS — closure criteria C-1 / C-2
materialized via OP-2 / OP-3 interactive tests (channel-publish success +
permission_denied paths); C-3 untested but structurally registered. Bot prompt
v1.7.0 target_kind_semantics verified on disambiguation (Tests C+D), partial
on payload (BUG-033 placeholder leak + BUG-034 NL typo misparse in Test D).

New entries in BUG_LOG.md:
  * BUG-029 (Medium) — digest_service.subscribe_digest race-retry missing
    session.rollback() (stub filed retroactively per OA-7).
  * BUG-030 (Medium) — bot _start_digest_scheduler initial-load fragile to
    Postgres startup race (stub filed retroactively per OA-8).
  * BUG-031 (Severe) — bot creates digest sub BEFORE user confirms.
  * BUG-032 (Medium) — bot does not parse «да» / «подтверждаю» tokens.
  * BUG-033 (Critical) — bot in group context inserts chat_id=123 placeholder
    instead of Message.chat.id.
  * BUG-034 (Medium) — channel-name parser fails on typo with whitespace.
  * BUG-035 (Critical) — unsubscribe_digest leaves orphan APScheduler job;
    empirically BOUNDED_1FIRE confirmed post-watch.
  * BUG-036 (Low) — Grafana alert-rule noData UI-state drift; not provisioned-as-code.
  * BUG-037 (Low) — Cursor webhook automation classifier title-prefix instability.
  * OBS-001 — watchlist matcher last_checked_at stagnation; needs investigation.
  * DOC-001 — stale @smoke_tgparser_bot reference; should be @Tgingest_bot.

REVIEW marker finalized; post-closure cleanup runbook added.
EOF
)"
```

**NB:** the staged-files list above includes documents that may have been edited across multiple watch sessions (the originally-untracked ones from `git status` at pre-flight) — operator should review `git status` + `git diff` before committing and prune the `git add` list to only files actually intended for this commit. The HEREDOC commit message above documents the conceptual scope; the file list is a suggested superset.

---

## End of runbook
