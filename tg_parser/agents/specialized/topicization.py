"""
Topicization Agent for Multi-Agent Architecture.

Phase 3A: Specialized agent for semantic topic clustering.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from tg_parser.agents.base import (
    AgentCapability,
    AgentInput,
    AgentMetadata,
    AgentOutput,
    AgentType,
    BaseAgent,
)

logger = logging.getLogger(__name__)


class TopicizationAgent(BaseAgent[AgentInput, AgentOutput]):
    """
    Specialized agent for topicization (semantic clustering).
    
    Takes processed documents and groups them into semantic topics.
    Integrates with existing topicization pipeline.
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        min_cluster_size: int = 2,
        max_topics: int = 50,
    ):
        """
        Initialize the topicization agent.
        
        Args:
            model: LLM model for semantic analysis
            provider: LLM provider
            min_cluster_size: Minimum documents per topic
            max_topics: Maximum number of topics to create
        """
        metadata = AgentMetadata(
            name="TopicizationAgent",
            agent_type=AgentType.TOPICIZATION,
            version="3.0.0",
            description="Specialized agent for semantic topic clustering",
            capabilities=[
                AgentCapability.TOPIC_EXTRACTION,
                AgentCapability.TOPICIZATION,
            ],
            model=model,
            provider=provider,
        )
        super().__init__(metadata)
        
        self.min_cluster_size = min_cluster_size
        self.max_topics = max_topics
        self._topicization_pipeline: Any = None
    
    async def initialize(self) -> None:
        """Initialize the agent."""
        logger.info(f"Initializing {self.name}...")
        
        # Lazy import to avoid circular dependencies
        try:
            from tg_parser.processing.topicization import TopicizationPipelineImpl
            self._topicization_pipeline = TopicizationPipelineImpl
        except ImportError:
            logger.warning("TopicizationPipelineImpl not available, using basic mode")
        
        self._is_initialized = True
        logger.info(f"{self.name} initialized successfully")
    
    async def shutdown(self) -> None:
        """Shutdown the agent."""
        logger.info(f"Shutting down {self.name}...")
        self._topicization_pipeline = None
        self._is_initialized = False
        logger.info(f"{self.name} shut down")
    
    async def process(self, input_data: AgentInput) -> AgentOutput:
        """
        Process input data for topicization.
        
        Expected input format:
        {
            "documents": [
                {"source_ref": "...", "topics": [...], "text_clean": "..."},
                ...
            ]
        }
        
        Args:
            input_data: Input containing documents to cluster
            
        Returns:
            AgentOutput with topic clusters
        """
        start_time = datetime.now(UTC)
        
        try:
            documents = input_data.data.get("documents", [])
            
            if not documents:
                return AgentOutput(
                    task_id=input_data.task_id,
                    success=False,
                    error="No documents provided for topicization",
                )
            
            logger.info(f"Topicizing {len(documents)} documents")
            
            # Perform topicization
            topics = await self._cluster_documents(documents)
            
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=True,
                result={
                    "topics": topics,
                    "total_documents": len(documents),
                    "total_topics": len(topics),
                },
                metadata={
                    "agent": self.name,
                    "min_cluster_size": self.min_cluster_size,
                    "max_topics": self.max_topics,
                },
                processing_time_ms=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Topicization failed: {e}", exc_info=True)
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=False,
                error=str(e),
                processing_time_ms=processing_time,
            )
    
    async def _cluster_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Cluster documents into semantic topics.
        
        Basic implementation using topic overlap.
        For production, integrates with full topicization pipeline.
        
        Args:
            documents: List of processed documents
            
        Returns:
            List of topic clusters
        """
        # Group documents by their topics
        topic_to_docs: dict[str, list[dict[str, Any]]] = {}
        
        for doc in documents:
            doc_topics = doc.get("topics", [])
            for topic in doc_topics:
                if topic not in topic_to_docs:
                    topic_to_docs[topic] = []
                topic_to_docs[topic].append(doc)
        
        # Filter by minimum cluster size
        clusters = []
        for topic_name, docs in topic_to_docs.items():
            if len(docs) >= self.min_cluster_size:
                clusters.append({
                    "topic": topic_name,
                    "document_count": len(docs),
                    "documents": [d.get("source_ref") for d in docs],
                    "sample_texts": [
                        d.get("text_clean", "")[:100] for d in docs[:3]
                    ],
                })
        
        # Sort by document count and limit
        clusters.sort(key=lambda x: x["document_count"], reverse=True)
        clusters = clusters[:self.max_topics]
        
        logger.info(f"Created {len(clusters)} topic clusters")
        return clusters
    
    async def cluster_processed_documents(
        self,
        documents: list[Any],
    ) -> list[dict[str, Any]]:
        """
        Convenience method to cluster ProcessedDocument objects.
        
        Args:
            documents: List of ProcessedDocument instances
            
        Returns:
            List of topic clusters
        """
        from uuid import uuid4
        
        # Convert ProcessedDocument to dict format
        doc_dicts = []
        for doc in documents:
            doc_dicts.append({
                "source_ref": doc.source_ref if hasattr(doc, "source_ref") else str(doc),
                "topics": doc.topics if hasattr(doc, "topics") else [],
                "text_clean": doc.text_clean if hasattr(doc, "text_clean") else "",
            })
        
        input_data = AgentInput(
            task_id=str(uuid4()),
            data={"documents": doc_dicts},
        )
        
        output = await self.process(input_data)
        
        if not output.success:
            raise RuntimeError(output.error)
        
        return output.result.get("topics", [])

