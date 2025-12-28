"""
API routes module.
"""

from tg_parser.api.routes.agents import router as agents_router
from tg_parser.api.routes.export import router as export_router
from tg_parser.api.routes.health import router as health_router
from tg_parser.api.routes.process import router as process_router

__all__ = ["health_router", "process_router", "export_router", "agents_router"]

