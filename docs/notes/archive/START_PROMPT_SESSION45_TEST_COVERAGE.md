# Session 45: Тестовое покрытие и порядок в репозитории (Tech Debt C)

**Дата:** [дата запуска]  
**Тип сессии:** Tech Debt — Test Coverage & Repo Housekeeping  
**Предыдущая сессия:** Session 44 (Tech Debt B — Code Quality & Deduplication)  
**План:** `docs/notes/TECH_DEBT_CLOSURE_PLAN.md` → Session 45 (C)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md`

---

## Цель сессии

Закрыть оставшийся технический долг: решить вопрос со скипнутыми миграционными тестами, добавить HTTP-тесты для RAG-роутов, покрыть тестами `domain/contract_validation.py` и `domain/json_utils.py`, навести порядок в корневых файлах репозитория, обновить ссылки на `postgres:16` в документах.

---

## Контекст проекта

### Текущее состояние (после Session 44)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17.9 (Docker: `pgvector/pgvector:pg17`), pgvector 0.8.2
- **Тесты:** 538 passed, 24 skipped, 0 failures (562 collected, 1 deselected)
- **Последний коммит:** Session 44 (не закоммичен, ожидает коммита вместе с Session 44 или отдельно)
- **Предыдущие коммиты:** `fa9121c` (Session 43)

### Что сделано в Session 44 (B)

- B1: Дедуплицирован `create_embedding_client()` (одна копия в `embedding_service.py`)
- B2: OpenAI base URL вынесен в `settings.openai_base_url`
- B3: Все 8 bare `except Exception: pass` заменены на `logger.debug(...)`
- B4: SQLite-ссылки в docstrings обновлены (~18 файлов)
- B5: TODO в `export.py` закрыт — подключён `run_export()` из `export_service`

---

## Задачи

### Задача C1: Решить вопрос с `test_migrations.py` (MEDIUM)

**Проблема:** `tests/test_migrations.py` полностью скипнут маркером:
```python
pytestmark = pytest.mark.skip(
    reason="SQLite migration tests removed. PostgreSQL migrations use init_postgres.py."
)
```

Файл содержит 8 тестов — все используют SQLite (`sqlite:///`, `.sqlite` файлы, `create_engine(f"sqlite:///{db_path}")`) и Alembic-миграции через `alembic.ini`. Проект теперь PostgreSQL-only.

**Варианты:**
1. **Переписать тесты на PostgreSQL** — использовать тестовую БД PostgreSQL, `init_postgres.py` для инициализации, проверять наличие таблиц через `pg_tables`. Это масштабная работа, но даёт реальную проверку.
2. **Удалить файл** — миграции через init_postgres.py/DDL-скрипты, а не Alembic. Тесты устарели по существу.
3. **Заменить на простые smoke-тесты** — проверить, что `init_*_schema()` функции работают на чистой PostgreSQL БД.

**Рекомендация:** Вариант 3 — написать 3 smoke-теста, проверяющих что DDL-функции (`init_ingestion_state_schema`, `init_raw_storage_schema`, `init_processing_storage_schema`) корректно создают таблицы на тестовом PostgreSQL engine. Удалить старые SQLite/Alembic тесты.

**Справка:**
- DDL-функции: `tg_parser/storage/sqlalchemy/schemas/ingestion_state.py`, `raw_storage.py`, `processing_storage.py`
- Тестовый PostgreSQL: `conftest.py` уже настраивает `_test_pg_settings()` и `e2e_db` fixture
- Текущие 8 тестов в файле: `test_ingestion_migration_upgrade`, `test_raw_migration_upgrade`, `test_processing_migration_upgrade`, `test_ingestion_downgrade_cycle`, `test_raw_downgrade_cycle`, `test_processing_downgrade_cycle`, `test_multi_database_independence`, `test_alembic_version_table_per_database`

---

### Задача C2: HTTP-тесты для RAG-роутов (MEDIUM)

**Проблема:** `tg_parser/api/routes/rag.py` содержит два HTTP-эндпоинта без тестов:
- `POST /api/v1/search` → `search_documents()`
- `POST /api/v1/ask` → `ask_question()`

Pydantic-схемы (`SearchRequest`, `AskRequest`, `SearchResponse`, `AskResponse`) определены, но HTTP-хэндлеры не тестируются.

**Что сделать:**
Создать 3-4 теста в `tests/test_rag_routes.py` (или добавить в существующий test_api):

