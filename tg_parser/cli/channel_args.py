"""Channel-id arguments of CLI commands (DF-4).

Source channel ids pass through the same ``normalize_channel_id`` as the
bot, MCP and HTTP surfaces, so ``--channel https://t.me/x`` and
``--channel x`` name one channel. A link outside the t.me grammar is a
usage error (exit 2) — never a missing filter.
"""

from __future__ import annotations

import typer

from tg_parser.utils.channel_id import (
    InvalidChannelUsername,
    normalize_channel_id,
    validate_channel_username,
)


def channel_filter(value: str | None, param: str = "--channel") -> str | None:
    """Canonical id for a read / job option; ``None`` stays "no filter"."""
    if value is None:
        return None
    try:
        return normalize_channel_id(value) or value
    except InvalidChannelUsername as exc:
        raise typer.BadParameter(str(exc), param_hint=param) from exc


def source_channel_id(value: str | None, param: str = "--channel") -> str:
    """Validated canonical id for an option that writes a source reference."""
    validated, error = validate_channel_username(value)
    if error is not None:
        raise typer.BadParameter(error["error"], param_hint=param)
    assert validated is not None
    return validated


def source_channel_list(value: str | None, param: str = "--channels") -> list[str]:
    """Split a comma-separated source list; blank entries are dropped.

    A link's ``?…`` / ``#…`` tail may itself contain commas, so after an
    entry with such a tail the split is ambiguous
    (``https://t.me/x?a=1,2`` — is ``2`` a channel?). That is a usage
    error, never an extra channel; the tail is fine on the last entry.
    """
    if not value:
        return []
    chunks = value.split(",")
    result: list[str] = []
    for index, chunk in enumerate(chunks):
        try:
            if normalize_channel_id(chunk) is None:
                continue
        except InvalidChannelUsername:
            pass
        if ("?" in chunk or "#" in chunk) and any(c.strip() for c in chunks[index + 1 :]):
            raise typer.BadParameter(
                f"«{chunk.strip()}» — ссылка с ?… или #… может быть только последней: "
                f"запятая после неё неоднозначна. Уберите хвост ссылки.",
                param_hint=param,
            )
        result.append(source_channel_id(chunk, param))
    return result
