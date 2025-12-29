# Session 24: PostgreSQL Production Ready — Финальные изменения

**Дата**: 30 декабря 2025  
**Версия**: v3.1.0 Production Ready  
**Статус**: ✅ Завершено

---

## 📋 Обзор изменений

Session 24 завершила переход проекта на production-ready состояние с полной поддержкой PostgreSQL. Ключевые изменения включают:

1. **CLI команды** — обновлены для поддержки PostgreSQL
2. **Репозитории** — исправлена совместимость типов данных
3. **Тесты** — обновлены для работы с обоими backend'ами
4. **Миграции** — реорганизованы с добавлением `init_postgres.py`

---

## 🔧 Изменения в CLI командах

### Проблема
CLI команды использовали устаревший `DatabaseConfig` с hardcoded путями SQLite:

```python
# До изменений (legacy)
config = DatabaseConfig(
    ingestion_state_path=settings.ingestion_state_db_path,
    raw_storage_path=settings.raw_storage_db_path,
    processing_storage_path=settings.processing_storage_db_path,
)
db = Database(config)
```

### Решение
Обновлены все CLI команды для использования `Database.from_settings()`:

```python
# После изменений (Session 24)
db = Database.from_settings(settings)
await db.init()
```

### Изменённые файлы

| Файл | Изменение |
|------|-----------|
| `tg_parser/cli/add_source_cmd.py` | Удалён импорт `DatabaseConfig`, используется `from_settings()` |
| `tg_parser/cli/ingest_cmd.py` | Удалён импорт `DatabaseConfig`, используется `from_settings()` |
| `tg_parser/cli/process_cmd.py` | **2 места** обновлены на `from_settings()` |
| `tg_parser/cli/export_cmd.py` | Удалён импорт `DatabaseConfig`, используется `from_settings()` |
| `tg_parser/cli/run_cmd.py` | Удалён импорт `DatabaseConfig`, используется `from_settings()` |
| `tg_parser/cli/topicize_cmd.py` | Удалён импорт `DatabaseConfig`, используется `from_settings()` |

### Пример изменения (add_source_cmd.py)

**До:**
```python
from tg_parser.storage.sqlite import (
    Database,
    DatabaseConfig,
    SQLiteIngestionStateRepo,
)

async def run_add_source(...):
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )
    db = Database(config)
    await db.init()
```

**После:**
```python
from tg_parser.storage.sqlite import (
    Database,
    SQLiteIngestionStateRepo,
)

async def run_add_source(...):
    # Инициализируем database (Session 24: поддержка SQLite и PostgreSQL)
    db = Database.from_settings(settings)
    await db.init()
```

---

## 🔧 Изменения в репозиториях

### Проблема
Репозитории использовали `1`/`0` для boolean полей, что работает с SQLite, но вызывает ошибку в PostgreSQL:

```
asyncpg.exceptions.DataError: invalid input for query argument $5: 0 
(a boolean is required (got type int))
```

### Решение
Заменены все `1 if condition else 0` на `bool(condition)`:

```python
# До (SQLite-only)
"include_comments": 1 if source.include_comments else 0,

# После (универсально)
"include_comments": bool(source.include_comments),
```

### Изменённые файлы

| Файл | Поле | Изменение |
|------|------|-----------|
| `ingestion_state_repo.py` | `include_comments` | `1 if x else 0` → `bool(x)` |
| `ingestion_state_repo.py` | `comments_unavailable` | `1 if x else 0` → `bool(x)` |
| `ingestion_state_repo.py` | `success` (source_attempts) | `1 if x else 0` → `bool(x)` |
| `raw_message_repo.py` | `raw_payload_truncated` | `1 if x else 0` → `bool(x)` |
| `agent_state_repo.py` | `is_active` | `1 if x else 0` → `bool(x)` |
| `task_history_repo.py` | `success` | `1 if x else 0` → `bool(x)` |

### Примечание
Файл `agent_stats_repo.py` **не изменён**, так как там используются арифметические операции со счётчиками:
```python
"success": 1 if success else 0,  # Используется для: successful_tasks + :success
"failed": 0 if success else 1,   # Используется для: failed_tasks + :failed
```

---

## 🧪 Изменения в тестах

### Проблема 1: Alembic тесты с PostgreSQL
Тесты миграций падали при `DB_TYPE=postgresql`, так как таблицы уже созданы через `init_postgres.py`.

**Решение:** Добавлен `pytestmark` для пропуска при PostgreSQL:

```python
# tests/test_migrations.py
pytestmark = pytest.mark.skipif(
    os.getenv("DB_TYPE", "sqlite") == "postgresql",
    reason="Alembic migration tests only run with SQLite. Use init_postgres.py for PostgreSQL."
)
```

### Проблема 2: E2E тесты использовали PostgreSQL
E2E тесты создавали `Settings` без явного `db_type`, что приводило к чтению из `.env` (postgresql).

