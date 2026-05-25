"""Regression tests for BUG-034 — bot channel-name parser typo handling.

In Test D (2026-05-24 ~21:11 UTC, observation captured during the
Wave 1 step 4 VPS watch — see ``docs/notes/BUG_LOG.md`` § BUG-034
for the empirical trail) the operator typed «Подпиши этот чат на
ежечасный дайджест канала **pro fendocrinologist**» (with an
embedded space — a typo for ``profendocrinologist``). The Gemini
agent emitted ``subscribe_digest(channel_ids=["pro_fendocrinologist"],
…)`` — the space was silently re-coerced to an underscore,
producing a structurally-invalid Telegram username that did NOT
match the real source ``profendocrinologist``. The resulting
subscription (``0a00768d-…``) was undeliverable.

Investigation (commit ``e50449b``, this PR) confirmed:

* **No** Python-side ``.replace(" ", "_")`` exists anywhere in
  ``tg_parser/bot/`` — the legacy ``normalize_channel_id`` helper
  is permissive but never substitutes underscores.
* The bug surface is the **executor-side write path**: prior to
  the fix, ``_exec_subscribe_digest`` / ``_exec_subscribe_watchlist``
  / ``_exec_add_channel`` only ran ``normalize_channel_id`` on each
  ``channel_id`` — that helper deliberately preserves internal
  whitespace, accepts any string, and does not validate the
  Telegram username regex. Whatever the LLM emitted (the typo'd
  form or the underscored guess) leaked verbatim to storage.

The fix introduces a new ``validate_channel_username`` helper that
runs BEFORE persistence and rejects typo'd / structurally-invalid
inputs with a typed ``InvalidChannelUsername`` error plus a
Russian-language clarification suggesting the whitespace-stripped
form. The bot prompt was also bumped to v1.7.1 with a hard rule
forbidding the LLM from silently coercing whitespace to underscores
(prompt-side defence in depth).

These tests pin the post-fix invariants:

1. Embedded whitespace (single space, double space, tab, mixed)
   is REJECTED — never silently normalized to an underscored form.
2. The rejection payload includes a clarification suggestion that
   shows the user the whitespace-stripped candidate.
3. Outer whitespace is stripped (legacy ``normalize_channel_id``
   contract preserved).
4. Structurally invalid usernames (too short, too long,
   starts-with-digit, special chars, non-ASCII) are rejected with
   a typed error.
5. Valid Telegram usernames AND numeric chat ids pass through.
6. Anti-regression: ``"pro fendocrinologist"`` NEVER produces
   ``"pro_fendocrinologist"`` on any code path (helper or executor).

Cross-references:

- ``docs/notes/BUG_LOG.md`` § BUG-034
- ``docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md``
  § 2.2 (full task spec)
- ``prompts/bot.yaml`` v1.7.1 § "Channel ID normalization"
- commit ``e50449b`` (BUG-033 PR #108 — precedent style for this PR)

Synthetic-only fixtures: per AGENTS.md + handoff Key reference
paths, real persistent reuse channels (R-1, R-2) and prod owner
chat ids are NEVER referenced here. See
``test_synthetic_only_no_real_fixtures`` for the runtime guard.
"""

from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_watchlist_service import (  # type: ignore[import-not-found]  # noqa: E402
    _FakeBot,
    _FakeEmbeddingRepo,
    _FakeInterestRepo,
    _FakeMatchRepo,
    _FakeProcessedDocRepo,
)

from tg_parser.auth.models import CurrentUser  # noqa: E402
from tg_parser.bot.tools import (  # noqa: E402
    _exec_add_channel,
    _exec_subscribe_digest,
    _exec_subscribe_watchlist,
)
from tg_parser.domain.models import DigestSubscription  # noqa: E402
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# The helper is the post-fix surface; import defensively so the
# self-review (stash production fix, rerun) still collects the
# helper-level tests and skips them cleanly when the helper is
# absent. Executor-level tests below stay green by exercising the
# bug end-to-end and MUST fail against the pre-fix HEAD.
try:  # pragma: no cover — branch exists for self-review only
    from tg_parser.utils.channel_id import (
        INVALID_CHANNEL_USERNAME_ERROR_CLASS,
        validate_channel_username,
    )
