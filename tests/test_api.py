"""
Tests for HTTP API endpoints.

Tests cover:
- Health check endpoints
- Processing endpoints (with mocked pipeline)
- Export endpoints
- Error handling
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from tg_parser.api.main import create_app
from tg_parser.api.schemas import JobStatus


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


# ============================================================================
# Health Endpoints Tests
# ============================================================================


class TestHealthEndpoints:
    """Tests for /health and /status endpoints."""

    async def test_health_check_returns_ok(self, client):
        """GET /health should return status ok."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "timestamp" in data

    async def test_health_check_timestamp_is_valid(self, client):
        """GET /health timestamp should be valid ISO format."""
        response = await client.get("/health")
        
        data = response.json()
        # Should parse without error
        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        assert timestamp is not None

    async def test_status_returns_components(self, client):
        """GET /status should return component status."""
        response = await client.get("/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "components" in data
        assert "api" in data["components"]
        assert data["components"]["api"] == "ok"

    async def test_status_returns_stats(self, client):
        """GET /status should return statistics."""
        response = await client.get("/status")
        
        data = response.json()
        assert "stats" in data
        assert "raw_messages" in data["stats"]
        assert "processed_documents" in data["stats"]


# ============================================================================
# Process Endpoints Tests
# ============================================================================


class TestProcessEndpoints:
    """Tests for /api/v1/process endpoints."""

    async def test_start_processing_creates_job(self, client):
        """POST /api/v1/process should create a job."""
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "processed_count": 10,
                "skipped_count": 5,
                "failed_count": 0,
                "total_count": 15,
            }
            
            response = await client.post(
                "/api/v1/process",
                json={"channel_id": "test_channel", "concurrency": 3}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["channel_id"] == "test_channel"
        assert "created_at" in data

    async def test_start_processing_with_all_options(self, client):
        """POST /api/v1/process should accept all options."""
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {"processed_count": 0, "total_count": 0}
            
            response = await client.post(
                "/api/v1/process",
                json={
                    "channel_id": "my_channel",
                    "force": True,
                    "retry_failed": False,
                    "provider": "openai",
                    "model": "gpt-4o",
                    "concurrency": 5,
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["channel_id"] == "my_channel"

    async def test_start_processing_validates_concurrency(self, client):
        """POST /api/v1/process should validate concurrency range."""
        # Concurrency > 20 should fail validation
        response = await client.post(
            "/api/v1/process",
            json={"channel_id": "test", "concurrency": 100}
        )
        
        assert response.status_code == 422  # Validation error

    async def test_start_processing_requires_channel_id(self, client):
        """POST /api/v1/process requires channel_id."""
        response = await client.post(
            "/api/v1/process",
            json={}
        )
        
        assert response.status_code == 422

    async def test_get_job_status_not_found(self, client):
        """GET /api/v1/status/{job_id} should return 404 for unknown job."""
        response = await client.get("/api/v1/status/unknown-job-id")
        
        assert response.status_code == 404

    async def test_get_job_status_after_creation(self, client):
        """GET /api/v1/status/{job_id} should return job after creation."""
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {"processed_count": 0, "total_count": 0}
            
            # Create job
            create_response = await client.post(
                "/api/v1/process",
                json={"channel_id": "test_channel"}
            )
            job_id = create_response.json()["job_id"]
            
            # Get status
            status_response = await client.get(f"/api/v1/status/{job_id}")
        
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["job_id"] == job_id
        assert data["channel_id"] == "test_channel"

    async def test_list_jobs_empty(self, app):
        """GET /api/v1/jobs should return empty list initially."""
        # Create fresh client to avoid jobs from other tests
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Clear jobs storage
            from tg_parser.api.routes import process
            process._jobs.clear()
            
            response = await client.get("/api/v1/jobs")
        
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_jobs_with_status_filter(self, client):
        """GET /api/v1/jobs should accept status filter parameter."""
        # Test that the endpoint accepts the status filter parameter
        # (actual filtering depends on job state which is timing-dependent)
        response = await client.get("/api/v1/jobs?status=pending")
        
        assert response.status_code == 200
        jobs = response.json()
        assert isinstance(jobs, list)
        
        # Also test with completed status
        response = await client.get("/api/v1/jobs?status=completed")
        assert response.status_code == 200
        
        # Invalid status should still work (FastAPI enum validation)
        response = await client.get("/api/v1/jobs?status=invalid")
        assert response.status_code == 422  # Validation error for invalid enum


# ============================================================================
# Export Endpoints Tests
# ============================================================================


class TestExportEndpoints:
    """Tests for /api/v1/export endpoints."""

    async def test_start_export_creates_job(self, client):
        """POST /api/v1/export should create an export job."""
        response = await client.post(
            "/api/v1/export",
            json={"format": "ndjson"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["format"] == "ndjson"

    async def test_start_export_with_channel_filter(self, client):
        """POST /api/v1/export should accept channel filter."""
        response = await client.post(
            "/api/v1/export",
            json={
                "channel_id": "my_channel",
                "format": "json",
                "include_topics": True,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"

    async def test_export_status_not_found(self, client):
        """GET /api/v1/export/status/{job_id} should return 404."""
        response = await client.get("/api/v1/export/status/unknown-id")
        
        assert response.status_code == 404

    async def test_export_download_not_ready(self, client):
        """GET /api/v1/export/download/{job_id} should fail if not ready."""
        # Create export job
        create_response = await client.post(
            "/api/v1/export",
            json={"format": "ndjson"}
        )
        job_id = create_response.json()["job_id"]
        
        # Try to download immediately (still pending)
        download_response = await client.get(f"/api/v1/export/download/{job_id}")
        
        # Should fail because not completed
        assert download_response.status_code == 400


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    async def test_invalid_json_returns_422(self, client):
        """Invalid JSON should return 422."""
        response = await client.post(
            "/api/v1/process",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 422

    async def test_wrong_content_type(self, client):
        """Wrong content type should be handled."""
        response = await client.post(
            "/api/v1/process",
            content="channel_id=test",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        assert response.status_code == 422

    async def test_method_not_allowed(self, client):
        """Wrong HTTP method should return 405."""
        response = await client.delete("/health")
        
        assert response.status_code == 405


# ============================================================================
# OpenAPI / Documentation Tests
# ============================================================================


class TestDocumentation:
    """Tests for API documentation."""

    async def test_openapi_json_available(self, client):
        """GET /openapi.json should return OpenAPI spec."""
        response = await client.get("/openapi.json")
        
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert data["info"]["title"] == "TG_parser API"

    async def test_docs_redirect(self, client):
        """GET /docs should be available."""
        response = await client.get("/docs")
        
        # 200 OK or redirect
        assert response.status_code in [200, 307]

    async def test_redoc_available(self, client):
        """GET /redoc should be available."""
        response = await client.get("/redoc")
        
        assert response.status_code in [200, 307]


# ============================================================================
# CORS Tests
# ============================================================================


class TestCORS:
    """Tests for CORS headers."""

    async def test_cors_headers_present(self, client):
        """CORS headers should be present."""
        response = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            }
        )
        
        # CORS preflight should succeed
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for API flows."""

    async def test_full_processing_flow(self, client):
        """Test complete processing flow: create -> status -> complete."""
        with patch("tg_parser.api.routes.process.run_processing", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "processed_count": 10,
                "skipped_count": 2,
                "failed_count": 1,
                "total_count": 13,
            }
            
            # 1. Create job
            create_response = await client.post(
                "/api/v1/process",
                json={"channel_id": "integration_test"}
            )
            assert create_response.status_code == 200
            job_id = create_response.json()["job_id"]
            
            # 2. Check status (initially pending)
            status_response = await client.get(f"/api/v1/status/{job_id}")
            assert status_response.status_code == 200
            
            # 3. Verify job in list
            list_response = await client.get("/api/v1/jobs")
            assert list_response.status_code == 200
            jobs = list_response.json()
            assert any(j["job_id"] == job_id for j in jobs)

