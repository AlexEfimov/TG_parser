"""Tests for F2 Parse-Only Export (raw channel export).

Covers:

- ``tg_parser.export.raw_export`` pure writer (JSON envelope + NDJSON).
- ``_group_messages`` helper (posts/comments/orphans grouping).
- ``tg_parser.services.export_service.run_export(level=...)`` branching
  (raw + backward-compat for processed / full).
- CLI ``tg_parser export --level ... --format ...`` wiring + validation.
- API ``POST /api/v1/export`` level-aware job creation + download media types.
- MCP ``export_channel`` / ``get_export_status`` tools.
- Bot ``export_channel`` tool with FSInputFile delivery + 50 MB size gate.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from typer.testing import CliRunner

from tg_parser.api.main import create_app
from tg_parser.api.schemas import ExportFormat, ExportLevel
from tg_parser.cli.app import app as cli_app
from tg_parser.domain.models import MessageType, RawTelegramMessage
from tg_parser.export.raw_export import (
    SCHEMA_VERSION,
    _group_messages,
    _message_payload,
    export_raw_channel_json,
    export_raw_channel_ndjson,
)

# ============================================================================
# Helpers
# ============================================================================


def _raw_post(
    msg_id: str,
    *,
    channel_id: str = "ch1",
    date: datetime | None = None,
    text: str = "post body",
    language: str | None = "ru",
    raw_payload: dict | None = None,
) -> RawTelegramMessage:
    return RawTelegramMessage(
        id=msg_id,
        message_type=MessageType.POST,
        source_ref=f"tg:{channel_id}:post:{msg_id}",
        channel_id=channel_id,
        date=date or datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        text=text,
        language=language,
        raw_payload=raw_payload,
    )


def _raw_comment(
    msg_id: str,
    parent_id: str | None,
    *,
    channel_id: str = "ch1",
    date: datetime | None = None,
    text: str = "comment body",
    language: str | None = "ru",
    thread_id: str | None = None,
    raw_payload: dict | None = None,
) -> RawTelegramMessage:
    return RawTelegramMessage(
        id=msg_id,
        message_type=MessageType.COMMENT,
        source_ref=f"tg:{channel_id}:comment:{msg_id}",
        channel_id=channel_id,
        date=date or datetime(2026, 1, 15, 11, 0, 0, tzinfo=UTC),
        text=text,
        language=language,
        parent_message_id=parent_id,
        thread_id=thread_id or parent_id,
        raw_payload=raw_payload,
    )


# ============================================================================
# TestGroupMessages — pure helper
# ============================================================================


class TestGroupMessages:
    def test_post_with_no_comments(self):
        post = _raw_post("1")
        posts, grouped, orphans = _group_messages([post])

        assert posts == [post]
        assert grouped == {}
        assert orphans == []

    def test_multiple_comments_under_one_post_ordered_by_date(self):
        post = _raw_post("1", date=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC))
        c_late = _raw_comment("20", "1", date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC))
        c_early = _raw_comment("21", "1", date=datetime(2026, 1, 15, 11, 0, 0, tzinfo=UTC))

        posts, grouped, orphans = _group_messages([post, c_late, c_early])

        assert posts == [post]
        assert list(grouped.keys()) == ["1"]
        assert [c.id for c in grouped["1"]] == ["21", "20"]
        assert orphans == []

    def test_orphan_comments_collected_separately(self):
        post = _raw_post("1")
        orphan = _raw_comment("99", "NONEXISTENT")

        posts, grouped, orphans = _group_messages([post, orphan])

        assert posts == [post]
        assert grouped == {}
        assert orphans == [orphan]

    def test_orphan_comment_without_parent_id_also_classified_as_orphan(self):
        orphan = _raw_comment("77", None)
        posts, grouped, orphans = _group_messages([orphan])

        assert posts == []
        assert grouped == {}
        assert orphans == [orphan]

    def test_multiple_posts_sorted_by_date(self):
        p_late = _raw_post("1", date=datetime(2026, 1, 16, 10, 0, 0, tzinfo=UTC))
        p_early = _raw_post("2", date=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC))

        posts, _grouped, _orphans = _group_messages([p_late, p_early])

        assert [p.id for p in posts] == ["2", "1"]


# ============================================================================
# TestRawExportWriter — pure writer to tmp_path
# ============================================================================


class TestRawExportWriter:
    def test_json_envelope_schema_version_present(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        export_raw_channel_json(
            messages=[],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
        )
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert SCHEMA_VERSION == "raw_channel_export.v1"

    def test_json_envelope_fields(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        from_dt = datetime(2026, 1, 1, tzinfo=UTC)
        to_dt = datetime(2026, 1, 31, tzinfo=UTC)
        stats = export_raw_channel_json(
            messages=[_raw_post("1"), _raw_comment("2", "1")],
            channel_id="ch1",
            channel_username="my_channel",
            from_date=from_dt,
            to_date=to_dt,
            output_path=out,
        )
        data = json.loads(out.read_text(encoding="utf-8"))

        assert data["channel_id"] == "ch1"
        assert data["channel_username"] == "my_channel"
        assert "exported_at" in data
        assert data["filters"] == {
            "from_date": from_dt.isoformat(),
            "to_date": to_dt.isoformat(),
        }
        assert data["messages_count"] == 1
        assert data["comments_count"] == 1
        assert data["orphan_comments_count"] == 0
        assert isinstance(data["messages"], list)
        assert isinstance(data["orphan_comments"], list)

        assert stats == {"posts": 1, "comments": 1, "orphan_comments": 0}

    def test_post_with_comments_grouped_by_parent_message_id(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        post = _raw_post("100")
        c1 = _raw_comment("101", "100", date=datetime(2026, 1, 15, 11, 0, 0, tzinfo=UTC))
        c2 = _raw_comment("102", "100", date=datetime(2026, 1, 15, 11, 30, 0, tzinfo=UTC))

        export_raw_channel_json(
            messages=[c2, c1, post],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
        )

        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["messages"]) == 1
        post_payload = data["messages"][0]
        assert post_payload["id"] == "100"
        assert [c["id"] for c in post_payload["comments"]] == ["101", "102"]

    def test_orphan_comments_bucket_when_parent_out_of_range(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        orphan = _raw_comment("77", "999")  # parent 999 not in messages list

        export_raw_channel_json(
            messages=[orphan],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
        )

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["messages_count"] == 0
        assert data["comments_count"] == 0
        assert data["orphan_comments_count"] == 1
        assert data["orphan_comments"][0]["id"] == "77"

    def test_ndjson_one_message_per_line_posts_first_then_comments(self, tmp_path: Path):
        out = tmp_path / "raw.ndjson"
        p1 = _raw_post("1", date=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC))
        p2 = _raw_post("2", date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC))
        c = _raw_comment("3", "1", date=datetime(2026, 1, 15, 11, 0, 0, tzinfo=UTC))

        stats = export_raw_channel_ndjson(messages=[c, p2, p1], output_path=out)

        assert stats == {"posts": 2, "comments": 1, "orphan_comments": 0}

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3

        parsed = [json.loads(ln) for ln in lines]
        assert [p["id"] for p in parsed] == ["1", "2", "3"]
        assert parsed[0]["message_type"] == "post"
        assert parsed[-1]["message_type"] == "comment"

        # Every line is valid JSON (no stray newlines inside records)
        for ln in lines:
            assert json.loads(ln) is not None

    def test_pretty_flag_produces_indented_json(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        export_raw_channel_json(
            messages=[_raw_post("1")],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
            pretty=True,
        )
        content = out.read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content

    def test_compact_json_no_indent(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        export_raw_channel_json(
            messages=[_raw_post("1")],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
            pretty=False,
        )
        content = out.read_text(encoding="utf-8")
        # Compact JSON must still parse and must not contain the pretty-print indent
        assert json.loads(content)
        assert "\n  " not in content

    def test_raw_payload_excluded_by_default_in_json(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        p = _raw_post("1", raw_payload={"secret": "telethon", "views": 100})
        c = _raw_comment("2", "1", raw_payload={"secret": "file_ref", "edit": None})

        export_raw_channel_json(
            messages=[p, c],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
        )
        data = json.loads(out.read_text(encoding="utf-8"))

        # Deep assertion across every serialized message in the envelope
        for msg in data["messages"]:
            assert "raw_payload" not in msg, msg
            for cm in msg.get("comments", []):
                assert "raw_payload" not in cm, cm
        for msg in data.get("orphan_comments", []):
            assert "raw_payload" not in msg, msg

    def test_raw_payload_excluded_by_default_in_ndjson(self, tmp_path: Path):
        out = tmp_path / "raw.ndjson"
        p = _raw_post("1", raw_payload={"secret": "telethon"})
        c = _raw_comment("2", "1", raw_payload={"secret": "oof"})

        export_raw_channel_ndjson(messages=[p, c], output_path=out)

        for line in out.read_text(encoding="utf-8").splitlines():
            parsed = json.loads(line)
            assert "raw_payload" not in parsed, parsed

    def test_empty_messages_writes_valid_envelope(self, tmp_path: Path):
        out = tmp_path / "raw.json"
        stats = export_raw_channel_json(
            messages=[],
            channel_id="ch1",
            channel_username=None,
            from_date=None,
            to_date=None,
            output_path=out,
        )
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["messages"] == []
        assert data["orphan_comments"] == []
        assert data["messages_count"] == 0
        assert data["comments_count"] == 0
        assert data["orphan_comments_count"] == 0
        assert stats == {"posts": 0, "comments": 0, "orphan_comments": 0}

    def test_message_payload_excludes_raw_payload(self):
        msg = _raw_post("1", raw_payload={"x": "y"})
        payload = _message_payload(msg)
        assert "raw_payload" not in payload
        assert payload["id"] == "1"
        assert payload["text"] == "post body"


# ============================================================================
# TestExportServiceRawMocked — run_export level=raw with mocked repos
# ============================================================================


class TestExportServiceRawMocked:
    """Tests ``run_export(level=RAW)`` branching via AsyncMock repos."""

    async def test_run_export_level_raw_requires_channel_id(self, tmp_path: Path):
        from tg_parser.services.export_service import run_export

        with pytest.raises(ValueError, match="level='raw' requires channel_id"):
            await run_export(
                output_dir=str(tmp_path),
                level=ExportLevel.RAW,
                raw_repo=AsyncMock(),
                processed_repo=AsyncMock(),
                topic_card_repo=AsyncMock(),
                topic_bundle_repo=AsyncMock(),
                ingestion_repo=AsyncMock(),
            )

    async def test_run_export_level_raw_writes_json(self, tmp_path: Path):
        from tg_parser.services.export_service import run_export

        raw_repo = AsyncMock()
        raw_repo.list_by_channel.return_value = [
            _raw_post("1"),
            _raw_comment("2", "1"),
        ]
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {"ch1": "my_channel"}

        stats = await run_export(
            output_dir=str(tmp_path),
            channel_id="ch1",
            level=ExportLevel.RAW,
            format=ExportFormat.JSON,
            raw_repo=raw_repo,
            ingestion_repo=ingestion_repo,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
        )

        assert stats == {
            "raw_posts_count": 1,
            "raw_comments_count": 1,
            "raw_orphan_comments_count": 0,
            "channels_count": 1,
        }

        out_file = tmp_path / "raw_messages.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["channel_id"] == "ch1"
        assert data["channel_username"] == "my_channel"

    async def test_run_export_level_raw_ndjson_writes_line_per_message(self, tmp_path: Path):
        from tg_parser.services.export_service import run_export

        raw_repo = AsyncMock()
        raw_repo.list_by_channel.return_value = [
            _raw_post("1"),
            _raw_post("2"),
            _raw_comment("3", "1"),
        ]
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {}

        stats = await run_export(
            output_dir=str(tmp_path),
            channel_id="ch1",
            level=ExportLevel.RAW,
            format=ExportFormat.NDJSON,
            raw_repo=raw_repo,
            ingestion_repo=ingestion_repo,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
        )

        out_file = tmp_path / "raw_messages.ndjson"
        assert out_file.exists()
        lines = out_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        # All lines must be valid JSON and must not contain raw_payload
        for line in lines:
            parsed = json.loads(line)
            assert "raw_payload" not in parsed

        assert stats["raw_posts_count"] == 2
        assert stats["raw_comments_count"] == 1
        assert stats["raw_orphan_comments_count"] == 0

    async def test_run_export_level_raw_respects_date_filter(self, tmp_path: Path):
        from tg_parser.services.export_service import run_export

        raw_repo = AsyncMock()
        raw_repo.list_by_channel.return_value = []
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {}

        from_dt = datetime(2026, 1, 1, tzinfo=UTC)
        to_dt = datetime(2026, 1, 31, tzinfo=UTC)

        await run_export(
            output_dir=str(tmp_path),
            channel_id="ch1",
            level=ExportLevel.RAW,
            format=ExportFormat.JSON,
            from_date=from_dt,
            to_date=to_dt,
            raw_repo=raw_repo,
            ingestion_repo=ingestion_repo,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
        )

        raw_repo.list_by_channel.assert_awaited_once_with(
            channel_id="ch1",
            from_date=from_dt,
            to_date=to_dt,
        )

    async def test_run_export_level_raw_channel_without_messages_returns_empty_envelope(
        self, tmp_path: Path
    ):
        from tg_parser.services.export_service import run_export

        raw_repo = AsyncMock()
        raw_repo.list_by_channel.return_value = []
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {}

        stats = await run_export(
            output_dir=str(tmp_path),
            channel_id="unknown_channel",
            level=ExportLevel.RAW,
            format=ExportFormat.JSON,
            raw_repo=raw_repo,
            ingestion_repo=ingestion_repo,
            processed_repo=AsyncMock(),
            topic_card_repo=AsyncMock(),
            topic_bundle_repo=AsyncMock(),
        )

        out_file = tmp_path / "raw_messages.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["messages"] == []
        assert data["channel_id"] == "unknown_channel"

        assert stats == {
            "raw_posts_count": 0,
            "raw_comments_count": 0,
            "raw_orphan_comments_count": 0,
            "channels_count": 0,
        }


# ============================================================================
# TestExportServiceBackwardCompat — ensure level=FULL default matches pre-F2
# ============================================================================


class TestExportServiceBackwardCompat:
    """Backward-compat: callers that don't pass ``level=`` must keep working."""

    async def test_run_export_default_call_signature_still_works(self, tmp_path: Path):
        from tg_parser.services.export_service import run_export

        processed_repo = AsyncMock()
        processed_repo.list_all.return_value = []
        processed_repo.list_by_channel.return_value = []

        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {}

        result = await run_export(
            output_dir=str(tmp_path),
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            ingestion_repo=ingestion_repo,
            raw_repo=AsyncMock(),
        )

        assert result["kb_entries_count"] == 0
        assert result["topics_count"] == 0
        assert result["channels_count"] == 0

    async def test_run_export_default_level_is_full(self, tmp_path: Path):
        """``run_export`` without ``level=`` must equal ``level=FULL`` behaviour."""
        from tg_parser.services.export_service import run_export

        processed_repo = AsyncMock()
        processed_repo.list_all.return_value = []
        processed_repo.list_by_channel.return_value = []
        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = []
        topic_bundle_repo = AsyncMock()
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {}

        out_default = tmp_path / "default"
        out_full = tmp_path / "full"

        stats_default = await run_export(
            output_dir=str(out_default),
            channel_id="ch1",
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            ingestion_repo=ingestion_repo,
            raw_repo=AsyncMock(),
        )
        stats_full = await run_export(
            output_dir=str(out_full),
            channel_id="ch1",
            level=ExportLevel.FULL,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            ingestion_repo=ingestion_repo,
            raw_repo=AsyncMock(),
        )

        assert stats_default == stats_full
        # No raw files leaked into FULL path
        assert not (out_default / "raw_messages.json").exists()
        assert not (out_default / "raw_messages.ndjson").exists()

    async def test_run_export_level_processed_skips_topics(self, tmp_path: Path):
        """``level=PROCESSED`` must NOT write ``topics.json`` even when cards exist."""
        from tg_parser.domain.ids import make_processed_document_id
        from tg_parser.domain.models import (
            Anchor,
            MessageType,
            ProcessedDocument,
            TopicCard,
            TopicType,
        )
        from tg_parser.services.export_service import run_export

        now = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        source_ref = "tg:ch1:post:1"
        doc = ProcessedDocument(
            id=make_processed_document_id(source_ref),
            source_ref=source_ref,
            channel_id="ch1",
            source_message_id="1",
            processed_at=now,
            text_clean="processed body",
            summary="Summary",
            topics=["topic_a"],
            entities=[],
            metadata={
                "pipeline_version": "test",
                "model_id": "test",
                "prompt_id": "test",
            },
        )
        topic_card = TopicCard(
            id="topic:tg:ch1:post:1",
            title="T",
            summary="S",
            scope_in=["x"],
            scope_out=["y"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch1",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref=source_ref,
                    score=1.0,
                )
            ],
            sources=["ch1"],
            updated_at=now,
        )

        processed_repo = AsyncMock()
        processed_repo.list_by_channel.return_value = [doc]
        processed_repo.list_all.return_value = [doc]
        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = [topic_card]
        topic_bundle_repo = AsyncMock()
        topic_bundle_repo.get_by_topic_id.return_value = None
        ingestion_repo = AsyncMock()
        ingestion_repo.get_channel_usernames.return_value = {"ch1": "chan"}

        # level=PROCESSED — must NOT produce topics.json
        await run_export(
            output_dir=str(tmp_path / "processed"),
            channel_id="ch1",
            level=ExportLevel.PROCESSED,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            ingestion_repo=ingestion_repo,
            raw_repo=AsyncMock(),
        )
        assert (tmp_path / "processed" / "kb_entries.ndjson").exists()
        assert not (tmp_path / "processed" / "topics.json").exists()

        # level=FULL — must produce topics.json (legacy behaviour)
        await run_export(
            output_dir=str(tmp_path / "full"),
            channel_id="ch1",
            level=ExportLevel.FULL,
            processed_repo=processed_repo,
            topic_card_repo=topic_card_repo,
            topic_bundle_repo=topic_bundle_repo,
            ingestion_repo=ingestion_repo,
            raw_repo=AsyncMock(),
        )
        assert (tmp_path / "full" / "kb_entries.ndjson").exists()
        assert (tmp_path / "full" / "topics.json").exists()


