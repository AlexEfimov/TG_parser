# Стартовый промпт для Session 20: Phase 3D — Advanced Features

**Дата создания:** 28 декабря 2025  
**Предыдущая сессия:** Session 19 (Phase 3C — Agent Observability)  
**Версия проекта:** v3.0.0-alpha.3

---

## 📋 Контекст проекта

### Что такое TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

### Текущее состояние (v3.0.0-alpha.3)

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
| **Docker** | ✅ Production | Dockerfile + docker-compose.yml |
| **Тесты** | ✅ 340 | 100% проходят |

### Архитектура проекта (Phase 3C)

```
tg_parser/
├── agents/
│   ├── base.py                 # BaseAgent, AgentCapability, AgentType
│   ├── registry.py             # AgentRegistry (with persistence)
│   ├── persistence.py          # AgentPersistence layer
│   ├── archiver.py             # AgentHistoryArchiver ⭐ NEW
│   ├── orchestrator.py         # OrchestratorAgent
│   ├── processing_agent.py     # TGProcessingAgent (v2.0)
│   ├── tools/                  # Tools for agents
│   └── specialized/            # ProcessingAgent, TopicizationAgent, ExportAgent
│
├── api/
│   ├── main.py                 # FastAPI app
│   ├── routes/
│   │   ├── agents.py           # Agent observability endpoints ⭐ NEW
│   │   ├── health.py
│   │   ├── process.py
│   │   └── export.py
│   ├── auth.py
│   ├── job_store.py
│   └── webhooks.py
│
├── cli/
│   ├── app.py                  # Main CLI app
│   ├── agents_cmd.py           # agents subcommand group ⭐ NEW
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

---

## 🎯 Цель Session 20: Phase 3D — Advanced Features

### Видение

Добавить продвинутые функции для продакшн-окружения:
- Prometheus-совместимые метрики
- Background scheduled tasks
- OpenTelemetry tracing (опционально)
- Dashboard UI (опционально)

### Предлагаемый scope для Phase 3D

1. **Prometheus Metrics**
   - Endpoint `/metrics`
   - Стандартные метрики (requests, latency, errors)
   - Agent-специфичные метрики
   - Интеграция с prometheus-fastapi-instrumentator

2. **Background Scheduled Tasks**
   - APScheduler интеграция
   - Scheduled cleanup expired records
   - Scheduled health checks
   - Конфигурация через settings

3. **Health Check Improvements**
   - Детальная проверка компонентов
   - LLM connectivity check
   - Database health check
   - Agent health aggregation

4. **OpenTelemetry Tracing (опционально)**
   - Distributed tracing для multi-agent workflows
   - Span context propagation
   - Integration with Jaeger/Zipkin

5. **Simple Dashboard (опционально)**
   - Static HTML с charts
   - Endpoint `/dashboard`
   - Grafana-ready JSON exports

---

## 📁 Ключевые файлы для изучения

### Agent Observability (Phase 3C)

- `tg_parser/agents/archiver.py` — AgentHistoryArchiver
- `tg_parser/cli/agents_cmd.py` — CLI commands
- `tg_parser/api/routes/agents.py` — API endpoints

### API

- `tg_parser/api/main.py` — FastAPI app, lifespan
- `tg_parser/api/routes/health.py` — Health endpoints

### Существующие тесты

- `tests/test_agents_observability.py` — 15 тестов

### Документация

- `docs/notes/SESSION19_PHASE3C_COMPLETE.md` — результаты Phase 3C

---

## 🧪 Тесты

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
python -m pytest tests/ -v

# Только observability тесты
python -m pytest tests/test_agents_observability.py -v

# С покрытием
python -m pytest tests/ --cov=tg_parser --cov-report=term-missing
```

**Текущий статус:** 340 тестов, все проходят ✅

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

### Для Phase 3D (потенциально)
- `prometheus-fastapi-instrumentator` — Prometheus metrics
- `apscheduler` — Background task scheduling
- `opentelemetry-api` + `opentelemetry-sdk` — Tracing (опционально)

---

## 🎯 Задачи Phase 3D (предложение)

### Обязательные (MVP)

1. **Prometheus Metrics**
   - Endpoint `/metrics`
   - Request count, latency, error rate
   - Agent task metrics

2. **Background Cleanup**
   - Scheduled task для очистки expired records
   - Конфигурация интервала

3. **Health Check v2**
   - DB connectivity
   - LLM provider check
   - Agent registry status

4. **Тесты**
   - Минимум 10 новых тестов

### Опциональные

5. **OpenTelemetry Tracing**
6. **Simple Dashboard endpoint**
7. **Grafana dashboard JSON**

### После завершения Phase 3

8. **E2E Integration Tests** (Phase 3 Finalization)
   - Реализовать `test_full_cli_workflow` — полный CLI workflow с реальной БД
   - Реализовать `test_full_api_workflow` — полный API workflow с TestClient
   - Сейчас это placeholder'ы в `tests/test_agents_observability.py`

---

## ✅ Чеклист готовности

- [x] Все 340 тестов проходят
- [x] Документация обновлена до v3.0.0-alpha.3
- [x] Phase 3C полностью завершена
- [x] Agent Observability работает (CLI + API)
- [x] Archiver функционирует

---

## 🚀 Как начать

1. **Изучить существующие health endpoints:**
   ```bash
   cat tg_parser/api/routes/health.py
   ```

2. **Изучить lifespan в main.py:**
   ```bash
   cat tg_parser/api/main.py
   ```

3. **Проверить доступные библиотеки metrics:**
   ```bash
   pip show prometheus-fastapi-instrumentator 2>/dev/null || echo "Not installed"
   ```

4. **Обсудить приоритеты Phase 3D**

---

**Готов к началу Phase 3D! 🚀**

