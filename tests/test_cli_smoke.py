"""
CLI smoke tests: verify Typer wiring for all subcommands.

Checks --help output for db, scheduler, link-topics, and other commands.
Does NOT test actual execution (which requires DB/Telegram).
"""

from typer.testing import CliRunner

from tg_parser.cli.app import app

runner = CliRunner()


class TestDBSubcommand:
    def test_db_help(self):
        result = runner.invoke(app, ["db", "--help"])
        assert result.exit_code == 0
        assert "db" in result.output.lower()

    def test_db_upgrade_help(self):
        result = runner.invoke(app, ["db", "upgrade", "--help"])
        assert result.exit_code == 0


class TestSchedulerSubcommand:
    def test_scheduler_help(self):
        result = runner.invoke(app, ["scheduler", "--help"])
        assert result.exit_code == 0
        assert "scheduler" in result.output.lower() or "start" in result.output.lower()


class TestLinkTopicsCommand:
    def test_link_topics_help(self):
        result = runner.invoke(app, ["link-topics", "--help"])
        assert result.exit_code == 0
        assert "threshold" in result.output.lower()


class TestTopLevelCommands:
    def test_app_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "tg_parser" in result.output.lower() or "telegram" in result.output.lower()

    def test_auth_help(self):
        result = runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0

    def test_ingest_help(self):
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0

    def test_process_help(self):
        result = runner.invoke(app, ["process", "--help"])
        assert result.exit_code == 0

    def test_topicize_help(self):
        result = runner.invoke(app, ["topicize", "--help"])
        assert result.exit_code == 0

    def test_export_help(self):
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0

    def test_run_help(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0


class TestAgentsSubcommand:
    def test_agents_help(self):
        result = runner.invoke(app, ["agents", "--help"])
        assert result.exit_code == 0
