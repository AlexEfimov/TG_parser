# Changelog

All notable changes to TG_parser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Sprint D.1 — Topicization Hardening (2026-04-25)

**Контекст:** Silent stall топикизации на канале `genotek` (см. `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md`) — incremental-режим не находил `TopicCard` и тихо пропускал работу, в `source_attempts.success=true` несмотря на 0 произведённых тем.

#### Added
- **`AnthropicBillingError`** (`tg_parser/processing/llm/errors.py`) — отдельный non-retryable класс ошибки для `400 invalid_request_error: credit balance is too low`. Pipeline retry-loops такую ошибку не ретраят.
- **`source_attempts.failed_stage`** — новая колонка (`VARCHAR`, nullable) с именем первого упавшего этапа (`ingest` / `process` / `export` / `topicize` / `incremental_topicization`). Миграция: `migrations/versions/ingestion/20260425_add_source_attempts_failed_stage.py` (revision `ac6a4414ac58`).
- **Метрика `tg_parser_anthropic_billing_block_total{stage}`** (`tg_parser/api/metrics.py`) — счётчик billing-пауз для алертинга.
- **`BILLING_BLOCK_BACKOFF_S`** (env, default `3600`, min `60`) — длительность паузы источника после billing-error. См. `ENV_VARIABLES_GUIDE.md` и `.env.example`.

#### Changed
- **Per-batch checkpointing в incremental Phase 2.** `topicization_service.run_incremental_topicization` теперь вызывает `_discover_single_batch` в цикле и после каждого успешного батча сразу персистит `topic_card_repo.upsert(...)` + `topic_bundle_repo.add_items(...)`. Падение N+1-го батча больше не откатывает первые N. Деталь оркестрации: `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` § Sprint D.1.
- **Эскалация incremental → full.** Если новые документы есть, а `TopicCard` = 0, incremental-режим автоматически вызывает `run_topicization(force=True)` вместо тихого no-op.
- **Truthful `source_attempts`.** `scheduler_service._process_source` ведёт `stage_errors[]` и в `finally` пишет `record_attempt(success, failed_stage, error_class, error_message)`. Любой сбой на любом этапе пишется в БД (`error_message` усечено до 4096 символов).
- **`_discover_single_batch`** (`tg_parser/processing/topicization.py`) пробрасывает `RuntimeError` / `ValueError` / `OSError` наружу вместо «тихого» fallback в `unassignable` — иначе scheduler не узнавал об ошибке.
- **`scheduler_service`** пропускает источники с активным `rate_limit_until` (включая billing-pause).

#### Tests
- `tests/test_anthropic_client_billing.py` — 4 теста: распознавание credit-balance, не-retry, malformed body, case-insensitivity.
- `tests/test_incremental_topicization.py` — добавлены `test_incremental_escalates_to_full_when_no_topic_cards`, `test_incremental_llm_checkpoint_persists_previous_batches_on_failure`.
- `tests/test_scheduler_service.py` — добавлены `test_failed_incremental_topicization_marks_attempt_failed`, `test_billing_error_pauses_source_and_marks_failure` (проверяют `failed_stage`, метрику, `rate_limit_until` ± `BILLING_BLOCK_BACKOFF_S`).
- `tests/test_cross_channel_topicization.py` — оркестрационные тесты адаптированы к новому per-batch call-path.

#### Migration
```bash
alembic -c migrations/alembic_ingestion.ini upgrade head   # ac6a4414ac58
```

