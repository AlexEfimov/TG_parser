"""
Tests for Agent State Persistence (Phase 3B).

Tests cover:
- AgentStateRepo
- TaskHistoryRepo  
- AgentStatsRepo
- HandoffHistoryRepo
- AgentPersistence integration
- Registry with persistence
"""

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.storage.ports import (
    AgentState,
    TaskRecord,
    AgentDailyStats,
    HandoffRecord,
    AgentStateRepo,
    TaskHistoryRepo,
    AgentStatsRepo,
    HandoffHistoryRepo,
)
from tg_parser.storage.sqlite.agent_state_repo import SQLiteAgentStateRepo
from tg_parser.storage.sqlite.task_history_repo import SQLiteTaskHistoryRepo
from tg_parser.storage.sqlite.agent_stats_repo import SQLiteAgentStatsRepo
from tg_parser.storage.sqlite.handoff_history_repo import SQLiteHandoffHistoryRepo
from tg_parser.agents.persistence import AgentPersistence
from tg_parser.agents.base import (
    AgentCapability,
    AgentMetadata,
    AgentType,
    BaseAgent,
    AgentInput,
    AgentOutput,
    HandoffRequest,
    HandoffResponse,
    HandoffStatus,
)
from tg_parser.agents.registry import AgentRegistry, reset_registry


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_session_factory():
    """Create a mock session factory for testing."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    
    def factory():
        return session
    
    return factory, session


@pytest.fixture
def sample_agent_state():
    """Create a sample agent state."""
    return AgentState(
        name="TestAgent",
        agent_type="processing",
        version="1.0.0",
        description="Test agent for unit tests",
        capabilities=["text_processing", "summarization"],
        model="gpt-4o-mini",
        provider="openai",
        is_active=True,
        metadata={"custom": "value"},
        total_tasks_processed=100,
        total_errors=5,
        avg_processing_time_ms=150.5,
        last_used_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_task_record():
    """Create a sample task record."""
    return TaskRecord(
        id="task_abc123",
        agent_name="ProcessingAgent",
        task_type="process_message",
        input_data={"text": "Hello world", "source_ref": "tg_test_post_1"},
        output_data={"summary": "Greeting", "topics": ["hello"]},
        source_ref="tg_test_post_1",
        channel_id="test_channel",
        success=True,
        processing_time_ms=100,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=14),
    )


@pytest.fixture
def sample_handoff_record():
    """Create a sample handoff record."""
    return HandoffRecord(
        id="handoff_xyz789",
        source_agent="OrchestratorAgent",
        target_agent="ProcessingAgent",
        task_type="process_batch",
        status="completed",
        priority=7,
        payload={"messages": ["msg1", "msg2"]},
        context={"channel_id": "test"},
        result={"processed": 2},
        processing_time_ms=500,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


class MockAgent(BaseAgent[AgentInput, AgentOutput]):
    """Mock agent for testing."""
    
    def __init__(self, name: str = "MockAgent"):
        metadata = AgentMetadata(
            name=name,
            agent_type=AgentType.PROCESSING,
            capabilities=[AgentCapability.TEXT_PROCESSING],
            model="gpt-4o-mini",
            provider="openai",
        )
        super().__init__(metadata)
    
    async def initialize(self) -> None:
        self._is_initialized = True
    
    async def process(self, input_data: AgentInput) -> AgentOutput:
        return AgentOutput(
            task_id=input_data.task_id,
            success=True,
            result={"processed": True},
        )
    
    async def shutdown(self) -> None:
        self._is_initialized = False


# ============================================================================
# AgentState Model Tests
# ============================================================================


class TestAgentStateModel:
    """Tests for AgentState dataclass."""
    
    def test_agent_state_creation(self, sample_agent_state):
        """Test creating an AgentState."""
        state = sample_agent_state
        
        assert state.name == "TestAgent"
        assert state.agent_type == "processing"
        assert state.version == "1.0.0"
        assert "text_processing" in state.capabilities
        assert state.total_tasks_processed == 100
        assert state.total_errors == 5
    
    def test_agent_state_defaults(self):
        """Test AgentState default values."""
        state = AgentState(
            name="MinimalAgent",
            agent_type="export",
        )
        
        assert state.version == "1.0.0"
        assert state.description == ""
        assert state.capabilities == []
        assert state.is_active is True
        assert state.total_tasks_processed == 0
        assert state.total_errors == 0
        assert state.avg_processing_time_ms == 0.0


# ============================================================================
# TaskRecord Model Tests
# ============================================================================


class TestTaskRecordModel:
    """Tests for TaskRecord dataclass."""
    
    def test_task_record_creation(self, sample_task_record):
        """Test creating a TaskRecord."""
        record = sample_task_record
        
        assert record.id == "task_abc123"
        assert record.agent_name == "ProcessingAgent"
        assert record.success is True
        assert "text" in record.input_data
        assert "summary" in record.output_data
    
    def test_task_record_defaults(self):
        """Test TaskRecord default values."""
        record = TaskRecord(
            id="task_123",
            agent_name="Agent",
            task_type="test",
            input_data={"key": "value"},
        )
        
        assert record.output_data is None
        assert record.success is True
        assert record.error is None
        assert record.expires_at is None


# ============================================================================
# AgentDailyStats Model Tests
# ============================================================================


class TestAgentDailyStatsModel:
    """Tests for AgentDailyStats dataclass."""
    
    def test_daily_stats_avg_processing_time(self):
        """Test average processing time calculation."""
        stats = AgentDailyStats(
            agent_name="Agent",
            date="2025-12-28",
            task_type="process",
            total_tasks=100,
            total_processing_time_ms=15000,
        )
        
        assert stats.avg_processing_time_ms == 150.0
    
    def test_daily_stats_success_rate(self):
        """Test success rate calculation."""
        stats = AgentDailyStats(
            agent_name="Agent",
            date="2025-12-28",
            task_type="process",
            total_tasks=100,
            successful_tasks=95,
            failed_tasks=5,
        )
        
        assert stats.success_rate == 0.95
    
    def test_daily_stats_zero_tasks(self):
        """Test calculations with zero tasks."""
        stats = AgentDailyStats(
            agent_name="Agent",
            date="2025-12-28",
            task_type="process",
            total_tasks=0,
        )
        
        assert stats.avg_processing_time_ms == 0.0
        assert stats.success_rate == 0.0


# ============================================================================
# HandoffRecord Model Tests
# ============================================================================


class TestHandoffRecordModel:
    """Tests for HandoffRecord dataclass."""
    
    def test_handoff_record_creation(self, sample_handoff_record):
        """Test creating a HandoffRecord."""
        record = sample_handoff_record
        
        assert record.id == "handoff_xyz789"
        assert record.source_agent == "OrchestratorAgent"
        assert record.target_agent == "ProcessingAgent"
        assert record.status == "completed"
        assert record.priority == 7


# ============================================================================
# AgentPersistence Integration Tests
# ============================================================================


class TestAgentPersistence:
    """Tests for AgentPersistence class."""
    
    def test_persistence_is_enabled_none(self):
        """Test is_enabled when no repos provided."""
        persistence = AgentPersistence()
        assert persistence.is_enabled is False
    
    def test_persistence_is_enabled_with_repos(self):
        """Test is_enabled when repos provided."""
        mock_repo = AsyncMock(spec=AgentStateRepo)
        persistence = AgentPersistence(agent_state_repo=mock_repo)
        assert persistence.is_enabled is True
    
    @pytest.mark.asyncio
    async def test_save_agent_state(self):
        """Test saving agent state."""
        mock_repo = AsyncMock(spec=AgentStateRepo)
        persistence = AgentPersistence(agent_state_repo=mock_repo)
        
        agent = MockAgent("TestAgent")
        await persistence.save_agent_state(agent)
        
        mock_repo.save.assert_called_once()
        saved_state = mock_repo.save.call_args[0][0]
        assert saved_state.name == "TestAgent"
        assert saved_state.agent_type == "processing"
    
    @pytest.mark.asyncio
    async def test_save_agent_state_no_repo(self):
        """Test saving without repo does nothing."""
        persistence = AgentPersistence()
        agent = MockAgent()
        
        # Should not raise
        await persistence.save_agent_state(agent)
    
    @pytest.mark.asyncio
    async def test_record_task(self):
        """Test recording a task."""
        mock_task_repo = AsyncMock(spec=TaskHistoryRepo)
        mock_task_repo.record.return_value = "task_123"
        
        mock_stats_repo = AsyncMock(spec=AgentStatsRepo)
        mock_state_repo = AsyncMock(spec=AgentStateRepo)
        
        persistence = AgentPersistence(
            task_history_repo=mock_task_repo,
            agent_stats_repo=mock_stats_repo,
            agent_state_repo=mock_state_repo,
            stats_enabled=True,
        )
        
        task_id = await persistence.record_task(
            agent_name="ProcessingAgent",
            task_type="process_message",
            input_data={"text": "Hello"},
            output_data={"summary": "Greeting"},
            success=True,
            processing_time_ms=100,
        )
        
        assert task_id == "task_123"
        mock_task_repo.record.assert_called_once()
        mock_stats_repo.record.assert_called_once()
        mock_state_repo.update_statistics.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_record_handoff_request(self):
        """Test recording a handoff request."""
        mock_repo = AsyncMock(spec=HandoffHistoryRepo)
        persistence = AgentPersistence(handoff_history_repo=mock_repo)
        
        request = HandoffRequest(
            id="handoff_123",
            source_agent="Orchestrator",
            target_agent="Processor",
            task_type="process",
            payload={"data": "test"},
        )
        
        await persistence.record_handoff_request(request)
        
        mock_repo.record.assert_called_once()
        call_kwargs = mock_repo.record.call_args[1]
        assert call_kwargs["handoff_id"] == "handoff_123"
        assert call_kwargs["source_agent"] == "Orchestrator"
    
    @pytest.mark.asyncio
    async def test_record_handoff_response(self):
        """Test recording a handoff response."""
        mock_repo = AsyncMock(spec=HandoffHistoryRepo)
        persistence = AgentPersistence(handoff_history_repo=mock_repo)
        
        response = HandoffResponse(
            handoff_id="handoff_123",
            status=HandoffStatus.COMPLETED,
            result={"processed": True},
            processing_time_ms=150,
        )
        
        await persistence.record_handoff_response(response)
        
        mock_repo.update_status.assert_called_once()
        call_kwargs = mock_repo.update_status.call_args[1]
        assert call_kwargs["handoff_id"] == "handoff_123"
        assert call_kwargs["status"] == "completed"
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_tasks(self):
        """Test cleaning up expired tasks."""
        mock_repo = AsyncMock(spec=TaskHistoryRepo)
        mock_repo.cleanup_expired.return_value = 10
        
        persistence = AgentPersistence(task_history_repo=mock_repo)
        
        deleted = await persistence.cleanup_expired_tasks()
        
        assert deleted == 10
        mock_repo.cleanup_expired.assert_called_once()


# ============================================================================
# Registry with Persistence Tests
# ============================================================================


class TestRegistryWithPersistence:
    """Tests for AgentRegistry with persistence."""
    
    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()
    
    def teardown_method(self):
        """Reset registry after each test."""
        reset_registry()
    
    def test_registry_with_persistence_init(self):
        """Test creating registry with persistence."""
        mock_persistence = MagicMock(spec=AgentPersistence)
        registry = AgentRegistry(persistence=mock_persistence)
        
        assert registry._persistence is mock_persistence
    
    @pytest.mark.asyncio
    async def test_register_with_persistence(self):
        """Test registering agent with persistence."""
        mock_persistence = AsyncMock(spec=AgentPersistence)
        mock_persistence.restore_agent_statistics.return_value = {
            "total_tasks_processed": 50,
            "total_errors": 2,
            "avg_processing_time_ms": 100.0,
            "last_used_at": datetime.now(UTC),
        }
        
        registry = AgentRegistry(persistence=mock_persistence)
        agent = MockAgent("TestAgent")
        
        await registry.register_with_persistence(agent)
        
        # Check agent is registered
        assert "TestAgent" in registry
        
        # Check persistence was called
        mock_persistence.save_agent_state.assert_called_once()
        mock_persistence.restore_agent_statistics.assert_called_once()
        
        # Check stats were restored
        registration = registry.get_registration("TestAgent")
        assert registration.total_tasks_processed == 50
        assert registration.total_errors == 2
    
    @pytest.mark.asyncio
    async def test_unregister_with_persistence(self):
        """Test unregistering agent with persistence."""
        mock_persistence = AsyncMock(spec=AgentPersistence)
        
        registry = AgentRegistry(persistence=mock_persistence)
        agent = MockAgent("TestAgent")
        registry.register(agent)
        
        result = await registry.unregister_with_persistence("TestAgent")
        
        assert result is True
        assert "TestAgent" not in registry
        mock_persistence.mark_agent_inactive.assert_called_once_with("TestAgent")
    
    @pytest.mark.asyncio
    async def test_record_task_completion_with_persistence(self):
        """Test recording task with persistence."""
        mock_persistence = AsyncMock(spec=AgentPersistence)
        mock_persistence.record_task.return_value = "task_456"
        
        registry = AgentRegistry(persistence=mock_persistence)
        agent = MockAgent("TestAgent")
        registry.register(agent)
        
        task_id = await registry.record_task_completion_with_persistence(
            name="TestAgent",
            task_type="process",
            input_data={"text": "test"},
            output_data={"result": "ok"},
            processing_time_ms=100.0,
            success=True,
        )
        
        assert task_id == "task_456"
        
        # Check in-memory stats updated
        registration = registry.get_registration("TestAgent")
        assert registration.total_tasks_processed == 1
        
        # Check persistence called
        mock_persistence.record_task.assert_called_once()


# ============================================================================
# SQLite Repository Tests (with mock session)
# ============================================================================


class TestSQLiteAgentStateRepo:
    """Tests for SQLiteAgentStateRepo."""
    
    @pytest.mark.asyncio
    async def test_state_to_row_conversion(self, mock_session_factory, sample_agent_state):
        """Test converting AgentState to row dict."""
        factory, session = mock_session_factory
        repo = SQLiteAgentStateRepo(factory)
        
        row = repo._state_to_row(sample_agent_state)
        
        assert row["name"] == "TestAgent"
        assert row["agent_type"] == "processing"
        assert row["is_active"] == 1
        assert "text_processing" in row["capabilities_json"]


class TestSQLiteTaskHistoryRepo:
    """Tests for SQLiteTaskHistoryRepo."""
    
    @pytest.mark.asyncio
    async def test_record_to_row_conversion(self, mock_session_factory, sample_task_record):
        """Test converting TaskRecord to row dict."""
        factory, session = mock_session_factory
        repo = SQLiteTaskHistoryRepo(factory)
        
        row = repo._record_to_row(sample_task_record)
        
        assert row["id"] == "task_abc123"
        assert row["agent_name"] == "ProcessingAgent"
        assert row["success"] == 1
        assert "text" in row["input_json"]


class TestSQLiteHandoffHistoryRepo:
    """Tests for SQLiteHandoffHistoryRepo."""
    
    @pytest.mark.asyncio
    async def test_record_creates_pending_handoff(self, mock_session_factory):
        """Test that recording creates pending handoff."""
        factory, session = mock_session_factory
        repo = SQLiteHandoffHistoryRepo(factory)
        
        await repo.record(
            source_agent="Source",
            target_agent="Target",
            task_type="process",
            handoff_id="handoff_test",
            priority=5,
            payload={"data": "test"},
        )
        
        session.execute.assert_called()
        session.commit.assert_called()


# ============================================================================
# Retention and Cleanup Tests
# ============================================================================


class TestRetentionAndCleanup:
    """Tests for retention policy and cleanup."""
    
    def test_task_record_expires_at_calculation(self):
        """Test that expires_at is calculated correctly."""
        now = datetime.now(UTC)
        retention_days = 14
        
        record = TaskRecord(
            id="task_test",
            agent_name="Agent",
            task_type="test",
            input_data={},
            created_at=now,
            expires_at=now + timedelta(days=retention_days),
        )
        
        expected_expiry = now + timedelta(days=retention_days)
        assert abs((record.expires_at - expected_expiry).total_seconds()) < 1
    
    @pytest.mark.asyncio
    async def test_persistence_cleanup_calls_repo(self):
        """Test that cleanup delegates to repo."""
        mock_repo = AsyncMock(spec=TaskHistoryRepo)
        mock_repo.cleanup_expired.return_value = 5
        
        persistence = AgentPersistence(task_history_repo=mock_repo)
        
        deleted = await persistence.cleanup_expired_tasks()
        
        assert deleted == 5
        mock_repo.cleanup_expired.assert_called_once()

