# Session 41: P5 RAG-интеграция

**Дата:** [дата запуска]  
**Тип сессии:** Feature — RAG (Retrieval-Augmented Generation)  
**Предыдущая сессия:** Session 40 (Code Review — PASSED)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md` → P5

---

## Цель сессии

Реализовать векторный поиск по базе знаний TG_parser: embedding pipeline, pgvector storage, retrieval endpoint. По итогу — можно задавать вопросы на естественном языке к контенту каналов.

---

## Контекст проекта

### Текущее состояние (после Session 39-40)

- **Pipeline:** ingest → process → topicize → export — работает
- **Database:** PostgreSQL-only (localhost Homebrew), 3 логических engines через `engine_factory`
- **Данные:** 1130 raw, 1128 processed, 80 тем, coverage 77.4%
- **Services:** Чистая архитектура с `db_context.py` (5 async context managers)
- **Тесты:** 517 passed, 24 skipped, 0 failures (стабильно)

### Ключевые файлы для справки

```
tg_parser/
├── config/settings.py                    # Settings (PostgreSQL fields: db_host..db_pool_*)
├── services/
│   ├── db_context.py                     # 5 async CMs (pattern for new embedding_repos)
│   ├── processing_service.py             # CM example: raw_and_processed_repos()
│   ├── topicization_service.py           # CM example: processing_repos()
│   ├── export_service.py                 # Nested CMs example
│   ├── pipeline_service.py               # Full pipeline orchestration
│   ├── scheduler_service.py              # Incremental pipeline
│   ├── _wiring.py                        # create_processing_engine, create_session_factory
│   └── background_scheduler.py           # APScheduler tasks
├── storage/
│   ├── engine_factory.py                 # create_engine_from_settings(settings, db_name)
│   └── sqlalchemy/
│       ├── database.py                   # Database class (3 engines + sessionmakers)
│       ├── __init__.py                   # Re-exports (SQLite*Repo names — cosmetic debt)
│       ├── processed_document_repo.py    # SQLiteProcessedDocumentRepo
│       └── schemas/
│           └── processing_storage.py     # DDL для processed_documents, topic_* tables
├── domain/models.py                      # ProcessedDocument, TopicCard, TopicBundle
├── processing/
│   ├── llm/factory.py                    # create_llm_client(), resolve_llm_config()
│   └── topicization.py                   # TopicizationPipelineImpl
└── export/
    └── kb_mapping.py                     # map_message_to_kb_entry()
```

### Документация

- `docs/notes/SESSION40_CODE_REVIEW_REPORT.md` — ревью Session 39
- `docs/notes/DEVELOPMENT_ROADMAP.md` — roadmap (P5 section)
- `docs/notes/START_PROMPT_SESSION38_CODE_REVIEW.md` — полная структура проекта (разделы: модели, API, storage ports)

---

## Архитектурный план RAG

### Компоненты

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ ProcessedDoc │────▶│ Embedding    │────▶│ pgvector      │────▶│ Retrieval    │
│ (existing)   │     │ Pipeline     │     │ Storage       │     │ Endpoint     │
└─────────────┘     └──────────────┘     └───────────────┘     └──────────────┘
                          │                      │                      │
                    text-embedding-       vector similarity      Q&A with context
                    3-small (OpenAI)      search (cosine)        via LLM
```

### Шаг 1: pgvector + DDL

1. **Установить зависимость:** `pgvector` Python package
2. **CREATE EXTENSION:** `CREATE EXTENSION IF NOT EXISTS vector` в processing DB
3. **Новая таблица:**

