# PLAN — Wave 2: Dogfood-Quality (internal-quality & Living-KB hygiene track)

> **⚠️ STATUS UPDATE 2026-07-20 — ACCEPTED / IMPLEMENTED (Wave 2 executed).**
> Этот план был реализован: **combo T1 / T3 / T4 / T5 / T7 shipped в `b294b05`** (2026-06-14; closes #39/#40/#41). **T6** (в тексте ниже помечен «deferred») **тоже shipped** позже — `eead91e` (2026-06-18, dedicated semantic-unavailable counter + alert). **Единственный residual — T2 (F5-B Phase 1)**: остаётся `Proposed / GATED` в [ADR-0016](../adr/0016-near-duplicate-dedup.md) как go/no-go по данным Phase 0 (метод в §4 T2 ниже — валиден). Phase-0 наблюдение (S0 2026-07-07) даёт near-dup **intra ≈ 2, cross = 0 за 7д ≪ 5% gate** → при формальной оценке T2 скорее **Reject**.
> **Текущее forward-состояние / что shipped после Wave 2** — см. [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) (Wave 2 закрыт в коде) + июльские handoff'ы (remediation S0–S7, F9 Phase 2–3, Phase-1 watch t2 FINAL, BUG-085 B1/B2). Историю ниже **не переоткрывать как implementation-sprint** — она сохранена как decision-log.
>
> Ниже — исходный planning-текст (2026-06-14), сохранён как есть; snapshot-цифры/HEAD ниже **исторические**.

**Тип документа:** planning plan + decision-log (design-only output Wave 2 planning-сессии 2026-06-14).
**Branch:** `main` (HEAD на момент планирования ~`c0e51e2` — **исторический**; Wave 2 landed в `b294b05`).
**Статус:** **`accepted / implemented`** (T1, T3–T5, T7 shipped `b294b05`; T6 shipped `eead91e`; **T2 = residual gated decision** per ADR-0016). *(исходно `proposed` — supporting-артефакт, питал главный артефакт*
[`START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md)*).*
**Governing brief:** [`START_PROMPT_PLANNING_WAVE2_2026-06-14.md`](START_PROMPT_PLANNING_WAVE2_2026-06-14.md).
**Режим:** docs-only, ноль кода; commit/deploy — только по явному запросу пользователя.

---

## 0. TL;DR (executive)

- **Audience driver = «continue dogfooding» → A1 internal-quality track.** Ни один Decision-Point threshold не достигнут (2A 0/≥3, 2B 0/≥3, 2C 0/≥1 strong ask). Это *само по себе решение* (§4 fork 1): не строить публичные 2A/2B/2C плечи; усиливать internal quality, на которой owner живёт ежедневно.
- **Форма контракта = combo средних/малых задач** (не одна большая фича), по образцу Living-KB A+B+C: **quality-трек (F5-B near-dup) + Bot-UX hygiene-трек (TD-D-01/02/03) + Living-KB freshness-трек (F5-C P2 evolving topic-summaries, #15 item #4 time-based trigger + item #10 per-channel re-summarize metric)**. **Swap vs прошлая версия плана:** gated-score alert (old T6) → **deferred** (non-blocking observability, см. §4); вместо него в combo — **T7 F5-C P2 (#15 #4+#10)**.
- **F5-B первым, не Wave E.** F5-B — натуральное продолжение Волны D, дешевле, есть data-substrate (см. §1 MCP-снимок: 1052 topic-links, 916 keyword-overlaps на 10 каналах одной тематики → near-dup правдоподобен, **причём скорее cross-channel**). Wave E — research-y, signal слабый → parking-lot.
- **F5-B стартует с Phase 0 (observation-only counter, обе оси intra+cross)** — мини-PR, измеряет реальный near-dup rate **по двум осям**; **Phase 1 (фактический dedup) — gated** на данных Phase 0 (порог ≥5% по доминирующей оси; scope intra/cross/both выбирает owner по реальной distribution). Canonical-pick = earliest-by-date + transparency «свёрнуто N» (§4 T2, ADR-0016).
- **Складываем в Wave 2** internal-facing item'ы (TD-D-01/02/03 + F5-C P2 freshness). **Держим deferred** external/A4-facing (F11 HTTP CRUD, webhook 2A ADR-0008, BUG-008 root-cause) **+ gated-score alert** (non-blocking observability — watchlist уже graceful-degradraded в keyword-only, ADR-0010/0011; см. §4 «Отложено»).
- Новый ADR-stub: [`docs/adr/0016-near-duplicate-dedup.md`](../adr/0016-near-duplicate-dedup.md) (`Proposed`).

---

## 1. Wave 1.5 signal-state (gate-проверка — нормативный вход)

### 1.1 Authoritative source — review log

[`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md` §5 + §11](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md):

| Signal pattern | Wave 2 dir | Counter | Threshold | Достигнут? |
|---|---|---:|---:|---|
| AI-ассистент users ставят MCP, GitHub stars | **2A (A4)** | **0** | ≥3 distinct | ❌ нет |
| «а где смотреть подробнее?» / web-view asks | **2B (A5/A6)** | **0** | ≥3 distinct | ❌ нет |
| Реальный team-collaboration ask | **2C (A3)** | **0** | ≥1 strong ask | ❌ нет |
| Никто не растёт, но **owner активно использует** | continue dogfooding | n/a | ongoing | ✅ **активно** |

Review log §11: единственная заполненная строка — baseline (2026-06-06, 0/0/0, `not triggered`). Первый 2-week review (2026-06-20) ещё не наступил. Нет `[wave1.5-dogfood]` записей в `FUTURE_FEATURES`, нет `WAVE1_5_MARKET_SCAN_*`, нет `WAVE1_5_VALIDATION_LOG.md`, нет внешних validator'ов. **Ни один threshold не достигнут.**

### 1.2 Corroboration — read-only MCP снимок (2026-06-14, `user-tg-parser`) — **[ИСТОРИЧЕСКИЙ SNAPSHOT]**

> **[Historical]** Цифры ниже — снимок на 2026-06-14 (момент планирования). Актуальное состояние KB см. live MCP / июльские baseline'ы (S0 `S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`). Оставлено как gate-обоснование того времени.

`get_cross_channel_stats` + `list_channels` (read-only, через guard'нутые read-tools BUG-008):

| Метрика | Baseline (2026-06-06) | Сейчас (2026-06-14) | Δ |
|---|---:|---:|---:|
| Documents | 5 405 | **11 618** | ~2.15× |
| Topics | 401 | **745** | ~1.86× |
| Topic links | 264 | **1 052** | ~3.99× |
| Active channels | — | **10** (все health/longevity ru) | — |
| Keyword overlaps (2+ ch) | — | **916** | — |

Рост ~2× за 8 дней = **сильный «owner активно использует» signal** (§5 row 4). Тематическая монокультура (10 health-каналов, covid-19 в 5 каналах, b12/helicobacter/glp-1 пересечения) + 1052 cross-channel links @ avg-sim 0.33 → **high a-priori вероятность near-duplicate контента** между каналами → подкрепляет приоритет F5-B. Внешнего роста (stars/DMs/asks) — ноль.

**Вывод гейта:** continue dogfooding, internal-quality. Это **не** «нет решения» — это зафиксированное решение per matrix row 4.

---

## 2. Audience-driven отбор кандидатов (линза §2 + signal-state)

| Кандидат | Сегмент | Signal сейчас | Вердикт Wave 2 |
|---|---|---|---|
| **F5-B near-dup dedup** | A1 (owner data-quality) | partial (counter нужен, cross-channel правдоподобнее) | ✅ **IN** — Phase 0 counter (intra+cross); Phase 1 gated |
| **TD-D-01/02/03 Bot UX** | A1/A5 (owner+journalists на bot) | owner-felt friction | ✅ **IN** (hygiene-трек) |
| **F5-C P2 (#15) evolving summaries** | A1 (owner KB-freshness) | KB вырос ~2× → summaries устаревают | ✅ **IN** (freshness-трек T7 = #15 item #4 time-based + item #10 per-channel метрика; строит на shipped F5-C P1) |
| Gated watchlist score alert | A1/A5 (silent-degradation guard) | BUG-060 follow-up | ⏸ **deferred** (non-blocking: watchlist уже graceful keyword-only, ADR-0010/0011; см. §4 «Отложено») |
| Wave E graph retrieval | A1/A2 (Q&A quality) | слабый, нет measurement | ⏸ parking-lot (research-y, 3–5 сессий, дорого) |
| F11 HTTP CRUD | A4 | 0 (2A=0) | ⏸ deferred (gated на 2A) |
| Webhook target (ADR-0008) | A4 | 0 (2A=0) | ⏸ deferred (gated на 2A) |
| S4 multilang tokenizer | A1/A5 | keyword-matching работает на ru | ⏸ parking-lot (нет logged friction) |
| F1 Full (DB prompts) | infra | prerequisite только для prompt-redesign | ⏸ parking-lot (нет такого кандидата) |
| BUG-008 root-cause | A4 ops | mitigation shipped, нет repro | ⏸ deferred (monitor-only) |

**Selected Wave 2 scope (combo):** T1 F5-B Phase 0 (intra+cross, +gated Phase 1 T2) · T3 TD-D-02 · T4 TD-D-01 (rich deterministic) · T5 TD-D-03 · **T7 F5-C P2 (#15 #4+#10) freshness**. **Deferred (parking-lot):** gated-score alert (old T6, non-blocking), Wave E, S4, F1, F11 HTTP CRUD, webhook 2A, BUG-008 root-cause.

---

## 3. Decision-log — 6 стратегических развилок (§4)

> Каждая развилка: выбор + обоснование + отвергнутые альтернативы + ссылка на signal-state (§1).

### Fork 1 — Audience driver
- **Выбор:** **continue dogfooding → A1 internal-quality**.
- **Обоснование:** signal-state 2A=0 / 2B=0 / 2C=0 (§1.1), ни один threshold; owner-active corroborated ростом KB ~2× (§1.2) = matrix row 4. Строить публичный surface без signal = anti-pattern «Web/publicity до signal» (`PRODUCT_STRATEGY §6`).
- **Отвергнуто:** 2A (нет MCP-adoption/stars), 2B (нет web-asks), 2C (нет team-ask). Все — premature commit (R-3 dogfooding risk register).

### Fork 2 — Глубина / форма контракта
- **Выбор:** **combo средних/малых** (3 параллельных мини-трека), не одна большая фича.
- **Обоснование:** прецедент Living-KB (A+B+C в одном контракте) и Wave 1 (product-трек ‖ tech-debt-трек). Каждый трек дёшев (≤2 сессии), низкий bus-factor risk, каждый создаёт data-foundation или убирает owner-felt friction. Большая фича (Wave E / 2B Web) не оправдана при zero external signal.
- **Отвергнуто:** single big feature — scope-creep risk без value «закрыть сегмент», т.к. сегмент (A1) уже закрыт Wave 1; остаётся quality, а не surface.

### Fork 3 — F5-B dedup vs Wave E graph первым
- **Выбор:** **F5-B первым; Wave E → parking-lot.**
- **Обоснование:** F5-B дешевле (~1.5–2 сессии vs 3–5), натуральное продолжение Волны D, имеет data-substrate (§1.2: 10 моно-тематических каналов, 916 keyword-overlaps → near-dup правдоподобен). Wave E signal «слабый» (`PLANNING_NEXT_CONTRACT_PREP §2 Кандидат 3`: нет measurement что flat retrieval недостаточен), graph-density blow-up risk, требует нового threshold-tuning цикла. При текущем bus-factor (solo) cost/value F5-B > Wave E.
- **Отвергнуто:** Wave E first — research-y, высокорисковый, build-and-nobody-uses без product-driver.

### Fork 4 — Складывать ли отложенные tech-item'ы
- **Выбор:** **fold owner-felt internal, keep external + non-blocking observability deferred.**
  - **Fold в Wave 2:** TD-D-01/02/03 (bot UX — owner на bot ежедневно), **F5-C P2 freshness (T7, #15 item #4 time-based trigger + item #10 per-channel re-summarize metric)** (owner-felt: KB вырос ~2× → темы морально устаревают; #10 — дешёвый observability-компаньон к #4, per-channel cost-видимость для тюнинга, marginal ~0, см. §4 T7).
  - **Keep deferred:** gated-score alert (old T6 — **non-blocking**: watchlist уже деградирует gracefully в keyword-only, ADR-0010/0011, ничто не ломается; это monitoring blind-spot, не дефект; ничего от него не зависит — см. §4 «Отложено» с сохранённым методом), F11 HTTP CRUD + webhook 2A (A4-facing, 2A-signal=0), BUG-008 root-cause (mitigation shipped, нет repro → monitor-only через lifecycle-логи).
- **Обоснование:** dogfooding-трек логично тянет за собой то, что owner *чувствует* (bot UX, KB-freshness), и не тянет ни A4-инфраструктуру без signal, ни observability-only item без зависимостей. Прецедент: Wave 1 = product-трек ‖ параллельный tech-debt-трек.
- **Swap-обоснование (T6 → T7, не addition):** при solo bus-factor бюджет combo фиксирован формой контракта; честный обмен — заменить gated-score alert (observability-only, non-blocking) на F5-C P2 (genuinely user-facing freshness, строит на shipped F5-C P1 → низкая marginal-стоимость, karpathy living-loop coherent). Оптимальное время закрыть T6 — когда в следующий раз тронут watchlist-scoring путь (`watchlist_service.py:565`) или metrics/alerts surface (не платить за context-paging дважды), и когда watchlist-quality станет реально нужен non-owner-пользователям (внешние validator'ы Wave 1.5). Дёшево (~0.5 сессии).
- **Отвергнуто:** (a) всё deferred — оставляет latent BUG-004 re-entry (TD-D-02) незакрытым, хотя owner на нём живёт; (b) fold всё включая webhook / gated-alert — тянет A4-инфраструктуру и non-blocking observability без signal/зависимостей, scope-creep при solo bus-factor.

### Fork 5 — Правило взвешивания сигналов
- **Выбор — explicit weighting rule** (lexicographic, при равенстве — следующий критерий):
  1. **Data-readiness** (есть ли метрика/данные обосновать scope) — высший вес: запускать сначала то, где можем измерить (→ F5-B Phase 0 counter перед Phase 1; gated-alert опирается на `semantic_available`).
  2. **Product-friction (owner-felt)** — что реально мешает owner'у в daily use (bot UX TD-D, false F11 alerts).
  3. **Karpathy-like coherence** (ADR-0006 7-checklist) — близость к натуральному продолжению Living-KB.
  4. **Cost/risk + bus-factor** — tie-breaker (solo → дешевле/обратимее лучше).
  - **Override-правило:** external product-signal (stars/DM/ask) — отсутствует → публичные surface'ы (2A/2B/2C) де-приоритизированы независимо от их «крутости». «Internal-quality, пока owner-active & no external growth» (`PLANNING_NEXT_CONTRACT_PREP §4 Q1` + matrix row 4).
- **Отвергнуто:** product-friction > data-readiness (соблазн чинить «больно» вслепую) — отвергнут: чинить без измерения = риск over/under-engineering (F5-B threshold нельзя угадать).

### Fork 6 — Combo vs single + триггер старта реализации
- **Выбор:** **combo** (Fork 2); **start-триггер = этот PLAN закрыт + главный START_PROMPT написан** (signal-threshold НЕ требуется — это internal quality, не gated на внешнем signal).
  - Внутри combo один gate: **F5-B Phase 1 execution gated** на Phase 0 counter (≥7 дней данных по обеим осям; near-dup rate ≥5% по **доминирующей** оси `dimension` → строить Phase 1, scope intra/cross/both выбирает owner из реальной distribution; иначе — зафиксировать «rate низкий по обеим осям, Phase 1 не нужен», counter остаётся как permanent observability).
- **Обоснование:** internal-quality треки самодостаточны (нет внешней зависимости); единственная data-gated развилка — масштаб F5-B, и она решается Phase-0-данными, а не угадыванием.
- **Отвергнуто:** ждать signal-threshold для старта — нерелевантно для internal track; временна́я отметка — произвольна.

---

## 4. Method-selection per task (§5 — ядро) + karpathy-like 7-checklist

> Для каждой задачи: ≥2 подхода → выбор через двойной фильтр (audience-линза + ADR-0006 7-checklist; cost/risk + bus-factor tie-breaker) → rationale + контракты/ADR + риски. Эти методы **дословно** переходят в главный START_PROMPT.

### T1 — F5-B Phase 0: near-duplicate observation-only counter

**Подходы:**
- **A. Pre-pipeline filter (observe before processing).** Считать near-dup до processing. ❌ меняет hot-path до того, как знаем rate; риск регрессии ingestion.
- **B. Post-processing observation против sliding-window last-N, pgvector `<=>` cosine, observation-only (НЕ блокирует), по двум осям — intra-channel + cross-channel.** ✅
- **C. Offline batch-скрипт (all-vs-all).** ❌ не living-loop, O(N²), даёт snapshot, не поток.

**Выбор: B (две оси).** Хук после embedding'а нового `ProcessedDocument`; сравнить embedding через pgvector `<=>` с last-N (N≈50) embeddings **(a) того же `channel_id` (dimension=intra)** и **(b) недавних документов sibling-каналов того же workspace/темы (dimension=cross)**; если max cosine ≥ observe-threshold (0.92) → `inc()` нового counter `tg_dedup_near_duplicates_detected_total{channel_id, method="embedding_cosine", dimension="intra"|"cross"}` + histogram similarity + structlog `near_duplicate_observed` (оба `source_ref` + similarity + `dimension`). **Ничего не скрывает, ничего не мутирует** (включая cross-channel путь — observation-only в Phase 0).

**Почему обе оси:** MCP-снимок (§1.2: 10 моно-тематических каналов, covid-19 в 5 каналах, 916 keyword-overlap'ов на 2+ каналах, 1052 cross-channel link) → felt-дубликация owner'а **скорее cross-channel** (один материал репостится между каналами). Измерять только intra = риск измерить не ту ось и выдать ложный «dedup не нужен» вердикт гейта. Даёт **data-readiness** (Fork 5 #1) для решения Phase 1 без риска. Karpathy: cheap retrieval (dot-product, без LLM), idempotent (observe-only, повтор не плодит state), graceful (embedding отсутствует → skip). Cost ~0.5–0.75 сессии (cross-window добавляет sibling-channel выборку).

**Контракты/ADR:** ADR-0016 (`Proposed`), ADR-0006 (#3/#6/#7). Не трогает `processed_document.schema.json` (только метрика). pgvector index `idx_pd_channel_content_hash` — соседство; near-dup использует embeddings table.

**7-checklist:** 1 нет новой сущности (метрика) · 2 оба `source_ref` + `dimension` в логе · 3 ✅ embedding cosine, no LLM (intra+cross) · 4 ✅ observe-only идемпотентен · 5 ✅ hook после embedding в incremental tick · 6 ✅ counter `{dimension}` + histogram similarity · 7 ✅ embedding down → skip.

**Риски:** (a) sliding-window-N миссит дальние дубли — accept (observation, не precision-critical); (b) cross-window состав sibling-каналов (workspace vs тема) — фиксируем выбор в impl, остаётся observation-only; (c) cross-channel cosine может ловить «независимое освещение» как дубль — accept в Phase 0 (меряем rate, UX-граница решается в Phase 1 по данным).

---

### T2 — F5-B Phase 1: near-duplicate dedup (GATED на T1 данных)

> **GATE:** строить ТОЛЬКО если T1 counter за ≥7 дней показал near-dup rate **≥5% по доминирующей оси** (`dimension`); scope Phase 1 (intra / cross / both) выбирает owner из реальной distribution. Иначе — «rate низкий по обеим осям, Phase 1 не нужен».

**Подходы:**
- **A. Pre-pipeline hard filter** (skip ingest near-dup). ❌ теряет provenance, необратимо, ломает «оба source_ref сохранены».
- **B. Post-processing consolidation: append-only `near_duplicate_links(source_ref_a, source_ref_b, similarity, method, dimension, detected_at)` + soft-hide flag на более позднем документе + transparency «свёрнуто N».** ✅

**Выбор: B (если gate открыт).** ANN: pgvector `<=>` с index, sliding-window last-N (bound O(N²)). Soft-hide (не delete) → reversible, оба ref в графе. Cascade на F11: near-dup B уже-matched A → skip B как duplicate evidence (фиксируется в link).

**Canonical-pick = A (earliest by published date):** keep самый ранний документ, soft-hide более поздний дубль(и); детерминистический tie-break при равных timestamp'ах по `source_ref` / `message_id` (требование идемпотентности, ADR-0006 #4). Cross-channel: «earliest = original source, later = reposts». **Отвергнуто:** B latest (derivative, теряет first-seen provenance), C richest-content (fuzzy/недетерминистичен), D priority-channel (нужен новый concept channel-priority — out of scope), E engagement (несравним между каналами, metadata может отсутствовать). **OPTIONAL future «A + superset guard»** (предпочесть более позднюю копию только если она явный текстовый superset) — намеренно отложен out of MVP ради детерминизма.

**Transparency (user-facing, нормативно):** dedup **не** скрывает молча — surface показывает affordance «свёрнуто N» с разворотом; в развёрнутом виде collapsed-копии **отсортированы по дате** и **подписаны source-каналом**. Reversible soft-hide + «свёрнуто N» — это то, что де-рискует выбор canonical-pick (ошибка обратима и видима).

**Почему:** provenance (#2) + graceful (#7) + reversibility + transparency. Hard-filter (A) необратим, нарушает Living-KB; earliest-canonical детерминистичен (в отличие от C/E) и сохраняет first-seen provenance (в отличие от B).

**Контракты/ADR:** ADR-0016 (созревает Draft→Accepted в impl-сессии: append-only `near_duplicate_links` + soft-hide + canonical=earliest + «свёрнуто N» transparency), новая таблица + Alembic + Pydantic + JSON-schema `near_duplicate_link.schema.json` (ADR-0006 #1: columns, не metadata dict).

**7-checklist:** 1 ✅ новая persistent таблица + schema (+`dimension`) · 2 ✅ оба ref + similarity · 3 ✅ embedding, no LLM · 4 ✅ UPSERT `ON CONFLICT (source_ref_a, source_ref_b) DO NOTHING`, append-only; canonical-pick детерминистичен · 5 ✅ hook после embedding · 6 ✅ `tg_dedup_near_duplicates_*` + soft-hide counter + «свёрнуто N» affordance · 7 ✅ embedding down → fallback exact-hash (existing); soft-hide reversible.

**Риски:** (a) false-positive «похожие новости из 2 каналов» vs «один re-post» — mitigate threshold из Phase 0 distribution + reversible soft-hide + видимый «свёрнуто N» (owner может развернуть); (b) cascade на watchlist/digest — explicit test; (c) gate может НЕ открыться (rate низкий) → Phase 1 не строится, T1 counter остаётся.

---

### T3 — TD-D-02: pagination_pending coverage (latent BUG-004 re-entry)

**Подходы:**
- **A. Per-tool bespoke pagination** на каждый list-tool. ❌ дублирование, drift.
- **B. Shared контракт-helper применён ко всем paginated read-tools симметрично (bot + mcp_server).** ✅

**Выбор: B.** Распространить `pagination_pending` контракт (сейчас только `_exec_list_topics` `tg_parser/bot/tools.py:1973`) на `_exec_list_channels` (`:2040`), `_exec_list_digests` (`:3637`), `_exec_list_watchlists` (`:4155`), `list_users`, paginated `get_cross_channel_stats`; симметрично в `tg_parser/mcp_server.py`. Contract-test: каждый paginated read-tool при `has_more=True` возвращает корректный `pagination_pending` shape.

**Почему:** убирает latent re-entry BUG-004 (`BUG_LOG.md:3818`) на всех surface'ах; DRY; owner-felt (A1/A5 на bot). Cost ~1 сессия.

**Контракты/ADR:** ADR-0006 (#4 идемпотентный replay), без новой схемы. Прецедент Session D `PaginationFlow`.

**7-checklist:** 1 n/a (поведение) · 2 args сохраняют фильтр без изменений · 3 n/a · 4 ✅ детерминированный replay stashed-query · 5 n/a · 6 опц. counter pagination-replay · 7 ✅ non-match → D-4 default.

**Риски:** разные list-tool'ы имеют разный args-shape → helper должен быть generic по `{tool_name, args, total, offset, limit}`; покрыть per-tool тестом.

---

### T4 — TD-D-01: renderer unification (page1 vs page2+ visual jump)

**Подходы:**
- **A. Strengthen prompt contract** (LLM рендерит page 1 консистентно). ❌ LLM-nondeterminism, fragile, требует prompt-version babysitting.
- **4a. Promote `_format_paginated_list` (`handlers.py:1374`) на page 1 как есть** — детерминизм + консистентность, но page 1 беднее текущего LLM-render'а. ⚠️ accept-беднее.
- **4b. Promote `_format_paginated_list` на page 1 + обогатить сам детерминистический форматтер** (headers / emphasis / структура) так, чтобы результат был И консистентен между страницами, И хорошо отформатирован. ✅

**Выбор: 4b (rich deterministic template).** Page 1 рендерится тем же детерминистом, что page 2+ → нет visual jump, numbering `n` консистентен (`offset+idx+1`), независимо от LLM; **и** форматтер обогащается (headers/emphasis/structure), чтобы не терять читабельность ради консистентности. Подход остаётся **детерминистическим** (не LLM-prompt), просто с богатым шаблоном. (Сопряжено с T3 — общий pagination-рендер-путь.)

**Почему:** karpathy observability/детерминизм > LLM free-form, но без регресса качества рендера — обогащённый шаблон снимает прежний trade-off «беднее ради консистентности». Убирает numbering-restart баг. Cost ~0.5–0.75 сессии (если делать вместе с T3; обогащение шаблона добавляет немного).

**Контракты/ADR:** ADR-0006 (#6 предсказуемость). `prompts/bot.yaml` — возможно убрать/ослабить free-form list-render инструкцию → **prompt-version bump** (bot.yaml write-surface) **обязателен**.

**7-checklist:** в основном n/a (рендер); #6 ✅ детерминированный И хорошо отформатированный вывод.

**Риски:** обогащённый шаблон не должен дрейфовать от page-2+ формата — единый рендер-путь для page 1 и page 2+ (один форматтер, не два) гарантирует identical-формат; snapshot-тест page1==page2 шаблон.

---

### T5 — TD-D-03: `_format_tool_result` fallback + contract-test

**Подходы:**
- **A. Synthesize fallback** из `channel_id`/`id`/`status` вместо слабого `"✅ Готово"`. 
- **B. A + contract-test что ВСЕ write-tools возвращают non-empty `message`.** ✅

**Выбор: B (оба).** `_format_tool_result` (`handlers.py:1428`) синтезирует информативный fallback; + contract-test enumerating все write-tools → assert non-empty `message` (ловит новый write-tool без `message` на CI, а не в проде).

**Почему:** belt-and-suspenders; превращает latent silent-degradation в compile/CI-time guard. Cost ~0.3 сессии.

**Контракты/ADR:** ADR-0006 (#6). Без схемы.

**7-checklist:** #6 ✅ (observability fallback) · #7 ✅ (graceful: новый tool не «молчит»).

**Риски:** низкие; contract-test должен импортировать canonical список write-tools (переиспользовать frozenset/декларации из `bot/tools.py`).

---

### T7 — F5-C P2: evolving topic-summaries freshness (#15 item #4 + item #10)

> **Selected (замещает old T6 в combo).** F5-C P1 (MVP, PR #14, tag `f5c-mvp-2026-04-26`) уже shipped: counter-driven trigger `new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N` (default 5), append-only `topic_card_versions`, MCP/CLI surface. T7 — Phase 2 freshness-слой поверх этой инфраструктуры. **Scope = option B: issue #15 item #4 (time-based trigger) + item #10 (per-channel re-summarize metric breakdown)** — #10 как дешёвый observability-компаньон к #4.

**Pinned MVP scope (issue #15 item #4 — Time-based trigger; item #10 — per-channel metric).** Issue #15 — tracking-issue с 10 backlog-пунктами; для combo-формы (один medium-task) пиннятся два самых **user-facing × дешёвых × freshness** среза: **(#4) time-based re-summarize trigger** + **(#10) per-channel re-summarize metric breakdown** (cheap observability companion). Точная граница phase-2 — per issue #15 (остальные 8 пунктов: TTL, diff-API, F6 topic-digest, Bot-tools, type-promotion, topic-dedup, item-removal, HTTP API — остаются в #15-backlog, **OUT** этого спринта). Обоснование выбора среза #4: «темы с `< RESUMMARIZE_TRIGGER_N` новых items, но summary старше N дней — морально устаревают» (issue #15 item #4) — прямо отвечает на «fresher living-topic summaries», а KB вырос ~2× (745 топиков) → low-volume темы реально стареют без триггера. Обоснование добавления #10: time-based триггер **повышает** объём/стоимость re-summarize → owner'у нужна per-channel cost-видимость (`tg_resummarize_tokens_total` / `tg_resummarize_total` by channel), чтобы тюнить `RESUMMARIZE_MAX_AGE_DAYS`; #10 — натуральный observability-компаньон к #4, закрывает karpathy observability-loop (ADR-0006 #6: включить knob → наблюдать его per-channel стоимость). Marginal cost ~0 — label `channel_id` уже зарезервирован в `tg_resummarize_total`, сегодня всегда `"-"`.

**Подходы (#4 — time-based trigger):**
- **A. Расширить `list_resummarize_candidates` вторым предикатом** (OR `last_summarized_at < NOW() - INTERVAL 'RESUMMARIZE_MAX_AGE_DAYS days' AND new_items_since_last_summary > 0`), gated на новом env `RESUMMARIZE_MAX_AGE_DAYS` (0/None = disabled → MVP-поведение bit-for-bit). ✅
- **B. Отдельный scheduler-pass / CRON, сканирующий stale-темы** независимо от per-channel tick. ❌ дублирует cap-логику, новый scheduler-surface, ломает single-hook living-loop.
- **C. Глобально понизить `RESUMMARIZE_TRIGGER_N`.** ❌ грубо, поднимает cost по всем темам, не адресует time-staleness low-volume тем.

**Подходы (#10 — per-channel re-summarize metric):**
- **A′. Пробросить реальный `channel_id` в уже-зарезервированный label `tg_resummarize_total{channel_id}`** (сегодня всегда `"-"`): передать канал в `record_resummarize_outcome` (через `card.sources[0]` или явный аргумент), fallback `"-"` когда канал неизвестен. ✅
- **B′. Отдельная новая метрика per-channel.** ❌ дублирует уже-зарезервированный label, лишняя сущность, marginal cost > 0.
- **C′. Оставить `channel_id="-"` (status-quo).** ❌ нет per-channel cost-видимости → нечем тюнить `RESUMMARIZE_MAX_AGE_DAYS`, observability-loop #4 не закрыт.

**Выбор #4: A (time-based как дополнение counter-триггеру, не замена).** Расширяем существующий candidate-query (`topic_card_repo.list_resummarize_candidates` `tg_parser/storage/sqlalchemy/topic_card_repo.py:200`, port `storage/ports.py:671`) вторым предикатом; **сохраняем `AND new_items_since_last_summary > 0`** → запрос по-прежнему едет на partial-index `idx_topic_cards_resummarize_candidates (WHERE new_items_since_last_summary > 0)` → cost остаётся O(active topics с pending items), без full-scan. Re-use существующего triple-cap (`MAX_PER_TICK`/`MAX_DURATION_S`/`MAX_TOKENS_PER_TICK`), advisory-lock и `commit_resummary`-пути в `ResummarizationService.run_for_channel` (`tg_parser/services/resummarization_service.py:101`, threshold-выбор `:124`, candidate-выборка `:135`). Issue #15 non-goal явно: time-based — дополнение, не замена counter-контракта.

**Выбор #10: A′ (real `channel_id` в зарезервированном label).** `tg_resummarize_total` (`tg_parser/api/metrics.py:153`, label `channel_id` `:157`, «always "-"»-комментарий `:160`–`:164`) уже несёт label `channel_id`, но `record_resummarize_outcome` (`tg_parser/api/metrics.py:272`) хардкодит `channel_id="-"` (`:287`). Канал доступен в service: `card.sources[0]` уже используется на happy-path (`tg_parser/services/resummarization_service.py:402`) → передать его в `record_resummarize_outcome` (новый kwarg `channel_id`, default `"-"`), на путях без card (`locked`/`no_card`/`no_bundle`) — fallback `"-"`. **Rationale:** #10 — натуральный observability-компаньон к #4: включение time-based триггера повышает re-summarize volume/cost → per-channel breakdown (`tg_resummarize_tokens_total` / `tg_resummarize_total` by channel) даёт owner'у видимость, чтобы тюнить `RESUMMARIZE_MAX_AGE_DAYS`; закрывает karpathy observability-loop (ADR-0006 #6: включить knob → наблюдать его per-channel стоимость). **Marginal cost ~0** — label уже зарезервирован, миграции метрик не требуется.

**Почему (audience-линза + karpathy):** genuinely user-facing (свежие living-topic summaries — A1 owner-value, KB ~2×), строит на shipped F5-C P1 (низкая marginal-стоимость, karpathy living-loop coherent), в отличие от Wave E graph Q&A (research-y, слабый signal, 3–5 сессий, ломает combo-of-medium форму контракта). Cross-channel dedup proper недоступен сейчас (Phase 1 gated на ≥7 дней Phase 0). Cost ~0.5–0.75 сессии (#10 добавляет ~0 marginal — label `channel_id` уже зарезервирован, нужна лишь правка `record_resummarize_outcome` + тест; оценка остаётся ~0.5–0.75).

**7-checklist:** 1 нет новой сущности (re-use `topic_cards.last_summarized_at`/`new_items_since_last_summary`; только новый env; #10 — re-use уже-зарезервированного label, не новая метрика) · 2 ✅ provenance через уже-существующий version-snapshot в `commit_resummary`-пути · 3 ✅ candidate-select — SQL-предикат, no LLM на отборе · 4 ✅ idempotent: после re-summary counter=0 + `last_summarized_at` bumped → не перезапускается следующий tick; `new_items > 0` guard не трогает unchanged-темы; #10 — чистый label-инкремент, идемпотентность не задета · 5 ✅ тот же scheduler-hook (`scheduler_service.py:272` `run_resummarize_for_channel`), без нового surface · 6 ✅ **#10 — реальный `channel_id` в `tg_resummarize_total{channel_id, outcome}`** (сегодня `"-"`) → per-channel cost-breakdown (вместе с `tg_resummarize_tokens_total`) для тюнинга `RESUMMARIZE_MAX_AGE_DAYS`; опц. label trigger=counter|age · 7 ✅ env default disabled → bit-for-bit MVP; LLM down → existing `llm_error` путь; #10 — канал неизвестен → fallback `"-"` (graceful).

**Контракты/ADR:** ADR-0006 (#5 living-loop / #6 observability). **Нет новой JSON-schema** (нет новой persistent-сущности — только новый env + query-предикат; #10 — re-use существующей `tg_resummarize_total`, label `channel_id` уже объявлен). Новый env `RESUMMARIZE_MAX_AGE_DAYS` (default 0/disabled, консервативный prod-старт ~14 дней — согласован со stale-detector issue #15 «>14 days»). `prompts/resummarize.yaml` — без version-bump (промпт re-summarize не меняется, меняется только триггер отбора). #10-якоря: `tg_resummarize_total` `tg_parser/api/metrics.py:153`, `record_resummarize_outcome` `:272` (хардкод `channel_id="-"` `:287`), источник канала `card.sources[0]` `tg_parser/services/resummarization_service.py:402`.

**Риски:** (a) на первом enable много stale-тем фитят разом → cost-spike — mitigate существующим triple-cap + консервативный default age + fair-scheduling `ORDER BY new_items DESC, updated_at DESC`; (b) предикат должен оставаться под partial-index (сохранить `new_items > 0`) — иначе full-scan; покрыть explain-проверкой; (c) граница phase-2 шире одного пункта — зафиксировано «exact phase-2 boundary per issue #15 (item #4 + #10)», остальные 8 пунктов остаются в #15-backlog; (d) **#10 cardinality**: `channel_id` поднимает кардинальность `tg_resummarize_total` с 1 до N серий по `channel_id` — фиксированный/ограниченный набор каналов (10 active) → **приемлемая cardinality** (mitigation); fallback `"-"` для неизвестного канала не плодит безграничных серий.

---

## 4a. Отложено (deferred — метод сохранён для будущего pickup)

### T6 — Gated watchlist score alert (BUG-060 follow-up) — **✅ SHIPPED `eead91e` (2026-06-18)**

> **⚠️ UPDATE 2026-07-20:** T6 больше **не** deferred — он **shipped** в `eead91e` (2026-06-18) как выбранный вариант **B** (dedicated counter `tg_watchlist_semantic_unavailable_total{reason}` + alert `WatchlistSemanticUnavailableHigh`), ровно по методу ниже. См. [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md` §1.1](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md). Текст ниже сохранён как исходный method-record (historical framing «deferred» относится к планированию 2026-06-14).

> **[Historical framing] Перенесён из SELECTED в deferred (swap T6 → T7, см. §3 Fork 4).** **Non-blocking:** watchlist-matching уже деградирует gracefully в keyword-only (`combined=1.0`, ADR-0010/0011) — ничто не ломается, если alert не построен; это monitoring blind-spot, не дефект; ничего от него не зависит. **Оптимальное время закрыть:** когда в следующий раз тронут watchlist-scoring путь (`tg_parser/services/watchlist_service.py:565`) или metrics/alerts surface (избежать context-paging дважды), и когда watchlist-quality станет реально нужен non-owner-пользователям (внешние validator'ы Wave 1.5). Дёшево (~0.5 сессии). **Метод (сохранён ниже, не переоткрывать при pickup):**

**Подходы:**
- **A. Добавить label `semantic_available` к histogram `WATCHLIST_SCORE` (`metrics.py:196`)** + gated Prometheus rule.
- **B. Dedicated counter `tg_watchlist_semantic_unavailable_total{reason}`** (reason ∈ {interest_no_embedding, doc_no_embedding}) + alert на ratio к `record_watchlist_match` total.** ✅

**Выбор: B (расхождение с буквой `WAVE1_TECH_DEBT §C`, обоснованное).** §C предлагает label на `WATCHLIST_SCORE`; но релейблинг histogram'а = cardinality-инфляция (score-buckets × semantic_available) + миграция dashboard'ов. Dedicated counter ниже-кардинальный, **прямо** gateable, не требует трогать score-path-семантику (которая by-design `combined=1.0` keyword-only, ADR-0010/0011). `semantic_available` уже вычисляется в `watchlist_service.py:565` — нужно только инкрементить counter в той ветке. Alert в `docker/prometheus/alerts.yml` (рядом с `WatchlistDeliveryErrors`); threshold (ratio %) консервативно (e.g. >50% keyword-only за 1h), iterate. ADR-0006 #6/#7. Расхождение с §C — осознанный method-выбор. Cost ~0.5 сессии.

---

## 5. Sequencing & cost

| # | Задача | Трек | Cost (сессии) | Зависимость / gate |
|---|---|---|---:|---|
| 1 | T1 F5-B Phase 0 counter (intra+cross) | quality | ~0.5–0.75 | — (первый, data-gathering) |
| 2 | T7 F5-C P2 freshness (#15 #4 time-based + #10 per-channel metric) | freshness | ~0.5–0.75 | независим; строит на shipped F5-C P1; #10 = ~0 marginal |
| 3 | T3+T4 pagination coverage + rich-deterministic renderer | bot-UX | ~1.0–1.25 | T3/T4 сопряжены (общий рендер-путь); T4 = rich-шаблон |
| 4 | T5 fallback + contract-test | bot-UX | ~0.3 | независим |
| 5 | T2 F5-B Phase 1 dedup | quality | ~1.5–2 | **GATED** на T1 (≥7д, rate ≥5% по доминирующей оси) |

**Итого Wave 2 (без gated T2):** ~2.3–3.05 сессии (T1 0.5–0.75 + T7 0.5–0.75 + T3+T4 1.0–1.25 + T5 0.3). **С T2 (если gate открыт):** ~3.8–5.05 сессии (+T2 1.5–2.0). **#10 (per-channel метрика) не меняет итог** — marginal ~0 (label `channel_id` уже зарезервирован в `tg_resummarize_total`), T7 остаётся ~0.5–0.75.
*(Swap-дельта vs прошлая версия: T6 ~0.5 → T7 ~0.5–0.75; T1 +cross-window ~+0.25; T4 rich-шаблон ~+0.25; T7 +#10 ~+0.)*
**Рекомендуемый порядок:** T1 → (T7 ‖ T3+T4 ‖ T5) → собрать Phase-0 данные ≥7д (обе оси) → решение по T2.

> **⚠️ UPDATE 2026-07-20 (executed):** T1 + T3 + T4 + T5 + T7 **shipped `b294b05`** (2026-06-14). **T6 gated-score alert также shipped** — `eead91e` (2026-06-18), т.е. больше не «deferred» (см. §4a-баннер). **T2 F5-B Phase 1 — единственный residual**, остаётся GATED (ADR-0016): Phase-0 наблюдение (S0 2026-07-07) → intra≈2 / cross=0 за 7д ≪ 5% → при оценке скорее **Reject**. Форвард-состояние: [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md).

**Deferred (parking-lot, метод в §4a):** ~~gated-score alert (old T6)~~ (**shipped `eead91e`**), Wave E graph, S4, F1, F11 HTTP CRUD, webhook 2A, BUG-008 root-cause (server-side H1 later shipped `5165875`).

---

## 6. ROADMAP cross-link note (✅ ПРИМЕНЕНО в ROADMAP 2026-07-20 — historical proposal, не применять повторно)

> **[HISTORICAL]** Предложение ниже было применено в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) (секция «2026-06-14 — Next contract: Wave 2», ныне помеченная **CLOSED**). Оставлено для истории; **не применять снова**.

Предлагалось заменить в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) секцию `## Next contract — TBD` на:

```markdown
## 2026-06-14 — Next contract: Wave 2 Dogfood-Quality (internal-quality track)

Decision Point (Wave 1.5 signal-state 2A/2B/2C = 0/0/0; owner-active dogfooding,
KB grew ~2× since baseline) → **continue dogfooding → A1 internal-quality**, не
публичные 2A/2B/2C плечи. Контракт = combo: F5-B near-dup dedup (Phase 0 counter
intra+cross + gated Phase 1, canonical=earliest + «свёрнуто N» transparency), Bot UX
hygiene (TD-D-01/02/03, rich-deterministic renderer), F5-C P2 evolving topic-summaries
freshness (#15 item #4 time-based trigger + item #10 per-channel re-summarize metric).
Wave E graph / F11 HTTP CRUD / webhook 2A /
gated-score alert → parking-lot (нет signal / non-blocking). Планировочные артефакты:
PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md +
START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md + ADR-0016 (Proposed).
```

Также (опц.) обновить Волну D: F5-B помечен «в работе (Wave 2 Phase 0/1)»; Wave C / F5-C — «P2 freshness в работе (Wave 2 T7, #15 item #4 time-based + item #10 per-channel metric)».

---

## 7. Связанные артефакты

- Главный: [`START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md)
- ADR-stub: [`docs/adr/0016-near-duplicate-dedup.md`](../adr/0016-near-duplicate-dedup.md)
- Гейт: [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md)
- Стратегия: [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)
- Инвариант: [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md)
- Backlog: [`BUG_LOG.md`](BUG_LOG.md) (TD-D-01/02/03 #39–41, BUG-060, BUG-008), [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) §C, GH issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) (F5-C P2 backlog, T7 source — item #4 time-based + item #10 per-channel metric)
- F5-C P1 foundation: `tg_parser/services/resummarization_service.py`, `tg_parser/storage/sqlalchemy/topic_card_repo.py` (`list_resummarize_candidates`), `prompts/resummarize.yaml`, MCP `get_topic_versions`/`force_resummarize`
- Брифинг: [`START_PROMPT_PLANNING_WAVE2_2026-06-14.md`](START_PROMPT_PLANNING_WAVE2_2026-06-14.md)
