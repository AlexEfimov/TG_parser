# ADR 0015 – Watchlist update-path re-embed + threshold recalibration (BUG-054)

## Статус

**Accepted (2026-06-13).** Closes BUG-054. Wires the ADR-0011 embedding path
and the ADR-0012 threshold-calibration path into `WatchlistService` **update**
(`_apply_upsert`), which previously persisted the mutable fields only — so a
keyword/description/channel edit left the stored embedding and the
auto-calibrated cutoff stale until the interest was deleted + recreated. Adds a
`threshold_source` provenance column (`{auto, manual, legacy}`) to
`watch_interests` so the update path knows whether it may overwrite the
threshold or must merely advise. Schema change is additive (nullable column +
CHECK); one ingestion migration with a `legacy` backfill. Local change —
**not yet deployed**.

## Контекст

F11 (ADR 0010–0014) ships the matcher, keyword aggregation, batched backfill
(ADR-0011), corpus threshold calibration (ADR-0012), the precision floor
(ADR-0013), and batch/silent delivery (ADR-0014). On **create**, `subscribe`
eagerly embeds the interest (`_embed_interest` → `update_embedding`) and, when
the caller omits `threshold`, auto-derives the cutoff via `calibrate_threshold`
(ADR-0012). On **update**, `_apply_upsert` recomputes a field diff and writes
the changed columns — but it never re-embeds and never recalibrates. The result
(BUG-054): editing `keywords` / `description` / `channel_ids` changes what the
user *intends* to match, yet semantic scoring still uses the **old** embedding
and the **old** threshold. The edit is a partial no-op for the scoring-relevant
fields. ADR-0012 §R5 explicitly deferred "recalibration on interest update" to
a follow-up; this ADR is that follow-up.

The blocker for a naive "always recalibrate on update" is **provenance**: if
the user pinned a threshold by hand, silently overwriting it with a corpus
suggestion on every keyword edit would be surprising and destroy their intent.
The threshold column never recorded *how* its value was chosen, so the update
path could not distinguish an auto-calibrated cutoff (safe to refresh) from a
hand-pinned one (must not be clobbered).

## Решение

### Provenance enum — `threshold_source ∈ {auto, manual, legacy}`

A new nullable `watch_interests.threshold_source` string column records how the
current `threshold` was set:

| Value | Meaning | Set when |
|---|---|---|
| `auto` | corpus-calibrated (ADR-0012) or the calibration-disabled default | create with `threshold=None` |
| `manual` | operator-pinned exact value | create/update with an explicit `threshold` |
| `legacy` | pre-BUG-054 row; provenance was never recorded | migration backfill only |

Runtime treats `legacy` **exactly like** `manual` (never overwrite, advisory
only), but the two stay distinguishable so a future reclassification job can
re-derive provenance for old rows without conflating them with values a user
actually pinned post-BUG-054.

### The HYBRID rule (locked, operator-approved)

**Create path** (`subscribe` INSERT branch + legacy `create_interest`):

- explicit `threshold` passed → `threshold_source = 'manual'`.
- `threshold=None` (calibration runs, OR calibration disabled → default `0.6`)
  → `threshold_source = 'auto'`.

**Update path** (`_apply_upsert`):

1. Compute the **text-field delta** = `{"description", "keywords",
   "channel_ids"} ∩ changed_fields`. (`title` is the natural key, not
   upsert-mutable, so it is never in the delta.)
2. If the text delta is **non-empty**:
   - Build a merged draft (`existing` + the update kwargs) and **re-embed** it
     via `_embed_interest` → `interest_repo.update_embedding`. The new text
     drives semantic scoring immediately.
   - **Recalibrate**: run `calibrate_threshold` on the merged draft
     (advisory-only — it never persists).
   - Branch on `existing.threshold_source`:
     - `auto` → persist the recalibrated `suggested_threshold`, keep
       `threshold_source = 'auto'`. The auto cutoff tracks the new intent.
     - `manual` / `legacy` / `NULL` → do **not** overwrite `threshold`;
       populate `SubscribeResult.threshold_calibration` with the advisory
       `ThresholdCalibration` (suggested value only) so the surface can show
       "your pinned threshold is X; the corpus now suggests Y".
