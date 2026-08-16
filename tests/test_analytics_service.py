"""
Tests for cross-channel analytics service (Cross-dev 2).
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicBundle,
    TopicCard,
    TopicLink,
    TopicType,
)
from tg_parser.services.analytics_service import (
    _extract_keywords,
    _get_channel_for_card,
    get_cross_channel_analytics,
)
from tg_parser.storage.ports import Source

NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


def _make_source(channel_id: str, status: str = "active") -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status=status,
        include_comments=False,
    )


def _make_topic_card(
    topic_id: str,
    channel_id: str,
    topic_type: TopicType = TopicType.SINGLETON,
    tags: list[str] | None = None,
    scope_in: list[str] | None = None,
) -> TopicCard:
    anchors = [
        Anchor(
            channel_id=channel_id,
            message_id="1",
            message_type=MessageType.POST,
            anchor_ref=f"tg:{channel_id}:post:1",
            score=1.0,
        ),
    ]
    if topic_type == TopicType.CLUSTER:
        anchors.append(
            Anchor(
                channel_id=channel_id,
                message_id="2",
                message_type=MessageType.POST,
                anchor_ref=f"tg:{channel_id}:post:2",
                score=0.8,
            ),
        )
    return TopicCard(
        id=topic_id,
        title="Test Topic",
        summary="Test summary",
        scope_in=scope_in or ["Генетика", "ДНК-тесты"],
        scope_out=["Не относится"],
        type=topic_type,
        anchors=anchors,
        sources=[channel_id],
        updated_at=NOW,
        tags=tags,
    )


def _make_bundle(topic_id: str, channel_id: str, item_count: int = 3) -> TopicBundle:
    items = [
        BundleItem(
            channel_id=channel_id,
            message_id=str(i),
            message_type=MessageType.POST,
            source_ref=f"tg:{channel_id}:post:{i}",
            role=BundleItemRole.ANCHOR if i == 0 else BundleItemRole.SUPPORTING,
        )
        for i in range(item_count)
    ]
    return TopicBundle(topic_id=topic_id, items=items, updated_at=NOW)


def _make_mock_repos(
    sources: list[Source],
    cards: list[TopicCard],
    bundles: list[TopicBundle],
    proc_counts: dict[str, int] | None = None,
    proc_refs: dict[str, list[str]] | None = None,
    links: list[Any] | None = None,
):
    """Create mock repos that return the given data."""
    state_repo = AsyncMock()
    state_repo.list_sources.return_value = sources

    raw_repo = AsyncMock()
    proc_repo = AsyncMock()

    if proc_counts is None:
        proc_counts = {}
    if proc_refs is None:
        proc_refs = {}

    proc_repo.count_by_channel.side_effect = lambda cid: proc_counts.get(cid, 0)
    proc_repo.list_source_refs_by_channel.side_effect = lambda cid: proc_refs.get(cid, [])

    topic_card_repo = AsyncMock()
    topic_card_repo.list_all.return_value = cards

    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_all.return_value = bundles

    emb_repo = AsyncMock()

    topic_link_repo = AsyncMock()
    topic_link_repo.list_all.return_value = links or []

    db = MagicMock()

    return (
        state_repo,
        raw_repo,
        proc_repo,
        topic_card_repo,
        topic_bundle_repo,
        emb_repo,
        topic_link_repo,
        db,
    )


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def test_from_tags(self):
        card = _make_topic_card("t:1", "ch1", tags=["Витамин D", "Генетика"])
        kws = _extract_keywords(card)
        assert "витамин d" in kws
        assert "генетика" in kws

    def test_from_scope_in(self):
        card = _make_topic_card("t:1", "ch1", scope_in=["Анализ крови на витамины"])
        kws = _extract_keywords(card)
        assert "анализ" in kws
        assert "крови" in kws
        assert "витамины" in kws

    def test_short_words_filtered(self):
        card = _make_topic_card("t:1", "ch1", scope_in=["По ДНК-тестам"])
        kws = _extract_keywords(card)
        assert "по" not in kws
        assert "днк-тестам" in kws

    def test_empty_tags(self):
        card = _make_topic_card("t:1", "ch1", tags=None, scope_in=["Test"])
        kws = _extract_keywords(card)
        assert "test" in kws

    def test_stoplist_drops_dlya_from_scope_in(self):
        card = _make_topic_card(
            "t:1", "ch1", tags=None, scope_in=["материалы для здоровья"]
        )
        kws = _extract_keywords(card)
        assert "материалы" in kws
        assert "здоровья" in kws
        assert "для" not in kws

    def test_stoplist_drops_tag_dlya_keeps_content_tag(self):
        card = _make_topic_card(
            "t:1", "ch1", tags=["для", "Витамин D"], scope_in=["анализ"]
        )
        kws = _extract_keywords(card)
        assert "для" not in kws
        assert "витамин d" in kws
        assert "анализ" in kws


class TestGetChannelForCard:
    def test_with_sources(self):
        card = _make_topic_card("t:1", "genotek")
        assert _get_channel_for_card(card) == "genotek"

    def test_empty_sources(self):
        card = _make_topic_card("t:1", "ch")
        card.sources = []
        assert _get_channel_for_card(card) is None


# ---------------------------------------------------------------------------
# Integration tests (mocked DB)
# ---------------------------------------------------------------------------


class TestCrossChannelAnalyticsGlobal:
    async def test_basic_global_stats(self):
        sources = [_make_source("ch1"), _make_source("ch2")]
        cards = [
            _make_topic_card("t:1", "ch1", TopicType.SINGLETON, tags=["витамины"]),
            _make_topic_card("t:2", "ch1", TopicType.CLUSTER, tags=["генетика"]),
            _make_topic_card("t:3", "ch2", TopicType.SINGLETON, tags=["витамины", "кровь"]),
        ]
        bundles = [
            _make_bundle("t:1", "ch1", 5),
            _make_bundle("t:2", "ch1", 3),
            _make_bundle("t:3", "ch2", 4),
        ]

        refs_ch1 = [f"tg:ch1:post:{i}" for i in range(10)]
        refs_ch2 = [f"tg:ch2:post:{i}" for i in range(8)]

        repos = _make_mock_repos(
            sources,
            cards,
            bundles,
            proc_counts={"ch1": 10, "ch2": 8},
            proc_refs={"ch1": refs_ch1, "ch2": refs_ch2},
        )

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics()

        assert result["total_documents"] == 18
        assert result["total_topics"] == 3
        assert len(result["channels"]) == 2

        ch1_data = next(c for c in result["channels"] if c["channel_id"] == "ch1")
        assert ch1_data["singleton_count"] == 1
        assert ch1_data["cluster_count"] == 1
        assert ch1_data["topics_count"] == 2

        ch2_data = next(c for c in result["channels"] if c["channel_id"] == "ch2")
        assert ch2_data["singleton_count"] == 1
        assert ch2_data["cluster_count"] == 0

    async def test_keyword_overlaps_detected(self):
        sources = [_make_source("ch1"), _make_source("ch2")]
        cards = [
            _make_topic_card("t:1", "ch1", tags=["витамин d", "анализы"]),
            _make_topic_card("t:2", "ch2", tags=["витамин d", "генетика"]),
        ]
        bundles = [_make_bundle("t:1", "ch1"), _make_bundle("t:2", "ch2")]

        repos = _make_mock_repos(
            sources,
            cards,
            bundles,
            proc_counts={"ch1": 5, "ch2": 5},
            proc_refs={"ch1": [], "ch2": []},
        )

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics()

        overlapping_keywords = [o["keyword"] for o in result["keyword_overlaps"]]
        assert "витамин d" in overlapping_keywords
        assert result["overlap_count"] > 0

    async def test_empty_channels(self):
        repos = _make_mock_repos([], [], [])

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics()

        assert result["total_documents"] == 0
        assert result["total_topics"] == 0
        assert result["channels"] == []


class TestCrossChannelAnalyticsSingle:
    async def test_single_channel_detail(self):
        sources = [_make_source("ch1"), _make_source("ch2")]
        cards = [
            _make_topic_card("t:1", "ch1", tags=["витамины", "кровь"]),
            _make_topic_card("t:2", "ch2", tags=["витамины", "генетика"]),
        ]
        bundles = [_make_bundle("t:1", "ch1"), _make_bundle("t:2", "ch2")]

        repos = _make_mock_repos(
            sources,
            cards,
            bundles,
            proc_counts={"ch1": 10, "ch2": 8},
            proc_refs={"ch1": [], "ch2": []},
        )

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics(channel_id="ch1")

        assert result["channel_id"] == "ch1"
        assert result["processed_documents"] == 10
        assert result["singleton_count"] == 1
        assert "all_keywords" in result
        assert "витамины" in result["all_keywords"]

        assert len(result["related_channels"]) > 0
        related_ch = result["related_channels"][0]
        assert related_ch["channel_id"] == "ch2"
        assert related_ch["shared_keywords"] > 0

    async def test_nonexistent_channel(self):
        sources = [_make_source("ch1")]
        cards = [_make_topic_card("t:1", "ch1")]
        bundles = [_make_bundle("t:1", "ch1")]

        repos = _make_mock_repos(
            sources,
            cards,
            bundles,
            proc_counts={"ch1": 5},
            proc_refs={"ch1": []},
        )

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics(channel_id="nonexistent")

        assert "error" in result


# ---------------------------------------------------------------------------
# BUG-021: topic_link_stats section
# ---------------------------------------------------------------------------


def _make_link(a: str, b: str, score: float) -> TopicLink:
    return TopicLink(topic_id_a=a, topic_id_b=b, similarity_score=score)


class TestCrossChannelTopicLinkStats:
    def _setup(self):
        # 5 topics across 3 channels.
        sources = [_make_source("ch1"), _make_source("ch2"), _make_source("ch3")]
        cards = [
            _make_topic_card("t:1", "ch1"),
            _make_topic_card("t:2", "ch2"),
            _make_topic_card("t:3", "ch3"),
            _make_topic_card("t:4", "ch1"),
            _make_topic_card("t:5", "ch2"),
        ]
        # 6 links: 4 cross-channel, 1 intra-channel, 1 spanning an unknown
        # (out-of-scope) topic that must always be excluded.
        links = [
            _make_link("t:1", "t:2", 0.9),  # ch1-ch2
            _make_link("t:1", "t:3", 0.8),  # ch1-ch3
            _make_link("t:2", "t:3", 0.7),  # ch2-ch3
            _make_link("t:4", "t:5", 0.6),  # ch1-ch2
            _make_link("t:1", "t:4", 0.5),  # ch1-ch1 (intra)
            _make_link("t:2", "t:999", 0.95),  # endpoint topic not in any card
        ]
        return sources, cards, links

    async def test_global_topic_link_stats(self):
        sources, cards, links = self._setup()
        repos = _make_mock_repos(
            sources,
            cards,
            bundles=[],
            proc_counts={"ch1": 1, "ch2": 1, "ch3": 1},
            links=links,
        )

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics()

        stats = result["topic_link_stats"]
        # The t:2↔t:999 link is dropped (t:999 is not an in-scope topic).
        assert stats["total_links"] == 5
        # avg over {0.9, 0.8, 0.7, 0.6, 0.5} = 0.7.
        assert stats["avg_similarity"] == 0.7

        pairs = {
            (p["channel_a"], p["channel_b"]): p["link_count"]
            for p in stats["links_by_channel_pair"]
        }
        assert pairs[("ch1", "ch2")] == 2
        assert pairs[("ch1", "ch3")] == 1
        assert pairs[("ch2", "ch3")] == 1
        assert pairs[("ch1", "ch1")] == 1

    async def test_topic_link_stats_respects_scope(self):
        sources, cards, links = self._setup()
        repos = _make_mock_repos(
            sources,
            cards,
            bundles=[],
            proc_counts={"ch1": 1, "ch2": 1, "ch3": 1},
            links=links,
        )

        @asynccontextmanager
        async def mock_stats_repos():
            yield repos

        with patch("tg_parser.services.analytics_service.stats_repos", mock_stats_repos):
            result = await get_cross_channel_analytics(allowed_channel_ids=["ch1", "ch2"])

        stats = result["topic_link_stats"]
        # ch3 is out of scope → links touching t:3 are excluded; t:999 too.
        # Remaining: (t:1,t:2), (t:4,t:5), (t:1,t:4) = 3.
        assert stats["total_links"] == 3
        pairs = {
            (p["channel_a"], p["channel_b"]): p["link_count"]
            for p in stats["links_by_channel_pair"]
        }
        assert pairs == {("ch1", "ch2"): 2, ("ch1", "ch1"): 1}
