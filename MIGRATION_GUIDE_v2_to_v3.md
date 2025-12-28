# Migration Guide: v2.x → v3.0

Руководство по миграции TG_parser с версии 2.x (v1.2) на версию 3.0.

---

## 🎉 Что нового в v3.0

### HTTP API (FastAPI)

v3.0 добавляет полноценный HTTP API для интеграции с внешними системами:

| Endpoint | Описание |
|----------|----------|
| `POST /api/v1/process` | Запуск обработки канала |
| `GET /api/v1/status/{job_id}` | Статус задачи |
| `POST /api/v1/export` | Экспорт данных |
| `GET /api/v1/agents` | Список агентов |
| `GET /metrics` | Prometheus метрики |
| `GET /status/detailed` | Детальная диагностика |

### Agents SDK

Новая архитектура на базе OpenAI Agents SDK:

- **TGProcessingAgent** — агент обработки сообщений
- **TopicizationAgent** — агент кластеризации тем
- **ExportAgent** — агент экспорта
- **OrchestratorAgent** — координатор агентов

### Multi-Agent Architecture

Специализированные агенты с протоколом handoff:

```python
# Пример использования агентов
from tg_parser.agents import AgentRegistry, ProcessingAgent

registry = AgentRegistry()
agent = ProcessingAgent()
await agent.initialize()
registry.register(agent)
```

### Agent Persistence

Сохранение состояния агентов в SQLite:

- Состояние агентов
- История задач
- История handoffs
- Агрегированная статистика

### Agent Observability

Мониторинг и отладка агентов:

- CLI команды: `agents list`, `agents status`, `agents history`
- API endpoints: `/api/v1/agents/*`
- Архивирование истории

### Production Features

- **Prometheus Metrics** — `/metrics` endpoint
- **Background Scheduler** — автоматическая очистка и health checks
- **Health Checks v2** — детальная диагностика компонентов
- **API Security** — API Key auth, Rate Limiting

---

## 📋 Checklist миграции

### 1. Обновление зависимостей

```bash
# Обновить requirements
pip install -r requirements.txt

# Переустановить пакет
pip install -e .
```

Новые зависимости в v3.0:
- `fastapi>=0.115`
- `uvicorn[standard]>=0.32`
- `prometheus-fastapi-instrumentator`
- `apscheduler`
- `openai>=1.70` (с Agents SDK)

### 2. Обновление .env файла

**Добавьте новые переменные** (опционально):

```env
# v3.0: HTTP API Configuration

# API Server
API_HOST=0.0.0.0
API_PORT=8000

# Security (опционально)
API_KEY=your-secret-api-key-here
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_PERIOD=60

# Metrics & Monitoring
METRICS_ENABLED=true

# Scheduler
SCHEDULER_ENABLED=true
SCHEDULER_CLEANUP_INTERVAL_HOURS=24
SCHEDULER_HEALTH_CHECK_INTERVAL_MINUTES=5

# Agent Configuration
AGENT_RETENTION_DAYS=14
AGENT_STATS_ENABLED=true
AGENT_ARCHIVE_PATH=./data/archives
```

> ✅ **Обратная совместимость**: Если вы не добавите новые переменные, v3.0 будет работать в режиме CLI как v2.x.

### 3. Миграция баз данных

v3.0 добавляет новые таблицы для агентов. Миграция выполняется **автоматически** при первом запуске:

```bash
# При первом запуске API или CLI схема обновится автоматически
python -m tg_parser.cli api --port 8000
```

Новые таблицы:
- `agent_states` — состояние агентов
- `task_history` — история задач
- `agent_daily_stats` — дневная статистика
- `handoff_history` — история handoffs
- `jobs` — задачи API

> ⚠️ **Важно**: Существующие данные (raw_messages, processed_documents, topics) сохраняются без изменений.

### 4. Обновление скриптов автоматизации

**CLI команды не изменились** — все существующие скрипты работают:

```bash
# Эти команды работают как в v2.x
python -m tg_parser.cli ingest --source @channel
python -m tg_parser.cli process --channel @channel
python -m tg_parser.cli topicize --channel @channel
python -m tg_parser.cli export --channel @channel
```

**Новые команды** (опционально):

```bash
# Запуск HTTP API
python -m tg_parser.cli api --port 8000

# Мониторинг агентов
python -m tg_parser.cli agents list
python -m tg_parser.cli agents status ProcessingAgent
python -m tg_parser.cli agents history ProcessingAgent --limit 20
```

---

## ⚠️ Breaking Changes

### Минимальные breaking changes

v3.0 спроектирована с максимальной обратной совместимостью.

| Аспект | v2.x | v3.0 | Совместимость |
|--------|------|------|---------------|
| CLI команды | ✅ | ✅ | Полная |
| .env файл | ✅ | ✅ + новые опции | Полная |
| Структура БД | v2 tables | v2 + agent tables | Полная |
| Python API | `run_processing()` | `run_processing()` + Agents | Полная |

### Deprecations

1. **Direct LLM client usage** — рекомендуется использовать через Agents SDK:

```python
# До (v2.x) - всё ещё работает
from tg_parser.processing import create_processing_pipeline
pipeline = create_processing_pipeline(...)

# После (v3.0) - рекомендуется
from tg_parser.agents import ProcessingAgent
agent = ProcessingAgent()
await agent.initialize()
result = await agent.process(input_data)
```

---

## 🔧 Новые CLI команды

### `api` команда

Запуск HTTP API сервера:

```bash
# Запуск с настройками по умолчанию
python -m tg_parser.cli api

# С кастомным портом
python -m tg_parser.cli api --port 9000 --host 0.0.0.0
```

### `agents` группа команд

| Команда | Описание |
|---------|----------|
| `agents list` | Список всех агентов |
| `agents status <name>` | Детальный статус агента |
| `agents history <name>` | История выполнения задач |
| `agents handoffs --stats` | Статистика handoffs |
| `agents cleanup` | Очистка старых записей |
| `agents archives` | Список архивов |

### Примеры использования

```bash
# Список активных агентов
python -m tg_parser.cli agents list --active

# Статистика за 7 дней
python -m tg_parser.cli agents status ProcessingAgent --days 7

# История ошибок
python -m tg_parser.cli agents history ProcessingAgent --errors --limit 50

# Очистка с архивированием
python -m tg_parser.cli agents cleanup --archive --force
```

---

## 🌐 HTTP API

### Запуск сервера

```bash
# Development
python -m tg_parser.cli api --port 8000

# Production с Gunicorn
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 "tg_parser.api:create_app()"

# Docker
docker run -p 8000:8000 -v $(pwd)/.env:/app/.env:ro tg_parser:v3.0
```

### Основные endpoints

```bash
# Health check
curl http://localhost:8000/health

# Детальный статус
curl http://localhost:8000/status/detailed

# Запуск обработки
curl -X POST http://localhost:8000/api/v1/process \
  -H "Content-Type: application/json" \
  -d '{"channel_id": "my_channel", "concurrency": 5}'

# Статус задачи
curl http://localhost:8000/api/v1/status/job-123

# Список агентов
curl http://localhost:8000/api/v1/agents

# Prometheus метрики
curl http://localhost:8000/metrics
```

### Authentication (опционально)

Если установлен `API_KEY` в .env:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/api/v1/process
```

---

## 📊 Prometheus Metrics

v3.0 экспортирует метрики в формате Prometheus:

### Доступные метрики

| Метрика | Тип | Описание |
|---------|-----|----------|
| `tg_parser_agent_tasks_total` | Counter | Всего задач по агентам |
| `tg_parser_agent_task_duration_seconds` | Histogram | Время выполнения задач |
| `tg_parser_messages_processed_total` | Counter | Обработанные сообщения |
| `tg_parser_llm_requests_total` | Counter | Запросы к LLM |
| `tg_parser_active_agents` | Gauge | Активные агенты |
| `tg_parser_scheduler_tasks_total` | Counter | Задачи scheduler |
| `http_requests_total` | Counter | HTTP запросы |
| `http_request_duration_seconds` | Histogram | Время HTTP запросов |

### Интеграция с Grafana

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'tg_parser'
    static_configs:
      - targets: ['localhost:8000']
```

---

## 🐳 Docker (обновлено в v3.0)

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  tg_parser_api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - API_PORT=8000
      - METRICS_ENABLED=true
    volumes:
      - ./.env:/app/.env:ro
      - ./data:/app/data
    command: ["api", "--host", "0.0.0.0"]
```

```bash
docker-compose up -d
curl http://localhost:8000/health
```

---

## 💡 Рекомендации

### Когда использовать HTTP API

| Use Case | Рекомендуется |
|----------|---------------|
| Интеграция с внешними системами | ✅ HTTP API |
| Автоматизация через CI/CD | ✅ HTTP API |
| Одноразовая обработка | CLI |
| Интерактивная работа | CLI |
| Мониторинг в production | ✅ HTTP API + Prometheus |

### Настройка для production

```env
# Production settings
API_KEY=<strong-random-key>
RATE_LIMIT_REQUESTS=1000
METRICS_ENABLED=true
SCHEDULER_ENABLED=true
AGENT_RETENTION_DAYS=30
```

---

## 📚 Дополнительные ресурсы

- [docs/architecture.md](docs/architecture.md) — архитектура v3.0
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — руководство пользователя
- [LLM_SETUP_GUIDE.md](LLM_SETUP_GUIDE.md) — настройка LLM провайдеров
- [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) — план развития

---

## ❓ FAQ

### Q: Нужно ли переобрабатывать существующие документы?

**A:** Нет, существующие ProcessedDocument'ы остаются валидными. Новые агенты просто предоставляют альтернативный способ обработки.

### Q: Можно ли использовать только CLI без API?

**A:** Да! CLI полностью функционален как в v2.x. API — опциональный компонент.

### Q: Как откатиться на v2.x если что-то пойдёт не так?

**A:** 
1. Данные совместимы — просто установите v2.x
2. Новые таблицы агентов не влияют на основной функционал
3. `.env` совместим — новые переменные просто игнорируются

### Q: Нужен ли API ключ для локального использования?

**A:** Нет, если `API_KEY` не установлен, API работает без аутентификации.

---

**Version**: 1.0  
**Created**: 28 декабря 2025

