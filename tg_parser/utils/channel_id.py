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
"""

from __future__ import annotations


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
