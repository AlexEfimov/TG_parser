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

DF-4 (R15, 2026-09-26). A link to a public channel resolves to its
username, so ``https://t.me/x`` and ``@x`` are one channel on every
surface. The grammar is closed — only these forms become ``x``:

* scheme ``https://``, ``http://`` (any case) or none;
* host exactly ``t.me`` or ``telegram.me``, optionally ``www.``, any case;
* path ``/x``, ``/x/``, ``/s/x``, ``/s/x/``, ``/x/<post>``, ``/s/x/<post>``
  with a decimal post id (``/s/x/`` and ``/s/x/<post>`` — the web preview
  of a post — were added to the R15 list by owner decision);
* a trailing ``?…`` / ``#…`` is dropped;
* no whitespace inside the link (outer whitespace is stripped first) and
  no ``@`` in front of it (``@https://t.me/x`` is rejected);
* the extracted ``x`` loses one quote pair and a leading ``@`` (as a
  bare id does), then must match the username regex and not be a
  reserved t.me path (``joinchat``, ``share``, ``addlist`` …).

Input is *link-like* when, after the outer strip above, it contains
any of ``/ : ? # \\ .`` — none of them can occur in a username or a
numeric id. Link-like input outside the grammar (private invites,
``tg://``, ``telegram.dog``, ports, userinfo, foreign hosts, extra
path segments, percent-encoding …) raises ``InvalidChannelUsername``.
It is never mapped to ``None``: ``None`` means "no filter", and a
rejected link that silently became "no filter" would widen a read
to every accessible channel. Non-link input keeps the pre-DF-4
semantics bit-for-bit, so every stored id normalizes to itself.

The exception subclasses ``ValueError`` on purpose: bot executors and
MCP tools already surface ``ValueError`` as a typed error, and every
internal caller (advisory lock, dispatch identity, Telethon) fails
closed instead of falling back to the raw string.

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

_LINK_CHARS = frozenset("/:?#\\.")

_TME_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me(?P<path>/[^?#]*)?(?:[?#].*)?",
    re.IGNORECASE | re.DOTALL,
)
_TME_PATH_RE = re.compile(r"/(?:s/)?(?P<name>[^/]+)(?:/(?:[0-9]+)?)?")

# First path segments that t.me serves itself; they match the username
# regex but never name a channel.
_TME_RESERVED_PATHS = frozenset(
    {
        "addemoji",
        "addlist",
        "addstickers",
        "addtheme",
        "boost",
        "confirmphone",
        "contact",
        "giftcode",
        "invoice",
        "joinchat",
        "login",
        "proxy",
        "setlanguage",
        "share",
        "socks",
    }
)


class InvalidChannelUsername(ValueError):
    """Link-like channel input outside the closed t.me grammar (DF-4)."""

    error_class = INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def __init__(self, raw_input: str) -> None:
        self.raw_input = raw_input
        super().__init__(
            f"«{raw_input}» — не ссылка на публичный Telegram-канал. "
            f"Укажите @username или ссылку вида https://t.me/username."
        )

    def to_error(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "error_class": self.error_class,
            "raw_input": self.raw_input,
        }


def _username_from_link(value: str) -> str:
    if any(ch.isspace() for ch in value):
        raise InvalidChannelUsername(value)
    link = _TME_LINK_RE.fullmatch(value)
    path = link.group("path") if link else None
    parsed = _TME_PATH_RE.fullmatch(path) if path else None
    name = _strip_outer_only(parsed.group("name")) if parsed else None
    if name is None or not _USERNAME_RE.fullmatch(name) or name.lower() in _TME_RESERVED_PATHS:
        raise InvalidChannelUsername(value)
    return name


def normalize_channel_id(value: str | None) -> str | None:
    """Return the canonical DB-form channel id, or ``None`` if empty.

    See module docstring for the full rationale. The order of
    operations is fixed: outer whitespace → matching quotes → inner
    whitespace (revealed by quote-strip) → leading ``@`` → trailing
    whitespace → link resolution.

    The "inner whitespace" step is critical for inputs like
    ``"' @ch '"`` (LLM-generated quoted variant with padding around
    the @): without it ``.lstrip("@")`` would see a leading space —
    not ``@`` — and the prefix would survive, breaking idempotency
    and re-introducing BUG-003 in a quoted disguise.

    Raises:
        InvalidChannelUsername: link-like input outside the DF-4 grammar.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] in ("'", '"') and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1].strip()
    unprefixed = stripped.lstrip("@").strip()
    if not unprefixed:
        return None
    if not _LINK_CHARS.isdisjoint(unprefixed):
        if unprefixed != stripped:
            raise InvalidChannelUsername(stripped)
        return _username_from_link(unprefixed)
    return unprefixed


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
    4. **Link outside the DF-4 grammar** — ``normalize_channel_id``
       raised ``InvalidChannelUsername``. A public-channel link inside
       the grammar (``https://t.me/x``) is not rejected: it validates
       as ``x``.

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

    try:
        normalized = normalize_channel_id(value)
    except InvalidChannelUsername as exc:
        return None, exc.to_error()
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
