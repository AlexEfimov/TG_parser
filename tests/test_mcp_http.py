"""
Tests for MCP Streamable HTTP transport and bearer-token auth (D1).

Covers:
- BearerTokenVerifier: valid/invalid/empty token verification
- create_mcp_server: factory produces FastMCP with correct settings
- HTTP transport: JSON-RPC initialize via streamable_http_app()
- Auth enforcement: 401 without token, 200 with valid token
"""

from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from tg_parser.mcp_server import BearerTokenVerifier, create_mcp_server

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_server(*, auth: bool = False) -> FastMCP:
    """Create a minimal FastMCP for HTTP tests (no DB lifespan)."""
    kwargs: dict = dict(
        name="test-server",
        host="127.0.0.1",
        port=9999,
        stateless_http=True,
        json_response=True,
    )
    if auth:
        kwargs["token_verifier"] = BearerTokenVerifier({"tok-valid": "test-client"})
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl("http://127.0.0.1:9999"),
            resource_server_url=AnyHttpUrl("http://127.0.0.1:9999"),
        )
    return FastMCP(**kwargs)


_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    },
}

_BASE_URL = "http://127.0.0.1:9999"

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# TestBearerTokenVerifier
# ---------------------------------------------------------------------------


class TestBearerTokenVerifier:
    """D1c: verify_token returns AccessToken for known tokens, None otherwise."""

    async def test_valid_token_returns_access_token(self):
        verifier = BearerTokenVerifier({"secret-123": "my-client"})
        result = await verifier.verify_token("secret-123")

        assert result is not None
        assert result.token == "secret-123"
        assert result.client_id == "my-client"
        assert result.scopes == []

    async def test_invalid_token_returns_none(self):
        verifier = BearerTokenVerifier({"secret-123": "my-client"})
        result = await verifier.verify_token("wrong-token")

        assert result is None

    async def test_empty_tokens_dict_returns_none(self):
        verifier = BearerTokenVerifier({})
        result = await verifier.verify_token("any-token")

        assert result is None

    async def test_multiple_tokens(self):
        tokens = {"tok-a": "client-a", "tok-b": "client-b"}
        verifier = BearerTokenVerifier(tokens)

        result_a = await verifier.verify_token("tok-a")
        result_b = await verifier.verify_token("tok-b")

        assert result_a is not None and result_a.client_id == "client-a"
        assert result_b is not None and result_b.client_id == "client-b"


# ---------------------------------------------------------------------------
# TestCreateMcpServer
# ---------------------------------------------------------------------------


class TestCreateMcpServer:
    """D1d: factory function produces FastMCP with correct settings."""

    def test_default_settings(self):
        """Factory returns FastMCP with settings-driven host/port."""
        server = create_mcp_server()
        assert isinstance(server, FastMCP)
        assert server.settings.stateless_http is True
        assert server.settings.json_response is True
        assert server.settings.lifespan is not None

    def test_auth_disabled_by_default(self):
        """When mcp_auth_enabled=False, no token_verifier is set."""
        server = create_mcp_server()
        assert server._token_verifier is None

    def test_auth_enabled_creates_verifier(self):
        """When auth is enabled with tokens, factory creates BearerTokenVerifier."""
        from tg_parser.config import settings

        with (
            patch.object(settings, "mcp_auth_enabled", True),
            patch.object(settings, "mcp_auth_tokens", {"test-token": "test-client"}),
        ):
            server = create_mcp_server()

        assert server._token_verifier is not None
        assert isinstance(server._token_verifier, BearerTokenVerifier)

    def test_auth_enabled_without_tokens_skips_verifier(self):
        """When auth is enabled but tokens dict is empty, no verifier is set."""
        from tg_parser.config import settings

        with (
            patch.object(settings, "mcp_auth_enabled", True),
            patch.object(settings, "mcp_auth_tokens", {}),
        ):
            server = create_mcp_server()

        assert server._token_verifier is None


# ---------------------------------------------------------------------------
# TestMcpHttpTransport
# ---------------------------------------------------------------------------


class TestMcpHttpTransport:
    """D1f: Streamable HTTP transport serves JSON-RPC over /mcp."""

    async def test_initialize_returns_jsonrpc_response(self):
        """POST /mcp with initialize should return a valid JSON-RPC response."""
        server = _make_test_server(auth=False)
        app = server.streamable_http_app()

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.post("/mcp", json=_INITIALIZE_BODY, headers=_JSON_HEADERS)

            assert resp.status_code == 200
            data = resp.json()
            assert data.get("jsonrpc") == "2.0"
            assert data.get("id") == 1
            result = data.get("result", {})
            assert "protocolVersion" in result
            assert "capabilities" in result
            assert "serverInfo" in result

    async def test_get_without_sse_accept_rejected(self):
        """GET /mcp without text/event-stream Accept should be rejected."""
        server = _make_test_server(auth=False)
        app = server.streamable_http_app()

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.get("/mcp", headers={"Accept": "application/json"})

            assert resp.status_code in (405, 406)


# ---------------------------------------------------------------------------
# TestMcpHttpAuth
# ---------------------------------------------------------------------------


class TestMcpHttpAuth:
    """D1f: Auth-enabled MCP rejects unauthenticated requests."""

    async def test_no_token_returns_401(self):
        """POST /mcp without bearer token should return 401."""
        server = _make_test_server(auth=True)
        app = server.streamable_http_app()

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.post("/mcp", json=_INITIALIZE_BODY, headers=_JSON_HEADERS)

            assert resp.status_code == 401

    async def test_invalid_token_returns_401(self):
        """POST /mcp with invalid bearer token should return 401."""
        server = _make_test_server(auth=True)
        app = server.streamable_http_app()

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.post(
                    "/mcp",
                    json=_INITIALIZE_BODY,
                    headers={**_JSON_HEADERS, "Authorization": "Bearer wrong-token"},
                )

            assert resp.status_code == 401

    async def test_valid_token_returns_200(self):
        """POST /mcp with valid bearer token should succeed."""
        server = _make_test_server(auth=True)
        app = server.streamable_http_app()

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.post(
                    "/mcp",
                    json=_INITIALIZE_BODY,
                    headers={**_JSON_HEADERS, "Authorization": "Bearer tok-valid"},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data.get("jsonrpc") == "2.0"
            assert "result" in data
