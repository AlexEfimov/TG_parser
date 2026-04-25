# Sprint F5-C — Evolving Topic Summaries

**Дата подготовки:** 26 апреля 2026 (после мёрджа Sprint F11, commit `c1c9f35`).
**Тип сессии:** Feature (~1 сессия, рекомендация — 2 коммита: 1/2 schema + service + scoring + тесты ядра, 2/2 scheduler hook + MCP/CLI + миграция data-bootstrap + docs).
**HEAD на момент написания:** `c1c9f35` на `origin/main` (Sprint F11 merged 25.04.2026; CI: 5/5 jobs зелёные `24938330375`; `pytest -q` 1697 / `TEST_POSTGRES=1` 1823 / testcontainers 4).
**Связанные задачи в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md):** F5-C / § Level C (~line 724) — статус **READY** (по итогам этой планировочной сессии).
**Roadmap:** F5-A Phase 3 ✅ → F2 ✅ → F6 ✅ → F11 ✅ → **F5-C (эта)** → (вход в Волну 3 — F1 полная / F11 Phase 2 / F5-B при сигнале).
**Прецеденты (читать перед стартом):**
- [`START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md) — планировочный промпт, по которому собран этот спринт-промпт; § Open design questions решён ниже в § Decision Log.
- [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — структурный шаблон (pre-flight, шаги, gotchas, Risks, PR-checklist).
- [`F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) — образец PR-чеклиста с **karpathy-like** пометками.
- [`F5C_PR_CHECKLIST.md`](F5C_PR_CHECKLIST.md) — чеклист для тела PR (1:1 со списком ниже + karpathy-like + разбивка по коммитам).
- [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — Волна C ("память темы") — F5-C финализирует спецификацию.
- [`ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) — incremental контракт + Sprint D.1 (per-batch checkpointing, truthful `source_attempts`, billing-pause). F5-C наследует **per-batch checkpointing** D.1 (counter инкрементируется per-batch); **не использует** D.1-контракт `failed_stage='resummarize'` (по Decision #13 — F5-C post-processing с silent-log семантикой, исключение — billing-pause).

---

## Цель сессии

Добавить **F5-C: Evolving Topic Summaries** — `TopicCard` перестаёт быть статичным: при накоплении **N новых supporting items** в его `TopicBundle` тема **перезаписывает** свой `summary` + `scope_in` + `scope_out` через LLM, **переэмбеддит** обновлённый текст и **сохраняет предыдущую версию** в новой append-only таблице `topic_card_versions` (audit trail + опорная точка для будущих фичей).

**Закрывает последний пробел в Living KB-контракте:** темы знают о новых материалах (через scheduler hook D.1 + F11 evidence log), но **не помнят** их содержания — F5-C делает summary **функцией от потока supporting items**, а не одноразовым артефактом топикизации.

**North star одной строкой:** TopicCard.summary становится **функцией bundle.items**, обновляемой по дешёвому триггеру (счётчик), с полной историей изменений и одним новым LLM-стейджем (`resummarize`).

### MVP scope (одна сессия)

1. **Schema + migration** в `processing` БД:
   - Новая таблица `topic_card_versions` (append-only, FK на `topic_cards.id` ON DELETE CASCADE).
   - Три новых колонки в `topic_cards`: `last_summarized_at TIMESTAMPTZ NULL`, `summary_version INTEGER NOT NULL DEFAULT 1`, `new_items_since_last_summary INTEGER NOT NULL DEFAULT 0`.
   - Partial index `idx_topic_cards_resummarize_candidates` (only `WHERE new_items_since_last_summary > 0`).
   - Data-bootstrap: `UPDATE topic_cards SET last_summarized_at = updated_at::timestamptz` (см. gotcha #11).
2. **`TopicCardVersionRepo`** в `tg_parser/storage/sqlalchemy/topic_card_version_repo.py` + порт в `tg_parser/storage/ports.py` (`append_version`, `list_for_topic`, `get_latest`).
3. **Counter increment в `_update_bundles_for_assignments`** (`tg_parser/services/topicization_service.py:558`) — после успешного `topic_bundle_repo.add_items(...)` сделать `topic_card_repo.increment_resummary_counter(topic_id, by=len(bundle_items))` (новый метод репозитория). **Per-batch checkpointing-friendly** (D.1): инкремент идёт в той же транзакции, что bundle add, по batch'у — частичный сбой средины батча не теряет уже зафиксированные счётчики.
4. **`ResummarizationService`** в `tg_parser/services/resummarization_service.py`:
   - `find_candidates(channel_id, n_threshold)` — `topic_card_repo.list_resummarize_candidates(channel_id, threshold=n)` (использует partial index).
   - `resummarize_topic(topic_id, *, dry_run=False)` — Postgres advisory lock через `pg_try_advisory_xact_lock(hashtext(topic_id))` → загрузить bundle.items + предыдущий summary → LLM call (новый scope `resummarize`) → upsert новый `TopicCard.summary/scope_*/summary_version+1/last_summarized_at=now/new_items_since_last_summary=0` → append `TopicCardVersion` с `version_no=N+1` → `run_topic_embedding(channel_id, topic_ids=[topic_id], force=True)` → метрики.
   - `run_for_channel(channel_id, *, max_topics=K, max_tokens=T, max_duration_s=W)` — обёртка для scheduler с тремя cap'ами.
5. **Hook в scheduler** (`tg_parser/services/scheduler_service.py::_process_source`) — **между** `run_topic_embedding` (line ~172) и `run_watchlist_check_for_channel` (line ~189). Семантика отказа (Decision #13): F5-C — **post-processing**, mirror F11 silent-log, **НЕ** добавляет в `stage_errors` (иначе любой LLM-сбой пометит весь source-attempt как `success=False` через `success = not stage_errors` на line 229). **Единственное исключение** — `AnthropicBillingError` пробрасывается в `stage_errors`, чтобы сработала существующая billing-pause логика (line 220-225). Наблюдаемость F5-C — через выделенную метрику `tg_resummarize_total{status="error"}`, не через `failed_stage`.
6. **MCP + CLI tools (минимум 3):**
   - MCP `get_topic_versions(topic_id, limit=10)` — audit trail; ownership через `assert_channel_access` для каждого канала из `topic.sources`.
   - MCP `force_resummarize(topic_id)` — admin-only (`assert_admin`).
   - CLI `tg-parser topic versions <topic_id>` + `tg-parser topic resummarize <topic_id> [--dry-run]`.
   - **Bot tools — НЕ добавляем в MVP** (см. Decision Log #9: F5-C — backend-фича, не для агентского чата; добавим если появится сигнал).
7. **Новый prompt** `prompts/resummarize.yaml` (по конвенции `system:` / `user:` / `model:`; reload через MCP `reload_prompts` работает out-of-the-box).
8. **Per-stage LLM конфиг** — новый scope `resummarize` в `LLMConfigManager` (`tg_parser/processing/llm/factory.py::resolve_llm_config`); ENV `RESUMMARIZE_LLM_PROVIDER` / `RESUMMARIZE_LLM_MODEL` — по образцу `DIGEST_LLM_PROVIDER` / `DIGEST_LLM_MODEL`.
9. **Метрики** — `tg_resummarize_total{topic_id, status}`, `tg_resummarize_tokens_total{model, type=input|output}`, `tg_resummarize_duration_seconds{model}`, `tg_resummarize_skipped_total{reason}` (по образцу F11 metric pattern).
10. **Pydantic модели** — новый `TopicCardVersion` в `domain/models.py` + sync с **новым** `docs/contracts/topic_card_version.schema.json` (см. Соглашения).
11. **JSON-schema sync для `TopicCard`** — добавить новые поля `last_summarized_at`, `summary_version`, `new_items_since_last_summary` как **optional** в [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json) (НЕ в `required`, чтобы не сломать backward-compat по существующим JSON-payload'ам).
12. **`Table()` декларации** в `tg_parser/storage/sqlalchemy/_metadata.py`:
    - `topic_card_versions` — новая Table в `PROCESSING_METADATA`.
    - `topic_cards` — добавить три новые Column (`last_summarized_at`, `summary_version`, `new_items_since_last_summary`) + partial index.
    - `tg-parser db check --db processing` обязан показать `No new upgrade operations detected.`.

### Не входит в сессию (Phase 2, отдельный PR при сигнале)

- **TTL/retention для `topic_card_versions`** — храним всё; авто-удаление старых версий по возрасту/количеству — Phase 2.
- **`get_topic_history_diff(topic_id, version_a, version_b)`** MCP/CLI — diff двух версий; полезно, но не блокер MVP.
- **F6 digest на topic-level summary** (см. [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) line 949) — переключение `DigestService` с `processed_document.summary` на `topic_cards.summary` — отдельная задача после F5-C MVP, требует тюнинга промпта digest.
- **Bot tools для F5-C** — MCP/CLI достаточно для пилота (admin debug + audit). Если появится UX-сигнал «хочу видеть историю темы из бота» — добавим в Phase 2.
- **Удаление supporting items** (если bundle ужмётся при переназначении doc в другую тему) — текущий `_update_bundles_for_assignments` только **добавляет** (не удаляет); если в будущем появится путь "remove" — добавить отдельный триггер re-summarize с уменьшением счётчика.
- **Time-based триггер** (раз в N часов независимо от количества items) — Phase 2 по сигналу.
- **HTTP API endpoints** (`GET /api/v1/topics/{id}/versions`, `POST /api/v1/topics/{id}/resummarize`) — MCP/CLI достаточно.
- **Topic-level dedup при re-summarize** (если две темы оказались near-duplicates по обновлённому summary) — связано с F5-B, не часть F5-C.

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на c1c9f35 или новее
gh run list --branch main --limit 3              # CI на main зелёный?

# Local стек
docker compose ps                                # tg_parser_postgres healthy

# Текущий head processing-ветки (F5-C идёт в processing, не в ingestion!)
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT * FROM alembic_version_processing;"  # ожидание: c9d8e7f6a5b4
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "\d topic_cards"                            # увидеть существующую схему до правок

# Базовая регрессия — что ничего не сломалось локально с прошлой сессии
.venv/bin/pytest -q --tb=line | tail -5

# Прочитать § Level C дизайн-блок (после планировочной сессии — статус READY)
grep -nE "^#### Level C|F5-C" docs/notes/FUTURE_FEATURES.md | head -10

# Прочитать решения, на которых строится спринт
grep -nE "^### " docs/notes/START_PROMPT_SPRINT_F5C.md | head -30
```

**Critical reminder:** перед каждым `git commit` — `.venv/bin/ruff format <files>` + `.venv/bin/ruff check <files>` (sustained lesson из Sprints A → A.7 → F11 — иначе CI красный на line-length / I001 / B023).

**Pre-condition:** F11 (Topic Watchlist) и Sprint D.1 (Topicization Hardening) смерджены и задеплоены. F5-C опирается на:
- D.1 per-batch checkpointing pattern в `_update_bundles_for_assignments` (для инкремента счётчика без отката).
- D.1 `AnthropicBillingError` non-retryable классификации (для billing-pause при re-summarize — единственный путь, через который F5-C использует `stage_errors`/D.1-механизм; см. Decision #13).
- D.1 `failed_stage` колонка в `source_attempts` существует, но F5-C **не пишет** в неё `'resummarize'` (по Decision #13 — F5-C post-processing с F11-style silent-log, наблюдаемость через `tg_resummarize_total{status}`).
- F11 `run_topic_embedding(channel_id, force=False)` (line ~172 в `scheduler_service.py`) — F5-C хук стоит **сразу после** этого вызова и **до** F11 watchlist hook.

---

## Контекст: что мы знаем из аудита 26 апреля 2026

Все цифры/пути проверены grep'ом / Read'ом в HEAD `c1c9f35`, не из памяти.

### Что уже есть (foundation, переиспользуем)

| Слой | Что | Где |
|---|---|---|
| Topicization service | `run_incremental_topicization(channel_id, new_doc_refs)` уже вызывается scheduler'ом per source; внутри `_update_bundles_for_assignments` инкрементально добавляет items в bundle | `tg_parser/services/topicization_service.py:148` (`run_incremental_topicization`), `:558` (`_update_bundles_for_assignments`) |
| Topic embedding | `run_topic_embedding(channel_id, topic_ids=[...], force=True)` — UPSERT в `document_embeddings(entry_type='topic', topic_id=...)`; `_prepare_topic_text(summary, scope_in)` строит canonical embedding text | `tg_parser/services/embedding_service.py:253` (`run_topic_embedding`), `:245` (`_prepare_topic_text`) |
| Scheduler hook slots | `_process_source` уже имеет последовательность: `run_full_pipeline` → `run_incremental_topicization` → `run_topic_embedding(force=False)` → `run_watchlist_check_for_channel`. F5-C hook встаёт **между** `run_topic_embedding` и `run_watchlist_check_for_channel` | `tg_parser/services/scheduler_service.py:82` (`_process_source`), `:172` (`run_topic_embedding(force=False)`), `:189` (F11 hook) |
| Truthful `source_attempts` | Sprint D.1: `stage_errors[]` + `failed_stage` в `record_attempt`. **F5-C НЕ добавляет** stage `'resummarize'` в эту цепочку — по Decision #13 F5-C использует F11-style silent log (только `logger.exception`), кроме `AnthropicBillingError` (тот эскалируется в `stage_errors` для billing-pause). Это сознательный отказ: F5-C — post-processing (использует уже персистнутые artefacts), и его сбой не должен лгать про upstream-стейджи. | `tg_parser/services/scheduler_service.py:227-252` (D.1 record_attempt — F5-C сюда НЕ пишет), `:201-206` (F11 watchlist — образец silent log для F5-C), `:220-225` (`_pause_source_for_billing` — единственное место, где F5-C использует D.1-механизм) |
| Per-batch checkpointing | Sprint D.1 паттерн: каждый batch персистится сразу (assignments → bundles), частичный сбой не откатывает прежние | `ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` § Sprint D.1 (line 275+) |
| Billing-pause | `AnthropicBillingError` → `_pause_source_for_billing` → `rate_limit_until = now + BILLING_BLOCK_BACKOFF_S` (default 1h) | `tg_parser/processing/llm/errors.py`, `tg_parser/services/scheduler_service.py:_pause_source_for_billing`, `tg_parser/api/metrics.py::ANTHROPIC_BILLING_BLOCK_TOTAL` |
| Per-stage LLM config | `LLMConfigManager` resolves provider/model по приоритету: stage override → global override → stage .env → global .env. Уже работают scope `processing` / `topicization` / `rag` / `digest` | `tg_parser/processing/llm/factory.py:33` (`resolve_llm_config`), `tg_parser/processing/llm/factory.py:51` (`create_llm_client`) |
| YAML prompt + reload | `prompts/*.yaml` с `system:` / `user:` / `model:`; `reload_prompts` MCP tool работает hot — F5-C добавит `prompts/resummarize.yaml` без модификаций PromptLoader | `prompts/README.md`, `prompts/digest.yaml` (образец) |
| Topic embedding repo | `SAEmbeddingRepo.save(source_ref=card.id, entry_type='topic', topic_id=card.id, channel_ids=[...])` — UPSERT idempotent. F5-C вообще НЕ трогает схему `document_embeddings` | `tg_parser/storage/sqlalchemy/embedding_repo.py:22` |
| Topic card UPSERT | `SATopicCardRepo.upsert(card)` — `INSERT ... ON CONFLICT(id) DO UPDATE` всех полей; F5-C добавит метод `increment_resummary_counter(topic_id, by=N)` и `list_resummarize_candidates(channel_id, threshold=N)` | `tg_parser/storage/sqlalchemy/topic_card_repo.py:29` (`upsert`) |
| DB context | F5-C добавляет один новый context manager `resummarization_repos()` → `(topic_card_repo, topic_bundle_repo, topic_card_version_repo, db)`. Используется и в scheduler hook (`run_resummarize_for_channel`), и в MCP tool `get_topic_versions` (см. Шаг 9 — bundle_repo там игнорируется через `_bundle_repo`). Отдельный `topic_versions_repos` плодить НЕ нужно — race-боль не стоит дублирования session boilerplate. | `tg_parser/services/db_context.py:46` (`processing_repos`), `:137` (`watchlist_repos` как образец нового context) |
| Ownership / ACL | `assert_channel_access(user, channel_id)`, `assert_admin(user)` — для MCP `get_topic_versions` и `force_resummarize` | `tg_parser/auth/ownership.py:18`, `:29` |
| Test patterns | F11: `tests/test_f11_scheduler_hook.py` (3 теста — образец для F5-C scheduler hook); `tests/test_topicization*.py` (~80+ кейсов backward-compat baseline) | `tests/test_f11_scheduler_hook.py`, `tests/test_topicization.py`, `tests/test_incremental_topicization.py` |
| Conftest test_db | session-scoped alembic upgrade head + per-test TRUNCATE CASCADE (после Sprint A.7) | `tests/conftest.py:_alembic_initialized_test_db` |

### Чего нет (F5-C добавляет)

- Таблицы `topic_card_versions` (append-only audit log).
- Колонок `topic_cards.last_summarized_at`, `summary_version`, `new_items_since_last_summary`.
- LLM scope `resummarize` в LLMConfigManager.
- YAML prompt `prompts/resummarize.yaml`.
- `ResummarizationService` (новый файл).
- Метода `topic_card_repo.increment_resummary_counter` и `list_resummarize_candidates`.
- MCP tools `get_topic_versions` / `force_resummarize` и CLI команд `tg-parser topic versions/resummarize`.
- Pydantic модели `TopicCardVersion` + JSON-schema `topic_card_version.schema.json`.
- Метрик `tg_resummarize_*`.

---

## Decision Log (фиксация решений по 12 open questions из планировочного промпта)

> Один экран на спринт; обоснование каждого решения — в § Hidden gotchas / § Контекст.

| # | Вопрос | Решение | Краткое обоснование |
|---|---|---|---|
| 1 | Триггер re-summarize: счётчик / live COUNT / time-based | **Вариант A**: колонка `topic_cards.new_items_since_last_summary INTEGER NOT NULL DEFAULT 0`, инкремент в `_update_bundles_for_assignments` per-batch, обнуление после успешного re-summarize. **N по умолчанию = 5** (env `RESUMMARIZE_TRIGGER_N`, ENV-tunable). | Дешевле live COUNT (нет JOIN на bundle_items с временной фильтрацией каждый tick); согласован с D.1 per-batch checkpointing; partial index по `new_items > 0` делает скан кандидатов O(active topics), не O(all topics). N=5 — баланс между свежестью и LLM-стоимостью (cluster тема со 5 новыми items за 1-2 tick'а уже устарела по содержанию). Time-based — Phase 2 при сигнале. |
| 2 | Схема `topic_card_versions` | Append-only: `(id BIGSERIAL, topic_id TEXT FK CASCADE, version_no INTEGER, summary TEXT, scope_in_json TEXT, scope_out_json TEXT, supporting_items_count_at_time INTEGER, llm_provider VARCHAR(50), llm_model VARCHAR(200), prompt_version VARCHAR(50), created_at TIMESTAMPTZ DEFAULT NOW())`, `UNIQUE(topic_id, version_no)`, `INDEX (topic_id, created_at DESC)`. **`tags` / `anchors` / `title` НЕ снапшотим** (меняются редко / не меняются F5-C). `version_no` — глобальный per-topic монотонный (`MAX(version_no)+1`), нужен для UI и стабильных ссылок `topic:xxx@vN`. **Retention = храним всё** в MVP; TTL — Phase 2. | Минимально достаточно для audit + diff; `version_no` стабилен для людей и тестов (`created_at DESC LIMIT 1` ломается при clock skew); FK CASCADE — естественная семантика «удалили тему — версии не нужны». |
| 3 | Granularity: что переписываем | **`summary + scope_in + scope_out`** (полный snapshot card). `title` НЕ трогаем (входит в `id`-якорь, ломает читаемость). `tags` — Phase 2. | Дизайн-док § Level C прямо говорит «обновлённый summary, обновлённый scope». Без scope_in/scope_out тема дрейфует только в формулировке, но не в границах — нерелевантно для F11/RAG. Title/anchors не должны меняться, потому что `id = topic:<anchors[0].anchor_ref>` — смена id ломает FK с `topic_card_versions`, `topic_links`, `document_embeddings`, `watch_matches`. |
| 4 | Граничные случаи | (a) **Singleton → Cluster**: при re-summarize на singleton-теме, если bundle вырос до >=2 anchor с score, F5-C **может** перевести `type='cluster'` (validate_cluster_anchors не упадёт). Решение **минимальное в MVP**: оставляем `type` как есть; смену типа делает только полная топикизация. (b) **Удалённые items**: текущий `_update_bundles_for_assignments` **только добавляет** — счётчик никогда не уменьшается; если в будущем появится remove-путь, добавить отдельный триггер. (c) **Backfill / большой канал**: `RESUMMARIZE_MAX_PER_TICK = 10` (env), батчинг по 1 теме за один LLM call. (d) **Race condition** (cross-channel topic, два tick'а): Postgres advisory lock `pg_try_advisory_xact_lock(hashtext(topic_id))`; не взяли — `skip_reason='locked'`, метрика `tg_resummarize_skipped_total{reason='locked'}`. | Минимальный MVP: тип темы — стабилен; advisory lock — самый дешёвый race guard в Postgres (не требует таблицы locks). MAX_PER_TICK + advisory lock вместе ограничивают и flood, и double-call. |
| 5 | Куда хранить служебные поля | **Новые колонки в `topic_cards`**, не metadata JSONB: `last_summarized_at TIMESTAMPTZ NULL`, `summary_version INTEGER NOT NULL DEFAULT 1`, `new_items_since_last_summary INTEGER NOT NULL DEFAULT 0`. Partial index `idx_topic_cards_resummarize_candidates ON topic_cards(new_items_since_last_summary) WHERE new_items_since_last_summary > 0`. | Поля участвуют в WHERE/ORDER BY на каждом scheduler tick — индекс по JSONB полю стоит дороже и хуже планируется. Partial index экономит ~99% строк (большинство тем в покое). |
| 6 | LLM scope + стоимость | **Новый scope `resummarize`** в LLMConfigManager. ENV: `RESUMMARIZE_LLM_PROVIDER`, `RESUMMARIZE_LLM_MODEL`. Default — `openai/gpt-4o-mini` (дешёвый, ~$0.15/1M input — 100× дешевле topicization Sonnet 4). **Input strategy**: предыдущий summary + последние N supporting items (sliding window, не все items). | Re-summary — частая операция (раз на 5 новых items на cluster-тему ≈ 1-2 раза в день для активного канала); дешёвый model + sliding window держат TCO в десятки центов / месяц / канал. Per-stage конфиг → можно тюнить per канал в проде через `set_llm_config` без рестарта. |
| 7 | Re-embed | После успешного re-summarize: `await run_topic_embedding(channel_id=card.sources[0], topic_ids=[topic_id], force=True)`. Embedding text — `_prepare_topic_text(summary, scope_in)` (уже работает). UPSERT идемпотентен по `source_ref = card.id`. | Переиспользуем готовый поток F11/RAG; нет новых таблиц/колонок embedding'ов. `force=True` критичен — без него `run_topic_embedding` пропустит уже существующий embedding. |
| 8 | Hook placement в scheduler | **Вариант B**: F5-C hook **после** `run_topic_embedding(channel_id, force=False)` (line ~172) и **до** `run_watchlist_check_for_channel` (line ~189). | F11 watchlist должен скорить против актуальной модели темы — F5-C обновляет summary/embedding до того, как F11 берёт `topic_id` для матчинга новых docs. Альтернатива «F5-C после F11» оставила бы F11 на один tick за актуальной темой — нежелательно для UX. |
| 9 | MCP / Bot / CLI surface | **MCP (2)**: `get_topic_versions(topic_id, limit=10)` (audit, ownership через `assert_channel_access` для каждого `topic.sources`); `force_resummarize(topic_id)` (admin-only, `assert_admin`). **CLI (2)**: `tg-parser topic versions <topic_id>`, `tg-parser topic resummarize <topic_id> [--dry-run]`. **Bot — НЕ добавляем в MVP** (фича backend, не для агентского чата). | F5-C — backend-фича (D.1-style), пользователю не нужно подписываться/настраивать. `get_topic_versions` — для audit/debug; `force_resummarize` — для admin при дебаге. Bot tools раздуют `_TOOL_DECLARATIONS` без реального value (32 → 34); добавим если появится UX-сигнал. |
| 10 | Тестирование | Service-level (no DB) ~12-15 (триггер по N, версионирование, advisory lock skip, sliding window input, граничные cases); PG-gated ~5-7 (schema migration round-trip, `topic_card_versions` append-only, partial index работает); scheduler hook ~3 (по образцу `tests/test_f11_scheduler_hook.py`); MCP/CLI ~5-7. **Итого ~25-30 тестов**. | Меньше surface чем F11 (нет Bot, нет push, нет HTML rendering), но сложнее edge-cases re-summarize triggering — баланс примерно тот же. |
| 11 | Backward-compat / migration story | Все существующие `topic_cards` после миграции: `summary_version=1`, `last_summarized_at = updated_at::timestamptz` (data-bootstrap в той же ревизии), `new_items_since_last_summary = 0`. **Первый tick после деплоя НЕ запустит лавину re-summarize** — счётчик у всех = 0. F11 не использует `topic.summary` напрямую — F5-C его не ломает. F6 digest — отдельная задача (Phase 2). | Без data-bootstrap первый scheduler tick после деплоя при `last_summarized_at=NULL` мог бы срабатывать на первом же batch'е (если бы триггер использовал `last_summarized_at IS NULL OR new_items >= N`); но т.к. триггер построен на счётчике (не на `last_summarized_at`), bootstrap нужен только для UI/audit чтобы показать «тема никогда не пересуммаризировалась после миграции» != «тема никогда не имела summary». |
| 12 | Деплой / runaway-защита | Тройной бюджет per tick: `RESUMMARIZE_MAX_PER_TICK=10` (env) + `RESUMMARIZE_MAX_DURATION_S=60` (env) + `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` (env). `AnthropicBillingError` → существующий `_pause_source_for_billing` через D.1-механизм (source паузится на `BILLING_BLOCK_BACKOFF_S`). | Тройной cap защищает от runaway LLM bills + tick latency. Billing-pause переиспользует D.1 контракт без дублирования. |
| 13 | Семантика отказа scheduler-hook'а: «truthful failed_stage» vs «F11-style silent log» | **F11-style silent log + escalation для `AnthropicBillingError`**. Не-billing failure → `logger.exception(...)`, **НЕ** добавляется в `stage_errors`; source-attempt success не зависит от F5-C. Billing-error → `stage_errors.append(("resummarize", exc))` для срабатывания billing-pause (line 220-225 scheduler_service.py). Наблюдаемость — через `tg_resummarize_total{status="error"}` + Grafana alert `rate(...) > 0.1`. | F5-C — **post-processing** (использует уже персистнутые `topic_cards/bundles/embeddings`), а не core pipeline (D.1 категория, где `failed_stage` определяет, что персистится). При выборе «truthful» один сбой F5-C на канале неделю → `aggregate["sources_failed"]` 100% даже при здоровом ingestion+topicization+F11 (потому что `success = not stage_errors` на line 229). Это **misleading** про upstream и противоречит F11-прецеденту (line 201-206 — silent log). Billing-error эскалируется потому, что Anthropic budget — общий ресурс между стейджами. |

---

## Hidden gotchas

> Минимум по 1 на каждый разрешённый open question; нумерация совпадает с § Decision Log где это уместно.

1. **Counter increment идёт сразу после успешного `add_items`, eventual consistency** (Decision #1). `_update_bundles_for_assignments` делает `await topic_bundle_repo.add_items(topic_id, bundle_items)` (внутри `add_items` свой `session.commit()` — line 216 `topic_bundle_repo.py`) → затем `await topic_card_repo.increment_resummary_counter(topic_id, by=len(bundle_items))` (тоже свой `session.commit()`). Это **две отдельные транзакции** — strict atomicity не достигается без явного `async with session.begin()`, который ломает контракт `add_items`. Real-world impact: race-окно — микросекунды между двумя commit'ами; в случае kill-9 между ними счётчик отстанет от bundle на 1 step (восстановится при следующем `_update_bundles_for_assignments` для той же темы). Это приемлемая eventual consistency для F5-C (триггер с N=5 толерантен к погрешности ±1). **Главное** — увеличиваем счётчик **только после** успеха `add_items`: если `add_items` бросило `ValueError` (нет bundle) — `increment` НЕ вызываем. Тест: моки на `add_items` бросают исключение → `increment_resummary_counter` не вызван; happy path → `increment_resummary_counter` вызван с правильным `by=len(bundle_items)`.

2. **`version_no` через `MAX(...)+1` имеет race в одной БД** (Decision #2). Если два scheduler tick'а одновременно вызывают re-summarize одного `topic_id` — оба прочитают `MAX(version_no)=N` и оба попытаются вставить `N+1`. Защита: `UNIQUE(topic_id, version_no)` constraint + retry-on-conflict (один loop). Альтернатива — Postgres `SEQUENCE` per-topic, но это дороже. **Базовая защита уже есть**: advisory lock в `resummarize_topic` (Decision #4) гарантирует, что одновременно re-summarize одного topic'а не запускается; UNIQUE — second line of defense.

3. **`scope_in` / `scope_out` могут стать пустыми после re-summarize** (Decision #3). Pydantic `TopicCard.scope_in: list[str] = Field(min_length=1)` упадёт валидацией, если LLM вернул пустой массив. Защита в `ResummarizationService.resummarize_topic`: если `new_scope_in == []` — fallback на старые `scope_in`; залогировать `tg_resummarize_skipped_total{reason='empty_scope'}`. Тест: мок LLM возвращает пустой scope_in — тема **не** обновляется, версия НЕ создаётся.

4. **Singleton → Cluster — НЕ меняем `type` в MVP** (Decision #4a). `validate_cluster_anchors` Pydantic-валидатор требует `len(anchors) >= 2 AND все anchors имеют score`. Если просто скопировать `type='cluster'` без проверки — падение. В MVP: `type` сохраняется из исходной карточки; если bundle вырос — это уже зафиксировано в `bundle.items_count`, тип карточки приведём в соответствие при следующей **полной** топикизации (manual trigger). Тест: re-summarize singleton-темы → `type='singleton'` сохранён.

5. **Advisory lock — namespace collision** (Decision #4d). `pg_try_advisory_xact_lock(hashtext(topic_id))` использует int hash; теоретически два разных `topic_id` могут дать тот же hash → false collision. Defensive: использовать **двухключевую** форму `pg_try_advisory_xact_lock(int4_hash_constant, hashtext(topic_id))` где `int4_hash_constant = 0xF5C` (магическое число F5-C) — снижает риск collision со счёт-локом из других мест кода. Тест: два F5-C re-summarize-вызова разных тем не конфликтуют (нужен real PG, не SQLite-mock).

6. **Sliding window input — НЕ «recent N», а «top-N по приоритету»** (Decision #6). `BundleItem` не имеет `created_at`, **и порядок в `bundle.items[]` НЕ отражает время добавления**: `topic_bundle_repo.add_items` (line 200-206) пересортирует bundle на каждом вызове по `(role: anchor-first, -score, source_ref)`. Поэтому `bundle.items[-N:]` дал бы items с **низшим score / последние по алфавиту**, а не «недавние». Корректная стратегия для re-summarize: `bundle.items[:RESUMMARIZE_INPUT_WINDOW_N]` — берём **топ-N после сортировки add_items**, что естественно даёт `все anchors + N highest-score supports` (это и нужно: anchors определяют тему, top-score supports наиболее релевантны). Если в Phase 2 потребуется time-based selection — добавить `BundleItem.created_at` отдельной миграцией или JOIN с `processed_documents.processed_at` через `source_ref`. Тест: bundle из 50 items с разными score'ами + 3 anchors → input в LLM = первые 10 после сортировки add_items (3 anchors + 7 top-score supports).

7. **`run_topic_embedding(force=True)` cleanup OpenAI client** (Decision #7). `run_topic_embedding` создаёт OpenAI embedding client через `create_embedding_client()` и закрывает его в `finally: await client.close()`. F5-C вызывает его **внутри** `_process_source` per-channel-tick — это корректно (один client на один tick на один topic_id). НЕ кешировать client между topic'ами в одном tick'е — это ломает graceful degradation (если client сломался на topic A, topic B всё ещё попробует с свежим). Тест: проверить, что после `run_topic_embedding` для topic_id=X нет утечки OpenAI httpx-сессий.

8. **F5-C hook — F11-style silent log, кроме billing-error** (Decision #13). F5-C **НЕ** добавляет в `stage_errors` — это сознательный отказ от D.1-style `failed_stage='resummarize'`, потому что F5-C — post-processing (использует уже персистнутые artefacts), а не core pipeline. При выборе «truthful» один LLM-сбой пометил бы весь source-attempt как FAILED через `success = not stage_errors` (line 229) — `aggregate["sources_failed"]` начало бы лгать про upstream-стейджи. Mirror F11 watchlist hook (line 201-206 — только `logger.exception`). **Единственное исключение** — `AnthropicBillingError`: пробрасываем в `stage_errors`, чтобы сработала существующая billing-pause логика (line 220-225) — Anthropic budget общий между стейджами. Также: `stages_ok.append("resummarize")` **только если `rs_summary["resummarized"] > 0`** (mirror F11 `wl_summary["inserted"]` pattern). Тесты: (a) F5-C бросает `RuntimeError` → `stage_errors` пуст → `success=True`; (b) F5-C бросает `AnthropicBillingError` → `stage_errors == [("resummarize", ...)]` → `_pause_source_for_billing` вызван; (c) F5-C обработал 0 кандидатов → `stages_ok` не содержит `"resummarize"`.

9. **`get_topic_versions` ownership rule — `topic.sources` может быть мульти-канал** (Decision #9). Cross-channel тема имеет `sources = ["@chan1", "@chan2"]`. `assert_channel_access` нужно вызвать для **каждого** канала отдельно? Или достаточно **хотя бы одного**? Решение: **достаточно хотя бы одного** (если user имеет access к `@chan1`, ему видна тема `@chan1+@chan2` — это уже принято в `topic_card_repo.list_by_channels`). Wrapper helper: `await assert_topic_access(user, topic.sources)` который пробует каждый канал и падает, если ни один не прошёл. Тест: user с access только к `@chan1` видит cross-channel тему `@chan1+@chan2`, но не видит чисто `@chan2` тему.

10. **`force_resummarize` — admin-only, не owner** (Decision #9). Тема может иметь несколько каналов от разных owner'ов; force re-summarize — глобальная операция (LLM вызов, обновление shared state). Только admin может вызвать. Тест: non-admin user падает с `PermissionDenied`, даже если у него access к одному из каналов темы.

11. **Bootstrap data-migration: cast `updated_at::timestamptz` может упасть на edge-cases** (Decision #11). `topic_cards.updated_at` хранится как `String()` с форматом `"%Y-%m-%dT%H:%M:%SZ"` (см. `topic_card_repo.upsert` line 71). Cast `updated_at::timestamptz` на строке формата `"2025-12-13T12:00:00Z"` работает в Postgres напрямую (`Z` parsed как UTC). Защита: `WHERE updated_at IS NOT NULL AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'` — только валидный формат. **NB**: regex использует POSIX-классы `[0-9]`, а не Perl-style `\d` — оба работают в Postgres ~ движке, но POSIX — это стандартная переносимая форма (если когда-то Postgres переедет на строгий POSIX режим — `\d` сломается). Если ни одна row не подошла — fallback на `last_summarized_at = NOW()` отдельным `UPDATE WHERE last_summarized_at IS NULL`. Тест на real PG: миграция round-trip preserves data (topic, у которого был `updated_at='2025-12-13T12:00:00Z'`, после миграции имеет `last_summarized_at = '2025-12-13T12:00:00+00'`).

12. **Triple cap (per_tick / duration_s / tokens) — все три обязательны** (Decision #12). Только один cap — runaway scenario: `MAX_PER_TICK=10` без `MAX_TOKENS` → 10 cluster-тем × 50 items × 200 tokens = 100K input tokens / tick (если новый scope `resummarize` случайно настроен на Sonnet 4 — это $0.30 / tick × 24 tick / day × 30 days = $216 / месяц / канал). Все три cap'а проверяются в `ResummarizationService.run_for_channel`: после каждой темы — `if total_tokens >= MAX_TOKENS_PER_TICK or elapsed >= MAX_DURATION_S or topics_done >= MAX_PER_TICK: break + log + метрика`. Тест: проверить, что все три cap'а независимо тормозят run_for_channel.

13. **`LLM_SCOPES` — захардкожен tuple, ОБЯЗАНО править**. В `tg_parser/config/settings.py:739` объявлено `LLM_SCOPES = ("global", "processing", "topicization", "rag", "digest")` и `LLMConfigManager.set()` валидирует против этого tuple (line 817-818). Без добавления `'resummarize'` в этот tuple любой `set_llm_config(scope='resummarize', ...)` упадёт с `ValueError: Invalid scope 'resummarize'`. **MUST**: расширить tuple до `("global", "processing", "topicization", "rag", "digest", "resummarize")` + добавить `resummarize_llm_provider: str | None = None` и `resummarize_llm_model: str | None = None` в Settings (по образцу `digest_llm_provider` на line 165-166) — иначе `getattr(self._static, f"{stage}_llm_provider", None)` в `LLMConfigManager.resolve()` (line 856-859) вернёт None и упадёт фолбэк на global. PromptLoader сканирует `prompts/*.yaml` динамически — для него отдельных правок не нужно. Тест: после правки `reload_prompts()` → `loader.get_system_prompt("resummarize")` работает + `set_llm_config(scope='resummarize', provider='openai', model='gpt-4o-mini')` не падает.

14. **JSON-schema `topic_card.schema.json` sync — новые поля в `properties`, НЕ в `required`** (см. § Соглашения проекта). Существующие JSON-payload'ы тем (например, в export файлах F2 на старой версии кода) НЕ имеют новых полей — добавление в `required` сломает валидацию для старых артефактов. F5-C добавляет:
    ```json
    "last_summarized_at": { "type": "string", "format": "date-time", "description": "..." },
    "summary_version": { "type": "integer", "minimum": 1, "default": 1, "description": "..." },
    "new_items_since_last_summary": { "type": "integer", "minimum": 0, "default": 0, "description": "..." }
    ```
    в `properties`, но НЕ трогает `required`.

15. **CHANGELOG / FUTURE_FEATURES / ROADMAP — после merge обновить статус F5-C → ✅ DONE**. § Level C в `FUTURE_FEATURES.md` (line ~724) меняется на `DONE`; § «Пост-F5-A Phase 3» в `ROADMAP_V3_PRODUCTION_FIRST.md` (line ~389) — F5-C → ✅; Wave C в `ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — пометка «реализовано». Это часть commit 2/2 docs scope, не отдельный commit.

16. **Anthropic runaway-protection при `set_llm_config(scope='resummarize', provider='anthropic')`** (Decision #13). Default F5-C provider — OpenAI gpt-4o-mini, и `AnthropicBillingError` для него никогда не возникнет. Но admin может **в рантайме** переключить scope на Anthropic через MCP `set_llm_config` — и тогда: (a) если код F5-C ловит `Exception` обобщённо и не пробрасывает `AnthropicBillingError` — billing-pause НЕ сработает (silent-log проглотит ошибку), и каждый scheduler tick будет долбить Anthropic API, генерируя новые billing-errors и метрики. Защита: в scheduler-hook сначала `except AnthropicBillingError as billing_exc: stage_errors.append(("resummarize", billing_exc)); raise` (или просто `re-raise` без catch — гарантировать пропуск этого типа). И второй уровень: внутри `ResummarizationService.resummarize_topic` НЕ ловить `AnthropicBillingError` в обобщённом `except Exception` — пусть он улетает наверх. Тест: `set_llm_config(scope='resummarize', provider='anthropic')` + LLM client мок бросает `AnthropicBillingError` → `_pause_source_for_billing` вызван, source.rate_limit_until установлен.

---

## План шагов

### Шаг 1: Аудит готовой инфраструктуры (10 минут)

```bash
# Где живут pgvector + topic embeddings
grep -nE "entry_type=.topic.|run_topic_embedding" tg_parser/services/scheduler_service.py
grep -nE "entry_type=.topic.|run_topic_embedding" tg_parser/services/embedding_service.py | head

# Текущий contract scheduler_service по new_doc_refs + hook chain
grep -nE "new_doc_refs|run_incremental_topicization|run_topic_embedding|run_watchlist_check" tg_parser/services/scheduler_service.py | head -20

# Образец F11 scheduler hook
cat tests/test_f11_scheduler_hook.py | head -50

# Текущий head processing-ветки
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT * FROM alembic_version_processing;"

# F11 миграция как образец (но F11 = ingestion, F5-C = processing — структура та же, ветка другая)
ls migrations/versions/processing/ | tail -5
```

**Output:** строка-приговор «processing alembic head: c9d8e7f6a5b4», «scheduler hook chain: incremental_topicization → topic_embedding(force=False) → [F5-C INSERT HERE] → watchlist_check», «F11 hook test pattern: 3 теста, fast-path / happy / aclose-on-raise».

### Шаг 2: Schema + migration (25 минут)

Файл: `migrations/versions/processing/20260426_add_topic_card_versions.py` (next slot — сверь с `ls migrations/versions/processing/`; на 26.04.2026 текущий head = `c9d8e7f6a5b4` (`processed_at_to_timestamptz`), следующая ревизия для F5-C — её `down_revision`).

```python
"""add topic card versions + resummarize counters (F5-C)

Revision ID: <8 hex>
Revises: c9d8e7f6a5b4
Create Date: 2026-04-26

F5-C Evolving Topic Summaries:
- New table topic_card_versions (append-only audit log).
- Three new columns on topic_cards: last_summarized_at, summary_version,
  new_items_since_last_summary.
- Partial index for the resummarize-candidate scan.
- Data-bootstrap: copy topic_cards.updated_at into last_summarized_at
  (cast VARCHAR -> TIMESTAMPTZ; gotcha #11).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "<8 hex>"
down_revision: str | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Расширение topic_cards
    op.add_column(
        "topic_cards",
        sa.Column("last_summarized_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "topic_cards",
        sa.Column(
            "summary_version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "topic_cards",
        sa.Column(
            "new_items_since_last_summary",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # 2. Partial index — кандидаты для re-summarize
    op.create_index(
        "idx_topic_cards_resummarize_candidates",
        "topic_cards",
        ["new_items_since_last_summary"],
        postgresql_where=sa.text("new_items_since_last_summary > 0"),
    )

    # 3. Data-bootstrap (gotcha #11): для существующих тем выставляем
    # last_summarized_at = updated_at::timestamptz (или NOW(), если cast fails).
    # NB: regex использует POSIX-классы [0-9], а не Perl-style \d, для
    # максимальной переносимости (Postgres ~ движок поддерживает оба, но
    # POSIX — стандарт SQL).
    op.execute(
        sa.text(r"""
            UPDATE topic_cards
            SET last_summarized_at = updated_at::timestamptz
            WHERE last_summarized_at IS NULL
              AND updated_at IS NOT NULL
              AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
        """)
    )
    op.execute(
        sa.text("""
            UPDATE topic_cards
            SET last_summarized_at = NOW()
            WHERE last_summarized_at IS NULL
        """)
    )

    # 4. Append-only audit log
    op.create_table(
        "topic_card_versions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "topic_id",
            sa.Text,
            sa.ForeignKey("topic_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("scope_in_json", sa.Text, nullable=False),
        sa.Column("scope_out_json", sa.Text, nullable=False),
        sa.Column("supporting_items_count_at_time", sa.Integer, nullable=False),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(200), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "topic_id", "version_no", name="uq_topic_card_versions_topic_version"
        ),
    )
    op.create_index(
        "idx_topic_card_versions_topic_created",
        "topic_card_versions",
        ["topic_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_topic_card_versions_topic_created",
        table_name="topic_card_versions",
    )
    op.drop_table("topic_card_versions")
    op.drop_index(
        "idx_topic_cards_resummarize_candidates",
        table_name="topic_cards",
    )
    op.drop_column("topic_cards", "new_items_since_last_summary")
    op.drop_column("topic_cards", "summary_version")
    op.drop_column("topic_cards", "last_summarized_at")
```

Также добавить `Table()` декларации в `tg_parser/storage/sqlalchemy/_metadata.py`:
- Расширить существующий `Table("topic_cards", PROCESSING_METADATA, ...)` (line 451) тремя новыми Column.
- Добавить partial index в тот же Table().
- Добавить новую `Table("topic_card_versions", PROCESSING_METADATA, ...)` рядом с `topic_bundles` / `topic_links`.

Smoke:
```bash
.venv/bin/tg-parser db check --db processing       # No new upgrade operations detected
.venv/bin/tg-parser db upgrade --db processing     # ровно 1 ревизия применена
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "\d topic_cards" -c "\d topic_card_versions"
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT id, summary_version, last_summarized_at, new_items_since_last_summary FROM topic_cards LIMIT 5;"
```

### Шаг 3: Domain + JSON-schema sync (15 минут)

#### `tg_parser/domain/models.py` — новый `TopicCardVersion`

```python
class TopicCardVersion(BaseModel):
    """Append-only snapshot of a TopicCard summary/scope, written by F5-C
    each time the topic is re-summarized.

    Соответствует docs/contracts/topic_card_version.schema.json.
    """

    id: int = Field(ge=1, description="Surrogate primary key (BIGSERIAL)")
    topic_id: str = Field(description="FK -> topic_cards.id (ON DELETE CASCADE)")
    version_no: int = Field(ge=1, description="Per-topic monotonic version number")
    summary: str = Field(description="Snapshot of TopicCard.summary at this version")
    scope_in: list[str] = Field(min_length=1, description="Snapshot of scope_in")
    scope_out: list[str] = Field(min_length=1, description="Snapshot of scope_out")
    supporting_items_count_at_time: int = Field(
        ge=0, description="bundle.items count at the moment of re-summarize"
    )
    llm_provider: str | None = Field(None, description="openai|anthropic|gemini|ollama")
    llm_model: str | None = Field(None, description="LLM model id")
    prompt_version: str | None = Field(None, description="prompts/resummarize.yaml metadata.version")
    created_at: datetime = Field(description="Когда версия записана")
```

Также — расширить `TopicCard` тремя optional полями (для read-через-API):
```python
class TopicCard(BaseModel):
    # ... existing fields ...
    last_summarized_at: datetime | None = Field(
        None, description="When summary was last regenerated by F5-C"
    )
    summary_version: int = Field(
        default=1, ge=1, description="Monotonic counter, ++1 on each re-summarize"
    )
    new_items_since_last_summary: int = Field(
        default=0, ge=0, description="Counter for F5-C trigger"
    )
```

#### `docs/contracts/topic_card_version.schema.json` (новый)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "TopicCardVersion",
  "type": "object",
  "description": "Append-only snapshot of TopicCard summary/scope at a point in time. Written by F5-C ResummarizationService.",
  "required": [
    "id",
    "topic_id",
    "version_no",
    "summary",
    "scope_in",
    "scope_out",
    "supporting_items_count_at_time",
    "created_at"
  ],
  "properties": {
    "id": { "type": "integer", "minimum": 1 },
    "topic_id": { "type": "string" },
    "version_no": { "type": "integer", "minimum": 1 },
    "summary": { "type": "string" },
    "scope_in": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
    "scope_out": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
    "supporting_items_count_at_time": { "type": "integer", "minimum": 0 },
    "llm_provider": { "type": "string", "enum": ["openai", "anthropic", "gemini", "ollama"] },
    "llm_model": { "type": "string" },
    "prompt_version": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" }
  },
  "additionalProperties": true
}
```

#### `docs/contracts/topic_card.schema.json` — расширить `properties` (НЕ `required`!)

```json
"last_summarized_at": {
  "type": "string",
  "format": "date-time",
  "description": "Timestamp последней успешной re-summarize (F5-C). NULL до первого вызова после миграции, либо bootstrap'ed = updated_at."
},
"summary_version": {
  "type": "integer",
  "minimum": 1,
  "default": 1,
  "description": "Per-topic monotonic счётчик версий summary; стартует с 1 (бесшовная миграция), ++1 на каждый успешный re-summarize."
},
"new_items_since_last_summary": {
  "type": "integer",
  "minimum": 0,
  "default": 0,
  "description": "Счётчик новых supporting items с прошлой re-summarize; обнуляется после успеха. F5-C триггер: >= RESUMMARIZE_TRIGGER_N (default 5)."
}
```

### Шаг 4: Ports + Repo (25 минут)

#### `tg_parser/storage/ports.py` — добавить:

```python
class TopicCardVersionRepo(Protocol):
    async def append_version(
        self,
        *,
        topic_id: str,
        summary: str,
        scope_in: list[str],
        scope_out: list[str],
        supporting_items_count_at_time: int,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        prompt_version: str | None = None,
    ) -> TopicCardVersion:
        """Insert a new version row; version_no = MAX(version_no)+1 per topic_id.

        Idempotent on UNIQUE(topic_id, version_no) — caller may retry on
        IntegrityError (race with another tick); the second insert will
        compute a fresh MAX.
        """

    async def list_for_topic(
        self, topic_id: str, *, limit: int = 10
    ) -> list[TopicCardVersion]:
        """Return up to `limit` versions ordered by created_at DESC."""

    async def get_latest(self, topic_id: str) -> TopicCardVersion | None: ...
```

И в `TopicCardRepo` (Protocol) — два новых метода:
```python
async def increment_resummary_counter(self, topic_id: str, by: int = 1) -> None:
    """Atomically: UPDATE topic_cards SET new_items_since_last_summary += :by
    WHERE id = :topic_id."""

async def list_resummarize_candidates(
    self, channel_id: str | None = None, *, threshold: int
) -> list[TopicCard]:
    """Return cards with new_items_since_last_summary >= threshold.
    Uses partial index idx_topic_cards_resummarize_candidates."""

async def commit_resummary(
    self,
    topic_id: str,
    *,
    summary: str,
    scope_in: list[str],
    scope_out: list[str],
    prev_summary_version: int,
    summarized_at: datetime,
    metadata_extras: dict | None = None,
) -> bool:
    """Atomically apply re-summary OR abort if summary_version raced.

    Updates summary/scope_in/scope_out + increments summary_version +
    resets new_items_since_last_summary + sets last_summarized_at +
    updated_at, all in ONE statement guarded by
    WHERE summary_version = :prev_summary_version.

    Returns True if applied, False if version raced (caller should
    log + skip; advisory lock should have prevented this).
    Replaces the earlier separate `upsert + reset_after_resummary` pair
    that had a no-op race window (gotcha: WHERE never matched after
    upsert had already moved the version).
    """
```

#### `tg_parser/storage/sqlalchemy/topic_card_version_repo.py` (новый)

По образцу `topic_card_repo.py`. Ключевое — `append_version`:
```python
async def append_version(self, *, topic_id, summary, scope_in, scope_out, ...):
    next_version_query = text("""
        SELECT COALESCE(MAX(version_no), 0) + 1
        FROM topic_card_versions
        WHERE topic_id = :topic_id
    """)
    next_v = (await self.session.execute(next_version_query, {"topic_id": topic_id})).scalar()
    insert_query = text("""
        INSERT INTO topic_card_versions
          (topic_id, version_no, summary, scope_in_json, scope_out_json,
           supporting_items_count_at_time, llm_provider, llm_model, prompt_version)
        VALUES
          (:topic_id, :version_no, :summary, :scope_in_json, :scope_out_json,
           :count, :llm_provider, :llm_model, :prompt_version)
        RETURNING id, created_at
    """)
    row = (await self.session.execute(insert_query, {...})).fetchone()
    await self.session.commit()
    return TopicCardVersion(id=row.id, topic_id=topic_id, version_no=next_v, ...)
```

#### `tg_parser/storage/sqlalchemy/topic_card_repo.py` — добавить:

```python
async def increment_resummary_counter(self, topic_id: str, by: int = 1) -> None:
    await self.session.execute(
        text("""
            UPDATE topic_cards
            SET new_items_since_last_summary = new_items_since_last_summary + :by
            WHERE id = :topic_id
        """),
        {"topic_id": topic_id, "by": by},
    )
    await self.session.commit()

async def list_resummarize_candidates(
    self, channel_id: str | None = None, *, threshold: int
) -> list[TopicCard]:
    if channel_id is not None:
        sql = text("""
            SELECT ... FROM topic_cards
            WHERE new_items_since_last_summary >= :threshold
              AND sources_json LIKE :channel_pattern
            ORDER BY new_items_since_last_summary DESC
        """)
        params = {"threshold": threshold, "channel_pattern": f'%"{channel_id}"%'}
    else:
        sql = text("""
            SELECT ... FROM topic_cards
            WHERE new_items_since_last_summary >= :threshold
            ORDER BY new_items_since_last_summary DESC
        """)
        params = {"threshold": threshold}
    rows = (await self.session.execute(sql, params)).fetchall()
    return [self._row_to_model(r) for r in rows]

# commit_resummary (атомарный + version-check) — см. SQL выше в "Важно (gotcha)" блоке;
# сюда не дублируем чтобы не было двух источников правды.
```

**Важно (gotcha): `topic_card_repo.py` имеет хардкод-список колонок в 5 местах** — расширение `topic_cards` тремя колонками требует править ВСЕ из них (иначе либо INSERT упадёт по NOT NULL, либо SELECT не вернёт новые поля → Pydantic упадёт):

1. `upsert` (line 34-58) — INSERT INTO + ON CONFLICT DO UPDATE: добавить три колонки **только** в `INSERT INTO topic_cards (...)` и `VALUES (...)` (для пути новой темы — server defaults `1, NULL, 0`), **НЕ добавлять** в `DO UPDATE SET ...`. **Rationale (фикс real-bug #2 из self-review)**: единственный путь для апдейта `summary_version / last_summarized_at / new_items_since_last_summary` — это новый атомарный `commit_resummary` (см. ниже). Если разрешить `upsert` дёргать эти колонки в `DO UPDATE`, любой полный re-topicization run сбросит `new_items_since_last_summary` к нулю и стопнет F5-C триггер. В `params` dict (line 60-78) — три новых ключа для INSERT-пути (`card.summary_version`, `card.last_summarized_at` (или None), `card.new_items_since_last_summary`).

2. `get_by_id` (line 85-91) SELECT — добавить `last_summarized_at, summary_version, new_items_since_last_summary` в список колонок.

3. `list_by_channel` (line 105-112) SELECT — то же самое.

4. `list_by_channels` (line 137+) SELECT — то же самое.

5. `_row_to_model` — читать новые три колонки и передавать в `TopicCard(...)`.

Также **новый метод `commit_resummary` вместо ранее предложенного `reset_after_resummary`** (Шаг 7 баг #2 в self-review): объединить «обновление content», «инкремент version» и «reset counter» в **один атомарный UPDATE** с `WHERE summary_version = :prev_v` (optimistic version-check). Ранее предложенная пара `upsert + reset_after_resummary` была no-op race: `upsert` уже сдвигал version → `WHERE summary_version = :new_v - 1` всегда не матчил. Сигнатура:

```python
async def commit_resummary(
    self,
    topic_id: str,
    *,
    summary: str,
    scope_in: list[str],
    scope_out: list[str],
    prev_summary_version: int,
    summarized_at: datetime,
    metadata_extras: dict | None = None,
) -> bool:
    """Atomically apply re-summary OR abort if summary_version raced.

    Returns True on success, False if WHERE didn't match (race detected;
    advisory lock should have prevented this, but UNIQUE/version_check
    is the second line of defense per gotcha #2).
    """
    result = await self.session.execute(
        text("""
            UPDATE topic_cards SET
              summary = :summary,
              scope_in_json = :scope_in_json,
              scope_out_json = :scope_out_json,
              summary_version = summary_version + 1,
              last_summarized_at = :summarized_at,
              new_items_since_last_summary = 0,
              updated_at = :updated_at,
              metadata_json = COALESCE(:metadata_json, metadata_json)
            WHERE id = :topic_id
              AND summary_version = :prev_v
        """),
        {
            "topic_id": topic_id,
            "summary": summary,
            "scope_in_json": stable_json_dumps(scope_in),
            "scope_out_json": stable_json_dumps(scope_out),
            "summarized_at": summarized_at,
            "updated_at": summarized_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata_json": stable_json_dumps(metadata_extras) if metadata_extras else None,
            "prev_v": prev_summary_version,
        },
    )
    await self.session.commit()
    return result.rowcount > 0
```

`increment_resummary_counter` остаётся отдельным методом (его вызывает `_update_bundles_for_assignments`, не F5-C). `list_resummarize_candidates` — тоже без изменений.

### Шаг 5: Counter increment в `_update_bundles_for_assignments` (10 минут)

`tg_parser/services/topicization_service.py:558-602` — после успешного `topic_bundle_repo.add_items(topic_id, bundle_items)` добавить:

```python
if bundle_items:
    try:
        await topic_bundle_repo.add_items(topic_id, bundle_items)
        # F5-C: bump the resummarize counter atomically with the bundle add.
        # Per-batch checkpointing (D.1): if the next batch fails, the
        # counter increment for THIS batch is preserved.
        await topic_card_repo.increment_resummary_counter(
            topic_id, by=len(bundle_items)
        )
        logger.info(
            "Added %d items to bundle %s (%s); resummary counter bumped by %d",
            len(bundle_items), topic_id, method, len(bundle_items),
        )
    except ValueError:
        logger.warning("Bundle not found for topic %s, skipping", topic_id)
```

Проблема: `_update_bundles_for_assignments` сейчас принимает `topic_bundle_repo`, но не `topic_card_repo`. Изменить сигнатуру — добавить `topic_card_repo: TopicCardRepo` **keyword-only** параметр (`*, topic_card_repo`) и пробросить из всех call sites: **3 в `topicization_service.py`** (line 245, 320, 525) + 1 в `tests/test_cross_channel_topicization.py` (плюс возможные в других тест-файлах — проверить grep'ом перед PR). **NB про атомарность** (gotcha #1): и `topic_bundle_repo.add_items`, и `topic_card_repo.increment_resummary_counter` внутри делают `await self.session.commit()` — это **две отдельные транзакции**, не одна. Real-world impact: race-окно микросекундное, eventual consistency приемлемая (счётчик может разъехаться с bundle на 1 step при kill-9 между add_items и increment, восстановится на следующем `_update_bundles_for_assignments` вызове). Если требуется strict atomicity — обернуть оба вызова в общий `async with session.begin():` (но это ломает текущий контракт `add_items`, который сам коммитит). Рекомендация: оставить eventual consistency, переформулировать gotcha #1 на «увеличение и add_items идут друг за другом в одной session — race-window микросекундный, не строгий atomic». Тест: моки на `add_items` бросают исключение → `increment_resummary_counter` НЕ вызывается (что мы вызываем `increment` ПОСЛЕ успеха `add_items`).

### Шаг 6: Новый prompt + LLM scope (15 минут)

#### `prompts/resummarize.yaml` (новый)

```yaml
# TG_parser Resummarize Prompt (F5-C)
# Version: 1.0.0
#
# Промпт для пересуммаризации TopicCard при накоплении N новых supporting items.
# Вход: предыдущий summary + scope + последние N supporting items текстов.
# Выход: обновлённые summary + scope_in + scope_out (JSON).
#
# Edit and reload via MCP tool `reload_prompts`.
metadata:
  version: "1.0.0"
  description: "Topic re-summarization prompt (F5-C)"

system:
  prompt: |
    Ты ассистент-аналитик. Твоя задача — обновить краткое описание (summary)
    темы и её границы (scope_in / scope_out) на основе предыдущей версии и
    новых поступивших материалов.

    Правила:
    - Не выдумывай факты, которых нет ни в previous_summary, ни в new_items.
    - Если новые материалы расширяют тему — расширь scope_in.
    - Если новые материалы выходят за границы темы — НЕ включай их в summary,
      но можно добавить близкие, но нерелевантные аспекты в scope_out.
    - Сохраняй язык, в котором написан большинство материалов.
    - summary: 1–3 предложения, не более 500 символов.
    - scope_in: 2–6 коротких пунктов (что включено).
    - scope_out: 1–4 коротких пунктов (что не включено).

    Формат ответа — строго валидный JSON:
    {
      "summary": "...",
      "scope_in": ["...", "..."],
      "scope_out": ["...", "..."]
    }

user:
  template: |
    Тема: {topic_title}

    Текущий summary (версия {previous_version}):
    {previous_summary}

    Текущий scope_in: {previous_scope_in}
    Текущий scope_out: {previous_scope_out}

    Новые материалы за последний период ({new_items_count} штук):
    {new_items_text}

    Верни обновлённые summary + scope_in + scope_out в JSON.
  variables:
    - topic_title
    - previous_version
    - previous_summary
    - previous_scope_in
    - previous_scope_out
    - new_items_count
    - new_items_text

model:
  temperature: 0.2
  max_tokens: 800
```

#### `tg_parser/processing/llm/factory.py` — НЕ трогаем код

`resolve_llm_config(stage)` делегирует в `LLMConfigManager.resolve(stage)`, который через `getattr(self._static, f"{stage}_llm_provider", None)` и `getattr(self._static, f"{stage}_llm_model", None)` подхватит новый scope **автоматически** — но только при условии, что соответствующие два изменения сделаны:

#### `tg_parser/config/settings.py` — **ОБЯЗАТЕЛЬНЫЕ** правки (без них рантайм-config упадёт)

1. **Расширить `LLM_SCOPES` tuple на line 739:**
   ```python
   LLM_SCOPES = ("global", "processing", "topicization", "rag", "digest", "resummarize")
   ```
   Без этого `LLMConfigManager.set(scope="resummarize", ...)` упадёт с `ValueError: Invalid scope 'resummarize'` (валидация на line 817-818).

2. **Добавить два новых поля Settings рядом с line 165-166** (по образцу `digest_llm_provider`/`digest_llm_model`):
   ```python
   resummarize_llm_provider: str | None = None
   resummarize_llm_model: str | None = None
   ```
   Без этого `getattr(self._static, "resummarize_llm_provider", None)` всегда вернёт None, и резолв упадёт на global default — нельзя будет настроить через ENV `RESUMMARIZE_LLM_PROVIDER` / `RESUMMARIZE_LLM_MODEL`.

Pydantic Settings автоматически биндит ENV `RESUMMARIZE_LLM_PROVIDER` → `resummarize_llm_provider` (BaseSettings convention). Алиас не нужен.

```bash
grep -nE "LLM_SCOPES|digest_llm_provider|digest_llm_model" tg_parser/config/settings.py
```

### Шаг 7: ResummarizationService (50 минут)

#### `tg_parser/services/resummarization_service.py` (новый)

```python
"""F5-C: Evolving Topic Summaries.

Re-summarize TopicCard when its TopicBundle has accumulated N new
supporting items. Hook is invoked by the scheduler after
run_topic_embedding(force=False) and before
run_watchlist_check_for_channel — so F11 sees the freshest summary.
"""
import json
import time
from datetime import UTC, datetime

import structlog

from tg_parser.config import settings
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.processing.llm.factory import create_llm_client, resolve_llm_config
from tg_parser.processing.prompt_loader import PromptLoader
from tg_parser.services.embedding_service import run_topic_embedding
from tg_parser.storage.ports import (
    TopicBundleRepo, TopicCardRepo, TopicCardVersionRepo,
)

logger = structlog.get_logger(__name__)


class ResummarizationService:
    def __init__(
        self,
        *,
        topic_card_repo: TopicCardRepo,
        topic_bundle_repo: TopicBundleRepo,
        topic_card_version_repo: TopicCardVersionRepo,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.topic_card_repo = topic_card_repo
        self.topic_bundle_repo = topic_bundle_repo
        self.topic_card_version_repo = topic_card_version_repo
        self.prompt_loader = prompt_loader or PromptLoader()

    async def run_for_channel(
        self,
        channel_id: str,
        *,
        n_threshold: int | None = None,
        max_topics: int | None = None,
        max_duration_s: int | None = None,
        max_tokens_per_tick: int | None = None,
    ) -> dict[str, int]:
        """Find candidates and resummarize, respecting all three caps."""
        n = n_threshold if n_threshold is not None else settings.resummarize_trigger_n
        cap_topics = max_topics if max_topics is not None else settings.resummarize_max_per_tick
        cap_duration = max_duration_s if max_duration_s is not None else settings.resummarize_max_duration_s
        cap_tokens = max_tokens_per_tick if max_tokens_per_tick is not None else settings.resummarize_max_tokens_per_tick

        candidates = await self.topic_card_repo.list_resummarize_candidates(
            channel_id=channel_id, threshold=n
        )
        if not candidates:
            return {"candidates": 0, "resummarized": 0, "skipped": 0, "tokens": 0}

        start_at = time.time()
        tokens_used = 0
        done = 0
        skipped: dict[str, int] = {"locked": 0, "empty_scope": 0, "llm_error": 0, "cap": 0}

        for card in candidates[:cap_topics]:
            if time.time() - start_at >= cap_duration:
                skipped["cap"] += 1
                logger.info("F5-C cap_duration reached", elapsed=time.time() - start_at)
                break
            if tokens_used >= cap_tokens:
                skipped["cap"] += 1
                logger.info("F5-C cap_tokens reached", tokens_used=tokens_used)
                break
            try:
                outcome = await self.resummarize_topic(card.id)
                if outcome.get("status") == "ok":
                    done += 1
                    tokens_used += outcome.get("tokens", 0)
                else:
                    skipped[outcome.get("status", "llm_error")] = (
                        skipped.get(outcome.get("status", "llm_error"), 0) + 1
                    )
            except AnthropicBillingError:
                # gotcha #16: pробрасываем — billing-pause логика в scheduler hook
                # должна сработать. Иначе runaway: каждый tick ещё одна billing-error.
                raise
            except Exception as exc:
                logger.exception(
                    "F5-C resummarize_topic failed", topic_id=card.id, error=str(exc)
                )
                skipped["llm_error"] += 1

        return {
            "candidates": len(candidates),
            "resummarized": done,
            "skipped": sum(skipped.values()),
            "skipped_breakdown": skipped,
            "tokens": tokens_used,
        }

    async def resummarize_topic(self, topic_id: str) -> dict:
        """One-topic re-summarize with advisory lock + LLM call + version snapshot.

        Returns:
          {"status": "ok"|"locked"|"empty_scope"|"llm_error"|"no_bundle"|"no_card"|"version_raced",
           "tokens": int (if ok), "version_no": int (if ok)}

        NB: AnthropicBillingError NOT caught here — propagates to scheduler hook
        for billing-pause (Decision #13 + gotcha #16). Other LLM errors converted
        to status="llm_error" so the per-channel run keeps going.
        """
        # 1. Advisory lock — gotcha #5: two-key form to reduce false collision.
        # Lock acquired on topic_card_repo.session — same connection as the
        # commit_resummary UPDATE that follows. xact_lock auto-releases at commit.
        from sqlalchemy import text as sa_text

        F5C_LOCK_NS = 0xF5C
        locked_row = await self.topic_card_repo.session.execute(
            sa_text("SELECT pg_try_advisory_xact_lock(:ns, hashtext(:tid))"),
            {"ns": F5C_LOCK_NS, "tid": topic_id},
        )
        if not locked_row.scalar():
            return {"status": "locked"}

        card = await self.topic_card_repo.get_by_id(topic_id)
        if card is None:
            return {"status": "no_card"}

        bundle = await self.topic_bundle_repo.get_by_topic_id(topic_id)
        if bundle is None or not bundle.items:
            return {"status": "no_bundle"}

        # 2. Input selection — gotcha #6: bundle.items already sorted by
        # add_items() as (anchor-first, -score, source_ref). Top-N gives us
        # `all anchors + top-score supports`, which is what we want for
        # re-summarize. NOT bundle.items[-N:] — that would give worst-score /
        # alphabetical-tail items.
        window_n = settings.resummarize_input_window_n
        input_items = bundle.items[:window_n] if window_n > 0 else list(bundle.items)
        new_items_text = "\n".join(
            f"- [{it.source_ref}] (role={it.role.value}, score={it.score or 0:.2f}) "
            f"{it.justification or '(no justification)'}"
            for it in input_items
        )

        # 3. LLM call — manual timing (LLMResponse has no duration_s field).
        # gotcha #16: AnthropicBillingError must NOT be swallowed by generic
        # except — let it propagate to scheduler hook for billing-pause.
        provider, api_key, model = resolve_llm_config("resummarize")
        client = create_llm_client(provider=provider, api_key=api_key, model=model)
        sys_prompt = self.prompt_loader.get_system_prompt("resummarize")
        user_template = self.prompt_loader.get_user_template("resummarize")
        user_prompt = user_template.format(
            topic_title=card.title,
            previous_version=card.summary_version,
            previous_summary=card.summary,
            previous_scope_in=", ".join(card.scope_in),
            previous_scope_out=", ".join(card.scope_out),
            new_items_count=len(input_items),
            new_items_text=new_items_text,
        )
        model_settings = self.prompt_loader.get_model_settings("resummarize")
        t0 = time.perf_counter()
        try:
            # Real signature (tg_parser/processing/ports.py:57): first positional
            # arg is `prompt` (i.e. user prompt), system_prompt is keyword.
            resp = await client.generate_with_usage(
                user_prompt,
                system_prompt=sys_prompt,
                **model_settings,
            )
        finally:
            duration_s = time.perf_counter() - t0
            await client.close()

        # 4. Parse + validate
        try:
            parsed = json.loads(resp.text.strip())
            new_summary = str(parsed["summary"]).strip()
            new_scope_in = [str(s).strip() for s in parsed["scope_in"]]
            new_scope_out = [str(s).strip() for s in parsed["scope_out"]]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("F5-C LLM response unparseable", topic_id=topic_id, error=str(exc))
            self._record_metric(status="llm_error", model=f"{provider}/{model}", duration_s=duration_s)
            return {"status": "llm_error"}

        if not new_scope_in:  # gotcha #3
            logger.info("F5-C empty scope_in returned, skipping", topic_id=topic_id)
            self._record_metric(status="empty_scope", model=f"{provider}/{model}", duration_s=duration_s)
            return {"status": "empty_scope"}
        if not new_scope_out:
            new_scope_out = card.scope_out  # сохраняем старый если LLM не дал

        # 5. Append version snapshot ("before" — we want the snapshot of the
        # state we are LEAVING, so future diffs work). Done BEFORE the atomic
        # commit_resummary so we have provenance even if commit races out.
        prompt_version = self.prompt_loader.get_metadata("resummarize").get("version")
        await self.topic_card_version_repo.append_version(
            topic_id=topic_id,
            summary=card.summary,        # old summary — snapshot of "before"
            scope_in=card.scope_in,
            scope_out=card.scope_out,
            supporting_items_count_at_time=len(bundle.items),
            llm_provider=provider,
            llm_model=model,
            prompt_version=prompt_version,
        )

        # 6. Atomic commit_resummary — single UPDATE with optimistic
        # version-check (replaces broken `upsert + reset_after_resummary` pair
        # which was a no-op because upsert had already advanced summary_version).
        now = datetime.now(UTC)
        new_metadata = dict(card.metadata or {})
        new_metadata.update(
            {
                "resummarize_run_at": now.isoformat(),
                "resummarize_version_no": card.summary_version + 1,
                "resummarize_llm": f"{provider}/{model}",
            }
        )
        applied = await self.topic_card_repo.commit_resummary(
            topic_id,
            summary=new_summary,
            scope_in=new_scope_in,
            scope_out=new_scope_out,
            prev_summary_version=card.summary_version,
            summarized_at=now,
            metadata_extras=new_metadata,
        )
        if not applied:
            # Версия рейснулась с другим scheduler tick'ом, несмотря на advisory
            # lock (теоретически невозможно, но UNIQUE/version_check — second
            # line of defense per gotcha #2).
            logger.warning("F5-C commit_resummary raced; version snapshot kept",
                           topic_id=topic_id, prev_v=card.summary_version)
            self._record_metric(status="version_raced", model=f"{provider}/{model}", duration_s=duration_s)
            return {"status": "version_raced"}

        new_version_no = card.summary_version + 1

        # 7. Re-embed (force=True overrides existing embedding). Non-blocking.
        try:
            primary_channel = card.sources[0] if card.sources else None
            if primary_channel:
                await run_topic_embedding(
                    channel_id=primary_channel,
                    topic_ids=[topic_id],
                    force=True,
                )
        except Exception as exc:
            logger.warning("F5-C re-embed failed (non-blocking)",
                           topic_id=topic_id, error=str(exc))

        # 8. Metrics
        from tg_parser.api.metrics import record_resummarize_outcome
        record_resummarize_outcome(
            topic_id=topic_id,
            status="ok",
            input_tokens=resp.input_tokens or 0,
            output_tokens=resp.output_tokens or 0,
            duration_s=duration_s,
            model=f"{provider}/{model}",
        )

        return {
            "status": "ok",
            "version_no": new_version_no,
            "tokens": (resp.input_tokens or 0) + (resp.output_tokens or 0),
        }

    def _record_metric(self, *, status: str, model: str, duration_s: float) -> None:
        """Tiny helper for non-ok branches (no token data, but timing recorded)."""
        from tg_parser.api.metrics import record_resummarize_outcome
        record_resummarize_outcome(
            topic_id="-",
            status=status,
            input_tokens=0,
            output_tokens=0,
            duration_s=duration_s,
            model=model,
        )

    async def aclose(self) -> None:
        """No-op — clients are short-lived and closed in resummarize_topic."""
        return None
```

#### Settings (env vars) — `tg_parser/config/settings.py`

```python
# F5-C: Evolving Topic Summaries — cap'ы и input-window
resummarize_trigger_n: int = Field(default=5, ge=1, alias="RESUMMARIZE_TRIGGER_N")
resummarize_max_per_tick: int = Field(default=10, ge=1, alias="RESUMMARIZE_MAX_PER_TICK")
resummarize_max_duration_s: int = Field(default=60, ge=10, alias="RESUMMARIZE_MAX_DURATION_S")
resummarize_max_tokens_per_tick: int = Field(default=50000, ge=1000, alias="RESUMMARIZE_MAX_TOKENS_PER_TICK")
resummarize_input_window_n: int = Field(default=10, ge=1, alias="RESUMMARIZE_INPUT_WINDOW_N")

# F5-C LLM scope (см. Шаг 6 — уже добавлены в правках LLM_SCOPES + Settings):
# resummarize_llm_provider: str | None = None  # ENV: RESUMMARIZE_LLM_PROVIDER
# resummarize_llm_model: str | None = None     # ENV: RESUMMARIZE_LLM_MODEL
```

И обновить `ENV_VARIABLES_GUIDE.md` + `.env.example` + `env.production.example` — описать все 5 cap-переменных + два LLM-scope (`RESUMMARIZE_LLM_PROVIDER`, `RESUMMARIZE_LLM_MODEL`).

#### Метрики — `tg_parser/api/metrics.py`

```python
from prometheus_client import Counter, Histogram

RESUMMARIZE_TOTAL = Counter(
    "tg_resummarize_total",
    "Total F5-C re-summarize attempts by status",
    ["status"],  # ok|locked|empty_scope|llm_error|no_bundle|no_card|cap|version_raced|error
)
RESUMMARIZE_TOKENS = Counter(
    "tg_resummarize_tokens_total",
    "Tokens consumed by F5-C re-summarize calls",
    ["model", "type"],  # type: input|output
)
RESUMMARIZE_DURATION = Histogram(
    "tg_resummarize_duration_seconds",
    "Per-call latency of F5-C re-summarize",
    ["model"],
)

def record_resummarize_outcome(*, topic_id, status, input_tokens=0, output_tokens=0, duration_s=0.0, model=""):
    RESUMMARIZE_TOTAL.labels(status=status).inc()
    if status == "ok" and model:
        RESUMMARIZE_TOKENS.labels(model=model, type="input").inc(input_tokens or 0)
        RESUMMARIZE_TOKENS.labels(model=model, type="output").inc(output_tokens or 0)
        RESUMMARIZE_DURATION.labels(model=model).observe(duration_s or 0.0)
```

### Шаг 8: Scheduler integration (15 минут)

`tg_parser/services/scheduler_service.py::_process_source` — между line ~178 (после `run_topic_embedding(force=False)`) и line ~188 (перед `run_watchlist_check_for_channel`):

```python
                        try:
                            await run_topic_embedding(channel_id=channel_id, force=False)
                        except Exception as te:
                            logger.warning(
                                "Topic embedding failed for %s: %s", source_id, te
                            )
                    except Exception as e:
                        stage_errors.append(("incremental_topicization", e))
                        logger.error(...)

                    # F5-C: Evolving Topic Summaries hook (between F11-prep
                    # topic embedding and F11 watchlist check). Mirror F11's
                    # silent-log contract: F5-C failure is post-processing,
                    # MUST NOT pollute stage_errors (otherwise success=False
                    # via line 229 `success = not stage_errors`). Only
                    # AnthropicBillingError escalates so existing billing-pause
                    # logic at line 220-225 fires (Decision #13 + gotcha #16).
                    try:
                        rs_summary = await run_resummarize_for_channel(
                            channel_id=channel_id
                        )
                        if rs_summary["resummarized"] > 0:
                            stages_ok.append("resummarize")
                        logger.info(
                            "f5c_resummarize source=%s candidates=%d resummarized=%d "
                            "skipped=%d tokens=%d",
                            source_id,
                            rs_summary["candidates"],
                            rs_summary["resummarized"],
                            rs_summary["skipped"],
                            rs_summary["tokens"],
                        )
                    except AnthropicBillingError as billing_exc:
                        # gotcha #16: общий Anthropic budget — паузим source
                        # через существующий _pause_source_for_billing,
                        # триггерится через stage_errors на line 220-225.
                        stage_errors.append(("resummarize", billing_exc))
                        logger.warning(
                            "f5c_resummarize_billing_error source=%s "
                            "— pausing source", source_id,
                        )
                    except Exception as rs_exc:
                        # F11-style silent log (Decision #13). Не добавляем в
                        # stage_errors → success-rate метрика не страдает.
                        # Наблюдаемость через tg_resummarize_total{status}.
                        logger.exception(
                            "f5c_resummarize_failed source=%s error=%s",
                            source_id, rs_exc,
                        )

                    try:
                        wl_summary = await run_watchlist_check_for_channel(...)
                        ...
```

**NB про imports:** `AnthropicBillingError` уже импортирован в `scheduler_service.py` на line 13 (использует `_pause_source_for_billing`); добавлять не нужно. `run_resummarize_for_channel` объявить как module-level функцию рядом с `run_watchlist_check_for_channel` (НЕ self-import внутри `_process_source`).

И отдельная module-level функция `run_resummarize_for_channel` рядом с `run_watchlist_check_for_channel` (line 479):

```python
async def run_resummarize_for_channel(
    *, channel_id: str
) -> dict[str, int]:
    """F5-C scheduler hook entry point. Mirrors the F11 hook contract.

    Builds a fresh ResummarizationService against per-tick repos, dispatches
    candidates with all three caps, then tears everything down.

    Failure semantics (Decision #13):
      - Non-billing exception propagates → caller wraps in `except Exception`
        + logger.exception (silent log, NOT in stage_errors).
      - AnthropicBillingError propagates → caller catches and pushes to
        stage_errors so existing billing-pause fires.
      - Net effect: F5-C outage never marks source-attempt as FAILED,
        except when billing is the root cause (where pause IS the right
        operational response).
    """
    from tg_parser.services.db_context import resummarization_repos
    from tg_parser.services.resummarization_service import ResummarizationService

    async with resummarization_repos() as (
        topic_card_repo, topic_bundle_repo, topic_card_version_repo, _db
    ):
        service = ResummarizationService(
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            topic_card_version_repo=topic_card_version_repo,
        )
        try:
            return await service.run_for_channel(channel_id)
        finally:
            await service.aclose()
```

Добавить `resummarization_repos` в `tg_parser/services/db_context.py`:
```python
@asynccontextmanager
async def resummarization_repos():
    """Context manager for F5-C ResummarizationService (processing branch)."""
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SATopicCardRepo(session),
            SATopicBundleRepo(session),
            SATopicCardVersionRepo(session),
            db,
        )
    finally:
        await session.close()
```

### Шаг 9: MCP / CLI tools (35 минут)

#### MCP tools (`tg_parser/mcp_server.py`)

По образцу `get_topic_details` / `force_retopicize`:

```python
@mcp.tool()
async def get_topic_versions(
    topic_id: str,
    limit: int = 10,
    ctx: Context | None = None,
) -> dict:
    """Список версий summary темы (audit trail F5-C).

    Returns:
        {"topic_id": str, "current_version": int, "versions": [
            {"version_no": int, "summary": str, "scope_in": list,
             "scope_out": list, "supporting_items_count_at_time": int,
             "llm_model": str | None, "created_at": str}, ...
        ]}
    """
    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    # NB: переиспользуем resummarization_repos — там уже есть card_repo +
    # version_repo (bundle_repo не нужен здесь, просто игнорируем). Отдельный
    # topic_versions_repos плодить не надо, чтобы не дублировать session
    # boilerplate в db_context.py.
    async with resummarization_repos() as (
        card_repo, _bundle_repo, version_repo, _db
    ):
        card = await card_repo.get_by_id(topic_id)
        if card is None:
            raise ValueError(f"Topic {topic_id} not found")
        # gotcha #9: достаточно access хотя бы к одному каналу темы
        await assert_topic_access(user, card.sources)
        versions = await version_repo.list_for_topic(topic_id, limit=limit)
    return {
        "topic_id": topic_id,
        "current_version": card.summary_version,
        "versions": [v.model_dump(mode="json") for v in versions],
    }


@mcp.tool()
async def force_resummarize(topic_id: str, ctx: Context | None = None) -> dict:
    """Ручной триггер F5-C re-summarize (admin only).

    Bypasses the N-threshold trigger and immediately re-summarizes the topic.
    Useful for debugging or for manual data refresh. Subject to the same
    advisory-lock semantics — if another tick is already re-summarizing,
    returns status='locked'.
    """
    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    assert_admin(user)  # gotcha #10
    async with resummarization_repos() as (card_repo, bundle_repo, version_repo, _db):
        service = ResummarizationService(
            topic_card_repo=card_repo,
            topic_bundle_repo=bundle_repo,
            topic_card_version_repo=version_repo,
        )
        try:
            return await service.resummarize_topic(topic_id)
        finally:
            await service.aclose()
```

Хелпер `assert_topic_access` — добавить в `tg_parser/auth/ownership.py`:
```python
async def assert_topic_access(user: CurrentUser, topic_sources: list[str]) -> None:
    """Topic visible if user has access to AT LEAST ONE of its sources.

    Admin (allowed_channel_ids=None) always passes. Mirrors the existing
    semantics of TopicCardRepo.list_by_channels.
    """
    if user.allowed_channel_ids is None:
        return
    if not any(src in user.allowed_channel_ids for src in topic_sources):
        raise PermissionDenied(
            f"No access to topic with sources={topic_sources}"
        )
```

#### CLI commands (`tg_parser/cli/topic_cmd.py` — расширить если есть, иначе новый файл)

```bash
tg-parser topic versions <topic_id> [--limit 10]
tg-parser topic resummarize <topic_id> [--dry-run]
```

Регистрация в `tg_parser/cli/app.py`:
```python
from tg_parser.cli import topic_cmd as topic_app
app.add_typer(topic_app.app, name="topic")
```

### Шаг 10: Tests (75 минут)

Целевая дельта: ~25-30 новых тестов.

| Файл | Покрытие |
|---|---|
| `tests/test_resummarization_service.py` (новый) | service-level (no DB), ~12-17 тестов: `run_for_channel` no candidates / N candidates / triple cap (per_tick / duration / tokens) / `AnthropicBillingError` пробрасывается (gotcha #16); `resummarize_topic` happy / advisory lock skip / empty_scope skip / LLM JSON error / no_bundle / no_card / version_raced (commit_resummary вернул False) / **input window — `bundle.items[:N]` после сортировки add_items** (anchors + top-score supports, НЕ `[-N:]` с alphabetical-tail items, gotcha #6); метрики записываются с правильным `duration_s` (через `time.perf_counter()`). Все моки на `topic_card_repo`, `topic_bundle_repo`, `topic_card_version_repo`, LLM client. |
| `tests/test_resummarize_counter.py` (новый) | test для `_update_bundles_for_assignments` extension: при успешном `add_items` → `increment_resummary_counter` вызван с правильным `by`; при `add_items` падении (ValueError) → counter НЕ инкрементится. |
| `tests/test_topic_card_version_repo.py` (новый, PG-gated) | `append_version` — `version_no = MAX+1` per topic; `UNIQUE(topic_id, version_no)` constraint; `list_for_topic` ordered by `created_at DESC` + limit; `get_latest`. |
| `tests/test_f5c_topic_card_repo.py` (новый, PG-gated) | `increment_resummary_counter` атомарно (конкурентные UPDATE'ы дают сумму, не race); `list_resummarize_candidates(threshold)` использует partial index (EXPLAIN ANALYZE покажет `Index Scan`); `commit_resummary` — атомарный single-UPDATE: при `prev_summary_version` совпадает → версия инкрементится, content / counter / `last_summarized_at` обновляются; при mismatch → возвращает `False`, ничего не пишется (race-detection). |
| `tests/test_f5c_migration.py` (новый, под `TEST_TESTCONTAINERS=1`) | alembic upgrade на чистом PG → схема корректна; data-bootstrap: тема с `updated_at='2025-12-13T12:00:00Z'` после migration имеет `last_summarized_at='2025-12-13T12:00:00+00'`; `summary_version=1`, `new_items=0`. |
| `tests/test_f5c_scheduler_hook.py` (новый, по образцу `test_f11_scheduler_hook.py`) | 3 теста: (1) `run_resummarize_for_channel` no candidates → fast return; (2) happy path → `ResummarizationService.run_for_channel` вызван, `aclose` вызван; (3) если `run_for_channel` бросает — `aclose` всё равно вызван, `repos` контекст закрыт. |
| `tests/test_f5c_mcp_tools.py` (новый) | `get_topic_versions` ownership: admin видит, owner видит, non-owner с access к одному из каналов темы видит, non-owner без access падает; `force_resummarize` admin only. |
| `tests/test_f5c_cli.py` (новый) | `tg-parser topic versions <id>` через `CliRunner` — happy + topic not found; `tg-parser topic resummarize <id> --dry-run` НЕ вызывает LLM, но возвращает structure с current_version. |
| `tests/test_topicization*.py` | **backward-compat baseline** — НЕ должны сломаться. После изменения сигнатуры `_update_bundles_for_assignments` (добавлен параметр `topic_card_repo`) — обновить call sites в существующих тестах (мокать `topic_card_repo` через MagicMock с `increment_resummary_counter = AsyncMock()`). |

Patterns:
- Service тесты — моки всех repos через `MagicMock()` + `AsyncMock()`; LLM client — moc возвращает фиксированный JSON.
- PG-gated — `postgres_settings` fixture из `conftest.py` (после Sprint A.7).
- Scheduler hook — pattern `_patch_hook` из `test_f11_scheduler_hook.py`.

### Шаг 11: Lint + format

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
```

### Шаг 12: Документация

| Файл | Что обновить |
|---|---|
| `docs/notes/FUTURE_FEATURES.md` § Level C (~line 724) | Статус → **✅ MVP DONE 26.04.2026**. Зафиксировать триггер N=5, схему `topic_card_versions`, hook placement (Variant B), MCP/CLI surface (no Bot), 5 ENV vars. |
| `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` § «Пост-F5-A Phase 3» (~line 389) | Строка F5-C → ✅ Выполнено 26.04.2026 (commit `<hash>`). Следующий пункт — F1 полная (Волна 3) или F11 Phase 2 при сигнале. |
| `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` Волна C (line 59-64) | Пометка «реализовано 26.04.2026»; ссылка на CHANGELOG. |
| `docs/USER_GUIDE.md` | Новый раздел «Evolving Topic Summaries (F5-C)» — как видеть историю версий через `tg-parser topic versions`, что меняется в `get_topic_details` (новые поля). |
| `docs/MCP_AGENT_GUIDE.md` | Новые MCP tools `get_topic_versions` / `force_resummarize` с примерами. Поле `summary_version` / `last_summarized_at` в `get_topic_details` ответе. |
| `docs/architecture.md` | Раздел про `topic_cards` — добавить три новые колонки. Раздел про новую таблицу `topic_card_versions`. Hook chain: incremental_topicization → topic_embedding → resummarize → watchlist_check. |
| `docs/contracts/topic_card.schema.json` | Расширены `properties` тремя новыми полями (НЕ `required`!). |
| `docs/contracts/topic_card_version.schema.json` | Новый файл. |
| `prompts/README.md` | Добавить `resummarize.yaml` в таблицу файлов. |
| `ENV_VARIABLES_GUIDE.md` + `.env.example` + `env.production.example` | 5 F5-C переменных + 2 LLM-scope. |
| `CHANGELOG.md` | Новая секция § Sprint F5-C — Evolving Topic Summaries (2026-04-26) — Added / Changed / Tests / Migration / Documentation. |

### Шаг 13: Атомарный коммит + push + watch CI

Опция A — один коммит. Опция B — два коммита (schema+service+counter+тесты ядра vs scheduler hook+MCP/CLI+docs). **Рекомендуется B**: чище review, отдельный fail-domain в CI.

```bash
# Commit 1/2 — schema + service + counter + тесты ядра
git add migrations/versions/processing/20260426_add_topic_card_versions.py \
        tg_parser/storage/sqlalchemy/_metadata.py \
        tg_parser/domain/models.py \
        docs/contracts/topic_card.schema.json \
        docs/contracts/topic_card_version.schema.json \
        tg_parser/storage/ports.py \
        tg_parser/storage/sqlalchemy/topic_card_version_repo.py \
        tg_parser/storage/sqlalchemy/topic_card_repo.py \
        tg_parser/services/topicization_service.py \
        tg_parser/services/resummarization_service.py \
        tg_parser/services/db_context.py \
        tg_parser/processing/llm/factory.py \
        tg_parser/config/settings.py \
        tg_parser/api/metrics.py \
        prompts/resummarize.yaml \
        tests/test_resummarization_service.py \
        tests/test_resummarize_counter.py \
        tests/test_topic_card_version_repo.py \
        tests/test_f5c_topic_card_repo.py \
        tests/test_f5c_migration.py
git commit -m "$(cat <<'EOF'
feat(F5C): Evolving Topic Summaries — schema + service + counter (1/2)

TopicCard.summary becomes a function of bundle.items: when N new
supporting items have been appended to a topic's bundle, the topic
re-summarizes itself (LLM call), re-embeds the result (force=True),
and persists an immutable `topic_card_versions` snapshot.  Triggered
by a per-row counter (`new_items_since_last_summary`) maintained
inside `_update_bundles_for_assignments` so per-batch checkpointing
(D.1) is preserved.

This commit lays the persistence + service foundation:

- migrations/versions/processing/<id>_add_topic_card_versions.py:
  * topic_card_versions append-only audit log
    (UNIQUE(topic_id, version_no), FK CASCADE)
  * three new columns on topic_cards (last_summarized_at,
    summary_version, new_items_since_last_summary)
  * partial index idx_topic_cards_resummarize_candidates
  * data-bootstrap: last_summarized_at = updated_at::timestamptz
- tg_parser/storage/sqlalchemy/_metadata.py: Table() declarations
  drift-checked by alembic-guardrail CI job.
- tg_parser/domain/models.py: TopicCardVersion + TopicCard extended
  (last_summarized_at, summary_version, new_items_since_last_summary
  as optional fields; backward-compat preserved).
- docs/contracts/topic_card.schema.json: new fields added to
  `properties` only (NOT to `required` — backward-compat).
- docs/contracts/topic_card_version.schema.json: new file.
- TopicCardVersionRepo port + SAImpl: append_version, list_for_topic,
  get_latest.
- TopicCardRepo extended: increment_resummary_counter,
  list_resummarize_candidates(threshold), commit_resummary (атомарный
  single-UPDATE с optimistic version-check).
- _update_bundles_for_assignments: counter increment
  alongside topic_bundle_repo.add_items in the same batch transaction
  (per-batch checkpointing preserved per D.1).
- ResummarizationService: advisory-lock guarded resummarize_topic
  (LLM call -> append_version -> upsert card -> reset counter ->
  re-embed via existing run_topic_embedding(force=True)); triple-cap
  run_for_channel (max_topics, max_duration_s, max_tokens_per_tick).
- prompts/resummarize.yaml: new YAML prompt (system/user/model);
  reload_prompts MCP tool picks it up out-of-the-box.
- LLM scope `resummarize` in LLMConfigManager (env vars
  RESUMMARIZE_LLM_PROVIDER / RESUMMARIZE_LLM_MODEL); default
  openai/gpt-4o-mini.
- Five new env vars: RESUMMARIZE_TRIGGER_N (5),
  RESUMMARIZE_MAX_PER_TICK (10), RESUMMARIZE_MAX_DURATION_S (60),
  RESUMMARIZE_MAX_TOKENS_PER_TICK (50000),
  RESUMMARIZE_INPUT_WINDOW_N (10).
- Metrics: tg_resummarize_total{status}, _tokens_total{model,type},
  _duration_seconds{model}.
- Tests: ~18 unit + repo + migration tests covering trigger / cap /
  advisory lock / empty_scope / LLM JSON error / sliding window /
  schema round-trip / data-bootstrap.

Scheduler hook + MCP/CLI tools + the rest of the docs follow in
commit 2/2.

Closes F5-C foundation per docs/notes/START_PROMPT_SPRINT_F5C.md.
EOF
)"

# Commit 2/2 — scheduler hook + MCP/CLI + остальные тесты + docs
git add tg_parser/services/scheduler_service.py \
        tg_parser/mcp_server.py \
        tg_parser/auth/ownership.py \
        tg_parser/cli/topic_cmd.py \
        tg_parser/cli/app.py \
        tests/test_f5c_scheduler_hook.py \
        tests/test_f5c_mcp_tools.py \
        tests/test_f5c_cli.py \
        docs/USER_GUIDE.md \
        docs/MCP_AGENT_GUIDE.md \
        docs/architecture.md \
        docs/notes/FUTURE_FEATURES.md \
        docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md \
        docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md \
        prompts/README.md \
        ENV_VARIABLES_GUIDE.md \
        .env.example \
        env.production.example \
        CHANGELOG.md
git commit -m "$(cat <<'EOF'
feat(F5C): Evolving Topic Summaries — scheduler hook + MCP/CLI (2/2)

Wires F5-C into the scheduler tick and adds the user-facing surface
for the persistence layer from commit 1/2.

- services/scheduler_service.py: run_resummarize_for_channel hook
  added between run_topic_embedding(force=False) and
  run_watchlist_check_for_channel — F11 watchlist now scores against
  the freshest topic summary.  Decision #13 — F11-style silent log:
  non-billing failure → logger.exception (NOT in stage_errors so
  source-attempt success isn't affected); AnthropicBillingError →
  stage_errors → existing _pause_source_for_billing fires.
  Pipeline + watchlist never blocked (graceful degradation).
- mcp_server.py: 2 new tools.
  * get_topic_versions(topic_id, limit=10): ownership via
    assert_topic_access (visible if user has access to AT LEAST ONE
    of topic.sources — mirrors TopicCardRepo.list_by_channels).
  * force_resummarize(topic_id): admin-only manual trigger;
    advisory-lock semantics still apply.
- auth/ownership.py: assert_topic_access(user, topic_sources) helper.
- cli/topic_cmd.py: `tg-parser topic versions <id>` and
  `tg-parser topic resummarize <id> [--dry-run]`.
- 11 new tests covering scheduler hook fast-path / happy / aclose-
  on-raise; MCP ownership matrix (admin / owner / non-owner with
  access to one source / non-owner without access); CLI happy + dry-
  run.
- Docs: § Level C in FUTURE_FEATURES.md → ✅ MVP DONE; ROADMAP_V3 +
  karpathy-roadmap updated; new USER_GUIDE / MCP_AGENT_GUIDE
  sections; architecture.md schema bullets; ENV_VARIABLES_GUIDE +
  env.example for 7 new env vars.

MVP scope:
- Trigger: counter-based (RESUMMARIZE_TRIGGER_N=5); no time-based
  trigger in MVP.
- Versioning: append-only; full retention; TTL/diff API → Phase 2.
- Surface: MCP (2) + CLI (2); Bot tools intentionally NOT added.
- Topic-level digest (F6 ↔ F5-C link from FUTURE_FEATURES line 949)
  → Phase 2.
- Singleton → Cluster type promotion stays in full topicization,
  not F5-C re-summarize.

Verification: pytest --tb=short -q → baseline (1697) + ~28 passed,
0 failures.  TEST_POSTGRES=1 pytest -q → baseline (1823) + ~10
passed.  ruff format + check clean.  CI green (5/5 jobs).

Roadmap: F5-C ✅ — closes Wave C of the karpathy-like Living KB
roadmap and the last gap in the Living KB contract.  Next big step:
Wave 3 — F1 full (DB + versions + A/B prompts) or F11 Phase 2
(batch/silent notify) when production metrics signal.
EOF
)"

git push origin main
gh run watch
```

---

## Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| Data-bootstrap UPDATE падает на edge-case формата `topic_cards.updated_at` | Low | gotcha #11: regex-фильтр по строгому ISO-8601, fallback на `NOW()` отдельным UPDATE. Тестируется в `test_f5c_migration.py` на `TEST_TESTCONTAINERS=1`. |
| LLM возвращает невалидный JSON (или `scope_in=[]`) | Medium | gotcha #3: Pydantic `min_length=1` для `scope_in` упадёт; F5-C ловит `(JSONDecodeError, KeyError, ValueError)` и возвращает status `empty_scope` / `llm_error`, метрика инкрементится, версия НЕ создаётся. Тест: моки LLM возвращают `{}` / пустой scope_in / битый JSON. |
| Race condition на cross-channel теме (два scheduler tick'а одновременно) | Medium | gotcha #5: advisory lock `pg_try_advisory_xact_lock(0xF5C, hashtext(topic_id))` + `UNIQUE(topic_id, version_no)` second line of defense. Если оба прошли lock — UNIQUE constraint поймает второй, можно retry один раз с фрешим `MAX(version_no)`. |
| Runaway LLM cost при backfill / большом канале | Low | gotcha #12: triple-cap (`MAX_PER_TICK=10`, `MAX_DURATION_S=60`, `MAX_TOKENS_PER_TICK=50000`). Default model — `gpt-4o-mini` (~$0.15/1M input). Метрика `tg_resummarize_tokens_total{model}` мониторится через Prometheus. |
| F5-C hook ломает F11 watchlist (изменился contract `run_topic_embedding`) | Low | F5-C НЕ меняет `run_topic_embedding` сигнатуру и НЕ меняет `entry_type='topic'` контракт; только вызывает `force=True` для одной темы за раз. F11 продолжает читать embeddings через `embedding_repo.get_by_source_ref(topic_id)`. Тест: F11 hook test остаётся зелёным. |
| Backward-compat: существующие тесты `_update_bundles_for_assignments` падают из-за нового параметра `topic_card_repo` | Medium | Изменить сигнатуру с `keyword`-only argument (`*, topic_card_repo`) — тесты с позиционными args упадут rare. Проверить `tests/test_topicization*.py` + `tests/test_incremental_topicization.py` + `test_cross_channel_topicization.py` — обновить call sites. Дельта ~5-10 правок в существующих тестах. |
| Singleton тема с расширившимся bundle получает `type='singleton'` несмотря на >= 2 anchors | Low (intentional) | Decision #4a: тип темы в MVP не меняется F5-C — это работа полной топикизации. Тест: re-summarize singleton оставляет `type='singleton'`. Phase 2: добавить smart promotion if user signals. |
| Pydantic `TopicCard` пытается валидировать `scope_in/min_length=1` при чтении старых данных где scope пуст | Low | Все существующие `topic_cards` уже соблюдают `min_length=1` (валидация на upsert). После F5-C — тоже (gotcha #3 защищает). Backward-compat по существующим JSON-payload'ам — `last_summarized_at`/`summary_version`/`new_items` — optional поля с default'ами. |
| `reload_prompts` MCP tool не подхватывает `prompts/resummarize.yaml` (старый PromptLoader hardcode) | Low | gotcha #13: PromptLoader сканирует `prompts/*.yaml` без хардкода списка. Проверить grep'ом перед PR: `grep -rn "topicization\|processing\|supporting_items\|digest" tg_parser/processing/prompt_loader.py` — если есть hardcoded список, добавить `'resummarize'`. |
| Rollback после push | Low | `git revert <commit2> <commit1>` + ручной `tg-parser db downgrade --db processing --revisions 1 --yes`. Downgrade: `topic_card_versions` дропается, три колонки `topic_cards` дропаются. F11 watchlist + F6 digest продолжают работать (изоляция через FK CASCADE и отсутствие чтения F5-C полей в F11/F6 коде). |

**Rollback:** `git revert HEAD~1 HEAD` → `git push` → CI восстановит код. Затем `docker compose run --rm tg_parser tg-parser db downgrade --db processing --revisions 1 --yes` на VPS — миграция откатится, новая таблица + 3 колонки исчезнут, остальные F-фичи продолжают работать (нет cross-FK от других таблиц). История версий тем (если успели накопиться за время production) — теряется навсегда; но MVP F5-C только-только запустился, потери минимальны.

---

## PR checklist (компактный — расширенная версия в `F5C_PR_CHECKLIST.md`)

**Канон для вставки в GitHub PR:** расширенная версия с пометками **karpathy-like** и порядком коммитов 1/2 · 2/2 — в [`F5C_PR_CHECKLIST.md`](F5C_PR_CHECKLIST.md).

- [ ] Миграция `migrations/versions/processing/<id>_add_topic_card_versions.py` создана; `tg-parser db check --db processing` → `No new upgrade operations detected.`; `Table()` декларации в `_metadata.py` синхронны.
- [ ] Data-bootstrap в миграции: `topic_cards.last_summarized_at = updated_at::timestamptz` для существующих тем, fallback на `NOW()` (gotcha #11).
- [ ] `TopicCardVersion` Pydantic + `docs/contracts/topic_card_version.schema.json` (новый) + расширение `topic_card.schema.json` (`properties`, не `required`).
- [ ] `TopicCardVersionRepo` (port + SAImpl): `append_version` / `list_for_topic` / `get_latest`; `UNIQUE(topic_id, version_no)` constraint работает.
- [ ] `TopicCardRepo` расширен: `increment_resummary_counter` / `list_resummarize_candidates(threshold)` (использует partial index) / `commit_resummary` (атомарный single-UPDATE с `WHERE summary_version = :prev_v` + content + counter reset; **заменяет** ранее предложенную пару `upsert + reset_after_resummary`, которая была no-op race).
- [ ] Counter increment в `_update_bundles_for_assignments` — в той же транзакции, что `add_items`; per-batch checkpointing сохранён (gotcha #1).
- [ ] `prompts/resummarize.yaml` создан; `reload_prompts` подхватывает (gotcha #13).
- [ ] `tg_parser/config/settings.py`: `LLM_SCOPES` расширен `("..", "resummarize")` (line ~739) **И** добавлены поля `resummarize_llm_provider: str | None = None`, `resummarize_llm_model: str | None = None` (рядом с `digest_llm_provider` line ~165). Без обоих — `LLMConfigManager.set(scope="resummarize", ...)` падает / `resolve` фоллбечит на global. ENV: `RESUMMARIZE_LLM_PROVIDER` / `RESUMMARIZE_LLM_MODEL` (default `openai/gpt-4o-mini`).
- [ ] `ResummarizationService.resummarize_topic` — advisory lock (`pg_try_advisory_xact_lock(0xF5C, hashtext(topic_id))`), input — `bundle.items[:RESUMMARIZE_INPUT_WINDOW_N]` (top-N **после** сортировки `add_items`: anchors + top-score supports; gotcha #6), `client.generate_with_usage(user_prompt, system_prompt=..., **model_settings)` (правильная сигнатура из `processing/ports.py:57`), `duration_s` через `time.perf_counter()` (нет в `LLMResponse`), append `topic_card_versions` snapshot ДО `commit_resummary`, re-embed `force=True` (best-effort), метрики.
- [ ] `ResummarizationService.run_for_channel` — triple cap (`MAX_PER_TICK` / `MAX_DURATION_S` / `MAX_TOKENS_PER_TICK`).
- [ ] Scheduler hook `run_resummarize_for_channel` в `_process_source` — между `run_topic_embedding(force=False)` и `run_watchlist_check_for_channel`. **Семантика отказа (Decision #13)**: не-billing exception → `logger.exception` (mirror F11, **НЕ** в `stage_errors` — иначе ломается `success = not stage_errors`); `AnthropicBillingError` → `stage_errors.append(("resummarize", exc))` для срабатывания billing-pause (line 220-225). `stages_ok.append("resummarize")` только если `rs_summary["resummarized"] > 0`. `run_resummarize_for_channel` — module-level функция, НЕ self-import внутри `_process_source`.
- [ ] MCP tools (2): `get_topic_versions` (ownership via `assert_topic_access`) + `force_resummarize` (admin-only via `assert_admin`).
- [ ] CLI: `tg-parser topic versions <id>` + `tg-parser topic resummarize <id> [--dry-run]`.
- [ ] Bot tools — НЕ добавлены в MVP (Decision #9).
- [ ] Метрики: `tg_resummarize_total{status}` (ok / locked / empty_scope / llm_error / no_bundle / no_card / cap / version_raced / error), `_tokens_total{model,type}`, `_duration_seconds{model}`. Алерт: `rate(tg_resummarize_total{status="error"}[5m]) > 0.1` в Grafana — единственный signal про сломанный F5-C (поскольку `failed_stage` его не трекает по Decision #13).
- [ ] Singleton-тема после re-summarize сохраняет `type='singleton'` (Decision #4a).
- [ ] Empty scope_in / битый JSON LLM — версия НЕ создаётся, метрика инкрементится (gotcha #3).
- [ ] Tests: ~25-30 новых, service + repo + scheduler hook + MCP + CLI + migration round-trip (PG/testcontainers).
- [ ] `pytest --tb=short -q` зелёный, baseline + ~28 passed.
- [ ] `TEST_POSTGRES=1 pytest -q` зелёный, baseline + ~10 passed.
- [ ] `ruff format` + `ruff check .` чистые.
- [ ] CI: 5/5 jobs зелёные.
- [ ] Существующие `tests/test_topicization*.py` НЕ сломаны (~80+ кейсов backward-compat).
- [ ] `docs/USER_GUIDE.md` — новый раздел F5-C.
- [ ] `docs/MCP_AGENT_GUIDE.md` — описания 2 новых tools, новые поля в `get_topic_details`.
- [ ] `docs/architecture.md` — schema + hook chain.
- [ ] `docs/notes/FUTURE_FEATURES.md` § Level C → ✅ MVP DONE; явно прописан scope, Phase 2 в backlog.
- [ ] `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — F5-C → ✅, следующая фича явно помечена.
- [ ] `docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md` Волна C — реализовано.
- [ ] `ENV_VARIABLES_GUIDE.md` + `.env.example` + `env.production.example` — 7 новых env vars (5 cap'ов + 2 LLM).
- [ ] `CHANGELOG.md` — секция Sprint F5-C — Evolving Topic Summaries (2026-04-26).
- [ ] Commit messages содержат: `feat(F5C)`, breaking changes (нет), verification numbers, ссылку на дизайн-док § Level C.

---

## После F5-C — что дальше

Согласно зафиксированной 26 апреля 2026 последовательности:

1. **F1 полная** (Configurable Prompt System DB + версии + A/B) — Волна 3 пункт 3.3 (~2 сессии). Прямое дополнение F5-C: `prompts/resummarize.yaml` становится первым кандидатом на A/B-тестирование (сравнить качество summary для разных промптов на одних и тех же bundle.items).
2. **F11 Phase 2** — `notify_mode=batch` через digest-инфраструктуру и `silent` (только evidence log) — отдельным PR при сигнале из метрик `tg_watchlist_matches_total{score_bucket}` (если default 0.6 даёт шум).
3. **F5-B (near-duplicate via embedding ≥ 0.97)** — отложен до сигнала из метрики `tg_dedup_duplicates_detected_total{channel_id}`. F5-A Phase 3 (content-hash) уже снимает ~80%; near-dup Phase 3.5 — отдельный PR при подтверждении.
4. **F5-C Phase 2 features** — TTL для `topic_card_versions`, `get_topic_history_diff(topic_id, version_a, version_b)`, time-based триггер, F6 digest на topic-level summary, smart singleton→cluster promotion. Все — отдельными PR при сигнале.
5. **DI-5** (operational backfill 4 каналов) — параллельный ops-таск, не требует фокуса; при включении нового канала или окне обслуживания.

**Совокупно:** F5-C закрывает **Волну C** karpathy-like roadmap (память темы) и **последний пробел в Living KB-контракте**. После этого продукт имеет полный цикл: **ingestion → processing → topicization → continuous summaries → user-defined alerts → scheduled digests** — все слои с persistent evidence, идемпотентностью, graceful degradation и наблюдаемостью. Готов к расширению на F1 (advanced prompt management) или F8-B (Redis/queue) для масштабирования.

---

## Связанные документы / артефакты (одним списком)

- [`docs/notes/START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md) — планировочный промпт; § Open design questions решён в Decision Log выше.
- [`docs/notes/F5C_PR_CHECKLIST.md`](F5C_PR_CHECKLIST.md) — расширенный PR-чеклист с karpathy-like пометками + разбивкой по коммитам 1/2 · 2/2.
- [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § Level C (line ~724) — после merge → ✅ MVP DONE.
- [`docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) — пост-F5-A treka, F5-C → ✅.
- [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — Волна C (lines 59-64).
- [`docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`](ARCHITECTURE_INCREMENTAL_TOPICIZATION.md) — incremental контракт + Sprint D.1; F5-C наследует **per-batch checkpointing** + billing-pause (но НЕ `failed_stage='resummarize'` — Decision #13).
- [`docs/notes/START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) — структурный шаблон.
- [`docs/notes/F11_PR_CHECKLIST.md`](F11_PR_CHECKLIST.md) — образец PR-чеклиста.
- [`docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`](START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md) — D.1 паттерн `failed_stage` / per-batch / billing-pause.
- [`docs/architecture.md`](../architecture.md) — текущая схема + контракты.
- [`docs/contracts/topic_card.schema.json`](../contracts/topic_card.schema.json) — расширяется F5-C (`properties`, не `required`).
- [`docs/contracts/topic_card_version.schema.json`](../contracts/topic_card_version.schema.json) — новый файл.
- [`docs/USER_GUIDE.md`](../USER_GUIDE.md) + [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) — обновляются.
- [`prompts/README.md`](../../prompts/README.md) + `prompts/resummarize.yaml` (новый).
- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) + `.env.example` + `env.production.example` — 7 новых env vars.
- Код-якоря: `tg_parser/services/topicization_service.py:148` (`run_incremental_topicization`), `:558` (`_update_bundles_for_assignments`); `tg_parser/services/scheduler_service.py:82` (`_process_source`), `:172` (`run_topic_embedding(force=False)` — F5-C hook сразу после), `:189` (`run_watchlist_check_for_channel` — F5-C hook сразу до), `:479` (`run_watchlist_check_for_channel` definition — образец для `run_resummarize_for_channel`); `tg_parser/services/embedding_service.py:253` (`run_topic_embedding`), `:245` (`_prepare_topic_text`); `tg_parser/services/db_context.py:46` (`processing_repos`), `:137` (`watchlist_repos` как образец); `tg_parser/processing/llm/factory.py:33` (`resolve_llm_config`); `tg_parser/auth/ownership.py:18`, `:29`; `tg_parser/storage/sqlalchemy/_metadata.py:451` (`topic_cards`), `:482` (`topic_bundles`); `migrations/versions/processing/20260420_processed_at_to_timestamptz.py` (head — `c9d8e7f6a5b4`).
- Тестовые шаблоны: `tests/test_f11_scheduler_hook.py` (3 теста — образец для `tests/test_f5c_scheduler_hook.py`), `tests/test_topicization*.py` + `tests/test_incremental_topicization.py` (~80+ кейсов backward-compat baseline; обновить call sites после изменения сигнатуры `_update_bundles_for_assignments`).
