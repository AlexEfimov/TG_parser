# SESSION 14 — ЭТАП 2B: OpenAI Agents SDK PoC

**Дата**: 27 декабря 2025  
**Предыдущий этап**: 2A (HTTP API Skeleton) ✅  
**Цель**: Создать Proof of Concept с OpenAI Agents SDK

---

## ⚠️ ВАЖНЫЕ ИНСТРУКЦИИ

### Перед началом работы
1. **Активировать виртуальное окружение**:
   ```bash
   cd /Users/alexanderefimov/TG_parser
   source .venv/bin/activate
   ```

2. **Установить OpenAI Agents SDK**:
   ```bash
   pip install openai-agents
   ```

3. **Проверить API ключ** (должен быть в .env):
   ```bash
   grep OPENAI_API_KEY .env
   ```

### Документация
- Использовать **Context7** для актуальной документации:
  ```
  mcp_Context7_get-library-docs(
    context7CompatibleLibraryID="/openai/openai-agents-python",
    topic="..."
  )
  ```

---

## 📋 Контекст

### Что уже сделано в сессии 14:

**ЭТАП 1: Research** ✅
- Изучена архитектура Agents SDK
- Определены ключевые компоненты: Agent, Tool, Runner, Handoffs
- Рекомендована гибридная архитектура

**ЭТАП 2A: HTTP API Skeleton** ✅
- FastAPI приложение (`tg_parser/api/`)
- 8 endpoints (health, process, export)
- CLI команда `tg-parser api`
- 24 теста для API
- **Всего 150 тестов проходят**

### Текущая архитектура v1.2:

```
RawMessage → ProcessingPipeline → LLM (Chat Completions) → ProcessedDocument
                    ↓
              prompt + text → response → parse JSON
```

### Целевая архитектура с Agents:

```
RawMessage → TGProcessingAgent → [Tools] → ProcessedDocument
                    ↓
         Agent orchestrates tool calls:
         - clean_text()
         - extract_entities()
         - extract_topics()
         - generate_summary()
```

---

## 🎯 Задачи ЭТАПА 2B

### 1. Установка и базовый тест (15 мин)

```bash
pip install openai-agents
```

```python
# Быстрый тест
from agents import Agent, Runner

agent = Agent(
    name="Test",
    instructions="Say hello"
)

result = Runner.run_sync(agent, "Hi")
print(result.final_output)
```

### 2. Создать TGProcessingAgent (1-2 часа)

**Файл**: `tg_parser/agents/processing_agent.py`

```python
from agents import Agent, Runner, function_tool
from tg_parser.domain.models import RawTelegramMessage, ProcessedDocument

@function_tool
def clean_text(raw_text: str) -> str:
    """Clean and normalize text from Telegram message."""
    # Remove excessive whitespace, normalize Unicode
    import re
    text = re.sub(r'\s+', ' ', raw_text).strip()
    return text

@function_tool
def extract_topics(text: str) -> list[str]:
    """Extract main topics from text."""
    # This will be called by the agent
    # Agent will use LLM reasoning to extract topics
    return []  # Agent fills this

@function_tool
def extract_entities(text: str) -> list[dict]:
    """Extract named entities from text."""
    return []  # Agent fills this

class TGProcessingAgent:
    """Agent for processing Telegram messages."""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.agent = Agent(
            name="TGProcessor",
            instructions=self._get_instructions(),
            tools=[clean_text, extract_topics, extract_entities],
            model=model,
        )
    
    def _get_instructions(self) -> str:
        return """
        You are an expert at processing Telegram messages for a knowledge base.
        
        For each message:
        1. Clean the text (remove noise, normalize)
        2. Extract 2-5 main topics
        3. Extract named entities (people, organizations, terms)
        4. Generate a brief summary
        
        Return structured JSON with:
        - text_clean: cleaned text
        - topics: list of topic strings
        - entities: list of {type, value, confidence}
        - summary: 1-2 sentence summary
        - language: detected language code
        """
    
    async def process(self, message: RawTelegramMessage) -> dict:
        """Process a single message through the agent."""
        result = await Runner.run(
            self.agent,
            f"Process this Telegram message:\n\n{message.text}"
        )
        return self._parse_output(result.final_output)
```

