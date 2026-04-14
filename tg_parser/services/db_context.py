"""
Database context managers for service layer.

Each context manager obtains the Database singleton (creating engines once),
opens short-lived sessions, and closes them on exit.
The singleton itself is NOT closed here — that happens in the application
lifespan handler (``api/main.py``, ``mcp_server.py``).
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
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
from tg_parser.storage.sqlalchemy.topic_link_repo import SATopicLinkRepo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _get_db() -> Database:
    """Return the initialized Database singleton."""
    db = Database.get_instance()
    await db.init()
    return db


@asynccontextmanager
async def processing_repos() -> "AsyncIterator[tuple[SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database]]":
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
async def ingestion_repos() -> "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, Database]]":
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
async def raw_and_processed_repos() -> "AsyncIterator[tuple[SARawMessageRepo, SAProcessedDocumentRepo, SAProcessingFailureRepo, Database]]":
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
async def ingestion_and_processing_repos() -> "AsyncIterator[tuple[SAIngestionStateRepo, SAProcessedDocumentRepo, Database]]":
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
async def embedding_repos() -> "AsyncIterator[tuple[SAEmbeddingRepo, SAProcessedDocumentRepo, Database]]":
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
async def topic_embedding_repos() -> "AsyncIterator[tuple[SAEmbeddingRepo, SATopicCardRepo, Database]]":
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
async def export_repos() -> "AsyncIterator[tuple[SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, SAIngestionStateRepo, Database]]":
    """Context manager for export (processing + ingestion state in single Database)."""
    db = await _get_db()
    proc_session = db.processing_storage_session()
    state_session = db.ingestion_state_session()
    try:
        yield (
            SAProcessedDocumentRepo(proc_session),
            SATopicCardRepo(proc_session),
            SATopicBundleRepo(proc_session),
            SAIngestionStateRepo(state_session),
            db,
        )
    finally:
        await proc_session.close()
        await state_session.close()


@asynccontextmanager
async def topic_linking_repos() -> "AsyncIterator[tuple[SATopicCardRepo, SATopicBundleRepo, SATopicLinkRepo, SAEmbeddingRepo, Database]]":
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
async def stats_repos() -> "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, SAEmbeddingRepo, Database]]":
    """Context manager for channel statistics (all three DB sessions, read-only)."""
    db = await _get_db()
    state_session = db.ingestion_state_session()
    raw_session = db.raw_storage_session()
    proc_session = db.processing_storage_session()
    try:
        yield (
            SAIngestionStateRepo(state_session),
            SARawMessageRepo(raw_session),
            SAProcessedDocumentRepo(proc_session),
            SATopicCardRepo(proc_session),
            SATopicBundleRepo(proc_session),
            SAEmbeddingRepo(proc_session),
            db,
        )
    finally:
        await state_session.close()
        await raw_session.close()
        await proc_session.close()


@asynccontextmanager
async def removal_repos() -> "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, SAProcessedDocumentRepo, SAProcessingFailureRepo, SAEmbeddingRepo, SATopicCardRepo, SATopicBundleRepo, SAJobRepo, SATaskHistoryRepo, Database]]":
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
