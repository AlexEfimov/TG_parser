"""
Processing Agent for Multi-Agent Architecture.

Phase 3A: Specialized agent for message processing with routing
between simple (fast) and deep (thorough) processing modes.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from agents import Agent, Runner, set_tracing_disabled

from tg_parser.agents.base import (
    AgentCapability,
    AgentInput,
    AgentMetadata,
    AgentOutput,
    AgentType,
    BaseAgent,
)
from tg_parser.agents.tools.text_tools import (
    AgentContext,
    DeepAnalysisResult,
    analyze_text_deep,
    clean_text,
    extract_entities,
    extract_topics,
)

logger = logging.getLogger(__name__)

# Disable tracing by default
set_tracing_disabled(True)


# ============================================================================
# Processing Mode (Router Pattern - Element C)
# ============================================================================


class ProcessingMode:
    """Processing modes for the agent."""
    
    SIMPLE = "simple"   # Fast, pattern-based processing
    DEEP = "deep"       # LLM-enhanced deep analysis
    AUTO = "auto"       # Automatically choose based on content


# ============================================================================
# Processing Agent
# ============================================================================


class ProcessingAgent(BaseAgent[AgentInput, AgentOutput]):
    """
    Specialized agent for message processing.
    
    Implements the A + C hybrid pattern:
    - A: Specialized agent for processing stage
    - C: Internal routing between simple and deep processing
    
    Features:
    - Simple mode: Fast pattern-based processing (no LLM calls)
    - Deep mode: LLM-enhanced analysis for complex content
    - Auto mode: Intelligently chooses based on message complexity
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        default_mode: str = ProcessingMode.AUTO,
        llm_client: Any = None,
        complexity_threshold: int = 200,  # chars threshold for auto mode
    ):
        """
        Initialize the processing agent.
        
        Args:
            model: LLM model to use for deep processing
            provider: LLM provider
            default_mode: Default processing mode (simple/deep/auto)
            llm_client: Optional LLM client for deep analysis
            complexity_threshold: Character count threshold for auto mode
        """
        metadata = AgentMetadata(
            name="ProcessingAgent",
            agent_type=AgentType.PROCESSING,
            version="3.0.0",
            description="Specialized agent for message processing with routing",
            capabilities=[
                AgentCapability.TEXT_PROCESSING,
                AgentCapability.ENTITY_EXTRACTION,
                AgentCapability.SUMMARIZATION,
                AgentCapability.DEEP_ANALYSIS,
            ],
            model=model,
            provider=provider,
        )
        super().__init__(metadata)
        
        self.default_mode = default_mode
        self.llm_client = llm_client
        self.complexity_threshold = complexity_threshold
        
        # OpenAI Agents SDK agents for different modes
        self._simple_agent: Agent | None = None
        self._deep_agent: Agent | None = None
        self._context: AgentContext | None = None
    
    async def initialize(self) -> None:
        """Initialize the agent and create SDK agents."""
        logger.info(f"Initializing {self.name}...")
        
        # Create simple processing agent (fast, pattern-based)
        self._simple_agent = Agent(
            name="SimpleProcessor",
            instructions="""You are a fast text processor for Telegram messages.
            
Use the provided tools to:
1. clean_text - Clean and normalize the raw text
2. extract_topics - Find topics and generate summary
3. extract_entities - Find named entities

Be efficient and thorough. Process the message quickly.""",
            tools=[clean_text, extract_topics, extract_entities],
            model=self._metadata.model,
        )
        
        # Create deep processing agent (LLM-enhanced)
        self._deep_agent = Agent[AgentContext](
            name="DeepProcessor",
            instructions="""You are a deep text analyzer for Telegram messages.

Use the analyze_text_deep tool for comprehensive analysis:
- Clean and normalize the text
- Detect language
- Generate detailed summary
- Extract semantic topics
- Extract named entities with context
- Identify key points
- Analyze sentiment

Provide thorough and accurate results.""",
            tools=[analyze_text_deep],
            model=self._metadata.model,
        )
        
        # Create context for LLM-enhanced tools
        self._context = AgentContext(
            llm_client=self.llm_client,
            use_llm_tools=True,
            provider=self._metadata.provider,
            model=self._metadata.model,
        )
        
        self._is_initialized = True
        logger.info(f"{self.name} initialized successfully")
    
    async def shutdown(self) -> None:
        """Shutdown the agent."""
        logger.info(f"Shutting down {self.name}...")
        self._simple_agent = None
        self._deep_agent = None
        self._context = None
        self._is_initialized = False
        logger.info(f"{self.name} shut down")
    
    async def process(self, input_data: AgentInput) -> AgentOutput:
        """
        Process input data.
        
        Args:
            input_data: Input containing text to process
            
        Returns:
            AgentOutput with processing results
        """
        start_time = datetime.now(UTC)
        
        try:
            # Extract text from input
            text = input_data.data.get("text", "")
            if not text:
                return AgentOutput(
                    task_id=input_data.task_id,
                    success=False,
                    error="No text provided in input data",
                )
            
            # Determine processing mode
            mode = input_data.options.get("mode", self.default_mode)
            if mode == ProcessingMode.AUTO:
                mode = self._select_mode(text)
            
            logger.info(f"Processing with mode={mode}, text_length={len(text)}")
            
            # Process based on mode
            if mode == ProcessingMode.SIMPLE:
                result = await self._process_simple(text)
            else:
                result = await self._process_deep(text)
            
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=True,
                result=result,
                metadata={
                    "mode": mode,
                    "agent": self.name,
                    "model": self._metadata.model,
                    "provider": self._metadata.provider,
                },
                processing_time_ms=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Processing failed: {e}", exc_info=True)
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=False,
                error=str(e),
                processing_time_ms=processing_time,
            )
    
    def _select_mode(self, text: str) -> str:
        """
        Automatically select processing mode based on text complexity.
        
        Simple heuristics:
        - Short texts (< threshold) → simple mode
        - Long or complex texts → deep mode
        
        Args:
            text: Text to analyze
            
        Returns:
            Processing mode
        """
        # Length check
        if len(text) < self.complexity_threshold:
            return ProcessingMode.SIMPLE
        
        # Check for complexity indicators
        complexity_indicators = [
            len(text.split()) > 50,  # Many words
            text.count("\n") > 5,     # Multiple paragraphs
            any(c in text for c in ["@", "#", "http"]),  # Contains mentions/hashtags/links
        ]
        
        if sum(complexity_indicators) >= 2:
            return ProcessingMode.DEEP
        
        return ProcessingMode.SIMPLE
    
    async def _process_simple(self, text: str) -> dict[str, Any]:
        """
        Process text using simple (fast) mode.
        
        Uses pattern-based tools without LLM calls.
        
        Args:
            text: Text to process
            
        Returns:
            Processing results
        """
        if not self._simple_agent:
            raise RuntimeError("Agent not initialized")
        
        result = await Runner.run(
            self._simple_agent,
            input=f"Process this message:\n\n{text}",
        )
        
        # Extract results from tool outputs
        return self._extract_results(result)
    
    async def _process_deep(self, text: str) -> dict[str, Any]:
        """
        Process text using deep (LLM-enhanced) mode.
        
        Uses LLM for semantic analysis.
        
        Args:
            text: Text to process
            
        Returns:
            Processing results
        """
        if not self._deep_agent:
            raise RuntimeError("Agent not initialized")
        
        result = await Runner.run(
            self._deep_agent,
            input=f"Analyze this message deeply:\n\n{text}",
            context=self._context,
        )
        
        # Extract results from tool outputs
        return self._extract_results(result)
    
    def _extract_results(self, result: Any) -> dict[str, Any]:
        """
        Extract structured results from agent run result.
        
        Args:
            result: Result from Runner.run()
            
        Returns:
            Structured dictionary with results
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
        
        # Process tool outputs
        for item in result.new_items:
            if hasattr(item, "output"):
                output = item.output
                
                if isinstance(output, DeepAnalysisResult):
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
                elif hasattr(output, "text_clean"):
                    data["text_clean"] = output.text_clean
                    if hasattr(output, "language"):
                        data["language"] = output.language
                elif hasattr(output, "topics"):
                    data["topics"] = output.topics
                    if hasattr(output, "summary"):
                        data["summary"] = output.summary
                elif hasattr(output, "entities"):
                    data["entities"] = [
                        {"type": e.type, "value": e.value, "confidence": e.confidence}
                        for e in output.entities
                    ]
        
        return data
    
    # =========================================================================
    # Convenience Methods
    # =========================================================================
    
    async def process_text(
        self,
        text: str,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """
        Convenience method to process text directly.
        
        Args:
            text: Text to process
            mode: Processing mode (optional, uses default if not provided)
            
        Returns:
            Processing results
        """
        from uuid import uuid4
        
        input_data = AgentInput(
            task_id=str(uuid4()),
            data={"text": text},
            options={"mode": mode} if mode else {},
        )
        
        output = await self.process(input_data)
        
        if not output.success:
            raise RuntimeError(output.error)
        
        return output.result

