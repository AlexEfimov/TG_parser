# CAL — Watchlist decision: «Гиперпролактинемия и пролактин» (2026-06-08)

**Interest ID:** `cfc94eb9-164e-4232-a10b-8d5c4d6634db`
**Current config:** threshold `0.6`, 10 keywords, 5 channels
(`profendocrinologist`, `Lab4health`, `kdl_ru`, `genotek`, `labdiagnostica_logical`)
**Status:** never matched in production (`would_match = 0`).
**Scope of this note:** dry-run / read-only analysis only. No prod interest, threshold,
or scoring code was modified. Decision is advisory; apply requires explicit operator action.

Scoring model (unchanged): `combined = 0.4·keyword + 0.6·semantic`, where `keyword` is
phrase-level recall (each keyword is a phrase counted only if **all** its normalized tokens
appear in the doc tokens), `semantic` is cosine(interest_embedding, doc_embedding).

---

## 1. Why it never matched — root cause

Two independent factors, confirmed by the 2026-06-08 dry-run backfill + full-corpus decomposition:

1. **Threshold 0.6 is above the realistic ceiling for a 10-keyword pack.**
   The phrase-level keyword scorer divides by the number of keyword *phrases* (10 here).
   The pack mixes high-frequency single tokens (`пролактин`, `гиперпролактинемия`,
   `пролактинома`) with rare terms (`макропролактин`, `лактотрофы`, `галакторея`) and
   two multi-word phrases (`агонисты дофамина`, `аденома гипофиза`) that require **both**
   tokens present. Even a textbook on-topic clinical case maxes out at `keyword = 0.7`
   (7/10). With `semantic ≈ 0.61–0.68`, `combined` tops out at ~0.65–0.69 only on the very
   best documents, and most on-topic docs land at 0.50–0.59.

2. **The capped backfill window hides the real matches.**
   `backfill_interest` scores at most `MAX_BACKFILL_DOCS = 2000` *newest* documents
   (by `processed_at`). The full corpus for this interest is **8 502** docs. The two
   documents that actually clear 0.6 are **older** clinical-case posts
   (`profendocrinologist:1707` = 0.6892, `:1709` = 0.6474) and fall **outside** the
   newest-2000 window. Inside that window the ceiling is only 0.5079
   (`profendocrinologist:3868`). So the prod `would_match = 0` is partly threshold and
   partly an artifact of the backfill cap + the per-tick scheduler never having seen the
   pre-interest historical docs.

**Net:** at the genuine corpus level the interest *would* surface 2 docs at 0.6 and
4 docs at 0.5 with the current keywords; with a tighter atomic pack it surfaces 3 at 0.6
and **8 at 0.5**. All of these are on-topic (prolactin / prolactinoma / hyperprolactinemia
clinical cases and a lab explainer); no noise appears in the top results.

---

## 2. Evidence (full-corpus, since=2024, no 2000 cap)

### Option A — current 10 keywords, current 5 channels (8 502 docs)

| count ≥ | 0.45 | 0.50 | 0.55 | 0.60 |
|---|---|---|---|---|
| docs | 8 | 4 | 3 | **2** |

Top documents (combined / kw / sem):

| combined | kw | sem | source_ref | on-topic? |
|---|---|---|---|---|
| 0.6892 | 0.70 | 0.682 | `profendocrinologist:1707` — пролактин-секретирующая аденома гипофиза | ✅ healthy |
| 0.6474 | 0.70 | 0.612 | `profendocrinologist:1709` — лечение пролактиномы бромокриптином | ✅ healthy |
| 0.5869 | 0.50 | 0.645 | `Lab4health:1518` — пролактин: функции, гиперпролактинемия, макропролактин | ✅ on-topic, capped by kw |
| 0.5079 | 0.40 | 0.580 | `profendocrinologist:3868` — вторичная гиперпролактинемия при гипотиреозе | ✅ on-topic |
| 0.4822 | 0.40 | 0.537 | `profendocrinologist:653` — гигантская пролактинома | ✅ on-topic |

→ no off-topic documents in the top-8 down to combined 0.46.

### Option B — atomic 5-keyword pack, re-embedded, current 5 channels (8 502 docs)

Pack: `пролактин, гиперпролактинемия, пролактинома, каберголин, бромокриптин`

| count ≥ | 0.45 | 0.50 | 0.55 | 0.60 |
|---|---|---|---|---|
| docs | 15 | **8** | 6 | 3 |

Top documents:

| combined | kw | sem | source_ref | on-topic? |
|---|---|---|---|---|
| 0.7228 | 0.80 | 0.671 | `profendocrinologist:1707` | ✅ healthy |
| 0.6742 | 0.80 | 0.590 | `profendocrinologist:1709` | ✅ healthy |
| 0.6229 | 0.60 | 0.638 | `Lab4health:1518` (now clears 0.6) | ✅ healthy |
| 0.5790 | 0.60 | 0.565 | `profendocrinologist:651` — гигантская пролактинома | ✅ |
| 0.5645 | 0.60 | 0.541 | `profendocrinologist:1706` — микроаденома, рефрактерная к каберголину | ✅ |
| 0.5564 | 0.60 | 0.527 | `profendocrinologist:653` | ✅ |
| 0.5471 | 0.60 | 0.512 | `profendocrinologist:3039` — микроаденома + гиперпролактинемия | ✅ |
| 0.5053 | 0.40 | 0.575 | `profendocrinologist:3868` | ✅ |

