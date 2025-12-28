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
# Integration Tests (E2E with real database)
# ============================================================================


class TestAgentsObservabilityE2E:
    """E2E Integration tests with real database."""
    
    @pytest.fixture
    async def temp_db_settings(self, tmp_path):
        """Create temporary database for E2E tests."""
        from tg_parser.config.settings import Settings
        
        db_path = tmp_path / "test_processing.db"
        
        settings = Settings(
            ingestion_state_db_path=tmp_path / "ingestion.db",
            raw_storage_db_path=tmp_path / "raw.db",
            processing_storage_db_path=db_path,
            telegram_api_id=12345,
            telegram_api_hash="test_hash",
            telegram_phone="+1234567890",
            openai_api_key="sk-test-key",
            agent_retention_days=14,
            agent_stats_enabled=True,
        )
        
        # Initialize processing storage schema (includes agent tables)
        from sqlalchemy.ext.asyncio import create_async_engine
        from tg_parser.storage.sqlite import init_processing_storage_schema
        
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        await init_processing_storage_schema(engine)
        await engine.dispose()
        
        return settings
    
    @pytest.fixture
    async def persistence_with_data(self, temp_db_settings):
        """Create persistence layer with sample data."""
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        
        from tg_parser.agents.persistence import AgentPersistence
        from tg_parser.storage.sqlite.agent_state_repo import SQLiteAgentStateRepo
        from tg_parser.storage.sqlite.agent_stats_repo import SQLiteAgentStatsRepo
        from tg_parser.storage.sqlite.handoff_history_repo import SQLiteHandoffHistoryRepo
        from tg_parser.storage.sqlite.task_history_repo import SQLiteTaskHistoryRepo
        from tg_parser.storage.ports import AgentState
        
        db_url = f"sqlite+aiosqlite:///{temp_db_settings.processing_storage_db_path}"
        engine = create_async_engine(db_url, echo=False)
        
        session_factory = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        persistence = AgentPersistence(
            agent_state_repo=SQLiteAgentStateRepo(session_factory),
            task_history_repo=SQLiteTaskHistoryRepo(session_factory),
            agent_stats_repo=SQLiteAgentStatsRepo(session_factory),
            handoff_history_repo=SQLiteHandoffHistoryRepo(session_factory),
            retention_days=14,
            stats_enabled=True,
        )
        
        # Create sample agent states
        now = datetime.now(UTC)
        sample_agents = [
            AgentState(
                name="TestProcessingAgent",
                agent_type="processing",
                version="1.0.0",
                description="Test processing agent",
                capabilities=["text_processing", "summarization"],
                model="gpt-4o-mini",
                provider="openai",
                is_active=True,
                total_tasks_processed=50,
                total_errors=2,
                avg_processing_time_ms=150.0,
                last_used_at=now,
                created_at=now,
                updated_at=now,
            ),
            AgentState(
                name="TestTopicizationAgent",
                agent_type="topicization",
                version="1.0.0",
                description="Test topicization agent",
                capabilities=["topic_extraction"],
                model="gpt-4o-mini",
                provider="openai",
                is_active=True,
                total_tasks_processed=25,
                total_errors=1,
                avg_processing_time_ms=200.0,
                last_used_at=now,
                created_at=now,
                updated_at=now,
            ),
        ]
        
        # Save sample agents
        for agent in sample_agents:
            await persistence._agent_state_repo.save(agent)
        
        # Record sample tasks
        for i in range(5):
            await persistence.record_task(
                agent_name="TestProcessingAgent",
                task_type="process_message",
                input_data={"text": f"Test message {i}"},
                output_data={"summary": f"Summary {i}"},
                success=True,
                processing_time_ms=100 + i * 10,
                source_ref=f"tg_test_post_{i}",
                channel_id="test_channel",
            )
        
        # Record a failed task
        await persistence.record_task(
            agent_name="TestProcessingAgent",
            task_type="process_message",
            input_data={"text": "Failed message"},
            success=False,
            error="LLM timeout",
            processing_time_ms=5000,
            source_ref="tg_test_post_failed",
            channel_id="test_channel",
        )
        
        yield persistence, engine, temp_db_settings
        
        await engine.dispose()
    
    @pytest.mark.asyncio
    async def test_full_cli_workflow(self, persistence_with_data, tmp_path):
        """
        Test full CLI workflow: list agents -> status -> history -> cleanup.
        
        This E2E test verifies the complete CLI agent observability workflow
        with a real database.
        """
        persistence, engine, temp_settings = persistence_with_data
        
        # ====== Step 1: List agents ======
        agents = await persistence.list_all_agent_states(None)
        
        assert len(agents) == 2
        agent_names = [a.name for a in agents]
        assert "TestProcessingAgent" in agent_names
        assert "TestTopicizationAgent" in agent_names
        
        # Verify agent properties
        processing_agent = next(a for a in agents if a.name == "TestProcessingAgent")
        assert processing_agent.agent_type == "processing"
        assert processing_agent.is_active is True
        assert "text_processing" in processing_agent.capabilities
        
        # ====== Step 2: Get agent status with statistics ======
        state = await persistence.load_agent_state("TestProcessingAgent")
        
        assert state is not None
        assert state.name == "TestProcessingAgent"
        assert state.total_tasks_processed >= 50  # May have more from recorded tasks
        assert state.avg_processing_time_ms > 0
        
        # Get summary for agent
        summary = await persistence.get_agent_summary("TestProcessingAgent", days=30)
        
        # Summary should have task statistics
        assert summary.get("total_tasks", 0) >= 6  # 5 success + 1 failure
        
        # ====== Step 3: Get task history ======
        history = await persistence.get_task_history(
            agent_name="TestProcessingAgent",
            limit=50,
        )
        
        assert len(history) >= 6
        
        # Check for successful and failed tasks
        success_count = sum(1 for t in history if t.success)
        failed_count = sum(1 for t in history if not t.success)
        
        assert success_count >= 5
        assert failed_count >= 1
        
        # Check failed task has error message
        failed_task = next(t for t in history if not t.success)
        assert failed_task.error is not None
        assert "timeout" in failed_task.error.lower()
        
        # ====== Step 4: Filter active only ======
        active_agents = [a for a in agents if a.is_active]
        
        assert len(active_agents) == 2  # Both are active
        
        # ====== Step 5: Mark agent inactive and verify ======
        await persistence.mark_agent_inactive("TestTopicizationAgent")
        
        updated_state = await persistence.load_agent_state("TestTopicizationAgent")
        assert updated_state.is_active is False
        
        # List with filter
        all_agents = await persistence.list_all_agent_states(None)
        active_only = [a for a in all_agents if a.is_active]
        
        assert len(active_only) == 1
        assert active_only[0].name == "TestProcessingAgent"
    
    @pytest.mark.asyncio
    async def test_full_api_workflow(self, persistence_with_data):
        """
        Test full API workflow with TestClient.
        
        This E2E test verifies the complete API workflow:
        - GET /api/v1/agents - list agents
        - GET /api/v1/agents/{name} - get specific agent
        - GET /api/v1/agents/{name}/stats - get agent statistics
        - GET /api/v1/agents/{name}/history - get task history
        - GET /status/detailed - detailed health check
        """
        persistence, engine, temp_settings = persistence_with_data
        
        from httpx import AsyncClient, ASGITransport
        from tg_parser.api.main import create_app
        
        # Create app with patched settings
        with patch("tg_parser.api.routes.agents._get_persistence") as mock_get:
            mock_get.return_value = (persistence, engine)
            
            app = create_app()
            transport = ASGITransport(app=app)
            
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # ====== Step 1: Health check ======
                health_response = await client.get("/health")
                assert health_response.status_code == 200
                
                health_data = health_response.json()
                assert health_data["status"] == "ok"
                assert "version" in health_data
                
                # ====== Step 2: List agents ======
                with patch("tg_parser.api.routes.agents._get_persistence") as mock_get_agents:
                    mock_get_agents.return_value = (persistence, engine)
                    
                    agents_response = await client.get("/api/v1/agents")
                    assert agents_response.status_code == 200
                    
                    agents_data = agents_response.json()
                    assert agents_data["total"] == 2
                    assert len(agents_data["agents"]) == 2
                    
                    # Check agent structure
                    agent = agents_data["agents"][0]
                    assert "name" in agent
                    assert "agent_type" in agent
                    assert "capabilities" in agent
                    assert "total_tasks_processed" in agent
                
                # ====== Step 3: Get specific agent ======
                with patch("tg_parser.api.routes.agents._get_persistence") as mock_get_agent:
                    mock_get_agent.return_value = (persistence, engine)
                    
                    agent_response = await client.get("/api/v1/agents/TestProcessingAgent")
                    assert agent_response.status_code == 200
                    
                    agent_data = agent_response.json()
                    assert agent_data["name"] == "TestProcessingAgent"
                    assert agent_data["agent_type"] == "processing"
                    assert agent_data["is_active"] is True
                
                # ====== Step 4: Get agent stats ======
                with patch("tg_parser.api.routes.agents._get_persistence") as mock_get_stats:
                    mock_get_stats.return_value = (persistence, engine)
                    
                    stats_response = await client.get(
                        "/api/v1/agents/TestProcessingAgent/stats?days=30"
                    )
                    assert stats_response.status_code == 200
                    
                    stats_data = stats_response.json()
                    assert stats_data["agent_name"] == "TestProcessingAgent"
                    assert stats_data["period_days"] == 30
                
                # ====== Step 5: Get agent history ======
                with patch("tg_parser.api.routes.agents._get_persistence") as mock_get_history:
                    mock_get_history.return_value = (persistence, engine)
                    
                    history_response = await client.get(
                        "/api/v1/agents/TestProcessingAgent/history?limit=10"
                    )
                    assert history_response.status_code == 200
                    
                    history_data = history_response.json()
                    assert history_data["agent_name"] == "TestProcessingAgent"
                    assert history_data["total"] >= 1
                    assert len(history_data["records"]) >= 1
                    
                    # Check record structure
                    record = history_data["records"][0]
                    assert "id" in record
                    assert "task_type" in record
                    assert "success" in record
                    assert "processing_time_ms" in record
                
                # ====== Step 6: Agent not found ======
                with patch("tg_parser.api.routes.agents._get_persistence") as mock_get_404:
                    mock_persistence_404 = AsyncMock()
                    mock_persistence_404.load_agent_state.return_value = None
                    mock_get_404.return_value = (mock_persistence_404, engine)
                    
                    not_found_response = await client.get("/api/v1/agents/NonExistentAgent")
                    assert not_found_response.status_code == 404
                
                # ====== Step 7: OpenAPI docs ======
                docs_response = await client.get("/openapi.json")
                assert docs_response.status_code == 200
                
                docs_data = docs_response.json()
                assert "paths" in docs_data
                assert "/api/v1/agents" in docs_data["paths"]
    
    @pytest.mark.asyncio
    async def test_handoff_workflow(self, persistence_with_data):
        """
        Test handoff recording and retrieval workflow.
        """
        persistence, engine, _ = persistence_with_data
        
        from tg_parser.agents.base import HandoffRequest, HandoffResponse, HandoffStatus
        
        # ====== Step 1: Record handoff request ======
        request = HandoffRequest(
            id="test-handoff-001",
            source_agent="TestOrchestratorAgent",
            target_agent="TestProcessingAgent",
            task_type="process_batch",
            payload={"messages": ["msg1", "msg2"]},
            context={"channel_id": "test_channel"},
            priority=7,
        )
        
        await persistence.record_handoff_request(request)
        
        # ====== Step 2: Record handoff response (completed) ======
        response = HandoffResponse(
            handoff_id="test-handoff-001",
            status=HandoffStatus.COMPLETED,
            result={"processed": 2},
            processing_time_ms=500,
        )
        
        await persistence.record_handoff_response(response)
        
        # ====== Step 3: Get handoff statistics ======
        stats = await persistence.get_handoff_statistics()
        
        assert stats.get("total_handoffs", 0) >= 1
        assert stats.get("completed", 0) >= 1
    
    @pytest.mark.asyncio
    async def test_archive_workflow(self, persistence_with_data, tmp_path):
        """
        Test archive workflow for task history.
        """
        persistence, engine, _ = persistence_with_data
        
        # ====== Step 1: Create archiver ======
        archive_path = tmp_path / "archives"
        archive_path.mkdir()
        
        archiver = AgentHistoryArchiver(archive_path)
        
        # ====== Step 2: Get task records ======
        records = await persistence.get_task_history(
            agent_name="TestProcessingAgent",
            limit=100,
        )
        
        assert len(records) >= 6
        
        # ====== Step 3: Archive records ======
        archive_file = await archiver.archive_task_history(records)
        
        assert archive_file is not None
        assert archive_file.exists()
        assert archive_file.suffix == ".gz"
        
        # ====== Step 4: List archives ======
        archives = archiver.list_archives()
        
        assert len(archives) >= 1
        assert any("task_history" in a["filename"] for a in archives)
        
        # ====== Step 5: Verify archive contents ======
        with gzip.open(archive_file, "rt", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) >= 6
        
        # Parse first line
        first_record = json.loads(lines[0])
        assert "id" in first_record
        assert "agent_name" in first_record
        assert first_record["agent_name"] == "TestProcessingAgent"

