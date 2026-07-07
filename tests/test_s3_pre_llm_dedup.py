"""S3 — Pre-LLM deduplication + batched dedup checks (F-01 / O-2, F-09 / O-8).

Covers:
- O-2 pre-LLM dedup: an exact repost (same channel, identical RAW text) is
  deduplicated BEFORE the LLM call and materialised as a traceable mirror row.
  * within-tick (parallel batch, default mode) — TestPreLlmWithinTick
  * cross-tick (single + batch, via a fake repo in default mode) — TestPreLlmCrossTick
- raw-vs-clean layering (pre-LLM miss + post-LLM hit) — TestRawVsClean
- idempotency of a re-run tick — TestPreLlmIdempotency
- dedup_enabled=False / force=True bypass — TestPreLlmBypass
- O-8 batched find_by_content_hashes in _filter_duplicates — TestO8Batching
- F-09 batched already-processed lookup (no per-message exists()) — TestF09ExistsBatching
- PG-only real-repo SQL for the two new repo methods + cross-tick end-to-end
  (TEST_POSTGRES=1) — TestRepoBatchedLookupsPG / TestCrossTickPipelinePG
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import UTC, datetime

import pytest

from tg_parser.domain.hashing import compute_content_hash
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage
from tg_parser.processing.pipeline import ProcessingPipelineImpl

_SKIP_PG = not os.environ.get("TEST_POSTGRES")


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _MockLLM:
    """LLM double for pre-LLM dedup tests.

    ``text_clean`` set  → returns that constant (post-LLM hashes collide).
    ``text_clean=None`` → echoes the prompt (post-LLM hashes diverge per input).
    """

    def __init__(self, text_clean: str | None = None):
        self._text_clean = text_clean
        self.call_count = 0

    async def generate(self, prompt: str, *args, **kwargs) -> str:
        import json as _json

        self.call_count += 1
        tc = self._text_clean if self._text_clean is not None else prompt
        return _json.dumps(
            {
                "text_clean": tc,
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


class FakeProcessedDocRepo:
    """In-memory ProcessedDocumentRepo double implementing the S3 lookups.

    Lets the pipeline's pre-LLM / batched paths run end-to-end in default mode
    (no Postgres). Records call counts so tests can assert batching (O-8) and the
    absence of the per-message exists() fan-out (F-09).
    """

    def __init__(self):
        self.docs: dict[str, ProcessedDocument] = {}
        self.calls: Counter[str] = Counter()

    async def upsert(self, doc: ProcessedDocument) -> None:
        self.calls["upsert"] += 1
        self.docs[doc.source_ref] = doc

    async def upsert_batch(self, docs: list[ProcessedDocument]) -> int:
        self.calls["upsert_batch"] += 1
        for d in docs:
            self.docs[d.source_ref] = d
        return len(docs)

    async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None:
        return self.docs.get(source_ref)

    async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
        self.calls["get_by_source_refs"] += 1
        return {r: self.docs[r] for r in source_refs if r in self.docs}

    async def exists(self, source_ref: str) -> bool:
        self.calls["exists"] += 1
        return source_ref in self.docs

    async def find_by_content_hash(self, channel_id, content_hash):
        for d in sorted(self.docs.values(), key=lambda x: x.processed_at):
            if d.channel_id == channel_id and d.content_hash == content_hash:
                return d
        return None

    async def find_by_content_hashes(self, channel_id, content_hashes):
        self.calls["find_by_content_hashes"] += 1
        wanted = set(content_hashes)
        out: dict[str, ProcessedDocument] = {}
        for d in sorted(self.docs.values(), key=lambda x: x.processed_at):
            if d.channel_id == channel_id and d.content_hash in wanted:
                out.setdefault(d.content_hash, d)
        return out

    async def find_by_raw_content_hashes(self, channel_id, raw_hashes):
        self.calls["find_by_raw_content_hashes"] += 1
        wanted = set(raw_hashes)
        out: dict[str, ProcessedDocument] = {}
        for d in sorted(self.docs.values(), key=lambda x: x.processed_at):
            rh = (d.metadata or {}).get("raw_content_hash")
            if d.channel_id == channel_id and rh in wanted:
                out.setdefault(rh, d)
        return out


class _FailureRepo:
    """Minimal ProcessingFailureRepo double (no cooldown data)."""

    def __init__(self):
        self.recorded: list[dict] = []

    async def list_failures(self, channel_id):
        return []

    async def record_failure(self, **kwargs):
        self.recorded.append(kwargs)

    async def delete_failure(self, source_ref):
        return None


def _raw(source_ref: str, channel: str, text: str) -> RawTelegramMessage:
    return RawTelegramMessage(
        id=source_ref.rsplit(":", 1)[-1],
        message_type=MessageType.POST,
        source_ref=source_ref,
        channel_id=channel,
        date=datetime(2026, 4, 18, tzinfo=UTC),
        text=text,
    )


def _pipeline(repo, llm=None, failure_repo=None) -> ProcessingPipelineImpl:
    return ProcessingPipelineImpl(
        llm_client=llm or _MockLLM(),
        processed_doc_repo=repo,
        failure_repo=failure_repo,
        pipeline_version="processing:v1.0.0",
        model_id="mock-model",
    )


def _doc(source_ref, channel, text_clean, *, raw_text=None) -> ProcessedDocument:
    meta = {"pipeline_version": "v1.0"}
    if raw_text is not None:
        meta["raw_content_hash"] = compute_content_hash(raw_text)
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref.rsplit(":", 1)[-1],
        channel_id=channel,
        processed_at=datetime(2026, 4, 18, tzinfo=UTC),
        text_clean=text_clean,
        content_hash=compute_content_hash(text_clean),
        metadata=meta,
    )


@pytest.fixture
def enable_dedup(monkeypatch):
    from tg_parser.config import settings as cfg

    monkeypatch.setattr(cfg, "dedup_enabled", True)
    monkeypatch.setattr(cfg, "dedup_strip_url_query", True)


@pytest.fixture
def disable_dedup(monkeypatch):
    from tg_parser.config import settings as cfg

    monkeypatch.setattr(cfg, "dedup_enabled", False)


def _pre_llm_metric(channel_id: str) -> float:
    from tg_parser.api.metrics import PRE_LLM_DEDUP_HITS

    return PRE_LLM_DEDUP_HITS.labels(channel_id=channel_id)._value.get()  # noqa: SLF001


# ---------------------------------------------------------------------------
# O-2 — within-tick pre-LLM dedup (parallel batch, default mode)
# ---------------------------------------------------------------------------


class TestPreLlmWithinTick:
    async def test_exact_within_tick_repost_skips_llm_and_is_traceable(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)  # echo → per-input clean hash
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_wt"
        before = _pre_llm_metric(ch)

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "identical repost body"),
            _raw(f"tg:{ch}:post:2", ch, "identical repost body"),
        ]
        results = await pipeline.process_batch(messages, concurrency=2)

        # Only the leader hit the LLM; the repost was deduped pre-LLM.
        assert llm.call_count == 1
        assert pipeline._batch_pre_llm_dedup == 1
        # Both messages are persisted (traceable), the repost mirrors the leader.
        assert set(repo.docs) == {f"tg:{ch}:post:1", f"tg:{ch}:post:2"}
        mirror = repo.docs[f"tg:{ch}:post:2"]
        assert (mirror.metadata or {}).get("dedup_of") == f"tg:{ch}:post:1"
        assert mirror.text_clean == repo.docs[f"tg:{ch}:post:1"].text_clean
        assert mirror.content_hash == repo.docs[f"tg:{ch}:post:1"].content_hash
        assert {d.source_ref for d in results} == set(repo.docs)
        # Distinct pre-LLM counter, not the post-LLM one.
        assert _pre_llm_metric(ch) == before + 1

    async def test_within_tick_repost_deferred_when_leader_fails(self, enable_dedup):
        """Bugbot regression: if the within-tick leader FAILS (no mirror built),
        its repost is DEFERRED (counted in _batch_pre_llm_deferred), never a
        failure — so the scheduler's fail_ratio can't exceed 100% on a repost
        burst whose leader failed."""
        from tg_parser.processing.llm.errors import LLMCallTimeoutError

        class _FailingLLM:
            def __init__(self):
                self.call_count = 0

            async def generate_with_usage(self, *args, **kwargs):
                self.call_count += 1
                raise LLMCallTimeoutError("boom")

        repo = FakeProcessedDocRepo()
        llm = _FailingLLM()
        failure_repo = _FailureRepo()
        pipeline = _pipeline(repo, llm=llm, failure_repo=failure_repo)
        ch = "ch_wtf"

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "burst body"),  # leader → fails
            _raw(f"tg:{ch}:post:2", ch, "burst body"),  # repost → deferred
        ]
        results = await pipeline.process_batch(messages, concurrency=2)

        assert results == []  # leader failed, repost deferred (no mirror)
        assert llm.call_count == 1  # only the leader was attempted
        assert pipeline._batch_attempted == 1
        assert pipeline._batch_pre_llm_dedup == 0
        assert pipeline._batch_pre_llm_deferred == 1  # the repost is deferred
        assert repo.docs == {}  # nothing persisted this tick

    async def test_two_leaders_one_repost(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_wt2"

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "alpha body"),
            _raw(f"tg:{ch}:post:2", ch, "beta body"),
            _raw(f"tg:{ch}:post:3", ch, "alpha body"),  # repost of post:1
        ]
        await pipeline.process_batch(messages, concurrency=3)

        assert llm.call_count == 2  # two unique leaders
        assert pipeline._batch_pre_llm_dedup == 1
        assert repo.docs[f"tg:{ch}:post:3"].metadata["dedup_of"] == f"tg:{ch}:post:1"

    async def test_within_tick_repost_mirrored_when_leader_dropped_post_llm(
        self, enable_dedup
    ):
        """Bugbot regression: the within-tick leader is dropped by post-LLM
        ``_filter_duplicates`` because its ``content_hash`` already exists on a
        LEGACY DB row (one without ``metadata['raw_content_hash']``, so the
        cross-tick pre-LLM lookup misses it). The repost must still be mirrored
        against that canonical existing row — NOT deferred forever while the
        leader re-burns the LLM every tick."""
        repo = FakeProcessedDocRepo()
        ch = "ch_legacy"
        # Legacy row: has the content_hash but NO raw_content_hash in metadata.
        legacy = _doc(f"tg:{ch}:post:0", ch, "legacy clean")
        assert "raw_content_hash" not in (legacy.metadata or {})
        repo.docs[legacy.source_ref] = legacy

        # LLM collapses both raw texts to the legacy clean text → same content_hash.
        llm = _MockLLM(text_clean="legacy clean")
        pipeline = _pipeline(repo, llm=llm)

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "fresh raw burst"),  # leader → dropped post-LLM
            _raw(f"tg:{ch}:post:2", ch, "fresh raw burst"),  # repost → mirror of legacy
        ]
        results = await pipeline.process_batch(messages, concurrency=2)

        assert llm.call_count == 1  # only the leader was sent to the LLM
        # Leader collapsed into the legacy row (not re-persisted); repost mirrored.
        assert f"tg:{ch}:post:1" not in repo.docs
        assert f"tg:{ch}:post:2" in repo.docs
        mirror = repo.docs[f"tg:{ch}:post:2"]
        assert mirror.metadata["dedup_of"] == legacy.source_ref
        assert mirror.metadata["raw_content_hash"] == compute_content_hash(
            "fresh raw burst"
        )
        assert pipeline._batch_pre_llm_dedup == 1
        assert pipeline._batch_pre_llm_deferred == 0  # resolved, NOT deferred
        assert {d.source_ref for d in results} == {f"tg:{ch}:post:2"}


# ---------------------------------------------------------------------------
# O-2 — cross-tick pre-LLM dedup (single + batch, fake repo)
# ---------------------------------------------------------------------------


class TestPreLlmCrossTick:
    async def test_single_path_cross_tick_repost(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_ct"

        original = await pipeline.process_message(_raw(f"tg:{ch}:post:1", ch, "hello world"))
        assert llm.call_count == 1
        assert original.metadata["raw_content_hash"] == compute_content_hash("hello world")

        before = _pre_llm_metric(ch)
        repost = await pipeline.process_message(_raw(f"tg:{ch}:post:2", ch, "hello world"))

        assert llm.call_count == 1, "cross-tick repost must not hit the LLM"
        assert repost.source_ref == f"tg:{ch}:post:2"
        assert repost.metadata["dedup_of"] == f"tg:{ch}:post:1"
        assert repost.text_clean == original.text_clean
        assert _pre_llm_metric(ch) == before + 1

    async def test_batch_path_cross_tick_repost(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_ctb"

        await pipeline.process_batch([_raw(f"tg:{ch}:post:1", ch, "cross tick body")], concurrency=2)
        assert llm.call_count == 1

        await pipeline.process_batch([_raw(f"tg:{ch}:post:2", ch, "cross tick body")], concurrency=2)
        assert llm.call_count == 1  # deduped pre-LLM against the persisted original
        assert repo.docs[f"tg:{ch}:post:2"].metadata["dedup_of"] == f"tg:{ch}:post:1"


# ---------------------------------------------------------------------------
# raw-vs-clean layering: pre-LLM miss + post-LLM hit
# ---------------------------------------------------------------------------


class TestRawVsClean:
    async def test_different_raw_same_clean_caught_post_llm(self, enable_dedup):
        # Constant text_clean → same content_hash regardless of (different) raw
        # text, so pre-LLM misses (raw hashes differ) but post-LLM catches it.
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean="canonical cleaned text")
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_rc"

        first = await pipeline.process_message(_raw(f"tg:{ch}:post:1", ch, "RAW variant one"))
        assert llm.call_count == 1

        second = await pipeline.process_message(_raw(f"tg:{ch}:post:2", ch, "raw VARIANT two!!"))
        # Pre-LLM missed (different raw) so the LLM ran, then post-LLM dedup hit.
        assert llm.call_count == 2
        assert second.source_ref == first.source_ref  # post-LLM returns existing
        # Post-LLM path does NOT write a new row (unlike the pre-LLM mirror).
        assert set(repo.docs) == {f"tg:{ch}:post:1"}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestPreLlmIdempotency:
    async def test_rerun_tick_no_new_llm_no_new_rows(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_idem"

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "same repost"),
            _raw(f"tg:{ch}:post:2", ch, "same repost"),
            _raw(f"tg:{ch}:post:3", ch, "unique one"),
        ]
        await pipeline.process_batch(messages, concurrency=3)
        calls_after_first = llm.call_count
        docs_after_first = dict(repo.docs)

        await pipeline.process_batch(messages, concurrency=3)
        assert llm.call_count == calls_after_first, "re-run must not call the LLM again"
        assert set(repo.docs) == set(docs_after_first), "re-run must not create new rows"
        assert pipeline._batch_pre_llm_dedup == 0
        assert pipeline._batch_attempted == 0


# ---------------------------------------------------------------------------
# dedup_enabled=False / force=True bypass
# ---------------------------------------------------------------------------


class TestPreLlmBypass:
    async def test_dedup_disabled_processes_repost_via_llm(self, disable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_off"

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "same body"),
            _raw(f"tg:{ch}:post:2", ch, "same body"),
        ]
        await pipeline.process_batch(messages, concurrency=2)
        assert llm.call_count == 2  # no dedup → both go to LLM
        assert repo.calls["find_by_raw_content_hashes"] == 0
        assert pipeline._batch_pre_llm_dedup == 0

    async def test_force_bypasses_pre_llm(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        # Seed an existing doc that a repost would otherwise match cross-tick.
        seed = _doc(f"tg:ch_force:post:0", "ch_force", "seed clean", raw_text="forced body")
        repo.docs[seed.source_ref] = seed
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)

        await pipeline.process_batch(
            [_raw("tg:ch_force:post:1", "ch_force", "forced body")], concurrency=2, force=True
        )
        assert llm.call_count == 1  # force → LLM runs despite the raw-hash match
        assert repo.calls["find_by_raw_content_hashes"] == 0

    async def test_single_path_force_bypasses_pre_llm(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        seed = _doc("tg:ch_sf:post:0", "ch_sf", "seed", raw_text="body x")
        repo.docs[seed.source_ref] = seed
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)

        got = await pipeline.process_message(_raw("tg:ch_sf:post:1", "ch_sf", "body x"), force=True)
        assert llm.call_count == 1
        assert got.source_ref == "tg:ch_sf:post:1"
        assert repo.calls["find_by_raw_content_hashes"] == 0


# ---------------------------------------------------------------------------
# O-8 — batched find_by_content_hashes in _filter_duplicates
# ---------------------------------------------------------------------------


class TestO8Batching:
    async def test_filter_duplicates_uses_one_batched_query(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        pipeline = _pipeline(repo)
        ch = "ch_o8"

        docs = [
            _doc(f"tg:{ch}:post:{i}", ch, f"clean {i}") for i in range(1, 6)
        ]
        kept, _dropped = await pipeline._filter_duplicates(docs)

        assert len(kept) == 5
        # One batched lookup for the whole chunk (single channel), not N.
        assert repo.calls["find_by_content_hashes"] == 1

    async def test_filter_duplicates_cross_chunk_dup_caught(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        pipeline = _pipeline(repo)
        ch = "ch_o8x"
        # Persist an earlier "chunk".
        early = _doc(f"tg:{ch}:post:1", ch, "shared clean")
        repo.docs[early.source_ref] = early

        later = [_doc(f"tg:{ch}:post:2", ch, "shared clean")]
        kept, dropped = await pipeline._filter_duplicates(later)
        assert kept == []  # duplicate of the already-persisted early chunk
        # the dropped doc maps back to the canonical (already-persisted) doc
        assert dropped[later[0].source_ref].source_ref == early.source_ref
        assert repo.calls["find_by_content_hashes"] == 1

    async def test_filter_duplicates_empty_input(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        pipeline = _pipeline(repo)
        kept, dropped = await pipeline._filter_duplicates([])
        assert kept == []
        assert dropped == {}
        assert repo.calls["find_by_content_hashes"] == 0


# ---------------------------------------------------------------------------
# F-09 — batched already-processed lookup (no per-message exists() fan-out)
# ---------------------------------------------------------------------------


class TestF09ExistsBatching:
    async def test_tick_path_does_not_call_exists_per_message(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_f09"

        messages = [_raw(f"tg:{ch}:post:{i}", ch, f"body {i}") for i in range(1, 6)]
        await pipeline.process_batch(messages, concurrency=3)

        # F-09: the per-message exists() fan-out is gone.
        assert repo.calls["exists"] == 0
        # Replaced by a single batched lookup.
        assert repo.calls["get_by_source_refs"] == 1

    async def test_non_tick_already_processed_still_skipped(self, enable_dedup):
        repo = FakeProcessedDocRepo()
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "ch_f09b"
        # Pre-seed post:1 as already processed (non-tick caller passes it anyway).
        seed = _doc(f"tg:{ch}:post:1", ch, "already", raw_text="already body")
        repo.docs[seed.source_ref] = seed

        messages = [
            _raw(f"tg:{ch}:post:1", ch, "already body"),
            _raw(f"tg:{ch}:post:2", ch, "fresh body"),
        ]
        await pipeline.process_batch(messages, concurrency=2)

        # Only the fresh message is attempted; the pre-existing one is skipped.
        assert pipeline._batch_attempted == 1
        assert llm.call_count == 1
        assert repo.calls["exists"] == 0


# ---------------------------------------------------------------------------
# PG-only — real-repo SQL for the two new repo methods
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestRepoBatchedLookupsPG:
    @pytest.fixture
    async def repo_session(self, test_db):
        from sqlalchemy import text as sql_text

        from tg_parser.storage.sqlalchemy.processed_document_repo import (
            SAProcessedDocumentRepo,
        )

        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:s3pg:%'")
            )
        session = test_db.processing_storage_session()
        try:
            yield SAProcessedDocumentRepo(session)
        finally:
            await session.close()
            async with test_db.processing_storage_engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:s3pg:%'")
                )

    def _make(self, source_ref, channel, text_clean, *, raw_text=None):
        return _doc(source_ref, channel, text_clean, raw_text=raw_text)

    async def test_find_by_content_hashes_batches_hits(self, repo_session):
        repo = repo_session
        h1 = compute_content_hash("c1")
        h2 = compute_content_hash("c2")
        await repo.upsert(self._make("tg:s3pg:post:1", "s3pg", "c1"))
        await repo.upsert(self._make("tg:s3pg:post:2", "s3pg", "c2"))

        got = await repo.find_by_content_hashes("s3pg", [h1, h2, compute_content_hash("miss")])
        assert set(got) == {h1, h2}
        assert got[h1].source_ref == "tg:s3pg:post:1"

    async def test_find_by_content_hashes_empty_returns_empty(self, repo_session):
        assert await repo_session.find_by_content_hashes("s3pg", []) == {}

    async def test_find_by_content_hashes_channel_scoped(self, repo_session):
        repo = repo_session
        h = compute_content_hash("scoped")
        await repo.upsert(self._make("tg:s3pg:post:3", "s3pg_a", "scoped"))
        assert await repo.find_by_content_hashes("s3pg_b", [h]) == {}

    async def test_find_by_raw_content_hashes_hit_and_miss(self, repo_session):
        repo = repo_session
        rh = compute_content_hash("raw body one")
        await repo.upsert(self._make("tg:s3pg:post:4", "s3pg", "clean", raw_text="raw body one"))

        got = await repo.find_by_raw_content_hashes("s3pg", [rh, compute_content_hash("nope")])
        assert set(got) == {rh}
        assert got[rh].source_ref == "tg:s3pg:post:4"

    async def test_find_by_raw_content_hashes_ignores_missing_key(self, repo_session):
        repo = repo_session
        # Row without raw_content_hash in metadata must never match.
        await repo.upsert(self._make("tg:s3pg:post:5", "s3pg", "clean"))
        got = await repo.find_by_raw_content_hashes("s3pg", [compute_content_hash("anything")])
        assert got == {}

    async def test_find_by_raw_content_hashes_empty_returns_empty(self, repo_session):
        assert await repo_session.find_by_raw_content_hashes("s3pg", []) == {}

    async def test_find_by_raw_content_hashes_tolerates_malformed_metadata(
        self, repo_session
    ):
        """Bugbot regression: a sibling row in the SAME channel with malformed
        ``metadata_json`` must NOT abort the scan. The old ``metadata_json::jsonb``
        WHERE cast errored on the whole query for a single bad row; the LIKE
        prefilter is total, so the valid mirror row is still returned."""
        from sqlalchemy import text as sql_text

        repo = repo_session
        rh = compute_content_hash("valid raw body")
        await repo.upsert(
            self._make("tg:s3pg:post:6", "s3pg", "clean6", raw_text="valid raw body")
        )
        # Malformed metadata_json (not JSON at all) in the same channel scan.
        await repo.session.execute(
            sql_text("""
                INSERT INTO processed_documents (
                    source_ref, id, source_message_id, channel_id, processed_at,
                    text_clean, summary, topics_json, entities_json, language,
                    metadata_json, content_hash
                ) VALUES (
                    'tg:s3pg:post:7', 'doc:tg:s3pg:post:7', '7', 's3pg', :ts,
                    'broken', NULL, NULL, NULL, 'ru', :bad, :ch
                )
            """),
            {
                "ts": datetime(2026, 4, 18, tzinfo=UTC),
                "bad": "this is <not> json {",
                "ch": compute_content_hash("broken"),
            },
        )
        await repo.session.commit()

        got = await repo.find_by_raw_content_hashes("s3pg", [rh])
        assert set(got) == {rh}
        assert got[rh].source_ref == "tg:s3pg:post:6"


# ---------------------------------------------------------------------------
# PG-only — cross-tick pre-LLM dedup end-to-end (AC#1 under Postgres)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestCrossTickPipelinePG:
    @pytest.fixture
    async def repo(self, test_db):
        from sqlalchemy import text as sql_text

        from tg_parser.storage.sqlalchemy.processed_document_repo import (
            SAProcessedDocumentRepo,
        )

        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:s3ct:%'")
            )
        session = test_db.processing_storage_session()
        try:
            yield SAProcessedDocumentRepo(session)
        finally:
            await session.close()
            async with test_db.processing_storage_engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:s3ct:%'")
                )

    async def test_cross_tick_repost_skips_llm_and_is_traceable(self, enable_dedup, repo):
        llm = _MockLLM(text_clean=None)
        pipeline = _pipeline(repo, llm=llm)
        ch = "s3ct"

        # Tick 1: original processed and persisted with raw_content_hash.
        await pipeline.process_batch([_raw("tg:s3ct:post:1", ch, "cross tick raw")], concurrency=2)
        assert llm.call_count == 1

        # Tick 2 (new pipeline instance = fresh tick): exact repost.
        pipeline2 = _pipeline(repo, llm=llm)
        results = await pipeline2.process_batch(
            [_raw("tg:s3ct:post:2", ch, "cross tick raw")], concurrency=2
        )

        assert llm.call_count == 1, "cross-tick repost must not hit the LLM (PG raw-hash match)"
        assert pipeline2._batch_pre_llm_dedup == 1
        mirror = await repo.get_by_source_ref("tg:s3ct:post:2")
        assert mirror is not None
        assert mirror.metadata["dedup_of"] == "tg:s3ct:post:1"
        assert {d.source_ref for d in results} == {"tg:s3ct:post:2"}
