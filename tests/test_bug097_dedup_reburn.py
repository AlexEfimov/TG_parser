"""BUG-097 (b) — a dropped duplicate stops being paid for on every tick.

R10 gave the post-LLM dedup drop its own outcome; it did not stop the drop from
recurring. Work is selected with ``NOT EXISTS (processed_documents)``
(``raw_message_repo.list_unprocessed_by_channel``) and the post-LLM dedup path
writes NO row, so the next tick sees the same message as unprocessed, pays for
the same summary and discards it again — measured on prod as 27 documents, each
dedup'd exactly three times over three ticks, none of them only once.

The invariant this file adds is the one the suite never stated: **the second tick
does not call the LLM for a document the first tick dropped**. Every existing
dedup test asserts the drop is *correct* (the duplicate does not end up stored),
which is true on both sides of the fix — that is precisely why the loop survived
a green CI for a month.

The fix records the drop in ``processing_dedup_drops`` and anti-joins that table
in the selection window, so the ref leaves the window without becoming a second
``processed_documents`` row. The assertions here are therefore written against
the two observable facts — «the LLM is not called again» and «the window stops
offering the ref» — not against the marker's storage shape; the real SQL
anti-join is pinned separately in ``test_storage_integration.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from tg_parser.domain.hashing import compute_content_hash
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage

CHANNEL = "ch097b"
CANONICAL_CLEAN = "canonical clean text"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _CollapsingLLM:
    """LLM double whose output collapses every input to the SAME ``text_clean``.

    The production shape of a post-LLM duplicate: RAW texts differ (so the S3
    pre-LLM raw-hash check misses and the call is really paid for) while the
    cleaned text — and therefore ``content_hash`` — is identical. ``prompts``
    records which documents were sent, so a re-burn is visible per ``source_ref``
    and not only in the aggregate count.
    """

    def __init__(self, text_clean: str = CANONICAL_CLEAN):
        self._text_clean = text_clean
        self.call_count = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, *args, **kwargs) -> str:
        import json

        self.call_count += 1
        self.prompts.append(prompt)
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


class _FakeDedupDropRepo:
    """In-memory DedupDropRepo double, keyed by ``source_ref`` like the table."""

    def __init__(self):
        self.drops: dict[str, dict] = {}
        self.record_calls = 0

    async def record_drops(self, drops) -> int:
        self.record_calls += 1
        written = 0
        for d in drops:
            self.drops[d.source_ref] = {
                "source_ref": d.source_ref,
                "channel_id": d.channel_id,
                "canonical_source_ref": d.canonical_source_ref,
                "raw_content_hash": d.raw_content_hash,
            }
            written += 1
        return written

    async def list_dropped_refs(self, source_refs) -> set[str]:
        return {r for r in source_refs if r in self.drops}

    async def get_drop(self, source_ref: str) -> dict | None:
        return self.drops.get(source_ref)


class _FakeRawRepo:
    """Raw repo double that emulates the PRODUCTION selection window.

    ``list_unprocessed_by_channel`` is a ``NOT EXISTS`` anti-join against
    ``processed_documents``; R11 adds a second one against
    ``processing_dedup_drops``. Both are mirrored here because that predicate IS
    the mechanism under test: a two-tick assertion is only meaningful if tick 2
    selects work the way production does. The real SQL is pinned by
    ``tests/test_storage_integration.py`` so this emulation cannot silently drift
    into testing itself.
    """

    def __init__(
        self,
        messages: list[RawTelegramMessage],
        processed_repo: _FakeProcessedDocRepo,
        drop_repo: _FakeDedupDropRepo | None = None,
    ):
        self._messages = messages
        self._processed = processed_repo
        self._drops = drop_repo

    async def list_unprocessed_by_channel(
        self, channel_id, *, limit, failure_cooldown_enabled=False
    ):
        out = []
        for m in self._messages:
            if m.channel_id != channel_id:
                continue
            if m.source_ref in self._processed.docs:
                continue
            if self._drops is not None and m.source_ref in self._drops.drops:
                continue
            out.append(m)
        return out[:limit]

    async def list_by_channel(self, channel_id):
        return [m for m in self._messages if m.channel_id == channel_id]

    async def get_by_source_ref(self, source_ref):
        for m in self._messages:
            if m.source_ref == source_ref:
                return m
        return None

    async def count_by_channel(self, channel_id) -> int:
        return len([m for m in self._messages if m.channel_id == channel_id])


class _FakeFailureRepo:
    def __init__(self):
        self.recorded: list[dict] = []

    async def list_failures(self, channel_id):
        return []

    async def record_failure(self, **kwargs):
        self.recorded.append(kwargs)

    async def delete_failure(self, source_ref):
        return None


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


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
    """The already-stored document every fresh message collapses into.

    Its ``raw_content_hash`` belongs to a raw text no incoming message carries,
    so the pre-LLM check cannot see it — the production case where the LLM call
    is paid before the duplicate is discovered.
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


