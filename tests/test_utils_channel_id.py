"""Unit tests for the shared `normalize_channel_id` helper (Session F, BUG-003).

Covers the F-1 + F-8 scope from
``docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md``:

* Strip ``@`` prefix (BUG-003 root cause).
* Strip surrounding ``'`` / ``"`` quotes (2026-04-29 production
  observation: ``Удали канал 'test_channel'`` reached storage as
  literal quoted string).
* Whitespace handling, idempotency, ``None`` / empty-string edge
  cases.
"""

from __future__ import annotations

import pytest

from tg_parser.utils.channel_id import normalize_channel_id


class TestNormalizeChannelId:
    def test_strips_at_prefix(self) -> None:
        assert normalize_channel_id("@AgeManagement") == "AgeManagement"

    def test_keeps_unprefixed(self) -> None:
        assert normalize_channel_id("AgeManagement") == "AgeManagement"

    def test_strips_whitespace(self) -> None:
        assert normalize_channel_id("  Lab4health  ") == "Lab4health"

    def test_strips_single_quotes(self) -> None:
        # Direct regression on the 2026-04-29 production observation.
        assert normalize_channel_id("'test_channel'") == "test_channel"

    def test_strips_double_quotes(self) -> None:
        assert normalize_channel_id('"Lab4health"') == "Lab4health"

    def test_strips_quotes_then_at(self) -> None:
        assert normalize_channel_id('"@Lab4health"') == "Lab4health"

    def test_strips_at_inside_quotes(self) -> None:
        assert normalize_channel_id("'@Lab4health'") == "Lab4health"

    def test_preserves_mismatched_quotes(self) -> None:
        # `"foo'` — opening double + closing single is malformed; we leave
        # it for the caller to flag rather than silently accept.
        assert normalize_channel_id("\"foo'") == "\"foo'"

    def test_strips_whitespace_inside_quotes(self) -> None:
        assert normalize_channel_id("  '@Lab4health'  ") == "Lab4health"

    def test_handles_none(self) -> None:
        assert normalize_channel_id(None) is None

    def test_handles_empty_string(self) -> None:
        assert normalize_channel_id("") is None

    def test_handles_only_whitespace(self) -> None:
        assert normalize_channel_id("   ") is None

    def test_handles_only_at(self) -> None:
        assert normalize_channel_id("@") is None

    def test_handles_only_quotes(self) -> None:
        assert normalize_channel_id("''") is None
        assert normalize_channel_id('""') is None

    def test_handles_quoted_at_only(self) -> None:
        assert normalize_channel_id("'@'") is None

    def test_strips_multiple_at_signs(self) -> None:
        # `lstrip("@")` strips ALL leading @s — matches existing behaviour
        # of every replaced site (`str(x).lstrip("@")`).
        assert normalize_channel_id("@@channel") == "channel"

    def test_preserves_internal_at(self) -> None:
        # Only LEADING @ is stripped — internal @ (rare, but possible in
        # fictional usernames) must survive.
        assert normalize_channel_id("ch@nnel") == "ch@nnel"

    def test_preserves_case(self) -> None:
        # Capitalization is preserved — DB key is case-sensitive
        # (BUG-003 § H3 verdict).
        assert normalize_channel_id("@AgeManagement") == "AgeManagement"
        assert normalize_channel_id("AGEMANAGEMENT") == "AGEMANAGEMENT"

    @pytest.mark.parametrize(
        "value",
        [
            "@AgeManagement",
            "Lab4health",
            "  '@Lab4health'  ",
            "'test_channel'",
            '"@channel"',
            None,
            "",
            "@",
        ],
    )
    def test_idempotent(self, value: str | None) -> None:
        once = normalize_channel_id(value)
        twice = normalize_channel_id(once)
        assert once == twice

    def test_accepts_non_string_via_str_coercion(self) -> None:
        # A few legacy call-sites pass `str(args["channel_id"])` already,
        # but we accept stringifiable objects directly to avoid forcing
        # the boilerplate. Numeric IDs (rare for channels) round-trip.
        assert normalize_channel_id(123) == "123"  # type: ignore[arg-type]

    def test_strips_tab_and_newline_whitespace(self) -> None:
        # Python's ``str.strip()`` removes ``\t``/``\n``/``\r`` by default
        # — relied upon by Telegram chat clients that occasionally send
        # tab-padded text from clipboard pastes.
        assert normalize_channel_id("\tLab4health\n") == "Lab4health"
        assert normalize_channel_id("  \t@Lab4health \r\n") == "Lab4health"

    def test_strips_only_one_pair_of_quotes(self) -> None:
        # ``"'foo'"`` — outer double, inner single. We only peel one matching
        # pair; the inner quotes survive verbatim. This is intentional: a
        # double-quoted literal containing a single-quoted username should
        # surface as malformed rather than be silently unwrapped twice.
        assert normalize_channel_id("\"'foo'\"") == "'foo'"

    def test_handles_triple_at(self) -> None:
        # ``lstrip("@")`` strips ALL leading @s — preserves the existing
        # behaviour of every replaced site (``str(x).lstrip("@")``).
        assert normalize_channel_id("@@@channel") == "channel"
        assert normalize_channel_id("@@@@@") is None

    def test_quotes_with_inner_padding_kept(self) -> None:
        # ``"' foo '"`` — quotes with leading/trailing space INSIDE.
        # After stripping the matching pair the contents still have
        # surrounding whitespace which is then trimmed by the second
        # ``.strip()`` call. End result: the inner token without padding.
        assert normalize_channel_id("' foo '") == "foo"

    def test_padding_around_at_inside_quotes(self) -> None:
        """Self-review-2026-04-29: explicit regression for the bug found
        during Session F self-review. Previously the order ``peel-quote →
        lstrip(@)`` left the ``@`` in place because ``.lstrip("@")`` saw
        a leading space (revealed by quote-peel) instead of the ``@`` and
        bailed without stripping. Inputs like ``"' @ch '"`` returned
        ``"@ch"`` instead of ``"ch"`` and broke idempotency.

        The fix is a ``.strip()`` immediately after quote-peel so the
        ``@`` becomes the first character before ``.lstrip("@")`` runs.
        """
        assert normalize_channel_id("' @ch '") == "ch"
        assert normalize_channel_id('"  @Lab4health  "') == "Lab4health"

    def test_idempotent_extra_input_variants(self) -> None:
        # Defense-in-depth idempotency check on shapes seen in production
        # but not parametrized above.
        for raw in ("\t@ch \n", '"@ch"', "' @ch '", '"  @Lab4health  "'):
            once = normalize_channel_id(raw)
            twice = normalize_channel_id(once)
            assert once == twice, f"non-idempotent for {raw!r}: {once!r} -> {twice!r}"
