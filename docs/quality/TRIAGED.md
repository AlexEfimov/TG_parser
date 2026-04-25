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

## 2026-04-20 — genotek topicization silent failure

**Labels:** `topicization` · `scheduler` · `reliability` · `observability` · `P1`
**Incident file:** [`incidents/2026-04-20_genotek_topicization_silent_failure.md`](incidents/2026-04-20_genotek_topicization_silent_failure.md)
**Disposition:** **triaged → Sprint D.1 — Topicization Hardening**
**Status:** fixed in code (Sprint D.1 implemented on 2026-04-25, pending merge to `main`)
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
