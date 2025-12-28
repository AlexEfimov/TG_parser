"""
SQLite реализации репозиториев TG_parser.

Реализует ADR-0003: SQLAlchemy 2.x async для SQLite (MVP).
"""

from .agent_state_repo import SQLiteAgentStateRepo
from .agent_stats_repo import SQLiteAgentStatsRepo
from .database import Database, DatabaseConfig
from .handoff_history_repo import SQLiteHandoffHistoryRepo
from .ingestion_state_repo import SQLiteIngestionStateRepo
from .processed_document_repo import SQLiteProcessedDocumentRepo
from .processing_failure_repo import SQLiteProcessingFailureRepo
from .raw_message_repo import SQLiteRawMessageRepo
from .schemas import (
    init_ingestion_state_schema,
    init_processing_storage_schema,
    init_raw_storage_schema,
)
from .task_history_repo import SQLiteTaskHistoryRepo
from .topic_bundle_repo import SQLiteTopicBundleRepo
from .topic_card_repo import SQLiteTopicCardRepo

__all__ = [
    # Database
    "Database",
    "DatabaseConfig",
    # Schemas
    "init_ingestion_state_schema",
    "init_raw_storage_schema",
    "init_processing_storage_schema",
    # Repositories
    "SQLiteIngestionStateRepo",
    "SQLiteRawMessageRepo",
    "SQLiteProcessedDocumentRepo",
    "SQLiteProcessingFailureRepo",
    "SQLiteTopicCardRepo",
    "SQLiteTopicBundleRepo",
    # Agent Persistence (Phase 3B)
    "SQLiteAgentStateRepo",
    "SQLiteTaskHistoryRepo",
    "SQLiteAgentStatsRepo",
    "SQLiteHandoffHistoryRepo",
]
