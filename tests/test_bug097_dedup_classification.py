"""BUG-097 (a) — a deduplicated document gets its own outcome, not ``failed``.

The dedup that fires on the tick path is the POST-LLM one (``dedup_db_duplicate``
/ ``dedup_within_batch_duplicate`` in ``_filter_duplicates``): the document was
summarized, then dropped because an equal ``content_hash`` already exists. It is
neither ``processed`` (no row of its own) nor ``skipped`` (nothing skipped it),
so ``failed_count = total − processed − skipped`` collected it by remainder —
and the scheduler's B1 marker turned that remainder into a permanent false
``degraded`` with a four-digit ``fail_count``.

These tests state the two invariants the suite never had (BUG-097 «Why CI didn't
catch it»): a deduplicated document does not raise ``failed_count``, and a
dedup-only tick is not ``degraded``. Both are about HOW an outcome is recorded,
which is why the existing dedup tests (correctness of the drop) pass on either
side of the fix.

Ordering — whether the check should run BEFORE the LLM call — is half (b) of
BUG-097 and lives in session R11. Nothing here changes which documents are
dropped; ``test_dedup_still_drops_the_same_documents`` pins that.
"""

from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.domain.hashing import compute_content_hash
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage
from tg_parser.processing.pipeline import ProcessingPipelineImpl
from tg_parser.storage.ports import Source

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _CollapsingLLM:
    """LLM double whose output collapses every input to the SAME ``text_clean``.

    That is the production shape of a post-LLM duplicate: the RAW texts differ
    (so the S3 pre-LLM raw-hash check misses and the call is really paid for),
    while the cleaned text — and therefore ``content_hash`` — is identical.
    """

    def __init__(self, text_clean: str = "canonical clean text"):
        self._text_clean = text_clean
        self.call_count = 0

    async def generate(self, prompt: str, *args, **kwargs) -> str:
        import json

        self.call_count += 1
        return json.dumps(
            {
                "text_clean": self._text_clean,
                "summary": "s",
                "topics": ["t"],
                "entities": [],
                "language": "ru",
            }
        )

    async def generate_with_usage(self, *args, **kwargs):
        from tg_parser.processing.ports import LLMResponse

        text = await self.generate(*args, **kwargs)
        return LLMResponse(text=text, input_tokens=1, output_tokens=1)


class _FakeProcessedDocRepo:
    """In-memory ProcessedDocumentRepo double covering the dedup lookups."""

    def __init__(self):
        self.docs: dict[str, ProcessedDocument] = {}

    async def upsert(self, doc: ProcessedDocument) -> None:
        self.docs[doc.source_ref] = doc

    async def upsert_batch(self, docs: list[ProcessedDocument]) -> int:
        for d in docs:
            self.docs[d.source_ref] = d
        return len(docs)

    async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None:
        return self.docs.get(source_ref)

    async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
        return {r: self.docs[r] for r in source_refs if r in self.docs}

    async def exists(self, source_ref: str) -> bool:
        return source_ref in self.docs

    async def find_by_content_hash(self, channel_id, content_hash):
        for d in sorted(self.docs.values(), key=lambda x: x.processed_at):
            if d.channel_id == channel_id and d.content_hash == content_hash:
                return d
        return None

    async def find_by_content_hashes(self, channel_id, content_hashes):
        wanted = set(content_hashes)
        out: dict[str, ProcessedDocument] = {}
        for d in sorted(self.docs.values(), key=lambda x: x.processed_at):
            if d.channel_id == channel_id and d.content_hash in wanted:
                out.setdefault(d.content_hash, d)
        return out

    async def find_by_raw_content_hashes(self, channel_id, raw_hashes):
        wanted = set(raw_hashes)
        out: dict[str, ProcessedDocument] = {}
        for d in sorted(self.docs.values(), key=lambda x: x.processed_at):
            rh = (d.metadata or {}).get("raw_content_hash")
            if d.channel_id == channel_id and rh in wanted:
                out.setdefault(rh, d)
        return out


class _FakeRawRepo:
    def __init__(self, messages: list[RawTelegramMessage]):
        self._messages = messages

    async def list_unprocessed_by_channel(self, channel_id, *, limit, failure_cooldown_enabled):
        return list(self._messages)

    async def count_by_channel(self, channel_id) -> int:
        return len(self._messages)


