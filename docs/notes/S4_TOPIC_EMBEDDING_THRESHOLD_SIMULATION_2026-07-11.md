# S4 — Topic embedding threshold simulation (F-04 / F-05)

**Date:** 2026-07-11  
**Type:** READ-ONLY baseline + what-if study (script: `scripts/s4_linking_simulation.py`).  
**Gate:** S3 delta `PARTIAL`, S4 `GO` ([`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md)).

---

## 1. before-S4 baseline (prod, HEAD `6904b0b`, 2026-07-11T07:25Z)

| Metric | Value |
|---|---|
| `topic_links` count | **2451** |
| avg `similarity_score` | **0.3290** |
| `document_embeddings` (`entry_type='topic'`) | **819** |
| topic cards total | **2046** |
| cards with topic embedding | **800** (39.1% coverage) |
| stale topic emb (`card.updated_at` > `emb.created_at`) | **193 / 800** (**24.1%**) |
| prod HEAD | `6904b0b` |

**Notes:**
- Current production linking uses **anchor (message) embeddings** — avg link score ≈0.33 matches ADR-0016 / MCP baseline (~1052 links @ ~0.33 in May; corpus grew to 2451 links).
- Topic embedding coverage **39%** → `load_card_embeddings` will use anchor fallback for ~61% of cards until backfill (AC-B).
- **24% stale** among cards that *do* have topic emb — MVP uses topic emb as-is; post-deploy watch recommended (stretch: stale → anchor fallback).

**Threshold sweep:** completed 2026-07-11T08:33Z (~46 min runtime, 1.64M cross-channel pairs).

---

## 2. Embedding resolve stats (simulated `load_card_embeddings`)

| Source mode | topic | anchor_fallback | missing |
|---|---:|---:|---:|
| **anchor-only** (current prod) | 0 | 0 | 157 |
| **topic + fallback** (S4) | 800 | 1090 | 156 |

53% of cards still resolve via anchor fallback in this run — **backfill before `link-topics` is mandatory** (AC-B). Post-backfill re-simulation recommended.

---

## 3. Cross-channel links (all-pairs, 14 channels, 2046 cards)

| Threshold | anchor_emb (current) | topic_emb (S4) | Δ topic vs anchor |
|---:|---:|---:|---:|
| 0.25 | 18 970 | 27 493 | +45% |
| **0.30** | **3 121** | **5 268** | **+69%** |
| 0.35 | 567 | 1 176 | +107% |
| 0.40 | 115 | 326 | +183% |

**Current prod:** 2 452 links @ avg 0.329 (built with anchor embeddings).

**Avg score all pairs:** anchor 0.1021 · topic 0.1063 (topic vectors slightly higher cosine overall).

### Snapshot diff @ 0.30 (vs current `topic_links`)

| Embedding | sim links | added | removed | score_changed | unchanged |
|---|---:|---:|---:|---:|---:|
| anchor_emb | 3 121 | 933 | 264 | 778 | 1 410 |
| **topic_emb** | **5 268** | **3 779** | **963** | **1 032** | **457** |

---

## 4. Same-channel merge losers (`_finalize_full_run` simulation)

| Threshold | anchor_emb | topic_emb | Δ |
|---:|---:|---:|---:|
| 0.55 | 13 | 27 | +108% |
| **0.60** | **9** | **18** | **+100%** |
| 0.65 | 5 | 13 | +160% |
| 0.70 | 4 | 11 | +175% |

Concentrated in `profendocrinologist` (15 losers @ 0.60 topic) and `murashko_med`. Absolute counts remain small (18 total @ 0.60) — **not a deploy blocker**, but watch on full-run resume channels.

---

## 5. Fine sweep @ 0.30–0.35 (topic_emb, 2026-07-11T11:10Z, ~6 min)

| Threshold | Links | vs prod (2452) | In ±20% band (1962–2942)? |
|---:|---:|---:|---|
| 0.30 | 5 266 | +115% | no |
| 0.31 | 3 794 | +55% | no |
| **0.32** | **2 807** | **+14%** | **yes** |
| **0.33** | **2 095** | **−15%** | **yes** |
| 0.34 | 1 555 | −37% | no |
| 0.35 | 1 176 | −52% | no |

Script: `python scripts/s4_linking_simulation.py --fine-sweep`

---

## 6. Threshold decision (final, pre-deploy)

| Setting | Decision | Rationale |
|---|---|---|
| `cross_channel_link_threshold` | **0.32** | Fine sweep: closest to prod volume in ±20% band (2807 vs 2452). 0.33 (2095) valid alternative if preferring tighter linking. |
| `topicization_full_merge_threshold` | **Keep 0.60 (watch-only)** | Losers 9→18 @ 0.60 — n=18 absolute; full-run path rare. |

**Deploy sequence:**
1. Backfill topic embs (`force=True` per channel) — 53% anchor fallback today confounds scores
2. Optional: re-run `--fine-sweep` post-backfill
3. `tg-parser link-topics` @ **0.32**
4. Watch 24–48h: links 1962–2942, `anchor_fallback < 10%`, T1 coverage

---

## 7. Implementation summary (code session)

| Item | Status |
|---|---|
| `load_card_embeddings` helper | topic → anchor → missing |
| `link_topics` | batch resolver + `settings.cross_channel_link_threshold` default |
| `_finalize_full_run` | batch resolver |
| `_run_cross_channel_linking` | batch resolver |
| AC-A scheduler | defer Phase 3 in incremental; embed touched + Phase 3 after `run_topic_embedding` |
| AC-C dispatch | `pipeline_dispatch_service` passes settings threshold |

---

## 8. Raw JSON (prod runs)

```json
{
  "generated_at": "2026-07-11T08:33:44Z",
  "coverage": {"total_cards": 2046, "topic_embeddings": 819, "topic_emb_coverage_pct": 40.03},
  "resolve_stats": {
    "anchor_source": {"topic": 0, "anchor_fallback": 0, "missing": 157},
    "topic_with_fallback": {"topic": 800, "anchor_fallback": 1090, "missing": 156}
  },
  "cross_channel": {
    "anchor_emb": {"links_at_threshold": {"0.25": 18970, "0.3": 3121, "0.35": 567, "0.4": 115}},
    "topic_emb": {"links_at_threshold": {"0.25": 27493, "0.3": 5268, "0.35": 1176, "0.4": 326}}
  },
  "same_channel_merge": {
    "anchor_emb": {"0.6": {"total_merge_losers": 9}},
    "topic_emb": {"0.6": {"total_merge_losers": 18}}
  },
  "snapshot_diff_at_0_30": {
    "anchor_emb": {"current_links": 2452, "simulated_links": 3121, "added": 933, "removed": 264},
    "topic_emb": {"current_links": 2452, "simulated_links": 5268, "added": 3779, "removed": 963}
  },
  "current_prod_links": {"count": 2452, "avg_score": 0.329}
}
```

*Full sweep runtime: ~46 min. Fine sweep: ~6 min.*

### Fine sweep JSON (2026-07-11T11:10Z)

```json
{
  "mode": "fine_sweep",
  "links_at_threshold": {
    "0.3": 5266, "0.31": 3794, "0.32": 2807,
    "0.33": 2095, "0.34": 1555, "0.35": 1176
  },
  "recommendation": {
    "watch_band": [1962, 2942],
    "in_band": {"0.32": 2807, "0.33": 2095},
    "closest_to_midband": {"threshold": 0.32, "links": 2807}
  }
}
```
