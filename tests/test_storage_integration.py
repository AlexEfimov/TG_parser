"""
Integration тесты для storage layer.

Проверяет:
- TR-8: raw snapshot (идемпотентность)
- TR-10: атомарность курсоров
- TR-18: уникальность по source_ref
- TR-22: upsert processed documents
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tg_parser.domain.ids import make_processed_document_id, make_source_ref
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage, TopicLink
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy import (
    SAIngestionStateRepo,
    SAProcessedDocumentRepo,
    SARawMessageRepo,
    SATopicBundleRepo,
    SATopicCardRepo,
)
from tg_parser.storage.sqlalchemy.topic_link_repo import SATopicLinkRepo

# DI-19 (Sprint A.7): the prior local ``test_db`` fixture override (which
# called ``init_*_schema()`` then ``DELETE FROM`` per table) is gone.  The
# session-scoped alembic upgrade in ``tests/conftest.py`` provides the
# schema; ``conftest.test_db`` ``TRUNCATE``-s user data between tests.


class TestRawMessageRepo:
    """Integration тесты для RawMessageRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_message(self, test_db):
        """Тест создания нового raw сообщения."""
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)

            msg = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14, 10, 0, 0),
                text="Test message",
            )

            created = await repo.upsert(msg)
            assert created is True

    @pytest.mark.asyncio
    async def test_upsert_idempotency_tr8(self, test_db):
        """
        TR-8: raw snapshot не должен перезаписываться.

        При повторном upsert с тем же source_ref должен быть conflict.
        """
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)

            # Первая запись
            msg1 = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14, 10, 0, 0),
                text="Original text",
            )
            created1 = await repo.upsert(msg1)
            assert created1 is True

        # Попытка перезаписать (новая сессия)
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)

            msg2 = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14, 11, 0, 0),  # Другая дата
                text="Modified text",  # Другой текст
            )
            created2 = await repo.upsert(msg2)

            # TR-8: должен быть conflict (не создано)
            assert created2 is False

            # Проверяем, что оригинальные данные сохранились
            retrieved = await repo.get_by_source_ref("tg:ch:post:123")
            assert retrieved is not None
            assert retrieved.text == "Original text"  # Исходный текст
            assert retrieved.date == datetime(2025, 12, 14, 10, 0, 0)  # Исходная дата

    @pytest.mark.asyncio
    async def test_unique_constraint_tr18(self, test_db):
        """TR-18: уникальность по source_ref."""
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)

            msg = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14),
                text="Text",
            )

            created1 = await repo.upsert(msg)
            assert created1 is True

            # Повторный upsert с тем же source_ref
            created2 = await repo.upsert(msg)
            assert created2 is False

    @pytest.mark.asyncio
    async def test_list_by_channel(self, test_db):
        """Тест получения сообщений канала."""
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)

            # Создаём несколько сообщений
            for i in range(3):
                msg = RawTelegramMessage(
                    id=str(i),
                    message_type=MessageType.POST,
                    source_ref=f"tg:ch:post:{i}",
                    channel_id="ch",
                    date=datetime(2025, 12, 14, 10, i, 0),
                    text=f"Message {i}",
                )
                await repo.upsert(msg)

        # Получаем все сообщения канала
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            messages = await repo.list_by_channel("ch")

            assert len(messages) == 3
            # Проверяем сортировку по дате
            assert messages[0].id == "0"
            assert messages[2].id == "2"

    @pytest.mark.asyncio
    async def test_list_unprocessed_skips_processed_docs(self, test_db):
        """BUG-069 / B2: list_unprocessed_by_channel must exclude any raw message
        that already has a processed_documents row (the NOT EXISTS filter)."""
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            for i in range(5):
                await repo.upsert(
                    RawTelegramMessage(
                        id=str(i),
                        message_type=MessageType.POST,
                        source_ref=f"tg:ch:post:{i}",
                        channel_id="ch",
                        date=datetime(2025, 12, 14, 10, i, 0),
                        text=f"Message {i}",
                    )
                )

        # Mark posts 0 and 2 as already processed.
        async with test_db.processing_storage_session() as session:
            proc = SAProcessedDocumentRepo(session)
            for i in (0, 2):
                ref = f"tg:ch:post:{i}"
                await proc.upsert(
                    ProcessedDocument(
                        id=make_processed_document_id(ref),
                        source_ref=ref,
                        source_message_id=str(i),
                        channel_id="ch",
                        processed_at=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
                        text_clean=f"clean {i}",
                    )
                )

        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            unprocessed = await repo.list_unprocessed_by_channel("ch", limit=100)

        refs = [m.source_ref for m in unprocessed]
        assert refs == ["tg:ch:post:1", "tg:ch:post:3", "tg:ch:post:4"]

    @pytest.mark.asyncio
    async def test_list_unprocessed_respects_limit_and_ordering(self, test_db):
        """BUG-069: the LIMIT bounds the window and ordering is (date ASC,
        source_ref ASC) so paging is deterministic."""
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            # Two messages share a date to exercise the source_ref tie-breaker.
            await repo.upsert(
                RawTelegramMessage(
                    id="b",
                    message_type=MessageType.POST,
                    source_ref="tg:ch:post:b",
                    channel_id="ch",
                    date=datetime(2025, 12, 14, 10, 0, 0),
                    text="b",
                )
            )
            await repo.upsert(
                RawTelegramMessage(
                    id="a",
                    message_type=MessageType.POST,
                    source_ref="tg:ch:post:a",
                    channel_id="ch",
                    date=datetime(2025, 12, 14, 10, 0, 0),
                    text="a",
                )
            )
            await repo.upsert(
                RawTelegramMessage(
                    id="c",
                    message_type=MessageType.POST,
                    source_ref="tg:ch:post:c",
                    channel_id="ch",
                    date=datetime(2025, 12, 14, 11, 0, 0),
                    text="c",
                )
            )

        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            window = await repo.list_unprocessed_by_channel("ch", limit=2)

        # Same date -> source_ref tie-break (a before b); LIMIT caps at 2.
        assert [m.source_ref for m in window] == ["tg:ch:post:a", "tg:ch:post:b"]

    @pytest.mark.asyncio
    async def test_list_unprocessed_empty_when_all_processed(self, test_db):
        """BUG-069: when every raw message is processed, the bounded load returns
        an empty list (forward progress / no re-burn)."""
        ref = "tg:ch:post:1"
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            await repo.upsert(
                RawTelegramMessage(
                    id="1",
                    message_type=MessageType.POST,
                    source_ref=ref,
                    channel_id="ch",
                    date=datetime(2025, 12, 14, 10, 0, 0),
                    text="only",
                )
            )

        async with test_db.processing_storage_session() as session:
            proc = SAProcessedDocumentRepo(session)
            await proc.upsert(
                ProcessedDocument(
                    id=make_processed_document_id(ref),
                    source_ref=ref,
                    source_message_id="1",
                    channel_id="ch",
                    processed_at=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
                    text_clean="clean",
                )
            )

        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            unprocessed = await repo.list_unprocessed_by_channel("ch", limit=100)

        assert unprocessed == []

    @pytest.mark.asyncio
    async def test_list_unprocessed_cooldown_prefix_does_not_starve_newer(self, test_db):
        """BUG-069 (Option A) — head-of-line / starvation regression.

        Construct a channel whose OLDEST ``batch`` messages all carry an
        ACTIVE-cooldown ``processing_failures`` row (a poison-pill prefix sized at
        the batch LIMIT) followed by NEWER unprocessed, non-failed messages. The
        original bounded ``NOT EXISTS(processed_documents)`` window would be fully
        consumed by the stuck failing prefix (those refs never get a
        ``processed_documents`` row), starving the newer actionable docs forever.

        With ``failure_cooldown_enabled=True`` the cooldown anti-join must skip
        the prefix and surface the NEWER docs — forward progress is guaranteed.
        With ``failure_cooldown_enabled=False`` the OLD (prefix-included)
        behaviour must be preserved exactly.
        """
        batch = 3
        # Oldest `batch` messages -> poison-pill prefix (active-cooldown failures).
        for i in range(batch):
            await self._seed_raw(test_db, idx=i, hour=i)
        # Newer messages -> unprocessed, never failed (the actionable backlog).
        for i in range(batch, batch + 3):
            await self._seed_raw(test_db, idx=i, hour=i)

        # Record an ACTIVE-cooldown failure for each prefix ref. record_failure
        # stamps last_attempt_at = now(UTC), so each is well within the default
        # 3600s cooldown -> currently skippable.
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        async with test_db.processing_storage_session() as session:
            frepo = SAProcessingFailureRepo(session)
            for i in range(batch):
                await frepo.record_failure(
                    source_ref=f"tg:ch:post:{i}",
                    channel_id="ch",
                    attempts=1,
                    error_class="RuntimeError",  # -> "other" -> default cooldown
                    error_message="boom",
                )

        # Cooldown ON: the failing prefix is skipped, newer docs surface.
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            window = await repo.list_unprocessed_by_channel(
                "ch", limit=batch, failure_cooldown_enabled=True
            )
        refs = [m.source_ref for m in window]
        assert refs == ["tg:ch:post:3", "tg:ch:post:4", "tg:ch:post:5"], (
            "cooldown-active prefix must be skipped so newer docs make progress"
        )

        # Cooldown OFF: legacy behaviour — the oldest (failing) prefix is included
        # and consumes the whole window (the regression this fix prevents).
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            window_off = await repo.list_unprocessed_by_channel(
                "ch", limit=batch, failure_cooldown_enabled=False
            )
        assert [m.source_ref for m in window_off] == [
            "tg:ch:post:0",
            "tg:ch:post:1",
            "tg:ch:post:2",
        ]

    @pytest.mark.asyncio
    async def test_list_unprocessed_cooldown_predicate_matches_should_skip_failed(self, test_db):
        """BUG-069 (Option A): the SQL cooldown predicate must agree with
        ``pipeline._should_skip_failed`` for every representative case (billing,
        parse-in-budget, parse-after-N-attempts, default/other, expired, and the
        future-dated clamp). A ref is excluded by the SQL iff Python says skip.
        """
        from tg_parser.config import settings
        from tg_parser.processing.pipeline import ProcessingPipelineImpl

        now = datetime.now(UTC).replace(microsecond=0)

        def ts(delta_s: int) -> str:
            return (now - timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # (label, error_class, attempts, last_attempt_at_string)
        # Offsets are chosen well away from the TTL boundaries to avoid flakiness.
        cases = [
            (
                "billing_active",
                "AnthropicBillingError",
                1,
                ts(settings.failure_billing_cooldown_s // 2),
            ),
            (
                "billing_expired",
                "AnthropicBillingError",
                1,
                ts(settings.failure_billing_cooldown_s + 600),
            ),
            (
                "parse_in_budget_active",
                "LLMJsonParseError",
                1,
                ts(settings.failure_default_cooldown_s // 2),
            ),
            (
                "parse_in_budget_expired",
                "LLMJsonParseError",
                1,
                ts(settings.failure_default_cooldown_s + 600),
            ),
            (
                "parse_exhausted_active",
                "LLMJsonParseError",
                settings.failure_parse_max_attempts,
                ts(settings.failure_parse_cooldown_s // 2),
            ),
            (
                "parse_exhausted_expired",
                "LLMJsonParseError",
                settings.failure_parse_max_attempts,
                ts(settings.failure_parse_cooldown_s + 600),
            ),
            ("other_active", "TimeoutError", 1, ts(settings.failure_default_cooldown_s // 2)),
            ("other_expired", "TimeoutError", 1, ts(settings.failure_default_cooldown_s + 600)),
            # Future-dated last_attempt_at: age_s < 0 -> Python clamps to "expired"
            # (do not skip); the SQL `last <= now` mirror must agree.
            (
                "future_dated_clamp",
                "TimeoutError",
                1,
                (now + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        ]

        # One unprocessed raw message per case + a matching failure row.
        for idx, (label, _ec, _att, _ts) in enumerate(cases):
            await self._seed_raw(test_db, idx=idx, hour=idx, channel_id="cp", suffix=label)

        async with test_db.processing_storage_session() as session:
            for label, error_class, attempts, last_at in cases:
                await session.execute(
                    text(
                        "INSERT INTO processing_failures "
                        "(source_ref, channel_id, attempts, last_attempt_at, "
                        " error_class, error_message, error_details_json) "
                        "VALUES (:sr, :ch, :att, :la, :ec, :em, NULL)"
                    ),
                    {
                        "sr": f"tg:cp:post:{label}",
                        "ch": "cp",
                        "att": attempts,
                        "la": last_at,
                        "ec": error_class,
                        "em": "x",
                    },
                )
            await session.commit()

        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            returned = await repo.list_unprocessed_by_channel(
                "cp", limit=1000, failure_cooldown_enabled=True, now=now
            )
        returned_refs = {m.source_ref for m in returned}

        for label, error_class, attempts, last_at in cases:
            record = {
                "source_ref": f"tg:cp:post:{label}",
                "channel_id": "cp",
                "attempts": attempts,
                "last_attempt_at": last_at,
                "error_class": error_class,
                "error_message": "x",
            }
            # _should_skip_failed does not touch `self`; call it with a dummy.
            py_skip = ProcessingPipelineImpl._should_skip_failed(
                ProcessingPipelineImpl.__new__(ProcessingPipelineImpl), record, now
            )
            sql_excluded = record["source_ref"] not in returned_refs
            assert py_skip == sql_excluded, (
                f"parity mismatch for {label!r}: python_skip={py_skip} sql_excluded={sql_excluded}"
            )

    @staticmethod
    async def _seed_raw(test_db, *, idx, hour, channel_id="ch", suffix=None):
        """Insert one unprocessed raw message; suffix lets refs be label-keyed."""
        ref = f"tg:{channel_id}:post:{suffix if suffix is not None else idx}"
        async with test_db.raw_storage_session() as session:
            repo = SARawMessageRepo(session)
            await repo.upsert(
                RawTelegramMessage(
                    id=str(idx),
                    message_type=MessageType.POST,
                    source_ref=ref,
                    channel_id=channel_id,
                    date=datetime(2025, 12, 14, hour % 24, idx % 60, 0),
                    text=f"msg {idx}",
                )
            )


class TestProcessedDocumentRepo:
    """Integration тесты для ProcessedDocumentRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_document(self, test_db):
        """Тест создания нового processed document."""
        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)

            source_ref = make_source_ref("ch", "post", "123")
            doc = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
                text_clean="Clean text",
            )

            await repo.upsert(doc)

            # Проверяем, что документ создан
            retrieved = await repo.get_by_source_ref(source_ref)
            assert retrieved is not None
            assert retrieved.text_clean == "Clean text"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_tr22(self, test_db):
        """
        TR-22: одно актуальное состояние на source_ref.

        При повторном upsert должна происходить замена.
        """
        source_ref = make_source_ref("ch", "post", "123")

        # Первая версия
        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)

            doc1 = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
                text_clean="Version 1",
                summary="Summary 1",
            )
            await repo.upsert(doc1)

        # Обновление (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)

            doc2 = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, 13, 0, 0, tzinfo=UTC),  # Новое время
                text_clean="Version 2",  # Новый текст
                summary="Summary 2",
            )
            await repo.upsert(doc2)

            # TR-22: должна быть только одна запись (обновлённая)
            retrieved = await repo.get_by_source_ref(source_ref)
            assert retrieved is not None
            assert retrieved.text_clean == "Version 2"
            assert retrieved.summary == "Summary 2"
            assert retrieved.processed_at == datetime(2025, 12, 14, 13, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_exists_check_tr48(self, test_db):
        """TR-48: проверка существования для инкрементальности."""
        source_ref = make_source_ref("ch", "post", "123")

        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)

            # Изначально не существует
            exists_before = await repo.exists(source_ref)
            assert exists_before is False

            # Создаём документ
            doc = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, tzinfo=UTC),
                text_clean="Text",
            )
            await repo.upsert(doc)

        # Проверяем существование (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)
            exists_after = await repo.exists(source_ref)
            assert exists_after is True

    @pytest.mark.asyncio
    async def test_metadata_json_serialization(self, test_db):
        """Тест сериализации/десериализации metadata."""
        source_ref = make_source_ref("ch", "post", "123")

        metadata = {
            "pipeline_version": "processing:v1.0.0",
            "model_id": "gpt-4",
            "parameters": {"temperature": 0.0},
        }

        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)

            doc = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, tzinfo=UTC),
                text_clean="Text",
                metadata=metadata,
            )
            await repo.upsert(doc)

        # Проверяем десериализацию
        async with test_db.processing_storage_session() as session:
            repo = SAProcessedDocumentRepo(session)
            retrieved = await repo.get_by_source_ref(source_ref)

            assert retrieved is not None
            assert retrieved.metadata == metadata
            assert retrieved.metadata["pipeline_version"] == "processing:v1.0.0"


class TestProcessingFailureRepo:
    """Тесты SAProcessingFailureRepo."""

    @pytest.mark.asyncio
    async def test_record_failure_creates_new_entry(self, test_db):
        """Тест создания новой записи о неудаче."""
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "100")

        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=3,
                error_class="TimeoutError",
                error_message="Request timeout after 30s",
                error_details={"timeout": 30, "retries": 3},
            )

        # Проверяем что запись создана
        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)
            failures = await repo.list_failures()

            assert len(failures) == 1
            assert failures[0]["source_ref"] == source_ref
            assert failures[0]["channel_id"] == "test_ch"
            assert failures[0]["attempts"] == 3
            assert failures[0]["error_class"] == "TimeoutError"
            assert failures[0]["error_message"] == "Request timeout after 30s"
            assert failures[0]["error_details"]["timeout"] == 30

    @pytest.mark.asyncio
    async def test_record_failure_updates_existing(self, test_db):
        """Тест обновления существующей записи о неудаче."""
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "200")

        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            # Первая попытка
            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=1,
                error_class="NetworkError",
                error_message="Connection refused",
            )

            # Вторая попытка (обновление)
            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=2,
                error_class="TimeoutError",
                error_message="Request timeout",
            )

        # Проверяем что только одна запись (обновлённая)
        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)
            failures = await repo.list_failures()

            assert len(failures) == 1
            assert failures[0]["source_ref"] == source_ref
            assert failures[0]["attempts"] == 2
            assert failures[0]["error_class"] == "TimeoutError"

    @pytest.mark.asyncio
    async def test_delete_failure_tr47(self, test_db):
        """TR-47: при успешной обработке запись о неудаче удаляется."""
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "300")

        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            # Записываем неудачу
            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=3,
                error_class="ValueError",
                error_message="Invalid data",
            )

            # Проверяем что есть
            failures_before = await repo.list_failures()
            assert len(failures_before) == 1

            # Удаляем (симулируем успешную обработку)
            await repo.delete_failure(source_ref)

            # Проверяем что удалена
            failures_after = await repo.list_failures()
            assert len(failures_after) == 0

    @pytest.mark.asyncio
    async def test_list_failures_with_channel_filter(self, test_db):
        """Тест фильтрации списка неудач по каналу."""
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            # Создаём неудачи для двух каналов
            await repo.record_failure(
                source_ref=make_source_ref("ch1", "post", "1"),
                channel_id="ch1",
                attempts=1,
                error_class="Error1",
                error_message="Error in ch1",
            )

            await repo.record_failure(
                source_ref=make_source_ref("ch2", "post", "1"),
                channel_id="ch2",
                attempts=1,
                error_class="Error2",
                error_message="Error in ch2",
            )

            await repo.record_failure(
                source_ref=make_source_ref("ch1", "post", "2"),
                channel_id="ch1",
                attempts=1,
                error_class="Error3",
                error_message="Another error in ch1",
            )

        # Проверяем фильтрацию
        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            all_failures = await repo.list_failures()
            assert len(all_failures) == 3

            ch1_failures = await repo.list_failures(channel_id="ch1")
            assert len(ch1_failures) == 2
            assert all(f["channel_id"] == "ch1" for f in ch1_failures)

            ch2_failures = await repo.list_failures(channel_id="ch2")
            assert len(ch2_failures) == 1
            assert ch2_failures[0]["channel_id"] == "ch2"

    @pytest.mark.asyncio
    async def test_list_failures_with_limit(self, test_db):
        """Тест ограничения количества возвращаемых записей."""
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            # Создаём несколько неудач
            for i in range(5):
                await repo.record_failure(
                    source_ref=make_source_ref("test_ch", "post", str(i)),
                    channel_id="test_ch",
                    attempts=1,
                    error_class="TestError",
                    error_message=f"Error {i}",
                )

        # Проверяем лимит
        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            all_failures = await repo.list_failures()
            assert len(all_failures) == 5

            limited_failures = await repo.list_failures(limit=3)
            assert len(limited_failures) == 3

    @pytest.mark.asyncio
    async def test_failure_without_error_details(self, test_db):
        """Тест записи неудачи без error_details."""
        from tg_parser.storage.sqlalchemy import SAProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "400")

        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)

            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=1,
                error_class="SimpleError",
                error_message="Simple error message",
                error_details=None,
            )

        # Проверяем что запись создана без error_details
        async with test_db.processing_storage_session() as session:
            repo = SAProcessingFailureRepo(session)
            failures = await repo.list_failures()

            assert len(failures) == 1
            assert failures[0]["error_details"] is None


class TestTopicCardRepo:
    """Integration тесты для TopicCardRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_topic_card(self, test_db):
        """Тест создания новой topic card."""
        from tg_parser.domain.models import Anchor, TopicCard, TopicType

        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)

            card = TopicCard(
                id="topic:tg:ch:post:123",
                title="Test Topic",
                summary="Test summary",
                scope_in=["test scope in"],
                scope_out=["test scope out"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.9,
                    )
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(card)

            # Проверяем что создана
            retrieved = await repo.get_by_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert retrieved.title == "Test Topic"
            assert retrieved.type == TopicType.SINGLETON
            assert len(retrieved.anchors) == 1
            assert retrieved.anchors[0].score == 0.9

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_topic_card(self, test_db):
        """TR-43: upsert/replace по id."""
        from tg_parser.domain.models import Anchor, TopicCard, TopicType

        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)

            # Первая версия
            card1 = TopicCard(
                id="topic:tg:ch:post:123",
                title="Original Title",
                summary="Original summary",
                scope_in=["original"],
                scope_out=["excluded"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.8,
                    )
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(card1)

        # Обновляем (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)

            card2 = TopicCard(
                id="topic:tg:ch:post:123",
                title="Updated Title",
                summary="Updated summary",
                scope_in=["updated"],
                scope_out=["new excluded"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.95,
                    )
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14, 13, 0, 0),
            )

            await repo.upsert(card2)

            # Проверяем что обновлена
            retrieved = await repo.get_by_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert retrieved.title == "Updated Title"
            assert retrieved.summary == "Updated summary"
            assert retrieved.anchors[0].score == 0.95

    @pytest.mark.asyncio
    async def test_list_by_channel(self, test_db):
        """Тест получения topic cards по каналу."""
        from tg_parser.domain.models import Anchor, TopicCard, TopicType

        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)

            # Создаём карточки для разных каналов
            for ch in ["ch1", "ch2"]:
                for i in range(2):
                    card = TopicCard(
                        id=f"topic:tg:{ch}:post:{i}",
                        title=f"Topic {ch}-{i}",
                        summary=f"Summary {i}",
                        scope_in=["scope"],
                        scope_out=["excluded"],
                        type=TopicType.SINGLETON,
                        anchors=[
                            Anchor(
                                channel_id=ch,
                                message_id=str(i),
                                message_type=MessageType.POST,
                                anchor_ref=f"tg:{ch}:post:{i}",
                                score=0.9,
                            )
                        ],
                        sources=[ch],
                        updated_at=datetime(2025, 12, 14, 12, i, 0),
                    )
                    await repo.upsert(card)

        # Проверяем фильтрацию по каналу
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)

            ch1_cards = await repo.list_by_channel("ch1")
            assert len(ch1_cards) == 2
            assert all(card.sources == ["ch1"] for card in ch1_cards)

            ch2_cards = await repo.list_by_channel("ch2")
            assert len(ch2_cards) == 2


class TestTopicBundleRepo:
    """Integration тесты для TopicBundleRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_bundle(self, test_db):
        """Тест создания новой topic bundle."""
        from tg_parser.domain.models import BundleItem, BundleItemRole, TopicBundle

        async with test_db.processing_storage_session() as session:
            repo = SATopicBundleRepo(session)

            bundle = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                    BundleItem(
                        channel_id="ch",
                        message_id="456",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:456",
                        role=BundleItemRole.SUPPORTING,
                        score=0.7,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(bundle)

            # Проверяем что создана
            retrieved = await repo.get_by_topic_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert len(retrieved.items) == 2
            assert retrieved.items[0].role == BundleItemRole.ANCHOR
            assert retrieved.items[1].role == BundleItemRole.SUPPORTING

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_bundle(self, test_db):
        """TR-43: upsert/replace по topic_id."""
        from tg_parser.domain.models import BundleItem, BundleItemRole, TopicBundle

        async with test_db.processing_storage_session() as session:
            repo = SATopicBundleRepo(session)

            # Первая версия
            bundle1 = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(bundle1)

        # Обновляем (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SATopicBundleRepo(session)

            bundle2 = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                    BundleItem(
                        channel_id="ch",
                        message_id="456",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:456",
                        role=BundleItemRole.SUPPORTING,
                        score=0.8,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 13, 0, 0),
            )

            await repo.upsert(bundle2)

            # Проверяем что обновлена
            retrieved = await repo.get_by_topic_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert len(retrieved.items) == 2

    @pytest.mark.asyncio
    async def test_deduplication_by_source_ref(self, test_db):
        """TR-36: дедупликация по source_ref."""
        from tg_parser.domain.models import BundleItem, BundleItemRole, TopicBundle

        async with test_db.processing_storage_session() as session:
            repo = SATopicBundleRepo(session)

            # Bundle с дублирующими source_ref (не должно происходить в реальности,
            # но проверяем что хранилище не отвергает)
            bundle = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(bundle)

            # Получаем обратно
            retrieved = await repo.get_by_topic_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert len(retrieved.items) == 1


class TestIngestionStateRepo:
    """Integration тесты для IngestionStateRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_source(self, test_db):
        """Тест создания нового источника."""
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            source = Source(
                source_id="test_source",
                channel_id="test_channel",
                channel_username="test_username",
                status="active",
                include_comments=True,
                batch_size=100,
            )

            await repo.upsert_source(source)

            # Получаем обратно
            retrieved = await repo.get_source("test_source")
            assert retrieved is not None
            assert retrieved.source_id == "test_source"
            assert retrieved.channel_id == "test_channel"
            assert retrieved.status == "active"
            assert retrieved.include_comments is True

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_source(self, test_db):
        """Тест обновления существующего источника."""
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            # Создаём источник
            source1 = Source(
                source_id="test_source",
                channel_id="test_channel",
                status="active",
                include_comments=False,
            )
            await repo.upsert_source(source1)

        # Обновляем статус (новая сессия)
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            source2 = Source(
                source_id="test_source",
                channel_id="test_channel",
                status="paused",
                include_comments=True,
            )
            await repo.upsert_source(source2)

            # Проверяем обновление
            retrieved = await repo.get_source("test_source")
            assert retrieved is not None
            assert retrieved.status == "paused"
            assert retrieved.include_comments is True

    @pytest.mark.asyncio
    async def test_list_sources_with_filter(self, test_db):
        """Тест фильтрации источников по статусу."""
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            # Создаём несколько источников
            await repo.upsert_source(
                Source(source_id="src1", channel_id="ch1", status="active", include_comments=False)
            )
            await repo.upsert_source(
                Source(source_id="src2", channel_id="ch2", status="paused", include_comments=False)
            )
            await repo.upsert_source(
                Source(source_id="src3", channel_id="ch3", status="active", include_comments=False)
            )

            # Фильтр по статусу
            active_sources = await repo.list_sources(status="active")
            assert len(active_sources) == 2

            paused_sources = await repo.list_sources(status="paused")
            assert len(paused_sources) == 1

            # Все источники
            all_sources = await repo.list_sources()
            assert len(all_sources) == 3

    @pytest.mark.asyncio
    async def test_update_cursors_tr7_tr10(self, test_db):
        """
        TR-7: per-post курсоры комментариев.
        TR-10: атомарность обновления курсоров.
        """
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            # Создаём источник
            source = Source(
                source_id="test_source",
                channel_id="test_channel",
                status="active",
                include_comments=True,
            )
            await repo.upsert_source(source)

        # Обновляем курсоры (новая сессия)
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            await repo.update_cursors(
                source_id="test_source",
                last_post_id="post_100",
                comment_cursors={
                    "thread_1": "comment_50",
                    "thread_2": "comment_75",
                },
            )

            # Проверяем last_post_id
            source = await repo.get_source("test_source")
            assert source.last_post_id == "post_100"

            # Проверяем per-thread курсоры
            cursor1 = await repo.get_comment_cursor("test_source", "thread_1")
            assert cursor1 == "comment_50"

            cursor2 = await repo.get_comment_cursor("test_source", "thread_2")
            assert cursor2 == "comment_75"

    @pytest.mark.asyncio
    async def test_record_attempt_success(self, test_db):
        """Тест записи успешной попытки (TR-11)."""
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            # Создаём источник
            source = Source(
                source_id="test_source",
                channel_id="test_channel",
                status="active",
                include_comments=False,
                fail_count=3,
                last_error="Previous error",
            )
            await repo.upsert_source(source)

        # Записываем успешную попытку (новая сессия)
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            await repo.record_attempt(
                source_id="test_source",
                success=True,
            )

            # Проверяем что fail_count сброшен и last_error очищен
            source = await repo.get_source("test_source")
            assert source.fail_count == 0
            assert source.last_error is None
            assert source.last_success_at is not None
            assert source.last_attempt_at is not None

    @pytest.mark.asyncio
    async def test_record_attempt_failure(self, test_db):
        """Тест записи неудачной попытки (TR-11, TR-12)."""
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            # Создаём источник
            source = Source(
                source_id="test_source",
                channel_id="test_channel",
                status="active",
                include_comments=False,
                fail_count=0,
            )
            await repo.upsert_source(source)

        # Записываем неудачную попытку (новая сессия)
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            await repo.record_attempt(
                source_id="test_source",
                success=False,
                error_class="NetworkError",
                error_message="Connection timeout",
                details={"retry": 1, "backoff": 2.0},
            )

            # Проверяем что fail_count увеличен и ошибка записана
            source = await repo.get_source("test_source")
            assert source.fail_count == 1
            assert source.last_error == "Connection timeout"
            assert source.last_attempt_at is not None

    @pytest.mark.asyncio
    async def test_get_comment_cursor_not_exists(self, test_db):
        """Тест получения несуществующего курсора."""
        async with test_db.ingestion_state_session() as session:
            repo = SAIngestionStateRepo(session)

            cursor = await repo.get_comment_cursor("test_source", "thread_999")
            assert cursor is None


class TestTopicLinkRepo:
    """Integration tests for SATopicLinkRepo (Cross-dev 3)."""

    @pytest.mark.asyncio
    async def test_upsert_and_get_by_topic_id(self, test_db):
        """Test upsert a TopicLink and retrieve it by topic_id."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            link = TopicLink(
                topic_id_a="topic:ch1:post:1",
                topic_id_b="topic:ch2:post:10",
                similarity_score=0.85,
                shared_keywords=["python", "asyncio"],
                created_at=datetime(2025, 12, 15, 10, 0, 0),
            )
            await repo.upsert(link)

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            results = await repo.get_by_topic_id("topic:ch1:post:1")
            assert len(results) == 1
            assert results[0].similarity_score == pytest.approx(0.85, abs=1e-4)
            assert set(results[0].shared_keywords) == {"python", "asyncio"}

            results_b = await repo.get_by_topic_id("topic:ch2:post:10")
            assert len(results_b) == 1

    @pytest.mark.asyncio
    async def test_upsert_batch(self, test_db):
        """Test batch upsert of multiple TopicLinks."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            links = [
                TopicLink(
                    topic_id_a="topic:a:post:1",
                    topic_id_b="topic:b:post:2",
                    similarity_score=0.9,
                    shared_keywords=["ml"],
                    created_at=datetime(2025, 12, 15, 10, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:a:post:1",
                    topic_id_b="topic:c:post:3",
                    similarity_score=0.7,
                    shared_keywords=["python", "ml"],
                    created_at=datetime(2025, 12, 15, 10, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:b:post:2",
                    topic_id_b="topic:c:post:3",
                    similarity_score=0.6,
                    shared_keywords=[],
                    created_at=datetime(2025, 12, 15, 10, 0, 0),
                ),
            ]
            saved = await repo.upsert_batch(links)
            assert saved == 3

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            all_links = await repo.list_all()
            assert len(all_links) == 3
            assert all_links[0].similarity_score >= all_links[-1].similarity_score

    @pytest.mark.asyncio
    async def test_upsert_batch_updates_existing(self, test_db):
        """Test that upsert_batch updates existing links on conflict."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            link = TopicLink(
                topic_id_a="topic:x:post:1",
                topic_id_b="topic:y:post:2",
                similarity_score=0.5,
                shared_keywords=["old"],
                created_at=datetime(2025, 12, 15, 10, 0, 0),
            )
            await repo.upsert(link)

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            updated = TopicLink(
                topic_id_a="topic:x:post:1",
                topic_id_b="topic:y:post:2",
                similarity_score=0.95,
                shared_keywords=["new", "updated"],
                created_at=datetime(2025, 12, 16, 10, 0, 0),
            )
            await repo.upsert_batch([updated])

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            results = await repo.get_by_topic_id("topic:x:post:1")
            assert len(results) == 1
            assert results[0].similarity_score == pytest.approx(0.95, abs=1e-4)
            assert "new" in results[0].shared_keywords

    @pytest.mark.asyncio
    async def test_list_all_returns_sorted_by_score(self, test_db):
        """Test that list_all returns links sorted by similarity_score DESC."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            links = [
                TopicLink(
                    topic_id_a="topic:1",
                    topic_id_b="topic:2",
                    similarity_score=0.3,
                    created_at=datetime(2025, 12, 15, 10, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:3",
                    topic_id_b="topic:4",
                    similarity_score=0.9,
                    created_at=datetime(2025, 12, 15, 10, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:5",
                    topic_id_b="topic:6",
                    similarity_score=0.6,
                    created_at=datetime(2025, 12, 15, 10, 0, 0),
                ),
            ]
            await repo.upsert_batch(links)

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            all_links = await repo.list_all()
            scores = [link.similarity_score for link in all_links]
            assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_delete_all(self, test_db):
        """Test delete_all removes all links."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            await repo.upsert_batch(
                [
                    TopicLink(
                        topic_id_a="a",
                        topic_id_b="b",
                        similarity_score=0.5,
                        created_at=datetime(2025, 12, 15, 10, 0, 0),
                    ),
                    TopicLink(
                        topic_id_a="c",
                        topic_id_b="d",
                        similarity_score=0.6,
                        created_at=datetime(2025, 12, 15, 10, 0, 0),
                    ),
                ]
            )

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            deleted = await repo.delete_all()
            assert deleted == 2
            assert await repo.count() == 0

    @pytest.mark.asyncio
    async def test_count(self, test_db):
        """Test count returns correct number of links."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            assert await repo.count() == 0

            await repo.upsert_batch(
                [
                    TopicLink(
                        topic_id_a="t1",
                        topic_id_b="t2",
                        similarity_score=0.5,
                        created_at=datetime(2025, 12, 15, 10, 0, 0),
                    ),
                ]
            )
            assert await repo.count() == 1


class TestTopicLinkRepoIntegration:
    """Integration tests for TopicLinkRepo batch APIs and query behavior."""

    @pytest.mark.asyncio
    async def test_upsert_batch_and_list_all(self, test_db):
        """Batch upsert links, then list_all and verify content and score ordering."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            links = [
                TopicLink(
                    topic_id_a="topic:tg:alpha_news:post:100",
                    topic_id_b="topic:tg:beta_tech:post:200",
                    similarity_score=0.82,
                    shared_keywords=["kubernetes", "deployment", "helm"],
                    created_at=datetime(2025, 12, 20, 9, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:tg:alpha_news:post:100",
                    topic_id_b="topic:tg:gamma_dev:post:300",
                    similarity_score=0.91,
                    shared_keywords=["kubernetes", "containers"],
                    created_at=datetime(2025, 12, 20, 9, 5, 0),
                ),
                TopicLink(
                    topic_id_a="topic:tg:beta_tech:post:200",
                    topic_id_b="topic:tg:gamma_dev:post:300",
                    similarity_score=0.55,
                    shared_keywords=["docker"],
                    created_at=datetime(2025, 12, 20, 9, 10, 0),
                ),
            ]
            n = await repo.upsert_batch(links)
            assert n == 3

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            all_links = await repo.list_all()
            assert len(all_links) == 3

            scores = [x.similarity_score for x in all_links]
            assert scores == sorted(scores, reverse=True)

            by_pair = {(x.topic_id_a, x.topic_id_b): x for x in all_links}
            l0 = by_pair[("topic:tg:alpha_news:post:100", "topic:tg:beta_tech:post:200")]
            assert l0.similarity_score == pytest.approx(0.82, abs=1e-4)
            assert set(l0.shared_keywords) == {"kubernetes", "deployment", "helm"}

            l1 = by_pair[("topic:tg:alpha_news:post:100", "topic:tg:gamma_dev:post:300")]
            assert l1.similarity_score == pytest.approx(0.91, abs=1e-4)
            assert set(l1.shared_keywords) == {"kubernetes", "containers"}

            l2 = by_pair[("topic:tg:beta_tech:post:200", "topic:tg:gamma_dev:post:300")]
            assert l2.similarity_score == pytest.approx(0.55, abs=1e-4)
            assert l2.shared_keywords == ["docker"]

    @pytest.mark.asyncio
    async def test_get_by_topic_id(self, test_db):
        """Upsert several links; get_by_topic_id returns all edges for that topic, sorted by score."""
        hub = "topic:tg:central_digest:post:1"
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            await repo.upsert_batch(
                [
                    TopicLink(
                        topic_id_a=hub,
                        topic_id_b="topic:tg:side_channel_a:post:50",
                        similarity_score=0.72,
                        shared_keywords=["policy", "regulation"],
                        created_at=datetime(2025, 12, 21, 12, 0, 0),
                    ),
                    TopicLink(
                        topic_id_a=hub,
                        topic_id_b="topic:tg:side_channel_b:post:60",
                        similarity_score=0.88,
                        shared_keywords=["policy", "eu"],
                        created_at=datetime(2025, 12, 21, 12, 1, 0),
                    ),
                    TopicLink(
                        topic_id_a="topic:tg:side_channel_a:post:50",
                        topic_id_b="topic:tg:side_channel_b:post:60",
                        similarity_score=0.41,
                        shared_keywords=["news"],
                        created_at=datetime(2025, 12, 21, 12, 2, 0),
                    ),
                ]
            )

        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)
            hub_links = await repo.get_by_topic_id(hub)
            assert len(hub_links) == 2
            assert hub_links[0].similarity_score >= hub_links[1].similarity_score
            assert hub_links[0].similarity_score == pytest.approx(0.88, abs=1e-4)
            assert hub_links[1].similarity_score == pytest.approx(0.72, abs=1e-4)
            for row in hub_links:
                assert hub in (row.topic_id_a, row.topic_id_b)

            side_a_links = await repo.get_by_topic_id("topic:tg:side_channel_a:post:50")
            assert len(side_a_links) == 2
            pairs = {(x.topic_id_a, x.topic_id_b) for x in side_a_links}
            assert (hub, "topic:tg:side_channel_a:post:50") in pairs
            assert (
                "topic:tg:side_channel_a:post:50",
                "topic:tg:side_channel_b:post:60",
            ) in pairs

    @pytest.mark.asyncio
    async def test_upsert_batch_deduplication(self, test_db):
        """Upserting the same logical links twice must not create duplicate rows."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicLinkRepo(session)

            batch = [
                TopicLink(
                    topic_id_a="topic:tg:dedupe_a:post:1",
                    topic_id_b="topic:tg:dedupe_b:post:2",
                    similarity_score=0.77,
                    shared_keywords=["rust", "wasm"],
                    created_at=datetime(2025, 12, 22, 8, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:tg:dedupe_a:post:1",
                    topic_id_b="topic:tg:dedupe_c:post:3",
                    similarity_score=0.63,
                    shared_keywords=["rust"],
                    created_at=datetime(2025, 12, 22, 8, 0, 0),
                ),
            ]
            assert await repo.upsert_batch(batch) == 2
            assert await repo.count() == 2

            same_again = [
                TopicLink(
                    topic_id_a="topic:tg:dedupe_a:post:1",
                    topic_id_b="topic:tg:dedupe_b:post:2",
                    similarity_score=0.77,
                    shared_keywords=["rust", "wasm"],
                    created_at=datetime(2025, 12, 22, 9, 0, 0),
                ),
                TopicLink(
                    topic_id_a="topic:tg:dedupe_a:post:1",
                    topic_id_b="topic:tg:dedupe_c:post:3",
                    similarity_score=0.63,
                    shared_keywords=["rust"],
                    created_at=datetime(2025, 12, 22, 9, 0, 0),
                ),
            ]
            assert await repo.upsert_batch(same_again) == 2
            assert await repo.count() == 2

            listed = await repo.list_all()
            assert len(listed) == 2
            pairs = {(x.topic_id_a, x.topic_id_b) for x in listed}
            assert pairs == {
                ("topic:tg:dedupe_a:post:1", "topic:tg:dedupe_b:post:2"),
                ("topic:tg:dedupe_a:post:1", "topic:tg:dedupe_c:post:3"),
            }
