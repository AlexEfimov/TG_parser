# DRAFT — Next contract (post-Wave-2): track-selection brief

> **DRAFT — for Wave 1.5 review decision on ~2026-06-18..06-20.** Это **не** контракт и **не** START_PROMPT — это decision-input: standalone черновик, из которого предстоящий Wave 1.5 review (2026-06-20) выбирает трек, вместо того чтобы стартовать с нуля. Ничего здесь **не** применяется к ROADMAP / существующим планам без явного go-ahead.

**Тип документа:** planning draft / track-selection brief (docs-only).
**Branch:** `main`. **Режим:** docs-only, ноль кода/тестов; commit/PR — **только** по явному запросу пользователя ([`AGENTS.md`](../../AGENTS.md)).
**Goal (одной строкой):** зафиксировать post-Wave-2 состояние (что shipped / date-gated / deferred) и предложить 2–3 готовых к выбору трека (mini-contracts) + рекомендованный default с явными блокерами, чтобы Wave 1.5 review мог решить, а не планировать.

---

## 0. TL;DR (executive)

- **Wave-2 Dogfood-Quality combo фактически закрыт в коде.** Implementation-волна (`b294b05`, 2026-06-14: T1 F5-B Phase 0 + T3/T4/T5 bot-UX + T7 F5-C P2) и watchlist-quality хвост этой сессии (`eead91e` T6, `8197817` Handoff C, `8f69129` Handoff B, `39edfcf` doc-hygiene, все 2026-06-18) — landed. Этот черновик закоммичен (`221fab4`); после него landed **BUG-008 H1-fix** (`5165875`) + **Grafana test realign** (`8e943d5`) → полный `TEST_POSTGRES=1` suite зелёный (8 Grafana-падений были stale-test drift, не регрессия). Остаток — **date-gated** или **deferred tail**, нового спринта нет.
- **Два внешних гейта в ближайшем окне:** (1) **Wave 1.5 первый 2-week review — 2026-06-20** ([`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md` §11](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md)); (2) **F5-B Phase 1 (T2) gate — ~2026-06-21** (≥7 дней Phase-0 данных от landing `b294b05` 06-14; rate ≥5% по доминирующей оси — [ADR-0016 §Статус](../adr/0016-near-duplicate-dedup.md)).
- **Нет START_PROMPT/PLAN, определяющего следующий спринт**, и в ROADMAP нет «Wave 3» entry (последняя секция — `## 2026-06-14 — Next contract: Wave 2`, [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md` L362–374](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)).
- **Предложено 3 трека** (§2): **α** watchlist-quality continuation, **β** F5-B T2 conditional (gated ≥5%), **γ** internal-quality / tech-debt. **Рекомендованный default (§3, обновлён): α1 (read-only recall-lift measurement) сейчас ‖ γ2 остаток** — γ's headline (BUG-008 spike) уже отгружен (`5165875`), поэтому immediate-actionable вес смещается на α1 (data-readiness, unblocked, замыкает петлю на только-что-landed Handoff B/C/E); γ2 (T7 ops enablement) + γ3 идут параллельно как cheap internal-quality fill, пока β ждёт Phase-0 distribution (~06-21), а α2 (seed-map edit) ждёт review-подтверждения (06-20).

---

## 1. Current state (anchored)

### 1.1 Shipped this session / Wave 2 (закрыто в коде)

| Item | Что | Anchor |
|---|---|---|
| Wave-2 combo (T1/T3/T4/T5/T7) | F5-B Phase 0 dedup observer (intra+cross), bot-UX hygiene (pagination coverage + rich-deterministic renderer + fallback), F5-C P2 freshness (time-based re-summarize + per-channel metric), MCP pagination symmetry | `b294b05` (2026-06-14); closes #39/#40/#41 |
| T6 — gated semantic-unavailable observability | dedicated counter `tg_watchlist_semantic_unavailable_total{reason}` + `WatchlistSemanticUnavailableHigh` alert | `eead91e` (2026-06-18) |
| Handoff C — general-search FTS asymmetry | симметричный tsquery `simple\|\|russian\|\|english` в `embedding_repo.keyword_search` (чинит `семаглутида`→0) | `8197817` (2026-06-18) |
| Handoff B — synonym/brand canonicalization | seed-first alias→canonical map в `watchlist_tokenizer.normalize_token` (GLP-1 RU drug/brand variants); **TIGHT, не** RxNorm/ATC ingestion | `8f69129` (2026-06-18) |
| Doc-hygiene | refresh T6/D1/C/B статусов (clear post-session drift) | `39edfcf` (2026-06-18) |
| Этот черновик (committed) | `DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md` закоммичен/запушен | `221fab4` (2026-06-18) |
| **BUG-008 H1-fix** | batched `get_all_channel_stats` (set-based aggregates вместо per-channel JSON `LIKE` fan-out) + read-scoped `SET LOCAL statement_timeout` (`stats_statement_timeout_ms`, default 30s, **только** stats-сессии, не ingestion); behavior-preserving, DB-backed parity/bounded-query-count/timeout тесты. BUG-008 **остаётся `open`** pending live recurrence (transport-гипотеза H3 отслеживается отдельно) | `5165875` (2026-06-18) |
| Grafana provisioning test realign | привёл тест в соответствие с decommissioned alerting (#149); 8 stale-падений починены → полный suite зелёный | `8e943d5` (2026-06-18) |

Источник backlog-статусов: [`HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md` §6](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) — B ▶ done, C ✅ done, D: D1 done (RARE ~0.83%, 3/360) + T6 done, **D2 deferred** (ADR-gated, no stub — D1 не material).

### 1.2 Date-gated (нельзя стартовать раньше даты/данных)

| Gate | Дата | Что разблокирует | Anchor |
|---|---|---|---|
| **Wave 1.5 review #1** | **2026-06-20** | первый 2-week review заполняет Decision-Point matrix (2A/2B/2C signal counters) → может выбрать внешний трек или confirm «continue dogfooding» | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md` §5/§11](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) |
| **F5-B Phase 1 (T2) gate** | **✅ CLOSED 2026-07-20 → REJECT** | Замерено на данных (с `b294b05` 2026-06-14, ~36д): intra 0.055 % / cross 0.000 % (N=32 805) ≪ 5 % → Phase 1 НЕ строится, ADR-0016 Phase 1 = `Rejected`; Phase-0 counter остаётся observability | [ADR-0016 §Статус](../adr/0016-near-duplicate-dedup.md), [`PLAN_WAVE2 §4 T2`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) |

### 1.3 Deferred tails (метод сохранён, нет гейта-даты — pickup по нужде)

| Item | Статус | Источник |
|---|---|---|
| **D2** — `compute_watch_score` formula change (cap combined при semantic-unavailable) | deferred — **NO ADR-stub** (D1 = RARE ~0.83%, не material; стаб не нужен пока данные не оправдают) | [HANDOFF §6 D](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md), [START_PROMPT T6/D1 §4.3](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md) |
| **F** — `foodf4thought` channel hygiene (Микробиота coverage 56%) | deferred by user | [HANDOFF §6](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) |
| **G** — pluggable lemmatizer registry + detect_language | deferred (нужен только для 3-го+ латино-скриптового языка) | [HANDOFF §6](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) |
| **H** — in-memory matcher scalability / materialized lemmatized FTS index | deferred by user | [HANDOFF §6](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) |
| `watchlist_fix_prompt.md` item 5 (interest-embedding de-dilution) | **refuted** (опровергнуто CAL-пилотами), parked | [HANDOFF §3 row 5](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) |
| Old T6 gated-score alert | **superseded** — реализован как dedicated counter в `eead91e` | [PLAN_WAVE2 §4a](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) |
| Parking-lot (нет signal): Wave E graph retrieval, F11 HTTP CRUD, webhook 2A (ADR-0008), S4 multilang, F1 DB-prompts | deferred — gated на внешнем signal (2A/2B/2C = 0) | [PLAN_WAVE2 §2/§5](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) |
| **BUG-008** — MCP remote endpoint hang | **server-side root-cause (H1) FIXED** (`5165875`: batched stats + read-scoped `statement_timeout`); прежний `guard_read_tool` mitigation остаётся. Статус **`open`** by-design — pending live recurrence; **transport-гипотеза H3** (client/transport stall) отслеживается отдельно, вне репо | [`BUG_LOG.md` BUG-008](BUG_LOG.md), commit `5165875` |

---

## 2. Candidate tracks (mini-contracts)

> Каждый трек — кандидат на следующий спринт. Выбор делает Wave 1.5 review (§3). Формат повторяет house START_PROMPT: goal one-liner · scope · size/risk · deps/gates · why-now.

### Track α — Watchlist-quality continuation

- **Goal (одной строкой):** измерить recall-lift от уже-landed Handoff B/C/E (морфология + canonicalization + FTS-симметрия) на полном корпусе и решить, расширять ли seed-map / тизерить ли Handoff H matcher-scalability groundwork.
- **Scope:**
  - **α1 (measure, read-only):** uncapped `backfill_watchlist(dry_run=true)` по 5 интересам ([HANDOFF §5](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) IDs) до/после-семантика — quantify recall-lift от canonicalization (GLP-1 RU drug-variants) и FTS-симметрии. Выход: per-interest таблица Δ would_match + вердикт «seed-map хватает / нужно расширить».
  - **α2 (опц., gated на α1):** расширить `_ALIAS_TO_CANONICAL` (`tg_parser/services/watchlist_tokenizer.py:53`) на следующий molecule-кластер **только** если α1 покажет underrating; остаётся seed-first (НЕ RxNorm/ATC ingestion — это deliberate post-Wave-2 deferred, [HANDOFF §3 row 6](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md)).
  - **α3 (опц., groundwork-only):** Handoff H scoping — описать materialized lemmatized FTS index / in-memory matcher scalability как ADR-stub `Proposed`, **без** реализации (тизер для будущего спринта).
- **Rough size/risk:** α1 ~0.3–0.5 сессии (read-only, low risk). α2 ~0.3 (seed-map edit + golden-test, low). α3 ~0.3 (docs-only, low). Combo ≤1 сессия.
- **Deps/gates:** нет внешнего гейта; data-readiness — нужен прогон против текущего корпуса. **НЕ** трогать scoring-формулу (D2 deferred).
- **Why-now:** Handoff B/C/E только что landed (06-18) — recall-lift ещё **не измерен** на корпусе; дёшево закрыть петлю «изменили → измерили» (ADR-0006 #6) пока контекст горячий.

### Track β — F5-B Phase 1 (T2) conditional dedup contract — ✅ CLOSED `Rejected` (2026-07-20)

> **⚠️ GATE CLOSED 2026-07-20 → REJECT.** Phase-0 gate отработал на данных за всю жизнь observer'а (с 2026-06-14, ~36 дней ≫ 7д): **intra 0.055 % (18/32 805), cross 0.000 % (0/32 805)** ≪ 5 % по обеим осям → Phase 1 НЕ строится, ADR-0016 Phase 1 = `Rejected — rate below threshold`, Phase-0 counter остаётся permanent observability. Этот трек больше **не** кандидат на спринт. Текст ниже сохранён как decision-record.

- **Goal (одной строкой):** иметь готовый Phase-1 dedup START_PROMPT/ADR-maturation, который **срабатывает только** если Phase-0 gate (~06-21) покажет near-dup rate ≥5% по доминирующей оси.
- **Scope (pre-write, contract-only пока gate закрыт):**
  - Прочитать Phase-0 counter `tg_dedup_near_duplicates_detected_total{dimension}` + histogram `tg_dedup_near_duplicate_similarity{dimension}` за ≥7д; вычислить rate по обеим осям; **go/no-go**.
  - Если **go:** дозреть [ADR-0016 Phase 1](../adr/0016-near-duplicate-dedup.md) Draft→Accepted: `near_duplicate_links` table (append-only, UPSERT DO NOTHING) + JSON-schema `docs/contracts/near_duplicate_link.schema.json` + Alembic + Pydantic + soft-hide flag + canonical=earliest-by-date + «свёрнуто N» transparency. Scope (intra/cross/both) — из реальной distribution.
  - Если **no-go:** закрыть Phase-1 раздел ADR-0016 как `Rejected — rate below threshold`, Phase-0 counter остаётся permanent observability.
- **Rough size/risk:** decision + (go-path) ~1.5–2 сессии (новая persistent сущность, cascade на F11/F6/digest — explicit test). Risk **MED**: false-positive «независимое освещение vs re-post» (mitigate threshold из distribution + reversible soft-hide + видимый «свёрнуто N»).
- **Deps/gates:** **HARD-gated** на Phase-0 ≥7д данных (~06-21) + rate ≥5%. Этот трек = pre-write контракта **до** гейта, чтобы 06-21 был decision, а не планирование.
- **Why-now:** gate открывается через ~3 дня; дешевле подготовить decision-skeleton сейчас, чем стартовать с нуля 06-21. Но **реализация** (go-path) не стартует до данных — иначе scope угадывается вслепую (anti-pattern «tuning без данных», ADR-0006 #6).

### Track γ — Internal-quality / tech-debt

- **Goal (одной строкой):** закрыть owner-felt internal-quality хвосты, не зависящие от внешнего signal или date-gate, пока α2/β ждут review/данных.
- **Scope (cherry-pick, не всё):**
  - **γ1 — BUG-008 root-cause spike → ✅ DONE (`5165875`).** Spike отработал И отгружен реальный server-side фикс (H1): batched `get_all_channel_stats` (set-based aggregates вместо per-channel JSON `LIKE` fan-out) + read-scoped `statement_timeout` (только stats-сессии), behavior-preserving + DB-backed тесты. **Не закрыто полностью:** BUG-008 by-design остаётся `open` pending live recurrence; **остаточный γ1′** = monitoring follow-up (watch на recurrence) + **transport-гипотеза H3** (client/transport stall, вне репо) — узкий low-effort tail, не headline-работа.
  - **γ2 — T7 ops enablement:** F5-C P2 freshness landed с env `RESUMMARIZE_MAX_AGE_DAYS` (default disabled) + per-channel `tg_resummarize_total{channel_id}` metric. Ops-задача: задокументировать/выкатить консервативный prod-default (~14д), добавить Grafana panel / runbook на per-channel re-summarize cost, чтобы owner мог тюнить knob. Size ~0.3–0.5, risk LOW.
  - **γ3 — parking-lot prune / debt audit:** пройтись по [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) + `[wave1.5-dogfood]` записям в FUTURE_FEATURES, отсеять stale, поднять реальные owner-friction в кандидаты. Size ~0.3, risk LOW.
- **Rough size/risk:** после landing γ1 остаток (γ1′ + γ2 + γ3) ≤0.75 сессии, uniformly LOW risk, обратимо.
- **Deps/gates:** **НЕТ** — ни внешнего signal, ни date-gate, ни Phase-0 данных. Можно стартовать сегодня.
- **Why-now:** не-заблокированная low-risk внутренняя работа в окне 06-18..06-21; прецедент Wave 1 / Wave 2 (internal-quality пока owner-active & no external growth, [PLAN_WAVE2 §3 Fork 1/4](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md)). **NB:** с отгрузкой γ1 (BUG-008) headline-объём γ просел → γ теперь parallel-fill, а не самостоятельный трек на полный спринт (см. §3).

---

## 3. Recommended default + per-track blockers

**Рекомендованный default (обновлён после landing `5165875`): α1 (read-only recall-lift measurement) как immediate-actionable сейчас ‖ γ2 (T7 ops enablement) + γ3 как параллельный low-risk fill.** β остаётся pre-write-then-gated.

> **Сдвиг vs первая версия черновика:** изначально дефолтом был **γ** с headline γ1 BUG-008 spike. Этот spike отработал И отгружен (`5165875`) → headline-объём γ просел, и γ больше не «трек на спринт», а parallel-fill. Поэтому immediate-вес смещается на **α1**.

**Rationale (один абзац):** Per Wave-2 weighting rule ([PLAN_WAVE2 §3 Fork 5](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md): #1 **data-readiness**, #2 product-friction, #3 karpathy-coherence, #4 cost/risk), верхний приоритет — то, где можем **измерить**. **α1** ровно это: read-only uncapped dry-run quantifies recall-lift от только-что-landed Handoff B/C/E (06-18) — петля «изменили → измерили» (ADR-0006 #6) ещё не замкнута, и α1 **unblocked сегодня** (read-only, не трогает scoring-формулу, не требует review/гейта). Это побеждает γ, у которого headline (BUG-008) уже отгружен (`5165875`), оставив только узкий monitoring/H3-tail + ops-enablement. **γ2/γ3** идут параллельно как дешёвый internal-quality fill (T7 ops замыкает observability-loop landed freshness-фичи). **β** hard-gated на Phase-0 distribution (~06-21) → его реализация не должна стартовать вслепую; допускается лишь pre-write decision-skeleton. **α2** (расширение seed-map, code change) держим за 06-20 review-подтверждением, что watchlist-quality остаётся приоритетом (а не внешний pivot). После 06-20 review + 06-21 Phase-0 gate — пересобрать приоритет (вероятный порядок: β если gate открыт → α2 если review confirm → γ остаток).

**Что каждый трек blocked on:**

| Track | Blocked on | Когда разблокируется |
|---|---|---|
| **α1** measure (read-only) | **ничего** — read-only, не меняет scoring | **сейчас** (рекомендованный immediate item) |
| **α2** seed-map extend (code) | (soft) Wave 1.5 review подтверждение, что watchlist-quality всё ещё приоритет (а не внешний pivot); + данные α1 | после **2026-06-20** review |
| **β** F5-B T2 | (hard) Phase-0 counter ≥7д **И** near-dup rate ≥5% по доминирующей оси | **~2026-06-21**; pre-write decision-skeleton — можно сейчас, реализация — нет |
| **γ** internal-quality | **ничего** (нет signal/date/data гейта); γ1 BUG-008 уже отгружен (`5165875`), остаток = γ1′ monitoring/H3 + γ2 + γ3 | **сейчас** (parallel-fill) |

---

## 4. Open ADR actions

- **ADR-0016 (near-dup dedup):** Phase 0 — **Implemented** (остаётся permanent observability); Phase 1 — **✅ `Rejected — rate below threshold` (2026-07-20)** — gate закрыт на данных: intra 0.055 % / cross 0.000 % (N=32 805, с 2026-06-14) ≪ 5 %. Track β закрыт. ([ADR-0016 §Статус](../adr/0016-near-duplicate-dedup.md)).
- **D2 (watchlist scoring formula change):** подтверждено — **NO ADR-stub нужен**. D1 показал semantic-unavailable порог-взятие = **RARE (~0.83%, 3/360, все GLP-1)** → не material; стаб создаётся только если будущие данные оправдают изменение формулы (которое тронет ADR-0010/0011 graceful keyword-only). ([HANDOFF §6 D](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md), [START_PROMPT §4.3/§5](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md)).
- **ROADMAP:** «Wave 3» entry **отсутствует** — последняя секция `## 2026-06-14 — Next contract: Wave 2`. Добавление Wave-3 секции — **out of scope этого черновика** (правка ROADMAP только по go-ahead после review-решения).
- **Никаких новых ADR** этот черновик не предлагает (decision-input, не контракт).

---

## 5. Ссылки

- [`HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md`](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) — §3 decisions, §5 interest IDs, §6 backlog (B/C/D/F/G/H).
- [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) — §2 selection, §3 forks, §4/§4a method, §5 sequencing.
- [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) — §5 Decision-Point matrix, §11 review log (06-20 review #1).
- [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — L362–374 Wave-2 entry (нет Wave-3).
- [`START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md`](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md) — house format reference + D1/T6/D2.
- [ADR-0016](../adr/0016-near-duplicate-dedup.md) (near-dup, Phase 1 gated), [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) (#6 tuning-on-data), [ADR-0010](../adr/0010-watchlist-keyword-aggregation.md) / [ADR-0011](../adr/0011-watchlist-backfill-rework.md) (graceful keyword-only).
- Commits: `b294b05` (Wave-2 combo), `eead91e` (T6), `8197817` (Handoff C), `8f69129` (Handoff B), `39edfcf` (doc-hygiene), `221fab4` (этот черновик), `5165875` (BUG-008 H1-fix), `8e943d5` (Grafana test realign).
- Code anchors: `tg_parser/services/watchlist_tokenizer.py:53` (`_ALIAS_TO_CANONICAL` seed-map), `tg_parser/services/near_duplicate_service.py` (Phase-0 observer), `tg_parser/api/metrics.py` (`tg_dedup_*`, `tg_resummarize_total{channel_id}`, `tg_watchlist_semantic_unavailable_total`), `get_all_channel_stats` (BUG-008 batched stats + `stats_statement_timeout_ms`).
