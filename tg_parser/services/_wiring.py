"""
Centralized repository wiring helpers.

Uses the Database singleton for engines and session factories.
"""

from sqlalchemy.orm import sessionmaker

from tg_parser.agents.persistence import AgentPersistence
from tg_parser.config import settings
from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.agent_state_repo import SAAgentStateRepo
from tg_parser.storage.sqlalchemy.agent_stats_repo import SAAgentStatsRepo
from tg_parser.storage.sqlalchemy.handoff_history_repo import SAHandoffHistoryRepo
from tg_parser.storage.sqlalchemy.task_history_repo import SATaskHistoryRepo


async def get_processing_session_factory() -> sessionmaker:
    """Return the processing sessionmaker from the Database singleton."""
    db = Database.get_instance()
    await db.init()
    return db.processing_session_factory


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


async def get_agent_persistence() -> AgentPersistence:
    """Return an AgentPersistence using the Database singleton."""
    session_factory = await get_processing_session_factory()
    return create_agent_persistence(session_factory)
