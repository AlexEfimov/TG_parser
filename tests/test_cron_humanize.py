"""Tests for the strict cron→human schedule label, i18n (UX follow-up to BUG-042).

A human-readable schedule label is shown ALONGSIDE the verbatim cron in the
digest preview / creation messages for a small set of common patterns;
arbitrary / unrecognized crons fall back to the raw ``<code>cron</code>`` only
(free-form-safe, BUG-042 fidelity preserved). The label is localized — ``ru``
and ``en`` ship today; the digest's own ``language`` selects which.

The message-level test (`test_preview_shows_human_label_and_verbatim_cron`)
is written to FAIL on pre-fix HEAD `10f0d9d` (the preview then showed only the
raw cron / `_format_schedule_phrase` did not exist) and PASS after the fix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import _exec_subscribe_digest, _format_schedule_phrase
from tg_parser.utils.cron_humanize import cron_to_human

TZ = "Europe/Moscow"


def _admin() -> CurrentUser:
    return CurrentUser(
        id="u-cron",
        name="cron",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


class TestCronToHumanRu:
    @pytest.mark.parametrize(
        ("cron", "expected"),
        [
            ("0 * * * *", "ежечасно в :00 (Europe/Moscow)"),
            ("5 * * * *", "ежечасно в :05 (Europe/Moscow)"),
            ("30 * * * *", "ежечасно в :30 (Europe/Moscow)"),
            ("59 * * * *", "ежечасно в :59 (Europe/Moscow)"),
            ("0 9 * * *", "ежедневно в 09:00 (Europe/Moscow)"),
            ("0 21 * * *", "ежедневно в 21:00 (Europe/Moscow)"),
            ("5 9 * * *", "ежедневно в 09:05 (Europe/Moscow)"),
            ("0 0 * * *", "ежедневно в 00:00 (Europe/Moscow)"),
            ("0 9 * * 1", "еженедельно по понедельникам в 09:00 (Europe/Moscow)"),
            ("0 9 * * 0", "еженедельно по воскресеньям в 09:00 (Europe/Moscow)"),
            ("0 9 * * 7", "еженедельно по воскресеньям в 09:00 (Europe/Moscow)"),
            ("30 18 * * 5", "еженедельно по пятницам в 18:30 (Europe/Moscow)"),
            ("0 9 * * 6", "еженедельно по субботам в 09:00 (Europe/Moscow)"),
        ],
    )
    def test_supported_patterns_ru(self, cron: str, expected: str):
        assert cron_to_human(cron, TZ, "ru") == expected


class TestCronToHumanEn:
    @pytest.mark.parametrize(
        ("cron", "expected"),
        [
            ("0 * * * *", "hourly at :00 (Europe/Moscow)"),
            ("5 * * * *", "hourly at :05 (Europe/Moscow)"),
            ("30 * * * *", "hourly at :30 (Europe/Moscow)"),
            ("0 9 * * *", "daily at 09:00 (Europe/Moscow)"),
            ("0 21 * * *", "daily at 21:00 (Europe/Moscow)"),
            ("5 9 * * *", "daily at 09:05 (Europe/Moscow)"),
            ("0 0 * * *", "daily at 00:00 (Europe/Moscow)"),
            ("0 9 * * 1", "weekly on Mondays at 09:00 (Europe/Moscow)"),
            ("0 9 * * 0", "weekly on Sundays at 09:00 (Europe/Moscow)"),
            ("0 9 * * 7", "weekly on Sundays at 09:00 (Europe/Moscow)"),
            ("30 18 * * 5", "weekly on Fridays at 18:30 (Europe/Moscow)"),
            ("0 9 * * 6", "weekly on Saturdays at 09:00 (Europe/Moscow)"),
        ],
    )
    def test_supported_patterns_en(self, cron: str, expected: str):
        assert cron_to_human(cron, TZ, "en") == expected


class TestCronToHumanUnsupportedAndLangFallback:
    @pytest.mark.parametrize(
        "cron",
        [
            "*/15 * * * *",  # step
            "0 9-18 * * *",  # range
            "0 9 * * 1-5",  # dow range
            "0,30 9 * * *",  # list
            "0 9 1 * *",  # day-of-month set
            "0 9 * 6 *",  # month set
            "0 9 * * 8",  # dow out of range
            "60 9 * * *",  # minute out of range
            "0 24 * * *",  # hour out of range
            "0 9 * *",  # too few fields
            "0 9 * * * *",  # too many fields
            "garbage",
            "",
        ],
    )
    @pytest.mark.parametrize("lang", ["ru", "en"])
    def test_unsupported_returns_none_any_lang(self, cron: str, lang: str):
        assert cron_to_human(cron, TZ, lang) is None

    def test_unknown_lang_falls_back_to_default_ru(self):
        # An unknown language code defers to the default (ru), never crashes.
        assert cron_to_human("0 9 * * *", TZ, "de") == "ежедневно в 09:00 (Europe/Moscow)"
        assert cron_to_human("0 9 * * *", TZ, "") == "ежедневно в 09:00 (Europe/Moscow)"

    def test_none_lang_falls_back_to_default_ru(self):
        assert cron_to_human("0 9 * * *", TZ, None) == "ежедневно в 09:00 (Europe/Moscow)"

    def test_lang_is_case_insensitive(self):
        assert cron_to_human("0 9 * * *", TZ, "EN") == "daily at 09:00 (Europe/Moscow)"

    def test_default_lang_is_ru(self):
        # Default arg (no lang) → ru.
        assert cron_to_human("0 9 * * *", TZ) == "ежедневно в 09:00 (Europe/Moscow)"

    def test_no_timezone_suffix_when_empty(self):
        assert cron_to_human("0 9 * * *", "", "en") == "daily at 09:00"

    def test_non_string_input_is_none(self):
        assert cron_to_human(None, TZ, "ru") is None  # type: ignore[arg-type]


class TestFormatSchedulePhrase:
    """The shared HTML phrase builder used by BOTH the preview and the
    deterministic creation-confirmation message."""

    def test_supported_ru_carries_label_and_verbatim_cron(self):
        out = _format_schedule_phrase("0 9 * * *", TZ, "ru")
        assert "ежедневно в 09:00 (Europe/Moscow)" in out
        assert "<code>0 9 * * *</code>" in out

    def test_supported_en_carries_label_and_verbatim_cron(self):
        out = _format_schedule_phrase("0 9 * * *", TZ, "en")
        assert "daily at 09:00 (Europe/Moscow)" in out
        assert "<code>0 9 * * *</code>" in out

    def test_unsupported_is_verbatim_only_legacy_form(self):
        out = _format_schedule_phrase("*/15 * * * *", TZ, "ru")
        # EXACTLY the legacy verbatim-only render — no human label, no regression.
        assert out == "<code>*/15 * * * *</code> (Europe/Moscow)"


@pytest.mark.asyncio
class TestScheduleLabelInDigestPreview:
    async def test_preview_shows_human_label_and_verbatim_cron(self):
        """The digest preview for `0 9 * * *` now contains the localized label
        (ru — the wired source defaults to 'ru') AND the verbatim cron. FAILS
        on pre-fix `10f0d9d` (raw cron only)."""
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ):
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["durov"],
                    "cron_expression": "0 9 * * *",
                    "timezone": TZ,
                },
                current_user=_admin(),
                bot=None,
                chat_id=12345,
            )
        msg = result["message"]
        assert "ежедневно в 09:00 (Europe/Moscow)" in msg
        assert "<code>0 9 * * *</code>" in msg

    async def test_preview_uses_digest_language_en(self):
        """The label language follows the digest's own ``language`` arg — an
        `en` digest renders the English label."""
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ):
            result = await _exec_subscribe_digest(
                {
                    "name": "morning",
                    "channel_ids": ["durov"],
                    "cron_expression": "0 9 * * *",
                    "timezone": TZ,
                    "language": "en",
                },
                current_user=_admin(),
                bot=None,
                chat_id=12345,
            )
        msg = result["message"]
        assert "daily at 09:00 (Europe/Moscow)" in msg
        assert "<code>0 9 * * *</code>" in msg

    async def test_preview_unsupported_cron_raw_only_no_label(self):
        """An unrecognized cron renders the raw `<code>cron</code>` only — no
        confidently-wrong label (no regression vs today)."""
        with patch(
            "tg_parser.bot.tools.verify_channel_exists",
            new=AsyncMock(return_value=None),
        ):
            result = await _exec_subscribe_digest(
                {
                    "name": "quarterly",
                    "channel_ids": ["durov"],
                    "cron_expression": "*/15 * * * *",
                    "timezone": TZ,
                },
                current_user=_admin(),
                bot=None,
                chat_id=12345,
            )
        msg = result["message"]
        assert "<code>*/15 * * * *</code>" in msg
        assert "ежечасно" not in msg
        assert "ежедневно" not in msg
        assert "еженедельно" not in msg
        assert "daily" not in msg
        assert "hourly" not in msg
        assert "weekly" not in msg
