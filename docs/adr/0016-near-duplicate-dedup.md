# ADR 0016 – Near-duplicate content dedup (embedding-similarity поверх F5-A exact-hash)

## Статус

**Phase 0 — Implemented (2026-06-14). Phase 1 — `Rejected — rate below threshold` (2026-07-20, gate closed on data).**

- **Phase 0 (observation-only counter, обе оси intra+cross) — РЕАЛИЗОВАНА** в Wave 2 implementation-сессии (T1). Post-embedding хук в incremental scheduler tick (`tg_parser/services/near_duplicate_service.py`, вызывается из `scheduler_service._process_source`), метрика `tg_dedup_near_duplicates_detected_total{channel_id, method="embedding_cosine", dimension="intra"|"cross"}` + histogram `tg_dedup_near_duplicate_similarity{dimension}` + structlog `near_duplicate_observed` (оба `source_ref` + similarity + `dimension`). Гейтящие knob'ы: `NEAR_DUP_OBSERVE_ENABLED` (default `true`), `NEAR_DUP_SIMILARITY_THRESHOLD` (`0.92`), `NEAR_DUP_WINDOW_N` (`50`). Observation-only: ничего не скрывает и не мутирует. Покрыто `tests/test_near_duplicate_observe.py`. **Остаётся как permanent observability** (после Reject Phase 1 counter НЕ снимается).
- **Phase 1 (фактический dedup) — `Rejected — rate below threshold` (2026-07-20).** Gate закрыт **на данных**, а не гаданием. Замер (prod Prometheus `increase[90d]`, покрывает всю жизнь observer'а с `b294b05` 2026-06-14 ≈ 36 дней ≫ требуемых 7д; знаменатель — prod Postgres `processed_documents`):

  | Ось | Детекций (cosine ≥0.92) | Docs обработано (с 2026-06-14) | **Rate** | Gate |
  |---|---:|---:|---:|---|
  | **intra** (доминирующая) | 18 | 32 805 | **0.055 %** | ≥5 % |
  | **cross** | 0 | 32 805 | **0.000 %** | ≥5 % |

  Доминирующая ось (intra) ≈ **91× ниже** порога 5 %; cross-ось = ровно 0 %. Разбивка intra: `Docma_ru`=10, `murashko_med`=6, `Lab4health`=2, остальные каналы 0; каждый тик логирует `checked=1–2, intra=0, cross=0`. Гипотеза §Контекст «монокультура 13 health-каналов → high a-priori near-dup, скорее cross» **эмпирически опровергнута**: cross-репостов между каналами по embedding-косинусу ≥0.92 нет вообще, intra — статистический шум. Persistent-сущность `near_duplicate_links` + soft-hide + «свёрнуто N» построением **не оправданы**. **T2 в Wave 2 НЕ реализуется** и не переоткрывается без нового сигнала (напр. смена тематического профиля каналов или устойчивый рост Phase-0 counter, за которым и остаётся наблюдение).

Stub-ADR создан Wave 2 planning-сессией ([`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md` §4 T1/T2](../notes/PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md)); Phase 0 раздел ниже отражает реализованное, Phase 1 раздел — gated draft.

## Контекст

F5-A Phase 3 ввёл **exact-hash** дедупликацию: `ProcessedDocument.content_hash` (sha-256 нормализованного текста, `tg_parser/domain/hashing.py:34`), index `idx_pd_channel_content_hash` (`storage/sqlalchemy/_metadata.py:571`), counter `tg_dedup_duplicates_detected_total{channel_id}` (`api/metrics.py:54`), dedup-хук в pipeline (`processing/pipeline.py:270`, batch-вариант `:837`). Это ловит **точные** re-post'ы.

**Пробел:** near-duplicate — re-post с минимальной правкой текста (эмодзи, хэштег, опечатка) → разный sha-256, но cosine-similarity embedding'ов > 0.92. Сегодня такие проходят как уникальные → шум в темах, дублирующиеся watchlist-алерты, раздувание KB.

**Signal substrate (2026-06-14 MCP-снимок):** 10 моно-тематических health/longevity каналов, 11 618 документов, 916 cross-channel keyword-overlap'ов, 1052 topic-link (avg-sim 0.33). Тематическая монокультура → высокая a-priori вероятность near-dup. На момент draft **фактический near-dup rate не был измерен** (нет метрики) — отсюда обязательная Phase 0 перед Phase 1 (ADR-0006 #6). **Update 2026-07-20:** rate измерен Phase-0 observer'ом → обе оси ≪ 5 % → Phase 1 `Rejected` (см. §Статус); a-priori «скорее cross» эмпирически опровергнута.

## Решение (draft)

Двухфазно:

### Phase 0 — observation-only (РЕАЛИЗОВАНО, T1 Wave 2)
> **Implemented 2026-06-14.** Anchors: `tg_parser/services/near_duplicate_service.py`, hook в `tg_parser/services/scheduler_service.py` (`_process_source`), метрики в `tg_parser/api/metrics.py` (`record_near_duplicate_observed`), env в `tg_parser/config/settings.py` (`near_dup_*`). Реализация совпала с draft'ом ниже; cross-axis window = «все остальные active sources в deployment». *(«точная ось/окно уточняются в Phase 1» — moot: Phase 1 Rejected 2026-07-20; Phase 0 остаётся permanent observability.)*
- Хук после embedding нового `ProcessedDocument`: cosine (`pgvector <=>`) против sliding-window last-N (N≈50) embeddings — **по двум осям:** (a) **intra** — last-N того же `channel_id`; (b) **cross** — last-N недавних документов sibling-каналов того же workspace/темы (cross-channel neighbours).
- При max-cosine ≥ observe-threshold (0.92): `inc()` нового counter `tg_dedup_near_duplicates_detected_total{channel_id, method="embedding_cosine", dimension="intra"|"cross"}` + histogram similarity-distribution + structlog `near_duplicate_observed` (оба `source_ref` + similarity + `dimension`).
- **Ничего не скрывает, ничего не мутирует** (включая cross-channel путь). Цель — измерить rate **по обеим осям** и откалибровать threshold + Phase-1 scope по реальной distribution.
- **Почему обе оси (нормативно):** MCP-снимок (§Контекст / PLAN §1.2 — 10 моно-тематических каналов, covid-19 в 5 каналах, 916 keyword-overlap'ов на 2+ каналах, 1052 cross-channel link) делает felt-дубликацию owner'а **скорее cross-channel** (один материал репостится между каналами), чем intra. Измерять только intra = риск измерить не ту ось и выдать ложный «dedup не нужен» вердикт гейта.

### Phase 1 — consolidation (`Rejected — rate below threshold`, 2026-07-20; исходно GATED на Phase 0 rate ≥5% по доминирующей оси)

> **Gate closed 2026-07-20 → REJECT.** Measured intra 0.055 % / cross 0 % (N=32 805 docs с 2026-06-14) ≪ 5 % — см. §Статус. Метод-запись ниже сохранена как decision-record (что бы строилось, если бы gate открылся); **не переоткрывать без нового сигнала**.
- **Метод (выбран, см. PLAN §4 T2):** post-processing consolidation, **не** pre-pipeline hard-filter.
  - Новая persistent сущность `near_duplicate_links(source_ref_a, source_ref_b, similarity, method, dimension, detected_at)` — append-only, UPSERT `ON CONFLICT (source_ref_a, source_ref_b) DO NOTHING` (ADR-0006 #1 columns-not-metadata, #4 идемпотентность).
  - **Canonical-pick = A (earliest by published date):** keep самый ранний документ, soft-hide более поздний дубль(и). Tie-break при равных timestamp'ах — детерминистический по `source_ref` / `message_id` (требование идемпотентности, ADR-0006 #4). Для cross-channel: «earliest = original source, later = reposts».
  - Soft-hide flag на более позднем документе (reversible, оба `source_ref` сохранены — ADR-0006 #2 provenance).
  - **Transparency (user-facing, нормативно):** dedup **не** скрывает молча — surface показывает affordance «свёрнуто N» с разворотом; в развёрнутом виде collapsed-копии **отсортированы по дате** и **подписаны source-каналом**. Reversible soft-hide + «свёрнуто N» — это то, что де-рискует выбор canonical-pick (ошибка обратима и видима).
  - Cascade на F11/F6: near-dup B уже-matched A → skip B как duplicate evidence (фиксируется в link).
- JSON-schema `docs/contracts/near_duplicate_link.schema.json` + Pydantic-модель + Alembic-миграция.
- **Граница:** ось Phase 1 (intra / cross / both) выбирается из Phase-0 `dimension`-distribution (не угадывается). Cross-channel «одна новость в 2 каналах» больше **не** open-question измерения — она **меряется в Phase 0**; в impl-сессии решается лишь UX-граница («один re-post» сворачиваем vs «независимое освещение» оставляем) на реальных данных.

### Отвергнутые правила canonical-pick (кратко)
- **B latest** — обычно derivative-копия, теряет first-seen provenance. Отвергнут.
- **C richest-content** — fuzzy / недетерминистичен (нарушает #4). Отвергнут.
- **D priority-channel** — требует нового concept'а channel-priority — out of scope. Отвергнут.
- **E engagement** — несравним между каналами, metadata может отсутствовать. Отвергнут.
- **OPTIONAL future refinement «A + superset guard»** (предпочесть более позднюю копию, только если она явный текстовый superset ранней) — **намеренно отложен out of MVP**, чтобы сохранить детерминизм.

## Альтернативы (отвергнуты)

- **Pre-pipeline hard filter** (skip ingest near-dup): теряет provenance, необратимо, нарушает ADR-0006 #2/#7. Отвергнут.
- **Offline all-vs-all batch-скрипт:** O(N²), не living-loop (ADR-0006 #5). Отвергнут как продакшн-механизм (допустим только как one-shot аудит).
- **Label `semantic_available` на чужой метрике** — не относится к dedup (это T6 gated-alert, отдельная развилка).

## Karpathy-like 7-checklist (ADR-0006)

| # | Принцип | Phase 0 | Phase 1 |
|---|---|---|---|
| 1 | Persistent entities | метрика (нет сущности) | ✅ `near_duplicate_links` table (+ `dimension`) + schema |
| 2 | Provenance | оба `source_ref` + `dimension` в логе | ✅ оба ref + similarity + `dimension` в таблице |
| 3 | Cheap retrieval | ✅ cosine, no LLM (intra+cross) | ✅ cosine, no LLM |
| 4 | Идемпотентность | ✅ observe-only | ✅ UPSERT DO NOTHING, append-only; canonical-pick детерминистичен (earliest + tie-break по `source_ref`) |
| 5 | Living loop | ✅ hook после embedding | ✅ hook после embedding |
| 6 | Observability | ✅ counter `{dimension}` + histogram | ✅ + soft-hide counter + «свёрнуто N» affordance |
| 7 | Graceful degradation | ✅ embedding down → skip | ✅ fallback exact-hash (existing); soft-hide reversible |

## Открытые вопросы — CLOSED with Phase 1 Reject (moot)

> Вопросы ниже относились к hypothetic Phase-1 impl-сессии. Gate закрыт `Rejected` (2026-07-20) → **не требуют ответа**, пока не появится новый сигнал на переоткрытие Phase 1. Сохранены как decision-record.

1. Точный observe-threshold (0.92? калибровать по Phase-0 histogram, отдельно для intra и cross).
2. Sliding-window N (50?) — trade-off recall vs cost; cross-channel окно — состав sibling-каналов (workspace vs тема).
3. Phase 1 scope (intra / cross / both) — выбирается из Phase-0 `dimension`-distribution; здесь решается лишь UX-граница «один re-post» vs «независимое освещение».
4. Cascade-семантика на watchlist/digest (skip vs new-evidence).
5. UX «свёрнуто N»: где именно разворот (bot/MCP), сортировка по дате + подпись source-канала.

## Ссылки
- [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](../notes/PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4 T1/T2 (method-selection).
- [`START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](../notes/START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) (impl-промпт).
- ADR-0006 (Living-KB principles), F5-A Phase 3 (`docs/plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md`).
- Code anchors: `tg_parser/processing/pipeline.py:270,837`; `tg_parser/api/metrics.py:54`; `tg_parser/domain/hashing.py:34`; `tg_parser/storage/sqlalchemy/_metadata.py:571`.