# ============================================================================
# TestExportServiceRawPostgres — integration with real Postgres (opt-in)
# ============================================================================


@pytest.fixture
async def postgres_test_db():
    """Integration Postgres DB: init schemas + clear tables."""
    if not os.environ.get("TEST_POSTGRES"):
        pytest.skip("Postgres integration disabled (set TEST_POSTGRES=1)")

    from sqlalchemy import text

    from tg_parser.config.settings import Settings
    from tg_parser.storage.sqlalchemy import (
        Database,
        init_ingestion_state_schema,
        init_processing_storage_schema,
        init_raw_storage_schema,
    )

    Database.reset_instance()
    s = Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=os.environ.get("TEST_DB_NAME", "tg_parser_test"),
        db_user=os.environ.get("DB_USER", "tg_parser_user"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_pool_size=2,
        db_max_overflow=3,
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
        openai_api_key="sk-test-key",
    )
    db = Database.get_instance(s)
    await db.init()

    await init_ingestion_state_schema(db.ingestion_state_engine)
    await init_raw_storage_schema(db.raw_storage_engine)
    await init_processing_storage_schema(db.processing_storage_engine)

    async with db.ingestion_state_engine.begin() as conn:
        await conn.execute(text("DELETE FROM source_attempts"))
        await conn.execute(text("DELETE FROM sources"))
    async with db.raw_storage_engine.begin() as conn:
        await conn.execute(text("DELETE FROM raw_conflicts"))
        await conn.execute(text("DELETE FROM raw_messages"))
    async with db.processing_storage_engine.begin() as conn:
        await conn.execute(text("DELETE FROM topic_links"))
        await conn.execute(text("DELETE FROM handoff_history"))
        await conn.execute(text("DELETE FROM task_history"))
        await conn.execute(text("DELETE FROM agent_stats"))
        await conn.execute(text("DELETE FROM agent_states"))
        await conn.execute(text("DELETE FROM topic_bundles"))
        await conn.execute(text("DELETE FROM topic_cards"))
        await conn.execute(text("DELETE FROM processing_failures"))
        await conn.execute(text("DELETE FROM processed_documents"))
        await conn.execute(text("DELETE FROM api_jobs"))

    try:
        yield db
    finally:
        await db.close()
        Database.reset_instance()


