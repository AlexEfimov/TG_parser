# F5-A Phase 1: Hybrid Search — Стартовый промпт

**Версия проекта:** 4.4.0+ (post F8-A Hardening)
**Предыдущая сессия:** F8-A Hardening — все 5 фаз ✅ (коммит `8012021`)
**Зафиксированная последовательность:** Wave 1.5 ✅ → F8-A ✅ → **F5-A Phase 1** → F5-A Phase 2 → F5-A Phase 3

**Design-doc:** [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md) — полный контекст, обоснование решений, альтернативы.

---

## Цель сессии

Добавить **hybrid search** (keyword FTS + semantic pgvector) в retrieval pipeline. Дефолтный режим `search()` становится `"hybrid"` — объединение keyword и semantic результатов через **Reciprocal Rank Fusion (RRF)**. Мультиязычная конфигурация FTS (`russian + english`) в одной сгенерированной `search_vector` колонке — расширяется миграциями на новые языки.

F5-A Phase 2 (relevance tuning, topic-weighted RAG context) и Phase 3 (deduplication) — отдельные сессии. Re-ranking вне scope F5-A.

---

## Контекст: текущее состояние RAG

### Что уже есть

| Компонент | Где | Статус |
|---|---|---|
| Topic embeddings | `run_topic_embedding()` в `tg_parser/services/embedding_service.py` (253–337) | ✅ DONE |
| Semantic search | `SAmbeddingRepo.similarity_search()` (`embedding_repo.py:132`) — pgvector IVFFlat cosine, `SET ivfflat.probes = 20` при channel filter | ✅ DONE |
| Multi-tenant изоляция | `channel_ids TEXT[]` GIN (`20260416_add_embedding_channel_ids.py`) | ✅ DONE (F4) |
| Unified retry для embedding API | F8-A | ✅ DONE |
| Topic-aware RAG (базовый) | `retrieval_service.search(include_topics=True)` default, `_build_context` различает `[TOPIC]` и message | ✅ DONE |
| `threshold` parameter в `search()` | `retrieval_service.py:49`, прокидывается в `similarity_search` | ✅ DONE (не требует работы) |

### Что НЕ сделано (gaps для Phase 1)

| Gap | Проблема |
|---|---|
| **Нет keyword search** | `tsvector`/FTS отсутствует в `processed_documents` и `topic_cards`. По точным терминам и редким словам (имена, идентификаторы, URL) semantic search проигрывает BM25/FTS. |
| **Нет hybrid fusion** | `retrieval_service.search()` работает только через pgvector cosine. Нет объединения нескольких сигналов. |
| **Нет переключателя режима** | API нельзя вызвать в режиме "только keyword" для диагностики/A-B. |
| **Нет multilingual FTS дизайна** | Надо заложить архитектуру, чтобы добавление 3-го языка было миграцией, а не переписыванием query path. |

---

## План реализации (5 sub-фаз внутри одной сессии)

### Phase 1.1: FTS Migrations

**Файлы:**
- `migrations/versions/processing/<timestamp>_add_fts_to_processed_documents.py` (новый)
- `migrations/versions/processing/<timestamp>_add_fts_to_topic_cards.py` (новый)
- `tg_parser/storage/sqlalchemy/schemas/processing_storage.py` — обновить DDL и `_ensure_*_columns()`

**DDL для `processed_documents`:**
```sql
ALTER TABLE processed_documents
ADD COLUMN search_vector tsvector
GENERATED ALWAYS AS (
  setweight(to_tsvector('simple',  coalesce(summary, '')),    'A') ||
  setweight(to_tsvector('russian', coalesce(text_clean, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(text_clean, '')), 'B')
) STORED;

CREATE INDEX IF NOT EXISTS idx_pd_search_vector
  ON processed_documents USING GIN (search_vector);
```

**DDL для `topic_cards`:** аналогично, но источники — `title` (weight A), `summary` + `scope_in_json` (weight B). `scope_in_json` хранится как JSON-массив; в generated-выражении извлекаем через `jsonb_array_elements_text(scope_in_json::jsonb)` + `string_agg(..., ' ')` — либо проще через прямой `coalesce(scope_in_json, '')` (JSON-текст тоже токенизируется, хотя немного зашумлённо).

