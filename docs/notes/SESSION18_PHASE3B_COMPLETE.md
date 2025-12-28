# Session 18: Phase 3B — Agent State Persistence

**Дата:** 28 декабря 2025  
**Версия:** v3.0.0-alpha.2  
**Статус:** ✅ Завершено

---

## 📋 Что было сделано

### 1. DDL для новых таблиц

Добавлены 4 новые таблицы в `processing_storage.sqlite`:

```sql
-- agent_states: состояние агентов и статистика
CREATE TABLE agent_states (
  name TEXT PRIMARY KEY,
  agent_type TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '1.0.0',
  description TEXT,
  capabilities_json TEXT NOT NULL,
  model TEXT,
  provider TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT,
  total_tasks_processed INTEGER NOT NULL DEFAULT 0,
  total_errors INTEGER NOT NULL DEFAULT 0,
  avg_processing_time_ms REAL NOT NULL DEFAULT 0.0,
  last_used_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- task_history: полная история задач с TTL
CREATE TABLE task_history (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  task_type TEXT NOT NULL,
  source_ref TEXT,
  channel_id TEXT,
  input_json TEXT NOT NULL,
  output_json TEXT,
  success INTEGER NOT NULL DEFAULT 1,
  error TEXT,
  processing_time_ms INTEGER,
  created_at TEXT NOT NULL,
  expires_at TEXT
);

-- agent_stats: агрегированная статистика по дням
CREATE TABLE agent_stats (
  agent_name TEXT NOT NULL,
  date TEXT NOT NULL,
  task_type TEXT NOT NULL,
  total_tasks INTEGER NOT NULL DEFAULT 0,
  successful_tasks INTEGER NOT NULL DEFAULT 0,
  failed_tasks INTEGER NOT NULL DEFAULT 0,
  total_processing_time_ms INTEGER NOT NULL DEFAULT 0,
  min_processing_time_ms INTEGER,
  max_processing_time_ms INTEGER,
  PRIMARY KEY (agent_name, date, task_type)
);

-- handoff_history: история handoffs между агентами
CREATE TABLE handoff_history (
  id TEXT PRIMARY KEY,
  source_agent TEXT NOT NULL,
  target_agent TEXT NOT NULL,
  task_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL,
  payload_json TEXT,
  context_json TEXT,
  result_json TEXT,
  error TEXT,
  processing_time_ms INTEGER,
  created_at TEXT NOT NULL,
  accepted_at TEXT,
  completed_at TEXT
);
```

### 2. Модели данных (ports.py)

Добавлены dataclass-ы:

- **AgentState** — состояние агента с метаданными и статистикой
- **TaskRecord** — запись о выполненной задаче с полным input/output
- **AgentDailyStats** — агрегированная статистика за день (с вычисляемыми свойствами)
- **HandoffRecord** — запись о handoff между агентами

### 3. Интерфейсы репозиториев (ports.py)

Добавлены абстрактные классы:

- **AgentStateRepo** — save, get, list_all, delete, update_statistics
- **TaskHistoryRepo** — record, get, list_by_agent, list_by_channel, cleanup_expired
- **AgentStatsRepo** — record, get_daily, get_range, get_summary
- **HandoffHistoryRepo** — record, update_status, get, list_by_agent, get_statistics

### 4. SQLite реализации

Созданы файлы:

- `tg_parser/storage/sqlite/agent_state_repo.py`
- `tg_parser/storage/sqlite/task_history_repo.py`
- `tg_parser/storage/sqlite/agent_stats_repo.py`
- `tg_parser/storage/sqlite/handoff_history_repo.py`

Все репозитории:
- Используют async SQLAlchemy
- Поддерживают JSON-сериализацию
- Следуют паттернам существующего кода

### 5. AgentPersistence Layer

Создан `tg_parser/agents/persistence.py`:

```python
class AgentPersistence:
    """Unified interface for agent state and history persistence."""
    
    async def save_agent_state(agent: BaseAgent) -> None
    async def load_agent_state(name: str) -> AgentState | None
    async def restore_agent_statistics(agent: BaseAgent) -> dict | None
    async def record_task(...) -> str | None
    async def record_handoff_request(request: HandoffRequest) -> None
    async def record_handoff_response(response: HandoffResponse) -> None
    async def cleanup_expired_tasks() -> int
    async def get_agent_summary(agent_name: str, days: int) -> dict
```

### 6. Интеграция с AgentRegistry

Обновлён `AgentRegistry`:

```python
class AgentRegistry:
    def __init__(self, persistence: AgentPersistence | None = None):
        self._persistence = persistence
    
    async def register_with_persistence(agent: BaseAgent) -> None
    async def unregister_with_persistence(name: str) -> bool
    async def record_task_completion_with_persistence(...) -> str | None
```

Добавлены функции:
- `get_registry(persistence=None)` — создание registry с persistence
- `set_registry_persistence(persistence)` — установка persistence для глобального registry

### 7. Конфигурация (settings.py)

Добавлены настройки:

```python
# Agent State Persistence (Phase 3B)
agent_retention_days: int = 14
agent_retention_mode: str = "delete"  # delete | export
agent_archive_path: Path = Path("data/archive/task_history")
agent_stats_enabled: bool = True
agent_persistence_enabled: bool = True
```

### 8. Тесты

Создан `tests/test_agent_persistence.py` с 25 тестами:

- Модели: AgentState, TaskRecord, AgentDailyStats, HandoffRecord
- AgentPersistence: save, record_task, record_handoff, cleanup
- Registry с persistence: register, unregister, record_task
- SQLite repos: конвертация row ↔ model
- Retention: expires_at calculation, cleanup

