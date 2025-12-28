# Стартовый промпт для Session 18: Phase 3B — Agent State Persistence

**Дата создания:** 28 декабря 2025  
**Предыдущая сессия:** Session 17 (Phase 3A — Multi-Agent Architecture)  
**Версия проекта:** v3.0.0-alpha.1

---

## 📋 Контекст проекта

### Что такое TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

### Текущее состояние (v3.0.0-alpha.1)

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
| **Docker** | ✅ Production | Dockerfile + docker-compose.yml |
| **Тесты** | ✅ 300 | 100% проходят |

### Архитектура Multi-Agent (Phase 3A)

```
tg_parser/agents/
├── base.py                 # BaseAgent, AgentCapability, AgentType, Handoff protocol
├── registry.py             # AgentRegistry (register, lookup, statistics)
├── orchestrator.py         # OrchestratorAgent (workflow coordination)
├── processing_agent.py     # Original TGProcessingAgent (v2.0)
├── tools/                  # Tools for agents
└── specialized/
    ├── processing.py       # ProcessingAgent (Simple/Deep/Auto)
    ├── topicization.py     # TopicizationAgent
    └── export.py           # ExportAgent
```

### Завершённые фазы v3.0

| Фаза | Сессия | Что сделано |
|------|--------|-------------|
| **2A** | 14 | HTTP API skeleton (FastAPI, 8 endpoints) |
| **2B** | 14 | Agents SDK PoC (TGProcessingAgent, 3 basic tools) |
| **2C** | 14 | LLM-Enhanced Tools (analyze_text_deep, extract_topics_llm) |
| **2E** | 15 | Hybrid Mode (pipeline как tool агента) |
| **2F** | 16 | API Production (Auth, Rate Limiting, Webhooks, Persistent Jobs) |
| **3A** | 17 | Multi-Agent Architecture (Registry, Orchestrator, Specialized Agents, Handoffs) |

---

## 🎯 Цель Session 18: Phase 3B — Agent State Persistence

### Видение

Добавить **сохранение состояния агентов** в SQLite для:
- Восстановления после restart
- Отслеживания истории задач
- Мониторинга производительности агентов

### Предлагаемый scope для Phase 3B

1. **AgentStateRepo** — репозиторий для хранения состояния агентов
   - Сохранение/восстановление AgentMetadata
   - История задач агента
   - Статистика производительности

2. **TaskHistoryRepo** — репозиторий для истории задач
   - Связь task → agent
   - Время выполнения
   - Результаты/ошибки

3. **HandoffHistoryRepo** — репозиторий для истории handoffs
   - Source/target агенты
   - Payload/результаты
   - Время обработки

4. **SQLite таблицы**
   ```sql
   agent_states (
     name TEXT PRIMARY KEY,
     agent_type TEXT,
     metadata_json TEXT,
     created_at TEXT,
     updated_at TEXT
   )
   
   task_history (
     id TEXT PRIMARY KEY,
     agent_name TEXT,
     task_type TEXT,
     input_json TEXT,
     output_json TEXT,
     success INTEGER,
     processing_time_ms INTEGER,
     created_at TEXT
   )
   
   handoff_history (
     id TEXT PRIMARY KEY,
     source_agent TEXT,
     target_agent TEXT,
     status TEXT,
     payload_json TEXT,
     result_json TEXT,
     processing_time_ms INTEGER,
     created_at TEXT,
     completed_at TEXT
   )
   ```

5. **Интеграция с Registry**
   - Автоматическое сохранение при регистрации
   - Восстановление состояния при старте
   - Запись статистики

6. **Тесты**
   - Unit тесты для репозиториев
   - Integration тесты для persistence
   - Минимум 15 новых тестов

---

## 📁 Ключевые файлы для изучения

### Multi-Agent система (Phase 3A)

- `tg_parser/agents/base.py` — BaseAgent, Handoff protocol
- `tg_parser/agents/registry.py` — AgentRegistry
- `tg_parser/agents/orchestrator.py` — OrchestratorAgent
- `tg_parser/agents/specialized/` — Specialized agents

### Storage (для примера реализации repo)

- `tg_parser/storage/ports.py` — Repository interfaces
- `tg_parser/storage/sqlite/` — SQLite implementations

### Документация

- `docs/notes/SESSION17_PHASE3A_COMPLETE.md` — результаты Phase 3A
- `docs/architecture.md` — общая архитектура

---

## 🧪 Тесты

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
python -m pytest tests/ -v

# Только multi-agent тесты
python -m pytest tests/test_multi_agent.py -v

# Только storage тесты
python -m pytest tests/test_storage*.py -v
```

**Текущий статус:** 300 тестов, все проходят ✅

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

### Для агентов
- `openai-agents` — OpenAI Agents SDK
- Model: gpt-4o или gpt-4o-mini

---

## 🎯 Задачи Phase 3B (предложение)

### Обязательные (MVP)

1. **AgentStateRepo**
   - Интерфейс в ports.py
   - SQLite реализация
   - Методы: save, get, list, delete

2. **TaskHistoryRepo**
   - Запись истории задач
   - Фильтрация по агенту/времени

3. **HandoffHistoryRepo**
   - Запись истории handoffs
   - Статистика успешности

4. **DDL для новых таблиц**
   - Миграция processing_storage.sqlite

5. **Интеграция с AgentRegistry**
   - Автосохранение при register/unregister
   - Загрузка при startup

6. **Тесты**
   - Минимум 15 новых тестов

### Опциональные

7. **CLI команда `agents status`**
   - Показать зарегистрированные агенты
   - Статистика задач

8. **API endpoints для агентов**
   - GET /api/v1/agents
   - GET /api/v1/agents/{name}/history

---

## ✅ Чеклист готовности

- [x] Все 300 тестов проходят
- [x] Документация обновлена до v3.0.0-alpha.1
- [x] Phase 3A полностью завершена
- [x] Multi-Agent Architecture работает
- [x] CLI флаг --multi-agent работает

---

## 🚀 Как начать

1. **Изучить текущую реализацию storage:**
   ```bash
   cat tg_parser/storage/ports.py
   cat tg_parser/storage/sqlite/processed_document_repo.py
   ```

2. **Изучить Agent Registry:**
   ```bash
   cat tg_parser/agents/registry.py
   ```

3. **Обсудить схему persistence:**
   - Какие данные сохранять?
   - Как часто обновлять?
   - Как восстанавливать после restart?

---

**Готов к началу Phase 3B! 🚀**

