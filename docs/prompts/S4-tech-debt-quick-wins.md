# Стартовый промпт: S4 — Quick wins (тесты + оптимизация get_channel_stats)

## Задача

Закрыть два элемента технического долга P0 из `docs/technical-debt-roadmap.md`:
1. Починить 5 сломанных тестов `TestListTopicsTool`
2. Перевести `get_channel_stats()` на `stats_repos()` + `count_by_channel()`

## Контекст

В S1–S3 были реализованы MCP management tools и оптимизация DB-вызовов. При добавлении пагинации в `list_topics` (S2) тесты не обновили — 5 тестов сломаны. Также `get_channel_stats()` (REST API) по-прежнему открывает 3 отдельных Database-контекста (9 engine create/dispose) на один запрос, хотя `stats_repos()` уже существует.

## Текущее состояние файлов

### `tests/test_mcp_server.py`

Класс `TestListTopicsTool` (5 тестов, строки ~265-329):
- `test_list_topics_returns_topics` — `len(result)` → TypeError, `result` теперь `TopicListResult`
- `test_list_topics_empty` — `result == []` → AssertionError
- `test_list_topics_filter_by_type` — `len(result)` → TypeError
- `test_list_topics_with_channel_id` — `len(result)` → TypeError
- `test_list_topics_respects_limit` — `len(result)` → TypeError

`list_topics` возвращает `TopicListResult(total, offset, limit, has_more, items)`.

### `tg_parser/services/channel_service.py`

`get_channel_stats()` (строки ~18-69):
- Открывает 3 отдельных `async with`: `ingestion_repos()`, `processing_repos()`, `embedding_repos()`
- Каждый создаёт свой `Database` → `init()` → 3 engine'а → `close()` → dispose
- Использует `list_by_channel()` + `len()` вместо `count_by_channel()`
- N+1 для coverage: `get_by_topic_id()` per card

`stats_repos()` уже существует в `db_context.py` — даёт `SAIngestionStateRepo`, `SARawMessageRepo`, `SAProcessedDocumentRepo`, `SATopicCardRepo`, `SATopicBundleRepo`, `SAEmbeddingRepo` в одном Database-контексте.

`count_by_channel()` уже реализован в `SARawMessageRepo` и `SAProcessedDocumentRepo` (добавлены в S3).

### `tg_parser/api/routes/channels.py`

REST-эндпоинт (строка ~72):
```python
@router.get("/channels/{channel_id}/stats", response_model=ChannelStatsResponse)
async def get_channel_stats(channel_id: str):
    from tg_parser.services.channel_service import get_channel_stats as _get_stats
    stats = await _get_stats(channel_id)
    return ChannelStatsResponse(**stats)
```

## Что нужно сделать

### S4.1: Починить TestListTopicsTool (5 тестов)

В `tests/test_mcp_server.py`:

1. Добавить `TopicListResult` в импорт из `tg_parser.mcp_server`
2. Обновить каждый тест:

**`test_list_topics_returns_topics`:**
```python
assert isinstance(result, TopicListResult)
assert result.total == 1
assert len(result.items) == 1
assert isinstance(result.items[0], TopicSummary)
assert result.items[0].id == card.id
assert result.items[0].title == "Test Topic"
assert result.items[0].type == "singleton"
assert result.items[0].items_count == 2
assert result.items[0].sources == ["ch"]
```

**`test_list_topics_empty`:**
```python
assert isinstance(result, TopicListResult)
assert result.total == 0
assert result.items == []
assert result.has_more is False
```

**`test_list_topics_filter_by_type`:**
```python
assert result.total == 1
assert len(result.items) == 1
assert result.items[0].title == "Singleton"
```

**`test_list_topics_with_channel_id`:**
```python
assert result.total == 1
assert len(result.items) == 1
```

**`test_list_topics_respects_limit`:**
```python
assert result.total == 5
assert len(result.items) == 2
assert result.has_more is True
```

### S4.2: Перевести get_channel_stats() на stats_repos()

В `tg_parser/services/channel_service.py`:

Переписать `get_channel_stats()`:
- Один `async with stats_repos()` вместо трёх отдельных контекстов
- `raw_repo.count_by_channel(channel_id)` вместо `raw_repo.list_by_channel()` + `len()`
- `proc_repo.count_by_channel(channel_id)` вместо `proc_repo.list_by_channel()` + `len()`
- Coverage: оставить `topic_card_repo.list_by_channel()` + `topic_bundle_repo.get_by_topic_id()` (N+1 фикс — задача S5c)
- Для coverage нужен `processed_count` (число) и `covered_refs` (set) → пересечение невозможно без source_refs. Использовать `proc_repo.count_by_channel()` для count, но для coverage по-прежнему нужен список processed source_refs. Два варианта:
  - a) Добавить `list_source_refs_by_channel()` в ProcessedDocumentRepo (лёгкий SELECT только source_ref)
  - b) Оставить `list_by_channel()` только для coverage calc, использовать `count_by_channel()` для основного счётчика

**Рекомендация:** Вариант (a) — добавить лёгкий метод.

Сигнатура `get_channel_stats()` и возвращаемый dict должны остаться прежними (обратная совместимость с REST API).

### Тестирование

```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_mcp_management.py -v
```

**Ожидаемый результат:** 0 failures (кроме, возможно, pre-existing проблем не связанных с S4).

Также проверить REST API тесты:
```bash
.venv/bin/python -m pytest tests/test_channels_routes.py -v
```

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `tests/test_mcp_server.py` | Обновить 5 тестов TestListTopicsTool, добавить TopicListResult в импорт |
| `tg_parser/services/channel_service.py` | Переписать `get_channel_stats()` на `stats_repos()` + count |
| `tg_parser/storage/ports.py` | (опционально) +`list_source_refs_by_channel()` в ProcessedDocumentRepo |
| `tg_parser/storage/sqlalchemy/processed_document_repo.py` | (опционально) SA-реализация `list_source_refs_by_channel()` |

**Другие файлы менять НЕ нужно.** Не трогать `mcp_server.py`, `db_context.py`, `database.py`.

## Чего НЕ делать

- **Не исправлять** N+1 в list_topics / search / coverage (это задачи S5)
- **Не менять** `get_all_channel_stats()` (он уже оптимизирован в S3)
- **Не трогать** Singleton Database (это S6)
- **Не менять** сигнатуру `get_channel_stats()` (REST API backward compat)

## Критерии приёмки

1. Все 5 тестов `TestListTopicsTool` проходят
2. `get_channel_stats()` открывает 1 Database вместо 3
3. `get_channel_stats()` использует `count_by_channel()` для raw/processed counts
4. REST API `GET /channels/{id}/stats` возвращает те же данные
5. Все существующие тесты не ломаются
