"""Strict cron → human-readable schedule label, i18n (ru / en).

A UX follow-up to BUG-042: digest subscriptions accept FREE-FORM 5-field
cron expressions (validated only by APScheduler's
``CronTrigger.from_crontab`` — no preset allowlist), so the only safe way to
add a human-readable schedule label is to describe a small set of *common*
digest patterns CONFIDENTLY and return ``None`` for everything else. The
caller then falls back to the verbatim ``<code>{cron}</code>`` render, which
preserves the BUG-042 fidelity guarantee for arbitrary / exotic crons.

Strictness is the whole point: this is NOT a general cron describer. Anything
with steps (``*/15``), ranges (``9-18``), lists (``0,30``), a non-wildcard
day-of-month / month, or an otherwise unrecognized shape yields ``None`` —
better a raw cron than a confidently-wrong sentence.

The label language is parameterized. Two locales ship today (``ru`` / ``en``);
adding a third is a single ``_LOCALES`` entry (templates + weekday names). An
unknown / ``None`` ``lang`` falls back to :data:`_DEFAULT_LANG`.

Pure, dependency-free, and unit-testable in isolation.
"""

from __future__ import annotations

from typing import Any

# Default label language when the requested one is unknown / None. The bot UX
# is Russian-first, so ``ru`` is the safe default.
_DEFAULT_LANG = "ru"

# Per-language phrasing. Each entry carries:
#   * three ``str.format`` templates (``hourly`` uses ``{mm}``; ``daily`` uses
#     ``{hh}``/``{mm}``; ``weekly`` uses ``{day}``/``{hh}``/``{mm}``), and
#   * ``weekdays``: index = cron day-of-week 0..6 (Sunday-first; cron ``7``
#     aliases ``0`` via ``% 7``), in the form the ``weekly`` template expects
#     (plural so «по понедельникам» / "on Mondays" read naturally).
# Adding a 3rd language = one more entry here; no code changes.
_LOCALES: dict[str, dict[str, Any]] = {
    "ru": {
        "hourly": "ежечасно в :{mm}",
        "daily": "ежедневно в {hh}:{mm}",
        "weekly": "еженедельно по {day} в {hh}:{mm}",
        "weekdays": [
            "воскресеньям",
            "понедельникам",
            "вторникам",
            "средам",
            "четвергам",
            "пятницам",
            "субботам",
        ],
    },
    "en": {
        "hourly": "hourly at :{mm}",
        "daily": "daily at {hh}:{mm}",
        "weekly": "weekly on {day} at {hh}:{mm}",
        "weekdays": [
            "Sundays",
            "Mondays",
            "Tuesdays",
            "Wednesdays",
            "Thursdays",
            "Fridays",
            "Saturdays",
        ],
    },
}


def _pure_int(field: str, lo: int, hi: int) -> int | None:
    """Return the int value of ``field`` IFF it is a bare decimal in range.

    Strict by construction: ``str.isdigit()`` rejects wildcards (``*``), steps
    (``*/15``), ranges (``9-18``), lists (``0,30``) and signs — exactly the
    forms we must NOT try to describe.
    """
    if not field.isdigit():
        return None
    value = int(field)
    if lo <= value <= hi:
        return value
    return None


def _resolve_locale(lang: str | None) -> dict[str, Any]:
    """Return the locale table for ``lang`` (case-insensitive), or the default.

    Never raises — an unknown / ``None`` ``lang`` falls back to
    :data:`_DEFAULT_LANG` so a bad language code can't wedge a message render.
    """
    key = (lang or "").strip().lower()
    return _LOCALES.get(key) or _LOCALES[_DEFAULT_LANG]


def cron_to_human(
    cron_expression: str,
    timezone: str,
    lang: str | None = _DEFAULT_LANG,
) -> str | None:
    """Map a common digest cron pattern to a natural-language label, or ``None``.

    Supported (5-field ``m h dom mon dow``; ``dom``/``mon`` must be ``*``):

    * ``M * * * *``  → hourly        («ежечасно в :MM» / "hourly at :MM")
    * ``M H * * *``  → daily         («ежедневно в HH:MM» / "daily at HH:MM")
    * ``M H * * D``  → weekly        (D single 0–7; 0/7 = Sunday)

    ``HH``/``MM`` are zero-padded. The ``timezone`` (IANA string, as supplied)
    is appended in parentheses, e.g. «ежедневно в 09:00 (Europe/Moscow)» /
    "daily at 09:00 (Europe/Moscow)". ``lang`` selects the locale (``ru`` /
    ``en`` today); unknown / ``None`` falls back to :data:`_DEFAULT_LANG`.

    Returns ``None`` for any input that is not one of the patterns above so
    the caller renders the raw cron (free-form-safe, BUG-042 fidelity).
    """
    if not isinstance(cron_expression, str):
        return None
    loc = _resolve_locale(lang)
    parts = cron_expression.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, mon, dow = parts

    # Every supported pattern is day-of-month / month agnostic.
    if dom != "*" or mon != "*":
        return None

    m = _pure_int(minute, 0, 59)
    if m is None:
        return None

    tz_suffix = f" ({timezone})" if timezone else ""

    # Hourly: M * * * * (minute fixed, every hour, every day).
    if hour == "*" and dow == "*":
        return loc["hourly"].format(mm=f"{m:02d}") + tz_suffix

    h = _pure_int(hour, 0, 23)
    if h is None:
        return None

    # Daily: M H * * *
    if dow == "*":
        return loc["daily"].format(hh=f"{h:02d}", mm=f"{m:02d}") + tz_suffix

    # Weekly: M H * * D (single day-of-week; cron 7 aliases 0 = Sunday).
    d = _pure_int(dow, 0, 7)
    if d is None:
        return None
    day = loc["weekdays"][d % 7]
    return loc["weekly"].format(day=day, hh=f"{h:02d}", mm=f"{m:02d}") + tz_suffix
