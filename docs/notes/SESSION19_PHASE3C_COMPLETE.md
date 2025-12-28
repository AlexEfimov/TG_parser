# Session 19: Phase 3C — Agent Observability

**Дата:** 28 декабря 2025  
**Версия:** v3.0.0-alpha.3  
**Статус:** ✅ Завершено

---

## 📋 Что было сделано

### 1. CLI группа `agents`

Новая группа команд для мониторинга агентов:

```bash
# Список агентов
tg-parser agents list
tg-parser agents list --type processing --active
tg-parser agents list --format json

# Статистика агента
tg-parser agents status ProcessingAgent
tg-parser agents status ProcessingAgent --days 30

# История задач
tg-parser agents history ProcessingAgent
tg-parser agents history ProcessingAgent --limit 50 --errors

# Очистка истёкших записей
tg-parser agents cleanup --dry-run
tg-parser agents cleanup --archive
tg-parser agents cleanup --archive --include-handoffs

# Статистика handoff'ов
tg-parser agents handoffs --stats
tg-parser agents handoffs --agent OrchestratorAgent

# Список архивов
tg-parser agents archives
```

### 2. API Endpoints

Новый роутер `/api/v1/agents`:

```
GET  /api/v1/agents                    — список агентов
GET  /api/v1/agents/{name}             — информация об агенте
GET  /api/v1/agents/{name}/stats       — статистика агента за период
GET  /api/v1/agents/{name}/history     — история задач с пагинацией
GET  /api/v1/agents/stats/handoffs     — статистика handoff'ов
```

### 3. Response Models (Pydantic)

Типизированные модели ответов:

- **AgentListResponse** — список агентов с метаданными
- **AgentInfoResponse** — полная информация об агенте
- **AgentStatsResponse** — статистика за период
- **TaskHistoryResponse** — история задач с пагинацией
- **HandoffStatsResponse** — статистика handoff'ов

### 4. AgentHistoryArchiver

Класс для архивации истёкших записей:

```python
class AgentHistoryArchiver:
    """
    Архивирует истёкшие записи task_history и handoff_history
    в NDJSON.gz файлы для долгосрочного хранения.
    """
    
    async def archive_expired_tasks(self) -> ArchiveResult:
        """Архивировать истёкшие записи task_history."""
        
    async def archive_expired_handoffs(self) -> ArchiveResult:
        """Архивировать старые записи handoff_history."""
        
    def list_archives(self) -> list[ArchiveInfo]:
        """Получить список архивных файлов."""
```

Формат имени файла: `task_history_20251228_123456.ndjson.gz`

### 5. Новые файлы

```
tg_parser/agents/archiver.py       — AgentHistoryArchiver
tg_parser/cli/agents_cmd.py        — CLI группа agents
tg_parser/api/routes/agents.py     — API endpoints
tests/test_agents_observability.py — 15 тестов
```

### 6. Обновлённые файлы

```
tg_parser/cli/app.py               — подключение agents subcommand
tg_parser/api/routes/__init__.py   — добавлен agents_router
tg_parser/api/main.py              — подключение agents_router
DEVELOPMENT_ROADMAP.md             — Phase 3C отмечена как завершённая
```

---

## 📊 Метрики

| Показатель | Значение |
|------------|----------|
| Новых файлов | 4 |
| Обновлённых файлов | 10+ |
| Новых тестов | 15 |
| Всего тестов | 340 |
| CLI команд добавлено | 6 |
| API endpoints добавлено | 5 |

---

## 🧪 Тестирование

### Новые тесты

```
tests/test_agents_observability.py:
- test_cli_agents_list                     — список агентов
- test_cli_agents_list_with_filters        — фильтрация по типу/статусу
- test_cli_agents_status                   — статистика агента
- test_cli_agents_history                  — история задач
- test_cli_agents_cleanup_dry_run          — очистка (dry run)
- test_cli_agents_cleanup_with_archive     — очистка с архивацией
- test_api_agents_list                     — API: список агентов
- test_api_agents_info                     — API: информация об агенте
- test_api_agents_stats                    — API: статистика
- test_api_agents_history                  — API: история задач
- test_api_handoff_stats                   — API: статистика handoff'ов
- test_archiver_tasks                      — архивация task_history
- test_archiver_handoffs                   — архивация handoff_history
- test_archiver_list_archives              — список архивов
- test_archiver_empty                      — архивация при отсутствии записей
```

