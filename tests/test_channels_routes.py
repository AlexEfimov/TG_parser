"""
HTTP tests for Channels API routes: GET /api/v1/channels, /channels/{id}/stats.

Mocks db_context repos and channel_service to avoid hitting real database.
"""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.main import create_app
from tg_parser.storage.ports import Source

pytestmark = pytest.mark.asyncio

NOW = datetime(2025, 12, 13, 12, 0, 0, tzinfo=UTC)


def _make_source(
    channel_id: str = "test_channel",
    status: str = "active",
) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        channel_username=f"@{channel_id}",
        status=status,
        include_comments=True,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


PATCH_INGESTION = "tg_parser.services.db_context.ingestion_state_repo"
PATCH_CHANNEL_STATS = "tg_parser.services.channel_service.get_channel_stats"


def _mock_ingestion_state_repo(sources: list[Source] | None = None):
    """Create a mock context manager for ingestion_state_repo()."""
    sources = sources or []

    state_repo = AsyncMock()
    db = MagicMock()

    state_repo.list_sources.return_value = sources

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx


class TestListChannels:
    """GET /api/v1/channels"""

    async def test_list_channels_empty(self, client):
        ctx = _mock_ingestion_state_repo()
        with patch(PATCH_INGESTION, ctx):
            resp = await client.get("/api/v1/channels")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["channels"] == []

    async def test_list_channels_returns_items(self, client):
        src = _make_source("lab_channel")
        ctx = _mock_ingestion_state_repo(sources=[src])
        with patch(PATCH_INGESTION, ctx):
            resp = await client.get("/api/v1/channels")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        ch = data["channels"][0]
        assert ch["channel_id"] == "lab_channel"
        assert ch["channel_username"] == "@lab_channel"
        assert ch["status"] == "active"
        assert ch["include_comments"] is True


class TestChannelStats:
    """GET /api/v1/channels/{channel_id}/stats"""

    async def test_stats_success(self, client):
        stats = {
            "channel_id": "test_ch",
            "channel_username": "@test_ch",
            "raw_messages": 100,
            "processed_documents": 90,
            "topics_count": 10,
            "covered_documents": 60,
            "coverage_percent": 66.67,
            "embeddings_count": 85,
            "missing_embeddings": 5,
        }
        with patch(
            PATCH_CHANNEL_STATS,
            new_callable=AsyncMock,
            return_value=stats,
        ):
            resp = await client.get("/api/v1/channels/test_ch/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["channel_id"] == "test_ch"
        assert data["raw_messages"] == 100
        assert data["coverage_percent"] == 66.67
        assert data["missing_embeddings"] == 5

    async def test_stats_not_found(self, client):
        with patch(
            PATCH_CHANNEL_STATS,
            new_callable=AsyncMock,
            side_effect=ValueError("Channel not found: nonexistent"),
        ):
            resp = await client.get("/api/v1/channels/nonexistent/stats")

        assert resp.status_code == 404
