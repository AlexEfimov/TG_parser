"""
TG Processing Agent using OpenAI Agents SDK.

Phase 2B: Proof of Concept for agent-based message processing.
Phase 2C: Added LLM-enhanced tools and multi-provider support.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from agents import Agent, Runner, function_tool, set_tracing_disabled
from pydantic import BaseModel, Field

from tg_parser.config import settings
from tg_parser.domain.ids import make_processed_document_id
from tg_parser.domain.models import Entity, ProcessedDocument, RawTelegramMessage

from .tools.text_tools import (
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
    # LLM-enhanced tools
    analyze_text_deep,
    extract_entities_llm,
    extract_topics_llm,
)

logger = logging.getLogger(__name__)

# Disable tracing by default for PoC
set_tracing_disabled(True)


# ============================================================================
# Agent Output Schema
# ============================================================================


class AgentProcessingOutput(BaseModel):
    """Structured output from the processing agent."""
    text_clean: str = Field(description="Cleaned and normalized text")
    language: str = Field(default="unknown", description="Detected language code")
    summary: str | None = Field(default=None, description="Brief summary")
    topics: list[str] = Field(default_factory=list, description="Extracted topics")
    entities: list[dict[str, Any]] = Field(default_factory=list, description="Extracted entities")


# ============================================================================
# TG Processing Agent
# ============================================================================


def create_processing_agent() -> Agent:
    """
    Create TGProcessingAgent with text processing tools.
    
    The agent uses three tools:
    - clean_text: Clean and normalize raw text
    - extract_topics: Extract topics and generate summary
    - extract_entities: Extract named entities
    
    Returns:
        Configured Agent instance
    """
    agent = Agent(
        name="TGProcessingAgent",
        instructions="""You are a Telegram message processing agent for a laboratory diagnostics channel.

Your task is to process raw Telegram messages and extract structured information.

For each message, you MUST use ALL THREE tools in order:
1. First, use clean_text to clean and normalize the raw text
2. Then, use extract_topics on the cleaned text to find topics and summary
3. Finally, use extract_entities on the cleaned text to find named entities

After using all tools, provide a final summary combining the results.

The channel content is about laboratory diagnostics, medical testing, and healthcare.
Messages are typically in Russian but may contain English terms.

Be thorough and accurate. Extract all relevant information.""",
        tools=[clean_text, extract_topics, extract_entities],
        model="gpt-4o-mini",  # Cost-effective model for PoC
    )
    
    return agent


# Global agent instance (lazy initialization)
_processing_agent: Agent | None = None


def get_processing_agent() -> Agent:
    """Get or create the global processing agent."""
    global _processing_agent
    if _processing_agent is None:
        _processing_agent = create_processing_agent()
    return _processing_agent


# ============================================================================
# Processing Function
# ============================================================================


async def process_message_with_agent(
    message: RawTelegramMessage,
    agent: Agent | None = None,
    context: AgentContext | None = None,
) -> ProcessedDocument:
    """
    Process a single message using the TGProcessingAgent.
    
    Args:
        message: RawTelegramMessage to process
        agent: Optional agent instance (uses global if not provided)
        context: Optional AgentContext for LLM-enhanced tools
        
    Returns:
        ProcessedDocument with extracted information
    """
    if agent is None:
        agent = get_processing_agent()
    
    # Default context if not provided
    if context is None:
        context = AgentContext()
    
    logger.info(f"Processing message with agent: {message.source_ref}")
    
    # Determine prompt based on available tools
    if context.use_llm_tools:
        input_prompt = f"""Process this Telegram message using deep analysis:

---
{message.text}
---

Use the analyze_text_deep tool for comprehensive analysis."""
    else:
        input_prompt = f"""Process this Telegram message:

---
{message.text}
---