except ImportError:  # pragma: no cover
    validate_channel_username = None  # type: ignore[assignment]
    INVALID_CHANNEL_USERNAME_ERROR_CLASS = "InvalidChannelUsername"


# ===========================================================================
# Constants
# ===========================================================================

# The empirical BUG-034 trigger from Test D 2026-05-24. Kept as a
# named constant so the anti-regression checks below cannot drift.
BUG034_TYPO_INPUT: str = "pro fendocrinologist"
BUG034_LLM_COERCED_FORM: str = "pro_fendocrinologist"
BUG034_CORRECT_SUGGESTION: str = "profendocrinologist"

DM_CHAT_ID: int = 100_500_011
GROUP_CHAT_ID: int = -100_500_022


# ===========================================================================
# Helpers — admin user, in-memory repos, executor patches
# ===========================================================================


def _admin(user_id: str = "user-bug034") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="bug034",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


@dataclass
class _FakeDigestSubscriptionRepo:
    """Minimal in-memory digest-subscription repo (mirrors BUG-033 test fake)."""

    store: dict[str, DigestSubscription] = field(default_factory=dict)

    async def create(self, sub: DigestSubscription) -> DigestSubscription:
        new_id = sub.id or str(uuid.uuid4())
        stored = sub.model_copy(update={"id": new_id})
        self.store[new_id] = stored
        return stored

    async def get(self, sub_id: str) -> DigestSubscription | None:
        return self.store.get(sub_id)

    async def find_by_owner_and_name(self, owner_id: str, name: str) -> DigestSubscription | None:
        for sub in self.store.values():
            if sub.owner_id == owner_id and sub.name == name:
                return sub
        return None

    async def update(self, sub_id: str, **fields: Any) -> DigestSubscription | None:
        existing = self.store.get(sub_id)
        if existing is None:
            return None
        clean: dict[str, Any] = {}
        for k, v in fields.items():
            if k == "unset_workspace_id":
                if v:
                    clean["workspace_id"] = None
                continue
            if v is not None:
                clean[k] = v
        if not clean:
            return existing
        clean["updated_at"] = datetime.now(UTC)
        new_row = existing.model_copy(update=clean)
        self.store[sub_id] = new_row
        return new_row

    async def delete(self, sub_id: str) -> bool:
        return self.store.pop(sub_id, None) is not None

    async def list_by_owner(self, owner_id: str) -> list[DigestSubscription]:
        return [s for s in self.store.values() if s.owner_id == owner_id]

    async def list_all(self) -> list[DigestSubscription]:
        return list(self.store.values())

    async def list_active(self) -> list[DigestSubscription]:
        return [s for s in self.store.values() if s.is_active]


@asynccontextmanager
async def _digest_repo_ctx(repo: _FakeDigestSubscriptionRepo):
    yield (repo, None)


@asynccontextmanager
async def _watchlist_repos_ctx(ir: _FakeInterestRepo, mr: _FakeMatchRepo):
    yield (ir, mr, _FakeProcessedDocRepo([]), _FakeEmbeddingRepo(), None)


def _patch_subscribe_digest_executor(repo: _FakeDigestSubscriptionRepo):
    return [
        patch(
            "tg_parser.services.db_context.digest_subscription_repo",
            lambda: _digest_repo_ctx(repo),
        ),
        patch(
            "tg_parser.services.background_scheduler.get_scheduler",
            lambda: object(),
        ),
        patch(
            "tg_parser.services.background_scheduler.register_digest_subscription",
            lambda *_a, **_kw: None,
        ),
        patch(
            "tg_parser.services.background_scheduler.unregister_digest_subscription",
            lambda *_a, **_kw: None,
        ),
    ]


def _patch_subscribe_watchlist_executor(
    ir: _FakeInterestRepo,
    mr: _FakeMatchRepo,
    svc: WatchlistService,
):
    return [
        patch(
            "tg_parser.services.db_context.watchlist_repos",
            lambda: _watchlist_repos_ctx(ir, mr),
        ),
        patch(
            "tg_parser.services.watchlist_service.make_watchlist_service",
            lambda **_kw: svc,
        ),
    ]


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in patches:
        p.__exit__(None, None, None)


