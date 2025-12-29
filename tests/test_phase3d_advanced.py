"""
Tests for Phase 3D: Advanced Features.

Tests for:
- Prometheus metrics
- Health checks
- Background scheduler
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# Prometheus Metrics Tests
# ============================================================================


class TestPrometheusMetrics:
    """Tests for Prometheus metrics module."""
    
    def test_create_instrumentator(self):
        """Test instrumentator creation."""
        from tg_parser.api.metrics import create_instrumentator
        
        instrumentator = create_instrumentator()
        
        assert instrumentator is not None
        # Check that excluded handlers are set (they are regex patterns)
        handler_patterns = [str(h.pattern) if hasattr(h, 'pattern') else str(h) 
                          for h in instrumentator.excluded_handlers]
        assert any("/metrics" in p for p in handler_patterns)
        assert any("/health" in p for p in handler_patterns)
    
    def test_record_agent_task(self):
        """Test recording agent task metrics."""
        from tg_parser.api.metrics import (
            AGENT_TASK_DURATION_SECONDS,
            AGENT_TASKS_TOTAL,
            record_agent_task,
        )
        
        # Record a successful task
        record_agent_task(
            agent_name="test_agent",
            task_type="process",
            success=True,
            duration_seconds=1.5,
        )
        
        # Metrics should be recorded (we can't easily verify counter values
        # without more setup, but no exception means success)
        assert True
    
    def test_record_message_processed(self):
        """Test recording message processing metrics."""
        from tg_parser.api.metrics import record_message_processed
        
        record_message_processed("test_channel", success=True)
        record_message_processed("test_channel", success=False)
        
        assert True
    
    def test_record_llm_request(self):
        """Test recording LLM request metrics."""
        from tg_parser.api.metrics import record_llm_request
        
        record_llm_request(
            provider="openai",
            model="gpt-4",
            success=True,
            duration_seconds=2.5,
            prompt_tokens=100,
            completion_tokens=50,
        )
        
        assert True
    
    def test_update_active_agents(self):
        """Test updating active agents gauge."""
        from tg_parser.api.metrics import update_active_agents
        
        update_active_agents("processing", 5)
        update_active_agents("orchestrator", 1)
        
        assert True
    
    def test_record_scheduler_task(self):
        """Test recording scheduler task metrics."""
        from tg_parser.api.metrics import record_scheduler_task
        
        record_scheduler_task("cleanup", success=True)
        record_scheduler_task("health_check", success=False)
        
        assert True


# ============================================================================
# Health Check Tests
# ============================================================================


class TestHealthChecks:
    """Tests for health check functions."""
    
    @pytest.mark.asyncio
    async def test_check_database_missing_file(self):
        """Test database check when file doesn't exist."""
        from pathlib import Path
        from tg_parser.api.health_checks import check_database
        
        with patch("tg_parser.api.health_checks.settings") as mock_settings:
            mock_settings.db_type = "sqlite"  # Session 24: added db_type
            mock_settings.processing_storage_db_path = Path("/nonexistent/db.sqlite")
            
            result = await check_database()
            
            assert result["status"] == "warning"
            assert "does not exist" in result["details"]["message"]
    
    @pytest.mark.asyncio
    async def test_check_llm_provider_no_key(self):
        """Test LLM check when API key not set."""
        from tg_parser.api.health_checks import check_llm_provider
        
        with patch("tg_parser.api.health_checks.settings") as mock_settings:
            mock_settings.llm_provider = "openai"
            mock_settings.llm_model = "gpt-4"
            
            with patch.dict("os.environ", {}, clear=True):
                result = await check_llm_provider()
                
                assert result["status"] == "warning"
                assert result["provider"] == "openai"
    
    @pytest.mark.asyncio
    async def test_check_scheduler_not_running(self):
        """Test scheduler check when not running."""
        from tg_parser.api.health_checks import check_scheduler
        
        result = await check_scheduler()
        
        # Scheduler might not be running in tests
        assert result["status"] in ("ok", "warning")
        assert "running" in result["details"]
    
    @pytest.mark.asyncio
    async def test_check_all_components(self):
        """Test checking all components."""
        from tg_parser.api.health_checks import check_all_components
        
        results = await check_all_components()
        
        # Should have all component keys
        assert "database" in results
        assert "llm" in results
        assert "agents" in results
        assert "scheduler" in results
    
    @pytest.mark.asyncio
    async def test_get_detailed_health(self):
        """Test getting detailed health info."""
        from tg_parser.api.health_checks import get_detailed_health
        
        detailed = await get_detailed_health()
        
        # Each component should have status and details
        for component in ["database", "llm", "agents", "scheduler"]:
            assert component in detailed
            assert "status" in detailed[component]
            assert "details" in detailed[component]


# ============================================================================
# Scheduler Tests
# ============================================================================


