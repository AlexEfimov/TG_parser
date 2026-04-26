"""
SQLAlchemy реализация TopicCardRepo (TR-43) + F5-C extensions.

F5-C Evolving Topic Summaries (a4b5c6d7e8f9):

* All five SQL blocks (``upsert``, ``get_by_id``, ``list_by_channel``,
  ``list_all``, ``list_by_channels``, ``_row_to_model``) read/write the
  three new columns: ``last_summarized_at``, ``summary_version``,
  ``new_items_since_last_summary``.
* ``increment_resummary_counter`` — single ``UPDATE`` bumping the F5-C
  trigger counter atomically; called from
  ``_update_bundles_for_assignments`` once per add_items batch.
* ``list_resummarize_candidates`` — partial-index scan returning topics
  whose counter crossed the threshold.
* ``commit_resummary`` — atomic, optimistic version-checked replacement
  of the older ``upsert + reset_after_resummary`` pair (Step 4 / Real-bug
  #2 in START_PROMPT_SPRINT_F5C.md).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.json_utils import (
    parse_iso_datetime,
    stable_json_dumps,
    stable_json_loads,
)
from tg_parser.domain.models import Anchor, TopicCard, TopicType
from tg_parser.storage.ports import TopicCardRepo

_TC_SELECT_COLUMNS = (
    "id, title, summary, scope_in_json, scope_out_json, type, "
    "anchors_json, sources_json, updated_at, tags_json, "
    "related_topics_json, status, metadata_json, "
    "last_summarized_at, summary_version, new_items_since_last_summary"
)


class SATopicCardRepo(TopicCardRepo):
    """
    SQLAlchemy реализация TopicCardRepo.

    Хранилище: PostgreSQL (таблица topic_cards)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, card: TopicCard) -> None:
        """
        TR-43: upsert/replace по id.
        TR-IF-4: id детерминирован (topic: + anchors[0].anchor_ref).

        F5-C: ``last_summarized_at`` / ``summary_version`` /
        ``new_items_since_last_summary`` are written from the model so
        round-trip via ``get_by_id`` preserves them; on first INSERT the
        DB-side ``DEFAULT 1 / 0`` covers the legacy callers that build
        TopicCard without specifying the new fields.
        """
        query = text("""
            INSERT INTO topic_cards (
                id, title, summary, scope_in_json, scope_out_json, type,
                anchors_json, sources_json, updated_at, tags_json,
                related_topics_json, status, metadata_json,
                last_summarized_at, summary_version, new_items_since_last_summary
            )
            VALUES (
                :id, :title, :summary, :scope_in_json, :scope_out_json, :type,
                :anchors_json, :sources_json, :updated_at, :tags_json,
                :related_topics_json, :status, :metadata_json,
                :last_summarized_at, :summary_version, :new_items_since_last_summary
            )
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                scope_in_json = excluded.scope_in_json,
                scope_out_json = excluded.scope_out_json,
                type = excluded.type,
                anchors_json = excluded.anchors_json,
                sources_json = excluded.sources_json,
                updated_at = excluded.updated_at,
                tags_json = excluded.tags_json,
                related_topics_json = excluded.related_topics_json,
                status = excluded.status,
                metadata_json = excluded.metadata_json
        """)

        await self.session.execute(
            query,
            {
                "id": card.id,
                "title": card.title,
                "summary": card.summary,
                "scope_in_json": stable_json_dumps(card.scope_in),
                "scope_out_json": stable_json_dumps(card.scope_out),
                "type": card.type.value,
                "anchors_json": stable_json_dumps([a.model_dump() for a in card.anchors]),
                "sources_json": stable_json_dumps(card.sources),
                "updated_at": card.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tags_json": stable_json_dumps(card.tags) if card.tags else None,
                "related_topics_json": stable_json_dumps(card.related_topics)
                if card.related_topics
                else None,
                "status": card.status,
                "metadata_json": stable_json_dumps(card.metadata) if card.metadata else None,
                # F5-C: pass-through model values; DB defaults cover NULL/0 cases.
                "last_summarized_at": card.last_summarized_at,
                "summary_version": card.summary_version,
                "new_items_since_last_summary": card.new_items_since_last_summary,
            },
        )

        await self.session.commit()

    async def get_by_id(self, topic_id: str) -> TopicCard | None:
        """Получить topic card по id."""
        query = text(f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards WHERE id = :topic_id")

        result = await self.session.execute(query, {"topic_id": topic_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_model(row)

    async def list_by_channel(self, channel_id: str) -> list[TopicCard]:
        """Получить все topic cards канала."""
        query = text(
            f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards "
            "WHERE sources_json LIKE :channel_pattern "
            "ORDER BY updated_at DESC"
        )

        channel_pattern = f'%"{channel_id}"%'

        result = await self.session.execute(query, {"channel_pattern": channel_pattern})
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def list_all(self) -> list[TopicCard]:
        """Получить все topic cards."""
        query = text(f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards ORDER BY updated_at DESC")

        result = await self.session.execute(query)
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def list_by_channels(self, channel_ids: list[str]) -> list[TopicCard]:
        """List topic cards visible to a user with these channels (F4)."""
        if not channel_ids:
            return []
        conditions = " OR ".join(f"sources_json LIKE :p{i}" for i in range(len(channel_ids)))
        params = {f"p{i}": f'%"{cid}"%' for i, cid in enumerate(channel_ids)}
        query = text(
            f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards "
            f"WHERE {conditions} ORDER BY updated_at DESC"
        )
        result = await self.session.execute(query, params)
        return [self._row_to_model(r) for r in result.fetchall()]

    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all topic cards whose sources include channel_id."""
        channel_pattern = f'%"{channel_id}"%'
        query = text("""
            DELETE FROM topic_cards
            WHERE sources_json LIKE :channel_pattern
        """)
        result = await self.session.execute(query, {"channel_pattern": channel_pattern})
        await self.session.commit()
        return result.rowcount

    # ------------------------------------------------------------------
    # F5-C Evolving Topic Summaries
    # ------------------------------------------------------------------

    async def increment_resummary_counter(self, topic_id: str, by: int = 1) -> None:
        """Atomically bump ``new_items_since_last_summary`` by ``by``.

        We deliberately do NOT raise on missing topic_id — the caller in
        ``_update_bundles_for_assignments`` is already guarded by
        ``topic_bundle_repo.add_items`` (which raises ValueError for a
        missing bundle), so a no-op UPDATE here is safe and silent.
        """
        if by <= 0:
            return
        query = text("""
            UPDATE topic_cards
            SET new_items_since_last_summary = new_items_since_last_summary + :by
            WHERE id = :topic_id
        """)
        await self.session.execute(query, {"topic_id": topic_id, "by": by})
        await self.session.commit()

    async def list_resummarize_candidates(
        self, channel_id: str | None = None, *, threshold: int
    ) -> list[TopicCard]:
        """Return cards whose counter crossed ``threshold``.

        Index ``idx_topic_cards_resummarize_candidates`` (partial,
        ``WHERE new_items_since_last_summary > 0``) keeps the scan tight
        even on a large topic_cards table.

        ``channel_id`` filter is implemented via ``LIKE :pattern`` on
        ``sources_json`` to mirror ``list_by_channel`` semantics — a
        topic with multiple sources is returned for every channel it
        belongs to (callers must dedupe if they enumerate channels).
        """
        params: dict[str, Any] = {"threshold": threshold}
        sql = (
            f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards "
            "WHERE new_items_since_last_summary >= :threshold"
        )
        if channel_id is not None:
            sql += " AND sources_json LIKE :channel_pattern"
            params["channel_pattern"] = f'%"{channel_id}"%'
        sql += " ORDER BY new_items_since_last_summary DESC, updated_at DESC"
        result = await self.session.execute(text(sql), params)
        return [self._row_to_model(r) for r in result.fetchall()]

    async def commit_resummary(
        self,
        topic_id: str,
        *,
        summary: str,
        scope_in: list[str],
        scope_out: list[str],
        prev_summary_version: int,
        summarized_at: datetime,
        metadata_extras: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically commit a fresh summary with optimistic version-check.

        Returns ``True`` on success, ``False`` if another worker already
        bumped ``summary_version`` past ``prev_summary_version`` (race
        loss — caller treats as a no-op and skips the version snapshot).

        Note on metadata_json:
        we COALESCE the new ``metadata_extras`` *into* the existing
        metadata_json (existing row wins on JSON-merge concerns; here we
        only choose between ``existing`` and ``new`` at the column level
        — whichever is non-NULL).  Service-layer is responsible for
        passing the merged dict it wants to persist.
        """
        query = text("""
            UPDATE topic_cards SET
              summary = :summary,
              scope_in_json = :scope_in_json,
              scope_out_json = :scope_out_json,
              summary_version = summary_version + 1,
              last_summarized_at = :summarized_at,
              new_items_since_last_summary = 0,
              updated_at = :updated_at,
              metadata_json = COALESCE(:metadata_json, metadata_json)
            WHERE id = :topic_id
              AND summary_version = :prev_v
        """)
        result = await self.session.execute(
            query,
            {
                "topic_id": topic_id,
                "summary": summary,
                "scope_in_json": stable_json_dumps(scope_in),
                "scope_out_json": stable_json_dumps(scope_out),
                "summarized_at": summarized_at,
                "updated_at": summarized_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "metadata_json": stable_json_dumps(metadata_extras) if metadata_extras else None,
                "prev_v": prev_summary_version,
            },
        )
        await self.session.commit()
        return result.rowcount > 0

    def _row_to_model(self, row) -> TopicCard:
        """Преобразовать row в TopicCard (включая F5-C поля)."""
        scope_in = stable_json_loads(row.scope_in_json)
        scope_out = stable_json_loads(row.scope_out_json)

        anchors_data = stable_json_loads(row.anchors_json)
        anchors = [Anchor(**a) for a in anchors_data]

        sources = stable_json_loads(row.sources_json)

        tags = stable_json_loads(row.tags_json) if row.tags_json else None
        related_topics = (
            stable_json_loads(row.related_topics_json) if row.related_topics_json else None
        )
        metadata = stable_json_loads(row.metadata_json) if row.metadata_json else None

        return TopicCard(
            id=row.id,
            title=row.title,
            summary=row.summary,
            scope_in=scope_in,
            scope_out=scope_out,
            type=TopicType(row.type),
            anchors=anchors,
            sources=sources,
            updated_at=parse_iso_datetime(row.updated_at),
            tags=tags,
            related_topics=related_topics,
            status=row.status,
            metadata=metadata,
            # F5-C
            last_summarized_at=row.last_summarized_at,
            summary_version=row.summary_version,
            new_items_since_last_summary=row.new_items_since_last_summary,
        )
