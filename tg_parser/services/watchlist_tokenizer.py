"""Script-routed token normalization for F11 watchlist keyword matching.

Routes each lowercased token by Unicode script:
- Cyrillic → pymorphy3 normal_form
- Latin (a-z only, len >= 3) → simplemma English lemma
- Identity (digits, hyphens, mixed script, short Latin) → as-is
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable

# Mirrors watchlist_service.MIN_TOKEN_LENGTH — tokens shorter than this are
# not emitted by the regex extractor but may be passed directly in tests.
MIN_TOKEN_LENGTH: int = 2

_CYRILLIC_RE = re.compile(r"[а-яё]")
_LATIN_RE = re.compile(r"[a-z]")
_PURE_LATIN_RE = re.compile(r"^[a-z]+$")

_morph_analyzer: object | None = None


def _get_morph_analyzer():
    """Lazy singleton MorphAnalyzer — dicts are ~30 MB; load once per process."""
    global _morph_analyzer
    if _morph_analyzer is None:
        from pymorphy3 import MorphAnalyzer

        _morph_analyzer = MorphAnalyzer()
    return _morph_analyzer


def _is_identity_token(token: str) -> bool:
    if any(ch.isdigit() for ch in token):
        return True
    if "-" in token:
        return True
    if _CYRILLIC_RE.search(token) and _LATIN_RE.search(token):
        return True
    if _PURE_LATIN_RE.fullmatch(token) and len(token) < 3:
        return True
    return False


def _lemmatize_russian(token: str) -> str:
    try:
        morph = _get_morph_analyzer()
        parsed = morph.parse(token)
        if parsed:
            return parsed[0].normal_form
    except Exception:
        pass
    return token


def _lemmatize_english(token: str) -> str:
    try:
        import simplemma

        lemma = simplemma.lemmatize(token, lang="en")
        if lemma:
            return lemma
    except Exception:
        pass
    return token


@functools.lru_cache(maxsize=8192)
def normalize_token(token: str) -> str:
    """Script-routed lemma/stem/identity for F11 keyword matching."""
    if not token or len(token) < MIN_TOKEN_LENGTH:
        return token
    if _is_identity_token(token):
        return token
    if _CYRILLIC_RE.search(token):
        return _lemmatize_russian(token)
    if _PURE_LATIN_RE.fullmatch(token) and len(token) >= 3:
        return _lemmatize_english(token)
    return token


def normalize_tokens(tokens: Iterable[str]) -> set[str]:
    """Batch helper for doc token sets."""
    return {normalize_token(t) for t in tokens}