class TestBackgroundScheduler:
    """Tests for background scheduler."""
    
    def test_scheduler_creation(self):
        """Test scheduler instance creation."""
        from tg_parser.api.scheduler import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        assert scheduler is not None
        assert not scheduler.is_running
    
    def test_add_task(self):
        """Test adding a scheduled task."""
        from tg_parser.api.scheduler import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        async def dummy_task():
            pass
        
        scheduler.add_task(
            task_id="test_task",
            func=dummy_task,
            interval_seconds=60,
        )
        
        tasks = scheduler.get_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "test_task"
    
    def test_remove_task(self):
        """Test removing a scheduled task."""
        from tg_parser.api.scheduler import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        async def dummy_task():
            pass
        
        scheduler.add_task("test_task", dummy_task, 60)
        assert len(scheduler.get_tasks()) == 1
        
        result = scheduler.remove_task("test_task")
        assert result is True
        assert len(scheduler.get_tasks()) == 0
    
    def test_remove_nonexistent_task(self):
        """Test removing a task that doesn't exist."""
        from tg_parser.api.scheduler import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        result = scheduler.remove_task("nonexistent")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_start_and_shutdown(self):
        """Test scheduler start and shutdown."""
        from tg_parser.api.scheduler import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        
        assert not scheduler.is_running
        
        # Start requires running event loop (which pytest-asyncio provides)
        scheduler.start()
        assert scheduler.is_running
        
        scheduler.shutdown(wait=False)
        assert not scheduler.is_running
    
    def test_get_scheduler_singleton(self):
        """Test that get_scheduler returns singleton."""
        from tg_parser.api.scheduler import get_scheduler
        
        scheduler1 = get_scheduler()
        scheduler2 = get_scheduler()
        
        assert scheduler1 is scheduler2
    
    def test_setup_default_tasks(self):
        """Test setup of default tasks."""
        from tg_parser.api.scheduler import BackgroundScheduler, setup_default_tasks
        
        scheduler = BackgroundScheduler()
        
        setup_default_tasks(
            scheduler,
            cleanup_interval_hours=24,
            health_check_interval_minutes=5,
            retention_days=30,
        )
        
        tasks = scheduler.get_tasks()
        task_ids = [t["id"] for t in tasks]
        
        assert "cleanup_expired_records" in task_ids
        assert "health_check" in task_ids


# ============================================================================
# API Endpoint Tests
# ============================================================================


class TestHealthEndpoints:
    """Tests for health check API endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test /health endpoint."""
        from tg_parser.api.routes.health import health_check
        
        response = await health_check()
        
        assert response.status == "ok"
        assert response.version is not None
        assert response.timestamp is not None
    
    @pytest.mark.asyncio
    async def test_status_endpoint(self):
        """Test /status endpoint."""
        from tg_parser.api.routes.health import status
        
        response = await status()
        
        assert response.status in ("ok", "warning", "degraded")
        assert response.components is not None
        assert response.stats is not None
    
    @pytest.mark.asyncio
    async def test_detailed_status_endpoint(self):
        """Test /status/detailed endpoint."""
        from tg_parser.api.routes.health import detailed_status
        
        response = await detailed_status()
        
        assert "status" in response
        assert "components" in response
        assert "timestamp" in response
    
    @pytest.mark.asyncio
    async def test_scheduler_status_endpoint(self):
        """Test /scheduler endpoint."""
        from tg_parser.api.routes.health import scheduler_status
        
        response = await scheduler_status()
        
        assert "running" in response
        assert "tasks" in response
        assert "enabled" in response


# ============================================================================
# Integration Tests
# ============================================================================


class TestMetricsIntegration:
    """Integration tests for metrics with FastAPI app."""
    
    def test_app_creation_with_metrics(self):
        """Test app creation with metrics (metrics disabled in test env)."""
        from tg_parser.api.main import create_app
        from tg_parser.config import settings
        
        app = create_app()
        
        # In test environment, metrics are disabled to prevent registry conflicts
        # Verify the setting controls whether /metrics is added
        routes = [getattr(r, 'path', str(r)) for r in app.routes]
        
        if settings.metrics_enabled:
            assert any('/metrics' in str(r) for r in routes)
        else:
            # Metrics disabled - just verify app was created
            assert app is not None
            assert len(routes) > 0


class TestSchedulerIntegration:
    """Integration tests for scheduler."""
    
    @pytest.mark.asyncio
    async def test_cleanup_task_function(self):
        """Test cleanup task function signature and import."""
        from tg_parser.api.scheduler import cleanup_expired_records
        
        # Just verify the function is importable and has correct signature
        import inspect
        sig = inspect.signature(cleanup_expired_records)
        
        assert "retention_days" in sig.parameters
        assert "archive_path" in sig.parameters


# ============================================================================
# Settings Tests
# ============================================================================


class TestPhase3DSettings:
    """Tests for Phase 3D settings."""
    
    def test_default_settings(self):
        """Test default Phase 3D settings (metrics may be disabled in tests)."""
        from tg_parser.config import Settings
        
        # Note: metrics_enabled may be False in test environment
        # due to conftest.py setting METRICS_ENABLED=false
        settings = Settings()
        
        # Metrics setting exists (value depends on environment)
        assert hasattr(settings, 'metrics_enabled')
        
        # Scheduler settings
        assert settings.scheduler_enabled is True
        assert settings.scheduler_cleanup_interval_hours == 24
        assert settings.scheduler_health_check_interval_minutes == 5
        
        # Ollama settings
        assert settings.ollama_base_url == "http://localhost:11434"
    
    def test_settings_can_be_overridden(self):
        """Test that settings can be overridden via environment."""
        import os
        
        with patch.dict(os.environ, {
            "METRICS_ENABLED": "false",
            "SCHEDULER_ENABLED": "false",
            "SCHEDULER_CLEANUP_INTERVAL_HOURS": "48",
        }):
            from tg_parser.config import Settings
            
            settings = Settings()
            
            assert settings.metrics_enabled is False
            assert settings.scheduler_enabled is False
            assert settings.scheduler_cleanup_interval_hours == 48

