# Технический долг: аудит и план закрытия

> Составлен 2026-03-30 после завершения S1–S3.
> Обновлён 2026-03-30 после завершения D2.

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
| D2 | Production Docker: .dockerignore, Dockerfile, healthchecks, env template, docs | **Выполнено** |

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

### ~~D2. Production Docker~~ — ✅ ЗАКРЫТО

Закрыто в D2. Docker-инфраструктура доведена до production-ready:
`.dockerignore` (исключает .git, .venv, tests, data из build context),
Dockerfile оптимизирован (deps из `pyproject.toml`, без editable mode, CMD = API сервер),
`tg_parser` сервис запускает API + scheduler вместо `--help`,
healthchecks для всех сервисов (postgres, API, MCP),
API порт проброшен (8000), `env.production.example` дополнен MCP-настройками,
`PRODUCTION_DEPLOYMENT.md` обновлён (v2.0: MCP, архитектура, подключение агентов).

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

### 7. Конфигурация reverse-proxy живёт вне репозитория — ОТКРЫТО (2026-08-07)

Публичный контур reference-деплоя обслуживает **системный nginx**: три vhost'а, терминация TLS, правило `403` на `/metrics`, WebSocket/SSE-настройки для MCP. Ничего из этого не под версионным контролем, не проходит ревью и не попадает в бэкап вместе с кодом — потеря хоста означает потерю конфигурации периметра и восстановление по памяти.

Обнаружено при закрытии [BUG-090](notes/BUG_LOG.md). Инварианты, которым конфигурация обязана удовлетворять, теперь зафиксированы в [`SERVER_ARCHITECTURE.md`](SERVER_ARCHITECTURE.md) § Reverse proxy — но это спецификация, а не бэкап.

Варианты, между которыми надо выбрать (owner-решение, ADR-уровень):

| Вариант | Плюс | Минус |
|---|---|---|
| Внести конфиги в репозиторий (`ops/nginx/`) + процедура применения | Полный контроль версий и ревью | Host-специфика в публичном репо — против конвенции `SERVER_ARCHITECTURE.md` о приватном runbook'е |
| Складывать дамп `nginx -T` + `certbot certificates` в приватный бэкап оператора на каждом деплое | Дёшево, закрывает бо́льшую часть риска, ничего не кладёт в git | Не даёт ревью изменений |
| Оставить как есть | — | Риск сохраняется |

**Промежуточная мера — ВЫПОЛНЕНА 2026-08-07.** Первый дамп снят и лежит в приватном бэкапе оператора: `~/backups/nginx/reverse-proxy-config-<TS>.tar.gz` (27 файлов, режим `600`). Внутри — `nginx.conf`, `conf.d/`, все `sites-available/`, список фактически включённых симлинков, certbot-конфиги продления, `options-ssl-nginx.conf`, инвентарь живых сертификатов (issuer/сроки/SAN) и состояние сервисов, плюс `MANIFEST.txt` с процедурой восстановления. Приватные ключи **не** сохраняются намеренно: они root-only и не нужны — certbot перевыпускает сертификаты из конфигов продления.

Процедура (sudo-free — беспарольного sudo на хосте нет, а `nginx -T` и `certbot certificates` требуют root; исходные файлы несут ту же информацию и читаемы всем) описана в [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md) § Reverse proxy.

**Что этим НЕ закрыто:** дамп разовый — автоматического обновления нет, и при следующей правке vhost'а архив устареет молча. Ревью изменений тоже не появляется. Оба пробела закрываются только выбором варианта из таблицы выше.

---

## Рекомендуемый порядок (оставшееся)

| Порядок | Задача | Оценка | Риск |
|---------|--------|--------|------|
| 1 | Bare except → typed exceptions | 30 мин | Низкий |
| 2 | Конфиги reverse-proxy вне репозитория (§7) | Owner-решение | Средний (потеря периметра при потере хоста) |
| 3 | Расширение тестового покрытия | По мере необходимости | Нулевой |

Все высокоприоритетные элементы техдолга закрыты в S1–S7.
