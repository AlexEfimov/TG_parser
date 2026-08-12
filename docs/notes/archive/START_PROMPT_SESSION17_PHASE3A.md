# Стартовый промпт для Session 17: Phase 3A — Multi-Agent Architecture

**Дата создания:** 28 декабря 2025  
**Предыдущая сессия:** Session 16 (Phase 2F — API Production)  
**Версия проекта:** v2.0.0-alpha.4

---

## 📋 Контекст проекта

### Что такое TG_parser

**TG_parser** — система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных для RAG-систем и баз знаний.

### Текущее состояние (v2.0.0-alpha.4)

| Компонент | Статус | Описание |
|-----------|--------|----------|
| **Ingestion** | ✅ Production | Telethon, snapshot mode, 846+ сообщений |
| **Processing** | ✅ Production | Multi-LLM (OpenAI, Anthropic, Gemini, Ollama) |
| **Topicization** | ✅ Production | Семантическая кластеризация |
| **Export** | ✅ Production | NDJSON/JSON для RAG |
| **HTTP API** | ✅ Production | FastAPI, Auth, Rate Limiting, Webhooks |
| **Agents SDK** | ✅ PoC | TGProcessingAgent с tools |
| **Hybrid Mode** | ✅ Done | Agent + v1.2 pipeline |
| **Docker** | ✅ Production | Dockerfile + docker-compose.yml |
| **Тесты** | ✅ 258 | 100% проходят |

### Архитектура

```
tg_parser/
├── ingestion/       # Telethon client, collectors
├── processing/      # LLM clients, pipeline, processing logic
├── storage/         # SQLite repos (ports & adapters pattern)
├── export/          # NDJSON/JSON exporters
├── cli/             # Typer CLI commands
├── api/             # FastAPI HTTP API (v2.0)
│   ├── auth.py              # API Key authentication
│   ├── webhooks.py          # Webhook sending
│   ├── job_store.py         # Persistent job storage
│   ├── middleware/          # Rate limiting, logging
│   └── routes/              # Process, export endpoints
├── agents/          # OpenAI Agents SDK (v2.0)
│   ├── agent.py             # TGProcessingAgent
│   ├── tools/               # clean_text, extract_topics, etc.
│   └── context.py           # AgentContext
├── domain/          # Domain models
└── config/          # Settings
```

### Завершённые фазы v2.0

| Фаза | Сессия | Что сделано |
|------|--------|-------------|
| **2A** | 14 | HTTP API skeleton (FastAPI, 8 endpoints) |
| **2B** | 14 | Agents SDK PoC (TGProcessingAgent, 3 basic tools) |
| **2C** | 14 | LLM-Enhanced Tools (analyze_text_deep, extract_topics_llm) |
| **2E** | 15 | Hybrid Mode (pipeline как tool агента) |
| **2F** | 16 | API Production (Auth, Rate Limiting, Webhooks, Persistent Jobs) |

---

## 🎯 Цель Session 17: Phase 3A — Multi-Agent Architecture

### Видение

Превратить single-agent подход (TGProcessingAgent) в **multi-agent систему** со специализированными агентами для разных задач.

### Возможные направления

#### Вариант A: Specialized Agents
Создать отдельные агенты для каждого этапа pipeline:

```
OrchestratorAgent (координатор)
├── IngestionAgent      # Сбор данных из Telegram
├── ProcessingAgent     # Обработка через LLM
├── TopicizationAgent   # Кластеризация по темам
└── ExportAgent         # Формирование экспорта
```

**Преимущества:**
- Чёткое разделение ответственности
- Возможность параллельной работы
- Специализированные промпты и tools для каждого агента

#### Вариант B: Supervisor Pattern
Один supervisor agent управляет worker agents:

```
SupervisorAgent
├── worker_1: MessageProcessor
├── worker_2: MessageProcessor
├── worker_3: MessageProcessor
└── aggregator: ResultAggregator
```

**Преимущества:**
- Масштабируемость
- Fault tolerance
- Dynamic scaling

#### Вариант C: Agentic Workflow
Цепочка агентов с передачей состояния:

```
Message → ClassifierAgent → (routing) → [SpecialistAgent A | B | C] → MergerAgent → Output
```

