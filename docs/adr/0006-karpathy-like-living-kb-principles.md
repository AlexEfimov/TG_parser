# ADR 0006 – Принципы Living-KB (karpathy-like): персистентные сущности, provenance, инкрементальный living loop

## Статус
Accepted (2026-05-02)

## Контекст

ADR 0001–0004 описывают **границы модулей** (слои, домен, порты, адаптеры,
hexagonal architecture). Они не описывают **семантику данных**, которую
эти модули хранят и обменивают: какие инварианты должны быть у
персистентных сущностей, как связан processing с retrieval, какие
гарантии даёт повторный запуск pipeline.

В период 2026-04-25 .. 2026-04-26 проект завершил серию волн (D.1
topicization hardening + F11 Topic Watchlist + F5-C Evolving Topic
Summaries), которые в совокупности названы **Living-KB-контрактом**.
Контракт закрыт коммитами `c1c9f35` (F11), `473f107` + `53f72ef` (F5-C),
TD-01..TD-04 (post-Living-KB Phase 1). Закрытие зафиксировано в
`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` § «2026-04-26 — Contract
closed».

Содержательно эти волны реализуют семь архитектурных принципов, которые
в проекте называются «karpathy-like» (по стилю системы знаний, а не по
автору). Принципы сформулированы в roadmap, но не зафиксированы как
ADR — то есть живут в **рабочей зоне** документации (`docs/notes/`),
а не в **нормативной** (`docs/adr/`). Это создаёт два конкретных
риска:

1. **Doc-drift.** Roadmap — живой документ; следующие правки могут
   переформулировать принципы или удалить их. Без ADR-якоря 7 принципов
   могут «уплыть» при следующей переписи roadmap.
2. **Слепая зона для новых разработчиков / сессий.** `docs/architecture.md`
   ссылается на ADR 0001–0004, но не на принципы Living-KB. Новый
   контрибьютор может месяц работать без знания о существовании
   контракта, что нарушает дисциплину.

Эти риски явно зафиксированы в [`docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`](../notes/REVIEW_2026-04-26_MERGED_PLAN.md)
§ 2 как находки C-002 / C-003 / C-004 (документация stale,
roadmap-stale, future-features-stale). ADR 0006 — структурный ответ на
эту группу находок.

## Решение

Принять **семь принципов Living-KB** как нормативный архитектурный
контракт. Любая новая feature, изменяющая persistent state, должна
проходить test «соблюдает ли 7 принципов». Roadmap остаётся живым
документом для **волн внедрения** (waves); ADR 0006 — стабильным
документом для **инвариантов** (invariants), которые волны реализуют.

### Семь принципов

1. **Persistent entities.** Темы, интересы, матчи, версии, дайджесты,
   подписки — явные таблицы и доменные модели в `tg_parser/domain/models.py`,
   а не «всё в JSON в одной колонке». Каждая сущность имеет JSON-схему
   в [`docs/contracts/`](../contracts/) (`raw_telegram_message`,
   `processed_document`, `topic_card`, `topic_card_version`,
   `topic_bundle`, `knowledge_base_entry`) и Pydantic-реализацию в
   `tg_parser/domain/models.py`. Любое поле, влияющее на retrieval или
   notification, переходит в схему / Pydantic, а не остаётся в
   `metadata: dict[str, Any]`.

2. **Provenance / evidence.** Каждый ответ или алерт прослеживается до
   первоисточника. Контрактные точки:
   - `source_ref` pattern `tg:<channel>:<post|comment>:<id>` —
     каноническая ссылка на материал; служит ключом идемпотентности.
   - `ProcessedDocument.id = "doc:" + source_ref` — детерминированный
     id, восстанавливается без БД.
   - `TopicCard.id = "topic:" + anchors[0].anchor_ref` — тема
     детерминирована primary anchor'ом.
   - `WatchMatch.id = (interest_id, source_ref)` — match хранит ссылку
     на конкретный документ и счёт.
   - `TopicCardVersion.{summary, scope_in, scope_out, supporting_items_count_at_time, llm_model, prompt_version}` —
     audit trail каждой re-summarize попытки.

3. **Cheap retrieval cycles.** На потоке (incremental tick — новые
   документы) используются **keyword + embedding scoring** без
   LLM-вызовов на документ. LLM зарезервирован для:
   - Сжатых сводок над уже отобранными кандидатами (digest, RAG answer,
     re-summarize).
   - Редких операций (initial topicization, новый кластер).
   - Никогда — для классификации каждого нового документа в pipeline.
   Реализовано: F11 watchlist hybrid score (KEYWORD_WEIGHT=0.4 +
   SEMANTIC_WEIGHT=0.6 в `tg_parser/services/watchlist_service.py`),
   incremental topicization Phase 1 (keyword-matching) в
   `tg_parser/services/topicization_service.py`, hybrid retrieval с RRF
   fusion в `tg_parser/services/retrieval_service.py`.

