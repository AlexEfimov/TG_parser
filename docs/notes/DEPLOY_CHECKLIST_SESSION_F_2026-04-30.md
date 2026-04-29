# Deploy Checklist — Session F (PR #44)

**Created:** 2026-04-29 17:50 MSK (UTC+4) immediately after PR #44 opened.
**Target window:** 2026-04-30 ~16:00 MSK (after 11:49 UTC Session E watch closure).
**PR:** [#44](https://github.com/AlexEfimov/TG_parser/pull/44) `fix/read-hardening-bug-003-005b-007-2026-04-29`.
**Pre-deploy gate:** Session E 24h watch on `tg_bot_gemini_empty_parts_total` (closes **2026-04-30 11:49 UTC = 15:49 MSK**).

---

## Phase 0 — Watch closure verification (2026-04-30 ~15:49 MSK onward)

Don't proceed past this phase if any check fails. The whole point of waiting is
to confirm Session E (BUG-006 fix) is **stable** before stacking Session F on top.

### 0.1 Pull metric data from VPS Prometheus

```bash
# SSH to VPS first
ssh root@mcp.tgp.efimov.mobi

# Inside VPS — query Prometheus for the watch window
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=tg_bot_gemini_empty_parts_total' \
  | python3 -m json.tool
```

**Pass criteria:**
- `tg_bot_gemini_empty_parts_total` total count for the 24h window: **≤ 1% of total bot-Gemini calls**.
- No spike of `>5%` in any 1h bucket.
- No new `finish_reason` labels appeared (set is bounded to `{STOP, MAX_TOKENS, MALFORMED_FUNCTION_CALL, RECITATION, SAFETY, OTHER, none, no_candidates, blocked}`).

**Fail action:** STOP. Re-open BUG-006 investigation. Session F deploy delayed
until BUG-006 root-cause is re-confirmed (could be a regression, could be a
distinct second issue). **Do NOT** merge PR #44 until this is resolved — even
the typed-catch (BUG-005-B) change in `execute_tool` could confound the
empty-parts signal post-deploy.

### 0.2 Grafana visual check

```bash
# Open Grafana on VPS (over SSH tunnel if needed)
# URL: http://mcp.tgp.efimov.mobi:3000 (or http://localhost:3000 if tunneling)
# Dashboard: tg_parser bot health → Panel "Gemini empty-parts rate"
```

**Pass criteria:** Flat or near-zero line for the entire 24h window.

### 0.3 Bot transcript spot-check

```bash
ssh root@mcp.tgp.efimov.mobi 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -E "gemini_empty_parts|gemini_no_candidates|gemini_blocked|parts_empty"'
```

**Pass criteria:** No log lines OR very few isolated incidents (and each one
has a non-pathological `finishReason` like `STOP` with empty `parts` due to
content-policy edge cases).

---

## Phase 1 — PR review & merge (after 0.x passes)

### 1.1 CI checks

```bash
# Verify PR CI is green from local machine
gh pr checks 44
```

If CI is configured (likely currently no CI on the repo per past experience):
all checks must be ✅. If no CI: rely on local test results from PR description
(1975 default-mode passed, 2138 with all gates).

### 1.2 Self-review of the diff one more time

```bash
gh pr diff 44 | wc -l       # sanity-check size
gh pr diff 44 | head -50    # spot-check first hunk
```

### 1.3 Merge to main

**Strategy:** squash merge (matches Session C/D/E convention).

```bash
gh pr merge 44 --squash --delete-branch \
  --body "$(cat <<'EOF'
Refs: BUG_LOG.md BUG-003 + BUG-005-B + BUG-007, Session F.
Closes: BUG-003, BUG-005-B, BUG-007.
EOF
)"
```

**Capture the squash SHA:**

```bash
git fetch origin main
git log -1 --format='%H' origin/main
# → save this SHA, you need it for the deploy command and BUG_LOG closure
export SESSION_F_SHA=$(git log -1 --format='%H' origin/main)
echo "Session F merge SHA: $SESSION_F_SHA"
```

---

## Phase 2 — Production deploy on VPS

This phase mirrors the Session E deploy command exactly (proven on
2026-04-29 11:49 UTC, 3-container restart in <60 seconds).

### 2.1 SSH to VPS

```bash
ssh root@mcp.tgp.efimov.mobi
cd /root/TG_parser   # or wherever the repo lives — verify with `pwd`
```

### 2.2 Pull merged main

```bash
git fetch origin
git status                                # MUST be clean
git log -1 --format='%H %s'               # capture pre-deploy SHA
git pull --ff-only origin main
git log -1 --format='%H %s'               # MUST equal SESSION_F_SHA
```

**Fail action:** if pull is non-fast-forward, abort. Investigate divergence
before forcing.

### 2.3 Rebuild image

```bash
docker compose build tg_parser
# Capture new image digest
docker images tg_parser:latest --format '{{.ID}} {{.CreatedSince}} {{.Size}}'
docker inspect tg_parser:latest --format='{{index .RepoDigests 0}}' \
  || docker inspect tg_parser:latest --format='{{.Id}}'
```

### 2.4 Restart all 3 containers

```bash
docker compose up -d --no-deps --force-recreate tg_parser mcp tg_bot
```

### 2.5 Health-check the containers

```bash
# Wait up to 60s for healthy state
for i in {1..12}; do
  status=$(docker compose ps --format json | python3 -c '
import json, sys
for line in sys.stdin:
    if not line.strip(): continue
    c = json.loads(line)
    name = c.get("Name", c.get("Service"))
    health = c.get("Health", "?")
    state = c.get("State", "?")
    print(f"{name}: state={state} health={health}")
')
  echo "--- attempt $i ---"
  echo "$status"
  if echo "$status" | grep -qE "tg_(parser|bot|mcp).*health=healthy" && \
     ! echo "$status" | grep -qE "health=unhealthy|health=starting"; then
    echo "All healthy."
    break
  fi
  sleep 5
done
```

**Pass criteria:** All three containers (`tg_parser`, `tg_parser_mcp`,
`tg_parser_bot`) show `state=running health=healthy` within 60 seconds.

### 2.6 Verify new code is live

```bash
# Confirm Session F symbols are present in the running image
docker exec tg_parser python3 -c "
from tg_parser.utils.channel_id import normalize_channel_id
print('helper:', normalize_channel_id('@AgeManagement'))
assert normalize_channel_id('@AgeManagement') == 'AgeManagement'
assert normalize_channel_id(\"'test_channel'\") == 'test_channel'
assert normalize_channel_id(\"' @ch '\") == 'ch'   # self-review fix
print('OK')
"

docker exec tg_parser_bot python3 -c "
from tg_parser.bot.tools import _build_no_results_suggestion, execute_tool
import inspect
src = inspect.getsource(execute_tool)
assert 'error_class' in src, 'BUG-005-B typed catch not wired'
assert 'TimeoutError' in src
print('execute_tool typed-catch: OK')
print('_build_no_results_suggestion: OK')
"

docker exec tg_parser_mcp python3 -c "
from tg_parser.mcp_server import TopicListResult
fields = TopicListResult.model_fields
assert 'available_channel_ids' in fields, 'BUG-007 MCP field missing'
assert 'suggestion' in fields
print('TopicListResult extension: OK')
"
```

**Fail action:** if any assert raises, deploy didn't take. Roll back via
`git reset --hard <pre-deploy SHA>` + `docker compose build tg_parser` +
`up -d --force-recreate`. Investigate why pull/build skipped the change.

---

## Phase 3 — Manual smoke (post-deploy on VPS)

These mirror PR #44 body's "Manual smoke" section. **All four must pass before
declaring Session F closed.** Use the dev-Telegram-bot account.

### 3.1 BUG-003 — `@`-prefix normalization

**Action:** Send to bot →

```
Каковы основные темы канала @AgeManagement?
```

**Pass criteria:** Bot returns a real list of topics (not empty / not «не нашёл
тем»). Pre-fix this was the deterministic production trigger.

**Fail action:** STOP. Check container logs for `tool_validation_error`,
`tool_timeout`. Most likely cause: import path issue or `normalize_channel_id`
not wired to the read-tool.

### 3.2 BUG-007 — typo suggestion

**Action:** Send to bot →

```
Какие темы в канале AgeManagment?
```

(Note the typo: `AgeManagment` instead of `AgeManagement`.)

**Pass criteria:** Bot returns one of:
- "Возможно, имелся в виду 'AgeManagement'? (вы запросили 'AgeManagment')" + list of available channels.
- OR: a list of topics (if `AgeManagment` is the actual channel name — both spellings exist in production).

If neither — investigate `_build_no_results_suggestion` wiring.

### 3.3 BUG-005-B — typed exception preservation

**Synthetic test** — runbook § 5 step 4. We don't have a way to trigger this
via end-user phrasing, so use the dev path:

```bash
# On VPS — run a synthetic Python check that exercises execute_tool's
# typed-catch path with a mock executor
docker exec tg_parser_bot python3 -c "
import asyncio
from unittest.mock import patch, AsyncMock
from tg_parser.bot.tools import execute_tool
from tg_parser.auth.models import CurrentUser

admin = CurrentUser(id='admin', name='admin', role='admin', allowed_channel_ids=None, max_channels=100)

async def fake_executor(args, **_):
    raise ValueError('synthetic test message')

async def main():
    with patch.dict('tg_parser.bot.tools._TOOL_EXECUTORS', {'fake_test_tool': fake_executor}):
        result = await execute_tool('fake_test_tool', {}, current_user=admin)
    print('result:', result)
    assert result['error_class'] == 'ValueError'
    assert result['error'] == 'synthetic test message'
    print('OK')

asyncio.run(main())
"
```

**Pass criteria:** prints `OK` and `result` contains both `error_class` and
`error` with the verbatim synthetic message.

### 3.4 F-9 — 4 input variants for `test_channel`

**Action:** Send four messages to bot in sequence. Wait for each preview, then
**cancel** (don't confirm) — we just verify normalization, not actual deletion.

```
Удали канал test_channel
Удали канал @test_channel
Удали канал 'test_channel'
Удали канал "@test_channel"
```

**Pass criteria:** All four preview replies contain the canonical
`channel_id="test_channel"` (no `@`, no quotes). Cancel each preview with
«нет» / «cancel» so no actual delete fires.

**Fail action:** if any preview shows `channel_id='test_channel'` (with quotes)
or `@test_channel` (with @) — F-8 quote-strip didn't take. Roll back.

---

## Phase 4 — Post-deploy 24h watch

Same metric, but now starting fresh from the Session F deploy moment.

### 4.1 Watch start time

Record the deploy timestamp:

```bash
date -u "+%Y-%m-%d %H:%M:%S UTC"
# Expected ~2026-04-30 12:00-12:15 UTC
```

### 4.2 Watch end target

`+24h` from the timestamp above. Likely **2026-05-01 ~12:00 UTC = 15:00 MSK**.

### 4.3 What we watch

Same Prometheus counter as Session E:

```promql
# In Grafana — alert if exceeded:
sum(rate(tg_bot_gemini_empty_parts_total[5m]))
  / sum(rate(tg_bot_gemini_total[5m]))   # if a base counter exists; else use absolute
```

**Pass criteria:**
- 0 spikes above 5% in any 1h bucket.
- 24h average ≤ 1% (matches Session E SLO).
- No new error_class labels in `execute_tool` failures (i.e., we're not surprising the new typed-catch with unexpected exception types — visible via bot logs).

### 4.4 Sample queries to run during watch

These are **smoke probes** — not automated, just spot-checks:

```
# At watch start + 6h + 12h + 18h, run:
1. "темы канала @Lab4health"          (BUG-003 trigger)
2. "Какие темы в канале AgeManagment" (BUG-007 typo)
3. "Покажи LLM конфиг"                (BUG-006 deterministic re-check)
4. "выведи список каналов"            (sanity)
```

If any of these returns generic «Не удалось получить ответ от LLM» — investigate
immediately (likely Session F regression on `execute_tool` masking real
exceptions; check container logs for `tool_execution_error` events).

---

## Phase 5 — Closure & TD opening

### 5.1 Update BUG_LOG.md `Update 2026-04-30 ...` row

Add a row to BUG-003 / BUG-005-B / BUG-007 entries in `## Resolved bugs`:

```markdown
| **Update 2026-04-30 ~12:00 UTC — Production deploy + live smoke PASSED** |
✅ Deployed to VPS via bundle: `git pull --ff-only origin main → <SESSION_F_SHA>`
+ `docker compose build tg_parser` (image `<sha256:NEW_DIGEST>`)
+ `up -d --no-deps --force-recreate tg_parser mcp tg_bot`. All 3 containers
healthy in <60s. Live smoke: 4/4 PASSED (BUG-003 @-prefix, BUG-007 typo
suggestion, BUG-005-B synthetic typed-catch, F-9 4 input variants). 24h watch
on `tg_bot_gemini_empty_parts_total` started; target ≤1% (SLO inherited from
Session E).
```

Commit & push:

```bash
git add docs/notes/BUG_LOG.md
git commit -m "docs(bug-log): record Session F production deploy 2026-04-30"
git push origin main
```

### 5.2 Open follow-up TDs as GitHub issues

Per runbook § 6 + § Out-of-scope of PR #44:

```bash
gh issue create --title "TD-storage-jsonb-channel-id: migrate LIKE → JSONB ?" \
  --label "tech-debt,priority/p1" --body "Replace LIKE '%\"channel_id\"%' with JSONB ? operator in topic_card_repo.list_by_channel + topic_bundle_repo.list_by_channel. Affects migrations, requires separate review per Session F D-5 default."

gh issue create --title "TD-data-quality-AgeManagment: rename canonical channel id?" \
  --label "tech-debt,priority/p1" --body "Verify whether AgeManagment is a typo or the real Telegram username. If typo: rename to AgeManagement + migrate FK references."

gh issue create --title "TD-bot-intent-router (Option B from Session E)" \
  --label "tech-debt,priority/p1" --body "Split TOOL_DECLARATIONS via intent classification — defer until Session F post-deploy metrics confirm whether Option A (Session E thinkingBudget=0) is sufficient long-term."

gh issue create --title "TD-bot-nightly-health-check" \
  --label "tech-debt,priority/p1" --body "Synthetic «Покажи LLM конфиг» query every hour + alert on tg_bot_gemini_empty_parts_total spike. Defends BUG-006 SLO continuously."

# BUG-008 already exists per Session D notes; verify
gh issue list --search "BUG-008" --state open
```

### 5.3 Final summary message to user

Include in the closing message:
- PR #44 merge SHA + deploy SHA
- Confirmation that bug-fix wave 2026-04-26..30 closed (7/7 functional bugs).
- Backlog dump (TD-* issues # opened in 5.2).
- Next-up suggestion: housekeeping sprint or TD-* prioritization.

---

## Rollback procedure (emergency only)

If Phase 2 or 3 fails catastrophically and we need to revert:

```bash
ssh root@mcp.tgp.efimov.mobi
cd /root/TG_parser

# 1. Revert main HEAD on VPS to pre-deploy SHA
git log --oneline -5
git reset --hard <PRE_DEPLOY_SHA>   # SHA captured in Phase 2.2

# 2. Rebuild + restart
docker compose build tg_parser
docker compose up -d --no-deps --force-recreate tg_parser mcp tg_bot

# 3. Verify rollback took
docker exec tg_parser python3 -c "
from tg_parser.utils.channel_id import normalize_channel_id
" 2>&1 | grep -E "ModuleNotFoundError|No module" \
  && echo "Rollback confirmed (helper module gone)" \
  || echo "ROLLBACK FAILED — Session F still active"

# 4. On main repo: revert the squash
gh pr revert 44   # or: git revert <SESSION_F_SHA>
git push origin main
```

Then re-open BUG-003 / BUG-005-B / BUG-007 in BUG_LOG.md with a "Reverted
YYYY-MM-DD HH:MM UTC due to ..." annotation.

---

## Quick reference card

| Step | Time est. | Command summary |
|---|---|---|
| 0.x watch verify | 5 min | `docker exec ... wget Prometheus` + Grafana |
| 1.x merge | 2 min | `gh pr merge 44 --squash` |
| 2.x deploy | 5 min | `git pull` + `compose build` + `compose up` |
| 3.x smoke | 10 min | 4 manual bot interactions + 1 synthetic |
| 4.x watch start | 1 min | `date -u` + Grafana panel link |
| 5.x closure | 15 min | BUG_LOG update + 4 GH issues |
| **Total** | **~40 min** | (excluding rollback contingency) |

**Single-line happy path** (after watch verified):

```bash
gh pr merge 44 --squash --delete-branch && \
ssh root@mcp.tgp.efimov.mobi 'cd /root/TG_parser && git pull --ff-only origin main && docker compose build tg_parser && docker compose up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

(Don't actually use this — the manual smoke checks in Phase 3 require human verification.)
