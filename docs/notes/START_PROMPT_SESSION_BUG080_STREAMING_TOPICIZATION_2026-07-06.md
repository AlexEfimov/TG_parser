# START_PROMPT — BUG-080: switch Anthropic topicization generation to STREAMING so the httpx read timeout is a true inter-chunk stall-guard (not a full-generation-latency proxy)

**Created:** 2026-07-06. This is a **CODE start-prompt**: a real change to `AnthropicClient` — introduce a **streaming (`stream: true`) SSE code path** for the Anthropic Messages API so the per-attempt httpx read timeout measures **inter-chunk gaps** (a genuinely dead/stalled socket) instead of the total time to receive the response headers of a slow-but-healthy non-streaming generation. This is the **structural long-term fix** that follows BUG-079: BUG-079 was resolved by a *correct-but-blunt* mitigation (per-attempt `anthropic_http_timeout_s` 60→**150s**, aggregate `anthropic_call_timeout_s` 300→**420s**), which had to be padded to the worst-case generation length because the read timeout could not tell a healthy 90s generation from a dead socket. Streaming lets that per-attempt timeout shrink again to a tight true stall-guard.
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`. **Prod:** `ssh prod` → `/home/user/TG_parser`.
**Local HEAD:** `db629df` (verify with `git rev-parse --short HEAD` — should be `db629df` or later). BUG-079's corrective retune shipped in commit `57d1bce` (150/420) on top of the initial hardening `9069396` (60/300, since disproven); both are on `origin/main`.
**Status:** BUG-080 is **`open`** (filed 2026-07-06, Low/Medium — enhancement / reliability). This is **NOT on fire** — BUG-079 is resolved and topicization is reliable today. This session ships the structural improvement over that blunt mitigation. Remediation is **proposed but NOT implemented**.

> **Read in order before touching anything:**
> 1. The `### BUG-080` section in [`BUG_LOG.md`](BUG_LOG.md) — the authoritative problem statement, root cause (non-streaming returns headers only when the generation is ~complete → the read timeout is a total-latency proxy), proposed fix (streaming), and the minor prompt-caching-no-op secondary finding. This start-prompt is the executable form of that row's *Proposed fix*.
> 2. The `### BUG-079` section in [`BUG_LOG.md`](BUG_LOG.md), especially the `Update 2026-07-06 — RESOLVED` row — the timed experiment that proved non-streaming Sonnet topicization generations return HTTP headers only when ~complete (**3 samples: 89.09s / 89.59s / 87.06s**, all HTTP 200, `stop_reason=end_turn`, TTFB≈total), the corrective 150/420 retune, and the airtight 3-chunk zero-stall validation. This is the origin and the evidence base for BUG-080.
> 3. This file.
> 4. [`START_PROMPT_SESSION_BUG079_NETWORK_STALL_HARDENING_2026-07-06.md`](START_PROMPT_SESSION_BUG079_NETWORK_STALL_HARDENING_2026-07-06.md) — the immediate predecessor; reuse its §7 murashko_med isolate → fund → drain validation discipline (§Validation below) and its BUG-078 compose-allow-list trap treatment.
> 5. [`START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md`](START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md) — the verify-live discipline (startup log echo / `/health`, NOT `docker compose exec ... python -c`) reused for the new streaming flag.
> 6. [`START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md`](START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md) — the controlled-exercise / kill-switch / watch discipline reused by the optional funded validation.
> 7. [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) (repo root) — deploy / rollback / smoke-check. BUG-079 used a **file-sync deploy** + `docker compose up -d --force-recreate tg_parser`.

---

## ⛔ OPERATIONAL WARNINGS — READ FIRST

