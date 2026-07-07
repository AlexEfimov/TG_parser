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
    ProcessedDocument,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.processing.llm.errors import AnthropicBillingError
from tg_parser.processing.ports import LLMResponse
from tg_parser.services.resummarization_service import ResummarizationService
from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
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


def _doc(
    source_ref: str,
    *,
    text_clean: str,
    summary: str | None = None,
) -> ProcessedDocument:
    """Build a minimal ProcessedDocument for the bundle's source_ref."""
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref,
        channel_id="ch",
        processed_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        text_clean=text_clean,
        summary=summary,
    )


async def _seed_docs(session, docs: list[ProcessedDocument]) -> SAProcessedDocumentRepo:
    """Upsert processed_documents so re-summarize can fetch window text."""
    doc_repo = SAProcessedDocumentRepo(session)
    for doc in docs:
        await doc_repo.upsert(doc)
    return doc_repo


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
    async def test_happy_path_records_real_channel_metric(self, test_db):
        """F5-C P2 / #15 item #10: the ok outcome is attributed to the topic's
        primary source channel (card.sources[0]), not the legacy "-".

        Wave 2: the default seed card has ``new_items_since_last_summary=8`` >=
        ``RESUMMARIZE_TRIGGER_N`` (5), so the attempt is classified as a
        ``trigger="counter"`` selection.
        """
        from tg_parser.api.metrics import RESUMMARIZE_TOTAL

        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            before = RESUMMARIZE_TOTAL.labels(
                channel_id="ch", outcome="ok", trigger="counter"
            )._value.get()

            llm_payload = json.dumps(
                {
                    "summary": "New refreshed summary",
                    "scope_in": ["a", "b"],
                    "scope_out": ["c"],
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
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            after = RESUMMARIZE_TOTAL.labels(
                channel_id="ch", outcome="ok", trigger="counter"
            )._value.get()
            assert after == pytest.approx(before + 1.0)

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
    async def test_empty_anthropic_content_returns_llm_error_without_raise(self, test_db):
        """Regression: Anthropic HTTP 200 with empty content[] must not escape
        as IndexError — record llm_error and return cleanly (no exception
        through run_for_channel's logger.exception path)."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            with (
                _patch_resolve(provider="anthropic", model="claude-sonnet"),
                _patch_llm(_FakeLLMClient("")),
                patch(
                    "tg_parser.services.resummarization_service.record_resummarize_outcome"
                ) as record_mock,
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "llm_error"
            llm_error_calls = [
                c for c in record_mock.call_args_list if c.kwargs.get("status") == "llm_error"
            ]
            assert len(llm_error_calls) == 1
            assert llm_error_calls[0].kwargs["model"] == "anthropic/claude-sonnet"

            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary_version == 1
            assert updated.new_items_since_last_summary == 8

    @pytest.mark.asyncio
    async def test_markdown_fenced_json_response_parses_to_ok(self, test_db):
        """Regression: newer Sonnet models (claude-sonnet-4-5/-6) wrap their
        JSON in a ```json markdown fence.  A bare ``json.loads`` failed at
        char 0 with "Expecting value: line 1 column 1"; the service now
        strips the fence via ``extract_json_from_response`` (same helper
        topicization uses) so a fenced response yields a ``success`` outcome.
        """
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            inner = json.dumps(
                {
                    "summary": "Fenced refreshed summary",
                    "scope_in": ["fenced-a", "fenced-b"],
                    "scope_out": ["fenced-out"],
                }
            )
            fenced_payload = f"```json\n{inner}\n```"
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(fenced_payload)),
                _patch_embed(),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            assert outcome["version_no"] == 2

            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary == "Fenced refreshed summary"
            assert updated.scope_in == ["fenced-a", "fenced-b"]
            assert updated.summary_version == 2

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

    @pytest.mark.asyncio
    async def test_llm_call_exception_records_llm_error_and_propagates(self, test_db):
        """Observability gap fix: when ``generate_with_usage`` raises a
        generic exception (e.g. the prod httpx 404 from a retired model),
        ``record_resummarize_outcome`` must be called once with
        ``status='llm_error'`` (so ``ResummarizeLLMErrorRate`` can see a
        full-failure outage) AND the original exception must still propagate
        so ``run_for_channel``'s local accounting is unchanged."""

        class _Http404(Exception):
            pass

        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            err = _Http404("404 model_not_found: the model has been retired")
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(err)),
                patch(
                    "tg_parser.services.resummarization_service.record_resummarize_outcome"
                ) as record_mock,
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                with pytest.raises(_Http404):
                    await svc.resummarize_topic("topic:tg:ch:post:1")

            record_mock.assert_called_once()
            kwargs = record_mock.call_args.kwargs
            assert kwargs["status"] == "llm_error"
            assert kwargs["topic_id"] == "topic:tg:ch:post:1"
            assert kwargs["channel_id"] == "ch"
            assert kwargs["trigger"] == "counter"
            assert kwargs["model"] == "openai/gpt-4o-mini"

            # No new summary committed; counter untouched on failure.
            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary_version == 1
            assert updated.new_items_since_last_summary == 8

    @pytest.mark.asyncio
    async def test_billing_error_not_reclassified_as_llm_error(self, test_db):
        """Decision #13: ``AnthropicBillingError`` must re-raise UNCHANGED —
        the call-exception path must NOT record an ``llm_error`` outcome for
        it (that would mask the billing-pause signal)."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            err = AnthropicBillingError("credit balance too low")
            with (
                _patch_resolve(provider="anthropic", model="claude-sonnet"),
                _patch_llm(_FakeLLMClient(err)),
                patch(
                    "tg_parser.services.resummarization_service.record_resummarize_outcome"
                ) as record_mock,
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                with pytest.raises(AnthropicBillingError):
                    await svc.resummarize_topic("topic:tg:ch:post:1")

            # The billing error must propagate without any outcome being
            # recorded by the call-exception path.
            assert not any(
                call.kwargs.get("status") == "llm_error" for call in record_mock.call_args_list
            )

    @pytest.mark.asyncio
    async def test_locked_status_when_advisory_lock_unavailable(self, test_db, monkeypatch):
        """Gotcha #5: ``pg_try_advisory_xact_lock`` returns false when
        another worker holds the lock — re-summarize must short-circuit
        with ``status='locked'`` and NOT call the LLM, NOT bump the
        version, NOT touch the audit log."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            real_execute = card_repo.session.execute

            async def _fake_execute(stmt, params=None, *args, **kwargs):
                # Detect the advisory lock probe and force it to "false".
                sql = str(stmt)
                if "pg_try_advisory_xact_lock" in sql:

                    class _R:
                        def scalar(self):
                            return False

                    return _R()
                if params is None:
                    return await real_execute(stmt, *args, **kwargs)
                return await real_execute(stmt, params, *args, **kwargs)

            monkeypatch.setattr(card_repo.session, "execute", _fake_execute)

            llm_payload = json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(llm_payload)) as _llm_patch,
                _patch_embed() as embed_mock,
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome == {"status": "locked"}
            assert embed_mock.await_count == 0, "must not re-embed on lock fail"

            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary == "Old summary"
            assert updated.summary_version == 1

    @pytest.mark.asyncio
    async def test_version_raced_when_commit_returns_false(self, test_db, monkeypatch):
        """Real-bug #2: ``commit_resummary`` returns False when another
        worker bumped the version concurrently — the service must report
        ``status='version_raced'`` and NOT re-embed.  Audit snapshot is
        already written by this point (provenance preserved)."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            async def _fake_commit(*_args, **_kwargs):
                return False

            monkeypatch.setattr(card_repo, "commit_resummary", _fake_commit)

            llm_payload = json.dumps(
                {
                    "summary": "Refreshed",
                    "scope_in": ["a"],
                    "scope_out": ["b"],
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

            assert outcome["status"] == "version_raced"
            assert embed_mock.await_count == 0

            # The version snapshot of the *previous* state was written
            # before commit_resummary, so the audit trail still gets the
            # row even though the commit lost the race (Real-bug #2).
            versions = await ver_repo.list_by_topic("topic:tg:ch:post:1")
            assert len(versions) == 1
            assert versions[0].summary == "Old summary"

    @pytest.mark.asyncio
    async def test_reembed_failure_does_not_roll_back_commit(self, test_db):
        """Step 7 contract: re-embedding is best-effort.  An exception
        from ``run_topic_embedding`` must not undo the already-committed
        ``commit_resummary``.  Operators see a warn log; the user-visible
        summary is still the new one."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            llm_payload = json.dumps(
                {"summary": "Refreshed", "scope_in": ["a"], "scope_out": ["b"]}
            )
            embed_failure = patch(
                "tg_parser.services.resummarization_service.run_topic_embedding",
                new=AsyncMock(side_effect=RuntimeError("embedder down")),
            )
            with (
                _patch_resolve(),
                _patch_llm(_FakeLLMClient(llm_payload)),
                embed_failure,
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            assert outcome["version_no"] == 2

            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.summary == "Refreshed"
            assert updated.summary_version == 2

    @pytest.mark.asyncio
    async def test_singleton_type_is_preserved_after_resummarize(self, test_db):
        """Decision #4a: re-summarize must NOT mutate ``type`` — a
        singleton stays a singleton, even if the bundle now has many
        supports.  ``commit_resummary`` writes summary/scopes/version
        only, never touches the type column."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            llm_payload = json.dumps(
                {"summary": "Refreshed", "scope_in": ["a"], "scope_out": ["b"]}
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
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")
            assert outcome["status"] == "ok"

            updated = await card_repo.get_by_id("topic:tg:ch:post:1")
            assert updated is not None
            assert updated.type == TopicType.SINGLETON


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

    @pytest.mark.asyncio
    async def test_kill_switch_short_circuits_run_for_channel(self, test_db, monkeypatch):
        """``RESUMMARIZE_ENABLED=false`` ops kill-switch: ``run_for_channel``
        must return immediately without touching the candidate scan or LLM.
        This is the on-call escape hatch for runaway summarization."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session)
            ver_repo = SATopicCardVersionRepo(session)

            monkeypatch.setattr("tg_parser.config.settings.resummarize_enabled", False)

            calls = {"list": 0}
            real_list = card_repo.list_resummarize_candidates

            async def _spy_list(*args, **kwargs):
                calls["list"] += 1
                return await real_list(*args, **kwargs)

            monkeypatch.setattr(card_repo, "list_resummarize_candidates", _spy_list)

            svc = ResummarizationService(
                topic_card_repo=card_repo,
                topic_bundle_repo=bundle_repo,
                topic_card_version_repo=ver_repo,
            )
            summary = await svc.run_for_channel("ch", n_threshold=5)

            assert summary["candidates"] == 0
            assert summary["resummarized"] == 0
            assert summary["skipped_breakdown"] == {"disabled": 1}
            assert calls["list"] == 0, "kill-switch must short-circuit before list query"

    @pytest.mark.asyncio
    async def test_cap_tokens_breaks_loop_with_skipped_reason(self, test_db):
        """Triple-cap (Decision #12 / Gotcha #12): exhausting
        ``max_tokens_per_tick`` must break the candidate loop and account
        the rest under ``skipped_breakdown['cap_tokens']`` so we don't
        silently drop topics off the schedule."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)

            # Three eligible candidates.  Each "ok" run reports 150 tokens
            # (input 100 + output 50).  With cap_tokens=149 the first run
            # accumulates >= cap and the loop breaks before topic 2.
            for idx in range(3):
                tid = f"topic:tg:ch:post:{idx + 1}"
                card = _card(topic_id=tid, counter=10)
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

            llm_payload = json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
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
                summary = await svc.run_for_channel(
                    "ch",
                    n_threshold=5,
                    max_tokens_per_tick=149,
                )

            assert summary["candidates"] == 3
            # First run consumed 150 tokens (>= cap=149) — second iteration
            # hits the tokens guard before invoking the LLM and breaks.
            assert summary["resummarized"] == 1
            assert summary["skipped_breakdown"].get("cap_tokens", 0) >= 1


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


class _CapturingClient(_FakeLLMClient):
    """``_FakeLLMClient`` that records every user-prompt it is asked to send."""

    def __init__(self, response_text):
        super().__init__(response_text)
        self.prompts: list[str] = []
        self.closed = 0

    async def generate_with_usage(self, prompt, system_prompt=None, **kwargs):
        self.prompts.append(prompt)
        return await super().generate_with_usage(prompt, system_prompt, **kwargs)

    async def close(self):
        self.closed += 1


# ============================================================================
# O-1 / F-02: window documents must reach the LLM prompt
# ============================================================================


@pg_only
class TestItemsPayloadCarriesDocumentContent:
    @pytest.mark.asyncio
    async def test_document_summary_and_text_reach_user_prompt(self, test_db):
        """RED→GREEN (F-02): each window item must carry the document's
        ``summary`` and (truncated) ``text_clean`` so the LLM actually sees
        the material. Before O-1 the payload held only refs/scores and this
        assertion fails."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=3)
            ver_repo = SATopicCardVersionRepo(session)
            doc_repo = await _seed_docs(
                session,
                [
                    _doc(
                        "tg:ch:post:1",
                        text_clean="ACME shipped the widget-9000 flux capacitor upgrade.",
                        summary="Widget-9000 flux capacitor released.",
                    ),
                    _doc(
                        "tg:ch:post:2",
                        text_clean="Benchmarks show a 42% latency drop after the upgrade.",
                        summary="42% latency improvement measured.",
                    ),
                    _doc(
                        "tg:ch:post:3",
                        text_clean="Rollout to EU region scheduled for next quarter.",
                        summary="EU rollout planned next quarter.",
                    ),
                ],
            )

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            with _patch_resolve(), _patch_llm(client), _patch_embed():
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                    processed_document_repo=doc_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            assert len(client.prompts) == 1
            prompt = client.prompts[0]
            # A distinctive fact from text_clean AND a summary must be present.
            assert "flux capacitor" in prompt
            assert "42% latency" in prompt
            assert "Widget-9000 flux capacitor released." in prompt
            assert "EU rollout planned next quarter." in prompt

    @pytest.mark.asyncio
    async def test_long_text_clean_is_truncated(self, test_db):
        """The per-item ``text_clean`` snippet is bounded by
        ``RESUMMARIZE_ITEM_TEXT_MAX_CHARS`` — a long document does not enter
        the prompt whole (upper-bound guarantee for token growth)."""
        from tg_parser.services.resummarization_service import (
            RESUMMARIZE_ITEM_TEXT_MAX_CHARS,
        )

        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=1)
            ver_repo = SATopicCardVersionRepo(session)
            long_marker = "Z" * 5000
            tail_marker = "TAIL_SENTINEL_SHOULD_NOT_APPEAR"
            # Distinct sentinel for the summary field so the two caps are
            # asserted independently (Nit 1: summary must be capped too).
            long_summary = "Q" * 5000
            summary_tail = "SUMMARY_TAIL_SHOULD_NOT_APPEAR"
            doc_repo = await _seed_docs(
                session,
                [
                    _doc(
                        "tg:ch:post:1",
                        text_clean=long_marker + tail_marker,
                        summary=long_summary + summary_tail,
                    ),
                ],
            )

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            with _patch_resolve(), _patch_llm(client), _patch_embed():
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                    processed_document_repo=doc_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            prompt = client.prompts[0]
            # The full 5000-char blob must not be present; the tail beyond the
            # cap must be dropped — for BOTH text_clean and summary.
            assert long_marker not in prompt
            assert tail_marker not in prompt
            assert long_summary not in prompt
            assert summary_tail not in prompt
            # The longest contiguous run of each sentinel char in the prompt is
            # bounded by the cap (JSON-escaping cannot lengthen a run of a plain
            # ASCII letter). Asserts the upper bound for text ('Z') AND summary
            # ('Q').
            import re

            longest_z = max((len(m) for m in re.findall(r"Z+", prompt)), default=0)
            longest_q = max((len(m) for m in re.findall(r"Q+", prompt)), default=0)
            assert longest_z <= RESUMMARIZE_ITEM_TEXT_MAX_CHARS
            assert longest_q <= RESUMMARIZE_ITEM_TEXT_MAX_CHARS

    @pytest.mark.asyncio
    async def test_missing_document_ref_does_not_crash(self, test_db):
        """A bundle ref with no processed_documents row must leave the item's
        content empty rather than raising."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=3)
            ver_repo = SATopicCardVersionRepo(session)
            # Seed only ONE of the three window refs; the other two are missing.
            doc_repo = await _seed_docs(
                session,
                [
                    _doc(
                        "tg:ch:post:1",
                        text_clean="Only this document exists in the store.",
                        summary="Present doc.",
                    ),
                ],
            )

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            with _patch_resolve(), _patch_llm(client), _patch_embed():
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                    processed_document_repo=doc_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            prompt = client.prompts[0]
            assert "Only this document exists" in prompt
            # Missing refs are still represented as items (refs present).
            assert "tg:ch:post:2" in prompt
            assert "tg:ch:post:3" in prompt

    @pytest.mark.asyncio
    async def test_window_documents_fetched_in_single_batch(self, test_db, monkeypatch):
        """Batch, not N+1: window docs come from ONE ``get_by_source_refs``
        call carrying all window refs."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=4)
            ver_repo = SATopicCardVersionRepo(session)
            doc_repo = await _seed_docs(
                session,
                [
                    _doc(f"tg:ch:post:{i}", text_clean=f"doc {i}", summary=f"sum {i}")
                    for i in range(1, 5)
                ],
            )

            calls: list[list[str]] = []
            real = doc_repo.get_by_source_refs

            async def _spy(refs):
                calls.append(list(refs))
                return await real(refs)

            monkeypatch.setattr(doc_repo, "get_by_source_refs", _spy)

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            with _patch_resolve(), _patch_llm(client), _patch_embed():
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                    processed_document_repo=doc_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            assert len(calls) == 1, "window docs must be fetched in a single batch"
            assert set(calls[0]) == {f"tg:ch:post:{i}" for i in range(1, 5)}

    @pytest.mark.asyncio
    async def test_no_repo_wired_still_succeeds_with_empty_content(self, test_db):
        """Back-compat: without a processed_document_repo the service still
        works (content simply absent) — legacy callers must not break."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=2)
            ver_repo = SATopicCardVersionRepo(session)

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            with _patch_resolve(), _patch_llm(client), _patch_embed():
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            # Refs still present even with no content source.
            assert "tg:ch:post:1" in client.prompts[0]


# ============================================================================
# O-9a (F-11 part): one LLM client per run_for_channel tick
# ============================================================================


@pg_only
class TestClientLifecyclePerTick:
    @pytest.mark.asyncio
    async def test_create_llm_client_called_once_for_multiple_candidates(self, test_db):
        """O-9a: ``create_llm_client`` is invoked exactly once per
        ``run_for_channel`` regardless of the number of candidates, and the
        single client is closed at the end of the tick."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)

            for idx in range(3):
                tid = f"topic:tg:ch:post:{idx + 1}"
                card = _card(topic_id=tid, counter=10).model_copy(
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
                await bundle_repo.upsert(_bundle_with_items(tid, 3))

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            create_calls = {"n": 0}

            def _factory(**_kwargs):
                create_calls["n"] += 1
                return client

            with (
                _patch_resolve(),
                patch(
                    "tg_parser.services.resummarization_service.create_llm_client",
                    side_effect=_factory,
                ),
                _patch_embed(),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                summary = await svc.run_for_channel("ch", n_threshold=5, max_topics=3)

            assert summary["resummarized"] == 3
            assert create_calls["n"] == 1, "one client per tick, not per topic"
            assert client.closed == 1, "the single per-tick client is closed once"

    @pytest.mark.asyncio
    async def test_no_client_created_when_no_candidates(self, test_db):
        """The handshake must not be paid when there are no candidates — the
        client is created only AFTER the candidate check."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            bundle_repo = SATopicBundleRepo(session)
            ver_repo = SATopicCardVersionRepo(session)

            await card_repo.upsert(_card(counter=2))
            await bundle_repo.upsert(_bundle_with_items("topic:tg:ch:post:1", 3))

            create_calls = {"n": 0}

            def _factory(**_kwargs):
                create_calls["n"] += 1
                return _CapturingClient("{}")

            with (
                _patch_resolve(),
                patch(
                    "tg_parser.services.resummarization_service.create_llm_client",
                    side_effect=_factory,
                ),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                summary = await svc.run_for_channel("ch", n_threshold=5)

            assert summary["candidates"] == 0
            assert create_calls["n"] == 0, "no handshake when there is nothing to do"

    @pytest.mark.asyncio
    async def test_standalone_resummarize_topic_creates_and_closes_own_client(self, test_db):
        """The standalone path (force_resummarize / CLI) calls
        ``resummarize_topic`` without an injected client — it must create one
        in-place and close it."""
        async with test_db.processing_storage_session() as session:
            card_repo, bundle_repo = await _seed(session, n_items=2)
            ver_repo = SATopicCardVersionRepo(session)

            client = _CapturingClient(
                json.dumps({"summary": "S", "scope_in": ["a"], "scope_out": ["b"]})
            )
            create_calls = {"n": 0}

            def _factory(**_kwargs):
                create_calls["n"] += 1
                return client

            with (
                _patch_resolve(),
                patch(
                    "tg_parser.services.resummarization_service.create_llm_client",
                    side_effect=_factory,
                ),
                _patch_embed(),
            ):
                svc = ResummarizationService(
                    topic_card_repo=card_repo,
                    topic_bundle_repo=bundle_repo,
                    topic_card_version_repo=ver_repo,
                )
                outcome = await svc.resummarize_topic("topic:tg:ch:post:1")

            assert outcome["status"] == "ok"
            assert create_calls["n"] == 1
            assert client.closed == 1, "standalone path owns and closes its client"
