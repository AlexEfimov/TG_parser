# ADR 0003 – Хранилище и индексация для базы знаний

## Статус
Accepted

## Контекст

TG_parser формирует `KnowledgeBaseEntry` на основе сообщений Telegram (в MVP — на этапе CLI‑экспорта, TR‑55..TR‑65).  
Нужно выбрать подход к хранению и индексации, который:
- поддерживает поиск по тексту и метаданным;
- масштабируется по объёму данных;
- допускает использование векторного поиска в будущем.

> **Implementation status (2026-05-14, HEAD `47e1c72`).**
>
> **MVP SQLite → production PostgreSQL.** ADR описывает MVP на трёх SQLite
> файлах (`ingestion_state.sqlite`, `raw_storage.sqlite`,
> `processing_storage.sqlite`). Текущая реальность — **PostgreSQL-only**:
> - `tg_parser/storage/engine_factory.py` — комментарий «PostgreSQL only»;
> - `tg_parser/config/settings.py` — поля `db_*` (PostgreSQL connection params);
> - `migrations/env.py` — комментарий «PostgreSQL-only (SQLite support removed)».
>
> Логическое разделение на 3 области (ingestion / raw / processing)
> сохранено — теперь это **3 ветки Alembic** (`migrations/versions/ingestion/`,
> `migrations/versions/raw/`, `migrations/versions/processing/`) + 3 engine
> в `tg_parser/storage/sqlalchemy/database.py`.
>
> Indexing — гибридный поиск через **FTS** (миграции `*add_fts_*.py` в
> `processing/`) + **pgvector** (`*add_entry_type_to_embeddings.py`).
> Дополнительные таблицы за пределами MVP-scope: `users`, `user_auth`
> (F4 multi-tenancy), `workspaces`, `workspace_sources` (F4-B Core),
> `topic_versions` (F5-C), `digest_subscriptions` (F6), `watch_interests`,
> `watch_matches` (F11), `embeddings` (RAG).
>
> Decision **расширен** под production scale; SQLite removal — отдельная
> архитектурная эволюция (не покрыта новым ADR — opportunistic candidate
> для future ADR 0007).

## Решение

- Логическая модель:
  - основная сущность – `KnowledgeBaseEntry` (см. `docs/contracts/knowledge_base_entry.schema.json`);
  - каждое сообщение Telegram порождает 0..N записей в базе знаний (в MVP — как результат CLI‑экспорта).
- MVP / локальный запуск:
  - **SQLite** как базовое хранилище, с разделением на отдельные файлы (см. TR‑17/TR‑42):
    - `ingestion_state.sqlite` — состояние ingestion (источники/статусы/курсоры);
    - `raw_storage.sqlite` — raw‑сообщения (уникальность по `source_ref`);
    - `processing_storage.sqlite` — результаты обработки (`ProcessedDocument`, `TopicCard`, `TopicBundle`).
- Серверный запуск / рост:
  - целевая СУБД — **PostgreSQL** (конкурентный доступ, масштабирование, удобнее для будущего API/интеграций).
- Доступ к данным:
  - **SQLAlchemy 2.x (async)** как единый слой доступа к SQLite/PostgreSQL (миграция без смены контрактов и без переписывания пайплайна).
- Индексация / поиск:
  - в MVP слой **Access / Export** = CLI‑экспорт (TR‑55..TR‑64), отдельный поисковый движок не обязателен;
  - при добавлении поиска: PostgreSQL **FTS** (tsvector) и/или **pgvector** для векторного индекса.

## Последствия

- Чёткий контракт `KnowledgeBaseEntry` позволяет менять конкретную СУБД/движок без переписывания всего пайплайна.
- Появляется возможность подключать несколько индексов (полнотекстовый, векторный) к одной логической модели.

## Addendum (2026-06-26) — cross-logical-branch `NOT EXISTS` join (BUG-069 / B2)

**Context.** The logical split into 3 areas (ingestion / raw / processing) is
realised as 3 Alembic branches + 3 SQLAlchemy engines, but they all point at the
**same physical PostgreSQL database** (`migrations/env.py` — все engines используют
`settings.db_name/db_host/db_port`; SQLite removed). Historically every repo query
stayed inside its own branch's tables.

**Decision.** The BUG-069 / B2 fix introduces the **first deliberate
cross-logical-branch reference** in the codebase:
`RawMessageRepo.list_unprocessed_by_channel` (impl in
`tg_parser/storage/sqlalchemy/raw_message_repo.py`) runs, on the **raw** connection,
a `NOT EXISTS (SELECT 1 FROM processed_documents p WHERE p.source_ref = r.source_ref)`
sub-select against a **processing**-branch table, with `ORDER BY r.date ASC,
r.source_ref ASC LIMIT :limit`.

**Option A follow-up (2026-06-27, BUG-069 starvation fix).** When the caller
passes `failure_cooldown_enabled=True`, the same method ALSO anti-joins a second
**processing**-branch table — `processing_failures` — to exclude refs whose
failure is still inside its category-specific cooldown (predicate mirrors
`pipeline._should_skip_failed`: billing / parse-after-N / default TTLs, future-date
clamp). Without it, oldest perpetually-failing messages (which only ever get a
`processing_failures` row, never a `processed_documents` row) form a poison-pill
prefix that consumes the whole bounded window and starves newer actionable docs.
Both anti-joins are backed by the target tables' `source_ref` primary keys, so
**no new index and no migration** are required. The same physical-DB rationale and
constraint below cover this second cross-branch reference.

**Why it is acceptable.**
- The branches are the same physical DB, so a single SQL statement can legally
  reference `processed_documents` by table name from the raw session — no
  cross-database / dblink machinery, no distributed transaction.
- Pushing the filter + `LIMIT` into one query lets Postgres bound the sort to a
  small window (backed by `raw_messages_channel_date_idx (channel_id, date)`),
  eliminating the full-backlog `ORDER BY` that spilled to `pgsql_tmp`
  (`DiskFullError`, BUG-069) and the per-tick token/cost re-burn (B2).
- `date` is fixed-width ISO-8601 UTC TEXT, so lexicographic == chronological order;
  `source_ref` is the stable tie-breaker for deterministic paging.
- It is **read-only** and additive: `list_by_channel` and the branch boundaries are
  otherwise unchanged; the per-message `processed_repo.exists()` check in the
  pipeline remains as a correctness backstop for `force` / agent callers.

**Constraint this creates.** These joins are sound **only while raw and processing
share one physical database**. If a future ADR splits processing onto a separate
physical instance, this method MUST be revisited (e.g. a `processed_documents` +
`processing_failures` source_ref read on the processing engine + an anti-join in
Python, or a materialised "processed / in-cooldown source_refs" projection on the
raw branch). Документировано
здесь так, чтобы такой split не пропустил эту зависимость. См. BUG_LOG § BUG-069.

## Ссылки

- Выбранный стек (язык/Telegram/LLM/хранилище): `docs/tech-stack.md`
- Минимальная схема SQLite (MVP): `docs/architecture.md` (раздел “Целевая минимальная схема таблиц (SQLite, MVP)”)
- BUG-069 / B2 fix: `docs/notes/BUG_LOG.md` § BUG-069