def _make_watchlist_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


def _mock_ingestion_state_repo():
    """Mirror the helper from ``test_bot_tools_v12`` for ``_exec_add_channel``."""
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.get_source.return_value = None
    state_repo.get_source_by_username.return_value = None
    state_repo.list_sources.return_value = []
    state_repo.upsert_source.return_value = None

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo


# ===========================================================================
# Helper unit tests — validate_channel_username (pure, no I/O)
# ===========================================================================


@pytest.mark.skipif(
    validate_channel_username is None,
    reason="helper added by BUG-034 fix; skipped during pre-fix self-review",
)
class TestValidateChannelUsernameWhitespace:
    """Whitespace handling — the BUG-034 core reproduction surface."""

    def test_single_space_rejected_with_clarification(self):
        value, err = validate_channel_username(BUG034_TYPO_INPUT)
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert err["suggestion"] == BUG034_CORRECT_SUGGESTION
        # The clarification message must contain the suggested form so
        # the bot can relay it verbatim to the user.
        assert BUG034_CORRECT_SUGGESTION in err["error"]
        assert BUG034_TYPO_INPUT in err["error"]

    def test_double_space_rejected_with_clarification(self):
        value, err = validate_channel_username("pro  fendocrinologist")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        # Multi-space collapses to a single token in the suggestion —
        # ``str.split()`` with no argument splits on any run of
        # whitespace and drops empty tokens.
        assert err["suggestion"] == BUG034_CORRECT_SUGGESTION

    def test_tab_rejected_with_clarification(self):
        value, err = validate_channel_username("pro\tfendocrinologist")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert err["suggestion"] == BUG034_CORRECT_SUGGESTION

    def test_mixed_whitespace_rejected_with_clarification(self):
        # Self-review addition: combined whitespace types — the user
        # might paste a tab-padded fragment between two space-separated
        # syllables. The helper must surface the same single-token
        # suggestion.
        value, err = validate_channel_username("pro \t fendocrinologist")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert err["suggestion"] == BUG034_CORRECT_SUGGESTION

    def test_leading_whitespace_only_is_stripped_and_validates(self):
        value, err = validate_channel_username("  profendocrinologist")
        assert err is None
        assert value == "profendocrinologist"

    def test_trailing_whitespace_only_is_stripped_and_validates(self):
        value, err = validate_channel_username("profendocrinologist  ")
        assert err is None
        assert value == "profendocrinologist"

    def test_both_sides_whitespace_only_is_stripped_and_validates(self):
        value, err = validate_channel_username("  profendocrinologist  ")
        assert err is None
        assert value == "profendocrinologist"

    def test_newline_internal_rejected(self):
        # Self-review addition: ``\n`` is a whitespace character per
        # ``str.isspace()`` — paste from clipboard sometimes carries
        # newlines mid-token.
        value, err = validate_channel_username("pro\nfendocrinologist")
        assert value is None
        assert err is not None
        assert err["suggestion"] == BUG034_CORRECT_SUGGESTION


