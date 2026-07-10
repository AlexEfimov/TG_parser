"""Shared per-channel Postgres advisory-lock helper (BUG-073).

Generalises the proven session-scoped-advisory-lock-on-a-dedicated-connection
pattern first introduced for the scheduler (``_source_processing_lock`` —
BUG-068 Fix 4) and the full-topicization funnel (``channel_topicization_lock``
— BUG-072) so the processing stage (F1) and the incremental-topicization stage
(F3) can reuse it without copy-pasting the connection/unlock/leak handling.

The two pre-existing locks are intentionally left untouched (they are heavily
unit-tested by name); this helper is the single implementation that all NEW
per-channel guards delegate to.

Design invariants (identical to the originals):

* A SESSION-scoped ``pg_try_advisory_lock(:ns, hashtext(:key))`` on a DEDICATED
  connection held open for the whole guarded run — a full stage spans many
  transactions/batches, so a transaction-scoped lock cannot cover it.
* The dedicated connection is NEVER returned to the pool while the lock is
  held, avoiding the classic footgun of a session lock leaking onto a pooled
  connection across commits.
* ``pg_advisory_unlock`` + ``conn.close()`` in ``finally`` (unlock guarded by
  ``acquired`` and its own ``try/except`` so an unlock hiccup cannot mask the
  caller's outcome or leak the connection).
* NON-BLOCKING (``pg_try_advisory_lock``): yields ``True`` if the lock was
  acquired (caller should run) or ``False`` if another holder owns the key
  (caller should benign-skip / defer).
* DEGRADES to ``True`` when the DB/engine is unavailable (e.g. unit tests with
  no initialized DB) so lock-infra problems never block the pipeline.

The two-arg key is ``(namespace, hashtext(normalize_channel_id(channel_id)))``
so every caller that identifies the channel by its normalized id contends on
the same lock regardless of which entry path triggered the run.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import structlog

logger = structlog.get_logger(__name__)


@contextlib.asynccontextmanager
async def channel_advisory_lock(
    channel_id: str,
    *,
    namespace: int,
    engine_attr: str,
    label: str,
) -> AsyncIterator[bool]:
    """Acquire a non-blocking per-channel advisory lock; yield whether acquired.

    Args:
        channel_id: raw channel id (normalized internally).
        namespace: int4 advisory-lock namespace (the first key of the two-key
            ``pg_try_advisory_lock`` form). MUST be distinct per guard so the
            different guards never collide in the shared advisory keyspace.
        engine_attr: attribute name of the :class:`Database` async engine to
            take the dedicated connection from (e.g.
            ``"advisory_lock_engine"`` — BUG-082 dedicated lock pool).
        label: short identifier used in the unlock-failure log line.
    """
    from sqlalchemy import text as _sa_text

    from tg_parser.storage.sqlalchemy.database import Database
    from tg_parser.utils.channel_id import normalize_channel_id

    key = normalize_channel_id(channel_id) or channel_id

    try:
        db = Database.get_instance()
        engine = getattr(db, engine_attr, None)
    except Exception:  # noqa: BLE001 — no DB context → no cross-process guard
        engine = None

    if engine is None:
        yield True
        return

    conn = await engine.connect()
    acquired = False
    try:
        row = await conn.execute(
            _sa_text("SELECT pg_try_advisory_lock(:ns, hashtext(:cid))"),
            {"ns": namespace, "cid": key},
        )
        acquired = bool(row.scalar())
        yield acquired
    finally:
        if acquired:
            try:
                await conn.execute(
                    _sa_text("SELECT pg_advisory_unlock(:ns, hashtext(:cid))"),
                    {"ns": namespace, "cid": key},
                )
            except Exception as unlock_exc:  # noqa: BLE001
                logger.warning(
                    "%s_unlock_failed channel=%s: %s",
                    label,
                    channel_id,
                    unlock_exc,
                )
        await conn.close()
