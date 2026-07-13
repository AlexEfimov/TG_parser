"""
HTTP tests for RAG routes: POST /api/v1/search and POST /api/v1/ask.

Mocks retrieval_service.search / retrieval_service.answer to avoid
hitting real embeddings or LLM backends.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.main import create_app
from tg_parser.domain.models import ProcessedDocument


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_search_result(source_ref="tg:ch:post:1", score=0.95):
    from tg_parser.services.retrieval_service import SearchResult

    doc = ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id="1",
        channel_id="test_channel",
        processed_at="2025-12-13T10:00:00Z",
        text_clean="Тестовый текст документа для проверки поиска.",
        summary="Краткое резюме",
    )
    return SearchResult(source_ref=source_ref, score=score, document=doc)


class TestSearchEndpoint:
    """POST /api/v1/search"""

    async def test_search_success(self, client):
        results = [
            _make_search_result("tg:ch:post:1", 0.95),
            _make_search_result("tg:ch:post:2", 0.80),
        ]

        with patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as mock:
            mock.return_value = results

            response = await client.post(
                "/api/v1/search",
                json={"query": "тестовый запрос", "limit": 5},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "тестовый запрос"
        assert data["total"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["source_ref"] == "tg:ch:post:1"
        assert data["results"][0]["score"] == 0.95
        assert data["results"][0]["summary"] == "Краткое резюме"

    async def test_search_empty_results(self, client):
        with patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as mock:
            mock.return_value = []

            response = await client.post(
                "/api/v1/search",
                json={"query": "ничего не найдётся"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["results"] == []

    async def test_search_validation_error(self, client):
        response = await client.post("/api/v1/search", json={})
        assert response.status_code == 422

    async def test_search_degraded_false_on_happy_path(self, client):
        """BUG-084 Q2: healthy search exposes degraded=false (additive, backward-compatible)."""
        results = [_make_search_result("tg:ch:post:1", 0.95)]

        with patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as mock:
            mock.return_value = results  # a plain list → no degraded attr → default False

            response = await client.post(
                "/api/v1/search",
                json={"query": "здоровый запрос", "limit": 5},
            )

        assert response.status_code == 200
        assert response.json()["degraded"] is False

    async def test_search_degraded_true_on_embedding_fallback(self, client):
        """BUG-084 Q2: semantic/hybrid → keyword fallback surfaces degraded=true over HTTP."""
        from tg_parser.services.retrieval_service import SearchResults

        results = SearchResults(
            [_make_search_result("tg:ch:post:1", 0.42)], degraded=True
        )

        with patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as mock:
            mock.return_value = results

            response = await client.post(
                "/api/v1/search",
                json={"query": "деградированный запрос", "mode": "semantic"},
            )

        assert response.status_code == 200
        assert response.json()["degraded"] is True


class TestAskEndpoint:
    """POST /api/v1/ask"""

    async def test_ask_success(self, client):
        from tg_parser.services.retrieval_service import AnswerResult

        sources = [_make_search_result("tg:ch:post:1", 0.90)]
        answer_result = AnswerResult(
            answer="Ответ на вопрос на основе контекста.",
            sources=sources,
            model="gpt-4o-mini",
        )

        with patch("tg_parser.services.retrieval_service.answer", new_callable=AsyncMock) as mock:
            mock.return_value = answer_result

            response = await client.post(
                "/api/v1/ask",
                json={"question": "Когда назначают анализ СОЭ?"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Ответ на вопрос на основе контекста."
        assert data["model"] == "gpt-4o-mini"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source_ref"] == "tg:ch:post:1"

    async def test_ask_no_results(self, client):
        from tg_parser.services.retrieval_service import AnswerResult

        answer_result = AnswerResult(
            answer="Не найдено релевантных документов для ответа на вопрос.",
            sources=[],
            model=None,
        )

        with patch("tg_parser.services.retrieval_service.answer", new_callable=AsyncMock) as mock:
            mock.return_value = answer_result

            response = await client.post(
                "/api/v1/ask",
                json={"question": "Непонятный вопрос"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "Не найдено" in data["answer"]
        assert data["sources"] == []
        assert data["model"] is None

    async def test_ask_degraded_false_on_happy_path(self, client):
        """BUG-084 Q2: healthy answer exposes degraded=false."""
        from tg_parser.services.retrieval_service import AnswerResult

        answer_result = AnswerResult(
            answer="Ответ.",
            sources=[_make_search_result("tg:ch:post:1", 0.90)],
            model="gpt-4o-mini",
        )

        with patch("tg_parser.services.retrieval_service.answer", new_callable=AsyncMock) as mock:
            mock.return_value = answer_result

            response = await client.post(
                "/api/v1/ask",
                json={"question": "Здоровый вопрос?"},
            )

        assert response.status_code == 200
        assert response.json()["degraded"] is False

    async def test_ask_degraded_true_on_embedding_fallback(self, client):
        """BUG-084 Q2: answer over a degraded (keyword-fallback) retrieval exposes degraded=true."""
        from tg_parser.services.retrieval_service import AnswerResult

        answer_result = AnswerResult(
            answer="Ответ на основе только keyword-поиска.",
            sources=[_make_search_result("tg:ch:post:1", 0.40)],
            model="gpt-4o-mini",
            degraded=True,
        )

        with patch("tg_parser.services.retrieval_service.answer", new_callable=AsyncMock) as mock:
            mock.return_value = answer_result

            response = await client.post(
                "/api/v1/ask",
                json={"question": "Вопрос при исчерпанной квоте?", "mode": "hybrid"},
            )

        assert response.status_code == 200
        assert response.json()["degraded"] is True
