"""
Text processing tools for TG Processing Agent.

Function tools using OpenAI Agents SDK @function_tool decorator.
Each tool performs a specific text processing task.

Phase 2C: Added LLM-enhanced versions of tools for deep analysis.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Annotated, Any

from agents import RunContextWrapper, function_tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Agent Context for LLM access
# ============================================================================


@dataclass
class AgentContext:
    """
    Context for agent tools.
    
    Provides access to LLM client and configuration for enhanced tools.
    Phase 2E: Added pipeline field for hybrid mode.
    """
    llm_client: Any = None  # LLMClient instance (optional)
    use_llm_tools: bool = True  # Enable LLM-enhanced tools
    provider: str = "openai"  # LLM provider name
    model: str = "gpt-4o-mini"  # Model name
    pipeline: Any = None  # ProcessingPipelineImpl instance (Phase 2E)
    extra: dict = field(default_factory=dict)  # Extra context data


# ============================================================================
# Pydantic Models for structured outputs
# ============================================================================


class EntityItem(BaseModel):
    """Single extracted entity."""
    type: str = Field(description="Entity type: person, organization, location, product, etc.")
    value: str = Field(description="Entity value/name")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Confidence score 0-1")


class CleanTextResult(BaseModel):
    """Result of text cleaning operation."""
    text_clean: str = Field(description="Cleaned and normalized text")
    language: str = Field(default="unknown", description="Detected language code (ISO 639-1)")


class TopicsResult(BaseModel):
    """Result of topic extraction operation."""
    topics: list[str] = Field(default_factory=list, description="List of extracted topics")
    summary: str | None = Field(default=None, description="Brief summary if applicable")


class EntitiesResult(BaseModel):
    """Result of entity extraction operation."""
    entities: list[EntityItem] = Field(default_factory=list, description="List of extracted entities")


# ============================================================================
# Function Tools
# ============================================================================


@function_tool
def clean_text(
    text: Annotated[str, "The raw text to clean and normalize"]
) -> CleanTextResult:
    """
    Clean and normalize raw text from a Telegram message.
    
    This tool performs:
    - Remove noise (excessive whitespace, special characters)
    - Fix formatting issues
    - Normalize unicode
    - Detect language
    
    Returns cleaned text and detected language.
    """
    if not text or not text.strip():
        return CleanTextResult(text_clean="", language="unknown")
    
    # Basic text cleaning (synchronous, no LLM needed for basic cleaning)
    cleaned = text.strip()
    
    # Remove excessive whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Remove common Telegram noise patterns
    # - Forward headers
    cleaned = re.sub(r'Forwarded from.*?\n', '', cleaned)
    # - Reply quotes (starting with >)
    cleaned = re.sub(r'^>.*?\n', '', cleaned, flags=re.MULTILINE)
    
    # Normalize line breaks
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    # Detect language (simple heuristic)
    # Count Cyrillic vs Latin characters
    cyrillic_count = len(re.findall(r'[а-яёА-ЯЁ]', cleaned))
    latin_count = len(re.findall(r'[a-zA-Z]', cleaned))
    
    if cyrillic_count > latin_count:
        language = "ru"
    elif latin_count > 0:
        language = "en"
    else:
        language = "unknown"
    
    logger.debug(f"clean_text: input={len(text)} chars, output={len(cleaned)} chars, lang={language}")
    
    return CleanTextResult(text_clean=cleaned.strip(), language=language)


@function_tool
def extract_topics(
    text: Annotated[str, "The text to extract topics from"],
    max_topics: Annotated[int, "Maximum number of topics to extract"] = 5
) -> TopicsResult:
    """
    Extract main topics and themes from text.
    
    Identifies key topics, categories, and themes present in the text.
    Also generates a brief summary if the text is meaningful.
    
    Returns list of topics and optional summary.
    """
    if not text or not text.strip():
        return TopicsResult(topics=[], summary=None)
    
    # Extract topics using keyword analysis (basic implementation for PoC)
    # In production, this would use LLM for semantic analysis
    
    topics = []
    text_lower = text.lower()
    
    # Domain-specific topic detection (medical/lab diagnostics context)
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
    
    # Generate summary (first sentence or first N characters)
    summary = None
    sentences = re.split(r'[.!?]', text.strip())
    if sentences and len(sentences[0]) > 10:
        first_sentence = sentences[0].strip()
        if len(first_sentence) > 150:
            summary = first_sentence[:147] + "..."
        else:
            summary = first_sentence
    
    logger.debug(f"extract_topics: found {len(topics)} topics, summary={bool(summary)}")
    
    return TopicsResult(topics=topics, summary=summary)


@function_tool
def extract_entities(
    text: Annotated[str, "The text to extract named entities from"]
) -> EntitiesResult:
    """
    Extract named entities from text.
    
    Identifies and extracts:
    - Persons (names of people)
    - Organizations (companies, institutions)
    - Locations (cities, countries, addresses)
    - Products (product names, brands)
    - Dates (date mentions)
    - Other relevant entities
    
    Returns list of entities with types and confidence scores.
    """
    if not text or not text.strip():
        return EntitiesResult(entities=[])
    
    entities = []
    
    # Pattern-based entity extraction (basic implementation for PoC)
    # In production, this would use NER models or LLM
    
    # Email patterns
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    for email in emails:
        entities.append(EntityItem(type="email", value=email, confidence=0.95))
    
    # URL patterns
    urls = re.findall(r'https?://[^\s]+', text)
    for url in urls:
        entities.append(EntityItem(type="url", value=url, confidence=0.95))
    
    # Phone patterns (Russian format)
    phones = re.findall(r'\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', text)
    for phone in phones:
        entities.append(EntityItem(type="phone", value=phone, confidence=0.9))
    
    # Date patterns (DD.MM.YYYY or DD/MM/YYYY)
    dates = re.findall(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}', text)
    for date in dates:
        entities.append(EntityItem(type="date", value=date, confidence=0.85))
    
    # Capitalized word sequences (potential names/organizations)
    # For Russian text
    ru_names = re.findall(r'[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+', text)
    for name in ru_names[:5]:  # Limit to avoid noise
        if len(name) > 5:  # Filter short matches
            entities.append(EntityItem(type="person_or_org", value=name, confidence=0.6))
    
    # For English text
    en_names = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', text)
    for name in en_names[:5]:
        if len(name) > 5:
            entities.append(EntityItem(type="person_or_org", value=name, confidence=0.6))
    
    # Hashtags
    hashtags = re.findall(r'#\w+', text)
    for tag in hashtags:
        entities.append(EntityItem(type="hashtag", value=tag, confidence=0.99))
    
    # Mentions
    mentions = re.findall(r'@\w+', text)
    for mention in mentions:
        entities.append(EntityItem(type="mention", value=mention, confidence=0.99))
    
    logger.debug(f"extract_entities: found {len(entities)} entities")
    
    return EntitiesResult(entities=entities)


# ============================================================================
# Combined Processing Result
# ============================================================================


class ProcessingResult(BaseModel):
    """Combined result from all processing tools."""
    text_clean: str
    language: str
    summary: str | None
    topics: list[str]
    entities: list[EntityItem]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for compatibility with v1.2 pipeline."""
        return {
            "text_clean": self.text_clean,
            "language": self.language,
            "summary": self.summary,
            "topics": self.topics,
            "entities": [
                {"type": e.type, "value": e.value, "confidence": e.confidence}
                for e in self.entities
            ],
        }


