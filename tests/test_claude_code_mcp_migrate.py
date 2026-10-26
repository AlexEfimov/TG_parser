"""redact() из scripts/claude_code_mcp_migrate.py: значения секретов не печатаются."""

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "claude_code_mcp_migrate.py"
_spec = importlib.util.spec_from_file_location("claude_code_mcp_migrate", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
redact = _mod.redact

FAKE = "FAKE_SECRET_VALUE"


def _dump(cfg: dict) -> str:
    return json.dumps(redact(cfg))


def test_headers_values_hidden_names_kept() -> None:
    out = redact({"type": "http", "headers": {"Authorization": f"Bearer {FAKE}"}})
    assert out["headers"] == {"Authorization": "<hidden>"}


def test_url_query_key_hidden() -> None:
    out = redact({"type": "http", "url": f"https://example.test/mcp?apiKey={FAKE}&x=1"})
    assert FAKE not in out["url"]
    assert out["url"].endswith("apiKey=<hidden>&x=1")


def test_env_values_hidden_names_kept() -> None:
    out = redact({"type": "stdio", "command": "npx", "env": {"CONTEXT7_API_KEY": FAKE}})
    assert out["env"] == {"CONTEXT7_API_KEY": "<hidden>"}


def test_value_after_secret_flag_hidden() -> None:
    out = redact({"command": "npx", "args": ["-y", "pkg-mcp", "--api-key", FAKE, "--port", "1"]})
    assert out["args"] == ["-y", "pkg-mcp", "--api-key", "<hidden>", "--port", "1"]


def test_inline_secret_in_args_hidden() -> None:
    cfg = {
        "command": "/bin/sh",
        "args": [
            "--token=" + FAKE,
            "-c",
            f"API_KEY={FAKE} exec server",
            f"https://h.test/?key={FAKE}",
        ],
    }
    assert FAKE not in _dump(cfg)


def test_non_secret_args_kept() -> None:
    args = ["-c", "cd /repo && exec /repo/.venv/bin/python -m tg_parser.mcp_server"]
    assert redact({"type": "stdio", "command": "/bin/sh", "args": args})["args"] == args


def test_input_not_mutated() -> None:
    cfg = {"env": {"K": FAKE}, "args": ["--api-key", FAKE], "headers": {"X-Key": FAKE}}
    before = json.dumps(cfg)
    redact(cfg)
    assert json.dumps(cfg) == before
