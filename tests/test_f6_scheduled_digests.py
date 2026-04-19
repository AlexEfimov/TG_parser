"""
F6 — Scheduled Digests test suite.

Commit 1 scope: schema, repo, DigestService, prompt loader, LLM-stage extension.
Commit 2 scope (added later): scheduler integration, bot delivery, bot/MCP tools,
reconciliation.

Postgres-backed tests are gated by ``TEST_POSTGRES=1`` (matches existing F4
storage tests). Pure-logic tests (service mock-only, prompt loader, LLM scope)
run unconditionally.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.config.settings import LLM_SCOPES, LLMConfigManager, Settings
from tg_parser.domain.models import (
    DigestFormat,
    DigestSubscription,
    ProcessedDocument,
)
from tg_parser.processing.prompt_loader import PromptLoader
from tg_parser.services.digest_service import (
    DigestResult,
    DigestService,
    escape_markdown_v2,
)
from tg_parser.storage.sqlalchemy.digest_subscription_repo import (
    SADigestSubscriptionRepo,
)
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"


# ============================================================================
# Helpers
# ============================================================================


def _make_processed_doc(
    channel_id: str = "ch1",
    msg_id: str = "1",
    processed_at: datetime | None = None,
    summary: str | None = None,
    text_clean: str | None = None,
) -> ProcessedDocument:
    return ProcessedDocument(
        id=f"doc:tg:{channel_id}:post:{msg_id}",
        source_ref=f"tg:{channel_id}:post:{msg_id}",
        source_message_id=msg_id,
        channel_id=channel_id,
        processed_at=processed_at or datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
        text_clean=text_clean or f"clean text {msg_id}",
        summary=summary or f"summary {msg_id}",
        topics=[],
        entities=[],
    )


def _make_subscription(
    *,
    sub_id: str | None = None,
    owner_id: str = "00000000-0000-0000-0000-0000000000bb",
    chat_id: int = 123,
    name: str = "morning brief",
    channel_ids: list[str] | None = None,
    cron_expression: str = "0 9 * * *",
    timezone: str = "UTC",
    format: DigestFormat = DigestFormat.SUMMARY,
    language: str = "ru",
    is_active: bool = True,
    last_sent_at: datetime | None = None,
    last_digest_cursor: datetime | None = None,
) -> DigestSubscription:
    import uuid as _uuid

    return DigestSubscription(
        id=sub_id if sub_id is not None else str(_uuid.uuid4()),
        owner_id=owner_id,
        chat_id=chat_id,
        name=name,
        channel_ids=channel_ids or ["ch1"],
        cron_expression=cron_expression,
        timezone=timezone,
        format=format,
        language=language,
        is_active=is_active,
        last_sent_at=last_sent_at,
        last_digest_cursor=last_digest_cursor,
    )


class _FakeProcessedRepo:
    """Tiny stub of ``ProcessedDocumentRepo.list_by_channel`` used by service tests."""

    def __init__(self, docs_by_channel: dict[str, list[ProcessedDocument]]):
        self._docs = docs_by_channel
        self.calls: list[tuple[str, datetime | None, datetime | None]] = []

    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ProcessedDocument]:
        self.calls.append((channel_id, from_date, to_date))
        docs = list(self._docs.get(channel_id, []))
        if from_date is not None:
            docs = [d for d in docs if d.processed_at >= from_date]
        if to_date is not None:
            docs = [d for d in docs if d.processed_at <= to_date]
        return docs


class _FakeLLM:
    """Captures (system, user, kwargs) and returns a canned response."""

    def __init__(self, response: str = "## Канал ch1\n- факт 1"):
        self.response = response
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        return self.response


def _make_current_user(
    user_id: str,
    *,
    name: str = "test",
    role: str = "admin",
    allowed_channel_ids: set[str] | None = None,
    max_channels: int = 999,
):
    """Wrapper around ``CurrentUser`` that defaults the F4-required fields."""
    from tg_parser.auth.models import CurrentUser

    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=(
            None if allowed_channel_ids is None and role == "admin" else allowed_channel_ids
        ),
        max_channels=max_channels,
    )


def _make_service(
    *,
    docs_by_channel: dict[str, list[ProcessedDocument]] | None = None,
    llm_response: str = "## ch1\n- bullet",
    max_docs_per_run: int = 50,
    first_run_lookback_hours: int = 24,
    sub_repo_update: AsyncMock | None = None,
    message_max_chars: int = 4096,
    max_message_parts: int = 10,
) -> tuple[DigestService, _FakeProcessedRepo, _FakeLLM, AsyncMock]:
    processed = _FakeProcessedRepo(docs_by_channel or {})
    llm = _FakeLLM(llm_response)
    sub_repo = MagicMock()
    sub_repo.update = sub_repo_update or AsyncMock()
    loader = PromptLoader(prompts_dir=PROMPTS_DIR)
    factory: Callable = lambda: llm  # noqa: E731
    service = DigestService(
        processed_repo=processed,
        subscription_repo=sub_repo,
        prompt_loader=loader,
        llm_client_factory=factory,
        max_docs_per_run=max_docs_per_run,
        first_run_lookback_hours=first_run_lookback_hours,
        message_max_chars=message_max_chars,
        max_message_parts=max_message_parts,
    )
    return service, processed, llm, sub_repo.update


# ============================================================================
# TestDigestSubscriptionRepo (Postgres)
# ============================================================================


pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


@pytest.fixture
async def _digest_db(test_db):
    """Truncate F4 + F6 tables (alembic-managed schema, DI-19)."""
    session = test_db.ingestion_state_session()
    try:
        from sqlalchemy import text

        await session.execute(text("DELETE FROM digest_subscriptions"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db


@pytest.fixture
async def digest_repo(_digest_db):
    session = _digest_db.ingestion_state_session()
    try:
        yield SADigestSubscriptionRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def user_repo_for_digest(_digest_db):
    session = _digest_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


@pg_only
class TestDigestSubscriptionRepo:
    async def test_create_returns_uuid_and_persists(self, digest_repo, user_repo_for_digest):
        owner = await user_repo_for_digest.create_user("alice")
        # Caller-supplied id is preserved so the scheduler and DB stay in sync.
        sub = _make_subscription(
            sub_id="11111111-2222-3333-4444-555555555555",
            owner_id=owner.id,
            channel_ids=["@durov", "@telegram"],
        )
        created = await digest_repo.create(sub)
        assert created.id == sub.id
        assert created.owner_id == owner.id
        assert created.channel_ids == ["@durov", "@telegram"]
        assert created.is_active is True
        # idempotent get
        fetched = await digest_repo.get(created.id)
        assert fetched is not None
        assert fetched.name == sub.name

    async def test_create_generates_uuid_when_id_omitted(self, digest_repo, user_repo_for_digest):
        """When ``sub.id`` is empty, the DB default (gen_random_uuid) kicks in."""
        owner = await user_repo_for_digest.create_user("alice_auto_id")
        sub = _make_subscription(
            sub_id="",
            owner_id=owner.id,
            channel_ids=["@durov"],
        )
        created = await digest_repo.create(sub)
        assert created.id and created.id != ""
        assert created.id != sub.id  # server-assigned UUID
        fetched = await digest_repo.get(created.id)
        assert fetched is not None

    async def test_get_returns_none_for_unknown_id(self, digest_repo):
        result = await digest_repo.get("00000000-0000-0000-0000-000000000000")
        assert result is None

    async def test_update_partial_fields_preserves_others(self, digest_repo, user_repo_for_digest):
        owner = await user_repo_for_digest.create_user("bob")
        sub = await digest_repo.create(_make_subscription(owner_id=owner.id))
        ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
        updated = await digest_repo.update(
            sub.id,
            last_sent_at=ts,
            last_digest_cursor=ts,
            is_active=False,
        )
        assert updated is not None
        assert updated.is_active is False
        assert updated.last_sent_at == ts
        assert updated.last_digest_cursor == ts
        assert updated.name == sub.name
        assert updated.cron_expression == sub.cron_expression
        assert updated.channel_ids == sub.channel_ids

    async def test_delete_returns_true_then_false(self, digest_repo, user_repo_for_digest):
        owner = await user_repo_for_digest.create_user("charlie")
        sub = await digest_repo.create(_make_subscription(owner_id=owner.id))
        assert await digest_repo.delete(sub.id) is True
        assert await digest_repo.delete(sub.id) is False
        assert await digest_repo.get(sub.id) is None

    async def test_list_by_owner_filters_correctly(self, digest_repo, user_repo_for_digest):
        alice = await user_repo_for_digest.create_user("alice2")
        bob = await user_repo_for_digest.create_user("bob2")
        await digest_repo.create(_make_subscription(owner_id=alice.id, name="alice 1"))
        await digest_repo.create(_make_subscription(owner_id=alice.id, name="alice 2"))
        await digest_repo.create(_make_subscription(owner_id=bob.id, name="bob 1"))

        alice_subs = await digest_repo.list_by_owner(alice.id)
        bob_subs = await digest_repo.list_by_owner(bob.id)
        assert len(alice_subs) == 2
        assert {s.name for s in alice_subs} == {"alice 1", "alice 2"}
        assert len(bob_subs) == 1
        assert bob_subs[0].name == "bob 1"

    async def test_list_active_excludes_paused(self, digest_repo, user_repo_for_digest):
        owner = await user_repo_for_digest.create_user("dora")
        active = await digest_repo.create(_make_subscription(owner_id=owner.id, name="active"))
        paused = await digest_repo.create(_make_subscription(owner_id=owner.id, name="paused"))
        await digest_repo.update(paused.id, is_active=False)

        active_list = await digest_repo.list_active()
        ids = {s.id for s in active_list}
        assert active.id in ids
        assert paused.id not in ids


# ============================================================================
# TestDigestService (pure logic with fakes)
# ============================================================================


class TestDigestService:
    async def test_generate_empty_when_no_new_docs_returns_skipped(self):
        service, _processed, llm, _update = _make_service(docs_by_channel={"ch1": []})
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 4, 17, tzinfo=UTC),
        )
        result = await service.generate(sub)
        assert result.skipped is True
        assert result.docs_count == 0
        assert result.body_markdown == ""
        assert llm.calls == [], "LLM must not be called on empty result"

    async def test_generate_first_run_uses_lookback_window(self):
        recent = _make_processed_doc(
            channel_id="ch1",
            msg_id="1",
            processed_at=datetime.now(UTC) - timedelta(hours=2),
        )
        old = _make_processed_doc(
            channel_id="ch1",
            msg_id="2",
            processed_at=datetime.now(UTC) - timedelta(days=5),
        )
        service, processed, llm, _update = _make_service(
            docs_by_channel={"ch1": [recent, old]},
            first_run_lookback_hours=24,
        )
        sub = _make_subscription(channel_ids=["ch1"], last_digest_cursor=None)
        result = await service.generate(sub)
        assert result.skipped is False
        assert result.docs_count == 1, "Only the recent doc falls inside lookback window"
        # confirm fake repo was queried with from_date ~ 24h ago
        _, from_date, _ = processed.calls[0]
        assert from_date is not None
        assert from_date <= datetime.now(UTC) - timedelta(hours=23, minutes=30)
        assert llm.calls, "LLM must be invoked for non-empty digest"

    async def test_generate_caps_docs_at_max_per_run(self):
        docs = [
            _make_processed_doc(
                channel_id="ch1",
                msg_id=str(i),
                processed_at=datetime(2026, 4, 18, 10, i % 60, tzinfo=UTC) + timedelta(minutes=i),
            )
            for i in range(100)
        ]
        service, _processed, llm, _update = _make_service(
            docs_by_channel={"ch1": docs},
            max_docs_per_run=10,
        )
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 1, 1, tzinfo=UTC),
        )
        result = await service.generate(sub)
        assert result.docs_count == 10
        assert result.per_channel_counts == {"ch1": 10}
        # LLM prompt should mention the per-channel total (100) AND the kept count (10)
        rendered_user_prompt = llm.calls[0]["prompt"]
        assert "10 of 100 new" in rendered_user_prompt

    async def test_generate_cap_keeps_oldest_so_backlog_resumes_next_tick(self):
        """Regression: with > max_docs new docs, cursor must advance only past
        the oldest slice we actually delivered — leftover newer docs must be
        picked up on the next tick, not silently skipped.
        """
        docs = [
            _make_processed_doc(
                channel_id="ch1",
                msg_id=str(i),
                processed_at=datetime(2026, 4, 18, 10, 0, tzinfo=UTC) + timedelta(minutes=i),
            )
            for i in range(5)
        ]
        service, _processed, _llm, _update = _make_service(
            docs_by_channel={"ch1": docs},
            max_docs_per_run=2,
        )
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
        )
        result = await service.generate(sub)

        assert result.docs_count == 2, "kept slice must equal max_docs_per_run"
        # Cursor must equal the timestamp of the LAST kept (oldest-slice) doc
        # so the next tick fetches the remaining three with strict `>`.
        assert result.new_cursor == docs[1].processed_at, (
            f"cursor must land on doc[1] (last kept), got {result.new_cursor}"
        )
        assert docs[2].processed_at > result.new_cursor, (
            "leftover docs must be strictly newer than the new cursor"
        )

    async def test_generate_updates_cursor_to_max_processed_at(self):
        doc1 = _make_processed_doc(
            channel_id="ch1",
            msg_id="1",
            processed_at=datetime(2026, 4, 18, 10, 0, tzinfo=UTC),
        )
        doc2 = _make_processed_doc(
            channel_id="ch1",
            msg_id="2",
            processed_at=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
        )
        service, _processed, _llm, _update = _make_service(docs_by_channel={"ch1": [doc1, doc2]})
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 4, 17, tzinfo=UTC),
        )
        result = await service.generate(sub)
        assert result.new_cursor == datetime(2026, 4, 18, 12, 0, tzinfo=UTC)

    async def test_generate_groups_by_channel_in_prompt(self):
        d1 = _make_processed_doc(
            channel_id="ch1",
            msg_id="1",
            summary="alpha",
            processed_at=datetime(2026, 4, 18, 10, tzinfo=UTC),
        )
        d2 = _make_processed_doc(
            channel_id="ch2",
            msg_id="2",
            summary="beta",
            processed_at=datetime(2026, 4, 18, 11, tzinfo=UTC),
        )
        service, _processed, llm, _update = _make_service(
            docs_by_channel={"ch1": [d1], "ch2": [d2]},
        )
        sub = _make_subscription(
            channel_ids=["ch1", "ch2"],
            last_digest_cursor=datetime(2026, 4, 17, tzinfo=UTC),
        )
        await service.generate(sub)
        rendered = llm.calls[0]["prompt"]
        assert "## ch1" in rendered
        assert "## ch2" in rendered
        idx_ch1 = rendered.index("## ch1")
        idx_ch2 = rendered.index("## ch2")
        assert idx_ch1 < idx_ch2  # order matches subscription channel_ids

    async def test_generate_strict_greater_than_cursor(self):
        """processed_at == cursor must be excluded — strict-`>` filter."""
        cursor_time = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
        doc_at_cursor = _make_processed_doc(
            channel_id="ch1", msg_id="boundary", processed_at=cursor_time
        )
        doc_after = _make_processed_doc(
            channel_id="ch1",
            msg_id="after",
            processed_at=cursor_time + timedelta(seconds=1),
        )
        service, _processed, llm, _update = _make_service(
            docs_by_channel={"ch1": [doc_at_cursor, doc_after]},
        )
        sub = _make_subscription(channel_ids=["ch1"], last_digest_cursor=cursor_time)
        result = await service.generate(sub)
        assert result.docs_count == 1, "doc with processed_at == cursor must be skipped"
        rendered = llm.calls[0]["prompt"]
        assert "after" in rendered
        assert "boundary" not in rendered

    async def test_run_for_subscription_skipped_advances_cursor_no_send(self):
        update_mock = AsyncMock()
        service, _processed, _llm, _update = _make_service(
            docs_by_channel={"ch1": []},
            sub_repo_update=update_mock,
        )
        sub = _make_subscription(channel_ids=["ch1"], last_digest_cursor=None)
        bot = AsyncMock()
        bot.send_message = AsyncMock()

        result = await service.run_for_subscription(sub, bot)
        assert result.skipped is True
        update_mock.assert_awaited()
        # Skipped digests must NOT call send_message
        bot.send_message.assert_not_called()
        # cursor must have advanced (first-run safety)
        kwargs = update_mock.await_args.kwargs
        assert kwargs.get("last_digest_cursor") is not None
        assert kwargs.get("last_sent_at") is not None

    async def test_run_for_subscription_no_bot_skips_cursor_update(self):
        update_mock = AsyncMock()
        doc = _make_processed_doc(
            channel_id="ch1",
            msg_id="1",
            processed_at=datetime(2026, 4, 18, 10, tzinfo=UTC),
        )
        service, _processed, _llm, _update = _make_service(
            docs_by_channel={"ch1": [doc]},
            sub_repo_update=update_mock,
        )
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 4, 17, tzinfo=UTC),
        )
        result = await service.run_for_subscription(sub, bot=None)
        assert result.delivery_failed is True
        assert result.delivery_error == "bot_unavailable"
        update_mock.assert_not_called()

    async def test_run_for_subscription_send_failure_skips_cursor(self):
        update_mock = AsyncMock()
        doc = _make_processed_doc(
            channel_id="ch1",
            msg_id="1",
            processed_at=datetime(2026, 4, 18, 10, tzinfo=UTC),
        )
        service, _processed, _llm, _update = _make_service(
            docs_by_channel={"ch1": [doc]},
            sub_repo_update=update_mock,
        )
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 4, 17, tzinfo=UTC),
        )
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("network down"))

        result = await service.run_for_subscription(sub, bot)
        assert result.delivery_failed is True
        assert "network down" in (result.delivery_error or "")
        update_mock.assert_not_called()


# ============================================================================
# TestDigestPromptLoader
# ============================================================================


class TestDigestPromptLoader:
    def test_digest_prompt_loads_successfully(self):
        loader = PromptLoader(prompts_dir=PROMPTS_DIR)
        cfg = loader.load("digest")
        assert isinstance(cfg, dict)
        assert "system" in cfg
        assert "user" in cfg
        assert "model" in cfg
        assert isinstance(cfg["system"].get("prompt"), str)
        assert isinstance(cfg["user"].get("template"), str)

    def test_digest_prompt_includes_required_template_vars(self):
        loader = PromptLoader(prompts_dir=PROMPTS_DIR)
        cfg = loader.load("digest")
        user_template = cfg["user"]["template"]
        for var in ("{format}", "{language}", "{from_iso}", "{to_iso}", "{channels_block}"):
            assert var in user_template, f"missing placeholder {var} in digest user template"


# ============================================================================
# TestDigestLLMScope
# ============================================================================


class TestDigestLLMScope:
    def test_llm_scopes_includes_digest(self):
        assert "digest" in LLM_SCOPES

    def test_resolve_digest_falls_back_to_global(self):
        LLMConfigManager.reset()
        s = Settings(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            openai_api_key="sk-test",
            telegram_api_id=1,
            telegram_api_hash="h",
            telegram_phone="+1",
        )
        mgr = LLMConfigManager.get_instance(s)
        try:
            provider, _api_key, model = mgr.resolve("digest")
            assert provider == "openai"
            assert model == "gpt-4o-mini"
        finally:
            LLMConfigManager.reset()

    def test_resolve_digest_uses_override_when_set(self):
        LLMConfigManager.reset()
        s = Settings(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            openai_api_key="sk-test",
            anthropic_api_key="ant-test",
            telegram_api_id=1,
            telegram_api_hash="h",
            telegram_phone="+1",
        )
        mgr = LLMConfigManager.get_instance(s)
        try:
            mgr.set("digest", provider="anthropic", model="claude-haiku")
            provider, _api_key, model = mgr.resolve("digest")
            assert provider == "anthropic"
            assert model == "claude-haiku"
        finally:
            LLMConfigManager.reset()

    def test_resolve_digest_uses_static_stage_setting(self):
        LLMConfigManager.reset()
        s = Settings(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            openai_api_key="sk-test",
            gemini_api_key="g-test",
            digest_llm_provider="gemini",
            digest_llm_model="gemini-2.0-flash-exp",
            telegram_api_id=1,
            telegram_api_hash="h",
            telegram_phone="+1",
        )
        mgr = LLMConfigManager.get_instance(s)
        try:
            provider, _api_key, model = mgr.resolve("digest")
            assert provider == "gemini"
            assert model == "gemini-2.0-flash-exp"
        finally:
            LLMConfigManager.reset()


# ============================================================================
# escape_markdown_v2 helper
# ============================================================================


class TestEscapeMarkdownV2:
    @pytest.mark.parametrize(
        "raw,expected_substring",
        [
            ("@my_channel", "@my\\_channel"),
            ("hello.world", "hello\\.world"),
            ("[link](url)", "\\[link\\]\\(url\\)"),
            ("a*b_c", "a\\*b\\_c"),
            ("price = 5+3-1!", "price \\= 5\\+3\\-1\\!"),
        ],
    )
    def test_escape_special_chars(self, raw: str, expected_substring: str):
        out = escape_markdown_v2(raw)
        assert expected_substring in out

    def test_empty_string(self):
        assert escape_markdown_v2("") == ""


# ============================================================================
# Commit 2 — Scheduler integration, delivery, bot/MCP tools, reconciliation
# ============================================================================


# ----------------------------------------------------------------------------
# TestSchedulerCronIntegration
# ----------------------------------------------------------------------------


class TestSchedulerCronIntegration:
    """Cron-trigger plumbing on top of ``BackgroundScheduler``."""

    def test_add_cron_task_registers_with_correct_trigger(self):
        from tg_parser.services.background_scheduler import BackgroundScheduler

        scheduler = BackgroundScheduler()

        async def _noop():
            return None

        job = scheduler.add_cron_task(
            task_id="test_cron",
            func=_noop,
            cron_expression="0 9 * * *",
            timezone="Europe/Moscow",
        )
        assert job is not None
        from apscheduler.triggers.cron import CronTrigger

        assert isinstance(job.trigger, CronTrigger)
        # Trigger must be configured with the requested IANA timezone
        assert "Moscow" in str(job.trigger.timezone)

    def test_add_cron_task_invalid_expression_raises(self):
        from tg_parser.services.background_scheduler import BackgroundScheduler

        scheduler = BackgroundScheduler()
        with pytest.raises(ValueError, match="invalid cron"):
            scheduler.add_cron_task(
                task_id="bad",
                func=lambda: None,
                cron_expression="not a cron",
                timezone="UTC",
            )

    def test_add_cron_task_invalid_timezone_raises(self):
        from tg_parser.services.background_scheduler import BackgroundScheduler

        scheduler = BackgroundScheduler()
        with pytest.raises(ValueError, match="invalid cron"):
            scheduler.add_cron_task(
                task_id="badtz",
                func=lambda: None,
                cron_expression="0 9 * * *",
                timezone="Mars/Olympus",
            )

    def test_register_digest_subscription_creates_job(self):
        from tg_parser.services.background_scheduler import (
            BackgroundScheduler,
            register_digest_subscription,
        )

        sub = _make_subscription(sub_id="11111111-1111-1111-1111-111111111111")
        scheduler = BackgroundScheduler()
        job = register_digest_subscription(sub, scheduler)
        assert job is not None
        assert job.id == f"digest:{sub.id}"

    def test_register_inactive_subscription_skipped(self):
        from tg_parser.services.background_scheduler import (
            BackgroundScheduler,
            register_digest_subscription,
        )

        sub = _make_subscription(
            sub_id="22222222-2222-2222-2222-222222222222",
            is_active=False,
        )
        scheduler = BackgroundScheduler()
        job = register_digest_subscription(sub, scheduler)
        assert job is None

    def test_unregister_removes_job(self):
        from tg_parser.services.background_scheduler import (
            BackgroundScheduler,
            register_digest_subscription,
            unregister_digest_subscription,
        )

        sub = _make_subscription(sub_id="33333333-3333-3333-3333-333333333333")
        scheduler = BackgroundScheduler()
        register_digest_subscription(sub, scheduler)
        assert unregister_digest_subscription(sub.id, scheduler) is True
        # idempotent: second call returns False
        assert unregister_digest_subscription(sub.id, scheduler) is False


# ----------------------------------------------------------------------------
# TestDigestDelivery
# ----------------------------------------------------------------------------


class TestDigestDelivery:
    """``DigestService.deliver`` → aiogram Bot interaction."""

    async def test_deliver_calls_send_message_with_markdown_v2(self):
        from aiogram.enums import ParseMode

        service, _processed, _llm, _update = _make_service()
        result = DigestResult(
            subscription_id="x",
            chat_id=42,
            title="My Digest",
            body_markdown="**Hello** _world_",
            docs_count=3,
            new_cursor=datetime(2026, 4, 18, tzinfo=UTC),
            skipped=False,
        )
        bot = AsyncMock()
        bot.send_message = AsyncMock()

        await service.deliver(bot, result)
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == 42
        assert kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
        # Body must be MarkdownV2-escaped
        assert "\\*" in kwargs["text"]
        assert "\\_" in kwargs["text"]

    async def test_deliver_splits_long_messages(self):
        service, _processed, _llm, _update = _make_service(
            message_max_chars=1000,
            max_message_parts=10,
        )
        long_body = "paragraph text\n" * 200
        result = DigestResult(
            subscription_id="x",
            chat_id=1,
            title="t",
            body_markdown=long_body,
            docs_count=1,
            new_cursor=None,
            skipped=False,
        )
        bot = AsyncMock()
        bot.send_message = AsyncMock()

        await service.deliver(bot, result)
        assert bot.send_message.await_count >= 2

    async def test_deliver_falls_back_to_document_when_too_many_parts(self):
        service, _processed, _llm, _update = _make_service(
            message_max_chars=200,
            max_message_parts=2,
        )
        huge_body = "paragraph text\n" * 500
        result = DigestResult(
            subscription_id="x",
            chat_id=1,
            title="huge",
            body_markdown=huge_body,
            docs_count=99,
            new_cursor=None,
            skipped=False,
        )
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        bot.send_document = AsyncMock()

        await service.deliver(bot, result)
        bot.send_message.assert_not_called()
        bot.send_document.assert_awaited_once()

    async def test_deliver_advances_cursor_only_after_success(self):
        update_mock = AsyncMock()
        doc = _make_processed_doc(
            channel_id="ch1",
            msg_id="1",
            processed_at=datetime(2026, 4, 18, 12, tzinfo=UTC),
        )
        service, _processed, _llm, _update = _make_service(
            docs_by_channel={"ch1": [doc]},
            sub_repo_update=update_mock,
        )
        sub = _make_subscription(
            channel_ids=["ch1"],
            last_digest_cursor=datetime(2026, 4, 17, tzinfo=UTC),
        )
        bot = AsyncMock()
        bot.send_message = AsyncMock()

        await service.run_for_subscription(sub, bot)
        update_mock.assert_awaited()
        kwargs = update_mock.await_args.kwargs
        assert kwargs.get("last_digest_cursor") == datetime(2026, 4, 18, 12, tzinfo=UTC)


# ----------------------------------------------------------------------------
# TestBotRuntime
# ----------------------------------------------------------------------------


class TestBotRuntime:
    """Process-local Bot singleton used by background tasks."""

    def setup_method(self):
        from tg_parser.bot.runtime import clear_bot

        clear_bot()

    def teardown_method(self):
        from tg_parser.bot.runtime import clear_bot

        clear_bot()

    def test_get_bot_returns_none_when_not_set(self):
        from tg_parser.bot.runtime import get_bot

        assert get_bot() is None

    def test_set_and_get_bot_round_trip(self):
        from tg_parser.bot.runtime import get_bot, set_bot

        sentinel = object()
        set_bot(sentinel)  # type: ignore[arg-type]
        assert get_bot() is sentinel

    def test_clear_bot_drops_reference(self):
        from tg_parser.bot.runtime import clear_bot, get_bot, set_bot

        set_bot(object())  # type: ignore[arg-type]
        clear_bot()
        assert get_bot() is None


# ----------------------------------------------------------------------------
# TestBotDigestTools
# ----------------------------------------------------------------------------


@pg_only
class TestBotDigestTools:
    """End-to-end exercise of the bot-tool executors against PostgreSQL."""

    async def test_subscribe_digest_persists_and_registers(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.bot.tools import _exec_subscribe_digest
        from tg_parser.services.background_scheduler import (
            get_registered_digest_subscription_ids,
            unregister_digest_subscription,
        )

        owner = await user_repo_for_digest.create_user("alice_bot")
        user = _make_current_user(owner.id, name=owner.name, role="admin")

        result = await _exec_subscribe_digest(
            {
                "name": "morning",
                "channel_ids": ["@durov"],
                "cron_expression": "0 9 * * *",
                "timezone": "Europe/Moscow",
                "format": "summary",
            },
            current_user=user,
            bot=None,
            chat_id=12345,
        )
        assert "subscription_id" in result, result
        sub_id = result["subscription_id"]

        # Persisted in DB (use existing repo fixture)
        persisted = await digest_repo.get(sub_id)
        assert persisted is not None
        assert persisted.name == "morning"
        assert persisted.channel_ids == ["durov"]

        assert sub_id in get_registered_digest_subscription_ids()
        unregister_digest_subscription(sub_id)

    async def test_subscribe_digest_validates_cron_expression(
        self,
        user_repo_for_digest,
    ):
        from tg_parser.bot.tools import _exec_subscribe_digest

        owner = await user_repo_for_digest.create_user("bob_bot")
        user = _make_current_user(owner.id, name=owner.name, role="admin")
        result = await _exec_subscribe_digest(
            {
                "name": "bad-cron",
                "channel_ids": ["@x"],
                "cron_expression": "this is not cron",
            },
            current_user=user,
            bot=None,
            chat_id=10,
        )
        assert "error" in result
        assert "cron" in result["error"].lower()

    async def test_subscribe_digest_rejects_unauthorized_channel(
        self,
        user_repo_for_digest,
    ):
        from tg_parser.bot.tools import _exec_subscribe_digest

        owner = await user_repo_for_digest.create_user("carol_bot")
        # Restricted user — only allowed to access "owned"
        user = _make_current_user(
            owner.id,
            name=owner.name,
            role="user",
            allowed_channel_ids={"owned"},
        )
        result = await _exec_subscribe_digest(
            {
                "name": "denied",
                "channel_ids": ["@forbidden"],
            },
            current_user=user,
            bot=None,
            chat_id=10,
        )
        assert "error" in result
        assert (
            "forbidden" in (result.get("channel_id") or "")
            or "no access" in result["error"].lower()
        )

    async def test_list_digests_non_admin_sees_only_owned(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.bot.tools import _exec_list_digests

        alice = await user_repo_for_digest.create_user("alice_list")
        bob = await user_repo_for_digest.create_user("bob_list")
        await digest_repo.create(_make_subscription(owner_id=alice.id, name="a"))
        await digest_repo.create(_make_subscription(owner_id=bob.id, name="b"))

        bob_user = _make_current_user(bob.id, name=bob.name, role="user", allowed_channel_ids=set())
        result = await _exec_list_digests({}, current_user=bob_user)
        names = {s["name"] for s in result["subscriptions"]}
        assert names == {"b"}

    async def test_list_digests_admin_sees_all(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.bot.tools import _exec_list_digests

        alice = await user_repo_for_digest.create_user("alice_listall")
        bob = await user_repo_for_digest.create_user("bob_listall")
        await digest_repo.create(_make_subscription(owner_id=alice.id, name="a"))
        b_sub = await digest_repo.create(_make_subscription(owner_id=bob.id, name="b"))
        await digest_repo.update(b_sub.id, is_active=False)

        admin = _make_current_user(alice.id, name="admin", role="admin")
        result = await _exec_list_digests({}, current_user=admin)
        assert result["count"] == 2
        names = {s["name"] for s in result["subscriptions"]}
        assert names == {"a", "b"}

    async def test_unsubscribe_digest_ownership_enforced(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.bot.tools import _exec_unsubscribe_digest

        alice = await user_repo_for_digest.create_user("alice_un")
        bob = await user_repo_for_digest.create_user("bob_un")
        sub = await digest_repo.create(_make_subscription(owner_id=alice.id))

        bob_user = _make_current_user(bob.id, name=bob.name, role="user", allowed_channel_ids=set())
        result = await _exec_unsubscribe_digest(
            {"subscription_id": sub.id},
            current_user=bob_user,
        )
        assert "error" in result
        # Owner can delete
        alice_user = _make_current_user(
            alice.id, name=alice.name, role="user", allowed_channel_ids=set()
        )
        ok = await _exec_unsubscribe_digest(
            {"subscription_id": sub.id},
            current_user=alice_user,
        )
        assert ok.get("deleted") is True


# ----------------------------------------------------------------------------
# TestMCPDigestTools
# ----------------------------------------------------------------------------


@pg_only
class TestMCPDigestTools:
    async def test_mcp_subscribe_digest_returns_subscription(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from unittest.mock import patch

        from tg_parser.mcp_server import subscribe_digest
        from tg_parser.services.background_scheduler import unregister_digest_subscription

        owner = await user_repo_for_digest.create_user("alice_mcp")
        user = _make_current_user(owner.id, name=owner.name, role="admin")

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await subscribe_digest(
                name="weekday",
                channel_ids=["@durov"],
                chat_id=99,
                cron_expression="0 9 * * 1-5",
                timezone="UTC",
            )
        assert result.success is True
        assert result.subscription is not None
        assert result.subscription.cron_expression == "0 9 * * 1-5"
        # Cleanup scheduler job to keep singleton clean
        unregister_digest_subscription(result.subscription.id)

    async def test_mcp_subscribe_digest_validates_cron(
        self,
        user_repo_for_digest,
    ):
        from unittest.mock import patch

        from tg_parser.mcp_server import subscribe_digest

        owner = await user_repo_for_digest.create_user("bob_mcp")
        user = _make_current_user(owner.id, name=owner.name, role="admin")

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await subscribe_digest(
                name="bad",
                channel_ids=["@x"],
                chat_id=1,
                cron_expression="garbage",
            )
        assert result.success is False
        assert "cron" in result.message.lower()

    async def test_mcp_subscribe_digest_channel_ownership_enforced(
        self,
        user_repo_for_digest,
    ):
        from unittest.mock import patch

        from tg_parser.mcp_server import subscribe_digest

        owner = await user_repo_for_digest.create_user("carol_mcp")
        user = _make_current_user(
            owner.id,
            name=owner.name,
            role="user",
            allowed_channel_ids={"only_this"},
        )
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await subscribe_digest(
                name="denied",
                channel_ids=["@forbidden"],
                chat_id=1,
            )
        assert result.success is False
        assert "forbidden" in result.message.lower() or "no access" in result.message.lower()

    async def test_mcp_list_digests_admin_sees_all(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from unittest.mock import patch

        from tg_parser.mcp_server import list_digests

        alice = await user_repo_for_digest.create_user("alice_mcp_list")
        bob = await user_repo_for_digest.create_user("bob_mcp_list")
        await digest_repo.create(_make_subscription(owner_id=alice.id, name="ml-a"))
        b_sub = await digest_repo.create(_make_subscription(owner_id=bob.id, name="ml-b"))
        await digest_repo.update(b_sub.id, is_active=False)

        admin = _make_current_user(alice.id, name="admin", role="admin")
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=admin)):
            result = await list_digests()
        names = {s.name for s in result.subscriptions}
        assert {"ml-a", "ml-b"} <= names

    async def test_mcp_unsubscribe_digest_returns_404_for_unknown_id(
        self,
        user_repo_for_digest,
    ):
        from unittest.mock import patch

        from tg_parser.mcp_server import unsubscribe_digest

        owner = await user_repo_for_digest.create_user("dora_mcp")
        user = _make_current_user(owner.id, name=owner.name, role="admin")

        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await unsubscribe_digest(
                subscription_id="00000000-0000-0000-0000-000000000000",
            )
        assert result.success is False
        assert "not found" in result.message.lower()


# ----------------------------------------------------------------------------
# TestSchedulerReconciliation
# ----------------------------------------------------------------------------


@pg_only
class TestSchedulerReconciliation:
    async def test_reconciliation_adds_new_subscriptions_without_restart(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.services.background_scheduler import (
            get_registered_digest_subscription_ids,
            unregister_digest_subscription,
        )
        from tg_parser.services.scheduler_service import reconcile_digest_subscriptions

        before = set(get_registered_digest_subscription_ids())
        owner = await user_repo_for_digest.create_user("alice_recon")
        sub = await digest_repo.create(_make_subscription(owner_id=owner.id, name="recon-add"))
        try:
            stats = await reconcile_digest_subscriptions()
            assert sub.id in stats["added"] or sub.id in get_registered_digest_subscription_ids()
            registered = get_registered_digest_subscription_ids()
            assert sub.id in registered
        finally:
            unregister_digest_subscription(sub.id)
            # Restore baseline (best-effort)
            for sid in get_registered_digest_subscription_ids() - before:
                unregister_digest_subscription(sid)

    async def test_reconciliation_removes_deleted_subscriptions(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.services.background_scheduler import (
            get_registered_digest_subscription_ids,
            register_digest_subscription,
            unregister_digest_subscription,
        )
        from tg_parser.services.scheduler_service import reconcile_digest_subscriptions

        owner = await user_repo_for_digest.create_user("bob_recon")
        sub = await digest_repo.create(_make_subscription(owner_id=owner.id, name="recon-rm"))
        register_digest_subscription(sub)
        assert sub.id in get_registered_digest_subscription_ids()

        # Drop from DB without unregistering scheduler job
        await digest_repo.delete(sub.id)
        try:
            stats = await reconcile_digest_subscriptions()
            assert (
                sub.id in stats["removed"] or sub.id not in get_registered_digest_subscription_ids()
            )
            assert sub.id not in get_registered_digest_subscription_ids()
        finally:
            unregister_digest_subscription(sub.id)


# ----------------------------------------------------------------------------
# TestRunScheduledDigestsTask (PG, integration)
# ----------------------------------------------------------------------------


@pg_only
class TestRunScheduledDigestsTask:
    async def test_run_returns_not_found_for_missing_subscription(self):
        from tg_parser.services.scheduler_service import run_scheduled_digests_task

        result = await run_scheduled_digests_task("00000000-0000-0000-0000-000000000000")
        assert result["status"] == "not_found"

    async def test_run_returns_inactive_for_paused_subscription(
        self,
        digest_repo,
        user_repo_for_digest,
    ):
        from tg_parser.services.scheduler_service import run_scheduled_digests_task

        owner = await user_repo_for_digest.create_user("alice_run")
        sub = await digest_repo.create(_make_subscription(owner_id=owner.id))
        await digest_repo.update(sub.id, is_active=False)
        result = await run_scheduled_digests_task(sub.id)
        assert result["status"] == "inactive"
