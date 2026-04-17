# F5-A: Persistent KB + Topic RAG — План реализации

> **Статус:** Design-doc (Session 1 ожидается)
> **Prerequisites:** Wave 1.5 ✅, F8-A (Hardening) ✅
> **Effort:** ~1.5–2 сессии (разбито на фазы)

---

## 1. Аудит текущего состояния

Исследование кодовой базы (на момент F8-A, коммит `8012021`) показало, что часть заявленного в исходном placeholder-скоупа уже реализована в предыдущих волнах.

### 1.1 Что уже есть

| Компонент | Где | Статус |
|---|---|---|
| Topic embeddings | `run_topic_embedding()` в `tg_parser/services/embedding_service.py` (строки 253–337). Хранение в `document_embeddings` с `entry_type='topic'`, `topic_id`, `channel_ids`. | ✅ Работает |
| Semantic search | `SAmbeddingRepo.similarity_search()` — pgvector IVFFlat + cosine + GIN по `channel_ids`. | ✅ Работает |
| Multi-tenant изоляция | `channel_ids TEXT[]` GIN-индекс (`20260416_add_embedding_channel_ids.py`). | ✅ F4 завершён |
| Topic-aware RAG (базовый) | `retrieval_service.search(include_topics=True)` (дефолт), `_build_context` различает `[TOPIC]` и message-блоки. | ✅ Базово работает |
| Retry для embedding API | Унифицированный 429/5xx retry в LLM-клиентах (F8-A). | ✅ F8-A |

### 1.2 Что реально надо сделать в F5-A

| Пробел | Приоритет |
|---|---|
| **Hybrid search (keyword + semantic)** — нет `tsvector`, нет FTS-индексов, нет fusion-алгоритма | **P0** (ядро F5-A) |
| **Relevance tuning** — нет `min_score` cutoff; topic и message смешаны в одном pool без квот | **P1** |
| **Topic-weighted RAG context** — в `_build_context` topic-блоки идут вперемешку с message-блоками, а не как отдельный структурный раздел | **P1** |
| **Deduplication** — только идемпотентность по `source_ref` в `raw_message_repo`, контент-хэша нет | **P2** (откладываем) |
| **Re-ranking** (cross-encoder / LLM-based) | **P3** (не входит в F5-A) |

---

## 2. Декомпозиция на фазы

| Фаза | Объём | Эффорт | Session |
|---|---|---|---|
| **1. Hybrid Search** | FTS миграции + hybrid repo/service + RRF + тесты + docs | ~1 сессия | **Session 1** |
| **2. Relevance tuning & Topic-weighted RAG** | `min_score` cutoff, topic/message квоты, структурированный prompt-context, обновление `rag.yaml` | ~0.3–0.5 сессии | Session 2 (или хвост 1) |
| **3. Deduplication** | SHA-256 content hash + колонка + миграция + backfill + блок в ingestion | ~0.3–0.5 сессии | Session 2 |
| **4. Docs & E2E tests** | USER_GUIDE, MCP_AGENT_GUIDE, интеграционные тесты качества поиска | по 0.1–0.2 на фазу | Вместе с фазами |

**Решение:** идём последовательно от P0 к P2. **Session 1 = только Фаза 1.** Фазы 2–3 — отдельные сессии после оценки результатов Фазы 1 на реальных данных.

---

## 3. Фаза 1 — Hybrid Search (детальный дизайн)

### 3.1 Архитектурное решение: мультиязычный FTS

**Решение:** одна сгенерированная колонка `search_vector tsvector` на каждой FTS-таблице, в которой конкатенируются `to_tsvector`-ы для каждого поддерживаемого языка.

```sql
ALTER TABLE processed_documents
ADD COLUMN search_vector tsvector
GENERATED ALWAYS AS (
  setweight(to_tsvector('simple',  coalesce(summary, '')),     'A') ||
  setweight(to_tsvector('russian', coalesce(text_clean, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(text_clean, '')), 'B')
) STORED;

CREATE INDEX idx_pd_search_vector ON processed_documents USING GIN (search_vector);
```

