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

    async def upsert(self, card: TopicCard, *, commit: bool = True) -> None:
        """
        TR-43: upsert/replace по id.
        TR-IF-4: id детерминирован (topic: + anchors[0].anchor_ref).

        F5-C: ``last_summarized_at`` / ``summary_version`` /
        ``new_items_since_last_summary`` are written from the model so
        round-trip via ``get_by_id`` preserves them; on first INSERT the
        DB-side ``DEFAULT 1 / 0`` covers the legacy callers that build
        TopicCard without specifying the new fields.

        BUG-076: ``commit=False`` stages the upsert WITHOUT committing so the
        caller can co-commit several card upserts + a bundle write + the
        resumable-run checkpoint advance in ONE atomic transaction on the shared
        session (a partial chunk must never persist — LLM-derived ids shift on
        re-run and would duplicate cards). Defaults to the legacy commit-per-call
        behaviour.
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

        if commit:
            await self.session.commit()

    async def delete_by_id(self, topic_id: str, *, commit: bool = True) -> int:
        """Delete a single topic card by id (BUG-076 cross-chunk merge).

        Used by the idempotent cross-chunk consolidation pass to remove a
        merged-away (loser) card after its bundle items / anchors have been
        folded into the surviving card. ``commit=False`` lets the merge stage
        several deletes in one transaction. Returns the deleted row count.
        """
        result = await self.session.execute(
            text("DELETE FROM topic_cards WHERE id = :topic_id"),
            {"topic_id": topic_id},
        )
        if commit:
            await self.session.commit()
        return result.rowcount

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

    async def count_by_channel_grouped(self) -> dict[str, int]:
        """Return ``{channel_id: topic_card_count}`` for all channels in one query.

        BUG-008 H1: batched replacement for the per-channel ``list_by_channel``
        fan-out used only to take ``len(...)`` in ``get_all_channel_stats``. The
        old path ran a leading-wildcard ``sources_json LIKE '%"cid"%'`` (full
        sequential scan of the un-indexed ``Text`` column) **per channel**.

        Here ``sources_json`` (a JSON array of channel-id strings) is parsed once
        via ``jsonb_array_elements_text`` and grouped, turning O(channels × table)
        into a single O(table) pass. ``COUNT(DISTINCT id)`` guards against a card
        that (defensively) lists the same channel twice — matching the old
        row-level ``LIKE`` semantics where each card counts once per channel.
        """
        query = text("""
            SELECT ch.channel AS channel_id, COUNT(DISTINCT tc.id) AS cnt
            FROM topic_cards tc
            CROSS JOIN LATERAL jsonb_array_elements_text(tc.sources_json::jsonb) AS ch(channel)
            GROUP BY ch.channel
        """)
        result = await self.session.execute(query)
        return {row.channel_id: row.cnt for row in result.fetchall()}

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
        self, channel_id: str | None = None, *, threshold: int, max_age_days: int = 0
    ) -> list[TopicCard]:
        """Return cards eligible for re-summarization (counter OR time-based).

        Index ``idx_topic_cards_resummarize_candidates`` (partial,
        ``WHERE new_items_since_last_summary > 0``) keeps the scan tight
        even on a large topic_cards table. The top-level
        ``new_items_since_last_summary > 0`` predicate is preserved so the
        time-based OR branch (F5-C P2 / #15 item #4) stays under that index.

        ``max_age_days = 0`` disables the time-based branch → the WHERE clause
        reduces to ``new_items_since_last_summary >= threshold`` (counter-only
        MVP, bit-for-bit). When ``> 0``, a topic whose ``last_summarized_at`` is
        older than ``max_age_days`` days AND has >= 1 new item also matches,
        even if the counter has not crossed ``threshold``.

        ``channel_id`` filter is implemented via ``LIKE :pattern`` on
        ``sources_json`` to mirror ``list_by_channel`` semantics — a
        topic with multiple sources is returned for every channel it
        belongs to (callers must dedupe if they enumerate channels).
        """
        params: dict[str, Any] = {"threshold": threshold, "max_age_days": max_age_days}
        sql = (
            f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards "
            "WHERE new_items_since_last_summary > 0 "
            "AND ("
            "new_items_since_last_summary >= :threshold "
            "OR (:max_age_days > 0 AND last_summarized_at IS NOT NULL "
            "AND last_summarized_at < NOW() - make_interval(days => :max_age_days))"
            ")"
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

    async def set_resummarize_backoff(
        self,
        topic_id: str,
        *,
        metadata: dict[str, Any],
        updated_at: datetime,
    ) -> None:
        """Metadata-only UPDATE to quarantine a refusing topic (BUG-083).

        Unlike ``commit_resummary`` this touches neither ``summary`` nor
        ``summary_version`` nor ``last_summarized_at`` — only ``metadata_json``
        (fully replaced with the caller-merged dict) and ``updated_at``. Commits
        so the cooldown persists and releases the F5-C advisory xact-lock.
        """
        query = text("""
            UPDATE topic_cards SET
              metadata_json = :metadata_json,
              updated_at = :updated_at
            WHERE id = :topic_id
        """)
        await self.session.execute(
            query,
            {
                "topic_id": topic_id,
                "metadata_json": stable_json_dumps(metadata) if metadata else None,
                "updated_at": updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        await self.session.commit()

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
