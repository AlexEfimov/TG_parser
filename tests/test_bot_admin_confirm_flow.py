"""TD-bot-confirm-coverage-completeness — ConfirmFlow contract for the admin write quartet.

The admin write-tool quartet — ``register_user`` / ``update_user`` /
``add_user_auth`` / ``remove_user_auth`` — were the last write surface
OUTSIDE the deterministic two-phase preview/confirm contract. Pre-fix they
carried no ``confirm: BOOLEAN`` parameter and mutated the user / auth-mapping
store on the LLM's first call, so an admin's «да» never armed ConfirmFlow and
the destructive create/update/revoke ran with no preview turn.

This module pins the closure with ONE parametrized family across all four
tools covering the SHARED contract (mirrors ``tests/test_bot_confirm_flow.py``
for the subscribe surface):

1. **preview-does-not-mutate** — a call WITHOUT ``confirm=True`` returns
   ``{"preview": True, ...}`` and touches NOTHING in the repo.
2. **confirm-mutates** — the framework-replayed call with ``confirm=True``
   (paired with a matching ``confirm_flow_state`` snapshot) commits exactly
   the intended mutation.
3. **BUG-009 mismatch-reject** — an LLM-issued ``confirm=True`` WITHOUT a
   matching FSM snapshot is rejected server-side with
   ``error_class="ConfirmFlowMismatch"`` and the executor never runs.

Plus per-tool preview-payload assertions (each tool's preview names its own
fields/consequences) and the membership/declaration contract pins.

Cross-references:
- ``docs/notes/BUG_LOG.md`` § TD-bot-confirm-coverage-completeness,
  § BUG-009 (server-side guard), § BUG-031 / § BUG-046 (subscribe / unsubscribe
  precedents this mirrors)
- ``tests/test_bot_execute_tool_guard.py`` (bidirectional contract + baseline)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import (
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    TOOL_DECLARATIONS,
    execute_tool,
)

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-admin-confirm") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="adminconfirm",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _non_admin(user_id: str = "user-plain") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="plain",
        role="user",
        allowed_channel_ids=[],
        max_channels=1,
    )


@dataclass
class _FakeUserRepo:
    """In-memory fake mirroring the UserRepo surface the admin executors touch.

    Records every mutating call so a test can assert ``total_mutations() == 0``
    on the preview turn (the canonical TD regression).
    """

    created: list[Any] = field(default_factory=list)
    updated: list[tuple[Any, ...]] = field(default_factory=list)
    added_auth: list[tuple[Any, ...]] = field(default_factory=list)
    removed_auth: list[str] = field(default_factory=list)

    async def create_user(
        self,
        name: str,
        role: str = "user",
        max_channels: int | None = None,
    ) -> Any:
        new = SimpleNamespace(id="new-user-id", name=name, role=role, max_channels=max_channels)
        self.created.append(new)
        return new

    async def update_user(
        self,
        user_id: str,
        name: str | None = None,
        role: str | None = None,
        max_channels: Any = ...,
    ) -> Any:
        self.updated.append((user_id, name, role, max_channels))
        return SimpleNamespace(
            id=user_id,
            name=name or "existing-name",
            role=role or "user",
        )

    async def add_auth_mapping(
        self,
        user_id: str,
        auth_type: str,
        stored: str,
        client_name: str | None = None,
    ) -> Any:
        self.added_auth.append((user_id, auth_type, stored, client_name))
        return SimpleNamespace(id="new-mapping-id", auth_type=auth_type)

    async def remove_auth_mapping(self, mapping_id: str) -> bool:
        self.removed_auth.append(mapping_id)
        return True

    def total_mutations(self) -> int:
        return len(self.created) + len(self.updated) + len(self.added_auth) + len(self.removed_auth)


@asynccontextmanager
async def _user_repo_ctx(repo: _FakeUserRepo):
    yield (repo, None)


def _patch_admin_executor(repo: _FakeUserRepo):
    """Patch the DB + auth side-effects the admin executors reach for.

    ``hash_credential`` / ``invalidate_user_cache`` are stubbed so
    ``add_user_auth`` is deterministic and never touches a real cache.
    """
    return [
        patch(
            "tg_parser.services.db_context.user_repo",
            lambda: _user_repo_ctx(repo),
        ),
        patch(
            "tg_parser.auth.resolvers.hash_credential",
            lambda value: f"hashed::{value}",
        ),
        patch(
            "tg_parser.auth.resolvers.invalidate_user_cache",
            lambda *_a, **_kw: None,
        ),
    ]


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Parametrized matrix — base args (WITHOUT confirm) + a mutation-counter probe
# ---------------------------------------------------------------------------


def _register_count(repo: _FakeUserRepo) -> int:
    return len(repo.created)


def _update_count(repo: _FakeUserRepo) -> int:
    return len(repo.updated)


def _add_auth_count(repo: _FakeUserRepo) -> int:
    return len(repo.added_auth)


def _remove_auth_count(repo: _FakeUserRepo) -> int:
    return len(repo.removed_auth)


ADMIN_TOOL_CASES = [
    pytest.param(
        "register_user",
        {"name": "Alice", "role": "admin", "max_channels": 5},
        _register_count,
        id="register_user",
    ),
    pytest.param(
        "update_user",
        {"user_id": "u-123", "name": "Bob", "role": "user"},
        _update_count,
        id="update_user",
    ),
    pytest.param(
        "add_user_auth",
        {"user_id": "u-123", "auth_type": "api_key", "identifier": "s3cr3t-raw-key"},
        _add_auth_count,
        id="add_user_auth",
    ),
    pytest.param(
        "remove_user_auth",
        {"mapping_id": "m-789"},
        _remove_auth_count,
        id="remove_user_auth",
    ),
]


# ===========================================================================
# 1. Shared contract — preview / confirm / BUG-009 mismatch (parametrized)
# ===========================================================================


@pytest.mark.asyncio
class TestAdminQuartetConfirmContract:
    """The SHARED two-phase contract across all four admin write tools."""

    @pytest.mark.parametrize("tool_name,base_args,counter", ADMIN_TOOL_CASES)
    async def test_preview_call_does_not_mutate(
        self, tool_name: str, base_args: dict[str, Any], counter
    ) -> None:
        """A call WITHOUT confirm returns preview=True and mutates nothing."""
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            result = await execute_tool(
                tool_name,
                dict(base_args),  # confirm intentionally omitted
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True, result
        assert result["tool"] == tool_name
        # The canonical TD regression: nothing persisted on the preview turn.
        assert counter(repo) == 0
        assert repo.total_mutations() == 0

    @pytest.mark.parametrize("tool_name,base_args,counter", ADMIN_TOOL_CASES)
    async def test_explicit_confirm_false_does_not_mutate(
        self, tool_name: str, base_args: dict[str, Any], counter
    ) -> None:
        """Explicit confirm=False is identical to omission — no write sneaks through."""
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            result = await execute_tool(
                tool_name,
                {**base_args, "confirm": False},
                current_user=_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert repo.total_mutations() == 0

    @pytest.mark.parametrize("tool_name,base_args,counter", ADMIN_TOOL_CASES)
    async def test_confirm_true_with_matching_snapshot_mutates(
        self, tool_name: str, base_args: dict[str, Any], counter
    ) -> None:
        """The framework-replayed confirm=True (paired with a matching FSM
        snapshot) commits exactly the intended mutation."""
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            result = await execute_tool(
                tool_name,
                {**base_args, "confirm": True},
                current_user=_admin(),
                confirm_flow_state={"tool_name": tool_name, "args": dict(base_args)},
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is not True
        assert "error" not in result, result
        assert counter(repo) == 1
        assert repo.total_mutations() == 1

    @pytest.mark.parametrize("tool_name,base_args,counter", ADMIN_TOOL_CASES)
    async def test_llm_issued_confirm_true_without_state_rejected(
        self, tool_name: str, base_args: dict[str, Any], counter
    ) -> None:
        """BUG-009: an LLM-issued confirm=True with no matching FSM snapshot
        is rejected server-side and the executor never runs (nothing mutates)."""
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            result = await execute_tool(
                tool_name,
                {**base_args, "confirm": True},
                current_user=_admin(),
                confirm_flow_state=None,
            )
        finally:
            _exit_all(patches)

        assert result.get("error_class") == "ConfirmFlowMismatch", result
        assert "BUG-009" in result["error"]
        assert repo.total_mutations() == 0

    @pytest.mark.parametrize("tool_name,base_args,counter", ADMIN_TOOL_CASES)
    async def test_confirm_true_with_changed_args_rejected(
        self, tool_name: str, base_args: dict[str, Any], counter
    ) -> None:
        """BUG-009: a confirm=True whose args drift from the snapshot is
        rejected (closes the injected-arg attack vector)."""
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            result = await execute_tool(
                tool_name,
                {**base_args, "confirm": True},
                current_user=_admin(),
                # Snapshot args deliberately differ (extra injected key).
                confirm_flow_state={
                    "tool_name": tool_name,
                    "args": {**base_args, "injected": "evil"},
                },
            )
        finally:
            _exit_all(patches)

        assert result.get("error_class") == "ConfirmFlowMismatch", result
        assert repo.total_mutations() == 0

    @pytest.mark.parametrize("tool_name,base_args,counter", ADMIN_TOOL_CASES)
    async def test_non_admin_rejected_even_on_preview(
        self, tool_name: str, base_args: dict[str, Any], counter
    ) -> None:
        """The admin permission check runs FIRST — a non-admin is rejected on
        the preview turn (no preview leaked, nothing mutated)."""
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            result = await execute_tool(
                tool_name,
                dict(base_args),
                current_user=_non_admin(),
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is not True
        assert "error" in result
        assert repo.total_mutations() == 0


# ===========================================================================
# 2. Per-tool preview payloads — each tool names its own fields/consequences
# ===========================================================================


@pytest.mark.asyncio
class TestAdminQuartetPreviewPayloads:
    """The preview text is PER-TOOL (locked decision 2): each tool surfaces
    its own concrete fields so the operator can verify before confirming."""

    async def _preview(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        repo = _FakeUserRepo()
        patches = _patch_admin_executor(repo)
        _enter_all(patches)
        try:
            return await execute_tool(tool_name, dict(args), current_user=_admin())
        finally:
            _exit_all(patches)

    async def test_register_user_preview_names_role_and_limit(self) -> None:
        result = await self._preview(
            "register_user", {"name": "Alice", "role": "admin", "max_channels": 5}
        )
        assert result["preview"] is True
        assert result["tool"] == "register_user"
        assert result["name"] == "Alice"
        assert result["role"] == "admin"
        assert result["max_channels"] == 5
        assert result["user_facing_message"] is True
        assert "Alice" in result["message"]
        assert "admin" in result["message"]
        assert "5" in result["message"]
        assert "Подтвердите" in result["message"]
        assert "[да/нет]" in result["message"]

    async def test_register_user_preview_default_limit_phrase(self) -> None:
        result = await self._preview("register_user", {"name": "Carol"})
        assert result["preview"] is True
        assert result["max_channels"] is None
        assert "по умолчанию" in result["message"]

    async def test_update_user_preview_enumerates_changed_fields(self) -> None:
        result = await self._preview(
            "update_user",
            {"user_id": "u-123", "name": "Bob", "role": "admin"},
        )
        assert result["preview"] is True
        assert result["tool"] == "update_user"
        assert result["user_id"] == "u-123"
        assert "имя" in result["message"]
        assert "Bob" in result["message"]
        assert "роль" in result["message"]
        assert "admin" in result["message"]
        assert "u-123" in result["message"]
        assert set(result["changed_fields"]) and len(result["changed_fields"]) == 2

    async def test_update_user_preview_reset_limit(self) -> None:
        result = await self._preview(
            "update_user",
            {"user_id": "u-123", "reset_max_channels": True},
        )
        assert result["preview"] is True
        assert result["reset_max_channels"] is True
        assert "по умолчанию" in result["message"]

    async def test_add_user_auth_preview_names_type_not_secret(self) -> None:
        result = await self._preview(
            "add_user_auth",
            {
                "user_id": "u-123",
                "auth_type": "api_key",
                "identifier": "s3cr3t-raw-key",
                "client_name": "cli",
            },
        )
        assert result["preview"] is True
        assert result["tool"] == "add_user_auth"
        assert result["auth_type"] == "api_key"
        assert result["user_id"] == "u-123"
        assert "api_key" in result["message"]
        assert "u-123" in result["message"]
        assert "cli" in result["message"]
        # Privacy invariant — the raw credential MUST NOT appear in the preview.
        assert "s3cr3t-raw-key" not in result["message"]
        assert "identifier" not in result

    async def test_remove_user_auth_preview_names_mapping(self) -> None:
        result = await self._preview("remove_user_auth", {"mapping_id": "m-789"})
        assert result["preview"] is True
        assert result["tool"] == "remove_user_auth"
        assert result["mapping_id"] == "m-789"
        assert "m-789" in result["message"]
        assert "Подтвердите" in result["message"]


# ===========================================================================
# 3. Contract pins — declaration confirm-param ↔ guard-set membership
# ===========================================================================


def _declared_params(tool_name: str) -> set[str]:
    for tool in TOOL_DECLARATIONS:
        if tool.get("name") == tool_name:
            return set(tool.get("parameters", {}).get("properties", {}).keys())
    raise AssertionError(f"tool {tool_name!r} not found in TOOL_DECLARATIONS")


class TestAdminQuartetContractMembership:
    """Explicit pins for the TD addition so a future refactor that strips
    either side (declaration confirm-param OR guard-set membership) surfaces
    immediately rather than silently re-opening the gap."""

    @pytest.mark.parametrize(
        "tool_name",
        ["register_user", "update_user", "add_user_auth", "remove_user_auth"],
    )
    def test_admin_tool_in_guard_set(self, tool_name: str) -> None:
        assert tool_name in _WRITE_TOOLS_REQUIRING_CONFIRM, (
            f"TD-bot-confirm-coverage-completeness regression — {tool_name} "
            "dropped from _WRITE_TOOLS_REQUIRING_CONFIRM; the server-side guard "
            "will stop rejecting LLM-issued confirm=true."
        )

    @pytest.mark.parametrize(
        "tool_name",
        ["register_user", "update_user", "add_user_auth", "remove_user_auth"],
    )
    def test_admin_tool_declares_confirm_param(self, tool_name: str) -> None:
        assert "confirm" in _declared_params(tool_name), (
            f"TD-bot-confirm-coverage-completeness regression — {tool_name} "
            "lost its confirm BOOLEAN parameter in TOOL_DECLARATIONS."
        )
