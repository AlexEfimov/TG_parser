# DRAFT — Next contract (post-Wave-2): track-selection brief

> **DRAFT — for Wave 1.5 review decision on ~2026-06-18..06-20.** Это **не** контракт и **не** START_PROMPT — это decision-input: standalone черновик, из которого предстоящий Wave 1.5 review (2026-06-20) выбирает трек, вместо того чтобы стартовать с нуля. Ничего здесь **не** применяется к ROADMAP / существующим планам без явного go-ahead.

**Тип документа:** planning draft / track-selection brief (docs-only).
**Branch:** `main`. **Режим:** docs-only, ноль кода/тестов; commit/PR — **только** по явному запросу пользователя ([`AGENTS.md`](../../AGENTS.md)).
**Goal (одной строкой):** зафиксировать post-Wave-2 состояние (что shipped / date-gated / deferred) и предложить 2–3 готовых к выбору трека (mini-contracts) + рекомендованный default с явными блокерами, чтобы Wave 1.5 review мог решить, а не планировать.

---

## 0. TL;DR (executive)

- **Wave-2 Dogfood-Quality combo фактически закрыт в коде.** Implementation-волна (`b294b05`, 2026-06-14: T1 F5-B Phase 0 + T3/T4/T5 bot-UX + T7 F5-C P2) и watchlist-quality хвост этой сессии (`eead91e` T6, `8197817` Handoff C, `8f69129` Handoff B, `39edfcf` doc-hygiene, все 2026-06-18) — landed. Остаток — **date-gated** или **deferred tail**, нового спринта нет.
- **Два внешних гейта в ближайшем окне:** (1) **Wave 1.5 первый 2-week review — 2026-06-20** ([`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md` §11](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md)); (2) **F5-B Phase 1 (T2) gate — ~2026-06-21** (≥7 дней Phase-0 данных от landing `b294b05` 06-14; rate ≥5% по доминирующей оси — [ADR-0016 §Статус](../adr/0016-near-duplicate-dedup.md)).
- **Нет START_PROMPT/PLAN, определяющего следующий спринт**, и в ROADMAP нет «Wave 3» entry (последняя секция — `## 2026-06-14 — Next contract: Wave 2`, [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md` L362–374](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)).
- **Предложено 3 трека** (§2): **α** watchlist-quality continuation, **β** F5-B T2 conditional (gated ≥5%), **γ** internal-quality / tech-debt. **Рекомендованный default (§3): γ** — единственный трек, **не** заблокированный внешним гейтом/датой/данными; даёт полезную работу в окне 06-18..06-21, пока α/β/Wave-3-выбор ждут review и Phase-0 distribution.

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

Источник backlog-статусов: [`HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md` §6](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) — B ▶ done, C ✅ done, D: D1 done (RARE ~0.83%, 3/360) + T6 done, **D2 deferred** (ADR-gated, no stub — D1 не material).

### 1.2 Date-gated (нельзя стартовать раньше даты/данных)

| Gate | Дата | Что разблокирует | Anchor |
|---|---|---|---|
| **Wave 1.5 review #1** | **2026-06-20** | первый 2-week review заполняет Decision-Point matrix (2A/2B/2C signal counters) → может выбрать внешний трек или confirm «continue dogfooding» | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md` §5/§11](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) |
| **F5-B Phase 1 (T2) gate** | **~2026-06-21** (≥7д от `b294b05`) | near-dup rate ≥5% по доминирующей оси (`dimension`) → строить Phase 1 (scope intra/cross/both выбирает owner из distribution); иначе закрыть как `Rejected — rate below threshold` | [ADR-0016 §Статус](../adr/0016-near-duplicate-dedup.md), [`PLAN_WAVE2 §4 T2`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) |

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
| **BUG-008** — MCP remote endpoint hang | `open`, monitor-only (mitigation `guard_read_tool` landed; root-cause unconfirmed, repro flaky) | [`BUG_LOG.md` BUG-008](BUG_LOG.md) |

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

### Track β — F5-B Phase 1 (T2) conditional dedup contract

- **Goal (одной строкой):** иметь готовый Phase-1 dedup START_PROMPT/ADR-maturation, который **срабатывает только** если Phase-0 gate (~06-21) покажет near-dup rate ≥5% по доминирующей оси.
- **Scope (pre-write, contract-only пока gate закрыт):**
  - Прочитать Phase-0 counter `tg_dedup_near_duplicates_detected_total{dimension}` + histogram `tg_dedup_near_duplicate_similarity{dimension}` за ≥7д; вычислить rate по обеим осям; **go/no-go**.
  - Если **go:** дозреть [ADR-0016 Phase 1](../adr/0016-near-duplicate-dedup.md) Draft→Accepted: `near_duplicate_links` table (append-only, UPSERT DO NOTHING) + JSON-schema `docs/contracts/near_duplicate_link.schema.json` + Alembic + Pydantic + soft-hide flag + canonical=earliest-by-date + «свёрнуто N» transparency. Scope (intra/cross/both) — из реальной distribution.
  - Если **no-go:** закрыть Phase-1 раздел ADR-0016 как `Rejected — rate below threshold`, Phase-0 counter остаётся permanent observability.
- **Rough size/risk:** decision + (go-path) ~1.5–2 сессии (новая persistent сущность, cascade на F11/F6/digest — explicit test). Risk **MED**: false-positive «независимое освещение vs re-post» (mitigate threshold из distribution + reversible soft-hide + видимый «свёрнуто N»).
- **Deps/gates:** **HARD-gated** на Phase-0 ≥7д данных (~06-21) + rate ≥5%. Этот трек = pre-write контракта **до** гейта, чтобы 06-21 был decision, а не планирование.
- **Why-now:** gate открывается через ~3 дня; дешевле подготовить decision-skeleton сейчас, чем стартовать с нуля 06-21. Но **реализация** (go-path) не стартует до данных — иначе scope угадывается вслепую (anti-pattern «tuning без данных», ADR-0006 #6).

### Track γ — Internal-quality / tech-debt (recommended default, §3)

- **Goal (одной строкой):** закрыть owner-felt internal-quality хвосты, не зависящие от внешнего signal или date-gate, пока α/β ждут review/данных.
- **Scope (cherry-pick 1–2, не всё):**
  - **γ1 — BUG-008 root-cause spike** ([`BUG_LOG.md` BUG-008](BUG_LOG.md)): MCP remote endpoint hang. Mitigation (`guard_read_tool` per-request timeout) landed, но root-cause unconfirmed / repro flaky. Spike: воспроизвести под нагрузкой / инструментировать transport-слой; либо локализовать, либо записать «не воспроизводится → monitor-only confirmed». Size ~0.5–1, risk LOW (мitigation уже защищает прод).
  - **γ2 — T7 ops enablement:** F5-C P2 freshness landed с env `RESUMMARIZE_MAX_AGE_DAYS` (default disabled) + per-channel `tg_resummarize_total{channel_id}` metric. Ops-задача: задокументировать/выкатить консервативный prod-default (~14д), добавить Grafana panel / runbook на per-channel re-summarize cost, чтобы owner мог тюнить knob. Size ~0.3–0.5, risk LOW.
  - **γ3 — parking-lot prune / debt audit:** пройтись по [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) + `[wave1.5-dogfood]` записям в FUTURE_FEATURES, отсеять stale, поднять реальные owner-friction в кандидаты. Size ~0.3, risk LOW.
- **Rough size/risk:** combo любых 1–2 ≤1 сессии, uniformly LOW risk, обратимо.
- **Deps/gates:** **НЕТ** — ни внешнего signal, ни date-gate, ни Phase-0 данных. Можно стартовать сегодня.
- **Why-now:** это единственный трек, дающий полезную, не-заблокированную работу в окне 06-18..06-21; прецедент Wave 1 / Wave 2 (internal-quality пока owner-active & no external growth, [PLAN_WAVE2 §3 Fork 1/4](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md)).

---

## 3. Recommended default + per-track blockers

**Рекомендованный default: Track γ (internal-quality / tech-debt), cherry-pick γ1 BUG-008 spike + γ2 T7 ops enablement.**

**Rationale (один абзац):** В окне 06-18..06-21 оба signal-несущих трека заблокированы: **α** хочет свежий corpus-замер, но его main value (решение «расширять seed-map?») всё равно лучше принимать после того, как Wave 1.5 review (06-20) подтвердит, что watchlist-quality остаётся приоритетом, а не внешний pivot; **β** hard-gated на Phase-0 данных (~06-21) и его реализация не должна стартовать вслепую. **γ** — единственный трек **без** внешней зависимости: BUG-008 — единственный `open` баг и owner живёт на MCP read-tools ежедневно; T7 ops enablement замыкает observability-loop только что landed freshness-фичи (ADR-0006 #6). γ даёт обратимую, low-risk, owner-felt работу прямо сейчас и **не** прожигает решение, которое review/гейт должны принять на данных. После 06-20 review + 06-21 Phase-0 gate — пересобрать приоритет (вероятный порядок: β если gate открыт → α measure → γ остаток).

**Что каждый трек blocked on:**

| Track | Blocked on | Когда разблокируется |
|---|---|---|
| **α** watchlist-quality | (soft) Wave 1.5 review подтверждение, что watchlist-quality всё ещё приоритет (а не внешний pivot); data-readiness — corpus-прогон | после **2026-06-20** review; α1 сам по себе read-only можно и раньше |
| **β** F5-B T2 | (hard) Phase-0 counter ≥7д **И** near-dup rate ≥5% по доминирующей оси | **~2026-06-21**; pre-write контракта — можно сейчас, реализация — нет |
| **γ** internal-quality | **ничего** (нет signal/date/data гейта) | **сейчас** |

---

## 4. Open ADR actions

- **ADR-0016 (near-dup dedup):** Phase 0 — **Implemented**; Phase 1 — **Proposed / GATED**, дозревает Draft→Accepted **только** при rate ≥5% по доминирующей оси (~06-21) или закрывается `Rejected — rate below threshold`. Прямо завязан на Track β. ([ADR-0016 §Статус](../adr/0016-near-duplicate-dedup.md)).
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
- Commits: `b294b05` (Wave-2 combo), `eead91e` (T6), `8197817` (Handoff C), `8f69129` (Handoff B), `39edfcf` (doc-hygiene).
- Code anchors: `tg_parser/services/watchlist_tokenizer.py:53` (`_ALIAS_TO_CANONICAL` seed-map), `tg_parser/services/near_duplicate_service.py` (Phase-0 observer), `tg_parser/api/metrics.py` (`tg_dedup_*`, `tg_resummarize_total{channel_id}`, `tg_watchlist_semantic_unavailable_total`).
