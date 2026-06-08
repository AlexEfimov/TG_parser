# ADR 0011 – Watchlist retroactive backfill rework (S3)

## Статус

**Accepted (2026-06-08).** Landed at code level in the S3 implementation
sub-session. Reworks `WatchlistService.backfill_interest` so the operator-
triggered retroactive scoring pass (1) defaults to the **full corpus** instead
of the interest's `created_at`, (2) scores the **whole matched corpus** in a
single batched pass (the `MAX_BACKFILL_DOCS=2000` newest-first cap is retired as
a scoring cap), and (3) on apply **silently materializes ALL matches**
(`notified=True`, no retroactive push) behind an **explicit confirmation gate**.
Local change — **not yet deployed**. The go-forward per-tick scheduler scoring
and the keyword aggregation / weights (ADR-0010) are **unchanged**.

## Контекст

`backfill_interest` closes the retroactive gap (DIAG 2026-06-07 hypothesis B2):
the scheduler only ever scores documents that become *new* `processed_documents`
within a tick (`check_interests` → `new_doc_refs`), so a corpus ingested
*before* an interest was created is never evaluated. The original backfill
(`tg_parser/services/watchlist_service.py`) had two latent defects and one
conflated budget.

### Problem A — empty window for a newly created interest

```
cutoff = since or interest.created_at
```

For a freshly created interest, `created_at ≈ now`, so the default window
(`since=None`) is effectively empty: `list_by_channel(channel_id, from_date=now)`
returns ~0 rows → 0 candidates. The single most common onboarding action —
"I just created an interest, score my history" — silently did nothing. The
operator had to know to pass an explicit `--since` far in the past.

### Problem B — the 2000-doc cap hides old on-topic matches

```
effective_limit = max(1, min(limit, MAX_BACKFILL_DOCS))   # 2000
ordered = sorted(docs, key=processed_at, reverse=True)[:effective_limit]
```

`processed_doc_repo.list_by_channel(...)` already returns **all** docs since the
cutoff (no DB `LIMIT`; `ORDER BY source_ref ASC`). The 2000 cap was a purely
in-memory scoring-cost guard. But by keeping only the **newest** 2000 docs
across all channels, any on-topic document older than the 2000-th newest was
**invisible** to dry-run / calibration. For broad multi-channel interests over a
large corpus this systematically under-reported `would_match` and `max_combined`
— exactly the numbers an operator inspects before applying
([`CAL_WATCHLIST_DECISION_HYPERPROLACTINEMIA_2026-06-08.md`](../notes/CAL_WATCHLIST_DECISION_HYPERPROLACTINEMIA_2026-06-08.md)
§ reports the in-window ceiling rather than the true corpus ceiling).

### The real per-doc cost was an N+1, not the doc count

The dominant cost was **not** scoring — it was one DB round-trip per doc:

```
for ref in scored_docs:
    stored = await self.embedding_repo.get_by_source_ref(ref)   # N+1
```

So the 2000 cap was bounding the wrong thing. Killing the N+1 (one batched
fetch) makes a whole-corpus pass cheap enough that no scoring cap is needed for
current corpus sizes (~8.5k docs/interest).

### One number served three different concerns

`MAX_BACKFILL_DOCS` simultaneously bounded (a) scoring cost, (b) how many
`watch_matches` rows got materialized on apply, and (c) — transitively — how
many matches were notified. These are independent concerns with different risk
profiles:

- **Scoring budget** — a memory/CPU cost. For an accurate dry-run/calibration it
  must cover the whole matched corpus.
- **Materialization budget** — `watch_matches` rows are idempotent
  (`UNIQUE (interest_id, source_ref)`) and cheap. Row count is not the
  user-facing risk.
- **Notification** — the *actual* flood risk. A naive apply over a large
  backlog could push a retroactive storm to the user's chat.

## Decision

1. **Default cutoff = full corpus.** `since=None` now means *no lower date
   bound* (`cutoff = since`; `list_by_channel(channel_id, from_date=None)`),
   NOT `interest.created_at`. This fixes Problem A: a freshly created interest
   is scored against its channels' entire history by default. An explicit
   `since` keeps the old windowed behaviour exactly.

