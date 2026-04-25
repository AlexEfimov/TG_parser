# Следующая сессия — F11 (дожим PR) и хвост living-KB

**Назначение:** стартовый промпт для агента/разработчика, который продолжает **Sprint F11 — Topic Watchlist** или закрывает PR после частичной реализации. Не заменяет полный спек — читать в первую очередь [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md).

**Дата подготовки:** 25 апреля 2026 (дополнение к промпту от 19 апреля 2026).

**Предусловие по продуктовому плану:** F11 в голове очереди после **Sprint D.1** (topicization hardening). См. [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) (таблица волн / строка про F11 «после D.1») и зафиксированный порядок **D.1 → F11 → F5-C** в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) (блок «Пересмотр приоритета» / rationale: watchlist опирается на нормальную topicизацию и `topic_cards`).

**Долгосрочный ориентир karpathy-like / Living KB** (волны B–F, принципы, что не входит в ближайшие PR): [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md).

---

## Что открыть в первые 5 минут

0. [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — **один экран контекста**: где F11 сидит в дорожной карте living KB и что после него (F5-C, метрики, Phase 2 watchlist, F5-B, граф).
1. [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — MVP scope, «Не входит в сессию», шаги 1–11, Risks, rollback, **Hidden gotchas** (пустой embedding, cosine `<=>`, idempotency, hook **после** topicization).
2. [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) — **чеклист для тела PR**: те же критерии, что в конце спринт-промпта, плюс **karpathy-like** пометки; строки **переупорядочены** по коммитам 1/2 · 2/2 (см. примечание в шапке файла).
3. [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § F11 — продуктовый дизайн, схема потока, mockup уведомлений; сверять с MVP (instant-only, MCP/bot/CLI без HTTP API).
4. [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) — после F11 следующая крупная фича в волне: **F5-C** (Evolving Topic Summaries).

---

## Karpathy-like север (не расширять scope PR)

Цель F11 в этом PR — не «ещё одна нотификация», а тонкий **личный слой поверх living KB**:

| Идея | Реализация в MVP F11 |
|------|----------------------|
| Персистентный user-defined объект | `watch_interests` + embedding в pgvector |
| Evidence / provenance | `watch_matches` с `keyword_score`, `semantic_score`, `combined_score`, `source_ref` |
| Дешёвый retrieval на потоке новизны | `compute_watch_score`: keyword + cosine, **без** LLM на документ |
| Идемпотентность | `UNIQUE(interest_id, source_ref)` + `ON CONFLICT DO NOTHING` |
| Digest, а не спам | group by `interest_id` перед `Bot.send_message` |
| Устойчивость пайплайна | scheduler hook **после** topicization; `try/except` — watchlist не валит tick |
| Деградация без topicization | если topicization упала, матчинг всё ещё возможен по доступным полям документа (graceful degradation; см. gotcha #10 в спринт-промпте) — **не** блокировать tick |
| Деградация доставки | «Chat not found» и др.: не валить pipeline; soft-disable interest + лог (Risks в спринт-промпте) |
| Наблюдаемость (желательно) | метрика с `score_bucket` из раздела Risks исходного промпта |
| DI без синглтонов | `WatchlistService` через провайдер/конструктор, как `digest_service` (Шаг 6 спринт-промпта) — тестируемость |

**Запрещено в этом PR** (Phase 2): `notify_mode=batch/silent`, LLM-matching на каждый документ, HTTP `/api/v1/watchlists`, workspace-scoping интересов — см. исходный промпт.

**Порог по умолчанию:** в коде и доках — **0.6** (спринт-промпт); в § F11 `FUTURE_FEATURES.md` в примере может быть 0.7 — не путать с production default.

---

## Порядок работы в сессии

1. **Pre-flight** — команды из «Pre-flight» в [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md); убедиться, что ingestion Alembic head известен и CI на целевой ветке зелёный.
2. **Состояние ветки** — если уже есть коммит 1/2: не переписывать миграцию без крайней нужности; довести коммит 2/2 + доки + тесты.
3. **Чеклист PR** — закрывать пункты из [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) по мере мержа; текст чеклиста копировать в GitHub PR description.
4. **Качество** — перед каждым `git commit`: `ruff format` / `ruff check` на затронутых файлах (урок спринтов A–A.7 в исходном промпте).
5. **Верификация** — `pytest`, `tg-parser db check --db ingestion` / `upgrade` по инструкции спринт-промпта; при наличии — `TEST_POSTGRES` для интеграции. **Embedding в тестах** — мокировать `EmbeddingService`, не жечь токены (gotcha #1 в спринт-промпте).

---

## После merge F11 (не в этом PR, ориентир следующих спринтов)

Полная раскладка **волн** (B–F), принципов и границ scope: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md). Ниже — краткий список; детали порога F5-B, DI-5/DI-20 — в [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) § «После F11».

1. **F5-C — Evolving Topic Summaries** — темы «помнят» новый материал (re-summarize / re-embed по порогу N новых supporting items); **связка с F11:** watchlist даёт поток новых `source_ref` с scores — F5-C переводит это в обновляемое содержание `TopicCard`.
2. **Метрики и тюнинг** — смотреть распределение `score_bucket` / шум; править дефолты и документацию, а не сразу LLM.
3. **Phase 2 watchlist** — только при сигнале: `batch` через digest-инфраструктуру, `silent` как «только журнал».
4. **F5-B dedup** — после метрик near-duplicate (`tg_dedup_duplicates_detected_total` и т.п., см. § «После F11» в спринт-промпте); чище корпус фактов → меньше мусорных алертов.
5. **Более богатый граф связей (typed edges, cross-channel)** — только отдельными инициативами после стабилизации F5-C и метрик watchlist; в текущей [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) это не отдельный пункт «K2», а логическое продолжение living-KB после F11/F5-C.
6. **DI-5 / DI-20** — ops и опциональные guardrails из того же § «После F11» спринт-промпта, не смешивать с кодом F11 в одном PR.

---

## Definition of Done для этой сессии

- Все пункты «После обоих коммитов» в [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) отмечены выполненными.
- PR description содержит чеклист из того файла (можно свернуть блок `<details>` в GitHub).
- В [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) и [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) отражены статус F11 и указание на **F5-C** как следующий шаг.

---

## Связанные артефакты

| Файл | Роль |
|------|------|
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Roadmap внедрения karpathy-like подхода (волны 0–F, связь с F11/F5-C/Roadmap v3). |
| [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) | Полный спек F11 (шаги, DDL, сервис, тесты, риски). |
| [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) | Чеклист для GitHub PR + karpathy-like пометки. |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | Продуктовый § F11. |
| [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | Порядок релизов. |
