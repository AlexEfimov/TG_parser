"""F5-A Phase 3 — Deduplication tests (content-hash).

Structure:
- TestNormalizeForHash               : pure unit tests for normalize_for_hash
- TestComputeContentHash             : pure unit tests for compute_content_hash
- TestSettingsPhase3                 : env-var driven dedup_enabled / dedup_strip_url_query
- TestProcessedDocumentDomainContentHash : Pydantic validator for content_hash
- TestProcessedDocRepoContentHash    : roundtrip + find_by_content_hash (requires Postgres)
- TestMigrationContentHash           : content_hash column + index existence (alembic-managed)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tg_parser.config.settings import Settings
from tg_parser.domain.hashing import compute_content_hash, normalize_for_hash
from tg_parser.domain.models import ProcessedDocument

_SKIP_PG = not os.environ.get("TEST_POSTGRES")


# ---------------------------------------------------------------------------
# 1. TestNormalizeForHash — pure unit tests
# ---------------------------------------------------------------------------


class TestNormalizeForHash:
    def test_lowercase_folding(self):
        assert normalize_for_hash("Hello World") == normalize_for_hash("hello world")
        assert normalize_for_hash("HELLO") == "hello"

    def test_whitespace_collapse_all_kinds(self):
        assert normalize_for_hash("a  b") == "a b"
        assert normalize_for_hash("a\tb") == "a b"
        assert normalize_for_hash("a\nb") == "a b"
        assert normalize_for_hash("a\r\nb") == "a b"
        assert normalize_for_hash("a   \t\n b") == "a b"

    def test_leading_trailing_whitespace_stripped(self):
        assert normalize_for_hash("  hello  ") == "hello"
        assert normalize_for_hash("\n\thello\n") == "hello"

    def test_url_query_stripped_by_default(self):
        assert normalize_for_hash("visit https://x.com/p?a=1&b=2") == normalize_for_hash(
            "visit https://x.com/p"
        )

    def test_url_query_preserved_when_flag_off(self):
        # With flag off, different URLs hash differently
        assert normalize_for_hash(
            "visit https://x.com/p?a=1", strip_url_query=False
        ) != normalize_for_hash("visit https://x.com/p", strip_url_query=False)
        assert "?a=1" in normalize_for_hash("visit https://x.com/p?a=1", strip_url_query=False)

    def test_url_fragment_also_stripped(self):
        assert normalize_for_hash("see https://x.com/page#section-2") == normalize_for_hash(
            "see https://x.com/page"
        )

    def test_url_in_path_not_touched(self):
        original = "read https://x.com/some/path"
        # No ?..# present — output should just be lowercased/whitespace-collapsed
        result = normalize_for_hash(original)
        assert "https://x.com/some/path" in result

    def test_multiple_urls_all_stripped(self):
        a = normalize_for_hash("a https://x.com/p?x=1 and b https://y.com/q?y=2")
        b = normalize_for_hash("a https://x.com/p and b https://y.com/q")
        assert a == b

    def test_unicode_safe(self):
        # Emoji and cyrillic preserved (but lowercased)
        got = normalize_for_hash("Привет 👋 Мир")
        assert "привет" in got
        assert "👋" in got
        assert "мир" in got

    def test_empty_string_returns_empty(self):
        assert normalize_for_hash("") == ""
        assert normalize_for_hash("   \n\t  ") == ""

    def test_very_long_input_is_fine(self):
        text = ("foo bar baz " * 1000).strip()
        got = normalize_for_hash(text)
        # whitespace collapsed → no double spaces
        assert "  " not in got


# ---------------------------------------------------------------------------
# 2. TestComputeContentHash — pure unit tests
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_hash_length_is_64(self):
        assert len(compute_content_hash("hello")) == 64
        assert len(compute_content_hash("")) == 64
        assert len(compute_content_hash("a" * 10_000)) == 64

    def test_hash_is_lowercase_hex(self):
        h = compute_content_hash("Some Text")
        assert all(c in "0123456789abcdef" for c in h)
        assert h.lower() == h

    def test_same_input_produces_same_hash(self):
        assert compute_content_hash("hello world") == compute_content_hash("hello world")

    def test_normalized_variants_produce_same_hash(self):
        assert compute_content_hash("Hello  world") == compute_content_hash("hello world")
        assert compute_content_hash(" HELLO\tWORLD\n") == compute_content_hash("hello world")

    def test_url_query_stripped_affects_hash_by_default(self):
        a = compute_content_hash("go https://x.com/p?utm=1")
        b = compute_content_hash("go https://x.com/p?utm=2")
        assert a == b

    def test_url_query_preserved_when_flag_off(self):
        a = compute_content_hash("go https://x.com/p?utm=1", strip_url_query=False)
        b = compute_content_hash("go https://x.com/p?utm=2", strip_url_query=False)
        assert a != b

    def test_different_text_different_hash(self):
        assert compute_content_hash("hello") != compute_content_hash("world")


# ---------------------------------------------------------------------------
# 3. TestSettingsPhase3 — env-driven settings
# ---------------------------------------------------------------------------


class TestSettingsPhase3:
    def _base_kwargs(self) -> dict:
        return {
            "telegram_api_id": 1,
            "telegram_api_hash": "h",
            "telegram_phone": "+1",
            "openai_api_key": "sk-x",
        }

    def test_defaults(self):
        s = Settings(**self._base_kwargs())
        assert s.dedup_enabled is True
        assert s.dedup_strip_url_query is True

    def test_env_override_disabled(self, monkeypatch):
        monkeypatch.setenv("DEDUP_ENABLED", "false")
        s = Settings(**self._base_kwargs())
        assert s.dedup_enabled is False

    def test_env_override_strip_url_false(self, monkeypatch):
        monkeypatch.setenv("DEDUP_STRIP_URL_QUERY", "false")
        s = Settings(**self._base_kwargs())
        assert s.dedup_strip_url_query is False


# ---------------------------------------------------------------------------
# 4. TestProcessedDocumentDomainContentHash — Pydantic validator
# ---------------------------------------------------------------------------


def _doc_kwargs(content_hash: str | None = None) -> dict:
    kwargs = {
        "id": "doc:tg:ch:post:1",
        "source_ref": "tg:ch:post:1",
        "source_message_id": "1",
        "channel_id": "ch",
        "processed_at": datetime(2026, 4, 18, tzinfo=UTC),
        "text_clean": "hello",
    }
    if content_hash is not None:
        kwargs["content_hash"] = content_hash
    return kwargs


class TestProcessedDocumentDomainContentHash:
    def test_none_is_default(self):
        doc = ProcessedDocument(**_doc_kwargs())
        assert doc.content_hash is None

    def test_accepts_valid_sha256_hex(self):
        h = "a" * 64
        doc = ProcessedDocument(**_doc_kwargs(content_hash=h))
        assert doc.content_hash == h

    def test_accepts_real_computed_hash(self):
        h = compute_content_hash("some text")
        doc = ProcessedDocument(**_doc_kwargs(content_hash=h))
        assert doc.content_hash == h

    def test_rejects_too_short(self):
        with pytest.raises(ValidationError):
            ProcessedDocument(**_doc_kwargs(content_hash="a" * 63))

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            ProcessedDocument(**_doc_kwargs(content_hash="a" * 65))

    def test_rejects_uppercase_hex(self):
        with pytest.raises(ValidationError):
            ProcessedDocument(**_doc_kwargs(content_hash="A" * 64))

    def test_rejects_non_hex(self):
        with pytest.raises(ValidationError):
            ProcessedDocument(**_doc_kwargs(content_hash="g" * 64))


# ---------------------------------------------------------------------------
# 5. TestProcessedDocRepoContentHash — roundtrip + find_by_content_hash
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestProcessedDocRepoContentHash:
    @pytest.fixture
    async def repo_session(self, test_db):
        from sqlalchemy import text as sql_text

        from tg_parser.storage.sqlalchemy.processed_document_repo import (
            SAProcessedDocumentRepo,
        )

        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_ph3:%'")
            )

        session = test_db.processing_storage_session()
        try:
            yield SAProcessedDocumentRepo(session), test_db
        finally:
            await session.close()
            async with test_db.processing_storage_engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_ph3:%'")
                )

    def _make_doc(
        self,
        source_ref: str,
        channel_id: str,
        text_clean: str,
        content_hash: str | None,
    ) -> ProcessedDocument:
        return ProcessedDocument(
            id=f"doc:{source_ref}",
            source_ref=source_ref,
            source_message_id=source_ref.rsplit(":", 1)[-1],
            channel_id=channel_id,
            processed_at=datetime(2026, 4, 18, tzinfo=UTC),
            text_clean=text_clean,
            content_hash=content_hash,
        )

    async def test_upsert_persists_content_hash(self, repo_session):
        repo, _ = repo_session
        h = compute_content_hash("hello world")
        doc = self._make_doc("tg:f5a_ph3:post:1", "f5a_ph3_ch", "hello world", h)
        await repo.upsert(doc)

        got = await repo.get_by_source_ref("tg:f5a_ph3:post:1")
        assert got is not None
        assert got.content_hash == h

    async def test_upsert_with_none_content_hash_stores_null(self, repo_session):
        repo, _ = repo_session
        doc = self._make_doc("tg:f5a_ph3:post:2", "f5a_ph3_ch", "hello", None)
        await repo.upsert(doc)

        got = await repo.get_by_source_ref("tg:f5a_ph3:post:2")
        assert got is not None
        assert got.content_hash is None

    async def test_find_by_content_hash_hit(self, repo_session):
        repo, _ = repo_session
        h = compute_content_hash("some unique text for hit")
        doc = self._make_doc("tg:f5a_ph3:post:3", "f5a_ph3_ch", "text", h)
        await repo.upsert(doc)

        got = await repo.find_by_content_hash("f5a_ph3_ch", h)
        assert got is not None
        assert got.source_ref == "tg:f5a_ph3:post:3"
        assert got.content_hash == h

    async def test_find_by_content_hash_miss_returns_none(self, repo_session):
        repo, _ = repo_session
        missing = "0" * 64
        got = await repo.find_by_content_hash("f5a_ph3_ch", missing)
        assert got is None

    async def test_find_by_content_hash_different_channel_miss(self, repo_session):
        repo, _ = repo_session
        h = compute_content_hash("cross-channel text")
        doc = self._make_doc("tg:f5a_ph3:post:4", "f5a_ph3_ch_a", "t", h)
        await repo.upsert(doc)

        # Same hash, different channel — no match
        got = await repo.find_by_content_hash("f5a_ph3_ch_b", h)
        assert got is None

    async def test_find_by_content_hash_ignores_null_rows(self, repo_session):
        repo, _ = repo_session
        # Insert a NULL-hash row
        doc_null = self._make_doc("tg:f5a_ph3:post:5", "f5a_ph3_ch", "t", None)
        await repo.upsert(doc_null)

        # Searching with all-zero hash must not match the NULL row
        got = await repo.find_by_content_hash("f5a_ph3_ch", "0" * 64)
        assert got is None

    async def test_upsert_batch_persists_content_hash(self, repo_session):
        repo, _ = repo_session
        h1 = compute_content_hash("text-1")
        h2 = compute_content_hash("text-2")
        docs = [
            self._make_doc("tg:f5a_ph3:post:6", "f5a_ph3_ch", "text-1", h1),
            self._make_doc("tg:f5a_ph3:post:7", "f5a_ph3_ch", "text-2", h2),
        ]
        n = await repo.upsert_batch(docs)
        assert n == 2

        got_1 = await repo.get_by_source_ref("tg:f5a_ph3:post:6")
        got_2 = await repo.get_by_source_ref("tg:f5a_ph3:post:7")
        assert got_1 is not None and got_1.content_hash == h1
        assert got_2 is not None and got_2.content_hash == h2

    async def test_upsert_overwrites_content_hash_on_conflict(self, repo_session):
        repo, _ = repo_session
        h_old = compute_content_hash("old text")
        h_new = compute_content_hash("new text")

        doc_v1 = self._make_doc("tg:f5a_ph3:post:8", "f5a_ph3_ch", "old text", h_old)
        await repo.upsert(doc_v1)

        doc_v2 = self._make_doc("tg:f5a_ph3:post:8", "f5a_ph3_ch", "new text", h_new)
        await repo.upsert(doc_v2)

        got = await repo.get_by_source_ref("tg:f5a_ph3:post:8")
        assert got is not None
        assert got.content_hash == h_new


# ---------------------------------------------------------------------------
# 6. TestMigrationContentHash — alembic-managed schema reflection (DI-19)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestMigrationContentHash:
    """Verify content_hash column + partial composite index are present.

    Pre-DI-19 these were ``_ensure_content_hash_column`` smoke tests; the
    helper is gone (alembic now creates the column + index directly).
    The runtime invariants are the same — checked here against the
    alembic-built schema via ``information_schema`` / ``pg_indexes``.
    """

    async def test_content_hash_column_exists(self, test_db):
        from sqlalchemy import text as sql_text

        async with test_db.processing_storage_engine.connect() as conn:
            result = await conn.execute(
                sql_text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'processed_documents' "
                    "AND column_name = 'content_hash'"
                )
            )
            assert result.fetchone() is not None

    async def test_content_hash_index_exists(self, test_db):
        from sqlalchemy import text as sql_text

        async with test_db.processing_storage_engine.connect() as conn:
            result = await conn.execute(
                sql_text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE indexname = 'idx_pd_channel_content_hash'"
                )
            )
            assert result.fetchone() is not None


# ---------------------------------------------------------------------------
# 7. TestDedupPipeline — single-path hook (mocks repo)
# ---------------------------------------------------------------------------


from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from tg_parser.domain.models import MessageType, RawTelegramMessage  # noqa: E402


class _FixedMockLLM:
    """Mock LLM for dedup tests.

    Two modes:
    - ``text_clean`` set (default): returns that exact value regardless of
      prompt — makes content_hash deterministic/uniform across messages.
    - ``text_clean=None``: echoes the *last* non-empty, non-comment line of
      the prompt as ``text_clean`` — lets us test per-message hash divergence.
    """

    def __init__(self, text_clean: str | None = "duplicate text"):
        self._text_clean = text_clean
        self.call_count = 0

    async def generate(self, prompt: str, *args, **kwargs) -> str:
        import json as _json

        self.call_count += 1
        if self._text_clean is not None:
            tc = self._text_clean
        else:
            # Echo the full prompt as text_clean so different input messages
            # (different {text} substitutions) produce different hashes.
            tc = prompt
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


def _make_raw(source_ref: str, channel: str, text: str) -> RawTelegramMessage:
    return RawTelegramMessage(
        id=source_ref.rsplit(":", 1)[-1],
        message_type=MessageType.POST,
        source_ref=source_ref,
        channel_id=channel,
        date=datetime(2026, 4, 18, tzinfo=UTC),
        text=text,
    )


def _build_existing_doc(source_ref: str, channel: str, text_clean: str) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=source_ref.rsplit(":", 1)[-1],
        channel_id=channel,
        processed_at=datetime(2026, 4, 18, tzinfo=UTC),
        text_clean=text_clean,
        content_hash=compute_content_hash(text_clean),
    )


def _make_pipeline(repo, failure_repo=None, llm=None):
    from tg_parser.processing.pipeline import ProcessingPipelineImpl

    return ProcessingPipelineImpl(
        llm_client=llm or _FixedMockLLM(),
        processed_doc_repo=repo,
        failure_repo=failure_repo,
        pipeline_version="processing:v1.0.0",
        model_id="mock-model",
    )


def _make_repo_mock(existing_doc: ProcessedDocument | None = None):
    repo = MagicMock()
    repo.exists = AsyncMock(return_value=False)
    repo.get_by_source_ref = AsyncMock(return_value=None)
    repo.upsert = AsyncMock(return_value=None)
    repo.upsert_batch = AsyncMock(return_value=None)
    repo.find_by_content_hash = AsyncMock(return_value=existing_doc)
    return repo


@pytest.fixture
def enable_dedup(monkeypatch):
    from tg_parser.config import settings as cfg

    monkeypatch.setattr(cfg, "dedup_enabled", True)
    monkeypatch.setattr(cfg, "dedup_strip_url_query", True)


@pytest.fixture
def disable_dedup(monkeypatch):
    from tg_parser.config import settings as cfg

    monkeypatch.setattr(cfg, "dedup_enabled", False)


class TestDedupPipeline:
    async def test_single_message_dedup_skip_same_channel(self, enable_dedup):
        existing = _build_existing_doc("tg:ch:post:0", "ch", "duplicate text")
        repo = _make_repo_mock(existing_doc=existing)
        pipeline = _make_pipeline(repo)

        new_msg = _make_raw("tg:ch:post:1", "ch", "duplicate text")
        got = await pipeline.process_message(new_msg)

        assert got is existing
        repo.upsert.assert_not_called()
        repo.find_by_content_hash.assert_awaited_once()

    async def test_single_message_different_channel_not_deduped(self, enable_dedup):
        # repo.find_by_content_hash returns None when scoped to new message's channel.
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo)

        new_msg = _make_raw("tg:ch_b:post:1", "ch_b", "duplicate text")
        got = await pipeline.process_message(new_msg)

        assert got.source_ref == "tg:ch_b:post:1"
        repo.upsert.assert_awaited_once()

    async def test_dedup_disabled_bypasses_lookup(self, disable_dedup):
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo)

        new_msg = _make_raw("tg:ch:post:1", "ch", "duplicate text")
        await pipeline.process_message(new_msg)

        repo.find_by_content_hash.assert_not_called()
        repo.upsert.assert_awaited_once()

    async def test_empty_text_no_hash_not_deduped(self, enable_dedup):
        repo = _make_repo_mock(existing_doc=None)

        # Media-only path produces content_hash from the synthetic "[...]" text,
        # so for this case we patch _process_single_message to return a doc
        # with content_hash=None explicitly.
        pipeline = _make_pipeline(repo)

        empty_doc = ProcessedDocument(
            id="doc:tg:ch:post:1",
            source_ref="tg:ch:post:1",
            source_message_id="1",
            channel_id="ch",
            processed_at=datetime(2026, 4, 18, tzinfo=UTC),
            text_clean="synthetic",
            content_hash=None,
        )
        pipeline._process_single_message = AsyncMock(return_value=empty_doc)

        new_msg = _make_raw("tg:ch:post:1", "ch", "hi")
        await pipeline.process_message(new_msg)

        repo.find_by_content_hash.assert_not_called()
        repo.upsert.assert_awaited_once()

    async def test_self_match_on_reprocess_does_not_skip(self, enable_dedup):
        # find_by_content_hash returns a doc with the SAME source_ref → skip
        # guard ignores it and proceeds with upsert.
        same_ref = "tg:ch:post:1"
        existing = _build_existing_doc(same_ref, "ch", "duplicate text")
        repo = _make_repo_mock(existing_doc=existing)
        pipeline = _make_pipeline(repo)

        new_msg = _make_raw(same_ref, "ch", "duplicate text")
        got = await pipeline.process_message(new_msg)

        repo.upsert.assert_awaited_once()
        assert got.source_ref == same_ref

    async def test_force_reprocess_bypasses_dedup(self, enable_dedup):
        existing = _build_existing_doc("tg:ch:post:0", "ch", "duplicate text")
        repo = _make_repo_mock(existing_doc=existing)
        pipeline = _make_pipeline(repo)

        new_msg = _make_raw("tg:ch:post:1", "ch", "duplicate text")
        got = await pipeline.process_message(new_msg, force=True)

        # With force=True, find_by_content_hash MUST NOT be called and
        # upsert MUST happen (the new doc, not the existing one).
        repo.find_by_content_hash.assert_not_called()
        repo.upsert.assert_awaited_once()
        assert got.source_ref == "tg:ch:post:1"

    async def test_metric_incremented_on_detection(self, enable_dedup):
        from tg_parser.api.metrics import DEDUP_DUPLICATES_DETECTED

        before = DEDUP_DUPLICATES_DETECTED.labels(channel_id="ch_metric").inc.__self__._value.get()  # noqa: SLF001
        existing = _build_existing_doc("tg:ch_metric:post:0", "ch_metric", "duplicate text")
        repo = _make_repo_mock(existing_doc=existing)
        pipeline = _make_pipeline(repo)

        new_msg = _make_raw("tg:ch_metric:post:1", "ch_metric", "duplicate text")
        await pipeline.process_message(new_msg)

        after = DEDUP_DUPLICATES_DETECTED.labels(channel_id="ch_metric").inc.__self__._value.get()  # noqa: SLF001
        assert after == before + 1


# ---------------------------------------------------------------------------
# 8. TestBatchDedup — within-batch + DB dedup
# ---------------------------------------------------------------------------


class TestBatchDedup:
    async def test_within_batch_duplicates_removed(self, enable_dedup):
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo)

        h = compute_content_hash("same text")
        docs = [
            ProcessedDocument(
                id=f"doc:tg:ch:post:{i}",
                source_ref=f"tg:ch:post:{i}",
                source_message_id=str(i),
                channel_id="ch",
                processed_at=datetime(2026, 4, 18, tzinfo=UTC),
                text_clean="same text",
                content_hash=h,
            )
            for i in range(1, 4)
        ]

        kept = await pipeline._filter_duplicates(docs)
        assert len(kept) == 1
        assert kept[0].source_ref == "tg:ch:post:1"

    async def test_within_batch_plus_db_duplicate_removed(self, enable_dedup):
        existing = _build_existing_doc("tg:ch:post:0", "ch", "text A")
        repo = _make_repo_mock(existing_doc=existing)
        pipeline = _make_pipeline(repo)

        h_a = compute_content_hash("text A")
        h_b = compute_content_hash("text B")
        docs = [
            ProcessedDocument(
                id="doc:tg:ch:post:1",
                source_ref="tg:ch:post:1",
                source_message_id="1",
                channel_id="ch",
                processed_at=datetime(2026, 4, 18, tzinfo=UTC),
                text_clean="text A",
                content_hash=h_a,  # duplicates existing DB doc
            ),
            ProcessedDocument(
                id="doc:tg:ch:post:2",
                source_ref="tg:ch:post:2",
                source_message_id="2",
                channel_id="ch",
                processed_at=datetime(2026, 4, 18, tzinfo=UTC),
                text_clean="text B",
                content_hash=h_b,
            ),
        ]

        # For the second doc, find_by_content_hash should return None.
        async def _find(channel_id, content_hash):
            if content_hash == h_a:
                return existing
            return None

        repo.find_by_content_hash = AsyncMock(side_effect=_find)

        kept = await pipeline._filter_duplicates(docs)
        refs = [d.source_ref for d in kept]
        assert "tg:ch:post:1" not in refs
        assert "tg:ch:post:2" in refs

    async def test_batch_with_no_duplicates_passes_all_through(self, enable_dedup):
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo)

        docs = [
            ProcessedDocument(
                id=f"doc:tg:ch:post:{i}",
                source_ref=f"tg:ch:post:{i}",
                source_message_id=str(i),
                channel_id="ch",
                processed_at=datetime(2026, 4, 18, tzinfo=UTC),
                text_clean=f"unique text {i}",
                content_hash=compute_content_hash(f"unique text {i}"),
            )
            for i in range(1, 4)
        ]

        kept = await pipeline._filter_duplicates(docs)
        assert len(kept) == 3
        assert [d.source_ref for d in kept] == [d.source_ref for d in docs]

    async def test_batch_metric_incremented_per_duplicate(self, enable_dedup):
        from tg_parser.api.metrics import DEDUP_DUPLICATES_DETECTED

        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo)

        counter = DEDUP_DUPLICATES_DETECTED.labels(channel_id="ch_bm")
        before = counter._value.get()  # noqa: SLF001

        h = compute_content_hash("batch dup")
        docs = [
            ProcessedDocument(
                id=f"doc:tg:ch_bm:post:{i}",
                source_ref=f"tg:ch_bm:post:{i}",
                source_message_id=str(i),
                channel_id="ch_bm",
                processed_at=datetime(2026, 4, 18, tzinfo=UTC),
                text_clean="batch dup",
                content_hash=h,
            )
            for i in range(1, 4)
        ]

        kept = await pipeline._filter_duplicates(docs)
        after = counter._value.get()  # noqa: SLF001

        assert len(kept) == 1
        # Two duplicates dropped → counter incremented by 2.
        assert after == before + 2

    async def test_batch_dedup_disabled_bypasses_filter(self, disable_dedup):
        """When DEDUP_ENABLED=False, _filter_duplicates must not be called in
        the parallel batch path — all LLM results reach upsert_batch."""
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo, llm=_FixedMockLLM(text_clean="same"))

        messages = [_make_raw(f"tg:ch_bd:post:{i}", "ch_bd", "same") for i in range(1, 4)]
        results = await pipeline.process_batch(messages, concurrency=3)

        assert len(results) == 3
        repo.find_by_content_hash.assert_not_called()

    async def test_batch_force_bypasses_filter(self, enable_dedup):
        """force=True in process_batch must bypass dedup (all three duplicates
        persist to upsert_batch)."""
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo, llm=_FixedMockLLM(text_clean="same text"))

        messages = [_make_raw(f"tg:ch_bf:post:{i}", "ch_bf", "same text") for i in range(1, 4)]
        results = await pipeline.process_batch(messages, concurrency=3, force=True)

        assert len(results) == 3
        repo.find_by_content_hash.assert_not_called()

    async def test_batch_return_excludes_skipped_duplicates(self, enable_dedup):
        """Documented visible behaviour: process_batch(...) returns a list
        shorter than len(messages) when duplicates are present.

        Uses echo-mode mock so the third (unique) message keeps its own hash.
        """
        repo = _make_repo_mock(existing_doc=None)
        pipeline = _make_pipeline(repo, llm=_FixedMockLLM(text_clean=None))

        messages = [
            _make_raw("tg:ch_br:post:1", "ch_br", "duplicate text"),
            _make_raw("tg:ch_br:post:2", "ch_br", "duplicate text"),
            _make_raw("tg:ch_br:post:3", "ch_br", "unique different text"),
        ]

        results = await pipeline.process_batch(messages, concurrency=3)
        refs = {d.source_ref for d in results}

        # One of the two duplicates is dropped, unique is kept.
        assert len(results) == 2
        assert "tg:ch_br:post:3" in refs
        # Exactly one of post:1 / post:2 should remain.
        assert len({"tg:ch_br:post:1", "tg:ch_br:post:2"} & refs) == 1


# ---------------------------------------------------------------------------
# 9. TestBackfillCLI — cursor-pagination, dry-run, channel scope
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestBackfillCLI:
    @pytest.fixture
    async def prepared_db(self, test_db, monkeypatch):
        """Prevent ``close()`` from tearing down shared engines mid-test and
        clean up ``tg:f5a_ph3_bf:*`` rows.

        DI-19 (Sprint A.7): schema is alembic-managed via the session
        fixture in conftest.py; no ``init_*_schema`` call needed here.
        """
        from sqlalchemy import text as sql_text

        # Backfill command calls Database.from_settings (→ same singleton) and
        # then db.close() at the end.  We neutralize close() so the shared
        # test_db keeps its engines open for subsequent assertions.
        monkeypatch.setattr(test_db, "close", AsyncMock())

        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_ph3_bf:%'")
            )

        yield test_db

        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                sql_text("DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_ph3_bf:%'")
            )

    async def _insert_null(self, engine, source_ref: str, channel_id: str, text_clean: str) -> None:
        from sqlalchemy import text as sql_text

        async with engine.begin() as conn:
            await conn.execute(
                sql_text(
                    "INSERT INTO processed_documents "
                    "(source_ref, id, source_message_id, channel_id, processed_at, "
                    " text_clean, summary, topics_json, entities_json, language, "
                    " metadata_json, content_hash) "
                    "VALUES (:sr, :id, :smid, :ch, :ts, :tc, NULL, NULL, NULL, 'ru', NULL, NULL)"
                ),
                {
                    "sr": source_ref,
                    "id": f"doc:{source_ref}",
                    "smid": source_ref.rsplit(":", 1)[-1],
                    "ch": channel_id,
                    # DI-19: alembic types ``processed_at`` as DateTime;
                    # the legacy DDL accepted ISO-8601 strings.
                    "ts": datetime(2026, 4, 18, tzinfo=UTC),
                    "tc": text_clean,
                },
            )

    async def _hash_of(self, engine, source_ref: str) -> str | None:
        from sqlalchemy import text as sql_text

        async with engine.connect() as conn:
            result = await conn.execute(
                sql_text("SELECT content_hash FROM processed_documents WHERE source_ref = :sr"),
                {"sr": source_ref},
            )
            row = result.fetchone()
            return row.content_hash if row else None

    async def test_backfill_dry_run_does_not_write(self, prepared_db):
        from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

        engine = prepared_db.processing_storage_engine
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:1", "ch", "hello")
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:2", "ch", "world")

        stats = await run_backfill_content_hash(batch_size=500, dry_run=True)

        assert stats.total_scanned == 2
        assert stats.total_hashed == 2
        assert await self._hash_of(engine, "tg:f5a_ph3_bf:post:1") is None
        assert await self._hash_of(engine, "tg:f5a_ph3_bf:post:2") is None

    async def test_backfill_fills_null_hashes(self, prepared_db):
        from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

        engine = prepared_db.processing_storage_engine
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:3", "ch", "hello")
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:4", "ch", "world")

        stats = await run_backfill_content_hash(batch_size=500, dry_run=False)

        assert stats.total_hashed == 2
        h3 = await self._hash_of(engine, "tg:f5a_ph3_bf:post:3")
        h4 = await self._hash_of(engine, "tg:f5a_ph3_bf:post:4")
        assert h3 is not None
        assert h4 is not None
        assert h3.strip() == compute_content_hash("hello")
        assert h4.strip() == compute_content_hash("world")

    async def test_backfill_channel_filter_scopes_update(self, prepared_db):
        from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

        engine = prepared_db.processing_storage_engine
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:5", "ch_a", "in-a")
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:6", "ch_b", "in-b")

        stats = await run_backfill_content_hash(channel_id="ch_a", batch_size=500)

        assert stats.total_hashed == 1
        h_a = await self._hash_of(engine, "tg:f5a_ph3_bf:post:5")
        h_b = await self._hash_of(engine, "tg:f5a_ph3_bf:post:6")
        assert h_a is not None
        assert h_b is None  # channel_b untouched

    async def test_backfill_existing_duplicates_all_get_same_hash(self, prepared_db):
        from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

        engine = prepared_db.processing_storage_engine
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:7", "ch", "dup text")
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:8", "ch", "dup text")

        stats = await run_backfill_content_hash(batch_size=500)
        assert stats.total_hashed == 2

        h7 = await self._hash_of(engine, "tg:f5a_ph3_bf:post:7")
        h8 = await self._hash_of(engine, "tg:f5a_ph3_bf:post:8")
        assert h7 is not None and h8 is not None
        assert h7.strip() == h8.strip()

    async def test_backfill_is_idempotent_skips_already_hashed(self, prepared_db):
        """Re-running backfill must not re-process rows whose content_hash is
        already set (WHERE content_hash IS NULL filter)."""
        from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

        engine = prepared_db.processing_storage_engine
        await self._insert_null(engine, "tg:f5a_ph3_bf:post:20", "ch", "seed text")

        first = await run_backfill_content_hash(batch_size=500)
        assert first.total_hashed == 1

        second = await run_backfill_content_hash(batch_size=500)
        assert second.total_scanned == 0
        assert second.total_hashed == 0

    async def test_backfill_paginates_beyond_batch_size(self, prepared_db):
        """Cursor-pagination must NOT miss rows between iterations after
        UPDATE shrinks the NULL-set. Seed more rows than batch_size."""
        from tg_parser.cli.backfill_content_hash_cmd import run_backfill_content_hash

        engine = prepared_db.processing_storage_engine
        for i in range(9, 14):
            await self._insert_null(engine, f"tg:f5a_ph3_bf:post:{i}", "ch", f"text {i}")

        stats = await run_backfill_content_hash(batch_size=2)
        assert stats.total_hashed == 5
        for i in range(9, 14):
            assert await self._hash_of(engine, f"tg:f5a_ph3_bf:post:{i}") is not None


# ---------------------------------------------------------------------------
# 10. TestDedupMetric — Prometheus wiring
# ---------------------------------------------------------------------------


class TestDedupMetric:
    def test_record_dedup_duplicate_detected_increments_counter(self):
        from tg_parser.api.metrics import (
            DEDUP_DUPLICATES_DETECTED,
            record_dedup_duplicate_detected,
        )

        counter = DEDUP_DUPLICATES_DETECTED.labels(channel_id="ch_unit_test")
        before = counter._value.get()  # noqa: SLF001

        record_dedup_duplicate_detected(channel_id="ch_unit_test")

        after = counter._value.get()  # noqa: SLF001
        assert after == before + 1
