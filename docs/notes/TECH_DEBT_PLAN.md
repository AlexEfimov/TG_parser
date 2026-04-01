# План закрытия технического долга

**Дата:** 2 апреля 2026
**Контекст:** Cross-dev завершён и протестирован. 729 тестов (711 passed, 2 pre-existing failures, 16 skipped). 5405 docs, 401 тема, 264 topic links, 14 MCP tools.

---

## TD-1: Исправить 2 pre-existing test failures (~15 мин)

**Приоритет: высокий** — красные тесты маскируют реальные регрессии.

Оба сбоя имеют одну корневую причину: тесты мокают `generate()`, а pipeline вызывает `generate_with_usage()`.

### 1.1 `test_e2e_pipeline::test_run_command_with_skip_options`

- **Ошибка:** `TypeError: expected string or bytes-like object, got 'coroutine'`
- **Причина:** Тест патчит `create_llm_client` и возвращает `AsyncMock` с настроенным `generate`, но pipeline вызывает `generate_with_usage()` → возвращается не `LLMResponse`, а auto-mock coroutine → `extract_json_from_response` передаёт coroutine в `re.search`.
- **Файл:** `tests/test_e2e_pipeline.py`
- **Фикс:** Использовать `ProcessingMockLLM()` (как в `test_run_command_full_pipeline`) или замокать `generate_with_usage` с `return_value=LLMResponse(text='{"result":...}', input_tokens=0, output_tokens=0)`.

### 1.2 `test_retry_settings::test_retry_settings_integration_with_pipeline`

- **Ошибка:** `TypeError: object Mock can't be used in 'await' expression`
- **Причина:** Тест создаёт `Mock()` (не `AsyncMock`), настраивает `generate = AsyncMock(side_effect=...)`, но pipeline вызывает `await generate_with_usage()` — а это обычный `Mock`, который не awaitable.
- **Файл:** `tests/test_retry_settings.py`
- **Фикс:** Либо субклассировать `LLMClient` с `async def generate` → `raise Exception("LLM error")`, либо `mock_llm.generate_with_usage = AsyncMock(side_effect=Exception("LLM error"))` и исправить assertion на `generate_with_usage.call_count`.

### Связанные файлы для понимания:

- `tg_parser/processing/ports.py` — `LLMClient.generate_with_usage()` (делегирует в `generate()`)
- `tg_parser/processing/pipeline.py` — `extract_json_from_response()`, `process_message()`
- `tg_parser/processing/topicization.py` — `generate_topics()`, `_discover_single_batch()`

---

## TD-2: Typed exceptions — 91 `except Exception` → конкретные типы (~2-3 часа)

**Приоритет: средний** — улучшает отладку, не влияет на функционал.

0 bare `except:` (хорошо!), но 91 `except Exception` в 35 файлах.

### Принципы:

1. **CLI boundary** (`cli/app.py`, 13 occurrences) — оставить `except Exception` (осознанный top-level catch)
2. **Job/scheduler boundary** — оставить `except Exception` с обязательным логированием
3. **Внутренний код** — заменить на конкретные типы

### По группам файлов:

| # | Группа | Файлы | ~Count | Целевые типы |
|---|--------|-------|--------|-------------|
| 1 | **Storage/DB** | `storage/sqlalchemy/schemas/processing_storage.py`, `storage/engine_factory.py` | 5 | `SQLAlchemyError`, `ProgrammingError`, `OperationalError`, `AttributeError` |
| 2 | **LLM clients** | `processing/llm/anthropic_client.py`, `ollama_client.py`, `gemini_client.py` | 3 | `httpx.HTTPError`, `httpx.TimeoutException` (re-raise после лога — можно оставить) |
| 3 | **Topicization** | `processing/topicization.py` | 6 | `ValueError`, `KeyError`, `json.JSONDecodeError`, `SQLAlchemyError`, `ValidationError` |
| 4 | **Pipeline** | `processing/pipeline.py` | 4 | `RuntimeError`, `SQLAlchemyError`, `json.JSONDecodeError` |
| 5 | **Services** | `services/topicization_service.py`, `services/channel_service.py`, `services/pipeline_service.py`, `services/processing_service.py`, `services/export_service.py` | 10 | `SQLAlchemyError`, `RuntimeError`, `OSError`, `ValueError` |
| 6 | **Scheduler** | `services/scheduler_service.py`, `services/background_scheduler.py` | 8 | `SQLAlchemyError`, `RuntimeError`, `OSError` |
| 7 | **MCP server** | `mcp_server.py` | 2 | `SQLAlchemyError` + заменить silent `pass` на `logger.warning` |
| 8 | **Health/API** | `api/health_checks.py`, `api/routes/health.py`, `api/routes/process.py`, `api/routes/export.py`, `api/middleware/logging.py` | 12 | `SQLAlchemyError`, `httpx.HTTPError`, `ConnectionError` |
| 9 | **Ingestion** | `ingestion/orchestrator.py`, `ingestion/telegram/telethon_client.py` | 5 | `telethon.errors.RPCError`, `OSError` + убрать silent `pass` |
| 10 | **Agents** | `agents/*.py` | 12 | `RuntimeError`, `ValueError` |
| 11 | **Prompt loader** | `processing/prompt_loader.py` | 1 | `OSError`, `UnicodeDecodeError` |
| 12 | **CLI (boundary)** | `cli/app.py`, `cli/db_cmd.py`, `cli/init_db.py` | 16 | Оставить + добавить `subprocess.SubprocessError` в db_cmd |