@pytest.fixture
def enable_dedup(monkeypatch):
    from tg_parser.config import settings as cfg

    monkeypatch.setattr(cfg, "dedup_enabled", True)
    monkeypatch.setattr(cfg, "dedup_strip_url_query", True)


class _Harness:
    """A channel wired to fake repos, able to run the SAME tick repeatedly."""

    def __init__(self, messages, *, llm, seed_canonical=True, with_drop_repo=True):
        self.processed_repo = _FakeProcessedDocRepo()
        if seed_canonical:
            canonical = _canonical_doc()
            self.processed_repo.docs[canonical.source_ref] = canonical
        self.drop_repo = _FakeDedupDropRepo() if with_drop_repo else None
        self.raw_repo = _FakeRawRepo(messages, self.processed_repo, self.drop_repo)
        self.failure_repo = _FakeFailureRepo()
        self.llm = llm

    async def tick(self, *, force: bool = False) -> dict:
        from tg_parser.processing.pipeline import ProcessingPipelineImpl
        from tg_parser.services.processing_service import run_processing

        pipeline = ProcessingPipelineImpl(
            llm_client=self.llm,
            processed_doc_repo=self.processed_repo,
            failure_repo=self.failure_repo,
            dedup_drop_repo=self.drop_repo,
            raw_repo=self.raw_repo,
            pipeline_version="processing:v1.0.0",
            model_id="mock-model",
        )
        with patch(
            "tg_parser.services.processing_service.create_processing_pipeline",
            return_value=pipeline,
        ):
            return await run_processing(
                channel_id=CHANNEL,
                concurrency=2,
                force=force,
                raw_repo=self.raw_repo,
                processed_repo=self.processed_repo,
                failure_repo=self.failure_repo,
                dedup_drop_repo=self.drop_repo,
            )


# ---------------------------------------------------------------------------
# THE invariant — the second tick does not pay again
# ---------------------------------------------------------------------------


class TestNoReburnAcrossTicks:
    async def test_second_tick_does_not_call_the_llm_for_a_dropped_duplicate(self, enable_dedup):
        """THE invariant of BUG-097 (b), asserted on the LLM call count.

        Three fresh messages whose summaries collapse onto one existing document.
        Tick 1 pays three calls and drops all three. Tick 2 must pay NOTHING —
        before the fix it paid three more, and would keep paying every hour
        forever (prod: the same 27 documents on three consecutive ticks).
        """
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2, 3)]
        h = _Harness(messages, llm=_CollapsingLLM())

        first = await h.tick()
        assert h.llm.call_count == 3, "tick 1 legitimately pays (ordering is §3.5, not this fix)"
        assert first["deduplicated_count"] == 3

        second = await h.tick()

        assert h.llm.call_count == 3, (
            "tick 2 must not re-send a single dropped duplicate to the LLM — "
            "this is the permanent recurring cost of BUG-097 (b)"
        )
        assert second["total_count"] == 0, "the dropped refs left the selection window"
        # ``.get`` on purpose: a tick with nothing to do returns early with a
        # short stats dict that has no ``deduplicated_count`` key at all. That
        # predates this fix and is why the prod query reads the counter through
        # ``coalesce`` — pinned by ``test_idle_tick_omits_the_dedup_counter``.
        assert second.get("deduplicated_count", 0) == 0
        assert second["failed_count"] == 0

    async def test_the_loop_stays_closed_on_the_third_tick(self, enable_dedup):
        """Prod saw each document exactly three times over three ticks, so the
        third tick is where a fix that only defers the cost would show up."""
        messages = [_raw(1, "fresh wording one")]
        h = _Harness(messages, llm=_CollapsingLLM())

        await h.tick()
        await h.tick()
        await h.tick()

        assert h.llm.call_count == 1

    async def test_within_batch_duplicate_also_stops_being_paid_for(self, enable_dedup):
        """The other drop kind (``dedup_within_batch_duplicate``): two fresh
        messages collapse onto each other, the leader is stored, its twin is
        dropped. The twin must not be re-sent next tick either."""
        messages = [_raw(1, "wording one"), _raw(2, "wording two")]
        h = _Harness(messages, llm=_CollapsingLLM(), seed_canonical=False)

        first = await h.tick()
        assert h.llm.call_count == 2
        assert first["processed_count"] == 1, "the leader is stored"
        assert first["deduplicated_count"] == 1, "its twin is dropped"

        await h.tick()

        assert h.llm.call_count == 2, "neither the stored leader nor the dropped twin is re-sent"

    async def test_a_genuine_failure_is_still_retried_next_tick(self, enable_dedup):
        """Guard against over-suppression: only DROPS get a marker. A document
        that really failed carries a failure row, not a drop, and must still come
        back — otherwise this fix would silently swallow work."""
        from tg_parser.processing.llm.errors import LLMJsonParseError

        class _PoisonLLM(_CollapsingLLM):
            async def generate_with_usage(self, prompt, *args, **kwargs):
                if "poison" in prompt:
                    self.call_count += 1
                    raise LLMJsonParseError("unparseable")
                return await super().generate_with_usage(prompt, *args, **kwargs)

        messages = [_raw(1, "fresh wording one"), _raw(2, "poison payload")]
        h = _Harness(messages, llm=_PoisonLLM())

        first = await h.tick()
        assert first["deduplicated_count"] == 1
        assert first["failed_count"] == 1

        second = await h.tick()

        assert second["total_count"] == 1, "the failure is still selectable; the drop is not"
        assert h.drop_repo is not None
        assert set(h.drop_repo.drops) == {f"tg:{CHANNEL}:post:1"}