# ============================================================================
# LLM-Enhanced Function Tools (Phase 2C)
# ============================================================================


class DeepAnalysisResult(BaseModel):
    """Result of deep LLM-based text analysis."""
    text_clean: str = Field(description="Cleaned and normalized text")
    language: str = Field(default="unknown", description="Detected language code")
    summary: str | None = Field(default=None, description="Concise summary of the text")
    topics: list[str] = Field(default_factory=list, description="Main topics discussed")
    entities: list[EntityItem] = Field(default_factory=list, description="Named entities")
    key_points: list[str] = Field(default_factory=list, description="Key points from text")
    sentiment: str | None = Field(default=None, description="Overall sentiment: positive/negative/neutral")


# LLM prompt for deep analysis
DEEP_ANALYSIS_PROMPT = """Analyze the following Telegram message from a laboratory diagnostics channel.

MESSAGE:
{text}

Provide a JSON response with the following structure:
{{
    "text_clean": "cleaned text without noise, normalized formatting",
    "language": "detected language code (ru, en, etc.)",
    "summary": "concise 1-2 sentence summary",
    "topics": ["topic1", "topic2", ...],
    "entities": [
        {{"type": "person|organization|location|product|date|email|url|phone|hashtag|mention", "value": "entity value", "confidence": 0.9}}
    ],
    "key_points": ["key point 1", "key point 2", ...],
    "sentiment": "positive|negative|neutral"
}}

Context: This is a professional channel about laboratory diagnostics, medical testing, and healthcare.
Be thorough but concise. Extract all meaningful information."""


