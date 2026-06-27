"""BUG-071: topicization token-burn regression tests.

Covers the three fixes from the BUG-071 handoff:

* Fix 1 — a ``max_tokens`` truncation (``stop_reason="max_tokens"``) is NOT
  retried with the identical oversized request (the pre-fix behaviour re-issued
  it up to 3x, each a full charged Sonnet call). Instead the request is shrunk
  (batch split / token-budget scale) and retried once at the smaller size.
* Fix 3 — every detected truncation increments ``tg_parser_llm_truncation_total``.
* Fix 2 — the full re-escalation in ``run_incremental_topicization`` is gated by
  a persisted cooldown: it escalates once, is skipped within the TTL, and is
  allowed again after the TTL elapses.
"""

import contextlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.api.metrics import (
    LLM_TRUNCATION_TOTAL,
    TOPICIZATION_FAILED_BATCHES_TOTAL,
)
from tg_parser.domain.models import ProcessedDocument
from tg_parser.processing.ports import LLMResponse
from tg_parser.processing.topicization import (
    TopicizationBatchTruncatedError,
    TopicizationPipelineImpl,
)
from tg_parser.services.topicization_service import (
    _reescalation_in_cooldown,
    _reescalation_marker_ref,
    run_incremental_topicization,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    source_ref: str,
    text_clean: str = "some text content",
    summary: str | None = "summary",
    topics: list[str] | None = None,
    channel_id: str = "labdiagnostica",
) -> ProcessedDocument:
    parts = source_ref.split(":")
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=parts[-1],
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=text_clean,
        summary=summary,
        topics=topics or [],
    )


def _resp(text: str, stop_reason: str | None = None) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=10, output_tokens=10, stop_reason=stop_reason)


def _valid_topics_json(ref: str) -> str:
    return json.dumps(
        {
            "topics": [
                {
                    "type": "cluster",
                    "title": f"Topic for {ref}",
                    "summary": "s",
                    "scope_in": ["a"],
                    "scope_out": ["b"],
                    "anchors": [
                        {"source_ref": ref, "score": 0.9},
                        {"source_ref": ref, "score": 0.8},
                    ],
                }
            ]
        }
    )


def _make_pipeline(generate_side_effect) -> TopicizationPipelineImpl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    llm.generate_with_usage = AsyncMock(side_effect=generate_side_effect)

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []
    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=topic_card_repo,
        topic_bundle_repo=AsyncMock(),
    )


def _truncation_metric_value(stage: str) -> float:
    # provider for an AsyncMock client resolves to "unknown" via
    # get_provider_from_client; model is the pipeline's model_id ("test-model").
    return (
        LLM_TRUNCATION_TOTAL.labels(provider="unknown", model="test-model", stage=stage)
        ._value.get()
    )


# ===========================================================================
# Fix 1 + Fix 3 — _generate_topics_batch truncation handling
# ===========================================================================


