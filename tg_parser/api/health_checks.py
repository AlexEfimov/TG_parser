"""
Health check implementations.

Phase 3D: Detailed health checks for all system components.
Session 24: Enhanced database checks with PostgreSQL support and pool metrics.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from tg_parser.config import settings

logger = logging.getLogger(__name__)


async def check_database() -> dict[str, Any]:
    """
    Check database connectivity and health.
    
    Session 24: Enhanced with PostgreSQL support and connection pool metrics.
    
    Returns:
        Dictionary with database health status
    """
    from pathlib import Path

    from sqlalchemy import text

    from tg_parser.storage.engine_factory import (
        create_engine_from_settings,
        get_pool_status,
    )

    result = {
        "status": "unknown",
        "type": settings.db_type,
        "latency_ms": None,
        "details": {},
    }
    
    db_type = settings.db_type.lower()
    
    # SQLite-specific checks
    if db_type == "sqlite":
        db_path = Path(settings.processing_storage_db_path)
        
        # Check if database file exists
        if not db_path.exists():
            result["status"] = "warning"
            result["details"]["message"] = "Database file does not exist (will be created on first use)"
            return result
        
        result["details"]["path"] = str(db_path)
        result["details"]["size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)
    
    # PostgreSQL-specific checks
    elif db_type == "postgresql":
        result["details"]["host"] = settings.db_host
        result["details"]["port"] = settings.db_port
        result["details"]["database"] = settings.db_name
        result["details"]["pool_size"] = settings.db_pool_size
        result["details"]["max_overflow"] = settings.db_max_overflow
    
    # Try to connect and execute a simple query
    engine = create_engine_from_settings(settings, "processing", echo=False)
    
    try:
        start_time = datetime.now(UTC)
        
        async with engine.connect() as conn:
            # Execute simple query
            await conn.execute(text("SELECT 1"))
            
            # Get table count
            try:
                if db_type == "sqlite":
                    result_rows = await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    )
                else:  # postgresql
                    result_rows = await conn.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname='public'"
                        )
                    )
                tables = [row[0] for row in result_rows.fetchall()]
                result["details"]["tables"] = len(tables)
            except Exception as e:
                logger.debug(f"Failed to get table count: {e}")
        
        latency = (datetime.now(UTC) - start_time).total_seconds() * 1000
        result["status"] = "ok"
        result["latency_ms"] = round(latency, 2)
        
        # Get connection pool status (Session 24)
        pool_status = get_pool_status(engine)
        result["pool"] = pool_status
        
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
        logger.error(f"Database health check failed: {e}")
        
    finally:
        await engine.dispose()
    
    return result


async def check_llm_provider() -> dict[str, Any]:
    """
    Check LLM provider connectivity.
    
    Returns:
        Dictionary with LLM provider health status
    """
    import os

    result = {
        "status": "unknown",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "latency_ms": None,
        "details": {},
    }
    
    provider = settings.llm_provider.lower()
    
    # Check API key presence
    api_key_vars = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "ollama": None,  # Ollama doesn't need API key
    }
    
    api_key_var = api_key_vars.get(provider)
    
    if api_key_var and not os.environ.get(api_key_var):
        result["status"] = "warning"
        result["details"]["message"] = f"{api_key_var} not set"
        return result
    
    # Try to make a simple API call
    try:
        start_time = datetime.now(UTC)
        
        if provider == "openai":
            await _check_openai()
        elif provider == "anthropic":
            await _check_anthropic()
        elif provider == "gemini":
            await _check_gemini()
        elif provider == "ollama":
            await _check_ollama()
        else:
            result["status"] = "warning"
            result["details"]["message"] = f"Unknown provider: {provider}"
            return result
        
        latency = (datetime.now(UTC) - start_time).total_seconds() * 1000
        result["status"] = "ok"
        result["latency_ms"] = round(latency, 2)
        
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
        logger.warning(f"LLM provider health check failed: {e}")
    
    return result


async def _check_openai() -> None:
    """Check OpenAI API connectivity."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        response.raise_for_status()


async def _check_anthropic() -> None:
    """Check Anthropic API connectivity."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Anthropic doesn't have a simple ping endpoint, 
        # so we just check if we can reach the API
        response = await client.get(
            "https://api.anthropic.com/v1/",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        # 404 is expected for root endpoint, but means API is reachable
        if response.status_code not in (200, 404):
            response.raise_for_status()


async def _check_gemini() -> None:
    """Check Google Gemini API connectivity."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"https://generativelanguage.googleapis.com/v1/models?key={settings.google_api_key}"
        )
        response.raise_for_status()


async def _check_ollama() -> None:
    """Check Ollama local server connectivity."""
    import httpx

    base_url = settings.ollama_base_url.rstrip("/")
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url}/api/tags")
        response.raise_for_status()


async def check_agent_registry() -> dict[str, Any]:
    """
    Check agent registry status.
    
    Returns:
        Dictionary with agent registry health status
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from tg_parser.storage.sqlite.agent_state_repo import SQLiteAgentStateRepo

    result = {
        "status": "unknown",
        "details": {},
    }
    
    try:
        db_url = f"sqlite+aiosqlite:///{settings.processing_storage_db_path}"
        engine = create_async_engine(db_url, echo=False)
        
        session_factory = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        repo = SQLiteAgentStateRepo(session_factory)
        
        try:
            agents = await repo.list_all()
            active_count = sum(1 for a in agents if a.is_active)
            
            result["status"] = "ok"
            result["details"]["total_agents"] = len(agents)
            result["details"]["active_agents"] = active_count
            result["details"]["agent_types"] = list(set(a.agent_type for a in agents))
            
        finally:
            await engine.dispose()
            
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
        logger.warning(f"Agent registry health check failed: {e}")
    
    return result


async def check_scheduler() -> dict[str, Any]:
    """
    Check background scheduler status.
    
    Returns:
        Dictionary with scheduler health status
    """
    from tg_parser.api.scheduler import get_scheduler

    result = {
        "status": "unknown",
        "details": {},
    }
    
    try:
        scheduler = get_scheduler()
        
        if scheduler.is_running:
            tasks = scheduler.get_tasks()
            result["status"] = "ok"
            result["details"]["running"] = True
            result["details"]["tasks_count"] = len(tasks)
            result["details"]["tasks"] = [t["id"] for t in tasks]
        else:
            result["status"] = "warning"
            result["details"]["running"] = False
            result["details"]["message"] = "Scheduler not running"
            
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
    
    return result


async def check_all_components() -> dict[str, str]:
    """
    Check all system components.
    
    Returns:
        Dictionary mapping component name to status
    """
    results = {}
    
    # Database check
    db_result = await check_database()
    results["database"] = db_result["status"]
    
    # LLM provider check
    llm_result = await check_llm_provider()
    results["llm"] = llm_result["status"]
    
    # Agent registry check
    agent_result = await check_agent_registry()
    results["agents"] = agent_result["status"]
    
    # Scheduler check
    scheduler_result = await check_scheduler()
    results["scheduler"] = scheduler_result["status"]
    
    return results


async def get_detailed_health() -> dict[str, Any]:
    """
    Get detailed health information for all components.
    
    Returns:
        Dictionary with detailed health info
    """
    return {
        "database": await check_database(),
        "llm": await check_llm_provider(),
        "agents": await check_agent_registry(),
        "scheduler": await check_scheduler(),
    }

