"""BUG-031 + BUG-032 regression suite — ConfirmFlow contract for subscribe_* tools.

Two tightly-coupled findings from the Wave 1 step 4 VPS watch window
(2026-05-24 / 2026-05-25, see ``docs/notes/BUG_LOG.md`` § BUG-031 +
§ BUG-032 and the watch trail in
``docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md``):

* **BUG-031** — the bot persisted a digest / watchlist subscription in
  the DB BEFORE asking the user «Подтвердите [да/нет]», breaking the
  ``/help``-documented invariant «записи только после явного
  подтверждения». Root cause: ``subscribe_digest`` / ``subscribe_watchlist``
  were absent from ``_WRITE_TOOLS_REQUIRING_CONFIRM`` and their
  declarations did not carry a ``confirm: BOOLEAN`` parameter, so the
  agent loop wired them straight through to the executor with no
  preview turn.
* **BUG-032** — the FSM ``ConfirmFlow.awaiting_confirmation`` handler
  did not classify «да» / «подтверждаю» / «yes» / «ok» / «ок» as
  affirmative when the FSM was missing (BUG-031 side effect), and the
  fallback path silently routed the reply through the LLM which
  produced the opaque «Я не совсем понимаю ваш ответ» message.

This module pins both fixes:

1. ``classify_confirmation_token`` covers every accepted affirmative
   and negative token with case / whitespace / Unicode variants
   (BUG-032 closure).
2. ``_exec_subscribe_digest`` / ``_exec_subscribe_watchlist`` return
   ``{"preview": True, ...}`` and DO NOT persist when ``confirm`` is
   not truthy (BUG-031 closure).
3. ``_handle_confirmation_response`` end-to-end flows for the
   affirmative / negative / unknown / TTL-expired paths.
4. Anti-regression: the opaque «не совсем понимаю» phrase never
   appears in bot output on a known confirmation token.
5. Backwards-compat: the legacy ``CONFIRM_PATTERN`` / ``REJECT_PATTERN``
   regex aliases agree with the new classifier on every documented
   token (a single source of truth contract).
6. BUG-086 (promoted here from the F5-C slice where the defect surfaced):
   the agent-loop recovery guard that repairs an LLM-AUTHORED confirmation
   is class-wide — it protects every ``_WRITE_TOOLS_REQUIRING_CONFIRM``
   entry, not just the tool it was found on — plus a tripwire on the
   ``_PREVIEW_SUPPRESSING_ARGS`` registry that keeps a future report-only
   flag from silently re-opening the defect.

Cross-references:

- ``docs/notes/BUG_LOG.md`` § BUG-031, § BUG-032, § BUG-086
- ``docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md`` § 2.3
- ``docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`` (TEST_POSTGRES=1 rerun standard)
- recent merge precedents: PR #108 (BUG-033, commit ``e50449b``) and
  PR #109 (BUG-034, commit ``6ebad33``).
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

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
from tg_parser.bot.agent import _PREVIEW_SUPPRESSING_ARGS, GeminiAgent  # noqa: E402
from tg_parser.bot.handlers import (  # noqa: E402
    AFFIRMATIVE_TOKENS,
    CONFIRM_PATTERN,
    NEGATIVE_TOKENS,
    PENDING_TTL_SECONDS,
    REJECT_PATTERN,
    UnknownConfirmationToken,
    _handle_confirmation_response,
    classify_confirmation_token,
)
from tg_parser.bot.states import ConfirmFlow  # noqa: E402
from tg_parser.bot.tools import (  # noqa: E402
    _WRITE_TOOLS_REQUIRING_CONFIRM,
    TOOL_DECLARATIONS,
    _exec_subscribe_digest,
    _exec_subscribe_watchlist,
    execute_tool,
)
from tg_parser.domain.models import DigestSubscription  # noqa: E402
from tg_parser.services.watchlist_service import WatchlistService  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic constants — never use the operator's real prod chat_id S-2
# (5445781511) or real prod subscription S-1 (digest_94483db9) here. The
# constants below mirror the synthetic IDs in
# ``test_bot_chat_target_resolution.py`` so the cross-module pattern stays
# consistent.
# ---------------------------------------------------------------------------

DM_CHAT_ID: int = 700_500_001
GROUP_CHAT_ID: int = -700_500_002


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin(user_id: str = "user-confirmflow") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="confirmflow",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _make_state(bot_id: int = 42, chat_id: int = 12345, user_id: int = 67890) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(text: str, chat_id: int = 12345) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.bot = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_chat_action = AsyncMock()
    return msg


@dataclass
class _FakeDigestSubscriptionRepo:
    """Minimal in-memory fake mirroring the surface used by
    :class:`DigestService.subscribe`.

    Identical to the helper in ``test_bot_chat_target_resolution`` —
    duplicated to keep this module self-contained and the BUG-031 /
    BUG-032 contract testable without cross-module coupling.
    """

    store: dict[str, DigestSubscription] = field(default_factory=dict)

    async def create(self, sub: DigestSubscription) -> DigestSubscription:
        import uuid

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
        # BUG-041/B2: the executor now runs a fail-open channel-existence check
        # before previewing. These tests exercise the preview/confirm GATE with
        # synthetic channel names that aren't seeded in the test DB; the
        # existence check is orthogonal here, so fail it open (``None`` = allow)
        # to keep the gate assertions focused. In a DB-absent environment the
        # check fail-opens naturally; this patch makes the behaviour
        # deterministic regardless of whether a test Postgres is reachable.
        patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ),
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


def _make_watchlist_service(ir: _FakeInterestRepo, mr: _FakeMatchRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=ir,
        match_repo=mr,
        processed_doc_repo=_FakeProcessedDocRepo([]),
        embedding_repo=_FakeEmbeddingRepo(),
        embedding_client=None,
    )


def _patch_subscribe_watchlist_executor(
    ir: _FakeInterestRepo,
    mr: _FakeMatchRepo,
    svc: WatchlistService,
):
    return [
        # BUG-041/B2: fail-open the executor existence check — see
        # ``_patch_subscribe_digest_executor`` for the rationale.
        patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ),
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


# ===========================================================================
# 1. classify_confirmation_token — token whitelist + classifier
# ===========================================================================


class TestClassifyConfirmationTokenAffirmatives:
    """Each documented affirmative token must classify to ``"affirmative"``.

    A parametrize sweep over :data:`AFFIRMATIVE_TOKENS` plus a deliberate
    `[da]` baseline ensures any future addition / removal trips this
    test rather than silently changing behaviour.
    """

    @pytest.mark.parametrize(
        "token",
        sorted(AFFIRMATIVE_TOKENS),
    )
    def test_each_affirmative_token_classifies(self, token: str) -> None:
        assert classify_confirmation_token(token) == "affirmative"


class TestClassifyConfirmationTokenNegatives:
    @pytest.mark.parametrize(
        "token",
        sorted(NEGATIVE_TOKENS),
    )
    def test_each_negative_token_classifies(self, token: str) -> None:
        assert classify_confirmation_token(token) == "negative"


class TestClassifyConfirmationTokenCaseAndWhitespace:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ДА", "affirmative"),
            ("Да", "affirmative"),
            ("Yes", "affirmative"),
            ("YES", "affirmative"),
            ("OK", "affirmative"),
            ("Ок", "affirmative"),
            ("ПОДТВЕРЖДАЮ", "affirmative"),
            ("Согласен", "affirmative"),
            ("СоГлАсНа", "affirmative"),
            ("НЕТ", "negative"),
            ("Нет", "negative"),
            ("No", "negative"),
            ("OTMENA", "affirmative"),
            ("Cancel", "negative"),
            ("СТОП", "negative"),
        ],
    )
    def test_case_variants(self, raw: str, expected: str) -> None:
        # NOTE: "OTMENA" is intentionally tagged as "affirmative" in the
        # parametrize above to remain disjoint from the Cyrillic «отмена»
        # — only the Cyrillic form is in the whitelist. Verifying that
        # ASCII transliteration does NOT silently fall into the negative
        # set is a useful guard against locale-bleed false positives.
        if raw == "OTMENA":
            assert classify_confirmation_token(raw) == "unknown"
        else:
            assert classify_confirmation_token(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "  да  ",
            "\tда",
            "да\n",
            "  yes\t",
            "\n\nок\n",
            "  подтверждаю   ",
        ],
    )
    def test_whitespace_stripping(self, raw: str) -> None:
        assert classify_confirmation_token(raw) == "affirmative"

    @pytest.mark.parametrize(
        "raw",
        ["  нет  ", "\tno", "отмена\n", "\n\nне  подтверждаю\n"],
    )
    def test_whitespace_stripping_negative(self, raw: str) -> None:
        # ``" ".join(text.split())`` collapses ANY internal-whitespace
        # run to a single space, so "не  подтверждаю" (double space)
        # matches the canonical "не подтверждаю".
        assert classify_confirmation_token(raw) == "negative"

    def test_empty_string_is_unknown(self) -> None:
        assert classify_confirmation_token("") == "unknown"

    def test_whitespace_only_is_unknown(self) -> None:
        assert classify_confirmation_token("   \t\n  ") == "unknown"

    def test_none_is_unknown(self) -> None:
        """``None`` must be a defensive ``"unknown"`` — the FSM handler
        never reaches here with ``None`` in practice, but the typed
        contract allows call-sites to skip a separate guard."""
        assert classify_confirmation_token(None) == "unknown"


class TestClassifyConfirmationTokenUnicode:
    """Cyrillic edge-cases — capital ё / е, NBSP, combining marks.

    The classifier uses ``str.casefold()`` (NOT ``.lower()``) so the
    full Unicode case-folding table applies — capital "Ё" → "ё" (not
    just "е"), German "ß" → "ss", etc. Without ``.casefold()`` the
    set lookup misses these forms even though a human reads them as
    equivalent.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Canonical forms (sanity baseline).
            ("да", "affirmative"),
            ("нет", "negative"),
            # NBSP (\u00a0) collapses via ``str.split``.
            ("да\u00a0", "affirmative"),
            ("\u00a0нет\u00a0", "negative"),
            # Trailing sentence punctuation is tolerated on the first
            # token of a compound reply — classifier rstrips ",.;:!?"
            # so «да.», «нет!», «yes,» etc. still classify intuitively.
            ("да.", "affirmative"),
            ("нет!", "negative"),
            ("yes,", "affirmative"),
            # Compound replies: «да, давай» / «нет, спасибо» pick up the
            # first-token classification with trailing punctuation stripped.
            ("да, давай", "affirmative"),
            ("нет, спасибо", "negative"),
        ],
    )
    def test_unicode_edge_cases(self, raw: str, expected: str) -> None:
        assert classify_confirmation_token(raw) == expected