### 3. Сравнение с v1.2 pipeline (30 мин)

Обработать 5-10 реальных сообщений через:
- v1.2 ProcessingPipeline
- TGProcessingAgent

Сравнить:
- Качество извлечения (topics, entities)
- Время обработки
- Количество API вызовов
- Стоимость (tokens)

### 4. Создать тесты (30 мин)

**Файл**: `tests/test_agents.py`

```python
import pytest
from unittest.mock import patch, AsyncMock

class TestTGProcessingAgent:
    
    async def test_agent_creation(self):
        """Agent should be created with tools."""
        from tg_parser.agents import TGProcessingAgent
        agent = TGProcessingAgent()
        assert agent.agent.name == "TGProcessor"
        assert len(agent.agent.tools) >= 3
    
    async def test_process_message(self):
        """Agent should process message and return structured output."""
        # Mock the Runner to avoid actual API calls
        ...
```

---

## 📁 Структура файлов

```
tg_parser/
├── agents/                    # NEW
│   ├── __init__.py
│   ├── processing_agent.py   # TGProcessingAgent
│   └── tools/                # Agent tools
│       ├── __init__.py
│       ├── text_tools.py     # clean_text, normalize
│       └── extraction_tools.py  # entities, topics
├── api/                      # EXISTING (from 2A)
│   └── ...
└── processing/               # EXISTING (v1.2)
    └── pipeline.py
```

---

## ✅ Success Criteria

### Minimum (MVP)
- [ ] OpenAI Agents SDK установлен
- [ ] TGProcessingAgent создан и работает
- [ ] Успешная обработка 5+ сообщений
- [ ] Базовые тесты (mock)

### Stretch
- [ ] Сравнительный анализ с v1.2
- [ ] Multi-agent prototype (Processing + Topicization)
- [ ] Интеграция с HTTP API endpoint `/api/v1/chat`

---

## 🔧 Полезные команды

```bash
# Активация окружения
source .venv/bin/activate

# Установка Agents SDK
pip install openai-agents

# Запуск тестов
pytest tests/test_agents.py -v

# Запуск API сервера
tg-parser api --port 8000

# Проверка всех тестов
pytest tests/ -v --tb=short
```

---

## 📚 Ключевые примеры из документации

### Базовый агент с tools:

```python
from agents import Agent, Runner, function_tool

@function_tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Sunny in {city}"

agent = Agent(
    name="Assistant",
    instructions="You help with weather queries.",
    tools=[get_weather],
    model="gpt-4o-mini",
)

result = await Runner.run(agent, "What's the weather in Moscow?")
print(result.final_output)
```

### Structured output с Pydantic:

```python
from pydantic import BaseModel
from agents import Agent

class ProcessingResult(BaseModel):
    text_clean: str
    topics: list[str]
    summary: str

agent = Agent(
    name="Processor",
    instructions="Process text and extract info",
    output_type=ProcessingResult,  # Structured output!
)
```

### Multi-agent с handoffs:

```python
from agents import Agent, handoff

processing_agent = Agent(
    name="Processing",
    handoff_description="Handles message processing",
)

topicization_agent = Agent(
    name="Topicization", 
    handoff_description="Groups messages by topic",
)

triage_agent = Agent(
    name="Triage",
    instructions="Route to appropriate agent",
    handoffs=[processing_agent, topicization_agent],
)
```

---

## 📝 Вопросы для исследования

1. Как Agents SDK обрабатывает ошибки tools?
2. Можно ли использовать batch processing с Agent?
3. Как измерить token usage для Agent vs direct API?
4. Нужен ли SQLiteSession для нашего use case?

---

**Version**: 1.0  
**Created**: 27 декабря 2025  
**Status**: Ready for Phase 2B