2. **Scoring budget = whole matched corpus; batched embedding fetch.** The
   `MAX_BACKFILL_DOCS=2000` newest-first cap is **retired as a scoring cap**
   (Problem B). The per-ref N+1 is replaced by a single
   `EmbeddingRepo.get_many_by_source_refs(refs) -> dict[str, DocumentEmbedding]`
   (`WHERE source_ref = ANY(:refs)`, IN-list chunked at 1000/query, mapped via
   the existing `_row_to_model`). The `limit` CLI/API/MCP parameter is retained
   for backward-compat but is now **optional and uncapped by default**: when
   omitted the whole matched corpus is scored; when an explicit value is passed
   it acts as a newest-first preview cap. Scoring is **never silently
   truncated** when the caller did not ask.

3. **Apply = full, silent, idempotent materialization — no arbitrary limit.**
   On `dry_run=False` the backfill scores the same full corpus as dry-run and
   materializes **ALL** matches via the idempotent `upsert_many` path. Because
   the user-facing risk is **notification**, not row count, backfill matches are
   inserted with **`notified=True`** ("seen") so they appear in match history
   but are **not** pushed. `notify()` is the only push mechanism and backfill no
   longer calls it; marking rows `notified=True` additionally makes any future
   `notified=False` selector skip them. Go-forward per-tick matches keep
   `notified=False` and notify normally — **unchanged**.

4. **Explicit confirmation gate for apply.** Apply is a bulk, mutating,
   retroactive operation, so the entrypoints gate it:
   - **CLI** (`tg-parser watchlist backfill`): `--apply` requires `--yes`/`-y`;
     without it an interactive `typer.confirm` prompt is shown and a declined
     prompt aborts cleanly.
   - **MCP** (`backfill_watchlist`): a `confirm: bool = False` argument; a
     mutating call (`dry_run=False`) without `confirm=true` is rejected with a
     `confirmation required` error and writes nothing.
   - **Bot**: there is **no** watchlist-backfill bot tool, so nothing to gate.
   No arbitrary numeric materialization limit is added.

5. **Go-forward scheduler scoring is untouched.** S3 is backfill-path only.
   `check_interests` per-tick scoring, its `MAX_DOCS_PER_TICK` guard, and its
   `notified=False` → `notify()` behaviour are unchanged.

6. **Weights / aggregation unchanged.** Backfill keeps calling
   `compute_watch_score(..., aggregation=self._keyword_aggregation,
   topk=self._keyword_topk)` — the ADR-0010 top-k (K=3) keyword aggregation and
   the 0.4 / 0.6 weights are not touched.

## Backfill behaviour contract (pinned by tests)

- `since=None` → score every `processed_document` for the interest's channels
  (no lower date bound), even for an interest whose `created_at ≈ now`.
- No implicit scoring cap: a corpus of `> 2000` docs is scored in full;
  `scored_docs` reflects the true matched-corpus size.
- Explicit `limit=N` → newest-first preview of `N` docs (back-compat).
- Batched `get_many_by_source_refs` yields the same per-doc scores as the old
  per-ref `get_by_source_ref` loop (parity).
- `dry_run=False` materializes matches with `notified=True`; `notify()` is not
  invoked by backfill. Go-forward `check_interests` matches remain
  `notified=False` and still notify.
- CLI `--apply` without `--yes` does not mutate; MCP apply without `confirm`
  returns a `confirmation required` error and writes nothing.

## Contracts check

No JSON Schema in `docs/contracts/` pins `BackfillResult`, `watch_matches`, or
the MCP/bot backfill tool I/O (grep over `docs/contracts/` for
`backfill | BackfillResult | watch_match | would_match | scored_docs` is clean;
the schemas there cover `knowledge_base_entry`, `processed_document`,
`raw_telegram_message`, `subscription_target`, `topic_bundle`, `topic_card`,
`topic_card_version`, `workspace`). `BackfillResult` is an in-memory dataclass;
the `watch_match_repo` serializes the unchanged float score columns plus the
existing `notified` boolean. No contract surface is touched — the only field
whose *value* changes for backfilled rows is `notified` (now `True`), which is
an already-persisted column with no schema change.

