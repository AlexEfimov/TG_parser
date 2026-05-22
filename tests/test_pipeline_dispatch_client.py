"""
Unit tests for MCP/Bot → tg_parser pipeline dispatch HTTP client (ADR 0007).
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from tg_parser.services.pipeline_dispatch_client import (
    DISPATCH_AUTH_REQUIRED,
    DISPATCH_HTTP_ERROR,
    post_pipeline_trigger,
)


class _CapturingAsyncClient:
    def __init__(self, response: httpx.Response, *, timeout: float):
        self._response = response
        self.timeout = timeout
        self.last_url: str | None = None
        self.last_json: dict | None = None
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def post(self, url: str, *, json: dict, headers: dict[str, str]):
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        return self._response


def _json_response(
    status_code: int, payload: dict, *, headers: dict | None = None
) -> httpx.Response:
    request = httpx.Request("POST", "http://tg_parser:8000/api/v1/pipeline/trigger")
    return httpx.Response(status_code, json=payload, request=request, headers=headers or {})


class TestPostPipelineTrigger:
    async def test_posts_correct_url_body_and_api_key(self):
        response = _json_response(
            200,
            {
                "job_id": "jid-99",
                "created": True,
                "status": "queued",
                "channel_id": "mych",
                "job": "topicization",
            },
        )
        client = _CapturingAsyncClient(response, timeout=30.0)

        with (
            patch("tg_parser.services.pipeline_dispatch_client.settings") as mock_settings,
            patch(
                "tg_parser.services.pipeline_dispatch_client.httpx.AsyncClient",
                return_value=client,
            ),
        ):
            mock_settings.pipeline_dispatch_base_url = "http://tg_parser:8000"
            mock_settings.pipeline_dispatch_timeout_seconds = 30.0
            mock_settings.mcp_auth_enabled = False
            mock_settings.api_key_required = False

            result = await post_pipeline_trigger(
                channel_id="@mych",
                job="topicization",
                force=True,
                api_key="secret-key",
                surface="mcp",
            )

        assert result.triggered is True
        assert result.job_id == "jid-99"
        assert result.job == "topicization"
        assert client.last_url == "http://tg_parser:8000/api/v1/pipeline/trigger"
        assert client.last_json == {
            "channel_id": "mych",
            "job": "topicization",
            "force": True,
        }
        assert client.last_headers is not None
        assert client.last_headers["X-API-Key"] == "secret-key"

    async def test_http_error_returns_dispatch_http_error(self):
        request = httpx.Request("POST", "http://tg_parser:8000/api/v1/pipeline/trigger")

        class _FailingClient:
            def __init__(self, *, timeout: float):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return None

            async def post(self, url: str, *, json: dict, headers: dict[str, str]):
                raise httpx.ConnectError("connection refused", request=request)

        with (
            patch("tg_parser.services.pipeline_dispatch_client.settings") as mock_settings,
            patch(
                "tg_parser.services.pipeline_dispatch_client.httpx.AsyncClient",
                _FailingClient,
            ),
        ):
            mock_settings.pipeline_dispatch_base_url = "http://tg_parser:8000"
            mock_settings.pipeline_dispatch_timeout_seconds = 5.0
            mock_settings.mcp_auth_enabled = False
            mock_settings.api_key_required = False

            result = await post_pipeline_trigger(
                channel_id="ch",
                job="full_pipeline",
                api_key=None,
                surface="bot",
            )

        assert result.triggered is False
        assert result.error_class == DISPATCH_HTTP_ERROR

    async def test_429_maps_to_rate_limited(self):
        response = _json_response(
            429,
            {"detail": "Rate limit exceeded"},
            headers={"Retry-After": "42"},
        )
        client = _CapturingAsyncClient(response, timeout=30.0)

        with (
            patch("tg_parser.services.pipeline_dispatch_client.settings") as mock_settings,
            patch(
                "tg_parser.services.pipeline_dispatch_client.httpx.AsyncClient",
                return_value=client,
            ),
        ):
            mock_settings.pipeline_dispatch_base_url = "http://tg_parser:8000"
            mock_settings.pipeline_dispatch_timeout_seconds = 30.0
            mock_settings.mcp_auth_enabled = False
            mock_settings.api_key_required = False

            result = await post_pipeline_trigger(
                channel_id="ch",
                job="link_topics",
                api_key="k",
                surface="mcp",
            )

        assert result.triggered is False
        assert result.error_class == "RateLimited"
        assert "42" in result.message

    async def test_auth_required_without_api_key_when_mcp_auth_on(self):
        with patch("tg_parser.services.pipeline_dispatch_client.settings") as mock_settings:
            mock_settings.mcp_auth_enabled = True
            mock_settings.api_key_required = True

            result = await post_pipeline_trigger(
                channel_id="ch",
                job="full_pipeline",
                api_key=None,
                surface="mcp",
            )

        assert result.triggered is False
        assert result.error_class == DISPATCH_AUTH_REQUIRED

    async def test_401_maps_to_dispatch_auth_required(self):
        response = _json_response(401, {"detail": "API key required"})
        client = _CapturingAsyncClient(response, timeout=30.0)

        with (
            patch("tg_parser.services.pipeline_dispatch_client.settings") as mock_settings,
            patch(
                "tg_parser.services.pipeline_dispatch_client.httpx.AsyncClient",
                return_value=client,
            ),
        ):
            mock_settings.pipeline_dispatch_base_url = "http://tg_parser:8000"
            mock_settings.pipeline_dispatch_timeout_seconds = 30.0
            mock_settings.mcp_auth_enabled = False
            mock_settings.api_key_required = False

            result = await post_pipeline_trigger(
                channel_id="ch",
                job="full_pipeline",
                api_key="bad",
                surface="mcp",
            )

        assert result.triggered is False
        assert result.error_class == DISPATCH_AUTH_REQUIRED