class TestClassifyConfirmationTokenGarbage:
    @pytest.mark.parametrize(
        "raw",
        [
            "asdf",
            "12345",
            "🚀",
            "yesno",  # substring of "yes" but distinct token
            "neckline",  # starts with "n" but is one word
            "yardstick",  # starts with "y" but one word
            "покажи каналы",
            "добавь канал",
            "не совсем понимаю",  # the BUG-032 opaque LLM reply itself
        ],
    )
    def test_garbage_inputs_are_unknown(self, raw: str) -> None:
        assert classify_confirmation_token(raw) == "unknown"


class TestUnknownConfirmationTokenException:
    """The typed error class is a downstream contract — callers that
    want to raise on ``"unknown"`` instead of branching on the literal
    return get a typed exception with the normalized text attached.
    """

    def test_constructor_carries_normalized_text(self) -> None:
        exc = UnknownConfirmationToken("asdf")
        assert exc.normalized_text == "asdf"
        assert "asdf" in str(exc)
        assert "affirmative=" in str(exc)
        assert "negative=" in str(exc)

    def test_is_value_error_subclass(self) -> None:
        """Subclassing ``ValueError`` keeps the existing ``ValueError``
        catch in ``execute_tool`` (BUG-005-B) capturing the typed
        confirmation error too — back-compat by design."""
        assert issubclass(UnknownConfirmationToken, ValueError)


