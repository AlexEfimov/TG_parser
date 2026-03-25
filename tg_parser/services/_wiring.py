"""
Centralized repository wiring helpers.

Provides convenience functions for creating engines, session factories,
and persistence instances using engine_factory.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.agents.persistence import AgentPersistence
from tg_parser.config import settings
from tg_parser.storage.engine_factory import create_engine_from_settings
from tg_parser.storage.sqlalchemy.agent_state_repo import SAAgentStateRepo
from tg_parser.storage.sqlalchemy.agent_stats_repo import SAAgentStatsRepo
from tg_parser.storage.sqlalchemy.handoff_history_repo import SAHandoffHistoryRepo
from tg_parser.storage.sqlalchemy.task_history_repo import SATaskHistoryRepo


def create_processing_engine(echo: bool = False) -> AsyncEngine:
    """Create an engine for the processing database."""
    return create_engine_from_settings(settings, "processing", echo=echo)


def create_session_factory(engine: AsyncEngine) -> sessionmaker:
    """Create an async session factory from an engine."""
    return sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def create_agent_persistence(
    session_factory: sessionmaker,
) -> AgentPersistence:
    """Create an AgentPersistence wired to the given session factory."""
    return AgentPersistence(
        agent_state_repo=SAAgentStateRepo(session_factory),
        task_history_repo=SATaskHistoryRepo(session_factory),
        agent_stats_repo=SAAgentStatsRepo(session_factory),
        handoff_history_repo=SAHandoffHistoryRepo(session_factory),
        retention_days=settings.agent_retention_days,
        stats_enabled=settings.agent_stats_enabled,
    )