#### Documentation
- `docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md` — обновлён до `DONE (in-code)`.
- `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` — добавлен раздел Sprint D.1 + расширена таблица рисков.
- `docs/architecture.md` — `source_attempts` schema (DDL + bullet-list) теперь включает `failed_stage`.
- `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` — статус `fixed in code`.
- `docs/quality/TRIAGED.md` / `docs/notes/FUTURE_FEATURES.md` / `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — D.1 отмечен завершённым.

## [4.3.0] - 2026-04-15

### Added

#### Multi-Tenancy — User Management (F4 Phase 5)
- **User model** — `users` + `user_auth_mappings` tables with roles (`admin` / `user`), per-user channel limits, and channel ownership (`sources.owner_id`)
- **Auth resolution** — `resolve_user_by_auth()` with TTL cache; supports `api_key` (SHA-256 hash), `mcp_token` (SHA-256 hash), and `telegram` (plain user ID) auth types
- **Ownership enforcement** — `assert_channel_access()`, `assert_admin()`, `check_channel_limit()` helpers used across API, MCP, and Bot layers

#### MCP Server (24 tools — was 17)
- **`register_user`** — create a new user (admin only)
- **`update_user`** — update user properties including `reset_max_channels` (admin only)
- **`list_users`** — list all users with owned channel counts (admin only)
- **`whoami`** — current user profile with channel list (any authenticated user)
- **`add_user_auth`** — add auth mapping; auto-hashes `api_key`/`mcp_token` (admin only)
- **`remove_user_auth`** — remove auth mapping by ID (admin only)
- **`reload_prompts`** — reload prompt YAML files without restart (admin only)

#### Telegram Bot (24 tools — was 17)
- 6 new `_exec_*` functions + 6 new `TOOL_DECLARATIONS` for Gemini function-calling
- Same capabilities as MCP user management tools
- `/start` now shows personalized greeting or "not registered" message based on `CurrentUser`

#### REST API — `/api/v1/users`
- **`GET /api/v1/users/me`** — current user profile with owned channels
- **`GET /api/v1/users`** — list all users with channel counts (admin only)
- **`POST /api/v1/users`** — create user (admin only, 201)
- **`PATCH /api/v1/users/{id}`** — update user with `reset_max_channels` flag (admin only)
- **`DELETE /api/v1/users/{id}`** — delete user + cascade auth mappings (admin only, 204)

#### CLI — Migration
- **`tg-parser migrate-users [--dry-run]`** — one-time migration of existing credentials to user model
  - Maps `API_KEYS` → `api_key` auth mappings (SHA-256 hashed)
  - Maps `MCP_AUTH_TOKENS` → `mcp_token` auth mappings (SHA-256 hashed)
  - Maps `BOT_ALLOWED_USERS` → `telegram` auth mappings
  - Assigns `owner_id` on orphan sources
  - Idempotent: safe to run multiple times

#### Configuration
- **`DEFAULT_MAX_CHANNELS`** — default channel limit per user when `users.max_channels` is NULL (default: 20)

### Changed
- **Version bumped to 4.3.0** from 4.2.0
- **MCP + Bot tool count**: 17 → 24 (+ 6 user management + 1 reload_prompts)
- **1266 tests** — up from 855 (incl. `TEST_POSTGRES=1`)

### Tests
- **`tests/test_f4_user_management.py`** — 57 unit tests covering MCP, Bot, API, Migration tools
- **`tests/test_users_routes.py`** — 13 HTTP integration tests via AsyncClient/ASGITransport
- Updated `test_bot_tools_v11.py` / `test_bot_tools_v12.py` — TOOL_DECLARATIONS count 18 → 24

## [4.2.0] - 2026-04-09

### Added

#### MCP Server (17 tools)
- **Streamable HTTP transport** — production-ready MCP over HTTP (replaces stdio)
- **Bearer token authentication** — `MCP_AUTH_ENABLED` + `MCP_AUTH_TOKENS`
- **Channel management tools** — `add_channel`, `pause_channel`, `resume_channel`, `remove_channel`
- **Pipeline control** — `trigger_pipeline`, `get_pipeline_status`
- **LLM config management** — `get_llm_config`, `set_llm_config`, `reset_llm_config`
- **Cross-channel analytics** — `get_cross_channel_stats`, `get_related_topics`
- **Search & Q&A** — `search_knowledge_base`, `ask_question` (RAG with citations)
- **Navigation** — `list_topics`, `get_topic_details`, `list_channels`, `get_document`

#### Telegram Bot (V1.2 — Full Operational Interface)
- **Gemini-powered agent** — free-form chat, automatic tool routing
- **17 tools** — same capabilities as MCP server
- **Two-phase confirmation** — preview → confirm for all write operations
- **User allowlist** — `BOT_ALLOWED_USERS` for access control
- **Rate limiting** — per-user request throttling

#### Embedding & RAG
- **pgvector embeddings** — semantic search over knowledge base
- **OpenAI embeddings** — `text-embedding-3-small` by default
- **RAG pipeline** — retrieval-augmented Q&A with source citations

#### Cross-channel Analytics
- **Topic linking** — automatic detection of related topics across channels
- **Keyword overlap** — cross-channel keyword analysis
- **Coverage stats** — topic counts and coverage per channel

#### Production Infrastructure
- **Docker Compose full stack** — API, MCP, Bot, PostgreSQL, Prometheus, Grafana
- **Nginx reverse proxy** — TLS via Let's Encrypt, auto-renewal
- **Prometheus + Grafana** — HTTP, LLM, pipeline, scheduler metrics; 2 dashboards
- **Automated backups** — daily PostgreSQL backups with rotation
- **Per-stage LLM overrides** — `PROCESSING_LLM_PROVIDER`, `TOPICIZATION_LLM_PROVIDER`
- **Incremental topicization** — process only new documents
- **Background scheduler** — automatic pipeline execution on intervals

### Changed
- **Version bumped to 4.2.0** from 3.1.1
- **PostgreSQL as primary** — pgvector for embeddings, connection pooling
- **855 tests** — up from 411

## [3.1.1] - 2025-12-30

### Fixed

#### CLI PostgreSQL Compatibility
- **All CLI commands now use `Database.from_settings()`** — unified database initialization
  - `add_source_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `ingest_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `process_cmd.py` — updated 2 instances to from_settings()
  - `export_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `run_cmd.py` — removed DatabaseConfig, uses from_settings()
  - `topicize_cmd.py` — removed DatabaseConfig, uses from_settings()

#### Repository Boolean Type Compatibility
- **Fixed boolean fields for PostgreSQL** — `asyncpg` requires native `bool`, not `int`
  - `ingestion_state_repo.py` — `include_comments`, `comments_unavailable`, `success`
  - `raw_message_repo.py` — `raw_payload_truncated`
  - `agent_state_repo.py` — `is_active`
  - `task_history_repo.py` — `success`
  - Changed from `1 if x else 0` to `bool(x)`

#### Test Fixes
- **E2E tests** — added explicit `db_type="sqlite"` in e2e_settings fixture
- **Migration tests** — added `pytestmark` to skip when `DB_TYPE=postgresql`
- **Run command tests** — added missing `run_cmd.settings` patch

### Tested

#### Session 24 (Initial PostgreSQL Testing)
- Full pipeline on real Telegram channel (@BiocodebySechenov)
- 8 posts ingested, processed, topicized, and exported
- All 411 tests passing

#### Session 25 (Multi-Channel Testing) 🆕
- **4 additional channels tested** with 100% success rate:
  - @durov (46 posts) — технологии/Telegram, EN/RU
  - @telegram (50 posts) — официальный канал, EN
  - @tproger (43 posts) — IT/программирование, RU
  - @habr_com (98 posts) — IT новости, RU
- **Total:** 237 posts processed with **100% success**
- **Performance metrics:**
  - Ingestion: ~80 posts/s
  - Processing: 0.16 posts/s (GPT-4o-mini)
  - 24 topics created
- PostgreSQL backend confirmed stable
- Multi-language support (RU + EN) verified

---

## [3.1.0] - 2025-12-29

### 🎯 v3.1.0 - Production Ready: PostgreSQL & Multi-user Support (Session 24)

**MAJOR RELEASE** - TG_parser теперь production-ready с PostgreSQL, connection pooling, и multi-user support.

#### Added

##### PostgreSQL Support

