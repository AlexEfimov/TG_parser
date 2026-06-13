# Тесты TG_parser

**Default suite (2026-06):** ~2800 passed, ~345 skipped, 2 deselected (`integration` marker).

Подробный разбор skip-причин: [`docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`](../docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md).

## Режимы прогона

### Default — CI / быстрая проверка

Соответствует `pyproject.toml` → `addopts = "-m 'not integration'"`. PG- и testcontainers-тесты **пропускаются**.

```bash
.venv/bin/python -m pytest -q
```

### PR standard — обязателен для app-code (bot / MCP / API / repos)

Разблокирует ~329 Postgres-gated тестов. Требует Postgres на `localhost:5432`, БД `tg_parser_test` (conftest сам делает `alembic upgrade head`).

```bash
TEST_POSTGRES=1 .venv/bin/python -m pytest -q
```

Ожидание (2026-06-13, `main`): **~3222 passed**, ~15 skipped (testcontainers; confirm-flow concurrency TD closed in Wave A — see BUG_LOG § TD-confirm-flow-concurrency-integration), 2 deselected.

### Максимальный локальный прогон (рекомендуется перед релизом / крупным merge)

Postgres + ephemeral testcontainers (миграции, alembic smoke). Docker daemon обязателен.

```bash
TEST_POSTGRES=1 TEST_TESTCONTAINERS=1 .venv/bin/python -m pytest -q
```

Ожидание: **~3234 passed**, **0 skipped** (the confirm-flow concurrency TD skip in `test_bot_confirm_flow.py` was replaced by a deterministic sequenced test in Wave A), 2 deselected.

Инфраструктура: контейнер `tg_parser_postgres` (`pgvector/pgvector:pg17`) на `:5432` — достаточно для `TEST_POSTGRES=1`; для testcontainers нужен только Docker.

### Absolute max — integration + compose (opt-in, live deps)

Снимает `integration`-filter и включает live OpenAI / docker-compose harness. Запускать только когда нужны эти поверхности.

```bash
TEST_POSTGRES=1 TEST_TESTCONTAINERS=1 \
  OPENAI_API_KEY=sk-... \
  COMPOSE_INTEGRATION=1 \
  .venv/bin/python -m pytest -m "" -q
```

`@pytest.mark.integration` (2 теста): `test_agents.py::TestAgentIntegration`, `test_compose_pipeline_dispatch_integration.py`.

### Параллельный прогон (pytest-xdist)

При прогоне в несколько воркеров (`-n auto`) все воркеры делят одну БД
`tg_parser_test`. Сессионная фикстура `_alembic_initialized_test_db`
сериализует разрушительный `DROP SCHEMA` + `alembic upgrade` через
Postgres advisory-lock (`pg_advisory_lock`, ключ `_SCHEMA_INIT_LOCK_KEY`):
первый воркер делает reset, остальные видят схему уже на head-ревизии и
пропускают reset, а не гонятся за ней (BUG-056). Lock всегда снимается в
`finally`, в т.ч. при ошибке инициализации.

### Точечный прогон (watchlist / F11)

```bash
.venv/bin/python -m pytest tests/test_watchlist_score.py tests/test_watchlist_service.py -k watchlist -q

# + repo integration:
TEST_POSTGRES=1 .venv/bin/python -m pytest \
  tests/test_f11_watchlist_repo.py tests/test_watchlist_score.py tests/test_watchlist_service.py -q
```

## Запуск тестов (прочее)

```bash
# Verbose
.venv/bin/python -m pytest -v

# Покрытие
.venv/bin/python -m pytest --cov=tg_parser --cov-report=term-missing

# Skip-reasons (диагностика)
.venv/bin/python -m pytest -rs -q

# Конкретный файл
.venv/bin/python -m pytest tests/test_e2e_pipeline.py -v
```

## Структура тестов

### Core модули
- **test_ids.py** — канонизация идентификаторов (TR-IF-5, TR-41, TR-IF-4, TR-61)
- **test_telegram_url.py** — резолюция Telegram URL (TR-58/TR-65)
- **test_models.py** — валидация Pydantic моделей против контрактов (TR-IF-1)

### Processing
- **test_processing_pipeline.py** — LLM processing pipeline
- **test_llm_clients.py** — Multi-LLM клиенты (OpenAI, Anthropic, Gemini, Ollama)
- **test_prompts.py** — YAML prompts loading

### Storage
- **test_storage_integration.py** — SQLite репозитории

### E2E
- **test_e2e_pipeline.py** — полный pipeline тест

### API (v2.0)
- **test_api.py** — FastAPI endpoints
- **test_api_auth.py** — API authentication
- **test_api_webhooks.py** — Webhook callbacks
- **test_api_jobs.py** — Persistent job storage

### Agents (v2.0-v3.0)
- **test_agents.py** — TGProcessingAgent, function tools
- **test_hybrid_agent.py** — Hybrid mode (agent + pipeline)
- **test_multi_agent.py** — Multi-Agent Architecture
- **test_agent_persistence.py** — Agent State Persistence (Phase 3B)
- **test_agents_observability.py** — Agent Observability (Phase 3C)
- **test_phase3d_advanced.py** — Advanced Features (Phase 3D) ⭐ NEW

## Покрытие по фазам

| Фаза | Тесты | Описание |
|------|-------|----------|
| v1.2 | ~126 | Multi-LLM, Pipeline |
| Phase 2A-2C | ~62 | HTTP API, Agents PoC |
| Phase 2E-2F | ~70 | Hybrid, Auth, Webhooks |
| Phase 3A | ~42 | Multi-Agent Architecture |
| Phase 3B | ~25 | Agent Persistence |
| Phase 3C | ~15 | Agent Observability |
| Phase 3D | ~26 | Prometheus, Scheduler, Health Checks |
