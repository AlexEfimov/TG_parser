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
    ) -> None:
        query = text("""
            INSERT INTO document_embeddings (source_ref, embedding, model, created_at, metadata_json)
            VALUES (:source_ref, :embedding, :model, :created_at, :metadata_json)
            ON CONFLICT(source_ref) DO UPDATE SET
                embedding = excluded.embedding,
                model = excluded.model,
                created_at = excluded.created_at,
                metadata_json = excluded.metadata_json
        """)
        await self.session.execute(
            query,
            {
                "source_ref": source_ref,
                "embedding": str(embedding),
                "model": model,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "metadata_json": stable_json_dumps(metadata) if metadata else None,
            },
        )
        await self.session.commit()

    async def save_batch(
        self,
        items: list[tuple[str, list[float], str, dict | None]],
    ) -> int:
        """Batch upsert embeddings. Each item: (source_ref, embedding, model, metadata).

        Returns count of saved items.
        """
        if not items:
            return 0
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = text("""
            INSERT INTO document_embeddings (source_ref, embedding, model, created_at, metadata_json)
            VALUES (:source_ref, :embedding, :model, :created_at, :metadata_json)
            ON CONFLICT(source_ref) DO UPDATE SET
                embedding = excluded.embedding,
                model = excluded.model,
                created_at = excluded.created_at,
                metadata_json = excluded.metadata_json
        """)
        for source_ref, embedding, model, metadata in items:
            await self.session.execute(
                query,
                {
                    "source_ref": source_ref,
                    "embedding": str(embedding),
                    "model": model,
                    "created_at": now,
                    "metadata_json": stable_json_dumps(metadata) if metadata else None,
                },
            )
        await self.session.commit()
        return len(items)

    async def get_by_source_ref(self, source_ref: str) -> DocumentEmbedding | None:
        query = text("""
            SELECT source_ref, embedding::text, model, created_at, metadata_json
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
    ) -> list[SimilarityResult]:
        query = text("""
            SELECT source_ref,
                   1 - (embedding <=> CAST(:query_embedding AS vector)) AS score
            FROM document_embeddings
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
            LIMIT :limit
        """)
        result = await self.session.execute(
            query,
            {"query_embedding": str(query_embedding), "limit": limit},
        )
        rows = result.fetchall()
        return [
            SimilarityResult(source_ref=r.source_ref, score=float(r.score))
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
            LEFT JOIN document_embeddings de ON pd.source_ref = de.source_ref
            WHERE pd.channel_id = :channel_id
              AND de.source_ref IS NULL
            ORDER BY pd.source_ref
        """)
        result = await self.session.execute(query, {"channel_id": channel_id})
        return [row.source_ref for row in result.fetchall()]

    @staticmethod
    def _row_to_model(row) -> DocumentEmbedding:
        embedding_str = row[1]  # embedding::text
        embedding = _parse_pgvector_text(embedding_str)
        meta = stable_json_loads(row.metadata_json) if row.metadata_json else {}
        return DocumentEmbedding(
            source_ref=row.source_ref,
            embedding=embedding,
            model=row.model,
            created_at=datetime.strptime(row.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            ),
            metadata=meta,
        )


def _parse_pgvector_text(s: str) -> list[float]:
    """Parse pgvector text representation '[0.1,0.2,...]' into list[float]."""
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [float(x) for x in s.split(",") if x.strip()]
