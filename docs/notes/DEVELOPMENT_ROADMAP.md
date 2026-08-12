# Roadmap развития TG_parser (после Session 41)

> ⚠️ **SUPERSEDED** — этот roadmap актуален для v4.0.0 (март 2026). Актуальный roadmap: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md). Промежуточный [ROADMAP_V3](ROADMAP_V3_PRODUCTION_FIRST.md), на который этот баннер вёл раньше, сам DEPRECATED с 2026-05-13.

**Дата:** 25 марта 2026  
**Версия:** v4.0.0 (RAG integration complete, PG17 migration)  
**Статус:** Утверждён

---

## Текущее состояние

- Full pipeline: ingest → process → topicize → embed → export → search/ask
- PostgreSQL 17.9 (Docker: `pgvector/pgvector:pg17`), pgvector 0.8.2
- RAG: OpenAI `text-embedding-3-small`, cosine similarity, LLM Q&A
- Services layer, чистая архитектура, `db_context.py` (6 async context managers)
- Тестовый канал @labdiagnostica_logical: 1130 raw, 1128 processed, 80 тем
- Coverage: 77.4% (875/1130 документов покрыты темами)
- Успешность обработки: 99.82%

---

## Завершённые этапы

### P1: Инкрементальная обработка ✅ (Session 30)

- Scheduled pipeline (ingest → process → topicize) по расписанию
- `run_incremental_for_all_sources()` для активных источников
- APScheduler интеграция, `poll_interval_seconds`

### P2: Параллельная обработка ✅ (Session 31)

- `--concurrency` CLI, rate limiter, батчевая обработка
- Default concurrency 3-5, обработка 1000+ за минуты

### P3: Улучшение обработки комментариев ✅ (Session 32)

- Robust parsing для коротких/пустых комментариев
- Контекст родительского поста при обработке

### P4: Топикизация — fix bundles ✅ (Session 33)

- 80 тем (68 cluster + 12 singleton), coverage 77.4%
- Bundles содержат anchors + supporting items
- Programmatic keyword matching для supporting items

### Инкрементальная топикизация ✅ (Sessions 34-37)

Полный цикл реализован — от архитектуры до CLI:

**Session 34 — Планирование:**
- Архитектурный план в `ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`
- Двухфазный подход: keyword assign (0 tokens) + LLM discover (~20K tokens)

**Session 35 — Phase 1 (Keyword Assign):**
- `assign_documents_to_topics()` — программное сопоставление по keywords
- `_tokenize_topic_card()`, `_tokenize_document()`, `_compute_match_score()`
- Strong tokens (topics/summary) + weak tokens (text_clean) с весами
- `add_items()` — инкрементальное обновление bundles
- Scheduler интеграция: автоматический Phase 1 при новых документах

**Session 36 — Phase 2 (LLM Discover):**
- `discover_new_topics()` — LLM анализ для unassigned документов
- Три исхода: assign to existing, create new topic, mark unassignable
- Retry: 3 попытки на JSONDecodeError, fallback → all unassignable
- Промпты: `INCREMENTAL_DISCOVER_SYSTEM_PROMPT`, `build_incremental_discover_prompt`
- `TopicCard.metadata.origin = "discovered"` для новых тем

**Session 37 — Интеграция и CLI:**
- CLI `topicize --mode incremental` — Phase 1 + Phase 2 для uncovered docs
- CLI `topicize --mode assign-only` — только Phase 1 (0 LLM tokens)
- CLI `topicize --force` — полная re-topicization
- `run_incremental_topicization_for_uncovered()` — CLI entry point
- `_run_assign_only()` — Phase 1-only mode
- E2E тест: 10 topics, 20 docs (10 covered + 10 new), Phase 1 + Phase 2
- 39 тестов: 27 unit + 5 E2E + 2 uncovered-docs + 5 CLI dispatch

---

### Code Review (Session 38) ✅

**Цель:** Всестороннее ревью кода + аудит и подготовка детального плана рефакторинга.

**Результаты:**
- Каталог Database lifecycle: 13 call sites, двойная инициализация в 3 местах, до 5 DB lifecycles в pipeline run
- План инверсии services→api: 6 символов из `api/scheduler.py` → `services/background_scheduler.py`, 6 файлов обновить
- План DI миграции: 7 сервисов, порядок от `pipeline_service` (low) до `processing_service` (medium-high)
- Обнаружено: 10 layering violations (critical), 4 DRY issues (medium), 3 error handling gaps, 2 async/sync issues
- Диагноз 3 pre-existing test failures + конкретные исправления
- RAG рекомендации: pgvector, text-embedding-3-small, retrieval pipeline design

