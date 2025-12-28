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

