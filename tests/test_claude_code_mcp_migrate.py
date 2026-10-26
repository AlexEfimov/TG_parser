"""redact() из scripts/claude_code_mcp_migrate.py: в печать идёт только структура."""

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
H = "<hidden>"


def test_headers_values_hidden_names_kept() -> None:
    out = redact({"type": "http", "headers": {"Authorization": f"Bearer {FAKE}"}})
    assert out["headers"] == {"Authorization": H}


def test_env_values_hidden_names_kept() -> None:
    out = redact({"type": "stdio", "command": "npx", "env": {"CONTEXT7_API_KEY": FAKE}})
    assert out["env"] == {"CONTEXT7_API_KEY": H}


def test_all_args_hidden_count_kept() -> None:
    out = redact({"command": "npx", "args": ["-y", "pkg-mcp", "--api-key", FAKE]})
    assert out["args"] == [H, H, H, H]
    assert out["command"] == "npx"


def test_url_structure_kept_values_hidden() -> None:
    out = redact(
        {"type": "http", "url": f"https://u:{FAKE}@mcp.example.test:8443/mcp?apiKey={FAKE}&x=1"}
    )
    assert out["url"] == f"https://mcp.example.test:8443/{H}?apiKey={H}&x={H}"


def test_url_path_hidden() -> None:
    out = redact({"type": "http", "url": f"https://mcp.example.test/api/{FAKE}/sse"})
    assert out["url"] == f"https://mcp.example.test/{H}"


def test_command_with_whitespace_hidden() -> None:
    out = redact({"command": f"sh -c 'TOKEN={FAKE} srv'"})
    assert out["command"] == H


def test_unknown_fields_hidden_type_kept() -> None:
    out = redact({"type": "stdio", "cwd": "/x", "oauth": {"clientSecret": FAKE}})
    assert out == {"type": "stdio", "cwd": H, "oauth": H}


def test_reviewer_leak_cases_hidden() -> None:
    cases = [
        {"args": ["mcp-remote", "https://x.test/sse", "--header", f"Authorization: Bearer {FAKE}"]},
        {"args": ["mcp-remote", "--header", f"Authorization:Bearer {FAKE}"]},
        {"args": ["-c", f"TOKEN='{FAKE}' exec srv"]},
        {"args": ["-c", f'TOKEN="{FAKE}" exec srv']},
        {"args": ["-k", FAKE]},
        {"args": [f"--token={FAKE}", f"https://h.test/?key={FAKE}"]},
        {"url": f"https://x.test/mcp?secret={FAKE}"},
        {"url": f"https://x.test/mcp?auth={FAKE}"},
        {"url": f"https://user:{FAKE}@x.test/mcp"},
        {"url": f"https://x.test/{FAKE.lower()}/sse"},
        {"env": {"ANY": FAKE}, "headers": {"X-Key": FAKE}},
    ]
    for cfg in cases:
        dumped = json.dumps(redact(cfg)).lower()
        assert FAKE.lower() not in dumped, cfg


def test_unexpected_types_and_odd_urls_hidden() -> None:
    cases = [
        {"args": FAKE},
        {"command": ["a", FAKE]},
        {"url": 123, "type": ["x", FAKE]},
        {"headers": f"Authorization: {FAKE}"},
        {"env": [FAKE]},
        {"url": f"https://x.test/?{FAKE}"},
        {"url": f"https://x.test:{FAKE}/"},
    ]
    for cfg in cases:
        dumped = json.dumps(redact(cfg)).lower()
        assert FAKE.lower() not in dumped, cfg
    assert redact({"url": f"https://x.test/?{FAKE}&k=1"})["url"] == f"https://x.test/?{H}&k={H}"
    assert redact({"url": f"https://x.test:{FAKE}/"})["url"] == H


def test_input_not_mutated() -> None:
    cfg = {"env": {"K": FAKE}, "args": ["--api-key", FAKE], "url": f"https://x.test/?k={FAKE}"}
    before = json.dumps(cfg)
    redact(cfg)
    assert json.dumps(cfg) == before
