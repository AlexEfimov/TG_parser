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
import subprocess
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.services.pipeline_dispatch_service import PipelineTriggerAccepted

# BUG-059: env gate kept as a belt-and-braces guard so even an explicit
# ``-m "integration and compose_only"`` selection no-ops when no stack is up.
_requires_compose_env = pytest.mark.skipif(
    not os.environ.get("COMPOSE_INTEGRATION"),
    reason="Set COMPOSE_INTEGRATION=1 to run docker-compose MCP→tg_parser log harness",
)

# Compose target names / endpoints (mirror docker-compose.yml).
_TG_PARSER_CONTAINER = os.environ.get("COMPOSE_TG_PARSER_CONTAINER", "tg_parser")
_MCP_URL = os.environ.get("COMPOSE_MCP_URL", "http://127.0.0.1:8080")
# The conftest forces DB_NAME=tg_parser_test for the in-process suite, so the
# compose DB name is read from a dedicated var (default matches compose).
_COMPOSE_DB_NAME = os.environ.get("COMPOSE_DB_NAME", "tg_parser")
_DISPATCH_PROBE_CHANNEL = "compose_dispatch_probe"


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


def _docker_logs_since(container: str, since_ts: str) -> str:
    """Return combined stdout+stderr of ``docker logs --since`` for ``container``."""
    proc = subprocess.run(
        ["docker", "logs", "--since", since_ts, container],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


def _container_running(container: str) -> bool:
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _seed_active_source(channel_id: str) -> None:
    """Insert (idempotently) an ``active`` source into the compose DB.

    The dispatch service rejects unknown channels BEFORE logging
    ``pipeline_trigger_queued`` (``_resolve_active_source``), so the probe
    channel must exist as an active source for the happy-path dispatch log to
    fire. Reuses the migration-seeded default admin as the owner.
    """
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=_COMPOSE_DB_NAME,
        user=os.environ.get("DB_USER", "tg_parser_user"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            row = cur.fetchone()
            owner_id = row[0] if row else None
            cur.execute(
                """
                INSERT INTO sources (
                    source_id, channel_id, status, include_comments,
                    fail_count, comments_unavailable, created_at, updated_at, owner_id
                )
                VALUES (%s, %s, 'active', false, 0, false,
                        now()::text, now()::text, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    status = 'active', deleted_at = NULL
                """,
                (channel_id, channel_id, owner_id),
            )
    finally:
        conn.close()


async def _mcp_trigger_pipeline(channel_id: str) -> object:
    """Call the MCP ``trigger_pipeline`` tool over streamable-HTTP."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{_MCP_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool("trigger_pipeline", {"channel_id": channel_id})


@pytest.mark.integration
@pytest.mark.compose_only
@_requires_compose_env
class TestComposeMcpPipelineDispatch:
    """Real compose stack: MCP ``trigger_pipeline`` → logs on ``tg_parser`` container.

    Operator / CI job with compose up:

    .. code-block:: bash

       COMPOSE_INTEGRATION=1 pytest tests/test_compose_pipeline_dispatch_integration.py \\
         -m "integration and compose_only"

    Asserts ``docker logs tg_parser`` contains ``pipeline_trigger_queued`` (the
    cross-container dispatch landed on the scheduler host, ADR 0007 Option B)
    within 60s after an MCP ``trigger_pipeline`` dispatch.
    """

    async def test_compose_mcp_trigger_logs_on_tg_parser(self):
        assert _container_running(_TG_PARSER_CONTAINER), (
            f"container {_TG_PARSER_CONTAINER!r} is not running — bring the stack up "
            "(docker compose up -d postgres tg_parser mcp) before COMPOSE_INTEGRATION=1"
        )

        _seed_active_source(_DISPATCH_PROBE_CHANNEL)

        since_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await _mcp_trigger_pipeline(_DISPATCH_PROBE_CHANNEL)
        # The tool call round-tripped through the MCP container to tg_parser.
        assert result is not None

        deadline = time.monotonic() + 60
        logs = ""
        while time.monotonic() < deadline:
            logs = _docker_logs_since(_TG_PARSER_CONTAINER, since_ts)
            if "pipeline_trigger_queued" in logs or "Starting ingestion" in logs:
                break
            time.sleep(2)

        assert ("pipeline_trigger_queued" in logs) or ("Starting ingestion" in logs), (
            "expected the MCP dispatch to surface 'pipeline_trigger_queued' / "
            f"'Starting ingestion' in {_TG_PARSER_CONTAINER} logs within 60s; got:\n{logs[-2000:]}"
        )
        assert _DISPATCH_PROBE_CHANNEL in logs