class TestGenerateBatchTruncation:
    @pytest.mark.asyncio
    async def test_truncation_splits_instead_of_reissuing_identical(self):
        """A truncated full batch is split in half — the identical oversized
        request is sent exactly ONCE, never 3x."""
        full_batch_calls = 0

        async def side_effect(*, prompt, **kwargs):
            nonlocal full_batch_calls
            has_300 = "post:300" in prompt
            has_301 = "post:301" in prompt
            if has_300 and has_301:
                # The full (oversized) batch — truncates.
                full_batch_calls += 1
                return _resp("{partial truncated json", stop_reason="max_tokens")
            # A single-doc sub-batch fits → valid JSON.
            ref = "tg:labdiagnostica:post:300" if has_300 else "tg:labdiagnostica:post:301"
            return _resp(_valid_topics_json(ref))

        pipeline = _make_pipeline(side_effect)
        candidates = [
            {"source_ref": "tg:labdiagnostica:post:300", "text_clean": "x", "summary": "", "topics": []},
            {"source_ref": "tg:labdiagnostica:post:301", "text_clean": "y", "summary": "", "topics": []},
        ]

        with patch("tg_parser.api.metrics.record_llm_json_parse_retry") as mock_json_retry:
            topics = await pipeline._generate_topics_batch(candidates)

        # The identical oversized request was issued exactly once (not 3x).
        assert full_batch_calls == 1
        # Total = 1 truncated full batch + 2 successful single-doc sub-batches.
        assert pipeline.llm_client.generate_with_usage.await_count == 3
        # The JSON-repair retry path was NOT taken (truncation != JSONDecodeError).
        mock_json_retry.assert_not_called()
        # Both halves produced their topic.
        assert len(topics) == 2

    @pytest.mark.asyncio
    async def test_truncation_increments_metric(self):
        before = _truncation_metric_value("topicization_generate")

        async def side_effect(*, prompt, **kwargs):
            if "post:300" in prompt and "post:301" in prompt:
                return _resp("{trunc", stop_reason="max_tokens")
            ref = "tg:labdiagnostica:post:300" if "post:300" in prompt else "tg:labdiagnostica:post:301"
            return _resp(_valid_topics_json(ref))

        pipeline = _make_pipeline(side_effect)
        candidates = [
            {"source_ref": "tg:labdiagnostica:post:300", "text_clean": "x", "summary": "", "topics": []},
            {"source_ref": "tg:labdiagnostica:post:301", "text_clean": "y", "summary": "", "topics": []},
        ]
        await pipeline._generate_topics_batch(candidates)

        after = _truncation_metric_value("topicization_generate")
        # Exactly one truncation event (the single full-batch truncation).
        assert after - before == 1

    @pytest.mark.asyncio
    async def test_single_candidate_truncation_scales_tokens_then_drops(self):
        """A single candidate can't be split — it scales max_tokens (capped) and,
        if still truncating, drops the batch by RAISING (so topicize_channel can
        count it as a failed batch — BUG-018), WITHOUT a 3x identical re-burn."""
        seen_max_tokens: list[int] = []

        async def side_effect(*, prompt, max_tokens, **kwargs):
            seen_max_tokens.append(max_tokens)
            return _resp("{trunc", stop_reason="max_tokens")

        pipeline = _make_pipeline(side_effect)
        candidates = [
            {"source_ref": "tg:labdiagnostica:post:300", "text_clean": "x", "summary": "", "topics": []},
        ]
        # BUG-071 (Bugbot follow-up): a full drop now surfaces as a failure.
        with pytest.raises(TopicizationBatchTruncatedError):
            await pipeline._generate_topics_batch(candidates)

        # Budget escalates 8192 -> 16384 -> 32768 (cap) then stops. Each value
        # appears once; crucially the SAME budget is never re-issued 3x.
        assert seen_max_tokens == [8192, 16384, 32768]
        assert len(seen_max_tokens) == len(set(seen_max_tokens))

    @pytest.mark.asyncio
    async def test_partial_salvage_does_not_raise(self):
        """If one half truncation-drops but the other yields topics, the batch is
        a PARTIAL success: the salvaged topics are returned and NO failure is
        raised (only a complete drop is a batch failure)."""

        async def side_effect(*, prompt, max_tokens, **kwargs):
            has_300 = "post:300" in prompt
            has_301 = "post:301" in prompt
            if has_300 and has_301:
                # Full batch truncates → split into post:300 | post:301.
                return _resp("{trunc", stop_reason="max_tokens")
            if has_301:
                # post:301 single-doc keeps truncating at every budget → drops.
                return _resp("{trunc", stop_reason="max_tokens")
            # post:300 single-doc fits → valid JSON.
            return _resp(_valid_topics_json("tg:labdiagnostica:post:300"))

        pipeline = _make_pipeline(side_effect)
        candidates = [
            {"source_ref": "tg:labdiagnostica:post:300", "text_clean": "x", "summary": "", "topics": []},
            {"source_ref": "tg:labdiagnostica:post:301", "text_clean": "y", "summary": "", "topics": []},
        ]
        topics = await pipeline._generate_topics_batch(candidates)
        # post:300 salvaged; post:301 dropped but did NOT fail the whole batch.
        assert len(topics) == 1


# ===========================================================================
# Bugbot follow-up — truncation-drops are counted as failed batches (BUG-018)
# ===========================================================================


def _make_pipeline_with_docs(docs: list[ProcessedDocument]) -> TopicizationPipelineImpl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    processed_repo = AsyncMock()
    processed_repo.list_by_channel = AsyncMock(return_value=docs)
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []
    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=processed_repo,
        topic_card_repo=topic_card_repo,
        topic_bundle_repo=AsyncMock(),
    )