1. **`AnthropicClient` is SHARED across EVERY LLM stage — streaming must NOT break the non-topicization call-sites.** The factory builds one `AnthropicClient` for **processing, topicization, RAG, digest, and resummarize** (`resolve_llm_config(stage)` → `create_llm_client(...)`; every Anthropic stage flows through `factory.py:100-125`). The streamed path MUST return an **identical** `LLMResponse(text, input_tokens, output_tokens, stop_reason)` contract as the non-streaming path — same `_extract_text_content` semantics, same `stop_reason` surfacing (BUG-071 relies on it), same billing/retry behavior. **Strongly prefer flag-gating streaming ON for topicization only (or globally opt-in, default OFF)** so a regression in SSE parsing cannot silently corrupt processing/RAG/digest output. Do NOT make streaming unconditionally always-on in one shot.
2. **Usage accounting is DIFFERENT in streaming and WILL regress token budgets/metrics if aggregated wrong.** Non-streaming returns a single `usage` object (`data.get("usage")` → `input_tokens` / `output_tokens`, `anthropic_client.py:259-290`). In the SSE stream: `message_start` carries `message.usage.input_tokens` (+ `cache_creation`/`cache_read` input tokens) and an **initial** `output_tokens`, and the FINAL `message_delta` event carries the **cumulative** `usage.output_tokens`. You MUST take input_tokens from `message_start` and the output_tokens from the terminal `message_delta` (not sum deltas). If you mis-aggregate, the rate-limiter reconciliation (`reconcile_usage`, `anthropic_client.py:263-270`), the token-budget cap (`TOPICIZATION_FULL_RUN_TOKEN_BUDGET`), `tg_parser_llm_tokens_total`, and the `self.total_input_tokens += …` accounting in `topicization.py:1292-1293` all silently drift.
3. **The `anthropic-beta: prompt-caching` header is a NO-OP today — do NOT claim it as a win.** The topicization **system prompt is ~450 tokens**, below Anthropic's **1024-token minimum** for prompt caching, so the `cache_control: {type: ephemeral}` block (`anthropic_client.py:174-192`) never actually caches. The header (`anthropic_client.py:174-175`, `anthropic-beta: prompt-caching-2024-07-31`) currently does nothing. Prompt caching is a **separate, optional, low-value** secondary finding (BUG-080 row) — do NOT bundle a fake "caching win" into the streaming PR. If you touch it at all, do it as an explicit separate item (e.g. drop the header, or move enough static context into the cached prefix to clear 1024 tokens) and MEASURE it.
4. **The 150/420 timeouts are the CURRENT safety net — do NOT drop them before streaming is proven.** With streaming, the per-attempt httpx read timeout semantics **change**: it becomes an **inter-event read timeout** (max gap between SSE events), not a full-generation timeout. A tight value (e.g. 20–30s) is only safe **after** the streamed path is proven in a live multi-chunk drain. Ship streaming first with the timeouts unchanged (150/420 are harmless as an upper bound on a healthy stream), then shrink the per-attempt timeout in a **separate, deliberate** step once streaming is validated (see §Implementation step 6). ⛔ Do NOT shrink the timeout and add streaming in the same untested change.
5. **AGENTS.md conventions apply.** No `git commit` without an explicit user request. Do not create/edit `docs/methodology/**`. Do **not** edit `pyproject.toml` / `requirements.txt` (streaming SSE can be done with the already-vendored `httpx` — no new dependency; do NOT add the Anthropic SDK). Accepted ADRs (`docs/adr/`) and JSON Schemas (`docs/contracts/`) are binding. This is a real code change — get explicit approval before commit/deploy.
6. **BUG-078 compose-allow-list trap applies to the new streaming flag.** The `tg_parser` compose service uses an explicit `environment:` **allow-list** (not `env_file: .env`), and pydantic-settings gives **OS-env priority over the bind-mounted `/app/.env`**. Any new `ANTHROPIC_STREAMING_ENABLED` (or similar) knob you add MUST be mirrored into the `docker-compose.yml` `tg_parser` `environment:` block (next to the `TOPICIZATION_*` mirror) + redeployed + **live-verified via the startup echo / `/health`** (NOT `docker compose exec ... python -c` — that is the BUG-078 false-green) or the running worker silently ignores it and uses the code default.

---

## TL;DR

