# Стартовый промпт: S6 — Баги, cleanup, качество кода

## Задача

Закрыть элементы технического долга из `docs/technical-debt-roadmap.md`:
1. Починить баг в coverage metric (`get_all_channel_stats` не делает пересечение)
2. Добавить `delete_by_channel` в `JobRepo` / `TaskHistoryRepo` для `remove_channel`
3. Вынести hardcoded timeouts в settings
4. Добавить unit-тесты для export-модулей
5. Убрать `type: ignore` и сконфигурировать pytest-cov

## Контекст

В S5 были устранены N+1 запросы в `list_topics`, `search`, `coverage calc`, починена E2E fixture. Все 646 тестов проходят. Аудит кода выявил 5 категорий оставшегося долга — все низкого риска, не меняющие внешнего поведения API/MCP.

## Текущее состояние файлов

### S6a: `tg_parser/services/channel_service.py` — баг coverage metric

`get_channel_stats()` (строки 37-46) — корректная формула:
```python
processed_refs = set(await proc_repo.list_source_refs_by_channel(channel_id))

all_bundles = await topic_bundle_repo.list_by_channel(channel_id)
covered_refs: set[str] = set()
for bundle in all_bundles:
    for item in bundle.items:
        covered_refs.add(item.source_ref)

covered_documents = len(covered_refs & processed_refs)  # пересечение!
coverage_percent = (covered_documents / processed_count * 100) if processed_count else 0.0
```

`get_all_channel_stats()` (строки 87-100) — **БАГ**, нет пересечения:
```python
all_bundles = await topic_bundle_repo.list_by_channel(cid)
covered_refs: set[str] = set()
for bundle in all_bundles:
    for item in bundle.items:
        covered_refs.add(item.source_ref)

coverage_percent = (
    (len(covered_refs) / processed_count * 100)  # НЕТ пересечения с processed_refs!
    if processed_count
    else 0.0
)
```

Если bundle содержит `source_ref` из другого канала, `len(covered_refs)` будет завышен.

### S6b: `tg_parser/mcp_server.py` remove_channel (строки 587-622)

Текущий код удаляет:
```python
async with removal_repos() as (
    state_repo, raw_repo, proc_repo, failure_repo,
    embedding_repo, topic_card_repo, topic_bundle_repo, _db,
):
    counts["embeddings"] = await embedding_repo.delete_by_channel(normalized)
    counts["processed_documents"] = await proc_repo.delete_by_channel(normalized)
    counts["processing_failures"] = await failure_repo.delete_by_channel(normalized)
    counts["topic_cards"] = await topic_card_repo.delete_by_channel(normalized)
    counts["topic_bundles"] = await topic_bundle_repo.delete_by_channel(normalized)
    counts["raw_messages"] = await raw_repo.delete_by_channel(normalized)
    existed = await state_repo.delete_source(normalized)
    counts["source"] = 1 if existed else 0
```

**НЕ удаляются:** `api_jobs` и `task_history` с `channel_id` этого канала.

### S6b: `tg_parser/storage/ports.py`

`JobRepo` (строки 484-528) — есть `delete_old_jobs()`, **нет** `delete_by_channel()`.
`TaskHistoryRepo` (строки 746-816) — есть `cleanup_expired()`, **нет** `delete_by_channel()`.

### S6b: `tg_parser/storage/sqlalchemy/job_repo.py`

`SAJobRepo` использует `self._session_factory` (callable) вместо `self.session` (как в остальных SA-репо). Метод `delete_by_channel()` должен следовать тому же паттерну:
```python
async with self._session_factory() as session:
    result = await session.execute(
        text("DELETE FROM api_jobs WHERE channel_id = :channel_id"),
        {"channel_id": channel_id},
    )
    await session.commit()
    return result.rowcount
```

### S6b: `tg_parser/storage/sqlalchemy/task_history_repo.py`

Аналогичный паттерн с `self._session_factory`:
```python
async with self._session_factory() as session:
    result = await session.execute(
        text("DELETE FROM task_history WHERE channel_id = :channel_id"),
        {"channel_id": channel_id},
    )
    await session.commit()
    return result.rowcount
```

### S6b: `tg_parser/services/db_context.py`

`removal_repos()` (строки 198-223) **не предоставляет** `SAJobRepo` и `SATaskHistoryRepo`. Нужно расширить tuple.

