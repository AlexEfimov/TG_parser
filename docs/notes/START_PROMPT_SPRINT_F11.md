# Sprint F11 — Topic Watchlist (тематические алерты)

**Дата подготовки:** 19 апреля 2026 (по итогам Sprint A.7 / DI-19, Session 55).
**Тип сессии:** Feature (~1.5–2 сессии, 2 коммита: schema+service, потом интерфейсы+интеграция).
**HEAD на момент написания:** `b0a1c99` на `origin/main` (Sprint A.7 закрыт, migration tech-debt = 0, CI зелёный по 5/5 jobs).
**Связанные задачи в [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md):** F11 (~line 1733, статус **READY** — все блокеры сняты).
**Roadmap:** F5-A Phase 3 ✅ → F2 ✅ → F6 ✅ → **F11 (эта)** → F5-C → (опционально F5-B при сигнале из метрик).
**Прецеденты (читать перед стартом):**
- `docs/plans/F6_SCHEDULED_DIGESTS_PLAN.md` — структура feature-prompt'а; готовая инфраструктура `BackgroundScheduler` + cron + ownership-aware tools (F11 переиспользует на 80%).
- `docs/prompts/F6_SCHEDULED_DIGESTS_PROMPT.md` — стиль раскладки checklist + risks.
- `tg_parser/services/digest_service.py` + `tg_parser/storage/sqlalchemy/digest_subscription_repo.py` — образец для `watchlist_service.py` + `watch_interest_repo.py`.
- `tg_parser/processing/topicization.py::_compute_match_score` (lines 380+) — готовая логика keyword-scoring, прямо переносимая.
- `tg_parser/services/embedding_service.py` — pgvector embedding API (для interest.embedding).

---

## Цель сессии

Добавить **F11: Topic Watchlist** — пользователь регистрирует «интерес» (заголовок + keywords + опциональное описание + список каналов + threshold), и после каждого incremental pipeline бот присылает push-уведомление по новым сообщениям, прошедшим hybrid-scoring (keyword + semantic).

**MVP scope (одна сессия):**
1. **Schema + migration** в `ingestion` БД: таблицы `watch_interests`, `watch_matches` с FK на `users.id` (multi-tenancy сразу — F4 уже DONE, нечего откладывать).
2. **`WatchInterestRepo` + `WatchMatchRepo`** в `tg_parser/storage/sqlalchemy/` + porty в `tg_parser/storage/ports.py`.
3. **`WatchlistService`** в `tg_parser/services/watchlist_service.py` — hybrid matching (keyword + cosine), запись `watch_matches`, `notify(matches)` через `Bot.send_message`.
4. **Hook в scheduler** — после `incremental_pipeline_task` для каждого источника, если есть `new_doc_refs` → `watchlist_service.check_interests(new_doc_refs, channel_id)`.
5. **MCP/Bot/CLI tools (5–6 штук):** `subscribe_watchlist`, `list_watchlists`, `unsubscribe_watchlist`, `get_watchlist_matches`, по образцу F6 digest-tools.
6. **Notify mode = `instant`** (push в bot chat) — единственный режим в MVP. `batch` (через F6 digest-инфраструктуру) и `silent` (только запись без push) — Phase 2, отдельным PR.

### Не входит в сессию (Phase 2, отдельный PR при сигнале)

- `notify_mode = batch` — агрегация matches в дайджест-style сообщение с cron'ом (требует переиспользования `digest_service.py` рендереров).
- `notify_mode = silent` — без push, только REST/MCP `get_watchlist_matches`.
- LLM-based matching ("содержит ли этот текст утверждения по интересу X?") — слишком дорого для каждого нового сообщения; добавим если hybrid scoring даст ложные срабатывания.
- HTTP API endpoints (`POST /api/v1/watchlists` etc.) — MCP/bot/CLI достаточно для пилота. Web UI ещё далеко (P6c в backlog).
- F4-B Workspaces scoping (interest viден всем участникам workspace) — пока interest привязан к user_id напрямую.

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на b0a1c99 или новее
gh run list --branch main --limit 3              # CI на main зелёный?

# Local стек
docker compose ps                                # tg_parser_postgres healthy
docker exec tg_parser_postgres psql -U postgres -d tg_parser_ingestion \
  -c "SELECT * FROM alembic_version_ingestion;"  # должна быть последняя ревизия
docker exec tg_parser_postgres psql -U postgres -d tg_parser_ingestion \
  -c "\dt"                                       # увидеть users, sources, digest_subscriptions

# Базовая регрессия — что ничего не сломалось локально с прошлой сессии
.venv/bin/pytest -q --tb=line | tail -5

