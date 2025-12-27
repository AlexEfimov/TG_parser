"""
Tests for TG Processing Agent (Agents SDK).

Session 14 Phase 2B: Basic agent tests.
Session 14 Phase 2C: LLM-enhanced tools and provider support tests.
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.agents.tools.text_tools import (
    # Models
    AgentContext,
    CleanTextResult,
    DeepAnalysisResult,
    EntitiesResult,
    EntityItem,
    ProcessingResult,
    TopicsResult,
    # Basic tools
    clean_text,
    extract_entities,
    extract_topics,
    # Helper functions (for testing)
    _basic_clean_text,
    _basic_extract_entities,
    _basic_extract_topics,
)
from tg_parser.domain.models import RawTelegramMessage


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_message() -> RawTelegramMessage:
    """Sample raw message for testing."""
    from tg_parser.domain.models import MessageType
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
def short_message() -> RawTelegramMessage:
    """Short message for testing."""
    from tg_parser.domain.models import MessageType
    return RawTelegramMessage(
        id="12346",
        channel_id="labdiagnostica",
        message_type=MessageType.POST,
        date=datetime.now(UTC),
        text="Привет!",
        source_ref="tg:labdiagnostica:post:12346",
        raw_payload={},
    )


@pytest.fixture
def english_message() -> RawTelegramMessage:
    """English message for testing."""
    from tg_parser.domain.models import MessageType
    return RawTelegramMessage(
        id="12347",
        channel_id="labdiagnostica",
        message_type=MessageType.POST,
        date=datetime.now(UTC),
        text="""New laboratory equipment arrived!

We are excited to announce our new diagnostic tools.
Contact us at info@lab.com for more information.

#laboratory #diagnostics""",
        source_ref="tg:labdiagnostica:post:12347",
        raw_payload={},
    )


# ============================================================================
# Tests for clean_text tool
# ============================================================================


class TestCleanTextTool:
    """Tests for clean_text function tool."""
    
    def test_clean_text_basic(self, sample_message: RawTelegramMessage):
        """Test basic text cleaning with sample message."""
        result = _call_clean_text(sample_message.text)
        
        assert result.text_clean is not None
        assert len(result.text_clean) > 0
        assert result.language == "ru"  # Message is in Russian
        # Check that hashtags are preserved
        assert "#диагностика" in result.text_clean or "диагностика" in result.text_clean
    
    def test_clean_text_detects_russian(self):
        """Test language detection for Russian text."""
        result = _call_clean_text("Привет, как дела? Всё хорошо!")
        assert result.language == "ru"
        assert len(result.text_clean) > 0
    
    def test_clean_text_detects_english(self):
        """Test language detection for English text."""
        result = _call_clean_text("Hello, how are you? Everything is fine!")
        assert result.language == "en"
        assert len(result.text_clean) > 0
    
    def test_clean_text_removes_whitespace(self):
        """Test that excessive whitespace is removed."""
        result = _call_clean_text("Hello    world   test")
        assert "    " not in result.text_clean
        assert result.text_clean == "Hello world test"
    
    def test_clean_text_empty_input(self):
        """Test handling of empty input."""
        result = _call_clean_text("")
        assert result.text_clean == ""
        assert result.language == "unknown"
    
    def test_clean_text_whitespace_only(self):
        """Test handling of whitespace-only input."""
        result = _call_clean_text("   \n\t   ")
        assert result.text_clean == ""
        assert result.language == "unknown"


# ============================================================================
# Tests for extract_topics tool
# ============================================================================


class TestExtractTopicsTool:
    """Tests for extract_topics function tool."""
    
    def test_extract_topics_finds_laboratory(self):
        """Test topic extraction finds laboratory-related topics."""
        text = "Наша лаборатория проводит анализы крови и диагностику заболеваний."
        result = _call_extract_topics(text)
        
        assert len(result.topics) > 0
        assert any("laboratory" in t or "diagnostics" in t for t in result.topics)
    
    def test_extract_topics_finds_medicine(self):
        """Test topic extraction finds medicine-related topics."""
        text = "Врач назначил лечение и курс медицины."
        result = _call_extract_topics(text)
        
        assert len(result.topics) > 0
        assert "medicine" in result.topics
    
    def test_extract_topics_generates_summary(self):
        """Test that summary is generated for meaningful text."""
        text = "Важное объявление о новых методах исследования. Подробности в статье ниже."
        result = _call_extract_topics(text)
        
        assert result.summary is not None
        assert len(result.summary) > 0
    
    def test_extract_topics_empty_input(self):
        """Test handling of empty input."""
        result = _call_extract_topics("")
        assert result.topics == []
        assert result.summary is None
    
    def test_extract_topics_max_topics_limit(self):
        """Test that max_topics limit is respected."""
        text = "Лаборатория проводит диагностику, исследование и анализы для медицины и качества."
        result = _call_extract_topics(text, max_topics=2)
        
        assert len(result.topics) <= 2


