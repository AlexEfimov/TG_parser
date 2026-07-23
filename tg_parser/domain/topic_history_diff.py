"""F5-C #15 item #2 — pure domain diff helper for evolving topic summaries.

Shared by the MCP tool ``get_topic_history_diff`` (structured JSON) and the
CLI command ``tg-parser topic diff`` (human-rendered). No I/O, no repo
access — the caller loads both sides and passes them in.

Both sides are normalised to a common lightweight value-object
(:class:`TopicSummarySnapshot`) so the helper does not care whether a side
came from an archival :class:`~tg_parser.domain.models.TopicCardVersion`
(``topic_card_versions``) or the live
:class:`~tg_parser.domain.models.TopicCard` (``topic_cards``, the ``current``
side, ``summary_version = N``, which is *not* stored in the versions table).

Diff semantics (owner-decision D1 — BOTH):

* ``summary`` → stdlib :mod:`difflib` line-level unified diff (ADR-0017:
  ``difflib`` is stdlib, no new dependency).
* ``scope_in`` / ``scope_out`` → set-diff ``{added, removed, unchanged_count}``.

Ordering is normalised by the caller: ``left`` is the older side, ``right``
the newer side; ``current`` (live card) is always the right side.
"""

from __future__ import annotations

import difflib
from typing import Any

from pydantic import BaseModel, Field

from tg_parser.domain.models import TopicCard, TopicCardVersion

# Sentinel used as ``version_no`` for the live-card ("current") side, which
# has no row in ``topic_card_versions``.
CURRENT_LABEL = "current"


class TopicSummarySnapshot(BaseModel):
    """Normalised, source-agnostic view of one side of a diff.

    Built from either a :class:`TopicCardVersion` (archival side) or a live
    :class:`TopicCard` (``current`` side). ``provenance`` carries the
    presentation/label metadata that is echoed back verbatim in the diff
    result (never fed into the text/set diff itself).
    """

    summary: str = Field(description="Summary text of this side")
    scope_in: list[str] = Field(default_factory=list, description="scope_in of this side")
    scope_out: list[str] = Field(default_factory=list, description="scope_out of this side")
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Label metadata (label, version_no|'current', created_at, llm_*)",
    )


def snapshot_from_version(version: TopicCardVersion) -> TopicSummarySnapshot:
    """Normalise an archival ``topic_card_versions`` row into a snapshot."""
    return TopicSummarySnapshot(
        summary=version.summary,
        scope_in=list(version.scope_in),
        scope_out=list(version.scope_out),
        provenance={
            "label": f"v{version.version_no}",
            "version_no": version.version_no,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "supporting_items_count_at_time": version.supporting_items_count_at_time,
            "llm_provider": version.llm_provider,
            "llm_model": version.llm_model,
            "prompt_version": version.prompt_version,
        },
    )


def snapshot_from_card(card: TopicCard) -> TopicSummarySnapshot:
    """Normalise the live ``topic_cards`` row (``current`` side) into a snapshot.

    Reads exactly the columns ``get_topic_details`` reads
    (``summary`` / ``scope_in`` / ``scope_out`` / ``summary_version``); the
    live card has no LLM provenance columns, so those are ``None``.
    """
    return TopicSummarySnapshot(
        summary=card.summary,
        scope_in=list(card.scope_in),
        scope_out=list(card.scope_out),
        provenance={
            "label": CURRENT_LABEL,
            "version_no": CURRENT_LABEL,
            "summary_version": card.summary_version,
            "created_at": (
                card.last_summarized_at.isoformat() if card.last_summarized_at else None
            ),
            "llm_provider": None,
            "llm_model": None,
            "prompt_version": None,
        },
    )


def _scope_diff(left: list[str], right: list[str]) -> dict[str, Any]:
    """Set-diff two scope lists, preserving input order for determinism.

    ``added`` = present in ``right`` but not ``left`` (in ``right`` order);
    ``removed`` = present in ``left`` but not ``right`` (in ``left`` order);
    ``unchanged_count`` = size of the intersection.
    """
    left_set = set(left)
    right_set = set(right)
    added = [x for x in right if x not in left_set]
    removed = [x for x in left if x not in right_set]
    unchanged_count = sum(1 for x in left if x in right_set)
    return {"added": added, "removed": removed, "unchanged_count": unchanged_count}


def diff_topic_summaries(left: TopicSummarySnapshot, right: TopicSummarySnapshot) -> dict[str, Any]:
    """Compare two normalised topic-summary snapshots.

    ``left`` is the older side, ``right`` the newer side (the caller enforces
    this ordering; ``current`` is always ``right``).

    Returns a structured, JSON-serialisable dict:

    * ``left`` / ``right`` — the provenance metadata of each side;
    * ``summary_changed`` — whether the summary text differs;
    * ``summary_diff`` — stdlib :func:`difflib.unified_diff` lines (empty
      when identical);
    * ``scope_in`` / ``scope_out`` — ``{added, removed, unchanged_count}``.
    """
    left_label = str(left.provenance.get("label", "left"))
    right_label = str(right.provenance.get("label", "right"))

    summary_diff = list(
        difflib.unified_diff(
            left.summary.splitlines(),
            right.summary.splitlines(),
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
        )
    )

    return {
        "left": dict(left.provenance),
        "right": dict(right.provenance),
        "summary_changed": left.summary != right.summary,
        "summary_diff": summary_diff,
        "scope_in": _scope_diff(left.scope_in, right.scope_in),
        "scope_out": _scope_diff(left.scope_out, right.scope_out),
    }