**Преимущества:**
- Адаптивная обработка
- Разные стратегии для разных типов контента

### Предлагаемый минимальный scope для Phase 3A

1. **Agent Registry** — реестр доступных агентов
2. **OrchestratorAgent** — координация multi-agent workflow
3. **Handoff Protocol** — протокол передачи задач между агентами
4. **Agent State Persistence** — сохранение состояния агентов
5. **CLI интеграция** — `--multi-agent` флаг

---

## 📁 Ключевые файлы для изучения

### Текущая реализация агентов

- `tg_parser/agents/agent.py` — TGProcessingAgent (основной агент)
- `tg_parser/agents/tools/` — Tools для агента
- `tg_parser/agents/context.py` — AgentContext

### API и Job Management

- `tg_parser/api/job_store.py` — Persistent job storage (SQLite)
- `tg_parser/api/routes/process.py` — Processing endpoint
- `tg_parser/storage/ports.py` — Job model, JobRepo interface

### Processing Pipeline

- `tg_parser/processing/pipeline.py` — v1.2 processing pipeline
- `tg_parser/processing/llm/` — LLM clients

### Документация

- `docs/notes/SESSION16_PHASE2F_COMPLETE.md` — последняя сессия
- `DEVELOPMENT_ROADMAP.md` — планы развития
- `docs/architecture.md` — архитектура системы

---

## 🧪 Тесты

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
python -m pytest tests/ -v

# Только agent тесты
python -m pytest tests/test_agents.py tests/test_agents_phase2e.py -v

# Только API тесты
python -m pytest tests/test_api.py tests/test_api_security.py tests/test_job_storage.py -v
```

**Текущий статус:** 258 тестов, все проходят ✅

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

**Необходимые переменные (.env):**
```env
OPENAI_API_KEY=sk-...
# или другой LLM provider
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

## 🎯 Задачи Phase 3A (предложение)

### Обязательные (MVP)

1. **Agent Registry**
   - Реестр агентов с metadata
   - Возможность регистрации новых агентов
   - Lookup по типу/capabilities

2. **OrchestratorAgent**
   - Координация workflow
   - Распределение задач
   - Сбор результатов

3. **Handoff механизм**
   - Передача контекста между агентами
   - Structured output для handoff
   - Error handling при handoff

4. **Тесты**
   - Unit тесты для каждого компонента
   - Integration тесты для multi-agent flow
   - Минимум 15 новых тестов

### Опциональные

5. **Agent State Persistence**
   - Сохранение состояния агентов в SQLite
   - Resume после restart

6. **CLI флаг `--multi-agent`**
   - Переключение между single/multi agent mode

7. **Observability**
   - Трассировка агентов
   - Логирование handoffs

---

## 📚 Полезные ссылки

### OpenAI Agents SDK

```python
from agents import Agent, Runner, handoff

# Handoff между агентами
handoff_to_specialist = handoff(
    agent=specialist_agent,
    tool_name="escalate_to_specialist",
    tool_description="Transfer complex message to specialist"
)
```

### Patterns

- **Supervisor Pattern** — один агент управляет другими
- **Router Pattern** — классификатор направляет к специалистам
- **Chain Pattern** — последовательная обработка агентами

---

## ✅ Чеклист готовности

- [x] Все 258 тестов проходят
- [x] Документация обновлена до v2.0.0-alpha.4
- [x] Phase 2F полностью завершена
- [x] API Production-ready (Auth, Rate Limiting, Webhooks)
- [x] Persistent Job Storage работает
- [x] TGProcessingAgent с hybrid mode работает

---

## 🚀 Как начать

1. **Изучить текущую реализацию агентов:**
   ```bash
   cat tg_parser/agents/agent.py
   cat tg_parser/agents/tools/__init__.py
   ```

2. **Запустить agent processing:**
   ```bash
   python -m tg_parser.cli process --channel test_channel --agent --hybrid
   ```

3. **Обсудить архитектуру Multi-Agent:**
   - Какой pattern выбрать? (Supervisor / Router / Chain)
   - Какие специализированные агенты нужны?
   - Как организовать handoff?

---

**Готов к началу Phase 3A! 🚀**