- **PostgreSQL Database Backend** — production-grade RDBMS
  - `DB_TYPE=postgresql` для production deployments
  - `DB_TYPE=sqlite` для development (backward compatible)
  - Асинхронный драйвер `asyncpg` для высокой производительности
  - `psycopg2-binary` для Alembic migrations
  
- **Connection Pooling** — эффективное управление соединениями
  - `AsyncAdaptedQueuePool` с настраиваемыми параметрами
  - `DB_POOL_SIZE=5` (base connections)
  - `DB_MAX_OVERFLOW=10` (additional connections under load)
  - `DB_POOL_TIMEOUT=30` (connection acquisition timeout)
  - `DB_POOL_RECYCLE=3600` (connection refresh after 1 hour)
  - `DB_POOL_PRE_PING=true` (health check before use)
  
- **Performance Indexes** — 11 новых индексов для оптимизации
  - `ingestion_state`: idx_ingestion_source_id
  - `raw_messages`: idx_raw_source_ref, idx_raw_channel_id, idx_raw_source_channel, idx_raw_date
  - `processed_documents`: idx_processed_source_ref, idx_processed_channel_id
  - `topics`: idx_topics_channel_id
  - `agent_registry`: idx_agents_type, idx_agents_active, idx_agents_type_active

##### Engine Factory

- **Universal Engine Creation** — `tg_parser/storage/engine_factory.py`
  - `create_engine_from_settings()` — автоматический выбор SQLite/PostgreSQL
  - `create_sqlite_engine_config()` — SQLite с NullPool
  - `create_postgres_engine_config()` — PostgreSQL с QueuePool
  - `get_pool_status()` — мониторинг состояния connection pool
  - Password masking для безопасного логирования
  
- **Database Class Refactoring** — обновлен для engine factory
  - `Database.from_settings(settings)` — рекомендуемый способ
  - Backward compatible с `DatabaseConfig`
  - Автоматический выбор backend

##### Migration Tools

- **SQLite → PostgreSQL Migration Script** — `scripts/migrate_sqlite_to_postgres.py`
  - Автоматическая миграция всех 3 БД (ingestion, raw, processing)
  - `--dry-run` режим для тестирования
  - `--verify` для проверки record counts
  - Детальная статистика и progress reporting
  - Error handling с продолжением миграции
  - Поддержка до 12 таблиц
  
- **Alembic PostgreSQL Support** — обновлен `migrations/env.py`
  - Автоматическое определение DB_TYPE из settings
  - PostgreSQL URL building
  - Environment variable override (`ALEMBIC_DATABASE_URL`)
  - Backward compatible с SQLite

##### Docker Compose Production

- **Production-Ready Setup** — обновлен `docker-compose.yml`
  - PostgreSQL service (postgres:16-alpine)
  - Health checks для PostgreSQL
  - Volumes для persistence (`postgres_data`)
  - Connection pool configuration
  - Network isolation (`tg_parser_network`)
  
- **Development Configuration** — новый `docker-compose.dev.yml`
  - SQLite backend для локальной разработки
  - Упрощенная конфигурация
  - Быстрый старт

##### Enhanced Health Checks

- **Database Metrics** — расширен `/health` endpoint
  - `type`: sqlite или postgresql
  - `pool`: connection pool status (type, size, checked_out, overflow)
  - `latency_ms`: database response time
  - PostgreSQL-specific: host, port, database, pool_size
  
- **Pool Monitoring** — real-time pool metrics
  - Количество активных соединений
  - Overflow connections
  - Pool health status

#### Changed

- **Settings** — новые PostgreSQL параметры:
  - `db_type`: sqlite или postgresql
  - `db_host`, `db_port`, `db_name`, `db_user`, `db_password`
  - `db_pool_size`, `db_max_overflow`, `db_pool_timeout`
  - `db_pool_recycle`, `db_pool_pre_ping`
  
- **Health Checks** — обновлены для PostgreSQL:
  - Автоматическое определение database type
  - Pool metrics для PostgreSQL
  - Таблица count для обоих backends

#### Documentation

- **PRODUCTION_DEPLOYMENT.md** — новый полный production guide (500+ lines)
  - Server setup (Ubuntu 22.04)
  - PostgreSQL configuration
  - Docker Compose deployment
  - SSL/TLS setup (Nginx reverse proxy)
  - Monitoring (Prometheus, CloudWatch, Datadog)
  - Backup strategy (automated daily backups)
  - Troubleshooting guide
  - Security checklist
  
- **MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md** — новый migration guide (400+ lines)
  - Когда мигрировать (decision matrix)
  - Pre-migration checklist
  - Пошаговая инструкция
  - Verification procedures
  - Rollback strategy
  - Troubleshooting
  - FAQ (10+ вопросов)
  
- **README.md** — обновлен с PostgreSQL setup
  - Database Setup section (новый)
  - SQLite vs PostgreSQL comparison
  - Quick start для обоих backends
  
- **ENV_VARIABLES_GUIDE.md** — 11 новых DB_* переменных
  - Полная документация PostgreSQL settings
  - Connection pool parameters
  - Рекомендации для development/production
  
- **ENV Templates** — 3 новых файла:
  - `env.example` — общий пример
  - `env.development.example` — SQLite configuration
  - `env.production.example` — PostgreSQL configuration

#### Tests

- **30 новых тестов** для PostgreSQL:
  - `tests/test_postgres_integration.py` (20 тестов):
    - Engine factory (6 тестов)
    - Connection pool (4 теста)
    - PostgreSQL operations (4 теста)
    - Settings validation (3 теста)
    - Health checks (2 теста)
    - Meta test (1 тест)
  - `tests/test_postgres_concurrency.py` (10 тестов):
    - Concurrent writes без deadlocks (3 теста)
    - Pool stress tests (2 теста)
    - E2E с PostgreSQL (2 теста)
    - Migration script tests (2 теста)
    - Meta test (1 тест)
- **1 тест обновлен** для PostgreSQL support:
  - `test_phase3d_advanced.py::test_check_database_missing_file`
