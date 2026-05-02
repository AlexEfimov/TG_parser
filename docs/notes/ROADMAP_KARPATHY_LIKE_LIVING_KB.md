# Roadmap: Karpathy-like подход и Living KB

> **Living-KB contract: CLOSED 2026-04-26**
> (D.1 hardening + F11 watchlist + F5-C evolving summaries — Wave A/B/C ниже)
> См. [`## 2026-04-26 — Contract closed`](#2026-04-26--contract-closed-) и `CHANGELOG.md`.
>
> **Нормативное определение принципов:** [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md)
> (формализованы 2026-05-02 — 7 принципов как ADR-якорь, защищённый от
> drift'а этого живого документа).

**Статус:** активный ориентир для развития продукта (дополняет, не заменяет [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) и [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md)).

**Дата:** 25 апреля 2026 (последняя крупная правка: 2026-05-02 — добавлен cross-link на ADR 0006 + planning prep [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) для будущей сессии).

---

## 2026-04-26 — Contract closed ✅

Living-KB-контракт (волны A + B + C) закрыт коммитами этого спринтового
цикла. Ссылки на CHANGELOG-секции и detailed deliverables — в каждом
пункте.

| Wave | Sprint | Что закрыто | CHANGELOG |
|---|---|---|---|
| A | D.1 | Topicization hardening — truthful `failed_stage`, per-batch checkpointing, error_message persistence (4096-char contract aligned in TD-01, post-Living-KB sprint Phase 1). | § Sprint D.1 — Topicization Hardening |
| B | F11 | Topic Watchlist MVP — hybrid keyword+embedding scoring, idempotent matches, instant push via aiogram, MCP/Bot/CLI surface, scheduler hook with graceful degradation. | § Sprint F11 — Topic Watchlist |
| C | F5-C | Evolving Topic Summaries MVP — counter-driven re-summarize, append-only `topic_card_versions` audit trail, advisory-lock + UNIQUE second line of defence, MCP/CLI surface. | § Sprint F5-C — Evolving Topic Summaries |

24h F5-C deploy-watch window: opens at `2026-04-26T11:07:13Z`, closes
≈ `2026-04-27T11:07Z`. Verdict reporting per [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
§ Post-watch report.

---

## 1. Что мы называем «karpathy-like» в этом проекте

Речь не про конкретного автора, а про **устойчивый стиль системы знаний**, согласованный с уже принятыми решениями (TopicCard, TopicBundle, hybrid RAG, incremental topicization, `TopicLink`):

| Принцип | Смысл для TG_parser |
|--------|---------------------|
| **Персистентные сущности** | Интересы, темы, матчи, дайджесты — явные таблицы и доменные модели, не «всё в JSON в одной колонке». |
| **Provenance / evidence** | К ответу или алерту привязаны `source_ref`, scores, версии — можно объяснить «почему сработало». |
| **Дешёвые циклы retrieval** | Keyword + embedding / hybrid там, где поток большой; LLM — на сжатых кандидатах или для редких операций (summarize, Q&A), не на каждое сырое сообщение без фильтра. |
| **Идемпотентность и журналы** | Повторный pipeline не плодит дубликаты «фактов» и уведомлений; история матчей и версий тем сохраняется осмысленно. |
| **Инкрементальный living loop** | Новые документы → processing → topicization → (алерты / дайджесты / будущие пересуммаризации тем) без ручного «пересобери всё». |
| **Наблюдаемость → тюнинг** | Метрики по bucket'ам score, дедуп, шум watchlist — правим пороги и доки по данным, а не вслепую добавляем LLM-слой. |
| **Деградация без падения ядра** | Сбой уведомлений, частичный topicization, отсутствие chat — не валят ingestion для остальных пользователей. |

Этот документ **склеивает** продуктовый roadmap с этими принципами, чтобы следующие спринты не расходились с архитектурой «живой базы знаний».

---

## 2. Связь с существующими документами

| Документ | Роль |
|----------|------|
| [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | Календарь волн, D.*, F-фичи, приоритеты релизов. |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | Дизайн F11, F5-C, F6 и др.; зафиксированный порядок **D.1 → F11 → F5-C**. |
| [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) | Полный спек F11 с karpathy-like деталями в чеклисте и рисках. |
| [`START_PROMPT_NEXT_SESSION_F11.md`](START_PROMPT_NEXT_SESSION_F11.md) | Старт сессии после D.1: дожим F11 + ссылки на этот roadmap. |
| [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) | PR-чеклист F11 с пометками **karpathy-like** по пунктам. |

---

## 3. Волны внедрения (состояние и очередь)

Условные **волны** ниже отражают **логический** порядок karpathy-like усилений; нумерация может совпадать с таблицами в Roadmap v3, но этот файл — про **тип изменений**, а не про замену таблицы приоритетов.

### Волна 0 — Фундамент (выполнено в продукте)

- Ingestion → processing → topicization → embeddings → hybrid RAG, MCP, бот, scheduled digests (F6).
- Multi-tenancy (F4), cross-channel темы и links.
- **Karpathy-like итог:** уже есть «страницы тем» (`TopicCard`), поиск с источниками, инкрементальная обработка.

### Волна A — Надёжность topicization (перед расширением «личного слоя»)

- **Sprint D.1** — topicization hardening (например учёт `failed_stage`, операционная диагностика).
- **Karpathy-like итог:** living loop не «молчит» при частичных сбоях; данные для watchlist и тем согласованы с реальным состоянием пайплайна.

### Волна B — Персональный слой внимания (текущий фокус после D.1)

- **F11 — Topic Watchlist:** персистентный интерес, `watch_matches` с scores, hybrid matching без LLM на документ, hook после topicization, instant notify, MCP/bot/CLI.
- **Karpathy-like итог:** user-defined «страница интереса» + evidence log + digest-style уведомления + метрики (желательно) для калибровки threshold.

### Волна C — Память темы (✅ реализовано 2026-04-26)

- **F5-C — Evolving Topic Summaries:** пересуммаризация / re-embed `TopicCard` при накоплении N новых supporting items; append-only версии в `topic_card_versions`.
- **Статус (26.04.2026):** ✅ **MVP DONE** — commit 1/2 `473f107` (schema + service + counter + 22 core tests), commit 2/2 `53f72ef` (scheduler hook + MCP/CLI + 21 surface tests + docs); self-review добавил ещё 15 тестов, итого **58 F5-C тестов** (10 mock + 48 PG-gated). См. CHANGELOG § Sprint F5-C. Реализовано: триггер по счётчику `new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N` (default 5), append-only `topic_card_versions` с `version_no`, hook между `run_topic_embedding(force=False)` и `run_watchlist_check_for_channel`, MCP/CLI surface (без Bot в MVP), triple cap (per_tick / duration / tokens), advisory lock + UNIQUE second line of defence, F11-style silent log + Anthropic billing-pause escalation.
- **Связка с D.1 + F11:** поток новых документов через D.1-incremental + match-evidence из F11 подпитывает сигнал «тема устарела по содержанию»; F5-C наследует **per-batch checkpointing** D.1 (counter инкрементируется per-batch без отката), но **не** контракт `failed_stage='resummarize'` — по Decision #13 F5-C использует F11-style silent log (single-billing исключение для billing-pause); F11 watchlist скорит против актуального summary благодаря порядку hook'ов.
- **Karpathy-like итог:** тема не только «видит» новые `source_ref`, но **обновляет формулировку** под накопленный корпус, сохраняя append-only провенанс эволюции каждой «страницы темы».

### Волна D — Данные и шум (по сигналам метрик)

- Тюнинг default threshold, документация, при необходимости **Phase 2 F11** (`batch` / `silent`) через существующую digest-инфраструктуру — отдельные PR.
- **F5-B** — near-duplicate по embedding после метрик (`tg_dedup_duplicates_detected_total` и т.д., см. [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) § «После F11»).
- **Karpathy-like итог:** меньше мусорных дублей и ложных алертов; решения подкреплены телеметрией.

### Волна E — Граф и retrieval+ (отдельные инициативы)

- Более явные типизированные связи (topic–doc, topic–topic, cross-channel), graph-assisted retrieval — **после** стабилизации F5-C и метрик F11, отдельными спринтами.
- В [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) это может оформляться как новые строки таблицы, когда появится спека; до тех пор этот раздел — **логический хвост**, не блокер F11/F5-C.

### Волна F — Операции и guardrails

- **DI-5**, **DI-20** и аналоги из § «После F11» спринт-промпта F11 — ops и регрессионная гигиена схемы БД, не смешивать с фиче-PR F11.

---

## 4. Что намеренно не входит в ближайшие волны

- **LLM-matching на каждый новый документ** для watchlist — только если hybrid даёт систематический шум; тогда узкий classifier на top-k (отдельное решение).
- **HTTP CRUD `/api/v1/watchlists`** — вне MVP F11 (см. спринт-промпт); MCP/bot/CLI достаточно для пилота.
- **Полная замена Postgres на graph DB** — не roadmap karpathy-like для текущей фазы; эволюция от реляционной модели + pgvector.

---

## 5. Критерий «мы на правильном пути»

После **F11 + F5-C** (плюс стабильный D.1) продукт закрывает цикл:

ingestion → processing → topicization → **обновляемые темы** → **user-defined алерты** → scheduled digests,

с явными артефактами provenance и без обязательного LLM на весь поток сообщений. Дальнейшие волны (D–F) усиливают **качество и граф**, а не переписывают контракт living KB с нуля.

---

## 6. История правок документа

| Дата | Изменение |
|------|-----------|
| 2026-04-25 | Первая версия: склейка обсуждения karpathy-like с Roadmap v3 и F11/F5-C. |
| 2026-04-26 | Волна C — статус **READY к реализации**: F5-C планировочная сессия закрыта, фиксированы 12 решений (триггер по счётчику N=5, append-only `topic_card_versions`, hook между F11-prep embedding и F11 watchlist, MCP/CLI без Bot в MVP, triple cap, advisory lock). Артефакты: `START_PROMPT_SPRINT_F5C.md`, `F5C_PR_CHECKLIST.md`. F11 (Волна B) смерджен (commit `c1c9f35`). |
| 2026-04-26 | Волна C — **MVP merged** (commits `473f107` + `53f72ef`). Living-KB-контракт (Waves A/B/C) **закрыт**, баннер сверху + `## 2026-04-26 — Contract closed` секция; 24h F5-C deploy-watch окно открыто `2026-04-26T11:07:13Z`. Добавлен `## Next contract — TBD` placeholder для будущей планирующей сессии. Правка из post-Living-KB debt-fix Phase 1 (TD-04). |
| 2026-05-02 | **ADR 0006 формализован** ([`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md)) — 7 принципов получили нормативный якорь, защищённый от drift'а этого живого документа. Закрытие review-finding C-002/C-003/C-004 из [`REVIEW_2026-04-26_MERGED_PLAN.md`](REVIEW_2026-04-26_MERGED_PLAN.md) § 2. Добавлен cross-link на ADR 0006 в [`docs/architecture.md`](../architecture.md) § «Семантика данных и Living-KB». **Planning prep** для будущей next-contract сессии: [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) — 3 кандидата (F11 P2 / F5-B / Wave E) + альтернативы + open questions. Pure docs change, без code impact. |

---

## Next contract — TBD

Следующий Karpathy-like контракт **формулируется в отдельной планирующей
сессии** — не в этом roadmap-документе, чтобы:

- не выдумывать scope без планирующей сессии (per merge-plan default Q4),
- сохранять чистую границу «закрытый контракт ↔ следующий контракт»
  (предыдущая Living-KB-секция уже закрыта выше),
- прийти к следующему контракту с явным набором OPEN QUESTIONS, которые
  стоят за приоритезацией (F11 P2 vs F5-B vs Wave E graph retrieval — см.
  [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) § 4).

**Prep-документ для будущей планирующей сессии:** [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md)
(создан 2026-05-02; содержит трёх первичных кандидатов с karpathy-like
checklist'ом по ADR 0006, альтернативные кандидаты, open design questions,
reading list, format-precedent для результирующего sprint-промпта).

**Не ставить здесь conjectured contract.** Когда планирующая сессия
закроется — добавить отдельный раздел `## 202X-XX-XX — Next contract:
<title>` со ссылкой на produced sprint-промпт, повторяющий формат
раздела `## 2026-04-26 — Contract closed`.

Кандидаты на следующий контракт (без приоритезации, для контекста
планирующей сессии — детально в [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) § 2):

- **F11 Phase 2** — `notify_mode=batch`/`silent`, calibration по
  watchlist metrics surface (TD-02 уже landed); concrete signal — есть
  (`tg_watchlist_score` histogram).
- **F5-B** — near-duplicate dedup по embedding (надстройка над F5-A
  Phase 3 exact-hash); concrete signal — частичный (нужен
  observation-only counter сначала).
- **Wave E (graph retrieval)** — расширение `TopicLink.relation_type` +
  graph-augmented retrieval; concrete signal — слабый (нужен
  measurement test-suite сложных вопросов).
- Альтернативные кандидаты (F1 / F4-B / F9 / F10 / F12) — в
  [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md), могут попасть в combo
  при подходящем product-driver'е (см. [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) § 3).