@function_tool
async def analyze_text_deep(
    ctx: RunContextWrapper[AgentContext],
    text: Annotated[str, "The raw text to analyze deeply using LLM"],
) -> DeepAnalysisResult:
    """
    Perform deep analysis of text using LLM.
    
    This tool uses the LLM for semantic analysis when available.
    Falls back to basic pattern matching if LLM is not configured.
    
    Extracts:
    - Clean text
    - Language
    - Summary
    - Topics (semantic, not just keyword matching)
    - Named entities (with context understanding)
    - Key points
    - Sentiment
    """
    if not text or not text.strip():
        return DeepAnalysisResult(text_clean="", language="unknown")
    
    context = ctx.context if ctx.context else AgentContext()
    
    # Try LLM-based analysis if available
    if context.use_llm_tools and context.llm_client is not None:
        try:
            response = await context.llm_client.generate(
                prompt=DEEP_ANALYSIS_PROMPT.format(text=text),
                system_prompt="You are a text analysis expert. Respond only with valid JSON.",
                temperature=0.0,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            
            # Parse JSON response
            data = json.loads(response)
            
            # Convert entities to EntityItem objects
            entities = []
            for e in data.get("entities", []):
                entities.append(EntityItem(
                    type=e.get("type", "unknown"),
                    value=e.get("value", ""),
                    confidence=e.get("confidence", 0.8),
                ))
            
            return DeepAnalysisResult(
                text_clean=data.get("text_clean", text.strip()),
                language=data.get("language", "unknown"),
                summary=data.get("summary"),
                topics=data.get("topics", []),
                entities=entities,
                key_points=data.get("key_points", []),
                sentiment=data.get("sentiment"),
            )
            
        except Exception as e:
            logger.warning(f"LLM analysis failed, falling back to basic: {e}")
    
    # Fallback: use basic tools
    clean_result = _basic_clean_text(text)
    topics_result = _basic_extract_topics(text)
    entities_result = _basic_extract_entities(text)
    
    return DeepAnalysisResult(
        text_clean=clean_result.text_clean,
        language=clean_result.language,
        summary=topics_result.summary,
        topics=topics_result.topics,
        entities=entities_result.entities,
        key_points=[],
        sentiment=None,
    )


@function_tool
async def extract_topics_llm(
    ctx: RunContextWrapper[AgentContext],
    text: Annotated[str, "The text to extract topics from using LLM"],
    max_topics: Annotated[int, "Maximum number of topics to extract"] = 10,
) -> TopicsResult:
    """
    Extract topics using LLM for semantic understanding.
    
    Unlike keyword-based extraction, this tool understands context
    and can identify topics that aren't explicitly mentioned.
    """
    if not text or not text.strip():
        return TopicsResult(topics=[], summary=None)
    
    context = ctx.context if ctx.context else AgentContext()
    
    if context.use_llm_tools and context.llm_client is not None:
        try:
            prompt = f"""Extract the main topics from this text. Maximum {max_topics} topics.

TEXT:
{text}

Return JSON:
{{
    "topics": ["topic1", "topic2", ...],
    "summary": "Brief 1-sentence summary"
}}

Topics should be specific and relevant to laboratory diagnostics/medical field."""

            response = await context.llm_client.generate(
                prompt=prompt,
                system_prompt="You are a topic extraction expert. Respond only with valid JSON.",
                temperature=0.0,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            
            data = json.loads(response)
            return TopicsResult(
                topics=data.get("topics", [])[:max_topics],
                summary=data.get("summary"),
            )
            
        except Exception as e:
            logger.warning(f"LLM topic extraction failed: {e}")
    
    # Fallback to basic
    return _basic_extract_topics(text, max_topics)


@function_tool
async def extract_entities_llm(
    ctx: RunContextWrapper[AgentContext],
    text: Annotated[str, "The text to extract entities from using LLM"],
) -> EntitiesResult:
    """
    Extract named entities using LLM for better accuracy.
    
    Can identify entities that pattern matching would miss,
    and correctly classify ambiguous entities.
    """
    if not text or not text.strip():
        return EntitiesResult(entities=[])
    
    context = ctx.context if ctx.context else AgentContext()
    
    if context.use_llm_tools and context.llm_client is not None:
        try:
            prompt = f"""Extract all named entities from this text.

TEXT:
{text}

Return JSON:
{{
    "entities": [
        {{"type": "person|organization|location|product|date|event|email|url|phone|hashtag|mention", "value": "entity value", "confidence": 0.9}}
    ]
}}

Be thorough. Include all persons, organizations, locations, products, dates, emails, URLs, phones, hashtags, and mentions."""

            response = await context.llm_client.generate(
                prompt=prompt,
                system_prompt="You are an NER expert. Respond only with valid JSON.",
                temperature=0.0,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            
            data = json.loads(response)
            entities = []
            for e in data.get("entities", []):
                entities.append(EntityItem(
                    type=e.get("type", "unknown"),
                    value=e.get("value", ""),
                    confidence=e.get("confidence", 0.8),
                ))
            
            return EntitiesResult(entities=entities)
            
        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}")
    
    # Fallback to basic
    return _basic_extract_entities(text)


# ============================================================================
# Helper functions for fallback
# ============================================================================


def _basic_clean_text(text: str) -> CleanTextResult:
    """Basic text cleaning without LLM."""
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


def _basic_extract_topics(text: str, max_topics: int = 5) -> TopicsResult:
    """Basic topic extraction without LLM."""
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


def _basic_extract_entities(text: str) -> EntitiesResult:
    """Basic entity extraction without LLM."""
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
    
    # Phone patterns (Russian format)
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

