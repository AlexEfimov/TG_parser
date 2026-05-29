# Handoff for next chat — Wave 1 step 5 (ops/observability cluster)

**Created:** 2026-05-29 (end of Wave 1 step 4 post-watch follow-up session).
**Purpose:** start Wave 1 step 5 in a fresh Cursor chat without losing context. Step 5 = the ops/observability cluster deferred from the step-4 watch (BUG-036, BUG-037, ENH-001) + the operator-manual Grafana password rotation.
**Predecessor handoff:** [`HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md`](HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md) — the post-watch follow-up that this session completed.

---

## 1. Current state (end of post-watch session)

| Аспект | Состояние |
|---|---|
| `main` HEAD | `39b6ba2` (`fix(digest): rollback aborted session before subscribe race-retry (BUG-029) (#139)`) |
| Prod VPS | deploy `af7790f → 39b6ba2` **dispatched at session end** — verify prod SHA = `39b6ba2` at step-5 start (see § 6) |
| Alembic head | `a8b7c6d5e4f3` (unchanged — no schema work this session) |
| Branch | `main`, clean, ahead 0 (pushed) |

### What the post-watch session closed (all merged/pushed)

| Item | PR / commit | Notes |
|---|---|---|
| BUG-033 (CRITICAL — group chat_id=123 placeholder) | #108 `e50449b` | root cause: LLM hallucination, no `Message.chat.id` injection; fixed via executor-authoritative `chat_id` |
| BUG-034 (channel name parser typo) | #109 `6ebad33` | `validate_channel_username` + prompt v1.7.1; fixture follow-up `@x`→`@validch` |
| BUG-031 + BUG-032 (ConfirmFlow refactor) | #111 `66e8297` | confirm-gate before subscribe side-effects + affirmative-token classifier; prompt v1.7.2 |
| BUG-035 (APScheduler invalidation) | #112 `af7790f` | cross-process `remove_task` hardening; watchlist invalidation-by-construction |
| BUG-029 (subscribe race-retry rollback) | #139 `39b6ba2` | `session.rollback()` in digest + watchlist race-retry |
| BUG-030 (scheduler initial-load retry) | #138 `d4fecb9` | **hand-rolled** retry (no tenacity, operator decision); mirrors `anthropic_client.py` idiom |
| OBS-001 | `9ede14c` | **CLOSED as expected-behaviour** — matcher healthy; see [`OBS_001_INVESTIGATION_2026-05-29.md`](OBS_001_INVESTIGATION_2026-05-29.md) |
| DOC-001 + skipped-tests audit + housekeeping | `a06f428`, `ce020ce` | `@smoke_tgparser_bot`→`@Tgingest_bot`; `TEST_POSTGRES=1` standard; `backups/` gitignored |

---

## 2. Step 5 scope — three findings + one operator-manual action

### 2.1. BUG-036 (**Medium** — ops/observability) — Grafana rules as code

