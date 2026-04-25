"""SQLAlchemy implementation of WatchInterestRepo (F11 Topic Watchlist).

Storage: PostgreSQL ``watch_interests`` (ingestion DB; pgvector ``embedding``
column).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import NotifyMode, WatchInterest
from tg_parser.storage.ports import WatchInterestRepo

_SELECT_COLUMNS = (
    "id, user_id, chat_id, title, description, "
    "keywords, exclude_keywords, channel_ids, "
    "threshold, notify_mode, is_active, "
    "embedding::text AS embedding_text, "
    "last_checked_at, last_match_at, "
    "created_at, updated_at"
)


class SAWatchInterestRepo(WatchInterestRepo):
    """PostgreSQL-backed watch-interest repository (ingestion DB)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, interest: WatchInterest) -> WatchInterest:
        provided_id = (interest.id or "").strip()
        embedding_param = str(list(interest.embedding)) if interest.embedding is not None else None

        if provided_id:
            query = text(f"""
                INSERT INTO watch_interests
                    (id, user_id, chat_id, title, description,
                     keywords, exclude_keywords, channel_ids,
                     threshold, notify_mode, is_active,
                     embedding, last_checked_at, last_match_at)
                VALUES
                    (:id, :user_id, :chat_id, :title, :description,
                     :keywords, :exclude_keywords, :channel_ids,
                     :threshold, :notify_mode, :is_active,
                     CAST(:embedding AS vector),
                     :last_checked_at, :last_match_at)
                RETURNING {_SELECT_COLUMNS}
            """)
            params: dict[str, Any] = {"id": provided_id}
        else:
            query = text(f"""
                INSERT INTO watch_interests
                    (user_id, chat_id, title, description,
                     keywords, exclude_keywords, channel_ids,
                     threshold, notify_mode, is_active,
                     embedding, last_checked_at, last_match_at)
                VALUES
                    (:user_id, :chat_id, :title, :description,
                     :keywords, :exclude_keywords, :channel_ids,
                     :threshold, :notify_mode, :is_active,
                     CAST(:embedding AS vector),
                     :last_checked_at, :last_match_at)
                RETURNING {_SELECT_COLUMNS}
            """)
            params = {}

        params.update(
            {
                "user_id": interest.user_id,
                "chat_id": interest.chat_id,
                "title": interest.title,
                "description": interest.description,
                "keywords": list(interest.keywords),
                "exclude_keywords": list(interest.exclude_keywords),
                "channel_ids": list(interest.channel_ids),
                "threshold": float(interest.threshold),
                "notify_mode": str(interest.notify_mode.value),
                "is_active": interest.is_active,
                "embedding": embedding_param,
                "last_checked_at": interest.last_checked_at,
                "last_match_at": interest.last_match_at,
            }
        )

        result = await self.session.execute(query, params)
        row = result.fetchone()
        await self.session.commit()
        return self._row_to_model(row)

    async def get(self, interest_id: str) -> WatchInterest | None:
        result = await self.session.execute(
            text(f"SELECT {_SELECT_COLUMNS} FROM watch_interests WHERE id = :id"),
            {"id": interest_id},
        )
        row = result.fetchone()
        return self._row_to_model(row) if row else None

    async def list_for_user(self, user_id: str) -> list[WatchInterest]:
        result = await self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM watch_interests "
                f"WHERE user_id = :user_id ORDER BY created_at"
            ),
            {"user_id": user_id},
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    async def list_active_for_channel(self, channel_id: str) -> list[WatchInterest]:
        result = await self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM watch_interests "
                f"WHERE is_active = TRUE AND :channel_id = ANY(channel_ids) "
                f"ORDER BY created_at"
            ),
            {"channel_id": channel_id},
        )
        return [self._row_to_model(row) for row in result.fetchall()]

    async def update_embedding(self, interest_id: str, embedding: list[float]) -> None:
        await self.session.execute(
            text(
                "UPDATE watch_interests "
                "SET embedding = CAST(:embedding AS vector), updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"id": interest_id, "embedding": str(list(embedding))},
        )
        await self.session.commit()

    async def soft_delete(self, interest_id: str) -> bool:
        result = await self.session.execute(
            text(
                "UPDATE watch_interests "
                "SET is_active = FALSE, updated_at = NOW() "
                "WHERE id = :id AND is_active = TRUE"
            ),
            {"id": interest_id},
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def touch_checked(self, interest_id: str, at: datetime) -> None:
        await self.session.execute(
            text(
                "UPDATE watch_interests "
                "SET last_checked_at = :at, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"id": interest_id, "at": at},
        )
        await self.session.commit()

    async def touch_match(self, interest_id: str, at: datetime) -> None:
        await self.session.execute(
            text(
                "UPDATE watch_interests SET last_match_at = :at, updated_at = NOW() WHERE id = :id"
            ),
            {"id": interest_id, "at": at},
        )
        await self.session.commit()

    @staticmethod
    def _row_to_model(row: Any) -> WatchInterest:
        embedding_text = getattr(row, "embedding_text", None)
        embedding = _parse_pgvector_text(embedding_text) if embedding_text else None
        return WatchInterest(
            id=str(row.id),
            user_id=str(row.user_id),
            chat_id=int(row.chat_id),
            title=row.title,
            description=row.description,
            keywords=list(row.keywords or []),
            exclude_keywords=list(row.exclude_keywords or []),
            channel_ids=list(row.channel_ids or []),
            threshold=float(row.threshold),
            notify_mode=NotifyMode(row.notify_mode),
            is_active=bool(row.is_active),
            embedding=embedding,
            last_checked_at=row.last_checked_at,
            last_match_at=row.last_match_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _parse_pgvector_text(value: str) -> list[float]:
    """Parse pgvector text representation '[0.1,0.2,...]' into list[float]."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [float(x) for x in value.split(",") if x.strip()]