1. `test_search_success` — мокнуть `tg_parser.services.retrieval_service.search`, проверить 200 + JSON-структуру
2. `test_search_empty_results` — мокнуть пустой результат, проверить `total: 0`
3. `test_ask_success` — мокнуть `tg_parser.services.retrieval_service.answer`, проверить 200 + `answer` + `sources`
4. `test_ask_no_results` — мокнуть пустой ответ

**Справка:**
- RAG routes: `tg_parser/api/routes/rag.py` (122 строки)
- Service functions: `retrieval_service.search()` → `list[SearchResult]`, `retrieval_service.answer()` → `AnswerResult`
- Модели для мока:
  ```python
  SearchResult(source_ref="ref1", score=0.95, document=ProcessedDocument(...))
  AnswerResult(answer="Ответ...", sources=[...], model="gpt-4o-mini")
  ```
- Смотреть как сделаны тесты в `tests/test_api.py` — используется `TestClient` из `httpx` + FastAPI
- `routes/rag.py` использует ленивый импорт: `from tg_parser.services.retrieval_service import search` внутри функции → мокать `tg_parser.services.retrieval_service.search`

---

### Задача C3: Тесты для domain-модулей (MEDIUM)

**Проблема:** Нет тестов для двух domain-модулей.

**Файл 1: `tg_parser/domain/contract_validation.py`** (112 строк)
- Класс `ContractValidator` — валидирует dict-объекты против JSON Schema из `docs/contracts/`
- Публичные методы: `validate()`, `validate_raw_message()`, `validate_processed_document()`, `validate_topic_card()`, `validate_topic_bundle()`, `validate_knowledge_base_entry()`
- Глобальный helper: `validate_contract(schema_name, obj)`
- JSON Schema файлы: `docs/contracts/{raw_telegram_message,processed_document,topic_card,topic_bundle,knowledge_base_entry}.schema.json`

**Файл 2: `tg_parser/domain/json_utils.py`** (95 строк)
- `stable_json_dumps(obj, pretty=False)` — JSON с sort_keys, compact separators
- `stable_json_loads(s)` — обёртка над json.loads
- `parse_iso_datetime(s)` — парсинг ISO 8601 строк ("2025-12-13T10:00:00Z" → datetime)
- `_json_default(obj)` — datetime serializer

**Что сделать:**
Создать `tests/test_contract_validation.py` и `tests/test_json_utils.py`:

Для `contract_validation`:
1. `test_validate_raw_message_valid` — валидный dict проходит валидацию
2. `test_validate_raw_message_invalid` — невалидный dict → `ValidationError`
3. `test_validate_processed_document_valid`
4. `test_validate_unknown_schema` — `FileNotFoundError`
5. `test_global_validate_contract_helper`

Для `json_utils`:
1. `test_stable_json_dumps_deterministic` — проверить sort_keys, compact separators
2. `test_stable_json_dumps_pretty` — проверить indent=2
3. `test_stable_json_dumps_datetime` — datetime → ISO 8601
4. `test_stable_json_loads`
5. `test_parse_iso_datetime` — с "Z" суффиксом и без
6. `test_parse_iso_datetime_with_timezone`

---

### Задача C4: Переместить root-level файлы (LOW)

**Проблема:** Корень репозитория загромождён файлами, которые должны быть в подпапках.

**Benchmark-скрипты** (5 файлов) → `benchmarks/`:
```
test_anthropic_gemini.py
test_baseline_v12.py
test_performance_v12.py
test_cloud_providers_comparison.py
test_concurrency_cloud.py
```

**Session MDs** (12 файлов) → `docs/notes/archive/`:
```
SESSION12_AND_13_PREP_COMPLETE.md
SESSION12_COMPLETE.md
SESSION13_READINESS.md
SESSION22_SUMMARY.md
SESSION23_COMPLETE_SUMMARY.md
SESSION23_DOCUMENTATION_SUMMARY.md
SESSION23_DOCUMENTATION_UPDATE.md
SESSION23_SUMMARY.md
SESSION23_USER_CHANGES.md
SESSION24_COMPLETE_SUMMARY.md
SESSION24_PREPARATION.md
SESSION_COMPLETE.md
```

**Устаревшие docs** (15 файлов) → `docs/archive/`:
```
AFTER_DEPLOYMENT.md
COMPLETION_SUMMARY.md
DEVELOPMENT_ROADMAP.md           # старая копия (актуальная в docs/notes/)
DOCUMENTATION_AUDIT.md
DOCUMENTATION_INDEX.md
DOCUMENTATION_REVIEW_COMPLETE.md
DOCUMENTATION_UPDATE_SESSION24.md
MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md
MIGRATION_GUIDE_v1.1_to_v1.2.md
MIGRATION_GUIDE_v2_to_v3.md
NEXT_STEPS.md
REAL_CHANNEL_TEST_RESULTS.md
TESTING_CHECKLIST.md
TESTING_INSTRUCTIONS.md
TESTING_RESULTS_v1.2.md
```

