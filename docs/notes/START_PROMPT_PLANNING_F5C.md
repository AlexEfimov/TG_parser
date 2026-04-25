# Планировочная сессия — F5-C: Evolving Topic Summaries

**Назначение:** стартовый промпт для **планировочной** (не реализационной) сессии нового окна, по итогам которой должны появиться:

1. Полный спринт-промпт `docs/notes/START_PROMPT_SPRINT_F5C.md` (по образцу [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — pre-flight, шаги 1..N, gotchas, риски, PR-чеклист, после-F5-C хвост);
2. Решение по списку **открытых проектных вопросов** (см. § «Open design questions» ниже);
3. Обновление дизайн-блока F5-C в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) — по факту принятых решений (триггер, версионирование, схема, контракт MCP/Bot/CLI), не «постфактум».

**Ничего не реализовывать в этой сессии.** Только дизайн + спринт-промпт. Реализация — отдельная сессия по выпущенному промпту.

**Дата подготовки промпта:** 26 апреля 2026 (после merge F11, commit `c1c9f35`).

---

## Где F5-C сидит в плане

| Источник | Что говорит |
|---|---|
| [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) строка 389 | F5-C — **следующий** шаг после F11; ~1 сессия; «закрывает последний пробел в Living KB-контракте» |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) строки 724–735 (§ Level C) | Краткий design: тригер «N новых supporting items», LLM re-summarize, re-embed, append-only `topic_card_versions` |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) строка 949 | Связка с F6: digest должен использовать **обновлённые** topic summaries вместо raw doc summaries |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) строки 59–64 (Волна C) | F5-C как «память темы» в karpathy-like модели: подпитывается потоком `source_ref` от F11 |
| [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) строка 668 (§ «После F11») | F5-C — пункт #1 в очереди; явная фраза «темы знают о новых материалах, но не помнят их содержания» |
| [`CHANGELOG.md`](../../CHANGELOG.md) § Sprint F11 (line 9+) | Что вошло в F11 и какие коммиты служат точкой входа для F5-C scheduler hook |

> **North star одной строкой:** TopicCard не статичен — при накоплении N новых supporting items в его TopicBundle тема **переписывает свой `summary` + `scope_*` + re-embed**, **сохраняя предыдущие версии** для аудита и для F6/F11 (которым нужна стабильная «текущая версия страницы темы»).

---

## Must-read до начала планирования

### Продуктовые / роадмап-документы