# ---------------------------------------------------------------------------
# The selection window — the invariant behind the invariant
# ---------------------------------------------------------------------------


class TestSelectionWindow:
    async def test_the_window_stops_offering_a_dropped_ref(self, enable_dedup):
        """Stated at the level the fix must hold at: the repository no longer
        returns the ref. Any storage shape that achieves this closes the loop;
        the assertion deliberately does not care which one."""
        messages = [_raw(1, "fresh wording one"), _raw(2, "fresh wording two")]
        h = _Harness(messages, llm=_CollapsingLLM())

        before = await h.raw_repo.list_unprocessed_by_channel(CHANNEL, limit=100)
        assert len(before) == 2

        await h.tick()

        after = await h.raw_repo.list_unprocessed_by_channel(CHANNEL, limit=100)
        assert after == [], "both dropped refs must have left the window"

    async def test_the_duplicate_is_still_not_stored_as_a_document(self, enable_dedup):
        """R10's invariant, unchanged: dedup still drops, and the marker is NOT a
        second ``processed_documents`` row. Keeping this true is why the drop is
        recorded in its own table — a document row would flow into
        ``new_doc_refs`` and from there into topicization and watchlist alerts."""
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2)]
        h = _Harness(messages, llm=_CollapsingLLM())

        await h.tick()

        assert set(h.processed_repo.docs) == {f"tg:{CHANNEL}:post:0"}, (
            "only the canonical document exists; the duplicates left no document"
        )

    async def test_force_reprocesses_a_dropped_ref(self, enable_dedup):
        """The operator escape hatch stays open: ``force`` bypasses the bounded
        load AND the dedup filter, so a marked ref can always be reprocessed."""
        messages = [_raw(1, "fresh wording one")]
        h = _Harness(messages, llm=_CollapsingLLM())

        await h.tick()
        assert h.llm.call_count == 1

        await h.tick(force=True)

        assert h.llm.call_count == 2, "force must still reach the LLM"


# ---------------------------------------------------------------------------
# What the marker carries
# ---------------------------------------------------------------------------


