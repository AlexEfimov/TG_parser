# Anthropic balance empty — TG_parser not the budget hole; Phase 2 discover still ~$0.80/miss

**Date:** 2026-08-28
**Observed in:** production (VPS, `ssh prod`)
**Component(s):** `topicization` · `scheduler` · `observability`
**Severity:** P2 (cost quality gap; not an outage. Billing-block on prod is a side effect of empty API credits.)
**Status:** parked — return for Phase 2 cost fix. Today's large Anthropic hole was another program on the same account, confirmed by the owner in Console.
**Author:** Cursor agent, session 2026-08-28

---

## Summary

Owner saw a massive Anthropic token spend and an empty API credit balance. Prod pipeline from **2026-08-28 15:32 UTC** fails with `AnthropicBillingError` (`credit balance is too low`) on `resummarize` / `process_billing_blocked`.

Read-only audit of Prometheus + `source_attempts` + container logs showed TG_parser spent **~$1.80 today** and **~$9.40 over 7 days** — not a budget-emptying leak. Owner later confirmed in Claude Console that **another program** on the same Anthropic account burned the credits.

What *is* left in TG_parser, and the reason to reopen this file: every incremental **Phase 2 discover** (keyword-miss) dumps the **entire other-channel topic catalog** (~1900–2100 cards) into a Sonnet prompt — **~260k prompt tokens ≈ $0.78–0.80 per miss**. Two such calls today; ~4 on 2026-08-26 (~$3.50 that day).

---

## Timeline (UTC unless noted)

| Time | Event |
|------|-------|
| 2026-08-26 | Prometheus: ~1.09M Sonnet prompt (~$3.50). Container logs for that day no longer have Phase 2 lines (rotated). Size matches ~4 discover calls. |
| 2026-08-27 11:32 | `profendocrinologist` Phase 2: loaded **1940** cross-channel topics, 1 doc → unassignable. Sonnet prompt spike ~265k (~$0.80). |
| 2026-08-28 05:32 | Same channel, Phase 2: **1940** cross-channel topics, 1 new topic created. Spike ~260k. |
| 2026-08-28 06:00 | Four digest jobs. Three `digest.skipped_empty`; one delivered on 693 input / 267 output (~$0.01). Not the spike. |
| 2026-08-28 12:31 | `foodf4thought` Phase 2: loaded **2101** cross-channel topics, 1 doc → unassignable. Coverage stayed 81.6%. Spike ~259k. |
| 2026-08-28 15:32 | Five `source_attempts` fail: AgeManagment / genotek / mediamedics = `resummarize` + `AnthropicBillingError`; tgnikitin / profendocrinologist = `process_billing_blocked`. |
| 2026-08-28 ~15:40–16:00 | This session: Prometheus / SQL / logs. Owner checked Console — spend is another program. |

---

## Root cause

Two separate facts. Do not collapse them.

