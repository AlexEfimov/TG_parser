"""
API routes module.
"""

from tg_parser.api.routes.agents import router as agents_router
from tg_parser.api.routes.channels import router as channels_router
from tg_parser.api.routes.documents import router as documents_router
from tg_parser.api.routes.export import router as export_router
from tg_parser.api.routes.health import router as health_router
from tg_parser.api.routes.llm_config import router as llm_config_router
from tg_parser.api.routes.process import router as process_router
from tg_parser.api.routes.rag import router as rag_router
from tg_parser.api.routes.topics import router as topics_router
from tg_parser.api.routes.users import router as users_router

__all__ = [
    "health_router",
    "process_router",
    "export_router",
    "agents_router",
    "rag_router",
    "topics_router",
    "channels_router",
    "documents_router",
    "llm_config_router",
    "users_router",
]
