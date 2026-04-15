"""
One-time migration: map existing API keys, MCP tokens, and bot user IDs
to the multi-tenancy user model.

Idempotent: safe to run multiple times — existing mappings are skipped.
"""

from typing import Any

import structlog

from tg_parser.auth.resolvers import hash_credential

logger = structlog.get_logger(__name__)


async def run_migrate_users(dry_run: bool = False) -> dict[str, Any]:
    """Migrate existing credentials to the F4 multi-tenancy user model.

    Steps:
        1. Create admin user (or reuse existing)
        2. Map settings.api_keys -> add_auth_mapping(admin, 'api_key', hash(key), client_name)
        3. Map settings.mcp_auth_tokens -> add_auth_mapping(admin, 'mcp_token', hash(token), client_name)
        4. Map settings.bot_allowed_user_ids -> add_auth_mapping(admin, 'telegram', str(uid))
        5. UPDATE sources SET owner_id = admin.id WHERE owner_id IS NULL
    """
    from sqlalchemy import text

    from tg_parser.config import settings
    from tg_parser.services.db_context import user_repo
    from tg_parser.storage.sqlalchemy import Database

    stats: dict[str, Any] = {
        "admin_user_id": None,
        "admin_created": False,
        "api_keys_mapped": 0,
        "mcp_tokens_mapped": 0,
        "telegram_users_mapped": 0,
        "orphan_sources_assigned": 0,
        "skipped_existing": 0,
        "dry_run": dry_run,
    }

    db = Database.get_instance()
    await db.init()

    try:
        async with user_repo() as (repo, _db):
            admin_user = None

            if settings.api_keys:
                first_key = next(iter(settings.api_keys))
                hashed_first = hash_credential(first_key)
                existing = await repo.resolve_auth("api_key", hashed_first)
                if existing:
                    admin_user = existing
                    logger.info("reusing_existing_admin", user_id=existing.id)

            if admin_user is None:
                if dry_run:
                    stats["admin_created"] = True
                    stats["admin_user_id"] = "(dry-run)"
                    logger.info("dry_run_would_create_admin")
                else:
                    admin_user = await repo.create_user("admin", role="admin")
                    stats["admin_created"] = True
                    logger.info("created_admin_user", user_id=admin_user.id)

            if admin_user:
                stats["admin_user_id"] = admin_user.id

            admin_id = admin_user.id if admin_user else None

            for raw_key, client_name in settings.api_keys.items():
                hashed = hash_credential(raw_key)
                existing = await repo.resolve_auth("api_key", hashed)
                if existing:
                    stats["skipped_existing"] += 1
                    continue
                if dry_run:
                    logger.info("dry_run_would_map_api_key", client_name=client_name)
                else:
                    await repo.add_auth_mapping(admin_id, "api_key", hashed, client_name)
                stats["api_keys_mapped"] += 1

            for raw_token, client_name in settings.mcp_auth_tokens.items():
                hashed = hash_credential(raw_token)
                existing = await repo.resolve_auth("mcp_token", hashed)
                if existing:
                    stats["skipped_existing"] += 1
                    continue
                if dry_run:
                    logger.info("dry_run_would_map_mcp_token", client_name=client_name)
                else:
                    await repo.add_auth_mapping(admin_id, "mcp_token", hashed, client_name)
                stats["mcp_tokens_mapped"] += 1

            for uid in settings.bot_allowed_user_ids:
                uid_str = str(uid)
                existing = await repo.resolve_auth("telegram", uid_str)
                if existing:
                    stats["skipped_existing"] += 1
                    continue
                if dry_run:
                    logger.info("dry_run_would_map_telegram", uid=uid_str)
                else:
                    await repo.add_auth_mapping(admin_id, "telegram", uid_str)
                stats["telegram_users_mapped"] += 1

            if admin_id and not dry_run:
                result = await repo.session.execute(
                    text("UPDATE sources SET owner_id = :admin_id WHERE owner_id IS NULL"),
                    {"admin_id": admin_id},
                )
                await repo.session.commit()
                stats["orphan_sources_assigned"] = result.rowcount or 0
            elif dry_run:
                result = await repo.session.execute(
                    text("SELECT COUNT(*) FROM sources WHERE owner_id IS NULL"),
                )
                row = result.fetchone()
                stats["orphan_sources_assigned"] = row[0] if row else 0

    finally:
        await Database.close_instance()

    return stats
