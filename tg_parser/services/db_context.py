"""
Database context managers for service layer.

Eliminates repetitive Database.from_settings / init / session / close
boilerplate across all services. Each context manager yields a tuple of
repos (and the Database instance when callers need extra access).
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from tg_parser.config import settings
from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.processed_document_repo import (
    SAProcessedDocumentRepo,
)
from tg_parser.storage.sqlalchemy.processing_failure_repo import (
    SAProcessingFailureRepo,
)
from tg_parser.storage.sqlalchemy.raw_message_repo import SARawMessageRepo
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def processing_repos() -> "AsyncIterator[tuple[SAProcessedDocumentRepo, SATopicCardRepo, SATopicBundleRepo, Database]]":
    """Context manager for processing repos (topicization, export)."""
    db = Database.from_settings(settings)
    await db.init()
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
        await db.close()


@asynccontextmanager
async def ingestion_repos() -> "AsyncIterator[tuple[SAIngestionStateRepo, SARawMessageRepo, Database]]":
    """Context manager for ingestion repos (state + raw messages)."""
    db = Database.from_settings(settings)
    await db.init()
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
        await db.close()


@asynccontextmanager
async def raw_and_processed_repos() -> "AsyncIterator[tuple[SARawMessageRepo, SAProcessedDocumentRepo, SAProcessingFailureRepo, Database]]":
    """Context manager for processing pipeline (raw -> processed)."""
    db = Database.from_settings(settings)
    await db.init()
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
        await db.close()


@asynccontextmanager
async def ingestion_state_repo() -> "AsyncIterator[tuple[SAIngestionStateRepo, Database]]":
    """Context manager for single IngestionStateRepo (add-source, status)."""
    db = Database.from_settings(settings)
    await db.init()
    session = db.ingestion_state_session()
    try:
        yield SAIngestionStateRepo(session), db
    finally:
        await session.close()
        await db.close()


@asynccontextmanager
async def ingestion_and_processing_repos() -> "AsyncIterator[tuple[SAIngestionStateRepo, SAProcessedDocumentRepo, Database]]":
    """Context manager for scheduler (ingestion state + processed docs)."""
    db = Database.from_settings(settings)
    await db.init()
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
        await db.close()


@asynccontextmanager
async def embedding_repos() -> "AsyncIterator[tuple[SAEmbeddingRepo, SAProcessedDocumentRepo, Database]]":
    """Context manager for embedding / retrieval (embedding + processed docs, shared processing engine)."""
    db = Database.from_settings(settings)
    try:
        await db.init()
        session = db.processing_storage_session()
        try:
            yield (
                SAEmbeddingRepo(session),
                SAProcessedDocumentRepo(session),
                db,
            )
        finally:
            await session.close()
    finally:
        await db.close()