**ВАЖНО:** `SAJobRepo` и `SATaskHistoryRepo` принимают `session_factory` (callable), а не `session`. В `db_context.py` нужно передать `db.processing_storage_session` (метод, не результат вызова).

### S6c: Hardcoded timeouts

**`tg_parser/api/health_checks.py`:**
- Строки 149, 161, 180: `httpx.AsyncClient(timeout=10.0)`
- Строка 193: `httpx.AsyncClient(timeout=5.0)`

**`tg_parser/processing/topicization.py`:**
- Строки 271, 335, 969: `await asyncio.sleep(2.0)` — retry delay при JSON parse error

**`tg_parser/config/settings.py`** уже имеет паттерн:
- `db_pool_timeout: float = 30.0`
- `webhook_timeout: float = 30.0`

### S6d: Export-модули без тестов

- `tg_parser/export/kb_export.py` — `export_kb_entries_ndjson(entries, output_path)`, чистая функция, пишет NDJSON
- `tg_parser/export/topics_export.py` — `export_topics_json(cards, output_path)`, `export_topic_bundles(cards, bundles, output_dir)`, чистые функции

Не требуют моков БД — работают с доменными моделями + файловой системой (`tmp_path` fixture).

### S6e: type:ignore

| Файл | Строка | Код |
|------|--------|-----|
| `tg_parser/cli/app.py` | 733 | `mode=mode,  # type: ignore` |
| `tg_parser/services/topicization_service.py` | 171 | `llm_client=None,  # type: ignore[arg-type]` |
| `tg_parser/services/topicization_service.py` | 355 | `llm_client=None,  # type: ignore[arg-type]` |
| `tg_parser/services/ingestion_service.py` | 66 | `mode=mode,  # type: ignore` |
| `tg_parser/agents/base.py` | 260 | `result = await self.process(agent_input)  # type: ignore` |

### S6e: pytest-cov

Нет секции `[tool.coverage]` в `pyproject.toml`. Минимальная конфигурация:
```toml
[tool.coverage.run]
source = ["tg_parser"]
omit = ["*/tests/*", "*/migrations/*"]

[tool.coverage.report]
show_missing = true
exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:"]
```

## Что нужно сделать

### S6a: Fix coverage metric (15 мин)

1. В `get_all_channel_stats()` добавить загрузку `processed_refs` и пересечение:
```python
processed_refs = set(await proc_repo.list_source_refs_by_channel(cid))

all_bundles = await topic_bundle_repo.list_by_channel(cid)
covered_refs: set[str] = set()
for bundle in all_bundles:
    for item in bundle.items:
        covered_refs.add(item.source_ref)

covered_documents = len(covered_refs & processed_refs)
coverage_percent = (covered_documents / processed_count * 100) if processed_count else 0.0
```

2. Извлечь helper `_compute_coverage(bundles, processed_refs) -> tuple[int, float]` для обеих функций.

3. Обновить тест `test_batch_stats_returns_all_channels` — добавить mock для `list_source_refs_by_channel`.

### S6b: remove_channel cleanup (40 мин)

1. **Добавить в ports.py:**
```python
# В JobRepo (после delete_old_jobs):
@abstractmethod
async def delete_by_channel(self, channel_id: str) -> int:
    """Delete all jobs for a channel. Returns deleted count."""
    pass

# В TaskHistoryRepo (после cleanup_expired):
@abstractmethod
async def delete_by_channel(self, channel_id: str) -> int:
    """Delete all task records for a channel. Returns deleted count."""
    pass
```

2. **SA-реализации** — `DELETE FROM ... WHERE channel_id = :channel_id` (паттерн с `self._session_factory`).

3. **Расширить `removal_repos()`** в `db_context.py` — добавить `SAJobRepo(db.processing_storage_session)` и `SATaskHistoryRepo(db.processing_storage_session)`.

4. **В `remove_channel()`** добавить:
```python
counts["api_jobs"] = await job_repo.delete_by_channel(normalized)
counts["task_history"] = await task_history_repo.delete_by_channel(normalized)
```

5. **Обновить mock** `_mock_removal_repos` в `tests/test_mcp_management.py`.

### S6c: Hardcoded timeouts → settings (30 мин)

1. **В `settings.py`** добавить:
```python
health_check_timeout: float = Field(default=10.0, description="Timeout for LLM provider health checks")
ollama_health_check_timeout: float = Field(default=5.0, description="Timeout for Ollama health check")
llm_json_retry_delay: float = Field(default=2.0, description="Delay between LLM JSON parse retries")
```