## Перф

- Backfill embedding fetch goes from **N** round-trips (one per doc) to
  **⌈N/1000⌉** batched `ANY()` queries. For a whole-corpus pass over ~8.5k docs
  this is ~9 queries instead of ~8 500.

## Test strategy

- **Problem A:** `since=None` on an interest with `created_at ≈ now` scores the
  full corpus (was 0 candidates before).
- **Problem B:** a `> 2000`-doc corpus is scored without truncation in dry-run
  (`scored_docs` exceeds the retired 2000 cap); explicit `limit=N` still caps
  newest-first.
- **Batched parity:** scores from the batched fetch equal the per-ref values.
- **Silent apply:** materialized backfill matches carry `notified=True`;
  go-forward `check_interests` matches stay `notified=False`.
- **Confirmation gate:** CLI `--apply` without `--yes` aborts without writing;
  MCP apply without `confirm` returns `confirmation required`.
- Existing `TestBackfillInterest` cases that encoded the `created_at` default or
  the 2000 cap are updated with an ADR-0011 reference comment.

## Последствия

### Положительные

- Onboarding works: "score my history" on a fresh interest is no longer a no-op.
- Calibration is accurate: dry-run reflects the true corpus ceiling, not the
  newest-2000 window ceiling.
- N+1 → batched fetch makes a whole-corpus pass cheap.
- Apply is safe by construction: silent materialization + explicit confirmation
  remove the retroactive-notification flood risk without an arbitrary row cap.

### Отрицательные / accepted debt

- Whole-corpus scoring is an in-memory pass; for corpus sizes well beyond
  current scale (~8.5k docs/interest) a future streaming/chunked scorer may be
  needed. Documented, not built — current sizes are comfortably in-memory.
- `--apply` UX changed (now requires `--yes` / `confirm`); the MCP tool dropped
  its `notify` argument and gained `confirm`. Callers/scripts must update. This
  is intentional: backfill is silent by design.

### Что НЕ меняется этим ADR

- Go-forward per-tick scheduler scoring and notification (`check_interests`,
  `MAX_DOCS_PER_TICK`, `notified=False` → `notify()`).
- Keyword aggregation (top-k, K=3) and weights (0.4 / 0.6) — see ADR-0010.
- The persisted `watch_matches` shape and the score-breakdown columns.

## Ссылки

- ADR 0010 (watchlist keyword aggregation) — adjacent context; this ADR keeps
  its aggregation/weights untouched.
- [`docs/notes/CAL_WATCHLIST_DECISION_HYPERPROLACTINEMIA_2026-06-08.md`](../notes/CAL_WATCHLIST_DECISION_HYPERPROLACTINEMIA_2026-06-08.md) — documents the in-window-ceiling symptom of Problem B.
- `tg_parser/services/watchlist_service.py` — `backfill_interest`, `BackfillResult`.
- `tg_parser/storage/ports.py`, `tg_parser/storage/sqlalchemy/embedding_repo.py` — `EmbeddingRepo.get_many_by_source_refs`.
- `tg_parser/cli/watchlist_cmd.py` — `backfill` command (`--yes` gate).
- `tg_parser/mcp_server.py` — `backfill_watchlist` tool (`confirm` arg).
- `tests/test_watchlist_service.py`, `tests/test_f11_cli_watchlist.py`, `tests/test_f11_mcp_tools.py`.

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-08 | Created and Accepted at code level in the S3 implementation sub-session. Default backfill cutoff → full corpus; whole-corpus batched scoring pass (N+1 → `get_many_by_source_refs`); `MAX_BACKFILL_DOCS` retired as a scoring cap; apply silently materializes ALL matches (`notified=True`) behind an explicit CLI `--yes` / MCP `confirm` gate, no arbitrary limit. Go-forward scheduler scoring and ADR-0010 aggregation/weights unchanged. Local change — not yet deployed. |
