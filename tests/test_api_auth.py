"""HTTP API authentication (``tg_parser/api/auth.py``).

This module was carrying zero direct tests while being a live FastAPI
dependency: ``resolve_current_user`` is wired via ``Depends`` into the
watchlists and users routes. Filed under `technical-debt-roadmap.md` § 6
("api/auth.py + rate-limit middleware — security middleware").

What is pinned here, and why these things rather than line coverage:

* **Credential redaction.** ``_redacted_key_prefix`` is the only thing standing
  between a rejected API key and the log pipeline. BUG-087 and BUG-088 were both
  exactly this class — a bot log site writing a secret verbatim — so the
  invariant "a rejected key never appears whole in a log field" gets pinned at
  the source rather than trusted.
* **The 401/403 split.** "No key while keys are required" and "key present but
  wrong" are different answers to a client, and swapping them is the kind of
  regression nothing else would notice.
* **The audit trail on rejection.** ``record_audit_event`` firing on a bad key is
  a security control; without a test, deleting the call is invisible.
* **``get_optional_user`` never raising.** Its docstring promises it, and callers
  rely on it, but nothing enforced it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from tg_parser.api.auth import (
    _redacted_key_prefix,
    get_optional_user,
    resolve_current_user,
    verify_api_key,
)
from tg_parser.auth.models import CurrentUser

_AUTH = "tg_parser.api.auth"


def _user(name: str = "alice") -> CurrentUser:
    return CurrentUser(
        id="u1",
        name=name,
        role="user",
        allowed_channel_ids=["tg:chan"],
        max_channels=5,
    )


class TestRedactedKeyPrefix:
    """The rejected key must never reach a log field whole."""

    def test_long_key_keeps_only_four_leading_chars(self):
        assert _redacted_key_prefix("sk-abcdefghijklmnop") == "sk-a****"

    def test_short_key_is_fully_masked(self):
        # Below the prefix floor even four characters would be a large fraction
        # of the secret, so nothing is revealed at all.
        assert _redacted_key_prefix("short") == "****"

    def test_boundary_exactly_at_the_floor_reveals_prefix(self):
        assert _redacted_key_prefix("12345678") == "1234****"
        assert _redacted_key_prefix("1234567") == "****"

    @pytest.mark.parametrize(
        "secret",
        ["sk-live-DEADBEEFCAFE", "0123456789abcdef", "short", "", "x"],
    )
    def test_output_never_contains_the_tail_of_the_secret(self, secret):
        """The property, not the format: whatever the shape, the part that makes
        the key a secret must not survive redaction."""
        out = _redacted_key_prefix(secret)
        tail = secret[4:]
        if tail:
            assert tail not in out


class TestResolveCurrentUser:
    @pytest.mark.asyncio
    async def test_no_key_and_not_required_yields_default_admin(self):
        admin = CurrentUser(
            id="admin", name="admin", role="admin", allowed_channel_ids=None, max_channels=99
        )
        with (
            patch(f"{_AUTH}.settings") as st,
            patch(f"{_AUTH}.get_default_admin", AsyncMock(return_value=admin)),
        ):
            st.api_key_required = False
            assert await resolve_current_user(api_key=None) is admin

    @pytest.mark.asyncio
    async def test_no_key_while_required_is_401_not_403(self):
        """401 means 'authenticate', 403 means 'you may not' — a client retries
        on one and gives up on the other."""
        with patch(f"{_AUTH}.settings") as st:
            st.api_key_required = True
            with pytest.raises(HTTPException) as exc:
                await resolve_current_user(api_key=None)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_key_mapped_to_db_user_returns_that_user(self):
        user = _user()
        with (
            patch(f"{_AUTH}.settings") as st,
            patch(f"{_AUTH}.hash_credential", return_value="hashed"),
            patch(f"{_AUTH}.resolve_user_by_auth", AsyncMock(return_value=user)) as resolve,
        ):
            st.api_keys = {"good-key": "client"}
            assert await resolve_current_user(api_key="good-key") is user
        resolve.assert_awaited_once_with("api_key", "hashed")

    @pytest.mark.asyncio
    async def test_valid_key_without_db_mapping_falls_back_to_admin(self):
        admin = CurrentUser(
            id="admin", name="admin", role="admin", allowed_channel_ids=None, max_channels=99
        )
        with (
            patch(f"{_AUTH}.settings") as st,
            patch(f"{_AUTH}.hash_credential", return_value="hashed"),
            patch(f"{_AUTH}.resolve_user_by_auth", AsyncMock(return_value=None)),
            patch(f"{_AUTH}.get_default_admin", AsyncMock(return_value=admin)),
        ):
            st.api_keys = {"good-key": "client"}
            assert await resolve_current_user(api_key="good-key") is admin

    @pytest.mark.asyncio
    async def test_unknown_key_still_resolves_as_forwarded_mcp_token(self):
        """ADR-0007: MCP forwards its bearer, which is absent from API_KEYS but
        valid in the DB. Losing this path would break the whole MCP surface
        while every API_KEYS-based test stayed green."""
        user = _user("mcp-user")
        with (
            patch(f"{_AUTH}.settings") as st,
            patch(f"{_AUTH}.hash_credential", return_value="hashed"),
            patch(f"{_AUTH}.resolve_user_by_auth", AsyncMock(return_value=user)) as resolve,
        ):
            st.api_keys = {}
            assert await resolve_current_user(api_key="mcp-bearer") is user
        resolve.assert_awaited_once_with("mcp_token", "hashed")

    @pytest.mark.asyncio
    async def test_invalid_key_is_403_and_audited_without_leaking_the_key(self):
        audit = AsyncMock()
        with (
            patch(f"{_AUTH}.settings") as st,
            patch(f"{_AUTH}.hash_credential", return_value="hashed"),
            patch(f"{_AUTH}.resolve_user_by_auth", AsyncMock(return_value=None)),
            patch("tg_parser.auth.audit.record_audit_event", audit),
        ):
            st.api_keys = {}
            with pytest.raises(HTTPException) as exc:
                await resolve_current_user(api_key="sk-secret-value-123")

        assert exc.value.status_code == 403
        audit.assert_awaited_once()
        meta = audit.await_args.kwargs["meta"]
        assert meta["key_prefix"] == "sk-s****"
        # The whole point: the audit record must not carry the secret.
        assert "secret-value-123" not in str(meta)


class TestVerifyApiKeyLegacy:
    @pytest.mark.asyncio
    async def test_no_key_and_not_required_returns_none(self):
        with patch(f"{_AUTH}.settings") as st:
            st.api_key_required = False
            assert await verify_api_key(api_key=None) is None

    @pytest.mark.asyncio
    async def test_no_key_while_required_is_401(self):
        with patch(f"{_AUTH}.settings") as st:
            st.api_key_required = True
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(api_key=None)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_known_key_returns_its_client_name(self):
        with patch(f"{_AUTH}.settings") as st:
            st.api_key_required = True
            st.api_keys = {"k": "grafana"}
            assert await verify_api_key(api_key="k") == "grafana"

    @pytest.mark.asyncio
    async def test_unknown_key_is_403_and_audited_redacted(self):
        audit = AsyncMock()
        with (
            patch(f"{_AUTH}.settings") as st,
            patch("tg_parser.auth.audit.record_audit_event", audit),
        ):
            st.api_key_required = True
            st.api_keys = {"k": "grafana"}
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(api_key="sk-nope-abcdef")

        assert exc.value.status_code == 403
        assert audit.await_args.kwargs["meta"]["key_prefix"] == "sk-n****"


class TestGetOptionalUser:
    """Documented contract: returns a user or None, and NEVER raises."""

    @pytest.mark.asyncio
    async def test_no_key_returns_none(self):
        assert await get_optional_user(api_key=None) is None

    @pytest.mark.asyncio
    async def test_unknown_key_returns_none_rather_than_403(self):
        with patch(f"{_AUTH}.settings") as st:
            st.api_keys = {}
            assert await get_optional_user(api_key="nope") is None

    @pytest.mark.asyncio
    async def test_known_key_returns_the_resolved_user(self):
        user = _user()
        with (
            patch(f"{_AUTH}.settings") as st,
            patch(f"{_AUTH}.hash_credential", return_value="hashed"),
            patch(f"{_AUTH}.resolve_user_by_auth", AsyncMock(return_value=user)),
        ):
            st.api_keys = {"k": "client"}
            assert await get_optional_user(api_key="k") is user
