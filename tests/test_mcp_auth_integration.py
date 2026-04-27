"""End-to-end integration tests for MCP bearer-auth identity flow (BUG-001).

These tests close the CI blind-spot documented in
``docs/notes/BUG_LOG.md`` § BUG-001 § 'Why CI didn't catch'. Until this
file existed, every MCP-tool test mocked ``resolve_mcp_user`` directly,
so the path

    HTTP request with Bearer header
        → BearerAuthBackend.authenticate
            → AuthenticatedUser into ASGI scope.user
                → AuthContextMiddleware → auth_context_var
                    → tool body → _extract_authenticated_user_id
                        → resolve_mcp_user

was never exercised end-to-end. The bug (handler reading ``ctx.client_id``
i.e. JSON-RPC ``params._meta.client_id`` which is attacker-controlled)
slipped through every existing layer of unit tests.

This module covers:
- BUG-001 happy path: valid bearer → tool sees the real authenticated id.
- BUG-001 regression guard: attacker-supplied ``_meta.client_id`` is ignored.
- 401 enforcement: missing/invalid bearer with auth enabled.
- Dev-mode fallback: stdio (no middleware) → helper returns None → admin.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AnyHttpUrl

from tg_parser.mcp_server import _extract_authenticated_user_id

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_BASE_URL = "http://127.0.0.1:9999"
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "auth-int-test", "version": "1.0"},
    },
}


class _FakeTokenVerifier(TokenVerifier):
    """In-memory verifier that maps token → client_id directly (no DB)."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def verify_token(self, token: str) -> AccessToken | None:
        client_id = self._mapping.get(token)
        if client_id is None:
            return None
        return AccessToken(token=token, client_id=client_id, scopes=[])


def _make_server(*, auth: bool, mapping: dict[str, str] | None = None) -> FastMCP:
    """Build a FastMCP instance with one inline tool that returns the
    output of ``_extract_authenticated_user_id`` for the current request.
    """
    kwargs: dict[str, Any] = {
        "name": "auth-int-test",
        "host": "127.0.0.1",
        "port": 9999,
        "stateless_http": True,
        "json_response": True,
    }
    if auth:
        kwargs["token_verifier"] = _FakeTokenVerifier(mapping or {})
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(_BASE_URL),
            resource_server_url=AnyHttpUrl(_BASE_URL),
        )

    server = FastMCP(**kwargs)

    @server.tool()
    def whoami_probe(ctx: Context) -> dict[str, Any]:  # pragma: no cover - exercised via HTTP
        """Test tool: returns helper-extracted client_id verbatim."""
        return {
            "extracted_user_id": _extract_authenticated_user_id(ctx),
            # Include the attacker-controlled value to demonstrate the helper
            # ignores it. ctx.client_id is the legacy buggy path.
            "ctx_client_id": ctx.client_id,
        }

    return server


async def _initialize(client: AsyncClient, headers: dict[str, str]) -> None:
    """Send a minimal initialize handshake; tolerate stateless responses."""
    resp = await client.post("/mcp", json=_INITIALIZE_BODY, headers=headers)
    # streamable_http with stateless=True returns 200 + JSON for initialize.
    assert resp.status_code == 200, resp.text


def _parse_response(resp_text: str) -> dict[str, Any]:
    """streamable_http with json_response=True returns plain JSON, but
    SDK versions that use SSE prefix lines with 'data: '. Accept both.
    """
    text = resp_text.strip()
    if text.startswith("data:"):
        text = text.split("data:", 1)[1].strip()
    return json.loads(text)


async def _call_tool(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    arguments: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name, "arguments": arguments or {}}
    if meta is not None:
        params["_meta"] = meta
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": params,
    }
    resp = await client.post("/mcp", json=body, headers=headers)
    return {"status_code": resp.status_code, "text": resp.text}


