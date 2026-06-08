# S1 — Keyword-Aggregation What-If Simulation (F11 Watchlist)

**Date:** 2026-06-08
**Type:** READ-ONLY systemic investigation / what-if study. No source changed, no prod data written, no thresholds/keywords/interests modified, no `--apply`, no SQL writes. All computation was in-memory inside the `tg_parser` container over the **full corpus** (no 2000-doc cap).
**Question:** Should keyword aggregation move from the current **MEAN** scheme to one that removes the "denominator penalty"? Would such a scoring-model change (S1) make per-interest tuning (e.g. the Гиперпролактинемия atomic-pack fix) unnecessary?

---

## 1. Method & invariants

Service code: `tg_parser/services/watchlist_service.py`. Current model (unchanged here):

```
combined = KEYWORD_WEIGHT*keyword_score + SEMANTIC_WEIGHT*semantic_score   (0.4 / 0.6)
semantic_score = cosine(interest_embedding, doc_embedding)               # clipped [0,1]
keyword_score (MEAN)  = matched_phrases / total_phrases                  # _keyword_score()
```

A *phrase* = one keyword; it "hits" only if **all** its normalized tokens appear in the doc's normalized token set (`phrase <= doc_tokens`). Tokenization is the production script-routed lemmatizer (`watchlist_tokenizer.normalize_token`: Cyrillic→pymorphy3, Latin len≥3→simplemma EN, identity for digits/hyphens/mixed/short). `exclude_keywords` are a hard filter: any exclude-token in the doc forces `combined = 0`. When the doc has no embedding the formula collapses to pure keyword. All of this was replicated exactly.

**Single expensive pass:** for every (interest, doc) we tokenized the doc once, computed the per-phrase hit booleans once, and read the stored doc embedding once; the four aggregation schemes are then cheap re-derivations of `keyword_score` over the same hit counts. `combined` is recomputed per scheme; weights held at **0.4/0.6 for all schemes** (S1 does not touch weights).

Repos/service were wired through the production `watchlist_repos()` context manager + `make_watchlist_service(..., with_embedding_client=True)`. Interests with `embedding=None` would have been embedded lazily via the service helper (in-memory only, no DB write) — in practice all 15 already had stored embeddings (`embedded_lazily=False` for all).

### 1.1 Aggregation schemes simulated

Let `h` = number of hitting phrases, `n` = number of keyword phrases, `k = min(3, n)`.

| scheme | keyword_score | note |
|---|---|---|
| `mean` (baseline) | `h / n` | current production |
| `max` | `1.0 if h>0 else 0.0` | presence of **any** keyword |
| `topk_mean` | `min(h, k) / k`, `k=min(3,n)` | mean of top-k hitting phrases; denominator capped at 3 so keywords 4..n add no penalty |
| `sqrt_recall` | `sqrt(h / n)` | softer denominator, monotonic in `h` |

> `any_match` was dropped: in the binary phrase-hit setting it is **identical to `max`** (any hit ⇒ 1.0). We replaced it with `sqrt_recall` per the brief, giving 4 genuinely different curves.

**Algebraic facts that matter for the decision:**
- For **n ≤ 3**, `k = n` ⇒ `topk_mean ≡ mean` (mathematically identical). `topk_mean` is a **strict no-op** for all atomic (n=1) and small (n=2,3) interests.
- `topk_mean` only differs from `mean` for **n ≥ 4**, and only relaxes the penalty for the 4th..nth keyword.
- `sqrt_recall` differs from `mean` for **every n ≥ 2** (e.g. h=1,n=2: mean 0.5 vs sqrt 0.707), so it touches even the 2- and 3-keyword controls.
- `max` differs from `mean` for every n ≥ 2 and is the most aggressive.

---

## 2. Interests evaluated (READ-ONLY)

5 production interests + all 10 active `CAL:*` pilots (enumerated dynamically from `list_all()`, `is_active AND title startswith "CAL"`).

