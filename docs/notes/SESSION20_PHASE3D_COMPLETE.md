# Session 20: Phase 3D — Advanced Features

**Дата:** 28 декабря 2025  
**Версия:** v3.0.0-alpha.4  
**Статус:** ✅ Завершено

---

## 📋 Цели сессии

Phase 3D добавляет продвинутые функции для production-окружения:
- Prometheus-совместимые метрики
- Background scheduled tasks
- Улучшенные health checks

---

## ✅ Что реализовано

### 1. Prometheus Metrics (`/metrics`)

**Новый файл:** `tg_parser/api/metrics.py`

Prometheus-совместимые метрики для мониторинга:

#### HTTP Metrics (автоматические)
- `tg_parser_http_requests_total` — общее количество HTTP запросов
- `tg_parser_http_request_duration_seconds` — latency запросов
- `tg_parser_http_request_size_bytes` — размер запросов
- `tg_parser_http_response_size_bytes` — размер ответов
- `tg_parser_http_requests_inprogress` — запросы в обработке

#### Custom Metrics
- `tg_parser_agent_tasks_total` — задачи агентов по типу и статусу
- `tg_parser_agent_task_duration_seconds` — время выполнения задач
- `tg_parser_agents_active` — активные агенты по типу
- `tg_parser_messages_processed_total` — обработанные сообщения
- `tg_parser_topics_created_total` — созданные топики
- `tg_parser_llm_requests_total` — запросы к LLM
- `tg_parser_llm_request_duration_seconds` — latency LLM
- `tg_parser_llm_tokens_total` — использованные токены
- `tg_parser_jobs_total` — задачи API
- `tg_parser_jobs_active` — активные задачи
- `tg_parser_scheduler_tasks_total` — выполнения scheduled tasks

#### Helper функции
```python
from tg_parser.api.metrics import (
    record_agent_task,
    record_message_processed,
    record_llm_request,
    record_scheduler_task,
    update_active_agents,
    update_active_jobs,
)

# Записать выполнение задачи агента
record_agent_task("processing_agent", "process", success=True, duration_seconds=1.5)

# Записать обработку сообщения
record_message_processed("labdiagnostica", success=True)

# Записать запрос к LLM
record_llm_request("openai", "gpt-4", success=True, duration_seconds=2.5, 
                   prompt_tokens=100, completion_tokens=50)
```

### 2. Background Scheduler

**Новый файл:** `tg_parser/api/scheduler.py`

APScheduler интеграция для периодических задач:

```python
from tg_parser.api.scheduler import get_scheduler, BackgroundScheduler

scheduler = get_scheduler()

# Добавить задачу
async def my_task():
    ...

scheduler.add_task("my_task", my_task, interval_seconds=3600)

# Получить список задач
tasks = scheduler.get_tasks()
# [{"id": "my_task", "name": "my_task", "pending": False, "next_run": "...", "trigger": "interval[1:00:00]"}]
```

#### Встроенные задачи

1. **cleanup_expired_records** — очистка устаревших task_history и handoff_history
   - Интервал: 24 часа (настраивается)
   - Опциональное архивирование перед удалением

2. **health_check** — периодическая проверка здоровья
   - Интервал: 5 минут (настраивается)
   - Логирует warnings для нездоровых компонентов

### 3. Health Checks v2

**Новый файл:** `tg_parser/api/health_checks.py`

Улучшенные проверки здоровья компонентов:

#### Endpoints

| Endpoint | Описание |
|----------|----------|
| `GET /health` | Базовая проверка (для load balancers) |
| `GET /status` | Статус с компонентами и статистикой |
| `GET /status/detailed` | Детальная информация по каждому компоненту |
| `GET /scheduler` | Статус background scheduler |

#### Проверяемые компоненты

1. **Database** — подключение, latency, количество таблиц, размер файла
2. **LLM Provider** — доступность API key, ping к API
3. **Agent Registry** — количество агентов, активные агенты
4. **Scheduler** — статус, список задач

```json
// GET /status/detailed
{
  "status": "ok",
  "version": "processing:v1.0.0",
  "timestamp": "2025-12-28T12:00:00+00:00",
  "components": {
    "database": {
      "status": "ok",
      "latency_ms": 0.5,
      "details": {
        "path": "/path/to/db.sqlite",
        "size_mb": 1.23,
        "tables": 5
      }
    },
    "llm": {
      "status": "ok",
      "provider": "openai",
      "model": "gpt-4",
      "latency_ms": 150.2
    },
    "agents": {
      "status": "ok",
      "details": {
        "total_agents": 4,
        "active_agents": 3,
        "agent_types": ["orchestrator", "processing", "topicization"]
      }
    },
    "scheduler": {
      "status": "ok",
      "details": {
        "running": true,
        "tasks_count": 2,
        "tasks": ["cleanup_expired_records", "health_check"]
      }
    }
  }
}
```

### 4. Новые настройки

