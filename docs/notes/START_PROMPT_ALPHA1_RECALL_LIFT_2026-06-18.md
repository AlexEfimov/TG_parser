# START PROMPT — α1: recall-lift measurement (read-only) for Handoff B/C

**Дата:** 2026-06-18 · **Контекст:** immediate-actionable default из [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) (§3 «Рекомендованный default: **α1** ‖ γ2/γ3»). Этот файл — self-contained стартовая точка для **свежей** сессии (без истории прошлого чата).

**Goal (одной строкой):** **read-only** квантифицировать recall-lift, который дали только-что-landed **Handoff B** (alias→canonical в `watchlist_tokenizer.normalize_token`) и **Handoff C** (симметричный `simple||russian||english` FTS tsquery в `embedding_repo.keyword_search`), на мотивирующих inflected/brand-кейсах против pre-fix baseline-класса — и вынести вердикт, материально ли B/C помогли. **Без** прод-мутаций, **без** изменения scoring-формулы.

> Рабочий режим: коммит / PR — **только** по явному запросу пользователя ([`AGENTS.md`](../../AGENTS.md)). α1 — **read-only** (MCP-чтения + uncapped `dry_run` при нужде; никаких `dry_run=false`). `docs/methodology/` — вне этого workspace.

---

## 1. Current state (durable handoff — всё shipped И задеплоено)

Всё из прошлой сессии **отгружено И задеплоено на VPS prod**: **local == GitHub == prod, все на `529676d`**. DB-миграции в parity — **pending нет**.

### 1.1 Code commits (landed)

