"""
SQLAlchemy implementation of TopicLinkRepo (Cross-dev 3).
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.json_utils import stable_json_dumps, stable_json_loads
from tg_parser.domain.models import TopicLink
from tg_parser.storage.ports import TopicLinkRepo


class SATopicLinkRepo(TopicLinkRepo):
    """PostgreSQL-backed topic link repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, link: TopicLink) -> None:
        a, b = sorted([link.topic_id_a, link.topic_id_b])
        query = text("""
            INSERT INTO topic_links (topic_id_a, topic_id_b, similarity_score, shared_keywords_json, created_at)
            VALUES (:a, :b, :score, :kw_json, :created_at)
            ON CONFLICT (topic_id_a, topic_id_b) DO UPDATE SET
                similarity_score = excluded.similarity_score,
                shared_keywords_json = excluded.shared_keywords_json,
                created_at = excluded.created_at
        """)
        await self.session.execute(
            query,
            {
                "a": a,
                "b": b,
                "score": link.similarity_score,
                "kw_json": stable_json_dumps(link.shared_keywords)
                if link.shared_keywords
                else None,
                "created_at": link.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        await self.session.commit()

    async def upsert_batch(self, links: list[TopicLink]) -> int:
        if not links:
            return 0

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        CHUNK = 100
        total = 0

        for chunk_start in range(0, len(links), CHUNK):
            chunk = links[chunk_start : chunk_start + CHUNK]
            values_parts = []
            params: dict = {}

            for idx, link in enumerate(chunk):
                a, b = sorted([link.topic_id_a, link.topic_id_b])
                placeholder = f"(:a{idx}, :b{idx}, :s{idx}, :kw{idx}, :ca{idx})"
                values_parts.append(placeholder)
                params[f"a{idx}"] = a
                params[f"b{idx}"] = b
                params[f"s{idx}"] = link.similarity_score
                params[f"kw{idx}"] = (
                    stable_json_dumps(link.shared_keywords) if link.shared_keywords else None
                )
                params[f"ca{idx}"] = now

            values_sql = ", ".join(values_parts)
            query = text(f"""
                INSERT INTO topic_links (topic_id_a, topic_id_b, similarity_score, shared_keywords_json, created_at)
                VALUES {values_sql}
                ON CONFLICT (topic_id_a, topic_id_b) DO UPDATE SET
                    similarity_score = excluded.similarity_score,
                    shared_keywords_json = excluded.shared_keywords_json,
                    created_at = excluded.created_at
            """)
            await self.session.execute(query, params)
            total += len(chunk)

        await self.session.commit()
        return total

    async def get_by_topic_id(self, topic_id: str) -> list[TopicLink]:
        query = text("""
            SELECT topic_id_a, topic_id_b, similarity_score, shared_keywords_json, created_at
            FROM topic_links
            WHERE topic_id_a = :tid OR topic_id_b = :tid
            ORDER BY similarity_score DESC
        """)
        result = await self.session.execute(query, {"tid": topic_id})
        return [self._row_to_model(row) for row in result.fetchall()]

    async def list_all(self) -> list[TopicLink]:
        query = text("""
            SELECT topic_id_a, topic_id_b, similarity_score, shared_keywords_json, created_at
            FROM topic_links
            ORDER BY similarity_score DESC
        """)
        result = await self.session.execute(query)
        return [self._row_to_model(row) for row in result.fetchall()]

    async def delete_all(self) -> int:
        result = await self.session.execute(text("DELETE FROM topic_links"))
        await self.session.commit()
        return result.rowcount

    async def count(self) -> int:
        result = await self.session.execute(text("SELECT count(*) FROM topic_links"))
        return result.scalar() or 0

    @staticmethod
    def _row_to_model(row) -> TopicLink:
        shared_kw = stable_json_loads(row.shared_keywords_json) if row.shared_keywords_json else []
        created_str = row.created_at
        created_dt = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return TopicLink(
            topic_id_a=row.topic_id_a,
            topic_id_b=row.topic_id_b,
            similarity_score=float(row.similarity_score),
            shared_keywords=shared_kw,
            created_at=created_dt,
        )
