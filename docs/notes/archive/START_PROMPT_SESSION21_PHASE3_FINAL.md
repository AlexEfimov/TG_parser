# Стартовый промпт для Session 21: Phase 3 Finalization

**Дата создания:** 28 декабря 2025  
**Предыдущая сессия:** Session 20 (Phase 3D — Advanced Features)  
**Версия проекта:** v3.0.0-alpha.4

---

## 📋 Контекст проекта

### Что такое TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

### Текущее состояние (v3.0.0-alpha.4)

| Компонент | Статус | Описание |
|-----------|--------|----------|
| **Ingestion** | ✅ Production | Telethon, snapshot mode, 846+ сообщений |
| **Processing** | ✅ Production | Multi-LLM (OpenAI, Anthropic, Gemini, Ollama) |
| **Topicization** | ✅ Production | Семантическая кластеризация |
| **Export** | ✅ Production | NDJSON/JSON для RAG |
| **HTTP API** | ✅ Production | FastAPI, Auth, Rate Limiting, Webhooks |
| **Agents SDK** | ✅ Production | TGProcessingAgent с tools |
| **Hybrid Mode** | ✅ Done | Agent + v1.2 pipeline |
| **Multi-Agent** | ✅ Done | Orchestrator, Processing, Topicization, Export Agents |
| **Agent Persistence** | ✅ Done | State, TaskHistory, Stats, HandoffHistory |
| **Agent Observability** | ✅ Done | CLI agents, API endpoints, Archiver |
| **Prometheus Metrics** | ✅ Done | `/metrics` endpoint, custom metrics |
| **Background Scheduler** | ✅ Done | APScheduler, cleanup, health checks |
| **Health Checks v2** | ✅ Done | DB, LLM, Agents, Scheduler checks |
| **Docker** | ✅ Production | Dockerfile + docker-compose.yml |
| **Тесты** | ✅ 366 | 100% проходят |

### Архитектура проекта (Phase 3D)

```
tg_parser/
├── agents/
│   ├── base.py                 # BaseAgent, AgentCapability, AgentType
│   ├── registry.py             # AgentRegistry (with persistence)
│   ├── persistence.py          # AgentPersistence layer
│   ├── archiver.py             # AgentHistoryArchiver
│   ├── orchestrator.py         # OrchestratorAgent
│   ├── processing_agent.py     # TGProcessingAgent (v2.0)
│   ├── tools/                  # Tools for agents
│   └── specialized/            # ProcessingAgent, TopicizationAgent, ExportAgent
│
├── api/
│   ├── main.py                 # FastAPI app with lifespan
│   ├── metrics.py              # Prometheus metrics ⭐ Phase 3D
│   ├── scheduler.py            # Background scheduler ⭐ Phase 3D
│   ├── health_checks.py        # Health check implementations ⭐ Phase 3D
│   ├── routes/
│   │   ├── agents.py           # Agent observability endpoints
│   │   ├── health.py           # Health endpoints (v2)
│   │   ├── process.py
│   │   └── export.py
│   ├── auth.py
│   ├── job_store.py
│   └── webhooks.py
│
├── cli/
│   ├── app.py                  # Main CLI app
│   ├── agents_cmd.py           # agents subcommand group
│   └── ...
│
├── storage/
│   └── sqlite/
│       ├── agent_state_repo.py
│       ├── task_history_repo.py
│       ├── agent_stats_repo.py
│       └── handoff_history_repo.py
```

### Завершённые фазы v3.0

| Фаза | Сессия | Что сделано |
|------|--------|-------------|
| **2A** | 14 | HTTP API skeleton (FastAPI, 8 endpoints) |
| **2B** | 14 | Agents SDK PoC (TGProcessingAgent, 3 basic tools) |
| **2C** | 14 | LLM-Enhanced Tools (analyze_text_deep, extract_topics_llm) |
| **2E** | 15 | Hybrid Mode (pipeline как tool агента) |
| **2F** | 16 | API Production (Auth, Rate Limiting, Webhooks, Persistent Jobs) |
| **3A** | 17 | Multi-Agent Architecture (Registry, Orchestrator, Specialized Agents) |
| **3B** | 18 | Agent State Persistence (State, TaskHistory, Stats, HandoffHistory) |
| **3C** | 19 | Agent Observability (CLI agents, API endpoints, Archiver) |
| **3D** | 20 | Advanced Features (Prometheus Metrics, Background Scheduler, Health Checks v2) |

---

## 🎯 Цель Session 21: Phase 3 Finalization

### Видение

Финализировать Phase 3 и подготовить проект к релизу v3.0.0:
- E2E Integration Tests для полных workflow
- Финальный polish документации
- Опционально: OpenTelemetry, Dashboard

### Предлагаемый scope

#### 1. **E2E Integration Tests** (Обязательно)

Реализовать полноценные E2E тесты вместо placeholder'ов:

**CLI Workflow Test:**
```python
# tests/test_e2e_full.py
async def test_full_cli_workflow():
    """
    Полный CLI workflow с реальной БД:
    1. init → ingest → process → topicize → export
    2. Проверка всех артефактов
    3. agents list/status/history
    """
```

**API Workflow Test:**
```python
async def test_full_api_workflow():
    """
    Полный API workflow с TestClient:
    1. POST /api/v1/process → poll status
    2. POST /api/v1/export → download
    3. GET /api/v1/agents/* endpoints
    4. GET /metrics, /status/detailed
    """
```

**Multi-Agent Workflow Test:**
```python
async def test_multi_agent_e2e():
    """
    Multi-Agent pipeline E2E:
    1. Создать агентов через Registry
    2. Запустить Orchestrator workflow
    3. Проверить handoffs и результаты
    4. Проверить persistence после workflow
    """
```