2. **В `health_checks.py`** заменить `timeout=10.0` → `timeout=settings.health_check_timeout`, `timeout=5.0` → `timeout=settings.ollama_health_check_timeout`.

3. **В `topicization.py`** заменить `asyncio.sleep(2.0)` → `asyncio.sleep(settings.llm_json_retry_delay)` (3 места).

### S6d: Тесты export-модулей (45 мин)

Создать `tests/test_export.py`:

1. **`test_kb_export_ndjson`** — создать список `KnowledgeBaseEntry`, вызвать `export_kb_entries_ndjson(entries, tmp_path / "out.ndjson")`, прочитать и проверить формат.

2. **`test_topics_export_json`** — создать `TopicCard` список, вызвать `export_topics_json(cards, tmp_path / "topics.json")`, проверить JSON.

3. **`test_topic_bundles_export`** — создать cards + bundles, вызвать `export_topic_bundles(...)`, проверить файлы.

4. **Edge cases:** пустые списки, длинные summary, спецсимволы в title.

### S6e: type:ignore + pytest-cov (20 мин)

1. Проанализировать каждый `type: ignore` — часть можно исправить через правильные type hints, часть через `cast()` или `Protocol`.

2. Добавить `[tool.coverage]` секцию в `pyproject.toml`.

## Тестирование

### Юнит-тесты (обязательно)
```bash
cd /Users/alexanderefimov/TG_parser
.venv/bin/python -m pytest tests/test_mcp_management.py tests/test_mcp_server.py tests/test_channels_routes.py -v
```

### Полный набор юнит-тестов
```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_postgres_integration.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_migrations.py --ignore=tests/test_storage_integration.py -v
```

### Все тесты включая integration
```bash
.venv/bin/python -m pytest tests/ -v
```

### MCP live smoke test
- `list_channels()` — проверить coverage_percent
- `list_topics(limit=5)` — пагинация
- `search_knowledge_base(query="гипогликемия", limit=3)` — поиск

**Ожидаемый результат:** все 650+ тестов проходят (включая новые export-тесты), MCP-инструменты работают корректно.

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `tg_parser/services/channel_service.py` | S6a: fix coverage metric, extract helper |
| `tg_parser/storage/ports.py` | S6b: +`delete_by_channel()` в JobRepo и TaskHistoryRepo |
| `tg_parser/storage/sqlalchemy/job_repo.py` | S6b: SA-реализация `delete_by_channel()` |
| `tg_parser/storage/sqlalchemy/task_history_repo.py` | S6b: SA-реализация `delete_by_channel()` |
| `tg_parser/services/db_context.py` | S6b: расширить `removal_repos()` |
| `tg_parser/mcp_server.py` | S6b: вызвать delete в `remove_channel()` |
| `tests/test_mcp_management.py` | S6a+S6b: обновить mocks |
| `tg_parser/config/settings.py` | S6c: новые поля timeout/delay |
| `tg_parser/api/health_checks.py` | S6c: заменить hardcoded timeouts |
| `tg_parser/processing/topicization.py` | S6c: заменить hardcoded sleep |
| `tests/test_export.py` | S6d: **новый файл** — тесты export |
| `tg_parser/cli/app.py` | S6e: убрать type:ignore |
| `tg_parser/services/topicization_service.py` | S6e: убрать type:ignore |
| `tg_parser/services/ingestion_service.py` | S6e: убрать type:ignore |
| `tg_parser/agents/base.py` | S6e: убрать type:ignore |
| `pyproject.toml` | S6e: добавить [tool.coverage] |

## Чего НЕ делать

- **Не трогать** Singleton Database (это S7)
- **Не менять** `database.py` и архитектуру `db_context.py` (кроме расширения `removal_repos`)
- **Не менять** сигнатуры MCP tools и REST API (обратная совместимость)
- **Не рефакторить** другие context managers

## Критерии приёмки

1. `get_all_channel_stats()` использует тот же паттерн coverage что и `get_channel_stats()` (пересечение)
2. `remove_channel` чистит `api_jobs` и `task_history`
3. Нет hardcoded timeout/sleep в `health_checks.py` и `topicization.py`
4. Export-модули покрыты тестами
5. 0 `type: ignore` (или обоснованный минимум)
6. pytest-cov сконфигурирован
7. Все тесты проходят
