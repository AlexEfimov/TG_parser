# HANDOFF — F11 watchlist: backfill calibration & morphology review (2026-06-15)

**Тип документа:** session handoff / decision-log (post-fix empirical review, docs-only).
**Branch:** `main`. **Режим:** docs-only — ноль кода; commit/deploy — только по явному запросу пользователя ([`AGENTS.md`](../../AGENTS.md)).
**Goal (одной строкой):** зафиксировать in-repo результаты сессии-ревью F11 watchlist (морфология E + калибровка порогов + uncapped backfill), развести подтверждённые факты от опровергнутых гипотез, и передать чётко приоритизированный backlog.

> **Источники вне репо (НЕ копировать в репо — решение пользователя):** `~/Downloads/watchlist_fix_prompt.md` (широкий fix-план) и `~/Downloads/watchlist_session_2026-06-15.md` (эмпирический post-fix handoff). Этот файл — **единственная** in-repo запись их выводов.

---

## 0. TL;DR (executive)

- **Морфология (fix E) — реализована и в проде** для F11 keyword-матчинга (per-token script-routing, см. §2.1). Это сознательный выбор команды, **не** pluggable-registry из `watchlist_fix_prompt.md` — функционально эквивалентно для пары RU/EN.
- **«Микробиота даёт 0 матчей» оказалось артефактом измерения `limit=450`**, а **не** проблемой корпуса/эмбеддингов (§2.3). Uncapped прогон → would_match=33.
- **`limit=450` систематически занижал ВСЕ интересы** (§2.4); manual/retroactive backfill отныне обязателен **uncapped** (guardrail задокументирован, §4).
- **Калибровка:** пороги GLP-1/Биомаркеры/Микробиота/mTOR — precision-OK; **Гиперпролактинемия** была слишком строгой → 0.6 → **0.55** (§3).
- **General search НЕ лемматизируется** — отдельный code path (PostgreSQL FTS), root-cause найден: query/index **асимметрия** `simple` vs `russian/english` (§2.2). → backlog **C**.
- **Embedding de-dilution (`watchlist_fix_prompt.md` item 5) — ОПРОВЕРГНУТО** CAL-пилотами, parked (§3).
- Главный открытый precision-blind-spot — `semantic_available=False` fallback (§2.6) → передан в start-prompt [Deliverable 2](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md) (D1 measure + Wave-2 T6).

---

## 1. Контекст сессии

Сессия — **эмпирическое ревью** после landed-фиксов S1/S3 (ADR-0010 keyword aggregation, ADR-0011 backfill rework) и fix E (morphology tokenizer). Не планирование новой фичи, а: (1) верификация что морфология жива; (2) расследование почему «Микробиота» по-прежнему показывала 0; (3) калибровочный аудит порогов на полном корпусе; (4) production-mutations (uncapped real backfill + один порог) с согласия пользователя; (5) docs guardrail против повторения `limit`-артефакта.

Предыстория: [`DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md`](DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md) (диагностика), [`START_PROMPT_FIX_F11_WATCHLIST_MULTILANG_TOKENIZER_2026-06-08.md`](START_PROMPT_FIX_F11_WATCHLIST_MULTILANG_TOKENIZER_2026-06-08.md) (план fix E), [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) (§4a сохраняет deferred T6-метод).

---

## 2. Findings (verified this session)

### 2.1 Morphology fix E — реализована и в проде ✅

Per-token script-routing для F11 watchlist matcher:

| Ветка | Правило |
|---|---|
| Кириллица | pymorphy3 → `normal_form` |
| Латиница (len ≥ 3) | simplemma `en` |
| Цифры / дефис / mixed / short | identity (lower-case) |

- Фасад: [`tg_parser/services/watchlist_tokenizer.py`](../../tg_parser/services/watchlist_tokenizer.py) — `lru_cache(8192)` + lazy singleton `MorphAnalyzer`.
- Интеграция: [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) `_tokenize` (≈ line 415) → автоматически покрывает doc-токены, keywords и exclude.
- **Это script-routing, НЕ «language-pluggable Lemmatizer registry + detect_language»** из `watchlist_fix_prompt.md`. Сознательный выбор команды; функционально эквивалентно для RU/EN. Pluggable registry нужен **только** при добавлении 3-го+ латино-скриптового языка → backlog **G** (deferred).

### 2.2 General search НЕ лемматизируется — root-caused ✅

`search_knowledge_base` (keyword mode) — **отдельный** code path, **не** вызывает `normalize_token`:

