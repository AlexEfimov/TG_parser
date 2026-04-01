# Стартовый промпт: Закрытие технического долга

## Задача

Выполни план закрытия техдолга из `@docs/notes/TECH_DEBT_PLAN.md`. Работай строго по рекомендуемой последовательности — от Фазы 1 до Фазы 3. Фаза 4 опциональна.

## Ключевые файлы

- **План:** `docs/notes/TECH_DEBT_PLAN.md` — полная карта: что, где, как, в каком порядке
- **Roadmap:** `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — обновить раздел "Техдолг" после завершения

## Порядок работы

### Фаза 1 (~30 мин): Quick wins

**TD-1:** Исправить 2 красных теста:

1. `tests/test_e2e_pipeline.py::test_run_command_with_skip_options` — мок `create_llm_client` не настраивает `generate_with_usage`, pipeline получает coroutine вместо `LLMResponse`. Фикс: использовать `ProcessingMockLLM()` или замокать `generate_with_usage` с `return_value=LLMResponse(text=..., input_tokens=0, output_tokens=0)`.

2. `tests/test_retry_settings.py::test_retry_settings_integration_with_pipeline` — `Mock()` не awaitable, а pipeline вызывает `await generate_with_usage()`. Фикс: субклассировать `LLMClient` с failing `generate()`, или `mock_llm.generate_with_usage = AsyncMock(side_effect=Exception("LLM error"))`.

Понимание цепочки вызовов:
- `pipeline.process_message()` → `await self.llm_client.generate_with_usage(...)` → `LLMResponse`
- `LLMClient.generate_with_usage()` (в `processing/ports.py`) делегирует в `self.generate()`
- `topicization._discover_single_batch()` → `await self.llm_client.generate_with_usage(...)` → `llm_response.text` → `extract_json_from_response()`

**TD-4:** 3 мелких улучшения:
- `mcp_server.py:435`: `except Exception: pass` → `except Exception: logger.warning(...)`
- `ingestion/orchestrator.py:247`: аналогично
- `mcp_server.py`: проверить `BearerTokenVerifier` наследование

**После:** `pytest tests/ -x --tb=short` — убедиться 0 failures. Коммит.

### Фаза 2 (~1 час): Typed exceptions в ядре

Заменить `except Exception` на конкретные типы в порядке приоритета:

1. `storage/sqlalchemy/schemas/processing_storage.py`, `storage/engine_factory.py` → `SQLAlchemyError`, `ProgrammingError`, `OperationalError`
2. `mcp_server.py` (2 места) → `SQLAlchemyError`
3. `services/topicization_service.py`, `channel_service.py`, `pipeline_service.py`, `processing_service.py`, `export_service.py` → `SQLAlchemyError`, `RuntimeError`, `OSError`
4. `processing/topicization.py`, `processing/pipeline.py` → `ValueError`, `KeyError`, `json.JSONDecodeError`, `SQLAlchemyError`

**Принципы:**
- CLI boundary (`cli/app.py`) — НЕ трогать, оставить `except Exception`
- Job/scheduler boundary — НЕ трогать
- Если handler делает `except Exception as e: ... raise` — можно оставить
- После каждой группы файлов запускать `pytest tests/ -x --tb=short`

**После:** коммит.

### Фаза 3 (~1 час): Тестовое покрытие

1. **TopicLinkRepo integration test** — добавить в `tests/test_storage_integration.py`: `upsert_batch`, `get_by_topic_id`, `list_all` с реальной in-memory SQLite или test-postgres.

2. **Topicization prompts** — добавить тесты для `build_topicization_prompt`, `build_merge_prompt` и других builders в `tests/test_topicization.py` или новый файл.

3. **CLI smoke tests** — добавить CliRunner тесты для `db --help`, `scheduler --help`, `link-topics --help` (проверка Typer wiring).

4. **Оставшиеся typed exceptions** — группы #6 (scheduler), #8 (health/API), #9 (ingestion), #10 (agents) из плана.

**После:** коммит. Обновить ROADMAP (раздел техдолга и метрики тестов).

## Контроль качества

- После каждой фазы: `pytest tests/ -v --tb=short` — 0 failures
- После Фазы 2: `rg "except Exception" tg_parser/ --count-matches` — число должно снизиться с ~91 до ~30 (boundary handlers)
- После Фазы 3: `pytest tests/ --co -q | tail -1` — число тестов ≥ 740

## Не делать

- Не менять бизнес-логику
- Не рефакторить архитектуру
- Не добавлять новые фичи
- Не трогать `except Exception` в CLI top-level и job/scheduler boundary handlers