### Рекомендуемый порядок (по impact):

1. Storage/DB (#1) — самые конкретные типы, простая замена
2. MCP server (#7) — 2 места + quick win с silent pass
3. Services (#5) — ядро бизнес-логики
4. Topicization (#3) + Pipeline (#4) — обработка LLM-ответов
5. Остальные по мере времени

---

## TD-3: Тестовое покрытие — закрыть gaps (~1-2 часа)

**Приоритет: средний** — повышает уверенность при рефакторинге.

| # | Gap | Модуль | Текущее покрытие | Действие |
|---|-----|--------|-----------------|----------|
| 1 | **TopicLinkRepo DB-тест** | `storage/sqlalchemy/topic_link_repo.py` | Только моки | Добавить integration тест: upsert_batch, get_by_topic_id, list_all (в `test_storage_integration.py`) |
| 2 | **Topicization prompts** | `processing/topicization_prompts.py` | Только `build_incremental_discover_prompt` | Добавить тесты для `build_topicization_prompt`, `build_merge_prompt` и др. |
| 3 | **Ingestion service** | `services/ingestion_service.py` | Только e2e через pipeline | Добавить unit-тесты с мокированным Telethon |
| 4 | **Pipeline service** | `services/pipeline_service.py` | Через scheduler/MCP моки | Добавить тест оркестрации pipeline stages |
| 5 | **CLI wiring** | `cli/db_cmd.py`, `cli/scheduler_cmd.py` | 0 | Добавить CliRunner smoke-тесты (--help, basic dispatch) |

### Рекомендуемый порядок:

1. TopicLinkRepo (#1) — самый полезный для cross-channel фичи
2. Topicization prompts (#2) — защищает от промпт-регрессий
3. CLI smoke (#5) — quick win
4. Остальные по мере времени

---

## TD-4: Мелкие улучшения (~15 мин)

| # | Задача | Файл | Оценка |
|---|--------|------|--------|
| 1 | Silent `except Exception: pass` → `logger.warning` | `mcp_server.py:435` | 5 мин |
| 2 | Silent `except Exception: pass` → `logger.warning` в flush | `ingestion/orchestrator.py:247` | 5 мин |
| 3 | `BearerTokenVerifier` — проверить/обновить наследование | `mcp_server.py` | 5 мин |

---

## Рекомендуемая последовательность выполнения

```
Фаза 1 (30 мин, quick wins):
  TD-1: Исправить 2 красных теста
  TD-4: 3 мелких улучшения
  → Коммит: "fix: repair 2 pre-existing test failures + silence-to-warning"

Фаза 2 (1 час, typed exceptions — ядро):
  TD-2 #1: Storage/DB (5 occurrences)
  TD-2 #7: MCP server (2 occurrences)
  TD-2 #5: Services (10 occurrences)
  TD-2 #3+#4: Topicization + Pipeline (10 occurrences)
  → Коммит: "refactor: typed exceptions in storage, services, processing"

Фаза 3 (1 час, тесты + оставшиеся exceptions):
  TD-3 #1: TopicLinkRepo integration test
  TD-3 #2: Topicization prompts tests
  TD-3 #5: CLI smoke tests
  TD-2 остальные группы (#6, #8, #9, #10)
  → Коммит: "test: TopicLinkRepo integration, prompt builders, CLI smoke"

Фаза 4 (опционально, по мере времени):
  TD-3 #3: Ingestion service unit tests
  TD-3 #4: Pipeline service orchestration tests
  TD-2 #11, #12: Prompt loader, CLI boundary
  → Коммит: "test: ingestion service, pipeline service orchestration"
```

---

## Метрики успеха

| Метрика | До | После |
|---------|-----|-------|
| Failing tests | 2 | 0 |
| `except Exception` (non-boundary) | ~60 | ~15 |
| Modules без тестов | 5 gaps | ≤ 2 gaps |
| Total tests | 729 | ~750+ |
