# Стартовый промпт: S5 — E2E fixture fix + устранение N+1 запросов

## Задача

Закрыть элементы технического долга P1 из `docs/technical-debt-roadmap.md`:
1. Починить E2E fixture (FK violation, 7 заблокированных тестов)
2. Устранить N+1 в `list_topics` (bundle per card)
3. Устранить N+1 в `search` / `ask_question` (doc per hit)
4. Устранить N+1 в coverage calc (bundle per card)

## Контекст

В S4 были закрыты P0 quick wins: починены тесты TestListTopicsTool, get_channel_stats() переведён на stats_repos() + count_by_channel(). Также починены 2 теста TestCLIModeDispatch. Все 588 юнит-тестов проходят.

Остались N+1 паттерны в трёх местах и сломанная E2E fixture. Все изменения — оптимизационные, не меняют внешнего поведения API/MCP.

## Текущее состояние файлов

### `tests/test_e2e_pipeline.py`

Fixture `e2e_db` (строки 144-165) очищает таблицы перед каждым E2E тестом. Порядок DELETE в блоке `processing_storage_engine`:
```python
await conn.execute(text("DELETE FROM handoff_history"))
await conn.execute(text("DELETE FROM task_history"))
await conn.execute(text("DELETE FROM agent_stats"))
await conn.execute(text("DELETE FROM agent_states"))
await conn.execute(text("DELETE FROM topic_bundles"))
await conn.execute(text("DELETE FROM topic_cards"))
await conn.execute(text("DELETE FROM processing_failures"))
await conn.execute(text("DELETE FROM processed_documents"))  # строка 159 — FK violation!
await conn.execute(text("DELETE FROM api_jobs"))
```
`document_embeddings` ссылается на `processed_documents.source_ref` через FK. Таблица `document_embeddings` не очищается — при наличии данных строка 159 падает с `ForeignKeyViolationError`.

### `tg_parser/mcp_server.py`

`list_topics()` (строки 248-302):
```python
async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
    if channel_id:
        cards = await topic_card_repo.list_by_channel(channel_id)
    else:
        cards = await topic_card_repo.list_all()
    # ...
    page = cards[offset : offset + limit]
    summaries: list[TopicSummary] = []
    for card in page:
        bundle = await topic_bundle_repo.get_by_topic_id(card.id)  # N+1!
        items_count = len(bundle.items) if bundle else 0
        summaries.append(TopicSummary(...))
```

`TopicBundleRepo` имеет `list_by_channel(channel_id)` (ports.py:459), но **не имеет** `list_all()`. Нужно добавить для случая без `channel_id`.

### `tg_parser/services/retrieval_service.py`

`search()` (строки 77-98):
```python
similar = await emb_repo.similarity_search(query_vec, limit=limit * 2 if channel_id else limit, ...)
results: list[SearchResult] = []
for sim in similar:
    doc = await proc_repo.get_by_source_ref(sim.source_ref)  # N+1!
    if channel_id and doc and doc.channel_id != channel_id:
        continue
    results.append(SearchResult(source_ref=sim.source_ref, score=sim.score, document=doc))
    if len(results) >= limit:
        break
```
До `limit * 2` = 20 последовательных запросов `get_by_source_ref`.

### `tg_parser/services/channel_service.py`

`get_channel_stats()` (строки 39-44):
```python
covered_refs: set[str] = set()
for card in topic_cards:
    bundle = await topic_bundle_repo.get_by_topic_id(card.id)  # N+1!
    if bundle:
        for item in bundle.items:
            covered_refs.add(item.source_ref)
```

`get_all_channel_stats()` (строки 88-93) — идентичный паттерн, вызывается для каждого канала.

### `tests/test_mcp_server.py`

Mock helper `_mock_processing_repos` (строки 137-169):
```python
async def get_bundle(tid):
    return bundles.get(tid)
topic_bundle_repo.get_by_topic_id.side_effect = get_bundle
```
Тесты TestListTopicsTool используют `get_by_topic_id` через mock. После рефакторинга нужно переключить mock на `list_by_channel` / `list_all`.

### `tg_parser/storage/ports.py`

