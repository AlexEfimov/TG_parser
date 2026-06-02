"""Unit tests for SARawMessageRepo._serialize_payload URL preservation on truncate."""

import json
from unittest.mock import MagicMock

from tg_parser.storage.sqlalchemy.raw_message_repo import RAW_PAYLOAD_MAX_SIZE, SARawMessageRepo


def test_serialize_payload_preserves_urls_on_truncate():
    repo = SARawMessageRepo(session=MagicMock())
    urls = [
        {
            "url": "https://example.com/hidden",
            "text": "click here",
            "type": "text_url",
        }
    ]
    payload = {
        "message": "x" * (RAW_PAYLOAD_MAX_SIZE + 1000),
        "urls": urls,
    }

    payload_json, truncated, original_size = repo._serialize_payload(payload)

    assert truncated is True
    assert original_size > RAW_PAYLOAD_MAX_SIZE
    loaded = json.loads(payload_json)
    assert loaded["truncated"] is True
    assert loaded["urls"] == urls
