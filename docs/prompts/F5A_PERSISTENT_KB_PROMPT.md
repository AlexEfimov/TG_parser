# F5-A: Persistent KB + Topic RAG — Placeholder

**Статус:** Placeholder (детальный план — в начале сессии реализации)  
**Prerequisites:** Wave 1.5, F8-A (Hardening)  
**Effort:** ~1.5–2 сессии

---

## Цель

Структурное улучшение RAG через topic-level embeddings, hybrid search, и дедупликацию — главная пользовательская фича для качества ответов.

## Scope

| Область | Что сделать |
|---------|-------------|
| **Topic embeddings** | Embeddings для topic cards (title + summary + tags), не только для processed documents |
| **Hybrid search** | Комбинация keyword (tsvector/FTS) + semantic (pgvector cosine) search |
| **Topic RAG** | При ответе на вопрос учитывать topic context (структурированные знания), а не только raw documents |
| **Deduplication** | Обнаружение дубликатов при ingestion (по content hash или embedding similarity) |
| **Search quality** | Relevance tuning: weights для keyword vs semantic, minimum threshold, re-ranking |

## Ключевые файлы (предварительно)

- `tg_parser/storage/sqlalchemy/embedding_repo.py` — embedding storage + similarity search
- `tg_parser/services/embedding_service.py` — embedding generation
- `tg_parser/services/retrieval_service.py` — search + answer
- `tg_parser/storage/ports.py` — repository interfaces
- `prompts/rag.yaml` — RAG prompt (после Wave 1.5 refactor)
- Alembic migrations — новые индексы (tsvector, topic embeddings)

## Что НЕ входит

- Knowledge Graph (F5-D)
- Evolving summaries (F5-C)
- Multi-source connectors (F3)

## Зависимости от предыдущих шагов

- **Wave 1.5:** RAG prompt refactored, topic context format established
- **F8-A:** Retry/circuit breaker для LLM embedding calls, DB pool stable under load
- Topic card schema уже содержит `summary`, `tags`, `scope_in/scope_out` — данные для embeddings готовы