4. **Идемпотентность и журналы.** Повторный запуск pipeline не плодит
   дубликаты «фактов» и уведомлений; история сохраняется append-only.
   Контрактные точки:
   - Все upsert'ы используют `ON CONFLICT (...) DO UPDATE/NOTHING` с
     дедуплицирующим ключом (`source_ref`, `(interest_id, source_ref)`,
     `(topic_id, version_no)`).
   - `topic_card_versions` — append-only; никогда не UPDATE, только
     INSERT при каждой re-summarize.
   - `processing_failure_repo` — отдельный append-only журнал, не
     нарушает идемпотентность `processed_documents` (см.
     `docs/architecture.md` L681).
   - `WatchMatchRepo.upsert_many` — `ON CONFLICT (interest_id,
     source_ref) DO NOTHING RETURNING`.

5. **Incremental living loop.** Поток новых документов проходит
   ingestion → processing → topicization → embeddings → (watchlist
   alerts / digest delivery / re-summarization hooks) **без ручного
   «пересобери всё»**. Контрактные точки:
   - `run_incremental_topicization` — Phase 1 keyword + Phase 2 LLM,
     не full re-run.
   - F5-C scheduler hook — re-summarize по счётчику
     `new_items_since_last_summary >= RESUMMARIZE_TRIGGER_N`, не по
     ручному запуску.
   - F11 hook — match-check после каждого topicization-tick, без
     явного триггера.
   - F2 export — pure читалка, не модифицирует state.

6. **Observability → tuning.** Метрики собираются по bucket'ам, чтобы
   калибровать пороги по данным, а не по догадкам. Контрактные точки:
   - `tg_watchlist_score` histogram — feedback signal для F11 default
     threshold (текущий 0.6).
   - `tg_resummarize_total{outcome}` — outcomes `{ok, locked,
     no_card, no_bundle, empty_scope, llm_error, version_raced,
     unknown}` — каждый класс ошибки виден в Prometheus.
   - `tg_dedup_duplicates_detected_total{channel_id}` — F5-A Phase 3
     dedup signal.
   - `tg_bot_gemini_empty_parts_total{model, finish_reason}` —
     BUG-006 watch metric (см. ADR 0005 § Re-evaluation triggers).

7. **Деградация без падения ядра.** Сбой одного компонента
   (notification delivery, частичный topicization, отсутствие chat
   у получателя дайджеста, embedding service down) **не валит
   ingestion для остальных пользователей и каналов**. Контрактные
   точки:
   - F11 watchlist falls back to keyword-only scoring если у
     ProcessedDocument нет embedding.
   - `WatchlistService.notify` outcome `blocked` → soft-delete
     interest (preserved matches), не валит scheduler tick.
   - Bot baгs (BUG-002 / -004 / -006 / -009 за месяц прода) ни разу
     не повлияли на ingestion / processing / topicization /
     watchlist / re-summarization — bot изолирован как адаптер.
   - `AnthropicBillingError` propagates до scheduler hook, который
     pause'ит источник, а не валит process.

### Применение принципов к будущим фичам

При проектировании любой feature, влияющей на persistent state,
сделать explicit checklist:

| # | Принцип | Применимый вопрос для feature |
|---|---------|------------------------------|
| 1 | Persistent entities | Нужны ли новые таблицы / Pydantic-модели / JSON-схемы? Где границы новой сущности vs `metadata: dict`? |
| 2 | Provenance | Какой `*_ref` / `id`-pattern гарантирует traceability к первоисточнику? Можно ли восстановить evidence без БД? |
| 3 | Cheap retrieval | Будет ли feature вызывать LLM на каждый документ потока? Если да — какой keyword/embedding pre-filter может сжать кандидатов? |
| 4 | Идемпотентность | Какой ключ идемпотентности у этой операции? UPSERT с каким ON CONFLICT clause? Нужен ли append-only журнал? |
| 5 | Living loop | Как feature интегрируется в incremental tick? Hook-position относительно topicization / embedding / watchlist? |
| 6 | Observability | Какие counters / histograms / gauges нужно эмитить? Какие outcomes (success / soft-fail / hard-fail) нужно различить? |
| 7 | Graceful degradation | Что произойдёт при отказе зависимости? Где fallback / soft-delete / skip-and-continue? Не валит ли feature ядро? |

Этот checklist должен попадать в каждый sprint-promt / planning
prep document как обязательная секция «Соблюдение Living-KB».

### Граница ответственности с другими ADR

