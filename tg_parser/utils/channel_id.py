"""Channel ID normalization — single source of truth.

The same canonical form must be produced everywhere a Telegram
channel identifier reaches storage / business logic, regardless of
whether it came from a Telegram-bot Gemini-agent message, an MCP
tool call, the CLI, or an internal scheduler tick. Concretely we
strip:

1. Surrounding whitespace (so ``"  ch "`` and ``"ch"`` collapse).
2. A single matching pair of surrounding quotes (``'…'`` /
   ``"…"``). 2026-04-29 production observation
   (``Удали канал 'test_channel'``) hit storage as the literal
   quoted string and produced an "unknown channel" UX dead-end.
   Mismatched quotes (``'…"``) are intentionally left as-is so
   they surface as "weird input" upstream rather than silently
   becoming valid.
3. The leading ``@`` (Telegram username convention). The DB
   stores channels without ``@`` (see ``add_channel`` flow) — read
   tools that didn't normalise produced spurious ``total=0``
   results, see BUG-003.

The helper is idempotent so chained / repeated normalization is a
no-op:

    >>> normalize_channel_id(normalize_channel_id("@ch")) == normalize_channel_id("@ch")
    True

It returns ``None`` for ``None`` input and for any input that
collapses to an empty string after stripping. Callers can then
treat ``None`` as "no channel filter" without ambiguous empty
strings leaking through.

Refs: ``docs/notes/BUG_LOG.md`` BUG-003, Session F (2026-04-29).

BUG-034 (Wave 1 step 4 post-watch hotfix). Write surfaces
(``_exec_subscribe_digest``, ``_exec_subscribe_watchlist``,
``_exec_add_channel``) used to accept the LLM's raw channel-id
verbatim after only ``normalize_channel_id`` ran — that helper is
deliberately permissive and does not validate the Telegram
username spec. Test D (2026-05-24) caught a user typo
«pro fendocrinologist» (with a space) that the Gemini agent
silently re-emitted as ``"pro_fendocrinologist"`` (with an
underscore) — a structurally invalid Telegram username that does
NOT match the real source ``profendocrinologist``. The resulting
subscription was undeliverable. ``validate_channel_username``
below is the executor-side pre-validation gate that rejects
typo'd / structurally-invalid usernames with a typed
``InvalidChannelUsername`` error and a clarification message
suggesting the whitespace-stripped form. Numeric Telegram
chat / channel ids (``12345``, ``-1001234567890``) bypass the
username regex via the dedicated ``_is_numeric_chat_id`` branch.
"""

from __future__ import annotations

import re
from typing import Any

INVALID_CHANNEL_USERNAME_ERROR_CLASS = "InvalidChannelUsername"

# Telegram username spec: 5-32 chars, start with letter, then
# alphanumeric / underscore. Channels published via ``@username``
# all conform. Numeric chat ids are handled separately by
# ``_is_numeric_chat_id`` because they are NOT usernames.
_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")

# Telegram numeric ids: positive integers for user/bot, ``-100…``
# for supergroups / channels, ``-…`` (legacy basic groups). We
# accept any optionally-signed integer string here — the executor
# will let the API reject genuinely-bad numeric values, but we
# need to wave them past the username regex.
_NUMERIC_CHAT_ID_RE = re.compile(r"^-?\d+$")


