# F4: Multi-Tenancy -- Финальный план реализации

> **Источник:** Скопировано из `.cursor/plans/f4_multi-tenancy_final_3f48b1a3.plan.md` для сохранности в репозитории.
>
> **Статус фаз:**
> - Phase 1 (Data Model + Migrations) -- DONE (Session 1)
> - Phase 2 (Auth Resolution + CurrentUser) -- DONE (Session 1)
> - Phase 3 (Channel Ownership) -- PLANNED (Session 2)
> - Phase 4 (Scoped Data Access) -- PLANNED (Session 2)
> - Phase 5 (User Management Tools) -- PLANNED (Session 3)

---

## Результаты аудита: расхождения с оригинальным планом

### 1. IVFFlat, не HNSW
Индекс `document_embeddings` -- **IVFFlat** (`lists=100`), не HNSW. WHERE-clause по `channel_ids` работает корректно (фильтр применяется во время скана IVF-листов), но при низкой selectivity нужен `SET ivfflat.probes` (не `hnsw.ef_search` как в старом плане).

### 2. F5-A уже реализован
`document_embeddings` уже содержит `entry_type` (default `'message'`) и `topic_id`. Функция `_ensure_embedding_columns()` в [processing_storage.py](tg_parser/storage/sqlalchemy/schemas/processing_storage.py) добавляет эти колонки идемпотентно. Нужно расширить её для `channel_ids`.

### 3. MCP Context injection
MCP SDK 1.26 поддерживает `ctx: Context` как параметр tool-функции. `ctx.client_id` возвращает `client_id` из `AccessToken`. FastMCP автоматически скрывает `ctx` от схемы инструмента. Это решает проблему прокидывания auth-контекста в MCP tools.

### 4. Файловая структура
- Source CRUD: [ingestion_state_repo.py](tg_parser/storage/sqlalchemy/ingestion_state_repo.py) (не отдельный `source_repo.py`)
- `Source` класс: [ports.py](tg_parser/storage/ports.py) (не `domain/models.py`)
- `save_batch()`: принимает 4-tuple `(source_ref, embedding, model, metadata)` + `entry_type` и `topic_id` как kwargs
- Topic cards: фильтрация по `sources_json LIKE '%"channel_id"%'` (нет колонки `channel_id`)

### 5. Тесты распределяются по фазам
Отдельная Phase 6 (Tests) **убрана**. Тесты пишутся вместе с каждой фазой -- быстрая обратная связь, меньше рисков.

### 6. Дополнительные точки скоупинга (выявлены при ревизии)
- **Export** ([export.py](tg_parser/api/routes/export.py)): `channel_id=None` экспортирует ВСЕ данные; `status/download` не проверяют ownership job. Нужен scoping.
- **Agent routes** ([agents.py](tg_parser/api/routes/agents.py)): task history глобальная, содержит `channel_id`. Делаем admin-only.
- **Topic links** ([topic_linking_service.py](tg_parser/services/topic_linking_service.py)): `get_related_topics_for()` возвращает темы из ЛЮБЫХ каналов. Нужна фильтрация по `allowed_channel_ids`.
- **LLM config / reload_prompts**: глобальные side-effects. Добавляем admin-only enforcement.
- **CLI**: работает без user identity -- всегда admin. Не требует изменений.

### 7. Auth identifier: hash-at-lookup
`user_auth_mappings.auth_identifier` хранит SHA-256 хеш (api_key, mcp_token) или plain text (telegram_user_id). Lookup flow: `hash(incoming_raw_key)` -> `SELECT WHERE auth_type=:type AND auth_identifier=:hash`. Это НЕ сравнение raw key с DB -- raw keys никогда не хранятся в БД.

### 8. Cross-channel linking: осознанно глобальное
`link_topics()` и `_run_cross_channel_linking()` остаются **глобальными** -- это функция качества данных (поиск семантических связей), не privacy feature. Topic links создаются между темами любых каналов. **Но отображение** (get_related_topics) фильтруется по `allowed_channel_ids` -- user видит только связи к своим темам.

---

## Архитектурные решения (финальные)

### Passing user context через слои

```
Interface layer          Service layer              Repo layer
(API/Bot/MCP)            (retrieval, analytics)     (embedding_repo, etc.)
     |                        |                          |
CurrentUser ──resolve──> allowed_channel_ids ──param──> WHERE channel_ids && ARRAY[...]
```

- **Interface -> Service**: `allowed_channel_ids: list[str] | None` (None = admin, все каналы)
- **Service -> Repo**: тот же `channel_ids` параметр прокидывается в SQL
- `CurrentUser` dataclass живёт только на interface layer; сервисы и репо не зависят от него

