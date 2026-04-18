"""Export-related enums shared across layers.

These live in the ``domain`` package so that services, CLI, API, MCP and bot
layers can all depend on a single source of truth without introducing a
circular import (``tg_parser.api.schemas`` pulls ``tg_parser.api.__init__``,
which wires up FastAPI routes that in turn depend on services).
"""

from __future__ import annotations

from enum import StrEnum


class ExportFormat(StrEnum):
    """Supported export formats."""

    NDJSON = "ndjson"
    JSON = "json"


class ExportLevel(StrEnum):
    """Export level — controls what gets exported (F2: Parse-Only Export).

    - ``RAW``: raw Telegram messages (parse-only, no LLM). Requires channel_id.
    - ``PROCESSED``: ``KnowledgeBaseEntry[]`` only (post-LLM; skip topics).
    - ``FULL``: PROCESSED + ``topics.json`` + ``topic_<id>.json`` (legacy default).
    """

    RAW = "raw"
    PROCESSED = "processed"
    FULL = "full"