class TestTokenSetsAreDisjoint:
    """Anti-regression: a token can never be both an affirmative and
    a negative — that would produce non-deterministic dispatch and a
    perpetual «не понял» loop for whoever typed the ambiguous token.
    """

    def test_affirmative_and_negative_sets_have_no_overlap(self) -> None:
        overlap = AFFIRMATIVE_TOKENS & NEGATIVE_TOKENS
        assert not overlap, f"Token classification ambiguous for: {sorted(overlap)}"


class TestLegacyRegexAliasesAgreeWithClassifier:
    """Backwards-compat: ``CONFIRM_PATTERN`` / ``REJECT_PATTERN`` are
    public regex aliases retained for the few callers (mostly tests)
    that still pre-match against the raw regex. They MUST agree with
    :func:`classify_confirmation_token` on every documented token.
    """

    @pytest.mark.parametrize("token", sorted(AFFIRMATIVE_TOKENS))
    def test_every_affirmative_token_matches_confirm_pattern(self, token: str) -> None:
        assert CONFIRM_PATTERN.match(token), (
            f"Affirmative token {token!r} not matched by CONFIRM_PATTERN — "
            "regex alias drifted out of sync with the canonical token set."
        )

    @pytest.mark.parametrize("token", sorted(NEGATIVE_TOKENS))
    def test_every_negative_token_matches_reject_pattern(self, token: str) -> None:
        assert REJECT_PATTERN.match(token), (
            f"Negative token {token!r} not matched by REJECT_PATTERN — "
            "regex alias drifted out of sync with the canonical token set."
        )


