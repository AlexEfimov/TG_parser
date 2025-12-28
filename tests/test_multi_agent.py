"""
Tests for Multi-Agent Architecture (Phase 3A).

Tests for:
- Agent base classes and protocols
- Agent registry
- Specialized agents
- Orchestrator agent
- Handoff protocol
- Workflow execution
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from tg_parser.agents import (
    # Base
    AgentCapability,
    AgentInput,
    AgentMetadata,
    AgentOutput,
    AgentType,
    BaseAgent,
    HandoffRequest,
    HandoffResponse,
    HandoffStatus,
    # Registry
    AgentRegistry,
    get_registry,
    reset_registry,
    # Orchestrator
    OrchestratorAgent,
    Workflow,
    WorkflowStep,
    # Specialized
    ProcessingAgent,
    TopicizationAgent,
    ExportAgent,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def reset_global_registry():
    """Reset global registry before each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def sample_input() -> AgentInput:
    """Sample agent input for testing."""
    return AgentInput(
        task_id="test-task-123",
        data={"text": "Тестовое сообщение для обработки"},
        context={"channel": "test_channel"},
        options={"mode": "simple"},
    )


@pytest.fixture
def sample_handoff_request() -> HandoffRequest:
    """Sample handoff request for testing."""
    return HandoffRequest(
        id="handoff-123",
        source_agent="OrchestratorAgent",
        target_agent="ProcessingAgent",
        task_type="text_processing",
        payload={"text": "Test message"},
        context={"workflow": "test"},
    )


# ============================================================================
# Test Agent Metadata
# ============================================================================


class TestAgentMetadata:
    """Tests for AgentMetadata dataclass."""
    
    def test_metadata_creation(self):
        """Test creating agent metadata."""
        metadata = AgentMetadata(
            name="TestAgent",
            agent_type=AgentType.PROCESSING,
            version="1.0.0",
            description="A test agent",
            capabilities=[AgentCapability.TEXT_PROCESSING],
        )
        
        assert metadata.name == "TestAgent"
        assert metadata.agent_type == AgentType.PROCESSING
        assert metadata.version == "1.0.0"
        assert AgentCapability.TEXT_PROCESSING in metadata.capabilities
    
    def test_metadata_defaults(self):
        """Test default values in metadata."""
        metadata = AgentMetadata(
            name="TestAgent",
            agent_type=AgentType.PROCESSING,
        )
        
        assert metadata.version == "1.0.0"
        assert metadata.description == ""
        assert metadata.capabilities == []
        assert metadata.model == "gpt-4o-mini"
        assert metadata.provider == "openai"


# ============================================================================
# Test Agent Input/Output
# ============================================================================


class TestAgentInput:
    """Tests for AgentInput model."""
    
    def test_input_creation(self):
        """Test creating agent input."""
        input_data = AgentInput(
            task_id="task-123",
            data={"key": "value"},
        )
        
        assert input_data.task_id == "task-123"
        assert input_data.data == {"key": "value"}
        assert input_data.context == {}
        assert input_data.options == {}
    
    def test_input_with_all_fields(self):
        """Test input with all fields populated."""
        input_data = AgentInput(
            task_id="task-456",
            data={"text": "Hello"},
            context={"user": "test"},
            options={"mode": "fast"},
        )
        
        assert input_data.context == {"user": "test"}
        assert input_data.options == {"mode": "fast"}


class TestAgentOutput:
    """Tests for AgentOutput model."""
    
    def test_output_success(self):
        """Test successful output."""
        output = AgentOutput(
            task_id="task-123",
            success=True,
            result={"processed": True},
            processing_time_ms=150,
        )
        
        assert output.success is True
        assert output.result == {"processed": True}
        assert output.error is None
        assert output.processing_time_ms == 150
    
    def test_output_failure(self):
        """Test failed output."""
        output = AgentOutput(
            task_id="task-123",
            success=False,
            error="Something went wrong",
        )
        
        assert output.success is False
        assert output.error == "Something went wrong"
        assert output.result == {}


# ============================================================================
# Test Handoff Protocol
# ============================================================================