> **Рекомендация:** для `topic_cards` взять простой `coalesce(scope_in_json, '')` — это самый надёжный generated-выражение без доп. функций. Шум от скобок/кавычек JSON минимальный, `simple` config их отфильтрует как не-word-chars.

**Миграционная осторожность:**
- `ADD COLUMN ... GENERATED STORED` делает **table rewrite** → downtime пропорционально размеру таблицы.
- На small/medium инсталляциях (< 1M rows) приемлемо. На production-инсталляциях с > 1M rows — документируем в release notes; fallback через `pg_repack` или triggered update — вне scope Phase 1.
- `init_processing_storage_schema()` для fresh инсталляций включает колонку сразу (без ALTER).

**`_ensure_*_columns()` идемпотентность:**
- В `processing_storage.py` расширить `_ensure_embedding_columns()` паттерном добавления `search_vector` и GIN-индекса для `processed_documents` и `topic_cards` (по образцу существующего `_ensure_embedding_columns()` — проверка `information_schema.columns` перед ALTER).

### Phase 1.2: Repo layer — `keyword_search`

**Файл:** `tg_parser/storage/sqlalchemy/embedding_repo.py`

**Добавить метод на `SAmbeddingRepo`:**
```python
async def keyword_search(
    self,
    query: str,
    limit: int = 10,
    entry_types: list[str] | None = None,
    channel_ids: list[str] | None = None,
    min_rank: float = 0.0,
) -> list[SimilarityResult]:
    """FTS search по processed_documents и topic_cards, объединённый UNION ALL."""
```

**SQL (два SELECT в UNION ALL):**
```sql
WITH q AS (SELECT plainto_tsquery('simple', :query) AS tsq)
SELECT source_ref, ts_rank_cd(search_vector, q.tsq) AS score,
       'message' AS entry_type, NULL::text AS topic_id
FROM processed_documents, q
WHERE search_vector @@ q.tsq
  AND (:channel_ids IS NULL OR channel_id = ANY(CAST(:channel_ids AS text[])))
UNION ALL
SELECT id AS source_ref, ts_rank_cd(search_vector, q.tsq) AS score,
       'topic' AS entry_type, id AS topic_id
FROM topic_cards, q
WHERE search_vector @@ q.tsq
  -- topic_cards использует sources_json для tenancy; оставим фильтр простым:
  -- в Phase 1 фильтр по channel_ids для topic делается Python-side через topic_card_repo
ORDER BY score DESC
LIMIT :limit;
```

**Решения:**
- **`entry_types` фильтр** — применяется в Python после fetch (или добавить `WHERE entry_type IN (...)` через CTE). Python проще и тестируется без БД.
- **`min_rank` cutoff** — применяется в Python (`if score >= min_rank`).
- **Channel filter для `topic_cards`** — в Phase 1 упрощаем: фильтруем результаты через `topic_card_repo.list_by_channels` после fetch, как уже делается в `retrieval_service`. Оптимизация (channel_ids GIN на topic_cards) — в Phase 2/3.

**Добавить `keyword_search` в ABC:** `tg_parser/storage/ports.py` — класс `EmbeddingRepo` (строки ~815–870).

### Phase 1.3: Service layer — `mode` + RRF fusion

**Файл:** `tg_parser/services/retrieval_service.py`

**Расширить сигнатуру `search()` (строка 45):**
```python
async def search(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    threshold: float = 0.0,
    include_topics: bool = True,
    allowed_channel_ids: list[str] | None = None,
    mode: Literal["semantic", "keyword", "hybrid"] = "hybrid",  # NEW
    *,
    emb_repo: EmbeddingRepo | None = None,
    proc_repo: ProcessedDocumentRepo | None = None,
    topic_card_repo: TopicCardRepo | None = None,
) -> list[SearchResult]:
```

