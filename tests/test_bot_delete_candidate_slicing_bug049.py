"""BUG-049 regression — delete-by-name candidate slicing drops the bare token.

Symptom (live, post BUG-048 smoke): a digest subscription «Ежечасный дайджест
Genotek» exists; «удали подписку на genotek» replies a plain «… не найдена»
instead of offering the fuzzy/substring suggestion «Возможно, вы имели в виду
«Ежечасный дайджест Genotek»?».

Root cause: ``_delete_name_candidates`` strips the delete verb and ONE connector
noun («подписку»), yielding «подписку на genotek» / «на genotek», but never
strips the leading preposition «на» nor emits the bare trailing token «genotek»,
so the substring match against «… Genotek» is never tested.

This case is RED on ``9ab998c`` (plain not_found, FSM inert) and GREEN after the
fix arms a ``delete_suggest`` clarify — exactly as «удали подписку genotek» does
today. Helpers/fixtures are reused from ``test_bot_delete_routing_bug047``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_bot_delete_routing_bug047 import (  # type: ignore[import-not-found]  # noqa: E402
    DIGEST_NAME,
    SUB_ID,
    _admin,
    _digest,
    _empty_repos,
    _enter_all,
    _exit_all,
    _make_message,
    _make_state,
    _routing_patches,
    _sent_text,
)

from tg_parser.bot.handlers import _delete_name_candidates, handle_text  # noqa: E402
from tg_parser.bot.states import ClarifyFlow  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Candidate slicing unit — the bare token must be emitted
# ---------------------------------------------------------------------------


class TestCandidateSlicingUnit:
    def test_na_preposition_yields_bare_token(self) -> None:
        """«удали подписку на genotek» must produce a bare «genotek» candidate so
        the substring/fuzzy suggest tier can match «… Genotek»."""
        cands = _delete_name_candidates("удали подписку на genotek")
        assert "genotek" in cands, cands
        # The bare token is a LAST-RESORT fallback (after the existing shapes).
        assert cands[-1] == "genotek"
        # Pre-existing shapes are preserved (no behavior change for them).
        assert "подписку на genotek" in cands
        assert "на genotek" in cands

    def test_bare_token_path_unchanged(self) -> None:
        """«удали подписку genotek» (works today) keeps its «genotek» candidate."""
        cands = _delete_name_candidates("удали подписку genotek")
        assert "genotek" in cands

    def test_multiword_name_not_over_stripped(self) -> None:
        """A multi-word name without a leading preposition must NOT be reduced to
        its trailing token (no over-stripping)."""
        cands = _delete_name_candidates("удали подписку Дайджест Genotek утро")
        assert "Дайджест Genotek утро" in cands
        # We never emit a bare trailing word for a prepositionless multi-word name.
        assert "утро" not in cands


# ---------------------------------------------------------------------------
# 2. End-to-end pre-router — «удали подписку на genotek» arms delete_suggest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNaPrepositionArmsSuggest:
    async def test_na_genotek_arms_delete_suggest(self):
        """«удали подписку на genotek» (digest «Ежечасный дайджест Genotek»
        exists) must ARM a ``delete_suggest`` clarify — NOT a plain not_found."""
        digest_repo, ir, mr, svc, unregister = _empty_repos()
        digest_repo.store[SUB_ID] = _digest(SUB_ID, DIGEST_NAME)

        state = _make_state()
        msg = _make_message("удали подписку на genotek")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        patches = _routing_patches(digest_repo, ir, mr, svc, unregister)
        _enter_all(patches)
        try:
            await handle_text(msg, agent=agent, state=state, current_user=_admin())
        finally:
            _exit_all(patches)

        agent.process_message.assert_not_called()
        # A clarify FSM is ARMED (not a stateless not_found message).
        assert await state.get_state() == ClarifyFlow.awaiting_channel_clarification.state
        data = await state.get_data()
        clarify = data["clarify_action"]
        assert clarify["kind"] == "delete_suggest"
        assert clarify["suggestion"]["id"] == SUB_ID
        # The user-facing suggestion text is surfaced (fuzzy-suggest tier).
        sent = _sent_text(msg)
        assert "Возможно, вы имели в виду" in sent
        assert "Ответьте «да»" in sent
        assert DIGEST_NAME in sent
        # Nothing deleted.
        assert SUB_ID in digest_repo.store
