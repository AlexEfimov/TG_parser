"""
Тесты admin-утилиты выдачи тестового доступа (`scripts/onboard_test_users.py`).

Сеть не трогаем: MCP-клиент подменяется фейком, проверяются чистые помощники
(токены, ledger, шаблон приглашения, разбор ответов MCP) и склейка `issue_one`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.onboard_test_users import (  # noqa: E402
    LedgerRecord,
    ToolError,
    ensure_success,
    extract_payload,
    find_active_record,
    generate_token,
    issue_one,
    load_ledger,
    main,
    render_invite,
    save_ledger,
    token_fingerprint,
)


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(
        self,
        structured: dict[str, Any] | None = None,
        text: str | None = None,
        is_error: bool = False,
    ) -> None:
        self.structuredContent = structured
        self.content = [_FakeBlock(text)] if text is not None else []
        self.isError = is_error


class _FakeAdmin:
    """Записывает вызовы и отдаёт заранее заданные ответы по имени tool'а."""

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((tool, args or {}))
        return self._responses[tool]


# ---------------------------------------------------------------------------
# Токены
# ---------------------------------------------------------------------------


class TestTokens:
    def test_generate_token_is_hex_and_unique(self):
        first = generate_token()
        second = generate_token()
        assert first != second
        assert len(first) == 64
        int(first, 16)  # hex-safe для HTTP-заголовка Authorization

    def test_fingerprint_is_deterministic_prefix_of_server_hash(self):
        """Отпечаток должен резаться из того же хеша, которым сервер ищет токен."""
        from tg_parser.auth.resolvers import hash_credential

        token = generate_token()
        assert token_fingerprint(token) == hash_credential(token)[:12]
        assert token_fingerprint(token) == token_fingerprint(token)

    def test_fingerprint_does_not_leak_token(self):
        token = generate_token()
        assert token[:12] not in token_fingerprint(token)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def _record(name: str, mapping_id: str, revoked_at: str | None = None) -> LedgerRecord:
    return LedgerRecord(
        name=name,
        user_id=f"uuid-{name}",
        mapping_id=mapping_id,
        client_name=f"{name}-mcp",
        role="user",
        max_channels=3,
        token_fingerprint="a" * 12,
        issued_at="2026-08-12T10:00:00+00:00",
        revoked_at=revoked_at,
    )


class TestLedger:
    def test_missing_file_reads_as_empty(self, tmp_path: Path):
        assert load_ledger(tmp_path / "nope.json") == []

    def test_roundtrip_preserves_fields(self, tmp_path: Path):
        path = tmp_path / "ledger.json"
        save_ledger(path, [_record("alice", "map-1")])
        loaded = load_ledger(path)
        assert loaded == [_record("alice", "map-1")]
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1

    def test_find_active_skips_revoked_and_takes_latest(self, tmp_path: Path):
        records = [
            _record("alice", "map-1", revoked_at="2026-08-12T11:00:00+00:00"),
            _record("alice", "map-2"),
            _record("bob", "map-3"),
        ]
        assert find_active_record(records, "alice").mapping_id == "map-2"
        assert find_active_record(records, "carol") is None

    def test_find_active_returns_none_when_all_revoked(self):
        records = [_record("alice", "map-1", revoked_at="2026-08-12T11:00:00+00:00")]
        assert find_active_record(records, "alice") is None


# ---------------------------------------------------------------------------
# Шаблон приглашения
# ---------------------------------------------------------------------------


class TestInvite:
    def test_contains_connection_essentials(self):
        text = render_invite(
            "alice",
            mcp_url="https://mcp.example.com/mcp",
            token="tok-123",
            max_channels=3,
        )
        assert "alice" in text
        assert "https://mcp.example.com/mcp" in text
        assert "Bearer tok-123" in text
        assert "whoami" in text
        assert "add_channel" in text
        assert "Лимит каналов: 3" in text

    def test_admin_role_has_no_channel_limit_wording(self):
        text = render_invite("root", mcp_url="https://x/mcp", token="t", max_channels=None)
        assert "без лимита (admin)" in text

    def test_bot_line_only_when_username_given(self):
        without = render_invite("alice", mcp_url="https://x/mcp", token="t", max_channels=1)
        assert "/start" not in without
        with_bot = render_invite(
            "alice", mcp_url="https://x/mcp", token="t", max_channels=1, bot_username="@SomeBot"
        )
        assert "@SomeBot" in with_bot
        assert "/start" in with_bot


# ---------------------------------------------------------------------------
# Разбор ответов MCP
# ---------------------------------------------------------------------------


class TestPayloadParsing:
    def test_prefers_structured_content(self):
        assert extract_payload(_FakeResult(structured={"user_id": "u1"})) == {"user_id": "u1"}

    def test_falls_back_to_json_text_block(self):
        assert extract_payload(_FakeResult(text='{"user_id": "u1"}')) == {"user_id": "u1"}

    def test_non_json_text_becomes_message(self):
        assert extract_payload(_FakeResult(text="boom")) == {"message": "boom"}

    def test_empty_result_is_empty_dict(self):
        assert extract_payload(_FakeResult()) == {}

    def test_ensure_success_raises_on_transport_error(self):
        with pytest.raises(ToolError, match="MCP вернул ошибку"):
            ensure_success("register_user", {"message": "nope"}, is_error=True)

    def test_ensure_success_raises_on_permission_denied_payload(self):
        with pytest.raises(ToolError, match="Admin access required"):
            ensure_success(
                "register_user",
                {"success": False, "message": "Admin access required"},
                is_error=False,
            )

    def test_ensure_success_passes_payload_through(self):
        payload = {"success": True, "user_id": "u1"}
        assert ensure_success("register_user", payload, is_error=False) is payload