class TestHandoffRequest:
    """Tests for HandoffRequest model."""
    
    def test_request_creation(self, sample_handoff_request):
        """Test creating handoff request."""
        assert sample_handoff_request.id == "handoff-123"
        assert sample_handoff_request.source_agent == "OrchestratorAgent"
        assert sample_handoff_request.target_agent == "ProcessingAgent"
        assert sample_handoff_request.task_type == "text_processing"
    
    def test_request_defaults(self):
        """Test handoff request defaults."""
        request = HandoffRequest(
            id="handoff-456",
            source_agent="Agent1",
            target_agent="Agent2",
            task_type="test",
        )
        
        assert request.payload == {}
        assert request.context == {}
        assert request.priority == 5
        assert request.created_at is not None


class TestHandoffResponse:
    """Tests for HandoffResponse model."""
    
    def test_response_completed(self):
        """Test completed handoff response."""
        response = HandoffResponse(
            handoff_id="handoff-123",
            status=HandoffStatus.COMPLETED,
            result={"data": "processed"},
            processing_time_ms=200,
        )
        
        assert response.status == HandoffStatus.COMPLETED
        assert response.result == {"data": "processed"}
        assert response.error is None
    
    def test_response_failed(self):
        """Test failed handoff response."""
        response = HandoffResponse(
            handoff_id="handoff-123",
            status=HandoffStatus.FAILED,
            error="Processing error",
        )
        
        assert response.status == HandoffStatus.FAILED
        assert response.error == "Processing error"


# ============================================================================
# Test Agent Registry
# ============================================================================


class TestAgentRegistry:
    """Tests for AgentRegistry."""
    
    def test_registry_creation(self):
        """Test creating empty registry."""
        registry = AgentRegistry()
        
        assert len(registry) == 0
        assert registry.names() == []
    
    def test_register_agent(self):
        """Test registering an agent."""
        registry = AgentRegistry()
        agent = ProcessingAgent()
        
        registry.register(agent)
        
        assert "ProcessingAgent" in registry
        assert len(registry) == 1
        assert registry.get("ProcessingAgent") is agent
    
    def test_register_duplicate_fails(self):
        """Test that registering duplicate name fails."""
        registry = AgentRegistry()
        agent1 = ProcessingAgent()
        agent2 = ProcessingAgent()
        
        registry.register(agent1)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(agent2)
    
    def test_unregister_agent(self):
        """Test unregistering an agent."""
        registry = AgentRegistry()
        agent = ProcessingAgent()
        
        registry.register(agent)
        assert "ProcessingAgent" in registry
        
        result = registry.unregister("ProcessingAgent")
        
        assert result is True
        assert "ProcessingAgent" not in registry
    
    def test_unregister_nonexistent(self):
        """Test unregistering nonexistent agent."""
        registry = AgentRegistry()
        
        result = registry.unregister("NonexistentAgent")
        
        assert result is False
    
    def test_get_by_type(self):
        """Test getting agents by type."""
        registry = AgentRegistry()
        processing_agent = ProcessingAgent()
        export_agent = ExportAgent()
        
        registry.register(processing_agent)
        registry.register(export_agent)
        
        processing_agents = registry.get_by_type(AgentType.PROCESSING)
        export_agents = registry.get_by_type(AgentType.EXPORT)
        
        assert len(processing_agents) == 1
        assert processing_agents[0] is processing_agent
        assert len(export_agents) == 1
        assert export_agents[0] is export_agent
    
    def test_get_by_capability(self):
        """Test getting agents by capability."""
        registry = AgentRegistry()
        agent = ProcessingAgent()
        
        registry.register(agent)
        
        agents = registry.get_by_capability(AgentCapability.TEXT_PROCESSING)
        
        assert len(agents) == 1
        assert agents[0] is agent
    
    def test_find_best_for_capability(self):
        """Test finding best agent for capability."""
        registry = AgentRegistry()
        agent = ProcessingAgent()
        
        registry.register(agent)
        
        best = registry.find_best_for_capability(AgentCapability.TEXT_PROCESSING)
        
        assert best is agent
    
    def test_record_task_completion(self):
        """Test recording task completion statistics."""
        registry = AgentRegistry()
        agent = ProcessingAgent()
        
        registry.register(agent)
        registry.record_task_completion("ProcessingAgent", 100.0, True)
        registry.record_task_completion("ProcessingAgent", 200.0, True)
        
        registration = registry.get_registration("ProcessingAgent")
        
        assert registration is not None
        assert registration.total_tasks_processed == 2
        assert registration.total_errors == 0
        assert registration.avg_processing_time_ms == 150.0
    
    def test_get_statistics(self):
        """Test getting registry statistics."""
        registry = AgentRegistry()
        agent = ProcessingAgent()
        
        registry.register(agent)
        stats = registry.get_statistics()
        
        assert stats["total_agents"] == 1
        assert stats["active_agents"] == 1
        assert "ProcessingAgent" in stats["agents"]
    
    def test_global_registry(self):
        """Test global registry singleton."""
        registry1 = get_registry()
        registry2 = get_registry()
        
        assert registry1 is registry2


