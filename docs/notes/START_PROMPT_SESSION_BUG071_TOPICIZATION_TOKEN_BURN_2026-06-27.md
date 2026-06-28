# START_PROMPT — BUG-071 topicization token-burn (truncation re-burn + latent re-escalation loop)

**Created:** 2026-06-27 (handoff from the BUG-069/B2 + BUG-070 fix+deploy session; this bug was discovered and root-caused READ-ONLY this session, NOT yet fixed).
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**Prod:** VPS `ssh prod` (`212.72.189.15:2296`, user `user`, app dir `/home/user/TG_parser`), Docker compose.

---

## ⛔ CRITICAL OPERATIONAL WARNING — READ FIRST

**DO NOT top up the Anthropic balance until this fix is deployed.** The processing stage is currently billing-blocked (Anthropic credit exhausted). That billing exhaustion is *the only thing* keeping a token-burn loop dormant. The moment credit is restored, processing resumes → new processed docs appear → the latent re-escalation loop (see §"The bug", part C) re-burns expensive Sonnet tokens **unboundedly** every scheduler tick. **The topicization fix MUST ship BEFORE the top-up.** Restoring credit is a separate user action and must wait.

---

## TL;DR for the next session

A token-burn bug lives in **TOPICIZATION** (not processing). Symptom paradox observed this session: `processed_documents` count is flat, yet money is still being deducted from Anthropic. Root cause: topicization sends 50-doc batches to the expensive `claude-sonnet-4-6` with `max_tokens=8192`; the topic JSON routinely **exceeds** 8192 output tokens, so Anthropic returns **HTTP 200 (CHARGED) but TRUNCATED**, `json.loads` fails (`Unterminated string`), the call is retried **3× (each a full charged Sonnet call)** and then discarded. `repair_json` cannot fix length-truncation. Worse, a latent loop re-runs the *entire* failed topicization every tick because the channel never reaches >0 topic cards.

**Workflow for this session (user-selected): implement the full fix + tests, then run a self-review AND a Bugbot review of the diff, then STOP before commit/deploy and await explicit user approval.** On approval: gated full-suite test → commit → push → deploy per `PRODUCTION_DEPLOYMENT.md`.

---

## What already shipped (context — DO NOT redo)

- **Prod HEAD = `61637d1`** — contains BOTH:
  - **BUG-069 / B2** — bounded per-tick raw load via `NOT EXISTS` + cooldown anti-join (commit `1809795`).
  - **BUG-070** — Telethon session lock + WAL/`busy_timeout` to stop concurrent `database is locked` (commit `61637d1`).
  - Both deployed and validated this session. **Rollback ref for any new deploy = `61637d1`.**
- Earlier this run: BUG-067/068 (commit `1ed86ac`) — LLM hang bounds, degraded-tick detection, B2b bounded retry + cooldown (the `processing_failures` pattern reused by Fix 2 below).

This BUG-071 fix is **net-new** and uncommitted. Nothing for it has been implemented yet — only the read-only diagnosis below.

---

## The bug (discovered + root-caused this session; READ-ONLY diagnosis done, NOT fixed)

All file:line anchors below were **verified against the working tree at HEAD `61637d1`** during the diagnosis.

### A. Truncation → charged-but-discarded retries (the per-call waste)
- `_generate_topics_batch` — [`tg_parser/processing/topicization.py:307-364`](../../tg_parser/processing/topicization.py). Sends one batch to the LLM with `max_tokens=model_cfg.get("max_tokens", 8192)` at **`topicization.py:330`**. The `8192` comes from [`prompts/topicization.yaml:83`](../../prompts/topicization.yaml) (`model.max_tokens: 8192`).
- `BATCH_SIZE = 50` at **`topicization.py:203`** (the `topicize_channel` full-run path; large channels are split into 50-doc batches at `:218-221`).
- JSON-parse retry loop: `max_json_retries = 3` at **`topicization.py:313`**; the `json.JSONDecodeError` retry/abort handling is at **`topicization.py:345-360`**. **Each retry re-issues a FULL, separately-charged Sonnet call** (`generate_with_usage` at `:326`). On a length-truncated reply every retry truncates identically → all 3 are wasted spend, then a `RuntimeError` is raised (`:360`) and the batch is discarded.
- `repair_json` ([`tg_parser/processing/pipeline.py:274`](../../tg_parser/processing/pipeline.py)) only escapes inner quotes / strips trailing commas — it **cannot** repair a reply cut off mid-string by the token cap.
- **Same truncation vulnerability exists at two more topicization LLM sites** (apply the same fix there):
  - `_merge_topics` — `max_tokens=merge_model.get("max_tokens", 16384)` at **`topicization.py:429`** (retry loop `:418-457`).
  - `_discover_single_batch` (incremental Phase-2 discover) — `max_tokens=discover_model.get("max_tokens", 8192)` at **`topicization.py:1157`** (retry loop `:1139-1182`). NOTE: this path *swallows* a final parse failure by marking the batch docs "unassignable" (`:1179`) rather than raising — but it still burns the paid truncated calls.

