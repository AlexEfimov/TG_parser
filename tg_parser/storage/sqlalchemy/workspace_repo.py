"""SQLAlchemy implementation of WorkspaceRepo (F4-B Core)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import Workspace
from tg_parser.storage.ports import WorkspaceRepo

_SELECT_COLUMNS = "id, owner_id, name, description, created_at, updated_at"


class SAWorkspaceRepo(WorkspaceRepo):
    """PostgreSQL-backed workspace repository (ingestion DB).

    Mirrors the structure of :class:`SADigestSubscriptionRepo` — short
    SQL strings via :func:`sqlalchemy.text`, explicit ``commit`` after each
    write so callers can rely on the row being visible to subsequent
    sessions.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        description: str | None = None,
    ) -> Workspace:
        query = text(
            f"""
            INSERT INTO workspaces (owner_id, name, description)
            VALUES (:owner_id, :name, :description)
            RETURNING {_SELECT_COLUMNS}
            """
        )
        result = await self.session.execute(
            query,
            {"owner_id": owner_id, "name": name, "description": description},
        )
        row = result.fetchone()
        await self.session.commit()
        return self._row_to_model(row)

    async def get(self, workspace_id: str) -> Workspace | None:
        result = await self.session.execute(
            text(f"SELECT {_SELECT_COLUMNS} FROM workspaces WHERE id = :id"),
            {"id": workspace_id},
        )
        row = result.fetchone()
        return self._row_to_model(row) if row else None

    async def list_by_owner(self, owner_id: str) -> list[Workspace]:
        result = await self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM workspaces "
                f"WHERE owner_id = :owner_id ORDER BY created_at"
            ),
            {"owner_id": owner_id},
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    async def list_all(self, owner_id: str | None = None) -> list[Workspace]:
        if owner_id is not None:
            return await self.list_by_owner(owner_id)
        result = await self.session.execute(
            text(f"SELECT {_SELECT_COLUMNS} FROM workspaces ORDER BY created_at"),
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    async def rename(self, workspace_id: str, new_name: str) -> Workspace | None:
        result = await self.session.execute(
            text(
                f"UPDATE workspaces SET name = :name, updated_at = NOW() "
                f"WHERE id = :id RETURNING {_SELECT_COLUMNS}"
            ),
            {"id": workspace_id, "name": new_name},
        )
        row = result.fetchone()
        await self.session.commit()
        return self._row_to_model(row) if row else None

    async def delete(self, workspace_id: str) -> bool:
        result = await self.session.execute(
            text("DELETE FROM workspaces WHERE id = :id"),
            {"id": workspace_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def add_source(self, workspace_id: str, source_id: str) -> bool:
        result = await self.session.execute(
            text(
                "INSERT INTO workspace_sources (workspace_id, source_id) "
                "VALUES (:workspace_id, :source_id) ON CONFLICT DO NOTHING"
            ),
            {"workspace_id": workspace_id, "source_id": source_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def remove_source(self, workspace_id: str, source_id: str) -> bool:
        result = await self.session.execute(
            text(
                "DELETE FROM workspace_sources "
                "WHERE workspace_id = :workspace_id AND source_id = :source_id"
            ),
            {"workspace_id": workspace_id, "source_id": source_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def list_source_ids(self, workspace_id: str) -> list[str]:
        result = await self.session.execute(
            text(
                "SELECT source_id FROM workspace_sources "
                "WHERE workspace_id = :workspace_id ORDER BY source_id"
            ),
            {"workspace_id": workspace_id},
        )
        return [row.source_id for row in result.fetchall()]

    async def list_channel_ids(self, workspace_id: str) -> list[str]:
        result = await self.session.execute(
            text(
                "SELECT s.channel_id FROM workspace_sources ws "
                "JOIN sources s ON s.source_id = ws.source_id "
                "WHERE ws.workspace_id = :workspace_id "
                "AND s.deleted_at IS NULL "
                "ORDER BY s.channel_id"
            ),
            {"workspace_id": workspace_id},
        )
        return [row.channel_id for row in result.fetchall()]

    async def resolve_source_id_for_channel(
        self,
        *,
        owner_id: str | None,
        channel_id: str,
    ) -> str | None:
        if owner_id is not None:
            result = await self.session.execute(
                text(
                    "SELECT source_id FROM sources "
                    "WHERE channel_id = :channel_id AND owner_id = :owner_id "
                    "AND deleted_at IS NULL "
                    "ORDER BY source_id LIMIT 1"
                ),
                {"channel_id": channel_id, "owner_id": owner_id},
            )
        else:
            result = await self.session.execute(
                text(
                    "SELECT source_id FROM sources "
                    "WHERE channel_id = :channel_id AND deleted_at IS NULL "
                    "ORDER BY source_id LIMIT 1"
                ),
                {"channel_id": channel_id},
            )
        row = result.fetchone()
        return row.source_id if row else None

    @staticmethod
    def _row_to_model(row: Any) -> Workspace:
        return Workspace(
            id=str(row.id),
            owner_id=str(row.owner_id),
            name=row.name,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