class TestTopicizeChannelTruncationFailedBatches:
    """Bugbot follow-up: a truncation-drop must be counted in ``failed_batches``
    so a channel run that drops all/most batches via ``max_tokens`` reports a
    systemic failure (BUG-018 exit code 2), NOT ``failed_batches=0`` (which the
    CLI renders as the misleading "insufficient data" hint)."""

    @pytest.mark.asyncio
    async def test_multibatch_all_truncation_drops_counts_failed_batches(self):
        docs = [_make_doc(f"tg:kdl_ru:post:{i}", channel_id="kdl_ru") for i in range(120)]
        pipeline = _make_pipeline_with_docs(docs)

        async def _always_truncation_drop(batch, **kwargs):
            raise TopicizationBatchTruncatedError(len(batch))

        with patch.object(
            pipeline, "_generate_topics_batch", side_effect=_always_truncation_drop
        ):
            topic_cards = await pipeline.topicize_channel(channel_id="kdl_ru")

        assert topic_cards == []
        assert pipeline.total_batches >= 2
        # The regression: every dropped batch is counted (not 0).
        assert pipeline.failed_batches == pipeline.total_batches
        assert pipeline.last_batch_error is not None
        assert "TopicizationBatchTruncatedError" in pipeline.last_batch_error
        # Systemic-fail ratio (CLI exits 2): failed/total > 0.5.
        assert pipeline.failed_batches / pipeline.total_batches > 0.5

    @pytest.mark.asyncio
    async def test_single_batch_truncation_drop_counts_failure_without_raising(self):
        docs = [_make_doc(f"tg:kdl_ru:post:{i}", channel_id="kdl_ru") for i in range(10)]
        pipeline = _make_pipeline_with_docs(docs)

        async def _always_truncation_drop(batch, **kwargs):
            raise TopicizationBatchTruncatedError(len(batch))

        with patch.object(
            pipeline, "_generate_topics_batch", side_effect=_always_truncation_drop
        ):
            # Must NOT raise — the single-batch truncation-drop degrades to 0
            # topics + failed_batches=1 (systemic-fail), not a CLI crash.
            topic_cards = await pipeline.topicize_channel(channel_id="kdl_ru")

        assert topic_cards == []
        assert pipeline.total_batches == 1
        assert pipeline.failed_batches == 1
        assert pipeline.last_batch_error is not None
        assert "TopicizationBatchTruncatedError" in pipeline.last_batch_error


# ===========================================================================
# BUG-071 observability — tg_parser_topicization_failed_batches_total
# The direct first-class counter must increment at EVERY failed_batches site in
# topicize_channel (no double-count, no missed path) so the metric stays
# consistent with the log/CLI failed_batches number, and must count BOTH
# truncation-drops and genuine non-truncation batch failures.
# ===========================================================================


def _failed_batches_metric_value(stage: str, channel_id: str) -> float:
    # .labels(...) creates the series at 0 if it does not exist yet, so a
    # before-read is always safe and returns 0.0 for a fresh (stage, channel_id).
    return (
        TOPICIZATION_FAILED_BATCHES_TOTAL.labels(stage=stage, channel_id=channel_id)
        ._value.get()
    )


