# F5-A Phase 1 Implementation — Стартовый промпт

**Версия проекта:** 4.4.0+ (post F8-A Hardening, коммит `8012021`)
**Ветка:** `feat/f5a-phase1-hybrid-search` (создать от `main`)
**План реализации:** [`docs/plans/F5A_PHASE1_IMPLEMENTATION_PLAN.md`](../plans/F5A_PHASE1_IMPLEMENTATION_PLAN.md) — **читать первым**
**Design-doc:** [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md)
**Исходный промпт:** [`F5A_PHASE1_HYBRID_SEARCH_PROMPT.md`](F5A_PHASE1_HYBRID_SEARCH_PROMPT.md)

---

## Цель

Добавить hybrid search (keyword FTS + semantic pgvector) в retrieval pipeline. Дефолтный режим `retrieval_service.search()` становится `"hybrid"` — объединение через Reciprocal Rank Fusion (RRF). Мультиязычная FTS (`russian + english`) через generated `tsvector` колонку.

---

## Коротко об архитектуре

```
query → retrieval_service.search(mode)
         ├── semantic → emb_repo.similarity_search (pgvector cosine)
         ├── keyword  → emb_repo.keyword_search (FTS, ts_rank_cd)
         └── hybrid   → asyncio.gather(both) → _ranking.rrf_fuse → top-N
```

Новая pure-function `rrf_fuse(*lists, k=60)` в `tg_parser/services/_ranking.py`: 1-indexed rank, дубликаты по `source_ref` агрегируются.

---

## Ключевые уточнения (после разведки)

- Класс repo — **`SAEmbeddingRepo`** (не `SAmbeddingRepo` как в оригинальном промпте).
- `EmbeddingRepo` ABC в [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) строки 815–870.
- Текущая `search()` — [`tg_parser/services/retrieval_service.py`](../../tg_parser/services/retrieval_service.py) строка 45.
- Alembic head: `c3d4e5f6a7b8` → новые ревизии `d4e5f6a7b8c9` (processed_documents) → `e5f6a7b8c9d0` (topic_cards).
- Существующие тесты используют `AsyncMock()` без spec → нужно добавить `mock_emb_repo.keyword_search = AsyncMock(return_value=[])` в:
  - [`tests/test_f4_scoped_access.py`](../../tests/test_f4_scoped_access.py)
  - [`tests/test_f4_coverage_supplement.py`](../../tests/test_f4_coverage_supplement.py)
  - [`tests/test_f5a_topic_rag.py`](../../tests/test_f5a_topic_rag.py)
  - [`tests/test_f4_vector_search_isolation.py`](../../tests/test_f4_vector_search_isolation.py) (если применимо)

---

## Структура работы (2 коммита)

### Коммит 1 — FTS слой

**Файлы:**
- `migrations/versions/processing/20260417_add_fts_to_processed_documents.py` (new)
- `migrations/versions/processing/20260417_add_fts_to_topic_cards.py` (new)
- [`tg_parser/storage/sqlalchemy/schemas/processing_storage.py`](../../tg_parser/storage/sqlalchemy/schemas/processing_storage.py) — DDL + новая `_ensure_fts_columns()`
- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) — abstract `keyword_search`
- [`tg_parser/storage/sqlalchemy/embedding_repo.py`](../../tg_parser/storage/sqlalchemy/embedding_repo.py) — реализация `keyword_search`
- `tg_parser/services/_ranking.py` (new) — pure `rrf_fuse`
- `tests/test_f5a_hybrid_search.py` (new) — классы `TestRRFFusion`, `TestKeywordSearchRepo`, `TestMigrationIdempotency`

**Commit message:**
```
feat(f5a-phase1): add FTS migrations, keyword_search repo, and rrf_fuse module
```

### Коммит 2 — Service + API + wiring

**Файлы:**
- [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) — `hybrid_enabled`, `hybrid_rrf_k`, `fts_languages`.
- `.env.example` — новые переменные.
- [`tg_parser/services/retrieval_service.py`](../../tg_parser/services/retrieval_service.py) — параметр `mode: Literal[...]` в `search()` и `answer()`, RRF wiring.
- [`tg_parser/api/routes/rag.py`](../../tg_parser/api/routes/rag.py) — `mode` в `SearchRequest`/`AskRequest`.
- Патч моков в существующих тестах (см. выше).
- `tests/test_f5a_hybrid_search.py` — классы `TestSearchModeSwitch`, `TestHybridIntegration`, `TestSettings`.
- Doc updates: [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md), [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md), [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md), [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md) (Phase 1: DONE).

**Commit message:**
```
feat(f5a-phase1): wire hybrid mode with RRF fusion in retrieval_service and API
```

---

## DDL шпаргалка

**`processed_documents.search_vector`:**
```sql
tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('simple',  coalesce(summary, '')),    'A') ||
  setweight(to_tsvector('russian', coalesce(text_clean, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(text_clean, '')), 'B')
) STORED
```

**`topic_cards.search_vector`:**
```sql
tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('simple',  coalesce(title, '')), 'A') ||
  setweight(to_tsvector('russian', coalesce(summary, '') || ' ' || coalesce(scope_in_json, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(scope_in_json, '')), 'B')
) STORED
```

