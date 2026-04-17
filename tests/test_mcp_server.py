"""
Tests for MCP Server tools (P6b).

Each MCP tool is tested as an async function. DB context managers are mocked
using the same pattern as test_topics_routes.py.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    ProcessedDocument,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.mcp_server import (
    AnswerResultItem,
    ChannelSummary,
    DocumentDetail,
    SearchResultItem,
    TopicDetail,
    TopicListResult,
    TopicSummary,
    ask_question,
    get_document,
    get_topic_details,
    list_channels,
    list_topics,
    search_knowledge_base,
)
from tg_parser.services.retrieval_service import AnswerResult, SearchResult
from tg_parser.storage.ports import Source

NOW = datetime(2025, 12, 13, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_processed_doc(
    source_ref: str = "tg:ch:post:1",
    channel_id: str = "ch",
    text: str = "Clean text content for testing",
    summary: str | None = "A short summary",
) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id="1",
        channel_id=channel_id,
        processed_at=NOW,
        text_clean=text,
        summary=summary,
        topics=["topic1"],
    )


def _make_topic_card(
    topic_id: str = "topic:tg:ch:post:1",
    title: str = "Test Topic",
    topic_type: TopicType = TopicType.SINGLETON,
    sources: list[str] | None = None,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary="Test summary",
        scope_in=["scope in"],
        scope_out=["scope out"],
        type=topic_type,
        anchors=[
            Anchor(
                channel_id="ch",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:ch:post:1",
                score=1.0,
            )
        ],
        sources=sources or ["ch"],
        updated_at=NOW,
    )


def _make_bundle(topic_id: str = "topic:tg:ch:post:1") -> TopicBundle:
    return TopicBundle(
        topic_id=topic_id,
        items=[
            BundleItem(
                channel_id="ch",
                message_id="1",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:1",
                role=BundleItemRole.ANCHOR,
            ),
            BundleItem(
                channel_id="ch",
                message_id="2",
                message_type=MessageType.COMMENT,
                source_ref="tg:ch:comment:2",
                role=BundleItemRole.SUPPORTING,
            ),
        ],
        updated_at=NOW,
    )


def _make_source(
    channel_id: str = "ch",
    status: str = "active",
    channel_username: str | None = "test_channel",
) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status=status,
        include_comments=True,
        channel_username=channel_username,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_processing_repos(
    topic_cards: list[TopicCard] | None = None,
    bundles: dict[str, TopicBundle] | None = None,
    processed_docs: list[ProcessedDocument] | None = None,
):
    topic_cards = topic_cards or []
    bundles = bundles or {}
    processed_docs = processed_docs or []

    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    db = MagicMock()

    topic_card_repo.list_all.return_value = topic_cards
    topic_card_repo.list_by_channel.return_value = topic_cards

    async def get_card_by_id(tid):
        return next((c for c in topic_cards if c.id == tid), None)
    topic_card_repo.get_by_id.side_effect = get_card_by_id

    async def get_bundle(tid):
        return bundles.get(tid)
    topic_bundle_repo.get_by_topic_id.side_effect = get_bundle
    topic_bundle_repo.list_by_channel.return_value = list(bundles.values())
    topic_bundle_repo.list_all.return_value = list(bundles.values())

    async def get_doc_by_ref(ref):
        return next((d for d in processed_docs if d.source_ref == ref), None)
    proc_repo.get_by_source_ref.side_effect = get_doc_by_ref

    @asynccontextmanager
    async def mock_ctx():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

    return mock_ctx


def _mock_ingestion_state_repo(sources: list[Source] | None = None):
    sources = sources or []
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.list_sources.return_value = sources

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx


PROC_PATCH = "tg_parser.services.db_context.processing_repos"
INGEST_STATE_PATCH = "tg_parser.services.db_context.ingestion_state_repo"
SEARCH_PATCH = "tg_parser.services.retrieval_service.search"
ANSWER_PATCH = "tg_parser.services.retrieval_service.answer"
BATCH_STATS_PATCH = "tg_parser.services.channel_service.get_all_channel_stats"


# ===========================================================================
# T2: Search & Ask tools
# ===========================================================================


class TestSearchTool:

    async def test_search_returns_results(self):
        doc = _make_processed_doc()
        mock_results = [
            SearchResult(source_ref="tg:ch:post:1", score=0.95, document=doc),
            SearchResult(source_ref="tg:ch:post:2", score=0.82, document=None),
        ]
        with patch(SEARCH_PATCH, return_value=mock_results) as mock_search:
            result = await search_knowledge_base("test query", limit=5)

        mock_search.assert_awaited_once_with(query="test query", channel_id=None, limit=5, allowed_channel_ids=None)
        assert len(result) == 2
        assert isinstance(result[0], SearchResultItem)
        assert result[0].source_ref == "tg:ch:post:1"
        assert result[0].score == 0.95
        assert result[0].summary == "A short summary"
        assert result[0].text_preview is not None
        assert result[0].channel_id == "ch"
        assert result[1].summary is None

    async def test_search_with_channel_filter(self):
        with patch(SEARCH_PATCH, return_value=[]) as mock_search:
            result = await search_knowledge_base("query", channel_id="my_ch")

        mock_search.assert_awaited_once_with(query="query", channel_id="my_ch", limit=10, allowed_channel_ids=None)
        assert result == []

    async def test_search_empty(self):
        with patch(SEARCH_PATCH, return_value=[]):
            result = await search_knowledge_base("nothing")

        assert result == []


class TestAskTool:

    async def test_ask_returns_answer(self):
        doc = _make_processed_doc()
        mock_answer = AnswerResult(
            answer="The answer is 42.",
            sources=[SearchResult(source_ref="tg:ch:post:1", score=0.9, document=doc)],
            model="gpt-4o-mini",
        )
        with patch(ANSWER_PATCH, return_value=mock_answer) as mock_fn:
            result = await ask_question("What is the answer?")

        mock_fn.assert_awaited_once_with(question="What is the answer?", channel_id=None, allowed_channel_ids=None)
        assert isinstance(result, AnswerResultItem)
        assert result.answer == "The answer is 42."
        assert result.model == "gpt-4o-mini"
        assert len(result.sources) == 1
        assert result.sources[0].source_ref == "tg:ch:post:1"

    async def test_ask_with_channel_filter(self):
        mock_answer = AnswerResult(answer="No data.", sources=[], model=None)
        with patch(ANSWER_PATCH, return_value=mock_answer) as mock_fn:
            result = await ask_question("question", channel_id="ch")

        mock_fn.assert_awaited_once_with(question="question", channel_id="ch", allowed_channel_ids=None)
        assert result.sources == []


# ===========================================================================
# T3: Navigation tools
# ===========================================================================


class TestListTopicsTool:

    async def test_list_topics_returns_topics(self):
        card = _make_topic_card()
        bundle = _make_bundle()
        ctx = _mock_processing_repos(topic_cards=[card], bundles={card.id: bundle})

        with patch(PROC_PATCH, ctx):
            result = await list_topics()

        assert isinstance(result, TopicListResult)
        assert result.total == 1
        assert len(result.items) == 1
        assert isinstance(result.items[0], TopicSummary)
        assert result.items[0].id == card.id
        assert result.items[0].title == "Test Topic"
        assert result.items[0].type == "singleton"
        assert result.items[0].items_count == 2
        assert result.items[0].sources == ["ch"]

    async def test_list_topics_empty(self):
        ctx = _mock_processing_repos()
        with patch(PROC_PATCH, ctx):
            result = await list_topics()

        assert isinstance(result, TopicListResult)
        assert result.total == 0
        assert result.items == []
        assert result.has_more is False

    async def test_list_topics_filter_by_type(self):
        card_s = _make_topic_card(topic_id="topic:s", title="Singleton")
        card_c = TopicCard(
            id="topic:c",
            title="Cluster",
            summary="Cluster summary",
            scope_in=["in"],
            scope_out=["out"],
            type=TopicType.CLUSTER,
            anchors=[
                Anchor(channel_id="ch", message_id="1", message_type=MessageType.POST,
                       anchor_ref="tg:ch:post:1", score=1.0),
                Anchor(channel_id="ch", message_id="2", message_type=MessageType.POST,
                       anchor_ref="tg:ch:post:2", score=0.9),
            ],
            sources=["ch"],
            updated_at=NOW,
        )
        ctx = _mock_processing_repos(topic_cards=[card_s, card_c])
        with patch(PROC_PATCH, ctx):
            result = await list_topics(topic_type="singleton")

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].title == "Singleton"

    async def test_list_topics_with_channel_id(self):
        card = _make_topic_card()
        ctx = _mock_processing_repos(topic_cards=[card])
        with patch(PROC_PATCH, ctx):
            result = await list_topics(channel_id="ch")

        assert result.total == 1
        assert len(result.items) == 1

    async def test_list_topics_respects_limit(self):
        cards = [_make_topic_card(topic_id=f"topic:{i}", title=f"T{i}") for i in range(5)]
        ctx = _mock_processing_repos(topic_cards=cards)
        with patch(PROC_PATCH, ctx):
            result = await list_topics(limit=2)

        assert result.total == 5
        assert len(result.items) == 2
        assert result.has_more is True


class TestGetTopicDetailsTool:

    async def test_get_topic_details_success(self):
        card = _make_topic_card()
        bundle = _make_bundle()
        ctx = _mock_processing_repos(topic_cards=[card], bundles={card.id: bundle})

        with patch(PROC_PATCH, ctx):
            result = await get_topic_details(card.id)

        assert isinstance(result, TopicDetail)
        assert result.id == card.id
        assert result.title == "Test Topic"
        assert result.scope_in == ["scope in"]
        assert result.scope_out == ["scope out"]
        assert len(result.anchors) == 1
        assert result.items is not None
        assert len(result.items) == 2

    async def test_get_topic_details_not_found(self):
        ctx = _mock_processing_repos()
        with patch(PROC_PATCH, ctx):
            result = await get_topic_details("nonexistent")

        assert isinstance(result, str)
        assert "not found" in result

    async def test_get_topic_details_no_bundle(self):
        card = _make_topic_card()
        ctx = _mock_processing_repos(topic_cards=[card])

        with patch(PROC_PATCH, ctx):
            result = await get_topic_details(card.id)

        assert isinstance(result, TopicDetail)
        assert result.items is None


class TestListChannelsTool:

    async def test_list_channels_returns_channels(self):
        batch_result = [
            {
                "channel_id": "ch",
                "channel_username": "test_channel",
                "status": "active",
                "raw_messages": 100,
                "processed_documents": 95,
                "topics_count": 10,
                "coverage_percent": 85.5,
            },
        ]
        with patch(BATCH_STATS_PATCH, return_value=batch_result):
            result = await list_channels()

        assert len(result) == 1
        assert isinstance(result[0], ChannelSummary)
        assert result[0].channel_id == "ch"
        assert result[0].channel_username == "test_channel"
        assert result[0].raw_messages == 100
        assert result[0].coverage_percent == 85.5

    async def test_list_channels_empty(self):
        with patch(BATCH_STATS_PATCH, return_value=[]):
            result = await list_channels()

        assert result == []

    async def test_list_channels_handles_stats_error(self):
        batch_result = [
            {
                "channel_id": "ch",
                "channel_username": "test_channel",
                "status": "active",
                "raw_messages": 0,
                "processed_documents": 0,
                "topics_count": 0,
                "coverage_percent": 0.0,
            },
        ]
        with patch(BATCH_STATS_PATCH, return_value=batch_result):
            result = await list_channels()

        assert len(result) == 1
        assert result[0].channel_id == "ch"
        assert result[0].raw_messages == 0
        assert result[0].coverage_percent == 0.0


class TestGetDocumentTool:

    async def test_get_document_success(self):
        doc = _make_processed_doc()
        ctx = _mock_processing_repos(processed_docs=[doc])

        with patch(PROC_PATCH, ctx):
            result = await get_document("tg:ch:post:1")

        assert isinstance(result, DocumentDetail)
        assert result.source_ref == "tg:ch:post:1"
        assert result.text_clean == "Clean text content for testing"
        assert result.summary == "A short summary"
        assert result.topics == ["topic1"]

    async def test_get_document_not_found(self):
        ctx = _mock_processing_repos()
        with patch(PROC_PATCH, ctx):
            result = await get_document("tg:ch:post:999")

        assert isinstance(result, str)
        assert "not found" in result


# ===========================================================================
# S1: MCP logging configuration
# ===========================================================================

import io  # noqa: E402  # section-local imports for TestMcpLogging
import sys  # noqa: E402


class TestMcpLogging:

    def test_mcp_logging_goes_to_stderr(self):
        from tg_parser.mcp_server import _configure_mcp_logging

        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_stdout, captured_stderr

        try:
            _configure_mcp_logging()

            import structlog

            structlog.get_logger().info("test_message")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        assert "test_message" not in captured_stdout.getvalue()
        assert "test_message" in captured_stderr.getvalue()

    def test_stdlib_logging_goes_to_stderr(self):
        import logging as _logging

        from tg_parser.mcp_server import _configure_mcp_logging

        _configure_mcp_logging()

        root = _logging.getLogger()
        assert all(
            getattr(h, "stream", None) is sys.stderr
            for h in root.handlers
        )
        assert root.level == _logging.WARNING
