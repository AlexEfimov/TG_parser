"""Script-routed token normalization for F11 watchlist keyword matching.

Routes each lowercased token by Unicode script:
- Cyrillic → pymorphy3 normal_form
- Latin (a-z only, len >= 3) → simplemma English lemma
- Identity (digits, hyphens, mixed script, short Latin) → as-is

After script-routed lemmatization a small **curated alias→canonical** map
(:data:`_ALIAS_TO_CANONICAL`) collapses brand / spelling / cross-language drug
variants onto one canonical token (backlog item B, seed-first). Because both the
interest keywords and the document tokens flow through this single function, an
interest keyworded ``semaglutide`` now matches a doc mentioning ``Ozempic`` or
``семаглутида``. This is a **recall normalization only** — it changes which
tokens land in the set the keyword scorer compares; it does NOT touch the
hybrid-score formula, weights, thresholds, or aggregation (ADR-0010/0011).
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

# ---------------------------------------------------------------------------
# Curated alias → canonical seed map (backlog item B, seed-first)
# ---------------------------------------------------------------------------
#
# Intentionally TIGHT and hand-curated — NOT an RxNorm / ATC / DrugBank
# ontology ingestion (that is the deferred "post-Wave-2 contract" follow-up;
# see HANDOFF_WATCHLIST_BACKFILL_CALIBRATION_2026-06-15.md §3 row 6 / §6 item B).
# It seeds only the handoff's motivating GLP-1 cases (§2.5: GLP-1 keyword
# underrating of RU drug / brand / spelling variants).
#
# Keys are the **post-lemmatization** lowercased form (the lookup in
# ``normalize_token`` runs AFTER script-routed lemmatization), e.g. the RU
# genitive ``семаглутида`` is lemmatized by pymorphy3 to ``семаглутид`` first,
# so only the lemma needs an entry. A canonical token maps to itself so that
# both an alias and the canonical name collapse to the same value.
#
# Canonical-token convention: a stable lowercased ASCII molecule/class name.
# Distinct molecules keep distinct canonicals (semaglutide vs tirzepatide) and
# the GLP-1 *class* abbreviation is its own canonical — we deliberately do NOT
# merge a specific molecule into the class (precision: a doc mentioning only the
# class should not satisfy a molecule-specific interest, and vice versa).
_ALIAS_TO_CANONICAL: dict[str, str] = {
    # semaglutide (molecule) + brand names + RU spellings → "semaglutide"
    "semaglutide": "semaglutide",
    "ozempic": "semaglutide",
    "wegovy": "semaglutide",
    "rybelsus": "semaglutide",
    "семаглутид": "semaglutide",
    "оземпик": "semaglutide",
    "вегови": "semaglutide",
    "ребелсас": "semaglutide",
    # tirzepatide (molecule) + brand names + RU spellings → "tirzepatide"
    "tirzepatide": "tirzepatide",
    "mounjaro": "tirzepatide",
    "zepbound": "tirzepatide",
    "тирзепатид": "tirzepatide",
    "мунджаро": "tirzepatide",
    # GLP-1 receptor-agonist drug class — cross-language abbreviations → "glp-1".
    # These are identity-routed tokens (hyphen), so the lemma == the raw token;
    # the alias lookup still fires on the raw token (see ``normalize_token``).
    "glp-1": "glp-1",
    "глп-1": "glp-1",
    "гпп-1": "glp-1",
    "агпп-1": "glp-1",
}

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


def _lemmatize(token: str) -> str:
    """Script-routed lemma/stem/identity (no alias canonicalization)."""
    if _is_identity_token(token):
        return token
    if _CYRILLIC_RE.search(token):
        return _lemmatize_russian(token)
    if _PURE_LATIN_RE.fullmatch(token) and len(token) >= 3:
        return _lemmatize_english(token)
    return token


@functools.lru_cache(maxsize=8192)
def normalize_token(token: str) -> str:
    """Script-routed lemma/stem/identity + curated alias canonicalization.

    Alias canonicalization (backlog item B) runs AFTER lemmatization so the
    seed map (:data:`_ALIAS_TO_CANONICAL`) only needs base/lemma forms. The raw
    token is used as a fallback key so identity-routed aliases (brand names with
    hyphens such as ``глп-1``) still resolve. Tokens absent from the map are
    returned as their plain lemma — unchanged from the fix-E behaviour.
    """
    if not token or len(token) < MIN_TOKEN_LENGTH:
        return token
    lemma = _lemmatize(token)
    return _ALIAS_TO_CANONICAL.get(lemma) or _ALIAS_TO_CANONICAL.get(token) or lemma


def normalize_tokens(tokens: Iterable[str]) -> set[str]:
    """Batch helper for doc token sets."""
    return {normalize_token(t) for t in tokens}