# Прочитать F11 entry в FUTURE_FEATURES.md
grep -nE "^## F11|^### " docs/notes/FUTURE_FEATURES.md | head -30
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` (sustained lesson из Sprints A → A.7 — иначе CI красный на line-length / I001 / B023).

**Pre-condition:** F4 (multi-tenancy) и F6 (Scheduled Digests) смерджены. F4 даёт `users.id` для FK, F6 — паттерн ownership-aware tools и интеграцию с `BackgroundScheduler`. Sprint A.7 закрыл alembic как единственный источник правды — миграция F11 пишется чисто через `op.create_table(...)`, без legacy DDL fallback.

---

## Контекст: что мы знаем из аудита 19 апреля 2026

Все цифры/пути проверены grep'ом в HEAD `b0a1c99`, не из памяти.

### Что уже есть (foundation, переиспользуем)

| Слой | Что | Где |
|---|---|---|
| Multi-tenancy | `users.id UUID`, `sources.owner_id` FK, `resolve_user_by_auth("telegram", str(uid))` | `migrations/versions/ingestion/20260416_add_users_and_ownership.py`, `tg_parser/services/user_service.py`, `tg_parser/bot/middleware.py:77–81` |
| Ownership-aware tools | `assert_channel_access(user, channel_id)`, паттерн «admin или owner» | `tg_parser/mcp_server.py` (см. `add_channel`, `subscribe_digest`) |
| Scheduler hook point | `scheduler_service.run_incremental_for_all_sources` уже возвращает `new_doc_refs` per source после `run_full_pipeline(...)` | `tg_parser/services/scheduler_service.py` (точное место — между existing `run_incremental_topicization(...)` и финальным `summary.append(...)`) |
| Embedding pipeline | `embedding_service.embed_text(text) -> list[float]` (1536-dim), `embedding_repo.similarity_search(...)` через pgvector cosine | `tg_parser/services/embedding_service.py`, `tg_parser/storage/sqlalchemy/embedding_repo.py` |
| Bot push | `aiogram.Bot.send_message(chat_id, text, parse_mode="HTML")` уже используется в F6 для доставки дайджестов | `tg_parser/services/digest_service.py::deliver` |
| Bot tool registry | `_TOOL_DECLARATIONS` + `_TOOL_EXECUTORS` + `_TOOLS_NEEDING_BOT_CONTEXT` | `tg_parser/bot/tools.py:26–27, 39+, 1885–1908` |
| MCP tool pattern | `@mcp.tool() async def foo(..., ctx: Context | None = None)` + `current_user = await resolve_mcp_user(ctx.client_id)` | `tg_parser/mcp_server.py` (~line 800+ для F6 tools) |
| Keyword scoring | `_compute_match_score(topic_card, doc_text)` — Jaccard-like over normalized tokens | `tg_parser/processing/topicization.py:380+` |
| Conftest test_db | session-scoped alembic upgrade head + per-test TRUNCATE CASCADE (ставится Sprint A.7) | `tests/conftest.py:_alembic_initialized_test_db` + `test_db` fixture |

### Hidden gotchas

1. **Embedding для interest.description.** Если description пустой — fallback к `title + " " + " ".join(keywords)`. **Никогда** не embed'ить пустую строку (OpenAI вернёт 400). В тестах — мокировать `EmbeddingService` через `monkeypatch`, иначе тесты будут жечь токены.

2. **Cosine similarity over `vector(1536)`.** В pgvector используется оператор `<=>` (cosine distance, **не** similarity). Similarity = `1 - (a <=> b)`. В `WatchInterestRepo.find_matches_for_channel(...)` нельзя писать `WHERE 1 - (interest.embedding <=> doc_embedding) >= threshold` напрямую без явного приведения — pgvector чувствителен к типам. Образец правильного синтаксиса — в `embedding_repo.similarity_search` (используется в RAG).

3. **`new_doc_refs` после incremental pipeline.** В `scheduler_service.run_incremental_for_all_sources(...)` после `run_full_pipeline(source.source_id)` нужно явно собрать ID новых `ProcessedDocument`. Проверить, возвращает ли `run_full_pipeline` структурированный результат с `new_processed_doc_ids`, или нужно делать `processed_document_repo.list_by_channel(channel_id, from_date=run_start_at)` и diff'нуть с предыдущим cursor. **Скорее всего нужен ProcessedDocumentRepo.list_by_channel(..., from_date=...)** (уже есть, см. `storage/ports.py:411–417`).

4. **Idempotency `watch_matches`.** `UNIQUE(interest_id, source_ref)` — ловит повторы при retry pipeline. `INSERT ... ON CONFLICT DO NOTHING` через SQLAlchemy `dialect_postgresql.insert(...).on_conflict_do_nothing(...)`. Без этого retry дублирует уведомления (catastrophic UX bug).

5. **chat_id для notification.** Для private chat = `telegram_user_id`. Для group/supergroup нужен явный `chat_id` в `watch_interests.chat_id`. **MVP:** при создании через bot брать `message.chat.id` (Telegram сам отдаст правильный); при создании через MCP/CLI — обязательный параметр `chat_id`. Документировать в tool description.

6. **Когда interest.is_active = false.** Не загружать в `check_interests(...)`, не присылать notify. CLI `unsubscribe_watchlist` должен делать SOFT delete (`is_active = false`), а не `DELETE` — иначе теряем `watch_matches` history.

7. **Conftest fixture.** В Sprint A.7 `tests/conftest.py` стал session-scoped alembic upgrade. Новая F11 миграция автоматически подхватится без изменений в conftest. Но если тестам нужен seed (несколько `WatchInterest` для разных пользователей) — это per-test, через function-scoped fixture в `tests/test_f11_watchlist.py`.

8. **Notification batching на одно сообщение от пользователя.** Если за один pipeline tick совпало 5 матчей по одному interest — слать **одно** сообщение со списком из 5 элементов (как в F11-mockup из FUTURE_FEATURES.md `🔔 Найдено по теме: ...`), а не 5 отдельных push'ей (флуд). Group by `interest_id` перед `Bot.send_message`.

9. **Threshold default = 0.7 — реалистичный?** Из логики `0.4 * keyword + 0.6 * semantic`: для семантически близких документов cosine обычно 0.7–0.85, keyword overlap 0.2–0.5. Combined ~0.55–0.71. Threshold 0.7 = «строгий», поймает только сильные совпадения. **MVP default = 0.6**, документировать что пользователь может тюнить через `--threshold` в `subscribe_watchlist`. Telemetry-метрика `tg_watchlist_matches_total{interest_id, score_bucket}` покажет реальное распределение.

10. **Конфликт с topicization-scheduler-hook.** Сейчас `scheduler_service.run_incremental_for_all_sources` ВЫЗЫВАЕТ `run_incremental_topicization(channel_id, new_doc_refs)`. F11 hook добавляется **после** этого вызова — потому что `WatchlistService` использует `processed_document.summary` + `processed_document.entities` + topics, которые формируются на topicization-этапе. Если `topicization` падает — `watchlist_check` всё равно запускается, но скорится по «сырому» `text_clean` (graceful degradation, не блокер).

11. **Embedding storage — единая таблица или отдельная?** В `document_embeddings` живут эмбеддинги документов. Interest-embedding 1536-dim может жить **inline** в `watch_interests.embedding vector(1536)` (как в design из FUTURE_FEATURES.md) — нет смысла плодить ещё одну таблицу. pgvector extension уже включён в processing БД, для ingestion БД нужно **добавить `CREATE EXTENSION vector` в первой строке F11-миграции** (если ещё не включён там). **Проверить grep'ом** перед написанием миграции: `grep -rn "vector" migrations/versions/ingestion/`.

---

## План шагов

### Шаг 1: Аудит готовой инфраструктуры (10 минут)

```bash
# Где живут pgvector extensions
grep -rn "CREATE EXTENSION vector\|create_extension.*vector" migrations/

