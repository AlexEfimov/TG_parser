# F5-A: Persistent KB + Topic RAG

**Статус:** Design зафиксирован, Session 1 prompt ожидается
**Prerequisites:** Wave 1.5 ✅, F8-A (Hardening) ✅
**Effort:** ~1.5–2 сессии, разбито на фазы

> **Детальный план:** [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md)

---

## Ключевые решения

Обсуждение зафиксировано в плане; краткая выжимка:

1. **Topic embeddings уже реализованы** (см. `run_topic_embedding` в `embedding_service.py`), хранятся в `document_embeddings` с `entry_type='topic'`. Реальный объём F5-A сводится к **hybrid search**, **tuning** и **deduplication**.
2. **Декомпозиция на фазы:**
   - **Фаза 1 — Hybrid Search** (tsvector FTS + RRF fusion + keyword/semantic режимы) — **Session 1**.
   - **Фаза 2 — Relevance tuning & Topic-weighted RAG** (квоты, `min_score`, структурированный prompt context) — Session 2.
   - **Фаза 3 — Deduplication** (SHA-256 content hash в ingestion) — Session 2/3.
3. **Мультиязычный FTS:** одна `search_vector tsvector GENERATED` колонка с конкатенацией per-language `to_tsvector` (`russian + english` на старте, расширяемо). `plainto_tsquery('simple', :q)` на стороне запроса.
4. **Fusion:** RRF (Reciprocal Rank Fusion) с `k=60`, Python-side merge; без env-опции на linear в Фазе 1.
5. **Deduplication:** content hash first, near-duplicate через embedding — отложено.

## Scope первой сессии (Фаза 1)

| Область | Что сделать |
|---|---|
| **Миграции** | `search_vector tsvector GENERATED` + GIN на `processed_documents` и `topic_cards` |
| **Repo** | `keyword_search()` на `EmbeddingRepo` (или отдельный `SearchRepo`); `min_score` в `similarity_search` |
| **Service** | `retrieval_service.search(mode="hybrid"\|"semantic"\|"keyword")`, default `hybrid`; чистая функция `_rrf_fuse` |
| **Settings** | `hybrid_enabled`, `hybrid_rrf_k`, `fts_languages` |
| **Tests** | Unit (RRF, mode switching) + integration (pg+pgvector фикстура, multilingual) + regression existing RAG-тестов |
| **Docs** | `USER_GUIDE.md`, `MCP_AGENT_GUIDE.md`, `ENV_VARIABLES_GUIDE.md` |

Полный список задач, acceptance criteria и рисков — в [плане](../plans/F5A_PERSISTENT_KB_PLAN.md).

## Что НЕ входит

- Re-ranking (cross-encoder / LLM-based) — отдельная инициатива после F5-A.
- Knowledge Graph (F5-D).
- Evolving summaries (F5-C).
- Multi-source connectors (F3).
- Deduplication и tuning — откладываются в Фазы 2–3.

## Следующий шаг

Написать детальный prompt на Session 1 — `F5A_PHASE1_HYBRID_SEARCH_PROMPT.md` (по образцу `F8A_HARDENING_PROMPT.md`), раскрывающий:
- пошаговые DDL-миграции (с подсказкой про table rewrite);
- точные сигнатуры методов repo/service;
- полный список unit- и integration-тестов;
- acceptance checklist.