class TestFailedBatchesMetric:
    @pytest.mark.asyncio
    async def test_multibatch_all_truncation_drops_increment_metric_per_batch(self):
        # Unique channel_id isolates this test's counter series from others.
        channel = "kdl_metric_mb_trunc"
        docs = [_make_doc(f"tg:{channel}:post:{i}", channel_id=channel) for i in range(120)]
        pipeline = _make_pipeline_with_docs(docs)
        before = _failed_batches_metric_value("topicization_generate", channel)

        async def _always_truncation_drop(batch, **kwargs):
            raise TopicizationBatchTruncatedError(len(batch))

        with patch.object(
            pipeline, "_generate_topics_batch", side_effect=_always_truncation_drop
        ):
            await pipeline.topicize_channel(channel_id=channel)

        after = _failed_batches_metric_value("topicization_generate", channel)
        # The metric delta exactly equals failed_batches (== total_batches here),
        # proving per-batch consistency with the log/CLI number (no double-count).
        assert pipeline.total_batches >= 2
        assert pipeline.failed_batches == pipeline.total_batches
        assert after - before == pipeline.failed_batches

    @pytest.mark.asyncio
    async def test_single_batch_truncation_drop_increments_metric_once(self):
        channel = "kdl_metric_sb_trunc"
        docs = [_make_doc(f"tg:{channel}:post:{i}", channel_id=channel) for i in range(10)]
        pipeline = _make_pipeline_with_docs(docs)
        before = _failed_batches_metric_value("topicization_generate", channel)

        async def _always_truncation_drop(batch, **kwargs):
            raise TopicizationBatchTruncatedError(len(batch))

        with patch.object(
            pipeline, "_generate_topics_batch", side_effect=_always_truncation_drop
        ):
            await pipeline.topicize_channel(channel_id=channel)

        after = _failed_batches_metric_value("topicization_generate", channel)
        assert pipeline.total_batches == 1
        assert pipeline.failed_batches == 1
        assert after - before == 1

    @pytest.mark.asyncio
    async def test_multibatch_genuine_failure_increments_metric(self):
        """The counter is BROADER than the truncation counter: a non-truncation
        batch failure (RuntimeError) is still counted as a failed batch."""
        channel = "kdl_metric_mb_err"
        docs = [_make_doc(f"tg:{channel}:post:{i}", channel_id=channel) for i in range(120)]
        pipeline = _make_pipeline_with_docs(docs)
        before = _failed_batches_metric_value("topicization_generate", channel)

        async def _always_runtime_error(batch, **kwargs):
            raise RuntimeError("boom (non-truncation)")

        with patch.object(
            pipeline, "_generate_topics_batch", side_effect=_always_runtime_error
        ):
            await pipeline.topicize_channel(channel_id=channel)

        after = _failed_batches_metric_value("topicization_generate", channel)
        assert pipeline.failed_batches == pipeline.total_batches
        assert after - before == pipeline.failed_batches
        assert "RuntimeError" in (pipeline.last_batch_error or "")

    @pytest.mark.asyncio
    async def test_single_batch_genuine_failure_increments_metric_then_raises(self):
        """The single-batch non-truncation path increments the metric once and
        then re-raises (covers the third failed_batches site)."""
        channel = "kdl_metric_sb_err"
        docs = [_make_doc(f"tg:{channel}:post:{i}", channel_id=channel) for i in range(10)]
        pipeline = _make_pipeline_with_docs(docs)
        before = _failed_batches_metric_value("topicization_generate", channel)

        async def _always_runtime_error(batch, **kwargs):
            raise RuntimeError("boom (non-truncation)")

        with patch.object(
            pipeline, "_generate_topics_batch", side_effect=_always_runtime_error
        ):
            with pytest.raises(RuntimeError):
                await pipeline.topicize_channel(channel_id=channel)

        after = _failed_batches_metric_value("topicization_generate", channel)
        assert pipeline.failed_batches == 1
        assert after - before == 1


# ===========================================================================
# Fix 2 — re-escalation cooldown gate
# ===========================================================================