def normalize_channel_id(value: str | None) -> str | None:
    """Return the canonical DB-form channel id, or ``None`` if empty.

    See module docstring for the full rationale. The order of
    operations is fixed: outer whitespace → matching quotes → inner
    whitespace (revealed by quote-strip) → leading ``@`` → trailing
    whitespace.

    The "inner whitespace" step is critical for inputs like
    ``"' @ch '"`` (LLM-generated quoted variant with padding around
    the @): without it ``.lstrip("@")`` would see a leading space —
    not ``@`` — and the prefix would survive, breaking idempotency
    and re-introducing BUG-003 in a quoted disguise.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] in ("'", '"') and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1].strip()
    stripped = stripped.lstrip("@").strip()
    return stripped or None


def _is_numeric_chat_id(value: str) -> bool:
    """Return ``True`` iff ``value`` looks like a raw Telegram numeric id."""
    return bool(_NUMERIC_CHAT_ID_RE.fullmatch(value))


def _strip_outer_only(raw: str) -> str:
    """Strip outer quotes / whitespace / @ WITHOUT collapsing inner whitespace.

    Used by ``validate_channel_username`` to surface internal
    whitespace as a typo signal — ``normalize_channel_id`` would
    happily return ``"pro fendocrinologist"`` because Python's
    ``str.strip`` only removes outer whitespace, but we still need
    a clean view of the raw input for the user-facing clarification
    suggestion (``"".join(stripped.split())`` → the candidate
    typo-corrected username).
    """
    stripped = raw.strip()
    if len(stripped) >= 2 and stripped[0] in ("'", '"') and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1].strip()
    return stripped.lstrip("@").strip()


def validate_channel_username(
    value: Any,
) -> tuple[str | None, dict[str, Any] | None]:
    """Validate a Telegram channel username/id; return ``(value, error)``.

    Contract:

    * Exactly one of the two returned slots is non-``None``.
    * On success: ``value`` is the canonical, normalized channel id
      ready to persist (no leading ``@``, no surrounding quotes,
      whitespace stripped).
    * On failure: ``error`` is a dict shaped for direct return from
      bot executors — ``{"error": <human RU msg>,
      "error_class": "InvalidChannelUsername", "raw_input": …,
      "suggestion": <typo-corrected form, optional>}``.

    Rejection cases (BUG-034 scope):

    1. **Embedded whitespace** (BUG-034 reproduction) — checked
       BEFORE ``normalize_channel_id`` runs so the raw form is
       preserved for the clarification suggestion. Covers space,
       tab, newline, and multi-char runs. Bot users get
       «Канал «pro fendocrinologist» содержит пробелы — Telegram
       usernames не могут содержать пробелы. Возможно, вы имели
       в виду «profendocrinologist»?»
    2. **Empty / ``None`` input** — typed ``InvalidChannelUsername``
       error rather than the legacy free-form
       ``"channel_id is required"`` so callers can route on the
       error class.
    3. **Non-numeric, non-username** — fails the Telegram regex
       ``^[a-zA-Z][a-zA-Z0-9_]{4,31}$``. Catches: invalid chars
       (``@`` in the middle, hyphens, ``.``, ``/`` etc.), too-short
       (< 5 chars), too-long (> 32 chars), starts-with-digit, and
       non-ASCII (Cyrillic / Greek — Telegram usernames are ASCII).

    Numeric chat ids (``"12345"``, ``"-1001234567890"``) skip the
    username regex via the numeric-id fast path — see
    ``_is_numeric_chat_id``.

    Refs: ``docs/notes/BUG_LOG.md`` § BUG-034.
    """
    if value is None:
        return None, {
            "error": "channel_id is required",
            "error_class": INVALID_CHANNEL_USERNAME_ERROR_CLASS,
            "raw_input": None,
        }
    if not isinstance(value, str):
        value = str(value)

    raw_outer_stripped = _strip_outer_only(value)
    if not raw_outer_stripped:
        return None, {
            "error": "channel_id is required",
            "error_class": INVALID_CHANNEL_USERNAME_ERROR_CLASS,
            "raw_input": value,
        }

    if any(ch.isspace() for ch in raw_outer_stripped):
        # Strip the bare quotes / @ wrapper for a clean user-facing
        # echo but keep the inner whitespace visible in the message
        # so the operator sees exactly what they typed.
        suggestion = "".join(raw_outer_stripped.split())
        return None, {
            "error": (
                f"Канал «{raw_outer_stripped}» содержит пробелы — Telegram "
                f"usernames не могут содержать пробелы. Возможно, вы имели "
                f"в виду «{suggestion}»?"
            ),
            "error_class": INVALID_CHANNEL_USERNAME_ERROR_CLASS,
            "raw_input": raw_outer_stripped,
            "suggestion": suggestion,
        }

    normalized = normalize_channel_id(value)
    if not normalized:
        return None, {
            "error": "channel_id is required",
            "error_class": INVALID_CHANNEL_USERNAME_ERROR_CLASS,
            "raw_input": value,
        }

    if _is_numeric_chat_id(normalized):
        return normalized, None

    if not _USERNAME_RE.fullmatch(normalized):
        return None, {
            "error": (
                f"«{normalized}» не является валидным Telegram username — "
                f"требуется 5-32 ASCII-символа, начиная с буквы, далее "
                f"буквы / цифры / подчёркивания."
            ),
            "error_class": INVALID_CHANNEL_USERNAME_ERROR_CLASS,
            "raw_input": normalized,
        }

    return normalized, None
