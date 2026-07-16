"""Safe prompt template rendering (F9 Phase 2).

Untrusted channel / user payloads often contain literal ``{`` / ``}``. Feeding
them through ``str.format`` raises ``KeyError`` / ``ValueError`` and aborts the
path. This helper substitutes only known ``{name}`` placeholders and leaves
every other brace sequence (including braces inside substituted values) intact.

Unlike ``str.format``, doubled braces ``{{`` / ``}}`` are **not** unescaped —
templates that rely on format-style escaping must keep using ``.format`` or be
rewritten to use literal single braces.
"""

from __future__ import annotations

import re

# Named placeholders only: {text}, {context}, {question}, …
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_prompt(template: str, **values: object) -> str:
    """Substitute known placeholders; leave unknown braces and payload braces intact.

    Parameters
    ----------
    template:
        Prompt template containing ``{name}`` placeholders.
    **values:
        Mapping of placeholder name → value (converted with ``str()``).

    Returns
    -------
    str
        Rendered prompt. Values containing ``{`` / ``}`` never raise and are
        inserted verbatim. Placeholders whose names are not in ``values`` are
        left unchanged (including surrounding braces).
    """
    if not values:
        return template

    stringified = {key: str(value) for key, value in values.items()}

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in stringified:
            return stringified[name]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, template)