class _FakeFailureRepo:
    """In-memory ProcessingFailureRepo stand-in (no Postgres needed)."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def list_failures(self, channel_id=None, limit=None):
        return [
            dict(r)
            for r in self.rows.values()
            if channel_id is None or r["channel_id"] == channel_id
        ]

    async def record_failure(
        self,
        source_ref,
        channel_id,
        attempts,
        error_class,
        error_message,
        error_details=None,
    ):
        self.rows[source_ref] = {
            "source_ref": source_ref,
            "channel_id": channel_id,
            "attempts": attempts,
            "error_class": error_class,
            "error_message": error_message,
            "last_attempt_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    async def delete_failure(self, source_ref):
        self.rows.pop(source_ref, None)


def _zero_card_repos():
    doc = _make_doc("tg:labdiagnostica:post:900")
    processed_repo = AsyncMock()
    processed_repo.get_by_source_ref.return_value = doc
    processed_repo.list_by_channel.return_value = [doc]
    # No real .session attribute → forces the gate to use the injected fake repo.
    del processed_repo.session

    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = []  # 0 cards → escalation candidate
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    return doc, processed_repo, topic_card_repo, topic_bundle_repo


@contextlib.contextmanager
def _patch_incremental_phase(*, assign_return, discover_return):
    """Stub the cheap incremental Phase 1/2 path so it makes NO real LLM call.

    BUG-071 (Bugbot Finding 1): a cooled-down zero-card channel now FALLS THROUGH
    to the incremental path instead of returning early, so the cooldown tests must
    neutralise ``resolve_llm_config`` / ``create_llm_client`` and the two pipeline
    methods (``assign_documents_to_topics`` keyword Phase 1, ``_discover_single_batch``
    LLM Phase 2) to keep the test offline and deterministic.
    """
    with (
        patch(
            "tg_parser.services.topicization_service.resolve_llm_config",
            return_value=("anthropic", "key", "model"),
        ),
        patch("tg_parser.services.topicization_service.create_llm_client") as mk_client,
        patch.object(
            TopicizationPipelineImpl,
            "assign_documents_to_topics",
            new_callable=AsyncMock,
            return_value=assign_return,
        ) as assign_mock,
        patch.object(
            TopicizationPipelineImpl,
            "_discover_single_batch",
            new_callable=AsyncMock,
            return_value=discover_return,
        ) as discover_mock,
    ):
        client = AsyncMock()
        client.close = AsyncMock()
        client.model = "model"
        # compute_prompt_id is sync in real clients — keep it sync so the
        # pipeline __init__ doesn't leave an un-awaited AsyncMock coroutine.
        client.compute_prompt_id = MagicMock(return_value="prompt-id")
        mk_client.return_value = client
        yield assign_mock, discover_mock


class TestReEscalationCooldown:
    @pytest.mark.asyncio
    async def test_escalates_then_skips_in_cooldown_then_allows_after_ttl(self):
        doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
        failure_repo = _FakeFailureRepo()
        marker_ref = _reescalation_marker_ref("labdiagnostica")

        # Full re-escalation keeps producing 0 cards (the BUG-071 truncation class).
        full_result = {"topics_count": 0, "total_tokens": 50}

        with (
            patch(
                "tg_parser.services.topicization_service.run_topicization",
                new_callable=AsyncMock,
                return_value=full_result,
            ) as mock_full,
            # The cooled-down tick (step 2) falls through to the incremental path.
            _patch_incremental_phase(
                assign_return=([], [doc.source_ref]),
                discover_return=([], [], [doc.source_ref], 0),
            ) as (assign_mock, _discover_mock),
        ):
            # 1) First tick: escalates, records the marker (attempts=1).
            await run_incremental_topicization(
                "labdiagnostica",
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )
            assert mock_full.await_count == 1
            assert failure_repo.rows[marker_ref]["attempts"] == 1
            assert assign_mock.await_count == 0  # full re-escalation, not incremental

            # 2) Second tick within TTL: full re-escalation skipped, but the cheap
            # incremental Phase 1/2 path STILL runs on the new docs (Finding 1).
            await run_incremental_topicization(
                "labdiagnostica",
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )
            assert mock_full.await_count == 1  # unchanged → full re-escalation skipped
            assert assign_mock.await_count == 1  # but incremental Phase 1 DID run

            # 3) Simulate the TTL elapsing by ageing the persisted marker.
            failure_repo.rows[marker_ref]["last_attempt_at"] = (
                datetime.now(UTC) - timedelta(seconds=7200)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            await run_incremental_topicization(
                "labdiagnostica",
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )
            assert mock_full.await_count == 2  # re-escalation allowed again
            assert failure_repo.rows[marker_ref]["attempts"] == 2  # attempts bumped

    @pytest.mark.asyncio
    async def test_successful_escalation_clears_marker(self):
        doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
        # BUG-071 (Bugbot Finding 2): the marker is cleared on the PERSISTED card
        # count, not the in-memory ``topics_count``. Simulate that the channel had
        # 0 cards before the run (1st list_by_channel) and >0 AFTER it (the
        # recount), i.e. upserts actually persisted.
        topic_card_repo.list_by_channel.side_effect = [[], [object()]]
        failure_repo = _FakeFailureRepo()
        marker_ref = _reescalation_marker_ref("labdiagnostica")
        # Pre-existing marker from an earlier failed run.
        await failure_repo.record_failure(
            source_ref=marker_ref,
            channel_id="labdiagnostica",
            attempts=1,
            error_class="TopicizationReEscalation",
            error_message="prior failure",
        )
        # Age it out so this tick is allowed to escalate.
        failure_repo.rows[marker_ref]["last_attempt_at"] = (
            datetime.now(UTC) - timedelta(seconds=7200)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        with patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            return_value={"topics_count": 5, "total_tokens": 999},
        ) as mock_full:
            await run_incremental_topicization(
                "labdiagnostica",
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )

        mock_full.assert_awaited_once()
        # >0 PERSISTED cards → recovered → marker cleared.
        assert marker_ref not in failure_repo.rows

    @pytest.mark.asyncio
    async def test_marker_armed_when_persisted_zero_despite_nonzero_topics_count(self):
        """Bugbot Finding 2 regression guard: ``topicize_channel`` swallows
        ``SQLAlchemyError`` on upsert and still returns a non-empty in-memory list,
        so ``full["topics_count"]`` can be > 0 while ZERO cards persisted. The
        marker MUST stay armed in that case (otherwise the cooldown never engages
        and every tick re-burns a full run)."""
        doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
        # Persisted count stays 0 across the whole call (every upsert "failed").
        topic_card_repo.list_by_channel.return_value = []
        failure_repo = _FakeFailureRepo()
        marker_ref = _reescalation_marker_ref("labdiagnostica")

        with patch(
            "tg_parser.services.topicization_service.run_topicization",
            new_callable=AsyncMock,
            # In-memory list says 7 topics, but NONE persisted.
            return_value={"topics_count": 7, "total_tokens": 1234},
        ) as mock_full:
            await run_incremental_topicization(
                "labdiagnostica",
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )

        mock_full.assert_awaited_once()
        # Persisted == 0 → marker ARMED despite topics_count=7.
        assert marker_ref in failure_repo.rows
        assert failure_repo.rows[marker_ref]["attempts"] == 1

    @pytest.mark.asyncio
    async def test_cooldown_runs_incremental_phase_not_full(self):
        """Bugbot Finding 1 regression guard: while in cooldown the EXPENSIVE full
        re-escalation is suppressed, but the cheap incremental Phase 1/2 path STILL
        runs on the new docs (it is not abandoned for the whole TTL window)."""
        doc, processed_repo, topic_card_repo, topic_bundle_repo = _zero_card_repos()
        failure_repo = _FakeFailureRepo()
        marker_ref = _reescalation_marker_ref("labdiagnostica")
        # Fresh (recent) marker → within cooldown.
        await failure_repo.record_failure(
            source_ref=marker_ref,
            channel_id="labdiagnostica",
            attempts=3,
            error_class="TopicizationReEscalation",
            error_message="still failing",
        )

        with (
            patch(
                "tg_parser.services.topicization_service.run_topicization",
                new_callable=AsyncMock,
                return_value={"topics_count": 0, "total_tokens": 0},
            ) as mock_full,
            _patch_incremental_phase(
                assign_return=([], [doc.source_ref]),
                discover_return=([], [], [doc.source_ref], 0),
            ) as (assign_mock, discover_mock),
        ):
            await run_incremental_topicization(
                "labdiagnostica",
                [doc.source_ref],
                cross_channel=False,
                processed_repo=processed_repo,
                topic_card_repo=topic_card_repo,
                topic_bundle_repo=topic_bundle_repo,
                failure_repo=failure_repo,
            )

        # The expensive full re-escalation was NOT run...
        mock_full.assert_not_awaited()
        # ...but the cheap incremental Phase 1 (keyword) + Phase 2 (LLM discover)
        # DID run on the new docs.
        assert assign_mock.await_count == 1
        assert discover_mock.await_count == 1
        # Cooldown marker is untouched by the incremental path (attempts unchanged).
        assert failure_repo.rows[marker_ref]["attempts"] == 3


class TestReEscalationCooldownHelper:
    def test_no_marker_not_in_cooldown(self):
        assert _reescalation_in_cooldown(None, datetime.now(UTC), 3600) is False

    def test_recent_marker_in_cooldown(self):
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _reescalation_in_cooldown(ts, datetime.now(UTC), 3600) is True

    def test_old_marker_not_in_cooldown(self):
        ts = (datetime.now(UTC) - timedelta(seconds=7200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _reescalation_in_cooldown(ts, datetime.now(UTC), 3600) is False

    def test_future_marker_not_in_cooldown(self):
        ts = (datetime.now(UTC) + timedelta(seconds=7200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _reescalation_in_cooldown(ts, datetime.now(UTC), 3600) is False
