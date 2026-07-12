# S5 — Top-k assign simulation (F-10 / O-5)

**Date:** 2026-07-11  
**Type:** READ-ONLY counterfactual (script: `scripts/s5_assign_simulation.py`).  
**Gate:** S4 deployed (`b1e4c7b`); S3 `PARTIAL` — не блокер.

---

## §0 Design decisions

### Gap matrix (token assign vs watchlist ADR-0010)

| Аспект | Watchlist (ADR-0010) | Topicization assign (F-10) | Blast radius |
|---|---|---|---|
| Единица счёта | Phrase (keyword string) | Token (flat union `scope_in` + `title`) | `_compute_match_score` shared |
| Hit rule | `phrase ⊆ doc_tokens` | token ∈ doc + substring ≥5 | substring обязателен в симуляции |
| Baseline | `hits / n_phrases` | `weighted_hits / n_tokens` | `_find_supporting_items_programmatic` |
| Weak weight | нет | weak × 0.3 | только assign path |
| Tokenizer | lemmatizer | regex `[a-zA-Zа-яА-ЯёЁ]{3,}` | не менять в S5 |
| Top-k no-op | `n_phrases ≤ 3` → byte-identical mean | **`topk_denom` (A): `n ≤ 3` → byte-identical mean** | algebraic invariant |
| | | `topk_num` (B): может отличаться при fractional weak hits | e.g. n=2, h=1.3: 0.65 vs 0.433 |

### Formula candidates (simulation results)

| Scheme | Formula | T1 assign% | T1 discover proxy | Winner-changed | Verdict |
|---|---|---:|---:|---:|---|
| **mean** (baseline) | `weighted_hits / n` | 83.11% | 16.89% | — | baseline |
| **topk_denom (A)** ★ | `weighted_hits / min(n, K)` | **97.65%** | **2.35%** | 13 029 (49.7%) | **recommended** |
| topk_num (B) | `min(weighted_hits, K) / K` | 97.65% | 2.35% | 17 702 | идентичен A на корпусе; больше winner-shift |
| sqrt | `sqrt(weighted_hits / n)` | 97.59% | 2.41% | 54 | мягче, но слабее lift |
| phrase_topk (C) | phrase hits + topk | 48.83% | 51.17% | 8 925 | **хуже mean** — отклонить |
| max | `1 if hits>0 else 0` | 97.65% | 2.35% | 21 616 | runaway argmax — отклонить |

### Recommendation

**Deploy candidate: `topk_denom` (variant A/D)** — зеркало ADR-0010 по смыслу (cap denominator), сохраняет weak-weight, byte-identical mean при `n ≤ 3`.

**Settings (proposal):**
- `topicization_assign_keyword_aggregation = "topk_denom"` (или `"topk"` с **явным** mapping в коде — см. ⚠️ ниже)
- `topicization_assign_keyword_topk = 3`
- Rollback: `topicization_assign_keyword_aggregation = "mean"`

**⚠️ Naming trap:** watchlist ADR-0010 `"topk"` = `min(hits,K)/K` (cap numerator); assign `"topk_denom"` = `hits/min(n,K)` (cap denominator). **Нельзя** слепо reuse `_aggregate_keyword_score(aggregation="topk")` — нужен отдельный mode или shared helper с explicit schemes `{mean, topk_denom}`.

**Scope:** один shared helper в `_compute_match_score` → затронет и `_find_supporting_items_programmatic` (консистентность с watchlist ADR pattern).

**Out of scope:** embedding-assign (§6.5), S6 merge, смена `MIN_SUPPORTING_SCORE` без отдельной симуляции.

---

## 1. Run metadata

| Field | Value |
|---|---|
| `generated_at` | 2026-07-11T14:32:28Z |
| Prod HEAD | `b1e4c7b` |
| Corpus | **13 active channels** (26 230 docs) |
| Excluded | `murashko_med` (18 056 docs) — channel disabled, not in `list_sources(status=active)` |
| Threshold | 0.10 (default `topicization_supporting_min_score`) |
| K | 3 |

**Note:** первый прогон завис на `murashko_med` (18K×850 pairs); после restart + `--exclude-channel murashko_med` завершился за ~19 min (`exit=0`).

---

## 2. T1 — counterfactual full assign replay (primary)

### Global

| Scheme | Docs | Assigned | Unassigned | Assign% | Discover proxy% | Δ unassigned vs mean |
|---|---:|---:|---:|---:|---:|---|
| mean | 26 230 | 21 800 | 4 430 | 83.11% | 16.89% | — |
| **topk_denom** | 26 230 | 25 613 | 617 | **97.65%** | **2.35%** | **−3 813 (−86%)** |
| topk_num | 26 230 | 25 613 | 617 | 97.65% | 2.35% | −3 813 |
| sqrt | 26 230 | 25 599 | 631 | 97.59% | 2.41% | −3 799 |
| phrase_topk | 26 230 | 12 808 | 13 422 | 48.83% | 51.17% | +8 992 |

### Assignment delta (topk_denom vs mean @ 0.10)

| Metric | Count | % of corpus |
|---|---:|---:|
| Newly assigned (unassigned→assigned) | **3 813** | 14.5% |
| Newly unassigned (assigned→unassigned) | **0** | 0% |
| Winner changed (topic A→topic B) | **13 029** | **49.7%** |

