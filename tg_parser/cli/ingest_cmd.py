"""
CLI command for ingestion.

Thin wrapper — delegates to tg_parser.services.ingestion_service.
"""

from tg_parser.services.ingestion_service import run_ingestion

__all__ = ["run_ingestion"]