class TestExportServiceRawPostgres:
    """End-to-end ``run_export(level=raw)`` with real Postgres."""

    @pytest.mark.asyncio
    async def test_run_export_level_raw_end_to_end(self, postgres_test_db, tmp_path: Path):
        from tg_parser.services.export_service import run_export
        from tg_parser.storage.sqlalchemy import (
            SAIngestionStateRepo,
            SARawMessageRepo,
        )

        channel_id = "f2_test_channel"

        # Seed raw messages: 2 posts, 1 comment
        async with postgres_test_db.raw_storage_session() as session:
            raw_repo = SARawMessageRepo(session)
            await raw_repo.upsert(
                _raw_post(
                    "100",
                    channel_id=channel_id,
                    date=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
                    text="First post",
                )
            )
            await raw_repo.upsert(
                _raw_post(
                    "101",
                    channel_id=channel_id,
                    date=datetime(2026, 1, 16, 10, 0, 0, tzinfo=UTC),
                    text="Second post",
                )
            )
            await raw_repo.upsert(
                _raw_comment(
                    "102",
                    "100",
                    channel_id=channel_id,
                    date=datetime(2026, 1, 15, 11, 0, 0, tzinfo=UTC),
                    text="Comment on first",
                )
            )

        # Seed source for channel_username resolution
        async with postgres_test_db.ingestion_state_session() as session:
            from tg_parser.storage.ports import Source

            state_repo = SAIngestionStateRepo(session)
            await state_repo.upsert_source(
                Source(
                    source_id="src_f2",
                    channel_id=channel_id,
                    status="active",
                    include_comments=True,
                    channel_username="f2_channel",
                )
            )

        stats = await run_export(
            output_dir=str(tmp_path),
            channel_id=channel_id,
            level=ExportLevel.RAW,
            format=ExportFormat.JSON,
        )

        assert stats["raw_posts_count"] == 2
        assert stats["raw_comments_count"] == 1
        assert stats["raw_orphan_comments_count"] == 0
        assert stats["channels_count"] == 1

        out_file = tmp_path / "raw_messages.json"
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["channel_id"] == channel_id
        assert data["channel_username"] == "f2_channel"
        assert data["messages_count"] == 2
        assert data["comments_count"] == 1

        # raw_payload invariant end-to-end
        for msg in data["messages"]:
            assert "raw_payload" not in msg
            for cm in msg.get("comments", []):
                assert "raw_payload" not in cm


