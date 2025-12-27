"""
Pipeline tool for Hybrid Agent mode.

Phase 2E: Wraps v1.2 ProcessingPipeline as an agent tool.
The agent can call this tool when it needs deep, reliable processing.
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from agents import RunContextWrapper, function_tool
from pydantic import BaseModel, Field

from .text_tools import AgentContext

if TYPE_CHECKING:
    from tg_parser.processing.pipeline import ProcessingPipelineImpl

logger = logging.getLogger(__name__)


class PipelineResult(BaseModel):
    """Result from v1.2 pipeline processing."""
    
    text_clean: str = Field(description="Cleaned and normalized text")
    summary: str | None = Field(default=None, description="Brief summary of the text")
    topics: list[str] = Field(default_factory=list, description="Extracted topics")
    entities: list[dict[str, Any]] = Field(
        default_factory=list, 
        description="Extracted entities with type, value, confidence"
    )
    language: str = Field(default="unknown", description="Detected language code")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Processing metadata")


async def _create_pipeline_on_demand(context: AgentContext) -> "ProcessingPipelineImpl | None":
    """
    Create a pipeline instance on demand when not provided in context.
    
    This is a fallback for when the pipeline isn't pre-configured.
    Returns None if creation fails.
    """
    try:
        from tg_parser.processing.pipeline import create_processing_pipeline
        from tg_parser.storage.sqlite.processed_document_repo import (
            InMemoryProcessedDocumentRepo,
        )
        
        # Use an in-memory repo for on-demand pipeline
        # (results won't be persisted unless explicitly saved)
        in_memory_repo = InMemoryProcessedDocumentRepo()
        
        # Determine API key based on provider
        provider = context.provider
        api_key = None
        
        if provider == "openai":
            import os
            api_key = os.getenv("OPENAI_API_KEY")
        elif provider == "anthropic":
            import os
            api_key = os.getenv("ANTHROPIC_API_KEY")
        elif provider == "gemini":
            import os
            api_key = os.getenv("GEMINI_API_KEY")
        
        if provider != "ollama" and not api_key:
            logger.warning(f"No API key for {provider}, cannot create pipeline on demand")
            return None
        
        pipeline = create_processing_pipeline(
            provider=provider,
            api_key=api_key,
            model=context.model,
            processed_doc_repo=in_memory_repo,
        )
        
        logger.info(f"Created on-demand pipeline with provider={provider}, model={context.model}")
        return pipeline
        
    except Exception as e:
        logger.error(f"Failed to create pipeline on demand: {e}")
        return None


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
    - Basic tools are insufficient for the message complexity
    - Text is long or contains technical/domain-specific content
    
    This tool uses the full LLM pipeline with:
    - Configurable prompts (YAML-based)
    - Retry mechanism (3 attempts with exponential backoff)
    - Multi-LLM support (OpenAI, Anthropic, Gemini, Ollama)
    
    Returns structured processing result with cleaned text, summary,
    topics, entities, and language detection.
    """
    if not text or not text.strip():
        logger.warning("process_with_pipeline called with empty text")
        return PipelineResult(
            text_clean="",
            summary=None,
            topics=[],
            entities=[],
            language="unknown",
            metadata={"error": "empty_input"},
        )
    
    context = ctx.context if ctx.context else AgentContext()
    
    # Try to get pipeline from context.extra first
    pipeline = context.extra.get("pipeline") if context.extra else None
    
    # Fallback: create pipeline on demand
    if pipeline is None:
        logger.info("No pipeline in context, creating on demand")
        pipeline = await _create_pipeline_on_demand(context)
    
    if pipeline is None:
        # Final fallback: use basic processing
        logger.warning("Could not create pipeline, falling back to basic processing")
        return _fallback_basic_processing(text)
    
    try:
        # Import models here to avoid circular imports
        from tg_parser.domain.models import MessageType, RawTelegramMessage
        
        # Create a RawTelegramMessage for pipeline processing
        source_ref = f"tg:{channel_id}:agent_request:{message_id or uuid4().hex[:8]}"
        
        message = RawTelegramMessage(
            id=str(message_id) if message_id else str(uuid4()),
            source_ref=source_ref,
            channel_id=channel_id,
            message_type=MessageType.POST,
            text=text,
            date=datetime.now(UTC),
            raw_payload={"agent_request": True},
        )
        
        # Process through pipeline (force=True to always process)
        doc = await pipeline.process_message(message, force=True)
        
        logger.info(f"Pipeline processed message: {source_ref}")
        
        return PipelineResult(
            text_clean=doc.text_clean,
            summary=doc.summary,
            topics=doc.topics,
            entities=[
                {
                    "type": e.type,
                    "value": e.value,
                    "confidence": e.confidence,
                }
                for e in doc.entities
            ],
            language=doc.language or "unknown",
            metadata={
                "source_ref": doc.source_ref,
                "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
                "pipeline_version": doc.metadata.get("pipeline_version") if doc.metadata else None,
                "model_id": doc.metadata.get("model_id") if doc.metadata else None,
            },
        )
        
    except Exception as e:
        logger.error(f"Pipeline processing failed: {e}", exc_info=True)
        # Return error result with fallback processing
        fallback = _fallback_basic_processing(text)
        fallback.metadata["pipeline_error"] = str(e)
        return fallback