@pytest.mark.skipif(
    validate_channel_username is None,
    reason="helper added by BUG-034 fix; skipped during pre-fix self-review",
)
class TestValidateChannelUsernameRegex:
    """Telegram username regex enforcement (no whitespace pre-check involved)."""

    def test_exact_match_passes_through(self):
        value, err = validate_channel_username("profendocrinologist")
        assert err is None
        assert value == "profendocrinologist"

    def test_with_at_prefix_normalized_and_validated(self):
        value, err = validate_channel_username("@profendocrinologist")
        assert err is None
        assert value == "profendocrinologist"

    def test_with_quotes_normalized_and_validated(self):
        # Legacy BUG-003 path: quoted form still validates.
        value, err = validate_channel_username("'profendocrinologist'")
        assert err is None
        assert value == "profendocrinologist"

    def test_special_char_at_rejected(self):
        value, err = validate_channel_username("pro@fendocrinologist")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_special_char_hyphen_rejected(self):
        value, err = validate_channel_username("pro-fendocrinologist")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_special_char_dot_rejected(self):
        value, err = validate_channel_username("pro.fendocrinologist")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_too_short_4_chars_rejected(self):
        value, err = validate_channel_username("abcd")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_minimum_length_5_chars_accepted(self):
        # Self-review addition: exact lower boundary of the Telegram
        # username spec (5 chars) must validate.
        value, err = validate_channel_username("abcde")
        assert err is None
        assert value == "abcde"

    def test_maximum_length_32_chars_accepted(self):
        # Self-review addition: exact upper boundary (32 chars) must
        # validate.
        value, err = validate_channel_username("a" * 32)
        assert err is None
        assert value == "a" * 32

    def test_too_long_33_chars_rejected(self):
        value, err = validate_channel_username("a" * 33)
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_starts_with_digit_rejected(self):
        value, err = validate_channel_username("123channel")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_three_chars_rejected(self):
        # The handoff case-list mentions "pro" (< 5 chars) as a
        # boundary case — same equivalence class as ``"abcd"`` but
        # cited explicitly to keep the test diff readable.
        value, err = validate_channel_username("pro")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_cyrillic_rejected(self):
        # Self-review addition: Telegram usernames are ASCII-only per
        # spec. The pre-fix permissive path would have happily
        # persisted Cyrillic.
        value, err = validate_channel_username("канал_тест")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_greek_rejected(self):
        value, err = validate_channel_username("αβγδε")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_mixed_case_preserved(self):
        # Self-review addition: existing ``normalize_channel_id``
        # contract preserves case (BUG-003 § H3 verdict). The new
        # helper must NOT silently lower-case — DB lookup is
        # case-sensitive.
        value, err = validate_channel_username("ProFendocrinologist")
        assert err is None
        assert value == "ProFendocrinologist"

    def test_underscore_only_username_accepted(self):
        # The Telegram regex allows underscores anywhere except the
        # first character. ``pro_fendocrinologist`` (the actual
        # BUG-034 LLM-coerced output) is structurally VALID per the
        # regex — the only way to detect it as a bug is via the
        # source-existence check (out of scope for the parser-only
        # unit). The helper must NOT reject it on regex grounds.
        value, err = validate_channel_username(BUG034_LLM_COERCED_FORM)
        assert err is None
        assert value == BUG034_LLM_COERCED_FORM

    def test_only_underscores_after_letter_accepted(self):
        value, err = validate_channel_username("a____")
        assert err is None
        assert value == "a____"


@pytest.mark.skipif(
    validate_channel_username is None,
    reason="helper added by BUG-034 fix; skipped during pre-fix self-review",
)
class TestValidateChannelUsernameNumericIds:
    """Telegram numeric chat / channel ids bypass the username regex."""

    def test_positive_numeric_id_accepted(self):
        value, err = validate_channel_username("123456789")
        assert err is None
        assert value == "123456789"

    def test_supergroup_minus100_id_accepted(self):
        # ``-100…`` prefix is the canonical supergroup / channel id
        # form. Pre-fix users could pass this directly to
        # ``add_channel`` for private channels.
        value, err = validate_channel_username("-1001234567890")
        assert err is None
        assert value == "-1001234567890"

    def test_int_coerced_via_str(self):
        # Mirror ``test_utils_channel_id::test_accepts_non_string_via_str_coercion``.
        value, err = validate_channel_username(123456789)
        assert err is None
        assert value == "123456789"


@pytest.mark.skipif(
    validate_channel_username is None,
    reason="helper added by BUG-034 fix; skipped during pre-fix self-review",
)
class TestValidateChannelUsernameEmpty:
    """Empty / ``None`` / missing input."""

    def test_none_rejected(self):
        value, err = validate_channel_username(None)
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_empty_string_rejected(self):
        value, err = validate_channel_username("")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_only_whitespace_rejected(self):
        value, err = validate_channel_username("   ")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_only_at_rejected(self):
        value, err = validate_channel_username("@")
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS


@pytest.mark.skipif(
    validate_channel_username is None,
    reason="helper added by BUG-034 fix; skipped during pre-fix self-review",
)
class TestValidateChannelUsernameIdempotency:
    """Calling the validator twice on its own output is a no-op."""

    @pytest.mark.parametrize(
        "raw",
        [
            "profendocrinologist",
            "@profendocrinologist",
            "  profendocrinologist  ",
            "ProFendocrinologist",
            "123456789",
            "-1001234567890",
        ],
    )
    def test_validator_is_idempotent(self, raw: str):
        once, err1 = validate_channel_username(raw)
        assert err1 is None
        assert once is not None
        twice, err2 = validate_channel_username(once)
        assert err2 is None
        assert twice == once


@pytest.mark.skipif(
    validate_channel_username is None,
    reason="helper added by BUG-034 fix; skipped during pre-fix self-review",
)
class TestAntiRegressionSpaceToUnderscore:
    """Explicit pin: the old `.replace(" ", "_")` path must NOT be reachable."""

    def test_typo_input_never_becomes_underscored_form(self):
        """The exact BUG-034 transformation must never materialize."""
        value, err = validate_channel_username(BUG034_TYPO_INPUT)
        # Either rejected (post-fix) or normalized — but NEVER coerced
        # to the buggy underscored form.
        if err is None:
            assert value != BUG034_LLM_COERCED_FORM
        else:
            assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_underscore_form_passes_but_not_via_space_coercion(self):
        # Defensive: if a caller explicitly types the underscored form
        # (which is a structurally-valid Telegram username — see
        # ``test_underscore_only_username_accepted``) it passes. The
        # bug class is the *coercion* from space to underscore, not the
        # underscored form per se.
        value_space, err_space = validate_channel_username(BUG034_TYPO_INPUT)
        value_under, err_under = validate_channel_username(BUG034_LLM_COERCED_FORM)
        assert value_space != BUG034_LLM_COERCED_FORM
        assert err_under is None
        assert value_under == BUG034_LLM_COERCED_FORM