### Запуск тестов

```bash
# Все тесты
pytest

# Только observability тесты
pytest tests/test_agents_observability.py -v

# С покрытием
pytest --cov=tg_parser.agents --cov=tg_parser.cli.agents_cmd --cov=tg_parser.api.routes.agents
```

### Результат

```
340 passed in 45.23s ✅
```

---

## 💻 Примеры использования

### CLI

```bash
# Активировать окружение
source .venv/bin/activate

# Список активных агентов
tg-parser agents list --active

# Статистика ProcessingAgent за месяц
tg-parser agents status ProcessingAgent --days 30

# История с ошибками
tg-parser agents history ProcessingAgent --errors --limit 10

# Очистка с архивацией (dry run сначала)
tg-parser agents cleanup --dry-run
tg-parser agents cleanup --archive

# Статистика handoff'ов
tg-parser agents handoffs --stats
```

### API

```bash
# Список агентов
curl http://localhost:8000/api/v1/agents

# Информация об агенте
curl http://localhost:8000/api/v1/agents/ProcessingAgent

# Статистика за 7 дней
curl "http://localhost:8000/api/v1/agents/ProcessingAgent/stats?days=7"

# История задач (пагинация)
curl "http://localhost:8000/api/v1/agents/ProcessingAgent/history?limit=20&offset=0"

# Статистика handoff'ов
curl http://localhost:8000/api/v1/agents/stats/handoffs
```

---

## 🔧 Конфигурация

Новые переменные окружения:

```env
# Архивация (Phase 3C)
AGENT_ARCHIVE_ENABLED=true           # Включить архивацию
AGENT_ARCHIVE_PATH=./data/archives   # Путь к архивам
```

---

## 📁 Структура архивов

```
data/archives/
├── task_history_20251228_143500.ndjson.gz      # Задачи
├── task_history_20251229_100000.ndjson.gz
├── handoff_history_20251228_143500.ndjson.gz   # Handoff'ы
└── handoff_history_20251229_100000.ndjson.gz
```

Формат NDJSON (каждая строка — JSON объект):
```json
{"id": "task_abc123", "agent_name": "ProcessingAgent", "task_type": "process_message", ...}
{"id": "task_def456", "agent_name": "ProcessingAgent", "task_type": "process_message", ...}
```

---

## 🎯 Следующие шаги (Phase 3D)

### Prometheus Metrics
- Endpoint `/metrics` в Prometheus формате
- Counter: `tg_parser_tasks_total{agent, status}`
- Histogram: `tg_parser_task_duration_seconds{agent}`
- Gauge: `tg_parser_active_agents`

### Background Scheduled Tasks
- APScheduler для фоновой очистки
- Настройка интервала через env
- Graceful shutdown

### Health Check v2
- Детальная проверка компонентов
- Статус каждого репозитория
- LLM provider health

### Опционально
- OpenTelemetry Tracing
- Simple Dashboard (HTML страница со статистикой)

---

## 📚 Обновлённая документация

- `CHANGELOG.md` — добавлена секция 3.0.0-alpha.3
- `DOCUMENTATION_INDEX.md` — добавлена ссылка на SESSION19
- `README.md` — добавлена секция agents CLI и обновлена версия
- `docs/architecture.md` — добавлена секция Phase 3C
- `docs/notes/README.md` — обновлён статус сессий
- `tests/README.md` — обновлена структура тестов

---

## ✅ Критерии завершения Phase 3C

| Критерий | Статус |
|----------|--------|
| CLI `agents list` | ✅ |
| CLI `agents status` | ✅ |
| CLI `agents history` | ✅ |
| CLI `agents cleanup` | ✅ |
| CLI `agents handoffs` | ✅ |
| CLI `agents archives` | ✅ |
| API `/agents` endpoints | ✅ |
| AgentHistoryArchiver | ✅ |
| 15+ новых тестов | ✅ |
| Документация обновлена | ✅ |

**Phase 3C: Agent Observability — ЗАВЕРШЕНА** ✅

---

**Следующая сессия:** Session 20 (Phase 3D — Advanced Features)  
**Начни с:** `START_PROMPT_SESSION20_PHASE3D.md`