```sql
CREATE TABLE IF NOT EXISTS document_embeddings (
  source_ref TEXT PRIMARY KEY REFERENCES processed_documents(source_ref),
  embedding vector(1536),    -- text-embedding-3-small dimension
  model TEXT NOT NULL,        -- "text-embedding-3-small"
  created_at TEXT NOT NULL,
  metadata_json TEXT          -- chunk info, token count etc.
);

CREATE INDEX IF NOT EXISTS document_embeddings_vector_idx
ON document_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

**Решение по engine:** Использовать **существующий `processing` engine** — embedding таблица в той же PostgreSQL базе рядом с `processed_documents`. Не нужен новый engine.

### Шаг 2: Embedding Service

```
tg_parser/services/embedding_service.py
```

- `run_embedding(channel_id, force=False)` — embed all processed documents
- `run_incremental_embedding(doc_refs)` — embed only new documents
- Использует `db_context.py` pattern → новый CM `embedding_repos()`
- Batching: OpenAI API supports batch embedding (up to 2048 inputs)
- Rate limiting: reuse existing `processing_concurrency` setting

**Новые Settings поля:**
```python
# Embedding Configuration
embedding_provider: str = "openai"
embedding_model: str = "text-embedding-3-small"
embedding_batch_size: int = 100
embedding_dimension: int = 1536
```

### Шаг 3: Embedding Repository

```
tg_parser/storage/sqlalchemy/embedding_repo.py
```

- `save(source_ref, embedding, model, metadata)` — upsert embedding
- `get_by_source_ref(source_ref)` → embedding vector
- `similarity_search(query_embedding, limit=10, threshold=0.7)` → list of (source_ref, score)
- `count()` → total embeddings
- `list_missing(channel_id)` → source_refs without embeddings

### Шаг 4: Retrieval Service

```
tg_parser/services/retrieval_service.py
```

- `search(query, channel_id=None, limit=10)` → ranked ProcessedDocuments with scores
- `answer(question, channel_id=None)` → LLM-generated answer with sources

Flow:
1. Embed query → vector
2. pgvector similarity search → top-K source_refs
3. Load ProcessedDocuments by source_refs
4. (Optional) Load TopicCards for context enrichment
5. Build prompt with retrieved docs → LLM → answer

### Шаг 5: CLI + API

CLI:
```bash
tg-parser embed --channel <id>              # Embed all docs
tg-parser embed --channel <id> --force      # Re-embed all
tg-parser search --query "..." [--channel]  # Similarity search
tg-parser ask --question "..." [--channel]  # Q&A with RAG
```

API:
```
POST /api/v1/search    { "query": "...", "channel_id": "...", "limit": 10 }
POST /api/v1/ask       { "question": "...", "channel_id": "..." }
```

---

## Порядок реализации (рекомендуемый)

| # | Задача | Файлы | Строк (est.) | Зависимость |
|---|--------|-------|-------------|-------------|
| 1 | pgvector extension + DDL | `schemas/processing_storage.py`, `requirements.txt` | ~30 | — |
| 2 | `EmbeddingRepo` | `storage/sqlalchemy/embedding_repo.py`, `__init__.py` | ~120 | #1 |
| 3 | `embedding_repos()` CM | `services/db_context.py` | ~15 | #2 |
| 4 | Embedding Settings | `config/settings.py` | ~15 | — |
| 5 | `EmbeddingService` | `services/embedding_service.py` | ~150 | #2, #3, #4 |
| 6 | `RetrievalService` | `services/retrieval_service.py` | ~120 | #2, #5 |
| 7 | CLI commands | `cli/embed_cmd.py`, `cli/search_cmd.py`, `cli/app.py` | ~100 | #5, #6 |
| 8 | API endpoints | `api/routes/rag.py`, `api/main.py` | ~80 | #6 |
| 9 | Tests | `tests/test_embedding.py`, `tests/test_retrieval.py` | ~200 | #5, #6 |
| 10 | Scheduler integration | `background_scheduler.py` → embed task | ~20 | #5 |

**Общая оценка:** ~850 строк, 1-2 сессии.

---

## Технические решения (pre-approved)

### Embedding model

**text-embedding-3-small** (OpenAI):
- 1536 dimensions
- $0.02 / 1M tokens
- Достаточно для медицинского контента (labdiagnostica)
- Совместим с pgvector

### pgvector index

**IVFFlat** (не HNSW):
- Подходит для текущего масштаба (~1130 docs)
- Меньше памяти, быстрее build
- Когда > 10K docs → мигрировать на HNSW

### Chunking strategy

**Документ = 1 embedding:**
- ProcessedDocument уже содержит `text_clean` + `summary`
- Средний размер `text_clean` < 1000 tokens — укладывается в 8191 token limit
- Для MVP: embed `summary + text_clean[:500]` (наиболее информативная часть)
- Позже: chunk-level embeddings для длинных документов

### Shared vs separate engine

**Processing engine (shared):**
- Embedding таблица в той же PostgreSQL базе (`tg_parser` / `tg_parser_test`)
- Не нужен новый engine — меньше connections
- `embedding_repos()` создаёт session через `db.processing_storage_session()`

---

## Заметки из Code Review (Session 40)

### Что учесть при реализации:

1. **`db_context.py` init() safety:** При создании `embedding_repos()` CM — добавить `try/except` на `await db.init()` с `await db.close()` в except. Исправить и в существующих 5 CMs (minor fix).

2. **DI pattern:** RAG-сервис писать с DI сразу — `EmbeddingService(repo, llm_client)` вместо прямых импортов. Это рекомендация Session 38/40.

3. **Pool exhaustion:** Избегать nested CMs (как в `export_service`). `RetrievalService` должен получать repos через один CM.

4. **engine_factory Literal:** `create_engine_from_settings` ограничен `Literal["ingestion", "raw", "processing"]`. Для embedding — использовать `"processing"` (shared DB). Не менять Literal.

5. **Тесты:** Использовать паттерн из `test_storage_integration.py` — fixture с cleanup. Для embedding тестов — mock OpenAI embeddings API.

---

## Зависимости для установки

```
pgvector>=0.3.0
```

OpenAI SDK уже установлен (`openai` в requirements.txt). pgvector нужен для Python-side vector операций и для `register_vector` в SQLAlchemy.

### PostgreSQL extension

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Нужно установить pgvector extension в PostgreSQL:
```bash
# macOS Homebrew
brew install pgvector
```

---

## Критерии завершения сессии

- [ ] pgvector extension установлен и DDL создан
- [ ] `EmbeddingRepo` с `save`, `similarity_search`, `list_missing`
- [ ] `EmbeddingService` с `run_embedding`, `run_incremental_embedding`
- [ ] `RetrievalService` с `search` и `answer`
- [ ] CLI: `embed`, `search`, `ask`
- [ ] Тесты: ≥15 новых (unit + integration)
- [ ] Все существующие тесты проходят (517+)
- [ ] Документация обновлена в roadmap

---

**Подготовлено:** Session 40 (Code Review)  
**Следующий шаг:** Начать с #1 (pgvector + DDL) и #2 (EmbeddingRepo)
