#!/usr/bin/env python3
"""
Выдача тестового доступа к TG_parser нескольким пользователям (admin-утилита).

Скрипт разговаривает с **живым MCP-сервером** от имени администратора
(bearer-токен админа) и делает за один проход то, что иначе выполняется
руками в четыре tool-call'а на каждого тестировщика:

1. генерирует случайный MCP-токен (`secrets.token_hex`);
2. `register_user` — создаёт пользователя с ролью и лимитом каналов;
3. `add_user_auth` — привязывает SHA-256 хеш токена (`auth_type='mcp_token'`);
4. `whoami` **уже под новым токеном** — проверка, что доступ реально работает;
5. печатает готовое сообщение тестировщику и пишет строку в ledger.

Ledger (`--ledger`, по умолчанию `onboarding_ledger.json`) нужен ровно для
одного: `remove_user_auth` требует `mapping_id`, а получить его повторно
нечем — ни один MCP-tool не перечисляет auth-mappings. Без ledger отзыв
доступа возможен только SQL-запросом к `user_auth` на проде.

Сырой токен в ledger **не пишется** — только `sha256[:12]` как отпечаток
для сверки. Токен показывается один раз, при выдаче.

Использование:

    export TGP_MCP_URL="https://mcp.example.com/mcp"
    export TGP_ADMIN_MCP_TOKEN="<admin bearer token>"

    # выдать доступ трём тестировщикам
    python scripts/onboard_test_users.py issue alice bob carol --max-channels 3

    # прогон без записи (проверить связь и увидеть шаблон приглашения)
    python scripts/onboard_test_users.py issue alice --dry-run

    # что выдано
    python scripts/onboard_test_users.py ledger
    python scripts/onboard_test_users.py users

    # проверить чужой токен так, как его увидит клиент
    python scripts/onboard_test_users.py verify --token <raw-token>

    # отозвать доступ (по имени из ledger или по mapping_id)
    python scripts/onboard_test_users.py revoke alice

Полная инструкция оператора: docs/runbooks/TEST_ACCESS_MULTI_USER.md
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_LEDGER = Path("onboarding_ledger.json")
LEDGER_VERSION = 1

# Значение по умолчанию совпадает с рекомендацией runbook'а: тестировщику
# хватает 1-3 каналов, а каждый лишний канал — это LLM-расход на ключах
# оператора (см. § «Стоимость» в TEST_ACCESS_MULTI_USER.md).
DEFAULT_MAX_CHANNELS = 3


# ---------------------------------------------------------------------------
# Чистые помощники (тестируются без сети — tests/test_onboard_test_users.py)
# ---------------------------------------------------------------------------


def generate_token(nbytes: int = 32) -> str:
    """Случайный bearer-токен: hex, чтобы безопасно жить в HTTP-заголовке."""
    return secrets.token_hex(nbytes)


def token_fingerprint(token: str) -> str:
    """Короткий отпечаток токена для ledger (сырой токен не сохраняем)."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


@dataclass
class LedgerRecord:
    """Одна выдача доступа. `mapping_id` — единственный путь к отзыву."""

    name: str
    user_id: str
    mapping_id: str
    client_name: str
    role: str
    max_channels: int | None
    token_fingerprint: str
    issued_at: str
    revoked_at: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def load_ledger(path: Path) -> list[LedgerRecord]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [LedgerRecord(**item) for item in raw.get("records", [])]