class _FakeFailureRepo:
    def __init__(self):
        self.recorded: list[dict] = []

    async def list_failures(self, channel_id):
        return []

    async def record_failure(self, **kwargs):
        self.recorded.append(kwargs)

    async def delete_failure(self, source_ref):
        return None


CHANNEL = "ch097"
CANONICAL_CLEAN = "canonical clean text"


def _raw(number: int, text: str, channel: str = CHANNEL) -> RawTelegramMessage:
    return RawTelegramMessage(
        id=str(number),
        message_type=MessageType.POST,
        source_ref=f"tg:{channel}:post:{number}",
        channel_id=channel,
        date=datetime(2026, 8, 13, tzinfo=UTC),
        text=text,
    )


def _canonical_doc(channel: str = CHANNEL) -> ProcessedDocument:
    """The already-persisted document every fresh message collapses into.

    Its ``raw_content_hash`` belongs to a raw text no incoming message carries,
    so the pre-LLM check cannot see it — exactly the production case where the
    LLM call is paid before the duplicate is discovered.
    """
    return ProcessedDocument(
        id=f"doc:tg:{channel}:post:0",
        source_ref=f"tg:{channel}:post:0",
        source_message_id="0",
        channel_id=channel,
        processed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text_clean=CANONICAL_CLEAN,
        content_hash=compute_content_hash(CANONICAL_CLEAN),
        metadata={
            "pipeline_version": "v1.0",
            "raw_content_hash": compute_content_hash("original raw text nobody reposts verbatim"),
        },
    )


def _pipeline(repo, llm, failure_repo=None) -> ProcessingPipelineImpl:
    return ProcessingPipelineImpl(
        llm_client=llm,
        processed_doc_repo=repo,
        failure_repo=failure_repo,
        pipeline_version="processing:v1.0.0",
        model_id="mock-model",
    )


@pytest.fixture
def enable_dedup(monkeypatch):
    from tg_parser.config import settings as cfg

    monkeypatch.setattr(cfg, "dedup_enabled", True)
    monkeypatch.setattr(cfg, "dedup_strip_url_query", True)


async def _run_processing_with(
    messages: list[RawTelegramMessage],
    *,
    llm,
    seed_canonical: bool = True,
) -> tuple[dict, _FakeProcessedDocRepo]:
    """Run the real ``run_processing`` over fake repos and a real pipeline."""
    from tg_parser.services.processing_service import run_processing

    processed_repo = _FakeProcessedDocRepo()
    if seed_canonical:
        canonical = _canonical_doc()
        processed_repo.docs[canonical.source_ref] = canonical
    raw_repo = _FakeRawRepo(messages)
    failure_repo = _FakeFailureRepo()
    pipeline = _pipeline(processed_repo, llm, failure_repo=failure_repo)

    with patch(
        "tg_parser.services.processing_service.create_processing_pipeline",
        return_value=pipeline,
    ):
        stats = await run_processing(
            channel_id=CHANNEL,
            concurrency=2,
            raw_repo=raw_repo,
            processed_repo=processed_repo,
            failure_repo=failure_repo,
        )
    return stats, processed_repo


# ---------------------------------------------------------------------------
# Pipeline level — the drop gets its own batch counter
# ---------------------------------------------------------------------------