# ===========================================================================
# subscribe_digest end-to-end — typo'd channels never persisted
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeDigestRejectsTypoChannels:
    """Pin BUG-034 at the executor surface (the actual production path)."""

    async def test_single_space_typo_rejected_nothing_persisted(self):
        """Exact BUG-034 reproduction — must NOT persist the subscription."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": [BUG034_TYPO_INPUT],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert "suggestion" in result
        assert result["suggestion"] == BUG034_CORRECT_SUGGESTION
        assert len(repo.store) == 0

    async def test_double_space_typo_rejected(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["pro  fendocrinologist"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert result["suggestion"] == BUG034_CORRECT_SUGGESTION
        assert len(repo.store) == 0

    async def test_tab_typo_rejected(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["pro\tfendocrinologist"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(repo.store) == 0

    async def test_special_char_rejected(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["pro@fendocrinologist"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(repo.store) == 0

    async def test_exact_match_persists_successfully(self):
        """Positive control — canonical username flows through.

        BUG-031 closure: confirm=True required to reach persistence.
        """
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["profendocrinologist"],
                    "cron_expression": "0 9 * * *",
                    "confirm": True,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        assert len(repo.store) == 1
        stored = next(iter(repo.store.values()))
        assert stored.channel_ids == ["profendocrinologist"]

    async def test_outer_whitespace_stripped_then_persists(self):
        """Outer whitespace is stripped (legacy ``normalize_channel_id`` contract)."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["  profendocrinologist  "],
                    "cron_expression": "0 9 * * *",
                    "confirm": True,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        stored = next(iter(repo.store.values()))
        assert stored.channel_ids == ["profendocrinologist"]

    async def test_first_invalid_in_list_rejects_entire_subscribe(self):
        """A single invalid entry aborts persistence — fail-fast contract."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": [BUG034_TYPO_INPUT, "valid_channel"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(repo.store) == 0

    async def test_second_invalid_in_list_rejects_entire_subscribe(self):
        """Self-review addition: invalid second entry also fails-fast."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["valid_channel", BUG034_TYPO_INPUT],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(repo.store) == 0

    async def test_none_entry_in_list_rejected_with_typed_error(self):
        """Self-review addition: pre-fix silently filtered ``None`` entries via
        ``[n for n in (normalize_channel_id(c) for c in raw_channels) if n]``
        and then emitted ``"channel_ids must contain at least one channel"`` —
        a free-form error string that callers cannot dispatch on. Post-fix
        emits a typed ``InvalidChannelUsername`` so the bot can route on the
        error class. Pre-fix behavior change is intentional.
        """
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": [None],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(repo.store) == 0

    async def test_empty_string_entry_in_list_rejected_with_typed_error(self):
        """Self-review addition: empty-string entry handled symmetrically."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": [""],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(repo.store) == 0

    async def test_at_prefix_typo_still_rejected(self):
        """Self-review addition: ``@`` prefix must be stripped BEFORE the
        whitespace check (so the suggestion is the bare username form,
        not the @-prefixed echo). Without this the helper would surface
        «Канал «@pro fendocrinologist»…» which still flags the bug but
        leaks the leading ``@`` into the suggestion field, breaking the
        downstream "did you mean X?" UX.
        """
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@pro fendocrinologist"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        # ``@`` prefix carried over to the suggestion would break the
        # downstream UX — the suggestion must be the bare username.
        assert result["suggestion"] == BUG034_CORRECT_SUGGESTION
        assert not result["suggestion"].startswith("@")
        assert len(repo.store) == 0


# ===========================================================================
# subscribe_watchlist end-to-end — symmetric coverage
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeWatchlistRejectsTypoChannels:
    """Mirror of the digest executor tests — same surface, same invariants."""

    async def test_single_space_typo_rejected_nothing_persisted(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": [BUG034_TYPO_INPUT],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert result["suggestion"] == BUG034_CORRECT_SUGGESTION
        assert len(ir.store) == 0

    async def test_exact_match_persists(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["profendocrinologist"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                    "confirm": True,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" not in result, result
        stored = next(iter(ir.store.values()))
        assert stored.channel_ids == ["profendocrinologist"]

    async def test_special_char_rejected(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["pro@fendocrinologist"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert len(ir.store) == 0


# ===========================================================================
# add_channel end-to-end — single channel_id surface
# ===========================================================================


@pytest.mark.asyncio
class TestAddChannelRejectsTypoChannels:
    """Symmetric coverage on the write surface that creates Source rows."""

    async def test_single_space_typo_rejected_in_preview(self):
        ctx, state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"channel_id": BUG034_TYPO_INPUT, "confirm": False},
                current_user=_admin(),
            )
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert result["suggestion"] == BUG034_CORRECT_SUGGESTION
        state_repo.upsert_source.assert_not_awaited()

    async def test_single_space_typo_rejected_in_confirm(self):
        """Even on confirm=true the typo'd input must never write a row."""
        ctx, state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"channel_id": BUG034_TYPO_INPUT, "confirm": True},
                current_user=_admin(),
            )
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        state_repo.upsert_source.assert_not_awaited()

    async def test_exact_match_preview_succeeds(self):
        ctx, _state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"channel_id": "profendocrinologist", "confirm": False},
                current_user=_admin(),
            )
        assert result.get("preview") is True
        assert result["channel_id"] == "profendocrinologist"

    async def test_special_char_rejected(self):
        ctx, state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"channel_id": "pro@fendocrinologist", "confirm": False},
                current_user=_admin(),
            )
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        state_repo.upsert_source.assert_not_awaited()

    async def test_missing_channel_id_rejected(self):
        ctx, state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"confirm": False},
                current_user=_admin(),
            )
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        state_repo.upsert_source.assert_not_awaited()

    async def test_too_short_rejected(self):
        ctx, state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"channel_id": "pro", "confirm": False},
                current_user=_admin(),
            )
        assert result.get("error_class") == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    async def test_numeric_id_accepted(self):
        # Self-review addition: private channels and supergroups are
        # addressable by ``-100…`` numeric id. The validator must let
        # them through so ``_exec_add_channel`` can register them.
        ctx, _state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            result = await _exec_add_channel(
                {"channel_id": "-1001234567890", "confirm": False},
                current_user=_admin(),
            )
        assert result.get("preview") is True
        assert result["channel_id"] == "-1001234567890"