**Артефакты:** `docs/notes/START_PROMPT_SESSION39_PRE_RAG_REFACTORING.md`

---

### Pre-RAG рефакторинг (Session 39) ✅

**Цель:** Создать чистый архитектурный фундамент перед добавлением RAG-слоя.

**Результаты:**

**Refactoring #1 — Database lifecycle dedup** ✅:
- Создан `services/db_context.py` с 5 async context managers: `processing_repos()`, `ingestion_repos()`, `raw_and_processed_repos()`, `ingestion_state_repo()`, `ingestion_and_processing_repos()`
- Заменены 15 блоков `Database.from_settings / try / finally` в 6 сервисах
- Устранена двойная инициализация DB в `topicization_service.py`
- ~150 строк сэкономлено

**Refactoring #2 — Инверсия services → api** ✅:
- `BackgroundScheduler`, `setup_default_tasks`, `cleanup_expired_records`, `health_check_task` перемещены в `services/background_scheduler.py`
- `incremental_pipeline_task` перемещён в `services/scheduler_service.py`
- `api/scheduler.py` оставлен как re-export shim для обратной совместимости
- Циклическая зависимость `services → api → services` устранена

**Refactoring #3 — Удаление SQLite** ✅:
- Удалены `DatabaseConfig`, SQLite branches в `engine_factory.py`, `settings.py`, `health_checks.py`, `init_db.py`, `migrations/env.py`
- Удалён `aiosqlite` из зависимостей
- DDL-схемы обновлены: `AUTOINCREMENT` → `SERIAL PRIMARY KEY`
- Все ~9 тестовых файлов мигрированы на PostgreSQL test database
- PostgreSQL service добавлен в CI workflow

**Исправлены 3 pre-existing test failures:**
- `test_process_message_with_agent`: маркирован `@pytest.mark.integration`, исключён из default runs
- `test_full_pipeline_e2e`: добавлен `replies` в mock raw_payload для постов с комментариями
- `test_comments_ingestion_with_per_thread_cursors`: то же исправление

**517 passed, 24 skipped, 0 failures**

---

### Code Review (Session 40) ✅

**Цель:** Ревью результатов рефакторинга Session 39.

**Артефакты:** `docs/notes/SESSION40_CODE_REVIEW_REPORT.md`

---

### P5: RAG-интеграция ✅ (Session 41)

**Цель:** Векторный поиск по базе знаний, Q&A чат-бот по контенту каналов.

**Результаты:**

**pgvector + DDL:**
- `pgvector>=0.3.0` в requirements.txt
- Таблица `document_embeddings` с `vector(1536)` столбцом
- IVFFlat индекс `document_embeddings_vector_idx` (cosine ops, lists=100)
- `_ensure_pgvector()` — отдельная транзакция для CREATE EXTENSION (non-fatal)

**EmbeddingRepo (`storage/sqlalchemy/embedding_repo.py`):**
- `save()` / `save_batch()` — upsert с ON CONFLICT
- `get_by_source_ref()` — получение embedding по ключу
- `similarity_search(query_embedding, limit, threshold)` — cosine similarity через pgvector
- `count()`, `list_missing(channel_id)` — статистика и поиск документов без embeddings

**EmbeddingService (`services/embedding_service.py`):**
- `OpenAIEmbeddingClient` — обёртка OpenAI embeddings API
- `_prepare_text()` — формирование текста: `summary + text_clean[:500]`
- `run_embedding(channel_id, force)` — полная генерация embeddings
- `run_incremental_embedding(source_refs)` — инкрементальная генерация

**RetrievalService (`services/retrieval_service.py`):**
- `search(query, channel_id, limit)` — семантический поиск с ranked results
- `answer(question, channel_id)` — RAG Q&A: embed → search → LLM-генерация ответа с источниками

**CLI команды:**
- `tg-parser embed --channel <id> [--force]`
- `tg-parser search --query "..." [--channel] [--limit]`
- `tg-parser ask --question "..." [--channel]`

**API endpoints (`api/routes/rag.py`):**
- `POST /api/v1/search` — семантический поиск
- `POST /api/v1/ask` — Q&A с RAG

**Storage ports:**
- `DocumentEmbedding`, `SimilarityResult` dataclasses в `storage/ports.py`
- `EmbeddingRepo` abstract base class

