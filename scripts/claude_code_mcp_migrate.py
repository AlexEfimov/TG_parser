#!/usr/bin/env python3
"""Перенести MCP-серверы из Cursor в Claude Code (одноразовая миграция).

Читает ~/.cursor/mcp.json (глобальные серверы) прямо на машине владельца, чтобы
ключи не проходили через чат, и регистрирует их в Claude Code через
`claude mcp add-json`:

  user scope  (все проекты): tg-parser (прод), context7, ref
  local scope (этот репо, не в git): tg-parser-local — локальный stdio dev-инстанс

Имя локального сервера отличается от продового намеренно: в Cursor оба назывались
`tg-parser`, и проектный конфиг перекрывал прод.

По умолчанию — dry-run: печатает, что будет сделано, со скрытыми секретами.
Запуск из корня репозитория:

    python3 scripts/claude_code_mcp_migrate.py           # посмотреть
    python3 scripts/claude_code_mcp_migrate.py --apply   # выполнить

Повторный --apply для уже существующего имени: claude вернёт ошибку — удалить
сервер (`claude mcp remove <имя> -s <scope>`) и повторить.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

CURSOR_MCP = Path.home() / ".cursor" / "mcp.json"
REPO = Path(__file__).resolve().parent.parent

# Cursor name -> Claude Code name (user scope)
RENAME = {"tg-parser": "tg-parser", "Context7": "context7", "Ref": "ref"}


HIDDEN = "<hidden>"


def _redact_url(url: str) -> str:
    """Только схема, хост и порт; путь, userinfo и значения query скрыты, имена query — нет."""
    try:
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if parts.port is not None:
            netloc += f":{parts.port}"
    except ValueError:  # например, нечисловой порт: значение не должно попасть в traceback
        return HIDDEN
    path = "/" + HIDDEN if parts.path not in ("", "/") else parts.path
    # Параметр без «=» целиком скрыт: «имя» само может быть токеном.
    query = "&".join(
        f"{p.split('=', 1)[0]}={HIDDEN}" if "=" in p else HIDDEN
        for p in parts.query.split("&")
        if p
    )
    return urlunsplit((parts.scheme, netloc, path, query, ""))


def redact(cfg: dict) -> dict:
    """Копия конфига MCP-сервера для печати: только структура, без значений.

    Скрыты значения headers и env (имена остаются), все элементы args, в url —
    userinfo, путь и значения query, command с пробелами и значения прочих полей.
    Поле известного имени, но неожиданного типа скрывается целиком.
    Перебор «секретных» форм не используется: любая строка args может быть секретом.
    """
    out = json.loads(json.dumps(cfg))
    for field, value in out.items():
        if field in ("headers", "env") and isinstance(value, dict):
            out[field] = dict.fromkeys(value, HIDDEN)
        elif field == "url" and isinstance(value, str):
            out[field] = _redact_url(value)
        elif field == "args" and isinstance(value, list):
            out[field] = [HIDDEN] * len(value)
        elif field in ("command", "type") and isinstance(value, str):
            if field == "command" and re.search(r"\s", value):
                out[field] = HIDDEN
        else:
            out[field] = HIDDEN
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="выполнить, а не только показать")
    args = ap.parse_args()

    if Path.cwd().resolve() != REPO:
        print(f"Запускать из корня репозитория: cd {REPO}", file=sys.stderr)
        return 2
    if args.apply and not shutil.which("claude"):
        print("claude CLI не найден в PATH — сначала установить Claude Code CLI", file=sys.stderr)
        return 2

    plan: list[tuple[str, str, dict]] = []  # (name, scope, config)

    servers = json.loads(CURSOR_MCP.read_text()).get("mcpServers", {})
    for src, cfg in servers.items():
        name = RENAME.get(src)
        if name is None:
            print(f"skip: '{src}' нет в RENAME — добавить вручную, если нужен")
            continue
        cfg = dict(cfg)
        cfg.setdefault("type", "http" if "url" in cfg else "stdio")
        if not cfg.get("headers"):
            cfg.pop("headers", None)
        plan.append((name, "user", cfg))

    venv_py = REPO / ".venv" / "bin" / "python"
    plan.append(
        (
            "tg-parser-local",
            "local",
            {
                "type": "stdio",
                "command": "/bin/sh",
                "args": [
                    "-c",
                    f"cd {shlex.quote(str(REPO))} && exec {shlex.quote(str(venv_py))} -m tg_parser.mcp_server",
                ],
            },
        )
    )

    failed = 0
    for name, scope, cfg in plan:
        print(
            f"{'APPLY' if args.apply else 'DRY  '}  {scope:5}  {name:16} {json.dumps(redact(cfg), ensure_ascii=False)}"
        )
        if args.apply:
            r = subprocess.run(
                ["claude", "mcp", "add-json", "-s", scope, name, json.dumps(cfg)],
                text=True,
                capture_output=True,
            )
            # Вывод claude не печатаем: при ошибке он может повторить переданный JSON с секретами.
            print(f"       -> exit {r.returncode}")
            if r.returncode != 0:
                failed += 1

    if "Ref" in servers and re.search(r"apiKey=", servers["Ref"].get("url", ""), re.I):
        print(
            "\nNOTE: ключ Ref передаётся в query-параметре URL (так было и в Cursor). "
            "Если ref.tools поддерживает заголовок, перенести ключ туда и ротировать."
        )
    print("\nПроверка: `claude mcp list`, затем в сессии `/mcp` — все Connected.")
    if failed:
        print(
            f"\nНе зарегистрировано серверов: {failed}. Вывод claude скрыт — повторить "
            "`claude mcp add-json` для этого имени вручную.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
