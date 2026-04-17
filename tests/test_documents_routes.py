"""
HTTP tests for Documents API routes: GET /api/v1/documents?source_ref=...

Mocks processing_repos() to avoid hitting real database.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.main import create_app
from tg_parser.domain.models import ProcessedDocument

NOW = datetime(2025, 12, 13, 12, 0, 0, tzinfo=UTC)


def _make_doc(source_ref: str = "tg:ch:post:1") -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id="1",
        channel_id="ch",
        processed_at=NOW,
        text_clean="Clean text content.",
        summary="Summary of the document.",
        topics=["topic1", "topic2"],
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


PATCH_TARGET = "tg_parser.services.db_context.processing_repos"


def _mock_processing_repos(docs: dict[str, ProcessedDocument] | None = None):
    """Create a mock context manager for processing_repos()."""
    docs = docs or {}

    proc_repo = AsyncMock()
    topic_card_repo = MagicMock()
    topic_bundle_repo = MagicMock()
    db = MagicMock()

    async def get_by_ref(ref):
        return docs.get(ref)
    proc_repo.get_by_source_ref.side_effect = get_by_ref

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_ctx():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

    return mock_ctx


class TestGetDocument:
    """GET /api/v1/documents?source_ref=..."""

    async def test_get_document_success(self, client):
        doc = _make_doc("tg:ch:post:1")
        ctx = _mock_processing_repos(docs={"tg:ch:post:1": doc})
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/documents", params={"source_ref": "tg:ch:post:1"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "doc:tg:ch:post:1"
        assert data["source_ref"] == "tg:ch:post:1"
        assert data["channel_id"] == "ch"
        assert data["text_clean"] == "Clean text content."
        assert data["summary"] == "Summary of the document."
        assert data["topics"] == ["topic1", "topic2"]
        assert data["message_type"] == "post"

    async def test_get_document_not_found(self, client):
        ctx = _mock_processing_repos()
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/documents", params={"source_ref": "tg:ch:post:999"})

        assert resp.status_code == 404

    async def test_get_document_missing_source_ref(self, client):
        resp = await client.get("/api/v1/documents")
        assert resp.status_code == 422
