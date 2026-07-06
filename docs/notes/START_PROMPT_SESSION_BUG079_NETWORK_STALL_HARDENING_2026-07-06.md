# START_PROMPT — BUG-079: harden against recurring Anthropic 300s aggregate-timeout network stalls in Sonnet topicization

**Created:** 2026-07-06. This is a **MIXED CODE + OPS-TUNING** start-prompt: two env-only knob changes (that MUST be mirrored into the docker-compose allow-list, BUG-078 class), **one real code change** (making the per-attempt httpx read timeout configurable + shrinking it), an aggregate-timeout retune, and a host↔Anthropic network-path investigation. It is the entry-point prompt for the session that finally makes multi-chunk full-run topicization drainage **reliable**.
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`. **Prod:** `ssh prod` → `/home/user/TG_parser`.
**Local HEAD:** `1135882` (`docs(bug-076,077): mark resolved after controlled chunked exercise; file BUG-079`) — this is a **docs-only** commit on top of the last code/deploy commit `78c3b93` (`fix(deploy): mirror TOPICIZATION_FULL_* into tg_parser env allow-list (BUG-078)`). **Verify prod HEAD in §1** — expected `78c3b93` (or newer if docs were also deployed).
**Status:** BUG-079 is 🚨 **`open`** (filed 2026-07-04, commit `1135882`). Remediation is **proposed but NOT implemented**. This session implements it.

> **Read in order before touching anything:**
> 1. The `### BUG-079` section in [`BUG_LOG.md`](BUG_LOG.md) (commit `1135882`) — the authoritative problem statement, evidence, root-cause hypothesis, and proposed fix. This start-prompt is the executable form of that row's *Proposed fix*.
> 2. The `### BUG-078` section in [`BUG_LOG.md`](BUG_LOG.md) — the **docker-compose `environment:` allow-list footgun** that every env knob in this session shares. Read the `Update 2026-07-04 — RESOLVED` row for the exact mechanism (OS-env priority over the bind-mounted `/app/.env`).
> 3. The `### BUG-076` / `### BUG-077` sections in [`BUG_LOG.md`](BUG_LOG.md), especially the `Update 2026-07-04 — RESOLVED (controlled chunked exercise performed)` row — the validation run during which BUG-079 was discovered (murashko chunk 2 burned ~809K tokens / 0 cards), and the one caveat left open (crash-resume-across-container-restart proven-by-mechanism, not literally exercised).
> 4. [`START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md`](START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md) — the verify-live discipline (log echo / `/health`, NOT `docker compose exec ... python -c`) this session reuses for every knob it touches.
> 5. [`START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md`](START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md) — the controlled-exercise / kill-switch / watch discipline reused by the optional Phase 2 validation (§7).
> 6. [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (repo root) — deploy / rollback / smoke-check (the §4 code change + compose edit → a real rebuild + force-recreate).

---

## ⛔ OPERATIONAL WARNINGS — READ FIRST

1. **The BUG-078 compose allow-list trap applies to EVERY env knob in this session.** The `tg_parser` compose service uses an explicit `environment:` **allow-list** (not `env_file: .env`), and pydantic-settings gives **OS-env priority over the bind-mounted `/app/.env`**. Any knob you set in `.env` that is **not** mirrored into that allow-list is **SILENTLY IGNORED** by the running worker — it falls back to the code `Field` default. This is exactly BUG-078. **None** of `TOPICIZATION_BATCH_CONCURRENCY`, `TOPICIZATION_BATCH_SIZE`, `ANTHROPIC_CALL_TIMEOUT_S` are in that allow-list today (verified below). **Mirroring into `docker-compose.yml` + redeploy + a live-verify is a REQUIRED step for every knob you touch — not optional.**
2. **The per-attempt httpx read timeout (120s) is NOT env-configurable — shrinking it is a CODE change.** The factory constructs `AnthropicClient` **without** passing `timeout=`, so the `__init__` default `timeout: float = 120.0` is a **hardcoded constant**. There is no `ANTHROPIC_HTTP_TIMEOUT_S` today. Making it 60s requires adding a settings field + threading it through the factory (see §4). Do not try to "set an env var" for it — there is no env var to set.
3. **Do NOT raise `anthropic_call_timeout_s` (300s) in isolation.** Raising the aggregate budget while the per-attempt httpx timeout is still 120s just lets **more** stalled 120s attempts pile up inside a longer budget — it makes the burn *worse*, not better. The aggregate retune (§knob 4) is only valid **in tandem with** the per-attempt shrink (§knob 3): fast-failing 60s attempts + one healthy retry that fits.
4. **Anthropic API calls cost real money and this class of bug BURNS tokens for 0 cards.** During the 2026-07-04 validation, murashko chunk 2 burned ~809K Sonnet tokens and persisted **0** cards to a stall. The hardening itself (§2–§6) is a config/code exercise that spends **nothing** if you do NOT fund the balance. The optional Phase 2 validation (§7) DOES spend money (~$20–30) and is gated behind explicit user sign-off + channel isolation.
5. **This is NOT rate-limiting.** The 429 / `anthropic_retryable` count on the key was **0** throughout the incident. Do not "fix" this by touching the rate limiter or backoff — the stall is a network read stall in httpx `_receive_response_headers`, amplified by the timeout config. The rate limiter is shared **per API key** (`factory.py` `_get_or_create_rate_limiter`), so concurrency reductions (§knob 1) reduce simultaneous in-flight reads against the same shared budget — relevant context, but not the root cause.
6. **AGENTS.md conventions apply.** No `git commit` without an explicit user request. Do not create/edit `docs/methodology/**`. Do **not** edit `pyproject.toml` / `requirements.txt`. Accepted ADRs (`docs/adr/`) and JSON Schemas (`docs/contracts/`) are binding. The §4 code change is small but still needs explicit approval before commit/deploy.

---

## TL;DR

During the 2026-07-04 BUG-076/077 controlled chunked full-topicization validation, the Sonnet topicization stage **repeatedly stalled** on `LLMCallTimeoutError: Anthropic generate_with_usage exceeded 300.0s aggregate wall-clock timeout`. The cancelled tracebacks unwind inside httpx `_receive_response_headers` — a **network read stall** waiting on response headers from `api.anthropic.com`, accompanied by `anthropic_network_error` events with **empty** error strings. It is **NOT** rate-limiting (429 count = 0) and **NOT** cross-channel contention (it recurred with all 13 other channels paused). It wastes Sonnet tokens (murashko chunk 2: ~809K tokens / 0 cards) and is the **reliability blocker** that prevented an airtight full multi-chunk drain — the last thing standing between BUG-076/077 "proven" and BUG-076/077 "airtight."

**Root cause (hypothesis, not yet code-pinned):** a network read stall on the host↔`api.anthropic.com` path, **amplified by the timeout configuration** — a per-attempt httpx `timeout=120s` (hardcoded default, NOT env-configurable) means one stalled read holds a slot up to 120s, and the `anthropic_call_timeout_s=300.0` **aggregate** wall-clock wrapper (wrapping `rate_limiter.acquire()` + the full 429/5xx retry loop + backoff) means a sequence of stalled retries eats the whole 300s budget before a healthy retry can complete → `LLMCallTimeoutError`.

**The hardening plan (ordered, by change class):** (1) `topicization_batch_concurrency` 5→2 — ENV + compose mirror; (2) `topicization_batch_size` 50→25 — ENV + compose mirror; (3) per-attempt httpx read timeout 120s→~60s — **CODE change** (new settings field + factory threading) + compose mirror; (4) `anthropic_call_timeout_s` retune — ENV + compose mirror, **only in tandem with #3**; (5) network-path investigation (DNS/egress/TLS/proxy/header latency). Then verify each knob is live **in the worker** (not just in `.env`), measure the stall-rate improvement, and — optionally, gated + funded — run an airtight multi-chunk Phase 2 validation (§7) that also finally exercises the residual BUG-076/077 crash-resume-across-container-restart caveat.

---

## 1. Pre-flight — verify current state BEFORE touching anything (read-only)

> **Command-mechanics note (carried from the BUG-076/077/078 runbooks):** `$POSTGRES_USER` / `$POSTGRES_DB` resolve **only inside the `postgres` container**, so every `psql` is wrapped `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "<SQL>"'`. Prometheus port 9090 is **not** published to the host — query via `docker compose exec -T prometheus wget …`. Grafana host port `3001` is published. `/health` and `/metrics` are on host `:8000`.

1. **Prod HEAD + services healthy:**
   ```bash
   ssh prod "cd /home/user/TG_parser && git rev-parse --short HEAD && docker compose ps"
   # expect: 78c3b93 (last code/deploy) or 1135882 if docs were also pulled ; all default-profile services healthy
   ```
2. **Confirm the current (unhardened) defaults are what the code says** — read-only, via the running worker's own signals where possible. The static defaults (pinned from source at HEAD `1135882`, see §8):
   - `topicization_batch_concurrency = 5`, `topicization_batch_size = 50`, `anthropic_call_timeout_s = 300.0`
   - per-attempt httpx timeout `= 120.0` (hardcoded in `AnthropicClient.__init__`, NOT env-configurable — §8 item 2/3).
3. **Confirm NONE of the three env knobs are currently in the compose allow-list** (the BUG-078 trap — this is *why* changing `.env` alone won't work):
   ```bash
   ssh prod "cd /home/user/TG_parser && grep -nE 'TOPICIZATION_BATCH_(CONCURRENCY|SIZE)|ANTHROPIC_CALL_TIMEOUT_S|ANTHROPIC_HTTP_TIMEOUT' docker-compose.yml || echo 'NONE MIRRORED (expected)'"
   # expect: NONE MIRRORED — only TOPICIZATION_FULL_* / RESUMMARIZE_* are in the tg_parser environment: block today
   ```
4. **Confirm the Anthropic balance state** (`[CONFIRM WITH USER]` — no MCP/repo tool for live balance; checked in the Anthropic console). The hardening in §2–§6 spends nothing; only the optional Phase 2 (§7) needs a funded balance. If the balance is empty, that is fine (and is the de-facto safety net per BUG-078) for everything except §7.
5. **Confirm channel isolation baseline** — the 13 channels that were isolated/resumed in the prior session (see §8 "prod ops facts"). For hardening (§2–§6) no isolation is needed; for Phase 2 (§7) they must be paused first, then restored after.
6. **Baseline the stall metrics** for a before/after comparison (§6):
   ```bash
   ssh prod "curl -s http://localhost:8000/metrics | grep -E 'anthropic_network_error|llm_call_timeout|llm_requests_total'"
   ```

---

## 2. The hardening plan — ordered, by change class

Each lever below is tagged **ENV-only**, **CODE-required**, **COMPOSE-mirror**, or **DEPLOY**. The recurring rule (⛔ warning 1): **every env knob you touch MUST be mirrored into the `tg_parser` compose `environment:` allow-list, then redeployed and live-verified** — otherwise the worker silently ignores it.

| # | Lever | Change | Class | Notes |
|---|---|---|---|---|
| 1 | `topicization_batch_concurrency` | **5 → 2** | ENV + **COMPOSE-mirror** + DEPLOY | Fewer simultaneous in-flight reads against the shared per-key rate limiter → less local queueing / contention amplification. |
| 2 | `topicization_batch_size` | **50 → 25** | ENV + **COMPOSE-mirror** + DEPLOY | Smaller per-call payloads → shorter individual reads, less exposure per stalled attempt. |
| 3 | per-attempt httpx read timeout | **120s → ~60s** | **CODE-required** + COMPOSE-mirror (new env var) + DEPLOY | Not env-configurable today (§8 item 3). Add a settings field (`anthropic_http_timeout_s`), thread it through the factory into `AnthropicClient(timeout=…)`, mirror the new env var. Fast-failing attempts so a healthy retry still fits the aggregate budget. |
| 4 | `anthropic_call_timeout_s` | **retune (e.g. keep 300 or raise)** | ENV + **COMPOSE-mirror** + DEPLOY | **ONLY in tandem with #3.** Raising it alone (⛔ warning 3) just lets more stalled 120s attempts pile up. With #3 at 60s, ~2 fast-fail attempts + one healthy retry fit inside 300s. |
| 5 | host↔Anthropic network path | investigate | INVESTIGATION | DNS / egress / TLS handshake / proxy / response-header latency from the prod host to `api.anthropic.com`. See §5. |

**Recommended order of execution:** do the cheap, reversible **ENV-only** knobs (#1, #2) first as a single deploy and observe; then land the **CODE change** (#3) with #4 retuned in the same deploy; run the network investigation (#5) in parallel since it is read-only and may reframe the whole fix.

---

## 3. Knobs #1 & #2 — ENV-only (but MUST be compose-mirrored)

These are pure `Settings` fields; env var name = field name, upper-cased (no prefix, case-insensitive — `model_config` has no `env_prefix`, §8). So the env vars are `TOPICIZATION_BATCH_CONCURRENCY` and `TOPICIZATION_BATCH_SIZE`.

### (a) Mirror into the compose allow-list — REQUIRED FIRST (or the `.env` edit is a no-op)

Add to the `tg_parser` service `environment:` block in `docker-compose.yml` (next to the existing `TOPICIZATION_FULL_*` mirror at lines 84–90 — reuse the exact same `${VAR:-default}` pattern, defaults matched to the **code** defaults so an unset var is inert):
```yaml
      # BUG-079: network-stall hardening knobs — same OS-env-priority gotcha as
      # TOPICIZATION_FULL_* / RESUMMARIZE_* above (BUG-078): MUST be mirrored here
      # or the bind-mounted .env value is ignored and the worker uses code defaults.
      - TOPICIZATION_BATCH_CONCURRENCY=${TOPICIZATION_BATCH_CONCURRENCY:-5}
      - TOPICIZATION_BATCH_SIZE=${TOPICIZATION_BATCH_SIZE:-50}
```
(Leave the compose defaults at the code defaults `5` / `50`; the *tuned* values go in `.env`, so the change is auditable and revertible by editing `.env` alone once the allow-list entry exists.)

### (b) Set the tuned values in prod `.env` (edit IN PLACE — never `sed -i` / atomic-save-rename, per BUG-078; the single-file bind mount `./.env:/app/.env:ro` orphans on inode change)
```env
TOPICIZATION_BATCH_CONCURRENCY=2
TOPICIZATION_BATCH_SIZE=25
```

### (c) Deploy + live-verify (§4 covers the combined deploy if you batch with the code change)
```bash
ssh prod "cd /home/user/TG_parser && docker compose up -d --force-recreate tg_parser"
```
Then verify the **running worker** actually reads the tuned values — see §6 (do NOT trust `docker compose exec ... python -c`; that is the BUG-078 false-green).

---

## 4. Knob #3 — the CODE change (per-attempt httpx read timeout 120s → ~60s)

**Why this is code, not config (⛔ warning 2, §8 items 2–3):** `AnthropicClient.__init__` takes `timeout: float = 120.0` and builds `self._client = httpx.AsyncClient(timeout=timeout)`. The factory (`factory.py:112-124`) constructs `AnthropicClient(...)` **without** passing `timeout=` — it passes `call_timeout=settings.anthropic_call_timeout_s` (the *aggregate* wrapper, which IS env-configurable) but NOT the per-attempt `timeout`. So the 120s per-attempt read timeout is a **hardcoded constant** with no env var behind it.

### Implementation sketch (get explicit approval before commit/deploy, AGENTS.md)
1. **Add a settings field** in `tg_parser/config/settings.py` (near `anthropic_call_timeout_s`, ~line 910), e.g.:
   ```python
   anthropic_http_timeout_s: float = Field(
       default=60.0,  # BUG-079: was a hardcoded 120.0 in AnthropicClient.__init__
       description=(
           "BUG-079: per-HTTP-attempt httpx read timeout (seconds) for a single "
           "Anthropic request. Distinct from anthropic_call_timeout_s (the aggregate "
           "wall-clock wrapper). Shrunk from the old hardcoded 120s so a stalled "
           "_receive_response_headers read fails FAST and a healthy retry still fits "
           "the aggregate budget."
       ),
       ge=5.0,
   )
   ```
2. **Thread it through the factory** — `tg_parser/processing/llm/factory.py:112-124`, add to the `AnthropicClient(...)` construction:
   ```python
       timeout=kwargs.pop("timeout", settings.anthropic_http_timeout_s),
   ```
   (mirror the existing `call_timeout=kwargs.pop("call_timeout", settings.anthropic_call_timeout_s)` pattern at lines 120–122). Optionally drop the `__init__` default from `120.0` to make the new default authoritative, but keeping it is harmless once the factory always passes the value.
3. **Mirror the new env var** into the `docker-compose.yml` `tg_parser` allow-list (same block as §3a):
   ```yaml
      - ANTHROPIC_HTTP_TIMEOUT_S=${ANTHROPIC_HTTP_TIMEOUT_S:-60}
   ```
4. **Tests:** add a unit test that constructs a client via the factory with a settings object and asserts the resulting `AnthropicClient._client.timeout` reflects `anthropic_http_timeout_s` (and that the env var overrides it). Consider a test injecting a slow/stalling transport to assert the per-attempt timeout fires before the aggregate budget — the interaction BUG-079's *Why CI didn't catch* row calls out as untested.
5. Run the repo test suite + `ruff`; get approval; deploy per `PRODUCTION_DEPLOYMENT.md` (this is a real image rebuild + force-recreate).

### Knob #4 — aggregate retune, in tandem ONLY
With #3 at 60s per attempt, the aggregate `anthropic_call_timeout_s` (env `ANTHROPIC_CALL_TIMEOUT_S`, default 300.0, IS env-configurable + mirror it into the allow-list) can stay at 300 (comfortably fits ~2 fast-fail attempts + one healthy retry + a 60s 429 retry-after) or be tuned deliberately. **Never raise it without #3 shipped** (⛔ warning 3). Mirror it into the allow-list the same way (`ANTHROPIC_CALL_TIMEOUT_S=${ANTHROPIC_CALL_TIMEOUT_S:-300}`).

---

## 5. Knob #5 — host↔Anthropic network-path investigation (read-only)

The timeout config amplifies the stall, but the stall *originates* on the network path (it persisted under full channel isolation, so local queueing is not the sole cause). Investigate from the prod host:
- **DNS:** resolution latency / flapping for `api.anthropic.com` (`dig`, repeated; check for slow or rotating answers).
- **Egress / firewall / NAT:** any egress proxy, connection-count caps, or idle-connection reaping on the path.
- **TLS:** handshake latency (`curl -w` timing breakdown: `time_namelookup`/`time_connect`/`time_appconnect`/`time_starttransfer`), MITM proxy, cert re-negotiation.
- **Header-receipt latency:** the stall is specifically in httpx `_receive_response_headers` (waiting on response headers) — measure `time_starttransfer` (TTFB) against `api.anthropic.com` under load; a high/variable TTFB points at Anthropic-side or path-side header latency rather than the client.
- Correlate spikes with the observed `anthropic_network_error` (empty error string) events in the worker logs.

This may reframe the fix (e.g. an egress proxy is the real culprit); run it early and in parallel with §3–§4.

---

## 6. Verification plan — prove each knob is LIVE in the worker, then measure improvement

**Per-knob live-verify (the BUG-078 discipline — do NOT use `docker compose exec ... python -c`, that is the false-green):**
- The worker already echoes effective settings at startup and via `/health` (BUG-078 fix, commits `338b0d8` / `78c3b93`). If the BUG-078 startup echo / `/health` surfaces only the `topicization_full_*` family today, **extend the same echo** (in `tg_parser/api/main.py`, next to the existing "Environment: LLM provider=…" log) to also print `topicization_batch_concurrency`, `topicization_batch_size`, `anthropic_call_timeout_s`, and the new `anthropic_http_timeout_s` — so the FIRST log lines of every boot record what the running singleton actually parsed. (Small additive change; same class as the BUG-078 observability fix.)
- After force-recreate, read the values from the running process's OWN signals:
  ```bash
  ssh prod "cd /home/user/TG_parser && docker inspect -f '{{.State.StartedAt}}' \$(docker compose ps -q tg_parser)"
  ssh prod "cd /home/user/TG_parser && docker logs tg_parser --since <StartedAt> 2>&1 | grep -iE 'batch_concurrency|batch_size|call_timeout|http_timeout'"
  # and/or the /health field if you extend it
  ```
  Only trust a value that the running worker echoed — NOT a fresh `python -c` process (which reads `/app/.env` directly and prints the .env value regardless of the worker's allow-list-shadowed reality).

**Measure stall-rate improvement (before vs after, using the §1 item 6 baseline):**
```promql
# Aggregate-timeout failures should drop toward 0
increase(tg_parser_anthropic_network_error_total[1h])         # (use the actual metric name from api/metrics.py)
# LLMCallTimeoutError surfaced as per-doc failures — should drop
# Sonnet error ratio on the topicization stage
sum(rate(tg_parser_llm_requests_total{model=~".*sonnet.*",status="error"}[30m]))
  / sum(rate(tg_parser_llm_requests_total{model=~".*sonnet.*"}[30m]))
```
(Confirm the exact metric names in `tg_parser/api/metrics.py` — `anthropic_network_error` / the `llm_requests_total{status=error}` series — before relying on the queries.) Success = the aggregate-timeout stall events fall to near-zero across a multi-chunk run, and Sonnet error-ratio drops materially vs the 2026-07-04 baseline.

---

## 7. OPTIONAL Phase 2 — airtight BUG-076/077 validation (GATED, costs money)

After the hardening lands and stalls are demonstrably reduced (§6), optionally run the **airtight** multi-chunk validation that BUG-079 blocked. This is what upgrades BUG-076/077 from "proven-by-mechanism" to "literally exercised."

**Goals:**
1. Drain **≥2–3 committed chunks** of a large 0-card channel end-to-end with NO stall aborting the run (the multi-chunk drain BUG-079 prevented).
2. Explicitly exercise **crash-resume-across-container-restart** — the ONE caveat left open at BUG-076/077 closure (currently proven-by-mechanism only: the checkpoint is Postgres-persisted and resume-across-invocations was shown, but a mid-run `docker compose restart tg_parser` between committed chunks was never literally done). Do it: let chunk 1 commit, restart the container mid-run, confirm chunk 2 resumes from the checkpoint (not from 0), losing ≤1 chunk.

**Cost reality (from the 2026-07-04 runs):** each murashko chunk ≈ **$5–8**; a 2–3 chunk airtight validation ≈ **$20–30**. `[CONFIRM WITH USER]` before spending.

**Ordering discipline (avoid the propagation-race that bit the 2026-07-04 attempts):**
1. **Isolate first** — pause all other active channels (the 13-channel list in §8) so the funded run exercises exactly the target channel with no cross-channel spend.
2. **Fund AFTER isolation** — top up the Anthropic balance only once isolation is confirmed, and **wait for balance propagation** before resuming the target channel (the 2026-07-04 attempts hit a propagation race where the run started against a not-yet-propagated balance).
3. Run per the BUG-076/077 controlled-enable runbook §4–§6 (verify flag live → resume → watch chunk-by-chunk).
4. **Always restore** — resume every paused channel afterward (§8 restore list).

`murashko_med` is the throwaway test channel (soft-deleted, ~17,848 docs) — the natural target for a large multi-chunk drain; re-adding/resuming it for the exercise is acceptable precisely because it is disposable.

---

## 8. Safety rails, code facts, and pointers

### Safety rails (reuse the proven set from BUG-076/077/078)
- **EMERGENCY monolithic-line stop:** if the legacy monolithic path ever runs (the `topicization.py` "Large channel (%d docs), %d batches of %d" log), STOP — that is the BUG-076/078 smoking gun that the chunked flag is not live.
- **BILLING stop:** any `AnthropicBillingError` → the empty-balance safety net is doing its job; do not top up mid-incident.
- **STALL cap:** if `LLMCallTimeoutError` / `anthropic_network_error` counts climb during a run, treat it as BUG-079 recurring — re-pause and reassess before spending more.
- **Token cap:** keep `TOPICIZATION_FULL_RUN_TOKEN_BUDGET` (auditable per-invocation cap) set for any Phase 2 run.
- **Empty-balance-is-the-safety-net:** processing AND topicization both need the Anthropic API; an empty balance means nothing can burn. Keep it empty until §7 is explicitly greenlit.
- **`remove_channel` to stop drip:** prefer `remove_channel` over `pause_channel` if a billing-backoff cycle could clobber a manual pause (BUG-078 kill-switch-clobber caveat).
- **Always restore:** resume every paused channel after any isolated run.

### Code facts pinned (verified against source at local HEAD `1135882`)
1. **`tg_parser/config/settings.py:363-368`** — `topicization_batch_concurrency: int = Field(default=5, …, ge=1, le=20)`. Env: `TOPICIZATION_BATCH_CONCURRENCY`.
2. **`tg_parser/config/settings.py:371-376`** — `topicization_batch_size: int = Field(default=50, …, ge=10, le=500)`. Env: `TOPICIZATION_BATCH_SIZE`.
3. **`tg_parser/config/settings.py:910-924`** — `anthropic_call_timeout_s: float = Field(default=300.0, …, ge=10.0)` — the **aggregate** wall-clock wrapper; its own docstring notes the per-HTTP-attempt httpx timeout is a separate **120s**. Env: `ANTHROPIC_CALL_TIMEOUT_S` (IS env-configurable — factory passes it, item 6).
4. **`tg_parser/config/settings.py:84-88`** — `model_config = SettingsConfigDict(env_file=…, extra="ignore")`, **no `env_prefix`** → env var name = field name, case-insensitive (upper-case form used above).
5. **`tg_parser/processing/llm/anthropic_client.py:59-84`** — `AnthropicClient.__init__(…, timeout: float = 120.0, …, call_timeout: float | None = None)`; line 75 `self._client = httpx.AsyncClient(timeout=timeout)`; line 84 `self._call_timeout = call_timeout`. The **per-attempt httpx read timeout is this hardcoded `120.0` default.**
6. **`tg_parser/processing/llm/anthropic_client.py:136-157`** — `generate_with_usage` wraps `_generate_with_usage_inner` in `asyncio.wait_for(..., timeout=self._call_timeout)` and raises `LLMCallTimeoutError("… exceeded {self._call_timeout}s aggregate wall-clock timeout")` on `TimeoutError`. **`:203-208`** — the retry loop (`for attempt in range(1, self._max_retries + 1): if self.rate_limiter: await self.rate_limiter.acquire(...); response = await self._client.post(...)`) — the aggregate `wait_for` wraps `acquire()` + this whole 429/5xx retry loop + backoff.
7. **`tg_parser/processing/llm/factory.py:112-124`** — constructs `AnthropicClient(...)` passing `call_timeout=kwargs.pop("call_timeout", settings.anthropic_call_timeout_s)` **but NOT `timeout=`** → the per-attempt httpx 120s is a **hardcoded default, NOT env-configurable**. Shrinking it requires the §4 code change. **`factory.py:21-30`** — `_get_or_create_rate_limiter` caches one `LLMRateLimiter` **per api_key** (org-level limits) → concurrency is shared per key.
8. **`docker-compose.yml:48-110`** — the `tg_parser` service `environment:` **allow-list**. Only `TOPICIZATION_FULL_*` (lines 84-90) and `RESUMMARIZE_*` (76-79) + LLM/DB/Telegram vars are mirrored. **`TOPICIZATION_BATCH_CONCURRENCY`, `TOPICIZATION_BATCH_SIZE`, `ANTHROPIC_CALL_TIMEOUT_S` are NOT present** → per BUG-078, changing them in `.env` alone is silently ignored by the running worker. Lines 80-83 document the OS-env-priority gotcha explicitly.

### Prod ops facts
- `ssh prod` → host `212.72.189.15:2296`, app dir `/home/user/TG_parser`. Prod HEAD expected `78c3b93` (verify §1).
- MCP server: `user-tg-parser` (channel management, `pause_channel` / `resume_channel` / `remove_channel` / `add_channel`, pipeline triggers, search).
- **13-channel isolate/resume list** (from the prior session — pause these for a Phase 2 isolated run, resume ALL afterward): `AgeManagment`, `BiocodebySechenov`, `Docma_ru`, `Lab4health`, `LongevityClub`, `foodf4thought`, `genotek`, `kdl_ru`, `labdiagnostica_logical`, `mediamedics`, `medportal_rfed`, `mind_rise`, `profendocrinologist`.
- `murashko_med` — throwaway test channel, soft-deleted, ~17,848 docs; the natural large multi-chunk drain target for §7.

### Pointers / reading list
- [`BUG_LOG.md`](BUG_LOG.md) — `### BUG-079` (this incident, commit `1135882`), `### BUG-078` (the compose allow-list footgun, `Update 2026-07-04` row), `### BUG-076` / `### BUG-077` (the validation that surfaced BUG-079 + the residual crash-restart caveat).
- [`START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md`](START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md) — verify-live discipline reused here.
- [`START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md`](START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md) — controlled-exercise / kill-switch / watch discipline for §7.
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) — deploy / rollback / smoke for the §4 code + compose change.
- Source: `tg_parser/config/settings.py` (:363-376, :910-924, :84-88), `tg_parser/processing/llm/anthropic_client.py` (:59-84, :136-157, :203-208), `tg_parser/processing/llm/factory.py` (:21-30, :112-124), `docker-compose.yml` (:48-110), `tg_parser/api/metrics.py` (metric names for §6), `tg_parser/api/main.py` (startup echo site to extend for §6).

---

## 9. Pre-flight checklist (read-only) & closeout criteria

**Pre-flight (read-only, do before any change):**
- [ ] Prod HEAD + services healthy (§1 item 1).
- [ ] Current defaults confirmed (§1 item 2): concurrency 5 / batch 50 / aggregate 300 / per-attempt 120 hardcoded.
- [ ] Confirmed NONE of the three env knobs are in the compose allow-list (§1 item 3).
- [ ] Balance state confirmed with user (§1 item 4) — empty is fine for §2–§6.
- [ ] Baseline stall metrics captured (§1 item 6).

**Closeout criteria:**
- **BUG-079 → `resolved`** when: knobs #1/#2 are live-verified in the worker (§6), the #3 code change (+ #4 retune) is shipped/deployed/live-verified, and a multi-chunk run shows aggregate-timeout stall events at near-zero with a materially lower Sonnet error-ratio vs the 2026-07-04 baseline (§6). Update the `### BUG-079` row with the observed before/after numbers and the pinned network-path finding (§5).
- **Residual BUG-076/077 caveat upgraded** — if the optional §7 Phase 2 is run and includes the explicit mid-run container restart, update the BUG-076/077 `Update 2026-07-04` caveat from "proven-by-mechanism" to "literally exercised (crash-resume across container restart, 2026-07-06)."
- All doc-status edits are `docs/notes/BUG_LOG.md` changes; **committing still requires an explicit user request** (AGENTS.md).
