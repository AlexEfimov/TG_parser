# Тесты TG_parser

> **Про цифры в этом файле.** До 2026-08-12 здесь стояли точные счётчики от 2026-06, разошедшиеся с реальностью примерно на +900 в обоих режимах: `tests/` тронули 82 коммита, а числа никто не обновлял. Снимок протухает — поэтому ниже даётся **порядок величины с датой** и команда, которой узнают текущее значение, а не обещание конкретного числа. Тот же приём, по которому `SERVER_ARCHITECTURE.md` описывает периметр инвариантами и командами чтения вместо снимка конфига.
>
> Порядок величины на **2026-08-12**: default ≈ 3.7k passed, PR-standard ≈ 4.2k passed. Точное число: `.venv/bin/python -m pytest -q | tail -1`.

Подробный разбор skip-причин: [`docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`](../docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md).

## Предпосылки, без которых числа не воспроизводятся

Замерено 2026-08-12 на чистой машине. Обе позиции невидимы на dev-боксе, где уже поднят контейнер `tg_parser_postgres` и заполнен `.env`, — именно поэтому они годами не попадали в этот файл:

| Нужно | Почему | Без этого |
|---|---|---|
| **Postgres на `localhost:5432`, БД `tg_parser_test`, расширение `vector`** — даже для default-режима | Фикстура `test_db` ([`conftest.py:367`](conftest.py)) **не** привязана к `TEST_POSTGRES`: гейт стоит только в `postgres_settings` ([`conftest.py:402`](conftest.py)). То есть «PG-тесты сами скипаются» верно не для всех | `43 failed, 99 errors` — все `Connection refused` |
| **Любые непустые `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`** (моки годятся, CI подставляет `sk-test-key`) | Два теста строят реальный LLM-клиент | `2 failed` с `ValueError: OpenAI API key required` — `test_bug023_topic_rejection.py::test_run_topicization_surfaces_rejection_breakdown_in_stats` и `test_incremental_topicization.py::test_incremental_llm_checkpoint_persists_previous_batches_on_failure` |

Полный набор переменных, которым пользуется CI, — в job `test` файла [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## Режимы прогона

### Default — CI / быстрая проверка

Соответствует `pyproject.toml` → `addopts = "-m 'not integration'"`. Testcontainers-тесты **пропускаются**; PG-тесты, помеченные через `postgres_settings`, тоже — но живой Postgres всё равно нужен (см. предпосылки выше).

```bash
.venv/bin/python -m pytest -q
```

### PR standard — обязателен для app-code (bot / MCP / API / repos)

Снимает гейт `postgres_settings` (~400 тестов на 2026-08-12). Postgres нужен и в default-режиме, так что разница между режимами — не «поднять БД», а только эта переменная; conftest сам делает `alembic upgrade head` под advisory-lock'ом.

```bash
TEST_POSTGRES=1 .venv/bin/python -m pytest -q
```

Ожидание (**2026-08-12**, `main`): ≈ **4.2k passed**, ~22 skipped, 2 deselected. Все остающиеся skip'ы — Docker/testcontainers-gated; при живом демоне их снимает `TEST_TESTCONTAINERS=1` (см. следующий режим).

### Максимальный локальный прогон (рекомендуется перед релизом / крупным merge)

Postgres + ephemeral testcontainers (миграции, alembic smoke). Docker daemon обязателен.

```bash
TEST_POSTGRES=1 TEST_TESTCONTAINERS=1 .venv/bin/python -m pytest -q
```

Ожидание: PR-standard плюс ~22 testcontainers-теста, **0 skipped**, 2 deselected.

Инфраструктура: контейнер `tg_parser_postgres` (`pgvector/pgvector:pg17`) на `:5432` — достаточно для `TEST_POSTGRES=1`; для testcontainers нужен только Docker. Нативная установка PostgreSQL 17 + `postgresql-17-pgvector` из PGDG равноценна для обоих PG-режимов и годится там, где Docker недоступен (проверено 2026-08-12); testcontainers без Docker недостижимы по определению, но их покрывает CI-job `Alembic Runtime Upgrade Smoke`.

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

Under a system Python without project deps (DF-1): missing `structlog` ignore-collects
watchlist import-set modules and skips any remaining collected tests (conftest loads without
eager `Settings`/`Database` so hooks still register); missing `pymorphy3` skips only
morphology suites (`test_watchlist_score/service/batch`) — bot/F11 wiring tests still run.
Message points to `.venv`. Always prefer `.venv/bin/python -m pytest` for real runs.

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

## Ориентирование в тестах

> **Почему здесь больше нет перечня файлов.** До 2026-08-12 в этой секции лежал рукописный список из 18 файлов, и **пять из них не существовали**: `test_prompts.py`, `test_api_webhooks.py`, `test_api_jobs.py`, `test_hybrid_agent.py` и `test_api_auth.py` (последний появился 2026-08-12). Перечислять файлы в тексте — значит дублировать то, что и так знает файловая система, и расходиться с ней при первом же переименовании. Ниже — области и способ найти нужное; список файлов даёт `ls tests/`.

Именование предсказуемо, поэтому поиск по нему быстрее чтения любого перечня:

| Что ищете | Как найти |
|---|---|
| Тесты конкретного бага | `ls tests/ \| grep -i bug0NN` — конвенция `test_bugNNN_*.py` |
| Тесты фичи | `ls tests/ \| grep -i f11` (F5-C → `f5c`, F4-B → `f4b`, и т.д.) |
| Кто трогает модуль | `rg -l "имя_модуля" tests/` |
| Кто **исполняет** функцию, а не мокает её | `rg -l "func_name" tests/` и затем отсеять `patch(...)` — разница неочевидна и уже стоила пропущенного покрытия (`get_channel_stats` мокался в 12 файлах и не исполнялся ни в одном; `technical-debt-roadmap.md` § 6) |

Тематические области, покрытые тестами: канонизация идентификаторов и резолюция Telegram-URL; валидация Pydantic-моделей против [`docs/contracts/`](../docs/contracts/); processing-пайплайн и LLM-клиенты четырёх провайдеров; репозитории и миграции; HTTP API с аутентификацией; MCP-инструменты; бот с его confirm-протоколом и пагинацией; watchlist-скоринг и морфология; топикизация с её concurrency-гардами; scheduler и его cron-хуки; наблюдаемость (метрики, alert-правила, Grafana-provisioning); compose-паритет env-переменных.

**Прогон по фазам** (историческая раскладка v1.2 → Phase 3D) снят как самостоятельная секция вместе с перечнем: те же счётчики, та же скорость протухания. История фаз живёт в [`CHANGELOG.md`](../CHANGELOG.md), где она датирована.