# ===========================================================================
# Anti-regression: persisted forms never include the BUG-034 coerced shape
# ===========================================================================


@pytest.mark.asyncio
class TestAntiRegressionPersistedForms:
    """No code path may persist ``"pro_fendocrinologist"`` from a space input."""

    async def test_subscribe_digest_typo_never_persists_underscored_form(self):
        """The grand assertion — directly inverts the bug observation."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": [BUG034_TYPO_INPUT],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        # The bug fingerprint: ANY persisted row carrying
        # ``"pro_fendocrinologist"`` as a channel_id when the input
        # was the space-separated typo is the regression.
        for sub in repo.store.values():
            assert BUG034_LLM_COERCED_FORM not in sub.channel_ids, (
                f"BUG-034 regression: space input coerced to {BUG034_LLM_COERCED_FORM} "
                f"in persisted subscription {sub.id!r}"
            )

    async def test_subscribe_watchlist_typo_never_persists_underscored_form(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": [BUG034_TYPO_INPUT],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        for interest in ir.store.values():
            assert BUG034_LLM_COERCED_FORM not in interest.channel_ids, (
                f"BUG-034 regression: space input coerced to {BUG034_LLM_COERCED_FORM} "
                f"in persisted interest {interest.id!r}"
            )

    async def test_add_channel_typo_never_persists_underscored_form(self):
        ctx, state_repo = _mock_ingestion_state_repo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", ctx):
            await _exec_add_channel(
                {"channel_id": BUG034_TYPO_INPUT, "confirm": True},
                current_user=_admin(),
            )
        # The upsert must not have happened at all; if it ever does,
        # the persisted form must not be the underscored one.
        for call in state_repo.upsert_source.await_args_list:
            persisted = call.args[0] if call.args else call.kwargs.get("source")
            assert getattr(persisted, "channel_id", None) != BUG034_LLM_COERCED_FORM
            assert getattr(persisted, "source_id", None) != BUG034_LLM_COERCED_FORM


# ===========================================================================
# Synthetic-fixture guard — real prod channels never appear in this module
# ===========================================================================


def test_synthetic_only_no_real_fixtures():
    """Anti-pattern guard.

    Real persistent reuse fixtures (R-1, R-2) and the operator's
    real prod chat id (S-2) are forbidden in tests per
    ``AGENTS.md`` + handoff Key reference paths. This module
    deliberately uses only synthetic names. The guard below pins
    the constraint so a future edit cannot quietly add a real
    fixture reference.

    All forbidden tokens are assembled at runtime so they never
    appear verbatim in this source file — otherwise the guard
    would trip on its own self-referencing string literals.
    """
    import inspect

    this_module = inspect.getsource(sys.modules[__name__])

    # R-1 / R-2 persistent reuse fixtures (handoff Key reference paths).
    forbidden_fixture_r1 = "vps_watch_test_" + "r1_" + "Alex"
    forbidden_fixture_r2 = "vps_watch_test_" + "r2_" + "Alex"
    # Group fixture (BUG-033 Test D context).
    forbidden_group_name = "vps-watch-" + "test-" + "grp"
    for forbidden in (forbidden_fixture_r1, forbidden_fixture_r2, forbidden_group_name):
        assert forbidden not in this_module, (
            f"Forbidden real fixture {forbidden!r} referenced in BUG-034 tests"
        )

    # Real prod chat id (S-2) — operator's real Telegram user.
    forbidden_real_owner = int("544" + "578" + "1511")
    assert str(forbidden_real_owner) not in this_module, (
        "Forbidden real prod chat_id S-2 referenced in BUG-034 tests"
    )

    # BUG-033 Test D group chat_id — also off-limits for new tests.
    forbidden_group_id = int("-527" + "967" + "2667")
    assert str(forbidden_group_id) not in this_module, (
        "Forbidden real group chat_id (Test D context) referenced in BUG-034 tests"
    )
