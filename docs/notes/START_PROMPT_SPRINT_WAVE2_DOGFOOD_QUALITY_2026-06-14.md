# START PROMPT — Wave 2 Sprint: Dogfood-Quality (F5-B + Bot UX hygiene + F5-C P2 freshness)

> # ⛔ IMPLEMENTED / CLOSED — DO NOT EXECUTE as an implementation sprint (banner 2026-07-20)
>
> **Этот спринт УЖЕ реализован.** Не запускать как implementation-сессию.
> - **T1 F5-B Phase 0 · T3 · T4 · T5 · T7 F5-C P2 → shipped `b294b05`** (2026-06-14; closes #39/#40/#41).
> - **T6 gated watchlist alert → shipped `eead91e`** (2026-06-18) — больше **не** deferred (см. §T6 ниже).
> - **Единственный residual = T2 F5-B Phase 1 → go/no-go decision only** (не build). GATED per [ADR-0016](../adr/0016-near-duplicate-dedup.md): Phase-0 наблюдение (S0 2026-07-07) даёт near-dup **intra ≈ 2, cross = 0 за 7д ≪ 5% gate** → при формальной оценке скорее **Reject — rate below threshold**. Если когда-либо перезапускать — использовать тонкий ADR-0016-prompt для одного go/no-go, **не** весь этот спринт.
> - **July closed work (НЕ переоткрывать):** remediation S0–S7, F9 Phase 2–3, Phase-1 watch t2 FINAL (automation DISABLE), BUG-085 + B1/B2 (`ca80dba` / PR #331, deployed 2026-07-19). Форвард-состояние: [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md).
> - **Baseline-цифры / HEAD / line-anchors ниже — ИСТОРИЧЕСКИЕ** (2026-06-14). Re-baseline, если документ когда-либо переиспользуется.

**Дата создания:** 2026-06-14 · **Для:** новой (свежей) **реализационной** сессии в отдельном окне.
**Goal (одной строкой):** реализовать combo internal-quality-контракта Wave 2 — **F5-B near-duplicate dedup (Phase 0 counter intra+cross → gated Phase 1)** + **Bot UX hygiene (TD-D-01/02/03)** + **F5-C P2 evolving topic-summaries freshness (#15 item #4 time-based trigger + item #10 per-channel re-summarize metric)** — по утверждённым в planning-сессии методам (методы НЕ переоткрывать).

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** branch `main` (HEAD на момент написания ~`c0e51e2` — **исторический**; Wave 2 landed `b294b05`); `git commit` и деплой — **только по явному запросу пользователя**; `docs/methodology/**` — не трогать; `pyproject.toml`/`requirements.txt` — не трогать без явного запроса. Принцип: **метод уже выбран в planning → сначала подтверждаем якоря в коде, потом код**. Scope строго по задачам ниже; unrelated-код не задевать.

> **Метод-источник (нормативный вход — НЕ переоткрывать):** [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4 (method-selection T1–T5 + T7; §4a deferred old-T6) + decision-log §3 (6 forks). Каждая задача ниже ссылается на свой §4-блок.

---

## 0. Контекст — почему этот контракт

Wave 1 закрыт полностью (product+ops `v4.4.0` + tech-debt Wave A–C; zero actionable debt кроме deferred BUG-008). Wave 2 planning-сессия (2026-06-14) свериться с Wave 1.5 signal-state: **2A/2B/2C = 0/0/0, ни один Decision-Point threshold не достигнут; owner активно использует** (KB вырос ~2× с baseline: 11 618 docs / 745 topics / 1052 links). → Решение: **continue dogfooding → A1 internal-quality** (не публичные 2A/2B/2C плечи). Контракт = **combo** quality+bot-UX+freshness треков (прецедент Living-KB A+B+C / Wave 1 product‖tech-debt). Подробное обоснование — PLAN §1–§3.

**Selected tasks (этот спринт):** T1 F5-B Phase 0 (intra+cross) · T2 F5-B Phase 1 (gated) · T3 TD-D-02 · T4 TD-D-01 (rich deterministic) · T5 TD-D-03 · **T7 F5-C P2 freshness (#15 item #4 time-based + item #10 per-channel metric)**.
**Out of scope (parking-lot, НЕ трогать):** gated watchlist score alert (old T6 — **✅ SHIPPED `eead91e`**; historical: было deferred на planning-этапе), Wave E graph, F5-C P2 backlog-пункты #15 кроме time-based (#4) и per-channel метрики (#10) — т.е. TTL, diff-API, F6 topic-digest, Bot-tools, type-promotion, topic-dedup, item-removal, HTTP API остаются в #15-backlog, S4 multilang, F1 Full, F11 HTTP CRUD, webhook 2A (ADR-0008 webhook остаётся deferred), BUG-008 root-cause (monitor-only через lifecycle-логи).

**Рекомендуемый порядок:** T1 → (T7 ‖ T3+T4 ‖ T5) → собрать Phase-0 данные ≥7д (обе оси) → решение по T2.

---

## 1. Baseline-прогон ПЕРЕД любым кодом (нормативно)

> **[Historical floor — re-baseline if ever reused]** Число **3289 passed** — это baseline на 2026-06-14. Suite с тех пор существенно вырос (июль: remediation S0–S7 → `TEST_POSTGRES=1` уже **3857+ passed**, см. BUG-084 update 2026-07-13). Не использовать 3289 как floor — если документ когда-либо переиспользуется, снять свежий baseline.

Вне sandbox, `required_permissions: all`:

```
TEST_POSTGRES=1 .venv/bin/python -m pytest -q
```

Ожидаемый baseline *(исторический, 2026-06-14, после BUG-008 mitigation)*: **3289 passed / 20 skipped / 2 deselected** (`BUG_LOG.md` BUG-008 update 2026-06-14). Любой pre-existing fail/skip-дрейф — зафиксировать ДО изменений. После каждого трека — re-baseline; новый fail/skip = блокирующий.

---

## T1 — F5-B Phase 0: near-duplicate observation-only counter

**Метод (утверждён, PLAN §4 T1, вариант B — две оси):** post-processing observation против sliding-window last-N, pgvector `<=>` cosine, **observation-only** (НЕ блокирует, НЕ мутирует), **по двум осям — intra-channel + cross-channel**. «Почему B + обе оси»: data-readiness без риска регрессии hot-path (отвергнуты A pre-pipeline / C offline batch); MCP-снимок (10 моно-тематических каналов, covid-19 в 5, 916 keyword-overlap'ов, 1052 cross-channel link) делает felt-дубликацию **скорее cross-channel** → измерять только intra = риск измерить не ту ось и выдать ложный «dedup не нужен» вердикт.

### Scope
- **IN:** новый counter `{dimension="intra"|"cross"}` + histogram + structlog-событие; хук после embedding нового `ProcessedDocument`; sliding-window сравнение **по двум осям** — (a) intra: last-N того же `channel_id`; (b) cross: last-N недавних документов sibling-каналов того же workspace/темы.
- **OUT:** любое скрытие/удаление/мутация документов (это Phase 1 / T2) — cross-channel путь тоже **observation-only** в Phase 0.

### Якоря в коде (проверить — строки могли сдвинуться)
- Existing exact-hash dedup (паттерн-прецедент): `tg_parser/processing/pipeline.py:270` (single), `:837` (batch); `find_by_content_hash` в `tg_parser/storage/sqlalchemy/processed_document_repo.py` (port `storage/ports.py:550`).
- Existing dedup-метрика: `tg_parser/api/metrics.py:54` (`DEDUP_DUPLICATES_DETECTED`), helper-инкремент `:455`.
- Embedding-hook в incremental tick: искать `run_topic_embedding` / embedding-write путь (рядом с hook'ом F5-C `run_watchlist_check_for_channel`, ADR-0006 #5).
- pgvector: embeddings table + `<=>` оператор (используется в `services/retrieval_service.py`).
- Cross-channel: sibling-каналы того же workspace/темы — выбрать состав окна (workspace-membership vs тематика); cross-window остаётся observation-only.

### Контракты / ADR
- [ADR-0016](../adr/0016-near-duplicate-dedup.md) (Phase 0 раздел) — `Proposed`.
- [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #3 (cheap retrieval, no LLM) / #6 (observability) / #7 (graceful: embedding отсутствует → skip).
- **Не трогать** `docs/contracts/processed_document.schema.json` (только метрика, не поле).

### Test strategy
- **Happy (intra):** документ near-dup (cosine ≥0.92) предыдущего в том же канале → counter{dimension="intra"} +1, histogram observed, structlog с обоими `source_ref` + dimension.
- **Happy (cross):** документ near-dup материала из sibling-канала того же workspace/темы → counter{dimension="cross"} +1, structlog с обоими `source_ref` + dimension.
- **Edge:** ровно на пороге; last-N окно границы; первый документ канала (нет соседей) → no-op; нет sibling-каналов → cross-путь no-op.
- **Negative:** embedding отсутствует → skip без ошибки; каналы вне общего workspace/темы не сравниваются по cross-оси.
- Pure-mock unit где можно; PG-gated для repo-пути.

### DoD (Phase 0)
- Counter `tg_dedup_near_duplicates_detected_total{channel_id, method="embedding_cosine", dimension="intra"|"cross"}` + histogram similarity; structlog `near_duplicate_observed` (+ `dimension`).
- observe-only (обе оси): ни один существующий тест ingestion/processing не меняет поведение.
- ruff чисто; re-baseline зелёный (+N новых).
- **Закрывающая строка** в [`BUG_LOG.md`](BUG_LOG.md) / [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) §C (F5-B Phase 0 landed); запись в ADR-0016 «Phase 0 implemented, собираем rate».

---

## T2 — F5-B Phase 1: near-duplicate dedup (GATED) — **RESIDUAL: go/no-go decision only**

> **⚠️ UPDATE 2026-07-20:** T2 — **единственный незакрытый пункт Wave 2**, и он остаётся **решением, а не задачей на реализацию**. Phase-0 counter уже собран: S0-наблюдение (2026-07-07) → near-dup **intra ≈ 2, cross = 0 за 7д ≪ 5% gate**, т.е. при формальной оценке гейт → **Reject — rate below threshold** (ADR-0016 Phase 1 закрывается, Phase-0 counter остаётся permanent observability). Если решено перезапустить оценку — сделать её тонким go/no-go по [ADR-0016](../adr/0016-near-duplicate-dedup.md), **не** этим спринтом. Build-инструкция ниже применяется **только** если owner на данных откроет gate.

> **GATE:** строить ТОЛЬКО если T1 counter за ≥7 дней показал near-dup rate **≥5% по доминирующей оси** (`dimension`); scope Phase 1 (intra / cross / both) выбирает пользователь из реальной distribution. Иначе — зафиксировать «rate низкий по обеим осям, Phase 1 не нужен», counter остаётся permanent observability, ADR-0016 → `Rejected — rate below threshold`. Решение принимает пользователь по данным.

**Метод (утверждён, PLAN §4 T2, вариант B):** post-processing consolidation: append-only `near_duplicate_links` + soft-hide flag (reversible) + **canonical-pick = earliest-by-date** + **transparency «свёрнуто N»**. Отвергнут pre-pipeline hard-filter (необратим, теряет provenance).

### Scope
- **IN:** таблица `near_duplicate_links(source_ref_a, source_ref_b, similarity, method, dimension, detected_at)` (append-only, UPSERT DO NOTHING); **canonical-pick = A (earliest by published date)** — keep ранний, soft-hide более поздний; **детерминистический tie-break** при равных timestamp'ах по `source_ref`/`message_id` (идемпотентность, ADR-0006 #4); pgvector `<=>` ANN + sliding-window last-N (bound O(N²)); cascade-skip на F11/F6; Pydantic-модель + Alembic + JSON-schema; **transparency**: affordance «свёрнуто N» с разворотом, collapsed-копии **отсортированы по дате** + **подписаны source-каналом**.
- **OUT:** hard delete; silent hiding (всегда «свёрнуто N» + reversible); «A + superset guard» refinement (отложен out of MVP ради детерминизма); canonical-правила B/C/D/E (отвергнуты, см. PLAN §4 T2).

### Якоря / контракты
- Новое: `docs/contracts/near_duplicate_link.schema.json` (ADR-0006 #1 columns-not-metadata); Pydantic в `tg_parser/domain/models.py`; репо + Alembic-миграция; хук рядом с T1.
- Cascade: `tg_parser/services/watchlist_service.py` (check_interests путь), digest-сервис.
- [ADR-0016](../adr/0016-near-duplicate-dedup.md) созревает Draft→**Accepted** в этой сессии (зафиксировать threshold + доминирующую ось из Phase-0 distribution; canonical=earliest + «свёрнуто N» transparency).

### Test strategy
- Happy: near-dup → link записан, **более поздний** soft-hidden (canonical = earliest by date), оба ref сохранены; «свёрнуто N» affordance видим.
- Edge: re-run pipeline идемпотентен (UPSERT DO NOTHING, повтор не плодит links); soft-hide reversible; **равные timestamp'ы → детерминистический tie-break по `source_ref`/`message_id`** (canonical стабилен между прогонами); разворот «свёрнуто N» сортирует по дате + подписывает source-каналом.
- Negative: false-positive guard (независимые новости не консолидируются ниже threshold); embedding down → fallback exact-hash.
- Cascade: near-dup B уже-matched A → skip B как duplicate evidence (explicit test).
- Прецедент по объёму: ~300–500 LOC, ~25–35 тестов (FUTURE_FEATURES F5-B estimate).

### DoD (Phase 1)
- Schema + migration (upgrade/downgrade) + Pydantic + repo + хук + cascade + «свёрнуто N» surface (разворот, sort-by-date, source-label).
- ADR-0016 → Accepted с зафиксированным threshold + доминирующей осью + canonical=earliest + transparency.
- self-review тестов; re-baseline зелёный; ruff чисто; закрывающие строки BUG_LOG + WAVE1_TECH_DEBT §C.

---

## T3 — TD-D-02: pagination_pending coverage ([#40](https://github.com/AlexEfimov/TG_parser/issues/40))

**Метод (утверждён, PLAN §4 T3, вариант B):** shared контракт-helper применён ко всем paginated read-tools симметрично (bot + mcp_server). Отвергнут per-tool bespoke (дублирование/drift).

### Scope
- **IN:** распространить `pagination_pending` контракт на все paginated read-tools; contract-test на shape.
- **OUT:** изменение pagination UX-семантики (Session D `PaginationFlow` остаётся).

### Якоря (проверить строки)
- Эталон (единственный сейчас): `_exec_list_topics` `tg_parser/bot/tools.py:1905`, штамп `pagination_pending` `:1973`.
- Подвести: `_exec_list_channels` `:2040`, `_exec_list_digests` `:3637`, `_exec_list_watchlists` `:4155`, плюс `list_users`. **⚠️ ПОПРАВКА 2026-07-20:** `get_cross_channel_stats` **НЕ** подводится под `pagination_pending` — в реализации (`b294b05`) он **явно исключён** (MCP `mcp_server.py:56` «`get_cross_channel_stats` is excluded»): это агрегатная аналитика, а не листинг элементов, поэтому pagination-контракт к нему неприменим. Не добавлять.
- Bot replay/arm: `handlers.py:775` (arm), `:1198`/`:1317` (nested pagination), `_handle_pagination_response`; `agent.py:109,206,463` (`pagination_pending` проброс).
- MCP симметрия: `tg_parser/mcp_server.py` соответствующие list-tools.
- Прецедент BUG-004 root-cause: `BUG_LOG.md:1264` (Session D).

### Контракты / ADR
- [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #4 (идемпотентный детерминированный replay).
- `pagination_pending` shape: `{tool_name, args(сохраняет фильтр + advanced offset), total, offset, limit}`.

### Test strategy
- Happy per-tool: `has_more=True` → корректный `pagination_pending`; replay следующей страницы сохраняет channel/filter context.
- Edge: terminal page → clear; soft-cap после 10 cumulative (D-6).
- Negative: «стоп» → clear; non-match → D-4 default.
- Contract-test: enumerate все paginated read-tools → assert pagination_pending shape (ловит новый paginated tool без контракта).

### DoD
- Все paginated read-tools (bot + mcp) подведены под контракт; contract-test зелёный.
- re-baseline; ruff; закрывающая строка TD-D-02 в BUG_LOG (#40) + WAVE1_TECH_DEBT §C.

---

## T4 — TD-D-01: renderer unification ([#39](https://github.com/AlexEfimov/TG_parser/issues/39))

**Метод (утверждён, PLAN §4 T4, вариант 4b — rich deterministic):** promote `_format_paginated_list` на page 1 **И** обогатить сам детерминистический форматтер (headers/emphasis/structure) → результат И консистентен между страницами, И хорошо отформатирован. Подход остаётся **детерминистическим** (не LLM-prompt), просто с богатым шаблоном. Отвергнуты: A (strengthen prompt — LLM-nondeterminism, fragile), 4a (promote as-is — беднее текущего рендера). **Делать вместе с T3** (общий рендер-путь).

### Scope
- **IN:** page 1 paginated list рендерится тем же детерминистом, что page 2+; consistent numbering `n` (`offset+idx+1`); **обогащение детерминистического форматтера** (headers/emphasis/структура) — единый rich-шаблон для page 1 и page 2+.
- **OUT:** LLM-prompt-рендер page 1 (заменяется детерминистом); расхождение шаблонов page1 vs page2+ (единый форматтер).

### Якоря
- `_format_paginated_list` `tg_parser/bot/handlers.py:1374`.
- LLM-render path page 1 (заменяемый): `_format_read_result` `:1480`; prompt list-render инструкция в `prompts/bot.yaml` (§ implicit-context, ~line 73 по BUG_LOG narrative).

### Контракты / ADR
- [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #6 (предсказуемый вывод).
- **Prompt-version bump** `prompts/bot.yaml` ОБЯЗАТЕЛЕН, если ослабляется/убирается free-form list-render инструкция (bot write-surface). Обновить version-floor guard (`tests/test_bot_read_context.py`) — текущий floor по последней версии (после Wave C — v1.7.9).

### Test strategy
- Happy: page 1 и page 2 рендерятся идентичным форматом; numbering не рестартует.
- Regression: visual-jump устранён (snapshot формата page 1 == page 2 шаблон).

### DoD
- Детерминистический page-1 рендер; prompt-bump + version-floor guard обновлён; re-baseline; ruff; закрывающая строка TD-D-01 (#39).

---

## T5 — TD-D-03: `_format_tool_result` fallback + contract-test ([#41](https://github.com/AlexEfimov/TG_parser/issues/41))

**Метод (утверждён, PLAN §4 T5, вариант B = оба):** synthesize информативный fallback + contract-test «все write-tools возвращают non-empty `message`».

### Scope
- **IN:** `_format_tool_result` синтезирует fallback из `channel_id`/`id`/`status` вместо `"✅ Готово: {tool_name}."`; contract-test enumerating write-tools.
- **OUT:** изменение успешных `message`-возвратов существующих tools.

### Якоря
- `_format_tool_result` `tg_parser/bot/handlers.py:1428` (слабый fallback).
- Canonical список write-tools: `_WRITE_TOOLS_REQUIRING_CONFIRM` + декларации `tg_parser/bot/tools.py` (переиспользовать, не дублировать).

### Контракты / ADR
- [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #6/#7 (новый write-tool не «молчит»).

### Test strategy
- Happy: write-result без `message` → синтезированный информативный fallback (не generic).
- Contract: enumerate все write-tools → assert non-empty `message` (CI-time guard вместо silent prod-degradation).

### DoD
- Fallback + contract-test зелёный; re-baseline; ruff; закрывающая строка TD-D-03 (#41).

---

## T7 — F5-C P2: evolving topic-summaries freshness ([#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #4 + item #10)

**Метод (утверждён, PLAN §4 T7):** два среза issue #15.
- **#4 — time-based trigger (вариант A):** расширить `list_resummarize_candidates` вторым предикатом (`last_summarized_at < NOW() - INTERVAL 'RESUMMARIZE_MAX_AGE_DAYS days' AND new_items_since_last_summary > 0`), gated на новом env `RESUMMARIZE_MAX_AGE_DAYS` (0/None = disabled → MVP bit-for-bit). Отвергнуты: B (отдельный CRON/scheduler-pass — дублирует cap-логику, новый surface), C (понизить `RESUMMARIZE_TRIGGER_N` глобально — грубо).
- **#10 — per-channel re-summarize metric (вариант A′):** пробросить реальный `channel_id` в уже-зарезервированный label `tg_resummarize_total{channel_id}` (сегодня хардкод `"-"`) через `record_resummarize_outcome`; канал из `card.sources[0]`, fallback `"-"` когда неизвестен. Отвергнуты: B′ (отдельная новая метрика — дубль зарезервированного label), C′ (оставить `"-"` — нет per-channel cost-видимости). **Rationale:** #10 — дешёвый observability-компаньон к #4 (time-based триггер повышает re-summarize volume/cost → per-channel breakdown даёт owner'у видимость для тюнинга `RESUMMARIZE_MAX_AGE_DAYS`; закрывает karpathy observability-loop ADR-0006 #6); marginal cost ~0 (label уже зарезервирован).

**Строит на shipped F5-C P1** (PR #14, tag `f5c-mvp-2026-04-26`).

> **Pinned MVP scope = issue #15 item #4 (Time-based trigger) + item #10 (per-channel metric).** Issue #15 — tracking-issue с 10 backlog-пунктами; для combo-формы пиннятся два самых user-facing × дешёвых × freshness среза (#4 + #10). **Exact phase-2 boundary per issue #15** — остальные 8 пунктов (TTL, diff-API, F6 topic-digest, Bot-tools, type-promotion, topic-dedup, item-removal, HTTP API) остаются в #15-backlog, OUT этого спринта.

### Scope
- **IN (#4):** новый env `RESUMMARIZE_MAX_AGE_DAYS` (default 0/disabled; prod-старт консервативно ~14д, согласован со stale-detector #15 «>14 days»); второй предикат в `list_resummarize_candidates` (OR time-based, **сохранить `AND new_items_since_last_summary > 0`** → остаётся под partial-index); re-use существующего triple-cap + advisory-lock + `commit_resummary`-пути.
- **IN (#10):** реальный `channel_id` в `tg_resummarize_total{channel_id, outcome}` — добавить kwarg `channel_id` (default `"-"`) в `record_resummarize_outcome`, передавать `card.sources[0]` с happy/commit-путей; на путях без card (`locked`/`no_card`/`no_bundle`) — fallback `"-"`. Per-channel cost-breakdown вместе с `tg_resummarize_tokens_total`.
- **OUT:** замена counter-триггера (time-based — **дополнение**, не замена — issue #15 non-goal); все прочие 8 пунктов #15; изменение append-only-инварианта `topic_card_versions`; промпт `resummarize.yaml` (без version-bump — триггер отбора, не промпт); новая метрика под #10 (re-use существующего label, НЕ заводить отдельную).

### Якоря в коде (проверить — строки могли сдвинуться)
- Candidate-query: `list_resummarize_candidates` `tg_parser/storage/sqlalchemy/topic_card_repo.py:200` (SQL WHERE `:217`, ORDER `:222`); port `tg_parser/storage/ports.py:671`.
- Service: `ResummarizationService.run_for_channel` `tg_parser/services/resummarization_service.py:101` (threshold-выбор `:124`, candidate-выборка `:135`); `resummarize_topic` `:203`; источник канала `card.sources[0]` `:402`.
- Scheduler-hook (без нового surface): `tg_parser/services/scheduler_service.py:272` (`run_resummarize_for_channel`), factory `:624`, `ResummarizationService(...)` `:657`.
- Env/settings: `tg_parser/config/settings.py:609` (`resummarize_trigger_n` — рядом добавить `resummarize_max_age_days`); `.env.example:221`.
- Partial-index: `idx_topic_cards_resummarize_candidates` (`storage/sqlalchemy/_metadata.py:649`, migration `migrations/versions/processing/20260426_add_topic_card_versions.py:81`).
- **#10 метрика:** counter `tg_resummarize_total` `tg_parser/api/metrics.py:153` (label `channel_id` `:157`, «always "-"»-комментарий `:160`–`:164`); `record_resummarize_outcome` `tg_parser/api/metrics.py:272` (хардкод `channel_id="-"` `:287`); токены `tg_resummarize_tokens_total` `:167`. (опц. доп. label trigger=counter|age для #4-tuning).

### Контракты / ADR
- [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #5 (living loop, тот же hook) / #6 (observability → tuning; #10 = per-channel cost-видимость).
- **Нет новой JSON-schema** (нет новой persistent-сущности — только env + query-предикат для #4; #10 re-use существующей `tg_resummarize_total`, label `channel_id` уже объявлен).
- Новый env → задокументировать в `ENV_VARIABLES_GUIDE.md` / `.env.example` / `PRODUCTION_DEPLOYMENT.md` (рядом с `RESUMMARIZE_TRIGGER_N`).

### Test strategy
- **Happy (#4):** тема `new_items < TRIGGER_N` но `last_summarized_at` старше `MAX_AGE_DAYS` и `new_items > 0` → попадает в candidates → re-summarize; version-snapshot append (provenance) + counter reset + `last_summarized_at` bumped.
- **Happy (#10):** успешный re-summary канала C → `tg_resummarize_total{channel_id="C", outcome="ok"}` +1 (реальный `channel_id`, НЕ `"-"`); токены атрибутированы.
- **Edge:** тема старая, но `new_items = 0` → НЕ кандидат (guard, не трогаем unchanged); ровно на границе age; `MAX_AGE_DAYS=0` → поведение bit-for-bit как MVP (counter-only).
- **Negative (#4):** `RESUMMARIZE_ENABLED=false` → no-op; LLM down → existing `llm_error` outcome; explain-проверка что запрос едет на partial-index (не full-scan).
- **Negative/cardinality (#10):** канал неизвестен (нет card — `locked`/`no_card`/`no_bundle`) → fallback `channel_id="-"`; cardinality ограничена фиксированным набором каналов (10 active) → приемлемо, fallback `"-"` не плодит безграничных серий.
- PG-gated для repo-query; mock для service-уровня; pure-unit для metrics-инкремента #10.

### DoD
- Env + расширенный `list_resummarize_candidates` (под partial-index) + реальный `channel_id` в `tg_resummarize_total` (#10) + опц. метрика-label trigger; default disabled → MVP-baseline не дрейфует.
- re-baseline зелёный (+N); ruff; env задокументирован; закрывающая строка в BUG_LOG + ROADMAP/CHANGELOG (F5-C P2 freshness landed, #15 item #4 + item #10 per-channel metric); запись «exact phase-2 boundary per issue #15 (item #4 + #10), остальные 8 пунктов — backlog».

---

## T6 — Gated watchlist score alert (BUG-060 follow-up) — **✅ SHIPPED `eead91e` (2026-06-18)**

> **⚠️ UPDATE 2026-07-20:** T6 **shipped** — реализован в `eead91e` (2026-06-18) как вариант B (dedicated counter `tg_watchlist_semantic_unavailable_total{reason}` + alert `WatchlistSemanticUnavailableHigh`), ровно по сохранённому методу. Уже **не** deferred. См. [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md` §1.1](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md). Текст ниже — исходный historical framing.

> **[Historical framing] Перенесён в deferred (swap T6 → T7, PLAN §3 Fork 4 + §4a).** **Non-blocking:** watchlist-matching уже деградирует gracefully в keyword-only (`combined=1.0`, ADR-0010/0011) — ничто не ломается без alert'а; monitoring blind-spot, не дефект; ничего от него не зависит. **Оптимальное время pickup:** когда в следующий раз тронут `tg_parser/services/watchlist_service.py:565` (scoring-путь) или metrics/alerts surface (не платить за context-paging дважды), и когда watchlist-quality станет нужен non-owner-пользователям (внешние validator'ы Wave 1.5). **Метод сохранён в PLAN §4a** (вариант B: dedicated counter `tg_watchlist_semantic_unavailable_total{reason}` + gated alert на ratio; `semantic_available` уже в `watchlist_service.py:565`; alert в `docker/prometheus/alerts.yml`). НЕ реализовывать в этом спринте.

---

## 8. Общий DoD реализационной сессии (нормативно)

- [ ] Каждая задача: метод **как утверждён в PLAN §4** (не переоткрывать); scope соблюдён (in/out).
- [ ] **Self-review тестов** (happy/edge/negative по каждому треку); прецедент объёма: F5-B Phase 1 ~25–35 тестов, TD-D трек ~15–25, F5-C P2 freshness ~8–12.
- [ ] **Полный прогон вне sandbox:** `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` (`required_permissions: all`). Baseline **3289 passed / 20 skipped / 2 deselected**; suite вырастет — re-baseline; любой новый fail/skip — блокирующий.
- [ ] **ruff** чисто на изменённых файлах.
- [ ] **Prompt-version bump** `prompts/bot.yaml` если задет bot write-surface (T4 — обязателен; T3 — если затронут list-render prompt) + обновить version-floor guard (`tests/test_bot_read_context.py`) и `test_guard_set_matches_known_baseline` (если меняется состав tools).
- [ ] **ADR-0016** Phase 0 → отметка implemented (counter intra+cross); Phase 1 → Accepted с canonical=earliest + «свёрнуто N» transparency + доминирующей осью (или Rejected если gate закрыт по обеим осям).
- [ ] **Закрывающие строки** в [`BUG_LOG.md`](BUG_LOG.md) (TD-D-01/02/03 #39–41, F5-B Phase 0, F5-C P2 freshness #15 item #4 time-based + item #10 per-channel metric) + [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) §C; обновить ROADMAP/CHANGELOG per PLAN §6 (по go-ahead). **[HISTORICAL DoD — все треки закрыты `b294b05`; T6 закрыт `eead91e`; см. верхний баннер.]**
- [ ] **commit + deploy — только по явному go-ahead пользователя.**

---

## 9. Артефакты для контекста (прочитать в начале)

- **Метод-источник:** [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) (§3 forks, §4 methods, §5 sequencing).
- **ADR-stub:** [`docs/adr/0016-near-duplicate-dedup.md`](../adr/0016-near-duplicate-dedup.md).
- **Инвариант:** [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) (7-checklist).
- **Backlog:** [`BUG_LOG.md`](BUG_LOG.md) (TD from Session D :3811; BUG-060; BUG-008 monitor-only), [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) §C, GH issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) (F5-C P2 backlog — T7 source, item #4 time-based + item #10 per-channel metric).
- **F5-A foundation:** `docs/plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md`; `tg_parser/domain/hashing.py`.
- **F5-C P1 foundation (T7 строит на этом):** `tg_parser/services/resummarization_service.py`, `tg_parser/storage/sqlalchemy/topic_card_repo.py` (`list_resummarize_candidates`), `prompts/resummarize.yaml`, MCP `get_topic_versions`/`force_resummarize` (`mcp_server.py:2340`/`:2398`); CHANGELOG § Sprint F5-C.
- **Прецеденты глубины:** [`START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md`](START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md), [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md).
- **Режим:** [`AGENTS.md`](../../AGENTS.md); pytest-режимы [`tests/README.md`](../../tests/README.md).

---

## 10. Стартовая реплика для реализационной сессии (⛔ HISTORICAL — НЕ ИСПОЛЬЗОВАТЬ)

> ⛔ **Этот блок — исторический. НЕ копировать как старт спринта:** Wave 2 combo (T1/T3/T4/T5/T7) реализован `b294b05`, T6 — `eead91e`. Единственный residual — T2 F5-B Phase 1 go/no-go (см. верхний баннер §T2). Реплика ниже сохранена только как запись исходного плана.

> Берёмся за **Wave 2 Sprint: Dogfood-Quality** — реализация. Прочитай [`docs/notes/START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](docs/notes/START_PROMPT_SPRINT_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) и метод-источник [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](docs/notes/PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) (§4 утверждённые методы — НЕ переоткрывать). Audience driver = continue dogfooding → A1 internal-quality (signal 0/0/0, owner-active). Scope = combo: T1 F5-B Phase 0 counter (intra+cross) → (T7 F5-C P2 freshness #15 item #4 time-based + item #10 per-channel re-summarize metric ‖ T3+T4 pagination coverage + rich-deterministic renderer ‖ T5 fallback+contract-test) → собрать Phase-0 данные ≥7д (обе оси) → решение по T2 F5-B Phase 1 (gated на rate ≥5% по доминирующей оси; canonical=earliest + «свёрнуто N» transparency). Old T6 gated-score alert — **deferred** (non-blocking), не трогаем. Сначала baseline-прогон `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` вне sandbox (ожидаем 3289/20/2), затем подтверждаем якоря в коде, потом код по утверждённым методам. DoD: self-review тестов, re-baseline зелёный, ruff чисто, prompt-version bump если задет bot write-surface (T4 обязателен), ADR-0016 mature, закрывающие строки в BUG_LOG + WAVE1_TECH_DEBT §C. Режим: коммит/деплой — только по моему явному запросу; `docs/methodology/**`, `pyproject.toml`/`requirements.txt` не трогать.
