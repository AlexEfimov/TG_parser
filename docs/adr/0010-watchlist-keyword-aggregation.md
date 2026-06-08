# ADR 0010 – Keyword aggregation for the F11 watchlist hybrid score

## Статус

**Accepted (2026-06-08).** Landed at code level in the S1 implementation
sub-session: the keyword component of the F11 watchlist hybrid score now
defaults to a **top-k (capped) recall** aggregation (`K=3`) instead of the
mean-recall fraction, with `watchlist_keyword_aggregation="mean"` as the
production rollback knob. Decision is backed by a full-corpus read-only
what-if simulation across 5 production + 10 CAL pilot interests
([`CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md`](../notes/CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md)).
Code default flipped to `topk`; **not yet deployed** (local change). The
operator may keep `Accepted` or downgrade to a staged-rollout note when
shipping; the `mean` env knob makes the change instantly reversible without a
redeploy of new code.

## Контекст

### The denominator-penalty problem

The F11 watchlist scores each `(interest, document)` pair with a hybrid model
(see `tg_parser/services/watchlist_service.py`):

```
combined        = keyword_weight * keyword + semantic_weight * semantic   (0.4 / 0.6)
semantic        = cosine(interest_embedding, doc_embedding)  clipped [0, 1]
keyword (MEAN)  = matched_phrases / total_phrases            # _keyword_score
```

A *phrase* is one keyword; it "hits" only when **all** its normalized tokens
appear in the doc's normalized token set (`phrase <= doc_tokens`). The keyword
component was a **MEAN** recall: `hits / total_phrases`.

MEAN aggregation imposes a **denominator penalty**: every additional keyword an
interest names raises the denominator, so adding a rare or multi-word keyword
*dilutes* the keyword score for genuinely on-topic documents — even when the
document substantively matches the interest. Concretely (from the simulation,
full corpus):

