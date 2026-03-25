# Tech Debt Closure Plan: Sessions 43-45

**Дата:** 25 марта 2026  
**Статус:** Утверждён  
**Предыдущие сессии:** Sessions 38-42 (Code Review → Pre-RAG Refactoring → RAG → PG17 → Tech Debt Cleanup)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md`

---

## Обзор

Три сессии для закрытия всего выявленного технического долга перед началом P6 (Веб-интерфейс). Каждая сессия — отдельный коммит. DI в services вынесен в отдельную будущую сессию.

**Аудит проведён:** Session 42. Источники: TODO/FIXME scan, code quality scan, test coverage gap analysis, dependency/config audit.

---

## Session 43 (A): Конфигурация и инфраструктура

**Приоритет:** Высокий  
**Оценка:** ~5 файлов, низкий риск

### A1. Консолидация `.env` шаблонов (HIGH)

**Проблема:** Два шаблона с конфликтующим содержимым.

- `.env.example` — содержит реалистично выглядящие Telegram credentials (`37408407`, `993af7cf...`, `+7919...`), устаревшие SQLite DB path comments (строки 107-113)
- `env.example` — ссылается на удалённый `DB_TYPE=sqlite`, SQLite paths (строки 1-14)

**Действия:**
- Удалить `env.example` (устаревший)
- Обновить `.env.example`:
  - Заменить Telegram credentials на плейсхолдеры (`your_telegram_api_id`, `your_api_hash`, `+1234567890`)
  - Заменить секцию "Database Paths" (строки 106-113) на PostgreSQL config: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, pool settings
  - Добавить секцию Embedding/RAG: `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`

### A2. Синхронизация `pyproject.toml` с `requirements.txt` (HIGH)

**Проблема:** `[project.dependencies]` в `pyproject.toml` неполный — отсутствуют `slowapi`, `pgvector`, `openai-agents`, `apscheduler`, `prometheus-fastapi-instrumentator`, `PyYAML`, `python-dotenv` и др. `pip install -e .` не работает полноценно.

**Действия:**
- Синхронизировать `[project.dependencies]` с `requirements.txt`
- Синхронизировать `[project.optional-dependencies].dev` — добавить `pytest-cov`

### A3. Обновить Dockerfile (MEDIUM)

**Проблема:** Строка 39: `# Create data directory for SQLite databases` — устаревший комментарий.

**Действие:** Обновить комментарий, убрать упоминание SQLite.

### A4. Добавить `output_*/` в `.gitignore` (MEDIUM)

**Проблема:** `output_session29/` и подобные директории не gitignored.

**Действие:** Добавить `output_*/` и `output_full/` в `.gitignore`.

### A5. Убрать дублирующий `pip install` в CI (LOW)

**Проблема:** `.github/workflows/ci.yml` содержит `pip install pytest pytest-cov pytest-asyncio ruff`, хотя все пакеты уже в `requirements.txt`.

**Действие:** Убрать дублирующую строку.

### Верификация

- Полный тест-сьют: 538+ passed, 24 skipped
- `pip install -e .` работает

---

## Session 44 (B): Качество кода и дедупликация

**Приоритет:** Средний  
**Оценка:** ~15 файлов, низкий-средний риск

### B1. Дедупликация `_create_embedding_client()` (MEDIUM)

**Проблема:** Одинаковая factory-логика в двух местах:
- `tg_parser/services/embedding_service.py` (строки ~63-71)
- `tg_parser/services/retrieval_service.py` (строки ~35-42)

**Действие:** Извлечь в одну функцию в `embedding_service.py`, импортировать из `retrieval_service.py`.

### B2. Вынести OpenAI base URL в константу (MEDIUM)

**Проблема:** `https://api.openai.com/v1` захардкожен в 3 файлах: `embedding_service.py`, `retrieval_service.py`, `openai_client.py`.

**Действие:** Добавить `openai_base_url` в `config/settings.py`, использовать во всех трёх файлах.

### B3. Добавить логирование в проглоченные исключения (MEDIUM)

**Проблема:** 8 мест с `except Exception: pass`:
- 5 в `tg_parser/api/routes/health.py` (stats queries)
- 2 в `tg_parser/storage/sqlalchemy/schemas/processing_storage.py` (pgvector DDL)
- 1 в `tg_parser/services/background_scheduler.py`

**Действие:** Заменить `pass` на `logger.debug(...)` или `logger.warning(...)`.

### B4. Обновить устаревшие SQLite-ссылки в docstrings (LOW)

