# START_PROMPT_SESSION14: TG_parser v2.0 Development

**Date**: 27 декабря 2025  
**Previous Session**: Session 13 (v1.2.0 Testing & Release)  
**Goal**: Начать разработку v2.0 с OpenAI Agents SDK

---

## ⚠️ ВАЖНЫЕ ИНСТРУКЦИИ

### Доступ к документации
- **Используй Ref и Context7** для получения актуальных версий документации
- Перед использованием любой библиотеки — проверяй документацию через `ref_search_documentation` или `mcp_Context7_get-library-docs`
- Не полагайся на устаревшие знания — API может измениться

### Процесс разработки
- **Поэтапная разработка**: каждый этап согласовывается перед началом выполнения
- Не переходи к следующему этапу без явного подтверждения пользователя
- После завершения каждого этапа — краткий отчёт и запрос на продолжение

### Порядок работы
1. Показать план этапа → Получить подтверждение
2. Выполнить этап → Показать результаты
3. Обсудить → Перейти к следующему этапу

---

## 📋 Context

### v1.2.0 Status: ✅ RELEASED

**Достижения v1.2.0:**
- ✅ Multi-LLM поддержка (OpenAI, Anthropic, Gemini, Ollama)
- ✅ Parallel processing (`--concurrency`)
- ✅ Docker & Docker Compose
- ✅ 126 unit тестов (100% pass)
- ✅ Полная документация

**Результаты тестирования:**

| Provider | Success | Throughput | Quality |
|----------|---------|------------|---------|
| OpenAI | 100% | 0.120 msg/s | Good |
| Anthropic | 100% | 0.121 msg/s | Best |
| Gemini | 100% | 0.342 msg/s | Great |
| Ollama | 100% | 0.024 msg/s | Good |

---

## 🎯 Session 14 Goals: v2.0 Foundation

### Primary Goal: OpenAI Agents SDK Integration

**v2.0 Vision**: Превратить TG_parser из CLI-инструмента в **Agent-based платформу** с:
- OpenAI Agents SDK для интеллектуальной обработки
- HTTP API для интеграций
- Web Dashboard для мониторинга
- Scheduled updates (cron-like)

### Phase 1: Research & Prototyping (Session 14)

1. **Изучить OpenAI Agents SDK**
   - https://openai.github.io/openai-agents-python/
   - Понять архитектуру: Agent, Tool, Runner
   - Изучить примеры: multi-agent, handoffs

2. **Proof of Concept: Agent for Processing**
   - Создать TGParserAgent с инструментами:
     - `process_message` — обработка одного сообщения
     - `extract_entities` — извлечение сущностей
     - `generate_summary` — генерация саммари
   - Сравнить с текущим подходом (prompt-based)

3. **Architecture Design**
   - Определить границы Agent vs традиционный подход
   - Спроектировать HTTP API схему
   - Спланировать миграцию существующего кода

---

## 📚 Reference Materials

### OpenAI Agents SDK

```python
# Пример базового агента
from openai import Agent, Tool

@Tool
def process_telegram_message(message: str) -> dict:
    """Обрабатывает сообщение из Telegram."""
    # ... processing logic
    return {"summary": "...", "topics": [...]}

agent = Agent(
    name="TGParserAgent",
    instructions="Ты — агент для обработки Telegram контента...",
    tools=[process_telegram_message],
)
```

### Ключевые концепции Agents SDK

1. **Agent** — LLM с инструментами и инструкциями
2. **Tool** — функции, которые агент может вызывать
3. **Runner** — оркестратор выполнения
4. **Handoffs** — передача между агентами
5. **Guardrails** — валидация input/output

### Документация

