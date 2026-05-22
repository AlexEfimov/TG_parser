"""
MCP pipeline dispatch proxy tests (Wave 1 step 3.1 / ADR 0007).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import tg_parser.mcp_server as mcp_server_module
from tg_parser.mcp_server import (
    TriggerPipelineResult,
    trigger_link_topics,
    trigger_pipeline,
    trigger_topicization,
)
from tg_parser.services.pipeline_dispatch_client import (
    DISPATCH_HTTP_ERROR,
    PipelineDispatchClientResult,
)


class TestMcpPipelineDispatchProxy:
    async def test_trigger_pipeline_dispatches_via_http(self):
        dispatch = PipelineDispatchClientResult(
            channel_id="ch",
            triggered=True,
            message="queued",
            job_id="jid-1",
            job="full_pipeline",
        )
        with (
            patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                new_callable=AsyncMock,
            ) as mock_user,
            patch(
                "tg_parser.mcp_server._extract_authenticated_user_id",
                return_value="user-1",
            ),
            patch(
                "tg_parser.auth.ownership.assert_channel_access",
                new_callable=AsyncMock,
            ),
            patch(
                "tg_parser.services.pipeline_dispatch_client.extract_mcp_dispatch_api_key",
                return_value="bearer-tok",
            ),
            patch(
                "tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger",
                new_callable=AsyncMock,
                return_value=dispatch,
            ) as mock_post,
        ):
            mock_user.return_value = object()
            result = await trigger_pipeline("ch", force=True)

        assert isinstance(result, TriggerPipelineResult)
        assert result.triggered is True
        assert result.job_id == "jid-1"
        mock_post.assert_awaited_once()
        assert mock_post.await_args.kwargs["api_key"] == "bearer-tok"
        assert mock_post.await_args.kwargs["job"] == "full_pipeline"

    async def test_trigger_pipeline_http_failure_not_success_lie(self):
        dispatch = PipelineDispatchClientResult(
            channel_id="ch",
            triggered=False,
            message="connection refused",
            error_class=DISPATCH_HTTP_ERROR,
            job="full_pipeline",
        )
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", new_callable=AsyncMock),
            patch("tg_parser.mcp_server._extract_authenticated_user_id", return_value=None),
            patch("tg_parser.auth.ownership.assert_channel_access", new_callable=AsyncMock),
            patch(
                "tg_parser.services.pipeline_dispatch_client.extract_mcp_dispatch_api_key",
                return_value=None,
            ),
            patch(
                "tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger",
                new_callable=AsyncMock,
                return_value=dispatch,
            ),
        ):
            result = await trigger_pipeline("ch")

        assert result.triggered is False
        assert result.error_class == DISPATCH_HTTP_ERROR

    async def test_trigger_topicization_job_kind(self):
        dispatch = PipelineDispatchClientResult(
            channel_id="ch",
            triggered=True,
            message="ok",
            job="topicization",
        )
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", new_callable=AsyncMock),
            patch("tg_parser.mcp_server._extract_authenticated_user_id", return_value=None),
            patch("tg_parser.auth.ownership.assert_channel_access", new_callable=AsyncMock),
            patch(
                "tg_parser.services.pipeline_dispatch_client.extract_mcp_dispatch_api_key",
                return_value="tok",
            ),
            patch(
                "tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger",
                new_callable=AsyncMock,
                return_value=dispatch,
            ) as mock_post,
        ):
            result = await trigger_topicization("ch")

        assert result.triggered is True
        assert mock_post.await_args.kwargs["job"] == "topicization"

    async def test_trigger_link_topics_job_kind(self):
        dispatch = PipelineDispatchClientResult(
            channel_id="ch",
            triggered=True,
            message="ok",
            job="link_topics",
        )
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", new_callable=AsyncMock),
            patch("tg_parser.mcp_server._extract_authenticated_user_id", return_value=None),
            patch("tg_parser.auth.ownership.assert_channel_access", new_callable=AsyncMock),
            patch(
                "tg_parser.services.pipeline_dispatch_client.extract_mcp_dispatch_api_key",
                return_value="tok",
            ),
            patch(
                "tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger",
                new_callable=AsyncMock,
                return_value=dispatch,
            ) as mock_post,
        ):
            result = await trigger_link_topics("ch")

        assert result.triggered is True
        assert mock_post.await_args.kwargs["job"] == "link_topics"
        assert mock_post.await_args.kwargs["force"] is False


class TestMcpNoInProcessPipelineRunner:
    def test_mcp_server_has_no_in_process_run_pipeline_background(self):
        assert not hasattr(mcp_server_module, "_run_pipeline_background")
