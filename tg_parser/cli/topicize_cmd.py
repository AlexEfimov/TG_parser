"""
CLI command for topicization pipeline.

Thin wrapper — delegates to tg_parser.services.topicization_service.
"""

from tg_parser.services.topicization_service import run_topicization

__all__ = ["run_topicization"]
