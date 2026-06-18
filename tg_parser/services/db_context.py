"""
Database context managers for service layer.

Each context manager obtains the Database singleton (creating engines once),
opens short-lived sessions, and closes them on exit.
The singleton itself is NOT closed here — that happens in the application
lifespan handler (``api/main.py``, ``mcp_server.py``).
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.digest_subscription_repo import (
    SADigestSubscriptionRepo,
)
from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
from tg_parser.storage.sqlalchemy.idempotency_key_repo import SAIdempotencyKeyRepo
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.job_repo import SAJobRepo
from tg_parser.storage.sqlalchemy.processed_document_repo import (
    SAProcessedDocumentRepo,
)
from tg_parser.storage.sqlalchemy.processing_failure_repo import (
    SAProcessingFailureRepo,
)
from tg_parser.storage.sqlalchemy.raw_message_repo import SARawMessageRepo
from tg_parser.storage.sqlalchemy.task_history_repo import SATaskHistoryRepo
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo
from tg_parser.storage.sqlalchemy.topic_card_version_repo import SATopicCardVersionRepo
from tg_parser.storage.sqlalchemy.topic_link_repo import SATopicLinkRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.watch_interest_repo import SAWatchInterestRepo
from tg_parser.storage.sqlalchemy.watch_match_repo import SAWatchMatchRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _get_db() -> Database:
    """Return the initialized Database singleton."""
    db = Database.get_instance()
    await db.init()
    return db


async def _apply_read_statement_timeout(
    session: "AsyncSession", engine: "AsyncEngine | None", timeout_ms: int
) -> None:
    """Bound a read session server-side with a transaction-scoped statement_timeout.

    BUG-008 H2: applies ``SET LOCAL statement_timeout`` (via ``set_config(..., true)``)
    so a slow or lock-blocked stats query can't run unbounded on the server. It is
    **read-scoped on purpose** — applied only to the stats/aggregation sessions, NOT
    as a global GUC — because the ingestion/topicization pipeline legitimately runs
    long queries that a blanket timeout would kill.

    ``is_local=True`` ties the setting to the session's current transaction, so it can
    never leak onto a pooled connection that is later reused by a writer. The
    ``set_config`` call autobegins that transaction; the subsequent read-only repo
    queries share it (they never COMMIT), so the bound holds for every read.

    No-ops when disabled (``timeout_ms <= 0``) or on a non-PostgreSQL dialect
    (defensive — the stats path is Postgres in production/tests). Failures are
    swallowed: the guard is best-effort and must never break stats collection.
    """
    if timeout_ms <= 0:
        return
    if engine is None or engine.dialect.name != "postgresql":
        return
    try:
        await session.execute(
            text("SELECT set_config('statement_timeout', :v, true)"),
            {"v": str(int(timeout_ms))},
        )
    except SQLAlchemyError:  # pragma: no cover - defensive, never break stats
        pass


@asynccontextmanager
async def processing_repos() -> (
    "AsyncIterator[tuple[SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database]]"
):
    """Context manager for processing repos (topicization, export)."""
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SAProcessedDocumentRepo(session),
            SATopicCardRepo(session),
            SATopicBundleRepo(session),
            db,
        )
    finally:
        await session.close()


@asynccontextmanager
async def ingestion_repos() -> (
    "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, Database]]"
):
    """Context manager for ingestion repos (state + raw messages)."""
    db = await _get_db()
    state_session = db.ingestion_state_session()
    raw_session = db.raw_storage_session()
    try:
        yield (
            SAIngestionStateRepo(state_session),
            SARawMessageRepo(raw_session),
            db,
        )
    finally:
        await state_session.close()
        await raw_session.close()


@asynccontextmanager
async def raw_and_processed_repos() -> (
    "AsyncIterator[tuple[SARawMessageRepo, SAProcessedDocumentRepo, SAProcessingFailureRepo, Database]]"
):
    """Context manager for processing pipeline (raw -> processed)."""
    db = await _get_db()
    raw_session = db.raw_storage_session()
    proc_session = db.processing_storage_session()
    try:
        yield (
            SARawMessageRepo(raw_session),
            SAProcessedDocumentRepo(proc_session),
            SAProcessingFailureRepo(proc_session),
            db,
        )
    finally:
        await raw_session.close()
        await proc_session.close()


@asynccontextmanager
async def ingestion_state_repo() -> "AsyncIterator[tuple[SAIngestionStateRepo, Database]]":
    """Context manager for single IngestionStateRepo (add-source, status)."""
    db = await _get_db()
    session = db.ingestion_state_session()
    try:
        yield SAIngestionStateRepo(session), db
    finally:
        await session.close()


@asynccontextmanager
async def user_repo() -> "AsyncIterator[tuple[SAUserRepo, Database]]":
    """Context manager for UserRepo (F4 multi-tenancy)."""
    db = await _get_db()
    session = db.ingestion_state_session()
    try:
        yield SAUserRepo(session), db
    finally:
        await session.close()


@asynccontextmanager
async def digest_subscription_repo() -> "AsyncIterator[tuple[SADigestSubscriptionRepo, Database]]":
    """Context manager for DigestSubscriptionRepo (F6 scheduled digests)."""
    db = await _get_db()
    session = db.ingestion_state_session()
    try:
        yield SADigestSubscriptionRepo(session), db
    finally:
        await session.close()


@asynccontextmanager
async def workspace_repo() -> "AsyncIterator[tuple[SAWorkspaceRepo, Database]]":
    """Context manager for WorkspaceRepo (F4-B Core)."""
    db = await _get_db()
    session = db.ingestion_state_session()
    try:
        yield SAWorkspaceRepo(session), db
    finally:
        await session.close()


@asynccontextmanager
async def idempotency_key_repo() -> "AsyncIterator[tuple[SAIdempotencyKeyRepo, Database]]":
    """Context manager for IdempotencyKeyRepo (Wave 1 step 3 commit 4/4).

    Lives on the ingestion DB session — same partition as the
    ``users``/``watch_interests``/``digest_subscriptions`` rows whose
    POST endpoints opt into the Idempotency-Key middleware (ADR 0009
    Option C).
    """
    db = await _get_db()
    session = db.ingestion_state_session()
    try:
        yield SAIdempotencyKeyRepo(session), db
    finally:
        await session.close()


@asynccontextmanager
async def watchlist_repos() -> (
    "AsyncIterator[tuple[SAWatchInterestRepo, SAWatchMatchRepo, SAProcessedDocumentRepo, SAEmbeddingRepo, Database]]"
):
    """Context manager for the F11 watchlist service.

    Opens two sessions (ingestion + processing) so the service can read
    user-owned ``watch_interests`` / ``watch_matches`` from the ingestion
    branch and pull document text + embeddings from the processing branch
    in a single tick without crossing branch boundaries.
    """
    db = await _get_db()
    state_session = db.ingestion_state_session()
    proc_session = db.processing_storage_session()
    try:
        yield (
            SAWatchInterestRepo(state_session),
            SAWatchMatchRepo(state_session),
            SAProcessedDocumentRepo(proc_session),
            SAEmbeddingRepo(proc_session),
            db,
        )
    finally:
        await state_session.close()
        await proc_session.close()


@asynccontextmanager
async def ingestion_and_processing_repos() -> (
    "AsyncIterator[tuple[SAIngestionStateRepo, SAProcessedDocumentRepo, Database]]"
):
    """Context manager for scheduler (ingestion state + processed docs)."""
    db = await _get_db()
    state_session = db.ingestion_state_session()
    proc_session = db.processing_storage_session()
    try:
        yield (
            SAIngestionStateRepo(state_session),
            SAProcessedDocumentRepo(proc_session),
            db,
        )
    finally:
        await state_session.close()
        await proc_session.close()


@asynccontextmanager
async def embedding_repos() -> (
    "AsyncIterator[tuple[SAEmbeddingRepo, SAProcessedDocumentRepo, Database]]"
):
    """Context manager for embedding / retrieval (embedding + processed docs, shared processing engine)."""
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SAEmbeddingRepo(session),
            SAProcessedDocumentRepo(session),
            db,
        )
    finally:
        await session.close()


@asynccontextmanager
async def near_duplicate_repos() -> (
    "AsyncIterator[tuple[SAEmbeddingRepo, SAIngestionStateRepo, Database]]"
):
    """Context manager for F5-B Phase 0 near-duplicate observation (ADR-0016).

    Yields an embedding repo (processing engine, for the pgvector ``<=>``
    sliding-window similarity search) plus an ingestion-state repo (to list
    sibling active sources for the cross-channel axis).
    """
    db = await _get_db()
    proc_session = db.processing_storage_session()
    state_session = db.ingestion_state_session()
    try:
        yield (
            SAEmbeddingRepo(proc_session),
            SAIngestionStateRepo(state_session),
            db,
        )
    finally:
        await proc_session.close()
        await state_session.close()


@asynccontextmanager
async def topic_embedding_repos() -> (
    "AsyncIterator[tuple[SAEmbeddingRepo, SATopicCardRepo, Database]]"
):
    """Context manager for topic embedding (embedding repo + topic cards, shared processing engine)."""
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SAEmbeddingRepo(session),
            SATopicCardRepo(session),
            db,
        )
    finally:
        await session.close()


@asynccontextmanager
async def export_repos() -> (
    "AsyncIterator[tuple[SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, SAIngestionStateRepo, SARawMessageRepo, Database]]"
):
    """Context manager for export (processing + ingestion state + raw in single Database).

    Includes ``SARawMessageRepo`` so that ``run_export(level='raw')``
    (F2 Parse-Only Export) can read raw messages without opening a
    separate session stack.
    """
    db = await _get_db()
    proc_session = db.processing_storage_session()
    state_session = db.ingestion_state_session()
    raw_session = db.raw_storage_session()
    try:
        yield (
            SAProcessedDocumentRepo(proc_session),
            SATopicCardRepo(proc_session),
            SATopicBundleRepo(proc_session),
            SAIngestionStateRepo(state_session),
            SARawMessageRepo(raw_session),
            db,
        )
    finally:
        await proc_session.close()
        await state_session.close()
        await raw_session.close()


@asynccontextmanager
async def resummarization_repos() -> (
    "AsyncIterator[tuple[SATopicCardRepo, SATopicBundleRepo, SATopicCardVersionRepo, Database]]"
):
    """Context manager for F5-C ResummarizationService.

    All three repos share a single processing session so that
    ``commit_resummary`` (UPDATE topic_cards) and the version-snapshot
    INSERT participate in the same SQLAlchemy session — and so the
    Postgres advisory lock + commit happen on the same connection.
    """
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SATopicCardRepo(session),
            SATopicBundleRepo(session),
            SATopicCardVersionRepo(session),
            db,
        )
    finally:
        await session.close()


@asynccontextmanager
async def topic_linking_repos() -> (
    "AsyncIterator[tuple[SATopicCardRepo, SATopicBundleRepo, SATopicLinkRepo, SAEmbeddingRepo, Database]]"
):
    """Context manager for topic linking (topic cards, bundles, links, embeddings)."""
    db = await _get_db()
    session = db.processing_storage_session()
    try:
        yield (
            SATopicCardRepo(session),
            SATopicBundleRepo(session),
            SATopicLinkRepo(session),
            SAEmbeddingRepo(session),
            db,
        )
    finally:
        await session.close()


@asynccontextmanager
async def stats_repos() -> (
    "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, SAEmbeddingRepo, SATopicLinkRepo, Database]]"
):
    """Context manager for channel statistics (all three DB sessions, read-only).

    BUG-021: also yields a :class:`SATopicLinkRepo` (same processing session)
    so cross-channel analytics can fold topic-link stats into the result.
    """
    db = await _get_db()
    state_session = db.ingestion_state_session()
    raw_session = db.raw_storage_session()
    proc_session = db.processing_storage_session()
    # BUG-008 H2: read-scoped statement_timeout on the stats sessions only.
    timeout_ms = db.settings.stats_statement_timeout_ms
    try:
        await _apply_read_statement_timeout(state_session, db.ingestion_state_engine, timeout_ms)
        await _apply_read_statement_timeout(raw_session, db.raw_storage_engine, timeout_ms)
        await _apply_read_statement_timeout(proc_session, db.processing_storage_engine, timeout_ms)
        yield (
            SAIngestionStateRepo(state_session),
            SARawMessageRepo(raw_session),
            SAProcessedDocumentRepo(proc_session),
            SATopicCardRepo(proc_session),
            SATopicBundleRepo(proc_session),
            SAEmbeddingRepo(proc_session),
            SATopicLinkRepo(proc_session),
            db,
        )
    finally:
        await state_session.close()
        await raw_session.close()
        await proc_session.close()


@asynccontextmanager
async def removal_repos() -> (
    "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, SAProcessedDocumentRepo, SAProcessingFailureRepo, SAEmbeddingRepo, SATopicCardRepo, SATopicBundleRepo, SAJobRepo, SATaskHistoryRepo, Database]]"
):
    """Context manager for channel removal (all three DB sessions)."""
    db = await _get_db()
    state_session = db.ingestion_state_session()
    raw_session = db.raw_storage_session()
    proc_session = db.processing_storage_session()
    try:
        yield (
            SAIngestionStateRepo(state_session),
            SARawMessageRepo(raw_session),
            SAProcessedDocumentRepo(proc_session),
            SAProcessingFailureRepo(proc_session),
            SAEmbeddingRepo(proc_session),
            SATopicCardRepo(proc_session),
            SATopicBundleRepo(proc_session),
            SAJobRepo(db.processing_session_factory),
            SATaskHistoryRepo(db.processing_session_factory),
            db,
        )
    finally:
        await state_session.close()
        await raw_session.close()
        await proc_session.close()