- [Agents SDK Quickstart](https://openai.github.io/openai-agents-python/quickstart/)
- [Multi-agent patterns](https://openai.github.io/openai-agents-python/multi_agent/)
- [Tools & Functions](https://openai.github.io/openai-agents-python/tools/)

---

## 🔧 Technical Plan

### Step 1: Install Agents SDK

```bash
pip install openai-agents
# или
uv add openai-agents
```

### Step 2: Create Basic Agent

```python
# tg_parser/agents/processing_agent.py

from agents import Agent, Tool, Runner

class TGProcessingAgent:
    """Agent для обработки Telegram сообщений."""
    
    def __init__(self, model: str = "gpt-4o"):
        self.agent = Agent(
            name="TGProcessor",
            instructions=self._load_instructions(),
            tools=[
                self.clean_text,
                self.extract_topics,
                self.extract_entities,
                self.generate_summary,
            ],
            model=model,
        )
    
    @Tool
    def clean_text(self, raw_text: str) -> str:
        """Очищает текст от мусора."""
        ...
    
    @Tool  
    def extract_topics(self, text: str) -> list[str]:
        """Извлекает темы из текста."""
        ...
    
    async def process(self, message: RawTelegramMessage) -> ProcessedDocument:
        """Обрабатывает сообщение через агента."""
        result = await Runner.run(self.agent, message.text)
        return self._to_processed_document(result)
```

### Step 3: Hybrid Architecture

```
v1.2 Pipeline (current):
RawMessage → ProcessingPipeline → LLM → ProcessedDocument

v2.0 Pipeline (proposed):
RawMessage → TGProcessingAgent → [Tools] → ProcessedDocument
                    ↓
              Multi-agent orchestration
                    ↓
           TopicizationAgent, ExportAgent
```

---

## 📋 Session 14 Tasks (ПОЭТАПНО)

> ⚠️ **Каждый этап требует согласования перед началом!**

### 🔬 ЭТАП 1: Research (2-3 часа)
**Согласовать перед началом!**

1. [ ] Получить документацию через Context7/Ref
2. [ ] Установить openai-agents
3. [ ] Изучить примеры: basic, multi-agent, tools
4. [ ] Понять различия: Agents SDK vs Chat Completions API
5. [ ] **→ Отчёт и обсуждение результатов**

### 🛠️ ЭТАП 2: Prototyping (3-4 часа)
**Согласовать перед началом!**

6. [ ] Создать базовый TGProcessingAgent
7. [ ] Реализовать 2-3 Tool функции
8. [ ] Протестировать на 5-10 реальных сообщениях
9. [ ] Сравнить качество с v1.2 подходом
10. [ ] **→ Отчёт и обсуждение результатов**

### 🏗️ ЭТАП 3: Architecture (2-3 часа)
**Согласовать перед началом!**

11. [ ] Спроектировать multi-agent архитектуру
12. [ ] Определить API endpoints (OpenAPI spec)
13. [ ] Создать ADR для Agents SDK adoption
14. [ ] **→ Отчёт и обсуждение результатов**

### 📝 ЭТАП 4: Documentation (1 час)
**Согласовать перед началом!**

15. [ ] Создать docs/adr/005-agents-sdk.md
16. [ ] Обновить DEVELOPMENT_ROADMAP.md
17. [ ] Создать START_PROMPT_SESSION15.md
18. [ ] **→ Финальный отчёт сессии**

---

## 🎯 Success Criteria

### Minimum (MVP для Session 14)

- [ ] OpenAI Agents SDK установлен и работает
- [ ] Создан базовый TGProcessingAgent
- [ ] Успешная обработка 5+ сообщений через агента
- [ ] Документирована архитектура v2.0

### Stretch Goals

- [ ] Multi-agent prototype (Processing + Topicization)
- [ ] HTTP API skeleton (FastAPI)
- [ ] Performance comparison: Agents vs v1.2

---

## ⚠️ Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Agents SDK не подходит для batch processing | High | Гибридный подход: Agents для сложных, batch для простых |
| Высокая latency при multi-agent | Medium | Оптимизация handoffs, parallel execution |
| Breaking changes в Agents SDK (beta) | Medium | Pin версию, мониторить changelog |
| Сложность отладки агентов | Medium | Structured logging, tracing |

---

## 📁 File Structure (proposed)

```
tg_parser/
├── agents/                    # NEW: v2.0 Agents
│   ├── __init__.py
│   ├── processing_agent.py    # TGProcessingAgent
│   ├── topicization_agent.py  # TopicizationAgent
│   ├── tools/                 # Agent tools
│   │   ├── text_cleaning.py
│   │   ├── entity_extraction.py
│   │   └── topic_detection.py
│   └── orchestrator.py        # Multi-agent runner
├── api/                       # NEW: HTTP API
│   ├── __init__.py
│   ├── main.py               # FastAPI app
│   ├── routes/
│   │   ├── process.py
│   │   ├── export.py
│   │   └── health.py
│   └── schemas.py            # Pydantic models for API
├── processing/               # EXISTING: v1.2 pipeline
│   ├── pipeline.py           # Keep for backward compat
│   └── llm/                  # Multi-LLM clients
└── cli/                      # EXISTING: CLI commands
```

---

## 🔗 Resources

### Доступ к документации (ОБЯЗАТЕЛЬНО использовать!)

```python
# Перед началом работы — получить актуальную документацию:

# 1. OpenAI Agents SDK
mcp_Context7_resolve-library-id(libraryName="openai-agents")
mcp_Context7_get-library-docs(context7CompatibleLibraryID="...", topic="quickstart")

# 2. FastAPI
mcp_Context7_resolve-library-id(libraryName="fastapi")
mcp_Context7_get-library-docs(context7CompatibleLibraryID="...", topic="async")

# 3. Или через Ref
mcp_Ref_ref_search_documentation(query="OpenAI Agents SDK python quickstart")
mcp_Ref_ref_read_url(url="...")
```

### OpenAI Agents SDK
- Docs: https://openai.github.io/openai-agents-python/
- GitHub: https://github.com/openai/openai-agents-python
- Examples: https://github.com/openai/openai-agents-python/tree/main/examples

### FastAPI (for HTTP API)
- Docs: https://fastapi.tiangolo.com/
- AsyncIO: https://fastapi.tiangolo.com/async/

### Related ADRs
- ADR-001: Hexagonal Architecture
- ADR-002: SQLite Storage
- ADR-003: Pydantic Models
- ADR-004: LLM Integration
- ADR-005: Agents SDK (to be created)

---

## 📝 Notes

### Вопросы для исследования

1. Как Agents SDK обрабатывает rate limits?
2. Есть ли встроенная поддержка batch processing?
3. Можно ли использовать non-OpenAI модели с Agents SDK?
4. Как реализовать streaming responses?
5. Какие guardrails доступны из коробки?

### Идеи для v2.0

1. **Intelligent Routing**: Агент выбирает оптимальный LLM для каждого сообщения
2. **Self-healing**: Агент автоматически retry failed messages
3. **Quality Assessment**: Агент оценивает качество своих ответов
4. **Context Awareness**: Агент использует контекст канала для лучшего понимания

---

**Version**: 1.0  
**Created**: 27 декабря 2025  
**Author**: Session 13 Agent