| Файл | Зачем читать | Ключевые строки |
|---|---|---|
| [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | Дизайн-набросок F5-C; связки F5-C↔F6, F5-C↔F11, F5-C↔F5-B | **§ Level C** (строки 724–735), **§ F5-C row** (строка 133), **F6 связь** (строка 949) |
| [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Принципы living-KB; F5-C как «Волна C — память темы» | строки 11–22 (раздел «1. Что мы называем karpathy-like» с таблицей 6 принципов), 59–64 (Волна C), 71–74 (Волна E — почему «не блокер F11/F5-C»), 82–86 (§ 4 «Что намеренно не входит в ближайшие волны») |
| [`docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | Последовательность волн, F5-C как точка перехода Волна 2 → Волна 3 | строки 378–414 (пост-F5-A траектория), 415–425 (дальние горизонты) |
| [`CHANGELOG.md`](../../CHANGELOG.md) § Sprint F11 | Свежий контекст: что уже работает в pipeline (scheduler hook, MCP/Bot/CLI surface, MarkdownV2 push), какие коммиты можно как образец цитировать | от заголовка `Sprint F11 — Topic Watchlist (2026-04-25)` до начала Sprint D.1 |
| [`docs/notes/START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) | **Образец** для финального sprint-промпта; § «После F11» содержит 4 пункта продолжения, F5-C — #1 | весь файл — как структурный шаблон; § Hidden gotchas; § Risks; § PR checklist; строки 664–673 |

### Архитектурные / технические

| Файл | Зачем читать | Что вынести |
|---|---|---|
| [`docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) | Кардинальное решение Session 34 + Sprint D.1: **incremental** топикизация, не full re-run; F5-C обязан вписаться в эту модель | § Принятые решения (строки 18–31); § Phase 1/Phase 2 flow; § Sprint D.1 (per-batch checkpointing) |
| [`docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`](START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md) | Образец паттерна `failed_stage` / per-batch checkpointing / billing-pause из Sprint D.1; F5-C должен соблюдать тот же контракт `source_attempts` (если падение на этапе resummarize — записать `failed_stage='resummarize'`) | вся документация спринта; § «Truthful source_attempts» |
| [`docs/architecture.md`](../architecture.md) | Текущая схема `topic_cards`, `topic_bundles`, `embeddings` — куда крепится versioning | поиск по `topic_cards`, `topic_bundles`, `embeddings.entry_type` |
| [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json) + [`docs/contracts/topic_bundle.schema.json`](../contracts/topic_bundle.schema.json) | **Канонические JSON-контракты** для TopicCard / TopicBundle. Pydantic-модели в `domain/models.py` — реализация этих контрактов. **Любая** правка `summary` / `scope_*` / новые поля (`summary_version`, `last_summarized_at`) **обязана** быть отражена и в JSON-схемах, и в Pydantic — и сверена с `tests/test_topicization*.py` (см. § Соглашения). | `required: [id, title, summary, scope_in, scope_out, type, anchors, sources, updated_at]` (строки 6–16 в `topic_card.schema.json`) |
| [`docs/USER_GUIDE.md`](../USER_GUIDE.md) | Контракт того, что пользователь видит в `get_topic_details` / digest / watchlist match — F5-C **не должен** ломать ни один из этих экранов | поиск по `topic_card`, `summary`, `digest` |
| [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) | MCP контракты для агента (если F5-C добавит `get_topic_versions` / `force_resummarize` — какой стиль соблюдать) | разделы про `get_topic_details`, `list_topics` |
| [`docs/quality/INBOX.md`](../quality/INBOX.md) + [`docs/quality/TRIAGED.md`](../quality/TRIAGED.md) | Журнал наблюдений и триажа. Перед стартом планирования стоит **проверить, нет ли там уже наблюдений про устаревшие/дрейфующие topic summaries** — если есть, использовать как обоснование триггера N (см. open question #1). Пример паттерна — Sprint D.1 закрытие incident'а `genotek` см. в `docs/quality/incidents/`. | вся таблица INBOX; в TRIAGED — поиск по `topic` / `summary` / `stale` |
| [`prompts/README.md`](../../prompts/README.md) + [`prompts/topicization.yaml`](../../prompts/topicization.yaml) + [`prompts/supporting_items.yaml`](../../prompts/supporting_items.yaml) + [`prompts/digest.yaml`](../../prompts/digest.yaml) | Текущие prompt templates топикизации и digest; F5-C добавит новый `prompts/resummarize.yaml` (или похожий) — соблюдать конвенцию `system:` (line 17 supporting_items.yaml) / `user:` (line 50) / `model:` (line 77) | structure всех yaml; `digest.yaml` как образец нового scope с per-stage LLM конфигом |

### Код — точки врезки и образцы

| Файл / символ | Зачем |
|---|---|
| `tg_parser/services/topicization_service.py:148 run_incremental_topicization` | Точка, **после** которой может срабатывать F5-C re-summarize hook (по образцу того, как F11 hook стоит после `run_incremental_topicization` в `_process_source`) |
| `tg_parser/services/topicization_service.py:558 _update_bundles_for_assignments` | Здесь группируются assignments по `topic_id` и добавляются items в bundle — это место, где можно **инкрементировать счётчик «items since last summary»** для триггера (или вычислять разность через bundle.items count) |
| `tg_parser/processing/topicization.py` (поиск `_compute_match_score`, `_discover_single_batch`) | Текущая модель того, как тема порождается; F5-C **не пересоздаёт** темы, а **обновляет** их |
| `tg_parser/domain/models.py:190 TopicCard` (строки 190–223) | Модель TopicCard: `summary: str (required)`, `scope_in: list[str] min_length=1`, `updated_at: datetime`, `metadata: dict \| None` — F5-C должен решить, добавлять ли поля `summary_version`, `last_summarized_at`, либо хранить эти поля в `metadata` (см. open question #5). **Помнить:** новые поля = update [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json). |
| `tg_parser/domain/models.py:341 TopicBundle` (строки 341–366) | `items: list[BundleItem]` — счётчик новых supporting items берётся отсюда; `updated_at` — кандидат на «когда последний раз тема видела новый материал» |
| `tg_parser/storage/sqlalchemy/topic_card_repo.py` | UPSERT-паттерн для `topic_cards` (UPSERT через `INSERT ... ON CONFLICT DO UPDATE`, см. строки 35–55); для F5-C `topic_card_versions` потребуется **новый** repo + port (по образцу `SAWatchInterestRepo`) |
| `tg_parser/storage/sqlalchemy/topic_bundle_repo.py` | Методы upsert / add_items — пригодятся для триггера счётчика |
| `tg_parser/storage/sqlalchemy/embedding_repo.py:16 SAEmbeddingRepo.upsert` (`entry_type='topic'`, `topic_id=...`) | **Готовый** механизм для re-embed обновлённого topic summary; уже поддерживает `entry_type='topic'` и UPSERT — F5-C ничего нового в схеме embeddings не нужно |
| `tg_parser/storage/sqlalchemy/_metadata.py` | `Table()` декларации (`topic_cards` line 452, `topic_bundles` line 479, `watch_interests` line 228 как образец F11); F5-C добавит `topic_card_versions` Table() сюда + соответствующая alembic ревизия (см. ниже). После добавления `tg-parser db check --db processing` обязан показать `No new upgrade operations detected.` |
| `tg_parser/services/db_context.py` (`processing_repos` line 47, `watchlist_repos` line 137) | Паттерн `@asynccontextmanager` для пакета репозиториев + автоматический `aclose()`; F5-C либо расширяет `processing_repos` новым `topic_card_versions_repo`, либо создаёт `topic_versions_repos()` контекст по образцу `watchlist_repos` |
| `tg_parser/services/scheduler_service.py:82 _process_source` + line 189 (F11 hook) + line 479 `run_watchlist_check_for_channel` | **Образец** того, как добавляются hook'и после topicization, c `try/except + logger.exception` (см. строки 189–203 для wrapping); F5-C hook будет соседним. Ровно такой же docstring-контракт как у F11 hook (см. строки 488–499). |
| `tg_parser/services/watchlist_service.py:753 make_watchlist_service` + line 708 `aclose` | **Образец** factory-функции с graceful fallback на embedding client (если `create_embedding_client` падает — сервис всё ещё работает, но без semantic scoring) — для `make_resummarization_service` (если будет такой сервис) |
| `tg_parser/processing/llm/factory.py:33 resolve_llm_config` + line 51 `create_llm_client` | Точка для нового LLM scope `resummarize` (см. open question #6); resolution priority: stage override → global override → stage .env → global .env |
| `tg_parser/auth/ownership.py:18 assert_channel_access` + line 29 `assert_admin` | Helpers для ownership-rules — пригодятся, если F5-C добавит MCP/Bot/CLI surface (open question #9); не путать с (несуществующим) `tg_parser/auth/permissions.py` |
| `migrations/versions/processing/` (8 ревизий, последняя — `20260420_processed_at_to_timestamptz.py`) | Куда упадёт новая F5-C ревизия (`topic_card_versions` — это **processing** БД, не ingestion); смотреть **head** через `tg-parser db check --db processing` |
| `migrations/versions/ingestion/20260425_add_watchlist.py` | **Образец** свежей миграции (F11) — `op.create_table` + UNIQUE + idempotent extension; стиль для F5-C ревизии |
| `tests/test_topicization.py` + `tests/test_incremental_topicization.py` + `tests/test_cross_channel_topicization.py` + `tests/test_topicization_prompts.py` | **Backward-compat checklist:** существующие тесты топикизации (~80+ кейсов) предполагают `topic.summary` пишется один раз. F5-C не должен сломать ни один; новые тесты re-summarize — отдельным файлом `tests/test_resummarization*.py` (по образцу F11 layout) |
| `tests/test_f11_scheduler_hook.py` | **Образец** структуры тестов scheduler hook (3 теста: happy path, notify failure не валит scheduler, ошибки логируются) |

---

## Open design questions (что должна решить планировочная сессия)

> Эти вопросы НЕ имеют «правильного» ответа в текущих документах — их надо явно обсудить и зафиксировать в спринт-промпте F5-C + § F5-C дизайн-блока в `FUTURE_FEATURES.md`.

### 1. Триггер re-summarize: что именно «N новых supporting items»?

- **Вариант A:** счётчик `new_items_since_last_summary` в `topic_cards.metadata` (или в новой колонке) — инкрементируется в `_update_bundles_for_assignments`, при достижении N запускается re-summarize, после успеха обнуляется.
- **Вариант B:** считать на лету `COUNT(bundle_items WHERE added_at > topic_cards.last_summarized_at)`. Дороже на каждый tick, но без drift.
- **Вариант C:** time-based (раз в N часов, если есть >=1 новый item) + cap `min_items_to_resummarize=K`.
- Что N по умолчанию? 5? 10? 20? — обоснование на основе **стоимости** одного re-summarize (см. вопрос #6) и **скорости устаревания** темы.

### 2. Версионирование: схема `topic_card_versions`

- **Минимальная схема (рекомендация дизайн-доку):** `(topic_id, version_no, summary, scope_in, scope_out, created_at, supporting_items_count_at_time, llm_model, prompt_version)` — append-only, никогда не UPDATE.
- Нужен ли `tags` / `anchors` snapshot? Они меняются редко — возможно не нужно.
- `version_no` — глобальный per-topic монотонный счётчик, или хватает `created_at DESC LIMIT N`?
- Retention: храним всё или только последние M версий? F5-C MVP — храним всё, но явно прописать TTL-вопрос как Phase 2.
- Связка с FK: `topic_card_versions.topic_id → topic_cards.id ON DELETE CASCADE`?

### 3. Granularity re-summarize: что переписываем?

- Только `summary`? (минимум, дизайн-док § Level C говорит «обновлённый summary, обновлённый scope»)
- `summary + scope_in + scope_out`? (полнее, но риск дрейфа scope, если темы фундаментально разные)
- `title` НЕ трогаем — он формирует часть `id` (`topic:{primary_anchor_ref}`), смена title не ломает id, но ломает читаемость; решить.
- `tags`? (опционально)

### 4. Граничные случаи

- **Cluster-тема vs Singleton:** для singleton (1 anchor) re-summarize при добавлении supporting — это эффективно «переход в cluster»; нужно ли менять `type`? Или фиксируем тип в момент создания?
- **Удалённые supporting items:** что если bundle ужался (топикизация переназначила doc в другую тему)? Тоже триггерит re-summarize с уменьшением счётчика?
- **Backfill / большой канал:** при первом подключении канала может за один tick прилететь сотни новых items — нужен **MAX_RESUMMARIZE_PER_TICK = K** (по образцу `MAX_DOCS_PER_TICK = 100` в F11) и батчинг.
- **Race condition:** два scheduler tick'а одновременно дёрнули `topic_id=X` (cross-channel topic с двумя channels) — как избежать двойного re-summarize? Advisory lock? `SELECT ... FOR UPDATE SKIP LOCKED`?

### 5. Куда хранить служебные поля темы

- `last_summarized_at: datetime` — новая колонка в `topic_cards` или поле в `metadata` JSONB?
- `summary_version: int` — то же самое: колонка или metadata?
- `new_items_since_last_summary: int` — колонка или metadata, если выбран Вариант A триггера (см. #1)?
- **Рекомендация дизайн-доку:** новые колонки (а не metadata JSONB) — потому что эти поля участвуют в WHERE/ORDER BY scheduler hook, и индекс по JSONB полю стоит дороже.
- Миграция: `ALTER TABLE topic_cards ADD COLUMN last_summarized_at TIMESTAMPTZ NULL` + `summary_version INTEGER NOT NULL DEFAULT 1` + `new_items_since_last_summary INTEGER NOT NULL DEFAULT 0`.

### 6. LLM-стоимость и провайдер

- `summary` — короткий (1–3 предложения), цена низкая. Но для cluster-темы с 50 items input может быть большим (50 * 200 tokens = 10K input).
- **Стратегия input:** только новые items с прошлой версии? + предыдущий summary? (Sliding window) Или всю историю bundle?
- Какой LLM stage в `LLM_CONFIG` использовать? Новый `resummarize` scope, или переиспользовать `topicization`? — рекомендация: **новый scope `resummarize`**, чтобы можно было per-stage тюнить (например, дешёвый GPT-4o-mini, не Sonnet 4).
- ENV вары: `RESUMMARIZE_LLM_PROVIDER`, `RESUMMARIZE_LLM_MODEL` — по образцу `DIGEST_LLM_PROVIDER` / `DIGEST_LLM_MODEL`; обновить `ENV_VARIABLES_GUIDE.md` + `.env.example` + `env.production.example`.
- Метрика: `tg_resummarize_tokens_total{topic_id, model}` + `tg_resummarize_duration_seconds` — по образцу F11/F6.

### 7. Re-embed: координация с pgvector

- `tg_parser/storage/sqlalchemy/embedding_repo.py:upsert(entry_type='topic', topic_id=...)` — уже работает; F5-C должен дёрнуть этот upsert после успешного re-summarize.
- Что embed'им? `summary` (одиночка) или `f"{title}\n\n{summary}\n\nScope: {scope_in}"` (канонический текст)? — по образцу `build_canonical_interest_text` из F11.
- Обработка пустого/слишком короткого summary — fallback на title (gotcha #1 в F11).
- Идемпотентность: при повторе можно ли upsert тот же source_ref `topic:{id}` — `embedding_repo.upsert` уже идемпотентен.

### 8. Hook placement в scheduler

- **Вариант A:** F5-C hook сразу после F11 hook в `_process_source` — тогда F11 на этот tick видит **старые** topic summaries (race), но получает их на следующем tick.
- **Вариант B:** F5-C hook **до** F11 hook — F11 сразу видит новые summaries, но pipeline дольше блокируется.
- **Вариант C:** F5-C — отдельный APScheduler job (по cron или `IntervalTrigger`), не в scheduler tick. Развязывает latency, но добавляет sync-point.
- **Рекомендация для рассмотрения:** B (F5-C до F11), потому что F11 как раз должен скорить против актуальной модели темы. Но нужно явно решить и записать в gotcha.

### 9. MCP / Bot / CLI surface

- **F5-C — backend-фича.** Нужны ли user-facing tools?
  - `get_topic_versions(topic_id, limit)` — посмотреть историю версий темы (audit trail) — **полезно**.
  - `force_resummarize(topic_id)` — ручной триггер для admin / power user — **полезно для отладки**.
  - `get_topic_history_diff(topic_id, version_a, version_b)` — diff двух версий — **опционально**.
- В F11 4 tools (subscribe / list / unsubscribe / matches). Для F5-C **минимум 1** (`get_topic_versions`), возможно 2.
- Если добавляем — соблюдать ownership-rules (admin vs owner) по образцу F11.

### 10. Тестирование (фундамент тестового бюджета)

- Service-level (no DB) ~15–20: триггер по N, версионирование, граничные случаи (cluster vs singleton, удалённые items, race), graceful degradation на падении LLM.
- PG-gated ~5–8: schema migration round-trip, append-only `topic_card_versions`, `last_summarized_at` индексы.
- Scheduler hook ~3–4: по образцу `tests/test_f11_scheduler_hook.py`.
- MCP/Bot/CLI ~3–5 на каждый surface (если добавляем).
- **Целевая дельта:** ~25–40 новых тестов (для сравнения, F11 итого ~162 тест-функции в 7 файлах: `test_watchlist_service.py` 75, `test_watchlist_score.py` 29, `test_f11_watchlist_repo.py` 16, `test_f11_bot_tools.py` 15, `test_f11_mcp_tools.py` 14, `test_f11_cli_watchlist.py` 10, `test_f11_scheduler_hook.py` 3; F5-C проще по surface, но сложнее по edge-cases re-summarize triggering).

### 11. Обратная совместимость и migration story

- Все существующие `topic_cards` после миграции имеют `summary_version=1`, `last_summarized_at=NULL`, `new_items_since_last_summary=0`. Первый tick после деплоя не должен запустить лавину re-summarize — нужен **bootstrap-режим**: `last_summarized_at` инициализируется через `UPDATE topic_cards SET last_summarized_at = updated_at` в data-migration шаге.
- F11 watchlist использует document-level фичи, не topic summary — поэтому F5-C **не должен** ломать F11 (см. § F11 § «no LLM на документ»).
- F6 digest использует `processed_document.summary` — F5-C может опционально начать использовать `topic_cards.summary` для тематических digest'ов; это **отдельная задача** (см. § F6↔F5-C в `FUTURE_FEATURES.md` строка 949), не в MVP F5-C.

### 12. Деплой и graceful degradation

- F5-C никогда не должен блокировать ingestion / topicization / F11. Любая ошибка в re-summarize → log + skip + следующий tick.
- Если LLM провайдер недоступен → пропускаем тему до восстановления (как F11 при недоступном embedding client).
- Бюджет на скан тем за tick: max W секунд / max K тем / max T tokens — все три cap'а явно описать.

---

## Соглашения проекта, которые F5-C обязан соблюдать (НЕ open questions — это **уже** решено)

| Соглашение | Ссылка |
|---|---|
| **Alembic = единственный источник правды** для DDL; никаких `init_*_schema` helpers (DI-19 закрыт) | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § «Migration tech-debt zero-out roadmap», CLOSED Sprint A.7 (строки 2914–2933) |
| **Table() декларации** в `tg_parser/storage/sqlalchemy/_metadata.py` для каждой новой таблицы (`topic_card_versions`) — `tg-parser db check --db processing` обязан показать `No new upgrade operations detected.` | `_metadata.py` (`topic_cards` line 452, `watch_interests` line 228 как образцы) + DI-9 phase 1/2 |
| **Pydantic ↔ JSON-schema sync** — любое новое поле в `domain/models.py:TopicCard` / `TopicBundle` обязано появиться в `docs/contracts/topic_card.schema.json` / `topic_bundle.schema.json` (`required`/`properties`); расхождение между Pydantic и JSON-schema = регрессия контракта | [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json) + `tg_parser/domain/models.py:190` |
| **Per-batch checkpointing** (Sprint D.1) — если re-summarize обрабатывает несколько тем подряд, каждая успешная тема должна персистится сразу, без отката всего батча | [`ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) § Sprint D.1 |
| **Truthful `source_attempts`** (Sprint D.1) — если F5-C падает на этапе `resummarize`, scheduler должен записать `failed_stage='resummarize'` + `error_class` + `error_message` (4096 чарактер cap) | [`CHANGELOG.md`](../../CHANGELOG.md) § Sprint D.1 §§ Changed |
| **Graceful degradation** — F5-C падение НЕ блокирует ingestion / topicization / F11 (gotcha #10 в F11 спринт-промпте) | [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) gotcha #10 |
| **Ownership / ACL** — если будет MCP/Bot/CLI surface, использовать `assert_channel_access` / `assert_admin` по образцу F11 | F11 PR checklist + `tg_parser/auth/ownership.py` (`assert_channel_access` line 18, `assert_admin` line 29, `check_channel_limit` line 35) |
| **Per-stage LLM конфиг** — новый stage `resummarize` в LLM-config (`set_llm_config(scope='resummarize', ...)`); resolution priority: stage override → global override → stage .env → global .env | `tg_parser/processing/llm/factory.py:resolve_llm_config` |
| **Prompt template** — YAML в `prompts/resummarize.yaml` (или подобное), reload через `reload_prompts` MCP tool работает out-of-the-box | [`prompts/README.md`](../../prompts/README.md) |
| **Embedding** — переиспользуем `SAEmbeddingRepo.upsert(entry_type='topic', topic_id=...)`, никакой новой таблицы embeddings | `tg_parser/storage/sqlalchemy/embedding_repo.py` строки 16–55 |
| **MarkdownV2 / push** — F5-C **НЕ** делает прямых уведомлений пользователю (это F11 / F6); F5-C только обновляет данные | F11 vs F6 разделение |
| **Test patterns** — service-level mocks + PG-gated отдельным файлом + scheduler hook по образцу `tests/test_f11_scheduler_hook.py` + ruff чистый | [`tests/conftest.py`](../../tests/conftest.py) + F11 коммиты `026313c` / `8e07212` / `0ff5bcf` |
| **Никаких эмодзи в коде / сообщениях системы** | проектное правило |
| **Документировать новые ENV** в `ENV_VARIABLES_GUIDE.md` + `.env.example` + `env.production.example` (по образцу `BILLING_BLOCK_BACKOFF_S` в Sprint D.1) | [`CHANGELOG.md`](../../CHANGELOG.md) § Sprint D.1 §§ Documentation |

---

## Что вне scope сессии планирования

- **Не писать код, миграции, тесты.** Это для следующей реализационной сессии.
- **Не запускать `pytest` / `ruff` / `alembic`** — есть свежие зелёные числа (F11 commit `c1c9f35`: 1697 / 1823 / 4 testcontainers, CI `24938772454` 5/5).
- **Не решать вопросы Phase 2** F5-C (TTL для версий, diff-API, авто-deprecation тем без активности) — отметить их в backlog и Phase 2 секции дизайн-дока.
- **Не трогать F11 / F6 / D.1 контракты** — F5-C должен встраиваться **в** них, а не модифицировать.
- **Не привязываться** к Knowledge Graph (Level D в `FUTURE_FEATURES.md` строки 737–777) — это отдельные спринты после F5-C, не часть F5-C.

---

## Deliverables планировочной сессии

По итогам новой сессии должен появиться commit (или несколько) с:

1. **`docs/notes/START_PROMPT_SPRINT_F5C.md`** — полный спринт-промпт по образцу [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md):
   - Goal / non-goals
   - Pre-flight (env, alembic head, baseline pytest)
   - Шаги 1..N с конкретными файлами / строками / порядком коммитов (рекомендация — 2 коммита: 1/2 schema + service + scoring, 2/2 hook + MCP/Bot/CLI + тесты + docs; повторить F11-паттерн)
   - Hidden gotchas (минимум по 1 на каждый разрешённый open question)
   - Risks таблица с mitigations
   - Rollback plan
   - PR-checklist (по образцу [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md))
   - § «После F5-C» — что дальше (вход в Волну 3: F1 полный, F11 Phase 2, F5-B при сигнале)

2. **`docs/notes/F5C_PR_CHECKLIST.md`** — чеклист для тела PR (по образцу [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md)): 1:1 с § PR checklist спринт-промпта + karpathy-like пометки + разбивка по коммитам.

3. **`docs/notes/START_PROMPT_NEXT_SESSION_F5C.md`** (опционально, если появится shared контекст для дожима PR) — по образцу [`START_PROMPT_NEXT_SESSION_F11.md`](START_PROMPT_NEXT_SESSION_F11.md).

4. **Дизайн-блок в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § Level C** — обновить с явно зафиксированными решениями (триггер, схема, surface, хук-placement); пометить статус `READY` (по аналогии с тем, как F11 был `READY` перед стартом). **Параллельно отразить новые поля TopicCard / TopicBundle (если решат добавить) в [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json) / [`topic_bundle.schema.json`](../contracts/topic_bundle.schema.json)** — `required` + `properties`, синхронно с Pydantic-моделями (см. § Соглашения).

5. **Один экран Decision Log** в начале спринт-промпта — таблица «вопрос → решение → краткое обоснование» по всем 12 пунктам § Open design questions выше.

6. **(опционально, желательно)** — короткий update в [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) Волна C: финализация спецификации F5-C.

---

## Минимальный «один экран контекста» для планирующего

Если читать вообще ничего нет времени — прочитать **в этом порядке**:

1. [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) строки **724–735** (3 минуты — собственно дизайн-задумка F5-C)
2. [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) строки **59–64** (Волна C — собственно F5-C) + **82–86** (§ 4 «Что намеренно не входит» — границы, чего F5-C не пытается решить) (2 минуты)
3. [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — **только § «Hidden gotchas» и § «PR checklist»** (5–7 минут — паттерн, в котором писать спринт-промпт F5-C)
4. [`docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) строки **18–31** (2 минуты — что нельзя сломать при добавлении re-summarize в incremental flow)
5. `tg_parser/services/topicization_service.py:148–230` (3 минуты — `run_incremental_topicization` точка врезки)
6. `tg_parser/domain/models.py:190–223` (1 минута — текущая модель TopicCard, что есть и чего нет для версионирования)

Итого ~15–20 минут до первого осмысленного решения по open questions.

---

## Связанные документы / артефакты (одним списком)

- [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md) — § Level C (line 724) + § F5-C row (line 133) + § F6↔F5-C link (line 949)
- [`docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) — таблица «Пост-F5-A Phase 3» (line 378+), F5-C — пункт #5 (line 389)
- [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — Волна C (lines 59–64), что НЕ берём (lines 82–86), общие принципы (lines 11–22)
- [`docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) — incremental контракт + Sprint D.1
- [`docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`](START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md) — паттерн `failed_stage` / per-batch checkpointing / billing-pause из D.1
- [`docs/notes/START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — образец спринт-промпта
- [`docs/notes/F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) — образец PR-чеклиста
- [`docs/notes/START_PROMPT_NEXT_SESSION_F11.md`](START_PROMPT_NEXT_SESSION_F11.md) — образец «следующей сессии» промпта
- [`CHANGELOG.md`](../../CHANGELOG.md) §§ Sprint F11, Sprint D.1 — свежий фактический state
- [`docs/architecture.md`](../architecture.md) — текущая схема + контракты
- [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json) + [`docs/contracts/topic_bundle.schema.json`](../contracts/topic_bundle.schema.json) — канонические JSON-контракты, обязательны к sync с Pydantic
- [`docs/USER_GUIDE.md`](../USER_GUIDE.md) + [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) — что НЕ должны сломать пользовательские контракты
- [`docs/quality/INBOX.md`](../quality/INBOX.md) + [`docs/quality/TRIAGED.md`](../quality/TRIAGED.md) — журнал наблюдений (проверить наличие записей про устаревшие topic summaries)
- [`prompts/README.md`](../../prompts/README.md) + `prompts/topicization.yaml` + `prompts/supporting_items.yaml` + `prompts/digest.yaml` — конвенция YAML-промптов (`system:` / `user:` / `model:`)
- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) + `.env.example` + `env.production.example` — куда добавлять `RESUMMARIZE_LLM_PROVIDER` / `RESUMMARIZE_LLM_MODEL` / триггерные пороги
- Код-якоря: `tg_parser/services/topicization_service.py` (line 148 `run_incremental_topicization`, line 558 `_update_bundles_for_assignments`), `tg_parser/services/scheduler_service.py` (line 82 `_process_source`, line 189 F11 hook call site, line 479 `run_watchlist_check_for_channel`), `tg_parser/services/watchlist_service.py` (line 753 `make_watchlist_service`, line 708 `aclose`), `tg_parser/services/db_context.py` (line 47 `processing_repos`, line 137 `watchlist_repos`), `tg_parser/processing/llm/factory.py` (line 33 `resolve_llm_config`, line 51 `create_llm_client`), `tg_parser/auth/ownership.py` (line 18 `assert_channel_access`, line 29 `assert_admin`), `tg_parser/storage/sqlalchemy/embedding_repo.py` (line 16 `SAEmbeddingRepo`, entry_type='topic'), `tg_parser/storage/sqlalchemy/_metadata.py` (line 228 watch_interests, line 452 topic_cards, line 479 topic_bundles), `migrations/versions/processing/` (head — `20260420_processed_at_to_timestamptz.py`), `migrations/versions/ingestion/20260425_add_watchlist.py` (F11 как образец свежей миграции)
- Тестовые шаблоны: `tests/test_f11_scheduler_hook.py` (3 теста — образец для `tests/test_resummarization_scheduler_hook.py`), `tests/test_topicization*.py` (~80+ кейсов — backward-compat baseline, не должны сломаться)

---

## Жёсткое DoD планировочной сессии

- [ ] Все 12 open questions имеют **зафиксированное решение** в Decision Log спринт-промпта (а не «обсудим в реализации»).
- [ ] Появился `START_PROMPT_SPRINT_F5C.md` — самодостаточный, по образцу F11 (можно копировать структуру буллетов).
- [ ] Появился `F5C_PR_CHECKLIST.md` — 1:1 с § PR checklist спринт-промпта + karpathy-like пометки.
- [ ] § Level C в `FUTURE_FEATURES.md` обновлён — триггер, схема, surface, гиппотезы по N — по факту принятых решений.
- [ ] Все ссылки в новых документах валидны (markdown links, не битые).
- [ ] Один git-коммит (или 2: planning + roadmap-bump) с message `docs(F5C): planning session — sprint prompt + PR checklist + design lock`.
- [ ] (опционально) push + проверить, что CI Lint Documentation зелёный.
