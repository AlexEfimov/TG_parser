"""INSERT-only audit_log repository (F9 Phase 3)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class SAAuditLogRepo:
    """Append-only writer for ``audit_log`` (ingestion DB)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(
        self,
        *,
        action: str,
        outcome: str,
        actor_user_id: UUID | str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> UUID:
        """Insert one audit row. No update/delete helpers by design."""
        result = await self.session.execute(
            text(
                """
                INSERT INTO audit_log (
                    actor_user_id, action, resource_type, resource_id, outcome, meta
                )
                VALUES (
                    :actor_user_id, :action, :resource_type, :resource_id, :outcome,
                    CAST(:meta AS jsonb)
                )
                RETURNING id
                """
            ),
            {
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "meta": json.dumps(meta) if meta is not None else None,
            },
        )
        row = result.fetchone()
        await self.session.commit()
        return row.id
