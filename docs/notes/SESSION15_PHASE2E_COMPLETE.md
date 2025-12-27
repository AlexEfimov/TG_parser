# Session 15 — Phase 2E Complete

**Дата**: 27 декабря 2025  
**Branch**: `feature/v2.0-agents`  
**Предыдущий этап**: Phase 2C/2D (Session 14)  
**Фокус**: Интеграция v1.2 pipeline как инструмента агента

---

## ✅ Что реализовано в Phase 2E

### 1. Pipeline Tool (`tg_parser/agents/tools/pipeline_tool.py`)

Создан новый инструмент `process_with_pipeline` для гибридного режима:

```python
@function_tool
async def process_with_pipeline(
    ctx: RunContextWrapper[AgentContext],
    text: Annotated[str, "Raw text to process with v1.2 pipeline"],
    channel_id: Annotated[str, "Channel identifier"] = "agent_request",
    message_id: Annotated[int, "Message ID for tracking"] = 0,
) -> PipelineResult:
    """
    Process text using the proven v1.2 LLM pipeline.
    
    Use this tool when:
    - Text requires deep semantic analysis
    - You need reliable entity/topic extraction
    - Basic tools are insufficient
    """
```

Особенности:
- Оборачивает v1.2 `ProcessingPipelineImpl` как agent tool
- Создаёт pipeline on-demand если не передан в контексте
- Fallback на basic processing если pipeline недоступен
- Возвращает `PipelineResult` с text_clean, summary, topics, entities, language, metadata

### 2. Обновлённый AgentContext

```python
@dataclass
class AgentContext:
    llm_client: Any = None
    use_llm_tools: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    pipeline: Any = None  # NEW: Phase 2E
    extra: dict = field(default_factory=dict)
```

### 3. Обновлённый TGProcessingAgent

```python
class TGProcessingAgent:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        use_llm_tools: bool = False,
        use_pipeline_tool: bool = False,  # NEW
        llm_client: Any = None,
        pipeline: Any = None,  # NEW
    ):
```

Агент теперь динамически добавляет `process_with_pipeline` tool когда `use_pipeline_tool=True`.

### 4. CLI флаг `--hybrid`

```bash
# Hybrid mode: agent может использовать v1.2 pipeline
tg-parser process --channel @lab --agent --hybrid

# Полный режим: agent + LLM tools + pipeline tool
tg-parser process --channel @lab --agent --agent-llm --hybrid
```

### 5. Comprehensive Tests (32 теста)

```
tests/test_agents_phase2e.py

TestPipelineResult (3 tests)
TestFallbackBasicProcessing (9 tests)
TestInMemoryProcessedDocumentRepo (3 tests)
TestAgentContextPhase2E (3 tests)
TestTGProcessingAgentPhase2E (8 tests)
TestProcessWithPipelineTool (2 tests)
TestModuleExports (2 tests)
TestCLIHybridFlag (2 tests)
TestHybridModeIntegration (1 test)
```

---

## 📁 Изменённые файлы

```
tg_parser/agents/
├── __init__.py                      # Export process_with_pipeline, PipelineResult
├── processing_agent.py              # Add use_pipeline_tool, pipeline parameters
└── tools/
    ├── __init__.py                  # Export pipeline_tool components
    ├── text_tools.py                # Add pipeline field to AgentContext
    └── pipeline_tool.py             # NEW: process_with_pipeline tool

tg_parser/cli/
├── app.py                           # Add --hybrid flag
└── process_cmd.py                   # Handle use_pipeline_tool parameter

tests/
└── test_agents_phase2e.py           # NEW: 32 Phase 2E tests
```

---

## 📊 Сравнение режимов

| Режим | Скорость | Качество | LLM Calls | Tools Count | Use Case |
|-------|----------|----------|-----------|-------------|----------|
| Basic Agent | ⚡ Fast | ⭐⭐ | 1 | 3 | Quick triage |
| LLM Agent | 🐢 Slow | ⭐⭐⭐⭐ | 2+ | 1 | Deep analysis |
| Hybrid Agent (basic) | 🔄 Adaptive | ⭐⭐⭐⭐ | 1-2 | 4 | Best of both |
| Hybrid Agent (llm) | 🔄 Adaptive | ⭐⭐⭐⭐⭐ | 2-3 | 2 | Maximum quality |
| Pipeline v1.2 | 🐢 Slow | ⭐⭐⭐⭐ | 1 | N/A | Proven results |

---

## 🧪 Результаты тестов

```
============================= test session starts ==============================
tests/test_agents_phase2e.py ..................................... [100%]
============================== 32 passed in 0.61s ==============================

tests/test_agents.py ..................................... [100%]
======================== 37 passed, 1 skipped in 0.55s =========================
```

---

## 🎯 Критерии завершения Phase 2E

| # | Критерий | Статус |
|---|----------|--------|
| 1 | `process_with_pipeline` tool реализован | ✅ |
| 2 | `AgentContext` расширен для хранения pipeline | ✅ |
| 3 | `TGProcessingAgent` поддерживает `use_pipeline_tool` | ✅ |
| 4 | CLI флаг `--hybrid` работает | ✅ |
| 5 | 10+ новых тестов | ✅ (32 теста) |
| 6 | Документация обновлена | ✅ |
| 7 | Существующие тесты проходят | ✅ (37/38 passed, 1 skipped) |

---

## 🚀 Примеры использования

### CLI

```bash
# Basic agent (3 tools: clean_text, extract_topics, extract_entities)
tg-parser process --channel @labdiagnostica --agent

# Agent with LLM tools (1 tool: analyze_text_deep)
tg-parser process --channel @labdiagnostica --agent --agent-llm

# Hybrid mode - basic agent + pipeline tool (4 tools)
tg-parser process --channel @labdiagnostica --agent --hybrid

# Full hybrid - LLM agent + pipeline tool (2 tools)
tg-parser process --channel @labdiagnostica --agent --agent-llm --hybrid
```

### Python API

```python
from tg_parser.agents import TGProcessingAgent

# Basic agent
agent = TGProcessingAgent()

# Hybrid agent
agent = TGProcessingAgent(
    use_pipeline_tool=True,
    pipeline=my_pipeline_instance,  # Optional
)

# Full hybrid with LLM tools
agent = TGProcessingAgent(
    use_llm_tools=True,
    use_pipeline_tool=True,
    llm_client=my_llm_client,
    pipeline=my_pipeline,
)

# Process message
doc = await agent.process(message)
```

---

## 🔮 Следующие этапы

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
- **Pipeline Tool**: `tg_parser/agents/tools/pipeline_tool.py`
- **Processing Agent**: `tg_parser/agents/processing_agent.py`
- **OpenAI Agents SDK**: https://github.com/openai/openai-agents-python

---

**Phase 2E успешно завершён!** 🎉

