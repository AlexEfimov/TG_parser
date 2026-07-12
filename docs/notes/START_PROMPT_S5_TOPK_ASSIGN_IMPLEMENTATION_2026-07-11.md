# START PROMPT — S5 **implementation**: Top-k assign (F-10 / O-5)

**Дата:** 2026-07-11 · **Для:** implementation-сессии (отдельное окно).  
**Planning closed:** [`S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md`](S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md).

---

## Decision (from simulation)

| Item | Value |
|---|---|
| Formula | **`topk_denom`**: `score = weighted_hits / min(n, K)` |
| Default aggregation | `"topk_denom"` (env value; **не** watchlist `"topk"`) |
| K | 3 |
| Rollback | `topicization_assign_keyword_aggregation=mean` → byte-identical текущему |
| Threshold | **keep 0.10** (`topicization_supporting_min_score`) |
| Scope | shared `_compute_match_score` + `_find_supporting_items_programmatic` |

**Rejected:** `phrase_topk` (хуже mean), `max` (runaway winner-shift), отдельный path «только assign».

---

## Files to change

| File | Change |
|---|---|
| `tg_parser/processing/topicization.py` | `_aggregate_assign_score(hits, n, *, aggregation, topk)` wrapper; wire into `_compute_match_score` |
| `tg_parser/config/settings.py` | `topicization_assign_keyword_aggregation: str = "topk_denom"`, `topicization_assign_keyword_topk: int = 3` |
| `.env.example` | document both settings + rollback |
| `tests/test_incremental_topicization.py` | mean regression + topk cases (K=3, rich vs poor vocab, n≤3 no-op) |

Pattern reference: `tg_parser/services/watchlist_service.py::_aggregate_keyword_score` (ADR-0010) — **не копировать `"topk"` mode**; assign использует `topk_denom` (`hits / min(n, K)`), watchlist `"topk"` = `min(hits, K) / K`.

---

## Acceptance criteria

- [ ] `mean` mode = старое поведение (existing `_compute_match_score` tests pass unchanged)
- [ ] `topk` default; K=3; weak-weight preserved
- [ ] n≤3 topics: assign decisions byte-identical to mean (algebraic invariant)
- [ ] `_find_supporting_items_programmatic` uses same helper (no divergent scoring)
- [ ] `.env.example` documented; rollback knob tested
- [ ] Post-deploy smoke: `run_incremental_topicization_for_uncovered(..., assign_only=True)` на одном канале — 0 LLM tokens
- [ ] 24–48h watch: assign logs, `llm_tokens{stage=topicization_discover}`, `tg_channel_processed_coverage_ratio` ≥ S0 baseline, winner-shift qualitatively stable

---

## Deploy

- Branch: `fix/S5-topk-assign`
- **Отдельный PR/деплой** (WORKFLOW §3); **без** S6
- Rollback: env `topicization_assign_keyword_aggregation=mean` (no redeploy)

---

## Post-deploy watch band

| Metric | Baseline (mean) | Target (topk) | Stop |
|---|---|---|---|
| T1 assign rate | 83.11% | ~95–98% | < 80% or > 99% sustained |
| Discover proxy (sim) | 16.89% unassigned | ~2–5% | > 10% without coverage gain |
| Winner-change | — | watch qualitatively | material off-topic in bundles |
| T1 coverage | S0 §2 обл.5 | ≥ baseline | any drop → investigate |

---

## Out of scope

- §6.5 embedding-assign, S6 merge-hardening, S7 RAG pooling
- `docs/contracts/**`, DB migrations
- `MIN_SUPPORTING_SCORE` recalibration
- `murashko_med` re-enable (channel disabled)
