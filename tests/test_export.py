"""
Tests for export modules (S6d).

Covers: kb_export, topics_export — pure functions that serialize
domain models to NDJSON/JSON files.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    KnowledgeBaseEntry,
    KnowledgeBaseEntrySource,
    MessageType,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.export.kb_export import export_kb_entries_ndjson
from tg_parser.export.topics_export import (
    export_topic_detail_json,
    export_topics_json,
)

NOW = datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC)


def _make_kb_entry(entry_id: str, title: str = "Test Entry") -> KnowledgeBaseEntry:
    return KnowledgeBaseEntry(
        id=entry_id,
        source=KnowledgeBaseEntrySource(
            type="telegram_message",
            channel_id="ch1",
            message_id="100",
            message_type=MessageType.POST,
            source_ref="tg:ch1:post:100",
        ),
        created_at=NOW,
        title=title,
        content="Some content",
        topics=["topic_a"],
    )


def _make_topic_card(
    card_id: str = "topic:tg:ch1:post:100",
    title: str = "Test Topic",
) -> TopicCard:
    return TopicCard(
        id=card_id,
        title=title,
        summary="A topic about testing",
        scope_in=["testing"],
        scope_out=["production"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="ch1",
                message_id="100",
                message_type=MessageType.POST,
                anchor_ref="tg:ch1:post:100",
                score=1.0,
            ),
        ],
        sources=["ch1"],
        updated_at=NOW,
    )


def _make_bundle(topic_id: str = "topic:tg:ch1:post:100") -> TopicBundle:
    return TopicBundle(
        topic_id=topic_id,
        items=[
            BundleItem(
                channel_id="ch1",
                message_id="100",
                message_type=MessageType.POST,
                source_ref="tg:ch1:post:100",
                role=BundleItemRole.ANCHOR,
                score=1.0,
            ),
            BundleItem(
                channel_id="ch1",
                message_id="200",
                message_type=MessageType.POST,
                source_ref="tg:ch1:post:200",
                role=BundleItemRole.SUPPORTING,
                score=0.7,
                justification="Related content",
            ),
        ],
        updated_at=NOW,
    )


# ===========================================================================
# kb_export
# ===========================================================================


class TestKbExportNdjson:
    def test_basic_export(self, tmp_path: Path):
        entries = [
            _make_kb_entry("kb:msg:tg:ch1:post:200", title="Second"),
            _make_kb_entry("kb:msg:tg:ch1:post:100", title="First"),
        ]
        out = tmp_path / "kb.ndjson"
        export_kb_entries_ndjson(entries, out)

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        first = json.loads(lines[0])
        second = json.loads(lines[1])
        # Sorted by id
        assert first["id"] == "kb:msg:tg:ch1:post:100"
        assert second["id"] == "kb:msg:tg:ch1:post:200"

    def test_empty_list(self, tmp_path: Path):
        out = tmp_path / "empty.ndjson"
        export_kb_entries_ndjson([], out)

        content = out.read_text(encoding="utf-8")
        assert content.strip() == ""

    def test_special_chars_in_title(self, tmp_path: Path):
        entry = _make_kb_entry("kb:msg:tg:ch1:post:1", title='Quotes "and" кириллица ÄÖÜ')
        out = tmp_path / "special.ndjson"
        export_kb_entries_ndjson([entry], out)

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        parsed = json.loads(lines[0])
        assert parsed["title"] == 'Quotes "and" кириллица ÄÖÜ'

    def test_deterministic_output(self, tmp_path: Path):
        """Same entries produce identical output on repeated calls."""
        entries = [
            _make_kb_entry("kb:msg:tg:ch1:post:2"),
            _make_kb_entry("kb:msg:tg:ch1:post:1"),
        ]
        out1 = tmp_path / "run1.ndjson"
        out2 = tmp_path / "run2.ndjson"

        export_kb_entries_ndjson(entries, out1)
        export_kb_entries_ndjson(entries, out2)

        assert out1.read_text() == out2.read_text()


# ===========================================================================
# topics_export — export_topics_json
# ===========================================================================


class TestExportTopicsJson:
    def test_basic_export(self, tmp_path: Path):
        cards = [
            _make_topic_card("topic:tg:ch1:post:200", title="Second"),
            _make_topic_card("topic:tg:ch1:post:100", title="First"),
        ]
        out = tmp_path / "topics.json"
        export_topics_json(cards, out)

        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2
        # Sorted by id
        assert data[0]["id"] == "topic:tg:ch1:post:100"
        assert data[1]["id"] == "topic:tg:ch1:post:200"

    def test_empty_list(self, tmp_path: Path):
        out = tmp_path / "empty.json"
        export_topics_json([], out)

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data == []

    def test_pretty_format(self, tmp_path: Path):
        cards = [_make_topic_card()]
        out = tmp_path / "pretty.json"
        export_topics_json(cards, out, pretty=True)

        content = out.read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content  # indented

    def test_deterministic_output(self, tmp_path: Path):
        cards = [
            _make_topic_card("topic:tg:ch1:post:2"),
            _make_topic_card("topic:tg:ch1:post:1"),
        ]
        out1 = tmp_path / "run1.json"
        out2 = tmp_path / "run2.json"

        export_topics_json(cards, out1)
        export_topics_json(cards, out2)

        assert out1.read_text() == out2.read_text()


# ===========================================================================
# topics_export — export_topic_detail_json
# ===========================================================================


class TestExportTopicDetailJson:
    def test_basic_export(self, tmp_path: Path):
        card = _make_topic_card()
        bundle = _make_bundle()
        out = tmp_path / "detail.json"

        export_topic_detail_json(
            card=card,
            bundle=bundle,
            channel_username_map={"ch1": "test_channel"},
            output_path=out,
        )

        data = json.loads(out.read_text(encoding="utf-8"))
        assert "topic_card" in data
        assert "topic_bundle" in data
        assert "resolved_sources" in data
        assert "exported_at" in data
        assert "export_version" in data
        assert data["topic_card"]["id"] == card.id

        sources = data["resolved_sources"]
        assert len(sources) == 2
        # Anchors first
        assert sources[0]["role"] == "anchor"

    def test_resolved_sources_have_telegram_url(self, tmp_path: Path):
        card = _make_topic_card()
        bundle = _make_bundle()
        out = tmp_path / "detail.json"

        export_topic_detail_json(
            card=card,
            bundle=bundle,
            channel_username_map={"ch1": "test_channel"},
            output_path=out,
        )

        data = json.loads(out.read_text(encoding="utf-8"))
        for src in data["resolved_sources"]:
            assert "telegram_url" in src

    def test_no_username_still_works(self, tmp_path: Path):
        card = _make_topic_card()
        bundle = _make_bundle()
        out = tmp_path / "detail.json"

        export_topic_detail_json(
            card=card,
            bundle=bundle,
            channel_username_map={},
            output_path=out,
        )

        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["resolved_sources"]) >= 1

    def test_supporting_item_has_justification(self, tmp_path: Path):
        card = _make_topic_card()
        bundle = _make_bundle()
        out = tmp_path / "detail.json"

        export_topic_detail_json(
            card=card,
            bundle=bundle,
            channel_username_map={"ch1": "test_channel"},
            output_path=out,
        )

        data = json.loads(out.read_text(encoding="utf-8"))
        supporting = [s for s in data["resolved_sources"] if s["role"] == "supporting"]
        assert len(supporting) == 1
        assert supporting[0]["justification"] == "Related content"
