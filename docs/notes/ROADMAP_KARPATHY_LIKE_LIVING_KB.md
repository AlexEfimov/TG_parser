# Roadmap: Karpathy-like подход и Living KB

**Статус:** активный ориентир для развития продукта (дополняет, не заменяет [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) и [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md)).

**Дата:** 25 апреля 2026.

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
