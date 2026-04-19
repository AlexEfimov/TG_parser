"""
CLI smoke tests: verify Typer wiring via --help only.

Does not run commands that need DB, Telegram, or long-lived servers.
"""

import pytest
from typer.testing import CliRunner

from tg_parser.cli.app import app

runner = CliRunner()


def test_main_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "auth",
        "init",
        "add-source",
        "ingest",
        "process",
        "topicize",
        "link-topics",
        "embed",
        "search",
        "ask",
        "export",
        "api",
        "bot",
        "mcp",
        "run",
    ],
)
def test_top_level_command_help(command: str):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout


@pytest.mark.parametrize("group", ["db", "scheduler", "agents"])
def test_subapp_help(group: str):
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["db", "upgrade"],
        ["db", "downgrade"],
        ["db", "current"],
        ["db", "history"],
        ["db", "stamp"],
        ["db", "backup"],
        ["db", "restore"],
        ["db", "list-backups"],
        ["db", "cleanup-orphan-admin"],
        ["scheduler", "start"],
        ["scheduler", "status"],
        ["scheduler", "run-once"],
        ["agents", "list"],
        ["agents", "status"],
        ["agents", "history"],
        ["agents", "cleanup"],
        ["agents", "handoffs"],
        ["agents", "archives"],
    ],
    ids=lambda a: "-".join(a),
)
def test_nested_subcommand_help(args: list[str]):
    result = runner.invoke(app, [*args, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
