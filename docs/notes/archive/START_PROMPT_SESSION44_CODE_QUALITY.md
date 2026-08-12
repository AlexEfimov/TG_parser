# Session 44: Качество кода и дедупликация (Tech Debt B)

**Дата:** [дата запуска]  
**Тип сессии:** Tech Debt — Code Quality & Deduplication  
**Предыдущая сессия:** Session 43 (Tech Debt A — Config & Infrastructure)  
**План:** `docs/notes/TECH_DEBT_CLOSURE_PLAN.md` → Session 44 (B)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md`

---

## Цель сессии

Улучшить качество кода: устранить дупликацию, вынести захардкоженные значения в конфиг, добавить логирование в проглоченные исключения, обновить устаревшие SQLite-ссылки в docstrings, подключить реальный экспорт в API route.

---

## Контекст проекта

### Текущее состояние (после Session 43)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17.9 (Docker: `pgvector/pgvector:pg17`), pgvector 0.8.2
- **Тесты:** 538 passed, 24 skipped, 0 failures
- **Последний коммит:** `fa9121c` (Session 43)

### Ключевые файлы для этой сессии

```
tg_parser/services/embedding_service.py    # _create_embedding_client() — дубль
tg_parser/services/retrieval_service.py    # _create_embedding_client() — дубль + hardcoded URL
tg_parser/processing/llm/openai_client.py  # hardcoded OpenAI base URL
tg_parser/config/settings.py               # Нужно добавить openai_base_url
tg_parser/api/routes/health.py             # 5× except Exception: pass
tg_parser/storage/sqlalchemy/schemas/processing_storage.py  # 2× except Exception: pass
tg_parser/services/background_scheduler.py # 1× except Exception: pass
tg_parser/storage/ports.py                 # SQLite ссылки в docstrings
tg_parser/storage/sqlalchemy/*.py          # SQLite ссылки в docstrings (~12 файлов)
tg_parser/api/routes/export.py             # TODO на строке 58
tg_parser/services/export_service.py       # Реальная логика экспорта
```

---

## Задачи

### Задача B1: Дедупликация `_create_embedding_client()` (MEDIUM)

**Проблема:** Одинаковая factory-функция в двух местах:

1. `tg_parser/services/embedding_service.py` (строки 63-71):
   ```python
   def _create_embedding_client() -> OpenAIEmbeddingClient:
       api_key = settings.openai_api_key
       if not api_key:
           raise ValueError("OPENAI_API_KEY required for embedding generation")
       return OpenAIEmbeddingClient(api_key=api_key, model=settings.embedding_model)
   ```

2. `tg_parser/services/retrieval_service.py` (строки 35-42):
   ```python
   def _create_embedding_client() -> OpenAIEmbeddingClient:
       api_key = settings.openai_api_key
       if not api_key:
           raise ValueError("OPENAI_API_KEY required for retrieval")
       return OpenAIEmbeddingClient(api_key=api_key, model=settings.embedding_model)
   ```

**Что сделать:**
1. Оставить `_create_embedding_client()` в `embedding_service.py`, сделать публичной: `create_embedding_client()`
2. В `retrieval_service.py` — удалить локальную копию, импортировать из `embedding_service`:
   ```python
   from tg_parser.services.embedding_service import create_embedding_client
   ```
3. Обновить все вызовы в обоих файлах

**Справка:** `OpenAIEmbeddingClient` определён в `embedding_service.py` (строки 24-60), уже импортируется в `retrieval_service.py` (строка 14).

---

### Задача B2: Вынести OpenAI base URL в константу (MEDIUM)

**Проблема:** `https://api.openai.com/v1` захардкожен в 3 файлах:

1. `tg_parser/services/embedding_service.py` строка 40:
   ```python
   base_url="https://api.openai.com/v1",
   ```

2. `tg_parser/services/retrieval_service.py` строка 159:
   ```python
   base_url="https://api.openai.com/v1",
   ```

3. `tg_parser/processing/llm/openai_client.py` строка 47:
   ```python
   self.base_url = base_url or "https://api.openai.com/v1"
   ```

**Примечание:** `tg_parser/api/health_checks.py` строка 151 тоже содержит `https://api.openai.com/v1/models`, но это полный URL для health check — его трогать не обязательно (можно на усмотрение).

**Что сделать:**
1. В `tg_parser/config/settings.py` добавить поле в класс `Settings`:
   ```python
   openai_base_url: str = Field(
       default="https://api.openai.com/v1",
       description="Base URL for OpenAI API (or compatible proxy)",
   )
   ```
   **Важно:** В `Settings` уже есть `llm_base_url` (строка 114) для override, но оно `Optional` и для другого (OpenAI-compatible proxies / Ollama). `openai_base_url` — это дефолтный base URL именно для OpenAI endpoints (embedding, chat).
   
   **Альтернатива (проще):** Использовать существующий `llm_base_url` с fallback на константу. Решение на усмотрение — главное убрать хардкод из 3 файлов.

2. Обновить `OpenAIEmbeddingClient.__init__()` (embedding_service.py строка 27) — принимать `base_url` параметр
3. Обновить `create_embedding_client()` — передавать base URL из settings
4. Обновить `_call_llm()` в `retrieval_service.py` (строка 158-159)
5. Обновить `OpenAIClient.__init__()` в `openai_client.py` (строка 47)

---

### Задача B3: Добавить логирование в проглоченные исключения (MEDIUM)

**Проблема:** 8 мест с bare `except Exception: pass` (без логирования):

**Файл 1: `tg_parser/api/routes/health.py`** — функция `_get_basic_stats()` (строки 114-172):
- Строка 140-141: `except Exception: pass` (raw_messages count)
- Строка 154-155: `except Exception: pass` (processed_documents count)
- Строка 162-163: `except Exception: pass` (topics count)
- Строка 164-165: `except Exception: pass` (connect to processing engine)
- Строка 169-170: `except Exception: pass` (outer try)

**Файл 2: `tg_parser/storage/sqlalchemy/schemas/processing_storage.py`**:
- Строка 267-268: `except Exception: pass` (embedding DDL creation)
- Строка 276-277: `except Exception: pass` (embedding index creation)

**Файл 3: `tg_parser/services/background_scheduler.py`**:
- Строка 115-116: `except Exception: pass` (remove_job — "Job might not exist in scheduler")

**Что сделать:**
Заменить `pass` на `logger.debug(...)` или `logger.warning(...)` с сообщением и `exc_info=True` или передачей exception:

- `health.py`: `logger.debug("Failed to query %s: %s", table_name, e)` — debug, т.к. это stats и ожидаемо может упасть если таблица ещё не создана
- `processing_storage.py`: `logger.debug("pgvector DDL skipped: %s", e)` — debug, т.к. pgvector может быть недоступен
- `background_scheduler.py`: `logger.debug("Job %s not found in scheduler: %s", task_id, e)` — debug, т.к. это ожидаемое поведение

**Справка:** В `health.py` уже импортирован `logger` (нет). Нужно проверить — `from tg_parser.api.health_checks import ...` на строке 12, но `logger` не определён в routes/health.py. Нужно добавить:
```python
import logging
logger = logging.getLogger(__name__)
```

В `processing_storage.py` — `logger` не определён. Нужно добавить аналогично.

В `background_scheduler.py` — `logger` уже определён (строка 17).

---

### Задача B4: Обновить устаревшие SQLite-ссылки в docstrings (LOW)

**Проблема:** ~15 файлов содержат docstrings со ссылками на `SQLite`, `processing_storage.sqlite`, `raw_storage.sqlite`, `ingestion_state.sqlite` и т.п. Проект теперь PostgreSQL-only (с Session 39).

**Файлы и строки:**

| Файл | Строки | Текущий текст |
|------|--------|---------------|
| `storage/ports.py` | 5 | `SQLite/PostgreSQL` |
| `storage/ports.py` | 135 | `ingestion_state.sqlite` |
| `storage/ports.py` | 204 | `raw_storage.sqlite` |
| `storage/ports.py` | 262, 324, 368, 406 | `processing_storage.sqlite` |
| `storage/__init__.py` | 4 | `SQLite в MVP` |
| `storage/sqlalchemy/schemas/__init__.py` | 2 | `SQLite хранилищ` |
| `storage/sqlalchemy/ingestion_state_repo.py` | 2, 21, 23 | `SQLite реализация`, `ingestion_state.sqlite` |
| `storage/sqlalchemy/raw_message_repo.py` | 2, 26, 28 | `SQLite реализация`, `raw_storage.sqlite` |
| `storage/sqlalchemy/processed_document_repo.py` | 2, 23, 25 | `SQLite реализация`, `processing_storage.sqlite` |
| `storage/sqlalchemy/processing_failure_repo.py` | 2, 18, 20 | `SQLite реализация`, `processing_storage.sqlite` |
| `storage/sqlalchemy/topic_card_repo.py` | 2, 21, 23 | `SQLite реализация`, `processing_storage.sqlite` |
| `storage/sqlalchemy/topic_bundle_repo.py` | 2, 23, 25, 47 | `SQLite реализация`, `processing_storage.sqlite`, `SQLite` |
| `storage/sqlalchemy/job_repo.py` | 2, 21, 23 | `SQLite implementation`, `processing_storage.sqlite` |
| `storage/sqlalchemy/agent_state_repo.py` | 2, 21, 23 | `SQLite implementation`, `processing_storage.sqlite` |
| `storage/sqlalchemy/agent_stats_repo.py` | 2, 21, 23 | `SQLite implementation`, `processing_storage.sqlite` |
| `storage/sqlalchemy/task_history_repo.py` | 2, 22, 24 | `SQLite implementation`, `processing_storage.sqlite` |
| `storage/sqlalchemy/handoff_history_repo.py` | 2, 22, 24 | `SQLite implementation`, `processing_storage.sqlite` |
| `api/job_store.py` | 53 | `supports SQLite and PostgreSQL` |
| `cli/add_source_cmd.py` | 37 | `поддержка SQLite и PostgreSQL` |

**Что сделать:**
- `SQLite реализация` → `SQLAlchemy реализация` (или `PostgreSQL реализация`)
- `SQLite implementation` → `SQLAlchemy implementation`
- `Хранилище: processing_storage.sqlite` → `Хранилище: PostgreSQL (таблица ...)` или просто убрать имя файла
- `Uses processing_storage.sqlite` → `Uses PostgreSQL (table ...)`
- `SQLite/PostgreSQL` → `PostgreSQL`
- `SQLite в MVP` → `PostgreSQL`
- `supports SQLite and PostgreSQL` → `supports PostgreSQL`
- `поддержка SQLite и PostgreSQL` → удалить упоминание SQLite
- `topic_bundle_repo.py` строка 47: комментарий `# не поддерживает ON CONFLICT в SQLite` — обновить или убрать

---

### Задача B5: Реализовать или убрать TODO в `api/routes/export.py` (LOW)

**Проблема:** Строка 58:
```python
# TODO: Implement actual export logic
# For now, use existing output directory
```
Реальный экспорт уже реализован в `tg_parser/services/export_service.py`.

**Что сделать:**
Подключить `_run_export_job()` к `export_service`. Функция `_run_export_job()` (строки 38-118) сейчас просто ищет файл в output directory. Нужно:

1. Импортировать `export_service`:
   ```python
   from tg_parser.services.export_service import run_export
   ```

2. В `_run_export_job()` (строка 57-65) заменить TODO-блок на вызов `run_export()`:
   ```python
   result = await run_export(
       channel_id=request.channel_id,
       output_dir=str(settings.output_dir),
       format_type=request.format.value,
   )
   ```

**Справка:** Посмотреть сигнатуру `run_export()` в `tg_parser/services/export_service.py` перед реализацией. Если интеграция сложная — задокументировать как placeholder: заменить TODO на docstring-комментарий, объясняющий что route использует pre-generated файлы.

---

## Порядок выполнения

| # | Задача | Файлы | Зависимость |
|---|--------|-------|-------------|
| 1 | B1: Дедупликация embedding client | `embedding_service.py`, `retrieval_service.py` | — |
| 2 | B2: OpenAI base URL | `settings.py`, `embedding_service.py`, `retrieval_service.py`, `openai_client.py` | B1 |
| 3 | B3: Логирование исключений | `health.py`, `processing_storage.py`, `background_scheduler.py` | — |
| 4 | B4: SQLite docstrings | ~15 файлов в `storage/` | — |
| 5 | B5: Export TODO | `api/routes/export.py` | — |
| 6 | Тесты | — | Все задачи |

---

## Критерии завершения

- [ ] `_create_embedding_client()` — одна копия в `embedding_service.py`
- [ ] `https://api.openai.com/v1` — не захардкожен (кроме health check URL, опционально)
- [ ] Нет bare `except Exception: pass` в health.py, processing_storage.py, background_scheduler.py
- [ ] Нет упоминаний `SQLite` в docstrings (кроме `cli/init_db.py` строка 5 — исторический комментарий)
- [ ] TODO в `export.py` закрыт (реализован или задокументирован)
- [ ] Все 538+ тестов проходят
- [ ] Технический коммит

---

**Подготовлено:** Session 43  
**Следующий шаг:** Начать с B1 (дедупликация) → B2 (base URL) → далее по порядку
