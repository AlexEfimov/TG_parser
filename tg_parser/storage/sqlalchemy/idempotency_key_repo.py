"""SQLAlchemy implementation of IdempotencyKeyRepo (Wave 1 step 3 commit 4/4).

Storage: PostgreSQL ``idempotency_keys`` (ingestion DB), created by migration
``f1a2b3c4d5e6``. This repo is the persistence backend for the Stripe-style
HTTP middleware in ``tg_parser/api/idempotency.py`` (opt-in per Q-OPEN-7 on
``POST /api/v1/watchlists`` + ``POST /api/v1/digests``); ADR 0009 Option C
hybrid.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import IdempotencyKey
from tg_parser.storage.ports import IdempotencyKeyRepo


class SAIdempotencyKeyRepo(IdempotencyKeyRepo):
    """PostgreSQL-backed Idempotency-Key repository (ingestion DB).

    Every method commits on its own — the table has no transactional
    coupling with the endpoints it serves (a successful POST that
    crashes before ``insert(...)`` simply replays as a cache miss on
    retry, which is harmless given the service-layer natural-key
    upsert collapses duplicates).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_key(self, *, key: str, user_id: str) -> IdempotencyKey | None:
        result = await self.session.execute(
            text(
                "SELECT key, user_id, request_hash, response_body, created_at "
                "FROM idempotency_keys "
                "WHERE key = :key AND user_id = :user_id"
            ),
            {"key": key, "user_id": user_id},
        )
        row = result.fetchone()
        if row is None:
            return None
        response_body = row.response_body
        if isinstance(response_body, str):
            response_body = json.loads(response_body)
        return IdempotencyKey(
            key=str(row.key),
            user_id=str(row.user_id),
            request_hash=str(row.request_hash),
            response_body=dict(response_body or {}),
            created_at=row.created_at,
        )

    async def insert(
        self,
        *,
        key: str,
        user_id: str,
        request_hash: str,
        response_body: dict[str, Any],
    ) -> None:
        """INSERT a fresh cache row.

        Uses ``ON CONFLICT (key) DO NOTHING`` so a benign race between
        two near-simultaneous first POSTs (same key, both miss the
        ``find_by_key`` check) collapses to one row instead of an
        :class:`IntegrityError`. The losing branch silently drops its
        response — both clients receive a valid 2xx and a subsequent
        replay will deterministically hit the surviving row.
        """
        await self.session.execute(
            text(
                "INSERT INTO idempotency_keys (key, user_id, request_hash, response_body) "
                "VALUES (:key, :user_id, :request_hash, CAST(:response_body AS jsonb)) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {
                "key": key,
                "user_id": user_id,
                "request_hash": request_hash,
                "response_body": json.dumps(response_body),
            },
        )
        await self.session.commit()

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            text("DELETE FROM idempotency_keys WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def count(self) -> int:
        result = await self.session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
        row = result.fetchone()
        return int(row[0]) if row is not None else 0
