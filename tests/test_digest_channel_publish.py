"""Channel-target digest publish (ADR 0008 OQ#3).

Covers the three metric labels (`success` / `permission_denied` / `failed`),
soft-deactivation on permanent errors, owner fallback notification, and
chat-target propagation (chat targets must NOT soft-deactivate on send
failure — only channel targets do).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from tg_parser.domain.models import (
    DigestFormat,
    DigestSubscription,
    TargetKind,
)
from tg_parser.services.digest_service import (
    ChannelPublishPermissionDenied,
    DigestResult,
    DigestService,
)


def _make_channel_sub(
    *,
    sub_id: str = "sub-x",
    chat_id: int | None = 111,
    channel_id: str = "@mychan",
) -> DigestSubscription:
    return DigestSubscription(
        id=sub_id,
        owner_id="owner-1",
        target_kind=TargetKind.CHANNEL,
        chat_id=chat_id,
        channel_id=channel_id,
        name="n",
        channel_ids=["durov"],
        format=DigestFormat.SUMMARY,
    )


def _make_chat_sub(*, sub_id: str = "sub-chat") -> DigestSubscription:
    return DigestSubscription(
        id=sub_id,
        owner_id="owner-1",
        target_kind=TargetKind.CHAT,
        chat_id=42,
        channel_id=None,
        name="n",
        channel_ids=["durov"],
        format=DigestFormat.SUMMARY,
    )


def _make_result(*, sub: DigestSubscription) -> DigestResult:
    return DigestResult(
        subscription_id=sub.id,
        chat_id=sub.chat_id,
        title="t",
        body_markdown="body",
        docs_count=1,
        new_cursor=datetime.now(UTC),
        skipped=False,
    )


def _patch_metric(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []

    def _record(*, result: str) -> None:
        recorded.append(result)

    monkeypatch.setattr(
        "tg_parser.services.digest_service.record_digest_channel_publish",
        _record,
    )
    return recorded


# ----------------------------------------------------------------------------
# Success path
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_publish_success_increments_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_metric(monkeypatch)
    sub = _make_channel_sub(sub_id="sub-success", chat_id=None, channel_id="@pub")
    repo = AsyncMock()
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    await svc.deliver(bot, _make_result(sub=sub), sub)

    assert recorded == ["success"]
    bot.send_message.assert_awaited()
    assert bot.send_message.await_args.kwargs["chat_id"] == "@pub"
    repo.update.assert_not_called()


# ----------------------------------------------------------------------------
# Permission-denied path: parametrised across all permanent fragments
# ----------------------------------------------------------------------------


_PERMANENT_FRAGMENTS = [
    "chat not found",
    "bot was blocked",
    "user is deactivated",
    "forbidden: not enough rights",
    "not enough rights",
    "need administrator",
    "have no rights",
    "bot is not a member of the channel",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("fragment", _PERMANENT_FRAGMENTS)
async def test_channel_publish_permission_denied_soft_deactivates_for_each_fragment(
    monkeypatch: pytest.MonkeyPatch, fragment: str
) -> None:
    """Each known permanent fragment classifies as permission_denied and soft-deactivates."""
    recorded = _patch_metric(monkeypatch)
    sub = _make_channel_sub(sub_id=f"sub-{hash(fragment)}", chat_id=None)
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=sub)
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=Exception(fragment))

    with pytest.raises(ChannelPublishPermissionDenied):
        await svc.deliver(bot, _make_result(sub=sub), sub)

    assert recorded == ["permission_denied"]
    repo.update.assert_awaited_once()
    assert repo.update.await_args.kwargs.get("is_active") is False


@pytest.mark.asyncio
async def test_channel_publish_permission_denied_sends_fallback_notification_to_owner_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When sub.chat_id is set, bot must DM the owner that the digest deactivated."""
    _patch_metric(monkeypatch)
    sub = _make_channel_sub(sub_id="sub-fallback", chat_id=999, channel_id="@dead")
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=sub)
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock(
        side_effect=[Exception("bot is not a member of the channel"), None]
    )

    with pytest.raises(ChannelPublishPermissionDenied):
        await svc.deliver(bot, _make_result(sub=sub), sub)

    assert bot.send_message.await_count == 2
    first_call_kwargs = bot.send_message.await_args_list[0].kwargs
    fallback_kwargs = bot.send_message.await_args_list[1].kwargs
    assert first_call_kwargs["chat_id"] == "@dead"
    assert fallback_kwargs["chat_id"] == 999
    text = fallback_kwargs["text"]
    assert "deactivated" in text.lower()
    assert "@dead" in text


@pytest.mark.asyncio
async def test_channel_publish_permission_denied_no_fallback_when_chat_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If sub.chat_id is None we silently skip the owner notice (no second send)."""
    _patch_metric(monkeypatch)
    sub = _make_channel_sub(sub_id="sub-no-fb", chat_id=None, channel_id="@dead2")
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=sub)
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=Exception("forbidden: bot was kicked"))

    with pytest.raises(ChannelPublishPermissionDenied):
        await svc.deliver(bot, _make_result(sub=sub), sub)

    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_channel_publish_fallback_notice_swallows_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the fallback DM itself fails (e.g. owner blocked the bot), we still raise
    ``ChannelPublishPermissionDenied`` for the original cause and don't leak the
    secondary exception."""
    _patch_metric(monkeypatch)
    sub = _make_channel_sub(sub_id="sub-fb-fail", chat_id=999)
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=sub)
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock(
        side_effect=[
            Exception("not enough rights"),
            Exception("user blocked the bot"),
        ]
    )

    with pytest.raises(ChannelPublishPermissionDenied) as excinfo:
        await svc.deliver(bot, _make_result(sub=sub), sub)

    assert "not enough rights" in str(excinfo.value).lower()
    assert bot.send_message.await_count == 2


# ----------------------------------------------------------------------------
# Transient (non-permanent) failure: result="failed", reraised, NO soft-deactivate
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_publish_transient_failure_records_failed_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _patch_metric(monkeypatch)
    sub = _make_channel_sub(sub_id="sub-transient", chat_id=None)
    repo = AsyncMock()
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()

    transient = TimeoutError("upstream Telegram timeout")
    bot.send_message = AsyncMock(side_effect=transient)

    with pytest.raises(TimeoutError):
        await svc.deliver(bot, _make_result(sub=sub), sub)

    assert recorded == ["failed"]
    repo.update.assert_not_called()


# ----------------------------------------------------------------------------
# Chat-target propagation: failures bubble up unchanged, no metric, no deactivate
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_target_send_failure_propagates_without_soft_deactivate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat targets retain pre-ADR-0008 behaviour — exception escapes for the
    scheduler to retry, no metric, no deactivation, no fallback notice."""
    recorded = _patch_metric(monkeypatch)
    sub = _make_chat_sub()
    repo = AsyncMock()
    svc = DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("transient chat error"))

    with pytest.raises(RuntimeError, match="transient chat error"):
        await svc.deliver(bot, _make_result(sub=sub), sub)

    assert recorded == []
    repo.update.assert_not_called()
