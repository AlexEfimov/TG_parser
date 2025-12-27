"""
Tests for Phase 2E: Hybrid Agent Mode.

Tests for pipeline tool, hybrid agent configuration, and CLI flags.
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.agents.tools.text_tools import AgentContext, EntityItem
from tg_parser.agents.tools.pipeline_tool import (
    PipelineResult,
    process_with_pipeline,
    _fallback_basic_processing,
    InMemoryProcessedDocumentRepo,
)
from tg_parser.domain.models import MessageType, RawTelegramMessage


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_message() -> RawTelegramMessage:
    """Sample raw message for testing."""
    return RawTelegramMessage(
        id="12345",
        channel_id="labdiagnostica",
        message_type=MessageType.POST,
        date=datetime.now(UTC),
        text="""🔬 Новые методы диагностики в лаборатории!

Наша лаборатория внедряет передовые методы исследования крови.
Контакты: +7 (495) 123-45-67
Email: lab@example.com
Сайт: https://lab-example.com

#диагностика #лаборатория""",
        source_ref="tg:labdiagnostica:post:12345",
        raw_payload={"views": 100},
    )


@pytest.fixture
def mock_context() -> AgentContext:
    """Create a mock agent context."""
    return AgentContext(
        llm_client=None,
        use_llm_tools=False,
        provider="openai",
        model="gpt-4o-mini",
        pipeline=None,
        extra={},
    )


# ============================================================================
# Tests for PipelineResult model
# ============================================================================


class TestPipelineResult:
    """Tests for PipelineResult Pydantic model."""
    
    def test_pipeline_result_creation(self):
        """Test creating PipelineResult with all fields."""
        result = PipelineResult(
            text_clean="Cleaned text content",
            summary="A brief summary",
            topics=["laboratory", "diagnostics"],
            entities=[
                {"type": "email", "value": "test@example.com", "confidence": 0.95},
            ],
            language="ru",
            metadata={"pipeline_version": "v1.2"},
        )
        
        assert result.text_clean == "Cleaned text content"
        assert result.summary == "A brief summary"
        assert len(result.topics) == 2
        assert len(result.entities) == 1
        assert result.language == "ru"
        assert result.metadata["pipeline_version"] == "v1.2"
    
    def test_pipeline_result_defaults(self):
        """Test PipelineResult with default values."""
        result = PipelineResult(text_clean="Test")
        
        assert result.text_clean == "Test"
        assert result.summary is None
        assert result.topics == []
        assert result.entities == []
        assert result.language == "unknown"
        assert result.metadata == {}
    
    def test_pipeline_result_empty(self):
        """Test creating empty PipelineResult."""
        result = PipelineResult(text_clean="")
        
        assert result.text_clean == ""
        assert result.language == "unknown"


# ============================================================================
# Tests for fallback processing
# ============================================================================


class TestFallbackBasicProcessing:
    """Tests for _fallback_basic_processing function."""
    
    def test_fallback_basic_cleaning(self):
        """Test basic text cleaning in fallback."""
        text = "Hello   world   test"
        result = _fallback_basic_processing(text)
        
        assert "   " not in result.text_clean
        assert result.text_clean == "Hello world test"
    
    def test_fallback_language_detection_russian(self):
        """Test language detection for Russian text."""
        result = _fallback_basic_processing("Привет, как дела?")
        assert result.language == "ru"
    
    def test_fallback_language_detection_english(self):
        """Test language detection for English text."""
        result = _fallback_basic_processing("Hello, how are you?")
        assert result.language == "en"
    
    def test_fallback_extracts_email(self):
        """Test email extraction in fallback."""
        result = _fallback_basic_processing("Contact: test@example.com")
        
        emails = [e for e in result.entities if e["type"] == "email"]
        assert len(emails) == 1
        assert emails[0]["value"] == "test@example.com"
    
    def test_fallback_extracts_url(self):
        """Test URL extraction in fallback."""
        result = _fallback_basic_processing("Visit https://example.com")
        
        urls = [e for e in result.entities if e["type"] == "url"]
        assert len(urls) == 1
        assert "example.com" in urls[0]["value"]
    
    def test_fallback_extracts_hashtags(self):
        """Test hashtag extraction in fallback."""
        result = _fallback_basic_processing("Check #python #testing")
        
        hashtags = [e for e in result.entities if e["type"] == "hashtag"]
        assert len(hashtags) == 2
    
    def test_fallback_extracts_mentions(self):
        """Test mention extraction in fallback."""
        result = _fallback_basic_processing("Follow @user1 and @user2")
        
        mentions = [e for e in result.entities if e["type"] == "mention"]
        assert len(mentions) == 2
    
    def test_fallback_generates_summary(self):
        """Test summary generation in fallback."""
        result = _fallback_basic_processing(
            "This is the first sentence. This is another sentence."
        )
        
        assert result.summary is not None
        assert "first sentence" in result.summary
    
    def test_fallback_metadata_indicates_fallback(self):
        """Test that metadata indicates fallback mode."""
        result = _fallback_basic_processing("Test text")
        
        assert result.metadata.get("fallback") is True
        assert result.metadata.get("reason") == "pipeline_unavailable"


