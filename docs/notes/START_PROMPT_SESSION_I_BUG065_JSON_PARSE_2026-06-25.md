# START PROMPT — Session I: BUG-065 (processing-stage JSON parse-drop) fix

> **Status:** `ACTIVE` — successor handoff to [`START_PROMPT_BREAK_2026-06-25.md`](START_PROMPT_BREAK_2026-06-25.md). **Decision settled:** the JSON parse-drop work is split into **TWO sessions**. **Session I (THIS doc's scope):** file **BUG-065** + implement the **LOW-RISK fix** (#1 provider-agnostic JSON-repair fallback + #4 prompt escape-hardening) + tests + deploy. **Session II (forward-pointer only here):** option C (#2 Anthropic structured output / tool-use) + observability (per-channel processed/raw coverage metric + alert). The **full** Session II handoff will be authored at the END of Session I with fresh post-fix data — so in THIS doc Session II is only a concise backlog/next-pointer. Independent of BUG-064 / the ADR-0016 near-dup watch (which keeps running, see §6).

| Метаданные | Значение |
|---|---|
| **Дата handoff** | 2026-06-25 (~16:58 UTC+4 / ~12:58 UTC) |
| **Wave** | 1.5 operational dogfooding (active) |
| **Prod HEAD (code)** | `e7feee4` (BUG-064 Option A fix; deployed ~2026-06-25 09:25 UTC, all services healthy) — on top of α2 `284436c` |
| **Repo tip (local == origin/main)** | `02569fa` (docs: mark BUG-064 resolved+deployed) — working tree clean, branch up to date |
| **Prior handoff** | [`START_PROMPT_BREAK_2026-06-25.md`](START_PROMPT_BREAK_2026-06-25.md) |
| **Living tracker** | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §11 |
| **This session's bug** | **BUG-065** — processing-stage LLM emits unescaped inner quotes → invalid JSON → doc silently dropped |

---

## §1 — TL;DR

A new **PRE-EXISTING LATENT** processing-quality bug — **BUG-065** — was root-caused this session with prod evidence: the processing-stage LLM (**Anthropic `claude-haiku-4-5`**) emits **unescaped straight double-quote characters inside the `text_clean` JSON string value**, producing syntactically invalid JSON, so the document is **silently dropped** (counted as a per-document failure, not a source failure). It bites any **quotation-dense / high-volume** channel, **not** aggregator-specific. **Live corroboration in the fresh snapshot below:** `mediamedics` shows **11,045 raw / 0 processed / fail_count 0** — a textbook mass parse-drop with no alarm.

**Session I plan (do this session):** file BUG-065 in [`BUG_LOG.md`](BUG_LOG.md) → implement the **low-risk pair**: **#1** a provider-agnostic **JSON-repair fallback** at the parse boundary (run a repair pass on `JSONDecodeError` and re-parse *before* counting the attempt failed) + **#4** prompt hardening in [`prompts/processing.yaml`](../../prompts/processing.yaml) (explicit rule to JSON-escape every `"` and `\` inside `text_clean`, output ONE JSON object only) → tests covering the repair path → deploy via the F5C runbook. **OPEN OPERATOR DECISION (flag first):** #1 may need a new dependency (`json-repair` / `json5`) → that is a `pyproject.toml` change requiring explicit operator GO per [`AGENTS.md`](../../AGENTS.md); the alternative is a pure-Python in-repo repair routine (no new dep). **Ask the operator which before adding any dependency.**

**Session II (backlog pointer only):** option **C (#2)** — rewrite the Anthropic processing call to structured output / tool-use so valid JSON is API-guaranteed; **observability** — per-channel processed/raw coverage gauge + alert. Full Session II handoff written at end of Session I with post-fix data.

---

## §2 — Why BUG-065 now (root-cause brief, prod-confirmed this session)

**Symptom:** documents from quotation-dense channels never reach `processed_documents`; the source's `fail_count` stays **0** (per-document drop, not a source-level failure), so a channel silently lands below its raw count with **no alarm**.

**Root cause (confirmed with prod evidence):** the processing LLM (Anthropic `claude-haiku-4-5`) writes the verbatim message text into the `text_clean` JSON value **without escaping inner `"`**. That breaks the JSON object → `json.loads` raises `JSONDecodeError` → after 3 identical retries the doc is dropped.

**Evidence (12h prod window):**
- **61/64** `failed_to_parse_llm_json` were `Expecting ',' delimiter` on **line 2** (the `text_clean` line); **3** were `Expecting ':' delimiter`.
- **ZERO** truncation / empty-content / markdown-fence signatures → **rules out** `max_tokens` truncation, fenced output, and preamble/prose as causes.
- Break column **600–900**, mid-string; **identical across all 3 retries** (processing runs `temperature=0`, so the retry reproduces the exact same unescaped quote — the hint can't steer it out).
- All failing refs were `tg:mediamedics:post:*`.

**Conclusion:** latent bug in the **parse boundary + prompt**, exposed by a high-volume quotation-dense channel. Not aggregator-specific; not caused by BUG-064 / the near-dup watch / Wave 2 gating.

### Code refs to cite in the BUG-065 entry (verified this session)

| Ref | What it shows |
|---|---|
| [`tg_parser/processing/pipeline.py:439-478`](../../tg_parser/processing/pipeline.py) | The parse loop (`for attempt in range(1, max_json_attempts+1)` at :439): `generate_with_usage(..., response_format={"type":"json_object"})` (:446-452) → `extract_json_from_response` (:458) → `json.loads` in a try/except that logs `failed_to_parse_llm_json` (:465-472) and, after `max_json_attempts`, raises `LLMJsonParseError` (:474-478). **This is where the repair pass must hook (before counting the attempt as failed).** |
| [`tg_parser/processing/pipeline.py:42-82`](../../tg_parser/processing/pipeline.py) | `extract_json_from_response` — **the only repair today is markdown-fence stripping**; no quote-escaping / JSON-repair. |
| [`tg_parser/processing/llm/anthropic_client.py:140-142`](../../tg_parser/processing/llm/anthropic_client.py) | `response_format={"type":"json_object"}` is effectively a **NO-OP for Anthropic** — it only appends "Respond with valid JSON only." *if* "json"/"JSON" is absent from the prompt (it isn't). No structural JSON guarantee. |
| [`tg_parser/processing/llm/openai_client.py:134-135`](../../tg_parser/processing/llm/openai_client.py) | Real JSON mode is wired **only** on the OpenAI Chat-Completions path… |
| [`tg_parser/processing/llm/openai_client.py:174-178`](../../tg_parser/processing/llm/openai_client.py) | …and is a **no-op on the OpenAI Responses / GPT-5 path**. (gemini/ollama similarly unguaranteed.) → **provider-agnostic #1 is the only baseline that covers every runtime-switchable provider.** |
| [`tg_parser/processing/pipeline.py:90-107`](../../tg_parser/processing/pipeline.py) | `apply_json_retry_hint` (`_JSON_RETRY_HINT`) — the hint **never mentions escaping inner quotes**, and at `temperature=0` the retry is deterministic, so it can't fix this class. |
| [`tg_parser/processing/pipeline.py:323-329`](../../tg_parser/processing/pipeline.py) | Non-retryable handling: an `LLMJsonParseError` is logged `processing_json_parse_non_retryable` and the doc is dropped (no outer re-retry, by BUG-019 design). |
| [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) | `max_json_attempts` budget = 3. The parse loop reads `retry_settings.max_attempts` (`RetrySettings.max_attempts` default `3`, `RETRY_`-prefixed, :1076); the outer per-message loop uses `processing_max_attempts_per_message` (default `3`, :206) — both `3`. |
| [`prompts/processing.yaml:28-43`](../../prompts/processing.yaml) | Output contract: the (cleaned) message text is written into the `text_clean` string value, **with no instruction to escape inner quotes**. |
| [`prompts/processing.yaml:86`](../../prompts/processing.yaml) | `max_tokens: 4096`, `temperature: 0`. (Confirms truncation is not the cause and the retry is deterministic.) |

---

## §3 — Current prod state (fresh snapshot this session)

```text
git rev-parse --short HEAD   # 02569fa (local == origin/main, clean); prod CODE tip e7feee4
```

| Component | State |
|---|---|
| **Prod SHA (code)** | `e7feee4` — BUG-064 Option A fix (deployed ~2026-06-25 09:25 UTC; healthy) — on top of α2 `284436c` |
| **Repo tip (local/origin)** | `02569fa` — working tree clean, `main` up to date with `origin/main` |
| **Processing LLM** | **anthropic / `claude-haiku-4-5-20251001`** (the BUG-065 emitter); confirmed live via read-only `get_llm_config` (`stages.processing`, `overridden=false`) this review; runtime-switchable via `set_llm_config(scope='processing', …)` — re-confirm with `get_llm_config` on resume |
| **ADR-0016 near-dup watch** | **RUNNING** from the `e7feee4` deploy (~09:25 UTC); counter accrues forward only; Phase-1 3-way decision at review #2 (~2026-07-04) — see §6 |
| **Decision Point** | 0/0/0 (2A/2B/2C); not triggered — continue dogfooding |

### Freshened watch snapshot — read-only `list_channels` + `get_pipeline_status` (reflects scheduler ticks ~11:25–11:28 UTC, captured ~12:58 UTC)

| Channel | raw | processed | coverage % | fail_count | last_success (UTC) | Note |
|---|---:|---:|---:|---:|---|---|
| **mediamedics** | 11,045 | **0** | **0.0** | **0** | 11:28 | **BUG-065 live**: full backlog ingested, every doc parse-dropped, no alarm |
| **murashko_med** | 0 | 0 | 0.0 | 0 | — (null) | Not yet ingesting (sequential pipeline) |
| **medportal_rfed** | 0 | 0 | 0.0 | 0 | — (null) | Not yet ingesting |
| AgeManagment | 1,132 | 1,128 | 94.59 | 0 | 11:25 | healthy baseline |
| Lab4health | 1,890 | 1,885 | 99.73 | 0 | 10:27 | healthy |
| profendocrinologist | 3,503 | 3,503 | 96.60 | 0 | 10:26 | healthy |
| genotek | 1,150 | 1,148 | 99.04 | 0 | 10:26 | healthy |
| kdl_ru | 865 | 865 | 90.75 | 0 | 10:26 | healthy |
| labdiagnostica_logical | 1,201 | 1,187 | 94.10 | 0 | 10:27 | healthy |
| mind_rise | 1,127 | 1,127 | 98.49 | 0 | 10:27 | healthy |
| LongevityClub | 339 | 339 | 97.64 | 0 | 10:27 | healthy |
| BiocodebySechenov | 191 | 191 | 93.19 | 0 | 10:27 | healthy |
| foodf4thought | 331 | 330 | 56.67 | 0 | 10:26 | low coverage (pre-existing, separate) |

> **Reading:** `mediamedics` 11,045 raw → **0 processed → fail_count 0** is the clearest possible BUG-065 + observability-gap demonstration: the source looks "healthy" (no failures) while every document is silently lost. (Note: a transient ~12:35 UTC observation in the prior context showed ~1/3 of the backlog processed; this later snapshot reads 0 — treat the exact processed count as volatile; the *shape* of the bug stands either way.) `murashko_med` / `medportal_rfed` had **not started** ingesting yet (sequential pipeline; `last_success_at` null).
>
> **Re-verified (read-only, ~13:10 UTC this review):** `get_pipeline_status` reconfirms all sources `fail_count=0` (incl. `mediamedics`, the silent-drop signature), `mediamedics last_success 11:28:02 UTC`, `murashko_med` / `medportal_rfed` `last_success_at=null`, no scheduler tick since 11:25–11:28 (next at :25) — the snapshot above still holds. (`get_pipeline_status` reports fail/last-success only; the raw/processed/coverage columns are from the earlier `list_channels` capture.)

---

## §4 — Session I work to implement

> Scope: **BUG-065 filing + low-risk fix (#1 + #4) + tests + deploy.** This is a bugfix to **processing quality**; it does **not** touch BUG-064 / the near-dup observer / Wave 2 gating.

### Step 0 — File BUG-065 (do first)

Add a `BUG-065` entry to [`BUG_LOG.md`](BUG_LOG.md) `## Active bugs`, formatted like **BUG-064** (the field table: `Severity` / `Status` / `Component` / `Discovered` / `Symptoms` / `Root cause` (with the §2 code refs) / `Why CI didn't catch` / `Proposed fix` (#1 + #4 separated from Session II C/#2) / `Workaround` / `Artifacts` / `Linked`). Suggested header:

> `### BUG-065 — Processing-stage LLM emits unescaped inner quotes in text_clean → invalid JSON → doc silently dropped`

Suggested fields: **Severity** High (silent data loss on quotation-dense channels, workaround exists = provider switch is *not* reliable since most providers' JSON-mode is no-op); **Status** `in-progress` (cite this START_PROMPT); **Component** `pipeline` (processing); **Why CI didn't catch** no test feeds an unescaped-quote payload through the parse boundary; **Linked** BUG-019 (retry-hint), ADR-0016 (independent).

### Step 1 — #1 JSON-repair fallback (provider-agnostic, lowest-risk, highest-leverage)

At the parse boundary in [`pipeline.py:439-478`](../../tg_parser/processing/pipeline.py): on `JSONDecodeError`, run a **repair pass** (escape unescaped inner `"` / `\`, strip trailing commas, etc.) and **re-parse BEFORE** logging `failed_to_parse_llm_json` / counting the attempt as failed. Only fall through to the failure path if the repaired parse also fails. Keep `extract_json_from_response` (fence-strip) as the first stage; add repair as a second stage.

> **⚠️ OPEN OPERATOR DECISION — ASK BEFORE CODING #1.**
> Adding a library (`json-repair` or `json5`) is a **`pyproject.toml` / dependency change** → requires **explicit operator GO** per [`AGENTS.md`](../../AGENTS.md) ("Forbidden: прямые правки `pyproject.toml`, `requirements.txt` без явного запроса").
> **Alternative:** a **pure-Python in-repo repair routine** (no new dependency) — e.g. a focused pass that escapes unescaped quotes inside string values.
> **The next session MUST ask the operator which path to take before adding any dependency.** Default lean (pending GO): pure-Python in-repo routine to avoid the dependency gate, unless the operator prefers a vetted lib.

### Step 2 — #4 prompt hardening (cheap complement, not a sole fix)

In [`prompts/processing.yaml`](../../prompts/processing.yaml) (system contract `:28-43`): add an explicit rule to **JSON-escape every `"` and `\` inside `text_clean`** (and all string values) and to output **exactly one JSON object** (no markdown fences, no prose). This reduces the rate but is **not** a guarantee (the model still occasionally violates it at `temperature=0`), hence it complements #1 rather than replacing it. Reload via `reload_prompts` (no restart) after deploy if editing prompts live.

### Step 3 — Tests (repair path)

Add a test that feeds a `text_clean` payload containing **unescaped inner double-quotes** (mirroring the prod `Expecting ',' delimiter` line-2 signature) through the parse boundary and asserts it now **parses successfully** via the repair pass (and that a genuinely irreparable payload still raises `LLMJsonParseError`). Run **venv-only**: `.venv/bin/python -m pytest tests/…` (see §7 gotcha).

### Step 4 — Deploy

Deploy via the F5C runbook ([`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)). **No migration expected** (code + prompt only). **SSH/deploy works ONLY outside the Cursor sandbox** (see §7). Post-deploy, re-run the parse-drop count and watch `mediamedics` `processed_documents` climb off 0 (the success criterion for #1).

---

## §5 — Session II backlog tail (concise pointer only — NOT a full plan)

> Full Session II handoff to be authored at the END of Session I with post-fix data (did #1 drive the drop-rate → 0? what are the real coverage numbers once `mediamedics` reprocesses?).

- **C (#2) — Anthropic structured output / tool-use:** rewrite the processing call so valid JSON is **API-guaranteed**. Note: provider-specific — OpenAI-Responses + gemini/ollama JSON-mode are also no-ops, and the processing provider is runtime-switchable via `set_llm_config`, so the **provider-agnostic #1 remains the baseline** regardless. C is a hardening upgrade for the Anthropic path, not a replacement for #1.
- **Observability — per-channel processed/raw coverage:** add a coverage **gauge + alert** that distinguishes **parse-drops at channel granularity** (today dropped docs are per-document failures; source `fail_count` stays 0, so a channel can silently sink below its raw count with no alarm — exactly the `mediamedics` 11,045/0/0 case). This is the metric that would have caught BUG-065 automatically.

---

## §6 — Live context to carry forward (independent of BUG-065)

- **BUG-064 RESOLVED & deployed** `e7feee4` (near-dup observer wiring + per-doc `channel_ids`); closed in [`BUG_LOG.md`](BUG_LOG.md) (`a5b2ce0`); docs updated (`02569fa`); f8a stale-mock test fix (`42fcd69`). All pushed to `origin/main` (tip `02569fa`).
- **ADR-0016 Phase-0 near-dup watch is RUNNING** from the `e7feee4` deploy (~2026-06-25 09:25 UTC); counter `tg_dedup_near_duplicates_detected_total` **accrues forward only**; Phase-1 3-way decision at review #2 (~2026-07-04).
- **3 new aggregator channels** added for cross-axis samples: `mediamedics`, `murashko_med`, `medportal_rfed`. Per the fresh snapshot (§3), `mediamedics` ingested its 11,045 backlog but processed 0 (BUG-065); the other two had not started (sequential pipeline). The near-dup counter is still **0** (no `near_duplicate_check` fired yet — embeddings/observer run hourly at **:25** only **after** docs are processed; with `mediamedics` parse-dropping, there were no new processed docs to embed).
- **The next session must CONTINUE the read-only watch monitoring:** re-check `processed > 0` (esp. once #1 lands and `mediamedics` reprocesses), `near_duplicate_check checked > 0 & skipped_no_embedding == 0`, and `{dimension=cross}` movement.
- **OPERATIONAL RULE (carry forward):** do **NOT** run manual `trigger_pipeline` / CLI / HTTP ingest on the new channels — it **bypasses the near-dup observer** AND consumes the backlog so the scheduler tick sees it as non-new → backlog cross-dups permanently missed. **Just let the hourly scheduler tick run.**
- **Observability gap (feeds Session II):** dropped docs are per-document failures; source `fail_count` stays 0, so a channel silently lands below its raw count with no alarm. No per-channel processed/raw coverage metric/alert today.

---

## §7 — Pre-flight on resume

```bash
cd /Users/alexanderefimov/TG_parser
git fetch origin && git status
git log --oneline -8
# Expect repo tip 02569fa (or later); prod CODE tip e7feee4 (BUG-064 fix on α2 284436c)

# Optional prod sanity (MCP, READ-ONLY):
# get_llm_config        # confirm processing = anthropic/claude-haiku-4-5 (the BUG-065 emitter)
# get_pipeline_status   # re-check mediamedics processed_documents (should be >0 after #1 deploy)
# list_channels         # re-check per-channel coverage_percent

# Tests — VENV ONLY:
.venv/bin/python -m pytest tests/ -q     # system Python lacks pymorphy3/structlog → HARD-FAIL (not skip)
```

> **Operational gotchas (carry forward from prior handoff):**
> - **Tests:** run via `.venv/bin/python -m pytest …` **ONLY** — system Python lacks `pymorphy3`/`structlog`; affected tests **hard-fail** on import → false "failed" alarm.
> - **Deploy:** SSH to the prod VPS works **ONLY outside** the Cursor sandbox (no SSH egress inside) — run deploy commands with elevated/outside-sandbox permissions, else the deploy stalls at the SSH boundary.
> - **Dependency gate:** adding `json-repair`/`json5` (or any dep) edits `pyproject.toml` → **explicit operator GO required** (`AGENTS.md`). Ask first; default to a pure-Python repair routine absent a GO.

---

## §8 — Do NOT reopen (all settled)

| Item | Reason |
|---|---|
| **α2 seed-map** | DONE & deployed (`284436c`) — no re-extend without a new GO |
| **RESUMMARIZE_LLM pin** | NOT needed (resummarize = anthropic/claude-sonnet-4-6; llm_error=0/96h) |
| **Option B (decouple near-dup hook)** | NOT required — observer is a no-op without new docs (early-return) |
| **D2 scoring formula** | Deferred, ADR-gated |
| **Wave 2 direction commit** | DP matrix 0/0/0 → continue dogfooding |
| **BUG-064** | RESOLVED & deployed (`e7feee4`); near-dup wiring-gap closed |

---

## §9 — Key links

| Doc | Path |
|---|---|
| Prior handoff (predecessor) | [`START_PROMPT_BREAK_2026-06-25.md`](START_PROMPT_BREAK_2026-06-25.md) |
| Bug log (file BUG-065 here, match BUG-064) | [`BUG_LOG.md`](BUG_LOG.md) |
| Processing pipeline (parse boundary) | [`tg_parser/processing/pipeline.py`](../../tg_parser/processing/pipeline.py) |
| Anthropic client (json_object no-op) | [`tg_parser/processing/llm/anthropic_client.py`](../../tg_parser/processing/llm/anthropic_client.py) |
| OpenAI client (json mode wiring) | [`tg_parser/processing/llm/openai_client.py`](../../tg_parser/processing/llm/openai_client.py) |
| Processing prompt (#4 hardening) | [`prompts/processing.yaml`](../../prompts/processing.yaml) |
| Settings (`max_attempts=3`) | [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) |
| Deploy runbook | [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) |
| ADR-0016 (near-dup, independent) | [`docs/adr/0016-near-duplicate-dedup.md`](../adr/0016-near-duplicate-dedup.md) |
| Wave 1.5 plan + §11 log | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §11 |
| Project conventions / forbidden actions | [`AGENTS.md`](../../AGENTS.md) |

### Reference commit lineage (no new commits this session)

| SHA | Summary | State |
|---|---|---|
| `284436c` | feat(watchlist): extend α2 seed-map with 5 GLP-1 molecule clusters | deployed |
| `e7feee4` | fix(dedup): wire incremental message embeddings before near-dup observer (BUG-064) | **prod code tip** |
| `42fcd69` | test(f8a): fix stale Anthropic `_ok_resp` mock shape (type:text) | test-only |
| `a5b2ce0` | docs(notes): close BUG-064 — resolved & deployed (e7feee4) | docs-only |
| `02569fa` | docs(notes): mark BUG-064 resolved+deployed in handoff & Wave1.5 §11 tracker | **repo tip (local == origin/main)** |

---

> **Reminder:** Wave 1.5 = habit, not sprint. BUG-065 is a **processing-quality bugfix**, independent of the (still-running) ADR-0016 near-dup watch and of Wave 2 gating. **Commit only on explicit user request** ([`AGENTS.md`](../../AGENTS.md)). Ask the operator before adding any dependency.
