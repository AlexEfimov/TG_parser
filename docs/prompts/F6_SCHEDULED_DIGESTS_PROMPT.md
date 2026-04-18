# F6 — Scheduled Digests Implementation — Стартовый промпт

**Версия проекта:** 4.7.0+ (после мёрджа F2 — PR #10, ветка `feat/f2-parse-only-export`)
**Ветка:** `feat/f6-scheduled-digests` (создать от обновлённого `main`)
**План реализации:** [`docs/plans/F6_SCHEDULED_DIGESTS_PLAN.md`](../plans/F6_SCHEDULED_DIGESTS_PLAN.md) — **читать первым**
**Design-doc:** [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F6: Scheduled Digests — автоматические сводки по расписанию"
**Roadmap:** [`docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`](../notes/ROADMAP_V3_PRODUCTION_FIRST.md) §"Пост-F5-A Phase 3 — утверждённая последовательность" (шаг 3 после F2)

---

## Цель

Дать пользователю возможность подписаться на **автоматические сводки** (digests) по выбранным каналам с доставкой в Telegram-чат по расписанию (cron). Дайджесты собираются из новых `ProcessedDocument`-ов с момента предыдущего запуска подписки, суммируются через LLM и отправляются как Markdown-сообщение(я) или файл, если длина превышает лимиты Telegram.

Реализуется **поверх** существующей инфраструктуры:

1. **APScheduler** уже работает (`tg_parser/services/background_scheduler.py` — `IntervalTrigger` для incremental ingestion). Добавляем `CronTrigger` через новый метод `BackgroundScheduler.add_cron_task(...)`.
2. **`ProcessedDocumentRepo.list_by_channel(from_date=..., to_date=...)`** уже фильтрует по `processed_at` — это и есть наш cursor-mechanism.
3. **Aiogram `Bot.send_message(chat_id, text)`** — для доставки. Bot-инстанс кладём в module-singleton `tg_parser/bot/runtime.py`, чтобы scheduler-task мог его получить.
4. **PromptLoader / per-stage LLM** — `prompts/digest.yaml` + `digest_llm_provider`/`digest_llm_model` settings + расширение `LLM_SCOPES` до `("global", "processing", "topicization", "rag", "digest")`.
5. **MCP-tools + Bot-tools** — `subscribe_digest`, `list_digests`, `unsubscribe_digest` в обоих каналах с одинаковой ownership-семантикой (паттерн F2 `export_channel`).

**Backward-compat:** F6 не меняет существующий API/CLI/scheduler. `BackgroundScheduler.add_task` (interval) остаётся как есть; `add_cron_task` — новый метод. Существующие тесты scheduler/bot/MCP не должны регрессировать.

---

## Коротко об архитектуре

```
                  CronTrigger ("0 9 * * *", tz=Europe/Moscow)
                                │
                                ▼
                  ┌───────────────────────────┐
                  │  BackgroundScheduler      │
                  │  (singleton in bot proc)  │
                  └────────────┬──────────────┘
                               │ tick per subscription
                               ▼
                  ┌───────────────────────────┐
                  │  run_scheduled_digests_task(sub_id)
                  │  1. Repo.get(sub_id)
                  │  2. DigestService.generate(sub)
                  │     ├─ ProcessedDocRepo.list_by_channel(processed_at > last_cursor)
                  │     ├─ cap to DIGEST_MAX_DOCS_PER_RUN per channel
                  │     ├─ LLM (scope=digest, prompt=prompts/digest.yaml)
                  │     └─ format Markdown grouped by channel
                  │  3. DigestService.deliver(bot, result)
                  │     ├─ split if > 4096 chars
                  │     ├─ if too many parts → FSInputFile
                  │     └─ Bot.send_message(chat_id, ParseMode.MARKDOWN_V2)
                  │  4. Repo.update(last_digest_cursor=max(processed_at), last_sent_at=now)
                  └───────────────────────────┘

Management:
  bot tools: subscribe_digest / list_digests / unsubscribe_digest
  mcp tools: same triple
  → DigestSubscriptionRepo (ingestion DB)
  → scheduler.register_digest_subscription(sub) (synchronous in bot proc)
  → reconciliation tick every DIGEST_REFRESH_INTERVAL (60s) for cross-process changes
```

**Где digest активен:** только в bot-процессе (`settings.digest_scheduler_enabled`, default `True`). API/CLI scheduler НЕ запускают digest-task — иначе двойная отправка.

---

## Ключевые уточнения (после разведки)

- [`tg_parser/services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py) — обёртка над `AsyncIOScheduler`; `add_task` (lines 47–95) использует только `IntervalTrigger`. **`CronTrigger` нигде не используется**. Singleton через `get_scheduler()` (173–178). `setup_default_tasks()` (260–318) — пример регистрации существующих job'ов.
- [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) — `incremental_pipeline_task` (337–353); CLI daemon `run_scheduler_blocking` (275–329) создаёт **новый** scheduler (НЕ singleton). `Source.poll_interval_seconds` хранится, но scheduler-тик глобальный (251–260) — это известный gap, F6 его НЕ исправляет.
- [`tg_parser/api/main.py`](../../tg_parser/api/main.py) lines 157–184 — lifespan стартует scheduler в API-процессе. **Для F6:** в API-процессе digest-task НЕ регистрируется (флаг `digest_scheduler_enabled` или явный гейт в `setup_default_tasks`).
- [`tg_parser/bot/main.py`](../../tg_parser/bot/main.py) lines 151–154 — `Bot(token=...)` создаётся в `run_bot()`. **Для F6:** после создания вызвать `tg_parser.bot.runtime.set_bot(bot)` + если digest enabled, `get_scheduler().start()` + регистрация активных подписок.
- [`tg_parser/bot/handlers.py`](../../tg_parser/bot/handlers.py) lines 143–148 — `agent.process_message(..., bot=message.bot, chat_id=message.chat.id)` — паттерн F2; используем тот же путь для bot-tools.
- [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py) — `TOOL_DECLARATIONS` (line 39+, после F2 — 25 элементов), `_TOOL_EXECUTORS` (1885–1908), `_TOOLS_NEEDING_BOT_CONTEXT = {"export_channel"}` (26–27). После F6 — 28 declarations, `_TOOLS_NEEDING_BOT_CONTEXT |= {"subscribe_digest"}`.
- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) lines 411–417 — `ProcessedDocumentRepo.list_by_channel(channel_id, from_date?, to_date?)`. Реализация ([`processed_document_repo.py`](../../tg_parser/storage/sqlalchemy/processed_document_repo.py) 169–196) фильтрует по **`processed_at`** — это наш cursor.
- [`tg_parser/processing/prompt_loader.py`](../../tg_parser/processing/prompt_loader.py) lines 17–78 — `PromptLoader.load(name)` грузит `{name}.yaml`. Дефолтный dir `Path("prompts")`. Reload через MCP `reload_prompts(name="digest")` работает без правок.
- [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py):
  - lines 138–144 — `processing_llm_provider/_model`, `topicization_*`, `rag_*`. Добавляем `digest_llm_provider/_model`.
  - line 657 — `LLM_SCOPES = ("global", "processing", "topicization", "rag")`. Расширяем `+ "digest"`.
  - lines 757–778 — `LLMConfigManager.resolve(stage)` использует `getattr(self._static, f"{stage}_llm_provider", None)` — `"digest"` будет работать сразу после добавления fields.
  - lines 417–446 — `scheduler_*` блок; рядом добавляем `digest_*` settings.
- [`migrations/env.py`](../../migrations/env.py) lines 96–123 — multi-DB Alembic. `digest_subscriptions` живёт в **`ingestion`** DB (там же где `users`, `sources.owner_id`).
- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — паттерн `@mcp.tool() async def foo(..., ctx: Context | None = None)` + `current_user = await resolve_mcp_user(ctx.client_id if ctx else None)`. Ownership: для каналов `assert_channel_access(user, cid)`; для прочих сущностей `if not user.is_admin and entity.owner_id != user.id: raise ...`.
- **Telegram `Bot.send_message` лимит:** 4096 символов на сообщение. Длинные дайджесты разбиваем; > 10 частей → `FSInputFile` с .md (паттерн F2 size-gate, но 50 MB здесь не критично — limit по частям).
- **Markdown V2 escape:** обязателен через `aiogram.utils.markdown.escape_md` для названий каналов и summary-текста (могут содержать `_`, `*`, `[`, `]`, `(`, `)`, `~`, `\``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`).
- **Cron security:** валидация в bot/MCP-tool — отвергаем `* * * * *` в minute-position (минимальный интервал — каждые 5 минут). Иначе DoS-вектор.
- **First-run lookback:** `last_digest_cursor is None` → берём docs за последние `digest_first_run_lookback_hours` (default 24h). После генерации `cursor = now()` даже при пустом результате — иначе на каждом тике повторим 24h-выборку.
- **Cursor-update только при успехе:** если `bot.send_message` падает — НЕ обновлять `last_digest_cursor` → следующий тик повторит. Иначе сообщения теряются молча.
- **Reconciliation вместо IPC:** в bot-процессе раз в `digest_refresh_interval` (default 60s) reconciliation-loop делает `repo.list_active()` и diff-ит с зарегистрированными scheduler job'ами. MCP-create в API-процессе → bot-процесс подхватит подписку максимум через 60s.

---

## Структура работы (2 коммита)

### Коммит 1 — Schema, Repo, Service, LLM stage, prompts

**Файлы:**

- `migrations/versions/ingestion/<timestamp>_add_digest_subscriptions.py` (new):
  - `op.create_table('digest_subscriptions', ...)` со всеми полями (см. `F6_SCHEDULED_DIGESTS_PLAN.md` §"DB schema").
  - Два индекса: `idx_digest_subscriptions_owner_active`, `idx_digest_subscriptions_active_cron` (partial index `WHERE is_active = true`).
  - `downgrade()` — `op.drop_table('digest_subscriptions')`.

- [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py):
  - `DigestFormat(StrEnum)` — `SUMMARY | BULLETS | DETAILED`.
  - `DigestSubscription(BaseModel)` — id, owner_id, chat_id, name, channel_ids, cron_expression, timezone, format, language, is_active, last_sent_at, last_digest_cursor, created_at, updated_at.

- [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py):
  - `class DigestSubscriptionRepo(Protocol)` — `create`, `get`, `update` (partial fields), `delete`, `list_by_owner(owner_id)`, `list_active()`.

- `tg_parser/storage/sqlalchemy/models.py`:
  - `DigestSubscriptionORM` — SQLAlchemy ORM-модель.

- `tg_parser/storage/sqlalchemy/digest_subscription_repo.py` (new):
  - `class SADigestSubscriptionRepo(DigestSubscriptionRepo)` — реализация всех методов.

- `tg_parser/services/digest_service.py` (new):
  - `@dataclass class DigestResult` — subscription_id, chat_id, title, body_markdown, docs_count, new_cursor, skipped.
  - `class DigestService` — `__init__(processed_repo, ingestion_repo, prompt_loader, llm_factory, max_docs_per_run, first_run_lookback_hours)`.
  - `async def generate(sub) -> DigestResult` — strict-`>` cursor; first-run lookback; cap per channel; LLM via `resolve_llm_config("digest")` + `prompt_loader.load("digest")`.
  - `async def deliver(bot, result) -> None` — split + escape + `send_message` / `send_document`.
  - `async def run_for_subscription(sub, bot) -> DigestResult` — generate → deliver → cursor update **только при успехе**.

- `prompts/digest.yaml` (new) — system + user template + model settings (см. `F6_SCHEDULED_DIGESTS_PLAN.md` §"Prompt template").

- [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py):
  - Добавить fields: `digest_scheduler_enabled`, `digest_default_timezone`, `digest_max_docs_per_run`, `digest_first_run_lookback_hours`, `digest_refresh_interval`, `digest_llm_provider`, `digest_llm_model`.
  - Расширить `LLM_SCOPES = ("global", "processing", "topicization", "rag", "digest")`.

- Новый файл `tests/test_f6_scheduled_digests.py` с классами (Commit 1 — ~16 тестов):
  - `TestDigestSubscriptionRepo` (~6, Postgres) — create/get/update/delete + list_by_owner + list_active.
  - `TestDigestService` (~5, Postgres + LLM mock) — empty/skipped, first-run lookback, cap per channel, cursor=max(processed_at), grouped-by-channel в prompt.
  - `TestDigestPromptLoader` (~2, no I/O) — loads + required template vars.
  - `TestDigestLLMScope` (~3, no I/O) — `LLM_SCOPES` includes digest, fallback to global, override applied.

**Commit message:**
```
feat(f6): add digest_subscriptions schema, repo, DigestService, and 'digest' LLM stage
```

---

### Коммит 2 — Scheduler integration, Bot push, Bot+MCP tools, docs

**Файлы:**

- [`tg_parser/services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py):
  - `add_cron_task(name, func, cron_expression, timezone="UTC", args=(), kwargs=None) -> Job` — обёртка над `CronTrigger.from_crontab(expr, timezone=ZoneInfo(timezone))`.
  - `register_digest_subscription(sub)`, `unregister_digest_subscription(sub_id)`, `reschedule_digest_subscription(sub)` — helpers на singleton.

- [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py):
  - `async def run_scheduled_digests_task(subscription_id: str)` — resolve sub → DigestService.run_for_subscription(sub, bot=get_bot()).

- `tg_parser/bot/runtime.py` (new):
  - `_bot: Bot | None = None`; `set_bot(bot)`, `get_bot()`, `clear_bot()`.

- [`tg_parser/bot/main.py`](../../tg_parser/bot/main.py):
  - В `run_bot()` после `Bot(...)` → `set_bot(bot)`; если `settings.digest_scheduler_enabled and settings.scheduler_enabled` — старт scheduler + `for sub in repo.list_active(): scheduler.register_digest_subscription(sub)`. Старт reconciliation-loop как `add_task` с `IntervalTrigger(seconds=settings.digest_refresh_interval)`.
  - На shutdown — `clear_bot()` + `scheduler.shutdown(wait=True)`.

- [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py):
  - 3 новых declarations в `TOOL_DECLARATIONS`: `subscribe_digest`, `list_digests`, `unsubscribe_digest`.
  - `_TOOLS_NEEDING_BOT_CONTEXT |= {"subscribe_digest"}`.
  - Executors `_exec_subscribe_digest(name, channel_ids, cron_expression="0 9 * * *", timezone="UTC", format="summary", language="ru", *, current_user, bot, chat_id)`, `_exec_list_digests(*, current_user)`, `_exec_unsubscribe_digest(subscription_id, *, current_user)`.
  - При успешном subscribe — синхронно `scheduler.register_digest_subscription(sub)`.

- [`tg_parser/bot/agent.py`](../../tg_parser/bot/agent.py):
  - Если `_TOOLS_NEEDING_BOT_CONTEXT` содержит больше одного имени, убедиться что `process_message` правильно прокидывает `bot`/`chat_id` (после F2 это уже работает).

- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py):
  - 3 новых `@mcp.tool()`: `subscribe_digest(name, channel_ids, chat_id, cron_expression, timezone, format, language, ctx)`, `list_digests(ctx)`, `unsubscribe_digest(subscription_id, ctx)`.
  - Pydantic Result-модели: `SubscribeDigestResult`, `ListDigestsResult` (subscriptions: list[DigestSubscriptionItem]), `UnsubscribeDigestResult`.
  - Channel ownership через `for cid in channel_ids: await assert_channel_access(user, cid)`.

- [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md) — новый раздел "Scheduled Digests (F6)": что это, как создать через бот, cron cheat sheet, форматы, LLM конфигурация.

- [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md):
  - Новая секция "Digests" в Tools by Category (3 tools).
  - Tool schemas для `subscribe_digest`, `list_digests`, `unsubscribe_digest`.
  - Workflow в Common Workflows: "Subscribe → list → unsubscribe".
  - Версия 4.4 → 4.5; tools 26 → 29.

- [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md):
  - 7 новых vars: `DIGEST_SCHEDULER_ENABLED`, `DIGEST_DEFAULT_TIMEZONE`, `DIGEST_MAX_DOCS_PER_RUN`, `DIGEST_FIRST_RUN_LOOKBACK_HOURS`, `DIGEST_REFRESH_INTERVAL`, `DIGEST_LLM_PROVIDER`, `DIGEST_LLM_MODEL`.

- [`docs/notes/FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md) §"F6" — отметить ✅ DONE + ссылка на PR.

- `tests/test_f6_scheduled_digests.py` — дополнить (Commit 2 — ~19 тестов):
  - `TestSchedulerCronIntegration` (~3) — `add_cron_task` registers correctly, `register_digest_subscription` создаёт job, unregister удаляет.
  - `TestDigestDelivery` (~4, mocked Bot) — `send_message` с MARKDOWN_V2, split длинных сообщений, skipped → no send, no-bot → log warning + skip cursor.
  - `TestBotDigestTools` (~5) — subscribe persists, cron validation, timezone validation, list ownership, unsubscribe ownership.
  - `TestMCPDigestTools` (~5) — subscribe returns id, cron validation, channel ownership, list admin sees all, unsubscribe 404.
  - `TestSchedulerReconciliation` (~2) — adds new without restart, removes deleted.

**Commit message:**
```
feat(f6): add digest scheduler, bot delivery, bot+MCP tools with documentation
```

---

## DB schema шпаргалка

```sql
CREATE TABLE digest_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    name VARCHAR(200) NOT NULL,
    channel_ids TEXT[] NOT NULL CHECK (array_length(channel_ids, 1) >= 1),
    cron_expression VARCHAR(100) NOT NULL DEFAULT '0 9 * * *',
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    format VARCHAR(20) NOT NULL DEFAULT 'summary',
    language VARCHAR(10) NOT NULL DEFAULT 'ru',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_sent_at TIMESTAMPTZ,
    last_digest_cursor TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_digest_subscriptions_owner_active ON digest_subscriptions(owner_id, is_active);
CREATE INDEX idx_digest_subscriptions_active_cron ON digest_subscriptions(is_active) WHERE is_active = true;
```

---

## Ключевые тест-кейсы

### `TestDigestSubscriptionRepo` (Postgres)
- `test_create_returns_uuid_and_persists`.
- `test_get_returns_none_for_unknown_id`.
- `test_update_partial_fields_preserves_others`.
- `test_delete_returns_true_then_false`.
- `test_list_by_owner_filters_correctly`.
- `test_list_active_excludes_paused`.

### `TestDigestService` (Postgres + LLM mock)
- `test_generate_empty_when_no_new_docs_returns_skipped`.
- `test_generate_first_run_uses_lookback_window`.
- `test_generate_caps_docs_at_max_per_run` — на 100 docs возвращается ≤ 50 в LLM-prompt.
- `test_generate_updates_cursor_to_max_processed_at`.
- `test_generate_groups_by_channel_in_prompt`.

### `TestDigestPromptLoader`
- `test_digest_prompt_loads_successfully`.
- `test_digest_prompt_includes_required_template_vars` — `{{ format }}`, `{{ language }}`, `{{ channels }}`.

### `TestDigestLLMScope`
- `test_llm_scopes_includes_digest`.
- `test_resolve_digest_falls_back_to_global`.
- `test_resolve_digest_uses_override_when_set`.

### `TestSchedulerCronIntegration`
- `test_add_cron_task_registers_with_correct_trigger` — assert `job.trigger.fields` соответствуют expression.
- `test_register_digest_subscription_creates_job` — singleton scheduler регистрирует с правильным id.
- `test_unregister_removes_job`.

### `TestDigestDelivery` (mocked Bot)
- `test_deliver_calls_send_message_with_markdown` — `parse_mode=ParseMode.MARKDOWN_V2`.
- `test_deliver_splits_long_messages` — на 5000-char body вызывается ≥ 2 раза `send_message`.
- `test_deliver_skipped_when_no_new_docs` — НЕТ `send_message`, но `last_sent_at` обновлён.
- `test_deliver_no_bot_logs_warning_and_skips_cursor_update` — `get_bot()` returns None → cursor НЕ меняется.

### `TestBotDigestTools`
- `test_subscribe_digest_creates_persisted_subscription`.
- `test_subscribe_digest_validates_cron_expression` — `* * * * *` отвергается с понятной ошибкой.
- `test_subscribe_digest_validates_timezone` — `Europe/Atlantis` отвергается.
- `test_list_digests_returns_only_owned_for_non_admin`.
- `test_unsubscribe_digest_ownership_enforced` — non-owner получает rejected.

### `TestMCPDigestTools`
- `test_mcp_subscribe_digest_returns_subscription_id`.
- `test_mcp_subscribe_digest_validates_cron`.
- `test_mcp_subscribe_digest_channel_ownership_enforced` — channel_id чужого канала → rejected.
- `test_mcp_list_digests_admin_sees_all` — admin видит чужие подписки.
- `test_mcp_unsubscribe_digest_returns_404_for_unknown_id`.

### `TestSchedulerReconciliation`
- `test_reconciliation_adds_new_subscriptions_without_restart` — создаём подписку через repo напрямую → reconcile → scheduler имеет новый job.
- `test_reconciliation_removes_deleted_subscriptions`.

**Запуск:**
```bash
.venv/bin/pytest tests/test_f6_scheduled_digests.py -x -q

TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

**Ожидаемо:** 1536 → ~1561 после Commit 1, ~1580 после Commit 2 (+~44 теста суммарно).

---

## Существующие тесты — риски

- `tests/test_scheduler_service.py`, `tests/test_phase3d_advanced.py::TestBackgroundScheduler`, `tests/test_f8a_hardening.py` — могут зависеть от точной формы `BackgroundScheduler.add_task` / job-listing. `add_cron_task` — новый метод, не должен ломать существующие, но проверить.
- `tests/test_bot_tools_v11.py` / `tests/test_bot_tools_v12.py` — фиксируют `len(TOOL_DECLARATIONS)` (после F2 = 25). После F6 = 28 — обновить assertions.
- `tests/test_mcp*.py` — могут содержать tool-listing assertions. Проверить.
- `tests/test_storage_integration.py` — добавляется новая таблица; изоляция через scoped fixture важна.
- `tests/test_rag_prompt_config.py` — `LLM_SCOPES` изменился; проверить тесты что итерируют scope-tuple.
- `tests/conftest.py::postgres_settings` — фикстура должна применить новую миграцию (`alembic upgrade head`) перед тестами; проверить что это уже происходит автоматически.

**Стратегия:** пробежать `pytest tests/test_scheduler*.py tests/test_bot*.py tests/test_mcp*.py tests/test_storage*.py tests/test_rag*.py -x -q` до и после правок; ломающиеся — чинить в том же коммите.

---

## Критерии готовности

1. Migration `add_digest_subscriptions` в `ingestion` DB; upgrade/downgrade идемпотентны.
2. `DigestSubscription` domain + `DigestSubscriptionRepo` port + `SADigestSubscriptionRepo`; CRUD + `list_active` + `list_by_owner`.
3. `DigestService.generate` — strict-`>` cursor, lookback first-run, cap per channel, skipped flag.
4. `prompts/digest.yaml` грузится; `reload_prompts(name="digest")` работает.
5. `LLM_SCOPES` расширен на `digest`; env vars `DIGEST_LLM_PROVIDER`/`_MODEL`; `set_llm_config(scope="digest", ...)` работает.
6. `BackgroundScheduler.add_cron_task` через `CronTrigger.from_crontab` + `ZoneInfo(timezone)`; helpers `register/unregister/reschedule`.
7. `tg_parser/bot/runtime.py` singleton + интеграция в `bot/main.py::run_bot`; digest-scheduler стартует только в bot-процессе.
8. Доставка через `Bot.send_message(MARKDOWN_V2)` + escape + split до 4096; >N частей → file.
9. Bot-tools `subscribe_digest`, `list_digests`, `unsubscribe_digest` (`subscribe_digest` ∈ `_TOOLS_NEEDING_BOT_CONTEXT`).
10. MCP-tools `subscribe_digest`, `list_digests`, `unsubscribe_digest` с channel-ownership и subscription-ownership.
11. Reconciliation loop в bot-scheduler (60s default).
12. Документация: USER_GUIDE (F6), MCP_AGENT_GUIDE (Digests), ENV_VARIABLES_GUIDE (7 новых vars), FUTURE_FEATURES (F6 DONE).
13. `tests/test_f6_scheduled_digests.py` — ~35+ тестов; все проходят.
14. `TEST_POSTGRES=1 pytest tests/ -x -q` — ≥1580 passed; существующие scheduler/bot/mcp/storage/rag тесты не регрессируют.
15. **Self-review loop выполнен** перед каждым коммитом (см. ниже §12).
16. Два коммита с указанными messages.

---

## Что НЕ входит в scope F6

- **Workspaces / per-group digests** — требует F4-B; F6 на уровне `channel_ids[]`.
- **Per-topic digest** — требует topic-filtering на уровне ProcessedDocument.
- **Digest history / archive** — отправленные дайджесты не сохраняются (только `last_sent_at`).
- **Email/webhook delivery** — только Telegram.
- **Smart adaptive scheduling** — `skipped=True` достаточно для MVP.
- **Per-source `poll_interval_seconds` enforcement** — отдельная задача (ingestion scheduler).
- **F1 (Configurable prompts in DB)** — digest prompt в `prompts/digest.yaml` (как все остальные).
- **Heartbeat empty digest** — флаг `notify_when_empty` не входит, можно добавить позже.
- **Migration auto-run в CI/prod** — миграция применяется через `alembic upgrade head` вручную; production runner — отдельная инфра-задача.

---

## Рекомендации исполнения

1. **Plan mode first** — свериться с актуальным `main` (после мёрджа PR #10): актуальные lines в `background_scheduler.py`, `tools.py` (`TOOL_DECLARATIONS` = 25 после F2), `mcp_server.py` (26 tools), `settings.py` (`LLM_SCOPES`).

2. **TDD для `DigestService.generate`** — pure logic поверх mock'ов repo и LLM. ~10 тестов покрывают 90% сложности фичи. Затем реализация.

3. **Порядок Commit 1:**
   1. Migration (`alembic revision -m "add digest subscriptions"`, ручная правка, `alembic upgrade head` локально).
   2. Domain (`DigestFormat`, `DigestSubscription`).
   3. Port (`DigestSubscriptionRepo` Protocol).
   4. ORM (`DigestSubscriptionORM`).
   5. SQLAlchemy repo (`SADigestSubscriptionRepo`) — gated unit-тестами repo.
   6. Settings (`digest_*` fields, `LLM_SCOPES` extension).
   7. Prompt YAML.
   8. `DigestService` — gated unit-тестами service.

4. **Порядок Commit 2:**
   1. `add_cron_task` + helpers — gated `TestSchedulerCronIntegration`.
   2. `tg_parser/bot/runtime.py`.
   3. `run_scheduled_digests_task` + reconciliation.
   4. Интеграция в `bot/main.py::run_bot`.
   5. Bot tools (3) — gated `TestBotDigestTools`.
   6. MCP tools (3) — gated `TestMCPDigestTools`.
   7. Docs.

5. **Backward-compat существующего scheduler-кода** — `BackgroundScheduler.add_task` (interval) НЕ трогаем; `add_cron_task` — новый. Тесты `TestBackgroundScheduler` (existing) должны остаться зелёными.

6. **Cursor-update только при успехе** — критичный invariant. Тест `test_deliver_no_bot_logs_warning_and_skips_cursor_update` фиксирует. Любая ошибка в `bot.send_message` (network, parse_mode crash, rate limit) → cursor НЕ обновляется → следующий тик повторит.

7. **Markdown V2 escape** — обязателен; пишем helper `_escape_md_v2(text)` (либо используем `aiogram.utils.markdown.escape_md`); тестируем на тексте с `_`, `*`, `[`, `]`, `(`, `)`, `~`, `\``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`. Реальный кейс: название канала `@my_channel` или summary с URL `https://example.com/path?q=1`.

8. **Cron validation** — `CronTrigger.from_crontab(expr)` бросает `ValueError` на invalid; в bot/MCP-tool ловим и возвращаем структурированную ошибку (`{"status": "rejected", "message": "Invalid cron expression: ..."}`) — НЕ пробрасываем 500.

9. **Cron security** — отвергать `*` в minute-position (`re.match(r"^\* ", expr)`); минимум — каждые 5 минут (`*/5 * * * *` ОК, `* * * * *` НЕТ).

10. **Timezone validation** — `try ZoneInfo(tz) except ZoneInfoNotFoundError` → структурированная ошибка.

11. **Channel ownership** — для **каждого** `channel_id` в `channel_ids[]` вызвать `assert_channel_access(user, cid)` **перед** созданием подписки. Тест `test_mcp_subscribe_digest_channel_ownership_enforced`: список `[own_channel, other_user_channel]` → rejected целиком (atomicity).

12. **Self-review loop (обязателен перед каждым коммитом)**

После того как новые тесты впервые прошли локально, **ДО** коммита:

1. **Первый прогон тестов** — убедиться что новые тесты зелёные:
   ```bash
   .venv/bin/pytest tests/test_f6_scheduled_digests.py -x -q
   ```
2. **Self-review** — перечитать **весь** новый и изменённый код + новые тесты. Оценить покрытие по чек-листу фазы:
   - **Commit 1 чек-лист:** migration upgrade/downgrade идемпотентны, repo isolation (no N+1), cursor strict-`>` (не `>=`), first-run lookback правильно обновляет cursor даже при пустом результате, max_docs_per_run cap per channel (не глобально), `LLM_SCOPES` расширен и `set_llm_config(scope="digest")` валидируется, prompt YAML валидный.
   - **Commit 2 чек-лист:** single-process delivery (только bot proc), bot runtime singleton (`set_bot` идемпотентен, `clear_bot` на shutdown), markdown_v2 escape (все спецсимволы), длинные сообщения split до 4096 и >N → file, cron validation возвращает понятную ошибку (не 500), timezone validation, channel ownership для каждого `channel_id`, reconciliation race (concurrent create + delete + reconcile), empty digest → НЕ send но `last_sent_at` обновляется, first-run pустой → `cursor=now` без повтора lookback, idempotency on cursor failure (send fail → cursor не меняется).
   - Детальные чек-листы — в [`F6_SCHEDULED_DIGESTS_PLAN.md`](../plans/F6_SCHEDULED_DIGESTS_PLAN.md) §"Self-review checklist" в Commit 1 и Commit 2.
3. **Добавить недостающие тесты** или поправить код, если чек-лист обнаружил пробелы. Это часть текущего коммита, не отдельный.
4. **Повторный прогон новых тестов** — убедиться что доработки зелёные:
   ```bash
   .venv/bin/pytest tests/test_f6_scheduled_digests.py -x -q
   ```
5. **Полный regression перед коммитом** — **обязателен**:
   ```bash
   .venv/bin/alembic upgrade head    # перед первым прогоном после Commit 1
   TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
   ```
   Ожидаемо после Commit 1: ≥1561 passed (1536 + ~25 новых). После Commit 2: ≥1580 passed.
6. **Commit** только после зелёного полного прогона.

Этот цикл применяется к **каждому** коммиту (Commit 1 и Commit 2 отдельно). Тот же паттерн, что и в F2 / F5-A Phase 1/2/3 — он ловит "тесты зелёные, но забыли edge case" и "новый код сломал что-то в existing suite".