def save_ledger(path: Path, records: list[LedgerRecord]) -> None:
    payload = {"version": LEDGER_VERSION, "records": [asdict(r) for r in records]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_active_record(records: list[LedgerRecord], name: str) -> LedgerRecord | None:
    """Последняя неотозванная выдача для имени (имена переиспользуемы)."""
    for record in reversed(records):
        if record.name == name and record.revoked_at is None:
            return record
    return None


def render_invite(
    name: str,
    *,
    mcp_url: str,
    token: str,
    max_channels: int | None,
    bot_username: str | None = None,
    docs_url: str | None = None,
) -> str:
    """Сообщение, которое оператор отправляет тестировщику как есть."""
    limit = "без лимита (admin)" if max_channels is None else str(max_channels)
    lines = [
        f"Привет, {name}! Доступ к TG_parser для тестирования.",
        "",
        "1. Добавь MCP-сервер в свой AI-клиент.",
        "",
        "   Cursor — файл ~/.cursor/mcp.json (или .cursor/mcp.json в проекте):",
        "   {",
        '     "mcpServers": {',
        '       "tg-parser": {',
        f'         "url": "{mcp_url}",',
        '         "headers": { "Authorization": "Bearer ' + token + '" }',
        "       }",
        "     }",
        "   }",
        "",
        "   Claude Code — одной командой:",
        f'   claude mcp add --transport http tg-parser {mcp_url} --header "Authorization: Bearer {token}"',
        "",
        "2. Перезапусти клиент и попроси ассистента вызвать инструмент whoami —",
        f"   в ответе должно быть name={name}, role=user.",
        '3. Добавь свой первый ПУБЛИЧНЫЙ канал: add_channel(channel_id="@имя_канала").',
        '4. Дождись обработки: get_pipeline_status(channel_id="@имя_канала") —',
        "   нужно непустое last_success_at (обычно 5-30 минут на первом проходе).",
        "5. После этого работают search_knowledge_base и ask_question по твоему каналу.",
        "",
        f"Лимит каналов: {limit}.",
        "Приватные каналы не подключатся: сбор идёт под Telegram-аккаунтом сервера,",
        "он должен быть подписан на канал. Начни с публичного.",
        "Видно только твои каналы — чужую базу знаний ты не увидишь, это by design.",
        "",
        "Токен персональный, показан один раз, в мессенджеры/репозитории не выкладывай.",
        "Что угодно не так — напиши мне текстом, отдельной формы для фидбека нет.",
    ]
    if bot_username:
        lines.insert(
            -3,
            f"Telegram-бот (тот же аккаунт, если он тебе выдан): @{bot_username.lstrip('@')} → /start",
        )
    if docs_url:
        lines.append(f"Подробнее: {docs_url}")
    return "\n".join(lines)


def extract_payload(result: Any) -> dict[str, Any]:
    """Достать структурированный ответ MCP-tool'а из CallToolResult.

    FastMCP отдаёт pydantic-модель в ``structuredContent``; текстовый блок —
    fallback для клиентов/версий без structured output.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"message": text}
        if isinstance(parsed, dict):
            return parsed
        return {"result": parsed}
    return {}


class ToolError(RuntimeError):
    """MCP-tool вернул isError или success=false."""


def ensure_success(tool: str, payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    if is_error:
        raise ToolError(f"{tool}: MCP вернул ошибку — {payload.get('message') or payload}")
    if payload.get("success") is False:
        raise ToolError(f"{tool}: {payload.get('message') or 'success=false'}")
    return payload


# ---------------------------------------------------------------------------
# MCP-клиент
# ---------------------------------------------------------------------------


class McpAdminClient:
    """Тонкая обёртка над streamable-HTTP клиентом MCP SDK."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._stack: Any = None
        self._session: Any = None

    async def __aenter__(self) -> McpAdminClient:
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(self._url, headers={"Authorization": f"Bearer {self._token}"})
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.__aexit__(*exc)

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self._session.call_tool(tool, args or {})
        payload = extract_payload(result)
        return ensure_success(tool, payload, is_error=bool(getattr(result, "isError", False)))


# ---------------------------------------------------------------------------
# Операции
# ---------------------------------------------------------------------------


async def issue_one(
    admin: McpAdminClient,
    *,
    name: str,
    role: str,
    max_channels: int | None,
    client_name: str,
    mcp_url: str,
) -> tuple[LedgerRecord, str]:
    """register_user + add_user_auth + проверка входа под новым токеном."""
    token = generate_token()

    created = await admin.call(
        "register_user",
        {
            "name": name,
            "role": role,
            **({} if max_channels is None else {"max_channels": max_channels}),
        },
    )
    user_id = created.get("user_id")
    if not user_id:
        raise ToolError(f"register_user не вернул user_id: {created}")

    mapping = await admin.call(
        "add_user_auth",
        {
            "user_id": user_id,
            "auth_type": "mcp_token",
            "identifier": token,
            "client_name": client_name,
        },
    )
    mapping_id = mapping.get("mapping_id")
    if not mapping_id:
        raise ToolError(f"add_user_auth не вернул mapping_id: {mapping}")

    profile = await verify_token(mcp_url, token)
    if profile.get("name") != name:
        raise ToolError(f"проверка whoami вернула чужой профиль: {profile}")

    record = LedgerRecord(
        name=name,
        user_id=str(user_id),
        mapping_id=str(mapping_id),
        client_name=client_name,
        role=role,
        max_channels=max_channels,
        token_fingerprint=token_fingerprint(token),
        issued_at=datetime.now(UTC).isoformat(timespec="seconds"),
        notes={"verified_role": profile.get("role"), "mcp_url": mcp_url},
    )
    return record, token


async def verify_token(mcp_url: str, token: str) -> dict[str, Any]:
    """whoami под выданным токеном — ровно тот путь, который пройдёт клиент."""
    async with McpAdminClient(mcp_url, token) as client:
        return await client.call("whoami")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_conn(args: argparse.Namespace) -> tuple[str, str]:
    url = args.mcp_url or os.environ.get("TGP_MCP_URL", "")
    token = args.admin_token or os.environ.get("TGP_ADMIN_MCP_TOKEN", "")
    if not url:
        raise SystemExit("Нужен --mcp-url или TGP_MCP_URL (например https://mcp.example.com/mcp)")
    if not token:
        raise SystemExit("Нужен --admin-token или TGP_ADMIN_MCP_TOKEN (bearer-токен админа)")
    return url, token


async def cmd_issue(args: argparse.Namespace) -> int:
    url, admin_token = _resolve_conn(args)
    ledger_path = Path(args.ledger)
    records = load_ledger(ledger_path)

    if args.dry_run:
        for name in args.names:
            print(f"\n{'=' * 72}\n[dry-run] приглашение для {name}\n{'=' * 72}")
            print(
                render_invite(
                    name,
                    mcp_url=url,
                    token="<TOKEN-БУДЕТ-СГЕНЕРИРОВАН>",
                    max_channels=args.max_channels,
                    bot_username=args.bot_username,
                    docs_url=args.docs_url,
                )
            )
        print("\n[dry-run] ничего не создано: ни пользователей, ни токенов, ни ledger.")
        return 0

    failures: list[str] = []
    async with McpAdminClient(url, admin_token) as admin:
        me = await admin.call("whoami")
        if me.get("role") != "admin":
            raise SystemExit(f"Токен не админский (role={me.get('role')}) — register_user откажет.")
        print(f"Админ подтверждён: {me.get('name')} ({me.get('id')})\n")

        for name in args.names:
            existing = find_active_record(records, name)
            if existing and not args.allow_duplicate:
                print(
                    f"⏭  {name}: в ledger уже есть активная выдача "
                    f"(user_id={existing.user_id}). Нужен новый токен — "
                    "сначала revoke, либо --allow-duplicate."
                )
                continue
            try:
                record, token = await issue_one(
                    admin,
                    name=name,
                    role=args.role,
                    max_channels=args.max_channels,
                    client_name=args.client_name or f"{name}-mcp",
                    mcp_url=url,
                )
            except Exception as exc:  # noqa: BLE001 — один сломавшийся не рвёт партию
                failures.append(f"{name}: {exc}")
                print(f"✗  {name}: {exc}")
                continue

            records.append(record)
            save_ledger(ledger_path, records)
            print(f"✓  {name}: user_id={record.user_id} mapping_id={record.mapping_id}")
            print(f"{'=' * 72}\nСООБЩЕНИЕ ДЛЯ {name} (токен виден только сейчас)\n{'=' * 72}")
            print(
                render_invite(
                    name,
                    mcp_url=url,
                    token=token,
                    max_channels=args.max_channels,
                    bot_username=args.bot_username,
                    docs_url=args.docs_url,
                )
            )
            print("=" * 72)

    print(f"\nLedger: {ledger_path} ({len(records)} записей)")
    if failures:
        print("Не выдано:")
        for line in failures:
            print(f"  - {line}")
        return 1
    return 0


async def cmd_verify(args: argparse.Namespace) -> int:
    url = args.mcp_url or os.environ.get("TGP_MCP_URL", "")
    if not url:
        raise SystemExit("Нужен --mcp-url или TGP_MCP_URL")
    token = args.token or os.environ.get("TGP_VERIFY_TOKEN", "")
    if not token:
        raise SystemExit("Нужен --token (или TGP_VERIFY_TOKEN)")
    profile = await verify_token(url, token)
    print(json.dumps(profile, indent=2, ensure_ascii=False))
    print(f"\nОтпечаток токена: {token_fingerprint(token)}")
    return 0


async def cmd_users(args: argparse.Namespace) -> int:
    url, admin_token = _resolve_conn(args)
    async with McpAdminClient(url, admin_token) as admin:
        payload = await admin.call("list_users")
    users = payload.get("users", [])
    print(f"{'name':<28} {'role':<7} {'max_ch':<7} {'каналов':<8} id")
    for user in users:
        print(
            f"{str(user.get('name')):<28} {str(user.get('role')):<7} "
            f"{str(user.get('max_channels')):<7} {str(user.get('owned_channels_count')):<8} "
            f"{user.get('id')}"
        )
    print(f"\nВсего: {len(users)}")
    return 0


async def cmd_revoke(args: argparse.Namespace) -> int:
    url, admin_token = _resolve_conn(args)
    ledger_path = Path(args.ledger)
    records = load_ledger(ledger_path)

    if args.mapping_id:
        mapping_id = args.mapping_id
        record = next((r for r in records if r.mapping_id == mapping_id), None)
    else:
        if not args.name:
            raise SystemExit("Укажи имя из ledger или --mapping-id")
        record = find_active_record(records, args.name)
        if record is None:
            raise SystemExit(
                f"В ledger нет активной выдачи для '{args.name}'. "
                "Передай --mapping-id (взять из user_auth на проде)."
            )
        mapping_id = record.mapping_id

    async with McpAdminClient(url, admin_token) as admin:
        payload = await admin.call("remove_user_auth", {"mapping_id": mapping_id})
    print(payload.get("message", "removed"))

    if record is not None:
        record.revoked_at = datetime.now(UTC).isoformat(timespec="seconds")
        save_ledger(ledger_path, records)
        print(f"Ledger обновлён: {record.name} → revoked_at={record.revoked_at}")
    print(
        "Кеш резолвера живёт до 60 с (tg_parser/auth/resolvers.py::_CACHE_TTL) — "
        "отозванный токен может отработать ещё один запрос."
    )
    return 0


async def cmd_ledger(args: argparse.Namespace) -> int:
    records = load_ledger(Path(args.ledger))
    if not records:
        print(f"Ledger пуст или отсутствует: {args.ledger}")
        return 0
    print(f"{'name':<24} {'статус':<10} {'выдан':<22} {'fp':<14} mapping_id")
    for record in records:
        status = "revoked" if record.revoked_at else "active"
        print(
            f"{record.name:<24} {status:<10} {record.issued_at:<22} "
            f"{record.token_fingerprint:<14} {record.mapping_id}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Выдача тестового MCP-доступа к TG_parser (admin-утилита)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Инструкция оператора: docs/runbooks/TEST_ACCESS_MULTI_USER.md",
    )
    parser.add_argument("--mcp-url", help="URL MCP-эндпоинта (env TGP_MCP_URL)")
    parser.add_argument("--admin-token", help="bearer-токен админа (env TGP_ADMIN_MCP_TOKEN)")
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_LEDGER),
        help=f"файл журнала выдач (по умолчанию {DEFAULT_LEDGER})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="выдать доступ одному или нескольким тестировщикам")
    issue.add_argument("names", nargs="+", help="имена пользователей (как их видит whoami)")
    issue.add_argument("--role", default="user", choices=["user", "admin"])
    issue.add_argument(
        "--max-channels",
        type=int,
        default=DEFAULT_MAX_CHANNELS,
        help=f"лимит каналов на пользователя (по умолчанию {DEFAULT_MAX_CHANNELS})",
    )
    issue.add_argument("--client-name", help="метка auth-mapping (по умолчанию <name>-mcp)")
    issue.add_argument("--bot-username", help="добавить строку про Telegram-бота в приглашение")
    issue.add_argument("--docs-url", help="ссылка на инструкцию для тестировщика")
    issue.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="выдать второй токен пользователю, у которого уже есть активная выдача",
    )
    issue.add_argument(
        "--dry-run",
        action="store_true",
        help="ничего не создавать: только показать шаблон приглашения",
    )
    issue.set_defaults(func=cmd_issue)

    verify = sub.add_parser("verify", help="проверить токен вызовом whoami")
    verify.add_argument("--token", help="проверяемый токен (env TGP_VERIFY_TOKEN)")
    verify.set_defaults(func=cmd_verify)

    users = sub.add_parser("users", help="list_users от имени админа")
    users.set_defaults(func=cmd_users)

    revoke = sub.add_parser("revoke", help="отозвать доступ (remove_user_auth)")
    revoke.add_argument("name", nargs="?", help="имя из ledger")
    revoke.add_argument("--mapping-id", help="mapping_id напрямую, если ledger потерян")
    revoke.set_defaults(func=cmd_revoke)

    ledger = sub.add_parser("ledger", help="показать журнал выдач")
    ledger.set_defaults(func=cmd_ledger)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except ToolError as exc:
        print(f"Ошибка MCP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
