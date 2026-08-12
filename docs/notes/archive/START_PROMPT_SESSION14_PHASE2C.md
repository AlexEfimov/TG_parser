# START PROMPT: Session 14 Phase 2C — Agents Integration

**Дата**: 27 декабря 2025  
**Контекст**: Продолжение сессии 14, этап 2C

---

## ⚠️ ИНСТРУКЦИИ

### Процесс разработки
- **Поэтапная разработка**: каждый этап согласовывается перед началом
- Используй **Context7** для актуальной документации OpenAI Agents SDK
- После каждого этапа — краткий отчёт

---

## 📋 Текущий статус

### Session 14 Progress:
- ✅ **ЭТАП 1**: Research (Agents SDK изучен)
- ✅ **ЭТАП 2A**: HTTP API Skeleton (FastAPI, 8 endpoints, 24 теста)
- ✅ **ЭТАП 2B**: Agents PoC (TGProcessingAgent, 3 tools, 24 теста)
- 🔄 **ЭТАП 2C**: Agents Integration (ТЕКУЩИЙ)

### Статистика:
- **174 теста** проходят
- HTTP API работает: `tg-parser api --port 8000`
- Agents PoC готов: `tg_parser/agents/`

### Созданные модули (Phase 2B):
```
tg_parser/agents/
├── __init__.py
├── processing_agent.py    # TGProcessingAgent, process_message_with_agent()
└── tools/
    ├── __init__.py
    └── text_tools.py      # clean_text, extract_topics, extract_entities
```

### Текущие ограничения tools:
- `clean_text` — regex-based, без LLM
- `extract_topics` — keyword matching, без семантики
- `extract_entities` — pattern matching (email, URL, phone, hashtags)

---

## 🎯 Цели ЭТАПА 2C

### 1. Добавить LLM в tools (Enhanced Tools)
Улучшить tools, добавив LLM вызовы для глубокого анализа:

```python
@function_tool
async def clean_text_llm(text: str) -> CleanTextResult:
    """Clean text using LLM for complex cases."""
    # Использовать существующий LLM client
    # Определить language более точно
    # Удалить шум с пониманием контекста
```

### 2. CLI флаг `--agent`
Добавить возможность использовать агентный подход через CLI:

```bash
# Стандартный pipeline (v1.2)
tg-parser process --channel @lab --provider openai

# Агентный подход (v2.0)
tg-parser process --channel @lab --agent
tg-parser process --channel @lab --agent --provider anthropic
```

### 3. Сравнение качества
Протестировать на 10-20 реальных сообщениях:
- Сравнить results agents vs v1.2 pipeline
- Замерить время обработки
- Оценить качество extraction

### 4. Гибридный режим (опционально)
Agent может вызывать существующий ProcessingPipeline как tool:

```python
@function_tool
async def run_v12_pipeline(text: str) -> ProcessedDocument:
    """Run the v1.2 processing pipeline."""
    # Использовать существующий pipeline
```

---

## 🔧 Быстрый старт

```bash
# Активация окружения
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверка текущего состояния
python -c "from tg_parser.agents import TGProcessingAgent; print('✅ Agents OK')"
python -m pytest tests/test_agents.py -v --tb=short

# Запуск тестов (174 теста)
python -m pytest tests/ --ignore=tests/test_integration.py -q
```

---

## 📁 Целевые изменения

### 1. Обновить `text_tools.py`

```python
# Добавить LLM-enhanced версии tools
@function_tool
async def analyze_text_deep(
    text: str,
    llm_client: LLMClient | None = None
) -> FullAnalysisResult:
    """Deep analysis using LLM."""
    ...
```

### 2. Обновить `processing_agent.py`

```python
# Добавить поддержку разных LLM провайдеров
class TGProcessingAgent:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",  # NEW
        use_llm_tools: bool = True,  # NEW
    ):
        ...
```

### 3. Обновить CLI `process_cmd.py`

```python
# Добавить --agent флаг
@app.command()
def process(
    channel: str,
    agent: bool = typer.Option(False, "--agent", help="Use agent-based processing"),
    ...
):
    if agent:
        # Use TGProcessingAgent
    else:
        # Use ProcessingPipelineImpl (v1.2)
```

---

## 📚 Документация

### Agents SDK
```
mcp_Context7_get-library-docs(
  context7CompatibleLibraryID="/openai/openai-agents-python",
  topic="async tools context"
)
```

### Существующий код
- `tg_parser/agents/tools/text_tools.py` — текущие tools
- `tg_parser/processing/pipeline.py` — v1.2 pipeline
- `tg_parser/processing/llm/factory.py` — LLM client factory

---

## ✅ Success Criteria

- [ ] LLM-enhanced tools работают
- [ ] CLI флаг `--agent` реализован
- [ ] Сравнение качества на 10+ сообщениях
- [ ] Документация обновлена
- [ ] Тесты для новой функциональности

---

## 📊 Ожидаемые результаты

| Метрика | v1.2 Pipeline | Agents v2.0 |
|---------|---------------|-------------|
| Качество topics | Baseline | Сравнить |
| Качество entities | Baseline | Сравнить |
| Время обработки | Baseline | Сравнить |
| Гибкость | Фиксированный | Адаптивный |

---

## 🚨 Риски и митигации

| Риск | Митигация |
|------|-----------|
| Agent делает лишние tool calls | Улучшить instructions, добавить stop conditions |
| Увеличенное время обработки | Кэширование, параллелизм |
| Разные результаты при повторах | Temperature=0, seed parameter |

---

**Начни с добавления LLM вызовов в существующие tools (`text_tools.py`).**