```python
# Prometheus Metrics
metrics_enabled: bool = True

# Background Scheduler
scheduler_enabled: bool = True
scheduler_cleanup_interval_hours: int = 24
scheduler_health_check_interval_minutes: int = 5

# Ollama
ollama_base_url: str = "http://localhost:11434"

# Google API Key (alias)
google_api_key: str | None = None
```

### 5. Интеграция в API

Автоматическая инициализация в `tg_parser/api/main.py`:

- Prometheus metrics включаются при старте приложения
- Background scheduler стартует в lifespan
- Graceful shutdown для scheduler

---

## 📁 Новые и изменённые файлы

### Новые файлы

| Файл | Описание |
|------|----------|
| `tg_parser/api/metrics.py` | Prometheus metrics module |
| `tg_parser/api/scheduler.py` | Background scheduler |
| `tg_parser/api/health_checks.py` | Health check implementations |
| `tests/test_phase3d_advanced.py` | 26 тестов для Phase 3D |

### Изменённые файлы

| Файл | Изменения |
|------|-----------|
| `tg_parser/api/main.py` | Интеграция metrics и scheduler |
| `tg_parser/api/routes/health.py` | Новые endpoints, real health checks |
| `tg_parser/config/settings.py` | Новые настройки |
| `tg_parser/agents/persistence.py` | Новые методы cleanup |
| `tg_parser/storage/sqlite/handoff_history_repo.py` | `list_expired()`, `cleanup_expired()` |
| `tg_parser/storage/sqlite/task_history_repo.py` | `list_expired()` alias |
| `requirements.txt` | prometheus-fastapi-instrumentator, apscheduler |
| `tests/conftest.py` | Disable metrics для тестов |
| `tests/test_api.py` | Обновлён тест status |

---

## 🧪 Тесты

**Всего тестов:** 366 (было 340)  
**Новых тестов:** 26  
**Статус:** ✅ Все проходят

### Новые тесты в `test_phase3d_advanced.py`

1. **TestPrometheusMetrics** (6 тестов)
   - Создание instrumentator
   - Запись метрик агентов, сообщений, LLM

2. **TestHealthChecks** (5 тестов)
   - Проверка базы данных
   - Проверка LLM provider
   - Проверка scheduler
   - Все компоненты

3. **TestBackgroundScheduler** (7 тестов)
   - Создание, добавление, удаление задач
   - Start/shutdown
   - Singleton pattern
   - Default tasks setup

4. **TestHealthEndpoints** (4 теста)
   - /health, /status, /status/detailed, /scheduler

5. **TestMetricsIntegration** (1 тест)
   - App creation with metrics

6. **TestSchedulerIntegration** (1 тест)
   - Cleanup task function

7. **TestPhase3DSettings** (2 теста)
   - Default settings
   - Environment override

---

## 📊 Новые зависимости

```
prometheus-fastapi-instrumentator>=7.0
apscheduler>=3.10
```

---

## 🔧 Использование

### Запуск API с метриками

```bash
# Метрики включены по умолчанию
uvicorn tg_parser.api.main:app --host 0.0.0.0 --port 8000

# Метрики доступны на /metrics
curl http://localhost:8000/metrics
```

### Prometheus конфигурация

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'tg_parser'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### Health checks

```bash
# Базовая проверка (для load balancers)
curl http://localhost:8000/health

# Детальный статус
curl http://localhost:8000/status/detailed

# Статус scheduler
curl http://localhost:8000/scheduler
```

### Отключение функций

```bash
# Через переменные окружения
METRICS_ENABLED=false uvicorn tg_parser.api.main:app
SCHEDULER_ENABLED=false uvicorn tg_parser.api.main:app

# Изменение интервалов
SCHEDULER_CLEANUP_INTERVAL_HOURS=48
SCHEDULER_HEALTH_CHECK_INTERVAL_MINUTES=10
```

---

## 🚀 Следующие шаги (Phase 3 Finalization)

1. **E2E Integration Tests**
   - `test_full_cli_workflow` — полный CLI workflow
   - `test_full_api_workflow` — полный API workflow

2. **OpenTelemetry Tracing** (опционально)
   - Distributed tracing для multi-agent workflows

3. **Grafana Dashboard** (опционально)
   - JSON export для Grafana

4. **Documentation Update**
   - Обновить README
   - Добавить примеры мониторинга

---

## ✅ Чеклист завершения

- [x] Prometheus metrics endpoint `/metrics`
- [x] Custom metrics для agents, LLM, jobs
- [x] Background scheduler с APScheduler
- [x] Cleanup expired records task
- [x] Health check v2 с реальными проверками
- [x] Detailed status endpoint
- [x] Scheduler status endpoint
- [x] Новые настройки в Settings
- [x] 26 новых тестов
- [x] Все 366 тестов проходят
- [x] Requirements обновлены
- [x] Документация создана

---

**Phase 3D завершена успешно! 🎉**

Версия: **v3.0.0-alpha.4**

