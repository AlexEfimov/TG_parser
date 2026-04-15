"""
SQLAlchemy implementation of UserRepo (F4 Multi-Tenancy).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import User, UserAuthMapping, UserRepo


class SAUserRepo(UserRepo):
    """PostgreSQL-backed user repository (shares ingestion state DB)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self, name: str, role: str = "user", max_channels: int | None = None,
    ) -> User:
        query = text("""
            INSERT INTO users (name, role, max_channels)
            VALUES (:name, :role, :max_channels)
            RETURNING id, created_at, updated_at
        """)
        result = await self.session.execute(
            query, {"name": name, "role": role, "max_channels": max_channels},
        )
        row = result.fetchone()
        await self.session.commit()
        return User(
            id=str(row.id),
            name=name,
            role=role,
            max_channels=max_channels,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(
            text("SELECT id, name, role, max_channels, created_at, updated_at FROM users WHERE id = :id"),
            {"id": user_id},
        )
        row = result.fetchone()
        return self._row_to_user(row) if row else None

    async def resolve_auth(self, auth_type: str, auth_identifier: str) -> User | None:
        query = text("""
            SELECT u.id, u.name, u.role, u.max_channels, u.created_at, u.updated_at
            FROM users u
            JOIN user_auth_mappings m ON m.user_id = u.id
            WHERE m.auth_type = :auth_type AND m.auth_identifier = :auth_identifier
        """)
        result = await self.session.execute(
            query, {"auth_type": auth_type, "auth_identifier": auth_identifier},
        )
        row = result.fetchone()
        return self._row_to_user(row) if row else None

    async def get_owned_channel_ids(self, user_id: str) -> list[str]:
        result = await self.session.execute(
            text("SELECT channel_id FROM sources WHERE owner_id = :user_id ORDER BY channel_id"),
            {"user_id": user_id},
        )
        return [row.channel_id for row in result.fetchall()]

    async def add_auth_mapping(
        self,
        user_id: str,
        auth_type: str,
        auth_identifier: str,
        client_name: str | None = None,
    ) -> UserAuthMapping:
        query = text("""
            INSERT INTO user_auth_mappings (user_id, auth_type, auth_identifier, client_name)
            VALUES (:user_id, :auth_type, :auth_identifier, :client_name)
            RETURNING id, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "user_id": user_id,
                "auth_type": auth_type,
                "auth_identifier": auth_identifier,
                "client_name": client_name,
            },
        )
        row = result.fetchone()
        await self.session.commit()
        return UserAuthMapping(
            id=str(row.id),
            user_id=user_id,
            auth_type=auth_type,
            auth_identifier=auth_identifier,
            client_name=client_name,
            created_at=row.created_at,
        )

    async def remove_auth_mapping(self, mapping_id: str) -> bool:
        result = await self.session.execute(
            text("DELETE FROM user_auth_mappings WHERE id = :id"),
            {"id": mapping_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def list_users(self) -> list[User]:
        result = await self.session.execute(
            text("SELECT id, name, role, max_channels, created_at, updated_at FROM users ORDER BY created_at"),
        )
        return [self._row_to_user(row) for row in result.fetchall()]

    async def delete_user(self, user_id: str) -> bool:
        result = await self.session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": user_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def update_user(
        self, user_id: str, *, name: str | None = None, role: str | None = None, max_channels: Any = ...,
    ) -> User | None:
        sets: list[str] = []
        params: dict[str, Any] = {"id": user_id}

        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if role is not None:
            sets.append("role = :role")
            params["role"] = role
        if max_channels is not ...:
            sets.append("max_channels = :max_channels")
            params["max_channels"] = max_channels

        if not sets:
            return await self.get_by_id(user_id)

        sets.append("updated_at = NOW()")
        sql = f"UPDATE users SET {', '.join(sets)} WHERE id = :id"
        await self.session.execute(text(sql), params)
        await self.session.commit()
        return await self.get_by_id(user_id)

    @staticmethod
    def _row_to_user(row) -> User:
        return User(
            id=str(row.id),
            name=row.name,
            role=row.role,
            max_channels=row.max_channels,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