Use all three tools (clean_text, extract_topics, extract_entities) to extract structured information."""

    try:
        result = await Runner.run(
            agent, 
            input=input_prompt,
            context=context,
        )
        
        # Parse the agent's final output and tool results
        processed_data = _extract_processing_data(result)
        
        # Create ProcessedDocument
        doc = _create_processed_document(message, processed_data, context)
        
        logger.info(f"Agent processing complete: {message.source_ref}")
        return doc
        
    except Exception as e:
        logger.error(f"Agent processing failed for {message.source_ref}: {e}", exc_info=True)
        raise


def _extract_processing_data(result: Any) -> dict:
    """
    Extract structured data from agent run result.
    
    Combines tool outputs into a single processing result.
    Handles both basic tools and LLM-enhanced DeepAnalysisResult.
    """
    data = {
        "text_clean": "",
        "language": "unknown",
        "summary": None,
        "topics": [],
        "entities": [],
        "key_points": [],
        "sentiment": None,
    }
    
    # Extract data from new_items (tool call outputs)
    for item in result.new_items:
        if hasattr(item, "output"):
            output = item.output
            
            # Parse tool outputs
            if isinstance(output, DeepAnalysisResult):
                # LLM-enhanced deep analysis result
                data["text_clean"] = output.text_clean
                data["language"] = output.language
                data["summary"] = output.summary
                data["topics"] = output.topics
                data["entities"] = [
                    {"type": e.type, "value": e.value, "confidence": e.confidence}
                    for e in output.entities
                ]
                data["key_points"] = output.key_points
                data["sentiment"] = output.sentiment
            elif isinstance(output, CleanTextResult):
                data["text_clean"] = output.text_clean
                data["language"] = output.language
            elif isinstance(output, TopicsResult):
                data["topics"] = output.topics
                data["summary"] = output.summary
            elif isinstance(output, EntitiesResult):
                data["entities"] = [
                    {"type": e.type, "value": e.value, "confidence": e.confidence}
                    for e in output.entities
                ]
            elif isinstance(output, str):
                # Try to parse as JSON if string
                try:
                    parsed = json.loads(output)
                    if "text_clean" in parsed:
                        data["text_clean"] = parsed.get("text_clean", "")
                        data["language"] = parsed.get("language", "unknown")
                    if "topics" in parsed:
                        data["topics"] = parsed.get("topics", [])
                        data["summary"] = parsed.get("summary")
                    if "entities" in parsed:
                        data["entities"] = parsed.get("entities", [])
                    if "key_points" in parsed:
                        data["key_points"] = parsed.get("key_points", [])
                    if "sentiment" in parsed:
                        data["sentiment"] = parsed.get("sentiment")
                except (json.JSONDecodeError, TypeError):
                    pass
    
    # Fallback: parse from final_output if tools didn't provide data
    if not data["text_clean"] and result.final_output:
        try:
            if isinstance(result.final_output, str):
                # Try to extract text_clean from final output
                parsed = json.loads(result.final_output)
                if "text_clean" in parsed:
                    data.update(parsed)
        except (json.JSONDecodeError, TypeError):
            # Use final output as cleaned text if all else fails
            data["text_clean"] = str(result.final_output)[:500]
    
    return data


def _create_processed_document(
    message: RawTelegramMessage,
    data: dict,
    context: AgentContext | None = None,
) -> ProcessedDocument:
    """Create ProcessedDocument from extracted data."""
    
    # Parse entities
    entities = [
        Entity(
            type=e.get("type", "unknown"),
            value=e.get("value", ""),
            confidence=e.get("confidence"),
        )
        for e in data.get("entities", [])
        if e.get("value")
    ]
    
    # Build metadata
    ctx = context or AgentContext()
    metadata = {
        "pipeline_version": "agents-v2.0" if ctx.use_llm_tools else "agents-poc-v0.1",
        "model_id": ctx.model,
        "provider": ctx.provider,
        "prompt_id": "agent-deep-analysis-v1" if ctx.use_llm_tools else "agent-processing-v1",
        "agent_name": "TGProcessingAgent",
        "use_llm_tools": ctx.use_llm_tools,
    }
    
    # Add enhanced data if available
    if data.get("key_points"):
        metadata["key_points"] = data["key_points"]
    if data.get("sentiment"):
        metadata["sentiment"] = data["sentiment"]
    
    # Create document
    doc = ProcessedDocument(
        id=make_processed_document_id(message.source_ref),
        source_ref=message.source_ref,
        source_message_id=message.id,
        channel_id=message.channel_id,
        processed_at=datetime.now(UTC),
        text_clean=data.get("text_clean", message.text),
        summary=data.get("summary"),
        topics=data.get("topics", []),
        entities=entities,
        language=data.get("language", "unknown"),
        metadata=metadata,
    )
    
    return doc


# ============================================================================
# Batch Processing
# ============================================================================


async def process_batch_with_agent(
    messages: list[RawTelegramMessage],
    concurrency: int = 3,
    agent: Agent | None = None,
    context: AgentContext | None = None,
) -> list[ProcessedDocument]:
    """
    Process multiple messages using the agent.
    
    Args:
        messages: List of messages to process
        concurrency: Max concurrent processing tasks
        agent: Optional agent instance
        context: Optional AgentContext for LLM-enhanced tools
        
    Returns:
        List of ProcessedDocuments
    """
    if agent is None:
        agent = get_processing_agent()
    
    if context is None:
        context = AgentContext()
    
    semaphore = asyncio.Semaphore(concurrency)
    results: list[ProcessedDocument] = []
    
    async def process_one(msg: RawTelegramMessage) -> ProcessedDocument | None:
        async with semaphore:
            try:
                return await process_message_with_agent(msg, agent, context)
            except Exception as e:
                logger.error(f"Failed to process {msg.source_ref}: {e}")
                return None
    
    # Process all messages concurrently
    tasks = [process_one(msg) for msg in messages]
    completed = await asyncio.gather(*tasks)
    
    # Filter out failures
    results = [r for r in completed if r is not None]
    
    logger.info(f"Batch processing complete: {len(results)}/{len(messages)} successful")
    
    return results


# ============================================================================
# Convenience wrapper
# ============================================================================


class TGProcessingAgent:
    """
    Wrapper class for TGProcessingAgent functionality.
    
    Provides object-oriented interface for agent-based processing.
    Supports both basic and LLM-enhanced tools.
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        use_llm_tools: bool = False,
        llm_client: Any = None,
    ):
        """
        Initialize the processing agent.
        
        Args:
            model: Model to use (e.g., "gpt-4o-mini")
            provider: LLM provider ("openai", "anthropic", "gemini", "ollama")
            use_llm_tools: Enable LLM-enhanced tools for deep analysis
            llm_client: Optional LLMClient instance for enhanced tools
        """
        self.model = model
        self.provider = provider
        self.use_llm_tools = use_llm_tools
        self.llm_client = llm_client
        self._agent: Agent | None = None
        self._context: AgentContext | None = None
    
    @property
    def context(self) -> AgentContext:
        """Get or create the agent context."""
        if self._context is None:
            self._context = AgentContext(
                llm_client=self.llm_client,
                use_llm_tools=self.use_llm_tools,
                provider=self.provider,
                model=self.model,
            )
        return self._context
    
    @property
    def agent(self) -> Agent:
        """Get or create the agent instance."""
        if self._agent is None:
            # Choose tools based on configuration
            if self.use_llm_tools:
                tools = [analyze_text_deep]
                instructions = """You are a Telegram message processing agent with LLM-enhanced analysis.

Your task is to process raw messages and extract structured information.

Use the analyze_text_deep tool to perform comprehensive analysis:
- Clean and normalize the text
- Detect language
- Generate summary
- Extract topics (semantic understanding)
- Extract named entities (with context)
- Identify key points
- Analyze sentiment

Provide thorough and accurate results."""
            else:
                tools = [clean_text, extract_topics, extract_entities]
                instructions = """You are a Telegram message processing agent.

Your task is to process raw messages and extract structured information.

For each message, use the provided tools:
1. clean_text - to clean and normalize the raw text
2. extract_topics - to find topics and generate summary
3. extract_entities - to find named entities

Use all tools and provide a comprehensive result."""
            
            self._agent = Agent[AgentContext](
                name="TGProcessingAgent",
                instructions=instructions,
                tools=tools,
                model=self.model,
            )
        return self._agent
    
    async def process(self, message: RawTelegramMessage) -> ProcessedDocument:
        """Process a single message."""
        return await process_message_with_agent(
            message, 
            self.agent, 
            context=self.context,
        )
    
    async def process_batch(
        self,
        messages: list[RawTelegramMessage],
        concurrency: int = 3,
    ) -> list[ProcessedDocument]:
        """Process multiple messages."""
        return await process_batch_with_agent(
            messages, 
            concurrency, 
            self.agent,
            context=self.context,
        )

