"""
Embedding repository (P5 RAG).

Stores and retrieves document embeddings using pgvector for similarity search.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.json_utils import stable_json_dumps, stable_json_loads
from tg_parser.storage.ports import DocumentEmbedding, EmbeddingRepo, SimilarityResult


class SAEmbeddingRepo(EmbeddingRepo):
    """pgvector-backed embedding repository (shares processing DB)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(
        self,
        source_ref: str,
        embedding: list[float],
        model: str,
        metadata: dict | None = None,
        entry_type: str = "message",
        topic_id: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> None:
        query = text("""
            INSERT INTO document_embeddings
                (source_ref, embedding, model, created_at, metadata_json, entry_type, topic_id, channel_ids)
            VALUES (:source_ref, :embedding, :model, :created_at, :metadata_json, :entry_type, :topic_id, :channel_ids)
            ON CONFLICT(source_ref) DO UPDATE SET
                embedding = excluded.embedding,
                model = excluded.model,
                created_at = excluded.created_at,
                metadata_json = excluded.metadata_json,
                entry_type = excluded.entry_type,
                topic_id = excluded.topic_id,
                channel_ids = excluded.channel_ids
        """)
        await self.session.execute(
            query,
            {
                "source_ref": source_ref,
                "embedding": str(embedding),
                "model": model,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "metadata_json": stable_json_dumps(metadata) if metadata else None,
                "entry_type": entry_type,
                "topic_id": topic_id,
                "channel_ids": channel_ids or [],
            },
        )
        await self.session.commit()

    async def save_batch(
        self,
        items: list[tuple[str, list[float], str, dict | None]],
        entry_type: str = "message",
        topic_id: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> int:
        """Batch upsert embeddings. Each item: (source_ref, embedding, model, metadata).

        Uses a multi-row VALUES clause for fewer round-trips.
        Returns count of saved items.
        """
        if not items:
            return 0

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        _channel_ids = channel_ids or []
        CHUNK = 50
        total_saved = 0

        for chunk_start in range(0, len(items), CHUNK):
            chunk = items[chunk_start : chunk_start + CHUNK]
            values_parts = []
            params: dict = {}

            for idx, (source_ref, embedding, model, metadata) in enumerate(chunk):
                placeholder = (
                    f"(:sr{idx}, :emb{idx}, :mdl{idx}, :ca{idx}, :mj{idx}, :et{idx}, :ti{idx}, :ci{idx})"
                )
                values_parts.append(placeholder)
                params[f"sr{idx}"] = source_ref
                params[f"emb{idx}"] = str(embedding)
                params[f"mdl{idx}"] = model
                params[f"ca{idx}"] = now
                params[f"mj{idx}"] = stable_json_dumps(metadata) if metadata else None
                params[f"et{idx}"] = entry_type
                params[f"ti{idx}"] = topic_id
                params[f"ci{idx}"] = _channel_ids

            values_sql = ", ".join(values_parts)
            query = text(f"""
                INSERT INTO document_embeddings
                    (source_ref, embedding, model, created_at, metadata_json, entry_type, topic_id, channel_ids)
                VALUES {values_sql}
                ON CONFLICT(source_ref) DO UPDATE SET
                    embedding = excluded.embedding,
                    model = excluded.model,
                    created_at = excluded.created_at,
                    metadata_json = excluded.metadata_json,
                    entry_type = excluded.entry_type,
                    topic_id = excluded.topic_id,
                    channel_ids = excluded.channel_ids
            """)
            await self.session.execute(query, params)
            total_saved += len(chunk)

        await self.session.commit()
        return total_saved

    async def get_by_source_ref(self, source_ref: str) -> DocumentEmbedding | None:
        query = text("""
            SELECT source_ref, embedding::text, model, created_at, metadata_json,
                   entry_type, topic_id, channel_ids
            FROM document_embeddings
            WHERE source_ref = :source_ref
        """)
        result = await self.session.execute(query, {"source_ref": source_ref})
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        threshold: float = 0.0,
        entry_types: list[str] | None = None,
        channel_ids: list[str] | None = None,
    ) -> list[SimilarityResult]:
        where_clauses = ["embedding IS NOT NULL"]
        params: dict = {"query_embedding": str(query_embedding), "limit": limit}

        if entry_types:
            placeholders = ", ".join(f":et{i}" for i in range(len(entry_types)))
            where_clauses.append(f"entry_type IN ({placeholders})")
            for i, et in enumerate(entry_types):
                params[f"et{i}"] = et

        if channel_ids is not None:
            where_clauses.append("channel_ids && CAST(:allowed_channels AS text[])")
            params["allowed_channels"] = channel_ids

        where_sql = " AND ".join(where_clauses)
        query = text(f"""
            SELECT source_ref,
                   1 - (embedding <=> CAST(:query_embedding AS vector)) AS score,
                   entry_type, topic_id
            FROM document_embeddings
            WHERE {where_sql}
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
            LIMIT :limit
        """)
        result = await self.session.execute(query, params)
        rows = result.fetchall()
        return [
            SimilarityResult(
                source_ref=r.source_ref,
                score=float(r.score),
                entry_type=r.entry_type or "message",
                topic_id=r.topic_id,
            )
            for r in rows
            if float(r.score) >= threshold
        ]

    async def count(self) -> int:
        result = await self.session.execute(
            text("SELECT count(*) FROM document_embeddings")
        )
        return result.scalar() or 0

    async def list_missing(self, channel_id: str) -> list[str]:
        query = text("""
            SELECT pd.source_ref
            FROM processed_documents pd
            LEFT JOIN document_embeddings de
                ON pd.source_ref = de.source_ref AND de.entry_type = 'message'
            WHERE pd.channel_id = :channel_id
              AND de.source_ref IS NULL
            ORDER BY pd.source_ref
        """)
        result = await self.session.execute(query, {"channel_id": channel_id})
        return [row.source_ref for row in result.fetchall()]

    async def delete_by_channel(self, channel_id: str) -> int:
        r1 = await self.session.execute(
            text("""
                DELETE FROM document_embeddings
                WHERE entry_type = 'message'
                  AND source_ref IN (
                    SELECT source_ref FROM processed_documents WHERE channel_id = :channel_id
                  )
            """),
            {"channel_id": channel_id},
        )
        r2 = await self.session.execute(
            text("""
                DELETE FROM document_embeddings
                WHERE entry_type = 'topic'
                  AND topic_id IN (
                    SELECT id FROM topic_cards WHERE sources_json LIKE :pattern
                  )
            """),
            {"channel_id": channel_id, "pattern": f"%{channel_id}%"},
        )
        await self.session.commit()
        return (r1.rowcount or 0) + (r2.rowcount or 0)

    @staticmethod
    def _row_to_model(row) -> DocumentEmbedding:
        embedding_str = row[1]  # embedding::text
        embedding = _parse_pgvector_text(embedding_str)
        meta = stable_json_loads(row.metadata_json) if row.metadata_json else {}
        raw_channel_ids = getattr(row, "channel_ids", None)
        try:
            parsed_channel_ids = list(raw_channel_ids) if raw_channel_ids else []
        except TypeError:
            parsed_channel_ids = []
        return DocumentEmbedding(
            source_ref=row.source_ref,
            embedding=embedding,
            model=row.model,
            created_at=datetime.strptime(row.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            ),
            metadata=meta,
            entry_type=getattr(row, "entry_type", "message") or "message",
            topic_id=getattr(row, "topic_id", None),
            channel_ids=parsed_channel_ids,
        )


def _parse_pgvector_text(s: str) -> list[float]:
    """Parse pgvector text representation '[0.1,0.2,...]' into list[float]."""
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [float(x) for x in s.split(",") if x.strip()]