* **Source of truth:** [`BUG_LOG.md` § BUG-036](BUG_LOG.md).
* **Symptom:** Grafana alert-rule `tg_api_5xx_spike` `noDataState` was patched to `OK` via UI twice (2026-05-24T18:30Z, 2026-05-25T06:21Z) but **did not persist** — re-emitted `DatasourceNoData` firing (issues #100/#101/#103/#104, fingerprint `47991b0914dd7148`). UI-state drifts back across Grafana eval cycles / container restarts.
* **Recommended fix (from BUG_LOG):**
  1. Provision all 3 alert rules (`tg_parser_bot_down`, `tg_parser_api_down`, `tg_api_5xx_spike`) via file-based provisioning at `docker/grafana/provisioning/alerting/wave1_step4.yaml` with explicit `noDataState: OK` + `for: 5m`.
  2. Bind contact-point `cursor-watch-webhook` to the same provisioning file so it survives restarts.
  3. Idempotency test: Grafana restart preserves `noDataState=OK`.
* **Effort:** ~1-2h. This is the **core step-5 deliverable**.
* **Note:** this is infra/config (`docker/grafana/...`), NOT application code — different test strategy (provisioning-load assertion, restart-idempotency), no `TEST_POSTGRES=1` relevance.

### 2.2. BUG-037 (**Low** — ops/automation) — webhook classifier prefix instability

* **Source of truth:** [`BUG_LOG.md` § BUG-037](BUG_LOG.md).
* **Symptom:** Cursor automation `7b35ca01-…` (Grafana→GitHub webhook ingress) routed identical payloads (same fingerprint `47991b0914dd7148`) to different title prefixes (`[5xx]` for #100, `[alert]` for #101). Classifier branches on a sometimes-empty field.
* **Recommended fix:** make the prefix branch deterministic — `labels.rulename` → `labels.alertname` → generic `[alert]` only if both absent. Inspect the `7b35ca01` workflow definition (via Cursor UI / `cursor-backend-control` MCP `get_automation`).
* **Effort:** ~30-60 min. **Can bundle with BUG-036** (same observability cluster, same incident trail) — but it's a Cursor-automation edit, not a repo change, so it may live outside a PR.

### 2.3. ENH-001 (**Low** — observability) — `last_checked_at` misleading telemetry

* **Source of truth:** [`BUG_LOG.md` § ENH-001](BUG_LOG.md) (filed this session, spun out of OBS-001 closure).
* **Symptom:** `last_checked_at` reads as "last evaluated" but means "last hourly tick with new docs"; stays null/stale for new interests + quiet channels; `trigger_pipeline` never advances it → operator misreads healthy matcher as stuck.
* **Fix options:** (a) add true matcher-liveness gauge (`tg_watchlist_last_tick_at`) + re-document field; OR (b) call `touch_checked` for all active interests every tick (incl. empty `new_doc_refs`).
* **Regression test:** scheduler-tick test asserting `touch_checked` invoked when `candidates=0`.
* **Effort:** ~1h. This IS application code (`watchlist_service.py:820-824`, `scheduler_service.py:297-301`) → standard PR + `TEST_POSTGRES=1` applies.

### 2.4. Grafana password rotation (operator-manual)

* **Source of truth:** [`WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` § C](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md).
* Plaintext `GRAFANA_ADMIN_PASSWORD` was passed via chat 2026-05-24 → rotate. SSH + `openssl rand -base64 24` + edit `.env` + `docker compose up -d --no-deps grafana`. **Operator-only** (SSH + credential handling); agent cannot do this.

---

## 3. Suggested priority order

1. **BUG-036 first** (Medium, core step-5 work) — provisioning-as-code. Biggest blast-radius reduction (stops the recurring spurious GitHub issues).
2. **BUG-037** — bundle alongside BUG-036 (same incident cluster); deterministic classifier in the `7b35ca01` automation.
3. **ENH-001** — application-code PR; lower urgency, can be its own PR or deferred to housekeeping.
4. **Grafana password rotation** — operator-manual, any time; independent.

**Suggested split:** BUG-036 + BUG-037 = one observability-config workstream (mixed repo + Cursor-automation). ENH-001 = separate small app-code PR. They're independent → safe to parallelize IF using **isolated worktrees** (see § 5 lesson).

---

## 4. Key reference paths & IDs

| Item | Value |
|---|---|
| `main` HEAD | `39b6ba2` |
| Target prod SHA | `39b6ba2` (verify at start) |
| Alembic head | `a8b7c6d5e4f3` |
| VPS SSH | `ssh -p 2296 user@212.72.189.15` (host alias `redboxtgbot`) |
| VPS Grafana | `https://grafana.tgp.efimov.mobi` |
| VPS MCP | `https://mcp.tgp.efimov.mobi/mcp` (Bearer auth) |
| Bot | `@Tgingest_bot` (id `8657845219`) |
| Grafana webhook automation | `7b35ca01-a7d1-4c3a-bb8b-940918e506d6` (active — **do NOT disable**, BUG-037 target) |
| Alert fingerprint (noData noise) | `47991b0914dd7148` (rule `tg_api_5xx_spike`) |
| Related GH issues | #100, #101, #103, #104 (all closed, same fingerprint) |
| BUG_LOG | [`docs/notes/BUG_LOG.md`](BUG_LOG.md) — § BUG-036, BUG-037, ENH-001 |
| Cleanup runbook | [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) (§ C Grafana pw) |
| Real prod digest | `digest_94483db9-9351-4f99-9aec-46949d9ddd09` (S-1 — **NEVER touch**) |
| Real owner chat_id | `5445781511` (S-2 — **NEVER use in tests**) |

---

## 5. Process lessons carried forward (apply in step 5)

1. **`TEST_POSTGRES=1` is standard** for any bot/MCP/API/repo app-code PR (closed a 303-test blind spot). Applies to ENH-001; NOT to BUG-036 (infra config). See [`SKIPPED_TESTS_AUDIT_2026-05-25.md`](SKIPPED_TESTS_AUDIT_2026-05-25.md).
2. **Self-review-then-rerun on every test-bearing PR:** write tests → stash-and-rerun to prove they fail pre-fix → fix gaps → full rerun. Operator-mandated.
3. **⚠️ Parallel write-workers share the working tree.** `generalPurpose` subagents operate in the SAME working directory — two concurrent write-workers in this session collided (both edits landed on one branch; one worker's `checkout -b` based off the other's commit). They self-recovered (scoped `git add`/`stash` + `rebase --onto`), but **for step 5: either run write-workers SEQUENTIALLY, or use `best-of-n-runner` (isolated git worktrees) for true parallelism.** Read-only spikes can parallelize freely.
4. **Sandbox network quirks:** `git push` SSH fails (`Could not resolve hostname github.com`) → use HTTPS fallback `git push https://github.com/AlexEfimov/TG_parser.git <branch>`. `gh pr create` / merge needs `required_permissions: ["full_network"]`; `git ls-remote` (HTTPS) is a working read-only substitute for `gh pr view` when api.github.com is blocked.
5. **One PR per BUG** (anti-pattern to bundle), exception for tightly-coupled pairs (BUG-031+032, and digest+watchlist symmetric fixes shared a PR). Operator sign-off before every merge.

---

## 6. First actions for the new chat

1. **Verify prod deploy landed:**
   ```bash
   git ls-remote https://github.com/AlexEfimov/TG_parser.git refs/heads/main   # expect 39b6ba2
   ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && git log --oneline -1'      # expect 39b6ba2
   ```
   If prod is NOT at `39b6ba2`, the end-of-session deploy may have failed/been-skipped — check this session's final deploy-worker report first.
2. **Read** [`BUG_LOG.md`](BUG_LOG.md) § BUG-036 / BUG-037 / ENH-001 (full specs).
3. **Read** [`WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` § C](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) for the Grafana provisioning + password context.
4. Locate existing Grafana config: `ls docker/grafana/` — see whether any provisioning dir already exists or if BUG-036 starts greenfield.
5. Start BUG-036.

---

## 7. Suggested initial prompt for the new chat

```text
@docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP5_2026-05-29.md

Начинаем Wave 1 step 5 (ops/observability cluster). Post-watch follow-up
завершён — main на 39b6ba2, prod задеплоен.

Порядок:
1. BUG-036 (Medium) — Grafana rules as code (docker/grafana/provisioning/alerting/).
2. BUG-037 (Low) — webhook classifier deterministic prefix (Cursor automation 7b35ca01).
3. ENH-001 (Low) — last_checked_at telemetry clarity (app-code PR + TEST_POSTGRES=1).
4. Grafana password rotation — operator-manual, я сделаю сам.

Multitask Mode ON. Параллельные write-workers — только изолированные worktree'ы
(урок shared-tree коллизии из прошлой сессии).
```

---

## 8. What NOT to do (anti-patterns)

* **НЕ** трогать prod digest `digest_94483db9` (S-1) / chat_id `5445781511` (S-2).
* **НЕ** disable Cursor automation `7b35ca01` (active webhook ingress — это target фикса BUG-037, не повод выключать).
* **НЕ** запускать параллельные write-workers в shared working tree — sequential или isolated worktrees.
* **НЕ** коммитить новый Grafana password в repo (даже зашифрованным) — `.env` gitignored.
* **НЕ** редактировать `pyproject.toml` / `requirements.txt` без operator approval.
* **НЕ** создавать `docs/methodology/**` в этом workspace.
* **НЕ** push в `main` / merge PR без operator sign-off.