**db_context.py:**
- Новый CM `embedding_repos()` — 6-й context manager
- `try/except/finally` для безопасной инициализации

**Background scheduler:**
- `_incremental_embedding_task()` — embed processed docs без embeddings
- Автоматический запуск по расписанию `poll_interval_seconds`

**Settings (`config/settings.py`):**
- `embedding_provider`, `embedding_model`, `embedding_batch_size`, `embedding_dimension`

**Тесты (`tests/test_embedding.py`):**
- 21 тест: EmbeddingRepo CRUD + similarity_search, EmbeddingService, RetrievalService, Settings, RAG schemas, db_context
- Автоматический skip если pgvector не доступен

**538 passed, 24 skipped, 0 failures**

---

### Миграция на PostgreSQL 17 ✅ (Session 41)

**Цель:** Обновить PostgreSQL 16 → 17 для pgvector 0.8.2 и long-term support.

**Результаты:**
- Docker: `pgvector/pgvector:pg17` (заменён `postgres:16-alpine`)
- `docker/init-db.sh` — auto-create `tg_parser_test` DB + pgvector на первом запуске
- CI: `pgvector/pgvector:pg17` + шаг "Enable pgvector extension"
- Удалён `docker-compose.dev.yml` (устаревший, SQLite-эра)
- Удалён нативный PostgreSQL 16 (Homebrew)
- Все данные мигрированы через pg_dump/pg_restore

---

## CLI-команды

```bash
# Pipeline
tg-parser run --channel <id>                    # Full pipeline
tg-parser run --channel <id> --skip-ingestion   # Process + topicize only

# Topicization
tg-parser topicize --channel <id>               # Полная topicization
tg-parser topicize --channel <id> --force       # Re-topicization
tg-parser topicize --channel <id> --mode incremental   # Phase 1 + Phase 2
tg-parser topicize --channel <id> --mode assign-only   # Phase 1 only (0 tokens)

# RAG
tg-parser embed --channel <id>                  # Embed all processed docs
tg-parser embed --channel <id> --force          # Re-embed all
tg-parser search --query "..." [--channel]      # Semantic search
tg-parser ask --question "..." [--channel]      # Q&A with RAG
```

---

## Текущие метрики

| Метрика | Значение |
|---------|----------|
| Documents | 1130 (906 posts + 224 comments) |
| TopicCards | 80 (68 cluster + 12 singleton) |
| Coverage | 77.4% (875/1130) |
| Avg items/bundle | 86.4 |
| Tests | 538 passed, 24 skipped, 0 regressions |
| PostgreSQL | 17.9 (Docker pgvector/pgvector:pg17) |
| pgvector | 0.8.2 |
| Embedding model | text-embedding-3-small (1536 dim) |

---

## Следующие этапы

### P6: Веб-интерфейс / дашборд

**Цель:** Визуализация результатов обработки.

**Что нужно:** Frontend (React/Vue/Streamlit), API endpoints для тем/документов/статистики.

---

### P7: Мульти-канальная аналитика

**Цель:** Кросс-канальные темы, сравнение каналов, единая база знаний.

---

### P8: Мониторинг и метрики

**Цель:** Prometheus exporters, Grafana дашборды, алерты на ошибки LLM.

---

## Оставшийся технический долг

Не блокирует разработку фич. Рекомендуется устранить перед P6.

### Высокий приоритет

- **DI в services** — repos передаются через параметры вместо прямых импортов. 7 сервисов, порядок от `pipeline_service` до `processing_service`. Рекомендовано в Session 38/40.

### Средний приоритет

- **`tokens_used` в `IncrementalTopicizeResult`** — пока 0, требуется изменение LLM client API для доступа к usage из API response
- **Batch splitting для `--mode incremental`** — при > 50 unassigned docs нужен split, текущий канал ~255 uncovered

### Низкий приоритет

- **`processing/` читает global config** (3 файла) — optional DI уже есть
- **`api/scheduler.py` re-export shim** — оставлен для обратной совместимости, можно удалить при следующем breaking change

### Закрыто (Session 42)

- ~~**Переименование `SQLite*Repo` → `SA*Repo`**~~ — 12 классов переименованы, ~226 ссылок обновлены в коде, тестах, скриптах и документации
- ~~**`OpenAIClient` прямой импорт в `pipeline.py`**~~ — мёртвый импорт удалён (1 строка)

---

**Подготовлено:** Session 37, обновлено Session 42  
**Следующий шаг:** P6 Веб-интерфейс