def _fallback_basic_processing(text: str) -> PipelineResult:
    """
    Fallback processing when pipeline is unavailable.
    
    Uses basic pattern matching similar to agent tools.
    """
    import re
    
    # Basic cleaning
    cleaned = text.strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'Forwarded from.*?\n', '', cleaned)
    
    # Language detection
    cyrillic_count = len(re.findall(r'[а-яёА-ЯЁ]', cleaned))
    latin_count = len(re.findall(r'[a-zA-Z]', cleaned))
    
    if cyrillic_count > latin_count:
        language = "ru"
    elif latin_count > 0:
        language = "en"
    else:
        language = "unknown"
    
    # Basic entity extraction
    entities = []
    
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    for email in emails:
        entities.append({"type": "email", "value": email, "confidence": 0.95})
    
    urls = re.findall(r'https?://[^\s]+', text)
    for url in urls:
        entities.append({"type": "url", "value": url, "confidence": 0.95})
    
    hashtags = re.findall(r'#\w+', text)
    for tag in hashtags:
        entities.append({"type": "hashtag", "value": tag, "confidence": 0.99})
    
    mentions = re.findall(r'@\w+', text)
    for mention in mentions:
        entities.append({"type": "mention", "value": mention, "confidence": 0.99})
    
    # Basic summary
    sentences = re.split(r'[.!?]', text.strip())
    summary = None
    if sentences and len(sentences[0]) > 10:
        first_sentence = sentences[0].strip()
        summary = first_sentence[:150] if len(first_sentence) <= 150 else first_sentence[:147] + "..."
    
    return PipelineResult(
        text_clean=cleaned,
        summary=summary,
        topics=[],  # Can't extract topics without LLM
        entities=entities,
        language=language,
        metadata={"fallback": True, "reason": "pipeline_unavailable"},
    )


class InMemoryProcessedDocumentRepo:
    """
    Simple in-memory repository for on-demand pipeline processing.
    
    Used when pipeline is created on-the-fly without database access.
    """
    
    def __init__(self):
        self._documents: dict[str, Any] = {}
    
    async def exists(self, source_ref: str) -> bool:
        return source_ref in self._documents
    
    async def get_by_source_ref(self, source_ref: str) -> Any:
        return self._documents.get(source_ref)
    
    async def save(self, doc: Any) -> None:
        self._documents[doc.source_ref] = doc
    
    async def upsert(self, doc: Any) -> None:
        self._documents[doc.source_ref] = doc