**Логика:**
```python
if mode == "semantic":
    sim = await emb_repo.similarity_search(query_vec, ...)
elif mode == "keyword":
    sim = await emb_repo.keyword_search(query, ...)
else:  # hybrid
    sem_task = emb_repo.similarity_search(query_vec, limit=limit * 2, ...)
    kw_task  = emb_repo.keyword_search(query, limit=limit * 2, ...)
    sem, kw = await asyncio.gather(sem_task, kw_task)
    sim = _rrf_fuse(sem, kw, k=settings.hybrid_rrf_k)[:limit]
```

**Chunk: `_rrf_fuse()` — pure function, new module `tg_parser/services/_ranking.py`:**
```python
def rrf_fuse(
    *lists: Sequence[SimilarityResult],
    k: int = 60,
) -> list[SimilarityResult]:
    """
    Reciprocal Rank Fusion. Возвращает объединённый список, отсортированный
    по RRF score по убыванию. Дубликаты по source_ref агрегируются.
    Score исходных результатов в финальном списке — RRF score (не original).
    """
```

**Особенности реализации:**
- Rank = 1-indexed позиция в исходном списке (уже отсортированном).
- Дубликаты: если один `source_ref` встречается в нескольких списках — суммируем `1/(k+rank)` по всем.
- Возвращаем `SimilarityResult` с заполненным `score=rrf_score`, сохраняем `entry_type` и `topic_id` из первого встреченного.
- Пустой список одного из источников — не крашит; fusion возвращает просто другой.

**Не трогаем:**
- `_build_context()` (строка ~167) — остаётся как есть; topic-weighted context — Phase 2.
- `answer()` (строка 198) — оборачивает `search()`, автоматически получит hybrid.
- Embedding client/flow — semantic path не меняется.

### Phase 1.4: Settings, factory, API wiring

**Файл:** `tg_parser/config/settings.py`

Добавить:
```python
# F5-A Phase 1: Hybrid Search
hybrid_enabled: bool = Field(default=True, description="Enable hybrid (keyword+semantic) retrieval; False → semantic only")
hybrid_rrf_k: int = Field(default=60, description="RRF constant; higher = less discrimination")
fts_languages: str = Field(default="russian,english", description="Informational: FTS languages baked into search_vector DDL")
```

**Wiring:**
- `retrieval_service.search()` — если `mode == "hybrid"` и `not settings.hybrid_enabled` → фолбэк на `"semantic"`.
- `retrieval_service.answer()` — ничего не меняем (пробрасывает `mode` в `search` через дефолт).

**API endpoints** (`tg_parser/api/routes/rag.py` или аналогичный):
- `POST /api/v1/search` — опциональный body field `mode` (default `"hybrid"`). Валидация через Pydantic Literal.
- `POST /api/v1/ask` — аналогично опциональный `mode`.
- **MCP tools** (`search_knowledge_base`, `ask_question`) — не добавляем параметр `mode` в Phase 1 (будет в Phase 2 вместе с topic-weighting UX). Дефолт `hybrid` применяется неявно.

**`.env.example`** — добавить новые переменные с комментариями.

### Phase 1.5: Tests + Docs

**Файл (новый тест-сьют):** `tests/test_f5a_hybrid_search.py`

Структура по аналогии с `tests/test_f8a_hardening.py`:

| Класс | Тестов | Покрытие |
|---|---|---|
| `TestRRFFusion` | ~10 | pure function: одинаковый doc в обоих списках получает суммарный ранг; пустой список одного источника; разные k; дубликаты агрегируются; стабильность сортировки; None/пустой вход; порядок `entry_type` и `topic_id` preserved |
| `TestSearchModeSwitch` | ~6 | `mode="semantic"` не вызывает `keyword_search`; `mode="keyword"` не вызывает `similarity_search`; `mode="hybrid"` вызывает оба в `asyncio.gather`; `hybrid_enabled=False` + `mode="hybrid"` → fallback на semantic; неверный mode → ValueError |
| `TestKeywordSearchRepo` (pg+pgvector) | ~6 | базовый FTS по `processed_documents` на фикстуре; FTS по `topic_cards`; UNION ALL возвращает оба типа; channel_id filter; `min_rank` cutoff; русский + английский запросы на смешанном корпусе |
| `TestHybridIntegration` (pg+pgvector) | ~4 | hybrid возвращает объединение без дубликатов; редкий термин (только в keyword) поднимается RRF; семантический запрос без точного совпадения — semantic доминирует; пустой корпус не ломает |
| `TestSettings` | ~3 | `hybrid_enabled`, `hybrid_rrf_k`, `fts_languages` читаются из env; дефолты корректны |
| `TestMigrationIdempotency` (pg) | ~2 | `_ensure_*_columns` повторный запуск не роняет; индекс существует после первого запуска |