**Primary (today's empty balance):** API credits on the Anthropic **account** were exhausted by a client that is **not** TG_parser. Console does not label applications — only API key / workspace / model. On this VPS only `tg_parser`, `tg_parser_bot`, `tg_parser_mcp` have `ANTHROPIC_API_KEY` (same key fingerprint). n8n and Flowise on the host have no Anthropic env. Other spend is therefore another machine / Cursor / Claude Code / Playground / a second key on the same org.

**Latent (TG_parser, still open):** when Phase 1 keyword assign leaves docs unassigned, `_load_cross_channel_topics` (`tg_parser/services/topicization_service.py` ~2375) does `topic_card_repo.list_all()` and `_discover_single_batch` sends **every other channel's** `id` + `title` + full `scope_in` via `build_incremental_discover_prompt` (`tg_parser/processing/topicization_prompts.py` ~267). `cross_channel_topicization=True` on prod. Catalog at audit: **2131** `topic_cards`. One unmatched document → one Sonnet call ~260k prompt.

Processing (Haiku) today was normal: 15 docs, ~31k tokens, `dedup=0`. BUG-097 loop is not back.

---

## Evidence

### Prometheus (24h ending ~2026-08-28 15:40 UTC)

| Series | Value |
|---|---|
| Sonnet prompt | ~548 754 |
| Sonnet completion | ~5 050 |
| Haiku prompt / completion | ~18 981 / ~13 961 |
| `tg_parser_topicization_full_run_tokens_total` | empty (no full-run) |
| `tg_resummarize_total{outcome=ok}` | ~4 |
| LLM requests Sonnet | ~10 success + ~3 error |

Hourly Sonnet prompt spikes (all ~260k, one call each): 2026-08-27 11:00–12:00; 2026-08-28 05:00–06:00; 2026-08-28 12:00–13:00.

7-day Sonnet prompt ~2.77M + Haiku ~0.23M ≈ **~$9.40** at list price (Sonnet $3/$15 per MTok, Haiku $1/$5; [docs.anthropic.com pricing](https://docs.anthropic.com/en/docs/about-claude/pricing), 2026-08-28). No Batch / cache assumed.

`sum by (job)` — all of the 24h LLM tokens are `job=tg_parser_api`. Bot digest tokens are tiny and live on the bot process.

### Logs (stripped)

```text
2026-08-27T11:32:46Z  Loaded 1940 cross-channel topics as context (excluding channel=profendocrinologist)
2026-08-27T11:32:46Z  incremental_llm_batch_start channel=profendocrinologist batch=1/1 docs=1
2026-08-27T11:33:31Z  Phase 2 batch: 0 assigned, 0 new topics, 1 unassignable

2026-08-28T05:32:41Z  Loaded 1940 cross-channel topics as context (excluding channel=profendocrinologist)
2026-08-28T05:32:41Z  incremental_llm_batch_start channel=profendocrinologist batch=1/1 docs=1
2026-08-28T05:33:04Z  Phase 2 batch: 0 assigned, 1 new topics, 0 unassignable
2026-08-28T05:33:04Z  Created discovered topic topic:tg:profendocrinologist:post:4084: …

2026-08-28T12:31:52Z  Loaded 2101 cross-channel topics as context (excluding channel=foodf4thought)
2026-08-28T12:31:52Z  incremental_llm_batch_start channel=foodf4thought batch=1/1 docs=1
2026-08-28T12:32:03Z  Phase 2 batch: 0 assigned, 0 new topics, 1 unassignable
```

### SQL / state snapshots

`source_attempts.details_json.pipeline_stats` has `ingest` / `process` / `export` only — **no `topicize`**. Process token key is `total_tokens`, not `tokens_total`. Today: 15 processed, 30 757 process tokens, `dedup=0`.

```sql
SELECT count(*) AS topics,
       round(avg(length(title))) AS avg_title,
       round(avg(length(scope_in_json))) AS avg_scope
FROM topic_cards;
-- 2131 | 55 | 226
```

Prod settings (running container): `cross_channel_topicization=True`, `topicization_batch_size=25`, `topicization_reconcile_max_docs=200`.

### Cost card (list price, no cache)

| Window | Approx. USD |
|---|---|
| One Phase 2 miss (~260k prompt) | **$0.78–0.80** |
| Quiet day, no Phase 2 | $0.15–0.25 |
| 2026-08-28 to ~15:40 (two misses) | **~$1.80** |
| 2026-08-26 (peak) | **~$3.50** |
| Last 7 days | **~$9.40** |

---

## Impact

- **Users affected:** all 14 active sources from 15:32 UTC 2026-08-28 — next ticks fail while credits are empty. Digests/resummarize/topicize that need Anthropic are blocked.
- **Data affected:** none lost. `foodf4thought` still 81.6% coverage (the unassignable doc was not assigned).
- **Downstream:** `fail_count=1` on AgeManagment, genotek, mediamedics, profendocrinologist, tgnikitin at audit time. Scheduler will keep retrying and re-pause on billing.
- **Duration:** billing-block until owner refills **and** the other program is stopped or moved off this account. Phase 2 cost defect is ongoing.

---

## What we did (mitigation)

Read-only. No deploy, no `.env` change, no credit refill, no pause of sources.

- MCP: `get_pipeline_status`, `get_llm_config`, `list_channels`.
- Prometheus: `increase(tg_parser_llm_tokens_total[…])` by model / hour / job.
- Postgres: `source_attempts` hourly + by channel; `topic_cards` catalog size.
- Logs: `tg_parser` / `tg_parser_bot` around 06:00, 05:32, 12:31.
- Host: only the three `tg_parser*` containers have `ANTHROPIC_API_KEY`; they share one key.

Owner action (outside this repo): inspected Claude Console Usage/Cost and attributed the large spend to another program.

---

## What still needs to happen (follow-ups)

Parked for a later session. Each item is sprint-scope sized.

1. **Phase 2 context cap.** Do not send `list_all()` scopes. Options to weigh: top-K by embedding/Jaccard; title-only for foreign cards; hard token budget; `cross_channel_topicization=False` on discover only (keep Phase 3 linking).
2. **Observability.** `tg_parser_llm_tokens_total` has no `stage` label — Phase 2 is invisible except via logs + hourly spikes. Persist topicize tokens in `source_attempts.pipeline_stats`. Log `input_tokens` on `incremental_llm_batch_start` / Phase 2 complete.
3. **Before refill.** Confirm the other program is off this API key / account. Otherwise the next top-up disappears the same way. After refill, follow [`ANTHROPIC_BILLING_RECOVERY.md`](../../runbooks/ANTHROPIC_BILLING_RECOVERY.md) — do not lift `rate_limit_until` before credits exist.
4. **Optional until (1):** pause incremental topicization or set `CROSS_CHANNEL_TOPICIZATION=false` so a refill does not immediately spend ~$0.80 per keyword-miss. `foodf4thought` at 81.6% coverage will miss more often than the others.
5. **Key hygiene.** Separate Anthropic keys (or workspaces) per app so Console group-by-key is enough next time. Console cannot group by application name.

---

## Lessons / latent defects exposed

- A “massive leak” in Console is an **account** total. TG_parser Prometheus only sees this process. Same key on Cursor / Claude Code / Playground / another host is invisible here.
- Console Usage/Cost groups by **API key, workspace, model** — not by app. Shared key ⇒ one blob. Playground usage has `api_key_id=null`.
- `credit balance is too low` is **API credits**, not a claude.ai subscription.
- Phase 2 “cross-channel context” scaled with catalog size (355 cards in the 2026-04-20 genotek incident → 2131 now) and was never re-budgeted.
- `source_attempts` cannot answer “what burned Sonnet today” — topicize stats are not stored.

---

## Cross-references

- INBOX entry: [`docs/quality/INBOX.md`](../INBOX.md) → `2026-08-28 16:00 UTC — topicization · perf · P2`
- Triage entry: _n/a — not triaged; parked for a later session._
- Related incidents: [`2026-04-20_genotek_topicization_silent_failure.md`](2026-04-20_genotek_topicization_silent_failure.md) (same billing error; then the spender *was* topicization)
- Runbook: [`docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md`](../../runbooks/ANTHROPIC_BILLING_RECOVERY.md)
- Related: BUG-097 (processing dedup loop — **not** this; today `dedup=0`)
- Console docs: [Usage & Cost Admin API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api)
- Roadmap / future-features: _n/a — no existing sprint bullet for Phase 2 prompt-size._
