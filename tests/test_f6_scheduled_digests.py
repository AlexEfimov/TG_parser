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
from tg_parser.storage.sqlalchemy import init_ingestion_state_schema
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
    sub_id: str = "00000000-0000-0000-0000-0000000000aa",
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
    return DigestSubscription(
        id=sub_id,
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
    ingestion_repo = MagicMock()
    loader = PromptLoader(prompts_dir=PROMPTS_DIR)
    factory: Callable = lambda: llm  # noqa: E731
    service = DigestService(
        processed_repo=processed,
        ingestion_repo=ingestion_repo,
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
    """Ensure F4 + F6 schema present, then truncate digest_subscriptions."""
    await init_ingestion_state_schema(test_db.ingestion_state_engine)
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
        sub = _make_subscription(
            sub_id="00000000-0000-0000-0000-000000000000",  # ignored by INSERT
            owner_id=owner.id,
            channel_ids=["@durov", "@telegram"],
        )
        created = await digest_repo.create(sub)
        assert created.id and created.id != sub.id  # server-assigned UUID
        assert created.owner_id == owner.id
        assert created.channel_ids == ["@durov", "@telegram"]
        assert created.is_active is True
        # idempotent get
        fetched = await digest_repo.get(created.id)
        assert fetched is not None
        assert fetched.name == sub.name

    async def test_get_returns_none_for_unknown_id(self, digest_repo):
        result = await digest_repo.get("00000000-0000-0000-0000-000000000000")
        assert result is None

    async def test_update_partial_fields_preserves_others(
        self, digest_repo, user_repo_for_digest
    ):
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

    async def test_list_by_owner_filters_correctly(
        self, digest_repo, user_repo_for_digest
    ):
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

    async def test_list_active_excludes_paused(
        self, digest_repo, user_repo_for_digest
    ):
        owner = await user_repo_for_digest.create_user("dora")
        active = await digest_repo.create(
            _make_subscription(owner_id=owner.id, name="active")
        )
        paused = await digest_repo.create(
            _make_subscription(owner_id=owner.id, name="paused")
        )
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
                processed_at=datetime(2026, 4, 18, 10, i % 60, tzinfo=UTC)
                + timedelta(minutes=i),
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
        service, _processed, _llm, _update = _make_service(
            docs_by_channel={"ch1": [doc1, doc2]}
        )
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
        sub = _make_subscription(
            channel_ids=["ch1"], last_digest_cursor=cursor_time
        )
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
        sub = _make_subscription(
            channel_ids=["ch1"], last_digest_cursor=None
        )
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