- [`tg_parser/storage/sqlalchemy/embedding_repo.py`](../../tg_parser/storage/sqlalchemy/embedding_repo.py) `keyword_search` (≈ line 204): `plainto_tsquery('simple', :query)` (≈ line 222) + `ts_rank_cd(search_vector, q.tsq)` (≈ line 224) над **STORED** `search_vector`.
- Индекс тела: [`tg_parser/storage/sqlalchemy/_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) `_PD_SEARCH_VECTOR_EXPR` (≈ line 542) / `_TC_SEARCH_VECTOR_EXPR` (≈ line 600) — `to_tsvector('russian'/'english', …)` (Snowball-stemmed).

**ROOT CAUSE** промаха `семаглутида`→0 vs `семаглутид`→6 docs — **query/index config АСИММЕТРИЯ**: query парсится `simple` (без stemming), а тело индексируется `russian`/`english` (Snowball). → дешёвый фикс = **симметричный tsquery** (`simple || russian || english`), **не обязательно** pymorphy3 tsvector-колонка. См. backlog **C**.

### 2.3 «Микробиота = 0» — артефакт `limit=450`, не корпус/не эмбеддинги ✅

- Per-channel content probe: обильный on-topic микробиота-контент в **5 из 6** каналов (слабый только `foodf4thought`, coverage 56%).
- Прошлая сессия: `backfill(dry_run=true, limit=450)` → would_match=0 / max_combined=0.331, потому что `limit` — **NEWEST-FIRST**, а релевантные посты микробиоты **СТАРЫЕ** (вне окна).
- Uncapped (полный корпус, 8004 docs) → **would_match=33 / max_combined=0.789**.
- ⇒ **NO channel surgery, NO scoring change** для Микробиоты.

### 2.4 `limit=450` систематически занижал ВСЕ интересы ✅

| Интерес | Uncapped would_match | Ранее записано (`limit=450`) |
|---|---:|---:|
| GLP-1 | 151 | 1 |
| Биомаркеры | 122 | 4 |
| Микробиота | 33 | 0 |
| mTOR | 26 | 1 |
| Гиперпролактинемия | 19 | 2 |

Uncapped прогоны завершились **без таймаута** (крупнейший `scored_docs=8536`). Кап был добавлен «против таймаута», который так и не материализовался (ср. ADR-0011: `MAX_BACKFILL_DOCS` ретайрнут как scoring-cap).

### 2.5 Calibration audit (read-only, full-corpus matches) ✅

Match %-of-corpus: GLP-1 **3.1%**, Биомаркеры **2.2%**, mTOR **1.0%**, Микробиота **0.4%**, Гиперпролактинемия **0.2%**.

- Lowest-scoring GLP-1 / Биомаркеры матчи — **genuinely on-topic**: GLP-1 low-scores = keyword underrating RU drug-variants (ГПП-1 / аГПП-1 / тирзепатид); Биомаркеры bottom-band = тонкий/тангенциальный longevity-контент.
- Пороги GLP-1 / Биомаркеры / Микробиота / mTOR — **precision-OK**; **Гиперпролактинемия (0.6)** — слишком строгий.

### 2.6 Data-quality flag — `semantic_available=False` fallback (drives backlog D) ⚠️

[`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) `compute_watch_score` (≈ lines 565–573): когда у дока нет эмбеддинга, `semantic_available=False` → `combined = keyword`, который может быть **1.0** и взять порог **без какого-либо semantic-сигнала**. Это graceful degradation by-design (ADR-0010/0011), но **precision-blind-spot**.

- Observed: GLP-1 match `id=14` (kw=1.0, sem=0.0, combined=1.0).
- Audit: редко (~1 из 351). ⇒ **MEASURE before changing scoring** → передано в [Deliverable 2](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md).

---

## 3. Decisions

| # | Решение | Обоснование |
|---|---|---|
| 1 | Морфология via **script-routing** — ACCEPTED; pluggable registry **deferred** | функц. эквивалент для RU/EN; registry нужен только для 3-го+ латино-языка (backlog G) |
| 2 | Микробиота — **NO channel surgery, NO scoring change** | был `limit`-артефакт (§2.3) |
| 3 | Manual/retroactive backfill — **только uncapped** | `limit` newest-first молча занижает (§2.4); guardrail задокументирован (§4) |
| 4 | Гиперпролактинемия порог **0.6 → 0.55** | recorded matches 19 → 26; новые в band 0.55–0.61, kw 0.67–1.0, high quality |
| 5 | Embedding de-dilution (`watchlist_fix_prompt.md` item 5) — **REFUTED**, parked | опровергнуто CAL-пилотами; **не** трогать `build_canonical_interest_text` без новых данных |
| 6 | Synonyms/canonicalization (item B) — **deliberate post-Wave-2 contract, seed-first** | не full RxNorm/ATC/DrugBank ingestion вперёд |
| 7 | Item D — **measure prevalence first (D1)**; формула (D2) — только если данные оправдают | избежать слепого изменения scoring для всех интересов |

