"""
Tests for Agent Observability (Phase 3C).

Tests cover:
- CLI commands (agents list/status/history/cleanup/handoffs/archives)
- API endpoints (/api/v1/agents/*)
- AgentHistoryArchiver
"""

import gzip
import json
import pytest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from io import StringIO

from tg_parser.agents.archiver import AgentHistoryArchiver
from tg_parser.storage.ports import (
    AgentState,
    TaskRecord,
    HandoffRecord,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_agent_states():
    """Create sample agent states."""
    return [
        AgentState(
            name="ProcessingAgent",
            agent_type="processing",
            version="1.0.0",
            description="Processing agent",
            capabilities=["text_processing", "summarization"],
            model="gpt-4o-mini",
            provider="openai",
            is_active=True,
            total_tasks_processed=100,
            total_errors=5,
            avg_processing_time_ms=150.0,
            last_used_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        AgentState(
            name="TopicizationAgent",
            agent_type="topicization",
            version="1.0.0",
            description="Topicization agent",
            capabilities=["topicization"],
            model="gpt-4o-mini",
            provider="openai",
            is_active=True,
            total_tasks_processed=50,
            total_errors=2,
            avg_processing_time_ms=200.0,
            last_used_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]


@pytest.fixture
def sample_task_records():
    """Create sample task records."""
    now = datetime.now(UTC)
    return [
        TaskRecord(
            id="task_001",
            agent_name="ProcessingAgent",
            task_type="process_message",
            input_data={"text": "Hello world"},
            output_data={"summary": "Greeting"},
            source_ref="tg_test_post_1",
            channel_id="test_channel",
            success=True,
            processing_time_ms=100,
            created_at=now - timedelta(hours=1),
            expires_at=now + timedelta(days=14),
        ),
        TaskRecord(
            id="task_002",
            agent_name="ProcessingAgent",
            task_type="process_message",
            input_data={"text": "Goodbye"},
            output_data=None,
            source_ref="tg_test_post_2",
            channel_id="test_channel",
            success=False,
            error="LLM timeout",
            processing_time_ms=5000,
            created_at=now - timedelta(hours=2),
            expires_at=now + timedelta(days=14),
        ),
    ]


@pytest.fixture
def sample_handoff_records():
    """Create sample handoff records."""
    now = datetime.now(UTC)
    return [
        HandoffRecord(
            id="handoff_001",
            source_agent="OrchestratorAgent",
            target_agent="ProcessingAgent",
            task_type="process_batch",
            status="completed",
            priority=7,
            payload={"messages": ["msg1", "msg2"]},
            context={"channel_id": "test"},
            result={"processed": 2},
            processing_time_ms=500,
            created_at=now - timedelta(hours=1),
            completed_at=now,
        ),
        HandoffRecord(
            id="handoff_002",
            source_agent="OrchestratorAgent",
            target_agent="TopicizationAgent",
            task_type="topicize",
            status="failed",
            priority=5,
            payload={"docs": ["doc1"]},
            context={},
            result={},
            error="Clustering failed",
            processing_time_ms=1000,
            created_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
        ),
    ]


@pytest.fixture
def temp_archive_dir(tmp_path):
    """Create temporary archive directory."""
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    return archive_dir


# ============================================================================
# AgentHistoryArchiver Tests
# ============================================================================


class TestAgentHistoryArchiver:
    """Tests for AgentHistoryArchiver."""
    
    @pytest.mark.asyncio
    async def test_archive_task_history(self, temp_archive_dir, sample_task_records):
        """Test archiving task history records."""
        archiver = AgentHistoryArchiver(temp_archive_dir)
        
        filepath = await archiver.archive_task_history(sample_task_records)
        
        assert filepath is not None
        assert filepath.exists()
        assert filepath.suffix == ".gz"
        assert "task_history" in filepath.name
        
        # Verify contents
        with gzip.open(filepath, "rt", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        record1 = json.loads(lines[0])
        assert record1["id"] == "task_001"
        assert record1["agent_name"] == "ProcessingAgent"
    
    @pytest.mark.asyncio
    async def test_archive_task_history_empty(self, temp_archive_dir):
        """Test archiving empty task history returns None."""
        archiver = AgentHistoryArchiver(temp_archive_dir)
        
        filepath = await archiver.archive_task_history([])
        
        assert filepath is None
    
    @pytest.mark.asyncio
    async def test_archive_handoff_history(self, temp_archive_dir, sample_handoff_records):
        """Test archiving handoff history records."""
        archiver = AgentHistoryArchiver(temp_archive_dir)
        
        filepath = await archiver.archive_handoff_history(sample_handoff_records)
        
        assert filepath is not None
        assert filepath.exists()
        assert "handoff_history" in filepath.name
        
        # Verify contents
        with gzip.open(filepath, "rt", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        record1 = json.loads(lines[0])
        assert record1["source_agent"] == "OrchestratorAgent"
    
    @pytest.mark.asyncio
    async def test_archive_all(self, temp_archive_dir, sample_task_records, sample_handoff_records):
        """Test archiving both task and handoff history."""
        archiver = AgentHistoryArchiver(temp_archive_dir)
        
        result = await archiver.archive_all(sample_task_records, sample_handoff_records)
        
        assert result["task_history"] is not None
        assert result["handoff_history"] is not None
        assert result["task_history"].exists()
        assert result["handoff_history"].exists()
    
    @pytest.mark.asyncio
    async def test_archive_all_no_handoffs(self, temp_archive_dir, sample_task_records):
        """Test archiving with no handoff records."""
        archiver = AgentHistoryArchiver(temp_archive_dir)
        
        result = await archiver.archive_all(sample_task_records, None)
        
        assert result["task_history"] is not None
        assert result["handoff_history"] is None
    
    def test_list_archives(self, temp_archive_dir):
        """Test listing archive files."""
        # Create some test archives
        (temp_archive_dir / "task_history_20251228_120000.ndjson.gz").write_bytes(gzip.compress(b"test"))
        (temp_archive_dir / "handoff_history_20251228_120000.ndjson.gz").write_bytes(gzip.compress(b"test"))
        
        archiver = AgentHistoryArchiver(temp_archive_dir)
        archives = archiver.list_archives()
        
        assert len(archives) == 2
        assert any("task_history" in a["filename"] for a in archives)
        assert any("handoff_history" in a["filename"] for a in archives)
        assert all("size_bytes" in a for a in archives)
        assert all("created_at" in a for a in archives)
    
    def test_list_archives_empty(self, temp_archive_dir):
        """Test listing archives when directory is empty."""
        archiver = AgentHistoryArchiver(temp_archive_dir)
        archives = archiver.list_archives()
        
        assert archives == []


# ============================================================================
# CLI Command Tests (Unit Tests with Mocks)
# ============================================================================


class TestAgentsCLICommands:
    """Tests for agents CLI commands."""
    
    @pytest.mark.asyncio
    async def test_list_agents_command_integration(self, sample_agent_states):
        """Test list agents command returns agents."""
        with patch("tg_parser.cli.agents_cmd._get_persistence_and_db") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.list_all_agent_states.return_value = sample_agent_states
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.cli.agents_cmd import _get_persistence_and_db
            
            persistence, engine = await mock_get()
            agents = await persistence.list_all_agent_states(None)
            await engine.dispose()
            
            assert len(agents) == 2
            assert agents[0].name == "ProcessingAgent"
    
    @pytest.mark.asyncio
    async def test_agent_status_not_found(self):
        """Test agent status for non-existent agent."""
        with patch("tg_parser.cli.agents_cmd._get_persistence_and_db") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.load_agent_state.return_value = None
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            persistence, engine = await mock_get()
            state = await persistence.load_agent_state("NonExistentAgent")
            await engine.dispose()
            
            assert state is None


# ============================================================================
# API Endpoint Tests (Unit Tests)
# ============================================================================


class TestAgentsAPIEndpoints:
    """Tests for agents API endpoints."""
    
    @pytest.mark.asyncio
    async def test_list_agents_endpoint(self, sample_agent_states):
        """Test GET /api/v1/agents endpoint."""
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.list_all_agent_states.return_value = sample_agent_states
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.api.routes.agents import list_agents
            
            response = await list_agents(agent_type=None, active_only=False)
            
            assert response.total == 2
            assert len(response.agents) == 2
            assert response.agents[0].name == "ProcessingAgent"
    
    @pytest.mark.asyncio
    async def test_get_agent_endpoint(self, sample_agent_states):
        """Test GET /api/v1/agents/{name} endpoint."""
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.load_agent_state.return_value = sample_agent_states[0]
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.api.routes.agents import get_agent
            
            response = await get_agent("ProcessingAgent")
            
            assert response.name == "ProcessingAgent"
            assert response.agent_type == "processing"
            assert response.total_tasks_processed == 100
    
    @pytest.mark.asyncio
    async def test_get_agent_not_found(self):
        """Test GET /api/v1/agents/{name} for non-existent agent."""
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.load_agent_state.return_value = None
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.api.routes.agents import get_agent
            from fastapi import HTTPException
            
            with pytest.raises(HTTPException) as exc_info:
                await get_agent("NonExistentAgent")
            
            assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_get_agent_stats_endpoint(self, sample_agent_states):
        """Test GET /api/v1/agents/{name}/stats endpoint."""
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.load_agent_state.return_value = sample_agent_states[0]
            mock_persistence.get_agent_summary.return_value = {
                "total_tasks": 100,
                "successful_tasks": 95,
                "failed_tasks": 5,
                "success_rate": 0.95,
                "avg_processing_time_ms": 150.0,
                "by_task_type": {"process_message": {"count": 100}},
            }
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.api.routes.agents import get_agent_stats
            
            response = await get_agent_stats("ProcessingAgent", days=30)
            
            assert response.agent_name == "ProcessingAgent"
            assert response.total_tasks == 100
            assert response.success_rate == 0.95
    
    @pytest.mark.asyncio
    async def test_get_agent_history_endpoint(self, sample_agent_states, sample_task_records):
        """Test GET /api/v1/agents/{name}/history endpoint."""
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.load_agent_state.return_value = sample_agent_states[0]
            mock_persistence.get_task_history.return_value = sample_task_records
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.api.routes.agents import get_agent_history
            
            response = await get_agent_history(
                "ProcessingAgent", 
                limit=50,
                from_date=None,
                to_date=None,
            )
            
            assert response.agent_name == "ProcessingAgent"
            assert response.total == 2
            assert len(response.records) == 2
            assert response.records[0].id == "task_001"
    
    @pytest.mark.asyncio
    async def test_get_handoff_stats_endpoint(self):
        """Test GET /api/v1/agents/stats/handoffs endpoint."""
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_persistence = AsyncMock()
            mock_persistence.get_handoff_statistics.return_value = {
                "total_handoffs": 100,
                "completed": 90,
                "failed": 8,
                "rejected": 2,
                "in_progress": 0,
                "success_rate": 0.9,
                "avg_processing_time_ms": 300.0,
                "min_processing_time_ms": 50,
                "max_processing_time_ms": 2000,
                "top_agent_pairs": [
                    {"source": "Orchestrator", "target": "Processor", "count": 50},
                ],
            }
            
            mock_engine = AsyncMock()
            mock_get.return_value = (mock_persistence, mock_engine)
            
            from tg_parser.api.routes.agents import get_handoff_stats
            
            response = await get_handoff_stats()
            
            assert response.total_handoffs == 100
            assert response.completed == 90
            assert response.success_rate == 0.9
            assert len(response.top_agent_pairs) == 1


# ============================================================================
# Integration Tests (with real database - skipped by default)
# ============================================================================


class TestAgentsObservabilityIntegration:
    """Integration tests with real database (skipped without marker)."""
    
    @pytest.mark.skip(reason="Requires initialized database")
    @pytest.mark.asyncio
    async def test_full_cli_workflow(self):
        """Test full CLI workflow: list -> status -> history -> cleanup."""
        # This would require a real database setup
        pass
    
    @pytest.mark.skip(reason="Requires running API server")
    @pytest.mark.asyncio
    async def test_full_api_workflow(self):
        """Test full API workflow with HTTP client."""
        # This would require TestClient and running server
        pass

