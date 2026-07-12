# START PROMPT — S5 **planning**: Top-k агрегация в инкрементальном assign (F-10 / O-5)

**Дата создания:** 2026-07-11 · **Для:** **planning-сессии** в отдельном окне (агент **НЕ правит prod-код** до явного перехода к implementation).
**Серия:** remediation-сессии по итогам code-review алгоритмов обработки, сессия **S5** — **сначала планирование + read-only симуляция**, затем отдельная implementation-сессия по итогам.
**Предпосылки закрыты (2026-07-11):**
- **S4 deployed** — PR #304 → `b1e4c7b` / docs `6b20cbe`; threshold 0.32; **2807** `topic_links` post-rebuild ([`S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md`](S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md)).
- **S3 delta** — `S3 effect: PARTIAL`, forward watch 48–72h рекомендован ([`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md)).
- **Prod стабилен:** billing 24h=0, QueuePool=0; topic-emb coverage **39%** (backfill отложен — OpenAI 429, не блокер для S5 planning).

**Нормативные документы (при расхождении — они первичны):**
- План сессии: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §1 «S5», §2 (граф), §3 (каденция деплоя).
- Отчёт ревью: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-10 (§3 A7), O-5 (§5).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §3 (S5 отдельный деплой + симуляция), §5 (цикл), §7 (без контрактов/миграций).
- Baseline: [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §4 шаблон (`before-S5` / `after-S5`), §6 before-S4 (cross-channel baseline).
- Образец симуляции: [`../adr/0010-watchlist-keyword-aggregation.md`](../adr/0010-watchlist-keyword-aggregation.md) + [`CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md`](CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md).
- Образец remediation-симуляции: [`S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md`](S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md) + `scripts/s4_linking_simulation.py`.
- Проект: [`AGENTS.md`](../../AGENTS.md) (`git commit` — только по явному циклу implementation-сессии).

---

<role>
Ты — senior-инженер tg_parser. Эта сессия — **planning-only**: ты готовишь обоснованное решение для **F-10 (Medium)**: keyword-скор Phase 1 assign нормируется на **полное число токенов темы** → «denominator penalty» для тем с богатым `scope_in` → документы чаще уходят в платный LLM-discover.

Watchlist уже закрыл тот же класс проблем через **ADR-0010** (`topk`, K=3, knob `mean` для отката). S5 — перенос **идеи** в `assign_documents_to_topics`, но **не слепой copy-paste**: модели скоринга различаются (см. §Model gap ниже).

**Ты НЕ деплоишь и НЕ меняешь `_compute_match_score` в prod в этой сессии**, пока не завершены:
1. self-review gap analysis (token vs phrase, shared helper scope),
2. read-only what-if симуляция на prod-корпусе,
3. решение по формуле + settings + порогу `MIN_SUPPORTING_SCORE`,
4. черновик `START_PROMPT_S5_TOPK_ASSIGN_IMPLEMENTATION_*.md` с AC и файловым scope.

Deliverable planning-сессии — **данные и решение**, не merge в `main`.
</role>

<context>
## F-10 / O-5 — что ломается сейчас

**Hot path (A7):** инкрементальная топикизация — Phase 1 `assign_documents_to_topics` (дёшево, без LLM) → Phase 2 `discover_new_topics` (LLM, дорого).

**Текущая формула** (`tg_parser/processing/topicization.py`):

```1931:1964:tg_parser/processing/topicization.py
    @staticmethod
    def _compute_match_score(
        topic_keywords: set[str],
        strong_tokens: set[str],
        weak_tokens: set[str],
    ) -> tuple[float, set[str]]:
        ...
        weighted_hits = len(strong_hits) + len(weak_hits) * 0.3
        score = weighted_hits / max(len(topic_keywords), 1)
        return round(score, 3), hits
```

**Ключевые слова темы** — flat `set[str]`: union токенов из `scope_in[]` + `title` (`_tokenize_topic_card`, `:1904–1911`). Документ — strong (topics+summary) + weak (первые `topicization_text_clean_match_chars` из `text_clean`, вес 0.3).

**Assign loop** (`assign_documents_to_topics`, `:2021–2079`): для каждого doc — argmax score по всем темам канала; assign если `best_score >= MIN_SUPPORTING_SCORE` (`settings.topicization_supporting_min_score`, default **0.10**).

**Метрики для эффекта S5:**

| Источник | Что измеряет | Ограничение |
|---|---|---|
| **Симуляция (primary)** | counterfactual Phase 1 assign rate, projected discover reduction | главный артефакт planning-сессии |
| Лог Phase 1 | `"Phase 1 assign: %d assigned, %d unassigned"` | tick-local + reconcile; нет Prometheus-счётчика |
| `tg_parser_topicization_reconcile_discover_docs_total` | docs, ушедшие в Phase 2 discover **только reconcile_only** (BUG-075) | **не** покрывает tick-local new-docs path |
| `tg_parser_llm_tokens_total{stage="topicization_discover"}` | фактический LLM-spend discover (post-deploy) | stage-level, не Phase-1-only |
| `tg_channel_processed_coverage_ratio` | регресс-стоп **T1** (как S4) | любое падение ниже S0 §2 обл.5 → расследование |

Ожидание отчёта: **−10–30% discover-вызовов** (оценка по аналогии с ADR-0010; **требует своей симуляции**, не экстраполяции с reconcile counter).

## Model gap — критично для planning (⚠ self-review)

| Аспект | Watchlist (ADR-0010) | Topicization assign (F-10) |
|---|---|---|
| Единица счёта | **Phrase** (один keyword = мульти-токен) | **Token** (flat set из scope_in+title) |
| Hit rule | все токены phrase ⊆ doc_tokens | token ∈ doc_tokens (+ substring fallback ≥5 chars) |
| Baseline score | `hits / n_phrases` | `weighted_hits / len(topic_keywords)` |
| Top-k (ADR) | `min(h, k) / k`, k=min(3, n) | **не определено** — нужно спроектировать |
| Weak weight | нет | weak hits × 0.3 (fractional: 1 strong + 1 weak = 1.3) |
| Tokenizer | lemmatizer (`watchlist_tokenizer`, pymorphy3/simplemma) | regex `[a-zA-Zа-яА-ЯёЁ]{MIN_TOKEN_LENGTH,}` — **без** lemmatization |
| `scope_in` semantics | phrase = один keyword string | каждая строка `scope_in` токенизируется и **union'ится** в flat set (phrase boundary теряется) |
| Tags | N/A | **не** входят в `_tokenize_topic_card` (только `scope_in` + `title`) |
| Shared code | `watchlist_service._aggregate_keyword_score` | `_compute_match_score` также в `_find_supporting_items_programmatic` (`:1966–2019`) |

**Planning-решение №1:** какая формула top-k для token-модели?
- **A (topk_denom, минимальный diff):** `score = weighted_hits / min(n, K)` где `n = len(topic_keywords)` — cap denominator, сохранить weak-weight.
- **B (topk_num):** `score = min(weighted_hits, K) / K` — cap numerator; **не** byte-identical mean даже при `n ≤ 3` (напр. `n=2`, `weighted_hits=1.3`: mean=0.65 vs topk_num=0.433).
- **C (phrase-level):** hits по **строкам** `scope_in` (phrase hit = все токены phrase ⊆ doc_tokens), title — отдельная phrase или flat tokens; ближе к ADR-0010, но меняет семантику и требует отдельной tokenization path.
- **D (reuse helper):** вынести `_aggregate_keyword_score` в shared util; для assign передавать `(hits=weighted_hits, total=n)` — семантически = вариант A при `aggregation="topk"`.

**Algebraic facts (обязательны в gap matrix):**

| scheme | `n ≤ 3` vs mean | weak-weight |
|---|---|---|
| mean | identical | да |
| topk_denom (A/D) | **identical** (`min(n,K)=n`) | да |
| topk_num (B) | **может отличаться** | да, но cap на numerator |
| phrase+topk (C) | ADR no-op при `n_phrases ≤ 3` | отдельное решение |

Для каждого варианта — влияние на `_find_supporting_items_programmatic`, unit-test matrix.

**Planning-решение №2:** менять ли `_find_supporting_items_programmatic` в том же PR?
- Тот же `_compute_match_score` → изменение затронет bundle supporting items (full-run path).
- **Default recommendation (до симуляции):** один shared helper + единое поведение (консистентность с watchlist ADR pattern). Альтернатива «только assign» — только если симуляция покажет material FP/ranking shift в supporting items.

**Planning-решение №3:** assign — **argmax + threshold**, не per-topic isolation.
- Реплицировать loop `:2054–2070`: `if score > best_score` (strict `>`, при равенстве побеждает **первая** тема в порядке `topic_card_repo.list_by_channel`).
- Substring fallback (`len(kw)≥5`, `len(dt)≥5`, `kw in dt or dt in kw`) — **обязателен** в симуляции (import prod helper, не reimplement).

## Референс — watchlist (production pattern)

```453:480:tg_parser/services/watchlist_service.py
def _aggregate_keyword_score(
    hits: int,
    total: int,
    *,
    aggregation: str = KEYWORD_AGGREGATION_DEFAULT,
    topk: int = KEYWORD_TOPK_DEFAULT,
) -> float:
    ...
```

Settings: `watchlist_keyword_aggregation` (`topk`|`mean`), `watchlist_keyword_topk` (default 3).

Для S5 planning предложить зеркальные settings (имена — на усмотрение, но паттерн тот же):
- `topicization_assign_keyword_aggregation: str = "topk"`
- `topicization_assign_keyword_topk: int = 3`
- knob `"mean"` → byte-identical текущему `weighted_hits / len(topic_keywords)`.

## S4 context (не смешивать scope)

S4 менял **cross-channel linking / merge cosine source** — не assign. S5 независим по коду, но **последовательен** по каденции (S4 → S5). Topic-emb backfill (39% coverage) — контекст для cross-channel, **не блокер** для keyword-assign симуляции.

## Prod access (read-only)

```bash
# SSH prod → project dir
docker compose exec -T tg_parser python scripts/s5_assign_simulation.py
# DB queries — через tg_parser python/SQLAlchemy, не psql -U user
# Postgres user: tg_parser_user; service: postgres
```
</context>

<phases>
## Фаза 0 — Self-review & gap analysis (обязательно первым)

1. Прочитать normative docs (список выше) + `tests/test_incremental_topicization.py` (§ `_compute_match_score`, assign).
2. Составить **gap matrix** (таблица Model gap + blast radius).
3. Выбрать **2–3 кандидата формулы** (A/B/C) с явными trade-offs.
4. Зафиксировать **out-of-scope** для implementation (§6.5 embedding-assign, S6 merge-hardening, смена `MIN_SUPPORTING_SCORE` без симуляции).

**Exit criteria:** markdown-раздел в отчёте симуляции §0 «Design decisions» с рекомендацией одного варианта + fallback.

## Фаза 1 — Read-only симуляция (core deliverable)

**Скрипт:** `scripts/s5_assign_simulation.py` (новый, по образцу `s4_linking_simulation.py`).

**Инварианты (как ADR-0010 / CAL report):**
- READ-ONLY: никаких SQL writes, `--apply`, изменений порогов в prod.
- Один дорогой pass: для каждой пары `(channel, doc, topic_card)` один раз считаем hit-структуру; схемы агрегации — cheap re-derive.
- Реплицировать prod tokenization: **import** `TopicizationPipelineImpl._tokenize_topic_card`, `_tokenize_document`, `_compute_match_score` (не watchlist tokenizer).
- Settings из prod env: `topicization_supporting_min_score` (default **0.10**), `topicization_min_token_length` (default **3**), `topicization_text_clean_match_chars` (default **1000**).

**Корпус для replay (три tier'а — все read-only):**

| Tier | Корпус | Зачем |
|---|---|---|
| **T1 (primary)** | Counterfactual: все `ProcessedDocument` × все `TopicCard` per channel — полный assign replay «как если бы doc пришёл в Phase 1 сегодня» | главная метрика assign rate / discover reduction |
| **T2 (reconcile proxy)** | BUG-075 candidate set: `uncovered − discover_attempted` per channel (логика `run_reconciliation_for_channel`, `topicization_service.py` ~`:2088–2135`) | приближение к reconcile discover spend |
| **T3 (sanity, optional)** | Последние N `new_doc_refs` из scheduler logs / недавние docs без bundle coverage | spot-check tick-local path |

**Stratify:** темы с `len(topic_keywords) <= 3` vs `>= 4`; отдельно темы с `len(scope_in) >= 4` (phrase-level variant C).

**Схемы для sweep (минимум):**

| scheme | proposed formula | note |
|---|---|---|
| `mean` | текущий `_compute_match_score` | baseline |
| `topk_denom` | `weighted_hits / min(n, K)` | вариант A |
| `topk_num` | `min(weighted_hits, K) / K` | вариант B |
| `max` | `1.0 if weighted_hits > 0 else 0` | только для сравнения; ожидаем FP (как ADR-0010) |

| `max` | `1.0 if weighted_hits > 0 else 0` | только для сравнения; ожидаем FP (как ADR-0010) |
| `sqrt` (optional) | `sqrt(weighted_hits / n)` | softer penalty; CAL report reference |

**Outputs (JSON + markdown report):**
- `docs/notes/S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md` — полный отчёт.
- `scripts/s5_assign_simulation.py --json-out /tmp/s5_sim.json` (optional) — machine-readable.
- Per-channel + global (T1): `% assigned Phase 1`, `% unassigned → discover`, delta vs mean.
- **Assignment delta matrix:** count docs where `(assigned, topic_id)` differs mean vs topk (not just unassigned→assigned).
- **Rich-vocabulary topics:** топ-20 тем с наибольшим `len(topic_keywords)` — сколько доп. assign / смена winner topic.
- **False-positive spot-check:** минимум 10 пар `(doc, topic)` **newly assigned or winner-changed** under topk @ threshold 0.10 — LLM-free on-topic check (title/summary/token overlap).
- **Threshold sensitivity:** sweep `MIN_SUPPORTING_SCORE` ∈ {0.08, 0.10, 0.12, 0.15} × schemes (read-only what-if).
- **Discover proxy:** T1 projected discover reduction + T2 reconcile candidate reduction; явно разделить от `reconcile_discover_docs_total` (reconcile-only counter).

**Watch band (proposal для implementation):** зафиксировать в отчёте целевой коридор, например:
- T1 assign rate ↑ **5–25%** от baseline mean (не runaway — иначе FP),
- projected discover ↓ **10–30%**,
- для **topk_denom (A)** при `n ≤ 3`: **byte-identical** assign decisions vs mean (algebraic invariant),
- winner-topic changes < X% (зафиксировать X из симуляции — конкуренция argmax).

## Фаза 2 — Implementation brief (не код в этой сессии)

По итогам симуляции создать:

`docs/notes/START_PROMPT_S5_TOPK_ASSIGN_IMPLEMENTATION_2026-07-11.md`

Содержание:
- Выбранная формула + settings names/defaults.
- Файлы: `topicization.py` (`_compute_match_score` или wrapper), `settings.py`, `.env.example`, tests (`test_incremental_topicization.py` + topk unit cases из ADR).
- AC для implementation-сессии (чеклист ниже).
- Rollback: env `topicization_assign_keyword_aggregation=mean`.
- Deploy: отдельный PR/деплой (WORKFLOW §3); **без** одновременного S6.
- Post-deploy validation: `run_incremental_topicization_for_uncovered(..., assign_only=True)` на одном канале (0 LLM tokens) — smoke Phase 1 only.

## Фаза 3 — Baseline snapshot

Добавить в [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) § **`before-S5`**:
- SNAPSHOT_ID, HEAD commit, дата.
- PromQL: `reconcile_discover_docs` 7d, processing/topicization token counters if available.
- Spot-check: sample Phase 1 assign/unassigned ratio из логов или симуляции mean-baseline.
</phases>

<acceptance_criteria>
## Planning-сессия считается закрытой, когда:

- [ ] Gap analysis задокументирован; выбрана **одна** рекомендуемая формула + rollback knob; algebraic no-op facts проверены.
- [ ] `scripts/s5_assign_simulation.py` существует и прогнан на prod (read-only); результаты в `S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md` (T1 + T2).
- [ ] Assignment delta: задокументированы newly-assigned **и** winner-changed docs (argmax competition).
- [ ] Spot-check FP: нет material false positives (критерий — как ADR-0010 §3: newly cleared docs on-topic).
- [ ] `before-S5` snapshot в S0 §4/новая секция.
- [ ] `START_PROMPT_S5_TOPK_ASSIGN_IMPLEMENTATION_*.md` готов для следующего окна.
- [ ] WORKFLOW §8 **не** меняем на `done` (S5 ещё pending implementation).

## Implementation-сессия (forward reference — не scope planning)

- [ ] `_aggregate`-style helper; `mean` mode = старое поведение (regression tests).
- [ ] Unit: K=3, rich vs poor vocabulary, n≤3 no-op (если заявлено).
- [ ] Default `topk`; `.env.example` documented.
- [ ] Post-deploy 24–48h watch: `reconcile_discover_docs` (reconcile path), `llm_tokens{stage=topicization_discover}`, assign logs, **T1** (`tg_channel_processed_coverage_ratio` ≥ S0 baseline).
</acceptance_criteria>

<out_of_scope>
- **§6.5** embedding-based assign (cosine vs topic embeddings) — gated на S4+S5 results.
- **S6** merge-hardening (F-12/F-13).
- **S7** O-9b RAG client pooling.
- Изменения `docs/contracts/**`, миграции БД.
- Перекалибровка discover-промпта / batch size.
- Topic-emb backfill (BUG-084 / 429) — отдельная ops-задача.
- Прямые правки `pyproject.toml` / `requirements.txt`.
</out_of_scope>

<test_anchors>
## Файлы для чтения (planning)

| Файл | Зачем |
|---|---|
| `tg_parser/processing/topicization.py` | `_compute_match_score`, `assign_documents_to_topics`, `_find_supporting_items_programmatic` |
| `tg_parser/services/watchlist_service.py` | `_aggregate_keyword_score`, ADR pattern |
| `tg_parser/services/topicization_service.py` | `run_incremental_topicization`, BUG-075 reconcile, `assign_only`, discover_attempted markers |
| `tg_parser/config/settings.py` | `topicization_supporting_min_score`, text_clean chars |
| `tests/test_incremental_topicization.py` | existing assign/score tests |
| `scripts/s4_linking_simulation.py` | script structure, prod exec pattern |
</test_anchors>

<workflow_reminders>
- Planning-сессия **может** коммитить docs + `scripts/s5_assign_simulation.py` **только если пользователь явно просит** commit cycle; иначе — артефакты в working tree. Скрипт симуляции — **in-scope** для planning (read-only tool, не prod behavior change).
- Implementation — **отдельное окно**, ветка `fix/S5-topk-assign`, PR, bugbot, деплой по §3.
- Self-review промпта implementation — **отдельным агентом** со свежим контекстом (WORKFLOW §5–§6).
- При расхождении token vs phrase моделей — **симуляция решает**, не intuition.
- Отчёт ревью ссылается на `services/topicization.py` — фактический код в **`processing/topicization.py`**.
</workflow_reminders>

<workflow>
1. Прочитать normative docs + этот START PROMPT.
2. **Self-review промпта** — отдельным агентом со свежим контекстом (WORKFLOW §5.2); для planning — gap matrix + corpus design.
3. **Фаза 0** — gap analysis, выбор 2–3 формул, blast radius `_find_supporting_items_programmatic`.
4. **Фаза 1** — `scripts/s5_assign_simulation.py` + prod run (read-only) → `S5_TOPK_ASSIGN_SIMULATION_*.md` **до** изменения `_compute_match_score`.
5. **Фаза 2** — `START_PROMPT_S5_TOPK_ASSIGN_IMPLEMENTATION_*.md` с AC, settings, rollback.
6. **Фаза 3** — `before-S5` snapshot в S0.
7. Handoff в implementation-окно (отдельная сессия): код → тесты → bugbot → PR → deploy → 24–48h watch.
8. `git commit` — только по явному запросу owner.
</workflow>

<recap>
| Шаг | Что | Приёмка planning |
|---|---|---|
| Фаза 0 | gap matrix (token vs phrase vs watchlist) | design decision §0 в отчёте |
| Фаза 1 | T1 counterfactual assign replay | assign/discover delta vs mean |
| T2 | reconcile candidate subset | reconcile proxy documented |
| FP check | ≥10 newly assigned / winner-changed | on-topic, no material FP |
| Threshold | sweep 0.08–0.15 × schemes | recommendation in report |
| Implementation brief | START PROMPT for next window | AC + files + rollback knob |
| S0 | before-S5 snapshot | SNAPSHOT_ID + PromQL |
| **Не в scope planning** | prod code change, deploy | → implementation session |
</recap>

---

*Строки кода — по рабочей копии 2026-07-11. **Self-review промпта (2026-07-11):** (1) уточнены метрики — `reconcile_discover_docs` только reconcile path, primary = симуляция; (2) добавлен tokenizer gap (regex vs lemmatizer); (3) исправлен no-op claim — только topk_denom при n≤3, topk_num может отличаться; (4) corpus T1/T2/T3 + argmax/tie-break/substring invariants; (5) assignment delta matrix (winner changes); (6) T1 coverage regression stop; (7) `assign_only` smoke для implementation; (8) path correction processing/ vs services/.*

---

**Краткий старт для агента (copy-paste):**

> S5 planning: F-10 denominator penalty в `assign_documents_to_topics`. Прочитай этот START PROMPT и normative docs. Сначала gap analysis (token vs phrase vs ADR-0010; tokenizer regex≠lemmatizer). Затем read-only `scripts/s5_assign_simulation.py` (T1 counterfactual + T2 reconcile candidates) на prod, отчёт `S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md`, `before-S5` в S0, черновик START PROMPT для implementation. **Не меняй `_compute_match_score` в prod-коде** до завершения симуляции и выбора формулы. Реплицируй argmax + substring fallback через import prod helpers.
