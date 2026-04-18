"""F5-A Phase 3 — Deduplication tests (content-hash).

Structure:
- TestNormalizeForHash               : pure unit tests for normalize_for_hash
- TestComputeContentHash             : pure unit tests for compute_content_hash
- TestSettingsPhase3                 : env-var driven dedup_enabled / dedup_strip_url_query
- TestProcessedDocumentDomainContentHash : Pydantic validator for content_hash
- TestProcessedDocRepoContentHash    : roundtrip + find_by_content_hash (requires Postgres)
- TestMigrationIdempotency           : _ensure_content_hash_column + index existence
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
        assert "?a=1" in normalize_for_hash(
            "visit https://x.com/p?a=1", strip_url_query=False
        )

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
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)

        async with test_db.processing_storage_engine.begin() as conn:
            await conn.execute(
                sql_text(
                    "DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_ph3:%'"
                )
            )

        session = test_db.processing_storage_session()
        try:
            yield SAProcessedDocumentRepo(session), test_db
        finally:
            await session.close()
            async with test_db.processing_storage_engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "DELETE FROM processed_documents WHERE source_ref LIKE 'tg:f5a_ph3:%'"
                    )
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
# 6. TestMigrationIdempotency
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_PG, reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)")
class TestMigrationIdempotency:
    async def test_ensure_content_hash_column_is_idempotent(self, test_db):
        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            _ensure_content_hash_column,
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)
        await _ensure_content_hash_column(test_db.processing_storage_engine)
        await _ensure_content_hash_column(test_db.processing_storage_engine)
        await _ensure_content_hash_column(test_db.processing_storage_engine)

    async def test_content_hash_column_exists(self, test_db):
        from sqlalchemy import text as sql_text

        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)

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

        from tg_parser.storage.sqlalchemy.schemas.processing_storage import (
            init_processing_storage_schema,
        )

        await init_processing_storage_schema(test_db.processing_storage_engine)

        async with test_db.processing_storage_engine.connect() as conn:
            result = await conn.execute(
                sql_text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE indexname = 'idx_pd_channel_content_hash'"
                )
            )
            assert result.fetchone() is not None