**Решение:** Добавлен явный `db_type="sqlite"`:

```python
# tests/test_e2e_pipeline.py
@pytest.fixture
def e2e_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        yield Settings(
            db_type="sqlite",  # Явно SQLite для E2E тестов
            ingestion_state_db_path=tmppath / "e2e_ingestion_state.db",
            raw_storage_db_path=tmppath / "e2e_raw_storage.db",
            processing_storage_db_path=tmppath / "e2e_processing_storage.db",
            # ...
        )
```

### Проблема 3: Отсутствующие патчи settings
Тесты `test_run_command_*` не патчили `tg_parser.cli.run_cmd.settings`.

**Решение:** Добавлен патч:

```python
with (
    patch("tg_parser.cli.run_cmd.settings", e2e_settings),
    patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
    # ...
):
```

---

## 📁 Новые файлы

### `scripts/init_postgres.py`
Скрипт для прямой инициализации PostgreSQL схемы без Alembic:

```bash
# Использование
python scripts/init_postgres.py

# Dry-run (показать SQL без выполнения)
python scripts/init_postgres.py --dry-run
```

**Когда использовать:**
- Новый deployment с PostgreSQL
- Пустая база данных (нет данных для миграции)
- Обход проблем с Alembic

---

## 🔄 Архитектура Database

### Класс Database (Session 24)

```
┌─────────────────────────────────────────────────────────┐
│                     Database                             │
├─────────────────────────────────────────────────────────┤
│ __init__(config=None, settings=None)                    │
│                                                         │
│ ┌─────────────────┐    ┌─────────────────────────────┐ │
│ │  DatabaseConfig │ OR │  Settings (from_settings)   │ │
│ │  (legacy SQLite)│    │  (новый: SQLite/PostgreSQL) │ │
│ └─────────────────┘    └─────────────────────────────┘ │
│                                                         │
│ init() → создаёт engines через engine_factory          │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ engine_factory.create_engine_from_settings()        ││
│ │                                                     ││
│ │ db_type="sqlite"   → SQLite engine + NullPool      ││
│ │ db_type="postgresql" → PostgreSQL + QueuePool      ││
│ └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Поток выбора backend

```
Settings
   │
   ├── db_type="sqlite"
   │      │
   │      └── SQLite файлы:
   │           ingestion_state.sqlite
   │           raw_storage.sqlite
   │           processing_storage.sqlite
   │
   └── db_type="postgresql"
          │
          └── Единая PostgreSQL база:
               postgresql://user:pass@host:port/tg_parser
               (все 3 "логические" БД в одной)
```

---

## 📊 Результаты тестирования

### Unit/Integration тесты

```
$ pytest tests/ -q

411 passed, 24 skipped, 2 warnings in 60s
```

### E2E тест на реальном канале

```
Канал: @BiocodebySechenov
База: PostgreSQL (Docker)

📥 Ingestion:    8 постов за 0.40s
⚙️  Processing:   8 документов через GPT-4o-mini
🏷️  Topicization: 4 темы созданы
📤 Export:       8 KB entries + topics.json
```

---

## 📝 Коммиты

| Hash | Сообщение |
|------|-----------|
| `6f52575` | fix(tests): Skip Alembic tests for PostgreSQL, fix E2E test patches |
| `c14c532` | feat(cli): PostgreSQL support in all CLI commands |
| `70645aa` | fix(tests): Add explicit db_type=sqlite in E2E test settings |

---

## 🚀 Инструкции для development

### Работа с SQLite (development)
```bash
# .env
DB_TYPE=sqlite

# Инициализация (если нужно)
python -m tg_parser.cli init

# Запуск
python -m tg_parser.cli add-source --source-id test --channel-id test_channel
python -m tg_parser.cli ingest --source test --mode snapshot --limit 10
```

### Работа с PostgreSQL (production)
```bash
# .env
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=your_password

# Запуск PostgreSQL
docker compose up -d postgres

# Инициализация схемы
python scripts/init_postgres.py

# Запуск
python -m tg_parser.cli add-source --source-id channel1 --channel-id @channel
python -m tg_parser.cli ingest --source channel1 --mode snapshot
```

---

## ⚠️ Известные ограничения

1. **Команда `init`** — работает только с SQLite. Для PostgreSQL используйте `init_postgres.py`.

2. **Alembic миграции** — временно не используются для PostgreSQL. Используйте `init_postgres.py` для начальной настройки.

3. **Смешанные backends** — не поддерживаются. Выберите один `db_type` и используйте его.

---

## 📚 Связанные документы

- [MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md](../../MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md)
- [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md)
- [ENV_VARIABLES_GUIDE.md](../../ENV_VARIABLES_GUIDE.md)
- [AFTER_DEPLOYMENT.md](../../AFTER_DEPLOYMENT.md)

