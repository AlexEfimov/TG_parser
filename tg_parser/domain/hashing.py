"""Content-hash utilities for F5-A Phase 3 deduplication.

Pure functions, zero I/O dependencies. Keep this module free of settings
imports so it can be used from migrations / backfill scripts without pulling
in config.
"""

import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")
_URL_QUERY_RE = re.compile(r"(https?://[^\s?#]+)[?#][^\s]*")


def normalize_for_hash(text: str, *, strip_url_query: bool = True) -> str:
    """Deterministic normalization for content-hash.

    Rules:
    - If ``strip_url_query`` (default): strip ``?query#fragment`` from URLs.
    - Lowercase (unicode-aware via ``str.lower``).
    - Collapse consecutive whitespace (incl. \\t \\n) to a single space.
    - Trim leading/trailing whitespace.

    Order matters: URL strip first (preserves original case in path),
    then lowercase, then whitespace collapse.
    """
    if strip_url_query:
        text = _URL_QUERY_RE.sub(r"\1", text)
    text = text.lower()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def compute_content_hash(text_clean: str, *, strip_url_query: bool = True) -> str:
    """SHA-256 hex digest (64 lowercase chars) of normalized ``text_clean``."""
    normalized = normalize_for_hash(text_clean, strip_url_query=strip_url_query)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