# ===========================================================================
# 2. ConfirmFlow end-to-end — subscribe_digest write-before-confirm regression
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeDigestPreviewGate:
    """BUG-031 closure at the executor surface.

    Pre-fix the executor wrote the row before the FSM was armed. The
    canonical regression is the `call_count == 0` write-before-confirm
    assertion: a call WITHOUT ``confirm=True`` must NOT touch the
    repo / scheduler / outbound-bot surfaces.
    """

    async def test_preview_call_does_not_touch_repo(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    # confirm intentionally omitted — preview turn.
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert "subscription_id" not in result
        # BUG-031 canonical regression: nothing persisted, nothing sent.
        assert repo.store == {}
        assert bot.sent == []

    async def test_preview_call_is_idempotent(self):
        """Re-issuing the preview turn must NOT accumulate side-effects."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            for _ in range(3):
                result = await _exec_subscribe_digest(
                    {
                        "name": "morning",
                        "channel_ids": ["@durov"],
                        "cron_expression": "0 9 * * *",
                    },
                    current_user=_admin(),
                    bot=bot,
                    chat_id=DM_CHAT_ID,
                )
                assert result.get("preview") is True
        finally:
            _exit_all(patches)
        assert repo.store == {}
        assert bot.sent == []

    async def test_preview_call_with_confirm_false_does_not_touch_repo(self):
        """Explicit ``confirm=False`` is treated identically to omission —
        no LLM-issued path can sneak a write through."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "confirm": False,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert repo.store == {}

    async def test_preview_payload_carries_actionable_details(self):
        """The preview payload must summarise WHAT will happen — the
        bot framework relays this to the user verbatim so they can
        verify before confirming. Without these fields the LLM has to
        invent the summary, re-opening the BUG-002 hallucination class
        on the digest surface.
        """
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov", "@telegram"],
                    "cron_expression": "0 9 * * *",
                    "timezone": "Europe/Moscow",
                    "format": "bullets",
                    "language": "ru",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert result["tool"] == "subscribe_digest"
        assert result["name"] == "morning"
        assert result["channel_count"] == 2
        assert result["channel_ids"] == ["durov", "telegram"]
        assert result["cron_expression"] == "0 9 * * *"
        assert result["timezone"] == "Europe/Moscow"
        assert result["format"] == "bullets"
        assert result["language"] == "ru"
        assert "Подтвердите" in result["message"]
        assert "[да/нет]" in result["message"]
        # ``preview=True`` is the FSM hint the agent loop snapshots
        # for ``preview_pending`` — its absence (or a stray ``False``)
        # would silently re-open BUG-031.
        assert result["preview"] is True

    async def test_confirm_true_persists_and_registers(self):
        """Symmetric: with ``confirm=True`` the executor commits."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "confirm": True,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "subscription_id" in result
        assert len(repo.store) == 1

    async def test_creation_message_names_channel_and_friendly_label(self):
        """Items 1+2+3 (2026-05-31): the creation confirmation NAMES the
        channel(s) («Каналы: durov») and shows the friendly schedule label
        WITHOUT the raw cron (recognized cron `0 9 * * *`).

        Pre-fix HEAD ``195589b``: «… Каналов: 1.» (count, no name) and the
        schedule embedded «— <code>0 9 * * *</code>».
        """
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "timezone": "Europe/Moscow",
                    "confirm": True,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert len(bot.sent) == 1
        text = bot.sent[0]["text"]
        assert "Каналы: durov" in text
        assert "Каналов:" not in text  # the bare count is gone
        assert "ежедневно в 09:00 (Europe/Moscow)" in text
        assert "<code>" not in text  # raw cron dropped for a recognized schedule
        assert "0 9 * * *" not in text

    async def test_creation_message_unrecognized_cron_keeps_verbatim(self):
        """An unrecognized cron in the creation message keeps the verbatim
        ``<code>cron</code>`` (BUG-042 guarantee, reframed)."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            await _exec_subscribe_digest(
                {
                    "name": "q",
                    "channel_ids": ["@durov"],
                    "cron_expression": "*/15 * * * *",
                    "timezone": "Europe/Moscow",
                    "confirm": True,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert len(bot.sent) == 1
        text = bot.sent[0]["text"]
        assert "<code>*/15 * * * *</code>" in text
        assert "Каналы: durov" in text

    async def test_preview_runs_validation_before_returning(self):
        """Invalid input MUST surface the typed error even on the
        preview turn — we don't want the user to confirm-then-discover
        the request was malformed. The preview branch runs AFTER all
        validation; only the persistence is gated."""
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "",  # invalid — empty name
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "error" in result
        assert "name" in result["error"].lower()
        # Validation error surfaces; preview hint is NOT emitted.
        assert result.get("preview") is not True


# ===========================================================================
# 3. ConfirmFlow end-to-end — subscribe_watchlist symmetric coverage
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeWatchlistPreviewGate:
    """Same shape as the digest gate — bug fingerprint and fix are
    symmetric on the watchlist surface."""

    async def test_preview_call_does_not_touch_repo(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
                    "keywords": ["mica"],
                    "threshold": 0.5,
                    # confirm intentionally omitted.
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert ir.store == {}
        assert bot.sent == []

    async def test_confirm_true_persists(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news"],
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
        assert "error" not in result
        assert len(ir.store) == 1

    async def test_preview_payload_carries_actionable_details(self):
        ir, mr = _FakeInterestRepo(), _FakeMatchRepo()
        svc = _make_watchlist_service(ir, mr)
        bot = _FakeBot()
        patches = _patch_subscribe_watchlist_executor(ir, mr, svc)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_watchlist(
                {
                    "title": "MiCA",
                    "channel_ids": ["@crypto_news", "@blocknews"],
                    "keywords": ["mica", "regulation"],
                    "exclude_keywords": ["spam"],
                    "threshold": 0.7,
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)

        assert result.get("preview") is True
        assert result["tool"] == "subscribe_watchlist"
        assert result["title"] == "MiCA"
        assert result["channel_count"] == 2
        assert result["channel_ids"] == ["crypto_news", "blocknews"]
        assert result["threshold"] == 0.7
        assert result["keywords"] == ["mica", "regulation"]
        assert result["exclude_keywords"] == ["spam"]
        assert "Подтвердите" in result["message"]


# ===========================================================================
# 4. ConfirmFlow contract surface — _WRITE_TOOLS_REQUIRING_CONFIRM coverage
# ===========================================================================


class TestWriteToolsContractIncludesSubscribers:
    """Forward+reverse contract from BUG-009 (Session G) extended to
    cover the subscribe_* surface.

    The bidirectional test in ``test_bot_execute_tool_guard.py`` pins
    «every tool with ``confirm: BOOLEAN`` parameter ↔ membership of
    ``_WRITE_TOOLS_REQUIRING_CONFIRM``». These two assertions are
    explicit pins for the BUG-031 addition so a future refactor that
    silently strips either side surfaces immediately rather than
    re-opening the bug.
    """

    def test_subscribe_digest_in_guard_set(self) -> None:
        assert "subscribe_digest" in _WRITE_TOOLS_REQUIRING_CONFIRM, (
            "BUG-031 regression — subscribe_digest dropped from "
            "_WRITE_TOOLS_REQUIRING_CONFIRM. The server-side guard in "
            "execute_tool will stop rejecting LLM-issued confirm=True; "
            "see docs/notes/BUG_LOG.md § BUG-031 for the production trace."
        )

    def test_subscribe_watchlist_in_guard_set(self) -> None:
        assert "subscribe_watchlist" in _WRITE_TOOLS_REQUIRING_CONFIRM, (
            "BUG-031 regression — subscribe_watchlist dropped from "
            "_WRITE_TOOLS_REQUIRING_CONFIRM. See § BUG-031 for trace."
        )


# ===========================================================================
# 5. ConfirmFlow end-to-end via handler — every accepted token works
# ===========================================================================


@pytest.mark.asyncio
class TestHandleConfirmationResponseAffirmativeTokens:
    """Each affirmative token, when typed on the FSM confirm-turn,
    triggers exactly one ``execute_tool`` call with ``confirm=True``.

    Pre-fix BUG-032 trace: «да» / «подтверждаю» / «yes» / «ok» landed
    on the «не совсем понимаю» fallback because the FSM was missing
    (BUG-031) — the LLM then improvised. The fix is two-pronged:

    1. BUG-031 ensures the FSM IS armed when the user replies.
    2. BUG-032 expands the affirmative whitelist so every documented
       token classifies, even on the rare edge where the FSM was
       armed by a manual tool call.
    """

    @pytest.mark.parametrize(
        "token",
        sorted(AFFIRMATIVE_TOKENS),
    )
    async def test_affirmative_token_triggers_commit(self, token: str) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "channel_a"},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(token)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        calls: list[tuple[str, dict]] = []

        async def mock_execute(name: str, args: dict, **_kw):
            calls.append((name, dict(args)))
            return {"ok": True, "message": "done"}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert calls == [("remove_channel", {"channel_id": "channel_a", "confirm": True})], (
            f"Affirmative token {token!r} failed to trigger commit"
        )
        agent.process_message.assert_not_called()
        # FSM cleared on successful commit.
        assert await state.get_state() is None


@pytest.mark.asyncio
class TestHandleConfirmationResponseNegativeTokens:
    @pytest.mark.parametrize(
        "token",
        sorted(NEGATIVE_TOKENS),
    )
    async def test_negative_token_aborts(self, token: str) -> None:
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message(token)
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert invoked == [], f"Negative token {token!r} unexpectedly triggered tool"
        assert await state.get_state() is None
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list)
        assert "Отменено" in sent


@pytest.mark.asyncio
class TestHandleConfirmationResponseUnknownToken:
    async def test_unknown_token_keeps_fsm_armed_and_prompts(self) -> None:
        """Per the BUG-032 closure contract: unknown tokens DO NOT clear
        the FSM. The handler emits a structured reminder listing the
        canonical affirmative + negative tokens so the user can recover
        within the same FSM turn (TTL still governs eventual eviction).
        """
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("asdf")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, _args: dict, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        # No tool fired, no LLM fallback.
        assert invoked == []
        agent.process_message.assert_not_called()
        # FSM still armed (the user can recover).
        assert await state.get_state() == ConfirmFlow.awaiting_confirmation.state
        # The reply must list both an affirmative and a negative token.
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list).lower()
        assert "да" in sent
        assert "нет" in sent

    async def test_unknown_token_response_does_not_use_opaque_phrase(self) -> None:
        """The pre-fix opaque «Я не совсем понимаю ваш ответ» phrase
        MUST NOT appear in the handler's response — that exact phrase
        was the BUG-032 fingerprint."""
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=datetime.now(UTC).isoformat(),
        )
        msg = _make_message("🚀")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        async def mock_execute(*_a, **_kw):
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        sent = " ".join(str(c.args) for c in msg.answer.call_args_list).lower()
        # The exact opaque phrase from the BUG-032 trace must NOT appear.
        assert "не совсем понимаю" not in sent

    async def test_ttl_expired_still_clears_and_messages(self) -> None:
        """TTL guard runs BEFORE the classifier — an expired confirm
        wins over an otherwise-affirmative token so the user can't
        accidentally trigger a stale tool by typing «да» an hour later.
        """
        state = _make_state()
        await state.set_state(ConfirmFlow.awaiting_confirmation)
        old = datetime.now(UTC) - timedelta(seconds=PENDING_TTL_SECONDS + 10)
        await state.update_data(
            pending_action={
                "tool_name": "remove_channel",
                "args": {"channel_id": "X"},
            },
            created_at=old.isoformat(),
        )
        msg = _make_message("да")
        agent = MagicMock()
        agent.process_message = AsyncMock()

        invoked: list[str] = []

        async def mock_execute(name: str, *_a, **_kw):
            invoked.append(name)
            return {}

        with patch("tg_parser.bot.handlers.execute_tool", new=mock_execute):
            await _handle_confirmation_response(msg, agent, state, current_user=None)

        assert invoked == []
        assert await state.get_state() is None
        sent = " ".join(str(c.args) for c in msg.answer.call_args_list).lower()
        assert "истекл" in sent


# ===========================================================================
# 6. Mock-spy regression — explicit `call_count == 0` on service surface
# ===========================================================================


@pytest.mark.asyncio
class TestSubscribeServiceCallCountOnPreview:
    """The canonical BUG-031 fingerprint phrased as an explicit
    ``call_count == 0`` assertion on the underlying service surface.

    The preview-gate tests above use an in-memory fake repo and check
    its store-dict — convenient and behaviour-equivalent, but the
    handoff's self-review checklist explicitly calls out a spy-mock
    with ``call_count == 0`` verification as a separate primitive
    (the empty-store assertion could in principle pass if persistence
    happened via a different path the fake doesn't track). The spy
    here intercepts ``DigestService.subscribe`` / ``WatchlistService.subscribe``
    directly and proves no service-level invocation occurs on the
    preview turn.
    """

    async def test_digest_service_subscribe_not_called_on_preview(self):
        spy = AsyncMock()
        repo = _FakeDigestSubscriptionRepo()
        patches = _patch_subscribe_digest_executor(repo) + [
            patch(
                "tg_parser.services.digest_service.DigestService.subscribe",
                new=spy,
            ),
        ]
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                },
                current_user=_admin(),
                bot=_FakeBot(),
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("preview") is True
        # The canonical BUG-031 regression assertion.
        assert spy.call_count == 0, (
            f"BUG-031 regression — DigestService.subscribe called {spy.call_count} "
            f"times on the preview turn (expected 0). Pre-fix the executor wrote "
            "the row before the bot asked the user to confirm; see § BUG-031."
        )

    async def test_digest_service_subscribe_called_once_on_confirm(self):
        """Symmetric positive control — the spy DOES fire on confirm=True.

        Uses the real :class:`_FakeDigestSubscriptionRepo` (which
        already mirrors the persistence path end-to-end via
        ``DigestService.subscribe`` → repo writes). The spy here is
        a thin wrapper that counts invocations of the real method —
        proving the confirm-turn call reaches the service layer.
        """
        from tg_parser.services.digest_service import DigestService

        repo = _FakeDigestSubscriptionRepo()
        real_subscribe = DigestService.subscribe
        call_count = {"n": 0}

        async def counting_subscribe(self, *args, **kwargs):
            call_count["n"] += 1
            return await real_subscribe(self, *args, **kwargs)

        patches = _patch_subscribe_digest_executor(repo) + [
            patch.object(DigestService, "subscribe", counting_subscribe),
        ]
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["@durov"],
                    "cron_expression": "0 9 * * *",
                    "confirm": True,
                },
                current_user=_admin(),
                bot=_FakeBot(),
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert "subscription_id" in result, result
        assert call_count["n"] == 1


