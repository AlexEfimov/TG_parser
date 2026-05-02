# Планировочная prep — Surface coverage parity (CLI / MCP / API / Bot)

**Назначение:** prep-документ для **будущей** планирующей сессии,
которая определит, какие из обнаруженных пробелов в покрытии CLI / MCP /
HTTP API / Telegram-бот будут закрываться следующими спринтами и в каком
порядке. Этот файл — **НЕ план**, **НЕ решение**. Он фиксирует **полную
инвентаризацию реализованных функций** и **расширенную матрицу покрытия**
четырёх поверхностей по состоянию на 2026-05-02, чтобы планирующая
сессия начиналась с готовых данных, а не с inventory'я с нуля.

**Дата подготовки prep:** Saturday 2026-05-02 (~18:30 UTC+4), parent
transcript «Surface coverage audit + planning prep».

**Дата проверки кодовой базы:** HEAD `mcp_server.py` от 2026-05-02
11:00, `tg_parser/bot/tools.py` от 2026-05-02 16:31. Все line-references
ниже сверены против этих ревизий.

**Когда использовать:** в момент, когда команда (a) явно решит
«parity-волна важнее текущего bug-fix-цикла или фичевой Wave D/E»
(см. § 8 Open question Q1), (b) выберет 1–3 parity-пакета из § 6
кандидатов для следующего спринта.

**Что должна произвести планирующая сессия:**

1. Зафиксированный приоритетный parity-пакет (или комбо из § 6) для
   следующего спринта (CLI / API / MCP / Bot).
2. Обновлённый full sprint-промпт по образцу
   [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) или
   [`START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md)
   (pre-flight, шаги, тесты, риски, PR-чеклист).
3. Запись decision-log в [`REVIEW_*`](.) или новом артефакте о том,
   **почему** выбран именно этот parity-пакет.
4. Обновление [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
   и/или [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md):
   куда parity-волна вставляется по приоритету относительно Wave D/E
   и активных bug-fix sprint'ов.

**Что планирующая сессия делать НЕ должна:**

- Реализовывать код или править существующие surface-handlers.
- Принимать решения, нарушающие Karpathy-like-инварианты ADR 0006
  (см. § 7 Karpathy-like-check).
- Расширять scope за пределы parity без явного флага «эта новая фича
  обоснована независимым product-сигналом, не parity-аргументом».

---

## 0. Зачем эта prep вообще нужна

После закрытия Living-KB-контракта (Wave A/B/C, 2026-04-26 — см.
[`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
§ «2026-04-26 — Contract closed»), и серии bug-fix-сессий (Sessions D/E/F/G,
финал 2026-05-02), накопилось **визуальное несоответствие** между
тем, что архитектура декларирует как «доступно через все surface'ы»
([`docs/architecture.md`](../architecture.md), [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md)),
и тем, что реально ассерт'ится в коде.

Конкретные триггеры:

- В [`docs/architecture.md`](../architecture.md) § «Phase 3C — Agent
  Observability» (L141–189) для агентов прописаны и CLI и API; для
  MCP/Bot — нет, и это **by design**. Но в других F-фичах (F6, F11,
  F5-C) симметрии между surface'ами **не зафиксировано** в архитектуре,
  хотя реализация фактически ассиметрична.
- В [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) описаны 36 MCP
  tools; в API эквивалент имеют ~22, в CLI ~24, в Bot ~33. Pattern
  расхождения не очевиден без явной матрицы.
- В Bot-промпте `prompts/bot.yaml` v1.5.0 LLM знает о 33 tool'ах. Если
  пользователь спросит про topic versions через бота — бот «не знает»
  такого инструмента, потому что F5-C tool'ы не зарегистрированы в
  `_TOOL_EXECUTORS`. Это видно из тестов BUG-007/BUG-009 (suggestion
  flow), но не задокументировано системно.
- ADR 0006 принцип #2 (Provenance / evidence) предполагает, что любая
  «карточка факта» (TopicCard, WatchInterest, DigestSubscription)
  доступна одинаковыми хелперами с любой surface. Текущее состояние
  это нарушает (digest-API нет вообще; watchlist-API нет вообще).

Этот документ — **inventory**, не **decision**. Он отвечает на вопрос
«какое именно расхождение?», а не «как чинить?». «Как чинить» — задача
планирующей сессии (см. § 6 кандидаты parity-пакетов).

---

## 1. Methodology

### 1.1 Источники данных

