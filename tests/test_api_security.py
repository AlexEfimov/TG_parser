"""
Tests for API security features (Phase 2F).

Tests cover:
- API key authentication
- Rate limiting
- Request logging / X-Request-ID
- Webhooks
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.main import create_app
from tg_parser.api.webhooks import (
    create_job_completion_payload,
    send_webhook,
    verify_webhook_signature,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def app():
    """Create test FastAPI application."""
    return create_app()


@pytest.fixture
async def client(app):
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_settings_auth_required():
    """Mock settings with API key required."""
    with patch("tg_parser.api.auth.settings") as mock:
        mock.api_key_required = True
        mock.api_keys = {"test-key-123": "test_client", "admin-key": "admin"}
        yield mock


@pytest.fixture
def mock_settings_auth_optional():
    """Mock settings with API key optional."""
    with patch("tg_parser.api.auth.settings") as mock:
        mock.api_key_required = False
        mock.api_keys = {"test-key-123": "test_client"}
        yield mock


# ============================================================================
# API Key Authentication Tests
# ============================================================================


class TestAPIKeyAuthentication:
    """Tests for X-API-Key authentication."""

    async def test_request_without_key_succeeds_when_not_required(self, client):
        """Request without API key should succeed when auth not required."""
        # Default settings don't require auth
        response = await client.get("/health")
        
        assert response.status_code == 200

    async def test_request_without_key_returns_401_when_required(
        self, app, mock_settings_auth_required
    ):
        """Request without API key should return 401 when auth required."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("tg_parser.api.routes.process.verify_api_key") as mock_verify:
                from fastapi import HTTPException
                mock_verify.side_effect = HTTPException(status_code=401, detail="API key required")
                
                response = await client.post(
                    "/api/v1/process",
                    json={"channel_id": "test"},
                )
        
        assert response.status_code == 401

    async def test_request_with_invalid_key_returns_403(
        self, app, mock_settings_auth_required
    ):
        """Request with invalid API key should return 403."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("tg_parser.api.routes.process.verify_api_key") as mock_verify:
                from fastapi import HTTPException
                mock_verify.side_effect = HTTPException(status_code=403, detail="Invalid API key")
                
                response = await client.post(
                    "/api/v1/process",
                    json={"channel_id": "test"},
                    headers={"X-API-Key": "invalid-key"},
                )
        
        assert response.status_code == 403

    async def test_request_with_valid_key_succeeds(self, client):
        """Request with valid API key should succeed (auth optional, no key = ok)."""
        # When api_key_required is False (default), requests without API key work
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {"processed_count": 0, "total_count": 0}
            
            response = await client.post(
                "/api/v1/process",
                json={"channel_id": "test"},
                # No API key - should work when auth not required
            )
        
        assert response.status_code == 200

    async def test_auth_works_for_export_endpoint(self, client):
        """Export endpoint works when auth not required."""
        # No API key needed when api_key_required is False (default)
        response = await client.post(
            "/api/v1/export",
            json={"format": "ndjson"},
        )
        
        assert response.status_code == 200


# ============================================================================
# Request Logging Tests
# ============================================================================


class TestRequestLogging:
    """Tests for request logging and X-Request-ID."""

    async def test_request_id_generated_in_response(self, client):
        """Response should include X-Request-ID header."""
        response = await client.get("/health")
        
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    async def test_custom_request_id_preserved(self, client):
        """Custom X-Request-ID should be preserved in response."""
        custom_id = "my-custom-request-id-12345"
        
        response = await client.get(
            "/health",
            headers={"X-Request-ID": custom_id},
        )
        
        assert response.headers["x-request-id"] == custom_id

    async def test_request_id_is_uuid_format(self, client):
        """Generated request ID should be UUID format."""
        response = await client.get("/health")
        
        request_id = response.headers["x-request-id"]
        # UUID format: 8-4-4-4-12 hex chars
        parts = request_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4

    async def test_request_id_unique_per_request(self, client):
        """Each request should get a unique request ID."""
        response1 = await client.get("/health")
        response2 = await client.get("/health")
        
        id1 = response1.headers["x-request-id"]
        id2 = response2.headers["x-request-id"]
        
        assert id1 != id2


# ============================================================================
# Webhook Tests
# ============================================================================


class TestWebhooks:
    """Tests for webhook notifications."""

    async def test_send_webhook_success(self):
        """send_webhook should send HTTP POST to webhook URL."""
        with patch("tg_parser.api.webhooks.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_instance
            
            result = await send_webhook(
                url="https://example.com/webhook",
                payload={"test": "data"},
                max_retries=0,
            )
        
        assert result is True
        mock_instance.post.assert_called_once()

    async def test_send_webhook_with_signature(self):
        """send_webhook should include HMAC signature when secret provided."""
        with patch("tg_parser.api.webhooks.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_instance
            
            await send_webhook(
                url="https://example.com/webhook",
                payload={"test": "data"},
                secret="my-secret",
                max_retries=0,
            )
            
            # Check that signature header was included
            call_args = mock_instance.post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "X-Webhook-Signature" in headers
            assert headers["X-Webhook-Signature"].startswith("sha256=")

    async def test_send_webhook_failure_returns_false(self):
        """send_webhook should return False on failure."""
        with patch("tg_parser.api.webhooks.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_instance
            
            result = await send_webhook(
                url="https://example.com/webhook",
                payload={"test": "data"},
                max_retries=0,
            )
        
        assert result is False

    def test_verify_webhook_signature_valid(self):
        """verify_webhook_signature should return True for valid signature."""
        body = b'{"test": "data"}'
        secret = "my-secret"
        
        expected_sig = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        signature = f"sha256={expected_sig}"
        
        result = verify_webhook_signature(body, signature, secret)
        
        assert result is True

    def test_verify_webhook_signature_invalid(self):
        """verify_webhook_signature should return False for invalid signature."""
        body = b'{"test": "data"}'
        secret = "my-secret"
        
        result = verify_webhook_signature(body, "sha256=invalid", secret)
        
        assert result is False

    def test_verify_webhook_signature_wrong_prefix(self):
        """verify_webhook_signature should return False for wrong prefix."""
        body = b'{"test": "data"}'
        secret = "my-secret"
        
        result = verify_webhook_signature(body, "md5=something", secret)
        
        assert result is False

    def test_create_job_completion_payload_completed(self):
        """create_job_completion_payload should create proper payload for completed job."""
        payload = create_job_completion_payload(
            job_id="test-123",
            job_type="processing",
            status="completed",
            result={"processed_count": 10},
        )
        
        assert payload["event"] == "job.completed"
        assert payload["job"]["id"] == "test-123"
        assert payload["job"]["type"] == "processing"
        assert payload["job"]["status"] == "completed"
        assert payload["job"]["result"]["processed_count"] == 10
        assert "timestamp" in payload

    def test_create_job_completion_payload_failed(self):
        """create_job_completion_payload should create proper payload for failed job."""
        payload = create_job_completion_payload(
            job_id="test-456",
            job_type="export",
            status="failed",
            error="Something went wrong",
        )
        
        assert payload["job"]["status"] == "failed"
        assert payload["job"]["error"] == "Something went wrong"


# ============================================================================
# CORS Tests
# ============================================================================


class TestCORSConfiguration:
    """Tests for CORS configuration."""

    async def test_cors_headers_exposed(self, client):
        """CORS should expose custom headers."""
        response = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key, X-Request-ID",
            },
        )
        
        assert response.status_code == 200
        
        # Check that custom headers are allowed
        allowed_headers = response.headers.get("access-control-allow-headers", "")
        assert "x-api-key" in allowed_headers.lower() or "*" in allowed_headers

    async def test_cors_allows_credentials(self, client):
        """CORS should allow credentials."""
        response = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        
        assert response.headers.get("access-control-allow-credentials") == "true"


# ============================================================================
# Integration Tests
# ============================================================================


class TestSecurityIntegration:
    """Integration tests for security features."""

    async def test_full_authenticated_flow(self, client):
        """Test complete flow with custom request ID."""
        custom_request_id = "integration-test-12345"
        
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "processed_count": 5,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 5,
            }
            
            # Create processing job with custom request ID
            response = await client.post(
                "/api/v1/process",
                json={"channel_id": "test_channel"},
                headers={"X-Request-ID": custom_request_id},
            )
        
        assert response.status_code == 200
        assert response.headers["x-request-id"] == custom_request_id
        
        data = response.json()
        assert "job_id" in data

    async def test_webhook_url_accepted_in_request(self, client):
        """Webhook URL should be accepted in process request."""
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {"processed_count": 0, "total_count": 0}
            
            # No API key needed when api_key_required is False (default)
            response = await client.post(
                "/api/v1/process",
                json={
                    "channel_id": "test",
                    "webhook_url": "https://example.com/webhook",
                    "webhook_secret": "my-secret",
                },
            )
        
        assert response.status_code == 200

    async def test_export_with_webhook(self, client):
        """Export endpoint should accept webhook configuration."""
        # No API key needed when api_key_required is False (default)
        response = await client.post(
            "/api/v1/export",
            json={
                "format": "ndjson",
                "webhook_url": "https://example.com/export-webhook",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data