Аналогично для `topic_cards` — конкатенация `title`, `summary`, `scope_in`.

**Почему один vector, а не колонка-на-язык:**
- Один GIN-индекс вместо N → меньше write amplification при INSERT/UPDATE.
- Query path не растёт с числом языков: `WHERE search_vector @@ plainto_tsquery('simple', :q)`.
- `setweight` даёт больший ранг заголовку/summary.
- Добавление нового языка = одна миграция `ALTER COLUMN ... SET GENERATED`.

**Trade-off:** стеммеры разных языков иногда дают false positives на омографах (напр., `pro` — стоп-слово в русском, термин в английском). На реальных корпусах шум минимальный.

**FTS query config:** `plainto_tsquery('simple', :q)` — `simple` принимает любой текст без стемминга. Это снижает recall на ~5–10%, но зато запрос работает одинаково для всех языков и не требует авто-детекции языка запроса.

**Env-переменная:** `FTS_LANGUAGES` (default `"russian,english"`) — **информационная** (readme/logs), жёстко зашивается в миграцию; при смене требуется новая миграция.

### 3.2 Алгоритм объединения: RRF (Reciprocal Rank Fusion)

**Решение:** RRF с константой `k=60` (стандарт Cormack et al., 2009). Без env-опции на линейную комбинацию в Фазе 1 — добавим, если практика покажет необходимость.

Формула:
```
score_rrf(d) = Σ_i  1 / (k + rank_i(d))
```

где `i` — источник (keyword, semantic), `rank_i(d)` — 1-индексированная позиция документа в соответствующем списке.

**Почему RRF, не linear:**

| Критерий | RRF | Linear (`α·kw + (1-α)·sem`) |
|---|---|---|
| Нормализация скоров | Не нужна (работает на рангах) | Нужна (min-max / z-score) |
| Тюнинг | Нет параметров (кроме `k`, дефолт работает) | `α` надо калибровать на размеченном корпусе |
| Устойчивость | Один источник ≠ доминирует | Выбросы в score искажают результат |
| Стабильность от запроса к запросу | Да | Зависит от распределения скоров |
| Управляемость | Меньше | Есть ручка `keyword_weight` |

На практике промышленные системы (Elastic, Vespa, OpenSearch, Milvus) используют RRF как дефолт. Для нашего MVP это правильный выбор.

**Реализация:** делаем **Python-side fusion** (два независимых `SELECT ... LIMIT N` в repo, объединение в сервисе). Это проще в тестах, легче отлаживать и не требует сложного CTE-SQL.

### 3.3 Изменения по слоям

#### Storage layer

**Миграции** (`migrations/versions/processing/`):
- `<timestamp>_add_fts_to_processed_documents.py` — `search_vector` + GIN
- `<timestamp>_add_fts_to_topic_cards.py` — `search_vector` + GIN

**DDL** (`processing_storage.py`): добавить generated-колонки и индексы в `PROCESSING_STORAGE_DDL` / `_ensure_*_columns()` для свежих инсталляций.

**Repo** (`embedding_repo.py` или новый `search_repo.py`):
```python
async def keyword_search(
    query: str,
    *,
    channel_ids: list[str] | None,
    entry_types: list[str],   # ["message", "topic"]
    limit: int,
) -> list[SimilarityResult]:
    """FTS по processed_documents и topic_cards, объединённый UNION ALL."""
```

Возвращает `SimilarityResult(source_ref, score=ts_rank_cd, entry_type, ...)`.

**`similarity_search`**: добавить параметр `min_score: float | None` для отсечения мусорных попаданий (в Фазе 2 задействуется активнее, но вводим ручку сейчас).

#### Service layer (`retrieval_service.py`)

```python
async def search(
    query: str,
    *,
    mode: Literal["semantic", "keyword", "hybrid"] = "hybrid",
    channel_ids: list[str] | None = None,
    include_topics: bool = True,
    limit: int = 10,
    ...
) -> list[SearchResult]:
    if mode == "semantic":
        return await self._semantic_search(...)
    if mode == "keyword":
        return await self._keyword_search(...)
    # hybrid:
    kw = await self._keyword_search(..., limit=limit * 2)
    sem = await self._semantic_search(..., limit=limit * 2)
    fused = _rrf_fuse(kw, sem, k=settings.hybrid_rrf_k)
    return fused[:limit]
```