| Surface | Источник truth (file) | Способ инвентаризации |
|---------|----------------------|----------------------|
| **CLI** | [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py) + [`tg_parser/cli/agents_cmd.py`](../../tg_parser/cli/agents_cmd.py) + [`tg_parser/cli/db_cmd.py`](../../tg_parser/cli/db_cmd.py) + [`tg_parser/cli/scheduler_cmd.py`](../../tg_parser/cli/scheduler_cmd.py) + [`tg_parser/cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) + [`tg_parser/cli/watchlist_cmd.py`](../../tg_parser/cli/watchlist_cmd.py) | Поиск декораторов `@app.command` и `@app.command("name")` в Typer-приложениях. |
| **MCP** | [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) | `grep "^@mcp.tool()"` → 36 деклараций. |
| **API** | [`tg_parser/api/routes/*.py`](../../tg_parser/api/routes/) | Поиск декораторов `@router.get/post/put/patch/delete`. Регистрация роутеров в [`tg_parser/api/main.py`](../../tg_parser/api/main.py) L246–255. |
| **Bot** | [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py) `_TOOL_EXECUTORS` dict L2791–2824 + [`tg_parser/bot/handlers.py`](../../tg_parser/bot/handlers.py) (Telegram-команды `/start`, `/help`). | Список ключей в `_TOOL_EXECUTORS` = 33; декларации Gemini-tools — `TOOL_DECLARATIONS` L85+. Аиограм-команды отдельно. |

### 1.2 Что считается «функцией» в этом аудите

**Функция** — это бизнес-возможность, реализованная в `tg_parser/services/`
или в `mcp_server.py`, которая может быть вызвана извне. Сюда **не**
включаются:

- Внутренние утилиты (`utils/channel_id.py`, `_ranking.py`).
- Чисто инфраструктурные команды CLI (`init`, `auth`, `db *`, `migrate-users`,
  `backfill-content-hash` — они из коробки только в CLI, и так и должно
  быть).
- Запуск процессов (`tg-parser bot`, `tg-parser api`, `tg-parser mcp` —
  это process boot, не «функция»).

В сумме получается **49 уникальных бизнес-функций** (см. § 2.1 master
list).

### 1.3 Точность матрицы

- Если функция доступна через wrapper (`trigger_pipeline` оборачивает
  ingest+process+topicize+export) — она считается одной строкой матрицы;
  отдельные suboperations отмечены `⚠️ через X` в ячейке.
- Если surface принимает `mode/format/level` как parameter, который в
  другом surface **отсутствует** — это `⚠️` (capability присутствует,
  но reduced).
- `n/a` — функция концептуально не применима к surface (например,
  «Запустить bot процесс» нельзя через API).

---

## 2. Полная инвентаризация (master lists)

### 2.1 Master list бизнес-функций (49 штук)

Группировка по функциональным доменам (соответствует разделам
[`docs/architecture.md`](../architecture.md)):

| # | Функция | Доменный сервис / источник |
|---|---------|---------------------------|
| **Channel management (10)** | | |
| 1 | Add channel (создать source) | [`channel_service.py`](../../tg_parser/services/channel_service.py) `add_channel` |
| 2 | Remove channel (soft-delete) | `channel_service.remove_channel` |
| 3 | Pause channel | `channel_service.pause_channel` |
| 4 | Resume channel | `channel_service.resume_channel` |
| 5 | List channels (with stats) | [`analytics_service.py`](../../tg_parser/services/analytics_service.py) `list_channels` |
| 6 | Get channel stats (single) | `channel_service.get_channel_stats` |
| 7 | Authenticate Telethon (initial OAuth) | [`ingestion/telegram/telethon_client.py`](../../tg_parser/ingestion/telegram/telethon_client.py) |
| 8 | Trigger full pipeline for channel | [`pipeline_service.py`](../../tg_parser/services/pipeline_service.py) + `scheduler_service.run_incremental_for_source` |
| 9 | Get pipeline status (per channel) | `pipeline_service.get_pipeline_status` |
| 10 | One-shot full pipeline (CLI-only flow) | [`run_cmd.run_full_pipeline`](../../tg_parser/cli/run_cmd.py) |
| **Ingestion / Processing / Topicization (8)** | | |
| 11 | Run ingestion (single channel) | [`ingestion_service.py`](../../tg_parser/services/ingestion_service.py) `run_ingestion` |
| 12 | Run processing (single channel) | [`processing_service.py`](../../tg_parser/services/processing_service.py) `run_processing` |
| 13 | Run topicization (full / incremental / assign-only / auto) | [`topicization_service.py`](../../tg_parser/services/topicization_service.py) |
| 14 | Cross-channel topic linking | [`topic_linking_service.py`](../../tg_parser/services/topic_linking_service.py) |
| 15 | Generate / re-embed embeddings | [`embedding_service.py`](../../tg_parser/services/embedding_service.py) `run_embedding` |
| 16 | Force re-summarize topic (F5-C) | [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) `resummarize_topic` |
| 17 | Get topic versions (F5-C audit trail) | `topic_card_version_repo.list_by_topic` |
| 18 | Reload prompts (no restart) | [`processing/llm/factory.py`](../../tg_parser/processing/llm/factory.py) prompt registry |
| **Search / Q&A / Read (5)** | | |
| 19 | Hybrid / semantic / keyword search | [`retrieval_service.py`](../../tg_parser/services/retrieval_service.py) `search` (mode= semantic/keyword/hybrid) |
| 20 | RAG Q&A (with mode) | `retrieval_service.answer` |
| 21 | Get document by source_ref | `processing_service.get_document_by_source_ref` |
| 22 | List topics (filter by channel/type) | `topic_card_repo.list_by_channel` / `list_all` |
| 23 | Get topic details (card + bundle) | `topic_card_repo.get_by_id` + `topic_bundle_repo.get_by_topic_id` |
| **Cross-channel analytics (2)** | | |
| 24 | Get related topics (cross-channel) | [`analytics_service.py`](../../tg_parser/services/analytics_service.py) `get_related_topics` |
| 25 | Get cross-channel stats (coverage / overlaps) | `analytics_service.get_cross_channel_stats` |
| **Export (F2 Parse-Only) (1)** | | |
| 26 | Export channel (raw / processed / full, json/ndjson) | [`export_service.py`](../../tg_parser/services/export_service.py) `run_export` |
| **LLM configuration (3)** | | |
| 27 | Get LLM config (per scope) | [`config/llm_config.py`](../../tg_parser/config/llm_config.py) `get_all` |
| 28 | Set LLM config (runtime) | `llm_config.set` |
| 29 | Reset LLM config (back to .env) | `llm_config.clear` |
| **Multi-tenancy / Users (8)** | | |
| 30 | Whoami (current user profile) | [`auth/resolvers.py`](../../tg_parser/auth/resolvers.py) |
| 31 | Register / create user | [`storage/sqlalchemy/user_repo.py`](../../tg_parser/storage/sqlalchemy/user_repo.py) `create_user` |
| 32 | Update user (name/role/max_channels) | `user_repo.update_user` |
| 33 | List users (admin) | `user_repo.list_users` |
| 34 | Delete user (admin) | `user_repo.delete_user` |
| 35 | Add user auth-mapping (api_key / mcp_token / telegram) | `user_repo.add_auth_mapping` |
| 36 | Remove user auth-mapping | `user_repo.remove_auth_mapping` |
| 37 | Migrate legacy → users (F4 bootstrap) | [`cli/migrate_users_cmd.py`](../../tg_parser/cli/migrate_users_cmd.py) |
| **F6 Scheduled Digests (3)** | | |
| 38 | Subscribe digest (cron + format) | [`digest_service.py`](../../tg_parser/services/digest_service.py) |
| 39 | List digests | `digest_service.list_subscriptions` |
| 40 | Unsubscribe digest | `digest_service.unsubscribe` |
| **F11 Topic Watchlist (4)** | | |
| 41 | Subscribe watchlist (interest with keywords/threshold) | [`watchlist_service.py`](../../tg_parser/services/watchlist_service.py) |
| 42 | List watchlists | `watchlist_service.list_interests` |
| 43 | Unsubscribe watchlist (soft-delete) | `watchlist_service.unsubscribe` |
| 44 | Get watchlist matches (history) | `watchlist_service.get_matches` |
| **Multi-Agent observability (Phase 3C) (5)** | | |
| 45 | List agents | [`agents/registry.py`](../../tg_parser/agents/registry.py) |
| 46 | Agent stats (per period) | [`agents/persistence.py`](../../tg_parser/agents/persistence.py) `AgentStateRepo` |
| 47 | Agent task history | `agents/persistence.TaskHistoryRepo` |
| 48 | Handoff stats | `agents/persistence.HandoffHistoryRepo` |
| 49 | Cleanup expired agent records (with archival) | [`agents/archiver.py`](../../tg_parser/agents/archiver.py) |
| **Maintenance / служебное (6 — не считаются в 49)** | | |
| — | Initialize DB (Alembic upgrade) | `cli/init_db.py` |
| — | DB management (backup/restore/heads/check/...) | `cli/db_cmd.py` |
| — | Backfill content_hash (F5-A Phase 3) | `cli/backfill_content_hash_cmd.py` |
| — | Scheduler control (start/run-once/status) | `cli/scheduler_cmd.py` + `services/scheduler_service.py` |
| — | Health checks / Prometheus / detailed status | `api/routes/health.py` + `api/metrics.py` |
| — | Process boot (`bot`, `api`, `mcp`) | `cli/app.py` |

### 2.2 CLI inventory (24 функций)

Команды из [`tg_parser/cli/`](../../tg_parser/cli/):

| Команда | Файл / line | Категория |
|---------|-------------|-----------|
| `tg-parser auth` | [`app.py:28`](../../tg_parser/cli/app.py) | Maintenance |
| `tg-parser init` | [`app.py:86`](../../tg_parser/cli/app.py) | Maintenance |
| `tg-parser add-source` | [`app.py:107`](../../tg_parser/cli/app.py) | F1 |
| `tg-parser ingest` | [`app.py:154`](../../tg_parser/cli/app.py) | F11 |
| `tg-parser process` | [`app.py:194`](../../tg_parser/cli/app.py) | F12 |
| `tg-parser topicize` | [`app.py:341`](../../tg_parser/cli/app.py) | F13 |
| `tg-parser link-topics` | [`app.py:545`](../../tg_parser/cli/app.py) | F14 |
| `tg-parser embed` | [`app.py:577`](../../tg_parser/cli/app.py) | F15 |
| `tg-parser search` | [`app.py:612`](../../tg_parser/cli/app.py) | F19 (без `mode`) |
| `tg-parser ask` | [`app.py:651`](../../tg_parser/cli/app.py) | F20 (без `mode`) |
| `tg-parser export` | [`app.py:687`](../../tg_parser/cli/app.py) | F26 (sync) |
| `tg-parser run` (one-shot) | [`app.py:941`](../../tg_parser/cli/app.py) | F10 |
| `tg-parser migrate-users` | [`app.py:1062`](../../tg_parser/cli/app.py) | F37 |
| `tg-parser backfill-content-hash` | [`app.py:1101`](../../tg_parser/cli/app.py) | Maintenance |
| `tg-parser bot` | [`app.py:860`](../../tg_parser/cli/app.py) | Process boot |
| `tg-parser api` | [`app.py:819`](../../tg_parser/cli/app.py) | Process boot |
| `tg-parser mcp` | [`app.py:888`](../../tg_parser/cli/app.py) | Process boot |
| `tg-parser db {upgrade,downgrade,current,heads,check,history,stamp,revision,merge,backup,restore,list-backups,cleanup-orphan-admin}` (13 sub-commands) | [`db_cmd.py`](../../tg_parser/cli/db_cmd.py) | Maintenance |
| `tg-parser scheduler {run-once,start,status}` (3) | [`scheduler_cmd.py`](../../tg_parser/cli/scheduler_cmd.py) | Maintenance |
| `tg-parser topic {versions,resummarize}` (2) | [`topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) | F5-C (F16, F17) |
| `tg-parser watchlist {add,list,remove,matches}` (4) | [`watchlist_cmd.py`](../../tg_parser/cli/watchlist_cmd.py) | F11 (F41–F44) |
| `tg-parser agents {list,status,history,cleanup,handoffs,archives}` (6) | [`agents_cmd.py`](../../tg_parser/cli/agents_cmd.py) | Phase 3C (F45–F49) |

### 2.3 MCP inventory (36 tools)

Из [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py)
(line numbers — current HEAD):

| L | Tool | Group |
|---|------|-------|
| 800 | `search_knowledge_base` | RAG |
| 850 | `ask_question` | RAG |
| 905 | `list_topics` | Topics |
| 983 | `get_topic_details` | Topics |
| 1041 | `list_channels` | Channels (read) |
| 1063 | `get_document` | Read |
| 1098 | `get_related_topics` | Cross-channel |
| 1126 | `get_cross_channel_stats` | Cross-channel |
| 1157 | `add_channel` | Channels (write) |
| 1240 | `pause_channel` | Channels (write) |
| 1296 | `resume_channel` | Channels (write) |
| 1357 | `remove_channel` | Channels (write) |
| 1456 | `get_pipeline_status` | Pipeline |
| 1499 | `trigger_pipeline` | Pipeline (write) |
| 1617 | `get_llm_config` | LLM config |
| 1629 | `set_llm_config` | LLM config (write) |
| 1683 | `reset_llm_config` | LLM config (write) |
| 1716 | `register_user` | Users |
| 1744 | `update_user` | Users |
| 1781 | `list_users` | Users |
| 1811 | `whoami` | Users |
| 1839 | `add_user_auth` | Users-auth |
| 1884 | `remove_user_auth` | Users-auth |
| 1913 | `get_topic_versions` | F5-C |
| 1971 | `force_resummarize` | F5-C (admin) |
| 2026 | `reload_prompts` | LLM ops |
| 2073 | `export_channel` | Export (job) |
| 2206 | `get_export_status` | Export (job) |
| 2280 | `subscribe_digest` | F6 |
| 2414 | `list_digests` | F6 |
| 2438 | `unsubscribe_digest` | F6 |
| 2531 | `subscribe_watchlist` | F11 |
| 2652 | `list_watchlists` | F11 |
| 2682 | `unsubscribe_watchlist` | F11 |
| 2742 | `get_watchlist_matches` | F11 |

Tools **отсутствующие** в MCP (но есть на других surface'ах):

- `delete_user` (есть только в API).
- `link-topics` (cross-channel topic linking — есть только в CLI).
- `embed` (re-generation embeddings — есть только в CLI).
- `agents *` (observability — by design, см. § 4 mismatch C-1).

### 2.4 API inventory (32 endpoints)

Регистрация роутеров: [`api/main.py:246–255`](../../tg_parser/api/main.py).
Префикс по умолчанию `/api/v1` (исключения: `/health`, `/status`,
`/scheduler` без префикса; `/llm/*` под собственным).

| Method + Path | Файл / line | Group |
|---------------|-------------|-------|
| `GET /health` | [`health.py:24`](../../tg_parser/api/routes/health.py) | Health |
| `GET /status` | [`health.py:63`](../../tg_parser/api/routes/health.py) | Health |
| `GET /status/detailed` | [`health.py:95`](../../tg_parser/api/routes/health.py) | Health |
| `GET /scheduler` | [`health.py:125`](../../tg_parser/api/routes/health.py) | Health |
| `GET /metrics` | (via `prometheus_fastapi_instrumentator`) | Health |
| `POST /api/v1/process` | [`process.py:142`](../../tg_parser/api/routes/process.py) | F12 |
| `GET /api/v1/status/{job_id}` | [`process.py:208`](../../tg_parser/api/routes/process.py) | F12 |
| `GET /api/v1/jobs` | [`process.py:245`](../../tg_parser/api/routes/process.py) | F12 |
| `POST /api/v1/export` | [`export.py:192`](../../tg_parser/api/routes/export.py) | F26 (job) |
| `GET /api/v1/export/status/{job_id}` | [`export.py:268`](../../tg_parser/api/routes/export.py) | F26 |
| `GET /api/v1/export/download/{job_id}` | [`export.py:305`](../../tg_parser/api/routes/export.py) | F26 |
| `GET /api/v1/agents` | [`agents.py:129`](../../tg_parser/api/routes/agents.py) | F45 |
| `GET /api/v1/agents/{name}` | [`agents.py:171`](../../tg_parser/api/routes/agents.py) | F46 |
| `GET /api/v1/agents/{name}/stats` | [`agents.py:202`](../../tg_parser/api/routes/agents.py) | F46 |
| `GET /api/v1/agents/{name}/history` | [`agents.py:234`](../../tg_parser/api/routes/agents.py) | F47 |
| `GET /api/v1/agents/stats/handoffs` | [`agents.py:296`](../../tg_parser/api/routes/agents.py) | F48 |
| `POST /api/v1/search` | [`rag.py:84`](../../tg_parser/api/routes/rag.py) | F19 |
| `POST /api/v1/ask` | [`rag.py:116`](../../tg_parser/api/routes/rag.py) | F20 |
| `GET /api/v1/topics` | [`topics.py:77`](../../tg_parser/api/routes/topics.py) | F22 |
| `GET /api/v1/topics/{topic_id}` | [`topics.py:164`](../../tg_parser/api/routes/topics.py) | F23 |
| `GET /api/v1/topics/{topic_id}/bundle` | [`topics.py:123`](../../tg_parser/api/routes/topics.py) | F23 |
| `GET /api/v1/channels` | [`channels.py:51`](../../tg_parser/api/routes/channels.py) | F5 |
| `GET /api/v1/channels/{channel_id}/stats` | [`channels.py:79`](../../tg_parser/api/routes/channels.py) | F6 |
| `GET /api/v1/documents` | [`documents.py:37`](../../tg_parser/api/routes/documents.py) | F21 |
| `GET /llm/config` | [`llm_config.py:40`](../../tg_parser/api/routes/llm_config.py) | F27 |
| `PUT /llm/config` | [`llm_config.py:48`](../../tg_parser/api/routes/llm_config.py) | F28 |
| `POST /llm/config/reset` | [`llm_config.py:69`](../../tg_parser/api/routes/llm_config.py) | F29 |
| `GET /api/v1/users/me` | [`users.py:56`](../../tg_parser/api/routes/users.py) | F30 |
| `GET /api/v1/users` | [`users.py:82`](../../tg_parser/api/routes/users.py) | F33 |
| `POST /api/v1/users` | [`users.py:107`](../../tg_parser/api/routes/users.py) | F31 |
| `PATCH /api/v1/users/{user_id}` | [`users.py:131`](../../tg_parser/api/routes/users.py) | F32 |
| `DELETE /api/v1/users/{user_id}` | [`users.py:170`](../../tg_parser/api/routes/users.py) | F34 |

Endpoints **отсутствующие** в API (но есть на других surface'ах) —
см. § 3.B полный список.

### 2.5 Bot inventory (33 tool executors + 2 Telegram-команды)

Из [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py)
`_TOOL_EXECUTORS` dict L2791–2824:

| L (executor def) | Tool name | Group |
|------------------|-----------|-------|
| 1026 | `ask_question` | RAG |
| 1052 | `search_knowledge_base` | RAG |
| 1083 | `list_topics` | Topics |
| 1165 | `get_topic_details` | Topics |
| 1216 | `list_channels` | Channels (read) |
| 1240 | `get_document` | Read |
| 1269 | `get_related_topics` | Cross-channel |
| 1294 | `get_cross_channel_stats` | Cross-channel |
| 1364 | `trigger_pipeline` | Pipeline |
| 1461 | `get_pipeline_status` | Pipeline |
| 1506 | `pause_channel` | Channels (write) |
| 1582 | `resume_channel` | Channels (write) |
| 1672 | `add_channel` | Channels (write) |
| 1780 | `remove_channel` | Channels (write) |
| 1857 | `get_llm_config` | LLM config |
| 1866 | `set_llm_config` | LLM config |
| 1927 | `reset_llm_config` | LLM config |
| 1964 | `reload_prompts` | LLM ops |
| 1984 | `register_user` | Users |
| 2007 | `update_user` | Users |
| 2039 | `list_users` | Users |
| 2070 | `whoami` | Users |
| 2100 | `add_user_auth` | Users-auth |
| 2140 | `export_channel` | Export |
| 2312 | `subscribe_digest` | F6 |
| 2436 | `list_digests` | F6 |
| 2476 | `unsubscribe_digest` | F6 |
| 2504 | `remove_user_auth` | Users-auth |
| 2565 | `subscribe_watchlist` | F11 |
| 2662 | `list_watchlists` | F11 |
| 2690 | `unsubscribe_watchlist` | F11 |
| 2736 | `get_watchlist_matches` | F11 |

Tool'ы **отсутствующие** в Bot (но есть в MCP):

- `get_topic_versions` (F5-C) — нет в `_TOOL_EXECUTORS`.
- `force_resummarize` (F5-C admin) — нет.
- `get_export_status` (job-status check) — нет (бот доставляет файл
  синхронно через `bot.send_document`, см. `_exec_export_channel` L2140;
  separate status-check не выставлен).

Telegram-команды (aiogram handlers, [`bot/handlers.py`](../../tg_parser/bot/handlers.py)):

- `/start` (L143) — приветствие + регистрационный статус.
- `/help` (L168) — справка.
- Свободный текст (L174) — маршрутизируется через Gemini agent
  (`process_message`); агент сам вызывает `_TOOL_EXECUTORS`.

В боте **нет** slash-команд `/whoami`, `/channels`, `/topics`, `/digests`,
`/watchlist` и т.д. Это **by design** (см. § 5 mismatch E-1) — UX
полностью conversational.

---

## 3. Расширенная coverage matrix

Условные обозначения: `✅` — есть, `⚠️` — частично/синонимом или с
разными возможностями, `—` — отсутствует, `n/a` — не применимо для
surface'а.

### 3.1 По функциональным группам

#### A. Pipeline и операции с источниками (10 функций)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 1 | Add channel | `add-source` | `add_channel` | — | `add_channel` |
| 2 | Remove channel (soft) | — | `remove_channel` | — | `remove_channel` |
| 3 | Pause channel | — | `pause_channel` | — | `pause_channel` |
| 4 | Resume channel | — | `resume_channel` | — | `resume_channel` |
| 5 | List channels | — | `list_channels` | `GET /api/v1/channels` | `list_channels` |
| 6 | Channel stats (single) | — | ⚠️ через `list_channels` | `GET /channels/{id}/stats` | ⚠️ через `list_channels` |
| 7 | Authenticate Telethon | `auth` | n/a | n/a | n/a |
| 8 | Trigger pipeline | ⚠️ через `run` (one-shot, sync) | `trigger_pipeline` (job) | ⚠️ только processing через `POST /process` | `trigger_pipeline` |
| 9 | Get pipeline status | — | `get_pipeline_status` | — | `get_pipeline_status` |
| 10 | One-shot pipeline (sync) | `run` | — | — | — |

**Покрытие:** CLI 4/10, MCP 9/10, API 4/10, Bot 8/10.

#### B. Ingestion / Processing / Topicization (8)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 11 | Ingestion (single channel) | `ingest` | ⚠️ через `trigger_pipeline` | — | ⚠️ через `trigger_pipeline` |
| 12 | Processing | `process` | ⚠️ через `trigger_pipeline` | `POST /api/v1/process` (+ `/status/{id}`, `/jobs`) | ⚠️ через `trigger_pipeline` |
| 13 | Topicization (full/incremental/assign-only/auto) | `topicize` | ⚠️ через `trigger_pipeline` | — | ⚠️ через `trigger_pipeline` |
| 14 | Cross-channel topic linking | `link-topics` | — | — | — |
| 15 | Embedding generation | `embed` | — | — | — |
| 16 | Force re-summarize topic | `topic resummarize` | `force_resummarize` | — | — |
| 17 | Get topic versions (audit) | `topic versions` | `get_topic_versions` | — | — |
| 18 | Reload prompts | — | `reload_prompts` | — | `reload_prompts` |

**Покрытие:** CLI 7/8, MCP 5/8, API 1/8, Bot 4/8.

#### C. Search / Q&A / Read (5)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 19 | Search (semantic/keyword/hybrid) | `search` (⚠️ нет `--mode`) | `search_knowledge_base` (`mode=`) | `POST /api/v1/search` (`mode=`) | `search_knowledge_base` (`mode=`) |
| 20 | RAG Q&A | `ask` (⚠️ нет `--mode`) | `ask_question` (`mode=`) | `POST /api/v1/ask` (`mode=`) | `ask_question` (`mode=`) |
| 21 | Get document by source_ref | — | `get_document` | `GET /api/v1/documents` | `get_document` |
| 22 | List topics (by channel/type) | — | `list_topics` | `GET /api/v1/topics` | `list_topics` |
| 23 | Get topic details | — | `get_topic_details` | `GET /topics/{id}` + `/bundle` | `get_topic_details` |

**Покрытие:** CLI 2/5 (с reduced mode), MCP 5/5, API 5/5, Bot 5/5.

#### D. Cross-channel analytics (2)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 24 | Related topics (cross-channel) | — | `get_related_topics` | — | `get_related_topics` |
| 25 | Cross-channel stats | — | `get_cross_channel_stats` | — | `get_cross_channel_stats` |

**Покрытие:** CLI 0/2, MCP 2/2, API 0/2, Bot 2/2.

#### E. Export (F2 Parse-Only) (1)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 26 | Export (raw/processed/full × json/ndjson) | `export` (sync, файл на диск) | `export_channel` (job) + `get_export_status` | `POST /export` + `/export/status/{id}` + `/export/download/{id}` | `export_channel` (доставка файла в чат) |

**Покрытие:** 4/4, но **разные семантики** (sync vs job-based, доставка
файла vs в чат). См. § 4 mismatch E-2.

#### F. LLM configuration (3) + Reload prompts

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 27 | Get LLM config | — | `get_llm_config` | `GET /llm/config` | `get_llm_config` |
| 28 | Set LLM config | — | `set_llm_config` | `PUT /llm/config` | `set_llm_config` |
| 29 | Reset LLM config | — | `reset_llm_config` | `POST /llm/config/reset` | `reset_llm_config` |
| 18 | Reload prompts (повтор из B) | — | `reload_prompts` | — | `reload_prompts` |

**Покрытие:** CLI 0/3, MCP 3/3, API 3/3 (без `reload_prompts`), Bot 3/3.

#### G. Multi-tenancy / Users (8)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 30 | Whoami | — | `whoami` | `GET /api/v1/users/me` | `whoami` |
| 31 | Register / create user | — | `register_user` | `POST /api/v1/users` | `register_user` |
| 32 | Update user | — | `update_user` | `PATCH /api/v1/users/{id}` | `update_user` |
| 33 | List users | — | `list_users` | `GET /api/v1/users` | `list_users` |
| 34 | Delete user | — | — | `DELETE /api/v1/users/{id}` | — |
| 35 | Add user auth-mapping | — | `add_user_auth` | — | `add_user_auth` |
| 36 | Remove user auth-mapping | — | `remove_user_auth` | — | `remove_user_auth` |
| 37 | Migrate legacy → users | `migrate-users` | — | — | — |

**Покрытие:** CLI 1/8, MCP 6/8, API 5/8, Bot 6/8.

#### H. F6 Scheduled Digests (3)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 38 | Subscribe digest | — | `subscribe_digest` | — | `subscribe_digest` |
| 39 | List digests | — | `list_digests` | — | `list_digests` |
| 40 | Unsubscribe digest | — | `unsubscribe_digest` | — | `unsubscribe_digest` |

**Покрытие:** CLI 0/3, MCP 3/3, API 0/3, Bot 3/3. **F6 — самая
ассиметричная фича** (только MCP+Bot).

#### I. F11 Topic Watchlist (4)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 41 | Subscribe watchlist | `watchlist add` | `subscribe_watchlist` | — | `subscribe_watchlist` |
| 42 | List watchlists | `watchlist list` | `list_watchlists` | — | `list_watchlists` |
| 43 | Unsubscribe watchlist | `watchlist remove` | `unsubscribe_watchlist` | — | `unsubscribe_watchlist` |
| 44 | Watchlist matches | `watchlist matches` | `get_watchlist_matches` | — | `get_watchlist_matches` |

**Покрытие:** CLI 4/4, MCP 4/4, API 0/4, Bot 4/4. **F11 — единственная
фича, у которой CLI surface полный, а API — пустой.**

#### J. Multi-Agent observability (Phase 3C) (5)

| # | Функция | CLI | MCP | API | Bot |
|---|---------|:---:|:---:|:---:|:---:|
| 45 | List agents | `agents list` | — | `GET /api/v1/agents` | — |
| 46 | Agent stats | `agents status` | — | `GET /agents/{name}/stats` (+ `/agents/{name}`) | — |
| 47 | Agent task history | `agents history` | — | `GET /agents/{name}/history` | — |
| 48 | Handoff stats | `agents handoffs` | — | `GET /agents/stats/handoffs` | — |
| 49 | Cleanup expired records (с архивацией) | `agents cleanup` + `agents archives` | — | — | — |

**Покрытие:** CLI 5/5, MCP 0/5, API 4/5, Bot 0/5. **Phase 3C
ассиметрия — by design** (см. § 5 mismatch C-1; зафиксировано в
[`docs/architecture.md`](../architecture.md) § «Phase 3C» L141–189).

### 3.2 Сводная статистика

| Surface | Покрытие (из 49 функций) | % |
|---------|--------------------------|---|
| **MCP** | 36/49 (плюс `get_export_status` как job-status helper, итого 37) | **76%** |
| **Bot** | 33/49 | **67%** |
| **CLI** | 24/49 | **49%** |
| **API** | 22/49 (плюс health/metrics/scheduler-status — 25) | **45%** |

MCP — текущий **референс**. Любой gap в матрице — это «функция есть в
MCP, но не на surface X».

---

## 4. Gap classification (по surface'у)

### 4.A. Что НЕ покрыто в CLI (есть в MCP+Bot+/API)

CLI как «on-call surface» — недостаёт:

| ID | Команда | Уровень критичности | Mapping → master | F-feature |
|----|---------|:------------------:|:----------------:|:--------:|
| **A-1** | `tg-parser channels list` (channel inventory) | High | F5 | F5 |
| **A-2** | `tg-parser channels stats <id>` (single-channel stats) | High | F6 | F6 |
| **A-3** | `tg-parser channels {pause,resume,remove}` (управление) | High | F2/F3/F4 | F2-F4 |
| **A-4** | `tg-parser pipeline status [<channel>]` (per-channel) | High | F9 | F9 |
| **A-5** | `tg-parser pipeline trigger <channel>` (без ingest+process+topicize wrapper) | Medium | F8 | F8 |
| **A-6** | `tg-parser topics list` / `topics show <id>` | Medium | F22, F23 | F22, F23 |
| **A-7** | `tg-parser topics related <id>` / `topics cross-stats` | Medium | F24, F25 | F24, F25 |
| **A-8** | `tg-parser docs show <source_ref>` | Low | F21 | F21 |
| **A-9** | `tg-parser users {whoami,list,register,update,add-auth,remove-auth}` | Medium | F30–F36 | F30–F36 |
| **A-10** | `tg-parser digests {subscribe,list,unsubscribe}` | Medium | F38, F39, F40 | F6 |
| **A-11** | `tg-parser llm-config {get,set,reset}` + `prompts reload` | Medium | F27, F28, F29, F18 | F1 |
| **A-12** | `tg-parser search --mode <semantic|keyword|hybrid>` (extend) | Low | F19 (parameter parity) | — |
| **A-13** | `tg-parser ask --mode <...>` (extend) | Low | F20 (parameter parity) | — |

**Итого CLI gap:** 13 missing groups (≈ 25 commands).

### 4.B. Что НЕ покрыто в API (есть в MCP+Bot+/CLI)

API как «external integration surface» — недостаёт:

| ID | Endpoint | Уровень критичности | Mapping → master | F-feature |
|----|----------|:------------------:|:----------------:|:--------:|
| **B-1** | `POST /api/v1/channels` (add) | **Critical** | F1 | F1 |
| **B-2** | `DELETE /api/v1/channels/{id}` (soft-remove) | **Critical** | F2 | F2 |
| **B-3** | `POST /api/v1/channels/{id}/pause` + `.../resume` | **Critical** | F3, F4 | F3-F4 |
| **B-4** | `POST /api/v1/channels/{id}/pipeline/trigger` | High | F8 | F8 |
| **B-5** | `GET /api/v1/channels/{id}/pipeline/status` | High | F9 | F9 |
| **B-6** | `POST /api/v1/topics/{id}/resummarize` (admin) | Medium | F16 | F5-C |
| **B-7** | `GET /api/v1/topics/{id}/versions` | Medium | F17 | F5-C |
| **B-8** | `GET /api/v1/cross-channel/stats` | Medium | F25 | — |
| **B-9** | `GET /api/v1/topics/{id}/related` | Medium | F24 | — |
| **B-10** | F6 digests CRUD: `POST/GET/DELETE /api/v1/digests` (3 endpoints) | **Critical** | F38–F40 | F6 |
| **B-11** | F11 watchlist CRUD: `POST/GET/DELETE /api/v1/watchlists/{id}` + `/matches` (4 endpoints) | **Critical** | F41–F44 | F11 |
| **B-12** | `POST /api/v1/users/{id}/auth` + `DELETE /api/v1/users/auth/{mapping_id}` | High | F35, F36 | F4 |
| **B-13** | `POST /api/v1/prompts/reload` | Low | F18 | — |
| **B-14** | `POST /api/v1/topic-links` (cross-channel link, equivalent of CLI `link-topics`) | Low | F14 | — |
| **B-15** | `POST /api/v1/channels/{id}/embeddings` (re-embed) | Low | F15 | — |

**Итого API gap:** 15 missing endpoints (~22 routes).

### 4.C. Что НЕ покрыто в MCP (есть в CLI+API+/Bot)

| ID | Tool | Уровень критичности | Обоснование | Action |
|----|------|:------------------:|-------------|--------|
| **C-1** | `agents *` (5 tools) | Low (by design) | Phase 3C явно ограничивает observability на CLI+API; LLM-agents не нуждаются в introspection. | **No-op** (architecture-aligned). |
| **C-2** | `delete_user` | Low | API имеет hard-delete; MCP-парадигма — soft-only. Расширение на MCP может open security risk. | **Open question** (см. § 8 Q3). |
| **C-3** | `link_topics` (cross-channel) | Low | Operation idempotent + idempotent batch; в MCP-стиле — admin-only tool. | **Candidate** (parity-package P3, см. § 6). |
| **C-4** | `embed` (re-generate) | Low | Long-running task; для MCP нужен job-pattern (как у `export_channel`). | **Candidate** (parity-package P3). |

**Итого MCP gap:** 4 (1 by-design, 3 кандидата).

### 4.D. Что НЕ покрыто в Bot (есть в MCP+CLI+/API)

| ID | Tool | Уровень критичности | Обоснование | Action |
|----|------|:------------------:|-------------|--------|
| **D-1** | `get_topic_versions` | Medium | F5-C audit-trail полезен power-юзеру; LLM может процитировать историю. | **Candidate** (parity-package P4). |
| **D-2** | `force_resummarize` | Low (admin) | Требует confirm-flow + admin guard; по аналогии с `set_llm_config`. См. также **TD-bot-confirm-coverage-completeness** (Session G § 1.3). | **Candidate** (parity-package P4 + extends TD). |
| **D-3** | `get_export_status` | Low | Bot уже доставляет файл синхронно через `bot.send_document`; status-check был бы полезен только для long-running экспортов >120s. | **Open question** (Q4). |
| **D-4** | `agents *` | by design | См. C-1. | **No-op.** |
| **D-5** | `delete_user` | Low | UI confirmation + cascade — non-trivial. | **Open question** (Q3). |
| **D-6** | `link_topics`, `embed` | Low | Long-running; не conversational по природе. | **Open question** (Q5). |
| **D-7** | `channel_stats <id>` (single-channel rich stats) | Medium | Сейчас `list_channels` возвращает stats для всех; single-channel deep-dive нет. | **Candidate** (parity-package P5). |

**Итого Bot gap:** 7 групп (большинство — open questions, не явные deliverables).

---

## 5. Mismatch / asymmetry findings (помимо явных gap'ов)

Это **расхождения в семантике** для функций, которые **формально** есть на
обоих surface'ах, но ведут себя по-разному. Они отдельная категория от
gap'ов и тоже требуют решения.

### E-1. Bot не имеет slash-команд для всех функций — by design

`/start` и `/help` — единственные slash-команды
([`bot/handlers.py:143,168`](../../tg_parser/bot/handlers.py)). Все
остальные действия идут через свободный текст + Gemini agent.

**Обоснование:** UX выбран conversational
(см. [`bot/handlers.py:90–104`](../../tg_parser/bot/handlers.py)
START_TEXT). Slash-команды добавили бы duplicate surface.

**Open question:** должны ли быть введены `/whoami`, `/status` для
**deterministic operations**, не зависящих от LLM (BUG-002 / BUG-009
class рекомендует deterministic paths, см.
[`docs/notes/BUG_LOG.md`](BUG_LOG.md))? — см. § 8 Q6.

### E-2. CLI export — синхронный; MCP/API — job-based

| Surface | Поведение |
|---------|-----------|
| CLI `export` ([`app.py:687`](../../tg_parser/cli/app.py)) | `asyncio.run(run_export(...))` blocks until complete; файл оседает на диске. |
| MCP `export_channel` ([`mcp_server.py:2073`](../../tg_parser/mcp_server.py)) | Возвращает `job_id`; client poll'ит `get_export_status`. |
| API `POST /export` ([`export.py:192`](../../tg_parser/api/routes/export.py)) | Возвращает `job_id`; есть `/export/status/{id}` + `/export/download/{id}`. |
| Bot `export_channel` ([`tools.py:2140`](../../tg_parser/bot/tools.py)) | Sync run + `bot.send_document` (доставка в чат). |

**Расхождение:** CLI **не имеет** способа «забрать файл по `job_id`», что
ломает паттерн «MCP запросил export, CLI забрал файл». Решение: либо
CLI добавляет `tg-parser export status <job_id>`, либо MCP переходит на
sync-mode для `level=raw` без `since`.

### E-3. CLI search/ask без `--mode`; API/MCP/Bot — с `mode=`

CLI `search` ([`app.py:612`](../../tg_parser/cli/app.py)) и `ask`
([`app.py:651`](../../tg_parser/cli/app.py)) **не принимают** `mode`
parameter — используется default `hybrid` через
[`retrieval_service.search`](../../tg_parser/services/retrieval_service.py).

Для дебага on-call (например, «hybrid даёт мусор, что показывает чистый
keyword?») CLI вынужден идти через MCP или API. Это **5-минутный**
fix, но представительный.

### E-4. CLI `process` синхронный без `job_id`; API `POST /process` — job-based

CLI `process` блокирует до завершения. API `POST /process` возвращает
`job_id`, дальше `GET /api/v1/status/{job_id}`. Аналогично E-2.

**Влияние:** для длинных каналов (10k+ messages) CLI блокирует терминал;
API/MCP позволяют detach. Решение — добавить CLI `--detach` flag, который
будет аналогом `POST /process`.

### E-5. CLI watchlist имеет `--user <uuid>`, MCP/Bot — нет

CLI `watchlist add`/`list`/`remove` имеют `--user` для admin-on-behalf-of
([`watchlist_cmd.py:47`](../../tg_parser/cli/watchlist_cmd.py)). MCP и
Bot — нет (action всегда от current user).

**Обоснование:** в MCP/Bot подразумевается, что admin использует свой
auth-mapping и может создать interest для своего chat_id, но не для
чужого. CLI работает off-band и поэтому имеет доп. capability.

**Open question:** нужен ли admin-on-behalf-of в MCP/Bot? — см. § 8 Q7.

### E-6. F11 watchlist в API — нет вообще

В FUTURE_FEATURES.md F11 §«После F11» (см.
[`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
Wave D) явно сказано:

> «**HTTP CRUD `/api/v1/watchlists`** — вне MVP F11 (см. спринт-промпт);
> MCP/bot/CLI достаточно для пилота.»

То есть это **намеренный** gap. Но если parity-волна выбирается, F11
API — один из кандидатов, и **должен быть отмечен как явное changeover**
(не «забыли», а «осознанно отложили»).

### E-7. F6 digests в CLI — нет вообще

В отличие от F11, F6 не имеет CLI-эквивалента (нет `digests_cmd.py`).
Учитывая, что F11 имеет CLI и обе фичи структурно похожи (subscription
с cron-параметрами и chat_id), это **расхождение** между двумя
схожими фичами. Скорее всего unintentional.

---

## 6. Кандидаты parity-пакетов (для планирующей сессии)

Каждый «parity-пакет» — это согласованный набор изменений, который
закрывает **связанный** gap-set, а не отдельные тулзы. Это уменьшает
test-overhead и оставляет ADR 0006 invariants in-tact.

### P1 — Channels CRUD on API (B-1..B-5)

**Что входит:**

- `POST /api/v1/channels` — add (передаёт `channel_id`, `username`,
  `include_comments`, `batch_size`, `owner_id`).
- `DELETE /api/v1/channels/{id}` — soft-remove (mirror MCP `remove_channel`
  с `confirm` parameter).
- `POST /api/v1/channels/{id}/pause` + `.../resume` — управление статусом.
- `POST /api/v1/channels/{id}/pipeline/trigger` — wrapper над
  `scheduler_service.run_incremental_for_source`.
- `GET /api/v1/channels/{id}/pipeline/status` — wrapper над
  `pipeline_service.get_pipeline_status`.

**Зависимости (все DONE):** F4 multi-tenancy auth, F2 export pattern
для `confirm`, существующие services.

**Karpathy-like check (ADR 0006):** см. § 7.

**Costs estimate (preliminary):** ~1–1.5 сессии, ~250–350 LOC,
~20–25 тестов.

**Concrete signal:** **есть** — внешние integrations (например, n8n,
Zapier) не могут управлять каналами через REST; для production-deploy с
HTTP-only клиентом это блокер.

**Risks:**

- `confirm` semantic для `DELETE` — REST-style 204 vs preview-confirm
  flow. Решение: query parameter `?confirm=true`, default reject.
- Cascade на existing data при `DELETE` — соответствие MCP soft-delete
  semantic'у (raw данные сохраняются).

### P2 — F6 + F11 CRUD on API (B-10, B-11)

**Что входит:**

- F6 digests: `POST /api/v1/digests`, `GET /api/v1/digests`,
  `DELETE /api/v1/digests/{id}`.
- F11 watchlists: `POST /api/v1/watchlists`, `GET /api/v1/watchlists`,
  `DELETE /api/v1/watchlists/{id}`, `GET /api/v1/watchlists/{id}/matches`.

**Зависимости (все DONE):** F4 multi-tenancy, F6/F11 services.

**Costs estimate:** ~1.5 сессии, ~300–400 LOC, ~25–30 тестов.

**Concrete signal:** F6/F11 — две из четырёх «персонализационных»
фичей (вместе с user-CRUD); они **должны** быть на API для multi-channel
clients. Также см. § 5 E-6 / E-7 явное «вне MVP» — ровно такой scope-creep
этот пакет и закрывает.

**Risks:**

- `chat_id` semantic — для API client'а chat_id может быть выбран не
  его собственный. Нужен validation (см. F11 RBAC).
- Authorization model: bot-API-only-feature → cross-surface использование.

### P3 — CLI channels + topics + users (A-1..A-3, A-6, A-7, A-9)

**Что входит:**

- `tg-parser channels list / stats / pause / resume / remove`.
- `tg-parser topics list / show / related / cross-stats`.
- `tg-parser users whoami / list / register / update / delete /
  add-auth / remove-auth`.

**Зависимости (все DONE):** services уже есть (см. § 2.1 master list).

**Costs estimate:** ~1 сессия, ~400–500 LOC, ~30 тестов (по 1–2 на
команду).

**Concrete signal:** **есть** — on-call runbooks (см.
[`docs/runbooks/`](../runbooks/)) предполагают, что админ может
ввести команду в shell без бота/Cursor. Сейчас runbook упоминает
psql + REST + bot — фрагментарно.

**Risks:**

- Output format — JSON vs human. CLI пока всё в human; для скриптинга
  нужен `--json` flag (отдельный mini-PR).
- Дублирование Pydantic schemas из API — нужен общий util или import.

### P4 — Bot F5-C + cleanup (D-1, D-2)

**Что входит:**

- `_TOOL_EXECUTORS["get_topic_versions"]` + Gemini decl.
- `_TOOL_EXECUTORS["force_resummarize"]` + Gemini decl + добавление
  в `_WRITE_TOOLS_REQUIRING_CONFIRM` (Session G guard).
- Соответствующее обновление [`prompts/bot.yaml`](../../prompts/bot.yaml)
  v1.5.0 → v1.6.0 (новые tool описания).

**Зависимости (все DONE):** F5-C MVP, Session G guard.

**Costs estimate:** ~0.5–1 сессия, ~150 LOC, ~10 тестов (включая
contract-test bidirectional из Session G § 7 R-1).

**Concrete signal:** **слабый** — F5-C currently surfaces только в
CLI/MCP; пользователь может смотреть аудит через MCP-клиент (Cursor,
Claude Desktop). Bot-доступ полезен power-юзеру, но не критично.

**Risks:**

- Confirm-flow extension — `force_resummarize` admin-only. Гарантия
  по Session G `_WRITE_TOOLS_REQUIRING_CONFIRM` поддержит. Но bidirectional
  contract-test (R-1) должен включить новые tool'ы.

### P5 — CLI parameter parity + Bot single-channel stats (E-3, E-4, D-7)

**Что входит:**

- `tg-parser search --mode {semantic,keyword,hybrid}`.
- `tg-parser ask --mode {semantic,keyword,hybrid}`.
- `tg-parser process --detach` (returns `job_id`, runs background).
- Bot tool `get_channel_stats(channel_id)` — single-channel deep-dive
  (отдельно от `list_channels` aggregate).

**Зависимости (все DONE):** retrieval_service параметризован.

**Costs estimate:** ~0.3–0.5 сессии, ~50–80 LOC, ~5 тестов.

**Concrete signal:** **средний** — frequent on-call request «покажи
отдельный канал детально».

**Risks:** низкие, scope узкий.

### P6 — F6 CLI digests (A-10)

**Что входит:**

- Новый `tg_parser/cli/digest_cmd.py` с командами `add/list/remove`,
  по образцу `watchlist_cmd.py`.

**Зависимости (все DONE):** F6 service.

**Costs estimate:** ~0.3 сессии, ~150 LOC, ~10 тестов.

**Concrete signal:** см. E-7 — это closure расхождения между F6 и F11
CLI-coverage. Очень узкий scope.

**Risks:** низкие.

### Combo predictions

Какие комбо имеют смысл (по аналогии с Living-KB Wave A+B+C):

- **P1 + P2** (full API parity) — ~2.5–3 сессии, ~700+ LOC. Closure
  всей API category в одну волну. **Преимущество:** один coherent
  release; внешние клиенты получают полный CRUD.
- **P3 + P6** (full CLI parity для on-call) — ~1.3 сессии, ~550–650
  LOC. Closure on-call runbook gaps.
- **P4 + P5** (UX polish) — ~0.8–1.5 сессии, маленький LOC. «Quality
  pass» волна.

**Антикомбо:** P1+P3 (overlap по channels services — risk что разные
sessions редактируют один service module).

---

## 7. Karpathy-like check (ADR 0006) для parity-пакетов

ADR 0006 фиксирует 7 принципов, которые любая новая фича обязана
проверить. Ниже — короткий run всех 7 для каждого parity-пакета,
который требует обоснования.

### P1 (Channels API CRUD)

| # | Принцип | Соответствие |
|---|---------|--------------|
| 1 | Persistent entities | `Source` уже сущность; новые endpoints — surface, не данные. ✓ |
| 2 | Provenance | `source_attempts` журнал не меняется. ✓ |
| 3 | Cheap retrieval | n/a (write-операции). |
| 4 | Идемпотентность | `add_channel` UPSERT по `source_id`; `pause/resume` — flag flip. ✓ |
| 5 | Living loop | Hooks не меняются; trigger_pipeline уже incremental. ✓ |
| 6 | Observability | Reuse `tg_pipeline_*` метрик. ✓ |
| 7 | Graceful degradation | `pause` → ingestion остаётся возможен через CLI. ✓ |

**Verdict:** ADR-0006 compliant.

### P2 (F6 + F11 API CRUD)

| # | Принцип | Соответствие |
|---|---------|--------------|
| 1 | Persistent entities | `WatchInterest`, `DigestSubscription` — уже сущности. ✓ |
| 2 | Provenance | `watch_matches` — append-only; не trogается. ✓ |
| 3 | Cheap retrieval | n/a. |
| 4 | Идемпотентность | `subscribe` UPSERT; `unsubscribe` soft-delete (preserve matches). ✓ |
| 5 | Living loop | Hooks scheduler/topicization не меняются. ✓ |
| 6 | Observability | `tg_watchlist_score` / `tg_digest_*` уже есть. ✓ |
| 7 | Graceful degradation | API client не валит F6/F11 hooks при крахе. ✓ |

**Verdict:** ADR-0006 compliant.

### P3 (CLI on-call commands)

CLI — read-mostly + admin write. Принципы 4, 5, 6 — n/a (тонкий wrapper
над services, semantic не меняется). Принципы 1, 2, 3, 7 наследуются от
underlying service'ов. ✓

### P4 (Bot F5-C tools)

| # | Принцип | Соответствие |
|---|---------|--------------|
| 1 | Persistent entities | `topic_card_versions` уже есть. ✓ |
| 2 | Provenance | F5-C audit trail — основа фичи. ✓ |
| 3 | Cheap retrieval | `get_topic_versions` — SQL по indexed `topic_id`. ✓ |
| 4 | Идемпотентность | `force_resummarize` — advisory-lock через ResummarizationService (как в CLI/MCP). ✓ |
| 5 | Living loop | Hook не меняется, manual trigger дополняет. ✓ |
| 6 | Observability | `tg_resummarize_total` reuse. ✓ |
| 7 | Graceful degradation | `force_resummarize` под locked → status='locked' (не fail). ✓ |

**Verdict:** ADR-0006 compliant; единственная concern — bot prompt
v1.6.0 должен описать tool достаточно чётко, чтобы LLM не путал
`force_resummarize` с обычным `resummarize_topic` (защита по Session G
`ConfirmFlowMismatch`).

### P5, P6 — trivial, без отдельной таблицы.

---

## 8. Open design questions (для планирующей сессии)

Эти вопросы НЕ имеют «правильного» ответа в текущих документах — их
надо явно обсудить и зафиксировать в результирующем спринт-промпте.

### Q1. Parity vs Wave D/E vs bug-fixes — что приоритетнее?

После Session G/H закрытия (BUG-009, BUG-011), команда стоит перед
выбором:

- **Parity-волна** (этот документ) — закрывает накопленные расхождения,
  не приносит новых product-feature.
- **Wave D** (F11 P2 / F5-B / threshold calibration —
  [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md)) —
  product-feature track.
- **Параллельные bug-fixes** (BUG-010 / BUG-012 / TD-bot-confirm-coverage)
  — quality track.

Какой signal должен доминировать?

- **External-client driver:** есть ли HTTP-only клиент, ждущий API?
- **Internal ops-friction:** насколько on-call страдает от CLI gap'а?
- **Karpathy-like coherence:** parity-волна — это «closure of inventory»,
  не направленное движение. Wave D — направленное.

### Q2. Combo vs single-package?

P1+P2 закрывают всю API ассимметрию в одну волну (2.5–3 сессии). Risk —
scope creep, как Living-KB Wave A+B+C, который ждал ~3 сессии. Альтернатива
— P1 → P2 sequential, по 1.5 сессии каждый.

P3+P6 — CLI complete (1.3 сессии). Очень компактно.

Combo с P4 (Bot F5-C) — отдельный лёгкий пакет, может присоединяться
к любому.

### Q3. `delete_user` в MCP / Bot?

Сейчас только API имеет `DELETE /users/{id}`. Расширение на MCP — открывает
attack vector «admin-LLM-token может удалить любого user'а». Решение:

- (a) НЕ добавлять, оставить hard-delete только за API admin.
- (b) Добавить с обязательным `confirm`-flow (MCP) и FSM (Bot,
  Session G guard).
- (c) Заменить на soft-delete (по аналогии с `remove_channel`).

### Q4. `get_export_status` в Bot?

Bot текущей реализацией доставляет файл синхронно. Status-check полезен
только если export долгий. С учётом, что aiogram bot не работает с
job_id (UX-anti-pattern), решение:

- (a) НЕ добавлять (текущее).
- (b) Добавить timeout-fallback («export занял >120s, проверь /status»).
- (c) Завести отдельный `/exports` slash-command для статуса.

### Q5. Long-running ops (`embed`, `link-topics`) на MCP/Bot?

Эти команды имеют CLI-only форму (несколько минут). Перевод на MCP/Bot
требует:

- Job pattern (как `export_channel`).
- Progress reporting (для долгих).
- Error-handling под MCP/Bot constraints (timeout 60s default в
  `execute_tool`).

Решение: либо вынести в P5+ (job-pattern volume), либо оставить CLI-only
(с явным маркером в архитектуре).

### Q6. Slash-команды бота — расширять?

Bot сейчас имеет только `/start` + `/help`. Введение `/whoami`, `/status`,
`/topics` (deterministic, без LLM) защищает от BUG-002/BUG-009 class
(LLM не может галлюцинировать на slash-команде).

Trade-off: extra UX surface vs deterministic-paths. Open question — кто
именно жалуется на conversational UX? (bug-trace vs user-feedback).

### Q7. Admin-on-behalf-of semantic в MCP/Bot?

CLI watchlist имеет `--user <uuid>`. MCP/Bot — нет. Нужен ли в MCP
эквивалент (`subscribe_watchlist(..., on_behalf_of=user_id)`)? Risk
— escalation token (admin может subscribe spam interest).

### Q8. Где живёт canonical schema для каждой surface?

Сейчас:
- API — Pydantic (FastAPI auto-schema).
- MCP — `pydantic.BaseModel` с `ArgModelBase`.
- Bot — Gemini `TOOL_DECLARATIONS` (JSON Schema, не Pydantic).
- CLI — Typer args.

Расхождения в `mode` parameter (E-3) — прямой следствие отсутствия
shared schema. Большой refactor — отдельный спринт; planning сессии
надо решить, делать ли это **сейчас** или после parity-волны.

---

## 9. Reading list для планирующей сессии

### Обязательные

| Файл | Зачем |
|------|-------|
| Этот файл (PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) | Inventory + матрица + кандидаты § 6 + open questions § 8. |
| [`docs/architecture.md`](../architecture.md) § «Phase 3C — Agent Observability» (L141–189) | Образец явного «by design ассиметрии». |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist для каждого parity-пакета § 7. |
| [`docs/notes/PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) | Альтернатива parity-волне (Wave D candidates). |
| [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Next contract — TBD» | Куда parity-волна вставляется. |

### Контекстные (по выбранному parity-пакету)

| Кандидат | Reading |
|----------|---------|
| **P1** (Channels API CRUD) | [`tg_parser/api/routes/channels.py`](../../tg_parser/api/routes/channels.py) (текущие GETs) + [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) L1157–1500 (mirror tools) + [`tg_parser/services/channel_service.py`](../../tg_parser/services/channel_service.py) (underlying ops) |
| **P2** (F6/F11 API CRUD) | [`tg_parser/services/digest_service.py`](../../tg_parser/services/digest_service.py) + [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) + [`tg_parser/cli/watchlist_cmd.py`](../../tg_parser/cli/watchlist_cmd.py) (CLI образец) + MCP tools L2280–2820 |
| **P3** (CLI on-call) | [`tg_parser/cli/watchlist_cmd.py`](../../tg_parser/cli/watchlist_cmd.py) (best-в-классе CLI образец) + [`tg_parser/cli/agents_cmd.py`](../../tg_parser/cli/agents_cmd.py) (subcommand-group образец) |
| **P4** (Bot F5-C) | [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py) + Session G start-prompt § 1.3 G-4 (bidirectional contract test) |
| **P5/P6** | trivial — `cli/app.py` search/ask + `cli/watchlist_cmd.py` template для P6 |

### Operational

| Файл | Зачем |
|------|-------|
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | Active bugs — для § 8 Q1 (parity vs bug-fix priority). |
| [`docs/runbooks/`](../runbooks/) | On-call gaps — обоснование для P3 (CLI). |
| [`CHANGELOG.md`](../../CHANGELOG.md) [Unreleased] | Свежие изменения в production. |

### Format-precedent для результирующего sprint-промпта

После выбора parity-пакета, планирующая сессия производит спринт-промпт
по образцу:

- **F11 (large feature):** [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md)
- **F5-C (planning + sprint pair):** [`START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md)
  + [`START_PROMPT_SPRINT_F5C.md`](START_PROMPT_SPRINT_F5C.md)
- **Bug-fix template (для combo с bug-fix):** [`START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md)
- **Mid-size API/CLI surface:** ближайший образец — F2 sprint (export-only)
  через [`docs/prompts/F2_PARSE_ONLY_EXPORT_PROMPT.md`](../prompts/F2_PARSE_ONLY_EXPORT_PROMPT.md)
  (3-surface coordinated change — CLI + API + MCP + Bot).

---

## 10. Связанные документы

| Документ | Связь |
|----------|-------|
| [`docs/architecture.md`](../architecture.md) | Декларирует архитектурные surface'ы; матрица здесь — фактическая реализация. |
| [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) | Описание 36 MCP tools — current MCP reference, см. § 2.3. |
| [`docs/USER_GUIDE.md`](../USER_GUIDE.md) | User-facing документация по CLI + Bot; gap analysis может потребовать её обновления. |
| [`docs/notes/FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | F-features таблица; mapping в § 4 идёт по этому каталогу. |
| [`docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | Календарь волн; parity-волна не в текущей таблице, должна вставляться (см. Q1). |
| [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Next contract — TBD» | Альтернатива (Wave D/E); см. Q1 trade-off. |
| [`docs/notes/PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) | Companion-prep для feature-track (F11 P2 / F5-B / Wave E). |
| [`docs/notes/PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) | Образец planning prep для крупной фичи; precedent для format. |
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | Active bugs; § 8 Q3 (combo с bug-fix). |
| [`docs/contracts/`](../contracts/) | JSON Schemas для всех domain-сущностей; новые endpoints должны переиспользовать. |
| [`docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md) | Bug-fix prompt template; для P4 Bot F5-C сценария надо учесть Session G `_WRITE_TOOLS_REQUIRING_CONFIRM` set extension. |

---

## 11. История prep-документа

| Дата | Изменение |
|------|-----------|
| 2026-05-02 | Первая версия. Создан после ревизии CLI/MCP/API/Bot surface'ов на HEAD `mcp_server.py` (2026-05-02 11:00) и `bot/tools.py` (2026-05-02 16:31). 5 parity-пакетов кандидатов § 6, 8 open questions § 8, ADR-0006 check § 7. Планирующая сессия — TBD по триггеру § 8 Q1. |

---

## 12. Когда удалить этот файл

Когда планирующая сессия пройдёт и produced спринт-промпт landed —
этот prep-документ заменяется ссылкой из roadmap → `## 202X-XX-XX —
Parity wave (P<N>): <title>` со ссылкой на произведённый sprint-промпт.
Этот файл может быть либо удалён, либо переименован в
`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02_archived.md` для
истории — на усмотрение планирующей сессии.

Если parity-волна полностью НЕ выбирается (команда решает «текущая
ассиметрия — допустима, идём в Wave D») — документ сохраняется как
**decision artifact** (запись «приоритеты были осознанно расставлены
не в пользу parity»).

---

**Pre-flight для планирующей сессии:**

```bash
# Sanity-check матрицы — line numbers могут уйти после новых
# commit'ов в mcp_server.py / bot/tools.py / cli/.
git log --since="2026-05-02 18:30 UTC+4" -- \
  tg_parser/mcp_server.py tg_parser/bot/tools.py \
  tg_parser/cli/ tg_parser/api/routes/

# Если есть commit'ы — пройтись по § 2.3 / 2.4 / 2.5 и обновить
# line refs в этом файле перед сессией.
```

Если grep вернул пусто — матрица актуальна. Иначе — refresh inventory
по procedure из § 1.1 Methodology.