- **Гиперпролактинемия** (10 keywords, threshold 0.60): only **2** docs clear
  under MEAN; the on-topic prolactin/hyperprolactinemia documents sit at
  ~0.587 because 5/10 phrase hits caps the keyword component at 0.5
  (`0.4·0.5 + 0.6·sem` can't reach 0.60 unless semantic is very high).
- **CAL W4 СПКЯ phrase pack** (5 keywords): scores **0 at every threshold**
  under MEAN — a 5-phrase pack where docs each hit only a subset is silently
  suppressed to nothing.

This is the per-interest workaround driver: the "atomic-pack" fix for
Гиперпролактинемия (splitting / trimming keywords) was a manual patch for
exactly this denominator penalty. We want a systemic fix.

### What the simulation measured

The read-only what-if study (no source changed, no prod writes) recomputed the
keyword component under four schemes over the same per-phrase hit booleans, for
15 interests, holding weights at 0.4/0.6 (S1 does not touch weights). Let
`h` = hitting phrases, `n` = total phrases, `k = min(3, n)`:

| scheme | keyword_score | character |
|---|---|---|
| `mean` (baseline) | `h / n` | denominator penalty |
| `max` | `1.0 if h>0 else 0.0` | any keyword present |
| `topk` (topk_mean) | `min(h, k) / k` | denominator capped at `k` |
| `sqrt` | `sqrt(h / n)` | softer penalty |

Key findings (see report §3–§6):

- **`topk` recovers recall with NO material false positives.** Every newly
  cleared doc inspected under `topk` was on-topic (Гиперпролактинемия 2→19
  @0.60; mTOR 6→26 @0.50; Микробиота 13→33 @0.50).
- **`topk` is a strict no-op for `n <= 3`** (atomic pilots W1/W3/W8/W9/W10, the
  2-kw W2, the 3-kw W6/W7 are byte-identical). For `n <= k`, `k = n` so
  `min(h, k)/k = h/n` exactly.
- **`max` admits material false positives**: lab-promo ads (W5 `kdl_ru:278`),
  near-empty docs (Биомаркеры `AgeManagment:542`), and cross-topic bleed (a
  GLP-1 aging paper clears the **mTOR** interest on one incidental token). It
  scores a doc with one incidental keyword the same as a doc nailing all of
  them, and would need a large (~+0.15–0.20) global threshold lift that
  *still* can't fully restore precision.
- **`sqrt`** is clean but lifts recall ~half as much as `topk` (Гиперпролактин.
  only 2→4 @0.60) and perturbs the small (n=2,3) controls — a weaker, less
  predictable knob.

## Decision

1. **Adopt `topk` (capped recall) as the default keyword aggregation**, with
   `K = min(watchlist_keyword_topk, n_phrases)` and `watchlist_keyword_topk = 3`.
   Closed form (phrase hits are binary, so the top-k *mean* is exactly
   `min(h, k)` ones and `k - min(h, k)` zeros):

   ```
   k = min(K, total_phrases)
   topk  = min(hits, k) / k            # total_phrases > 0
   mean  = hits / total_phrases        # rollback
   total_phrases == 0  ->  0.0         # both schemes
   ```

2. **Ship a global rollback knob.** `watchlist_keyword_aggregation:
   Literal["mean", "topk"] = "topk"` and `watchlist_keyword_topk: int = 3`
   (`ge=1`) in `Settings`, mirroring the existing `watchlist_keyword_weight` /
   `watchlist_semantic_weight` / `watchlist_default_threshold` pattern. Setting
   the env var to `"mean"` reverts to the original behaviour **without a code
   deploy** — this is the production rollback path.

3. **Default = topk out of the box** (code default), not gated behind opt-in.

4. **Keep weights at 0.4 / 0.6** and **keep current thresholds**. No global
   recalibration: `n <= 3` interests are mathematically unchanged; `n >= 4`
   interests just realize their intended (less-penalized) recall point.

5. **Diagnostics:** `WatchScore` gains `keyword_hits` / `keyword_total` (raw
   phrase counts, default 0). In-memory only — never serialized to a contract
   surface — so operators can read *how many* keywords matched independently of
   the aggregation scheme.

### Aggregation contract (pinned by tests)

Given `phrases` = tokenized non-empty keyword phrases, `hits` = phrases that are
subsets of `doc_tokens`, `K = watchlist_keyword_topk` (default 3):

- **mean:** `score = hits / len(phrases)`
- **topk:** `k = min(K, len(phrases)); score = min(hits, k) / k`
- **len(phrases) == 0 → 0.0** (both schemes)

Invariants (each has an explicit unit test in `tests/test_watchlist_score.py`):

- **INV-1 (safety / no-op):** for `len(phrases) <= K`, `topk == mean` exactly.
  All atomic and `<=3`-keyword interests are byte-identical, so existing
  thresholds are preserved by construction. Tested for `n ∈ {1, 2, 3}`.
- **INV-2 (anti-max / precision):** a doc hitting 1 of 10 keywords scores
  `1/3` under topk (`K=3`), **not** `1.0`. Explicit `topk != max` assertion.
- **INV-3:** monotonic non-decreasing in `hits`; bounded `[0, 1]`;
  `exclude_keywords` still hard-zero the combined score (excluded path
  unchanged).

### Why `max` and `sqrt` were rejected

- **`max` rejected** for precision: it equates one incidental keyword with
  nailing all of them, admitting ads, near-empty docs, and cross-topic bleed
  (report §5.3). Needs a large global threshold lift that still cannot fully
  restore precision.
- **`sqrt` rejected as primary**: lift too small to fix the headline cases
  (Гиперпролактин. 2→4 @0.60), and it perturbs the n=2/3 controls that `topk`
  leaves untouched. Retained only as a theoretical fallback.

### Backward-compat statement

- **No-op for `<= K` keywords** (INV-1): atomic pilots and small packs score
  identically; their thresholds are untouched.
- **Thresholds unchanged**: `>=4`-keyword interests rise in recall but every
  newly cleared doc inspected was on-topic. Two broad multi-channel interests
  (Биомаркеры: ~122 @0.50; GLP-1: ~102 @0.50) **may** want an optional
  **+0.05** threshold bump *post-deploy* if push volume is uncomfortable — an
  operational volume lever, **not** a code change and **not** a prerequisite.
- **Weights stay 0.4 / 0.6.**
- **`mean` env knob** is the instant rollback.

## Test strategy

- `_keyword_score` / `_aggregate_keyword_score` unit tests: INV-1 (parametrized
  `n=1,2,3` `mean==topk`), INV-2 (`1/10 → 1/3` and `topk != max`), INV-3
  (monotonicity, bounds, `len 0 → 0`, exclude hard-zero).
- Global-default test: `Settings().watchlist_keyword_aggregation == "topk"`.
- `aggregation="mean"` reproduces the old fraction for an `n>=4` pack.
- Existing exact-fraction tests for `n>=4` packs updated: mean-math tests pin
  `aggregation="mean"`; behavioural tests adopt the topk value with an
  ADR-0010 reference comment.

## Contracts check

No JSON Schema in `docs/contracts/` pins `WatchScore` / `watch_matches` /
the score breakdown (grep is clean — the watch_match repo serializes
`keyword_score` / `semantic_score` / `combined_score` floats only, which are
unchanged). The new `keyword_hits` / `keyword_total` fields live solely on the
in-memory `WatchScore` dataclass and are not added to any persisted/contract
surface, so no contract is touched.

## Последствия

### Положительные

- Removes the denominator penalty globally; multi-keyword interests realize
  their intended recall without per-interest keyword surgery.
- The Гиперпролактинемия per-interest atomic-pack fix becomes **unnecessary**
  for recall (2→19 @0.60 under topk, top-ranked on-topic).
- Strict no-op for `<=3`-keyword interests → zero blast radius for atomic
  pilots and small packs.
- Instant, code-free rollback via the `mean` env knob.

### Отрицательные / accepted debt

- A sparse multi-phrase pack where docs each hit only **one** term (W4-style)
  is barely helped by `topk` — those interests are better served by splitting
  into multiple single-keyword interests (the W1/W3/W8 pattern), not by
  aggregation. Documented, not fixed here.
- Score-scale shift for `>=4`-keyword interests: counts rise; the two broad
  interests may need the optional +0.05 volume bump post-deploy.

### Что НЕ меняется этим ADR

- Weights (`0.4 / 0.6`), thresholds, the exclude-keywords hard-filter path, the
  semantic component, and the persisted `watch_matches` shape.
- Single-keyword interests (`n=1`) — aggregation is irrelevant; all schemes
  equal.

## Ссылки

- [`docs/notes/CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md`](../notes/CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md) — full-corpus what-if simulation + recommendation (primary justification).
- [`docs/notes/CAL_WATCHLIST_DECISION_HYPERPROLACTINEMIA_2026-06-08.md`](../notes/CAL_WATCHLIST_DECISION_HYPERPROLACTINEMIA_2026-06-08.md) — the per-interest decision this ADR supersedes for recall.
- `tg_parser/services/watchlist_service.py` — `_aggregate_keyword_score`, `compute_watch_score`, `WatchlistService`, `make_watchlist_service`.
- `tg_parser/config/settings.py` — `watchlist_keyword_aggregation` / `watchlist_keyword_topk`.
- `tests/test_watchlist_score.py`, `tests/test_watchlist_service.py` — INV-1/2/3 + contract tests.
- ADR 0006 (Living-KB principles) — principle 6 (observability: keyword_hits/total).

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-08 | Created and Accepted at code level in the S1 implementation sub-session. Adopts `topk` (capped recall, K=3) as the default F11 keyword aggregation with a `mean` env rollback knob; rejects `max` (precision) and `sqrt` (weak lift). Backed by the full-corpus what-if simulation. WatchScore gains diagnostic `keyword_hits`/`keyword_total`. Weights and thresholds unchanged; strict no-op for `<=3`-keyword interests. Local change — not yet deployed. |