### B. Production evidence (prod, 09:21–10:19 UTC today)
One full re-topicization of channel `murashko_med`: **334 batches, 328 failed, 0 topic cards saved, ~2.38M Sonnet tokens burned** (1.56M prompt / 0.82M completion). Completion ÷ successful-call ≈ **8097 ≈ the 8192 cap** → essentially every call maxed out its output budget, i.e. truncation. Metrics consulted:
- `tg_parser_llm_tokens_total{model="claude-sonnet-4-6"}`
- `tg_parser_llm_json_parse_retry_total{stage="topicization_generate"}`

### C. LATENT RE-BURN LOOP (the dangerous part)
- `run_incremental_topicization` re-escalates to a FULL run when a channel has 0 cards but new docs: the branch `if len(existing_cards) == 0 and len(new_docs) > 0:` at **[`tg_parser/services/topicization_service.py:216`](../../tg_parser/services/topicization_service.py)** → calls `run_topicization(...)` (the full ~334-batch path) at **`topicization_service.py:222-237`**.
- The scheduler invokes `run_incremental_topicization` after each successful processing tick that produced new docs: **[`tg_parser/services/scheduler_service.py:486-500`](../../tg_parser/services/scheduler_service.py)** (`new_doc_refs` → `run_incremental_topicization(channel_id, new_doc_refs)`).
- Because the part-A truncation bug guarantees **0 cards are ever saved**, the channel stays at 0 cards forever, so the `:216` branch re-escalates to a full Sonnet re-topicization **every tick that has new docs**.
- It is **DORMANT only because processing is billing-blocked** (no new processed docs → `len(new_docs) == 0` → branch not taken). **Topping up credit re-arms it.** (Hence the warning at the top.)

---

## The APPROVED fix plan (design — implement this session)

### Fix 1 — Detect truncation; do not blindly retry the same oversized request
**Root correction vs the original handoff note:** `stop_reason` is **NOT** currently surfaced to callers. `_extract_text_content` ([`tg_parser/processing/llm/anthropic_client.py:332-357`](../../tg_parser/processing/llm/anthropic_client.py)) only *logs* `stop_reason` inside the **empty-content** branch (`:341-344`) — and on a `max_tokens` truncation the content is **non-empty**, so that log line never even fires. The returned `LLMResponse` ([`tg_parser/processing/ports.py:13-23`](../../tg_parser/processing/ports.py)) has **no `stop_reason` field**. So the mechanism must be *built*:

1. Add `stop_reason: str | None = None` to `LLMResponse` (`ports.py:13-23`).
2. Populate it from `data.get("stop_reason")` where the `LLMResponse` is constructed in `anthropic_client.py` (**`:259-285`**, i.e. read `data` alongside `content`/`usage` and pass `stop_reason=data.get("stop_reason")`). The `InstrumentedLLMClient.generate_with_usage` wrapper ([`tg_parser/processing/llm/instrumented.py:66-96`](../../tg_parser/processing/llm/instrumented.py)) returns the inner result unchanged, so the new field propagates automatically. (Other providers default to `None` — harmless.)
3. In the topicization retry loops (`_generate_topics_batch` `:319-360`, and the analogous `_merge_topics` / `_discover_single_batch` loops), treat `llm_response.stop_reason == "max_tokens"` as a **non-retryable "too big" signal**: do NOT re-issue the identical oversized request. Instead **shrink the request** — halve / lower the batch (`BATCH_SIZE` at `topicization.py:203`, and/or `settings.topicization_batch_size`, default 50 at [`tg_parser/config/settings.py:371`](../../tg_parser/config/settings.py)) and/or auto-scale `max_tokens` — then retry once at the smaller size. Verify the exact retry/return contract of each loop so the change is localized and does not regress the existing JSON-repair retry path.

### Fix 2 — Break the re-burn loop (cooldown / attempt budget on full re-escalation)
Gate the full re-escalation at `topicization_service.py:216` behind a cooldown / attempt budget, mirroring the processing B2b failure-cooldown pattern (`_should_skip_failed` at [`tg_parser/processing/pipeline.py:1447-1478`](../../tg_parser/processing/pipeline.py), backed by `processing_failures`). A channel that JUST failed a full topicization must NOT be re-escalated on the next tick.
- **Open implementation decision (no existing topicization-failure store):** `processing_failures` is keyed to per-document raw refs, not to a channel-level topicization attempt, so it cannot be reused as-is. Pick a persistence home for the "topicization attempted/failed at <ts>, attempts=N" marker:
  - (a) a small new state table (e.g. `topicization_failures` / `topicization_attempts`) on the **processing** alembic branch (`alembic_processing.ini`) — cleanest mirror of B2b, requires a migration;
  - (b) a column on the `sources` table (e.g. `last_topicization_attempt_at`) — fewer tables, also a migration;
  - (c) defensible default if a migration is undesirable: reuse the cooldown settings (`failure_billing_cooldown_s`=1800 / `failure_default_cooldown_s`=3600) with a channel-keyed marker.
  Propose one with a default cooldown and justify it. Whatever the home, the gate must (i) skip re-escalation while in cooldown, (ii) still allow eventual re-attempt after TTL (so a real prompt/model fix can recover the channel), (iii) log a clear "topicization re-escalation skipped (cooldown)" event.

