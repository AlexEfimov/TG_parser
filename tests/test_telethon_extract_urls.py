"""
Unit tests for TelethonClient._extract_urls and URL preservation in _convert_message.
"""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from tg_parser.config.settings import Settings
from tg_parser.domain.models import MessageType
from tg_parser.ingestion.telegram import TelethonClient


@pytest.fixture
def client() -> TelethonClient:
    return TelethonClient(
        Settings(
            telegram_api_id=12345,
            telegram_api_hash="test_hash",
            telegram_phone="+1234567890",
        )
    )


def _make_message(*, message: str, entities) -> Mock:
    mock_message = Mock()
    mock_message.id = 1
    mock_message.text = message
    mock_message.message = message
    mock_message.date = datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC)
    mock_message.reply_to = None
    mock_message.views = None
    mock_message.forwards = None
    mock_message.replies = None
    mock_message.edit_date = None
    mock_message.post_author = None
    mock_message.grouped_id = None
    mock_message.media = None
    mock_message.entities = entities
    return mock_message


class TestExtractUrls:
    def test_entities_none_returns_empty(self, client):
        message = _make_message(message="plain text", entities=None)
        assert client._extract_urls(message) == []

    def test_text_url_entity(self, client):
        plain = "Read more here"
        message = _make_message(
            message=plain,
            entities=[
                MessageEntityTextUrl(
                    offset=0,
                    length=14,
                    url="https://example.com/article",
                )
            ],
        )
        assert client._extract_urls(message) == [
            {
                "url": "https://example.com/article",
                "text": "Read more here",
                "type": "text_url",
            }
        ]

    def test_bare_url_entity(self, client):
        plain = "Visit https://example.com today"
        url = "https://example.com"
        offset = len("Visit ".encode("utf-16-le")) // 2
        length = len(url.encode("utf-16-le")) // 2
        message = _make_message(
            message=plain,
            entities=[MessageEntityUrl(offset=offset, length=length)],
        )
        assert client._extract_urls(message) == [
            {
                "url": url,
                "text": url,
                "type": "url",
            }
        ]

    def test_utf16_emoji_offset(self, client):
        plain = "Hi 👋 link"
        # "Hi " = 3 UTF-16 units, "👋" = 2, " " = 1, so "link" starts at offset 6
        message = _make_message(
            message=plain,
            entities=[
                MessageEntityTextUrl(
                    offset=6,
                    length=4,
                    url="https://example.com/emoji-test",
                )
            ],
        )
        assert client._extract_urls(message) == [
            {
                "url": "https://example.com/emoji-test",
                "text": "link",
                "type": "text_url",
            }
        ]

    def test_mixed_entities_preserves_order(self, client):
        plain = "Site https://a.com and click"
        url_offset = len("Site ".encode("utf-16-le")) // 2
        url_length = len("https://a.com".encode("utf-16-le")) // 2
        text_url_offset = len("Site https://a.com and ".encode("utf-16-le")) // 2
        message = _make_message(
            message=plain,
            entities=[
                MessageEntityUrl(offset=url_offset, length=url_length),
                MessageEntityTextUrl(
                    offset=text_url_offset,
                    length=5,
                    url="https://b.com/hidden",
                ),
            ],
        )
        assert client._extract_urls(message) == [
            {
                "url": "https://a.com",
                "text": "https://a.com",
                "type": "url",
            },
            {
                "url": "https://b.com/hidden",
                "text": "click",
                "type": "text_url",
            },
        ]

    def test_dedup_exact_url_repeats(self, client):
        plain = "dup dup"
        message = _make_message(
            message=plain,
            entities=[
                MessageEntityTextUrl(offset=0, length=3, url="https://dup.example"),
                MessageEntityTextUrl(offset=4, length=3, url="https://dup.example"),
            ],
        )
        assert client._extract_urls(message) == [
            {
                "url": "https://dup.example",
                "text": "dup",
                "type": "text_url",
            }
        ]

    def test_empty_entities_list(self, client):
        message = _make_message(message="no links", entities=[])
        assert client._extract_urls(message) == []


class TestConvertMessageUrls:
    @pytest.mark.asyncio
    async def test_convert_message_adds_urls_to_raw_payload(self, client):
        message = _make_message(
            message="click me",
            entities=[
                MessageEntityTextUrl(
                    offset=0,
                    length=8,
                    url="https://example.com/hidden",
                )
            ],
        )
        raw_msg = await client._convert_message(
            message=message,
            channel_id="test_channel",
            message_type=MessageType.POST,
        )
        assert raw_msg.raw_payload["urls"] == [
            {
                "url": "https://example.com/hidden",
                "text": "click me",
                "type": "text_url",
            }
        ]

    @pytest.mark.asyncio
    async def test_convert_message_omits_urls_key_when_empty(self, client):
        message = _make_message(message="plain", entities=None)
        raw_msg = await client._convert_message(
            message=message,
            channel_id="test_channel",
            message_type=MessageType.POST,
        )
        assert "urls" not in raw_msg.raw_payload
