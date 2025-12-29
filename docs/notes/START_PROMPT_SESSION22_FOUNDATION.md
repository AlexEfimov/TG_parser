# Session 22: Foundation & Tech Debt

**Дата**: 29 декабря 2025  
**Версия**: v3.0.0 → v3.1.0-alpha.1  
**Фаза**: Phase 4A — Production Hardening  
**Приоритет**: 🔴 Critical  
**Время**: ~6 часов  
**Milestone**: 🔶 Staging Deploy Ready

---

## 🚢 Deployment Milestone

После завершения этой сессии проект будет готов к **deploy на Staging сервер**:
- ✅ Alembic миграции — обновления без потери данных
- ✅ Документация актуальна
- ⚠️ SQLite — только 1 пользователь (production после Session 24)

```
Session 22 ──► 🔶 Staging Ready
                    ↓
Session 23-24 ──► 🟢 Production Ready
```

### Что добавили в план Session 23 (важно)

В Session 23, помимо Structured JSON Logging, запланирован **рефакторинг OpenAI клиента для GPT‑5 моделей**:
- Перевод вызовов `gpt-5.*` на **Responses API** (`/responses`)
- Добавление поддержки `reasoning.effort` и `verbosity` (config-driven)

Это нужно, чтобы стабильно использовать модели `gpt-5.2`, `gpt-5-mini`, `gpt-5-nano` и удобно отлаживать их поведение на staging (вместе с JSON логами).

**Start prompt Session 23**: `docs/notes/START_PROMPT_SESSION23_LOGGING_GPT5.md`

---

## 📋 Цели сессии

1. **Alembic Migrations Setup** — версионирование схемы БД (BLOCKING!)
2. **Архивация устаревших docs** — очистка документации
3. **Обновление current-state.md** — актуализация статуса
4. **Вынос retry параметров в config** — конфигурируемость

---

## 🎯 Задача 1: Alembic Migrations Setup (3-4 часа)

### Почему критично
- **Блокирует PostgreSQL** — без Alembic невозможно мигрировать схему
- **Блокирует изменения схемы** — добавление колонок требует миграций
- **Production requirement** — нельзя терять данные при обновлениях

### Требования

#### 1.1 Установка и конфигурация
```bash
# Добавить в pyproject.toml
poetry add alembic
```

```python
# alembic.ini — multi-database support
# У нас 3 базы:
# - ingestion_state.sqlite
# - raw_storage.sqlite  
# - processing_storage.sqlite
```

#### 1.2 Структура директорий
```
migrations/
├── alembic.ini
├── env.py                  # Multi-database env
├── script.py.mako
└── versions/
    ├── ingestion/          # Миграции для ingestion_state
    │   └── 001_initial.py
    ├── raw/                # Миграции для raw_storage
    │   └── 001_initial.py
    └── processing/         # Миграции для processing_storage
        └── 001_initial.py
```

#### 1.3 Initial миграции из текущих DDL

Текущие DDL находятся в:
- `tg_parser/storage/sqlite/schemas/ingestion_storage.py`
- `tg_parser/storage/sqlite/schemas/raw_storage.py`
- `tg_parser/storage/sqlite/schemas/processing_storage.py`

Создать initial миграции, которые создают текущую схему.

#### 1.4 CLI интеграция
```bash
# Новые команды
tg-parser db upgrade      # Применить миграции
tg-parser db downgrade    # Откатить миграцию
tg-parser db current      # Показать текущую версию
tg-parser db history      # Показать историю миграций
```

#### 1.5 Обновить init команду
```python
# cli/init_cmd.py
# При инициализации использовать Alembic для создания схемы
async def init_database():
    # Вместо прямого создания таблиц
    # Использовать alembic upgrade head
    pass
```

#### 1.6 Тесты
- [ ] Test: миграция на пустую БД
- [ ] Test: upgrade/downgrade цикл
- [ ] Test: multi-database sync
- [ ] Test: CLI команды

### Критерии готовности
- [ ] Alembic настроен для 3 SQLite баз
- [ ] Initial миграции созданы и работают
- [ ] CLI `init` использует Alembic
- [ ] CLI `db` команды работают
- [ ] Тесты миграций проходят (минимум 6)

---

## 🎯 Задача 2: Архивация устаревших docs (30 минут)

### Файлы для архивации

