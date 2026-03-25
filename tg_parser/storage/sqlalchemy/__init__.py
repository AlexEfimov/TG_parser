"""
SQLAlchemy repository implementations for TG_parser.

PostgreSQL via SQLAlchemy 2.x async.
"""

from .agent_state_repo import SAAgentStateRepo
from .agent_stats_repo import SAAgentStatsRepo
from .database import Database
from .embedding_repo import SAEmbeddingRepo
from .handoff_history_repo import SAHandoffHistoryRepo
from .ingestion_state_repo import SAIngestionStateRepo
from .processed_document_repo import SAProcessedDocumentRepo
from .processing_failure_repo import SAProcessingFailureRepo
from .raw_message_repo import SARawMessageRepo
from .schemas import (
    init_ingestion_state_schema,
    init_processing_storage_schema,
    init_raw_storage_schema,
)
from .task_history_repo import SATaskHistoryRepo
from .topic_bundle_repo import SATopicBundleRepo
from .topic_card_repo import SATopicCardRepo

__all__ = [
    # Database
    "Database",
    # Schemas
    "init_ingestion_state_schema",
    "init_raw_storage_schema",
    "init_processing_storage_schema",
    # Repositories
    "SAIngestionStateRepo",
    "SARawMessageRepo",
    "SAProcessedDocumentRepo",
    "SAProcessingFailureRepo",
    "SATopicCardRepo",
    "SATopicBundleRepo",
    # Embedding (P5 RAG)
    "SAEmbeddingRepo",
    # Agent Persistence (Phase 3B)
    "SAAgentStateRepo",
    "SATaskHistoryRepo",
    "SAAgentStatsRepo",
    "SAHandoffHistoryRepo",
]
