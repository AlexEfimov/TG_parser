"""
CLI command for topicization pipeline.

Thin wrapper — delegates to tg_parser.services.topicization_service.
"""

from tg_parser.services.topicization_service import (
    run_incremental_topicization,
    run_incremental_topicization_for_uncovered,
    run_topicization,
)

__all__ = [
    "run_topicization",
    "run_incremental_topicization",
    "run_incremental_topicization_for_uncovered",
]
