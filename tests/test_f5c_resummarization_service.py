"""F5-C ResummarizationService unit + integration tests.

Mocks LLMClient + embedding wrapper to keep tests fast (no LLM calls,
no real embedding API), but uses a real Postgres session for the
advisory-lock + commit_resummary path so we exercise the production
storage layer.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.processing.ports import LLMResponse
from tg_parser.services.resummarization_service import ResummarizationService
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo
from tg_parser.storage.sqlalchemy.topic_card_version_repo import SATopicCardVersionRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _card(
    *,
    topic_id: str = "topic:tg:ch:post:1",
    summary_version: int = 1,
    counter: int = 8,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title="Test Topic",
        summary="Old summary",
        scope_in=["old-in"],
        scope_out=["old-out"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="ch",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:ch:post:1",
                score=1.0,
            )
        ],
        sources=["ch"],
        updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        summary_version=summary_version,
        new_items_since_last_summary=counter,
    )


def _bundle_with_items(topic_id: str, n: int) -> TopicBundle:
    items = [
        BundleItem(
            channel_id="ch",
            message_id=str(idx + 1),
            message_type=MessageType.POST,
            source_ref=f"tg:ch:post:{idx + 1}",
            role=BundleItemRole.ANCHOR if idx == 0 else BundleItemRole.SUPPORTING,
            score=1.0 - 0.05 * idx,
            justification=f"item-{idx}",
        )
        for idx in range(n)
    ]
    return TopicBundle(
        topic_id=topic_id,
        items=items,
        updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
    )


@pg_only
async def _seed(session, topic_id: str = "topic:tg:ch:post:1", n_items: int = 6):
    card_repo = SATopicCardRepo(session)
    bundle_repo = SATopicBundleRepo(session)
    await card_repo.upsert(_card(topic_id=topic_id))
    bundle = _bundle_with_items(topic_id, n_items)
    # SATopicBundleRepo.upsert requires the topic to already exist.
    await bundle_repo.upsert(bundle)
    return card_repo, bundle_repo


# ----------------------------------------------------------------------------
# Mock helpers
# ----------------------------------------------------------------------------


class _FakeLLMClient:
    def __init__(self, response_text: str | Exception):
        self._response = response_text
        self.input_tokens = 100
        self.output_tokens = 50

    async def generate_with_usage(self, prompt, system_prompt=None, **kwargs):
        if isinstance(self._response, Exception):
            raise self._response
        return LLMResponse(
            text=self._response, input_tokens=self.input_tokens, output_tokens=self.output_tokens
        )

    async def close(self):  # noqa: D401
        pass


def _patch_llm(client: _FakeLLMClient):
    return patch(
        "tg_parser.services.resummarization_service.create_llm_client",
        return_value=client,
    )


def _patch_resolve(provider: str = "openai", model: str = "gpt-4o-mini"):
    return patch(
        "tg_parser.services.resummarization_service.resolve_llm_config",
        return_value=(provider, "fake-key", model),
    )


def _patch_embed():
    return patch(
        "tg_parser.services.resummarization_service.run_topic_embedding",
        new=AsyncMock(return_value={"embedded_count": 1, "skipped_count": 0, "total_count": 1}),
    )


# ============================================================================
# Tests
# ============================================================================


@pg_only
class TestResummarizeTopic:
    @pytest.mark.asyncio
    async def test_happy_path_writes_version_commits_and_reembeds(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            llm_payload = json.dumps(
                {
                    "summary": "New refreshed summary",
                    "scope_in": ["new-aspect-a", "new-aspect-b"],
                    "scope_out": ["new-out"],
                }
            )
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(llm_payload)),
                _patch_embed() as embed_mock,
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            assert outcome["version_no"] == 2
            assert outcome["tokens"] == 150
            assert embed_mock.await_count == 1

            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary == "New refreshed summary"
            assert updated.summary_version == 2
            assert updated.new_items_since_last_summary == 0
            assert updated.last_summarized_at is not None

            versions = await ver_repo.list_by_topic("topic:tg:ch:post:1")
            # Snapshot of the *previous* state was written.
            assert len(versions) == 1
            assert versions[0].version_no == 1
            assert versions[0].summary == "Old summary"
            assert versions[0].llm_provider == "openai"
            assert versions[0].llm_model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_no_card_status(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            svc = ResummarizationService(
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                topic_card_version_repo=ver_repo,
            )
            outcome = await svc.resummarize_topic("topic:does:not:exist")
            assert outcome["status"] == "no_card"

    @pytest.mark.asyncio
    async def test_no_bundle_status(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_card())
            svc = ResummarizationService(
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                topic_card_version_repo=ver_repo,
            )
            outcome = await svc.resummarize_topic("topic:tg:ch:post:1")
            assert outcome["status"] == "no_bundle"

    @pytest.mark.asyncio
    async def test_llm_error_status_on_unparseable_response(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient("this is not JSON")),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "llm_error"
            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            # Counter unchanged on failure.
            assert updated is not None
            assert updated.summary_version == 1
            assert updated.new_items_since_last_summary == 8

    @pytest.mark.asyncio
    async def test_empty_scope_in_returns_empty_scope(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            llm_payload = json.dumps({"summary": "x", "scope_in": [], "scope_out": []})
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(llm_payload)),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "empty_scope"
            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary_version == 1

    @pytest.mark.asyncio
    async def test_anthropic_billing_error_propagates(self, test_db):
        """Gotcha #16: must not be swallowed inside resummarize_topic."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            err = AnthropicBillingError("credit balance too low")
            with (
                _patch_resolve(provider="anthropic", model="claude-sonnet"),
                _patch_llm(_FakeLLMClient(err)),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                with pytest.raises(AnthropicBillingError):
                    await svc.resummarize_topic("topic:tg:ch:post:1")


@pg_only
class TestRunForChannel:
    @pytest.mark.asyncio
    async def test_iterates_candidates_and_aggregates(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)

            for idx in range(3):
                tid = f"topic:tg:ch:post:{idx + 1}"
                card = _card(topic_id=tid, counter=10)
                # Distinct topic id by varying anchor message id.
                card = card.model_copy(
                    update={
                        "anchors": [
                            Anchor(
                                channel_id="ch",
                                message_id=str(idx + 1),
                                message_type=MessageType.POST,
                                anchor_ref=f"tg:ch:post:{idx + 1}",
                                score=1.0,
                            )
                        ]
                    }
                )
                await card_repo.upsert(card)
                await bundle_repo.upsert(_bundle_with_items(tid, 5))

            llm_payload = json.dumps(
                {
                    "summary": "S",
                    "scope_in": ["a"],
                    "scope_out": ["b"],
                }
            )
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(llm_payload)),
                _patch_embed(),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                summary = await svc.run_for_channel("ch", n_threshold=5, max_topics=2)

            # Capped at 2 of 3 candidates.
            assert summary["candidates"] == 3
            assert summary["resummarized"] == 2
            assert summary["tokens"] > 0

    @pytest.mark.asyncio
    async def test_run_for_channel_below_threshold_returns_zero(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)

            await card_repo.upsert(_card(counter=2))
            await bundle_repo.upsert(_bundle_with_items("topic:tg:ch:post:1", 3))

            svc = ResummarizationService(
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                topic_card_version_repo=ver_repo,
            )
            summary = await svc.run_for_channel("ch", n_threshold=5)
            assert summary == {
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "skipped_breakdown": {},
                "tokens": 0,
            }

    @pytest.mark.asyncio
    async def test_run_for_channel_propagates_billing_error(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            with (
                _patch_resolve(provider="anthropic", model="claude-sonnet"),
                _patch_llm(_FakeLLMClient(AnthropicBillingError("budget"))),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                with pytest.raises(AnthropicBillingError):
                    await svc.run_for_channel("ch", n_threshold=5)


@pg_only
class TestInputWindow:
    @pytest.mark.asyncio
    async def test_uses_top_n_items_not_tail(self, test_db, monkeypatch):
        """Gotcha #6: input must be bundle.items[:N] not [-N:]."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=10)
            ver_repo = SATopicCardVersionRepo(session)

            captured_prompts: list[str] = []

            class _CapturingClient(_FakeLLMClient):
                async def generate_with_usage(self, prompt, system_prompt=None, **kwargs):
                    captured_prompts.append(prompt)
                    return await super().generate_with_usage(prompt, system_prompt, **kwargs)

            monkeypatch.setattr("tg_parser.config.settings.resummarize_input_window_n", 3)
            llm_payload = json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})

            with (
                _patch_resolve(),
                _patch_llm(_CapturingClient(llm_payload)),
                _patch_embed(),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")
            assert outcome["status"] == "ok"
            assert len(captured_prompts) == 1
            prompt = captured_prompts[0]
            # Top-3 items must include the anchor (post:1) and post:2 / post:3
            # (highest scores by add_items sort), NOT post:8 / post:9 / post:10
            # (which would be the alphabetical / lowest-score tail).
            assert "tg:ch:post:1" in prompt
            assert "tg:ch:post:2" in prompt
            assert "tg:ch:post:3" in prompt
            assert "tg:ch:post:9" not in prompt
            assert "tg:ch:post:10" not in prompt