### MCP: `ctx: Context` injection

```python
@mcp.tool()
async def search_knowledge_base(query: str, ..., ctx: Context) -> ...:
    user = await resolve_mcp_user(ctx.client_id)  # cached
    results = await search(query, allowed_channel_ids=user.allowed_channel_ids)
```

`BearerTokenVerifier` изменяется: `verify_token()` резолвит token -> user_id через DB, возвращает `AccessToken(client_id=str(user_id))`. В stdio-режиме `ctx.client_id` = None -> admin.

### Bot: `UserResolutionMiddleware`

Заменяет `AllowlistMiddleware`. Резолвит `telegram_user_id` -> `CurrentUser` через `user_auth_mappings`. Кладёт в `data["current_user"]`. Незарегистрированный user -> reject.

### API: `Depends(resolve_current_user)`

Заменяет `Depends(verify_api_key)`. Резолвит API key -> `CurrentUser` через `user_auth_mappings`. Если `api_key_required=False` и ключ не передан -> admin (backward compat).

---

## Phase 1: Data Model + Migrations (~0.5 сессии) -- DONE

### DDL

**users + user_auth_mappings** (в [ingestion_state.py](tg_parser/storage/sqlalchemy/schemas/ingestion_state.py)):

```sql
CREATE TABLE IF NOT EXISTS users (
    ...  -- id UUID PK, name, role, max_channels INT DEFAULT NULL, timestamps
);
CREATE TABLE IF NOT EXISTS user_auth_mappings (...);  -- user_id FK, auth_type, auth_identifier, UNIQUE
ALTER TABLE sources ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
```

`users.max_channels` -- per-user лимит каналов. `NULL` = использовать глобальный дефолт из settings (`DEFAULT_MAX_CHANNELS`, default 20). Позволяет admin назначить разным пользователям разные лимиты.

**document_embeddings.channel_ids** (в [processing_storage.py](tg_parser/storage/sqlalchemy/schemas/processing_storage.py)):

```sql
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS channel_ids TEXT[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_de_channel_ids ON document_embeddings USING GIN(channel_ids);
```

### Файлы Phase 1

- [tg_parser/storage/sqlalchemy/schemas/ingestion_state.py](tg_parser/storage/sqlalchemy/schemas/ingestion_state.py) -- DDL: users, user_auth_mappings, sources.owner_id
- [tg_parser/storage/sqlalchemy/schemas/processing_storage.py](tg_parser/storage/sqlalchemy/schemas/processing_storage.py) -- DDL: channel_ids + GIN index + расширить `_ensure_embedding_columns`
- [tg_parser/storage/ports.py](tg_parser/storage/ports.py) -- `User` dataclass (+`max_channels: int | None`), `UserAuthMapping` dataclass; `UserRepo` ABC; `Source.owner_id`; `DocumentEmbedding.channel_ids`; `EmbeddingRepo.save()` + `similarity_search()` сигнатуры
- `tg_parser/storage/sqlalchemy/user_repo.py` (новый) -- SAUserRepo
- [tg_parser/config/settings.py](tg_parser/config/settings.py) -- `default_max_channels: int = 20`
- [tg_parser/storage/sqlalchemy/embedding_repo.py](tg_parser/storage/sqlalchemy/embedding_repo.py) -- `save()`, `save_batch()`, `similarity_search()` + `channel_ids`
- [tg_parser/storage/sqlalchemy/ingestion_state_repo.py](tg_parser/storage/sqlalchemy/ingestion_state_repo.py) -- `upsert_source`: persist `owner_id`; `list_sources`: optional `owner_id` filter
- [tg_parser/services/db_context.py](tg_parser/services/db_context.py) -- `user_repo()` context manager
- Alembic migrations (ingestion + processing)

### Тесты Phase 1

- `tests/test_f4_user_model.py`: UserRepo CRUD, resolve_auth, get_owned_channel_ids
- `tests/test_f4_embedding_channel_ids.py`: save/save_batch populate channel_ids, similarity_search

---

## Phase 2: Auth Resolution + CurrentUser (~0.5 сессии) -- DONE

### CurrentUser

```python
@dataclass
class CurrentUser:
    id: str
    name: str
    role: str  # 'admin' | 'user'
    allowed_channel_ids: list[str] | None  # None = admin (все каналы)
    max_channels: int  # per-user лимит (из users.max_channels или settings.default_max_channels)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
```

### Файлы Phase 2

