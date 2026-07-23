"""F5-C #15 item #2 — unit tests for the pure domain diff helper.

Covers ``diff_topic_summaries`` over normalised snapshots built from both an
archival ``TopicCardVersion`` and the live ``TopicCard`` (``current`` side).
No Postgres, no I/O — this is the shared, pure core used by both the MCP tool
and the CLI.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tg_parser.domain.models import (
    Anchor,
    MessageType,
    TopicCard,
    TopicCardVersion,
    TopicType,
)
from tg_parser.domain.topic_history_diff import (
    CURRENT_LABEL,
    TopicSummarySnapshot,
    diff_topic_summaries,
    snapshot_from_card,
    snapshot_from_version,
)


def _version(
    *,
    version_no: int = 1,
    summary: str = "Line one\nLine two",
    scope_in: list[str] | None = None,
    scope_out: list[str] | None = None,
) -> TopicCardVersion:
    return TopicCardVersion(
        id=version_no,
        topic_id="topic:tg:c1:post:1",
        version_no=version_no,
        summary=summary,
        scope_in=scope_in if scope_in is not None else ["alpha"],
        scope_out=scope_out if scope_out is not None else ["beta"],
        supporting_items_count_at_time=10 + version_no,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        prompt_version="1.0.0",
        created_at=datetime(2026, 4, 26, 10, version_no, 0, tzinfo=UTC),
    )


def _card(
    *,
    summary_version: int = 3,
    summary: str = "Line one\nLine two",
    scope_in: list[str] | None = None,
    scope_out: list[str] | None = None,
) -> TopicCard:
    return TopicCard(
        id="topic:tg:c1:post:1",
        title="Test topic",
        summary=summary,
        scope_in=scope_in if scope_in is not None else ["alpha"],
        scope_out=scope_out if scope_out is not None else ["beta"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="c1",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:c1:post:1",
                score=0.9,
            )
        ],
        sources=["c1"],
        updated_at=datetime(2026, 4, 26, tzinfo=UTC),
        summary_version=summary_version,
        last_summarized_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        new_items_since_last_summary=0,
    )


class TestSummaryDiff:
    def test_identical_sides_yield_empty_diff(self):
        left = snapshot_from_version(_version(version_no=1))
        right = snapshot_from_version(_version(version_no=2))  # same content
        result = diff_topic_summaries(left, right)

        assert result["summary_changed"] is False
        assert result["summary_diff"] == []
        assert result["scope_in"] == {"added": [], "removed": [], "unchanged_count": 1}
        assert result["scope_out"] == {"added": [], "removed": [], "unchanged_count": 1}

    def test_summary_line_change_produces_unified_diff(self):
        left = snapshot_from_version(_version(version_no=1, summary="Line one\nLine two"))
        right = snapshot_from_version(_version(version_no=2, summary="Line one\nLine TWO"))
        result = diff_topic_summaries(left, right)

        assert result["summary_changed"] is True
        joined = "\n".join(result["summary_diff"])
        # unified_diff marks removed with '-' and added with '+'.
        assert "-Line two" in joined
        assert "+Line TWO" in joined
        # Labels come from provenance.
        assert "v1" in joined
        assert "v2" in joined


class TestScopeDiff:
    def test_scope_added_and_removed(self):
        left = snapshot_from_version(_version(version_no=1, scope_in=["a", "b"], scope_out=["x"]))
        right = snapshot_from_version(
            _version(version_no=2, scope_in=["b", "c"], scope_out=["x", "y"])
        )
        result = diff_topic_summaries(left, right)

        assert result["scope_in"] == {
            "added": ["c"],
            "removed": ["a"],
            "unchanged_count": 1,
        }
        assert result["scope_out"] == {
            "added": ["y"],
            "removed": [],
            "unchanged_count": 1,
        }

    def test_scope_order_preserved_in_added_and_removed(self):
        left = TopicSummarySnapshot(
            summary="s", scope_in=["a", "b", "c"], scope_out=[], provenance={"label": "L"}
        )
        right = TopicSummarySnapshot(
            summary="s", scope_in=["c", "z", "y"], scope_out=[], provenance={"label": "R"}
        )
        result = diff_topic_summaries(left, right)

        assert result["scope_in"]["added"] == ["z", "y"]  # right order
        assert result["scope_in"]["removed"] == ["a", "b"]  # left order
        assert result["scope_in"]["unchanged_count"] == 1


class TestCurrentSideNormalisation:
    def test_current_side_from_card_matches_archival_shape(self):
        """The ``current`` side (live TopicCard) must produce the same diff
        structure as an archival side, and be labelled ``current``."""
        left = snapshot_from_version(_version(version_no=1, summary="Old summary"))
        right = snapshot_from_card(_card(summary_version=3, summary="New summary"))

        assert right.provenance["label"] == CURRENT_LABEL
        assert right.provenance["version_no"] == CURRENT_LABEL
        assert right.provenance["summary_version"] == 3

        result = diff_topic_summaries(left, right)
        # Same top-level keys regardless of source type.
        assert set(result.keys()) == {
            "left",
            "right",
            "summary_changed",
            "summary_diff",
            "scope_in",
            "scope_out",
        }
        assert result["left"]["version_no"] == 1
        assert result["right"]["version_no"] == CURRENT_LABEL
        assert result["summary_changed"] is True