| id | title | thr | #kw (n) | #docs scored |
|---|---|---|---|---|
| 9f23fd49-8794-427d-a5c0-235a24e175cb | GLP-1 агонисты и семаглутид | 0.45 | 6 | 4934 |
| cfc94eb9-164e-4232-a10b-8d5c4d6634db | Гиперпролактинемия и пролактин | 0.60 | 10 | 8502 |
| 9deccefc-c388-4721-bb1f-b7e7dd51d8a5 | Микробиота и кишечный микробиом | 0.50 | 6 | 7976 |
| c4d87f14-9619-4394-8505-68ab20230d45 | Биомаркеры старения | 0.50 | 7 | 5573 |
| 64ce09c3-fa5c-4f57-8512-dde5fd160993 | mTOR и геропротекторы | 0.50 | 7 | 2577 |
| 88bbb92e-06fb-44d8-8dd5-9258cc96fd59 | CAL: W1 Пролактин atomic | 0.50 | 1 | 4649 |
| 567b963b-8dc2-4bfa-9b22-59105cdf857e | CAL: W10 Semantic noise stress | 0.50 | 1 | 5025 |
| f4c38dc5-8a83-4e3c-bd0a-543f04f82d79 | CAL: W2 Гипотиреоз atomic | 0.50 | 2 | 3477 |
| ef250fc9-9060-4b58-a2ed-b52a7a2fff7c | CAL: W3 Инсулинорезистентность atomic | 0.50 | 1 | 5343 |
| 0a0ef6ac-1692-44cb-acfb-f5b051397600 | CAL: W4 СПКЯ phrase pack | 0.50 | 5 | 3477 |
| a8901892-a0b4-40c6-aab5-0181b0ff0c80 | CAL: W5 Гиперпролактинемия phrase | 0.50 | 5 | 5506 |
| 27849366-a5ae-40be-9717-c938fe648992 | CAL: W6 GLP-1 EN control | 0.45 | 3 | 3816 |
| d001b0b3-51e9-4ee5-a322-ebdcc83960b4 | CAL: W7 Senolytics EN control | 0.45 | 3 | 1457 |
| ff8e377e-a4b6-4b9f-8904-9f583b5d3da9 | CAL: W8 Пролактин single-channel | 0.50 | 1 | 1172 |
| 580a3fc0-e60d-4d2f-80f6-5abeef5b236a | CAL: W9 Translit gap | 0.50 | 1 | 3816 |

---

## 3. Global table — `would_match @ OWN threshold` (scheme × interest)

| interest | thr | n | **mean** | **max** | **topk** | **sqrt** | precision (max) |
|---|---|---|---:|---:|---:|---:|---|
| GLP-1 агонисты и семаглутид | 0.45 | 6 | 45 | 279 | 150 | 156 | some-noise |
| Гиперпролактинемия и пролактин | 0.60 | 10 | 2 | 100 | 19 | 4 | some-noise |
| Микробиота и кишечный микробиом | 0.50 | 6 | 13 | 154 | 33 | 26 | some-noise |
| Биомаркеры старения | 0.50 | 7 | 25 | 527 | 122 | 87 | noisy (volume) |
| mTOR и геропротекторы | 0.50 | 7 | 6 | 101 | 26 | 15 | some-noise (cross-topic) |
| CAL: W1 Пролактин atomic | 0.50 | 1 | 40 | 40 | 40 | 40 | n/a (identical) |
| CAL: W10 Semantic noise stress | 0.50 | 1 | 947 | 947 | 947 | 947 | n/a (identical) |
| CAL: W2 Гипотиреоз atomic | 0.50 | 2 | 28 | 193 | 28 | 66 | some-noise |
| CAL: W3 Инсулинорезистентность atomic | 0.50 | 1 | 44 | 44 | 44 | 44 | n/a (identical) |
| CAL: W4 СПКЯ phrase pack | 0.50 | 5 | **0** | 122 | 1 | 0 | mostly-on-topic |
| CAL: W5 Гиперпролактинемия phrase | 0.50 | 5 | 3 | 79 | 11 | 11 | noisy (ads) |
| CAL: W6 GLP-1 EN control | 0.45 | 3 | 3 | 33 | 3 | 15 | some-noise |
| CAL: W7 Senolytics EN control | 0.45 | 3 | 3 | 12 | 3 | 7 | clean-ish |
| CAL: W8 Пролактин single-channel | 0.50 | 1 | 6 | 6 | 6 | 6 | n/a (identical) |
| CAL: W9 Translit gap | 0.50 | 1 | 70 | 70 | 70 | 70 | n/a (identical) |

Precision flag for **mean/topk/sqrt** = **clean** across the board (see §5: every doc that newly clears a threshold under `topk`/`sqrt` was judged on-topic). The flag column above reports the *additional* precision risk that **`max`** introduces.

### Per-scheme `max_combined` (score ceiling)

