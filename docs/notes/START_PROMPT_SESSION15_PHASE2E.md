# Session 15 — Phase 2E: Hybrid Agent Mode

**Дата**: 27 декабря 2025  
**Branch**: `feature/v2.0-agents`  
**Предыдущий этап**: Phase 2C/2D (Session 14)  
**Фокус**: Интеграция v1.2 pipeline как инструмента агента

---

## 📋 Цель Phase 2E

Создать **гибридный режим** агента, где:
1. Agent может вызывать **v1.2 pipeline** как специальный инструмент
2. Agent сам решает, когда использовать pipeline vs собственные tools
3. Объединяем преимущества обоих подходов

---

## 🔧 Текущее состояние

### Что уже есть:

#### v1.2 Pipeline (`tg_parser/processing/pipeline.py`):
```python
class ProcessingPipelineImpl(ProcessingPipeline):
    """
    LLM-based processing с:
    - Детальным parsing JSON ответов
    - Retry механизмом (3 попытки, backoff)
    - Записью в репозиторий
    - Поддержкой всех LLM провайдеров
    """
    
    async def process_message(
        self, 
        message: RawTelegramMessage, 
        force: bool = False
    ) -> ProcessedDocument
```

#### Agent Tools (`tg_parser/agents/tools/text_tools.py`):
```python
# Basic tools (pattern matching, быстрые)
clean_text(text) -> CleanTextResult
extract_topics(text, max_topics) -> TopicsResult  
extract_entities(text) -> EntitiesResult

# LLM-enhanced tools (глубокий анализ)
analyze_text_deep(ctx, text) -> DeepAnalysisResult
extract_topics_llm(ctx, text) -> TopicsResult
extract_entities_llm(ctx, text) -> EntitiesResult
```

#### Agent Context:
```python
@dataclass
class AgentContext:
    llm_client: Any = None
    use_llm_tools: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    extra: dict = field(default_factory=dict)
```

---

## 🎯 Целевая архитектура Phase 2E

### Новый инструмент — `process_with_pipeline`:

```python
# tg_parser/agents/tools/pipeline_tool.py

from agents import RunContextWrapper, function_tool
from pydantic import BaseModel, Field

class PipelineResult(BaseModel):
    """Result from v1.2 pipeline processing."""
    text_clean: str
    summary: str | None
    topics: list[str]
    entities: list[dict]
    language: str
    metadata: dict = Field(default_factory=dict)


@function_tool
async def process_with_pipeline(
    ctx: RunContextWrapper[AgentContext],
    text: Annotated[str, "Raw text to process with v1.2 pipeline"],
    channel_id: Annotated[str, "Channel identifier"] = "unknown",
    message_id: Annotated[int, "Message ID"] = 0,
) -> PipelineResult:
    """
    Process text using the proven v1.2 LLM pipeline.
    
    Use this tool when:
    - Text requires deep semantic analysis
    - You need reliable entity/topic extraction
    - Basic tools are insufficient
    
    This tool uses the full LLM pipeline with:
    - Configurable prompts (YAML-based)
    - Retry mechanism
    - Multi-LLM support
    """
    # Получить pipeline из контекста
    pipeline = ctx.context.extra.get("pipeline")
    if not pipeline:
        # Fallback: создать pipeline на лету
        pipeline = await _create_pipeline(ctx.context)
    
    # Создать RawTelegramMessage
    message = RawTelegramMessage(
        id=str(uuid4()),
        source_ref=f"agent_request_{message_id}",
        channel_id=channel_id,
        text=text,
        date=datetime.now(UTC),
        raw_json={},
    )
    
    # Обработать через pipeline
    doc = await pipeline.process_message(message, force=True)
    
    return PipelineResult(
        text_clean=doc.text_clean,
        summary=doc.summary,
        topics=doc.topics,
        entities=[e.model_dump() for e in doc.entities],
        language=doc.language,
        metadata=doc.metadata,
    )
```

### Обновлённый AgentContext:

```python
@dataclass
class AgentContext:
    llm_client: Any = None
    use_llm_tools: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    # NEW: v1.2 pipeline instance
    pipeline: ProcessingPipelineImpl | None = None
    extra: dict = field(default_factory=dict)
```

### Новый режим агента — Hybrid:

```python
class TGProcessingAgent:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        use_llm_tools: bool = False,
        use_pipeline_tool: bool = False,  # NEW
        llm_client: Any = None,
        pipeline: ProcessingPipelineImpl | None = None,  # NEW
    ):
        ...
    
    @property
    def agent(self) -> Agent:
        if self._agent is None:
            # Choose tools based on configuration
            tools = [clean_text, extract_topics, extract_entities]
            
            if self.use_llm_tools:
                tools.append(analyze_text_deep)
            
            if self.use_pipeline_tool:
                tools.append(process_with_pipeline)  # NEW
            
            ...
```

---

## 📝 CLI изменения

### Новые флаги:

```bash
# Hybrid mode: agent может использовать v1.2 pipeline
tg-parser process --channel @lab --agent --hybrid

# Полный режим: agent + LLM tools + pipeline tool
tg-parser process --channel @lab --agent --agent-llm --hybrid
```

### Реализация в `process_cmd.py`:

```python
@app.command()
def process(
    channel: str,
    agent: bool = typer.Option(False, "--agent", help="Use agent-based processing"),
    agent_llm: bool = typer.Option(False, "--agent-llm", help="Enable LLM tools in agent"),
    hybrid: bool = typer.Option(False, "--hybrid", help="Enable v1.2 pipeline as tool"),  # NEW
    ...
):
    if agent:
        use_pipeline_tool = hybrid
        # Create TGProcessingAgent with pipeline tool
```

---

## 🧪 Тесты

### Новые тесты для Phase 2E:

```python
# tests/test_agents_phase2e.py

class TestPipelineTool:
    """Tests for process_with_pipeline tool."""
    
    def test_pipeline_tool_exists(self):
        from tg_parser.agents.tools.pipeline_tool import process_with_pipeline
        assert callable(process_with_pipeline)
    
    async def test_pipeline_tool_with_mock_pipeline(self):
        ...
    
    async def test_pipeline_tool_fallback(self):
        """Test fallback when pipeline not in context."""
        ...


class TestHybridAgent:
    """Tests for hybrid agent mode."""
    
    def test_agent_with_pipeline_tool(self):
        agent = TGProcessingAgent(
            use_pipeline_tool=True,
        )
        assert len(agent.agent.tools) == 4  # 3 basic + pipeline
    
    def test_agent_full_hybrid(self):
        agent = TGProcessingAgent(
            use_llm_tools=True,
            use_pipeline_tool=True,
        )
        # analyze_text_deep + process_with_pipeline
        ...


class TestCLIHybridFlag:
    """Tests for --hybrid CLI flag."""
    
    def test_hybrid_flag_parsing(self):
        ...
```

---

## 📊 Ожидаемые результаты

### Сравнение режимов:

| Режим | Скорость | Качество | LLM Calls | Use Case |
|-------|----------|----------|-----------|----------|
| Basic Agent | ⚡ Fast | ⭐⭐ | 1 (orchestration) | Quick triage |
| LLM Agent | 🐢 Slow | ⭐⭐⭐⭐ | 2+ | Deep analysis |
| Hybrid Agent | 🔄 Adaptive | ⭐⭐⭐⭐⭐ | 1-3 | Best of both |
| Pipeline v1.2 | 🐢 Slow | ⭐⭐⭐⭐ | 1 | Proven results |

### Преимущества Hybrid Mode:

1. **Адаптивность**: Agent сам решает, когда нужен pipeline
2. **Эффективность**: Простые сообщения → basic tools, сложные → pipeline
3. **Надёжность**: Fallback на проверенный pipeline
4. **Flexibility**: Можно комбинировать tools по ситуации

---

## 📁 Файлы для изменения

```
tg_parser/agents/
├── tools/
│   ├── __init__.py              # Export pipeline_tool
│   ├── text_tools.py            # Update AgentContext
│   └── pipeline_tool.py         # NEW: process_with_pipeline
├── processing_agent.py          # Add use_pipeline_tool, hybrid support
└── __init__.py                  # Export new components

tg_parser/cli/
├── app.py                       # Add --hybrid flag
└── process_cmd.py               # Handle hybrid mode

tests/
├── test_agents.py               # Update existing tests
└── test_agents_phase2e.py       # NEW: Phase 2E tests
```

---

## ✅ Критерии завершения Phase 2E

1. [ ] `process_with_pipeline` tool реализован
2. [ ] `AgentContext` расширен для хранения pipeline
3. [ ] `TGProcessingAgent` поддерживает `use_pipeline_tool`
4. [ ] CLI флаг `--hybrid` работает
5. [ ] 10+ новых тестов
6. [ ] Документация обновлена
7. [ ] Сравнительный benchmark (basic vs llm vs hybrid vs pipeline)

---

## 🚀 Следующие этапы

После Phase 2E:

| Этап | Название | Описание |
|------|----------|----------|
| **Phase 2F** | API Production | Auth, rate limiting, webhooks для HTTP API |
| **Phase 3A** | Multi-Agent | Специализированные агенты (cleaner, extractor, summarizer) |
| **Phase 3B** | RAG Integration | Векторный поиск, embeddings, knowledge base |
| **Phase 3C** | Web UI | Dashboard для управления обработкой |

---

## 📎 Ссылки

- **Предыдущий этап**: `docs/notes/SESSION14_PHASE2C_COMPLETE.md`
- **v1.2 Pipeline**: `tg_parser/processing/pipeline.py`
- **Agent Tools**: `tg_parser/agents/tools/text_tools.py`
- **Processing Agent**: `tg_parser/agents/processing_agent.py`
- **OpenAI Agents SDK**: https://github.com/openai/openai-agents-python

---

**Готов к началу Phase 2E!**

