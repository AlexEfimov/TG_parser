"""
CLI command for artifact export.

Thin wrapper — delegates to tg_parser.services.export_service.
"""

from tg_parser.services.export_service import run_export

__all__ = ["run_export"]
