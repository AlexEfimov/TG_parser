# START PROMPT — S4: Topic embeddings в линковке и cross-chunk консолидации (F-04 High + F-05 Medium; O-4)

**Дата создания:** 2026-07-11 · **Для:** implementation-сессии в отдельном окне (агент **ПРАВИТ код**).
**Серия:** remediation-сессии по итогам code-review алгоритмов обработки, сессия **S4** (главный рычаг качества cross-channel линковки — cosine по теме, а не по первому якорному посту).
**Предпосылки закрыты (2026-07-11):**
- **P2 S3 delta** — `S3 effect: PARTIAL`, **`S4: GO`** ([`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md)).
- **Prod стабилен:** billing 24h=0, QueuePool=0, coverage ≥ S0 baseline, HEAD `6904b0b`.

**Нормативные документы (при расхождении — они первичны):**
- План сессии: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §1 «S4», §2 (граф), §3 (каденция деплоя).
- Отчёт ревью: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-04 (§3 A8/A8, §4), F-05 (§3 A9), O-4 (§5).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §3 (деплой S4 отдельно + симуляция), §5 (цикл), §7 (без контрактов/миграций).
- Baseline: [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §4 шаблон (`before-S4` / `after-S4`).
- Симуляция (образец): [`../adr/0010-watchlist-keyword-aggregation.md`](../adr/0010-watchlist-keyword-aggregation.md) + [`CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md`](CAL_WATCHLIST_S1_AGGREGATION_SIMULATION_2026-06-08.md).
- Cross-channel ops: [`mcp_testing/2026-05-15_claude_session/04-operational-runbook.md`](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md) (O-9 Phase 3, O-10 truncate-and-rebuild).
- Проект: [`AGENTS.md`](../../AGENTS.md) (`git commit` — только по явному циклу сессии).

---

<role>
Ты — senior-инженер tg_parser. Ты закрываешь **F-04 (High)**: сейчас «эмбеддинг темы» = эмбеддинг **документа первого якоря** (`anchors[0].anchor_ref`), хотя topic-эмбеддинги (`run_topic_embedding`, `entry_type='topic'`, `source_ref=card.id`) уже существуют. Похожесть тем измеряется похожестью двух случайных постов → ложные слияния/пропуски линков; порог `0.3` калиброван по искажённой метрике (avg-sim линков ≈0.33, ADR-0016).

Ты также частично закрываешь **F-05**: N+1 фетч эмбеддингов в цикле → батчевый `get_many_by_source_refs`. All-pairs O(C²·T²) **остаётся** (stretch S4b / HNSW — out of scope MVP).

**Три call sites, один resolver.** Все пути cosine используют общий helper с fallback. **Без миграций и без изменений `docs/contracts/**`.** Формула `0.4·Jaccard + 0.6·cosine` не меняется.

Сессия начинается с **read-only симуляции** (Фаза 0), затем код, тесты, отдельный деплой, 24–48h watch.
</role>

<context>
**F-04 (High, качество).** `topic_linking_service.link_topics` (`:103–109`) и аналогичная логика в `topicization_service._finalize_full_run` (`:757–769`) и `_run_cross_channel_linking` (`:2442–2458`) грузят `embedding_repo.get_by_source_ref(card.anchors[0].anchor_ref)` — message embedding. Topic embedding строится из `summary | scope_in` (`embedding_service._prepare_topic_text`) и хранится с `source_ref=card.id`.

**F-05 (Medium, скорость).** Per-card `get_by_source_ref` в цикле при ~1000 темах — сотни round-trip'ов; батчевый метод уже есть (`embedding_repo.get_many_by_source_refs`, ADR-0011).

**Два порога — два blast radius (⚠ self-review patch):**

| Порог | Setting | Где | Эффект |
|---|---|---|---|
| **0.3** | `cross_channel_link_threshold` | `link_topics`, Phase 3 `_run_cross_channel_linking` | Создание/пересборка `topic_links` |
| **0.6** | `topicization_full_merge_threshold` | `_finalize_full_run` | **Удаление** loser-карточек same-channel при full-run merge |

Смена embedding source меняет combined score **в обоих** путях. Симуляция и watch обязаны покрыть **оба** порога, даже если default меняем только для 0.3.

**⚠ `link_topics` НЕ в scheduler per-tick.** Global `link_topics` — on-demand: CLI `tg-parser link-topics`, MCP `trigger_link_topics`, `pipeline_dispatch_service` (`job=link_topics`). Cron в `background_scheduler` для link_topics **нет**. Нормативное «актуальные topic-эмбеддинги перед линковкой» — это **precondition**, не порядок хуков `_process_source`.

**Два режима линковки (разный watch):**

| Режим | Поведение | Когда |
|---|---|---|
| **Global** `link_topics` | `delete_all` + rebuild (O-10 truncate-and-rebuild) | Ручной/MCP trigger |
| **Incremental Phase 3** | `upsert` новых links для touched topics | Каждый incremental tick с `cross_channel=True` |

**Stale topic embeddings.** После resummarize (S1) `run_topic_embedding(force=True)` обновляет вектор. Но карточка может измениться без re-embed → линковка на устаревшем topic emb. В Фазе 0 замерить долю stale (`card.updated_at` vs `embedding.created_at`).

**Confounders (не блокеры S4):** BUG-084 embeddings `429` → больше anchor fallback; billing clean (P0 снят).
</context>

<verified_anchors>
Факты по рабочей копии 2026-07-11 — при смещении строк ориентируйся на символы.

| Что | Где | Факт |
|---|---|---|
| Global linking | `topic_linking_service.py:65` (`link_topics`), `:103–109` (N+1 anchor emb) | all-pairs; `delete_all` + `upsert_batch`; weights `JACCARD_WEIGHT=0.4`, `COSINE_WEIGHT=0.6`; default threshold `SIMILARITY_THRESHOLD=0.3` |
| Full-run merge | `topicization_service.py:678` (`_finalize_full_run`), `:757–769` | same cosine+Jaccard; threshold `settings.topicization_full_merge_threshold` (default **0.6**); loser card **deleted** |
| Incremental Phase 3 | `topicization_service.py:2399` (`_run_cross_channel_linking`), `:2442–2458` | reuses `_jaccard_similarity` / `_cosine_similarity` from `topic_linking_service`; threshold `settings.cross_channel_link_threshold` |
| Topic embedding write | `embedding_service.py:265` (`run_topic_embedding`), `:257` (`_prepare_topic_text`), `:327–334` (`save`) | `source_ref=card.id`, `entry_type='topic'`, `topic_id=card.id` |
| Batch fetch | `embedding_repo.py:130` (`get_many_by_source_refs`) | `source_ref = ANY(:refs)`, chunk 1000; **без** filter `entry_type` |
| Per-tick topic embed | `scheduler_service.py:514–534` | **после** `run_incremental_topicization` — ⚠ Phase 3 linking уже отработал внутри incremental **до** embed |
| Phase 3 inside incremental | `topicization_service.py:1406–1419` | `_run_cross_channel_linking` в хвосте incremental — **до** scheduler `run_topic_embedding` |
| Dispatch threshold gap | `pipeline_dispatch_service.py:263` | `await do_link()` без threshold → default const, **не** `settings.cross_channel_link_threshold` |
| Background topic embed | `background_scheduler.py:551–588` (`_incremental_embedding_task`) | `run_topic_embedding(force=False)` per active channel (не link_topics) |
| Dispatch | `pipeline_dispatch_service.py:254–255` | `LINK_TOPICS` → `link_topics()` |
| CLI | `cli/app.py:639` (`link-topics`) | `--threshold`, prints `avg_similarity`, `total_pairs_evaluated` |
| Settings | `settings.py:570` (`cross_channel_link_threshold=0.3`), `:516` (`topicization_full_merge_threshold=0.6`) | оба `ge=0, le=1` |
| Baseline avg-sim | ADR-0016 / MCP testing | ~1052 links, avg-sim **≈0.33**; link-topics ~**46s** / 746 links |
| Регресс-стоп | `tg_channel_processed_coverage_ratio` | T1: любое падение ниже S0 §2 обл.5 → расследование |
| Existing tests | `tests/test_topic_linking_service.py`, `tests/test_cross_channel_topicization.py` | моки `get_by_source_ref(anchor_ref)` — **сломаются** после batch-by-card.id |
</verified_anchors>

<design_decision>
**1. Общий resolver (ядро сессии).**

Вынести в `topic_linking_service.py`:

```python
async def load_card_embeddings(
    cards: list[TopicCard],
    embedding_repo: EmbeddingRepo,
) -> tuple[dict[str, list[float]], EmbeddingLoadStats]:
    """
    1. topic_ids = [c.id for c in cards]
    2. batch = await embedding_repo.get_many_by_source_refs(topic_ids)
    3. для каждого hit: assert entry_type == 'topic' (defensive)
    4. fallback: anchor_refs для карт без topic emb → второй batch
    5. missing → Jaccard-only (как сейчас)
    """
```

Лог/метрика (рекомендуется): `topic_embedding_resolve_total{source=topic|anchor_fallback|missing}`.

**Stale policy (решение в PR, зафиксировать явно):**
- **MVP (рекомендуется):** использовать topic emb как есть; в симуляции отчитаться о % stale; post-deploy watch.
- **Stretch:** если `card.updated_at > embedding.created_at` → fallback на anchor emb для этой карты.

**2. Два AC для «актуальности эмбеддингов» (⚠ patch — НЕ «hook link_topics в scheduler»):**

**⚠ Факт по коду (2026-07-11):** Phase 3 `_run_cross_channel_linking` вызывается **внутри** `run_incremental_topicization` (`topicization_service.py:1406–1419`), а `run_topic_embedding` в scheduler идёт **после** incremental (`scheduler_service.py:514–534`). Значит в текущем тике Phase 3 линкует **до** обновления topic-эмбеддингов для новых/изменённых тем. Нормативный план требует **исправить** это (не «сохранить порядок»).

**AC-A (incremental — обязательный fix, выбрать один путь в PR):**
- **Вариант A (рекомендуется):** в scheduler после `run_topic_embedding(force=False)` вызвать Phase 3 для `touched_topic_ids` из `incr_result` (вынести linking из хвоста incremental **или** дублировать вызов с идемпотентным upsert). Phase 3 внутри incremental — удалить или сделать no-op при флаге.
- **Вариант B (минимальный):** перед Phase 3 внутри incremental — `run_topic_embedding(channel_id, topic_ids=list(touched), force=True)` только для touched/new topics.
- Тест: в одном тике topic-embedding для touched topics **завершён до** `_run_cross_channel_linking`.

**AC-B (global link_topics):** pre-flight: ≥95% карт имеют topic embedding **или** явный backfill `run_topic_embedding(force=True)` per channel **перед** первым post-deploy `link_topics`. `link_topics` не добавлять в cron scheduler.

**AC-C (settings wiring):** `link_topics()` и `pipeline_dispatch_service` (`do_link()`) должны брать порог из `settings.cross_channel_link_threshold`, а не только из константы `SIMILARITY_THRESHOLD=0.3` (сейчас dispatch вызывает `do_link()` без аргументов).

**3. Калибровка порогов (симуляция до merge кода).**

Read-only what-if на prod/dev корпусе (~13 каналов, ~1000 тем):

| Ось | Пороги для sweep | Deliverable |
|---|---|---|
| Cross-channel links | 0.25, 0.30, 0.35, 0.40 | snapshot-diff `topic_links`: added/removed/changed-score |
| Same-channel merge | 0.55, 0.60, 0.65, 0.70 | estimate `merge_losers` per channel @ `_finalize_full_run` |

Сравнить **anchor_emb (текущее)** vs **topic_emb (новое)**. Выбрать `cross_channel_link_threshold` data-driven. Для `topicization_full_merge_threshold=0.6`: **не менять default в MVP**, если симуляция показывает аномальный рост merge — задокументировать watch-only decision.

**Примечание:** `_finalize_full_run` активен только при `topicization_full_resume_enabled=True` (BUG-076). На типичном incremental prod-пути merge @0.6 может быть редким — симуляция всё равно обязательна, но приоритет watch — cross-channel @0.3.

**4. S4b (HNSW / top-K KNN) — out of MVP.** Если сессия не укладывается — отдельная S4b. `embedding_repo.similarity_search(entry_types=['topic'])` — задел, не scope.
</design_decision>

<scope>
**Фаза 0 — Read-only подготовка (до кода, обязательна):**

1. **Baseline `before-S4`** в S0 §4 / новая подсекция:
   - export `topic_links` count + avg `similarity_score`
   - `SELECT count(*) FROM document_embeddings WHERE entry_type='topic'`
   - topic emb coverage: % `topic_cards` с topic emb
   - stale audit: % карт где `topic_cards.updated_at` > `document_embeddings.created_at` (оба **Text/String ISO** — парсить в Python, не наивный SQL `>`)
   - `link_topics` duration baseline из prod logs (ориентир ~46s)
2. **Симуляция** → артефакт [`S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-*.md`](S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md) + скрипт `scripts/s4_linking_simulation.py` (read-only SQL, reproducible).
3. **Решение по порогу** — зафиксировать в simulation report до написания production-кода.

**Фаза 1 — Helper:**
- `load_card_embeddings` + `EmbeddingLoadStats` dataclass
- optional Prometheus counter `topic_embedding_resolve_total`

**Фаза 2 — Wire 3 call sites + hook fix:**
- `topic_linking_service.link_topics` — заменить `:103–109`; default threshold из `settings.cross_channel_link_threshold`
- `topicization_service._finalize_full_run` — заменить `:757–769`
- `topicization_service._run_cross_channel_linking` — заменить `:2442–2458`
- **Scheduler hook fix (AC-A):** обеспечить topic embed до Phase 3 (см. `<design_decision>` §2)

**Фаза 3 — Threshold + settings:**
- Обновить `cross_channel_link_threshold` default (и `.env.example`) по симуляции
- `topicization_full_merge_threshold` — только если симуляция @0.6 требует; иначе watch-only note в PR

**Фаза 4 — Тесты:**
- Обновить моки в `test_topic_linking_service.py`: `get_many_by_source_refs` по `card.id`, fallback по `anchor_ref`
- Новые: topic-primary, anchor-fallback, batch-single-call, `entry_type='topic'` guard
- `test_cross_channel_topicization.py`: Phase 3 path с topic emb
- `test_bug076_checkpoint_topicization.py`: `_finalize_full_run` merge path
- `test_scheduler_service.py`: AC-A — topic_embedding до Phase 3 (не «до link_topics»)

**Фаза 5 — Deploy & watch (отдельный деплой, WORKFLOW §3):**
1. Pre-deploy: billing 24h=0, coverage ≥ S0, QueuePool=0
2. Deploy S4
3. Backfill: `run_topic_embedding(force=True)` per channel (если coverage < 95%)
4. Trigger `link_topics` (MCP или CLI)
5. Watch 24–48h: `topic_links` ±20% от симуляции; merge losers не аномальны; `topic_embedding_resolve` anchor_fallback < 10%; coverage T1

**Docs (deliverable):**
- `S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_*.md`
- S0 §4/§6 `after-S4` snapshot
- WORKFLOW §8: S4 status
</scope>

<out_of_scope>
- **Миграции, `docs/contracts/**`** — запрещены (WORKFLOW §7).
- **Изменение формулы** Jaccard+cosine weights — не трогать.
- **S4b HNSW / all-pairs replacement** — отдельная сессия.
- **S5 top-k assign**, **S6 merge**, **BUG-084 fix** — не в S4.
- **near-dup ANN** (ADR-0016 Phase 1).
- **Добавление `link_topics` в cron scheduler** — не требуется; global job остаётся on-demand.
- **Hard rollback блока S1–S3** (`f985b9c`) — только при T1 coverage regression + owner approval.
</out_of_scope>

<acceptance_criteria>
Сессия принята, когда:

1. **Фаза 0 выполнена:** simulation report + `before-S4` baseline (links, topic emb coverage, stale %, link_topics duration).
2. **Все 3 call sites** используют `load_card_embeddings` (topic primary, anchor fallback, batch).
3. **Симуляция** покрывает пороги **0.3 (cross-channel)** и **0.6 (same-channel merge)**; snapshot-diff приложен.
4. **`cross_channel_link_threshold`** перекалиброван с обоснованием; `.env.example` синхронизирован.
5. **Решение по `topicization_full_merge_threshold`** задокументировано (change или watch-only).
6. **AC-A:** hook fix выполнен; тест подтверждает topic_embedding до Phase 3 в incremental tick.
7. **AC-B:** pre-flight/backfill topic emb перед post-deploy `link_topics` описан и выполнен.
8. **AC-C:** `link_topics` / dispatch используют `settings.cross_channel_link_threshold`.
9. **Тесты:** default + `TEST_POSTGRES=1` green; моки обновлены (`test_embedding.py` при затрагивании repo).
10. **Bugbot clean**, PR merged, **отдельный deploy**, 24h watch без T1 regression.
11. **S0 after-S4** + WORKFLOW §8 обновлены.
</acceptance_criteria>

<commands>
**Фаза 0 — baseline (read-only prod):**

```bash
ssh prod 'cd /home/user/TG_parser && \
  echo "HEAD $(git rev-parse --short HEAD)" && \
  docker compose exec -T tg_parser_postgres psql -U user -d tg_parser -c \
    "SELECT count(*) AS topic_links FROM topic_links;" && \
  docker compose exec -T tg_parser_postgres psql -U user -d tg_parser -c \
    "SELECT round(avg(similarity_score)::numeric,4) FROM topic_links;" && \
  docker compose exec -T tg_parser_postgres psql -U user -d tg_parser -c \
    "SELECT count(*) AS topic_embs FROM document_embeddings WHERE entry_type='"'"'topic'"'"';"'
```

**Topic emb coverage + stale (адаптировать под схему):**

```sql
-- coverage: cards with topic embedding
SELECT count(DISTINCT tc.id) AS cards,
       count(DISTINCT de.source_ref) AS with_topic_emb
FROM topic_cards tc
LEFT JOIN document_embeddings de
  ON de.source_ref = tc.id AND de.entry_type = 'topic';
```

**Post-deploy watch:**

```bash
ssh prod 'curl -s localhost:8000/metrics | grep "^tg_channel_processed_coverage"'
ssh prod 'cd /home/user/TG_parser && docker compose logs --since 24h tg_parser 2>&1 | grep -i "topic link\|link_topics\|Created.*topic links" | tail -10'
```

**Trigger link_topics после deploy:**

```bash
ssh prod 'cd /home/user/TG_parser && docker compose exec tg_parser tg-parser link-topics'
# или MCP trigger_link_topics
```

**Тесты (локально):**

```bash
pytest -q tests/test_topic_linking_service.py tests/test_cross_channel_topicization.py
TEST_POSTGRES=1 pytest -q tests/test_topic_linking_service.py tests/test_bug076_checkpoint_topicization.py
```
</commands>

<workflow>
1. Прочитать normative docs + этот START PROMPT.
2. **Self-review промпта** — отдельным агентом со свежим контекстом (WORKFLOW §5.2).
3. **Фаза 0** — read-only baseline + simulation → порог выбран **до кода**.
4. **Фаза 1–2** — helper + 3 call sites.
5. **Фаза 4** — тесты (red → green), обновить моки.
6. **Фаза 3** — применить порог по симуляции.
7. Self-review тестов → self-review кода → bugbot.
8. PR → merge → **отдельный deploy** → backfill → link_topics → 24h watch.
9. Docs: simulation report, S0 after-S4, WORKFLOW §8.
10. `git commit` — только по явному запросу owner в конце цикла.
</workflow>

<recap>
| Шаг | Что | Приёмка |
|---|---|---|
| Фаза 0 | simulation @ 0.3 + 0.6, baseline | report до кода |
| Helper | `load_card_embeddings` | topic→anchor→missing |
| 3 sites | link_topics, finalize, Phase 3 | batch, no N+1 |
| AC-A | hook fix: embed before Phase 3 | scheduler or inline re-embed |
| AC-B | global link_topics pre-flight | coverage ≥95% or backfill |
| AC-C | settings threshold wiring | dispatch + link_topics |
| Threshold | `cross_channel_link_threshold` | data-driven + .env.example |
| Merge 0.6 | watch or change | documented in PR |
| Deploy | отдельно от S1–S3 | 24h watch, T1 OK |
| S4b | HNSW | deferred |
</recap>

---

*Строки кода — по рабочей копии 2026-07-11. Self-review плана S4 (2026-07-11): patch-list incorporated. Self-review промпта (2026-07-11): AC-A исправлен (Phase 3 сейчас ДО embed — нужен hook fix); добавлен AC-C (settings wiring); stale audit уточнён; full_resume gate для 0.6.*
