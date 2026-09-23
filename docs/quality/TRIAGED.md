# TRIAGED — processed observations

**Purpose:** audit trail of what happened to each `INBOX.md` entry and each
`incidents/*.md` file after triage: which sprint absorbs the fix, which are
duplicates, which are `wontfix`. Newest entries on top.

**Lifecycle:**

1. Entry appears in `INBOX.md` (or a full file in `incidents/`).
2. Triage (done before each sprint-planning session — see `docs/quality/INBOX.md` § "Triage cadence").
3. Disposition written **here**, with rationale in 1–3 sentences.
4. Original INBOX entry is **cut** from `INBOX.md` and pasted into the
   "Entry text" block below, preserving content verbatim for git history.
5. When the fix lands on `main`, update `Status` to `fixed → <commit-sha>` here
   and in the corresponding incident file. Do not remove the entry.

See [`TAXONOMY.md`](TAXONOMY.md) for label definitions.

---

## 2026-08-28 — Phase 2 discover sends the whole cross-channel topic catalog per keyword-miss

**Labels:** `topicization` · `perf` · `P2`
**Incident file:** [`incidents/2026-08-28_anthropic_spend_phase2_discover.md`](incidents/2026-08-28_anthropic_spend_phase2_discover.md)
**Disposition:** **triaged → [BUG-108](../notes/BUG_LOG.md)** — (a) observability in R13, (b) context cap in R17 ([`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](../notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §4a)
**Status:** open, code fix pending. Billing block itself is over: last `AnthropicBillingError` 2026-09-03 08:32Z, zero failed attempts since (prod read 2026-09-23).

### Why BUG_LOG, not a sprint

The fix queue for this period lives in `PLAN_REMEDIATION` §4 and references
`BUG-NNN` only; a P2 cost defect with two sessions fits that queue, not a new
sprint track. Re-measured 2026-09-23: ~14 calls in 20 days, ~75 % of all LLM
spend — worth fixing, not urgent.

### Scope absorbed

- Follow-up 1 (context cap) → BUG-108 (b).
- Follow-up 2 (observability: `stage` label, topicize tokens) → BUG-108 (a).
- Follow-up 3 (refill / other program off the key) → operationally resolved; key hygiene stays as owner action (follow-up 5).

### Out of scope (deferred)

- Follow-up 4 (`CROSS_CHANNEL_TOPICIZATION=false` as a stopgap) — not needed at the current spend level.

### Entry text (cut from INBOX)

> ## 2026-08-28 16:00 UTC — topicization · perf · P2
>
> → [`incidents/2026-08-28_anthropic_spend_phase2_discover.md`](incidents/2026-08-28_anthropic_spend_phase2_discover.md)
>
> Пустой баланс Anthropic сегодня — не TG_parser (~$1.80 / ~$9 за 7д). Остаётся Phase 2 discover: полный кросс-канальный каталог тем в каждый keyword-miss (~260k Sonnet ≈ $0.80). Вернуться до пополнения кредита.

---

## 2026-04-20 — genotek topicization silent failure

**Labels:** `topicization` · `scheduler` · `reliability` · `observability` · `P1`
**Incident file:** [`incidents/2026-04-20_genotek_topicization_silent_failure.md`](incidents/2026-04-20_genotek_topicization_silent_failure.md)
**Disposition:** **triaged → Sprint D.1 — Topicization Hardening**
**Status:** **fixed in production** — Sprint D.1 deployed to `redboxtgbot` on 2026-04-25. Code commit `cdce066` (feat), deploy commit on `main` `33d9f48`, ingestion migration `ac6a4414ac58` (`add_source_attempts_failed_stage`). Verified live: new column present, `tg_parser_anthropic_billing_block_total` exposed, all sources `rate_limit_until=NULL`. Full evidence in the incident file § 7a.
**Sprint prompt:** [`../notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`](../notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md)

### Why a new sprint (not folded into F11)

F11 (Topic Watchlist) reads `topic_cards`. Shipping F11 on top of a topicization
path that can silently land on 0 cards bakes a hard-to-diagnose false-negative
into the product. Hardening first → F11 on a trusted base. Roadmap slot
inserted before F11.

### Scope absorbed into D.1

Four defects promoted from the RCA §5:

1. **§5.1 [HIGH]** — `run_incremental_topicization` must escalate to full discovery when `existing_cards == 0`. Silent no-op otherwise.
2. **§5.2 [HIGH]** — Per-batch savepoint in `discover_new_topics` so partial progress survives mid-run failure.
3. **§5.3 [MEDIUM]** — Typed `AnthropicBillingError` for `invalid_request_error: credit balance`; no retry, metric, single ERROR log per window.
4. **§5.4 [MEDIUM]** — `source_attempts.success` must reflect per-stage outcome; add `failed_stage` / `error_class` / `error_message`.

### Out of scope for D.1 (deferred)

- **§5.5** — coverage-metric semantics clarification → docs-only, will be addressed as part of FUTURE_FEATURES F11 docs.
- **§6** — `force_retopicize` MCP tool → separate mini-sprint after D.1 if desired (nice-to-have, not hardening).

### Original evidence

Full timeline / SQL / stacktraces live in the incident file. Not copied here to
avoid drift; this document is the **pointer** and the decision log.

---

## Reference

- Agent playbook (how AI writes here): [`AGENT_PLAYBOOK.md`](AGENT_PLAYBOOK.md) §5–§7
- Vocabulary: [`TAXONOMY.md`](TAXONOMY.md)
- Active intake: [`INBOX.md`](INBOX.md)
- Incident files: [`incidents/`](incidents/)
