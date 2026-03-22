"""
CLI command for one-shot full pipeline run.

Thin wrapper — delegates to tg_parser.services.pipeline_service.
"""

from tg_parser.services.pipeline_service import run_full_pipeline

__all__ = ["run_full_pipeline"]