# ============================================================================
# TestCLIExportLevel
# ============================================================================


class TestCLIExportLevel:
    def test_cli_level_raw_requires_channel(self):
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            ["export", "--level", "raw", "--out", "/tmp/f2_cli_test"],
        )
        assert result.exit_code != 0
        assert "--level=raw" in result.output or "--level=raw" in (result.stderr or "")

    def test_cli_invalid_level_rejected(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            ["export", "--level", "nonsense", "--out", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "level" in result.output.lower() or "level" in (result.stderr or "").lower()

    def test_cli_invalid_format_rejected(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            [
                "export",
                "--level",
                "raw",
                "--channel",
                "ch1",
                "--format",
                "yaml",
                "--out",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert "format" in result.output.lower() or "format" in (result.stderr or "").lower()

    def test_cli_export_help_mentions_level_and_format(self):
        import re

        runner = CliRunner()
        result = runner.invoke(cli_app, ["export", "--help"])
        assert result.exit_code == 0
        # Strip ANSI escape sequences and collapse whitespace so the assertion
        # is robust against Rich/Typer help rendering on CI (color + wrapping).
        ansi_re = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        plain = ansi_re.sub("", result.output)
        plain = re.sub(r"\s+", " ", plain)
        assert "--level" in plain
        assert "--format" in plain


# ============================================================================
# TestAPIExportLevel
# ============================================================================


@pytest.fixture
def api_app():
    return create_app()


@pytest.fixture
async def api_client(api_app):
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestAPIExportLevel:
    @pytest.mark.asyncio
    async def test_post_export_level_raw_creates_job(self, api_client):
        resp = await api_client.post(
            "/api/v1/export",
            json={
                "channel_id": "ch1",
                "level": "raw",
                "format": "json",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        assert data["level"] == "raw"
        assert data["format"] == "json"
        assert "job_id" in data

    @pytest.mark.asyncio
    async def test_post_export_level_raw_without_channel_returns_400(self, api_client):
        resp = await api_client.post(
            "/api/v1/export",
            json={"level": "raw", "format": "json"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "raw" in str(body).lower()

    @pytest.mark.asyncio
    async def test_post_export_without_level_defaults_to_full(self, api_client):
        resp = await api_client.post("/api/v1/export", json={"format": "ndjson"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "full"

    @pytest.mark.asyncio
    async def test_get_status_includes_level(self, api_client):
        import uuid

        from tg_parser.api.job_store import ensure_job_store_initialized
        from tg_parser.storage.ports import Job, JobStatus, JobType

        job_store = await ensure_job_store_initialized()
        job_id = f"test-raw-{uuid.uuid4()}"
        pending_job = Job(
            job_id=job_id,
            job_type=JobType.EXPORT,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            channel_id="ch1",
            export_format="json",
            progress={"level": "raw"},
        )
        await job_store.create_job(pending_job)

        resp = await api_client.get(f"/api/v1/export/status/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "raw"
        assert data["format"] == "json"

    @pytest.mark.asyncio
    async def test_download_raw_ndjson_has_correct_media_type_and_filename(
        self, api_client, tmp_path: Path
    ):
        import uuid

        from tg_parser.api.job_store import ensure_job_store_initialized
        from tg_parser.storage.ports import Job, JobStatus, JobType

        # Simulate a completed raw/ndjson job pointing at a real file
        file_path = tmp_path / "raw_messages.ndjson"
        file_path.write_text(
            json.dumps({"id": "1", "message_type": "post"}) + "\n",
            encoding="utf-8",
        )

        job_store = await ensure_job_store_initialized()
        job_id = f"test-raw-complete-{uuid.uuid4()}"
        completed_job = Job(
            job_id=job_id,
            job_type=JobType.EXPORT,
            status=JobStatus.COMPLETED,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            channel_id="ch1",
            export_format="ndjson",
            file_path=str(file_path),
            download_url=f"/api/v1/export/download/{job_id}",
            progress={"level": "raw"},
            result={"format": "ndjson", "level": "raw", "file_size": file_path.stat().st_size},
        )
        await job_store.create_job(completed_job)

        resp = await api_client.get(f"/api/v1/export/download/{job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        # FastAPI FileResponse sets filename through content-disposition
        cd = resp.headers.get("content-disposition", "")
        assert "raw_messages.ndjson" in cd

    @pytest.mark.asyncio
    async def test_download_raw_json_has_correct_media_type_and_filename(
        self, api_client, tmp_path: Path
    ):
        import uuid

        from tg_parser.api.job_store import ensure_job_store_initialized
        from tg_parser.storage.ports import Job, JobStatus, JobType

        file_path = tmp_path / "raw_messages.json"
        file_path.write_text(json.dumps({"messages": []}), encoding="utf-8")

        job_store = await ensure_job_store_initialized()
        job_id = f"test-raw-json-{uuid.uuid4()}"
        completed_job = Job(
            job_id=job_id,
            job_type=JobType.EXPORT,
            status=JobStatus.COMPLETED,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            channel_id="ch1",
            export_format="json",
            file_path=str(file_path),
            download_url=f"/api/v1/export/download/{job_id}",
            progress={"level": "raw"},
            result={"format": "json", "level": "raw", "file_size": file_path.stat().st_size},
        )
        await job_store.create_job(completed_job)

        resp = await api_client.get(f"/api/v1/export/download/{job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        cd = resp.headers.get("content-disposition", "")
        assert "raw_messages.json" in cd


# ============================================================================
# TestMCPExportChannel
# ============================================================================


class _StubMCPCtx:
    """Minimal stand-in for ``mcp.server.fastmcp.Context`` used in MCP tools."""

    def __init__(self, client_id: str | None = None) -> None:
        self.client_id = client_id


class TestMCPExportChannel:
    @pytest.mark.asyncio
    async def test_mcp_export_channel_invalid_level_raises(self):
        from tg_parser.mcp_server import export_channel

        with pytest.raises(ValueError, match="invalid level"):
            await export_channel(channel_id="ch1", level="bogus", ctx=None)

    @pytest.mark.asyncio
    async def test_mcp_export_channel_invalid_format_raises(self):
        from tg_parser.mcp_server import export_channel

        with pytest.raises(ValueError, match="invalid format"):
            await export_channel(channel_id="ch1", level="raw", format="yaml", ctx=None)

    @pytest.mark.asyncio
    async def test_mcp_export_channel_raw_requires_channel_id(self):
        from tg_parser.mcp_server import export_channel

        with pytest.raises(ValueError, match="channel_id"):
            await export_channel(channel_id="", level="raw", ctx=None)

    @pytest.mark.asyncio
    async def test_mcp_export_channel_submits_job(self, monkeypatch):
        import tg_parser.mcp_server as mcp_mod
        from tg_parser.api.schemas import ExportLevel
        from tg_parser.auth.models import CurrentUser

        captured: dict[str, object] = {}

        async def fake_assert(_user, _channel_id):
            return None

        async def fake_resolve(_client_id):
            return CurrentUser(
                id="u1",
                name="tester",
                role="user",
                allowed_channel_ids=None,
                max_channels=20,
            )

        class FakeJobStore:
            async def create_job(self, job):
                captured["job"] = job

        async def fake_ensure():
            return FakeJobStore()

        async def fake_run_export_job(job_id, request):
            captured["called_job_id"] = job_id
            captured["called_level"] = request.level

        monkeypatch.setattr(mcp_mod, "resolve_mcp_user", fake_resolve)
        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.api.job_store.ensure_job_store_initialized", fake_ensure)
        monkeypatch.setattr("tg_parser.api.routes.export._run_export_job", fake_run_export_job)

        result = await mcp_mod.export_channel(
            channel_id="ch1", level="raw", format="json", ctx=None
        )
        assert result.status == "pending"
        assert result.channel_id == "ch1"
        assert result.level == ExportLevel.RAW.value
        assert result.format == "json"
        assert result.job_id
        assert "Poll" in result.message or "poll" in result.message.lower()
        assert captured["job"].channel_id == "ch1"
        assert captured["job"].progress == {"level": "raw"}

    @pytest.mark.asyncio
    async def test_mcp_export_channel_ownership_denied(self, monkeypatch):
        import tg_parser.mcp_server as mcp_mod
        from tg_parser.auth.models import CurrentUser
        from tg_parser.auth.ownership import PermissionDenied

        async def fake_resolve(_client_id):
            return CurrentUser(
                id="u-non-owner",
                name="other",
                role="user",
                allowed_channel_ids=["other_ch"],
                max_channels=10,
            )

        async def fake_assert(_user, channel_id):
            raise PermissionDenied(f"No access to {channel_id}")

        monkeypatch.setattr(mcp_mod, "resolve_mcp_user", fake_resolve)
        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)

        result = await mcp_mod.export_channel(
            channel_id="ch1", level="raw", format="json", ctx=None
        )
        assert result.status == "rejected"
        assert "no access" in result.message.lower()
        assert result.job_id == ""

    @pytest.mark.asyncio
    async def test_mcp_export_channel_defaults_to_raw_json(self, monkeypatch):
        import tg_parser.mcp_server as mcp_mod
        from tg_parser.auth.models import CurrentUser

        async def fake_resolve(_client_id):
            return CurrentUser(
                id="u1",
                name="t",
                role="user",
                allowed_channel_ids=None,
                max_channels=20,
            )

        async def fake_assert(_user, _channel_id):
            return None

        class FakeJobStore:
            async def create_job(self, _job):
                return None

        async def fake_ensure():
            return FakeJobStore()

        async def fake_run(_jid, _req):
            return None

        monkeypatch.setattr(mcp_mod, "resolve_mcp_user", fake_resolve)
        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.api.job_store.ensure_job_store_initialized", fake_ensure)
        monkeypatch.setattr("tg_parser.api.routes.export._run_export_job", fake_run)

        result = await mcp_mod.export_channel(channel_id="ch1", ctx=None)
        assert result.level == "raw"
        assert result.format == "json"


# ============================================================================
# TestBotExportChannel (mocked aiogram Bot)
# ============================================================================


class _FakeBot:
    """Aiogram-Bot-like double recording calls made by ``_exec_export_channel``."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.sent_documents: list[dict] = []
        self.deleted_messages: list[dict] = []
        self._next_message_id = 1
        self.send_document_should_raise: Exception | None = None

    async def send_message(self, *, chat_id, text, parse_mode=None):  # noqa: ANN001
        mid = self._next_message_id
        self._next_message_id += 1
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "id": mid}
        )

        class _Msg:
            def __init__(self, message_id):
                self.message_id = message_id

        return _Msg(mid)

    async def send_document(self, *, chat_id, document, caption=None):  # noqa: ANN001
        if self.send_document_should_raise is not None:
            raise self.send_document_should_raise
        self.sent_documents.append({"chat_id": chat_id, "document": document, "caption": caption})

    async def delete_message(self, *, chat_id, message_id):  # noqa: ANN001
        self.deleted_messages.append({"chat_id": chat_id, "message_id": message_id})


class TestBotExportChannel:
    @pytest.fixture
    def fake_bot(self):
        return _FakeBot()

    @pytest.fixture
    def test_user(self):
        from tg_parser.auth.models import CurrentUser

        return CurrentUser(
            id="u1",
            name="tester",
            role="user",
            allowed_channel_ids=None,
            max_channels=20,
        )

    @pytest.mark.asyncio
    async def test_bot_export_channel_invalid_level(self, fake_bot, test_user):
        from tg_parser.bot.tools import execute_tool

        result = await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "bogus"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=42,
        )
        assert "error" in result
        assert "invalid level" in result["error"]
        assert fake_bot.sent_documents == []

    @pytest.mark.asyncio
    async def test_bot_export_channel_invalid_format(self, fake_bot, test_user):
        from tg_parser.bot.tools import execute_tool

        result = await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "raw", "format": "yaml"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=42,
        )
        assert "error" in result
        assert "invalid format" in result["error"]

    @pytest.mark.asyncio
    async def test_bot_export_channel_raw_requires_channel_id(self, fake_bot, test_user):
        from tg_parser.bot.tools import execute_tool

        result = await execute_tool(
            "export_channel",
            {"channel_id": "", "level": "raw"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=42,
        )
        assert "error" in result
        assert "channel_id" in result["error"]

    @pytest.mark.asyncio
    async def test_bot_export_channel_ownership_enforced(self, monkeypatch, fake_bot, test_user):
        from tg_parser.auth.ownership import PermissionDenied
        from tg_parser.bot.tools import execute_tool

        async def fake_assert(_user, channel_id):
            raise PermissionDenied(f"No access to {channel_id}")

        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)

        result = await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "raw"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=42,
        )
        assert "error" in result
        assert "no access" in result["error"].lower()
        assert fake_bot.sent_documents == []

    @pytest.mark.asyncio
    async def test_bot_export_channel_small_file_sent_as_document(
        self, monkeypatch, tmp_path, fake_bot, test_user
    ):
        from tg_parser.bot.tools import execute_tool
        from tg_parser.config import settings

        async def fake_assert(_user, _channel_id):
            return None

        async def fake_run_export(*, output_dir, **_kwargs):
            file_path = Path(output_dir) / "raw_messages.json"
            file_path.write_text(json.dumps({"messages": []}), encoding="utf-8")
            return {
                "raw_posts_count": 0,
                "raw_comments_count": 0,
                "raw_orphan_comments_count": 0,
                "channels_count": 1,
            }

        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.services.export_service.run_export", fake_run_export)
        monkeypatch.setattr(settings, "output_dir", str(tmp_path))

        result = await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "raw", "format": "json"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=42,
        )
        assert result.get("sent") is True
        assert result["channel_id"] == "ch1"
        assert result["file_name"] == "raw_messages.json"
        assert len(fake_bot.sent_documents) == 1
        sent = fake_bot.sent_documents[0]
        assert sent["chat_id"] == 42
        # Progress message sent and then deleted
        assert len(fake_bot.sent_messages) == 1
        assert "Готовлю экспорт" in fake_bot.sent_messages[0]["text"]
        assert len(fake_bot.deleted_messages) == 1

    @pytest.mark.asyncio
    async def test_bot_export_channel_large_file_returns_url_no_send_document(
        self, monkeypatch, tmp_path, fake_bot, test_user
    ):
        from tg_parser.bot.tools import (
            TG_BOT_DOCUMENT_LIMIT_BYTES,
            execute_tool,
        )
        from tg_parser.config import settings

        async def fake_assert(_user, _channel_id):
            return None

        async def fake_run_export(*, output_dir, **_kwargs):
            file_path = Path(output_dir) / "raw_messages.json"
            file_path.write_text("x", encoding="utf-8")
            return {
                "raw_posts_count": 1,
                "raw_comments_count": 0,
                "raw_orphan_comments_count": 0,
                "channels_count": 1,
            }

        original_stat = Path.stat
        oversize = TG_BOT_DOCUMENT_LIMIT_BYTES + 1

        def fake_stat(self, *args, **kwargs):
            if self.name == "raw_messages.json":

                class _S:
                    st_size = oversize

                return _S()
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.services.export_service.run_export", fake_run_export)
        monkeypatch.setattr(settings, "output_dir", str(tmp_path))
        monkeypatch.setattr(Path, "stat", fake_stat)

        result = await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "raw", "format": "json"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=42,
        )
        assert result.get("sent") is False
        assert result["reason"] == "file_too_large"
        assert result["file_size"] == oversize
        assert "50" in result["message"] or "лимит" in result["message"]
        assert fake_bot.sent_documents == []

    @pytest.mark.asyncio
    async def test_bot_export_channel_progress_message_sent_and_deleted(
        self, monkeypatch, tmp_path, fake_bot, test_user
    ):
        from tg_parser.bot.tools import execute_tool
        from tg_parser.config import settings

        async def fake_assert(_user, _channel_id):
            return None

        async def fake_run_export(*, output_dir, **_kwargs):
            file_path = Path(output_dir) / "raw_messages.json"
            file_path.write_text(json.dumps({"messages": []}), encoding="utf-8")
            return {
                "raw_posts_count": 0,
                "raw_comments_count": 0,
                "raw_orphan_comments_count": 0,
                "channels_count": 1,
            }

        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.services.export_service.run_export", fake_run_export)
        monkeypatch.setattr(settings, "output_dir", str(tmp_path))

        await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "raw", "format": "json"},
            current_user=test_user,
            bot=fake_bot,
            chat_id=99,
        )
        assert len(fake_bot.sent_messages) == 1
        assert fake_bot.sent_messages[0]["chat_id"] == 99
        assert len(fake_bot.deleted_messages) == 1
        assert fake_bot.deleted_messages[0]["chat_id"] == 99

    @pytest.mark.asyncio
    async def test_bot_export_channel_no_bot_context_returns_summary(
        self, monkeypatch, tmp_path, test_user
    ):
        from tg_parser.bot.tools import execute_tool
        from tg_parser.config import settings

        async def fake_assert(_user, _channel_id):
            return None

        async def fake_run_export(*, output_dir, **_kwargs):
            file_path = Path(output_dir) / "raw_messages.json"
            file_path.write_text(json.dumps({"messages": []}), encoding="utf-8")
            return {
                "raw_posts_count": 0,
                "raw_comments_count": 0,
                "raw_orphan_comments_count": 0,
                "channels_count": 1,
            }

        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.services.export_service.run_export", fake_run_export)
        monkeypatch.setattr(settings, "output_dir", str(tmp_path))

        result = await execute_tool(
            "export_channel",
            {"channel_id": "ch1", "level": "raw", "format": "json"},
            current_user=test_user,
        )
        assert result.get("sent") is False
        assert result.get("reason") == "no_bot_context"
        assert "channel_id" in result and result["channel_id"] == "ch1"