- **Общее количество тестов**: **435** (было 405)
- **Test pass rate**: **100%** (435/435 passing)

#### Performance

- **Connection Pool**: < 10ms overhead для получения connection
- **Concurrent Writes**: 5+ processes без deadlocks
- **Migration Speed**: < 5 минут для 1000 сообщений
- **Index Performance**: 2-10x ускорение queries на больших данных
- **Test Execution**: 50.34s для всех 435 тестов

#### Migration Notes

##### Для новых пользователей:
```bash
# Production: PostgreSQL (рекомендуется)
DB_TYPE=postgresql
docker-compose up -d

# Development: SQLite (по умолчанию)
DB_TYPE=sqlite
```

##### Для существующих пользователей:
```bash
# 1. Backup
cp *.sqlite backups/

# 2. Setup PostgreSQL
docker-compose up -d postgres

# 3. Migrate data
python scripts/migrate_sqlite_to_postgres.py --verify

# 4. Switch
DB_TYPE=postgresql
```

#### Breaking Changes

**NONE** — Полная обратная совместимость:
- SQLite продолжает работать как раньше
- Все ENV переменные опциональны
- Default: `DB_TYPE=sqlite`

#### See Also

- `PRODUCTION_DEPLOYMENT.md` — production deployment guide
- `MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md` — database migration guide
- `ENV_VARIABLES_GUIDE.md` — все DB_* переменные
- `docs/notes/START_PROMPT_SESSION24_PRODUCTION.md` — план Session 24

---

## [3.1.0-alpha.2] - 2025-12-29

### 🎯 v3.1.0-alpha.2 - Structured Logging & GPT-5 Support (Session 23)

Production hardening release with structured JSON logging and GPT-5 Responses API support.

#### Added

##### Structured Logging (structlog)

- **JSON Logging Support** — production-ready structured logs
  - `LOG_FORMAT=json` для production (structured JSON, one per line)
  - `LOG_FORMAT=text` для development (human-readable, colored)
  - `LOG_LEVEL` configuration (DEBUG/INFO/WARNING/ERROR/CRITICAL)
  
- **Request ID Propagation** — корреляция логов
  - `request_id` в каждом логе API запросов
  - Автогенерация или использование заголовка `X-Request-ID`
  - Context vars для прокидывания через async границы
  
- **Structured Metadata** — все логи содержат структурированные поля
  - Timestamp, level, logger, event name
  - Дополнительные поля: method, path, duration_ms, error_type и др.
  - jq-friendly формат для фильтрации и анализа

##### GPT-5 / Responses API Support

- **Responses API Integration** — поддержка GPT-5.* моделей
  - Автоматический routing: `/v1/responses` для `gpt-5.*`, `/chat/completions` для остальных
  - `reasoning.effort` параметр: minimal/low/medium/high
  - `verbosity` параметр: low/medium/high
  
- **Configuration** — новые ENV переменные:
  - `LLM_REASONING_EFFORT` (default: low)
  - `LLM_VERBOSITY` (default: low)
  
- **Backward Compatible** — `gpt-4o-mini` и другие модели работают как раньше

##### RetrySettings Integration (Tech Debt from Session 22)

- **Pipeline Integration** — `retry_settings` используется в retry логике
  - Exponential backoff с cap: `min(base * 2^(attempt-1), max)`
  - Jitter для рандомизации: `delay + random(0, delay * jitter)`
  - Конфигурируемо через ENV (`RETRY_*` переменные)

#### Changed

- **Logging** — мигрировано на structlog:
  - `tg_parser.api.main` — structlog logger
  - `tg_parser.api.middleware.logging` — structlog + request_id binding
  - `tg_parser.processing.pipeline` — все логи structured
  - `tg_parser.processing.llm.openai_client` — structlog
  
- **OpenAIClient** — рефакторинг для GPT-5:
  - `_is_gpt5_model()` — detection метод
  - `_generate_chat_completions()` — для GPT-4 и старше
  - `_generate_responses_api()` — для GPT-5.*
  - `reasoning_effort` и `verbosity` в `__init__`

#### Documentation

- **ENV_VARIABLES_GUIDE.md** — полный справочник переменных окружения
  - Все LOG_*, RETRY_*, GPT-5 параметры
  - Примеры для development и production
  - jq рецепты для фильтрации JSON логов
  
- **LLM_SETUP_GUIDE.md** — обновлена секция про GPT-5
  - Описание Responses API
  - Планируемые изменения в Session 23 (completed)

#### Tests

- **12 новых тестов**:
  - `tests/test_logging.py` (7 тестов) — JSON/text format, request_id, context vars
  - `tests/test_gpt5_responses_api.py` (9 тестов) — routing, payload, response parsing
  - `tests/test_retry_settings.py` (9 тестов) — validation, ENV loading, integration
- Общее количество тестов: **393+** (было 381)

#### Migration Notes

- **Logging**: Установите `LOG_FORMAT=json` в production, `LOG_LEVEL=INFO`
- **GPT-5**: Используйте `LLM_MODEL=gpt-5.2` (или gpt-5-mini/gpt-5-nano)
- **Retry**: Настройте через `RETRY_*` переменные (опционально)
- **Backward Compatible**: Существующие конфигурации работают без изменений

#### See Also

- `ENV_VARIABLES_GUIDE.md` — справочник переменных окружения
- `docs/notes/START_PROMPT_SESSION23_LOGGING_GPT5.md` — план Session 23

---

## [3.1.0-alpha.1] - 2025-12-29

### 🔧 v3.1.0-alpha.1 - Foundation & Tech Debt (Session 22)

Foundation release focusing on database migrations and configuration improvements.

#### Added

##### Database Migrations (Alembic)

- **Alembic Integration** — полная поддержка версионирования схемы БД
  - Multi-database support для 3 независимых SQLite баз
  - Initial миграции с полными DDL схемами
  - Отдельные `alembic_version_{db_name}` таблицы для каждой БД
  - Динамическая настройка `version_locations` в `env.py`