class TestMarkerContents:
    async def test_marker_records_the_canonical_document(self, enable_dedup):
        """Provenance: the same mapping ``metadata['dedup_of']`` carries for
        pre-LLM mirrors — the dropped ref → the document it collapsed into."""
        messages = [_raw(1, "fresh wording one")]
        h = _Harness(messages, llm=_CollapsingLLM())

        await h.tick()

        drop = await h.drop_repo.get_drop(f"tg:{CHANNEL}:post:1")
        assert drop is not None
        assert drop["canonical_source_ref"] == f"tg:{CHANNEL}:post:0"
        assert drop["channel_id"] == CHANNEL

    async def test_marker_carries_the_raw_hash_when_there_is_text(self, enable_dedup):
        """The second-order saving: with the raw hash stored, a LATER message
        carrying the same raw text can be recognised before the LLM call."""
        messages = [_raw(1, "fresh wording one")]
        h = _Harness(messages, llm=_CollapsingLLM())

        await h.tick()

        drop = await h.drop_repo.get_drop(f"tg:{CHANNEL}:post:1")
        assert drop["raw_content_hash"] == compute_content_hash(
            "fresh wording one", strip_url_query=True
        )

    async def test_marker_is_written_without_a_raw_hash_for_an_empty_message(self, enable_dedup):
        """Media-only / empty messages have no raw hash by construction
        (``_compute_raw_hash`` returns ``None``) and their synthetic
        ``text_clean`` collides en masse. The marker must still be written —
        exclusion is keyed on ``source_ref``, not on the hash — with the hash
        left NULL. These documents never cost an LLM call anyway, so the missing
        hash costs nothing beyond the second-order saving."""
        empty_clean = "[Пустое сообщение]"
        seeded = ProcessedDocument(
            id=f"doc:tg:{CHANNEL}:post:0",
            source_ref=f"tg:{CHANNEL}:post:0",
            source_message_id="0",
            channel_id=CHANNEL,
            processed_at=datetime(2026, 8, 12, tzinfo=UTC),
            text_clean=empty_clean,
            content_hash=compute_content_hash(empty_clean),
            metadata={"pipeline_version": "v1.0"},
        )
        messages = [_raw(1, "")]
        h = _Harness(messages, llm=_CollapsingLLM(), seed_canonical=False)
        h.processed_repo.docs[seeded.source_ref] = seeded

        first = await h.tick()

        assert h.llm.call_count == 0, "an empty message never reaches the LLM"
        assert first["deduplicated_count"] == 1
        drop = await h.drop_repo.get_drop(f"tg:{CHANNEL}:post:1")
        assert drop is not None
        assert drop["raw_content_hash"] is None
        assert drop["canonical_source_ref"] == f"tg:{CHANNEL}:post:0"

        await h.tick()
        assert h.llm.call_count == 0

    async def test_a_marker_is_never_a_canonical_target(self, enable_dedup):
        """The ``dedup_of`` chain question: a marker is terminal. Nothing can
        collapse INTO it (only ``processed_documents`` rows are returned by the
        content-hash lookups), so recording drops cannot lengthen the pre-existing
        mirror chain. The stored ``canonical_source_ref`` is therefore the
        immediate canonical, matching ``metadata['dedup_of']``, and is left
        unresolved on purpose."""
        messages = [_raw(1, "fresh wording one"), _raw(2, "fresh wording two")]
        h = _Harness(messages, llm=_CollapsingLLM())

        await h.tick()

        canonical_targets = {d["canonical_source_ref"] for d in h.drop_repo.drops.values()}
        assert canonical_targets <= set(h.processed_repo.docs), (
            "every canonical target is a real document, never another marker"
        )


# ---------------------------------------------------------------------------
# R10's arithmetic must survive untouched
# ---------------------------------------------------------------------------


class TestR10CountersUnchanged:
    async def test_first_tick_stats_match_r10_exactly(self, enable_dedup):
        """Recording the drop changes no counter: the document was still
        deduplicated, still not processed, still not a failure, and still
        attempted (it reached the LLM). This is the reason the marker lives
        outside ``processed_documents`` — a document row would move the drop into
        ``processed_count``."""
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2, 3)]
        h = _Harness(messages, llm=_CollapsingLLM())

        stats = await h.tick()

        assert stats["deduplicated_count"] == 3
        assert stats["processed_count"] == 0
        assert stats["skipped_count"] == 0
        assert stats["failed_count"] == 0
        assert stats["total_count"] == 3
        assert stats["attempted_count"] == 3
        assert stats["pre_llm_dedup_count"] == 0

    async def test_dedup_plateau_goes_to_zero(self, enable_dedup):
        """The observable prod signal: ``deduplicated_count`` was a per-tick
        plateau because the same documents returned every tick. After the fix it
        is paid once and then reads zero on a stable channel."""
        messages = [_raw(i, f"fresh wording {i}") for i in (1, 2, 3)]
        h = _Harness(messages, llm=_CollapsingLLM())

        assert (await h.tick())["deduplicated_count"] == 3
        assert (await h.tick()).get("deduplicated_count", 0) == 0
        assert (await h.tick()).get("deduplicated_count", 0) == 0

    async def test_idle_tick_omits_the_dedup_counter(self, enable_dedup):
        """Pre-existing shape, pinned because the prod verification depends on it:
        a tick with no work returns early and its stats dict carries NO
        ``deduplicated_count`` key. Reading it without a default (or without
        ``coalesce`` in SQL) turns a healthy idle tick into a missing-data error —
        which is exactly what a post-fix stable channel produces."""
        h = _Harness([], llm=_CollapsingLLM())

        stats = await h.tick()

        assert stats["total_count"] == 0
        assert "deduplicated_count" not in stats


# ---------------------------------------------------------------------------
# Degradation / flags
# ---------------------------------------------------------------------------