**Маркер для тестов, требующих реальный PostgreSQL+pgvector:** использовать `pytest.mark.skipif(SKIP_PGVECTOR_TESTS, ...)` — существующая практика в `test_f4_embedding_channel_ids.py`.

**Regression — существующие тесты (должны проходить без изменений):**
- `tests/test_f5a_topic_rag.py`
- `tests/test_retrieval_llm_refactor.py`
- `tests/test_rag_routes.py`
- `tests/test_rag_prompt_config.py`
- `tests/test_f4_embedding_channel_ids.py`
- `tests/test_f4_vector_search_isolation.py`
- `tests/test_embedding.py`

Если тесту требуется mock `emb_repo` с методом `keyword_search` — добавить заглушку `AsyncMock(return_value=[])` в setUp.

**Документация:**
- `docs/USER_GUIDE.md` — новая секция "Hybrid Search" с описанием режимов, env vars, multilingual support, мигaционное предупреждение про table rewrite.
- `docs/MCP_AGENT_GUIDE.md` — короткая заметка: `search_knowledge_base` теперь по умолчанию hybrid; поведение отличается от pure semantic.
- `ENV_VARIABLES_GUIDE.md` — `HYBRID_ENABLED`, `HYBRID_RRF_K`, `FTS_LANGUAGES`.
- `docs/plans/F5A_PERSISTENT_KB_PLAN.md` — в конце пометить "Phase 1: DONE" с ссылкой на коммит.

---

## Ключевые файлы для изучения

| Файл | Назначение |
|---|---|
| `tg_parser/storage/sqlalchemy/embedding_repo.py` | `SAmbeddingRepo` — **target Phase 1.2** (добавить `keyword_search`) |
| `tg_parser/storage/ports.py` | `EmbeddingRepo` ABC (~строки 815–870) — добавить abstract `keyword_search` |
| `tg_parser/storage/sqlalchemy/schemas/processing_storage.py` | DDL + `_ensure_*_columns()` — **target Phase 1.1** |
| `tg_parser/services/retrieval_service.py` | `search()` (строка 45) — **target Phase 1.3** (параметр `mode`, wiring RRF) |
| `tg_parser/services/_ranking.py` | **новый модуль** — pure function `rrf_fuse()` |
| `tg_parser/config/settings.py` | — **target Phase 1.4** (новые settings) |
| `migrations/versions/processing/20260416_add_embedding_channel_ids.py` | Эталон миграции processing БД (идемпотентность, backfill паттерн) |
| `migrations/versions/processing/20260415_add_entry_type_to_embeddings.py` | Ещё один эталон миграции (ALTER + index) |
| `tests/test_f8a_hardening.py` | Эталон структуры test file (классы по фазам, markers, fixtures) |
| `tests/test_f4_embedding_channel_ids.py` | Эталон pg+pgvector integration тестов (skip marker, session-level fixture) |
| `docs/plans/F5A_PERSISTENT_KB_PLAN.md` | **Полный дизайн-док** с обоснованиями |

---

## Что НЕ входит в scope Phase 1

