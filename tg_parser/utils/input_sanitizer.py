"""Input length caps and prompt-injection suspect detection (F9 Phase 2).

Defense-in-depth only — not 100% injection immunity. Truncate at edges;
classify suspicious patterns for structured logs + Prometheus (do not block).

Caps (normative):
- ``MAX_USER_INPUT_LENGTH`` (4096) — bot free-text / ask question
- ``MAX_SEARCH_QUERY_LENGTH`` (1024) — search / embed query

Idempotence: applying the same truncate twice with the same ``max_length`` is a
no-op when the string is already ≤ the cap. ``answer()`` may sanitize at 4096
then call ``search()`` which sanitizes at 1024 — that further truncate is
intentional (search/embed budget), not a violation of per-helper idempotence.

Channel names / IDs are out of scope — use ``tg_parser.utils.channel_id``.
"""

from __future__ import annotations

import re
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

MAX_USER_INPUT_LENGTH = 4096
MAX_SEARCH_QUERY_LENGTH = 1024

Surface = Literal["bot", "rag", "processing"]

# Short, configurable list — prefer detection (F4) over destructive stripping (F1).
_INJECTION_SUSPECT_RAW: tuple[str, ...] = (
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"ignore\s+all\s+instructions?",
    r"system\s+prompt",
    r"you\s+are\s+now",
    r"\bDAN\b",
    r"developer\s+mode",
)

INJECTION_SUSPECT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _INJECTION_SUSPECT_RAW
)


def truncate_text(text: str, max_length: int) -> tuple[str, bool]:
    """Return ``(text, truncated)``. Idempotent when already ≤ ``max_length``."""
    if len(text) <= max_length:
        return text, False
    return text[:max_length], True


def detect_injection_suspect(text: str) -> tuple[bool, str | None]:
    """Return ``(suspect, matched_snippet)`` for known injection-like phrases."""
    for pat in INJECTION_SUSPECT_PATTERNS:
        match = pat.search(text)
        if match:
            return True, match.group(0)
    return False, None


def _record_suspect(*, surface: Surface, snippet: str | None, text: str) -> None:
    truncated_snippet = (snippet or text)[:80]
    logger.warning(
        "prompt_injection_suspect",
        prompt_injection_suspect=True,
        surface=surface,
        matched=snippet,
        snippet=truncated_snippet,
        text_length=len(text),
    )
    try:
        from tg_parser.api.metrics import record_prompt_injection_suspect

        record_prompt_injection_suspect(surface=surface)
    except Exception:  # noqa: BLE001 — metrics must never break the request path
        logger.debug("prompt_injection_metric_failed", surface=surface, exc_info=True)


def sanitize_user_input(
    text: str,
    *,
    max_length: int = MAX_USER_INPUT_LENGTH,
    surface: Surface = "bot",
    emit_metrics: bool = True,
) -> str:
    """Truncate to ``max_length`` and classify injection-like input (log/metric only).

    Does not strip or reject on pattern match — blocking is a later hardening pass.
    Safe to call at both ``answer()`` and ``search()`` (see module docstring).
    """
    if not text:
        return text

    suspect, matched = detect_injection_suspect(text)
    if suspect and emit_metrics:
        _record_suspect(surface=surface, snippet=matched, text=text)

    out, truncated = truncate_text(text, max_length)
    if truncated:
        logger.info(
            "input_truncated",
            surface=surface,
            original_length=len(text),
            max_length=max_length,
        )
    return out