3. If the caller passes an **explicit** `threshold` on update → set
   `threshold_source = 'manual'` and persist that value (overrides the branch
   above; an explicit pin always wins and re-marks provenance as manual).
4. `exclude_keywords` / `chat_id` / target / `notify_mode` / `workspace_id`
   changes **alone** do **not** trigger re-embed or recalibration (they do not
   change the canonical embedding text — see `build_canonical_interest_text`,
   which uses description + keywords).
5. The early no-op return (empty `update_kwargs`) is unchanged: an identical
   replay never embeds, recalibrates, or writes.

`NULL → manual` runtime rule: a row whose `threshold_source` is NULL (only
possible transiently before backfill, or via a hand-written row) is treated as
`manual` — the conservative choice never silently overwrites a threshold.

### Surface parity — MCP / bot / HTTP all reach `auto`

The create-path semantics ("omit `threshold` → auto-calibrate; pass an explicit
value → manual") are identical across all three surfaces. `WatchlistService.subscribe`
already accepts `threshold: float | None = None`, so the only requirement is that
each surface be able to express "omit". The MCP tool and bot tool already pass
`None` through when the operator omits the argument. The HTTP
`WatchlistCreateRequest.threshold` is therefore `Optional[float] = None`
(`Field(default=None, ge=0.0, le=1.0)`): an omitted threshold flows to the
service as `None` → calibration → `threshold_source = 'auto'`, while an explicit
value (still validated to 0..1) pins it → `threshold_source = 'manual'`. An
earlier draft of this surface defaulted the HTTP field to `0.6`, which forced
every HTTP-created interest to provenance `manual` and barred auto-calibration;
that asymmetry is resolved — HTTP now reaches full parity with MCP/bot.

### Legacy backfill heuristic + edge cases

The migration sets every pre-existing row to `threshold_source = 'legacy'`
because provenance was **never persisted** before this change — we cannot
reconstruct, after the fact, whether an old threshold was hand-pinned or
auto-calibrated. Edge cases the `legacy` bucket deliberately absorbs:

- **Provenance was never recorded** — the fundamental reason a third enum value
  exists rather than guessing `auto`/`manual`.
- **explicit == calibrated ambiguity** — a user who pinned exactly the value the
  corpus would have suggested is indistinguishable from an auto row; `legacy`
  refuses to guess.
- **pre-calibration rows** — interests created before ADR-0012 landed have a
  flat default `0.6` that is neither a corpus suggestion nor a deliberate pin.

Conservatively, `legacy` behaves like `manual` (advisory-only), so no old
threshold is ever silently overwritten on its first post-BUG-054 edit.

### Nullable + CHECK (expand/contract)

The column is **NULLABLE** with a CHECK constraint allowing
`('auto','manual','legacy')` (and NULL). It is intentionally **not** `NOT NULL`
now: this is the *expand* phase of an expand/contract migration. The
application always writes a non-null value on every new INSERT/UPDATE, and the
backfill fills existing rows, so in practice no NULLs remain — but tightening to
`NOT NULL` is deferred to a later contract migration once we are confident no
writer path leaves it NULL. Runtime treats NULL as `manual`-equivalent.

### Deferred follow-up — exclude_keywords-driven recalibration

`exclude_keywords` changes the *negative* filter and therefore the score
distribution (excluded docs drop out of the calibration sample), so in principle
an `exclude_keywords` edit could justify a recalibration. We **defer** this: the
canonical embedding text does not include `exclude_keywords`, so a re-embed is
never warranted, and the calibration delta from a negative-filter change is
second-order. Tracking as a BUG-054 follow-up rather than expanding the
text-field trigger now.

## Contracts check

No JSON Schema pins the watchlist subscribe I/O. The DB change is additive (a
nullable column + a CHECK constraint; backfill to `legacy`). The
`SubscribeResult.threshold_calibration` advisory field already existed
(create-only); this ADR populates it on the update path too — additive and
backward-compatible. MCP `SubscribeWatchlistResult.threshold_calibration`, the
bot tool dict, and the new optional HTTP
`WatchlistSubscribeResponse.threshold_calibration` are all additive. No removed
or renamed fields, no contract break.

## Тестовая стратегия

- `tests/test_watchlist_service.py`: update-path re-embed spy (asserts
  `_embed_interest` / `update_embedding` fire on a text-field update and do
  **not** fire on an `exclude_keywords`-only or threshold-only update);
  `auto` vs `manual` vs `legacy` recalibration branches (`auto` persists the new
  threshold; `manual`/`legacy` keep the threshold and return the advisory);
  `threshold_source` set correctly on create (explicit → `manual`,
  `None` → `auto`); explicit threshold on update → `manual` + persisted.
- `tests/test_subscribe_idempotency.py`: embedding client called on a text-field
  update.
- `tests/test_f11_watchlist_repo.py`: round-trips `threshold_source` through the
  PG repo (create + update_subscribe_fields).
- `tests/test_alembic_threshold_source_migration.py` (new, testcontainer): the
  column + CHECK exist, the backfill sets every existing row to `legacy`, the
  upgrade is idempotent, and the CHECK rejects an out-of-domain value.

## Последствия

### Положительные

- A watchlist edit now actually changes scoring: the embedding tracks the new
  text and an `auto` threshold re-tracks the new corpus distribution.
- Hand-pinned (`manual`) and old (`legacy`) thresholds are never silently
  clobbered; the user instead gets an advisory suggestion.
- Provenance is now first-class and auditable, unblocking future
  reclassification and a possible `NOT NULL` tighten.

### Отрицательные / accepted debt

- A text-field update now incurs one embedding call + one corpus calibration
  pass (same cost as create). Bounded; acceptable for an interactive edit.
- `legacy` rows behave like `manual` until (optionally) reclassified; a truly
  auto-calibrated old row will get advisories instead of auto-refresh on its
  first edit (conservative by design).
- `exclude_keywords`-driven recalibration is deferred (see above).
- The column stays nullable (expand phase); the `NOT NULL` contract step is
  future work.

## Ссылки

- BUG-054 (`docs/notes/BUG_LOG.md`) — the closed defect.
- ADR 0011 (batched embedding path reused by the re-embed),
  ADR 0012 (`calibrate_threshold` / `ThresholdCalibration`; §R5 deferred this
  follow-up), ADR 0013 (precision floor folded into the suggestion).
- `tg_parser/services/watchlist_service.py` — `subscribe` (create provenance),
  `_apply_upsert` (HYBRID update), `_embed_interest`, `calibrate_threshold`.
- `tg_parser/storage/sqlalchemy/watch_interest_repo.py`,
  `tg_parser/storage/ports.py`, `tg_parser/domain/models.py` — the
  `threshold_source` column / field plumbing.
- `migrations/versions/ingestion/20260613_bug054_threshold_source.py`,
  `tg_parser/storage/sqlalchemy/_metadata.py` — the schema change + guard.

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-13 | Created and Accepted. Closes BUG-054. Adds `threshold_source ∈ {auto,manual,legacy}` provenance column (nullable + CHECK, expand/contract; `legacy` backfill). HYBRID update rule: text-field delta (`description`/`keywords`/`channel_ids`) triggers re-embed + recalibration; `auto` persists the new threshold, `manual`/`legacy`/NULL keep it and return an advisory; explicit threshold on update → `manual` + persist; `exclude_keywords`/target/notify_mode/workspace alone do not trigger; `title` not upsert-mutable; calibration-disabled → `auto`. `SubscribeResult.threshold_calibration` now populated on update; surfaced via MCP/bot/HTTP. HTTP create-path threshold parity: `WatchlistCreateRequest.threshold` is now `Optional[float] = None` (omit → auto-calibrate; explicit → manual), resolving the earlier HTTP-always-`manual` asymmetry. `exclude_keywords`-driven recalibration deferred. Not yet deployed. |
