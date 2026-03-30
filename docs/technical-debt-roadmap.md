# Технический долг: аудит и план закрытия

> Составлен 2026-03-30 после завершения S1–S3.
> Обновлён 2026-03-30 после завершения D1.

## Статус выполнения

| Сессия | Задачи | Статус |
|--------|--------|--------|
| S1 | MCP logging (stderr redirect) | **Выполнено** |
| S2+S2.5 | Management tools + remove_channel | **Выполнено** |
| S3 | DB optimization (batch stats, count_by_channel) | **Выполнено** |
| S4 | Quick wins: тесты TestListTopicsTool + get_channel_stats на stats_repos | **Выполнено** |
| S4+ | Fix TestCLIModeDispatch (positional vs keyword args) | **Выполнено** |
| S5 | E2E fixture fix + N+1 запросы (list_topics, search, coverage) | **Выполнено** |
| S6 | Coverage bug + remove_channel cleanup + hardcoded values + export tests + type:ignore + pytest-cov | **Выполнено** |
| S7 | Singleton Database + unified logging + lazy formatting | **Выполнено** |
| D1 | MCP Streamable HTTP transport + bearer auth + Docker | **Выполнено** |

---

## Оставшийся технический долг

### ~~1. Singleton Database (S7a)~~ — ✅ ЗАКРЫТО

Закрыто в S7. `Database` теперь singleton: engines создаются один раз, все context managers
в `db_context.py` переиспользуют его. Lifecycle управляется в `api/main.py` lifespan и
`mcp_server.py`. `_wiring.py` упрощён до `get_processing_session_factory()` / `get_agent_persistence()`.

### ~~2. Дубликат в add_source_cmd.py (S7b)~~ — ✅ ЗАКРЫТО

Закрыто в S7. Теперь использует `ingestion_state_repo()` из `db_context.py`.

### ~~3. Смешанное логирование (S7c)~~ — ✅ ЗАКРЫТО

Закрыто в S7. Все 44 файла переведены на `structlog`. Исключения: `config/logging.py` (инфра)
и `mcp_server.py` (оставлен `import logging` для `_configure_mcp_logging()`; модульный
logger — structlog).

### ~~4. f-string в logger-вызовах (S7d)~~ — ✅ ЗАКРЫТО

Закрыто в S7. ~160 вызовов заменены на lazy `%s` formatting. `typer.echo()` не затронуты.

---

### ~~D1. MCP Streamable HTTP транспорт~~ — ✅ ЗАКРЫТО

Закрыто в D1. MCP-сервер теперь поддерживает Streamable HTTP транспорт для удалённого развёртывания.
Реализовано: lifespan для Database singleton (исправлен баг с неинициализированной DB для HTTP-транспортов),
BearerTokenVerifier для bearer-токен аутентификации, factory-функция `create_mcp_server()`,
CLI `--host`/`--port` параметры, Docker Compose `mcp` сервис, 13 новых тестов в `test_mcp_http.py`.
SSE transport убран (deprecated с апреля 2026).

---

### 5. Bare `except Exception` без reraise — НИЗКИЙ приоритет

**Файлы:**
- `services/channel_service.py:120` — в цикле по каналам (оправдано: per-channel fallback)
- `mcp_server.py:744, 759` — в background pipeline (оправдано: fire-and-forget)
- `services/pipeline_service.py:193` — в pipeline runner
- `storage/engine_factory.py:205` — при чтении pool status
- `storage/sqlalchemy/schemas/processing_storage.py:248` — при парсинге

**Решение:** Проанализировать каждый случай, добавить более конкретные типы исключений или хотя бы `logger.exception()` где его нет.

**Оценка:** 30 минут, низкий риск.

---

### 6. Покрытие тестами — ИНФОРМАЦИОННЫЙ

Из 98 модулей в `tg_parser/`:
- **~20** имеют прямые тесты (по имени файла)
- Реально покрытие выше: многие модули тестируются через integration/E2E тесты (`test_e2e_pipeline.py`, `test_processing_pipeline.py`, `test_llm_clients.py`)

**Непокрытые зоны, заслуживающие тестов:**
- `services/channel_service.py` — `get_channel_stats()` (тестируется только `get_all_channel_stats`)
- `api/auth.py` + `api/middleware/rate_limit.py` — security middleware
- `services/background_scheduler.py` — scheduler lifecycle
- `agents/` (большинство) — agent orchestration, handoffs

Это не блокер, но повышает уверенность при рефакторинге (особенно S7).

---

## Рекомендуемый порядок (оставшееся)

| Порядок | Задача | Оценка | Риск |
|---------|--------|--------|------|
| 1 | Bare except → typed exceptions | 30 мин | Низкий |
| 2 | Расширение тестового покрытия | По мере необходимости | Нулевой |

Все высокоприоритетные элементы техдолга закрыты в S1–S7.