class TestBatchCounter:
    async def test_db_duplicate_counted_on_its_own_counter(self, enable_dedup):
        """A doc dropped against an existing DB row (``dedup_db_duplicate``) is
        counted as deduplicated — separately from the pre-LLM counter, which
        describes documents that never reached the LLM at all."""
        repo = _FakeProcessedDocRepo()
        canonical = _canonical_doc()
        repo.docs[canonical.source_ref] = canonical
        llm = _CollapsingLLM()
        pipeline = _pipeline(repo, llm)

        results = await pipeline.process_batch([_raw(1, "fresh wording one")], concurrency=2)

        assert llm.call_count == 1, "the duplicate WAS summarized (ordering is R11)"
        assert results == []
        assert pipeline._batch_attempted == 1
        assert pipeline._batch_post_llm_dedup == 1
        assert pipeline._batch_pre_llm_dedup == 0
        assert pipeline._batch_pre_llm_deferred == 0
        assert pipeline._batch_cooldown_skipped == 0

    async def test_within_batch_duplicate_counted_too(self, enable_dedup):
        """``dedup_within_batch_duplicate`` is the same outcome as the DB one:
        summarized, then dropped. Only the surviving leader is persisted."""
        repo = _FakeProcessedDocRepo()
        llm = _CollapsingLLM()
        pipeline = _pipeline(repo, llm)

        results = await pipeline.process_batch(
            [_raw(1, "wording one"), _raw(2, "wording two")], concurrency=2
        )

        assert llm.call_count == 2
        assert len(results) == 1, "one leader survives, its twin is deduplicated"
        assert pipeline._batch_attempted == 2
        assert pipeline._batch_post_llm_dedup == 1

    async def test_clean_batch_reports_zero(self, enable_dedup):
        """No duplicates → the counter stays at 0 (no drift into other buckets)."""
        repo = _FakeProcessedDocRepo()

        class _EchoLLM(_CollapsingLLM):
            async def generate(self, prompt: str, *args, **kwargs) -> str:
                import json

                self.call_count += 1
                return json.dumps(
                    {
                        "text_clean": prompt,
                        "summary": "s",
                        "topics": ["t"],
                        "entities": [],
                        "language": "ru",
                    }
                )

        pipeline = _pipeline(repo, _EchoLLM())
        results = await pipeline.process_batch(
            [_raw(1, "unique one"), _raw(2, "unique two")], concurrency=2
        )

        assert len(results) == 2
        assert pipeline._batch_post_llm_dedup == 0


# ---------------------------------------------------------------------------
# Service level — ``failed_count`` describes failures only
# ---------------------------------------------------------------------------


class TestProcessStats:
    async def test_dedup_only_tick_reports_no_failures(self, enable_dedup):
        """THE invariant: a tick whose every document was deduplicated reports
        ``failed_count == 0``. Before the fix it reported 3 — the remainder of
        ``total − processed − skipped`` — which is what put nine healthy sources
        into a permanent false ``degraded``."""
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2, 3)]
        stats, repo = await _run_processing_with(messages, llm=_CollapsingLLM())

        assert stats["failed_count"] == 0
        assert stats["deduplicated_count"] == 3
        assert stats["processed_count"] == 0
        assert stats["skipped_count"] == 0
        assert stats["total_count"] == 3
        assert stats["attempted_count"] == 3, "they were sent to the LLM (R11 territory)"

    async def test_genuine_failure_still_counted_next_to_dedup(self, enable_dedup):
        """The fix must not swallow real failures: a tick with one LLM failure
        and two duplicates reports exactly one failure and two deduplicated."""
        from tg_parser.processing.llm.errors import LLMJsonParseError

        class _OneFailureLLM(_CollapsingLLM):
            async def generate_with_usage(self, prompt, *args, **kwargs):
                if "poison" in prompt:
                    self.call_count += 1
                    raise LLMJsonParseError("unparseable")
                return await super().generate_with_usage(prompt, *args, **kwargs)

        messages = [
            _raw(1, "fresh wording one"),
            _raw(2, "fresh wording two"),
            _raw(3, "poison payload"),
        ]
        stats, _repo = await _run_processing_with(messages, llm=_OneFailureLLM())

        assert stats["failed_count"] == 1
        assert stats["deduplicated_count"] == 2
        assert stats["processed_count"] == 0

    async def test_clean_tick_unchanged(self, enable_dedup):
        """A tick with no duplicates keeps its byte-for-byte previous shape."""

        class _EchoLLM(_CollapsingLLM):
            async def generate(self, prompt: str, *args, **kwargs) -> str:
                import json

                self.call_count += 1
                return json.dumps(
                    {
                        "text_clean": prompt,
                        "summary": "s",
                        "topics": ["t"],
                        "entities": [],
                        "language": "ru",
                    }
                )

        messages = [_raw(1, "unique one"), _raw(2, "unique two")]
        stats, _repo = await _run_processing_with(messages, llm=_EchoLLM(), seed_canonical=False)

        assert stats["processed_count"] == 2
        assert stats["failed_count"] == 0
        assert stats["deduplicated_count"] == 0

    async def test_dedup_still_drops_the_same_documents(self, enable_dedup):
        """AC#4: the classification changed, the dedup behaviour did not — the
        duplicates are still discarded and no second row is written."""
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2)]
        _stats, repo = await _run_processing_with(messages, llm=_CollapsingLLM())

        assert set(repo.docs) == {f"tg:{CHANNEL}:post:0"}, "only the canonical row survives"


