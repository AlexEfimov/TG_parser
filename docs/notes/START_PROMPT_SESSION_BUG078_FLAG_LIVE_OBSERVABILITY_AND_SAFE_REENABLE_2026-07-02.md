# START_PROMPT — BUG-078: make the resume flag OBSERVABLE in the live worker, then safely re-enable BUG-076/077

**Created:** 2026-07-02. This is a **CODE-IMPLEMENTATION + OPERATIONAL** start-prompt: a small, additive observability fix (a startup log echo + an optional `/health` field) followed by a *corrected* controlled re-enable of the BUG-076/077 checkpointed full-topicization resume. The previous session (which executed the controlled-enable runbook) ran out of context after the exercise **failed** — this session picks up from the pinned root cause.
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**Local HEAD == origin/main HEAD == prod HEAD (verify in §1):** `4f8a326` (`fix(topicization): close residual token-leak surfaces in checkpointed full topicization (BUG-077)`), on top of `596fe30` (BUG-076 checkpoint/resume feature) and `b7285d7` (tip of the BUG-071→075 token-burn hardening chain).
**Status:** the BUG-076/077 code is **live in prod and correct**, but the first controlled enable (2026-07-02) **replayed the original BUG-076 token-burn incident** — see BUG-078 in [`BUG_LOG.md`](BUG_LOG.md). The flag was written to `.env` and a fresh in-container process read it as `True`, but the **long-lived worker never actually ran the chunked path** — the effective in-process value was `False` and there was **no way to observe that**. This session closes that observability gap first, then re-enables safely.