**Индексы:** `idx_pd_search_vector`, `idx_tc_search_vector` (GIN).

> Table rewrite на ALTER! Для prod > 1M строк — применять в maintenance window. Упомянуть в USER_GUIDE.

---

## SQL для `keyword_search`

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
ORDER BY score DESC
LIMIT :limit
```

- `entry_types` фильтр и `min_rank` cutoff — Python-side.
- Channel filter для `topic_cards` — не в этом запросе; downstream в `retrieval_service` через `card.sources`.

---

## Service: сигнатура `search()`

```python
from typing import Literal

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
    ...
```

Логика ветвления:
```python
effective_mode = mode
if effective_mode == "hybrid" and not settings.hybrid_enabled:
    effective_mode = "semantic"

if effective_mode == "semantic":
    similar = await emb_repo.similarity_search(query_vec, ...)
elif effective_mode == "keyword":
    similar = await emb_repo.keyword_search(query, ...)
else:  # hybrid
    sem, kw = await asyncio.gather(
        emb_repo.similarity_search(query_vec, limit=limit * 2, ...),
        emb_repo.keyword_search(query, limit=limit * 2, ...),
    )
    similar = rrf_fuse(sem, kw, k=settings.hybrid_rrf_k)[:limit]
```

`answer()` принимает `mode` и пробрасывает в `search`.

---

## Settings

```python
hybrid_enabled: bool = Field(default=True, description="Enable hybrid (keyword+semantic) retrieval")
hybrid_rrf_k: int = Field(default=60, description="RRF constant; higher = less discrimination", ge=1)
fts_languages: str = Field(default="russian,english", description="Informational: FTS languages baked into search_vector DDL")
```

---

## Тесты

Новый файл `tests/test_f5a_hybrid_search.py` по образцу [`tests/test_f8a_hardening.py`](../../tests/test_f8a_hardening.py):

| Класс | Кейсов | Requires pg? |
|---|---|---|
| `TestRRFFusion` | ~10 | no |
| `TestKeywordSearchRepo` | ~6 | yes (`SKIP_PGVECTOR_TESTS`) |
| `TestMigrationIdempotency` | ~2 | yes |
| `TestSearchModeSwitch` | ~6 | no |
| `TestHybridIntegration` | ~4 | yes |
| `TestSettings` | ~3 | no |

**Запуск:**
```bash
# Unit only
.venv/bin/pytest tests/test_f5a_hybrid_search.py -x -q

# С Postgres + pgvector
TEST_POSTGRES=1 .venv/bin/pytest tests/test_f5a_hybrid_search.py -x -q

# Полный regression
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

**Ожидаемо:** 1331 → ~1362 тестов.

---

## Критерии готовности

1. Обе FTS-миграции применяются идемпотентно (fresh + existing БД).
2. GIN-индексы `idx_pd_search_vector`, `idx_tc_search_vector` созданы.
3. `SAEmbeddingRepo.keyword_search()` работает, возвращает `list[SimilarityResult]` с `ts_rank_cd`.
4. `EmbeddingRepo` ABC содержит abstract `keyword_search`.
5. `search(mode=...)` и `answer(mode=...)` поддерживают 3 режима; дефолт `hybrid`.
6. `tg_parser/services/_ranking.py` содержит `rrf_fuse` + ≥10 unit-тестов.
7. Settings читаются из env; `hybrid_enabled=False` отключает keyword path в hybrid.
8. `POST /api/v1/search` и `/ask` принимают опциональный `mode` (Pydantic Literal validation).
9. ~31 новый тест; все проходят.
10. Существующие тесты проходят с минимальным добавлением `keyword_search` stub.
11. Документация обновлена (USER_GUIDE, MCP_AGENT_GUIDE, ENV_VARIABLES_GUIDE, F5A_PERSISTENT_KB_PLAN).
12. Два коммита с указанными messages.

---

## Что НЕ входит в scope

- Relevance tuning, topic quotas, topic-weighted context — Phase 2.
- Dedup — Phase 3.
- Re-ranking (cross-encoder / LLM) — вне F5-A.
- `mode` в MCP tools / bot tools / CLI — Phase 2.
- Linear fusion как альтернатива RRF.
- GIN по `topic_cards.channel_ids` — Phase 2/3.

---

## Рекомендации исполнения

1. **Начать с Plan mode** → сверка плана с актуальным `main`, не появилось ли расхождений.
2. **TDD для `rrf_fuse`** — pure function, 10+ кейсов, пишутся и гоняются без БД.
3. **Миграции вторыми** — без `search_vector` integration-тесты keyword_search не пройдут.
4. **Skip-marker для pg-тестов** — использовать `SKIP_PGVECTOR_TESTS` по паттерну `tests/test_f4_embedding_channel_ids.py`.
5. **Идемпотентность `_ensure_fts_columns`** протестировать явно (двойной вызов не падает).
6. **Release notes** — про table-rewrite при ALTER GENERATED STORED на больших таблицах.
