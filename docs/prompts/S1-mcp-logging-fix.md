# Стартовый промпт: S1 — Исправление логирования MCP-сервера

## Задача

Исправить MCP-сервер (`tg_parser/mcp_server.py`) так, чтобы при работе через stdio-транспорт в stdout попадал **только** JSON-RPC, а все логи шли в stderr.

## Контекст проблемы

MCP-сервер использует stdio-транспорт: JSON-RPC читается из stdin и пишется в stdout. При вызове любого инструмента (например `list_channels`) lazy-импорты подтягивают модули, использующие `structlog`. В частности `tg_parser/storage/engine_factory.py` (строка 15) использует `structlog.get_logger(__name__)` и логирует `creating_postgres_engine` / `engine_created` при каждом создании DB engine.

Проблема: structlog без явной конфигурации использует `PrintLoggerFactory`, который пишет через `print()` в **stdout**. Эти строки логов попадают в stdout и ломают JSON-RPC парсинг на стороне Claude Desktop:

```
{"jsonrpc":"2.0","id":1,"result":{...}}         ← корректный JSON-RPC
2026-03-30 14:06:48 [info] creating_postgres_engine ...  ← мусор в stdout
```

Claude Desktop выдаёт ошибку: `Unexpected non-whitespace character after JSON at position 4`.

Функция `configure_logging()` в `tg_parser/config/logging.py` существует, но:
- Вызывается **только** из `tg_parser/api/main.py` (REST API), не из MCP-сервера
- Даже она настраивает handler на `sys.stdout` (строка 79), а не на `sys.stderr`

## Что нужно сделать

### 1. Добавить функцию `_configure_mcp_logging()` в `tg_parser/mcp_server.py`

Функция должна:

1. **Перенаправить structlog на stderr:**
   ```python
   import structlog
   structlog.configure(
       logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
   )
   ```

2. **Перенаправить стандартный logging на stderr:**
   ```python
   import logging
   root = logging.getLogger()
   root.handlers.clear()
   handler = logging.StreamHandler(sys.stderr)
   handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
   root.addHandler(handler)
   ```

3. **Установить уровень WARNING** для root logger, чтобы подавить INFO-шум (`creating_postgres_engine` вызывается 30+ раз при `list_channels` — это не нужно в MCP-контексте):
   ```python
   root.setLevel(logging.WARNING)
   ```

### 2. Вызвать перед `mcp.run()`

В блоке `if __name__ == "__main__"` (строка 398-399 файла `mcp_server.py`):

```python
if __name__ == "__main__":
    _configure_mcp_logging()
    mcp.run()
```

**Важно:** функция должна вызываться **до** `mcp.run()`, но **после** всех импортов и определения инструментов (декораторы `@mcp.tool()` не логируют ничего в stdout при определении — проверено).

### 3. Проверить что `__main__.py` не нужен

В проекте нет `tg_parser/__main__.py`. Модуль запускается через `python -m tg_parser.mcp_server`, что вызывает `mcp_server.py` напрямую как `__main__`. Если `__main__.py` не существует — ничего делать не нужно.

## Файлы для изменения

| Файл | Что делать |
|---|---|
| `tg_parser/mcp_server.py` | Добавить `_configure_mcp_logging()` + вызов в entrypoint |

**Другие файлы менять НЕ нужно.** Не трогать `config/logging.py`, `engine_factory.py`, `api/main.py`.

## Тестирование

### Ручная проверка (обязательно)

Запустить MCP-сервер с тестовым JSON-RPC запросом и убедиться что stdout чистый:

```bash
cd /Users/alexanderefimov/TG_parser

# Тест 1: initialize — stdout должен содержать только JSON
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | .venv/bin/python -m tg_parser.mcp_server 2>/dev/null

# Тест 2: вызов инструмента list_channels — stdout должен содержать только JSON-RPC
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_channels","arguments":{}}}\n' \
  | .venv/bin/python -m tg_parser.mcp_server 2>/dev/null
```

**Ожидаемый результат:** каждая строка stdout — валидный JSON начинающийся с `{"jsonrpc"`. Никаких строк вида `2026-... [info]`.

### Unit-тест

Добавить тест в `tests/test_mcp_server.py` (или рядом). Тест должен:
1. Импортировать `_configure_mcp_logging` из `tg_parser.mcp_server`
2. Вызвать функцию
3. Проверить что `structlog.get_logger()` пишет в stderr, а не в stdout
4. Проверить что `logging.getLogger().handlers` содержат только stderr-handler

Паттерн:
```python
import io, sys

def test_mcp_logging_goes_to_stderr():
    from tg_parser.mcp_server import _configure_mcp_logging
    _configure_mcp_logging()

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = captured_stdout, captured_stderr

    try:
        import structlog
        structlog.get_logger().info("test_message")
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    assert "test_message" not in captured_stdout.getvalue()
    assert "test_message" in captured_stderr.getvalue()
```

### Проверка существующих тестов

```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_server.py -v
```

Все существующие тесты должны пройти без изменений.

## Чего НЕ делать

- **Не менять** `tg_parser/config/logging.py` — это общая конфигурация логирования для всего приложения, её handler на stdout используется REST API и CLI
- **Не менять** `tg_parser/storage/engine_factory.py` — логирование engine creation полезно для отладки, проблема в транспорте, а не в самих логах
- **Не менять** уровни логирования в отдельных модулях
- **Не добавлять** зависимостей
- **Не оптимизировать** количество DB engine'ов — это задача S3

## Критерии приёмки

1. ✅ `python -m tg_parser.mcp_server` с JSON-RPC запросами выдаёт на stdout **только** валидный JSON-RPC
2. ✅ Логи идут в stderr (видны при `2>log.txt`)
3. ✅ Claude Desktop не показывает предупреждение `Unexpected non-whitespace character after JSON`
4. ✅ Cursor MCP продолжает работать
5. ✅ Существующие тесты `tests/test_mcp_server.py` проходят
6. ✅ Новый тест `test_mcp_logging_goes_to_stderr` проходит