- `tg_parser/auth/` (новый пакет) -- `models.py` (CurrentUser), `resolvers.py` (resolve functions + cache)
- [tg_parser/api/auth.py](tg_parser/api/auth.py) -- `resolve_current_user()` dependency
- [tg_parser/bot/middleware.py](tg_parser/bot/middleware.py) -- `UserResolutionMiddleware`
- [tg_parser/mcp_server.py](tg_parser/mcp_server.py) -- `BearerTokenVerifier` + `resolve_mcp_user()`

### Тесты Phase 2

- `tests/test_f4_auth_resolution.py`: API key -> user, Telegram ID -> user, MCP token -> user, anonymous -> admin, etc.

---

## Phase 3: Channel Ownership (~0.5 сессии)

### Enforcement points

**Channel operations (owner or admin):**
- `add_channel`: требует authenticated user, `source.owner_id = current_user.id`. Лимит active sources = `current_user.max_channels` (per-user, настраиваемый). Убрать захардкоженный `MAX_ACTIVE_SOURCES = 20` из [mcp_server.py](tg_parser/mcp_server.py) и [bot/tools.py](tg_parser/bot/tools.py)
- `remove_channel`: only owner or admin
- `pause_channel` / `resume_channel`: only owner or admin
- `trigger_pipeline`: only owner or admin
- `list_channels`: scoped по owner_id (admin видит все)
- `get_pipeline_status`: scoped по owner channels

**Global admin-only operations:**
- `set_llm_config`, `reset_llm_config`: глобальное изменение LLM для всего процесса. Только admin.
- `reload_prompts`: глобальная перезагрузка промптов. Только admin.

### Файлы Phase 3

- [tg_parser/mcp_server.py](tg_parser/mcp_server.py) -- `add_channel`, `remove_channel`, `pause_channel`, `resume_channel`, `trigger_pipeline`, `list_channels`, `get_pipeline_status`: добавить `ctx: Context`, resolve user, ownership check
- [tg_parser/bot/tools.py](tg_parser/bot/tools.py) -- `_exec_add_channel`, `_exec_remove_channel`, etc.: получать `current_user`, ownership check
- [tg_parser/api/routes/channels.py](tg_parser/api/routes/channels.py) -- scoped listing
- [tg_parser/api/routes/process.py](tg_parser/api/routes/process.py) -- ownership check на trigger

### Тесты Phase 3 (~15 тестов)

- `tests/test_f4_ownership.py`: add channel with owner, remove as owner/admin/other, pause/resume scoping, list_channels scoped, configurable max_channels

---

## Phase 4: Scoped Data Access (~1 сессия) -- наибольший объём

### Repo layer

- [tg_parser/storage/sqlalchemy/embedding_repo.py](tg_parser/storage/sqlalchemy/embedding_repo.py): `similarity_search()` -- `WHERE channel_ids && ARRAY[:allowed_channels]`
- [tg_parser/storage/sqlalchemy/topic_card_repo.py](tg_parser/storage/sqlalchemy/topic_card_repo.py): новый метод `list_by_channels(channel_ids: list[str]) -> list[TopicCard]`
- [tg_parser/storage/ports.py](tg_parser/storage/ports.py): `TopicCardRepo.list_by_channels()` в ABC

### Service layer

- [tg_parser/services/retrieval_service.py](tg_parser/services/retrieval_service.py): `search()` и `answer()` получают `allowed_channel_ids`
- [tg_parser/services/analytics_service.py](tg_parser/services/analytics_service.py): `get_cross_channel_analytics()` получает `allowed_channel_ids`
- [tg_parser/services/channel_service.py](tg_parser/services/channel_service.py): `get_all_channel_stats()` получает `allowed_channel_ids`
- [tg_parser/services/topic_linking_service.py](tg_parser/services/topic_linking_service.py): `get_related_topics_for(topic_id, allowed_channel_ids)`

### MCP tools (все tools получают `ctx: Context`)

- `search_knowledge_base`, `ask_question` -- через `allowed_channel_ids` в retrieval
- `list_topics` -- `list_by_channels()` для non-admin
- `get_topic_details` -- verify topic sources overlap
- `get_document` -- ownership check
- `get_related_topics` -- filter через `allowed_channel_ids`
- `get_cross_channel_stats` -- scoped analytics

### Bot: полная цепочка propagation

1. [tg_parser/bot/handlers.py](tg_parser/bot/handlers.py): `handle_text()` передаёт `current_user` в agent
2. [tg_parser/bot/agent.py](tg_parser/bot/agent.py): `process_message(user_message, current_user)` передаёт в `execute_tool`
3. [tg_parser/bot/tools.py](tg_parser/bot/tools.py): все `_exec_*` прокидывают `allowed_channel_ids` в сервисы

### API routes