- **ADR 0001 (overall architecture)** — слои (Ingestion / Processing /
  Storage / Access). ADR 0006 не пересматривает слои; описывает, какие
  инварианты данных живут **внутри** этих слоёв.
- **ADR 0002 (telegram ingestion)** — выбор Telethon. ADR 0006
  ссылается на ingestion как источник `RawTelegramMessage` с обязательным
  `source_ref` (принцип 2).
- **ADR 0003 (storage and indexing)** — SQLite/PostgreSQL, схема. ADR
  0006 уточняет, какие свойства таблиц обязательны (UPSERT с дедуп-
  ключом, append-only журналы, дисциплина `metadata` vs первоклассные
  поля).
- **ADR 0004 (hexagonal)** — порты / адаптеры. ADR 0006 операционно
  совместим: персистентные сущности живут в домене, repos —
  адаптеры. Принцип 7 (graceful degradation) использует тот факт, что
  адаптер можно подменить или временно отключить без падения домена.
- **ADR 0005 (bot LLM provider flexibility)** — фиксирует исключение:
  bot — единственный компонент, не соблюдающий принцип 1 / 3
  полностью на уровне prompt-конфигурации. Re-evaluation triggers ADR
  0005 включают «Gemini-quirk не лечится config'ом» (принцип 7
  graceful degradation у бота сейчас неполный).

## Последствия

### Положительные

- 7 принципов получают нормативный якорь, защищённый от drift при
  правке roadmap.
- Новый разработчик / следующая планирующая сессия имеют один
  authoritative документ для «что обязательно соблюдать», вместо
  чтения 5+ docs/notes файлов.
- Closure для review-findings C-002 / C-003 / C-004 из
  [`docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`](../notes/REVIEW_2026-04-26_MERGED_PLAN.md)
  § 2.
- Будущие планирующие сессии (Wave D / E) могут опираться на ADR
  0006 как на «проверочный лист»: feature должна проходить 7-checklist
  перед попаданием в roadmap.

### Отрицательные / принятый долг

- ADR 0005 (bot LLM flexibility) явно нарушает принципы 1 / 3 на
  prompt-уровне (Gemini-specific bullets в `prompts/bot.yaml`). Это
  принятое исключение, но оно остаётся видимым «отступлением» от ADR
  0006.
- Принципы сформулированы абстрактно; конкретное применение к новой
  feature требует судейского решения (например, что считать
  «достаточно cheap retrieval cycle»). Mitigation — checklist в § «Применение
  принципов» + opportunistic ревью на planning sessions.

### Что НЕ меняется этим ADR

- Никаких code changes. Pure documentation.
- Roadmap (`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`) остаётся
  живым документом — только добавляется cross-ref на ADR 0006.
- Существующие waves A/B/C (D.1 / F11 / F5-C) считаются реализующими
  ADR 0006 ретроактивно (closure 2026-04-26).
- Существующие 67 FSM-тестов / 1869 prod-теста не затрагиваются.

## Ссылки

- Roadmap (живой документ для волн): [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](../notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md).
- Контракты данных (JSON-схемы): [`docs/contracts/`](../contracts/) —
  `raw_telegram_message`, `processed_document`, `topic_card`,
  `topic_card_version`, `topic_bundle`, `knowledge_base_entry`.
- Pydantic-реализация: [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py).
- Реализующие сервисы:
  - F11: [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py)
    (см. inline «Karpathy-like invariants:» в docstring L9–28).
  - F5-C: [`tg_parser/services/resummarization_service.py`](../../tg_parser/services/resummarization_service.py).
  - Hybrid retrieval: [`tg_parser/services/retrieval_service.py`](../../tg_parser/services/retrieval_service.py).
- Метрики: [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py).
- Архитектурный обзор: [`docs/architecture.md`](../architecture.md)
  (cross-link на ADR 0006 — § «Семантика данных и Living-KB»).
- Источник 7 принципов: [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](../notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
  § 1 «Что мы называем "karpathy-like" в этом проекте».
- Closure context: [`docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`](../notes/REVIEW_2026-04-26_MERGED_PLAN.md)
  § 2 (review-findings C-002 / C-003 / C-004 — этот ADR — структурный
  ответ).
- Связанные ADR: [`0001-overall-architecture.md`](0001-overall-architecture.md),
  [`0002-telegram-ingestion-approach.md`](0002-telegram-ingestion-approach.md),
  [`0003-storage-and-indexing.md`](0003-storage-and-indexing.md),
  [`0004-hexagonal-architecture-and-module-boundaries.md`](0004-hexagonal-architecture-and-module-boundaries.md),
  [`0005-bot-llm-provider-flexibility.md`](0005-bot-llm-provider-flexibility.md).