| Commit | Что |
|---|---|
| `eead91e` | **T6** — gated semantic-unavailable observability: counter `tg_watchlist_semantic_unavailable_total{reason}` + alert `WatchlistSemanticUnavailableHigh` |
| `8197817` | **Handoff C** — симметричный FTS tsquery `simple\|\|russian\|\|english` в `embedding_repo.keyword_search` (чинит `семаглутида`→0) |
| `8f69129` | **Handoff B** — seed-first alias→canonical canonicalization в `watchlist_tokenizer.normalize_token` (GLP-1 RU drug/brand variants; **TIGHT**, не RxNorm/ATC ingestion) |
| `5165875` | **BUG-008 H1** — batched `get_all_channel_stats` (set-based aggregates вместо per-channel JSON `LIKE` fan-out) + read-scoped `SET LOCAL statement_timeout` (`stats_statement_timeout_ms`, default 30s, **только** stats-сессии, не ingestion) |
| `8e943d5` | **Grafana test realign** — провизионинг-тест приведён к decommissioned alerting (#149); 8 stale-падений → полный `TEST_POSTGRES=1` suite зелёный |

### 1.2 Docs commits (landed)

| Commit | Что |
|---|---|
| `221fab4` | post-Wave-2 contract draft (первая версия) |
| `ee7e7b2` | realign того же contract draft к текущему состоянию |
| `529676d` | runbook/deploy fix — force-recreate prometheus после смены `alerts.yml` (stale inode) · **= текущий HEAD на local/GitHub/prod** |

### 1.3 Статусы, которые важно не «переоткрыть»

- **BUG-008** остаётся **`open` by-design** — pending live recurrence. Server-side root-cause (H1) уже зафикшен (`5165875`); **transport-гипотеза H3** (client/transport stall) отслеживается **отдельно**, вне репо. Не закрывать BUG-008 в этой сессии.
- **D2** (изменение `compute_watch_score` formula) — **deferred, ADR-gated, NO stub**: D1 показал semantic-unavailable порог-взятие = **RARE (~0.83%, 3/360, все GLP-1)**, не material. Стаб не создаётся, пока данные не оправдают.
- Морфология (fix E), uncapped-backfill guardrail, Гиперпролактинемия threshold 0.55 — уже в проде (см. handoff).

---

## 2. Primary task — α1 (READ-ONLY measurement)

**Что измеряем:** recall-lift от двух landed-фиксов на мотивирующих кейсах, против их pre-fix baseline-класса.

- **Handoff B** (`8f69129`) — alias→canonical в `tg_parser/services/watchlist_tokenizer.py` (`_ALIAS_TO_CANONICAL` seed-map ≈ L53, `normalize_token` ≈ L138). Мотивирующий класс: бренд/синоним/cross-language drug-variants должны схлопываться в каноникал — напр. **Ozempic / Wegovy ↔ semaglutide / семаглутид**, ГПП-1 / аГПП-1 / тирзепатид (GLP-1 keyword underrating).
- **Handoff C** (`8197817`) — симметричный tsquery в `tg_parser/storage/sqlalchemy/embedding_repo.py` `keyword_search` (≈ L204; OR-ing `simple || russian || english` ≈ L233–235). Мотивирующий класс: inflected RU-формы в general search — напр. **`семаглутида`** (раньше → 0 docs) vs `семаглутид` (→ 6 docs).

### 2.1 Метод (только read-only, через MCP)

1. **General search (Handoff C):** `search_knowledge_base` mode=`keyword` и mode=`hybrid` на inflected/brand-кейсах (`семаглутида`, `семаглутид`, Ozempic/Wegovy↔semaglutide и т.п.). Сравнить hit-count/recall сейчас против ожидаемого pre-fix поведения (асимметрия `simple`-query vs `russian/english`-index → промах на inflected форме).
2. **Watchlist matching (Handoff B):** `get_watchlist_matches` по 5 интересам (IDs ниже) + при нужде **uncapped** `backfill_watchlist(dry_run=true)` (НЕ `dry_run=false`; `limit` newest-first молча занижает — всегда uncapped). Оценить Δ would_match / recall на canonicalization-чувствительных интересах (особенно GLP-1 drug-variants).
3. **Baseline:** «pre-fix класс» восстановить аналитически (поведение без симметрии tsquery / без alias-map) — НЕ откатывать код. Достаточно показать, какие кейсы класса промахивались до B/C и попадают теперь.

### 2.2 Interest IDs (из [HANDOFF §5](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md))

| Интерес | interest_id | threshold |
|---|---|---|
| GLP-1 | `9f23fd49-8794-427d-a5c0-235a24e175cb` | 0.45 |
| Гиперпролактинемия | `cfc94eb9-164e-4232-a10b-8d5c4d6634db` | 0.55 |
| Микробиота | `9deccefc-c388-4721-bb1f-b7e7dd51d8a5` | 0.5 |
| Биомаркеры | `c4d87f14-9619-4394-8505-68ab20230d45` | 0.5 |
| mTOR | `64ce09c3-fa5c-4f57-8512-dde5fd160993` | 0.5 |

### 2.3 Deliverable α1

- **before/after recall-таблица** для мотивирующих кейсов (general-search inflected + watchlist brand/synonym) — что промахивалось в pre-fix классе и что матчится сейчас.
- **Вердикт:** материально ли B/C помогли recall'у. → это и есть вход для решения α2 (расширять ли seed-map), которое **soft-gated** на Wave 1.5 review (06-20).

---

## 3. Parallel low-risk fill (optional — не вместо α1)

Из [DRAFT §2 Track γ](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md):

- **γ2 — T7 ops enablement:** F5-C P2 freshness landed с env `RESUMMARIZE_MAX_AGE_DAYS` (default disabled) + per-channel `tg_resummarize_total{channel_id}`. Задача: задокументировать/выкатить консервативный prod-default (**~14д**), Grafana panel / runbook на re-summarize cost. ⚠️ Выкат default = **prod-action → нужен явный go пользователя** (gated на cost-watch).
- **γ3 — parking-lot prune / debt audit:** пройтись по [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) + `[wave1.5-dogfood]` записям, отсеять stale, поднять реальный owner-friction. Docs-only, LOW risk.

---

## 4. Date-gated (НЕ стартовать раньше)

| Gate | Дата | Что разблокирует |
|---|---|---|
| **Wave 1.5 review #1** | **~2026-06-20** | первый 2-week review → решает, расширять ли seed-map (**α2**) / остаётся ли watchlist-quality приоритетом. [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md` §5/§11](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) |
| **F5-B Phase 1 (T2) gate** | **~2026-06-21** (≥7д Phase-0 данных от `b294b05` 06-14) | строить Phase-1 dedup **только** если near-dup rate **≥5%** по доминирующей оси (`dimension`); иначе закрыть `Rejected — rate below threshold`. ADR-0016 Phase 1 = **Proposed / GATED**. [`PLAN_WAVE2 §4 T2`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) |

---

## 5. Constraints (CRITICAL)

- **α1 — read-only:** только MCP-чтения + uncapped `dry_run=true`. **Никаких** прод-мутаций, **никакого** `dry_run=false`, **никакого** изменения порогов.
- **Scoring-формула не меняется.** **D2** остаётся deferred/ADR-gated — D1 был RARE (~0.83%), стаб не нужен.
- Коммит / PR — **только** по явному запросу пользователя.
- γ2 prod-default rollout — отдельный explicit go (cost-watch). β-реализация не стартует до Phase-0 данных (~06-21).
- Не трогать `docs/methodology/**`; не править `pyproject.toml` / `requirements.txt` без явного запроса.

---

## 6. Verification plan

1. **Sanity:** `git log --oneline -5` → HEAD = `529676d`; убедиться local==prod (нет pending миграций).
2. **Handoff C:** `search_knowledge_base` keyword/hybrid на `семаглутида` vs `семаглутид` + brand-кейсы → recall сейчас.
3. **Handoff B:** `get_watchlist_matches` + (нужно) uncapped `backfill_watchlist(dry_run=true)` по 5 интересам → would_match / recall на canonicalization-кейсах.
4. **Свести** before/after таблицу + вердикт material/marginal.
5. **Отчёт:** таблица + вердикт + (если material и после 06-20 review) рекомендация по α2 seed-map extension — как предложение, не реализация.

---

## 7. Ссылки

- [`docs/notes/DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) — primary source (track-selection brief; α1 = recommended default). Draft history: `221fab4` → realigned `ee7e7b2`.
- [`docs/notes/HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md`](HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md) — §5 interest IDs, §6 backlog (B/C/D/F/G/H), §2.2 FTS-асимметрия root-cause.
- [`docs/notes/PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) — §5 Decision-Point matrix, §11 review log (06-20 review #1).
- [`docs/notes/PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) — §4 T2 gate (~06-21), §4a deferred T6-метод.
- [`docs/notes/START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md`](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md) — house format reference + D1/T6/D2.
- ADR: [`0010`](../adr/0010-watchlist-keyword-aggregation.md) / [`0011`](../adr/0011-watchlist-backfill-rework.md) (graceful keyword-only — формула by-design), [`0016`](../adr/0016-near-duplicate-dedup.md) (near-dup, Phase 1 Proposed/gated).
- Code anchors: `tg_parser/services/watchlist_tokenizer.py:53` (`_ALIAS_TO_CANONICAL`), `:138` (`normalize_token`); `tg_parser/storage/sqlalchemy/embedding_repo.py:204` (`keyword_search`, symmetric tsquery ≈ L233–235).
- Commits: `eead91e` (T6), `8197817` (Handoff C), `8f69129` (Handoff B), `5165875` (BUG-008 H1), `8e943d5` (Grafana realign), `221fab4`/`ee7e7b2` (contract draft), `529676d` (runbook fix · current HEAD).
