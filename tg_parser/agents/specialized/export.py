"""
Export Agent for Multi-Agent Architecture.

Phase 3A: Specialized agent for data export and formatting.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
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


class ExportFormat:
    """Supported export formats."""
    
    NDJSON = "ndjson"
    JSON = "json"
    TOPICS = "topics"


class ExportAgent(BaseAgent[AgentInput, AgentOutput]):
    """
    Specialized agent for data export.
    
    Handles conversion of processed documents to various output formats
    suitable for RAG systems and knowledge bases.
    """
    
    def __init__(
        self,
        output_dir: str | Path | None = None,
        default_format: str = ExportFormat.NDJSON,
    ):
        """
        Initialize the export agent.
        
        Args:
            output_dir: Directory for output files
            default_format: Default export format
        """
        metadata = AgentMetadata(
            name="ExportAgent",
            agent_type=AgentType.EXPORT,
            version="3.0.0",
            description="Specialized agent for data export and formatting",
            capabilities=[AgentCapability.EXPORT],
        )
        super().__init__(metadata)
        
        self.output_dir = Path(output_dir) if output_dir else None
        self.default_format = default_format
    
    async def initialize(self) -> None:
        """Initialize the agent."""
        logger.info(f"Initializing {self.name}...")
        
        # Ensure output directory exists
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._is_initialized = True
        logger.info(f"{self.name} initialized successfully")
    
    async def shutdown(self) -> None:
        """Shutdown the agent."""
        logger.info(f"Shutting down {self.name}...")
        self._is_initialized = False
        logger.info(f"{self.name} shut down")
    
    async def process(self, input_data: AgentInput) -> AgentOutput:
        """
        Process export request.
        
        Expected input format:
        {
            "documents": [...],  # Documents to export
            "format": "ndjson",  # Export format
            "filename": "...",   # Optional filename
        }
        
        Args:
            input_data: Input containing documents and export options
            
        Returns:
            AgentOutput with export results
        """
        start_time = datetime.now(UTC)
        
        try:
            documents = input_data.data.get("documents", [])
            export_format = input_data.options.get("format", self.default_format)
            filename = input_data.options.get("filename")
            
            if not documents:
                return AgentOutput(
                    task_id=input_data.task_id,
                    success=False,
                    error="No documents provided for export",
                )
            
            logger.info(f"Exporting {len(documents)} documents as {export_format}")
            
            # Perform export
            if export_format == ExportFormat.NDJSON:
                result = await self._export_ndjson(documents, filename)
            elif export_format == ExportFormat.JSON:
                result = await self._export_json(documents, filename)
            elif export_format == ExportFormat.TOPICS:
                topics = input_data.data.get("topics", [])
                result = await self._export_topics(topics, filename)
            else:
                return AgentOutput(
                    task_id=input_data.task_id,
                    success=False,
                    error=f"Unknown export format: {export_format}",
                )
            
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=True,
                result=result,
                metadata={
                    "agent": self.name,
                    "format": export_format,
                    "document_count": len(documents),
                },
                processing_time_ms=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Export failed: {e}", exc_info=True)
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=False,
                error=str(e),
                processing_time_ms=processing_time,
            )
    
    async def _export_ndjson(
        self,
        documents: list[dict[str, Any]],
        filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Export documents as NDJSON (one JSON object per line).
        
        Args:
            documents: Documents to export
            filename: Optional filename
            
        Returns:
            Export result with content or file path
        """
        lines = []
        for doc in documents:
            # Convert to KB entry format
            entry = self._to_kb_entry(doc)
            lines.append(json.dumps(entry, ensure_ascii=False))
        
        content = "\n".join(lines)
        
        result = {
            "format": "ndjson",
            "document_count": len(documents),
            "content_size_bytes": len(content.encode("utf-8")),
        }
        
        if self.output_dir and filename:
            filepath = self.output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            result["filepath"] = str(filepath)
            logger.info(f"Exported to {filepath}")
        else:
            result["content"] = content
        
        return result
    
    async def _export_json(
        self,
        documents: list[dict[str, Any]],
        filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Export documents as JSON array.
        
        Args:
            documents: Documents to export
            filename: Optional filename
            
        Returns:
            Export result with content or file path
        """
        entries = [self._to_kb_entry(doc) for doc in documents]
        content = json.dumps(entries, ensure_ascii=False, indent=2)
        
        result = {
            "format": "json",
            "document_count": len(documents),
            "content_size_bytes": len(content.encode("utf-8")),
        }
        
        if self.output_dir and filename:
            filepath = self.output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            result["filepath"] = str(filepath)
            logger.info(f"Exported to {filepath}")
        else:
            result["content"] = content
        
        return result
    
    async def _export_topics(
        self,
        topics: list[dict[str, Any]],
        filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Export topic clusters.
        
        Args:
            topics: Topic clusters to export
            filename: Optional filename
            
        Returns:
            Export result with content or file path
        """
        content = json.dumps(topics, ensure_ascii=False, indent=2)
        
        result = {
            "format": "topics",
            "topic_count": len(topics),
            "content_size_bytes": len(content.encode("utf-8")),
        }
        
        if self.output_dir and filename:
            filepath = self.output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            result["filepath"] = str(filepath)
            logger.info(f"Exported topics to {filepath}")
        else:
            result["content"] = content
        
        return result
    
    def _to_kb_entry(self, doc: dict[str, Any]) -> dict[str, Any]:
        """
        Convert document to knowledge base entry format.
        
        Args:
            doc: Document dict
            
        Returns:
            KB entry dict
        """
        return {
            "id": doc.get("id") or doc.get("source_ref"),
            "source_ref": doc.get("source_ref"),
            "text": doc.get("text_clean", ""),
            "summary": doc.get("summary"),
            "topics": doc.get("topics", []),
            "entities": doc.get("entities", []),
            "language": doc.get("language", "unknown"),
            "metadata": doc.get("metadata", {}),
        }
    
    # =========================================================================
    # Convenience Methods
    # =========================================================================
    
    async def export_documents(
        self,
        documents: list[Any],
        format: str = ExportFormat.NDJSON,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Convenience method to export documents.
        
        Args:
            documents: Documents to export (dicts or ProcessedDocument)
            format: Export format
            filename: Optional filename
            
        Returns:
            Export results
        """
        from uuid import uuid4
        
        # Convert ProcessedDocument to dict if needed
        doc_dicts = []
        for doc in documents:
            if hasattr(doc, "model_dump"):
                doc_dicts.append(doc.model_dump())
            elif hasattr(doc, "__dict__"):
                doc_dicts.append(doc.__dict__)
            else:
                doc_dicts.append(doc)
        
        input_data = AgentInput(
            task_id=str(uuid4()),
            data={"documents": doc_dicts},
            options={"format": format, "filename": filename},
        )
        
        output = await self.process(input_data)
        
        if not output.success:
            raise RuntimeError(output.error)
        
        return output.result