# ============================================================================
# Tests for InMemoryProcessedDocumentRepo
# ============================================================================


class TestInMemoryProcessedDocumentRepo:
    """Tests for InMemoryProcessedDocumentRepo."""
    
    @pytest.mark.asyncio
    async def test_save_and_exists(self):
        """Test saving document and checking existence."""
        repo = InMemoryProcessedDocumentRepo()
        
        mock_doc = MagicMock()
        mock_doc.source_ref = "test:123"
        
        await repo.save(mock_doc)
        
        assert await repo.exists("test:123")
        assert not await repo.exists("test:456")
    
    @pytest.mark.asyncio
    async def test_get_by_source_ref(self):
        """Test retrieving document by source_ref."""
        repo = InMemoryProcessedDocumentRepo()
        
        mock_doc = MagicMock()
        mock_doc.source_ref = "test:123"
        
        await repo.save(mock_doc)
        
        retrieved = await repo.get_by_source_ref("test:123")
        assert retrieved is mock_doc
    
    @pytest.mark.asyncio
    async def test_upsert(self):
        """Test upsert (update or insert)."""
        repo = InMemoryProcessedDocumentRepo()
        
        mock_doc1 = MagicMock()
        mock_doc1.source_ref = "test:123"
        mock_doc1.text_clean = "version1"
        
        mock_doc2 = MagicMock()
        mock_doc2.source_ref = "test:123"
        mock_doc2.text_clean = "version2"
        
        await repo.save(mock_doc1)
        await repo.upsert(mock_doc2)
        
        retrieved = await repo.get_by_source_ref("test:123")
        assert retrieved.text_clean == "version2"


# ============================================================================
# Tests for AgentContext with pipeline field
# ============================================================================


class TestAgentContextPhase2E:
    """Tests for AgentContext with Phase 2E pipeline field."""
    
    def test_context_with_pipeline(self):
        """Test context with pipeline instance."""
        mock_pipeline = MagicMock()
        
        ctx = AgentContext(
            llm_client=None,
            use_llm_tools=False,
            provider="openai",
            model="gpt-4o-mini",
            pipeline=mock_pipeline,
        )
        
        assert ctx.pipeline is mock_pipeline
    
    def test_context_default_pipeline_is_none(self):
        """Test that default pipeline is None."""
        ctx = AgentContext()
        assert ctx.pipeline is None
    
    def test_context_extra_can_hold_pipeline(self):
        """Test that extra dict can hold pipeline reference."""
        mock_pipeline = MagicMock()
        
        ctx = AgentContext(
            extra={"pipeline": mock_pipeline},
        )
        
        assert ctx.extra.get("pipeline") is mock_pipeline


# ============================================================================
# Tests for TGProcessingAgent with pipeline tool
# ============================================================================