- **CLI Commands `db`** — управление миграциями:
  - `tg-parser db upgrade` — применить миграции
  - `tg-parser db downgrade` — откатить миграции
  - `tg-parser db current` — показать текущую версию
  - `tg-parser db history` — история миграций
  - `tg-parser db stamp` — пометить версию

##### Configuration

- **RetrySettings** — конфигурируемые параметры retry через ENV:
  - `RETRY_MAX_ATTEMPTS` (default: 3, range: 1-10)
  - `RETRY_BACKOFF_BASE` (default: 1.0, range: 0.1-60.0)
  - `RETRY_BACKOFF_MAX` (default: 60.0, range: 1.0-300.0)
  - `RETRY_JITTER` (default: 0.3, range: 0.0-1.0)

#### Changed

- **`init` command** — обновлена для использования Alembic миграций с fallback на DDL
- **Documentation** — обновлена структура docs:
  - Архивированы устаревшие документы → `docs/notes/archive/`
  - Создан новый `docs/notes/current-state.md` для v3.0.0
  - Добавлен `SESSION22_SUMMARY.md`

#### Dependencies

- `alembic>=1.13` — database migrations

#### Tests

- **8 новых тестов** в `tests/test_migrations.py`:
  - Migration upgrade tests (3 databases)
  - Migration downgrade tests (3 databases)
  - Multi-database independence test
  - Version table per database test
- Общее количество тестов: **381** (было 373)

#### Migration Notes

- Alembic infrastructure готова для staging deployment
- Миграции работают базово, требуют финализации для production
- `init` команда автоматически применяет миграции
- Для существующих БД рекомендуется использовать `db stamp` для синхронизации

#### Known Limitations

- Миграции пока создают только version tables
- Основные таблицы создаются через fallback DDL
- Требуется дополнительная отладка для полного применения миграций (Session 23)

---

## [3.0.0] - 2025-12-28

### 🎉 v3.0.0 Release - Multi-Agent Architecture

This is the first stable release of the v3.0 Multi-Agent Architecture. See [MIGRATION_GUIDE_v2_to_v3.md](MIGRATION_GUIDE_v2_to_v3.md) for upgrade instructions.

#### Key Features

- **Multi-Agent Architecture** — OrchestratorAgent, ProcessingAgent, TopicizationAgent, ExportAgent
- **Agent State Persistence** — сохранение состояния агентов, истории задач, статистики
- **Agent Observability** — CLI команды `agents`, API endpoints, архивация истории
- **HTTP API v2** — FastAPI с Auth, Rate Limiting, Webhooks, Prometheus Metrics
- **Background Scheduler** — автоматическая очистка и health checks
- **Hybrid Mode** — agent + v1.2 pipeline для адаптивной обработки
- **373+ тестов** — 100% проходят

### Added

#### E2E Integration Tests (Session 21 Phase 3 Finalization)

- **7 новых E2E тестов**:
  - `test_full_cli_workflow` — полный CLI workflow с persistence
  - `test_full_api_workflow` — полный API workflow с TestClient
  - `test_handoff_workflow` — тестирование handoff протокола
  - `test_archive_workflow` — тестирование архивации истории
  - `test_multi_agent_e2e_workflow` — multi-agent pipeline E2E
  - `test_multi_agent_workflow_execution` — workflow execution через orchestrator
  - `test_multi_agent_registry_persistence_sync` — синхронизация registry с persistence

#### Documentation

- **MIGRATION_GUIDE_v2_to_v3.md** — полное руководство по миграции с v2.x на v3.0
- Обновлён README.md с ссылками на Migration Guide

### Tests

- Общее количество тестов: **373** (было 366)
- Все тесты проходят ✅

---

## [3.0.0-alpha.4] - 2025-12-28

### Added

#### Advanced Features (Session 20 Phase 3D) ⭐

- **Prometheus Metrics** (`/metrics` endpoint):
  - HTTP request metrics (count, latency, size)
  - Agent task metrics (count, duration, status)
  - LLM request metrics (provider, model, tokens)
  - Job metrics (active, total)
  - Custom metric helper functions

- **Background Scheduler** (APScheduler):
  - Periodic cleanup of expired records
  - Periodic health checks
  - Configurable intervals
  - Graceful shutdown

- **Health Checks v2**:
  - `GET /status/detailed` — detailed component health
  - `GET /scheduler` — scheduler status and tasks
  - Real database connectivity check
  - LLM provider ping
  - Agent registry status
  - Scheduler status

### Configuration