| interest | mean | max | topk | sqrt |
|---|---:|---:|---:|---:|
| GLP-1 | 0.641 | 0.806 | 0.793 | 0.676 |
| Гиперпролактинемия | 0.689 | 0.809 | 0.809 | 0.744 |
| Микробиота | 0.713 | 0.789 | 0.789 | 0.745 |
| Биомаркеры | 0.676 | 0.819 | 0.819 | 0.729 |
| mTOR | 0.632 | 0.771 | 0.771 | 0.684 |
| W4 СПКЯ pack | **0.394** | 0.645 | 0.500 | 0.486 |
| W5 Гиперпрол. phrase | 0.599 | 0.687 | 0.679 | 0.637 |

`max`/`topk` lift the ceiling of multi-keyword interests by **+0.10–0.20** (a doc that hits ≥3 / any keyword gets `keyword_score = 1.0`, i.e. `+0.4*(1-h/n)` on `combined`). `sqrt` lifts it ~half as much. Single-keyword interests are unchanged.

---

## 4. Threshold-grid tables (`would_match` at {0.45, 0.50, 0.55, 0.60, 0.65})

### 4.1 MEAN (baseline)

| interest | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 |
|---|---:|---:|---:|---:|---:|
| GLP-1 | 45 | 21 | 9 | 1 | 0 |
| Гиперпролактинемия | 8 | 4 | 3 | **2** | 1 |
| Микробиота | 20 | 13 | 8 | 4 | 3 |
| Биомаркеры | 48 | 25 | 12 | 5 | 2 |
| mTOR | 8 | 6 | 5 | 2 | 0 |
| W4 СПКЯ pack | **0** | **0** | 0 | 0 | 0 |
| W5 Гиперпрол. phrase | 7 | 3 | 2 | 0 | 0 |

### 4.2 TOPK_MEAN (k=min(3,n))

| interest | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 |
|---|---:|---:|---:|---:|---:|
| GLP-1 | 150 | 102 | 62 | 41 | 24 |
| Гиперпролактинемия | 37 | 31 | 26 | **19** | 16 |
| Микробиота | 43 | 33 | 23 | 18 | 14 |
| Биомаркеры | 146 | 122 | 91 | 57 | 39 |
| mTOR | 29 | 26 | 17 | 12 | 10 |
| W4 СПКЯ pack | 8 | 1 | 0 | 0 | 0 |
| W5 Гиперпрол. phrase | 20 | 11 | 10 | 8 | 2 |

### 4.3 MAX

| interest | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 |
|---|---:|---:|---:|---:|---:|
| GLP-1 | 279 | 279 | 277 | 242 | 160 |
| Гиперпролактинемия | 135 | 130 | 123 | **100** | 60 |
| Микробиота | 154 | 154 | 139 | 77 | 39 |
| Биомаркеры | 540 | 527 | 486 | 377 | 211 |
| mTOR | 102 | 101 | 91 | 70 | 41 |
| W4 СПКЯ pack | 125 | 122 | 73 | 16 | 0 |
| W5 Гиперпрол. phrase | 79 | 79 | 75 | 37 | 4 |

### 4.4 SQRT_RECALL

| interest | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 |
|---|---:|---:|---:|---:|---:|
| GLP-1 | 156 | 89 | 42 | 17 | 3 |
| Гиперпролактинемия | 28 | 17 | 8 | 4 | 3 |
| Микробиота | 39 | 26 | 18 | 13 | 6 |
| Биомаркеры | 146 | 87 | 44 | 22 | 8 |
| mTOR | 27 | 15 | 7 | 5 | 3 |
| W4 СПКЯ pack | 6 | 0 | 0 | 0 | 0 |
| W5 Гиперпрол. phrase | 18 | 11 | 3 | 1 | 0 |

> Single-keyword interests (W1, W3, W8, W9, W10) are byte-identical across all four schemes at every threshold — confirming aggregation is irrelevant when n=1.

---

## 5. False-positive analysis — the key S1 risk

A "false positive" here = a doc that **newly clears the interest's own threshold under a looser scheme but stays below it under `mean`**. Snippets were eyeballed for on-topic vs noise.

### 5.1 `topk_mean` — FPs are ON-TOPIC (clean)

Every new doc inspected under `topk_mean` was on-topic. Representative examples:

