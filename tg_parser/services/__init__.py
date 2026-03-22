"""
Service layer for TG_parser.

Encapsulates business logic previously spread across CLI commands.
Both CLI and API should call these services instead of duplicating logic.
"""

from tg_parser.services.export_service import run_export
from tg_parser.services.ingestion_service import run_ingestion
from tg_parser.services.pipeline_service import run_full_pipeline
from tg_parser.services.processing_service import (
    run_multi_agent_processing,
    run_processing,
)
from tg_parser.services.scheduler_service import (
    get_scheduler_status,
    run_incremental_for_all_sources,
    run_incremental_for_source,
)
from tg_parser.services.topicization_service import run_topicization

__all__ = [
    "run_ingestion",
    "run_processing",
    "run_multi_agent_processing",
    "run_topicization",
    "run_export",
    "run_full_pipeline",
    "run_incremental_for_all_sources",
    "run_incremental_for_source",
    "get_scheduler_status",
]
