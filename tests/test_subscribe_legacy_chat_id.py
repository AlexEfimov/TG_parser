"""Backward-compat: legacy chat_id-only subscribe paths (ADR 0008).

These tests pin the *resolution layer* shared by all four surfaces (HTTP, MCP,
Bot, CLI). Each surface has its own targeted suite — see ``test_api_digests.py``
/ ``test_api_watchlists.py`` (HTTP), ``test_mcp_*.py`` (MCP), the Bot tools
suites, and ``test_cli_*`` for CLI — but every surface ultimately funnels
through :func:`resolve_subscription_target`, so a regression here would break
all of them simultaneously.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tg_parser.domain.models import (
    DigestFormat,
    DigestSubscription,
    SubscriptionTargetConflictError,
    TargetChannel,
    TargetChat,
    TargetKind,
    WatchInterest,
    resolve_subscription_target,
    storage_fields_from_target,
    subscription_target_from_digest,
    subscription_target_from_watch,
    target_to_api_dict,
    telegram_address_from_target,
)

# ----------------------------------------------------------------------------
# resolve_subscription_target — happy paths + edges
# ----------------------------------------------------------------------------


def test_resolve_legacy_chat_id_wraps_target_chat() -> None:
    t = resolve_subscription_target(chat_id=999)
    assert isinstance(t, TargetChat)
    assert t.chat_id == 999
    assert t.kind == "chat"


def test_resolve_explicit_target_channel_dict() -> None:
    t = resolve_subscription_target(target={"kind": "channel", "channel_id": "@x"})
    assert isinstance(t, TargetChannel)
    assert t.kind == "channel"
    assert storage_fields_from_target(t)["target_kind"] == TargetKind.CHANNEL


def test_resolve_target_chat_instance_passthrough() -> None:
    """Pre-validated TargetChat instance is returned as-is (no re-validation cost)."""
    inst = TargetChat(chat_id=5)
    out = resolve_subscription_target(target=inst)
    assert out is inst


def test_resolve_target_channel_instance_passthrough() -> None:
    inst = TargetChannel(channel_id="@yo")
    out = resolve_subscription_target(target=inst)
    assert out is inst


def test_mutual_exclusion_raises_subscription_target_conflict() -> None:
    with pytest.raises(SubscriptionTargetConflictError):
        resolve_subscription_target(chat_id=1, target={"kind": "chat", "chat_id": 2})


def test_resolve_neither_chat_id_nor_target_raises() -> None:
    with pytest.raises(ValueError, match="either chat_id or target is required"):
        resolve_subscription_target()


@pytest.mark.parametrize(
    "bad_target",
    [
        {"kind": "webhook", "url": "https://x"},
        {"kind": "channel", "channel_id": ""},
        {"kind": "chat"},
        {"channel_id": "@x"},
    ],
)
def test_resolve_invalid_target_dict_raises(bad_target: dict) -> None:
    with pytest.raises(ValidationError):
        resolve_subscription_target(target=bad_target)


# ----------------------------------------------------------------------------
# storage_fields_from_target — chat vs channel symmetry
# ----------------------------------------------------------------------------


def test_storage_fields_chat_zeroes_channel_id() -> None:
    fields = storage_fields_from_target(TargetChat(chat_id=42))
    assert fields == {"target_kind": TargetKind.CHAT, "chat_id": 42, "channel_id": None}


def test_storage_fields_channel_zeroes_chat_id() -> None:
    fields = storage_fields_from_target(TargetChannel(channel_id="@cn"))
    assert fields == {"target_kind": TargetKind.CHANNEL, "chat_id": None, "channel_id": "@cn"}


def test_telegram_address_from_target() -> None:
    assert telegram_address_from_target(TargetChat(chat_id=7)) == 7
    assert telegram_address_from_target(TargetChannel(channel_id="@k")) == "@k"


# ----------------------------------------------------------------------------
# Round-trip — target_to_api_dict reflects DB storage exactly
# ----------------------------------------------------------------------------


def test_digest_round_trip_chat_target() -> None:
    sub = DigestSubscription(
        id="00000000-0000-0000-0000-000000000001",
        owner_id="00000000-0000-0000-0000-000000000002",
        target_kind=TargetKind.CHAT,
        chat_id=12345,
        channel_id=None,
        name="daily",
        channel_ids=["durov"],
        format=DigestFormat.SUMMARY,
    )
    api = target_to_api_dict(subscription_target_from_digest(sub))
    assert api == {"kind": "chat", "chat_id": 12345}


def test_digest_round_trip_channel_target() -> None:
    sub = DigestSubscription(
        id="00000000-0000-0000-0000-000000000003",
        owner_id="00000000-0000-0000-0000-000000000002",
        target_kind=TargetKind.CHANNEL,
        chat_id=None,
        channel_id="@daily",
        name="daily",
        channel_ids=["durov"],
        format=DigestFormat.SUMMARY,
    )
    api = target_to_api_dict(subscription_target_from_digest(sub))
    assert api == {"kind": "channel", "channel_id": "@daily"}


def test_watch_round_trip_chat_target() -> None:
    interest = WatchInterest(
        id="00000000-0000-0000-0000-000000000010",
        user_id="00000000-0000-0000-0000-000000000020",
        target_kind=TargetKind.CHAT,
        chat_id=42,
        channel_id=None,
        title="cap markets",
        channel_ids=["fin_news"],
    )
    api = target_to_api_dict(subscription_target_from_watch(interest))
    assert api == {"kind": "chat", "chat_id": 42}


def test_watch_round_trip_channel_target() -> None:
    interest = WatchInterest(
        id="00000000-0000-0000-0000-000000000011",
        user_id="00000000-0000-0000-0000-000000000020",
        target_kind=TargetKind.CHANNEL,
        chat_id=None,
        channel_id="@regwatch",
        title="cap markets",
        channel_ids=["fin_news"],
    )
    api = target_to_api_dict(subscription_target_from_watch(interest))
    assert api == {"kind": "channel", "channel_id": "@regwatch"}


def test_subscription_target_from_digest_unresolvable_raises() -> None:
    """target_kind=channel + missing channel_id is data-integrity violation."""
    sub = DigestSubscription(
        id="00000000-0000-0000-0000-000000000099",
        owner_id="00000000-0000-0000-0000-000000000002",
        target_kind=TargetKind.CHANNEL,
        chat_id=None,
        channel_id=None,
        name="broken",
        channel_ids=["durov"],
        format=DigestFormat.SUMMARY,
    )
    with pytest.raises(ValueError, match="no resolvable delivery target"):
        subscription_target_from_digest(sub)