**`_rrf_fuse`** — pure-function, unit-тестируется отдельно.

#### Settings (`config/settings.py`)

```python
hybrid_enabled: bool = True
hybrid_rrf_k: int = 60
fts_min_rank: float = 0.0         # на будущее, пока не фильтруем
fts_languages: str = "russian,english"  # информационная
```

#### API / MCP

- Сигнатуры `POST /api/v1/search`, `POST /api/v1/ask`, MCP `search_knowledge_base`, `ask_question` — **не меняем**. Hybrid включён по умолчанию.
- Опционально добавляем query-param `?mode=semantic|keyword|hybrid` для A/B-тестирования на уровне HTTP (не обязателен для Session 1).

### 3.4 Тесты

**Unit:**
- `_rrf_fuse`: одинаковые документы в обоих списках получают высший ранг; пустой keyword или semantic не ломает; порядок внутри ранга стабилен.
- `mode` switching: `"semantic"` не вызывает keyword_search, и наоборот.
- Settings: `hybrid_rrf_k` пробрасывается корректно.

**Integration (требует pg + pgvector, маркируем `SKIP_PGVECTOR_TESTS`):**
- Фикстура: 5 сообщений + 2 темы, известный ground truth.
- Запрос с редким термином (только в одном документе) → keyword доминирует.
- Запрос семантический ("что такое X") → semantic доминирует.
- Hybrid возвращает union без дубликатов.
- Многоязычность: документ на русском + запрос на русском; на английском + запрос на английском.

**Regression:**
- `test_f5a_topic_rag.py`, `test_rag_routes.py`, `test_retrieval_llm_refactor.py` — проверить, что hybrid=default не ломает существующие сценарии.

### 3.5 Документация

- **`docs/USER_GUIDE.md`** — новый раздел "Hybrid Search" с описанием: что это, какие env vars, как отключить (`HYBRID_ENABLED=false`), multilingual behavior.
- **`docs/MCP_AGENT_GUIDE.md`** — пометка, что `search_knowledge_base` теперь по умолчанию использует hybrid; результаты могут включать документы, которых не было при чистом semantic (и наоборот).
- **`ENV_VARIABLES_GUIDE.md`** — новые переменные.

### 3.6 Acceptance criteria (Session 1)

- [ ] Миграции применяются без downtime (generated columns — онлайновые при STORED, но требуют REWRITE; на больших таблицах нужен план; документируем в release notes).
- [ ] GIN индексы созданы на обеих таблицах.
- [ ] `retrieval_service.search(mode="hybrid")` — дефолт; старые сигнатуры сохранены.
- [ ] RRF unit-тесты проходят (≥ 10 кейсов).
- [ ] Integration-тесты с pg+pgvector проходят в CI и локально.
- [ ] Все существующие тесты (`test_f5a_topic_rag.py`, `test_retrieval_llm_refactor.py`, `test_rag_routes.py`, `test_rag_prompt_config.py`) проходят без модификаций логики.
- [ ] Документация обновлена.
- [ ] Коммит(ы) в отдельной ветке/PR для review перед merge в `main`.

---

## 4. Фаза 2 — Relevance tuning & Topic-weighted RAG (набросок)

> Детализация — в отдельном prompt перед Session 2.

- **`min_score` cutoff** в `similarity_search` и в hybrid fusion (пороги — в settings).
- **Квоты по типам**: `topic_quota=2`, `message_quota=N-2` вместо общего pool — в `retrieval_service.answer()`.
- **Структурированный RAG context**: `_build_context` выдаёт два раздела — `## Related Topics` (сжатые topic cards) и `## Source Messages` (chunks). Обновляем `prompts/rag.yaml`.
- **A/B-проверка**: опционально пробрасываем `include_topic_cards` как параметр MCP-tool для сравнения.

---

## 5. Фаза 3 — Deduplication (набросок)