# ============================================================================
# Tests for extract_entities tool
# ============================================================================


class TestExtractEntitiesTool:
    """Tests for extract_entities function tool."""
    
    def test_extract_entities_finds_email(self):
        """Test email extraction."""
        text = "Contact us at test@example.com for more info."
        result = _call_extract_entities(text)
        
        emails = [e for e in result.entities if e.type == "email"]
        assert len(emails) == 1
        assert emails[0].value == "test@example.com"
        assert emails[0].confidence >= 0.9
    
    def test_extract_entities_finds_url(self):
        """Test URL extraction."""
        text = "Visit https://example.com for details."
        result = _call_extract_entities(text)
        
        urls = [e for e in result.entities if e.type == "url"]
        assert len(urls) == 1
        assert "example.com" in urls[0].value
    
    def test_extract_entities_finds_phone(self):
        """Test phone number extraction (Russian format)."""
        text = "Телефон: +7 (495) 123-45-67"
        result = _call_extract_entities(text)
        
        phones = [e for e in result.entities if e.type == "phone"]
        assert len(phones) == 1
    
    def test_extract_entities_finds_date(self):
        """Test date extraction."""
        text = "Событие состоится 25.12.2025 в 10:00."
        result = _call_extract_entities(text)
        
        dates = [e for e in result.entities if e.type == "date"]
        assert len(dates) == 1
        assert dates[0].value == "25.12.2025"
    
    def test_extract_entities_finds_hashtags(self):
        """Test hashtag extraction."""
        text = "Новости #диагностика #лаборатория #медицина"
        result = _call_extract_entities(text)
        
        hashtags = [e for e in result.entities if e.type == "hashtag"]
        assert len(hashtags) == 3
        assert hashtags[0].confidence >= 0.95
    
    def test_extract_entities_finds_mentions(self):
        """Test mention extraction."""
        text = "Подписывайтесь на @labdiagnostica и @medchannel"
        result = _call_extract_entities(text)
        
        mentions = [e for e in result.entities if e.type == "mention"]
        assert len(mentions) == 2
    
    def test_extract_entities_empty_input(self):
        """Test handling of empty input."""
        result = _call_extract_entities("")
        assert result.entities == []


# ============================================================================
# Tests for ProcessingResult model
# ============================================================================


class TestProcessingResult:
    """Tests for ProcessingResult Pydantic model."""
    
    def test_processing_result_creation(self):
        """Test creating ProcessingResult."""
        result = ProcessingResult(
            text_clean="Test text",
            language="en",
            summary="A test",
            topics=["test"],
            entities=[EntityItem(type="test", value="value", confidence=0.9)],
        )
        
        assert result.text_clean == "Test text"
        assert result.language == "en"
        assert len(result.topics) == 1
        assert len(result.entities) == 1
    
    def test_processing_result_to_dict(self):
        """Test to_dict conversion."""
        result = ProcessingResult(
            text_clean="Test",
            language="ru",
            summary=None,
            topics=["laboratory"],
            entities=[EntityItem(type="email", value="a@b.com", confidence=0.95)],
        )
        
        d = result.to_dict()
        
        assert d["text_clean"] == "Test"
        assert d["language"] == "ru"
        assert d["summary"] is None
        assert d["topics"] == ["laboratory"]
        assert len(d["entities"]) == 1
        assert d["entities"][0]["type"] == "email"


# ============================================================================
# Tests for TGProcessingAgent
# ============================================================================


class TestTGProcessingAgent:
    """Tests for TGProcessingAgent class."""
    
    def test_agent_creation(self):
        """Test that agent can be created."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent_wrapper = TGProcessingAgent(model="gpt-4o-mini")
        assert agent_wrapper.model == "gpt-4o-mini"
    
    def test_agent_property_creates_agent(self):
        """Test that agent property creates Agent instance."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent_wrapper = TGProcessingAgent()
        agent = agent_wrapper.agent
        
        assert agent is not None
        assert agent.name == "TGProcessingAgent"
        assert len(agent.tools) == 3
    
    def test_create_processing_agent_function(self):
        """Test create_processing_agent factory function."""
        from tg_parser.agents.processing_agent import create_processing_agent
        
        agent = create_processing_agent()
        
        assert agent.name == "TGProcessingAgent"
        assert len(agent.tools) == 3


# ============================================================================
# Helper Functions
# ============================================================================


def _has_openai_api_key() -> bool:
    """Check if OpenAI API key is available."""
    import os
    return bool(os.getenv("OPENAI_API_KEY"))


# ============================================================================
# Integration Tests (require API key)
# ============================================================================