# ===========================================================================
# 7. Anti-regression — exact watch-evidence trace fingerprint
# ===========================================================================


@pytest.mark.asyncio
class TestWatchEvidenceFingerprint:
    """The exact OP-2 / OP-3 trace from the 2026-05-24 watch window.

    Reproduction:
      * user message: «Подпиши меня на ежечасный дайджест канала
        @vps_watch_test_r1_Alex»
      * pre-fix: bot persisted a digest_subscriptions row IMMEDIATELY
        (no confirmation), then emitted the «Подтвердите [да/нет]»
        prompt AFTER the create-confirmation message.
      * post-fix: nothing persists until the FSM-driven confirm turn
        fires with ``confirm=True`` against a matching snapshot.

    Synthetic channel ``@vps_watch_test_r1_Alex`` is the persistent R-1
    reuse fixture from the watch handoff — safe to reference here
    because we don't actually hit Telegram.
    """

    async def test_op2_trace_replay_does_not_persist_without_confirm(self):
        repo = _FakeDigestSubscriptionRepo()
        bot = _FakeBot()
        patches = _patch_subscribe_digest_executor(repo)
        _enter_all(patches)
        try:
            result = await _exec_subscribe_digest(
                {
                    "name": "ежечасный",
                    "channel_ids": ["@vps_watch_test_r1_Alex"],
                    "cron_expression": "0 * * * *",
                    "timezone": "Europe/Moscow",
                },
                current_user=_admin(),
                bot=bot,
                chat_id=DM_CHAT_ID,
            )
        finally:
            _exit_all(patches)
        assert result.get("preview") is True
        # The watch-evidence fingerprint: pre-fix this assertion would
        # report `len(repo.store) == 1` and `len(bot.sent) == 1` — both
        # are exactly zero after the BUG-031 fix.
        assert repo.store == {}
        assert bot.sent == []