```bash
# Создать папку архива
mkdir -p docs/notes/archive/

# Переместить устаревшие файлы
mv docs/notes/current-state.md docs/notes/archive/current-state-v2.md
```

### Файлы для проверки на актуальность
- [ ] `PROCESSING_COMPLETE.md` — возможно архивировать
- [ ] `SESSION*_COMPLETE.md` — оставить как есть
- [ ] `docs/notes/README.md` — обновить ссылки

---

## 🎯 Задача 3: Обновить current-state.md (1 час)

### Создать новый current-state.md для v3.0.0

```markdown
# TG_parser Current State

**Version**: 3.0.0 (Released)  
**Updated**: 29 декабря 2025

## Архитектура
- Multi-Agent Architecture
- 4 агента (Orchestrator, Processing, Topicization, Export)
- Agent State Persistence
- Agent Observability

## Компоненты
...
```

---

## 🎯 Задача 4: Retry параметры в config (1 час)

### Текущая проблема
Retry параметры hardcoded в коде:
- `max_retries = 3`
- `backoff_base = 1.0`
- `backoff_max = 60.0`

### Решение

```python
# tg_parser/core/settings.py

class RetrySettings(BaseSettings):
    """Настройки retry для LLM и других операций."""
    
    max_attempts: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    jitter: float = 0.3
    
    model_config = SettingsConfigDict(
        env_prefix="RETRY_",
    )

# .env
RETRY_MAX_ATTEMPTS=5
RETRY_BACKOFF_BASE=2.0
```

### Файлы для обновления
- [ ] `tg_parser/core/settings.py` — добавить RetrySettings
- [ ] `tg_parser/llm/base_client.py` — использовать settings
- [ ] `.env.example` — добавить примеры

---

## 📊 Критерии успеха сессии

| Задача | Критерий | Тесты |
|--------|----------|-------|
| Alembic | Multi-DB миграции работают | 6+ |
| Archive | Устаревшие docs в archive/ | — |
| State | current-state.md v3.0.0 | — |
| Retry | Конфигурируемые параметры | 2+ |

**Итого**: 8+ новых тестов

---

## 🔗 Зависимости

### Что блокирует эта сессия
- **Session 24**: PostgreSQL Support (требует Alembic)
- Любые изменения схемы БД

### Что нужно для старта
- v3.0.0 релиз — ✅ DONE
- Понимание текущей схемы — смотри `tg_parser/storage/sqlite/schemas/`

---

## 📁 Ключевые файлы

### Для изучения
```
tg_parser/storage/sqlite/schemas/
├── ingestion_storage.py    # DDL для ingestion
├── raw_storage.py          # DDL для raw
└── processing_storage.py   # DDL для processing

tg_parser/storage/sqlite/database.py  # Database config
tg_parser/core/settings.py            # Settings
```

### Для создания
```
migrations/
├── alembic.ini
├── env.py
└── versions/
    └── ...

docs/notes/archive/
└── current-state-v2.md

docs/notes/current-state.md  # Новый
```

---

## 📝 Примечания

### Особенности multi-database Alembic

У нас 3 отдельные SQLite базы данных. Варианты:
1. **Отдельные alembic.ini** — 3 конфигурации
2. **Multi-database env.py** — один env.py с логикой выбора
3. **Единая БД** — объединить в одну (BREAKING CHANGE)

**Рекомендация**: Вариант 2 — один env.py с multi-database support.

### Пример multi-database Alembic

```python
# migrations/env.py
from alembic import context
from tg_parser.storage.sqlite.database import DatabaseConfig

# Определяем какую БД мигрируем
db_name = context.config.get_main_option("db_name")

databases = {
    "ingestion": "ingestion_state.sqlite",
    "raw": "raw_storage.sqlite", 
    "processing": "processing_storage.sqlite",
}
```

---

## ✅ Checklist для начала работы

1. [ ] Прочитать этот prompt
2. [ ] Изучить текущие DDL в `schemas/`
3. [ ] Изучить `database.py`
4. [ ] Установить alembic: `poetry add alembic`
5. [ ] Создать структуру migrations/
6. [ ] Реализовать multi-database env.py
7. [ ] Создать initial миграции
8. [ ] Добавить CLI команды `db`
9. [ ] Написать тесты
10. [ ] Архивировать старые docs
11. [ ] Создать новый current-state.md
12. [ ] Добавить RetrySettings

---

**Готов к Session 22!** 🚀

