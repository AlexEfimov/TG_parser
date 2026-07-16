"""Telethon session at-rest encryption (F9 Phase 3 / M1).

Threat model: protect offline theft of ``data/sessions/`` (backup, stopped
stack, copied volume). While any container holds an open Telethon SQLite
session, a working ``.session`` (plus WAL sidecars) may exist plaintext on the
shared volume — this module does **not** claim live multi-container
confidentiality.

Protocol:
- Durable sealed form: ``<session_name>.session.enc``
- Working form (Telethon): ``<session_name>.session`` (+ optional -wal/-shm)
- Encrypt iff ``TELEGRAM_SESSION_KEY`` is set (Fernet key from
  ``Fernet.generate_key()``). No separate enable flag.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)

ENC_SUFFIX = ".session.enc"
SESSION_SUFFIX = ".session"


class SessionCryptoError(RuntimeError):
    """Raised when session seal/unseal cannot proceed safely."""


def _fernet_from_key(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception as exc:
        raise SessionCryptoError(
            "TELEGRAM_SESSION_KEY is not a valid Fernet key. "
            'Generate with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from exc


def session_working_path(session_name: str) -> Path:
    """Telethon working SQLite path (``…/name.session``)."""
    base = Path(session_name)
    if base.suffix == SESSION_SUFFIX:
        return base
    return Path(str(base) + SESSION_SUFFIX)


def session_sealed_path(session_name: str) -> Path:
    """Durable sealed path (``…/name.session.enc``)."""
    return Path(str(session_working_path(session_name)) + ".enc")


def encryption_enabled(key: str | None) -> bool:
    return bool(key and key.strip())


def _sidecar_paths(working: Path) -> list[Path]:
    """SQLite WAL/SHM/journal leftovers beside the working session."""
    return [
        Path(str(working) + "-wal"),
        Path(str(working) + "-shm"),
        Path(str(working) + "-journal"),
    ]


def wipe_working_session(working: Path) -> None:
    """Delete working plaintext session and WAL/shm/journal sidecars."""
    for path in [working, *_sidecar_paths(working)]:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("session_sidecar_unlink_failed", path=str(path), exc_info=True)


def unseal_session_for_use(session_name: str, key: str | None) -> Path:
    """Ensure a working ``.session`` exists before opening ``_WALSQLiteSession``.

    - Key set + working plaintext already present → keep it (crash recovery:
      may be newer than last seal; do **not** wipe from stale ``.enc``).
    - Key set + only ``.enc`` → decrypt to working path (clean sidecars).
    - Key set + only plaintext → leave plaintext (one-shot seal after use).
    - Key empty + only ``.enc`` → fail closed.
    - Key empty + plaintext → legacy (no encrypt).
    """
    working = session_working_path(session_name)
    sealed = session_sealed_path(session_name)
    key_set = encryption_enabled(key)

    if not key_set:
        if sealed.exists() and not working.exists():
            raise SessionCryptoError(
                f"Encrypted Telethon session found at {sealed} but "
                "TELEGRAM_SESSION_KEY is not set. Set the Fernet key to unseal, "
                "or restore a plaintext .session for break-glass recovery."
            )
        return working

    assert key is not None

    # Prefer a non-empty working file over re-decrypting a possibly stale seal
    # (process crash between Telethon write and seal_session_at_rest).
    # Zero-byte leftovers after a partial crash must not block fallback to .enc.
    if working.exists() and working.stat().st_size > 0:
        logger.info("telethon_session_using_existing_working", path=str(working))
        return working

    if sealed.exists():
        fernet = _fernet_from_key(key.strip())
        try:
            plaintext = fernet.decrypt(sealed.read_bytes())
        except InvalidToken as exc:
            raise SessionCryptoError(
                "Failed to decrypt Telethon session: TELEGRAM_SESSION_KEY does not "
                "match the sealed blob (or the file is corrupt)."
            ) from exc
        working.parent.mkdir(parents=True, exist_ok=True)
        # Clean WAL/shm before writing a fresh unseal (no stale sidecars).
        wipe_working_session(working)
        working.write_bytes(plaintext)
        try:
            os.chmod(working, 0o600)
        except OSError:
            pass
        logger.info("telethon_session_unsealed", path=str(working))
        return working

    # No sealed blob and no usable working file: first auth / empty path.
    return working


def seal_session_at_rest(session_name: str, key: str | None) -> Path | None:
    """Seal working ``.session`` to ``.session.enc`` and wipe plaintext.

    No-op when key is empty. Returns sealed path when a seal was written.
    """
    if not encryption_enabled(key):
        return None

    assert key is not None
    working = session_working_path(session_name)
    sealed = session_sealed_path(session_name)

    if not working.exists():
        logger.warning("telethon_session_seal_skipped_missing", path=str(working))
        return None

    fernet = _fernet_from_key(key.strip())
    # Ensure SQLite has flushed; caller should disconnect Telethon first.
    plaintext = working.read_bytes()
    if not plaintext:
        raise SessionCryptoError(f"Refusing to seal empty session file: {working}")

    sealed.parent.mkdir(parents=True, exist_ok=True)
    tmp = sealed.with_suffix(sealed.suffix + ".tmp")
    tmp.write_bytes(fernet.encrypt(plaintext))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(sealed)

    wipe_working_session(working)
    logger.info("telethon_session_sealed", path=str(sealed))
    return sealed