# ---------------------------------------------------------------------------
# issue_one
# ---------------------------------------------------------------------------


class TestIssueOne:
    async def test_registers_binds_and_verifies(self, monkeypatch: pytest.MonkeyPatch):
        admin = _FakeAdmin(
            {
                "register_user": {"success": True, "user_id": "uuid-1"},
                "add_user_auth": {"success": True, "mapping_id": "map-1"},
            }
        )
        seen: dict[str, str] = {}

        async def fake_verify(url: str, token: str) -> dict[str, Any]:
            seen["url"] = url
            seen["token"] = token
            return {"name": "alice", "role": "user"}

        monkeypatch.setattr("scripts.onboard_test_users.verify_token", fake_verify)

        record, token = await issue_one(
            admin,
            name="alice",
            role="user",
            max_channels=3,
            client_name="alice-cursor",
            mcp_url="https://mcp.example.com/mcp",
        )

        tools = [call[0] for call in admin.calls]
        assert tools == ["register_user", "add_user_auth"]
        assert admin.calls[0][1] == {"name": "alice", "role": "user", "max_channels": 3}
        auth_args = admin.calls[1][1]
        assert auth_args["auth_type"] == "mcp_token"
        assert auth_args["identifier"] == token, "сервер хеширует сам — отдаём сырой токен"
        assert auth_args["client_name"] == "alice-cursor"

        assert seen["token"] == token, "проверяем именно выданный токен"
        assert record.user_id == "uuid-1"
        assert record.mapping_id == "map-1"
        assert record.token_fingerprint == token_fingerprint(token)
        assert record.revoked_at is None

    async def test_omits_max_channels_when_none(self, monkeypatch: pytest.MonkeyPatch):
        admin = _FakeAdmin(
            {
                "register_user": {"success": True, "user_id": "uuid-1"},
                "add_user_auth": {"success": True, "mapping_id": "map-1"},
            }
        )
        monkeypatch.setattr(
            "scripts.onboard_test_users.verify_token",
            lambda url, token: _coro({"name": "alice", "role": "user"}),
        )
        await issue_one(
            admin,
            name="alice",
            role="user",
            max_channels=None,
            client_name="alice-mcp",
            mcp_url="https://x/mcp",
        )
        assert "max_channels" not in admin.calls[0][1]

    async def test_raises_when_whoami_returns_other_profile(self, monkeypatch: pytest.MonkeyPatch):
        admin = _FakeAdmin(
            {
                "register_user": {"success": True, "user_id": "uuid-1"},
                "add_user_auth": {"success": True, "mapping_id": "map-1"},
            }
        )
        monkeypatch.setattr(
            "scripts.onboard_test_users.verify_token",
            lambda url, token: _coro({"name": "admin", "role": "admin"}),
        )
        with pytest.raises(ToolError, match="чужой профиль"):
            await issue_one(
                admin,
                name="alice",
                role="user",
                max_channels=3,
                client_name="alice-mcp",
                mcp_url="https://x/mcp",
            )

    async def test_raises_when_register_user_gives_no_id(self):
        admin = _FakeAdmin({"register_user": {"success": True, "user_id": None}})
        with pytest.raises(ToolError, match="user_id"):
            await issue_one(
                admin,
                name="alice",
                role="user",
                max_channels=3,
                client_name="alice-mcp",
                mcp_url="https://x/mcp",
            )


async def _coro(value: Any) -> Any:
    return value


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_dry_run_creates_nothing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        ledger = tmp_path / "ledger.json"
        code = main(
            [
                "--mcp-url",
                "https://mcp.example.com/mcp",
                "--admin-token",
                "unused",
                "--ledger",
                str(ledger),
                "issue",
                "alice",
                "bob",
                "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert not ledger.exists()
        assert "alice" in out and "bob" in out
        assert "<TOKEN-БУДЕТ-СГЕНЕРИРОВАН>" in out

    def test_missing_url_exits_with_hint(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("TGP_MCP_URL", raising=False)
        monkeypatch.delenv("TGP_ADMIN_MCP_TOKEN", raising=False)
        with pytest.raises(SystemExit, match="TGP_MCP_URL"):
            main(["--ledger", str(tmp_path / "l.json"), "issue", "alice"])

    def test_ledger_command_lists_status(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        ledger = tmp_path / "ledger.json"
        save_ledger(
            ledger,
            [
                _record("alice", "map-1", revoked_at="2026-08-12T11:00:00+00:00"),
                _record("bob", "map-2"),
            ],
        )
        assert main(["--ledger", str(ledger), "ledger"]) == 0
        out = capsys.readouterr().out
        assert "alice" in out and "revoked" in out
        assert "bob" in out and "active" in out
