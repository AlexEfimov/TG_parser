"""
Схемы DDL для SQLite хранилищ.

Реализует TR-17: разделение на 3 файла.
"""

from .ingestion_state import init_ingestion_state_schema
from .processing_storage import init_processing_storage_schema
from .raw_storage import init_raw_storage_schema

__all__ = [
    "init_ingestion_state_schema",
    "init_raw_storage_schema",
    "init_processing_storage_schema",
]
