"""
Regression tests for DI-14 — `tg-parser db downgrade --yes/-y` flag.

DI-14: `tg_parser/cli/db_cmd.py::downgrade` used `typer.confirm(...)` without
a bypass flag, causing CI / non-tty contexts to hang on stdin (workaround:
`yes y | tg-parser db downgrade ...`). Fixed by adding `--yes/-y` flag
that skips the confirmation prompt.

These are pure CliRunner tests with `run_alembic_command` mocked — no live
PostgreSQL needed. End-to-end smoke (upgrade head → downgrade base → upgrade
head) is already covered by the `alembic-guardrail` job in
`.github/workflows/ci.yml`.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from tg_parser.cli.db_cmd import app as db_app

runner = CliRunner()


class TestDowngradeYesFlagDI14:
    """DI-14 regression: --yes/-y must bypass typer.confirm()."""

    def test_downgrade_default_prompts_and_aborts_on_no(self):
        """
        Without --yes the command must call typer.confirm; if user answers
        'no' (or stdin is empty/closed) it must abort cleanly without invoking
        alembic.
        """
        with patch("tg_parser.cli.db_cmd.run_alembic_command") as run_mock:
            result = runner.invoke(
                db_app,
                ["downgrade", "--db", "ingestion", "base"],
                input="n\n",
            )

        assert result.exit_code == 0, (
            f"expected clean abort (exit 0), got {result.exit_code}. stdout={result.stdout!r}"
        )
        assert "Отменено" in result.stdout, (
            f"expected 'Отменено.' message, got: {result.stdout!r}"
        )
        run_mock.assert_not_called(), (
            "DI-14: alembic must NOT run when user declines confirmation"
        )

    def test_downgrade_yes_flag_skips_prompt_and_calls_alembic(self):
        """
        DI-14 fix: --yes must bypass typer.confirm and proceed straight to
        run_alembic_command. We pass empty stdin to prove no prompt is read
        (typer.confirm with no stdin would otherwise raise EOFError/Abort).
        """
        with patch("tg_parser.cli.db_cmd.run_alembic_command", return_value=0) as run_mock:
            result = runner.invoke(
                db_app,
                ["downgrade", "--db", "ingestion", "--yes", "base"],
                input="",
            )

        assert result.exit_code == 0, (
            f"DI-14: --yes must succeed without prompting. "
            f"exit_code={result.exit_code}, stdout={result.stdout!r}, "
            f"exception={result.exception!r}"
        )
        run_mock.assert_called_once_with(["downgrade", "base"], db_name="ingestion")
        assert "Отменено" not in result.stdout, (
            "DI-14: --yes must NOT print 'Отменено.' (that would mean the "
            "confirm path still ran)"
        )

    def test_downgrade_short_flag_y_works(self):
        """DI-14: -y must behave identically to --yes (typer short form)."""
        with patch("tg_parser.cli.db_cmd.run_alembic_command", return_value=0) as run_mock:
            result = runner.invoke(
                db_app,
                ["downgrade", "--db", "raw", "-y", "base"],
                input="",
            )

        assert result.exit_code == 0, (
            f"DI-14: -y must succeed without prompting. "
            f"exit_code={result.exit_code}, stdout={result.stdout!r}, "
            f"exception={result.exception!r}"
        )
        run_mock.assert_called_once_with(["downgrade", "base"], db_name="raw")