- [tg_parser/api/routes/rag.py](tg_parser/api/routes/rag.py): search + ask -> `allowed_channel_ids`
- [tg_parser/api/routes/topics.py](tg_parser/api/routes/topics.py): list + detail -> filter
- [tg_parser/api/routes/documents.py](tg_parser/api/routes/documents.py): ownership check
- [tg_parser/api/routes/export.py](tg_parser/api/routes/export.py): export scoped
- [tg_parser/api/routes/agents.py](tg_parser/api/routes/agents.py): **admin-only**

### IVFFlat tuning

`SET ivfflat.probes = 20` per-session при низкой selectivity.

### Тесты Phase 4 (~30 тестов)

- `tests/test_f4_scoped_access.py`: search returns only user's data, list_topics scoped, analytics scoped, etc.
- `tests/test_f4_vector_search_isolation.py`: SQL-level channel_ids filter, IVFFlat + GIN interaction

---

## Phase 5: User Management Tools + Migration Script (~0.5 сессии)

### New tools (MCP + Bot + API)

- `register_user(name, role?, max_channels?, auth_mappings?)` -- **admin only**. `max_channels` -- per-user лимит (NULL = глобальный дефолт)
- `update_user(user_id, name?, role?, max_channels?)` -- **admin only**. Позволяет изменить лимит каналов для конкретного пользователя
- `list_users()` -- **admin only** (показывает name, role, max_channels, owned_channels_count)
- `whoami` -- свой профиль (имя, роль, N каналов / лимит)
- `add_user_auth(user_id, auth_type, identifier)` -- **admin only**
- `remove_user_auth(mapping_id)` -- **admin only**

### API routes

- `GET /api/v1/users` -- admin only
- `POST /api/v1/users` -- admin only
- `GET /api/v1/users/me` -- current user info
- `PATCH /api/v1/users/{id}` -- admin only (name, role, max_channels)
- `DELETE /api/v1/users/{id}` -- admin only

### Bot UX

- Незарегистрированный user -> "/start не зарегистрирован. Обратитесь к администратору."
- `whoami` -> имя, роль, N каналов

### Migration helper (CLI command)

`tg-parser migrate-users` -- одноразовая утилита: создаёт admin user, маппит существующие API keys / MCP tokens / bot_allowed_users из settings, присваивает owner_id всем sources.

### Тесты Phase 5 (~15 тестов)

- `tests/test_f4_user_management.py`: register, list, whoami, add/remove auth, admin enforcement, migration script

---

## Риски и митигации (обновлённые)

- **GIN + IVFFlat**: pgvector IVFFlat сканирует ближайшие листы, затем применяет WHERE. При low selectivity (<5%) часть листов может не содержать matching rows. Митигация: `SET ivfflat.probes = 20` per-session. При 1M+ embeddings -- рассмотреть HNSW + partial indexes.
- **Backward compat**: single-user deployment работает без изменений. Без auth -> default admin user. Admin `allowed_channel_ids=None` -> SQL без WHERE по channel_ids.
- **Performance**: `resolve_user_by_auth()` вызывается на каждый запрос. Митигация: in-memory LRU cache (maxsize=256, TTL 60s). Cache invalidation при add/remove auth mapping.
- **MCP stdio**: `ctx.client_id` = None в stdio -> default admin user (полный доступ как сейчас).
- **Alembic migration**: backfill channel_ids для ~5400 embeddings -- одна транзакция, ~1-2 секунды. Topic embeddings: парсинг `sources_json` в Python.
- **Bot handler chain**: `handlers.py` -> `agent.py` -> `tools.py` -- все три звена обновляются для propagation `current_user`.
- **Auth hash timing**: `secrets.compare_digest` для сравнения hex-encoded SHA-256 хешей (защита от timing attacks).
- **Topic LIKE chain**: `list_by_channels()` генерирует `OR`-chain из LIKE patterns. При 50+ allowed channels это может стать медленным. Митигация: при большом числе channels использовать `list_all()` + Python filter.

## Общая оценка: ~3 сессии (вместо ~3.5-4)

| Сессия | Фазы | Объём |
|--------|------|-------|
| Session 1 | Phase 1 + Phase 2 | **DONE** (1128 тестов) |
| Session 2 | Phase 3 + Phase 4 | ~45 новых тестов |
| Session 3 | Phase 5 | ~15 новых тестов |

## Промпты для сессий

- Session 1: `docs/prompts/F4_MULTI_TENANCY_SESSION1_PROMPT.md`
- Session 2: `docs/prompts/F4_MULTI_TENANCY_SESSION2_PROMPT.md`
- Session 3: `docs/prompts/F4_MULTI_TENANCY_SESSION3_PROMPT.md`
