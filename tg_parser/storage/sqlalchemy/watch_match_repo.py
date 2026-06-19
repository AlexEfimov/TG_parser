"""SQLAlchemy implementation of WatchMatchRepo (F11 Topic Watchlist).

Storage: PostgreSQL ``watch_matches`` (ingestion DB) with
``UNIQUE(interest_id, source_ref)`` for idempotent batch inserts.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import WatchMatch
from tg_parser.storage.ports import WatchMatchRepo

_SELECT_COLUMNS = (
    "id, interest_id, source_ref, channel_id, "
    "keyword_score, semantic_score, combined_score, "
    "notified, created_at"
)


class SAWatchMatchRepo(WatchMatchRepo):
    """PostgreSQL-backed watch-match repository (ingestion DB)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_many(self, matches: list[WatchMatch]) -> list[WatchMatch]:
        """Idempotent batch insert via ``ON CONFLICT DO NOTHING RETURNING``.

        Returns only the rows that were actually inserted: a re-run of the
        pipeline on the same (interest_id, source_ref) pair returns an empty
        list, so ``WatchlistService.notify`` does not re-deliver matches.
        """
        if not matches:
            return []

        values_parts: list[str] = []
        params: dict[str, Any] = {}
        for idx, match in enumerate(matches):
            placeholder = f"(:iid{idx}, :sr{idx}, :ch{idx}, :ks{idx}, :ss{idx}, :cs{idx}, :nt{idx})"
            values_parts.append(placeholder)
            params[f"iid{idx}"] = match.interest_id
            params[f"sr{idx}"] = match.source_ref
            params[f"ch{idx}"] = match.channel_id
            params[f"ks{idx}"] = float(match.keyword_score)
            params[f"ss{idx}"] = float(match.semantic_score)
            params[f"cs{idx}"] = float(match.combined_score)
            params[f"nt{idx}"] = bool(match.notified)

        values_sql = ", ".join(values_parts)
        query = text(f"""
            INSERT INTO watch_matches
                (interest_id, source_ref, channel_id,
                 keyword_score, semantic_score, combined_score, notified)
            VALUES {values_sql}
            ON CONFLICT ON CONSTRAINT uq_watch_matches_interest_source DO NOTHING
            RETURNING {_SELECT_COLUMNS}
        """)

        result = await self.session.execute(query, params)
        rows = result.fetchall()
        await self.session.commit()
        return [self._row_to_model(row) for row in rows]

    async def list_for_interest(
        self, interest_id: str, since: datetime | None = None
    ) -> list[WatchMatch]:
        if since is None:
            query = text(
                f"SELECT {_SELECT_COLUMNS} FROM watch_matches "
                f"WHERE interest_id = :interest_id "
                f"ORDER BY created_at"
            )
            params = {"interest_id": interest_id}
        else:
            query = text(
                f"SELECT {_SELECT_COLUMNS} FROM watch_matches "
                f"WHERE interest_id = :interest_id AND created_at > :since "
                f"ORDER BY created_at"
            )
            params = {"interest_id": interest_id, "since": since}

        result = await self.session.execute(query, params)
        return [self._row_to_model(row) for row in result.fetchall()]

    async def list_unnotified_for_interests(self, interest_ids: list[str]) -> list[WatchMatch]:
        """Pending (``notified = false``) matches for the given interests (ADR-0014).

        Backs the F11 P2 global batch flush: ``notified`` is the batch
        watermark, so this selects every not-yet-delivered match for the
        active batch-mode interests in one round-trip. Ordered by
        ``created_at`` ascending for deterministic per-interest grouping.
        """
        if not interest_ids:
            return []
        query = text(
            f"SELECT {_SELECT_COLUMNS} FROM watch_matches "
            f"WHERE notified = FALSE "
            f"AND interest_id = ANY(CAST(:interest_ids AS uuid[])) "
            f"ORDER BY created_at"
        )
        result = await self.session.execute(query, {"interest_ids": interest_ids})
        return [self._row_to_model(row) for row in result.fetchall()]

    async def mark_notified(self, match_ids: list[int]) -> None:
        if not match_ids:
            return
        await self.session.execute(
            text("UPDATE watch_matches SET notified = TRUE WHERE id = ANY(CAST(:ids AS bigint[]))"),
            {"ids": match_ids},
        )
        await self.session.commit()

    @staticmethod
    def _row_to_model(row: Any) -> WatchMatch:
        return WatchMatch(
            id=int(row.id),
            interest_id=str(row.interest_id),
            source_ref=row.source_ref,
            channel_id=row.channel_id,
            keyword_score=float(row.keyword_score),
            semantic_score=float(row.semantic_score),
            combined_score=float(row.combined_score),
            notified=bool(row.notified),
            created_at=row.created_at,
        )
