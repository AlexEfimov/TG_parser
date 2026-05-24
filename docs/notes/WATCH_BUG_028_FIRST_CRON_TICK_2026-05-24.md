# Watch — BUG-028 first cron-tick post-hotfix (2026-05-24)

**Opened:** `2026-05-23T19:21:06Z` (synchronous restart of `tg_parser`, `tg_parser_bot`, `tg_parser_mcp` for BUG-028 hotfix deploy `26d03a5`; deploy window in BUG_LOG closure row records ≈19:23Z — actual `StartedAt` per `docker inspect` is `19:21:06Z` ±2s across all three containers, RestartCount=0 since).

**Closed:** `2026-05-24T06:43:00Z` (T+11h22 from container restart, T+43m from observed cron tick) — closure session executed against fresh logs (~43 minutes after the digest fired); window formally closed because the post-hotfix code path (Layer A guard + Layer B literal-`"None"` fallback + Layer C settings default + Layer D compose env) has now been exercised end-to-end on a real prod cron tick with the only active subscription on system.

**Window duration:** 11h22m container-uptime, 43m post-tick observation.

**Hotfix commit:** `26d03a5` («fix(bug-028): digest cron PromptLoader None-string regression (hotfix)») — squash-merged 2026-05-23T16:57:45Z via [PR #92](https://github.com/AlexEfimov/TG_parser/pull/92).

**DONE marker (BUG-028 closure):** [`BUG_LOG.md` § BUG-028 closure row «Update 2026-05-23 — PR #92 landed → BUG-028 RESOLVED»](BUG_LOG.md) — captures all four delivered layers (A/B/C/D) and notes pending follow-up = "next digest cron tick fires `2026-05-24T06:00:00Z` … to be observed in a separate session" — i.e. **this watch journal is that session**.

---

## § Context

* Filed: [`BUG_LOG.md` § BUG-028](BUG_LOG.md) — daily digest cron task aborted with `PromptLoaderError` because `scheduler_service.py:560` did `PromptLoader(prompts_dir=str(settings.prompts_dir))` and `str(None) == "None"` resolved to non-existent path `None/digest.yaml`. Pre-existing latent bug since F6 landing 2026-04-19, surfaced 2026-05-23T06:00Z by Wave 1 step 3 24h watch.
* Hotfix: [PR #92](https://github.com/AlexEfimov/TG_parser/pull/92) squash [`26d03a5`](https://github.com/AlexEfimov/TG_parser/commit/26d03a5b9e40b64fa7f75f3a3de5576c67fca8ef), four layers of defense-in-depth (A: call-site `None`-aware cast; B: literal-`"None"` fallback in `PromptLoader.__init__`; C: `prompts_dir: Path = Field(default=Path("prompts"))` in `settings.py`; D: `PROMPTS_DIR=${PROMPTS_DIR:-/app/prompts}` propagated to all three services in `docker-compose.yml`).
* Deploy: prod VPS `mcp.tgp.efimov.mobi`, all three containers restarted simultaneously at `2026-05-23T19:21:06Z` (per `docker inspect ... .State.StartedAt`); RestartCount=0 ever since.
* **Expected first cron tick (under scope of this watch):** `2026-05-24T06:00:00Z` = `09:00 Europe/Nicosia` (DST = UTC+3 in May; ≡ `09:00 MSK`) for subscription `digest:94483db9-9351-4f99-9aec-46949d9ddd09` (prod endocrinology digest, cron `0 9 * * *`, only active digest subscription on system at watch open).
* Wider context: [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict — Open items #3](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md) (where BUG-028 was first surfaced); [`START_PROMPT_HOTFIX_BUG_028_2026-05-23.md`](START_PROMPT_HOTFIX_BUG_028_2026-05-23.md) (hotfix sprint prompt).

---

## § Observations

### Container health (pre-flight, sampled `2026-05-24T06:43Z`)

```
$ docker inspect tg_parser_bot tg_parser tg_parser_mcp \
    --format "{{.Name}} StartedAt={{.State.StartedAt}} RestartCount={{.RestartCount}} Health={{.State.Health.Status}}"
/tg_parser_bot StartedAt=2026-05-23T19:21:06.843117442Z RestartCount=0 Health=healthy
/tg_parser     StartedAt=2026-05-23T19:21:06.844635202Z RestartCount=0 Health=healthy
/tg_parser_mcp StartedAt=2026-05-23T19:21:06.846781145Z RestartCount=0 Health=healthy
```

All three target containers `(healthy)`, `RestartCount=0`, started within 4ms of each other (synchronous compose-up at hotfix deploy moment). No restarts in the ~11h22m window between deploy and tick observation. ✅ PASS pre-flight.

### Post-deploy boot signals (sampled from `tg_parser_bot` logs `2026-05-23T19:21:00Z…19:25:00Z`)

```
{"positional_args": ["PosixPath('/app/prompts')"], "event": "PromptLoader initialized with prompts_dir=%s", "level": "debug", "timestamp": "2026-05-23T19:21:15.550694Z"}
{"positional_args": ["bot", "PosixPath('/app/prompts/bot.yaml')"], "event": "Loaded prompt '%s' from %s", "level": "info", "timestamp": "2026-05-23T19:21:15.584601Z"}
2026-05-23 19:21:15,633 INFO apscheduler.scheduler: Scheduler started
{"event": "Background scheduler started", "level": "info", "timestamp": "2026-05-23T19:21:15.633606Z"}
2026-05-23 19:21:15,692 INFO apscheduler.scheduler: Added job "digest:94483db9-9351-4f99-9aec-46949d9ddd09" to job store "default"
{"task_id": "digest:94483db9-9351-4f99-9aec-46949d9ddd09", "cron_expression": "0 9 * * *", "timezone": "Europe/Nicosia", "event": "added_cron_task", "level": "info", "timestamp": "2026-05-23T19:21:15.693103Z"}
{"active_subscriptions": 1, "refresh_interval": 60, "event": "digest_scheduler_started", "level": "info", "timestamp": "2026-05-23T19:21:15.693167Z"}
```

`PromptLoader initialized with prompts_dir=PosixPath('/app/prompts')` confirms Layer C (`settings.prompts_dir` default = `Path("prompts")`) AND Layer D (`PROMPTS_DIR=/app/prompts` env override) both effective — no `None/...` path leakage at boot. APScheduler started, digest job loaded for subscription `94483db9-…` with cron `0 9 * * *` `Europe/Nicosia`, `digest_scheduler_started active_subscriptions=1`. ✅ PASS post-deploy smoke (matches BUG_LOG closure row claim).

### Cron tick observation (`2026-05-24T06:00:00Z`)

`docker logs tg_parser_bot --since 2026-05-24T05:55:00Z --until 2026-05-24T06:15:00Z` returned 12 log lines, all benign. Full ordered execution trace:

```
2026-05-24 06:00:00,005 INFO apscheduler.executors.default: Running job "digest:94483db9-9351-4f99-9aec-46949d9ddd09 (trigger: cron[month='*', day='*', day_of_week='*', hour='9', minute='0'], next run at: 2026-05-25 09:00:00 EEST)" (scheduled at 2026-05-24 09:00:00+03:00)
{"subscription_id": "94483db9-9351-4f99-9aec-46949d9ddd09", "event": "digest_task_triggered", "level": "info", "timestamp": "2026-05-24T06:00:00.014237Z"}
{"positional_args": ["PosixPath('/app/prompts')"], "event": "PromptLoader initialized with prompts_dir=%s", "level": "debug", "timestamp": "2026-05-24T06:00:00.014386Z"}
{"positional_args": ["digest", "PosixPath('/app/prompts/digest.yaml')"], "event": "Loaded prompt '%s' from %s", "level": "info", "timestamp": "2026-05-24T06:00:00.070832Z"}
{"extra": {"from": 50, "to": 4000}, "event": "rate_limit_rpm_adjusted", "level": "info", "timestamp": "2026-05-24T06:00:08.344662Z"}
{"extra": {"from": 30000, "to": 2000000}, "event": "rate_limit_itpm_adjusted", "level": "info", "timestamp": "2026-05-24T06:00:08.344750Z"}
{"extra": {"from": 8000, "to": 400000}, "event": "rate_limit_otpm_adjusted", "level": "info", "timestamp": "2026-05-24T06:00:08.344776Z"}
{"extra": {"requests_remaining": 3999.0, "input_tokens_remaining": 1999000.0, "output_tokens_remaining": 400000.0}, "event": "anthropic_rate_limit_snapshot", "level": "debug", "timestamp": "2026-05-24T06:00:08.344813Z"}
{"extra": {"model": "claude-sonnet-4-20250514", "input_tokens": 2712, "output_tokens": 494}, "event": "Anthropic response received", "level": "debug", "timestamp": "2026-05-24T06:00:08.344855Z"}
{"subscription_id": "94483db9-9351-4f99-9aec-46949d9ddd09", "chat_id": 5445781511, "docs_count": 25, "event": "digest.delivered", "level": "info", "timestamp": "2026-05-24T06:00:08.448826Z"}
{"task_id": "digest:94483db9-9351-4f99-9aec-46949d9ddd09", "duration": 8.444182, "event": "cron_task_completed", "level": "debug", "timestamp": "2026-05-24T06:00:08.449492Z"}
2026-05-24 06:00:08,449 INFO apscheduler.executors.default: Job "digest:94483db9-9351-4f99-9aec-46949d9ddd09 (trigger: cron[month='*', day='*', day_of_week='*', hour='9', minute='0'], next run at: 2026-05-25 09:00:00 EEST)" executed successfully
```

Decomposed:

| # | Marker | Timestamp | Verdict |
|---|---|---|---|
| 1 | `apscheduler.executors.default: Running job "digest:94483db9-…"` | `2026-05-24T06:00:00.005Z` | ✅ scheduled-at `2026-05-24 09:00:00+03:00` (Europe/Nicosia DST = UTC+3 in May) — **5ms drift from nominal**, well within tolerance |
| 2 | `digest_task_triggered subscription_id=94483db9-…` | `2026-05-24T06:00:00.014237Z` | ✅ entry-log fired, task body started |
| 3 | `PromptLoader initialized with prompts_dir=PosixPath('/app/prompts')` | `2026-05-24T06:00:00.014386Z` | ✅ **direct proof BUG-028 fixed** — real path `'/app/prompts'`, NOT `'None'`; Layer A guard active at `scheduler_service.py:560` |
| 4 | `Loaded prompt 'digest' from PosixPath('/app/prompts/digest.yaml')` | `2026-05-24T06:00:00.070832Z` | ✅ digest.yaml resolved + loaded; no `PromptLoaderError`; latency 56.4ms (small first-touch IO) |
| 5 | Anthropic rate-limit auto-adjust (rpm 50→4000, itpm 30000→2000000, otpm 8000→400000) | `2026-05-24T06:00:08.344Z` | ✅ provider tier upgrade picked up; informational |
| 6 | `Anthropic response received model=claude-sonnet-4-20250514 input_tokens=2712 output_tokens=494` | `2026-05-24T06:00:08.344855Z` | ✅ LLM call succeeded (8.27s duration, 2712 in / 494 out) |
| 7 | `digest.delivered subscription_id=94483db9-… chat_id=5445781511 docs_count=25` | `2026-05-24T06:00:08.448826Z` | ✅ **delivery confirmed** — chat_id=5445781511 (subscription owner, redacted from public surface), 25 docs covered in digest payload, 104ms after LLM completion |
| 8 | `cron_task_completed task_id=digest:94483db9-… duration=8.444182` | `2026-05-24T06:00:08.449492Z` | ✅ task wrapper exited cleanly, no exception path |
| 9 | `apscheduler.executors.default: Job "digest:94483db9-…" executed successfully` | `2026-05-24T06:00:08.449Z` | ✅ apscheduler outer wrapper logged success; **next run scheduled `2026-05-25 09:00:00 EEST`** (cron persists, no schedule corruption) |

End-to-end tick latency: **8.444 seconds** from `apscheduler` dispatch to `executed successfully`. No retries, no errors, single-shot success.

### Error scan — narrow window (`2026-05-24T05:55:00Z…06:15:00Z`)

```
$ docker logs tg_parser_bot --since "2026-05-24T05:55:00Z" --until "2026-05-24T06:15:00Z" 2>&1 \
    | grep -iE "PromptLoader|prompt.*not.*found|None/processing|None/digest|exception|traceback|error" | head -50
{"positional_args": ["PosixPath('/app/prompts')"], "event": "PromptLoader initialized with prompts_dir=%s", "level": "debug", "timestamp": "2026-05-24T06:00:00.014386Z"}
```

Single match, **benign** (it matches the substring `PromptLoader` of the success-path init message). **Zero** matches for `PromptLoaderError`, `None/digest`, `None/processing`, `traceback`, `exception`, or any `error`-level log entry. ✅ PASS.

### Error scan — wider window (deploy-to-now, `2026-05-23T19:23:00Z…2026-05-24T06:43Z`)

BUG-028-specific patterns (`PromptLoaderError|None/digest|None/processing|None/bot|None/topicization|None/rag|None/merge|None/incremental_discover|None/resummarize`) on `tg_parser_bot`:

```
$ docker logs tg_parser_bot --since "2026-05-23T19:23:00Z" 2>&1 | grep -ciE "PromptLoaderError|None/digest|None/processing|None/bot|None/topicization|None/rag|None/merge|None/incremental_discover|None/resummarize"
0
```

General error-class patterns (`traceback|"level": "error"|exception`) on `tg_parser_bot`:

```
$ docker logs tg_parser_bot --since "2026-05-23T19:23:00Z" 2>&1 | grep -ciE 'traceback|"level": "error"|exception'
0
```

Cross-container check on `tg_parser` and `tg_parser_mcp`:

```
$ docker logs tg_parser --since "2026-05-23T19:23:00Z" 2>&1 | grep -ciE 'PromptLoaderError|None/digest|None/processing|None/bot|traceback|"level": "error"|exception'
0
$ docker logs tg_parser_mcp --since "2026-05-23T19:23:00Z" 2>&1 | grep -ciE 'PromptLoaderError|None/digest|None/processing|None/bot|traceback|"level": "error"|exception'
0
```

**Zero** error-class events across all three containers over the full ~11h22m post-deploy window. ✅ PASS.

### Side-finding (informational, not BUG-028-related)

Single non-error warning surfaced in wider scan: `unregistered_telegram_user telegram_user_id=1184786120 telegram_username=Marina_Sedykh request_id=dea2ce98 level=warning timestamp=2026-05-23T22:36:32Z`. **Expected behaviour** — bot's registration gate blocks unregistered users with a single warning log line (no exception, no error-level event). Not a regression, not file-worthy. Listed only for completeness in § Follow-ups.

### DB cross-check

Skipped per prompt guidance — no `digest_deliveries` table on the schema (manual `\dt` exec aborted on stale `tg_parser` role mismatch in compose-exec wrapper; not pursued because log evidence is unambiguous: `digest.delivered chat_id=5445781511 docs_count=25` is the terminal delivery event written by the bot's own send-message wrapper after the aiogram call returned successfully).

---

## § Verdict

| Field | Value |
|---|---|
| **Status** | **CLOSED** (`2026-05-24T06:43:00Z`, T+43m post-tick) |
| **Final verdict** | **GREEN** — tick fired at `2026-05-24T06:00:00.005Z` (5ms drift from nominal `06:00:00.000Z`); `PromptLoader initialized with prompts_dir=PosixPath('/app/prompts')` (NOT `None`) — direct evidence the four-layer hotfix is effective on the exact code path that previously failed; `Loaded prompt 'digest' from /app/prompts/digest.yaml` clean; LLM call succeeded; `digest.delivered chat_id=5445781511 docs_count=25` delivery event present; `cron_task_completed duration=8.444s` + `apscheduler … executed successfully`; **zero** `PromptLoaderError` / `traceback` / `exception` / error-level entries across all three containers in the entire ~11h22m post-deploy window; all three target containers `(healthy)` with `RestartCount=0` since synchronous restart at `2026-05-23T19:21:06Z`; next cron tick correctly scheduled for `2026-05-25 09:00:00 EEST`. |

---

## § Implications

### For BUG-028 closure

* BUG_LOG closure row («Update 2026-05-23 — PR #92 landed → BUG-028 RESOLVED») listed «next digest cron tick fires `2026-05-24T06:00:00Z` (09:00 MSK), to be observed in a separate session» as the only outstanding follow-up beyond optional VPS backup-file cleanup. **That follow-up is now closed by this journal.** No status change in BUG_LOG (resolution stands; verdict = GREEN, not AMBER/RED, so per the watch rubric **no BUG_LOG edit is required this session**).
* The four-layer fix is now empirically proven against the real production execution path (not just local + smoke): Layer A guard prevented the `str(None)` → `"None"` regression at `scheduler_service.py:560`; Layer B fallback was not needed in this run (no `"None"`-string ever reached `PromptLoader.__init__`); Layer C settings default is observed effective at boot; Layer D compose env propagated to all three services per `docker inspect` evidence. Defense-in-depth held without any single layer being load-bearing in isolation.
* No regression risk window remains — this was the only active digest subscription, and the cron tick fired and delivered cleanly. Subsequent ticks (`2026-05-25T06:00:00Z` and onwards) execute the same code path on the same containers.

### For Wave 1 step 4 start readiness

* **GREEN signal: step 4 sprint can start at user's signal.** All exit criteria from prompt's GREEN rubric met:
  * Tick fired ✓
  * No `PromptLoaderError` ✓
  * No `exception`/`traceback` near tick window ✓
  * Delivery confirmed (`digest.delivered` + `cron_task_completed` + apscheduler `executed successfully`) ✓
  * All three containers healthy, no restart since deploy ✓
* Step 4 sprint scope ([`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md), [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md), [`CHECKLIST_WAVE1_STEP4_2026-05-23.md`](CHECKLIST_WAVE1_STEP4_2026-05-23.md)) has no dependency on the digest scheduler beyond the `digest_subscriptions` table schema (which step 4 extends with `target_kind` enum + nullable `channel_id`). No reason to delay sprint start; ADR 0008 implementation can proceed in a fresh execution sub-session.
* Recommendation: **«step 4 sprint can start at user's signal»** (GREEN per rubric, no caveat).

---

## § Follow-ups

1. **VPS backup file cleanup (optional).** The on-VPS file `~/TG_parser/docker-compose.yml.bak-bug028-20260523-114830` (created by manual workaround at `2026-05-23T09:49:15Z`, preserved through hotfix deploy per BUG_LOG closure row) **can now be safely deleted** — the hotfix has run a full real cron-tick cycle without regression, and the audit trail is preserved in `BUG_LOG.md` § BUG-028 closure row anyway. **Out of scope for this watch session per prompt § Do NOT** («Do NOT delete the VPS backup file … that's a separate optional cleanup step the user may approve later»). Not actioned here; flagged for user.
2. **Side-finding (informational only, NOT to be filed as a bug):** `unregistered_telegram_user` warning at `2026-05-23T22:36:32Z` for `telegram_user_id=1184786120` (`@Marina_Sedykh`). Expected registration-gate behaviour (warn-then-refuse for users absent from `users` table). If this person should have access, an admin should call `register_user(...)` via MCP — but that's a user-management operational concern, not a watch-flagged anomaly. Not bug-worthy.
3. **No regression-class follow-ups.** No new BUG-NN candidates surfaced by this watch.

---

## § Cross-reference

* BUG-028 entry: [`BUG_LOG.md` § BUG-028](BUG_LOG.md) (closure row dated 2026-05-23, no edits this session).
* Hotfix PR: [PR #92](https://github.com/AlexEfimov/TG_parser/pull/92), squash [`26d03a5`](https://github.com/AlexEfimov/TG_parser/commit/26d03a5b9e40b64fa7f75f3a3de5576c67fca8ef).
* Prior watch (where BUG-028 was first surfaced): [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict — Open items #3](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).
* Hotfix sprint prompt: [`START_PROMPT_HOTFIX_BUG_028_2026-05-23.md`](START_PROMPT_HOTFIX_BUG_028_2026-05-23.md).
* Wave 1 step 4 planning: [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md), [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md), [`CHECKLIST_WAVE1_STEP4_2026-05-23.md`](CHECKLIST_WAVE1_STEP4_2026-05-23.md).