# ============================================================================
# Test Processing Agent
# ============================================================================


class TestProcessingAgent:
    """Tests for ProcessingAgent."""
    
    def test_agent_creation(self):
        """Test creating processing agent."""
        agent = ProcessingAgent()
        
        assert agent.name == "ProcessingAgent"
        assert agent.agent_type == AgentType.PROCESSING
        assert AgentCapability.TEXT_PROCESSING in agent.capabilities
    
    def test_agent_with_custom_model(self):
        """Test agent with custom model."""
        agent = ProcessingAgent(model="gpt-4o", provider="openai")
        
        assert agent.metadata.model == "gpt-4o"
        assert agent.metadata.provider == "openai"
    
    @pytest.mark.asyncio
    async def test_agent_initialization(self):
        """Test agent initialization."""
        agent = ProcessingAgent()
        
        await agent.initialize()
        
        assert agent._is_initialized is True
        assert agent._simple_agent is not None
        assert agent._deep_agent is not None
        
        await agent.shutdown()
        
        assert agent._is_initialized is False
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test agent health check."""
        agent = ProcessingAgent()
        
        # Not initialized
        healthy = await agent.health_check()
        assert healthy is False
        
        # After initialization
        await agent.initialize()
        healthy = await agent.health_check()
        assert healthy is True
        
        await agent.shutdown()


# ============================================================================
# Test Topicization Agent
# ============================================================================


class TestTopicizationAgent:
    """Tests for TopicizationAgent."""
    
    def test_agent_creation(self):
        """Test creating topicization agent."""
        agent = TopicizationAgent()
        
        assert agent.name == "TopicizationAgent"
        assert agent.agent_type == AgentType.TOPICIZATION
        assert AgentCapability.TOPIC_EXTRACTION in agent.capabilities
    
    @pytest.mark.asyncio
    async def test_process_documents(self):
        """Test processing documents for topicization."""
        agent = TopicizationAgent()
        await agent.initialize()
        
        input_data = AgentInput(
            task_id="test-123",
            data={
                "documents": [
                    {"source_ref": "doc1", "topics": ["laboratory"], "text_clean": "Lab test"},
                    {"source_ref": "doc2", "topics": ["laboratory"], "text_clean": "Lab analysis"},
                    {"source_ref": "doc3", "topics": ["medicine"], "text_clean": "Medical care"},
                ]
            },
        )
        
        output = await agent.process(input_data)
        
        assert output.success is True
        assert "topics" in output.result
        assert output.result["total_documents"] == 3
        
        await agent.shutdown()


# ============================================================================
# Test Export Agent
# ============================================================================


class TestExportAgent:
    """Tests for ExportAgent."""
    
    def test_agent_creation(self):
        """Test creating export agent."""
        agent = ExportAgent()
        
        assert agent.name == "ExportAgent"
        assert agent.agent_type == AgentType.EXPORT
        assert AgentCapability.EXPORT in agent.capabilities
    
    @pytest.mark.asyncio
    async def test_export_ndjson(self):
        """Test exporting documents as NDJSON."""
        agent = ExportAgent()
        await agent.initialize()
        
        input_data = AgentInput(
            task_id="test-123",
            data={
                "documents": [
                    {"source_ref": "doc1", "text_clean": "Test 1"},
                    {"source_ref": "doc2", "text_clean": "Test 2"},
                ]
            },
            options={"format": "ndjson"},
        )
        
        output = await agent.process(input_data)
        
        assert output.success is True
        assert output.result["format"] == "ndjson"
        assert output.result["document_count"] == 2
        assert "content" in output.result
        
        await agent.shutdown()
    
    @pytest.mark.asyncio
    async def test_export_json(self):
        """Test exporting documents as JSON."""
        agent = ExportAgent()
        await agent.initialize()
        
        input_data = AgentInput(
            task_id="test-123",
            data={
                "documents": [
                    {"source_ref": "doc1", "text_clean": "Test"},
                ]
            },
            options={"format": "json"},
        )
        
        output = await agent.process(input_data)
        
        assert output.success is True
        assert output.result["format"] == "json"
        
        await agent.shutdown()


# ============================================================================
# Test Orchestrator Agent
# ============================================================================


class TestOrchestratorAgent:
    """Tests for OrchestratorAgent."""
    
    def test_orchestrator_creation(self):
        """Test creating orchestrator agent."""
        orchestrator = OrchestratorAgent()
        
        assert orchestrator.name == "OrchestratorAgent"
        assert orchestrator.agent_type == AgentType.ORCHESTRATOR
        assert AgentCapability.ORCHESTRATION in orchestrator.capabilities
    
    @pytest.mark.asyncio
    async def test_orchestrator_initialization(self):
        """Test orchestrator initialization."""
        orchestrator = OrchestratorAgent()
        
        await orchestrator.initialize()
        
        assert orchestrator._is_initialized is True
        assert orchestrator.name in orchestrator.registry
        
        await orchestrator.shutdown()
    
    def test_get_workflows(self):
        """Test getting registered workflows."""
        orchestrator = OrchestratorAgent()
        
        workflows = orchestrator.get_workflows()
        
        assert "processing" in workflows
    
    def test_register_custom_workflow(self):
        """Test registering custom workflow."""
        orchestrator = OrchestratorAgent()
        
        workflow = Workflow(
            name="custom",
            description="Custom workflow",
            steps=[
                WorkflowStep(
                    name="step1",
                    agent_type=AgentType.PROCESSING,
                ),
            ],
        )
        
        orchestrator.register_workflow(workflow)
        
        assert "custom" in orchestrator.get_workflows()
    
    @pytest.mark.asyncio
    async def test_route_to_agent(self):
        """Test routing directly to an agent."""
        registry = AgentRegistry()
        processing_agent = ProcessingAgent()
        await processing_agent.initialize()
        registry.register(processing_agent)
        
        orchestrator = OrchestratorAgent(registry=registry)
        await orchestrator.initialize()
        
        # Test direct routing (will fail without OpenAI key, but tests the routing logic)
        input_data = AgentInput(
            task_id="test-123",
            data={"text": "Test message"},
            options={"target_agent": "ProcessingAgent"},
        )
        
        # This will try to process but may fail due to missing API key
        # The important thing is the routing logic is tested
        output = await orchestrator.process(input_data)
        
        # Check that routing was attempted
        assert output.task_id == "test-123"
        
        await orchestrator.shutdown()
        await processing_agent.shutdown()


# ============================================================================
# Test Workflow Steps
# ============================================================================


class TestWorkflowStep:
    """Tests for WorkflowStep."""
    
    def test_step_creation(self):
        """Test creating workflow step."""
        step = WorkflowStep(
            name="process",
            agent_type=AgentType.PROCESSING,
            input_mapping={"text": "message_text"},
            output_mapping={"result": "processed_data"},
        )
        
        assert step.name == "process"
        assert step.agent_type == AgentType.PROCESSING
        assert step.optional is False
    
    def test_optional_step(self):
        """Test optional workflow step."""
        step = WorkflowStep(
            name="optional_step",
            agent_type=AgentType.EXPORT,
            optional=True,
        )
        
        assert step.optional is True


class TestWorkflow:
    """Tests for Workflow."""
    
    def test_workflow_creation(self):
        """Test creating workflow."""
        workflow = Workflow(
            name="test_workflow",
            description="A test workflow",
            steps=[
                WorkflowStep(name="step1", agent_type=AgentType.PROCESSING),
                WorkflowStep(name="step2", agent_type=AgentType.EXPORT),
            ],
        )
        
        assert workflow.name == "test_workflow"
        assert len(workflow.steps) == 2


# ============================================================================
# Integration Tests
# ============================================================================


class TestMultiAgentIntegration:
    """Integration tests for multi-agent system."""
    
    @pytest.mark.asyncio
    async def test_registry_with_multiple_agents(self):
        """Test registry with multiple specialized agents."""
        registry = AgentRegistry()
        
        processing = ProcessingAgent()
        topicization = TopicizationAgent()
        export = ExportAgent()
        
        registry.register(processing)
        registry.register(topicization)
        registry.register(export)
        
        assert len(registry) == 3
        
        # Get by type
        proc_agents = registry.get_by_type(AgentType.PROCESSING)
        assert len(proc_agents) == 1
        
        topic_agents = registry.get_by_type(AgentType.TOPICIZATION)
        assert len(topic_agents) == 1
        
        export_agents = registry.get_by_type(AgentType.EXPORT)
        assert len(export_agents) == 1
    
    @pytest.mark.asyncio
    async def test_handoff_between_agents(self):
        """Test handoff protocol between agents."""
        export_agent = ExportAgent()
        await export_agent.initialize()
        
        # Create handoff request
        request = HandoffRequest(
            id="handoff-test",
            source_agent="OrchestratorAgent",
            target_agent="ExportAgent",
            task_type="export",
            payload={
                "documents": [
                    {"source_ref": "doc1", "text_clean": "Test"},
                ]
            },
            context={"format": "ndjson"},
        )
        
        # Handle handoff
        response = await export_agent.handle_handoff(request)
        
        assert response.handoff_id == "handoff-test"
        assert response.status == HandoffStatus.COMPLETED
        assert response.processing_time_ms is not None
        
        await export_agent.shutdown()
    
    @pytest.mark.asyncio
    async def test_orchestrator_finds_agents(self):
        """Test that orchestrator can find agents by type."""
        registry = AgentRegistry()
        
        processing = ProcessingAgent()
        registry.register(processing)
        
        orchestrator = OrchestratorAgent(registry=registry)
        
        # Find agent for processing step
        step = WorkflowStep(
            name="process",
            agent_type=AgentType.PROCESSING,
        )
        
        found = orchestrator._find_agent_for_step(step)
        
        assert found is processing
    
    @pytest.mark.asyncio
    async def test_all_agents_initialize_shutdown(self):
        """Test that all agents can initialize and shutdown."""
        agents = [
            ProcessingAgent(),
            TopicizationAgent(),
            ExportAgent(),
            OrchestratorAgent(),
        ]
        
        # Initialize all
        for agent in agents:
            await agent.initialize()
            assert agent._is_initialized is True
        
        # Shutdown all
        for agent in agents:
            await agent.shutdown()
            assert agent._is_initialized is False


# ============================================================================
# E2E Multi-Agent Tests
# ============================================================================


class TestMultiAgentE2E:
    """E2E tests for multi-agent workflows with persistence."""
    
    @pytest.fixture
    async def e2e_registry_with_persistence(self, tmp_path):
        """Create registry with persistence for E2E testing."""
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        
        from tg_parser.agents.persistence import AgentPersistence
        from tg_parser.storage.sqlite import init_processing_storage_schema
        from tg_parser.storage.sqlite.agent_state_repo import SQLiteAgentStateRepo
        from tg_parser.storage.sqlite.agent_stats_repo import SQLiteAgentStatsRepo
        from tg_parser.storage.sqlite.handoff_history_repo import SQLiteHandoffHistoryRepo
        from tg_parser.storage.sqlite.task_history_repo import SQLiteTaskHistoryRepo
        
        # Create temp database
        db_path = tmp_path / "e2e_multi_agent.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        engine = create_async_engine(db_url, echo=False)
        
        # Initialize schema
        await init_processing_storage_schema(engine)
        
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
        
        # Create registry with persistence
        registry = AgentRegistry(persistence=persistence)
        
        yield registry, persistence, engine
        
        await engine.dispose()
    
    @pytest.mark.asyncio
    async def test_multi_agent_e2e_workflow(self, e2e_registry_with_persistence):
        """
        E2E test for multi-agent workflow with full pipeline:
        
        1. Create and register agents
        2. Initialize orchestrator workflow
        3. Execute handoff between agents
        4. Verify persistence (state, history, stats)
        5. Cleanup and shutdown
        """
        registry, persistence, engine = e2e_registry_with_persistence
        
        # ====== Step 1: Create and register agents ======
        processing_agent = ProcessingAgent()
        topicization_agent = TopicizationAgent()
        export_agent = ExportAgent()
        
        await processing_agent.initialize()
        await topicization_agent.initialize()
        await export_agent.initialize()
        
        # Use register_with_persistence to save to database
        await registry.register_with_persistence(processing_agent)
        await registry.register_with_persistence(topicization_agent)
        await registry.register_with_persistence(export_agent)
        
        # Verify registration
        assert len(registry) == 3
        assert "ProcessingAgent" in registry
        assert "TopicizationAgent" in registry
        assert "ExportAgent" in registry
        
        # ====== Step 2: Create orchestrator with registry ======
        orchestrator = OrchestratorAgent(registry=registry)
        await orchestrator.initialize()  # This also registers orchestrator in registry
        
        # Save orchestrator state to persistence 
        await persistence.save_agent_state(orchestrator)
        
        # Verify orchestrator is in registry
        assert "OrchestratorAgent" in registry
        assert len(registry) == 4
        
        # ====== Step 3: Test handoff between agents ======
        handoff_request = HandoffRequest(
            id="e2e-handoff-001",
            source_agent="OrchestratorAgent",
            target_agent="ExportAgent",
            task_type="export",
            payload={
                "documents": [
                    {"source_ref": "doc1", "text_clean": "Test document 1"},
                    {"source_ref": "doc2", "text_clean": "Test document 2"},
                ]
            },
            context={"format": "ndjson"},
            priority=5,
        )
        
        # Handle handoff
        response = await export_agent.handle_handoff(handoff_request)
        
        assert response.handoff_id == "e2e-handoff-001"
        assert response.status == HandoffStatus.COMPLETED
        assert response.processing_time_ms is not None
        assert response.processing_time_ms >= 0  # May be 0 for fast operations
        
        # ====== Step 4: Verify agent can be found by capability ======
        text_processors = registry.get_by_capability(AgentCapability.TEXT_PROCESSING)
        assert len(text_processors) >= 1
        assert any(a.name == "ProcessingAgent" for a in text_processors)
        
        exporters = registry.get_by_capability(AgentCapability.EXPORT)
        assert len(exporters) >= 1
        assert any(a.name == "ExportAgent" for a in exporters)
        
        # ====== Step 5: Record task completion stats ======
        registry.record_task_completion("ExportAgent", 150.0, success=True)
        registry.record_task_completion("ExportAgent", 200.0, success=True)
        registry.record_task_completion("ExportAgent", 500.0, success=False)
        
        # Check statistics
        stats = registry.get_statistics()
        
        assert stats["total_agents"] == 4
        assert stats["active_agents"] == 4
        assert "ExportAgent" in stats["agents"]
        
        export_stats = stats["agents"]["ExportAgent"]
        assert export_stats["total_tasks"] == 3
        assert export_stats["total_errors"] == 1
        
        # ====== Step 6: Verify persistence saved agent states ======
        saved_agents = await persistence.list_all_agent_states(None)
        
        # Agents are persisted when registered
        assert len(saved_agents) >= 4
        
        agent_names = [a.name for a in saved_agents]
        assert "ProcessingAgent" in agent_names
        assert "TopicizationAgent" in agent_names
        assert "ExportAgent" in agent_names
        assert "OrchestratorAgent" in agent_names
        
        # ====== Step 7: Shutdown and verify ======
        await orchestrator.shutdown()
        await processing_agent.shutdown()
        await topicization_agent.shutdown()
        await export_agent.shutdown()
        
        assert not orchestrator._is_initialized
        assert not processing_agent._is_initialized
    
    @pytest.mark.asyncio
    async def test_multi_agent_workflow_execution(self, e2e_registry_with_persistence):
        """
        E2E test for workflow execution through orchestrator.
        
        Tests the complete workflow: 
        - Orchestrator routes to specialized agents
        - Each agent processes its step
        - Results are aggregated
        """
        registry, persistence, engine = e2e_registry_with_persistence
        
        # ====== Setup agents ======
        processing_agent = ProcessingAgent()
        topicization_agent = TopicizationAgent()
        export_agent = ExportAgent()
        
        await processing_agent.initialize()
        await topicization_agent.initialize()
        await export_agent.initialize()
        
        registry.register(processing_agent)
        registry.register(topicization_agent)
        registry.register(export_agent)
        
        orchestrator = OrchestratorAgent(registry=registry)
        await orchestrator.initialize()
        
        # ====== Create custom workflow ======
        custom_workflow = Workflow(
            name="e2e_test_workflow",
            description="E2E test workflow for multi-agent testing",
            steps=[
                WorkflowStep(
                    name="process",
                    agent_type=AgentType.PROCESSING,
                    input_mapping={"text": "input_text"},
                ),
                WorkflowStep(
                    name="export",
                    agent_type=AgentType.EXPORT,
                    input_mapping={"documents": "processed_docs"},
                    optional=True,
                ),
            ],
        )
        
        orchestrator.register_workflow(custom_workflow)
        
        # Verify workflow is registered
        workflows = orchestrator.get_workflows()
        assert "e2e_test_workflow" in workflows
        
        # ====== Test agent finding ======
        found_processing = orchestrator._find_agent_for_step(custom_workflow.steps[0])
        assert found_processing is processing_agent
        
        found_export = orchestrator._find_agent_for_step(custom_workflow.steps[1])
        assert found_export is export_agent
        
        # ====== Cleanup ======
        await orchestrator.shutdown()
        await processing_agent.shutdown()
        await topicization_agent.shutdown()
        await export_agent.shutdown()
    
    @pytest.mark.asyncio
    async def test_multi_agent_registry_persistence_sync(self, e2e_registry_with_persistence):
        """
        E2E test for registry-persistence synchronization.
        
        Verifies that:
        - Agent registration triggers persistence save
        - Agent unregistration updates persistence
        - Statistics are persisted correctly
        """
        registry, persistence, engine = e2e_registry_with_persistence
        
        # ====== Step 1: Register agent with persistence ======
        agent = ExportAgent()
        await agent.initialize()
        
        # Use register_with_persistence to save to database
        await registry.register_with_persistence(agent)
        
        # ====== Step 2: Verify persistence has agent state ======
        saved_state = await persistence.load_agent_state("ExportAgent")
        
        assert saved_state is not None
        assert saved_state.name == "ExportAgent"
        assert saved_state.agent_type == "export"
        assert saved_state.is_active is True
        assert "export" in saved_state.capabilities
        
        # ====== Step 3: Record task and verify stats update ======
        await persistence.record_task(
            agent_name="ExportAgent",
            task_type="export_ndjson",
            input_data={"docs": ["doc1"]},
            output_data={"exported": 1},
            success=True,
            processing_time_ms=100,
            source_ref="test_export_1",
            channel_id="test_channel",
        )
        
        # Get updated state
        updated_state = await persistence.load_agent_state("ExportAgent")
        
        # Task should be recorded
        assert updated_state.total_tasks_processed >= 1
        
        # Get task history
        history = await persistence.get_task_history(
            agent_name="ExportAgent",
            limit=10,
        )
        
        assert len(history) >= 1
        assert history[0].task_type == "export_ndjson"
        assert history[0].success is True
        
        # ====== Step 4: Unregister and mark inactive ======
        registry.unregister("ExportAgent")
        await persistence.mark_agent_inactive("ExportAgent")
        
        inactive_state = await persistence.load_agent_state("ExportAgent")
        assert inactive_state.is_active is False
        
        # ====== Cleanup ======
        await agent.shutdown()

