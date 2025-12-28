# Стартовый промпт для Session 19: Phase 3C — Agent Observability

**Дата создания:** 28 декабря 2025  
**Предыдущая сессия:** Session 18 (Phase 3B — Agent State Persistence)  
**Версия проекта:** v3.0.0-alpha.2

---

## 📋 Контекст проекта

### Что такое TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

### Текущее состояние (v3.0.0-alpha.2)

| Компонент | Статус | Описание |
|-----------|--------|----------|
| **Ingestion** | ✅ Production | Telethon, snapshot mode, 846+ сообщений |
| **Processing** | ✅ Production | Multi-LLM (OpenAI, Anthropic, Gemini, Ollama) |
| **Topicization** | ✅ Production | Семантическая кластеризация |
| **Export** | ✅ Production | NDJSON/JSON для RAG |
| **HTTP API** | ✅ Production | FastAPI, Auth, Rate Limiting, Webhooks |
| **Agents SDK** | ✅ Production | TGProcessingAgent с tools |
| **Hybrid Mode** | ✅ Done | Agent + v1.2 pipeline |
| **Multi-Agent** | ✅ Done | OrchestratorAgent, ProcessingAgent, TopicizationAgent, ExportAgent |
| **Agent Persistence** | ✅ Done | State, TaskHistory, Stats, HandoffHistory |
| **Docker** | ✅ Production | Dockerfile + docker-compose.yml |
| **Тесты** | ✅ 325 | 100% проходят |

### Архитектура Agent Persistence (Phase 3B)

```
tg_parser/agents/
├── base.py                 # BaseAgent, AgentCapability, AgentType, Handoff protocol
├── registry.py             # AgentRegistry (with persistence support)
├── persistence.py          # AgentPersistence (unified persistence layer)
├── orchestrator.py         # OrchestratorAgent (workflow coordination)
├── processing_agent.py     # Original TGProcessingAgent (v2.0)
├── tools/                  # Tools for agents
└── specialized/
    ├── processing.py       # ProcessingAgent (Simple/Deep/Auto)
    ├── topicization.py     # TopicizationAgent
    └── export.py           # ExportAgent

tg_parser/storage/sqlite/
├── agent_state_repo.py     # SQLiteAgentStateRepo
├── task_history_repo.py    # SQLiteTaskHistoryRepo
├── agent_stats_repo.py     # SQLiteAgentStatsRepo
└── handoff_history_repo.py # SQLiteHandoffHistoryRepo
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

---

## 🎯 Цель Session 19: Phase 3C — Agent Observability

### Видение

Добавить инструменты для мониторинга и отладки агентов:
- CLI команды для просмотра статистики
- API endpoints для агентов
- Архивация истёкших данных
- Метрики для мониторинга

### Предлагаемый scope для Phase 3C

1. **CLI команда `tg-parser agents`**
   - `tg-parser agents list` — список зарегистрированных агентов
   - `tg-parser agents status <name>` — статистика агента
   - `tg-parser agents history <name>` — история задач
   - `tg-parser agents cleanup` — очистка истёкших записей

2. **API endpoints для агентов**
   - `GET /api/v1/agents` — список агентов
   - `GET /api/v1/agents/{name}` — информация об агенте
   - `GET /api/v1/agents/{name}/stats` — статистика агента
   - `GET /api/v1/agents/{name}/history` — история задач

3. **Архивация в NDJSON**
   - Экспорт истёкших записей перед удалением
   - Сжатие gzip
   - Конфигурация через settings

4. **Scheduled cleanup**
   - Background task для очистки
   - Интеграция с API lifecycle

5. **Метрики (опционально)**
   - Prometheus-совместимые метрики
   - Endpoint `/metrics`

---

## 📁 Ключевые файлы для изучения

### Agent Persistence (Phase 3B)

- `tg_parser/agents/persistence.py` — AgentPersistence layer
- `tg_parser/agents/registry.py` — AgentRegistry с persistence
- `tg_parser/storage/sqlite/agent_state_repo.py` — SQLiteAgentStateRepo
- `tg_parser/storage/sqlite/task_history_repo.py` — SQLiteTaskHistoryRepo

### CLI (для примера)

- `tg_parser/cli/commands.py` — существующие CLI команды
- `tg_parser/cli/process.py` — process команда

### API (для примера)

- `tg_parser/api/routes/` — существующие routes

### Документация

- `docs/notes/SESSION18_PHASE3B_COMPLETE.md` — результаты Phase 3B

---

## 🧪 Тесты

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
python -m pytest tests/ -v

# Только agent persistence тесты
python -m pytest tests/test_agent_persistence.py -v

# Только multi-agent тесты
python -m pytest tests/test_multi_agent.py -v
```

**Текущий статус:** 325 тестов, все проходят ✅

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

### Для агентов
- `openai-agents` — OpenAI Agents SDK
- Model: gpt-4o или gpt-4o-mini

---

## 🎯 Задачи Phase 3C (предложение)

### Обязательные (MVP)

1. **CLI `tg-parser agents` группа команд**
   - list, status, history, cleanup

2. **API endpoints**
   - GET /api/v1/agents
   - GET /api/v1/agents/{name}

3. **Архивация перед удалением**
   - Экспорт в NDJSON.gz
   - Настройка через agent_retention_mode

4. **Тесты**
   - Минимум 10 новых тестов

### Опциональные

5. **Background cleanup task**
6. **Prometheus metrics**
7. **Dashboard endpoint**

---

## ✅ Чеклист готовности

- [x] Все 325 тестов проходят
- [x] Документация обновлена до v3.0.0-alpha.2
- [x] Phase 3B полностью завершена
- [x] Agent Persistence работает
- [x] Все 4 репозитория реализованы

---

## 🚀 Как начать

1. **Изучить AgentPersistence:**
   ```bash
   cat tg_parser/agents/persistence.py
   ```

2. **Изучить существующие CLI команды:**
   ```bash
   cat tg_parser/cli/commands.py
   ls tg_parser/cli/
   ```

3. **Изучить существующие API routes:**
   ```bash
   ls tg_parser/api/routes/
   ```

4. **Обсудить scope CLI/API команд**

---

**Готов к началу Phase 3C! 🚀**