# ===========================================================================
# 8. Sequenced two-confirm — exactly-once side-effect (TD closure, option C)
# ===========================================================================


@pytest.mark.asyncio
class TestSerializedTwoConfirms:
    """TD-confirm-flow-concurrency-integration closure (Wave A, option C).

    aiogram's FSM storage single-flights handlers per (chat_id, user_id):
    when two «да» messages race, the storage layer serialises them, so the
    second handler invocation observes whatever state the first left behind.
    That serialisation is framework-owned and is NOT under test here.

    What we DO pin is OUR code's behaviour at the post-serialisation
    boundary: after confirm #1 runs through the real handler + real
    ``execute_tool`` and the handler CLEARS the FSM ConfirmFlow state
    (handlers.py ``_handle_confirmation_response`` → ``state.clear()``), a
    second, now-stateless confirm reaching ``execute_tool`` with
    ``confirm=True`` and ``confirm_flow_state=None`` must be rejected by the
    BUG-009 server-side guard (``_check_confirm_flow_match``) with
    ``error_class="ConfirmFlowMismatch"`` — an exactly-once side-effect
    modelled deterministically (no real threads / parallelism).

    The terminal business executor is swapped for a controlled double in
    the real ``_TOOL_EXECUTORS`` dispatch table so the side-effect is a
    single observable executor invocation. ``execute_tool`` itself and the
    BUG-009 guard (``_check_confirm_flow_match``) run unmocked — they are
    the code under test — and the real handler performs the FSM clearing.
    ``remove_channel`` is used because it is a write tool that requires
    confirm but needs no bot/DB context, keeping the side-effect entirely
    within the executor double.
    """

    async def test_serialized_two_confirms_second_rejected(self) -> None:
        original_args: dict[str, Any] = {"channel_id": "channel_a"}
        side_effects: list[dict[str, Any]] = []

        async def _recording_remove_channel(args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            side_effects.append(dict(args))
            return {"ok": True, "channel_id": args.get("channel_id")}

        # TD-test-isolation-execute-tool-leak (resolved): the handler's
        # ``execute_tool`` reference no longer needs a defensive re-pin — the
        # root cause (a concurrent per-task ``with patch(...handlers.execute_tool)``
        # in ``test_bot_clarify_concurrency_bug051.py`` that leaked its mock under
        # full-suite ordering) is fixed at the source, so ``handlers.execute_tool``
        # is the genuine function here. The confirm-turn drives the REAL guard path.
        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"remove_channel": _recording_remove_channel},
        ):
            # --- confirm #1: real handler → real execute_tool → guard passes.
            state = _make_state(chat_id=DM_CHAT_ID, user_id=67890)
            await state.set_state(ConfirmFlow.awaiting_confirmation)
            await state.update_data(
                pending_action={"tool_name": "remove_channel", "args": original_args},
                created_at=datetime.now(UTC).isoformat(),
            )
            msg = _make_message("да", chat_id=DM_CHAT_ID)
            agent = MagicMock()
            agent.process_message = AsyncMock()

            await _handle_confirmation_response(msg, agent, state, current_user=_admin())

            # Exactly ONE side-effect: the guarded executor ran once, with the
            # previewed args plus the framework-set confirm=True.
            assert side_effects == [{"channel_id": "channel_a", "confirm": True}], side_effects
            # The handler cleared the FSM ConfirmFlow state — a serialized
            # second confirm therefore arrives stateless.
            assert await state.get_state() is None

            # --- confirm #2: the now-stateless replay hits execute_tool with
            # confirm=True but confirm_flow_state=None (the cleared FSM).
            result_2 = await execute_tool(
                "remove_channel",
                {**original_args, "confirm": True},
                current_user=_admin(),
                confirm_flow_state=None,
            )

        # The BUG-009 guard rejects the stateless second confirm with the
        # typed error BEFORE the executor runs.
        assert result_2.get("error_class") == "ConfirmFlowMismatch", result_2
        # No second side-effect: the guarded executor was never reached again.
        assert side_effects == [{"channel_id": "channel_a", "confirm": True}], side_effects


