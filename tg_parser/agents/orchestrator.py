"""
Orchestrator Agent for Multi-Agent Architecture.

Phase 3A: Coordinates multi-agent workflows and manages handoffs.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from tg_parser.agents.base import (
    AgentCapability,
    AgentInput,
    AgentMetadata,
    AgentOutput,
    AgentType,
    BaseAgent,
    HandoffRequest,
    HandoffResponse,
    HandoffStatus,
)
from tg_parser.agents.registry import AgentRegistry, get_registry

logger = logging.getLogger(__name__)


# ============================================================================
# Workflow Definition
# ============================================================================


class WorkflowStep:
    """A step in an orchestrated workflow."""
    
    def __init__(
        self,
        name: str,
        agent_name: str | None = None,
        agent_type: AgentType | None = None,
        capability: AgentCapability | None = None,
        input_mapping: dict[str, str] | None = None,
        output_mapping: dict[str, str] | None = None,
        optional: bool = False,
    ):
        """
        Initialize a workflow step.
        
        Args:
            name: Step name for identification
            agent_name: Specific agent to use (optional)
            agent_type: Agent type to find if name not provided
            capability: Required capability if type not provided
            input_mapping: Map context keys to agent input keys
            output_mapping: Map agent output keys to context keys
            optional: Whether step failure should stop workflow
        """
        self.name = name
        self.agent_name = agent_name
        self.agent_type = agent_type
        self.capability = capability
        self.input_mapping = input_mapping or {}
        self.output_mapping = output_mapping or {}
        self.optional = optional


class Workflow:
    """Definition of a multi-agent workflow."""
    
    def __init__(
        self,
        name: str,
        steps: list[WorkflowStep],
        description: str = "",
    ):
        """
        Initialize a workflow.
        
        Args:
            name: Workflow name
            steps: List of workflow steps in order
            description: Workflow description
        """
        self.name = name
        self.steps = steps
        self.description = description


# ============================================================================
# Pre-defined Workflows
# ============================================================================


# Standard processing workflow: Process → Topicize → Export
PROCESSING_WORKFLOW = Workflow(
    name="processing",
    description="Standard message processing workflow",
    steps=[
        WorkflowStep(
            name="process",
            agent_type=AgentType.PROCESSING,
            input_mapping={"text": "text"},
            output_mapping={"result": "processed"},
        ),
        WorkflowStep(
            name="topicize",
            agent_type=AgentType.TOPICIZATION,
            input_mapping={"documents": "documents"},
            output_mapping={"topics": "topics"},
            optional=True,
        ),
        WorkflowStep(
            name="export",
            agent_type=AgentType.EXPORT,
            input_mapping={"documents": "documents"},
            output_mapping={"filepath": "output_file"},
            optional=True,
        ),
    ],
)


# ============================================================================
# Orchestrator Agent
# ============================================================================


class OrchestratorAgent(BaseAgent[AgentInput, AgentOutput]):
    """
    Orchestrator agent that coordinates multi-agent workflows.
    
    Responsibilities:
    - Route tasks to appropriate specialized agents
    - Manage handoffs between agents
    - Track workflow progress
    - Aggregate results
    - Handle failures and retries
    """
    
    def __init__(
        self,
        registry: AgentRegistry | None = None,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        max_retries: int = 2,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            registry: Agent registry (uses global if not provided)
            model: LLM model for decision making
            provider: LLM provider
            max_retries: Maximum retries per step
        """
        metadata = AgentMetadata(
            name="OrchestratorAgent",
            agent_type=AgentType.ORCHESTRATOR,
            version="3.0.0",
            description="Coordinates multi-agent workflows",
            capabilities=[AgentCapability.ORCHESTRATION],
            model=model,
            provider=provider,
        )
        super().__init__(metadata)
        
        self._registry = registry
        self.max_retries = max_retries
        self._workflows: dict[str, Workflow] = {
            "processing": PROCESSING_WORKFLOW,
        }
    
    @property
    def registry(self) -> AgentRegistry:
        """Get the agent registry."""
        if self._registry is None:
            self._registry = get_registry()
        return self._registry
    
    async def initialize(self) -> None:
        """Initialize the orchestrator."""
        logger.info(f"Initializing {self.name}...")
        
        # Register self with registry if not already registered
        if self.name not in self.registry:
            self.registry.register(self)
        
        self._is_initialized = True
        logger.info(f"{self.name} initialized successfully")
    
    async def shutdown(self) -> None:
        """Shutdown the orchestrator."""
        logger.info(f"Shutting down {self.name}...")
        self._is_initialized = False
        logger.info(f"{self.name} shut down")
    
    async def process(self, input_data: AgentInput) -> AgentOutput:
        """
        Process an orchestration request.
        
        Expected input format:
        {
            "workflow": "processing",  # Workflow name
            "data": {...},             # Initial data
        }
        
        Or for direct routing:
        {
            "target_agent": "ProcessingAgent",  # Specific agent
            "data": {...},
        }
        
        Args:
            input_data: Orchestration request
            
        Returns:
            AgentOutput with aggregated results
        """
        start_time = datetime.now(UTC)
        
        try:
            # Check for workflow execution
            workflow_name = input_data.options.get("workflow")
            if workflow_name:
                return await self._execute_workflow(
                    workflow_name,
                    input_data,
                    start_time,
                )
            
            # Check for direct agent routing
            target_agent = input_data.options.get("target_agent")
            if target_agent:
                return await self._route_to_agent(
                    target_agent,
                    input_data,
                    start_time,
                )
            
            # Default: execute processing workflow
            return await self._execute_workflow(
                "processing",
                input_data,
                start_time,
            )
            
        except Exception as e:
            logger.error(f"Orchestration failed: {e}", exc_info=True)
            end_time = datetime.now(UTC)
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            return AgentOutput(
                task_id=input_data.task_id,
                success=False,
                error=str(e),
                processing_time_ms=processing_time,
            )
    
    async def _execute_workflow(
        self,
        workflow_name: str,
        input_data: AgentInput,
        start_time: datetime,
    ) -> AgentOutput:
        """
        Execute a named workflow.
        
        Args:
            workflow_name: Name of workflow to execute
            input_data: Initial input data
            start_time: When processing started
            
        Returns:
            AgentOutput with workflow results
        """
        workflow = self._workflows.get(workflow_name)
        if not workflow:
            return AgentOutput(
                task_id=input_data.task_id,
                success=False,
                error=f"Unknown workflow: {workflow_name}",
            )
        
        logger.info(f"Executing workflow: {workflow_name} ({len(workflow.steps)} steps)")
        
        # Workflow context accumulates data between steps
        context = {**input_data.data}
        step_results: list[dict[str, Any]] = []
        
        for step in workflow.steps:
            step_start = datetime.now(UTC)
            
            try:
                # Find agent for this step
                agent = self._find_agent_for_step(step)
                
                if not agent:
                    if step.optional:
                        logger.warning(f"No agent for optional step '{step.name}', skipping")
                        continue
                    else:
                        raise RuntimeError(f"No agent available for step: {step.name}")
                
                # Prepare step input from context
                step_input = self._prepare_step_input(step, context, input_data.task_id)
                
                # Execute step
                step_output = await self._execute_step_with_retry(
                    agent, step_input, step.name
                )
                
                # Record step result
                step_end = datetime.now(UTC)
                step_time = int((step_end - step_start).total_seconds() * 1000)
                
                step_results.append({
                    "step": step.name,
                    "agent": agent.name,
                    "success": step_output.success,
                    "processing_time_ms": step_time,
                    "error": step_output.error,
                })
                
                if not step_output.success:
                    if not step.optional:
                        raise RuntimeError(
                            f"Step '{step.name}' failed: {step_output.error}"
                        )
                    else:
                        logger.warning(
                            f"Optional step '{step.name}' failed: {step_output.error}"
                        )
                        continue
                
                # Update context with step output
                context = self._update_context(step, context, step_output)
                
            except Exception as e:
                if not step.optional:
                    raise
                logger.warning(f"Optional step '{step.name}' failed: {e}")
        
        # Workflow complete
        end_time = datetime.now(UTC)
        processing_time = int((end_time - start_time).total_seconds() * 1000)
        
        return AgentOutput(
            task_id=input_data.task_id,
            success=True,
            result=context,
            metadata={
                "workflow": workflow_name,
                "steps": step_results,
                "orchestrator": self.name,
            },
            processing_time_ms=processing_time,
        )
    
    async def _route_to_agent(
        self,
        agent_name: str,
        input_data: AgentInput,
        start_time: datetime,
    ) -> AgentOutput:
        """
        Route directly to a specific agent.
        
        Args:
            agent_name: Name of target agent
            input_data: Input data
            start_time: When processing started
            
        Returns:
            AgentOutput from target agent
        """
        agent = self.registry.get(agent_name)
        if not agent:
            return AgentOutput(
                task_id=input_data.task_id,
                success=False,
                error=f"Agent not found: {agent_name}",
            )
        
        # Create handoff request
        request = HandoffRequest(
            id=str(uuid4()),
            source_agent=self.name,
            target_agent=agent_name,
            task_type="direct_routing",
            payload=input_data.data,
            context=input_data.context,
        )
        
        # Execute handoff
        response = await agent.handle_handoff(request)
        
        end_time = datetime.now(UTC)
        processing_time = int((end_time - start_time).total_seconds() * 1000)
        
        # Record statistics
        self.registry.record_task_completion(
            agent_name,
            response.processing_time_ms or 0,
            response.status == HandoffStatus.COMPLETED,
        )
        
        return AgentOutput(
            task_id=input_data.task_id,
            success=response.status == HandoffStatus.COMPLETED,
            result=response.result,
            error=response.error,
            metadata={
                "handoff_id": response.handoff_id,
                "target_agent": agent_name,
                "orchestrator": self.name,
            },
            processing_time_ms=processing_time,
        )
    
    def _find_agent_for_step(self, step: WorkflowStep) -> BaseAgent | None:
        """
        Find an appropriate agent for a workflow step.
        
        Args:
            step: Workflow step
            
        Returns:
            Agent instance or None
        """
        # Try specific agent name first
        if step.agent_name:
            return self.registry.get(step.agent_name)
        
        # Try by type
        if step.agent_type:
            agents = self.registry.get_by_type(step.agent_type)
            if agents:
                return agents[0]  # Use first available
        
        # Try by capability
        if step.capability:
            return self.registry.find_best_for_capability(step.capability)
        
        return None
    
    def _prepare_step_input(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
        task_id: str,
    ) -> AgentInput:
        """
        Prepare input for a workflow step.
        
        Args:
            step: Workflow step
            context: Current workflow context
            task_id: Task identifier
            
        Returns:
            AgentInput for the step
        """
        # Apply input mapping
        data = {}
        for context_key, input_key in step.input_mapping.items():
            if context_key in context:
                data[input_key] = context[context_key]
        
        # Include unmapped context data
        for key, value in context.items():
            if key not in data:
                data[key] = value
        
        return AgentInput(
            task_id=f"{task_id}:{step.name}",
            data=data,
            context=context,
        )
    
    def _update_context(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
        output: AgentOutput,
    ) -> dict[str, Any]:
        """
        Update workflow context with step output.
        
        Args:
            step: Completed workflow step
            context: Current context
            output: Step output
            
        Returns:
            Updated context
        """
        new_context = {**context}
        
        # Apply output mapping
        for output_key, context_key in step.output_mapping.items():
            if output_key in output.result:
                new_context[context_key] = output.result[output_key]
        
        # Include unmapped output data
        for key, value in output.result.items():
            if key not in new_context:
                new_context[key] = value
        
        return new_context
    
    async def _execute_step_with_retry(
        self,
        agent: BaseAgent,
        input_data: AgentInput,
        step_name: str,
    ) -> AgentOutput:
        """
        Execute a step with retry logic.
        
        Args:
            agent: Agent to execute
            input_data: Step input
            step_name: Name of the step
            
        Returns:
            AgentOutput from step execution
        """
        last_error: Exception | None = None
        
        for attempt in range(self.max_retries + 1):
            try:
                output = await agent.process(input_data)
                
                if output.success:
                    return output
                
                last_error = RuntimeError(output.error or "Unknown error")
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Step '{step_name}' attempt {attempt + 1} failed: {e}"
                )
            
            if attempt < self.max_retries:
                # Exponential backoff
                await asyncio.sleep(1 * (2 ** attempt))
        
        # All retries failed
        return AgentOutput(
            task_id=input_data.task_id,
            success=False,
            error=str(last_error),
        )
    
    # =========================================================================
    # Workflow Management
    # =========================================================================
    
    def register_workflow(self, workflow: Workflow) -> None:
        """
        Register a custom workflow.
        
        Args:
            workflow: Workflow to register
        """
        self._workflows[workflow.name] = workflow
        logger.info(f"Registered workflow: {workflow.name}")
    
    def get_workflows(self) -> list[str]:
        """Get list of registered workflow names."""
        return list(self._workflows.keys())
    
    # =========================================================================
    # Convenience Methods
    # =========================================================================
    
    async def orchestrate(
        self,
        data: dict[str, Any],
        workflow: str = "processing",
    ) -> dict[str, Any]:
        """
        Convenience method to orchestrate a workflow.
        
        Args:
            data: Input data
            workflow: Workflow name
            
        Returns:
            Workflow results
        """
        input_data = AgentInput(
            task_id=str(uuid4()),
            data=data,
            options={"workflow": workflow},
        )
        
        output = await self.process(input_data)
        
        if not output.success:
            raise RuntimeError(output.error)
        
        return output.result
    
    async def send_to(
        self,
        agent_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Convenience method to send data directly to an agent.
        
        Args:
            agent_name: Target agent name
            data: Data to send
            
        Returns:
            Agent response
        """
        input_data = AgentInput(
            task_id=str(uuid4()),
            data=data,
            options={"target_agent": agent_name},
        )
        
        output = await self.process(input_data)
        
        if not output.success:
            raise RuntimeError(output.error)
        
        return output.result

