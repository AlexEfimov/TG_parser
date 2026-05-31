"""Tests for the strict cron→human schedule label, i18n (UX follow-up to BUG-042).

Reframed contract (items 1+2, 2026-05-31): for a small set of common patterns
the digest preview / creation messages show the localized friendly label as the
SOLE human-facing schedule representation (the raw cron is dropped once a
faithful label exists); arbitrary / unrecognized crons fall back to the verbatim
``<code>cron</code>`` only (free-form-safe, BUG-042 fidelity preserved in
reframed form — the schedule is never silently dropped or mangled). The label is
localized — ``ru`` and ``en`` ship today; the digest's own ``language`` selects
which.

The ``cron_to_human`` unit tests assert exact localized strings derived from
cron semantics + the agreed wording (correct-by-derivation, not change-detector
snapshots). The message-level tests are written to FAIL on pre-fix HEAD
``195589b`` (recognized crons then rendered «label — <code>cron</code>», and
pre-ENH-002 the helper/`_format_schedule_phrase` did not exist) and PASS after.
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
    deterministic creation-confirmation message.

    Reframed contract (items 1+2, 2026-05-31): recognized cron → friendly
    label ONLY (no raw cron); unrecognized cron → verbatim ``<code>cron</code>``
    only. The «label — cron» combo never appears.
    """

    def test_supported_ru_is_friendly_label_only(self):
        out = _format_schedule_phrase("0 9 * * *", TZ, "ru")
        assert out == "ежедневно в 09:00 (Europe/Moscow)"
        # The raw cron is DROPPED once a faithful label exists.
        assert "<code>" not in out
        assert "0 9 * * *" not in out

    def test_supported_en_is_friendly_label_only(self):
        out = _format_schedule_phrase("0 9 * * *", TZ, "en")
        assert out == "daily at 09:00 (Europe/Moscow)"
        assert "<code>" not in out
        assert "0 9 * * *" not in out

    def test_unsupported_is_verbatim_only_legacy_form(self):
        out = _format_schedule_phrase("*/15 * * * *", TZ, "ru")
        # Unrecognized → verbatim cron is the only faithful representation
        # (BUG-042 guarantee preserved in reframed form).
        assert out == "<code>*/15 * * * *</code> (Europe/Moscow)"


async def _preview(args: dict) -> dict:
    with patch(
        "tg_parser.bot.tools.verify_channel_exists",
        new=AsyncMock(return_value=None),
    ):
        return await _exec_subscribe_digest(
            args,
            current_user=_admin(),
            bot=None,
            chat_id=12345,
        )


@pytest.mark.asyncio
class TestScheduleLabelInDigestPreview:
    async def test_preview_recognized_cron_friendly_label_no_raw_cron(self):
        """Reframed contract (items 1+2): a recognized cron `0 9 * * *` renders
        the friendly label ONLY — the raw cron / `<code>` is GONE from the
        user-facing preview. FAILS on pre-fix `195589b` (which showed
        «label — <code>0 9 * * *</code>»)."""
        result = await _preview(
            {
                "name": "morning",
                "channel_ids": ["durov"],
                "cron_expression": "0 9 * * *",
                "timezone": TZ,
            }
        )
        msg = result["message"]
        assert "ежедневно в 09:00 (Europe/Moscow)" in msg
        assert "<code>" not in msg
        assert "0 9 * * *" not in msg

    async def test_preview_uses_digest_language_en(self):
        """The label language follows the digest's own ``language`` arg — an
        `en` digest renders the English label (and still no raw cron)."""
        result = await _preview(
            {
                "name": "morning",
                "channel_ids": ["durov"],
                "cron_expression": "0 9 * * *",
                "timezone": TZ,
                "language": "en",
            }
        )
        msg = result["message"]
        assert "daily at 09:00 (Europe/Moscow)" in msg
        assert "<code>" not in msg
        assert "0 9 * * *" not in msg

    async def test_preview_unsupported_cron_verbatim_only(self):
        """An unrecognized cron renders the verbatim `<code>cron</code>` only —
        the BUG-042 guarantee preserved in reframed form (never dropped)."""
        result = await _preview(
            {
                "name": "quarterly",
                "channel_ids": ["durov"],
                "cron_expression": "*/15 * * * *",
                "timezone": TZ,
            }
        )
        msg = result["message"]
        assert "<code>*/15 * * * *</code>" in msg
        for needle in ("ежечасно", "ежедневно", "еженедельно", "daily", "hourly", "weekly"):
            assert needle not in msg

    async def test_preview_names_the_target_channel(self):
        """Item-3: the preview NAMES the channel (not «1 канал(ов)»)."""
        result = await _preview(
            {
                "name": "morning",
                "channel_ids": ["durov"],
                "cron_expression": "0 9 * * *",
                "timezone": TZ,
            }
        )
        msg = result["message"]
        assert "канал durov" in msg
        assert "канал(ов)" not in msg

    async def test_preview_names_multiple_channels(self):
        """Item-3: multiple channels are listed by name with the plural «каналы»."""
        result = await _preview(
            {
                "name": "morning",
                "channel_ids": ["durov", "telegram"],
                "cron_expression": "0 9 * * *",
                "timezone": TZ,
            }
        )
        msg = result["message"]
        assert "каналы durov, telegram" in msg
        assert "канал(ов)" not in msg