# Текущий contract scheduler_service по new_doc_refs
grep -nE "new_doc_refs|new_processed_doc|run_full_pipeline" tg_parser/services/scheduler_service.py

# Образец F6 для копирования паттерна
grep -nE "subscribe_digest|list_digests|unsubscribe_digest" tg_parser/mcp_server.py | head

# Текущий repo-test pattern
grep -nE "DigestSubscription|digest_subscriptions" tests/test_f6_scheduled_digests.py | head
```

**Output:** строка-приговор «pgvector extension в ingestion БД: есть/нет», «new_doc_refs в scheduler_service: возвращается/надо дотягивать», «F6 tools sample: line X:Y».

### Шаг 2: Schema + migration (20 минут)

Файл: `migrations/versions/ingestion/20260419_add_watchlist.py` (next slot — проверь `ls migrations/versions/ingestion/` и возьми следующий timestamp).

```python
"""add watchlist (F11)

Revision ID: <8 hex>
Revises: <previous head — текущий head ingestion ветки>
Create Date: 2026-04-19 ...
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "<8 hex>"
down_revision = "<previous head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Если ext не включён в ingestion DB — включить (no-op если уже есть):
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "watch_interests",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("keywords", sa.dialects.postgresql.ARRAY(sa.Text),
                  server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("exclude_keywords", sa.dialects.postgresql.ARRAY(sa.Text),
                  server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("channel_ids", sa.dialects.postgresql.ARRAY(sa.Text),
                  nullable=False),  # FK не ставим: source_ids — внешние Telegram-ID
        sa.Column("threshold", sa.Float, server_default=sa.text("0.6"), nullable=False),
        sa.Column("notify_mode", sa.String(20),
                  server_default=sa.text("'instant'"), nullable=False),
        sa.Column("is_active", sa.Boolean,
                  server_default=sa.true(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_match_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_watch_interests_user_id", "watch_interests", ["user_id"])
    op.create_index("idx_watch_interests_active", "watch_interests",
                    ["is_active"], postgresql_where=sa.text("is_active = true"))

    op.create_table(
        "watch_matches",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("interest_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("watch_interests.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("channel_id", sa.String(200), nullable=False),
        sa.Column("keyword_score", sa.Float, nullable=False),
        sa.Column("semantic_score", sa.Float, nullable=False),
        sa.Column("combined_score", sa.Float, nullable=False),
        sa.Column("notified", sa.Boolean,
                  server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("interest_id", "source_ref",
                            name="uq_watch_matches_interest_source"),
    )
    op.create_index("idx_watch_matches_interest_created",
                    "watch_matches", ["interest_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_watch_matches_interest_created", table_name="watch_matches")
    op.drop_table("watch_matches")
    op.drop_index("idx_watch_interests_active", table_name="watch_interests")
    op.drop_index("idx_watch_interests_user_id", table_name="watch_interests")
    op.drop_table("watch_interests")
    # CREATE EXTENSION vector НЕ дропаем — мог использоваться другими F-фичами.
```

Также добавить `Table()` декларации в `tg_parser/storage/sqlalchemy/_metadata.py` (для `target_metadata` и `alembic check`).

Smoke:
```bash
.venv/bin/tg-parser db check --db ingestion       # No new upgrade operations detected
.venv/bin/tg-parser db upgrade --db ingestion     # ровно 1 ревизия применена
docker exec tg_parser_postgres psql -U postgres -d tg_parser_ingestion \
  -c "\d watch_interests" -c "\d watch_matches"
```

### Шаг 3: Domain + ports (15 минут)

`tg_parser/domain/models.py` — добавить:
```python
class WatchInterest(BaseModel):
    id: UUID
    user_id: UUID
    chat_id: int
    title: str
    description: str | None
    keywords: list[str]
    exclude_keywords: list[str]
    channel_ids: list[str]
    threshold: float
    notify_mode: Literal["instant", "batch", "silent"]  # MVP: только instant
    is_active: bool
    embedding: list[float] | None  # 1536-dim или None если ещё не embed'нули
    last_checked_at: datetime | None
    last_match_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WatchMatch(BaseModel):
    id: int
    interest_id: UUID
    source_ref: str
    channel_id: str
    keyword_score: float
    semantic_score: float
    combined_score: float
    notified: bool
    created_at: datetime
```

`tg_parser/storage/ports.py` — добавить:
```python
class WatchInterestRepo(Protocol):
    async def create(self, interest: WatchInterest) -> WatchInterest: ...
    async def get(self, interest_id: UUID) -> WatchInterest | None: ...
    async def list_for_user(self, user_id: UUID) -> list[WatchInterest]: ...
    async def list_active_for_channel(self, channel_id: str) -> list[WatchInterest]: ...
    async def soft_delete(self, interest_id: UUID) -> bool: ...
    async def touch_checked(self, interest_id: UUID, at: datetime) -> None: ...


class WatchMatchRepo(Protocol):
    async def upsert_many(self, matches: list[WatchMatch]) -> list[WatchMatch]: ...
    async def list_for_interest(
        self, interest_id: UUID, since: datetime | None = None
    ) -> list[WatchMatch]: ...
    async def mark_notified(self, match_ids: list[int]) -> None: ...
```

### Шаг 4: Repo implementations (30 минут)

`tg_parser/storage/sqlalchemy/watch_interest_repo.py` + `watch_match_repo.py` — по образцу `digest_subscription_repo.py`. Ключевые моменты:

- `upsert_many` использует `dialect_postgresql.insert(WatchMatchTable).values(...).on_conflict_do_nothing(index_elements=["interest_id", "source_ref"]).returning(WatchMatchTable)`.
- `list_active_for_channel(channel_id)` фильтрует по `is_active = true AND :channel_id = ANY(channel_ids)`.
- Embedding читается/пишется как `np.array` или `list[float]` напрямую — pgvector через SQLAlchemy типизирован.

### Шаг 5: WatchlistService (45 минут)

`tg_parser/services/watchlist_service.py`:

```python
class WatchlistService:
    def __init__(
        self,
        interest_repo: WatchInterestRepo,
        match_repo: WatchMatchRepo,
        document_repo: ProcessedDocumentRepo,
        embedding_service: EmbeddingService,
        bot: Bot | None = None,  # для notify; None в тестах
    ) -> None:
        ...

    async def create_interest(
        self, *, user_id: UUID, chat_id: int, title: str,
        keywords: list[str], channel_ids: list[str],
        description: str | None = None, exclude_keywords: list[str] | None = None,
        threshold: float = 0.6,
    ) -> WatchInterest:
        # 1. Валидация (threshold ∈ [0, 1], channel_ids непустой, ...)
        # 2. Embed: text = description or f"{title}. keywords: {' '.join(keywords)}"
        # 3. interest_repo.create(...)

    async def check_interests(
        self, new_doc_refs: list[str], channel_id: str,
    ) -> list[WatchMatch]:
        # 1. interests = await interest_repo.list_active_for_channel(channel_id)
        # 2. docs = [await document_repo.get_by_source_ref(ref) for ref in new_doc_refs]
        # 3. doc_embeddings = batched embed (если embeddings уже посчитаны
        #    embedding_service.get_for_source_refs — переиспользовать; иначе embed)
        # 4. matches = []
        #    for interest in interests:
        #        for doc, doc_emb in zip(docs, doc_embeddings):
        #            score = compute_watch_score(interest, doc, doc_emb)
        #            if score >= interest.threshold:
        #                matches.append(WatchMatch(...))
        # 5. saved = await match_repo.upsert_many(matches)  # idempotent
        # 6. await self.notify(saved)
        # 7. await interest_repo.touch_checked(interest.id, now())

    async def notify(self, matches: list[WatchMatch]) -> None:
        # Group by interest_id, по группе формируем одно сообщение,
        # bot.send_message(chat_id, ..., parse_mode="HTML"),
        # затем match_repo.mark_notified(group_match_ids).

    async def list_user_interests(self, user_id: UUID) -> list[WatchInterest]: ...
    async def get_matches(self, interest_id: UUID, since: datetime | None = None) -> list[WatchMatch]: ...
    async def delete_interest(self, interest_id: UUID, user_id: UUID) -> bool: ...
```

`compute_watch_score` — pure-function, помещаем в тот же модуль или отдельный `watchlist_scoring.py`:

```python
def compute_watch_score(
    interest: WatchInterest,
    doc_text: str,
    doc_topics: list[str],
    doc_embedding: list[float],
) -> tuple[float, float, float]:
    """Returns (keyword_score, semantic_score, combined_score)."""
    interest_tokens = {k.lower() for k in interest.keywords}
    doc_tokens = {t.lower() for t in doc_topics} | _tokenize(doc_text.lower())

    if interest.exclude_keywords:
        exclude = {k.lower() for k in interest.exclude_keywords}
        if exclude & doc_tokens:
            return 0.0, 0.0, 0.0  # negative filter

    keyword = (
        len(interest_tokens & doc_tokens) / max(len(interest_tokens), 1)
        if interest_tokens else 0.0
    )

    semantic = (
        cosine_similarity(interest.embedding, doc_embedding)
        if interest.embedding else 0.0
    )

    combined = 0.4 * keyword + 0.6 * semantic
    return keyword, semantic, combined
```

`cosine_similarity` — взять из `tg_parser/processing/embedding_utils.py` (уже есть для RAG) или скопировать numpy-вариант.

### Шаг 6: Scheduler integration (15 минут)

`tg_parser/services/scheduler_service.py::run_incremental_for_all_sources` — найти хвост обработки одного source:

```python
# СУЩЕСТВУЮЩЕЕ:
new_doc_refs = result.new_doc_refs  # или эквивалент
if new_doc_refs:
    await run_incremental_topicization(...)

# ДОБАВИТЬ ПОСЛЕ:
if new_doc_refs and watchlist_service is not None:
    try:
        matches = await watchlist_service.check_interests(
            new_doc_refs, source.channel_id
        )
        if matches:
            logger.info("watchlist matches",
                        channel_id=source.channel_id,
                        match_count=len(matches))
    except Exception as exc:
        # Не валим pipeline на сбое уведомлений
        logger.exception("watchlist check failed",
                         channel_id=source.channel_id, error=str(exc))
```

`watchlist_service` инжектится через `services_provider.get_watchlist_service()` (или прямо в конструктор `IncrementalPipelineService`, по образцу того как `digest_service` пробрасывается). **Не делать** singleton, **не делать** lazy import — резать тесты на моках через DI.

### Шаг 7: MCP/Bot/CLI tools (45 минут)

#### MCP tools (`tg_parser/mcp_server.py`)

По образцу `subscribe_digest` / `list_digests` / `unsubscribe_digest`:

```python
@mcp.tool()
async def subscribe_watchlist(
    title: str,
    keywords: list[str],
    channel_ids: list[str],
    chat_id: int,
    description: str | None = None,
    exclude_keywords: list[str] | None = None,
    threshold: float = 0.6,
    ctx: Context | None = None,
) -> dict:
    """Создать тематический алерт. Бот будет присылать ..."""
    user = await resolve_mcp_user(ctx.client_id if ctx else None)
    for ch_id in channel_ids:
        await assert_channel_access(user, ch_id)
    interest = await watchlist_service.create_interest(
        user_id=user.id, chat_id=chat_id, title=title,
        keywords=keywords, channel_ids=channel_ids,
        description=description, exclude_keywords=exclude_keywords or [],
        threshold=threshold,
    )
    return {"interest_id": str(interest.id), "title": interest.title, ...}


@mcp.tool()
async def list_watchlists(ctx: Context | None = None) -> list[dict]: ...
@mcp.tool()
async def unsubscribe_watchlist(interest_id: str, ctx: Context | None = None) -> dict: ...
@mcp.tool()
async def get_watchlist_matches(
    interest_id: str, since_iso: str | None = None,
    ctx: Context | None = None,
) -> dict: ...
```

Не забыть зарегистрировать в `mcp_server.py` и добавить use-instructions (см. как сделан `subscribe_digest` в текущем файле).

#### Bot tools (`tg_parser/bot/tools.py`)

- Добавить 4 декларации в `_TOOL_DECLARATIONS` (по образцу F6 digest tools — там уже паттерн).
- Добавить executors в `_TOOL_EXECUTORS`.
- `subscribe_watchlist` нужен `bot` контекст (в смысле — `chat_id` берётся из `message.chat.id`); добавить в `_TOOLS_NEEDING_BOT_CONTEXT = {"export_channel", "subscribe_watchlist"}`.
- В executor `_execute_subscribe_watchlist(args, *, bot, chat_id, ...)` — если в args нет `chat_id` (Gemini не извлёк), подставлять из контекста.

#### CLI commands (`tg_parser/cli/app.py`)

`tg-parser watchlist add --title "..." --keywords k1,k2 --channels @c1,@c2 --threshold 0.6 --chat-id 12345` (CLI = full power user, обязательный `--chat-id`).
`tg-parser watchlist list --user-id <UUID>` (admin может смотреть чужие).
`tg-parser watchlist remove <interest_id>`.
`tg-parser watchlist matches <interest_id> --since 2026-04-19`.

Файл реализации: `tg_parser/cli/watchlist_cmd.py` (новый), регистрация в `app.py` через `app.add_typer(watchlist_cmd.app, name="watchlist")` (паттерн как `digest_cmd.py`).

### Шаг 8: Tests (60 минут)

Целевая дельта: ~25–30 новых тестов, baseline после A.7 актуальный (узнаем `pytest -q | tail -3`).

| Файл | Покрытие |
|---|---|
| `tests/test_watchlist_service.py` (новый) | `compute_watch_score` (positive / negative filter / только keyword / только semantic / threshold ровно на границе); `WatchlistService.check_interests` (matches пишутся, idempotent, notify вызывается, soft fail при упавшем bot); `create_interest` embedding fallback на `title + keywords`. |
| `tests/test_watch_interest_repo.py` (новый) | CRUD, `list_active_for_channel`, `soft_delete` оставляет matches. |
| `tests/test_watch_match_repo.py` (новый) | `upsert_many` идемпотентен, `mark_notified` обновляет только указанные id, `list_for_interest(since)` фильтрует по `created_at`. |
| `tests/test_f11_watchlist_integration.py` (новый, под `TEST_POSTGRES`) | E2E на реальной PG: создать interest, скормить 3 фейк-документа (matched + matched_dup + non-match), вызвать `check_interests`, проверить matches и idempotency на повторном вызове. |
| `tests/test_mcp_watchlist_tools.py` (новый) | `subscribe_watchlist` ownership check (admin / owner / третий user), `unsubscribe_watchlist` запрещён чужим. |
| `tests/test_scheduler_watchlist_hook.py` (новый) | scheduler hook — `check_interests` вызывается с `new_doc_refs`, исключение в watchlist не валит pipeline. |
| `tests/test_bot_tools_v13_watchlist.py` (новый) | Bot tool declarations в `_TOOL_DECLARATIONS`, executor роутинг работает, `chat_id` пробрасывается из bot-context. |

Patterns:
- Repo тесты — `postgres_settings` fixture из conftest.
- Service тесты — моки `WatchInterestRepo`, `WatchMatchRepo`, `ProcessedDocumentRepo`, `EmbeddingService`, `Bot` (через `MagicMock`).
- Scheduler тесты — моки + проверка interaction по `assert_called_once_with(...)`.

### Шаг 9: Lint + format

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
```

### Шаг 10: Документация

| Файл | Что обновить |
|---|---|
| `docs/notes/FUTURE_FEATURES.md` § F11 | Добавить статус `✅ MVP DONE 19.04.2026` поверх существующего design-doc'а. Список реализованного / отложенного на Phase 2 (batch / silent / LLM-matching). |
| `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` § «Пост-F5-A Phase 3» | Строка F11 → ✅ Выполнено [date], следующая — F5-C. |
| `docs/USER_GUIDE.md` | Новый раздел «Topic Watchlist (F11)» — как пользоваться через бот, MCP, CLI; примеры; параметры. |
| `docs/MCP_AGENT_GUIDE.md` | Новые tools: subscribe_watchlist, list_watchlists, unsubscribe_watchlist, get_watchlist_matches с примерами. |

### Шаг 11: Атомарный коммит + push + watch CI

Опция A — один коммит. Опция B — два коммита (schema+service vs interfaces+integration). **Рекомендуется B**: чище review, отдельный fail-domain в CI.

```bash
# Commit 1
git add migrations/versions/ingestion/20260419_add_watchlist.py \
        tg_parser/storage/sqlalchemy/_metadata.py \
        tg_parser/domain/models.py \
        tg_parser/storage/ports.py \
        tg_parser/storage/sqlalchemy/watch_interest_repo.py \
        tg_parser/storage/sqlalchemy/watch_match_repo.py \
        tg_parser/services/watchlist_service.py \
        tg_parser/services/services_provider.py \
        tests/test_watchlist_service.py \
        tests/test_watch_interest_repo.py \
        tests/test_watch_match_repo.py \
        tests/test_f11_watchlist_integration.py
git commit -m "$(cat <<'EOF'
feat(F11): Topic Watchlist — schema + service + repos (1/2)

Persistent thematic alerts: user defines an "interest" (title +
keywords + description + channels + threshold), and after each
incremental pipeline tick we score new ProcessedDocuments via a
hybrid keyword+semantic match.  Matches with combined score above
threshold are stored in `watch_matches` (idempotent via
UNIQUE(interest_id, source_ref)) ready for delivery.

This commit lays the persistence + scoring foundation:

- migrations/versions/ingestion/20260419_add_watchlist.py:
  watch_interests + watch_matches in ingestion DB; pgvector ext
  ensured (idempotent CREATE EXTENSION IF NOT EXISTS).  user_id FK
  to users.id (multi-tenancy via F4 ✅).
- tg_parser/storage/sqlalchemy/_metadata.py: Table() declarations
  added (drift-checked by alembic-guardrail CI job).
- tg_parser/domain/models.py: WatchInterest + WatchMatch pydantic.
- tg_parser/storage/ports.py: WatchInterestRepo + WatchMatchRepo.
- tg_parser/storage/sqlalchemy/{watch_interest_repo,watch_match_repo}.py:
  CRUD, list_active_for_channel, idempotent upsert_many.
- tg_parser/services/watchlist_service.py: check_interests
  (hybrid scoring, group-by-interest notify), create_interest
  (embedding fallback when description empty).
- tests/test_watchlist_service.py + repo tests: 18 unit tests
  covering scoring edge cases, idempotency, soft-delete.
- tests/test_f11_watchlist_integration.py: E2E PG smoke (gated
  on TEST_POSTGRES).

Interfaces (MCP/Bot/CLI tools) and scheduler hook follow in
commit 2/2.

Closes F11 design from FUTURE_FEATURES.md (foundation only).
EOF
)"

# Commit 2 — interfaces + scheduler hook
git add tg_parser/services/scheduler_service.py \
        tg_parser/mcp_server.py \
        tg_parser/bot/tools.py \
        tg_parser/cli/app.py \
        tg_parser/cli/watchlist_cmd.py \
        tests/test_mcp_watchlist_tools.py \
        tests/test_scheduler_watchlist_hook.py \
        tests/test_bot_tools_v13_watchlist.py \
        docs/USER_GUIDE.md \
        docs/MCP_AGENT_GUIDE.md \
        docs/notes/FUTURE_FEATURES.md \
        docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md
git commit -m "$(cat <<'EOF'
feat(F11): Topic Watchlist — MCP/Bot/CLI tools + scheduler hook (2/2)

Adds user-facing surface for the watchlist persistence layer from
commit 1/2.

- mcp_server.py: 4 new tools (subscribe_watchlist,
  list_watchlists, unsubscribe_watchlist, get_watchlist_matches),
  ownership-aware (admin OR owner OR has channel access).
- bot/tools.py: 4 new declarations + executors mirror MCP tools.
  subscribe_watchlist receives chat_id from bot context per the
  F2 export_channel pattern.
- cli/watchlist_cmd.py: full-power CLI (`tg-parser watchlist
  {add,list,remove,matches}`), registered under app.add_typer.
- services/scheduler_service.py: hook after
  run_incremental_topicization, calls
  watchlist_service.check_interests with new_doc_refs.  Failures
  log + continue (graceful degradation; pipeline not blocked).
- 12 new tests covering MCP ownership, scheduler hook, bot tool
  routing.

MVP scope:
- notify_mode=instant only (push to chat_id via Bot.send_message).
- batch (digest-style aggregation) + silent (no push) + LLM-based
  matching → Phase 2 if production metrics show need.

Verification: pytest --tb=short -q ⇒ baseline + ~30 passed,
0 failures, 0 new skips.  ruff format + check clean.  CI green
(5/5 jobs).

Roadmap: F11 ✅ → F5-C (Evolving Topic Summaries) is next.
EOF
)"

git push origin main
gh run watch
```

---

## Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| `CREATE EXTENSION vector` падает на ingestion DB (нет permissions) | Low | Dev-инстанс `pgvector/pgvector:pg17` запускается с superuser. На VPS — postgres superuser. Если фейлится — отдельным шагом руками `psql -U postgres -d tg_parser_ingestion -c "CREATE EXTENSION vector"` и retry миграции. |
| Threshold 0.6 даёт слишком много false-positive | Medium | Telemetry-метрика `tg_watchlist_matches_total{score_bucket="0.6-0.7","0.7-0.8","0.8+"}` покажет распределение. Через неделю реальной работы — корректировать default или документировать tuning. |
| Notification flood при подключении нового канала с большим backfill | High | **MVP-защита:** в `check_interests` обрабатывать максимум `MAX_DOCS_PER_TICK = 100` за один call; остаток — следующий tick. После DI-5 при backfill пользователь может получить десятки match'ей; документировать в `subscribe_watchlist` description: «при первом подключении канала возможна серия уведомлений». |
| `Bot.send_message` падает с `Chat not found` (пользователь удалил приватный чат с ботом) | Medium | Поймать в `notify`, пометить interest как `is_active = false` + лог. Не валить pipeline. |
| pgvector `<=>` cosine distance vs similarity путаница | Low | Pinned образец из `embedding_repo.similarity_search`. Тест на конкретные значения через известные эмбеддинги (mock-ed). |
| F4 `users.id` UUID — какой-то interest у удалённого пользователя | Low | FK `ON DELETE CASCADE` — удаление пользователя удаляет interests + matches. Без вмешательства. |
| Scheduler hook увеличивает latency tick'а | Low | Hybrid scoring без LLM — < 50 ms / interest. Embedding документов уже посчитаны на стадии processing, не пересчитываем. При 10 active interests × 50 docs = 500 операций cosine — < 1s. |
| Rollback после push | Low | `git revert <commit2> <commit1>` + ручной `tg-parser db downgrade --db ingestion --revisions 1 --yes`. Никаких production-data degradation. |

**Rollback:** `git revert HEAD~1 HEAD` → `git push` → CI восстановит код. Затем `docker compose run --rm tg_parser tg-parser db downgrade --db ingestion --revisions 1 --yes` на VPS — миграция откатится, таблицы исчезнут, остальные F-фичи продолжают работать (изоляция через ingestion DB и отсутствие FK от других таблиц).

---

## PR checklist

- [ ] Миграция `migrations/versions/ingestion/20260419_add_watchlist.py` создана; `tg-parser db check --db ingestion` → `No new upgrade operations detected.`; `Table()` декларации в `_metadata.py`.
- [ ] `pgvector` extension включён в ingestion БД (idempotent `CREATE EXTENSION IF NOT EXISTS`).
- [ ] `WatchInterest` + `WatchMatch` доменные модели в `domain/models.py`.
- [ ] `WatchInterestRepo` + `WatchMatchRepo` ports + SQLAlchemy реализации, `upsert_many` идемпотентен.
- [ ] `WatchlistService` с `compute_watch_score` (negative filter работает; threshold ровно на границе включает; пустой keywords-set → keyword_score = 0; пустой interest.embedding → semantic_score = 0).
- [ ] Embedding fallback: при пустом description embed `f"{title}. {' '.join(keywords)}"`.
- [ ] Scheduler hook в `run_incremental_for_all_sources` — после `run_incremental_topicization`, fail-soft через `try/except + logger.exception`.
- [ ] MCP tools (4): `subscribe_watchlist`, `list_watchlists`, `unsubscribe_watchlist`, `get_watchlist_matches`. Ownership через `assert_channel_access` для каналов + admin/owner для interest.
- [ ] Bot tools (4): декларации + executors + `subscribe_watchlist` ∈ `_TOOLS_NEEDING_BOT_CONTEXT`.
- [ ] CLI: `tg-parser watchlist {add,list,remove,matches}`.
- [ ] Notification: group by `interest_id`, одно сообщение на группу, HTML-formatting, `match_repo.mark_notified` после send.
- [ ] `MAX_DOCS_PER_TICK = 100` защита от flood при backfill.
- [ ] Tests: ~30 новых, repo + service + integration (PG-gated) + MCP + bot + scheduler hook.
- [ ] `pytest --tb=short -q` зелёный, baseline + ~30 passed.
- [ ] `ruff format` + `ruff check .` чистые.
- [ ] CI: 5/5 jobs зелёные.
- [ ] `docs/USER_GUIDE.md` — новый раздел F11 с примерами.
- [ ] `docs/MCP_AGENT_GUIDE.md` — описания 4 новых tools.
- [ ] `docs/notes/FUTURE_FEATURES.md` § F11 — `✅ MVP DONE`, scope явно прописан, Phase 2 в backlog.
- [ ] `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — строка F11 → ✅, следующая F5-C явно помечена.
- [ ] Commit messages содержат: `feat(F11)`, breaking changes (нет), verification numbers, ссылку на дизайн-док FUTURE_FEATURES.

---

## После F11 — что дальше

Согласно зафиксированной 19 апреля 2026 последовательности:

1. **F5-C: Evolving Topic Summaries** (~1 сессия) — re-summarize TopicCard при добавлении N новых supporting items + re-embed; версионирование (append-only `topic_card_versions`). Закрывает последний пробел в Living KB-контракте «темы знают о новых материалах, но не помнят их содержания».
2. **F5-B (near-duplicate via embedding ≥ 0.97)** — отложен до сигнала из метрики `tg_dedup_duplicates_detected_total{channel_id}`. F5-A Phase 3 (content-hash) уже снимает ~80%; без размеченного корпуса порог 0.95/0.97/0.98 выбирается вслепую. Если через 2–4 недели реального трафика метрика покажет устойчивый поток near-dup → разворачиваем как **F5-B Phase 3.5** в отдельной сессии.
3. **DI-5** (operational backfill 4 каналов) — параллельный ops-таск, не требует фокуса; при включении нового канала или окне обслуживания.
4. **Опциональный DI-20** (snapshot test для alembic schema) — только при появлении конкретной потребности (миграция unauthorized edit, который должен был быть пойман regression-сейфом).

**Совокупно:** F11 + F5-C ≈ **2.5–3 сессии до конца Волны 2 / входа в Волну 3**. После этого продукт имеет полный living-KB цикл (ingestion → processing → topicization → continuous summaries → user-defined alerts → scheduled digests), готовый к расширению на F4-A Multi-User или F8-B Redis/queue.