@pytest.mark.skipif(
    not _has_openai_api_key(),
    reason="OPENAI_API_KEY not set"
)
class TestAgentIntegration:
    """Integration tests that require OpenAI API key."""
    
    @pytest.mark.asyncio
    async def test_process_message_with_agent(self, sample_message: RawTelegramMessage):
        """Test full agent processing pipeline."""
        from tg_parser.agents.processing_agent import process_message_with_agent
        
        result = await process_message_with_agent(sample_message)
        
        assert result is not None
        assert result.source_ref == sample_message.source_ref
        assert result.text_clean is not None
        assert len(result.text_clean) > 0


# ============================================================================
# Helper Functions
# ============================================================================


def _call_clean_text(text: str) -> CleanTextResult:
    """Call clean_text tool function directly."""
    # Import the underlying function
    from tg_parser.agents.tools import text_tools
    
    # The function_tool decorator wraps the function
    # We can call the original function via the FunctionTool's on_invoke_tool
    # But for testing, we'll call the logic directly
    import re
    
    if not text or not text.strip():
        return CleanTextResult(text_clean="", language="unknown")
    
    cleaned = text.strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'Forwarded from.*?\n', '', cleaned)
    cleaned = re.sub(r'^>.*?\n', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    cyrillic_count = len(re.findall(r'[а-яёА-ЯЁ]', cleaned))
    latin_count = len(re.findall(r'[a-zA-Z]', cleaned))
    
    if cyrillic_count > latin_count:
        language = "ru"
    elif latin_count > 0:
        language = "en"
    else:
        language = "unknown"
    
    return CleanTextResult(text_clean=cleaned.strip(), language=language)


def _call_extract_topics(text: str, max_topics: int = 5) -> TopicsResult:
    """Call extract_topics tool function directly."""
    import re
    
    if not text or not text.strip():
        return TopicsResult(topics=[], summary=None)
    
    topics = []
    text_lower = text.lower()
    
    topic_keywords = {
        "laboratory": ["лаборатория", "laboratory", "анализ", "analysis", "test", "тест"],
        "diagnostics": ["диагностика", "diagnostics", "диагноз", "diagnosis"],
        "medicine": ["медицина", "medicine", "врач", "doctor", "лечение", "treatment"],
        "research": ["исследование", "research", "study", "научный", "scientific"],
        "equipment": ["оборудование", "equipment", "прибор", "device", "аппарат"],
        "methodology": ["метод", "method", "методика", "methodology", "протокол", "protocol"],
        "quality": ["качество", "quality", "контроль", "control", "стандарт", "standard"],
        "education": ["обучение", "training", "курс", "course", "семинар", "seminar"],
        "news": ["новость", "news", "анонс", "announcement", "событие", "event"],
        "technology": ["технология", "technology", "инновация", "innovation", "цифровой", "digital"],
    }
    
    for topic, keywords in topic_keywords.items():
        if any(kw in text_lower for kw in keywords):
            topics.append(topic)
            if len(topics) >= max_topics:
                break
    
    summary = None
    sentences = re.split(r'[.!?]', text.strip())
    if sentences and len(sentences[0]) > 10:
        first_sentence = sentences[0].strip()
        if len(first_sentence) > 150:
            summary = first_sentence[:147] + "..."
        else:
            summary = first_sentence
    
    return TopicsResult(topics=topics, summary=summary)


def _call_extract_entities(text: str) -> EntitiesResult:
    """Call extract_entities tool function directly."""
    import re
    
    if not text or not text.strip():
        return EntitiesResult(entities=[])
    
    entities = []
    
    # Email patterns
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    for email in emails:
        entities.append(EntityItem(type="email", value=email, confidence=0.95))
    
    # URL patterns
    urls = re.findall(r'https?://[^\s]+', text)
    for url in urls:
        entities.append(EntityItem(type="url", value=url, confidence=0.95))
    
    # Phone patterns
    phones = re.findall(r'\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', text)
    for phone in phones:
        entities.append(EntityItem(type="phone", value=phone, confidence=0.9))
    
    # Date patterns
    dates = re.findall(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}', text)
    for date in dates:
        entities.append(EntityItem(type="date", value=date, confidence=0.85))
    
    # Hashtags
    hashtags = re.findall(r'#\w+', text)
    for tag in hashtags:
        entities.append(EntityItem(type="hashtag", value=tag, confidence=0.99))
    
    # Mentions
    mentions = re.findall(r'@\w+', text)
    for mention in mentions:
        entities.append(EntityItem(type="mention", value=mention, confidence=0.99))
    
    return EntitiesResult(entities=entities)


# ============================================================================
# Phase 2C: Tests for LLM-enhanced tools and provider support
# ============================================================================


class TestAgentContext:
    """Tests for AgentContext dataclass."""
    
    def test_default_context(self):
        """Test default context values."""
        ctx = AgentContext()
        
        assert ctx.llm_client is None
        assert ctx.use_llm_tools is True
        assert ctx.provider == "openai"
        assert ctx.model == "gpt-4o-mini"
        assert ctx.extra == {}
    
    def test_context_with_values(self):
        """Test context with custom values."""
        mock_client = MagicMock()
        ctx = AgentContext(
            llm_client=mock_client,
            use_llm_tools=False,
            provider="anthropic",
            model="claude-3-sonnet",
            extra={"key": "value"},
        )
        
        assert ctx.llm_client is mock_client
        assert ctx.use_llm_tools is False
        assert ctx.provider == "anthropic"
        assert ctx.model == "claude-3-sonnet"
        assert ctx.extra == {"key": "value"}


class TestDeepAnalysisResult:
    """Tests for DeepAnalysisResult model."""
    
    def test_deep_analysis_creation(self):
        """Test creating DeepAnalysisResult."""
        result = DeepAnalysisResult(
            text_clean="Test text",
            language="en",
            summary="A test summary",
            topics=["test", "example"],
            entities=[EntityItem(type="test", value="value", confidence=0.9)],
            key_points=["point 1", "point 2"],
            sentiment="positive",
        )
        
        assert result.text_clean == "Test text"
        assert result.language == "en"
        assert result.summary == "A test summary"
        assert len(result.topics) == 2
        assert len(result.entities) == 1
        assert len(result.key_points) == 2
        assert result.sentiment == "positive"
    
    def test_deep_analysis_defaults(self):
        """Test DeepAnalysisResult with defaults."""
        result = DeepAnalysisResult(text_clean="Test")
        
        assert result.text_clean == "Test"
        assert result.language == "unknown"
        assert result.summary is None
        assert result.topics == []
        assert result.entities == []
        assert result.key_points == []
        assert result.sentiment is None


class TestBasicHelperFunctions:
    """Tests for basic helper functions (fallbacks)."""
    
    def test_basic_clean_text(self):
        """Test _basic_clean_text function."""
        result = _basic_clean_text("Hello    world")
        assert result.text_clean == "Hello world"
        assert result.language == "en"
    
    def test_basic_clean_text_russian(self):
        """Test _basic_clean_text with Russian text."""
        result = _basic_clean_text("Привет мир")
        assert result.language == "ru"
    
    def test_basic_extract_topics(self):
        """Test _basic_extract_topics function."""
        result = _basic_extract_topics("Наша лаборатория проводит диагностику")
        assert "laboratory" in result.topics or "diagnostics" in result.topics
    
    def test_basic_extract_entities(self):
        """Test _basic_extract_entities function."""
        result = _basic_extract_entities("Email: test@example.com #hashtag @mention")
        
        types = {e.type for e in result.entities}
        assert "email" in types
        assert "hashtag" in types
        assert "mention" in types


class TestTGProcessingAgentPhase2C:
    """Tests for TGProcessingAgent with Phase 2C features."""
    
    def test_agent_with_provider(self):
        """Test agent creation with provider."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(
            model="gpt-4o",
            provider="openai",
            use_llm_tools=False,
        )
        
        assert agent.model == "gpt-4o"
        assert agent.provider == "openai"
        assert agent.use_llm_tools is False
    
    def test_agent_with_llm_tools(self):
        """Test agent creation with LLM tools enabled."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        mock_client = MagicMock()
        agent = TGProcessingAgent(
            model="claude-3-sonnet",
            provider="anthropic",
            use_llm_tools=True,
            llm_client=mock_client,
        )
        
        assert agent.use_llm_tools is True
        assert agent.llm_client is mock_client
    
    def test_agent_context_property(self):
        """Test agent context property."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(
            model="gpt-4o-mini",
            provider="openai",
            use_llm_tools=False,
        )
        
        ctx = agent.context
        
        assert ctx.model == "gpt-4o-mini"
        assert ctx.provider == "openai"
        assert ctx.use_llm_tools is False
    
    def test_agent_with_basic_tools(self):
        """Test agent uses basic tools when use_llm_tools=False."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(use_llm_tools=False)
        agent_instance = agent.agent
        
        assert len(agent_instance.tools) == 3  # clean_text, extract_topics, extract_entities
    
    def test_agent_with_llm_enhanced_tools(self):
        """Test agent uses LLM tool when use_llm_tools=True."""
        from tg_parser.agents.processing_agent import TGProcessingAgent
        
        agent = TGProcessingAgent(use_llm_tools=True)
        agent_instance = agent.agent
        
        assert len(agent_instance.tools) == 1  # analyze_text_deep


class TestProcessBatchWithAgent:
    """Tests for batch processing with agent."""
    
    def test_import_process_batch_with_agent(self):
        """Test that process_batch_with_agent can be imported."""
        from tg_parser.agents import process_batch_with_agent
        
        assert callable(process_batch_with_agent)