> Детализация — в отдельном prompt перед Session 2/3.

- **Content hash** (SHA-256 на нормализованный `text_clean`): новая колонка `processed_documents.content_hash CHAR(64)` + B-tree индекс.
- **Нормализация для хэша**: lowercase + collapse whitespace + strip URL query params (вопрос tune-ится в дизайне).
- **Блок в processing pipeline**: при обнаружении существующего hash в том же `channel_id` → skip + log + пометка `metadata.duplicate_of=<source_ref>`.
- **Backfill миграция**: для существующих данных (batched).
- **Near-duplicate через embedding cosine ≥ 0.97** — **отложено** (дорогая операция, тюнинг порога на реальных данных).

**Почему content hash как MVP, не near-dup:**

| | Content hash | Near-duplicate (embedding) |
|---|---|---|
| Сложность | O(1) lookup по индексу | O(log N) similarity search |
| Цена | Одна колонка + индекс | Зависит от IVFFlat probes, дороже на больших корпусах |
| Ловит | Точные пересылки, репосты | + семантические перефразировки |
| Ложные срабатывания | Нулевые | Зависят от порога 0.97, без разметки — игра вслепую |
| Откатываемость | Тривиально (drop column) | Тяжелее |

Content hash покрывает ~80% кейсов в Telegram (пересылки, repost, одинаковые объявления), решения о near-dup принимаем после мониторинга.

---

## 6. Риски и открытые вопросы

| Риск | Митигация |
|---|---|
| `ALTER TABLE ... ADD COLUMN ... GENERATED STORED` делает table rewrite → downtime на больших БД | Документируем в release notes; в проде сначала применяем на тестовом дампе; рассматриваем `pg_repack` или batch backfill через триггеры как fallback |
| Стеммеры ru + en дают конфликты на омографах | Мониторим `ts_rank` на production queries; при проблемах — откат на `simple` только |
| RRF=60 даёт плохой ранкинг на нашем корпусе | Добавим linear fusion как fallback в Фазе 2, если метрики не сойдутся |
| FTS на smaller Postgres-инсталляциях (SQLite в dev) не работает | Проверить fallback / skip fixture на SQLite; hybrid требует pg |
| Увеличение размера `processed_documents` из-за `search_vector STORED` | Оценить: tsvector обычно ~10–30% от text_clean; на 1M документов ~десятки гигабайт — терпимо |

---

## 7. Зафиксированные решения (итоговая сводка)

1. **Session 1 объём = только Фаза 1 (Hybrid Search)**. Фазы 2–3 — отдельные сессии.
2. **FTS стратегия:** одна `search_vector` generated column с конкатенацией per-language `to_tsvector` (default: `russian + english`); расширяемо миграцией.
3. **FTS query:** `plainto_tsquery('simple', ...)` — language-agnostic.
4. **Fusion algorithm:** RRF с `k=60`, без env-переключателя на linear в Фазе 1.
5. **Fusion execution:** Python-side (два SELECT + merge в сервисе), не SQL CTE.
6. **Deduplication:** откладываем на Фазу 3; при реализации — content hash first, near-duplicate позже (если потребуется).
7. **Re-ranking:** вне скоупа F5-A.
8. **API contracts:** не ломаем; hybrid = дефолт; `mode=semantic|keyword|hybrid` — опциональный параметр.
9. **Placeholder-промпт** `docs/prompts/F5A_PERSISTENT_KB_PROMPT.md` обновляется, полный Session 1 prompt пишется отдельно как `F5A_PHASE1_HYBRID_SEARCH_PROMPT.md` (по образцу `F8A_HARDENING_PROMPT.md`).

---

## 8. Связанные документы

- `docs/prompts/F5A_PERSISTENT_KB_PROMPT.md` — исходный placeholder (обновлён).
- `docs/prompts/F8A_HARDENING_PROMPT.md` — образец детального Session-prompt.
- `docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md` — завершённый F4 (multi-tenancy), см. раздел "F5-A уже реализован" про topic embeddings.
- `docs/USER_GUIDE.md` — будет обновлён в Session 1.