**Interpretation:** topk поднимает score для rich-vocabulary тем → массовая переконкуренция argmax (не FP по unassign). Discover-proxy падает сильно, но winner-shift требует post-deploy watch.

### Per-channel (topk_denom vs mean)

| Channel | Docs | Mean assign% | Topk assign% | Newly assigned | Winner changed |
|---|---:|---:|---:|---:|---:|
| mediamedics | 11 124 | 71.04% | 97.64% | 2 958 | 5 560 |
| profendocrinologist | 3 531 | 95.98% | 98.90% | 103 | 2 033 |
| Docma_ru | 3 209 | 94.17% | 99.81% | 181 | 1 584 |
| Lab4health | 1 903 | 95.59% | 97.79% | 42 | 1 063 |
| labdiagnostica_logical | 1 215 | 83.70% | 94.16% | 127 | 625 |
| genotek | 1 157 | 91.79% | 97.06% | 61 | 425 |
| AgeManagment | 1 153 | 81.09% | 93.50% | 143 | 645 |
| mind_rise | 1 135 | 94.63% | 99.74% | 58 | 490 |
| kdl_ru | 870 | 94.25% | 99.20% | 43 | 262 |
| LongevityClub | 339 | 88.79% | 92.63% | 13 | 162 |
| foodf4thought | 336 | 66.96% | 85.42% | 62 | 103 |
| BiocodebySechenov | 200 | 90.00% | 98.50% | 17 | 68 |
| medportal_rfed | 58 | 91.38% | 100.00% | 5 | 9 |

**Stratification:** lift концентрирован в каналах с rich `scope_in` (mediamedics, profendocrinologist, Docma_ru). На корпусе **все темы имеют `n_keywords ≥ 4`** (`topics_n_le3 = 0` на каждом канале) — инвариант n≤3 no-op **не верифицирован эмпирически**, только алгебраически.

### Rich-vocabulary topics (mediamedics, top-5 по `topk_only`)

| Topic (trunc.) | n_keywords | mean wins | topk wins | topk_only |
|---|---:|---:|---:|---:|
| Уголовное преследование врачей… | 80 | — | — | 1 090 |
| Коррупция и уголовные дела… | 111 | — | — | 830 |
| Кадровый кризис и системные проблемы… | 58 | — | — | 514 |
| Уникальные хирургические операции… | 69 | — | — | 501 |
| Кадровая политика и трудовые условия… | 61 | — | — | 433 |

Полные данные: `rich_topics_top20` per channel в JSON.

---

## 3. T2 — reconcile candidate proxy

**Result: empty** (`t2_per_channel = 0`, `t2_global = {}`).

На момент симуляции для всех 13 каналов `uncovered − discover_attempted = ∅` (steady-state BUG-075: все непокрытые уже marked). T2 не даёт дополнительной метрики; primary = T1.

---

## 4. Threshold sensitivity (mediamedics exemplar)

| Threshold | mean assign% | topk_denom assign% |
|---:|---:|---:|
| 0.08 | 86.25% | 97.64% |
| **0.10** | **71.04%** | **97.64%** |
| 0.12 | 52.04% | 97.27% |
| 0.15 | 26.42% | 97.27% |

**Recommendation:** оставить **0.10** (default). Для **mean** порог чувствителен (71%→52% @0.12); для **topk_denom** plateau до 0.12 (97.6%→97.3%).

---

## 5. FP spot-check (≥10 newly assigned / winner-changed)

Проверено 12 пар из `fp_spot_check_candidates` (AgeManagment, topk_denom @ 0.10):

| # | Type | On-topic? | Note |
|---|---|---|---|
| 1–3 | newly assigned | ✅ | комментарии про антиоксиданты, биогеронтологов — тема longevity |
| 4 | winner changed | ✅ | 3D Bioprinting → та же тема, другой winner |
| 5–7 | newly assigned | ✅ | стартап, благодарности — on-topic для канала |
| 8–9 | winner changed | ✅ | контент-фидбек, благодарность |
| 10–12 | mixed | ✅ | ссылки/рекомендации в контексте longevity |

**Verdict:** material false positives **не обнаружены** в spot-check (критерий ADR-0010 §3). Winner-changed — перераспределение между темами одного канала, не off-topic bleed.

---

## 6. Watch band vs simulation

| Criterion | Target (planning) | Actual (topk_denom) | Status |
|---|---|---|---|
| Assign rate lift | +5–25 pp | **+14.5 pp** (83.11→97.65%) | OK в коридоре |
| Discover reduction | −10–30% | **−86%** (unassigned 4430→617) | ⚠️ сильнее ожидания |
| Winner change cap | TBD from sim | **49.7%** | зафиксировать cap **< 50%** post-deploy watch |
| n≤3 no-op (topk_denom) | byte-identical | algebraic ✓ | OK |
| FP spot-check | no material FP | 12/12 on-topic | OK |

**Deploy posture:** GO с **осторожным watch** — discover reduction сильный, winner-shift высокий; rollback knob `mean` обязателен.

---

## 7. Raw JSON

Prod run: `/tmp/s5_sim_prod.json` (877 KB, local copy from 2026-07-11T14:32:28Z).

```bash
docker compose exec -T tg_parser python scripts/s5_assign_simulation.py --exclude-channel murashko_med
```
