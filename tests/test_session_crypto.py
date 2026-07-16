"""F9 Phase 3 M1 — Telethon session at-rest encryption tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from tg_parser.config.settings import Settings
from tg_parser.ingestion.telegram.session_crypto import (
    SessionCryptoError,
    seal_session_at_rest,
    session_sealed_path,
    session_working_path,
    unseal_session_for_use,
    wipe_working_session,
)
from tg_parser.ingestion.telegram.telethon_client import TelethonClient, _WALSQLiteSession


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def session_base(tmp_path: Path) -> str:
    return str(tmp_path / "tg_test_session")


def test_seal_unseal_round_trip(session_base: str, fernet_key: str) -> None:
    working = session_working_path(session_base)
    working.write_bytes(b"synthetic-session-bytes-not-a-real-telethon-db")

    sealed = seal_session_at_rest(session_base, fernet_key)
    assert sealed is not None
    assert sealed.exists()
    assert not working.exists()
    assert not Path(str(working) + "-wal").exists()

    unseal_session_for_use(session_base, fernet_key)
    assert working.exists()
    assert working.read_bytes() == b"synthetic-session-bytes-not-a-real-telethon-db"


def test_plaintext_migration_then_seal(session_base: str, fernet_key: str) -> None:
    working = session_working_path(session_base)
    working.write_bytes(b"plaintext-legacy")
    # Unseal is a no-op when only plaintext exists.
    unseal_session_for_use(session_base, fernet_key)
    assert working.exists()
    assert not session_sealed_path(session_base).exists()

    seal_session_at_rest(session_base, fernet_key)
    assert session_sealed_path(session_base).exists()
    assert not working.exists()


def test_missing_key_with_enc_fails_closed(session_base: str, fernet_key: str) -> None:
    working = session_working_path(session_base)
    working.write_bytes(b"blob")
    seal_session_at_rest(session_base, fernet_key)
    assert not working.exists()

    with pytest.raises(SessionCryptoError, match="TELEGRAM_SESSION_KEY is not set"):
        unseal_session_for_use(session_base, None)

    with pytest.raises(SessionCryptoError, match="TELEGRAM_SESSION_KEY is not set"):
        unseal_session_for_use(session_base, "")


def test_seal_wipes_wal_sidecars(session_base: str, fernet_key: str) -> None:
    working = session_working_path(session_base)
    working.write_bytes(b"main")
    wal = Path(str(working) + "-wal")
    shm = Path(str(working) + "-shm")
    wal.write_bytes(b"wal-leak")
    shm.write_bytes(b"shm-leak")

    seal_session_at_rest(session_base, fernet_key)
    assert not working.exists()
    assert not wal.exists()
    assert not shm.exists()
    assert session_sealed_path(session_base).exists()


def test_unseal_prefers_existing_working_over_stale_enc(session_base: str, fernet_key: str) -> None:
    """Crash recovery: do not wipe a newer working .session from stale .enc."""
    working = session_working_path(session_base)
    working.write_bytes(b"old-sealed-content")
    seal_session_at_rest(session_base, fernet_key)
    # Simulate crash after Telethon wrote newer state but before re-seal.
    working.write_bytes(b"newer-unsealed-state")

    unseal_session_for_use(session_base, fernet_key)
    assert working.read_bytes() == b"newer-unsealed-state"


def test_wipe_working_session(session_base: str) -> None:
    working = session_working_path(session_base)
    working.write_bytes(b"x")
    Path(str(working) + "-wal").write_bytes(b"w")
    wipe_working_session(working)
    assert not working.exists()
    assert not Path(str(working) + "-wal").exists()


@pytest.mark.asyncio
async def test_connect_uses_walsqlite_after_unseal(tmp_path: Path, fernet_key: str) -> None:
    """Connect path still builds ``_WALSQLiteSession`` (BUG-070) after unseal."""
    session_name = str(tmp_path / "locked_session")
    working = session_working_path(session_name)
    # Minimal non-empty bytes; Telethon open is mocked.
    working.write_bytes(b"synthetic")
    seal_session_at_rest(session_name, fernet_key)

    settings = Settings(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_phone="+10000000000",
        telegram_session_name=session_name,
        telegram_session_key=fernet_key,
    )

    captured: dict[str, object] = {}

    def _fake_wal(session_id=None, *, busy_timeout_ms: int = 5000):
        captured["session_id"] = session_id
        captured["busy_timeout_ms"] = busy_timeout_ms
        mock = MagicMock(spec=_WALSQLiteSession)
        return mock

    fake_client = MagicMock()
    fake_client.start = AsyncMock()
    fake_client.disconnect = AsyncMock()

    with (
        patch(
            "tg_parser.ingestion.telegram.telethon_client._WALSQLiteSession",
            side_effect=_fake_wal,
        ),
        patch(
            "tg_parser.ingestion.telegram.telethon_client.TelethonTelegramClient",
            return_value=fake_client,
        ),
    ):
        client = TelethonClient(settings)
        await client.connect()
        assert isinstance(captured["session_id"], str)
        assert working.exists()  # unsealed for use
        await client.disconnect()

    assert session_sealed_path(session_name).exists()
    assert not working.exists()