### Fix 3 — Make paid-but-wasted calls observable
Today `record_llm_request` ([`tg_parser/api/metrics.py:596-639`](../../tg_parser/api/metrics.py)) folds everything into `status="success"`/`"error"` (`:615`) with no notion of truncation — a charged truncated call counts as `success`. Add a dedicated metric for `stop_reason == "max_tokens"` truncations so this class of wasted spend is alertable. **Model it on the existing pattern:** Counter `BOT_GEMINI_EMPTY_PARTS_TOTAL` (`metrics.py:162-170`) + helper `record_bot_gemini_empty_parts` (`metrics.py:714`). Suggested: `LLM_TRUNCATION_TOTAL` labelled `(provider, model, stage)` + `record_llm_truncation(...)`, incremented at the topicization sites when `stop_reason == "max_tokens"` is detected.

---

## Suggested first action in the new session

1. **Read-only confirm the anchors** above are still current (the tree may have moved if anything landed after `61637d1`): open `topicization.py` (`:203`, `:307-364`, `:429`, `:1157`), `topicization_service.py:216-237`, `anthropic_client.py:259-285` + `:332-357`, `ports.py:13-23`, `instrumented.py:66-96`, `pipeline.py:1447-1478`, `metrics.py:596-639` + `:162-170`/`:714`, `prompts/topicization.yaml:83`, `settings.py:371`.
2. **Implement Fixes 1–3** with tests (see conventions). Add unit tests for: a mocked truncated (`stop_reason="max_tokens"`) reply → no 3× re-issue + batch shrink + truncation metric incremented; and the re-escalation cooldown gate (escalates once, then skipped within TTL, then allowed after TTL).
3. **Self-review + Bugbot review** the diff. Then **STOP** and await explicit user approval before commit/deploy.

---

## Current prod / repo state to record

- **Prod HEAD = `61637d1`** (BUG-069/B2 + BUG-070, both deployed & validated). Rollback ref = `61637d1`.
- **Processing fully billing-blocked** (Anthropic credit exhausted). Backlog ~16,489 unprocessed (raw ~55,979 / processed ~39,489); `murashko_med` coverage ~0.503. The billing block is a SEPARATE issue (user's action to restore credit) — but per the top warning, the topicization fix MUST ship BEFORE the top-up.
- **Prod env models:** `PROCESSING_LLM_MODEL=claude-haiku-4-5-20251001`, `TOPICIZATION_LLM_MODEL=claude-sonnet-4-6`, `LLM_MODEL=claude-sonnet-4-6`, `PROCESSING_CONCURRENCY=20`.
- **Known unrelated pre-existing test failure** (out of scope; fails on clean HEAD too): `tests/test_mcp_management.py::TestGetAllChannelStats::test_batch_stats_degrades_to_zeros_on_aggregation_error`.
- **Relevant settings defaults** (all in `tg_parser/config/settings.py`): `topicization_batch_size=50` (`:371`); `failure_billing_cooldown_s=1800` (`:245`); `failure_parse_max_attempts=3` (`:256`); `failure_parse_cooldown_s=86400` (`:266`); `failure_default_cooldown_s=3600` (`:276`); `llm_json_retry_delay=2.0` (`:540`).

---

## Conventions to respect (from `AGENTS.md`)

- Branch `main`. **NO `git commit` without an explicit user request.**
- Accepted ADRs in [`docs/adr/`](../adr/) and JSON Schemas in [`docs/contracts/`](../contracts/) are **binding**.
- Do **NOT** create or edit `docs/methodology/**` from this workspace (it lives in a separate worktree; absent on `main` by design).
- No direct edits to `pyproject.toml` / `requirements.txt` without an explicit request.
- Tests per [`tests/README.md`](../../tests/README.md): default / PR / max-local modes; use `TEST_POSTGRES=1` for cross-table / storage tests (Fix 2's persistence marker likely needs this).
- Quality lifecycle: [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md). Log the fix under **BUG-071** in [`docs/notes/BUG_LOG.md`](BUG_LOG.md) (BUG-070 is the latest used).

---

## Deploy procedure reference (only after explicit approval)

`PRODUCTION_DEPLOYMENT.md` § Updating (canonical): backup → `git pull --ff-only` → `docker compose build tg_parser` → `db upgrade --db all` (run as a no-op check; **Fix 2 may add a real migration** — verify it applies cleanly) → `docker compose up -d` → `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` → smoke (`/health`, `/metrics`, `docker compose ps`). Force-recreate prometheus ONLY if `docker/prometheus*` changed. All via `ssh prod` (`212.72.189.15:2296`, app dir `/home/user/TG_parser`). **Rollback = `git checkout 61637d1 && docker compose build tg_parser && docker compose up -d`.**
