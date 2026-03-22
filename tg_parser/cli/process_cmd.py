"""
CLI command for processing pipeline.

Thin wrapper — delegates to tg_parser.services.processing_service.
"""

from tg_parser.services.processing_service import (
    _get_api_key_for_provider,
    _process_with_agent,
    run_multi_agent_processing,
    run_processing,
)

__all__ = [
    "run_processing",
    "run_multi_agent_processing",
    "_process_with_agent",
    "_get_api_key_for_provider",
]