- **GLP-1** (new @0.45): семаглутид/Оземпик sales report (`profendocrinologist:3650`, h=3), GLP-1 CV-outcomes meta-analysis (`:2368`, h=2), oral GLP-1 orforglipron (`:3230`), amycretin trial (`:3511`). All squarely GLP-1/семаглутид.
- **Гиперпролактинемия** (new @0.60): `Lab4health:1518` (prolactin / hyperprolactinemia / macroprolactin, h=5, **on-topic, missed by mean at 0.587**), `profendocrinologist:3868` secondary hyperprolactinemia (h=4), prolactinoma cases `:651/:653/:1706` (h=3). A couple of acromegaly-with-pituitary-adenoma cases (`:1377`, `:3042`) appear — defensible because `аденома гипофиза` is an explicit keyword (adjacent, not noise).
- **Микробиота** (new @0.50): gut-microbiota / probiotics / microbiome-aging posts (`LongevityClub:83/168/28`, `kdl_ru:573`). On-topic.
- **mTOR** (new @0.50): geroprotectors, AMPK, mitochondria, curcumin longevity (`LongevityClub:267/109/116/43`). On-topic.
- **W5 Гиперпролактинемия phrase** (new @0.50): prolactinoma / hyperprolactinemia clinical cases (`:3868/:1706/:653/:651`). On-topic.

### 5.2 `sqrt_recall` — also clean, smaller lift

`sqrt` admits a strict-ish subset of the same on-topic docs (gentler boost). It additionally nudges single-hit docs in **n=2/3 controls** (W2: h=1→0.707; W6: h=1→0.577), which `topk` leaves untouched. Inspected W2/W6 additions are thyroid-domain / GLP-1-EN respectively — on-topic-adjacent, no spam.

### 5.3 `max` — introduces MATERIAL false positives (the precision risk)

`max` scores a doc with **one incidental keyword** the same as a doc nailing all of them, so a single keyword + a middling semantic (~0.6) clears the threshold. Confirmed off-topic / low-value docs newly clearing under `max`:

- **W5 Гиперпролактинемия phrase @0.50 — NOISY:** `kdl_ru:278` and `kdl_ru:1103` are **lab-promo ADS** ("скидка 20% на гормональные профили", h=1); `profendocrinologist:3392` is GLP-1→libido via dopamine (h=1, off-topic); `:3257` gynecomastia (h=1). These are genuine false positives.
- **mTOR @0.50 — cross-topic:** `LongevityClub:118` "GLP-1R agonists slow aging in mice" clears the **mTOR** interest on a single incidental token (h=1); generic "mechanisms of aging" reviews (`:175/:250`, h=1) also clear. Topic bleed.
- **GLP-1 @0.45:** many h=1 diabetes-general / device docs clear (e.g. `:131` DM2 treatment schemes). Mostly endo-adjacent but dilutes precision.
- **Биомаркеры @0.50 — volume blow-up:** 25→527. Includes h=1 longevity-general posts and even `AgeManagment:542` = *"Reference to a YouTube video"* (near-empty). On-topic rate stays high but the long tail is thin.
- **W4 СПКЯ pack @0.50:** 0→122. These are largely **on-topic PCOS** docs (oral contraceptives for PCOS, etc.) that the 5-phrase pack killed under `mean` — but they clear via a single keyword, defeating the "phrase pack" intent (precision is acceptable here only because the channel is endocrinology-pure).
- **W2 Гипотиреоз @0.50:** 28→193 via h=1 thyroid docs (lyothyronine, amiodarone-induced, тиреотоксикоз). Thyroid-domain but `тиреотоксикоз` is the opposite of `гипотиреоз` — semantic-only inclusion.

---

## 6. Synthesis

### 6.1 Best recall without material false positives → **`topk_mean`**
Across all 15 interests, `topk_mean` (k=min(3,n)) recovers substantial recall on the multi-keyword interests (e.g. Гиперпролактинемия 2→19 @0.60, mTOR 6→26 @0.50, Микробиота 13→33 @0.50) while **every newly-cleared doc was on-topic**. `max` recovers more raw volume but pays for it with ads (W5), near-empty docs (Биомаркеры), and cross-topic bleed (mTOR `:118`). `sqrt_recall` is clean but lifts recall ~half as much as `topk` and perturbs the small controls.

### 6.2 Does S1 make the Гиперпролактинемия per-interest fix unnecessary? → **Yes (with `topk_mean`).**
Under `mean` the 10-keyword pack dilutes genuine prolactin docs below 0.60 (only 2 clear; `Lab4health:1518` and `:3868` sit at ~0.587/0.60-). Under `topk_mean` those same on-topic docs clear **0.60 without any keyword edit** (19 matches, top-ranked all on-topic). So the atomic-pack edit (fix **b**) was a per-interest workaround for exactly the denominator penalty that `topk_mean` removes globally. **After S1 with `topk_mean`, the Гиперпролактинемия per-interest fix is no longer needed for recall** at its current 0.60 (and is comfortably satisfied at 0.50 too: 31 matches, on-topic). `sqrt` only gets it to 4 @0.60 — not enough on its own.