class TestDegradation:
    async def test_no_marker_when_dedup_is_disabled(self, enable_dedup, monkeypatch):
        """``dedup_enabled=False`` means nothing is dropped, so there is nothing
        to mark — the whole path stays dark."""
        from tg_parser.config import settings as cfg

        monkeypatch.setattr(cfg, "dedup_enabled", False)
        messages = [_raw(1, "fresh wording one")]
        h = _Harness(messages, llm=_CollapsingLLM())

        stats = await h.tick()

        assert stats["processed_count"] == 1, "with dedup off the duplicate is stored"
        assert h.drop_repo.drops == {}
        assert h.drop_repo.record_calls == 0

    async def test_drops_of_completed_chunks_survive_an_interrupted_batch(
        self, enable_dedup, monkeypatch
    ):
        """Same reasoning as Fix 3(b) for failures: a batch cancelled mid-flight
        must keep the bookkeeping of the chunks that already finished. If the
        journal were written only at the end of the batch, an interrupted tick
        would discard it and re-summarize those documents next tick — the exact
        leak being closed."""
        from tg_parser.config import settings as cfg
        from tg_parser.processing.pipeline import ProcessingPipelineImpl

        monkeypatch.setattr(cfg, "processing_persist_chunk_size", 1)

        repo = _FakeProcessedDocRepo()
        canonical = _canonical_doc()
        repo.docs[canonical.source_ref] = canonical
        drop_repo = _FakeDedupDropRepo()

        class _ExplodesOnThirdCall(_CollapsingLLM):
            async def generate_with_usage(self, prompt, *args, **kwargs):
                if self.call_count >= 2:
                    raise asyncio.CancelledError()
                return await super().generate_with_usage(prompt, *args, **kwargs)

        pipeline = ProcessingPipelineImpl(
            llm_client=_ExplodesOnThirdCall(),
            processed_doc_repo=repo,
            dedup_drop_repo=drop_repo,
            pipeline_version="processing:v1.0.0",
            model_id="mock-model",
        )

        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pipeline.process_batch(
                [_raw(i, f"fresh wording {i}") for i in (1, 2, 3)], concurrency=1
            )

        assert drop_repo.drops, (
            "the chunk that completed before the interruption must have journalled "
            "its drop, or its document is paid for again next tick"
        )

    async def test_pipeline_without_a_drop_repo_still_dedups(self, enable_dedup):
        """A pipeline constructed without the repo (CLI paths, older test
        doubles) must keep working exactly as before — the drop is simply not
        recorded, which is the pre-R11 behaviour."""
        from tg_parser.processing.pipeline import ProcessingPipelineImpl

        repo = _FakeProcessedDocRepo()
        canonical = _canonical_doc()
        repo.docs[canonical.source_ref] = canonical
        llm = _CollapsingLLM()
        pipeline = ProcessingPipelineImpl(
            llm_client=llm,
            processed_doc_repo=repo,
            pipeline_version="processing:v1.0.0",
            model_id="mock-model",
        )

        results = await pipeline.process_batch([_raw(1, "fresh wording one")], concurrency=2)

        assert results == []
        assert pipeline._batch_post_llm_dedup == 1


# ---------------------------------------------------------------------------
# The single-message path has the same defect
# ---------------------------------------------------------------------------


class TestSingleMessagePath:
    async def test_single_message_drop_is_recorded_and_not_repaid(self, enable_dedup):
        """``process_message`` returns the canonical document and writes nothing
        (``dedup_duplicate_found``) — the same shape of leak as the batch path.
        The marker is recorded, and a second call resolves from it without
        touching the LLM while returning the same document as before."""
        from tg_parser.processing.pipeline import ProcessingPipelineImpl

        repo = _FakeProcessedDocRepo()
        canonical = _canonical_doc()
        repo.docs[canonical.source_ref] = canonical
        drop_repo = _FakeDedupDropRepo()
        llm = _CollapsingLLM()
        pipeline = ProcessingPipelineImpl(
            llm_client=llm,
            processed_doc_repo=repo,
            dedup_drop_repo=drop_repo,
            pipeline_version="processing:v1.0.0",
            model_id="mock-model",
        )
        message = _raw(1, "fresh wording one")

        first = await pipeline.process_message(message)
        assert first.source_ref == canonical.source_ref
        assert llm.call_count == 1
        assert (await drop_repo.get_drop(message.source_ref)) is not None

        second = await pipeline.process_message(message)

        assert llm.call_count == 1, "the marked duplicate is resolved without a paid call"
        assert second.source_ref == canonical.source_ref, "same document as before the fix"
