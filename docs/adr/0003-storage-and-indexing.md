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

## Ссылки

- Выбранный стек (язык/Telegram/LLM/хранилище): `docs/tech-stack.md`
- Минимальная схема SQLite (MVP): `docs/architecture.md` (раздел “Целевая минимальная схема таблиц (SQLite, MVP)”)


