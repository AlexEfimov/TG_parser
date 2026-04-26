"""SQLAlchemy implementation of ``TopicCardVersionRepo`` (F5-C audit log)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.json_utils import stable_json_dumps, stable_json_loads
from tg_parser.domain.models import TopicCardVersion
from tg_parser.storage.ports import TopicCardVersionRepo


class SATopicCardVersionRepo(TopicCardVersionRepo):
    """Append-only repository for ``topic_card_versions``.

    Schema (a4b5c6d7e8f9):
        id BIGSERIAL PRIMARY KEY,
        topic_id TEXT FK -> topic_cards(id) ON DELETE CASCADE,
        version_no INTEGER NOT NULL,
        summary TEXT NOT NULL,
        scope_in_json / scope_out_json TEXT NOT NULL,
        supporting_items_count_at_time INTEGER NOT NULL,
        llm_provider VARCHAR(50) NULL,
        llm_model VARCHAR(200) NULL,
        prompt_version VARCHAR(50) NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(topic_id, version_no).

    The UNIQUE constraint is the "last line of defence" against double-write
    races (advisory lock is the first defence inside ResummarizationService).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(self, version: TopicCardVersion) -> int:
        """Insert and return the surrogate ``id``.

        Uses ``RETURNING id`` so callers can audit the persisted row.
        ``created_at`` is filled by the DB DEFAULT (NOW()) — we
        intentionally do NOT pass ``version.created_at`` to keep the
        DB clock authoritative for "when was this snapshot stored".
        """
        query = text("""
            INSERT INTO topic_card_versions (
                topic_id, version_no, summary, scope_in_json, scope_out_json,
                supporting_items_count_at_time, llm_provider, llm_model, prompt_version
            ) VALUES (
                :topic_id, :version_no, :summary, :scope_in_json, :scope_out_json,
                :supporting_items_count_at_time, :llm_provider, :llm_model, :prompt_version
            )
            RETURNING id
        """)
        result = await self.session.execute(
            query,
            {
                "topic_id": version.topic_id,
                "version_no": version.version_no,
                "summary": version.summary,
                "scope_in_json": stable_json_dumps(version.scope_in),
                "scope_out_json": stable_json_dumps(version.scope_out),
                "supporting_items_count_at_time": version.supporting_items_count_at_time,
                "llm_provider": version.llm_provider,
                "llm_model": version.llm_model,
                "prompt_version": version.prompt_version,
            },
        )
        new_id = result.scalar_one()
        await self.session.commit()
        return int(new_id)

    async def list_by_topic(self, topic_id: str, limit: int = 50) -> list[TopicCardVersion]:
        """List versions for a topic, newest first, capped at ``limit``."""
        query = text("""
            SELECT id, topic_id, version_no, summary, scope_in_json, scope_out_json,
                   supporting_items_count_at_time, llm_provider, llm_model, prompt_version,
                   created_at
            FROM topic_card_versions
            WHERE topic_id = :topic_id
            ORDER BY created_at DESC, version_no DESC
            LIMIT :limit
        """)
        result = await self.session.execute(query, {"topic_id": topic_id, "limit": limit})
        rows = result.fetchall()
        return [
            TopicCardVersion(
                id=row.id,
                topic_id=row.topic_id,
                version_no=row.version_no,
                summary=row.summary,
                scope_in=stable_json_loads(row.scope_in_json),
                scope_out=stable_json_loads(row.scope_out_json),
                supporting_items_count_at_time=row.supporting_items_count_at_time,
                llm_provider=row.llm_provider,
                llm_model=row.llm_model,
                prompt_version=row.prompt_version,
                created_at=row.created_at,
            )
            for row in rows
        ]