#### 2. **Документация v3.0** (Обязательно)

- Обновить README с полным описанием v3.0
- Создать MIGRATION_GUIDE_v2_to_v3.md
- Обновить docs/architecture.md с финальной схемой
- Проверить все примеры кода в документации

#### 3. **OpenTelemetry Tracing** (Опционально)

Если останется время:
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

# Distributed tracing для multi-agent workflows
# Span context propagation между агентами
# Integration с Jaeger/Zipkin
```

#### 4. **Grafana Dashboard** (Опционально)

- JSON export для Grafana dashboard
- Панели для основных метрик
- Алерты

---

## 📁 Ключевые файлы для изучения

### Phase 3D (Advanced Features)

- `tg_parser/api/metrics.py` — Prometheus metrics
- `tg_parser/api/scheduler.py` — Background scheduler
- `tg_parser/api/health_checks.py` — Health check implementations
- `tg_parser/api/routes/health.py` — Health endpoints

### Существующие E2E тесты

- `tests/test_e2e_pipeline.py` — базовый E2E тест
- `tests/test_agents_observability.py` — placeholder'ы для E2E (TODO)

### Документация

- `docs/notes/SESSION20_PHASE3D_COMPLETE.md` — результаты Phase 3D
- `DEVELOPMENT_ROADMAP.md` — план развития

---

## 🧪 Тесты

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
python -m pytest tests/ -v

# С покрытием
python -m pytest tests/ --cov=tg_parser --cov-report=term-missing

# Только E2E тесты
python -m pytest tests/test_e2e*.py -v
```

**Текущий статус:** 366 тестов, все проходят ✅

---

## 🔧 Настройка окружения

```bash
# Клонировать и настроить
cd TG_parser
source .venv/bin/activate

# Проверить версию
python --version  # Python 3.12.0

# Проверить тесты
python -m pytest tests/ --tb=short

# Запустить API для тестирования
python -m tg_parser.cli api --port 8000

# Проверить метрики
curl http://localhost:8000/metrics

# Проверить health
curl http://localhost:8000/status/detailed
```

---

## 📊 Зависимости

### Основные
- Python 3.12+
- OpenAI SDK (включая Agents SDK)
- FastAPI + Uvicorn
- SQLAlchemy 2.x (async)
- Pydantic v2
- Click (CLI)
- prometheus-fastapi-instrumentator
- apscheduler

### Для OpenTelemetry (опционально)
- `opentelemetry-api`
- `opentelemetry-sdk`
- `opentelemetry-instrumentation-fastapi`
- `opentelemetry-exporter-otlp`

---

## 🎯 Задачи Phase 3 Finalization

### Обязательные (MVP)

1. **E2E Integration Tests**
   - `test_full_cli_workflow` — полный CLI pipeline
   - `test_full_api_workflow` — полный API workflow
   - `test_multi_agent_e2e` — multi-agent pipeline
   - Минимум 5-10 новых E2E тестов

2. **Документация v3.0**
   - MIGRATION_GUIDE_v2_to_v3.md
   - Обновление README секции v3.0
   - Финальная ревизия docs/architecture.md

3. **Version bump**
   - pyproject.toml → v3.0.0
   - CHANGELOG.md → v3.0.0 release notes
   - Тегирование релиза

### Опциональные

4. **OpenTelemetry Tracing**
   - Distributed tracing setup
   - Agent span propagation
   - Jaeger/Zipkin integration

5. **Grafana Dashboard**
   - Dashboard JSON export
   - Key metrics panels
   - Alert rules

6. **Performance Optimization**
   - Profiling hot paths
   - Memory optimization
   - Connection pooling review

---

## ✅ Чеклист готовности

- [x] Все 366 тестов проходят
- [x] Документация обновлена до v3.0.0-alpha.4
- [x] Phase 3D полностью завершена
- [x] Prometheus Metrics работают
- [x] Background Scheduler работает
- [x] Health Checks v2 работают

---

## 📋 Placeholder'ы для реализации

В `tests/test_agents_observability.py` есть placeholder'ы:

```python
@pytest.mark.skip(reason="E2E test - requires full environment")
async def test_full_cli_workflow():
    """TODO: Implement full CLI workflow test."""
    pass

@pytest.mark.skip(reason="E2E test - requires full environment")
async def test_full_api_workflow():
    """TODO: Implement full API workflow test with TestClient."""
    pass
```

Эти тесты должны быть реализованы в Session 21.

---

## 🚀 Как начать

1. **Изучить существующие E2E тесты:**
   ```bash
   cat tests/test_e2e_pipeline.py
   ```

2. **Изучить placeholder'ы:**
   ```bash
   grep -n "TODO\|skip" tests/test_agents_observability.py
   ```

3. **Запустить API для ручного тестирования:**
   ```bash
   source .venv/bin/activate
   python -m tg_parser.cli api --port 8000
   ```

4. **Проверить endpoints:**
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/status/detailed
   curl http://localhost:8000/metrics | head -50
   ```

5. **Обсудить приоритеты Phase 3 Finalization**

---

## 📊 Метрики успеха Session 21

| Метрика | Цель |
|---------|------|
| E2E тесты | +5-10 новых |
| Общее количество тестов | ~375+ |
| Покрытие кода | >80% |
| Документация | MIGRATION_GUIDE создан |
| Версия | v3.0.0 released |

---

## 🎉 После завершения Phase 3

После Session 21 проект будет готов к:
- Production deployment
- v3.0.0 release
- Публикации в PyPI (опционально)
- Интеграции с внешними системами

---

**Готов к началу Phase 3 Finalization! 🚀**

