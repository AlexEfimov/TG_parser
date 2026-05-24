"""
SQLAlchemy implementation of DigestSubscriptionRepo (F6 Scheduled Digests).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import DigestFormat, DigestSubscription, TargetKind
from tg_parser.storage.ports import DigestSubscriptionRepo

_SELECT_COLUMNS = (
    "id, owner_id, target_kind, chat_id, channel_id, name, channel_ids, "
    "cron_expression, timezone, format, language, is_active, last_sent_at, "
    "last_digest_cursor, workspace_id, created_at, updated_at"
)


class SADigestSubscriptionRepo(DigestSubscriptionRepo):
    """PostgreSQL-backed digest-subscription repository (ingestion DB)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, sub: DigestSubscription) -> DigestSubscription:
        # When the caller pre-allocates an id (e.g. so that the scheduler can
        # register the job before persistence), preserve it instead of relying
        # on the database's gen_random_uuid() default.
        provided_id = (sub.id or "").strip()
        target_kind = (
            sub.target_kind.value
            if isinstance(sub.target_kind, TargetKind)
            else str(sub.target_kind)
        )
        base_cols = (
            "owner_id, target_kind, chat_id, channel_id, name, channel_ids, "
            "cron_expression, timezone, format, language, is_active, "
            "last_sent_at, last_digest_cursor, workspace_id"
        )
        if provided_id:
            query = text(f"""
                INSERT INTO digest_subscriptions
                    (id, {base_cols})
                VALUES
                    (:id, :owner_id, :target_kind, :chat_id, :channel_id, :name,
                     :channel_ids, :cron_expression, :timezone, :format, :language,
                     :is_active, :last_sent_at, :last_digest_cursor, :workspace_id)
                RETURNING {_SELECT_COLUMNS}
            """)
            params: dict[str, Any] = {"id": provided_id}
        else:
            query = text(f"""
                INSERT INTO digest_subscriptions
                    ({base_cols})
                VALUES
                    (:owner_id, :target_kind, :chat_id, :channel_id, :name,
                     :channel_ids, :cron_expression, :timezone, :format, :language,
                     :is_active, :last_sent_at, :last_digest_cursor, :workspace_id)
                RETURNING {_SELECT_COLUMNS}
            """)
            params = {}
        params.update(
            {
                "owner_id": sub.owner_id,
                "target_kind": target_kind,
                "chat_id": sub.chat_id,
                "channel_id": sub.channel_id,
                "name": sub.name,
                "channel_ids": list(sub.channel_ids),
                "cron_expression": sub.cron_expression,
                "timezone": sub.timezone,
                "format": str(sub.format.value),
                "language": sub.language,
                "is_active": sub.is_active,
                "last_sent_at": sub.last_sent_at,
                "last_digest_cursor": sub.last_digest_cursor,
                "workspace_id": sub.workspace_id,
            }
        )
        result = await self.session.execute(query, params)
        row = result.fetchone()
        await self.session.commit()
        return self._row_to_model(row)

    async def get(self, subscription_id: str) -> DigestSubscription | None:
        result = await self.session.execute(
            text(f"SELECT {_SELECT_COLUMNS} FROM digest_subscriptions WHERE id = :id"),
            {"id": subscription_id},
        )
        row = result.fetchone()
        return self._row_to_model(row) if row else None

    async def find_by_owner_and_name(self, owner_id: str, name: str) -> DigestSubscription | None:
        result = await self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM digest_subscriptions "
                f"WHERE owner_id = :owner_id AND name = :name"
            ),
            {"owner_id": owner_id, "name": name},
        )
        row = result.fetchone()
        return self._row_to_model(row) if row else None

    async def update(
        self,
        subscription_id: str,
        *,
        is_active: bool | None = None,
        last_sent_at: datetime | None = None,
        last_digest_cursor: datetime | None = None,
        cron_expression: str | None = None,
        timezone: str | None = None,
        format: DigestFormat | None = None,
        language: str | None = None,
        chat_id: int | None = None,
        target_kind: TargetKind | str | None = None,
        channel_id: str | None = None,
        unset_channel_id: bool = False,
        name: str | None = None,
        channel_ids: list[str] | None = None,
        workspace_id: str | None = None,
        unset_workspace_id: bool = False,
    ) -> DigestSubscription | None:
        sets: list[str] = []
        params: dict[str, Any] = {"id": subscription_id}

        if is_active is not None:
            sets.append("is_active = :is_active")
            params["is_active"] = is_active
        if last_sent_at is not None:
            sets.append("last_sent_at = :last_sent_at")
            params["last_sent_at"] = last_sent_at
        if last_digest_cursor is not None:
            sets.append("last_digest_cursor = :last_digest_cursor")
            params["last_digest_cursor"] = last_digest_cursor
        if cron_expression is not None:
            sets.append("cron_expression = :cron_expression")
            params["cron_expression"] = cron_expression
        if timezone is not None:
            sets.append("timezone = :timezone")
            params["timezone"] = timezone
        if format is not None:
            sets.append("format = :format")
            params["format"] = str(format.value)
        if language is not None:
            sets.append("language = :language")
            params["language"] = language
        if target_kind is not None:
            sets.append("target_kind = :target_kind")
            params["target_kind"] = (
                target_kind.value if isinstance(target_kind, TargetKind) else str(target_kind)
            )
        if chat_id is not None:
            sets.append("chat_id = :chat_id")
            params["chat_id"] = chat_id
        if unset_channel_id:
            sets.append("channel_id = NULL")
        elif channel_id is not None:
            sets.append("channel_id = :channel_id")
            params["channel_id"] = channel_id
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if channel_ids is not None:
            sets.append("channel_ids = :channel_ids")
            params["channel_ids"] = list(channel_ids)
        if unset_workspace_id:
            sets.append("workspace_id = NULL")
        elif workspace_id is not None:
            sets.append("workspace_id = :workspace_id")
            params["workspace_id"] = workspace_id

        if not sets:
            return await self.get(subscription_id)

        sets.append("updated_at = NOW()")
        sql = (
            f"UPDATE digest_subscriptions SET {', '.join(sets)} "
            f"WHERE id = :id RETURNING {_SELECT_COLUMNS}"
        )
        result = await self.session.execute(text(sql), params)
        row = result.fetchone()
        await self.session.commit()
        return self._row_to_model(row) if row else None

    async def delete(self, subscription_id: str) -> bool:
        result = await self.session.execute(
            text("DELETE FROM digest_subscriptions WHERE id = :id"),
            {"id": subscription_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def list_by_owner(self, owner_id: str) -> list[DigestSubscription]:
        result = await self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM digest_subscriptions "
                f"WHERE owner_id = :owner_id ORDER BY created_at"
            ),
            {"owner_id": owner_id},
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    async def list_active(self) -> list[DigestSubscription]:
        result = await self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM digest_subscriptions "
                f"WHERE is_active = TRUE ORDER BY created_at"
            ),
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    async def list_all(self) -> list[DigestSubscription]:
        """Return every subscription regardless of ``is_active`` (admin views).

        Sorted by ``created_at`` ascending.
        """
        result = await self.session.execute(
            text(f"SELECT {_SELECT_COLUMNS} FROM digest_subscriptions ORDER BY created_at"),
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    @staticmethod
    def _row_to_model(row: Any) -> DigestSubscription:
        workspace_id_raw = getattr(row, "workspace_id", None)
        tk = getattr(row, "target_kind", "chat")
        return DigestSubscription(
            id=str(row.id),
            owner_id=str(row.owner_id),
            target_kind=TargetKind(tk),
            chat_id=int(row.chat_id) if row.chat_id is not None else None,
            channel_id=getattr(row, "channel_id", None),
            name=row.name,
            channel_ids=list(row.channel_ids or []),
            workspace_id=str(workspace_id_raw) if workspace_id_raw is not None else None,
            cron_expression=row.cron_expression,
            timezone=row.timezone,
            format=DigestFormat(row.format),
            language=row.language,
            is_active=bool(row.is_active),
            last_sent_at=row.last_sent_at,
            last_digest_cursor=row.last_digest_cursor,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