### 6.3 Threshold / weight recalibration
- **Weights:** keep **0.4 / 0.6** (S1 scope). No evidence to move them.
- **`topk_mean` thresholds — no global recalibration required:**
  - For **n ≤ 3** interests (all atomic pilots W1/W3/W8/W9/W10, the 2-kw W2, the 3-kw W6/W7) `topk_mean ≡ mean` → scores and counts are **identical**, so their thresholds are untouched by construction.
  - For **n ≥ 4** interests the `combined` ceiling rises by ≤ +0.4·(1−h/n); counts rise but stay on-topic. Current thresholds simply become the intended (less-penalized) recall point. Recommend **keep current thresholds and monitor volume**; only the broad, multi-channel interests (Биомаркеры: 122 @0.50; GLP-1: 102 @0.50) might warrant a small **+0.05** bump if push volume is uncomfortable — a tuning knob, not a correctness fix.
- **`max` would force a global threshold lift of ~+0.15–0.20** to suppress the h=1 noise, and even then keeps ads/cross-topic docs (see §5.3) — i.e. recalibration cannot fully repair `max`'s precision. This is the main argument against `max`.

### 6.4 Honest cons of each scheme
- **`mean` (current):** correct precision but the denominator penalty silently suppresses on-topic docs as soon as an interest names ≥4 keywords; a 5-phrase pack can score **0 at every threshold** (W4). This is the bug S1 targets.
- **`max`:** ignores *how many* keywords match — 1 incidental keyword ≡ nailing all of them. Highest recall, but admits ads, near-empty docs, and cross-topic bleed; needs a large threshold lift that still can't fully restore precision.
- **`topk_mean`:** middle ground. Removes the penalty beyond the top 3 keywords (so a doc must still substantively hit the interest, not just graze it), no-op for n≤3, clean precision. Con: a sparse multi-phrase pack where docs each hit only **one** term (W4 PCOS) is barely helped (topk 1 @0.50) — those interests are better served by splitting into atomic single-keyword interests (the W1/W3/W8 pilot pattern) than by aggregation.
- **`sqrt_recall`:** softens the penalty while staying monotonic and clean; but the lift is modest (Гиперпролактинемия only 2→4 @0.60) and it perturbs the small controls, giving a weaker, less predictable knob than `topk`.

### 6.5 Side finding (not an aggregation issue)
**W10 Semantic noise stress** (n=1) clears **947 docs @0.50 under every scheme**: with one broad keyword the 0.6 semantic weight dominates and 0.50 is simply a loose cutoff. This is orthogonal to aggregation (all four schemes equal) and points to a separate lever — per-interest threshold or a semantic floor for single-keyword interests — outside S1's scope.

---

## 7. RECOMMENDATION

1. **Adopt `topk_mean` with k = min(3, n_keywords)** as the keyword aggregation for F11, carried forward to an ADR. It gives the best recall recovery on the real corpus **without introducing material false positives** (every newly-cleared doc inspected was on-topic), and — crucially — it is a **strict no-op for all interests with ≤3 keywords**, so atomic pilots and small packs are unaffected.
2. **Keep weights at 0.4 / 0.6** and **keep current thresholds** (no global recalibration: ≤3-kw interests are mathematically unchanged; ≥4-kw interests just realize their intended recall). Treat a small **+0.05** threshold bump on the two broad, multi-channel interests (Биомаркеры, GLP-1) as an optional volume knob to evaluate post-deploy, not a prerequisite.
3. **Reject `max`** (precision: ads + cross-topic bleed; would require a large, still-insufficient threshold lift). **Reject `sqrt_recall`** as primary (lift too small; perturbs controls) — usable only as a fallback if topk's score-scale shift proves undesirable.
4. **The per-interest Гиперпролактинемия atomic-pack fix (b) becomes unnecessary after S1**: under `topk_mean`, on-topic prolactin docs clear 0.60 with the original 10-keyword pack (2→19, top-ranked on-topic). Keep S1 as the systemic fix; reserve atomic-keyword splitting for the genuinely sparse phrase-pack case (W4-style), where no aggregation helps and the right answer is multiple single-keyword interests.

> Caveat: precision labels in §3/§5 are snippet-level human judgments over top/added docs, not exhaustive corpus labeling; the volume/ceiling numbers are exact over the full corpus.
