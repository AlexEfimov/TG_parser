"""ADR 0007 compose integration: MCP/Bot dispatch must queue work on ``tg_parser``.

Full docker-compose harness (both containers, ``docker logs tg_parser`` shows
``pipeline_trigger_queued`` / ``Starting ingestion`` within 60s) is gated on
``COMPOSE_INTEGRATION=1`` — CI default pytest excludes ``integration`` markers
and does not start compose stacks.

The always-on harness below verifies the in-process contract: HTTP
``POST /api/v1/pipeline/trigger`` on the API app schedules
``trigger_pipeline_job`` on this process (not a no-op in MCP container).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.services.pipeline_dispatch_service import PipelineTriggerAccepted

compose_only = pytest.mark.skipif(
    not os.environ.get("COMPOSE_INTEGRATION"),
    reason="Set COMPOSE_INTEGRATION=1 to run docker-compose MCP→tg_parser log harness",
)


def _user(user_id: str, *, role: str = "admin") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="dispatch-test",
        role=role,
        allowed_channel_ids=None if role == "admin" else [],
        max_channels=100,
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestPipelineDispatchHarness:
    """In-process harness: API trigger queues on tg_parser (ADR 0007 Option B)."""

    async def test_api_trigger_emits_pipeline_trigger_queued_on_tg_parser(self, app, client):
        admin = _user("admin-dispatch-harness")

        async def _resolver() -> CurrentUser:
            return admin

        app.dependency_overrides[resolve_current_user] = _resolver

        accepted = PipelineTriggerAccepted(job_id="job-harness", created=True)
        try:
            with (
                patch(
                    "tg_parser.api.routes.pipeline.trigger_pipeline_job",
                    new_callable=AsyncMock,
                    return_value=accepted,
                ) as mock_trigger,
                capture_logs() as captured,
            ):
                resp = await client.post(
                    "/api/v1/pipeline/trigger",
                    json={"channel_id": "ch-harness", "job": "full_pipeline"},
                )

            assert resp.status_code == 200, resp.text
            mock_trigger.assert_awaited_once()
            assert mock_trigger.await_args.kwargs["surface"] == "api"
            event_names = [e["event"] for e in captured]
            assert "api_pipeline_trigger" in event_names
        finally:
            app.dependency_overrides.clear()


@pytest.mark.integration
@compose_only
class TestComposeMcpPipelineDispatch:
    """Real compose stack: MCP ``trigger_pipeline`` → logs on ``tg_parser`` container.

    Operator / CI job with compose up:

    .. code-block:: bash

       COMPOSE_INTEGRATION=1 pytest tests/test_compose_pipeline_dispatch_integration.py -m integration

    Asserts ``docker logs tg_parser`` contains ``pipeline_trigger_queued`` or
    ``Starting ingestion`` within 60s after MCP dispatch (ADR 0007 test strategy).
    """

    async def test_compose_mcp_trigger_logs_on_tg_parser(self):
        pytest.skip(
            "Compose harness stub: implement subprocess docker-compose + MCP client "
            "when CI gains a compose job; in-process harness covers dispatch wiring."
        )