- **Relevance tuning** (topic quotas, min_score cutoff в hybrid) — Phase 2.
- **Topic-weighted RAG context** (structured sections в `_build_context`) — Phase 2.
- **Deduplication** (content hash, near-duplicate) — Phase 3.
- **Re-ranking** (cross-encoder, LLM-based) — вне F5-A.
- **Linear fusion (alpha-weighted)** как альтернатива RRF — не добавляем ручку, если понадобится — отдельная итерация после Phase 2.
- **GIN по `topic_cards.channel_ids`** для SQL-level tenancy фильтра — Phase 2/3.
- **Автоматическая детекция языка запроса** — используем `plainto_tsquery('simple', ...)` универсально.
- **Изменение MCP tool signature** (добавление `mode` параметра) — Phase 2.
- **Rename** `SAmbeddingRepo` → `SASearchRepo` или вынос в отдельный класс — не делаем, оставляем метод в existing repo.

---

## Критерии завершённости

1. Миграции для `processed_documents.search_vector` и `topic_cards.search_vector` применяются на fresh БД и на существующей (идемпотентно через `_ensure_*_columns()`).
2. GIN-индексы `idx_pd_search_vector` и `idx_tc_search_vector` созданы.
3. `SAmbeddingRepo.keyword_search()` реализован и возвращает `list[SimilarityResult]` с корректным score (`ts_rank_cd`) и `entry_type`.
4. `EmbeddingRepo` ABC содержит abstract `keyword_search`.
5. `retrieval_service.search(mode="hybrid")` — дефолт; режимы `"semantic"`, `"keyword"` работают и тестированы.
6. `tg_parser/services/_ranking.py` содержит pure function `rrf_fuse()` с unit-тестами (≥10 кейсов).
7. Settings: `hybrid_enabled`, `hybrid_rrf_k`, `fts_languages` читаются из env с дефолтами; `hybrid_enabled=False` корректно отключает keyword path.
8. `POST /api/v1/search` и `/ask` принимают опциональный `mode` в body; Pydantic валидация через Literal.
9. Новый тест-файл `tests/test_f5a_hybrid_search.py` содержит ~31 тестов (см. таблицу Phase 1.5); все проходят.
10. Существующие тесты (1331+) проходят без изменений логики. Допускается минимальное обновление моков (`AsyncMock` для `keyword_search`).
11. `docs/USER_GUIDE.md`, `docs/MCP_AGENT_GUIDE.md`, `ENV_VARIABLES_GUIDE.md`, `docs/plans/F5A_PERSISTENT_KB_PLAN.md` обновлены.
12. Коммит (или несколько) на отдельной ветке с ясным message `feat(f5a-phase1): hybrid search with FTS + RRF fusion`.

---

## Тесты

Запуск тестов:
```bash
# Unit + mocks only:
.venv/bin/pytest tests/test_f5a_hybrid_search.py -x -q

# С PostgreSQL integration (требует запущенный pg с pgvector):
TEST_POSTGRES=1 .venv/bin/pytest tests/test_f5a_hybrid_search.py -x -q

# Полный regression:
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

Текущее состояние: **1331 тестов** (post F8-A, коммит `8012021`).
Ожидаемое после Phase 1: **~1362 тестов** (+31 в новом файле).

---

## Замечания по выполнению

1. **Начать с Plan mode** — сверить сигнатуры `similarity_search`, текущие использования `search()` в кодовой базе (API routes, MCP tools, CLI), найти все места где нужен `mode`-прокидывание или mock-адаптация.
2. **Миграции первыми** — без колонки `search_vector` тесты не пройдут даже для pure-Python RRF (интеграционные).
3. **`rrf_fuse` — pure function** — можно писать и тестировать первым, до всего остального. Легко TDD.
4. **Интеграционные тесты** — запускать только если `TEST_POSTGRES=1`. Без pgvector можно сломать CI; убедиться, что skip работает корректно.
5. **Идемпотентность `_ensure_*_columns()`** — протестировать явно (вызов дважды не должен падать).
6. **Downtime миграции** — если в README видно, что prod уже имеет сотни тысяч processed_documents, упомянуть в release notes про table rewrite и рекомендацию применить в maintenance window.
7. **Коммит-стратегия** — 1 big commit приемлем; альтернатива — 2 коммита: `feat(f5a-phase1): add FTS migrations and keyword_search repo` + `feat(f5a-phase1): wire hybrid mode with RRF fusion`.