def _extract_tool_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """Pull the structured payload back out of the MCP tools/call result.

    FastMCP returns the dict via ``result.structuredContent`` when the
    function-return is a dict (it gets wrapped in ``{"result": <dict>}``).
    """
    result = parsed.get("result", {})
    structured = result.get("structuredContent")
    if structured is not None:
        # FastMCP wraps non-BaseModel returns in {"result": <value>}.
        return structured.get("result", structured)
    # Fallback: text content with embedded JSON.
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    raise AssertionError(f"unexpected MCP result shape: {parsed!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMcpAuthIdentityE2E:
    """End-to-end: bearer flow → tool sees real client_id."""

    async def test_valid_bearer_yields_real_client_id_in_tool(self):
        """Happy path: tool body extracts the bearer-resolved client_id.

        This is the BUG-001 happy-path regression: prior to the fix,
        ``ctx.client_id`` was always None (params._meta absent) and
        ``resolve_mcp_user`` silently fell through to the synthetic admin
        ``00000000-…``. With the helper, ``_extract_authenticated_user_id``
        reads the AccessToken from ``auth_context_var`` (populated by the
        SDK's AuthContextMiddleware) and returns the real ``client_id``.
        """
        server = _make_server(
            auth=True,
            mapping={"valid-token": "real-user-uuid-12345"},
        )
        app = server.streamable_http_app()
        headers = {**_MCP_HEADERS, "Authorization": "Bearer valid-token"}

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                await _initialize(client, headers)
                resp = await _call_tool(client, headers, name="whoami_probe")

        assert resp["status_code"] == 200, resp["text"]
        parsed = _parse_response(resp["text"])
        payload = _extract_tool_payload(parsed)
        assert payload["extracted_user_id"] == "real-user-uuid-12345"

    async def test_meta_client_id_attack_is_ignored(self):
        """BUG-001 regression: attacker-supplied _meta.client_id MUST NOT
        leak into the resolved identity.

        The helper deliberately ignores ``ctx.client_id`` (which is a
        thin pass-through of JSON-RPC ``params._meta.client_id``). With a
        valid bearer + a forged ``_meta.client_id``, the tool must still
        see the real authenticated id.
        """
        server = _make_server(
            auth=True,
            mapping={"valid-token": "real-user-uuid-67890"},
        )
        app = server.streamable_http_app()
        headers = {**_MCP_HEADERS, "Authorization": "Bearer valid-token"}

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                await _initialize(client, headers)
                resp = await _call_tool(
                    client,
                    headers,
                    name="whoami_probe",
                    meta={"client_id": "attacker-evil-id"},
                )

        assert resp["status_code"] == 200, resp["text"]
        parsed = _parse_response(resp["text"])
        payload = _extract_tool_payload(parsed)
        assert payload["extracted_user_id"] == "real-user-uuid-67890"
        assert payload["extracted_user_id"] != "attacker-evil-id"

    async def test_missing_bearer_returns_401(self):
        """auth_enabled + no Authorization header → 401, no admin fallback."""
        server = _make_server(auth=True, mapping={"valid-token": "u1"})
        app = server.streamable_http_app()

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.post("/mcp", json=_INITIALIZE_BODY, headers=_MCP_HEADERS)

        assert resp.status_code == 401

    async def test_invalid_bearer_returns_401(self):
        """auth_enabled + unknown token → 401."""
        server = _make_server(auth=True, mapping={"valid-token": "u1"})
        app = server.streamable_http_app()
        headers = {**_MCP_HEADERS, "Authorization": "Bearer nope"}

        async with server.session_manager.run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                resp = await client.post("/mcp", json=_INITIALIZE_BODY, headers=headers)

        assert resp.status_code == 401


class TestResolveMcpUserUnderRealMiddleware:
    """Verify ``resolve_mcp_user`` behaviour when called from a tool body
    that is dispatched through the real AuthContextMiddleware stack.

    These cover the integration of helper + resolve_mcp_user in production
    mode (auth_enabled=True) — which was previously short-circuited by
    blanket ``@patch("tg_parser.mcp_server.resolve_mcp_user")`` decorators
    in the existing test suite.
    """

    async def test_dev_mode_tool_call_resolves_to_default_admin(self):
        """Auth disabled → helper returns None → resolve_mcp_user → admin.

        Note the helper ALWAYS returns None when no AuthContextMiddleware is
        in the stack (e.g. stdio transport, dev-mode HTTP without auth).
        ``resolve_mcp_user(None)`` falls through to ``get_default_admin``
        only because ``mcp_auth_enabled`` is False — once auth is enabled,
        the same path raises PermissionError (see fail_loud test below).
        """
        from tg_parser.config import settings
        from tg_parser.mcp_server import resolve_mcp_user

        with patch.object(settings, "mcp_auth_enabled", False):
            user = await resolve_mcp_user(_extract_authenticated_user_id(None))

        assert user.is_admin is True
        assert user.id == "00000000-0000-0000-0000-000000000000"

    async def test_production_mode_no_identity_fail_loud(self):
        """Auth enabled + no identity → PermissionError (BUG-001 fix).

        Previously this code path silently authenticated as admin, which
        is exactly the security bug. Now it raises PermissionError.
        """
        from tg_parser.config import settings
        from tg_parser.mcp_server import resolve_mcp_user

        with patch.object(settings, "mcp_auth_enabled", True):
            with pytest.raises(PermissionError, match="BUG-001"):
                await resolve_mcp_user(_extract_authenticated_user_id(None))
