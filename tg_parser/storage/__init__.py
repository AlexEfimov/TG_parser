"""
Модуль хранения данных TG_parser.

Порты (интерфейсы) репозиториев и их реализации (SQLite в MVP).
"""

from .ports import (
    IngestionStateRepo,
    ProcessedDocumentRepo,
    ProcessingFailureRepo,
    RawMessageRepo,
    Source,
    TopicBundleRepo,
    TopicCardRepo,
)

__all__ = [
    # Ports
    "IngestionStateRepo",
    "RawMessageRepo",
    "ProcessedDocumentRepo",
    "ProcessingFailureRepo",
    "TopicCardRepo",
    "TopicBundleRepo",
    # Models
    "Source",
]






