"""
Cleanup helper for orphan admin users from pre-DI-11 deployments.

Pre-DI-11 (commit 0fafe63), `tg-parser migrate-users` could create a SECOND
admin user alongside the one seeded by migration ``b2c3d4e5f6a7``: the
older row (orphan, no auth_mappings, no owned sources/digests) and the
younger one (created by migrate-users, holding all mappings).

This module wraps the cleanup transaction documented in
``docs/runbooks/DEV_RESURRECTION.md`` FAQ section
"Как почистить duplicate admin от pre-DI-11 deployment'а" into a
reusable, typer-friendly entry point.

Safety invariants:

* Only deletes when target user has role='admin'.
* Refuses to delete the LAST admin (would brick the deployment).
* Verifies FK count == 0 in three tables before DELETE:
  - ``user_auth_mappings.user_id``
  - ``sources.owner_id``
  - ``digest_subscriptions.owner_id``
* Re-checks FK counts inside the same transaction immediately before
  DELETE (TOCTOU safety against concurrent writers).
* Explicit rollback on any failure.

Out of scope (intentionally — see DI-14/§3 plan):

* Reassigning FKs to a different user (`--reassign-to`). Future iteration.
* Soft-delete / archive. Hard DELETE only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


class OrphanAdminCleanupError(Exception):
    """Raised when cleanup cannot proceed safely."""


@dataclass(frozen=True)
class FKReport:
    """Foreign-key reference counts for a candidate orphan user."""

    user_auth_mappings: int
    sources: int
    digest_subscriptions: int

    @property
    def total(self) -> int:
        return self.user_auth_mappings + self.sources + self.digest_subscriptions

    @property
    def is_clean(self) -> bool:
        return self.total == 0


@dataclass
class CleanupResult:
    """Outcome of `run_cleanup_orphan_admin` call."""

    orphan_uuid: str
    deleted: bool
    dry_run: bool
    fk_report: FKReport
    admins_before: int
    admins_after: int
    user_name: str | None
    rollback: bool = False


def _validate_uuid(value: str) -> str:
    """Normalize and validate a UUID string. Returns lowercase canonical form."""
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OrphanAdminCleanupError(
            f"Invalid UUID format: {value!r} (expected canonical UUID, e.g. 'b2c3d4e5-f6a7-...').",
        ) from exc


async def _fetch_user(session, orphan_id: str) -> dict[str, Any] | None:
    result = await session.execute(
        text("SELECT id, name, role FROM users WHERE id = :id"),
        {"id": orphan_id},
    )
    row = result.fetchone()
    return {"id": str(row.id), "name": row.name, "role": row.role} if row else None


async def _count_admins(session) -> int:
    result = await session.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'"))
    return int(result.scalar() or 0)


async def _fk_report(session, orphan_id: str) -> FKReport:
    queries = {
        "user_auth_mappings": "SELECT COUNT(*) FROM user_auth_mappings WHERE user_id = :id",
        "sources": "SELECT COUNT(*) FROM sources WHERE owner_id = :id",
        "digest_subscriptions": ("SELECT COUNT(*) FROM digest_subscriptions WHERE owner_id = :id"),
    }
    counts: dict[str, int] = {}
    for name, sql in queries.items():
        result = await session.execute(text(sql), {"id": orphan_id})
        counts[name] = int(result.scalar() or 0)
    return FKReport(**counts)


async def run_cleanup_orphan_admin(
    orphan_uuid: str,
    *,
    dry_run: bool = False,
) -> CleanupResult:
    """Verify and delete an orphan admin user.

    Raises:
        OrphanAdminCleanupError: when cleanup cannot proceed (invalid UUID,
            user not found, user is not admin, last admin, or FK count > 0).
            Message is human-readable and safe to print to the operator.
    """
    from tg_parser.services.db_context import user_repo
    from tg_parser.storage.sqlalchemy import Database

    orphan_id = _validate_uuid(orphan_uuid)

    db = Database.get_instance()
    await db.init()

    try:
        async with user_repo() as (repo, _db):
            session = repo.session

            user = await _fetch_user(session, orphan_id)
            if user is None:
                raise OrphanAdminCleanupError(
                    f"User {orphan_id} not found. Run "
                    "`docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser "
                    '-c "SELECT id, name, role, created_at FROM users ORDER BY created_at;"` '
                    "to inspect the users table.",
                )

            if user["role"] != "admin":
                raise OrphanAdminCleanupError(
                    f"User {orphan_id} has role={user['role']!r}, not 'admin'. "
                    "This command only deletes orphan admin rows from pre-DI-11 "
                    "deployments. For non-admin user deletion use the user_repo API.",
                )

            admins_before = await _count_admins(session)
            if admins_before <= 1:
                raise OrphanAdminCleanupError(
                    f"Refusing to delete the last admin (count={admins_before}). "
                    "This would leave the deployment without an authenticated owner. "
                    "If you really want to delete this user, create a replacement admin first.",
                )

            fk_report = await _fk_report(session, orphan_id)

            if not fk_report.is_clean:
                breakdown = (
                    f"user_auth_mappings={fk_report.user_auth_mappings}, "
                    f"sources={fk_report.sources}, "
                    f"digest_subscriptions={fk_report.digest_subscriptions}"
                )
                raise OrphanAdminCleanupError(
                    f"User {orphan_id} is NOT orphan — has {fk_report.total} FK reference(s): "
                    f"{breakdown}. Reassign these to another user before cleanup. "
                    "Manual SQL:\n"
                    f"  UPDATE user_auth_mappings   SET user_id  = '<keep_uuid>' WHERE user_id  = '{orphan_id}';\n"
                    f"  UPDATE sources              SET owner_id = '<keep_uuid>' WHERE owner_id = '{orphan_id}';\n"
                    f"  UPDATE digest_subscriptions SET owner_id = '<keep_uuid>' WHERE owner_id = '{orphan_id}';\n"
                    "(future iteration: --reassign-to <uuid> flag).",
                )

            if dry_run:
                logger.info(
                    "cleanup_orphan_admin_dry_run",
                    orphan_uuid=orphan_id,
                    user_name=user["name"],
                    admins_before=admins_before,
                )
                return CleanupResult(
                    orphan_uuid=orphan_id,
                    deleted=False,
                    dry_run=True,
                    fk_report=fk_report,
                    admins_before=admins_before,
                    admins_after=admins_before,
                    user_name=user["name"],
                )

            # TOCTOU safety: re-check FK + admin count inside the same transaction
            # immediately before DELETE. If a concurrent writer attached an FK or
            # deleted the other admin between the first check and now, abort.
            try:
                fk_recheck = await _fk_report(session, orphan_id)
                if not fk_recheck.is_clean:
                    raise OrphanAdminCleanupError(
                        "Concurrent FK reference appeared between initial check and DELETE "
                        f"(now: user_auth_mappings={fk_recheck.user_auth_mappings}, "
                        f"sources={fk_recheck.sources}, "
                        f"digest_subscriptions={fk_recheck.digest_subscriptions}). "
                        "Re-run after the writer settles.",
                    )

                admins_recheck = await _count_admins(session)
                if admins_recheck <= 1:
                    raise OrphanAdminCleanupError(
                        f"Concurrent admin deletion detected (count now {admins_recheck}). "
                        "Refusing to delete the last admin.",
                    )

                delete_result = await session.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": orphan_id},
                )
                deleted_rows = delete_result.rowcount or 0
                if deleted_rows != 1:
                    raise OrphanAdminCleanupError(
                        f"Expected to delete 1 row, DELETE affected {deleted_rows}. "
                        "Aborting transaction.",
                    )

                await session.commit()
                admins_after = await _count_admins(session)

                logger.info(
                    "cleanup_orphan_admin_deleted",
                    orphan_uuid=orphan_id,
                    user_name=user["name"],
                    admins_before=admins_before,
                    admins_after=admins_after,
                )

                return CleanupResult(
                    orphan_uuid=orphan_id,
                    deleted=True,
                    dry_run=False,
                    fk_report=fk_report,
                    admins_before=admins_before,
                    admins_after=admins_after,
                    user_name=user["name"],
                )

            except Exception:
                await session.rollback()
                logger.warning(
                    "cleanup_orphan_admin_rollback",
                    orphan_uuid=orphan_id,
                )
                raise

    finally:
        await Database.close_instance()