BUG-079 proved (by a controlled timed experiment on the prod host, real payload) that legitimate **non-streaming** Sonnet topicization generations (`claude-sonnet-4-6`, `max_tokens=8192`, `batch_size=25`, ~8.4k input tokens) take **~87–90s to return HTTP response headers** — 3 samples 89.09s / 89.59s / 87.06s, all HTTP 200, TTFB≈total, because a non-streaming httpx request blocks in `_receive_response_headers` until the model finishes. That forced the per-attempt read timeout up to **150s** (padded above the ~90s measured, toward the ~124s 8192-token worst case) — a **blunt** stall-guard that cannot distinguish a slow-but-healthy generation from a dead socket.

**The structural fix (BUG-080):** convert the topicization generation to **streaming** (`stream: true` on the Messages API; consume the `text/event-stream` SSE: `message_start` → `content_block_start` → `content_block_delta` (text) → `message_delta` (final usage + stop_reason) → `message_stop`). Because a healthy generation emits chunks continuously, the httpx read timeout becomes a **per-event inter-chunk gap** guard — it can shrink back to tens of seconds and fire FAST on a genuinely stalled socket, while never guillotining a healthy 90s generation. The return contract of `generate_with_usage` (`LLMResponse(text, input_tokens, output_tokens, stop_reason)`) is preserved exactly so processing/RAG/digest/resummarize are unregressed.

**Plan:** (1) add a flag-gated streaming SSE path in `AnthropicClient` (default OFF), reusing `httpx.AsyncClient.stream(...)`; (2) parse `content_block_delta` text + accumulate usage from `message_start` (input) and the final `message_delta` (output); (3) preserve the `LLMResponse` contract + the aggregate `asyncio.wait_for` wrapper; (4) unit-test SSE parsing + a gap-stall test + non-streaming/other-stage non-regression; (5) deploy flag-OFF, flip ON for topicization, live-verify; (6) validate a multi-chunk drain on `murashko_med`; (7) ONLY THEN, in a separate step, shrink the per-attempt timeout back toward a true stall-guard.

---

## 1. Pre-flight — verify current state BEFORE touching anything (read-only)

> **Command-mechanics note (carried from BUG-076/077/078/079 runbooks):** `$POSTGRES_USER` / `$POSTGRES_DB` resolve **only inside the `postgres` container**, so every `psql` is wrapped `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "<SQL>"'`. Prometheus port 9090 is **not** published to the host — query via `docker compose exec -T prometheus wget …`. Grafana host port `3001` is published. `/health` and `/metrics` are on host `:8000`.

1. **Local + prod HEAD + services healthy:**
   ```bash
   git rev-parse --short HEAD   # expect db629df or later
   ssh prod "cd /home/user/TG_parser && git rev-parse --short HEAD && docker compose ps"
   # expect: 57d1bce (or later — the BUG-079 corrective retune) ; all default-profile services healthy
   ```
2. **Confirm the current (post-BUG-079) timeouts are what the code says** (§Code facts pinned): `anthropic_http_timeout_s = 150.0`, `anthropic_call_timeout_s = 420.0`. There is **NO streaming flag today** (grep confirms none exists) — you are adding it.
3. **Confirm the AnthropicClient path is non-streaming today** — `_generate_with_usage_inner` does a single `await self._client.post(...)` (`anthropic_client.py:208-212`) then `data = response.json()` (`:259`). No `stream=True`, no SSE.
4. **Baseline the topicization latency + error signals** for a before/after comparison:
   ```bash
   ssh prod "curl -s http://localhost:8000/metrics | grep -E 'anthropic_network_error|llm_request_duration|llm_requests_total|llm_call_timeout'"
   ```
   (`anthropic_network_error` is a **structlog event**, `anthropic_client.py:319`, NOT a Prometheus counter — grep the worker logs for it; the Prometheus series are `tg_parser_llm_requests_total{status="error"}` and `tg_parser_llm_request_duration_seconds`.)
5. **Confirm the Anthropic balance state** (`[CONFIRM WITH USER]` — no MCP/repo tool for live balance). Building + unit-testing streaming spends **nothing**; only the optional funded multi-chunk validation (§Validation) needs a funded balance. Empty balance is fine (and is the de-facto safety net per BUG-078) for everything except the live drain.

