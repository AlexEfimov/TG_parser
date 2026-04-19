"""
CLI команда для добавления источника (add-source).

Реализует добавление канала в ingestion_state.
"""

from datetime import UTC, datetime

import structlog

from tg_parser.storage.ports import Source

logger = structlog.get_logger(__name__)


class AddSourceError(Exception):
    """Raised when add-source cannot be completed (e.g. no admin to assign)."""


async def run_add_source(
    source_id: str,
    channel_id: str,
    channel_username: str | None = None,
    include_comments: bool = False,
    batch_size: int | None = None,
    owner_id: str | None = None,
) -> None:
    """
    Добавить источник для ingestion (TR-15).

    Args:
        source_id: Идентификатор источника (уникальный ключ)
        channel_id: ID канала в Telegram
        channel_username: Username канала (опционально)
        include_comments: Собирать комментарии (TR-5)
        batch_size: Размер батча для ingestion
        owner_id: User UUID for ownership (DI-13). If None, auto-resolves to
            the seeded admin via UserRepo.find_first_by_role('admin'). Raises
            AddSourceError if no admin is found — callers must run
            ``tg-parser db upgrade`` (which seeds an admin) first or pass an
            explicit ``--owner-id``.
    """
    from tg_parser.services.db_context import ingestion_state_repo, user_repo

    resolved_owner_id = owner_id
    if resolved_owner_id is None:
        async with user_repo() as (repo, _db):
            admin = await repo.find_first_by_role("admin")
        if admin is None:
            raise AddSourceError(
                "DI-13: cannot add source — no admin user found and no "
                "--owner-id provided. Run `tg-parser db upgrade` to seed the "
                "default admin, or pass --owner-id <uuid> explicitly."
            )
        resolved_owner_id = admin.id
        logger.info("auto_resolved_admin_owner", owner_id=resolved_owner_id)

    async with ingestion_state_repo() as (state_repo, _db):
        existing = await state_repo.get_source(source_id)
        if existing:
            logger.info("Source %s already exists, updating...", source_id)

        source = Source(
            source_id=source_id,
            channel_id=channel_id,
            channel_username=channel_username,
            status="active",
            include_comments=include_comments,
            batch_size=batch_size or 100,
            created_at=existing.created_at if existing else datetime.now(UTC),
            updated_at=datetime.now(UTC),
            owner_id=resolved_owner_id,
        )

        await state_repo.upsert_source(source)

        logger.info(
            "Source added: %s (channel=%s, comments=%s, owner_id=%s)",
            source_id,
            channel_id,
            include_comments,
            resolved_owner_id,
        )
