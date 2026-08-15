"""BUG-102 / F-04 — a topic hit is readable on MCP, HTTP, and bot.

Internal retrieval already builds ``SearchResult(entry_type="topic",
topic_card=card, document=None)``. The six serializers used to read only
``document``, so the wire row was a string of nulls and ``entry_type``
never left the process. This file asserts the projected form on every
surface; existing ``test_f5a_*`` / ``test_f4_coverage_supplement`` cover
the internal ``SearchResult`` and do not replace it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from tg_parser.auth.models import CurrentUser
from tg_parser.domain.models import Anchor, MessageType, ProcessedDocument, TopicCard, TopicType
from tg_parser.services.retrieval_service import AnswerResult, SearchResult
from tg_parser.services.search_result_projection import project_search_result

NOW = datetime(2026, 8, 15, tzinfo=UTC)
SEARCH_PATCH = "tg_parser.services.retrieval_service.search"
ANSWER_PATCH = "tg_parser.services.retrieval_service.answer"


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _topic_card() -> TopicCard:
    return TopicCard(
        id="topic:tg:medportal:post:1",
        title="Vitamin D deficiency",
        summary="A long enough topic summary used both as summary and as preview text.",
        scope_in=["labs"],
        scope_out=["unrelated"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="medportal",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:medportal:post:1",
                score=1.0,
            )
        ],
        sources=["medportal"],
        updated_at=NOW,
    )


def _topic_hit() -> SearchResult:
    return SearchResult(
        source_ref="topic:tg:medportal:post:1",
        score=0.91,
        document=None,
        entry_type="topic",
        topic_card=_topic_card(),
    )


def _doc_hit() -> SearchResult:
    doc = ProcessedDocument(
        id="doc:tg:medportal:post:9",
        source_ref="tg:medportal:post:9",
        source_message_id="9",
        channel_id="medportal",
        processed_at=NOW,
        text_clean="Clean document text for the message hit.",
        summary="Document summary",
        topics=[],
    )
    return SearchResult(
        source_ref=doc.source_ref,
        score=0.77,
        document=doc,
        entry_type="message",
    )


def _assert_topic_fields(item, *, expect_preview: bool, preview_limit: int | None) -> None:
    entry_type = item["entry_type"] if isinstance(item, dict) else item.entry_type
    title = item["title"] if isinstance(item, dict) else item.title
    summary = item["summary"] if isinstance(item, dict) else item.summary
    channel_id = item["channel_id"] if isinstance(item, dict) else item.channel_id
    assert entry_type == "topic"
    assert title == "Vitamin D deficiency"
    assert summary
    assert channel_id == "medportal"
    if expect_preview:
        preview = item["text_preview"] if isinstance(item, dict) else item.text_preview
        assert preview == summary[:preview_limit]
    else:
        assert "text_preview" not in item


async def test_helper_projects_topic_and_omits_preview_when_asked() -> None:
    topic = project_search_result(_topic_hit(), preview_limit=300)
    _assert_topic_fields(topic, expect_preview=True, preview_limit=300)
    ask = project_search_result(_topic_hit(), preview_limit=None)
    _assert_topic_fields(ask, expect_preview=False, preview_limit=None)

    doc = project_search_result(_doc_hit(), preview_limit=200)
    assert doc["entry_type"] == "message"
    assert doc["title"] is None
    assert doc["summary"] == "Document summary"
    assert doc["channel_id"] == "medportal"
    assert doc["text_preview"] == "Clean document text for the message hit."[:200]


async def test_mcp_search_and_ask_project_a_topic_hit() -> None:
    from tg_parser.mcp_server import ask_question, search_knowledge_base

    with patch(SEARCH_PATCH, return_value=[_topic_hit(), _doc_hit()]):
        result = await search_knowledge_base("vitamin D")
    topic, doc = result.result
    _assert_topic_fields(topic, expect_preview=True, preview_limit=300)
    assert doc.entry_type == "message"
    assert doc.title is None
    assert doc.summary == "Document summary"
    assert doc.channel_id == "medportal"

    with patch(
        ANSWER_PATCH,
        return_value=AnswerResult(answer="ok", sources=[_topic_hit()], model="stub"),
    ):
        asked = await ask_question("what about vitamin D?")
    _assert_topic_fields(asked.sources[0], expect_preview=True, preview_limit=300)


async def test_http_search_and_ask_project_a_topic_hit() -> None:
    from tg_parser.api.routes.rag import AskRequest, SearchRequest, ask_question, search_documents

    admin = _admin()
    request = MagicMock()
    with patch(SEARCH_PATCH, return_value=[_topic_hit()]):
        resp = await search_documents(SearchRequest(query="q"), request, admin)
    _assert_topic_fields(resp.results[0], expect_preview=True, preview_limit=200)

    with patch(
        ANSWER_PATCH,
        return_value=AnswerResult(answer="ok", sources=[_topic_hit()], model="stub"),
    ):
        asked = await ask_question(AskRequest(question="q"), request, admin)
    _assert_topic_fields(asked.sources[0], expect_preview=True, preview_limit=200)


async def test_bot_search_and_ask_project_a_topic_hit() -> None:
    from tg_parser.bot.tools import _exec_ask_question, _exec_search

    with patch(SEARCH_PATCH, return_value=[_topic_hit()]):
        payload = await _exec_search({"query": "q"}, current_user=_admin())
    _assert_topic_fields(payload["results"][0], expect_preview=True, preview_limit=300)

    with patch(
        ANSWER_PATCH,
        return_value=AnswerResult(answer="ok", sources=[_topic_hit()], model="stub"),
    ):
        asked = await _exec_ask_question({"question": "q"}, current_user=_admin())
    _assert_topic_fields(asked["sources"][0], expect_preview=False, preview_limit=None)