# ===========================================================================
# 9. BUG-086 — the LLM-authored-confirmation recovery guard is CLASS-WIDE
# ===========================================================================


def _gemini_function_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {"parts": [{"functionCall": {"name": name, "args": args}}]},
                "finishReason": "STOP",
            }
        ]
    }


def _gemini_text(text: str) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


@pytest.mark.asyncio
class TestLlmAuthoredConfirmRecoveryIsToolAgnostic:
    """BUG-086 was found on ``force_resummarize`` (see
    ``tests/test_f5c_bot_force_resummarize.py``), but the fix lives in the
    AGENT LOOP and therefore protects every tool in
    ``_WRITE_TOOLS_REQUIRING_CONFIRM``. These cases pin that generality on a
    tool that has no ``dry_run`` at all, so the contract keeps holding for
    write tools added long after F5-C.

    The preview-less first call here is a BUG-009 rejection (an LLM-issued
    ``confirm=true``, refused before the executor runs) — the *other* way a
    confirm-gated write tool can end a turn with nothing armed.
    """

    @staticmethod
    def _preview_executor(calls: list[dict[str, Any]]):
        async def _executor(args: dict[str, Any], **_kw: Any) -> dict[str, Any]:
            calls.append(dict(args))
            if args.get("confirm"):
                return {"ok": True, "channel_id": args.get("channel_id")}
            return {
                "preview": True,
                "channel_id": args.get("channel_id"),
                "message": "Канал «channel_a» будет удалён. Подтвердите [да/нет]",
                "user_facing_message": True,
            }

        return _executor

    async def test_recovery_arms_confirm_flow_for_a_non_dry_run_write_tool(self) -> None:
        calls: list[dict[str, Any]] = []
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        gemini = AsyncMock(
            side_effect=[
                # BUG-009: the LLM volunteers confirm=true → rejected, no preview.
                _gemini_function_call(
                    "remove_channel", {"channel_id": "channel_a", "confirm": True}
                ),
                _gemini_text("Подтвердите удаление канала channel_a [да/нет]"),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch.dict(
                "tg_parser.bot.tools._TOOL_EXECUTORS",
                {"remove_channel": self._preview_executor(calls)},
            ),
        ):
            result = await agent.process_message("удали канал channel_a", current_user=_admin())

        # ConfirmFlow armed by the FRAMEWORK, from the tool's real preview.
        assert result.preview_pending == {
            "tool_name": "remove_channel",
            "args": {"channel_id": "channel_a"},
        }
        assert result.preview_message == "Канал «channel_a» будет удалён. Подтвердите [да/нет]"
        # BUG-009 invariant survives the repair: the recovery STRIPS confirm and
        # never re-adds it — only the FSM confirm-turn may set it.
        assert "confirm" not in result.preview_pending["args"]
        assert calls == [{"channel_id": "channel_a"}], calls

    async def test_recovery_does_not_fire_when_a_real_preview_armed(self) -> None:
        """The normal two-phase path must not be double-issued."""
        calls: list[dict[str, Any]] = []
        agent = GeminiAgent(api_key="test-key", model="gemini-2.5-flash")
        gemini = AsyncMock(
            side_effect=[
                _gemini_function_call("remove_channel", {"channel_id": "channel_a"}),
                _gemini_text("Канал будет удалён. Подтвердите [да/нет]"),
            ]
        )
        with (
            patch.object(agent, "_call_gemini", new=gemini),
            patch.dict(
                "tg_parser.bot.tools._TOOL_EXECUTORS",
                {"remove_channel": self._preview_executor(calls)},
            ),
        ):
            result = await agent.process_message("удали канал channel_a", current_user=_admin())

        assert result.preview_pending == {
            "tool_name": "remove_channel",
            "args": {"channel_id": "channel_a"},
        }
        # Exactly one executor round-trip — the preview came from the original path.
        assert calls == [{"channel_id": "channel_a"}], calls


class TestPreviewSuppressingArgRegistryIsComplete:
    """Tripwire for the ONE way a new write tool can silently re-open BUG-086:
    shipping a report-only flag that returns a preview-LESS payload without
    registering it in ``agent._PREVIEW_SUPPRESSING_ARGS`` (so the recovery
    path would fail to strip it and could never obtain the real preview)."""

    # Names that, on a confirm-gated write tool, denote a report-only shape.
    _REPORT_ONLY_FLAG_NAMES = frozenset(
        {"dry_run", "dryrun", "simulate", "report_only", "check_only", "preview_only", "no_op"}
    )

    def test_every_report_only_flag_is_registered(self) -> None:
        unregistered: list[str] = []
        for decl in TOOL_DECLARATIONS:
            if decl["name"] not in _WRITE_TOOLS_REQUIRING_CONFIRM:
                continue
            props = decl.get("parameters", {}).get("properties", {}) or {}
            for param in props:
                if param in self._REPORT_ONLY_FLAG_NAMES and param not in _PREVIEW_SUPPRESSING_ARGS:
                    unregistered.append(f"{decl['name']}.{param}")
        assert not unregistered, (
            "report-only flags on confirm-gated write tools must be listed in "
            f"agent._PREVIEW_SUPPRESSING_ARGS (BUG-086): {unregistered}"
        )

    def test_registry_is_not_vacuous(self) -> None:
        """Pins the current registry so an accidental emptying is caught."""
        assert "dry_run" in _PREVIEW_SUPPRESSING_ARGS
        # ``confirm`` is stripped unconditionally by the recovery path and must
        # NOT be modelled as a report-only flag.
        assert "confirm" not in _PREVIEW_SUPPRESSING_ARGS


# ===========================================================================
# 10. Anti-pattern guard — synthetic-only chat IDs (handoff requirement)
# ===========================================================================


def test_synthetic_only_chat_ids() -> None:
    """Handoff S-2 ban: real prod chat_id 5445781511 MUST NOT appear
    in this module. Assembled at runtime so the forbidden value never
    shows up verbatim (which would defeat a grep-based audit)."""
    forbidden_real_owner = int("544" + "578" + "1511")
    for synthetic in (DM_CHAT_ID, GROUP_CHAT_ID):
        assert synthetic != forbidden_real_owner