**Оставить в корне:** `README.md`, `CHANGELOG.md`, `LLM_SETUP_GUIDE.md`, `MULTI_CHANNEL_GUIDE.md`, `OUTPUT_FORMATS.md`, `PRODUCTION_DEPLOYMENT.md`, `PYTHON_SETUP_QUICK_GUIDE.md`, `QUICKSTART_v1.2.md`, `ENV_VARIABLES_GUIDE.md`

**Что сделать:**
1. `mkdir -p benchmarks docs/archive docs/notes/archive`
2. `git mv` каждый файл в целевую папку
3. Проверить, что нет битых ссылок в `README.md` или других активных docs

---

### Задача C5: Обновить ссылки на `postgres:16` (LOW)

**Проблема:** Активные документы ссылаются на `postgres:16-alpine`, хотя проект перешёл на `pgvector/pgvector:pg17`.

**Файлы для обновления (активные docs):**

| Файл | Строка | Текущий текст |
|------|--------|---------------|
| `docs/USER_GUIDE.md` | 1627 | `image: postgres:16-alpine` |
| `CHANGELOG.md` | 123 | `postgres:16-alpine` |

**Файлы, которые будут перемещены в archive (C4) — можно не трогать:**
- `SESSION24_COMPLETE_SUMMARY.md` (→ archive)
- `SESSION24_PREPARATION.md` (→ archive)
- `docs/notes/current-state.md` (историческая справка)
- `docs/notes/START_PROMPT_SESSION25_REAL_TESTING.md` (историческая)
- `docs/notes/START_PROMPT_SESSION39_PRE_RAG_REFACTORING.md` (историческая)
- `docs/notes/START_PROMPT_SESSION24_PRODUCTION.md` (историческая)
- `docs/notes/SESSION40_CODE_REVIEW_REPORT.md` (историческая)
- `docs/notes/DEVELOPMENT_ROADMAP.md` строка 201 — уже содержит `pgvector/pgvector:pg17` с пояснением "(заменён postgres:16-alpine)"

**Что сделать:**
1. `docs/USER_GUIDE.md` строка 1627: `postgres:16-alpine` → `pgvector/pgvector:pg17`
2. `CHANGELOG.md` строка 123: добавить примечание или обновить (CHANGELOG — исторический документ, лучше оставить как есть и добавить новую запись о миграции на pg17 в Session 39)

**Примечание:** CI (`.github/workflows/ci.yml`) и `docker-compose.yml` уже используют `pgvector/pgvector:pg17` — проверять не нужно.

---

## Порядок выполнения

| # | Задача | Файлы | Зависимость |
|---|--------|-------|-------------|
| 1 | C1: Миграционные тесты | `tests/test_migrations.py` | — |
| 2 | C2: RAG HTTP-тесты | `tests/test_rag_routes.py` (новый) | — |
| 3 | C3: Domain-тесты | `tests/test_contract_validation.py`, `tests/test_json_utils.py` (новые) | — |
| 4 | C4: Переместить файлы | ~32 файла, `git mv` | — |
| 5 | C5: postgres:16 ссылки | `docs/USER_GUIDE.md`, `CHANGELOG.md` | C4 (знать какие уже в archive) |
| 6 | Тесты | — | Все задачи |

**Совет:** C1, C2, C3 можно делать параллельно — они независимы. C4 и C5 — в конце.

---

## Критерии завершения

- [ ] `test_migrations.py` — не скипнут; переписан или заменён на PostgreSQL smoke-тесты
- [ ] 3-4 HTTP-теста для `POST /api/v1/search` и `POST /api/v1/ask`
- [ ] Unit-тесты для `contract_validation.py` и `json_utils.py`
- [ ] Benchmark-скрипты в `benchmarks/`
- [ ] Session MDs в `docs/notes/archive/`
- [ ] Устаревшие docs в `docs/archive/`
- [ ] Нет `postgres:16` в активных документах (кроме исторических заметок)
- [ ] Все 538+ тестов + новые тесты проходят
- [ ] Технический коммит

---

**Подготовлено:** Session 44  
**Следующий шаг:** Начать с C1 + C2 + C3 параллельно → C4 (перемещения) → C5 (ссылки) → тесты