- `METRICS_ENABLED` — enable Prometheus metrics (default: true)
- `SCHEDULER_ENABLED` — enable background scheduler (default: true)
- `SCHEDULER_CLEANUP_INTERVAL_HOURS` — cleanup interval (default: 24)
- `SCHEDULER_HEALTH_CHECK_INTERVAL_MINUTES` — health check interval (default: 5)
- `OLLAMA_BASE_URL` — Ollama server URL (default: http://localhost:11434)

### Dependencies

- `prometheus-fastapi-instrumentator>=7.0`
- `apscheduler>=3.10`

### Tests

- **26 новых тестов** в `tests/test_phase3d_advanced.py`
- Общее количество тестов: **366** (было 340)
- Все тесты проходят ✅

### Documentation

- Создан `docs/notes/SESSION20_PHASE3D_COMPLETE.md`

---

## [3.0.0-alpha.3] - 2025-12-28

### Added

#### Agent Observability (Session 19 Phase 3C) ⭐
- **CLI группа `agents`**: новые команды для мониторинга агентов
  - `agents list` — список всех агентов с фильтрами (--type, --active)
  - `agents status <name>` — статистика агента (--days для периода)
  - `agents history <name>` — история задач (--limit, --errors)
  - `agents cleanup` — очистка истёкших записей (--dry-run, --archive)
  - `agents handoffs` — статистика handoff'ов (--stats, --agent)
  - `agents archives` — список архивных файлов
- **API Endpoints (Agent Observability)**:
  - `GET /api/v1/agents` — список агентов с метаданными
  - `GET /api/v1/agents/{name}` — информация об агенте
  - `GET /api/v1/agents/{name}/stats` — статистика агента за период
  - `GET /api/v1/agents/{name}/history` — история задач с пагинацией
  - `GET /api/v1/agents/stats/handoffs` — статистика handoff'ов
- **AgentHistoryArchiver**: архивация истёкших записей
  - Экспорт в NDJSON.gz формат
  - Поддержка task_history и handoff_history
  - Автоматическая очистка после архивации
  - Список архивов с метаданными
- **Pydantic Response Models**: типизированные ответы API
  - `AgentListResponse`, `AgentInfoResponse`
  - `AgentStatsResponse`, `TaskHistoryResponse`
  - `HandoffStatsResponse`

### Configuration
- `AGENT_ARCHIVE_ENABLED` — включить архивацию (default: false)
- `AGENT_ARCHIVE_PATH` — путь для архивов (default: ./data/archives)

### Tests
- **15 новых тестов** в `tests/test_agents_observability.py`
- Общее количество тестов: **340** (было 325)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION19_PHASE3C_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION20_PHASE3D.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, README.md, CHANGELOG.md
- Обновлены: tests/README.md, docs/notes/README.md

---

## [3.0.0-alpha.2] - 2025-12-28

### Added

#### Agent State Persistence (Session 18 Phase 3B) ⭐
- **AgentPersistence Layer**: unified интерфейс для работы с persistence
  - Сохранение состояния агентов при регистрации
  - Восстановление статистики при рестарте
  - Полное хранение input/output задач с TTL
  - Агрегированная статистика по дням
- **AgentStateRepo**: хранение метаданных и статистики агентов
  - Сохранение capabilities, model, provider
  - Накопление total_tasks, total_errors, avg_processing_time
  - Автообновление при выполнении задач
- **TaskHistoryRepo**: полная история задач
  - Хранение полного input_json/output_json
  - Настраиваемый TTL через `expires_at`
  - Фильтрация по агенту, каналу, датам
  - Метод `cleanup_expired()` для очистки
- **AgentStatsRepo**: агрегированная статистика по дням
  - Ежедневные агрегаты: total_tasks, successful, failed
  - min/max/avg processing time
  - Сохраняется даже после очистки task_history
- **HandoffHistoryRepo**: история handoffs между агентами
  - Tracking статусов: pending → accepted → completed
  - Время обработки и ошибки
  - Статистика по парам агентов
- **Registry интеграция**:
  - `register_with_persistence()` — регистрация + сохранение + восстановление
  - `unregister_with_persistence()` — отмена + пометка inactive
  - `record_task_completion_with_persistence()` — запись в history + stats

### Database
- **4 новые таблицы** в `processing_storage.sqlite`:
  - `agent_states` — состояние агентов с метаданными и статистикой
  - `task_history` — полная история задач с TTL
  - `agent_stats` — ежедневная агрегированная статистика
  - `handoff_history` — история handoffs между агентами

### Configuration
- `AGENT_RETENTION_DAYS` — TTL для task_history (default: 14)
- `AGENT_RETENTION_MODE` — delete | export (default: delete)
- `AGENT_ARCHIVE_PATH` — путь для архивации
- `AGENT_STATS_ENABLED` — включить агрегацию статистики
- `AGENT_PERSISTENCE_ENABLED` — включить persistence

### Tests
- **25 новых тестов** в `tests/test_agent_persistence.py`
- Общее количество тестов: **325** (было 300)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION18_PHASE3B_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION19_PHASE3C.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, architecture.md, README.md, CHANGELOG.md

---

## [3.0.0-alpha.1] - 2025-12-28

### Added

#### Multi-Agent Architecture (Session 17 Phase 3A) ⭐
- **Base Agent Protocol**: стандартизированный интерфейс для всех агентов
  - `BaseAgent` абстрактный класс с lifecycle методами
  - `AgentInput`/`AgentOutput` типизированные контракты
  - `AgentCapability`/`AgentType` enum'ы для классификации
- **Agent Registry**: централизованное управление агентами
  - Регистрация/отмена регистрации агентов
  - Поиск по типу и capabilities
  - Статистика выполнения задач
  - Health checks
- **Handoff Protocol**: обмен данными между агентами
  - `HandoffRequest`/`HandoffResponse` структуры
  - `HandoffStatus` для отслеживания состояния
  - Приоритеты и контекст передачи
- **OrchestratorAgent**: координация workflow
  - Управление workflow'ами
  - Маршрутизация задач к специализированным агентам
  - Lifecycle management для всех агентов
- **Specialized Agents**:
  - `ProcessingAgent` — очистка текста, извлечение тем/entities, routing (simple/deep)
  - `TopicizationAgent` — кластеризация документов по темам
  - `ExportAgent` — экспорт в NDJSON/JSON форматы
- **CLI флаг `--multi-agent`**: активация multi-agent режима
  - `tg-parser process --channel @lab --multi-agent`
  - `tg-parser process --channel @lab --multi-agent --provider anthropic`

### Architecture
- Hybrid подход: Specialized Agents (Variant A) + элементы Agentic Workflow (Variant C)
- Routing внутри ProcessingAgent для адаптивной обработки
- Расширяемая архитектура через Agent Registry

### Tests
- **42 новых теста** в `tests/test_multi_agent.py`
- Общее количество тестов: **300** (было 258)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION17_PHASE3A_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION18_PHASE3B.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, architecture.md, README.md
- Обновлена пользовательская документация: USER_GUIDE.md, pipeline.md, LLM_SETUP_GUIDE.md, QUICKSTART_v1.2.md

---

## [2.0.0-alpha.4] - 2025-12-28

### Added

#### API Production (Session 16 Phase 2F) ⭐
- **API Key Authentication**: защита endpoints через X-API-Key header
  - Конфигурируемые ключи через `API_KEYS` environment variable
  - Режим разработки (auth опционален) и production (auth обязателен)
- **Rate Limiting**: защита от перегрузки через slowapi
  - Настраиваемые лимиты для `/process`, `/export` endpoints
  - По умолчанию: 10/min для process, 20/min для export
- **Webhooks**: уведомления о завершении задач
  - HMAC-SHA256 подписи для верификации
  - Retry с экспоненциальным backoff
  - Стандартный payload для job completion/failure
- **Request Logging**: структурированное логирование с X-Request-ID
  - Автоматическая генерация UUID для каждого запроса
  - Сохранение пользовательского X-Request-ID
  - Duration tracking
- **Persistent Job Storage**: SQLite хранилище для job state
  - `Job` модель с полным lifecycle tracking
  - `JobRepo` интерфейс (порт) и SQLite реализация
  - `JobStore` singleton для API routes
  - Таблица `api_jobs` в processing_storage.sqlite
- **Configurable CORS**: CORS_ORIGINS через environment

### Tests
- **38 новых тестов** (22 в test_api_security.py, 16 в test_job_storage.py)
- Общее количество тестов: **258** (было 219)
- Исправлено зависание тестов из-за незакрытых SQLite соединений
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION16_PHASE2F_COMPLETE.md`
- Обновлены CHANGELOG.md, DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, README.md

---

## [2.0.0-alpha.3] - 2025-12-28

### Added

#### Hybrid Agent Mode (Session 15 Phase 2E) ⭐
- **Pipeline Tool**: v1.2 pipeline как инструмент агента
  - `process_with_pipeline` — глубокая обработка через проверенный pipeline
  - `PipelineResult` — структурированный результат с metadata
  - Автоматический fallback на basic processing при недоступности pipeline
  - On-demand создание pipeline если не передан в контексте
- **AgentContext update**: добавлено поле `pipeline` для hybrid mode
- **TGProcessingAgent update**: 
  - Новый параметр `use_pipeline_tool` для включения pipeline tool
  - Новый параметр `pipeline` для передачи экземпляра pipeline
  - Динамическое формирование инструкций агента для hybrid mode
- **CLI флаг `--hybrid`**: включает v1.2 pipeline как tool агента
  - `tg-parser process --channel @lab --agent --hybrid` — basic + pipeline (4 tools)
  - `tg-parser process --channel @lab --agent --agent-llm --hybrid` — LLM + pipeline (2 tools)
- **InMemoryProcessedDocumentRepo**: in-memory репозиторий для on-demand pipeline

### Performance
- **Hybrid режим**: адаптивная обработка — простые сообщения через basic tools, сложные через pipeline
- Agent выбирает оптимальный инструмент в зависимости от сложности сообщения

### Tests
- **32 новых теста** в `tests/test_agents_phase2e.py`
- Общее количество тестов: **219** (было 187)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION15_PHASE2E_COMPLETE.md`
- Обновлены CHANGELOG.md, DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md

---

## [2.0.0-alpha.2] - 2025-12-27

### Added

#### Agents Integration (Session 14 Phase 2C) ⭐
- **LLM-Enhanced Tools**: глубокий семантический анализ через LLM
  - `analyze_text_deep` — комплексный анализ с key_points и sentiment
  - `extract_topics_llm` — семантическое извлечение тем
  - `extract_entities_llm` — NER через LLM
- **AgentContext**: dataclass для передачи LLM client в tools
- **DeepAnalysisResult**: расширенная модель с key_points и sentiment
- **CLI флаги**:
  - `--agent` — использовать agent-based processing
  - `--agent-llm` — включить LLM-enhanced tools
- **Multi-provider support**: агент поддерживает OpenAI, Anthropic, Gemini, Ollama
- **Quality comparison script**: `scripts/compare_agents_pipeline.py`

### Performance
- **Agent Basic**: ~0.3ms/сообщение (1000x быстрее pipeline) без LLM вызовов
- Автоматический fallback к pattern matching при отсутствии LLM

### Tests
- **14 новых тестов** для Phase 2C
- Общее количество тестов: **187** (было 174)
- Все тесты проходят ✅

### Documentation
- Обновлён USER_GUIDE.md с секцией об Agent-based Processing
- Обновлён README.md с новыми CLI флагами
- Создан SESSION14_PHASE2C_COMPLETE.md

---

## [2.0.0-alpha.1] - 2025-12-27

### Added

#### HTTP API (Session 14 Phase 2A) ⭐
- **FastAPI HTTP API**: полноценный REST API для TG_parser
- **8 endpoints** в трёх группах:
  - `/health`, `/status` — health checks и статус системы
  - `/api/v1/process`, `/api/v1/status/{job_id}`, `/api/v1/jobs` — управление обработкой
  - `/api/v1/export`, `/api/v1/export/status/{job_id}`, `/api/v1/export/download/{job_id}` — экспорт
- **CLI команда `tg-parser api`**: запуск сервера с параметрами `--port`, `--host`, `--reload`
- **OpenAPI/Swagger**: автодокументация на `/docs` и `/redoc`
- **CORS middleware**: поддержка cross-origin запросов
- **Job-based processing**: асинхронная обработка с отслеживанием статуса

#### OpenAI Agents SDK PoC (Session 14 Phase 2B) ⭐
- **Новый модуль `tg_parser/agents/`**: интеграция с OpenAI Agents SDK
- **TGProcessingAgent**: агент для обработки сообщений с тремя tools:
  - `clean_text` — очистка и нормализация текста
  - `extract_topics` — извлечение тем и генерация summary
  - `extract_entities` — извлечение сущностей (email, URL, phone, hashtags, etc.)
- **Function tools**: используют `@function_tool` декоратор из agents SDK
- **Batch processing**: `process_batch_with_agent()` с настройкой concurrency

### Tests
- **24 теста для HTTP API** в `tests/test_api.py`
- **24 теста для Agents** в `tests/test_agents.py`  
- Общее количество тестов: 174 (было 126)
- Все тесты проходят ✅

### Dependencies
- `openai-agents>=0.6` — OpenAI Agents SDK
- `fastapi>=0.115`, `uvicorn>=0.32` — уже были для API

## [1.2.0] - 2025-12-27

### Added

#### Multi-LLM Support ⭐
- **AnthropicClient**: поддержка Claude models (claude-sonnet-4-20250514)
- **GeminiClient**: поддержка Google Gemini models (gemini-2.0-flash-exp, gemini-1.5-pro)
- **OllamaClient**: поддержка локальных LLM через Ollama (qwen3:8b, llama3.2, mistral, etc.)
- **Factory**: `create_llm_client()` для создания клиентов по провайдеру
- CLI флаги `--provider` и `--model` для выбора LLM
- Environment variables: `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`

#### Performance
- **Parallel processing**: флаг `--concurrency` для параллельной обработки сообщений
- `ProcessingPipelineImpl._process_batch_parallel()` с `asyncio.Semaphore`
- Реальное ускорение: до 3x при `--concurrency 5` для облачных провайдеров

#### Docker & CI/CD
- **Dockerfile**: multi-stage build для production (370MB image)
- **docker-compose.yml**: compose файл с опциональным Ollama service
- **GitHub Actions CI**: автоматическое тестирование, линтинг, Docker build
- Markdown link checking в CI

#### PromptLoader Integration
- `ProcessingPipelineImpl` использует `PromptLoader` по умолчанию
- Model settings (temperature, max_tokens) загружаются из YAML
- Fallback на hardcoded промпты если YAML не найден

#### Documentation
- **TESTING_RESULTS_v1.2.md**: полный отчёт о тестировании
- **MIGRATION_GUIDE_v1.1_to_v1.2.md**: руководство по миграции
- Обновлённые README.md и USER_GUIDE.md с Multi-LLM примерами

### Fixed
- **Anthropic JSON parsing**: Claude иногда возвращает JSON в markdown блоках (`\`\`\`json`), добавлена функция `extract_json_from_response()` для корректного парсинга
- **Anthropic model name**: обновлено с устаревшего `claude-3-5-sonnet-20241022` на актуальное `claude-sonnet-4-20250514`
- **docker-compose.yml**: удалён устаревший атрибут `version`

### Changed
- `tg_parser/processing/pipeline.py`: обновлена `create_processing_pipeline()` для Multi-LLM
- `tg_parser/cli/process_cmd.py`: добавлены параметры `provider`, `model`, `concurrency`
- `tg_parser/cli/app.py`: обновлена команда `process` с новыми флагами
- `tg_parser/config/settings.py`: добавлен `gemini_api_key`

### Performance Benchmarks

| Provider | Model | Throughput | Quality |
|----------|-------|------------|---------|
| OpenAI | gpt-4o-mini | 0.120 msg/s | Good |
| Anthropic | claude-sonnet-4-20250514 | 0.121 msg/s | Best (90% entities) |
| Gemini | gemini-2.0-flash-exp | 0.342 msg/s | Great (fastest!) |
| Ollama | qwen3:8b | 0.024 msg/s | Good |

### Tests
- Добавлено 23 новых теста в `tests/test_llm_clients.py`
- Общее количество тестов: 126 (было 103)
- Все тесты проходят ✅
- Протестированы все 4 LLM провайдера на реальных данных

## [1.1.0] - 2025-12-26

### Added
- **Configurable Prompts (YAML)**: Prompts can now be customized via YAML files in `prompts/` directory
  - `prompts/processing.yaml` - Processing prompts
  - `prompts/topicization.yaml` - Topicization prompts
  - `prompts/supporting_items.yaml` - Supporting items prompts
  - `prompts/README.md` - Documentation for YAML format
- **PromptLoader class** (`tg_parser/processing/prompt_loader.py`): 
  - Loads prompts from YAML with fallback to defaults
  - Caching support
  - Helper methods: `get_system_prompt()`, `get_user_template()`, `get_model_settings()`
- **`--retry-failed` flag** for `process` command: Retry only failed messages
- **`list_all()` method** in ProcessedDocumentRepo: Export all channels without filter
- **`get_channel_usernames()` method** in IngestionStateRepo: Get channel username mappings
- **Improved LLM response validation**: 
  - Validates required fields
  - Fills defaults for optional fields
  - Normalizes entity confidence scores
- **18 new tests** for PromptLoader (total: 103 tests)

### Fixed
- Export command now works without `--channel` filter
- Telegram URLs now correctly include channel usernames when available

### Changed
- Dependencies: added `PyYAML>=6.0`

### Technical Debt Resolved
- Removed TODO at `export_cmd.py:82` (list_all implemented)
- Removed TODO at `export_cmd.py:99` (usernames implemented)

## [1.0.0] - 2025-12-25

### Added
- Initial production-ready release
- **Ingestion Pipeline**: Telethon-based Telegram message collection
  - Posts and comments support
  - Incremental and snapshot modes
  - Cursor-based pagination
- **Processing Pipeline**: LLM-based message processing
  - Text cleaning and normalization
  - Entity extraction
  - Topic detection
  - Language detection
- **Topicization Pipeline**: Message clustering into topics
  - Singleton and cluster topics
  - Anchor-based topic cards
  - Supporting items with relevance scores
- **Export System**:
  - `kb_entries.ndjson` - Knowledge base entries
  - `topics.json` - Topic catalog
  - `topic_<id>.json` - Detailed topic files
- **CLI Commands**:
  - `init` - Initialize databases
  - `add-source` - Add ingestion source
  - `ingest` - Run ingestion
  - `process` - Run processing
  - `topicize` - Run topicization
  - `export` - Export artifacts
  - `run` - One-shot full pipeline
- **Storage**:
  - SQLite-based storage (3 databases)
  - Idempotent operations
  - Cursor management

### Technical
- 85 tests passing
- 99.76% success rate on 846 real messages
- Pydantic v2 domain models
- Async/await architecture
- Type hints throughout

