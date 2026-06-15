# START PROMPT — Fix F11 `semantic_available` precision-blind-spot (D1 measure) + Wave-2 T6 (gated alert)

**Дата:** 2026-06-15 · **Контекст:** follow-up к ревью-сессии [`HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md`](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) (backlog item **D**) + deferred Wave-2 **T6**, метод сохранён в [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4a.

**Goal (одной строкой):** закрыть precision-blind-spot `semantic_available=False` через **observability first** (D1 — измерение, read-only) и в том же касании watchlist-scoring-пути сложить deferred Wave-2 **T6** (gated Prometheus alert на keyword-only долю); **формулу скоринга (D2) НЕ менять** в этом спринте.

> Рабочий режим: коммит / PR — **только** по явному запросу пользователя ([`AGENTS.md`](../../AGENTS.md)). Scope — **только watchlist observability** (counter + alert), без изменения scoring-формулы. `docs/methodology/` — вне workspace.

---

## 1. Почему D1 и T6 батчатся вместе

Оба трогают **один и тот же** code path — `semantic_available`-ветку в `compute_watch_score` и watchlist metrics/alerts surface. PLAN_WAVE2 §4a прямо советует закрыть T6 «когда в следующий раз тронут watchlist-scoring путь (`watchlist_service.py:565`) или metrics/alerts surface (не платить за context-paging дважды)». D1 — ровно это касание. ⇒ батчим: D1 (измерить blind-spot) + T6 (gated alert на ту же метрику). D2 (изменение формулы) — **за рамками**, gated на данных D1 + ADR.

---

## 2. Подтверждённый blind-spot (из handoff §2.6)

[`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) `compute_watch_score` — когда у дока (или интереса) нет эмбеддинга:

```
semantic_available = bool(interest.embedding) and bool(doc_embedding)   # line 565
...
elif semantic_available:
    combined = keyword_weight * keyword + semantic_weight * semantic     # line 571
else:
    combined = keyword                                                   # line 573  ← blind-spot
```

`combined = keyword` может быть **1.0** и взять порог **без semantic-сигнала** (graceful degradation by ADR-0010/0011, но precision-blind-spot). Observed: GLP-1 match `id=14` (kw=1.0, sem=0.0, combined=1.0). Audit: редко (~1/351) — **поэтому сначала меряем**.

---

## 3. Code anchors (VERIFIED 2026-06-15 — перепроверить перед правкой)

| Якорь | Файл | Линия (на 2026-06-15) |
|---|---|---|
| `compute_watch_score` (def) | [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) | ≈ 527 |
| `semantic_available = …` | то же | ≈ 565 |
| `else: combined = keyword` (blind-spot branch) | то же | ≈ 572–573 |
| `WATCHLIST_SCORE` histogram (`tg_watchlist_score`) | [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) | ≈ 233 |
| `WATCHLIST_MATCHES` counter (`tg_watchlist_matches_total`) | то же | ≈ 219 |
| `record_watchlist_match` | то же | ≈ 271 (observe ≈ 286) |
| `record_watchlist_delivery` | то же | ≈ 289 |
| `WatchlistDeliveryErrors` alert (anchor для нового rule) | [`docker/prometheus/alerts.yml`](../../docker/prometheus/alerts.yml) | ≈ 115 |
| BUG-060 «why delivery not score» комментарий | то же | ≈ 90–114 |

ADR-якоря: [`0006`](../adr/0006-karpathy-like-living-kb-principles.md) (#6 observability / #7 graceful), [`0010`](../adr/0010-watchlist-keyword-aggregation.md), [`0011`](../adr/0011-watchlist-backfill-rework.md) (graceful keyword-only — формула by-design).

> ⚠️ Линии приблизительны — **прочитать файлы и подтвердить** перед записью в любые тесты/правки.

---

## 4. Scope

### 4.1 D1 — measure (READ-ONLY, MCP/data)

Квантифицировать через MCP `get_watchlist_matches` / uncapped `dry_run`: **сколько recorded matches имеют `semantic_score = 0.0`, но взяли порог**, по каждому интересу. Установить: это **редко** (audit ~1/351) или **material**.

- Интересы (handoff §5): GLP-1 `9f23fd49-…`, Гиперпролактинемия `cfc94eb9-…` (thr 0.55), Микробиота `9deccefc-…`, Биомаркеры `c4d87f14-…`, mTOR `64ce09c3-…`.
- Read-only: **никаких** прод-мутаций в D1. Если нужен свежий замер — `backfill_watchlist(dry_run=true)` **uncapped** (см. handoff §2.4 — `limit` newest-first занижает).
- Выход D1: таблица per-interest `{keyword_only_matches, total_matches, %}` + вердикт rare/material.

### 4.2 T6 — gated alert (преселектированный Wave-2 метод — **option B**, НЕ переоткрывать)

Метод дословно из PLAN_WAVE2 §4a (option B выбран над A=relabel histogram из-за cardinality):

1. **Dedicated counter** `tg_watchlist_semantic_unavailable_total{reason}`, `reason ∈ {interest_no_embedding, doc_no_embedding}`, инкрементируется в `semantic_available`-ветке (`watchlist_service.py` ≈ 565) — различать причину: `not interest.embedding` vs `not doc_embedding`.
   - Объявить counter в [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) рядом с прочими `tg_watchlist_*`; добавить helper (напр. `record_watchlist_semantic_unavailable(*, reason)`), вызывать из service.
   - **Выбор dedicated counter над relabel `WATCHLIST_SCORE`** — осознанный: relabel histogram = cardinality-инфляция (score-buckets × semantic_available) + миграция dashboard'ов; dedicated counter ниже-кардинальный и прямо gateable.
2. **Gated Prometheus alert** в [`docker/prometheus/alerts.yml`](../../docker/prometheus/alerts.yml) рядом с `WatchlistDeliveryErrors` (≈ 115): ratio `tg_watchlist_semantic_unavailable_total` к total `record_watchlist_match` (= `tg_watchlist_matches_total`); **консервативный** порог (e.g. **>50% keyword-only за 1h**), `for:` достаточный чтобы не пейджить на transient; severity `warning`; iterate. Mirror комментарий-стиль BUG-060-блока (≈ 90–114), указать что это **gated на reason**, в отличие от blended `tg_watchlist_score`.

### 4.3 D2 — gated, OUT of this sprint (unless D1 data warrants)

Изменение `compute_watch_score` так, чтобы отсутствие эмбеддинга **не могло** раздуть `combined` до 1.0 (e.g. cap combined при semantic-unavailable, или требовать semantic для взятия порога). **Меняет scoring для ВСЕХ интересов** → нужен **ADR** (трогает ADR-0010/0011 graceful keyword-only). **НЕ делать вслепую**; только если D1 покажет material-долю.

---

## 5. Acceptance criteria (Definition of Done)

- [ ] **D1:** per-interest таблица keyword-only-matches (sem=0.0, взявшие порог) + вердикт rare/material; read-only, ноль прод-мутаций.
- [ ] **T6 counter:** `tg_watchlist_semantic_unavailable_total{reason}` объявлен в `metrics.py`, инкрементится в `semantic_available`-ветке `watchlist_service.py`, оба reason покрыты.
- [ ] **T6 alert:** новое правило в `docker/prometheus/alerts.yml` рядом с `WatchlistDeliveryErrors`, gated на ratio, консервативный порог, комментарий поясняет gating.
- [ ] Unit-тест: counter инкрементится по правильному `reason` (interest vs doc нет эмбеддинга); существующие watchlist-тесты зелёные.
- [ ] **Scoring-формула НЕ изменена** (D1/T6); `compute_watch_score` combined-логика byte-identical.
- [ ] (Если D1 = material) — записать предложение D2 как **ADR-stub** (`Proposed`), не реализовывать в этом спринте.

---

## 6. Constraints (CRITICAL)

- Scope — **только** watchlist observability (counter + alert + D1 measurement). **Ни одного** изменения scoring-формулы в D1/T6.
- Коммит / PR — только по явному запросу пользователя.
- D1 — **read-only** по данным (dry-run uncapped допустим; никаких `dry_run=false`).
- Не релейблить `WATCHLIST_SCORE` histogram (cardinality — см. §4.2; метод-выбор зафиксирован).
- Не слать уведомления; не менять пороги интересов.
- D2 — **только** после D1-данных и через ADR; не делать в этом спринте.

---

## 7. Verification plan

1. **D1:** запустить per-interest замер (MCP `get_watchlist_matches` + uncapped dry-run), собрать таблицу, классифицировать rare/material.
2. **T6 counter:** unit-тест на оба `reason`; локально прогнать watchlist suite (`tests/test_watchlist_score.py`, `tests/test_watchlist_service.py`).
3. **T6 alert:** `promtool check rules docker/prometheus/alerts.yml` (синтаксис); ревью PromQL-выражения и порога на дешёвый smoke-сценарий (не false-fire на keyword-only при низкой доле).
4. **Регрессия:** подтвердить что `compute_watch_score` combined-результаты не изменились (existing score-тесты green).
5. **Отчёт:** D1-таблица + вердикт, дифф counter+alert, открытый вопрос по D2 (нужен ли ADR).

---

## 8. Ссылки

- [`docs/notes/HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md`](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) — Deliverable 1, backlog item D source.
- [`docs/notes/PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4a — сохранённый deferred T6-метод (option B).
- [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) — `compute_watch_score`, `semantic_available` branch.
- [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) — `record_watchlist_match`, `WATCHLIST_SCORE`, `record_watchlist_delivery`.
- [`docker/prometheus/alerts.yml`](../../docker/prometheus/alerts.yml) — `WatchlistDeliveryErrors` (anchor) + BUG-060 «why delivery not score».
- ADR [`0006`](../adr/0006-karpathy-like-living-kb-principles.md) / [`0010`](../adr/0010-watchlist-keyword-aggregation.md) / [`0011`](../adr/0011-watchlist-backfill-rework.md).