---

## 2. § Implementation plan (ordered)

**Get explicit approval before commit/deploy (AGENTS.md). No new dependency — use the already-vendored `httpx` streaming API; do NOT add the Anthropic SDK, do NOT edit `requirements.txt`.**

1. **Add a streaming flag (default OFF).** In `tg_parser/config/settings.py`, next to `anthropic_http_timeout_s` (~line 928), add:
   ```python
   anthropic_streaming_enabled: bool = Field(
       default=False,  # BUG-080: opt-in; default OFF so processing/RAG/digest keep the proven non-streaming path
       description=(
           "BUG-080: consume the Anthropic Messages API as a text/event-stream "
           "(stream=true) so the per-HTTP-attempt httpx read timeout measures "
           "inter-chunk GAPS (a true dead-socket stall-guard) instead of total "
           "generation latency (non-streaming returns headers only when the "
           "generation is ~complete, ~90s for Sonnet topicization — see BUG-079). "
           "Default OFF: flip ON for the topicization stage first, validate a "
           "multi-chunk drain, then consider shrinking anthropic_http_timeout_s."
       ),
   )
   ```
   Thread it through the factory (`factory.py:100-125`) into `AnthropicClient(...)` — mirror the existing `timeout=kwargs.pop("timeout", settings.anthropic_http_timeout_s)` (line 120) pattern, e.g. `streaming=kwargs.pop("streaming", settings.anthropic_streaming_enabled)`. Store it on `self._streaming` in `__init__`. **Decision needed** (§Ambiguity): a single global flag applies to all stages; if you want topicization-only, gate it at the topicization call-site instead (pass `streaming=True` as a per-call kwarg through `generate_with_usage(**kwargs)` → down to the client) rather than the global setting. **Recommended: global `anthropic_streaming_enabled` setting, default OFF**, since the streamed path returns an identical contract and there is no reason processing/RAG can't also benefit once proven — but keep it OFF until validated.
2. **Add the streaming SSE branch** inside `_generate_with_usage_inner` (`anthropic_client.py:159-334`). When `self._streaming` is true, set `payload["stream"] = True` and, inside the retry loop, replace `response = await self._client.post(...)` (`:208-212`) with an `async with self._client.stream("POST", self.BASE_URL, headers=headers, json=payload) as response:` block. Keep the existing status-code handling (`_RETRYABLE_STATUS_CODES`, 400/billing, `raise_for_status`) — note that with streaming you must `await response.aread()` (or check `response.status_code` before iterating) to inspect an error body, since the body is otherwise lazily streamed. Then iterate `async for line in response.aiter_lines():` and parse the SSE frames.
3. **Parse the SSE event stream** into `(text, usage, stop_reason)`:
   - Lines come as `event: <type>` / `data: <json>` pairs (blank-line-separated). Accumulate the JSON on each `data:` line and dispatch on the `type` field.
   - `message_start` → `data.message.usage.input_tokens` (also `cache_creation_input_tokens` / `cache_read_input_tokens`) and the initial `output_tokens`.
   - `content_block_delta` with `delta.type == "text_delta"` → append `delta.text` to the accumulated text buffer.
   - `message_delta` → `data.delta.stop_reason` (final `stop_reason`) and `data.usage.output_tokens` (the **cumulative** final output token count — use THIS for output_tokens, do not sum deltas).
   - `message_stop` → end of stream.
   - Build the SAME `LLMResponse(text=<buffer>, input_tokens=<from message_start>, output_tokens=<from final message_delta>, stop_reason=<from message_delta>)` — identical contract to the non-streaming return (`:281-290`). Preserve the `_extract_text_content` empty-content semantics (empty text = "" not an exception) and the rate-limiter reconciliation (`:263-270`).
