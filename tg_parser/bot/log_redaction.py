"""Bot INFO-log redaction for secret-bearing tool args (BUG-087).

Deny-list per tool — not a global strip by key name, and not an allow-list.
Non-secret args stay visible so BUG-002 / BUG-004 forensics remain useful
(``remove_channel args={'channel_id':…,'confirm':true}``).

Bot-local helper: do **not** import ``tg_parser.api.auth`` (hexagonal
boundary / ADR-0004). Redaction style mirrors ``_redacted_key_prefix`` there
(prefix / length token), but this is redaction for logs, not cryptographic
irreversibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Per-tool deny-list of secret-bearing arg names. Today the only secret arg
# in bot TOOL_DECLARATIONS is ``add_user_auth.identifier``. Neighbour admin
# tools do not declare an ``identifier`` parameter — keep the map per-tool
# so a future ``*.identifier`` / ``*.token`` is not redacted by name alone.
_SECRET_ARGS_BY_TOOL: dict[str, frozenset[str]] = {
    "add_user_auth": frozenset({"identifier"}),
}

_MIN_SECRET_PREFIX_LEN = 8


def _redacted_secret_token(value: Any) -> str:
    """Forensic stand-in for a secret value (prefix and/or length)."""
    text = value if isinstance(value, str) else str(value)
    if len(text) < _MIN_SECRET_PREFIX_LEN:
        return "****"
    return text[:4] + "****"


def redact_tool_args(tool_name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow copy safe for INFO logs.

    Never drop a secret key silently — replace its value with a redacted
    forensic token. Non-secret keys pass through unchanged. Unknown tools /
    empty deny-sets return args as-is (forensic default).

    Does **not** mutate ``args``; callers must pass the original mapping to
    ``execute_tool`` so ``hash_credential`` still sees the raw secret.
    """
    secret_keys = _SECRET_ARGS_BY_TOOL.get(tool_name)
    if not secret_keys:
        return dict(args)

    redacted: dict[str, Any] = {}
    for key, value in args.items():
        if key in secret_keys:
            redacted[key] = _redacted_secret_token(value)
        else:
            redacted[key] = value
    return redacted
