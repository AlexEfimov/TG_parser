# План реализации сессий S1–S3: MCP Management & Quality

## Общая цель

Превратить MCP-сервер из read-only интерфейса к базе знаний в инструмент управления каналами, сохраняя стабильность и производительность.

---

## S1: Исправление логирования MCP-сервера

**Приоритет:** Критический (блокер)
**Объём:** Маленький (~30 минут)
**Затрагиваемые файлы:** `tg_parser/mcp_server.py`

### Проблема

MCP-протокол использует stdio — JSON-RPC идёт по stdout. При вызове инструментов (например `list_channels`) lazy-импорты подтягивают `engine_factory.py`, который использует `structlog.get_logger()`. Без явной конфигурации structlog пишет через `PrintLoggerFactory` → `print()` → **stdout**. Логи вроде `2026-03-30 [info] creating_postgres_engine ...` попадают в stdout и ломают JSON-парсинг на стороне клиента.

Claude Desktop выдаёт: `Unexpected non-whitespace character after JSON at position 4`.

### Решение

Добавить в `mcp_server.py` функцию `_configure_mcp_logging()`, которая:
1. Перенаправляет structlog на stderr (`PrintLoggerFactory(file=sys.stderr)`)
2. Очищает стандартные logging handlers и вешает `StreamHandler(sys.stderr)`
3. Устанавливает уровень WARNING для root logger (подавить шум `creating_postgres_engine` при каждом вызове)
4. Вызывается в `if __name__ == "__main__"` перед `mcp.run()`

### Критерий приёмки

- `echo '<JSON-RPC initialize + list_channels>' | python -m tg_parser.mcp_server 2>/dev/null` выдаёт **только** валидный JSON, без примесей логов
- Claude Desktop не показывает предупреждение о JSON
- Cursor MCP по-прежнему работает
- Существующие тесты проходят

### Тесты

- `test_mcp_logging_stderr` — проверить что при вызове инструмента stdout содержит только JSON-RPC
- Убедиться что существующие тесты в `tests/test_mcp_server.py` проходят

---

## S2: MCP Management Tools

**Приоритет:** Высокий (основная фича)
**Объём:** Средний (1–2 сессии)
**Затрагиваемые файлы:** `tg_parser/mcp_server.py`, `tests/test_mcp_management.py`
**Спецификация:** `docs/mcp-management-tools-spec.md`

### Подзадачи

#### S2.1: Pydantic-схемы
Добавить `AddChannelResult`, `ChannelStatusResult`, `PipelineSourceStatus`, `PipelineStatusResult`, `TriggerPipelineResult` в `mcp_server.py`.

#### S2.2: `add_channel`
- Параметры: `channel_id`, `channel_username`, `include_comments`, `batch_size`
- Логика: нормализация `channel_id`, upsert в `sources`, лимит active sources
- Тесты: new/update/normalize/limit

#### S2.3: `pause_channel` / `resume_channel`
- Параметры: `channel_id`
- Логика: идемпотентная смена статуса, `resume` сбрасывает `fail_count`/`last_error` для `error`
- Тесты: active→paused, paused→paused (idempotent), not_found, error→active (reset)

#### S2.4: `get_pipeline_status`
- Параметры: `channel_id` (опциональный фильтр)
- Логика: переиспользовать `scheduler_service.get_scheduler_status()`
- Тесты: all sources, filtered, empty

#### S2.5: `trigger_pipeline`
- Параметры: `channel_id`, `force`
- Логика: проверка source exists + active, `asyncio.create_task()` для `run_full_pipeline()` + `run_embedding()`, защита от дублирования через `_running_pipelines: set`
- Тесты: success, not_found, paused, duplicate

#### S2.6: Обновление instructions и документации
- FastMCP instructions в конструкторе
- INSTRUCTIONS.md для MCP-клиентов

### Критерий приёмки

- Все 5 новых инструментов работают в Claude Desktop
- Полный цикл: `add_channel` → `trigger_pipeline` → `get_pipeline_status` → `search_knowledge_base`
- Все существующие инструменты продолжают работать
- 15+ тестов покрывают новый код

### Зависимости

- **Требует S1** (без фикса логирования тестирование в Claude Desktop невозможно)
- Не требует изменений в существующих сервисах — всё через `db_context`, `pipeline_service`, `scheduler_service`

---

## S3: Оптимизация DB-вызовов в MCP

**Приоритет:** Средний (качество/производительность)
**Объём:** Средний (1 сессия)
**Затрагиваемые файлы:** `tg_parser/services/channel_service.py`, `tg_parser/mcp_server.py`, возможно `tg_parser/services/db_context.py`

### Проблема

Вызов `list_channels` в MCP-сервере проходит по циклу каналов и для каждого вызывает `get_channel_stats(src.channel_id)`. Каждый вызов `get_channel_stats` открывает собственный `Database` контекст через `Database.from_settings()` → создаёт 3 engine'а (ingestion, raw, processing). При 10 каналах — 30+ engine'ов за один запрос.

Аналогичная проблема может быть в `get_pipeline_status` (из S2.4).

### Решение

Варианты (выбрать в начале сессии):

**Вариант A: Batch-версия `get_channel_stats`.**
Создать `get_channels_stats(channel_ids: list[str])`, которая открывает один `Database` контекст и собирает статистику для всех каналов за один проход.

**Вариант B: Shared DB context в `list_channels`.**
Передавать открытые репозитории в `get_channel_stats()` через параметр, а не создавать каждый раз новые.

**Вариант C: Глобальный/cached engine pool.**
`Database.from_settings()` возвращает один и тот же engine при повторных вызовах с одинаковыми параметрами (singleton pattern).

### Критерий приёмки

- `list_channels` для 10 каналов создаёт не более 3 engine'ов (один per db_name)
- Время ответа `list_channels` уменьшается (измерить до/после)
- Все существующие тесты проходят
- REST API `/api/v1/channels` по-прежнему работает

### Зависимости

- Не блокируется S1 или S2, но логически лучше делать после S2
- Затрагивает `channel_service` — нужно проверить что REST API эндпоинт `GET /api/v1/channels/{channel_id}/stats` продолжает работать

---

## Диаграмма зависимостей

```
S1 (логирование)
  │
  ▼
S2 (management tools)
  │
  ▼
S3 (DB оптимизация)
```

S1 → S2: строгая зависимость (блокер для тестирования)
S2 → S3: мягкая зависимость (удобнее оптимизировать когда все инструменты написаны)