4. **Preserve the aggregate `asyncio.wait_for` wrapper** (`generate_with_usage`, `:110-157`) unchanged — it still bounds the whole call (rate-limiter acquire + retry loop). With streaming, the per-attempt `timeout` (the httpx client's read timeout) now bounds the max gap between SSE reads.
5. **Mirror the flag into `docker-compose.yml`** `tg_parser` `environment:` allow-list (BUG-078, ⛔ 6): `- ANTHROPIC_STREAMING_ENABLED=${ANTHROPIC_STREAMING_ENABLED:-false}` (compose default = code default `false`; the tuned value goes in `.env`). **Extend the BUG-078 startup echo** (in `tg_parser/api/main.py`, next to the "Environment: LLM provider=…" log) to print the effective `anthropic_streaming_enabled` + `anthropic_http_timeout_s` so the running worker's real value is observable at boot.
6. **(SEPARATE, LATER step — do NOT bundle):** after streaming is proven in a live multi-chunk drain (§Validation), shrink `anthropic_http_timeout_s` back toward a true stall-guard (e.g. 150s → ~20–30s inter-event gap). ⛔ warning 4 — do this only once streaming is validated; keep 150/420 until then.

---

## 3. § Tests

Add under `tests/` (respect `tests/README.md` modes). No live API — mock the transport.
1. **SSE parse happy-path (unit):** feed a mocked `text/event-stream` (a canned sequence: `message_start` with `input_tokens`, several `content_block_delta` text deltas, a final `message_delta` with `stop_reason=end_turn` + cumulative `output_tokens`, `message_stop`) via a stub `httpx` transport / `MockTransport`, call `generate_with_usage(streaming=True)`, and assert the returned `LLMResponse.text` == concatenated deltas, `input_tokens` == the `message_start` value, `output_tokens` == the final `message_delta` value, and `stop_reason == "end_turn"`. This is the acceptance test the BUG-080 "Why CI didn't catch → N/A" row wants to exist.
2. **Gap-stall trips the read timeout FAST (unit):** a mocked stream that emits `message_start` then STALLS (no further events) beyond the per-attempt `timeout` must raise the timeout quickly (well before the aggregate `call_timeout`), proving the inter-chunk stall-guard works. Contrast with a healthy stream that emits within the gap and completes.
3. **Truncation still detected (unit):** a stream whose final `message_delta` has `stop_reason == "max_tokens"` must surface `LLMResponse.stop_reason == "max_tokens"` so the topicization shrink-and-retry path (`topicization.py:1297-1306`) still fires.
4. **Non-regression — non-streaming path unchanged (unit):** with `streaming=False` (default), the existing `post(...)` + `response.json()` path is untouched and returns the same `LLMResponse` — protects processing / RAG / digest / resummarize.
5. **Contract-equivalence (unit):** given equivalent inputs, the streamed and non-streamed paths produce the same `LLMResponse` shape (same fields populated), so downstream token accounting (`total_input_tokens`/`total_output_tokens`, `reconcile_usage`, `tg_parser_llm_tokens_total`) is identical.
6. Run the repo suite + `ruff`; get approval.

---

## 4. § Deploy + live-verify (BUG-078 discipline)

1. Deploy per `PRODUCTION_DEPLOYMENT.md` — BUG-079 used a **file-sync deploy** to prod then `ssh prod "cd /home/user/TG_parser && docker compose up -d --force-recreate tg_parser"` (real force-recreate so the long-lived worker re-reads settings). Ship with `ANTHROPIC_STREAMING_ENABLED` **unset / false first** (dark), confirm no regression on the existing non-streaming path.
2. **Live-verify the flag is actually live in the WORKER** (NOT `docker compose exec ... python -c` — BUG-078 false-green):
   ```bash
   ssh prod "cd /home/user/TG_parser && docker inspect -f '{{.State.StartedAt}}' \$(docker compose ps -q tg_parser)"
   ssh prod "cd /home/user/TG_parser && docker logs tg_parser --since <StartedAt> 2>&1 | grep -iE 'streaming|http_timeout'"
   # and/or the /health field if you surface it
   ```
   Only trust a value the running worker echoed at boot.
3. Confirm the mirror is present so `.env` is honored:
   ```bash
   ssh prod "cd /home/user/TG_parser && grep -n 'ANTHROPIC_STREAMING_ENABLED' docker-compose.yml || echo 'NOT MIRRORED — .env will be ignored'"
   ```
4. Flip `ANTHROPIC_STREAMING_ENABLED=true` in prod `.env` (edit **in place** — never `sed -i` / atomic-save-rename, per BUG-078; the single-file bind mount `./.env:/app/.env:ro` orphans on inode change), `--force-recreate`, re-verify live.

---

## 5. § Validation (reuse BUG-079 §7 murashko_med discipline — GATED, costs money)

Prove the streamed path drains a **multi-chunk** run with the per-attempt timeout able to be small again, and that non-topicization stages are unregressed.

**Ordering discipline (avoid the propagation-race that bit prior attempts):**
1. **Isolate first** — pause all other active channels (the 13-channel list in the BUG-079 start-prompt §8) so the funded run exercises exactly the target channel with no cross-channel spend.
2. **Fund AFTER isolation** — top up the Anthropic balance only once isolation is confirmed; wait for balance propagation before resuming the target.
3. Resume `murashko_med` (throwaway test channel, soft-deleted, ~17,848 docs — the natural large multi-chunk drain target) and watch chunk-by-chunk per the BUG-076/077 controlled-enable runbook.
4. **Assert:** ≥2–3 committed chunks drain end-to-end with streaming ON, **ZERO** `anthropic_network_error` / `LLMCallTimeoutError`, streamed generations produce the same card counts / token accounting as the non-streaming baseline, and (once you shrink the per-attempt timeout in the separate step) a small inter-event timeout does NOT guillotine healthy generations.
5. **Always restore** — resume every paused channel afterward.

**Cost reality (from the 2026-07-04/06 runs):** each murashko chunk ≈ **$5–8**; a 2–3 chunk validation ≈ **$20–30**. `[CONFIRM WITH USER]` before spending. Keep `TOPICIZATION_FULL_RUN_TOKEN_BUDGET` set as the per-invocation cap.

---

## 6. § Code facts pinned (verified against source at local HEAD `db629df`)

1. **`tg_parser/processing/llm/anthropic_client.py:56-57`** — `BASE_URL = "https://api.anthropic.com/v1/messages"`, `API_VERSION = "2023-06-01"`. The streaming request POSTs the same URL with `payload["stream"] = True`.
2. **`tg_parser/processing/llm/anthropic_client.py:59-84`** — `__init__(..., timeout: float = 150.0, ..., call_timeout: float | None = None)`; line 75 `self._client = httpx.AsyncClient(timeout=timeout)` (the **per-attempt read timeout**, now the inter-event gap guard under streaming); line 84 `self._call_timeout = call_timeout` (aggregate). Add `self._streaming` here.
3. **`tg_parser/processing/llm/anthropic_client.py:110-157`** — `generate_with_usage` wraps `_generate_with_usage_inner` in `asyncio.wait_for(..., timeout=self._call_timeout)` and raises `LLMCallTimeoutError` on `TimeoutError`. **Keep this wrapper unchanged.**
4. **`tg_parser/processing/llm/anthropic_client.py:159-334`** — `_generate_with_usage_inner`. Headers built at `:168-175` (prompt-caching header `anthropic-beta: prompt-caching-2024-07-31` at `:174-175` — **NO-OP today**, ⛔ 3); payload at `:179-192` (add `stream: True` here); the retry loop `for attempt in range(1, self._max_retries + 1):` at `:203`; the **single non-streaming** `response = await self._client.post(self.BASE_URL, headers=headers, json=payload)` at `:208-212` (this is what the streaming branch replaces with `self._client.stream("POST", ...)`); retryable-status / 429 handling `:214-238`; 400/billing `:240-256`; **non-streaming response parse** `data = response.json()` / `_extract_text_content` / `usage = data.get("usage", {})` at `:259-290`; rate-limiter reconcile `:263-270`; the `LLMResponse(text, input_tokens, output_tokens, stop_reason)` return at `:281-290`; **`anthropic_network_error` structlog event** (empty error string on stalls) in the `except httpx.HTTPError` branch at `:315-328`.
5. **`tg_parser/processing/llm/anthropic_client.py:336-362`** — `_extract_text_content` (static) — empty `content` array returns `""` (not an exception). The streaming buffer must preserve the same "empty text is not a crash" semantics.
6. **`tg_parser/processing/llm/factory.py:100-125`** — the `anthropic` branch constructs `AnthropicClient(...)`: `prompt_caching_enabled=settings.anthropic_prompt_caching_enabled` (`:116`), `timeout=kwargs.pop("timeout", settings.anthropic_http_timeout_s)` (`:120`), `call_timeout=kwargs.pop("call_timeout", settings.anthropic_call_timeout_s)` (`:121-123`). Add the streaming kwarg here mirroring `:120`. **`factory.py:21-30`** — `_get_or_create_rate_limiter` caches one `LLMRateLimiter` **per api_key** (shared across stages). **`factory.py:157-160`** — `InstrumentedLLMClient` wraps the client (records `llm_requests_total` / duration).
7. **`tg_parser/config/settings.py:882-889`** — `anthropic_prompt_caching_enabled: bool = Field(default=True, …)` (the header toggle; no-op today, ⛔ 3).
8. **`tg_parser/config/settings.py:910-927`** — `anthropic_call_timeout_s: float = Field(default=420.0, …, ge=10.0)` — **aggregate** wall-clock wrapper; docstring records the BUG-079 300→420 retune. Env: `ANTHROPIC_CALL_TIMEOUT_S`.
9. **`tg_parser/config/settings.py:928-944`** — `anthropic_http_timeout_s: float = Field(default=150.0, …, ge=5.0)` — **per-attempt** httpx read timeout; docstring explicitly notes "these requests are NON-STREAMING, so this read timeout measures the FULL generation time … measured ~87-90s". **This is exactly the limitation BUG-080 removes.** Env: `ANTHROPIC_HTTP_TIMEOUT_S`. **No `anthropic_streaming_*` field exists — you add it.**
10. **`tg_parser/processing/topicization.py:1285-1291`** — the topicization generation call: `await self.llm_client.generate_with_usage(prompt=…, system_prompt=…, temperature=…, max_tokens=max_tokens, response_format={"type": "json_object"})`; token accounting `self.total_input_tokens += llm_response.input_tokens` / `+= llm_response.output_tokens` at `:1292-1293`; truncation detection `if llm_response.stop_reason == "max_tokens":` at `:1297-1306`. Other generate call-sites at `:1455` and `:2218` (same client). If you go per-call-site gating, this (`:1285`) is where you'd pass `streaming=True`.
11. **`tg_parser/services/topicization_service.py:524-530`** — `resolve_llm_config("topicization")` → `create_llm_client(provider, api_key, model)` (also at `:1296`). This is the topicization entry into the shared factory path — confirming topicization uses the SAME `AnthropicClient` as processing/RAG/digest/resummarize (⛔ 1).
12. **`tg_parser/api/metrics.py:83-87`** — `LLM_REQUESTS_TOTAL = Counter("tg_parser_llm_requests_total", …, ["provider", "model", "status"])`; **`:96-100`** `LLM_TOKENS_TOTAL` (`token_type`: prompt/completion); **`:89-94`** `LLM_REQUEST_DURATION_SECONDS`; **`:862`** `record_anthropic_5xx(*, status)`. `anthropic_network_error` is a **structlog event** (`anthropic_client.py:319`), not a Prometheus counter — verify no regression by watching logs + the `llm_requests_total{status="error"}` series.
13. **`prompts/topicization.yaml`** — the topicization system prompt (~450 tokens, below the 1024-token prompt-caching minimum — the ⛔ 3 no-op).

---

## 7. § Safety rails + closeout criteria

### Safety rails (reuse the proven set from BUG-076/077/078/079)
- **Contract-regression stop:** if ANY non-topicization stage (processing / RAG / digest / resummarize) shows empty/garbled output after streaming ships, the SSE parse is corrupting the `LLMResponse` contract — flip `ANTHROPIC_STREAMING_ENABLED=false` and reassess.
- **Token-accounting stop:** if `tg_parser_llm_tokens_total` or the per-run token accounting diverges from the non-streaming baseline, usage aggregation is wrong (⛔ 2) — the fix is a bug, revert the flag.
- **BILLING stop:** any `AnthropicBillingError` → the empty-balance safety net is doing its job; do not top up mid-incident.
- **STALL cap:** if `LLMCallTimeoutError` / `anthropic_network_error` counts climb during a run, treat it as a regression — re-pause and reassess before spending more.
- **Do NOT shrink the per-attempt timeout prematurely** (⛔ 4): 150/420 stay until streaming is validated live.
- **`remove_channel` to stop drip** — prefer over `pause_channel` if a billing-backoff cycle could clobber a manual pause (BUG-078 kill-switch-clobber caveat). Always restore paused channels afterward.
- **AGENTS.md** — no commit without explicit request; no `pyproject.toml`/`requirements.txt` edits (no new dependency needed); ADR/contracts binding.

### Closeout criteria
- **BUG-080 → `resolved`** when: the flag-gated streaming path ships + deploys + is live-verified in the worker (§4); a multi-chunk `murashko_med` drain (§5) completes with streaming ON, **ZERO** stalls, and card counts / token accounting matching the non-streaming baseline; and the non-topicization call-sites (processing / RAG / digest / resummarize) are demonstrably unregressed (§Tests 4–5 + live).
- **Bonus / optional:** the per-attempt `anthropic_http_timeout_s` is shrunk back toward a true inter-chunk stall-guard (separate step §Implementation 6) and validated. Note this explicitly in the BUG-080 row if done.
- **Prompt-caching no-op** (⛔ 3, secondary finding): resolve ONLY as a clearly separate, measured item — do NOT claim it as part of the streaming win.
- All doc-status edits are `docs/notes/BUG_LOG.md` changes; **committing still requires an explicit user request** (AGENTS.md).

---

## 8. Reading list / pointers
- [`BUG_LOG.md`](BUG_LOG.md) — `### BUG-080` (this enhancement, filed 2026-07-06), `### BUG-079` (origin + the `Update 2026-07-06 — RESOLVED` timed-experiment evidence: 89.09s / 89.59s / 87.06s, commits `9069396` / `57d1bce`), `### BUG-068` (adjacent Anthropic no-effective-timeout class).
- [`START_PROMPT_SESSION_BUG079_NETWORK_STALL_HARDENING_2026-07-06.md`](START_PROMPT_SESSION_BUG079_NETWORK_STALL_HARDENING_2026-07-06.md) — predecessor; the §7 isolate→fund→drain validation + BUG-078 compose-mirror discipline reused here.
- [`START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md`](START_PROMPT_SESSION_BUG078_FLAG_LIVE_OBSERVABILITY_AND_SAFE_REENABLE_2026-07-02.md) — verify-live discipline for the new streaming flag.
- [`START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md`](START_PROMPT_SESSION_BUG076_077_CONTROLLED_ENABLE_MURASHKO_MED_2026-07-02.md) — controlled-exercise / kill-switch / watch discipline for §5.
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) — deploy / rollback / smoke (file-sync deploy + `--force-recreate`).
- Source: `tg_parser/processing/llm/anthropic_client.py` (:56-57, :59-84, :110-157, :159-334, :336-362), `tg_parser/processing/llm/factory.py` (:21-30, :100-125, :157-160), `tg_parser/config/settings.py` (:882-889, :910-927, :928-944), `tg_parser/processing/topicization.py` (:1285-1306, :1455, :2218), `tg_parser/services/topicization_service.py` (:524-530, :1296), `tg_parser/api/metrics.py` (:83-100, :862), `prompts/topicization.yaml`.
- Anthropic Messages streaming reference: server-sent events `message_start` → `content_block_start` → `content_block_delta` (`text_delta`) → `content_block_stop` → `message_delta` (final `stop_reason` + cumulative `usage.output_tokens`) → `message_stop`.