**Проблема:** ~15 файлов в `tg_parser/storage/` и `storage/ports.py` ссылаются на `raw_storage.sqlite`, `processing_storage.sqlite` и т.д.

**Действие:** Обновить docstrings — убрать упоминания конкретных SQLite файлов, указать PostgreSQL.

### B5. Реализовать или убрать TODO в `api/routes/export.py` (LOW)

**Проблема:** Строка 58: `# TODO: Implement actual export logic`. Реальный экспорт существует в `services/export_service.py`.

**Действие:** Подключить route к `export_service` или задокументировать как placeholder.

### Верификация

- Полный тест-сьют: 538+ passed, 24 skipped

---

## Session 45 (C): Тестовое покрытие и порядок в репозитории

**Приоритет:** Средний-Низкий  
**Оценка:** ~30 файлов (в основном перемещения), низкий риск

### C1. Раз-skip-нуть тесты миграций (MEDIUM)

**Проблема:** `tests/test_migrations.py` полностью `pytest.mark.skip`. С PG17 должны работать.

**Действие:** Убрать skip-маркер, проверить прохождение.

### C2. Добавить HTTP-тесты для RAG-роутов (MEDIUM)

**Проблема:** `tg_parser/api/routes/rag.py` — Pydantic-схемы протестированы, но HTTP-хэндлеры (`search_documents`, `ask_question`) нет.

**Действие:** 3-4 теста через `TestClient` для `POST /api/v1/search` и `POST /api/v1/ask` (мокнуть service layer).

### C3. Тесты для непокрытых domain-модулей (MEDIUM)

**Проблема:** Нет тестов для:
- `tg_parser/domain/contract_validation.py`
- `tg_parser/domain/json_utils.py`

**Действие:** Unit-тесты для публичных функций.

### C4. Переместить root-level файлы (LOW)

**Benchmark-скрипты** (5 файлов) → `benchmarks/`:
- `test_anthropic_gemini.py`, `test_baseline_v12.py`, `test_performance_v12.py`, `test_cloud_providers_comparison.py`, `test_concurrency_cloud.py`

**Session MDs** (13 файлов в корне) → `docs/notes/archive/`:
- `SESSION12_*.md`, `SESSION13_*.md`, `SESSION22_*.md`, `SESSION23_*.md` (5), `SESSION24_*.md` (2), `SESSION_COMPLETE.md`

**Устаревшие docs** (13 файлов в корне) → `docs/archive/`:
- `AFTER_DEPLOYMENT.md`, `COMPLETION_SUMMARY.md`, `DEVELOPMENT_ROADMAP.md` (старая копия), `DOCUMENTATION_*.md` (4), `MIGRATION_GUIDE_*.md` (3), `NEXT_STEPS.md`, `TESTING_*.md` (3)

**Оставить в корне:** `README.md`, `CHANGELOG.md`, `LLM_SETUP_GUIDE.md`, `MULTI_CHANNEL_GUIDE.md`, `OUTPUT_FORMATS.md`, `PRODUCTION_DEPLOYMENT.md`, `PYTHON_SETUP_QUICK_GUIDE.md`, `QUICKSTART_v1.2.md`, `ENV_VARIABLES_GUIDE.md`

### C5. Обновить ссылки на `postgres:16` в документах (LOW)

**Проблема:** `docs/USER_GUIDE.md` и другие упоминают `postgres:16`.

**Действие:** Search-replace `postgres:16` → `pgvector/pgvector:pg17` в активных документах.

### Верификация

- Полный тест-сьют + новые тесты
- Бенчмарк-скрипты работают из `benchmarks/`

---

## Вне скоупа (отдельные сессии)

| Пункт | Причина |
|-------|---------|
| DI в 8 сервисах | Масштабный рефакторинг — отдельная сессия с design pass |
| `tokens_used` в `IncrementalTopicizeResult` | Требует изменения LLM client API |
| Batch splitting для incremental mode | Feature-работа, не cleanup |
| `# type: ignore` (5 строк) | Мелочь, исправлять по ходу |

---

## Текущие метрики

| Метрика | Значение |
|---------|----------|
| Tests | 538 passed, 24 skipped |
| PostgreSQL | 17.9 (Docker pgvector/pgvector:pg17) |
| pgvector | 0.8.2 |
| Pipeline | ingest → process → topicize → embed → export → search/ask |

---

**Подготовлено:** Session 42  
**Следующий шаг:** Session 43 (A) — Конфигурация и инфраструктура