> **Read in order before touching anything:**
> 1. The `### BUG-078` row in [`BUG_LOG.md`](BUG_LOG.md) — the incident, the monolithic-path proof, the pinned root cause, the corrective actions already taken. Also skim the `### BUG-076` and `### BUG-077` rows (their `Update 2026-07-02` rows link back here).
> 2. [`START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md`](START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md) — the runbook that was executed. **Its §4b "verify-live" is the false-green step this session supersedes** (§3 below).
> 3. [`DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md`](DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md) — the architecture (chunked/atomic/checkpoint/budget/resume-driver), §10 rollout sketch, §11 tunables.
> 4. [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md) — the token-burn watch discipline + §10 BUG-077 F7 re-enable hygiene + the §8 kill-switch table.
> 5. [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (repo root) — deploy / rollback / smoke-check procedure (this session ships a real code change, so a deploy is involved).

---

## ⛔ OPERATIONAL WARNINGS — READ FIRST

1. **The catastrophic case is unchanged from the controlled-enable runbook: resuming a 0-card, large-backlog channel while `topicization_full_resume_enabled` is NOT actually live in the running worker.** That is exactly what happened on 2026-07-02 — the flag was in `.env`, a fresh `docker compose exec ... python -c` printed `True`, but the worker (PID 1) had captured `False` at import and ran the **legacy monolithic all-or-nothing** path, replaying the BUG-076 ~0-card billing crash (~430K tokens on that run). **The entire point of this session's fix is to make "the flag is live in the running worker" DIRECTLY OBSERVABLE** so this can never again be a false-green.
2. **Do NOT top up the Anthropic balance until the flag is verified live in the worker (see §4).** The balance is currently **EXHAUSTED**, and that is the de-facto safety net: processing AND topicization both require the Anthropic API, so nothing can burn or escalate (on `@Docma_ru` or any other active 0-card channel) while the balance is empty. Topping up before the fix is deployed re-arms the exact monolithic-re-burn trap.
3. **`topicization_full_resume_enabled` is a GLOBAL flag.** The instant it is genuinely live, the chunked path applies to **every** active channel and the resume driver consults every active channel's checkpoint every tick. `@Docma_ru` is now active and will accumulate a backlog — treat it as a channel that WILL go through the chunked path on its next 0-card `should_reescalate` tick once the flag is live + balance is funded.
4. **Kill-switch caveat (learned this session):** a manual MCP `pause_channel` issued while a billing-backoff cycle is in flight can be **clobbered back to `active`** by the `anthropic_billing_source_paused` handler (it did this once during the incident; a second pause held). Prefer `remove_channel`, or re-verify the pause actually held after issuing it.
5. **AGENTS.md conventions apply.** No `git commit` without an explicit user request. Do not create/edit `docs/methodology/**`. Do **not** edit `pyproject.toml` / `requirements.txt`. Accepted ADRs (`docs/adr/`) and JSON Schemas (`docs/contracts/`) are binding. The code change in §2 is small and additive but still needs explicit approval before commit/deploy.

---

## TL;DR

The controlled first-enable of BUG-076/077 failed in the worst diagnosable way: the fix worked in tests, the `.env` had the flag, and the verify command printed `True 450000` — but the production worker ran the legacy monolithic path anyway and re-burned to a 0-card billing crash. **Root cause is pinned:** `settings = Settings()` (`tg_parser/config/settings.py:1705`) is a module-level singleton read **once at import**; a long-lived worker captures it at process start, while the §4b verify (`docker compose exec ... python -c`) spawns a **fresh** process that re-parses the current `.env` — a **false-green** that structurally cannot see the running worker's in-memory value. The repo operand of the gate (`processing_failure_repo is None`) is **definitively ruled out**; it was the **flag** operand that was False in-process.

This session: (§2) add a **startup log echo** of the effective `topicization_full_resume_enabled` + `topicization_full_run_token_budget` next to the existing "Environment: LLM provider=..." log, and (recommended) surface both in `/health`; (§3) replace the false-green verify with a **log/`/health`-based verify** + an in-place `.env` edit discipline; (§4) guardrails (keep the balance empty until the flag is proven live); (§5) let the next boot's log finally explain the unresolved "process read False" puzzle; (§6) re-run the controlled first exercise on a controlled channel and close out BUG-076/077/078.

---

## 1. Pre-flight — verify current state BEFORE touching anything

> **Command-mechanics note (carried from the controlled-enable runbook §1):** `$POSTGRES_USER`/`$POSTGRES_DB` resolve **only inside the `postgres` container**, so every `psql` is wrapped `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "<SQL>"'`. Prometheus port 9090 is **not** published to the host — query it via `docker compose exec -T prometheus wget …`. Grafana host port `3001` is published.

1. **Prod HEAD is `4f8a326` and services are healthy:**
   ```bash
   ssh prod "cd /home/user/TG_parser && git rev-parse --short HEAD && docker compose ps"
   # expect: 4f8a326 ; all default-profile services healthy
   ```
2. **Confirm the incident's residual prod state (from BUG-078 corrective actions):**
   - `murashko_med` is soft-deleted (out of scheduler):
     ```bash
     ssh prod "cd /home/user/TG_parser && docker compose exec -T postgres sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"SELECT source_id, status, deleted_at FROM sources WHERE channel_id = '\''murashko_med'\'';\"'"
     # expect: deleted_at IS NOT NULL (soft-deleted)
     ```
   - `@Docma_ru` is active:
     ```bash
     ssh prod "cd /home/user/TG_parser && docker compose exec -T postgres sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"SELECT source_id, status, deleted_at FROM sources WHERE channel_id ILIKE '\''%docma%'\'';\"'"
     # expect: status = 'active', deleted_at IS NULL
     ```
   - `.env` still has the flag + budget (UNRELIABLE / unverified-live) and the backup exists:
     ```bash
     ssh prod "cd /home/user/TG_parser && grep -E 'TOPICIZATION_FULL_(RESUME_ENABLED|RUN_TOKEN_BUDGET)' .env && ls -la .env.bak_bug077_enable_20260702_174927"
     # expect: TOPICIZATION_FULL_RESUME_ENABLED=true ; TOPICIZATION_FULL_RUN_TOKEN_BUDGET=450000 ; backup present
     ```
3. **Confirm the Anthropic balance is still EXHAUSTED** (`[CONFIRM WITH USER]` — checked in the Anthropic console; there is no MCP/repo tool for the live balance). This is the current safety gate — it MUST stay empty until §4 verifies the flag is live.
4. **Note that the running worker's effective flag is currently UNOBSERVABLE** — that is the whole reason for §2. Do NOT rely on `docker compose exec ... python -c` to answer "is the flag live?" (§3 explains why).

---

## 2. THE FIX — make the effective settings observable in the live process

The defect is not in the BUG-076/077 machinery; it is that a long-lived worker's effective `settings` singleton value is invisible. Two additive changes, gated by nothing (pure logging/read surfaces), no behaviour change to any pipeline path.

### (a) Startup log echo — PRIMARY (mandatory)

`settings = Settings()` is instantiated once at import (`tg_parser/config/settings.py:1705`). Echo the effective full-run flag + budget at process start, right next to the existing environment log so it lands in the FIRST lines of every boot.

**Anchor — `tg_parser/api/main.py:150-154`** (inside `lifespan`, currently):
```python
    logger.info(
        "Environment: LLM provider=%s, model=%s",
        settings.llm_provider,
        settings.llm_model,
    )
```
Add immediately after it a second `logger.info` echoing `settings.topicization_full_resume_enabled` and `settings.topicization_full_run_token_budget` (both read from the SAME live singleton the pipeline gate at `tg_parser/processing/topicization.py:334` reads). Use a stable, greppable key, e.g. a message containing the literal token `topicization_full_resume_enabled` so the verify grep in §3 matches. This is the import-time value of the running process — exactly the thing the false-green verify could not see.

> Note: `tg_parser/api/main.py` is the **API/scheduler** process entrypoint (the worker that runs the background scheduler → `_process_source` → the topicization escalation). Confirm this is the process that hosts the scheduler for prod's default compose profile (it is, per the controlled-enable runbook — the `tg_parser` service). If any other long-lived entrypoint also imports `settings` and runs the pipeline, echo there too; but for the default profile the `tg_parser` service is the one that matters.

### (b) `/health` surfacing — RECOMMENDED (on-demand read-only verification)

Add the same two effective values to the `/health` payload so the RUNNING process can be interrogated at any time without reading logs.

**Anchors:**
- Route: `tg_parser/api/routes/health.py:24-40` (`health_check()` builds a `HealthResponse`).
- Schema: `tg_parser/api/schemas.py:62-68` (`class HealthResponse` — add two optional fields, e.g. `topicization_full_resume_enabled: bool | None` and `topicization_full_run_token_budget: int | None`, both defaulting to `None` so nothing else breaks), then populate them from `settings` in `health_check()`.

`/health` is unauthenticated and always returns HTTP 200, so it is a convenient live probe. (`/status` / `/status/detailed` are alternatives, but `/health` is the lightest and already DB-pinged.)

### Constraints
- **No `pyproject.toml` / `requirements.txt` edits** (AGENTS.md). This change needs none.
- **No commit without explicit user approval** (AGENTS.md). Implement, run tests/`ruff`, then ask.
- Keep it purely additive — do not touch the gate at `topicization.py:334`, the resume driver (`topicization_service.py:1782`), or the repo binding (`:553-557`, `:991-1003`). Those are correct; the flag simply never reached the worker.

---

## 3. CORRECTED enable / verify procedure (supersedes the controlled-enable runbook §4b)

The old §4b verify was:
```bash
# ❌ FALSE-GREEN — DO NOT TRUST for "is the flag live in the worker?"
docker compose exec tg_parser python -c \
  'from tg_parser.config import settings; print(settings.topicization_full_resume_enabled, ...)'
```
This spawns a **fresh** Python process that re-parses the CURRENT `.env` — it prints `True` regardless of what the long-lived worker (PID 1) captured at its own import time. It reported `True 450000` during the incident while the worker was running with `False`.

### Corrected sequence

1. **Edit `.env` IN PLACE only.** Append / rewrite with `cat`/`printf` redirection — **never** `sed -i` and never an editor that does an atomic-save-rename. `.env` is bind-mounted as a **single file** (`./.env:/app/.env:ro`); an atomic-save changes the inode and can **orphan the bind mount** (the container keeps the old inode). Verify the inode is stable host-side + container-side if in doubt:
   ```bash
   ssh prod "cd /home/user/TG_parser && stat -c '%i %Z' .env && docker compose exec -T tg_parser stat -c '%i' /app/.env"
   ```
2. **Force-recreate the worker so it re-imports and re-reads `.env`:**
   ```bash
   ssh prod "cd /home/user/TG_parser && docker compose up -d --force-recreate tg_parser"
   # capture the new StartedAt for the log --since window:
   ssh prod "cd /home/user/TG_parser && docker inspect -f '{{.State.StartedAt}} pid={{.State.Pid}}' \$(docker compose ps -q tg_parser)"
   ```
3. **VERIFY via the running process's OWN signals — NOT a fresh exec:**
   ```bash
   # (a) startup echo — the singleton's import-time value for THIS process:
   ssh prod "cd /home/user/TG_parser && docker logs tg_parser --since <StartedAt> 2>&1 | grep topicization_full_resume_enabled"
   # expect the new §2(a) line showing True + budget=450000

   # (b) /health field (if §2(b) shipped) — the RUNNING process, on demand:
   ssh prod "curl -s http://localhost:8000/health | python3 -m json.tool | grep -i topicization_full"
   ```
   Only proceed to a resume once BOTH the startup echo and/or `/health` confirm the live value is `True`. **Do not use `docker compose exec ... python -c`** as the gate.
4. **Behavioural proof once genuinely live** (the ground truth that the chunked path — not the monolithic one — is running): the first escalation of a 0-card channel must
   - write a `topicization:full_checkpoint:<channel>` row in `processing_failures`:
     ```bash
     docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT source_ref, attempts AS chunks_done, last_attempt_at FROM processing_failures WHERE source_ref LIKE '\''topicization:full_checkpoint:%'\'';"'
     ```
   - emit `tg_parser_topicization_full_run_*` metric samples:
     ```bash
     ssh prod "curl -s http://localhost:8000/metrics | grep tg_parser_topicization_full_run"
     ```
   - and the log must show the chunked path, **not** the monolithic `tg_parser/processing/topicization.py:376-382` "Large channel (%d docs), %d batches of %d" line running all batches in one invocation (that line is the incident's smoking gun — its presence means the monolithic path ran).

---

## 4. Guardrails (do these, in this order)

1. **Do NOT top up the Anthropic balance until §3 verifies the flag live in the worker.** The empty balance is the only thing currently preventing a monolithic re-burn on `@Docma_ru` (or any active 0-card channel) if the flag were ever live-but-unverified again. Deploy §2, verify live via §3, THEN discuss funding with the user.
2. **Keep `TOPICIZATION_FULL_RUN_TOKEN_BUDGET=450000`** as the auditable kill-switch (secondary safety net at `max_chunks_per_invocation=1`, per the controlled-enable runbook §4a / ⛔ warning 3).
3. **Re-run the controlled FIRST exercise per the BUG-076 runbook on a CONTROLLED channel** — not blindly on `@Docma_ru` at scale. Pick a bounded 0-card channel (or `@Docma_ru` only once its backlog and the balance headroom are understood), watch it converge chunk-by-chunk per the controlled-enable runbook §5/§6.
4. **Kill-switch caveat:** if you must pause mid-run, remember billing-backoff can clobber a manual `pause_channel` (§⛔4). Prefer `remove_channel`, or re-verify the pause held (`SELECT status, updated_at FROM sources …`).
5. **The global-flag reminder:** once live, enumerate active channels for 0-card + backlog before/at enable time (controlled-enable runbook §1 item 5b) so no unexpected channel starts a chunked run.

---

## 5. Residual investigation — the unresolved "process read False" puzzle

By read-only means this session could **not** determine the exact mechanism by which PID 1 (StartedAt `14:52:25Z`) ran with `topicization_full_resume_enabled=False` even though every static signal (`.env` contains the flag; ctime `14:49:40Z` predates process start; same inode host+container; correct F7 bytecode; no OS-env override; a fresh in-container parse returns `True`) said it *should* have parsed `True`. That is unresolvable precisely because the live singleton was unobservable — which is the core BUG-078 finding.

**Once §2(a) ships, the NEXT boot's first log lines will directly reveal the running process's effective value.** After the corrected enable in §3, capture that log line and compare it against the `.env`. Likely candidates the echo will disambiguate: a stale/duplicate `.env` key later in the file overriding an earlier one; an env var set in the compose environment/`env_file` shadowing the `.env`; a recreate that didn't actually re-import (old container reused); or a Pydantic parsing quirk on the truthy value. The echo turns all of these from "unfalsifiable by read-only means" into "visible in line 2 of the log."

---

## 6. Re-test + closeout plan

1. **Deploy §2** (startup echo + optional `/health`) per `PRODUCTION_DEPLOYMENT.md` (this is a real code change → rebuild `tg_parser` image, force-recreate; run the post-deploy smoke check). Get explicit approval before commit/deploy per AGENTS.md.
2. **Verify the flag live** via §3 (log echo / `/health`), captured against the new StartedAt.
3. **Fund the balance** (`[CONFIRM WITH USER]`) only after step 2 is green.
4. **Prove the CHUNKED path** on a controlled channel: checkpoint rows advancing (`chunks_done` monotically ↑), per-chunk `topics_created` rising during the run, `tg_parser_topicization_full_run_*` metrics emitting; a `docker compose restart tg_parser` mid-run loses ≤1 chunk (crash-resume test). Watch per controlled-enable runbook §5/§6, kill-switch per §7.
5. **Decide `@Docma_ru` processing/topicization** once RAW ingestion has a backlog and the chunked path is proven (`[CONFIRM WITH USER]`).
6. **Update statuses in [`BUG_LOG.md`](BUG_LOG.md):** flip BUG-078 → `resolved` once the startup echo is deployed and a genuinely-live re-run is confirmed; flip BUG-076 / BUG-077 → `resolved` once the controlled first exercise succeeds for real (their `Update 2026-07-02` rows currently point here). Doc-only edits; committing still requires explicit request.

---

## 7. Reading list / pointers

**Primary (read in "Read in order" above):**
- [`BUG_LOG.md`](BUG_LOG.md) — `### BUG-078` (this incident), `### BUG-076` / `### BUG-077` (`Update 2026-07-02` rows).
- [`START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md`](START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md) — the executed runbook (its §4b verify is superseded by §3 here).
- [`DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md`](DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md) — the feature architecture + rollout sketch.
- [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md) — watch discipline, §10 F7 re-enable hygiene, §8 kill-switch table.
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (repo root) — § Updating, § Rollback Procedures, post-deploy smoke.

**Deep background (source of truth if code contradicts a runbook):**
- [`START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md`](START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md) — BUG-076 implementation.
- [`START_PROMPT_SESSION_BUG076_TOKENLEAK_HARDENING_IMPL_2026-07-02.md`](START_PROMPT_SESSION_BUG076_TOKENLEAK_HARDENING_IMPL_2026-07-02.md) — BUG-077 hardening.

**Code anchors (verified at HEAD `4f8a326` while writing this prompt):**
- `tg_parser/config/settings.py:1705` — `settings = Settings()`, the module-level singleton read once at import (the root of the observability gap); the `topicization_full_*` fields are defined at `:431-536` (`topicization_full_resume_enabled` `:431`, `topicization_full_run_token_budget` `:475`).
- `tg_parser/api/main.py:150-154` — the "Environment: LLM provider=%s, model=%s" startup log; add the §2(a) echo immediately after.
- `tg_parser/api/routes/health.py:24-40` — the `/health` route; `tg_parser/api/schemas.py:62-68` — the `HealthResponse` schema to extend for §2(b).
- `tg_parser/processing/topicization.py:334` — the gate `if settings.topicization_full_resume_enabled and self.processing_failure_repo is not None:` (evaluated False on the FLAG operand during the incident).
- `tg_parser/processing/topicization.py:376-382` — the legacy monolithic "Large channel (%d docs), %d batches of %d (concurrency=%d)" log (the incident's path-exclusive smoking gun).
- `tg_parser/services/topicization_service.py:553-557` — F7 `pipeline_failure_repo` binding from the shared session (always non-None → the repo operand of the gate is ruled out); `:991-1003` — the incremental path's equivalent `failure_repo` bind; `:1087-1095` — the `should_reescalate` → `run_topicization(...)` first-escalation call; `:1782` — the resume driver's `run_topicization(channel_id=channel_id, resume=True)`.