class TestTGProcessingAgentPhase2E:
    """Tests for TGProcessingAgent with Phase 2E features."""
    
    def test_agent_with_pipeline_tool_enabled(self):
        """Test agent creation with pipeline tool enabled."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(
            use_pipeline_tool=True,
        )
        
        assert agent.use_pipeline_tool is True
    
    def test_agent_with_pipeline_instance(self):
        """Test agent with pipeline instance."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        mock_pipeline = MagicMock()
        
        agent = TGProcessingAgent(
            use_pipeline_tool=True,
            pipeline=mock_pipeline,
        )
        
        assert agent.pipeline is mock_pipeline
    
    def test_agent_basic_tools_count(self):
        """Test that basic agent has 3 tools."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(use_llm_tools=False, use_pipeline_tool=False)
        agent_instance = agent.agent
        
        assert len(agent_instance.tools) == 3  # clean_text, extract_topics, extract_entities
    
    def test_agent_with_pipeline_tool_has_4_tools(self):
        """Test that agent with pipeline tool has 4 tools."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(use_llm_tools=False, use_pipeline_tool=True)
        agent_instance = agent.agent
        
        assert len(agent_instance.tools) == 4  # 3 basic + process_with_pipeline
    
    def test_agent_llm_tools_with_pipeline_has_2_tools(self):
        """Test that LLM agent with pipeline tool has 2 tools."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(use_llm_tools=True, use_pipeline_tool=True)
        agent_instance = agent.agent
        
        assert len(agent_instance.tools) == 2  # analyze_text_deep + process_with_pipeline
    
    def test_agent_context_includes_pipeline(self):
        """Test that agent context includes pipeline."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        mock_pipeline = MagicMock()
        
        agent = TGProcessingAgent(
            use_pipeline_tool=True,
            pipeline=mock_pipeline,
        )
        
        ctx = agent.context
        
        assert ctx.pipeline is mock_pipeline
        assert ctx.extra.get("pipeline") is mock_pipeline
    
    def test_agent_instructions_include_hybrid_mode(self):
        """Test that instructions mention hybrid mode when enabled."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(use_llm_tools=False, use_pipeline_tool=True)
        agent_instance = agent.agent
        
        assert "HYBRID MODE" in agent_instance.instructions
        assert "process_with_pipeline" in agent_instance.instructions


# ============================================================================
# Tests for process_with_pipeline tool
# ============================================================================


class TestProcessWithPipelineTool:
    """Tests for process_with_pipeline function tool."""
    
    def test_tool_exists_and_is_callable(self):
        """Test that process_with_pipeline tool exists."""
        from tg_parser.agents.tools.pipeline_tool import process_with_pipeline
        
        assert process_with_pipeline is not None
        # It's a FunctionTool, not directly callable
    
    def test_pipeline_result_import(self):
        """Test that PipelineResult can be imported."""
        from tg_parser.agents.tools.pipeline_tool import PipelineResult
        
        assert PipelineResult is not None


# ============================================================================
# Tests for module exports
# ============================================================================


class TestModuleExports:
    """Tests for module exports in Phase 2E."""
    
    def test_tools_init_exports_pipeline_tool(self):
        """Test that tools/__init__.py exports pipeline tool."""
        from tg_parser.agents.tools import process_with_pipeline, PipelineResult
        
        assert process_with_pipeline is not None
        assert PipelineResult is not None
    
    def test_agents_init_exports_pipeline_tool(self):
        """Test that agents/__init__.py exports pipeline tool."""
        from tg_parser.agents import process_with_pipeline, PipelineResult
        
        assert process_with_pipeline is not None
        assert PipelineResult is not None


# ============================================================================
# Tests for CLI hybrid flag
# ============================================================================


class TestCLIHybridFlag:
    """Tests for --hybrid CLI flag."""
    
    def test_run_processing_accepts_use_pipeline_tool(self):
        """Test that run_processing accepts use_pipeline_tool parameter."""
        import inspect
        from tg_parser.cli.process_cmd import run_processing
        
        sig = inspect.signature(run_processing)
        params = list(sig.parameters.keys())
        
        assert "use_pipeline_tool" in params
    
    def test_process_with_agent_accepts_use_pipeline_tool(self):
        """Test that _process_with_agent accepts use_pipeline_tool parameter."""
        import inspect
        from tg_parser.cli.process_cmd import _process_with_agent
        
        sig = inspect.signature(_process_with_agent)
        params = list(sig.parameters.keys())
        
        assert "use_pipeline_tool" in params
        assert "pipeline" in params


# ============================================================================
# Integration tests (mock-based)
# ============================================================================


class TestHybridModeIntegration:
    """Integration tests for hybrid mode with mocks."""
    
    @pytest.mark.asyncio
    async def test_fallback_when_no_pipeline(self):
        """Test that fallback is used when pipeline is unavailable."""
        # This tests the fallback path directly
        result = _fallback_basic_processing(
            "Test message with email test@example.com and #hashtag"
        )
        
        assert result.text_clean is not None
        assert result.metadata.get("fallback") is True
        
        # Check that entities were extracted
        email_entities = [e for e in result.entities if e["type"] == "email"]
        hashtag_entities = [e for e in result.entities if e["type"] == "hashtag"]
        
        assert len(email_entities) == 1
        assert len(hashtag_entities) == 1