---

## 4. Actions taken (production mutations — все user-approved)

- **Real uncapped `backfill_watchlist(dry_run=false, confirm=true)`** для всех 5 интересов: **total inserted 342** (идемпотентно, `notified=true` → **никаких** ретроактивных Telegram-пушей, per ADR-0011). Recorded counts теперь = would_match для каждого.
- **Гиперпролактинемия** (`cfc94eb9-164e-4232-a10b-8d5c4d6634db`) порог → **0.55** через `subscribe_watchlist` upsert (`changed_fields == ["threshold"]`); затем uncapped real backfill (**+7, total 26**).
- **Docs guardrail (эта сессия):**
  - [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) — § «F11 watchlist health» → новая подсекция «Retroactive backfill».
  - [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) — `### backfill_watchlist`.
  - Текст: *«run manual/retroactive backfill uncapped; `limit` is newest-first and silently undercounts»*. Также исправлена устаревшая строка «кап 2000 docs» в обоих файлах.

---

## 5. Interest IDs (для будущих сессий)

| Интерес | interest_id | threshold |
|---|---|---|
| GLP-1 | `9f23fd49-8794-427d-a5c0-235a24e175cb` | 0.45 |
| Гиперпролактинемия | `cfc94eb9-164e-4232-a10b-8d5c4d6634db` | **0.55 (NOW)** |
| Микробиота | `9deccefc-c388-4721-bb1f-b7e7dd51d8a5` | 0.5 |
| Биомаркеры | `c4d87f14-9619-4394-8505-68ab20230d45` | 0.5 |
| mTOR | `64ce09c3-fa5c-4f57-8512-dde5fd160993` | 0.5 |

---

## 6. Remaining backlog (priority order)

| Приоритет | Item | Суть | Статус |
|---|---|---|---|
| **HIGH** | **B — synonym/brand canonicalization** | alias→canonical, cross-language; seed-first; post-Wave-2 contract; чинит GLP-1 keyword underrating; prereq для graph-слоя | ✅ **DONE** — seed-first canonicalization в `watchlist_tokenizer.normalize_token` (`8f69129`); α2 extend (+5 GLP-1 molecule clusters) `284436c` (без scoring-formula/ADR/contract change) |
| **MED** | **C — general-search FTS asymmetry** | step 1: симметричный tsquery `simple\|\|russian\|\|english` в `embedding_repo.keyword_search` + inflection golden-set regression test; step 2 (опц.) pymorphy3 tsvector by need | ✅ **DONE** (`8197817`, симметричный FTS tsquery) |
| **MED** | **D — `semantic_available` guard** | D1 measure (+ T6 counter); D2 формула — только если данные оправдают. См. [Deliverable 2](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md) | ✅ D1 **DONE** (RARE ~0.83%, 3/360, все GLP-1); T6 **DONE** (`eead91e`, dedicated `tg_watchlist_semantic_unavailable_total{reason}` counter + `WatchlistSemanticUnavailableHigh` alert); D2 **deferred** (ADR-gated, no stub — D1 не material) |
| deferred | **F** — `foodf4thought` channel hygiene (Микробиота) | — | by user |
| deferred | **G** — pluggable lemmatizer registry + detect_language | нужен для 3-го+ латино-языка | by user |
| deferred | **H** — in-memory matcher scalability / materialized lemmatized FTS index | — | by user |
| refuted | `watchlist_fix_prompt.md` item 5 (interest-embedding de-dilution) | опровергнуто CAL-пилотами | parked |

---

## 7. Ссылки

- [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) — `compute_watch_score`, `_tokenize`, `semantic_available` branch.
- [`tg_parser/services/watchlist_tokenizer.py`](../../tg_parser/services/watchlist_tokenizer.py) — script-routing фасад (fix E).
- [`tg_parser/storage/sqlalchemy/embedding_repo.py`](../../tg_parser/storage/sqlalchemy/embedding_repo.py) — `keyword_search` (general search FTS).
- [`tg_parser/storage/sqlalchemy/_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) — `_PD_SEARCH_VECTOR_EXPR` / `_TC_SEARCH_VECTOR_EXPR`.
- [`docs/adr/0010-watchlist-keyword-aggregation.md`](../adr/0010-watchlist-keyword-aggregation.md) — top-k keyword aggregation.
- [`docs/adr/0011-watchlist-backfill-rework.md`](../adr/0011-watchlist-backfill-rework.md) — uncapped backfill + silent materialization.
- [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) — Living-KB principles (graceful keyword-only).
- [`docs/notes/PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4a — сохранённый deferred T6-метод.
- [`docs/notes/DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md`](DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md) — runbook диагностики.
- **Next:** [`docs/notes/START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md`](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md) — D1 + T6 start prompt.