---

## 📊 Статистика

| Метрика | До | После |
|---------|-----|-------|
| Тесты | 300 | 325 (+25) |
| Таблицы в processing_storage | 5 | 9 (+4) |
| Файлы storage/sqlite | 10 | 14 (+4) |
| Модели в ports.py | 7 | 11 (+4) |
| Интерфейсы в ports.py | 7 | 11 (+4) |

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                     AgentRegistry                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              AgentPersistence                        │   │
│  │  ┌───────────┐ ┌────────────┐ ┌─────────────────┐  │   │
│  │  │AgentState │ │TaskHistory │ │HandoffHistory   │  │   │
│  │  │   Repo    │ │   Repo     │ │    Repo         │  │   │
│  │  └─────┬─────┘ └─────┬──────┘ └───────┬─────────┘  │   │
│  │        │             │                │             │   │
│  │        └─────────────┼────────────────┘             │   │
│  │                      │                              │   │
│  │              ┌───────┴───────┐                      │   │
│  │              │  AgentStats   │                      │   │
│  │              │     Repo      │                      │   │
│  │              └───────────────┘                      │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │   processing_storage.sqlite   │
              │                              │
              │  • agent_states              │
              │  • task_history              │
              │  • agent_stats               │
              │  • handoff_history           │
              └──────────────────────────────┘
```

---

## 🔧 Использование

### Создание persistence layer

```python
from tg_parser.agents import AgentPersistence, AgentRegistry
from tg_parser.storage.sqlite import (
    SQLiteAgentStateRepo,
    SQLiteTaskHistoryRepo,
    SQLiteAgentStatsRepo,
    SQLiteHandoffHistoryRepo,
)

# Создать репозитории
agent_state_repo = SQLiteAgentStateRepo(session_factory)
task_history_repo = SQLiteTaskHistoryRepo(session_factory, default_retention_days=14)
agent_stats_repo = SQLiteAgentStatsRepo(session_factory)
handoff_repo = SQLiteHandoffHistoryRepo(session_factory)

# Создать persistence layer
persistence = AgentPersistence(
    agent_state_repo=agent_state_repo,
    task_history_repo=task_history_repo,
    agent_stats_repo=agent_stats_repo,
    handoff_history_repo=handoff_repo,
    retention_days=14,
    stats_enabled=True,
)

# Создать registry с persistence
registry = AgentRegistry(persistence=persistence)
```

### Регистрация агента с восстановлением статистики

```python
agent = ProcessingAgent(name="MainProcessor")

# Регистрация + сохранение + восстановление статистики
await registry.register_with_persistence(agent)
```

### Запись задачи с полным input/output

```python
task_id = await registry.record_task_completion_with_persistence(
    name="MainProcessor",
    task_type="process_message",
    input_data={"text": "Hello world", "source_ref": "tg_test_1"},
    output_data={"summary": "Greeting", "topics": ["hello"]},
    processing_time_ms=150.5,
    success=True,
)
```

### Очистка истёкших записей

```python
deleted = await persistence.cleanup_expired_tasks()
print(f"Cleaned up {deleted} expired records")
```

### Получение статистики агента

```python
summary = await persistence.get_agent_summary("MainProcessor", days=30)
print(f"Total tasks: {summary['total_tasks']}")
print(f"Success rate: {summary['success_rate']:.1%}")
print(f"Avg time: {summary['avg_processing_time_ms']:.0f}ms")
```

---

## 🧪 Тестирование

```bash
# Все тесты
python -m pytest tests/ -v

# Только тесты persistence
python -m pytest tests/test_agent_persistence.py -v

# С покрытием
python -m pytest tests/test_agent_persistence.py -v --cov=tg_parser.agents.persistence
```

---

## 📁 Изменённые/созданные файлы

### Созданные
- `tg_parser/storage/sqlite/agent_state_repo.py`
- `tg_parser/storage/sqlite/task_history_repo.py`
- `tg_parser/storage/sqlite/agent_stats_repo.py`
- `tg_parser/storage/sqlite/handoff_history_repo.py`
- `tg_parser/agents/persistence.py`
- `tests/test_agent_persistence.py`
- `docs/notes/SESSION18_PHASE3B_COMPLETE.md`

### Изменённые
- `tg_parser/storage/ports.py` — добавлены модели и интерфейсы
- `tg_parser/storage/sqlite/schemas/processing_storage.py` — добавлен DDL
- `tg_parser/storage/sqlite/__init__.py` — экспорт новых репозиториев
- `tg_parser/agents/registry.py` — интеграция с persistence
- `tg_parser/agents/__init__.py` — экспорт AgentPersistence
- `tg_parser/config/settings.py` — настройки retention

---

## 🎯 Следующие шаги (Phase 3C)

1. **CLI команда `tg-parser agents status`** — просмотр агентов и статистики
2. **API endpoints для агентов** — GET /api/v1/agents, GET /api/v1/agents/{name}/history
3. **Архивация в NDJSON** — экспорт перед удалением (mode=export)
4. **Scheduled cleanup** — автоматическая очистка по расписанию
5. **Dashboard metrics** — экспорт метрик для мониторинга

---

## ✅ Чеклист завершения

- [x] DDL для 4 новых таблиц
- [x] Модели данных в ports.py
- [x] Интерфейсы репозиториев
- [x] SQLite реализации всех репозиториев
- [x] AgentPersistence layer
- [x] Интеграция с AgentRegistry
- [x] Настройки retention в config
- [x] 25 новых тестов
- [x] Документация сессии
- [x] Все 325 тестов проходят

**Session 18 завершена! 🎉**

