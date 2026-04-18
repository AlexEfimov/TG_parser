# F6 — Scheduled Digests — Implementation Plan

**Версия проекта:** 4.7.0+ (после мёрджа F2 — `feat/f2-parse-only-export`, PR #10)
**Scope:** Автоматические сводки (digests) по выбранным каналам, доставка через Telegram-бот по расписанию (cron). Подписки хранятся в новой таблице `digest_subscriptions`; LLM-summarization по новым `ProcessedDocument`-ам с момента последнего запуска. Управление подписками через bot-tools и MCP-tools. Добавляем `CronTrigger` в существующий `BackgroundScheduler` (уже работающий на `IntervalTrigger`). Новый стейдж LLM `digest` (env-overrides + runtime switch).
**Предыдущие фазы:** Wave 1.5 → F8-A ✅ → F5-A Phase 1 (Hybrid) ✅ → Phase 2 (Relevance tuning) ✅ → Phase 3 (Deduplication) ✅ → F2 (Parse-Only Export) ✅ (ожидает мёрджа PR #10).
**Design-doc:** [`../notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F6: Scheduled Digests — автоматические сводки по расписанию"
**Starter prompt:** [`../prompts/F6_SCHEDULED_DIGESTS_PROMPT.md`](../prompts/F6_SCHEDULED_DIGESTS_PROMPT.md)
**Ветка:** `feat/f6-scheduled-digests` (создать от `main` после мёрджа PR #10)

---

## Контекст (что уже есть)

### Scheduler

- [`tg_parser/services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py) — обёртка над `AsyncIOScheduler` (`BackgroundScheduler` class lines 19–38, `add_task` + `IntervalTrigger` lines 47–95, `start`/`shutdown` 149–166, singleton `get_scheduler()` 173–178, `setup_default_tasks()` 260–318). **Используется только `IntervalTrigger`**, `CronTrigger` нигде не зарегистрирован.
- [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) — `incremental_pipeline_task` (337–353), `run_scheduler_blocking` для CLI daemon (275–329), `get_scheduler_status` (251–260) показывает `Source.poll_interval_seconds` в reporting'е, **но scheduler сам интервал per-source не использует** (тик глобальный — `settings.scheduler_default_interval`).
- Lifecycle:
  - **FastAPI:** `tg_parser/api/main.py` lines 157–184 — при старте если `settings.scheduler_enabled` → `get_scheduler()` + `setup_default_tasks(...)` + `scheduler.start()`; на shutdown `scheduler.shutdown(wait=True)`.
  - **CLI daemon:** `tg_parser/services/scheduler_service.py` 275–329 — создаёт **новый** `BackgroundScheduler()` (НЕ singleton), регистрирует, ждёт сигнала.
- `tzdata` уже в `uv.lock` (зависимость некоторых пакетов); `pytz` отсутствует — используем `zoneinfo` (stdlib) для cron-таймзон.

### Processed-doc слой

- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) lines 411–417 — `ProcessedDocumentRepo.list_by_channel(channel_id, from_date?, to_date?) -> list[ProcessedDocument]`.
- [`tg_parser/storage/sqlalchemy/processed_document_repo.py`](../../tg_parser/storage/sqlalchemy/processed_document_repo.py) lines 169–196 — фильтр по **`processed_at`** (не `date`). **Это то, что нам нужно** для cursor "новые с прошлого раза".
- [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py) — `ProcessedDocument` имеет `summary`, `entities`, `text_clean`, `processed_at`, `channel_id`, `source_ref` — достаточно для составления дайджеста без обращения к raw.

### LLM / prompts

- [`tg_parser/processing/prompt_loader.py`](../../tg_parser/processing/prompt_loader.py) lines 17–78, 379–386 — `PromptLoader` грузит `{name}.yaml` из `settings.prompts_dir` (default `prompts/`). YAML структура: `system.prompt`, `user.template`, `model.{temperature, max_tokens, ...}`. Reload через MCP-tool `reload_prompts(name="digest")`.
- [`tg_parser/processing/llm/factory.py`](../../tg_parser/processing/llm/factory.py) lines 33–48 — `resolve_llm_config(stage)` → `llm_config.resolve(stage)`. Поддерживаемые scopes: `LLM_SCOPES = ("global", "processing", "topicization", "rag")` ([`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) line 657). **Расширяем до `("global", "processing", "topicization", "rag", "digest")`**.
- Per-stage env vars в `Settings`: `processing_llm_provider/_model`, `topicization_*`, `rag_*` ([`settings.py`](../../tg_parser/config/settings.py) 138–144). Добавляем `digest_llm_provider`/`digest_llm_model` тем же шаблоном.

### Bot

- [`tg_parser/bot/main.py`](../../tg_parser/bot/main.py) lines 151–154 — `Bot(token=..., default=DefaultBotProperties(...))` создаётся в `run_bot()`. Bot-инстанс доступен в handler через `message.bot`.
- [`tg_parser/bot/handlers.py`](../../tg_parser/bot/handlers.py) lines 143–148 — `agent.process_message(..., bot=message.bot, chat_id=message.chat.id)` — паттерн прокидывания bot/chat_id из F2.
- [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py) lines 26–27, 581–616 — `_TOOLS_NEEDING_BOT_CONTEXT = {"export_channel"}`, `execute_tool` условно прокидывает `bot`/`chat_id`. `TOOL_DECLARATIONS` (line 39+), executor registry `_TOOL_EXECUTORS` (1885–1908). Паттерн F2 переиспользуется для digest-tools.
- [`tg_parser/bot/middleware.py`](../../tg_parser/bot/middleware.py) lines 77–81 — F4 user resolution через `resolve_user_by_auth("telegram", str(user_id))`. **`chat_id` нигде НЕ хранится отдельно** — для private chat `chat_id == telegram_user_id` (Telegram convention), для group/supergroup нужен явный `chat_id` в подписке.

### MCP

- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — паттерн `@mcp.tool() async def foo(..., ctx: Context | None = None)`, `current_user = await resolve_mcp_user(ctx.client_id if ctx else None)`, ownership через `assert_channel_access(user, channel_id)` (для каналов) или `if not user.is_admin and entity.owner_id != user.id: raise ...` (для прочих сущностей; см. `add_channel` 834–866).

### Storage / migrations

- [`migrations/env.py`](../../migrations/env.py) lines 96–106, 114–123 — multi-DB setup: ingestion / raw / processing, `version_locations = migrations/versions/{db_name}`, version-table `alembic_version_{db_name}`.
- Пример F4 миграции с `users` + `owner_id`: [`migrations/versions/ingestion/20260416_add_users_and_ownership.py`](../../migrations/versions/ingestion/20260416_add_users_and_ownership.py) — в этой же DB живут `sources.owner_id` (FK на `users.id` UUID). **`digest_subscriptions` — в `ingestion` DB** (тот же контекст user-owned ресурсов).

### Tests baseline

- `1536 passed` (после F2). Целевая дельта F6: ~25–30 новых тестов → ≥1561 после Commit 1, ≥1567+ после Commit 2.
- Patterns:
  - Repo: `tests/test_storage_integration.py` (PG fixture).
  - Scheduler: `tests/test_scheduler_service.py`, `tests/test_phase3d_advanced.py::TestBackgroundScheduler`, `tests/test_f8a_hardening.py`.
  - Bot: `tests/test_bot_tools_v11.py`, `tests/test_bot_tools_v12.py`.
  - PG fixture: `tests/conftest.py::postgres_settings` (88–93) + `pytest.mark.skipif(not os.environ.get("TEST_POSTGRES"), ...)`.

### Observed constraints

- **Idempotency cursor:** дайджест не должен повторно включать те же сообщения. Используем `last_digest_cursor: TIMESTAMPTZ` — фильтр `processed_at > last_digest_cursor` (strict greater).
- **`chat_id` в private vs group:** для private = telegram user id, для group/supergroup — отрицательное число (Telegram convention). Подписка хранит `chat_id` явно — пользователь может оформить дайджест в private, в группу, в канал (если бот admin).
- **CronTrigger таймзоны:** APScheduler принимает `timezone=ZoneInfo("Europe/Moscow")`. Хранимое поле `timezone VARCHAR(50)` валидируется при создании подписки — `try ZoneInfo(tz)` → 400 при неверном.
- **Ownership:** `digest_subscriptions.owner_id` (FK `users.id`). Не-админ видит/редактирует только свои; админ видит всё. **Каналы в `channel_ids[]` обязаны принадлежать owner'у** (или быть public — но F6 в scope ограничивается owned channels через `assert_channel_access` для каждого `channel_id`).
- **Empty digest:** если новых ProcessedDocument нет — НЕ слать сообщение (suppress empty digests), но обновить `last_sent_at` для статистики. Альтернатива (heartbeat) — отдельный флаг подписки в опциональных расширениях.
- **LLM cost cap:** дайджест может включать сотни новых сообщений → ограничиваем до **`DIGEST_MAX_DOCS_PER_RUN`** (default 50) самых свежих per channel; в шаблоне отмечаем "(показаны 50 из N новых)".

---

## Архитектура

```mermaid
flowchart TD
  subgraph Scheduler
    Cron[CronTrigger<br/>per subscription] -->|tick| Task[run_scheduled_digests]
  end

  Task --> Loop[for each active subscription]
  Loop --> Fetch[ProcessedDocumentRepo.list_by_channel<br/>processed_at > last_digest_cursor]
  Fetch -->|empty| Skip[skip + update last_sent_at]
  Fetch -->|N docs| Trim[cap to DIGEST_MAX_DOCS_PER_RUN per channel]
  Trim --> LLM[DigestService.summarize<br/>prompts/digest.yaml]
  LLM --> Format[format Markdown by channel]
  Format --> Send[Bot.send_message chat_id]
  Send --> Update[update last_digest_cursor=max(processed_at)<br/>+ last_sent_at=now]

  subgraph Management
    BotTools[bot tools:<br/>subscribe_digest<br/>list_digests<br/>unsubscribe_digest]
    MCPTools[mcp tools: same triple]
    BotTools --> Repo
    MCPTools --> Repo
    Repo[DigestSubscriptionRepo]
  end

  Repo --> Task
```

---

## Дизайн

### DB schema (Alembic migration в `ingestion` DB)

```sql
CREATE TABLE digest_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    name VARCHAR(200) NOT NULL,
    channel_ids TEXT[] NOT NULL CHECK (array_length(channel_ids, 1) >= 1),
    cron_expression VARCHAR(100) NOT NULL DEFAULT '0 9 * * *',
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    format VARCHAR(20) NOT NULL DEFAULT 'summary',  -- 'summary' | 'bullets' | 'detailed'
    language VARCHAR(10) NOT NULL DEFAULT 'ru',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_sent_at TIMESTAMPTZ,
    last_digest_cursor TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_digest_subscriptions_owner_active
    ON digest_subscriptions(owner_id, is_active);

CREATE INDEX idx_digest_subscriptions_active_cron
    ON digest_subscriptions(is_active) WHERE is_active = true;
```

### Domain model

[`tg_parser/domain/models.py`](../../tg_parser/domain/models.py) — добавить:

```python
class DigestFormat(StrEnum):
    SUMMARY = "summary"
    BULLETS = "bullets"
    DETAILED = "detailed"


class DigestSubscription(BaseModel):
    id: UUID
    owner_id: UUID
    chat_id: int
    name: str
    channel_ids: list[str]
    cron_expression: str
    timezone: str
    format: DigestFormat
    language: str
    is_active: bool
    last_sent_at: datetime | None
    last_digest_cursor: datetime | None
    created_at: datetime
    updated_at: datetime
```

### Repo port

[`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) — после `IngestionStateRepo`:

```python
class DigestSubscriptionRepo(Protocol):
    async def create(self, sub: DigestSubscription) -> DigestSubscription: ...
    async def get(self, sub_id: UUID) -> DigestSubscription | None: ...
    async def update(
        self,
        sub_id: UUID,
        *,
        is_active: bool | None = None,
        last_sent_at: datetime | None = None,
        last_digest_cursor: datetime | None = None,
        cron_expression: str | None = None,
        timezone: str | None = None,
        format: DigestFormat | None = None,
        language: str | None = None,
    ) -> DigestSubscription: ...
    async def delete(self, sub_id: UUID) -> bool: ...
    async def list_by_owner(self, owner_id: UUID) -> list[DigestSubscription]: ...
    async def list_active(self) -> list[DigestSubscription]: ...
```

Реализация — `tg_parser/storage/sqlalchemy/digest_subscription_repo.py` (паттерн `processed_document_repo.py`).

### DigestService

Новый файл [`tg_parser/services/digest_service.py`](../../tg_parser/services/digest_service.py):

```python
@dataclass
class DigestResult:
    subscription_id: UUID
    chat_id: int
    title: str
    body_markdown: str
    docs_count: int
    new_cursor: datetime | None
    skipped: bool      # True если новых doc'ов не было


class DigestService:
    def __init__(
        self,
        processed_repo: ProcessedDocumentRepo,
        ingestion_repo: IngestionStateRepo,
        prompt_loader: PromptLoader,
        llm_factory: LLMFactory,  # см. processing/llm/factory.py
        max_docs_per_run: int = 50,
    ): ...

    async def generate(self, sub: DigestSubscription) -> DigestResult:
        """Fetch new docs since last_digest_cursor, summarize via LLM, format Markdown."""

    async def deliver(self, bot: Bot, result: DigestResult) -> None:
        """bot.send_message(chat_id, body_markdown, parse_mode=ParseMode.MARKDOWN_V2)."""

    async def run_for_subscription(self, sub: DigestSubscription, bot: Bot) -> DigestResult:
        """generate → deliver (if not skipped) → repo.update(last_digest_cursor, last_sent_at)."""
```

**Ключевые инварианты:**
- `from_date = sub.last_digest_cursor` (или `None` для первого запуска — берём всё за последние **24 часа**, чтобы не залить пользователя историей).
- `to_date = datetime.now(UTC)`.
- `new_cursor = max(doc.processed_at for doc in docs)` или `to_date` если `docs` пусты.
- Если `not docs and sub.last_digest_cursor is not None` → `skipped=True`, тело не отправляется, `last_sent_at` обновляется (для статистики).
- При первом запуске `last_digest_cursor is None` и `docs` пусты → `skipped=True`, `last_digest_cursor = to_date` (избегаем повторной "первой" 24-часовой выборки на следующем тике).

### Prompt template

Новый файл [`prompts/digest.yaml`](../../prompts/digest.yaml):

```yaml
system:
  prompt: |
    Ты ассистент-аналитик. Задача — сделать краткий дайджест новых сообщений
    из Telegram-каналов за указанный период. Группируй по каналам, выделяй
    главное, не выдумывай факты, не цитируй дословно длинные блоки.
    Стиль зависит от format: 'summary' — 1-2 параграфа на канал, 'bullets' —
    маркеры по 1 строке, 'detailed' — параграф + ключевые цитаты.
    Язык вывода: {{ language }}.

user:
  template: |
    Сформируй дайджест в формате '{{ format }}' за период
    {{ from_iso }} — {{ to_iso }}.

    Каналы и сообщения:
    {% for ch in channels %}
    ## {{ ch.title }} ({{ ch.docs|length }} новых)
    {% for doc in ch.docs %}
    - [{{ doc.processed_at_short }}] {{ doc.summary or doc.text_clean_truncated }}
    {% endfor %}
    {% endfor %}

model:
  temperature: 0.3
  max_tokens: 1500
```

### Scheduler integration

[`tg_parser/services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py) — расширить `BackgroundScheduler`:

```python
def add_cron_task(
    self,
    name: str,
    func: Callable[..., Awaitable[Any]],
    cron_expression: str,
    timezone: str = "UTC",
    args: tuple = (),
    kwargs: dict | None = None,
) -> Job:
    """Wrap apscheduler.triggers.cron.CronTrigger.from_crontab(...)."""
```

Новый task в [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py):

```python
async def run_scheduled_digests_task(subscription_id: str) -> None:
    """Resolve subscription, fetch new docs, summarize, deliver via bot."""
```

**Регистрация подписок:**
- При старте API/scheduler daemon: `repo.list_active()` → для каждой `add_cron_task(name=f"digest:{sub.id}", ...)`.
- При создании/изменении/удалении подписки через bot/MCP-tool: вызывать `scheduler.reschedule_subscription(sub)` / `scheduler.remove_subscription(sub_id)` — динамическое обновление job'ов **без рестарта**.
- Singleton scheduler (`get_scheduler()`) экспортирует helper `register_digest_subscription(sub)` / `unregister_digest_subscription(sub_id)`.

**Bot-инстанс из background task:** scheduler не имеет прямой ссылки на `aiogram.Bot`. Решение:
1. При старте бота (`tg_parser/bot/main.py::run_bot`) — после `Bot()` положить инстанс в module-level singleton `tg_parser.bot.runtime.set_bot(bot)`.
2. `digest_service.deliver` → `from tg_parser.bot.runtime import get_bot`. Если `get_bot()` is None (бот не запущен) → log warning + skip delivery + НЕ обновлять `last_digest_cursor` (повторим на следующем тике).
3. Альтернатива: каждый процесс (API, CLI daemon, bot daemon) запускает свой scheduler; digest task активен **только** в bot-процессе. Решение по результату prompt-mode review (см. `tg_parser/bot/main.py::run_bot` — там сейчас НЕТ scheduler.start). **Принятое решение:** активировать digest-scheduler только в bot-процессе через флаг `settings.digest_scheduler_enabled` (default `True` в bot, `False` в API/CLI daemon во избежание двойной отправки).

### Bot tools

[`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py) — добавить три declarations + executors:

```python
TOOL_DECLARATIONS.append({
    "name": "subscribe_digest",
    "description": "Создать подписку на регулярный дайджест по выбранным каналам. "
                   "Дайджест будет отправляться в текущий чат по расписанию.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Название подписки (для list/unsubscribe)"},
            "channel_ids": {"type": "array", "items": {"type": "string"},
                           "description": "Список channel_id (или username) для дайджеста"},
            "cron_expression": {"type": "string",
                                "description": "Cron expression (default: '0 9 * * *' = ежедневно 9:00)"},
            "timezone": {"type": "string", "description": "IANA timezone (default: UTC, e.g. Europe/Moscow)"},
            "format": {"type": "string", "enum": ["summary", "bullets", "detailed"], "default": "summary"},
            "language": {"type": "string", "default": "ru"},
        },
        "required": ["name", "channel_ids"],
    },
})
# + list_digests, unsubscribe_digest
```

Executors: `_exec_subscribe_digest`, `_exec_list_digests`, `_exec_unsubscribe_digest` — пишутся в стиле `_exec_export_channel` (ownership через `current_user`, валидация cron/timezone, ответ структурированным dict для агента-LLM).

**`_TOOLS_NEEDING_BOT_CONTEXT`:** `subscribe_digest` нужен `chat_id` (берём `message.chat.id` из handler-context) → добавить `"subscribe_digest"` в set.

### MCP tools

[`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — три `@mcp.tool()`:

```python
@mcp.tool()
async def subscribe_digest(
    name: str,
    channel_ids: list[str],
    chat_id: int,           # MCP-клиент должен указать chat_id явно (нет message-context)
    cron_expression: str = "0 9 * * *",
    timezone: str = "UTC",
    format: str = "summary",
    language: str = "ru",
    ctx: Context | None = None,
) -> SubscribeDigestResult: ...


@mcp.tool()
async def list_digests(ctx: Context | None = None) -> ListDigestsResult:
    """Non-admin: only own subscriptions. Admin: all."""


@mcp.tool()
async def unsubscribe_digest(subscription_id: str, ctx: Context | None = None) -> UnsubscribeDigestResult:
    """Ownership: non-admin can only delete own subscriptions."""
```

Pydantic-результаты — `SubscribeDigestResult`, `ListDigestsResult`, `UnsubscribeDigestResult` (как `ExportChannelResult`).

**Channel ownership:** при `subscribe_digest` для каждого `channel_id` вызвать `assert_channel_access(user, channel_id)` → не-владелец получает rejected.

### Settings

[`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) — добавить рядом с `scheduler_*` (lines 417–446) и `*_llm_*` (138–144):

```python
digest_scheduler_enabled: bool = Field(default=True, description="Enable digest scheduler in bot process")
digest_default_timezone: str = Field(default="UTC", description="Fallback IANA timezone")
digest_max_docs_per_run: int = Field(default=50, description="Cap docs per channel per digest")
digest_first_run_lookback_hours: int = Field(default=24, description="When last_digest_cursor is None, look back this many hours")

digest_llm_provider: str | None = Field(default=None, description="LLM provider override for digest stage")
digest_llm_model: str | None = Field(default=None, description="LLM model override for digest stage")
```

И в `LLM_SCOPES` (line 657): `("global", "processing", "topicization", "rag", "digest")`.

---

## Коммит 1 — Schema, Repo, Service, LLM stage, prompts

### 1.1 Migration

[`migrations/versions/ingestion/<timestamp>_add_digest_subscriptions.py`](../../migrations/versions/ingestion/) — `op.create_table('digest_subscriptions', ...)` + два индекса (см. §"DB schema").

### 1.2 Domain + Repo

- `tg_parser/domain/models.py` — `DigestFormat` + `DigestSubscription`.
- `tg_parser/storage/ports.py` — `DigestSubscriptionRepo` Protocol.
- `tg_parser/storage/sqlalchemy/models.py` — ORM `DigestSubscriptionORM`.
- `tg_parser/storage/sqlalchemy/digest_subscription_repo.py` — `SADigestSubscriptionRepo` (CRUD + `list_active` + `list_by_owner`).

### 1.3 LLM stage

- `tg_parser/config/settings.py` — `digest_llm_provider/_model` + `digest_*` подсистемные поля.
- Расширить `LLM_SCOPES` и `LLMConfigManager.resolve` ([`settings.py`](../../tg_parser/config/settings.py) 757–778) — `digest` как валидный stage.
- MCP `set_llm_config(scope="digest", ...)` — должно работать "из коробки" после расширения `LLM_SCOPES`.

### 1.4 Prompt

- `prompts/digest.yaml` — см. §"Prompt template".
- `MCP reload_prompts(name="digest")` — должен работать без правок (PromptLoader универсален).

### 1.5 DigestService

- `tg_parser/services/digest_service.py` — `DigestService` + `DigestResult` dataclass.
- Используем `resolve_llm_config("digest")` + `prompt_loader.load("digest")` — паттерн `tg_parser/services/rag_service.py` или `tg_parser/processing/processor.py` (выбрать ближайший образец в plan-mode).

### 1.6 Тесты Коммита 1

Новый файл `tests/test_f6_scheduled_digests.py`:

- **`TestDigestSubscriptionRepo`** (~6, requires Postgres):
  - `test_create_returns_uuid_and_persists`.
  - `test_get_returns_none_for_unknown_id`.
  - `test_update_partial_fields_preserves_others`.
  - `test_delete_returns_true_then_false`.
  - `test_list_by_owner_filters_correctly`.
  - `test_list_active_excludes_paused`.

- **`TestDigestService`** (~5, requires Postgres + LLM mock):
  - `test_generate_empty_when_no_new_docs_returns_skipped`.
  - `test_generate_first_run_uses_lookback_window`.
  - `test_generate_caps_docs_at_max_per_run`.
  - `test_generate_updates_cursor_to_max_processed_at`.
  - `test_generate_groups_by_channel_in_prompt`.

- **`TestDigestPromptLoader`** (~2, no I/O):
  - `test_digest_prompt_loads_successfully`.
  - `test_digest_prompt_includes_required_template_vars`.

- **`TestDigestLLMScope`** (~3, no I/O):
  - `test_llm_scopes_includes_digest`.
  - `test_resolve_digest_falls_back_to_global`.
  - `test_resolve_digest_uses_override_when_set`.

### 1.7 Self-review checklist (Commit 1)

- [ ] **Migration upgrade/downgrade** — `op.drop_table` в `downgrade()` идемпотентный.
- [ ] **Repo isolation** — `list_active` возвращает только `is_active=true`; нет N+1.
- [ ] **Cursor semantics** — strict `>` (не `>=`), иначе последний doc дубликатится на след. тике.
- [ ] **First-run window** — `last_digest_cursor is None` → `from_date = now - lookback_hours`, после генерации `cursor = now` даже при пустом результате (избегаем повторной 24h-выборки).
- [ ] **`max_docs_per_run` cap** — применяется per channel, не глобально (иначе один шумный канал съедает квоту).
- [ ] **LLM scope** — `set_llm_config(scope="digest")` валидируется; `LLM_SCOPES` обновлён.
- [ ] **Prompt YAML** — валидный по структуре `system.prompt` / `user.template` / `model.*`.

### 1.8 Commit 1 message

```
feat(f6): add digest_subscriptions schema, repo, DigestService, and 'digest' LLM stage
```

---

## Коммит 2 — Scheduler integration, Bot push, Bot+MCP tools, docs

### 2.1 Scheduler

- `tg_parser/services/background_scheduler.py` — `add_cron_task(name, func, cron_expression, timezone, ...)` через `apscheduler.triggers.cron.CronTrigger.from_crontab(cron_expression, timezone=ZoneInfo(timezone))`.
- Helpers на singleton: `register_digest_subscription(sub)`, `unregister_digest_subscription(sub_id)`, `reschedule_digest_subscription(sub)` — для динамических обновлений.
- `tg_parser/services/scheduler_service.py` — `run_scheduled_digests_task(subscription_id)` (resolve sub → DigestService.run_for_subscription → handle errors).
- На старте бота (см. §2.2): `repo.list_active()` → `scheduler.register_digest_subscription(sub)` для каждой.

### 2.2 Bot runtime + push

- Новый файл `tg_parser/bot/runtime.py`:

  ```python
  _bot: Bot | None = None

  def set_bot(bot: Bot) -> None: ...
  def get_bot() -> Bot | None: ...
  def clear_bot() -> None: ...
  ```

- `tg_parser/bot/main.py::run_bot` — после `Bot(...)` вызвать `set_bot(bot)`; на shutdown — `clear_bot()`. Если `settings.digest_scheduler_enabled and settings.scheduler_enabled` — запустить scheduler в bot-процессе и зарегистрировать активные подписки.
- `DigestService.deliver` использует `get_bot()` внутри (или принимает `Bot` явно через DI — тоньше для тестов; **выбираем DI** — `run_for_subscription(sub, bot=get_bot())` зовёт scheduler-task).
- **Markdown:** `bot.send_message(chat_id, body_markdown, parse_mode=ParseMode.MARKDOWN_V2)` — body предварительно прогоняется через `aiogram.utils.markdown.escape_md` для безопасности (избегаем `_` / `*` краша).
- **Длинные сообщения:** Telegram лимит 4096 символов. Разбивать на части `_split_for_telegram(text)`; если > 10 частей — сохранять полный текст в файл и отправлять `FSInputFile` (паттерн F2 size-gate).

### 2.3 Bot tools

- `tg_parser/bot/tools.py` — добавить три declarations + executors (см. §"Bot tools").
- `_TOOLS_NEEDING_BOT_CONTEXT |= {"subscribe_digest"}` — нужен `chat_id`.
- `_TOOL_EXECUTORS` — зарегистрировать `_exec_subscribe_digest`, `_exec_list_digests`, `_exec_unsubscribe_digest`.
- При успешном `subscribe_digest` — синхронно вызвать `scheduler.register_digest_subscription(sub)` (либо отложенно через event-bus, но для простоты — прямой вызов в bot-процессе).

### 2.4 MCP tools

- `tg_parser/mcp_server.py` — три `@mcp.tool()` + Pydantic Result-модели.
- Channel ownership: `for cid in channel_ids: await assert_channel_access(user, cid)`.
- При создании подписки через MCP в API-процессе → нужно межпроцессное уведомление scheduler'а в bot-процессе. **Решение:** scheduler в bot-процессе при старте регистрирует **все** active подписки; для динамических добавлений между перезапусками — каждые N секунд (`settings.digest_refresh_interval`, default 60s) bot-scheduler делает `repo.list_active()` и реконсилирует свои job'ы (paint/diff). Это упрощает логику без необходимости IPC.

### 2.5 Документация

- [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md) — новый раздел **"Scheduled Digests (F6)"**:
  - Что это и зачем.
  - Как создать подписку через бот ("/start", команда естественным языком "подпишись на дайджест по @durov каждое утро в 9").
  - Cron expression cheat sheet (5 фрагментов).
  - Поддерживаемые форматы (`summary` / `bullets` / `detailed`).
  - Где настраивается LLM (`DIGEST_LLM_PROVIDER`, `set_llm_config(scope="digest")`).
- [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md) — секция "Digests" в Tools by Category + три tool-schema + workflow "Subscribe → poll list → unsubscribe".
- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) — `DIGEST_SCHEDULER_ENABLED`, `DIGEST_DEFAULT_TIMEZONE`, `DIGEST_MAX_DOCS_PER_RUN`, `DIGEST_FIRST_RUN_LOOKBACK_HOURS`, `DIGEST_LLM_PROVIDER`, `DIGEST_LLM_MODEL`, `DIGEST_REFRESH_INTERVAL`.
- [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F6" — отметить ✅ DONE + ссылка на PR.

### 2.6 Тесты Коммита 2

В `tests/test_f6_scheduled_digests.py` добавить:

- **`TestSchedulerCronIntegration`** (~3, in-process scheduler):
  - `test_add_cron_task_registers_with_correct_trigger`.
  - `test_register_digest_subscription_creates_job`.
  - `test_unregister_removes_job`.

- **`TestDigestDelivery`** (~4, mocked aiogram `Bot`):
  - `test_deliver_calls_send_message_with_markdown`.
  - `test_deliver_splits_long_messages`.
  - `test_deliver_skipped_when_no_new_docs`.
  - `test_deliver_no_bot_logs_warning_and_skips_cursor_update`.

- **`TestBotDigestTools`** (~5):
  - `test_subscribe_digest_creates_persisted_subscription`.
  - `test_subscribe_digest_validates_cron_expression`.
  - `test_subscribe_digest_validates_timezone`.
  - `test_list_digests_returns_only_owned_for_non_admin`.
  - `test_unsubscribe_digest_ownership_enforced`.

- **`TestMCPDigestTools`** (~5):
  - `test_mcp_subscribe_digest_returns_subscription_id`.
  - `test_mcp_subscribe_digest_validates_cron`.
  - `test_mcp_subscribe_digest_channel_ownership_enforced`.
  - `test_mcp_list_digests_admin_sees_all`.
  - `test_mcp_unsubscribe_digest_returns_404_for_unknown_id`.

- **`TestSchedulerReconciliation`** (~2):
  - `test_reconciliation_adds_new_subscriptions_without_restart`.
  - `test_reconciliation_removes_deleted_subscriptions`.

### 2.7 Self-review checklist (Commit 2)

- [ ] **Single-process delivery** — scheduler digest-task активен только в bot-процессе (`settings.digest_scheduler_enabled`); API/CLI daemon не отправляют дайджесты дважды.
- [ ] **Bot runtime singleton** — `set_bot` идемпотентен; `clear_bot` на shutdown; тест что `get_bot()` возвращает None если бот не запущен.
- [ ] **Markdown escape** — `_` / `*` / `[` в названиях каналов и summary-тексте не крашат `parse_mode=MARKDOWN_V2`.
- [ ] **Длинные сообщения** — split до 4096; > N частей → файл (как F2 size-gate).
- [ ] **Cron validation** — `CronTrigger.from_crontab(expr)` ловит invalid; bot/MCP tool возвращают понятную ошибку (НЕ 500).
- [ ] **Timezone validation** — `ZoneInfo(tz)` с try/except → понятная ошибка.
- [ ] **Channel ownership** — для каждого `channel_id` в подписке проверяем `assert_channel_access`; не-владелец получает rejected (тест на mixed-ownership list).
- [ ] **Reconciliation race** — параллельный create/delete + reconciliation не теряет job'ы (тест с двумя подписками + delete одной + reconciliation tick).
- [ ] **Empty digest** — НЕ отправляется сообщение, НО `last_sent_at` обновляется.
- [ ] **First-run** — пустой первый запуск → `last_digest_cursor = now`, не повторяет lookback.
- [ ] **Idempotency on cursor failure** — если `bot.send_message` падает (network), cursor НЕ обновляется → следующий тик повторит.

### 2.8 Commit 2 message

```
feat(f6): add digest scheduler, bot delivery, bot+MCP tools with documentation
```

---

## Порядок работы

1. **Plan mode first** — свериться с актуальным `main` (после мёрджа PR #10): актуальные lines в `background_scheduler.py`, `tools.py` (`TOOL_DECLARATIONS` в результате F2 имеет 25 элементов), `mcp_server.py` (26 tools), `settings.py` (`LLM_SCOPES`).
2. **Ветка** `feat/f6-scheduled-digests` от актуального `main` (после мёрджа PR #10).
3. **Коммит 1 — имплементация:**
   - Migration `digest_subscriptions`.
   - `DigestSubscription` domain + `DigestSubscriptionRepo` port + `SADigestSubscriptionRepo`.
   - `DigestService` + `DigestResult`.
   - `prompts/digest.yaml`.
   - `digest_*` settings + `LLM_SCOPES` extension.
   - Тесты `TestDigestSubscriptionRepo`, `TestDigestService`, `TestDigestPromptLoader`, `TestDigestLLMScope`.
4. **Коммит 1 — local gate (первый прогон):**
   ```bash
   .venv/bin/pytest tests/test_f6_scheduled_digests.py -x -q
   TEST_POSTGRES=1 .venv/bin/pytest \
     tests/test_f6_scheduled_digests.py \
     tests/test_storage_integration.py \
     tests/test_rag_prompt_config.py -x -q
   ```
5. **Коммит 1 — self-review loop (обязателен перед commit):**
   - Чек-лист §1.7.
   - Если пробел — добавить тест/правку в том же коммите.
6. **Коммит 1 — re-run gate + full regression:**
   ```bash
   .venv/bin/alembic upgrade head    # применить миграцию локально
   TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
   ```
   Ожидаемо ≥1561 passed (1536 baseline + ~25 новых в Commit 1). Если меньше — разобраться **до** коммита.
7. **Коммит 1 — commit** с указанным message.
8. **Коммит 2 — имплементация:**
   - `BackgroundScheduler.add_cron_task` + helpers `register/unregister/reschedule`.
   - `tg_parser/bot/runtime.py` + интеграция в `bot/main.py`.
   - `run_scheduled_digests_task` + reconciliation loop.
   - Bot tools (3) + MCP tools (3).
   - Docs: USER_GUIDE, MCP_AGENT_GUIDE, ENV_VARIABLES_GUIDE, FUTURE_FEATURES (F6 DONE).
   - Тесты `TestSchedulerCronIntegration`, `TestDigestDelivery`, `TestBotDigestTools`, `TestMCPDigestTools`, `TestSchedulerReconciliation`.
9. **Коммит 2 — local gate (первый прогон):**
   ```bash
   .venv/bin/pytest tests/test_f6_scheduled_digests.py -x -q
   .venv/bin/pytest tests/test_mcp*.py tests/test_bot*.py tests/test_scheduler*.py -x -q
   ```
10. **Коммит 2 — self-review loop (обязателен перед commit):**
    - Чек-лист §2.7.
    - Если пробел — добавить тест/правку в том же коммите.
11. **Коммит 2 — re-run gate + full regression:**
    ```bash
    TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
    ```
    Ожидаемо ≥1580 passed (1536 baseline + ~25 + ~19). Если меньше — разобраться.
12. **Коммит 2 — commit** с указанным message.
13. **PR** против `main` → CI green → rebase-and-merge (паттерн F2/F5-A Phase 3).

---

## Критерии готовности

1. Таблица `digest_subscriptions` создана через Alembic-миграцию в `ingestion` DB; `upgrade`/`downgrade` идемпотентны.
2. `DigestSubscription` domain + `DigestSubscriptionRepo` port + SQLAlchemy реализация; CRUD + `list_active` + `list_by_owner`.
3. `DigestService.generate` — strict-`>` cursor, lookback на первом запуске, cap `max_docs_per_run` per channel, skipped-флаг для пустого результата.
4. `prompts/digest.yaml` загружается через `PromptLoader.load("digest")`; `reload_prompts(name="digest")` работает без правок.
5. LLM stage `digest` — `LLM_SCOPES` расширен; env vars `DIGEST_LLM_PROVIDER` / `DIGEST_LLM_MODEL`; runtime-переключение через `set_llm_config(scope="digest", ...)`.
6. `BackgroundScheduler.add_cron_task` через `CronTrigger.from_crontab(expr, timezone=ZoneInfo(tz))`; helpers `register_digest_subscription` / `unregister` / `reschedule`.
7. `tg_parser/bot/runtime.py` — singleton bot для background-доставки; интеграция в `bot/main.py::run_bot`.
8. Доставка через `Bot.send_message` с `MARKDOWN_V2`; escape специальных символов; split по 4096 символов; > N частей → file (паттерн F2).
9. Bot-tools `subscribe_digest`, `list_digests`, `unsubscribe_digest` (`subscribe_digest` ∈ `_TOOLS_NEEDING_BOT_CONTEXT`).
10. MCP-tools `subscribe_digest`, `list_digests`, `unsubscribe_digest` с ownership на channels (`assert_channel_access`) и subscriptions (`owner_id`).
11. Reconciliation loop в bot-scheduler — динамические create/delete без рестарта.
12. Документация: USER_GUIDE (F6 section), MCP_AGENT_GUIDE (Digests + workflow), ENV_VARIABLES_GUIDE (7 новых vars), FUTURE_FEATURES (F6 DONE).
13. `tests/test_f6_scheduled_digests.py` — ~30+ тестов; все проходят.
14. `TEST_POSTGRES=1 pytest tests/ -x -q` — ≥1580 passed; существующие scheduler/bot/mcp/storage тесты не регрессируют.
15. **Self-review loop выполнен перед каждым коммитом** (шаги 5 и 10 в §"Порядок работы").
16. Два коммита с указанными messages; PR с green CI.

---

## Что НЕ входит в scope F6

- **Workspaces / per-group digests** — требует F4-B (Workspaces), отложено. F6 работает на уровне `channel_ids[]`.
- **Per-topic digest** ("только новое по теме X") — требует topic-filtering на уровне ProcessedDocument (F5-A topic-cards уже есть, но интеграция в `list_by_channel` отдельная задача).
- **Digest history / archive** — отправленные дайджесты НЕ сохраняются в БД (только `last_sent_at` timestamp). При желании просмотра — пользователь скроллит чат.
- **Email/webhook delivery** — только Telegram-чат через aiogram bot. Email/webhook — отдельная фича по запросу.
- **Smart scheduling** ("если контента мало — отложить") — `skipped=True` достаточно для MVP; адаптивное расписание — out of scope.
- **Per-source `poll_interval_seconds` enforcement в scheduler** — упомянуто в FUTURE_FEATURES шаг 8, но это **отдельная задача** (затрагивает ingestion scheduler, не digest scheduler). Откладываем — оставим в F6 design-doc как known gap.
- **Migration auto-run в CI** — миграция применяется в test-fixture / dev-environment вручную через `alembic upgrade head`. Production migration runner — отдельная инфраструктурная задача.
- **F1 (Configurable Prompts in DB):** digest prompt храним в `prompts/digest.yaml`, не в БД (как все остальные prompts на момент F6).
- **Heartbeat empty digest** — опция "слать сообщение даже если новых нет" (e.g. "за сегодня новостей нет, всё спокойно") — не входит, можно добавить флагом `notify_when_empty BOOLEAN` в Phase 2.

---

## Риски и митигация

| Риск | Митигация |
|---|---|
| Двойная отправка из разных процессов (API + bot daemon оба запускают scheduler) | `settings.digest_scheduler_enabled` дефолт `True` в bot-процессе, рекомендация в docs выключить в API/CLI |
| `bot.send_message` падает (network/Telegram down) → cursor обновлён → сообщения потеряны | Cursor обновляется **только после успешного `send_message`** (или `skipped=True`); fail в delivery → НЕ обновлять cursor → следующий тик повторит |
| Markdown escape для русского текста + emoji + URL — крашит `MARKDOWN_V2` | `aiogram.utils.markdown.escape_md` + интеграционные тесты с реальными Markdown corner-cases (`_`, `*`, `[`, `]`, `(`, `)`) |
| Cron expression от пользователя — DoS-вектор (`* * * * *` каждую секунду = шторм запросов к LLM) | Минимальный интервал = 5 минут; валидация в bot/MCP tool отвергает `*` в minute-position |
| Reconciliation race — параллельный delete + reconcile может оставить orphan job или удалить только что добавленный | Reconciliation использует diff на основе `set` of IDs из БД; идемпотентен; тест с конкурентными операциями |
| Длинные дайджесты > 4096 символов → split на много частей засоряет чат | > 10 частей → отправляется файл `digest_{date}.md` (паттерн F2 size-gate) |
| Подписка на канал, который потом удалён через `remove_channel` | На каждом тике перед summarize проверяем `assert_channel_access(owner, cid)` ; если канал недоступен — skip + log warning + НЕ удалять подписку (channel может быть восстановлен) |
| LLM-стоимость на больших корпусах (50+ docs × N подписок × N тиков/день) | `DIGEST_MAX_DOCS_PER_RUN=50` per channel; в шаблоне просим summary, не дословный пересказ; `DIGEST_LLM_MODEL` можно выставить на cheap model (e.g. `gemini-2.5-flash`) |
| Scheduler в API-процессе и в bot-процессе оба регистрируют один digest-job | Только bot-процесс регистрирует digest-jobs (см. §2.1); API-scheduler оставляем для incremental ingestion |
| Зависимость от F4 (`users.id` FK для `owner_id`) | F4 уже мёрджнут; FK на `users.id` UUID работает |
| Backward-compat существующего scheduler-кода | `add_cron_task` — **новый** метод; `add_task` (interval) не трогаем; тесты `TestBackgroundScheduler` не должны регрессировать |
| Передача `chat_id` в MCP-tool (нет message-context) | MCP `subscribe_digest` принимает `chat_id` как обязательный параметр; в docs указываем что для private chat = `telegram_user_id`, для group — отрицательное число |
| Reconciliation tick раз в 60 сек = задержка применения новой подписки до 60s | Bot-tool `subscribe_digest` синхронно вызывает `scheduler.register_digest_subscription` — мгновенная регистрация в bot-процессе. Reconciliation покрывает MCP-create + cross-process changes |

---

## Связанные документы

- [`../notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F6: Scheduled Digests" — исходный design-doc.
- [`../notes/ROADMAP_V3_PRODUCTION_FIRST.md`](../notes/ROADMAP_V3_PRODUCTION_FIRST.md) §"Пост-F5-A Phase 3 — утверждённая последовательность" — место F6 в roadmap'е (шаг 3 после F2).
- [`F2_PARSE_ONLY_EXPORT_PLAN.md`](F2_PARSE_ONLY_EXPORT_PLAN.md) — эталон структуры plan-документа + F2-паттерны (bot context propagation, MCP/bot tool dual-channel, size-gate).
- [`F5A_PHASE3_IMPLEMENTATION_PLAN.md`](F5A_PHASE3_IMPLEMENTATION_PLAN.md) — пример работы с миграциями + repo-pattern.
- [`../prompts/F6_SCHEDULED_DIGESTS_PROMPT.md`](../prompts/F6_SCHEDULED_DIGESTS_PROMPT.md) — стартовый промпт.
- PR #10 ([`feat/f2-parse-only-export`](https://github.com/AlexEfimov/TG_parser/pull/10)) — prerequisite (ожидает мёрджа).