→ dropping the 5 rare / multi-word keywords **raises** the keyword fraction for genuinely
on-topic docs (denominator 5 instead of 10), and the re-embedded interest text concentrates
on the core concept, lifting both components. Still zero noise in the top-8.

### Option C — current 10 keywords, reduced scope `profendocrinologist` + `labdiagnostica_logical` (4 649 docs)

| count ≥ | 0.45 | 0.50 | 0.55 | 0.60 |
|---|---|---|---|---|
| docs | 7 | 3 | 2 | 2 |

The combined score is computed **per document** and is independent of channel scope —
narrowing the scope cannot raise any document's score, it can only remove candidate docs.
In this corpus there are **no false positives** in the full-scope top results, so reducing
scope buys no precision and actually **loses** recall: it drops `Lab4health:1518` (the
on-topic prolactin explainer, 0.5869), taking @0.50 from 4 → 3.

---

## 3. Comparison of options

| Option | Change | @0.50 matches | @0.60 matches | Precision (top-8) | Risk / cost |
|---|---|---|---|---|---|
| **(a)** threshold 0.6 → 0.50, keep 10 keywords | 1 field | 4 (all on-topic) | 2 | clean | lowest; no re-embed |
| **(b)** atomic 5-keyword pack + threshold 0.50 | keywords + threshold (+ re-embed) | **8 (all on-topic)** | 3 | clean | edits keywords; triggers re-embed |
| **(c)** reduce scope to 2 high-signal channels | channel_ids | 3 | 2 | clean | **negative**: loses recall, no precision gain |

---

## 4. Recommendation — primary: **Option (b)** (atomic pack + threshold 0.50)

Replace the 10-keyword pack with the atomic 5-term pack
`пролактин, гиперпролактинемия, пролактинома, каберголин, бромокриптин`
and lower the threshold from `0.6` to `0.50`, keeping all 5 channels.

**Justification (data-driven):**
- It is the only option that meaningfully improves recall: **8 on-topic matches @0.50**
  vs 4 (option a) vs 3 (option c), and 3 @0.60 vs 2.
- It addresses the actual root cause — phrase-recall dilution from rare/multi-word
  keywords — rather than masking it by moving the cutoff alone.
- Precision is not sacrificed: the top-8 are 100% on-topic (prolactin/prolactinoma/
  hyperprolactinemia clinical cases + the lab explainer); the weakest retained doc
  (`:3868`, secondary hyperprolactinemia) is still squarely on-topic.
- No scoring-code or weight change required — keywords, threshold and channels are all
  per-interest config.

**Low-risk fallback / phase-1:** if editing keywords is undesirable, **Option (a)**
(threshold 0.50, keep current keywords) already yields 4 clean matches with zero config
churn and no re-embed. It is a strictly safe first step; option (b) can follow if recall
is judged too low.

**Reject Option (c):** narrowing scope cannot lift scores (scoring is per-doc) and removes
a genuine match; it only helps when off-topic channels generate false positives, which the
decomposition does not show here.

---

## 5. Residual risks

- **False positives at 0.50.** Threshold 0.50 sits closer to the semantic-noise floor.
  The broad channels `kdl_ru` / `genotek` (general lab marketing) could occasionally
  surface generic "сдайте анализ на пролактин" posts. Mitigation: keep/extend
  `exclude_keywords`; monitor the first weeks of matches and re-tighten if noise appears.
- **Compound-word gap.** `гиперпролактинемия` is a single token and is **not** lemmatized
  down to `пролактин` by pymorphy3; a doc that says only «гиперпролактинемия» does not hit
  the `пролактин` keyword. Both terms are deliberately kept as separate keywords in the
  atomic pack so either form scores. Do not collapse them.
- **Translit / cross-language gap.** The tokenizer lemmatizes Cyrillic (pymorphy3) and
  Latin≥3 (simplemma EN) independently but does **not** cross-map RU↔EN. English posts
  about "cabergoline" / "bromocriptine" / "prolactinoma" will not keyword-match the
  Cyrillic pack (they can still match semantically). If English coverage matters, add the
  Latin synonyms as extra keywords.
- **Historical matches need a backfill, and the backfill is capped.** The two docs above
  0.60 are older than the newest-2000 window, so `backfill --since 2024` (cap
  `MAX_BACKFILL_DOCS = 2000`) does not reach them and reports the in-window ceiling
  (0.5079) instead. Go-forward (per-tick) scoring is unaffected, but to retro-surface the
  historical clinical cases an operator must run a backfill whose window actually contains
  them (e.g. a narrower `--since`/date range), keeping in mind the 2000-doc hard cap.