# ---------------------------------------------------------------------------
# Scheduler level — a dedup-only tick is not ``degraded``
# ---------------------------------------------------------------------------


def _mock_ingestion_state_repo(state_repo):
    @asynccontextmanager
    async def _cm():
        db = MagicMock()
        db.close = AsyncMock()
        yield state_repo, db

    return _cm


def _mock_ingestion_and_processing_repos(state_repo, processed_repo):
    @asynccontextmanager
    async def _cm():
        db = MagicMock()
        db.close = AsyncMock()
        yield state_repo, processed_repo, db

    return _cm


@asynccontextmanager
async def _yield_lock(acquired: bool):
    yield acquired


def _scheduler_stack(stack, state_repo, processed_repo, run_full_pipeline):
    """Patch bundle mirroring the BUG-067 B1 scheduler tests."""
    stack.enter_context(
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(state_repo),
        )
    )
    stack.enter_context(
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(state_repo, processed_repo),
        )
    )
    stack.enter_context(
        patch("tg_parser.services.pipeline_service.run_full_pipeline", run_full_pipeline)
    )
    stack.enter_context(
        patch(
            "tg_parser.services.scheduler_service._source_processing_lock",
            lambda *_a, **_k: _yield_lock(True),
        )
    )
    mock_settings = stack.enter_context(patch("tg_parser.services.scheduler_service.settings"))
    mock_settings.scheduler_max_concurrent_sources = 1
    mock_settings.scheduler_retopicize_threshold = 100
    mock_settings.processing_concurrency = 1
    mock_settings.scheduler_source_timeout_s = 60
    mock_settings.scheduler_degraded_failure_ratio = 0.5
    mock_settings.scheduler_coverage_alert_ratio = 0.8
    return mock_settings


def _tick_stats(process_stats: dict) -> dict:
    return {
        "ingest": {"posts_collected": 0, "comments_collected": 0},
        "process": process_stats,
        "export": {"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
    }


class TestSchedulerClassification:
    async def test_dedup_only_tick_is_not_degraded(self, enable_dedup):
        """The second invariant, fed by the stats a dedup-only tick REALLY
        produces (``run_processing`` is executed, not hand-mocked): the source is
        recorded as a success — no ``degraded``, no ``fail_count`` bump, and no
        ``last_error`` claiming «processed 0 of N»."""
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2, 3)]
        process_stats, _repo = await _run_processing_with(messages, llm=_CollapsingLLM())

        state_repo = AsyncMock()
        state_repo.list_sources.return_value = [
            Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
        ]
        processed_repo = AsyncMock()
        processed_repo.list_source_refs_by_channel.return_value = []

        with ExitStack() as stack:
            _scheduler_stack(
                stack,
                state_repo,
                processed_repo,
                AsyncMock(return_value=_tick_stats(process_stats)),
            )
            from tg_parser.services.scheduler_service import run_incremental_for_all_sources

            result = await run_incremental_for_all_sources()

        assert result["sources_degraded"] == 0
        assert result["sources_failed"] == 0
        assert result["sources_succeeded"] == 1

        kwargs = state_repo.record_attempt.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["failed_stage"] is None
        assert kwargs["details"]["outcome"] == "success"
        assert kwargs["details"]["degraded_reason"] is None

    async def test_real_failures_still_degrade_the_tick(self, enable_dedup):
        """Guard against over-correction: with two genuine failures among three
        attempted documents the B1 marker must still fire. The denominator keeps
        counting the deduplicated document — it did reach the LLM — so the ratio
        stays «share of LLM attempts that failed»."""
        state_repo = AsyncMock()
        state_repo.list_sources.return_value = [
            Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
        ]
        processed_repo = AsyncMock()
        processed_repo.list_source_refs_by_channel.return_value = []

        process_stats = {
            "processed_count": 0,
            "skipped_count": 0,
            "failed_count": 2,
            "deduplicated_count": 1,
            "total_count": 3,
            "attempted_count": 3,
        }

        with ExitStack() as stack:
            _scheduler_stack(
                stack,
                state_repo,
                processed_repo,
                AsyncMock(return_value=_tick_stats(process_stats)),
            )
            from tg_parser.services.scheduler_service import run_incremental_for_all_sources

            result = await run_incremental_for_all_sources()

        assert result["sources_degraded"] == 1
        kwargs = state_repo.record_attempt.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["failed_stage"] == "process_degraded"
        assert "degraded processing tick" in kwargs["error_message"]
