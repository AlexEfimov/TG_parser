"""
Unit тесты для CLI команды `tg-parser auth`.

Проверяет авторизацию Telegram, --force флаг, обработку ошибок.
"""

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from tg_parser.cli.app import app

runner = CliRunner()


@pytest.fixture
def mock_telethon(tmp_path):
    """Mock TelethonClient для auth тестов без реального Telegram."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    mock_settings = type("MockSettings", (), {
        "telegram_session_name": str(session_dir / "tg_parser_session"),
        "telegram_phone": "+1234567890",
        "telegram_api_id": 12345,
        "telegram_api_hash": "test_hash",
    })()

    instance = AsyncMock()
    instance.connect = AsyncMock()
    instance.disconnect = AsyncMock()

    with (
        patch(
            "tg_parser.ingestion.telegram.telethon_client.TelethonClient",
            return_value=instance,
        ) as mock_cls,
        patch("tg_parser.config.settings", mock_settings),
    ):
        yield {
            "cls": mock_cls,
            "instance": instance,
            "settings": mock_settings,
            "session_dir": session_dir,
        }


class TestAuthCommand:
    """Тесты для tg-parser auth."""

    def test_auth_success(self, mock_telethon):
        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Авторизация успешна" in result.output
        mock_telethon["instance"].connect.assert_awaited_once()
        mock_telethon["instance"].disconnect.assert_awaited_once()

    def test_auth_shows_session_info(self, mock_telethon):
        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Запуск Telegram-авторизации" in result.output
        assert "+1234567890" in result.output

    def test_auth_force_deletes_existing_session(self, mock_telethon):
        session_file = mock_telethon["session_dir"] / "tg_parser_session.session"
        session_file.write_text("old session data")

        result = runner.invoke(app, ["auth", "--force"])

        assert result.exit_code == 0
        assert "Удалён старый session-файл" in result.output
        assert not session_file.exists()

    def test_auth_force_no_existing_session(self, mock_telethon):
        """--force когда session-файла нет — не падает."""
        result = runner.invoke(app, ["auth", "--force"])

        assert result.exit_code == 0
        assert "Удалён старый" not in result.output
        assert "Авторизация успешна" in result.output

    def test_auth_creates_session_directory(self, tmp_path):
        """auth создаёт директорию для session если её нет."""
        nested_dir = tmp_path / "deep" / "nested" / "sessions"

        mock_settings = type("MockSettings", (), {
            "telegram_session_name": str(nested_dir / "session"),
            "telegram_phone": "+1234567890",
            "telegram_api_id": 12345,
            "telegram_api_hash": "test_hash",
        })()

        instance = AsyncMock()
        instance.connect = AsyncMock()
        instance.disconnect = AsyncMock()

        with (
            patch(
                "tg_parser.ingestion.telegram.telethon_client.TelethonClient",
                return_value=instance,
            ),
            patch("tg_parser.config.settings", mock_settings),
        ):
            result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert nested_dir.exists()

    def test_auth_eoferror_non_interactive(self, mock_telethon):
        """При закрытом stdin (docker compose up) — понятная ошибка."""
        mock_telethon["instance"].connect = AsyncMock(side_effect=EOFError)

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 1
        assert "stdin закрыт" in result.output
        assert "docker compose run" in result.output

    def test_auth_generic_error(self, mock_telethon):
        mock_telethon["instance"].connect = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 1
        assert "Ошибка авторизации" in result.output

    def test_auth_disconnect_called_on_error(self, mock_telethon):
        """disconnect вызывается даже при ошибке connect."""
        mock_telethon["instance"].connect = AsyncMock(
            side_effect=RuntimeError("fail")
        )

        runner.invoke(app, ["auth"])

        mock_telethon["instance"].disconnect.assert_awaited_once()


class TestSessionPathResolution:
    """Тесты для корректного разрешения путей session."""

    def test_absolute_session_path_preserved(self):
        """Абсолютный путь в TELEGRAM_SESSION_NAME не изменяется."""
        from tg_parser.config.settings import Settings

        s = Settings(
            telegram_session_name="/app/sessions/tg_parser_session",
            telegram_api_id=12345,
            telegram_api_hash="test_hash",
        )
        assert s.telegram_session_name == "/app/sessions/tg_parser_session"

    def test_relative_session_path_resolved(self):
        """Относительный путь резолвится от PROJECT_ROOT."""
        from tg_parser.config.settings import Settings, _PROJECT_ROOT

        s = Settings(
            telegram_session_name="my_session",
            telegram_api_id=12345,
            telegram_api_hash="test_hash",
        )
        assert s.telegram_session_name == str(_PROJECT_ROOT / "my_session")
