"""Log-safe shape summary for the unknown confirm-token event (BUG-088).

``fsm_confirm_unknown_token`` used to log the whole normalized user reply, so
any free text typed on an armed ConfirmFlow turn — including a pasted
credential — reached the log pipeline verbatim. The field was not gratuitous:
it is the only diagnostic the event carries and it exists because of BUG-032
(an operator must be able to see WHY a token was rejected), so it cannot be
fixed by deletion.

This module replaces the value with facts ABOUT it: a closed-vocabulary
``verdict`` plus length / token-count / character-class flags. Both halves are
compile-time vocabularies, so no user byte can reach a record.

Deliberately NOT in ``log_redaction.py`` (BUG-087): that helper is a deny-list
keyed on tool-argument NAMES, which cannot reach free text — there is no
argument name to deny. Same file, adjacent lines, disjoint mechanism.

Bot-local and stdlib-only: no ``tg_parser.api.*`` import (hexagonal boundary /
ADR-0004), no new dependency for the edit distance.
"""

from __future__ import annotations

# Literal key set of the ``fsm_confirm_unknown_token`` INFO record. Pinned by
# tests so that adding a field is a deliberate act reviewed for privacy.
UNKNOWN_CONFIRM_LOG_KEYS: frozenset[str] = frozenset(
    {
        "chat_id",
        "tool",
        "verdict",
        "length",
        "token_count",
        "is_single_token",
        "has_digits",
        "has_punct",
    }
)

# Closed vocabulary. ``verdict`` is chosen from these five strings and never
# derived from the reply's content.
UNKNOWN_CONFIRM_VERDICTS: frozenset[str] = frozenset(
    {
        "non_text",
        "near_miss_affirmative",
        "near_miss_negative",
        "single_token_unlisted",
        "multi_token_free_text",
    }
)

_MAX_NEAR_MISS_DISTANCE = 1


def _confirmation_token_sets() -> tuple[frozenset[str], frozenset[str]]:
    """Return the LIVE whitelists from ``handlers``.

    Imported inside the function on purpose: ``handlers`` imports this module,
    so a top-level import would be a cycle. Resolving it through
    ``sys.modules`` on every call also means the near-miss verdict is always
    computed against the whitelists the classifier itself uses — a local copy
    of the token sets would drift the moment one of them gains an entry.
    """
    from tg_parser.bot.handlers import AFFIRMATIVE_TOKENS, NEGATIVE_TOKENS

    return AFFIRMATIVE_TOKENS, NEGATIVE_TOKENS


def normalize_confirm_reply(text: str | None) -> str:
    """Normalize exactly as ``classify_confirmation_token`` does.

    Same normalization or the verdict would describe a different string than
    the one the classifier rejected.
    """
    if text is None:
        return ""
    return " ".join(text.split()).casefold()


def _levenshtein_within(left: str, right: str, max_distance: int) -> bool:
    """Return True when the edit distance is ``<= max_distance``.

    Length-difference short-circuit first, so a long paste never runs the full
    matrix against every whitelist entry.
    """
    if abs(len(left) - len(right)) > max_distance:
        return False
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1] <= max_distance


def _strip_non_alnum(normalized: str) -> str:
    return "".join(ch for ch in normalized if ch.isalnum())


def _is_near_miss(normalized: str, tokens: frozenset[str]) -> bool:
    """Single-token near-miss test against one whitelist.

    Two ways in: a typo (``«дя»`` for ``«да»``) or decoration the classifier
    does not strip (it only removes trailing ``,.;:!?`` from the first token).
    Stripping is compared against the RAW tokens, so an all-punctuation reply
    cannot match the ``"+"`` / ``"👍"`` entries by both sides collapsing to the
    empty string.
    """
    stripped = _strip_non_alnum(normalized)
    if stripped and stripped in tokens:
        return True
    return any(_levenshtein_within(normalized, token, _MAX_NEAR_MISS_DISTANCE) for token in tokens)


def classify_unknown_confirm_verdict(normalized: str) -> str:
    """Return a member of :data:`UNKNOWN_CONFIRM_VERDICTS` for ``normalized``.

    Order is load-bearing:

    1. ``non_text`` — nothing to diagnose (empty, or emoji / punctuation only).
    2. ``multi_token_free_text`` — two or more tokens. Edit distance is not run
       on free text: expensive and the answer would be noise.
    3. single token — near-miss against the affirmative whitelist, then the
       negative one (affirmative wins a collision, which needs both a typo of
       one set landing within one edit of the other), else unlisted.

    ``single_token_unlisted`` with a large ``length`` and ``has_digits`` is the
    paste shape; a short one is probably a synonym worth adding to a whitelist.
    """
    if not normalized or not any(ch.isalnum() for ch in normalized):
        return "non_text"
    if len(normalized.split()) >= 2:
        return "multi_token_free_text"

    affirmative_tokens, negative_tokens = _confirmation_token_sets()
    if _is_near_miss(normalized, affirmative_tokens):
        return "near_miss_affirmative"
    if _is_near_miss(normalized, negative_tokens):
        return "near_miss_negative"
    return "single_token_unlisted"


def unknown_confirm_log_fields(
    text: str | None,
    *,
    chat_id: int,
    tool: str | None,
) -> dict[str, object]:
    """Build the kwargs for ``logger.info("fsm_confirm_unknown_token", …)``.

    The returned keys are exactly :data:`UNKNOWN_CONFIRM_LOG_KEYS`. No value
    derives from the reply's content: ``verdict`` is one of five compile-time
    strings and the rest are counts and booleans. ``tool`` closes a diagnostic
    gap — unlike its siblings, this event never said which pending action the
    user failed to answer.
    """
    normalized = normalize_confirm_reply(text)
    token_count = len(normalized.split())
    return {
        "chat_id": chat_id,
        "tool": tool,
        "verdict": classify_unknown_confirm_verdict(normalized),
        "length": len(normalized),
        "token_count": token_count,
        "is_single_token": token_count == 1,
        "has_digits": any(ch.isdigit() for ch in normalized),
        "has_punct": any(not (ch.isalnum() or ch.isspace()) for ch in normalized),
    }