`TopicBundleRepo` (строки 437-477):
- `upsert()` — есть
- `get_by_topic_id()` — есть
- `list_by_channel(channel_id)` — **есть** (строка 459)
- `list_all()` — **отсутствует** (нужно добавить)
- `add_items()` — есть
- `delete_by_channel()` — есть

`ProcessedDocumentRepo` (строки 278-348):
- `get_by_source_ref()` — есть
- `get_by_source_refs(refs)` — **отсутствует** (нужно добавить)
- `count_by_channel()` — есть
- `list_source_refs_by_channel()` — есть (добавлен в S4)

## Что нужно сделать

### S5a: Починить E2E fixture (5 мин)

В `tests/test_e2e_pipeline.py`:

Добавить `DELETE FROM document_embeddings` **перед** строкой 159:
```python
await conn.execute(text("DELETE FROM processing_failures"))
await conn.execute(text("DELETE FROM document_embeddings"))   # <-- добавить
await conn.execute(text("DELETE FROM processed_documents"))
await conn.execute(text("DELETE FROM api_jobs"))
```

### S5b: Устранить N+1 в `list_topics` (30 мин)

1. **Добавить `list_all()` в `TopicBundleRepo`** (ports.py):
```python
@abstractmethod
async def list_all(self) -> list[TopicBundle]:
    """Получить все topic bundles."""
    pass
```

2. **SA-реализация** в `tg_parser/storage/sqlalchemy/topic_bundle_repo.py`:
```python
async def list_all(self) -> list[TopicBundle]:
    # SELECT * FROM topic_bundles ORDER BY topic_id
```

3. **Рефакторинг `list_topics()`** в `tg_parser/mcp_server.py` (строки 269-294):
```python
async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
    if channel_id:
        cards = await topic_card_repo.list_by_channel(channel_id)
        bundles = await topic_bundle_repo.list_by_channel(channel_id)
    else:
        cards = await topic_card_repo.list_all()
        bundles = await topic_bundle_repo.list_all()

    bundle_map = {b.topic_id: b for b in bundles}

    if topic_type:
        cards = [c for c in cards if c.type.value == topic_type]

    total = len(cards)
    page = cards[offset : offset + limit]

    summaries: list[TopicSummary] = []
    for card in page:
        bundle = bundle_map.get(card.id)
        items_count = len(bundle.items) if bundle else 0
        summaries.append(TopicSummary(...))
```

4. **Обновить mock** `_mock_processing_repos` в `tests/test_mcp_server.py`:
```python
# Добавить list_by_channel и list_all для bundles:
topic_bundle_repo.list_by_channel.return_value = list(bundles.values())
topic_bundle_repo.list_all.return_value = list(bundles.values())
# get_by_topic_id можно оставить (используется в get_topic_details)
```

### S5c: Устранить N+1 в `search` / `ask_question` (40 мин)

1. **Добавить `get_by_source_refs()` в `ProcessedDocumentRepo`** (ports.py):
```python
@abstractmethod
async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
    """Batch-load documents by source_refs. Returns dict keyed by source_ref."""
    pass
```

2. **SA-реализация** в `tg_parser/storage/sqlalchemy/processed_document_repo.py`:
```python
async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
    if not source_refs:
        return {}
    # SQL: WHERE source_ref IN (:refs)
    # Для asyncpg: использовать ANY(:refs) или конструировать IN-clause
    # Вернуть {doc.source_ref: doc for doc in results}
```

3. **Рефакторинг `search()`** в `tg_parser/services/retrieval_service.py` (строки 83-98):
```python
similar = await emb_repo.similarity_search(...)
all_refs = [sim.source_ref for sim in similar]
doc_map = await proc_repo.get_by_source_refs(all_refs)

results: list[SearchResult] = []
for sim in similar:
    doc = doc_map.get(sim.source_ref)
    if channel_id and doc and doc.channel_id != channel_id:
        continue
    results.append(SearchResult(source_ref=sim.source_ref, score=sim.score, document=doc))
    if len(results) >= limit:
        break
```

4. **Проверить `answer()`** — использует `search()` внутри, должна автоматически получить ускорение.

### S5d: Устранить N+1 в coverage calc (20 мин)

В `tg_parser/services/channel_service.py`:

1. **`get_channel_stats()`** (строки 39-44) — заменить цикл:
```python
# Было:
covered_refs: set[str] = set()
for card in topic_cards:
    bundle = await topic_bundle_repo.get_by_topic_id(card.id)
    if bundle:
        for item in bundle.items:
            covered_refs.add(item.source_ref)

# Стало:
all_bundles = await topic_bundle_repo.list_by_channel(channel_id)
covered_refs: set[str] = set()
for bundle in all_bundles:
    for item in bundle.items:
        covered_refs.add(item.source_ref)
```

2. **`get_all_channel_stats()`** (строки 88-93) — аналогичная замена:
```python
# Было:
for card in topic_cards:
    bundle = await topic_bundle_repo.get_by_topic_id(card.id)
    ...

# Стало:
all_bundles = await topic_bundle_repo.list_by_channel(cid)
covered_refs: set[str] = set()
for bundle in all_bundles:
    for item in bundle.items:
        covered_refs.add(item.source_ref)
```

После этого `topic_cards` загружается только для `topics_count = len(topic_cards)`, а bundles — отдельным вызовом для coverage.

3. **Обновить тесты** `TestGetAllChannelStats` в `tests/test_mcp_management.py` — mock для `topic_bundle_repo` должен настроить `list_by_channel` вместо/в дополнение к `get_by_topic_id`.

## Тестирование

### Юнит-тесты (обязательно)
```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_mcp_management.py tests/test_channels_routes.py -v
```

### Полный набор юнит-тестов
```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_postgres_integration.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_migrations.py --ignore=tests/test_storage_integration.py -v
```

### E2E тесты (после S5a)
```bash
.venv/bin/python -m pytest tests/test_e2e_pipeline.py -v
```

### MCP live smoke test
Вызвать через MCP tools:
- `list_topics(limit=5)` — проверить пагинацию, отсутствие N+1
- `list_topics(channel_id="profendocrinologist", topic_type="singleton", limit=3)`
- `search_knowledge_base(query="гипогликемия", limit=3)` — проверить batch-загрузку
- `list_channels()` — проверить coverage calc

**Ожидаемый результат:** все 590+ тестов проходят, MCP-инструменты работают корректно, 0 failures.

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `tests/test_e2e_pipeline.py` | S5a: добавить `DELETE FROM document_embeddings` |
| `tg_parser/storage/ports.py` | S5b: +`list_all()` в TopicBundleRepo; S5c: +`get_by_source_refs()` в ProcessedDocumentRepo |
| `tg_parser/storage/sqlalchemy/topic_bundle_repo.py` | S5b: SA-реализация `list_all()` |
| `tg_parser/storage/sqlalchemy/processed_document_repo.py` | S5c: SA-реализация `get_by_source_refs()` |
| `tg_parser/mcp_server.py` | S5b: рефакторинг `list_topics()` — batch-загрузка bundles |
| `tg_parser/services/retrieval_service.py` | S5c: рефакторинг `search()` — batch-загрузка документов |
| `tg_parser/services/channel_service.py` | S5d: рефакторинг coverage в `get_channel_stats()` и `get_all_channel_stats()` |
| `tests/test_mcp_server.py` | S5b: обновить mock `_mock_processing_repos` |
| `tests/test_mcp_management.py` | S5d: обновить mock для `TestGetAllChannelStats` |

## Чего НЕ делать

- **Не трогать** Singleton Database (это S6)
- **Не менять** `remove_channel` cleanup (это S6b)
- **Не менять** сигнатуры MCP tools и REST API (обратная совместимость)
- **Не добавлять** SQL-пагинацию в list_topics (оптимизация in-memory пагинации — отдельная задача)
- **Не менять** `db_context.py` и `database.py`

## Критерии приёмки

1. E2E fixture не падает с FK violation, 7 E2E тестов проходят (или проходят до pre-existing issues)
2. `list_topics()` делает 2 запроса (cards + bundles) вместо 1 + N
3. `search()` делает 1 batch-запрос документов вместо N
4. Coverage calc в `get_channel_stats()` и `get_all_channel_stats()` использует `list_by_channel` для bundles
5. Все существующие тесты проходят
6. MCP tools работают корректно на живых данных
